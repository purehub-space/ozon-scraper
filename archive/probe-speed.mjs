const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/speed.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-speed-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);

const api = (n) => "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(`/seller/39932/?page=${n}`);
const get = async (n) => {
  const t0 = Date.now();
  try {
    const r = await page.fetch(api(n), { headers:{accept:"application/json"}, timeout: 30000 });
    if (r.status !== 200) return { n, s: r.status, ms: Date.now()-t0 };
    const ws = JSON.parse(r.body).widgetStates || {};
    const k = Object.keys(ws).find(x=>x.startsWith("tileGridDesktop"));
    const items = k ? (JSON.parse(ws[k]).items || []) : [];
    return { n, s: 200, ms: Date.now()-t0, c: items.length };
  } catch(e) { return { n, s: "ERR", ms: Date.now()-t0 }; }
};

// A: 串行 12 页, delay 300
let t0 = Date.now(), succ = 0, items = 0;
for (let i=0;i<12;i++) { const r = await get(180+i); if (r.s===200) { succ++; items += r.c; } await page.waitForTimeout(300); }
await w({ phase:"serial12_delay300", wall: Date.now()-t0, succ, items });

// B: 并发 4, 12 页
t0 = Date.now(); succ = 0; items = 0;
for (let i=0;i<12;i+=4) {
  const rs = await Promise.all([get(200+i), get(201+i), get(202+i), get(203+i)]);
  for (const r of rs) if (r.s===200) { succ++; items += r.c; }
  await page.waitForTimeout(300);
}
await w({ phase:"conc4_12", wall: Date.now()-t0, succ, items });

// C: 并发 8, 16 页
t0 = Date.now(); succ = 0; items = 0;
for (let i=0;i<16;i+=8) {
  const rs = await Promise.all(Array.from({length:8},(_,k)=>get(220+i+k)));
  for (const r of rs) if (r.s===200) { succ++; items += r.c; }
  await page.waitForTimeout(500);
}
await w({ phase:"conc8_16", wall: Date.now()-t0, succ, items });
await w({ done:true });
