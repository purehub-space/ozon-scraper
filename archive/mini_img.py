import json, glob, os, re, sys, time, urllib.parse
from curl_cffi import requests as cr, CurlMime

CACHE=os.path.expanduser("~/.cache/ozon-search")
d=json.load(open(sorted(glob.glob(CACHE+"/*.json"), key=os.path.getmtime)[-1]))
H={'accept':'application/json','accept-language':'zh-CN,zh;q=0.9','referer':'https://www.ozon.ru/',
   'sec-ch-ua':'"Chromium";v="156", "Google Chrome";v="156"','sec-ch-ua-mobile':'?0','sec-ch-ua-platform':'"macOS"',
   'sec-fetch-site':'same-origin','sec-fetch-mode':'cors','sec-fetch-dest':'empty',
   'user-agent':d['ua'],'cookie':d['cookie']}
IMG=open("/tmp/ozon-test-img.jpg","rb").read()

print("upload...", flush=True)
mp=CurlMime(); mp.addpart(name="file", data=IMG, filename="blob", content_type="image/jpeg")
UPH=dict(H, referer="https://www.ozon.ru/search-by-image/", origin="https://www.ozon.ru")
s=cr.Session(impersonate="chrome")
r=s.post("https://www.ozon.ru/api/composer-api.bx/_action/searchByImage", headers=UPH, multipart=mp, timeout=60)
mp.close()
print("upload:", r.status_code, flush=True)
rid=r.json()["resultId"]

rows={}
for pg in range(1, 21):
    path=f"/search-by-image?image_id={rid}"+(f"&page={pg}" if pg>1 else "")
    u="https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(path,safe="")
    t=time.time()
    try:
        rr=s.get(u, headers=H, timeout=25)
        n=0
        if rr.status_code==200:
            ws=json.loads(rr.text).get("widgetStates") or {}
            for k,v in ws.items():
                if k.startswith("tileGridDesktop"):
                    for it in (json.loads(v).get("items") or []):
                        rows[it.get("sku")]=pg; n+=1
        print(f"p{pg}: {rr.status_code} items={n} total={len(rows)} {int((time.time()-t)*1000)}ms", flush=True)
        if n==0: break
    except Exception as e:
        print(f"p{pg}: ERR {str(e)[:60]}", flush=True)
    time.sleep(0.4)
print("TOTAL SKU:", len(rows), flush=True)
