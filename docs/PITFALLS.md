# 踩过的坑（每个都花了时间，别再踩）

## 1. 死锁：`log()` 里拿同一把锁

**症状**：采集器跑起来只打了一条 `upload` 日志，然后永远挂住，没有任何报错，`ps` 能看到进程活着。

**原因**：

```python
_lock = threading.Lock()

def fetch(n):
    with _lock:          # ← 拿到锁
        ...
        log({...})       # ← log 内部又 with _lock → 不可重入 → 死锁

def log(o):
    with _lock:          # ← 永远等不到
        ...
```

**修法**：日志用独立的锁 `_loglock`。

```python
_lock = threading.Lock()      # 数据
_loglock = threading.Lock()   # 日志

def log(o):
    with _loglock:
        ...
```

这个坑导致图搜脚本卡了两轮调试，最后发现跟 Ozon 一点关系没有。

---

## 2. `cr.post(multipart=...)` 污染全局 handle

**症状**：上传图片成功（200），之后所有请求无响应、卡到超时。

**原因**：模块级 `curl_cffi.requests.post(..., multipart=...)` 会污染全局 curl handle。

**修法**：上传和翻页用**同一个 `Session` 对象**，且不要 `close()`。

```python
S = cr.Session(impersonate="chrome")
r = S.post(upload_url, headers=UP_H, multipart=mp, timeout=90)
mp.close()
# 后续翻页继续用 S（不要 close，不要新建）
r = S.get(list_url, headers=H, timeout=25)
```

反面教材（都试过，都会卡）：
- 上传用独立 Session + `close()` → 后续卡
- 上传用模块级 `cr.post` → 后续卡
- 每请求新建 Session → 部分情况卡

---

## 3. cookie 缓存按文件名排序 → 拿到过期 cookie

**症状**：手测 200，脚本 403，同一份 cookie。

**原因**：

```python
sorted(glob.glob(CACHE + "/*.json"))[-1]   # 按文件名排序！
```

`kw______.json`（11 小时前）排在 `image.json`（1 分钟前）前面，脚本拿到的是过期 cookie。

**修法**：

```python
sorted(glob.glob(CACHE + "/*.json"), key=os.path.getmtime, reverse=True)
+ 加年龄过滤（< 12 小时）
```

---

## 4. multipart 的字段名不是猜出来的

**症状**：图搜 URL 透传，JSON body 试了 18 种字段名（`url` / `image_url` / `imageUrl` / `link` / `src` / `photo_url` …）**全部 500**。

**真相**：它不是 JSON 接口，是 multipart 表单，而且 URL 要用**纯文本字段**：

```python
mp = CurlMime()
mp.addpart(name="url", data="https://...jpg".encode())   # 文本字段，不是文件
```

`500 rpc error: Internal` 的含义：**端点存在，参数不对**（区别于 404 = 端点不存在）。

---

## 5. `curl_cffi` 的 multipart API 有两个版本

```python
# 0.13.0 的正确写法
from curl_cffi import CurlMime
mp = CurlMime()
mp.addpart(name="file", data=bytes, filename="blob", content_type="image/jpeg")
r = cr.post(url, multipart=mp)
mp.close()
```

错误写法（都会报错）：
- `files={"file": (...)}` → `files is not supported, use multipart`
- `multipart={"file": (...)}` → `'dict' object has no attribute '_form'`
- `mp.addpart(name=..., content=...)` → `unexpected keyword argument 'content'`（要用 `data=`）

---

## 6. `/search/?text=X` 不是 HTTP 302

**我一开始的判断是错的**（后来 worker 用 CDP 抓 Document 链纠正）：

```
RESP 200  /search/?...text=сквиш            x-o3-page-type=search
RESP 200  /category/igrushki-antistress-7181/?...   x-o3-page-type=category
```

两条 Document 请求都是 200，没有 `Location` 头，也没有 `redirectResponse`。
是**前端 JS 执行 `location.replace`** 跳到预测类目。

含义：
- 纯 HTTP 拿不到「跳转后的地址」（因为跳转发生在 JS 里）
- 但**带 cookie 后可以直接打 `/search/` 端点**，不需要转类目
- `/search/` 的结果字面匹配率 ~88%，高于类目页的 ~71%（其实是更好的数据源）

---

## 7. page 1 单独有保护

无 cookie 时：

```
page 1   → 403（连试 5 次全 403）
page 2   → 200
page 3   → 200
```

同一秒内，p1 403、p2 200 → 稳定的端点级差异，不是 IP 限流。
带上 cookie 后 p1 也 200。

**影响**：如果不想预热，可以从 page 2 开始抓，牺牲前 8 条。

---

## 8. 每页条数是硬的，参数改不动

试过的全部无效：

```
per_page=40 / limit=40 / page_size=40 / items_per_page=40 / layout_page_index=2&per_page=40
```

| 场景 | 每页条数 |
|---|---|
| 列表（类目/搜索/店铺） | 8 |
| 图搜 | 12 |
| 评论 | 30 |

响应 160KB 里商品数据只占 32KB（`filtersDesktop` 39KB + `catalogMenu` 13KB + metadata 60KB 都是浪费），
但服务端不给裁剪参数。体积也不是瓶颈——`content-encoding: br`，实际传输只有 ~20KB。

---

## 9. headless 过不了 antibot

```
--headless=new  →  title = "Похоже, нет соединения"，cookie 只有 3 个，全 403
headful + --window-position=-2400,-2400  →  正常
```

想静默只能把窗口丢到屏幕外，不能 headless。

---

## 10. 店铺页虚拟滚动

`infiniteVirtualPaginator.nextPage` 只给到第 2 页就 `null`（带 `layout_page_index=2` 参数的那种）。

**直接用 `?page=N` 递增**，能一直翻到底（实测 170 页 / 1275 SKU 无重复），不需要 `paginator_token`。

---

## 11. 打太密会被升级成行为风控

- `fab_chlg_*` = 会话级挑战，**清 cookie 换指纹立刻恢复**
- `fab_*`（无 chlg）= 行为级，**只能等 5~40 分钟**

触发对比：

| 行为 | 后果 |
|---|---|
| 24 线程 × 504 请求稳定批量 | 99.2% 成功，不触发 |
| 反复零散试 header 组合（几十次） | 触发了 |

**结论**：有节奏的批量比碎试安全。调试时每条件限 3~5 次，间隔 ≥2 秒。

---

## 12. `ozon_search.py` 的缓存 TTL 和实际寿命不一致

脚本里写 `COOKIE_TTL = 1800`（30 分钟），但实测 cookie 活过 11 小时。

如果只跑一次长任务没问题；如果要隔天跑，把 TTL 放大或直接复用 `~/.cache/ozon-search/` 里最新的那份（脚本已按 mtime 取最新 + 12 小时过滤）。
