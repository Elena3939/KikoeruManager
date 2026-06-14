"""库存索引 PostgreSQL trigram 搜索索引维护。

文件名保留为 fts.py 是为了兼容既有调用路径；运行时使用 PostgreSQL pg_trgm 索引。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import text

logger = logging.getLogger(__name__)

FTS_PREFERRED_TOKENIZE = "pg_trgm"
FTS_FALLBACK_TOKENIZE = "pg_trgm"
FTS_TABLE_NAME = "library_index_entries"
_LIBRARY_INDEX_SEARCH_INDEXES = (
    "idx_library_index_search_text_trgm",
)

_REBUILD_STATE_LOCK = threading.Lock()
_REBUILD_RUN_LOCK = threading.Lock()
_REBUILD_THREAD: threading.Thread | None = None
_REBUILD_STATE: Dict[str, Any] = {
    "state": "idle",
    "tokenizer": "pg_trgm",
    "total_entries": 0,
    "indexed_entries": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _set_rebuild_state(**updates: Any) -> None:
    with _REBUILD_STATE_LOCK:
        _REBUILD_STATE.update(updates)
        snapshot = dict(_REBUILD_STATE)
    _broadcast_fts_state(snapshot)


def _broadcast_fts_state(snapshot: Dict[str, Any]) -> None:
    try:
        from ..realtime_event_service import broadcast_event

        state = str(snapshot.get("state") or "idle")
        total = int(snapshot.get("total_entries") or 0)
        indexed = int(snapshot.get("indexed_entries") or 0)
        progress = 100 if state in {"done", "error"} else (min(99, int(indexed * 100 / total)) if total else 0)
        broadcast_event({
            "type": "maintenance.search.changed",
            "reason": "library_index",
            "id": "library_index_pg_trgm",
            "domain": "maintenance",
            "status": state,
            "progress": progress,
            "current_step": "库存 PostgreSQL trigram 索引重建中" if state == "running" else "",
            "payload": {"kind": "library_index", "rebuild": dict(snapshot)},
        })
    except Exception:
        logger.debug("[索引] 广播库存搜索索引状态失败", exc_info=True)


def _ensure_indexes(conn, *, schedule_backfill: bool = True) -> None:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    rows = conn.execute(text("""
        SELECT indexname
          FROM pg_indexes
         WHERE schemaname = current_schema()
           AND indexname = ANY(:names)
    """), {"names": list(_LIBRARY_INDEX_SEARCH_INDEXES)}).fetchall()
    existing = {str(row[0]) for row in rows}
    if schedule_backfill and len(existing) < len(_LIBRARY_INDEX_SEARCH_INDEXES):
        from ...models.database import schedule_library_index_postgres_index_maintenance

        schedule_library_index_postgres_index_maintenance()


def _estimated_entry_count(conn) -> int:
    """读 pg 统计估算行数，状态页不能对几十万库存索引做 count(*)。"""
    row = conn.execute(
        text(
            """
            SELECT GREATEST(
                     COALESCE(s.n_live_tup::bigint, c.reltuples::bigint, 0),
                     0
                   ) AS estimated_rows
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_stat_user_tables s
                ON s.relid = c.oid
               AND s.schemaname = n.nspname
             WHERE n.nspname = current_schema()
               AND c.relname = 'library_index_entries'
            """
        )
    ).mappings().first()
    estimated = int((row or {}).get("estimated_rows") or 0)
    if estimated > 0:
        return estimated
    exists = bool(conn.execute(text("SELECT 1 FROM library_index_entries LIMIT 1")).first())
    return 1 if exists else 0


def _reindex_if_exists(conn, index_name: str, *, concurrently: bool = False) -> None:
    exists = bool(conn.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": index_name}).scalar())
    if exists:
        concurrently_sql = " CONCURRENTLY" if concurrently else ""
        conn.execute(text(f'REINDEX INDEX{concurrently_sql} "{index_name}"'))


def ensure_library_index_fts(conn, *, schedule_backfill: bool = True) -> tuple[bool, str]:
    _ensure_indexes(conn, schedule_backfill=schedule_backfill)
    ready = bool(conn.execute(text("""
        SELECT count(*) = :expected
          FROM pg_indexes
         WHERE schemaname = current_schema()
           AND indexname = ANY(:names)
    """), {"expected": len(_LIBRARY_INDEX_SEARCH_INDEXES), "names": list(_LIBRARY_INDEX_SEARCH_INDEXES)}).scalar())
    return ready, "pg_trgm"


def library_index_fts_enabled(conn=None) -> bool:
    try:
        if conn is None:
            from ...models.database import engine

            with engine.connect() as local_conn:
                return library_index_fts_enabled(local_conn)
        return bool(conn.execute(text("""
            SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')
               AND (
                   SELECT count(*) = :expected
                     FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'library_index_entries'
                      AND indexname = ANY(:names)
               )
        """), {"expected": len(_LIBRARY_INDEX_SEARCH_INDEXES), "names": list(_LIBRARY_INDEX_SEARCH_INDEXES)}).scalar())
    except Exception:
        return False


def library_index_fts_ready_hint() -> bool:
    return True


def read_library_index_fts_tokenizer(conn=None) -> str:
    return "pg_trgm" if library_index_fts_enabled(conn) else ""


def sanitize_library_index_search_text(raw: str) -> str:
    text_value = "".join(ch for ch in str(raw or "") if ch.isprintable() or ch in (" ", "\t"))
    return " ".join(text_value.split())[:200]


def build_library_index_fts_match_expression(search_text: str, tokenizer: str) -> str:
    return sanitize_library_index_search_text(search_text)


def rebuild_library_index_fts(*, target_tokenizer: str = FTS_PREFERRED_TOKENIZE, progress_cb=None, batch_size: int = 5000) -> Dict[str, Any]:
    from ...models.database import engine, ensure_library_index_postgres_indexes_concurrently

    with engine.connect() as conn:
        total = _estimated_entry_count(conn)
    ensure_result = ensure_library_index_postgres_indexes_concurrently()
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        for name in _LIBRARY_INDEX_SEARCH_INDEXES:
            _reindex_if_exists(conn, name, concurrently=True)
    finally:
        conn.close()
    if progress_cb:
        progress_cb(total, total)
    return {
        "ok": True,
        "tokenizer": "pg_trgm",
        "indexed_entries": total,
        "total_entries": total,
        "copied": total,
        "total": total,
        "index_maintenance": ensure_result,
    }


def rebuild_library_index_fts_on_connection(conn, *, target_tokenizer: str = FTS_PREFERRED_TOKENIZE, batch_size: int = 5000) -> Dict[str, Any]:
    total = _estimated_entry_count(conn)
    _ensure_indexes(conn, schedule_backfill=False)
    return {
        "ok": True,
        "tokenizer": "pg_trgm",
        "indexed_entries": total,
        "total_entries": total,
        "copied": total,
        "total": total,
    }


def get_library_index_fts_rebuild_state() -> Dict[str, Any]:
    with _REBUILD_STATE_LOCK:
        return dict(_REBUILD_STATE)


def _library_index_fts_rebuild_worker(target_tokenizer: str) -> None:
    try:
        result = rebuild_library_index_fts(target_tokenizer=target_tokenizer)
        _set_rebuild_state(
            state="done",
            tokenizer="pg_trgm",
            total_entries=int(result.get("total_entries") or 0),
            indexed_entries=int(result.get("indexed_entries") or 0),
            finished_at=_now_iso(),
            error=None,
        )
    except Exception as exc:
        logger.warning("[索引] 库存 PostgreSQL 搜索索引重建失败", exc_info=True)
        _set_rebuild_state(state="error", finished_at=_now_iso(), error=str(exc))
    finally:
        try:
            _REBUILD_RUN_LOCK.release()
        except RuntimeError:
            pass


def trigger_library_index_fts_rebuild(target_tokenizer: str = FTS_PREFERRED_TOKENIZE) -> Dict[str, Any]:
    global _REBUILD_THREAD
    if not _REBUILD_RUN_LOCK.acquire(blocking=False):
        return {"started": False, "already_running": True, "status": get_library_index_fts_rebuild_state()}
    _set_rebuild_state(
        state="running",
        tokenizer="pg_trgm",
        total_entries=0,
        indexed_entries=0,
        started_at=_now_iso(),
        finished_at=None,
        error=None,
    )
    thread = threading.Thread(
        target=_library_index_fts_rebuild_worker,
        kwargs={"target_tokenizer": "pg_trgm"},
        name="library-index-pg-trgm-reindex",
        daemon=True,
    )
    _REBUILD_THREAD = thread
    thread.start()
    return {"started": True, "status": get_library_index_fts_rebuild_state()}


def library_index_fts_status() -> Dict[str, Any]:
    from ...models.database import engine

    info: Dict[str, Any] = {
        "backend": "postgresql_pg_trgm",
        "fts_enabled": False,
        "search_enabled": False,
        "tokenizer": "pg_trgm",
        "trigram_supported": False,
        "row_count": 0,
        "fts_row_count": 0,
        "needs_upgrade": False,
        "ready_hint": True,
    }
    try:
        with engine.connect() as conn:
            row_count = _estimated_entry_count(conn)
            pg_trgm_enabled = bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")).scalar())
            index_count = int(conn.execute(text("""
                SELECT count(*)
                  FROM pg_indexes
                 WHERE schemaname = current_schema()
                   AND tablename = 'library_index_entries'
                   AND indexname = ANY(:names)
            """), {"names": list(_LIBRARY_INDEX_SEARCH_INDEXES)}).scalar() or 0)
        info.update({
            "fts_enabled": pg_trgm_enabled and index_count > 0,
            "search_enabled": pg_trgm_enabled and index_count > 0,
            "trigram_supported": pg_trgm_enabled,
            "row_count": row_count,
            "fts_row_count": row_count if index_count else 0,
            "row_count_estimated": True,
            "index_count": index_count,
        })
    except Exception:
        logger.debug("[索引] 库存搜索索引状态检查失败", exc_info=True)
    return info
