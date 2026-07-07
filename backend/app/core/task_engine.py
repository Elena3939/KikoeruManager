import asyncio
import concurrent.futures
import re
import uuid
import os
import shutil
import tempfile
import threading
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
from pathlib import Path
import logging
from sqlalchemy import or_

from .archive_volume_utils import get_archive_total_size, get_archive_volume_paths, sort_archive_volumes

logger = logging.getLogger(__name__)

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAUSED = "paused"
    WAITING_MANUAL = "waiting_manual"  # 等待手动处理（重复作品）
    WAITING_RETRY = "waiting_retry"  # 等待重试（未找到版本等）
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(str, Enum):
    EXTRACT = "extract"
    FILTER = "filter"
    METADATA = "metadata"
    RENAME = "rename"
    AUTO_PROCESS = "auto_process"
    PROCESS_EXISTING_FOLDER = "process_existing_folder"  # 处理已存在的文件夹（跳过解压）
    ASMR_SYNC_DOWNLOAD = "asmr_sync_download"  # ASMR 同步下载任务
    HTTP_DOWNLOAD = "http_download"  # HTTP 外链下载任务
    BAIDU_NETDISK_DOWNLOAD = "baidu_netdisk_download"  # 百度网盘下载任务
    BAIDU_NETDISK_UPLOAD = "baidu_netdisk_upload"  # 百度网盘上传任务
    RJ_SUBTITLE_FETCH = "rj_subtitle_fetch"  # RJ 字幕抓取任务
    LOCAL_LIBRARY_UPLOAD = "local_library_upload"
    LIBRARY_FOLDER_COMPLETION_PREVIEW = "library_folder_completion_preview"
    CIRCLE_COMPLETION_INDEX = "circle_completion_index"
    CIRCLE_COMPLETION_REFRESH_SELECTED = "circle_completion_refresh_selected"
    CIRCLE_COMPLETION_DOWNLOAD_BATCH = "circle_completion_download_batch"
    CIRCLE_COMPLETION_BONUS_PROBE = "circle_completion_bonus_probe"

class Task:
    """任务对象"""
    _global_event_hook: Optional[Callable] = None
    _EVENT_FIELDS = {"status", "progress", "current_step", "error_message", "started_at", "completed_at"}
    _PROGRESS_REFRESH_PATTERN = re.compile(
        r"(\d+(?:\.\d+)?\s*(?:%|b/s|kb/s|mb/s|gb/s|bps|kb|mb|gb|bytes?|个/秒|项/秒|文件/秒))"
        r"|(\b(?:eta|speed|速度|速率|剩余|已传|已下载|downloaded|uploaded)\b)"
        r"|(\d+\s*/\s*\d+)",
        re.IGNORECASE,
    )

    def __setattr__(self, name, value):
        old_value = getattr(self, name, None) if hasattr(self, name) else None
        object.__setattr__(self, name, value)
        if name not in self._EVENT_FIELDS:
            return
        if not getattr(self, "_events_initialized", False):
            return
        if getattr(self, "_suppress_auto_event", 0):
            return
        if old_value == value:
            return
        reason = "progress" if name in {"progress", "current_step"} else "status"
        if name == "status":
            status_value = value.value if hasattr(value, "value") else str(value or "")
            reason = {
                TaskStatus.COMPLETED.value: "completed",
                TaskStatus.FAILED.value: "failed",
                TaskStatus.CANCELLED.value: "cancelled",
            }.get(status_value, "status")
        self.mark_changed(reason)

    def __init__(
        self,
        task_type: TaskType,
        source_path: str,
        output_path: Optional[str] = None,
        auto_classify: bool = False,
        metadata: Optional[dict] = None,
        skip_archive: bool = False,
        task_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        rjcode: Optional[str] = None
    ):
        self._events_initialized = False
        self._suppress_auto_event = 0
        self.id = task_id if task_id else str(uuid.uuid4())
        self.type = task_type
        self.status = status if status else TaskStatus.PENDING
        self.source_path = source_path
        self.output_path = output_path
        self.auto_classify = auto_classify
        self.skip_archive = skip_archive  # 是否跳过归档（用于重新解压）
        self.progress = 0
        self.current_step = "等待中"
        self.error_message = None
        self.task_metadata = metadata or {}
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self._cancelled = (
            status == TaskStatus.CANCELLED
            or str((self.task_metadata or {}).get("cancel_reason") or "").strip() == "用户取消"
        )
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self.rjcode = rjcode  # 作品的RJ号，用于重复检测
        self.session_id = None
        self.business_key = None
        # 任务运行期间活跃的外部子进程（主要是 7zz x / -so）。
        # cancel / pause 只设 flag 是不够的：7zz 进程不会主动轮询标志，
        # 必须被主动 kill 才能让上层 await 返回，进而走到下一个
        # is_cancelled() / wait_if_paused() 检查点。
        self._active_processes: List = []
        self._proc_lock = threading.Lock()
        self._stop_reason: Optional[str] = None  # 'cancel' | 'pause' | None
        self._event_hook: Optional[Callable] = None
        self._last_progress_event_at = 0.0
        self._last_progress_event_progress: Optional[int] = None
        self._metadata_version = 0
        self._events_initialized = True

    @classmethod
    def set_global_event_hook(cls, hook: Optional[Callable]):
        cls._global_event_hook = hook

    def set_event_hook(self, hook: Optional[Callable]):
        self._event_hook = hook

    def mark_changed(self, reason: str = "status"):
        hook = self._event_hook or self.__class__._global_event_hook
        if not hook:
            return
        try:
            hook(self, reason)
        except Exception:
            logger.debug("任务事件回调失败", exc_info=True)

    def touch_metadata(self, reason: str = "metadata"):
        self._metadata_version = int(getattr(self, "_metadata_version", 0) or 0) + 1
        self.mark_changed(reason)

    def metadata_version(self) -> int:
        return int(getattr(self, "_metadata_version", 0) or 0)

    def _set_state_silent(self):
        task = self

        class _SilentState:
            def __enter__(self):
                task._suppress_auto_event = int(getattr(task, "_suppress_auto_event", 0) or 0) + 1

            def __exit__(self, exc_type, exc, tb):
                task._suppress_auto_event = max(0, int(getattr(task, "_suppress_auto_event", 0) or 0) - 1)

        return _SilentState()

    def start(self):
        """开始任务"""
        with self._set_state_silent():
            self.status = TaskStatus.PROCESSING
            self.started_at = datetime.now()
            self.current_step = "处理中"
        self.mark_changed("started")
    
    def complete(self):
        """完成任务"""
        with self._set_state_silent():
            self.status = TaskStatus.COMPLETED
            self.completed_at = datetime.now()
            self.progress = 100
            self.current_step = "完成"
        self.mark_changed("completed")
    
    def fail(self, error: str):
        """任务失败"""
        with self._set_state_silent():
            self.status = TaskStatus.FAILED
            self.completed_at = datetime.now()
            self.error_message = error
            self.current_step = f"失败: {error}"
        self.mark_changed("failed")
    
    def pause(self):
        """暂停任务。会主动 kill 正在跑的 7z 子进程，让上层从 await 返回，
        之后会在下一个 wait_if_paused 检查点阻塞。恢复后调用方会重试
        被中断的那个阶段（例如同一个密码的完整解压）。"""
        previous_status = self.status.value if isinstance(self.status, TaskStatus) else str(self.status or "")
        if previous_status == TaskStatus.PENDING.value:
            self.task_metadata["pause_origin_status"] = TaskStatus.PENDING.value
        with self._set_state_silent():
            self.status = TaskStatus.PAUSED
            self._pause_event.clear()
            self._kill_active_processes('pause')
        self.mark_changed("status")
    
    def resume(self):
        """恢复任务"""
        with self._set_state_silent():
            self.status = TaskStatus.PROCESSING
            self._pause_event.set()
        self.mark_changed("status")

    def set_waiting_retry(self, reason: str, retry_after: datetime = None):
        """设置等待重试状态"""
        with self._set_state_silent():
            self.status = TaskStatus.WAITING_RETRY
            self.current_step = f"等待重试: {reason}"
        self.task_metadata['retry_reason'] = reason
        self.task_metadata['retry_after'] = retry_after.isoformat() if retry_after else None
        self.task_metadata['retry_count'] = self.task_metadata.get('retry_count', 0) + 1
        logger.info(f"任务 {self.id} 进入等待重试状态: {reason}")
        self.mark_changed("status")

    def can_retry_now(self) -> bool:
        """检查是否可以重试"""
        if self.status != TaskStatus.WAITING_RETRY:
            return False
        retry_after = self.task_metadata.get('retry_after')
        if retry_after:
            from datetime import datetime
            return datetime.fromisoformat(retry_after) <= datetime.now()
        return True

    def cancel(self):
        """取消任务。同时 kill 正在跑的 7z 子进程，以免后台还在跑。"""
        with self._set_state_silent():
            self._cancelled = True
            self.status = TaskStatus.CANCELLED
            self.error_message = None
            self.completed_at = datetime.now()
            self.current_step = "已取消"
        if not isinstance(self.task_metadata, dict):
            self.task_metadata = dict(self.task_metadata or {})
        self.task_metadata["cancel_reason"] = "用户取消"
        # 取消优先级高于暂停：避免子进程被 kill 后又被 pause 逻辑卡住。
        if not self._pause_event.is_set():
            self._pause_event.set()
        self._kill_active_processes('cancel')
        logger.info(f"任务 {self.id} 已被用户取消")
        self.mark_changed("cancelled")
    
    async def wait_if_paused(self):
        """如果暂停则等待"""
        await self._pause_event.wait()

    # ---------------------------------------------------------------
    # 活跃子进程跟踪 / kill
    # ---------------------------------------------------------------

    def register_process(self, proc) -> None:
        """登记当前任务在跑的外部子进程。允许重入，嵌套调用者各自负责配对 unregister。"""
        if proc is None:
            return
        with self._proc_lock:
            self._active_processes.append(proc)
            should_kill_now = self._cancelled or not self._pause_event.is_set()
            current_reason = self._stop_reason
        # 边界情况：子进程启动与 cancel/pause 下发出现竞态，
        # 这里补一刀，避免接下来又跑一个完整解压。
        if should_kill_now and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
            if not current_reason:
                with self._proc_lock:
                    if not self._stop_reason:
                        self._stop_reason = 'cancel' if self._cancelled else 'pause'

    def unregister_process(self, proc) -> None:
        if proc is None:
            return
        with self._proc_lock:
            try:
                self._active_processes.remove(proc)
            except ValueError:
                pass

    def _kill_active_processes(self, reason: str) -> None:
        """主动 kill 任务当前所有外部子进程。reason 供调用方区分取消 / 暂停。"""
        with self._proc_lock:
            self._stop_reason = reason
            procs = list(self._active_processes)
        for p in procs:
            try:
                if p.returncode is None:
                    p.kill()
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.debug(f"任务 {self.id} kill 子进程失败（忽略）: {e}")
        if procs:
            logger.info(f"任务 {self.id} 因 {reason} kill 了 {len(procs)} 个活跃子进程")

    def consume_stop_reason(self) -> Optional[str]:
        """取出并清除上一次 cancel/pause 设下的原因标记，供调用方决策重试/中止。"""
        with self._proc_lock:
            r = self._stop_reason
            self._stop_reason = None
        return r
    
    def is_cancelled(self) -> bool:
        """检查是否被取消"""
        return self._cancelled

    def _progress_source_label(self) -> str:
        metadata = self.task_metadata if isinstance(self.task_metadata, dict) else {}
        source_path = str(self.source_path or "").rstrip("\\/")
        source_name = re.split(r"[\\/]+", source_path)[-1].strip() if source_path else ""
        label = source_name if self.type in {TaskType.EXTRACT, TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER} else ""
        if not label:
            label = str(metadata.get("source_label") or "").strip()
        if not label:
            label = source_name
        label = label.replace("】", "]").strip()
        if len(label) > 96:
            label = f"{label[:42]}...{label[-42:]}"
        return label
    
    def update_progress(self, progress: int, step: str):
        """更新进度，同时追加一条 progress_log 条目供邮件 / 详情面板回放。

        之前只更新 current_step，结果邮件里 recent_logs 只能拿到最后一个
        步骤（"完成"），整个执行链路看不到。这里改为每次 update_progress
        都写入 task_metadata['progress_log']，限长 60 条防止无限增长。
        同一句紧邻重复（常见于多次刷新进度）直接跳过，避免大量"解压中"刷屏。
        """
        normalized_progress = min(100, max(0, int(progress or 0)))
        with self._set_state_silent():
            self.progress = normalized_progress
            self.current_step = step

        try:
            if not isinstance(self.task_metadata, dict):
                self.task_metadata = dict(self.task_metadata or {})
            logs = list(self.task_metadata.get("progress_log") or [])
            text = str(step or "").strip()
            if not text:
                return
            last_text = ""
            last = logs[-1] if logs else None
            if isinstance(last, dict):
                last_text = str(last.get("message") or last.get("text") or "").strip()
                last_progress = last.get("progress")
                if last_text == text and last_progress == self.progress:
                    return
            now_ts = time.monotonic()
            force_emit = self._should_force_progress_emit(text, normalized_progress)
            progress_delta = abs(normalized_progress - int(self._last_progress_event_progress or 0))
            if (
                not force_emit
                and self._last_progress_event_at > 0
                and progress_delta < 1
                and (now_ts - self._last_progress_event_at) < 0.75
                and self._is_high_frequency_progress_refresh(text, last_text)
            ):
                return
            now = datetime.now()
            logs.append({
                "time": now.isoformat(),
                "ts": now.strftime("%H:%M:%S"),
                "progress": self.progress,
                "message": text,
                "level": "info",
            })
            source_label = self._progress_source_label()
            if source_label:
                logger.info("任务 %s【%s】: %s (%d%%)", self.id, source_label, text, normalized_progress)
            else:
                logger.info("任务 %s: %s (%d%%)", self.id, text, normalized_progress)
            # 限长 60 条：解压/入库平均 15~20 条，留足余量给重试场景。
            self.task_metadata["progress_log"] = logs[-60:]
            self._metadata_version = int(getattr(self, "_metadata_version", 0) or 0) + 1
            self._last_progress_event_at = now_ts
            self._last_progress_event_progress = normalized_progress
            self.mark_changed("progress")
        except Exception:
            # 日志写入失败不能影响主流程
            logger.debug("append progress_log 失败", exc_info=True)

    def _should_force_progress_emit(self, step: str, progress: int) -> bool:
        if progress in {0, 100}:
            return True
        text = str(step or "")
        force_tokens = (
            "完成",
            "失败",
            "取消",
            "暂停",
            "等待",
            "重试",
            "冲突",
            "错误",
            "校验失败",
        )
        return any(token in text for token in force_tokens)

    @classmethod
    def _is_high_frequency_progress_refresh(cls, current_step: str, previous_step: str = "") -> bool:
        """识别下载/上传/扫描里的数值型刷新，避免吞掉真实阶段切换。"""
        text = str(current_step or "").strip()
        previous = str(previous_step or "").strip()
        if not text:
            return False
        if not cls._PROGRESS_REFRESH_PATTERN.search(text) and not cls._PROGRESS_REFRESH_PATTERN.search(previous):
            return False

        def normalize(value: str) -> str:
            value = str(value or "").lower()
            value = cls._PROGRESS_REFRESH_PATTERN.sub("#", value)
            value = re.sub(r"\s+", " ", value).strip()
            return value.rstrip("# ").strip()

        return normalize(text) == normalize(previous)

    @staticmethod
    def _is_key_progress_log_item(item: dict) -> bool:
        text = str(item.get("message") or item.get("text") or "").strip()
        level = str(item.get("level") or "").strip().lower()
        if level in {"error", "warning", "warn", "success"}:
            return True
        key_tokens = (
            "完成",
            "失败",
            "取消",
            "暂停",
            "等待",
            "重试",
            "冲突",
            "错误",
            "校验失败",
            "远端校验失败",
        )
        return any(token in text for token in key_tokens)

    @classmethod
    def compact_progress_log_for_persistence(cls, metadata: dict, status: TaskStatus | str) -> dict:
        """压缩落库用 progress_log，运行中 task_metadata 不受影响。"""
        next_metadata = dict(metadata or {})
        logs = [item for item in list(next_metadata.get("progress_log") or []) if isinstance(item, dict)]
        if len(logs) <= 24:
            return next_metadata

        status_value = status.value if isinstance(status, TaskStatus) else str(status or "")
        if status_value in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.WAITING_MANUAL.value, TaskStatus.WAITING_RETRY.value}:
            target_limit = 36
            head_count = 6
            tail_count = 18
        else:
            target_limit = 24
            head_count = 4
            tail_count = 12

        selected: dict[int, dict] = {}
        for index, item in enumerate(logs[:head_count]):
            selected[index] = item
        for index in range(max(0, len(logs) - tail_count), len(logs)):
            selected[index] = logs[index]
        for index, item in enumerate(logs):
            if cls._is_key_progress_log_item(item):
                selected[index] = item

        compacted = [selected[index] for index in sorted(selected)]
        if len(compacted) > target_limit:
            head = compacted[:head_count]
            tail = compacted[-max(1, target_limit - head_count):]
            compacted = head + tail

        next_metadata["progress_log"] = compacted
        next_metadata["progress_log_compacted"] = {
            "original_count": len(logs),
            "retained_count": len(compacted),
            "compacted_at": datetime.now().isoformat(),
        }
        return next_metadata

    def reset_for_rerun(self, step: str = "等待重新执行"):
        """重置任务运行态，保留任务 ID 原地重跑。"""
        with self._set_state_silent():
            self.status = TaskStatus.PENDING
            self.progress = 0
            self.current_step = step
            self.error_message = None
            self.started_at = None
            self.completed_at = None
            self._cancelled = False
            self._pause_event.set()
        with self._proc_lock:
            self._active_processes.clear()
            self._stop_reason = None
        self._metadata_version = int(getattr(self, "_metadata_version", 0) or 0) + 1
        self.mark_changed("status")

    def ensure_business_context(self, domain: str, defaults: Optional[dict] = None):
        """为任务补齐业务上下文，供任务中心统一展示。"""
        defaults = dict(defaults or {})
        metadata = dict(self.task_metadata or {})
        metadata.setdefault("task_domain", domain)
        metadata.setdefault("task_kind", self.type.value)
        metadata.setdefault("session_id", defaults.get("session_id") or self.id)
        metadata.setdefault("source_page", defaults.get("source_page") or "tasks")
        metadata.setdefault("source_action", defaults.get("source_action") or self.type.value)
        metadata.setdefault(
            "source_label",
            defaults.get("source_label") or os.path.basename(str(self.source_path or "").rstrip("\\/")) or self.type.value
        )
        metadata.setdefault("business_key", defaults.get("business_key") or self.id)
        self.session_id = metadata.get("session_id")
        self.business_key = metadata.get("business_key")
        if metadata != (self.task_metadata or {}):
            self.task_metadata = metadata
            self._metadata_version = int(getattr(self, "_metadata_version", 0) or 0) + 1
        else:
            self.task_metadata = metadata

def get_conflict_type_name(conflict_type: str) -> str:
    """获取冲突类型的中文名称"""
    names = {
        'DUPLICATE': '直接重复',
        'LINKED_WORK_ORIGINAL': '原作已存在',
        'LINKED_WORK_TRANSLATION': '翻译版已存在',
        'LINKED_WORK_CHILD': '子版本已存在',
        'LINKED_WORK': '关联作品',
        'LANGUAGE_VARIANT': '语言变体',
        'MULTIPLE_VERSIONS': '多版本'
    }
    return names.get(conflict_type, '冲突')

