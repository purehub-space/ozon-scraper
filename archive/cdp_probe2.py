import json, subprocess, tempfile, time, urllib.request, urllib.parse, sys
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9334
HEADLESS = "--headless" in sys.argv
PROFILE = tempfile.mkdtemp(prefix=f"ozon-cdp2-{PORT}-")
cmd = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
       "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
       "--disable-blink-features=AutomationControlled"]
if HEADLESS: cmd.append("--headless=new")
cmd.append("about:blank")
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

ws_url = None
for _ in range(40):
    time.sleep(0.4)
    try:
        data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
        pages = [t for t in data if t["type"] == "page" and t.get("webSocketDebuggerUrl")]
        if pages: ws_url = pages[0]["webSocketDebuggerUrl"]; break
    except Exception: pass
print("cdp:", ws_url, "| headless:", HEADLESS)
ws = websocket.create_connection(ws_url, timeout=90, suppress_origin=True)
_i=[0]
def call(m, params=None, timeout=90):
    _i[0]+=1; mid=_i[0]
    ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
    t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("id")==mid: return r
    raise TimeoutError(m)
def ev(expr, await_p=True):
    r = call("Runtime.evaluate", {"expression": expr, "awaitPromise": await_p, "returnByValue": True})
    return r.get("result",{}).get("result",{}).get("value")

call("Page.enable"); call("Runtime.enable")
# 先正常访问首页，让 challenge 自己跑
call("Page.navigate", {"url":"https://www.ozon.ru/"})
for i in range(6):
    time.sleep(4)
    u = ev("location.href"); t = ev("document.title")
    print(f"  +{(i+1)*4}s", str(u)[:70], "|", str(t)[:40])
    if u and "challenge" not in u and "block" not in u and t and len(t) > 5:
        break
print("cookies:", ev("document.cookie.length"))
B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
JS = """(async () => { const t0=performance.now();
 const r = await fetch(%s, {headers:{accept:'application/json'}});
 const t = await r.text();
 return JSON.stringify({s:r.status, ms:Math.round(performance.now()-t0), len:t.length, kind: r.status===200?'json':t.slice(0,40)}); })()"""
for i in range(3):
    print(i, ev(JS % json.dumps("/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={i+2}", safe=""))))
    time.sleep(1)
ws.close(); p.terminate()
