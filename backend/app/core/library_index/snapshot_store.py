"""SnapshotStore：索引数据的 PostgreSQL CRUD 层。

职责边界：
- 只管读写 `library_index_entries` / `library_index_status` 两张表
- 不做扫描、不做路径解析、不做 RJ 号提取
- 上层 scanner / watcher 以 IndexEntry / WatcherEvent 为单位和本层交互

幂等语义：
- upsert 用 (library_id, relative_path) 判重
- bulk_upsert 会把同一库存同一相对路径的重复条目去重，保留最后一个
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator, Optional, Sequence, Union

from sqlalchemy import and_, case, func, or_, text
from sqlalchemy.orm import Session

from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexStatus,
    SessionLocal,
    library_index_name_sort_key,
)
from ..resource_budget_service import get_resource_budget_service
from ..ttl_cache import TTLCache
from .types import (
    IndexEntry,
    IndexStatus,
    IndexStatusName,
    WatcherMode,
)
logger = logging.getLogger(__name__)

_RJ_PREFIX_RE = re.compile(r"^(?:RJ)?\d{0,12}$", re.IGNORECASE)

_BULK_UPSERT_SQL = """
INSERT INTO library_index_entries (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
VALUES (
    :library_id,
    :entry_type,
    :relative_path,
    :absolute_path,
    :name,
    :name_sort_key,
    :rjcode,
    :parent_path,
    :size,
    :file_count,
    :mtime,
    :depth,
    :indexed_at
)
ON CONFLICT(library_id, relative_path) DO UPDATE SET
    entry_type = excluded.entry_type,
    absolute_path = excluded.absolute_path,
    name = excluded.name,
    name_sort_key = excluded.name_sort_key,
    rjcode = excluded.rjcode,
    parent_path = excluded.parent_path,
    size = excluded.size,
    file_count = excluded.file_count,
    mtime = excluded.mtime,
    depth = excluded.depth,
    indexed_at = excluded.indexed_at
WHERE library_index_entries.entry_type IS DISTINCT FROM excluded.entry_type
   OR library_index_entries.absolute_path IS DISTINCT FROM excluded.absolute_path
   OR library_index_entries.name IS DISTINCT FROM excluded.name
   OR library_index_entries.name_sort_key IS DISTINCT FROM excluded.name_sort_key
   OR library_index_entries.rjcode IS DISTINCT FROM excluded.rjcode
   OR library_index_entries.parent_path IS DISTINCT FROM excluded.parent_path
   OR library_index_entries.size IS DISTINCT FROM excluded.size
   OR library_index_entries.file_count IS DISTINCT FROM excluded.file_count
   OR library_index_entries.mtime IS DISTINCT FROM excluded.mtime
   OR library_index_entries.depth IS DISTINCT FROM excluded.depth
"""

_BULK_UNNEST_SOURCE_SQL = """
SELECT
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
FROM unnest(
    CAST(:library_ids AS text[]),
    CAST(:entry_types AS text[]),
    CAST(:relative_paths AS text[]),
    CAST(:absolute_paths AS text[]),
    CAST(:names AS text[]),
    CAST(:name_sort_keys AS text[]),
    CAST(:rjcodes AS text[]),
    CAST(:parent_paths AS text[]),
    CAST(:sizes AS bigint[]),
    CAST(:file_counts AS integer[]),
    CAST(:mtimes AS bigint[]),
    CAST(:depths AS integer[]),
    CAST(:indexed_ats AS bigint[])
) AS payload(
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
"""

_BULK_UPSERT_UNNEST_SQL = f"""
INSERT INTO library_index_entries (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
{_BULK_UNNEST_SOURCE_SQL}
ON CONFLICT(library_id, relative_path) DO UPDATE SET
    entry_type = excluded.entry_type,
    absolute_path = excluded.absolute_path,
    name = excluded.name,
    name_sort_key = excluded.name_sort_key,
    rjcode = excluded.rjcode,
    parent_path = excluded.parent_path,
    size = excluded.size,
    file_count = excluded.file_count,
    mtime = excluded.mtime,
    depth = excluded.depth,
    indexed_at = excluded.indexed_at
WHERE library_index_entries.entry_type IS DISTINCT FROM excluded.entry_type
   OR library_index_entries.absolute_path IS DISTINCT FROM excluded.absolute_path
   OR library_index_entries.name IS DISTINCT FROM excluded.name
   OR library_index_entries.name_sort_key IS DISTINCT FROM excluded.name_sort_key
   OR library_index_entries.rjcode IS DISTINCT FROM excluded.rjcode
   OR library_index_entries.parent_path IS DISTINCT FROM excluded.parent_path
   OR library_index_entries.size IS DISTINCT FROM excluded.size
   OR library_index_entries.file_count IS DISTINCT FROM excluded.file_count
   OR library_index_entries.mtime IS DISTINCT FROM excluded.mtime
   OR library_index_entries.depth IS DISTINCT FROM excluded.depth
"""

_BULK_INSERT_IGNORE_UNNEST_SQL = f"""
INSERT INTO library_index_entries (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
{_BULK_UNNEST_SOURCE_SQL}
ON CONFLICT(library_id, relative_path) DO NOTHING
"""

_REBUILD_STAGE_TABLE_NAME = "library_index_rebuild_stage"

_CREATE_REBUILD_STAGE_SQL = f"""
CREATE TEMP TABLE {_REBUILD_STAGE_TABLE_NAME} (
    library_id TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    relative_path TEXT PRIMARY KEY,
    absolute_path TEXT NOT NULL,
    name TEXT NOT NULL,
    name_sort_key TEXT NOT NULL DEFAULT '',
    rjcode TEXT,
    parent_path TEXT,
    size BIGINT NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    mtime BIGINT,
    depth INTEGER,
    indexed_at BIGINT NOT NULL
) ON COMMIT PRESERVE ROWS
"""

_REBUILD_STAGE_UPSERT_UNNEST_SQL = f"""
INSERT INTO {_REBUILD_STAGE_TABLE_NAME} (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
{_BULK_UNNEST_SOURCE_SQL}
ON CONFLICT(relative_path) DO UPDATE SET
    library_id = excluded.library_id,
    entry_type = excluded.entry_type,
    absolute_path = excluded.absolute_path,
    name = excluded.name,
    name_sort_key = excluded.name_sort_key,
    rjcode = excluded.rjcode,
    parent_path = excluded.parent_path,
    size = excluded.size,
    file_count = excluded.file_count,
    mtime = excluded.mtime,
    depth = excluded.depth,
    indexed_at = excluded.indexed_at
"""

_REBUILD_STAGE_STATS_SQL = f"""
SELECT
    count(*) AS total_entries,
    COALESCE(SUM(CASE WHEN entry_type = 'file' THEN size ELSE 0 END), 0) AS total_size_bytes,
    COALESCE(SUM(CASE
        WHEN entry_type = 'dir'
         AND relative_path != ''
         AND COALESCE(parent_path, '') = ''
        THEN 1
        ELSE 0
    END), 0) AS folder_count
FROM {_REBUILD_STAGE_TABLE_NAME}
WHERE library_id = :library_id
"""

_REBUILD_STAGE_ANALYZE_SQL = f"ANALYZE {_REBUILD_STAGE_TABLE_NAME}"

_REBUILD_STAGE_INSERT_NEW_CHUNK_SQL = f"""
INSERT INTO library_index_entries (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
    name_sort_key,
    rjcode,
    parent_path,
    size,
    file_count,
    mtime,
    depth,
    indexed_at
)
SELECT
    s.library_id,
    s.entry_type,
    s.relative_path,
    s.absolute_path,
    s.name,
    s.name_sort_key,
    s.rjcode,
    s.parent_path,
    s.size,
    s.file_count,
    s.mtime,
    s.depth,
    s.indexed_at
FROM {_REBUILD_STAGE_TABLE_NAME} s
WHERE s.library_id = :library_id
  AND NOT EXISTS (
      SELECT 1
        FROM library_index_entries AS existing
       WHERE existing.library_id = s.library_id
         AND existing.relative_path = s.relative_path
  )
ORDER BY s.relative_path
LIMIT :chunk_size
ON CONFLICT(library_id, relative_path) DO NOTHING
"""

_REBUILD_STAGE_UPDATE_CHANGED_CHUNK_SQL = f"""
WITH changed AS (
    SELECT
        staged.library_id,
        staged.entry_type,
        staged.relative_path,
        staged.absolute_path,
        staged.name,
        staged.name_sort_key,
        staged.rjcode,
        staged.parent_path,
        staged.size,
        staged.file_count,
        staged.mtime,
        staged.depth,
        staged.indexed_at
      FROM {_REBUILD_STAGE_TABLE_NAME} AS staged
      JOIN library_index_entries AS target
        ON target.library_id = staged.library_id
       AND target.relative_path = staged.relative_path
     WHERE target.library_id = :library_id
       AND staged.library_id = :library_id
       AND (
           target.entry_type IS DISTINCT FROM staged.entry_type
           OR target.absolute_path IS DISTINCT FROM staged.absolute_path
           OR target.name IS DISTINCT FROM staged.name
           OR target.name_sort_key IS DISTINCT FROM staged.name_sort_key
           OR target.rjcode IS DISTINCT FROM staged.rjcode
           OR target.parent_path IS DISTINCT FROM staged.parent_path
           OR target.size IS DISTINCT FROM staged.size
           OR target.file_count IS DISTINCT FROM staged.file_count
           OR target.mtime IS DISTINCT FROM staged.mtime
           OR target.depth IS DISTINCT FROM staged.depth
       )
     ORDER BY staged.relative_path
     LIMIT :chunk_size
)
UPDATE library_index_entries AS target
   SET entry_type = changed.entry_type,
       absolute_path = changed.absolute_path,
       name = changed.name,
       name_sort_key = changed.name_sort_key,
       rjcode = changed.rjcode,
       parent_path = changed.parent_path,
       size = changed.size,
       file_count = changed.file_count,
       mtime = changed.mtime,
       depth = changed.depth,
       indexed_at = changed.indexed_at
  FROM changed
 WHERE target.library_id = :library_id
   AND changed.library_id = :library_id
   AND target.relative_path = changed.relative_path
"""

_REBUILD_STAGE_DELETE_MISSING_CHUNK_SQL = f"""
DELETE FROM library_index_entries AS target
 WHERE target.id IN (
       SELECT stale.id
         FROM library_index_entries AS stale
        WHERE stale.library_id = :library_id
          AND NOT EXISTS (
              SELECT 1
                FROM {_REBUILD_STAGE_TABLE_NAME} AS staged
               WHERE staged.library_id = :library_id
                 AND staged.relative_path = stale.relative_path
          )
        ORDER BY stale.id ASC
        LIMIT :chunk_size
 )
"""

DEFAULT_BULK_UPSERT_CHUNK_SIZE = 500
DEFAULT_SELF_MUTATION_DELETE_CHUNK_SIZE = 200
DEFAULT_SELF_MUTATION_MOVE_CHUNK_SIZE = 50
DIRECT_CHILD_TOTAL_CACHE_TTL_SECONDS = 10.0
DIRECT_CHILD_TOTAL_CACHE_MAX_SIZE = 4096
DIRECT_CHILD_PAGE_CURSOR_VERSION = 1


def _now_ms() -> int:
    return int(time.time() * 1000)


def _has_surrogate(value: str) -> bool:
    return any('\ud800' <= char <= '\udfff' for char in value)


def _database_safe_text(value: Optional[str]) -> Optional[str]:
    """PostgreSQL 只能接收合法 UTF-8；本地坏文件名里的 surrogate 要转义后再入库。"""
    if value is None or not _has_surrogate(value):
        return value
    return value.encode('utf-8', 'backslashreplace').decode('utf-8')


def _database_safe_entry(entry: IndexEntry) -> IndexEntry:
    safe_relative = _database_safe_text(entry.relative_path) or ''
    safe_absolute = _database_safe_text(entry.absolute_path) or ''
    safe_name = _database_safe_text(entry.name) or ''
    safe_parent = _database_safe_text(entry.parent_path)
    if (
        safe_relative == entry.relative_path
        and safe_absolute == entry.absolute_path
        and safe_name == entry.name
        and safe_parent == entry.parent_path
    ):
        return entry
    logger.warning(
        "[索引] 路径包含非法 UTF-8 字节，已转义后写入索引 library=%s path=%r",
        entry.library_id,
        safe_relative or safe_absolute or safe_name,
    )
    return replace(
        entry,
        relative_path=safe_relative,
        absolute_path=safe_absolute,
        name=safe_name,
        parent_path=safe_parent,
    )


class SnapshotStore:
    """索引快照 CRUD。"""

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory
        self._children_total_cache = TTLCache(
            max_size=DIRECT_CHILD_TOTAL_CACHE_MAX_SIZE,
            ttl_seconds=DIRECT_CHILD_TOTAL_CACHE_TTL_SECONDS,
            name="library_index.children_total",
        )

    @property
    def bind_engine(self):
        return (getattr(self._session_factory, "kw", {}) or {}).get("bind")

    @contextmanager
    def _write_session(
        self,
        *,
        relaxed_commit: bool = False,
        invalidate_children_total_cache: bool = True,
    ) -> Iterator[Session]:
        with get_resource_budget_service().acquire_sync("database_write", reason="library_index.write"):
            db = self._session_factory()
            try:
                if relaxed_commit:
                    db.execute(text("SET LOCAL synchronous_commit = off"))
                yield db
                db.commit()
                if invalidate_children_total_cache:
                    self._invalidate_children_total_cache()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    @contextmanager
    def _read_session(self) -> Iterator[Session]:
        db = self._session_factory()
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _children_total_cache_key(
        library_id: str,
        parent_path: Optional[str],
        entry_type: Optional[str],
    ) -> str:
        return f"{library_id}\0{parent_path or ''}\0{entry_type or ''}"

    def _invalidate_children_total_cache(self, library_id: Optional[str] = None) -> None:
        if library_id:
            self._children_total_cache.invalidate_prefix(f"{library_id}\0")
        else:
            self._children_total_cache.clear()

    def _count_direct_children(
        self,
        db: Session,
        library_id: str,
        parent_path: Optional[str],
        entry_type: Optional[str],
        q,
    ) -> int:
        cache_key = self._children_total_cache_key(library_id, parent_path, entry_type)
        cached = self._children_total_cache.get(cache_key)
        if cached is not None:
            return int(cached)
        total = int(q.with_entities(func.count(LibraryIndexEntry.id)).scalar() or 0)
        self._children_total_cache.set(cache_key, total)
        return total

    @staticmethod
    def _encode_direct_child_page_cursor(
        *,
        library_id: str,
        parent_path: Optional[str],
        entry_type: Optional[str],
        sort_by: str,
        sort_order: str,
        row: LibraryIndexEntry,
    ) -> str:
        payload = {
            "v": DIRECT_CHILD_PAGE_CURSOR_VERSION,
            "l": str(library_id or ""),
            "p": str(parent_path or ""),
            "e": str(entry_type or ""),
            "s": str(sort_by or "name"),
            "o": str(sort_order or "asc"),
            "k": {
                "n": str(row.name_sort_key or library_index_name_sort_key(row.name)),
                "r": str(row.relative_path or ""),
                "z": int(row.size or 0),
                "t": None if row.mtime is None else int(row.mtime),
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_direct_child_page_cursor(
        page_cursor: Optional[str],
        *,
        library_id: str,
        parent_path: Optional[str],
        entry_type: Optional[str],
        sort_by: str,
        sort_order: str,
    ) -> Optional[dict[str, object]]:
        if not page_cursor:
            return None
        token = str(page_cursor or "").strip()
        if not token or len(token) > 2048:
            return None
        try:
            padded = token + ("=" * (-len(token) % 4))
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("v") != DIRECT_CHILD_PAGE_CURSOR_VERSION:
            return None
        if (
            payload.get("l") != str(library_id or "")
            or payload.get("p") != str(parent_path or "")
            or payload.get("e") != str(entry_type or "")
            or payload.get("s") != str(sort_by or "name")
            or payload.get("o") != str(sort_order or "asc")
        ):
            return None
        key = payload.get("k")
        return key if isinstance(key, dict) else None

    @staticmethod
    def _direct_child_secondary_after_condition(cursor_key: dict[str, object]):
        last_name_sort_key = str(cursor_key.get("n") or "")
        last_relative_path = str(cursor_key.get("r") or "")
        return or_(
            LibraryIndexEntry.name_sort_key > last_name_sort_key,
            and_(
                LibraryIndexEntry.name_sort_key == last_name_sort_key,
                LibraryIndexEntry.relative_path > last_relative_path,
            ),
        )

    @classmethod
    def _direct_child_keyset_after_condition(
        cls,
        sort_by: str,
        sort_order: str,
        cursor_key: dict[str, object],
    ):
        secondary_after = cls._direct_child_secondary_after_condition(cursor_key)
        descending = str(sort_order or "asc").lower() == "desc"
        normalized_sort_by = str(sort_by or "name").lower()

        if normalized_sort_by == "size":
            try:
                last_size = int(cursor_key.get("z") or 0)
            except Exception:
                last_size = 0
            primary_after = (
                LibraryIndexEntry.size < last_size
                if descending
                else LibraryIndexEntry.size > last_size
            )
            return or_(
                primary_after,
                and_(LibraryIndexEntry.size == last_size, secondary_after),
            )

        if normalized_sort_by == "time":
            raw_mtime = cursor_key.get("t")
            try:
                last_mtime = None if raw_mtime is None else int(raw_mtime)
            except Exception:
                last_mtime = None
            if last_mtime is None:
                return and_(LibraryIndexEntry.mtime.is_(None), secondary_after)
            primary_after = (
                LibraryIndexEntry.mtime < last_mtime
                if descending
                else LibraryIndexEntry.mtime > last_mtime
            )
            return or_(
                primary_after,
                and_(LibraryIndexEntry.mtime == last_mtime, secondary_after),
                LibraryIndexEntry.mtime.is_(None),
            )

        last_name_sort_key = str(cursor_key.get("n") or "")
        primary_after = (
            LibraryIndexEntry.name_sort_key < last_name_sort_key
            if descending
            else LibraryIndexEntry.name_sort_key > last_name_sort_key
        )
        return or_(
            primary_after,
            and_(
                LibraryIndexEntry.name_sort_key == last_name_sort_key,
                LibraryIndexEntry.relative_path > str(cursor_key.get("r") or ""),
            ),
        )

    # ========== Entry 写入 ==========

    def upsert(self, entry: IndexEntry) -> None:
        """写入或更新一行索引，(library_id, relative_path) 作为自然主键。"""
        with self._write_session() as db:
            entry = _database_safe_entry(entry)
            old = self._get_existing_stats_map(db, entry.library_id, [entry.relative_path])
            old_size, old_folders = old.get(entry.relative_path, (0, 0))
            new_size, new_folders = self._entry_stats(entry)
            self._upsert_one(db, entry)
            self._apply_status_delta(
                db,
                entry.library_id,
                size_delta=new_size - old_size,
                folder_delta=new_folders - old_folders,
                entry_delta=0 if entry.relative_path in old else 1,
            )

    def bulk_upsert(
        self,
        entries: Iterable[IndexEntry],
        *,
        chunk_size: int = DEFAULT_BULK_UPSERT_CHUNK_SIZE,
        maintain_status_stats: bool = True,
        insert_only: bool = False,
        relaxed_commit: bool = False,
    ) -> int:
        """批量写入 / 更新，返回实际写入条数。

        主路径使用 PostgreSQL 数组 unnest + UPSERT，避免逐条 SELECT + ORM 物化。
        全量首建可传 insert_only=True，空库首次导入时少走 UPDATE 分支。
        异常环境下回退 `_upsert_one()`，保证用户现场可用。
        """
        deduped: dict[tuple[str, str], IndexEntry] = {}
        for item in entries:
            safe_item = _database_safe_entry(item)
            deduped[(safe_item.library_id, safe_item.relative_path)] = safe_item
        if not deduped:
            return 0

        chunk_size = max(1, int(chunk_size or DEFAULT_BULK_UPSERT_CHUNK_SIZE))
        payload = list(deduped.values())
        try:
            with self._write_session(relaxed_commit=relaxed_commit) as db:
                affected_total = 0
                deltas = (
                    self._build_bulk_upsert_status_deltas(db, payload, insert_only=insert_only)
                    if maintain_status_stats else {}
                )
                for i in range(0, len(payload), chunk_size):
                    chunk = payload[i:i + chunk_size]
                    sql = _BULK_INSERT_IGNORE_UNNEST_SQL if insert_only else _BULK_UPSERT_UNNEST_SQL
                    result = db.execute(
                        text(sql),
                        self._chunk_to_unnest_params(chunk),
                    )
                    affected = int(result.rowcount or 0)
                    affected_total += affected if affected >= 0 else len(chunk)
                for library_id, delta in deltas.items():
                    self._apply_status_delta(
                        db,
                        library_id,
                        size_delta=delta["size"],
                        folder_delta=delta["folders"],
                        entry_delta=delta["entries"],
                    )
            return affected_total
        except Exception:
            logger.warning("[索引] 原生批量 UPSERT 失败，回退逐条写入", exc_info=True)

        written = 0
        with self._write_session(relaxed_commit=relaxed_commit) as db:
            deltas = (
                self._build_bulk_upsert_status_deltas(db, payload, insert_only=insert_only)
                if maintain_status_stats else {}
            )
            for item in payload:
                if insert_only:
                    exists = (
                        db.query(LibraryIndexEntry.id)
                        .filter(
                            LibraryIndexEntry.library_id == item.library_id,
                            LibraryIndexEntry.relative_path == item.relative_path,
                        )
                        .first()
                    )
                    if exists:
                        continue
                if self._upsert_one(db, item):
                    written += 1
            for library_id, delta in deltas.items():
                self._apply_status_delta(
                    db,
                    library_id,
                    size_delta=delta["size"],
                    folder_delta=delta["folders"],
                    entry_delta=delta["entries"],
                )
        return written

    def create_rebuild_writer(
        self,
        library_id: str,
        *,
        chunk_size: int = DEFAULT_BULK_UPSERT_CHUNK_SIZE,
        relaxed_commit: bool = False,
    ) -> "SnapshotRebuildWriter":
        return SnapshotRebuildWriter(
            self,
            library_id,
            chunk_size=chunk_size,
            relaxed_commit=relaxed_commit,
        )

    def _upsert_one(self, db: Session, entry: IndexEntry) -> bool:
        entry = _database_safe_entry(entry)
        row = (
            db.query(LibraryIndexEntry)
            .filter(
                LibraryIndexEntry.library_id == entry.library_id,
                LibraryIndexEntry.relative_path == entry.relative_path,
            )
            .first()
        )
        indexed_at = entry.indexed_at or _now_ms()
        if row is None:
            row = LibraryIndexEntry(
                library_id=entry.library_id,
                entry_type=entry.entry_type,
                relative_path=entry.relative_path,
                absolute_path=entry.absolute_path,
                name=entry.name,
                name_sort_key=library_index_name_sort_key(entry.name),
                rjcode=entry.rjcode,
                parent_path=entry.parent_path,
                size=entry.size or 0,
                file_count=entry.file_count or 0,
                mtime=entry.mtime,
                depth=entry.depth,
                indexed_at=indexed_at,
            )
            db.add(row)
            return True
        else:
            if not self._row_differs_from_entry(row, entry):
                return False
            row.entry_type = entry.entry_type
            row.absolute_path = entry.absolute_path
            row.name = entry.name
            row.name_sort_key = library_index_name_sort_key(entry.name)
            row.rjcode = entry.rjcode
            row.parent_path = entry.parent_path
            row.size = entry.size or 0
            row.file_count = entry.file_count or 0
            row.mtime = entry.mtime
            row.depth = entry.depth
            row.indexed_at = indexed_at
            return True

    @staticmethod
    def _row_differs_from_entry(row: LibraryIndexEntry, entry: IndexEntry) -> bool:
        return (
            row.entry_type != entry.entry_type
            or row.absolute_path != entry.absolute_path
            or row.name != entry.name
            or row.name_sort_key != library_index_name_sort_key(entry.name)
            or row.rjcode != entry.rjcode
            or row.parent_path != entry.parent_path
            or int(row.size or 0) != int(entry.size or 0)
            or int(row.file_count or 0) != int(entry.file_count or 0)
            or row.mtime != entry.mtime
            or row.depth != entry.depth
        )

    @staticmethod
    def _entry_to_upsert_params(entry: IndexEntry) -> dict:
        return {
            "library_id": entry.library_id,
            "entry_type": entry.entry_type,
            "relative_path": entry.relative_path,
            "absolute_path": entry.absolute_path,
            "name": entry.name,
            "name_sort_key": library_index_name_sort_key(entry.name),
            "rjcode": entry.rjcode,
            "parent_path": entry.parent_path,
            "size": entry.size or 0,
            "file_count": entry.file_count or 0,
            "mtime": entry.mtime,
            "depth": entry.depth,
            "indexed_at": entry.indexed_at or _now_ms(),
        }

    @classmethod
    def _chunk_to_unnest_params(cls, entries: Sequence[IndexEntry]) -> dict:
        rows = [cls._entry_to_upsert_params(entry) for entry in entries]
        return {
            "library_ids": [row["library_id"] for row in rows],
            "entry_types": [row["entry_type"] for row in rows],
            "relative_paths": [row["relative_path"] for row in rows],
            "absolute_paths": [row["absolute_path"] for row in rows],
            "names": [row["name"] for row in rows],
            "name_sort_keys": [row["name_sort_key"] for row in rows],
            "rjcodes": [row["rjcode"] for row in rows],
            "parent_paths": [row["parent_path"] for row in rows],
            "sizes": [row["size"] for row in rows],
            "file_counts": [row["file_count"] for row in rows],
            "mtimes": [row["mtime"] for row in rows],
            "depths": [row["depth"] for row in rows],
            "indexed_ats": [row["indexed_at"] for row in rows],
        }

    @staticmethod
    def _entry_stats(entry: IndexEntry) -> tuple[int, int]:
        if entry.entry_type == 'file':
            return max(0, int(entry.size or 0)), 0
        if (
            entry.entry_type == 'dir'
            and bool(entry.relative_path)
            and (entry.parent_path or '') == ''
        ):
            return 0, 1
        return 0, 0

    @staticmethod
    def _row_stats(row: LibraryIndexEntry) -> tuple[int, int]:
        if row.entry_type == 'file':
            return max(0, int(row.size or 0)), 0
        if (
            row.entry_type == 'dir'
            and bool(row.relative_path)
            and (row.parent_path or '') == ''
        ):
            return 0, 1
        return 0, 0

    @staticmethod
    def _stats_from_values(
        entry_type: str,
        relative_path: str,
        parent_path: Optional[str],
        size: int,
    ) -> tuple[int, int]:
        if entry_type == 'file':
            return max(0, int(size or 0)), 0
        if entry_type == 'dir' and bool(relative_path) and (parent_path or '') == '':
            return 0, 1
        return 0, 0

    def _get_existing_stats_map(
        self,
        db: Session,
        library_id: str,
        relative_paths: Iterable[str],
    ) -> dict[str, tuple[int, int]]:
        paths = list(dict.fromkeys(relative_paths))
        if not paths:
            return {}
        result: dict[str, tuple[int, int]] = {}
        chunk_size = 500
        for i in range(0, len(paths), chunk_size):
            rows = (
                db.query(
                    LibraryIndexEntry.relative_path,
                    LibraryIndexEntry.entry_type,
                    LibraryIndexEntry.size,
                    LibraryIndexEntry.parent_path,
                )
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.relative_path.in_(paths[i:i + chunk_size]),
                )
                .all()
            )
            for row in rows:
                result[row.relative_path] = self._stats_from_values(
                    row.entry_type,
                    row.relative_path,
                    row.parent_path,
                    row.size,
                )
        return result

    def _build_bulk_upsert_status_deltas(
        self,
        db: Session,
        payload: list[IndexEntry],
        *,
        insert_only: bool = False,
    ) -> dict[str, dict[str, int]]:
        by_library: dict[str, list[IndexEntry]] = {}
        for item in payload:
            by_library.setdefault(item.library_id, []).append(item)

        deltas: dict[str, dict[str, int]] = {}
        for library_id, items in by_library.items():
            old = self._get_existing_stats_map(
                db,
                library_id,
                [item.relative_path for item in items],
            )
            size_delta = 0
            folder_delta = 0
            entry_delta = 0
            for item in items:
                if insert_only and item.relative_path in old:
                    continue
                old_size, old_folders = old.get(item.relative_path, (0, 0))
                new_size, new_folders = self._entry_stats(item)
                size_delta += new_size - old_size
                folder_delta += new_folders - old_folders
                if item.relative_path not in old:
                    entry_delta += 1
            if size_delta or folder_delta or entry_delta:
                deltas[library_id] = {
                    "size": size_delta,
                    "folders": folder_delta,
                    "entries": entry_delta,
                }
        return deltas

    def _apply_status_delta(
        self,
        db: Session,
        library_id: str,
        *,
        size_delta: int = 0,
        folder_delta: int = 0,
        entry_delta: int = 0,
        accumulator: Optional[dict[str, dict[str, int]]] = None,
    ) -> None:
        if not (size_delta or folder_delta or entry_delta):
            return
        if accumulator is not None:
            bucket = accumulator.setdefault(
                library_id,
                {"size": 0, "folders": 0, "entries": 0},
            )
            bucket["size"] += int(size_delta or 0)
            bucket["folders"] += int(folder_delta or 0)
            bucket["entries"] += int(entry_delta or 0)
            return
        row = (
            db.query(LibraryIndexStatus)
            .filter(LibraryIndexStatus.library_id == library_id)
            .first()
        )
        if row is None or row.status not in {'ready', 'syncing'}:
            return
        row.total_size_bytes = max(0, int(row.total_size_bytes or 0) + int(size_delta or 0))
        row.folder_count = max(0, int(row.folder_count or 0) + int(folder_delta or 0))
        row.total_entries = max(0, int(row.total_entries or 0) + int(entry_delta or 0))
        row.updated_at = _now_ms()
        db.flush()
        self._broadcast_status_change(self._row_to_status(row), reason="library_index_delta")

    def _flush_status_deltas(
        self,
        db: Session,
        accumulator: dict[str, dict[str, int]],
    ) -> None:
        for library_id, delta in accumulator.items():
            self._apply_status_delta(
                db,
                library_id,
                size_delta=delta.get("size", 0),
                folder_delta=delta.get("folders", 0),
                entry_delta=delta.get("entries", 0),
            )

    def _query_stats_delta(self, q) -> tuple[int, int, int]:
        row = q.with_entities(
            func.coalesce(
                func.sum(
                    case(
                        (LibraryIndexEntry.entry_type == 'file', LibraryIndexEntry.size),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (
                                (LibraryIndexEntry.entry_type == 'dir')
                                & (LibraryIndexEntry.relative_path != '')
                                & (func.coalesce(LibraryIndexEntry.parent_path, '') == '')
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.count(LibraryIndexEntry.id),
        ).first()
        total_size = int(row[0] if row else 0)
        folder_count = int(row[1] if row else 0)
        entry_count = int(row[2] if row else 0)
        return max(0, total_size), max(0, folder_count), max(0, entry_count)

    @staticmethod
    def _normalize_relative_path(value: Optional[str]) -> str:
        return str(value or "").strip("/")

    @classmethod
    def _compress_relative_subtree_paths(cls, paths: Iterable[str]) -> list[str]:
        """去掉已被父目录覆盖的子路径，减少批量删除时的 OR 条件和索引探测次数。"""
        unique = sorted(
            dict.fromkeys(
                normalized
                for item in paths
                if (normalized := cls._normalize_relative_path(item))
            ),
            key=lambda value: (value.count("/"), value),
        )
        kept: list[str] = []
        kept_set: set[str] = set()
        for path in unique:
            parent = path
            covered = False
            while "/" in parent:
                parent = parent.rsplit("/", 1)[0]
                if parent in kept_set:
                    covered = True
                    break
            if not covered:
                kept.append(path)
                kept_set.add(path)
        return kept

    @staticmethod
    def _escape_like_literal(value: str) -> str:
        return str(value or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")

    @classmethod
    def _subtree_like_pattern(cls, relative_path: str) -> str:
        return f"{cls._escape_like_literal(relative_path)}/%"

    @classmethod
    def _subtree_column_condition(cls, column, relative_path: str):
        return or_(
            column == relative_path,
            column.like(cls._subtree_like_pattern(relative_path), escape="!"),
        )

    @staticmethod
    def _relative_parent(relative_path: str) -> str:
        value = str(relative_path or "").strip("/")
        if "/" not in value:
            return ""
        return value.rsplit("/", 1)[0]

    @staticmethod
    def _relative_name(relative_path: str) -> str:
        value = str(relative_path or "").strip("/")
        if not value:
            return ""
        return value.rsplit("/", 1)[-1]

    @staticmethod
    def _relative_depth(relative_path: str) -> int:
        value = str(relative_path or "").strip("/")
        return 0 if not value else value.count("/") + 1

    @staticmethod
    def _replace_prefix(value: Optional[str], old_prefix: str, new_prefix: str) -> str:
        current = str(value or "")
        if current == old_prefix:
            return new_prefix
        if old_prefix and current.startswith(old_prefix):
            return new_prefix + current[len(old_prefix):]
        return current

    def _subtree_query(self, db: Session, library_id: str, relative_path: str):
        normalized = self._normalize_relative_path(relative_path)
        q = db.query(LibraryIndexEntry).filter(LibraryIndexEntry.library_id == library_id)
        if not normalized:
            return q
        return q.filter(self._subtree_column_condition(LibraryIndexEntry.relative_path, normalized))

    def _delete_subtree_in_session(
        self,
        db: Session,
        library_id: str,
        relative_path: str,
        *,
        status_delta_accumulator: Optional[dict[str, dict[str, int]]] = None,
    ) -> tuple[int, int, int, int]:
        q = self._subtree_query(db, library_id, relative_path)
        total_size, folder_count, entry_count = self._query_stats_delta(q)
        deleted = q.delete(synchronize_session=False)
        self._apply_status_delta(
            db,
            library_id,
            size_delta=-total_size,
            folder_delta=-folder_count,
            entry_delta=-entry_count,
            accumulator=status_delta_accumulator,
        )
        return deleted, total_size, folder_count, entry_count

    def _transform_subtree_entry(
        self,
        entry: IndexEntry,
        *,
        target_library_id: str,
        old_relative: str,
        new_relative: str,
        old_absolute: str,
        new_absolute: str,
        depth_delta: int,
        indexed_at: int,
    ) -> IndexEntry:
        next_relative = self._replace_prefix(entry.relative_path, old_relative, new_relative)
        next_absolute = self._replace_prefix(entry.absolute_path, old_absolute, new_absolute)
        if entry.relative_path == old_relative:
            next_parent = self._relative_parent(new_relative)
            next_name = self._relative_name(new_relative) or entry.name
        else:
            next_parent = self._replace_prefix(entry.parent_path, old_relative, new_relative)
            next_name = entry.name
        next_depth = None if entry.depth is None else max(0, int(entry.depth or 0) + depth_delta)
        return replace(
            entry,
            library_id=target_library_id,
            relative_path=next_relative,
            absolute_path=next_absolute,
            parent_path=next_parent,
            name=next_name,
            depth=next_depth,
            indexed_at=indexed_at,
        )

    def _move_subtree_same_library_in_session(
        self,
        db: Session,
        library_id: str,
        *,
        old_relative_path: str,
        new_relative_path: str,
        old_absolute_path: str,
        new_absolute_path: str,
        status_delta_accumulator: Optional[dict[str, dict[str, int]]] = None,
    ) -> int:
        old_rel = self._normalize_relative_path(old_relative_path)
        new_rel = self._normalize_relative_path(new_relative_path)
        if not old_rel or not new_rel or old_rel == new_rel:
            return 0
        old_abs = str(old_absolute_path or "")
        new_abs = str(new_absolute_path or "")
        if not old_abs or not new_abs:
            return 0

        new_parent = self._relative_parent(new_rel)
        new_name = self._relative_name(new_rel)
        new_name_sort_key = library_index_name_sort_key(new_name)
        depth_delta = self._relative_depth(new_rel) - self._relative_depth(old_rel)
        now = _now_ms()
        root_row = (
            db.query(LibraryIndexEntry)
            .filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.relative_path == old_rel,
            )
            .first()
        )
        if root_row is None:
            return 0
        old_size, old_folders = self._row_stats(root_row)
        moved_root = self._transform_subtree_entry(
            self._row_to_entry(root_row),
            target_library_id=library_id,
            old_relative=old_rel,
            new_relative=new_rel,
            old_absolute=old_abs,
            new_absolute=new_abs,
            depth_delta=depth_delta,
            indexed_at=now,
        )
        new_size, new_folders = self._entry_stats(moved_root)

        deleted, target_size, target_folders, target_entries = self._delete_subtree_in_session(
            db,
            library_id,
            new_rel,
            status_delta_accumulator=status_delta_accumulator,
        )

        result = db.execute(
            text(
                """
                UPDATE library_index_entries
                   SET relative_path = CASE
                           WHEN relative_path = :old_rel THEN :new_rel
                           ELSE :new_rel || substr(relative_path, :old_rel_suffix_start)
                       END,
                       absolute_path = CASE
                           WHEN absolute_path = :old_abs THEN :new_abs
                           ELSE :new_abs || substr(absolute_path, :old_abs_suffix_start)
                       END,
                       parent_path = CASE
                           WHEN relative_path = :old_rel THEN :new_parent
                           WHEN parent_path = :old_rel THEN :new_rel
                           WHEN parent_path LIKE :old_child_like ESCAPE '!'
                               THEN :new_rel || substr(parent_path, :old_rel_suffix_start)
                           ELSE parent_path
                       END,
                       name = CASE
                           WHEN relative_path = :old_rel THEN :new_name
                           ELSE name
                       END,
                       name_sort_key = CASE
                           WHEN relative_path = :old_rel THEN :new_name_sort_key
                           ELSE name_sort_key
                       END,
                       depth = CASE
                           WHEN depth IS NULL THEN NULL
                           ELSE depth + :depth_delta
                       END,
                       indexed_at = :indexed_at
                 WHERE library_id = :library_id
                   AND (
                       relative_path = :old_rel
                       OR (
                           relative_path LIKE :old_child_like ESCAPE '!'
                       )
                   )
                """
            ),
            {
                "library_id": library_id,
                "old_rel": old_rel,
                "new_rel": new_rel,
                "old_abs": old_abs,
                "new_abs": new_abs,
                "new_parent": new_parent,
                "new_name": new_name,
                "new_name_sort_key": new_name_sort_key,
                "old_child_like": self._subtree_like_pattern(old_rel),
                "old_rel_suffix_start": len(old_rel) + 1,
                "old_abs_suffix_start": len(old_abs) + 1,
                "depth_delta": depth_delta,
                "indexed_at": now,
            },
        )
        moved = int(result.rowcount or 0)
        if moved:
            self._apply_status_delta(
                db,
                library_id,
                size_delta=new_size - old_size,
                folder_delta=new_folders - old_folders,
                entry_delta=0,
                accumulator=status_delta_accumulator,
            )
        elif deleted:
            logger.warning(
                "[索引] 同库移动 fast-path 未命中旧子树，但已删除目标旧索引 library=%s old=%s new=%s",
                library_id,
                old_rel,
                new_rel,
            )
        return moved

    def move_subtree_same_library(
        self,
        library_id: str,
        *,
        old_relative_path: str,
        new_relative_path: str,
        old_absolute_path: str,
        new_absolute_path: str,
    ) -> int:
        """同库移动索引 fast-path：单条 UPDATE 改写子树路径，不扫磁盘。"""
        with self._write_session() as db:
            status_deltas: dict[str, dict[str, int]] = {}
            moved = self._move_subtree_same_library_in_session(
                db,
                library_id,
                old_relative_path=old_relative_path,
                new_relative_path=new_relative_path,
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
                status_delta_accumulator=status_deltas,
            )
            self._flush_status_deltas(db, status_deltas)
            return moved

    def move_subtrees_same_library(
        self,
        library_id: str,
        moves: Iterable[dict[str, str]],
        *,
        chunk_size: int = DEFAULT_SELF_MUTATION_MOVE_CHUNK_SIZE,
    ) -> list[int]:
        """同库批量移动索引 fast-path：按小批提交，避免千级移动形成长事务。"""
        items = list(moves or [])
        if not items:
            return []
        results: list[int] = []
        chunk_size = max(1, int(chunk_size or DEFAULT_SELF_MUTATION_MOVE_CHUNK_SIZE))
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            with self._write_session() as db:
                status_deltas: dict[str, dict[str, int]] = {}
                for item in chunk:
                    moved = self._move_subtree_same_library_in_session(
                        db,
                        library_id,
                        old_relative_path=str(item.get("old_relative_path") or ""),
                        new_relative_path=str(item.get("new_relative_path") or ""),
                        old_absolute_path=str(item.get("old_absolute_path") or ""),
                        new_absolute_path=str(item.get("new_absolute_path") or ""),
                        status_delta_accumulator=status_deltas,
                    )
                    results.append(moved)
                self._flush_status_deltas(db, status_deltas)
        return results

    def _move_subtree_between_libraries_in_session(
        self,
        db: Session,
        source_library_id: str,
        target_library_id: str,
        *,
        old_relative_path: str,
        new_relative_path: str,
        old_absolute_path: str,
        new_absolute_path: str,
        status_delta_accumulator: Optional[dict[str, dict[str, int]]] = None,
    ) -> int:
        old_rel = self._normalize_relative_path(old_relative_path)
        new_rel = self._normalize_relative_path(new_relative_path)
        if not old_rel or not new_rel:
            return 0
        old_abs = str(old_absolute_path or "")
        new_abs = str(new_absolute_path or "")
        if not old_abs or not new_abs:
            return 0

        depth_delta = self._relative_depth(new_rel) - self._relative_depth(old_rel)
        now = _now_ms()
        new_parent = self._relative_parent(new_rel)
        new_name = self._relative_name(new_rel)
        new_name_sort_key = library_index_name_sort_key(new_name)
        source_q = self._subtree_query(db, source_library_id, old_rel)
        source_size, _source_folders, source_entries = self._query_stats_delta(source_q)
        if not source_entries:
            return 0

        source_root = (
            db.query(LibraryIndexEntry.entry_type)
            .filter(
                LibraryIndexEntry.library_id == source_library_id,
                LibraryIndexEntry.relative_path == old_rel,
            )
            .first()
        )
        inserted_top_folders = (
            1
            if source_root is not None
            and source_root[0] == 'dir'
            and new_parent == ''
            else 0
        )

        _, target_size, target_folders, target_entries = self._delete_subtree_in_session(
            db,
            target_library_id,
            new_rel,
            status_delta_accumulator=status_delta_accumulator,
        )

        insert_result = db.execute(
            text(
                """
                INSERT INTO library_index_entries (
                    library_id,
                    entry_type,
                    relative_path,
                    absolute_path,
                    name,
                    name_sort_key,
                    rjcode,
                    parent_path,
                    size,
                    file_count,
                    mtime,
                    depth,
                    indexed_at
                )
                SELECT
                    :target_library_id,
                    entry_type,
                    CASE
                        WHEN relative_path = :old_rel THEN :new_rel
                        ELSE :new_rel || substr(relative_path, :old_rel_suffix_start)
                    END,
                    CASE
                        WHEN absolute_path = :old_abs THEN :new_abs
                        ELSE :new_abs || substr(absolute_path, :old_abs_suffix_start)
                    END,
                    CASE
                        WHEN relative_path = :old_rel THEN :new_name
                        ELSE name
                    END,
                    CASE
                        WHEN relative_path = :old_rel THEN :new_name_sort_key
                        ELSE name_sort_key
                    END,
                    rjcode,
                    CASE
                        WHEN relative_path = :old_rel THEN :new_parent
                        WHEN parent_path = :old_rel THEN :new_rel
                        WHEN parent_path LIKE :old_child_like ESCAPE '!'
                            THEN :new_rel || substr(parent_path, :old_rel_suffix_start)
                        ELSE parent_path
                    END,
                    size,
                    file_count,
                    mtime,
                    CASE
                        WHEN depth IS NULL THEN NULL
                        ELSE depth + :depth_delta
                    END,
                    :indexed_at
                FROM library_index_entries
                WHERE library_id = :source_library_id
                  AND (
                      relative_path = :old_rel
                      OR (
                          relative_path LIKE :old_child_like ESCAPE '!'
                      )
                  )
                """
            ),
            {
                "source_library_id": source_library_id,
                "target_library_id": target_library_id,
                "old_rel": old_rel,
                "new_rel": new_rel,
                "old_abs": old_abs,
                "new_abs": new_abs,
                "new_parent": new_parent,
                "new_name": new_name,
                "new_name_sort_key": new_name_sort_key,
                "old_child_like": self._subtree_like_pattern(old_rel),
                "old_rel_suffix_start": len(old_rel) + 1,
                "old_abs_suffix_start": len(old_abs) + 1,
                "depth_delta": depth_delta,
                "indexed_at": now,
            },
        )
        inserted = int(insert_result.rowcount or source_entries)

        self._delete_subtree_in_session(
            db,
            source_library_id,
            old_rel,
            status_delta_accumulator=status_delta_accumulator,
        )

        self._apply_status_delta(
            db,
            target_library_id,
            size_delta=source_size,
            folder_delta=inserted_top_folders,
            entry_delta=inserted,
            accumulator=status_delta_accumulator,
        )
        return inserted

    def move_subtree_between_libraries(
        self,
        source_library_id: str,
        target_library_id: str,
        *,
        old_relative_path: str,
        new_relative_path: str,
        old_absolute_path: str,
        new_absolute_path: str,
        chunk_size: int = 500,
    ) -> int:
        """跨库移动索引 fast-path：数据库内 INSERT...SELECT 搬迁，不扫磁盘。"""
        with self._write_session() as db:
            status_deltas: dict[str, dict[str, int]] = {}
            moved = self._move_subtree_between_libraries_in_session(
                db,
                source_library_id,
                target_library_id,
                old_relative_path=old_relative_path,
                new_relative_path=new_relative_path,
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
                status_delta_accumulator=status_deltas,
            )
            self._flush_status_deltas(db, status_deltas)
            return moved

    def move_subtrees_between_libraries(
        self,
        source_library_id: str,
        target_library_id: str,
        moves: Iterable[dict[str, str]],
        *,
        chunk_size: int = DEFAULT_SELF_MUTATION_MOVE_CHUNK_SIZE,
    ) -> list[int]:
        """跨库批量移动索引 fast-path：按小批提交，避免千级移动形成长事务。"""
        items = list(moves or [])
        if not items:
            return []
        results: list[int] = []
        chunk_size = max(1, int(chunk_size or DEFAULT_SELF_MUTATION_MOVE_CHUNK_SIZE))
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            with self._write_session() as db:
                status_deltas: dict[str, dict[str, int]] = {}
                for item in chunk:
                    moved = self._move_subtree_between_libraries_in_session(
                        db,
                        source_library_id,
                        target_library_id,
                        old_relative_path=str(item.get("old_relative_path") or ""),
                        new_relative_path=str(item.get("new_relative_path") or ""),
                        old_absolute_path=str(item.get("old_absolute_path") or ""),
                        new_absolute_path=str(item.get("new_absolute_path") or ""),
                        status_delta_accumulator=status_deltas,
                    )
                    results.append(moved)
                self._flush_status_deltas(db, status_deltas)
        return results

    # ========== Entry 删除 ==========

    def delete_by_relative_path(self, library_id: str, relative_path: str) -> int:
        """删除单行。"""
        with self._write_session() as db:
            q = (
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.relative_path == relative_path,
                )
            )
            total_size, folder_count, entry_count = self._query_stats_delta(q)
            deleted = q.delete(synchronize_session=False)
            self._apply_status_delta(
                db,
                library_id,
                size_delta=-total_size,
                folder_delta=-folder_count,
                entry_delta=-entry_count,
            )
            return deleted

    def delete_subtree(self, library_id: str, relative_path: str) -> int:
        """删除指定 relative_path 自身 + 所有后代。

        watcher 处理目录删除 / 重命名时调用。
        """
        if relative_path is None:
            return 0
        normalized = relative_path.strip('/')
        with self._write_session() as db:
            q = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
            )
            if normalized:
                q = q.filter(self._subtree_column_condition(LibraryIndexEntry.relative_path, normalized))
            total_size, folder_count, entry_count = self._query_stats_delta(q)
            deleted = q.delete(synchronize_session=False)
            self._apply_status_delta(
                db,
                library_id,
                size_delta=-total_size,
                folder_delta=-folder_count,
                entry_delta=-entry_count,
            )
            return deleted

    def delete_library(self, library_id: str) -> int:
        """整库清空（rebuild 前调用）。"""
        with self._write_session() as db:
            return (
                db.query(LibraryIndexEntry)
                .filter(LibraryIndexEntry.library_id == library_id)
                .delete(synchronize_session=False)
            )

    def delete_stale_library_entries(
        self,
        library_id: str,
        *,
        indexed_before_ms: int,
        chunk_size: int = 500,
        relaxed_commit: bool = False,
    ) -> int:
        """分块删除全量重建后未被本轮扫描刷新到的旧行。

        rebuild 主路径会先 upsert 新快照，再按 indexed_at 边界清 stale。
        这里故意不用一条大 DELETE，避免数据库写入和索引维护长时间占用。
        """
        chunk_size = max(1, int(chunk_size or 500))
        cutoff = int(indexed_before_ms or 0)
        deleted_total = 0
        started = time.time()
        while True:
            with self._write_session(relaxed_commit=relaxed_commit) as db:
                rows = (
                    db.query(LibraryIndexEntry.id)
                    .filter(
                        LibraryIndexEntry.library_id == library_id,
                        LibraryIndexEntry.indexed_at < cutoff,
                    )
                    .order_by(LibraryIndexEntry.id.asc())
                    .limit(chunk_size)
                    .all()
                )
                ids = [row.id for row in rows]
                if not ids:
                    break
                deleted = (
                    db.query(LibraryIndexEntry)
                    .filter(LibraryIndexEntry.id.in_(ids))
                    .delete(synchronize_session=False)
                )
                deleted_total += int(deleted or 0)
            if deleted_total and deleted_total % (chunk_size * 10) == 0:
                logger.info(
                    "[索引] stale 分块清理中 library=%s deleted=%s cutoff=%s",
                    library_id,
                    deleted_total,
                    cutoff,
                )
        if deleted_total:
            logger.info(
                "[索引] stale 分块清理完成 library=%s deleted=%s elapsed=%.2fs cutoff=%s",
                library_id,
                deleted_total,
                time.time() - started,
                cutoff,
            )
        return deleted_total

    def analyze_entries_for_query_planner(
        self,
        *,
        lock_timeout_ms: int = 500,
        clean_trigram_pending: bool = False,
    ) -> bool:
        """全量重建后刷新 PostgreSQL 统计信息。

        新增第二个库存时，主表已经不是空表，不能暂停二级索引；几十万行插入后
        主动 ANALYZE 一次，避免搜索和子树查询短时间内按旧行数估算。
        大批导入后可顺手清理 GIN pending list，避免刚建完索引后的第一次模糊搜索
        额外扫描大量 pending 页面；日常千级 self-mutation 不走这里。
        """
        engine = self.bind_engine
        if engine is None:
            return False
        from ...models.database import (
            _POSTGRES_LIBRARY_TRIGRAM_INDEX_NAMES,
            configure_postgres_online_maintenance_connection,
            release_postgres_online_maintenance_lock,
        )

        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        lock_acquired = False
        try:
            lock_acquired = configure_postgres_online_maintenance_connection(
                conn,
                lock_timeout_ms=lock_timeout_ms,
            )
            if not lock_acquired:
                return False
            conn.execute(text("ANALYZE library_index_entries"))
            if clean_trigram_pending:
                for name in _POSTGRES_LIBRARY_TRIGRAM_INDEX_NAMES:
                    exists = bool(
                        conn.execute(
                            text("SELECT to_regclass(:name) IS NOT NULL"),
                            {"name": name},
                        ).scalar()
                    )
                    if exists:
                        conn.execute(
                            text("SELECT gin_clean_pending_list(:name)"),
                            {"name": name},
                        )
            return True
        except Exception:
            logger.debug("[索引] ANALYZE library_index_entries 跳过", exc_info=True)
            return False
        finally:
            if lock_acquired:
                try:
                    release_postgres_online_maintenance_lock(conn)
                except Exception:
                    logger.debug("[索引] 释放库存索引维护锁失败", exc_info=True)
            conn.close()

    # ========== Entry 查询 ==========

    def find_by_rjcode(
        self,
        library_id: Optional[Union[str, Sequence[str]]],
        rjcode: str,
        *,
        entry_type: Optional[str] = 'dir',
        limit: int = 100,
    ) -> list[IndexEntry]:
        """按 RJ 号精确查。

        library_id：
        - str → 仅该库存
        - None / 空序列 → 跨全部库存
        - Sequence[str] → 多库存（IN 子查询）
        """
        if not rjcode:
            return []
        scope_ids: Optional[list[str]]
        if library_id is None:
            scope_ids = None
        elif isinstance(library_id, str):
            scope_ids = [library_id] if library_id else None
        else:
            scope_ids = [str(item) for item in library_id if item]
            if not scope_ids:
                scope_ids = None
        with self._read_session() as db:
            q = db.query(LibraryIndexEntry)
            filters = [LibraryIndexEntry.rjcode == rjcode]
            if scope_ids:
                if len(scope_ids) == 1:
                    filters.append(LibraryIndexEntry.library_id == scope_ids[0])
                else:
                    filters.append(LibraryIndexEntry.library_id.in_(scope_ids))
            if entry_type:
                filters.append(LibraryIndexEntry.entry_type == entry_type)
            # 稳定命中 idx_lie_rj_lookup；该 partial 索引只覆盖有 RJ 号的行，
            # 避免几十万普通文件行拖慢重建和日常 upsert。
            q = q.filter(*filters)
            q = q.order_by(
                LibraryIndexEntry.depth.asc(),
                LibraryIndexEntry.relative_path.asc(),
            )
            return [self._row_to_entry(row) for row in q.limit(limit).all()]

    def find_by_name(
        self,
        library_id: Optional[Union[str, Sequence[str]]],
        name_like: str,
        *,
        entry_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[IndexEntry]:
        """按名称 / 路径 / RJ 号模糊搜索。

        关键性能优化：
        - PostgreSQL pg_trgm 索引加速 ILIKE，适合中文子串、文件名片段、
          相对路径片段和 RJ 号搜索。

        library_id：
        - str → 仅该库存
        - None / 空序列 → 跨全部库存（库存维度由调用方上层保证可见性）
        - Sequence[str] → 多库存命中（IN 子查询）
        """
        if not name_like:
            return []
        scope_ids = self._normalize_scope_ids(library_id)
        with self._read_session() as db:
            return self._find_by_name_like(
                db,
                scope_ids,
                name_like,
                entry_type=entry_type,
                limit=limit,
            )

    def _find_by_name_like(
        self,
        db: Session,
        scope_ids: Optional[list[str]],
        name_like: str,
        *,
        entry_type: Optional[str],
        limit: int,
    ) -> list[IndexEntry]:
        rj_prefix = self._normalize_rj_prefix_query(name_like)
        if rj_prefix:
            return self._find_by_rj_prefix(
                db,
                scope_ids,
                rj_prefix,
                entry_type=entry_type,
                limit=limit,
            )
        # 转义 SQL 通配符，让用户输入的 _ % ! 真正只匹配自身。
        # 查询表达式必须和 idx_library_index_search_text_trgm 保持一致，PostgreSQL
        # 才能用单个 GIN trigram 索引覆盖 name/path/rjcode/parent_path 的模糊搜索。
        escaped = name_like.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        pattern = f"%{escaped}%"
        q = db.query(LibraryIndexEntry).filter(
            text(
                """
                (COALESCE(name, '') || ' ' ||
                 COALESCE(relative_path, '') || ' ' ||
                 COALESCE(rjcode, '') || ' ' ||
                 COALESCE(parent_path, '')) ILIKE :library_index_pattern ESCAPE '!'
                """
            ).bindparams(library_index_pattern=pattern)
        )
        if scope_ids:
            if len(scope_ids) == 1:
                q = q.filter(LibraryIndexEntry.library_id == scope_ids[0])
            else:
                q = q.filter(LibraryIndexEntry.library_id.in_(scope_ids))
        if entry_type:
            q = q.filter(LibraryIndexEntry.entry_type == entry_type)
        q = q.order_by(
            LibraryIndexEntry.depth.asc(),
            LibraryIndexEntry.name_sort_key.asc(),
            LibraryIndexEntry.relative_path.asc(),
        )
        return [self._row_to_entry(row) for row in q.limit(limit).all()]

    @staticmethod
    def _normalize_rj_prefix_query(value: str) -> Optional[str]:
        text_value = str(value or "").strip().upper().replace(" ", "")
        if not text_value or not _RJ_PREFIX_RE.match(text_value):
            return None
        if text_value.startswith("RJ"):
            return text_value
        if len(text_value) < 4:
            return None
        return f"RJ{text_value}"

    def _find_by_rj_prefix(
        self,
        db: Session,
        scope_ids: Optional[list[str]],
        rj_prefix: str,
        *,
        entry_type: Optional[str],
        limit: int,
    ) -> list[IndexEntry]:
        # 短 RJ 前缀（RJ / RJ12 / 123456）用 text_pattern_ops btree，避免
        # trigram 在短 pattern 上退化成几十万行顺序扫。
        q = db.query(LibraryIndexEntry).filter(
            LibraryIndexEntry.rjcode.like(f"{rj_prefix}%")
        )
        if scope_ids:
            if len(scope_ids) == 1:
                q = q.filter(LibraryIndexEntry.library_id == scope_ids[0])
            else:
                q = q.filter(LibraryIndexEntry.library_id.in_(scope_ids))
        if entry_type:
            q = q.filter(LibraryIndexEntry.entry_type == entry_type)
        q = q.order_by(
            LibraryIndexEntry.depth.asc(),
            LibraryIndexEntry.relative_path.asc(),
            LibraryIndexEntry.library_id.asc(),
        )
        return [self._row_to_entry(row) for row in q.limit(limit).all()]

    def list_children(
        self,
        library_id: str,
        parent_path: Optional[str],
        *,
        entry_type: Optional[str] = None,
        sort_by: str = "name",
        sort_order: str = "asc",
        offset: int = 0,
        limit: Optional[int] = None,
        include_total: bool = False,
    ) -> list[IndexEntry]:
        """列指定 parent_path 的直接子项。parent_path='' 表示库根的一级子项。"""
        return self.list_children_page(
            library_id,
            parent_path,
            entry_type=entry_type,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=limit,
            include_total=include_total,
        )["entries"]

    def list_children_page(
        self,
        library_id: str,
        parent_path: Optional[str],
        *,
        entry_type: Optional[str] = None,
        sort_by: str = "name",
        sort_order: str = "asc",
        offset: int = 0,
        limit: Optional[int] = 200,
        include_total: bool = True,
        page_cursor: Optional[str] = None,
    ) -> dict[str, object]:
        """分页列指定 parent_path 的直接子项。

        目录浏览热路径专用：排序和分页下推到 PostgreSQL，避免把大目录全量拉回
        Python 后再切片。`page_cursor` 用于连续翻页的 keyset 快路径，跳页继续
        走 offset 兼容老分页。
        """
        with self._read_session() as db:
            q = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.parent_path == (parent_path or ''),
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            total = (
                self._count_direct_children(db, library_id, parent_path, entry_type, q)
                if include_total
                else None
            )
            normalized_sort_by = str(sort_by or "name").lower()
            normalized_sort_order = "desc" if str(sort_order or "asc").lower() == "desc" else "asc"
            descending = normalized_sort_order == "desc"
            cursor_key = self._decode_direct_child_page_cursor(
                page_cursor,
                library_id=library_id,
                parent_path=parent_path,
                entry_type=entry_type,
                sort_by=normalized_sort_by,
                sort_order=normalized_sort_order,
            )
            if cursor_key:
                q = q.filter(
                    self._direct_child_keyset_after_condition(
                        normalized_sort_by,
                        normalized_sort_order,
                        cursor_key,
                    )
                )
            if normalized_sort_by == "time":
                primary = LibraryIndexEntry.mtime.desc() if descending else LibraryIndexEntry.mtime.asc()
                q = q.order_by(
                    primary.nullslast(),
                    LibraryIndexEntry.name_sort_key.asc(),
                    LibraryIndexEntry.relative_path.asc(),
                )
            elif normalized_sort_by == "size":
                primary = LibraryIndexEntry.size.desc() if descending else LibraryIndexEntry.size.asc()
                q = q.order_by(
                    primary,
                    LibraryIndexEntry.name_sort_key.asc(),
                    LibraryIndexEntry.relative_path.asc(),
                )
            else:
                primary = LibraryIndexEntry.name_sort_key.desc() if descending else LibraryIndexEntry.name_sort_key.asc()
                q = q.order_by(
                    primary,
                    LibraryIndexEntry.relative_path.asc(),
                )
            if not cursor_key:
                q = q.offset(max(0, int(offset or 0)))
            if limit is not None:
                q = q.limit(max(1, int(limit or 1)))
            rows = q.all()
            next_page_cursor = None
            if rows and limit is not None and len(rows) >= max(1, int(limit or 1)):
                next_page_cursor = self._encode_direct_child_page_cursor(
                    library_id=library_id,
                    parent_path=parent_path,
                    entry_type=entry_type,
                    sort_by=normalized_sort_by,
                    sort_order=normalized_sort_order,
                    row=rows[-1],
                )
            return {
                "entries": [self._row_to_entry(row) for row in rows],
                "total": total,
                "next_page_cursor": next_page_cursor,
                "used_page_cursor": bool(cursor_key),
            }

    def get_entry(self, library_id: str, relative_path: str) -> Optional[IndexEntry]:
        with self._read_session() as db:
            row = (
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.relative_path == relative_path,
                )
                .first()
            )
            return self._row_to_entry(row) if row else None

    def sum_library_size(self, library_id: str) -> int:
        """库存所有文件条目的总大小（字节）。目录行不累加，避免重复计数。"""
        with self._read_session() as db:
            total = (
                db.query(func.coalesce(func.sum(LibraryIndexEntry.size), 0))
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.entry_type == 'file',
                )
                .scalar()
            )
            return int(total or 0)

    def get_library_stats(
        self,
        library_id: str,
        *,
        parent_path: Optional[str] = '',
    ) -> dict[str, int]:
        """读取持久化聚合快照。

        parent_path 参数保留给旧调用方兼容；聚合快照按库存根维护，不在统计接口
        热路径上重新按目录过滤 / SUM。
        """
        with self._read_session() as db:
            row = (
                db.query(LibraryIndexStatus)
                .filter(LibraryIndexStatus.library_id == library_id)
                .first()
            )
            if row is None:
                return {"folder_count": 0, "total_size_bytes": 0}
            return {
                "folder_count": int(row.folder_count or 0),
                "total_size_bytes": int(row.total_size_bytes or 0),
            }

    def count_library_entries(
        self,
        library_id: str,
        *,
        entry_type: Optional[str] = None,
    ) -> int:
        with self._read_session() as db:
            q = db.query(func.count(LibraryIndexEntry.id)).filter(
                LibraryIndexEntry.library_id == library_id,
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            return int(q.scalar() or 0)

    def has_library_entries(
        self,
        library_id: str,
        *,
        entry_type: Optional[str] = None,
    ) -> bool:
        """判断某个库存是否已有索引行；重建前只需要存在性，不做 count(*)。"""
        with self._read_session() as db:
            q = db.query(LibraryIndexEntry.id).filter(
                LibraryIndexEntry.library_id == library_id,
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            return q.limit(1).first() is not None

    def has_any_entries(self) -> bool:
        """判断索引表是否已有任何业务行。

        这里刻意不用 count(*)：第二个库存加入时表里可能已经有几十万行，
        EXISTS/LIMIT 1 能避免为了首建快路径判断扫大表。
        """
        with self._read_session() as db:
            return (
                db.query(LibraryIndexEntry.id)
                .limit(1)
                .first()
                is not None
            )

    # ========== Status ==========

    def get_status(self, library_id: str) -> Optional[IndexStatus]:
        with self._read_session() as db:
            row = (
                db.query(LibraryIndexStatus)
                .filter(LibraryIndexStatus.library_id == library_id)
                .first()
            )
            return self._row_to_status(row) if row else None

    def upsert_status(
        self,
        library_id: str,
        *,
        status: Optional[IndexStatusName] = None,
        watcher_mode: Optional[WatcherMode] = None,
        last_full_scan_at: Optional[int] = None,
        last_event_at: Optional[int] = None,
        total_entries: Optional[int] = None,
        total_size_bytes: Optional[int] = None,
        folder_count: Optional[int] = None,
        error: Optional[str] = ...,  # type: ignore[assignment]
    ) -> IndexStatus:
        """写入状态。error 默认省略不动；显式传 None 才会清空。"""
        now = _now_ms()
        with self._write_session(invalidate_children_total_cache=False) as db:
            row = (
                db.query(LibraryIndexStatus)
                .filter(LibraryIndexStatus.library_id == library_id)
                .first()
            )
            if row is None:
                row = LibraryIndexStatus(
                    library_id=library_id,
                    status=status or 'idle',
                    watcher_mode=watcher_mode,
                    last_full_scan_at=last_full_scan_at,
                    last_event_at=last_event_at,
                    total_entries=total_entries or 0,
                    total_size_bytes=total_size_bytes or 0,
                    folder_count=folder_count or 0,
                    error=error if error is not ... else None,
                    updated_at=now,
                )
                db.add(row)
            else:
                if status is not None:
                    row.status = status
                if watcher_mode is not None:
                    row.watcher_mode = watcher_mode
                if last_full_scan_at is not None:
                    row.last_full_scan_at = last_full_scan_at
                if last_event_at is not None:
                    row.last_event_at = last_event_at
                if total_entries is not None:
                    row.total_entries = total_entries
                if total_size_bytes is not None:
                    row.total_size_bytes = max(0, int(total_size_bytes or 0))
                if folder_count is not None:
                    row.folder_count = max(0, int(folder_count or 0))
                if error is not ...:
                    row.error = error
                row.updated_at = now
            db.flush()
            snapshot = self._row_to_status(row)
            self._broadcast_status_change(snapshot, reason="library_index_status")
        return snapshot

    def delete_status(self, library_id: str) -> int:
        with self._write_session(invalidate_children_total_cache=False) as db:
            return (
                db.query(LibraryIndexStatus)
                .filter(LibraryIndexStatus.library_id == library_id)
                .delete(synchronize_session=False)
            )

    def delete_subtrees(
        self,
        library_id: str,
        relative_paths: Iterable[str],
        *,
        chunk_size: int = DEFAULT_SELF_MUTATION_DELETE_CHUNK_SIZE,
    ) -> int:
        """批量删除多个子树（自身 + 所有后代），按小批提交。

        每个 path 的匹配规则与 delete_subtree 一致：
        relative_path == p OR p + '/' <= relative_path < p + '0'

        超过 chunk_size 个路径时分批提交，避免 SQL 过长和长事务拖住业务查询。
        """
        paths = self._compress_relative_subtree_paths(
            p for p in relative_paths if p is not None
        )
        if not paths:
            return 0
        chunk_size = max(1, int(chunk_size or DEFAULT_SELF_MUTATION_DELETE_CHUNK_SIZE))
        deleted = 0
        for i in range(0, len(paths), chunk_size):
            chunk = paths[i:i + chunk_size]
            conditions = []
            for p in chunk:
                conditions.append(self._subtree_column_condition(LibraryIndexEntry.relative_path, p))
            if not conditions:
                continue
            with self._write_session() as db:
                q = (
                    db.query(LibraryIndexEntry)
                    .filter(LibraryIndexEntry.library_id == library_id)
                    .filter(or_(*conditions))
                )
                total_size, folder_count, entry_count = self._query_stats_delta(q)
                deleted += q.delete(synchronize_session=False)
                self._apply_status_delta(
                    db,
                    library_id,
                    size_delta=-total_size,
                    folder_delta=-folder_count,
                    entry_delta=-entry_count,
                )
        return deleted

    def list_all_status(self) -> list[IndexStatus]:
        with self._read_session() as db:
            rows = db.query(LibraryIndexStatus).all()
            return [self._row_to_status(row) for row in rows]

    # ========== helpers ==========

    @staticmethod
    def _row_to_entry(row: LibraryIndexEntry) -> IndexEntry:
        return IndexEntry(
            library_id=row.library_id,
            entry_type=row.entry_type,
            relative_path=row.relative_path,
            absolute_path=row.absolute_path,
            name=row.name,
            rjcode=row.rjcode,
            parent_path=row.parent_path,
            size=int(row.size or 0),
            file_count=int(row.file_count or 0),
            mtime=row.mtime,
            depth=row.depth,
            indexed_at=int(row.indexed_at or 0),
        )

    @staticmethod
    def _mapping_to_entry(row) -> IndexEntry:
        return IndexEntry(
            library_id=row["library_id"],
            entry_type=row["entry_type"],
            relative_path=row["relative_path"],
            absolute_path=row["absolute_path"],
            name=row["name"],
            rjcode=row["rjcode"],
            parent_path=row["parent_path"],
            size=int(row["size"] or 0),
            file_count=int(row["file_count"] or 0),
            mtime=row["mtime"],
            depth=row["depth"],
            indexed_at=int(row["indexed_at"] or 0),
        )

    @staticmethod
    def _normalize_scope_ids(
        library_id: Optional[Union[str, Sequence[str]]],
    ) -> Optional[list[str]]:
        if library_id is None:
            return None
        if isinstance(library_id, str):
            return [library_id] if library_id else None
        scope_ids = [str(item) for item in library_id if item]
        return scope_ids or None

    @staticmethod
    def _row_to_status(row: LibraryIndexStatus) -> IndexStatus:
        return IndexStatus(
            library_id=row.library_id,
            status=row.status,
            watcher_mode=row.watcher_mode,
            last_full_scan_at=row.last_full_scan_at,
            last_event_at=row.last_event_at,
            total_entries=int(row.total_entries or 0),
            total_size_bytes=int(row.total_size_bytes or 0),
            folder_count=int(row.folder_count or 0),
            error=row.error,
            updated_at=int(row.updated_at or 0),
        )

    @staticmethod
    def _broadcast_status_change(status: IndexStatus, *, reason: str) -> None:
        try:
            from ..task_center_event_service import broadcast_library_index_status_changed

            broadcast_library_index_status_changed(status, reason=reason)
        except Exception:
            logger.debug("[索引] 广播状态变更失败 library=%s", status.library_id, exc_info=True)


class SnapshotRebuildWriter:
    """重复全量重建专用：先写临时快照表，再差量合并主表。

    连接会被固定到 writer 生命周期，但每批 stage 都独立提交；扫描几十万文件时
    不持有长事务，也不会因为未变化行刷新 indexed_at 而放大 GIN/btree 写入。
    """

    def __init__(
        self,
        store: SnapshotStore,
        library_id: str,
        *,
        chunk_size: int = DEFAULT_BULK_UPSERT_CHUNK_SIZE,
        relaxed_commit: bool = False,
    ):
        self._store = store
        self.library_id = str(library_id or "")
        self.chunk_size = max(1, int(chunk_size or DEFAULT_BULK_UPSERT_CHUNK_SIZE))
        self.relaxed_commit = bool(relaxed_commit)
        self._engine = store.bind_engine
        self._conn = None
        self._closed = False
        self.staged_rows = 0
        if self._engine is None:
            raise RuntimeError("SnapshotRebuildWriter 需要绑定 PostgreSQL engine")

    def __enter__(self) -> "SnapshotRebuildWriter":
        self._conn = self._engine.connect()
        self._execute_write(lambda conn: conn.execute(text(f"DROP TABLE IF EXISTS {_REBUILD_STAGE_TABLE_NAME}")))
        self._execute_write(lambda conn: conn.execute(text(_CREATE_REBUILD_STAGE_SQL)))
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _execute_write(self, fn):
        if self._conn is None:
            raise RuntimeError("SnapshotRebuildWriter 尚未初始化")
        with get_resource_budget_service().acquire_sync("database_write", reason="library_index.rebuild_stage"):
            with self._conn.begin():
                if self.relaxed_commit:
                    self._conn.execute(text("SET LOCAL synchronous_commit = off"))
                return fn(self._conn)

    def stage(self, entries: Iterable[IndexEntry]) -> int:
        deduped: dict[str, IndexEntry] = {}
        for item in entries:
            safe_item = _database_safe_entry(item)
            if safe_item.library_id != self.library_id:
                raise ValueError(
                    f"重建快照写入器只接受 library={self.library_id}，收到 {safe_item.library_id}"
                )
            deduped[safe_item.relative_path] = safe_item
        if not deduped:
            return 0
        payload = list(deduped.values())

        def _stage(conn):
            affected_total = 0
            for i in range(0, len(payload), self.chunk_size):
                chunk = payload[i:i + self.chunk_size]
                result = conn.execute(
                    text(_REBUILD_STAGE_UPSERT_UNNEST_SQL),
                    SnapshotStore._chunk_to_unnest_params(chunk),
                )
                affected = int(result.rowcount or 0)
                affected_total += affected if affected >= 0 else len(chunk)
            return affected_total

        affected_total = int(self._execute_write(_stage) or 0)
        self.staged_rows += affected_total
        return affected_total

    def finish(self, *, delete_chunk_size: Optional[int] = None) -> dict[str, int]:
        chunk_size = max(1, int(delete_chunk_size or self.chunk_size))

        def _prepare_merge(conn):
            conn.execute(text(_REBUILD_STAGE_ANALYZE_SQL))
            stats_row = conn.execute(
                text(_REBUILD_STAGE_STATS_SQL),
                {"library_id": self.library_id},
            ).mappings().first() or {}
            return {
                "staged": int(stats_row.get("total_entries") or 0),
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "total_entries": int(stats_row.get("total_entries") or 0),
                "total_size_bytes": int(stats_row.get("total_size_bytes") or 0),
                "folder_count": int(stats_row.get("folder_count") or 0),
            }

        result = self._execute_write(_prepare_merge)
        inserted_total = 0
        while True:
            inserted = int(
                self._execute_write(
                    lambda conn: conn.execute(
                        text(_REBUILD_STAGE_INSERT_NEW_CHUNK_SQL),
                        {
                            "library_id": self.library_id,
                            "chunk_size": chunk_size,
                        },
                    ).rowcount or 0
                )
            )
            if not inserted:
                break
            inserted_total += inserted
            if inserted_total and inserted_total % (chunk_size * 10) == 0:
                logger.info(
                    "[索引] staging 新增分块合并中 library=%s inserted=%s",
                    self.library_id,
                    inserted_total,
                )

        updated_total = 0
        while True:
            updated = int(
                self._execute_write(
                    lambda conn: conn.execute(
                        text(_REBUILD_STAGE_UPDATE_CHANGED_CHUNK_SQL),
                        {
                            "library_id": self.library_id,
                            "chunk_size": chunk_size,
                        },
                    ).rowcount or 0
                )
            )
            if not updated:
                break
            updated_total += updated
            if updated_total and updated_total % (chunk_size * 10) == 0:
                logger.info(
                    "[索引] staging 变更分块合并中 library=%s updated=%s",
                    self.library_id,
                    updated_total,
                )

        deleted_total = 0
        while True:
            deleted = int(
                self._execute_write(
                    lambda conn: conn.execute(
                        text(_REBUILD_STAGE_DELETE_MISSING_CHUNK_SQL),
                        {
                            "library_id": self.library_id,
                            "chunk_size": chunk_size,
                        },
                    ).rowcount or 0
                )
            )
            if not deleted:
                break
            deleted_total += deleted
            if deleted_total and deleted_total % (chunk_size * 10) == 0:
                logger.info(
                    "[索引] staging stale 分块清理中 library=%s deleted=%s",
                    self.library_id,
                    deleted_total,
                )
        if deleted_total:
            logger.info(
                "[索引] staging stale 分块清理完成 library=%s deleted=%s",
                self.library_id,
                deleted_total,
            )
        if inserted_total or updated_total or deleted_total:
            self._store._invalidate_children_total_cache(self.library_id)
            self._store.analyze_entries_for_query_planner(clean_trigram_pending=True)
        result["inserted"] = inserted_total
        result["updated"] = updated_total
        result["deleted"] = deleted_total
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            with conn.begin():
                conn.execute(text(f"DROP TABLE IF EXISTS {_REBUILD_STAGE_TABLE_NAME}"))
        except Exception:
            logger.debug("[索引] 清理重建临时表失败", exc_info=True)
        finally:
            conn.close()


_default_store: Optional[SnapshotStore] = None


def get_snapshot_store() -> SnapshotStore:
    """进程内单例访问器。"""
    global _default_store
    if _default_store is None:
        _default_store = SnapshotStore()
    return _default_store
