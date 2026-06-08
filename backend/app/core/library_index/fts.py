"""库存索引 FTS5 搜索引擎。

只服务 `library_index_entries`：
- 启动时幂等确保 FTS5 虚表和触发器存在
- 新写入 / 更新 / 删除由触发器同步
- 老数据回填和 tokenizer 切换走后台重建，避免启动卡死
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

FTS_TABLE_NAME = "library_index_entries_fts"
FTS_PREFERRED_TOKENIZE = "trigram"
FTS_FALLBACK_TOKENIZE = "unicode61 remove_diacritics 2"

_SEARCH_TEXT_MAX_LEN = 200
_FTS_DANGER_CHARS = (
    '"',
    "(",
    ")",
    "*",
    ":",
    "^",
    "+",
    "-",
    "&",
    "|",
    "%",
    "_",
    "\x00",
)

_READY_HINT_LOCK = threading.Lock()
_READY_HINT: Optional[bool] = None

_REBUILD_STATE_LOCK = threading.Lock()
_REBUILD_RUN_LOCK = threading.Lock()
_REBUILD_THREAD: Optional[threading.Thread] = None
_REBUILD_STATE: Dict[str, Any] = {
    "state": "idle",
    "tokenizer": "",
    "total_entries": 0,
    "indexed_entries": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _set_ready_hint(value: Optional[bool]) -> None:
    global _READY_HINT
    with _READY_HINT_LOCK:
        _READY_HINT = value


def library_index_fts_ready_hint() -> Optional[bool]:
    """返回 FTS 是否已经覆盖主表的轻量提示。

    None 表示未知：查询层可以尝试走 FTS，失败再 fallback。
    False 表示 FTS 表为空而主表已有数据，重建完成前应直接走 LIKE。
    """
    with _READY_HINT_LOCK:
        return _READY_HINT


def _normalize_tokenizer(tokenizer: str) -> str:
    desired = (tokenizer or "").strip().lower()
    if desired == FTS_PREFERRED_TOKENIZE:
        return FTS_PREFERRED_TOKENIZE
    if desired.startswith("unicode61"):
        return FTS_FALLBACK_TOKENIZE
    return FTS_PREFERRED_TOKENIZE


def _detect_fts5_supported(conn) -> bool:
    try:
        conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS _lie_fts5_probe USING fts5(x)"))
        try:
            conn.execute(text("DROP TABLE IF EXISTS _lie_fts5_probe"))
        except Exception:
            pass
        return True
    except Exception:
        return False


def _detect_trigram_supported(conn) -> bool:
    try:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _lie_fts_trigram_probe "
            "USING fts5(x, tokenize='trigram')"
        ))
        try:
            conn.execute(text("DROP TABLE IF EXISTS _lie_fts_trigram_probe"))
        except Exception:
            pass
        return True
    except Exception:
        return False


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return row is not None


def _read_fts_tokenizer(conn, table_name: str = FTS_TABLE_NAME) -> str:
    try:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        ).fetchone()
        if not row or not row[0]:
            return ""
        sql_text = str(row[0])
        lower = sql_text.lower()
        idx = lower.find("tokenize")
        if idx < 0:
            return "simple"
        rest = sql_text[idx:]
        for quote in ("'", '"'):
            q1 = rest.find(quote)
            if q1 < 0:
                continue
            q2 = rest.find(quote, q1 + 1)
            if q2 < 0:
                continue
            return rest[q1 + 1:q2].strip().lower()
        return ""
    except Exception:
        return ""


def _create_fts_triggers(conn, table_name: str = FTS_TABLE_NAME) -> None:
    trigger_sqls = (
        f"""
        CREATE TRIGGER IF NOT EXISTS library_index_entries_fts_ai
        AFTER INSERT ON library_index_entries BEGIN
          INSERT INTO {table_name}(id, library_id, entry_type, name, relative_path, rjcode, parent_path)
          VALUES (
            NEW.id,
            COALESCE(NEW.library_id, ''),
            COALESCE(NEW.entry_type, ''),
            COALESCE(NEW.name, ''),
            COALESCE(NEW.relative_path, ''),
            COALESCE(NEW.rjcode, ''),
            COALESCE(NEW.parent_path, '')
          );
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS library_index_entries_fts_ad
        AFTER DELETE ON library_index_entries BEGIN
          DELETE FROM {table_name} WHERE id = OLD.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS library_index_entries_fts_au
        AFTER UPDATE ON library_index_entries BEGIN
          DELETE FROM {table_name} WHERE id = OLD.id;
          INSERT INTO {table_name}(id, library_id, entry_type, name, relative_path, rjcode, parent_path)
          VALUES (
            NEW.id,
            COALESCE(NEW.library_id, ''),
            COALESCE(NEW.entry_type, ''),
            COALESCE(NEW.name, ''),
            COALESCE(NEW.relative_path, ''),
            COALESCE(NEW.rjcode, ''),
            COALESCE(NEW.parent_path, '')
          );
        END
        """,
    )
    for sql in trigger_sqls:
        try:
            conn.execute(text(sql))
        except Exception:
            logger.warning("[索引] 创建库存 FTS 触发器失败", exc_info=True)


def _drop_fts_triggers(conn) -> None:
    for name in (
        "library_index_entries_fts_ai",
        "library_index_entries_fts_ad",
        "library_index_entries_fts_au",
    ):
        try:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        except Exception:
            logger.debug("[索引] 删除库存 FTS 触发器失败 trigger=%s", name, exc_info=True)


def _create_fts_table(conn, tokenizer: str, table_name: str = FTS_TABLE_NAME) -> None:
    conn.execute(text(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
            id UNINDEXED,
            library_id UNINDEXED,
            entry_type UNINDEXED,
            name,
            relative_path,
            rjcode,
            parent_path,
            tokenize='{tokenizer}'
        )
        """
    ))


