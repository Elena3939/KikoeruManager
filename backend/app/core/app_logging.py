"""
应用日志初始化与文件操作工具。

作用：
- 统一三个入口（backend/app/main.py、backend/run.py、desktop_app.py）的日志
  配置，强制启用 RotatingFileHandler，避免 app.log 无限膨胀（历史最大已到
  756MB 级别）。
- 对外提供 list_log_files / cleanup_log_files / truncate_main_log 供 routes
  里的日志管理 API 直接调用，从而可以在前端一键清理。

关键设计：
- 默认 maxBytes = 20MB，backupCount = 5。上限约 120MB，足够排错又不会继续涨。
- 可通过环境变量覆盖：
    - KIKOERUMANAGER_LOG_MAX_MB：单文件大小上限（MB）
    - KIKOERUMANAGER_LOG_BACKUPS：保留备份份数（轮转编号最大值）
    - KIKOERUMANAGER_LOG_QUEUE_SIZE：异步写盘队列上限（默认 10000）
- force_rotate() / truncate_main_log() 都会关闭再打开 RotatingFileHandler，
  避免 Windows 下 rename/truncate 正在写入的日志文件时出现句柄冲突。
- 文件输出由 listener 异步写盘；控制台独立输出，不能反压文件消费线程。
"""
from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

__all__ = [
    "configure_app_logging",
    "get_log_dir",
    "get_main_log_path",
    "list_log_files",
    "LogFileInfo",
    "cleanup_log_files",
    "truncate_main_log",
    "force_rotate_main_log",
    "get_app_logging_status",
    "shutdown_app_logging",
]

logger = logging.getLogger(__name__)

_DEFAULT_MAX_MB = 20
_DEFAULT_BACKUP_COUNT = 5
_MAIN_LOG_NAME = "app.log"

_config_lock = threading.Lock()
_configured_log_path: Optional[str] = None
_rotating_handler: Optional[logging.handlers.RotatingFileHandler] = None
_console_handler: Optional[logging.Handler] = None
_queue_handler: Optional[logging.handlers.QueueHandler] = None
_queue_listener: Optional[logging.handlers.QueueListener] = None
_log_queue: Optional[queue.Queue] = None


