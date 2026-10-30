import json, time, urllib.parse
import undetected_chromedriver as uc

opts = uc.ChromeOptions()
opts.add_argument("--window-size=1440,900")
opts.add_argument("--lang=zh-CN")
d = uc.Chrome(options=opts, driver_executable_path="/Users/a1234/.cache/selenium/chromedriver/mac-arm64/156.0.8078.73/chromedriver", use_subprocess=True)
print("uc up")

B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F"
d.get("https://www.ozon.ru/robots.txt")
time.sleep(2)
print("url:", d.current_url)
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
        print(i, "ERR", str(e)[:110])
    time.sleep(1)
d.quit()
