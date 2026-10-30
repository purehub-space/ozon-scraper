import json, subprocess, tempfile, time, urllib.request, urllib.parse, re
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9967; prof=tempfile.mkdtemp(prefix="ozon-img3-")
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
def call(m,params=None,timeout=120):
    i[0]+=1; mid=i[0]
    ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
    t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("method")=="Network.requestWillBeSent":
            q=r["params"]["request"]; net.append((q["method"],r["params"].get("type"),q["url"]))
        if r.get("id")==mid: return r
    raise TimeoutError(m)
def ev(e):
    r=call("Runtime.evaluate",{"expression":e,"awaitPromise":True,"returnByValue":True})
    res=r.get("result",{})
    if res.get("exceptionDetails"): return {"__err":str(res["exceptionDetails"])[:120]}
    return res.get("result",{}).get("value")
call("Page.enable"); call("Runtime.enable"); call("Network.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>10:
        print("warm:",round(time.time()-t0,1)); break

# 1) 搜索框区域 outerHTML 里找 camera/image
r=ev("""(()=>{
  const w=document.querySelector('[data-widget="searchBarDesktop"]');
  if(!w) return JSON.stringify({no_widget:true});
  const html=w.outerHTML;
  const hits=[];
  for(const kw of ['camera','Camera','image','Image','фото','поиск по картинк','photo','visual']){
    let i=html.indexOf(kw);
    if(i>=0) hits.push(kw+'@'+i);
  }
  return JSON.stringify({len:html.length, hits, snippet: html.slice(0,600)});
})()""")
print("searchBar:", str(r)[:700])

# 2) 全页找 aria-label / title 含 camera 的元素
r2=ev("""(()=>{
  const out=[];
  document.querySelectorAll('[aria-label],[title],[data-testid]').forEach(el=>{
    const s=(el.getAttribute('aria-label')||'')+' '+(el.getAttribute('title')||'')+' '+(el.getAttribute('data-testid')||'');
    if(/камер|фото|camera|image|visual|картинк/i.test(s) && out.length<15)
      out.push({tag:el.tagName, s:s.slice(0,60), widget:el.getAttribute('data-widget')||''});
  });
  return JSON.stringify(out);
})()""")
print("labels:", r2)

# 3) 页面 JS 里的图搜关键词（从已加载 script src 猜）
r3=ev("""(()=>{
  const s=new Set();
  performance.getEntriesByType('resource').forEach(e=>{ if(/\\.js(\\?|$)/.test(e.name)) s.add(e.name); });
  return JSON.stringify([...s].slice(0,25));
})()""")
print("scripts:", str(r3)[:500])
ws.close(); p.terminate()
