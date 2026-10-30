#!/usr/bin/env python3
"""
Ozon 搜索/类目采集器 — 搜索词自动转类目 + 403 静默预热 + 纯 HTTP 并发

流程：
  1) 喂搜索词（keyword 或 /search/ URL）
  2) 缓存里有可用 cookie+类目地址且未过期 → 直接跑
  3) 否则静默起一个 Chrome（headful，窗口移到屏幕外，不打扰），
     打开搜索 URL → 过 antibot challenge → 被 302 到 /category/... → 导出 cookie
  4) 关闭浏览器，纯 HTTP（curl_cffi）并发抓 page 1..N
  5) 中途大面积 403 → 自动重新预热一次，接着跑

实测（2026-10-29）：
  - headless 模式过不了 challenge（title=Похоже, нет соединения）
  - headful + 窗口移出屏幕：约 13 秒拿到 /category/ 地址 + 8 个 cookie
  - 带这份 cookie，page 1 也 200（不带 cookie 时 page 1 恒 403）
  - 纯 HTTP 24 线程实测 34.5 SKU/s

用法：
  python3 ozon_search.py --kw "сквиш" --out out_kw
  python3 ozon_search.py --url "https://www.ozon.ru/search/?from_global=true&text=..." --out out_u
  python3 ozon_search.py --category "https://www.ozon.ru/category/xxx-7181/?text=..." --out out_c  # 跳过预热
"""
import argparse, json, os, re, subprocess, tempfile, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from curl_cffi import requests as cr
    import websocket
except ImportError:
    print("需要: pip3 install --user curl_cffi websocket-client")
    raise SystemExit(1)

try:
    from pool_client import PoolClient, CONCURRENCY_PER_COOKIE
except ImportError:
    PoolClient = None

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CACHE = os.path.expanduser("~/.cache/ozon-search")
VOID_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
COOKIE_TTL = 1800  # 30 分钟


def headers(ua=VOID_UA, cookie=None):
    h = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
        "referer": "https://www.ozon.ru/",
        "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": ua or VOID_UA,
    }
    if cookie:
        h["cookie"] = cookie
    return h


# ---------------- 静默预热 ----------------
def warm(url, port=9970, timeout=45, quiet=True):
    """起一个移出屏幕的 Chrome，打开 url，等 challenge 过并拿到最终地址 + cookie"""
    prof = tempfile.mkdtemp(prefix="ozon-warm-")
    cmd = [CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
           "--no-first-run", "--no-default-browser-check",
           "--window-size=1200,800", "--window-position=-2400,-2400",
           "--disable-blink-features=AutomationControlled", "about:blank"]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

        call("Page.enable")
        call("Runtime.enable")
        call("Network.enable")
        call("Page.navigate", {"url": url})
        final, ua = None, None
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(2)
            u = str(ev("location.href") or "")
            t = str(ev("document.title") or "")
            if "Challenge" not in u + t and "block" not in u and "Похоже" not in t:
                if u.startswith("https://www.ozon.ru/") and u.rstrip("/") != "https://www.ozon.ru":
                    final = u
                    ua = ev("navigator.userAgent")
                    break
        if not final:
            return None
        cks = call("Network.getAllCookies").get("result", {}).get("cookies", [])
        cks = [c for c in cks if "ozon" in (c.get("domain") or "")]
        cookie = "; ".join(f"{c['name']}={c['value']}" for c in cks)
        return {"final_url": final, "cookie": cookie, "ua": ua, "n_cookies": len(cks),
                "at": time.time()}
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()


def load_cache(key):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, re.sub(r"[^a-zA-Z0-9_.-]", "_", key)[:120] + ".json")
    try:
        d = json.load(open(f))
        if time.time() - d.get("at", 0) < COOKIE_TTL:
            return d
    except Exception:
        pass
    return None


