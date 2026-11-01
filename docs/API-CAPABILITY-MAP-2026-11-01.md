# Ozon 买家端能力全景（浏览器内实弹验证）

> 全部端点走 `/api/entrypoint-api.bx/page/json/v2?url=<path>` 浏览器内同源 fetch；composer action 走 `/api/composer-api.bx/_action/<name>`。cookie 池 12h 有效，每份 100~150 页配额。

## 1. 跟卖同款数据

```
GET /api/entrypoint-api.bx/page/json/v2?url=/modal/otherOffersFromSellers?product_id=<sku>&sort=price|date
→ webSellerList.sellers[]:
  sku / id / name(店铺名) / link / 
  credentials(公司名+注册号+国家+城市+营业模式) / 
  price.cardPrice.price(价格) / 配送时效
```
实测：SKU 5527434733 → **112 家同款卖家**，全中国跨境（漳州兆拓/厦门汇美丰/晋江福宜达…）+ 完整企业凭据。
用途：判断红海程度、价格带、竞争对手身份。

## 2. 类目 → 卖家 sellerId

| 途径 | 端点 | 内容 |
|---|---|---|
| 类目页筛选 | `/category/<slug>-<id>/` → `filtersDesktop` | 17 筛选维度，**Магазин 店铺筛选项直接给头部店铺 sellerId** |
| 三级类目→SKU→店铺 | tileGrid sku → PDP `webCurrentSeller` | 单 SKU 归属店铺 |
| 批量更优 | otherOffersFromSellers | 一次拿所有同款卖家 sellerId |

## 3. 卖家 → SKU 列表

```
GET ...?url=/seller/<slug>-<id>/?page=N
→ tileGrid（全量翻页无上限）；?sorting=new 新品差集
```
实测：/seller/5902907/（漳州兆拓）已抓。

## 4. SKU 价格

| 途径 | 字段 |
|---|---|
| tile priceV2 | 现价 + 原价 + 折扣%（−90%） |
| PDP webPrice | `cardPrice`(绿标 Ozon 卡价) + `price`(黑标普通价) + `originalPrice` |
| /modal/pdpListOfBanks | 各银行支付价 |
| /modal/web_pdp_lower_price | 上月平均价（280₽ vs 10月均价 299₽） |

## 5. SKU 库存

| 途径 | 覆盖 | 说明 |
|---|---|---|
| tile `quantityButton.maxItems` | ✅ 100%（促销+非促销） | **批量**：翻列表页即得，2000 平台硬顶 |
| 购物车 `cartSplit.quantity.maximum` | 单 SKU | 加购后读，精确库存 |
| bigPromoPDP stockNumber | 仅促销品 | 172 件 + percentage 已售 81% |

## 6. SKU 销量

- **无直接"已售 N 件"字段**
- 代理指标：
  - 评价数：PDP `webReviewProductScore.reviewsCount` / 评论页 `webListReviews.paging.total`（实测 20 807）
  - 评分：webSingleProductScore
  - 库存变化曲线（自建快照，maxItems 逐日差值 = 动销）
  - 促销已售比例（bigPromoPDP.percentage，促销品）

## 7. 后台价格

- 买家端能拿：绿标（Ozon 卡价）+ 黑标（普通价）+ 原价 + 银行价 + 上月均价
- **卖家后台真实设置价/到手价/佣金：买家端不可得**（属 Seller API，需卖家账号授权，见 ozon-seller-* 项目）

## 8. 评论与星级筛选

```
GET ...?url=/product/<sku>/reviews/?reviewsVariantMode=2&sort=<sort>
→ webListReviews:
  reviews[].content.{score(1-5), comment, positive, negative, photos[], videos[]}
  + createdAt/publishedAt/author/usefulness/badge
  paging.total / page=N&page_key=<游标> 翻页
```

| 能力 | 状态 |
|---|---|
| 每条评论精确星级 | ✅ content.score |
| 排序 | ✅ usefulness_desc / **score_desc(高星)** / **score_asc(低星，实测全 1 星)** |
| 精确星级过滤（URL 参数） | ❌ score/rating/scoreFilter 不生效；本地按 score 过滤可行 |
| 有图筛选 | ⚠️ withPhotos 参数未生效（待深挖） |
| 评论图片/视频 | ✅ URL 直达 |

## 采集链路速查（选品/竞对）

```
关键词 → /search/?text=<kw>（类目预测 category_was_predicted=true）
类目 → /category/<slug>/?page=N（tile: maxItems库存+priceV2+评分+评价数+卖家）
SKU → /product/<sku>/（webPrice/webCurrentSeller/bigPromoPDP/评价数）
SKU → /modal/otherOffersFromSellers（112家同款+企业凭据）
卖家 → /seller/<id>/?page=N（全量SKU）
SKU → /product/<sku>/reviews/（评论全字段+星级排序）
```
