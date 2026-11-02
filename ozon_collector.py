#!/usr/bin/env python3
"""
Ozon 鲁棒高并发综合采集器
支持功能：
  1. 跨平台自动寻找 Chrome / Edge（支持 Windows, macOS, Linux）
  2. 自动检测并挂载本地 Clash/v2ray 代理（7897, 7890 等）
  3. 稳健 CDP 静默预热（过 antibot challenge + 自动绕过/处理 18+ 成人类目拦截）
  4. 纯 HTTP（curl_cffi Chrome 124 TLS 指纹）并发抓取
  5. 一站式聚合：搜索列表 SKU + 详情页卖家信息（店铺名、sellerId、历史单量、好评率）
"""
import argparse
import glob
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from curl_cffi import requests as cr
except ImportError:
    print("[!] 需要安装 curl_cffi: pip install curl_cffi")
    sys.exit(1)

from ozon_env import get_chrome_executable, detect_proxy, parse_num, parse_count_num

CACHE_DIR = os.path.expanduser("~/.cache/ozon-search")
COOKIE_TTL = 3600 * 6  # 6小时


def load_valid_cookie(cache_key="default"):
    os.makedirs(CACHE_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("cookie") and time.time() - d.get("at", 0) < COOKIE_TTL:
                return d
        except Exception:
            pass
    return None


def save_cookie_cache(d, cache_key="ozon_session"):
    os.makedirs(CACHE_DIR, exist_ok=True)
    fpath = os.path.join(CACHE_DIR, f"{cache_key}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return fpath


def cdp_warmup(target_url="https://www.ozon.ru/", proxy=None, timeout=60, is_adult=False):
    """跨平台安全静默预热：启动 Chrome/Edge 通过 CDP 过 antibot 并获取 Cookie"""
    try:
        import websocket
    except ImportError:
        print("[!] 需要安装 websocket-client: pip install websocket-client")
        return None

    chrome_bin = get_chrome_executable()
    if not chrome_bin:
        raise RuntimeError("未在当前系统找到 Chrome 或 Edge 可执行文件！")

    if not proxy:
        proxy = detect_proxy()

    port = 9888
    prof = tempfile.mkdtemp(prefix="ozon-cdp-")
    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={prof}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,800",
        "--window-position=-2400,-2400",  # 移出主屏幕避免打扰
        "--disable-blink-features=AutomationControlled",
        "about:blank",
    ]
    if proxy:
        args.append(f"--proxy-server={proxy}")

    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        ws_url = None
        for _ in range(80):
            time.sleep(0.3)
            try:
                raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2).read()
                tabs = json.loads(raw.decode("utf-8"))
                for tab in tabs:
                    if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                        ws_url = tab["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                pass

        if not ws_url:
            raise RuntimeError("CDP 端口响应超时，未能获取 Debugger URL")

        ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        call_id = [0]

        def call(method, params=None, tmo=30):
            call_id[0] += 1
            cid = call_id[0]
            ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
            t0 = time.time()
            while time.time() - t0 < tmo:
                res = json.loads(ws.recv())
                if res.get("id") == cid:
                    return res
            raise TimeoutError(f"CDP call {method} timed out")

        def evaluate(js):
            res = call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
            return res.get("result", {}).get("result", {}).get("value")

        call("Page.enable")
        call("Runtime.enable")
        call("Network.enable")

        print(f"[*] 导航至 Ozon: {target_url} (代理: {proxy})")
        call("Page.navigate", {"url": target_url})

        # 循环等待 challenge 通过
        t0 = time.time()
        passed = False
        while time.time() - t0 < timeout:
            time.sleep(2)
            title = str(evaluate("document.title") or "")
            if "Challenge" not in title and (evaluate("document.cookie.length") or 0) > 10:
                passed = True
                break

        # 检查是否命中 18+ 成人弹窗拦截并自动通过
        if is_adult or "18" in str(evaluate("document.body.innerText") or ""):
            has_adult_modal = evaluate("!!document.querySelector('[data-widget=\"userAdultModal\"]')")
            if has_adult_modal:
                print("[*] 命中 18+ 年龄确认弹窗，正在自动填写出生日期...")
                fill_js = """
                (function() {
                    var inp = document.querySelector('input[type="text"]');
                    if (inp) {
                        inp.focus();
                        inp.value = '01.01.1990';
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    var btns = Array.from(document.querySelectorAll('button'));
                    var confirmBtn = btns.find(b => b.innerText.includes('Подтвердить'));
                    if (confirmBtn) {
                        confirmBtn.click();
                        return true;
                    }
                    return false;
                })()
                """
                evaluate(fill_js)
                time.sleep(3)

        cookies_raw = call("Network.getAllCookies").get("result", {}).get("cookies", [])
        ozon_cookies = [c for c in cookies_raw if "ozon" in (c.get("domain") or "")]
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in ozon_cookies)
        ua = evaluate("navigator.userAgent")

        creds = {
            "cookie": cookie_header,
            "ua": ua,
            "proxy": proxy,
            "n_cookies": len(ozon_cookies),
            "at": time.time(),
        }
        save_cookie_cache(creds)
        print(f"[+] 预热成功！提取 Cookie 数量: {len(ozon_cookies)}")
        return creds
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            pass


