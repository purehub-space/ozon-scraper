import json, time, urllib.parse
from curl_cffi import requests as cr
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
H={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
 "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
 "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA}
def get(path):
    u="https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(path,safe="")
    t=time.time()
    r=cr.get(u,headers=H,impersonate="chrome",timeout=40)
    items=[]
    if r.status_code==200:
        ws=json.loads(r.text).get("widgetStates") or {}
        for k,v in ws.items():
            if k.startswith("tileGridDesktop"): items=json.loads(v).get("items") or []
    return r.status_code, items, int((time.time()-t)*1000)

KW="сквиш"
S=f"/search/?from_global=true&text={urllib.parse.quote(KW)}"
C=f"/category/igrushki-antistress-7181/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text={urllib.parse.quote(KW)}"

print("== 搜索页重试 page1-5 ==")
for n in [1,2,3,4,5]:
    s,items,ms = get(f"{S}&page={n}")
    print(f"  p{n}: {s} items={len(items)} first={items[0].get('sku') if items else None} {ms}ms")
    time.sleep(1.5)

print("\n== 同样关键词：搜索页 vs 类目页 p1 ==")
s1,i1,_=get(S); s2,i2,_=get(C)
print(f"  search : {s1} {len(i1)} first3={[x.get('sku') for x in i1[:3]]}")
print(f"  category: {s2} {len(i2)} first3={[x.get('sku') for x in i2[:3]]}")
a={x.get('sku') for x in i1}; b={x.get('sku') for x in i2}
print(f"  交集 {len(a&b)} / 搜索 {len(a)} / 类目 {len(b)}")

print("\n== 搜索页上限细查 ==")
for n in [1240, 1250, 1251, 1260]:
    s,items,ms = get(f"{S}&page={n}")
    print(f"  p{n}: {s} items={len(items)}")
    time.sleep(1.2)
