const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/limit.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-limit-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(500);
const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const variants = ["&page=2&per_page=40","&page=2&limit=40","&page=2&page_size=40","&page=2&items_per_page=40","&page=2&layout_page_index=2&per_page=40"];
for (const q of variants) {
  const t0=Date.now();
  try {
    const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + q), { headers:{accept:"application/json"}, timeout:30000 });
    const ws = JSON.parse(r.body).widgetStates || {};
    let n=0;
    for (const [k,raw] of Object.entries(ws)) if (k.startsWith("tileGridDesktop")) n=(JSON.parse(raw).items||[]).length;
    await w({ q, s:r.status, ms:Date.now()-t0, items:n, bytes:(r.body||"").length });
  } catch(e) { await w({ q, err:String(e).slice(0,50) }); }
  await page.waitForTimeout(900);
}
await w({ done:true });
