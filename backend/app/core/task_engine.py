import asyncio
import uuid
import os
import shutil
from datetime import datetime
from typing import Optional, Callable
from enum import Enum
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAUSED = "paused"
    WAITING_MANUAL = "waiting_manual"  # 等待手动处理（重复作品）
    WAITING_RETRY = "waiting_retry"  # 等待重试（未找到版本等）
    COMPLETED = "completed"
    FAILED = "failed"

class TaskType(str, Enum):
    EXTRACT = "extract"
    FILTER = "filter"
    METADATA = "metadata"
    RENAME = "rename"
    AUTO_PROCESS = "auto_process"
    PROCESS_EXISTING_FOLDER = "process_existing_folder"  # 处理已存在的文件夹（跳过解压）
    ASMR_SYNC_DOWNLOAD = "asmr_sync_download"  # ASMR 同步下载任务
    RJ_SUBTITLE_FETCH = "rj_subtitle_fetch"  # RJ 字幕抓取任务
    LOCAL_LIBRARY_UPLOAD = "local_library_upload"
    CIRCLE_COMPLETION_INDEX = "circle_completion_index"
    CIRCLE_COMPLETION_REFRESH_SELECTED = "circle_completion_refresh_selected"
    CIRCLE_COMPLETION_DOWNLOAD_BATCH = "circle_completion_download_batch"

