const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/cat3.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-cat-probe3", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);
const BASE = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const pull = async (p) => {
  const t0 = Date.now();
  try {
    const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(BASE + `&page=${p}`), { headers:{accept:"application/json"}, timeout: 35000 });
    if (r.status !== 200) { await w({ p, s:r.status }); return; }
    const ws = JSON.parse(r.body).widgetStates || {};
    let items=[];
    for (const [k, raw] of Object.entries(ws)) if (k.startsWith("tileGridDesktop")) items = JSON.parse(raw).items||[];
    await w({ p, ms:Date.now()-t0, n:items.length, first:items[0]&&items[0].sku, last:items.length?items[items.length-1].sku:null });
  } catch(e) { await w({ p, err:String(e).slice(0,50) }); }
};
for (const p of [999, 1000, 1001, 1100, 1250, 1500, 1750]) { await pull(p); await page.waitForTimeout(500); }
await w({ done:true });
