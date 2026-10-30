const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/cat2.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-cat-probe2", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);
const BASE = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const seen = new Map();
const pull = async (p) => {
  const q = p === 1 ? "" : `&page=${p}`;
  const t0 = Date.now();
  try {
    const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(BASE + q), { headers:{accept:"application/json"}, timeout: 35000 });
    if (r.status !== 200) return w({ p, s:r.status, ms:Date.now()-t0 });
    const ws = JSON.parse(r.body).widgetStates || {};
    let items=[];
    for (const [k, raw] of Object.entries(ws)) if (k.startsWith("tileGridDesktop")) items = JSON.parse(raw).items||[];
    if (p === 1) {
      const s = r.body;
      const m = s.match(/([\d\u202f\s]{3,12})\s*(?:товар|商品)/g);
      await w({ p, totalHints: m ? m.slice(0,4) : null });
      await fs.writeFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/raw-cat-p1.json", r.body);
    }
    const dup = items.filter(i => seen.has(i.sku)).length;
    items.forEach(i => seen.set(i.sku, p));
    await w({ p, ms:Date.now()-t0, n:items.length, dup, totalUnique:seen.size, first:items[0]&&items[0].sku });
  } catch(e) { await w({ p, err:String(e).slice(0,50) }); }
};
for (const p of [1, 2000, 5000, 10000, 20000]) { await pull(p); await page.waitForTimeout(600); }
await w({ done:true, totalUnique: seen.size });