class _RecentFirstQueueHandler(logging.handlers.QueueHandler):
    """队列满时淘汰最旧日志，业务线程始终不等待磁盘。"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__(log_queue)
        self.dropped_count = 0
        self._dropped_lock = threading.Lock()

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
            return
        except queue.Full:
            pass

        try:
            self.queue.get_nowait()
            self.queue.task_done()
        except queue.Empty:
            pass
        with self._dropped_lock:
            self.dropped_count += 1
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self._dropped_lock:
                self.dropped_count += 1


class _BoundedQueueListener(logging.handlers.QueueListener):
    def enqueue_sentinel(self) -> None:
        while True:
            try:
                self.queue.put(self._sentinel, timeout=0.2)
                return
            except queue.Full:
                thread = getattr(self, "_thread", None)
                if thread is None or not thread.is_alive():
                    return


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1_000_000) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _resolve_log_dir(log_dir: Optional[str]) -> str:
    """解析日志目录，带上合理 fallback；统一创建目录。"""
    candidate = log_dir or os.environ.get("DATA_PATH") or "./data"
    candidate = os.path.abspath(candidate)
    os.makedirs(candidate, exist_ok=True)
    return candidate


def get_log_dir() -> str:
    """返回当前进程正在使用的日志目录（若未配置则用 DATA_PATH / ./data）。"""
    if _configured_log_path:
        return os.path.dirname(_configured_log_path)
    return _resolve_log_dir(None)


def get_main_log_path() -> str:
    return _configured_log_path or os.path.join(_resolve_log_dir(None), _MAIN_LOG_NAME)


def _stop_queue_listener_locked() -> None:
    global _queue_listener
    listener = _queue_listener
    _queue_listener = None
    if listener is not None:
        listener.stop()


def _start_queue_listener_locked() -> None:
    global _queue_listener
    if _log_queue is None or _rotating_handler is None:
        return
    listener = _BoundedQueueListener(_log_queue, _rotating_handler, respect_handler_level=True)
    listener.start()
    _queue_listener = listener


def shutdown_app_logging() -> None:
    """排空并关闭异步日志 listener，供重复初始化和进程退出使用。"""
    global _rotating_handler, _console_handler, _queue_handler, _log_queue
    with _config_lock:
        _stop_queue_listener_locked()
        for handler in (_rotating_handler, _console_handler, _queue_handler):
            if handler is None:
                continue
            try:
                handler.flush()
            except Exception:
                pass
            try:
                handler.close()
            except Exception:
                pass
        _rotating_handler = None
        _console_handler = None
        _queue_handler = None
        _log_queue = None


def get_app_logging_status() -> dict:
    handler = _queue_handler
    listener = _queue_listener
    log_queue = _log_queue
    listener_thread = getattr(listener, "_thread", None)
    return {
        "async_writer": handler is not None and listener is not None,
        "queue_size": log_queue.qsize() if log_queue is not None else 0,
        "queue_capacity": log_queue.maxsize if log_queue is not None else 0,
        "dropped_count": int(getattr(handler, "dropped_count", 0) or 0),
        "listener_alive": bool(listener_thread and listener_thread.is_alive()),
    }


def configure_app_logging(
    log_dir: Optional[str] = None,
    *,
    use_console: bool = True,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    max_mb: Optional[int] = None,
    backup_count: Optional[int] = None,
) -> str:
    """统一配置根 logger，返回主日志文件的绝对路径。

    - 关闭并清掉已有 handler，避免多次 import 产生重复输出。
    - 文件日志只写有界内存队列，由 listener 线程输出。
    - 文件 handler 用 RotatingFileHandler，默认 20MB × 5。
    - 可选再挂一个控制台 StreamHandler（桌面打包态 stdout 可能为 None，这里
      做好容错）。
    - 同时把 uvicorn / sqlalchemy 的 logger 调到 WARNING，避免刷屏把 app.log
      撑爆。
    """
    global _configured_log_path, _rotating_handler, _console_handler
    global _queue_handler, _queue_listener, _log_queue

    resolved_dir = _resolve_log_dir(log_dir)
    log_path = os.path.join(resolved_dir, _MAIN_LOG_NAME)

    effective_max_mb = max_mb if max_mb is not None else _env_int(
        "KIKOERUMANAGER_LOG_MAX_MB", _DEFAULT_MAX_MB, min_value=1, max_value=512
    )
    effective_backups = backup_count if backup_count is not None else _env_int(
        "KIKOERUMANAGER_LOG_BACKUPS", _DEFAULT_BACKUP_COUNT, min_value=0, max_value=50
    )
    queue_size = _env_int(
        "KIKOERUMANAGER_LOG_QUEUE_SIZE", 10_000, min_value=100, max_value=100_000
    )

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    with _config_lock:
        root = logging.getLogger()
        _stop_queue_listener_locked()
        for output_handler in (_rotating_handler, _console_handler):
            if output_handler is None:
                continue
            try:
                output_handler.flush()
            except Exception:
                pass
            try:
                output_handler.close()
            except Exception:
                pass
        # 先关旧 handler 再替换，防止 Windows 下文件占用
        for handler in list(root.handlers):
            try:
                handler.flush()
            except Exception:
                pass
            try:
                handler.close()
            except Exception:
                pass
            root.removeHandler(handler)

        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=int(effective_max_mb) * 1024 * 1024,
                backupCount=int(effective_backups),
                encoding="utf-8",
                delay=False,
            )
        except OSError:
            log_path = os.path.join(resolved_dir, f"app.{os.getpid()}.log")
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=int(effective_max_mb) * 1024 * 1024,
                backupCount=int(effective_backups),
                encoding="utf-8",
                delay=False,
            )
        file_handler.setFormatter(formatter)

        console_handler = None
        if use_console and getattr(sys, "stdout", None) is not None:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        log_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        queue_handler = _RecentFirstQueueHandler(log_queue)
        root.addHandler(queue_handler)

        root.setLevel(level)
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("LiteLLM").setLevel(logging.WARNING)
        logging.getLogger("litellm").setLevel(logging.WARNING)

        _configured_log_path = log_path
        _rotating_handler = file_handler
        _console_handler = console_handler
        _queue_handler = queue_handler
        _log_queue = log_queue
        _start_queue_listener_locked()

    return log_path


@dataclass
class LogFileInfo:
    path: str
    name: str
    size_bytes: int
    modified_ts: float
    is_main: bool
    is_backup: bool

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "modified_ts": self.modified_ts,
            "is_main": self.is_main,
            "is_backup": self.is_backup,
        }


def list_log_files(log_dir: Optional[str] = None) -> List[LogFileInfo]:
    """列出目录下所有 app.log / app.log.N / desktop_app.log 相关文件。

    返回按 (is_main DESC, name ASC) 排序 —— 主日志置顶，其余按名字升序，
    方便 UI 一眼看出哪个是正在写的。
    """
    resolved_dir = _resolve_log_dir(log_dir)
    results: List[LogFileInfo] = []
    try:
        for entry in os.scandir(resolved_dir):
            if not entry.is_file():
                continue
            name = entry.name
            lowered = name.lower()
            if lowered == "app.log" or lowered.startswith("app.log."):
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                is_main = lowered == "app.log"
                results.append(
                    LogFileInfo(
                        path=os.path.join(resolved_dir, name),
                        name=name,
                        size_bytes=stat.st_size,
                        modified_ts=stat.st_mtime,
                        is_main=is_main,
                        is_backup=not is_main,
                    )
                )
            elif lowered == "desktop_app.log":
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                results.append(
                    LogFileInfo(
                        path=os.path.join(resolved_dir, name),
                        name=name,
                        size_bytes=stat.st_size,
                        modified_ts=stat.st_mtime,
                        is_main=False,
                        is_backup=False,
                    )
                )
    except FileNotFoundError:
        return []

    results.sort(key=lambda item: (0 if item.is_main else 1, item.name))
    return results


def _reopen_rotating_handler(handler: logging.handlers.RotatingFileHandler) -> None:
    """安全地重新打开文件流。"""
    try:
        handler.stream = handler._open()  # type: ignore[attr-defined]
    except Exception:
        logger.exception("[日志管理] 重新打开日志文件失败")


def cleanup_log_files(
    *,
    purge_backups: bool = False,
    truncate_main: bool = False,
    keep_tail_bytes: int = 2 * 1024 * 1024,
) -> dict:
    """一键清理日志文件。

    - ``purge_backups=True``：删除所有 app.log.N 备份文件。
    - ``truncate_main=True``：保留主日志文件末尾 ``keep_tail_bytes`` 字节，其余
      丢弃。适合应急把 756MB 瞬间降到几 MB。
    - 其它日志（desktop_app.log）不会被动。返回一个统计 dict 方便前端展示。
    """
    summary = {
        "purged_files": [],
        "purged_bytes": 0,
        "truncated_main": False,
        "truncated_from_bytes": 0,
        "truncated_to_bytes": 0,
        "errors": [],
    }

    with _config_lock:
        _stop_queue_listener_locked()
        try:
            if purge_backups:
                for info in list_log_files():
                    if not info.is_backup:
                        continue
                    try:
                        os.remove(info.path)
                        summary["purged_files"].append(info.name)
                        summary["purged_bytes"] += int(info.size_bytes or 0)
                    except Exception as exc:
                        summary["errors"].append(f"删除 {info.name} 失败: {exc}")

            if not truncate_main:
                return summary

            main_path = get_main_log_path()
            try:
                summary["truncated_from_bytes"] = (
                    os.path.getsize(main_path) if os.path.exists(main_path) else 0
                )
            except OSError:
                summary["truncated_from_bytes"] = 0

            handler = _rotating_handler
            if handler is not None and handler.stream is not None:
                try:
                    handler.flush()
                except Exception:
                    pass
                try:
                    handler.stream.close()
                except Exception:
                    pass
                handler.stream = None  # type: ignore[assignment]

            try:
                _truncate_file_keep_tail(main_path, max(0, int(keep_tail_bytes)))
                summary["truncated_main"] = True
                try:
                    summary["truncated_to_bytes"] = (
                        os.path.getsize(main_path) if os.path.exists(main_path) else 0
                    )
                except OSError:
                    summary["truncated_to_bytes"] = 0
            except Exception as exc:
                summary["errors"].append(f"截断主日志失败: {exc}")
            finally:
                if handler is not None:
                    _reopen_rotating_handler(handler)
        finally:
            _start_queue_listener_locked()

    return summary


def _truncate_file_keep_tail(path: str, keep_tail_bytes: int) -> None:
    """保留末尾 keep_tail_bytes 字节，其余丢弃。

    - keep_tail_bytes <= 0 时直接清空文件。
    - 原文件比保留大小还小时，直接返回不动它。
    - 为避免峰值内存爆掉，分块 copy 到临时文件后再原子替换。
    """
    if not os.path.exists(path):
        return
    try:
        file_size = os.path.getsize(path)
    except OSError:
        return

    if keep_tail_bytes <= 0:
        # 直接清空
        with open(path, "wb"):
            pass
        return

    if file_size <= keep_tail_bytes:
        return

    start_offset = file_size - keep_tail_bytes
    tmp_path = f"{path}.trunc.{int(time.time())}.tmp"

    chunk_size = 1024 * 1024  # 1MB chunk
    try:
        with open(path, "rb") as src, open(tmp_path, "wb") as dst:
            src.seek(start_offset)
            # 吃掉第一行残片，保证输出以完整行开头
            first = src.readline()
            _ = first  # 丢弃半行
            remaining = True
            while remaining:
                block = src.read(chunk_size)
                if not block:
                    break
                dst.write(block)

        # Windows 下 os.replace 对目标是已存在文件也 OK
        os.replace(tmp_path, path)
    except Exception:
        # 失败时尽量清掉临时文件
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def force_rotate_main_log() -> dict:
    """立即触发一次 rollover，让当前主日志滚到 .1，重新生成空文件。

    对 __从未轮转过__ 的老日志很有用——用户可以先 rotate 一下把老的移走，
    下次 cleanup 就能删掉它。
    """
    summary = {
        "rotated": False,
        "rolled_over_size": 0,
        "errors": [],
    }
    handler = _rotating_handler
    if handler is None:
        summary["errors"].append("日志系统未初始化")
        return summary
    try:
        summary["rolled_over_size"] = (
            os.path.getsize(get_main_log_path()) if os.path.exists(get_main_log_path()) else 0
        )
        with _config_lock:
            _stop_queue_listener_locked()
            try:
                handler.doRollover()
            finally:
                _start_queue_listener_locked()
        summary["rotated"] = True
    except Exception as exc:
        summary["errors"].append(f"触发轮转失败: {exc}")
    return summary


def truncate_main_log(keep_tail_bytes: int = 2 * 1024 * 1024) -> dict:
    """便捷封装：只截断主日志（不动备份），供 routes 调用。"""
    return cleanup_log_files(purge_backups=False, truncate_main=True, keep_tail_bytes=keep_tail_bytes)


atexit.register(shutdown_app_logging)
