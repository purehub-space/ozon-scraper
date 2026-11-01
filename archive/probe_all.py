#!/usr/bin/env python3
"""Ozon 全量端点探测：Session 预热主页 → 批量验证候选端点 → 输出可续接清单"""
import json, time, urllib.parse, re
from curl_cffi import requests as cr

SKU = "4056369411"
SELLER = "4340585"

d = json.load(open("/home/user/.cache/ozon-search/pool-0.json"))
H = {"accept": "application/json", "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
     "referer": "https://www.ozon.ru/",
     "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"', "sec-ch-ua-mobile": "?0",
     "sec-ch-ua-platform": '"macOS"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
     "sec-fetch-site": "same-origin", "user-agent": d.get("ua"), "cookie": d["cookie"]}

# (名称, 页面路径)
C = [
    ("PDP1",                  f"/product/{SKU}/"),
    ("PDP2(第二屏)",           f"/product/{SKU}/?layout_container=pdpPage2column&layout_page_index=2"),
    ("评论",                   f"/product/{SKU}/reviews/?page=1"),
    ("问答",                   f"/product/{SKU}/question/"),
    ("其他卖家modal",          f"/modal/otherOffersFromSellers?product_id={SKU}&sort=price"),
    ("店铺页",                 f"/seller/magazin-{SELLER}-{SELLER}/"),
    ("店铺评价",                f"/seller/magazin-{SELLER}-{SELLER}/reviews/"),
    ("店铺主体modal",          f"/modal/shop-in-shop-info?seller_id={SELLER}"),
    ("店铺评分popover",        f"/modal/shop-in-shop-rating-popover?seller_id={SELLER}"),
    ("品牌页(筛选格式)",        "/category/sumki-na-plecho-zhenskie-17002/bellastar-102054974/"),
    ("类目排序price",          "/category/sumki-na-plecho-zhenskie-17002/?sorting=price&page=2"),
    ("类目排序rating",         "/category/sumki-na-plecho-zhenskie-17002/?sorting=rating&page=2"),
    ("类目排序new",            "/category/sumki-na-plecho-zhenskie-17002/?sorting=new&page=2"),
    ("搜索排序price",          "/search/?from_global=true&text=сумка&sorting=price"),
    ("highlight精选",          "/highlight/20023/"),
    ("货币语言modal",          "/modal/currency-language"),
    ("收藏(匿名)",              "/my/favorites/"),
    ("购物车(匿名)",            "/cart/"),
    ("订单(匿名)",              "/my/orderlist/"),
    ("优惠券中心",              "/coupons/"),
    ("全球购",                 "/global/"),
    ("促销",                   "/action/"),
    ("每日特惠",                "/action/deal-of-the-day/"),
    ("Ozon直播",               "/live/"),
    ("排行榜",                 "/top/"),
]

COMMON = {"header", "footer", "catalogMenu", "searchBar", "horizontalMenu", "orderTracking",
          "orderInfo", "favoriteCounter", "addressBookBar", "selectedCurrency", "homeButton",
          "profileMenu", "column-", "row-", "container-", "separator-", "wallpaper",
          "tapTags", "pixel", "bannerCarousel", "customHtml", "textBlock", "paginator"}

S = cr.Session(impersonate="chrome")
r0 = S.get("https://www.ozon.ru/", headers=H, timeout=25)
print(f"主页预热: {r0.status_code}\n")

results = []
for name, path in C:
    full = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(path, safe="")
    try:
        r = S.get(full, headers=H, timeout=22)
        if r.status_code == 200:
            try:
                dd = json.loads(r.text)
                ws = dd.get("widgetStates", {})
                biz = [k.split("-")[0] for k in ws if k.split("-")[0] not in COMMON]
                results.append((name, 200, len(ws), biz))
                print(f"  {name:<16} 200  widgets={len(ws):<3} 业务: {', '.join(sorted(set(biz)))[:110]}")
            except Exception as e:
                results.append((name, 200, -1, []))
                print(f"  {name:<16} 200  (非标准JSON)")
        else:
            results.append((name, r.status_code, 0, []))
            print(f"  {name:<16} {r.status_code}")
    except Exception as e:
        results.append((name, "ERR", 0, []))
        print(f"  {name:<16} ERR {str(e)[:40]}")
    time.sleep(1.8)

json.dump(results, open("/tmp/ozon-re/probe_results.json", "w"))
print("\n完成，结果已存 /tmp/ozon-re/probe_results.json")
