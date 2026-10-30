import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9965; prof=tempfile.mkdtemp(prefix="ozon-img-")
p=subprocess.Popen([CHROME,f"--remote-debugging-port={port}",f"--user-data-dir={prof}","--no-first-run",
 "--no-default-browser-check","--window-size=1440,900","--window-position=-2400,-2400",
 "--disable-blink-features=AutomationControlled","about:blank"],
 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
ws=None
for _ in range(80):
    time.sleep(0.4)
    try:
        d=json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list",timeout=2))
        pg=[t for t in d if t["type"]=="page" and t.get("webSocketDebuggerUrl")]
        if pg: ws=websocket.create_connection(pg[0]["webSocketDebuggerUrl"],timeout=120,suppress_origin=True); break
    except Exception: pass
i=[0]; net=[]
def send(m,params=None):
    i[0]+=1; ws.send(json.dumps({"id":i[0],"method":m,"params":params or {}}))
    return i[0]
def call(m,params=None,timeout=120):
    mid=send(m,params); t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("method")=="Network.requestWillBeSent":
            q=r["params"]["request"]; net.append({"url":q["url"],"method":q["method"],"type":r["params"].get("type")})
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
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>10:
        print("warm:",round(time.time()-t0,1)); break
net.clear()
# 找相机 / 图片搜索入口
info=ev("""(()=>{
 const out={inputs:[],candidates:[]};
 document.querySelectorAll('input[type=file]').forEach((el,i)=>out.inputs.push({i,accept:el.accept,name:el.name,cls:(el.className||'').slice(0,60)}));
 const walk=(el,d)=>{ if(d>14||!el) return;
   for(const ch of (el.children||[])){ walk(ch,d+1); }
   const t=(el.getAttribute&&el.getAttribute('aria-label'))||el.title||'';
   const id=(el.getAttribute&&el.getAttribute('data-widget'))||'';
   if(/камер|camera|фото|image|visual|поиск по картинк/i.test(t+id)) out.candidates.push({tag:el.tagName,label:t.slice(0,50),widget:id});
 };
 walk(document.body,0);
 out.candidates=out.candidates.slice(0,12);
 return JSON.stringify(out);
})()""")
print("DOM:", info)
print("\nrequests after load:", len(net))
for n in net[:12]: print("  ", n["method"], n["type"], urllib.parse.unquote(n["url"])[:110])
ws.close(); p.terminate()
