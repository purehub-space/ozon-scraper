import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket, requests as plain
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
B="/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
def api(n): return "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={n}", safe="")
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
FULL={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
 "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
 "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
 "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA}
# 1) 纯 HTTP 冷却后
for i in range(2):
    r=plain.get("https://www.ozon.ru"+api(60+i), headers=FULL, timeout=30)
    print(f"http after cooldown {i}: {r.status_code} {len(r.text)}")
    time.sleep(2)
# 2) 浏览器
port=9700; prof=tempfile.mkdtemp(prefix="ozon-alive-")
p=subprocess.Popen([CHROME,f"--remote-debugging-port={port}",f"--user-data-dir={prof}","--no-first-run",
 "--no-default-browser-check","--window-size=1440,900","--disable-blink-features=AutomationControlled","about:blank"],
 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
call("Page.enable");call("Runtime.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>10:
        print("browser warm:",round(time.time()-t0,1)); break
js=("(async()=>{const r=await fetch(%s,{headers:{accept:'application/json'}});const t=await r.text();"
    "return JSON.stringify({s:r.status,len:t.length});})()") % json.dumps(api(70))
print("browser fetch:", ev(js))
ws.close(); p.terminate()
