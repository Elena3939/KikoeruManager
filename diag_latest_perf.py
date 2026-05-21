"""拉最新 RaRo 索引 detail.perf，重点看 sub-stage 分布。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "cache.db"
if not DB_PATH.exists():
    DB_PATH = Path(__file__).resolve().parent / "backend" / "data" / "cache.db"

if not DB_PATH.exists():
    print(f"[ERR] 找不到 cache.db，尝试路径：{DB_PATH}")
    sys.exit(1)

print(f"使用数据库：{DB_PATH}\n")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 最新一次 index_completed
cur.execute("""
    SELECT id, created_at, detail, action
    FROM activity_logs
    WHERE category = 'circle_completion'
      AND action = 'index_completed'
    ORDER BY created_at DESC
    LIMIT 1
""")
row = cur.fetchone()
if not row:
    print("没有 index_completed 日志")
    sys.exit(1)

detail = json.loads(row["detail"] or "{}")
perf = detail.get("perf") or {}
stage_ms = perf.get("stage_ms") or {}
counters = perf.get("counters") or {}

print(f"=== 最新索引 #{row['id']} @ {row['created_at']} action={row['action']} ===\n")

print("【全局 stage 耗时】")
overall_keys = [
    "stage_local_owned_sync",
    "stage_dlsite_candidates",
    "stage_external_snapshot",
    "stage_kikoeru_check",
    "stage_persist",
]
total = 0.0
for k in overall_keys:
    ms = stage_ms.get(k, 0)
    total += ms
    print(f"  {k:40s} {ms / 1000:8.2f}s  ({ms / 60000:5.2f} 分)")
print(f"  {'TOTAL':40s} {total / 1000:8.2f}s  ({total / 60000:5.2f} 分)\n")

print("【全部 stage_ms（含 sub-stage）】")
ext_total = stage_ms.get("stage_external_snapshot", 0)
for k in sorted(stage_ms.keys()):
    ms = stage_ms.get(k, 0)
    pct = (ms / ext_total * 100) if ext_total else 0
    pct_str = f", {pct:5.1f}% of external" if "snapshot_wave" in k or "snapshot_prewarm" in k else ""
    print(f"  {k:50s} {ms / 1000:8.2f}s  ({ms / 60000:5.2f} 分{pct_str})")
print()

print("【ASMR.one chain 耗时分布】")
chain_count = counters.get("asmr_chain_total_count", 0)
chain_ms = counters.get("asmr_chain_total_ms", 0)
slow_10 = counters.get("asmr_chain_slow_gt_10s", 0)
slow_30 = counters.get("asmr_chain_slow_gt_30s", 0)
avg = (chain_ms / chain_count) if chain_count else 0
print(f"  总 chain 数:           {chain_count}")
print(f"  累计耗时:             {chain_ms / 1000:.2f}s ({chain_ms / 60000:.2f} 分)")
print(f"  平均单 chain 耗时:    {avg:.0f}ms ({avg / 1000:.2f}s)")
print(f"  慢 chain (>10s):      {slow_10}")
print(f"  慢 chain (>30s):      {slow_30}\n")

print("【所有 counters】")
for k in sorted(counters.keys()):
    print(f"  {k:50s} {counters[k]}")

conn.close()
