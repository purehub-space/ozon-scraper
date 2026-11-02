# Ozon 爬虫项目架构复盘、鲁棒性优化与运维排障手册

## 一、 上次执行耗时过长的深度复盘 (Post-Mortem)

在对情趣内衣等特殊品类的实际抓取过程中，主要耗时集中在**环境适配阻塞**、**18+成人弹窗拦截摸索**以及**两阶段串行探测**上。具体复盘如下：

### 1. 跨平台兼容性缺陷（硬编码阻塞）
- **根因**：原脚本（`ozon_search.py`、`ozon_detail.py`、`prepare_pool.py`）硬编码了 macOS 的 Chrome 绝对路径（`/Applications/Google Chrome.app/...`）。
- **影响**：在 Windows 系统上直接报错 `FileNotFoundError`，必须经历反复的进程探测与环境适配。

### 2. 代理穿透与网络通道割裂
- **根因**：本机俄罗斯 Ozon 买家端受网络环境限制（直连频繁超时或 403 挑战失败），需经过本地代理（如 `127.0.0.1:7897`）。
- **影响**：原代码起的 Chrome 无头进程未挂载 `--proxy-server`，导致预热时 WebSocket 与页面长久卡死在加载等待，消耗大量排查时间。

### 3. 18+ 成人类目（Adult-Gate）的前端微前端拦截
- **根因**：情趣内衣核心类目（`/category/eroticheskoe-bele-i-kostyumy-9015/`）触发了 Ozon 强制的成年认证（`userAdultModal` 弹窗）。在此状态下，服务端的 `entrypoint-api` 页面响应**完全不返回**商品网格（`tileGridDesktop`），只下发弹窗组件。
- **影响**：排查为什么 API 只有 2KB 响应且无任何商品卡片耗费了数轮探索；最终通过 CDP 模拟输入出生日期（如 `01.01.1990`）确认或通过款式核心搜索词绕过。

### 4. 数据架构的「两阶段」非对称性
- **根因**：Ozon 搜索列表/类目页（`searchResultsV2`）仅包含 SKU 标题、价格、评分、评价数，**不包含店铺 ID（sellerId）和店铺历史单量（Заказы）**。
- **影响**：要获取头部店铺和实际售卖单量，必须走二次请求——提取每个 SKU 的商品详情微前端数据（PDP 中的 `webCurrentSeller` 组件）。上轮采用串行逐个验证耗时较长。

---

## 二、 修复方案与代码增强

针对上述痛点，已完成系统级修复：

1. **新增跨平台与代理自适应环境模块 (`ozon_env.py`)**：
   - 自动探测 Windows、macOS、Linux 下的 Chrome / Edge 路径；
   - 自动探测本机常用代理端口（7897 / 7890 等）及系统代理环境变量。
2. **修复核心脚本 (`ozon_search.py` & `ozon_detail.py`)**：
   - 消除硬编码，支持代理参数透传至 CDP 浏览器与 `curl_cffi`；
   - 延长 Cookie 缓存 TTL 至 6 小时，减少无意义的浏览器冷启动。
3. **沉淀全流程自动化综合采集工具 (`ozon_collector.py`)**：
   - 自动执行「CDP 预热 -> 自动解决 18+ 认证 -> 纯 HTTP 高并发搜索 -> 自动聚合 PDP 店铺与单量」全链路；
   - 完整合并最新**库存通道**（列表页 tile `stock_max` 100% 覆盖提取 + PDP `bigPromoPDP` 促销库存）与**评论通道**（`reviewsVariantMode=2` + 星级排序 `score_asc/score_desc/usefulness_desc` 真翻页）；
   - 输出结构化 JSON 报表（店铺名、ID、单量徽标、数字单量、好评率、可用库存上限、评论列表、关联 SKU）。

---

## 三、 最新库存与评论通道技术指南 (Inventory & Reviews Channel)

### 1. 最新库存通道（100% 覆盖）
- **列表页 Tile 直接提取 (`stock_max`)**：
  - 核心路径：`multiButton.ozonButton.addToCart.quantityButton.maxItems`（兼容 `mainState.quantityButton.maxItems`）；
  - 特性：**无需加购**，翻列表页直接返回全类目在售 SKU 真实库存上限（平台硬顶 2000）；
  - 已覆盖脚本：`ozon_http.py`、`ozon_search.py`、`ozon_collector.py`、`ozon_browser.py`。
