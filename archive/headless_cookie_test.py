import json, subprocess, tempfile, time, urllib.request, urllib.parse, sys
import websocket
from curl_cffi import requests as cr

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HEADLESS = "--headless" in sys.argv
port=9960; prof=tempfile.mkdtemp(prefix="ozon-hl-")
cmd=[CHROME,f"--remote-debugging-port={port}",f"--user-data-dir={prof}","--no-first-run",
 "--no-default-browser-check","--window-size=1440,900","--disable-blink-features=AutomationControlled",
 "--window-position=-2400,-2400"]
if HEADLESS: cmd.append("--headless=new")
cmd.append("about:blank")
p=subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ws=None
for _ in range(60):
    time.sleep(0.4)
    try:
        d=json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list",timeout=2))
        pg=[t for t in d if t["type"]=="page" and t.get("webSocketDebuggerUrl")]
        if pg: ws=websocket.create_connection(pg[0]["webSocketDebuggerUrl"],timeout=90,suppress_origin=True); break
    except Exception: pass
i=[0]
def call(m,params=None,timeout=90):
    i[0]+=1; mid=i[0]; ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
    t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("id")==mid: return r
    raise TimeoutError(m)
def ev(e):
    r=call("Runtime.evaluate",{"expression":e,"awaitPromise":True,"returnByValue":True})
    return r.get("result",{}).get("result",{}).get("value")
call("Page.enable"); call("Runtime.enable"); call("Network.enable")
print("headless:", HEADLESS)

SEARCH="https://www.ozon.ru/search/?from_global=true&text="+urllib.parse.quote("сквиш")
call("Page.navigate",{"url":SEARCH})
final=None
t0=time.time()
while time.time()-t0<40:
    time.sleep(2.5)
    u=str(ev("location.href") or ""); t=str(ev("document.title") or "")
    print(f"  +{round(time.time()-t0)}s", u[:80], "|", t[:36])
    if "Challenge" not in u+t and "block" not in u:
        if "category/" in u or t:
            final=u; break
print("final:", final)
ck=[c for c in call("Network.getAllCookies").get("result",{}).get("cookies",[]) if "ozon" in c.get("domain","")]
print("cookies:", len(ck))
ckh="; ".join(f"{c['name']}={c['value']}" for c in ck)
UA=ev("navigator.userAgent")
ws.close(); p.terminate()

# 用 cookie 打 page 1
C=final
if C and C.startswith("https://www.ozon.ru"):
    base=C[len("https://www.ozon.ru"):]
    H={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
       "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
       "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA,"cookie":ckh}
    for n in [1,2]:
        u="https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(base+f"&page={n}",safe="")
        r=cr.get(u,headers=H,impersonate="chrome",timeout=40)
        items=0
        if r.status_code==200:
            try:
                wsx=json.loads(r.text).get("widgetStates") or {}
                for k,v in wsx.items():
                    if k.startswith("tileGridDesktop"): items=len(json.loads(v).get("items") or [])
            except Exception: pass
        print(f"  WITH-COOKIE p{n}: {r.status_code} items={items}")
        time.sleep(1.5)
