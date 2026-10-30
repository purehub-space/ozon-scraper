# Ozon 前台（买家端）可查字段全表 — 2026-10-27 复测

免登录。三个入口：

```
1) GET /api/entrypoint-api.bx/page/json/v2?url=<path>          # 页面即 JSON，返回 widgetStates
2) GET /api/entrypoint-api.bx/page/json/v2?url=/product/<sku>/?layout_container=pdpPage2column&layout_page_index=2
3) GET /api/composer-api.bx/page/json/v2?url=<path>            # 等价
```

所有字段都在 `widgetStates` 里，每个 widget 一个 key，值是 JSON 字符串。

---

## 一、店铺层

### 1.1 `/seller/<seller_id or slug>/` → `sellerTransparency`

| 字段 | 位置 | 实测（MEDVEDI.BIZ / 78486） |
|---|---|---|
| 店名 | `title.text` | MEDVEDI.BIZ |
| 店铺 logo | `logoImage.backgroundImage` | cdn1.ozonusercontent.com/... |
| 高级商店徽章 | `badges[].leftIcon = ic_m_status_points_filled` | 有 |
| 店铺评分 | `badges` 中 `ic_m_star_filled` 那条 `text` | 4,9 |
| 评价数 | `badges` 中 `ic_m_speech_bubble_filled` | 16 K 评价 |
| **累计订单数** | `badges` 中 `ic_m_box_filled` | **54,1 K 订单** |
| 收藏人数 | `buttons[favoriteButton].button.title` | 3 257 |
| 是否已收藏 | `favoriteButton.isFavorite` | false |
| 聊天入口 | `chat`（跳 `/modal/ozonIdIframe`） | 有 |

### 1.2 `/modal/shop-in-shop-info?seller_id=<id>` → **店铺主体**

⚠️ 主体信息在这个 modal 的 **`textBlock-*`** widget 里，不在 `cellList`。

| 字段 | 实测值 |
|---|---|
| 高级商店说明 | 高级商店 / 这是一家通过特殊检查的大型商店。客户高度赞赏货物的质量 |
| 累计订单数 | 54,1 K（78486）/ 261 K（39932） |
| 与 Ozon 合作年限 | 5 年 / 6 年 |
| 商品平均评分 | 4,9 分之 5 / 4,8 分之 5 |
| 评价数量 | 16 K / 58,5 K |
| **主体名称** | `ИП Татур Максим Олегович` / `ООО "СТРОЙТЕРМИНАЛ ЦЕНТР КРАСОК"` |
| **主体法定地址** | 仅 ООО 有：`121351, Россия, г. Москва, ул. Ивана Франко, д. 48` |
| **注册号** | ИП：`314860815400040`（15 位 = **ОГРНИП**）<br>ООО：`1055000518957`（13 位 = **ОГРН**） |
| 经营模式 | 操作模式-根据臭氧操作模式 |
| 品牌墙 | `cellList` 里的品牌名（СДЕЛАЙ ПОЛ / ЭКОДОМ / …） |

> 更正 10-21 记录：那个数字是 **ОГРН / ОГРНИП**，不是 ИНН。前台不展示 ИНН。

### 1.3 店铺页其他 widget

| widget | 内容 |
|---|---|
| `tileGridDesktop` | 商品卡列表（30~38 条/页），字段同搜索 tile |
| `infiniteVirtualPaginator.nextPage` | 下一页 URL（含 `paginator_token` + `search_page_state`，会话内一次性） |
| `filtersDesktop.sections` | 类目树、价格区间、品牌、原产国、颜色、评分、配送方式 |
| `searchResultsSort` | 排序项：流行 / 新品 / 价格升 / 价格降 / 评分 / 折扣 |
| `?sorting=new` | 上架时间序 → 抓新品（与热销序列做差集） |
| `sharingLink` | 店铺分享链接 |
| `addressBookBarWeb` | 当前配送城市/地址（可改） |

---

## 二、SKU 层

### 2.1 PDP 第一屏（`/product/<sku>/`，79 个 widget）

