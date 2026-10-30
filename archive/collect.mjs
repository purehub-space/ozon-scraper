// Ozon 前台采集器 v2 — 全店翻页 + 评论 + 证书 + 增量去重 + 多实例(cookie 注入)
//
// 用法：
//   OZ_TARGETS=/abs/targets.json OZ_OUT=/abs/out OZ_SHARD=0 OZ_SHARDS=2 \
//     ego-browser nodejs < collect.mjs
//
// targets.json:
// {
//   "sellers": [{ "id": "78486", "maxPages": 0 }],
//   "skus": ["244245278"],
//   "opts": { "pdp2": true, "attachments": true, "reviews": 2, "delayMs": 1200,
//             "profile": "Profile 1", "cookieFile": "/abs/cookies.json", "maxPages": 0 }
// }
//
// 输出（JSONL 追加，增量去重）：
//   stores.jsonl / products.jsonl / sku_details.jsonl / reviews.jsonl / attachments.jsonl
//   state.json  run.log

const fs = await import("node:fs/promises");

// ego nodejs 不继承 env，配置全部走 job 文件；多实例时各生成一份 job 文件
const JOB_PATH = "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out/targets.json";
const cfg = JSON.parse(await fs.readFile(JOB_PATH, "utf8"));
const OUT = cfg.out || "/Users/a1234/Workspace/haiou/scratch/2026-10-27-ozon-collector/out";
const SHARD = cfg.shard || 0;
const SHARDS = cfg.shards || 1;
await fs.mkdir(OUT, { recursive: true });
const O = Object.assign({
  delayMs: 1200, pdp2: true, attachments: true, reviews: 0, maxPages: 0,
  profile: null, cookieFile: null, maxRetry: 2, cooldownMs: 15000,
}, cfg.opts || {});

const log = async (o) => {
  const line = JSON.stringify({ t: new Date().toISOString(), shard: SHARD, ...o });
  console.log(line);
  await fs.appendFile(OUT + "/run.log", line + "\n");
};

// ---------- 增量索引 ----------
const readJsonl = async (f) => {
  try {
    const t = await fs.readFile(OUT + "/" + f, "utf8");
    return t.split("\n").filter(Boolean).flatMap((l) => { try { return [JSON.parse(l)]; } catch { return []; } });
  } catch { return []; }
};
const day = new Date().toISOString().slice(0, 10);
const seen = {
  sellers: new Set(), products: new Set(), skus: new Set(), reviews: new Set(), attachments: new Set(),
};
for (const r of await readJsonl("stores.jsonl")) if (r.page === undefined) seen.sellers.add(String(r.seller_id));
for (const r of await readJsonl("products.jsonl")) seen.products.add(`${r.seller_id}:${r.sku}:${day}`);
for (const r of await readJsonl("sku_details.jsonl")) seen.skus.add(`${r.sku}:${day}`);
for (const r of await readJsonl("reviews.jsonl")) seen.reviews.add(String(r.uuid));
for (const r of await readJsonl("attachments.jsonl")) seen.attachments.add(String(r.sku));
await log({ ev: "index", sellers: seen.sellers.size, products: seen.products.size, skus: seen.skus.size, reviews: seen.reviews.size });

const append = (f, o) => fs.appendFile(OUT + "/" + f, JSON.stringify(o) + "\n");

const stateFile = OUT + "/state.json";
let state = { pages: {}, doneSellers: [], doneSkus: {}, sellerComplete: {}, startedAt: new Date().toISOString() };
try { state = Object.assign(state, JSON.parse(await fs.readFile(stateFile, "utf8"))); } catch {}
const saveState = () => fs.writeFile(stateFile, JSON.stringify(state, null, 1));

// ---------- 浏览器上下文 ----------
const SPACE = O.profile ? "ozon-collector-" + O.profile.replace(/\s+/g, "") : "ozon-collector";
let task;
try { task = O.profile ? await taskSpace(SPACE, { profileId: O.profile }) : await taskSpace(SPACE); }
catch { task = await taskSpace(SPACE); }   // 空间已存在则复用（profile 已绑定）
const page = task.page("p1");

