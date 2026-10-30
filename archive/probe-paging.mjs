const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/paging.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const task = await taskSpace("ozon-paging-probe");
const page = task.page("p1");
await page.goto("https://www.ozon.ru/", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(()=>{});
await page.waitForTimeout(2500);

const pull = async (path, label) => {
  for (let a=0;a<2;a++) {
    try {
      const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(path), { headers:{accept:"application/json"}, timeout: 30000 });
      if (r.status !== 200) { await w({ label, status: r.status }); continue; }
      const j = JSON.parse(r.body);
      const ws = j.widgetStates || {};
      let items = [], next = null, gridPage = null, total = null;
      for (const [k, raw] of Object.entries(ws)) {
        if (k.startsWith("tileGridDesktop")) {
          const t = JSON.parse(raw);
          items = t.items || []; gridPage = t.page; total = t.total || t.totalCount || null;
        }
        if (k.startsWith("infiniteVirtualPaginator")) {
          const p = JSON.parse(raw);
          next = p.nextPage || null;
        }
      }
      await w({ label, n: items.length, gridPage, next: next ? next.slice(0, 120) : null,
        skus: items.map(i=>i.sku).slice(0,4) });
      return { items, next, ws };
    } catch(e) { await w({ label, err: String(e).slice(0,60) }); await page.waitForTimeout(2000); }
  }
  return null;
};

const base = await pull("/seller/39932/", "base");
await page.waitForTimeout(3000);
if (base && base.next) { await pull(base.next, "p2_via_next"); await page.waitForTimeout(3000); }
await pull("/seller/39932/?page=3", "q_page3");
await page.waitForTimeout(3000);
await pull("/seller/39932/?sorting=new", "q_sort_new");
await page.waitForTimeout(3000);
await pull("/seller/39932/?layout_page_index=3&page=3", "q_layout3");
await w({ done: true });
