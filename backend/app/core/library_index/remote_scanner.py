"""RemoteScanner：旧远程库存快照扫描器，当前业务入口已禁用。

该实现保留给历史测试和兼容引用；synology_filestation 库存现在不创建
library_index 快照，浏览 / 搜索统一回到群晖 FileStation 原生接口。

群晖端原生建索引器，单次 search task 拉回扁平的目录 + 文件列表。
对比 SMB 走 LocalScanner 的 os.scandir，性能差一个数量级以上：
- SMB scandir：每个 stat 都是网络 round trip，几十万项要数十分钟
- SYNO.Search：群晖端 CPU 跑，结果分页拉回，几分钟搞定
- Search 异常返回 0 时，自动退回 FileStation.List 递归扫描，避免把
  可见远程目录误写成 ready 空索引。

设计要点：
- 流式 yield：分页一边拉一边产出 IndexEntry，写库走 bulk_upsert chunk
- 容错：单条 entry 转换失败日志后跳过，不影响整体
- 资源回收：始终在 finally 里 stop_search，避免群晖端积累 task
- 不依赖 LibraryManager / settings：调用方传入已认证 client，方便测试 mock

限制：
- SYNO.FileStation.Search 对目录返回的 size 通常是 0（API 限制）
  库存总大小由 SnapshotStore.sum_library_size 走 SUM(file 行 size) 实现，
  不依赖目录行的 size，所以这里不强求精确。
"""
from __future__ import annotations

import asyncio
from collections import deque
import logging
import time
from typing import Any, AsyncIterator, Optional

from ._helpers import extract_rjcode, should_skip_name
from .types import IndexEntry

logger = logging.getLogger(__name__)


