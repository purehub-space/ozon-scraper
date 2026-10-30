# Ozon 买家端采集器

<p>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/TLS-curl__cffi%20chrome%20impersonate-success" alt="tls">
  <img src="https://img.shields.io/badge/browser-not%20required-brightgreen" alt="no browser">
  <img src="https://img.shields.io/badge/RAM-~50MB-lightgrey" alt="memory">
  <img src="https://img.shields.io/badge/throughput-up%20to%2063%20SKU%2Fs-orange" alt="throughput">
  <img src="https://img.shields.io/badge/coverage-store%20%7C%20keyword%20%7C%20image%20%7C%20detail-blueviolet" alt="coverage">
</p>

![demo](assets/demo.gif)

免登录抓取 Ozon 前台：店铺、类目、关键词搜索、以图搜同款、SKU 详情。

纯 Python HTTP（curl_cffi 伪装 TLS），内存 ~50MB，不需要常驻浏览器。

## 装依赖

```bash
pip3 install --user curl_cffi websocket-client
```

（`websocket-client` 只在需要静默预热 cookie 时用到；有现成 cookie 可以不装）

## 四个脚本

| 脚本 | 用途 | 输入 | 吞吐 |
|---|---|---|---|
| `ozon_http.py` | 店铺 / 类目全量列表 | seller 或 category URL | 34.5 → **193 SKU/s** |
| `ozon_search.py` | 关键词全量（自动转类目 + 预热） | 关键词或 /search/ URL | 37.5 → **179 SKU/s** |
| `ozon_image.py` | 以图搜同款 | 本地图片 或 图片 URL | 63 → **211 SKU/s** |
| `ozon_detail.py` | SKU 详情 + 评论 | skus.txt | 4.4 → **18.6 SKU/s** |

（后者为加 `--pool 4` 的实测值；四个脚本都支持 `--pool N` 和 `--browser chrome`）

## 快速开始

```bash
# 1) 打一家店
python3 ozon_http.py --url "https://www.ozon.ru/seller/78486/" --out out_shop

# 2) 抓一个关键词
python3 ozon_search.py --kw "сквиш" --out out_kw --threads 24

# 3) 以图搜同款（URL 直接透传，不用下载图）
python3 ozon_image.py --url "https://ir-20.ozonstatic.cn/s3/multimedia-1-e/7401951734.jpg" \
    --out out_img --threads 6

# 4) 抓详情（吃上面任一脚本的 skus.txt）
python3 ozon_detail.py --skus out_kw/skus.txt --out out_detail --reviews 1

# 5) 转 CSV
python3 to-csv.py out_detail
```

## 产物

所有脚本统一输出：

| 文件 | 内容 |
|---|---|
| `skus.txt` | 纯 SKU ID，一行一个 |
| `products.jsonl` | sku/标题/图片/价格/原价/折扣/评分/评价数/库存提示/广告位标记/页码 |
| `run.log` | 每次请求的状态、耗时、失败原因 |
| `progress.json` | 进度（中断后能看到跑到哪） |

`ozon_detail.py` 输出 `details.jsonl`：价格三档/变体矩阵/图集/视频/短特征/全量属性/描述 HTML/话题标签/卖家/类目路径/评论。

## 一条链跑完

```bash
# 池 4 + 详情前 200 + 列表全量（默认）
bash examples/run_all.sh "сквиш"

# 池 4 + 详情 500 + 只抓前 300 页
bash examples/run_all.sh "сквиш" 4 500 1-300
```

跑完直接给你价格分位、广告位占比、有评价的款数：

```
▶ 4/4  汇总（价格分布）
  SKU 732 个，有价 732 个
  价格  P10 153 / 中位 256 / P90 590 ₽
  区间  60 ~ 5655 ₽
  广告位 666/732
  评价>100 的款 487 个
  完成，用时 14 秒
```

## 三种拿 cookie 的方式

| 方式 | 开窗口 | 耗时 | 会话数 | 吞吐 |
|---|---|---|---|---|
| **`--browser chrome`**（读现有浏览器） | **0（完全后台）** | ~10 s（读+校验） | 1 | 62~81 SKU/s |
| **`--pool 4`（预热 headless）** | **0（headless，完全无窗口）** | 8 s | 4 | **210~300 SKU/s** |
| 不加（无 cookie） | 0 | 0 | 0 | 只能抓 page 2+ |

