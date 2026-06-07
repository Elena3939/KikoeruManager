import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_config
from .asmr_resource_service import get_asmr_resource_service
from .library_manager import get_library_manager
from .rjcode_utils import extract_rjcode
from .task_engine import Task, TaskType, get_task_engine

logger = logging.getLogger(__name__)


MAX_FOLDER_COMPLETION_TARGETS = 100
FOLDER_COMPLETION_ASMR_CONCURRENCY = 4
IGNORED_CONTAINER_CHILDREN = {"__macosx", "_conflicts", "subtitles", ".git", ".svn", "__pycache__"}


@dataclass
class FolderCompletionTarget:
    library_id: str
    rjcode: str
    folder_path: str
    folder_name: str
    source_path: str
    source_name: str
    source_kind: str


class LibraryFolderCompletionService:
    """库存页“补全文件夹”：本地 RJ 目录缺失资源预览与下载任务创建。"""

    def __init__(self):
        self.manager = get_library_manager()
        self.resource_service = get_asmr_resource_service()
        self.asmr_service = self.resource_service.asmr_service

    def _get_local_library(self, library_id: str):
        normalized_library_id = str(library_id or "").strip()
        if not normalized_library_id:
            raise ValueError("缺少库存")
        library = self.manager.get_library_definition(normalized_library_id)
        if library.type != "local":
            raise ValueError("补全文件夹第一版仅支持本地库存")
        if not getattr(library, "writable", True):
            raise PermissionError("当前库存只读，不能补全文件夹")
        return library

    def _normalize_local_path(self, library, path: str) -> str:
        raw_path = str(path or "").strip()
        if not raw_path:
            raise ValueError("缺少目录路径")
        target_path = os.path.abspath(os.path.normpath(raw_path))
        browse_root = os.path.abspath(os.path.normpath(library.browse_root_path or library.root_path))
        if not self.manager._local_path_is_within_root(target_path, browse_root):
            raise PermissionError("目录不在当前库存浏览根内")
        if not os.path.isdir(target_path):
            raise ValueError(f"不是可补全的目录: {raw_path}")
        return target_path

    @staticmethod
    def _path_key(path: str) -> str:
        normalized = os.path.abspath(os.path.normpath(str(path or "")))
        return os.path.normcase(normalized) if os.name == "nt" else normalized

    @staticmethod
    def _target_key(rjcode: str, folder_path: str) -> str:
        return f"{str(rjcode or '').upper()}:{LibraryFolderCompletionService._path_key(folder_path)}"

    def _resolve_selected_path_targets(self, library, selected_path: str) -> tuple[list[FolderCompletionTarget], list[dict[str, Any]]]:
        target_path = self._normalize_local_path(library, selected_path)
        folder_name = os.path.basename(target_path.rstrip("\\/")) or target_path
        direct_rjcode = extract_rjcode(folder_name) or extract_rjcode(target_path)
        if direct_rjcode:
            return [
                FolderCompletionTarget(
                    library_id=library.id,
                    rjcode=direct_rjcode,
                    folder_path=target_path,
                    folder_name=folder_name,
                    source_path=target_path,
                    source_name=folder_name,
                    source_kind="rj_folder",
                )
            ], []

        targets: list[FolderCompletionTarget] = []
        skipped: list[dict[str, Any]] = []
        try:
            entries = sorted(os.scandir(target_path), key=lambda entry: entry.name.lower())
        except OSError as exc:
            return [], [{"path": target_path, "name": folder_name, "reason": f"读取社团目录失败: {exc}"}]

        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            child_name = entry.name
            if child_name.startswith(".") or child_name.lower() in IGNORED_CONTAINER_CHILDREN:
                continue
            child_rjcode = extract_rjcode(child_name)
            if not child_rjcode:
                continue
            child_path = os.path.abspath(os.path.normpath(entry.path))
            targets.append(
                FolderCompletionTarget(
                    library_id=library.id,
                    rjcode=child_rjcode,
                    folder_path=child_path,
                    folder_name=child_name,
                    source_path=target_path,
                    source_name=folder_name,
                    source_kind="circle_child",
                )
            )

        if not targets:
            skipped.append({
                "path": target_path,
                "name": folder_name,
                "reason": "未识别到 RJ 文件夹",
            })
        return targets, skipped

    def resolve_targets(self, library_id: str, selected_paths: list[str]) -> tuple[Any, list[FolderCompletionTarget], list[dict[str, Any]]]:
        library = self._get_local_library(library_id)
        raw_paths = [str(path or "").strip() for path in selected_paths or [] if str(path or "").strip()]
        if not raw_paths:
            raise ValueError("没有选中要补全的目录")

        targets: list[FolderCompletionTarget] = []
        skipped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_path in raw_paths:
            try:
                path_targets, path_skipped = self._resolve_selected_path_targets(library, raw_path)
            except (ValueError, PermissionError) as exc:
                skipped.append({"path": raw_path, "name": os.path.basename(raw_path.rstrip("\\/")) or raw_path, "reason": str(exc)})
                continue
            skipped.extend(path_skipped)
            for target in path_targets:
                key = self._target_key(target.rjcode, target.folder_path)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(target)
                if len(targets) > MAX_FOLDER_COMPLETION_TARGETS:
                    raise ValueError(f"一次最多预览 {MAX_FOLDER_COMPLETION_TARGETS} 个 RJ 文件夹，请缩小选择范围")

        if not targets and not skipped:
            raise ValueError("没有识别到可补全的 RJ 文件夹")
        return library, targets, skipped

    def _apply_extract_filter_rules(self, remote_resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        rules = list(getattr(get_config().filter, "rules", []) or [])
        if not rules:
            return list(remote_resources), []

        rows: list[dict[str, Any]] = []
        resource_by_path: dict[str, dict[str, Any]] = {}
        for item in remote_resources:
            relative_path = str(item.get("relative_path") or item.get("file_name") or "").strip()
            if not relative_path:
                continue
            rows.append({
                "title": str(item.get("file_name") or os.path.basename(relative_path) or relative_path),
                "path": relative_path,
                "type": item.get("resource_type") or item.get("type") or "",
                "size": int(item.get("size_bytes") or item.get("size") or 0),
            })
            resource_by_path[relative_path] = item

        allowed_rows = self.asmr_service.filter_files(rows, rules)
        allowed_paths = {str(row.get("path") or row.get("title") or "").strip() for row in allowed_rows}
        allowed = [item for item in remote_resources if str(item.get("relative_path") or item.get("file_name") or "").strip() in allowed_paths]
        filtered_paths = [
            path for path in resource_by_path.keys()
            if path not in allowed_paths
        ]
        return allowed, filtered_paths

    @staticmethod
    def _is_empty_rj_folder(local_resources: list[dict[str, Any]]) -> bool:
        return not any(str(item.get("relative_path") or item.get("file_name") or "").strip() for item in local_resources or [])

    async def _fetch_remote_resources_for_target(self, target: FolderCompletionTarget) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        actual_rjcode, work_info = await self.asmr_service.find_best_available_work(target.rjcode)
        if not actual_rjcode or not work_info:
            raise ValueError("ASMR.one 未找到该 RJ 或关联版本")
        tracks = await self.asmr_service.fetch_track_list(actual_rjcode)
        flat_files = self.asmr_service._flatten_tracks(tracks or [])
        remote_resources = [
            self.resource_service._build_remote_resource(actual_rjcode, work_info, file_info)
            for file_info in flat_files
            if file_info.get("media_download_url") or file_info.get("download_url")
        ]
        remote_resources.sort(key=lambda item: (item.get("resource_type") or "", item.get("relative_path") or ""))
        return actual_rjcode, work_info, remote_resources

    async def _build_target_preview(self, target: FolderCompletionTarget) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        try:
            actual_rjcode, work_info, remote_resources = await self._fetch_remote_resources_for_target(target)
            if not remote_resources:
                return None, {"path": target.folder_path, "name": target.folder_name, "rjcode": target.rjcode, "reason": "ASMR.one 文件列表为空"}

            filtered_resources, filtered_paths = self._apply_extract_filter_rules(remote_resources)
            if not filtered_resources:
                return None, {"path": target.folder_path, "name": target.folder_name, "rjcode": target.rjcode, "reason": "过滤后没有可下载文件"}

            local_resources = await asyncio.to_thread(self.resource_service.scan_local_resources, target.folder_path)
            matched, missing, local_only, conflicts = self.resource_service._match_remote_with_local(local_resources, filtered_resources)
            empty_folder = self._is_empty_rj_folder(local_resources)
            selected_resources = list(filtered_resources if empty_folder else missing)
            if not selected_resources:
                return None, {
                    "path": target.folder_path,
                    "name": target.folder_name,
                    "rjcode": target.rjcode,
                    "actual_rjcode": actual_rjcode,
                    "reason": "没有缺失文件",
                    "status": "up_to_date",
                }

            selected_resources = [self._sanitize_resource_for_task(item) for item in selected_resources]
            estimated_bytes = sum(int(item.get("size_bytes") or 0) for item in selected_resources)
            session_id = self.resource_service._create_download_session(
                rjcode=actual_rjcode,
                work_title=str(work_info.get("title") or target.rjcode),
                folder_path=target.folder_path,
                target_path=target.folder_path,
                upload_mode="local",
                selected_filters={"mode": "library_folder_completion", "extract_filter_rules": True},
                selected_resources=selected_resources,
                source_page="library",
                source_action="folder_completion",
                source_label="音声补全 / 补全文件夹",
                status="planning",
            )
            item = {
                "key": self._target_key(target.rjcode, target.folder_path),
                "library_id": target.library_id,
                "rjcode": target.rjcode,
                "actual_rjcode": actual_rjcode,
                "folder_path": target.folder_path,
                "folder_name": target.folder_name,
                "source_path": target.source_path,
                "source_name": target.source_name,
                "source_kind": target.source_kind,
                "work_title": str(work_info.get("title") or target.rjcode),
                "cover_url": str(work_info.get("mainCoverUrl") or work_info.get("cover_url") or ""),
                "mode": "full_download" if empty_folder else "missing_only",
                "remote_total": len(remote_resources),
                "filtered_total": len(filtered_resources),
                "filtered_out_count": len(filtered_paths),
                "matched_total": len(matched),
                "missing_total": len(selected_resources),
                "local_total": len(local_resources),
                "local_only_total": len(local_only),
                "pairing_conflict_count": len(conflicts),
                "estimated_bytes": estimated_bytes,
                "session_id": session_id,
                "selected": True,
                "selected_resources": selected_resources,
                "missing_resources": selected_resources[:100],
                "filtered_paths": filtered_paths[:100],
            }
            return item, None
        except Exception as exc:
            logger.warning("[补全文件夹] 预览失败 rj=%s path=%s: %s", target.rjcode, target.folder_path, exc, exc_info=True)
            return None, {
                "path": target.folder_path,
                "name": target.folder_name,
                "rjcode": target.rjcode,
                "reason": str(exc),
            }

    async def build_preview(
        self,
        library_id: str,
        selected_paths: list[str],
        progress_callback=None,
        cancel_callback=None,
    ) -> dict[str, Any]:
        library, targets, skipped = self.resolve_targets(library_id, selected_paths)
        semaphore = asyncio.Semaphore(FOLDER_COMPLETION_ASMR_CONCURRENCY)
        completed = 0
        total = max(len(targets), 1)

        def report(progress: int, step: str) -> None:
            if progress_callback:
                try:
                    progress_callback(progress, step)
                except Exception:
                    logger.debug("[补全文件夹] progress_callback 失败", exc_info=True)

        async def build_with_limit(target: FolderCompletionTarget):
            nonlocal completed
            if cancel_callback and cancel_callback():
                raise asyncio.CancelledError()
            async with semaphore:
                report(10 + int(completed / total * 80), f"检查 {target.rjcode}")
                result = await self._build_target_preview(target)
                completed += 1
                report(10 + int(completed / total * 80), f"已检查 {completed}/{total}")
                return result

        pairs = await asyncio.gather(*(build_with_limit(target) for target in targets))
        items: list[dict[str, Any]] = []
        for item, skipped_item in pairs:
            if item:
                items.append(item)
            if skipped_item:
                skipped.append(skipped_item)

        summary = {
            "target_count": len(targets),
            "downloadable_count": len(items),
            "skipped_count": len(skipped),
            "missing_file_count": sum(int(item.get("missing_total") or 0) for item in items),
            "estimated_bytes": sum(int(item.get("estimated_bytes") or 0) for item in items),
        }
        return {
            "success": bool(items),
            "library_id": library.id,
            "library_name": library.name,
            "summary": summary,
            "items": items,
            "skipped": skipped,
        }

    def _sanitize_resource_for_task(self, item: dict[str, Any]) -> dict[str, Any]:
        resource = dict(item or {})
        relative_path = str(resource.get("relative_path") or resource.get("file_name") or "").replace("\\", "/").strip("/")
        if not relative_path:
            raise ValueError("资源缺少相对路径")
        if os.path.isabs(relative_path) or any(part in {"", ".", ".."} for part in relative_path.split("/")):
            raise ValueError(f"资源路径不安全: {relative_path}")
        remote_url = str(resource.get("remote_url") or resource.get("media_download_url") or resource.get("download_url") or "").strip()
        if not remote_url:
            raise ValueError(f"资源缺少下载地址: {relative_path}")
        file_name = str(resource.get("file_name") or os.path.basename(relative_path) or relative_path).strip()
        return {
            **resource,
            "relative_path": relative_path,
            "file_name": file_name,
            "remote_url": remote_url,
            "source": str(resource.get("source") or "asmr.one"),
            "resource_type": str(resource.get("resource_type") or self.resource_service.classify_resource_type(file_name, relative_path)),
            "size_bytes": int(resource.get("size_bytes") or resource.get("size") or 0),
            "selected": True,
        }

    def _sanitize_start_item(self, library, item: dict[str, Any]) -> dict[str, Any]:
        data = dict(item or {})
        folder_path = self._normalize_local_path(library, str(data.get("folder_path") or ""))
        rjcode = self.resource_service.normalize_rjcode(data.get("actual_rjcode") or data.get("rjcode") or "")
        if not re.fullmatch(r"[RVB]J(?:\d{6}|\d{8})", rjcode, re.IGNORECASE):
            raise ValueError("缺少有效 RJ 号")
        selected_resources = [
            self._sanitize_resource_for_task(resource)
            for resource in list(data.get("selected_resources") or [])
            if isinstance(resource, dict)
        ]
        if not selected_resources:
            raise ValueError(f"{rjcode} 没有选中任何缺失文件")
        return {
            **data,
            "folder_path": folder_path,
            "folder_name": os.path.basename(folder_path.rstrip("\\/")) or folder_path,
            "actual_rjcode": rjcode,
            "selected_resources": selected_resources,
        }

    async def start_downloads(self, library_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        library = self._get_local_library(library_id)
        raw_items = [item for item in items or [] if isinstance(item, dict)]
        if not raw_items:
            raise ValueError("没有可启动的补全任务")

        config = get_config()
        engine = get_task_engine()
        engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
        created_tasks: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for raw_item in raw_items:
            try:
                item = self._sanitize_start_item(library, raw_item)
                rjcode = item["actual_rjcode"]
                selected_resources = item["selected_resources"]
                session_id = str(item.get("session_id") or "").strip()
                if not session_id:
                    session_id = self.resource_service._create_download_session(
                        rjcode=rjcode,
                        work_title=str(item.get("work_title") or rjcode),
                        folder_path=item["folder_path"],
                        target_path=item["folder_path"],
                        upload_mode="local",
                        selected_filters={"mode": "library_folder_completion", "extract_filter_rules": True},
                        selected_resources=selected_resources,
                        source_page="library",
                        source_action="folder_completion",
                        source_label="音声补全 / 补全文件夹",
                        status="planning",
                    )

                metadata = {
                    "rjcode": rjcode,
                    "work_title": str(item.get("work_title") or rjcode),
                    "cover_url": str(item.get("cover_url") or ""),
                    "folder_path": item["folder_path"],
                    "download_mode": "enhanced",
                    "session_id": session_id,
                    "selected_resources": selected_resources,
                    "selected_resource_count": len(selected_resources),
                    "upload_options": {
                        "enabled": True,
                        "mode": "local",
                        "target_path": item["folder_path"],
                        "library_id": library.id,
                    },
                    "postprocess_options": {"enabled": False},
                    "download_base_path": os.path.join(str(config.storage.temp_path), "library_folder_completion"),
                    "verify_md5_after_download": bool(getattr(config.asmr_sync, "verify_md5_after_download", True)),
                    "download_timeout_seconds": int(getattr(config.asmr_sync, "download_timeout_seconds", 60) or 60),
                    "priority": int(item.get("queue_priority") or item.get("priority") or 100),
                    "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
                    "resource_filter_snapshot": {
                        "mode": "library_folder_completion",
                        "remote_total": int(item.get("remote_total") or 0),
                        "filtered_total": int(item.get("filtered_total") or 0),
                        "filtered_out_count": int(item.get("filtered_out_count") or 0),
                    },
                    "task_domain": "asmr_sync",
                    "source_page": "library",
                    "source_action": "folder_completion",
                    "source_label": "音声补全 / 补全文件夹",
                    "business_key": f"{library.id}:{item['folder_path']}:{rjcode}",
                    "target_library_id": library.id,
                }
                task = Task(
                    task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                    source_path=item["folder_path"],
                    auto_classify=False,
                    metadata=metadata,
                    rjcode=rjcode,
                )
                task.ensure_business_context("asmr_sync", {
                    "session_id": session_id,
                    "source_page": "library",
                    "source_action": "folder_completion",
                    "source_label": "音声补全 / 补全文件夹",
                    "business_key": metadata["business_key"],
                })
                await engine.submit(task)
                self.resource_service._update_session(
                    session_id,
                    task_id=task.id,
                    status="queued",
                    queue_priority=int(metadata["queue_priority"]),
                    target_path=item["folder_path"],
                    upload_mode="local",
                    statistics={
                        "selected_resource_count": len(selected_resources),
                        "library_id": library.id,
                        "target_path": item["folder_path"],
                        "source_action": "folder_completion",
                    },
                    selected_resources=selected_resources,
                )
                created_tasks.append({
                    "task_id": task.id,
                    "session_id": session_id,
                    "rjcode": rjcode,
                    "folder_path": item["folder_path"],
                    "work_title": str(item.get("work_title") or rjcode),
                    "selected_resource_count": len(selected_resources),
                })
            except Exception as exc:
                logger.warning("[补全文件夹] 创建任务失败: %s", exc, exc_info=True)
                errors.append({
                    "rjcode": str(raw_item.get("rjcode") or raw_item.get("actual_rjcode") or ""),
                    "folder_path": str(raw_item.get("folder_path") or ""),
                    "error": str(exc),
                })

        if not created_tasks:
            first_error = errors[0]["error"] if errors else "没有有效下载项"
            raise ValueError(first_error)
        return {
            "success": True,
            "library_id": library.id,
            "tasks": created_tasks,
            "errors": errors,
            "created_count": len(created_tasks),
            "failed_count": len(errors),
            "message": f"已创建 {len(created_tasks)} 个补全文件夹任务",
        }


_library_folder_completion_service: Optional[LibraryFolderCompletionService] = None


def get_library_folder_completion_service() -> LibraryFolderCompletionService:
    global _library_folder_completion_service
    if _library_folder_completion_service is None:
        _library_folder_completion_service = LibraryFolderCompletionService()
    return _library_folder_completion_service
