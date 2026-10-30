const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/lite.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const task = await taskSpace("ozon-lite-probe");
const page = task.page("p1");
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);
const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const tries = [
  ["baseline_p2", "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=2")],
  ["layout_container", "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=2&layout_container=catalogResults")],
  ["widget_tile", "/api/composer-api.bx/widget/json/v2?widgetStateId=tileGridDesktop-3669724-default-1"],
  ["widget_tile_p2", "/api/composer-api.bx/widget/json/v2?widgetStateId=tileGridDesktop-3669724-default-1&page=2"],
  ["composer_page", "/api/composer-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=2")],
];
for (const [label, u] of tries) {
  const t0 = Date.now();
  try {
    const r = await page.fetch(u, { headers:{accept:"application/json"}, timeout: 30000 });
    let n = null, head = "";
    try { const j = JSON.parse(r.body); head = JSON.stringify(j).slice(0, 160); } catch { head = (r.body||"").slice(0,120); }
    await w({ label, s: r.status, ms: Date.now()-t0, bytes: (r.body||"").length, head });
  } catch(e) { await w({ label, err: String(e).slice(0,60), ms: Date.now()-t0 }); }
  await page.waitForTimeout(1500);
}
await w({ done:true });
