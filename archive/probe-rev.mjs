const fs = await import("node:fs/promises");
const OUT = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/";
const w = async (o) => { await fs.appendFile(OUT + "rev.log", JSON.stringify(o) + "\n"); };
await fs.writeFile(OUT + "rev.log", "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-front-fields/cookies.json", "utf8"));
const task = await taskSpace("ozon-rev-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly, ...(c.expires>0?{expires:c.expires}:{}) }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(600);
const api = (p) => "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(p);
for (const [tag, path] of [["p1","/product/244245278/reviews/"], ["p2","/product/244245278/reviews/?page=2"]]) {
  try {
    const r = await page.fetch(api(path), { headers:{accept:"application/json"}, timeout:35000 });
    await fs.writeFile(OUT + `raw-reviews-${tag}.json`, r.body || "");
    const ws = JSON.parse(r.body).widgetStates || {};
    const k = Object.keys(ws).find(x=>x.startsWith("webListReviews"));
    if (k) {
      const j = JSON.parse(ws[k]);
      await w({ tag, status:r.status, len:(r.body||"").length, topKeys:Object.keys(j), reviews: (j.reviews||[]).length, hasNext: !!(j.nextPage||j.pagination) });
      const one = (j.reviews||[])[0];
      if (one) await w({ tag, sampleKeys: Object.keys(one), sample: JSON.stringify(one).slice(0,600) });
    } else {
      await w({ tag, status:r.status, len:(r.body||"").length, widgets: Object.keys(ws).filter(x=>/eview/i.test(x)) });
    }
  } catch(e) { await w({ tag, err: String(e).slice(0,70) }); }
  await page.waitForTimeout(2000);
}
await w({ done:true });