class Task:
    """任务对象"""
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
        self._cancelled = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self.rjcode = rjcode  # 作品的RJ号，用于重复检测
        self.session_id = None
        self.business_key = None

    def start(self):
        """开始任务"""
        self.status = TaskStatus.PROCESSING
        self.started_at = datetime.now()
        self.current_step = "处理中"
    
    def complete(self):
        """完成任务"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now()
        self.progress = 100
        self.current_step = "完成"
    
    def fail(self, error: str):
        """任务失败"""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error
        self.current_step = f"失败: {error}"
    
    def pause(self):
        """暂停任务"""
        self.status = TaskStatus.PAUSED
        self._pause_event.clear()
    
    def resume(self):
        """恢复任务"""
        self.status = TaskStatus.PROCESSING
        self._pause_event.set()

    def set_waiting_retry(self, reason: str, retry_after: datetime = None):
        """设置等待重试状态"""
        self.status = TaskStatus.WAITING_RETRY
        self.current_step = f"等待重试: {reason}"
        self.task_metadata['retry_reason'] = reason
        self.task_metadata['retry_after'] = retry_after.isoformat() if retry_after else None
        self.task_metadata['retry_count'] = self.task_metadata.get('retry_count', 0) + 1
        logger.info(f"任务 {self.id} 进入等待重试状态: {reason}")

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
        """取消任务"""
        self._cancelled = True
        self.status = TaskStatus.FAILED
        self.error_message = "用户取消"
        self.completed_at = datetime.now()
        self.current_step = "已取消"
        logger.info(f"任务 {self.id} 已被用户取消")
    
    async def wait_if_paused(self):
        """如果暂停则等待"""
        await self._pause_event.wait()
    
    def is_cancelled(self) -> bool:
        """检查是否被取消"""
        return self._cancelled
    
    def update_progress(self, progress: int, step: str):
        """更新进度"""
        self.progress = min(100, max(0, progress))
        self.current_step = step
        logger.info(f"任务 {self.id}: {step} ({progress}%)")

    def reset_for_rerun(self, step: str = "等待重新执行"):
        """重置任务运行态，保留任务 ID 原地重跑。"""
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.current_step = step
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        self._cancelled = False
        self._pause_event.set()

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

    def set_max_concurrent(self, max_concurrent: int):
        """动态更新最大并发数"""
        max_concurrent = max(1, int(max_concurrent))
        if self.max_concurrent != max_concurrent:
            logger.info(f"更新任务引擎最大并发数: {self.max_concurrent} -> {max_concurrent}")
            self.max_concurrent = max_concurrent

    def is_rjcode_processing(self, rjcode: str) -> bool:
        """检查RJ号是否正在被处理"""
        return rjcode in self._processing_rjcodes
    
    def mark_rjcode_processing(self, rjcode: str):
        """标记RJ号正在处理"""
        self._processing_rjcodes.add(rjcode)
        logger.info(f"标记RJ号正在处理: {rjcode}")
    
    def unmark_rjcode_processing(self, rjcode: str):
        """取消标记RJ号"""
        if rjcode in self._processing_rjcodes:
            self._processing_rjcodes.discard(rjcode)
            logger.info(f"取消标记RJ号: {rjcode}")
    
    def add_progress_callback(self, callback: Callable):
        """添加进度回调"""
        self._progress_callbacks.append(callback)
    
    async def _notify_progress(self, task: Task):
        """通知进度更新"""
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
        rjcode = self._extract_rjcode(task.source_path) or "未知"
        logger.info(f"[{rjcode}] 任务提交 - ID: {task.id[:8]}..., 源文件: {os.path.basename(task.source_path)}")
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
        if task.type == TaskType.LOCAL_LIBRARY_UPLOAD:
            return "upload"
        if task.type in {TaskType.CIRCLE_COMPLETION_INDEX, TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH}:
            return "circle_completion"
        return "system"

    def _ensure_task_context(self, task: Task):
        """给历史任务和新任务补齐统一上下文。"""
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

    def persist_task_snapshot(self, task: Task) -> None:
        """把需要跨重启保留的任务快照写入 tasks 表。"""
        from ..models.database import SessionLocal, Task as TaskRecord

        self._ensure_task_context(task)
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
            record.task_metadata = dict(task.task_metadata or {})
            db.commit()
        except Exception:
            logger.warning("[任务持久化] 写入任务快照失败: task_id=%s", getattr(task, "id", ""), exc_info=True)
            db.rollback()
        finally:
            db.close()

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
        except Exception:
            logger.warning("[任务持久化] 删除任务快照失败: task_id=%s", normalized_task_id, exc_info=True)
            db.rollback()
        finally:
            db.close()

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
        """恢复等待人工配对的字幕补配任务，避免后端重启后工作台状态丢失。"""
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
                if not bool(metadata.get("awaiting_manual_match")):
                    continue
                if bool(metadata.get("manual_match_completed")):
                    continue

                task_type = self._coerce_task_type(row.type)
                if task_type is None:
                    continue
                task = Task(
                    task_type=task_type,
                    source_path=row.source_path or metadata.get("folder_path") or "",
                    output_path=row.output_path,
                    auto_classify=False,
                    metadata=metadata,
                    task_id=row.id,
                    status=self._coerce_task_status(row.status),
                    rjcode=metadata.get("rjcode") or metadata.get("target_rjcode") or "",
                )
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

    def _get_effective_rjcode(self, task: Task, fallback_path: Optional[str] = None) -> str:
        """统一获取当前任务可用的 RJ 号，优先复用已推断结果。"""
        candidates = [
            getattr(task, "rjcode", None),
            (task.task_metadata or {}).get("rjcode"),
            (task.task_metadata or {}).get("inferred_rjcode"),
            self._extract_rjcode(fallback_path or task.source_path),
        ]
        for candidate in candidates:
            value = self._extract_rjcode(str(candidate or "")) or str(candidate or "").strip().upper()
            if value and value != "未知":
                return value
        return ""

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

        normalized_rjcode = (rjcode or "").strip()
        if normalized_rjcode == "未知":
            normalized_rjcode = self._extract_rjcode(source_path) or ""

        metadata = dict(task.task_metadata or {})
        metadata["failure_stage"] = "extract"
        metadata["error_message"] = reason
        metadata["available_actions"] = ["RETRY", "SKIP"]

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

    def _record_problem_work_for_task_failure(self, task: Task, rjcode: Optional[str], reason: str):
        """把导入流程中的失败统一写入问题作品，避免任务中心失败但问题作品页为空。"""
        from .classifier import SmartClassifier

        source_path = str(task.source_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return

        normalized_rjcode = (rjcode or "").strip()
        if normalized_rjcode == "未知":
            normalized_rjcode = ""
        if not normalized_rjcode:
            normalized_rjcode = self._extract_rjcode(source_path) or ""

        failure_stage = self._infer_failure_stage(task, reason)
        conflict_type = "EXTRACT_FAILED" if failure_stage == "extract" else "PROCESS_FAILED"
        metadata = dict(task.task_metadata or {})
        metadata.update({
            "failure_stage": failure_stage,
            "error_message": reason,
            "available_actions": ["RETRY", "SKIP"],
            "source_task_type": task.type.value,
            "failed_task_id": task.id,
            "failed_step": str(task.current_step or "").strip(),
            "failed_progress": int(task.progress or 0),
        })

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
                db.delete(conflict)
            db.commit()
            if conflict:
                logger.info("失败问题项重试成功，已移出问题作品: conflict_id=%s task_id=%s", conflict.id, task.id)
        except Exception as exc:
            db.rollback()
            logger.error("更新解压失败问题项状态失败: %s", exc, exc_info=True)
        finally:
            db.close()

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
                    conflict.new_metadata = next_metadata
                    db.commit()
                return

            if task.status == TaskStatus.COMPLETED:
                conflict.status = action
                next_metadata.pop("resolution_error", None)
                if task.output_path:
                    next_metadata["resolution_output_path"] = task.output_path
                if conflict.new_path:
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == os.path.basename(str(conflict.new_path))
                    ).first()
                    if archive_record:
                        archive_record.status = "completed"
                        archive_record.processed_at = datetime.now()
            elif task.status == TaskStatus.FAILED:
                conflict.status = "PENDING"
                next_metadata["resolution_error"] = str(task.error_message or "冲突处理失败")
            else:
                return

            conflict.new_metadata = next_metadata
            db.commit()
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
    
    async def _process_task(self, task: Task):
        """处理单个任务"""
        from .extract_service import ExtractService
        from .filter_service import FilterService
        from .metadata_service import MetadataService
        from .rename_service import RenameService
        from .classifier import SmartClassifier
        
        inferred_rjcode = self._extract_rjcode(str((task.task_metadata or {}).get('inferred_rjcode') or '')) or str((task.task_metadata or {}).get('inferred_rjcode') or '').strip().upper()
        rjcode = self._extract_rjcode(task.source_path) or inferred_rjcode or "未知"
        self._sync_task_rjcode(task, rjcode if rjcode != "未知" else None, source="source_path")
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

                # 步骤0: 预检（先字幕补配，再普通查重）
                logger.info(f"[{rjcode}] 步骤0: 预检")
                task.update_progress(5, "预检中")
                rjcode = self._extract_rjcode(task.source_path)

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
                
                linked_result = {"handled": False, "reason": "not_run", "preview": {}}
                if not rjcode:
                    logger.warning(f"[未知] 无法从文件名提取RJ号，跳过字幕补配预检和预检查重: {os.path.basename(task.source_path)}")
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
                        return
                    logger.info(
                        f"[{rjcode}] 未进入字幕补配预检分支: "
                        f"target={preview.get('target_rjcode', '')} "
                        f"reason={linked_result.get('reason') or preview.get('reason') or 'conditions_not_met'}"
                    )

                    if not config.auto_process.check_duplicate:
                        logger.info(f"[{rjcode}] 预检查重已禁用，跳过")
                    else:
                        is_duplicate = await classifier.check_duplicate_before_extract(rjcode, task, self)
                        logger.info(f"[{rjcode}] 重复检查结果: {is_duplicate}")
                        if is_duplicate:
                            logger.info(f"[{rjcode}] 作品已存在或正在处理中，已添加到问题作品列表")
                            task.status = TaskStatus.WAITING_MANUAL
                            task.update_progress(100, "重复作品，请在问题作品页面处理")
                            task.completed_at = datetime.now()
                            return

                # 步骤1: 解压
                logger.info(f"[{rjcode}] 步骤1: 解压")
                if config.auto_process.extract:
                    task.update_progress(10, "解压中")
                    extracted_path = await extract_service.extract(task)
                    logger.info(f"[{rjcode}] 解压结果路径: {extracted_path}")
                    if not extracted_path:
                        self._record_problem_work_for_extract_failure(
                            task,
                            rjcode,
                            task.error_message or "解压失败"
                        )
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

                task.update_progress(100, "完成")
                task.complete()
                logger.info(f"[{rjcode}] ========== 任务完成 ==========")
                
            elif task.type == TaskType.PROCESS_EXISTING_FOLDER:
                from ..config.settings import get_config
                config = get_config()

                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()

                existing_folder_path = task.source_path
                logger.debug(f"[{rjcode}] 处理已存在文件夹: {existing_folder_path}")

                # 步骤0: 预检重复
                logger.debug(f"[{rjcode}] 步骤0: 预检重复")
                task.update_progress(5, "预检中")
                rjcode = self._extract_rjcode(existing_folder_path)
                logger.debug(f"[{rjcode}] 提取到的RJ号: {rjcode}")
                resolution_mode = str((task.task_metadata or {}).get('existing_folder_resolution') or '').strip().upper()
                if resolution_mode in {"KEEP_NEW", "MERGE"}:
                    logger.info(f"[{rjcode}] 已指定冲突处理方案 {resolution_mode}，跳过重复预检")
                elif config.process_existing.check_duplicate and rjcode and task.auto_classify:
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

                        classifier._add_to_conflict_works(
                            task.id,
                            rjcode,
                            conflict_type,
                            check_result.direct_duplicate['path'] if check_result.direct_duplicate else
                            (check_result.linked_works_found[0]['path'] if check_result.linked_works_found else "未知路径"),
                            existing_folder_path,
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
                        logger.info(f"[{rjcode}] 正在处理中，已添加到问题作品列表")
                        task.status = TaskStatus.WAITING_MANUAL
                        task.update_progress(100, "正在处理中，请在问题作品页面查看")
                        task.completed_at = datetime.now()
                        return
                else:
                    if not config.process_existing.check_duplicate:
                        logger.info(f"[{rjcode}] 步骤[预检重复]已禁用，跳过")

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
                if config.process_existing.import_lrc and hasattr(config, 'asmr_sync') and config.asmr_sync.asmr_subtitle_path:
                    subtitle_base = config.asmr_sync.asmr_subtitle_path
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
                else:
                    if not config.process_existing.import_lrc:
                        logger.info(f"[{rjcode}] 步骤[LRC导入]已禁用，跳过")

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

                task.update_progress(100, "完成")
                task.complete()
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
                elif task.type == TaskType.RJ_SUBTITLE_FETCH:
                    await self._process_rj_subtitle_fetch(task)
                elif task.type == TaskType.LOCAL_LIBRARY_UPLOAD:
                    await self._process_local_library_upload(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_INDEX:
                    await self._process_circle_completion_index(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED:
                    await self._process_circle_completion_refresh_selected(task)
                elif task.type == TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH:
                    task.update_progress(100, "完成")

                # 只有当任务没有被设置为其他状态（如 waiting_retry）时才标记为完成
                if task.status == TaskStatus.PROCESSING:
                    task.complete()
                    logger.info(f"[{rjcode}] ========== 任务完成 ==========")
                
        except asyncio.CancelledError:
            append_progress_log('任务已取消', task.progress, 'warning')
            if not task.is_cancelled():
                task.cancel()
        except Exception as e:
            logger.error(f"[{rjcode}] 任务失败: {e}", exc_info=True)
            if task.type in {TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER}:
                self._record_problem_work_for_task_failure(task, rjcode, str(e))
            task.fail(str(e))
            logger.info(f"[{rjcode}] ========== 任务失败 ==========")
        finally:
            # 操作记录优先写入，避免后续清理/通知异常导致整段 finally 中断而未落库
            try:
                from .activity_log_service import log_task_lifecycle_event

                log_task_lifecycle_event(task)
            except Exception:
                logger.warning("[操作记录] 任务周期记录失败", exc_info=True)
            # 清理任务产生的临时文件（无论成功还是失败）
            self._resolve_retry_extract_conflict(task)
            self._resolve_completed_failure_followups(task)
            self._finalize_conflict_resolution_task(task)
            await self._cleanup_failed_task(task)
            self.processing.discard(task.id)
            # 清除RJ号处理标记
            if task.rjcode:
                self.unmark_rjcode_processing(task.rjcode)
            await self._notify_progress(task)
    
    async def _worker(self):
        """工作线程"""
        while not self._shutdown:
            try:
                # 控制并发数
                while len(self.processing) >= self.max_concurrent:
                    await asyncio.sleep(0.1)
                
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
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
                task.status = TaskStatus.PENDING
                task.current_step = "等待重试"
                await self.queue.put(task)
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
                task.status = TaskStatus.PENDING
                task.current_step = "等待重试"
                asyncio.create_task(self.queue.put(task))
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
                    task.current_step = "手动重试"
                    self.tasks[task.id] = task
                    asyncio.create_task(self.queue.put(task))
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
        task.task_metadata = metadata
        self.processing.discard(task.id)
        if task.rjcode:
            self.unmark_rjcode_processing(task.rjcode)
        task.reset_for_rerun("等待重新抓取字幕")
        self._ensure_task_context(task)
        await self.queue.put(task)
        logger.info("RJ 字幕任务已重新入队: %s", task.id)
        return task

    def pause_task(self, task_id: str):
        """暂停任务"""
        if task_id in self.tasks:
            self.tasks[task_id].pause()
    
    def resume_task(self, task_id: str):
        """恢复任务"""
        if task_id in self.tasks:
            self.tasks[task_id].resume()
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        if task_id in self.tasks:
            self.tasks[task_id].cancel()
    
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
        self.delete_task_snapshot(task_id)
        return True
    
    def update_task_status(self, task_id: str, status: TaskStatus, message: Optional[str] = None):
        """更新任务状态"""
        task = self.tasks.get(task_id)
        if task:
            task.status = status
            if message:
                task.current_step = message
            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.completed_at = datetime.now()
            logger.info(f"任务 {task_id} 状态更新为: {status.value}")
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
        return sorted([t for t in self.tasks.values() if t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and not self._is_hidden_task(t)],
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

    async def _cleanup_failed_task(self, task: Task):
        """清理失败任务产生的临时文件"""
        from ..config.settings import get_config
        
        config = get_config()
        cleaned_paths = []
        
        # 对于 PROCESS_EXISTING_FOLDER 类型，成功完成的任务不需要清理
        # 因为文件夹是直接从已有目录处理的，不是临时文件
        if task.type == TaskType.PROCESS_EXISTING_FOLDER:
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
                shutil.rmtree(task.output_path)
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
                        shutil.rmtree(path)
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
                        shutil.rmtree(potential_path)
                        logger.info(f"清理解压失败残留: {potential_path}")
                    except Exception as e:
                        logger.warning(f"清理解压失败残留失败: {potential_path}, {e}")

    async def _move_file_with_retry(self, source_path: str, dest_path: str, attempts: int = 5, delay_seconds: float = 1.0):
        """带重试地移动文件，缓解 Windows 下解压后句柄释放延迟导致的占用问题"""
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                shutil.move(source_path, dest_path)
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
        """归档完成后清理空源目录，避免分卷目录残留且需要用户手动删除"""
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

        for attempt in range(1, 6):
            try:
                if os.listdir(normalized_source):
                    logger.info(f"源目录非空，跳过自动删除: {normalized_source}")
                    return
                os.rmdir(normalized_source)
                logger.info(f"已自动清理空源目录: {normalized_source}")
                return
            except FileNotFoundError:
                return
            except PermissionError as exc:
                logger.warning(f"删除空源目录时仍被占用，稍后重试 ({attempt}/5): {normalized_source}, {exc}")
            except OSError as exc:
                logger.warning(f"删除空源目录失败，稍后重试 ({attempt}/5): {normalized_source}, {exc}")

            if attempt < 5:
                await asyncio.sleep(1)

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
                    db.commit()
                    
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

        # 检测是否是分卷压缩包，如果是则获取所有分卷文件
        files_to_archive = [source_path]
        source_dir = os.path.dirname(source_path)
        filename = os.path.basename(source_path)

        logger.info(f"[Archive] 开始归档检测 - source_path: {source_path}")
        logger.info(f"[Archive] source_dir: {source_dir}, filename: {filename}")

        # 检查是否是分卷压缩的首卷
        # 格式1: .partX.rar/zip/7z/exe (如 filename.part1.rar) - 带扩展名的分卷
        part_match = re.search(r'^(.*)\.part(\d+)\.(rar|zip|7z|exe)$', filename, re.IGNORECASE)
        # 格式4: .part1, .part2, ... (无扩展名的RAR分卷格式) - 新增支持
        no_ext_part_match = re.search(r'^(.*)\.part(\d+)$', filename, re.IGNORECASE)
        # 格式2: .zip 首卷 + .z01, .z02... 分卷 (ZIP 分卷格式)
        zip_volume_match = re.search(r'^(.*)\.zip$', filename, re.IGNORECASE)
        # 格式3: .7z.001, .7z.002... 分卷 (7z 分卷格式)
        seven_z_volume_match = re.search(r'^(.*)\.7z\.001$', filename, re.IGNORECASE)

        logger.info(f"[Archive] 匹配结果 - part_match: {part_match is not None}, no_ext_part_match: {no_ext_part_match is not None}")
        
        if part_match:
            base_name = part_match.group(1)
            for f in os.listdir(source_dir):
                if re.match(rf'{re.escape(base_name)}\.part\d+\.(rar|zip|7z|exe)$', f, re.IGNORECASE):
                    volume_path = os.path.join(source_dir, f)
                    if volume_path not in files_to_archive:
                        files_to_archive.append(volume_path)
            logger.info(f"检测到分卷压缩包，共 {len(files_to_archive)} 个分卷文件: {[os.path.basename(f) for f in files_to_archive]}")
        elif no_ext_part_match:  # 新增无扩展名分卷格式的处理
            base_name = no_ext_part_match.group(1)
            for f in os.listdir(source_dir):
                if re.match(rf'{re.escape(base_name)}\.part\d+$', f, re.IGNORECASE):
                    volume_path = os.path.join(source_dir, f)
                    if volume_path not in files_to_archive:
                        files_to_archive.append(volume_path)
            logger.info(f"检测到无扩展名分卷压缩包，共 {len(files_to_archive)} 个分卷文件: {[os.path.basename(f) for f in files_to_archive]}")
        elif zip_volume_match:
            # 检查是否存在对应的 .zXX 分卷文件
            base_name = zip_volume_match.group(1)
            volume_files = []
            for f in os.listdir(source_dir):
                if re.match(rf'^{re.escape(base_name)}\.z\d+$', f, re.IGNORECASE):
                    volume_files.append(os.path.join(source_dir, f))
            if volume_files:
                # 找到分卷文件，将所有分卷加入归档列表
                files_to_archive.extend(volume_files)
                logger.info(f"检测到 ZIP 分卷压缩包，共 {len(files_to_archive)} 个文件: {[os.path.basename(f) for f in files_to_archive]}")
        elif seven_z_volume_match:
            # 检查是否存在对应的 .7z.XXX 分卷文件
            base_name = seven_z_volume_match.group(1)
            volume_files = []
            for f in os.listdir(source_dir):
                if re.match(rf'^{re.escape(base_name)}\.7z\.\d+$', f, re.IGNORECASE):
                    volume_files.append(os.path.join(source_dir, f))
            if volume_files:
                # 找到分卷文件，将所有分卷加入归档列表（排除已在列表中的首卷）
                for vf in volume_files:
                    if vf not in files_to_archive:
                        files_to_archive.append(vf)
                logger.info(f"检测到 7z 分卷压缩包，共 {len(files_to_archive)} 个文件: {[os.path.basename(f) for f in files_to_archive]}")
        
        # 移动所有文件
        archived_files = []

        try:
            # 确保已处理目录存在
            os.makedirs(processed_dir, exist_ok=True)

            # 移动所有分卷文件（或单个文件）
            for file_path in files_to_archive:
                filename = os.path.basename(file_path)
                dest_path = os.path.join(processed_dir, filename)
                
                # 处理重名
                counter = 1
                original_dest = dest_path
                while os.path.exists(dest_path):
                    name, ext = os.path.splitext(filename)
                    dest_path = os.path.join(processed_dir, f"{name}({counter}){ext}")
                    counter += 1

                # 移动文件，允许在 7z 刚退出时等待句柄释放
                await self._move_file_with_retry(file_path, dest_path)
                logger.info(f"压缩包已归档: {file_path} -> {dest_path}")
                archived_files.append((filename, dest_path, file_path))

            # 记录主文件（第一个分卷或唯一文件）到数据库
            if archived_files:
                main_filename, main_dest_path, main_source_path = archived_files[0]
                rjcode = self._extract_rjcode(main_source_path) or str((task.task_metadata or {}).get('inferred_rjcode') or '').strip().upper()
                file_size = os.path.getsize(main_dest_path)

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
                            processed_at=now,  # 显式设置处理时间
                            process_count=1,
                            task_id=task.id,
                            status='completed'
                        )
                        db.add(archive_record)
                        logger.info(f"已记录压缩包归档信息: {main_filename}, 时间: {now}")
                    
                    db.commit()
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

                shutil.move(renamed_path, final_path)
                task.output_path = final_path
                logger.info(f"[{rjcode}] 移动到: {final_path}")

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

                    shutil.move(subtitle_folder, dest_subtitle_path)
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
                    shutil.rmtree(download_dir)
                    logger.info(f"[{rjcode}] 清理临时目录: {download_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"[{rjcode}] 清理临时目录失败: {cleanup_error}")

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

        rjcode = task.task_metadata.get('rjcode') or self._extract_rjcode(folder_path) or "未知"
        task.rjcode = rjcode

        logger.info(f"[{rjcode}] 开始 RJ 字幕抓取任务: {folder_path}")

        try:
            task.update_progress(5, "准备扫描 RJ 文件夹")
            task.task_metadata['download_files'] = []
            task.task_metadata['progress_log'] = []

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
                task.task_metadata.update({
                    'force_rerun_deleted_subtitles': deleted_subtitles,
                    'force_rerun_cleared_subtitle_dir': cleanup_result.get('subtitle_dir', ''),
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
                kikoeru_state = await rj_service.check_kikoeru_existing_subtitles(rjcode)
                task.task_metadata.update({
                    'kikoeru_checked_rjcode': kikoeru_state.get('checked_rjcode', rjcode),
                    'kikoeru_has_work': bool(kikoeru_state.get('has_work')),
                    'kikoeru_has_existing_subtitles': bool(kikoeru_state.get('has_existing_subtitles')),
                    'kikoeru_matched_rjcode': kikoeru_state.get('matched_rjcode', ''),
                    'kikoeru_subtitle_file_count': int(kikoeru_state.get('subtitle_file_count') or 0),
                    'kikoeru_subtitle_check_source': kikoeru_state.get('subtitle_check_source', ''),
                })
                if bool(kikoeru_state.get('has_existing_subtitles')):
                    matched_rjcode = str(kikoeru_state.get('matched_rjcode') or rjcode).upper()
                    subtitle_file_count = int(kikoeru_state.get('subtitle_file_count') or 0)
                    skip_message = f"Kikoeru 已有字幕（{matched_rjcode}"
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
            })

            deduped_count = int(result.get('content_deduped_count') or 0)
            if deduped_count > 0:
                append_progress_log(f"已按内容合并 {deduped_count} 个完全重复字幕", task.progress)

            if not result.get('success'):
                error_message = result.get('error', 'RJ 字幕抓取失败')
                append_progress_log(error_message, task.progress, 'error')
                task.fail(error_message)
                return

            if result.get('awaiting_manual_match'):
                task.progress = 100
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                task.current_step = '已抓取原始字幕，等待筛选与匹配'
                append_progress_log(task.current_step, 100)
                logger.info(f'[{rjcode}] RJ 字幕原始抓取完成，等待用户筛选与匹配')
                return

            written_count = len(result.get('written_files', []))
            skipped_count = len(result.get('skipped_files', []))
            unmatched_count = len(result.get('match_result', {}).get('unmatched_audio', []))
            task.update_progress(100, f"完成，写入 {written_count} 个字幕")
            task.complete()
            if result.get('partial'):
                task.current_step = f"部分完成，写入 {written_count}，跳过 {skipped_count}，未匹配音频 {unmatched_count}"
            logger.info(f"[{rjcode}] RJ 字幕抓取完成，写入 {written_count} 个字幕")

        except Exception as e:
            logger.error(f"[{rjcode}] RJ 字幕抓取任务失败: {e}", exc_info=True)
            task.fail(str(e))

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
                batch_results.append({
                    'circle_query': circle_query,
                    'success': False,
                    'error_message': str(exc),
                })
                append_progress_log(f"[{batch_index}/{total_queries}] 社团索引失败：{circle_query} - {exc}", None, 'warning')

        if not success_count and failed_count:
            raise RuntimeError(f"批量建立失败：共 {failed_count} 个社团建立失败")

        if last_successful_result is None:
            raise RuntimeError("社团索引未生成有效结果")

        summary_step = "批量社团索引完成" if is_batch else "社团索引完成"
        task.task_metadata = {
            **(task.task_metadata or {}),
            'circle_query': str((last_successful_result.get('summary') or {}).get('circle_name') or normalized_circle_queries[0]),
            'circle_id': str(last_successful_result.get('circle_id') or ''),
            'circle_name': str(((last_successful_result.get('summary') or {}).get('circle_name')) or normalized_circle_queries[0]),
            'index_result': last_successful_result,
            'index_batch_results': batch_results,
            'indexed_counts': dict(last_successful_result.get('indexed_counts') or {}),
            'index_meta': {
                **dict((task.task_metadata or {}).get('index_meta') or {}),
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

    async def _process_local_library_upload(self, task: Task):
        from .circle_completion_service import get_circle_completion_service
        from .library_manager import get_library_manager

        task.task_metadata = dict(task.task_metadata or {})
        task.task_metadata.setdefault("upload_files", [])
        task.task_metadata.setdefault("uploaded_files", [])
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
            "last_non_zero_speed_bytes_per_sec": 0,
            "current_file_name": "",
            "current_relative_path": "",
            "current_source_dir": "",
        }

        task.update_progress(1, "准备上传目录")
        append_progress_log(f"准备上传 {len(selected_paths)} 个目录", 1)

        manager = get_library_manager()
        uploaded = []
        uploaded_rows = []
        runtime = dict(task.task_metadata.get("upload_runtime") or {})

        def progress_callback(snapshot: dict):
            runtime.update(snapshot or {})
            try:
                speed_value = int(runtime.get("speed_bytes_per_sec") or 0)
            except Exception:
                speed_value = 0
            if speed_value > 0:
                runtime["last_non_zero_speed_bytes_per_sec"] = speed_value
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
            total_bytes_current = max(0, int(runtime.get("current_file_total_bytes") or 0))
            uploaded_bytes_current = max(0, int(runtime.get("current_file_uploaded_bytes") or 0))
            if current_relative_path:
                rows = list(task.task_metadata.get("upload_files") or [])
                for row in rows:
                    if str(row.get("relative_path") or "").strip() != current_relative_path:
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
            rows = list(task.task_metadata.get("upload_files") or [])
            for row in rows:
                if str(row.get("relative_path") or "").strip() != relative_path:
                    continue
                row["status"] = "completed"
                row["uploaded_bytes"] = int(row.get("size") or 0)
                row["progress"] = 100
                break
            task.task_metadata["upload_files"] = rows

        total_dirs = len(source_entries)
        for index, entry in enumerate(source_entries, start=1):
            source_dir = str(entry.get("source_path") or "").strip()
            relative_target_dir = str(entry.get("relative_target_dir") or "").strip() or build_relative_target_dir()
            source_name = os.path.basename(os.path.abspath(source_dir))
            step_progress = max(1, min(95, int(((index - 1) / max(total_dirs, 1)) * 100)))
            task.update_progress(step_progress, f"上传目录 {index}/{total_dirs}: {source_name}")
            append_progress_log(f"开始上传目录 {source_name}", step_progress)
            if relative_target_dir:
                task.task_metadata["target_path"] = relative_target_dir.replace("\\", "/")
            target_path = await manager.upload_directory_to_library(
                target_library_id,
                source_dir,
                relative_target_dir,
                delete_source_on_success=True,
                progress_callback=progress_callback,
                file_completed_callback=file_completed_callback,
            )
            uploaded.append({"source": source_dir, "target": target_path})
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
    else:
        _task_engine.set_max_concurrent(configured_max_workers)
    return _task_engine
