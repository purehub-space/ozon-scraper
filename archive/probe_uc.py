import json, tempfile, time, urllib.parse
import undetected_chromedriver as uc

PROFILE = tempfile.mkdtemp(prefix="ozon-uc-")
opts = uc.ChromeOptions()
opts.add_argument(f"--user-data-dir={PROFILE}")
opts.add_argument("--window-size=1440,900")
opts.add_argument("--no-first-run")
opts.add_argument("--lang=zh-CN")
d = uc.Chrome(options=opts, driver_executable_path="/Users/a1234/.cache/selenium/chromedriver/mac-arm64/156.0.8078.73/chromedriver", use_subprocess=True)
print("uc up, profile:", PROFILE)

COOKIE = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json"
d.get("https://www.ozon.ru/robots.txt")
time.sleep(1)
try:
    for c in json.load(open(COOKIE)):
        d.add_cookie({"name": c["name"], "value": c["value"], "domain": c.get("domain") or ".ozon.ru", "path": "/", "secure": bool(c.get("secure"))})
    print("cookies injected")
except Exception as e:
    print("cookie err", str(e)[:80])
d.get("https://www.ozon.ru/robots.txt")
time.sleep(1)
print("url:", d.current_url)

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
JS = """
const url = arguments[0], done = arguments[arguments.length-1];
const t0 = performance.now();
fetch(url, {headers:{accept:'application/json'}}).then(async r => { const t = await r.text();
  done({s:r.status, ms:Math.round(performance.now()-t0), len:t.length, kind: r.status===200 ? 'json' : t.slice(0,50)}); })
  .catch(e => done({err:String(e).slice(0,60)}));
"""
for i in range(3):
    try:
        print(i, d.execute_async_script(JS, "/api/entrypoint-api.bx/page/json/v2?url=" + urllib.parse.quote(B + f"&page={i+2}", safe="")))
    except Exception as e:
        print(i, "ERR", str(e)[:100])
    time.sleep(1)
d.quit()
