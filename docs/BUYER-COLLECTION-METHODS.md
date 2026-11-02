# Ozon 买家端前台数据采集方法与字段字典规范

> 本文档规范了 `ozon-seller-kit` 中集成的 **买家端前台采集模块 (`ozon_buyer`)** 的采集方法、底层微前端 Widget 映射关系及数据字段字典。

---

## 一、 为什么将买家端采集平铺收录到 `ozon-seller-kit`（且无需嵌套 Git）？

在版本管理与架构设计上，**坚决不采用 Git Submodule 或嵌套 Git 仓库**，理由如下：
1. **工程维护体验**：Git Submodule 在拉取与更新时容易出现 detached HEAD、遗漏 `--recursive` 导致空目录、以及 CI/CD 构建时的权限配置阻碍；平铺原生纳入受主仓单一 Git 树管理。
2. **职责边界清晰**：
   - `ozon_seller/`：负责具名卖家端后台私有分析接口（P6 畅销榜 / P7 词库 / P8 搜索位 / CJM 我的商品），使用店铺授权 Cookie，单线程/低频受控采集。
   - `ozon_buyer/`：负责匿名买家端公开页面微前端接口（搜索、类目、PDP 变体矩阵、全属性、`stock_max` 物理库存、买家评价、同款卖家工商凭据），使用匿名池化 Cookie，高并发纯 HTTP 极速采集。
3. **数据合流统一**：两端各自产出 JSON/SQLite，在中间分析层以 `sku` 统一对齐合并。

---

## 二、 买家端采集方法全景

### 1. 通用微前端端点 (Entrypoint API)
Ozon 买家端是典型的单页微前端架构，核心数据入口为：
```http
GET https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=<站点路径>
GET https://www.ozon.ru/api/composer-api.bx/page/json/v2?url=<站点路径>
```
* **请求头要求**：必须伪装现代浏览器 TLS 指纹（`impersonate="chrome124"`），携带有效匿名 Cookie。
* **语言绑定**：返回的文本语言与 Session 预热时的 Locale 绑定，请求头中的 `Accept-Language` 无效。
* **响应结构**：统一返回 `{ "layout": [...], "widgetStates": { "<widgetName>-<id>-default-<v>": "<json_string>" } }`。

---

## 三、 买家端核心采集字段与 Widget 映射字典

### 1. SKU 商品详情层 (PDP 第一屏 & 第二屏)

| 归属组件 (Widget) | 字段键名 | 中文名称 | 数据类型 | 业务定义与分析价值 |
|---|---|---|---|---|
| `webProductHeading` | `title` / `text` | 商品主标题 | String | 完整商品标题，无截断，供关键词提取与文本相关性对齐。 |
| `webDetailSKU` | `copyText` / `sku` | 商品 SKU | String | 买家前台商品数字编码，全系统主键。 |
| `webPrice` | `cardPrice` | Ozon 卡价 (绿标) | Float | ★ 买家使用 Ozon Card 结算的真实底价，是核心成交转化价。 |
| `webPrice` | `price` | 普通售价 (黑标) | Float | 常规非卡买家看到的价格。 |
| `webPrice` | `originalPrice` | 划线原价 | Float | 卖家高标参考原价，用于前端计算划线折扣率。 |
| `webPrice` | `isAvailable` | 可售标记 | Boolean | 是否在售。 |
| `webAspects` | `aspects[].variants[]` | 变体全家桶矩阵 | Array | ★ **买家端独家**：遍历该款下的所有变体 SKU、属性色值 (HEX)、尺码、对应价格与在售状态。 |
| `webGallery` | `images[]` | 主图图集 | Array | 高清商品图片列表（支持插入 `/wc1200/` 参数一键转超清 WebP）。 |
| `webGallery` | `videos[].url` | 主图视频直链 | String | MP4 视频演示流地址。 |
| `webShortCharacteristics` | `characteristics[]` | 核心短特征 | Array | 首屏展示的关键属性，包含官方属性 ID（如 `Type_0`）。 |
| `webCharacteristics` (P2) | `characteristics[].short[]`| 全量结构化属性表 | Array | 材质、产地、包装尺寸、重量等全量参数表。 |
| `webDescription` (P2) | `richAnnotation` | 富文本详情 HTML | String | 详情页长图文 HTML 原文。 |
| `webReviewProductScore` | `totalScore` / `reviewsCount`| 评分 / 评价数 | Float / Int | 前台综合评分与累计评价总数。 |
| `bigPromoPDP` | `stockNumber` / `percentage` | 限时抢购库存 | String / Float| 促销中的剩余库存（如 `"172 шт."`）与已售进度（`81%`）。 |
| `webCurrentSeller` | `sellerId` / `name` | 在售店铺与 ID | String / String | 占领当前 Buybox 的卖家店铺信息。 |
| `webBestSeller` | `count` / `minPrice` | 同款跟卖商数量 | Int / Float | 跟卖此款式的外部卖家总数及最低起售价。 |

