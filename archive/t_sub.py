import subprocess, json, time
js = '''
const fs = await import("node:fs/promises");
const task = await taskSpace("ozon-py-" + Date.now());
const page = task.page("p1");
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(400);
const t0 = Date.now();
const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent("/modal/shop-in-shop-info?seller_id=78486"), { headers:{accept:"application/json"}, timeout:30000 });
await fs.writeFile("/tmp/ozon-t-sub.json", JSON.stringify({ s: r.status, ms: Date.now()-t0, len: (r.body||"").length }));
'''
t = time.time()
p = subprocess.run(["/Users/a1234/.local/bin/ego-browser", "nodejs"], input=js, text=True, capture_output=True, timeout=120)
print("rc:", p.returncode, "elapsed:", round(time.time()-t,1))
print("stdout:", p.stdout.strip()[-300:])
print("stderr:", p.stderr.strip()[-300:])
try:
    print("result:", json.load(open("/tmp/ozon-t-sub.json")))
except Exception as e:
    print("no result:", e)
