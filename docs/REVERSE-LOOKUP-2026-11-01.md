# Ozon 前台"反查"能力全表 — 2026-11-01 实弹验证

> 目标：建立 SKU ↔ 关键词 ↔ 类目 ↔ 店铺 的双向映射。全部端点实弹 200 验证（cookie + 会话预热）。

---

## 一、映射总览

```
关键词 ──search──▶ SKU ──PDP──▶ 类目(breadCrumbs) ──tagListModal──▶ 相关关键词/类目
  │                    │              │
  │  (category_was_predicted)         ▼
  ▼                    └──PDP──▶ 店铺(webCurrentSeller) ──店铺页──▶ SKU 全量
 类目(预测)                                              │
  │                                                      ▼
  └──tileGrid──▶ SKU ──otherOffersFromSellers──▶ 同款其他店铺(+企业凭据)
```

## 二、四条反查链路（用户要求全覆盖）

### 1. 三级类目 → 店铺 ✅

```
类目页 /category/<slug>-<id>/?page=N
  → tileGridDesktop.items[].sku            # 类目 → SKU
PDP /product/<sku>/
  → webCurrentSeller.header                # SKU → 店铺（sellerId + 店名 + logo）
```

更快路径（一次拿多店 + 竞品主体）：`webBestSeller.modalLink` → `/modal/otherOffersFromSellers?product_id=<sku>` → `webSellerList.sellers[]`（同款所有卖家，含企业凭据/价格/配送时效）。

### 2. 关键词 → 类目 ✅

```
/search/?from_global=true&text=<关键词>
  → searchResultsSort.sortButton.options[].action.link
  → /category/<slug>-<id>/?category_was_predicted=true&...&text=<关键词>
```

**`category_was_predicted=true` 就是前端 JS 跳转的同一预测**（实测：сквиш → igrushki-antistress-7181 解压玩具）。
`tapTags.searchText` 回显确认关键词。

### 3. 类目 → 关键词 / 相关类目 ✅

```
类目页 /category/<slug>-<id>/
  → tagListModal.tags[]      # SEO 相关类目标签（"Сумки через плечо женские" 等，带类目链接）
  → categoryBrandList.brands[]  # 品牌墙（20 个：LV/COACH/Chanel/Gucci/Hermes…，带筛选链接）
  → filtersDesktop.sections[].filters[]  # 17 维度筛选（类目树/价格区间/颜色/布尔/复选）
```

### 4. 店铺 seller ID → SKU ID ✅

```
/seller/<slug>-<id>/?page=N
  → tileGridDesktop.items[].sku            # 全量翻页（无上限，直到空页）
  → ?sorting=new                           # 新品序（与热销序做差集 = 新品）
```

## 三、SKU 出发的映射（全部已有）

| 方向 | 端点 | 数据 |
|---|---|---|
| SKU → 类目 | `/product/<sku>/` | `breadCrumbs`（4 级类目路径 + 品牌） |
| SKU → 店铺 | `/product/<sku>/` | `webCurrentSeller`（sellerId/店名/logo/评分/订单数） |
| SKU → 关键词 | `/product/<sku>/` | `webProductHeading.title`（标题分词） |
| SKU → 同款其他店 | `/modal/otherOffersFromSellers?product_id=<sku>&sort=price\|date` | `webSellerList`（店铺+价格+企业凭据+配送） |

## 四、REA 逆向产出（2026-11-01）

对 Ozon 主应用 167 个 JS bundle（下载+解压）做 REA/静态分析：

1. **composer action 共 55 个**（`/api/composer-api.bx/_action/<name>`），主要是账户/收藏/认证类：
   - `categoryChildV3`（类目树子级）
   - `v2/getSearchTapTags`（搜索热词标签）
   - `favoriteListsBySku` / `favoriteCheckItems`（SKU → 用户收藏列表，登录态）
   - `summaryV2` / `summary`（价格/评分摘要）
   - 其余为认证/账户/物流（见 `all_actions.txt`）
2. **action 名是服务端动态下发**：前端代码用 `composerActionLink` / `action.link` 拼接（`composer-api.bx/_action/${t.composerActionLink}`），不存在硬编码全集 → 枚举方法 = 遍历 widget 响应里的 action 字段
3. 搜索建议（autocomplete）端点不在首页 bundle 集内，需在搜索页热加载时抓 Network（后续可做）
4. 素材已归档：`archive/challenge_v47_3.js`（antibot 脚本）、`archive/grab_js.py`（bundle 抓取器）、`archive/probe-endpoints-2026-11-01.py`（端点探针）

## 五、实现建议（续接采集器）

- **关键词 → 类目映射表**：批量跑 `/search/?text=<词>`，从排序链接解析预测类目 → 得到"词→类目"词典（类目预测命中率 ~88%）
- **三级类目 → 店铺表**：类目页 tile → SKU → PDP 取 webCurrentSeller（或同款卖家 modal 批量）
- **类目 → 关键词表**：类目页 tagListModal.tags 直取
- **店铺 → SKU**：已有（ozon_http.py），可加 `?sorting=new` 抓新品差集