def _maybe_schedule_initial_backfill(conn, tokenizer: str, schedule_backfill: bool) -> None:
    try:
        row_count = int(conn.execute(text("SELECT count(*) FROM library_index_entries")).scalar() or 0)
        fts_row_count = int(conn.execute(text(f"SELECT count(*) FROM {FTS_TABLE_NAME}")).scalar() or 0)
    except Exception:
        _set_ready_hint(None)
        return

    if row_count > 0 and fts_row_count != row_count:
        _set_ready_hint(False)
        if schedule_backfill:
            logger.info(
                "[索引] 库存 FTS 行数不一致 main=%d fts=%d，后台触发回填",
                row_count,
                fts_row_count,
            )
            trigger_library_index_fts_rebuild(target_tokenizer=tokenizer)
        return

    _set_ready_hint(True)


def ensure_library_index_fts(conn, *, schedule_backfill: bool = True) -> tuple[bool, str]:
    """启动时确保库存 FTS 表和触发器存在。

    只创建缺失结构；已有 FTS 表不做同步重建，避免大库启动卡住。
    """
    if not _detect_fts5_supported(conn):
        logger.warning("[索引] 当前 SQLite 不支持 FTS5，库存搜索回退 LIKE")
        _set_ready_hint(None)
        return False, ""

    existing = _read_fts_tokenizer(conn)
    if existing:
        _create_fts_triggers(conn)
        _maybe_schedule_initial_backfill(conn, existing, schedule_backfill)
        return True, existing

    tokenizer = FTS_PREFERRED_TOKENIZE if _detect_trigram_supported(conn) else FTS_FALLBACK_TOKENIZE
    try:
        _create_fts_table(conn, tokenizer)
        _create_fts_triggers(conn)
        logger.info("[索引] library_index_entries_fts 创建完成，tokenizer=%s", tokenizer)
    except Exception:
        logger.warning("[索引] 创建 library_index_entries_fts 失败，库存搜索回退 LIKE", exc_info=True)
        _set_ready_hint(None)
        return False, ""

    _maybe_schedule_initial_backfill(conn, tokenizer, schedule_backfill)
    return True, tokenizer


def library_index_fts_enabled(conn=None) -> bool:
    try:
        if conn is not None:
            return _table_exists(conn, FTS_TABLE_NAME)
        from ...models.database import engine

        with engine.connect() as own_conn:
            return _table_exists(own_conn, FTS_TABLE_NAME)
    except Exception:
        return False


def read_library_index_fts_tokenizer(conn=None) -> str:
    try:
        if conn is not None:
            return _read_fts_tokenizer(conn)
        from ...models.database import engine

        with engine.connect() as own_conn:
            return _read_fts_tokenizer(own_conn)
    except Exception:
        return ""


def sanitize_library_index_search_text(raw: str) -> str:
    if not raw:
        return ""
    value = "".join(ch for ch in str(raw) if ch.isprintable() or ch in (" ", "\t"))
    for danger in _FTS_DANGER_CHARS:
        value = value.replace(danger, " ")
    value = " ".join(value.split())
    return value[:_SEARCH_TEXT_MAX_LEN]


