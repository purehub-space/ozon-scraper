const fs = await import("node:fs/promises");
const LOG = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/hdr.log";
const w = async (o) => { await fs.appendFile(LOG, JSON.stringify(o) + "\n"); };
await fs.writeFile(LOG, "");
const cookies = JSON.parse(await fs.readFile("/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/ozon-cookies.json", "utf8"));
const task = await taskSpace("ozon-hdr-probe", { profileId: "Profile 1" });
const page = task.page("p1");
for (const c of cookies) await page.cdp("Network.setCookie", { name:c.name, value:c.value, domain:c.domain||".ozon.ru", path:"/", secure:!!c.secure, httpOnly:!!c.httpOnly }).catch(()=>{});
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil:"domcontentloaded", timeout:45000 }).catch(()=>{});
await page.waitForTimeout(500);
const B = "/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
const u = "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=5");
const r = await page.fetch(u, { headers:{accept:"application/json"}, timeout:30000 });
const h = {};
for (const k of ["content-encoding","content-length","cache-control","server-timing","x-cache","age"]) {
  const v = r.headers.get ? r.headers.get(k) : (r.headers[k] || null);
  if (v) h[k] = v;
}
await w({ headers: h, bytesDecoded: (r.body||"").length });

// 并发吞吐：4 / 8 并发各 8 页
const get = async (n) => {
  const t0=Date.now();
  try { const rr = await page.fetch("/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(B + "&page=" + n), { headers:{accept:"application/json"}, timeout:30000 });
    return { n, s:rr.status, ms:Date.now()-t0, bytes:(rr.body||"").length };
  } catch(e){ return { n, err:1, ms:Date.now()-t0 }; }
};
for (const width of [4, 6]) {
  const t0 = Date.now();
  const res = [];
  for (let i=0;i<8;i+=width) res.push(...await Promise.all(Array.from({length:Math.min(width,8-i)},(_,k)=>get(600+i+k))));
  await w({ conc: width, wall: Date.now()-t0, ok: res.filter(x=>x.s===200).length, perPage: +((Date.now()-t0)/8/1000).toFixed(2), avg: Math.round(res.reduce((a,x)=>a+x.ms,0)/res.length) });
}
await w({ done:true });
