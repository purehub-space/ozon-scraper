import json, subprocess, tempfile, time, urllib.request, urllib.parse
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9969; prof=tempfile.mkdtemp(prefix="ozon-img5-")
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
i=[0]
def call(m,params=None,timeout=120):
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
call("Page.enable"); call("Runtime.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>10:
        print("warm:",round(time.time()-t0,1)); break

IMG="https://ir-20.ozonstatic.cn/s3/multimedia-1-e/7401951734.jpg"
q=urllib.parse.quote(IMG, safe="")
tries=[
 ("search?image_url", f"https://www.ozon.ru/search/?image_url={q}"),
 ("search?image",     f"https://www.ozon.ru/search/?image={q}"),
 ("search?visual",    f"https://www.ozon.ru/search/?visual=true&image_url={q}"),
 ("visual-search",    f"https://www.ozon.ru/visual-search/?image_url={q}"),
 ("image-search",     f"https://www.ozon.ru/image-search/?url={q}"),
 ("search?text=img",  f"https://www.ozon.ru/search/?text=&image_url={q}&from_global=true"),
]
for label,u in tries:
    try:
        call("Page.navigate",{"url":u})
        time.sleep(4)
        cur=str(ev("location.href") or ""); t=str(ev("document.title") or "")
        h1=str(ev("(document.querySelector('h1')||{}).innerText||''"))
        body=str(ev("(document.body.innerText||'').slice(0,100)")).replace("\n"," ")
        print(f"{label:18} -> {cur[:75]}")
        print(f"                   title={t[:40]!r} h1={h1[:30]!r} body={body[:50]!r}")
    except Exception as e:
        print(f"{label:18} -> ERR {str(e)[:60]}")
ws.close(); p.terminate()
