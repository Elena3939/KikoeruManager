"""线程内逐目录发现；跨线程投递有界，取消后等待线程实际退出。"""

import asyncio
import concurrent.futures
import contextlib
import itertools
import os
import re
import threading

from .file_processor import FileProcessor
from .input_scan_repository import path_key


class InputScanDiscovery:
    def __init__(self, root, capacity=128, *, repository=None, scan_id=None):
        self.root = root
        self.queue = asyncio.Queue(maxsize=capacity)
        self.stopped = threading.Event()
        self._producer = None
        self.repository = repository
        self.scan_id = scan_id

    @contextlib.contextmanager
    def _io(self, loop):
        from .resource_budget_service import get_resource_budget_service
        entered, started, exited = threading.Event(), threading.Event(), threading.Event()
        released = asyncio.Event()

        async def hold():
            started.set()
            try:
                async with get_resource_budget_service().acquire("disk_io_local", reason="input_discovery"):
                    entered.set()
                    await released.wait()
            finally:
                exited.set()

        future = asyncio.run_coroutine_threadsafe(hold(), loop)
        try:
            while not entered.wait(0.1):
                if future.done():
                    future.result()
                if self.stopped.is_set() and started.is_set():
                    raise _DiscoveryStopped()
            yield
        finally:
            if not entered.is_set():
                future.cancel()
            else:
                loop.call_soon_threadsafe(released.set)
            exited.wait()
            if not future.cancelled():
                future.result()

    @staticmethod
    def _unambiguous_single(name):
        return (
            os.path.splitext(name)[1].lower() in {".7z", ".tar", ".gz", ".bz2", ".xz"}
            and not re.search(r"\.part\d+", name, re.IGNORECASE)
        )

    @staticmethod
    def _group(directory, path, volume=None):
        source = volume.entry_path if volume else path
        identity = os.path.join(directory, volume.base_name + "\0" + volume.type) if volume else source
        return {
            "group_key": path_key(identity), "source_path": source,
            "members": volume.volumes if volume else [path], "needs_stability": bool(volume),
        }

    async def start(self):
        loop = asyncio.get_running_loop()
        self._producer = asyncio.create_task(asyncio.to_thread(self._produce, loop))

    def _send(self, loop, message):
        future = asyncio.run_coroutine_threadsafe(self.queue.put(message), loop)
        while not self.stopped.is_set():
            try:
                future.result(timeout=0.1)
                return True
            except concurrent.futures.TimeoutError:
                continue
        future.cancel()
        return False

    def _produce(self, loop):
        processor = FileProcessor()
        directories = [self.root]
        errors = []
        enumerated = 0
        try:
            while directories and not self.stopped.is_set():
                directory = directories.pop()
                if processor.is_internal_download_path(directory):
                    continue
                names = []
                index = None
                try:
                    if self.repository is not None:
                        from .input_directory_index import InputDirectoryIndex
                        index = InputDirectoryIndex(self.repository, self.scan_id, directory)
                    with os.scandir(directory) as entries:
                        while not self.stopped.is_set():
                            block, rows = [], []
                            with self._io(loop):
                                chunk = list(itertools.islice(entries, 128))
                                for entry in chunk:
                                    if processor.is_internal_download_path(entry.path):
                                        continue
                                    if entry.is_dir(follow_symlinks=False):
                                        directories.append(entry.path)
                                    elif entry.is_file(follow_symlinks=False):
                                        enumerated += 1
                                        single = self._unambiguous_single(entry.name)
                                        rows.append((entry.name, single))
                                        if single:
                                            block.append(self._group(directory, entry.path))
                            for name, single in rows:
                                if index is not None:
                                    index.add(name, processed=single)
                                else:
                                    names.append((name, single))
                            for offset in range(0, len(block), 32):
                                if not self._send(loop, {"groups": block[offset:offset + 32]}):
                                    return
                            if not chunk:
                                break
                    if self.stopped.is_set():
                        return
                    if index is not None:
                        if index.spilled:
                            index.flush()
                        processor._directory_lookup = (directory, index.members)
                        remaining = index.remaining()
                    else:
                        processor._directory_members = (directory, tuple(name for name, _ in names))
                        remaining = iter(names)
                    seen = set() if index is None else None
                    block = []
                    first = True
                    for name, processed in remaining:
                        if self.stopped.is_set():
                            return
                        path = os.path.join(directory, name)
                        if processed or (seen is not None and path in seen) or name.endswith(".aria2"):
                            continue
                        with self._io(loop):
                            if not processor.is_archive(path, include_downloading=True):
                                continue
                            volume = processor.detect_volume_set(path)
                        group = self._group(directory, path, volume)
                        if index is not None:
                            index.mark(os.path.basename(member) for member in group["members"])
                        else:
                            seen.update(group["members"])
                        block.append(group)
                        if first or len(block) == 32:
                            if not self._send(loop, {"groups": block}):
                                return
                            block = []
                            first = False
                    if block and not self._send(loop, {"groups": block}):
                        return
                    if not self._send(loop, {"directory_closed": directory, "groups": []}):
                        return
                except OSError as exc:
                    errors.append({"path": directory, "reason": str(exc)})
                finally:
                    processor._directory_lookup = None
                    processor._directory_members = None
                    if index is not None:
                        index.clear()
            self._send(loop, {"closed": True, "errors": errors, "enumerated_files": enumerated})
        except _DiscoveryStopped:
            return
        finally:
            processor._directory_members = None

    async def receive(self):
        """生产异常也必须唤醒消费者，不能永远挂在空队列上。"""
        pending = asyncio.create_task(self.queue.get())
        try:
            done, _ = await asyncio.wait(
                {pending, self._producer}, return_when=asyncio.FIRST_COMPLETED,
            )
            if pending in done:
                return pending.result()
            await self._producer
            if not self.queue.empty():
                return self.queue.get_nowait()
            raise RuntimeError("目录发现线程未发送结束标记")
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def stop(self):
        self.stopped.set()
        if self._producer is not None:
            await asyncio.shield(self._producer)


class _DiscoveryStopped(Exception):
    pass
