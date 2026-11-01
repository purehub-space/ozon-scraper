"""浏览器内调用 Ozon API：headful Chrome 过 challenge → 页面内同源 fetch → 返回 JSON"""
import json, os, subprocess, tempfile, time, urllib.request
import websocket

PORT = 9989
CHROME = "/usr/local/bin/chromium"

def main():
    prof = tempfile.mkdtemp(prefix="ozon-api-")
    args = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
            "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
            "--disable-blink-features=AutomationControlled", "--window-position=-2400,-2400",
            "about:blank"]
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        pages = None
        for _ in range(100):
            time.sleep(0.5)
            if p.poll() is not None:
                print("[!] chromium 退出"); return
            try:
                pages = [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages: break
            except Exception: pass
        if not pages:
            print("[!] CDP 未就绪"); return
        ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
        cnt = [0]
        def call(m, params=None, tmo=90):
            cnt[0] += 1; mid = cnt[0]
            ws.send(json.dumps({"id": mid, "method": m, "params": params or {}}))
            t0 = time.time()
            while time.time() - t0 < tmo:
                r = json.loads(ws.recv())
                if r.get("id") == mid: return r
            raise TimeoutError(m)
        def ev(e):
            r = call("Runtime.evaluate", {"expression": e, "awaitPromise": True, "returnByValue": True})
            return r.get("result", {}).get("result", {}).get("value")

        call("Page.enable"); call("Runtime.enable")
        call("Page.navigate", {"url": "https://www.ozon.ru/"})
        t0 = time.time()
        passed = False
        while time.time() - t0 < 70:
            time.sleep(3)
            try:
                title = str(ev("document.title") or "")
                clen = ev("document.cookie.length") or 0
                print(f"  [t={int(time.time()-t0)}s] title={title[:35]!r} cookie={clen}")
                if "Challenge" not in title and clen > 10:
                    passed = True; break
            except Exception: pass
        if not passed:
            print("[!] challenge 未通过"); return

        # 在页面上下文里调用 API（同源 fetch）
        def api(method, path, body=None):
            js = f"""async () => {{
                try {{
                    const opt = {{method:"{method}",headers:{{"accept":"application/json"}}}};
                    {('opt.body=JSON.stringify('+json.dumps(body, ensure_ascii=False)+');opt.headers["content-type"]="application/json";') if body else ''}
                    const r = await fetch("{path}", opt);
                    const t = await r.text();
                    return JSON.stringify({{status:r.status, len:t.length, body:t.substring(0,3000)}});
                }} catch(e) {{ return JSON.stringify({{err:String(e)}}); }}
            }}"""
            res = ev(f"({js})()")
            try:
                return json.loads(res)
            except Exception:
                return {"raw": res}

        # 测试队列
        tests = [
            ("autocomplete_сумка", "GET", "/searchSuggestions/сумка", None),
            ("autocomplete_сквиш", "GET", "/searchSuggestions/сквиш", None),
            ("tapTags_сквиш", "GET", "/api/composer-api.bx/_action/getSearchTapTags?query=сквиш&widgetVersion=2", None),
            ("tapTags_сумка", "GET", "/api/composer-api.bx/_action/getSearchTapTags?query=сумка&widgetVersion=2", None),
        ]
        for name, m, path, body in tests:
            r = api(m, path, body)
            print(f"\n== {name}: status={r.get('status')} len={r.get('len')}")
            b = r.get("body", "")
            print("   ", b[:400])
            time.sleep(2)
        # 保存完整结果
        r = api("GET", "/searchSuggestions/сквиш")
        print(f"\n[完整] autocomplete сквиш: {r.get('status')}")
        json.dump(r, open("/tmp/ozon-re/autocomplete_full.json","w"), ensure_ascii=False)
    finally:
        try: ws.close()
        except Exception: pass
        p.terminate()

if __name__ == "__main__":
    main()
