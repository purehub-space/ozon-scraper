# Ozon 前台 API 全表（2026-10 实测）

所有数据都走同一个门：

```
GET https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=<URL编码的页面路径>
```

返回 `{"layout":[...], "widgetStates":{...}}`，每个 widget 是 key → JSON 字符串。
翻页只需在 `url` 里加 `&page=N`，**不需要 `paginator_token`**。

---

## 一、列表类

### 1.1 类目 / 关键词

```
url=/category/<slug>-<id>/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=<关键词>&page=N
```

| 项 | 值 |
|---|---|
| 每页 | **8 条** |
| 页数上限 | 1,250 页（page 1251 起返回空）= **9,999 个商品** |
| 无 cookie | page 1 → 403，page 2+ → 200 |
| 有 cookie | 全段 200 |

数据位置：`widgetStates["tileGridDesktop-*"]` → `.items[]`

### 1.2 店铺

```
url=/seller/<seller_id>/?page=N
```

| 项 | 值 |
|---|---|
| 每页 | 8 条 |
| 上限 | 到空页为止（大店可能几千页） |

响应里还带：
- `sellerTransparency-*` → 店名/logo/徽章/评分/评价数/订单数/收藏数
- `filtersDesktop-*` → 类目树、价格区间、品牌、原产国、颜色
- `searchResultsSort-*` → 排序项

### 1.3 纯搜索页（`/search/`）

```
url=/search/?from_global=true&text=<kw>&page=N
```

| 项 | 值 |
|---|---|
| 每页 | 8 条 |
| 无 cookie | page 1~200 全 403，250+ 才 200 |
| 有 cookie | 全段 200 |
| 上限 | 1,250 页 |

⚠️ 浏览器打开 `/search/?text=X` 会**前端 JS 跳转**到 `/category/<预测类目>/?...`（不是 HTTP 302）。
带 cookie 后可以直接打 `/search/` 端点，拿到的是全站搜索结果（字面匹配率 ~88%，高于类目页的 ~71%）。

### 1.4 以图搜图

**上传图（返回 image_id）**

```
POST /api/composer-api.bx/_action/searchByImage
Content-Type: multipart/form-data
```

两种模式：

| 模式 | form-data | 说明 |
|---|---|---|
| 文件 | `file` = <二进制>，文件名 `blob`，`image/jpeg` | ≤4MB |
| **URL 透传** | `url` = <图片URL>（**纯文本字段**） | 不用下载图 |

响应：`{"redirectUri":"/search-by-image?image_id=...&resultId":"..."}`

**拉结果**

```
url=/search-by-image?image_id=<id>&page=N
```

| 项 | 值 |
|---|---|
| 每页 | **12 条** |
| 上限 | 约 450 页（每次结果不同，跑到空页为准） |
| 排序 | 第一条就是最相似商品 |

图片要求：JPEG/PNG/WEBP/PDF，≤4MB，裁剪最小分辨率 60px。

---

## 二、详情类（全部需要 cookie，无 cookie 一律 403）

### 2.1 SKU 第一屏

```
url=/product/<sku>/
```

79 个 widget，主要字段见 `DATA-FIELDS.md`。

### 2.2 SKU 第二屏（描述 / 全量属性 / 标签）

```
url=/product/<sku>/?layout_container=pdpPage2column&layout_page_index=2
```

### 2.3 评论

```
url=/product/<sku>/reviews/?page=N
```

| 项 | 值 |
|---|---|
| 每页 | **30 条** |
| 上限 | 无（`paging.links[]` 给下一页完整参数） |
| 同商品集团 | 不同变体共享评论池，按 `uuid` 去重 |

数据位置：`webListReviews-*` → `.reviews[]` / `.paging`

### 2.4 店铺主体（法人信息）

```
url=/modal/shop-in-shop-info?seller_id=<id>
```

⚠️ 主体信息在 **`textBlock-*`** widget，不在 `cellList`。

```
ИП Татур Максим Олегович<br>314860815400040        ← ИП：名称 + ОГРНИП(15位)
ООО "СТРОЙТЕРМИНАЛ ЦЕНТР КРАСОК"<br>121351, Россия, г. Москва, ул. Ивана Франко, д. 48<br>1055000518957
                                                    ← ООО：名称 + 法定地址 + ОГРН(13位)
```

**前台不展示 ИНН**，那个数字是 ОГРН/ОГРНИП。

`cellList-*` 里另有：高级商店徽章、订单数、合作年限、平均评分、评价数量、品牌墙。

### 2.5 证书 / 说明书

```
1) 从 2.2 的 layout 里找 component == "webAttachments" 的条目，取 stateId + asyncData
2) POST /api/composer-api.bx/widget/json/v2?widgetStateId=<stateId>
   body: {"asyncData":"<原样的 asyncData>"}
   → {"state":{"attachments":[{"title":"注册证书"},{"fileUrl":"https://...pdf"}],"params":{...}}}
```

`title` 和 `fileUrl` 是**分开的两个对象**，按顺序配对。

毛绒玩具类目多数为空（卖家没上传），医疗器械类有。

---

## 三、无效的尝试（省得再试）

| 试法 | 结果 |
|---|---|
| `per_page` / `limit` / `page_size` / `items_per_page` | 全部被忽略，固定 8 条 |
| `layout_container=catalogResults` | 无效，响应还是一整页 160KB |
| `widget/json/v2?widgetStateId=tileGridDesktop-*` 单取商品组件 | 400/405（类目页 tileGrid 没有 asyncData） |
| `sec-ch-ua` / `x-o3-*` 渲染协商头 | 对 `/search/` 的 403 无效 |
| JSON body 传图搜 URL（`{"url":...}` 等 18 种字段名） | 全部 500，必须 multipart |
| `/search/by-image/`、`/visual-search/`、`/image-search/` 等页面路径 | 全部重定向回首页 |
| `searchByImageUrl` / `searchByPhotoUrl` 等 action 名 | 404，只有 `searchByImage` |

---

## 四、响应体积与耗时参考

| 端点 | 响应大小 | 单请求耗时 |
|---|---|---|
| 类目/搜索列表页 | ~160 KB（解码后；br 压缩实际传输 ~20KB） | 0.8~3 s |
| 店铺页 | ~150 KB | 1~3 s |
| PDP1 | ~160 KB | 1.1 s |
| PDP2 | ~105 KB | 1.0 s |
| 评论页 | ~290 KB | 1.4 s |
| 店铺主体 modal | ~13 KB | 0.7 s |
| 图搜结果页 | ~155 KB | 0.8~1.3 s |
