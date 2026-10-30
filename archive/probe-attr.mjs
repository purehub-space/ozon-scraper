const fs = await import("node:fs/promises");
const OUT = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/";
const w = async (o) => { await fs.appendFile(OUT + "attr.log", JSON.stringify(o) + "\n"); };
await fs.writeFile(OUT + "attr.log", "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-front-fields/cookies.json", "utf8"));
const task = await taskSpace("ozon-attr-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly, ...(c.expires>0?{expires:c.expires}:{}) }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);

// reviews
const rp = "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent("/product/218490069/reviews/");
try {
  const r = await page.fetch(rp, { headers:{accept:"application/json"}, timeout:30000 });
  await fs.writeFile(OUT + "raw-reviews.json", r.body || "");
  await w({ reviews: r.status, len:(r.body||"").length });
} catch(e) { await w({ reviewsErr: String(e).slice(0,60) }); }

// attachments
const dp = "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent("/product/218490069/?layout_container=pdpPage2column&layout_page_index=2");
try {
  const r = await page.fetch(dp, { headers:{accept:"application/json"}, timeout:30000 });
  const j = JSON.parse(r.body);
  let found = null;
  const walk = (o) => { if (!o || found) return; if (Array.isArray(o)) return o.forEach(walk); if (typeof o === "object") { if (o.component === "webAttachments") found = o; else Object.values(o).forEach(walk); } };
  walk(j.layout);
  await w({ layoutAttach: found ? { stateId: found.stateId, hasAsync: !!found.asyncData, params: found.params } : null });
  if (found && found.asyncData) {
    const url = "/api/composer-api.bx/widget/json/v2?widgetStateId=" + encodeURIComponent(found.stateId);
    const pr = await page.fetch(url, { method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({ asyncData: found.asyncData }), timeout: 30000 });
    await fs.writeFile(OUT + "raw-attachments.json", pr.body || "");
    await w({ attachPost: pr.status, len:(pr.body||"").length, head:(pr.body||"").slice(0,300) });
  }
} catch(e) { await w({ attachErr: String(e).slice(0,80) }); }
await w({ done: true });