def build_library_index_fts_match_expression(search_text: str, tokenizer: str) -> str:
    cleaned = (search_text or "").strip()
    if not cleaned:
        return ""
    tk = (tokenizer or "").strip().lower()
    if tk.startswith("trigram"):
        if len(cleaned) < 3:
            return ""
        return f'"{cleaned}"'

    tokens = [item for item in cleaned.split() if item]
    parts = []
    for token in tokens:
        safe = token
        for danger in _FTS_DANGER_CHARS:
            safe = safe.replace(danger, "")
        safe = safe.strip()
        if safe:
            parts.append(f"{safe}*")
    return " AND ".join(parts)


def rebuild_library_index_fts_on_connection(
    conn,
    *,
    target_tokenizer: str = FTS_PREFERRED_TOKENIZE,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    batch_size: int = 5000,
) -> Dict[str, Any]:
    """同步重建库存 FTS 表。调用方负责放后台线程或测试事务。"""
    target = _normalize_tokenizer(target_tokenizer)
    new_table = f"{FTS_TABLE_NAME}_new"
    batch_size = max(1, int(batch_size or 5000))

    if not _detect_fts5_supported(conn):
        _set_ready_hint(None)
        return {"ok": False, "reason": "fts5_not_supported"}
    if target == FTS_PREFERRED_TOKENIZE and not _detect_trigram_supported(conn):
        return {"ok": False, "reason": "trigram_not_supported"}

    try:
        conn.execute(text(f"DROP TABLE IF EXISTS {new_table}"))
        _create_fts_table(conn, target, new_table)
    except Exception as exc:
        logger.warning("[索引] 创建库存 FTS 新表失败", exc_info=True)
        return {"ok": False, "reason": f"create_new_table_failed: {exc}"}

    total = int(conn.execute(text("SELECT count(*) FROM library_index_entries")).scalar() or 0)
    copied = 0
    last_id: Optional[int] = None
    while True:
        if last_id is None:
            rows = conn.execute(text(
                """
                SELECT id, library_id, entry_type, name, relative_path, rjcode, parent_path
                  FROM library_index_entries
                 ORDER BY id
                 LIMIT :limit
                """
            ), {"limit": batch_size}).fetchall()
        else:
            rows = conn.execute(text(
                """
                SELECT id, library_id, entry_type, name, relative_path, rjcode, parent_path
                  FROM library_index_entries
                 WHERE id > :last_id
                 ORDER BY id
                 LIMIT :limit
                """
            ), {"last_id": last_id, "limit": batch_size}).fetchall()

        if not rows:
            break

        payload = [
            {
                "id": row[0],
                "library_id": row[1] or "",
                "entry_type": row[2] or "",
                "name": row[3] or "",
                "relative_path": row[4] or "",
                "rjcode": row[5] or "",
                "parent_path": row[6] or "",
            }
            for row in rows
        ]
        conn.execute(text(
            f"""
            INSERT INTO {new_table}(id, library_id, entry_type, name, relative_path, rjcode, parent_path)
            VALUES (:id, :library_id, :entry_type, :name, :relative_path, :rjcode, :parent_path)
            """
        ), payload)
        copied += len(payload)
        last_id = int(rows[-1][0])
        if progress_cb is not None:
            try:
                progress_cb(copied, total)
            except Exception:
                pass
        if len(rows) < batch_size:
            break

    _drop_fts_triggers(conn)
    try:
        conn.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE_NAME}"))
        conn.execute(text(f"ALTER TABLE {new_table} RENAME TO {FTS_TABLE_NAME}"))
        _create_fts_triggers(conn)
    except Exception as exc:
        logger.warning("[索引] 切换库存 FTS 新表失败", exc_info=True)
        _set_ready_hint(False)
        return {"ok": False, "reason": f"swap_failed: {exc}", "copied": copied, "total": total}

    _set_ready_hint(True)
    return {"ok": True, "tokenizer": target, "copied": copied, "total": total}


def rebuild_library_index_fts(
    *,
    target_tokenizer: str = FTS_PREFERRED_TOKENIZE,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    batch_size: int = 5000,
) -> Dict[str, Any]:
    from ...models.database import engine

    with engine.begin() as conn:
        return rebuild_library_index_fts_on_connection(
            conn,
            target_tokenizer=target_tokenizer,
            progress_cb=progress_cb,
            batch_size=batch_size,
        )


