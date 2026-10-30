const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/depth.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const task = await taskSpace("ozon-depth-probe");
const page = task.page("p1");
await page.goto("https://www.ozon.ru/", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(()=>{});
await page.waitForTimeout(2500);
const seen = new Set();
const pull = async (path) => {
  for (let a=0;a<2;a++) {
    try {
      const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(path), { headers:{accept:"application/json"}, timeout: 30000 });
      if (r.status !== 200) return { status: r.status, n: 0 };
      const ws = JSON.parse(r.body).widgetStates || {};
      let items = [];
      for (const [k, raw] of Object.entries(ws)) if (k.startsWith("tileGridDesktop")) items = JSON.parse(raw).items || [];
      return { n: items.length, skus: items.map(i=>i.sku) };
    } catch(e) { await page.waitForTimeout(2000); }
  }
  return { n: 0, err: true };
};
for (let p=1; p<=12; p++) {
  const path = p === 1 ? "/seller/39932/" : `/seller/39932/?page=${p}`;
  const r = await pull(path);
  const fresh = (r.skus||[]).filter(s=>!seen.has(s));
  for (const s of r.skus||[]) seen.add(s);
  await w({ p, n: r.n, fresh: fresh.length, totalUnique: seen.size, status: r.status });
  await page.waitForTimeout(3000);
  if (!r.n) break;
}
await w({ done: true, totalUnique: seen.size });