class TaskEngine:
    """任务引擎 - 管理任务队列和执行"""

    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.tasks: dict[str, Task] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.processing: set[str] = set()
        self._processing_rjcodes: set[str] = set()  # 正在处理的RJ号集合，防止并发重复处理
        self._shutdown = False
        self._worker_task: Optional[asyncio.Task] = None
        self._progress_callbacks: list[Callable] = []
        self._retry_scheduler_task: Optional[asyncio.Task] = None  # 重试调度器任务
        # 方案 B 并行 list 预检的后台协程集合：fire-and-forget 启动，写入
        # ExtractService._archive_info_cache 后自然完成。用 set 强引用避免 GC 警告。
        # task.cancel() 时通过 register_process 联动 kill 子进程，协程会自动退出。
        self._background_precheck_tasks: set[asyncio.Task] = set()
        self._background_precheck_by_task_id: dict[str, asyncio.Task] = {}
        self._task_center_version = 0
        self._task_center_version_lock = threading.Lock()
        self._persisted_task_snapshot_versions: dict[str, tuple] = {}
        self._materialized_task_center_item_versions: dict[str, tuple] = {}
        self._materialized_task_center_item_last_write_at: dict[str, float] = {}
        self._materialized_task_center_item_written_versions: dict[str, int] = {}
        self._materialized_snapshot_lock = threading.Lock()
        self._materialized_snapshot_pending: dict[str, tuple[Dict[str, Any], int, Dict[str, Any], tuple]] = {}
        self._materialized_snapshot_worker_scheduled = False
        self._materialized_snapshot_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="task-center-materialize",
        )
        self._materialized_progress_min_interval_seconds = float(
            os.getenv("KIKOERUMANAGER_TASK_CENTER_PROGRESS_SNAPSHOT_INTERVAL_SECONDS", "5") or 5
        )
        Task.set_global_event_hook(self._emit_task_center_event)
        self.stale_processing_seconds = int(
            os.getenv("KIKOERUMANAGER_TASK_STALE_PROCESSING_SECONDS", "900") or 900
        )

    def _bump_task_center_version(self) -> int:
        with self._task_center_version_lock:
            self._task_center_version += 1
            return self._task_center_version

    def get_task_center_version(self) -> int:
        with self._task_center_version_lock:
            return self._task_center_version

    def _emit_task_center_event(self, task: Task, reason: str = "progress") -> None:
        try:
            from .task_center_event_service import broadcast_task_center_changed

            self._ensure_task_context(task)
            self._bump_task_center_version()
            self._write_task_runtime_to_redis(task, reason=reason)
            self.enqueue_task_center_item_snapshot(task)
            broadcast_task_center_changed(task, reason=reason)
        except Exception:
            logger.debug("任务中心事件广播失败: task_id=%s", getattr(task, "id", ""), exc_info=True)

    def _write_task_runtime_to_redis(self, task: Task, reason: str = "progress") -> None:
        try:
            from .redis_service import get_redis_service

            redis_service = get_redis_service()
            redis_service.write_task_runtime_sync(task, reason=reason)
        except Exception:
            logger.debug("[Redis] 写入任务运行态失败: task_id=%s", getattr(task, "id", ""), exc_info=True)

    def set_max_concurrent(self, max_concurrent: int):
        """动态更新最大并发数"""
        max_concurrent = max(1, int(max_concurrent))
        if self.max_concurrent != max_concurrent:
            logger.info(f"更新任务引擎最大并发数: {self.max_concurrent} -> {max_concurrent}")
            self.max_concurrent = max_concurrent

    @staticmethod
    async def _abort_precheck(precheck_task: Optional[asyncio.Task]) -> None:
        """在步骤 0 早返回前 cancel 后台 list 预检协程，避免重复作品场景浪费 7zz l 子进程。

        - 协程未启动 / 已完成 → no-op
        - 协程在跑 → cancel 触发 _run_7z_command 的 CancelledError 分支，主动 kill 7z 子进程
        - cancel 后等协程退出，确保不留孤儿 7zz 进程
        """
        if precheck_task is None or precheck_task.done():
            return
        precheck_task.cancel()
        try:
            await precheck_task
        except (asyncio.CancelledError, Exception):
            pass

    def _handle_background_precheck_done(
        self,
        precheck_task: asyncio.Task,
        *,
        task_id: str,
        label: str,
        source_path: str,
    ) -> None:
        self._background_precheck_tasks.discard(precheck_task)
        if self._background_precheck_by_task_id.get(task_id) is precheck_task:
            self._background_precheck_by_task_id.pop(task_id, None)
        if precheck_task.cancelled():
            return
        try:
            archive_info = precheck_task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(
                "[%s] 后台 list 预检异常，后续解压/预检会自行重试: source=%s error=%s",
                label,
                os.path.basename(str(source_path or "")),
                exc,
            )
            return

        if archive_info is not None:
            logger.info(
                "[%s] 后台 list 预检完成，已写入压缩包清单缓存: source=%s",
                label,
                os.path.basename(str(source_path or "")),
            )

    def _start_background_archive_precheck(
        self,
        extract_service: Any,
        task: Task,
        *,
        label: Optional[str] = None,
    ) -> Optional[asyncio.Task]:
        source_path = str(getattr(task, "source_path", "") or "")
        if not source_path or not os.path.isfile(source_path):
            return None

        existing_task = self._background_precheck_by_task_id.get(task.id)
        if existing_task is not None and not existing_task.done():
            return existing_task
        if existing_task is not None:
            self._background_precheck_by_task_id.pop(task.id, None)

        resolved_label = (
            label
            or self._get_effective_rjcode(task)
            or self._extract_rjcode_from_path_tail(source_path)
            or "未知"
        )
        precheck_task = asyncio.create_task(extract_service.precheck_archive(task))
        self._background_precheck_tasks.add(precheck_task)
        self._background_precheck_by_task_id[task.id] = precheck_task
        precheck_task.add_done_callback(
            lambda done_task: self._handle_background_precheck_done(
                done_task,
                task_id=task.id,
                label=resolved_label,
                source_path=source_path,
            )
        )
        logger.info(
            "[%s] 已并行启动压缩包清单预读（写缓存，不占解压槽）: source=%s",
            resolved_label,
            os.path.basename(source_path),
        )
        return precheck_task

    def is_rjcode_processing(self, rjcode: str) -> bool:
        """检查RJ号是否正在被处理"""
        return rjcode in self._processing_rjcodes
    
    def mark_rjcode_processing(self, rjcode: str):
        """标记RJ号正在处理"""
        self._processing_rjcodes.add(rjcode)
        logger.info(f"标记RJ号正在处理: {rjcode}")
    
    def unmark_rjcode_processing(self, rjcode: str):
        """取消标记RJ号，同步清理该RJ号因并发等待创建的临时冲突记录"""
        if rjcode in self._processing_rjcodes:
            self._processing_rjcodes.discard(rjcode)
            logger.info(f"取消标记RJ号: {rjcode}")
        # 无论是否在集合中，都尝试清理该RJ号的"正在处理中"临时冲突（兼容重复调用）
        try:
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                deleted = (
                    db.query(ConflictWork)
                    .filter(
                        ConflictWork.rjcode == rjcode,
                        ConflictWork.existing_path == "正在处理中",
                        ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                    )
                    .all()
                )
                if deleted:
                    for c in deleted:
                        db.delete(c)
                    db.commit()
                    logger.info(f"清理 {rjcode} 的临时'正在处理中'冲突记录 {len(deleted)} 条")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"清理'正在处理中'冲突记录时出错: {e}")

    def _release_non_running_slots(self):
        """释放等待人工/已结束任务误占的并发槽。"""
        releasable_statuses = {
            TaskStatus.WAITING_MANUAL,
            TaskStatus.WAITING_RETRY,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.PAUSED,
        }
        for task_id in list(self.processing):
            task = self.tasks.get(task_id)
            if task is None or task.status in releasable_statuses:
                self.processing.discard(task_id)
                if task and task.rjcode:
                    self.unmark_rjcode_processing(task.rjcode)
                logger.info(
                    "释放非运行任务占用的并发槽: task_id=%s status=%s",
                    task_id,
                    getattr(task, "status", "missing"),
                )
    
    def _refresh_conflict_resolution_progress(
        self,
        task: Task,
        *,
        state: str,
        step: str = "",
        error: str = "",
    ) -> None:
        """把问题作品后台处理的轻量状态写回 ConflictWork，供列表持续展示。"""
        metadata = dict(task.task_metadata or {})
        conflict_id = str(metadata.get("conflict_resolution_conflict_id") or "").strip()
        action = str(metadata.get("conflict_resolution_action") or "").strip().upper()
        if not conflict_id or not action:
            return

        try:
            from ..models.database import ConflictWork, get_db

            db = next(get_db())
            try:
                conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
                if not conflict:
                    return
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["resolution_task_id"] = task.id
                next_metadata["resolution_action"] = action
                next_metadata["resolution_task_state"] = state
                next_metadata["resolution_progress"] = int(getattr(task, "progress", 0) or 0)
                next_metadata["resolution_step"] = step or str(getattr(task, "current_step", "") or "")
                next_metadata["resolution_updated_at"] = datetime.now().isoformat()
                if error:
                    next_metadata["resolution_error"] = error
                conflict.new_metadata = next_metadata
                if state in {"queued", "running"}:
                    conflict.status = "PROCESSING"
                db.commit()
            except Exception:
                db.rollback()
                logger.debug(
                    "刷新问题作品处理状态失败: task_id=%s conflict_id=%s",
                    task.id,
                    conflict_id,
                    exc_info=True,
                )
            finally:
                db.close()
        except Exception:
            logger.debug("刷新问题作品处理状态外层失败: task_id=%s", task.id, exc_info=True)

    def add_progress_callback(self, callback: Callable):
        """添加进度回调"""
        self._progress_callbacks.append(callback)
    
    async def _notify_progress(self, task: Task):
        """通知进度更新"""
        if (task.task_metadata or {}).get("conflict_resolution_conflict_id"):
            await asyncio.to_thread(
                self._refresh_conflict_resolution_progress,
                task,
                state="running" if task.status == TaskStatus.PROCESSING else str(task.status.value if isinstance(task.status, TaskStatus) else task.status),
            )
        for callback in self._progress_callbacks:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"进度回调错误: {e}")
    
    async def submit(self, task: Task) -> str:
        """提交任务"""
        self._ensure_task_context(task)
        self.tasks[task.id] = task
        await self.queue.put(task)
        task.mark_changed("submitted")
        rjcode = self._extract_rjcode_from_path_tail(task.source_path) or "未知"
        source_path = str(task.source_path or "").rstrip("\\/")
        source_name = re.split(r"[\\/]+", source_path)[-1].strip() if source_path else ""
        logger.info(f"[{rjcode}] 任务提交 - ID: {task.id}, 源文件: {source_name or source_path}")
        return task.id

    def _task_queue_priority(self, task: Task) -> tuple[int, datetime]:
        metadata = dict(task.task_metadata or {})
        try:
            priority = int(metadata.get("queue_priority") or metadata.get("priority") or 100)
        except Exception:
            priority = 100
        return priority, task.created_at

    def _rebuild_pending_queue(self):
        pending: list[Task] = []
        while True:
            try:
                pending.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        for task in sorted(pending, key=self._task_queue_priority):
            self.queue.put_nowait(task)

    def update_task_priority(self, task_id: str, queue_priority: int) -> bool:
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task.task_metadata is None:
            task.task_metadata = {}
        task.task_metadata["queue_priority"] = max(1, int(queue_priority))
        if task.status == TaskStatus.PENDING:
            self._rebuild_pending_queue()
        return True

    def get_tasks_by_session(self, session_id: str) -> list[Task]:
        target = str(session_id or "").strip()
        if not target:
            return []
        return [task for task in self.tasks.values() if str((task.task_metadata or {}).get("session_id") or "") == target]

    def _infer_task_domain(self, task: Task) -> str:
        if task.type in {TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
            return "import"
        if task.type == TaskType.RJ_SUBTITLE_FETCH:
            return "rj_subtitle"
        if task.type == TaskType.ASMR_SYNC_DOWNLOAD:
            return "asmr_sync"
        if task.type == TaskType.HTTP_DOWNLOAD:
            return "http_download"
        if task.type == TaskType.BAIDU_NETDISK_DOWNLOAD:
            return "baidu_netdisk"
        if task.type == TaskType.LOCAL_LIBRARY_UPLOAD:
            return "upload"
        if task.type == TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW:
            return "asmr_sync"
        if task.type in {
            TaskType.CIRCLE_COMPLETION_INDEX,
            TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED,
            TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH,
            TaskType.CIRCLE_COMPLETION_BONUS_PROBE,
        }:
            return "circle_completion"
        return "system"

    def _ensure_task_context(self, task: Task):
        """给历史任务和新任务补齐统一上下文。"""
        task.set_event_hook(self._emit_task_center_event)
        domain = self._infer_task_domain(task)
        metadata = dict(task.task_metadata or {})
        fallback_label = os.path.basename(str(task.source_path or "").rstrip("\\/")) or task.type.value
        task.ensure_business_context(
            domain,
            defaults={
                "source_page": metadata.get("source_page") or ("library" if domain in {"import", "rj_subtitle"} else "tasks"),
                "source_action": metadata.get("source_action") or task.type.value,
                "source_label": metadata.get("source_label") or fallback_label,
                "business_key": metadata.get("business_key") or metadata.get("rjcode") or task.id,
            }
        )

    def _should_skip_conflict_retry_precheck(self, task: Task) -> bool:
        """问题作品页发起的处理任务不再重复跑解压前预检 / 重复预检。"""
        metadata = dict(task.task_metadata or {})
        action = str(metadata.get("conflict_resolution_action") or "").strip().upper()
        return bool(
            metadata.get("skip_retry_precheck")
            or metadata.get("retry_from_conflicts")
            or metadata.get("retry_conflict_id")
            or metadata.get("conflict_resolution_conflict_id")
            or metadata.get("manual_retry_password_requested")
            or action in {"RETRY", "KEEP_NEW", "MERGE", "RENAME_VOLUMES"}
        )

    def _task_snapshot_version_key(self, task: Task) -> tuple:
        status_value = task.status.value if isinstance(task.status, TaskStatus) else str(task.status or "")
        type_value = task.type.value if isinstance(task.type, TaskType) else str(task.type or "")
        metadata_fp = self._task_metadata_fingerprint(task.task_metadata)
        return (
            type_value,
            status_value,
            str(task.source_path or ""),
            str(task.output_path or ""),
            int(task.progress or 0),
            str(task.current_step or ""),
            str(task.error_message or ""),
            task.created_at.isoformat() if task.created_at else "",
            task.started_at.isoformat() if task.started_at else "",
            task.completed_at.isoformat() if task.completed_at else "",
            int(task.metadata_version()),
            metadata_fp,
        )

    @staticmethod
    def _task_metadata_fingerprint(metadata: Any) -> tuple[int, str]:
        try:
            payload = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        except Exception:
            payload = repr(metadata)
        digest = hashlib.blake2b(payload.encode("utf-8", errors="replace"), digest_size=16).hexdigest()
        return len(payload), digest

    def _should_persist_task_snapshot(self, task: Task, version_key: tuple) -> bool:
        previous = self._persisted_task_snapshot_versions.get(task.id)
        if previous is None:
            return True
        if previous != version_key:
            return True
        status_value = task.status.value if isinstance(task.status, TaskStatus) else str(task.status or "")
        return status_value in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.WAITING_MANUAL.value,
            TaskStatus.WAITING_RETRY.value,
        }

    def _should_upsert_task_center_item_snapshot(self, task: Task, item: Dict[str, Any]) -> bool:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return False
        item_fp = self._task_metadata_fingerprint(item)
        status_value = task.status.value if isinstance(task.status, TaskStatus) else str(task.status or "")
        terminal_or_waiting = status_value in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.WAITING_MANUAL.value,
            TaskStatus.WAITING_RETRY.value,
        }
        if terminal_or_waiting:
            return True
        with self._materialized_snapshot_lock:
            previous = self._materialized_task_center_item_versions.get(item_id)
            if previous == item_fp:
                return False
            last_write_at = float(self._materialized_task_center_item_last_write_at.get(item_id, 0.0) or 0.0)
        return time.monotonic() - last_write_at >= max(0.2, self._materialized_progress_min_interval_seconds)

    def persist_task_snapshot(self, task: Task) -> None:
        """把需要跨重启保留的任务快照写入 tasks 表。"""
        from ..models.database import SessionLocal, Task as TaskRecord

        self._ensure_task_context(task)
        version_key = self._task_snapshot_version_key(task)
        if not self._should_persist_task_snapshot(task, version_key):
            self.persist_task_center_item_snapshot(task)
            return
        db = SessionLocal()
        try:
            record = db.query(TaskRecord).filter(TaskRecord.id == task.id).first()
            if not record:
                record = TaskRecord(id=task.id)
                db.add(record)

            record.type = task.type.value if isinstance(task.type, TaskType) else str(task.type or "")
            record.status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status or "")
            record.source_path = task.source_path
            record.output_path = task.output_path
            record.progress = int(task.progress or 0)
            record.current_step = task.current_step
            record.error_message = task.error_message
            record.created_at = task.created_at
            record.started_at = task.started_at
            record.completed_at = task.completed_at
            record.task_metadata = Task.compact_progress_log_for_persistence(
                dict(task.task_metadata or {}),
                task.status,
            )
            db.commit()
            self._persisted_task_snapshot_versions[task.id] = version_key
        except Exception:
            logger.warning("[任务持久化] 写入任务快照失败: task_id=%s", getattr(task, "id", ""), exc_info=True)
            db.rollback()
        finally:
            db.close()
        self.persist_task_center_item_snapshot(task)

    def persist_task_center_item_snapshot(self, task: Task) -> None:
        """旁路写入任务中心物化快照，供后续 SQL 分页读路径切换前对照。"""
        self._ensure_task_context(task)
        try:
            from .task_center_materialization_service import get_task_center_materialization_service
            from .task_center_service import get_task_center_service

            item = get_task_center_service()._safe_serialize_engine_task(task, mode="summary")
            if not item:
                return
            item_id = str(item.get("id") or "").strip()
            if not self._should_upsert_task_center_item_snapshot(task, item):
                return
            service = get_task_center_materialization_service()
            version = self.get_task_center_version()
            service.upsert_engine_item(
                item,
                version=version,
                metadata=dict(task.task_metadata or {}),
            )
            with self._materialized_snapshot_lock:
                self._materialized_task_center_item_versions[item_id] = self._task_metadata_fingerprint(item)
                self._materialized_task_center_item_last_write_at[item_id] = time.monotonic()
                self._materialized_task_center_item_written_versions[item_id] = version
        except Exception:
            logger.warning("[任务中心物化] 生成任务快照失败: task_id=%s", getattr(task, "id", ""), exc_info=True)

    def enqueue_task_center_item_snapshot(self, task: Task) -> None:
        """把任务中心物化快照放进后台合并队列，避免进度事件同步等数据库写锁。"""
        self._ensure_task_context(task)
        try:
            from .task_center_service import get_task_center_service

            item = get_task_center_service()._safe_serialize_engine_task(task, mode="summary")
            if not item:
                return
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                return
            item_fp = self._task_metadata_fingerprint(item)
            if not self._should_upsert_task_center_item_snapshot(task, item):
                return
            version = self.get_task_center_version()
            metadata = dict(task.task_metadata or {})
            with self._materialized_snapshot_lock:
                self._materialized_snapshot_pending[item_id] = (item, version, metadata, item_fp)
                if self._materialized_snapshot_worker_scheduled:
                    return
                self._materialized_snapshot_worker_scheduled = True
            self._materialized_snapshot_executor.submit(self._drain_task_center_item_snapshots)
        except Exception:
            logger.debug("[任务中心物化] 快照入队失败: task_id=%s", getattr(task, "id", ""), exc_info=True)

    def _drain_task_center_item_snapshots(self) -> None:
        """专用后台线程串行写任务中心快照；同一个 item 只保留最新 payload。"""
        try:
            from .task_center_materialization_service import get_task_center_materialization_service

            service = get_task_center_materialization_service()
            while True:
                with self._materialized_snapshot_lock:
                    pending = self._materialized_snapshot_pending
                    self._materialized_snapshot_pending = {}
                    if not pending:
                        self._materialized_snapshot_worker_scheduled = False
                        return

                for item_id, (item, version, metadata, item_fp) in pending.items():
                    with self._materialized_snapshot_lock:
                        written_version = int(self._materialized_task_center_item_written_versions.get(item_id, -1))
                    if version < written_version:
                        continue
                    try:
                        service.upsert_engine_item(item, version=version, metadata=metadata)
                    except Exception:
                        logger.warning("[任务中心物化] 后台写入快照失败: item_id=%s", item_id, exc_info=True)
                        continue
                    with self._materialized_snapshot_lock:
                        current_written = int(self._materialized_task_center_item_written_versions.get(item_id, -1))
                        if version >= current_written:
                            self._materialized_task_center_item_versions[item_id] = item_fp
                            self._materialized_task_center_item_last_write_at[item_id] = time.monotonic()
                            self._materialized_task_center_item_written_versions[item_id] = version
        except Exception:
            logger.warning("[任务中心物化] 后台写入线程异常", exc_info=True)
            with self._materialized_snapshot_lock:
                self._materialized_snapshot_worker_scheduled = False

    def delete_task_snapshot(self, task_id: str) -> None:
        """删除任务快照，避免用户清理后重启又恢复。"""
        from ..models.database import SessionLocal, Task as TaskRecord

        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return
        db = SessionLocal()
        try:
            db.query(TaskRecord).filter(TaskRecord.id == normalized_task_id).delete()
            db.commit()
            self._persisted_task_snapshot_versions.pop(normalized_task_id, None)
            materialized_item_id = f"engine:{normalized_task_id}"
            with self._materialized_snapshot_lock:
                self._materialized_task_center_item_versions.pop(materialized_item_id, None)
                self._materialized_task_center_item_last_write_at.pop(materialized_item_id, None)
                self._materialized_task_center_item_written_versions.pop(materialized_item_id, None)
                self._materialized_snapshot_pending.pop(materialized_item_id, None)
        except Exception:
            logger.warning("[任务持久化] 删除任务快照失败: task_id=%s", normalized_task_id, exc_info=True)
            db.rollback()
        finally:
            db.close()
        try:
            from .task_center_materialization_service import get_task_center_materialization_service

            get_task_center_materialization_service().delete_engine_item(normalized_task_id)
        except Exception:
            logger.warning("[任务中心物化] 删除任务中心快照失败: task_id=%s", normalized_task_id, exc_info=True)

    def _coerce_task_type(self, value: str) -> Optional[TaskType]:
        normalized = str(value or "").strip()
        for item in TaskType:
            if normalized in {item.value, item.name}:
                return item
        return None

    def _coerce_task_status(self, value: str) -> TaskStatus:
        normalized = str(value or "").strip()
        for item in TaskStatus:
            if normalized in {item.value, item.name}:
                return item
        return TaskStatus.COMPLETED

    def load_persisted_linked_subtitle_tasks(self) -> int:
        """恢复字幕补配工作台任务，只有用户清理后才从工作台消失。"""
        from ..models.database import SessionLocal, Task as TaskRecord

        db = SessionLocal()
        loaded_count = 0
        try:
            rows = db.query(TaskRecord).filter(TaskRecord.type == TaskType.RJ_SUBTITLE_FETCH.value).all()
            for row in rows:
                if row.id in self.tasks:
                    continue
                metadata = dict(row.task_metadata or {})
                source_mode = str(metadata.get("source_mode") or "").strip().lower()
                if source_mode not in {"linked_translation_archive_import", "subtitle_folder_import"}:
                    continue
                is_waiting_manual = bool(metadata.get("awaiting_manual_match"))
                is_manual_completed = bool(metadata.get("manual_match_completed"))
                if not (is_waiting_manual or is_manual_completed):
                    continue

                task_type = self._coerce_task_type(row.type)
                if task_type is None:
                    continue
                task = Task(
                    task_type=task_type,
                    source_path=row.source_path or metadata.get("folder_path") or "",
                    output_path=row.output_path,
                    auto_classify=bool(metadata.get("auto_classify", False)),
                    metadata=metadata,
                    task_id=row.id,
                    status=self._coerce_task_status(row.status),
                    rjcode=metadata.get("rjcode") or metadata.get("target_rjcode") or "",
                )
                with task._set_state_silent():
                    task.progress = int(row.progress or 0)
                    task.current_step = row.current_step or "等待筛选与配对"
                    task.error_message = row.error_message
                    task.created_at = row.created_at or task.created_at
                    task.started_at = row.started_at
                    task.completed_at = row.completed_at
                self._ensure_task_context(task)
                self.tasks[task.id] = task
                loaded_count += 1
            if loaded_count:
                logger.info("[任务持久化] 已恢复字幕补配人工配对任务 %s 个", loaded_count)
            return loaded_count
        except Exception:
            logger.warning("[任务持久化] 恢复字幕补配任务失败", exc_info=True)
            return 0
        finally:
            db.close()

    def recover_stale_processing_tasks(self) -> int:
        """把上次进程中断留下的 processing 快照恢复为等待重试。

        这些任务没有活跃内存协程，继续保留 processing 只会让任务中心永久卡住。
        """
        from ..models.database import SessionLocal, Task as TaskRecord, TaskCenterItem

        threshold_seconds = max(60, int(getattr(self, "stale_processing_seconds", 900) or 900))
        stale_before = datetime.now() - timedelta(seconds=threshold_seconds)
        recovered_ids: set[str] = set()
        db = SessionLocal()
        try:
            task_rows = (
                db.query(TaskRecord)
                .filter(
                    TaskRecord.status == TaskStatus.PROCESSING.value,
                    or_(TaskRecord.started_at == None, TaskRecord.started_at <= stale_before),  # noqa: E711
                )
                .all()
            )
            for row in task_rows:
                metadata = dict(row.task_metadata or {})
                metadata["stale_processing_recovered"] = True
                metadata["stale_processing_recovered_at"] = datetime.now().isoformat()
                metadata["retry_reason"] = "上次处理进程中断或预检超时，已恢复为等待重试"
                row.status = TaskStatus.WAITING_RETRY.value
                row.current_step = "等待重试: 上次处理进程中断或预检超时"
                row.error_message = ""
                row.completed_at = None
                row.task_metadata = metadata
                recovered_ids.add(str(row.id))

            item_rows = (
                db.query(TaskCenterItem)
                .filter(
                    TaskCenterItem.status == TaskStatus.PROCESSING.value,
                    or_(TaskCenterItem.updated_at == None, TaskCenterItem.updated_at <= stale_before),  # noqa: E711
                )
                .all()
            )
            for item in item_rows:
                payload = dict(item.payload_json or {})
                engine_task_id = str(item.engine_task_id or payload.get("engine_task_id") or payload.get("entity_id") or "").strip()
                payload["status"] = TaskStatus.WAITING_RETRY.value
                payload["status_label"] = "等待重试"
                payload["current_step"] = "等待重试: 上次处理进程中断或预检超时"
                payload["error_message"] = ""
                details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
                metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
                metadata = dict(metadata)
                metadata["stale_processing_recovered"] = True
                metadata["stale_processing_recovered_at"] = datetime.now().isoformat()
                details["metadata"] = metadata
                payload["details"] = details
                item.status = TaskStatus.WAITING_RETRY.value
                item.payload_json = payload
                item.updated_at = datetime.now()
                if engine_task_id:
                    recovered_ids.add(engine_task_id)

            if recovered_ids:
                db.commit()
                logger.warning(
                    "[启动清理] 已将 %s 个残留 processing 任务恢复为等待重试: %s",
                    len(recovered_ids),
                    sorted(recovered_ids)[:8],
                )
            else:
                db.rollback()
            return len(recovered_ids)
        except Exception:
            db.rollback()
            logger.warning("[启动清理] 恢复残留 processing 任务失败", exc_info=True)
            return 0
        finally:
            db.close()

    def _get_effective_rjcode(self, task: Task, fallback_path: Optional[str] = None) -> str:
        """统一获取当前任务可用的 RJ 号，优先复用已推断结果。"""
        candidates = [
            getattr(task, "rjcode", None),
            (task.task_metadata or {}).get("rjcode"),
            (task.task_metadata or {}).get("inferred_rjcode"),
            self._extract_rjcode_from_path_tail(fallback_path or task.source_path),
        ]
        for candidate in candidates:
            value = self._extract_rjcode(str(candidate or "")) or str(candidate or "").strip().upper()
            if value and value != "未知":
                return value
        return ""

    def _extract_rjcode_from_path_tail(self, path: str) -> Optional[str]:
        path = str(path or "").strip()
        if not path:
            return None
        tail = os.path.basename(path.rstrip("\\/"))
        if tail:
            tail_rjcode = self._extract_rjcode(tail, search_subfolders=False)
            if tail_rjcode:
                return tail_rjcode
        return self._extract_rjcode(path, search_subfolders=False)

    def _sync_task_rjcode(self, task: Task, rjcode: Optional[str], source: Optional[str] = None) -> str:
        """把有效 RJ 号同步回任务对象和元数据，供后续重命名、归档和分类统一使用。"""
        normalized = self._extract_rjcode(str(rjcode or "")) or str(rjcode or "").strip().upper()
        if not normalized or normalized == "未知":
            return ""

        if task.task_metadata is None:
            task.task_metadata = {}

        task.rjcode = normalized
        task.task_metadata["rjcode"] = normalized
        task.task_metadata.setdefault("inferred_rjcode", normalized)
        if source:
            task.task_metadata["rjcode_source"] = source
        return normalized

    def _resolve_task_log_type_label(self, task: Task) -> str:
        """给日志输出业务语义标签，避免直接入库显示成下载任务。"""
        source_action = str((task.task_metadata or {}).get("source_action") or "").strip()
        if task.type == TaskType.ASMR_SYNC_DOWNLOAD and source_action in {"reimport_local_download_root", "reimport_downloaded_session"}:
            return "direct_reimport"
        return task.type.value

    def _record_problem_work_for_extract_failure(self, task: Task, rjcode: Optional[str], reason: str):
        """将解压阶段失败的任务记录到问题作品列表，避免前端无项可见"""
        from .classifier import SmartClassifier

        source_path = str(task.source_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return

        # 来自问题作品页的重试任务：原 conflict 在 routes.retry_extract_failed_conflict
        # 中已被改为 PROCESSING，_add_to_conflict_works 的去重查询只看 PENDING，
        # 这里再写一条会造成同源重复（A 仍 PROCESSING/重试中，B 新增 PENDING）。
        # 失败时由 _finalize_conflict_resolution_task 把原 conflict 恢复为 PENDING
        # 并写 resolution_error，这里直接短路即可。
        if self._is_retry_from_conflicts_task(task):
            return

        normalized_rjcode = (rjcode or "").strip()
        if normalized_rjcode == "未知":
            normalized_rjcode = self._extract_rjcode_from_path_tail(source_path) or ""

        metadata = dict(task.task_metadata or {})
        metadata["failure_stage"] = "extract"
        metadata["error_message"] = reason
        metadata["available_actions"] = ["RETRY", "SKIP"]
        metadata = self._sanitize_failure_metadata(metadata, reason)

        classifier = SmartClassifier()
        classifier._add_to_conflict_works(
            task.id,
            normalized_rjcode or None,
            "EXTRACT_FAILED",
            "",
            source_path,
            metadata,
            status="PENDING",
        )

    def _is_retry_from_conflicts_task(self, task: Task) -> bool:
        """判断该任务是否由问题作品页的重试入口生成；这类任务失败时不应再写新 conflict。"""
        metadata = dict(task.task_metadata or {})
        if metadata.get("retry_from_conflicts"):
            return True
        if str(metadata.get("retry_conflict_id") or "").strip():
            return True
        if str(metadata.get("conflict_resolution_conflict_id") or "").strip():
            return True
        action = str(metadata.get("conflict_resolution_action") or "").strip().upper()
        if action == "RETRY":
            return True
        return False

    def _infer_failure_stage(self, task: Task, reason: str) -> str:
        metadata = dict(task.task_metadata or {})
        explicit_stage = str(metadata.get("failure_stage") or "").strip().lower()
        if explicit_stage:
            return explicit_stage

        current_step = str(task.current_step or "").strip()
        combined_text = f"{current_step} {reason}".lower()
        stage_map = [
            ("extract", ["解压", "密码", "压缩包"]),
            ("metadata", ["元数据", "metadata"]),
            ("rename", ["重命名", "rename"]),
            ("filter", ["过滤", "filter"]),
            ("classify", ["分类", "库存", "移动到库存"]),
            ("archive", ["归档", "archive"]),
        ]
        for stage, keywords in stage_map:
            if any(keyword.lower() in combined_text for keyword in keywords):
                return stage
        return "process"

    def _is_password_failure_metadata(self, metadata: dict, reason: str = "") -> bool:
        extract_reason = str(metadata.get("extract_failure_reason") or "").strip()
        if extract_reason in {"wrong_password", "missing_password"}:
            return True
        combined_text = f"{reason} {metadata.get('error_message') or ''} {metadata.get('resolution_error') or ''}".lower()
        return any(
            marker in combined_text
            for marker in (
                "无正确密码",
                "密码错误",
                "密码不正确",
                "wrong password",
                "incorrect password",
                "password required",
                "missing password",
            )
        )

    def _sanitize_failure_metadata(self, metadata: dict, reason: str = "") -> dict:
        next_metadata = dict(metadata or {})
        if self._is_password_failure_metadata(next_metadata, reason):
            next_metadata["extract_failure_reason"] = "wrong_password"
        if str(next_metadata.get("extract_failure_reason") or "").strip() == "garbled_filename":
            return next_metadata
        for key in list(next_metadata.keys()):
            if key.startswith("garbled_filename_"):
                next_metadata.pop(key, None)
        next_metadata.pop("manual_retry_filename_encoding", None)
        next_metadata.pop("manual_retry_ignore_garbled", None)
        return next_metadata

    def _record_problem_work_for_task_failure(self, task: Task, rjcode: Optional[str], reason: str):
        """把导入流程中的失败统一写入问题作品，避免任务中心失败但问题作品页为空。"""
        from .classifier import SmartClassifier

        source_path = str(task.source_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return

        # 来自问题作品页的重试任务：原 conflict 已被 routes 改为 PROCESSING；
        # _add_to_conflict_works 的 PENDING 去重在此场景下查不到原条目，会重复插入。
        # _finalize_conflict_resolution_task 在 finally 里会把原 conflict 状态恢复，
        # 这里直接跳过，避免重复条目 + "原作品仍重试中、新作品冒出来"的视觉错乱。
        if self._is_retry_from_conflicts_task(task):
            return

        normalized_rjcode = (rjcode or "").strip()
        if normalized_rjcode == "未知":
            normalized_rjcode = ""
        if not normalized_rjcode:
            normalized_rjcode = self._extract_rjcode_from_path_tail(source_path) or ""

        failure_stage = self._infer_failure_stage(task, reason)
        conflict_type = "EXTRACT_FAILED" if failure_stage == "extract" else "PROCESS_FAILED"
        metadata = dict(task.task_metadata or {})
        available_actions = ["RETRY", "SKIP"]
        # extract_service._maybe_raise_disguised_volume_set 命中"伪装多卷"时
        # 会往 task_metadata["disguised_volume_set"] 写 detection payload。
        # 这里把 conflict_type 切到 分卷压缩包后缀无法识别，让前端弹"手动重命名分卷"
        # 而不是普通 RETRY；保留 SKIP 兜底。
        disguised = metadata.get("disguised_volume_set")
        if isinstance(disguised, dict) and disguised.get("suspect_files"):
            conflict_type = "分卷压缩包后缀无法识别"
            available_actions = ["RENAME_VOLUMES", "SKIP"]
        metadata.update({
            "failure_stage": failure_stage,
            "error_message": reason,
            "available_actions": available_actions,
            "source_task_type": task.type.value,
            "failed_task_id": task.id,
            "failed_step": str(task.current_step or "").strip(),
            "failed_progress": int(task.progress or 0),
        })
        metadata = self._sanitize_failure_metadata(metadata, reason)

        classifier = SmartClassifier()
        classifier._add_to_conflict_works(
            task.id,
            normalized_rjcode or None,
            conflict_type,
            "",
            source_path,
            metadata,
            status="PENDING",
        )

    def _resolve_retry_extract_conflict(self, task: Task):
        """当问题作品中的失败项重试成功后，将原记录和旧失败任务标记为已恢复。"""
        if task.status != TaskStatus.COMPLETED:
            return

        metadata = dict(task.task_metadata or {})
        conflict_id = str(metadata.get("retry_conflict_id") or "").strip()
        source_path = str(metadata.get("retry_conflict_source_path") or task.source_path or "").strip()
        failed_task_id = str(metadata.get("retry_failed_task_id") or "").strip()
        if not conflict_id and not source_path:
            if not failed_task_id:
                return

        from ..models.database import ConflictWork, get_db

        db = next(get_db())
        try:
            query = db.query(ConflictWork).filter(
                ConflictWork.conflict_type.in_(["EXTRACT_FAILED", "PROCESS_FAILED"]),
                ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            )
            conflict = None
            if conflict_id:
                conflict = query.filter(ConflictWork.id == conflict_id).first()
            if not conflict and source_path:
                conflict = query.filter(ConflictWork.new_path == source_path).first()

            if conflict:
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["retry_result"] = "completed"
                next_metadata["retry_completed_at"] = datetime.now().isoformat()
                next_metadata["retry_task_id"] = task.id
                if task.output_path:
                    next_metadata["retry_output_path"] = task.output_path
                conflict.new_metadata = next_metadata

            if failed_task_id:
                failed_task = self.get_task(failed_task_id)
                if failed_task and failed_task.id != task.id and failed_task.status == TaskStatus.FAILED:
                    if task.output_path and not failed_task.output_path:
                        failed_task.output_path = task.output_path
                    self._mark_task_superseded(failed_task, task.id, task.output_path)

            if conflict:
                try:
                    from .activity_log_service import log_conflict_resolution_activity
                    log_conflict_resolution_activity(
                        conflict_id=str(conflict.id),
                        action="RETRY",
                        status="success",
                        rjcode=conflict.rjcode or getattr(task, "rjcode", None),
                        task_id=task.id,
                        source_path=str(source_path or conflict.new_path or getattr(task, "source_path", "") or ""),
                        final_path=str(task.output_path or ""),
                        error_message="乱码强制入库" if bool(metadata.get("garbled_filename_bypassed")) else None,
                        extra_detail=self._build_retry_conflict_activity_extra(task),
                    )
                except Exception:
                    logger.warning("写入问题作品重试成功操作记录失败: task_id=%s conflict_id=%s", task.id, conflict.id, exc_info=True)
                db.delete(conflict)
            db.commit()
            if conflict:
                logger.info("失败问题项重试成功，已移出问题作品: conflict_id=%s task_id=%s", conflict.id, task.id)
        except Exception as exc:
            db.rollback()
            logger.error("更新解压失败问题项状态失败: %s", exc, exc_info=True)
        finally:
            db.close()

    def _should_block_linked_translation_without_subtitles(self, preview: Dict[str, Any]) -> bool:
        if not preview:
            return False
        if not bool(preview.get("is_translation_work")):
            return False
        if not bool(preview.get("kikoeru_has_work") or preview.get("kikoeru_target_found")):
            return False
        if bool(preview.get("kikoeru_target_is_empty_shell")):
            return False
        if bool(
            preview.get("can_stage_pending")
            or preview.get("should_queue_pending")
            or preview.get("can_execute")
        ):
            return False
        if int(preview.get("subtitle_count") or 0) > 0 or bool(preview.get("source_has_subtitles")):
            return False
        probe_status = str(preview.get("source_subtitle_probe_status") or "").strip().lower()
        if probe_status == "timeout":
            return False
        return True

    def _should_block_uncertain_dlsite_linkage(self, preview: Dict[str, Any]) -> bool:
        if not preview:
            return False
        if not bool(preview.get("dlsite_linkage_uncertain")):
            return False
        if bool(
            preview.get("can_stage_pending")
            or preview.get("should_queue_pending")
            or preview.get("can_execute")
        ):
            return False
        return True

    def _record_linked_translation_without_subtitles_problem(
        self,
        task: Task,
        preview: Dict[str, Any],
        reason: str,
    ) -> None:
        from .classifier import SmartClassifier

        source_rjcode = self._extract_rjcode(str(preview.get("source_rjcode") or "")) or self._extract_rjcode_from_path_tail(task.source_path)
        target_rjcode = self._extract_rjcode(str(preview.get("target_rjcode") or ""))
        source_label = str(preview.get("source_label") or os.path.basename(task.source_path or "") or source_rjcode or "").strip()
        target_title = str(preview.get("kikoeru_title") or target_rjcode or "").strip()
        metadata = {
            "work_name": source_label,
            "source_label": source_label,
            "source_rjcode": source_rjcode,
            "target_rjcode": target_rjcode,
            "reason": reason,
            "failure_stage": "linked_subtitle_precheck",
            "error_message": reason,
            "subtitle_count": int(preview.get("subtitle_count") or 0),
            "kikoeru_has_work": bool(preview.get("kikoeru_has_work") or preview.get("kikoeru_target_found")),
            "kikoeru_needs_subtitle": bool(preview.get("kikoeru_needs_subtitle")),
            "available_actions": ["SKIP"],
        }
        linked_works_info = []
        if target_rjcode:
            linked_works_info.append({
                "rjcode": target_rjcode,
                "work_type": "original",
                "lang": "JPN",
                "path": target_title,
                "work_name": target_title,
                "source": "kikoeru",
            })

        SmartClassifier()._add_to_conflict_works(
            task.id,
            source_rjcode or target_rjcode or None,
            "LINKED_WORK",
            target_title,
            task.source_path,
            metadata,
            status="PENDING",
            linked_works_info=linked_works_info,
            analysis_info={
                "preview": preview,
                "problem_kind": "linked_translation_without_subtitles",
            },
            related_rjcodes=[code for code in [source_rjcode, target_rjcode] if code],
        )

    def _build_retry_conflict_activity_extra(self, task: Task) -> dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        keys = (
            "manual_retry_password_requested",
            "manual_retry_filename_encoding",
            "manual_retry_ignore_garbled",
            "garbled_filename_bypassed",
            "garbled_filename_bypass_origin",
            "garbled_filename_sample",
            "garbled_filename_score_before",
            "garbled_filename_score_after",
            "garbled_filename_repaired_count",
            "garbled_filename_guard_origin",
            # surrogate 修复统计：让操作记录里能看到本次有几个非 UTF-8 文件名被自动反解
            # （repaired = 强信号，已变为合法 UTF-8）/ 几个仅字面转义（escaped = 仍需人工编码确认）。
            "garbled_filename_surrogate_repaired_count",
            "garbled_filename_surrogate_escaped_count",
        )
        return {key: metadata.get(key) for key in keys if key in metadata}

    def _finalize_conflict_resolution_task(self, task: Task):
        """处理由问题作品页提交的后台冲突解决任务收尾。"""
        metadata = dict(task.task_metadata or {})
        conflict_id = str(metadata.get("conflict_resolution_conflict_id") or "").strip()
        action = str(metadata.get("conflict_resolution_action") or "").strip().upper()
        if not conflict_id or not action:
            return

        from ..models.database import ConflictWork, ProcessedArchive, get_db

        db = next(get_db())
        try:
            conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
            if not conflict:
                return

            next_metadata = dict(conflict.new_metadata or {})
            next_metadata["resolution_task_id"] = task.id
            next_metadata["resolution_action"] = action
            next_metadata["resolution_updated_at"] = datetime.now().isoformat()

            if action == "RETRY":
                if task.status == TaskStatus.COMPLETED:
                    next_metadata["retry_result"] = "completed"
                    next_metadata["retry_completed_at"] = datetime.now().isoformat()
                    next_metadata["retry_task_id"] = task.id
                    if task.output_path:
                        next_metadata["retry_output_path"] = task.output_path
                    conflict.new_metadata = next_metadata
                    db.delete(conflict)
                    db.commit()
                    logger.info(
                        "重试冲突任务完成后兜底清理问题项: conflict_id=%s task_id=%s",
                        conflict_id,
                        task.id,
                    )
                    return
                if task.status == TaskStatus.FAILED:
                    conflict.status = "PENDING"
                    next_metadata["resolution_error"] = str(task.error_message or "重试失败")
                    task_extract_reason = str((task.task_metadata or {}).get("extract_failure_reason") or "").strip()
                    if task_extract_reason:
                        next_metadata["extract_failure_reason"] = task_extract_reason
                    next_metadata = self._sanitize_failure_metadata(next_metadata, str(task.error_message or ""))
                    conflict.new_metadata = next_metadata
                    db.commit()
                    try:
                        from .activity_log_service import log_conflict_resolution_activity
                        log_conflict_resolution_activity(
                            conflict_id=str(conflict.id),
                            action="RETRY",
                            status="failed",
                            rjcode=conflict.rjcode or getattr(task, "rjcode", None),
                            task_id=task.id,
                            source_path=str(conflict.new_path or getattr(task, "source_path", "") or ""),
                            error_message=str(task.error_message or "重试失败"),
                            extra_detail=self._build_retry_conflict_activity_extra(task),
                        )
                    except Exception:
                        logger.warning("写入问题作品重试失败操作记录失败: task_id=%s conflict_id=%s", task.id, conflict_id, exc_info=True)
                return

            if task.status == TaskStatus.COMPLETED:
                conflict.status = action
                next_metadata["resolution_task_state"] = "completed"
                next_metadata["resolution_progress"] = 100
                next_metadata["resolution_step"] = "完成"
                next_metadata["resolution_completed_at"] = datetime.now().isoformat()
                next_metadata.pop("resolution_error", None)
                if task.output_path:
                    next_metadata["resolution_output_path"] = task.output_path
                archive_record = None
                if conflict.new_path:
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == os.path.basename(str(conflict.new_path))
                    ).first()
                    if archive_record:
                        archive_record.status = "completed"
                        archive_record.processed_at = datetime.now()
                if action == "KEEP_NEW":
                    try:
                        from .activity_log_service import (
                            log_conflict_resolution_activity,
                            snapshot_file_tree_for_activity,
                        )
                        before_items = list(next_metadata.get("resolution_before_tree_items") or [])
                        snapshot_skipped = bool(next_metadata.get("resolution_activity_snapshot_skipped"))
                        extra_detail = {"snapshot_skipped": True} if snapshot_skipped else None
                        if not snapshot_skipped:
                            existing_path = str(next_metadata.get("existing_path") or conflict.existing_path or "")
                            if not before_items and next_metadata.get("resolution_before_tree_deferred") and existing_path:
                                before_items = snapshot_file_tree_for_activity(existing_path, limit=300)
                            after_items = snapshot_file_tree_for_activity(task.output_path, limit=300) if task.output_path else []
                        else:
                            after_items = []
                        log_conflict_resolution_activity(
                            conflict_id=conflict.id,
                            action=action,
                            status="success",
                            rjcode=conflict.rjcode or getattr(task, "rjcode", None),
                            task_id=task.id,
                            source_path=str(getattr(task, "source_path", "") or ""),
                            target_path=str(next_metadata.get("existing_path") or conflict.existing_path or ""),
                            final_path=str(task.output_path or ""),
                            before_tree_items=before_items,
                            after_tree_items=after_items,
                            extra_detail=extra_detail,
                        )
                    except Exception:
                        logger.warning("写入保留新版操作记录失败: task_id=%s conflict_id=%s", task.id, conflict_id, exc_info=True)
            elif task.status == TaskStatus.FAILED:
                conflict.status = "PENDING"
                next_metadata["resolution_task_state"] = "failed"
                next_metadata["resolution_progress"] = int(getattr(task, "progress", 0) or 0)
                next_metadata["resolution_step"] = str(getattr(task, "current_step", "") or "")
                next_metadata["resolution_error"] = str(task.error_message or "冲突处理失败")
                task_extract_reason = str((task.task_metadata or {}).get("extract_failure_reason") or "").strip()
                if task_extract_reason:
                    next_metadata["extract_failure_reason"] = task_extract_reason
                next_metadata = self._sanitize_failure_metadata(next_metadata, str(task.error_message or ""))
            else:
                return

            conflict.new_metadata = next_metadata
            db.commit()
            if task.status == TaskStatus.COMPLETED and archive_record:
                try:
                    from .task_center_event_service import broadcast_processed_archive_changed
                    broadcast_processed_archive_changed(archive_record)
                except Exception:
                    logger.debug("广播归档更新事件失败", exc_info=True)
        except Exception:
            logger.warning("冲突解决任务收尾失败: task_id=%s conflict_id=%s", task.id, conflict_id, exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _is_hidden_task(self, task: Task) -> bool:
        metadata = dict(task.task_metadata or {})
        return bool(metadata.get("hidden_in_task_lists"))

    def _mark_task_superseded(self, task: Task, superseded_by_task_id: str, output_path: str = ""):
        metadata = dict(task.task_metadata or {})
        if str(metadata.get("superseded_by_task_id") or "").strip() == superseded_by_task_id and self._is_hidden_task(task):
            return

        metadata["superseded_by_task_id"] = superseded_by_task_id
        metadata["superseded_at"] = datetime.now().isoformat()
        metadata["superseded_reason"] = "later_completed"
        metadata["hidden_in_task_lists"] = True
        if output_path:
            metadata["superseded_output_path"] = output_path
        task.task_metadata = metadata

        if task.status != TaskStatus.COMPLETED:
            task.status = TaskStatus.COMPLETED
            task.completed_at = task.completed_at or datetime.now()
        task.error_message = None
        task.current_step = f"已由后续成功任务覆盖: {superseded_by_task_id}"
        task.mark_changed("completed")

    async def revive_superseded_local_upload_tasks(self, task_ids: Optional[list[str]] = None) -> list[str]:
        """修复旧逻辑误标记的本地上传任务，并重新入队。"""
        target_ids = {str(item or "").strip() for item in (task_ids or []) if str(item or "").strip()}
        revived: list[str] = []

        for task in list(self.tasks.values()):
            if task.type != TaskType.LOCAL_LIBRARY_UPLOAD:
                continue
            if target_ids and task.id not in target_ids:
                continue

            metadata = dict(task.task_metadata or {})
            current_step = str(task.current_step or "").strip()
            was_superseded = bool(
                str(metadata.get("superseded_by_task_id") or "").strip()
                or current_step.startswith("已由后续成功任务覆盖")
            )
            if not was_superseded:
                continue

            upload_result = metadata.get("upload_result") if isinstance(metadata.get("upload_result"), dict) else {}
            if task.status == TaskStatus.COMPLETED and int((upload_result or {}).get("count") or 0) > 0:
                continue
            if task.id in self.processing or task.status == TaskStatus.PROCESSING:
                continue

            for key in ("superseded_by_task_id", "superseded_at", "superseded_reason", "superseded_output_path"):
                metadata.pop(key, None)
            metadata.pop("hidden_in_task_lists", None)

            upload_files = []
            for row in list(metadata.get("upload_files") or []):
                if not isinstance(row, dict):
                    continue
                next_row = dict(row)
                next_row["status"] = "pending"
                next_row["progress"] = 0
                next_row["uploaded_bytes"] = 0
                upload_files.append(next_row)
            total_files = len(upload_files)
            total_bytes = sum(int(row.get("size") or row.get("size_bytes") or 0) for row in upload_files)
            metadata["upload_files"] = upload_files
            metadata["uploaded_files"] = []
            metadata["upload_runtime"] = {
                "phase": "preparing",
                "total_files": total_files,
                "completed_files": 0,
                "transferred_bytes": 0,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0,
                "current_file_name": "",
                "current_relative_path": "",
                "current_source_dir": "",
            }

            logs = list(metadata.get("progress_log") or [])
            logs.append({
                "time": datetime.now().isoformat(),
                "message": "检测到上传任务曾被错误合并，已恢复并重新排队",
                "progress": 0,
                "level": "warning",
            })
            metadata["progress_log"] = logs[-40:]
            task.task_metadata = metadata
            task.reset_for_rerun("等待重新上传")
            self._ensure_task_context(task)

            queued_ids = {getattr(queued_task, "id", "") for queued_task in list(getattr(self.queue, "_queue", []))}
            if task.id not in queued_ids:
                await self.queue.put(task)
            revived.append(task.id)

        if revived:
            logger.warning("已恢复被错误合并的本地上传任务: %s", ",".join(revived))
        return revived

    def cleanup_retry_output_artifacts(self, failed_task_id: str, source_path: str = "") -> list[str]:
        """在失败任务重试前，主动清掉上次失败留下的产物目录，避免被新的重复检测命中。"""
        target_task = self.get_task(str(failed_task_id or "").strip())
        if not target_task:
            return []

        candidate_paths = []
        output_path = str(getattr(target_task, "output_path", "") or "").strip()
        source_path = str(source_path or "").strip()
        if output_path:
            candidate_paths.append(output_path)
        superseded_output = str((target_task.task_metadata or {}).get("superseded_output_path") or "").strip()
        if superseded_output:
            candidate_paths.append(superseded_output)

        from ..config.settings import get_config
        config = get_config()
        allowed_roots = [
            os.path.abspath(str(config.storage.temp_path or "").strip()),
            os.path.abspath(str(config.storage.library_path or "").strip()),
            os.path.abspath(str(config.storage.existing_folders_path or "").strip()),
        ]

        cleaned_paths: list[str] = []
        normalized_source = os.path.abspath(source_path) if source_path and os.path.exists(source_path) else ""

        for raw_path in candidate_paths:
            try:
                abs_path = os.path.abspath(raw_path)
            except Exception:
                continue
            if not abs_path or not os.path.exists(abs_path):
                continue
            if normalized_source and abs_path == normalized_source:
                continue
            if not any(abs_path == root or abs_path.startswith(root + os.sep) for root in allowed_roots if root):
                logger.warning("跳过清理重试产物，路径不在允许范围内: %s", abs_path)
                continue
            try:
                if os.path.isdir(abs_path):
                    shutil.rmtree(abs_path)
                else:
                    os.remove(abs_path)
                cleaned_paths.append(abs_path)
                logger.info("重试前已清理失败产物: failed_task_id=%s path=%s", failed_task_id, abs_path)
            except Exception as exc:
                logger.warning("清理失败产物失败: failed_task_id=%s path=%s error=%s", failed_task_id, abs_path, exc, exc_info=True)

        return cleaned_paths

    def _task_matches_recovered_success(self, candidate: Task, source_path: str, rjcode: str, recovered_task_id: str) -> bool:
        if not candidate or candidate.id == recovered_task_id:
            return False
        if candidate.type not in {TaskType.EXTRACT, TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
            return False
        if candidate.status == TaskStatus.COMPLETED:
            return False

        candidate_rjcode = self._extract_rjcode(
            getattr(candidate, "rjcode", "")
            or (candidate.task_metadata or {}).get("actual_rjcode")
            or (candidate.task_metadata or {}).get("target_rjcode")
            or (candidate.task_metadata or {}).get("rjcode")
            or (candidate.task_metadata or {}).get("inferred_rjcode")
        )
        if rjcode and candidate_rjcode and candidate_rjcode == rjcode:
            return True

        candidate_source_path = str(candidate.source_path or "").strip()
        if source_path and candidate_source_path and os.path.abspath(candidate_source_path) == os.path.abspath(source_path):
            return True

        return False

    def _resolve_completed_failure_followups(self, task: Task):
        """普通任务后续成功时，自动移除同源/同 RJ 的失败问题项，并标记旧失败已恢复。"""
        if task.status != TaskStatus.COMPLETED:
            return
        if task.type not in {TaskType.EXTRACT, TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
            return

        metadata = dict(task.task_metadata or {})
        source_path = str(task.source_path or "").strip()
        rjcode = self._extract_rjcode(
            getattr(task, "rjcode", "")
            or metadata.get("actual_rjcode")
            or metadata.get("target_rjcode")
            or metadata.get("rjcode")
            or metadata.get("inferred_rjcode")
        )

        recovered_conflict_ids: list[str] = []
        recovered_failed_task_ids: list[str] = []

        from ..models.database import ConflictWork, get_db

        db = next(get_db())
        try:
            query = db.query(ConflictWork).filter(
                ConflictWork.conflict_type.in_(["EXTRACT_FAILED", "PROCESS_FAILED"]),
                ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            )

            if source_path and rjcode:
                conflicts = query.filter(
                    (ConflictWork.new_path == source_path) | (ConflictWork.rjcode == rjcode)
                ).all()
            elif source_path:
                conflicts = query.filter(ConflictWork.new_path == source_path).all()
            elif rjcode:
                conflicts = query.filter(ConflictWork.rjcode == rjcode).all()
            else:
                conflicts = []

            for conflict in conflicts:
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["retry_result"] = "completed"
                next_metadata["retry_completed_at"] = datetime.now().isoformat()
                next_metadata["retry_task_id"] = task.id
                next_metadata["retry_auto_resolved"] = True
                if task.output_path:
                    next_metadata["retry_output_path"] = task.output_path
                conflict.new_metadata = next_metadata
                recovered_conflict_ids.append(str(conflict.id))

                failed_task_id = str(conflict.task_id or "").strip()
                if failed_task_id:
                    failed_task = self.get_task(failed_task_id)
                    if failed_task and self._task_matches_recovered_success(failed_task, source_path, rjcode, task.id):
                        self._mark_task_superseded(failed_task, task.id, task.output_path)
                        recovered_failed_task_ids.append(failed_task.id)
                db.delete(conflict)

            for candidate in self.tasks.values():
                if not self._task_matches_recovered_success(candidate, source_path, rjcode, task.id):
                    continue
                candidate_metadata = dict(candidate.task_metadata or {})
                if str(candidate_metadata.get("superseded_by_task_id") or "").strip() == task.id and self._is_hidden_task(candidate):
                    continue
                self._mark_task_superseded(candidate, task.id, task.output_path)
                recovered_failed_task_ids.append(candidate.id)

            recovered_failed_task_ids = list(dict.fromkeys(recovered_failed_task_ids))
            recovered_conflict_ids = list(dict.fromkeys(recovered_conflict_ids))

            if recovered_failed_task_ids or recovered_conflict_ids:
                metadata["recovered_failure_count"] = len(recovered_failed_task_ids)
                metadata["recovered_failure_ids"] = recovered_failed_task_ids
                metadata["recovered_conflict_count"] = len(recovered_conflict_ids)
                metadata["recovered_conflict_ids"] = recovered_conflict_ids
                notice_parts = []
                if recovered_failed_task_ids:
                    notice_parts.append(f"此前 {len(recovered_failed_task_ids)} 条失败已由本次成功覆盖")
                if recovered_conflict_ids:
                    notice_parts.append(f"问题作品已自动移除 {len(recovered_conflict_ids)} 项")
                metadata["recovered_notice"] = "，".join(notice_parts)
                task.task_metadata = metadata

            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("自动收敛已恢复失败任务失败: %s", exc, exc_info=True)
        finally:
            db.close()

    async def _cleanup_task_temp_extract_path(self, task: Task):
        metadata = dict(task.task_metadata or {})
        temp_path = str(metadata.get("temp_extract_path") or "").strip()
        if not temp_path:
            return

        try:
            from ..config.settings import get_config
            config = get_config()
            temp_root = os.path.abspath(str(config.storage.temp_path or ""))
            target = os.path.abspath(temp_path)
        except Exception:
            logger.warning("[清理] 解析临时解压目录失败: task_id=%s path=%s", task.id, temp_path, exc_info=True)
            return

        if not os.path.exists(target):
            return
        if not temp_root or os.path.commonpath([temp_root, target]) != temp_root:
            logger.warning("[清理] 跳过非配置临时目录: task_id=%s path=%s", task.id, target)
            return

        output_path = str(getattr(task, "output_path", "") or "").strip()
        if output_path:
            try:
                output_abs = os.path.abspath(output_path)
                if os.path.commonpath([target, output_abs]) == target:
                    logger.warning(
                        "[清理] 最终产物仍位于临时目录内，跳过删除避免误删: task_id=%s temp=%s output=%s",
                        task.id,
                        target,
                        output_abs,
                    )
                    return
            except Exception:
                logger.warning("[清理] 判断最终产物路径失败，跳过临时目录清理: task_id=%s", task.id, exc_info=True)
                return

        try:
            await asyncio.to_thread(shutil.rmtree, target)
            logger.info("[清理] 已删除任务临时解压目录: task_id=%s path=%s", task.id, target)
            metadata["temp_extract_path_cleaned"] = True
            metadata["temp_extract_path_cleaned_at"] = datetime.now().isoformat()
            task.task_metadata = metadata
        except FileNotFoundError:
            return
        except Exception:
            logger.warning("[清理] 删除任务临时解压目录失败: task_id=%s path=%s", task.id, target, exc_info=True)

    async def _stabilize_extract_subtask_conflict_source(self, task: Task, source_path: str, classifier) -> str:
        metadata = dict(task.task_metadata or {})
        if not metadata.get("is_extract_subtask"):
            return source_path

        candidate = str(source_path or "").strip()
        if not candidate or not os.path.exists(candidate):
            return candidate

        try:
            from ..config.settings import get_config
            config = get_config()
            conflict_base_path = os.path.join(str(config.storage.library_path), "_conflicts")
            os.makedirs(conflict_base_path, exist_ok=True)
            final_path = await asyncio.to_thread(classifier._move_with_rename, candidate, conflict_base_path)
        except Exception:
            logger.warning(
                "[多作品拆分] 稳定化问题作品来源失败: task_id=%s source=%s",
                task.id,
                candidate,
                exc_info=True,
            )
            return candidate

        if final_path and final_path != candidate:
            metadata["extract_subtask_conflict_source_original"] = candidate
            metadata["extract_subtask_conflict_source_stable_path"] = final_path
            task.task_metadata = metadata
            task.source_path = final_path
            task.output_path = final_path
            logger.info(
                "[多作品拆分] 问题作品来源已搬到稳定目录: task_id=%s %s -> %s",
                task.id,
                candidate,
                final_path,
            )
        return final_path or candidate

    def _rewrite_active_conflict_new_path(self, task_id: str, old_path: str, new_path: str) -> int:
        old_value = str(old_path or "").strip()
        new_value = str(new_path or "").strip()
        if not task_id or not old_value or not new_value or old_value == new_value:
            return 0

        from ..models.database import ConflictWork, get_db

        db = next(get_db())
        updated = 0
        try:
            rows = (
                db.query(ConflictWork)
                .filter(
                    ConflictWork.task_id == task_id,
                    ConflictWork.new_path == old_value,
                    ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                )
                .all()
            )
            for row in rows:
                row.new_path = new_value
                metadata = dict(row.new_metadata or {})
                metadata["new_path_recovered_from"] = old_value
                metadata["new_path_recovered_at"] = datetime.now().isoformat()
                row.new_metadata = metadata
                updated += 1
            if updated:
                db.commit()
                logger.info(
                    "问题作品 new_path 已随多作品子任务稳定化修正: task_id=%s count=%s old=%s new=%s",
                    task_id,
                    updated,
                    old_value,
                    new_value,
                )
        except Exception:
            db.rollback()
            logger.warning("修正多作品子任务问题作品路径失败: task_id=%s", task_id, exc_info=True)
            return 0
        finally:
            db.close()
        return updated

    def _rj_subtitle_remote_retry_delay_seconds(self, value: Any) -> Optional[float]:
        message = str(value or "")
        if "远程库存暂时退化" not in message and "已熔断" not in message:
            return None
        matched = re.search(r"熔断\s*(\d+(?:\.\d+)?)\s*秒", message)
        if matched:
            try:
                return max(30.0, min(float(matched.group(1)), 180.0))
            except Exception:
                pass
        return 60.0

    def _rj_subtitle_remote_retry_after(self, result_or_error: Any) -> Optional[datetime]:
        candidates: List[Any] = [result_or_error]
        if isinstance(result_or_error, dict):
            candidates.append(result_or_error.get("error"))
            candidates.extend(result_or_error.get("write_errors") or [])
            for item in result_or_error.get("failed_files") or []:
                if isinstance(item, dict):
                    candidates.append(item.get("error") or item.get("reason") or item.get("message"))
                else:
                    candidates.append(item)
        delays = [self._rj_subtitle_remote_retry_delay_seconds(item) for item in candidates]
        delays = [delay for delay in delays if delay is not None]
        if not delays:
            return None
        return datetime.now() + timedelta(seconds=max(delays))

    def _rj_subtitle_remote_retry_reason(self, result_or_error: Any) -> str:
        candidates: List[Any] = []
        if isinstance(result_or_error, dict):
            candidates.extend(result_or_error.get("write_errors") or [])
            for item in result_or_error.get("failed_files") or []:
                if isinstance(item, dict):
                    candidates.append(item.get("error") or item.get("reason") or item.get("message"))
                else:
                    candidates.append(item)
        candidates.append(result_or_error)
        for item in candidates:
            message = str(item or "").strip()
            if self._rj_subtitle_remote_retry_delay_seconds(message) is not None:
                return message
        return "远程库存暂时退化，等待恢复后重试字幕回写"

    async def _process_task(self, task: Task):
        """处理单个任务"""
        from .extract_service import ExtractService
        from .filter_service import FilterService
        from .metadata_service import MetadataService
        from .rename_service import RenameService
        from .classifier import SmartClassifier
        
        inferred_rjcode = self._extract_rjcode(str((task.task_metadata or {}).get('inferred_rjcode') or '')) or str((task.task_metadata or {}).get('inferred_rjcode') or '').strip().upper()
        task_metadata_rjcode = self._get_effective_rjcode(task)
        rjcode = task_metadata_rjcode or self._extract_rjcode_from_path_tail(task.source_path) or inferred_rjcode or "未知"
        self._sync_task_rjcode(
            task,
            rjcode if rjcode != "未知" else None,
            source=(task.task_metadata or {}).get("rjcode_source") or ("task_metadata" if task_metadata_rjcode else "source_path"),
        )
        logger.info(f"[{rjcode}] ========== 开始处理任务 ==========")
        logger.info(f"[{rjcode}] 任务ID: {task.id}, 类型: {self._resolve_task_log_type_label(task)}")
        logger.info(f"[{rjcode}] 源路径: {task.source_path}")
        
        try:
            task.start()
            await self._notify_progress(task)
            
            if task.type == TaskType.AUTO_PROCESS:
                from ..config.settings import get_config
                config = get_config()

                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()
                skip_retry_precheck = self._should_skip_conflict_retry_precheck(task)

                # 方案 B 并行 list 预检：fire-and-forget 启动后台协程，
                # 协程跑完 7zz l 后写入 ExtractService._archive_info_cache，
                # 步骤 1 解压时内部 _get_archive_info 命中缓存秒回，消除重复 list。
                # 预检只占清单/探测槽，不能阻塞正式解压槽。
                precheck_task: Optional[asyncio.Task] = None

                # 步骤0: 预检（先字幕补配，再普通查重）
                if skip_retry_precheck:
                    logger.info(f"[{rjcode}] 问题作品处理任务，跳过已完成的解压前预检")
                    task.update_progress(8, "准备处理")
                else:
                    try:  # 步骤 0 try/except：确保步骤 0 意外异常时 cancel precheck
                        logger.info(f"[{rjcode}] 步骤0: 预检")
                        task.update_progress(5, "预检中")
                        rjcode = self._extract_rjcode_from_path_tail(task.source_path)

                        # 密码库权威绑定：若条目同时填写 filename + rjcode 命中了当前压缩包，
                        # 整条链路（查重/命名/包裹目录）都使用条目里的 rjcode。
                        if os.path.isfile(task.source_path):
                            try:
                                bound_rjcode = await extract_service.lookup_filename_bound_rjcode(task.source_path)
                            except Exception as exc:
                                bound_rjcode = None
                                logger.warning(f"[{rjcode or '未知'}] 查询密码库绑定 RJ 失败: {exc}")
                            if bound_rjcode and bound_rjcode != rjcode:
                                logger.info(
                                    f"[{bound_rjcode}] 密码库 filename+RJ 权威绑定，"
                                    f"覆盖源路径 RJ {rjcode or '未知'} -> {bound_rjcode}"
                                )
                                rjcode = self._sync_task_rjcode(
                                    task,
                                    bound_rjcode,
                                    source="password_entry_filename_match",
                                )
                                if task.task_metadata is None:
                                    task.task_metadata = {}
                                task.task_metadata["rjcode_lock"] = True

                        if not rjcode and os.path.isfile(task.source_path):
                            try:
                                archive_rj_result = await extract_service.infer_rjcode_from_archive(
                                    task.source_path,
                                    max_nested_depth=3,
                                )
                            except Exception as exc:
                                archive_rj_result = None
                                logger.warning(f"[未知] 压缩包预检推断 RJ 失败: {os.path.basename(task.source_path)} error={exc}")

                            if archive_rj_result and archive_rj_result.get("rjcode"):
                                rjcode = self._sync_task_rjcode(
                                    task,
                                    archive_rj_result.get("rjcode"),
                                    source=archive_rj_result.get("source") or "archive_precheck",
                                )
                                logger.info(
                                    f"[{rjcode}] 预检阶段从压缩包内容推断到 RJ 号: "
                                    f"source={archive_rj_result.get('source') or 'archive_precheck'}"
                                )
                            else:
                                logger.info(
                                    f"[未知] 压缩包预检未推断出 RJ 号: "
                                    f"source={os.path.basename(task.source_path)}"
                                )
                        logger.info(f"[{rjcode}] 提取到的RJ号: {rjcode}")

                        precheck_task = None
                        linked_result = {"handled": False, "reason": "not_run", "preview": {}}
                        if not rjcode:
                            logger.warning(f"[未知] 无法从文件名提取RJ号，跳过字幕补配预检和预检查重: {os.path.basename(task.source_path)}")
                            # 小型压缩包且 RJ 号未知：视作疑似字幕包，无法自动关联，转入问题作品等待人工处理
                            if (
                                task.auto_classify
                                and getattr(config.auto_process, 'import_linked_translation_subtitles', False)
                                and os.path.isfile(task.source_path)
                            ):
                                try:
                                    _unknown_size = os.path.getsize(task.source_path)
                                except OSError:
                                    _unknown_size = 0
                                if 0 < _unknown_size < 10 * 1024 * 1024:
                                    _reason = "小型压缩包无法识别 RJ 号，需人工处理"
                                    task.fail(_reason)
                                    self._record_problem_work_for_extract_failure(task, None, _reason)
                                    logger.warning(
                                        f"[未知] 小型压缩包未识别到 RJ 号，已转入问题作品: "
                                        f"source={os.path.basename(task.source_path)} size={_unknown_size}"
                                    )
                                    await self._abort_precheck(precheck_task)
                                    return
                        elif not task.auto_classify:
                            logger.info(f"[{rjcode}] auto_classify=False，跳过字幕补配预检和预检查重")
                        else:
                            if getattr(config.auto_process, 'import_linked_translation_subtitles', False):
                                from .linked_subtitle_import_service import get_linked_subtitle_import_service

                                linked_import_service = get_linked_subtitle_import_service()
                                try:
                                    linked_result = await linked_import_service.queue_pending_archive_import(task, rjcode)
                                except Exception as exc:
                                    linked_result = {"handled": False, "reason": str(exc)}
                                    logger.warning(f"[{rjcode}] 关联字幕自动导入预检失败，回退原问题队列逻辑: {exc}")

                                if linked_result.get("handled"):
                                    record = linked_result.get("record") or {}
                                    preview = linked_result.get("preview") or {}
                                    source_label = os.path.basename(task.source_path or "").strip() or rjcode or "字幕补配预检"
                                    task.task_metadata = {
                                        **(task.task_metadata or {}),
                                        "linked_subtitle_import": record,
                                        "linked_subtitle_preview": preview,
                                        "source_mode": "linked_translation_archive_pending",
                                        "task_domain": "subtitle_import",
                                        "task_kind": "linked_translation_archive_pending",
                                        "source_page": "subtitle-import",
                                        "source_action": "linked_translation_archive_pending",
                                        "source_label": source_label,
                                        "business_key": str(record.get("id") or task.id),
                                    }
                                    task.output_path = ""
                                    task.status = TaskStatus.COMPLETED
                                    task.update_progress(100, "已加入字幕补配预检列表，请在字幕补配页继续处理")
                                    task.completed_at = datetime.now()
                                    logger.info(
                                        f"[{rjcode}] 命中关联字幕补配预检分支，已挂入字幕补配页: "
                                        f"target={preview.get('target_rjcode', '')} record={record.get('id', '')}"
                                    )
                                    await self._abort_precheck(precheck_task)
                                    return

                                preview = linked_result.get("preview") or {}
                                existing_subtitle_problem = await linked_import_service.create_existing_subtitle_problem(
                                    source_path=task.source_path,
                                    preview=preview,
                                    task_id=task.id,
                                    queue_origin="auto_process",
                                )
                                if existing_subtitle_problem.get("handled"):
                                    task.task_metadata = {
                                        **(task.task_metadata or {}),
                                        "linked_subtitle_preview": preview,
                                        "linked_subtitle_problem": existing_subtitle_problem,
                                        "source_mode": "linked_translation_archive_existing_subtitle_conflict",
                                    }
                                    task.output_path = ""
                                    task.status = TaskStatus.COMPLETED
                                    task.update_progress(100, "原作目录已有字幕，已加入问题作品列表")
                                    task.completed_at = datetime.now()
                                    logger.info(
                                        f"[{rjcode}] 原作目录已有字幕，已转入问题作品列表: "
                                        f"target={preview.get('target_rjcode', '')} conflict={existing_subtitle_problem.get('conflict_id', '')}"
                                    )
                                    await self._abort_precheck(precheck_task)
                                    return
                            else:
                                logger.info(f"[{rjcode}] 字幕补配预检已禁用，跳过")

                            preview = linked_result.get("preview") or {}
                            fatal_extract_error = str(preview.get("fatal_extract_error") or "").strip()
                            if fatal_extract_error:
                                task.fail(fatal_extract_error)
                                self._record_problem_work_for_extract_failure(
                                    task,
                                    rjcode,
                                    fatal_extract_error,
                                )
                                logger.error(f"[{rjcode}] 字幕补配预检已确认解压失败，任务终止: {fatal_extract_error}")
                                await self._abort_precheck(precheck_task)
                                return
                            if preview.get("kikoeru_target_is_empty_shell"):
                                _empty_reason = "字幕补配时发现服务器作品为空壳"
                                task.fail(_empty_reason)
                                self._record_problem_work_for_extract_failure(task, rjcode, _empty_reason)
                                logger.warning(
                                    f"[{rjcode}] 服务器作品文件树为空，已转入问题作品: "
                                    f"target={preview.get('target_rjcode', '')}"
                                )
                                await self._abort_precheck(precheck_task)
                                return
                            logger.info(
                                f"[{rjcode}] 未进入字幕补配预检分支: "
                                f"target={preview.get('target_rjcode', '')} "
                                f"reason={linked_result.get('reason') or preview.get('reason') or 'conditions_not_met'}"
                            )
                            if preview:
                                task.task_metadata = {
                                    **(task.task_metadata or {}),
                                    "linked_subtitle_preview": preview,
                                }
                                if self._should_block_uncertain_dlsite_linkage(preview):
                                    _reason = (
                                        str(preview.get("dlsite_linkage_uncertain_reason") or preview.get("reason") or "").strip()
                                        or "DLsite 关联链结果不完整，疑似翻译作品，等待重试后重新预检"
                                    )
                                    task.output_path = ""
                                    retry_after = datetime.now() + timedelta(minutes=15)
                                    task.task_metadata = {
                                        **(task.task_metadata or {}),
                                        "retry_source": "linked_subtitle_precheck",
                                        "retry_kind": "dlsite_linkage_uncertain",
                                    }
                                    task.set_waiting_retry(_reason, retry_after)
                                    logger.warning(
                                        f"[{rjcode}] DLsite 关联链不完整，疑似翻译作品，等待重试: "
                                        f"reason={_reason} retry_after={retry_after.isoformat()}"
                                    )
                                    await self._abort_precheck(precheck_task)
                                    return
                                if self._should_block_linked_translation_without_subtitles(preview):
                                    _reason = (
                                        str(preview.get("reason") or "").strip()
                                        or "翻译作命中已收录原作，但来源压缩包未发现可补配字幕"
                                    )
                                    self._record_linked_translation_without_subtitles_problem(
                                        task,
                                        preview,
                                        _reason,
                                    )
                                    task.output_path = ""
                                    task.status = TaskStatus.WAITING_MANUAL
                                    task.update_progress(100, "翻译作命中已收录原作，但未发现可补配字幕，已加入问题作品列表")
                                    task.completed_at = datetime.now()
                                    logger.warning(
                                        f"[{rjcode}] 翻译作命中已收录原作但包内无字幕，已转入问题作品: "
                                        f"target={preview.get('target_rjcode', '')} reason={_reason}"
                                    )
                                    await self._abort_precheck(precheck_task)
                                    return

                            if not config.auto_process.check_duplicate:
                                logger.info(f"[{rjcode}] 预检查重已禁用，跳过")
                            else:
                                # 小型压缩包（< 10MB）且开启了字幕补配预检：
                                # 不走 Kikoeru RJ 查重，改用包内字幕是否存在来判断。
                                # 有字幕 → 本应已被字幕补配路由处理，此处只做日志；
                                # 无字幕 → 视为非法/不明小包，转入问题作品等待人工。
                                _is_small_subtitle_candidate = False
                                if (
                                    getattr(config.auto_process, 'import_linked_translation_subtitles', False)
                                    and os.path.isfile(task.source_path)
                                ):
                                    try:
                                        _src_size = os.path.getsize(task.source_path)
                                    except OSError:
                                        _src_size = 0
                                    if 0 < _src_size < 10 * 1024 * 1024:
                                        _is_small_subtitle_candidate = True

                                if _is_small_subtitle_candidate:
                                    _preview_subtitle_count = int(preview.get("subtitle_count") or 0)
                                    _kikoeru_has_work = bool(preview.get("kikoeru_has_work") or preview.get("kikoeru_target_found"))
                                    _kikoeru_needs_subtitle = bool(preview.get("kikoeru_needs_subtitle"))
                                    _kikoeru_empty_shell = bool(preview.get("kikoeru_target_is_empty_shell"))
                                    _kikoeru_confident = bool(preview.get("kikoeru_route_confident"))
                                    if (
                                        _kikoeru_has_work
                                        and not _kikoeru_needs_subtitle
                                        and not _kikoeru_empty_shell
                                    ):
                                        # 本地库存已有字幕 → 小包视为重复，转问题作品
                                        _reason = "小型压缩包对应作品在本地库存已有字幕，按重复处理"
                                        task.fail(_reason)
                                        self._record_problem_work_for_extract_failure(task, rjcode, _reason)
                                        logger.warning(
                                            f"[{rjcode}] 小型压缩包对应本地库存作品已有字幕，转入问题作品: "
                                            f"source={os.path.basename(task.source_path)}"
                                        )
                                        await self._abort_precheck(precheck_task)
                                        return
                                    elif not _kikoeru_has_work and _kikoeru_confident:
                                        if _preview_subtitle_count > 0:
                                            _reason = "小型压缩包对应 RJ 作品未在 ready 库存索引命中，但包内含字幕，需人工核查"
                                            task.fail(_reason)
                                            self._record_problem_work_for_extract_failure(task, rjcode, _reason)
                                            logger.warning(
                                                f"[{rjcode}] 小型压缩包无原始作品但包内含字幕，转入问题作品: "
                                                f"source={os.path.basename(task.source_path)} subtitle_count={_preview_subtitle_count}"
                                            )
                                            await self._abort_precheck(precheck_task)
                                            return
                                        logger.info(
                                            f"[{rjcode}] 小型压缩包未命中 ready 库存索引且包内无字幕，按新作继续解压入库: "
                                            f"source={os.path.basename(task.source_path)}"
                                        )
                                    elif _preview_subtitle_count == 0:
                                        _reason = "小型压缩包内未发现字幕文件，需人工核查"
                                        task.fail(_reason)
                                        self._record_problem_work_for_extract_failure(task, rjcode, _reason)
                                        logger.warning(
                                            f"[{rjcode}] 小型压缩包无字幕，跳过 Kikoeru 查重，转入问题作品: "
                                            f"source={os.path.basename(task.source_path)}"
                                        )
                                        await self._abort_precheck(precheck_task)
                                        return
                                    else:
                                        logger.info(
                                            f"[{rjcode}] 小型压缩包内含字幕，跳过 Kikoeru 查重，继续处理: "
                                            f"subtitle_count={_preview_subtitle_count}"
                                        )
                                else:
                                    # 解压前多 RJ 合集预检：合集包（一个大压缩包内有多个独立 RJ 顶层目录）
                                    # 的 inferred_rjcode 只是清单里第一个 RJ，不代表整包语义。若这个 RJ 已
                                    # 在库存命中，原流程会把整个大包都判成"完全重复"跳过解压，剩下几十个
                                    # 不重复的 RJ 永远没机会处理。这里先扫一遍清单：若顶层 >=2 个独立 RJ，
                                    # 跳过基于第一个 RJ 的整体查重，让解压完成后的步骤 1.4
                                    # （_detect_multi_rj_subfolders + _dispatch_multi_rj_subtasks）拆分子任务，
                                    # 每个 RJ 各自查重。失败回退到原行为。
                                    skip_aggregate_dedup = False
                                    rjcode_locked_for_dedup = bool(
                                        (task.task_metadata or {}).get('rjcode_lock')
                                    )
                                    if (
                                        not rjcode_locked_for_dedup
                                        and os.path.isfile(task.source_path)
                                    ):
                                        try:
                                            archive_top_rjs = await extract_service.collect_top_level_rjcodes(
                                                task.source_path,
                                                task=task,
                                            )
                                        except Exception:
                                            archive_top_rjs = []
                                            logger.warning(
                                                f"[{rjcode}] 解压前多 RJ 合集预检异常，回退到单作品查重",
                                                exc_info=True,
                                            )
                                        if len(archive_top_rjs) >= 2:
                                            _preview = archive_top_rjs[:8]
                                            _more = (
                                                f"... +{len(archive_top_rjs) - 8}"
                                                if len(archive_top_rjs) > 8
                                                else ""
                                            )
                                            logger.info(
                                                f"[{rjcode}] 清单检测到 {len(archive_top_rjs)} 个独立 RJ"
                                                f"（合集包），跳过整体查重，"
                                                f"交给解压后多作品拆分: {_preview}{_more}"
                                            )
                                            skip_aggregate_dedup = True
                                    if skip_aggregate_dedup:
                                        logger.info(
                                            f"[{rjcode}] 合集包跳过解压前整体查重，"
                                            "每个子 RJ 将在拆分后各自查重"
                                        )
                                    else:
                                        is_duplicate = await classifier.check_duplicate_before_extract(rjcode, task, self)
                                        logger.info(f"[{rjcode}] 重复检查结果: {is_duplicate}")
                                        if is_duplicate:
                                            logger.info(f"[{rjcode}] 作品已存在或正在处理中，已添加到问题作品列表")
                                            task.status = TaskStatus.WAITING_MANUAL
                                            task.update_progress(100, "重复作品，请在问题作品页面处理")
                                            task.completed_at = datetime.now()
                                            await self._abort_precheck(precheck_task)
                                            return


                    except Exception:
                        await self._abort_precheck(precheck_task)
                        raise

                # 不等待后台 list 预检。预检和正式解压不共享槽位，预检结果只是缓存优化；
                # 如果这里 await，解压槽空闲时反而会被慢清单拖住。
                if precheck_task is not None and not precheck_task.done():
                    logger.info(
                        f"[{rjcode}] 后台 list 预检仍在运行，步骤1解压不等待；"
                        "清单完成后会自动写缓存"
                    )

                # 步骤1: 解压
                logger.info(f"[{rjcode}] 步骤1: 解压")
                if config.auto_process.extract:
                    task.update_progress(10, "解压中")
                    extracted_path = await extract_service.extract(task)
                    logger.info(f"[{rjcode}] 解压结果路径: {extracted_path}")
                    if not extracted_path:
                        if task.is_cancelled():
                            logger.info(f"[{rjcode}] 解压已取消，任务终止")
                            return
                        failure_reason = task.error_message or "解压失败"
                        self._record_problem_work_for_extract_failure(
                            task,
                            rjcode,
                            failure_reason
                        )
                        task.error_message = failure_reason
                        task.status = TaskStatus.WAITING_MANUAL
                        task.update_progress(100, "解压失败，已加入问题作品列表")
                        task.completed_at = datetime.now()
                        logger.error(f"[{rjcode}] 解压失败，任务终止")
                        return
                else:
                    logger.info(f"[{rjcode}] 步骤[解压]已禁用，跳过")
                    extracted_path = task.source_path
                    if os.path.isfile(extracted_path):
                        logger.error(f"[{rjcode}] 解压已禁用但源路径是文件，任务终止")
                        return

                await task.wait_if_paused()
                if task.is_cancelled():
                    logger.info(f"[{rjcode}] 任务已取消")
                    return

                # 步骤1.4: 多作品压缩包检测 —— 当压缩包按「社团/RJ 作品/...」组织时，
                # 解压根目录里会同时存在多个独立 RJ 子目录。原流程会把整个临时目录
                # 当作单作品入库，导致只有第一个 RJ 留下、其余 RJ 被吞并。这里在重复
                # 检查之前先做一次多 RJ 扫描：若发现 >=2 个独立 RJ 顶层目录，把每个
                # 子目录搬到独立临时位置并派发为 PROCESS_EXISTING_FOLDER 子任务，
                # 父任务负责归档原压缩包后即标记完成，剩下的元数据/重命名/分类全部
                # 由各 RJ 自己的子任务独立完成，互不影响。
                if not bool((task.task_metadata or {}).get('rjcode_lock')):
                    try:
                        multi_rj_dirs = self._detect_multi_rj_subfolders(extracted_path)
                    except Exception:
                        multi_rj_dirs = []
                        logger.warning(f"[{rjcode}] 多作品包检测失败，回退到单作品流程", exc_info=True)
                    if multi_rj_dirs and len(multi_rj_dirs) >= 2:
                        rj_list = [d.get("rjcode") for d in multi_rj_dirs]
                        logger.info(
                            f"[{rjcode}] 检测到压缩包内含 {len(multi_rj_dirs)} 个独立 RJ 作品: {rj_list}"
                        )
                        task.update_progress(45, f"检测到 {len(multi_rj_dirs)} 个独立作品，正在拆分子任务")
                        subtask_ids = await self._dispatch_multi_rj_subtasks(
                            task, extracted_path, multi_rj_dirs
                        )
                        if subtask_ids:
                            # 派发成功 —— 父任务直接进入归档/完成阶段，不再走单作品的
                            # 元数据 / 重命名 / 扁平化 / 分类 / 字幕等链路。
                            task.update_progress(90, f"已拆分为 {len(subtask_ids)} 个独立入库子任务")
                            if config.auto_process.archive and not task.skip_archive:
                                try:
                                    await self._archive_source_file(task)
                                except Exception:
                                    logger.warning(
                                        f"[{rjcode}] 多作品拆分后归档原压缩包失败",
                                        exc_info=True,
                                    )
                            else:
                                if task.skip_archive:
                                    logger.info(f"[{rjcode}] 多作品拆分（重新处理模式），跳过归档")
                                else:
                                    logger.info(f"[{rjcode}] 多作品拆分，步骤[归档压缩包]已禁用")
                            task.update_progress(100, f"已拆分为 {len(subtask_ids)} 个独立入库子任务")
                            task.complete()
                            try:
                                from .notification_helper import (
                                    _load_circle_work_map,
                                    build_recent_logs,
                                    dlsite_cover_url,
                                    set_notification_extra,
                                    upgrade_dlsite_cover_to_hd,
                                )
                                dispatch_records = list(
                                    (task.task_metadata or {}).get("multi_rj_dispatch_records") or []
                                )
                                dispatch_failures = list(
                                    (task.task_metadata or {}).get("multi_rj_dispatch_failures") or []
                                )
                                rj_list_text = "、".join(
                                    str(r.get("rjcode") or "?") for r in dispatch_records
                                )
                                summary_text = (
                                    f"压缩包内含 {len(subtask_ids)} 个独立 RJ 作品，"
                                    f"已自动拆分为独立入库子任务：{rj_list_text}"
                                )
                                # 一次性查 circle_works 把所有子 RJ 的封面 / 标题 / 社团名补出来；
                                # 查不到的 RJ 用 DLsite 公开 URL 兜底，避免邮件出现一堆“无封面”。
                                rj_work_codes = [
                                    str(rec.get("rjcode") or "").strip().upper()
                                    for rec in dispatch_records
                                    if rec.get("rjcode")
                                ]
                                try:
                                    work_map = _load_circle_work_map("", rj_work_codes)
                                except Exception:
                                    work_map = {}
                                    logger.warning(
                                        f"[{rjcode}] 拆分子任务卡片补元数据失败，回退仅展示 RJ 号",
                                        exc_info=True,
                                    )
                                multi_cards: list[dict] = []
                                for rec in dispatch_records:
                                    sub_rj_value = str(rec.get("rjcode") or "").strip().upper()
                                    sub_id_value = str(rec.get("task_id") or "").strip()
                                    work_row = work_map.get(sub_rj_value) or {}
                                    work_title_value = str(work_row.get("title") or "").strip() or sub_rj_value or "拆分子任务"
                                    circle_name_value = str(work_row.get("maker_name") or "").strip()
                                    cover_value = upgrade_dlsite_cover_to_hd(
                                        work_row.get("image_url") or "",
                                        sub_rj_value,
                                    ) or dlsite_cover_url(sub_rj_value)
                                    badges_text: list[str] = []
                                    if work_row.get("has_asmr_one"):
                                        badges_text.append("ASMR.one 可下载")
                                    if work_row.get("has_kikoeru"):
                                        badges_text.append("KIKOERU 已有")
                                    changes_list: list[dict] = []
                                    if circle_name_value:
                                        changes_list.append({"icon": "users", "text": f"社团：{circle_name_value}"})
                                    if badges_text:
                                        changes_list.append({"icon": "tag", "text": " · ".join(badges_text)})
                                    changes_list.append({
                                        "icon": "git-branch",
                                        "text": f"已派发独立子任务 {sub_id_value[:8]}" if sub_id_value else "已派发独立子任务",
                                    })
                                    multi_cards.append({
                                        "rjcode": sub_rj_value,
                                        "title": work_title_value,
                                        "cover_url": cover_value,
                                        "circle_name": circle_name_value,
                                        "size_text": "",
                                        "file_count": 0,
                                        "count_label": "",
                                        "changes": changes_list,
                                        "status": "pending",
                                        "error": "",
                                    })
                                # 失败派发的 RJ 也单独成卡，方便邮件里立刻看到
                                for fail in dispatch_failures:
                                    fail_rj = str(fail.get("rjcode") or "").strip().upper()
                                    multi_cards.append({
                                        "rjcode": fail_rj,
                                        "title": fail_rj or "派发失败",
                                        "cover_url": dlsite_cover_url(fail_rj) if fail_rj else "",
                                        "circle_name": "",
                                        "size_text": "",
                                        "file_count": 0,
                                        "count_label": "",
                                        "changes": [{
                                            "icon": "x-circle",
                                            "text": str(fail.get("error") or "派发失败"),
                                        }],
                                        "status": "failed",
                                        "error": str(fail.get("error") or ""),
                                    })
                                set_notification_extra(
                                    task,
                                    summary=summary_text,
                                    recent_logs=build_recent_logs(task, max_lines=30),
                                    rj_work_cards=multi_cards,
                                    stats={
                                        "total_files": 0,
                                        "total_size": "",
                                        "filtered_count": 0,
                                        "filtered_size": "",
                                        "duration": "",
                                        "multi_rj_subtask_count": len(subtask_ids),
                                        "multi_rj_dispatch_failed": len(dispatch_failures),
                                    },
                                )
                            except Exception:
                                logger.warning(
                                    f"[{rjcode}] 多作品拆分通知 payload 构建失败",
                                    exc_info=True,
                                )
                            logger.info(
                                f"[{rjcode}] ========== 任务完成（多作品拆分: {len(subtask_ids)} 个子任务） =========="
                            )
                            return
                        else:
                            logger.warning(
                                f"[{rjcode}] 多作品包检测命中但未派发任何子任务，回退到单作品流程"
                            )

                # 步骤1.5: 解压后重复检查（如果预检时无法提取 RJ 号）
                # 从解压后的文件夹路径提取 RJ 号
                rjcode_locked = bool((task.task_metadata or {}).get('rjcode_lock'))
                if rjcode_locked:
                    extracted_rjcode = rjcode
                    logger.info(f"[{rjcode}] 密码库权威绑定已锁定 RJ，跳过解压后覆盖")
                else:
                    extracted_rjcode = self._extract_rjcode(extracted_path) or str(task.task_metadata.get('inferred_rjcode') or '').strip().upper()
                    logger.info(f"[{rjcode}] 从解压后路径提取到的RJ号: {extracted_rjcode}")

                if not rjcode_locked and extracted_rjcode and extracted_rjcode != rjcode:
                    # 更新任务的 RJ 号
                    rjcode = self._sync_task_rjcode(task, extracted_rjcode, source="extracted_path")
                    logger.info(f"[{rjcode}] 更新任务RJ号为解压后提取的RJ号")
                    
                    # 如果预检时没有提取到 RJ 号，现在进行重复检查
                    if config.auto_process.check_duplicate and task.auto_classify:
                        logger.info(f"[{rjcode}] 解压后进行重复检查")
                        is_duplicate = await classifier.check_duplicate_before_extract(rjcode, task, self)
                        logger.info(f"[{rjcode}] 解压后重复检查结果: {is_duplicate}")
                        if is_duplicate:
                            logger.info(f"[{rjcode}] 作品已存在或正在处理中，移动到冲突目录")
                            # 移动到冲突目录
                            conflict_base_path = os.path.join(config.storage.library_path, '_conflicts')
                            os.makedirs(conflict_base_path, exist_ok=True)
                            final_path = classifier._move_with_rename(extracted_path, conflict_base_path)
                            task.output_path = final_path
                            task.status = TaskStatus.WAITING_MANUAL
                            task.update_progress(100, "重复作品，请在问题作品页面处理")
                            task.completed_at = datetime.now()
                            return

                # 步骤2: 获取元数据
                logger.debug(f"[{rjcode}] 步骤2: 获取元数据")
                if config.auto_process.fetch_metadata:
                    task.update_progress(40, "获取元数据")
                    metadata = await metadata_service.fetch(extracted_path, task)
                    effective_rjcode = self._get_effective_rjcode(task, extracted_path)
                    if effective_rjcode and not metadata.get('rjcode'):
                        metadata['rjcode'] = effective_rjcode
                    logger.debug(f"[{rjcode}] 元数据: {metadata.get('work_name', '未知')}")
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        **metadata,
                    }
                    if effective_rjcode:
                        self._sync_task_rjcode(task, effective_rjcode, source=task.task_metadata.get('rjcode_source') or 'metadata_fallback')
                else:
                    logger.info(f"[{rjcode}] 步骤[获取元数据]已禁用，跳过")
                    metadata = {'rjcode': self._get_effective_rjcode(task, extracted_path) or rjcode}
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        **metadata,
                    }
                    self._sync_task_rjcode(task, metadata.get('rjcode'), source='task_fallback')

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤3: 重命名
                logger.debug(f"[{rjcode}] 步骤3: 重命名")
                if config.auto_process.rename:
                    task.update_progress(60, "重命名文件夹")
                    from .rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = await rename_service.rename(extracted_path, task)
                    logger.debug(f"[{rjcode}] 重命名后路径: {renamed_path}")
                else:
                    logger.info(f"[{rjcode}] 步骤[重命名]已禁用，跳过")
                    renamed_path = extracted_path

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤4: 过滤
                logger.debug(f"[{rjcode}] 步骤4: 过滤")
                if config.auto_process.filter:
                    task.update_progress(75, "过滤文件中")
                    filter_result = await filter_service.filter(renamed_path, task)
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        "file_tree_items": list((filter_result or {}).get("all_items") or []),
                        "filtered_files": list((filter_result or {}).get("filtered_files") or []),
                        "filtered_dirs": list((filter_result or {}).get("filtered_dirs") or []),
                        "filtered_items": list((filter_result or {}).get("filtered_items") or []),
                        "filtered_count": int((filter_result or {}).get("filtered_count") or 0),
                        "filtered_size": int((filter_result or {}).get("filtered_size") or 0),
                    }
                else:
                    logger.info(f"[{rjcode}] 步骤[过滤]已禁用，跳过")

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤5: 扁平化
                logger.debug(f"[{rjcode}] 步骤5: 扁平化")
                if config.rename.flatten_single_subfolder:
                    task.update_progress(78, "扁平化文件夹结构")
                    from .rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = rename_service._flatten_single_subfolder(renamed_path)
                    logger.debug(f"[{rjcode}] 扁平化后路径: {renamed_path}")

                if config.rename.remove_empty_folders:
                    task.update_progress(79, "清理空文件夹")
                    rename_service.remove_empty_folders(renamed_path, remove_root=False)

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤5.5: 字幕文件繁体转简体（如果启用）
                if getattr(config.asmr_sync, 'simplify_chinese_enabled', False) if hasattr(config, 'asmr_sync') else False:
                    task.update_progress(79, "字幕繁体转简体")
                    from .subtitle_sync_service import get_subtitle_sync_service
                    subtitle_svc = get_subtitle_sync_service()
                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                    if simplify_result['converted_files'] > 0:
                        logger.info(f"[{rjcode}] 字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                   f"转换 {simplify_result['converted_files']} 个文件")

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤6: 智能分类
                logger.debug(f"[{rjcode}] 步骤6: 智能分类")
                if config.auto_process.classify and task.auto_classify:
                    task.update_progress(80, "智能分类")
                    final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                    task.output_path = final_path
                    logger.debug(f"[{rjcode}] 分类后路径: {final_path}")
                else:
                    if not config.auto_process.classify:
                        logger.info(f"[{rjcode}] 步骤[智能分类]已禁用，跳过")
                    task.output_path = renamed_path

                # 步骤7: 归档压缩包
                logger.debug(f"[{rjcode}] 步骤7: 归档压缩包")
                if config.auto_process.archive and not task.skip_archive:
                    task.update_progress(95, "归档压缩包")
                    await self._archive_source_file(task)
                else:
                    if task.skip_archive:
                        logger.info(f"[{rjcode}] 重新处理模式，跳过归档")
                    else:
                        logger.info(f"[{rjcode}] 步骤[归档压缩包]已禁用，跳过")

                # 步骤7.5: 处理嵌套字幕压缩包（小型压缩包，跳过了常规解压，在此触发字幕补配预检）
                nested_subtitle_filenames = list(
                    (task.task_metadata or {}).get("nested_subtitle_archive_filenames") or []
                )
                if nested_subtitle_filenames and task.output_path and rjcode:
                    await self._queue_nested_subtitle_archives(
                        task, rjcode, task.output_path, nested_subtitle_filenames
                    )

                if task.output_path and rjcode and rjcode != "未知":
                    try:
                        from .circle_completion_service import get_circle_completion_service

                        await get_circle_completion_service().sync_owned_for_rj(
                            rjcode,
                            folder_path=task.output_path,
                            library_id=str((task.task_metadata or {}).get("target_library_id") or ""),
                        )
                    except Exception:
                        logger.warning("[%s] 标准解压入库完成后同步社团拥有态失败 path=%s", rjcode, task.output_path, exc_info=True)

                task.update_progress(100, "完成")
                task.complete()
                try:
                    from .notification_helper import build_import_notification_extra, set_notification_extra
                    set_notification_extra(task, **build_import_notification_extra(task))
                except Exception:
                    logger.warning("[通知] 构建导入完成 payload 失败", exc_info=True)
                logger.info(f"[{rjcode}] ========== 任务完成 ==========")
                
            elif task.type == TaskType.PROCESS_EXISTING_FOLDER:
                from ..config.settings import get_config
                config = get_config()

                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()

                existing_folder_path = task.source_path
                logger.debug(f"[{rjcode}] 处理已存在文件夹: {existing_folder_path}")

                effective_existing_rjcode = self._get_effective_rjcode(task, existing_folder_path)
                rjcode = self._sync_task_rjcode(
                    task,
                    effective_existing_rjcode,
                    source=(task.task_metadata or {}).get("rjcode_source") or "existing_folder_scan",
                ) or effective_existing_rjcode or "未知"
                logger.debug(f"[{rjcode}] 已有文件夹任务RJ号: {rjcode}")
                resolution_mode = str((task.task_metadata or {}).get('existing_folder_resolution') or '').strip().upper()
                skip_conflict_retry_precheck = self._should_skip_conflict_retry_precheck(task)
                skip_duplicate_precheck = bool((task.task_metadata or {}).get("skip_duplicate_precheck"))
                if skip_conflict_retry_precheck:
                    logger.info(f"[{rjcode}] 问题作品处理任务，跳过重复预检")
                    task.update_progress(5, "准备处理")
                elif resolution_mode in {"KEEP_NEW", "MERGE"}:
                    logger.info(f"[{rjcode}] 已指定冲突处理方案 {resolution_mode}，跳过重复预检")
                    task.update_progress(5, "准备处理")
                elif skip_duplicate_precheck:
                    logger.info(f"[{rjcode}] 已有文件夹查重缓存确认无冲突，跳过重复预检")
                    task.update_progress(5, "准备处理")
                elif config.process_existing.check_duplicate and rjcode and task.auto_classify:
                    # 步骤0: 预检重复
                    logger.debug(f"[{rjcode}] 步骤0: 预检重复")
                    task.update_progress(5, "预检中")
                    from .duplicate_service import get_duplicate_service
                    duplicate_service = get_duplicate_service()

                    check_result = await duplicate_service.check_duplicate_enhanced(
                        rjcode,
                        check_linked_works=True,
                        cue_languages=['CHI_HANS', 'CHI_HANT', 'ENG']
                    )
                    logger.debug(f"[{rjcode}] 重复检查结果: is_duplicate={check_result.is_duplicate}")

                    if check_result.is_duplicate:
                        conflict_type = check_result.conflict_type

                        if check_result.direct_duplicate:
                            logger.warning(f"[{rjcode}] 已存在: {check_result.direct_duplicate['path']}")
                        elif check_result.linked_works_found:
                            linked_rjcodes = [w['rjcode'] for w in check_result.linked_works_found]
                            logger.warning(f"[{rjcode}] 关联作品冲突: {linked_rjcodes}")

                        source_for_conflict = await self._stabilize_extract_subtask_conflict_source(
                            task,
                            existing_folder_path,
                            classifier,
                        )
                        classifier._add_to_conflict_works(
                            task.id,
                            rjcode,
                            conflict_type,
                            check_result.direct_duplicate['path'] if check_result.direct_duplicate else
                            (check_result.linked_works_found[0]['path'] if check_result.linked_works_found else "未知路径"),
                            source_for_conflict,
                            {},
                            linked_works_info=check_result.linked_works_found,
                            analysis_info=check_result.analysis_info,
                            related_rjcodes=check_result.related_rjcodes
                        )

                        logger.info(f"[{rjcode}] 已添加到问题作品列表")
                        task.status = TaskStatus.WAITING_MANUAL
                        task.update_progress(100, f"发现{get_conflict_type_name(conflict_type)}，请在问题作品页面处理")
                        task.completed_at = datetime.now()
                        return

                    is_processing = await classifier.check_duplicate_before_extract(rjcode, task, self)
                    if is_processing:
                        stable_source_path = await self._stabilize_extract_subtask_conflict_source(
                            task,
                            existing_folder_path,
                            classifier,
                        )
                        self._rewrite_active_conflict_new_path(task.id, existing_folder_path, stable_source_path)
                        logger.info(f"[{rjcode}] 正在处理中，已添加到问题作品列表")
                        task.status = TaskStatus.WAITING_MANUAL
                        task.update_progress(100, "正在处理中，请在问题作品页面查看")
                        task.completed_at = datetime.now()
                        return
                else:
                    if not config.process_existing.check_duplicate:
                        logger.info(f"[{rjcode}] 步骤[预检重复]已禁用，跳过")
                    task.update_progress(5, "准备处理")

                extracted_path = existing_folder_path

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤1: 获取元数据
                logger.debug(f"[{rjcode}] 步骤1: 获取元数据")
                if config.process_existing.fetch_metadata:
                    task.update_progress(30, "获取元数据")
                    metadata = await metadata_service.fetch(extracted_path, task)
                    effective_rjcode = self._get_effective_rjcode(task, extracted_path)
                    if effective_rjcode and not metadata.get('rjcode'):
                        metadata['rjcode'] = effective_rjcode
                    logger.debug(f"[{rjcode}] 元数据: {metadata.get('work_name', '未知')}")
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        **metadata,
                    }
                    if effective_rjcode:
                        self._sync_task_rjcode(task, effective_rjcode, source=task.task_metadata.get('rjcode_source') or 'metadata_fallback')
                else:
                    logger.info(f"[{rjcode}] 步骤[获取元数据]已禁用，跳过")
                    metadata = {'rjcode': self._get_effective_rjcode(task, extracted_path) or rjcode}
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        **metadata,
                    }
                    self._sync_task_rjcode(task, metadata.get('rjcode'), source='task_fallback')

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤2: 重命名
                logger.debug(f"[{rjcode}] 步骤2: 重命名")
                if config.process_existing.rename:
                    task.update_progress(50, "重命名文件夹")
                    from .rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = await rename_service.rename(extracted_path, task)
                    logger.debug(f"[{rjcode}] 重命名后路径: {renamed_path}")
                else:
                    logger.info(f"[{rjcode}] 步骤[重命名]已禁用，跳过")
                    renamed_path = extracted_path

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤3: 过滤
                logger.debug(f"[{rjcode}] 步骤3: 过滤")
                if config.process_existing.filter:
                    task.update_progress(70, "过滤文件中")
                    filter_result = await filter_service.filter(renamed_path, task)
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        "file_tree_items": list((filter_result or {}).get("all_items") or []),
                        "filtered_files": list((filter_result or {}).get("filtered_files") or []),
                        "filtered_dirs": list((filter_result or {}).get("filtered_dirs") or []),
                        "filtered_items": list((filter_result or {}).get("filtered_items") or []),
                        "filtered_count": int((filter_result or {}).get("filtered_count") or 0),
                        "filtered_size": int((filter_result or {}).get("filtered_size") or 0),
                    }
                else:
                    logger.info(f"[{rjcode}] 步骤[过滤]已禁用，跳过")

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                logger.debug(f"[{rjcode}] 步骤4: 扁平化")
                if config.rename.flatten_single_subfolder:
                    task.update_progress(75, "扁平化文件夹结构")
                    from .rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = rename_service._flatten_single_subfolder(renamed_path)
                    logger.debug(f"[{rjcode}] 扁平化后路径: {renamed_path}")

                if config.rename.remove_empty_folders:
                    task.update_progress(78, "清理空文件夹")
                    rename_service.remove_empty_folders(renamed_path, remove_root=False)

                # 步骤4.5: 从 Subtitles 目录导入 LRC 字幕（如果存在且启用）
                subtitle_folder = None
                subtitle_base = getattr(getattr(config, 'storage', None), 'asmr_subtitle_path', '')
                if config.process_existing.import_lrc and subtitle_base:
                    try:
                        if os.path.exists(subtitle_base) and rjcode:
                            # 查找匹配 RJ 号的字幕文件夹
                            from .subtitle_sync_service import get_subtitle_sync_service
                            subtitle_svc = get_subtitle_sync_service()
                            for item in os.listdir(subtitle_base):
                                item_path = os.path.join(subtitle_base, item)
                                if os.path.isdir(item_path):
                                    folder_rj = subtitle_svc.extract_rjcode_from_folder(item)
                                    if folder_rj and folder_rj.upper() == rjcode.upper():
                                        subtitle_folder = item_path
                                        logger.info(f"[{rjcode}] 找到匹配的字幕文件夹: {item}")
                                        break

                            if subtitle_folder:
                                # LRC 广告清理
                                if config.asmr_sync.lrc_clean_enabled:
                                    task.update_progress(79, "清理LRC广告")
                                    custom_patterns = config.asmr_sync.lrc_clean_patterns if hasattr(config.asmr_sync, 'lrc_clean_patterns') else None
                                    lrc_clean_result = subtitle_svc.clean_lrc_files_in_folder(subtitle_folder, custom_patterns)
                                    if lrc_clean_result['cleaned_files'] > 0:
                                        logger.info(f"[{rjcode}] LRC广告清理完成: 处理 {lrc_clean_result['total_files']} 个文件, "
                                                   f"清理 {lrc_clean_result['cleaned_files']} 个文件")

                                # 字幕繁简转换（字幕源文件夹）
                                if getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                                    task.update_progress(79, "字幕繁简转换中")
                                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(subtitle_folder)
                                    if simplify_result['converted_files'] > 0:
                                        logger.info(f"[{rjcode}] 字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                                   f"转换 {simplify_result['converted_files']} 个文件")

                                # 同步字幕到作品目录
                                task.update_progress(79, "同步字幕到作品目录")
                                sync_result = subtitle_svc.sync_subtitles_to_download(
                                    renamed_path,
                                    subtitle_folder
                                )
                                if sync_result['success']:
                                    logger.info(f"[{rjcode}] 字幕同步完成: 重命名 {len(sync_result['renamed_files'])} 个文件, "
                                               f"复制 {len(sync_result['copied_subtitles'])} 个字幕")
                                else:
                                    logger.warning(f"[{rjcode}] 字幕同步失败: {sync_result.get('errors', [])}")
                        elif not os.path.exists(subtitle_base):
                            logger.info(f"[{rjcode}] ASMR 字幕目录不存在，跳过 LRC 导入: {subtitle_base}")
                    except Exception as subtitle_error:
                        logger.warning(f"[{rjcode}] 可选 LRC 导入失败，继续已有文件夹入库: {subtitle_error}", exc_info=True)
                else:
                    if not config.process_existing.import_lrc:
                        logger.info(f"[{rjcode}] 步骤[LRC导入]已禁用，跳过")
                    else:
                        logger.info(f"[{rjcode}] 未配置 ASMR 字幕目录，跳过 LRC 导入")

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤4.6: 字幕繁简转换（作品目录内已有的字幕文件）
                if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                    from .subtitle_sync_service import get_subtitle_sync_service
                    subtitle_svc = get_subtitle_sync_service()
                    task.update_progress(79, "字幕繁简转换中")
                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                    if simplify_result['converted_files'] > 0:
                        logger.info(f"[{rjcode}] 字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                   f"转换 {simplify_result['converted_files']} 个文件")

                await task.wait_if_paused()
                if task.is_cancelled():
                    return

                # 步骤5: 智能分类
                logger.debug(f"[{rjcode}] 步骤5: 智能分类")
                if config.process_existing.classify and task.auto_classify:
                    task.update_progress(80, "智能分类")
                    final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                    task.output_path = final_path
                    logger.debug(f"[{rjcode}] 分类后路径: {final_path}")
                else:
                    if not config.process_existing.classify:
                        logger.info(f"[{rjcode}] 步骤[智能分类]已禁用，跳过")
                    task.output_path = renamed_path

                if task.output_path and rjcode and rjcode != "未知":
                    try:
                        from .circle_completion_service import get_circle_completion_service

                        await get_circle_completion_service().sync_owned_for_rj(
                            rjcode,
                            folder_path=task.output_path,
                            library_id=str((task.task_metadata or {}).get("target_library_id") or ""),
                        )
                    except Exception:
                        logger.warning("[%s] 已有文件夹入库完成后同步社团拥有态失败 path=%s", rjcode, task.output_path, exc_info=True)

                task.update_progress(100, "完成")
                task.complete()
                try:
                    from .notification_helper import build_import_notification_extra, set_notification_extra
                    set_notification_extra(task, **build_import_notification_extra(task))
                except Exception:
                    logger.warning("[通知] 构建导入完成 payload 失败", exc_info=True)
                logger.info(f"[{rjcode}] ========== 任务完成 ==========")
                
            else:
                if task.type == TaskType.EXTRACT:
                    service = ExtractService()
                    task.output_path = await service.extract(task)
                elif task.type == TaskType.FILTER:
                    service = FilterService()
                    await service.filter(task.source_path, task)
                elif task.type == TaskType.METADATA:
                    service = MetadataService()
                    task.task_metadata = await service.fetch(task.source_path, task)
                elif task.type == TaskType.RENAME:
                    service = RenameService()
                    await service.rename(task.source_path, task)
                elif task.type == TaskType.ASMR_SYNC_DOWNLOAD:
                    # ASMR 同步下载任务
                    await self._process_asmr_sync_download(task)
                elif task.type == TaskType.HTTP_DOWNLOAD:
                    await self._process_http_download(task)
                elif task.type == TaskType.BAIDU_NETDISK_DOWNLOAD:
                    await self._process_baidu_netdisk_download(task)
                elif task.type == TaskType.BAIDU_NETDISK_UPLOAD:
                    await self._process_baidu_netdisk_upload(task)
                elif task.type == TaskType.RJ_SUBTITLE_FETCH:
                    await self._process_rj_subtitle_fetch(task)
                elif task.type == TaskType.LOCAL_LIBRARY_UPLOAD:
                    await self._process_local_library_upload(task)
                elif task.type == TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW:
                    await self._process_library_folder_completion_preview(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_INDEX:
                    await self._process_circle_completion_index(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED:
                    await self._process_circle_completion_refresh_selected(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH:
                    task.update_progress(100, "完成")
                elif task.type == TaskType.CIRCLE_COMPLETION_BONUS_PROBE:
                    await self._process_circle_completion_bonus_probe(task)

                # 只有当任务没有被设置为其他状态（如 waiting_retry）时才标记为完成
                if task.status == TaskStatus.PROCESSING:
                    task.complete()
                    logger.info(f"[{rjcode}] ========== 任务完成 ==========")
                
        except asyncio.CancelledError:
            # `append_progress_log` 是 _process_asmr_sync_download / _process_rj_subtitle_fetch /
            # _process_circle_completion_index 等内部方法的局部闭包，专门给那几个任务类型
            # 写 task.task_metadata['progress_log'] 给前端 UI 用。外层 _process_task 这个
            # generic dispatcher 没有这个闭包，曾经误用过 → 任务被取消时（典型场景：用户暂停
            # 正在 _probe_password 跑 7zz 的 EXTRACT 任务）抛 NameError 把 cancel 流程整段毁掉。
            # 这里只写日志，task.cancel() 自身会更新状态、前端会反映，不再尝试写 progress_log。
            if task.status == TaskStatus.PAUSED and not task.is_cancelled():
                logger.info(f"[{rjcode}] 任务已暂停")
            elif not task.is_cancelled():
                logger.info(f"[{rjcode}] 任务已取消")
                task.cancel()
            else:
                logger.info(f"[{rjcode}] 任务已取消")
        except Exception as e:
            logger.error(f"[{rjcode}] 任务失败: {e}", exc_info=True)
            if task.type in {TaskType.EXTRACT, TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
                self._record_problem_work_for_task_failure(task, rjcode, str(e))
            task.fail(str(e))
            await asyncio.to_thread(
                self._refresh_conflict_resolution_progress,
                task,
                state="failed",
                error=str(e),
            )
            if task.type in {TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
                try:
                    from .notification_helper import build_import_notification_extra, set_notification_extra
                    set_notification_extra(task, **build_import_notification_extra(task, error=str(e)))
                except Exception:
                    logger.warning("[通知] 构建导入失败 payload 失败", exc_info=True)
            logger.info(f"[{rjcode}] ========== 任务失败 ==========")
        finally:
            # 操作记录优先写入，避免后续清理/通知异常导致整段 finally 中断而未落库
            try:
                from .activity_log_service import log_task_lifecycle_event

                log_task_lifecycle_event(task)
            except Exception:
                logger.warning("[操作记录] 任务周期记录失败", exc_info=True)
            try:
                from .task_notification_service import enqueue_notification_check
                asyncio.create_task(enqueue_notification_check(task))
            except Exception:
                logger.warning("[通知] 通知入队失败", exc_info=True)
            # 清理任务产生的临时文件（无论成功还是失败）
            try:
                self._resolve_retry_extract_conflict(task)
            except Exception:
                logger.warning("[任务清理] 刷新重试问题作品失败: task_id=%s", task.id, exc_info=True)
            try:
                self._resolve_completed_failure_followups(task)
            except Exception:
                logger.warning("[任务清理] 处理失败跟随项失败: task_id=%s", task.id, exc_info=True)
            try:
                self._finalize_conflict_resolution_task(task)
            except Exception:
                logger.warning("[任务清理] 完成问题作品处理链路失败: task_id=%s", task.id, exc_info=True)
            try:
                await self._cleanup_task_temp_extract_path(task)
            except Exception:
                logger.warning("[任务清理] 清理临时解压目录失败: task_id=%s", task.id, exc_info=True)
            try:
                await self._cleanup_failed_task(task)
            except Exception:
                logger.warning("[任务清理] 清理失败任务产物失败: task_id=%s", task.id, exc_info=True)
            try:
                self.processing.discard(task.id)
                # 清除RJ号处理标记
                if task.rjcode:
                    self.unmark_rjcode_processing(task.rjcode)
            except Exception:
                logger.warning("[任务清理] 清理运行中标记失败: task_id=%s", task.id, exc_info=True)
            try:
                await self._notify_progress(task)
            except Exception:
                logger.warning("[任务清理] 发送最终进度失败: task_id=%s", task.id, exc_info=True)
            try:
                await asyncio.to_thread(self.persist_task_center_item_snapshot, task)
            except Exception:
                logger.warning("[任务中心物化] 写入最终任务快照失败: task_id=%s", task.id, exc_info=True)
    
    async def _worker(self):
        """工作线程"""
        while not self._shutdown:
            try:
                # 控制并发数
                while len(self.processing) >= self.max_concurrent:
                    self._release_non_running_slots()
                    if len(self.processing) < self.max_concurrent:
                        break
                    await asyncio.sleep(0.1)
                
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if task.status != TaskStatus.PENDING:
                    logger.info(
                        "跳过非待处理队列项，避免占用并发槽: task_id=%s status=%s",
                        task.id,
                        task.status,
                    )
                    continue
                self.processing.add(task.id)
                
                # 创建任务处理协程
                asyncio.create_task(self._process_task(task))
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"工作线程错误: {e}")
    
    def start(self):
        """启动引擎"""
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("任务引擎已启动")

        # 启动重试调度器
        if not self._retry_scheduler_task:
            self._retry_scheduler_task = asyncio.create_task(self._retry_scheduler())
            logger.info("重试调度器已启动")

        # 加载等待重试的任务
        self.recover_stale_processing_tasks()
        self.load_waiting_retry_tasks()
        self.load_persisted_linked_subtitle_tasks()

    async def _retry_scheduler(self):
        """定时重试调度器，使用cron表达式"""
        from croniter import croniter
        from ..config.settings import get_config

        while not self._shutdown:
            try:
                config = get_config()
                cron_expr = config.asmr_sync.retry_cron if hasattr(config, 'asmr_sync') else "0 */1 * * *"

                # 计算下次执行时间
                cron = croniter(cron_expr, datetime.now())
                next_run = cron.get_next(datetime)
                wait_seconds = (next_run - datetime.now()).total_seconds()

                logger.info(f"[重试调度器] Cron: {cron_expr}, 下次执行: {next_run.strftime('%Y-%m-%d %H:%M:%S')} UTC, 等待 {wait_seconds/3600:.1f} 小时")

                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # 检查待重试任务
                await self._check_retry_tasks()

            except Exception as e:
                logger.error(f"重试调度器错误: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    async def _check_retry_tasks(self):
        """检查并重试等待中的任务（由cron调度器触发）"""
        from ..config.settings import get_config

        config = get_config()
        max_retry = config.asmr_sync.max_retry_count if hasattr(config, 'asmr_sync') else 10

        retry_count = 0
        for task_id, task in list(self.tasks.items()):
            if task.status == TaskStatus.WAITING_RETRY:
                # 检查重试次数
                if task.task_metadata.get('retry_count', 0) >= max_retry:
                    logger.warning(f"任务 {task_id} 已达到最大重试次数 {max_retry}，标记为失败")
                    task.fail("已达到最大重试次数")
                    continue

                # cron调度器触发，直接重试所有等待中的任务
                # 重入保护：若任务已在处理中或已是 PENDING，跳过
                if task_id in self.processing or task.status == TaskStatus.PROCESSING:
                    logger.debug(f"[Cron重试] 任务 {task_id} 已在执行中，跳过")
                    continue
                logger.info(f"[Cron重试] 重试任务 {task_id}: {task.rjcode}")
                with task._set_state_silent():
                    task.status = TaskStatus.PENDING
                    task.current_step = "等待重试"
                await self.queue.put(task)
                task.mark_changed("submitted")
                retry_count += 1

        if retry_count > 0:
            logger.info(f"[Cron重试] 已将 {retry_count} 个任务加入重试队列")

    def stop(self):
        """停止引擎"""
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
        if self._retry_scheduler_task:
            self._retry_scheduler_task.cancel()
        self._materialized_snapshot_executor.shutdown(wait=False, cancel_futures=True)

    def retry_task(self, task_id: str):
        """手动重试等待中的任务"""
        logger.info(f"[重试] 尝试重试任务: {task_id}")
        logger.info(f"[重试] 当前内存中的任务: {list(self.tasks.keys())}")

        if task_id in self.tasks:
            task = self.tasks[task_id]
            logger.info(f"[重试] 找到任务 {task_id}, 状态: {task.status}, RJ号: {task.rjcode}")
            if task.status == TaskStatus.WAITING_RETRY:
                # 重入保护：若任务已在处理中则不重复入队
                if task_id in self.processing:
                    logger.warning(f"[重试] 任务 {task_id} 已在处理中，跳过")
                    return False
                with task._set_state_silent():
                    task.status = TaskStatus.PENDING
                    task.current_step = "等待重试"
                asyncio.create_task(self.queue.put(task))
                task.mark_changed("submitted")
                logger.info(f"[重试] 任务 {task_id} ({task.rjcode}) 已加入重试队列")
                return True
            else:
                logger.warning(f"[重试] 任务 {task_id} 状态不是 WAITING_RETRY: {task.status}")
        else:
            logger.warning(f"[重试] 任务 {task_id} 不在内存中")
            # 尝试从数据库加载
            from ..models.database import WaitingRetryTask, SessionLocal
            db = SessionLocal()
            try:
                wt = db.query(WaitingRetryTask).filter(WaitingRetryTask.id == task_id).first()
                if wt:
                    logger.info(f"[重试] 从数据库找到任务: {wt.rjcode}")
                    # 创建任务并加入队列
                    task = Task(
                        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                        source_path=wt.subtitle_folder,
                        task_id=wt.id,
                        status=TaskStatus.PENDING,
                        rjcode=wt.rjcode
                    )
                    task.task_metadata = wt.task_metadata or {}
                    task.task_metadata['subtitle_folder'] = wt.subtitle_folder
                    task.task_metadata['work_title'] = wt.work_title
                    with task._set_state_silent():
                        task.current_step = "手动重试"
                    self._ensure_task_context(task)
                    self.tasks[task.id] = task
                    asyncio.create_task(self.queue.put(task))
                    task.mark_changed("submitted")
                    # 从等待重试表删除
                    db.delete(wt)
                    db.commit()
                    logger.info(f"[重试] 任务 {task_id} ({wt.rjcode}) 从数据库加载并加入队列")
                    return True
            except Exception as e:
                logger.error(f"[重试] 从数据库加载任务失败: {e}")
            finally:
                db.close()
        return False

    async def rerun_rj_subtitle_task(self, task_id: str, overrides: Optional[dict] = None) -> Task:
        """复用已有 RJ 字幕任务并重新入队，不创建新任务。"""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise ValueError("仅支持重跑 RJ 字幕任务")
        if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
            raise ValueError("任务正在执行中，不能重新提交")

        metadata = dict(task.task_metadata or {})
        overrides = dict(overrides or {})
        metadata.update({
            'force_rerun': True,
            'skip_if_existing_subtitles': False,
            'awaiting_manual_match': False,
            'manual_match_completed': False,
            'manual_match_applied_pairs': 0,
            'manual_match_deleted_subtitles': 0,
            'manual_match_completed_at': None,
            'subtitle_dir': '',
            'written_files': [],
            'skipped_files': [],
            'write_errors': [],
            'failed_files': [],
            'match_result': {},
            'download_files': [],
            'downloaded_count': 0,
            'progress_log': [],
        })
        if 'overwrite' in overrides:
            metadata['overwrite'] = bool(overrides.get('overwrite'))
        if 'enable_metadata_match' in overrides:
            metadata['enable_metadata_match'] = bool(overrides.get('enable_metadata_match'))
        if 'naming_strategy' in overrides:
            metadata['naming_strategy'] = str(overrides.get('naming_strategy') or metadata.get('naming_strategy') or 'audio').lower()
        if 'use_filter_rules' in overrides:
            metadata['use_filter_rules'] = bool(overrides.get('use_filter_rules'))
        if 'subtitle_filter_rules' in overrides:
            metadata['subtitle_filter_rules'] = overrides.get('subtitle_filter_rules') or []
        if 'ai_match_mode' in overrides:
            metadata['ai_match_mode'] = str(overrides.get('ai_match_mode') or 'rule_ai_auto').lower()
        if 'ai_confidence_threshold' in overrides:
            metadata['ai_confidence_threshold'] = overrides.get('ai_confidence_threshold')
        task.task_metadata = metadata
        self.processing.discard(task.id)
        if task.rjcode:
            self.unmark_rjcode_processing(task.rjcode)
        task.reset_for_rerun("等待重新抓取字幕")
        self._ensure_task_context(task)
        await self.queue.put(task)
        task.mark_changed("submitted")
        logger.info("RJ 字幕任务已重新入队: %s", task.id)
        return task

    def pause_task(self, task_id: str):
        """暂停任务"""
        if task_id in self.tasks:
            self.tasks[task_id].pause()
    
    def resume_task(self, task_id: str):
        """恢复任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            metadata = dict(task.task_metadata or {})
            if task.status in {TaskStatus.FAILED, TaskStatus.COMPLETED} and task.type in {TaskType.HTTP_DOWNLOAD, TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
                return
            if task.status == TaskStatus.PAUSED and task.type in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
                metadata.pop("pause_origin_status", None)
                task.task_metadata = metadata
                with task._set_state_silent():
                    task.status = TaskStatus.PENDING
                    task._pause_event.set()
                pending: list[Task] = []
                already_queued = False
                while True:
                    try:
                        queued_task = self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if queued_task.id == task.id:
                        already_queued = True
                    pending.append(queued_task)
                if task.id in self.processing:
                    already_queued = True
                if not already_queued:
                    pending.append(task)
                for queued_task in sorted(pending, key=self._task_queue_priority):
                    self.queue.put_nowait(queued_task)
                task.mark_changed("submitted")
                return
            if task.status == TaskStatus.PAUSED and metadata.get("pause_origin_status") == TaskStatus.PENDING.value:
                metadata.pop("pause_origin_status", None)
                task.task_metadata = metadata
                with task._set_state_silent():
                    task.status = TaskStatus.PENDING
                    task._pause_event.set()
                pending: list[Task] = []
                already_queued = False
                while True:
                    try:
                        queued_task = self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if queued_task.id == task.id:
                        already_queued = True
                    pending.append(queued_task)
                if not already_queued:
                    pending.append(task)
                for queued_task in sorted(pending, key=self._task_queue_priority):
                    self.queue.put_nowait(queued_task)
                task.mark_changed("submitted")
            else:
                metadata.pop("pause_origin_status", None)
                task.task_metadata = metadata
                task.resume()
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            should_log_immediately = task.status == TaskStatus.PENDING and task_id not in self.processing
            task.cancel()
            if task.type == TaskType.HTTP_DOWNLOAD:
                try:
                    from .http_download_service import get_http_download_service
                    asyncio.create_task(get_http_download_service().cancel_task(task_id))
                except Exception:
                    logger.debug("取消 HTTP 下载 aria2 任务失败: task_id=%s", task_id, exc_info=True)
            if task.type in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
                try:
                    from .baidu_netdisk_service import get_baidu_netdisk_service
                    asyncio.create_task(get_baidu_netdisk_service().cancel_task(task_id))
                except Exception:
                    logger.debug("取消百度网盘下载进程失败: task_id=%s", task_id, exc_info=True)
            if should_log_immediately:
                try:
                    from .activity_log_service import log_task_lifecycle_event

                    log_task_lifecycle_event(task)
                except Exception:
                    logger.warning("[操作记录] 取消未运行任务记录失败: task_id=%s", task_id, exc_info=True)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)

    def remove_task(self, task_id: str) -> bool:
        """移除已结束任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False

        if task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED]:
            raise RuntimeError("任务仍在执行中，不能清理")

        self.tasks.pop(task_id, None)
        self.processing.discard(task_id)
        if task.rjcode:
            self._processing_rjcodes.discard(task.rjcode)
        if task.type == TaskType.HTTP_DOWNLOAD:
            try:
                from .http_download_service import get_http_download_service
                asyncio.create_task(get_http_download_service().cancel_task(task_id))
            except Exception:
                logger.debug("清理 HTTP 下载 aria2 状态失败: task_id=%s", task_id, exc_info=True)
        if task.type in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
            try:
                from .baidu_netdisk_service import get_baidu_netdisk_service
                asyncio.create_task(get_baidu_netdisk_service().cancel_task(task_id))
            except Exception:
                logger.debug("清理百度网盘下载进程状态失败: task_id=%s", task_id, exc_info=True)
        self.delete_task_snapshot(task_id)
        return True
    
    def update_task_status(self, task_id: str, status: TaskStatus, message: Optional[str] = None):
        """更新任务状态"""
        task = self.tasks.get(task_id)
        if task:
            with task._set_state_silent():
                task.status = status
                if message:
                    task.current_step = message
                if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    task.completed_at = datetime.now()
                if status in {
                    TaskStatus.WAITING_MANUAL,
                    TaskStatus.WAITING_RETRY,
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.PAUSED,
                }:
                    self.processing.discard(task.id)
                    if task.rjcode:
                        self.unmark_rjcode_processing(task.rjcode)
            logger.info(f"任务 {task_id} 状态更新为: {status.value}")
            reason = {
                TaskStatus.COMPLETED: "completed",
                TaskStatus.FAILED: "failed",
                TaskStatus.CANCELLED: "cancelled",
            }.get(status, "status")
            task.mark_changed(reason)
            return True
        return False
    
    def get_all_tasks(self, include_hidden: bool = False) -> list[Task]:
        """获取所有任务，按创建时间倒序排列。默认隐藏已被后续成功覆盖的旧任务。"""
        for task in self.tasks.values():
            self._ensure_task_context(task)
        tasks = list(self.tasks.values())
        if not include_hidden:
            tasks = [t for t in tasks if not self._is_hidden_task(t)]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)
    
    def get_pending_tasks(self) -> list[Task]:
        """获取待处理任务，按创建时间倒序排列"""
        return sorted([t for t in self.tasks.values() if t.status == TaskStatus.PENDING], 
                     key=lambda t: t.created_at, reverse=True)
    
    def get_processing_tasks(self) -> list[Task]:
        """获取进行中任务，按创建时间倒序排列"""
        return sorted([t for t in self.tasks.values() if t.status == TaskStatus.PROCESSING], 
                     key=lambda t: t.created_at, reverse=True)
    
    def get_completed_tasks(self) -> list[Task]:
        """获取已完成任务，按创建时间倒序排列"""
        return sorted([t for t in self.tasks.values() if t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] and not self._is_hidden_task(t)],
                     key=lambda t: t.created_at, reverse=True)

    def _save_waiting_retry_task(self, task: Task, subtitle_folder: str, work_title: str, retry_reason: str, retry_after):
        """保存等待重试任务到数据库"""
        from ..models.database import WaitingRetryTask, SessionLocal
        from ..config.settings import get_config
        import uuid

        logger.info(f"[等待重试] 开始保存任务 {task.rjcode} 到数据库...")
        db = SessionLocal()
        try:
            # 检查是否已存在
            existing = db.query(WaitingRetryTask).filter(WaitingRetryTask.rjcode == task.rjcode).first()
            if existing:
                # 更新现有记录
                existing.retry_count = (existing.retry_count or 0) + 1
                existing.retry_reason = retry_reason
                existing.retry_after = retry_after
                existing.updated_at = datetime.now()
                existing.task_metadata = task.task_metadata
                logger.info(f"[等待重试] 更新任务 {task.rjcode}, 重试次数: {existing.retry_count}")
            else:
                # 创建新记录
                config = get_config()
                max_retry = config.asmr_sync.max_retry_count if hasattr(config, 'asmr_sync') else 10
                waiting_task = WaitingRetryTask(
                    id=str(uuid.uuid4()),
                    rjcode=task.rjcode,
                    subtitle_folder=subtitle_folder,
                    work_title=work_title,
                    retry_reason=retry_reason,
                    retry_count=1,
                    max_retry_count=max_retry,
                    retry_after=retry_after,
                    task_metadata=task.task_metadata
                )
                db.add(waiting_task)
                logger.info(f"[等待重试] 创建新任务记录 {task.rjcode}")
            db.commit()
            logger.info(f"[等待重试] 任务 {task.rjcode} 已提交到数据库")

            # 验证保存结果
            count = db.query(WaitingRetryTask).count()
            logger.info(f"[等待重试] 数据库中当前共有 {count} 条等待重试记录")
        except Exception as e:
            logger.error(f"[等待重试] 保存任务失败: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _remove_waiting_retry_task(self, rjcode: str):
        """从数据库删除等待重试任务"""
        from ..models.database import WaitingRetryTask, SessionLocal

        db = SessionLocal()
        try:
            db.query(WaitingRetryTask).filter(WaitingRetryTask.rjcode == rjcode).delete()
            db.commit()
            logger.info(f"[等待重试] 删除任务 {rjcode}")
        except Exception as e:
            logger.error(f"[等待重试] 删除任务失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _remove_waiting_retry_task_by_id(self, task_id: str):
        """从数据库删除等待重试任务（通过任务ID）"""
        from ..models.database import WaitingRetryTask, SessionLocal

        db = SessionLocal()
        try:
            db.query(WaitingRetryTask).filter(WaitingRetryTask.id == task_id).delete()
            db.commit()
            logger.info(f"[等待重试] 删除任务 ID: {task_id}")
        except Exception as e:
            logger.error(f"[等待重试] 删除任务失败: {e}")
            db.rollback()
        finally:
            db.close()

    def load_waiting_retry_tasks(self):
        """从数据库加载等待重试的任务"""
        from ..models.database import WaitingRetryTask, SessionLocal, get_db_path_info

        db_path = get_db_path_info()
        logger.info(f"[等待重试] 开始从数据库加载等待重试任务...")
        logger.info(f"[等待重试] 数据库路径: {db_path}")

        db = SessionLocal()
        try:
            waiting_tasks = db.query(WaitingRetryTask).all()
            logger.info(f"[等待重试] 数据库中找到 {len(waiting_tasks)} 条等待重试记录")

            loaded_count = 0
            for wt in waiting_tasks:
                # 检查是否已加载
                if wt.rjcode in [t.rjcode for t in self.tasks.values() if t.status == TaskStatus.WAITING_RETRY]:
                    logger.debug(f"[等待重试] 任务 {wt.rjcode} 已在内存中，跳过")
                    continue

                # 创建任务对象
                task = Task(
                    task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                    source_path=wt.subtitle_folder,
                    task_id=wt.id,
                    status=TaskStatus.WAITING_RETRY,
                    rjcode=wt.rjcode
                )
                task.task_metadata = wt.task_metadata or {}
                task.task_metadata['subtitle_folder'] = wt.subtitle_folder
                task.task_metadata['work_title'] = wt.work_title
                task.task_metadata['retry_reason'] = wt.retry_reason
                task.task_metadata['retry_count'] = wt.retry_count
                task.task_metadata['retry_after'] = wt.retry_after.isoformat() if wt.retry_after else None
                task.current_step = f"等待重试: {wt.retry_reason}"

                self.tasks[task.id] = task
                loaded_count += 1
                logger.info(f"[等待重试] 加载任务 {wt.rjcode}, 重试次数: {wt.retry_count}")

            logger.info(f"[等待重试] 共加载 {loaded_count} 个等待重试任务")
            return loaded_count
        except Exception as e:
            logger.error(f"[等待重试] 加载任务失败: {e}", exc_info=True)
            return 0
        finally:
            db.close()

    def get_waiting_retry_tasks_from_db(self):
        """从数据库获取等待重试任务列表（用于API返回）"""
        from ..models.database import WaitingRetryTask, SessionLocal

        db = SessionLocal()
        try:
            waiting_tasks = db.query(WaitingRetryTask).all()
            return [wt.to_dict() for wt in waiting_tasks]
        except Exception as e:
            logger.error(f"[等待重试] 获取任务列表失败: {e}")
            return []
        finally:
            db.close()
    
    def _extract_rjcode(self, path: str, search_subfolders: bool = True) -> Optional[str]:
        """从路径中提取 RJ 号
            
        支持格式：
        - RJ123456, RJ12345678
        - VJ123456, BJ123456
        - 纯数字目录名：01503161 -> RJ01503161
        - 带前缀的数字：39.RJ01570159 -> RJ01570159
        - 支持从嵌套路径中提取 RJ 号（会搜索整个路径字符串）
        - 支持递归搜索子目录（当直接提取失败时）
        
        Args:
            path: 要提取的路径
            search_subfolders: 是否递归搜索子目录（默认 True）
        """
        import re
        path = str(path or "")
        if not path:
            return None
            
        # 优先匹配标准格式 [RVB]J + 6/8 位数字（搜索整个路径）
        pattern = r'[RVB]J(\d{8}|\d{6})(?!\d)'
        match = re.search(pattern, path, re.IGNORECASE)
        if match:
            return match.group(0).upper()
            
        # 尝试从路径最后的目录/文件名中提取纯数字
        # 例如：E:\path\01503161 -> RJ01503161
        path_parts = re.split(r'[\\/]', path)
        if path_parts:
            last_part = path_parts[-1]
            # 移除常见前缀如 "39." 等
            clean_name = re.sub(r'^\d+\.', '', last_part)
            # 匹配 6 位或 8 位纯数字
            num_match = re.match(r'^(\d{8}|\d{6})$', clean_name)
            if num_match:
                num = num_match.group(1)
                return f"RJ{num}"
        
        # 如果直接提取失败，且允许搜索子目录
        if search_subfolders and os.path.isdir(path):
            logger.debug(f"从当前路径无法提取 RJ 号，尝试搜索子目录：{path}")
            try:
                # 遍历直接子目录
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    
                    # 优先检查文件夹（递归深入搜索）
                    if os.path.isdir(item_path):
                        # 尝试从子文件夹名提取（继续递归搜索子目录）
                        sub_rjcode = self._extract_rjcode(item_path, search_subfolders=True)
                        if sub_rjcode:
                            logger.debug(f"从子目录找到 RJ 号：{sub_rjcode} (路径：{item_path})")
                            return sub_rjcode
                    
                    # 其次检查文件（特别是压缩包）
                    elif os.path.isfile(item_path):
                        # 尝试从文件名提取
                        file_rjcode = self._extract_rjcode(item_path, search_subfolders=False)
                        if file_rjcode:
                            logger.debug(f"从子文件找到 RJ 号：{file_rjcode} (路径：{item_path})")
                            return file_rjcode
            except Exception as e:
                logger.warning(f"搜索子目录失败：{e}")
            
        return None

    def _detect_multi_rj_subfolders(
        self,
        root_path: str,
        max_scan_depth: int = 4,
    ) -> List[Dict[str, str]]:
        """检测解压后临时根目录下是否存在多个独立的 RJ 顶层子作品。

        典型场景：压缩包里是「社团/RJ 作品/...」二级以上结构（按社团分类的合集包）。
        返回结构 ``[{"rjcode": "RJxxxx", "path": "/abs/path"}, ...]``：
        - 一旦某层目录被识别为 RJ 作品目录（自身或直接子项含 RJ 号），
          就把该目录整体当成一个独立 RJ，不再继续向其内部递归。
        - 同一 RJ 号只保留最浅一层匹配，避免嵌套重复识别。
        - 仅当返回 >=2 个结果时才视为「多作品包」，调用方再决定是否拆分。
        - ``max_scan_depth`` 限制扫描层数，防止异常深嵌套时耗时过长。
        """
        import re

        try:
            if not root_path or not os.path.isdir(root_path):
                return []
        except Exception:
            return []

        rj_pattern = re.compile(r'[RVB]J(\d{8}|\d{6})(?!\d)', re.IGNORECASE)

        def _match_rj(name: str) -> Optional[str]:
            text = str(name or "")
            if not text:
                return None
            match = rj_pattern.search(text)
            if match:
                return match.group(0).upper()
            # 兼容纯数字目录名 / 带前缀，例如 39.RJ01570159、01503161
            base = re.sub(r'^\d+\.', '', text)
            num_match = re.match(r'^(\d{8}|\d{6})$', base)
            if num_match:
                return f"RJ{num_match.group(1)}"
            return None

        def _distinct_children_rjs(directory: str, max_children: int = 400) -> set:
            """该目录直接子项的名字里出现的不同 RJ 集合。

            这里不能像之前那样「找到一个 RJ 就返回」——社团目录下会同时有多个
            RJ 子作品，那种场景必须能识别出 >=2 个 RJ 才能正确决定向内深入扫描，
            而不是把整个社团目录错认成单作品的壳。
            """
            try:
                entries = list(os.listdir(directory))[:max_children]
            except OSError:
                return set()
            collected: set = set()
            for name in entries:
                rj = _match_rj(name)
                if rj:
                    collected.add(rj)
            return collected

        discovered: Dict[str, Dict[str, str]] = {}

        def _walk(current: str, depth: int) -> None:
            if depth > max_scan_depth:
                return
            try:
                entries = list(os.scandir(current))
            except OSError:
                return
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                name = entry.name
                # 常见无关目录直接跳过
                if name.startswith('.') or name.lower() in {"__macosx", "_conflicts", "subtitles"}:
                    continue
                child_path = entry.path
                # 1) 目录名直接含 RJ → 该目录就是 RJ 作品根目录，不再深入
                rj_in_name = _match_rj(name)
                if rj_in_name:
                    if rj_in_name not in discovered:
                        discovered[rj_in_name] = {
                            "rjcode": rj_in_name,
                            "path": os.path.abspath(child_path),
                            "match_kind": "name",
                        }
                    continue
                # 2) 目录名不含 RJ，看其直接子项里能定位多少个不同 RJ：
                #    - 恰好 1 个 → 视为单作品壳目录（典型如 [社团][RJxxx]/雪荷風ノ宿/ ）
                #    - 多于 1 个 → 视为社团 / 合集容器，向内继续深入扫描每个 RJ 子作品
                #    - 0 个 → 继续深入，期待更深层的 RJ
                child_rj_set = _distinct_children_rjs(child_path)
                if len(child_rj_set) == 1:
                    only_rj = next(iter(child_rj_set))
                    if only_rj not in discovered:
                        discovered[only_rj] = {
                            "rjcode": only_rj,
                            "path": os.path.abspath(child_path),
                            "match_kind": "children",
                        }
                    continue
                # 否则继续向下扫描，期待找到更深层的 RJ
                _walk(child_path, depth + 1)

        _walk(root_path, depth=1)

        results = list(discovered.values())
        if len(results) < 2:
            return []

        # 稳定顺序：按路径字符串排序，便于日志和测试可重复
        results.sort(key=lambda item: item.get("path") or "")
        return results

    async def _dispatch_multi_rj_subtasks(
        self,
        parent_task: Task,
        extracted_path: str,
        multi_rj_dirs: List[Dict[str, str]],
    ) -> List[str]:
        """把每个 RJ 子目录从父任务的临时根目录搬到独立位置，并创建子任务入队。

        返回成功派发的子任务 ID 列表。任何子目录派发失败都不会中止整体流程，
        而是写到父任务 metadata 的 ``multi_rj_dispatch_failures`` 中由通知体现。
        """
        from ..config.settings import get_config

        config = get_config()
        try:
            temp_root = str(getattr(getattr(config, "storage", None), "temp_path", "") or "").strip()
        except Exception:
            temp_root = ""
        if not temp_root or not os.path.isdir(temp_root):
            # 临时目录不可用就不强行搬运，回退到原流程
            logger.warning(
                "[多作品拆分] 任务 %s 临时根目录不可用，跳过拆分: temp_root=%s",
                parent_task.id, temp_root,
            )
            return []

        parent_metadata = dict(parent_task.task_metadata or {})
        target_library_id = parent_metadata.get("target_library_id")
        # 父任务的来源标签，给子任务通知用
        parent_source_label = parent_metadata.get("source_label") or os.path.basename(
            str(parent_task.source_path or "").rstrip("\\/")
        )

        # 让父任务和后续派发的所有子任务共享通知聚合键：
        # 没有这个，task_notification_service 的 _resolve_group_key 会给每个子任务回落到
        # group_type='task' 并立刻为每个 waiting_manual 写一封邮件，
        # 一个合集包能瞬间炸出 N 封通知 + N 套 inbox / outbox 写库，
        # 把数据库写入、ThreadPoolExecutor、QQ SMTP 同时打爆，
        # 表现为问题作品列表接口超时、铃铛刷一长串。
        # 共享 group key 后，所有兄弟任务全部到终态时 _is_group_terminal=True，
        # 由 aggregate_import_batch_extras 合并出一封多 RJ 卡片的批量邮件。
        notification_group_key = str(
            parent_metadata.get("notification_group_key") or parent_task.id
        )
        notification_batch_id = str(
            parent_metadata.get("batch_id") or parent_task.id
        )
        parent_metadata.setdefault("notification_group_key", notification_group_key)
        parent_metadata.setdefault("batch_id", notification_batch_id)
        parent_task.task_metadata = parent_metadata

        subtask_ids: List[str] = []
        dispatched_records: List[Dict[str, Any]] = []
        dispatch_failures: List[Dict[str, str]] = []

        for index, entry in enumerate(multi_rj_dirs):
            sub_rj = str(entry.get("rjcode") or "").strip().upper()
            sub_src = str(entry.get("path") or "").strip()
            if not sub_rj or not sub_src or not os.path.isdir(sub_src):
                dispatch_failures.append({
                    "rjcode": sub_rj or "未知",
                    "path": sub_src,
                    "error": "源目录不存在或无 RJ 号",
                })
                continue

            try:
                # 给每个子任务一个独立的临时容器目录，避免与父任务清理路径冲突
                holder = await asyncio.to_thread(
                    tempfile.mkdtemp,
                    prefix=f"{sub_rj}_subtask_{parent_task.id[:8]}_",
                    dir=temp_root,
                )
                target_path = os.path.join(holder, os.path.basename(sub_src.rstrip("\\/")))
                # 同步搬运目录（数据较大时阻塞，但已经在线程里）
                await asyncio.to_thread(shutil.move, sub_src, target_path)
            except Exception as exc:
                logger.error(
                    "[多作品拆分] 移动 RJ 子目录失败: parent=%s rj=%s src=%s err=%s",
                    parent_task.id, sub_rj, sub_src, exc,
                )
                dispatch_failures.append({
                    "rjcode": sub_rj,
                    "path": sub_src,
                    "error": f"移动失败: {exc}",
                })
                continue

            # 构造子任务 metadata，复用 PROCESS_EXISTING_FOLDER 流程
            child_metadata: Dict[str, Any] = {
                "rjcode": sub_rj,
                "inferred_rjcode": sub_rj,
                "rjcode_source": "multi_rj_archive_split",
                "rjcode_lock": True,  # 锁定 RJ，避免在子任务中再次推断
                "is_extract_subtask": True,
                "extract_subtask_temp_holder": holder,
                "extract_subtask_match_kind": entry.get("match_kind") or "name",
                "parent_task_id": parent_task.id,
                "parent_archive_path": parent_task.source_path,
                "parent_archive_label": parent_source_label,
                "source_action": "multi_rj_extract_subtask",
                "source_label": f"{parent_source_label} → {sub_rj}",
                "source_page": parent_metadata.get("source_page") or "tasks",
                "queue_priority": parent_metadata.get("queue_priority") or 50,
                # 共享通知聚合键 → 同一合集包派出的所有兄弟子任务和父任务共用
                # 一个 group_key + group_run_id，由 task_notification_service 自动归并成
                # 一封批量邮件，避免 N 个 waiting_manual 各自轰炸 SMTP / inbox。
                "notification_group_key": notification_group_key,
                "batch_id": notification_batch_id,
                "parent_session_id": notification_group_key,
            }
            if target_library_id:
                child_metadata["target_library_id"] = target_library_id

            child_task = Task(
                task_type=TaskType.PROCESS_EXISTING_FOLDER,
                source_path=target_path,
                auto_classify=parent_task.auto_classify,
                metadata=child_metadata,
                rjcode=sub_rj,
            )
            try:
                child_task_id = await self.submit(child_task)
            except Exception as exc:
                logger.error(
                    "[多作品拆分] 子任务入队失败: parent=%s rj=%s err=%s",
                    parent_task.id, sub_rj, exc,
                )
                dispatch_failures.append({
                    "rjcode": sub_rj,
                    "path": target_path,
                    "error": f"子任务入队失败: {exc}",
                })
                # 入队失败也别留临时目录残骸
                try:
                    await asyncio.to_thread(shutil.rmtree, holder, ignore_errors=True)
                except Exception:
                    pass
                continue

            subtask_ids.append(child_task_id)
            dispatched_records.append({
                "rjcode": sub_rj,
                "task_id": child_task_id,
                "source_path": target_path,
                "match_kind": entry.get("match_kind") or "name",
            })
            logger.info(
                "[多作品拆分] 已派发子任务: parent=%s rj=%s task=%s path=%s",
                parent_task.id, sub_rj, child_task_id[:8], target_path,
            )

        # 把派发结果写回父任务 metadata，便于通知 / 历史展示
        parent_task.task_metadata = {
            **(parent_task.task_metadata or {}),
            "multi_rj_dispatched": True,
            "multi_rj_subtask_ids": subtask_ids,
            "multi_rj_subtask_count": len(subtask_ids),
            "multi_rj_dispatch_records": dispatched_records,
            "multi_rj_dispatch_failures": dispatch_failures,
        }
        return subtask_ids

    async def _cleanup_failed_task(self, task: Task):
        """清理失败任务产生的临时文件"""
        from ..config.settings import get_config
        
        config = get_config()
        cleaned_paths = []

        if task.type == TaskType.HTTP_DOWNLOAD:
            logger.info("HTTP 下载任务失败/部分成功不清理下载根目录: %s", task.output_path)
            return
        
        # 对于 PROCESS_EXISTING_FOLDER 类型，成功完成的任务不需要清理
        # 因为文件夹是直接从已有目录处理的，不是临时文件
        if task.type == TaskType.PROCESS_EXISTING_FOLDER:
            # 多作品包派发出来的子任务例外：source_path 是父任务从临时目录搬过来的
            # 容器路径，无论成功失败都必须把对应 holder 清掉，否则会留下临时残骸。
            metadata = task.task_metadata or {}
            if metadata.get("is_extract_subtask"):
                holder = str(metadata.get("extract_subtask_temp_holder") or "").strip()
                if holder and os.path.isdir(holder):
                    source_in_holder = False
                    try:
                        holder_abs = os.path.abspath(holder)
                        source_abs = os.path.abspath(str(task.source_path or ""))
                        source_in_holder = (
                            os.path.exists(source_abs)
                            and os.path.commonpath([holder_abs, source_abs]) == holder_abs
                        )
                    except ValueError:
                        source_in_holder = False
                    except Exception:
                        logger.warning(
                            "[多作品拆分] 判断子任务临时容器是否仍在使用失败: task_id=%s holder=%s",
                            task.id,
                            holder,
                            exc_info=True,
                        )
                        return
                    if task.status == TaskStatus.WAITING_MANUAL and source_in_holder:
                        logger.warning(
                            "[多作品拆分] 子任务等待人工处理，跳过清理仍在使用的临时容器: task_id=%s holder=%s source=%s",
                            task.id,
                            holder,
                            task.source_path,
                        )
                        return
                    try:
                        await asyncio.to_thread(shutil.rmtree, holder, ignore_errors=True)
                        logger.info(
                            "[多作品拆分] 清理子任务临时容器: task_id=%s holder=%s",
                            task.id, holder,
                        )
                    except Exception:
                        logger.warning(
                            "[多作品拆分] 清理子任务临时容器失败: task_id=%s holder=%s",
                            task.id, holder, exc_info=True,
                        )
                return
            if task.status == TaskStatus.COMPLETED:
                # 成功完成的已有文件夹处理任务，不需要清理任何文件
                logger.info(f"已有文件夹处理任务成功完成，跳过清理: {task.source_path}")
                return
            # 失败的已有文件夹处理任务，只清理可能创建的临时文件
            # 不清理 source_path 或 output_path，因为那是用户的原始文件
            logger.info(f"已有文件夹处理任务失败，跳过清理原始文件: {task.source_path}")
            return
        
        # 1. 清理 output_path（如果已设置）- 只针对失败的任务
        if task.status == TaskStatus.FAILED and task.output_path and os.path.exists(task.output_path):
            try:
                await asyncio.to_thread(shutil.rmtree, task.output_path)
                cleaned_paths.append(task.output_path)
                logger.info(f"清理失败任务缓存: {task.output_path}")
            except Exception as e:
                logger.warning(f"清理失败任务缓存失败: {task.output_path}, {e}")
        
        # 2. 如果是自动处理流程，检查并清理temp目录下所有可能的残留
        if task.type == TaskType.AUTO_PROCESS and task.source_path:
            source_name = Path(task.source_path).stem
            temp_path = config.storage.temp_path
            
            # 检查更多可能的目录名（包括带序号的后缀）
            possible_names = [
                source_name,
                f"{source_name}_1",
                f"{source_name}_2",
                f"{source_name}_3",
                f"{source_name}_temp",
            ]
            
            for name in possible_names:
                path = os.path.join(temp_path, name)
                if os.path.exists(path) and path not in cleaned_paths:
                    try:
                        await asyncio.to_thread(shutil.rmtree, path)
                        cleaned_paths.append(path)
                        logger.info(f"清理残留目录: {path}")
                    except Exception as e:
                        logger.warning(f"清理残留目录失败: {path}, {e}")
        
        # 3. 如果任务状态是 failed，且是解压步骤失败，额外检查
        if task.status == TaskStatus.FAILED and task.source_path:
            # 检查是否有错误信息提示是解压失败
            if task.error_message and ("解压" in task.error_message or "密码" in task.error_message):
                source_name = Path(task.source_path).stem
                temp_path = config.storage.temp_path
                potential_path = os.path.join(temp_path, source_name)
                
                if os.path.exists(potential_path) and potential_path not in cleaned_paths:
                    try:
                        await asyncio.to_thread(shutil.rmtree, potential_path)
                        logger.info(f"清理解压失败残留: {potential_path}")
                    except Exception as e:
                        logger.warning(f"清理解压失败残留失败: {potential_path}, {e}")

    async def _move_file_with_retry(
        self,
        source_path: str,
        dest_path: str,
        attempts: int = 5,
        delay_seconds: float = 1.0,
        progress_cb=None,
    ):
        """带重试地移动文件。

        - 缓解 Windows 下解压后句柄释放延迟导致的占用问题
        - 跨卷场景使用 fs_utils.move_path_efficient 走 8 MB buffer 流式复制 +
          ``progress_cb(copied, total)`` 实时上报，避免归档大文件时进度卡 95% 不动
        """
        from .fs_utils import move_path_efficient

        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                await move_path_efficient(
                    source_path,
                    dest_path,
                    progress_cb=progress_cb,
                )
                return
            except FileNotFoundError:
                raise
            except PermissionError as exc:
                last_error = exc
                logger.warning(
                    f"移动文件时仍被占用，稍后重试 ({attempt}/{attempts}): {source_path} -> {dest_path}, {exc}"
                )
            except OSError as exc:
                last_error = exc
                logger.warning(
                    f"移动文件失败，稍后重试 ({attempt}/{attempts}): {source_path} -> {dest_path}, {exc}"
                )

            if attempt < attempts:
                await asyncio.sleep(delay_seconds)

        if last_error:
            raise last_error

    async def _cleanup_empty_source_dir(self, source_dir: str, protected_paths: Optional[list[str]] = None):
        """归档完成后清理空源目录，并向上递归清理所有空父目录。

        例如：待处理\\社团\\RJ号\\A.zip 处理后，依次尝试删除 RJ号\\ → 社团\\ →
        直到遇到受保护路径（input_path 等）或非空目录为止。
        """
        normalized_source = os.path.abspath(str(source_dir or ""))
        if not normalized_source or not os.path.isdir(normalized_source):
            return

        protected = {
            os.path.abspath(path)
            for path in (protected_paths or [])
            if path
        }
        if normalized_source in protected:
            return

        # 删除当前目录（带重试，防止 AV 工具短暂占用）
        deleted = False
        for attempt in range(1, 6):
            try:
                if os.listdir(normalized_source):
                    logger.info(f"源目录非空，跳过自动删除: {normalized_source}")
                    return
                os.rmdir(normalized_source)
                logger.info(f"已自动清理空源目录: {normalized_source}")
                deleted = True
                break
            except FileNotFoundError:
                deleted = True  # 已被其他任务删除，视为成功
                break
            except PermissionError as exc:
                logger.warning(f"删除空源目录时仍被占用，稍后重试 ({attempt}/5): {normalized_source}, {exc}")
            except OSError as exc:
                logger.warning(f"删除空源目录失败，稍后重试 ({attempt}/5): {normalized_source}, {exc}")

            if attempt < 5:
                await asyncio.sleep(1)

        if not deleted:
            return

        # 向上递归清理空父目录（单次尝试，不重试）
        current = os.path.dirname(normalized_source)
        while current:
            parent = os.path.dirname(current)
            if parent == current:
                break  # 已到文件系统根，防止死循环
            if not os.path.isdir(current):
                break
            if current in protected:
                break
            try:
                if os.listdir(current):
                    break  # 非空，停止向上清理
                os.rmdir(current)
                logger.info(f"已自动清理空父目录: {current}")
                current = parent
            except (FileNotFoundError, PermissionError, OSError) as exc:
                logger.debug(f"清理空父目录停止: {current}, {exc}")
                break

    async def _archive_source_file(self, task: Task):
        """将源压缩包移动到已处理目录并记录"""
        import shutil
        import uuid
        import os
        import re
        from datetime import datetime
        from ..config.settings import get_config
        from ..models.database import ProcessedArchive, get_db

        config = get_config()
        source_path = task.source_path
        processed_dir = config.storage.processed_archives_path

        # 检查是否需要跳过归档（重新解压的情况）
        if task.skip_archive:
            logger.info(f"任务标记为跳过归档，更新处理记录: {source_path}")
            # 只更新数据库中的处理次数和时间
            filename = os.path.basename(source_path)
            
            db = next(get_db())
            try:
                # 尝试通过文件名查找记录
                existing_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                
                logger.info(f"查找记录 - 文件名: {filename}, 找到: {existing_record is not None}")
                
                # 如果通过文件名找不到，尝试通过当前路径查找
                if not existing_record:
                    # 尝试多种路径匹配方式
                    existing_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.current_path == source_path
                    ).first()
                    logger.info(f"通过完整路径查找: {source_path}, 找到: {existing_record is not None}")
                    
                    # 如果还找不到，尝试通过文件名模糊匹配
                    if not existing_record:
                        all_records = db.query(ProcessedArchive).filter(
                            ProcessedArchive.filename.like(f'%{filename}%')
                        ).all()
                        logger.info(f"模糊查找 {filename}，找到 {len(all_records)} 条记录")
                        if len(all_records) == 1:
                            existing_record = all_records[0]
                            logger.info(f"使用模糊匹配的记录: {existing_record.filename}")
                
                if existing_record:
                    old_count = existing_record.process_count or 0
                    old_status = existing_record.status
                    logger.info(f"更新记录前 - ID: {existing_record.id}, 旧次数: {old_count}, 旧状态: {old_status}")
                    
                    existing_record.process_count = old_count + 1
                    existing_record.processed_at = datetime.now()
                    existing_record.status = 'completed'
                    existing_record.volume_count = len(get_archive_volume_paths(source_path))
                    db.commit()
                    try:
                        from .task_center_event_service import broadcast_processed_archive_changed
                        broadcast_processed_archive_changed(existing_record)
                    except Exception:
                        logger.debug("广播归档更新事件失败", exc_info=True)
                    
                    # 重新查询验证更新
                    db.expire_all()
                    verified = db.query(ProcessedArchive).filter(
                        ProcessedArchive.id == existing_record.id
                    ).first()
                    logger.info(f"更新记录后 - 新次数: {verified.process_count}, 新状态: {verified.status}")
                else:
                    logger.error(f"未找到归档记录: {filename}，无法更新状态")
                    # 列出所有记录帮助调试
                    all_files = db.query(ProcessedArchive.filename).all()
                    logger.info(f"数据库中所有文件名: {[f[0] for f in all_files[:10]]}")
            except Exception as e:
                logger.error(f"更新处理记录失败: {e}", exc_info=True)
                try:
                    db.rollback()
                except:
                    pass
            finally:
                db.close()
            return

        # 检查源文件是否存在
        if not os.path.exists(source_path):
            logger.warning(f"源文件不存在，无法归档: {source_path}")
            return

        # 检测是否是分卷压缩包，如果是则获取所有分卷文件。
        files_to_archive = get_archive_volume_paths(source_path)
        source_dir = os.path.dirname(source_path)
        filename = os.path.basename(source_path)

        logger.info(f"[Archive] 开始归档检测 - source_path: {source_path}")
        logger.info(f"[Archive] source_dir: {source_dir}, filename: {filename}")

        # 按"首卷优先"排序：让 archived_files[0] 是分卷组首卷，
        # 后面写 ProcessedArchive 时用首卷文件名作为唯一 key，避免同组多卷产生多条记录。
        files_to_archive = sort_archive_volumes(files_to_archive)
        if len(files_to_archive) > 1:
            logger.info(
                f"[Archive] 检测到分卷压缩包，共 {len(files_to_archive)} 个文件: "
                f"{[os.path.basename(f) for f in files_to_archive]}"
            )
        
        # 移动所有文件
        archived_files = []

        try:
            # 确保已处理目录存在
            os.makedirs(processed_dir, exist_ok=True)

            # 计算所有待归档文件总大小，用于跨卷复制时计算总进度（多分卷场景）
            total_archive_bytes = 0
            for fp in files_to_archive:
                try:
                    total_archive_bytes += os.path.getsize(fp)
                except OSError:
                    pass
            archived_bytes_so_far = [0]  # mutable closure，用于跨文件累计

            # 移动所有分卷文件（或单个文件）
            for index, file_path in enumerate(files_to_archive):
                filename = os.path.basename(file_path)
                dest_path = os.path.join(processed_dir, filename)
                
                # 处理重名
                counter = 1
                original_dest = dest_path
                while os.path.exists(dest_path):
                    name, ext = os.path.splitext(filename)
                    dest_path = os.path.join(processed_dir, f"{name}({counter}){ext}")
                    counter += 1

                file_size = 0
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    pass

                # 跨卷归档时把"已复制字节数"实时映射到 95~99 进度区间，
                # 让前端能看到归档大文件的实际进度，避免长时间停在 95%。
                def _make_progress_cb(captured_filename, captured_size):
                    base = archived_bytes_so_far[0]
                    grand_total = total_archive_bytes if total_archive_bytes > 0 else captured_size or 1

                    def _on_progress(copied: int, _total: int) -> None:
                        try:
                            global_copied = base + copied
                            ratio = min(1.0, max(0.0, global_copied / max(1, grand_total)))
                            # 95~99：archive 阶段固定占 95~99 进度，留 100% 给 complete
                            progress_value = 95 + int(ratio * 4)
                            mb_done = global_copied / (1024 * 1024)
                            mb_total = grand_total / (1024 * 1024)
                            task.update_progress(
                                progress_value,
                                f"归档压缩包 {mb_done:.0f}/{mb_total:.0f}MB ({captured_filename})",
                            )
                        except Exception:
                            logger.debug("归档进度回调异常已忽略", exc_info=True)

                    return _on_progress

                # 移动文件，允许在 7z 刚退出时等待句柄释放
                await self._move_file_with_retry(
                    file_path,
                    dest_path,
                    progress_cb=_make_progress_cb(filename, file_size),
                )
                archived_bytes_so_far[0] += file_size
                logger.info(f"压缩包已归档: {file_path} -> {dest_path}")
                archived_files.append((filename, dest_path, file_path))

            # 记录主文件（第一个分卷或唯一文件）到数据库
            if archived_files:
                main_filename, main_dest_path, main_source_path = archived_files[0]
                rjcode = self._extract_rjcode_from_path_tail(main_source_path) or str((task.task_metadata or {}).get('inferred_rjcode') or '').strip().upper()
                archived_paths = [item[1] for item in archived_files]
                volume_count = max(1, len(archived_paths))
                file_size = 0
                for archived_path in archived_paths:
                    try:
                        file_size += os.path.getsize(archived_path)
                    except OSError:
                        pass
                if file_size <= 0:
                    file_size = get_archive_total_size(main_dest_path)

                db = next(get_db())
                try:
                    # 查找是否已存在相同文件名的记录
                    existing_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == main_filename
                    ).first()
                    
                    if existing_record:
                        # 更新已有记录
                        existing_record.current_path = main_dest_path
                        existing_record.file_size = file_size
                        existing_record.volume_count = volume_count
                        existing_record.processed_at = datetime.now()
                        existing_record.process_count = (existing_record.process_count or 1) + 1
                        existing_record.task_id = task.id
                        existing_record.status = 'completed'
                        logger.info(f"更新压缩包归档记录: {main_filename}，处理次数: {existing_record.process_count}")
                    else:
                        # 创建新记录
                        from datetime import datetime
                        now = datetime.now()
                        archive_record = ProcessedArchive(
                            id=str(uuid.uuid4()),
                            original_path=main_source_path,
                            current_path=main_dest_path,
                            filename=main_filename,
                            rjcode=rjcode or '',
                            file_size=file_size,
                            volume_count=volume_count,
                            processed_at=now,  # 显式设置处理时间
                            process_count=1,
                            task_id=task.id,
                            status='completed'
                        )
                        db.add(archive_record)
                        logger.info(f"已记录压缩包归档信息: {main_filename}, 时间: {now}")
                    
                    db.commit()
                    changed_archive = existing_record or archive_record
                    try:
                        from .task_center_event_service import broadcast_processed_archive_changed
                        broadcast_processed_archive_changed(changed_archive)
                    except Exception:
                        logger.debug("广播归档更新事件失败", exc_info=True)
                except Exception as e:
                    logger.error(f"记录压缩包归档信息失败: {e}")
                    db.rollback()
                finally:
                    db.close()

            await self._cleanup_empty_source_dir(
                source_dir,
                protected_paths=[
                    getattr(config.storage, 'input_path', ''),
                    processed_dir,
                    getattr(config.storage, 'temp_path', ''),
                    getattr(config.storage, 'library_path', ''),
                    getattr(config.storage, 'existing_folders_path', ''),
                ],
            )

        except Exception as e:
            logger.error(f"归档压缩包失败: {e}")

    def _sort_volumes_for_archive(self, files: List[str]) -> List[str]:
        """归档时把分卷文件按"首卷优先"排序。

        排序约定（数字越小越靠前，即越靠近"首卷"）：
        - 0/1: .partN.ext / .partN  -> 按 N 升序，.part1 必然最小
        - 2:   .7z.NNN              -> 按 NNN 升序，.001 在最前
        - 3:   .exe 主卷             -> 在 .eNN 之前
        - 4:   .eNN                 -> 按 N 升序
        - 5:   .zip 主卷             -> 在 .zXX 之前
        - 6:   .zXX                 -> 按 N 升序
        - 7:   .rar 主卷             -> 在 .rXX 之前
        - 8:   .rXX                 -> 按 N 升序
        - 9:   其他单文件 / 未知格式

        排序结果保证 list[0] 是分卷组首卷，后续写 ProcessedArchive 记录时
        以 list[0] 的文件名为主键，可避免同组多卷各产生一条独立记录。
        """

        def key(path: str) -> Tuple[int, int, str]:
            name = os.path.basename(path).lower()

            m = re.search(r'\.part(\d+)\.(rar|zip|7z|exe)$', name, re.IGNORECASE)
            if m:
                return (0, int(m.group(1)), name)

            m = re.search(r'\.part(\d+)$', name, re.IGNORECASE)
            if m:
                return (1, int(m.group(1)), name)

            m = re.search(r'\.7z\.(\d{3})$', name, re.IGNORECASE)
            if m:
                return (2, int(m.group(1)), name)

            if name.endswith('.exe'):
                return (3, 0, name)

            m = re.search(r'\.e(\d{2})$', name, re.IGNORECASE)
            if m:
                return (4, int(m.group(1)), name)

            if name.endswith('.zip'):
                return (5, 0, name)

            m = re.search(r'\.z(\d{2})$', name, re.IGNORECASE)
            if m:
                return (6, int(m.group(1)), name)

            if name.endswith('.rar'):
                return (7, 0, name)

            m = re.search(r'\.r(\d{2})$', name, re.IGNORECASE)
            if m:
                return (8, int(m.group(1)), name)

            return (9, 0, name)

        return sorted(files, key=key)

    async def _process_asmr_sync_download(self, task: Task):
        """
        处理 ASMR 同步下载任务

        task.task_metadata 应包含:
        - rjcode: RJ号
        - subtitle_folder: 字幕文件夹路径
        - work_title: 作品标题（可选）
        """
        from .asmr_download_service import get_asmr_download_service
        from .subtitle_sync_service import get_subtitle_sync_service
        from .rename_service import RenameService
        from .classifier import SmartClassifier
        from ..config.settings import get_config

        config = get_config()
        asmr_service = get_asmr_download_service()
        subtitle_service = get_subtitle_sync_service()
        rename_service = RenameService()
        classifier = SmartClassifier()

        rjcode = task.task_metadata.get('rjcode', '')
        subtitle_folder = task.task_metadata.get('subtitle_folder', '')
        work_title = task.task_metadata.get('work_title', '')
        written_count = 0
        source_action = str(task.task_metadata.get('source_action') or '').strip()
        is_reimport_task = source_action in {'reimport_local_download_root', 'reimport_downloaded_session'}

        def append_progress_log(*args, **kwargs):
            return None

        logger.info(f"[{rjcode}] 开始{'直接入库' if is_reimport_task else 'ASMR 同步下载'}任务")

        try:
            if str(task.task_metadata.get('download_mode') or '').strip().lower() == 'enhanced':
                from .asmr_resource_service import get_asmr_resource_service

                task.update_progress(3, "准备直接入库任务" if is_reimport_task else "准备增强下载任务")
                await get_asmr_resource_service().process_download_task(task)
                if task.status == TaskStatus.PROCESSING:
                    task.complete()
                logger.info(f"[{rjcode}] {'直接入库' if is_reimport_task else 'ASMR 增强下载'}任务完成")
                return

            # 步骤1: 创建下载目录
            task.update_progress(5, "准备下载目录")
            temp_path = config.storage.temp_path
            download_dir = os.path.join(temp_path, f"{rjcode}_asmr_sync")
            os.makedirs(download_dir, exist_ok=True)

            # 步骤2: 获取作品信息和下载文件
            task.update_progress(10, "获取作品信息")

            def progress_callback(rj, current, total, step):
                progress = 10 + int((current / total) * 60) if total > 0 else 10
                task.update_progress(progress, step)

            # 获取筛选规则
            filter_rules = config.filter.rules
            logger.info(f"[ASMR同步] 筛选规则数量: {len(filter_rules)}")
            for i, rule in enumerate(filter_rules):
                if isinstance(rule, dict):
                    logger.info(f"[ASMR同步] 规则{i+1}: name={rule.get('name')}, enabled={rule.get('enabled')}, pattern={rule.get('pattern')}")
                else:
                    logger.info(f"[ASMR同步] 规则{i+1}: name={getattr(rule, 'name', '未知')}, enabled={getattr(rule, 'enabled', True)}, pattern={getattr(rule, 'pattern', '')}")

            # 存储文件下载进度
            task.task_metadata['download_files'] = []

            def file_progress_callback(file_name, file_index, total_files, downloaded_bytes, total_bytes):
                """单个文件的下载进度回调"""
                files = task.task_metadata.get('download_files', [])
                found = False
                for f in files:
                    if f['name'] == file_name:
                        f['downloaded'] = downloaded_bytes
                        f['total'] = total_bytes
                        f['progress'] = int((downloaded_bytes / total_bytes * 100)) if total_bytes > 0 else 0
                        found = True
                        break
                if not found:
                    files.append({
                        'name': file_name,
                        'index': file_index,
                        'total_files': total_files,
                        'downloaded': downloaded_bytes,
                        'total': total_bytes,
                        'progress': int((downloaded_bytes / total_bytes * 100)) if total_bytes > 0 else 0,
                        'status': 'downloading'
                    })
                task.task_metadata['download_files'] = files

            def check_pause():
                """检查任务是否被暂停"""
                return task.status == TaskStatus.PAUSED

            download_result = await asmr_service.download_work(
                rjcode=rjcode,
                dest_dir=download_dir,
                filter_rules=filter_rules,
                progress_callback=progress_callback,
                file_progress_callback=file_progress_callback,
                check_pause=check_pause
            )

            # 保存失败文件列表
            if download_result.get('failed_files'):
                task.task_metadata['failed_files'] = download_result['failed_files']

            # 处理暂停情况
            if download_result.get('paused'):
                logger.info(f"[{rjcode}] 下载被暂停，等待恢复...")
                task.update_progress(task.progress, "已暂停 - 等待恢复")
                await task.wait_if_paused()
                if task.is_cancelled():
                    return

            if not download_result['success']:
                # 检查是否是"未找到版本"错误
                error_msg = download_result.get('error', '下载失败')
                if '未找到该作品的任何版本' in error_msg or '未找到' in error_msg:
                    # 进入等待重试状态，使用 cron 计算下次重试时间
                    from croniter import croniter
                    cron_expr = config.asmr_sync.retry_cron if hasattr(config, 'asmr_sync') else "0 */1 * * *"
                    now = datetime.now()
                    cron = croniter(cron_expr, now)
                    retry_after = cron.get_next(datetime)

                    task.set_waiting_retry(error_msg, retry_after)
                    task.task_metadata['subtitle_folder'] = subtitle_folder
                    task.task_metadata['work_title'] = work_title

                    # 保存到数据库持久化
                    self._save_waiting_retry_task(task, subtitle_folder, work_title, error_msg, retry_after)

                    wait_hours = (retry_after - now).total_seconds() / 3600
                    logger.warning(f"[{rjcode}] 未在 asmr.one 找到作品，将在 {wait_hours:.1f} 小时后重试 (cron: {cron_expr})")
                    return

                # 检查是否有部分文件下载成功
                if download_result.get('downloaded_files'):
                    task.task_metadata['partial_success'] = True
                    logger.warning(f"[{rjcode}] 部分文件下载成功，但有失败: {len(download_result.get('failed_files', []))} 个文件失败")
                else:
                    task.fail(error_msg)
                    return

            work_title = download_result.get('title', work_title)
            actual_rjcode = download_result.get('actual_rjcode', rjcode)
            task.task_metadata['work_title'] = work_title
            task.task_metadata['actual_rjcode'] = actual_rjcode
            task.rjcode = actual_rjcode  # 更新任务的RJ号为实际下载的版本

            await task.wait_if_paused()
            if task.is_cancelled():
                return

            # 步骤3: 清理LRC广告（如果启用）
            lrc_clean_result = None
            if config.asmr_sync.lrc_clean_enabled:
                task.update_progress(70, "清理LRC广告")
                custom_patterns = config.asmr_sync.lrc_clean_patterns if hasattr(config.asmr_sync, 'lrc_clean_patterns') else None
                lrc_clean_result = subtitle_service.clean_lrc_files_in_folder(subtitle_folder, custom_patterns)
                if lrc_clean_result['cleaned_files'] > 0:
                    logger.info(f"[{rjcode}] LRC广告清理完成: 处理 {lrc_clean_result['total_files']} 个文件, "
                               f"清理 {lrc_clean_result['cleaned_files']} 个文件, "
                               f"移除 {lrc_clean_result['total_removed_lines']} 行广告")
                task.task_metadata['lrc_clean_result'] = lrc_clean_result

            # 步骤3.5: 字幕文件繁体转简体（如果启用）
            simplify_result = None
            if getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                task.update_progress(72, "字幕繁体转简体")
                simplify_result = subtitle_service.convert_subtitles_to_simplified_in_folder(subtitle_folder)
                if simplify_result['converted_files'] > 0:
                    logger.info(f"[{rjcode}] 字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                               f"转换 {simplify_result['converted_files']} 个文件")
                task.task_metadata['simplify_result'] = simplify_result

            # 步骤4: 同步字幕文件
            if config.asmr_sync_step.sync_subtitle:
                task.update_progress(75, "同步字幕文件")
                sync_result = subtitle_service.sync_subtitles_to_download(
                    download_dir=download_dir,
                    subtitle_folder=subtitle_folder
                )

                # 保存字幕同步结果到任务元数据
                task.task_metadata['sync_result'] = {
                    'success': sync_result['success'],
                    'renamed_files': sync_result.get('renamed_files', []),
                    'copied_subtitles': sync_result.get('copied_subtitles', []),
                    'errors': sync_result.get('errors', [])
                }

                if not sync_result['success']:
                    logger.warning(f"[{rjcode}] 字幕同步部分失败: {sync_result.get('errors', [])}")
                else:
                    logger.info(f"[{rjcode}] 字幕同步成功: 重命名 {len(sync_result.get('renamed_files', []))} 个文件")
            else:
                logger.info(f"[{rjcode}] 步骤[同步字幕]已禁用，跳过")

            await task.wait_if_paused()
            if task.is_cancelled():
                return

            # 步骤4: 重命名文件夹
            if config.asmr_sync_step.rename:
                task.update_progress(85, "重命名文件夹")

                # 检测标题是否包含日文字符
                def contains_japanese(text):
                    """检测文本是否包含日文字符（平假名、片假名、日文汉字）"""
                    for char in text:
                        if '\u3040' <= char <= '\u309F':  # 平假名
                            return True
                        if '\u30A0' <= char <= '\u30FF':  # 片假名
                            return True
                        if '\u4E00' <= char <= '\u9FAF':  # 日文汉字（CJK统一表意文字）
                            # 进一步检查是否是常见日文用字
                            pass
                    # 检查是否包含平假名或片假名
                    import re
                    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
                        return True
                    return False

                # 如果下载的标题包含日文，尝试从字幕文件夹名称获取中文标题
                final_work_title = work_title
                if contains_japanese(work_title):
                    # 从字幕文件夹路径提取名称
                    subtitle_folder_name = os.path.basename(subtitle_folder)
                    logger.info(f"[{rjcode}] 检测到日文标题，尝试从字幕文件夹获取中文名称: {subtitle_folder_name}")

                    # 尝试从字幕文件夹名称提取标题（格式通常是: RJxxxxxxxx 标题）
                    import re
                    match = re.match(r'(RJ\d+)\s*(.+)', subtitle_folder_name, re.IGNORECASE)
                    if match:
                        extracted_title = match.group(2).strip()
                        if extracted_title and not contains_japanese(extracted_title):
                            final_work_title = extracted_title
                            logger.info(f"[{rjcode}] 使用字幕文件夹标题: {final_work_title}")
                        else:
                            logger.info(f"[{rjcode}] 字幕文件夹标题也包含日文，保留原标题")

                # 构建元数据用于重命名
                metadata = {
                    'rjcode': actual_rjcode,  # 使用实际下载的RJ号
                    'work_name': final_work_title,
                    'work_title': final_work_title,
                }
                task.task_metadata.update(metadata)

                renamed_path = await rename_service.rename(download_dir, task)
                logger.info(f"[{rjcode}] 重命名后路径: {renamed_path}")
            else:
                logger.info(f"[{rjcode}] 步骤[重命名]已禁用，跳过")
                renamed_path = download_dir
                metadata = {
                    'rjcode': actual_rjcode,
                    'work_name': work_title,
                    'work_title': work_title,
                }
                task.task_metadata.update(metadata)

            # 步骤4.5: 扁平化文件夹
            if config.rename.flatten_single_subfolder:
                task.update_progress(87, "扁平化文件夹结构")
                renamed_path = rename_service._flatten_single_subfolder(renamed_path)
                logger.info(f"[{rjcode}] 扁平化后路径: {renamed_path}")

            await task.wait_if_paused()
            if task.is_cancelled():
                return

            # 步骤5: 智能分类
            if config.asmr_sync_step.classify and task.auto_classify:
                task.update_progress(90, "智能分类")
                final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                task.output_path = final_path
                logger.info(f"[{rjcode}] 分类后路径: {final_path}")
            else:
                if not config.asmr_sync_step.classify:
                    logger.info(f"[{rjcode}] 步骤[智能分类]已禁用，跳过")
                # 移动到 library_path
                task.update_progress(90, "移动到媒体库")
                library_path = config.storage.library_path
                final_path = os.path.join(library_path, os.path.basename(renamed_path))

                # 处理重名
                counter = 1
                while os.path.exists(final_path):
                    final_path = os.path.join(library_path, f"{os.path.basename(renamed_path)}_{counter}")
                    counter += 1

                await asyncio.to_thread(shutil.move, renamed_path, final_path)
                task.output_path = final_path
                logger.info(f"[{rjcode}] 移动到: {final_path}")
                # 索引同步：禁用 classify 的兜底链路里没有 library 上下文，
                # 用按路径反查的 helper 让索引也能跟上
                try:
                    from .library_manager import get_library_manager
                    get_library_manager().notify_index_upsert_by_path(final_path)
                except Exception:
                    logger.debug(
                        "[索引] ASMRSync 禁用 classify 分支通知索引失败 path=%s",
                        final_path, exc_info=True,
                    )

            # 步骤6: 移动字幕文件夹到Finished目录
            if config.asmr_sync_step.move_subtitle_folder:
                task.update_progress(95, "整理字幕文件夹")
                try:
                    subtitle_parent = os.path.dirname(subtitle_folder)
                    finished_dir = os.path.join(subtitle_parent, "Finished")

                    # 创建Finished目录
                    os.makedirs(finished_dir, exist_ok=True)

                    # 移动字幕文件夹
                    subtitle_folder_name = os.path.basename(subtitle_folder)
                    dest_subtitle_path = os.path.join(finished_dir, subtitle_folder_name)

                    # 处理重名
                    counter = 1
                    while os.path.exists(dest_subtitle_path):
                        dest_subtitle_path = os.path.join(finished_dir, f"{subtitle_folder_name}_{counter}")
                        counter += 1

                    await asyncio.to_thread(shutil.move, subtitle_folder, dest_subtitle_path)
                    logger.info(f"[{rjcode}] 字幕文件夹已移动到: {dest_subtitle_path}")
                    task.task_metadata['subtitle_moved_to'] = dest_subtitle_path

                except Exception as move_error:
                    logger.warning(f"[{rjcode}] 移动字幕文件夹失败: {move_error}")
            else:
                logger.info(f"[{rjcode}] 步骤[移动字幕文件夹]已禁用，跳过")

            task.update_progress(100, "完成")
            append_progress_log(f"完成，写入 {written_count} 个字幕", 100, 'success')
            task.complete()
            logger.info(f"[{rjcode}] ASMR 同步下载任务完成")

        except Exception as e:
            logger.error(f"[{rjcode}] ASMR 同步下载任务失败: {e}", exc_info=True)
            task.fail(str(e))

            # 清理临时文件
            if 'download_dir' in locals() and os.path.exists(download_dir):
                try:
                    await asyncio.to_thread(shutil.rmtree, download_dir)
                    logger.info(f"[{rjcode}] 清理临时目录: {download_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"[{rjcode}] 清理临时目录失败: {cleanup_error}")

    async def _process_http_download(self, task: Task):
        """处理 HTTP 外链下载任务。"""
        from .http_download_service import get_http_download_service, sanitize_http_download_item

        service = get_http_download_service()
        task.task_metadata.setdefault("download_files", [])
        task.task_metadata.setdefault("download_runtime", {})
        task.task_metadata.setdefault("failed_files", [])
        task.task_metadata.setdefault("progress_log", [])
        task.task_metadata.setdefault("download_mode", "http")
        task.task_metadata.setdefault("source_page", "asmr-sync")
        task.task_metadata.setdefault("source_action", "manual_http_download")
        task.task_metadata.setdefault("task_domain", "http_download")
        task.task_metadata.setdefault("task_kind", TaskType.HTTP_DOWNLOAD.value)

        try:
            from ..config.settings import get_config

            cfg_retry_count = int(getattr(get_config().http_downloader, "retry_count", 5) or 5)
        except Exception:
            cfg_retry_count = 5
        max_auto_retries = int(task.task_metadata.get("http_download_auto_retry_limit", min(2, max(1, cfg_retry_count))) or 0)
        max_auto_retries = max(0, min(3, max_auto_retries))
        cumulative_download_files: List[Dict[str, Any]] = [
            row for row in list(task.task_metadata.get("download_attempt_history") or [])
            if isinstance(row, dict)
        ]
        last_error = ""

        def refresh_merged_attempt_state() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
            nonlocal cumulative_download_files
            attempt_rows = [
                row for row in list(task.task_metadata.get("download_files") or [])
                if isinstance(row, dict)
            ]
            cumulative_download_files = service.merge_download_attempt_rows(cumulative_download_files, attempt_rows)
            merged_failed = service.merge_download_failed_rows(
                cumulative_download_files,
                [
                    row for row in list(task.task_metadata.get("failed_files") or [])
                    if isinstance(row, dict)
                ],
            )
            completed = [
                row for row in cumulative_download_files
                if str(row.get("status") or "").strip().lower() == "completed"
            ]
            downloaded_bytes = sum(int((row or {}).get("downloaded") or (row or {}).get("size") or 0) for row in completed)
            transferred_bytes = sum(int((row or {}).get("downloaded") or 0) for row in cumulative_download_files)
            runtime = dict(task.task_metadata.get("download_runtime") or {})
            runtime.update({
                "status": "completed" if completed and not merged_failed else ("partial_failed" if completed else "failed"),
                "total_files": len(cumulative_download_files),
                "completed_files": len(completed),
                "failed_files": len(merged_failed),
                "active_file_count": 0,
                "transferred_bytes": transferred_bytes,
                "speed_bytes_per_sec": 0,
            })
            metrics = dict(task.task_metadata.get("performance_metrics") or {})
            duration_ms = int(metrics.get("duration_ms") or 0)
            metrics.update({
                "downloaded_bytes": downloaded_bytes,
                "transferred_bytes": transferred_bytes,
                "success_count": len(completed),
                "failed_count": len(merged_failed),
                "average_speed_bytes": int(downloaded_bytes / max(duration_ms / 1000, 1)) if downloaded_bytes and duration_ms else int(metrics.get("average_speed_bytes") or 0),
            })
            task.task_metadata["download_files"] = cumulative_download_files
            task.task_metadata["failed_files"] = merged_failed
            task.task_metadata["download_runtime"] = runtime
            task.task_metadata["performance_metrics"] = metrics
            return completed, merged_failed

        def finish_partial(completed: List[Dict[str, Any]], failed: List[Dict[str, Any]]) -> None:
            message = f"下载部分成功，成功 {len(completed)} 个，失败 {len(failed)} 个"
            if last_error:
                message = f"{message}：{last_error}"
            task.task_metadata["partial_success"] = True
            task.task_metadata["failure_reason"] = message
            task.task_metadata["http_download_final_status"] = "partial_failed"
            task.task_metadata["auto_retry_exhausted"] = bool(task.task_metadata.get("auto_retry_attempts"))
            task.touch_metadata("http_download_partial_failed")
            task.fail(message)
            task.progress = 100
            task.current_step = message

        try:
            attempt_index = 0
            while True:
                if attempt_index > 0:
                    retry_items, retry_keys = service.build_retry_selection_for_task(task)
                    if not retry_items:
                        break
                    task.task_metadata["http_download_auto_retrying"] = True
                    task.task_metadata["auto_retry_attempts"] = attempt_index
                    task.task_metadata["retry_target_count"] = len(retry_items)
                    task.task_metadata["selected_items"] = [
                        sanitize_http_download_item(item)
                        for item in retry_items
                    ]
                    task.task_metadata["selected_keys"] = retry_keys
                    task.task_metadata["download_files"] = []
                    task.task_metadata["download_runtime"] = {}
                    task.task_metadata["failed_files"] = []
                    task.task_metadata["performance_metrics"] = {}
                    task.task_metadata["failure_reason"] = ""
                    task.progress = 0
                    service._append_control_log(
                        task,
                        f"自动重试失败文件，第 {attempt_index}/{max_auto_retries} 轮，共 {len(retry_items)} 个",
                        "warning",
                    )

                try:
                    await service.start_download_task(task)
                    if task.is_cancelled():
                        raise asyncio.CancelledError()
                    completed, failed = refresh_merged_attempt_state()
                except Exception as exc:
                    last_error = str(exc)
                    completed, failed = refresh_merged_attempt_state()
                    if failed and attempt_index < max_auto_retries and not task.is_cancelled():
                        attempt_index += 1
                        continue
                    if completed and failed:
                        finish_partial(completed, failed)
                        return
                    raise

                if failed and attempt_index < max_auto_retries and not task.is_cancelled():
                    attempt_index += 1
                    continue
                if failed:
                    finish_partial(completed, failed)
                    return

                if attempt_index > 0:
                    service._append_control_log(task, "自动重试完成，失败项已全部补齐", "success")
                if task.is_cancelled():
                    raise asyncio.CancelledError()
                task.task_metadata["http_download_final_status"] = "completed"
                task.touch_metadata("http_download_completed")
                task.complete()
                return
        finally:
            if task.is_cancelled():
                await service.cancel_task(task.id)

    async def _process_baidu_netdisk_download(self, task: Task):
        """处理百度网盘下载任务。"""
        from .baidu_netdisk_service import get_baidu_netdisk_service

        service = get_baidu_netdisk_service()
        task.task_metadata.setdefault("download_files", [])
        task.task_metadata.setdefault("download_runtime", {})
        task.task_metadata.setdefault("failed_files", [])
        task.task_metadata.setdefault("progress_log", [])
        task.task_metadata.setdefault("download_mode", "baidu_netdisk")
        task.task_metadata.setdefault("source_modes", ["baidu_netdisk"])
        task.task_metadata.setdefault("platforms", ["baidu_netdisk"])
        task.task_metadata.setdefault("platform_label", "百度网盘")
        task.task_metadata.setdefault("source_page", "asmr-sync")
        task.task_metadata.setdefault("source_action", "manual_baidu_netdisk_download")
        task.task_metadata.setdefault("task_domain", "baidu_netdisk")
        task.task_metadata.setdefault("task_kind", TaskType.BAIDU_NETDISK_DOWNLOAD.value)

        try:
            result = await service.start_download_task(task)
            if result.get("skipped"):
                task.task_metadata["baidu_netdisk_final_status"] = "skipped"
                task.complete()
                return
            failed_files = list(result.get("failed_files") or task.task_metadata.get("failed_files") or [])
            downloaded_files = list(result.get("downloaded_files") or [])
            if downloaded_files and failed_files:
                message = f"百度网盘下载部分成功，成功 {len(downloaded_files)} 个，失败 {len(failed_files)} 个"
                task.task_metadata["partial_success"] = True
                task.task_metadata["failure_reason"] = message
                task.task_metadata["baidu_netdisk_final_status"] = "partial_failed"
                task.fail(message)
                task.progress = 100
                task.current_step = message
                return
            task.task_metadata["baidu_netdisk_final_status"] = "completed"
            task.complete()
        finally:
            if task.is_cancelled():
                await service.cancel_task(task.id)

    async def _process_baidu_netdisk_upload(self, task: Task):
        """处理百度网盘上传任务。"""
        from .baidu_netdisk_service import get_baidu_netdisk_service

        service = get_baidu_netdisk_service()
        task.task_metadata.setdefault("upload_files", [])
        task.task_metadata.setdefault("uploaded_files", [])
        task.task_metadata.setdefault("failed_files", [])
        task.task_metadata.setdefault("upload_runtime", {})
        task.task_metadata.setdefault("progress_log", [])
        task.task_metadata.setdefault("platforms", ["baidu_netdisk"])
        task.task_metadata.setdefault("platform_label", "百度网盘")
        task.task_metadata.setdefault("source_page", "library")
        task.task_metadata.setdefault("source_action", "manual_baidu_netdisk_upload")
        task.task_metadata.setdefault("task_domain", "baidu_netdisk")
        task.task_metadata.setdefault("task_kind", TaskType.BAIDU_NETDISK_UPLOAD.value)

        try:
            result = await service.start_upload_task(task)
            uploaded_files = list(result.get("uploaded_files") or task.task_metadata.get("uploaded_files") or [])
            failed_files = list(result.get("failed_files") or task.task_metadata.get("failed_files") or [])
            if uploaded_files and failed_files:
                message = f"百度网盘上传部分成功，成功 {len(uploaded_files)} 个，失败 {len(failed_files)} 个"
                task.task_metadata["partial_success"] = True
                task.task_metadata["failure_reason"] = message
                task.task_metadata["baidu_netdisk_upload_final_status"] = "partial_failed"
                task.fail(message)
                task.progress = 100
                task.current_step = message
                return
            if failed_files and not uploaded_files:
                message = service._first_failure_reason(failed_files) or "百度网盘上传失败"
                task.task_metadata["baidu_netdisk_upload_final_status"] = "failed"
                raise RuntimeError(message)
            task.task_metadata["baidu_netdisk_upload_final_status"] = "completed"
            task.complete()
        finally:
            if task.is_cancelled():
                await service.cancel_task(task.id)

    async def _queue_nested_subtitle_archives(
        self,
        parent_task: Task,
        rjcode: str,
        library_path: str,
        filenames: List[str],
    ) -> None:
        """将嵌套解压时跳过的小型压缩包（潜在字幕源）加入字幕补配预检队列。

        这些压缩包因 < NESTED_SUBTITLE_SIZE_THRESHOLD 而在嵌套解压阶段被保留为原始文件。
        此方法在主作品入库完成后调用，直接走 queue_pending_archive_import 预检，
        无需重复判断"是否翻译作"。
        """
        from .linked_subtitle_import_service import get_linked_subtitle_import_service

        linked_svc = get_linked_subtitle_import_service()

        for filename in filenames:
            # 在库目录中查找文件（支持子目录嵌套）
            found_path: Optional[str] = None
            for dirpath, _, files in os.walk(library_path):
                if filename in files:
                    found_path = os.path.join(dirpath, filename)
                    break

            if not found_path:
                logger.warning("[%s] 嵌套字幕压缩包在库目录中未找到，跳过: %s", rjcode, filename)
                continue

            # 创建临时 Task 引用，仅用于调用字幕补配预检服务（不提交到任务队列）
            stub_task = Task(
                task_type=TaskType.RJ_SUBTITLE_FETCH,
                source_path=found_path,
                auto_classify=False,
                metadata={
                    "rjcode": rjcode,
                    "queue_origin": "nested_archive_auto",
                    "parent_task_id": parent_task.id,
                },
            )

            try:
                result = await linked_svc.queue_pending_archive_import(stub_task, rjcode)
                if result.get("handled"):
                    logger.info(
                        "[%s] 嵌套字幕压缩包已加入字幕补配预检队列: %s", rjcode, filename
                    )
                else:
                    logger.info(
                        "[%s] 嵌套字幕压缩包未命中字幕补配路径: %s, reason=%s",
                        rjcode,
                        filename,
                        result.get("reason") or "",
                    )
            except Exception as e:
                logger.warning(
                    "[%s] 处理嵌套字幕压缩包失败: %s, 错误: %s", rjcode, filename, e
                )

    async def _process_rj_subtitle_fetch(self, task: Task):
        """处理 RJ 字幕抓取任务"""
        from .rj_subtitle_service import get_rj_subtitle_service

        rj_service = get_rj_subtitle_service()
        folder_path = task.task_metadata.get('folder_path') or task.source_path
        library_id = task.task_metadata.get('library_id') or None
        overwrite = bool(task.task_metadata.get('overwrite', False))
        enable_metadata_match = bool(task.task_metadata.get('enable_metadata_match', True))
        force_rerun = bool(task.task_metadata.get('force_rerun', False))
        naming_strategy = str(task.task_metadata.get('naming_strategy') or 'audio').lower()
        use_filter_rules = bool(task.task_metadata.get('use_filter_rules', False))
        subtitle_filter_rules = task.task_metadata.get('subtitle_filter_rules') or []
        ai_match_mode = str(task.task_metadata.get('ai_match_mode') or 'rule_ai_auto').lower()
        ai_confidence_threshold = task.task_metadata.get('ai_confidence_threshold')

        rjcode = task.task_metadata.get('rjcode') or self._extract_rjcode(folder_path) or "未知"
        task.rjcode = rjcode

        logger.info(f"[{rjcode}] 开始 RJ 字幕抓取任务: {folder_path}")

        try:
            task.update_progress(5, "准备扫描 RJ 文件夹")
            task.task_metadata['download_files'] = []
            task.task_metadata['progress_log'] = []
            cleaned_subtitle_dir = ''
            cleaned_library_id = library_id

            def enqueue_subtitle_index_replace(subtitle_dir: str) -> None:
                if not subtitle_dir or not library_id:
                    return
                try:
                    manager = get_library_manager()
                    library = manager.get_library_definition(library_id)
                    manager._enqueue_index_replace_subtree_many(library, [subtitle_dir])
                except Exception:
                    logger.debug(
                        "[索引] RJ 字幕抓取后 replace subtitles 索引失败 library=%s path=%s",
                        library_id, subtitle_dir, exc_info=True,
                    )

            def enqueue_cleaned_subtitle_index_delete() -> None:
                if not cleaned_subtitle_dir or not cleaned_library_id:
                    return
                try:
                    manager = get_library_manager()
                    library = manager.get_library_definition(cleaned_library_id)
                    manager._enqueue_index_delete_many(library, [cleaned_subtitle_dir])
                except Exception:
                    logger.debug(
                        "[索引] RJ 字幕强制清理后 delete subtitles 索引失败 library=%s path=%s",
                        cleaned_library_id, cleaned_subtitle_dir, exc_info=True,
                    )

            def append_progress_log(message: str, progress: Optional[int] = None, level: str = 'info'):
                if not message:
                    return
                logs = task.task_metadata.get('progress_log', [])
                last = logs[-1] if logs else None
                if last and last.get('message') == message and last.get('progress') == progress and last.get('level') == level:
                    return
                logs.append({
                    'time': datetime.now().isoformat(),
                    'progress': task.progress if progress is None else progress,
                    'message': message,
                    'level': level,
                })
                task.task_metadata['progress_log'] = logs[-30:]

            append_progress_log("准备扫描 RJ 文件夹", 5)

            if force_rerun:
                task.update_progress(6, "强制清理旧字幕目录")
                append_progress_log("强制清理旧字幕目录", 6, 'warning')
                cleanup_result = await rj_service.clear_existing_subtitles_for_folder(
                    folder_path=folder_path,
                    library_id=library_id,
                )
                deleted_subtitles = int(cleanup_result.get('deleted_subtitles') or 0)
                cleaned_subtitle_dir = str(cleanup_result.get('subtitle_dir') or '')
                task.task_metadata.update({
                    'force_rerun_deleted_subtitles': deleted_subtitles,
                    'force_rerun_cleared_subtitle_dir': cleaned_subtitle_dir,
                    'existing_subtitle_count': 0,
                    'subtitle_dir': '',
                    'written_files': [],
                    'skipped_files': [],
                    'write_errors': [],
                    'failed_files': [],
                    'match_result': {},
                    'downloaded_count': 0,
                })
                if deleted_subtitles > 0:
                    append_progress_log(f"已清理旧字幕 {deleted_subtitles} 个，开始重新抓取", 6, 'warning')
                else:
                    append_progress_log("未发现旧字幕，按强制模式重新抓取", 6, 'warning')

            if bool(task.task_metadata.get('skip_if_existing_subtitles')) and rjcode != "未知":
                try:
                    local_hits = get_library_manager().find_rj_in_ready_index([rjcode], library_ids=[library_id] if library_id else None)
                except Exception:
                    logger.warning("[%s] ready 库存索引字幕态检查失败，按无字幕继续抓取", rjcode, exc_info=True)
                    local_hits = {}
                flat_hits = list(local_hits.get(rjcode) or [])
                primary_hit = flat_hits[0] if flat_hits else {}
                local_has_subtitles = any(
                    bool(hit.get('local_subtitle_present')) or int(hit.get('subtitle_file_count') or 0) > 0
                    for hit in flat_hits
                )
                subtitle_file_count = sum(int(hit.get('subtitle_file_count') or 0) for hit in flat_hits)
                matched_rjcode = str(primary_hit.get('matched_rjcode') or primary_hit.get('rjcode') or rjcode).upper()
                task.task_metadata.update({
                    'kikoeru_checked_rjcode': rjcode,
                    'kikoeru_has_work': bool(flat_hits),
                    'kikoeru_has_existing_subtitles': local_has_subtitles,
                    'kikoeru_matched_rjcode': matched_rjcode,
                    'kikoeru_subtitle_file_count': subtitle_file_count,
                    'kikoeru_subtitle_check_source': 'library_index',
                })
                if local_has_subtitles:
                    skip_message = f"本地库存已有字幕（{matched_rjcode}"
                    if subtitle_file_count > 0:
                        skip_message += f" / {subtitle_file_count} 个"
                    skip_message += "），跳过抓取"
                    task.update_progress(100, skip_message)
                    append_progress_log(skip_message, 100)
                    task.complete()
                    logger.info(f"[{rjcode}] {skip_message}")
                    return

            def progress_callback(progress: int, step: str):
                task.update_progress(progress, step)
                append_progress_log(step, progress)

            def file_progress_callback(file_name, file_index, total_files, downloaded_bytes, total_bytes):
                files = task.task_metadata.get('download_files', [])
                found = False
                for item in files:
                    if item['name'] == file_name:
                        item['downloaded'] = downloaded_bytes
                        item['total'] = total_bytes
                        item['progress'] = int((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
                        found = True
                        break
                if not found:
                    files.append({
                        'name': file_name,
                        'index': file_index,
                        'total_files': total_files,
                        'downloaded': downloaded_bytes,
                        'total': total_bytes,
                        'progress': int((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0,
                        'status': 'downloading',
                    })
                task.task_metadata['download_files'] = files

            result = await rj_service.process_folder(
                folder_path=folder_path,
                library_id=library_id,
                overwrite=overwrite,
                enable_metadata_match=enable_metadata_match,
                naming_strategy=naming_strategy,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
                ai_match_mode=ai_match_mode,
                ai_confidence_threshold=ai_confidence_threshold,
                task_id=task.id,
                progress_callback=progress_callback,
                file_progress_callback=file_progress_callback,
                should_cancel=task.is_cancelled,
            )

            download_display_map = {
                str(item.get('name') or ''): str(item.get('display_name') or item.get('name') or '')
                for item in result.get('download_files', []) or []
                if item.get('name')
            }
            if download_display_map:
                files = task.task_metadata.get('download_files', [])
                for item in files:
                    display_name = download_display_map.get(str(item.get('name') or ''))
                    if display_name:
                        item['display_name'] = display_name
                task.task_metadata['download_files'] = files

            task.task_metadata.update({
                'folder_path': folder_path,
                'library_id': library_id,
                'rjcode': result.get('rjcode', rjcode),
                'actual_rjcode': result.get('actual_rjcode', ''),
                'source_lang': result.get('source_lang', ''),
                'source_work_type': result.get('source_work_type', ''),
                'source_title': result.get('source_title', ''),
                'downloaded_count': result.get('downloaded_count', 0),
                'existing_subtitle_count': result.get('existing_subtitle_count', 0),
                'subtitle_dir': result.get('subtitle_dir', ''),
                'written_files': result.get('written_files', []),
                'skipped_files': result.get('skipped_files', []),
                'write_errors': result.get('write_errors', []),
                'failed_files': result.get('failed_files', []),
                'match_result': result.get('match_result', {}),
                'search_attempts': result.get('search_attempts', []),
                'lrc_clean_result': result.get('lrc_clean_result'),
                'simplify_result': result.get('simplify_result'),
                'content_deduped_count': result.get('content_deduped_count', 0),
                'content_deduped_files': result.get('content_deduped_files', []),
                'awaiting_manual_match': result.get('awaiting_manual_match', False),
                'ai_match_status': result.get('ai_match_status', task.task_metadata.get('ai_match_status', '')),
                'ai_match_mode': result.get('ai_match_mode', ai_match_mode),
                'ai_auto_applied': bool(result.get('ai_auto_applied', False)),
                'ai_match_model': result.get('ai_match_model', task.task_metadata.get('ai_match_model', '')),
                'ai_confidence_threshold': result.get('ai_confidence_threshold', ai_confidence_threshold),
                'ai_low_confidence_count': result.get('ai_low_confidence_count', 0),
                'ai_unmatched_audio_count': result.get('ai_unmatched_audio_count', 0),
                'ai_unmatched_subtitle_count': result.get('ai_unmatched_subtitle_count', 0),
                'ai_match_result': result.get('ai_match_result', {}),
                'ai_match_error': result.get('ai_match_error', {}),
            })

            deduped_count = int(result.get('content_deduped_count') or 0)
            if deduped_count > 0:
                append_progress_log(f"已按内容合并 {deduped_count} 个完全重复字幕", task.progress)

            remote_retry_after = self._rj_subtitle_remote_retry_after(result)
            if remote_retry_after and not result.get('success'):
                reason = self._rj_subtitle_remote_retry_reason(result)
                append_progress_log(reason, task.progress, 'warning')
                task.task_metadata.update({
                    'retry_source': 'rj_subtitle_fetch',
                    'retry_kind': 'remote_library_degraded',
                    'remote_retry_after': remote_retry_after.isoformat(),
                })
                task.set_waiting_retry(reason, remote_retry_after)
                logger.warning(
                    "[%s] RJ 字幕远程回写遇到库存退化，进入等待重试: retry_after=%s reason=%s",
                    rjcode,
                    remote_retry_after.isoformat(),
                    reason,
                )
                return

            if not result.get('success'):
                error_message = result.get('error', 'RJ 字幕抓取失败')
                append_progress_log(error_message, task.progress, 'error')
                enqueue_cleaned_subtitle_index_delete()
                task.fail(error_message)
                return

            if result.get('awaiting_manual_match'):
                enqueue_subtitle_index_replace(str(result.get('subtitle_dir') or ''))
                task.progress = 100
                task.status = TaskStatus.WAITING_MANUAL
                task.completed_at = datetime.now()
                if result.get('ai_match_status') == 'failed':
                    task.current_step = 'AI 配对失败，等待筛选与匹配'
                elif result.get('ai_match_status'):
                    task.current_step = 'AI 配对待确认，等待筛选与匹配'
                else:
                    task.current_step = '已抓取原始字幕，等待筛选与匹配'
                append_progress_log(task.current_step, 100)
                try:
                    from .task_notification_service import enqueue_notification_check
                    asyncio.create_task(enqueue_notification_check(task))
                except Exception:
                    logger.warning(f'[{rjcode}] 触发 AI/人工配对等待通知失败', exc_info=True)
                logger.info(f'[{rjcode}] RJ 字幕原始抓取完成，等待用户筛选与匹配')
                return

            written_count = len(result.get('written_files', []))
            skipped_count = len(result.get('skipped_files', []))
            unmatched_count = len(result.get('match_result', {}).get('unmatched_audio', []))
            subtitle_dir = str(result.get('subtitle_dir') or '')
            if subtitle_dir:
                enqueue_subtitle_index_replace(subtitle_dir)
                try:
                    from .circle_completion_service import get_circle_completion_service

                    await get_circle_completion_service().sync_subtitle_for_rj(
                        str(result.get('actual_rjcode') or result.get('rjcode') or rjcode),
                        folder_path=folder_path,
                        library_id=library_id,
                        subtitle_dir=subtitle_dir,
                        subtitle_file_count=written_count,
                    )
                except Exception:
                    logger.warning("[%s] RJ 字幕抓取完成后同步社团字幕态失败", rjcode, exc_info=True)
            else:
                enqueue_cleaned_subtitle_index_delete()
            task.update_progress(100, f"完成，写入 {written_count} 个字幕")
            task.complete()
            if result.get('partial'):
                task.current_step = f"部分完成，写入 {written_count}，跳过 {skipped_count}，未匹配音频 {unmatched_count}"
            logger.info(f"[{rjcode}] RJ 字幕抓取完成，写入 {written_count} 个字幕")

        except Exception as e:
            logger.error(f"[{rjcode}] RJ 字幕抓取任务失败: {e}", exc_info=True)
            try:
                enqueue_cleaned_subtitle_index_delete()
            except Exception:
                logger.debug("[索引] RJ 字幕异常清理后 delete subtitles 索引兜底失败", exc_info=True)
            task.fail(str(e))

    async def _process_library_folder_completion_preview(self, task: Task):
        """处理库存页“补全文件夹”后台预览任务。"""
        from .library_folder_completion_service import get_library_folder_completion_service

        metadata = dict(task.task_metadata or {})
        library_id = str(metadata.get("library_id") or "").strip()
        selected_paths = list(metadata.get("selected_paths") or [])
        if not library_id:
            raise ValueError("缺少库存")
        if not selected_paths:
            raise ValueError("没有选中要补全的目录")

        task.update_progress(8, "解析选中目录")
        result = await get_library_folder_completion_service().build_preview(
            library_id,
            selected_paths,
            progress_callback=lambda pct, step: task.update_progress(pct, step),
            cancel_callback=task.is_cancelled,
        )
        task.task_metadata["folder_completion_preview_result"] = result
        task.task_metadata["folder_completion_summary"] = result.get("summary") or {}
        task.task_metadata["downloadable_count"] = int((result.get("summary") or {}).get("downloadable_count") or 0)
        task.task_metadata["missing_file_count"] = int((result.get("summary") or {}).get("missing_file_count") or 0)
        task.touch_metadata("folder_completion_preview")
        task.update_progress(100, "补全预览完成")
        task.complete()

    async def _process_circle_completion_index(self, task: Task):
        """处理社团补全索引任务"""
        from .circle_completion_service import get_circle_completion_service

        task.task_metadata = dict(task.task_metadata or {})
        task.task_metadata.setdefault('progress_log', [])

        def append_progress_log(message: str, progress: Optional[int] = None, level: str = 'info'):
            if not message:
                return
            logs = list(task.task_metadata.get('progress_log') or [])
            last = logs[-1] if logs else None
            if last and last.get('message') == message and last.get('progress') == progress and last.get('level') == level:
                return
            logs.append({
                'time': datetime.now().isoformat(),
                'progress': task.progress if progress is None else progress,
                'message': message,
                'level': level,
            })
            task.task_metadata['progress_log'] = logs[-40:]

        raw_circle_queries = list(task.task_metadata.get('circle_queries') or [])
        normalized_circle_queries = []
        for value in raw_circle_queries:
            query = str(value or '').strip()
            if query and query not in normalized_circle_queries:
                normalized_circle_queries.append(query)
        if not normalized_circle_queries:
            circle_query = str(task.task_metadata.get('circle_query') or task.source_path or '').strip()
            if circle_query:
                normalized_circle_queries = [circle_query]
        if not normalized_circle_queries:
            raise ValueError('社团名不能为空')

        is_batch = len(normalized_circle_queries) > 1
        task.task_metadata['circle_query'] = normalized_circle_queries[0]
        task.task_metadata['circle_queries'] = normalized_circle_queries
        task.task_metadata['batch_total'] = len(normalized_circle_queries)
        append_progress_log("准备建立社团索引", 1)

        batch_results = []
        batch_circle_summaries = []
        last_successful_result = None
        success_count = 0
        failed_count = 0
        total_queries = len(normalized_circle_queries)

        for batch_index, circle_query in enumerate(normalized_circle_queries, start=1):
            if task.is_cancelled():
                raise asyncio.CancelledError()

            def progress_callback(progress: int, step: str, **meta):
                base_progress = int(((batch_index - 1) / max(total_queries, 1)) * 100)
                scaled_progress = base_progress + int((max(0, min(100, int(progress or 0))) / 100) * (100 / max(total_queries, 1)))
                task.update_progress(min(99, scaled_progress), step)
                task.task_metadata = {
                    **(task.task_metadata or {}),
                    'circle_query': circle_query,
                    'current_circle_query': circle_query,
                    'batch_index': batch_index,
                    'batch_total': total_queries,
                    'index_meta': {
                        **dict((task.task_metadata or {}).get('index_meta') or {}),
                        **{key: value for key, value in (meta or {}).items() if value is not None},
                        'batch_index': batch_index,
                        'batch_total': total_queries,
                        'current_circle_query': circle_query,
                        'completed_queries': success_count,
                        'failed_queries': failed_count,
                        'is_batch': is_batch,
                        'is_refresh_all': bool((task.task_metadata or {}).get('is_refresh_all')),
                    },
                }
                prefix = f"[{batch_index}/{total_queries}] " if is_batch else ""
                append_progress_log(f"{prefix}{step}", min(99, scaled_progress))

            try:
                result = await get_circle_completion_service().index_circle_catalog(
                    circle_query,
                    force_refresh=bool(task.task_metadata.get('force_refresh')),
                    include_dlsite=bool(task.task_metadata.get('include_dlsite', True)),
                    include_kikoeru=bool(task.task_metadata.get('include_kikoeru', True)),
                    only_new_works=bool(task.task_metadata.get('only_new_works')),
                    progress_callback=progress_callback,
                    cancel_callback=task.is_cancelled,
                )
                last_successful_result = result
                success_count += 1
                result_summary = dict(result.get('summary') or {})
                indexed_counts = dict(result.get('indexed_counts') or {})
                batch_circle_summaries.append({
                    'circle_query': circle_query,
                    'circle_id': str(result.get('circle_id') or ''),
                    'circle_name': str(result_summary.get('circle_name') or circle_query),
                    'works': int(indexed_counts.get('works') or result_summary.get('works') or 0),
                    'local_owned_count': int(indexed_counts.get('local_owned_count') or result_summary.get('local_owned_count') or 0),
                    'kikoeru_owned_count': int(indexed_counts.get('owned_count') or result_summary.get('owned_count') or 0),
                    'dl_count': int(indexed_counts.get('dl_count') or result_summary.get('dl_count') or 0),
                    'asmr_available_count': int(indexed_counts.get('asmr_available_count') or result_summary.get('asmr_available_count') or indexed_counts.get('downloadable_count') or 0),
                    'downloadable_count': int(indexed_counts.get('downloadable_count') or result_summary.get('downloadable_count') or 0),
                    'missing_count': int(indexed_counts.get('missing_count') or result_summary.get('missing_count') or 0),
                })
                batch_results.append({
                    'circle_query': circle_query,
                    'success': True,
                    'circle_id': str(result.get('circle_id') or ''),
                    'circle_name': str(((result.get('summary') or {}).get('circle_name')) or circle_query),
                    'result': result,
                })
                append_progress_log(f"[{batch_index}/{total_queries}] 社团索引完成：{circle_query}", None, 'success' if is_batch else 'info')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failed_count += 1
                batch_circle_summaries.append({
                    'circle_query': circle_query,
                    'circle_name': circle_query,
                    'success': False,
                    'error_message': str(exc),
                })
                batch_results.append({
                    'circle_query': circle_query,
                    'success': False,
                    'error_message': str(exc),
                })
                logger.warning(
                    "[社团补全] 社团索引失败 circle_query=%s batch=%d/%d: %s",
                    circle_query, batch_index, total_queries, exc,
                    exc_info=True,
                )
                append_progress_log(f"[{batch_index}/{total_queries}] 社团索引失败：{circle_query} - {exc}", None, 'warning')

        if not success_count and failed_count:
            raise RuntimeError(f"批量建立失败：共 {failed_count} 个社团建立失败")

        if last_successful_result is None:
            raise RuntimeError("社团索引未生成有效结果")

        summary_step = "批量社团索引完成" if is_batch else "社团索引完成"
        successful_summaries = [item for item in batch_circle_summaries if item.get('success', True)]
        aggregate_indexed_counts = {
            'works': sum(int(item.get('works') or 0) for item in successful_summaries),
            'local_owned_count': sum(int(item.get('local_owned_count') or 0) for item in successful_summaries),
            'owned_count': sum(int(item.get('kikoeru_owned_count') or 0) for item in successful_summaries),
            'dl_count': sum(int(item.get('dl_count') or 0) for item in successful_summaries),
            'asmr_available_count': sum(int(item.get('asmr_available_count') or 0) for item in successful_summaries),
            'downloadable_count': sum(int(item.get('downloadable_count') or 0) for item in successful_summaries),
            'missing_count': sum(int(item.get('missing_count') or 0) for item in successful_summaries),
        }
        final_indexed_counts = aggregate_indexed_counts if is_batch else dict(last_successful_result.get('indexed_counts') or {})
        task.task_metadata = {
            **(task.task_metadata or {}),
            'circle_query': str((last_successful_result.get('summary') or {}).get('circle_name') or normalized_circle_queries[0]),
            'circle_id': str(last_successful_result.get('circle_id') or ''),
            'circle_name': str(((last_successful_result.get('summary') or {}).get('circle_name')) or normalized_circle_queries[0]),
            'index_result': last_successful_result,
            'index_batch_results': batch_results,
            'batch_circle_summaries': batch_circle_summaries,
            'indexed_counts': final_indexed_counts,
            'index_meta': {
                **dict((task.task_metadata or {}).get('index_meta') or {}),
                **({
                    'combined_candidates_count': aggregate_indexed_counts.get('works'),
                    'aggregated_count': aggregate_indexed_counts.get('works'),
                    'dlsite_candidates_count': aggregate_indexed_counts.get('dl_count'),
                    'asmr_available_count': aggregate_indexed_counts.get('asmr_available_count'),
                } if is_batch else {}),
                'batch_total': total_queries,
                'completed_queries': success_count,
                'failed_queries': failed_count,
                'is_batch': is_batch,
                'is_refresh_all': bool((task.task_metadata or {}).get('is_refresh_all')),
                'current_circle_query': normalized_circle_queries[-1],
            },
        }
        task.update_progress(100, f"{summary_step}（成功 {success_count} / 失败 {failed_count}）" if is_batch else summary_step)
        append_progress_log(
            f"{summary_step}（成功 {success_count} / 失败 {failed_count}）" if is_batch else summary_step,
            100,
            'success',
        )

    async def _process_circle_completion_refresh_selected(self, task: Task):
        """处理社团补全选中作品刷新任务"""
        from .circle_completion_service import get_circle_completion_service

        task.task_metadata = dict(task.task_metadata or {})
        task.task_metadata.setdefault('progress_log', [])

        def append_progress_log(message: str, progress: Optional[int] = None, level: str = 'info'):
            if not message:
                return
            logs = list(task.task_metadata.get('progress_log') or [])
            last = logs[-1] if logs else None
            if last and last.get('message') == message and last.get('progress') == progress and last.get('level') == level:
                return
            logs.append({
                'time': datetime.now().isoformat(),
                'progress': task.progress if progress is None else progress,
                'message': message,
                'level': level,
            })
            task.task_metadata['progress_log'] = logs[-40:]

        circle_id = str(task.task_metadata.get('circle_id') or '').strip()
        canonical_rjcodes = list(task.task_metadata.get('canonical_rjcodes') or [])
        if not circle_id:
            raise ValueError('缺少社团标识')
        if not canonical_rjcodes:
            raise ValueError('没有选中要刷新的作品')

        task.task_metadata['circle_id'] = circle_id
        task.task_metadata['selected_count'] = len(canonical_rjcodes)
        append_progress_log("准备批量刷新选中作品", 1)

        def progress_callback(progress: int, step: str, **meta):
            task.update_progress(progress, step)
            task.task_metadata = {
                **(task.task_metadata or {}),
                'refresh_meta': {
                    **dict((task.task_metadata or {}).get('refresh_meta') or {}),
                    **{key: value for key, value in (meta or {}).items() if value is not None},
                },
            }
            append_progress_log(step, progress)

        result = await get_circle_completion_service().refresh_circle_works(
            circle_id,
            canonical_rjcodes,
            force_refresh=bool(task.task_metadata.get('force_refresh')),
            progress_callback=progress_callback,
            cancel_callback=task.is_cancelled,
        )

        task.task_metadata = {
            **(task.task_metadata or {}),
            'circle_id': str(result.get('circle_id') or circle_id),
            'circle_name': str(result.get('circle_name') or task.task_metadata.get('circle_name') or ''),
            'refresh_result': result,
            'refreshed_count': int(result.get('refreshed_count') or 0),
            'changed_count': int(result.get('changed_count') or 0),
            'force_refresh': bool(task.task_metadata.get('force_refresh')),
        }
        task.update_progress(100, "批量刷新完成")
        append_progress_log("批量刷新完成", 100, 'success')

    async def _process_circle_completion_bonus_probe(self, task: Task):
        """处理 DLsite 隐藏特典探测任务。"""
        from .dlsite_bonus_probe_service import get_dlsite_bonus_probe_service

        task.task_metadata = dict(task.task_metadata or {})
        task.task_metadata.setdefault('progress_log', [])

        def append_progress_log(message: str, progress: Optional[int] = None, level: str = 'info'):
            if not message:
                return
            logs = list(task.task_metadata.get('progress_log') or [])
            last = logs[-1] if logs else None
            if last and last.get('message') == message and last.get('progress') == progress and last.get('level') == level:
                return
            logs.append({
                'time': datetime.now().isoformat(),
                'progress': task.progress if progress is None else progress,
                'message': message,
                'level': level,
            })
            task.task_metadata['progress_log'] = logs[-80:]
            task.touch_metadata('bonus_probe_log')

        metadata = dict(task.task_metadata or {})
        circle_id = str(metadata.get('circle_id') or task.source_path or '').strip()
        maker_id = str(metadata.get('maker_id') or '').strip().upper()
        mode = str(metadata.get('mode') or 'normal').strip() or 'normal'
        release_dates = list(metadata.get('release_dates') or [])
        selected_rjcodes_by_date = dict(metadata.get('selected_rjcodes_by_date') or {})
        gap_limit = int(metadata.get('gap_limit') or 500)
        raw_batch_size = metadata.get('batch_size')
        raw_concurrency = metadata.get('concurrency')
        batch_size = int(raw_batch_size) if raw_batch_size is not None else None
        concurrency = int(raw_concurrency) if raw_concurrency is not None else None
        if not circle_id:
            raise ValueError('缺少社团 ID')

        append_progress_log('准备探测 DLsite 隐藏特典', 1)
        bonus_probe_service = get_dlsite_bonus_probe_service()
        runtime_limits = bonus_probe_service.resolve_probe_runtime_limits(
            mode=mode,
            batch_size=batch_size,
            concurrency=concurrency,
        )
        batch_size = int(runtime_limits['batch_size'])
        concurrency = int(runtime_limits['concurrency'])
        task.task_metadata.update({
            'batch_size': batch_size,
            'concurrency': concurrency,
            'bonus_probe_runtime_limits': runtime_limits,
        })

        def progress_callback(progress: int, step: str, meta: Dict[str, Any]):
            if task.status != TaskStatus.PROCESSING or task.is_cancelled():
                return
            pct = min(99, max(1, int(progress or 0)))
            task.update_progress(pct, step)
            task.task_metadata = {
                **dict(task.task_metadata or {}),
                'bonus_probe_meta': {
                    **dict((task.task_metadata or {}).get('bonus_probe_meta') or {}),
                    **dict(meta or {}),
                },
            }
            append_progress_log(step, pct)

        result = await bonus_probe_service.probe_circle_dates(
            circle_id=circle_id,
            maker_id=maker_id,
            release_dates=release_dates,
            mode=mode,
            gap_limit=gap_limit,
            batch_size=batch_size,
            concurrency=concurrency,
            job_id=task.id,
            selected_rjcodes_by_date=selected_rjcodes_by_date,
            progress_callback=progress_callback,
            cancel_callback=task.is_cancelled,
        )
        task.task_metadata.update({
            'circle_id': result.get('circle_id') or circle_id,
            'circle_name': result.get('circle_name') or metadata.get('circle_name') or '',
            'maker_id': result.get('maker_id') or maker_id,
            'bonus_probe_result': result,
            'bonus_probe_summary': {
                'date_count': int(result.get('date_count') or 0),
                'probe_count': int(result.get('probe_count') or 0),
                'checked_probe_count': int(result.get('probe_count') or 0),
                'hit_count': int(result.get('hit_count') or 0),
                'inserted_count': int(result.get('inserted_count') or 0),
                'request_count': int(result.get('request_count') or 0),
                'original_count': int(result.get('original_count') or 0),
                'original_concluded_count': int(result.get('original_concluded_count') or 0),
                'original_pending_count': int(result.get('original_pending_count') or 0),
                'original_has_bonus_count': int(result.get('original_has_bonus_count') or 0),
                'original_no_bonus_count': int(result.get('original_no_bonus_count') or 0),
                'incomplete_count': int(result.get('incomplete_count') or 0),
                'failed_count': int(result.get('failed_count') or 0),
                'failed_dates': list(result.get('failed_dates') or []),
                'budget_reached': bool(result.get('budget_reached')),
            },
        })
        inserted_count = int(result.get('inserted_count') or 0)
        incomplete_count = int(result.get('incomplete_count') or 0)
        failed_count = int(result.get('failed_count') or 0)
        if incomplete_count:
            append_progress_log(
                f"特典探测完成但有 {incomplete_count} 个发售日未产出完整结论",
                100,
                'warning',
            )
        if failed_count:
            append_progress_log(
                f"特典探测有 {failed_count} 个发售日局部失败，可稍后重试失败日期",
                100,
                'warning',
            )
        append_progress_log(
            f"特典探测完成：命中 {int(result.get('hit_count') or 0)} 个，写入 {inserted_count} 个",
            100,
            'success',
        )
        task.update_progress(
            100,
            f"特典探测完成，写入 {inserted_count} 个"
            + (f"，{incomplete_count} 个发售日未产出完整结论" if incomplete_count else ""),
        )
        task.complete()

    async def _process_local_library_upload(self, task: Task):
        from .circle_completion_service import get_circle_completion_service
        from .library_manager import (
            LocalUploadCleanupError,
            LocalUploadSourceLockedError,
            LocalUploadVerificationError,
            get_library_manager,
        )

        task.task_metadata = dict(task.task_metadata or {})
        task.task_metadata.setdefault("upload_files", [])
        task.task_metadata.setdefault("uploaded_files", [])
        task.task_metadata.setdefault("failed_files", [])
        task.task_metadata.setdefault("verification_failures", [])
        task.task_metadata.setdefault("progress_log", [])
        task.task_metadata.setdefault("upload_runtime", {})

        selected_items = [
            {
                "source_path": str((item or {}).get("source_path") or "").strip(),
                "relative_target_dir": str((item or {}).get("relative_target_dir") or "").strip(),
            }
            for item in (task.task_metadata.get("selected_items") or [])
            if str((item or {}).get("source_path") or "").strip()
        ]
        selected_paths = [
            str(path or "").strip()
            for path in (task.task_metadata.get("selected_paths") or [])
            if str(path or "").strip()
        ]
        target_library_id = str(task.task_metadata.get("target_library_id") or "").strip()
        target_subdir = str(task.task_metadata.get("target_subdir") or "").strip()
        circle_name = str(task.task_metadata.get("circle_name") or "").strip()

        if not selected_paths:
            raise RuntimeError("没有可上传的目录")
        if not target_library_id:
            raise RuntimeError("缺少目标库存")

        def append_progress_log(message: str, progress: Optional[int] = None, level: str = "info"):
            if not message:
                return
            logs = list(task.task_metadata.get("progress_log") or [])
            last = logs[-1] if logs else None
            if last and last.get("message") == message and last.get("progress") == progress and last.get("level") == level:
                return
            logs.append({
                "time": datetime.now().isoformat(),
                "message": message,
                "progress": progress,
                "level": level,
            })
            task.task_metadata["progress_log"] = logs[-40:]

        def build_relative_target_dir():
            if circle_name and target_subdir:
                return f"{target_subdir}/{circle_name}".strip("/")
            if circle_name:
                return circle_name
            return target_subdir or None

        upload_files = []
        total_bytes = 0
        total_files = 0
        source_entries = selected_items or [{"source_path": path, "relative_target_dir": build_relative_target_dir() or ""} for path in selected_paths]
        for entry in source_entries:
            source_dir = str(entry.get("source_path") or "").strip()
            normalized_source_dir = str(source_dir or "").strip()
            if not normalized_source_dir:
                continue
            task_scope = os.path.basename(os.path.abspath(normalized_source_dir))
            # 单文件来源：作为唯一一条 upload_file 直接登记，UI 任务面板也能看到该文件
            if os.path.isfile(normalized_source_dir):
                try:
                    file_size = int(os.path.getsize(normalized_source_dir))
                except OSError:
                    file_size = 0
                filename = os.path.basename(normalized_source_dir)
                upload_files.append({
                    "task_scope": task_scope,
                    "source_dir": normalized_source_dir,
                    "name": filename,
                    "relative_path": filename,
                    "local_path": normalized_source_dir,
                    "status": "pending",
                    "progress": 0,
                    "size": file_size,
                    "uploaded_bytes": 0,
                })
                total_files += 1
                total_bytes += file_size
                continue
            for root, _, files in os.walk(normalized_source_dir):
                for filename in files:
                    local_path = os.path.join(root, filename)
                    try:
                        file_size = int(os.path.getsize(local_path))
                    except OSError:
                        file_size = 0
                    relative_path = os.path.relpath(local_path, normalized_source_dir).replace(os.sep, "/")
                    upload_files.append({
                        "task_scope": task_scope,
                        "source_dir": normalized_source_dir,
                        "name": filename,
                        "relative_path": relative_path,
                        "local_path": local_path,
                        "status": "pending",
                        "progress": 0,
                        "size": file_size,
                        "uploaded_bytes": 0,
                    })
                    total_files += 1
                    total_bytes += file_size

        task.task_metadata["upload_files"] = upload_files
        task.task_metadata["upload_runtime"] = {
            "phase": "preparing",
            "total_files": total_files,
            "completed_files": 0,
            "transferred_bytes": 0,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": 0,
            "current_file_name": "",
            "current_relative_path": "",
            "current_source_dir": "",
        }

        task.update_progress(1, f"准备上传 {len(selected_paths)} 个目录")

        manager = get_library_manager()
        uploaded = []
        uploaded_rows = []
        runtime = dict(task.task_metadata.get("upload_runtime") or {})

        def normalize_relative_target_dir(value: str) -> str:
            text = str(value or "").replace("\\", "/").strip("/")
            if not text:
                return ""
            try:
                library_def = manager.get_library_definition(target_library_id)
                root_text = str(getattr(library_def, "root_path", "") or "").replace("\\", "/").strip("/")
                root_name = root_text.rsplit("/", 1)[-1] if root_text else ""
                if root_text and text == root_text:
                    return ""
                if root_text and text.startswith(f"{root_text}/"):
                    return text[len(root_text):].strip("/")
                if root_name and text == root_name:
                    return ""
                if root_name and text.startswith(f"{root_name}/"):
                    return text[len(root_name):].strip("/")
            except Exception:
                logger.debug("归一化上传目标相对目录失败: %s", value, exc_info=True)
            return text

        def progress_callback(snapshot: dict):
            runtime.update(snapshot or {})
            runtime["backend_speed_bytes_per_sec"] = int(runtime.get("speed_bytes_per_sec") or 0)
            runtime["speed_bytes_per_sec"] = 0
            task.task_metadata["upload_runtime"] = dict(runtime)
            phase = str(runtime.get("phase") or "").strip()
            current_file_name = str(runtime.get("current_file_name") or "").strip()
            current_relative_path = str(runtime.get("current_relative_path") or "").strip()
            if phase == "preparing":
                label = current_relative_path or current_file_name or "准备远程目录"
                task.current_step = f"准备上传: {label}"
            elif current_file_name:
                task.current_step = f"上传中: {current_file_name}"
            current_relative_path = str(runtime.get("current_relative_path") or "").strip()
            current_source_dir = str(runtime.get("current_source_dir") or "").strip()
            total_bytes_current = max(0, int(runtime.get("current_file_total_bytes") or 0))
            uploaded_bytes_current = max(0, int(runtime.get("current_file_uploaded_bytes") or 0))
            if current_relative_path:
                rows = list(task.task_metadata.get("upload_files") or [])
                for row in rows:
                    if str(row.get("relative_path") or "").strip() != current_relative_path:
                        continue
                    row_source_dir = str(row.get("source_dir") or "").strip()
                    if current_source_dir and row_source_dir and os.path.abspath(row_source_dir) != os.path.abspath(current_source_dir):
                        continue
                    row["status"] = "uploading" if phase != "preparing" else "preparing"
                    row["uploaded_bytes"] = uploaded_bytes_current
                    if total_bytes_current > 0:
                        row["progress"] = max(0, min(100, int((uploaded_bytes_current / total_bytes_current) * 100)))
                    break
                task.task_metadata["upload_files"] = rows

        def file_completed_callback(file_row: dict):
            uploaded_rows.append(dict(file_row or {}))
            task.task_metadata["uploaded_files"] = uploaded_rows[-200:]
            relative_path = str((file_row or {}).get("relative_path") or "").strip()
            source_dir = str((file_row or {}).get("source_dir") or "").strip()
            rows = list(task.task_metadata.get("upload_files") or [])
            for row in rows:
                if str(row.get("relative_path") or "").strip() != relative_path:
                    continue
                row_source_dir = str(row.get("source_dir") or "").strip()
                if source_dir and row_source_dir and os.path.abspath(row_source_dir) != os.path.abspath(source_dir):
                    continue
                row["status"] = "completed"
                row["uploaded_bytes"] = int(row.get("size") or 0)
                row["progress"] = 100
                break
            task.task_metadata["upload_files"] = rows

        def mark_upload_verification_failed(error: LocalUploadVerificationError):
            failures = list(getattr(error, "failures", []) or [])
            task.task_metadata["verification_failures"] = failures
            task.task_metadata["failure_reason"] = str(error)
            failed_files = []
            rows = list(task.task_metadata.get("upload_files") or [])
            for failure in failures:
                failure_relative = str((failure or {}).get("relative_path") or "").strip()
                for row in rows:
                    if failure_relative and str(row.get("relative_path") or "").strip() != failure_relative:
                        continue
                    row["status"] = "failed"
                    row["progress"] = min(99, int(row.get("progress") or 0))
                    row["failure_reason"] = str((failure or {}).get("reason") or "远端校验失败")
                    failed_files.append({
                        "name": row.get("name") or failure_relative,
                        "relative_path": row.get("relative_path") or failure_relative,
                        "size": int(row.get("size") or row.get("size_bytes") or 0),
                        "uploaded": int(row.get("uploaded_bytes") or 0),
                        "stage": "upload",
                        "reason": row["failure_reason"],
                        "remote_path": (failure or {}).get("remote_path") or "",
                    })
                    break
            task.task_metadata["upload_files"] = rows
            task.task_metadata["failed_files"] = failed_files
            append_progress_log(f"远端校验失败，已保留本地源目录: {str(error)}", task.progress, "error")

        def mark_upload_cleanup_failed(error: LocalUploadCleanupError, target_path: str):
            task.task_metadata["local_cleanup_status"] = "failed"
            task.task_metadata["local_cleanup_error"] = str(getattr(error, "cleanup_error", "") or error)
            task.task_metadata["remote_upload_verified"] = True
            task.task_metadata["failure_reason"] = str(error)
            if target_path:
                task.output_path = target_path
                task.task_metadata["final_output_path"] = target_path
            append_progress_log("远端已确认上传完成，但本地源目录删除失败，请关闭占用文件后手动清理", task.progress, "error")

        def mark_upload_source_locked(error: LocalUploadSourceLockedError):
            locked_paths = list(getattr(error, "locked_paths", []) or [])
            task.task_metadata["source_lock_failures"] = locked_paths
            task.task_metadata["failure_reason"] = str(error)
            failed_files = []
            rows = list(task.task_metadata.get("upload_files") or [])
            for row in rows:
                row_path = str(row.get("local_path") or "").strip()
                matched_lock = next((item for item in locked_paths if str(item.get("path") or "") == row_path), None)
                if not matched_lock:
                    continue
                row["status"] = "failed"
                row["failure_reason"] = "本地文件被占用，未开始上传"
                failed_files.append({
                    "name": row.get("name") or row.get("relative_path") or "",
                    "relative_path": row.get("relative_path") or "",
                    "size": int(row.get("size") or row.get("size_bytes") or 0),
                    "uploaded": 0,
                    "stage": "preflight",
                    "reason": row["failure_reason"],
                    "local_path": row_path,
                })
            task.task_metadata["upload_files"] = rows
            task.task_metadata["failed_files"] = failed_files
            append_progress_log("本地源文件仍被占用，已停止上传，避免远端成功但本地无法删除", task.progress, "error")

        total_dirs = len(source_entries)
        for index, entry in enumerate(source_entries, start=1):
            source_dir = str(entry.get("source_path") or "").strip()
            relative_target_dir = normalize_relative_target_dir(str(entry.get("relative_target_dir") or "").strip() or build_relative_target_dir() or "")
            source_name = os.path.basename(os.path.abspath(source_dir))
            step_progress = max(1, min(95, int(((index - 1) / max(total_dirs, 1)) * 100)))
            task.update_progress(step_progress, f"开始上传 {index}/{total_dirs}: {source_name}")
            if relative_target_dir:
                task.task_metadata["target_relative_dir"] = relative_target_dir.replace("\\", "/")
            try:
                target_path = await manager.upload_directory_to_library(
                    target_library_id,
                    source_dir,
                    relative_target_dir,
                    delete_source_on_success=True,
                    progress_callback=progress_callback,
                    file_completed_callback=file_completed_callback,
                )
            except LocalUploadVerificationError as exc:
                mark_upload_verification_failed(exc)
                raise
            except LocalUploadSourceLockedError as exc:
                mark_upload_source_locked(exc)
                raise
            except LocalUploadCleanupError as exc:
                target_path = str(getattr(exc, "remote_path", "") or "")
                uploaded.append({
                    "source": source_dir,
                    "target": target_path,
                    "remote_verified": True,
                    "local_cleanup": "failed",
                    "cleanup_error": str(getattr(exc, "cleanup_error", "") or exc),
                })
                task.task_metadata["upload_result"] = {
                    "uploaded": uploaded,
                    "count": len(uploaded),
                    "local_cleanup": "failed",
                }
                mark_upload_cleanup_failed(exc, target_path)
                raise
            uploaded.append({"source": source_dir, "target": target_path})
            # 索引同步：远程上传完成后立即 fire-and-forget upsert，
            # 让跨库搜索 / 库存页搜索能立刻找到刚上传的子树
            try:
                target_library_def = manager.get_library_definition(target_library_id)
                manager._notify_index_self_mutation_upsert_subtree(
                    target_library_def, target_path,
                )
            except Exception:
                logger.debug(
                    "[索引] PROCESS_EXISTING_FOLDER 上传后通知 upsert 失败 path=%s",
                    target_path, exc_info=True,
                )
            append_progress_log(
                f"目录上传完成: {source_name}",
                min(99, int((index / max(total_dirs, 1)) * 100)),
                "success",
            )

        task.task_metadata["upload_runtime"] = {
            **runtime,
            "phase": "completed",
            "completed_files": total_files,
            "transferred_bytes": total_bytes,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": 0,
        }
        task.task_metadata["upload_result"] = {
            "uploaded": uploaded,
            "count": len(uploaded),
        }
        if uploaded:
            task.output_path = str(uploaded[-1].get("target") or "")
            task.task_metadata["final_output_path"] = task.output_path

        source_rjcodes = []
        for entry in source_entries:
            source_dir = str((entry or {}).get("source_path") or "").strip()
            normalized_rjcode = self._extract_rjcode(source_dir)
            if normalized_rjcode and normalized_rjcode not in source_rjcodes:
                source_rjcodes.append(normalized_rjcode)

        if source_rjcodes and uploaded:
            circle_service = get_circle_completion_service()
            for index, rjcode in enumerate(source_rjcodes):
                target_info = uploaded[min(index, len(uploaded) - 1)] if uploaded else {}
                target_path = str((target_info or {}).get("target") or task.output_path or "").strip()
                try:
                    await circle_service.sync_owned_for_rj(
                        rjcode,
                        folder_path=target_path,
                        library_id=target_library_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[社团补全] 本地上传完成后回写拥有态失败 rj=%s target=%s error=%s",
                        rjcode,
                        target_path,
                        exc,
                        exc_info=True,
                    )
        task.update_progress(100, "上传完成")
        append_progress_log(f"上传完成，共 {len(uploaded)} 个目录", 100, "success")

# 全局任务引擎实例
_task_engine: Optional[TaskEngine] = None

def get_task_engine() -> TaskEngine:
    """获取任务引擎实例"""
    global _task_engine
    from ..config.settings import get_config
    configured_max_workers = max(1, int(get_config().processing.max_workers))
    if _task_engine is None:
        _task_engine = TaskEngine(max_concurrent=configured_max_workers)
        # 启动时清理上次服务重启前残留的"正在处理中"临时冲突记录
        try:
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                stale = (
                    db.query(ConflictWork)
                    .filter(
                        ConflictWork.existing_path == "正在处理中",
                        ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                    )
                    .all()
                )
                if stale:
                    for c in stale:
                        db.delete(c)
                    db.commit()
                    logger.info(f"[启动清理] 删除 {len(stale)} 条残留的'正在处理中'冲突记录")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[启动清理] 清理残留冲突记录时出错: {e}")
    else:
        _task_engine.set_max_concurrent(configured_max_workers)
    return _task_engine
