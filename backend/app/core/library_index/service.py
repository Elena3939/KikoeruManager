"""LibraryIndexService：库存搜索索引对外的统一入口。

职责：
- rebuild_local：清空 + 全量扫描（同步）
- schedule_rebuild_local：异步触发，立刻置 syncing 并返回当前状态
- query 系列：包装 SnapshotStore 的查询接口
- get_status / list_all_status：跟踪每库存的 syncing / ready / error 状态

依赖：
- SnapshotStore（DB 读写）
- LocalScanner（本地全量扫描）
- 不直接 import LibraryManager / settings：路由层 / 上层负责把
  LibraryDefinition 解析成 (library_id, root_path) 再调本类，
  便于在测试里换装 fake scanner / store。

当前范围：仅支持 local 库存。synology_filestation 不创建库存索引，
统一回到群晖 FileStation 原生浏览 / 搜索。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional, Sequence, Union

from sqlalchemy import func, text

from .local_scanner import LocalScanner
from .remote_scanner import RemoteScanner
from ..resource_budget_service import get_resource_budget_service
from .snapshot_store import (
    DEFAULT_BULK_UPSERT_CHUNK_SIZE,
    SnapshotStore,
    get_snapshot_store,
)
from .types import IndexEntry, IndexStatus
from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexGeneration,
    LibraryIndexMutationEffect,
    LibraryIndexMutationLedger,
    LibraryIndexMutationOperation,
    LibraryIndexPendingMask,
    LibraryIndexStatus,
    SessionLocal,
    get_local_now,
    require_library_index_generation_contract_ready,
    suspend_library_index_secondary_indexes_for_initial_bulk_load,
)

logger = logging.getLogger(__name__)

# 首次全量重建通常是几十万文件；日常 self-mutation 仍走 SnapshotStore 的 500 小批。
FULL_REBUILD_BULK_CHUNK_SIZE = 5000
FULL_REBUILD_ANALYZE_THRESHOLD = 5000
STALE_SYNCING_GRACE_SECONDS = 30.0
INTERRUPTED_SYNCING_MESSAGE = "上次索引同步中断，未发现正在运行的重建任务；请手动重建索引"
GENERATION_RETENTION_HOURS = 24
GENERATION_CLEANUP_CHUNK_SIZE = 5000


@dataclass(slots=True)
class _SubtreeParentStatsDelta:
    relative_path: str
    old_size: int
    old_file_count: int
    new_size: int = 0
    new_file_count: int = 0

    @property
    def size_delta(self) -> int:
        return self.new_size - self.old_size

    @property
    def file_count_delta(self) -> int:
        return self.new_file_count - self.old_file_count

# 远程全量重建入口已禁用；保留环境变量解析只为旧代码兼容。
def _remote_rebuild_min_interval_seconds() -> float:
    raw = os.getenv("KIKOERUMANAGER_REMOTE_REBUILD_MIN_INTERVAL_SECONDS", "")
    try:
        value = float(raw)
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    return 600.0  # 默认 10 分钟


# ========== 远程 Search 全局串行锁 ==========
# 群晖 SYNO.FileStation.Search 是递归重活：起一次 task 群晖端 CPU/磁盘满负荷跑。
# 多个库并发全量重建 / 高频子树扫描会同时在群晖端起多个 search task，直接打爆 NAS。
# 这里用一把进程级（per-event-loop）锁，保证任意时刻群晖上只跑一个 search task。
#
# 为什么 per-loop：asyncio.Lock 绑定创建它的 event loop，而远程扫描可能跑在主 loop、
# watcher loop 或 _remote_upsert_loop 上。按 running loop 取锁，同一 loop 内严格串行；
# 不同 loop 间极少同时跑远程扫描（部署上远程操作集中在少数 loop），可接受。
#
# 关键顺序：必须在获取 remote_fs 资源预算【之前】拿这把锁。否则全量重建持有的
# remote_fs 预算（weight=2）会和它内部 list_search（weight=1）互相等待——两个库并发
# 重建时 2+2 占满 4 个令牌，谁都拿不到第三个，造成死锁。先拿串行锁能从根上避免。
_remote_search_locks: dict[int, asyncio.Lock] = {}
_remote_search_locks_guard = threading.Lock()


def _get_remote_search_lock() -> asyncio.Lock:
    """取当前 running event loop 对应的远程 search 串行锁。"""
    loop = asyncio.get_event_loop()
    key = id(loop)
    lock = _remote_search_locks.get(key)
    if lock is not None:
        return lock
    with _remote_search_locks_guard:
        lock = _remote_search_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _remote_search_locks[key] = lock
        return lock


class LibraryIndexService:
    def __init__(
        self,
        *,
        store: Optional[SnapshotStore] = None,
        local_scanner_factory=LocalScanner,
        remote_scanner_factory=RemoteScanner,
    ):
        self._store = store or get_snapshot_store()
        self._local_scanner_factory = local_scanner_factory
        self._remote_scanner_factory = remote_scanner_factory
        # 防止同库存并发 rebuild
        self._rebuild_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        # 持有 fire-and-forget 的后台 task，避免被 GC 警告
        self._pending_tasks: set[asyncio.Task] = set()
        self._pending_tasks_by_library: dict[str, set[asyncio.Task]] = {}

    # ========== 锁 ==========

    def _get_lock(self, library_id: str) -> threading.Lock:
        with self._global_lock:
            lock = self._rebuild_locks.get(library_id)
            if lock is None:
                lock = threading.Lock()
                self._rebuild_locks[library_id] = lock
            return lock

    def _track_rebuild_task(self, library_id: str, task: asyncio.Task) -> None:
        self._pending_tasks.add(task)
        bucket = self._pending_tasks_by_library.setdefault(library_id, set())
        bucket.add(task)

        def _discard(done_task: asyncio.Task) -> None:
            self._pending_tasks.discard(done_task)
            bucket.discard(done_task)
            if not bucket:
                self._pending_tasks_by_library.pop(library_id, None)

        task.add_done_callback(_discard)

    # ========== 重建 ==========

    @staticmethod
    def _generation_contract_enabled() -> bool:
        requested = os.getenv(
            "KIKOERUMANAGER_LIBRARY_INDEX_GENERATION_CONTRACT",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not requested:
            return False
        db = SessionLocal()
        try:
            require_library_index_generation_contract_ready(db.connection())
            return True
        finally:
            db.rollback()
            db.close()

    @staticmethod
    def _estimate_generation_bytes(library_id: str, generation: int) -> int:
        db = SessionLocal()
        try:
            total = db.query(
                LibraryIndexEntry,
            ).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.generation == generation,
            ).count()
            relation_bytes = int(db.execute(
                text("SELECT COALESCE(pg_total_relation_size('library_index_entries'), 0)")
            ).scalar() or 0)
            all_rows = int(db.execute(
                text("SELECT count(*) FROM library_index_entries")
            ).scalar() or 0)
            return max(1, int(relation_bytes * total / max(all_rows, 1)))
        finally:
            db.close()

    def _require_generation_capacity(self, library_id: str, root_path: str, active_generation: int) -> None:
        del root_path
        estimated = self._estimate_generation_bytes(library_id, active_generation)
        override = os.getenv("KIKOERUMANAGER_LIBRARY_INDEX_DATABASE_FREE_BYTES", "").strip()
        if override:
            try:
                available = int(override)
            except ValueError as exc:
                raise RuntimeError("库存索引数据库可用空间配置不是整数") from exc
        else:
            db = SessionLocal()
            try:
                data_directory = str(db.execute(text("SHOW data_directory")).scalar() or "").strip()
            finally:
                db.close()
            if not data_directory or not os.path.isdir(data_directory):
                raise RuntimeError(
                    "无法从应用主机读取 PostgreSQL data_directory 可用空间；请设置 "
                    "KIKOERUMANAGER_LIBRARY_INDEX_DATABASE_FREE_BYTES 后再重建"
                )
            available = int(shutil.disk_usage(data_directory).free)
        required = int(estimated * 1.2)
        if available < required:
            raise RuntimeError(
                f"库存索引候选 generation 空间不足: free={available} required={required}"
            )

    def _create_building_generation(self, library_id: str, root_path: str) -> tuple[int, int]:
        if not self._generation_contract_enabled():
            raise RuntimeError(
                "generation contract 尚未启用；所有实例升级后先删除旧二列唯一索引，再设置 "
                "KIKOERUMANAGER_LIBRARY_INDEX_GENERATION_CONTRACT=1"
            )
        db = SessionLocal()
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).with_for_update().first()
            if status is None:
                status = LibraryIndexStatus(
                    library_id=library_id,
                    status="idle",
                    watcher_mode="disabled",
                    accepted_seq=0,
                    materialized_seq=0,
                    state_revision=0,
                    view_revision=0,
                    active_generation=1,
                    materializer_epoch=0,
                    catchup_state="idle",
                    updated_at=int(time.time() * 1000),
                )
                db.add(status)
                db.flush()
            if status.building_generation is not None:
                raise RuntimeError("当前库存已有 building generation")
            prepared_exists = db.query(LibraryIndexMutationOperation.operation_id).join(
                LibraryIndexPendingMask,
                LibraryIndexPendingMask.operation_id == LibraryIndexMutationOperation.operation_id,
            ).filter(
                LibraryIndexMutationOperation.state == "prepared",
                LibraryIndexPendingMask.library_id == library_id,
            ).first()
            if prepared_exists is not None:
                raise RuntimeError("当前库存有 prepared mutation，暂不能开始重建")
            active_generation = int(status.active_generation or 1)
            self._require_generation_capacity(library_id, root_path, active_generation)
            max_generation = db.query(func.max(LibraryIndexGeneration.generation)).filter(
                LibraryIndexGeneration.library_id == library_id
            ).scalar()
            generation = max(active_generation, int(max_generation or 0)) + 1
            base_seq = int(status.accepted_seq or 0)
            db.add(LibraryIndexGeneration(
                library_id=library_id,
                generation=generation,
                state="building",
                build_base_seq=base_seq,
                reconciled_seq=base_seq,
            ))
            status.building_generation = generation
            status.status = "syncing"
            status.catchup_state = "rebuilding"
            status.state_revision = int(status.state_revision or 0) + 1
            status.updated_at = int(time.time() * 1000)
            db.commit()
            return generation, base_seq
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _scan_building_generation(
        self,
        library_id: str,
        root_path: str,
        generation: int,
        build_base_seq: int,
        chunk_size: int,
    ) -> dict[str, int]:
        scanner = self._local_scanner_factory()
        buffer: list[IndexEntry] = []
        written = 0
        total_size = 0
        folder_count = 0
        for entry in scanner.scan(library_id, root_path):
            entry.generation = generation
            entry.materialized_seq = build_base_seq
            buffer.append(entry)
            size_delta, folder_delta = self._entry_stats(entry)
            total_size += size_delta
            folder_count += folder_delta
            if len(buffer) >= chunk_size:
                written += self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_status_stats=False,
                    insert_only=True,
                    relaxed_commit=True,
                )
                buffer.clear()
        if buffer:
            written += self._store.bulk_upsert(
                buffer,
                chunk_size=chunk_size,
                maintain_status_stats=False,
                insert_only=True,
                relaxed_commit=True,
            )
        return {
            "total_entries": written,
            "total_size_bytes": total_size,
            "folder_count": folder_count,
        }

    @staticmethod
    def _generation_reconcile_roots(
        library_id: str,
        after_seq: int,
        through_seq: int,
    ) -> list[str]:
        db = SessionLocal()
        try:
            rows = db.query(LibraryIndexMutationEffect).filter(
                LibraryIndexMutationEffect.library_id == library_id,
                LibraryIndexMutationEffect.seq > after_seq,
                LibraryIndexMutationEffect.seq <= through_seq,
            ).order_by(
                LibraryIndexMutationEffect.seq.asc(),
                LibraryIndexMutationEffect.effect_no.asc(),
            ).all()
            paths: list[str] = []
            for row in rows:
                paths.append(str(row.relative_path or ""))
                if row.target_library_id == library_id and row.target_path is not None:
                    paths.append(str(row.target_path or ""))
            compressed: list[str] = []
            for path in sorted(set(paths), key=lambda value: (value.count("/"), value)):
                if any(not root or path == root or path.startswith(root + "/") for root in compressed):
                    continue
                compressed.append(path)
            return compressed
        finally:
            db.close()

    def _reconcile_building_generation(
        self,
        library_id: str,
        root_path: str,
        generation: int,
        from_seq: int,
        through_seq: int,
        chunk_size: int,
    ) -> None:
        for relative_path in self._generation_reconcile_roots(
            library_id,
            from_seq,
            through_seq,
        ):
            target = (
                os.path.abspath(os.path.join(root_path, *relative_path.split("/")))
                if relative_path
                else os.path.abspath(root_path)
            )
            db = SessionLocal()
            try:
                q = db.query(LibraryIndexEntry).filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.generation == generation,
                )
                if relative_path:
                    q = q.filter(
                        (LibraryIndexEntry.relative_path == relative_path)
                        | (
                            (LibraryIndexEntry.relative_path >= relative_path + "/")
                            & (LibraryIndexEntry.relative_path < relative_path + "0")
                        )
                    )
                q.delete(synchronize_session=False)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            if not os.path.exists(target):
                continue
            buffer: list[IndexEntry] = []
            for entry in self._local_scanner_factory().scan_subtree(
                library_id,
                root_path,
                target,
            ):
                entry.generation = generation
                entry.materialized_seq = through_seq
                buffer.append(entry)
                if len(buffer) >= chunk_size:
                    self._store.bulk_upsert(
                        buffer,
                        chunk_size=chunk_size,
                        maintain_status_stats=False,
                    )
                    buffer.clear()
            if buffer:
                self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_status_stats=False,
                )

    @staticmethod
    def _building_generation_stats(library_id: str, generation: int) -> dict[str, int]:
        db = SessionLocal()
        try:
            total_entries, total_size_bytes, folder_count = db.query(
                func.count(LibraryIndexEntry.id),
                func.coalesce(
                    func.sum(
                        func.greatest(
                            func.coalesce(LibraryIndexEntry.size, 0),
                            0,
                        )
                    ).filter(LibraryIndexEntry.entry_type == "file"),
                    0,
                ),
                func.count(LibraryIndexEntry.id).filter(
                    LibraryIndexEntry.entry_type == "dir",
                    LibraryIndexEntry.relative_path != "",
                    func.coalesce(LibraryIndexEntry.parent_path, "") == "",
                ),
            ).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.generation == generation,
            ).one()
            return {
                "total_entries": int(total_entries or 0),
                "total_size_bytes": int(total_size_bytes or 0),
                "folder_count": int(folder_count or 0),
            }
        finally:
            db.close()

    def _cutover_building_generation(
        self,
        library_id: str,
        generation: int,
        expected_seq: int,
        stats: dict[str, int],
    ) -> IndexStatus:
        db = SessionLocal()
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).with_for_update().one()
            if int(status.building_generation or 0) != generation:
                raise RuntimeError("building generation 已变化")
            if int(status.accepted_seq or 0) != expected_seq:
                raise RuntimeError("cutover 前 accepted_seq 已推进")
            prepared_exists = db.query(LibraryIndexMutationOperation.operation_id).join(
                LibraryIndexPendingMask,
                LibraryIndexPendingMask.operation_id == LibraryIndexMutationOperation.operation_id,
            ).filter(
                LibraryIndexMutationOperation.state == "prepared",
                LibraryIndexPendingMask.library_id == library_id,
            ).first()
            if prepared_exists is not None:
                raise RuntimeError("cutover 时仍有 prepared mutation")
            old_generation = int(status.active_generation or 1)
            now = get_local_now()
            candidate = db.query(LibraryIndexGeneration).filter(
                LibraryIndexGeneration.library_id == library_id,
                LibraryIndexGeneration.generation == generation,
            ).with_for_update().one()
            old = db.query(LibraryIndexGeneration).filter(
                LibraryIndexGeneration.library_id == library_id,
                LibraryIndexGeneration.generation == old_generation,
            ).with_for_update().first()
            candidate.state = "active"
            candidate.reconciled_seq = expected_seq
            candidate.total_entries = int(stats["total_entries"])
            candidate.total_size_bytes = int(stats["total_size_bytes"])
            candidate.folder_count = int(stats["folder_count"])
            candidate.error = None
            candidate.cutover_at = now
            candidate.retired_at = None
            candidate.delete_after = None
            if old is not None and old.generation != generation:
                old.state = "retired"
                old.retired_at = now
                old.delete_after = now + timedelta(hours=GENERATION_RETENTION_HOURS)
            status.active_generation = generation
            status.building_generation = None
            status.materialized_seq = expected_seq
            status.total_entries = int(stats["total_entries"])
            status.total_size_bytes = int(stats["total_size_bytes"])
            status.folder_count = int(stats["folder_count"])
            status.status = "ready"
            status.catchup_state = "idle"
            status.blocked_seq = None
            status.catchup_error = None
            status.error = None
            status.state_revision = int(status.state_revision or 0) + 1
            status.view_revision = int(status.view_revision or 0) + 1
            status.materializer_epoch = int(status.materializer_epoch or 0) + 1
            status.materializer_owner = None
            status.materializer_lease_until = None
            status.last_full_scan_at = int(time.time() * 1000)
            status.updated_at = int(time.time() * 1000)
            db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.library_id == library_id,
                LibraryIndexMutationLedger.seq <= expected_seq,
                LibraryIndexMutationLedger.applied_at.is_(None),
            ).update(
                {
                    LibraryIndexMutationLedger.applied_at: now,
                    LibraryIndexMutationLedger.attempt_count: 0,
                    LibraryIndexMutationLedger.error: None,
                    LibraryIndexMutationLedger.next_retry_at: None,
                },
                synchronize_session=False,
            )
            db.query(LibraryIndexPendingMask).filter(
                LibraryIndexPendingMask.library_id == library_id,
                LibraryIndexPendingMask.ledger_seq.isnot(None),
                LibraryIndexPendingMask.ledger_seq <= expected_seq,
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        snapshot = self._store.get_status(library_id)
        if snapshot is None:
            raise RuntimeError("generation cutover 后状态行不存在")
        self._store._broadcast_status_change(snapshot, reason="library_index_generation_cutover")
        return snapshot

    def _fail_building_generation(self, library_id: str, generation: int, error: Exception) -> None:
        db = SessionLocal()
        changed = False
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).with_for_update().first()
            candidate = db.query(LibraryIndexGeneration).filter(
                LibraryIndexGeneration.library_id == library_id,
                LibraryIndexGeneration.generation == generation,
            ).with_for_update().first()
            if candidate is not None:
                now = get_local_now()
                candidate.state = "failed"
                candidate.error = str(error)
                candidate.retired_at = now
                candidate.delete_after = now + timedelta(hours=GENERATION_RETENTION_HOURS)
                changed = True
            if status is not None and int(status.building_generation or 0) == generation:
                status.building_generation = None
                status.status = "ready" if status.active_generation else "error"
                status.catchup_state = (
                    "catching_up"
                    if int(status.accepted_seq or 0) > int(status.materialized_seq or 0)
                    else "idle"
                )
                status.error = str(error)
                status.state_revision = int(status.state_revision or 0) + 1
                status.updated_at = int(time.time() * 1000)
                changed = True
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[索引] 标记 building generation 失败异常 library=%s", library_id)
        finally:
            db.close()
        if changed:
            snapshot = self._store.get_status(library_id)
            if snapshot is not None:
                self._store._broadcast_status_change(
                    snapshot,
                    reason="library_index_generation_failed",
                )

    def rebuild_local_generation(
        self,
        library_id: str,
        root_path: str,
        *,
        chunk_size: int = FULL_REBUILD_BULK_CHUNK_SIZE,
    ) -> IndexStatus:
        lock = self._get_lock(library_id)
        if not lock.acquire(blocking=False):
            raise RuntimeError("当前库存正在重建")
        generation = 0
        try:
            generation, reconciled_seq = self._create_building_generation(
                library_id,
                root_path,
            )
            self._scan_building_generation(
                library_id,
                root_path,
                generation,
                reconciled_seq,
                chunk_size,
            )
            while True:
                db = SessionLocal()
                try:
                    accepted_seq = int(db.query(LibraryIndexStatus.accepted_seq).filter(
                        LibraryIndexStatus.library_id == library_id
                    ).scalar() or 0)
                finally:
                    db.close()
                if accepted_seq == reconciled_seq:
                    stats = self._building_generation_stats(library_id, generation)
                    try:
                        return self._cutover_building_generation(
                            library_id,
                            generation,
                            accepted_seq,
                            stats,
                        )
                    except RuntimeError as exc:
                        if "accepted_seq" not in str(exc):
                            raise
                        continue
                self._reconcile_building_generation(
                    library_id,
                    root_path,
                    generation,
                    reconciled_seq,
                    accepted_seq,
                    chunk_size,
                )
                reconciled_seq = accepted_seq
                db = SessionLocal()
                try:
                    candidate = db.query(LibraryIndexGeneration).filter(
                        LibraryIndexGeneration.library_id == library_id,
                        LibraryIndexGeneration.generation == generation,
                    ).one()
                    candidate.reconciled_seq = reconciled_seq
                    db.commit()
                finally:
                    db.close()
        except Exception as exc:
            if generation:
                self._fail_building_generation(library_id, generation, exc)
            raise
        finally:
            lock.release()

    @staticmethod
    def cleanup_retired_generations(
        *,
        chunk_size: int = GENERATION_CLEANUP_CHUNK_SIZE,
    ) -> int:
        removed = 0
        while True:
            db = SessionLocal()
            try:
                candidate = db.query(LibraryIndexGeneration).filter(
                    LibraryIndexGeneration.state.in_(("retired", "failed")),
                    LibraryIndexGeneration.delete_after.isnot(None),
                    LibraryIndexGeneration.delete_after <= get_local_now(),
                ).order_by(LibraryIndexGeneration.delete_after.asc()).first()
                if candidate is None:
                    return removed
                ids = [
                    row[0]
                    for row in db.query(LibraryIndexEntry.id).filter(
                        LibraryIndexEntry.library_id == candidate.library_id,
                        LibraryIndexEntry.generation == candidate.generation,
                    ).order_by(LibraryIndexEntry.id.asc()).limit(chunk_size).all()
                ]
                if ids:
                    db.query(LibraryIndexEntry).filter(
                        LibraryIndexEntry.id.in_(ids)
                    ).delete(synchronize_session=False)
                    removed += len(ids)
                else:
                    db.delete(candidate)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def rebuild_local(
        self,
        library_id: str,
        root_path: str,
        *,
        chunk_size: int = FULL_REBUILD_BULK_CHUNK_SIZE,
    ) -> IndexStatus:
        """同步全量重建本地库存索引。线程安全：同库存并发只允许一个。"""
        lock = self._get_lock(library_id)
        if not lock.acquire(blocking=False):
            existing = self._store.get_status(library_id)
            if existing and existing.status == 'syncing':
                logger.info("[索引] rebuild 跳过：%s 正在同步", library_id)
                return existing
            # 没拿到锁但状态不是 syncing：阻塞等
            lock.acquire()
        try:
            return self._do_rebuild_local(library_id, root_path, chunk_size)
        finally:
            lock.release()

    def _do_rebuild_local(
        self,
        library_id: str,
        root_path: str,
        chunk_size: int,
    ) -> IndexStatus:
        started = time.time()
        rebuild_started_ms = int(started * 1000)
        logger.info("[索引] 开始重建本地库存 library=%s root=%s", library_id, root_path)

        # 起始置 syncing；error 显式 None 清理上一轮失败痕迹
        self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error=None,
        )

        try:
            scanner = self._local_scanner_factory()
            # 手动分块，每足块写盘 + 每 0.5s 上报一次 syncing 进度
            # （total_entries 在 syncing 期间语义 = 已扫描数，ready 后 = 总数）。
            buffer: list[IndexEntry] = []
            written = 0
            total_size = 0
            folder_count = 0
            insert_only = not self._store_has_library_entries(library_id)
            initial_bulk_load = insert_only and not self._store_has_any_entries()
            last_progress_report = time.time()
            rebuild_writer = None
            if not insert_only:
                rebuild_writer = self._store.create_rebuild_writer(
                    library_id,
                    chunk_size=chunk_size,
                    relaxed_commit=True,
                )
            with self._initial_bulk_load_search_index_context(initial_bulk_load) as maintenance:
                if maintenance.get("active"):
                    logger.info(
                        "[索引] 首次全量构建暂停库存二级索引 library=%s dropped=%s",
                        library_id,
                        maintenance.get("dropped") or [],
                    )
                elif initial_bulk_load and maintenance.get("skipped"):
                    logger.info(
                        "[索引] 首次全量构建未暂停库存二级索引 library=%s reason=%s",
                        library_id,
                        maintenance.get("reason"),
                    )
                with rebuild_writer or nullcontext(None) as writer:
                    for entry in scanner.scan(library_id, root_path):
                        buffer.append(entry)
                        size_delta, folder_delta = self._entry_stats(entry)
                        total_size += size_delta
                        folder_count += folder_delta
                        if len(buffer) >= chunk_size:
                            if writer is not None:
                                written += writer.stage(buffer)
                            else:
                                written += self._store.bulk_upsert(
                                    buffer,
                                    chunk_size=chunk_size,
                                    maintain_status_stats=False,
                                    insert_only=insert_only,
                                    relaxed_commit=True,
                                )
                            buffer.clear()
                            now = time.time()
                            if now - last_progress_report >= 0.5:
                                self._store.upsert_status(
                                    library_id,
                                    status='syncing',
                                    watcher_mode='disabled',
                                    total_entries=written,
                                    total_size_bytes=total_size,
                                    folder_count=folder_count,
                                )
                                last_progress_report = now
                    if buffer:
                        if writer is not None:
                            written += writer.stage(buffer)
                        else:
                            written += self._store.bulk_upsert(
                                buffer,
                                chunk_size=chunk_size,
                                maintain_status_stats=False,
                                insert_only=insert_only,
                                relaxed_commit=True,
                            )

                    stale_removed = 0
                    if writer is not None:
                        merge_result = writer.finish(delete_chunk_size=chunk_size)
                        written = int(merge_result.get("total_entries") or written)
                        total_size = int(merge_result.get("total_size_bytes") or total_size)
                        folder_count = int(merge_result.get("folder_count") or folder_count)
                        stale_removed = int(merge_result.get("deleted") or 0)
                        logger.info(
                            "[索引] staging 合并完成 library=%s staged=%s inserted=%s updated=%s deleted=%s",
                            library_id,
                            merge_result.get("staged"),
                            merge_result.get("inserted"),
                            merge_result.get("updated"),
                            stale_removed,
                        )
                    elif not insert_only:
                        stale_removed = self._store.delete_stale_library_entries(
                            library_id,
                            indexed_before_ms=rebuild_started_ms,
                            chunk_size=chunk_size,
                            relaxed_commit=True,
                        )
            if (
                writer is None
                and written >= FULL_REBUILD_ANALYZE_THRESHOLD
                and not bool((maintenance or {}).get("active"))
            ):
                self._store.analyze_entries_for_query_planner(clean_trigram_pending=True)
            now_ms = int(time.time() * 1000)
            status = self._store.upsert_status(
                library_id,
                status='ready',
                watcher_mode='disabled',
                last_full_scan_at=now_ms,
                total_entries=written,
                total_size_bytes=total_size,
                folder_count=folder_count,
                error=None,
            )
            elapsed = time.time() - started
            logger.info(
                "[索引] 重建完成 library=%s entries=%s stale_removed=%s elapsed=%.2fs",
                library_id, written, stale_removed, elapsed,
            )
            return status
        except Exception as exc:  # noqa: BLE001 顶层兑底
            logger.exception("[索引] 重建失败 library=%s", library_id)
            return self._store.upsert_status(
                library_id,
                status='error',
                error=str(exc),
            )

    async def schedule_rebuild_local(
        self,
        library_id: str,
        root_path: str,
    ) -> IndexStatus:
        """异步后台触发：立即把状态置为 syncing 并返回，扫描在 thread 里跑。"""
        status = self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error=None,
        )

        async def _run() -> None:
            try:
                await asyncio.to_thread(self.rebuild_local, library_id, root_path)
            except Exception:
                logger.exception("[索引] 异步重建任务异常 library=%s", library_id)

        task = asyncio.create_task(_run())
        self._track_rebuild_task(library_id, task)
        return status

    async def rebuild_remote(
        self,
        library_id: str,
        client: Any,
        root_path: str,
        *,
        chunk_size: int = FULL_REBUILD_BULK_CHUNK_SIZE,
    ) -> IndexStatus:
        """远程群晖库不再创建库存索引，保留方法只做兼容 no-op。"""
        logger.info("[索引] remote rebuild 已禁用，跳过远程库存索引创建 library=%s", library_id)
        return self._store.upsert_status(
            library_id,
            status='disabled',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error="远程群晖库存不创建库存索引，请使用 FileStation 原生浏览/搜索",
        )

    async def _do_rebuild_remote(
        self,
        library_id: str,
        client: Any,
        root_path: str,
        chunk_size: int,
    ) -> IndexStatus:
        started = time.time()
        rebuild_started_ms = int(started * 1000)
        logger.info(
            "[索引] 开始重建远程库存 library=%s root=%s",
            library_id, root_path,
        )

        self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error=None,
        )

        try:
            async def _count_root_children() -> int:
                try:
                    if root_path == "/":
                        data = await client.list_share(offset=0, limit=1, sort_by="name", sort_direction="asc")
                        return int(data.get("total") or len(data.get("shares") or data.get("files") or []))
                    data = await client.list(root_path, offset=0, limit=1, sort_by="name", sort_direction="asc")
                    return int(data.get("total") or len(data.get("files") or []))
                except Exception:
                    logger.debug("[索引] 远程根目录直列校验失败 library=%s root=%s", library_id, root_path, exc_info=True)
                    return -1

            scanner = self._remote_scanner_factory()

            # 流式：每攒满 chunk_size 就 bulk_upsert 一次，避免内存堆积。
            # 同时每 0.5s 上报一次 syncing 进度，让前端圆环能看到实时增长。
            buffer: list[IndexEntry] = []
            written = 0
            total_size = 0
            folder_count = 0
            insert_only = not self._store_has_library_entries(library_id)
            initial_bulk_load = insert_only and not self._store_has_any_entries()
            last_progress_report = time.time()
            rebuild_writer = None
            if not insert_only:
                rebuild_writer = self._store.create_rebuild_writer(
                    library_id,
                    chunk_size=chunk_size,
                    relaxed_commit=True,
                )
            with self._initial_bulk_load_search_index_context(initial_bulk_load) as maintenance:
                if maintenance.get("active"):
                    logger.info(
                        "[索引] 首次远程全量构建暂停库存二级索引 library=%s dropped=%s",
                        library_id,
                        maintenance.get("dropped") or [],
                    )
                elif initial_bulk_load and maintenance.get("skipped"):
                    logger.info(
                        "[索引] 首次远程全量构建未暂停库存二级索引 library=%s reason=%s",
                        library_id,
                        maintenance.get("reason"),
                    )
                with rebuild_writer or nullcontext(None) as writer:
                    # 先拿全局远程 search 串行锁，再拿 remote_fs 预算，保证群晖端任一时刻
                    # 只跑一个递归 search task，且避免预算令牌互锁（详见文件顶部说明）。
                    async with _get_remote_search_lock():
                        async with get_resource_budget_service().acquire("remote_fs", weight=2, reason="library_index.remote_rebuild"):
                            async for entry in scanner.scan(library_id, client, root_path):
                                buffer.append(entry)
                                size_delta, folder_delta = self._entry_stats(entry)
                                total_size += size_delta
                                folder_count += folder_delta
                                if len(buffer) >= chunk_size:
                                    if writer is not None:
                                        written += writer.stage(buffer)
                                    else:
                                        written += self._store.bulk_upsert(
                                            buffer,
                                            chunk_size=chunk_size,
                                            maintain_status_stats=False,
                                            insert_only=insert_only,
                                            relaxed_commit=True,
                                        )
                                    buffer.clear()
                                    now = time.time()
                                    if now - last_progress_report >= 0.5:
                                        self._store.upsert_status(
                                            library_id,
                                            status='syncing',
                                            watcher_mode='disabled',
                                            total_entries=written,
                                            total_size_bytes=total_size,
                                            folder_count=folder_count,
                                        )
                                        last_progress_report = now
                    if buffer:
                        if writer is not None:
                            written += writer.stage(buffer)
                        else:
                            written += self._store.bulk_upsert(
                                buffer,
                                chunk_size=chunk_size,
                                maintain_status_stats=False,
                                insert_only=insert_only,
                                relaxed_commit=True,
                            )

                    if written <= 0:
                        root_children = await _count_root_children()
                        if root_children > 0:
                            message = (
                                f"远程搜索重建返回 0 条，但根目录直列可见 {root_children} 条，"
                                "本次结果疑似异常，已保留旧索引并标记错误"
                            )
                            logger.warning("[索引] %s library=%s root=%s", message, library_id, root_path)
                            return self._store.upsert_status(
                                library_id,
                                status='error',
                                watcher_mode='disabled',
                                error=message,
                            )

                    stale_removed = 0
                    if writer is not None:
                        merge_result = writer.finish(delete_chunk_size=chunk_size)
                        written = int(merge_result.get("total_entries") or written)
                        total_size = int(merge_result.get("total_size_bytes") or total_size)
                        folder_count = int(merge_result.get("folder_count") or folder_count)
                        stale_removed = int(merge_result.get("deleted") or 0)
                        logger.info(
                            "[索引] 远程 staging 合并完成 library=%s staged=%s inserted=%s updated=%s deleted=%s",
                            library_id,
                            merge_result.get("staged"),
                            merge_result.get("inserted"),
                            merge_result.get("updated"),
                            stale_removed,
                        )
                    elif not insert_only:
                        stale_removed = self._store.delete_stale_library_entries(
                            library_id,
                            indexed_before_ms=rebuild_started_ms,
                            chunk_size=chunk_size,
                            relaxed_commit=True,
                        )
            if (
                writer is None
                and written >= FULL_REBUILD_ANALYZE_THRESHOLD
                and not bool((maintenance or {}).get("active"))
            ):
                self._store.analyze_entries_for_query_planner(clean_trigram_pending=True)
            now_ms = int(time.time() * 1000)
            status = self._store.upsert_status(
                library_id,
                status='ready',
                watcher_mode='disabled',
                last_full_scan_at=now_ms,
                total_entries=written,
                total_size_bytes=total_size,
                folder_count=folder_count,
                error=None,
            )
            elapsed = time.time() - started
            logger.info(
                "[索引] 远程重建完成 library=%s entries=%s stale_removed=%s elapsed=%.2fs",
                library_id, written, stale_removed, elapsed,
            )
            return status
        except Exception as exc:  # noqa: BLE001 顶层兜底
            logger.exception("[索引] 远程重建失败 library=%s", library_id)
            return self._store.upsert_status(
                library_id,
                status='error',
                error=str(exc),
            )

    async def schedule_rebuild_remote(
        self,
        library_id: str,
        client_factory: Any,
        root_path: str,
        *,
        force: bool = False,
    ) -> IndexStatus:
        """远程群晖库不再创建库存索引，保留方法只做兼容 no-op。"""
        logger.info("[索引] schedule remote rebuild 已禁用，跳过远程库存索引创建 library=%s", library_id)
        return self._store.upsert_status(
            library_id,
            status='disabled',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error="远程群晖库存不创建库存索引，请使用 FileStation 原生浏览/搜索",
        )

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

    def _initial_bulk_load_search_index_context(self, enabled: bool):
        if not enabled:
            return nullcontext({"active": False, "skipped": False, "dropped": [], "restored": []})
        return suspend_library_index_secondary_indexes_for_initial_bulk_load(
            getattr(self._store, "bind_engine", None),
        )

    def _store_has_any_entries(self) -> bool:
        checker = getattr(self._store, "has_any_entries", None)
        if not callable(checker):
            return True
        return bool(checker())

    def _store_has_library_entries(self, library_id: str) -> bool:
        checker = getattr(self._store, "has_library_entries", None)
        if callable(checker):
            return bool(checker(library_id))
        counter = getattr(self._store, "count_library_entries", None)
        if callable(counter):
            return int(counter(library_id) or 0) > 0
        return True

    def _has_running_rebuild_task(self, library_id: str) -> bool:
        tasks = self._pending_tasks_by_library.get(library_id) or set()
        return any(not task.done() for task in list(tasks))

    def _syncing_status_is_stale(self, status: IndexStatus) -> bool:
        updated_at = int(getattr(status, "updated_at", 0) or 0)
        if updated_at <= 0:
            return True
        age_seconds = time.time() - updated_at / 1000.0
        return age_seconds >= STALE_SYNCING_GRACE_SECONDS

    def _entry_stats_snapshot(self, library_id: str) -> dict[str, int]:
        calculator = getattr(self._store, "calculate_library_stats", None)
        if callable(calculator):
            stats = calculator(library_id) or {}
            return {
                "total_entries": int(stats.get("total_entries") or 0),
                "total_size_bytes": int(stats.get("total_size_bytes") or 0),
                "folder_count": int(stats.get("folder_count") or 0),
            }
        return {
            "total_entries": int(getattr(self._store, "count_library_entries")(library_id) or 0)
            if callable(getattr(self._store, "count_library_entries", None))
            else 0,
            "total_size_bytes": 0,
            "folder_count": 0,
        }

    def normalize_interrupted_syncing_status(
        self,
        library_id: str,
    ) -> Optional[IndexStatus]:
        """进程重启后把遗留 syncing 收敛掉，不自动重建库存索引。"""
        status = self._store.get_status(library_id)
        if not status or status.status != 'syncing':
            return status
        if self._has_running_rebuild_task(library_id) or not self._syncing_status_is_stale(status):
            return status

        has_completed_snapshot = int(getattr(status, "last_full_scan_at", 0) or 0) > 0
        stats = self._entry_stats_snapshot(library_id)
        if has_completed_snapshot:
            logger.warning(
                "[索引] 检测到中断的同步状态，恢复为 ready library=%s entries=%s",
                library_id,
                stats["total_entries"],
            )
            return self._store.upsert_status(
                library_id,
                status='ready',
                watcher_mode='disabled',
                total_entries=stats["total_entries"],
                total_size_bytes=stats["total_size_bytes"],
                folder_count=stats["folder_count"],
                error=INTERRUPTED_SYNCING_MESSAGE,
            )

        logger.warning(
            "[索引] 检测到未完成的同步状态，恢复为 error library=%s",
            library_id,
        )
        return self._store.upsert_status(
            library_id,
            status='error',
            watcher_mode='disabled',
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
            error=INTERRUPTED_SYNCING_MESSAGE,
        )

    def normalize_all_interrupted_syncing_statuses(self) -> list[IndexStatus]:
        normalized: list[IndexStatus] = []
        for status in self._store.list_all_status():
            if status.status == 'syncing':
                next_status = self.normalize_interrupted_syncing_status(status.library_id)
                if next_status is not None:
                    normalized.append(next_status)
            else:
                normalized.append(status)
        return normalized

    # ========== self_mutation ==========
    # 业务自身写操作（rename / delete / move / 解压落地 / 字幕落盘）完成后
    # 主动调用，立即同步索引，不依赖 watcher。watcher 只兜底外部变更。

    def handle_self_mutation_upsert(self, entry: IndexEntry) -> None:
        """单条 upsert：业务创建 / 更新一个目录或文件后调用。"""
        self._store.upsert(entry)

    def handle_self_mutation_delete(
        self,
        library_id: str,
        relative_path: str,
    ) -> int:
        """单条 delete：业务删除目录 / 文件后调用，连子树一起清掉。"""
        return self._store.delete_subtree(library_id, relative_path)

    def handle_self_mutation_batch(
        self,
        library_id: str,
        *,
        upserts: Optional[list[IndexEntry]] = None,
        deletes: Optional[list[str]] = None,
    ) -> dict:
        """批量自更新：deletes / upserts 各自合并到一个事务里。

        典型场景：
        - 批量分类：把一批 RJ 从旧路径移到新路径
            handle_self_mutation_batch(
                lib_id,
                upserts=new_subtree_entries,
                deletes=old_relative_paths,
            )
        - 批量删除：用户在浏览器里勾选 N 个 RJ 删掉
            handle_self_mutation_batch(lib_id, deletes=[rj1, rj2, ...])

        返回 {"upserts": int, "deletes": int} 实际生效的条目数。
        """
        result = {"upserts": 0, "deletes": 0}
        if upserts:
            result["upserts"] = self._store.bulk_upsert(
                upserts,
                chunk_size=500,
                maintain_parent_dir_stats=True,
            )
        if deletes:
            result["deletes"] = self._store.delete_subtrees(
                library_id, deletes,
            )
        return result

    def handle_self_mutation_move(
        self,
        *,
        source_library_id: str,
        target_library_id: str,
        old_relative_path: str,
        new_relative_path: str,
        old_absolute_path: str,
        new_absolute_path: str,
    ) -> int:
        """移动/重命名索引 fast-path，不扫磁盘。

        - 同库：单条 SQL UPDATE 前缀改写。
        - 跨库：数据库内 INSERT...SELECT 搬迁，再批量删除源子树。

        返回命中的索引条数；0 表示旧索引缺失，调用方可 fallback 到扫新子树。
        """
        if source_library_id == target_library_id:
            return self._store.move_subtree_same_library(
                source_library_id,
                old_relative_path=old_relative_path,
                new_relative_path=new_relative_path,
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
            )
        return self._store.move_subtree_between_libraries(
            source_library_id,
            target_library_id,
            old_relative_path=old_relative_path,
            new_relative_path=new_relative_path,
            old_absolute_path=old_absolute_path,
            new_absolute_path=new_absolute_path,
        )

    def handle_self_mutation_move_many(
        self,
        moves: list[dict[str, str]],
    ) -> list[int]:
        """批量移动/重命名索引 fast-path，按库组合并到尽量少的事务。"""
        if not moves:
            return []

        results = [0 for _ in moves]
        same_library_groups: dict[str, list[dict[str, str]]] = {}
        cross_library_groups: dict[tuple[str, str], list[dict[str, str]]] = {}

        for index, raw in enumerate(moves):
            item = dict(raw or {})
            item["_index"] = index
            source_library_id = str(item.get("source_library_id") or "").strip()
            target_library_id = str(item.get("target_library_id") or "").strip()
            if not source_library_id or not target_library_id:
                continue
            if source_library_id == target_library_id:
                same_library_groups.setdefault(source_library_id, []).append(item)
            else:
                cross_library_groups.setdefault((source_library_id, target_library_id), []).append(item)

        for library_id, group in same_library_groups.items():
            moved_counts = self._store.move_subtrees_same_library(library_id, group)
            for item, moved in zip(group, moved_counts):
                results[int(item["_index"])] = int(moved or 0)

        for (source_library_id, target_library_id), group in cross_library_groups.items():
            moved_counts = self._store.move_subtrees_between_libraries(
                source_library_id,
                target_library_id,
                group,
            )
            for item, moved in zip(group, moved_counts):
                results[int(item["_index"])] = int(moved or 0)

        return results

    # ========== self_mutation：增量 upsert 子树 ==========
    # 业务自身写操作（解压入库 / rename / 远程上传 / 字幕落盘 / 冲突重绑等）
    # 完成后调用，把刚刚创建/落地的子树立即扫描 + bulk_upsert 到索引，
    # 避免依赖手动重建。
    #
    # 设计要点：
    # - 索引未就绪（idle / syncing / error）时跳过：完整扫描完成后会覆盖一切，
    #   不需要中间状态做 upsert 抢跑
    # - 不更新 last_event_at / total_entries：和 delete 路径一致，
    #   状态字段只在全量 rebuild 时刷新
    # - 任何异常都向上抛，由调用方（library_manager 包装层）catch 后静默

    def _subtree_parent_stats_delta(self, library_id: str, relative_path: str) -> Optional[_SubtreeParentStatsDelta]:
        normalized = str(relative_path or "").strip("/")
        if not normalized:
            return None
        old_entry = self._store.get_entry(library_id, normalized)
        return _SubtreeParentStatsDelta(
            relative_path=normalized,
            old_size=int(getattr(old_entry, "size", 0) or 0) if old_entry else 0,
            old_file_count=(
                int(getattr(old_entry, "file_count", 0) or 0)
                if old_entry and old_entry.entry_type == 'dir'
                else (1 if old_entry and old_entry.entry_type == 'file' else 0)
            ),
        )

    def _capture_subtree_parent_stats_delta(
        self,
        delta: Optional[_SubtreeParentStatsDelta],
        entry: IndexEntry,
    ) -> None:
        if delta is None or entry.relative_path != delta.relative_path:
            return
        delta.new_size = max(0, int(entry.size or 0))
        delta.new_file_count = max(0, int(entry.file_count or 0)) if entry.entry_type == 'dir' else 1

    def _flush_subtree_parent_stats_delta(
        self,
        library_id: str,
        delta: Optional[_SubtreeParentStatsDelta],
    ) -> None:
        if delta is None:
            return
        if not (delta.size_delta or delta.file_count_delta):
            return
        self._store.apply_parent_dir_delta(
            library_id,
            delta.relative_path,
            size_delta=delta.size_delta,
            file_count_delta=delta.file_count_delta,
        )

    def upsert_subtree_local(
        self,
        library_id: str,
        library_root: str,
        subtree_path: str,
        *,
        chunk_size: int = DEFAULT_BULK_UPSERT_CHUNK_SIZE,
    ) -> int:
        """同步全量扫指定本地子树并 bulk_upsert。

        返回 upsert 的条目数。索引未就绪时返回 0。
        """
        if not self.is_ready(library_id):
            return 0
        scanner = self._local_scanner_factory()
        buffer: list[IndexEntry] = []
        written = 0
        relative_path = os.path.relpath(os.path.abspath(subtree_path), os.path.abspath(library_root)).replace("\\", "/")
        if relative_path == ".":
            relative_path = ""
        relative_path = relative_path.strip("/")
        stats_delta = self._subtree_parent_stats_delta(library_id, relative_path)
        if stats_delta is not None and relative_path:
            stats_delta.new_size = stats_delta.old_size
            stats_delta.new_file_count = stats_delta.old_file_count
        for entry in scanner.scan_subtree(library_id, library_root, subtree_path):
            self._capture_subtree_parent_stats_delta(stats_delta, entry)
            buffer.append(entry)
            if len(buffer) >= chunk_size:
                written += self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_parent_dir_stats=False,
                )
                buffer.clear()
        if buffer:
            written += self._store.bulk_upsert(
                buffer,
                chunk_size=chunk_size,
                maintain_parent_dir_stats=False,
            )
        self._flush_subtree_parent_stats_delta(library_id, stats_delta)
        logger.info(
            "[索引] upsert 本地子树完成 library=%s subtree=%s entries=%s",
            library_id, subtree_path, written,
        )
        return written

    async def upsert_subtree_remote(
        self,
        library_id: str,
        client: Any,
        library_root: str,
        subtree_path: str,
        *,
        chunk_size: int = DEFAULT_BULK_UPSERT_CHUNK_SIZE,
    ) -> int:
        """异步全量扫指定远程子树并 bulk_upsert。

        SYNO.FileStation.Search 不返回 folder_path 自身那一行，所以这里会先
        用 client.stat(subtree_path) 补一条子树根目录的 IndexEntry，避免
        find_by_rjcode 找不到 RJ 目录本身。

        返回 upsert 的条目数。索引未就绪时返回 0。
        """
        if not self.is_ready(library_id):
            return 0

        # 1) 子树根目录条目：SYNO.Search 不会返回它，必须显式构造
        root_entry = await self._build_remote_subtree_root_entry(
            library_id, client, library_root, subtree_path,
        )

        # 2) 扫所有后代
        scanner = self._remote_scanner_factory()
        buffer: list[IndexEntry] = []
        if root_entry is not None:
            buffer.append(root_entry)
        relative_path = self._remote_relative_path(library_root, subtree_path)
        stats_delta = self._subtree_parent_stats_delta(library_id, relative_path)
        if root_entry is not None:
            self._capture_subtree_parent_stats_delta(stats_delta, root_entry)
        written = 0
        # 与全量重建共用同一把全局远程 search 串行锁：子树扫描同样是 SYNO.Search
        # task，必须和全量重建互斥，避免高频写操作触发的子树扫描和全量重建在群晖端
        # 同时起多个 search task。锁只包住扫描循环，stat 补根行（普通请求）不持锁。
        async with _get_remote_search_lock():
            async for entry in scanner.scan_subtree(
                library_id, client, library_root, subtree_path,
            ):
                self._capture_subtree_parent_stats_delta(stats_delta, entry)
                buffer.append(entry)
                if len(buffer) >= chunk_size:
                    written += self._store.bulk_upsert(
                        buffer,
                        chunk_size=chunk_size,
                        maintain_parent_dir_stats=False,
                    )
                    buffer.clear()
            if buffer:
                written += self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_parent_dir_stats=False,
                )
        self._flush_subtree_parent_stats_delta(library_id, stats_delta)
        logger.info(
            "[索引] upsert 远程子树完成 library=%s subtree=%s entries=%s",
            library_id, subtree_path, written,
        )
        return written

    @staticmethod
    def _remote_relative_path(library_root: str, subtree_path: str) -> str:
        root = (library_root or "").replace("\\", "/").rstrip("/") or "/"
        target = (subtree_path or "").replace("\\", "/").rstrip("/") or "/"
        if target == root:
            return ""
        prefix = root + "/" if root != "/" else "/"
        return target[len(prefix):].strip("/") if target.startswith(prefix) else target.lstrip("/")

    async def _build_remote_subtree_root_entry(
        self,
        library_id: str,
        client: Any,
        library_root: str,
        subtree_path: str,
    ) -> Optional[IndexEntry]:
        """对子树根目录（SYNO.Search 不会返回的那一行）做一次 stat，
        构造对应的 IndexEntry。stat 失败返回 None，由调用方自行决定是否
        放弃整次 upsert。
        """
        try:
            info = await client.stat(subtree_path)
        except Exception:
            logger.warning(
                "[索引] 子树根 stat 失败，跳过补行 library=%s subtree=%s",
                library_id, subtree_path, exc_info=True,
            )
            return None

        item: Optional[dict] = None
        if isinstance(info, dict):
            files = info.get("files")
            if isinstance(files, list) and files:
                item = files[0]
            else:
                item = info
        if not isinstance(item, dict):
            return None

        absolute_path = str(item.get("path") or subtree_path).rstrip("/") or "/"
        is_dir = bool(item.get("isdir", True))
        name = str(
            item.get("name")
            or absolute_path.rsplit("/", 1)[-1]
            or absolute_path
        )
        from ._helpers import extract_rjcode

        norm_root = (library_root or "").rstrip("/") or "/"
        if absolute_path == norm_root:
            relative = ""
            parent: Optional[str] = None
            depth = 0
        else:
            prefix = norm_root + "/" if norm_root != "/" else "/"
            relative = (
                absolute_path[len(prefix):]
                if absolute_path.startswith(prefix)
                else absolute_path.lstrip("/")
            )
            parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
            depth = relative.count("/") + 1 if relative else 0

        additional = item.get("additional") or {}
        size_raw = additional.get("size")
        try:
            size_value = int(size_raw) if size_raw not in (None, "") else 0
        except (TypeError, ValueError):
            size_value = 0
        time_info = additional.get("time") or {}
        mtime_seconds_raw = time_info.get("mtime")
        try:
            mtime_seconds = int(mtime_seconds_raw) if mtime_seconds_raw else None
        except (TypeError, ValueError):
            mtime_seconds = None
        mtime_ms = mtime_seconds * 1000 if mtime_seconds else None

        return IndexEntry(
            library_id=library_id,
            entry_type='dir' if is_dir else 'file',
            relative_path=relative,
            absolute_path=absolute_path,
            name=name,
            rjcode=extract_rjcode(name),
            parent_path=parent,
            size=0 if is_dir else size_value,
            file_count=0,
            mtime=mtime_ms,
            depth=depth,
        )

    # ========== 状态 ==========

    def get_status(self, library_id: str) -> Optional[IndexStatus]:
        return self.normalize_interrupted_syncing_status(library_id)

    def list_all_status(self) -> list[IndexStatus]:
        return self.normalize_all_interrupted_syncing_statuses()

    def is_ready(self, library_id: str) -> bool:
        status = self.get_status(library_id)
        return bool(
            status
            and status.status == 'ready'
            and int(getattr(status, "accepted_seq", 0) or 0)
            == int(getattr(status, "materialized_seq", 0) or 0)
            and getattr(status, "building_generation", None) is None
        )

    def has_usable_snapshot(self, library_id: str) -> bool:
        """读路径可用性：ready 或 syncing 且库里已有快照。

        远程全量重建会先把状态置为 syncing，再在 staging 表里构建新快照；
        旧快照此时仍然可以安全服务浏览 / 搜索。读路径如果只认 ready，
        重建期间会退回 FileStation walk，反而打爆群晖。
        """
        status = self.get_status(library_id)
        if not status or status.status not in {'ready', 'syncing'}:
            return False
        return self._store_has_library_entries(library_id)

    def has_library_entries(self, library_id: str) -> bool:
        """调用方需要区分 ready 空快照和真实有条目的快照。"""
        return self._store_has_library_entries(library_id)

    # ========== 查询包装 ==========

    def find_by_rjcode(
        self,
        rjcode: str,
        library_id: Optional[Union[str, Sequence[str]]] = None,
        *,
        entry_type: Optional[str] = 'dir',
        limit: int = 100,
    ) -> list[IndexEntry]:
        """按 RJ 号精确查。

        library_id 透传到 SnapshotStore.find_by_rjcode：
        - str → 单库存
        - None / 空序列 → 跨全部库存
        - Sequence[str] → 多库存（IN 查询）
        """
        return self._store.find_by_rjcode(
            library_id, rjcode, entry_type=entry_type, limit=limit,
        )

    def find_by_rjcodes(
        self,
        rjcodes: Sequence[str],
        library_id: Optional[Union[str, Sequence[str]]] = None,
        *,
        entry_type: Optional[str] = 'dir',
        limit: int = 100,
    ) -> list[IndexEntry]:
        """批量按 RJ 精确查，避免关联翻译号逐个建立数据库会话。"""
        return self._store.find_by_rjcodes(
            library_id,
            rjcodes,
            entry_type=entry_type,
            limit=limit,
        )

    def find_by_name(
        self,
        library_id: Optional[Union[str, Sequence[str]]],
        name_like: str,
        *,
        entry_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[IndexEntry]:
        """按名称模糊搜索。

        library_id 透传到 SnapshotStore.find_by_name：
        - str → 单库存
        - None / 空序列 → 跨全部库存
        - Sequence[str] → 多库存（IN 查询）
        """
        return self._store.find_by_name(
            library_id, name_like, entry_type=entry_type, limit=limit,
        )

    def list_children(
        self,
        library_id: str,
        parent_path: str = '',
        *,
        entry_type: Optional[str] = None,
    ) -> list[IndexEntry]:
        return self._store.list_children(
            library_id, parent_path, entry_type=entry_type,
        )

    def list_children_page(
        self,
        library_id: str,
        parent_path: str = '',
        *,
        entry_type: Optional[str] = None,
        sort_by: str = "name",
        sort_order: str = "asc",
        offset: int = 0,
        limit: Optional[int] = 200,
        page_cursor: Optional[str] = None,
    ) -> dict[str, object]:
        return self._store.list_children_page(
            library_id,
            parent_path,
            entry_type=entry_type,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=limit,
            page_cursor=page_cursor,
            include_total=True,
        )

    def list_subtree_entries(
        self,
        library_id: str,
        relative_path: str = '',
        *,
        include_self: bool = True,
        entry_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[IndexEntry]:
        return self._store.list_subtree_entries(
            library_id,
            relative_path,
            include_self=include_self,
            entry_type=entry_type,
            limit=limit,
        )

    def get_entry(self, library_id: str, relative_path: str) -> Optional[IndexEntry]:
        return self._store.get_entry(library_id, relative_path)

    def get_library_size(self, library_id: str) -> int:
        stats = self._store.get_library_stats(library_id)
        return int(stats.get("total_size_bytes") or 0)

    def get_library_stats(
        self,
        library_id: str,
        *,
        parent_path: str = '',
    ) -> dict[str, int]:
        return self._store.get_library_stats(
            library_id,
            parent_path=parent_path,
        )

    def count_descendant_dirs_many(
        self,
        library_id: str,
        relative_paths: Sequence[str],
    ) -> dict[str, int]:
        return self._store.count_descendant_dirs_many(library_id, relative_paths)

    def summarize_descendant_files_many(
        self,
        library_id: str,
        relative_paths: Sequence[str],
    ) -> dict[str, dict[str, int]]:
        return self._store.summarize_descendant_files_many(library_id, relative_paths)


_default_service: Optional[LibraryIndexService] = None


def get_library_index_service() -> LibraryIndexService:
    """进程内单例访问器。"""
    global _default_service
    if _default_service is None:
        _default_service = LibraryIndexService()
    return _default_service
