#!/usr/bin/env python3
"""
Ozon 类目/搜索页 SKU 采集器 — 纯 HTTP（curl_cffi），零浏览器

关键：必须用 curl_cffi 的 impersonate（TLS/JA3 伪装成 Chrome）。
plain requests / curl 会被 403 fab_chlg —— 实测差异就在 TLS 指纹，不在 cookie。

实测（2026-10-29）：
  24 线程 × 21 页 = 504 请求 → 500 成功（99.2%），135.9s，29.4 SKU/s
  1000 SKU ≈ 34 秒；全量 9999 SKU ≈ 5.7 分钟
  内存 ≈ 50MB（对比 6 个 Chrome 实例 ≈ 1.8GB）

用法：
  python3 ozon_http.py --url "<类目/搜索页 URL>" --pages 1-0 --out out_http --threads 24
  python3 ozon_http.py --url "<URL>" --pages 1-200 --out out_c --threads 12
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from curl_cffi import requests as cr
except ImportError:
    print("需要 curl_cffi:  pip3 install --user curl_cffi")
    sys.exit(1)


CACHE = os.path.expanduser("~/.cache/ozon-search")
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def _chrome():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def load_creds(max_age=12 * 3600):
    """读最近一次预热缓存的 cookie（按 mtime 取最新，不能按文件名排）"""
    files = sorted(glob.glob(os.path.join(CACHE, "*.json")), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            d = json.load(open(f))
            if d.get("cookie") and time.time() - d.get("at", 0) < max_age:
                return d
        except Exception:
            pass
    return None


def warm_creds(port=9970, timeout=45):
    """静默预热：起 headful Chrome（窗口移出屏幕）→ 过 antibot challenge → 导出 cookie

    注意：headless 过不了 challenge（实测 title='Похоже, нет соединения'）。
    """
    chrome = _chrome()
    if not chrome:
        return None
    try:
        import websocket
    except ImportError:
        print("[!] 需要 websocket-client：pip3 install --user websocket-client")
        return None
    prof = tempfile.mkdtemp(prefix="ozon-warm-")
    p = subprocess.Popen([chrome, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1200,800",
        "--window-position=-2400,-2400", "--disable-blink-features=AutomationControlled", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        for _ in range(80):
            time.sleep(0.4)
            try:
                d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
                pages = [t for t in d if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
                    break
            except Exception:
                pass
        if not ws:
            return None
        cnt = [0]
        def call(m, params=None, tmo=60):
            cnt[0] += 1
            mid = cnt[0]
            ws.send(json.dumps({"id": mid, "method": m, "params": params or {}}))
            t0 = time.time()
            while time.time() - t0 < tmo:
                r = json.loads(ws.recv())
                if r.get("id") == mid:
                    return r
            raise TimeoutError(m)
        def ev(e):
            r = call("Runtime.evaluate", {"expression": e, "awaitPromise": True, "returnByValue": True})
            return r.get("result", {}).get("result", {}).get("value")
        call("Page.enable"); call("Runtime.enable"); call("Network.enable")
        call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(2.5)
            if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0) > 10:
                break
        cks = [c for c in call("Network.getAllCookies").get("result", {}).get("cookies", []) if "ozon" in (c.get("domain") or "")]
        if not cks:
            return None
        d = {"cookie": "; ".join(f"{c['name']}={c['value']}" for c in cks),
             "ua": ev("navigator.userAgent"), "n_cookies": len(cks), "at": time.time()}
        os.makedirs(CACHE, exist_ok=True)
        json.dump(d, open(os.path.join(CACHE, "http.json"), "w"))
        return d
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

def build_headers(creds=None):
    h = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
        "referer": "https://www.ozon.ru/",
        "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": (creds or {}).get("ua") or UA,
    }
    if creds and creds.get("cookie"):
        h["cookie"] = creds["cookie"]
    return h

try:
    from pool_client import PoolClient, CONCURRENCY_PER_COOKIE
except ImportError:
    PoolClient = None

STOP = threading.Event()
_lock = threading.Lock()


def num(s):
    if s is None:
        return None
    c = re.sub(r"[^\d.,-]", "", str(s).replace("\u202f", "").replace("\u00a0", "").replace(" ", "")).replace(",", ".")
    if not c:
        return None
    try:
        v = float(c)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def count_num(s):
    if s is None:
        return None
    m = re.search(r"\d[\d\s\u202f\u00a0.,]*", str(s))
    if not m:
        return None
    v = re.sub(r"[\s\u202f\u00a0.,]", "", m.group(0))
    return int(v) if v else None


def parse_items(text):
    try:
        ws = json.loads(text).get("widgetStates") or {}
    except Exception:
        return []
    for k, v in ws.items():
        if k.startswith("tileGridDesktop"):
            try:
                return json.loads(v).get("items") or []
            except Exception:
                return []
    return []


def parse_tile(it, page_no):
    o = {"sku": it.get("sku") or it.get("id"), "page": page_no}
    act = it.get("action") or {}
    if act.get("link"):
        o["link"] = act["link"].split("?")[0]
    ti = it.get("tileImage") or {}
    its = ti.get("items") or []
    if its and its[0].get("image"):
        o["image"] = its[0]["image"].get("link")
    for st in it.get("mainState") or []:
        t = st.get("type")
        if t == "priceV2":
            pr = (st.get("priceV2") or {}).get("price") or []
            if pr:
                o["price"] = num(pr[0].get("text"))
            if len(pr) > 1:
                o["original_price"] = num(pr[1].get("text"))
            o["discount_pct"] = num((st.get("priceV2") or {}).get("discount"))
        elif t == "textDS":
            ds = st.get("textDS") or {}
            txt = ds.get("text") or ""
            aid = st.get("id") or ((ds.get("testInfo") or {}).get("automatizationId") or "")
            if aid == "name":
                o["title"] = txt.strip()
            elif "仅剩" in txt:
                o["stock_hint"] = txt.strip()
        elif t == "labelListV2":
            texts = [x.get("text", {}).get("text") for x in ((st.get("labelListV2") or {}).get("items") or []) if x.get("text")]
            texts = [x for x in texts if x]
            if texts:
                o["rating"] = num(texts[0])
                if len(texts) > 1:
                    o["reviews"] = count_num(texts[1])
    tgi = it.get("trackingInfo") or {}
    o["is_advert"] = bool(((tgi.get("click") or {}).get("custom") or {}).get("advertLite"))
    # 库存：实测路径 multiButton.ozonButton.addToCart.quantityButton.maxItems
    # （兼容变体：ozonButton.quantityButton / multiButton.quantityButton / mainState）
    mb = it.get("multiButton") or {}
    ob = mb.get("ozonButton") or {}
    qb = ((ob.get("addToCart") or {}).get("quantityButton")
          or ob.get("quantityButton") or mb.get("quantityButton") or {})
    o["stock_max"] = qb.get("maxItems")
    if o["stock_max"] is None:
        for st in it.get("mainState") or []:
            if st.get("type") == "quantityButton":
                o["stock_max"] = (st.get("quantityButton") or {}).get("maxItems")
                break
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--pages", default="1-0", help="start-end；end=0 抓到空页")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--out", required=True)
    ap.add_argument("--impersonate", default="chrome", help="curl_cffi 的 TLS 指纹目标")
    ap.add_argument("--retry", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--no-cookie", action="store_true", help="不带 cookie（page 1 会 403，但省掉预热）")
    ap.add_argument("--pool", type=int, default=0, help="用 N 个 cookie 轮换（0=单一 cookie；>=2 提速数倍）")
    ap.add_argument("--browser", help="从本机浏览器直接读 cookie（chrome/edge/brave/safari），零窗口零预热")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "run.log"), "a", encoding="utf-8")

    def log(o):
        with _lock:
            logf.write(json.dumps({"t": time.strftime("%H:%M:%S"), **o}, ensure_ascii=False) + "\n")
            logf.flush()

    u = a.url if a.url.startswith("http") else "https://www.ozon.ru" + a.url
    p = urllib.parse.urlparse(u)
    base_path, base_q = p.path, p.query

    s, _, e = a.pages.partition("-")
    p_from = int(s)
    p_to = int(e) if e else p_from
    until_end = (p_to == 0)

    def build(n):
        params = [(k, v) for k, v in urllib.parse.parse_qsl(base_q) if k != "page"] + [("page", str(n))]
        path = base_path + "?" + urllib.parse.urlencode(params)
        return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")

    skus = {}
    stat = {"ok": 0, "fail": 0, "pages": 0}

    def fetch(n):
        if STOP.is_set():
            return
        url = build(n)
        for attempt in range(a.retry + 1):
            t0 = time.time()
            try:
                r = pc.get(url, timeout=a.timeout) if pc else cr.get(url, headers=HEADERS, impersonate=a.impersonate, timeout=a.timeout)
                ms = int((time.time() - t0) * 1000)
                if r.status_code != 200:
                    log({"ev": "bad", "p": n, "s": r.status_code, "a": attempt})
                    if r.status_code == 403:
                        time.sleep(3)
                    continue
                items = parse_items(r.text)
                if not items:
                    log({"ev": "empty", "p": n})
                    STOP.set()
                    return
                new = 0
                with _lock:
                    for it in items:
                        row = parse_tile(it, n)
                        if row["sku"] and row["sku"] not in skus:
                            skus[row["sku"]] = row
                            new += 1
                    stat["ok"] += 1
                    stat["pages"] += 1
                    if stat["pages"] % 10 == 0:
                        json.dump({"pages": stat["pages"], "skus": len(skus), "at": time.strftime("%H:%M:%S")},
                                  open(os.path.join(out, "progress.json"), "w"))
                log({"ev": "page", "p": n, "n": len(items), "new": new, "ms": ms, "total": len(skus)})
                return
            except Exception as ex:
                log({"ev": "err", "p": n, "a": attempt, "msg": str(ex)[:60]})
                time.sleep(1.5)
        with _lock:
            stat["fail"] += 1

    creds = None
    if a.browser:
        try:
            from cookie_from_browser import creds_from_browser
            creds = creds_from_browser(a.browser)
            if creds:
                print(f"[+] 从 {a.browser} 读到 cookie（{creds['n_cookies']} 个，零窗口）")
            else:
                print(f"[!] {a.browser} 里没有可用的 ozon cookie，回退到缓存/预热")
        except ImportError:
            print("[!] 缺 browser_cookie3：pip3 install --user browser-cookie3")
    if not creds and not a.no_cookie:
        creds = load_creds()
    if not creds and not a.no_cookie:
        print("[*] 无可用 cookie，静默预热一次（约 13 秒，page 1 需要它）...")
        creds = warm_creds()
    HEADERS = build_headers(creds)
    if creds:
        print(f"[+] cookie {creds.get('n_cookies') or creds.get('n') or '?'} 个")

    pc = None
    if a.pool >= 2 and PoolClient:
        pc = PoolClient(n=a.pool)
        HEADERS = pc.headers_for(0)
        if a.threads <= 16:
            a.threads = pc.recommended_threads()
        print(f"[+] cookie 池: {len(pc.pool)} 会话 → {a.threads} 线程")
    log({"ev": "start", "base": base_path, "from": p_from, "to": p_to, "threads": a.threads,
         "imp": a.impersonate, "cookie": bool(creds)})
    t0 = time.time()

    # 分块批量提交，遇到空页能及时停
    CHUNK = a.threads * 4
    n = p_from
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        while not STOP.is_set():
            batch = []
            for _ in range(CHUNK):
                if not until_end and n > p_to:
                    break
                batch.append(n)
                n += 1
            if not batch:
                break
            list(ex.map(fetch, batch))
            if not until_end and n > p_to:
                break

    wall = time.time() - t0
    rows = sorted(skus.values(), key=lambda r: (r["page"], r["sku"]))
    with open(os.path.join(out, "skus.txt"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(str(r["sku"]) + "\n")
    with open(os.path.join(out, "products.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    log({"ev": "done", "wall": round(wall, 1), "pages": stat["pages"], "fail": stat["fail"], "skus": len(rows)})
    print(f"\n== done ==")
    print(f"pages {stat['pages']}  fail {stat['fail']}  wall {wall:.1f}s")
    print(f"unique SKU {len(rows)}")
    if wall > 0:
        print(f"throughput {stat['pages']/wall:.2f} pages/s = {stat['pages']/wall*8:.1f} SKU/s")
    prices = [r["price"] for r in rows if r.get("price")]
    if prices:
        prices.sort()
        print(f"price {prices[0]} ~ {prices[-1]} ₽, median {prices[len(prices)//2]} ₽")
    print(f"-> {out}/skus.txt  {out}/products.jsonl")
    if pc:
        print(f"[pool] {pc.stats()}")
    logf.close()


if __name__ == "__main__":
    main()
