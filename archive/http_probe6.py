import time, urllib.parse, threading, json, sys
from curl_cffi import requests as cr

B="/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
def api(n): return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(B+f"&page={n}",safe="")
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
H={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
 "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
 "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA}
THREADS=int(sys.argv[1]) if len(sys.argv)>1 else 24
PER=int(sys.argv[2]) if len(sys.argv)>2 else 8
START=int(sys.argv[3]) if len(sys.argv)>3 else 100

results=[]; lock=threading.Lock()
def w(off):
    for k in range(PER):
        n=START+off+k*THREADS
        t=time.time()
        try:
            r=cr.get(api(n),headers=H,impersonate="chrome",timeout=45)
            items=0
            if r.status_code==200:
                try:
                    ws=json.loads(r.text).get("widgetStates") or {}
                    for kk,vv in ws.items():
                        if kk.startswith("tileGridDesktop"): items=len(json.loads(vv).get("items") or [])
                except Exception: pass
            with lock: results.append({"s":r.status_code,"items":items,"ms":int((time.time()-t)*1000)})
        except Exception as e:
            with lock: results.append({"s":"ERR","ms":int((time.time()-t)*1000)})
ths=[threading.Thread(target=w,args=(i,)) for i in range(THREADS)]
t0=time.time(); [t.start() for t in ths]; [t.join() for t in ths]
wall=time.time()-t0
ok=[x for x in results if x["s"]==200]; ms=sorted(x["ms"] for x in ok)
bad=[x for x in results if x["s"]!=200]
print(f"{THREADS} threads x{PER} = {len(results)} req")
print(f"ok {len(ok)}, bad {len(bad)}, wall {wall:.1f}s, median {ms[len(ms)//2] if ms else 0}ms, max {ms[-1] if ms else 0}ms")
print(f"throughput {len(ok)/wall:.2f} pages/s = {len(ok)/wall*8:.1f} SKU/s, rows {sum(x['items'] for x in ok)}")
if bad: print("bad sample:", bad[:3])
