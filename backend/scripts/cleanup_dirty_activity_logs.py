from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
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
    stale_processing_conflicts = cur.execute(
        """
        select count(*)
          from conflict_works c
          left join tasks t on t.id = c.task_id
         where c.status='PROCESSING'
           and (
                ifnull(c.task_id, '') = ''
                or t.id is null
                or lower(ifnull(t.status, '')) not in (
                    'pending',
                    'processing',
                    'paused',
                    'waiting_manual',
                    'waiting_retry'
                )
           )
        """
    ).fetchone()[0]
    miscategorized_upload_logs = cur.execute(
        """
        select count(*)
          from activity_logs l
          join tasks t on t.id = l.task_id
         where l.category='asmr_sync'
           and lower(ifnull(t.type, ''))='local_library_upload'
        """
    ).fetchone()[0]
    heuristic_upload_logs = cur.execute(
        """
        select count(*)
          from activity_logs
         where category='asmr_sync'
           and action in ('task_finished', 'task_finished_incomplete')
           and ifnull(task_id, '') != ''
           and (
                summary like '上传完成%'
                or source_path like 'E:\\0\\临时\\asmr\\asmr%'
                or json_extract(detail, '$.output_path') like '/AMSR/%'
           )
        """
    ).fetchone()[0]
    return {
        "pending_execute_logs": int(pending_execute_logs or 0),
        "duplicate_success_logs": int(duplicate_success_logs or 0),
        "temp_conflicts": int(temp_conflicts or 0),
        "stale_processing_conflicts": int(stale_processing_conflicts or 0),
        "miscategorized_upload_logs": int(miscategorized_upload_logs or 0),
        "heuristic_upload_logs": int(heuristic_upload_logs or 0),
    }


