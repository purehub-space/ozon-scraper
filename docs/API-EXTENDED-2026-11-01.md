# Ozon 前台 API 续接探测记录 — 2026-11-01 实弹验证

> 基于本机 `prepare_pool.py --n 2 --headful` 预热 cookie（8 个/会话）+ `curl_cffi` 实弹探测。
> 所有端点均通过 `GET /api/entrypoint-api.bx/page/json/v2?url=<path>` 验证。

---

## 0. 关键新机制（最重要）

### 0.1 PDP 详情需要"会话预热"，直接打必 403

之前文档只写了"PDP 需要 cookie"，实测发现**光有 cookie 不够**：

```
直接打 PDP（带 cookie）                     → 403 fab_chlg_*（返回完整 layout 壳，业务 widget 全无）
同一 Session 先 GET 主页 → 再打 PDP          → 200，84 个 widget ✅
```

**结论**：PDP（可能含全部详情类端点）需要"会话已建立"。正确姿势：

```python
S = cr.Session(impersonate="chrome")
S.get("https://www.ozon.ru/", headers=H, timeout=25)   # 预热主页（200）
r = S.get(entrypoint_url(pdp_path), headers=H, timeout=25)  # 再打详情 → 200
```

会话被打 fab_chlg 后：**重新预热 cookie 池即可恢复**（约 8 秒，`prepare_pool.py --force`）。

### 0.2 composer widget 二次拉取（验证可用）

```
POST /api/composer-api.bx/widget/json/v2?widgetStateId=<stateId>
Content-Type: application/json
body: {"asyncData":"<layout 里原样的 asyncData>"}
→ 200 {"state":{"attachments":[...]}}
```

- 从 PDP2 layout 里找 `component == "webAttachments" / "webReviewGallery" / "webFeedbackForm"` 的条目，取 `stateId` + `asyncData`。
- 验证：webAttachments 二次拉取 200（本商品附件为 0，机制通）。
- 异步内容（证书/说明书/评论图墙/反馈表单）都走这条。

---

## 1. 新增可抓端点（本次验证 200）

| 端点 | URL | 数据价值 |
|---|---|---|
| **问答列表** | `/product/<sku>/question/questions/` | 入口藏在 `webQuestionCount.link` 里（`/question/` 只是 PDP 拷贝，`/question/questions/` 才是列表） |
| **同款其他卖家** | `/modal/otherOffersFromSellers?product_id=<sku>&sort=price\|date` | `webSellerList.sellers[]`：**每家的 sku/id/店名/店铺链接/企业主体凭据/logo/配送时效/价格/商品链接**。比 shop-in-shop 更值钱——横向比价 + 竞品主体批量获取 |
| **店铺评价页** | `/seller/<slug>-<id>/reviews/` | sellerTransparency + 评价列表（列表本体异步） |
| **店铺评分 popover** | `/modal/shop-in-shop-rating-popover?seller_id=<id>` | 评分分布 |
| **品牌筛选页** | `/category/<slug>-<id>/<brand>-<brandId>/` | 品牌下全量商品（33 widgets，含 filtersDesktop） |
| **类目排序变体** | `/category/<slug>-<id>/?sorting=price\|rating\|new` | 排序全量；新增 `categoryBrandList`（页内品牌列表） |
| **highlight 精选** | `/highlight/<id>/` | 专题聚合页（32 widgets） |
| **匿名购物车** | `/cart/` | emptyCart（匿名态可开） |
| **匿名收藏** | `/my/favorites/` | 匿名态可开 |
| **匿名订单** | `/my/orderlist/` | loginButton + myGuest（登录引导页） |
| **PDP2 新组件** | `/product/<sku>/?layout_container=pdpPage2column&layout_page_index=2` | webFeedbackForm / webReviewGallery / webAnchor / tagList（SEO 类目标签）/ tileScrollDesktop（"也推荐"相关推荐） |

## 2. 类目树全量（从任意页 footer 提取）

PDP 响应 footer 含全部顶级类目 URL，可直接做类目地图：

```
/category/odezhda-obuv-i-aksessuary-7500/
/category/elektronika-15500/
/category/dom-i-sad-14500/
/category/krasota-i-zdorove-6500/
...（30+ 顶级类目）
品牌筛选格式：/category/<slug>-<id>/<brand>-<brandId>/
```

## 3. PDP 84 widgets 里文档未覆盖的新组件

| widget | 内容 |
|---|---|
| `webAddToCompare` | 加入对比按钮 |
| `webAddToFavorite` | 收藏按钮（isFavorite 状态） |
| `webBrand` | 品牌认证标记（"Бренд проверен"） |
| `webQuestionCount` | 问答数 + **问答列表链接** |
| `webOneClickButton` | 一键购买 |
| `webStickyColumn` / `webStickyProducts` | 吸顶卡（sku/店名/价格） |
| `webBestSeller` | 同款卖家数（117 个）+ 最低价（от 139₽）+ **modalLink** |
| `webDelivery` | 配送信息（本商品空，带城市参数才出） |
| `bannerCarousel` / `bigPromoPDP` | 促销 banner |
| `foundCheaperText` | "有更便宜的"入口 |

## 4. 同款卖家 webSellerList 结构（新富矿）

```json
{"sellers":[{
  "sku":"5820212207","id":"5854613","name":"peiyurong",
  "link":"/seller/5854613/",
  "credentials":["Suzhoushipeiyurongmaoyiyouxiangongsi","changsanjioaguojiyanfaqidongshequ","CN, Suzhou","Режим работы — согласно режиму работы Ozon"],
  "logoImageUrl":"...","advantages":[{"headRs":[{"content":"Доставим 17 ноября"}],"key":"delivery"}],
  "price":{"cardPrice":{"price":"139 ₽"}},
  "coverImage":"...","productLink":"/product/sumka-ridikyul-5820212207/"
}]}
```

`credentials[]` = 企业主体凭据（公司名 / 注册号 / 国家城市 / 经营模式）——**免登录批量拿竞品主体信息**。

## 5. 无效/需其他条件的路径

| 路径 | 结果 |
|---|---|
| `/modal/currency-language` | 404 |
| `/coupons/` `/global/` `/action/` `/action/deal-of-the-day/` `/live/` `/top/` | 404（路径格式可能不同，待确认） |
| `/product/<sku>/bundle/` `/similar/` `/compare/` | 200 但**路由回 PDP 完整页**（84 widgets），内容靠前端 tab 异步加载，非独立端点 |

## 6. 环境注意

- **Ozon 无需代理，直连即可**（entrypoint-api 对海外 IP 开放；主页/浏览器渲染被 geo 拦时不影响 API）。
- 本机 chromium 在 `/usr/local/bin/chromium`，`prepare_pool.py` 需手动加入候选（已补）。
- headful 预热：5~8 秒、8 cookies；headless：50 秒、3 cookies（headful 优先）。
- 零散探测易触发 fab_chlg（会话级），间隔 ≥2 秒、双 cookie 轮换更稳；被打后重新预热即恢复。
