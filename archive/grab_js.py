#!/usr/bin/env python3
"""Ozon 主应用 JS bundle 抓取器 v2：headless Chrome 过 challenge → performance API 收集 JS → 下载"""
import json, os, subprocess, tempfile, time, urllib.request
import websocket

PORT = 9967
OUT = "/tmp/ozon-re/js"
os.makedirs(OUT, exist_ok=True)
CHROME = "/usr/local/bin/chromium"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"

def main():
    prof = tempfile.mkdtemp(prefix="ozon-js-")
    cmd = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
           "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled",
           "--window-size=1280,900", "--headless=new", f"--user-agent={UA}", "about:blank"]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        pages = None
        for _ in range(60):
            time.sleep(0.4)
            try:
                pages = [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    break
            except Exception:
                pass
        if not pages:
            print("[!] CDP 未就绪"); return
        ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
        cnt = [0]
        def call(m, params=None, tmo=90):
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

        call("Page.enable"); call("Runtime.enable")
        call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        passed = False
        while time.time() - t0 < 75:
            time.sleep(3)
            try:
                title = str(ev("document.title") or "")
                clen = ev("document.cookie.length") or 0
                print(f"  [t={int(time.time()-t0)}s] title={title[:40]!r} cookie_len={clen}")
                if "Challenge" not in title and clen > 10:
                    passed = True
                    break
            except Exception:
                pass
        if not passed:
            time.sleep(12)  # 再等热加载
        # performance API 收集 JS
        res = ev("JSON.stringify(performance.getEntriesByType('resource').map(e=>e.name).filter(n=>n.includes('.js')))") or "[]"
        urls = sorted({u for u in json.loads(res) if "challenge" not in u and "vendor" not in u.split("/")[-1][:20] or ".js" in u})
        print(f"\n[+] challenge 通过: {passed}，收集 {len(urls)} 个 JS")
        with open("/tmp/ozon-re/js_urls.txt", "w") as f:
            f.write("\n".join(urls))
        for u in urls:
            print("  ", u)
        # 下载（并行）
        from concurrent.futures import ThreadPoolExecutor
        import urllib.request
        def dl(u):
            try:
                name = u.split("/")[-1].split("?")[0]
                req = urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.ozon.ru/"})
                data = urllib.request.urlopen(req, timeout=30).read()
                path = os.path.join(OUT, name)
                open(path, "wb").write(data)
                return f"{name} {len(data)}"
            except Exception as e:
                return f"{u.split('/')[-1][:40]} ERR {e}"
        with ThreadPoolExecutor(max_workers=8) as ex:
            for r2 in ex.map(dl, urls):
                print("  dl:", r2)
    finally:
        try:
            ws.close()
        except Exception:
            pass
        p.terminate()

if __name__ == "__main__":
    main()
