import asyncio
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_config
from ..models.database import ConflictWork, LibrarySnapshot, get_db
from .dlsite_service import get_dlsite_service
from .extract_service import ExtractService
from .kikoeru_duplicate_service import get_kikoeru_service
from .library_manager import SynologyFileStationClient, get_library_manager
from .rj_subtitle_service import get_rj_subtitle_service
from .task_engine import Task, TaskStatus, TaskType, get_task_engine

logger = logging.getLogger(__name__)


class LinkedSubtitleImportService:
    """Handle automatic linked-subtitle staging and manual subtitle-folder import."""

    PENDING_CONFLICT_TYPE = "LINKED_SUBTITLE_IMPORT"
    EXISTING_SUBTITLE_CONFLICT_TYPE = "LINKED_WORK"
    PENDING_SOURCE_MODE = "linked_translation_archive_pending"
    EXISTING_SUBTITLE_SOURCE_MODE = "linked_translation_archive_existing_subtitle_conflict"
    WORKBENCH_RELATIVE_DIR = "_prekikoeru_subtitle_workbench/linked"
    REMOTE_SEARCH_RETRY_DELAYS: tuple[float, ...] = ()
    REMOTE_PENDING_REASON = "远程库存暂未检出原作目录，请稍后重试"
    EXISTING_SUBTITLE_REASON = "原作目录已有字幕，按重复作品处理"
    KIKOERU_UNCERTAIN_SOURCES = {
        "kikoeru_timeout",
        "kikoeru_exception",
        "kikoeru_no_token",
        "kikoeru_auth_error",
    }

    def __init__(self):
        self.extract_service = ExtractService()
        self.subtitle_service = get_rj_subtitle_service()
        self.library_manager = get_library_manager()
        self.dlsite_service = get_dlsite_service()
        self.kikoeru_service = get_kikoeru_service()

    def _extract_rjcode(self, value: str) -> str:
        return self.subtitle_service.extract_rjcode(str(value or "")) or ""

    def _normalize_single_rjcode(self, value: str) -> str:
        extracted = self._extract_rjcode(value)
        return extracted or str(value or "").strip().upper()

    def _extract_all_rjcodes(self, value: str) -> List[str]:
        return [
            match.group(0).upper()
            for match in re.finditer(r"[RVB]J(?:\d{8}|\d{6})(?!\d)", str(value or ""), re.IGNORECASE)
        ]

    def _has_multiple_rjcodes(self, value: str) -> bool:
        return len(self._extract_all_rjcodes(value)) > 1

    def _extract_rjcode_from_paths(self, *values: str) -> str:
        for value in values:
            rjcode = self._extract_rjcode(value)
            if rjcode:
                return rjcode
        return ""

    def _is_kikoeru_result_reliable(self, result: Any) -> bool:
        if result is None:
            return False
        source = str(getattr(result, "source", "") or "").strip().lower()
        if not source:
            return True
        if source in self.KIKOERU_UNCERTAIN_SOURCES:
            return False
        if source.startswith("kikoeru_error_"):
            return False
        return True

    async def _repair_cached_preview_rj_fields(
        self,
        preview: Dict[str, Any],
        *,
        source_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        next_preview = dict(preview or {})
        next_preview.setdefault("source_path", str(source_path or "").strip())

        raw_source_rjcode = str(next_preview.get("source_rjcode") or "").strip().upper()
        raw_target_rjcode = str(next_preview.get("target_rjcode") or "").strip().upper()
        source_dirty = self._has_multiple_rjcodes(raw_source_rjcode)
        target_dirty = self._has_multiple_rjcodes(raw_target_rjcode)

        if not source_dirty and not target_dirty:
            return next_preview

        repaired_source_rjcode = self._extract_rjcode_from_paths(
            next_preview.get("source_path", ""),
            next_preview.get("source_label", ""),
            next_preview.get("source_subtitle_dir", ""),
            next_preview.get("staged_subtitle_dir", ""),
            raw_source_rjcode,
        )
        if not repaired_source_rjcode:
            repaired_source_rjcode = self._extract_rjcode(raw_source_rjcode)

        if not repaired_source_rjcode:
            next_preview["source_rjcode"] = self._extract_rjcode(raw_source_rjcode)
            next_preview["target_rjcode"] = self._extract_rjcode(raw_target_rjcode)
            return next_preview

        preferred_library_id = str(
            (next_preview.get("selected_candidate") or {}).get("library_id")
            or ((next_preview.get("candidates") or [{}])[0] or {}).get("library_id")
            or ""
        ).strip() or None

        rebuilt_preview = await self._build_common_preview(
            source_rjcode=repaired_source_rjcode,
            source_label=str(
                next_preview.get("source_label")
                or os.path.basename(str(next_preview.get("source_path") or "").rstrip("\\/"))
                or next_preview.get("source_path")
                or ""
            ),
            subtitle_count=int(next_preview.get("subtitle_count") or 0),
            preferred_library_id=preferred_library_id,
        )

        rebuilt_preview.update({
            "mode": next_preview.get("mode"),
            "source_path": next_preview.get("source_path"),
            "source_has_subtitles": next_preview.get("source_has_subtitles"),
            "source_subtitle_dir": next_preview.get("source_subtitle_dir"),
            "staged_subtitle_dir": next_preview.get("staged_subtitle_dir"),
            "subtitle_entries": next_preview.get("subtitle_entries") or [],
        })
        return rebuilt_preview

    def _is_subtitle_entry(self, entry_name: str) -> bool:
        normalized = str(entry_name or "").replace("\\", "/").strip("/")
        if not normalized:
            return False
        return os.path.splitext(normalized)[1].lower() in self.subtitle_service.SUBTITLE_EXTENSIONS

    def _scan_source_subtitles(self, root_dir: str, source_root: Optional[str] = None) -> List[Dict[str, Any]]:
        base_dir = Path(source_root or root_dir)
        source_dir = Path(root_dir)
        items: List[Dict[str, Any]] = []
        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in self.subtitle_service.SUBTITLE_EXTENSIONS:
                continue
            try:
                relative_path = str(file_path.relative_to(base_dir)).replace("\\", "/")
            except ValueError:
                relative_path = file_path.name
            items.append({
                "name": file_path.name,
                "path": str(file_path),
                "relative_path": relative_path,
                "source_name": file_path.name,
                "display_name": file_path.name,
            })
        items.sort(key=lambda item: item.get("relative_path") or item.get("name") or "")
        return items

    async def _collect_archive_subtitles_to_stage(self, archive_path: str) -> tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        extracted_dir = None
        stage_dir = ""
        try:
            logger.info("[字幕补配预检] 开始临时解包扫描来源字幕: %s", archive_path)
            probe_task = Task(
                task_type=TaskType.EXTRACT,
                source_path=archive_path,
                auto_classify=False,
            )
            extracted_dir = await self.extract_service.extract(probe_task)
            if not extracted_dir or not os.path.isdir(extracted_dir):
                probe_reason = str(getattr(probe_task, "error_message", "") or "").strip()
                probe_status = "missing_password" if ("无正确密码" in probe_reason or "密码" in probe_reason) else "extract_failed"
                if not probe_reason:
                    probe_reason = "解压失败：无正确密码" if probe_status == "missing_password" else "压缩包预检临时解包未生成有效目录"
                logger.info(
                    "[字幕补配预检] 临时解包失败: source=%s extracted_dir=%s status=%s reason=%s",
                    archive_path,
                    extracted_dir or "",
                    probe_status,
                    probe_reason,
                )
                return "", [], {
                    "status": probe_status,
                    "reason": probe_reason,
                }

            extracted_subtitles = self._scan_source_subtitles(extracted_dir, source_root=extracted_dir)
            if not extracted_subtitles:
                logger.info(
                    "[字幕补配预检] 临时解包完成，但未扫描到字幕文件: source=%s extracted_dir=%s",
                    archive_path,
                    extracted_dir,
                )
                return "", [], {
                    "status": "no_subtitles",
                    "reason": "",
                }

            stage_dir = self._create_archive_stage_dir(archive_path)
            for item in extracted_subtitles:
                relative_path = str(item.get("relative_path") or item.get("name") or "").strip().replace("\\", "/")
                if not relative_path:
                    continue
                destination = os.path.join(stage_dir, *relative_path.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(item.get("path") or "", destination)

            logger.info(
                "[字幕补配预检] 临时解包扫描到字幕并已复制到工作区: source=%s extracted_dir=%s stage_dir=%s subtitle_count=%s",
                archive_path,
                extracted_dir,
                stage_dir,
                len(extracted_subtitles),
            )
            return stage_dir, self._scan_source_subtitles(stage_dir, source_root=stage_dir), {
                "status": "ok",
                "reason": "",
            }
        finally:
            if extracted_dir and os.path.isdir(extracted_dir):
                logger.info("[字幕补配预检] 清理临时解包目录: %s", extracted_dir)
                shutil.rmtree(extracted_dir, ignore_errors=True)

    def _resolve_subtitle_source_folder(self, folder_path: str) -> Tuple[str, str]:
        source_path = Path(folder_path)
        subtitle_dir = source_path / "subtitles"
        if subtitle_dir.is_dir():
            subtitle_files = list(subtitle_dir.rglob("*"))
            if any(item.is_file() and item.suffix.lower() in self.subtitle_service.SUBTITLE_EXTENSIONS for item in subtitle_files):
                return str(subtitle_dir), str(source_path)
        return str(source_path), str(source_path)

    def _create_archive_stage_dir(self, archive_path: str) -> str:
        temp_root = os.path.join(self.extract_service.config.storage.temp_path, "linked_subtitle_import")
        os.makedirs(temp_root, exist_ok=True)
        safe_name = re.sub(r'[<>:"|?*]', "", Path(str(archive_path or "")).stem.strip()) or "linked_subtitle"
        return tempfile.mkdtemp(prefix=f"{safe_name}_stage_", dir=temp_root)

    async def _wait_for_archive_file(
        self,
        archive_path: str,
        *,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 1.0,
    ) -> str:
        normalized_path = str(archive_path or "").strip()
        if not normalized_path:
            raise ValueError("压缩包路径不能为空")
        if os.path.isfile(normalized_path):
            return normalized_path

        deadline = datetime.now().timestamp() + max(1.0, timeout_seconds)
        while datetime.now().timestamp() < deadline:
            await asyncio.sleep(poll_interval_seconds)
            if os.path.isfile(normalized_path):
                logger.info("[字幕补配] 压缩包路径已就绪: %s", normalized_path)
                return normalized_path

        if os.path.exists(normalized_path):
            raise ValueError("指定路径不是压缩包文件")
        raise FileNotFoundError("压缩包不存在")

    def _cleanup_stage_dir(self, stage_dir: Optional[str]) -> None:
        target = str(stage_dir or "").strip()
        if not target or not os.path.isdir(target):
            return
        shutil.rmtree(target, ignore_errors=True)
        self._cleanup_empty_workbench_shell(target)

    def _cleanup_empty_workbench_shell(self, path_hint: Optional[str]) -> None:
        target = str(path_hint or "").strip()
        if not target:
            return

        current = Path(target)
        if current.name.lower() == "subtitles":
            current = current.parent
        if not current.exists():
            current = current.parent
        if not str(current):
            return

        expected_parts = [part.lower() for part in self.WORKBENCH_RELATIVE_DIR.split("/") if part]
        if not expected_parts:
            return

        shell_leaf: Optional[Path] = None
        for candidate in [current, *current.parents]:
            if candidate.name.lower() != expected_parts[-1]:
                continue

            probe = candidate
            matched = True
            for expected_name in reversed(expected_parts[:-1]):
                probe = probe.parent
                if probe.name.lower() != expected_name:
                    matched = False
                    break
            if matched:
                shell_leaf = candidate
                break

        if shell_leaf is None:
            return

        shell_root = shell_leaf
        for _ in expected_parts[:-1]:
            shell_root = shell_root.parent

        cleanup_target = current
        stop_parent = shell_root.parent
        while cleanup_target != stop_parent:
            if not cleanup_target.exists() or not cleanup_target.is_dir():
                cleanup_target = cleanup_target.parent
                continue
            try:
                cleanup_target.rmdir()
            except OSError:
                break
            cleanup_target = cleanup_target.parent

    def _select_local_workbench_library(self) -> Dict[str, Any]:
        libraries = self.library_manager.list_libraries()
        local_candidates = [
            item for item in libraries
            if str(item.get("type") or "").lower() == "local" and bool(item.get("writable", True))
        ]
        if not local_candidates:
            raise ValueError("未找到可写入的本地库存，无法创建字幕补配工作台")
        return local_candidates[0]

    def _copy_source_subtitles_to_workspace(
        self,
        source_subtitles: List[Dict[str, Any]],
        *,
        destination_dir: str,
    ) -> List[Dict[str, Any]]:
        copied_items: List[Dict[str, Any]] = []
        seen_paths: set[str] = set()
        for index, item in enumerate(source_subtitles or [], start=1):
            source_path = str(item.get("path") or "").strip()
            if not source_path or not os.path.isfile(source_path):
                continue

            relative_path = str(item.get("relative_path") or item.get("name") or "").strip().replace("\\", "/")
            flat_name = os.path.basename(relative_path) if relative_path else os.path.basename(source_path)
            if not flat_name:
                flat_name = os.path.basename(source_path)

            stem, ext = os.path.splitext(flat_name)
            dedupe_index = 1
            normalized_relative = flat_name
            while normalized_relative.lower() in seen_paths:
                dedupe_index += 1
                normalized_relative = f"{stem}_{dedupe_index}{ext}"
            seen_paths.add(normalized_relative.lower())

            destination_path = os.path.join(destination_dir, normalized_relative)
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.copy2(source_path, destination_path)
            copied_items.append({
                "name": os.path.basename(destination_path),
                "path": destination_path,
                "relative_path": normalized_relative,
                "source_name": item.get("source_name") or os.path.basename(source_path),
                "display_name": item.get("display_name") or os.path.basename(destination_path),
                "order": index,
            })
        copied_items.sort(key=lambda current: current.get("relative_path") or current.get("name") or "")
        return copied_items

    def _prepare_workbench_source_subtitles(
        self,
        source_subtitles: List[Dict[str, Any]],
        *,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_subtitles: List[Dict[str, Any]] = []
        for item in source_subtitles or []:
            normalized = self.subtitle_service._normalize_subtitle_file(item)
            if normalized.get("ext") not in self.subtitle_service.SUBTITLE_EXTENSIONS:
                continue
            normalized_subtitles.append(normalized)
        if not use_filter_rules:
            return normalized_subtitles
        return self.subtitle_service._apply_subtitle_filter_rules(
            normalized_subtitles,
            subtitle_filter_rules or [],
        )

    def _build_workbench_clean_subtitle_name(self, subtitle: Dict[str, Any]) -> str:
        normalized = self.subtitle_service._normalize_subtitle_file(subtitle)
        ext = str(normalized.get("ext") or "").strip().lower()
        base_name = str(normalized.get("base_name") or "").strip()
        if not base_name:
            source_name = str(normalized.get("name") or "").strip()
            base_name = os.path.splitext(source_name)[0]
            base_name = self.subtitle_service._strip_trailing_audio_extension(base_name)
        cleaned_name = f"{base_name}{ext}" if ext else base_name
        return cleaned_name.strip()

    def _prepare_workbench_stage_subtitles(
        self,
        source_subtitles: List[Dict[str, Any]],
        *,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        prepared_subtitles = self._prepare_workbench_source_subtitles(
            source_subtitles,
            use_filter_rules=use_filter_rules,
            subtitle_filter_rules=subtitle_filter_rules,
        )
        initial_count = len(prepared_subtitles)
        stage_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in prepared_subtitles:
            normalized = self.subtitle_service._normalize_subtitle_file(item)
            cleaned_name = self._build_workbench_clean_subtitle_name(normalized)
            if not cleaned_name:
                continue
            normalized.setdefault("source_name", normalized.get("name") or os.path.basename(str(normalized.get("path") or "")))
            normalized["cleaned_workbench_name"] = cleaned_name
            stage_groups.setdefault(cleaned_name.lower(), []).append(normalized)

        staged_subtitles: List[Dict[str, Any]] = []
        content_deduped_files: List[Dict[str, Any]] = []
        renamed_collision_files: List[Dict[str, Any]] = []
        seen_stage_names: set[str] = set()

        for group_name in sorted(stage_groups.keys()):
            group = stage_groups[group_name]
            deduped_group, deduped_records = self.subtitle_service._dedupe_downloaded_subtitles_by_content(group, [])
            target_name = str(group[0].get("cleaned_workbench_name") or "").strip()
            for record in deduped_records:
                content_deduped_files.append({
                    **record,
                    "target_name": target_name,
                })

            deduped_group = sorted(
                deduped_group,
                key=lambda item: (
                    str(item.get("display_name") or item.get("name") or ""),
                    str(item.get("source_name") or ""),
                    str(item.get("path") or ""),
                ),
            )
            for item in deduped_group:
                final_name = str(item.get("cleaned_workbench_name") or target_name or item.get("name") or "").strip()
                if not final_name:
                    continue
                stem, ext = os.path.splitext(final_name)
                candidate_name = final_name
                collision_index = 1
                while candidate_name.lower() in seen_stage_names:
                    collision_index += 1
                    candidate_name = f"{stem}_{collision_index}{ext}"
                if candidate_name != final_name:
                    renamed_collision_files.append({
                        "source_name": item.get("source_name") or item.get("name") or "",
                        "preferred_name": final_name,
                        "final_name": candidate_name,
                    })
                seen_stage_names.add(candidate_name.lower())
                staged_subtitles.append({
                    **item,
                    "display_name": candidate_name,
                    "relative_path": candidate_name,
                })

        staged_subtitles.sort(key=lambda item: str(item.get("relative_path") or item.get("display_name") or item.get("name") or ""))
        filtered_out_count = max(0, len(source_subtitles or []) - initial_count)
        logger.info(
            "[字幕补配] 工作台字幕整理完成: source=%s filtered_out=%s staged=%s content_merged=%s renamed_collisions=%s",
            len(source_subtitles or []),
            filtered_out_count,
            len(staged_subtitles),
            len(content_deduped_files),
            len(renamed_collision_files),
        )
        return {
            "subtitles": staged_subtitles,
            "filtered_out_count": filtered_out_count,
            "content_deduped_count": len(content_deduped_files),
            "content_deduped_files": content_deduped_files,
            "renamed_collision_files": renamed_collision_files,
        }

    def _append_task_progress_log(
        self,
        task: Task,
        messages: List[str],
        *,
        level: str = "info",
    ) -> None:
        if not messages:
            return
        metadata = dict(task.task_metadata or {})
        progress_log = list(metadata.get("progress_log") or [])
        now = datetime.now().isoformat()
        for message in messages:
            progress_log.append({
                "time": now,
                "progress": int(task.progress or 100),
                "level": level,
                "message": message,
            })
        metadata["progress_log"] = progress_log[-30:]
        task.task_metadata = metadata

    async def _create_manual_match_workbench(
        self,
        *,
        source_subtitles: List[Dict[str, Any]],
        target_candidate: Dict[str, Any],
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        workbench_library = self._select_local_workbench_library()
        library_id = str(workbench_library.get("id") or "").strip()
        library_root = str(workbench_library.get("path") or "").strip()
        if not library_id or not library_root:
            raise ValueError("本地工作台库存配置不完整，无法创建字幕补配工作台")

        local_workspace_root = os.path.join(
            library_root,
            *self.WORKBENCH_RELATIVE_DIR.split("/"),
            uuid.uuid4().hex,
        )
        os.makedirs(local_workspace_root, exist_ok=True)
        local_subtitle_dir = os.path.join(local_workspace_root, "subtitles")
        os.makedirs(local_subtitle_dir, exist_ok=True)

        try:
            stage_plan = self._prepare_workbench_stage_subtitles(
                source_subtitles,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
            )
            copied_items = self._copy_source_subtitles_to_workspace(
                stage_plan.get("subtitles") or [],
                destination_dir=local_subtitle_dir,
            )
            if not copied_items:
                raise ValueError("来源中没有可供工作台处理的字幕文件")
        except Exception:
            if os.path.isdir(local_workspace_root):
                shutil.rmtree(local_workspace_root, ignore_errors=True)
                self._cleanup_empty_workbench_shell(local_workspace_root)
            raise

        return {
            "library_id": library_id,
            "workspace_root_dir": local_workspace_root,
            "subtitle_dir": local_subtitle_dir,
            "staged_files": copied_items,
            "downloaded_count": len(copied_items),
            "filtered_out_count": int(stage_plan.get("filtered_out_count") or 0),
            "content_deduped_count": int(stage_plan.get("content_deduped_count") or 0),
            "content_deduped_files": stage_plan.get("content_deduped_files") or [],
            "renamed_collision_files": stage_plan.get("renamed_collision_files") or [],
        }

    async def _publish_workbench_to_target(
        self,
        *,
        library_id: str,
        workbench_root_dir: str,
        subtitle_dir: str,
        target_folder_path: str,
    ) -> str:
        library = self.library_manager.get_library_definition(library_id)
        normalized_target_folder = str(target_folder_path or "").strip()
        if not normalized_target_folder:
            raise ValueError("缺少目标目录，无法应用字幕补配结果")

        if library.type == "synology_filestation":
            target_subtitle_dir = f"{normalized_target_folder.rstrip('/')}/subtitles"
            workbench_subtitle_dir = os.path.abspath(subtitle_dir)
            if not os.path.isdir(workbench_subtitle_dir):
                raise FileNotFoundError(f"字幕工作台目录不存在: {workbench_subtitle_dir}")
            client = SynologyFileStationClient(library.synology)
            await self.library_manager._ensure_remote_directory(client, normalized_target_folder)
            await self.library_manager._ensure_remote_directory(client, target_subtitle_dir)
            for root, _, files in os.walk(workbench_subtitle_dir):
                relative_root = os.path.relpath(root, workbench_subtitle_dir)
                remote_dir = target_subtitle_dir if relative_root == "." else str(PurePosixPath(target_subtitle_dir) / relative_root.replace(os.sep, "/"))
                await self.library_manager._ensure_remote_directory(client, remote_dir)
                for filename in files:
                    staged_file = os.path.join(root, filename)
                    await client.upload_file(remote_dir, staged_file, overwrite=True, remote_name=filename)
            shutil.rmtree(workbench_root_dir, ignore_errors=True)
            self._cleanup_empty_workbench_shell(workbench_root_dir)
            return target_subtitle_dir

        workbench_subtitle_dir = os.path.abspath(subtitle_dir)
        target_folder = os.path.abspath(normalized_target_folder)
        target_subtitle_dir = os.path.join(target_folder, "subtitles")
        if not os.path.isdir(workbench_subtitle_dir):
            raise FileNotFoundError(f"字幕工作台目录不存在: {workbench_subtitle_dir}")
        os.makedirs(target_subtitle_dir, exist_ok=True)
        for root, dirs, files in os.walk(workbench_subtitle_dir):
            relative_root = os.path.relpath(root, workbench_subtitle_dir)
            destination_root = target_subtitle_dir if relative_root == "." else os.path.join(target_subtitle_dir, relative_root)
            os.makedirs(destination_root, exist_ok=True)
            for directory in dirs:
                os.makedirs(os.path.join(destination_root, directory), exist_ok=True)
            for filename in files:
                source_file = os.path.join(root, filename)
                destination_file = os.path.join(destination_root, filename)
                if os.path.isdir(destination_file):
                    shutil.rmtree(destination_file, ignore_errors=True)
                elif os.path.exists(destination_file):
                    os.remove(destination_file)
                shutil.move(source_file, destination_file)
        try:
            shutil.rmtree(workbench_root_dir, ignore_errors=True)
            self._cleanup_empty_workbench_shell(workbench_root_dir)
        except Exception:
            logger.warning("[字幕补配] 清理本地工作台目录失败: %s", workbench_root_dir, exc_info=True)
        return target_subtitle_dir

    def _count_local_subtitle_files(self, subtitle_dir: str) -> int:
        normalized_dir = str(subtitle_dir or "").strip()
        if not normalized_dir or not os.path.isdir(normalized_dir):
            return 0
        return len(self._scan_source_subtitles(normalized_dir, source_root=normalized_dir))

    async def _wait_for_published_subtitles(
        self,
        *,
        library_id: str,
        subtitle_dir: str,
        expected_count: int,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 3.0,
    ) -> List[Dict[str, Any]]:
        normalized_dir = str(subtitle_dir or "").strip()
        if not normalized_dir:
            raise ValueError("缺少最终字幕目录，无法校验字幕补配结果")

        deadline = datetime.now().timestamp() + timeout_seconds
        minimum_count = max(1, int(expected_count or 0))
        last_error: Optional[Exception] = None
        last_items: List[Dict[str, Any]] = []

        while datetime.now().timestamp() <= deadline:
            try:
                contents = await self.library_manager.folder_contents(library_id, normalized_dir)
                items = [item for item in (contents.get("items") or []) if not item.get("is_directory")]
                last_items = items
                if len(items) >= minimum_count:
                    return items
            except Exception as exc:
                last_error = exc
                logger.info(
                    "[字幕补配] 等待最终字幕目录就绪: library=%s path=%s expected=%s error=%s",
                    library_id,
                    normalized_dir,
                    minimum_count,
                    exc,
                )
            await asyncio.sleep(poll_interval_seconds)

        if last_items:
            return last_items
        if last_error:
            raise RuntimeError(f"目标字幕目录等待超时: {last_error}") from last_error
        raise RuntimeError("目标字幕目录等待超时，未检测到已导入字幕")

    async def finalize_manual_match_task(self, task: Task) -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        source_mode = str(metadata.get("source_mode") or "").strip().lower()
        if source_mode not in {"linked_translation_archive_import", "subtitle_folder_import"}:
            return {"applied": False, "reason": "not_linked_subtitle_task"}
        if metadata.get("linked_workbench_applied"):
            return {"applied": False, "reason": "already_applied"}

        library_id = str(metadata.get("target_library_id") or metadata.get("library_id") or "").strip()
        target_folder_path = str(metadata.get("target_folder_path") or metadata.get("folder_path") or "").strip()
        subtitle_dir = str(metadata.get("subtitle_dir") or "").strip()
        workbench_root_dir = str(metadata.get("linked_workbench_root_dir") or "").strip()
        if not workbench_root_dir and subtitle_dir:
            workbench_root_dir = str(Path(subtitle_dir).parent).replace("\\", "/") if "/" in subtitle_dir else str(Path(subtitle_dir).parent)
        if not library_id or not target_folder_path or not subtitle_dir or not workbench_root_dir:
            raise ValueError("字幕补配工作台缺少必要路径信息，无法完成最终应用")

        expected_file_count = self._count_local_subtitle_files(subtitle_dir)
        final_subtitle_dir = await self._publish_workbench_to_target(
            library_id=library_id,
            workbench_root_dir=workbench_root_dir,
            subtitle_dir=subtitle_dir,
            target_folder_path=target_folder_path,
        )
        final_items = await self._wait_for_published_subtitles(
            library_id=library_id,
            subtitle_dir=final_subtitle_dir,
            expected_count=expected_file_count,
        )
        metadata.update({
            "subtitle_dir": final_subtitle_dir,
            "subtitle_library_id": library_id,
            "linked_workbench_root_dir": "",
            "linked_workbench_applied": True,
            "written_files": [
                {
                    "subtitle_name": item.get("name") or "",
                    "output_name": item.get("name") or "",
                    "match_type": "manual_match_applied",
                    "match_score": 0,
                }
                for item in final_items
            ],
            "downloaded_count": len(final_items),
        })
        task.task_metadata = metadata
        return {
            "applied": True,
            "final_subtitle_dir": final_subtitle_dir,
            "final_file_count": len(final_items),
            "expected_file_count": expected_file_count,
        }

    def _refresh_preview_execution_state(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        candidates = list(preview.get("candidates") or [])
        ready_candidates = [item for item in candidates if bool(item.get("ready_for_import"))]
        selected_candidate = preview.get("selected_candidate")
        if selected_candidate and not bool(selected_candidate.get("ready_for_import")):
            selected_candidate = None
        if not selected_candidate and len(ready_candidates) == 1:
            selected_candidate = ready_candidates[0]

        stage_reason = str(preview.get("stage_reason") or "")
        source_subtitle_probe_status = str(preview.get("source_subtitle_probe_status") or "").strip().lower()
        source_subtitle_probe_reason = str(preview.get("source_subtitle_probe_reason") or "").strip()
        candidate_search_status = str(preview.get("candidate_search_status") or "")
        candidate_search_reason = str(preview.get("candidate_search_reason") or "")
        subtitle_count = int(preview.get("subtitle_count") or 0)
        can_stage_pending = bool(preview.get("should_queue_pending")) and (
            not stage_reason or candidate_search_status == "pending_remote"
        )
        can_execute = can_stage_pending and subtitle_count > 0 and len(ready_candidates) > 0

        execute_reason = ""
        if stage_reason:
            execute_reason = stage_reason
        elif source_subtitle_probe_status in {"missing_password", "extract_failed"} and source_subtitle_probe_reason:
            execute_reason = source_subtitle_probe_reason
        elif candidate_search_status == "pending_remote":
            execute_reason = candidate_search_reason or self.REMOTE_PENDING_REASON
        elif not subtitle_count:
            execute_reason = "压缩包预检临时解包后未发现可导入的字幕文件"
        elif candidates and not ready_candidates:
            execute_reason = "原作目录已有字幕，按重复作品处理"
        elif not candidates:
            execute_reason = "目标作品仍缺字幕，但尚未定位到可用库存目录，可稍后重试或手动选择目标目录"
        elif len(ready_candidates) > 1:
            execute_reason = "命中多个可用目标目录，需要在字幕补配页手动选择"

        preview.update({
            "selected_candidate": selected_candidate,
            "ready_candidate_count": len(ready_candidates),
            "can_stage_pending": can_stage_pending,
            "can_execute": can_execute,
            "can_auto_import": bool(selected_candidate and can_execute),
            "execute_reason": execute_reason,
            "reason": stage_reason or execute_reason,
        })
        return preview

    def _apply_staged_subtitles_to_preview(
        self,
        preview: Dict[str, Any],
        *,
        stage_dir: str,
        source_subtitles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        preview.update({
            "source_subtitle_dir": stage_dir,
            "staged_subtitle_dir": stage_dir,
            "source_has_subtitles": bool(source_subtitles),
            "subtitle_count": len(source_subtitles),
            "source_subtitle_probe_status": "ok",
            "source_subtitle_probe_reason": "",
            "fatal_extract_error": "",
            "subtitle_entries": [
                item.get("relative_path") or item.get("name") or ""
                for item in source_subtitles
            ],
        })
        return self._refresh_preview_execution_state(preview)

    async def _stage_archive_subtitles_for_preview(
        self,
        archive_path: str,
        preview: Dict[str, Any],
    ) -> Dict[str, Any]:
        existing_stage_dir = str(
            preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
        ).strip()
        if existing_stage_dir and os.path.isdir(existing_stage_dir):
            source_subtitles = self._scan_source_subtitles(existing_stage_dir, source_root=existing_stage_dir)
            return self._apply_staged_subtitles_to_preview(
                preview,
                stage_dir=existing_stage_dir,
                source_subtitles=source_subtitles,
            )

        stage_dir, source_subtitles, probe_result = await self._collect_archive_subtitles_to_stage(archive_path)
        if not source_subtitles:
            if stage_dir:
                self._cleanup_stage_dir(stage_dir)
            preview.update({
                "source_subtitle_probe_status": str((probe_result or {}).get("status") or ""),
                "source_subtitle_probe_reason": str((probe_result or {}).get("reason") or ""),
                "fatal_extract_error": str((probe_result or {}).get("reason") or "") if str((probe_result or {}).get("status") or "") == "missing_password" else "",
            })
            return self._refresh_preview_execution_state(preview)
        return self._apply_staged_subtitles_to_preview(
            preview,
            stage_dir=stage_dir,
            source_subtitles=source_subtitles,
        )

    def _is_path_in_library(self, library_id: str, folder_path: str) -> bool:
        try:
            library = self.library_manager.get_library_definition(library_id)
        except Exception:
            return False

        normalized_folder = str(folder_path or "").strip()
        if not normalized_folder:
            return False

        if library.type == "synology_filestation":
            browse_root = str(library.browse_root_path or library.root_path or "").rstrip("/")
            target = normalized_folder.rstrip("/")
            return bool(browse_root and target and (target == browse_root or target.startswith(f"{browse_root}/")))

        browse_root = os.path.abspath(library.browse_root_path or library.root_path or "")
        target = os.path.abspath(normalized_folder)
        if not browse_root:
            return False
        return target == browse_root or target.startswith(browse_root + os.sep)

    def _collect_snapshot_candidates(
        self,
        target_rjcode: str,
        preferred_library_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not target_rjcode:
            return []

        db = next(get_db())
        try:
            rows = db.query(LibrarySnapshot).filter(
                LibrarySnapshot.rjcode == target_rjcode
            ).order_by(LibrarySnapshot.scanned_at.desc()).all()
        finally:
            db.close()

        libraries = self.library_manager.list_libraries()
        ordered_ids = [
            library.get("id")
            for library in sorted(
                libraries,
                key=lambda item: (0 if item.get("id") == preferred_library_id else 1, item.get("name") or ""),
            )
            if library.get("id")
        ]

        candidates: List[Tuple[str, str]] = []
        seen_paths: set[Tuple[str, str]] = set()
        for row in rows:
            folder_path = str(getattr(row, "folder_path", "") or "").strip()
            if not folder_path:
                continue
            for library_id in ordered_ids:
                dedupe_key = (library_id, folder_path)
                if dedupe_key in seen_paths:
                    continue
                if not self._is_path_in_library(library_id, folder_path):
                    continue
                seen_paths.add(dedupe_key)
                candidates.append(dedupe_key)
        return candidates

    async def _locate_direct_rj_candidate(
        self,
        library_id: str,
        target_rjcode: str,
    ) -> Optional[Dict[str, Any]]:
        if not target_rjcode:
            return None

        library = self.library_manager.get_library_definition(library_id)
        direct_path = ""
        if library.type == "synology_filestation":
            if not getattr(library, "synology", None):
                return None
            browse_root = self.library_manager._normalize_remote_path(library.browse_root_path or library.root_path or "/")
            direct_path = self.library_manager._normalize_remote_path(
                f"{browse_root.rstrip('/')}/{target_rjcode}" if browse_root != "/" else f"/{target_rjcode}"
            )
            client = SynologyFileStationClient(library.synology)
            try:
                info = await client.stat(direct_path)
                item = self.library_manager._first_remote_info_item(info)
                if not item or not bool(item.get("isdir", False)):
                    return None
            except Exception:
                return None
        else:
            browse_root = os.path.abspath(library.browse_root_path or library.root_path or "")
            if not browse_root:
                return None
            direct_path = os.path.join(browse_root, target_rjcode)
            if not os.path.isdir(direct_path):
                return None

        logger.info(
            "[字幕补配] 命中目录规则直查: library=%s rj=%s path=%s",
            library_id,
            target_rjcode,
            direct_path,
        )
        try:
            return await self._summarize_candidate(library_id, direct_path)
        except Exception as exc:
            logger.warning("[字幕补配] 目录规则直查摘要失败: library=%s path=%s error=%s", library_id, direct_path, exc)
            return None

    async def _search_library_browser_candidates(
        self,
        library_id: str,
        target_rjcode: str,
    ) -> List[Dict[str, Any]]:
        library = self.library_manager.get_library_definition(library_id)
        search_rounds: List[tuple[bool, float]] = [(False, 0.0)]
        if library.type == "synology_filestation":
            search_rounds.extend((True, delay) for delay in self.REMOTE_SEARCH_RETRY_DELAYS)

        last_items: List[Dict[str, Any]] = []
        for round_index, (force_refresh, delay_seconds) in enumerate(search_rounds, start=1):
            if delay_seconds > 0:
                logger.info(
                    "[字幕补配] 远程目标目录未命中，等待后重试: library=%s rj=%s round=%s delay=%.1fs force_refresh=%s",
                    library_id,
                    target_rjcode,
                    round_index,
                    delay_seconds,
                    force_refresh,
                )
                await asyncio.sleep(delay_seconds)

            result = await self.library_manager.global_search_files(
                library_id,
                target_rjcode,
                sort_by="name",
                sort_order="asc",
                force_refresh=force_refresh,
            )
            items = list(result.get("files") or [])
            total = int(result.get("total") or len(items))
            last_items = items
            logger.info(
                "[字幕补配] 目标目录搜索结果: library=%s total=%s returned=%s round=%s force_refresh=%s",
                library_id,
                total,
                len(items),
                round_index,
                force_refresh,
            )
            if items or total:
                return items

        return last_items

    async def _summarize_candidate(self, library_id: str, folder_path: str) -> Optional[Dict[str, Any]]:
        library = self.library_manager.get_library_definition(library_id)
        if library.type == "synology_filestation":
            return await self._summarize_remote_candidate(library, folder_path)

        folder_info = await self.library_manager.folder_contents(library_id, folder_path)
        items = folder_info.get("items") or []

        if library.type == "synology_filestation":
            audio_count = len(self.subtitle_service._collect_remote_audio_entries(items))
            existing_subtitle_count = self.subtitle_service._count_remote_existing_subtitles(items)
            folder_name = folder_path.rstrip("/").split("/")[-1]
            subtitle_dir = f"{folder_path.rstrip('/')}/subtitles"
        else:
            folder = Path(folder_path)
            audio_count = len(self.subtitle_service._collect_audio_files(folder))
            existing_subtitle_count = self.subtitle_service._count_existing_subtitles(folder)
            folder_name = folder.name
            subtitle_dir = os.path.join(folder_path, "subtitles")

        total_size = sum(int(item.get("size") or 0) for item in items)
        file_samples = [str(item.get("relative_path") or item.get("name") or "") for item in items[:12]]

        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "folder_path": folder_path,
            "folder_name": folder_name,
            "audio_count": audio_count,
            "existing_subtitle_count": existing_subtitle_count,
            "has_existing_subtitles": existing_subtitle_count > 0,
            "has_audio": audio_count > 0,
            "total_files": len(items),
            "total_size": total_size,
            "subtitle_dir": subtitle_dir,
            "file_samples": file_samples,
            "ready_for_import": existing_subtitle_count == 0,
        }

    async def summarize_target_folder(
        self,
        library_id: str,
        folder_path: str,
    ) -> Optional[Dict[str, Any]]:
        normalized_library_id = str(library_id or "").strip()
        normalized_folder_path = str(folder_path or "").strip()
        if not normalized_library_id or not normalized_folder_path:
            return None
        return await self._summarize_candidate(normalized_library_id, normalized_folder_path)

    async def _summarize_remote_candidate(self, library: Any, folder_path: str) -> Dict[str, Any]:
        if not getattr(library, "synology", None):
            raise RuntimeError("远程库存缺少群晖连接配置")

        normalized_folder_path = self.library_manager._normalize_remote_path(folder_path)
        folder_name = PurePosixPath(normalized_folder_path).name or normalized_folder_path
        subtitle_dir = f"{normalized_folder_path.rstrip('/')}/subtitles"
        folder_info = await self.library_manager.folder_contents(library.id, normalized_folder_path)
        items = list(folder_info.get("items") or [])
        audio_count = len(self.subtitle_service._collect_remote_audio_entries(items))
        existing_subtitle_count = self.subtitle_service._count_remote_existing_subtitles(items)
        total_size = sum(int(item.get("size") or 0) for item in items)
        file_samples = [
            str(item.get("relative_path") or item.get("name") or "")
            for item in items[:12]
        ]

        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "folder_path": normalized_folder_path,
            "folder_name": folder_name,
            "audio_count": audio_count,
            "existing_subtitle_count": existing_subtitle_count,
            "has_existing_subtitles": existing_subtitle_count > 0,
            "has_audio": audio_count > 0,
            "total_files": len(items),
            "total_size": total_size,
            "subtitle_dir": subtitle_dir,
            "file_samples": file_samples,
            "ready_for_import": existing_subtitle_count == 0,
        }

    async def search_target_candidates(
        self,
        target_rjcode: str,
        preferred_library_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not target_rjcode:
            return {
                "candidates": [],
                "search_status": "not_found",
                "search_reason": "",
            }

        library_config = self.library_manager.load_config()
        libraries = [
            {
                "id": library.id,
                "name": library.name,
                "type": library.type,
                "browse_root_path": library.browse_root_path,
            }
            for library in self.library_manager._active_libraries(library_config)
        ]
        ordered_libraries = sorted(
            libraries,
            key=lambda item: (
                0 if item.get("type") == "synology_filestation" else 1,
                0 if item.get("id") == preferred_library_id else 1,
                item.get("name") or "",
            ),
        )
        logger.info(
            "[字幕补配] 目标目录搜索库存列表: rj=%s libraries=%s",
            target_rjcode,
            [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "root": item.get("browse_root_path") or "",
                }
                for item in ordered_libraries
            ],
        )

        candidates: List[Dict[str, Any]] = []
        seen_paths: set[Tuple[str, str]] = set()

        for library_id, folder_path in self._collect_snapshot_candidates(
            target_rjcode,
            preferred_library_id=preferred_library_id,
        ):
            try:
                summary = await self._summarize_candidate(library_id, folder_path)
            except Exception as exc:
                logger.warning("[字幕补配] 读取快照目标目录摘要失败: library=%s path=%s error=%s", library_id, folder_path, exc)
                continue
            if summary:
                dedupe_key = (library_id, folder_path)
                seen_paths.add(dedupe_key)
                candidates.append(summary)

        async def collect_library_candidates(library: Dict[str, Any]) -> List[Dict[str, Any]]:
            library_id = str(library.get("id") or "").strip()
            if not library_id:
                return []

            logger.info(
                "[字幕补配] 开始搜索目标目录: library=%s type=%s rj=%s",
                library_id,
                library.get("type") or "",
                target_rjcode,
            )
            direct_summary = await self._locate_direct_rj_candidate(library_id, target_rjcode)
            if direct_summary:
                return [direct_summary]
            try:
                search_items = await self._search_library_browser_candidates(library_id, target_rjcode)
            except Exception as exc:
                logger.warning("[字幕补配] 搜索目标目录失败: library=%s rj=%s error=%s", library_id, target_rjcode, exc)
                return []

            logger.info(
                "[字幕补配] 目标目录搜索完成: library=%s type=%s total=%s",
                library_id,
                library.get("type") or "",
                len(search_items),
            )

            results: List[Dict[str, Any]] = []
            for item in search_items:
                if not bool(item.get("is_directory")):
                    continue
                folder_path = str(item.get("path") or "")
                if not folder_path:
                    continue

                try:
                    summary = await self._summarize_candidate(library_id, folder_path)
                except Exception as exc:
                    logger.warning("[字幕补配] 读取目标目录摘要失败: library=%s path=%s error=%s", library_id, folder_path, exc)
                    continue

                if summary:
                    results.append(summary)
            return results

        local_libraries = [item for item in ordered_libraries if item.get("type") != "synology_filestation"]
        remote_libraries = [item for item in ordered_libraries if item.get("type") == "synology_filestation"]

        local_results = await asyncio.gather(
            *(collect_library_candidates(library) for library in local_libraries),
            return_exceptions=True,
        )
        for result in local_results:
            if isinstance(result, Exception):
                logger.warning("[字幕补配] 本地目标目录搜索失败: %s", result)
                continue
            for summary in result:
                library_id = str(summary.get("library_id") or "").strip()
                folder_path = str(summary.get("folder_path") or "").strip()
                dedupe_key = (library_id, folder_path)
                if not library_id or not folder_path or dedupe_key in seen_paths:
                    continue
                seen_paths.add(dedupe_key)
                candidates.append(summary)

        remote_search_pending = False
        if remote_libraries:
            remote_tasks: dict[asyncio.Task, Dict[str, Any]] = {
                asyncio.create_task(collect_library_candidates(library)): library
                for library in remote_libraries
            }
            try:
                pending_remote_tasks = set(remote_tasks.keys())
                remote_match_found = False
                while pending_remote_tasks:
                    done, pending_remote_tasks = await asyncio.wait(
                        pending_remote_tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        library = remote_tasks[task]
                        try:
                            result = await task
                        except Exception as exc:
                            logger.warning(
                                "[字幕补配] 远程目标目录搜索失败: library=%s error=%s",
                                library.get("id") or "",
                                exc,
                            )
                            continue

                        appended_count = 0
                        for summary in result:
                            library_id = str(summary.get("library_id") or "").strip()
                            folder_path = str(summary.get("folder_path") or "").strip()
                            dedupe_key = (library_id, folder_path)
                            if not library_id or not folder_path or dedupe_key in seen_paths:
                                continue
                            seen_paths.add(dedupe_key)
                            candidates.append(summary)
                            appended_count += 1

                        if appended_count > 0:
                            remote_match_found = True
                            logger.info(
                                "[字幕补配] 远程目标目录提前命中: rj=%s library=%s candidate_count=%s",
                                target_rjcode,
                                library.get("id") or "",
                                appended_count,
                            )
                            for pending_task in pending_remote_tasks:
                                pending_task.cancel()
                            pending_remote_tasks.clear()
                            break

                if not remote_match_found:
                    remote_search_pending = True
                    logger.info("[字幕补配] 远程目标目录暂未检出: rj=%s", target_rjcode)
            finally:
                for task in remote_tasks:
                    if not task.done():
                        task.cancel()

        candidates.sort(
            key=lambda item: (
                1 if item.get("has_existing_subtitles") else 0,
                item.get("library_name") or "",
                item.get("folder_path") or "",
            )
        )
        return {
            "candidates": candidates,
            "search_status": "matched" if candidates else ("pending_remote" if remote_search_pending else "not_found"),
            "search_reason": "" if candidates else (self.REMOTE_PENDING_REASON if remote_search_pending else "库存中未找到原作目录"),
        }

    async def _resolve_translation_target_rjcode(self, source_rjcode: str, translation_info: Any) -> str:
        target_rjcode = ""
        if translation_info and not getattr(translation_info, "is_original", False):
            target_rjcode = str(getattr(translation_info, "original_workno", "") or "").strip().upper()
        if target_rjcode or not source_rjcode:
            return target_rjcode

        try:
            product_info = await self.dlsite_service.get_product_info(source_rjcode)
        except Exception as exc:
            product_info = None
            logger.warning("[字幕补配] 读取作品语言版本失败: source_rj=%s error=%s", source_rjcode, exc)

        if product_info and product_info.get("product"):
            product = product_info.get("product") or {}
            language_editions = product.get("language_editions", [])
            if isinstance(language_editions, dict):
                language_editions = list(language_editions.values())

            jpn_candidates: List[str] = []
            seen_jpn = set()
            for edition in language_editions or []:
                normalized = str(edition.get("workno") or "").strip().upper()
                if not normalized or normalized == source_rjcode:
                    continue
                lang = str(edition.get("lang") or "").strip().upper()
                if lang != "JPN":
                    continue
                if normalized not in seen_jpn:
                    seen_jpn.add(normalized)
                    jpn_candidates.append(normalized)

            if len(jpn_candidates) == 1:
                logger.info(
                    "[字幕补配] 从 language_editions 反推原作: source_rj=%s target_rj=%s",
                    source_rjcode,
                    jpn_candidates[0],
                )
                return jpn_candidates[0]

        try:
            linked_works = await self.dlsite_service.get_linked_works(source_rjcode)
        except Exception as exc:
            logger.warning("[字幕补配] 读取关联链失败: source_rj=%s error=%s", source_rjcode, exc)
            return ""

        jpn_linked_candidates: List[str] = []
        for workno, work in (linked_works or {}).items():
            normalized = str(workno or "").strip().upper()
            if not normalized or normalized == source_rjcode:
                continue
            work_type = str(getattr(work, "work_type", "") or "").lower()
            lang = str(getattr(work, "lang", "") or "").strip().upper()
            if work_type == "original":
                return normalized
            if lang == "JPN" and normalized not in jpn_linked_candidates:
                jpn_linked_candidates.append(normalized)

        if len(jpn_linked_candidates) == 1:
            logger.info(
                "[字幕补配] 从关联链语言反推原作: source_rj=%s target_rj=%s",
                source_rjcode,
                jpn_linked_candidates[0],
            )
            return jpn_linked_candidates[0]
        return ""

    async def _build_common_preview(
        self,
        *,
        source_rjcode: str,
        source_label: str,
        subtitle_count: int,
        preferred_library_id: Optional[str],
    ) -> Dict[str, Any]:
        source_rjcode = self._extract_rjcode(source_rjcode)
        translation_info = await self.dlsite_service.get_translation_info(source_rjcode) if source_rjcode else None
        resolved_target_rjcode = await self._resolve_translation_target_rjcode(source_rjcode, translation_info)
        is_translation_work = bool(source_rjcode and resolved_target_rjcode and resolved_target_rjcode != source_rjcode)
        # Some manually made subtitle packs are placed directly into the original RJ folder.
        # When the source is not a translation work but clearly contains subtitle files,
        # we still treat it as a linked subtitle source and supplement the same RJ work.
        is_manual_subtitle_source = bool(source_rjcode and subtitle_count > 0 and not is_translation_work)
        target_rjcode = resolved_target_rjcode or (source_rjcode if is_manual_subtitle_source else "")
        is_linked_subtitle_source = bool(is_translation_work or is_manual_subtitle_source)

        source_kikoeru_result = None
        source_exists_in_kikoeru = False
        source_kikoeru_query_ok = not bool(source_rjcode)
        if source_rjcode:
            try:
                source_kikoeru_result = await self.kikoeru_service.check_duplicate(source_rjcode, use_cache=True)
                source_exists_in_kikoeru = bool(source_kikoeru_result and source_kikoeru_result.is_found)
                source_kikoeru_query_ok = self._is_kikoeru_result_reliable(source_kikoeru_result)
            except Exception as exc:
                source_kikoeru_query_ok = False
                logger.warning("[字幕补配] 查询来源作品 Kikoeru 失败: rj=%s error=%s", source_rjcode, exc)

        target_kikoeru_result = None
        target_exists_in_kikoeru = False
        target_has_subtitle_in_kikoeru = False
        target_needs_subtitle_in_kikoeru = False
        target_kikoeru_query_ok = not bool(target_rjcode)
        if target_rjcode:
            try:
                target_kikoeru_result = await self.kikoeru_service.check_duplicate(target_rjcode, use_cache=True)
                target_exists_in_kikoeru = bool(target_kikoeru_result and target_kikoeru_result.is_found)
                target_has_subtitle_in_kikoeru = bool(target_kikoeru_result and getattr(target_kikoeru_result, "has_lyric_hint", False))
                target_needs_subtitle_in_kikoeru = bool(target_exists_in_kikoeru and not target_has_subtitle_in_kikoeru)
                target_kikoeru_query_ok = self._is_kikoeru_result_reliable(target_kikoeru_result)
            except Exception as exc:
                target_kikoeru_query_ok = False
                logger.warning("[字幕补配] 查询 Kikoeru 失败: rj=%s error=%s", target_rjcode, exc)

        kikoeru_route_confident = bool(source_kikoeru_query_ok and target_kikoeru_query_ok)

        candidate_bundle = await self.search_target_candidates(
            target_rjcode,
            preferred_library_id=preferred_library_id,
        ) if target_rjcode else []
        if isinstance(candidate_bundle, dict):
            candidates = list(candidate_bundle.get("candidates") or [])
            candidate_search_status = str(candidate_bundle.get("search_status") or "")
            candidate_search_reason = str(candidate_bundle.get("search_reason") or "")
        else:
            candidates = list(candidate_bundle or [])
            candidate_search_status = ""
            candidate_search_reason = ""
        ready_candidates = [item for item in candidates if bool(item.get("ready_for_import"))]
        selected_candidate = ready_candidates[0] if len(ready_candidates) == 1 else None

        treat_as_new_work = (
            bool(source_rjcode)
            and kikoeru_route_confident
            and (
                not target_rjcode
                or (
                    candidate_search_status != "pending_remote"
                    and not target_exists_in_kikoeru
                    and not candidates
                )
            )
        )
        should_queue_pending = False
        if is_translation_work:
            should_queue_pending = (
                bool(source_rjcode)
                and not source_exists_in_kikoeru
                and (
                    target_needs_subtitle_in_kikoeru
                    or not kikoeru_route_confident
                )
                and subtitle_count > 0
            )
        elif is_manual_subtitle_source:
            should_queue_pending = (
                bool(source_rjcode)
                and subtitle_count > 0
                and (
                    target_needs_subtitle_in_kikoeru
                    or not kikoeru_route_confident
                    or bool(candidates)
                    or candidate_search_status == "pending_remote"
                )
            )

        stage_reason = ""
        if not source_rjcode:
            stage_reason = "无法识别来源作品 RJ 号"
        elif treat_as_new_work:
            stage_reason = "未命中任何关联作品，按新作直接解压入库"
        elif not kikoeru_route_confident:
            stage_reason = ""
        elif not is_linked_subtitle_source:
            stage_reason = "当前作品不是可补配到原作的翻译作品"
        elif is_translation_work and source_exists_in_kikoeru:
            stage_reason = "来源作品已在 Kikoeru 命中，按重复作品处理"
        elif is_translation_work and not target_exists_in_kikoeru:
            stage_reason = "Kikoeru 未命中原作作品，按普通解压入库处理"
        elif target_has_subtitle_in_kikoeru:
            stage_reason = "Kikoeru 显示原作已有字幕，不需要触发字幕补配"
        elif candidates and not ready_candidates:
            stage_reason = "原作目录已有字幕，按重复作品处理"
        execute_reason = ""
        if stage_reason:
            execute_reason = stage_reason
        elif not kikoeru_route_confident:
            execute_reason = "Kikoeru 查询结果不稳定，暂不自动降级为普通解压，稍后重试"
        elif candidate_search_status == "pending_remote":
            execute_reason = candidate_search_reason or self.REMOTE_PENDING_REASON
        elif not subtitle_count:
            execute_reason = "来源内容中没有可导入的字幕文件"
        elif not candidates:
            execute_reason = "目标作品仍缺字幕，但尚未定位到可用库存目录，可稍后重试或手动选择目标目录"
        elif len(ready_candidates) > 1:
            execute_reason = "命中多个可用目标目录，需要在字幕补配页手动选择"

        can_stage_pending = should_queue_pending and (not stage_reason or candidate_search_status == "pending_remote")
        can_execute = can_stage_pending and subtitle_count > 0 and len(ready_candidates) > 0

        return {
            "source_rjcode": source_rjcode,
            "source_label": source_label,
            "target_rjcode": target_rjcode,
            "is_translation_work": is_translation_work,
            "is_manual_subtitle_source": is_manual_subtitle_source,
            "is_linked_subtitle_source": is_linked_subtitle_source,
            "subtitle_count": subtitle_count,
            "translation_info": {
                "is_original": bool(getattr(translation_info, "is_original", False)) if translation_info else False,
                "is_parent": bool(getattr(translation_info, "is_parent", False)) if translation_info else False,
                "is_child": bool(getattr(translation_info, "is_child", False)) if translation_info else False,
                "lang": str(getattr(translation_info, "lang", "") or "") if translation_info else "",
            },
            "kikoeru_checked_rjcode": target_rjcode,
            "kikoeru_has_work": target_exists_in_kikoeru,
            "kikoeru_needs_subtitle": target_needs_subtitle_in_kikoeru,
            "kikoeru_source_query_ok": source_kikoeru_query_ok,
            "kikoeru_target_query_ok": target_kikoeru_query_ok,
            "kikoeru_route_confident": kikoeru_route_confident,
            "kikoeru_source_result_source": getattr(source_kikoeru_result, "source", "") if source_kikoeru_result else "",
            "kikoeru_target_result_source": getattr(target_kikoeru_result, "source", "") if target_kikoeru_result else "",
            "kikoeru_title": getattr(target_kikoeru_result, "title", "") if target_kikoeru_result else "",
            "kikoeru_lyric_status": getattr(target_kikoeru_result, "lyric_status", "") if target_kikoeru_result else "",
            "kikoeru_source_checked_rjcode": source_rjcode,
            "kikoeru_source_found": source_exists_in_kikoeru,
            "kikoeru_source_title": getattr(source_kikoeru_result, "title", "") if source_kikoeru_result else "",
            "kikoeru_target_found": target_exists_in_kikoeru,
            "candidates": candidates,
            "selected_candidate": selected_candidate,
            "candidate_count": len(candidates),
            "ready_candidate_count": len(ready_candidates),
            "candidate_search_status": candidate_search_status,
            "candidate_search_reason": candidate_search_reason,
            "treat_as_new_work": treat_as_new_work,
            "should_queue_pending": should_queue_pending,
            "can_stage_pending": can_stage_pending,
            "can_execute": can_execute,
            "can_auto_import": bool(selected_candidate and can_execute),
            "stage_reason": stage_reason,
            "execute_reason": execute_reason,
            "reason": stage_reason or execute_reason,
        }

    async def preview_archive_import(
        self,
        archive_path: str,
        preferred_library_id: Optional[str] = None,
        source_rjcode_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        archive_path = await self._wait_for_archive_file(archive_path)
        archive_path = str(archive_path or "").strip()
        if not archive_path:
            raise ValueError("压缩包路径不能为空")
        if not os.path.exists(archive_path):
            raise FileNotFoundError("压缩包不存在")
        if not os.path.isfile(archive_path):
            raise ValueError("指定路径不是压缩包文件")

        archive_info = await self.extract_service.get_archive_info(archive_path)
        source_rjcode = self._extract_rjcode(source_rjcode_hint) or self._extract_rjcode_from_paths(
            archive_path,
            getattr(archive_info, "inferred_rjcode", "") if archive_info else "",
        )
        stage_dir, source_subtitles, probe_result = await self._collect_archive_subtitles_to_stage(archive_path)
        subtitle_entries = [item.get("relative_path") or item.get("name") or "" for item in source_subtitles]
        logger.info(
            "[字幕补配预检] 压缩包来源扫描完成: source=%s source_rj=%s subtitle_count=%s probe_status=%s probe_reason=%s subtitle_entries=%s",
            archive_path,
            source_rjcode,
            len(source_subtitles),
            str((probe_result or {}).get("status") or ""),
            str((probe_result or {}).get("reason") or ""),
            subtitle_entries[:12],
        )

        preview = await self._build_common_preview(
            source_rjcode=source_rjcode,
            source_label=os.path.basename(archive_path),
            subtitle_count=len(source_subtitles),
            preferred_library_id=preferred_library_id,
        )
        preview.update({
            "mode": "archive",
            "source_path": archive_path,
            "source_has_subtitles": bool(source_subtitles),
            "source_subtitle_dir": stage_dir,
            "staged_subtitle_dir": stage_dir,
            "source_subtitle_probe_status": str((probe_result or {}).get("status") or ""),
            "source_subtitle_probe_reason": str((probe_result or {}).get("reason") or ""),
            "fatal_extract_error": str((probe_result or {}).get("reason") or "") if str((probe_result or {}).get("status") or "") == "missing_password" else "",
            "subtitle_entries": subtitle_entries,
        })
        return self._refresh_preview_execution_state(preview)

    async def preview_subtitle_folder_import(
        self,
        folder_path: str,
        preferred_library_id: Optional[str] = None,
        source_rjcode_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        folder_path = str(folder_path or "").strip()
        if not folder_path:
            raise ValueError("字幕文件夹路径不能为空")
        if not os.path.exists(folder_path):
            raise FileNotFoundError("字幕文件夹不存在")
        if not os.path.isdir(folder_path):
            raise ValueError("指定路径不是文件夹")

        source_dir, source_root = self._resolve_subtitle_source_folder(folder_path)
        source_rjcode = self._extract_rjcode(source_rjcode_hint) or self._extract_rjcode_from_paths(folder_path, source_root, source_dir)
        subtitle_files = self._scan_source_subtitles(source_dir, source_root=source_root)

        preview = await self._build_common_preview(
            source_rjcode=source_rjcode,
            source_label=os.path.basename(folder_path.rstrip("\\/")) or folder_path,
            subtitle_count=len(subtitle_files),
            preferred_library_id=preferred_library_id,
        )
        preview.update({
            "mode": "subtitle_folder",
            "source_path": folder_path,
            "source_subtitle_dir": source_dir,
            "source_has_subtitles": bool(subtitle_files),
            "subtitle_entries": [item.get("relative_path") or item.get("name") or "" for item in subtitle_files],
        })
        return preview

    def _resolve_target_candidate(
        self,
        preview: Dict[str, Any],
        *,
        target_library_id: Optional[str] = None,
        target_folder_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidates = preview.get("candidates") or []

        if target_library_id and target_folder_path:
            for candidate in candidates:
                if candidate.get("library_id") == target_library_id and candidate.get("folder_path") == target_folder_path:
                    if not bool(candidate.get("ready_for_import")):
                        raise ValueError("目标目录已有字幕，不能进入字幕补配")
                    return candidate
            raise ValueError("指定的目标目录不在当前候选列表中")

        selected_candidate = preview.get("selected_candidate")
        if selected_candidate:
            if not bool(selected_candidate.get("ready_for_import")):
                raise ValueError("目标目录已有字幕，不能进入字幕补配")
            return selected_candidate

        ready_candidates = [item for item in candidates if bool(item.get("ready_for_import"))]
        if len(ready_candidates) == 1:
            return ready_candidates[0]
        if not ready_candidates:
            raise ValueError(preview.get("reason") or "没有可用的目标目录")
        raise ValueError("命中多个可用目标目录，请手动选择目标目录")

    def _build_progress_log(self, summary: str, detail_lines: List[str]) -> List[Dict[str, Any]]:
        now = datetime.now().isoformat()
        logs = []
        for message in [summary, *detail_lines]:
            logs.append({
                "time": now,
                "progress": 100,
                "level": "info",
                "message": message,
            })
        return logs[-30:]

    def _register_import_task(
        self,
        *,
        source_mode: str,
        source_path: str,
        source_rjcode: str,
        target_rjcode: str,
        target_candidate: Dict[str, Any],
        import_result: Dict[str, Any],
        import_reason: str,
        kikoeru_checked_rjcode: str,
        kikoeru_has_work: bool,
    ) -> Task:
        engine = get_task_engine()
        folder_path = str(target_candidate.get("folder_path") or "")
        library_id = str(target_candidate.get("library_id") or "")
        written_files = import_result.get("written_files") or []
        skipped_files = import_result.get("skipped_files") or []
        write_errors = import_result.get("write_errors") or []
        partial = bool(import_result.get("partial"))

        summary = f"已导入原始字幕 {len(written_files)} 个，等待筛选与配对"
        if partial:
            summary = f"已部分导入原始字幕 {len(written_files)} 个，等待筛选与配对"

        detail_lines = [
            "命中关联作品字幕补配",
            f"目标原作 RJ: {target_rjcode}",
            f"来源模式: {source_mode}",
            f"写入数量: {len(written_files)}",
            "等待人工配对",
        ]
        if import_result.get("filtered_out_count"):
            detail_lines.append(f"过滤排除数: {import_result.get('filtered_out_count')}")
        if import_result.get("content_deduped_count"):
            detail_lines.append(f"内容去重合并数: {import_result.get('content_deduped_count')}")
        if import_result.get("renamed_collision_files"):
            detail_lines.append(f"重名顺延数: {len(import_result.get('renamed_collision_files') or [])}")

        task = Task(
            task_type=TaskType.RJ_SUBTITLE_FETCH,
            source_path=folder_path,
            auto_classify=False,
            metadata={
                "folder_path": folder_path,
                "folder_name": target_candidate.get("folder_name") or Path(folder_path).name,
                "library_id": library_id,
                "rjcode": target_rjcode,
                "actual_rjcode": source_rjcode,
                "source_mode": source_mode,
                "target_rjcode": target_rjcode,
                "target_folder_path": folder_path,
                "target_library_id": library_id,
                "subtitle_library_id": import_result.get("subtitle_library_id", library_id),
                "source_archive_path": source_path if source_mode == "linked_translation_archive_import" else "",
                "source_subtitle_folder_path": source_path if source_mode == "subtitle_folder_import" else "",
                "import_reason": import_reason,
                "awaiting_manual_match": True,
                "manual_match_completed": False,
                "kikoeru_checked_rjcode": kikoeru_checked_rjcode,
                "kikoeru_has_work": kikoeru_has_work,
                "downloaded_count": import_result.get("downloaded_count", 0),
                "download_files": import_result.get("download_files", []),
                "filtered_out_count": import_result.get("filtered_out_count", 0),
                "content_deduped_count": import_result.get("content_deduped_count", 0),
                "content_deduped_files": import_result.get("content_deduped_files", []),
                "renamed_collision_files": import_result.get("renamed_collision_files", []),
                "existing_subtitle_count": import_result.get("existing_subtitle_count", 0),
                "subtitle_dir": import_result.get("subtitle_dir", ""),
                "linked_workbench_root_dir": import_result.get("linked_workbench_root_dir", ""),
                "written_files": written_files,
                "skipped_files": skipped_files,
                "write_errors": write_errors,
                "failed_files": [],
                "match_result": import_result.get("match_result", {}),
                "search_attempts": [],
                "progress_log": self._build_progress_log(summary, detail_lines),
            },
        )
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.current_step = summary
        task.completed_at = datetime.now()
        engine.tasks[task.id] = task
        return task

    async def cleanup_workbench_subtitles(self, task_id: str) -> Dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("任务 ID 不能为空")

        engine = get_task_engine()
        task = engine.get_task(normalized_task_id)
        if not task:
            raise ValueError("字幕补配任务不存在")

        metadata = dict(task.task_metadata or {})
        source_mode = str(metadata.get("source_mode") or "").strip().lower()
        if source_mode not in {"linked_translation_archive_import", "subtitle_folder_import"}:
            raise ValueError("当前任务不是字幕补配工作台任务")
        if bool(metadata.get("manual_match_completed")):
            raise ValueError("当前任务已完成重命名导入，无需再清理工作台字幕")

        subtitle_dir = str(metadata.get("subtitle_dir") or "").strip()
        if not subtitle_dir:
            raise ValueError("当前任务没有可清理的字幕工作台目录")
        if not os.path.isdir(subtitle_dir):
            raise FileNotFoundError("字幕工作台目录不存在，无法执行清理")

        config = get_config().asmr_sync
        lrc_enabled = bool(config.lrc_clean_enabled)
        simplify_enabled = bool(config.simplify_chinese_enabled)
        if not lrc_enabled and not simplify_enabled:
            raise ValueError("当前设置未启用 LRC 广告清理或字幕繁体转简体")

        logger.info(
            "[字幕补配] 执行工作台字幕清理: task_id=%s subtitle_dir=%s lrc_enabled=%s simplify_enabled=%s",
            normalized_task_id,
            subtitle_dir,
            lrc_enabled,
            simplify_enabled,
        )

        lrc_result = {
            "enabled": lrc_enabled,
            "total_files": 0,
            "cleaned_files": 0,
            "total_removed_lines": 0,
            "errors": [],
        }
        simplify_result = {
            "enabled": simplify_enabled,
            "total_files": 0,
            "converted_files": 0,
            "errors": [],
        }

        if lrc_enabled:
            lrc_result = self.subtitle_service.subtitle_service.clean_lrc_files_in_folder(
                subtitle_dir,
                list(config.lrc_clean_patterns or []),
            )
            lrc_result["enabled"] = True
        if simplify_enabled:
            simplify_result = self.subtitle_service.subtitle_service.convert_subtitles_to_simplified_in_folder(
                subtitle_dir
            )
            simplify_result["enabled"] = True

        result = {
            "task_id": normalized_task_id,
            "subtitle_dir": subtitle_dir,
            "lrc_clean": lrc_result,
            "simplify_chinese": simplify_result,
            "cleaned_at": datetime.now().isoformat(),
        }
        metadata["linked_subtitle_cleanup_result"] = result
        task.task_metadata = metadata
        self._append_task_progress_log(
            task,
            [
                "已执行工作台字幕清理",
                f"LRC 广告清理: 文件 {int(lrc_result.get('total_files') or 0)}，清理 {int(lrc_result.get('cleaned_files') or 0)}，移除广告行 {int(lrc_result.get('total_removed_lines') or 0)}",
                f"字幕繁体转简体: 文件 {int(simplify_result.get('total_files') or 0)}，转换 {int(simplify_result.get('converted_files') or 0)}",
            ],
        )
        engine.tasks[task.id] = task
        return result

    async def execute_archive_import(
        self,
        archive_path: str,
        *,
        preferred_library_id: Optional[str] = None,
        target_library_id: Optional[str] = None,
        target_folder_path: Optional[str] = None,
        prepared_preview: Optional[Dict[str, Any]] = None,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
        import_reason: str = "手动压缩包字幕补配导入",
        source_mode: str = "linked_translation_archive_import",
    ) -> Dict[str, Any]:
        preview = dict(prepared_preview or {})
        if not preview:
            preview = await self.preview_archive_import(archive_path, preferred_library_id=preferred_library_id)
        if not (preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir")):
            preview = await self._stage_archive_subtitles_for_preview(archive_path, preview)
        target_candidate = self._resolve_target_candidate(
            preview,
            target_library_id=target_library_id,
            target_folder_path=target_folder_path,
        )

        source_subtitles: List[Dict[str, Any]] = []
        temp_dir = None
        try:
            source_dir = str(preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or "").strip()
            if source_dir and os.path.isdir(source_dir):
                source_subtitles = self._scan_source_subtitles(source_dir, source_root=source_dir)
            else:
                temp_dir, source_subtitles = await self._collect_archive_subtitles_to_stage(archive_path)
            workbench_result = await self._create_manual_match_workbench(
                source_subtitles=source_subtitles,
                target_candidate=target_candidate,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
            )
            import_result = {
                "success": True,
                "partial": False,
                "error": None,
                "download_files": workbench_result.get("staged_files", []),
                "downloaded_count": int(workbench_result.get("downloaded_count") or 0),
                "filtered_out_count": int(workbench_result.get("filtered_out_count") or 0),
                "content_deduped_count": int(workbench_result.get("content_deduped_count") or 0),
                "content_deduped_files": workbench_result.get("content_deduped_files", []),
                "renamed_collision_files": workbench_result.get("renamed_collision_files", []),
                "written_files": [
                    {
                        "subtitle_name": item.get("name") or "",
                        "output_name": item.get("name") or "",
                        "match_type": "raw_workbench_stage",
                        "match_score": 0,
                    }
                    for item in (workbench_result.get("staged_files") or [])
                ],
                "skipped_files": [],
                "write_errors": [],
                "awaiting_manual_match": True,
                "existing_subtitle_count": int(target_candidate.get("existing_subtitle_count") or 0),
                "subtitle_dir": workbench_result.get("subtitle_dir") or "",
                "subtitle_library_id": workbench_result.get("library_id") or "",
                "linked_workbench_root_dir": workbench_result.get("workspace_root_dir") or "",
                "match_result": {
                    "matches": [],
                    "matched_group_count": 0,
                    "matched_subtitle_count": 0,
                    "unmatched_audio": [],
                    "unmatched_subtitles": [],
                },
            }
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

        task = None
        if import_result.get("success") and import_result.get("awaiting_manual_match"):
            task = self._register_import_task(
                source_mode=source_mode,
                source_path=archive_path,
                source_rjcode=preview.get("source_rjcode", ""),
                target_rjcode=preview.get("target_rjcode", ""),
                target_candidate=target_candidate,
                import_result=import_result,
                import_reason=import_reason,
                kikoeru_checked_rjcode=preview.get("kikoeru_checked_rjcode", ""),
                kikoeru_has_work=bool(preview.get("kikoeru_has_work")),
            )

        return {
            "success": bool(import_result.get("success")),
            "preview": preview,
            "target_candidate": target_candidate,
            "import_result": import_result,
            "task": {
                "id": task.id,
                "folder_path": task.task_metadata.get("folder_path", ""),
                "library_id": task.task_metadata.get("library_id", ""),
                "source_mode": task.task_metadata.get("source_mode", ""),
            } if task else None,
        }

    async def execute_subtitle_folder_import(
        self,
        folder_path: str,
        *,
        preferred_library_id: Optional[str] = None,
        target_library_id: Optional[str] = None,
        target_folder_path: Optional[str] = None,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
        import_reason: str = "手动字幕文件夹补配导入",
        source_mode: str = "subtitle_folder_import",
        source_rjcode_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        preview = await self.preview_subtitle_folder_import(
            folder_path,
            preferred_library_id=preferred_library_id,
            source_rjcode_hint=source_rjcode_hint,
        )
        target_candidate = self._resolve_target_candidate(
            preview,
            target_library_id=target_library_id,
            target_folder_path=target_folder_path,
        )

        source_dir = preview.get("source_subtitle_dir") or folder_path
        source_root = folder_path
        source_subtitles = self._scan_source_subtitles(source_dir, source_root=source_root)
        workbench_result = await self._create_manual_match_workbench(
            source_subtitles=source_subtitles,
            target_candidate=target_candidate,
            use_filter_rules=use_filter_rules,
            subtitle_filter_rules=subtitle_filter_rules,
        )
        import_result = {
            "success": True,
            "partial": False,
            "error": None,
            "download_files": workbench_result.get("staged_files", []),
            "downloaded_count": int(workbench_result.get("downloaded_count") or 0),
            "filtered_out_count": int(workbench_result.get("filtered_out_count") or 0),
            "content_deduped_count": int(workbench_result.get("content_deduped_count") or 0),
            "content_deduped_files": workbench_result.get("content_deduped_files", []),
            "renamed_collision_files": workbench_result.get("renamed_collision_files", []),
            "written_files": [
                {
                    "subtitle_name": item.get("name") or "",
                    "output_name": item.get("name") or "",
                    "match_type": "raw_workbench_stage",
                    "match_score": 0,
                }
                for item in (workbench_result.get("staged_files") or [])
            ],
            "skipped_files": [],
            "write_errors": [],
            "awaiting_manual_match": True,
            "existing_subtitle_count": int(target_candidate.get("existing_subtitle_count") or 0),
            "subtitle_dir": workbench_result.get("subtitle_dir") or "",
            "subtitle_library_id": workbench_result.get("library_id") or "",
            "linked_workbench_root_dir": workbench_result.get("workspace_root_dir") or "",
            "match_result": {
                "matches": [],
                "matched_group_count": 0,
                "matched_subtitle_count": 0,
                "unmatched_audio": [],
                "unmatched_subtitles": [],
            },
        }

        task = None
        if import_result.get("success") and import_result.get("awaiting_manual_match"):
            task = self._register_import_task(
                source_mode=source_mode,
                source_path=folder_path,
                source_rjcode=preview.get("source_rjcode", ""),
                target_rjcode=preview.get("target_rjcode", ""),
                target_candidate=target_candidate,
                import_result=import_result,
                import_reason=import_reason,
                kikoeru_checked_rjcode=preview.get("kikoeru_checked_rjcode", ""),
                kikoeru_has_work=bool(preview.get("kikoeru_has_work")),
            )

        return {
            "success": bool(import_result.get("success")),
            "preview": preview,
            "target_candidate": target_candidate,
            "import_result": import_result,
            "task": {
                "id": task.id,
                "folder_path": task.task_metadata.get("folder_path", ""),
                "library_id": task.task_metadata.get("library_id", ""),
                "source_mode": task.task_metadata.get("source_mode", ""),
            } if task else None,
        }

    def _should_create_pending_import(self, preview: Dict[str, Any]) -> bool:
        return bool(preview.get("can_stage_pending"))

    def _can_execute_pending_import(self, preview: Dict[str, Any]) -> bool:
        return bool(preview.get("can_execute"))

    def _is_existing_subtitle_duplicate_preview(self, preview: Dict[str, Any]) -> bool:
        if not preview:
            return False
        reason_values = [
            preview.get("stage_reason"),
            preview.get("execute_reason"),
            preview.get("reason"),
        ]
        return any(
            self.EXISTING_SUBTITLE_REASON in str(value or "")
            for value in reason_values
        )

    def _pick_existing_subtitle_conflict_candidate(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        selected_candidate = preview.get("selected_candidate")
        if isinstance(selected_candidate, dict) and str(selected_candidate.get("folder_path") or "").strip():
            return selected_candidate
        candidates = list(preview.get("candidates") or [])
        for candidate in candidates:
            if str(candidate.get("folder_path") or "").strip():
                return candidate
        return {}

    def _upsert_existing_subtitle_conflict(
        self,
        db,
        *,
        source_path: str,
        preview: Dict[str, Any],
        task_id: Optional[str] = None,
        queue_origin: str = "auto_process",
    ) -> ConflictWork:
        normalized_source_path = str(source_path or "").strip()
        if not normalized_source_path:
            raise ValueError("缺少来源路径，无法写入问题作品")
        if not self._is_existing_subtitle_duplicate_preview(preview):
            raise ValueError("当前预检结果不是原作已有字幕问题项")

        preview_data = dict(preview or {})
        candidate = self._pick_existing_subtitle_conflict_candidate(preview_data)
        target_rjcode = self._extract_rjcode(preview_data.get("target_rjcode") or "")
        source_rjcode = self._extract_rjcode(preview_data.get("source_rjcode") or "")
        source_label = str(preview_data.get("source_label") or os.path.basename(normalized_source_path) or "").strip()
        existing_path = str(candidate.get("folder_path") or "").strip()
        queue_origin_value = str(queue_origin or "auto_process").strip() or "auto_process"

        metadata = {
            "work_name": source_label,
            "source_label": source_label,
            "source_rjcode": source_rjcode,
            "target_rjcode": target_rjcode,
            "subtitle_count": int(preview_data.get("subtitle_count") or 0),
            "reason": self.EXISTING_SUBTITLE_REASON,
            "queue_origin": queue_origin_value,
            "existing_library_id": str(candidate.get("library_id") or "").strip(),
            "existing_library_name": str(candidate.get("library_name") or "").strip(),
            "existing_subtitle_count": int(candidate.get("existing_subtitle_count") or 0),
            "existing_audio_count": int(candidate.get("audio_count") or 0),
            "available_actions": ["SKIP"],
        }
        analysis_info = {
            "preview": preview_data,
            "source_mode": self.EXISTING_SUBTITLE_SOURCE_MODE,
            "queued_at": datetime.now().isoformat(),
            "problem_kind": "existing_subtitles",
        }
        related_rjcodes = [code for code in [source_rjcode, target_rjcode] if code]

        conflict = db.query(ConflictWork).filter(
            ConflictWork.new_path == normalized_source_path,
            ConflictWork.status == "PENDING",
        ).first()

        if conflict:
            conflict.task_id = task_id or conflict.task_id
            conflict.rjcode = target_rjcode or source_rjcode or conflict.rjcode
            conflict.conflict_type = self.EXISTING_SUBTITLE_CONFLICT_TYPE
            conflict.existing_path = existing_path
            conflict.new_metadata = metadata
            conflict.analysis_info = analysis_info
            conflict.related_rjcodes = related_rjcodes
            conflict.linked_works_info = []
            return conflict

        conflict = ConflictWork(
            id=str(uuid.uuid4()),
            task_id=task_id,
            rjcode=target_rjcode or source_rjcode,
            conflict_type=self.EXISTING_SUBTITLE_CONFLICT_TYPE,
            existing_path=existing_path,
            new_path=normalized_source_path,
            new_metadata=metadata,
            status="PENDING",
            linked_works_info=[],
            analysis_info=analysis_info,
            related_rjcodes=related_rjcodes,
            created_at=datetime.now(),
        )
        db.add(conflict)
        return conflict

    async def create_existing_subtitle_problem(
        self,
        *,
        source_path: str,
        preview: Dict[str, Any],
        task_id: Optional[str] = None,
        queue_origin: str = "auto_process",
    ) -> Dict[str, Any]:
        if not self._is_existing_subtitle_duplicate_preview(preview):
            return {
                "handled": False,
                "reason": "",
            }

        db = next(get_db())
        try:
            conflict = self._upsert_existing_subtitle_conflict(
                db,
                source_path=source_path,
                preview=preview,
                task_id=task_id,
                queue_origin=queue_origin,
            )
            db.commit()
            db.refresh(conflict)
            logger.info(
                "[字幕补配] 原作已有字幕，已转入问题作品: source=%s source_rj=%s target_rj=%s conflict_id=%s",
                source_path,
                preview.get("source_rjcode"),
                preview.get("target_rjcode"),
                conflict.id,
            )
            return {
                "handled": True,
                "conflict_id": str(conflict.id),
                "conflict_type": str(conflict.conflict_type or ""),
                "reason": self.EXISTING_SUBTITLE_REASON,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _should_retry_pending_candidate_search(self, preview: Dict[str, Any]) -> bool:
        if not preview:
            return False
        if not str(preview.get("target_rjcode") or "").strip():
            return False
        if not bool(preview.get("is_linked_subtitle_source") or preview.get("is_translation_work")):
            return False
        if not bool(preview.get("kikoeru_route_confident", True)):
            return True
        if not bool(preview.get("kikoeru_has_work")) and str(preview.get("candidate_search_status") or "").strip().lower() != "pending_remote":
            return False
        if str(preview.get("stage_reason") or "").strip():
            return False

        candidates = list(preview.get("candidates") or [])
        candidate_search_status = str(preview.get("candidate_search_status") or "").strip().lower()
        if candidates:
            return False
        return candidate_search_status in {"", "pending_remote", "not_found"}

    async def _refresh_pending_preview_candidates(
        self,
        preview: Dict[str, Any],
        *,
        preferred_library_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._should_retry_pending_candidate_search(preview):
            return self._refresh_preview_execution_state(dict(preview or {}))

        next_preview = dict(preview or {})
        target_rjcode = str(next_preview.get("target_rjcode") or "").strip()
        if not target_rjcode:
            return self._refresh_preview_execution_state(next_preview)

        if not bool(next_preview.get("kikoeru_route_confident", True)):
            rebuilt_preview = await self._build_common_preview(
                source_rjcode=str(next_preview.get("source_rjcode") or "").strip(),
                source_label=str(next_preview.get("source_label") or "").strip(),
                subtitle_count=int(next_preview.get("subtitle_count") or 0),
                preferred_library_id=preferred_library_id,
            )
            rebuilt_preview.update({
                "mode": next_preview.get("mode"),
                "source_path": next_preview.get("source_path"),
                "source_has_subtitles": next_preview.get("source_has_subtitles"),
                "source_subtitle_dir": next_preview.get("source_subtitle_dir"),
                "staged_subtitle_dir": next_preview.get("staged_subtitle_dir"),
                "subtitle_entries": next_preview.get("subtitle_entries") or [],
            })
            return self._refresh_preview_execution_state(rebuilt_preview)

        current_selected = next_preview.get("selected_candidate") or {}
        effective_preferred_library_id = (
            preferred_library_id
            or str(current_selected.get("library_id") or "").strip()
            or None
        )

        logger.info(
            "[字幕补配] 重新检查待处理预检单候选: target_rj=%s previous_status=%s previous_candidate_count=%s preferred_library=%s",
            target_rjcode,
            next_preview.get("candidate_search_status") or "",
            len(next_preview.get("candidates") or []),
            effective_preferred_library_id or "",
        )

        candidate_bundle = await self.search_target_candidates(
            target_rjcode,
            preferred_library_id=effective_preferred_library_id,
        )
        candidates = list(candidate_bundle.get("candidates") or []) if isinstance(candidate_bundle, dict) else list(candidate_bundle or [])
        candidate_search_status = str(candidate_bundle.get("search_status") or "") if isinstance(candidate_bundle, dict) else ""
        candidate_search_reason = str(candidate_bundle.get("search_reason") or "") if isinstance(candidate_bundle, dict) else ""

        selected_candidate = None
        selected_library_id = str(current_selected.get("library_id") or "").strip()
        selected_folder_path = str(current_selected.get("folder_path") or "").strip()
        if selected_library_id and selected_folder_path:
            for candidate in candidates:
                if str(candidate.get("library_id") or "").strip() == selected_library_id and str(candidate.get("folder_path") or "").strip() == selected_folder_path:
                    selected_candidate = candidate
                    break
        if not selected_candidate and len(candidates) == 1:
            selected_candidate = candidates[0]

        next_preview.update({
            "candidates": candidates,
            "selected_candidate": selected_candidate,
            "candidate_count": len(candidates),
            "ready_candidate_count": len(candidates),
            "candidate_search_status": candidate_search_status,
            "candidate_search_reason": candidate_search_reason,
        })
        return self._refresh_preview_execution_state(next_preview)

    def _serialize_pending_record(self, conflict: ConflictWork) -> Dict[str, Any]:
        preview = dict((conflict.analysis_info or {}).get("preview") or {})
        preview.setdefault("target_rjcode", self._extract_rjcode((conflict.new_metadata or {}).get("target_rjcode") or ""))
        preview.setdefault("source_rjcode", self._extract_rjcode((conflict.new_metadata or {}).get("source_rjcode") or ""))
        preview.setdefault("source_label", (conflict.new_metadata or {}).get("source_label") or "")
        preview.setdefault("subtitle_count", (conflict.new_metadata or {}).get("subtitle_count") or 0)
        preview["source_rjcode"] = self._extract_rjcode(preview.get("source_rjcode") or "")
        preview["target_rjcode"] = self._extract_rjcode(preview.get("target_rjcode") or "")
        preview = self._refresh_preview_execution_state(preview)
        return {
            "id": conflict.id,
            "task_id": conflict.task_id,
            "status": conflict.status,
            "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
            "source_path": conflict.new_path,
            "source_mode": (conflict.analysis_info or {}).get("source_mode") or self.PENDING_SOURCE_MODE,
            "preview": preview,
            "can_execute": self._can_execute_pending_import(preview),
        }

    async def queue_pending_archive_import(self, task: Task, rjcode: str) -> Dict[str, Any]:
        hinted_rjcode = self._extract_rjcode(
            rjcode
            or getattr(task, "rjcode", "")
            or (task.task_metadata or {}).get("rjcode")
            or (task.task_metadata or {}).get("inferred_rjcode")
            or ""
        )
        preview = await self.preview_archive_import(
            task.source_path,
            source_rjcode_hint=hinted_rjcode,
        )
        should_create_pending = self._should_create_pending_import(preview)
        if should_create_pending:
            preview = await self._stage_archive_subtitles_for_preview(task.source_path, preview)
            should_create_pending = self._should_create_pending_import(preview)
        logger.info(
            "[字幕补配预检] source=%s source_rj=%s target_rj=%s is_translation_work=%s is_manual_subtitle_source=%s subtitle_count=%s candidate_count=%s ready_candidate_count=%s kikoeru_has_work=%s stage_reason=%s execute_reason=%s handled=%s can_execute=%s",
            task.source_path,
            preview.get("source_rjcode", ""),
            preview.get("target_rjcode", ""),
            bool(preview.get("is_translation_work")),
            bool(preview.get("is_manual_subtitle_source")),
            int(preview.get("subtitle_count") or 0),
            int(preview.get("candidate_count") or 0),
            int(preview.get("ready_candidate_count") or 0),
            bool(preview.get("kikoeru_has_work")),
            preview.get("stage_reason", ""),
            preview.get("execute_reason", ""),
            should_create_pending,
            self._can_execute_pending_import(preview),
        )
        if not should_create_pending:
            return {
                "handled": False,
                "preview": preview,
                "reason": preview.get("reason") or "",
            }

        db = next(get_db())
        try:
            pending = db.query(ConflictWork).filter(
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.new_path == task.source_path,
                ConflictWork.status == "PENDING",
            ).first()

            metadata = {
                "source_rjcode": preview.get("source_rjcode", ""),
                "target_rjcode": preview.get("target_rjcode", ""),
                "source_label": preview.get("source_label", ""),
                "subtitle_count": int(preview.get("subtitle_count") or 0),
                "queue_origin": "auto_process",
            }
            analysis_info = {
                "preview": preview,
                "source_mode": self.PENDING_SOURCE_MODE,
                "queued_at": datetime.now().isoformat(),
            }
            existing_path = (preview.get("selected_candidate") or {}).get("folder_path") or ""

            if pending:
                old_preview = dict((pending.analysis_info or {}).get("preview") or {})
                old_stage_dir = str(
                    old_preview.get("source_subtitle_dir") or old_preview.get("staged_subtitle_dir") or ""
                ).strip()
                new_stage_dir = str(
                    preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
                ).strip()
                if old_stage_dir and old_stage_dir != new_stage_dir:
                    self._cleanup_stage_dir(old_stage_dir)
                pending.task_id = task.id
                pending.rjcode = preview.get("target_rjcode") or preview.get("source_rjcode") or rjcode
                pending.existing_path = existing_path
                pending.new_metadata = metadata
                pending.analysis_info = analysis_info
            else:
                pending = ConflictWork(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    rjcode=preview.get("target_rjcode") or preview.get("source_rjcode") or rjcode,
                    conflict_type=self.PENDING_CONFLICT_TYPE,
                    existing_path=existing_path,
                    new_path=task.source_path,
                    new_metadata=metadata,
                    status="PENDING",
                    linked_works_info=[],
                    analysis_info=analysis_info,
                    related_rjcodes=[
                        code for code in [
                            preview.get("source_rjcode"),
                            preview.get("target_rjcode"),
                        ] if code
                    ],
                    created_at=datetime.now(),
                )
                db.add(pending)

            db.commit()
            db.refresh(pending)
            logger.info(
                "[字幕补配] 已将来源加入预检列表: source=%s source_rj=%s target_rj=%s",
                task.source_path,
                preview.get("source_rjcode"),
                preview.get("target_rjcode"),
            )
            return {
                "handled": True,
                "preview": preview,
                "record": self._serialize_pending_record(pending),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def list_pending_imports(self) -> List[Dict[str, Any]]:
        db = next(get_db())
        try:
            rows = db.query(ConflictWork).filter(
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status == "PENDING",
            ).order_by(ConflictWork.created_at.desc()).all()
            items: List[Dict[str, Any]] = []
            updated = False
            for row in rows:
                original_preview = dict((row.analysis_info or {}).get("preview") or {})
                preview = await self._repair_cached_preview_rj_fields(
                    original_preview,
                    source_path=str(row.new_path or ""),
                )
                refreshed_preview = await self._refresh_pending_preview_candidates(preview)
                if not self._should_create_pending_import(refreshed_preview):
                    converted_conflict = None
                    if self._is_existing_subtitle_duplicate_preview(refreshed_preview):
                        converted_conflict = self._upsert_existing_subtitle_conflict(
                            db,
                            source_path=str(row.new_path or ""),
                            preview=refreshed_preview,
                            task_id=str(row.task_id or "").strip() or None,
                            queue_origin=str((row.new_metadata or {}).get("queue_origin") or "auto_process"),
                        )
                    stage_dir = str(
                        refreshed_preview.get("source_subtitle_dir") or refreshed_preview.get("staged_subtitle_dir") or ""
                    ).strip()
                    if stage_dir:
                        self._cleanup_stage_dir(stage_dir)
                    if converted_conflict is row:
                        updated = True
                        continue
                    db.delete(row)
                    updated = True
                    continue
                if refreshed_preview != original_preview:
                    row.analysis_info = {
                        **(row.analysis_info or {}),
                        "preview": refreshed_preview,
                        "candidate_refreshed_at": datetime.now().isoformat(),
                    }
                    updated = True
                items.append(self._serialize_pending_record(row))
            if updated:
                db.commit()
            return items
        finally:
            db.close()

    async def clear_pending_imports(
        self,
        *,
        record_ids: Optional[List[str]] = None,
        clear_all: bool = False,
    ) -> Dict[str, Any]:
        normalized_ids = [
            str(record_id or "").strip()
            for record_id in (record_ids or [])
            if str(record_id or "").strip()
        ]
        if not clear_all and not normalized_ids:
            raise ValueError("没有可清除的字幕补配预检单")

        db = next(get_db())
        try:
            query = db.query(ConflictWork).filter(
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status == "PENDING",
            )
            if not clear_all:
                query = query.filter(ConflictWork.id.in_(normalized_ids))

            rows = query.all()
            if not rows:
                raise ValueError("未找到可清除的字幕补配预检单")

            cleared_ids: List[str] = []
            cleared_stage_dirs = 0
            for row in rows:
                preview = dict((row.analysis_info or {}).get("preview") or {})
                stage_dir = str(
                    preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
                ).strip()
                if stage_dir:
                    self._cleanup_stage_dir(stage_dir)
                    cleared_stage_dirs += 1
                cleared_ids.append(str(row.id))
                db.delete(row)

            db.commit()
            return {
                "success": True,
                "cleared_count": len(cleared_ids),
                "cleared_ids": cleared_ids,
                "cleared_stage_dirs": cleared_stage_dirs,
                "clear_all": bool(clear_all),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _archive_source_after_execute(self, record: ConflictWork):
        source_path = str(record.new_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return

        engine = get_task_engine()
        task = engine.get_task(str(record.task_id)) if record.task_id else None
        if task is None:
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=source_path,
                auto_classify=False,
            )
        await engine._archive_source_file(task)

    async def execute_pending_import(
        self,
        record_id: str,
        *,
        target_library_id: Optional[str] = None,
        target_folder_path: Optional[str] = None,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        db = next(get_db())
        try:
            record = db.query(ConflictWork).filter(
                ConflictWork.id == record_id,
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status == "PENDING",
            ).first()
            if not record:
                raise ValueError("字幕补配预检单不存在")

            record_preview = await self._refresh_pending_preview_candidates(
                await self._repair_cached_preview_rj_fields(
                    dict((record.analysis_info or {}).get("preview") or {}),
                    source_path=str(record.new_path or ""),
                )
            )
            record.analysis_info = {
                **(record.analysis_info or {}),
                "preview": record_preview,
                "candidate_refreshed_at": datetime.now().isoformat(),
            }
            result = await self.execute_archive_import(
                str(record.new_path or ""),
                target_library_id=target_library_id,
                target_folder_path=target_folder_path,
                prepared_preview=record_preview,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
                import_reason="正常解压检测后的关联字幕补配导入",
                source_mode="linked_translation_archive_import",
            )

            if not result.get("success"):
                db.commit()
                return result

            self._cleanup_stage_dir(
                record_preview.get("source_subtitle_dir") or record_preview.get("staged_subtitle_dir")
            )
            final_preview = dict(result.get("preview") or {})
            final_preview.pop("source_subtitle_dir", None)
            final_preview.pop("staged_subtitle_dir", None)
            record.status = "IMPORTED"
            record.analysis_info = {
                **(record.analysis_info or {}),
                "preview": final_preview,
                "executed_at": datetime.now().isoformat(),
                "import_result_summary": {
                    "written_count": len((result.get("import_result") or {}).get("written_files") or []),
                    "write_error_count": len((result.get("import_result") or {}).get("write_errors") or []),
                    "awaiting_manual_match": bool((result.get("import_result") or {}).get("awaiting_manual_match")),
                    "task_id": (result.get("task") or {}).get("id"),
                },
            }
            db.commit()

            await self._archive_source_after_execute(record)

            engine = get_task_engine()
            if record.task_id:
                original_task = engine.get_task(str(record.task_id))
                if original_task:
                    original_task.output_path = (result.get("target_candidate") or {}).get("folder_path", "")
                    original_task.status = TaskStatus.COMPLETED
                    original_task.progress = 100
                    original_task.completed_at = datetime.now()
                    original_task.current_step = "已转入字幕补配并完成原始字幕导入"

            return result
        finally:
            db.close()


_linked_subtitle_import_service: Optional[LinkedSubtitleImportService] = None


def get_linked_subtitle_import_service() -> LinkedSubtitleImportService:
    global _linked_subtitle_import_service
    if _linked_subtitle_import_service is None:
        _linked_subtitle_import_service = LinkedSubtitleImportService()
    return _linked_subtitle_import_service
