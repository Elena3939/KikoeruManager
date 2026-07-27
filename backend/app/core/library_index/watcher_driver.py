"""本地库存 watcher：回调只写 dirty set，后台去抖后生成 reconcile ledger。"""

from __future__ import annotations

import errno
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..redis_service import get_redis_service
from .mutation_service import get_library_index_mutation_service

logger = logging.getLogger(__name__)

QUIET_SECONDS = 0.75
MAX_WAIT_SECONDS = 5.0
MAX_DIRTY_PATHS = 20000
SCRUB_INTERVAL_SECONDS = 300.0
SCRUB_MAX_DIRECTORIES = 200
SCRUB_MAX_SECONDS = 2.0
_INOTIFY_LIMIT_PATHS = {
    "max_user_watches": "/proc/sys/fs/inotify/max_user_watches",
    "max_user_instances": "/proc/sys/fs/inotify/max_user_instances",
}


@dataclass(slots=True)
class _DirtyPath:
    first_at: float
    last_at: float


def _compress_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    for path in sorted(set(paths), key=lambda value: (len(value), value.casefold())):
        normalized = path.rstrip("\\/")
        if any(
            normalized == parent
            or normalized.startswith(parent + os.sep)
            for parent in result
        ):
            continue
        result.append(normalized)
    return result


def _is_inotify_capacity_error(exc: BaseException) -> bool:
    current: Optional[BaseException] = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, OSError) and current.errno in {
            errno.ENOSPC,
            errno.EMFILE,
            errno.ENFILE,
        }:
            return True
        message = str(current).lower()
        if "inotify" in message and ("limit" in message or "too many open files" in message):
            return True
        current = current.__cause__ or current.__context__
    return False


def _read_inotify_limits() -> dict[str, Optional[int]]:
    limits: dict[str, Optional[int]] = {}
    for name, path in _INOTIFY_LIMIT_PATHS.items():
        try:
            with open(path, "r", encoding="ascii") as file:
                limits[name] = int(file.read().strip())
        except (OSError, TypeError, ValueError):
            limits[name] = None
    return limits


class _InventoryEventHandler(FileSystemEventHandler):
    def __init__(self, owner: "LibraryIndexWatcherDriver", library_id: str, root_path: str) -> None:
        super().__init__()
        self.owner = owner
        self.library_id = library_id
        self.root_path = root_path

    def on_any_event(self, event) -> None:
        if getattr(event, "event_type", "") in {"opened", "closed", "closed_no_write"}:
            return
        paths = [getattr(event, "src_path", None), getattr(event, "dest_path", None)]
        for path in paths:
            if path:
                self.owner.mark_dirty(self.library_id, self.root_path, str(path))

    def on_error(self, _event) -> None:
        self.owner.mark_dirty(self.library_id, self.root_path, self.root_path)


