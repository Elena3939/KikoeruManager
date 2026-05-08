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
from typing import Iterable, Iterator, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexStatus,
    SessionLocal,
)
from .types import (
    IndexEntry,
    IndexStatus,
    IndexStatusName,
    WatcherMode,
)

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class SnapshotStore:
    """索引快照 CRUD。"""

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Iterator[Session]:
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
            self._upsert_one(db, entry)

    def bulk_upsert(self, entries: Iterable[IndexEntry], *, chunk_size: int = 500) -> int:
        """批量写入 / 更新，返回实际写入条数。

        批次 1 实现用朴素 upsert 循环，批次 2 全量扫描落地时会改成
        INSERT ... ON CONFLICT DO UPDATE 原生 SQL，以支撑几十万级数据。
        """
        written = 0
        buffer: list[IndexEntry] = []

        def _flush(db: Session) -> None:
            nonlocal written
            # 同一批次里如果出现了 relative_path 重复，按最后一个为准
            deduped: dict[tuple[str, str], IndexEntry] = {}
            for item in buffer:
                deduped[(item.library_id, item.relative_path)] = item
            for item in deduped.values():
                self._upsert_one(db, item)
                written += 1
            buffer.clear()

        with self._session() as db:
            for entry in entries:
                buffer.append(entry)
                if len(buffer) >= chunk_size:
                    _flush(db)
            if buffer:
                _flush(db)
        return written

    def _upsert_one(self, db: Session, entry: IndexEntry) -> None:
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

    # ========== Entry 删除 ==========

    def delete_by_relative_path(self, library_id: str, relative_path: str) -> int:
        """删除单行。"""
        with self._session() as db:
            return (
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.relative_path == relative_path,
                )
                .delete(synchronize_session=False)
            )

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
            return q.delete(synchronize_session=False)

    def delete_library(self, library_id: str) -> int:
        """整库清空（rebuild 前调用）。"""
        with self._session() as db:
            return (
                db.query(LibraryIndexEntry)
                .filter(LibraryIndexEntry.library_id == library_id)
                .delete(synchronize_session=False)
            )

    # ========== Entry 查询 ==========

    def find_by_rjcode(
        self,
        library_id: Optional[str],
        rjcode: str,
        *,
        entry_type: Optional[str] = 'dir',
        limit: int = 100,
    ) -> list[IndexEntry]:
        """按 RJ 号精确查。library_id 为 None 时跨全部库存。"""
        if not rjcode:
            return []
        with self._session() as db:
            q = db.query(LibraryIndexEntry).filter(LibraryIndexEntry.rjcode == rjcode)
            if library_id:
                q = q.filter(LibraryIndexEntry.library_id == library_id)
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            q = q.order_by(
                LibraryIndexEntry.depth.asc(),
                LibraryIndexEntry.relative_path.asc(),
            )
            return [self._row_to_entry(row) for row in q.limit(limit).all()]

    def find_by_name(
        self,
        library_id: str,
        name_like: str,
        *,
        entry_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[IndexEntry]:
        """按名称模糊搜索。LIKE 大小写敏感与否依赖 SQLite 默认 NOCASE 校对。"""
        if not name_like:
            return []
        pattern = f"%{name_like.lower()}%"
        with self._session() as db:
            q = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
                func.lower(LibraryIndexEntry.name).like(pattern),
            )
            if entry_type:
                q = q.filter(LibraryIndexEntry.entry_type == entry_type)
            q = q.order_by(
                LibraryIndexEntry.depth.asc(),
                LibraryIndexEntry.name.asc(),
            )
            return [self._row_to_entry(row) for row in q.limit(limit).all()]

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
                if error is not ...:
                    row.error = error
                row.updated_at = now
            db.flush()
            snapshot = self._row_to_status(row)
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
                deleted += (
                    db.query(LibraryIndexEntry)
                    .filter(LibraryIndexEntry.library_id == library_id)
                    .filter(or_(*conditions))
                    .delete(synchronize_session=False)
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
    def _row_to_status(row: LibraryIndexStatus) -> IndexStatus:
        return IndexStatus(
            library_id=row.library_id,
            status=row.status,
            watcher_mode=row.watcher_mode,
            last_full_scan_at=row.last_full_scan_at,
            last_event_at=row.last_event_at,
            total_entries=int(row.total_entries or 0),
            error=row.error,
            updated_at=int(row.updated_at or 0),
        )


_default_store: Optional[SnapshotStore] = None


def get_snapshot_store() -> SnapshotStore:
    """进程内单例访问器。"""
    global _default_store
    if _default_store is None:
        _default_store = SnapshotStore()
    return _default_store
