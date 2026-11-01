import json, tempfile, time, sys, urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

HEADLESS = "--headful" not in sys.argv
COOKIE = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json"
opts = Options()
if HEADLESS: opts.add_argument("--headless=new")
opts.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='ozon-prof-')}")
opts.add_argument("--no-first-run"); opts.add_argument("--no-default-browser-check")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_argument("--window-size=1440,900")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)
d = webdriver.Chrome(options=opts)
d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})

d.get("https://www.ozon.ru/robots.txt")
cookies = json.load(open(COOKIE))
ok = 0
for c in cookies:
    try:
        ck = {"name": c["name"], "value": c["value"], "domain": c.get("domain") or ".ozon.ru", "path": c.get("path") or "/", "secure": bool(c.get("secure"))}
        d.add_cookie(ck); ok += 1
    except Exception as e:
        pass
print("cookies added:", ok, "/", len(cookies), "headless:", HEADLESS)
d.get("https://www.ozon.ru/robots.txt")
time.sleep(1)

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
JS = """
const url = arguments[0], done = arguments[arguments.length-1];
const t0 = performance.now();
fetch(url, {headers: {accept: 'application/json'}})
  .then(async r => { const t = await r.text(); let kind='json';
    if (r.status !== 200) { try { const j=JSON.parse(t); kind = j.incidentId ? 'challenge' : 'err'; } catch(e){ kind=t.slice(0,50); } }
    done({s:r.status, ms:Math.round(performance.now()-t0), len:t.length, kind}); })
  .catch(e => done({err:String(e).slice(0,80)}));
"""
for i in range(3):
    t = time.time()
    try:
        print(i, d.execute_async_script(JS, "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={i+2}", safe="")), "wall", round(time.time()-t,1))
    except Exception as e:
        print(i, "ERR", str(e)[:100])
    time.sleep(1)
d.quit()