| widget | 可查字段 |
|---|---|
| `webProductHeading` | 商品标题、行数 |
| `webDetailSKU` | **货号 = SKU**、复制文本 |
| `webPrice` | `isAvailable` 有货标记、`price` 现价、`cardPrice` Ozon 卡价、`originalPrice` 原价、`showOriginalPrice` |
| `webAspects` | **变体矩阵**：aspect 名（Цвет/Размер…）、每个变体的 `sku`、`link`、`availability`、`price`、`originalPrice`、`coverImage`、`colors`（HEX）、`title` |
| `webGallery` | `coverImage`、`images[]`（src + alt，实测 10 张）、`videos[]`（mp4） |
| `webShortCharacteristics` | 短特征键值对，含 `id`（属性ID，如 `Type_0` / `Softtoy_1` / `Heiht_0`）+ 属性链接 |
| `webCharacteristics`（第二屏） | **全量属性表**：`totalCount` + `short[][]`，每项 `key / name / values[].text / link` |
| `webDescription`（第二屏） | `richAnnotation` 富文本 HTML（换行 `<br/>`）、`richAnnotationType` |
| `webHashtags`（第二屏） | 话题标签数组（带 `/search/?text=%23...` 跳转） |
| `webAttachments`（第二屏） | 说明书/证书 widget（`params.title`），需二次 POST 取 `attachments[].fileUrl` |
| `webReviewGallery`（第二屏） | 买家晒图墙 |
| `webListPhotos` | 评论区图片列表 |
| `webReviewProductScore` | `totalScore` 评分、`reviewsCount` 评价数、`url` 评论页路径 |
| `webSingleProductScore` | 评分 + 评价数（合成文案） |
| `webCurrentSeller` | `sellerId`、店名、logo、评分、订单数、`trustFactors`（可信标签）、`chat`、订阅状态 |
| `webStickyProducts` | 吸顶卡：sku / 名称 / 封面 / 店铺名 / 店铺链接 |
| `webBestSeller` | 同款其他卖家数 `count`（4）、最低价（从 4 238 ₽）、`/modal/otherOffersFromSellers` |
| `webMarketingLabels` | 营销标：后付费 / 就是这个价 / 双十一 等 |
| `webSale` | `isAvailable`、`offerType` |
| `webAddToCart` | 加入购物车按钮、`quantityButton.maxItems`（可购上限，实测 965） |
| `webInstallmentPurchase` | 分期方案（“0-0-6”） |
| `breadCrumbs` | 类目路径（4 级：儿童用品 > 玩具和游戏 > 毛绒玩具 > MEDVEDI）+ 品牌链接 |
| `webDelivery` | 配送信息（多数商品该 widget 为空，需带城市参数） |
| `bigPromoPDP` | 大促 banner |
| `foundCheaperText` | “找到更便宜” 入口 |

### 2.2 评论页

```
/product/<sku>/reviews/?page=N        # 30 条/页
```

单条评论：正文、评分、日期、作者、图片、视频、有用票数、是否购买、规格（颜色/尺寸）。

---

## 三、搜索 / 类目层

```
/search/?text=<关键词>&sorting=score|new|price|rating
/category/<slug>-<id>/?page=N&paginator_token=...&search_page_state=...
```

| widget | 字段 |
|---|---|
| `tileGridDesktop.items[]` | `sku`、`id`、`isAdult`、`tileImage`、`mainState`、`topRightButtons`、`brandLogo`、`multiButton`（加购/立即购买）、`action.link` |
| `mainState.priceV2` | 现价、原价、折扣 %（`−87%`）、价格样式 |
| `mainState.textDS` | **“仅剩 N 件”库存提示**、商品名、评分、评价数（`labelListV2`） |
| `trackingInfo.custom.advertLite` | **广告位标识**（有值 = 该 tile 走广告曝光上报；实测搜索首屏 8/8 全带） |
| `filtersDesktop.sections` | 类目树、价格、品牌、原产国、颜色、高评级、分期 |
| `infiniteVirtualPaginator` | `nextPage` / `prevPage`（分页必须沿它走，不能 `page++`） |
| `searchResultsSort` | 排序选项全集 |

> 更正 10-21 记录：「前台没有广告字段」是错的，`advertLite` 就在 tile 的 trackingInfo 里。

---

## 四、拿不到的（前台无字段）

| 数据 | 说明 |
|---|---|
| 精确销量 / GMV / 转化率 | 卖家后台派生指标 |
| 精确库存数 | 只有 “仅剩 N 件” 低库存提示 |
| 卖家内部货号 `offer_id` | 卖家端才有 |
| 退货率 / 取消率 / 广告花费 | 卖家端 |
| ИНН | 前台只给 ОГРН/ОГРНИП |

## 五、可估算

- 店铺 GMV ≈ 累计订单数 × 均价（54.1K × ~4 000 ₽ ≈ 2.2 亿 ₽ 量级）
- SKU 趋势 ≈ 评价数增量（绝对值不可信，只看相对）
- 广告位判定 = tile 是否有 `advertLite`

---

## 六、本次复测产物

| 文件 | 内容 |
|---|---|
| `raw-shopinfo.json` / `raw-shopinfo2.json` | 78486 店铺 modal（含主体 textBlock） |
| `raw-shopinfo-39932.json` | 39932 店铺 modal（ООО 格式，含地址） |
| `raw-sellerpage.json` | 78486 店铺页 34 widgets |
| `raw-sellerpage-new.json` | 同上 `?sorting=new` |
| `raw-pdp1.json` | SKU 244245278 第一屏 79 widgets |
| `raw-pdp2.json` | 同 SKU 第二屏 33 widgets |
| `raw-search.json` | 搜索 `сквиш` 30 widgets（含 advertLite） |
| `probe2.mjs` / `pdp1.mjs` / `more.mjs` | 复现脚本（ego-browser nodejs） |
