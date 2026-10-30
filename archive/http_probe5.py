import time, urllib.parse, threading, requests as plain, json, re

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
def api(n): return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={n}", safe="")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
FULL = {
    "accept":"application/json","accept-language":"zh-CN,zh;q=0.9,ru;q=0.8",
    "referer":"https://www.ozon.ru/",
    "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
    "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
    "user-agent":UA,
}
print("== ua_only 重复 6 次 ==")
for i in range(6):
    try:
        r=plain.get(api(50+i), headers={"user-agent":UA}, timeout=30)
        print(f"  {i}: {r.status_code} {len(r.text)}")
    except Exception as e:
        print(f"  {i}: ERR {str(e)[:40]}")

print("== 24 线程跑 200 页稳定性 ==")
results=[]; lock=threading.Lock(); stop=threading.Event()
def w(start):
    n=start
    while n<=200 and not stop.is_set():
        t=time.time()
        try:
            r=plain.get(api(n), headers=FULL, timeout=45)
            body=r.text
            items=0
            if r.status_code==200:
                try:
                    ws=json.loads(body).get("widgetStates") or {}
                    for k,v in ws.items():
                        if k.startswith("tileGridDesktop"): items=len(json.loads(v).get("items") or [])
                except Exception: pass
            with lock: results.append({"n":n,"s":r.status_code,"items":items,"ms":int((time.time()-t)*1000)})
        except Exception as e:
            with lock: results.append({"n":n,"s":"ERR","ms":int((time.time()-t)*1000)})
        n+=24
ths=[threading.Thread(target=w,args=(i+1,)) for i in range(24)]
t0=time.time(); [t.start() for t in ths]; [t.join() for t in ths]
wall=time.time()-t0
ok=[x for x in results if x["s"]==200]; ms=sorted(x["ms"] for x in ok)
items=sum(x.get("items",0) for x in ok)
print(f"pages {len(results)}, ok {len(ok)}, wall {wall:.1f}s, median {ms[len(ms)//2] if ms else 0}ms, max {ms[-1] if ms else 0}ms")
print(f"SKU rows fetched: {items}, throughput {len(ok)/wall:.2f} pages/s = {len(ok)/wall*8:.1f} SKU/s")
bad=[x for x in results if x["s"]!=200]
print("bad:", bad[:5], "total bad:", len(bad))
