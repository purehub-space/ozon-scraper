import json, tempfile, time, sys, urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

HEADLESS = "--headless" in sys.argv
PROFILE = tempfile.mkdtemp(prefix="ozon-prof-")
opts = Options()
if HEADLESS: opts.add_argument("--headless=new")
opts.add_argument(f"--user-data-dir={PROFILE}")
opts.add_argument("--no-first-run"); opts.add_argument("--no-default-browser-check")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_argument("--window-size=1440,900")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)
d = webdriver.Chrome(options=opts)
d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})

URL = "https://www.ozon.ru/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
print("profile:", PROFILE, "headless:", HEADLESS)
d.get(URL)
for i in range(8):
    time.sleep(3)
    try:
        u = d.current_url; t = d.title
        body = d.execute_script("return (document.body && document.body.innerText || '').slice(0,120)")
        print(i*3+3, "s |", u[:90], "|", t[:40], "|", body.replace("\n"," ")[:80])
        if "challenge" not in u and "block" not in u and len(t) > 5:
            break
    except Exception as e:
        print("wait err", str(e)[:80])
print("--- cookies ---")
for c in d.get_cookies():
    print(" ", c["name"], len(c.get("value") or ""))
print("--- fetch test ---")
B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
JS = """
const url = arguments[0], done = arguments[arguments.length-1];
fetch(url, {headers:{accept:'application/json'}}).then(async r => { const t = await r.text();
  done({s:r.status, len:t.length, kind: r.status===200 ? 'json' : t.slice(0,60)}); }).catch(e => done({err:String(e).slice(0,60)}));
"""
for i in range(2):
    try:
        print(d.execute_async_script(JS, "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={i+2}", safe="")))
    except Exception as e:
        print("fetch err", str(e)[:100])
d.quit()
