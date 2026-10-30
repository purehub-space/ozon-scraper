import json, subprocess, tempfile, time, urllib.request, urllib.parse, threading
import websocket, requests as plain
from curl_cffi import requests as cr

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
def api(n): return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={n}", safe="")

port = 9601; prof = tempfile.mkdtemp(prefix="ozon-h2-")
p = subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
    "--no-first-run","--no-default-browser-check","--window-size=1440,900",
    "--disable-blink-features=AutomationControlled","about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
call("Page.enable");call("Runtime.enable");call("Network.enable")
call("Page.navigate",{"url":"https://www.ozon.ru/"})
t0=time.time()
while time.time()-t0<50:
    time.sleep(2.5)
    if "Challenge" not in str(ev("document.title") or "") and (ev("document.cookie.length") or 0)>20:
        print("warm:",round(time.time()-t0,1)); break
ua=ev("navigator.userAgent")
ck=[c for c in call("Network.getAllCookies").get("result",{}).get("cookies",[]) if "ozon" in c.get("domain","")]
ws.close(); p.terminate()
print("cookies:",len(ck))

base_h = {
    "accept":"application/json","accept-language":"zh-CN,zh;q=0.9,ru;q=0.8",
    "referer":"https://www.ozon.ru/",
    "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
    "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
    "user-agent":ua,
}
ckh="; ".join(f"{c['name']}={c['value']}" for c in ck)
json.dump({"cookie":ckh,"ua":ua}, open("/tmp/ozon-http-creds.json","w"))

# A: 无 cookie
r=cr.get(api(3), headers=base_h, impersonate="chrome", timeout=30)
print("A no-cookie:", r.status_code, len(r.text))
# B: 纯 requests（带 cookie，不同 TLS）
h2=dict(base_h); h2["cookie"]=ckh
try:
    r2=plain.get(api(3), headers=h2, timeout=30)
    print("B plain-requests:", r2.status_code, len(r2.text), r2.text[:50].replace("\n"," "))
except Exception as e: print("B err", str(e)[:60])
# C: curl_cffi 并发 6 × 4 页
H=dict(base_h); H["cookie"]=ckh
results=[]; lock=threading.Lock()
def w(off):
    for k in range(4):
        n=off+k+10
        t=time.time()
        try:
            r=cr.get(api(n), headers=H, impersonate="chrome", timeout=40)
            with lock: results.append({"n":n,"s":r.status_code,"ms":int((time.time()-t)*1000),"len":len(r.text)})
        except Exception as e:
            with lock: results.append({"n":n,"s":"ERR","ms":int((time.time()-t)*1000)})
ths=[threading.Thread(target=w,args=(i*4,)) for i in range(6)]
t0=time.time(); [t.start() for t in ths]; [t.join() for t in ths]
wall=time.time()-t0
ok=[x for x in results if x["s"]==200]
ms=sorted(x["ms"] for x in ok)
print(f"C 6-thread×4: wall {wall:.1f}s ok {len(ok)}/{len(results)} median {ms[len(ms)//2] if ms else 0}ms")
print(f"   throughput {len(ok)/wall:.2f} pages/s = {len(ok)/wall*8:.1f} SKU/s")