def _broadcast_library_fts_state(snapshot: Dict[str, Any]) -> None:
    try:
        from ..realtime_event_service import broadcast_event

        status = str(snapshot.get("state") or "idle")
        indexed = int(snapshot.get("indexed_entries") or 0)
        total = int(snapshot.get("total_entries") or 0)
        progress = 100 if status in {"done", "error"} else (min(99, int(indexed * 100 / total)) if total > 0 else 0)
        broadcast_event({
            "type": "maintenance.fts.changed",
            "reason": "library_index",
            "id": "library_index_fts",
            "domain": "maintenance",
            "status": status,
            "progress": progress,
            "current_step": "库存索引全文搜索重建中" if status == "running" else "",
            "payload": {
                "kind": "library_index",
                "rebuild": dict(snapshot),
            },
        })
    except Exception:
        logger.debug("[索引] 广播库存 FTS 实时状态失败", exc_info=True)


def _set_rebuild_state(**updates: Any) -> None:
    with _REBUILD_STATE_LOCK:
        _REBUILD_STATE.update(updates)
        snapshot = dict(_REBUILD_STATE)
    _broadcast_library_fts_state(snapshot)


def get_library_index_fts_rebuild_state() -> Dict[str, Any]:
    with _REBUILD_STATE_LOCK:
        return dict(_REBUILD_STATE)


def _library_index_fts_rebuild_worker(target_tokenizer: str) -> None:
    def _progress(copied: int, total: int) -> None:
        _set_rebuild_state(indexed_entries=int(copied), total_entries=int(total))

    try:
        result = rebuild_library_index_fts(
            target_tokenizer=target_tokenizer,
            progress_cb=_progress,
        )
        if result.get("ok"):
            _set_rebuild_state(
                state="done",
                tokenizer=str(result.get("tokenizer") or target_tokenizer),
                total_entries=int(result.get("total") or 0),
                indexed_entries=int(result.get("copied") or 0),
                finished_at=_now_iso(),
                error=None,
            )
        else:
            _set_rebuild_state(
                state="error",
                finished_at=_now_iso(),
                error=str(result.get("reason") or "unknown"),
            )
            _set_ready_hint(False)
    except Exception as exc:
        logger.warning("[索引] 库存 FTS 后台重建失败", exc_info=True)
        _set_rebuild_state(state="error", finished_at=_now_iso(), error=str(exc))
        _set_ready_hint(False)
    finally:
        try:
            _REBUILD_RUN_LOCK.release()
        except Exception:
            logger.debug("[索引] 库存 FTS 重建锁释放失败", exc_info=True)


def trigger_library_index_fts_rebuild(target_tokenizer: str = FTS_PREFERRED_TOKENIZE) -> Dict[str, Any]:
    """后台触发库存 FTS 重建；已在跑就返回当前状态。"""
    global _REBUILD_THREAD
    target = _normalize_tokenizer(target_tokenizer)
    if not _REBUILD_RUN_LOCK.acquire(blocking=False):
        return {
            "started": False,
            "already_running": True,
            "status": get_library_index_fts_rebuild_state(),
        }

    _set_rebuild_state(
        state="running",
        tokenizer=target,
        total_entries=0,
        indexed_entries=0,
        started_at=_now_iso(),
        finished_at=None,
        error=None,
    )
    thread = threading.Thread(
        target=_library_index_fts_rebuild_worker,
        args=(target,),
        name="library-index-fts-rebuild",
        daemon=True,
    )
    _REBUILD_THREAD = thread
    thread.start()
    return {
        "started": True,
        "already_running": False,
        "status": get_library_index_fts_rebuild_state(),
    }


def library_index_fts_status() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "fts_enabled": False,
        "tokenizer": "",
        "trigram_supported": False,
        "row_count": 0,
        "fts_row_count": 0,
        "needs_upgrade": False,
        "ready_hint": library_index_fts_ready_hint(),
    }
    try:
        from ...models.database import engine

        with engine.connect() as conn:
            info["fts_enabled"] = _table_exists(conn, FTS_TABLE_NAME)
            info["tokenizer"] = _read_fts_tokenizer(conn)
            info["trigram_supported"] = _detect_trigram_supported(conn)
            info["row_count"] = int(conn.execute(text("SELECT count(*) FROM library_index_entries")).scalar() or 0)
            if info["fts_enabled"]:
                info["fts_row_count"] = int(
                    conn.execute(text(f"SELECT count(*) FROM {FTS_TABLE_NAME}")).scalar() or 0
                )
    except Exception:
        logger.debug("[索引] 库存 FTS 状态检查失败", exc_info=True)

    info["needs_upgrade"] = bool(
        info["fts_enabled"]
        and info["trigram_supported"]
        and info["tokenizer"] != FTS_PREFERRED_TOKENIZE
    )
    return info
