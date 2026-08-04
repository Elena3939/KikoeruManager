import asyncio
import copy
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from .linked_subtitle_import_service import get_linked_subtitle_import_service
from .task_engine import Task, TaskStatus, TaskType, get_task_engine
from .json_safety import safe_json_value, safe_text
from .http_download_service import (
    build_http_download_batch_title,
    http_download_platform_label,
    http_download_platforms_from_metadata,
    http_download_platforms_label,
    sanitize_http_download_metadata,
)
from .baidu_netdisk_service import (
    build_baidu_netdisk_batch_title,
    sanitize_baidu_netdisk_item,
    sanitize_baidu_netdisk_metadata,
)
from ..models.database import ConflictWork, SessionLocal

logger = logging.getLogger(__name__)


class TaskCenterService:
    """统一聚合业务任务与引擎任务，供任务中心页面使用。"""

    # detail 模式给 get_item / 详情面板用，需要完整 metadata + 文件树
    CACHE_TTL_SECONDS = 1.2
    # summary 模式给 list / overview 用，可容忍稍长的延迟换取明显更轻的开销
    SUMMARY_CACHE_TTL_SECONDS = 2.5
    OVERVIEW_CACHE_TTL_SECONDS = 1.0
    # pending / conflict 走数据库 + 可能有远程查询，单独缓存避免每次重建都触发
    PENDING_CACHE_TTL_SECONDS = 5.0
    CONFLICT_CACHE_TTL_SECONDS = 3.0
    WAITING_RETRY_CACHE_TTL_SECONDS = 3.0

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
        "garbled_filename_sample",
        "garbled_filename_score",
        "garbled_filename_score_before",
        "garbled_filename_score_after",
        "garbled_filename_repaired_count",
        "garbled_filename_codec_pairs_tried",
        "garbled_filename_guard_origin",
        "garbled_filename_top_samples",
        "garbled_filename_total_names",
        "garbled_filename_garbled_count",
        "garbled_filename_garbled_ratio",
        "garbled_filename_bypassed",
        "garbled_filename_bypass_origin",
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
        "ai_match_status",
        "ai_match_mode",
        "ai_auto_applied",
        "ai_match_model",
        "ai_confidence_threshold",
        "ai_low_confidence_count",
        "ai_unmatched_audio_count",
        "ai_unmatched_subtitle_count",
        # 前端 list 页 getTaskSummary / getOutputPath 直接读
        "subtitle_dir",
        # 社团补全批量任务：Tasks.vue 详情面板 + Dashboard 任务卡需要这些
        # 字段判断 is_batch 并渲染"批量补全 N 个社团"；缺这些字段会导致
        # summary 模式下 details.metadata 只能看到第一个社团名（错误展示）。
        "circle_query",
        "circle_queries",
        "circle_name",
        "circle_id",
        "is_batch",
        "is_refresh_all",
        "batch_total",
        "current_circle_query",
        "index_meta",
        "indexed_counts",
        # HTTP 下载平台展示
        "download_mode",
        "source_modes",
        "platforms",
        "platform_label",
        "url_count",
        "output_folder_name",
        "staging_dir",
        "final_output_path",
        "renamed_output_path",
        "output_finalize_status",
        "svip_speed",
        # Redis runtime overlay: summary 模式也要保留工作台需要的活跃运行态
        "download_runtime",
        "upload_runtime",
        "bonus_probe_meta",
        "progress_log",
        "awaiting_manual_match",
        "manual_match_completed",
        "manual_match_completed_at",
        "manual_match_applied_pairs",
        "manual_match_deleted_subtitles",
        "redis_runtime_updated_at",
    )

    REDIS_RUNTIME_METADATA_KEYS: tuple = (
        "download_runtime",
        "upload_runtime",
        "bonus_probe_meta",
        "progress_log",
        "awaiting_manual_match",
        "manual_match_completed",
        "manual_match_completed_at",
        "manual_match_applied_pairs",
        "manual_match_deleted_subtitles",
        "naming_strategy",
        "ai_match_status",
        "ai_match_mode",
        "ai_auto_applied",
        "ai_low_confidence_count",
        "ai_unmatched_audio_count",
        "ai_unmatched_subtitle_count",
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
        "http_download": "HTTP 下载",
        "baidu_netdisk": "百度网盘",
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
        TaskStatus.CANCELLED.value: "已取消",
        "partial_failed": "部分成功",
    }

    STATUS_PRIORITY = {
        TaskStatus.PROCESSING.value: 0,
        TaskStatus.WAITING_MANUAL.value: 1,
        TaskStatus.WAITING_RETRY.value: 2,
        TaskStatus.PENDING.value: 3,
        TaskStatus.PAUSED.value: 4,
        "partial_failed": 5,
        TaskStatus.FAILED.value: 6,
        TaskStatus.CANCELLED.value: 7,
        TaskStatus.COMPLETED.value: 8,
    }

    DOMAIN_PRIORITY = {
        "import": 0,
        "existing_folder": 1,
        "rj_subtitle": 2,
        "subtitle_import": 3,
        "asmr_sync": 4,
        "http_download": 5,
        "baidu_netdisk": 6,
        "upload": 7,
        "circle_completion": 8,
        "system": 9,
    }

    TASK_TYPE_TO_DOMAIN = {
        TaskType.AUTO_PROCESS: "import",
        TaskType.PROCESS_EXISTING_FOLDER: "existing_folder",
        TaskType.RJ_SUBTITLE_FETCH: "rj_subtitle",
        TaskType.ASMR_SYNC_DOWNLOAD: "asmr_sync",
        TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW: "asmr_sync",
        TaskType.HTTP_DOWNLOAD: "http_download",
        TaskType.BAIDU_NETDISK_DOWNLOAD: "baidu_netdisk",
        TaskType.BAIDU_NETDISK_UPLOAD: "baidu_netdisk",
        TaskType.LOCAL_LIBRARY_UPLOAD: "upload",
        TaskType.CIRCLE_COMPLETION_INDEX: "circle_completion",
        TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED: "circle_completion",
        TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH: "circle_completion",
        TaskType.CIRCLE_COMPLETION_BONUS_PROBE: "circle_completion",
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
        "http_download": "/asmr-sync?tab=http",
        "baidu_netdisk": "/asmr-sync?tab=baidu",
        "baidu_netdisk_upload": "/library",
        "upload": "/library",
        "circle_completion": "/circle-completion",
        "system": "/tasks",
    }

    def __init__(self):
        # detail 模式缓存（给 get_item 用）
        self._detail_cache: Optional[List[Dict[str, Any]]] = None
        self._detail_cache_signature: Optional[Tuple[Any, ...]] = None
        self._detail_cache_engine_version: Optional[int] = None
        self._detail_cache_at = 0.0
        # summary 模式缓存（给 list / overview 用）
        self._summary_cache: Optional[List[Dict[str, Any]]] = None
        self._summary_cache_signature: Optional[Tuple[Any, ...]] = None
        self._summary_cache_engine_version: Optional[int] = None
        self._summary_cache_at = 0.0
        # 子集缓存：pending imports / active conflicts，单独 TTL，避免每次重建都查库
        self._pending_cache: Optional[List[Dict[str, Any]]] = None
        self._pending_cache_at = 0.0
        self._conflict_cache: Optional[List[ConflictWork]] = None
        self._conflict_cache_at = 0.0
        self._waiting_retry_cache: Optional[List[Dict[str, Any]]] = None
        self._waiting_retry_cache_at = 0.0
        # summary 模式单任务快照缓存：任务未变化时避免重复 metadata 清洗和指标构建。
        self._summary_engine_item_cache: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
        self._overview_cache: Optional[Dict[str, Any]] = None
        self._overview_cache_at = 0.0

    def _safe_iso(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    def _safe_text(self, value: Any) -> str:
        return safe_text(value, strip=True)

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

    def _should_skip_directory_file_tree_snapshot(self, metadata: Dict[str, Any], domain: str) -> bool:
        return domain == "http_download"

    def _ensure_file_tree_metadata(
        self,
        metadata: Dict[str, Any],
        resolved_target_path: str,
        source_path: str,
        domain: str = "",
        task_status: str = "",
    ) -> Dict[str, Any]:
        enriched = dict(metadata)
        legacy_items = list(enriched.get("file_tree_items") or [])
        if legacy_items and not enriched.get("extracted_file_tree_items"):
            enriched["extracted_file_tree_items"] = legacy_items
            enriched["extracted_file_tree_root_path"] = self._safe_text(
                enriched.get("file_tree_root_path")
            )
            enriched["extracted_file_tree_root_label"] = self._safe_text(
                enriched.get("file_tree_root_label")
            )
        if self._should_skip_directory_file_tree_snapshot(metadata, domain):
            return enriched

        final_candidate_paths: List[str] = []
        for candidate in (
            metadata.get("renamed_output_path"),
            metadata.get("final_output_path"),
            metadata.get("target_path"),
            resolved_target_path,
            metadata.get("folder_path"),
        ):
            normalized = self._safe_text(candidate)
            if not normalized or normalized in final_candidate_paths:
                continue
            if os.path.isdir(normalized):
                final_candidate_paths.append(normalized)

        if not enriched.get("final_file_tree_items"):
            for candidate in final_candidate_paths:
                snapshot = self._snapshot_directory_items(candidate)
                if snapshot:
                    enriched["final_file_tree_items"] = snapshot
                    enriched["final_file_tree_root_path"] = candidate
                    enriched["final_file_tree_root_label"] = self._basename(candidate)
                    break

        if not enriched.get("extracted_file_tree_items"):
            extracted_candidates: List[str] = []
            for candidate in (
                metadata.get("staging_dir"),
                metadata.get("extract_dir"),
                metadata.get("output_path"),
                source_path,
            ):
                normalized = self._safe_text(candidate)
                if not normalized or normalized in extracted_candidates:
                    continue
                if os.path.isdir(normalized) and normalized not in final_candidate_paths:
                    extracted_candidates.append(normalized)
            for candidate in extracted_candidates:
                snapshot = self._snapshot_directory_items(candidate)
                if snapshot:
                    enriched["extracted_file_tree_items"] = snapshot
                    enriched["extracted_file_tree_root_path"] = candidate
                    enriched["extracted_file_tree_root_label"] = self._basename(candidate)
                    break

        completed = self._safe_text(task_status).lower() == TaskStatus.COMPLETED.value
        if completed and enriched.get("final_file_tree_items"):
            enriched["file_tree_view_kind"] = "final"
        elif enriched.get("extracted_file_tree_items"):
            enriched["file_tree_view_kind"] = "extracted_snapshot" if completed else "extracted"
        elif enriched.get("final_file_tree_items"):
            enriched["file_tree_view_kind"] = "final"
        return enriched

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
            return safe_json_value(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                safe_text(key): self._json_safe(current)
                for key, current in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(current) for current in value]
        return str(value)

    def _summary_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """任务列表/概览用轻量结构，避免轮询时反复传大 metadata。"""
        details = dict(item.get("details") or {})
        metadata = dict(details.get("metadata") or {}) if isinstance(details.get("metadata"), dict) else {}
        summary_metadata = self._build_summary_metadata(metadata)
        summary_details: Dict[str, Any] = {"metadata": summary_metadata} if summary_metadata else {}

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
            "platforms": list(item.get("platforms") or metadata.get("platforms") or []),
            "platform_label": self._safe_text(item.get("platform_label") or metadata.get("platform_label")),
            "download_mode": self._safe_text(item.get("download_mode") or metadata.get("download_mode")),
            "source_modes": list(item.get("source_modes") or metadata.get("source_modes") or []),
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

    def _engine_tasks_snapshot(self) -> List[Task]:
        """取一份与 TaskEngine.get_all_tasks 等价的轻量快照，供签名和序列化复用。"""
        engine = get_task_engine()
        for task in engine.tasks.values():
            engine._ensure_task_context(task)
        tasks = [task for task in engine.tasks.values() if not engine._is_hidden_task(task)]
        return sorted(tasks, key=lambda task: task.created_at, reverse=True)

    def _engine_signature_from_tasks(self, tasks: List[Task]) -> Tuple[Any, ...]:
        """内存里就能算出的引擎任务签名，避免每次缓存校验都查库。

        变化敏感字段（status / progress / current_step / error / completed_at）足以驱动
        UI 刷新；conflict / pending 走自己的 TTL 缓存，整体缓存仍受 TTL 兜底。
        """
        engine = get_task_engine()
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

    def _engine_signature(self) -> Tuple[Any, ...]:
        return self._engine_signature_from_tasks(self._engine_tasks_snapshot())

    def _engine_task_summary_cache_key(self, task: Task) -> Tuple[Any, ...]:
        return (
            task.id,
            getattr(getattr(task, "status", None), "value", str(getattr(task, "status", ""))),
            int(getattr(task, "progress", 0) or 0),
            self._safe_text(getattr(task, "current_step", "")),
            self._safe_text(getattr(task, "error_message", "")),
            self._safe_iso(getattr(task, "started_at", None)),
            self._safe_iso(getattr(task, "completed_at", None)),
            int(getattr(task, "metadata_version", lambda: 0)()),
        )

    def _serialize_engine_task_cached(self, task: Task, *, mode: str = "detail") -> Optional[Dict[str, Any]]:
        if self._safe_text(mode).lower() != "summary":
            return self._safe_serialize_engine_task(task, mode=mode)

        cache_key = self._engine_task_summary_cache_key(task)
        cached = self._summary_engine_item_cache.get(task.id)
        if cached and cached[0] == cache_key:
            return dict(cached[1])

        serialized = self._safe_serialize_engine_task(task, mode=mode)
        if serialized:
            self._summary_engine_item_cache[task.id] = (cache_key, dict(serialized))
        return serialized

    def _redis_runtime_for_task(self, task_id: str) -> Dict[str, Any]:
        if not task_id:
            return {}
        try:
            from .redis_service import get_redis_service

            payload = get_redis_service().get_task_runtime_sync(task_id)
            return dict(payload or {}) if isinstance(payload, dict) else {}
        except Exception:
            logger.debug("[Redis] 读取任务运行态失败: task_id=%s", task_id, exc_info=True)
            return {}

    def _merge_redis_runtime_item(self, item: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        if not item or not runtime:
            return item
        current_status = self._safe_text(item.get("status"))
        if current_status not in {
            TaskStatus.PENDING.value,
            TaskStatus.PROCESSING.value,
            TaskStatus.PAUSED.value,
            TaskStatus.WAITING_MANUAL.value,
            TaskStatus.WAITING_RETRY.value,
        }:
            return item
        status = self._safe_text(runtime.get("status"))
        if status not in {
            TaskStatus.PENDING.value,
            TaskStatus.PROCESSING.value,
            TaskStatus.PAUSED.value,
            TaskStatus.WAITING_MANUAL.value,
            TaskStatus.WAITING_RETRY.value,
        }:
            status = ""
        progress = runtime.get("progress")
        current_step = self._safe_text(runtime.get("current_step"))
        updated_at = self._safe_text(runtime.get("updated_at"))
        progress_log = runtime.get("progress_log")
        merged = dict(item)
        if status:
            merged["status"] = status
            merged["status_label"] = self.STATUS_LABELS.get(status, status)
        if progress is not None:
            try:
                merged["progress"] = int(progress or 0)
            except Exception:
                pass
        if current_step:
            merged["current_step"] = current_step
        if updated_at:
            merged["updated_at"] = updated_at
        details = dict(merged.get("details") or {})
        metadata = dict(details.get("metadata") or {})
        for key in self.REDIS_RUNTIME_METADATA_KEYS:
            if key not in runtime:
                continue
            value = runtime.get(key)
            if key == "progress_log" and isinstance(value, list):
                metadata[key] = list(value)[-80:]
            else:
                metadata[key] = self._json_safe(value)
        if current_step:
            metadata["current_step"] = current_step
        if updated_at:
            metadata["redis_runtime_updated_at"] = updated_at
        details["metadata"] = metadata
        merged["details"] = details
        return merged

    def _first_metadata_rjcode(self, metadata: Dict[str, Any]) -> str:
        for key in ("canonical_rjcode", "target_rjcode", "actual_rjcode", "rjcode"):
            normalized = self._normalize_rjcode(self._safe_text(metadata.get(key)))
            if normalized:
                return normalized
        for key in ("canonical_rjcodes", "rjcodes"):
            values = metadata.get(key)
            if not isinstance(values, (list, tuple)):
                continue
            for value in values:
                normalized = self._normalize_rjcode(self._safe_text(value))
                if normalized:
                    return normalized
        return ""

    def _circle_completion_route_hint(self, metadata: Dict[str, Any], rjcode: str = "") -> str:
        query = {}
        circle_id = self._safe_text(metadata.get("circle_id"))
        circle_name = (
            self._safe_text(metadata.get("circle_name"))
            or self._safe_text(metadata.get("circle_query"))
            or self._safe_text(metadata.get("current_circle_query"))
        )
        normalized_rjcode = self._normalize_rjcode(rjcode) or self._first_metadata_rjcode(metadata)
        if circle_id:
            query["circle_id"] = circle_id
        if circle_name:
            query["circle_name"] = circle_name
        if normalized_rjcode:
            query["rjcode"] = normalized_rjcode
        if not query:
            return self.DOMAIN_ROUTE_HINT["circle_completion"]
        return f"{self.DOMAIN_ROUTE_HINT['circle_completion']}?{urlencode(query)}"

    def _prune_summary_engine_item_cache(self, task_ids: set[str]) -> None:
        for task_id in list(self._summary_engine_item_cache):
            if task_id not in task_ids:
                self._summary_engine_item_cache.pop(task_id, None)

    def _engine_change_version(self) -> Optional[int]:
        """事件期维护的任务中心版本号；旧引擎实例缺字段时回退签名扫描。"""
        getter = getattr(get_task_engine(), "get_task_center_version", None)
        if not callable(getter):
            return None
        try:
            return int(getter())
        except Exception:
            return None

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
        stored_error_message = self._safe_text(metadata.get("error_message"))
        error_message = "" if is_retrying else stored_error_message
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

    def _build_engine_actions(self, task: Task, domain: str, *, check_retry_source: bool = True) -> List[str]:
        actions: List[str] = []
        if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
            actions.extend(["pause", "cancel"])
        elif task.status == TaskStatus.PAUSED:
            actions.extend(["resume", "cancel"])
        elif domain in {"http_download", "baidu_netdisk"} and task.status == TaskStatus.COMPLETED and list((task.task_metadata or {}).get("failed_files") or []):
            actions.extend(["retry", "delete"])
        elif task.status == TaskStatus.FAILED and self._can_retry_engine_task(task, domain, check_source_exists=check_retry_source):
            actions.extend(["retry", "delete"])
        elif task.status == TaskStatus.WAITING_RETRY and domain in {"import", "system"}:
            actions.extend(["retry_waiting", "delete"])
        elif task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            actions.append("delete")
        elif task.status == TaskStatus.WAITING_RETRY and domain == "asmr_sync":
            actions.extend(["retry_waiting", "delete_waiting_retry"])
        return actions

    def _can_retry_engine_task(self, task: Task, domain: str, *, check_source_exists: bool = True) -> bool:
        if domain in {"http_download", "baidu_netdisk"}:
            return task.status in {TaskStatus.FAILED, TaskStatus.COMPLETED}
        if domain not in {"import", "system"}:
            return False
        source_path = self._safe_text(getattr(task, "source_path", ""))
        if not source_path:
            return False
        if check_source_exists and not os.path.exists(source_path):
            return False
        return True

    def _resolve_display_status(self, task: Task, domain: str, metadata: Dict[str, Any]) -> str:
        cancel_text = " ".join(
            self._safe_text(value)
            for value in (
                getattr(task, "error_message", ""),
                getattr(task, "current_step", ""),
                metadata.get("cancel_reason"),
            )
            if self._safe_text(value)
        )
        if task.is_cancelled() or "用户取消" in cancel_text:
            return TaskStatus.CANCELLED.value
        if domain in {"http_download", "baidu_netdisk"}:
            failed_files = list(metadata.get("failed_files") or [])
            metrics = dict(metadata.get("performance_metrics") or {})
            success_count = int(metrics.get("success_count") or 0)
            if not success_count:
                transfer_rows = list(metadata.get("download_files") or []) + list(metadata.get("upload_files") or [])
                success_count = sum(
                    1 for row in transfer_rows
                    if isinstance(row, dict) and self._safe_text(row.get("status")).lower() == "completed"
                )
            if failed_files and success_count > 0:
                return "partial_failed"
        if domain == "rj_subtitle":
            if bool(metadata.get("manual_match_completed")):
                return TaskStatus.COMPLETED.value
            if task.status == TaskStatus.COMPLETED:
                return TaskStatus.PENDING.value
        if domain == "asmr_sync" and task.status == TaskStatus.COMPLETED:
            failed_files = list(metadata.get("failed_files") or [])
            verification_failures = list(metadata.get("verification_failures") or [])
            failure_reason = self._safe_text(metadata.get("failure_reason"))
            metrics = dict(metadata.get("performance_metrics") or {})
            success_count = int(metrics.get("success_count") or 0)
            if not success_count:
                transfer_rows = list(metadata.get("downloaded_resources") or []) + list(metadata.get("uploaded_files") or [])
                success_count = len([row for row in transfer_rows if isinstance(row, dict)])
            if success_count > 0 and (failed_files or verification_failures or failure_reason):
                return "partial_failed"
        return task.status.value

    def _serialize_engine_task(self, task: Task, *, mode: str = "detail") -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        domain = self._infer_domain(task)
        if domain in {"http_download", "baidu_netdisk"}:
            if domain == "baidu_netdisk":
                metadata = sanitize_baidu_netdisk_metadata(metadata)
            else:
                metadata = sanitize_http_download_metadata(metadata)
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
            metadata = self._ensure_file_tree_metadata(
                metadata,
                resolved_target_path,
                source_path,
                domain,
                task.status.value,
            )
        rjcode = self._normalize_rjcode(
            self._safe_text(getattr(task, "rjcode", ""))
            or self._first_metadata_rjcode(metadata)
            or self._safe_text(metadata.get("target_rjcode"))
            or self._safe_text(metadata.get("actual_rjcode"))
            or self._safe_text(metadata.get("rjcode"))
        )
        route_hint = self.DOMAIN_ROUTE_HINT.get(domain, "/tasks")

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
            if metadata.get("ai_match_mode") and metadata.get("ai_match_mode") != "rule":
                self._append_metric(metrics, "AI", "自动应用" if metadata.get("ai_auto_applied") else "待确认")
            if metadata.get("awaiting_manual_match"):
                self._append_metric(metrics, "待手配", "是")
        elif domain == "asmr_sync":
            is_reimport_task = source_action in {"reimport_local_download_root", "reimport_downloaded_session"}
            is_folder_completion = source_action == "folder_completion"
            is_folder_completion_preview = task.type == TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW
            if is_folder_completion_preview:
                title = "补全文件夹检查"
            elif is_folder_completion:
                title = self._safe_text(metadata.get("work_title")) or rjcode or self._basename(source_path) or "补全文件夹下载"
            else:
                title = self._safe_text(metadata.get("work_title")) or rjcode or self._basename(source_path) or ("直接入库任务" if is_reimport_task else "ASMR 同步任务")
            subtitle = self._safe_text(metadata.get("subtitle_folder")) or source_path
            source_label = source_label or ("音声补全 / 补全文件夹" if is_folder_completion else ("直接入库" if is_reimport_task else "ASMR 同步下载"))
            source_action = source_action or ("reimport_downloaded_session" if is_reimport_task else "asmr_sync_start")
            source_page = source_page or ("library" if is_folder_completion else ("circle-completion" if is_reimport_task else "asmr-sync"))
            sync_result = dict(metadata.get("sync_result") or {})
            verify_summary = dict(metadata.get("verify_summary") or {})
            upload_summary = dict(metadata.get("upload_summary") or {})
            performance_metrics = dict(metadata.get("performance_metrics") or {})
            if is_folder_completion_preview:
                folder_summary = dict(metadata.get("folder_completion_summary") or {})
                self._append_metric(metrics, "目录", metadata.get("selected_count"))
                self._append_metric(metrics, "可补全", folder_summary.get("downloadable_count") or metadata.get("downloadable_count"))
                self._append_metric(metrics, "缺失文件", folder_summary.get("missing_file_count") or metadata.get("missing_file_count"))
                self._append_metric(metrics, "预计", self._format_bytes(folder_summary.get("estimated_bytes")) if folder_summary.get("estimated_bytes") else None)
            else:
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
                # ★ Bug 修复（2026-05-21）：批量补全任务卡 title/subtitle 错乱。
                # 此前 ``is_batch=True`` 但 ``is_refresh_all=False`` 时没有专门分支，落到
                # 单社团 fallback：``title = metadata.circle_name``（一直是第一个社团名，例如
                # "Clover Voice"），``subtitle = metadata.circle_query``（被 task_engine 循环
                # 改成"当前正在跑的社团名"，例如 "Whisp"）。结果任务卡顶部显示 "Clover Voice"
                # + "Whisp" 两个不同社团名，前端没法看出这是"批量补全 2 个社团"。
                # 修复：批量任务统一显示批量元信息，subtitle 显示当前进度 / 当前正在处理的社团。
                circle_queries_list = [
                    str(value or "").strip()
                    for value in (metadata.get("circle_queries") or [])
                    if str(value or "").strip()
                ]
                is_batch = bool(metadata.get("is_batch")) or len(circle_queries_list) > 1
                batch_total = int(metadata.get("batch_total") or 0) or len(circle_queries_list)
                completed_queries = int(index_meta.get("completed_queries") or 0)
                failed_queries = int(index_meta.get("failed_queries") or 0)
                if is_batch:
                    batch_rows = [
                        item for item in list(metadata.get("batch_circle_summaries") or [])
                        if isinstance(item, dict) and item.get("success", True)
                    ]
                    if batch_rows:
                        indexed_counts = {
                            **indexed_counts,
                            "works": sum(int(item.get("works") or 0) for item in batch_rows),
                            "local_owned_count": sum(int(item.get("local_owned_count") or 0) for item in batch_rows),
                            "owned_count": sum(int(item.get("kikoeru_owned_count") or 0) for item in batch_rows),
                            "dl_count": sum(int(item.get("dl_count") or 0) for item in batch_rows),
                            "asmr_available_count": sum(int(item.get("asmr_available_count") or 0) for item in batch_rows),
                            "downloadable_count": sum(int(item.get("downloadable_count") or 0) for item in batch_rows),
                            "missing_count": sum(int(item.get("missing_count") or 0) for item in batch_rows),
                        }
                        index_meta = {
                            **index_meta,
                            "combined_candidates_count": indexed_counts.get("works"),
                            "aggregated_count": indexed_counts.get("works"),
                            "dlsite_candidates_count": indexed_counts.get("dl_count"),
                            "asmr_available_count": indexed_counts.get("asmr_available_count"),
                        }
                current_circle = (
                    self._safe_text(index_meta.get("current_circle_query"))
                    or self._safe_text(metadata.get("current_circle_query"))
                    or self._safe_text(metadata.get("circle_query"))
                )
                if bool(metadata.get("is_refresh_all")):
                    title = "全部刷新社团索引"
                    subtitle = self._safe_text(metadata.get("source_label")) or f"{batch_total} 个社团"
                elif is_batch:
                    title = self._safe_text(metadata.get("source_label")) or f"批量补全 {batch_total} 个社团"
                    if task.status == TaskStatus.PROCESSING and current_circle:
                        done = completed_queries + failed_queries
                        position = min(done + 1, batch_total) if batch_total else done + 1
                        subtitle = f"正在处理 {current_circle}（{position}/{batch_total}）" if batch_total else f"正在处理 {current_circle}"
                    elif task.status == TaskStatus.PENDING:
                        subtitle = "排队中" + (f"，共 {batch_total} 个社团" if batch_total else "")
                    elif task.status in (TaskStatus.PAUSED, TaskStatus.FAILED):
                        subtitle = f"已完成 {completed_queries}/{batch_total}" + (f"，失败 {failed_queries}" if failed_queries else "")
                    else:
                        # COMPLETED 等终态：列出第一个 / 最后一个社团名做摘要
                        head_name = circle_queries_list[0] if circle_queries_list else current_circle
                        tail_hint = "..." if len(circle_queries_list) > 1 else ""
                        subtitle = f"{head_name}{tail_hint}（成功 {completed_queries} / 失败 {failed_queries}）" if head_name else f"完成 {completed_queries} / 失败 {failed_queries}"
                else:
                    title = self._safe_text(metadata.get("circle_name")) or self._safe_text(metadata.get("circle_query")) or "社团索引任务"
                    subtitle = self._safe_text(metadata.get("circle_id")) or self._safe_text(metadata.get("circle_query"))
                if is_batch:
                    self._append_metric(metrics, "批量", f"{batch_total} 个社团" if batch_total else None)
                    self._append_metric(metrics, "进度", f"{completed_queries}/{batch_total}" if batch_total else None)
                    if failed_queries > 0:
                        self._append_metric(metrics, "失败", failed_queries)
                    if task.status == TaskStatus.PROCESSING and current_circle:
                        self._append_metric(metrics, "当前", current_circle)
                self._append_metric(metrics, "候选", index_meta.get("combined_candidates_count") or index_meta.get("aggregated_count"))
                self._append_metric(metrics, "DLsite", index_meta.get("dlsite_candidates_count") or index_meta.get("dlsite_profile_total") or indexed_counts.get("dl_count"))
                self._append_metric(metrics, "可下载", index_meta.get("asmr_available_count") or indexed_counts.get("downloadable_count"))
                self._append_metric(metrics, "本地", indexed_counts.get("local_owned_count"))
                self._append_metric(metrics, "缺失", indexed_counts.get("missing_count"))
            elif task.type == TaskType.CIRCLE_COMPLETION_BONUS_PROBE:
                bonus_summary = dict(metadata.get("bonus_probe_summary") or {})
                release_dates = [
                    self._safe_text(value)
                    for value in list(metadata.get("release_dates") or [])
                    if self._safe_text(value)
                ]
                auto_source_labels = {source_path, task.type.value, TaskType.CIRCLE_COMPLETION_BONUS_PROBE.value}
                explicit_source_label = source_label if source_label and source_label not in auto_source_labels else ""
                source_label = explicit_source_label or "社团补全 / 特典补全"
                title = explicit_source_label or self._safe_text(metadata.get("circle_name")) or "特典补全"
                if task.status == TaskStatus.PROCESSING:
                    current_date = self._safe_text((metadata.get("bonus_probe_meta") or {}).get("release_date"))
                    subtitle = f"正在探测 {current_date}" if current_date else "正在探测隐藏特典"
                elif task.status == TaskStatus.PENDING:
                    subtitle = f"排队中，{len(release_dates)} 个发售日" if release_dates else "排队中"
                else:
                    subtitle = f"写入 {int(bonus_summary.get('inserted_count') or 0)} 个隐藏特典"
                self._append_metric(metrics, "发售日", len(release_dates) if release_dates else None)
                self._append_metric(metrics, "候选筛选", bonus_summary.get("candidate_count"))
                self._append_metric(metrics, "缓存跳过", bonus_summary.get("cached_candidate_count"))
                self._append_metric(metrics, "实际探测", bonus_summary.get("probe_count"))
                self._append_metric(metrics, "命中", bonus_summary.get("hit_count"))
                self._append_metric(metrics, "写入", bonus_summary.get("inserted_count"))
                self._append_metric(metrics, "请求", bonus_summary.get("request_count"))
            else:
                title = self._safe_text(metadata.get("circle_name")) or self._safe_text(metadata.get("work_title")) or rjcode or "社团补全任务"
                subtitle = self._safe_text(metadata.get("canonical_rjcode")) or self._safe_text(metadata.get("circle_id"))
                self._append_metric(metrics, "RJ", rjcode)
                self._append_metric(metrics, "Canonical", metadata.get("canonical_rjcode"))
                self._append_metric(metrics, "资源数", metadata.get("selected_resource_count"))
            source_label = source_label or "社团补全"
            if task.type == TaskType.CIRCLE_COMPLETION_INDEX and not source_action:
                source_action = "index_start"
            elif task.type == TaskType.CIRCLE_COMPLETION_BONUS_PROBE and source_action in {
                "",
                TaskType.CIRCLE_COMPLETION_BONUS_PROBE.value,
            }:
                source_action = "bonus_probe"
            elif not source_action:
                source_action = "batch_download"
            source_page = source_page or "circle-completion"
            route_hint = self._circle_completion_route_hint(metadata, rjcode)
        elif domain == "http_download":
            download_files = list(metadata.get("download_files") or [])
            failed_files = list(metadata.get("failed_files") or [])
            download_runtime = dict(metadata.get("download_runtime") or {})
            download_mode = self._safe_text(metadata.get("download_mode")) or "http"
            platforms = http_download_platforms_from_metadata(metadata)
            platform_label = self._safe_text(metadata.get("platform_label")) or http_download_platforms_label(platforms)
            current_file_name = self._safe_text(download_runtime.get("current_file_name"))
            primary_file_name = ""
            for file_row in download_files:
                if not isinstance(file_row, dict):
                    continue
                primary_file_name = self._safe_text(file_row.get("name")) or self._safe_text(file_row.get("filename"))
                if primary_file_name:
                    break
            default_download_title = build_http_download_batch_title(
                {
                    **metadata,
                    "platforms": platforms,
                    "platform_label": platform_label,
                },
                item_count=len(download_files),
                fallback_host=self._basename(source_path) or source_path,
            )
            title = self._safe_text(metadata.get("batch_name")) or self._safe_text(metadata.get("source_label")) or default_download_title
            if len(download_files) == 1:
                title = self._safe_text(download_files[0].get("name")) or title
            subtitle = (
                self._safe_text(metadata.get("workbench_subtitle"))
                or current_file_name
                or primary_file_name
                or self._safe_text(metadata.get("download_root"))
                or output_path
                or source_path
            )
            source_label = source_label or default_download_title
            source_action = source_action or (f"manual_{download_mode}_download" if download_mode not in {"http", "mixed"} else "manual_http_download")
            source_page = source_page or "asmr-sync"
            route_hint = self.DOMAIN_ROUTE_HINT["http_download"]
            metadata["platforms"] = platforms
            metadata["platform_label"] = platform_label
            total_bytes = int(
                download_runtime.get("total_bytes")
                or sum(int((item or {}).get("total") or (item or {}).get("size") or 0) for item in download_files)
                or 0
            )
            transferred = int(download_runtime.get("transferred_bytes") or 0)
            speed = int(download_runtime.get("speed_bytes_per_sec") or 0)
            self._append_metric(metrics, "文件", len(download_files) if download_files else metadata.get("url_count"))
            self._append_metric(metrics, "完成", download_runtime.get("completed_files"))
            self._append_metric(metrics, "失败", len(failed_files) or download_runtime.get("failed_files"))
            self._append_metric(metrics, "大小", self._format_bytes(total_bytes) if total_bytes else None)
            self._append_metric(metrics, "已下载", self._format_bytes(transferred) if transferred else None)
            self._append_metric(metrics, "速度", f"{self._format_bytes(speed)}/s" if speed else None)
            self._append_metric(metrics, "来源", platform_label if platform_label and platform_label != "HTTP" else http_download_platform_label(download_mode))
            self._append_metric(metrics, "目录", self._safe_text(metadata.get("download_root")) or output_path or source_path)
        elif domain == "baidu_netdisk" and task.type == TaskType.BAIDU_NETDISK_UPLOAD:
            upload_files = list(metadata.get("upload_files") or [])
            failed_files = list(metadata.get("failed_files") or [])
            upload_runtime = dict(metadata.get("upload_runtime") or {})
            total_bytes = int(
                upload_runtime.get("total_bytes")
                or sum(int((item or {}).get("size") or (item or {}).get("size_bytes") or 0) for item in upload_files)
                or 0
            )
            transferred = int(upload_runtime.get("transferred_bytes") or 0)
            speed = int(upload_runtime.get("speed_bytes_per_sec") or 0)
            remote_dir = self._safe_text(metadata.get("remote_dir"))
            title = self._safe_text(metadata.get("batch_name")) or self._safe_text(metadata.get("source_label")) or "百度网盘上传"
            if len(upload_files) == 1:
                title = self._safe_text(upload_files[0].get("name")) or title
            subtitle = remote_dir or output_path or source_path
            source_label = source_label or "百度网盘上传"
            source_action = source_action or "manual_baidu_netdisk_upload"
            source_page = source_page or "library"
            route_hint = self.DOMAIN_ROUTE_HINT["baidu_netdisk_upload"]
            metadata["platforms"] = ["baidu_netdisk"]
            metadata["platform_label"] = "百度网盘"
            self._append_metric(metrics, "文件", len(upload_files) if upload_files else metadata.get("source_count"))
            self._append_metric(metrics, "完成", upload_runtime.get("completed_files"))
            self._append_metric(metrics, "失败", len(failed_files) or upload_runtime.get("failed_files"))
            self._append_metric(metrics, "大小", self._format_bytes(total_bytes) if total_bytes else None)
            self._append_metric(metrics, "已上传", self._format_bytes(transferred) if transferred else None)
            self._append_metric(metrics, "速度", f"{self._format_bytes(speed)}/s" if speed else None)
            self._append_metric(metrics, "远端目录", remote_dir)
        elif domain == "baidu_netdisk":
            download_files = list(metadata.get("download_files") or [])
            failed_files = list(metadata.get("failed_files") or [])
            download_runtime = dict(metadata.get("download_runtime") or {})
            total_bytes = int(
                download_runtime.get("total_bytes")
                or sum(int((item or {}).get("total") or (item or {}).get("size") or 0) for item in download_files)
                or 0
            )
            transferred = int(download_runtime.get("transferred_bytes") or 0)
            speed = int(download_runtime.get("speed_bytes_per_sec") or 0)
            output_folder_name = self._safe_text(metadata.get("output_folder_name"))
            final_output_path = self._safe_text(metadata.get("renamed_output_path")) or self._safe_text(metadata.get("final_output_path"))
            title = self._safe_text(metadata.get("batch_name")) or self._safe_text(metadata.get("source_label")) or build_baidu_netdisk_batch_title(metadata, item_count=len(download_files))
            if len(download_files) == 1:
                title = self._safe_text(download_files[0].get("name")) or title
            subtitle = final_output_path or self._safe_text(metadata.get("staging_dir")) or output_path or source_path
            source_label = source_label or "百度网盘"
            source_action = source_action or "manual_baidu_netdisk_download"
            source_page = source_page or "asmr-sync"
            route_hint = self.DOMAIN_ROUTE_HINT["baidu_netdisk"]
            metadata["platforms"] = ["baidu_netdisk"]
            metadata["platform_label"] = "百度网盘"
            metadata["download_mode"] = "baidu_netdisk"
            self._append_metric(metrics, "文件", len(download_files) if download_files else metadata.get("url_count"))
            self._append_metric(metrics, "完成", download_runtime.get("completed_files"))
            self._append_metric(metrics, "失败", len(failed_files) or download_runtime.get("failed_files"))
            self._append_metric(metrics, "大小", self._format_bytes(total_bytes) if total_bytes else None)
            self._append_metric(metrics, "已下载", self._format_bytes(transferred) if transferred else None)
            self._append_metric(metrics, "速度", f"{self._format_bytes(speed)}/s" if speed else None)
            self._append_metric(metrics, "保存为", output_folder_name)
            self._append_metric(metrics, "最终目录", final_output_path)
            self._append_metric(metrics, "模式", "SVIP 高速" if bool(metadata.get("svip_speed")) else "百度网盘")
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
        if task.status == TaskStatus.COMPLETED and recovered_notice:
            current_step = recovered_notice

        # 关键优化：summary 模式下只挑几个必要的键，跳过全量深拷贝
        if mode == "detail":
            details_metadata = self._json_safe(metadata)
        else:
            details_metadata = self._build_summary_metadata(metadata)

        item = {
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
            "platforms": list(metadata.get("platforms") or []),
            "platform_label": self._safe_text(metadata.get("platform_label")),
            "download_mode": self._safe_text(metadata.get("download_mode")),
            "source_modes": list(metadata.get("source_modes") or []),
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
            "actions": self._build_engine_actions(task, domain, check_retry_source=(mode == "detail")),
            "details": {
                "type": task.type.value,
                "metadata": details_metadata,
            },
        }
        runtime = self._redis_runtime_for_task(task.id)
        return self._merge_redis_runtime_item(item, runtime)

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

            candidate_details = dict(candidate.get("details") or {})
            candidate_metadata = dict(candidate_details.get("metadata") or {})
            retry_failed_task_id = self._safe_text(candidate_metadata.get("retry_failed_task_id"))
            if retry_failed_task_id and retry_failed_task_id == item_id:
                candidate_created_at = self._last_timestamp(candidate)
                if not candidate_created_at or not completed_at or candidate_created_at >= completed_at:
                    return True

            if self._safe_text(candidate.get("status")) != TaskStatus.COMPLETED.value:
                continue

            candidate_completed_at = self._last_timestamp(candidate)
            if candidate_completed_at and completed_at and candidate_completed_at < completed_at:
                continue

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

    async def _get_active_conflicts_cached(self) -> List[ConflictWork]:
        """active conflicts 单独 TTL 缓存，避免每次重建都查一次 ConflictWork 表。"""
        now = time.monotonic()
        if (
            self._conflict_cache is not None
            and now - self._conflict_cache_at <= self.CONFLICT_CACHE_TTL_SECONDS
        ):
            return list(self._conflict_cache)
        try:
            fetched = await asyncio.to_thread(self._load_active_conflicts)
            self._conflict_cache = list(fetched or [])
            self._conflict_cache_at = now
            return list(self._conflict_cache)
        except Exception:
            logger.exception("[任务中心] 读取问题作品列表失败，当前轮次已跳过 conflict items")
            return list(self._conflict_cache or [])

    async def _get_waiting_retry_items_cached(self) -> List[Dict[str, Any]]:
        """waiting retry 单独 TTL 缓存，避免任务中心刷新频繁时反复查库。"""
        now = time.monotonic()
        if (
            self._waiting_retry_cache is not None
            and now - self._waiting_retry_cache_at <= self.WAITING_RETRY_CACHE_TTL_SECONDS
        ):
            return list(self._waiting_retry_cache)
        try:
            fetched = await asyncio.to_thread(get_task_engine().get_waiting_retry_tasks_from_db)
            self._waiting_retry_cache = list(fetched or [])
            self._waiting_retry_cache_at = now
            return list(self._waiting_retry_cache)
        except Exception:
            logger.exception("[任务中心] 读取等待重试任务失败，当前轮次已跳过 waiting retry items")
            return list(self._waiting_retry_cache or [])

    def _build_overview_counts(self, items: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
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

        return {
            "counts_by_domain": counts_by_domain,
            "counts_by_status": counts_by_status,
            "highlight_counts": {
                "processing": counts_by_status.get(TaskStatus.PROCESSING.value, 0),
                "waiting_total": (
                    counts_by_status.get(TaskStatus.PENDING.value, 0)
                    + counts_by_status.get(TaskStatus.PAUSED.value, 0)
                    + counts_by_status.get(TaskStatus.WAITING_MANUAL.value, 0)
                    + counts_by_status.get(TaskStatus.WAITING_RETRY.value, 0)
                ),
                "completed": counts_by_status.get(TaskStatus.COMPLETED.value, 0),
                "waiting_manual": counts_by_status.get(TaskStatus.WAITING_MANUAL.value, 0),
                "waiting_retry": counts_by_status.get(TaskStatus.WAITING_RETRY.value, 0),
                "partial_failed": counts_by_status.get("partial_failed", 0),
                "failed": counts_by_status.get(TaskStatus.FAILED.value, 0),
            },
        }

    async def _build_all_items(self, *, mode: str = "detail") -> List[Dict[str, Any]]:
        """根据 mode 选择 detail / summary 两套独立缓存。summary 跳过重 IO。"""
        now = time.monotonic()
        is_summary = self._safe_text(mode).lower() == "summary"

        if is_summary:
            cache_data = self._summary_cache
            cache_signature = self._summary_cache_signature
            cache_engine_version = self._summary_cache_engine_version
            cache_at = self._summary_cache_at
            ttl = self.SUMMARY_CACHE_TTL_SECONDS
        else:
            cache_data = self._detail_cache
            cache_signature = self._detail_cache_signature
            cache_engine_version = self._detail_cache_engine_version
            cache_at = self._detail_cache_at
            ttl = self.CACHE_TTL_SECONDS

        engine_tasks_snapshot: Optional[List[Task]] = None
        engine_version_now = self._engine_change_version()

        # 热路径：缓存未过期且事件期版本号未变，直接返回，避免为签名扫描所有任务。
        if cache_data is not None and now - cache_at <= ttl:
            if engine_version_now is not None and engine_version_now == cache_engine_version:
                return list(cache_data)
            engine_tasks_snapshot = self._engine_tasks_snapshot()
            engine_signature_now = self._engine_signature_from_tasks(engine_tasks_snapshot)
            if engine_signature_now == cache_signature:
                if is_summary:
                    self._summary_cache_engine_version = engine_version_now
                else:
                    self._detail_cache_engine_version = engine_version_now
                return list(cache_data)
        else:
            engine_signature_now = None

        if engine_signature_now is None:
            engine_tasks_snapshot = self._engine_tasks_snapshot()
            engine_signature_now = self._engine_signature_from_tasks(engine_tasks_snapshot)

        # 冷路径：重建。engine tasks 走对应 mode 的序列化；pending / conflict 走子集缓存。
        if engine_tasks_snapshot is None:
            engine_tasks_snapshot = self._engine_tasks_snapshot()
        if is_summary:
            self._prune_summary_engine_item_cache({task.id for task in engine_tasks_snapshot})
        items: List[Dict[str, Any]] = [
            serialized
            for serialized in (
                self._serialize_engine_task_cached(task, mode=mode)
                for task in engine_tasks_snapshot
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

        waiting_retry_items = await self._get_waiting_retry_items_cached()
        items.extend(
            serialized
            for serialized in (
                self._safe_serialize_waiting_retry_item(item, mode=mode)
                for item in waiting_retry_items
            )
            if serialized
        )

        active_conflicts = await self._get_active_conflicts_cached()
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
            self._summary_cache_engine_version = engine_version_now
            self._summary_cache_at = completed_at
        else:
            self._detail_cache = list(items)
            self._detail_cache_signature = engine_signature_now
            self._detail_cache_engine_version = engine_version_now
            self._detail_cache_at = completed_at
        return items

    async def backfill_materialized_items(self) -> Dict[str, Any]:
        """用旧聚合器输出回填任务中心物化表，并返回对照 diff。

        当前阶段只作为迁移/诊断入口，不改变 list_items 的读路径。
        """
        from .task_center_materialization_service import get_task_center_materialization_service

        engine_tasks_snapshot = self._engine_tasks_snapshot()
        metadata_by_task_id = {
            task.id: dict(getattr(task, "task_metadata", None) or {})
            for task in engine_tasks_snapshot
        }
        items = await self._build_all_items(mode="summary")
        service = get_task_center_materialization_service()
        version = self._engine_change_version() or 0
        upserted = service.upsert_items(
            items,
            version=version,
            metadata_by_task_id=metadata_by_task_id,
        )
        valid_item_ids = {
            self._safe_text(item.get("id"))
            for item in items
        }
        pruned = service.prune_items(valid_item_ids)
        diff = service.diff_items(items)
        return {
            "item_count": len(items),
            "engine_item_count": len([item for item in items if self._safe_text(item.get("id")).startswith("engine:")]),
            "upserted": upserted,
            "pruned": pruned,
            "version": version,
            **diff,
        }

    def list_materialized_items(
        self,
        *,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """任务中心物化表 SQL 读路径预览，暂不接管正式 API。"""
        from .task_center_materialization_service import get_task_center_materialization_service

        service = get_task_center_materialization_service()
        result = service.list_items(
            limit=5000,
            offset=0,
        )
        all_items = self._dedupe_items(list(result.get("items") or []))
        all_items = [item for item in all_items if not self._is_superseded_failed_item(item)]
        all_items = self._sort_items(all_items)
        counts = self._build_overview_counts(all_items)
        filtered_items = self._filter_items(all_items, domain=domain, status=status, search=search)
        safe_limit = max(1, min(int(limit or 200), 500))
        safe_offset = max(0, int(offset or 0))
        return {
            "items": filtered_items[safe_offset:safe_offset + safe_limit],
            "total": len(filtered_items),
            "offset": safe_offset,
            "limit": safe_limit,
            **counts,
            "mode": "materialized_summary",
            "generated_at": datetime.now().isoformat(),
        }

    def list_materialized_engine_items(self, **kwargs) -> Dict[str, Any]:
        """兼容旧诊断接口名。"""
        return self.list_materialized_items(**kwargs)

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
                    "task_metadata_preview": self._json_safe(
                        sanitize_baidu_netdisk_metadata(getattr(task, "task_metadata", None))
                        if getattr(getattr(task, "type", None), "value", getattr(task, "type", "")) == TaskType.BAIDU_NETDISK_DOWNLOAD.value
                        else (
                            sanitize_http_download_metadata(getattr(task, "task_metadata", None))
                            if getattr(getattr(task, "type", None), "value", getattr(task, "type", "")) == TaskType.HTTP_DOWNLOAD.value
                            else getattr(task, "task_metadata", None)
                        )
                    ),
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
        if normalized_mode == "summary" and os.getenv("KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY", "").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                materialized = self.list_materialized_items(
                    domain=domain,
                    status=status,
                    search=search,
                    limit=safe_limit,
                    offset=safe_offset,
                )
                if materialized.get("items") or int(materialized.get("total") or 0) > 0:
                    return materialized
            except Exception:
                logger.warning("[任务中心] 物化 summary 读路径失败，回退旧聚合", exc_info=True)
        # 顶层防御：底层任意环节抛错都回退到"空列表 + 200"，避免整个任务中心
        # 因为单条任务序列化异常被拖成 500。具体异常已经在底层 logger.exception 记录。
        try:
            items = await self._build_all_items(mode=normalized_mode)
        except Exception:
            logger.exception("[任务中心] _build_all_items 顶层异常，返回空列表兜底")
            items = []
        counts = self._build_overview_counts(items)
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
            **counts,
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
        now = time.monotonic()
        if self._overview_cache is not None and now - self._overview_cache_at <= self.OVERVIEW_CACHE_TTL_SECONDS:
            return copy.deepcopy(self._overview_cache)

        # overview 只用来统计 + 提取 top items，summary 模式足矣
        # 顶层防御：底层异常时返回零数据兜底，避免 dashboard 头部 500。
        try:
            items = await self._build_all_items(mode="summary")
        except Exception:
            logger.exception("[任务中心] get_overview 顶层异常，返回零数据兜底")
            items = []
        counts = self._build_overview_counts(items)
        counts_by_status = counts["counts_by_status"]

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
            if item.get("status") in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}
        ]

        result = {
            "generated_at": datetime.now().isoformat(),
            "total": len(items),
            **counts,
            "recent_items": [self._summary_item(item) for item in recent_terminal_items[:60]],
            "active_items": [self._summary_item(item) for item in active_items[:60]],
        }
        self._overview_cache = copy.deepcopy(result)
        self._overview_cache_at = time.monotonic()
        return result

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
            if normalized_action == "delete":
                try:
                    removed = await asyncio.to_thread(engine.remove_task, engine_task_id)
                except Exception as exc:
                    from .filter_recovery_service import FilterRecoveryError

                    if isinstance(exc, FilterRecoveryError):
                        raise ValueError(str(exc)) from exc
                    raise
                if removed:
                    return {"success": True, "message": "任务记录已删除"}
                raise ValueError("任务不存在")
            if normalized_action == "retry_waiting":
                if engine.retry_task(engine_task_id):
                    return {"success": True, "message": "任务已加入重试队列"}
                raise ValueError("任务不在等待重试状态")
            if normalized_action == "retry":
                if self._infer_domain(task) == "http_download":
                    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
                        raise ValueError("任务仍在执行中，不能重试")
                    from .http_download_service import get_http_download_service

                    await get_http_download_service().reset_task_for_retry(task)
                    await engine.queue.put(task)
                    return {
                        "success": True,
                        "message": "HTTP 下载任务已加入重试队列",
                        "route_hint": self.DOMAIN_ROUTE_HINT["http_download"],
                    }
                if self._infer_domain(task) == "baidu_netdisk":
                    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
                        raise ValueError("任务仍在执行中，不能重试")
                    from .baidu_netdisk_service import get_baidu_netdisk_service

                    await get_baidu_netdisk_service().reset_task_for_retry(task)
                    await engine.queue.put(task)
                    return {
                        "success": True,
                        "message": "百度网盘下载任务已加入重试队列",
                        "route_hint": self.DOMAIN_ROUTE_HINT["baidu_netdisk"],
                    }
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