def request_entrypoint_page(url, creds, proxy=None):
    """请求 Ozon 的 entrypoint-api 接口获取页面微前端 JSON"""
    u = urllib.parse.urlparse(url)
    api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={urllib.parse.quote(u.path + ('?' + u.query if u.query else ''))}"

    headers = {
        "User-Agent": creds.get("ua", "Mozilla/5.0"),
        "Cookie": creds.get("cookie", ""),
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Referer": "https://www.ozon.ru/",
    }

    proxies = {"http": proxy, "https": proxy} if proxy else None

    resp = cr.get(
        api_url,
        headers=headers,
        impersonate="chrome124",
        proxies=proxies,
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"Entrypoint API 请求失败，状态码: {resp.status_code}")


def extract_skus_from_page(page_json):
    """从 entrypoint-api 的响应中抽取商品卡片信息（含最新 stock_max 批量库存通道）"""
    if isinstance(page_json, dict) and "body" in page_json:
        b = page_json["body"]
        page_json = json.loads(b) if isinstance(b, str) else b
    ws = page_json.get("widgetStates", {})
    skus = []
    for k, v in ws.items():
        if "searchResultsV2" in k or "tileGrid" in k or "tile" in k:
            try:
                tile_data = json.loads(v) if isinstance(v, str) else v
                items = tile_data.get("items", [])
                for it in items:
                    raw_link = (it.get("action") or {}).get("link") or ""
                    clean_link = raw_link.split("?")[0] if raw_link else None

                    # 提取数值型 SKU ID
                    sku_id = it.get("sku") or it.get("id")
                    if not sku_id and clean_link:
                        m_sku = re.search(r"/product/.*?(\d{6,14})(?:/|$)", clean_link)
                        if m_sku:
                            sku_id = m_sku.group(1)

                    cell_ti = it.get("cellTrackingInfo") or {}
                    title = cell_ti.get("title")
                    price = parse_num(cell_ti.get("price"))
                    original_price = None
                    discount_pct = None
                    rating = parse_num(cell_ti.get("rating"))
                    reviews_count = parse_count_num(cell_ti.get("reviewCount"))

                    # 从 mainState 提取精准的 priceV2 现价/原价/折扣
                    for st in it.get("mainState") or []:
                        st_type = st.get("type")
                        if st_type == "priceV2":
                            pr_list = (st.get("priceV2") or {}).get("price") or []
                            if pr_list:
                                price = parse_num(pr_list[0].get("text")) or price
                            if len(pr_list) > 1:
                                original_price = parse_num(pr_list[1].get("text"))
                            discount_pct = parse_num((st.get("priceV2") or {}).get("discount"))
                        elif st_type == "textDS" and not title:
                            ds = st.get("textDS") or {}
                            aid = st.get("id") or ((ds.get("testInfo") or {}).get("automatizationId") or "")
                            if aid == "name":
                                title = (ds.get("text") or "").strip()
                        elif st_type == "labelListV2" and (rating is None or reviews_count is None):
                            texts = [x.get("text", {}).get("text") for x in ((st.get("labelListV2") or {}).get("items") or []) if x.get("text")]
                            texts = [x for x in texts if x]
                            if texts and rating is None:
                                rating = parse_num(texts[0])
                            if len(texts) > 1 and reviews_count is None:
                                reviews_count = parse_count_num(texts[1])

                    # 最新库存通道：multiButton.ozonButton.addToCart.quantityButton.maxItems
                    # （100% 覆盖，翻页即得全类目可用库存，2000 为平台上限）
                    mb = it.get("multiButton") or {}
                    ob = mb.get("ozonButton") or {}
                    qb = ((ob.get("addToCart") or {}).get("quantityButton")
                          or ob.get("quantityButton") or mb.get("quantityButton") or {})
                    stock_max = qb.get("maxItems")
                    if stock_max is None:
                        for st in it.get("mainState") or []:
                            if st.get("type") == "quantityButton":
                                stock_max = (st.get("quantityButton") or {}).get("maxItems")
                                break

                    tgi = it.get("trackingInfo") or {}
                    is_advert = bool(((tgi.get("click") or {}).get("custom") or {}).get("advertLite"))

                    skus.append({
                        "sku_id": str(sku_id) if sku_id else None,
                        "link": clean_link or raw_link,
                        "title": title,
                        "price": price,
                        "original_price": original_price,
                        "discount_pct": discount_pct,
                        "rating": rating,
                        "reviews_count": reviews_count,
                        "stock_max": stock_max,
                        "is_advert": is_advert,
                    })
            except Exception:
                pass
    return skus


