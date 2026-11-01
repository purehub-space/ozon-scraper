# Ozon 前端接口数据形态总览 + 大盘/竞对情报价值评估 — 2026-11-01

> 素材：167 个 JS bundle 逆向（55 个 composer action）+ 页面级 widget 实弹验证 + autocomplete 新发现。
> 调用通道：浏览器内同源 fetch（`archive/js-reverse-2026-11-01/browser_api_cdp.py`），避免直接 curl 消耗 cookie 额度。

---

## 一、接口全景（两类入口）

### A. composer actions（55 个，`/api/composer-api.bx/_action/<name>`）

| 类别 | action | 数据形态 | 情报价值 |
|---|---|---|---|
| **搜索热词** | `v2/getSearchTapTags`（参数 `{query, link, widgetVersion:2}`，需 POST 修正，GET 405） | 搜索框热门标签数组 `items[]` | ★★★ 大盘：热搜词榜 |
| **类目树** | `categoryChildV3`（`{menuId, categoryId, hash}`） | 类目子级树（菜单展开） | ★★★ 大盘：市场结构 |
| **类目导航** | `v2/shellHorizontalMenuGetChildV1` | 顶栏水平菜单子类目 | ★★★ 大盘：一级类目格局 |
| **购物车摘要** | `summary` / `summaryV2` | 购物车 items + itemsFamily（SKU 聚合） | ★★ 竞对：热销 SKU 观察 |
| **收藏** | `favoriteListsBySku`、`favoriteCheckItems`、`favoriteLists` 等 13 个 | 用户收藏列表 / SKU 在哪些收藏 | ★★ 需登录态 |
| **认证/账户** | `fastEntryV3`、`ozonIdAuth*`、`sberIdEntryV1`、`patchUserAccount` 等 18 个 | 登录/注册/资料（无公开数据） | — 无关情报 |
| **widget 批量** | `/widget/json/v2/batch` | 多 widget 一次拉取 | ★★★ 采集效率：单请求多 widget |
| **购物车布局** | `layout` | 页面布局 | — |

机制：action 名**服务端动态下发**（`composer-api.bx/_action/${composerActionLink}`），前端无硬编码全集；枚举 = 遍历页面 widget 的 action 字段。

### B. 页面级 entrypoint 端点（`/api/entrypoint-api.bx/page/json/v2?url=<path>`）

所有页面返回统一结构：`{layout: [...], widgetStates: {<widgetName>-<id>-default-<v>: "<json字符串>"}}`。

| 端点 | 关键 widget | 数据形态 |
|---|---|---|
| `/search/?text=<词>` | `searchResultsSort`（类目预测链接）、`tileGridDesktop`（商品列表）、`searchResultsFiltersActive`、`tapTags` | 搜索结果 + 预测类目 + 商品 SKU |
| `/searchSuggestions/search/?text=<词>&from_global=true` | `webSuggestions`（**本次新发现**） | 联想词（5 条搜索词 + 4 条类目/品牌，带跳转链接） |
| `/category/<slug>-<id>/` | `tileGridDesktop`、`filtersDesktop`（17 维度）、`tagListModal`（相关类目）、`categoryBrandList`（20 品牌） | 类目商品 + 筛选分布 + SEO 标签 + 品牌墙 |
| `/product/<sku>/` | 84 widgets：`webPrice`、`webCurrentSeller`、`webBestSeller`、`breadCrumbs`、`webSale`、`webAspects`、`webQuestionCount`… | 商品全维度 |
| `/product/<sku>/?layout_container=pdpPage2column&layout_page_index=2` | `webDescription`、`webCharacteristics`、`webHashtags`、`webReviewGallery`、`tagList`（SEO 标签） | 详情/参数/标签 |
| `/modal/otherOffersFromSellers?product_id=<sku>&sort=price\|date` | `webSellerList.sellers[]` | **同款所有卖家 + 企业凭据** |
| `/seller/<slug>-<id>/?page=N` | `sellerTransparency`（评分/订单/收藏）、`tileGridDesktop` | 店铺实力 + 全店 SKU |
| 评论/问答 | 评论列表 widget、`/product/<sku>/question/questions/` | 口碑数据 |
| 品牌筛选页 | 品牌页商品列表 | 品牌维度 |

---

## 二、大盘信息（市场容量/结构/趋势）重点接口 ★★★

