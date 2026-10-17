"""按仍然保留的操作事实核对日统计；rollup 是同批事实的展示投影，不重复计数。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import text


def rebuild_daily_stats(db, *, start_date: date, end_date: date, apply: bool = False) -> dict:
    """核对闭区间日期；调用方负责提交。应用时与 Writer 的同日共享锁互斥。

    正常压缩只裁剪 detail、不删除事实行。人工清理脚本删除的记录不再视为保留事实。
    rollup 可同时按 batch/session/task 聚合同一行，不能与 activity_logs 相加。
    """
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ValueError("日期区间必须正序，且不超过 367 天")
    params = {
        "start": datetime.combine(start_date, time.min),
        "end": datetime.combine(end_date + timedelta(days=1), time.min),
        "first_day": start_date.isoformat(),
        "last_day": end_date.isoformat(),
    }
    if apply:
        # 在 READ COMMITTED 下，等同日 Writer 提交后再读取事实，排队的新 Writer 随后增量。
        isolation = str(db.execute(text("SHOW transaction_isolation")).scalar()).lower()
        if isolation != "read committed":
            raise ValueError("日统计重建要求 READ COMMITTED 事务")
        day = start_date
        while day <= end_date:
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                "key": f"activity-log-daily:{day.isoformat()}",
            })
            day += timedelta(days=1)
    rows = db.execute(text("""
        SELECT to_char(created_at, 'YYYY-MM-DD') AS date,
               left(coalesce(category, ''), 40) AS category,
               left(coalesce(status, ''), 20) AS status, count(*) AS count
          FROM activity_logs
         WHERE created_at >= :start AND created_at < :end
         GROUP BY 1, 2, 3
    """), params).mappings().all()
    expected = {(row["date"], row["category"], row["status"]): int(row["count"]) for row in rows}
    actual = {
        (row["date"], row["category"], row["status"]): int(row["count"])
        for row in db.execute(text("""
            SELECT date, category, status, count FROM activity_log_daily_stats
             WHERE date >= :first_day AND date <= :last_day
        """), params).mappings()
    }
    differences = [
        {"date": key[0], "category": key[1], "status": key[2],
         "before": actual.get(key, 0), "expected": expected.get(key, 0)}
        for key in sorted(actual.keys() | expected.keys())
        if actual.get(key) != expected.get(key)
    ]
    if apply and differences:
        db.execute(text("DELETE FROM activity_log_daily_stats WHERE date >= :first_day AND date <= :last_day"), params)
        if rows:
            db.execute(text("""
                INSERT INTO activity_log_daily_stats(date, category, status, count, updated_at)
                VALUES (:date, :category, :status, :count, CURRENT_TIMESTAMP)
            """), [dict(row) for row in rows])
    return {"applied": bool(apply), "source_rows": sum(expected.values()),
            "stored_count": sum(actual.values()), "mismatched_buckets": len(differences),
            "differences": differences, "source": "activity_logs", "rollup_added": False}
