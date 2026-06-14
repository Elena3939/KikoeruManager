"""PostgreSQL 数据库维护服务。

保留旧的 ``/database/maintenance/shrink`` 接口形状，但底层语义已经改为：
- 压缩旧操作记录 detail，减少 JSONB 体积。
- 执行 ``VACUUM (ANALYZE)`` 刷新统计信息并清理死元组。
- 重建 pg_trgm 搜索索引，保证操作历史和库存搜索继续走 GIN trigram。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

_STATE_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "state": "idle",
    "stage": None,
    "stage_label": "",
    "started_at": None,
    "finished_at": None,
    "duration_ms": 0,
    "older_than_days": 30,
    "min_detail_bytes": 8192,
    "before": None,
    "after": None,
    "compact_result": None,
    "vacuum_ms": 0,
    "reindex_result": None,
    "freed_bytes": 0,
    "freed_human": "0 B",
    "estimated_freed_bytes": 0,
    "estimated_freed_human": "0 B",
    "error": None,
    "heartbeat": None,
}

_STAGE_LABELS = {
    "compact": "正在压缩旧操作记录详情...",
    "vacuum_analyze": "正在执行 PostgreSQL VACUUM ANALYZE...",
    "reindex": "正在重建 PostgreSQL trigram 搜索索引...",
    "finalize": "正在采集维护结果...",
}

_TRIGRAM_INDEXES = (
    "idx_activity_logs_summary_trgm",
    "idx_activity_logs_source_path_trgm",
    "idx_activity_logs_rjcode_trgm",
    "idx_activity_logs_task_id_trgm",
    "idx_activity_logs_batch_id_trgm",
    "idx_library_index_search_text_trgm",
    "idx_task_center_searchable_text_trgm",
    "idx_task_center_title_trgm",
    "idx_task_center_business_key_trgm",
    "idx_task_center_engine_task_id_trgm",
    "idx_processed_archives_filename_trgm",
    "idx_processed_archives_rjcode_trgm",
)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _human_bytes(n: int) -> str:
    n = int(n or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ("B", "KB", "MB", "GB", "TB")
    idx = 0
    value = float(n)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{sign}{int(value)} {units[idx]}" if idx == 0 else f"{sign}{value:.2f} {units[idx]}"


def _database_identity() -> str:
    from ..models.database import get_database_url_info

    return get_database_url_info()


def _pg_relation_size(conn, table_name: str) -> Dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
              pg_total_relation_size(to_regclass(:name)) AS total,
              pg_relation_size(to_regclass(:name)) AS heap,
              pg_indexes_size(to_regclass(:name)) AS indexes
            """
        ),
        {"name": table_name},
    ).mappings().first() or {}
    return {
        "total_size_bytes": int(row.get("total") or 0),
        "table_size_bytes": int(row.get("heap") or 0),
        "index_size_bytes": int(row.get("indexes") or 0),
        "total_human": _human_bytes(row.get("total") or 0),
        "table_human": _human_bytes(row.get("heap") or 0),
        "index_human": _human_bytes(row.get("indexes") or 0),
    }


def _pg_estimated_table_rows(conn, table_names: list[str]) -> Dict[str, int]:
    if not table_names:
        return {}
    stmt = text(
        """
        SELECT
          c.relname,
          GREATEST(
            COALESCE(s.n_live_tup::bigint, c.reltuples::bigint, 0),
            0
          ) AS estimated_rows
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_stat_user_tables s
            ON s.relid = c.oid
           AND s.schemaname = n.nspname
         WHERE n.nspname = current_schema()
           AND c.relkind IN ('r', 'p')
           AND c.relname IN :names
        """
    ).bindparams(bindparam("names", expanding=True))
    rows = conn.execute(stmt, {"names": table_names}).mappings().all()
    estimates = {str(row["relname"]): int(row["estimated_rows"] or 0) for row in rows}
    return {name: estimates.get(name, 0) for name in table_names}