| 情报 | 接口 | 字段 | 用法 |
|---|---|---|---|
| **搜索热度/词库** | `webSuggestions`（autocomplete） | `items[].cellItem.centerBlock.title.text` + `common.action.link` | 输入种子词 → 联想词 + 关联类目 + 关联品牌 → **关键词库自动扩充**（SEO/广告词源） |
| **热搜榜** | `v2/getSearchTapTags` | `items[]` | 搜索框热门标签 = 实时需求热榜 |
| **类目结构** | `categoryChildV3` + `shellHorizontalMenuGetChildV1` | 类目树 | 全类目层级 → 市场地图 |
| **类目容量** | 类目页 `tileGridDesktop` | 分页数 | 每类目在售 SKU 规模（翻页到空页） |
| **类目价格带** | 类目页 `filtersDesktop` 的 rangeFilter + 搜索页 `tileGrid` 价格 | 价格区间 + 价格分布 | 类目价格结构 |
| **品牌格局** | 类目页 `categoryBrandList.brands[]` | 20 品牌 + 筛选链接 | 类目头部品牌榜 |
| **相关类目热度** | 类目页 `tagListModal.tags[]` | SEO 标签（带类目链接） | 相邻类目/需求外溢方向 |
| **需求预测** | `/search/?text=X` → `searchResultsSort` 的 `category_was_predicted=true` | 预测类目链接 | 词→类目归属（词典） |
| **在售 SKU 规模** | 搜索页 `tileGridDesktop` 全翻页 | SKU 列表 | 品类供给量 |

---

## 三、竞对信息（卖家/价格/口碑）重点接口 ★★★

| 情报 | 接口 | 字段 | 用法 |
|---|---|---|---|
| **同款全卖家** | `/modal/otherOffersFromSellers?product_id=<sku>&sort=price\|date` | `webSellerList.sellers[]` | 同 SKU 全部在售卖家 + 价格排序 → **价格战/跟卖分析** |
| **企业主体** | 同上 | `sellers[].credentials` | **公司名 + 注册号 + 国家城市** → 竞对工商主体溯源 |
| **店铺实力** | `/seller/<id>/` → `sellerTransparency` | 评分/评价数/**累计订单数**/收藏数/徽章 | 竞对店铺量级 |
| **竞品价格带** | 同款卖家 modal `sort=price` | 每卖家价格/原价 | 定价策略 |
| **配送时效** | 同款卖家 modal | 配送时间/方式 | 履约能力对比 |
| **热销款** | PDP `webStickyProducts` / `webBestSeller` / `tileScrollDesktop`（"Рекомендуем также"） | 关联推荐 SKU | 竞品连带销售 |
| **促销力度** | PDP `webSale` / `webMarketingLabels` | 折扣/营销标签 | 竞对促销监控 |
| **商品口碑** | PDP 评论 + 问答 widget | 评分/评论数/问答 | 竞品质量信号 |
| **新品差集** | `/seller/<id>/?sorting=new` | tileGrid SKU | 竞店上新监控 |
| **反查店铺** | 关键词→类目→SKU→`webCurrentSeller` | sellerId | 任意关键词找到活跃卖家 |

---

## 四、本次新增：autocomplete 端点（webSuggestions）实测

```
GET /api/entrypoint-api.bx/page/json/v2?url=/searchSuggestions/search/?text=<词>&from_global=true
→ 200 JSON，widgetStates.webSuggestions-*.items[]（9 条/词）
```

实测样本：

| 输入 | 联想词（icon=False） | 类目/品牌（icon=True） |
|---|---|---|
| сквиш | сквиши / сквиш пельмень / сквиш антистресс / сквиш масло | Сквиши и слаймы(38098) / Прочие антистрессы(38102) / Needoh / Funky Toys |
| сумка | сумка женская / сумка мужская через плечо / сумка дорожная / сумка для инструмента | Сумки женские(17002) / Сумки мужские(17065) / AMBERRY / IMMAKOLETA |
| casio | casio f-91w / casio часы мужские / casio часы женские | Часы женские(17037) / Часы мужские(17089) / Casio(26303060) |

**价值**：一个词 → 词族（复数/长尾）+ 归属类目 ID + 头部品牌 ID，是关键词库和类目归类的自动扩充器。
样本：`archive/js-reverse-2026-11-01/autocomplete_{сквиш,сумка,casio}.json`

