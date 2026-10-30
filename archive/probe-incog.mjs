const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/incog.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");

// 1) 试 incognito 选项
let task = null, mode = null;
for (const opt of [{ incognito: true }, { private: true }, { isolated: true }]) {
  try { task = await taskSpace("ozon-incog-" + Object.keys(opt)[0], opt); mode = JSON.stringify(opt); await w({ created: mode, space: task.spaceId }); break; }
  catch (e) { await w({ opt: JSON.stringify(opt), err: String(e).slice(0, 120) }); }
}
if (!task) { await w({ fallback: "use Profile 1 + clear ozon cookies" }); }

if (!mode) {
  task = await taskSpace("ozon-incog-fallback", { profileId: "Profile 1" });
}
const page = task.page("p1");

// 清掉 ozon 站点 cookie（只清该 origin）
try {
  await page.cdp("Storage.clearDataForOrigin", { origin: "https://www.ozon.ru", storageTypes: "cookies" });
  await w({ step: "cleared ozon cookies" });
} catch (e) { await w({ clearErr: String(e).slice(0, 100) }); }

await page.goto("https://www.ozon.ru/robots.txt", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(()=>{});
await page.waitForTimeout(500);
await w({ url: await page.url().catch(()=>"?") });

const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
for (let i = 0; i < 3; i++) {
  const t0 = Date.now();
  try {
    const r = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=" + (i + 2)), { headers: { accept: "application/json" }, timeout: 30000 });
    let kind = "json";
    if (r.status !== 200) { try { const j = JSON.parse(r.body); kind = j.incidentId ? "challenge:" + j.incidentId : "err"; } catch { kind = (r.body||"").slice(0,60); } }
    await w({ i, s: r.status, ms: Date.now()-t0, bytes: (r.body||"").length, kind });
  } catch (e) { await w({ i, err: String(e).slice(0, 70), ms: Date.now()-t0 }); }
  await page.waitForTimeout(1500);
}
await w({ done: true });
