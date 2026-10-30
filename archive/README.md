# 调研期探针（保留作证据，日常不用）

这些是逆向过程中写的实验脚本，记录了每一步是怎么试出来的。
想知道某个结论的原始证据，在这里找。

## 分类

| 前缀 | 用途 |
|---|---|
| `http_probe*.py` | 纯 HTTP 路线的验证：TLS 指纹对比、并发吞吐、header 最小集、稳定性压测 |
| `cdp_*.py` | CDP 浏览器路线：并发实例、cookie 注入、重定向确认、速度对比 |
| `probe_search*.py` | `/search/` 端点 403 的定位（page 1~200 vs 250+） |
| `probe_image*/probe_img*.py` | 图搜入口的摸索（DOM 找相机图标、试 URL 参数、试 action 名） |
| `probe.py` / `probe2.py` / `probe3.py` / `probe_uc*.py` | Selenium / undetected-chromedriver 全部 403 的证据 |
| `mini_img.py` | 图搜最小可复现版（30 行，死锁修好后的参考实现） |
| `check_redirect.py` | `/search/` → `/category/` 是前端 JS 跳转的证据 |
| `headless_cookie_test.py` | headless 过不了 challenge 的证据 |
| `cmp_search_cat.py` | 搜索页 vs 类目页结果对比 |
| `collect.mjs` | 早期 ego-browser 版采集器（含评论/证书，已被 ozon_detail.py 取代） |
| `probe-*.mjs` | ego 浏览器版的各类探针（分页/限流/cookie 对比） |

## 重要证据文件（在原工作目录）

- `scratch/2026-10-27-ozon-front-fields/FIELDS.md` — 字段全表原始版
- `scratch/2026-10-27-ozon-front-fields/raw-*.json` — 各端点原始响应
- `scratch/2026-10-27-ozon-collector/README.md` — ego 版的限流实测记录
- `scratch/2026-10-27-ozon-py/probe_search_worker/REPORT.md` — worker 对 `/search/` 403 的独立调查报告

## 注意

探针脚本里有些是失败的尝试（比如 `probe_uc.py` 就是踩坑记录），**不要直接拿来用**。
生产用的四个脚本在父目录。
