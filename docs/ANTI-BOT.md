# Ozon 反爬机制与对策（全部实测）

## 一句话

**TLS 指纹决定生死，cookie 决定能不能拿 page 1。**

---

## 一、四道门，逐层过

### 第 1 道：TLS/JA3 指纹

| 客户端 | 结果 |
|---|---|
| `curl` | 307 → `?__rr=1` → 403 `challengeURL` |
| `curl + 浏览器导出的 cookie` | **307 无限循环**（redirects=50） |
| Python `requests`（LibreSSL） | 前 ~100 次能过，之后 **403 拉黑**，冷却 60s 无效 |
| **`curl_cffi` + `impersonate="chrome"`** | **稳定 200** ✅ |
| `curl_cffi` + `impersonate="safari"` / `"chrome136"` | 也能过 |

关键：header 齐全也没用，`requests` 一样被打。差别在 TLS 握手本身（BoringSSL vs LibreSSL）。
`curl_cffi` 把 TLS 伪装成 Chrome 就过了。

```python
from curl_cffi import requests as cr
r = cr.get(url, headers=H, impersonate="chrome", timeout=45)
```

### 第 2 道：cookie（只管 page 1）

| 端点 | 无 cookie | 有 cookie |
|---|---|---|
| 类目/搜索列表 page 2+ | 200 | 200 |
| 类目/搜索列表 **page 1** | **403** | **200** |
| PDP1 / PDP2 | **403** | **200** |
| 评论 | **403** | **200** |
| 店铺主体 modal | **403** | **200** |
| 图搜结果 | 200 | 200 |

所以 cookie 不是「能不能抓」的门票，是「能不能拿首屏和详情」的门票。

cookie 实测寿命 **> 11 小时** 仍有效（`~/.cache/ozon-search/` 里那份 42220 秒前的照样 200）。

### 第 3 道：antibot challenge（`fab_chlg`）

无 cookie 打被保护的端点会返回：

```json
{
  "incidentId": "fab_chlg_20261027...",
  "challengeURL": "https://www.ozon.ru/challenge.html?challenge=...",
  "timeoutSec": 180
}
```

这是会话级封禁。**清 cookie 换全新指纹可以立刻恢复**（但会话历史也一起没了）。

### 第 4 道：行为风控（`fab_`，不带 `chlg`）

打太密会被升级成 `fab_`（行为级）：

- 症状：所有端点 403，包括之前能过的类目 page 2
- 恢复：**等 5~40 分钟**，无其他办法
- 触发量级：连续 60+ 请求猛打、并发 24 线程满速跑几百页、反复试错

实测两条线：

| 场景 | 表现 |
|---|---|
| 24 线程 × 504 请求（类目列表） | 99.2% 成功，**没有**触发 |
| 反复试 header 组合（几十次零散请求） | 触发了，恢复要等半小时 |

**结论**：稳定批量（有节奏的并发）比零散试错更安全。

---

## 二、cookie 从哪来：静默预热

### 为什么不能直接导 cookie

实测：从浏览器 A 导出的 21 个 cookie（含 `abt_data`、`__Secure-ETC`）注入全新浏览器 B → **仍然 403**。

challenge 绑的不只是 cookie，还有会话内存态/指纹绑定。

### 正确做法：让浏览器自己过一次 challenge

```python
# 起 Chrome（窗口移到屏幕外，用户看不到）
"--window-position=-2400,-2400"

# 打开 www.ozon.ru/
# 等 5~10 秒，页面 JS 自己跑完 antibot challenge
# 导出 cookie + UA
```

实测 5.0~5.5 秒完成。

### 💡 更省事的方案：直接读本机浏览器

`cookie_from_browser.py` 用 `browser_cookie3` 从 Chrome/Edge/Brave 的 Cookie 数据库里
解密出 `abt_data`（macOS 用 Keychain 密钥），**不启动浏览器进程**，零窗口零等待。

实测本机 Chrome 42 个 ozon cookie，直接可用：seller/pdp/list p1/图搜 全 200。

前提：这个浏览器访问过 `www.ozon.ru`。

### ⚠️ headless 不行（根因已定位）

| 模式 | 页面 | 拿到的 cookie 能否用于 API |
|---|---|---|
| `--headless=new`（默认 UA） | ❌ title = "Похоже, нет соединения" | — |
| `--headless=new --user-agent=<真实UA>` | ✅ 页面正常打开，cookie 78 字节 | ❌ **API 仍 403** |
| headful + 窗口移出屏幕 | ✅ | ✅ 200 |

