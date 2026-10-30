import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
from curl_cffi import requests as cr

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
API = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + "&page=3", safe="")

# 1) 起浏览器预热并导出 cookie
port = 9600
prof = tempfile.mkdtemp(prefix="ozon-http-")
p = subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
    "--no-first-run","--no-default-browser-check","--window-size=1440,900",
    "--disable-blink-features=AutomationControlled","about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ws = None
for _ in range(60):
    time.sleep(0.4)
    try:
        d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
        pg=[t for t in d if t["type"]=="page" and t.get("webSocketDebuggerUrl")]
        if pg: ws = websocket.create_connection(pg[0]["webSocketDebuggerUrl"], timeout=90, suppress_origin=True); break
    except Exception: pass
i=[0]
def call(m, params=None, timeout=90):
    i[0]+=1; mid=i[0]
    ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
    t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("id")==mid: return r
    raise TimeoutError(m)
def ev(e):
    r=call("Runtime.evaluate",{"expression":e,"awaitPromise":True,"returnByValue":True})
    return r.get("result",{}).get("result",{}).get("value")
call("Page.enable"); call("Runtime.enable"); call("Network.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    t=str(ev("document.title") or ""); c=ev("document.cookie.length") or 0
    if "Challenge" not in t and c>20:
        print("warm:", round(time.time()-t0,1), "s")
        break
ua = ev("navigator.userAgent")
ck = [c for c in call("Network.getAllCookies").get("result",{}).get("cookies",[]) if "ozon" in c.get("domain","")]
print("cookies:", len(ck), "| UA:", (ua or "")[:60])
ws.close(); p.terminate()

cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in ck)
H = {
    "accept": "application/json",
    "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
    "referer": "https://www.ozon.ru/",
    "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
    "user-agent": ua,
    "cookie": cookie_hdr,
}
for imp in ["chrome", "chrome136", "chrome131", "safari"]:
    try:
        r = cr.get(API, headers=H, impersonate=imp, timeout=30)
        print(f"impersonate={imp:10} -> {r.status_code} len={len(r.text)} {r.text[:60]!r}")
    except Exception as e:
        print(f"impersonate={imp:10} -> ERR {str(e)[:60]}")
