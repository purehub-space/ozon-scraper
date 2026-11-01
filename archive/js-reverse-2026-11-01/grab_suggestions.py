import json, os, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket

PORT = 9994
CHROME = "/usr/local/bin/chromium"
prof = tempfile.mkdtemp(prefix="ozon-sa2-")
args = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
        "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
        "--disable-blink-features=AutomationControlled", "--window-position=-2400,-2400", "about:blank"]
p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ws = None
try:
    for _ in range(100):
        time.sleep(0.5)
        try:
            pages = [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
                     if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages: break
        except Exception: pass
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
    cnt = [0]
    def call(m, params=None, tmo=60):
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
    while time.time() - t0 < 70:
        time.sleep(3)
        title = str(ev("document.title") or "")
        clen = ev("document.cookie.length") or 0
        if "Challenge" not in title and clen > 10: break
    print("主页就绪, cookie:", clen)

    def api(path):
        js = f"""async () => {{
            try {{
                const r = await fetch("{path}", {{headers:{{"accept":"application/json"}}}});
                const t = await r.text();
                return JSON.stringify({{status:r.status, len:t.length, body:t}});
            }} catch(e) {{ return JSON.stringify({{err:String(e)}}); }}
        }}"""
        res = ev(f"({js})()")
        return json.loads(res)

    for kw in ["сквиш", "сумка", "casio"]:
        p_ = "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(f"/searchSuggestions/search/?text={kw}&from_global=true", safe="")
        r = api(p_)
        print(f"== autocomplete[{kw}]: status={r.get('status')} len={r.get('len')}")
        if r.get("status") == 200:
            json.dump(r, open(f"/tmp/ozon-re/autocomplete_{kw}.json","w"), ensure_ascii=False)
            # 解析建议
            try:
                body = json.loads(r["body"])
                for k, v in body.get("widgetStates", {}).items():
                    if "webSuggestions" in k:
                        j = json.loads(v)
                        for it in j.get("items", []):
                            cell = it.get("cellItem", {})
                            c = cell.get("content", {})
                            title = c.get("title", {})
                            print("    建议:", title.get("text", "")[:60], "| 副题:", (c.get("subtitle",{}) or {}).get("text","")[:40] if isinstance(c.get("subtitle"),dict) else "")
            except Exception as e:
                print("    解析失败:", e)
        time.sleep(3)
finally:
    try: ws.close()
    except Exception: pass
    try: p.terminate()
    except Exception: pass
