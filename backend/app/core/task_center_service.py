import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .linked_subtitle_import_service import get_linked_subtitle_import_service
from .task_engine import Task, TaskStatus, TaskType, get_task_engine
from ..models.database import ConflictWork, SessionLocal

logger = logging.getLogger(__name__)


class TaskCenterService:
    """统一聚合业务任务与引擎任务，供任务中心页面使用。"""

    # detail 模式给 get_item / 详情面板用，需要完整 metadata + 文件树
    CACHE_TTL_SECONDS = 1.2
    # summary 模式给 list / overview 用，可容忍稍长的延迟换取明显更轻的开销
    SUMMARY_CACHE_TTL_SECONDS = 2.5
    # pending / conflict 走数据库 + 可能有远程查询，单独缓存避免每次重建都触发
    PENDING_CACHE_TTL_SECONDS = 5.0
    CONFLICT_CACHE_TTL_SECONDS = 3.0

    # summary 模式输出的 details.metadata 仅保留这些键，避免对完整 task_metadata 做 json_safe 深拷贝
    # 注意：必须涵盖任务中心内部 dedup / merge 逻辑会读的字段，否则会破坏行为
    SUMMARY_METADATA_KEYS: tuple = (
        # 既有 _summary_item 已使用
        "recovered_notice",
        "extract_stage",
        "archive_size",
        "extract_started_at",
        "extract_finished_at",
        "nested_archive_count",
        "verify_mode",
        "failure_stage",
        "conflict_resolution_action",
        "retry_result",
        "retry_completed_at",
        "manual_retry_password_requested",
        "linked_conflict_retrying",
        # dedup / superseded 判定
        "superseded_by_task_id",
        "recovered_failure_ids",
        "recovered_failure_count",
        "recovered_conflict_count",
        "task_domain",
        # 联动字幕补配 / 串联流水线 merge
        "source_mode",
        "source_archive_path",
        "manual_match_completed",
        "linked_workbench_applied",
        # 前端 list 页 getTaskSummary / getOutputPath 直接读
        "subtitle_dir",
    )

    # summary 模式下 pending preview 仅保留这些键
    SUMMARY_PREVIEW_KEYS: tuple = (
        "source_rjcode",
        "target_rjcode",
        "subtitle_count",
        "candidate_count",
        "ready_candidate_count",
        "selected_candidate",
        "execute_reason",
        "source_label",
    )

    DOMAIN_LABELS = {
        "all": "全部",
        "import": "导入处理",
        "existing_folder": "已有文件夹",
        "rj_subtitle": "RJ 字幕",
        "subtitle_import": "字幕补配",
        "asmr_sync": "ASMR 同步",
        "upload": "库存上传",
        "circle_completion": "社团补全",
        "system": "系统任务",
    }

    STATUS_LABELS = {
        TaskStatus.PENDING.value: "待处理",
        TaskStatus.PROCESSING.value: "处理中",
        TaskStatus.PAUSED.value: "已暂停",
        TaskStatus.WAITING_MANUAL.value: "等待人工",
        TaskStatus.WAITING_RETRY.value: "等待重试",
        TaskStatus.COMPLETED.value: "已完成",
        TaskStatus.FAILED.value: "失败",
    }

    STATUS_PRIORITY = {
        TaskStatus.PROCESSING.value: 0,
        TaskStatus.WAITING_MANUAL.value: 1,
        TaskStatus.WAITING_RETRY.value: 2,
        TaskStatus.PENDING.value: 3,
        TaskStatus.PAUSED.value: 4,
        TaskStatus.FAILED.value: 5,
        TaskStatus.COMPLETED.value: 6,
    }

    DOMAIN_PRIORITY = {
        "import": 0,
        "existing_folder": 1,
        "rj_subtitle": 2,
        "subtitle_import": 3,
        "asmr_sync": 4,
        "upload": 5,
        "circle_completion": 6,
        "system": 7,
    }

    TASK_TYPE_TO_DOMAIN = {
        TaskType.AUTO_PROCESS: "import",
        TaskType.PROCESS_EXISTING_FOLDER: "existing_folder",
        TaskType.RJ_SUBTITLE_FETCH: "rj_subtitle",
        TaskType.ASMR_SYNC_DOWNLOAD: "asmr_sync",
        TaskType.LOCAL_LIBRARY_UPLOAD: "upload",
        TaskType.CIRCLE_COMPLETION_INDEX: "circle_completion",
        TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH: "circle_completion",
        TaskType.EXTRACT: "system",
        TaskType.FILTER: "system",
        TaskType.METADATA: "system",
        TaskType.RENAME: "system",
    }

    DOMAIN_ROUTE_HINT = {
        "library": "/library",
        "import": "/library",
        "existing_folder": "/existing-folders",
        "rj_subtitle": "/library",
        "subtitle_import": "/subtitle-import",
        "asmr_sync": "/asmr-sync",
        "upload": "/library",
        "circle_completion": "/circle-completion",
        "system": "/tasks",
    }

    def __init__(self):
        # detail 模式缓存（给 get_item 用）
        self._detail_cache: Optional[List[Dict[str, Any]]] = None
        self._detail_cache_signature: Optional[Tuple[Any, ...]] = None
        self._detail_cache_at = 0.0
        # summary 模式缓存（给 list / overview 用）
        self._summary_cache: Optional[List[Dict[str, Any]]] = None
        self._summary_cache_signature: Optional[Tuple[Any, ...]] = None
        self._summary_cache_at = 0.0
        # 子集缓存：pending imports / active conflicts，单独 TTL，避免每次重建都查库
        self._pending_cache: Optional[List[Dict[str, Any]]] = None
        self._pending_cache_at = 0.0
        self._conflict_cache: Optional[List[ConflictWork]] = None
        self._conflict_cache_at = 0.0

    def _safe_iso(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    def _safe_text(self, value: Any) -> str:
        return str(value or "").strip()

    def _normalize_rjcode(self, value: Any) -> str:
        text = self._safe_text(value).upper()
        if not text:
            return ""
        import re
        match = re.search(r"(?:RJ)+\d{4,}", text, re.IGNORECASE)
        if match:
            number_match = re.search(r"\d{4,}", match.group(0))
            if number_match:
                return f"RJ{number_match.group(0)}"
        match = re.search(r"RJ\d{4,}", text, re.IGNORECASE)
        if match:
            return match.group(0).upper()
        return text

    def _basename(self, value: Any) -> str:
        normalized = self._safe_text(value).rstrip("\\/")
        if not normalized:
            return ""
        return os.path.basename(normalized) or normalized

    def _format_bytes(self, value: Any) -> str:
        try:
            size = max(0, int(float(value or 0)))
        except Exception:
            return self._safe_text(value)
        if size < 1024:
            return f"{size} B"
        units = ["KB", "MB", "GB", "TB"]
        current = size / 1024
        unit_index = 0
        while current >= 1024 and unit_index < len(units) - 1:
            current /= 1024
            unit_index += 1
        return f"{current:.2f} {units[unit_index]}"

    def _snapshot_directory_items(self, root_path: str, limit: int = 600) -> List[Dict[str, Any]]:
        normalized_root = self._safe_text(root_path)
        if not normalized_root or not os.path.isdir(normalized_root):
            return []

        items: List[Dict[str, Any]] = []
        try:
            for current_root, dirs, files in os.walk(normalized_root):
                relative_root = os.path.relpath(current_root, normalized_root).replace("\\", "/")
                if relative_root == ".":
                    relative_root = ""
                dirs.sort()
                files.sort()

                for dir_name in dirs:
                    relative_path = f"{relative_root}/{dir_name}".strip("/")
                    items.append({
                        "path": os.path.join(current_root, dir_name),
                        "relative_path": relative_path,
                        "name": dir_name,
                        "type": "dir",
                        "size": None,
                    })
                    if len(items) >= limit:
                        return items

                for file_name in files:
                    file_path = os.path.join(current_root, file_name)
                    relative_path = f"{relative_root}/{file_name}".strip("/")
                    try:
                        size = int(os.path.getsize(file_path)) if os.path.exists(file_path) else 0
                    except Exception:
                        size = 0
                    items.append({
                        "path": file_path,
                        "relative_path": relative_path,
                        "name": file_name,
                        "type": "file",
                        "size": size,
                    })
                    if len(items) >= limit:
                        return items
        except Exception:
            logger.debug("任务中心回填文件树失败: %s", normalized_root, exc_info=True)
        return items

    def _build_summary_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """summary 模式专用：只挑 SUMMARY_METADATA_KEYS 里面的键做 json_safe，避免全量深拷贝。"""
        if not isinstance(metadata, dict) or not metadata:
            return {}
        out: Dict[str, Any] = {}
        for key in self.SUMMARY_METADATA_KEYS:
            if key in metadata:
                out[key] = self._json_safe(metadata.get(key))
        return out

    def _build_summary_preview(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        """summary 模式下 pending preview 只保留前端 list 页会读的字段。"""
        if not isinstance(preview, dict) or not preview:
            return {}
        out: Dict[str, Any] = {}
        for key in self.SUMMARY_PREVIEW_KEYS:
            if key in preview:
                out[key] = self._json_safe(preview.get(key))
        return out

    def _ensure_file_tree_metadata(self, metadata: Dict[str, Any], resolved_target_path: str, source_path: str) -> Dict[str, Any]:
        if metadata.get("file_tree_items"):
            return metadata

        candidate_paths: List[str] = []
        for candidate in (
            metadata.get("final_output_path"),
            metadata.get("target_path"),
            resolved_target_path,
            metadata.get("folder_path"),
            source_path,
        ):
            normalized = self._safe_text(candidate)
            if not normalized or normalized in candidate_paths:
                continue
            if os.path.isdir(normalized):
                candidate_paths.append(normalized)

        for candidate in candidate_paths:
            snapshot = self._snapshot_directory_items(candidate)
            if snapshot:
                enriched = dict(metadata)
                enriched["file_tree_items"] = snapshot
                return enriched

        return metadata

    def _format_duration_ms(self, value: Any) -> str:
        try:
            ms = max(0, int(float(value or 0)))
        except Exception:
            return self._safe_text(value)
        if ms < 1000:
            return f"{ms} ms"
        total_seconds = int(round(ms / 1000))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours}时{minutes}分{seconds}秒"
        if minutes > 0:
            return f"{minutes}分{seconds}秒"
        return f"{seconds}秒"

    def _append_metric(self, items: List[Dict[str, str]], label: str, value: Any):
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        if isinstance(value, (list, tuple, set)) and not value:
            return
        items.append({"label": label, "value": str(value)})

    def _last_timestamp(self, item: Dict[str, Any]) -> float:
        for field in ("completed_at", "started_at", "created_at"):
            raw_value = self._safe_text(item.get(field))
            if not raw_value:
                continue
            try:
                return datetime.fromisoformat(raw_value).timestamp()
            except ValueError:
                continue
        return 0.0

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(key): self._json_safe(current)
                for key, current in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(current) for current in value]
        return str(value)

    def _summary_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """任务列表/概览用轻量结构，避免轮询时反复传大 metadata。"""
        details = dict(item.get("details") or {})
        metadata = dict(details.get("metadata") or {}) if isinstance(details.get("metadata"), dict) else {}
        summary_details: Dict[str, Any] = {}
        for key in (
            "recovered_notice",
            "extract_stage",
            "archive_size",
            "extract_started_at",
            "extract_finished_at",
            "nested_archive_count",
            "verify_mode",
            "failure_stage",
            "conflict_resolution_action",
            "retry_result",
            "retry_completed_at",
            "manual_retry_password_requested",
            "linked_conflict_retrying",
        ):
            if key in metadata:
                summary_details.setdefault("metadata", {})[key] = self._json_safe(metadata.get(key))

        return {
            "id": self._safe_text(item.get("id")),
            "entity_id": self._safe_text(item.get("entity_id")),
            "engine_task_id": self._safe_text(item.get("engine_task_id")) or None,
            "record_id": self._safe_text(item.get("record_id")) or None,
            "domain": self._safe_text(item.get("domain")),
            "domain_label": self._safe_text(item.get("domain_label")),
            "kind": self._safe_text(item.get("kind")),
            "kind_label": self._safe_text(item.get("kind_label")),
            "title": self._safe_text(item.get("title")),
            "subtitle": self._safe_text(item.get("subtitle")),
            "source_label": self._safe_text(item.get("source_label")),
            "source_page": self._safe_text(item.get("source_page")),
            "source_action": self._safe_text(item.get("source_action")),
            "route_hint": self._safe_text(item.get("route_hint")),
            "status": self._safe_text(item.get("status")),
            "status_label": self._safe_text(item.get("status_label")),
            "progress": int(item.get("progress") or 0),
            "current_step": self._safe_text(item.get("current_step")),
            "error_message": self._safe_text(item.get("error_message")),
            "source_path": self._safe_text(item.get("source_path")),
            "target_path": self._safe_text(item.get("target_path")),
            "rjcode": self._safe_text(item.get("rjcode")),
            "created_at": item.get("created_at"),
            "started_at": item.get("started_at"),
            "completed_at": item.get("completed_at"),
            "metrics": list(item.get("metrics") or [])[:8],
            "actions": list(item.get("actions") or []),
            "details": summary_details,
        }

    def _engine_signature(self) -> Tuple[Any, ...]:
        """内存里就能算出的引擎任务签名，避免每次缓存校验都查库。

        变化敏感字段（status / progress / current_step / error / completed_at）足以驱动
        UI 刷新；conflict / pending 走自己的 TTL 缓存，整体缓存仍受 TTL 兜底。
        """
        engine = get_task_engine()
        tasks = engine.get_all_tasks()
        task_signature = tuple(
            (
                task.id,
                getattr(getattr(task, "status", None), "value", str(getattr(task, "status", ""))),
                int(getattr(task, "progress", 0) or 0),
                self._safe_text(getattr(task, "current_step", "")),
                self._safe_text(getattr(task, "error_message", "")),
                self._safe_iso(getattr(task, "completed_at", None)),
            )
            for task in tasks
        )
        return (
            len(tasks),
            task_signature,
            len(getattr(engine, "processing", set()) or set()),
        )

    def _item_metadata(self, item: Dict[str, Any]) -> Dict[str, Any]:
        details = dict(item.get("details") or {})
        metadata = details.get("metadata") or {}
        return dict(metadata) if isinstance(metadata, dict) else {}

    def _merge_metric_items(self, base: List[Dict[str, str]], extra: List[Dict[str, str]]) -> List[Dict[str, str]]:
        merged: List[Dict[str, str]] = []
        seen_labels: set[str] = set()
        for collection in (base or [], extra or []):
            for item in collection:
                if not isinstance(item, dict):
                    continue
                label = self._safe_text(item.get("label"))
                value = self._safe_text(item.get("value"))
                if not label or not value or label in seen_labels:
                    continue
                seen_labels.add(label)
                merged.append({"label": label, "value": value})
        return merged

    def _normalize_conflict_metadata(self, raw_metadata: Any) -> Dict[str, Any]:
        if isinstance(raw_metadata, dict):
            return dict(raw_metadata)
        if raw_metadata in (None, "", []):
            return {}
        if isinstance(raw_metadata, str):
            try:
                import json

                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {"raw_metadata": raw_metadata}
            return {"raw_metadata": raw_metadata}
        try:
            return dict(raw_metadata)
        except Exception:
            return {"raw_metadata": str(raw_metadata)}

    def _conflict_type_label(self, conflict_type: str) -> str:
        mapping = {
            "DUPLICATE": "重复作品",
            "LANGUAGE_VARIANT": "语言版本冲突",
            "MULTIPLE_VERSIONS": "多版本冲突",
            "LINKED_WORK": "关联作品冲突",
            "EXTRACT_FAILED": "解压失败",
            "PROCESS_FAILED": "处理失败",
        }
        normalized = self._safe_text(conflict_type).upper()
        return mapping.get(normalized, normalized or "问题作品")

    def _serialize_conflict_item(self, conflict: ConflictWork) -> Dict[str, Any]:
        metadata = self._normalize_conflict_metadata(getattr(conflict, "new_metadata", None))
        conflict_type = self._safe_text(getattr(conflict, "conflict_type", "")).upper()
        raw_status = self._safe_text(getattr(conflict, "status", "")).upper()
        display_status = TaskStatus.PROCESSING.value if raw_status == "PROCESSING" else TaskStatus.WAITING_MANUAL.value
        resolution_action = self._safe_text(metadata.get("resolution_action")).upper()
        is_retrying = display_status == TaskStatus.PROCESSING.value and resolution_action == "RETRY"
        linked_engine_task = None
        linked_task_id = (
            self._safe_text(metadata.get("resolution_task_id"))
            or self._safe_text(getattr(conflict, "task_id", ""))
        )
        if linked_task_id:
            try:
                linked_engine_task = get_task_engine().get_task(linked_task_id)
            except Exception:
                linked_engine_task = None
        title = self._normalize_rjcode(getattr(conflict, "rjcode", "")) or self._basename(getattr(conflict, "new_path", "")) or "问题作品"
        error_message = self._safe_text(metadata.get("error_message"))
        subtitle = error_message or self._basename(getattr(conflict, "new_path", ""))
        metrics: List[Dict[str, str]] = []
        self._append_metric(metrics, "问题类型", self._conflict_type_label(conflict_type))
        self._append_metric(metrics, "来源", "压缩包" if os.path.isfile(str(getattr(conflict, "new_path", "") or "")) else "目录")
        self._append_metric(metrics, "目标 RJ", self._normalize_rjcode(getattr(conflict, "rjcode", "")))

        if is_retrying:
            current_step = self._safe_text(getattr(linked_engine_task, "current_step", "")) or "正在按问题作品重试"
            status_label = "重试中"
            progress = int(getattr(linked_engine_task, "progress", 0) or 0)
            subtitle = self._safe_text(getattr(linked_engine_task, "current_step", "")) or subtitle
            actions = self._build_engine_actions(linked_engine_task, "import") if linked_engine_task else []
        else:
            current_step = error_message or (
                "等待在问题作品页处理中" if display_status == TaskStatus.WAITING_MANUAL.value else "问题作品处理中"
            )
            status_label = self.STATUS_LABELS[display_status]
            progress = 0
            actions = []

        return {
            "id": f"conflict:{self._safe_text(getattr(conflict, 'id', ''))}",
            "entity_id": self._safe_text(getattr(conflict, "id", "")),
            "engine_task_id": self._safe_text(getattr(conflict, "task_id", "")),
            "record_id": self._safe_text(getattr(conflict, "id", "")),
            "domain": "import",
            "domain_label": self.DOMAIN_LABELS["import"],
            "kind": "conflict_work",
            "kind_label": self._conflict_type_label(conflict_type),
            "title": title,
            "subtitle": subtitle,
            "source_label": "问题作品 / 重试" if is_retrying else "问题作品 / 待处理",
            "source_page": "conflicts",
            "source_action": "conflict_resolution",
            "route_hint": "/conflicts",
            "status": display_status,
            "status_label": status_label,
            "progress": progress,
            "current_step": current_step,
            "error_message": error_message,
            "source_path": self._safe_text(getattr(conflict, "new_path", "")),
            "target_path": self._safe_text(getattr(conflict, "existing_path", "")),
            "rjcode": self._normalize_rjcode(getattr(conflict, "rjcode", "")),
            "created_at": self._safe_iso(getattr(conflict, "created_at", None)),
            "started_at": None,
            "completed_at": None,
            "metrics": metrics,
            "actions": actions,
            "details": {
                "metadata": self._json_safe(metadata),
                "retrying": is_retrying,
                "conflict": {
                    "id": self._safe_text(getattr(conflict, "id", "")),
                    "task_id": self._safe_text(getattr(conflict, "task_id", "")),
                    "conflict_type": conflict_type,
                    "existing_path": self._safe_text(getattr(conflict, "existing_path", "")),
                    "new_path": self._safe_text(getattr(conflict, "new_path", "")),
                    "status": raw_status,
                },
            },
        }

    def _safe_serialize_conflict_item(self, conflict: ConflictWork) -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_conflict_item(conflict)
        except Exception:
            logger.exception(
                "[任务中心] 序列化问题作品失败，已跳过: conflict_id=%s task_id=%s type=%s",
                getattr(conflict, "id", ""),
                getattr(conflict, "task_id", ""),
                getattr(conflict, "conflict_type", ""),
            )
            return None

    def _load_active_conflicts(self) -> List[ConflictWork]:
        db = SessionLocal()
        try:
            return (
                db.query(ConflictWork)
                .filter(
                    ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                    ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
                )
                .order_by(ConflictWork.created_at.desc())
                .all()
            )
        finally:
            db.close()

    def _merge_conflict_pipeline_items(
        self,
        items: List[Dict[str, Any]],
        conflict_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        parent_by_engine_id: Dict[str, Dict[str, Any]] = {}
        merged_conflict_ids: set[str] = set()

        for item in items:
            if not self._safe_text(item.get("id")).startswith("engine:"):
                continue
            engine_task_id = self._safe_text(item.get("engine_task_id")) or self._safe_text(item.get("entity_id"))
            if engine_task_id:
                parent_by_engine_id[engine_task_id] = item

        for conflict_item in conflict_items:
            engine_task_id = self._safe_text(conflict_item.get("engine_task_id"))
            parent = parent_by_engine_id.get(engine_task_id)
            if not parent:
                continue

            parent_status = self._safe_text(parent.get("status"))
            conflict_details = dict(conflict_item.get("details") or {})
            is_retrying = bool(conflict_details.get("retrying"))
            if parent_status not in {TaskStatus.WAITING_MANUAL.value, TaskStatus.FAILED.value} and not is_retrying:
                merged_conflict_ids.add(self._safe_text(conflict_item.get("id")))
                continue

            parent["status"] = self._safe_text(conflict_item.get("status")) or parent.get("status")
            parent["status_label"] = self._safe_text(conflict_item.get("status_label")) or parent.get("status_label")
            parent["kind"] = self._safe_text(conflict_item.get("kind")) or parent.get("kind")
            parent["kind_label"] = self._safe_text(conflict_item.get("kind_label")) or parent.get("kind_label")
            parent["route_hint"] = self._safe_text(conflict_item.get("route_hint")) or parent.get("route_hint")
            parent["current_step"] = self._safe_text(conflict_item.get("current_step")) or parent.get("current_step")
            parent["error_message"] = self._safe_text(conflict_item.get("error_message")) or parent.get("error_message")
            parent["progress"] = max(int(parent.get("progress") or 0), int(conflict_item.get("progress") or 0))
            parent["metrics"] = self._merge_metric_items(parent.get("metrics") or [], conflict_item.get("metrics") or [])
            parent["actions"] = list(conflict_item.get("actions") or [])

            parent_details = dict(parent.get("details") or {})
            parent_metadata = self._item_metadata(parent)
            linked_conflict = dict(conflict_details.get("conflict") or {})
            parent_metadata["linked_conflict_id"] = self._safe_text(linked_conflict.get("id"))
            parent_metadata["linked_conflict_type"] = self._safe_text(linked_conflict.get("conflict_type"))
            parent_metadata["linked_conflict_status"] = self._safe_text(linked_conflict.get("status"))
            parent_metadata["linked_conflict_retrying"] = bool((conflict_item.get("details") or {}).get("retrying"))
            parent_details["metadata"] = self._json_safe(parent_metadata)
            parent_details["conflict"] = self._json_safe(linked_conflict)
            parent["details"] = parent_details
            merged_conflict_ids.add(self._safe_text(conflict_item.get("id")))

        passthrough_conflicts = [
            item for item in conflict_items
            if self._safe_text(item.get("id")) not in merged_conflict_ids
        ]
        return items + passthrough_conflicts

    def _compose_import_step(self, parent: Dict[str, Any], linked_item: Dict[str, Any]) -> str:
        parent_step = self._safe_text(parent.get("current_step"))
        linked_step = self._safe_text(linked_item.get("current_step"))
        if linked_step:
            return linked_step
        return parent_step or "等待中"

    def _merge_linked_subtitle_pipeline_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        parent_by_engine_id: Dict[str, Dict[str, Any]] = {}
        parent_by_source_path: Dict[str, Dict[str, Any]] = {}
        merged_item_ids: set[str] = set()

        for item in items:
            if not self._safe_text(item.get("id")).startswith("engine:"):
                continue
            if self._safe_text(item.get("domain")) not in ("import", "subtitle_import"):
                continue
            metadata = self._item_metadata(item)
            source_mode = self._safe_text(metadata.get("source_mode"))
            if source_mode != "linked_translation_archive_pending":
                continue
            engine_task_id = self._safe_text(item.get("engine_task_id")) or self._safe_text(item.get("entity_id"))
            if engine_task_id:
                parent_by_engine_id[engine_task_id] = item
            source_path = self._safe_text(item.get("source_path"))
            if source_path:
                parent_by_source_path[os.path.abspath(source_path)] = item

        for item in items:
            item_id = self._safe_text(item.get("id"))
            if item_id.startswith("subtitle-pending:"):
                engine_task_id = self._safe_text(item.get("engine_task_id"))
                parent = parent_by_engine_id.get(engine_task_id)
                if not parent:
                    continue
                parent["status"] = TaskStatus.WAITING_MANUAL.value
                parent["status_label"] = self.STATUS_LABELS[TaskStatus.WAITING_MANUAL.value]
                parent["current_step"] = self._compose_import_step(parent, item)
                parent["route_hint"] = self.DOMAIN_ROUTE_HINT["subtitle_import"]
                parent["actions"] = ["open_subtitle_import"]
                parent["progress"] = max(int(parent.get("progress") or 0), 100)
                parent["metrics"] = self._merge_metric_items(parent.get("metrics") or [], item.get("metrics") or [])
                parent_details = dict(parent.get("details") or {})
                parent_metadata = self._item_metadata(parent)
                parent_metadata["merged_subtitle_pending"] = True
                parent_details["metadata"] = self._json_safe(parent_metadata)
                parent_details["pending_preview"] = self._json_safe((item.get("details") or {}).get("preview") or {})
                parent["details"] = parent_details
                merged_item_ids.add(item_id)
                continue

            if not item_id.startswith("engine:"):
                continue
            metadata = self._item_metadata(item)
            source_mode = self._safe_text(metadata.get("source_mode"))
            if source_mode != "linked_translation_archive_import":
                continue
            source_archive_path = self._safe_text(metadata.get("source_archive_path"))
            parent = None
            if source_archive_path:
                try:
                    parent = parent_by_source_path.get(os.path.abspath(source_archive_path))
                except Exception:
                    parent = None
            if not parent:
                continue

            parent["status"] = self._safe_text(item.get("status")) or parent.get("status")
            parent["status_label"] = self._safe_text(item.get("status_label")) or parent.get("status_label")
            parent["current_step"] = self._compose_import_step(parent, item)
            parent["target_path"] = self._safe_text(item.get("target_path")) or self._safe_text(parent.get("target_path"))
            parent["completed_at"] = item.get("completed_at") or parent.get("completed_at")
            parent["started_at"] = item.get("started_at") or parent.get("started_at")
            parent["progress"] = max(int(parent.get("progress") or 0), int(item.get("progress") or 0))
            parent["metrics"] = self._merge_metric_items(parent.get("metrics") or [], item.get("metrics") or [])

            child_metadata = metadata
            if bool(child_metadata.get("manual_match_completed")) or bool(child_metadata.get("linked_workbench_applied")):
                parent["route_hint"] = self.DOMAIN_ROUTE_HINT["library"]
                parent["actions"] = []
            else:
                parent["status"] = TaskStatus.WAITING_MANUAL.value
                parent["status_label"] = self.STATUS_LABELS[TaskStatus.WAITING_MANUAL.value]
                parent["route_hint"] = self.DOMAIN_ROUTE_HINT["subtitle_import"]
                parent["actions"] = ["open_subtitle_import"]

            parent_details = dict(parent.get("details") or {})
            parent_metadata = self._item_metadata(parent)
            parent_metadata["merged_subtitle_task_id"] = self._safe_text(item.get("engine_task_id"))
            parent_metadata["merged_subtitle_source_mode"] = source_mode
            parent_details["metadata"] = self._json_safe(parent_metadata)
            parent_details["merged_subtitle_task"] = self._json_safe(item)
            parent["details"] = parent_details
            merged_item_ids.add(item_id)

        return [item for item in items if self._safe_text(item.get("id")) not in merged_item_ids]


    def _infer_domain(self, task: Task) -> str:
        metadata = dict(task.task_metadata or {})
        explicit = self._safe_text(metadata.get("task_domain"))
        if explicit:
            return explicit
        return self.TASK_TYPE_TO_DOMAIN.get(task.type, "system")

    def _build_engine_actions(self, task: Task, domain: str) -> List[str]:
        actions: List[str] = []
        if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
            actions.extend(["pause", "cancel"])
        elif task.status == TaskStatus.PAUSED:
            actions.extend(["resume", "cancel"])
        elif task.status == TaskStatus.FAILED and self._can_retry_engine_task(task, domain):
            actions.append("retry")
        elif task.status == TaskStatus.WAITING_RETRY and domain == "asmr_sync":
            actions.extend(["retry_waiting", "delete_waiting_retry"])
        return actions

    def _can_retry_engine_task(self, task: Task, domain: str) -> bool:
        if domain not in {"import", "system"}:
            return False
        source_path = self._safe_text(getattr(task, "source_path", ""))
        if not source_path or not os.path.exists(source_path):
            return False
        return True

    def _resolve_display_status(self, task: Task, domain: str, metadata: Dict[str, Any]) -> str:
        if domain == "rj_subtitle":
            if bool(metadata.get("manual_match_completed")):
                return TaskStatus.COMPLETED.value
            if task.status == TaskStatus.COMPLETED:
                return TaskStatus.PENDING.value
        return task.status.value

    def _serialize_engine_task(self, task: Task, *, mode: str = "detail") -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        domain = self._infer_domain(task)
        source_path = self._safe_text(task.source_path)
        output_path = self._safe_text(task.output_path)
        resolved_target_path = (
            output_path
            or self._safe_text(metadata.get("subtitle_dir"))
            or self._safe_text(metadata.get("target_folder_path"))
            or self._safe_text(metadata.get("folder_path"))
        )
        # 关键优化：summary 模式跳过 os.walk，它只给详情面板的文件树用
        if mode == "detail":
            metadata = self._ensure_file_tree_metadata(metadata, resolved_target_path, source_path)
        route_hint = self.DOMAIN_ROUTE_HINT.get(domain, "/tasks")
        rjcode = self._normalize_rjcode(
            self._safe_text(getattr(task, "rjcode", ""))
            or self._safe_text(metadata.get("target_rjcode"))
            or self._safe_text(metadata.get("actual_rjcode"))
            or self._safe_text(metadata.get("rjcode"))
        )

        title = self._basename(source_path) or self._safe_text(metadata.get("folder_name")) or task.type.value
        subtitle = ""
        source_label = self._safe_text(metadata.get("source_label"))
        source_action = self._safe_text(metadata.get("source_action"))
        source_page = self._safe_text(metadata.get("source_page"))
        metrics: List[Dict[str, str]] = []
        current_step_override = ""

        if domain == "import":
            title = self._basename(source_path) or self._safe_text(metadata.get("work_name")) or "导入任务"
            subtitle = self._safe_text(metadata.get("work_name")) or self._safe_text(metadata.get("maker_name"))
            source_label = source_label or "上传压缩包 / 手动导入"
            source_action = source_action or "auto_process"
            source_page = source_page or "dashboard"
            self._append_metric(metrics, "RJ", rjcode)
            self._append_metric(metrics, "输出", self._basename(output_path))
            self._append_metric(metrics, "目标库", metadata.get("target_library_id"))
        elif domain == "existing_folder":
            title = self._safe_text(metadata.get("folder_name")) or self._basename(source_path) or rjcode or "已有文件夹任务"
            subtitle = self._safe_text(metadata.get("folder_path")) or source_path
            source_label = source_label or "已有文件夹 / 批量处理"
            source_action = source_action or "process_existing_folder"
            source_page = source_page or "existing-folders"
            self._append_metric(metrics, "RJ", rjcode or metadata.get("inferred_rjcode"))
            self._append_metric(metrics, "目录", self._basename(source_path))
            self._append_metric(metrics, "自动分类", "是" if bool(metadata.get("auto_classify")) else "否")
            self._append_metric(metrics, "目标库", metadata.get("target_library_id"))
        elif domain == "rj_subtitle":
            title = self._safe_text(metadata.get("folder_name")) or self._basename(metadata.get("folder_path")) or self._basename(source_path) or "RJ 字幕任务"
            subtitle = self._safe_text(metadata.get("source_title")) or self._safe_text(metadata.get("folder_path"))
            source_label = source_label or "库存页 / 抓字幕"
            source_action = source_action or self._safe_text(metadata.get("source_mode")) or "rj_subtitle_fetch"
            source_page = source_page or "library"
            self._append_metric(metrics, "RJ", rjcode or metadata.get("actual_rjcode"))
            self._append_metric(metrics, "下载", metadata.get("downloaded_count"))
            self._append_metric(metrics, "现有字幕", metadata.get("existing_subtitle_count"))
            self._append_metric(metrics, "写入", len(metadata.get("written_files") or []))
            if metadata.get("awaiting_manual_match"):
                self._append_metric(metrics, "待手配", "是")
        elif domain == "asmr_sync":
            is_reimport_task = source_action in {"reimport_local_download_root", "reimport_downloaded_session"}
            title = self._safe_text(metadata.get("work_title")) or rjcode or self._basename(source_path) or ("直接入库任务" if is_reimport_task else "ASMR 同步任务")
            subtitle = self._safe_text(metadata.get("subtitle_folder")) or source_path
            source_label = source_label or ("直接入库" if is_reimport_task else "ASMR 同步下载")
            source_action = source_action or ("reimport_downloaded_session" if is_reimport_task else "asmr_sync_start")
            source_page = source_page or ("circle-completion" if is_reimport_task else "asmr-sync")
            sync_result = dict(metadata.get("sync_result") or {})
            verify_summary = dict(metadata.get("verify_summary") or {})
            upload_summary = dict(metadata.get("upload_summary") or {})
            performance_metrics = dict(metadata.get("performance_metrics") or {})
            self._append_metric(metrics, "RJ", rjcode or metadata.get("actual_rjcode"))
            self._append_metric(metrics, "资源数", metadata.get("selected_resource_count") or len(metadata.get("download_files") or []))
            self._append_metric(metrics, "失败文件", len(metadata.get("failed_files") or []))
            self._append_metric(metrics, "MD5失败", verify_summary.get("failed"))
            self._append_metric(metrics, "已上传", upload_summary.get("uploaded"))
            self._append_metric(metrics, "上传大小", self._format_bytes(performance_metrics.get("uploaded_bytes")) if performance_metrics.get("uploaded_bytes") else None)
            self._append_metric(metrics, "平均上传", f"{self._format_bytes(performance_metrics.get('average_upload_speed_bytes'))}/s" if performance_metrics.get("average_upload_speed_bytes") else None)
            self._append_metric(metrics, "耗时", self._format_duration_ms(performance_metrics.get("duration_ms")) if performance_metrics.get("duration_ms") else None)
            self._append_metric(metrics, "已写入", sync_result.get("downloaded_files"))
            if is_reimport_task:
                self._append_metric(
                    metrics,
                    "目标库",
                    self._safe_text(metadata.get("target_library_id"))
                    or self._safe_text((metadata.get("postprocess_options") or {}).get("target_library_id")),
                )
        elif domain == "upload":
            selected_paths = [
                self._safe_text(path)
                for path in (metadata.get("selected_paths") or [])
                if self._safe_text(path)
            ]
            selected_items = [
                item for item in (metadata.get("selected_items") or [])
                if isinstance(item, dict) and self._safe_text(item.get("source_path"))
            ]
            upload_runtime = dict(metadata.get("upload_runtime") or {})
            upload_files = list(metadata.get("upload_files") or [])
            uploaded_files = list(metadata.get("uploaded_files") or [])
            selected_dir_count = int(metadata.get("selected_dir_count") or len(selected_paths) or len(selected_items) or 0)
            current_relative_path = self._safe_text(upload_runtime.get("current_relative_path"))
            current_file_name = self._safe_text(upload_runtime.get("current_file_name"))
            title_source = ""
            if len(selected_paths) == 1:
                title_source = selected_paths[0]
            elif len(selected_items) == 1:
                title_source = self._safe_text(selected_items[0].get("source_path"))
            elif selected_paths:
                title_source = selected_paths[0]
            elif selected_items:
                title_source = self._safe_text(selected_items[0].get("source_path"))
            else:
                title_source = self._safe_text(metadata.get("source_label")) or self._safe_text(metadata.get("circle_name")) or source_path
            title = self._basename(title_source) or "库存上传任务"
            if selected_dir_count > 1:
                title = f"{title} 等 {selected_dir_count} 项"
            subtitle_parts = []
            final_target = self._safe_text(metadata.get("final_output_path")) or output_path or self._safe_text(metadata.get("target_path"))
            if selected_dir_count > 0:
                subtitle_parts.append(f"{selected_dir_count} 个目录")
            if final_target:
                subtitle_parts.append(final_target)
            subtitle = " · ".join(subtitle_parts) or self._safe_text(metadata.get("target_path")) or source_path
            source_label = source_label or "库存上传"
            source_action = source_action or "upload_to_server"
            source_page = source_page or "library"
            if not rjcode:
                rjcode = self._normalize_rjcode(title_source)
            upload_total_bytes = int(
                upload_runtime.get("total_bytes")
                or sum(int((item or {}).get("size") or (item or {}).get("size_bytes") or 0) for item in upload_files)
                or sum(int((item or {}).get("size") or (item or {}).get("size_bytes") or (item or {}).get("uploaded_bytes") or 0) for item in uploaded_files)
                or 0
            )
            uploaded_count = int(len(uploaded_files) or sum(1 for item in upload_files if int((item or {}).get("progress") or 0) >= 100))
            self._append_metric(metrics, "RJ", rjcode)
            self._append_metric(metrics, "目录", selected_dir_count)
            self._append_metric(metrics, "文件", len(upload_files) or len(uploaded_files))
            self._append_metric(metrics, "大小", self._format_bytes(upload_total_bytes) if upload_total_bytes else None)
            self._append_metric(metrics, "已上传", uploaded_count if uploaded_count else None)
            self._append_metric(metrics, "目标库", metadata.get("target_library_id"))
            self._append_metric(metrics, "前缀", metadata.get("target_subdir"))
            if task.status == TaskStatus.PROCESSING:
                if current_relative_path:
                    current_step_override = f"上传中: {current_relative_path}"
                elif current_file_name:
                    current_step_override = f"上传中: {current_file_name}"
        elif domain == "circle_completion":
            if task.type == TaskType.CIRCLE_COMPLETION_INDEX:
                index_meta = dict(metadata.get("index_meta") or {})
                indexed_counts = dict(metadata.get("indexed_counts") or {})
                if bool(metadata.get("is_refresh_all")):
                    title = "全部刷新社团索引"
                    subtitle = self._safe_text(metadata.get("source_label")) or f"{int(metadata.get('batch_total') or 0)} 个社团"
                else:
                    title = self._safe_text(metadata.get("circle_name")) or self._safe_text(metadata.get("circle_query")) or "社团索引任务"
                    subtitle = self._safe_text(metadata.get("circle_id")) or self._safe_text(metadata.get("circle_query"))
                self._append_metric(metrics, "候选", index_meta.get("combined_candidates_count") or index_meta.get("aggregated_count"))
                self._append_metric(metrics, "DLsite", index_meta.get("dlsite_candidates_count") or index_meta.get("dlsite_profile_total") or indexed_counts.get("dl_count"))
                self._append_metric(metrics, "可下载", index_meta.get("asmr_available_count") or indexed_counts.get("downloadable_count"))
                self._append_metric(metrics, "本地", indexed_counts.get("local_owned_count"))
                self._append_metric(metrics, "缺失", indexed_counts.get("missing_count"))
            else:
                title = self._safe_text(metadata.get("circle_name")) or self._safe_text(metadata.get("work_title")) or rjcode or "社团补全任务"
                subtitle = self._safe_text(metadata.get("canonical_rjcode")) or self._safe_text(metadata.get("circle_id"))
                self._append_metric(metrics, "RJ", rjcode)
                self._append_metric(metrics, "Canonical", metadata.get("canonical_rjcode"))
                self._append_metric(metrics, "资源数", metadata.get("selected_resource_count"))
            source_label = source_label or "社团补全"
            source_action = source_action or ("index_start" if task.type == TaskType.CIRCLE_COMPLETION_INDEX else "batch_download")
            source_page = source_page or "circle-completion"
        else:
            title = self._basename(source_path) or task.type.value
            subtitle = self._safe_text(metadata.get("work_name")) or self._safe_text(metadata.get("folder_path"))
            source_label = source_label or "任务引擎"
            source_action = source_action or task.type.value
            source_page = source_page or "tasks"
            self._append_metric(metrics, "类型", task.type.value)
            self._append_metric(metrics, "RJ", rjcode)

        recovered_notice = self._safe_text(metadata.get("recovered_notice"))
        recovered_failure_count = int(metadata.get("recovered_failure_count") or 0)
        recovered_conflict_count = int(metadata.get("recovered_conflict_count") or 0)
        display_status = self._resolve_display_status(task, domain, metadata)
        is_conflict_retry = self._safe_text(metadata.get("conflict_resolution_action")).upper() == "RETRY"
        if recovered_failure_count > 0:
            self._append_metric(metrics, "此前失败", f"{recovered_failure_count} 次")
        if recovered_conflict_count > 0:
            self._append_metric(metrics, "问题作品", f"已移除 {recovered_conflict_count} 项")

        current_step = current_step_override or self._safe_text(task.current_step) or "等待中"
        status_label = self.STATUS_LABELS.get(display_status, display_status)
        if is_conflict_retry and display_status == TaskStatus.PROCESSING.value:
            status_label = "重试中"
            source_label = "问题作品 / 重试"
            source_page = "conflicts"
            route_hint = "/conflicts"
        elif is_conflict_retry and display_status == TaskStatus.COMPLETED.value:
            status_label = "已解决"
            source_label = "问题作品 / 已解决"
            source_page = "conflicts"
            route_hint = "/conflicts"
        if task.status == TaskStatus.COMPLETED and recovered_notice:
            current_step = recovered_notice

        # 关键优化：summary 模式下只挑几个必要的键，跳过全量深拷贝
        if mode == "detail":
            details_metadata = self._json_safe(metadata)
        else:
            details_metadata = self._build_summary_metadata(metadata)

        return {
            "id": f"engine:{task.id}",
            "entity_id": task.id,
            "engine_task_id": task.id,
            "domain": domain,
            "domain_label": self.DOMAIN_LABELS.get(domain, domain),
            "kind": task.type.value,
            "kind_label": source_label or task.type.value,
            "title": title,
            "subtitle": subtitle,
            "source_label": source_label,
            "source_page": source_page,
            "source_action": source_action,
            "route_hint": route_hint,
            "status": display_status,
            "status_label": status_label,
            "progress": int(task.progress or 0),
            "current_step": current_step,
            "error_message": self._safe_text(task.error_message),
            "source_path": source_path,
            "target_path": resolved_target_path,
            "rjcode": rjcode,
            "created_at": self._safe_iso(task.created_at),
            "started_at": self._safe_iso(task.started_at),
            "completed_at": self._safe_iso(task.completed_at),
            "metrics": metrics,
            "actions": self._build_engine_actions(task, domain),
            "details": {
                "type": task.type.value,
                "metadata": details_metadata,
            },
        }

    def _is_superseded_failed_item(self, item: Dict[str, Any]) -> bool:
        if self._safe_text(item.get("status")) != TaskStatus.FAILED.value:
            return False
        details = dict(item.get("details") or {})
        metadata = dict(details.get("metadata") or {})
        return bool(self._safe_text(metadata.get("superseded_by_task_id")))

    def _same_source_path(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        try:
            return os.path.abspath(left) == os.path.abspath(right)
        except Exception:
            return left == right

    def _is_superseded_active_engine_item(self, item: Dict[str, Any], items: List[Dict[str, Any]]) -> bool:
        if not self._safe_text(item.get("id")).startswith("engine:"):
            return False

        status = self._safe_text(item.get("status"))
        if status not in {
            TaskStatus.PENDING.value,
            TaskStatus.PROCESSING.value,
            TaskStatus.PAUSED.value,
            TaskStatus.WAITING_MANUAL.value,
            TaskStatus.WAITING_RETRY.value,
        }:
            return False

        details = dict(item.get("details") or {})
        metadata = dict(details.get("metadata") or {})
        if self._safe_text(metadata.get("superseded_by_task_id")):
            return True

        item_id = self._safe_text(item.get("entity_id")) or self._safe_text(item.get("engine_task_id"))
        source_path = self._safe_text(item.get("source_path"))
        completed_at = self._last_timestamp(item)

        for candidate in items:
            if candidate is item:
                continue
            if not self._safe_text(candidate.get("id")).startswith("engine:"):
                continue
            if self._safe_text(candidate.get("status")) != TaskStatus.COMPLETED.value:
                continue

            candidate_completed_at = self._last_timestamp(candidate)
            if candidate_completed_at and completed_at and candidate_completed_at < completed_at:
                continue

            candidate_details = dict(candidate.get("details") or {})
            candidate_metadata = dict(candidate_details.get("metadata") or {})
            recovered_failure_ids = candidate_metadata.get("recovered_failure_ids") or []
            if item_id and item_id in {str(value) for value in recovered_failure_ids}:
                return True

            if source_path and self._same_source_path(source_path, self._safe_text(candidate.get("source_path"))):
                return True

        return False

    def _serialize_pending_subtitle_item(self, item: Dict[str, Any], *, mode: str = "detail") -> Dict[str, Any]:
        preview = dict(item.get("preview") or {})
        selected_candidate = dict(preview.get("selected_candidate") or {})
        source_rjcode = self._safe_text(preview.get("source_rjcode"))
        target_rjcode = self._safe_text(preview.get("target_rjcode"))
        title = self._safe_text(preview.get("source_label")) or self._basename(item.get("source_path")) or "字幕补配预检"
        subtitle_parts = [part for part in [source_rjcode, target_rjcode] if part]
        subtitle = " -> ".join(subtitle_parts)
        metrics: List[Dict[str, str]] = []
        self._append_metric(metrics, "来源字幕", preview.get("subtitle_count"))
        self._append_metric(metrics, "候选目录", preview.get("candidate_count"))
        self._append_metric(metrics, "可执行候选", preview.get("ready_candidate_count"))
        self._append_metric(metrics, "目标库", selected_candidate.get("library_id"))

        # summary 模式下 preview 只保留几个前端 list 页会读的字段
        if mode == "detail":
            details_preview = self._json_safe(preview)
        else:
            details_preview = self._build_summary_preview(preview)

        return {
            "id": f"subtitle-pending:{item.get('id')}",
            "entity_id": self._safe_text(item.get("id")),
            "record_id": self._safe_text(item.get("id")),
            "engine_task_id": self._safe_text(item.get("task_id")),
            "domain": "subtitle_import",
            "domain_label": self.DOMAIN_LABELS["subtitle_import"],
            "kind": "linked_subtitle_pending",
            "kind_label": "字幕补配预检",
            "title": title,
            "subtitle": subtitle,
            "source_label": "字幕补配页 / 预检单",
            "source_page": "subtitle-import",
            "source_action": "pending_import",
            "route_hint": self.DOMAIN_ROUTE_HINT["subtitle_import"],
            "status": TaskStatus.WAITING_MANUAL.value,
            "status_label": self.STATUS_LABELS[TaskStatus.WAITING_MANUAL.value],
            "progress": 0,
            "current_step": self._safe_text(preview.get("execute_reason")) or "等待在字幕补配页确认目标目录和执行方式",
            "error_message": "",
            "source_path": self._safe_text(item.get("source_path")),
            "target_path": self._safe_text(selected_candidate.get("folder_path")),
            "rjcode": target_rjcode or source_rjcode,
            "created_at": self._safe_text(item.get("created_at")),
            "started_at": None,
            "completed_at": None,
            "metrics": metrics,
            "actions": ["open_subtitle_import"],
            "details": {
                "preview": details_preview,
                "can_execute": bool(item.get("can_execute")),
                "source_mode": self._safe_text(item.get("source_mode")),
            },
        }

    def _serialize_waiting_retry_item(self, item: Dict[str, Any], *, mode: str = "detail") -> Dict[str, Any]:
        metadata = dict(item.get("task_metadata") or {})
        retry_reason = self._safe_text(item.get("retry_reason")) or self._safe_text(metadata.get("retry_reason"))
        retry_after = self._safe_text(item.get("retry_after")) or self._safe_text(metadata.get("retry_after"))
        metrics: List[Dict[str, str]] = []
        self._append_metric(metrics, "重试次数", item.get("retry_count") or metadata.get("retry_count"))
        self._append_metric(metrics, "下次重试", retry_after)

        # summary 模式下不需要完整 task_metadata
        if mode == "detail":
            details_metadata = self._json_safe(metadata)
        else:
            details_metadata = self._build_summary_metadata(metadata)

        return {
            "id": f"waiting-retry:{item.get('id')}",
            "entity_id": self._safe_text(item.get("id")),
            "engine_task_id": self._safe_text(item.get("id")),
            "domain": "asmr_sync",
            "domain_label": self.DOMAIN_LABELS["asmr_sync"],
            "kind": "asmr_sync_waiting_retry",
            "kind_label": "ASMR 等待重试",
            "title": self._safe_text(item.get("work_title")) or self._safe_text(item.get("rjcode")) or "等待重试任务",
            "subtitle": self._safe_text(item.get("subtitle_folder")),
            "source_label": "ASMR 同步下载",
            "source_page": "asmr-sync",
            "source_action": "waiting_retry",
            "route_hint": self.DOMAIN_ROUTE_HINT["asmr_sync"],
            "status": TaskStatus.WAITING_RETRY.value,
            "status_label": self.STATUS_LABELS[TaskStatus.WAITING_RETRY.value],
            "progress": 0,
            "current_step": retry_reason or "等待定时重试",
            "error_message": "",
            "source_path": self._safe_text(item.get("subtitle_folder")),
            "target_path": "",
            "rjcode": self._safe_text(item.get("rjcode")),
            "created_at": self._safe_text(item.get("created_at")),
            "started_at": None,
            "completed_at": None,
            "metrics": metrics,
            "actions": ["retry_waiting", "delete_waiting_retry"],
            "details": {
                "task_metadata": details_metadata,
                "retry_reason": retry_reason,
                "retry_after": retry_after,
            },
        }

    def _dedupe_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen_waiting_retry_ids: set[str] = set()

        for item in items:
            if item.get("kind") == "asmr_sync_waiting_retry":
                entity_id = self._safe_text(item.get("entity_id"))
                if entity_id in seen_waiting_retry_ids:
                    continue
                seen_waiting_retry_ids.add(entity_id)
            deduped.append(item)

        deduped = [
            item for item in deduped
            if not self._is_superseded_active_engine_item(item, deduped)
        ]
        return deduped

    def _filter_items(
        self,
        items: List[Dict[str, Any]],
        *,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_domain = self._safe_text(domain)
        normalized_status = self._safe_text(status)
        normalized_search = self._safe_text(search).lower()

        filtered = items
        if normalized_domain and normalized_domain != "all":
            filtered = [item for item in filtered if item.get("domain") == normalized_domain]
        if normalized_status and normalized_status != "all":
            filtered = [item for item in filtered if item.get("status") == normalized_status]
        if normalized_search:
            filtered = [
                item for item in filtered
                if normalized_search in " ".join([
                    self._safe_text(item.get("title")),
                    self._safe_text(item.get("subtitle")),
                    self._safe_text(item.get("source_path")),
                    self._safe_text(item.get("rjcode")),
                    self._safe_text(item.get("current_step")),
                ]).lower()
            ]
        return filtered

    def _sort_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                self.STATUS_PRIORITY.get(self._safe_text(item.get("status")), 99),
                self.DOMAIN_PRIORITY.get(self._safe_text(item.get("domain")), 99),
                -self._last_timestamp(item),
            )
        )

    def _safe_serialize_engine_task(self, task: Task, *, mode: str = "detail") -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_engine_task(task, mode=mode)
        except Exception:
            logger.exception(
                "[任务中心] 序列化引擎任务失败，已跳过: task_id=%s type=%s source=%s",
                getattr(task, "id", ""),
                getattr(getattr(task, "type", None), "value", getattr(task, "type", "")),
                getattr(task, "source_path", ""),
            )
            return None

    def _safe_serialize_pending_item(self, item: Dict[str, Any], *, mode: str = "detail") -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_pending_subtitle_item(item, mode=mode)
        except Exception:
            logger.exception(
                "[任务中心] 序列化字幕补配预检项失败，已跳过: id=%s task_id=%s source=%s",
                item.get("id", ""),
                item.get("task_id", ""),
                item.get("source_path", ""),
            )
            return None

    def _safe_serialize_waiting_retry_item(self, item: Dict[str, Any], *, mode: str = "detail") -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_waiting_retry_item(item, mode=mode)
        except Exception:
            logger.exception(
                "[任务中心] 序列化等待重试任务失败，已跳过: id=%s rj=%s",
                item.get("id", ""),
                item.get("rjcode", ""),
            )
            return None

    async def _get_pending_items_cached(self) -> List[Dict[str, Any]]:
        """pending imports 单独 TTL 缓存，避免每次 _build_all_items 都走 DB + 可能的远程查询。"""
        now = time.monotonic()
        if (
            self._pending_cache is not None
            and now - self._pending_cache_at <= self.PENDING_CACHE_TTL_SECONDS
        ):
            return list(self._pending_cache)
        try:
            subtitle_import_service = get_linked_subtitle_import_service()
            fetched = await subtitle_import_service.list_pending_imports()
            self._pending_cache = list(fetched or [])
            self._pending_cache_at = now
            return list(self._pending_cache)
        except Exception:
            logger.exception("[任务中心] 读取字幕补配预检列表失败，当前轮次已跳过 pending items")
            return list(self._pending_cache or [])

    def _get_active_conflicts_cached(self) -> List[ConflictWork]:
        """active conflicts 单独 TTL 缓存，避免每次重建都查一次 ConflictWork 表。"""
        now = time.monotonic()
        if (
            self._conflict_cache is not None
            and now - self._conflict_cache_at <= self.CONFLICT_CACHE_TTL_SECONDS
        ):
            return list(self._conflict_cache)
        try:
            fetched = self._load_active_conflicts()
            self._conflict_cache = list(fetched or [])
            self._conflict_cache_at = now
            return list(self._conflict_cache)
        except Exception:
            logger.exception("[任务中心] 读取问题作品列表失败，当前轮次已跳过 conflict items")
            return list(self._conflict_cache or [])

    async def _build_all_items(self, *, mode: str = "detail") -> List[Dict[str, Any]]:
        """根据 mode 选择 detail / summary 两套独立缓存。summary 跳过重 IO。"""
        now = time.monotonic()
        is_summary = self._safe_text(mode).lower() == "summary"

        if is_summary:
            cache_data = self._summary_cache
            cache_signature = self._summary_cache_signature
            cache_at = self._summary_cache_at
            ttl = self.SUMMARY_CACHE_TTL_SECONDS
        else:
            cache_data = self._detail_cache
            cache_signature = self._detail_cache_signature
            cache_at = self._detail_cache_at
            ttl = self.CACHE_TTL_SECONDS

        # 热路径：缓存未过期且引擎签名未变，直接返回。签名计算只走内存。
        if cache_data is not None and now - cache_at <= ttl:
            engine_signature_now = self._engine_signature()
            if engine_signature_now == cache_signature:
                return list(cache_data)
        else:
            engine_signature_now = None

        if engine_signature_now is None:
            engine_signature_now = self._engine_signature()

        # 冷路径：重建。engine tasks 走对应 mode 的序列化；pending / conflict 走子集缓存。
        engine = get_task_engine()
        items: List[Dict[str, Any]] = [
            serialized
            for serialized in (
                self._safe_serialize_engine_task(task, mode=mode)
                for task in engine.get_all_tasks()
            )
            if serialized
        ]

        pending_items_raw = await self._get_pending_items_cached()
        items.extend(
            serialized
            for serialized in (
                self._safe_serialize_pending_item(item, mode=mode)
                for item in pending_items_raw
            )
            if serialized
        )

        waiting_retry_items = engine.get_waiting_retry_tasks_from_db()
        items.extend(
            serialized
            for serialized in (
                self._safe_serialize_waiting_retry_item(item, mode=mode)
                for item in waiting_retry_items
            )
            if serialized
        )

        active_conflicts = self._get_active_conflicts_cached()
        conflict_items = [
            serialized
            for serialized in (self._safe_serialize_conflict_item(conflict) for conflict in active_conflicts)
            if serialized
        ]

        # 单步出错不阻断整体：每步骤独立 try/except，避免一个 item 字段异常
        # 把整个任务中心 API 拖成 500。失败步骤回退到上一步的 items 即可。
        try:
            items = self._merge_linked_subtitle_pipeline_items(items)
        except Exception:
            logger.exception("[任务中心] 合并 linked subtitle pipeline 失败，跳过该步骤")
        try:
            items = self._merge_conflict_pipeline_items(items, conflict_items)
        except Exception:
            logger.exception("[任务中心] 合并 conflict pipeline 失败，跳过该步骤")
        try:
            items = self._dedupe_items(items)
        except Exception:
            logger.exception("[任务中心] 去重 items 失败，跳过该步骤")
        try:
            items = [item for item in items if not self._is_superseded_failed_item(item)]
        except Exception:
            logger.exception("[任务中心] 过滤 superseded failed items 失败，跳过该步骤")
        try:
            items = self._sort_items(items)
        except Exception:
            logger.exception("[任务中心] 排序 items 失败，使用原始顺序")

        completed_at = time.monotonic()
        if is_summary:
            self._summary_cache = list(items)
            self._summary_cache_signature = engine_signature_now
            self._summary_cache_at = completed_at
        else:
            self._detail_cache = list(items)
            self._detail_cache_signature = engine_signature_now
            self._detail_cache_at = completed_at
        return items

    async def diagnose_serialization_failures(self) -> Dict[str, Any]:
        engine = get_task_engine()
        report: Dict[str, Any] = {
            "engine_tasks": [],
            "pending_items": [],
            "waiting_retry_items": [],
        }

        for task in engine.get_all_tasks():
            try:
                self._serialize_engine_task(task)
            except Exception as exc:
                report["engine_tasks"].append({
                    "task_id": getattr(task, "id", ""),
                    "type": getattr(getattr(task, "type", None), "value", getattr(task, "type", "")),
                    "status": getattr(getattr(task, "status", None), "value", getattr(task, "status", "")),
                    "source_path": getattr(task, "source_path", ""),
                    "output_path": getattr(task, "output_path", ""),
                    "rjcode": getattr(task, "rjcode", ""),
                    "error": repr(exc),
                    "task_metadata_type": type(getattr(task, "task_metadata", None)).__name__,
                    "task_metadata_preview": self._json_safe(getattr(task, "task_metadata", None)),
                })

        subtitle_import_service = get_linked_subtitle_import_service()
        pending_items = await subtitle_import_service.list_pending_imports()
        for item in pending_items:
            try:
                self._serialize_pending_subtitle_item(item)
            except Exception as exc:
                report["pending_items"].append({
                    "id": item.get("id", ""),
                    "task_id": item.get("task_id", ""),
                    "source_path": item.get("source_path", ""),
                    "error": repr(exc),
                    "item_preview": self._json_safe(item),
                })

        waiting_retry_items = engine.get_waiting_retry_tasks_from_db()
        for item in waiting_retry_items:
            try:
                self._serialize_waiting_retry_item(item)
            except Exception as exc:
                report["waiting_retry_items"].append({
                    "id": item.get("id", ""),
                    "rjcode": item.get("rjcode", ""),
                    "error": repr(exc),
                    "item_preview": self._json_safe(item),
                })

        report["summary"] = {
            "engine_task_total": len(engine.get_all_tasks()),
            "engine_task_failures": len(report["engine_tasks"]),
            "pending_item_total": len(pending_items),
            "pending_item_failures": len(report["pending_items"]),
            "waiting_retry_total": len(waiting_retry_items),
            "waiting_retry_failures": len(report["waiting_retry_items"]),
        }
        return report

    async def list_items(
        self,
        *,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        mode: str = "detail",
    ) -> Dict[str, Any]:
        normalized_mode = self._safe_text(mode).lower() or "detail"
        safe_limit = max(1, min(int(limit or 200), 500))
        safe_offset = max(0, int(offset or 0))
        # 顶层防御：底层任意环节抛错都回退到"空列表 + 200"，避免整个任务中心
        # 因为单条任务序列化异常被拖成 500。具体异常已经在底层 logger.exception 记录。
        try:
            items = await self._build_all_items(mode=normalized_mode)
        except Exception:
            logger.exception("[任务中心] _build_all_items 顶层异常，返回空列表兜底")
            items = []
        try:
            items = self._filter_items(items, domain=domain, status=status, search=search)
        except Exception:
            logger.exception("[任务中心] _filter_items 异常，跳过过滤步骤")
        total = len(items)
        page_items = items[safe_offset:safe_offset + safe_limit]
        if normalized_mode == "summary":
            try:
                page_items = [self._summary_item(item) for item in page_items]
            except Exception:
                logger.exception("[任务中心] summary 模式构建失败，回退原始 items")
        return {
            "items": page_items,
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
            "mode": normalized_mode,
            "generated_at": datetime.now().isoformat(),
        }

    async def get_item(
        self,
        *,
        item_id: Optional[str] = None,
        engine_task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_item_id = self._safe_text(item_id)
        normalized_engine_task_id = self._safe_text(engine_task_id)
        if not normalized_item_id and not normalized_engine_task_id:
            raise ValueError("item_id 和 engine_task_id 不能同时为空")

        # get_item 需要完整 metadata + 文件树，走 detail 模式
        items = await self._build_all_items(mode="detail")
        for item in items:
            if normalized_item_id and self._safe_text(item.get("id")) == normalized_item_id:
                return item
            if normalized_engine_task_id and self._safe_text(item.get("engine_task_id")) == normalized_engine_task_id:
                return item
        return None

    async def get_overview(self) -> Dict[str, Any]:
        # overview 只用来统计 + 提取 top items，summary 模式足矣
        # 顶层防御：底层异常时返回零数据兜底，避免 dashboard 头部 500。
        try:
            items = await self._build_all_items(mode="summary")
        except Exception:
            logger.exception("[任务中心] get_overview 顶层异常，返回零数据兜底")
            items = []
        counts_by_domain = {
            key: 0 for key in self.DOMAIN_LABELS.keys()
            if key != "all"
        }
        counts_by_status = {
            key: 0 for key in self.STATUS_LABELS.keys()
        }

        for item in items:
            domain = self._safe_text(item.get("domain"))
            status = self._safe_text(item.get("status"))
            if domain in counts_by_domain:
                counts_by_domain[domain] += 1
            if status in counts_by_status:
                counts_by_status[status] += 1

        active_items = [
            item for item in items
            if item.get("status") in {
                TaskStatus.PROCESSING.value,
                TaskStatus.PENDING.value,
                TaskStatus.PAUSED.value,
                TaskStatus.WAITING_MANUAL.value,
                TaskStatus.WAITING_RETRY.value,
            }
        ]

        recent_terminal_items = [
            item for item in items
            if item.get("status") in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}
        ]

        return {
            "generated_at": datetime.now().isoformat(),
            "total": len(items),
            "counts_by_domain": counts_by_domain,
            "counts_by_status": counts_by_status,
            "highlight_counts": {
                "processing": counts_by_status.get(TaskStatus.PROCESSING.value, 0),
                "waiting_manual": counts_by_status.get(TaskStatus.WAITING_MANUAL.value, 0),
                "waiting_retry": counts_by_status.get(TaskStatus.WAITING_RETRY.value, 0),
                "failed": counts_by_status.get(TaskStatus.FAILED.value, 0),
            },
            "recent_items": [self._summary_item(item) for item in recent_terminal_items[:6]],
            "active_items": [self._summary_item(item) for item in active_items[:6]],
        }

    async def execute_action(self, item_id: str, action: str) -> Dict[str, Any]:
        normalized_item_id = self._safe_text(item_id)
        normalized_action = self._safe_text(action)
        if not normalized_item_id or not normalized_action:
            raise ValueError("任务 ID 和动作不能为空")

        engine = get_task_engine()

        if normalized_item_id.startswith("engine:"):
            engine_task_id = normalized_item_id.split(":", 1)[1]
            task = engine.get_task(engine_task_id)
            if not task:
                raise ValueError("任务不存在")

            if normalized_action == "open_subtitle_import":
                return {
                    "success": True,
                    "message": "请前往字幕补配页继续处理",
                    "route_hint": self.DOMAIN_ROUTE_HINT["subtitle_import"],
                }
            if normalized_action == "pause":
                engine.pause_task(engine_task_id)
                return {"success": True, "message": "任务已暂停"}
            if normalized_action == "resume":
                engine.resume_task(engine_task_id)
                return {"success": True, "message": "任务已恢复"}
            if normalized_action == "cancel":
                engine.cancel_task(engine_task_id)
                return {"success": True, "message": "任务已取消"}
            if normalized_action == "retry":
                if not self._can_retry_engine_task(task, self._infer_domain(task)):
                    raise ValueError("当前任务不支持重试")
                from .file_processor import get_file_processor

                file_processor = get_file_processor()
                source_path = self._safe_text(task.source_path)
                new_task = await file_processor.process_file(
                    source_path,
                    auto_classify=bool(getattr(task, "auto_classify", False)),
                    wait_stable=False,
                    is_processed=lambda path: False,
                    mark_processed=None,
                )
                if not new_task:
                    raise ValueError("无法重新创建任务")

                previous_metadata = dict(task.task_metadata or {})
                new_metadata = dict(new_task.task_metadata or {})
                if previous_metadata.get("target_library_id"):
                    new_metadata["target_library_id"] = previous_metadata.get("target_library_id")
                new_metadata["retry_from_task_id"] = task.id
                new_metadata["source_page"] = previous_metadata.get("source_page") or new_metadata.get("source_page") or "dashboard"
                new_metadata["source_action"] = "retry_task"
                new_metadata["source_label"] = previous_metadata.get("source_label") or new_metadata.get("source_label") or self._basename(source_path)
                new_task.task_metadata = new_metadata

                old_metadata = previous_metadata
                old_metadata["superseded_by_task_id"] = new_task.id
                task.task_metadata = old_metadata

                return {
                    "success": True,
                    "message": "已重新创建任务",
                    "route_hint": self.DOMAIN_ROUTE_HINT.get(self._infer_domain(new_task), "/tasks"),
                }
            raise ValueError("当前任务不支持该动作")

        if normalized_item_id.startswith("waiting-retry:"):
            waiting_task_id = normalized_item_id.split(":", 1)[1]
            if normalized_action == "retry_waiting":
                if engine.retry_task(waiting_task_id):
                    return {"success": True, "message": "任务已加入重试队列"}
                raise ValueError("任务不在等待重试状态")
            if normalized_action == "delete_waiting_retry":
                if waiting_task_id in engine.tasks:
                    task = engine.tasks[waiting_task_id]
                    rjcode = task.rjcode
                    del engine.tasks[waiting_task_id]
                    if rjcode:
                        engine._remove_waiting_retry_task(rjcode)
                else:
                    engine._remove_waiting_retry_task_by_id(waiting_task_id)
                return {"success": True, "message": "等待重试任务已移除"}
            raise ValueError("当前任务不支持该动作")

        if normalized_item_id.startswith("subtitle-pending:"):
            if normalized_action == "open_subtitle_import":
                return {
                    "success": True,
                    "message": "请前往字幕补配页继续处理",
                    "route_hint": self.DOMAIN_ROUTE_HINT["subtitle_import"],
                }
            raise ValueError("当前任务不支持该动作")

        if normalized_item_id.startswith("conflict:"):
            return {
                "success": True,
                "message": "请前往问题作品页继续处理",
                "route_hint": "/conflicts",
            }

        raise ValueError("未知的任务中心项目")


_task_center_service: Optional[TaskCenterService] = None


def get_task_center_service() -> TaskCenterService:
    global _task_center_service
    if _task_center_service is None:
        _task_center_service = TaskCenterService()
    return _task_center_service