def _pg_database_sizes() -> Dict[str, Any]:
    from ..models.database import engine

    with engine.connect() as conn:
        database_size = int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
        activity_logs = _pg_relation_size(conn, "activity_logs")
        library_index = _pg_relation_size(conn, "library_index_entries")
        table_rows = _pg_estimated_table_rows(conn, ["activity_logs", "library_index_entries"])
        index_rows = conn.execute(
            text(
                """
                SELECT indexname, tablename, pg_relation_size((schemaname || '.' || indexname)::regclass) AS bytes
                  FROM pg_indexes
                 WHERE schemaname = current_schema()
                   AND (
                        indexname LIKE 'idx_activity_logs_%_trgm'
                     OR indexname LIKE 'idx_library_index_%_trgm'
                     OR indexname LIKE 'idx_task_center_%_trgm'
                     OR indexname LIKE 'idx_processed_archives_%_trgm'
                   )
                 ORDER BY tablename, indexname
                """
            )
        ).mappings().all()
        indexes = [
            {
                "name": str(row["indexname"]),
                "table": str(row["tablename"]),
                "size_bytes": int(row["bytes"] or 0),
                "size_human": _human_bytes(row["bytes"] or 0),
            }
            for row in index_rows
        ]
    return {
        "database_url": _database_identity(),
        "database_size_bytes": database_size,
        "database_size_human": _human_bytes(database_size),
        "main_size_bytes": database_size,
        "wal_size_bytes": 0,
        "shm_size_bytes": 0,
        "total_size_bytes": database_size,
        "main_human": _human_bytes(database_size),
        "wal_human": "0 B",
        "shm_human": "0 B",
        "total_human": _human_bytes(database_size),
        "activity_logs": activity_logs,
        "library_index_entries": library_index,
        "table_rows": table_rows,
        "table_rows_estimated": True,
        "trigram_indexes": indexes,
        "index_size_bytes": sum(item["size_bytes"] for item in indexes),
        "index_size_human": _human_bytes(sum(item["size_bytes"] for item in indexes)),
    }


def _broadcast_shrink_state(snapshot: Dict[str, Any]) -> None:
    try:
        from .realtime_event_service import broadcast_event

        stage = str(snapshot.get("stage") or "")
        state = str(snapshot.get("state") or "idle")
        progress_by_stage = {
            "compact": 25,
            "vacuum_analyze": 55,
            "reindex": 80,
            "finalize": 95,
        }
        if state in {"done", "error"}:
            progress = 100
        elif state == "running":
            progress = progress_by_stage.get(stage, 5)
        else:
            progress = 0
        broadcast_event({
            "type": "maintenance.database_shrink.changed",
            "reason": stage or state,
            "id": "database_maintenance",
            "domain": "maintenance",
            "status": state,
            "progress": progress,
            "current_step": str(snapshot.get("stage_label") or ""),
            "updated_at": str(snapshot.get("heartbeat") or _now_iso()),
            "payload": dict(snapshot),
        })
    except Exception:
        logger.debug("[数据库维护] 广播实时状态失败", exc_info=True)


def _set_state(**updates: Any) -> None:
    with _STATE_LOCK:
        _STATE.update(updates)
        _STATE["heartbeat"] = _now_iso()
        snapshot = dict(_STATE)
    _broadcast_shrink_state(snapshot)


def get_status() -> Dict[str, Any]:
    with _STATE_LOCK:
        snapshot = dict(_STATE)
    snapshot["database_url"] = _database_identity()
    snapshot["db_path"] = snapshot["database_url"]
    return snapshot


def reset_status() -> None:
    with _STATE_LOCK:
        if _STATE["state"] == "running":
            return
        _STATE.update({
            "state": "idle",
            "stage": None,
            "stage_label": "",
            "started_at": None,
            "finished_at": None,
            "duration_ms": 0,
            "before": None,
            "after": None,
            "compact_result": None,
            "vacuum_ms": 0,
            "reindex_result": None,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "estimated_freed_bytes": 0,
            "estimated_freed_human": "0 B",
            "error": None,
            "heartbeat": _now_iso(),
        })