def fetch_sku_seller_info(sku_link, creds, proxy=None):
    """从商品详情页提取店铺、单量、以及 PDP 级库存/价格 (webCurrentSeller / bigPromoPDP / webPrice)"""
    u = urllib.parse.urlparse(sku_link if sku_link.startswith("http") else f"https://www.ozon.ru{sku_link}")
    api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={urllib.parse.quote(u.path)}"

    headers = {
        "User-Agent": creds.get("ua", "Mozilla/5.0"),
        "Cookie": creds.get("cookie", ""),
        "Accept": "application/json",
        "Referer": "https://www.ozon.ru/",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None

    out = {
        "seller_name": None,
        "seller_id": None,
        "orders_str": None,
        "orders_count": 0,
        "rating": None,
        "promo_stock": None,
        "promo_sold_pct": None,
        "card_price": None,
        "price": None,
        "original_price": None,
        "is_available": None,
    }

    try:
        resp = cr.get(api_url, headers=headers, impersonate="chrome124", proxies=proxies, timeout=12)
        if resp.status_code != 200:
            return None
        data = resp.json()
        ws = data.get("widgetStates", {})
        for k, v in ws.items():
            if "webCurrentSeller" in k:
                s_data = json.loads(v) if isinstance(v, str) else v
                out["seller_name"] = s_data.get("name")
                out["seller_id"] = s_data.get("id")
                if not out["seller_name"]:
                    cell = s_data.get("sellerCell") or {}
                    out["seller_name"] = ((cell.get("centerBlock") or {}).get("title") or {}).get("text")
                if not out["seller_id"]:
                    m = re.search(r'"sellerId":\s*"?(\d{3,12})"?', json.dumps(s_data))
                    if m:
                        out["seller_id"] = m.group(1)

                for factor in s_data.get("trustFactors", []):
                    title = factor.get("title", "")
                    sub = factor.get("subtitle", "")
                    if "Заказ" in sub:
                        out["orders_str"] = title
                        out["orders_count"] = parse_count_num(title)
                    elif "рейтинг" in sub.lower() or "оценок" in sub.lower():
                        out["rating"] = title
            elif "bigPromoPDP" in k:
                bp = json.loads(v) if isinstance(v, str) else v
                out["promo_stock"] = (bp.get("stockNumber") or {}).get("text")
                out["promo_sold_pct"] = (bp.get("counter") or {}).get("percentage")
            elif "webPrice" in k:
                pr = json.loads(v) if isinstance(v, str) else v
                out["card_price"] = parse_num(pr.get("cardPrice"))
                out["price"] = parse_num(pr.get("price"))
                out["original_price"] = parse_num(pr.get("originalPrice"))
                out["is_available"] = pr.get("isAvailable")

        return out if (out["seller_name"] or out["seller_id"]) else None
    except Exception:
        return None


def fetch_sku_reviews(sku_id, creds, proxy=None, pages=1, sort="usefulness_desc"):
    """
    通过最新 reviews 接口获取评论列表
    端点: /api/entrypoint-api.bx/page/json/v2?url=/product/{sku}/reviews/?reviewsVariantMode=2&sort={sort}&page={page}
    支持排序: usefulness_desc / score_desc(高星在前) / score_asc(差评/1星在前)
    """
    if not sku_id:
        return {"total": 0, "reviews": []}
    all_reviews = []
    total_reviews = None
    overall_info = None

    headers = {
        "User-Agent": creds.get("ua", "Mozilla/5.0"),
        "Cookie": creds.get("cookie", ""),
        "Accept": "application/json",
        "Referer": f"https://www.ozon.ru/product/{sku_id}/",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None

    sort_q = f"?reviewsVariantMode=2&sort={sort}"
    for p in range(1, pages + 1):
        rel_path = f"/product/{sku_id}/reviews/{sort_q}" + ("" if p == 1 else f"&page={p}")
        api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={urllib.parse.quote(rel_path)}"
        try:
            resp = cr.get(api_url, headers=headers, impersonate="chrome124", proxies=proxies, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            ws = data.get("widgetStates", {})
            w_reviews = None
            for k, v in ws.items():
                if k.startswith("webListReviews"):
                    w_reviews = json.loads(v) if isinstance(v, str) else v
                elif k.startswith("webReviewProductScore") and not overall_info:
                    sc = json.loads(v) if isinstance(v, str) else v
                    overall_info = {"score": sc.get("totalScore"), "count": sc.get("reviewsCount")}

            if not w_reviews:
                break

            pg = w_reviews.get("paging") or {}
            if total_reviews is None:
                total_reviews = pg.get("total")

            rev_list = w_reviews.get("reviews") or []
            for r in rev_list:
                ct = r.get("content") or {}
                author_obj = r.get("author") or {}
                author_name = f"{author_obj.get('firstName', '')} {author_obj.get('lastName', '')}".strip() or None
                photos = [ph.get("url") for ph in (ct.get("photos") or []) if ph.get("url")]
                all_reviews.append({
                    "uuid": r.get("uuid"),
                    "score": parse_num(ct.get("score")),
                    "comment": ct.get("comment"),
                    "positive": ct.get("positive"),
                    "negative": ct.get("negative"),
                    "author": author_name,
                    "published_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r["publishedAt"])) if r.get("publishedAt") else None,
                    "photos": photos,
                    "useful": (r.get("usefulness") or {}).get("useful"),
                })
            if not rev_list:
                break
        except Exception:
            break

    return {
        "sku_id": str(sku_id),
        "sort": sort,
        "total": total_reviews,
        "overall": overall_info,
        "count": len(all_reviews),
        "reviews": all_reviews,
    }



def fetch_sku_other_offers(sku_id, creds, proxy=None):
    """从 /modal/otherOffersFromSellers 提取跟卖商总数、价格区间与跟卖商列表"""
    sku_str = str(sku_id).strip()
    headers = {
        "User-Agent": creds.get("ua", "Mozilla/5.0"),
        "Cookie": creds.get("cookie", ""),
        "Accept": "application/json",
        "Referer": "https://www.ozon.ru/",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    rel_path = f"/modal/otherOffersFromSellers?product_id={sku_str}&sort=price"
    api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={urllib.parse.quote(rel_path)}"

    try:
        resp = cr.get(api_url, headers=headers, impersonate="chrome124", proxies=proxies, timeout=12)
        if resp.status_code != 200:
            return None
        data = resp.json()
        ws = data.get("widgetStates", {})
        for k, v in ws.items():
            if "webSellerList" in k:
                d = json.loads(v) if isinstance(v, str) else v
                sellers_raw = d.get("sellers") or []
                extracted = []
                prices = []
                for s in sellers_raw:
                    cred = s.get("credentials") or []
                    comp_name, reg_no, city = None, None, None
                    if isinstance(cred, list):
                        if len(cred) > 0: comp_name = cred[0]
                        if len(cred) > 1: reg_no = cred[1]
                        if len(cred) > 2: city = cred[2]
                    elif isinstance(cred, dict):
                        comp_name = cred.get("name")
                        reg_no = cred.get("number")
                        city = cred.get("city")

                    price_val = parse_num(((s.get("price") or {}).get("cardPrice") or {}).get("price"))
                    if price_val is None:
                        price_val = parse_num((s.get("price") or {}).get("price"))
                    if price_val is not None:
                        prices.append(price_val)

                    extracted.append({
                        "seller_id": str(s.get("id")) if s.get("id") else None,
                        "seller_name": s.get("name"),
                        "competitor_sku": str(s.get("sku")) if s.get("sku") else None,
                        "price": price_val,
                        "company_name": comp_name,
                        "city": city,
                    })
                return {
                    "count": len(extracted),
                    "min_price": min(prices) if prices else None,
                    "max_price": max(prices) if prices else None,
                    "sellers": extracted
                }
    except Exception:
        return None
    return None

def run_collection(keyword=None, sku_inputs=None, out_file="ozon_collected.json",
                   max_pages=3, max_threads=8, reviews_pages=0, review_sort="usefulness_desc"):
    proxy = detect_proxy()
    print(f"[*] 当前网络代理: {proxy or '直连'}")

    # 1. 检查或进行 Cookie 预热
    creds = load_valid_cookie()
    if not creds:
        print("[*] 缓存中无可用 Cookie，启动 CDP 预热...")
        target = f"https://www.ozon.ru/search/?text={urllib.parse.quote(keyword)}" if keyword else "https://www.ozon.ru/"
        creds = cdp_warmup(target_url=target, proxy=proxy, is_adult=True)

    if not creds:
        print("[!] 预热失败，退出。")
        return

    unique_skus = []
    seen = set()

    # 2. 获取商品列表（搜索关键词模式 或 直接 SKU 模式）
    if keyword:
        all_skus = []
        print(f"[*] 开始检索关键词: {keyword}")
        for p in range(1, max_pages + 1):
            page_url = f"/search/?page={p}&text={urllib.parse.quote(keyword)}"
            try:
                p_json = request_entrypoint_page(page_url, creds, proxy=proxy)
                skus = extract_skus_from_page(p_json)
                print(f"  - 第 {p} 页抓取到 {len(skus)} 个商品卡片")
                all_skus.extend(skus)
                if not skus:
                    break
            except Exception as e:
                print(f"  [!] 第 {p} 页请求失败: {e}")

        for s in all_skus:
            ident = s.get("sku_id") or s.get("link")
            if ident and ident not in seen:
                seen.add(ident)
                unique_skus.append(s)
    elif sku_inputs:
        for s in sku_inputs:
            s_clean = str(s).strip()
            if s_clean and s_clean not in seen:
                seen.add(s_clean)
                unique_skus.append({
                    "sku_id": s_clean,
                    "link": f"/product/{s_clean}/",
                    "title": None,
                    "price": None,
                    "stock_max": None,
                })
    else:
        print("[!] 请提供 --keyword 或 --sku / --file 参数。")
        return

    print(f"[+] 累计去重获得 {len(unique_skus)} 个商品，开始并发提取店铺、最新库存与评论通道...")

    # 3. 并发提取详情（店铺+PDP库存）与评论通道
    seller_stats = {}

    def process_item(item):
        link = item.get("link")
        sku_id = item.get("sku_id")
        if not link and sku_id:
            link = f"/product/{sku_id}/"

        seller_info = fetch_sku_seller_info(link, creds, proxy)
        if seller_info:
            item["seller"] = {
                "id": seller_info.get("seller_id"),
                "name": seller_info.get("seller_name"),
                "orders_badge": seller_info.get("orders_str"),
                "orders_num": seller_info.get("orders_count") or 0,
                "rating": seller_info.get("rating"),
            }
            if seller_info.get("promo_stock"):
                item["promo_stock"] = seller_info.get("promo_stock")
                item["promo_sold_pct"] = seller_info.get("promo_sold_pct")
            if seller_info.get("card_price") and item.get("price") is None:
                item["price"] = seller_info.get("card_price")

        if with_offers and sku_id:
            offers = fetch_sku_other_offers(sku_id, creds, proxy=proxy)
            if offers:
                item["competing_offers_count"] = offers["count"]
                item["competing_min_price"] = offers["min_price"]
                item["competing_sellers"] = offers["sellers"]

        if reviews_pages > 0 and sku_id:
            rev_data = fetch_sku_reviews(sku_id, creds, proxy=proxy, pages=reviews_pages, sort=review_sort)
            item["reviews_data"] = rev_data
            if rev_data.get("total") is not None:
                item["reviews_count"] = rev_data.get("total")
        return item, seller_info

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {executor.submit(process_item, item): item for item in unique_skus}
        done_cnt = 0
        for fut in futures:
            try:
                item, seller = fut.result()
                done_cnt += 1
                if done_cnt % 5 == 0 or done_cnt == len(unique_skus):
                    print(f"  进度: [{done_cnt}/{len(unique_skus)}]")
                if seller and seller.get("seller_name"):
                    s_id = seller["seller_id"]
                    if s_id not in seller_stats:
                        seller_stats[s_id] = {
                            "name": seller["seller_name"],
                            "seller_id": s_id,
                            "orders_badge": seller.get("orders_str"),
                            "orders_num": seller.get("orders_count") or 0,
                            "rating": seller.get("rating"),
                            "sample_skus": [item.get("sku_id") or item.get("link")],
                            "total_stock": item.get("stock_max") or 0,
                        }
                    else:
                        seller_stats[s_id]["sample_skus"].append(item.get("sku_id") or item.get("link"))
                        if item.get("stock_max"):
                            seller_stats[s_id]["total_stock"] += item["stock_max"]
                        if seller.get("orders_count") and seller["orders_count"] > seller_stats[s_id]["orders_num"]:
                            seller_stats[s_id]["orders_num"] = seller["orders_count"]
                            seller_stats[s_id]["orders_badge"] = seller.get("orders_str")
            except Exception:
                pass

    sorted_sellers = sorted(seller_stats.values(), key=lambda x: x["orders_num"], reverse=True)

    # 库存统计
    stock_hits = [s for s in unique_skus if s.get("stock_max") is not None]
    total_stock_units = sum(s["stock_max"] for s in stock_hits)

    result_data = {
        "keyword": keyword,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_skus": len(unique_skus),
        "inventory_summary": {
            "skus_with_stock_max": len(stock_hits),
            "stock_coverage_pct": round(len(stock_hits) / len(unique_skus) * 100, 1) if unique_skus else 0,
            "total_stock_units": total_stock_units,
        },
        "total_sellers": len(sorted_sellers),
        "sellers": sorted_sellers,
        "skus": unique_skus,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"\n[+] 采集完成！输出结果文件: {out_file}")
    print(f"[*] 库存通道统计: {len(stock_hits)}/{len(unique_skus)} SKU 命中 stock_max (总可用库存: {total_stock_units})")
    if reviews_pages > 0:
        rev_count = sum(len(s.get("reviews_data", {}).get("reviews", [])) for s in unique_skus)
        print(f"[*] 评论通道统计: 累计获取 {rev_count} 条评论 (排序模式: {review_sort})")

    print(f"\n{'排名':<4} {'店铺名称':<25} {'店铺ID':<10} {'历史单量':<10} {'好评率':<8} {'在售总库存':<10}")
    for idx, s in enumerate(sorted_sellers[:10], 1):
        print(f"{idx:<4} {s['name'][:24]:<25} {str(s['seller_id']):<10} {str(s['orders_badge']):<10} {str(s['rating']):<8} {str(s.get('total_stock', 0)):<10}")


def main():
    parser = argparse.ArgumentParser(description="Ozon 鲁棒高并发综合采集工具（支持最新库存+评论通道）")
    parser.add_argument("--keyword", default="пеньюар кружевной", help="搜索关键词")
    parser.add_argument("--sku", action="append", help="指定单个或多个 SKU（可多次传入）")
    parser.add_argument("--file", help="SKU 列表文件（每行一个）")
    parser.add_argument("--out", default="erotic_sellers.json", help="输出路径")
    parser.add_argument("--pages", type=int, default=2, help="爬取页数")
    parser.add_argument("--threads", type=int, default=6, help="详情并发线程数")
    parser.add_argument("--reviews", type=int, default=0, help="评论抓取页数（30 条/页，0=不抓）")
    parser.add_argument("--with-offers", action="store_true", help="同时抓取同款跟卖商家数量与名单明细")
    parser.add_argument("--sort", default="usefulness_desc",
                        choices=["usefulness_desc", "score_desc", "score_asc"],
                        help="评论排序（score_asc=差评/1星在前、score_desc=好评在前、usefulness_desc=最有价值）")
    args = parser.parse_args()

    sku_list = list(args.sku or [])
    if args.file and os.path.exists(args.file):
        sku_list += [l.strip() for l in open(args.file, encoding="utf-8") if l.strip() and not l.startswith("#")]

    run_collection(
        keyword=args.keyword if not sku_list else None,
        sku_inputs=sku_list if sku_list else None,
        out_file=args.out,
        max_pages=args.pages,
        max_threads=args.threads,
        reviews_pages=args.reviews,
        review_sort=args.sort,
        with_offers=args.with_offers,
    )


if __name__ == "__main__":
    main()
