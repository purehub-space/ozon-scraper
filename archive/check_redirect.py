import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9950; prof=tempfile.mkdtemp(prefix="ozon-redir-")
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
i=[0]; navs=[]
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
# 预热
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>10:
        print("warm:",round(time.time()-t0,1)); break

SEARCH="https://www.ozon.ru/search/?from_global=true&text="+urllib.parse.quote("сквиш")
print("\n[navigate]", SEARCH)
call("Page.navigate",{"url":SEARCH})
time.sleep(8)
print("current url:", ev("location.href"))
print("title:", str(ev("document.title"))[:60])
print("h1:", str(ev("(document.querySelector('h1')||{}).innerText||''"))[:80])
# 页面里实际打的结果 API 是什么？
print("\n[page-side fetch of /search/ p1]")
url="/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote("/search/?from_global=true&text=сквиш&page=1",safe="")
js=("(async()=>{const r=await fetch(%s,{headers:{accept:'application/json'}});const t=await r.text();"
    "let n=0,kind='';try{const j=JSON.parse(t);const ws=j.widgetStates||{};for(const k in ws){if(k.startsWith('tileGridDesktop'))n=(JSON.parse(ws[k]).items||[]).length} if(j.incidentId)kind='challenge'}catch(e){kind='parse'}"
    "return JSON.stringify({s:r.status,n,len:t.length,kind});})()") % json.dumps(url)
print(ev(js))
ws.close(); p.terminate()
