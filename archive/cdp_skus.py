#!/usr/bin/env python3
"""
Ozon 类目/搜索页 SKU 并发采集器（纯 Python + CDP，无 Selenium、无 ego 依赖）

每个 worker = 一个独立 Chrome 实例（独立 user-data-dir = 无痕）+ 独立 remote-debugging-port。
预热：先访问一次 www.ozon.ru 让 antibot challenge 自己跑完（实测 6~10 秒）。
之后 Runtime.evaluate 在页面里跑 window.fetch，直接拿 JSON。

用法：
  python3 cdp_skus.py --url "<类目/搜索页 URL>" --pages 1-0 --instances 6 --out out_skus
  python3 cdp_skus.py --url "<URL>" --pages 1-200 --instances 4 --out out_c

产物：out/skus.txt, out/products.jsonl, out/progress.json, out/run.log
"""
import argparse, json, os, re, subprocess, tempfile, threading, time, urllib.parse, urllib.request
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE_PORT = 9400
_lock = threading.Lock()
STOP = threading.Event()


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


def parse_items(raw):
    try:
        ws = json.loads(raw).get("widgetStates") or {}
    except Exception:
        return []
    for k, v in ws.items():
        if k.startswith("tileGridDesktop"):
            try:
                return json.loads(v).get("items") or []
            except Exception:
                return []
    return []


def parse_tile(it):
    o = {"sku": it.get("sku") or it.get("id")}
    act = it.get("action") or {}
    if act.get("link"):
        o["link"] = act["link"].split("?")[0]
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
    ti = it.get("trackingInfo") or {}
    o["is_advert"] = bool(((ti.get("click") or {}).get("custom") or {}).get("advertLite"))
    return o