def estimate(*, older_than_days: int = 30, min_detail_bytes: int = 8192, sample_limit: int = 200) -> Dict[str, Any]:
    from .activity_log_compactor import estimate_compact_savings

    sizes = _pg_database_sizes()
    try:
        compact = estimate_compact_savings(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            sample_limit=sample_limit,
        )
    except Exception as exc:
        logger.warning("[数据库维护] 操作记录压缩估算失败: %s", exc, exc_info=True)
        compact = {
            "candidate_total": 0,
            "estimated_compactable_total": 0,
            "estimated_saved_bytes": 0,
            "older_than_days": older_than_days,
            "min_detail_bytes": min_detail_bytes,
            "error": str(exc),
        }

    estimated_freed = int(compact.get("estimated_saved_bytes", 0) or 0)
    estimated_after = max(0, int(sizes["database_size_bytes"] or 0) - estimated_freed)
    return {
        "backend": "postgresql",
        "db_path": sizes["database_url"],
        **sizes,
        "compact": compact,
        "maintenance_actions": ["compact_activity_logs", "vacuum_analyze", "reindex_pg_trgm"],
        "estimated_freed_bytes": estimated_freed,
        "estimated_freed_human": _human_bytes(estimated_freed),
        "estimated_after_total_bytes": estimated_after,
        "estimated_after_total_human": _human_bytes(estimated_after),
        "running": get_status()["state"] == "running",
    }


def _do_compact_loop(*, older_than_days: int, min_detail_bytes: int) -> Dict[str, Any]:
    from .activity_log_compactor import compact_old_activity_logs

    overall_deadline = time.monotonic() + 10 * 60
    aggregate = {
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "saved_bytes": 0,
        "rounds": 0,
        "done": False,
    }

    while True:
        if time.monotonic() > overall_deadline:
            logger.warning("[数据库维护] 操作记录压缩超过 10 分钟，提前进入下一阶段")
            break
        result = compact_old_activity_logs(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            max_rows=5000,
            chunk_size=200,
            time_budget_seconds=5.0,
        )
        aggregate["rounds"] += 1
        for key in ("scanned", "updated", "skipped", "failed", "saved_bytes"):
            aggregate[key] += int(result.get(key, 0) or 0)
        _set_state(
            stage="compact",
            stage_label=(
                f"{_STAGE_LABELS['compact']} 已扫描 {aggregate['scanned']} 行，"
                f"更新 {aggregate['updated']} 行，预计节省 {_human_bytes(aggregate['saved_bytes'])}"
            ),
        )
        if result.get("done"):
            aggregate["done"] = True
            break
    return aggregate


def _do_vacuum_analyze() -> int:
    from ..models.database import engine

    started = time.monotonic()
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        conn.execute(text("VACUUM (ANALYZE)"))
    finally:
        conn.close()
    return int((time.monotonic() - started) * 1000)


