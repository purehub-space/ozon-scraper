const fs = await import("node:fs/promises");
const OUT = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/";
const w = async (o) => { await fs.appendFile(OUT + "extra.log", JSON.stringify(o) + "\n"); };
await fs.writeFile(OUT + "extra.log", "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-front-fields/cookies.json", "utf8"));
const task = await taskSpace("ozon-extra-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly, ...(c.expires>0?{expires:c.expires}:{}) }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(800);

const api = (p) => "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(p);
const get = async (p, label) => {
  const t0=Date.now();
  try {
    const r = await page.fetch(api(p), { headers:{accept:"application/json"}, timeout: 25000 });
    await w({ label, s:r.status, ms:Date.now()-t0, len:(r.body||"").length });
    return r.status===200 ? JSON.parse(r.body) : null;
  } catch(e) { await w({ label, err:String(e).slice(0,60) }); return null; }
};

// 1) 评论页
const rev = await get("/product/244245278/reviews/", "reviews");
if (rev) {
  const ws = rev.widgetStates || {};
  const keys = Object.keys(ws);
  await w({ reviewWidgets: keys.slice(0, 20), count: keys.length });
  for (const [k, raw] of Object.entries(ws)) {
    if (/review|comment/i.test(k)) {
      try {
        const j = JSON.parse(raw);
        const s = JSON.stringify(j);
        await w({ widget: k, bytes: s.length, sample: s.slice(0, 700) });
      } catch {}
    }
  }
}
await page.waitForTimeout(2500);

// 2) PDP2 attachments
const d2 = await get("/product/244245278/?layout_container=pdpPage2column&layout_page_index=2", "pdp2");
if (d2) {
  const layout = d2.layout || [];
  const ws = d2.widgetStates || {};
  for (const l of layout) {
    const sid = l.stateId || "";
    if (/attach/i.test(sid) || /attach/i.test(JSON.stringify(l.params||{}))) {
      await w({ layoutItem: { component: l.component, stateId: sid, params: l.params } });
    }
  }
  for (const k of Object.keys(ws)) if (/attach/i.test(k)) await w({ attachWidget: k, body: ws[k].slice(0,300) });
}
await w({ done: true });