### 方式一：直接读本机浏览器（零窗口，推荐日常用）

```bash
python3 cookie_from_browser.py --check          # 看哪个浏览器有可用 cookie
python3 cookie_from_browser.py                  # 读 Chrome + 校验 + 存缓存

# 之后采集直接加 --browser
python3 ozon_image.py --url "<图片URL>" --out out_img --browser chrome
python3 ozon_http.py  --url "<店铺URL>"  --out out_shop --browser chrome
```

原理：Chrome 的 cookie 存在本地 SQLite（Keychain 加密），`browser_cookie3` 读出来解密，
里面就有 Ozon 要的 `abt_data` + `__Secure-ETC`。**不启动任何浏览器进程。**

前提：这个浏览器访问过 `www.ozon.ru`（走过一次 antibot challenge）。

实测你机器上 Chrome 有 42 个 ozon cookie，校验直通：
```
seller 200 / pdp 200 / list p1 200 / list p2 200 / 图搜结果 200
```

### 方式二：预热无痕会话池（要吞吐时用）

见下一节。

## 多 cookie 池（提速 4 倍）

单个 cookie 的并发甜点约 24 线程（66 SKU/s），超过 40 线程直接崩（4 SKU/s）。
但 **N 个独立 cookie 各自限速**，吞吐近似线性叠加：

```bash
# 一次预热 4 个无痕会话（窗口都在屏幕外，8 秒）
python3 prepare_pool.py --n 4

# 采集时加 --pool 4，线程数自动变成 4×16=64
python3 ozon_image.py --url "<图片URL>" --out out_img --pool 4
python3 ozon_http.py  --url "<店铺或类目URL>" --out out_shop --pool 4
```

池默认用 **headless**（完全无窗口）。headless 被识别只有两个破绽：UA 带 `HeadlessChrome`、
`screen` 默认 800×600 —— 都在 `prepare_pool.py` 里补掉了（真实 UA + `Emulation.setDeviceMetricsOverride`）。
要回退有头模式加 `--headful`。

实测（4 cookie × 16 并发 = 64 线程，headless 池）：

| 场景 | 单 cookie | 4 cookie 池 |
|---|---|---|
| 图搜 60 页 / 720 SKU | 63 SKU/s | **211 SKU/s** |
| 类目 300 页 | 34.5 SKU/s | **299 SKU/s，300/300 成功（100%）** |

每个 cookie 大约 100~150 页的新鲜额度，用完后转 403；`pool_client.py` 会在 403 累积到 30 次时
**自动重新预热补池**（约 8 秒），采集不中断。

```bash
python3 prepare_pool.py --list      # 看池状态（数量 / 年龄）
python3 prepare_pool.py --n 4 --force   # 强制重来
```

## 必读

- **`docs/ANTI-BOT.md`** — 为什么必须用 curl_cffi、cookie 从哪来、预热机制
- **`docs/API.md`** — 所有端点、参数、每页条数、页数上限
- **`docs/PITFALLS.md`** — 踩过的坑（死锁、multipart、cookie 排序…）
- **`docs/DATA-FIELDS.md`** — 前台能查到哪些字段（含店铺主体 ОГРН）
- **`docs/BENCHMARKS.md`** — 实测吞吐与耗时

## 已知硬限制

| 限制 | 数值 |
|---|---|
| 列表每页 | 8 条 |
| 图搜每页 | 12 条 |
| 评论每页 | 30 条 |
| 列表翻页上限 | 1,250 页 = **9,999 个商品** |
| 图搜翻页上限 | 约 450 页（每次不同） |
| 图搜图片大小 | ≤ 4MB，JPEG/PNG/WEBP/PDF |
| `/search/` 直接打 API | 无 cookie 时 page 1 恒定 403 |

## 目录

```
ozon-scraper/
├── README.md
├── requirements.txt
├── ozon_http.py  ozon_search.py  ozon_image.py  ozon_detail.py  to-csv.py
├── docs/          知识存档（反爬/端点/坑/字段/性能）
├── examples/      一键脚本
└── archive/       调研期的探针脚本（保留作证据，不用管）
```
