const fs = await import("node:fs/promises");
const OUT = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/";
const task = await taskSpace("ozon-net-probe2");
const page = task.page("p1");


// 注入 fetch/XHR 拦截
await page.cdp("Page.addScriptToEvaluateOnNewDocument", { source: `
window.__net = [];
(function(){
  const of = window.fetch;
  window.fetch = async function(input, init){
    const u = (typeof input === 'string') ? input : (input && input.url) || '';
    const t0 = performance.now();
    const r = await of.apply(this, arguments);
    try {
      const ct = r.headers.get('content-type') || '';
      if (/json/.test(ct)) {
        const t = await r.clone().text();
        window.__net.push({ u, s: r.status, len: t.length, ms: Math.round(performance.now()-t0) });
      } else {
        window.__net.push({ u, s: r.status, len: -1, ms: Math.round(performance.now()-t0) });
      }
    } catch(e) { window.__net.push({ u, s: 0, err: String(e).slice(0,40) }); }
    return r;
  };
  const oo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(m, u){ window.__net.push({ xhr: m, u: String(u) }); return oo.apply(this, arguments); };
})();
`});

const URL = "https://www.ozon.ru/category/sumki-na-plecho-zhenskie-17002/?category_was_predicted=true&deny_category_prediction=true&from_global=true&text=%D1%81%D1%83%D0%BC%D0%BA%D0%B0+%D0%B6%D0%B5%D0%BD%D1%81%D0%BA%D0%B0%D1%8F";
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(e=>console.log("goto", String(e).slice(0,80)));
await page.waitForTimeout(5000);
for (let i=0;i<4;i++) { await page.evaluate(()=>window.scrollBy(0, 1800)); await page.waitForTimeout(2500); }

const net = await page.evaluate(() => window.__net || []);
await fs.writeFile(OUT + "net.json", JSON.stringify(net, null, 1));
const api = net.filter(x => /\/api\//.test(x.u || ""));
console.log("total:", net.length, "api:", api.length);
for (const a of api.slice(0, 30)) console.log(JSON.stringify(a).slice(0, 220));