- **详情页促销库存 (`bigPromoPDP`)**：
  - 提取 `stockNumber`（如 `"172 шт."`）与 `counter.percentage`（已售比例，如 `81%`）；
  - 已覆盖脚本：`ozon_detail.py`、`ozon_collector.py`、`ozon_browser.py`。
- **购物车精确认证 (`cartSplit.quantity.maximum`)**：
  - 走 `POST _action/addToCart` 后查验，适合重点单品可购性验证；
  - 已覆盖脚本：`ozon_browser.py --stock-batch`。

### 2. 最新评论通道（真翻页 + 星级排序）
- **请求端点**：
  `GET /api/entrypoint-api.bx/page/json/v2?url=/product/<sku>/reviews/?reviewsVariantMode=2&sort=<sort>&page=<page>`
- **关键参数与能力**：
  - `reviewsVariantMode=2`：必须携带，服务端下发完整结构化微前端响应；
  - `sort=score_asc`：**核心差评筛选**（实测直接按 1 星在前排序，适合选品排雷与差评分析）；
  - `sort=score_desc`：好评优先；
  - `sort=usefulness_desc`：最有价值/点赞最多评论优先；
  - `page=N`：真翻页无重叠（实测 P1/P2/P3 零数据重复）。
- **字段提取**：
  `content.score` (1-5星级)、`content.comment` (主评)、`content.positive` (优点)、`content.negative` (缺点)、`content.photos` (图集链接)、`publishedAt` (发布时间)、`author` (买家名)、`usefulness.likeCount` (有用点赞)。
- **已覆盖脚本**：
  - `ozon_collector.py --reviews 2 --sort score_asc`
  - `ozon_detail.py --reviews 2 --sort score_asc`
  - `ozon_browser.py --with-reviews --review-sort score_asc --review-pages 2`

---

## 四、 日常运维与快速排障手册 (Cheatsheet)

### 1. 快速执行采集
```bash
# 激活 python 环境 (需安装 curl_cffi 和 websocket-client)
# 一站式采集：关键词搜索 + 批量库存 + 店铺/单量 + 差评分析
python ozon_collector.py --keyword "пеньюар кружевной" --pages 2 --threads 8 --reviews 1 --sort score_asc --out result.json

# 直接指定一批 SKU 采集详情、库存与好评
python ozon_collector.py --sku 5081332378 --sku 5527434733 --reviews 2 --sort score_desc --out result.json

# 纯 HTTP 批量类目抓取（带 stock_max 库存）
python ozon_http.py --url "/category/igrushki-antistress-7181/?page=1" --pages 1-3 --out out_cat

# 详情抓取 + 评论差评翻页
python ozon_detail.py --skus 5081332378,5527434733 --reviews 2 --sort score_asc --out out_detail
```

### 2. 常见故障排查表

| 故障现象 | 根因定位 | 快速处置方案 |
| :--- | :--- | :--- |
| **`FileNotFoundError: Chrome not found`** | 操作系统未安装标准路径 Chrome / Edge | 检查 `ozon_env.py` 中的 `CHROME_CANDIDATES`，补充实际安装路径 |
| **预热卡住 / `TimeoutError`** | 代理未启动或直连 Ozon 超时 | 确保 Clash Verge 处于运行状态（默认侦听 7897），或配置 `HTTP_PROXY` |
| **API 返回 403 `fab_chlg`** | 缓存 Cookie 失效或 TLS 指纹不对 | 1) 删掉 `~/.cache/ozon-search/` 下失效 JSON<br>2) 确保使用 `curl_cffi` 的 `impersonate="chrome124"` |
| **搜索返回 0 个商品卡片** | 命中了 18+ 成人类目弹窗拦截 | 1) 在 `ozon_collector.py` 开启 `is_adult=True`<br>2) 换用细分品类词（如 `боди эротическое` 代替宽泛词） |
| **单量为 None** | 店铺为新店或单量 < 1,000 | 检查 `webCurrentSeller` 的 `trustFactors`，低于 1000 单的店铺平台不展示单量徽标 |
