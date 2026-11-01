import json, urllib.parse, time
from curl_cffi import requests as cr

def sess(i):
    d = json.load(open(f'/home/user/.cache/ozon-search/pool-{i}.json'))
    H = {"accept":"application/json","accept-language":"zh-CN,zh;q=0.9,ru;q=0.8","referer":"https://www.ozon.ru/",
         "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
         "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
         "user-agent":d.get("ua"),"cookie":d["cookie"]}
    S = cr.Session(impersonate="chrome")
    S.get("https://www.ozon.ru/", headers=H, timeout=25)
    return S, H

SKU = "4056369411"
C = [
    ("问答列表", f"/product/{SKU}/question/questions/"),
    ("组合购买", f"/product/{SKU}/bundle/"),
    ("类似商品", f"/product/{SKU}/similar/"),
    ("对比页",   f"/product/{SKU}/compare/"),
    ("PDP2",    f"/product/{SKU}/?layout_container=pdpPage2column&layout_page_index=2"),
]
S0,H0 = sess(0); S1,H1 = sess(1)
for idx,(name,path) in enumerate(C):
    S,H = (S0,H0) if idx%2==0 else (S1,H1)
    full = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")
    try:
        r = S.get(full, headers=H, timeout=22)
        if r.status_code == 200:
            dd = json.loads(r.text)
            ws = dd.get("widgetStates", {})
            json.dump(dd, open(f"/tmp/ozon-re/probe_{name}.json","w"), ensure_ascii=False)
            biz = [k.split("-")[0] for k in ws if "web" in k or "cell" in k or "question" in k.lower() or "review" in k.lower() or "seller" in k.lower() or "bundle" in k.lower() or "similar" in k.lower() or "compare" in k.lower() or "tile" in k.lower() or "list" in k.lower()]
            print(f"{name:<8} 200 widgets={len(ws):<3} 业务: {sorted(set(biz))}")
        else:
            print(f"{name:<8} {r.status_code}")
    except Exception as e:
        print(f"{name:<8} ERR {str(e)[:40]}")
    time.sleep(3)
print("done")
