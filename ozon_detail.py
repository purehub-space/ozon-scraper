#!/usr/bin/env python3
"""
Ozon SKU 详情采集 — 纯 HTTP（curl_cffi）+ 复用 cookie 缓存

前置：先跑过一次 ozon_search.py（会静默预热并缓存 cookie 到 ~/.cache/ozon-search/）
      没有缓存也行，本脚本会自己静默预热一次。

实测（2026-10-29）：
  - 无 cookie：PDP1 / PDP2 / reviews / shop-info 全部 403
  - 带 cookie：全部 200
  - 24 SKU × 2 请求 = 48 req / 4.3 秒 → 5.56 SKU/s（含 PDP1+PDP2）
  - 1000 SKU 详情 ≈ 3 分钟

用法：
  python3 ozon_detail.py --skus out_full/skus.txt --out out_detail --threads 24
  python3 ozon_detail.py --skus out_full/skus.txt --out out_detail --reviews 1 --attachments
"""
import argparse, glob, json, os, re, subprocess, tempfile, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as cr

CACHE = os.path.expanduser("~/.cache/ozon-search")
try:
    from pool_client import PoolClient, CONCURRENCY_PER_COOKIE
except ImportError:
    PoolClient = None

from ozon_env import get_chrome_executable, detect_proxy

CHROME = get_chrome_executable() or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROXY = detect_proxy()
VOID_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_lock = threading.Lock()


# ---------- cookie ----------
def load_creds():
    files = sorted(glob.glob(os.path.join(CACHE, "*.json")), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            d = json.load(open(f))
            if d.get("cookie"):
                return d
        except Exception:
            pass
    return None


def warm_creds():
    """静默预热：起 Chrome（移出屏幕）→ 拿 cookie"""
    import websocket
    port = 9980
    prof = tempfile.mkdtemp(prefix="ozon-det-")
    cmd = [CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1200,800",
        "--window-position=-2400,-2400", "--disable-blink-features=AutomationControlled", "about:blank"]
    if PROXY:
        cmd.append(f"--proxy-server={PROXY}")
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
        call("Page.enable"); call("Runtime.enable"); call("Network.enable")
        call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        while time.time() - t0 < 45:
            time.sleep(2.5)
            if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0) > 10:
                break
        cks = [c for c in call("Network.getAllCookies").get("result", {}).get("cookies", []) if "ozon" in (c.get("domain") or "")]
        d = {"cookie": "; ".join(f"{c['name']}={c['value']}" for c in cks),
             "ua": ev("navigator.userAgent"), "n_cookies": len(cks), "at": time.time()}
        os.makedirs(CACHE, exist_ok=True)
        json.dump(d, open(os.path.join(CACHE, "detail.json"), "w"))
        return d
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()


# ---------- 解析 ----------
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


def W(ws, prefix):
    for k, v in (ws or {}).items():
        if k.startswith(prefix):
            try:
                return json.loads(v)
            except Exception:
                return None
    return None


def parse_pdp1(ws):
    o = {}
    h = W(ws, "webProductHeading")
    o["title"] = (h or {}).get("title") or (h or {}).get("text")
    sk = W(ws, "webDetailSKU")
    o["sku"] = (sk or {}).get("copyText")
    pr = W(ws, "webPrice")
    if pr:
        o["price"] = num(pr.get("price"))
        o["card_price"] = num(pr.get("cardPrice"))
        o["original_price"] = num(pr.get("originalPrice"))
        o["available"] = pr.get("isAvailable")
    rv = W(ws, "webReviewProductScore")
    if rv:
        o["rating"] = rv.get("totalScore")
        o["reviews"] = rv.get("reviewsCount")
    sps = W(ws, "webSingleProductScore")
    if sps and not o.get("rating"):
        o["rating"] = sps.get("text")
    bp = W(ws, "bigPromoPDP")
    if bp:
        o["promo_stock"] = (bp.get("stockNumber") or {}).get("text")
        o["promo_sold_pct"] = (bp.get("counter") or {}).get("percentage")
    sel = W(ws, "webCurrentSeller")
    if sel:
        cell = sel.get("sellerCell") or {}
        cb = cell.get("centerBlock") or {}
        m = re.search(r'"sellerId":\s*"?(\d{3,12})"?', json.dumps(sel))
        o["seller"] = {"id": m.group(1) if m else None, "name": (cb.get("title") or {}).get("text")}
    gal = W(ws, "webGallery")
    if gal:
        o["images"] = [x.get("src") for x in (gal.get("images") or [])]
        o["videos"] = [v.get("url") or v.get("link") for v in (gal.get("videos") or []) if v]
    ch = W(ws, "webShortCharacteristics")
    if ch:
        o["short_characteristics"] = [
            {"id": c.get("id"),
             "name": "".join(x.get("content", "") for x in ((c.get("title") or {}).get("textRs") or [])),
             "value": ((c.get("values") or [{}])[0]).get("text")}
            for c in (ch.get("characteristics") or [])]
    asp = W(ws, "webAspects")
    if asp:
        o["variants"] = [{"aspect": a.get("aspectName"),
                          "variants": [{"sku": v.get("sku"), "price": v.get("price"),
                                        "avail": v.get("availability"),
                                        "colors": (v.get("data") or {}).get("colors")}
                                       for v in (a.get("variants") or [])]}
                         for a in (asp.get("aspects") or [])]
    bs = W(ws, "webBestSeller")
    if bs:
        o["other_sellers"] = {"count": num(bs.get("count"))}
    ml = W(ws, "webMarketingLabels")
    if ml:
        o["labels"] = [l.get("badge", {}).get("text") for l in (ml.get("labels") or []) if l.get("badge")]
    bc = W(ws, "breadCrumbs")
    if bc:
        o["breadcrumbs"] = [(x.get("text") or "").strip() for x in (bc.get("breadcrumbs") or [])]
    return o