if (O.cookieFile) {
  const cookies = JSON.parse(await fs.readFile(O.cookieFile, "utf8"));
  let ok = 0;
  for (const c of cookies) {
    try {
      await page.cdp("Network.setCookie", {
        name: c.name, value: c.value, domain: c.domain || ".ozon.ru", path: "/",
        secure: !!c.secure, httpOnly: !!c.httpOnly,
        ...(c.expires && c.expires > 0 ? { expires: c.expires } : {}),
      });
      ok++;
    } catch {}
  }
  await log({ ev: "cookie-inject", n: ok, profile: O.profile });
}

// 用 robots.txt 建同源上下文：有 cookie、不触发定位权限弹窗、几乎无开销
await page.goto("https://www.ozon.ru/robots.txt", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
await page.waitForTimeout(500);

const api = (p) => "/api/entrypoint-api.bx/page/json/v2?url=" + encodeURIComponent(p);

let reqCount = 0, failStreak = 0;
const pull = async (path, label) => {
  for (let attempt = 0; attempt <= O.maxRetry; attempt++) {
    const t0 = Date.now();
    try {
      const r = await page.fetch(api(path), { headers: { accept: "application/json" }, timeout: 40000 });
      reqCount++;
      if (r.status === 200 && r.body && r.body.length > 60) {
        failStreak = 0;
        await log({ ev: "ok", label, ms: Date.now() - t0, bytes: r.body.length, n: reqCount });
        try { return { json: JSON.parse(r.body), raw: r.body }; } catch { return null; }
      }
      await log({ ev: "bad-status", label, status: r.status });
    } catch (e) {
      reqCount++;
      await log({ ev: "fetch-error", label, attempt, err: String(e).slice(0, 80) });
    }
    failStreak++;
    if (failStreak >= 2) {
      await log({ ev: "cooldown", ms: O.cooldownMs });
      await page.waitForTimeout(O.cooldownMs);
      await page.goto("https://www.ozon.ru/robots.txt", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
      await page.waitForTimeout(600);
      failStreak = 0;
    } else await page.waitForTimeout(2500);
  }
  return null;
};
const pause = () => page.waitForTimeout(O.delayMs);

// ---------- 解析工具 ----------
const num = (s) => {
  if (s == null) return null;
  const c = String(s).replace(/[\s\u00a0\u202f]/g, "").replace(/[^\d.,-]/g, "").replace(/,/g, ".");
  if (!c) return null;
  const n = parseFloat(c);
  return Number.isNaN(n) ? null : n;
};
const findWidget = (ws, prefix) => {
  for (const [k, raw] of Object.entries(ws || {})) if (k.startsWith(prefix)) { try { return JSON.parse(raw); } catch { return null; } }
  return null;
};
const deepFind = (o, test, out = []) => {
  if (!o) return out;
  if (Array.isArray(o)) { for (const x of o) deepFind(x, test, out); return out; }
  if (typeof o === "object") { if (test(o)) out.push(o); for (const v of Object.values(o)) deepFind(v, test, out); }
  return out;
};

const parseShopInfo = (ws) => {
  const out = { cells: {}, legal: null, address: null, ogrn: null };
  for (const [k, raw] of Object.entries(ws || {})) {
    let w; try { w = JSON.parse(raw); } catch { continue; }
    if (k.startsWith("cellList")) {
      for (const c of w.cells || []) {
        const cell = c.dsCell || {}, cb = cell.centerBlock || {};
        const title = cb.title && cb.title.text;
        const val = (cell.rightBlock && cell.rightBlock.badge && cell.rightBlock.badge.text) || (cb.subtitle && cb.subtitle.text);
        if (title) out.cells[title] = val || true;
      }
    }
    if (k.startsWith("textBlock")) {
      for (const b of w.body || []) {
        const t = b.textAtom && b.textAtom.text;
        if (!t) continue;
        if (/操作模式/.test(t)) out.mode = t;
        else if (/^(ИП|ООО|АО|ЗАО|ПАО)\s/.test(t)) {
          const parts = t.split("<br>");
          out.legal = parts[0].trim();
          out.address = parts[1] && /(Россия|г\.|обл\.|ул\.|д\.|край|респ)/.test(parts[1]) ? parts[1].trim() : null;
          const digits = (parts[2] || parts[1] || "").replace(/\D/g, "");
          if (digits.length === 13 || digits.length === 15) out.ogrn = digits;
        }
      }
    }
  }
  return out;
};

const parseTile = (it, sellerId) => {
  const o = { seller_id: sellerId, sku: it.sku || it.id, collected_at: new Date().toISOString() };
  o.link = it.action && it.action.link ? it.action.link.split("?")[0] : null;
  const imgs = (it.tileImage && it.tileImage.items) || [];
  o.image = imgs[0] && imgs[0].image && imgs[0].image.link;
  for (const st of it.mainState || []) {
    if (st.type === "priceV2") {
      const pr = st.priceV2.price || [];
      o.price = num(pr[0] && pr[0].text);
      o.original_price = num(pr[1] && pr[1].text);
      o.discount_pct = num(st.priceV2.discount);
    }
    if (st.type === "textDS") {
      const t = st.textDS.text || "";
      const id = st.id || (st.textDS.testInfo && st.textDS.testInfo.automatizationId) || "";
      if (id === "name") o.title = t.trim();
      else if (/仅剩/.test(t)) o.stock_hint = t.trim();
    }
    if (st.type === "labelListV2") {
      const texts = (st.labelListV2.items || []).map((x) => x.text && x.text.text).filter(Boolean);
      if (texts.length) { o.rating = num(texts[0]); o.reviews = num(texts[1]); }
    }
  }
  o.is_advert = !!(it.trackingInfo && it.trackingInfo.click && it.trackingInfo.click.custom && it.trackingInfo.click.custom.advertLite);
  return o;
};

const parsePdp1 = (ws) => {
  const o = { collected_at: new Date().toISOString() };
  const headW = findWidget(ws, "webProductHeading");
  o.title = headW ? (headW.title || (headW.text) || null) : null;
  const skuW = findWidget(ws, "webDetailSKU"); o.sku = skuW && skuW.copyText;
  const price = findWidget(ws, "webPrice");
  if (price) { o.price = num(price.price); o.card_price = num(price.cardPrice); o.original_price = num(price.originalPrice); o.available = price.isAvailable; }
  const rev = findWidget(ws, "webReviewProductScore");
  if (rev) { o.rating = rev.totalScore; o.reviews = rev.reviewsCount; o.reviews_url = rev.url; }
  const sel = findWidget(ws, "webCurrentSeller");
  if (sel) {
    const cell = sel.sellerCell || {}, cb = cell.centerBlock || {};
    const raw = JSON.stringify(sel);
    const idm = raw.match(/"sellerId":\s*"?(\d{3,12})"?/);
    o.seller = {
      id: idm ? idm[1] : null,
      name: cb.title && cb.title.text,
      logo: cell.leftBlock && cell.leftBlock.icon && cell.leftBlock.icon.backgroundImage,
    };
  }
  const gal = findWidget(ws, "webGallery");
  if (gal) { o.images = (gal.images || []).map((x) => x.src); o.videos = (gal.videos || []).map((v) => v.url || v.link).filter(Boolean); }
  const chars = findWidget(ws, "webShortCharacteristics");
  if (chars) o.short_characteristics = (chars.characteristics || []).map((c) => ({
    id: c.id,
    name: ((c.title && c.title.textRs) || []).map((x) => x.content).join(""),
    value: ((c.values || [])[0] || {}).text || null,
    link: ((c.values || [])[0] || {}).href || null,
  }));
  const asp = findWidget(ws, "webAspects");
  if (asp) o.variants = (asp.aspects || []).map((a) => ({
    aspect: a.aspectName, key: a.aspectKey,
    variants: (a.variants || []).map((v) => ({ sku: v.sku, price: v.price, avail: v.availability, colors: v.data && v.data.colors, text: v.data && v.data.searchableText })),
  }));
  const bs = findWidget(ws, "webBestSeller");
  if (bs) o.other_sellers = { count: num(bs.count), min_price_text: ((bs.textRs || []).map((x) => x.content).filter(Boolean).join(" ")) };
  const ml = findWidget(ws, "webMarketingLabels");
  if (ml) o.labels = (ml.labels || []).map((l) => l.badge && l.badge.text).filter(Boolean);
  const bc = findWidget(ws, "breadCrumbs");
  if (bc) o.breadcrumbs = (bc.breadcrumbs || []).map((x) => x.text.trim());
  return o;
};

const parsePdp2 = (ws) => {
  const o = {};
  const d = findWidget(ws, "webDescription");
  if (d) { o.description_html = d.richAnnotation; o.description_text = (d.richAnnotation || "").replace(/<br\s*\/?>/g, "\n").replace(/<[^>]+>/g, ""); }
  const c = findWidget(ws, "webCharacteristics");
  if (c) {
    o.characteristics_total = c.totalCount;
    o.characteristics = (c.characteristics || []).flatMap((g) => g.short || []).map((x) => ({
      key: x.key, name: x.name, values: (x.values || []).map((v) => v.text).filter(Boolean),
    }));
  }
  const h = findWidget(ws, "webHashtags");
  if (h) o.hashtags = (h.badges || []).map((b) => b.text);
  return o;
};

const parseReviews = (ws) => {
  const w = findWidget(ws, "webListReviews");
  if (!w) return null;
  const score = findWidget(ws, "webReviewProductScore");
  const paging = w.paging || {};
  const rows = (w.reviews || []).map((r) => ({
    uuid: r.uuid,
    sku: String(r.itemId || w.itemId || ""),
    rating: num(r.content && r.content.score !== undefined ? r.content.score : r.score),
    published_at: r.publishedAt ? new Date(r.publishedAt * 1000).toISOString() : null,
    author: r.author ? ((r.author.firstName || "") + " " + (r.author.lastName || "")).trim() || null : null,
    is_anonymous: !!r.isAnonymous,
    is_purchased: !!r.isItemPurchased,
    text: r.content && (r.content.comment || "") || null,
    positive: r.content && r.content.positive || null,
    negative: r.content && r.content.negative || null,
    photos: ((r.content && r.content.photos) || []).map((p) => p.url),
    videos: ((r.content && r.content.videos) || []).map((v) => v.url).filter(Boolean),
    useful: r.usefulness && r.usefulness.useful,
    unuseful: r.usefulness && r.usefulness.unuseful,
    variants: (r.variants || r.productVariants || []).map ? undefined : undefined,
  }));
  return {
    rows,
    total: paging.total || null,
    per_page: paging.perPage || null,
    page: paging.page || 1,
    next_params: (paging.links || []).find((l) => Number(l.text) === (paging.page || 1) + 1)?.urlParams || null,
    overall: score ? { total: score.totalScore, count: score.reviewsCount, dist: (score.score || []).map((s) => ({ label: s.title, n: s.value })) } : null,
  };
};

// ---------- 主流程：店铺 ----------
const sellers = (cfg.sellers || []).filter((s, i) => i % SHARDS === SHARD);

for (const s of sellers) {
  const id = String(s.id);
  if (state.sellerComplete && state.sellerComplete[id]) { await log({ ev: "skip-seller", id }); continue; }

  const info = await pull(`/modal/shop-in-shop-info?seller_id=${id}`, `shopinfo:${id}`);
  if (info) {
    const parsed = parseShopInfo(info.json.widgetStates);
    await append("stores.jsonl", { seller_id: id, collected_at: new Date().toISOString(), ...parsed });
    await log({ ev: "store", id, legal: parsed.legal, ogrn: parsed.ogrn, address: parsed.address, orders: parsed.cells["订单"] });
  }
  await pause();

  const maxPages = s.maxPages !== undefined ? s.maxPages : O.maxPages;
  const resumeFrom = (state.pages[id] && state.pages[id].lastPage ? state.pages[id].lastPage : 0) + 1;
  let pageNo = resumeFrom, freshTotal = 0;
  await log({ ev: "seller-resume", id, from: pageNo });
  for (;;) {
    if (maxPages > 0 && pageNo > maxPages) break;
    const path = pageNo === 1 ? `/seller/${id}/` : `/seller/${id}/?page=${pageNo}`;
    const r = await pull(path, `seller:${id}:p${pageNo}`);
    if (!r) break;
    const ws = r.json.widgetStates || {};
    const grid = findWidget(ws, "tileGridDesktop");
    const items = (grid && grid.items) || [];
    if (!items.length) { await log({ ev: "seller-page-empty", id, page: pageNo }); break; }

    let fresh = 0;
    for (const it of items) {
      const row = parseTile(it, id);
      const key = `${id}:${row.sku}:${day}`;
      if (seen.products.has(key)) continue;
      seen.products.add(key);
      await append("products.jsonl", row);
      fresh++; freshTotal++;
    }
    if (pageNo === 1) {
      const st = findWidget(ws, "sellerTransparency");
      if (st) await append("stores.jsonl", {
        seller_id: id, collected_at: new Date().toISOString(),
        page: {
          name: st.title && st.title.text,
          logo: st.logoImage && st.logoImage.backgroundImage,
          badges: (st.badges || []).map((b) => b.text).filter(Boolean),
        },
      });
    }
    state.pages[id] = { lastPage: pageNo, lastN: items.length, updatedAt: new Date().toISOString() };
    await saveState();
    await log({ ev: "seller-page", id, page: pageNo, n: items.length, fresh, freshTotal });
    if (items.length === 0) break;
    pageNo++;
    await pause();
  }
  state.sellerComplete = state.sellerComplete || {};
  state.sellerComplete[id] = new Date().toISOString();
  state.doneSellers.push(id);
  await saveState();
}

// ---------- 主流程：SKU ----------
const skus = (cfg.skus || []).filter((x, i) => i % SHARDS === SHARD);

for (const sku of skus) {
  const key = String(sku);
  if (seen.skus.has(`${key}:${day}`)) { await log({ ev: "skip-sku", sku: key }); continue; }

  const d1 = await pull(`/product/${key}/`, `pdp1:${key}`);
  if (!d1) { await log({ ev: "pdp1-fail", sku: key }); continue; }
  const detail = { sku: key, ...parsePdp1(d1.json.widgetStates) };
  await pause();

  let pdp2Json = null;
  if (O.pdp2) {
    const d2 = await pull(`/product/${key}/?layout_container=pdpPage2column&layout_page_index=2`, `pdp2:${key}`);
    if (d2) { pdp2Json = d2.json; Object.assign(detail, parsePdp2(d2.json.widgetStates)); }
    await pause();
  }

  // 证书：从 layout 找 webAttachments 的 asyncData → POST composer-api
  if (O.attachments && !seen.attachments.has(key) && pdp2Json) {
    const hit = deepFind(pdp2Json.layout, (o) => o.component === "webAttachments" && o.asyncData)[0];
    if (hit) {
      try {
        const url = "/api/composer-api.bx/widget/json/v2?widgetStateId=" + encodeURIComponent(hit.stateId);
        const r = await page.fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ asyncData: hit.asyncData }),
          timeout: 30000,
        });
        reqCount++;
        if (r.status === 200) {
          const st = (JSON.parse(r.body).state) || {};
          const raw = st.attachments || [];
          const files = [];
          let lastTitle = null;
          for (const a of raw) {
            if (a.title) lastTitle = a.title;
            if (a.fileUrl) files.push({ sku: key, title: lastTitle, file_url: a.fileUrl, size: a.size || null, collected_at: new Date().toISOString() });
          }
          for (const f of files) await append("attachments.jsonl", f);
          seen.attachments.add(key);
          await log({ ev: "attachments", sku: key, n: files.length, title: st.params && st.params.title });
        } else await log({ ev: "attachments-bad", sku: key, status: r.status });
      } catch (e) { await log({ ev: "attachments-err", sku: key, err: String(e).slice(0, 70) }); }
      await pause();
    }
  }

  // 评论
  const revPages = O.reviews | 0;
  if (revPages > 0) {
    let params = "";
    let got = 0;
    for (let p = 1; p <= revPages; p++) {
      const path = `/product/${key}/reviews/` + (p === 1 ? "" : params || `?page=${p}`);
      const r = await pull(path, `reviews:${key}:p${p}`);
      if (!r) break;
      const parsed = parseReviews(r.json.widgetStates);
      if (!parsed) break;
      for (const row of parsed.rows) {
        if (seen.reviews.has(String(row.uuid))) continue;
        seen.reviews.add(String(row.uuid));
        await append("reviews.jsonl", { ...row, collected_at: new Date().toISOString() });
        got++;
      }
      detail.review_total = parsed.total;
      detail.overall_score = parsed.overall;
      await log({ ev: "reviews-page", sku: key, page: p, rows: parsed.rows.length, new: got, total: parsed.total });
      if (!parsed.next_params) break;
      params = parsed.next_params;
      await pause();
    }
  }

  await append("sku_details.jsonl", detail);
  seen.skus.add(`${key}:${day}`);
  state.doneSkus[key] = new Date().toISOString();
  await saveState();
}

await log({ ev: "done", reqCount, sellers: state.doneSellers.length, skus: Object.keys(state.doneSkus).length });