---

## 五、采集建议

1. **大盘监控**：种子词表 → autocomplete（联想词 + 类目 ID）→ 类目页（SKU 容量/品牌墙/价格带）→ 定期快照比较
2. **竞对监控**：目标 SKU → `otherOffersFromSellers`（全卖家 + 企业凭据 + 价格）→ 卖家店铺页（订单量/上新）
3. **效率**：用 `/widget/json/v2/batch` 批量拉 widget；cookie 额度有限，浏览器内 fetch（`browser_api_cdp.py`）优于直连
4. **待办**：`getSearchTapTags` 需改 POST 或补参数（GET 405）；登录态可解锁 favorite* 系列（收藏数据）

---

## 库存获取（2026-11-01 实弹定论）

### 三种途径对比

| 途径 | 覆盖 | 精度 | 机制 |
|---|---|---|---|
| **购物车 maximum** | ✅ 100%（促销+非促销） | 精确数字 | `POST /action/addToCart {items:[{id,quantity}]}` → `GET /cart` → `cartSplit.cartItems[].quantity.maximum` |
| **bigPromoPDP** | ⚠️ 仅促销商品 | 精确数字 | PDP `bigPromoPDP.stockNumber` + `counter.percentage`（已售比例） |
| **卡片"X ед осталось"** | ⚠️ 仅促销商品 | 精确数字 | 搜索/类目/推荐 tile 卡片文本 |

### 决定性验证

- SKU 5527434733：PDP bigPromoPDP 显示库存 172 → 加购后购物车 `maximum=172` ✅ 完全一致
- 非促销 3 SKU（无任何库存显示）：加购后 `maximum=987/1353/2000` → **非促销品库存同样可拿**
- `maximum` 是服务端按可用库存动态下发；**2000 为平台硬顶**（库存≥2000 时封顶显示 2000）
- **修正**：早期判断"maximum=2000 固定值、不能反推库存"为错误结论

### 反推销量

促销品：`已售 = stockNumber/(1-percentage) × percentage`（5527434733 → 总量≈905、已售≈733）
非促销品：无已售数据，仅评价数/收藏数代理。

### 采集建议

- 竞对重点 SKU：定期（如每天）加购+读 maximum → 库存变化曲线（动销速率）
- 注意：加购写入匿名购物车，同一浏览器会话内可重复覆盖；不触发支付

---

## 库存/价格/销量批量获取（2026-11-01 补充定论）

### 库存：列表页 tile 直接返回（无需加购）

**`tileGridDesktop.items[].quantityButton.maxItems` = 商品可用库存**，100% 覆盖（促销+非促销）：
- cat p1: 8/8（172/219/2000/1395/1353/1597/1629/987）
- cat p2: 8/8（18/360/840/1660/2000/601/991/2000）
- search: 8/8（2000/214/67/166/2000/287/2000/215）
- 与购物车加购实测完全吻合（5034371857=987、5034433921=1353、5097092644=2000）
- **批量采集 = 翻列表页**（搜索/类目/店铺 tileGrid），每页 8~30 卡片，翻页无上限
- 2000 为平台硬顶

### 价格

| 途径 | 内容 | 覆盖 |
|---|---|---|
| tile priceV2 | 现价+原价+折扣% | 列表页批量 |
| PDP webPrice | 现价/originalPrice/Ozon 卡价 | 单 SKU |
| `/modal/web_pdp_lower_price?product_id=<sku>` | **上月平均价**（280₽ vs 10月均价 299₽，降19₽） | 降价商品 |

无完整历史价格 API；唯一历史值=上月均价。

### 销量：无直接字段

- 无 "已售 N 件"；收藏数接口（favoriteCountItems）匿名不可用（entity not found）
- 代理：评价数（webSingleProductScore/webReviewProductScore.reviewsCount）+ 库存变化曲线

### 大量历史数据方案（唯一正路 = 自建快照）

Ozon 不提供历史价格/销量 API。方法：
1. 每天抓目标列表页（类目/关键词/店铺）→ 存 tile 全字段（SKU、maxItems 库存、priceV2、评分、评价数）
2. 逐日差值：库存变化=动销速率、价格变动、评价增长=销量代理
3. 竞对重点 SKU 可叠加加购+读 maxItems 精确认证
