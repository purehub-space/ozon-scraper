#!/usr/bin/env python3
"""
Cookie 池预热：并行起 N 个无痕 Chrome，各自过 antibot challenge，导出 cookie。

为什么要池：
  实测单个 cookie 的并发甜点约 24 线程（66 SKU/s），40 线程直接崩（4 SKU/s）。
  但 N 个 cookie 各自独立限速 → 吞吐接近线性叠加：
      4 cookie × 24 并发 = 243 SKU/s（单 cookie 24 并发的 3.7 倍）
      4 cookie × 16 并发 = 208 SKU/s
      4 cookie ×  8 并发 =  84 SKU/s（每个会话没吃满，反而浪费）

用法：
  python3 prepare_pool.py --n 4              # 预热 4 个，写 ~/.cache/ozon-search/pool-*.json
  python3 prepare_pool.py --n 4 --force      # 忽略已有，强制重来
  python3 prepare_pool.py --list             # 看现有池状态
"""
import argparse, glob, json, os, shutil, subprocess, tempfile, threading, time, urllib.request

CACHE = os.path.expanduser("~/.cache/ozon-search")
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]
BASE_PORT = 9700


def chrome():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def warm_one(idx, timeout=50, quiet=True):
    """起一个 Chrome（窗口移出屏幕）→ 过 challenge → 返回 cookie"""
    try:
        import websocket
    except ImportError:
        return {"i": idx, "err": "需要 websocket-client"}
    exe = chrome()
    if not exe:
        return {"i": idx, "err": "找不到 Chrome"}
    port = BASE_PORT + idx
    prof = tempfile.mkdtemp(prefix=f"ozon-pool{idx}-")
    p = subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1200,800",
        "--window-position=-2400,-2400", "--disable-blink-features=AutomationControlled", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        for _ in range(90):
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
            return {"i": idx, "err": "CDP 连不上"}
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
        cks = [c for c in call("Network.getAllCookies").get("result", {}).get("cookies", [])
               if "ozon" in (c.get("domain") or "")]
        if not cks:
            return {"i": idx, "err": "没拿到 cookie（challenge 没过）"}
        return {"i": idx, "cookie": "; ".join(f"{c['name']}={c['value']}" for c in cks),
                "ua": ev("navigator.userAgent"), "n": len(cks), "warm": round(time.time() - t0, 1)}
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()


def prepare(n, force=False):
    os.makedirs(CACHE, exist_ok=True)
    if force:
        for f in glob.glob(os.path.join(CACHE, "pool-*.json")):
            os.remove(f)
    print(f"[*] 并行预热 {n} 个无痕实例（窗口都在屏幕外，看不见）")
    t0 = time.time()
    out = [None] * n
    def w(i):
        out[i] = warm_one(i)
    ths = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    ok = 0
    for r in out:
        if r and r.get("cookie"):
            r["at"] = time.time()
            path = os.path.join(CACHE, f"pool-{r['i']}.json")
            json.dump(r, open(path, "w"))
            print(f"  [{r['i']}] OK  {r['n']} cookies  warm {r['warm']}s  -> {path}")
            ok += 1
        else:
            print(f"  [{r and r.get('i')}] FAIL {r.get('err') if r else '?'}")
    print(f"[+] {ok}/{n} 成功，总耗时 {time.time()-t0:.1f}s")
    if ok == 0:
        raise SystemExit(2)
    return ok


def list_pool():
    files = sorted(glob.glob(os.path.join(CACHE, "pool-*.json")))
    if not files:
        print("池是空的")
        return []
    pool = []
    for f in files:
        d = json.load(open(f))
        age = int(time.time() - d.get("at", 0))
        print(f"  {os.path.basename(f):16} age {age//3600}h{age%3600//60}m  cookies {d.get('n')}")
        if age < 12 * 3600:
            pool.append(d)
    print(f"可用 {len(pool)} 个")
    return pool


def load_pool(max_age=12 * 3600, auto=0):
    """给采集脚本用：读可用池；空了且 auto>0 就现场预热"""
    files = sorted(glob.glob(os.path.join(CACHE, "pool-*.json")), key=os.path.getmtime, reverse=True)
    pool = []
    for f in files:
        try:
            d = json.load(open(f))
            if d.get("cookie") and time.time() - d.get("at", 0) < max_age:
                pool.append(d)
        except Exception:
            pass
    if not pool and auto > 0:
        prepare(auto)
        return load_pool(max_age, 0)
    return pool


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4, help="预热几个（默认 4）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        list_pool()
    else:
        prepare(a.n, a.force)