def _format_bytes(size: int) -> str:
    value = float(max(0, int(size or 0)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"


def _format_duration_ms(duration_ms: int) -> str:
    value = max(0, int(duration_ms or 0))
    if value < 1000:
        return f"{value} ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes = int(seconds // 60)
    remain = int(seconds % 60)
    return f"{minutes} 分 {remain} 秒"


def _build_upload_detail_and_summary(task_row: sqlite3.Row, log_row: sqlite3.Row) -> tuple[dict, str]:
    metadata = {}
    try:
        metadata = json.loads(task_row["task_metadata"] or "{}")
    except Exception:
        metadata = {}

    uploaded_files = list(metadata.get("uploaded_files") or [])
    upload_files = list(metadata.get("upload_files") or [])
    upload_runtime = dict(metadata.get("upload_runtime") or {})
    selected_paths = list(metadata.get("selected_paths") or [])

    uploaded_count = len(uploaded_files) or len(upload_files)
    selected_dir_count = int(metadata.get("selected_dir_count") or len(selected_paths) or 0)
    uploaded_bytes = int(
        upload_runtime.get("total_bytes")
        or sum(int((item or {}).get("size_bytes") or (item or {}).get("size") or 0) for item in uploaded_files)
        or sum(int((item or {}).get("size") or 0) for item in upload_files)
        or 0
    )

    duration_ms = 0
    completed_at = task_row["completed_at"]
    started_at = task_row["started_at"]
    if completed_at and started_at:
        try:
            duration_ms = int((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
        except Exception:
            duration_ms = 0
    average_upload_speed_bytes = int(uploaded_bytes / max(duration_ms / 1000, 1)) if uploaded_bytes > 0 and duration_ms > 0 else 0

    target_path = str(
        metadata.get("final_output_path")
        or task_row["output_path"]
        or metadata.get("target_path")
        or ""
    ).strip()
    detail = {
        "target_path": target_path or None,
        "target_library_id": str(metadata.get("target_library_id") or "").strip() or None,
        "target_subdir": str(metadata.get("target_subdir") or "").strip() or None,
        "source_library_id": str(metadata.get("source_library_id") or "").strip() or None,
        "source_base_path": str(metadata.get("source_base_path") or task_row["source_path"] or "").strip() or None,
        "source_action": str(metadata.get("source_action") or "").strip() or None,
        "selected_dir_count": selected_dir_count or None,
        "uploaded_count": uploaded_count or None,
        "uploaded_bytes": uploaded_bytes or None,
        "average_upload_speed_bytes": average_upload_speed_bytes or None,
        "duration_ms": duration_ms or None,
        "uploaded_files": uploaded_files[:200] if uploaded_files else None,
        "upload_files": upload_files[:200] if upload_files else None,
    }
    summary_parts = [f"上传 {uploaded_count or 0} 个文件"]
    if uploaded_bytes > 0:
        summary_parts.append(_format_bytes(uploaded_bytes))
    if duration_ms > 0:
        summary_parts.append(f"耗时 {_format_duration_ms(duration_ms)}")
    if average_upload_speed_bytes > 0:
        summary_parts.append(f"平均 {_format_bytes(average_upload_speed_bytes)}/s")
    return ({k: v for k, v in detail.items() if v is not None}, " / ".join(summary_parts))


def _build_upload_detail_and_summary_from_log(log_row: sqlite3.Row) -> tuple[dict, str]:
    detail = {}
    try:
        detail = json.loads(log_row["detail"] or "{}")
    except Exception:
        detail = {}
    source_path = str(log_row["source_path"] or "").strip()
    target_path = str(detail.get("target_path") or detail.get("final_output_path") or detail.get("output_path") or "").strip()
    duration_ms = int(detail.get("duration_ms") or 0)
    summary_parts = ["上传任务完成" if str(log_row["status"] or "") == "success" else "上传任务结束"]
    if target_path:
        summary_parts.append(f"目标 {target_path}")
    if duration_ms > 0:
        summary_parts.append(f"耗时 {_format_duration_ms(duration_ms)}")
    rebuilt = {
        "target_path": target_path or None,
        "source_base_path": source_path or None,
        "duration_ms": duration_ms or None,
        "source_action": "upload_to_server",
        "selected_dir_count": None,
        "uploaded_count": None,
        "uploaded_bytes": None,
        "average_upload_speed_bytes": None,
        "upload_log_recovered": True,
    }
    return ({k: v for k, v in rebuilt.items() if v is not None}, " / ".join(summary_parts))


def apply_cleanup(conn: sqlite3.Connection) -> dict[str, int]:
    conn.row_factory = sqlite3.Row
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

    stale_processing_conflict_ids = [
        row[0]
        for row in cur.execute(
            """
            select c.id
              from conflict_works c
              left join tasks t on t.id = c.task_id
             where c.status='PROCESSING'
               and (
                    ifnull(c.task_id, '') = ''
                    or t.id is null
                    or lower(ifnull(t.status, '')) not in (
                        'pending',
                        'processing',
                        'paused',
                        'waiting_manual',
                        'waiting_retry'
                    )
               )
            """
        ).fetchall()
    ]
    for conflict_id in stale_processing_conflict_ids:
        cur.execute(
            """
            update conflict_works
               set status='PENDING',
                   new_metadata=json_set(
                       coalesce(new_metadata, '{}'),
                       '$.resolution_task_state', 'stale_processing_recovered',
                       '$.resolution_recovered_by', 'cleanup_dirty_activity_logs',
                       '$.resolution_recovered_at', datetime('now', 'localtime')
                   )
             where id=?
            """,
            (conflict_id,),
        )

    upload_log_rows = cur.execute(
        """
        select l.id,
               l.task_id,
               l.source_path,
               l.summary,
               l.detail,
               t.type,
               t.source_path as task_source_path,
               t.output_path,
               t.started_at,
               t.completed_at,
               t.task_metadata
          from activity_logs l
          join tasks t on t.id = l.task_id
         where l.category='asmr_sync'
           and lower(ifnull(t.type, ''))='local_library_upload'
        """
    ).fetchall()
    fixed_upload_logs = 0
    for row in upload_log_rows:
        detail, summary = _build_upload_detail_and_summary(row, row)
        cur.execute(
            """
            update activity_logs
               set category='upload',
                   summary=?,
                   detail=?
             where id=?
            """,
            (summary, json.dumps(detail, ensure_ascii=False), row["id"]),
        )
        fixed_upload_logs += 1

    heuristic_upload_rows = cur.execute(
        """
        select id, status, source_path, summary, detail, task_id
          from activity_logs
         where category='asmr_sync'
           and action in ('task_finished', 'task_finished_incomplete')
           and ifnull(task_id, '') != ''
           and task_id not in (select id from tasks where lower(ifnull(type, ''))='local_library_upload')
           and (
                summary like '上传完成%'
                or source_path like 'E:\\0\\临时\\asmr\\asmr%'
                or json_extract(detail, '$.output_path') like '/AMSR/%'
           )
        """
    ).fetchall()
    heuristic_fixed_upload_logs = 0
    for row in heuristic_upload_rows:
        detail, summary = _build_upload_detail_and_summary_from_log(row)
        cur.execute(
            """
            update activity_logs
               set category='upload',
                   summary=?,
                   detail=?
             where id=?
            """,
            (summary, json.dumps(detail, ensure_ascii=False), row["id"]),
        )
        heuristic_fixed_upload_logs += 1

    conn.commit()
    return {
        "deleted_pending_execute_logs": len(pending_ids),
        "updated_duplicate_success_logs": len(duplicate_ids),
        "deleted_temp_conflicts": len(deleted_conflict_ids),
        "recovered_stale_processing_conflicts": len(stale_processing_conflict_ids),
        "fixed_miscategorized_upload_logs": fixed_upload_logs,
        "heuristic_fixed_upload_logs": heuristic_fixed_upload_logs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清理历史脏操作记录/问题作品")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[2] / "data" / "cache.db"),
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