class Worker:
    def __init__(self, idx, log):
        self.idx = idx
        self.port = BASE_PORT + idx
        self.profile = tempfile.mkdtemp(prefix=f"ozon-w{idx}-")
        self.log = log
        self.ws = None
        self._i = 0
        self.ok = 0
        self.pages_ok = 0

    def start(self):
        cmd = [CHROME, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
               "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
               "--disable-blink-features=AutomationControlled", "about:blank"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            time.sleep(0.4)
            try:
                d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                pages = [t for t in d if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
                    self.call("Page.enable")
                    self.call("Runtime.enable")
                    return True
            except Exception:
                pass
        return False

    def call(self, m, params=None, timeout=90):
        self._i += 1
        mid = self._i
        self.ws.send(json.dumps({"id": mid, "method": m, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = json.loads(self.ws.recv())
            if r.get("id") == mid:
                return r
        raise TimeoutError(m)

    def ev(self, expr, await_p=True):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": await_p, "returnByValue": True})
        res = r.get("result", {})
        if res.get("exceptionDetails"):
            return None
        return res.get("result", {}).get("value")

    def warm(self):
        """访问首页，等 antibot challenge 自己过"""
        self.call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        while time.time() - t0 < 50:
            time.sleep(2.5)
            try:
                title = str(self.ev("document.title") or "")
                ck = self.ev("document.cookie.length") or 0
                if "Challenge" not in title and ck > 20:
                    return round(time.time() - t0, 1)
            except Exception:
                pass
        return -1

    def fetch(self, url, retry=2):
        js = ("(async()=>{const t0=performance.now();"
              "const r=await fetch(%s,{headers:{accept:'application/json'}});"
              "const t=await r.text();"
              "return JSON.stringify({s:r.status,ms:Math.round(performance.now()-t0),body:t});})()")
        for a in range(retry + 1):
            try:
                v = self.ev(js % json.dumps(url))
                if v:
                    return json.loads(v)
            except Exception as e:
                self.log({"ev": "err", "w": self.idx, "a": a, "msg": str(e)[:60]})
            time.sleep(2)
        return None

    def stop(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.p.terminate()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--pages", default="1-0", help="start-end；end=0 抓到空页")
    ap.add_argument("--instances", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("--delay", type=int, default=400, help="每页后额外延迟 ms")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "run.log"), "a", encoding="utf-8")
    loglock = threading.Lock()

    def log(o):
        with loglock:
            logf.write(json.dumps({"t": time.strftime("%H:%M:%S"), **o}, ensure_ascii=False) + "\n")
            logf.flush()

    u = a.url if a.url.startswith("http") else "https://www.ozon.ru" + a.url
    p = urllib.parse.urlparse(u)
    BASE = p.path + ("?" + p.query if p.query else "")

    s, _, e = a.pages.partition("-")
    p_from = int(s)
    p_to = int(e) if e else p_from
    UNTIL_END = (p_to == 0)

    workers = [Worker(i, log) for i in range(a.instances)]
    log({"ev": "start", "base": BASE, "from": p_from, "to": p_to, "workers": a.instances})
    for w in workers:
        ok = w.start()
        log({"ev": "ready", "w": w.idx, "port": w.port, "ok": ok})

    warm = {}
    def warmup(w):
        warm[w.idx] = w.warm()
    ths = [threading.Thread(target=warmup, args=(w,)) for w in workers]
    [t.start() for t in ths]
    [t.join() for t in ths]
    log({"ev": "warmup", "secs": warm})

    skus = {}
    skus_lock = threading.Lock()
    counter = {"pages": 0, "new": 0}

    def run(w, offset):
        page_no = p_from + offset
        while not STOP.is_set():
            if not UNTIL_END and page_no > p_to:
                break
            q = urllib.parse.urlparse(BASE)
            params = urllib.parse.parse_qsl(q.query)
            params = [kv for kv in params if kv[0] != "page"] + [("page", str(page_no))]
            path = q.path + "?" + urllib.parse.urlencode(params)
            url = "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")

            r = w.fetch(url)
            if not r:
                log({"ev": "fail", "w": w.idx, "p": page_no})
                page_no += a.instances
                time.sleep(3)
                continue
            items = parse_items(r.get("body") or "")
            if not items:
                log({"ev": "empty", "w": w.idx, "p": page_no, "status": r.get("s")})
                STOP.set()
                break
            new = 0
            with skus_lock:
                for it in items:
                    row = parse_tile(it)
                    if row["sku"] and row["sku"] not in skus:
                        skus[row["sku"]] = {**row, "page": page_no}
                        new += 1
                counter["pages"] += 1
                counter["new"] += new
                if counter["pages"] % 5 == 0:
                    json.dump({"pages": counter["pages"], "skus": len(skus), "at": time.strftime("%H:%M:%S")},
                              open(os.path.join(out, "progress.json"), "w"))
            log({"ev": "page", "w": w.idx, "p": page_no, "n": len(items), "new": new, "ms": r.get("ms"), "total": len(skus)})
            page_no += a.instances
            time.sleep(a.delay / 1000)

    ths = [threading.Thread(target=run, args=(w, i)) for i, w in enumerate(workers)]
    t0 = time.time()
    [t.start() for t in ths]
    [t.join() for t in ths]
    wall = time.time() - t0

    rows = sorted(skus.values(), key=lambda r: r["page"])
    with open(os.path.join(out, "skus.txt"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(str(r["sku"]) + "\n")
    with open(os.path.join(out, "products.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    log({"ev": "done", "wall": round(wall, 1), "pages": counter["pages"], "skus": len(rows)})
    print(f"\n== done ==")
    print(f"instances: {a.instances}  pages: {counter['pages']}  wall: {wall:.1f}s")
    print(f"unique SKU: {len(rows)}")
    if wall > 0 and counter["pages"]:
        print(f"throughput: {counter['pages']/wall:.2f} pages/s = {counter['pages']/wall*8:.1f} SKU/s")
    print(f"-> {out}/skus.txt")

    for w in workers:
        w.stop()
    logf.close()


if __name__ == "__main__":
    main()
