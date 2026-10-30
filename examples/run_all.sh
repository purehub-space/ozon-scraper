#!/usr/bin/env bash
# 一条链：关键词 → SKU 列表 → 详情 → CSV
# 用法: bash examples/run_all.sh "сквиш" [线程数]
set -euo pipefail
KW="${1:?用法: bash run_all.sh <关键词> [线程数]}"
T="${2:-24}"
OUT="out_${KW//[^a-zA-Z0-9]/_}"

cd "$(dirname "$0")/.."
echo "=== 1/3 抓列表: $KW ==="
python3 ozon_search.py --kw "$KW" --out "$OUT" --pages 1-0 --threads "$T"

echo "=== 2/3 抓详情（前 200 个）==="
head -200 "$OUT/skus.txt" > "$OUT/skus200.txt"
python3 ozon_detail.py --skus "$OUT/skus200.txt" --out "${OUT}_detail" --threads 20

echo "=== 3/3 转 CSV ==="
python3 to-csv.py "${OUT}_detail" 2>/dev/null || \
  python3 - <<PY
import json,csv,os
src="${OUT}_detail/details.jsonl"; dst="${OUT}_detail/details.csv"
rows=[json.loads(l) for l in open(src) if l.strip()]
keys=["sku","title","price","original_price","rating","reviews","seller","breadcrumbs","characteristics_total"]
with open(dst,"w",newline="",encoding="utf-8-sig") as f:
    w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader()
    for r in rows: w.writerow({k:str(r.get(k,"")).replace("\n"," ") for k in keys})
print(dst, len(rows), "rows")
PY

echo
echo "完成:"
echo "  列表  $OUT/skus.txt  ($(wc -l < $OUT/skus.txt) 个 SKU)"
echo "  详情  ${OUT}_detail/details.jsonl"
