#!/usr/bin/env bash
# 一条链：cookie 池 → 关键词列表 → 详情 → CSV
#
# 用法:
#   bash examples/run_all.sh "сквиш"                     # 池 4，详情 200，列表全量
#   bash examples/run_all.sh "сквиш" 4 500               # 池 4，详情 500
#   bash examples/run_all.sh "сквиш" 4 200 1-300         # 只抓前 300 页列表
#
set -euo pipefail

KW="${1:?用法: bash run_all.sh <关键词> [池大小=4] [详情数量=200] [页码范围=1-0]}"
POOL="${2:-4}"
DETAIL_N="${3:-200}"
PAGES="${4:-1-0}"
# 目录名：保留关键词里的 ASCII 字符 + 短 hash（西里尔/中文会被替换掉）
SLUG=$(python3 - "$KW" <<'PYSLUG'
import hashlib, re, sys
k = sys.argv[1]
a = re.sub(r"[^a-zA-Z0-9]+", "", k)[:16]
print((a + "_" if a else "") + hashlib.md5(k.encode()).hexdigest()[:6])
PYSLUG
)
OUT="out_${SLUG}"

cd "$(dirname "$0")/.."

t_all=$SECONDS

echo "════════════════════════════════════════════════════"
echo " 关键词: $KW"
echo " 池大小: $POOL   详情: $DETAIL_N 个   列表: $PAGES 页"
echo "════════════════════════════════════════════════════"

echo
echo "▶ 0/4  准备 cookie 池（$POOL 个 headless 会话，完全无窗口）"
if ! python3 prepare_pool.py --list 2>/dev/null | grep -q "可用 $POOL"; then
    python3 prepare_pool.py --n "$POOL" 2>&1 | tail -n 4
else
    echo "  池已就绪，跳过预热"
fi

echo
echo "▶ 1/4  抓关键词列表"
python3 ozon_search.py --kw "$KW" --out "$OUT" --pages "$PAGES" --pool "$POOL" 2>&1 | tail -n 6

TOTAL=$(wc -l < "$OUT/skus.txt" | tr -d ' ')
echo
echo "▶ 2/4  抓详情（取前 $DETAIL_N / $TOTAL 个）"
if [ "$TOTAL" -gt 0 ]; then
    head -n "$DETAIL_N" "$OUT/skus.txt" > "$OUT/skus_top${DETAIL_N}.txt"
    python3 ozon_detail.py --skus "$OUT/skus_top${DETAIL_N}.txt" --out "${OUT}_detail" --pool "$POOL" 2>&1 | tail -n 4
else
    echo "  列表为空，跳过"
fi

echo
echo "▶ 3/4  转 CSV"
python3 to-csv.py "$OUT" "${OUT}_detail"

echo
echo "▶ 4/4  汇总（价格分布）"
python3 - "$OUT" <<'PY'
import json, sys, os
out = sys.argv[1]
rows = [json.loads(l) for l in open(os.path.join(out, "products.jsonl"), encoding="utf-8") if l.strip()]
prices = sorted(r["price"] for r in rows if r.get("price"))
if prices:
    q = lambda p: prices[int(len(prices) * p)]
    print(f"  SKU {len(rows)} 个，有价 {len(prices)} 个")
    print(f"  价格  P10 {q(.1)} / 中位 {q(.5)} / P90 {q(.9)} ₽")
    print(f"  区间  {prices[0]} ~ {prices[-1]} ₽")
adv = sum(1 for r in rows if r.get("is_advert"))
print(f"  广告位 {adv}/{len(rows)}" if rows else "")
stars = [r for r in rows if (r.get("reviews") or 0) > 100]
print(f"  评价>100 的款 {len(stars)} 个")
PY

echo
echo "════════════════════════════════════════════════════"
echo " 完成，用时 $((SECONDS - t_all)) 秒"
echo " 列表 $OUT/skus.txt          （$TOTAL 个 SKU）"
echo " 列表 $OUT/products.csv"
echo " 详情 ${OUT}_detail/details.jsonl"
echo "════════════════════════════════════════════════════"
