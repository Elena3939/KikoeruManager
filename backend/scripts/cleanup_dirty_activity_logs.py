from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def is_temp_like_path(value: str) -> bool:
    normalized = (value or "").replace("/", "\\").lower()
    if not normalized:
        return False
    markers = [
        "\\_conflicts\\",
        "\\temp\\",
        "\\tmp\\",
        "\\待处理\\",
        "\\待处理1\\",
    ]
    if normalized.endswith("\\_conflicts") or normalized.endswith("\\待处理"):
        return True
    return any(marker in normalized for marker in markers)


def fetch_counts(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.cursor()
    pending_execute_logs = cur.execute(
        "select count(*) from activity_logs where category='subtitle_import' and action='pending_execute'"
    ).fetchone()[0]
    duplicate_success_logs = cur.execute(
        """
        select count(*) from activity_logs
        where category in ('auto_import','process_existing')
          and status='success'
          and summary like '%重复作品%'
        """
    ).fetchone()[0]
    temp_conflicts = 0
    for (existing_path,) in cur.execute(
        "select ifnull(existing_path,'') from conflict_works where conflict_type like 'DUPLICATE%' or conflict_type like 'LINKED_WORK%'"
    ).fetchall():
        if is_temp_like_path(existing_path):
            temp_conflicts += 1
    return {
        "pending_execute_logs": int(pending_execute_logs or 0),
        "duplicate_success_logs": int(duplicate_success_logs or 0),
        "temp_conflicts": int(temp_conflicts or 0),
    }


def apply_cleanup(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.cursor()

    pending_ids = [
        row[0]
        for row in cur.execute(
            "select id from activity_logs where category='subtitle_import' and action='pending_execute'"
        ).fetchall()
    ]
    for log_id in pending_ids:
        cur.execute("delete from activity_logs where id=?", (log_id,))

    duplicate_ids = [
        row[0]
        for row in cur.execute(
            """
            select id from activity_logs
            where category in ('auto_import','process_existing')
              and status='success'
              and summary like '%重复作品%'
            """
        ).fetchall()
    ]
    for log_id in duplicate_ids:
        cur.execute(
            """
            update activity_logs
               set status='waiting'
             where id=?
            """,
            (log_id,),
        )

    deleted_conflict_ids: list[str] = []
    for conflict_id, existing_path in cur.execute(
        """
        select id, ifnull(existing_path,'')
          from conflict_works
         where conflict_type like 'DUPLICATE%'
            or conflict_type like 'LINKED_WORK%'
        """
    ).fetchall():
        if is_temp_like_path(existing_path):
            deleted_conflict_ids.append(conflict_id)
    for conflict_id in deleted_conflict_ids:
        cur.execute("delete from conflict_works where id=?", (conflict_id,))

    conn.commit()
    return {
        "deleted_pending_execute_logs": len(pending_ids),
        "updated_duplicate_success_logs": len(duplicate_ids),
        "deleted_temp_conflicts": len(deleted_conflict_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清理历史脏操作记录/问题作品")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[1] / "data" / "cache.db"),
        help="SQLite 数据库路径",
    )
    parser.add_argument("--apply", action="store_true", help="执行写入清理")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        before = fetch_counts(conn)
        print("DB =", db_path)
        print("BEFORE =", before)
        if not args.apply:
            return 0
        changed = apply_cleanup(conn)
        after = fetch_counts(conn)
        print("CHANGED =", changed)
        print("AFTER =", after)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