---

### 2. 搜索列表与类目页 (TileGrid)

| 组件层级 | 字段路径 | 中文名称 | 数据类型 | 业务定义与说明 |
|---|---|---|---|---|
| `tile.action` | `link` | 商品落地路径 | String | 商品的访问 URL（包含 SEO slug 和 SKU）。 |
| `mainState.priceV2` | `price[0].text` / `[1].text` | 现价 / 划线价 | Float / Float | 列表页显示的标价。 |
| `mainState.priceV2` | `discount` | 折扣幅度 | String | 列表角标折扣百分比（如 `−90%`）。 |
| `mainState.textDS` | `text` | 低库存警示 | String | 当库存告急时的紧迫度文案（如 `"仅剩 3 件"`）。 |
| `multiButton` | `quantityButton.maxItems` | **真实物理库存 (stock_max)** | Int | ★ **100% 覆盖**：无需加购，翻列表页直接获得买家最大可购数（平台硬顶 2000）。 |
| `trackingInfo` | `click.custom.advertLite` | 搜索广告位标记 | Boolean | 为 `true` 代表此坑位走 Trafarets 推广曝光，用于测算广告密度。 |
| `filtersDesktop` | `sections[]` | 17维筛选器 | Array | 类目树、价格区间、品牌墙、头部卖家 ID 列表。 |
| `infiniteVirtualPaginator`| `nextPage` | 动态真分页游标 | String | 包含会话单次有效的 `paginator_token`，禁止直接 `page++`。 |

---

### 3. 同款跟卖商全景 (`/modal/otherOffersFromSellers`) 工商资质字典

| 字段路径 | 中文名称 | 数据类型 | 说明 |
|---|---|---|---|
| `sellers[].id` | 卖家 ID (`sellerId`) | String | 跟卖商唯一数字 ID，可拼接 `/seller/<id>/` 扫全店商品。 |
| `sellers[].name` | 店铺公开名称 | String | 招牌名称。 |
| `sellers[].credentials.name` | **企业主体全称** | String | 营业执照登记的法定企业名称（如“漳州兆拓贸易有限公司”）。 |
| `sellers[].credentials.number` | **商业注册号 (OGRN)** | String | 俄罗斯主体为 ОГРН (13位) 或 ОГРНИП (15位)；中国跨境卖家为统一社会信用代码。 |
| `sellers[].credentials.city / country` | 注册城市 / 国家 | String / String | 用于判断是俄罗斯本土海外仓还是中国跨境直发。 |
| `sellers[].price.cardPrice.price` | 跟卖到底报价 | Float | 实际跟卖价格。 |
| `sellers[].delivery.period` | 配送履约时效 | String | 承诺时效（如“15~20 天”或“2 天本地达”）。 |

---

### 4. 买家评价通道 (`/reviews/`) 字典

* `content.score`：打分星级（1 ~ 5 分整数）。
* `content.comment`：买家主评文本。
* `content.positive` / `negative`：Ozon 特有的结构化优缺点填写项。
* `content.photos[]` / `videos[]`：买家晒单实拍图片/视频 URL（高清做工瑕疵分析）。
* `usefulness.likeCount`：评价点赞有用数。
* `paging.total`：全量评价条数，支持带 `?reviewsVariantMode=2&sort=score_asc` 真翻页排查 1 星差评。

---

## 四、 买家端采集与工程避坑法则

