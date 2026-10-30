const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/withcookie.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-withcookie-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(()=>{});
await page.waitForTimeout(600);
const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const times = []; let succ = 0;
for (let i = 0; i < 10; i++) {
  const t0 = Date.now();
  try {
    const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=" + (i + 30)), { headers: { accept: "application/json" }, timeout: 30000 });
    const ms = Date.now() - t0;
    if (r.status === 200) { succ++; times.push(ms); }
    await w({ i, s: r.status, ms, bytes: (r.body||"").length });
  } catch (e) { await w({ i, err: String(e).slice(0, 50), ms: Date.now()-t0 }); }
  await page.waitForTimeout(600);
}
times.sort((a,b)=>a-b);
await w({ summary: { succ, n: times.length, min: times[0], median: times[Math.floor(times.length/2)], max: times[times.length-1], avg: Math.round(times.reduce((a,b)=>a+b,0)/times.length) } });
await w({ done: true });
