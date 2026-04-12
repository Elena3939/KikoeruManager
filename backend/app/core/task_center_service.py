import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .linked_subtitle_import_service import get_linked_subtitle_import_service
from .task_engine import Task, TaskStatus, TaskType, get_task_engine

logger = logging.getLogger(__name__)


class TaskCenterService:
    """统一聚合业务任务与引擎任务，供任务中心页面使用。"""

    DOMAIN_LABELS = {
        "all": "全部",
        "import": "导入处理",
        "rj_subtitle": "RJ 字幕",
        "subtitle_import": "字幕补配",
        "asmr_sync": "ASMR 同步",
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
        "rj_subtitle": 1,
        "subtitle_import": 2,
        "asmr_sync": 3,
        "circle_completion": 4,
        "system": 5,
    }

    TASK_TYPE_TO_DOMAIN = {
        TaskType.AUTO_PROCESS: "import",
        TaskType.PROCESS_EXISTING_FOLDER: "import",
        TaskType.RJ_SUBTITLE_FETCH: "rj_subtitle",
        TaskType.ASMR_SYNC_DOWNLOAD: "asmr_sync",
        TaskType.CIRCLE_COMPLETION_INDEX: "circle_completion",
        TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH: "circle_completion",
        TaskType.EXTRACT: "system",
        TaskType.FILTER: "system",
        TaskType.METADATA: "system",
        TaskType.RENAME: "system",
    }

    DOMAIN_ROUTE_HINT = {
        "import": "/library",
        "rj_subtitle": "/library",
        "subtitle_import": "/subtitle-import",
        "asmr_sync": "/asmr-sync",
        "circle_completion": "/circle-completion",
        "system": "/tasks",
    }

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
            if self._safe_text(item.get("domain")) != "import":
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
        if task.status == TaskStatus.PROCESSING:
            actions.extend(["pause", "cancel"])
        elif task.status == TaskStatus.PAUSED:
            actions.append("resume")
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

    def _serialize_engine_task(self, task: Task) -> Dict[str, Any]:
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

        if domain == "import":
            title = self._basename(source_path) or self._safe_text(metadata.get("work_name")) or "导入任务"
            subtitle = self._safe_text(metadata.get("work_name")) or self._safe_text(metadata.get("maker_name"))
            source_label = source_label or "上传压缩包 / 手动导入"
            source_action = source_action or "auto_process"
            source_page = source_page or "dashboard"
            self._append_metric(metrics, "RJ", rjcode)
            self._append_metric(metrics, "输出", self._basename(output_path))
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
            title = self._safe_text(metadata.get("work_title")) or rjcode or self._basename(source_path) or "ASMR 同步任务"
            subtitle = self._safe_text(metadata.get("subtitle_folder")) or source_path
            source_label = source_label or "ASMR 同步下载"
            source_action = source_action or "asmr_sync_start"
            source_page = source_page or "asmr-sync"
            sync_result = dict(metadata.get("sync_result") or {})
            verify_summary = dict(metadata.get("verify_summary") or {})
            upload_summary = dict(metadata.get("upload_summary") or {})
            self._append_metric(metrics, "RJ", rjcode or metadata.get("actual_rjcode"))
            self._append_metric(metrics, "资源数", metadata.get("selected_resource_count") or len(metadata.get("download_files") or []))
            self._append_metric(metrics, "失败文件", len(metadata.get("failed_files") or []))
            self._append_metric(metrics, "MD5失败", verify_summary.get("failed"))
            self._append_metric(metrics, "已上传", upload_summary.get("uploaded"))
            self._append_metric(metrics, "已写入", sync_result.get("downloaded_files"))
        elif domain == "circle_completion":
            if task.type == TaskType.CIRCLE_COMPLETION_INDEX:
                index_meta = dict(metadata.get("index_meta") or {})
                indexed_counts = dict(metadata.get("indexed_counts") or {})
                title = self._safe_text(metadata.get("circle_name")) or self._safe_text(metadata.get("circle_query")) or "社团索引任务"
                subtitle = self._safe_text(metadata.get("circle_id")) or self._safe_text(metadata.get("circle_query"))
                self._append_metric(metrics, "候选", index_meta.get("combined_candidates_count") or index_meta.get("aggregated_count"))
                self._append_metric(metrics, "DLsite", index_meta.get("dlsite_candidates_count") or index_meta.get("dlsite_profile_total"))
                self._append_metric(metrics, "可下载", index_meta.get("asmr_available_count") or indexed_counts.get("downloadable_count"))
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
        if recovered_failure_count > 0:
            self._append_metric(metrics, "此前失败", f"{recovered_failure_count} 次")
        if recovered_conflict_count > 0:
            self._append_metric(metrics, "问题作品", f"已移除 {recovered_conflict_count} 项")

        current_step = self._safe_text(task.current_step) or "等待中"
        if task.status == TaskStatus.COMPLETED and recovered_notice:
            current_step = recovered_notice

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
            "status_label": self.STATUS_LABELS.get(display_status, display_status),
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
                "metadata": self._json_safe(metadata),
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

    def _serialize_pending_subtitle_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
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
                "preview": self._json_safe(preview),
                "can_execute": bool(item.get("can_execute")),
                "source_mode": self._safe_text(item.get("source_mode")),
            },
        }

    def _serialize_waiting_retry_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        metadata = dict(item.get("task_metadata") or {})
        retry_reason = self._safe_text(item.get("retry_reason")) or self._safe_text(metadata.get("retry_reason"))
        retry_after = self._safe_text(item.get("retry_after")) or self._safe_text(metadata.get("retry_after"))
        metrics: List[Dict[str, str]] = []
        self._append_metric(metrics, "重试次数", item.get("retry_count") or metadata.get("retry_count"))
        self._append_metric(metrics, "下次重试", retry_after)

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
                "task_metadata": self._json_safe(metadata),
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

    def _safe_serialize_engine_task(self, task: Task) -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_engine_task(task)
        except Exception:
            logger.exception(
                "[任务中心] 序列化引擎任务失败，已跳过: task_id=%s type=%s source=%s",
                getattr(task, "id", ""),
                getattr(getattr(task, "type", None), "value", getattr(task, "type", "")),
                getattr(task, "source_path", ""),
            )
            return None

    def _safe_serialize_pending_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_pending_subtitle_item(item)
        except Exception:
            logger.exception(
                "[任务中心] 序列化字幕补配预检项失败，已跳过: id=%s task_id=%s source=%s",
                item.get("id", ""),
                item.get("task_id", ""),
                item.get("source_path", ""),
            )
            return None

    def _safe_serialize_waiting_retry_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return self._serialize_waiting_retry_item(item)
        except Exception:
            logger.exception(
                "[任务中心] 序列化等待重试任务失败，已跳过: id=%s rj=%s",
                item.get("id", ""),
                item.get("rjcode", ""),
            )
            return None

    async def _build_all_items(self) -> List[Dict[str, Any]]:
        engine = get_task_engine()
        items = [
            serialized
            for serialized in (self._safe_serialize_engine_task(task) for task in engine.get_all_tasks())
            if serialized
        ]

        subtitle_import_service = get_linked_subtitle_import_service()
        pending_items = await subtitle_import_service.list_pending_imports()
        items.extend(
            serialized
            for serialized in (self._safe_serialize_pending_item(item) for item in pending_items)
            if serialized
        )

        waiting_retry_items = engine.get_waiting_retry_tasks_from_db()
        items.extend(
            serialized
            for serialized in (self._safe_serialize_waiting_retry_item(item) for item in waiting_retry_items)
            if serialized
        )

        items = self._merge_linked_subtitle_pipeline_items(items)
        items = self._dedupe_items(items)
        items = [item for item in items if not self._is_superseded_failed_item(item)]
        return self._sort_items(items)

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
    ) -> List[Dict[str, Any]]:
        items = await self._build_all_items()
        items = self._filter_items(items, domain=domain, status=status, search=search)
        return items[: max(1, min(int(limit or 200), 500))]

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

        items = await self._build_all_items()
        for item in items:
            if normalized_item_id and self._safe_text(item.get("id")) == normalized_item_id:
                return item
            if normalized_engine_task_id and self._safe_text(item.get("engine_task_id")) == normalized_engine_task_id:
                return item
        return None

    async def get_overview(self) -> Dict[str, Any]:
        items = await self._build_all_items()
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
            "recent_items": items[:5],
            "active_items": active_items[:6],
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

        raise ValueError("未知的任务中心项目")


_task_center_service: Optional[TaskCenterService] = None


def get_task_center_service() -> TaskCenterService:
    global _task_center_service
    if _task_center_service is None:
        _task_center_service = TaskCenterService()
    return _task_center_service