1. **前台不提供 ИНН 纳税人识别号**：前台公开的数字为 ОГРН / ОГРНИП（统一国家法人/个体工商户登记号），若需要 ИНН 必须通过 ОГРН 在俄罗斯联邦税务局 (ФНС) 数据库二次反查。
2. **前台无直接“已售件数”**：`reviewsCount` 为多年累计评价，绝不能当月销；月销量需由卖家端 P6 补充，或对前台 `stock_max` 做逐日快照差值测算动销。
3. **评论接口必须按排序置顶**：URL 传入 `score=1` 无效，必须传入 `reviewsVariantMode=2&sort=score_asc` 将 1 星差评置顶，在本地按 `score == 1` 过滤。
4. **Adult 18+ 弹窗拦截**：情趣内衣等敏感品类遭遇 `userAdultModal` 弹窗时，必须通过 CDP 模拟输入出生日期（如 `01.01.1990`）过检，否则 `tileGridDesktop` 响应为空。

---

## 五、 对标与吸收：`ozon-seller-assistant` 插件取证审计与端口分析

通过对 `ozon-seller-assistant`（v1.7.10 选品核价助手）源码及取证审计文档 (`docs/AUDIT.md`) 的静态逆向分析，其每个商品卡片实际调用的核心端口与接口链路如下：

### 1. 调用的端口与 API 映射全景

| 序号 | 接口端点 (端口路径) | HTTP 方法 | 所属域名 / 权限要求 | 采集数据内容 |
|---|---|---|---|---|
| **S3** | `/api/entrypoint-api.bx/page/json/v2?url=/modal/otherOffersFromSellers?product_id=<SKU>&page_changed=true` | GET | `www.ozon.ru` (买家端公开端点 / 会话 Cookie) | **跟卖卖家总数 (`count`)**、所有跟卖商列表、最低跟卖价 (`minPrice`)、最高跟卖价 (`maxPrice`)、币种、每家店铺的 `sellerId`、`sellerName`、跟卖单品 `sku`、实付底价 `price`、买家评分 `rating`、评价数 `reviewsCount`、店铺链接、商品独立落地页、店铺 Logo |
| **S1** | `/api/site/seller-analytics/what_to_sell/data/v3` | POST | `seller.ozon.ru` (需卖家店铺登录态 Cookie) | 30 天销量 (`soldCount`)、GMV、销售动态、平均售价、加购率、DRR 广告比、投流天数、结单率、体积、曝光量等 27 项后台私有数据 |
| **S2** | `/api/site/seller-prototype/create-bundle-by-variant-id` | POST | `seller.ozon.ru` (需卖家店铺登录态 Cookie) | 详情补全：根据 `variantId` 反查条形码、包装规格尺寸、毛重、上架时间 |
| **S4** | `/api/composer-api.bx/_action/v2/addToCart` &rarr; `/cart` &rarr; `deleteItems` | POST/GET | `www.ozon.ru` (需买家账号登录态，写操作) | **商品包装实重**（通过模拟加购物车后读取购物车结算物流重量反推，需要清空购物车，有写入污染风险） |
| **S6** | `open.er-api.com/v6/latest/CNY` | GET | 外部免认证公共汇率接口 | 人民币对卢布汇率（用于核价面板实时折算） |

### 2. 吸收补充到 `ozon_buyer` 的增强功能

1. **同款跟卖商家数量与最低价 (`webBestSeller`)**：
   - 在无需请求 modal 弹窗的情况下，直接在 PDP 首屏的 `webBestSeller` 中提取 `count`（跟卖商家数量，如 `112`）与 `minPrice`（如 `"от 193 ₽"`）。
2. **完整跟卖商名单与工商资质 (`/modal/otherOffersFromSellers`)**：
   - `BuyerClient.other_offers(sku)` 提取完整跟卖列表：
     - `count`：跟卖商家总数
     - `min_price` / `max_price`：价格区间
     - `sellers[]`：每家跟卖商的 `seller_id`、`seller_name`、`competitor_sku`（跟卖商品独立 SKU）、`price`、`company_name`（营业执照法定公司全称）、`reg_number`（ОГРН/统一代码）、`city`、`country`、`delivery_period`（承诺时效）、`product_url`。
3. **CLI 综合采集器支持 `--with-offers`**：
   - 运行 `python3 scripts/collect_buyer.py --sku <SKU> --with-offers` 时，自动抓取并输出跟卖商家数量与名单，直接用于货源对比和被跟卖排查。