class LibraryIndexWatcherDriver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dirty: dict[str, dict[str, _DirtyPath]] = {}
        self._roots: dict[str, str] = {}
        self._observers: list[Observer] = []
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._overflow_count = 0
        self._dispatched_count = 0
        self._scrubbed_directories = 0
        self._scrub_elapsed_ms = 0
        self._scrub_cursor: dict[str, int] = {}
        self._scrub_signatures: dict[tuple[str, str], tuple] = {}
        self._watcher_mode = "stopped"
        self._last_start_error: Optional[str] = None
        self._last_start_errno: Optional[int] = None
        self._inotify_limits = _read_inotify_limits()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        from ..library_manager import get_library_manager

        self._stop_event.clear()
        self._watcher_mode = "watchdog"
        self._last_start_error = None
        self._last_start_errno = None
        self._inotify_limits = _read_inotify_limits()
        self._roots.clear()
        manager = get_library_manager()
        observers: list[Observer] = []
        try:
            for item in manager.list_libraries():
                if str(item.get("type") or "") != "local":
                    continue
                library_id = str(item.get("id") or "")
                root_path = os.path.abspath(str(item.get("root_path") or item.get("path") or ""))
                if not library_id or not os.path.isdir(root_path):
                    continue
                self._roots[library_id] = root_path
                self._restore_redis_dirty(library_id, root_path)
                observer = Observer()
                observer.schedule(
                    _InventoryEventHandler(self, library_id, root_path),
                    root_path,
                    recursive=True,
                )
                observers.append(observer)
                observer.start()
        except Exception as exc:
            self._stop_observers(observers)
            if not _is_inotify_capacity_error(exc):
                self._watcher_mode = "start_failed"
                self._last_start_error = str(exc)
                self._last_start_errno = getattr(exc, "errno", None)
                raise
            self._watcher_mode = "inotify_limit"
            self._last_start_error = str(exc)
            self._last_start_errno = getattr(exc, "errno", None)
            logger.error(
                "[索引 watcher] inotify 容量不足，已关闭实时 observer 并降级为轻量巡检: "
                "errno=%s limits=%s error=%s",
                self._last_start_errno,
                self._inotify_limits,
                self._last_start_error,
            )
            observers = []
        self._observers = observers
        self._thread = threading.Thread(
            target=self._run,
            name="library-index-watcher-dispatch",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[索引 watcher] 已启动 mode=%s local_libraries=%s observed_libraries=%s",
            self._watcher_mode,
            len(self._observers),
            len(self._roots),
        )

    @staticmethod
    def _stop_observers(observers: list[Observer], timeout: float = 5.0) -> None:
        for observer in observers:
            try:
                observer.stop()
            except Exception:
                logger.debug("[索引 watcher] observer.stop 失败", exc_info=True)
        for observer in observers:
            try:
                observer.join(timeout=max(0.1, timeout))
            except Exception:
                logger.debug("[索引 watcher] observer.join 失败", exc_info=True)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._stop_observers(self._observers, timeout=timeout)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.1, timeout))
        self._observers.clear()
        self._watcher_mode = "stopped"

    def _restore_redis_dirty(self, library_id: str, root_path: str) -> None:
        try:
            rows = get_redis_service().read_library_index_dirty_paths_sync(library_id)
        except Exception:
            logger.debug("[索引 watcher] Redis dirty 启动恢复失败", exc_info=True)
            return
        if not rows:
            return
        now = time.monotonic()
        with self._lock:
            bucket = self._dirty.setdefault(library_id, {})
            for relative_path, _score in rows:
                normalized_relative = str(relative_path or "").strip().replace("\\", "/").strip("/")
                if any(part == ".." for part in normalized_relative.split("/")):
                    continue
                absolute_path = (
                    os.path.abspath(os.path.join(root_path, *normalized_relative.split("/")))
                    if normalized_relative
                    else root_path
                )
                try:
                    if os.path.normcase(os.path.commonpath([root_path, absolute_path])) != os.path.normcase(root_path):
                        continue
                except ValueError:
                    continue
                bucket.setdefault(absolute_path, _DirtyPath(first_at=now, last_at=now))
            self._roots[library_id] = root_path

    def mark_dirty(self, library_id: str, root_path: str, absolute_path: str) -> None:
        """watchdog 回调入口：不 stat、不扫盘、不触碰数据库。"""
        relative_path = ""
        try:
            normalized = os.path.abspath(absolute_path)
            if os.path.normcase(os.path.commonpath([root_path, normalized])) != os.path.normcase(root_path):
                return
        except ValueError:
            return
        try:
            relative_path = os.path.relpath(normalized, root_path).replace("\\", "/")
            if relative_path == ".":
                relative_path = ""
            if get_library_index_mutation_service().should_suppress_watcher(
                library_id,
                relative_path,
            ):
                return
        except Exception:
            logger.debug("[索引 watcher] prepared scope 判定失败", exc_info=True)
        now = time.monotonic()
        overflowed = False
        with self._lock:
            bucket = self._dirty.setdefault(library_id, {})
            if normalized not in bucket and len(bucket) >= MAX_DIRTY_PATHS:
                bucket.clear()
                bucket[root_path] = _DirtyPath(first_at=now, last_at=now)
                self._overflow_count += 1
                overflowed = True
            else:
                row = bucket.get(normalized)
                if row is None:
                    bucket[normalized] = _DirtyPath(first_at=now, last_at=now)
                else:
                    row.last_at = now
            self._roots[library_id] = root_path
        try:
            redis = get_redis_service()
            if overflowed:
                redis.upsert_library_index_dirty_paths_sync(
                    library_id,
                    [""],
                    score_ms=time.time() * 1000,
                )
            else:
                redis.upsert_library_index_dirty_paths_sync(
                    library_id,
                    [relative_path],
                    score_ms=time.time() * 1000,
                )
        except Exception:
            logger.debug("[索引 watcher] Redis dirty 热提示失败", exc_info=True)
        self._wake_event.set()

    def _requeue(self, library_id: str, absolute_paths: list[str]) -> None:
        now = time.monotonic()
        root_path = self._roots.get(library_id)
        with self._lock:
            bucket = self._dirty.setdefault(library_id, {})
            for absolute_path in absolute_paths:
                row = bucket.get(absolute_path)
                if row is None:
                    bucket[absolute_path] = _DirtyPath(first_at=now, last_at=now)
                else:
                    row.last_at = now
        if root_path:
            relative_paths = []
            for absolute_path in absolute_paths:
                try:
                    relative_path = os.path.relpath(absolute_path, root_path).replace("\\", "/")
                except ValueError:
                    continue
                relative_paths.append("" if relative_path == "." else relative_path)
            if relative_paths:
                try:
                    get_redis_service().upsert_library_index_dirty_paths_sync(
                        library_id,
                        relative_paths,
                        score_ms=time.time() * 1000,
                    )
                except Exception:
                    logger.debug("[索引 watcher] 重试写入 Redis dirty 失败", exc_info=True)
        self._wake_event.set()

    def _take_due(self) -> dict[str, list[str]]:
        now = time.monotonic()
        due: dict[str, list[str]] = {}
        with self._lock:
            for library_id, bucket in list(self._dirty.items()):
                selected = [
                    path
                    for path, row in bucket.items()
                    if now - row.last_at >= QUIET_SECONDS or now - row.first_at >= MAX_WAIT_SECONDS
                ]
                if not selected:
                    continue
                for path in selected:
                    bucket.pop(path, None)
                if not bucket:
                    self._dirty.pop(library_id, None)
                due[library_id] = _compress_paths(selected)
        return due

    def _dispatch(self, library_id: str, absolute_paths: list[str]) -> None:
        dispatch_cutoff_ms = time.time() * 1000
        root_path = self._roots.get(library_id)
        if not root_path:
            return
        effects = []
        for absolute_path in absolute_paths:
            try:
                relative_path = os.path.relpath(absolute_path, root_path).replace("\\", "/")
            except ValueError:
                continue
            if relative_path == ".":
                relative_path = ""
            effects.append({
                "kind": "reconcile",
                "relative_path": relative_path,
                "scope": "subtree" if os.path.isdir(absolute_path) or not os.path.exists(absolute_path) else "exact",
            })
        if not effects:
            return
        service = get_library_index_mutation_service()
        idempotency_key = f"watcher:{library_id}:{uuid.uuid4()}"
        prepared = service.prepare(
            kind="watcher_reconcile",
            effects_by_library={library_id: effects},
            idempotency_key=idempotency_key,
        )
        try:
            service.mark_filesystem_started(prepared.operation_id)
            service.finalize(
                prepared.operation_id,
                actual_effects_by_library={library_id: effects},
                actual_result={"source": "watcher", "path_count": len(effects)},
            )
        except Exception as exc:
            try:
                service.mark_reconcile_required(prepared.operation_id, exc)
            except Exception:
                logger.debug("[索引 watcher] 标记 reconcile_required 失败", exc_info=True)
            raise
        relative_paths = [str(effect["relative_path"] or "") for effect in effects]
        try:
            if relative_paths:
                get_redis_service().remove_library_index_dirty_paths_sync(
                    library_id,
                    relative_paths,
                    include_descendants=True,
                    max_score_ms=dispatch_cutoff_ms,
                )
        except Exception:
            logger.debug("[索引 watcher] Redis dirty 清理失败", exc_info=True)
        self._dispatched_count += len(effects)

    def _run(self) -> None:
        next_scrub_at = time.monotonic() + SCRUB_INTERVAL_SECONDS
        while not self._stop_event.is_set():
            self._wake_event.wait(0.25)
            self._wake_event.clear()
            for library_id, paths in self._take_due().items():
                try:
                    self._dispatch(library_id, paths)
                except Exception:
                    logger.exception("[索引 watcher] reconcile 入账失败 library=%s", library_id)
                    self._requeue(library_id, paths)
            if time.monotonic() >= next_scrub_at:
                try:
                    self._scrub_once()
                except Exception:
                    logger.exception("[索引 watcher] 低优先级巡检失败")
                next_scrub_at = time.monotonic() + SCRUB_INTERVAL_SECONDS

    @staticmethod
    def _direct_signature(directory: str) -> tuple:
        rows = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                    rows.append((
                        entry.name,
                        bool(entry.is_dir(follow_symlinks=False)),
                        int(stat_result.st_size or 0),
                        int(stat_result.st_mtime_ns or 0),
                    ))
                except OSError:
                    rows.append((entry.name, None, None, None))
        return tuple(sorted(rows, key=lambda item: str(item[0]).casefold()))

    def _scrub_once(self) -> None:
        started = time.monotonic()
        visited = 0
        for library_id, root_path in sorted(self._roots.items()):
            if visited >= SCRUB_MAX_DIRECTORIES or time.monotonic() - started >= SCRUB_MAX_SECONDS:
                break
            directories = [root_path]
            try:
                directories.extend(
                    entry.path
                    for entry in os.scandir(root_path)
                    if entry.is_dir(follow_symlinks=False)
                )
            except OSError:
                self.mark_dirty(library_id, root_path, root_path)
                continue
            cursor = int(self._scrub_cursor.get(library_id, 0) or 0) % max(len(directories), 1)
            for offset in range(len(directories)):
                if visited >= SCRUB_MAX_DIRECTORIES or time.monotonic() - started >= SCRUB_MAX_SECONDS:
                    self._scrub_cursor[library_id] = (cursor + offset) % len(directories)
                    break
                directory = directories[(cursor + offset) % len(directories)]
                visited += 1
                key = (library_id, os.path.normcase(directory))
                try:
                    signature = self._direct_signature(directory)
                except OSError:
                    signature = ()
                previous = self._scrub_signatures.get(key)
                self._scrub_signatures[key] = signature
                if previous is not None and previous != signature:
                    self.mark_dirty(library_id, root_path, directory)
            else:
                self._scrub_cursor[library_id] = 0
        self._scrubbed_directories += visited
        self._scrub_elapsed_ms = int((time.monotonic() - started) * 1000)

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            dirty = {library_id: len(paths) for library_id, paths in self._dirty.items()}
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "watcher_mode": self._watcher_mode,
            "live_events_available": bool(self._observers),
            "scrub_fallback_running": bool(
                self._watcher_mode == "inotify_limit"
                and self._thread
                and self._thread.is_alive()
            ),
            "start_error": self._last_start_error,
            "start_errno": self._last_start_errno,
            "inotify_limits": dict(self._inotify_limits),
            "observed_libraries": sorted(self._roots),
            "dirty_paths": dirty,
            "overflow_count": self._overflow_count,
            "dispatched_count": self._dispatched_count,
            "scrubbed_directories": self._scrubbed_directories,
            "last_scrub_elapsed_ms": self._scrub_elapsed_ms,
        }


_watcher_driver: Optional[LibraryIndexWatcherDriver] = None
_watcher_lock = threading.Lock()


def get_library_index_watcher_driver() -> LibraryIndexWatcherDriver:
    global _watcher_driver
    if _watcher_driver is None:
        with _watcher_lock:
            if _watcher_driver is None:
                _watcher_driver = LibraryIndexWatcherDriver()
    return _watcher_driver


def start_library_index_watcher_driver() -> None:
    get_library_index_watcher_driver().start()


def stop_library_index_watcher_driver() -> None:
    driver = _watcher_driver
    if driver is not None:
        driver.stop()
