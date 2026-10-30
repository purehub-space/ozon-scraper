import json, os, subprocess, tempfile, time, urllib.request, urllib.parse, sys
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9333
HEADLESS = "--headless" in sys.argv
PROFILE = tempfile.mkdtemp(prefix=f"ozon-cdp-{PORT}-")

cmd = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
       "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
       "--disable-blink-features=AutomationControlled"]
if HEADLESS: cmd.append("--headless=new")
cmd.append("about:blank")
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 等 CDP 就绪
ws_url = None
for _ in range(40):
    time.sleep(0.4)
    try:
        data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
        pages = [t for t in data if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
        if pages:
            ws_url = pages[0]["webSocketDebuggerUrl"]; break
    except Exception:
        pass
print("cdp:", ws_url)
if not ws_url:
    p.kill(); sys.exit(1)

ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
_i = [0]
def call(method, params=None, timeout=60):
    _i[0] += 1; mid = _i[0]
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            return r
    raise TimeoutError(method)

call("Page.enable"); call("Runtime.enable")
call("Page.navigate", {"url": "https://www.ozon.ru/robots.txt"})
time.sleep(3)
print("url:", call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})["result"]["result"].get("value"))

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
JS = """
(async () => {
  const t0 = performance.now();
  const r = await fetch(%s, {headers:{accept:'application/json'}});
  const t = await r.text();
  return JSON.stringify({s:r.status, ms:Math.round(performance.now()-t0), len:t.length, kind: r.status===200?'json':t.slice(0,50)});
})()
"""
for i in range(3):
    expr = JS % json.dumps("/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={i+2}", safe=""))
    r = call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
    val = r.get("result", {}).get("result", {}).get("value")
    print(i, val, "| err:", r.get("result", {}).get("exceptionDetails", {}).get("text"))
    time.sleep(1)
ws.close(); p.terminate()
print("profile:", PROFILE)
