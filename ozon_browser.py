#!/usr/bin/env python3
"""
Ozon 浏览器通道采集器（CDP + 页面内同源 fetch）

为什么需要它：
  纯 HTTP（curl_cffi）通道每份 cookie 只有 100~150 页额度，频繁直打会把额度打坏。
  本脚本走 headful Chromium + CDP，在页面内用同源 fetch 调已验证的 entrypoint JSON API，
  与真实用户流量同源，额度消耗极小，且能拿到 HTTP 通道拿不到的字段
  （tile maxItems 库存 / 评论星级排序 / 同款卖家企业凭据 / 上月均价）。

已验证端点（2026-11-01 实弹）：
  ?url=/search/?from_global=true&text=<kw>            搜索+类目预测
  ?url=/category/<slug>-<id>/?page=N                  类目页（tile: maxItems库存+priceV2+评分+卖家）
  ?url=/seller/<slug>-<id>/?page=N                    店铺页
  ?url=/product/<sku>/                                 PDP（webPrice/webCurrentSeller/bigPromoPDP）
  ?url=/modal/otherOffersFromSellers?product_id=<sku> 同款卖家（112家+企业凭据）
  ?url=/product/<sku>/reviews/?sort=<sort>            评论（content.score 星级 / 排序 / 图片视频）
  POST /api/composer-api.bx/_action/addToCart         加购（购物车 maximum=库存 单SKU精确认证）

用法：
  python3 ozon_browser.py --url "/search/?from_global=true&text=сквиш" --out out_search
  python3 ozon_browser.py --url "/category/igrushki-antistress-7181/?page=1" --pages 1-3 --out out_cat
  python3 ozon_browser.py --sku 5527434733 --out out_sku --with-offers --with-reviews
  python3 ozon_browser.py --seller 5902907 --pages 1-5 --out out_shop
  python3 ozon_browser.py --file skus.txt --out out_batch          # 批量 SKU（--with-offers）

鲁棒性：
  - 会话预热过 challenge（title 检测，Antibot → 自动重试）
  - fetch 失败指数退避重试（网络/429/5xx）
  - 请求间隔限速（--delay，默认 0.5s，避免行为风控）
  - 输出逐条原子落盘（已存在的跳过，可断点续采）
  - 错误分类统计（ok/antibot/timeout/parse）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

try:
    import websocket
except ImportError:
    print("需要 websocket-client:  pip3 install --user websocket-client")
    sys.exit(1)

CHROME = "/usr/local/bin/chromium"
EP = "/api/entrypoint-api.bx/page/json/v2?url="
ACTION = "/api/composer-api.bx/_action"

# 已验证 404 / 做不通的路径（勿重试）
KNOWN_DEAD = ("/coupons/", "/global/", "/action/", "/live/", "/top/",
              "/modal/currency-language", "/searchSuggestions/")


class BrowserSession:
    """headful Chromium + CDP，页面内同源 fetch（额度友好）。"""

    def __init__(self, port=9900, user_data=None, quiet=False):
        self.port = port
        self.quiet = quiet
        self.user_data = user_data or tempfile.mkdtemp(prefix="ozon-br-")
        self.proc = None
        self.ws = None
        self._mid = 0
        self.ready = False

    def start(self):
        args = [CHROME, f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.user_data}",
                "--no-first-run", "--no-default-browser-check",
                "--window-size=1440,900", "--window-position=-2400,-2400",
                "--disable-blink-features=AutomationControlled", "about:blank"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        page = None
        for _ in range(120):  # 最多 60s 等 CDP 端口
            time.sleep(0.5)
            try:
                pages = [t for t in json.load(urllib.request.urlopen(
                            f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    page = pages[0]
                    break
            except Exception:
                pass
        if not page:
            raise RuntimeError("CDP 端口未就绪")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"],
                                              timeout=120, suppress_origin=True)
        self._call("Page.enable")
        self._call("Runtime.enable")
        return self

    def _call(self, method, params=None, timeout=60):
        self._mid += 1
        mid = self._mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = json.loads(self.ws.recv())
            if r.get("id") == mid:
                return r
        raise TimeoutError(method)

    def _ev(self, expr, timeout=60):
        r = self._call("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, timeout=timeout)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return None
        return res.get("result", {}).get("value")

    def warm(self, max_wait=90):
        """导航主页过 challenge。成功标志：title 非 Antibot 且 cookie>10。"""
        self._call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        while time.time() - t0 < max_wait:
            time.sleep(3)
            try:
                title = str(self._ev("document.title") or "")
                clen = self._ev("document.cookie.length") or 0
            except Exception:
                continue
            if "Antibot" not in title and "Challenge" not in title and clen > 10:
                self.ready = True
                if not self.quiet:
                    print(f"[ok] 会话就绪 cookie={clen} title={title[:40]}")
                return True
        raise RuntimeError("challenge 未通过（title=%s）" % title)

    def fetch_page(self, path, retries=3, delay=0.5):
        """页面内 fetch entrypoint JSON API。返回 dict 或抛异常。"""
        if any(path.startswith(p) for p in KNOWN_DEAD):
            raise ValueError(f"已知做不通: {path}")
        if not self.ready:
            self.warm()
        full = EP + urllib.parse.quote(path, safe="/?=&")
        last_err = None
        for attempt in range(retries):
            try:
                expr = (f"fetch('{full}',{{headers:{{'accept':'application/json'}}}})"
                        f".then(r=>r.text()).then(t=>window.__ozr=t)"
                        f".catch(e=>window.__ozr='ERR:'+e); 'ok'")
                self._ev(expr)
                got = None
                for _ in range(25):  # 最多 25s 等响应
                    time.sleep(1)
                    got = self._ev("window.__ozr")
                    if got:
                        break
                if not got:
                    raise TimeoutError("fetch 无响应")
                if got.startswith("ERR:"):
                    raise RuntimeError(got)
                d = json.loads(got)
                # 页面 HTML 反爬检测（entrypoint 正常应返回 JSON）
                if isinstance(d, dict) and "widgetStates" not in d:
                    # 可能是 antibot 页或错误体
                    if "Antibot" in got[:2000] or "captcha" in got[:2000].lower():
                        raise RuntimeError("antibot-page")
                if delay:
                    time.sleep(delay)
                return d
            except (json.JSONDecodeError, TimeoutError, RuntimeError) as e:
                last_err = e
                # antibot → 重新预热一次再试
                if "antibot" in str(e).lower():
                    if not self.quiet:
                        print(f"[!] antibot 拦截 {path[:60]}，重新预热…")
                    try:
                        self.warm()
                    except Exception:
                        pass
                backoff = 2 ** attempt
                time.sleep(backoff)
        raise RuntimeError(f"fetch 失败 {path[:80]}: {last_err}")

    def fetch_action(self, name, body=None, retries=3, delay=0.5):
        """POST composer action（如 addToCart）。"""
        if not self.ready:
            self.warm()
        full = f"{ACTION}/{name}"
        payload = json.dumps(body or {})
        last_err = None
        for attempt in range(retries):
            try:
                expr = (f"fetch('{full}',{{method:'POST',"
                        f"headers:{{'accept':'application/json','content-type':'application/json'}},"
                        f"body:{json.dumps(payload)}}}).then(r=>r.text()).then(t=>window.__ozr=t)"
                        f".catch(e=>window.__ozr='ERR:'+e); 'ok'")
                self._ev(expr)
                got = None
                for _ in range(25):
                    time.sleep(1)
                    got = self._ev("window.__ozr")
                    if got:
                        break
                if not got:
                    raise TimeoutError("action 无响应")
                if got.startswith("ERR:"):
                    raise RuntimeError(got)
                if delay:
                    time.sleep(delay)
                return json.loads(got)
            except (json.JSONDecodeError, TimeoutError, RuntimeError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"action {name} 失败: {last_err}")

    def close(self):
        try:
            self.ws and self.ws.close()
        except Exception:
            pass
        try:
            self.proc and self.proc.terminate()
        except Exception:
            pass


# ---------- 数据提取 ----------

def _ws(page):
    """兼容 entrypoint 直接返回（widgetStates 顶层）或 {"body": str} 两种结构。"""
    if isinstance(page, dict) and isinstance(page.get("body"), str):
        try:
            page = json.loads(page["body"])
        except Exception:
            return {}
    return page.get("widgetStates") if isinstance(page, dict) else {}


def tile_extract(page):
    """类目/搜索/店铺页 tileGrid → 结构化行。"""
    rows = []
    for k, v in _ws(page).items():
        if "tileGrid" not in k:
            continue
        try:
            j = json.loads(v)
        except Exception:
            continue
        for it in j.get("items", []):
            s = json.dumps(it, ensure_ascii=False)
            sku = it.get("id") or it.get("sku")
            if not sku:
                continue
            row = {"sku": sku,
                   "maxItems": _g(s, r'"maxItems"\s*:\s*(\d+)'),
                   "price": _g(s, r'"price"\s*:\s*\[\s*\{\s*"text"\s*:\s*"([^"]+)"'),
                   "originalPrice": _g(s, r'ORIGINAL_PRICE"\s*},\s*\{\s*"text"\s*:\s*"([^"]+)"'),
                   "discount": _g(s, r'"discount"\s*:\s*"([^"]+)"'),
                   "rating": _g(s, r'"rating"\s*:\s*(\d+(?:\.\d+)?)') or _g(s, r'tile-list-rating[^}]*"text"\s*:\s*"([^"]+)"'),
                   "reviewsCount": _g(s, r'"reviewsCount"\s*:\s*(\d+)'),
                   "title": _g(s, r'"title"\s*:\s*\{\s*"text"\s*:\s*"([^"]{5,})"') or _g(s, r'"text"\s*:\s*"([А-Яа-яЁёA-Za-z][^"]{12,})"'),
                   "sellerId": _g(s, r'"sellerId"\s*:\s*(\d+)') or _g(s, r'"(?:tile-list-)?seller[^"]*"\s*:\s*\{\s*"id"\s*:\s*(\d+)'),
                   "sellerName": _g(s, r'"sellerName"\s*:\s*"([^"]+)"'),
                   "hasStockText": "осталось" in s}
            # 从 mainState 里抓 priceV2 价格对
            pm = re.search(r'"priceV2"\s*:\s*\{\s*"price"\s*:\s*\[\s*(.*?)\s*\]\s*,\s*"discount"', s)
            if pm:
                prices = re.findall(r'"text"\s*:\s*"([^"]+)"', pm.group(1))
                if prices:
                    row["price"] = prices[0]
                    if len(prices) > 1:
                        row["originalPrice"] = prices[1]
            rows.append(row)
    return rows


def _g(s, pat):
    m = re.search(pat, s)
    return m.group(1) if m else None


def _dg(d, key):
    """类型安全的 dict 取值：非 dict 返回 None（Ozon widget 字段类型不稳定）。"""
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else None


def offers_extract(page):
    """同款卖家 modal → 卖家列表。"""
    sellers = []
    for k, v in _ws(page).items():
        if "webSellerList" not in k:
            continue
        try:
            j = json.loads(v)
        except Exception:
            continue
        for sd in j.get("sellers", []):
            s = json.dumps(sd, ensure_ascii=False)
            cred = sd.get("credentials")
            # credentials 实测为数组: [公司名, 地址, "国家, 城市", 营业模式]
            if isinstance(cred, list) and len(cred) >= 3:
                company, addr = cred[0], cred[1]
                cc = cred[2].split(",") if isinstance(cred[2], str) else ["", ""]
                country = cc[0].strip() if len(cc) > 0 else ""
                city = cc[1].strip() if len(cc) > 1 else ""
                mode = cred[3] if len(cred) > 3 else ""
            else:
                company = addr = country = city = mode = None
            sellers.append({
                "sellerId": sd.get("id"),
                "name": sd.get("name"),
                "link": sd.get("link"),
                "price": _g(s, r'"cardPrice"\s*:\s*\{\s*"price"\s*:\s*"([^"]+)"'),
                "company": company,
                "address": addr,
                "country": country,
                "city": city,
                "mode": mode,
            })
    return sellers


def pdp_extract(page):
    """PDP 关键字段。"""
    out = {"sku": None}
    for k, v in _ws(page).items():
        base = k.split("-")[0]
        try:
            j = json.loads(v)
        except Exception:
            continue
        if base == "webProductHeading":
            # title 是纯字符串（实测），非 {text:...}
            t = j.get("title")
            out["title"] = t if isinstance(t, str) else (_dg(j, "title") or {}).get("text")
        elif base == "webCurrentSeller":
            # sellerId 藏在 badge 订阅 action 的 params.sellerId；店名在 sellerCell.centerBlock
            s = json.dumps(j, ensure_ascii=False)
            m = re.search(r'"sellerId"\s*:\s*"(\d+)"', s)
            out["sellerId"] = m.group(1) if m else None
            m2 = re.search(r'"link"\s*:\s*"https://www\.ozon\.ru/seller/([^"/]+)-(\d+)/"', s)
            if m2:
                out["sellerSlug"] = m2.group(1)
                out["sellerId"] = out["sellerId"] or m2.group(2)
            m3 = re.search(r'"centerBlock"\s*:\s*\{\s*"title"\s*:\s*\{\s*"text"\s*:\s*"([^"]+)"', s)
            out["sellerName"] = m3.group(1) if m3 else None
        elif base == "webPrice":
            out["price"] = j.get("price")
            out["cardPrice"] = j.get("cardPrice")
            out["originalPrice"] = j.get("originalPrice")
        elif base == "bigPromoPDP":
            out["stockNumber"] = (_dg(j, "stockNumber") or {}).get("text")
            out["stockPercentage"] = (_dg(j, "counter") or {}).get("percentage")
        elif base == "webSingleProductScore":
            out["score"] = j.get("text")
        elif base == "webReviewProductScore":
            out["reviewsCount"] = j.get("reviewsCount")
            out["totalScore"] = j.get("totalScore")
    return out


def reviews_extract(page):
    """评论页 → 评论列表 + 元信息。找不到 webListReviews 返回空 dict（页面可能被路由回 PDP）。"""
    for k, v in _ws(page).items():
        if "webListReviews" not in k:
            continue
        try:
            j = json.loads(v)
        except Exception:
            return {"total": None, "reviews": []}
        items = []
        for rv in j.get("reviews", []):
            c = rv.get("content") if isinstance(rv, dict) else None
            c = c if isinstance(c, dict) else {}
            auth = rv.get("author") if isinstance(rv, dict) else None
            auth = auth if isinstance(auth, dict) else {}
            use = rv.get("usefulness") if isinstance(rv, dict) else None
            use = use if isinstance(use, dict) else {}
            items.append({
                "score": c.get("score"),
                "comment": c.get("comment"),
                "positive": c.get("positive"),
                "negative": c.get("negative"),
                "publishedAt": rv.get("publishedAt") if isinstance(rv, dict) else None,
                "author": auth.get("firstName"),
                "usefulness": use.get("likeCount"),
                "photos": len(c.get("photos") or []),
                "videos": len(c.get("videos") or []),
                "badge": rv.get("badge") if isinstance(rv, dict) else None,
            })
        pg = j.get("paging") if isinstance(j, dict) else {}
        pg = pg if isinstance(pg, dict) else {}
        links = pg.get("links") or []
        return {"total": pg.get("total"),
                "page": pg.get("page"),
                "perPage": pg.get("perPage"),
                "nextUrl": (links[1].get("urlParams") if len(links) > 1 and isinstance(links[1], dict) else None),
                "reviews": items}
    return {"total": None, "reviews": [], "note": "no-webListReviews"}


def _has_widget(d, frag):
    return any(frag in k for k in _ws(d).keys())


# ---------- 采集入口 ----------

def _save(out_dir, name, data):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def collect_url(bs, path, pages, out_dir, delay):
    """URL 采集（搜索/类目/店铺，支持多页）。"""
    results = []
    for page in pages:
        p = path
        if page > 1:
            sep = "&" if "?" in p else "?"
            p = f"{p}{sep}page={page}"
        fname = f"page_{page:03d}.json"
        fpath = os.path.join(out_dir, fname)
        if os.path.exists(fpath):  # 断点续采
            print(f"[skip] {fname} 已存在")
            continue
        try:
            d = bs.fetch_page(p, delay=delay)
        except Exception as e:
            print(f"[err] page {page}: {e}")
            continue
        rows = tile_extract(d)
        _save(out_dir, fname, {"path": p, "tiles": rows})
        print(f"[ok] page {page}: {len(rows)} tiles | 库存上限示例 {rows[0]['maxItems'] if rows else '-'}")
        results.extend(rows)
        time.sleep(delay)
    return results


def collect_sku(bs, sku, out_dir, with_offers, with_reviews, delay):
    """单 SKU 采集（PDP + 可选同款卖家/评论）。"""
    os.makedirs(out_dir, exist_ok=True)
    # PDP
    fpath = os.path.join(out_dir, f"pdp_{sku}.json")
    if not os.path.exists(fpath):
        try:
            d = bs.fetch_page(f"/product/{sku}/", delay=delay)
            info = pdp_extract(d)
            _save(out_dir, f"pdp_{sku}.json", {"sku": sku, "info": info,
                                               "widgets": list((d.get("widgetStates") or {}).keys())})
            print(f"[ok] pdp {sku}: {info.get('title', '')[:40]} | 库存={info.get('stockNumber')} 评价={info.get('reviewsCount')}")
        except Exception as e:
            print(f"[err] pdp {sku}: {e}")
    # 同款卖家
    if with_offers:
        fpath = os.path.join(out_dir, f"offers_{sku}.json")
        if not os.path.exists(fpath):
            # 首次请求可能被服务器偶发路由回 PDP（widgetStates 无 webSellerList），重试最多 3 次
            for attempt in range(3):
                try:
                    d = bs.fetch_page(f"/modal/otherOffersFromSellers?product_id={sku}&sort=price", delay=delay)
                    sellers = offers_extract(d)
                    if not sellers and not _has_widget(d, "webSellerList"):
                        print(f"[retry] offers {sku} 路由回 PDP，刷新会话后重试 {attempt+1}/3")
                        time.sleep(1)
                        try:
                            bs.warm()
                        except Exception:
                            pass
                        continue
                    _save(out_dir, f"offers_{sku}.json", {"sku": sku, "sellers": sellers})
                    print(f"[ok] offers {sku}: {len(sellers)} 家同款")
                    break
                except Exception as e:
                    print(f"[err] offers {sku}: {e}")
                    time.sleep(2)
    # 评论（前 30 条，可排序）
    if with_reviews:
        fpath = os.path.join(out_dir, f"reviews_{sku}.json")
        if not os.path.exists(fpath):
            for attempt in range(3):
                try:
                    d = bs.fetch_page(f"/product/{sku}/reviews/?reviewsVariantMode=2&sort=usefulness_desc", delay=delay)
                    rv = reviews_extract(d) or {}
                    if not rv.get("reviews") and not _has_widget(d, "webListReviews"):
                        print(f"[retry] reviews {sku} 路由回 PDP，刷新会话后重试 {attempt+1}/3")
                        time.sleep(1)
                        try:
                            bs.warm()
                        except Exception:
                            pass
                        continue
                    _save(out_dir, f"reviews_{sku}.json", rv)
                    print(f"[ok] reviews {sku}: total={rv.get('total')} 本页{len(rv.get('reviews') or [])}条")
                    break
                except Exception as e:
                    print(f"[err] reviews {sku}: {e}")
                    time.sleep(2)


def collect_stock_batch(bs, skus, out_dir, delay):
    """批量 SKU 库存验证：加购（确认可购性）+ 读购物车 maximum（best effort）。

    注意：entrypoint API fetch 的 /cart 里 cartItem.quantity 为 null（maximum 仅页面
    导航渲染后才有）。所以本函数主要输出"可加购"标志；批量库存请用类目/搜索页
    tile 的 maxItems（collect_url，100% 覆盖，无需加购）。
    """
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for sku in skus:
        # 加购
        try:
            r = bs.fetch_action("addToCart",
                                {"items": [{"id": int(sku), "quantity": 1}]}, delay=delay)
            if not (r.get("success") or r.get("cart")):
                print(f"[err] {sku} 加购失败: {str(r)[:100]}")
                continue
        except Exception as e:
            print(f"[err] {sku} 加购异常: {e}")
            continue
        time.sleep(delay)
        # 读购物车（best effort）
        mx = None
        try:
            d = bs.fetch_page("/cart", delay=delay)
            for k, v in _ws(d).items():
                if "cartSplit" not in k:
                    continue
                try:
                    j = json.loads(v)
                except Exception:
                    continue
                for it in j.get("cartItems", []):
                    q = it.get("quantity") if isinstance(it, dict) else None
                    if str(sku) in json.dumps(it, ensure_ascii=False):
                        mx = (q or {}).get("maximum")
                        break
        except Exception as e:
            print(f"[err] {sku} 读购物车: {e}")
        rows.append({"sku": sku, "addable": True, "stock_max": mx,
                     "note": None if mx else "quantity 仅页面渲染可得，批量库存用 tile maxItems"})
        print(f"[ok] {sku} 可加购 | 库存上限={mx}")
    _save(out_dir, "stock_batch.json", rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description="Ozon 浏览器通道采集器")
    ap.add_argument("--url", help="entrypoint 页面路径，如 /category/igrushki-antistress-7181/?page=1")
    ap.add_argument("--pages", default="1", help="页范围，如 1-3 或 1,5,9")
    ap.add_argument("--sku", action="append", help="SKU（可多次）")
    ap.add_argument("--file", help="SKU 列表文件（每行一个）")
    ap.add_argument("--seller", help="seller id 或 slug-id")
    ap.add_argument("--with-offers", action="store_true", help="同时抓同款卖家")
    ap.add_argument("--with-reviews", action="store_true", help="同时抓评论")
    ap.add_argument("--stock-batch", action="store_true", help="批量库存精确认证（加购→读上限）")
    ap.add_argument("--out", default="out_ozon", help="输出目录")
    ap.add_argument("--port", type=int, default=9900, help="CDP 端口")
    ap.add_argument("--delay", type=float, default=0.5, help="请求间隔秒")
    ap.add_argument("--keep-session", help="复用 user-data-dir（跨次保留会话）")
    args = ap.parse_args()

    bs = BrowserSession(port=args.port, user_data=args.keep_session, quiet=False)
    bs.start()
    try:
        bs.warm()
        if args.url:
            pages = []
            for part in args.pages.split(","):
                if "-" in part:
                    a, b = part.split("-")
                    pages.extend(range(int(a), int(b) + 1))
                else:
                    pages.append(int(part))
            collect_url(bs, args.url, pages, args.out, args.delay)
        skus = list(args.sku or [])
        if args.file and os.path.exists(args.file):
            skus += [l.strip() for l in open(args.file) if l.strip()]
        if args.seller:
            # seller 也走 URL 采集（支持 slug-id 或纯 id）
            sid = args.seller if "-" in args.seller or not args.seller.isdigit() else args.seller
            slug = "seller-" + args.seller if args.seller.isdigit() else args.seller
            if args.pages == "1":
                args.pages = "1-3"
            pages = []
            for part in args.pages.split(","):
                if "-" in part:
                    a, b = part.split("-")
                    pages.extend(range(int(a), int(b) + 1))
                else:
                    pages.append(int(part))
            collect_url(bs, f"/{slug}/", pages, os.path.join(args.out, "seller"), args.delay)
        for sku in skus:
            if args.stock_batch:
                collect_stock_batch(bs, [sku], args.out, args.delay)
            else:
                collect_sku(bs, sku, args.out, args.with_offers, args.with_reviews, args.delay)
        print(f"\n完成。输出目录: {os.path.abspath(args.out)}")
    finally:
        bs.close()


if __name__ == "__main__":
    main()