**根因**：headless 的 UA 里带 `HeadlessChrome`，Ozon 直接拒。把 UA 改成正常的之后，
页面能开、cookie 也能拿到（9 个，含 `abt_data`），但**用这份 cookie 从外部打 API 仍然 403** ——
说明 challenge 通过时签发的 `abt_data` 还绑了更深的指纹（WebGL/字体等 headless 与 headful 的差异）。

结论：**headless 拿的 cookie 是废的**，只能 headful（哪怕窗口在屏幕外），或者直接读现有浏览器的 cookie。

所以「静默」只能靠把窗口丢到屏幕外，不能靠 headless。

### 什么时候需要预热

| 脚本 | 需要预热吗 |
|---|---|
| `ozon_http.py`（店铺/类目） | page 1 需要，page 2+ 不需要 |
| `ozon_search.py`（关键词） | 需要（page 1 是搜索结果头部，最值钱） |
| `ozon_image.py`（图搜） | 需要（上传接口要会话） |
| `ozon_detail.py`（详情） | 需要（全端点都要） |

脚本会自动检测缓存，没有就预热一次写进 `~/.cache/ozon-search/`。

### 强制刷新 cookie

```bash
rm -rf ~/.cache/ozon-search/
```

下次运行任何脚本都会重新预热。

---

## 三、指纹与 header 的最小集

实测能过的最小组合：

```python
H = {
    "accept": "application/json",
    "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
    "referer": "https://www.ozon.ru/",
    "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": <真实 Chrome UA>,
    # cookie 可选（page 1 / 详情需要）
}
```

**不带** `x-o3-*` 那一套也能过。那些是 SSR 渲染协商头（`x-o3-app-name: dweb_client`、`x-o3-manifest-version`、`x-page-view-id` 等），
实测加到 curl_cffi 里对 `/search/` 的 403 **没有任何帮助**。

一个反例：把 `x-o3-app-name` 改成 `seller-ui` 会让 curl **TLS 握手直接失败**（`curl: (35)`），说明这个头参与服务端路由分支，别乱加。

---

## 四、并发与限速实证

| 方式 | 吞吐 | 备注 |
|---|---|---|
| 单实例串行（类目页） | 2.5~3.6 s/页 = **2.2~3.2 SKU/s** | |
| 同实例并发 4 | 2.05 s/页 | 单请求延迟涨到 7.6s，摊平后没提升 |
| 同实例并发 8 | 2.25 s/页 | 反而更差 |
| **curl_cffi 24 线程** | **34.5~37.5 SKU/s** | 504 请求实测 99.2% 成功 |
| 多个浏览器实例（不同 profile） | 8.2 SKU/s | 不如直接 HTTP |

关键：**服务端按会话限速**，堆浏览器实例没用；但 HTTP 多线程（同 TLS 指纹）能到 30+ SKU/s，
说明限速维度主要是「会话/cookie」而不是「IP + 指纹」。

### 4.1 用多个 cookie 突破会话限速（实测有效）

既然限速是按会话的，那 N 个会话就能叠加：

| 配置 | 吞吐 | 成功率 |
|---|---|---|
| 1 cookie × 24 并发 | 66~98 SKU/s | 95% |
| 1 cookie × **40 并发** | **4 SKU/s** | **2%**（会话被打崩） |
| 4 cookie × 64 并发（16/会话） | **208~248 SKU/s** | 96~100% |
| 4 cookie × 96 并发（24/会话） | 243~341 SKU/s | 74%（过载） |

- **每会话并发甜点 16**（不是越多越好，40 会崩）
- 每个 cookie 有约 **100~150 页**的新鲜额度，用完后转 403
- `prepare_pool.py --force` 重新预热（8 秒）立刻恢复
- `pool_client.py` 在 403 累积到 30 次时自动补池，采集不中断

所以「多备用无痕浏览器 cookie」这件事是**真的有用**，收益接近线性。

---

## 五、被封了怎么判断

| 现象 | 含义 | 处理 |
|---|---|---|
| 307 循环 | TLS 指纹不对 | 换 curl_cffi |
| 403 `fab_chlg_...` | 缺 cookie 或会话被挑战 | 预热拿新 cookie |
| 403 `fab_...`（无 chlg） | 行为风控 | 停 5~40 分钟 |
| `page.fetch timed out`（浏览器） | 会话被降速 | 换 profile / 等 |
| `curl: (35) TLS connect error` | 本地网络或指纹异常 | 重试 / 换 impersonate |
