import json, subprocess, tempfile, time, urllib.request, urllib.parse, re
import websocket
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
port=9972; prof=tempfile.mkdtemp(prefix="ozon-js-")
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
        if pg: ws=websocket.create_connection(pg[0]["webSocketDebuggerUrl"],timeout=180,suppress_origin=True); break
    except Exception: pass
i=[0]; scripts={}
def pump(timeout=1.0):
    ws.settimeout(timeout)
    try:
        while True:
            r=json.loads(ws.recv())
            if r.get("method")=="Network.responseReceived":
                rr=r["params"]["response"]
                if ".js" in rr.get("url","") and "ozonstatic" in rr["url"]:
                    scripts[rr["url"]]=max(scripts.get(rr["url"],0), rr.get("encodedDataLength") or 0)
    except Exception: pass
    ws.settimeout(180)
def call(m,params=None,timeout=180):
    i[0]+=1; mid=i[0]
    ws.send(json.dumps({"id":mid,"method":m,"params":params or {}}))
    t0=time.time()
    while time.time()-t0<timeout:
        r=json.loads(ws.recv())
        if r.get("method")=="Network.responseReceived":
            rr=r["params"]["response"]
            if ".js" in rr.get("url","") and "ozonstatic" in rr["url"]:
                scripts[rr["url"]]=max(scripts.get(rr["url"],0), rr.get("encodedDataLength") or 0)
        if r.get("id")==mid: return r
    raise TimeoutError(m)
def ev(e):
    r=call("Runtime.evaluate",{"expression":e,"awaitPromise":True,"returnByValue":True})
    return r.get("result",{}).get("result",{}).get("value")
call("Page.enable"); call("Runtime.enable"); call("Network.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/search/?from_global=true&text="+urllib.parse.quote("сквиш")})
for _ in range(8):
    time.sleep(2); 
    try: ev("1")
    except Exception: pass
    pump(1.2)
print("scripts captured:", len(scripts))
top=sorted(scripts.items(), key=lambda x:-x[1])[:8]
for u,s in top: print(f"  {s:>9} {u}")
json.dump(dict(top), open("/tmp/ozon_scripts.json","w"))

KWS=["imageSearch","image_search","visualSearch","visual-search","searchByImage","search-by-image","SearchByPhoto","поиск по фото","photoSearch","imageUrl"]
print("\n=== grep ===")
for u,_ in top[:6]:
    try:
        d=urllib.request.urlopen(u,timeout=30).read().decode("utf-8","ignore")
        found={k:d.count(k) for k in KWS if k in d}
        if found: print(u.split("/")[-1], found)
        for k in found:
            idx=d.find(k)
            print("   ctx:", d[max(0,idx-90):idx+120].replace("\n"," ")[:200])
    except Exception as e:
        print(u.split("/")[-1],"ERR",str(e)[:40])
ws.close(); p.terminate()
