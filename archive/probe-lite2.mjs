const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/lite2.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-lite-probe2", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);
const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const get = async (label, u) => {
  const t0=Date.now();
  try { const r = await page.fetch(u, { headers:{accept:"application/json"}, timeout:30000 });
    await w({ label, s:r.status, ms:Date.now()-t0, bytes:(r.body||"").length, head:(r.body||"").slice(0,120) });
  } catch(e){ await w({ label, err:String(e).slice(0,50), ms:Date.now()-t0 }); }
  await page.waitForTimeout(800);
};
const post = async (label, u, body) => {
  const t0=Date.now();
  try { const r = await page.fetch(u, { method:"POST", headers:{"content-type":"application/json", accept:"application/json"}, body: JSON.stringify(body), timeout:30000 });
    await w({ label, s:r.status, ms:Date.now()-t0, bytes:(r.body||"").length, head:(r.body||"").slice(0,160) });
  } catch(e){ await w({ label, err:String(e).slice(0,50), ms:Date.now()-t0 }); }
  await page.waitForTimeout(800);
};
await get("baseline_p2", "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=2"));
await get("baseline_p3", "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=3"));
const sid = "tileGridDesktop-3669724-default-1";
await post("widget_post_empty", "/api/composer-api.bx/widget/json/v2?widgetStateId=" + sid, {});
await post("widget_post_page", "/api/composer-api.bx/widget/json/v2?widgetStateId=" + sid, { page: "2" });
await post("widget_post_pi", "/api/composer-api.bx/widget/json/v2?widgetStateId=" + sid, { layout_page_index: "2" });
await w({ done:true });
