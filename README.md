# Ozon 买家端采集器

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
| `ozon_http.py` | 店铺 / 类目全量列表 | seller 或 category URL | ~34 SKU/s |
| `ozon_search.py` | 关键词全量（自动转类目 + 预热） | 关键词或 /search/ URL | ~37 SKU/s |
| `ozon_image.py` | 以图搜同款 | 本地图片 或 图片 URL | ~63 SKU/s |
| `ozon_detail.py` | SKU 详情 + 评论 | skus.txt | ~4.4 SKU/s |

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
bash examples/run_all.sh "сквиш"
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
