#!/usr/bin/env python3
"""
Ozon 以图搜图采集 — 纯 HTTP（curl_cffi，multipart 上传）

实测（2026-10-30）：
  1) POST /api/composer-api.bx/_action/searchByImage
     multipart，字段名 file，image/jpeg（支持 JPEG/PNG/WEBP/PDF，≤4MB）
     → {"redirectUri":"/search-by-image?image_id=...", "resultId":"..."}
  2) GET /api/entrypoint-api.bx/page/json/v2?url=/search-by-image?image_id=<id>&page=N
     → 每页 12 条（比关键词搜索的 8 条多）
     → page 100 仍有数据，page 500 为空
  需要 cookie（走 ozon_search.py 的缓存，或本脚本自动预热）

用法：
  python3 ozon_image.py --image /tmp/panda.jpg --out out_img
  python3 ozon_image.py --image /tmp/panda.jpg --out out_img --pages 1-20 --threads 12
"""
import argparse, glob, json, os, re, subprocess, tempfile, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as cr, CurlMime

try:
    from pool_client import PoolClient, CONCURRENCY_PER_COOKIE
except ImportError:
    PoolClient = None

CACHE = os.path.expanduser("~/.cache/ozon-search")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VOID_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
_lock = threading.Lock()
_loglock = threading.Lock()
_tls = threading.local()


def sess():
    """每线程一个 Session：curl_cffi 多线程共享 handle 会 TLS 卡死"""
    if not hasattr(_tls, "s"):
        _tls.s = cr.Session(impersonate="chrome")
    return _tls.s


