"""临时脚本：调研操作日志表的体积分布。用完可删。"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(r"d:/Tool/ASMR/KikoeruTool_Elena_StartAll/data/cache.db")
if not DB_PATH.exists():
    print(f"db not found: {DB_PATH}")
    sys.exit(0)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print(f"== {DB_PATH} ({DB_PATH.stat().st_size/1024/1024:.2f} MB) ==")

cur.execute("SELECT COUNT(*) FROM activity_logs")
total = cur.fetchone()[0]
print(f"activity_logs total rows: {total}")

cur.execute("SELECT MIN(created_at), MAX(created_at) FROM activity_logs")
print("date range:", cur.fetchone())

cur.execute("SELECT category, COUNT(*) FROM activity_logs GROUP BY category ORDER BY COUNT(*) DESC")
print("\nby category:")
for c in cur.fetchall():
    print(f"  {c[0]:<22} {c[1]:>8}")

cur.execute("SELECT status, COUNT(*) FROM activity_logs GROUP BY status ORDER BY COUNT(*) DESC")
print("\nby status:")
for c in cur.fetchall():
    print(f"  {c[0]:<22} {c[1]:>8}")

cur.execute(
    "SELECT category, AVG(LENGTH(detail)), MAX(LENGTH(detail)), SUM(LENGTH(detail)) FROM activity_logs GROUP BY category ORDER BY SUM(LENGTH(detail)) DESC"
)
print("\ndetail JSON size by category:")
for cat, avg, mx, tot in cur.fetchall():
    print(f"  {cat:<22} avg={int(avg or 0):>8}  max={int(mx or 0):>10}  total={int(tot or 0):>12}")

cur.execute(
    "SELECT category, status, COUNT(*) FROM activity_logs WHERE created_at < datetime('now','-30 days') GROUP BY category, status ORDER BY COUNT(*) DESC"
)
print("\nrows older than 30 days (top 30):")
for cat, st, cnt in cur.fetchall()[:30]:
    print(f"  {cat:<22} {st:<18} {cnt:>8}")

cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at < datetime('now','-30 days')")
print(f"\ntotal older than 30 days: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM activity_logs WHERE created_at < datetime('now','-90 days')")
print(f"total older than 90 days: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM activity_log_daily_stats")
print(f"\ndaily_stats rows: {cur.fetchone()[0]}")

cur.execute("SELECT name, type FROM sqlite_master WHERE name LIKE '%fts%' OR name LIKE '%activity%' ORDER BY name")
print("\nactivity-related sqlite_master entries:")
for nm, tp in cur.fetchall():
    print(f"  {nm:<40} {tp}")

# 字段大小占比
cur.execute("SELECT SUM(LENGTH(detail)), SUM(LENGTH(summary)), SUM(LENGTH(source_path)) FROM activity_logs")
sd, ss, sp = cur.fetchone()
print(f"\ntotal payload bytes: detail={sd or 0:,} summary={ss or 0:,} source_path={sp or 0:,}")

conn.close()
