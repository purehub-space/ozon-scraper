import json, time, urllib.parse, threading, requests as plain

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
def api(n): return "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={n}", safe="")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
H = {
    "accept":"application/json","accept-language":"zh-CN,zh;q=0.9,ru;q=0.8",
    "referer":"https://www.ozon.ru/",
    "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
    "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
    "user-agent":UA,
}
# A: 纯 requests，无 cookie，无浏览器
for n in [3, 4, 5]:
    t=time.time()
    try:
        r=plain.get(api(n), headers=H, timeout=30)
        print(f"plain no-cookie p{n}: {r.status_code} len={len(r.text)} {int((time.time()-t)*1000)}ms")
    except Exception as e:
        print(f"plain p{n} ERR {str(e)[:60]}")

# B: 并发 12 线程 × 4 页
results=[]; lock=threading.Lock()
def w(off):
    for k in range(4):
        n=off+k+20
        t=time.time()
        try:
            r=plain.get(api(n), headers=H, timeout=40)
            with lock: results.append({"n":n,"s":r.status_code,"ms":int((time.time()-t)*1000),"len":len(r.text)})
        except Exception as e:
            with lock: results.append({"n":n,"s":"ERR","ms":int((time.time()-t)*1000)})
ths=[threading.Thread(target=w,args=(i*4,)) for i in range(12)]
t0=time.time(); [t.start() for t in ths]; [t.join() for t in ths]
wall=time.time()-t0
ok=[x for x in results if x["s"]==200]; ms=sorted(x["ms"] for x in ok)
print(f"\n12 threads x4 = {len(results)} req, ok {len(ok)}, wall {wall:.1f}s, median {ms[len(ms)//2] if ms else 0}ms")
print(f"throughput {len(ok)/wall:.2f} pages/s = {len(ok)/wall*8:.1f} SKU/s")
bad=[x for x in results if x["s"]!=200][:3]
print("bad:", bad)
