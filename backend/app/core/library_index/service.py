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
from typing import Any, Optional, Sequence, Union

from .local_scanner import LocalScanner
from .remote_scanner import RemoteScanner
from ..resource_budget_service import get_resource_budget_service
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
            last_progress_report = time.time()
            for entry in scanner.scan(library_id, root_path):
                buffer.append(entry)
                size_delta, folder_delta = self._entry_stats(entry)
                total_size += size_delta
                folder_count += folder_delta
                if len(buffer) >= chunk_size:
                    written += self._store.bulk_upsert(
                        buffer,
                        chunk_size=chunk_size,
                        maintain_status_stats=False,
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
                written += self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_status_stats=False,
                )

            stale_removed = self._store.delete_stale_library_entries(
                library_id,
                indexed_before_ms=rebuild_started_ms,
                chunk_size=chunk_size,
            )
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
                library_id,
                status='syncing',
                watcher_mode='disabled',
                total_entries=0,
                total_size_bytes=0,
                folder_count=0,
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
            scanner = self._remote_scanner_factory()

            # 流式：每攒满 chunk_size 就 bulk_upsert 一次，避免内存堆积。
            # 同时每 0.5s 上报一次 syncing 进度，让前端圆环能看到实时增长。
            buffer: list[IndexEntry] = []
            written = 0
            total_size = 0
            folder_count = 0
            last_progress_report = time.time()
            async with get_resource_budget_service().acquire("remote_fs", weight=2, reason="library_index.remote_rebuild"):
                async for entry in scanner.scan(library_id, client, root_path):
                    buffer.append(entry)
                    size_delta, folder_delta = self._entry_stats(entry)
                    total_size += size_delta
                    folder_count += folder_delta
                    if len(buffer) >= chunk_size:
                        written += self._store.bulk_upsert(
                            buffer,
                            chunk_size=chunk_size,
                            maintain_status_stats=False,
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
                written += self._store.bulk_upsert(
                    buffer,
                    chunk_size=chunk_size,
                    maintain_status_stats=False,
                )

            stale_removed = self._store.delete_stale_library_entries(
                library_id,
                indexed_before_ms=rebuild_started_ms,
                chunk_size=chunk_size,
            )
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
            total_entries=0,
            total_size_bytes=0,
            folder_count=0,
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

    def upsert_subtree_local(
        self,
        library_id: str,
        library_root: str,
        subtree_path: str,
        *,
        chunk_size: int = 500,
    ) -> int:
        """同步全量扫指定本地子树并 bulk_upsert。

        返回 upsert 的条目数。索引未就绪时返回 0。
        """
        if not self.is_ready(library_id):
            return 0
        scanner = self._local_scanner_factory()
        buffer: list[IndexEntry] = []
        written = 0
        for entry in scanner.scan_subtree(library_id, library_root, subtree_path):
            buffer.append(entry)
            if len(buffer) >= chunk_size:
                written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)
                buffer.clear()
        if buffer:
            written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)
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
        chunk_size: int = 500,
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
        written = 0
        async for entry in scanner.scan_subtree(
            library_id, client, library_root, subtree_path,
        ):
            buffer.append(entry)
            if len(buffer) >= chunk_size:
                written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)
                buffer.clear()
        if buffer:
            written += self._store.bulk_upsert(buffer, chunk_size=chunk_size)
        logger.info(
            "[索引] upsert 远程子树完成 library=%s subtree=%s entries=%s",
            library_id, subtree_path, written,
        )
        return written

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


_default_service: Optional[LibraryIndexService] = None


def get_library_index_service() -> LibraryIndexService:
    """进程内单例访问器。"""
    global _default_service
    if _default_service is None:
        _default_service = LibraryIndexService()
    return _default_service
