import json, time, urllib.parse, sys
from curl_cffi import requests as cr
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
H={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
 "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
 "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA}

def probe(path, n):
    u="https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(path,safe="")
    t=time.time()
    try:
        r=cr.get(u,headers=H,impersonate="chrome",timeout=40)
        items=[]; total=None
        if r.status_code==200:
            ws=json.loads(r.text).get("widgetStates") or {}
            for k,v in ws.items():
                if k.startswith("tileGridDesktop"):
                    t2=json.loads(v); items=t2.get("items") or []; total=t2.get("total")
        first = items[0].get("sku") if items else None
        print(f"  page {n:>5}: {r.status_code} items={len(items)} total={total} first={first} {int((time.time()-t)*1000)}ms")
        return items
    except Exception as e:
        print(f"  page {n:>5}: ERR {str(e)[:50]}")
        return []

KW = "сквиш"
SEARCH = f"/search/?from_global=true&text={urllib.parse.quote(KW)}"
print("== 纯搜索页:", SEARCH)
for n in [1, 2, 10, 100, 500, 1000, 1250, 1300]:
    probe(SEARCH + f"&page={n}", n)
    time.sleep(0.6)
