"""SnapshotStore：索引数据的 SQLite CRUD 层。

职责边界：
- 只管读写 `library_index_entries` / `library_index_status` 两张表
- 不做扫描、不做路径解析、不做 RJ 号提取
- 上层 scanner / watcher 以 IndexEntry / WatcherEvent 为单位和本层交互

幂等语义：
- upsert 用 (library_id, relative_path) 判重
- bulk_upsert 会把同一库存同一相对路径的重复条目去重，保留最后一个
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator, Optional, Sequence, Union

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexStatus,
    SessionLocal,
)
from ..resource_budget_service import get_resource_budget_service
from .types import (
    IndexEntry,
    IndexStatus,
    IndexStatusName,
    WatcherMode,
)
from .fts import (
    FTS_TABLE_NAME,
    build_library_index_fts_match_expression,
    library_index_fts_enabled,
    library_index_fts_ready_hint,
    read_library_index_fts_tokenizer,
    sanitize_library_index_search_text,
)

logger = logging.getLogger(__name__)

_BULK_UPSERT_SQL = """
INSERT INTO library_index_entries (
    library_id,
    entry_type,
    relative_path,
    absolute_path,
    name,
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
    rjcode = excluded.rjcode,
    parent_path = excluded.parent_path,
    size = excluded.size,
    file_count = excluded.file_count,
    mtime = excluded.mtime,
    depth = excluded.depth,
    indexed_at = excluded.indexed_at
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _has_surrogate(value: str) -> bool:
    return any('\ud800' <= char <= '\udfff' for char in value)


def _sqlite_safe_text(value: Optional[str]) -> Optional[str]:
    """SQLite 只能接收合法 UTF-8；本地坏文件名里的 surrogate 要转义后再入库。"""
    if value is None or not _has_surrogate(value):
        return value
    return value.encode('utf-8', 'backslashreplace').decode('utf-8')


def _sqlite_safe_entry(entry: IndexEntry) -> IndexEntry:
    safe_relative = _sqlite_safe_text(entry.relative_path) or ''
    safe_absolute = _sqlite_safe_text(entry.absolute_path) or ''
    safe_name = _sqlite_safe_text(entry.name) or ''
    safe_parent = _sqlite_safe_text(entry.parent_path)
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

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with get_resource_budget_service().acquire_sync("sqlite_write", reason="library_index.write"):
            db = self._session_factory()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    # ========== Entry 写入 ==========

    def upsert(self, entry: IndexEntry) -> None:
        """写入或更新一行索引，(library_id, relative_path) 作为自然主键。"""
        with self._session() as db:
            entry = _sqlite_safe_entry(entry)
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
        chunk_size: int = 500,
        maintain_status_stats: bool = True,
    ) -> int:
        """批量写入 / 更新，返回实际写入条数。

        主路径使用 SQLite 原生 UPSERT，避免逐条 SELECT + ORM 物化。
        旧 SQLite / 异常环境下回退 `_upsert_one()`，保证用户现场可用。
        """
        deduped: dict[tuple[str, str], IndexEntry] = {}
        for item in entries:
            safe_item = _sqlite_safe_entry(item)
            deduped[(safe_item.library_id, safe_item.relative_path)] = safe_item
        if not deduped:
            return 0

        chunk_size = max(1, int(chunk_size or 500))
        payload = list(deduped.values())
        try:
            with self._session() as db:
                deltas = (
                    self._build_bulk_upsert_status_deltas(db, payload)
                    if maintain_status_stats else {}
                )
                for i in range(0, len(payload), chunk_size):
                    chunk = payload[i:i + chunk_size]
                    db.execute(
                        text(_BULK_UPSERT_SQL),
                        [self._entry_to_upsert_params(item) for item in chunk],
                    )
                for library_id, delta in deltas.items():
                    self._apply_status_delta(
                        db,
                        library_id,
                        size_delta=delta["size"],
                        folder_delta=delta["folders"],
                        entry_delta=delta["entries"],
                    )
            return len(payload)
        except Exception:
            logger.warning("[索引] 原生批量 UPSERT 失败，回退逐条写入", exc_info=True)

        written = 0
        with self._session() as db:
            deltas = (
                self._build_bulk_upsert_status_deltas(db, payload)
                if maintain_status_stats else {}
            )
            for item in payload:
                self._upsert_one(db, item)
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

    def _upsert_one(self, db: Session, entry: IndexEntry) -> None:
        entry = _sqlite_safe_entry(entry)
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
                rjcode=entry.rjcode,
                parent_path=entry.parent_path,
                size=entry.size or 0,
                file_count=entry.file_count or 0,
                mtime=entry.mtime,
                depth=entry.depth,
                indexed_at=indexed_at,
            )
            db.add(row)
        else:
            row.entry_type = entry.entry_type
            row.absolute_path = entry.absolute_path
            row.name = entry.name
            row.rjcode = entry.rjcode
            row.parent_path = entry.parent_path
            row.size = entry.size or 0
            row.file_count = entry.file_count or 0
            row.mtime = entry.mtime
            row.depth = entry.depth
            row.indexed_at = indexed_at

    @staticmethod
    def _entry_to_upsert_params(entry: IndexEntry) -> dict:
        return {
            "library_id": entry.library_id,
            "entry_type": entry.entry_type,
            "relative_path": entry.relative_path,
            "absolute_path": entry.absolute_path,
            "name": entry.name,
            "rjcode": entry.rjcode,
            "parent_path": entry.parent_path,
            "size": entry.size or 0,
            "file_count": entry.file_count or 0,
            "mtime": entry.mtime,
            "depth": entry.depth,
            "indexed_at": entry.indexed_at or _now_ms(),
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
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.relative_path.in_(paths[i:i + chunk_size]),
                )
                .all()
            )
            for row in rows:
                result[row.relative_path] = self._row_stats(row)
        return result

    def _build_bulk_upsert_status_deltas(
        self,
        db: Session,
        payload: list[IndexEntry],
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
    ) -> None:
        if not (size_delta or folder_delta or entry_delta):
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

    def _query_stats_delta(self, q) -> tuple[int, int, int]:
        entry_count = int(q.with_entities(func.count(LibraryIndexEntry.id)).scalar() or 0)
        total_size = int(
            q.filter(LibraryIndexEntry.entry_type == 'file')
            .with_entities(func.coalesce(func.sum(LibraryIndexEntry.size), 0))
            .scalar() or 0
        )
        folder_count = int(
            q.filter(
                LibraryIndexEntry.entry_type == 'dir',
                LibraryIndexEntry.relative_path != '',
                func.coalesce(LibraryIndexEntry.parent_path, '') == '',
            )
            .with_entities(func.count(LibraryIndexEntry.id))
            .scalar() or 0
        )
        return max(0, total_size), max(0, folder_count), max(0, entry_count)

    @staticmethod
    def _normalize_relative_path(value: Optional[str]) -> str:
        return str(value or "").strip("/")

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _subtree_like_pattern(cls, relative_path: str) -> str:
        return f"{cls._escape_like(relative_path)}/%"

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
        return q.filter(
            or_(
                LibraryIndexEntry.relative_path == normalized,
                LibraryIndexEntry.relative_path.like(
                    self._subtree_like_pattern(normalized),
                    escape="\\",
                ),
            ),
        )

    def _delete_subtree_in_session(
        self,
        db: Session,
        library_id: str,
        relative_path: str,
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
                           WHEN parent_path LIKE :old_child_like ESCAPE '\\'
                               THEN :new_rel || substr(parent_path, :old_rel_suffix_start)
                           ELSE parent_path
                       END,
                       name = CASE
                           WHEN relative_path = :old_rel THEN :new_name
                           ELSE name
                       END,
                       depth = CASE
                           WHEN depth IS NULL THEN NULL
                           ELSE depth + :depth_delta
                       END,
                       indexed_at = :indexed_at
                 WHERE library_id = :library_id
                   AND (
                       relative_path = :old_rel
                       OR relative_path LIKE :old_child_like ESCAPE '\\'
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
                size_delta=-target_size + (new_size - old_size),
                folder_delta=-target_folders + (new_folders - old_folders),
                entry_delta=-target_entries,
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
        with self._session() as db:
            return self._move_subtree_same_library_in_session(
                db,
                library_id,
                old_relative_path=old_relative_path,
                new_relative_path=new_relative_path,
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
            )

    def move_subtrees_same_library(
        self,
        library_id: str,
        moves: Iterable[dict[str, str]],
    ) -> list[int]:
        """同库批量移动索引 fast-path：所有前缀改写放在一个事务里。"""
        items = list(moves or [])
        if not items:
            return []
        results: list[int] = []
        with self._session() as db:
            for item in items:
                moved = self._move_subtree_same_library_in_session(
                    db,
                    library_id,
                    old_relative_path=str(item.get("old_relative_path") or ""),
                    new_relative_path=str(item.get("new_relative_path") or ""),
                    old_absolute_path=str(item.get("old_absolute_path") or ""),
                    new_absolute_path=str(item.get("new_absolute_path") or ""),
                )
                results.append(moved)
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
                    rjcode,
                    CASE
                        WHEN relative_path = :old_rel THEN :new_parent
                        WHEN parent_path = :old_rel THEN :new_rel
                        WHEN parent_path LIKE :old_child_like ESCAPE '\\'
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
                      OR relative_path LIKE :old_child_like ESCAPE '\\'
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
                "old_child_like": self._subtree_like_pattern(old_rel),
                "old_rel_suffix_start": len(old_rel) + 1,
                "old_abs_suffix_start": len(old_abs) + 1,
                "depth_delta": depth_delta,
                "indexed_at": now,
            },
        )
        inserted = int(insert_result.rowcount or source_entries)

        self._delete_subtree_in_session(db, source_library_id, old_rel)

        self._apply_status_delta(
            db,
            target_library_id,
            size_delta=-target_size + source_size,
            folder_delta=-target_folders + inserted_top_folders,
            entry_delta=-target_entries + inserted,
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
        with self._session() as db:
            return self._move_subtree_between_libraries_in_session(
                db,
                source_library_id,
                target_library_id,
                old_relative_path=old_relative_path,
                new_relative_path=new_relative_path,
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
            )

    def move_subtrees_between_libraries(
        self,
        source_library_id: str,
        target_library_id: str,
        moves: Iterable[dict[str, str]],
    ) -> list[int]:
        """跨库批量移动索引 fast-path：所有搬迁放在一个事务里。"""
        items = list(moves or [])
        if not items:
            return []
        results: list[int] = []
        with self._session() as db:
            for item in items:
                moved = self._move_subtree_between_libraries_in_session(
                    db,
                    source_library_id,
                    target_library_id,
                    old_relative_path=str(item.get("old_relative_path") or ""),
                    new_relative_path=str(item.get("new_relative_path") or ""),
                    old_absolute_path=str(item.get("old_absolute_path") or ""),
                    new_absolute_path=str(item.get("new_absolute_path") or ""),
                )
                results.append(moved)
        return results

    # ========== Entry 删除 ==========

    def delete_by_relative_path(self, library_id: str, relative_path: str) -> int:
        """删除单行。"""
        with self._session() as db:
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
        prefix = (normalized + '/') if normalized else ''
        with self._session() as db:
            q = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
            )
            if normalized:
                q = q.filter(
                    or_(
                        LibraryIndexEntry.relative_path == normalized,
                        LibraryIndexEntry.relative_path.like(prefix + '%'),
                    ),
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

    def delete_library(self, library_id: str) -> int:
        """整库清空（rebuild 前调用）。"""
        with self._session() as db:
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
    ) -> int:
        """分块删除全量重建后未被本轮扫描刷新到的旧行。

        rebuild 主路径会先 upsert 新快照，再按 indexed_at 边界清 stale。
        这里故意不用一条大 DELETE，避免 SQLite 写锁和 FTS 删除触发器长时间占用。
        """
        chunk_size = max(1, int(chunk_size or 500))
        cutoff = int(indexed_before_ms or 0)
        deleted_total = 0
        started = time.time()
        while True:
            with self._session() as db:
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
        with self._session() as db:
            q = db.query(LibraryIndexEntry).filter(LibraryIndexEntry.rjcode == rjcode)
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
        - FTS5/trigram 可用时优先走 `library_index_entries_fts`，适合中文子串、
          文件名片段、相对路径片段和 RJ 号搜索。
        - FTS 不可用 / 查询失败时回退 LIKE，多列语义保持一致。

        library_id：
        - str → 仅该库存
        - None / 空序列 → 跨全部库存（库存维度由调用方上层保证可见性）
        - Sequence[str] → 多库存命中（IN 子查询）
        """
        if not name_like:
            return []
        scope_ids = self._normalize_scope_ids(library_id)
        with self._session() as db:
            try:
                fts_result = self._find_by_name_fts(
                    db,
                    scope_ids,
                    name_like,
                    entry_type=entry_type,
                    limit=limit,
                )
                if fts_result is not None:
                    return fts_result
            except Exception:
                logger.warning("[索引] FTS 搜索失败，回退 LIKE keyword=%r", name_like, exc_info=True)
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
        # 转义 SQL 通配符，让用户输入的 _ % 真正只匹配自身
        escaped = name_like.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f"%{escaped}%"
        q = db.query(LibraryIndexEntry).filter(
            or_(
                LibraryIndexEntry.name.collate('NOCASE').like(pattern, escape='\\'),
                LibraryIndexEntry.relative_path.collate('NOCASE').like(pattern, escape='\\'),
                LibraryIndexEntry.rjcode.collate('NOCASE').like(pattern, escape='\\'),
                LibraryIndexEntry.parent_path.collate('NOCASE').like(pattern, escape='\\'),
            )
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
            LibraryIndexEntry.name.asc(),
            LibraryIndexEntry.relative_path.asc(),
        )
        return [self._row_to_entry(row) for row in q.limit(limit).all()]

    def _find_by_name_fts(
        self,
        db: Session,
        scope_ids: Optional[list[str]],
        raw_keyword: str,
        *,
        entry_type: Optional[str],
        limit: int,
    ) -> Optional[list[IndexEntry]]:
        conn = db.connection()
        if library_index_fts_ready_hint() is False:
            return None
        if not library_index_fts_enabled(conn):
            return None

        tokenizer = read_library_index_fts_tokenizer(conn)
        if not tokenizer:
            return None

        keyword = sanitize_library_index_search_text(raw_keyword)
        if not keyword:
            return []

        params: dict[str, object] = {"limit": max(1, int(limit or 200))}
        filters: list[str] = []
        if scope_ids:
            if len(scope_ids) == 1:
                filters.append("e.library_id = :library_id_0")
                params["library_id_0"] = scope_ids[0]
            else:
                placeholders = []
                for idx, item in enumerate(scope_ids):
                    key = f"library_id_{idx}"
                    placeholders.append(f":{key}")
                    params[key] = item
                filters.append(f"e.library_id IN ({', '.join(placeholders)})")
        if entry_type:
            filters.append("e.entry_type = :entry_type")
            params["entry_type"] = entry_type

        tk = tokenizer.strip().lower()
        if tk.startswith("trigram") and len(keyword) < 3:
            params["pattern"] = f"%{keyword}%"
            search_clause = (
                f"({FTS_TABLE_NAME}.name LIKE :pattern "
                f"OR {FTS_TABLE_NAME}.relative_path LIKE :pattern "
                f"OR {FTS_TABLE_NAME}.rjcode LIKE :pattern "
                f"OR {FTS_TABLE_NAME}.parent_path LIKE :pattern)"
            )
        else:
            match_expr = build_library_index_fts_match_expression(keyword, tokenizer)
            if not match_expr:
                return None
            params["match_expr"] = match_expr
            search_clause = f"{FTS_TABLE_NAME} MATCH :match_expr"

        where_sql = " AND ".join([search_clause, *filters])
        rows = db.execute(
            text(
                f"""
                SELECT
                    e.library_id AS library_id,
                    e.entry_type AS entry_type,
                    e.relative_path AS relative_path,
                    e.absolute_path AS absolute_path,
                    e.name AS name,
                    e.rjcode AS rjcode,
                    e.parent_path AS parent_path,
                    e.size AS size,
                    e.file_count AS file_count,
                    e.mtime AS mtime,
                    e.depth AS depth,
                    e.indexed_at AS indexed_at
                  FROM {FTS_TABLE_NAME}
                  JOIN library_index_entries e ON e.id = {FTS_TABLE_NAME}.id
                 WHERE {where_sql}
                 ORDER BY e.depth ASC, e.name COLLATE NOCASE ASC, e.relative_path COLLATE NOCASE ASC
                 LIMIT :limit
                """
            ),
            params,
        ).fetchall()

        result = [self._mapping_to_entry(row._mapping) for row in rows]
        # unicode61 对 CJK 子串较弱，空命中时回退 LIKE 保证搜索质量。
        if not result and not tk.startswith("trigram"):
            return None
        return result

    def list_children(
        self,
        library_id: str,
        parent_path: Optional[str],
        *,
        entry_type: Optional[str] = None,
    ) -> list[IndexEntry]:
        """列指定 parent_path 的直接子项。parent_path='' 表示库根的一级子项。"""
        with self._session() as db:
            q = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.parent_path == (parent_path or ''),
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            q = q.order_by(LibraryIndexEntry.name.asc())
            return [self._row_to_entry(row) for row in q.all()]

    def get_entry(self, library_id: str, relative_path: str) -> Optional[IndexEntry]:
        with self._session() as db:
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
        with self._session() as db:
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
        with self._session() as db:
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
        with self._session() as db:
            q = db.query(func.count(LibraryIndexEntry.id)).filter(
                LibraryIndexEntry.library_id == library_id,
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            return int(q.scalar() or 0)

    # ========== Status ==========

    def get_status(self, library_id: str) -> Optional[IndexStatus]:
        with self._session() as db:
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
        with self._session() as db:
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
        with self._session() as db:
            return (
                db.query(LibraryIndexStatus)
                .filter(LibraryIndexStatus.library_id == library_id)
                .delete(synchronize_session=False)
            )

    def delete_subtrees(
        self,
        library_id: str,
        relative_paths: Iterable[str],
    ) -> int:
        """批量删除多个子树（自身 + 所有后代），单事务执行。

        每个 path 的匹配规则与 delete_subtree 一致：
        relative_path == p OR relative_path LIKE p + '/%'

        SQLite 的 OR 条件长度有限，超过 200 个路径时分批，避免 SQL 超长。
        """
        paths = [p for p in relative_paths if p is not None]
        if not paths:
            return 0
        chunk_size = 200
        deleted = 0
        with self._session() as db:
            for i in range(0, len(paths), chunk_size):
                chunk = paths[i:i + chunk_size]
                conditions = []
                for p in chunk:
                    conditions.append(LibraryIndexEntry.relative_path == p)
                    conditions.append(LibraryIndexEntry.relative_path.like(f"{p}/%"))
                if not conditions:
                    continue
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
        with self._session() as db:
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


_default_store: Optional[SnapshotStore] = None


def get_snapshot_store() -> SnapshotStore:
    """进程内单例访问器。"""
    global _default_store
    if _default_store is None:
        _default_store = SnapshotStore()
    return _default_store
