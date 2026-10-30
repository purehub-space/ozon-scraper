import json, time, urllib.parse
from curl_cffi import requests as cr
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
H={"accept":"application/json","accept-language":"zh-CN,zh;q=0.9","referer":"https://www.ozon.ru/",
 "sec-ch-ua":'"Chromium";v="156", "Google Chrome";v="156"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"macOS"',
 "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin","user-agent":UA}
def get(path):
    u="https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="+urllib.parse.quote(path,safe="")
    r=cr.get(u,headers=H,impersonate="chrome",timeout=40)
    items=[]
    if r.status_code==200:
        ws=json.loads(r.text).get("widgetStates") or {}
        for k,v in ws.items():
            if k.startswith("tileGridDesktop"): items=json.loads(v).get("items") or []
    return r.status_code, items
KW="сквиш"
S=f"/search/?from_global=true&text={urllib.parse.quote(KW)}"
print("搜索页边界扫描")
for n in [150,200,250,300,350,400,450]:
    s,items=get(f"{S}&page={n}")
    print(f"  p{n}: {s} items={len(items)}")
    time.sleep(1.2)
print("\n带 sorting 参数试前几页")
for q in ["&sorting=score","&sorting=new","&sorting=price","&layout_page_index=2"]:
    s,items=get(S+q+"&page=1")
    print(f"  {q:26} -> {s} items={len(items)}")
    time.sleep(1.5)
print("\n其它关键词 p1")
for kw in ["сумка","игрушка","сквиш антистресс"]:
    s,items=get(f"/search/?from_global=true&text={urllib.parse.quote(kw)}")
    print(f"  {kw:16} -> {s} items={len(items)}")
    time.sleep(1.5)