def parse_pdp2(ws):
    o = {}
    d = W(ws, "webDescription")
    if d:
        o["description_html"] = d.get("richAnnotation")
        o["description_text"] = re.sub(r"<[^>]+>", "", (d.get("richAnnotation") or "").replace("<br/>", "\n"))
    c = W(ws, "webCharacteristics")
    if c:
        o["characteristics_total"] = c.get("totalCount")
        o["characteristics"] = [{"key": x.get("key"), "name": x.get("name"),
                                 "values": [v.get("text") for v in (x.get("values") or []) if v.get("text")]}
                                for g in (c.get("characteristics") or []) for x in (g.get("short") or [])]
    h = W(ws, "webHashtags")
    if h:
        o["hashtags"] = [b.get("text") for b in (h.get("badges") or [])]
    return o


def parse_reviews(ws):
    w = W(ws, "webListReviews")
    if not w:
        return None
    sc = W(ws, "webReviewProductScore")
    pg = w.get("paging") or {}
    rows = []
    for r in w.get("reviews") or []:
        ct = r.get("content") or {}
        rows.append({
            "uuid": r.get("uuid"),
            "rating": num(ct.get("score")),
            "published_at": (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r["publishedAt"])) if r.get("publishedAt") else None),
            "author": (((r.get("author") or {}).get("firstName") or "") + " " + ((r.get("author") or {}).get("lastName") or "")).strip() or None,
            "text": ct.get("comment"),
            "positive": ct.get("positive"),
            "negative": ct.get("negative"),
            "photos": [p.get("url") for p in (ct.get("photos") or [])],
            "useful": (r.get("usefulness") or {}).get("useful"),
        })
    return {"rows": rows, "total": pg.get("total"), "per_page": pg.get("perPage"), "page": pg.get("page"),
            "overall": {"score": (sc or {}).get("totalScore"), "count": (sc or {}).get("reviewsCount")} if sc else None}


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", required=True, help="skus.txt 或逗号分隔的 SKU")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=0, help="0 = 自动（池大小 × 16，单 cookie 时 24）")
    ap.add_argument("--pool", type=int, default=0, help="用 N 个 headless 会话轮换")
    ap.add_argument("--browser", help="从本机浏览器直接读 cookie（零窗口零预热）")
    ap.add_argument("--pdp2", action="store_true", default=True)
    ap.add_argument("--no-pdp2", dest="pdp2", action="store_false")
    ap.add_argument("--reviews", type=int, default=0, help="评论页数（30 条/页），0=不抓")
    ap.add_argument("--sort", default="usefulness_desc",
                    choices=["usefulness_desc", "score_desc", "score_asc"],
                    help="评论排序（score_asc=只看差评、score_desc=只看好评）")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out + "/raw", exist_ok=True)
    logf = open(os.path.join(out, "run.log"), "a", encoding="utf-8")

    def log(o):
        with _lock:
            logf.write(json.dumps({"t": time.strftime("%H:%M:%S"), **o}, ensure_ascii=False) + "\n")
            logf.flush()

    creds = None
    if a.browser:
        try:
            from cookie_from_browser import creds_from_browser
            creds = creds_from_browser(a.browser)
            if creds:
                print(f"[+] 从 {a.browser} 读到 cookie（{creds['n_cookies']} 个，零窗口）")
        except ImportError:
            print("[!] 缺 browser_cookie3：pip3 install --user browser-cookie3")
    creds = creds or load_creds()
    if not creds:
        print("[*] 无缓存 cookie，静默预热一次（约 13 秒）...")
        creds = warm_creds()
        if not creds:
            print("[!] 预热失败")
            raise SystemExit(2)
    print(f"[+] 用 cookie（{creds.get('n') or creds.get('n_cookies') or 0} 个，{int(time.time()-creds['at'])}s 前）")

    H = {
        "accept": "application/json", "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
        "referer": "https://www.ozon.ru/",
        "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
        "user-agent": creds.get("ua") or VOID_UA,
        "cookie": creds["cookie"],
    }

    pc = None
    if a.pool >= 2 and PoolClient:
        pc = PoolClient(n=a.pool)
        if a.threads <= 0:
            a.threads = pc.recommended_threads()
        print(f"[+] cookie 池：{len(pc.pool)} 会话 → {a.threads} 线程")
    elif a.threads <= 0:
        a.threads = 24

    if os.path.exists(a.skus) and os.path.getsize(a.skus) > 0:
        skus = [l.strip() for l in open(a.skus) if l.strip() and not l.startswith("#")]
    else:
        skus = [s.strip() for s in a.skus.split(",") if s.strip()]
    print(f"[*] {len(skus)} 个 SKU")

    API = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="
    stat = {"ok": 0, "fail": 0, "r403": 0}

    def get(path):
        u = API + urllib.parse.quote(path, safe="")
        for _ in range(2):
            try:
                proxies = {"http": PROXY, "https": PROXY} if PROXY else None
                r = pc.get(u, timeout=45) if pc else cr.get(u, headers=H, impersonate="chrome", timeout=45, proxies=proxies)
                if r.status_code == 403:
                    with _lock:
                        stat["r403"] += 1
                    time.sleep(2)
                    continue
                if r.status_code != 200:
                    return None
                return json.loads(r.text)
            except Exception as ex:
                log({"ev": "err", "path": path[:50], "msg": str(ex)[:50]})
                time.sleep(1)
        return None

    def work(sku):
        row = {"sku": sku, "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        j1 = get(f"/product/{sku}/")
        if not j1:
            with _lock:
                stat["fail"] += 1
            log({"ev": "pdp1-fail", "sku": sku})
            return
        row.update(parse_pdp1(j1.get("widgetStates") or {}))
        row["sku"] = sku
        with _lock:
            stat["ok"] += 1

        if a.pdp2:
            j2 = get(f"/product/{sku}/?layout_container=pdpPage2column&layout_page_index=2")
            if j2:
                row.update(parse_pdp2(j2.get("widgetStates") or {}))

        if a.reviews > 0:
            # 评论：带 reviewsVariantMode=2 + 排序（score_asc/score_desc 星级筛选），?page=N 真翻页（实测零重叠）
            revs = []
            sort_q = f"?reviewsVariantMode=2&sort={a.sort}"
            for p in range(1, a.reviews + 1):
                path = f"/product/{sku}/reviews/{sort_q}" + ("" if p == 1 else f"&page={p}")
                jr = get(path)
                if not jr:
                    break
                pr = parse_reviews(jr.get("widgetStates") or {})
                if not pr:
                    break
                row["review_total"] = pr["total"]
                row["review_overall"] = pr["overall"]
                revs.extend(pr["rows"])
            row["reviews"] = revs

        with _lock:
            with open(os.path.join(out, "details.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if stat["ok"] % 20 == 0:
                json.dump(stat, open(os.path.join(out, "progress.json"), "w"))
        log({"ev": "sku", "sku": sku, "title": (row.get("title") or "")[:30], "ok": stat["ok"]})

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        list(ex.map(work, skus))
    wall = time.time() - t0

    log({"ev": "done", "wall": round(wall, 1), **stat})
    print(f"\n== done ==")
    print(f"SKU ok={stat['ok']} fail={stat['fail']} 403={stat['r403']}  wall {wall:.1f}s")
    if wall > 0:
        print(f"throughput {stat['ok']/wall:.2f} SKU/s")
    print(f"-> {out}/details.jsonl")
    if pc:
        print(f"[pool] {pc.stats()}")
    logf.close()


if __name__ == "__main__":
    main()