def load_creds():
    files = sorted(glob.glob(os.path.join(CACHE, "*.json")), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            d = json.load(open(f))
            if d.get("cookie") and time.time() - d.get("at", 0) < 12 * 3600:
                return d
        except Exception:
            pass
    return None


def warm_creds():
    import websocket
    port = 9985
    prof = tempfile.mkdtemp(prefix="ozon-imgwarm-")
    p = subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1200,800",
        "--window-position=-2400,-2400", "--disable-blink-features=AutomationControlled", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        for _ in range(80):
            time.sleep(0.4)
            try:
                d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
                pg = [t for t in d if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
                if pg:
                    ws = websocket.create_connection(pg[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
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
        json.dump(d, open(os.path.join(CACHE, "image.json"), "w"))
        return d
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()


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
    return o


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


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image", help="本地图片路径（multipart 文件上传）")
    g.add_argument("--url", help="图片 URL，直接透传给 Ozon（不下载）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="1-100", help="默认 100 页（图搜常见上限，page 500 为空）")
    ap.add_argument("--threads", type=int, default=0, help="0 = 自动（池大小 × 16）")
    ap.add_argument("--pool", type=int, default=0, help="用 N 个 cookie 轮换（0=单一 cookie，N>=2 提速）")
    ap.add_argument("--max-mb", type=float, default=4.0)
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "run.log"), "a", encoding="utf-8")

    def log(o):
        with _loglock:
            logf.write(json.dumps({"t": time.strftime("%H:%M:%S"), **o}, ensure_ascii=False) + "\n")
            logf.flush()

    img = b""
    if a.image:
        img = open(a.image, "rb").read()
        if len(img) > a.max_mb * 1024 * 1024:
            print(f"[!] 图片 {len(img)/1024/1024:.1f}MB 超过 {a.max_mb}MB，Ozon 会拒")
            raise SystemExit(2)

    creds = load_creds() or warm_creds()
    if not creds:
        print("[!] 拿不到 cookie（预热失败）")
        raise SystemExit(2)
    print(f"[+] cookie {creds.get('n_cookies') or creds.get('n') or '?'} 个")

    H = {
        "accept": "application/json", "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
        "referer": "https://www.ozon.ru/",
        "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
        "user-agent": creds.get("ua") or VOID_UA, "cookie": creds["cookie"],
    }

    pc = None
    if a.pool >= 2 and PoolClient:
        pc = PoolClient(n=a.pool)
        H = pc.headers_for(0)
        if a.threads <= 0:
            a.threads = pc.recommended_threads()
        print(f"[+] cookie 池模式：{len(pc.pool)} 会话，{a.threads} 线程")
    elif a.threads <= 0:
        a.threads = 6

    # 1) 上传
    mp = CurlMime()
    if a.url:
        # URL 透传：multipart 里放纯文本字段 url（不是文件）
        mp.addpart(name="url", data=a.url.encode())
    else:
        mp.addpart(name="file", data=img, filename="blob", content_type="image/jpeg")
    UP_H = dict(H, referer="https://www.ozon.ru/search-by-image/", origin="https://www.ozon.ru")
    UP_H["content-type"] = None
    UP_H.pop("content-type", None)
    # 上传必须用独立 Session：模块级 cr.post(multipart=...) 会污染全局 handle，
    # 导致之后所有请求 hang（实测卡死在 30s 超时前的连接阶段）
    S = cr.Session(impersonate="chrome")
    try:
        if pc:
            r = pc.get("https://www.ozon.ru/search-by-image/", timeout=30)  # 热身
            r = pc.post("https://www.ozon.ru/api/composer-api.bx/_action/searchByImage",
                        multipart=mp, extra_headers={"referer": "https://www.ozon.ru/search-by-image/",
                                                     "origin": "https://www.ozon.ru"}, timeout=90)
        else:
            r = S.post("https://www.ozon.ru/api/composer-api.bx/_action/searchByImage",
                       headers=UP_H, multipart=mp, timeout=90)
    finally:
        mp.close()
    _tls.s = S   # 主线程复用上传用的同一个 Session（不要 close）
    log({"ev": "upload", "status": r.status_code, "mode": "url" if a.url else "file",
         "src": a.url or a.image, "bytes": len(img)})
    if r.status_code != 200:
        print(f"[!] 上传失败 {r.status_code}: {r.text[:150]}")
        raise SystemExit(2)
    j = r.json()
    rid = j.get("resultId")
    print(f"[+] 上传成功 image_id={rid}")

    s, _, e = a.pages.partition("-")
    p_from, p_to = int(s), (int(e) if e else int(s))
    until_end = (p_to == 0)

    def build(n):
        path = f"/search-by-image?image_id={rid}" + (f"&page={n}" if n > 1 else "")
        return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")

    skus, stat = {}, {"ok": 0, "fail": 0}
    stop = threading.Event()

    def fetch(n):
        if stop.is_set():
            return
        for _ in range(3):
            try:
                r = pc.get(build(n), timeout=25) if pc else sess().get(build(n), headers=H, timeout=25)
                if r.status_code != 200:
                    log({"ev": "bad", "p": n, "s": r.status_code, "body": (r.text or "")[:80]})
                    time.sleep(2)
                    continue
                items = parse_items(r.text)
                if not items:
                    stop.set()
                    return
                with _lock:
                    new = 0
                    for it in items:
                        row = parse_tile(it, n)
                        if row["sku"] and row["sku"] not in skus:
                            skus[row["sku"]] = row
                            new += 1
                    stat["ok"] += 1
                    log({"ev": "page", "p": n, "n": len(items), "new": new, "total": len(skus)})
                return
            except Exception as ex:
                log({"ev": "err", "p": n, "msg": str(ex)[:50]})
                time.sleep(1.5)
        with _lock:
            stat["fail"] += 1

    t0 = time.time()
    n = p_from
    if a.threads <= 1:
        while n <= (p_to if not until_end else 10**9) and not stop.is_set():
            fetch(n); n += 1
        wall0 = time.time() - t0
        print(f"[serial] {stat['ok']} pages in {wall0:.1f}s")
    with ThreadPoolExecutor(max_workers=max(a.threads, 1)) as ex:
        while not stop.is_set() and a.threads > 1:
            batch = []
            for _ in range(a.threads * 4):
                if not until_end and n > p_to:
                    break
                batch.append(n); n += 1
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
    json.dump({"image_id": rid, "n": len(rows), "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(os.path.join(out, "meta.json"), "w"))

    # 顺手把最高分（第一条）标出来
    if rows:
        top = rows[0]
        print(f"\n[+] 最相似: {top['sku']} {top.get('title','')[:50]} {top.get('price')} ₽")

    print(f"\n== done ==")
    print(f"pages ok={stat['ok']} fail={stat['fail']}  wall {wall:.1f}s")
    print(f"unique SKU {len(rows)}  (12 条/页)")
    if wall > 0 and stat["ok"]:
        print(f"throughput {stat['ok']/wall:.2f} pages/s = {stat['ok']/wall*12:.1f} SKU/s")
    print(f"-> {out}/skus.txt  {out}/products.jsonl")
    if pc:
        print(f"[pool] {pc.stats()}")
    logf.close()


if __name__ == "__main__":
    main()