class RemoteScanner:
    """单库存 SYNO.FileStation.Search 全量扫描器。"""

    def __init__(
        self,
        *,
        page_size: int = 1000,
        wait_timeout_seconds: float = 600.0,
        wait_initial_delay: float = 0.3,
        wait_max_delay: float = 5.0,
    ):
        # SYNO.Search list 接口单次最多 1000 条
        self.page_size = max(1, min(int(page_size), 1000))
        self.wait_timeout_seconds = max(1.0, wait_timeout_seconds)
        self.wait_initial_delay = max(0.05, wait_initial_delay)
        self.wait_max_delay = max(self.wait_initial_delay, wait_max_delay)

    async def scan(
        self,
        library_id: str,
        client: Any,  # SynologyFileStationClient 或 mock
        root_path: str,
    ) -> AsyncIterator[IndexEntry]:
        """对 root_path 启动一次 search task，yield 所有 IndexEntry。

        异常：
        - root_path 为空：ValueError
        - 起 task 不返回 taskid：RuntimeError
        - 等待超时：TimeoutError
        - 单条 raw → IndexEntry 失败：日志警告后跳过
        """
        async for entry in self._search_and_yield(
            library_id=library_id,
            client=client,
            search_path=root_path,
            relative_base=root_path,
        ):
            yield entry

    async def scan_subtree(
        self,
        library_id: str,
        client: Any,
        library_root: str,
        subtree_path: str,
    ) -> AsyncIterator[IndexEntry]:
        """扫指定子树 subtree_path，relative_path 始终基于 library_root 计算。

        给业务自身写操作（远程上传 / 远程 rename / 字幕落盘等）调用，
        把刚刚创建/落地的子树立即 upsert 到索引，避免依赖全量重建。

        注意：SYNO.FileStation.Search 不返回子树自身那条记录（它只返回
        子树下的成员）；调用方上层会按需补一条目录条目。
        """
        if not library_root:
            raise ValueError("library_root 为空")
        if not subtree_path:
            raise ValueError("subtree_path 为空")
        norm_root = library_root.rstrip("/") or "/"
        norm_subtree = subtree_path.rstrip("/") or "/"
        # 越界保护：子树必须在 library_root 下，否则 relative_path 会变成奇怪的兜底值
        if norm_subtree != norm_root:
            prefix = norm_root + "/" if norm_root != "/" else "/"
            if not norm_subtree.startswith(prefix):
                raise ValueError(
                    f"subtree 不在 library_root 下: subtree={subtree_path} "
                    f"library_root={library_root}"
                )
        async for entry in self._search_and_yield(
            library_id=library_id,
            client=client,
            search_path=norm_subtree,
            relative_base=norm_root,
        ):
            yield entry

    async def _search_and_yield(
        self,
        *,
        library_id: str,
        client: Any,
        search_path: str,
        relative_base: str,
    ) -> AsyncIterator[IndexEntry]:
        """启动 SYNO 搜索并 yield IndexEntry。

        search_path：起 SYNO.FileStation.Search 的目录（库根 / 子树）
        relative_base：计算 IndexEntry.relative_path 时的库根
        """
        if not search_path:
            raise ValueError("search_path 为空")

        normalized_search = search_path.rstrip("/") or "/"
        normalized_base = relative_base.rstrip("/") or "/"
        started_at = time.time()

        logger.info(
            "[RemoteScanner] 启动远程搜索 library=%s search=%s base=%s",
            library_id, normalized_search, normalized_base,
        )
        started = await client.start_search(
            normalized_search, "*", recursive=True,
        )
        task_id = started.get("taskid") or started.get("task_id")
        if not task_id:
            raise RuntimeError(f"群晖搜索未返回 taskid: {started!r}")

        scanned_count = 0
        try:
            await self._wait_finish(client, task_id)

            offset = 0
            while True:
                data = await client.list_search(
                    task_id,
                    offset=offset,
                    limit=self.page_size,
                    sort_by="name",
                    sort_direction="asc",
                )
                files = data.get("files") or []
                if not files:
                    break

                for raw in files:
                    entry = self._raw_to_entry(library_id, raw, normalized_base)
                    if entry is None:
                        continue
                    scanned_count += 1
                    yield entry

                if len(files) < self.page_size:
                    break
                offset += len(files)
        finally:
            try:
                await client.stop_search(task_id)
            except Exception:
                logger.debug(
                    "[RemoteScanner] stop_search 失败 task_id=%s",
                    task_id, exc_info=True,
                )
            elapsed = time.time() - started_at
            logger.info(
                "[RemoteScanner] 扫描结束 library=%s search=%s entries=%s elapsed=%.2fs",
                library_id, normalized_search, scanned_count, elapsed,
            )
        if scanned_count <= 0:
            logger.warning(
                "[RemoteScanner] 远程搜索返回 0，改用 FileStation.List 递归扫描 "
                "library=%s search=%s base=%s",
                library_id, normalized_search, normalized_base,
            )
            fallback_count = 0
            fallback_started_at = time.time()
            async for entry in self._list_walk_and_yield(
                library_id=library_id,
                client=client,
                start_path=normalized_search,
                relative_base=normalized_base,
            ):
                fallback_count += 1
                yield entry
            logger.info(
                "[RemoteScanner] List 递归扫描结束 library=%s search=%s entries=%s elapsed=%.2fs",
                library_id,
                normalized_search,
                fallback_count,
                time.time() - fallback_started_at,
            )

    async def _list_walk_and_yield(
        self,
        *,
        library_id: str,
        client: Any,
        start_path: str,
        relative_base: str,
    ) -> AsyncIterator[IndexEntry]:
        """用 SYNO.FileStation.List 分页递归扫描。"""
        pending = deque([start_path.rstrip("/") or "/"])
        while pending:
            current_path = pending.popleft()
            offset = 0
            while True:
                if current_path == "/":
                    data = await client.list_share(
                        offset=offset,
                        limit=self.page_size,
                        sort_by="name",
                        sort_direction="asc",
                    )
                    files = data.get("shares") or data.get("files") or []
                    assume_dirs = True
                else:
                    data = await client.list(
                        current_path,
                        offset=offset,
                        limit=self.page_size,
                        sort_by="name",
                        sort_direction="asc",
                    )
                    files = data.get("files") or []
                    assume_dirs = False

                if not files:
                    break

                for raw in files:
                    if not isinstance(raw, dict):
                        continue
                    name = raw.get("name") or self._basename(raw.get("path") or "")
                    if should_skip_name(name):
                        continue
                    path = raw.get("path") or raw.get("real_path") or ""
                    if not path:
                        continue
                    is_dir = bool(raw.get("isdir") if "isdir" in raw else assume_dirs)
                    normalized_raw = raw
                    if (
                        normalized_raw.get("path") != path
                        or normalized_raw.get("name") != name
                        or ("isdir" not in normalized_raw and assume_dirs)
                    ):
                        normalized_raw = {
                            **raw,
                            "path": path,
                            "name": name,
                            "isdir": is_dir,
                        }
                    entry = self._raw_to_entry(library_id, normalized_raw, relative_base)
                    if entry is not None:
                        yield entry
                    if is_dir:
                        pending.append(path.rstrip("/") or "/")

                if len(files) < self.page_size:
                    break
                offset += len(files)

    async def _wait_finish(self, client: Any, task_id: str) -> None:
        """轮询 list_search 直到 finished=True，超时抛 TimeoutError。

        指数退避，与现有 _wait_remote_search_ready 同思路。
        """
        deadline = time.monotonic() + self.wait_timeout_seconds
        delay = self.wait_initial_delay
        polls = 0
        while True:
            await asyncio.sleep(delay)
            polls += 1
            try:
                probe = await client.list_search(
                    task_id, offset=0, limit=1,
                    sort_by="name", sort_direction="asc",
                )
                if probe.get("finished"):
                    logger.debug(
                        "[RemoteScanner] search 完成 task=%s polls=%s",
                        task_id, polls,
                    )
                    return
            except Exception:
                logger.warning(
                    "[RemoteScanner] 轮询失败 task=%s poll=%s",
                    task_id, polls, exc_info=True,
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"群晖搜索超时 task_id={task_id} polls={polls}"
                )

            delay = min(delay * 1.5, self.wait_max_delay)

    def _raw_to_entry(
        self,
        library_id: str,
        raw: dict,
        root_path: str,
    ) -> Optional[IndexEntry]:
        try:
            absolute_path = raw.get("path") or ""
            if not absolute_path:
                return None

            name = raw.get("name") or self._basename(absolute_path)
            if should_skip_name(name):
                return None

            is_dir = bool(raw.get("isdir"))
            additional = raw.get("additional") or {}

            size_raw = additional.get("size")
            size = self._coerce_int(size_raw, default=0) or 0

            time_info = additional.get("time") or {}
            mtime_seconds = self._coerce_int(time_info.get("mtime"), default=None)
            mtime_ms = mtime_seconds * 1000 if mtime_seconds else None

            relative = self._compute_relative(absolute_path, root_path)
            parent = self._compute_parent(relative)
            depth = self._compute_depth(relative)

            return IndexEntry(
                library_id=library_id,
                entry_type='dir' if is_dir else 'file',
                relative_path=relative,
                absolute_path=absolute_path,
                name=name,
                rjcode=extract_rjcode(name),
                parent_path=parent,
                size=size if not is_dir else 0,
                file_count=0,
                mtime=mtime_ms,
                depth=depth,
            )
        except Exception:
            logger.warning(
                "[RemoteScanner] 转换 raw 失败 raw=%r",
                raw, exc_info=True,
            )
            return None

    @staticmethod
    def _basename(path: str) -> str:
        if not path:
            return ""
        return path.rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _compute_relative(absolute_path: str, root_path: str) -> str:
        norm_root = root_path.rstrip("/")
        if absolute_path == norm_root or absolute_path == norm_root + "/":
            return ""
        prefix = norm_root + "/"
        if absolute_path.startswith(prefix):
            return absolute_path[len(prefix):]
        # 不在根下：兜底剥首 /
        return absolute_path.lstrip("/")

    @staticmethod
    def _compute_parent(relative_path: str) -> Optional[str]:
        if not relative_path:
            return None  # 根条目
        if "/" not in relative_path:
            return ""
        return relative_path.rsplit("/", 1)[0]

    @staticmethod
    def _compute_depth(relative_path: str) -> int:
        if not relative_path:
            return 0
        return relative_path.count("/") + 1

    @staticmethod
    def _coerce_int(value: Any, default=None) -> Optional[int]:
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
