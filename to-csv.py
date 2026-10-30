#!/usr/bin/env python3
"""把目录里所有 *.jsonl 转成同名 CSV（扁平化嵌套字段）

用法:
  python3 to-csv.py out_kw
  python3 to-csv.py out_detail
  python3 to-csv.py out_kw out_detail        # 多个目录
"""
import csv, json, os, sys


def flat(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else ""
    if isinstance(v, (list, tuple)):
        return " | ".join(flat(x) for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return " ".join(f"{k}={flat(x)}" for k, x in v.items() if x not in (None, "", [], {}))
    return str(v).replace("\n", " ").strip()


def convert(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    if not rows:
        return None
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    out = path[:-6] + ".csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: flat(r.get(k)) for k in keys})
    return out, len(rows), len(keys)


def main():
    dirs = sys.argv[1:] or ["out"]
    for d in dirs:
        if not os.path.isdir(d):
            print(f"[skip] {d} 不是目录")
            continue
        found = 0
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            r = convert(os.path.join(d, fn))
            if r:
                print(f"{r[0]}: {r[1]} rows × {r[2]} cols")
                found += 1
        if not found:
            print(f"[skip] {d} 里没有 jsonl")


if __name__ == "__main__":
    main()
