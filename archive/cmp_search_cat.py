import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9955; prof=tempfile.mkdtemp(prefix="ozon-cmp-")
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

JS=("(async()=>{const r=await fetch(%s,{headers:{accept:'application/json'}});const t=await r.text();"
    "const out={s:r.status,items:[]};"
    "try{const ws=JSON.parse(t).widgetStates||{};for(const k in ws){if(k.startswith('tileGridDesktop')){"
    "for(const it of (JSON.parse(ws[k]).items||[])){let nm='';for(const st of (it.mainState||[])){const ds=st.textDS||{};"
    "if(st.id==='name'||((ds.testInfo||{}).automatizationId==='tile-name'))nm=ds.text||''}out.items.push([it.sku,nm.trim()])}}}}catch(e){}"
    "return JSON.stringify(out);})()")
S="/search/?from_global=true&text="+urllib.parse.quote("сквиш")
C="/category/igrushki-antistress-7181/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text="+urllib.parse.quote("сквиш")
for label, base, pg in [("search p2",S,2),("cat p2",C,2),("search p5",S,5),("cat p5",C,5)]:
    url="/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(base+f"&page={pg}",safe="")
    v=ev(JS % json.dumps(url))
    d=json.loads(v)
    hits=sum(1 for _,n in d['items'] if 'сквиш' in n.lower())
    print(f"{label}: s={d['s']} n={len(d['items'])} 含词={hits} err={d.get('err')} keys={d.get('keys')}")
    print("   names:", [n[:36] for _,n in d['items'][:4]])
    time.sleep(1.2)
ws.close(); p.terminate()
