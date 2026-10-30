#!/usr/bin/env python3
"""
从本机已登录的浏览器直接读 Ozon cookie —— 零窗口、零预热、完全后台。

原理：
  Chrome / Edge / Brave / Firefox / Safari 的 cookie 存在本地数据库里（Chrome 用 Keychain 加密）。
  browser_cookie3 读出来解密，其中就有 Ozon 反爬需要的 abt_data + __Secure-ETC。
  前提：这个浏览器访问过 www.ozon.ru（走过一次 antibot challenge）。

为什么比预热好：
  - 不启动浏览器进程，屏幕上一个窗口都没有
  - 不占内存（预热要 4 个 Chrome = 1.2GB）
  - 立刻可用（0 秒，不用等 8~13 秒）

实测（2026-10-30，Chrome 42 个 ozon cookie）：
  seller 200 / pdp 200 / list p1 200 / list p2 200 / 图搜结果 200

用法：
  python3 cookie_from_browser.py                 # 读 Chrome，校验后写缓存
  python3 cookie_from_browser.py --browser edge
  python3 cookie_from_browser.py --browser chrome --no-validate
  python3 cookie_from_browser.py --check         # 只看有没有，不写

⚠️ 这是「借用你日常浏览器的会话」。如果那个浏览器没访问过 ozon.ru，会读不到 abt_data，
   这时才需要退回 prepare_pool.py（会起窗口，但移到屏幕外）。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import time
import urllib.parse

CACHE = os.path.expanduser("~/.cache/ozon-search")
TEST_URL = ("https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url="
            + urllib.parse.quote("/seller/78486/", safe=""))

BROWSERS = ["chrome", "edge", "brave", "chromium", "firefox", "safari", "opera", "vivaldi"]


def detect_chrome_version():
    """从 app 的 Info.plist 读版本，构造真�� UA"""
    cands = [
        "/Applications/Google Chrome.app/Contents/Info.plist",
        "/Applications/Microsoft Edge.app/Contents/Info.plist",
        "/Applications/Brave Browser.app/Contents/Info.plist",
    ]
    for c in cands:
        if os.path.exists(c):
            try:
                out = subprocess.run(["/usr/bin/defaults", "read", c, "CFBundleShortVersionString"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                m = re.match(r"(\d+)\.", out)
                if m:
                    return m.group(1)
            except Exception:
                pass
    return "156"


def read_cookies(browser="chrome", domain="ozon.ru"):
    try:
        import browser_cookie3 as bc3
    except ImportError:
        raise SystemExit("需要 browser_cookie3：pip3 install --user browser-cookie3")
    fn = getattr(bc3, browser, None)
    if fn is None:
        raise SystemExit(f"不支持的浏览器: {browser}（可选 {', '.join(BROWSERS)}）")
    jar = fn(domain_name=domain)
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in jar]


def build_ua():
    return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{detect_chrome_version()}.0.0.0 Safari/537.36")


def creds_from_browser(browser="chrome", do_validate=True, quiet=False):
    """给采集脚本用：读 cookie → 返回 creds dict（失败返回 None）"""
    try:
        cks = read_cookies(browser)
    except SystemExit:
        return None
    except Exception:
        return None
    if not cks or not any(c["name"] == "abt_data" for c in cks):
        return None
    ua = build_ua()
    if do_validate and not validate(cks, ua, quiet=quiet):
        return None
    return {"cookie": "; ".join(f"{c['name']}={c['value']}" for c in cks),
            "ua": ua, "n_cookies": len(cks), "at": time.time(), "source": browser}


def build_headers(cookies, ua):
    return {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9,ru;q=0.8",
        "referer": "https://www.ozon.ru/",
        "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": ua,
        "cookie": "; ".join(f"{c['name']}={c['value']}" for c in cookies),
    }


def validate(cookies, ua, quiet=False):
    from curl_cffi import requests as cr
    t0 = time.time()
    try:
        r = cr.get(TEST_URL, headers=build_headers(cookies, ua), impersonate="chrome", timeout=25)
        ms = int((time.time() - t0) * 1000)
        ok = r.status_code == 200 and len(r.text) > 1000
        if not quiet:
            print(f"[{'OK' if ok else 'FAIL'}] 校验 {r.status_code} len={len(r.text)} {ms}ms")
        return ok
    except Exception as e:
        if not quiet:
            print(f"[FAIL] 校验异常 {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="chrome", choices=BROWSERS)
    ap.add_argument("--no-validate", action="store_true", help="不做 API 校验直接存")
    ap.add_argument("--check", action="store_true", help="只看，不写缓存")
    ap.add_argument("--out", default=None, help="输出路径（默认 ~/.cache/ozon-search/browser.json）")
    a = ap.parse_args()

    if a.check:
        for b in BROWSERS:
            try:
                cks = read_cookies(b)
                names = {c["name"] for c in cks}
                print(f"  {b:9} {len(cks):>3} cookies  abt_data={'✓' if 'abt_data' in names else '✗'}"
                      f"  ETC={'✓' if '__Secure-ETC' in names else '✗'}")
            except Exception as e:
                print(f"  {b:9} — ({type(e).__name__})")
        return

    print(f"[*] 从 {a.browser} 读取 ozon.ru cookie...")
    cks = read_cookies(a.browser)
    names = {c["name"] for c in cks}
    print(f"[+] {len(cks)} 个 cookie，abt_data={'有' if 'abt_data' in names else '没有'}"
          f"，__Secure-ETC={'有' if '__Secure-ETC' in names else '没有'}")

    if "abt_data" not in names:
        print("[!] 缺 abt_data —— 这个浏览器没访问过 www.ozon.ru（或 cookie 已清）")
        print("    可选：① 用它打开一次 www.ozon.ru（一次就够，之后长期有效）")
        print("          ② python3 prepare_pool.py --n 4   （起屏幕外窗口预热）")
        raise SystemExit(2)

    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          f"(KHTML, like Gecko) Chrome/{detect_chrome_version()}.0.0.0 Safari/537.36")

    if not a.no_validate and not validate(cks, ua):
        print("[!] 校验失败：cookie 可能已过期，或这份会话不能用于外部请求")
        print("    试试用它打开一次 www.ozon.ru 刷新，或退回 prepare_pool.py")
        raise SystemExit(2)

    os.makedirs(CACHE, exist_ok=True)
    out = a.out or os.path.join(CACHE, "browser.json")
    data = {"cookie": "; ".join(f"{c['name']}={c['value']}" for c in cks),
            "ua": ua, "n_cookies": len(cks), "at": time.time(), "source": a.browser}
    json.dump(data, open(out, "w"))
    # 同时写成池格式，让 --pool 也能直接用（只有一个会话）
    json.dump({**data, "i": 0, "n": len(cks)}, open(os.path.join(CACHE, "pool-0.json"), "w"))
    print(f"[+] 已保存: {out}")
    print(f"[+] 采集脚本直接用：--browser {a.browser} 或 --pool 1")


if __name__ == "__main__":
    main()