def save_cache(key, d):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, re.sub(r"[^a-zA-Z0-9_.-]", "_", key)[:120] + ".json")
    json.dump(d, open(f, "w"), ensure_ascii=False)
    return f


# ---------------- 解析 ----------------
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


def cnt_num(s):
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
                    o["reviews"] = cnt_num(texts[1])
    tgi = it.get("trackingInfo") or {}
    o["is_advert"] = bool(((tgi.get("click") or {}).get("custom") or {}).get("advertLite"))
    return o


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", help="关键词，等价于 /search/?from_global=true&text=<kw>")
    ap.add_argument("--url", help="搜索页 URL 或 /search/ 路径")
    ap.add_argument("--category", help="已经是 category URL，跳过预热")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="1-0", help="start-end；end=0 抓到空页")
    ap.add_argument("--threads", type=int, default=0, help="0 = 自动（池大小 × 16，单 cookie 时 20）")
    ap.add_argument("--pool", type=int, default=0, help="用 N 个 headless 会话轮换（>=2 提速数倍）")
    ap.add_argument("--browser", help="从本机浏览器直接读 cookie（chrome/edge/...），零窗口零预热")
    ap.add_argument("--force-warm", action="store_true", help="忽略缓存，强制重新预热")
    ap.add_argument("--silent", action="store_true", default=True, help="预热窗口移出屏幕（默认开）")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "run.log"), "a", encoding="utf-8")
    lk = threading.Lock()

    def log(o):
        with lk:
            logf.write(json.dumps({"t": time.strftime("%H:%M:%S"), **o}, ensure_ascii=False) + "\n")
            logf.flush()

    # 1) 决定入口
    if a.category:
        base_path = urllib.parse.urlparse(a.category).path or a.category
        q = urllib.parse.urlparse(a.category).query
        if q:
            base_path += "?" + q
        creds = {"cookie": None, "ua": VOID_UA}
        entry = a.category
        log({"ev": "category-direct", "url": entry})
    else:
        if a.kw:
            entry = "https://www.ozon.ru/search/?from_global=true&text=" + urllib.parse.quote(a.kw)
            key = "kw:" + a.kw
        else:
            entry = a.url if a.url.startswith("http") else "https://www.ozon.ru" + a.url
            key = "url:" + entry
        creds = None
        if a.browser:
            try:
                from cookie_from_browser import creds_from_browser
                creds = creds_from_browser(a.browser)
                if creds:
                    print(f"[+] 从 {a.browser} 读到 cookie（{creds['n_cookies']} 个，零窗口）")
            except ImportError:
                print("[!] 缺 browser_cookie3：pip3 install --user browser-cookie3")
        creds = creds or (None if a.force_warm else load_cache(key))
        if creds:
            log({"ev": "cache-hit", "age": int(time.time() - creds["at"]), "final": creds["final_url"]})
        else:
            print("[*] 静默预热：起浏览器 → 过 challenge → 拿类目地址 + cookie（约 13 秒）")
            log({"ev": "warm-start", "entry": entry})
            creds = warm(entry)
            if not creds:
                print("[!] 预热失败：浏览器没拿到最终地址（可能 IP 被限或 challenge 未过）")
                log({"ev": "warm-fail"})
                raise SystemExit(2)
            save_cache(key, creds)
            log({"ev": "warm-ok", "final": creds["final_url"], "cookies": creds["n_cookies"]})
        print(f"[+] 类目地址: {creds['final_url'][:120]}")
        u = urllib.parse.urlparse(creds["final_url"])
        base_path = u.path + ("?" + u.query if u.query else "")

    s, _, e = a.pages.partition("-")
    p_from = int(s)
    p_to = int(e) if e else p_from
    until_end = (p_to == 0)

    def build(n):
        params = [(k, v) for k, v in urllib.parse.parse_qsl(urllib.parse.urlparse(base_path).query) if k != "page"]
        params += [("page", str(n))]
        path = urllib.parse.urlparse(base_path).path + "?" + urllib.parse.urlencode(params)
        return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")

    H = headers(creds.get("ua"), creds.get("cookie"))

    pc = None
    if a.pool >= 2 and PoolClient:
        pc = PoolClient(n=a.pool)
        H = pc.headers_for(0)
        if a.threads <= 0:
            a.threads = pc.recommended_threads()
        print(f"[+] cookie 池：{len(pc.pool)} 会话 → {a.threads} 线程")
    else:
        if a.threads <= 0:
            a.threads = 20
    skus, stat = {}, {"ok": 0, "fail": 0, "p403": 0, "empty": 0}
    stop = threading.Event()
    rewarm_lock = threading.Lock()
    rewarmed = [False]

    def maybe_rewarm():
        with rewarm_lock:
            if rewarmed[0]:
                return
            rewarmed[0] = True
        print("[!] 大面积 403，重新静默预热一次...")
        log({"ev": "rewarm"})
        enc = entry if not a.category else entry
        nc = warm(enc)
        if nc:
            H["cookie"] = nc.get("cookie")
            H["user-agent"] = nc.get("ua") or H.get("user-agent")
            save_cache("kw:" + (a.kw or ""), nc)
            log({"ev": "rewarm-ok", "cookies": nc.get("n_cookies")})
        else:
            log({"ev": "rewarm-fail"})

    def fetch(n):
        if stop.is_set():
            return
        url = build(n)
        for attempt in range(2):
            try:
                r = pc.get(url, timeout=45) if pc else cr.get(url, headers=H, impersonate="chrome", timeout=45)
                if r.status_code == 403:
                    with lk:
                        stat["p403"] += 1
                    if stat["p403"] == 5:
                        maybe_rewarm()
                    time.sleep(2)
                    continue
                if r.status_code != 200:
                    continue
                items = parse_items(r.text)
                if not items:
                    with lk:
                        stat["empty"] += 1
                    stop.set()
                    return
                new = 0
                with lk:
                    for it in items:
                        row = parse_tile(it, n)
                        if row["sku"] and row["sku"] not in skus:
                            skus[row["sku"]] = row
                            new += 1
                    stat["ok"] += 1
                    if stat["ok"] % 10 == 0:
                        json.dump({"pages": stat["ok"], "skus": len(skus)}, open(os.path.join(out, "progress.json"), "w"))
                log({"ev": "page", "p": n, "n": len(items), "new": new, "total": len(skus)})
                return
            except Exception as ex:
                log({"ev": "err", "p": n, "a": attempt, "msg": str(ex)[:50]})
                time.sleep(1.5)
        with lk:
            stat["fail"] += 1

    t0 = time.time()
    CHUNK = max(a.threads * 4, 8)
    n = p_from
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        while not stop.is_set():
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

    rows = sorted(skus.values(), key=lambda r: (r.get("page", 0), str(r["sku"])))
    with open(os.path.join(out, "skus.txt"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(str(r["sku"]) + "\n")
    with open(os.path.join(out, "products.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    log({"ev": "done", "wall": round(wall, 1), **stat, "skus": len(rows)})
    print(f"\n== done ==")
    print(f"pages ok={stat['ok']} 403={stat['p403']} fail={stat['fail']}  wall {wall:.1f}s")
    print(f"unique SKU {len(rows)}")
    if wall > 0 and stat["ok"]:
        print(f"throughput {stat['ok']/wall:.2f} pages/s = {stat['ok']/wall*8:.1f} SKU/s")
    prices = [r["price"] for r in rows if r.get("price")]
    if prices:
        prices.sort()
        print(f"price {prices[0]} ~ {prices[-1]} ₽, median {prices[len(prices)//2]} ₽")
    print(f"-> {out}/skus.txt")
    if pc:
        print(f"[pool] {pc.stats()}")
    logf.close()


if __name__ == "__main__":
    main()
