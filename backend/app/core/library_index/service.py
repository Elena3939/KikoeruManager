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

批次 2 范围：仅支持 local 库存。synology_filestation 由批次 3
新增 RemoteScanner 后再扩展。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from .local_scanner import LocalScanner
from .remote_scanner import RemoteScanner
from .snapshot_store import SnapshotStore, get_snapshot_store
from .types import IndexEntry, IndexStatus

logger = logging.getLogger(__name__)


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

    # ========== 锁 ==========

    def _get_lock(self, library_id: str) -> threading.Lock:
        with self._global_lock:
            lock = self._rebuild_locks.get(library_id)
            if lock is None:
                lock = threading.Lock()
                self._rebuild_locks[library_id] = lock
            return lock

    # ========== 重建 ==========

    def rebuild_local(
        self,
        library_id: str,
        root_path: str,
        *,
        chunk_size: int = 500,
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
        logger.info("[索引] 开始重建本地库存 library=%s root=%s", library_id, root_path)

        # 起始置 syncing；error 显式 None 清理上一轮失败痕迹
        self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            error=None,
        )

        try:
            removed = self._store.delete_library(library_id)
            if removed:
                logger.info("[索引] 清掉旧索引 library=%s removed=%s", library_id, removed)

            scanner = self._local_scanner_factory()
            written = self._store.bulk_upsert(
                scanner.scan(library_id, root_path),
                chunk_size=chunk_size,
            )

            now_ms = int(time.time() * 1000)
            status = self._store.upsert_status(
                library_id,
                status='ready',
                watcher_mode='disabled',
                last_full_scan_at=now_ms,
                total_entries=written,
                error=None,
            )
            elapsed = time.time() - started
            logger.info(
                "[索引] 重建完成 library=%s entries=%s elapsed=%.2fs",
                library_id, written, elapsed,
            )
            return status
        except Exception as exc:  # noqa: BLE001 顶层兜底
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
            error=None,
        )

        async def _run() -> None:
            try:
                await asyncio.to_thread(self.rebuild_local, library_id, root_path)
            except Exception:
                logger.exception("[索引] 异步重建任务异常 library=%s", library_id)

        task = asyncio.create_task(_run())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return status

    async def rebuild_remote(
        self,
        library_id: str,
        client: Any,
        root_path: str,
        *,
        chunk_size: int = 500,
    ) -> IndexStatus:
        """async 全量重建远程（群晖 FileStation）库存索引。

        线程安全：同库存并发只允许一个；后续 rebuild 会立即返回当前 syncing
        状态而不会阻塞，避免远程扫描互相挤占。
        """
        lock = self._get_lock(library_id)
        if not lock.acquire(blocking=False):
            existing = self._store.get_status(library_id)
            if existing and existing.status == 'syncing':
                logger.info("[索引] remote rebuild 跳过：%s 正在同步", library_id)
                return existing
            # 远程扫描耗时较长，没拿到锁不阻塞，直接返回当前状态
            return existing or self._store.upsert_status(
                library_id, status='syncing', watcher_mode='disabled',
            )
        try:
            return await self._do_rebuild_remote(
                library_id, client, root_path, chunk_size,
            )
        finally:
            lock.release()

    async def _do_rebuild_remote(
        self,
        library_id: str,
        client: Any,
        root_path: str,
        chunk_size: int,
    ) -> IndexStatus:
        started = time.time()
        logger.info(
            "[索引] 开始重建远程库存 library=%s root=%s",
            library_id, root_path,
        )

        self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            error=None,
        )

        try:
            removed = self._store.delete_library(library_id)
            if removed:
                logger.info(
                    "[索引] 清掉旧索引 library=%s removed=%s",
                    library_id, removed,
                )

            scanner = self._remote_scanner_factory()

            # 流式：每攒满 chunk_size 就 bulk_upsert 一次，避免内存堆积
            buffer: list[IndexEntry] = []
            written = 0
            async for entry in scanner.scan(library_id, client, root_path):
                buffer.append(entry)
                if len(buffer) >= chunk_size:
                    written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)
                    buffer.clear()
            if buffer:
                written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)

            now_ms = int(time.time() * 1000)
            status = self._store.upsert_status(
                library_id,
                status='ready',
                watcher_mode='disabled',
                last_full_scan_at=now_ms,
                total_entries=written,
                error=None,
            )
            elapsed = time.time() - started
            logger.info(
                "[索引] 远程重建完成 library=%s entries=%s elapsed=%.2fs",
                library_id, written, elapsed,
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
    ) -> IndexStatus:
        """异步后台触发远程重建。

        client_factory：可调用对象（同步 / 异步均可）或者已经实例化的 client。
        因为远程客户端有连接 / 认证状态，让后台 task 启动时再获取最稳妥；
        如果传入的是 client 实例则直接使用。
        """
        status = self._store.upsert_status(
            library_id,
            status='syncing',
            watcher_mode='disabled',
            error=None,
        )

        async def _run() -> None:
            try:
                client = (
                    client_factory()
                    if callable(client_factory)
                    else client_factory
                )
                if asyncio.iscoroutine(client):
                    client = await client
                await self.rebuild_remote(library_id, client, root_path)
            except Exception:
                logger.exception(
                    "[索引] 异步远程重建任务异常 library=%s",
                    library_id,
                )

        task = asyncio.create_task(_run())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return status

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
                upserts, chunk_size=500,
            )
        if deletes:
            result["deletes"] = self._store.delete_subtrees(
                library_id, deletes,
            )
        return result

    # ========== 状态 ==========

    def get_status(self, library_id: str) -> Optional[IndexStatus]:
        return self._store.get_status(library_id)

    def list_all_status(self) -> list[IndexStatus]:
        return self._store.list_all_status()

    def is_ready(self, library_id: str) -> bool:
        status = self.get_status(library_id)
        return bool(status and status.status == 'ready')

    # ========== 查询包装 ==========

    def find_by_rjcode(
        self,
        rjcode: str,
        library_id: Optional[str] = None,
        *,
        entry_type: Optional[str] = 'dir',
        limit: int = 100,
    ) -> list[IndexEntry]:
        return self._store.find_by_rjcode(
            library_id, rjcode, entry_type=entry_type, limit=limit,
        )

    def find_by_name(
        self,
        library_id: str,
        name_like: str,
        *,
        entry_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[IndexEntry]:
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

    def get_entry(self, library_id: str, relative_path: str) -> Optional[IndexEntry]:
        return self._store.get_entry(library_id, relative_path)

    def get_library_size(self, library_id: str) -> int:
        return self._store.sum_library_size(library_id)


_default_service: Optional[LibraryIndexService] = None


def get_library_index_service() -> LibraryIndexService:
    """进程内单例访问器。"""
    global _default_service
    if _default_service is None:
        _default_service = LibraryIndexService()
    return _default_service
