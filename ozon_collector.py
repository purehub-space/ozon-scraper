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
    """从 entrypoint-api 的响应中抽取商品卡片信息"""
    ws = page_json.get("widgetStates", {})
    skus = []
    for k, v in ws.items():
        if "searchResultsV2" in k or "tileGrid" in k or "tile" in k:
            try:
                tile_data = json.loads(v) if isinstance(v, str) else v
                items = tile_data.get("items", [])
                for it in items:
                    sku = it.get("action", {}).get("link")
                    title = it.get("cellTrackingInfo", {}).get("title")
                    price = it.get("cellTrackingInfo", {}).get("price")
                    rating = it.get("cellTrackingInfo", {}).get("rating")
                    reviews = it.get("cellTrackingInfo", {}).get("reviewCount")
                    skus.append({
                        "link": sku,
                        "title": title,
                        "price": price,
                        "rating": rating,
                        "reviews": reviews,
                    })
            except Exception:
                pass
    return skus


def fetch_sku_seller_info(sku_link, creds, proxy=None):
    """从商品详情页的 webCurrentSeller 组件提取店铺与单量信息"""
    u = urllib.parse.urlparse(sku_link if sku_link.startswith("http") else f"https://www.ozon.ru{sku_link}")
    api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url={urllib.parse.quote(u.path)}"

    headers = {
        "User-Agent": creds.get("ua", "Mozilla/5.0"),
        "Cookie": creds.get("cookie", ""),
        "Accept": "application/json",
        "Referer": "https://www.ozon.ru/",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        resp = cr.get(api_url, headers=headers, impersonate="chrome124", proxies=proxies, timeout=12)
        if resp.status_code != 200:
            return None
        data = resp.json()
        ws = data.get("widgetStates", {})
        for k, v in ws.items():
            if "webCurrentSeller" in k:
                s_data = json.loads(v) if isinstance(v, str) else v
                name = s_data.get("name")
                seller_id = s_data.get("id")
                orders_str = None
                rating_str = None
                for factor in s_data.get("trustFactors", []):
                    title = factor.get("title", "")
                    sub = factor.get("subtitle", "")
                    if "Заказ" in sub:
                        orders_str = title
                    elif "рейтинг" in sub.lower() or "оценок" in sub.lower():
                        rating_str = title

                return {
                    "seller_name": name,
                    "seller_id": seller_id,
                    "orders_str": orders_str,
                    "orders_count": parse_count_num(orders_str),
                    "rating": rating_str,
                }
    except Exception:
        return None
    return None


def run_collection(keyword, out_file, max_pages=3, max_threads=8):
    proxy = detect_proxy()
    print(f"[*] 当前网络代理: {proxy or '直连'}")

    # 1. 检查或进行 Cookie 预热
    creds = load_valid_cookie()
    if not creds:
        print("[*] 缓存中无可用 Cookie，启动 CDP 预热...")
        target = f"https://www.ozon.ru/search/?text={urllib.parse.quote(keyword)}"
        creds = cdp_warmup(target_url=target, proxy=proxy, is_adult=True)

    if not creds:
        print("[!] 预热失败，退出。")
        return

    # 2. 爬取多页商品
    all_skus = []
    print(f"[*] 开始检索关键词: {keyword}")
    for p in range(1, max_pages + 1):
        page_url = f"/search/?page={p}&text={urllib.parse.quote(keyword)}"
        try:
            p_json = request_entrypoint_page(page_url, creds, proxy=proxy)
            skus = extract_skus_from_page(p_json)
            print(f"  - 第 {p} 页抓取到 {len(skus)} 个 SKU")
            all_skus.extend(skus)
            if not skus:
                break
        except Exception as e:
            print(f"  [!] 第 {p} 页请求失败: {e}")

    # 去重
    unique_skus = []
    seen = set()
    for s in all_skus:
        link = s.get("link")
        if link and link not in seen:
            seen.add(link)
            unique_skus.append(s)

    print(f"[+] 累计去重获得 {len(unique_skus)} 个商品，开始并发提取店铺与历史销量...")

    # 3. 并发提取店铺与单量
    seller_stats = {}
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {executor.submit(fetch_sku_seller_info, item["link"], creds, proxy): item for item in unique_skus}
        done_cnt = 0
        for fut in futures:
            item = futures[fut]
            try:
                seller = fut.result()
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
                            "sample_skus": [item["link"]],
                        }
                    else:
                        seller_stats[s_id]["sample_skus"].append(item["link"])
                        if seller.get("orders_count") and seller["orders_count"] > seller_stats[s_id]["orders_num"]:
                            seller_stats[s_id]["orders_num"] = seller["orders_count"]
                            seller_stats[s_id]["orders_badge"] = seller.get("orders_str")
            except Exception:
                pass

    sorted_sellers = sorted(seller_stats.values(), key=lambda x: x["orders_num"], reverse=True)

    result_data = {
        "keyword": keyword,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_skus": len(unique_skus),
        "total_sellers": len(sorted_sellers),
        "sellers": sorted_sellers,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"\n[+] 采集完成！输出结果文件: {out_file}")
    print(f"{'排名':<4} {'店铺名称':<25} {'店铺ID':<10} {'历史单量':<10} {'好评率':<8}")
    for idx, s in enumerate(sorted_sellers[:10], 1):
        print(f"{idx:<4} {s['name'][:24]:<25} {str(s['seller_id']):<10} {str(s['orders_badge']):<10} {str(s['rating']):<8}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ozon 鲁棒店铺与商品采集工具")
    parser.add_argument("--keyword", default="пеньюар кружевной", help="搜索关键词")
    parser.add_argument("--out", default="erotic_sellers.json", help="输出路径")
    parser.add_argument("--pages", type=int, default=2, help="爬取页数")
    parser.add_argument("--threads", type=int, default=6, help="详情并发线程数")
    args = parser.parse_args()

    run_collection(args.keyword, args.out, max_pages=args.pages, max_threads=args.threads)