def _do_reindex_trigram() -> Dict[str, Any]:
    from ..models.database import (
        configure_postgres_online_maintenance_connection,
        engine,
        release_postgres_online_maintenance_lock,
    )

    started = time.monotonic()
    rebuilt: list[str] = []
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_acquired = False
    try:
        lock_acquired = configure_postgres_online_maintenance_connection(conn, lock_timeout_ms=3000)
        if not lock_acquired:
            return {
                "rebuilt_indexes": rebuilt,
                "rebuilt_count": 0,
                "skipped": True,
                "reason": "already_running",
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        for name in _TRIGRAM_INDEXES:
            exists = bool(conn.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar())
            if not exists:
                continue
            conn.execute(text(f'REINDEX INDEX CONCURRENTLY "{name}"'))
            rebuilt.append(name)
    finally:
        if lock_acquired:
            try:
                release_postgres_online_maintenance_lock(conn)
            except Exception:
                logger.debug("[数据库维护] 释放 PostgreSQL 在线维护锁失败", exc_info=True)
        conn.close()
    return {
        "rebuilt_indexes": rebuilt,
        "rebuilt_count": len(rebuilt),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


_PERFORMANCE_SETTINGS = (
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "max_wal_size",
    "checkpoint_timeout",
    "random_page_cost",
    "effective_io_concurrency",
    "default_statistics_target",
    "autovacuum",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_analyze_scale_factor",
    "track_io_timing",
    "shared_preload_libraries",
    "pg_stat_statements.track",
    "pg_stat_statements.max",
    "statement_timeout",
)

_PERFORMANCE_TABLES = (
    "activity_logs",
    "activity_log_rollups",
    "library_index_entries",
    "library_index_status",
    "task_center_items",
    "task_phase_metrics",
    "work_metadata",
    "conflict_works",
    "asmr_resource_records",
    "asmr_download_sessions",
    "password_entries",
    "processed_archives",
)


def _pg_stat_statements_status(conn) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "installed": False,
        "preloaded": False,
        "queryable": False,
        "track": None,
        "max": None,
        "error": None,
    }
    try:
        status["installed"] = bool(
            conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')")
            ).scalar()
        )
        try:
            preload = str(conn.execute(text("SHOW shared_preload_libraries")).scalar() or "")
            status["preloaded"] = "pg_stat_statements" in {item.strip() for item in preload.split(",") if item.strip()}
        except Exception as exc:
            status["error"] = str(exc)
        if status["installed"]:
            nested = conn.begin_nested()
            try:
                status["track"] = str(conn.execute(text("SHOW pg_stat_statements.track")).scalar() or "")
                status["max"] = str(conn.execute(text("SHOW pg_stat_statements.max")).scalar() or "")
                conn.execute(text("SELECT 1 FROM pg_stat_statements LIMIT 1")).first()
                status["queryable"] = True
                nested.commit()
            except Exception as exc:
                nested.rollback()
                status["queryable"] = False
                status["error"] = str(exc)
    except Exception as exc:
        status["error"] = str(exc)
    return status


def _postgres_runtime_settings(conn) -> Dict[str, Any]:
    stmt = text(
            """
            SELECT name, setting, unit, source, pending_restart, boot_val, reset_val
              FROM pg_settings
             WHERE name IN :names
             ORDER BY name
            """
    ).bindparams(bindparam("names", expanding=True))
    rows = conn.execute(
        stmt,
        {"names": list(_PERFORMANCE_SETTINGS)},
    ).mappings().all()
    settings = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        setting = str(row["setting"])
        unit = row.get("unit")
        item = {
            "name": str(row["name"]),
            "setting": setting,
            "unit": unit,
            "pretty_value": _format_pg_setting_value(setting, unit),
            "source": str(row.get("source") or ""),
            "pending_restart": bool(row.get("pending_restart")),
            "boot_val": str(row.get("boot_val") or ""),
            "reset_val": str(row.get("reset_val") or ""),
        }
        settings.append(item)
        by_name[item["name"]] = item
    return {"items": settings, "by_name": by_name}


def _format_pg_setting_value(setting: str, unit: Any) -> str:
    unit_text = str(unit or "")
    if not unit_text:
        return str(setting)
    try:
        numeric = float(setting)
    except (TypeError, ValueError):
        return f"{setting}{unit_text}"
    if unit_text == "8kB":
        return _human_bytes(int(numeric * 8 * 1024))
    if unit_text == "kB":
        return _human_bytes(int(numeric * 1024))
    if unit_text == "MB":
        return _human_bytes(int(numeric * 1024 * 1024))
    if unit_text == "ms":
        return f"{int(numeric)}ms"
    if unit_text == "s":
        return f"{int(numeric)}s"
    if unit_text == "min":
        return f"{int(numeric)}min"
    return f"{setting}{unit_text}"


