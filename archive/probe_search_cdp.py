import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
KW="сквиш"
S=f"/search/?from_global=true&text={urllib.parse.quote(KW)}"
port=9800; prof=tempfile.mkdtemp(prefix="ozon-srch-")
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
        print("warm:",round(time.time()-t0,1)); break
js=("(async()=>{const r=await fetch(%s,{headers:{accept:'application/json'}});const t=await r.text();"
    "let n=0;try{const ws=JSON.parse(t).widgetStates||{};for(const k in ws){if(k.startsWith('tileGridDesktop'))n=(JSON.parse(ws[k]).items||[]).length}}catch(e){}"
    "return JSON.stringify({s:r.status,n,len:t.length});})()")
for n in [1,2,3,10,100,200,250]:
    url="/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(S+f"&page={n}",safe="")
    print(f"  browser search p{n}:", ev(js % json.dumps(url)))
    time.sleep(1)
ws.close(); p.terminate()