def _slow_queries(conn, *, limit: int) -> Dict[str, Any]:
    status = _pg_stat_statements_status(conn)
    if not status.get("queryable"):
        return {"status": status, "items": []}

    rows = conn.execute(
        text(
            """
            SELECT
              queryid::text AS queryid,
              calls,
              total_exec_time,
              mean_exec_time,
              max_exec_time,
              rows,
              shared_blks_hit,
              shared_blks_read,
              temp_blks_read,
              temp_blks_written,
              CASE
                WHEN shared_blks_hit + shared_blks_read = 0 THEN 100.0
                ELSE round((shared_blks_hit::numeric / (shared_blks_hit + shared_blks_read)) * 100, 2)
              END AS shared_hit_percent,
              left(regexp_replace(query, '\\s+', ' ', 'g'), 420) AS query
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND lower(ltrim(query)) NOT LIKE '%pg_stat_statements%'
              AND lower(ltrim(query)) NOT LIKE '%pg_settings%'
              AND lower(ltrim(query)) NOT LIKE '%pg_stat_user_tables%'
              AND lower(ltrim(query)) NOT LIKE '%pg_indexes%'
              AND lower(ltrim(query)) NOT LIKE '%pg_database_size%'
              AND lower(ltrim(query)) NOT LIKE '%pg_total_relation_size%'
              AND lower(ltrim(query)) NOT LIKE '%pg_extension%'
              AND lower(ltrim(query)) NOT LIKE '%from pg_type%'
              AND lower(ltrim(query)) NOT LIKE 'show %'
              AND lower(ltrim(query)) NOT LIKE 'create extension%'
              AND lower(ltrim(query)) NOT LIKE 'create index%'
              AND lower(ltrim(query)) NOT LIKE 'analyze %'
              AND lower(ltrim(query)) NOT LIKE 'explain %'
              AND lower(ltrim(query)) NOT LIKE 'select current_schema%'
              AND lower(ltrim(query)) NOT LIKE 'select pg_catalog.version%'
              AND lower(ltrim(query)) NOT LIKE 'select typname as name%'
              AND lower(ltrim(query)) NOT LIKE 'savepoint %'
              AND lower(ltrim(query)) NOT LIKE 'release savepoint%'
              AND lower(ltrim(query)) NOT LIKE 'release %'
              AND lower(ltrim(query)) NOT IN ('begin', 'commit', 'rollback')
            ORDER BY total_exec_time DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return {
        "status": status,
        "items": [
            {
                "queryid": row["queryid"],
                "calls": int(row["calls"] or 0),
                "total_exec_time_ms": round(float(row["total_exec_time"] or 0), 2),
                "mean_exec_time_ms": round(float(row["mean_exec_time"] or 0), 2),
                "max_exec_time_ms": round(float(row["max_exec_time"] or 0), 2),
                "rows": int(row["rows"] or 0),
                "shared_blks_hit": int(row["shared_blks_hit"] or 0),
                "shared_blks_read": int(row["shared_blks_read"] or 0),
                "temp_blks_read": int(row["temp_blks_read"] or 0),
                "temp_blks_written": int(row["temp_blks_written"] or 0),
                "shared_hit_percent": float(row["shared_hit_percent"] or 0),
                "query": str(row["query"] or "").strip(),
            }
            for row in rows
        ],
    }


def _table_performance_stats(conn) -> list[Dict[str, Any]]:
    stmt = text(
            """
            SELECT
              s.relname,
              s.seq_scan,
              s.idx_scan,
              s.n_live_tup,
              s.n_dead_tup,
              s.vacuum_count,
              s.autovacuum_count,
              s.analyze_count,
              s.autoanalyze_count,
              s.last_vacuum,
              s.last_autovacuum,
              s.last_analyze,
              s.last_autoanalyze,
              pg_total_relation_size(c.oid) AS total_size_bytes
            FROM pg_stat_user_tables s
            JOIN pg_class c ON c.relname = s.relname
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = current_schema()
            WHERE s.relname IN :names
              AND s.schemaname = current_schema()
            ORDER BY pg_total_relation_size(c.oid) DESC, s.relname
            """
    ).bindparams(bindparam("names", expanding=True))
    rows = conn.execute(
        stmt,
        {"names": list(_PERFORMANCE_TABLES)},
    ).mappings().all()
    result = []
    for row in rows:
        total_scans = int(row["seq_scan"] or 0) + int(row["idx_scan"] or 0)
        seq_scan_percent = 0.0 if total_scans <= 0 else round((int(row["seq_scan"] or 0) / total_scans) * 100, 2)
        dead_tuple_percent = 0.0
        live = int(row["n_live_tup"] or 0)
        dead = int(row["n_dead_tup"] or 0)
        if live + dead > 0:
            dead_tuple_percent = round((dead / (live + dead)) * 100, 2)
        result.append({
            "table": str(row["relname"]),
            "seq_scan": int(row["seq_scan"] or 0),
            "idx_scan": int(row["idx_scan"] or 0),
            "seq_scan_percent": seq_scan_percent,
            "n_live_tup": live,
            "n_dead_tup": dead,
            "dead_tuple_percent": dead_tuple_percent,
            "vacuum_count": int(row["vacuum_count"] or 0),
            "autovacuum_count": int(row["autovacuum_count"] or 0),
            "analyze_count": int(row["analyze_count"] or 0),
            "autoanalyze_count": int(row["autoanalyze_count"] or 0),
            "last_vacuum": row["last_vacuum"].isoformat() if row.get("last_vacuum") else None,
            "last_autovacuum": row["last_autovacuum"].isoformat() if row.get("last_autovacuum") else None,
            "last_analyze": row["last_analyze"].isoformat() if row.get("last_analyze") else None,
            "last_autoanalyze": row["last_autoanalyze"].isoformat() if row.get("last_autoanalyze") else None,
            "total_size_bytes": int(row["total_size_bytes"] or 0),
            "total_size_human": _human_bytes(row["total_size_bytes"] or 0),
        })
    return result


def performance_snapshot(*, limit: int = 10) -> Dict[str, Any]:
    """返回 PostgreSQL 性能观测快照。

    不要求 ``pg_stat_statements`` 一定可用；未预加载或无权限时返回状态和空 Top SQL，
    避免维护页因为观测扩展不可用而影响业务。
    """
    from ..models.database import engine

    started = time.monotonic()
    limit = max(1, min(50, int(limit or 10)))
    with engine.connect() as conn:
        settings = _postgres_runtime_settings(conn)
        slow = _slow_queries(conn, limit=limit)
        tables = _table_performance_stats(conn)
        database_size = int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
    return {
        "backend": "postgresql",
        "database_url": _database_identity(),
        "database_size_bytes": database_size,
        "database_size_human": _human_bytes(database_size),
        "settings": settings["items"],
        "settings_by_name": settings["by_name"],
        "pg_stat_statements": slow["status"],
        "slow_queries": slow["items"],
        "table_stats": tables,
        "limit": limit,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def reset_pg_stat_statements() -> Dict[str, Any]:
    from ..models.database import engine

    try:
        with engine.begin() as conn:
            status = _pg_stat_statements_status(conn)
            if not status.get("queryable"):
                return {
                    "ok": False,
                    "reset": False,
                    "pg_stat_statements": status,
                    "error": status.get("error") or "pg_stat_statements 不可查询",
                }
            conn.execute(text("SELECT pg_stat_statements_reset()"))
            return {"ok": True, "reset": True, "pg_stat_statements": _pg_stat_statements_status(conn)}
    except Exception as exc:
        logger.warning("[数据库维护] 重置 pg_stat_statements 失败: %s", exc, exc_info=True)
        return {"ok": False, "reset": False, "error": str(exc)}


def _invalidate_activity_log_caches() -> None:
    try:
        from .activity_log_writer import get_activity_log_query_cache, get_activity_log_row_dict_cache

        get_activity_log_query_cache().invalidate()
        get_activity_log_row_dict_cache().invalidate()
    except Exception:
        logger.debug("[数据库维护] 失效操作记录缓存失败（非致命）", exc_info=True)


def _shrink_worker(*, older_than_days: int, min_detail_bytes: int) -> None:
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    before = _pg_database_sizes()
    _set_state(
        state="running",
        stage="compact",
        stage_label=_STAGE_LABELS["compact"],
        started_at=started_at,
        finished_at=None,
        duration_ms=0,
        older_than_days=older_than_days,
        min_detail_bytes=min_detail_bytes,
        before=before,
        after=None,
        compact_result=None,
        vacuum_ms=0,
        reindex_result=None,
        freed_bytes=0,
        freed_human="0 B",
        estimated_freed_bytes=0,
        estimated_freed_human="0 B",
        error=None,
    )
    try:
        from ..models.database import check_database_health

        precheck = check_database_health(full=False)
        if not precheck.get("ok"):
            raise RuntimeError(f"数据库维护前自检失败: {precheck}")

        compact_result = _do_compact_loop(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
        )
        _set_state(compact_result=compact_result)
        _invalidate_activity_log_caches()

        _set_state(stage="vacuum_analyze", stage_label=_STAGE_LABELS["vacuum_analyze"])
        vacuum_ms = _do_vacuum_analyze()
        _set_state(vacuum_ms=vacuum_ms)

        _set_state(stage="reindex", stage_label=_STAGE_LABELS["reindex"])
        reindex_result = _do_reindex_trigram()
        _set_state(reindex_result=reindex_result)

        _set_state(stage="finalize", stage_label=_STAGE_LABELS["finalize"])
        postcheck = check_database_health(full=True)
        if not postcheck.get("ok"):
            raise RuntimeError(f"数据库维护后自检失败: {postcheck}")
        after = _pg_database_sizes()
        freed = max(0, int(before["database_size_bytes"] or 0) - int(after["database_size_bytes"] or 0))
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        _set_state(
            state="done",
            stage=None,
            stage_label="",
            finished_at=_now_iso(),
            duration_ms=duration_ms,
            after=after,
            freed_bytes=freed,
            freed_human=_human_bytes(freed),
            estimated_freed_bytes=int(compact_result.get("saved_bytes", 0) or 0),
            estimated_freed_human=_human_bytes(compact_result.get("saved_bytes", 0) or 0),
        )
        logger.info(
            "[数据库维护] 完成：扫描 %s 行 / 更新 %s 行 / VACUUM ANALYZE %sms / REINDEX %s 个 / 库大小 %s -> %s",
            compact_result.get("scanned", 0),
            compact_result.get("updated", 0),
            vacuum_ms,
            reindex_result.get("rebuilt_count", 0),
            before["database_size_human"],
            after["database_size_human"],
        )
    except Exception as exc:
        logger.error("[数据库维护] 失败: %s", exc, exc_info=True)
        try:
            after = _pg_database_sizes()
        except Exception:
            after = None
        freed = 0
        if after and before:
            freed = max(0, int(before["database_size_bytes"] or 0) - int(after["database_size_bytes"] or 0))
        _set_state(
            state="error",
            stage=None,
            stage_label="",
            finished_at=_now_iso(),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            after=after,
            freed_bytes=freed,
            freed_human=_human_bytes(freed),
            error=str(exc),
        )
    finally:
        try:
            _RUN_LOCK.release()
        except RuntimeError:
            pass


def start_shrink(*, older_than_days: int = 30, min_detail_bytes: int = 8192) -> Dict[str, Any]:
    older_than_days = max(1, int(older_than_days or 30))
    min_detail_bytes = max(0, int(min_detail_bytes or 0))
    if not _RUN_LOCK.acquire(blocking=False):
        logger.info("[数据库维护] 启动请求被忽略：已有任务运行中")
        return {"started": False, "already_running": True, "status": get_status()}

    with _STATE_LOCK:
        _STATE.update({
            "state": "running",
            "stage": "compact",
            "stage_label": _STAGE_LABELS["compact"],
            "started_at": _now_iso(),
            "finished_at": None,
            "duration_ms": 0,
            "older_than_days": older_than_days,
            "min_detail_bytes": min_detail_bytes,
            "before": None,
            "after": None,
            "compact_result": None,
            "vacuum_ms": 0,
            "reindex_result": None,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "estimated_freed_bytes": 0,
            "estimated_freed_human": "0 B",
            "error": None,
            "heartbeat": _now_iso(),
        })

    thread = threading.Thread(
        target=_shrink_worker,
        kwargs={"older_than_days": older_than_days, "min_detail_bytes": min_detail_bytes},
        name="database-maintenance",
        daemon=True,
    )
    thread.start()
    logger.info("[数据库维护] 已启动: older_than_days=%s min_detail_bytes=%s", older_than_days, min_detail_bytes)
    return {"started": True, "already_running": False, "status": get_status()}
