import asyncio
import contextlib
import hashlib
import logging
import os
import re
import shutil
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_config
from ..models.database import ConflictWork, SessionLocal, WorkCanonicalLink, get_db
from .dlsite_service import get_dlsite_service
from .extract_service import ExtractService
from .kikoeru_duplicate_service import get_kikoeru_service
from .library_manager import SynologyFileStationClient, get_library_manager
from .rj_subtitle_service import get_rj_subtitle_service
from .task_engine import Task, TaskStatus, TaskType, get_task_engine
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


class LinkedSubtitleArchivePrecheckTimeout(TimeoutError):
    """字幕补配预检超时，但保留已经确认的轻量路由信息。"""

    def __init__(self, preview: Dict[str, Any]):
        super().__init__("字幕补配预检超时")
        self.preview = preview


class LinkedSubtitleImportAlreadyRunning(RuntimeError):
    """同一条字幕补配预检单已经在执行中。"""


class LinkedSubtitleImportService:
    """Handle automatic linked-subtitle staging and manual subtitle-folder import."""

    PENDING_CONFLICT_TYPE = "LINKED_SUBTITLE_IMPORT"
    EXISTING_SUBTITLE_CONFLICT_TYPE = "LINKED_WORK"
    PENDING_SOURCE_MODE = "linked_translation_archive_pending"
    EXISTING_SUBTITLE_SOURCE_MODE = "linked_translation_archive_existing_subtitle_conflict"
    PENDING_EXECUTING_STATUS = "PROCESSING"
    PENDING_EXECUTION_LEASE_SECONDS = max(
        60,
        int(os.getenv("KIKOERUMANAGER_LINKED_SUBTITLE_EXECUTION_LEASE_SECONDS", "600") or 600),
    )
    PENDING_EXECUTION_HEARTBEAT_SECONDS = max(
        10,
        min(60, PENDING_EXECUTION_LEASE_SECONDS // 3),
    )
    WORKBENCH_RELATIVE_DIR = "_kikoerumanager_subtitle_workbench/linked"
    REMOTE_SEARCH_RETRY_DELAYS: tuple[float, ...] = ()
    REMOTE_PENDING_REASON = "远程库存暂未检出原作目录，请稍后重试"
    EXISTING_SUBTITLE_REASON = "原作目录已有字幕，按重复作品处理"
    DLSITE_LINKAGE_UNCERTAIN_REASON = "DLsite 关联链结果不完整，疑似翻译作品，等待重试后重新预检"
    TRANSLATION_TEXT_MARKERS = (
        "中文版",
        "中文",
        "简体",
        "簡体",
        "簡體",
        "繁体",
        "繁體",
        "汉化",
        "漢化",
        "みんなで翻訳",
        "みんなで翻译",
        "翻訳",
        "翻译",
        "chinese",
        "zh_cn",
        "zh-tw",
        "zh_tw",
    )
    PENDING_REFRESH_MIN_INTERVAL_SECONDS = 12
    KIKOERU_UNCERTAIN_SOURCES = {
        "kikoeru_timeout",
        "kikoeru_exception",
        "kikoeru_no_token",
        "kikoeru_auth_error",
        "kikoeru_tracks_unreliable",
    }
    ARCHIVE_PRECHECK_TIMEOUT_SECONDS = float(
        os.getenv("KIKOERUMANAGER_LINKED_SUBTITLE_PRECHECK_TIMEOUT_SECONDS", "300") or 300
    )
    _FOLDER_SUMMARY_CACHE_SCHEMA_VERSION = "v1"
    _FOLDER_SUMMARY_CACHE_L1_MAX_SIZE = 512
    _FOLDER_SUMMARY_CACHE_L1_TTL_SECONDS = 30

    def __init__(self):
        self.extract_service = ExtractService()
        self.subtitle_service = get_rj_subtitle_service()
        self.library_manager = get_library_manager()
        self.dlsite_service = get_dlsite_service()
        self.kikoeru_service = get_kikoeru_service()
        self._archive_preview_inflight: Dict[str, asyncio.Task] = {}
        self._archive_preview_inflight_lock = asyncio.Lock()
        self._pending_execution_owner_id = f"{os.getpid()}:{uuid.uuid4()}"
        self._target_folder_summary_cache = TTLCache(
            max_size=self._FOLDER_SUMMARY_CACHE_L1_MAX_SIZE,
            ttl_seconds=self._FOLDER_SUMMARY_CACHE_L1_TTL_SECONDS,
            name="linked_subtitle.target_folder_summary",
        )
        self._target_folder_summary_inflight: Dict[str, asyncio.Task] = {}
        self._target_folder_summary_inflight_lock = asyncio.Lock()

    def _get_archive_preview_inflight(self) -> Tuple[Dict[str, asyncio.Task], asyncio.Lock]:
        if not hasattr(self, "_archive_preview_inflight"):
            self._archive_preview_inflight = {}
        if not hasattr(self, "_archive_preview_inflight_lock"):
            self._archive_preview_inflight_lock = asyncio.Lock()
        return self._archive_preview_inflight, self._archive_preview_inflight_lock

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

    def _has_translation_text_signal(self, *values: str) -> bool:
        text = " ".join(str(value or "") for value in values).casefold()
        if not text:
            return False
        return any(marker.casefold() in text for marker in self.TRANSLATION_TEXT_MARKERS)

    def _is_unverified_dlsite_translation_info(self, translation_info: Any) -> bool:
        if not translation_info:
            return False
        if getattr(translation_info, "is_original", False):
            return False
        return not any(
            [
                getattr(translation_info, "is_parent", False),
                getattr(translation_info, "is_child", False),
                str(getattr(translation_info, "original_workno", "") or "").strip(),
                str(getattr(translation_info, "parent_workno", "") or "").strip(),
                list(getattr(translation_info, "child_worknos", []) or []),
                str(getattr(translation_info, "lang", "") or "").strip(),
            ]
        )

    async def _detect_uncertain_dlsite_translation(
        self,
        source_rjcode: str,
        source_label: str,
        translation_info: Any,
        resolved_target_rjcode: str,
    ) -> Dict[str, str]:
        if not source_rjcode or resolved_target_rjcode:
            return {}
        if not self._is_unverified_dlsite_translation_info(translation_info):
            return {}

        product_title = ""
        fallback_source = ""
        try:
            product_info = await self.dlsite_service.get_product_info(source_rjcode)
            product = dict((product_info or {}).get("product") or {})
            product_title = str(product.get("work_name") or "").strip()
            fallback_source = str((product_info or {}).get("fallback_source") or "").strip()
        except Exception as exc:
            logger.warning("[字幕补配] 读取 DLsite 页面标题失败: source_rj=%s error=%s", source_rjcode, exc)

        if not self._has_translation_text_signal(source_label, product_title):
            return {}
        return {
            "reason": self.DLSITE_LINKAGE_UNCERTAIN_REASON,
            "product_title": product_title,
            "fallback_source": fallback_source,
        }

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

    async def _collect_archive_subtitles_to_stage(
        self,
        archive_path: str,
        hint_password: Optional[str] = None,
        task: Optional[Task] = None,
    ) -> tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        extracted_dir = None
        stage_dir = ""
        try:
            logger.info("[字幕补配预检] 开始临时解包扫描来源字幕: %s", archive_path)
            if task is not None and task.is_cancelled():
                return "", [], {"status": "cancelled", "reason": "任务已取消"}
            probe_task = Task(
                task_type=TaskType.EXTRACT,
                source_path=archive_path,
                auto_classify=False,
                metadata={"subtitle_probe_mode": True},
            )
            cancel_watcher: Optional[asyncio.Task] = None
            if task is not None:
                probe_task.set_event_hook(lambda _probe_task, _reason: task.mark_changed("progress"))
                if task.is_cancelled():
                    probe_task.cancel()
                    return "", [], {"status": "cancelled", "reason": "任务已取消"}

                async def _cancel_probe_when_parent_cancelled() -> None:
                    try:
                        while not task.is_cancelled() and not probe_task.is_cancelled():
                            await asyncio.sleep(0.2)
                        if task.is_cancelled() and not probe_task.is_cancelled():
                            probe_task.cancel()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.debug("[字幕补配预检] 传播父任务取消失败", exc_info=True)

                cancel_watcher = asyncio.create_task(_cancel_probe_when_parent_cancelled())
            if hint_password:
                probe_task.task_metadata = dict(probe_task.task_metadata or {})
                probe_task.task_metadata["manual_retry_password"] = hint_password
                probe_task.task_metadata["manual_retry_password_only"] = True
            extract_future = asyncio.create_task(self.extract_service.extract(probe_task))
            try:
                extracted_dir = await asyncio.shield(extract_future)
            except asyncio.CancelledError:
                probe_task.cancel()
                extract_future.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await extract_future
                raise
            finally:
                if cancel_watcher is not None:
                    cancel_watcher.cancel()
                    try:
                        await cancel_watcher
                    except asyncio.CancelledError:
                        pass
            if task is not None and task.is_cancelled():
                probe_task.cancel()
                return "", [], {"status": "cancelled", "reason": "任务已取消"}
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

            extracted_subtitles = await asyncio.to_thread(self._scan_source_subtitles, extracted_dir, extracted_dir)
            if not extracted_subtitles:
                raw_nested_failures = (probe_task.task_metadata or {}).get("nested_archive_failures") or []
                nested_failures = (
                    list(raw_nested_failures)
                    if isinstance(raw_nested_failures, list)
                    else [str(raw_nested_failures)]
                )
                if nested_failures:
                    reason = "；".join(str(item) for item in nested_failures[:3])
                    logger.warning(
                        "[字幕补配预检] 嵌套压缩包解压失败，无法扫描其中字幕: source=%s failures=%s",
                        archive_path,
                        nested_failures[:3],
                    )
                    return "", [], {
                        "status": "nested_extract_failed",
                        "reason": f"嵌套压缩包未能解开，无法扫描其中字幕：{reason}",
                    }
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
            staged_subtitles: List[Dict[str, Any]] = []
            for item in extracted_subtitles:
                relative_path = str(item.get("relative_path") or item.get("name") or "").strip().replace("\\", "/")
                if not relative_path:
                    continue
                destination = os.path.join(stage_dir, *relative_path.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                await asyncio.to_thread(shutil.copy2, item.get("path") or "", destination)
                staged_subtitles.append({
                    "name": os.path.basename(destination),
                    "path": destination,
                    "relative_path": relative_path,
                    "source_name": item.get("source_name") or item.get("name") or os.path.basename(destination),
                    "display_name": item.get("display_name") or os.path.basename(destination),
                })

            logger.info(
                "[字幕补配预检] 临时解包扫描到字幕并已复制到工作区: source=%s extracted_dir=%s stage_dir=%s subtitle_count=%s",
                archive_path,
                extracted_dir,
                stage_dir,
                len(staged_subtitles),
            )
            staged_subtitles.sort(key=lambda current: current.get("relative_path") or current.get("name") or "")
            return stage_dir, staged_subtitles, {
                "status": "ok",
                "reason": "",
            }
        finally:
            if extracted_dir and os.path.isdir(extracted_dir):
                logger.info("[字幕补配预检] 清理临时解包目录: %s", extracted_dir)
                await asyncio.to_thread(shutil.rmtree, extracted_dir, True)

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
        """把 source 字幕复制到工作台目录。

        ★ 性能优化（修复用户痛点：导入 / 配对工作台奇慢无比）：
        原版主循环逐个 ``shutil.copy2`` 串行执行，30 个字幕在本地都要 1-3 秒，
        群晖 NAS 上跨卷复制能拖到 30+ 秒。改为：
        1. 第一阶段串行计算所有 (src, dst) 对（dedupe / mkdir），快，纯 CPU 操作。
        2. 第二阶段用 ThreadPoolExecutor 并发执行 ``shutil.copy2``，单次整体耗时
           降到原来的 1/N（受 8 个 worker 上限约束，避免把磁盘 IO 打爆）。
        """
        seen_paths: set[str] = set()
        plans: List[Tuple[str, str, Dict[str, Any]]] = []  # (source_path, destination_path, item_meta)

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
            plans.append((
                source_path,
                destination_path,
                {
                    "name": os.path.basename(destination_path),
                    "path": destination_path,
                    "relative_path": normalized_relative,
                    "source_name": item.get("source_name") or os.path.basename(source_path),
                    "display_name": item.get("display_name") or os.path.basename(destination_path),
                    "order": index,
                },
            ))

        if not plans:
            return []

        # 并发复制：本地磁盘 8 worker 已经能打满 SATA SSD，再多反而 IO 调度抖动。
        # 群晖 NAS 上 SMB / NFS 单连接限制下也能拿到 60-80% 的并发收益。
        copy_workers = min(8, len(plans))

        def _do_copy(plan: Tuple[str, str, Dict[str, Any]]) -> Dict[str, Any]:
            src, dst, meta = plan
            shutil.copy2(src, dst)
            return meta

        if copy_workers == 1:
            copied_items = [_do_copy(plan) for plan in plans]
        else:
            with ThreadPoolExecutor(max_workers=copy_workers, thread_name_prefix="subtitle-stage-copy") as executor:
                copied_items = list(executor.map(_do_copy, plans))

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
            copied_items = await asyncio.to_thread(
                self._copy_source_subtitles_to_workspace,
                stage_plan.get("subtitles") or [],
                destination_dir=local_subtitle_dir,
            )
            if not copied_items:
                raise ValueError("来源中没有可供工作台处理的字幕文件")
        except Exception:
            if os.path.isdir(local_workspace_root):
                await asyncio.to_thread(shutil.rmtree, local_workspace_root, True)
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

    def _should_direct_import_to_empty_candidate(
        self,
        preview: Dict[str, Any],
        target_candidate: Optional[Dict[str, Any]] = None,
    ) -> bool:
        candidates = list(preview.get("candidates") or [])
        candidate = target_candidate or preview.get("selected_candidate")
        if not candidate and len(candidates) == 1:
            candidate = candidates[0]
        if not candidate:
            return False
        if len(candidates) != 1:
            return False
        if not bool(candidate.get("ready_for_import")):
            return False
        if int(candidate.get("existing_subtitle_count") or 0) > 0:
            return False
        return int(candidate.get("total_files") or 0) == 0

    async def _direct_import_source_subtitles_to_target(
        self,
        *,
        source_subtitles: List[Dict[str, Any]],
        target_candidate: Dict[str, Any],
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        library_id = str(target_candidate.get("library_id") or "").strip()
        target_folder_path = str(target_candidate.get("folder_path") or "").strip()
        if not library_id or not target_folder_path:
            raise ValueError("缺少目标目录信息，无法直接入库")

        temp_root = os.path.join(
            self.extract_service.config.storage.temp_path,
            "linked_subtitle_import_direct",
            uuid.uuid4().hex,
        )
        temp_subtitle_dir = os.path.join(temp_root, "subtitles")
        os.makedirs(temp_subtitle_dir, exist_ok=True)

        try:
            stage_plan = self._prepare_workbench_stage_subtitles(
                source_subtitles,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
            )
            copied_items = await asyncio.to_thread(
                self._copy_source_subtitles_to_workspace,
                stage_plan.get("subtitles") or [],
                destination_dir=temp_subtitle_dir,
            )
            if not copied_items:
                raise ValueError("来源中没有可直接入库的字幕文件")

            final_subtitle_dir = await self._publish_workbench_to_target(
                library_id=library_id,
                workbench_root_dir=temp_root,
                subtitle_dir=temp_subtitle_dir,
                target_folder_path=target_folder_path,
            )
            final_items = await self._wait_for_published_subtitles(
                library_id=library_id,
                subtitle_dir=final_subtitle_dir,
                expected_count=len(copied_items),
            )
            return {
                "success": True,
                "partial": False,
                "error": None,
                "download_files": copied_items,
                "downloaded_count": len(copied_items),
                "filtered_out_count": int(stage_plan.get("filtered_out_count") or 0),
                "content_deduped_count": int(stage_plan.get("content_deduped_count") or 0),
                "content_deduped_files": stage_plan.get("content_deduped_files") or [],
                "renamed_collision_files": stage_plan.get("renamed_collision_files") or [],
                "written_files": [
                    {
                        "subtitle_name": item.get("source_name") or item.get("name") or "",
                        "output_name": item.get("relative_path") or item.get("name") or "",
                        "match_type": "empty_target_direct_import",
                        "match_score": 100,
                    }
                    for item in final_items
                ],
                "skipped_files": [],
                "write_errors": [],
                "awaiting_manual_match": False,
                "existing_subtitle_count": int(target_candidate.get("existing_subtitle_count") or 0),
                "subtitle_dir": final_subtitle_dir,
                "subtitle_library_id": library_id,
                "linked_workbench_root_dir": "",
                "match_result": {
                    "matches": [],
                    "matched_group_count": 0,
                    "matched_subtitle_count": len(final_items),
                    "unmatched_audio": [],
                    "unmatched_subtitles": [],
                },
            }
        except Exception:
            if os.path.isdir(temp_root):
                await asyncio.to_thread(shutil.rmtree, temp_root, True)
            raise

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

        workbench_subtitle_dir = os.path.abspath(subtitle_dir)
        if not os.path.isdir(workbench_subtitle_dir):
            raise FileNotFoundError(f"字幕工作台目录不存在: {workbench_subtitle_dir}")

        if library.type == "synology_filestation":
            if not library.synology:
                raise RuntimeError(f"远程库存 {library_id} 缺少群晖连接配置")
            target_subtitle_dir = f"{normalized_target_folder.rstrip('/')}/subtitles"
            client = self.library_manager.get_cached_synology_client(library.synology)
            await self.library_manager._ensure_remote_directory(client, normalized_target_folder)
            await self.library_manager.replace_remote_directory_with_local(
                library_id=library_id,
                source_dir=workbench_subtitle_dir,
                target_path=target_subtitle_dir,
            )
            await asyncio.to_thread(shutil.rmtree, workbench_root_dir, True)
            self._cleanup_empty_workbench_shell(workbench_root_dir)
            # 索引同步：只重扫 subtitles 子目录（避免重扫整个 RJ 100+ 文件）
            self._notify_index_after_subtitle_publish(library, target_subtitle_dir)
            self.invalidate_target_folder_summary_cache(library_id)
            return target_subtitle_dir

        target_folder = os.path.abspath(normalized_target_folder)
        target_subtitle_dir = os.path.join(target_folder, "subtitles")
        target_parent_dir = os.path.dirname(target_subtitle_dir)
        target_name = os.path.basename(target_subtitle_dir.rstrip("\\/")) or "subtitles"
        stage_dir = os.path.join(target_parent_dir, f"{target_name}.__kikoerumanager_stage__.{uuid.uuid4().hex[:8]}")
        backup_dir = os.path.join(target_parent_dir, f"{target_name}.__kikoerumanager_backup__.{uuid.uuid4().hex[:8]}")
        os.makedirs(target_parent_dir, exist_ok=True)

        try:
            await asyncio.to_thread(shutil.copytree, workbench_subtitle_dir, stage_dir)
            if os.path.exists(target_subtitle_dir):
                await asyncio.to_thread(os.replace, target_subtitle_dir, backup_dir)
            await asyncio.to_thread(os.replace, stage_dir, target_subtitle_dir)
            if os.path.exists(backup_dir):
                await asyncio.to_thread(shutil.rmtree, backup_dir, True)
        except Exception:
            if os.path.exists(stage_dir):
                await asyncio.to_thread(shutil.rmtree, stage_dir, True)
            if os.path.exists(backup_dir) and not os.path.exists(target_subtitle_dir):
                try:
                    await asyncio.to_thread(os.replace, backup_dir, target_subtitle_dir)
                except Exception:
                    logger.warning("[字幕补配] 恢复本地字幕目录失败: %s -> %s", backup_dir, target_subtitle_dir, exc_info=True)
            raise

        try:
            await asyncio.to_thread(shutil.rmtree, workbench_root_dir, True)
            self._cleanup_empty_workbench_shell(workbench_root_dir)
        except Exception:
            logger.warning("[字幕补配] 清理本地工作台目录失败: %s", workbench_root_dir, exc_info=True)
        # 索引同步：只重扫 subtitles 子目录（避免重扫整个 RJ 100+ 文件）
        self._notify_index_after_subtitle_publish(library, target_subtitle_dir)
        self.invalidate_target_folder_summary_cache(library_id)
        return target_subtitle_dir

    def _notify_index_after_subtitle_publish(
        self,
        library: Any,
        subtitle_directory_absolute_path: str,
    ) -> None:
        """字幕落盘后只重扫 subtitles 子目录。

        I/O 优化背景：原本是「delete RJ 整个子树 + upsert RJ 整个子树」，那会
        重扫 RJ 下 100+ 个音频文件（实际上音频根本没变），而且中间窗口期里
        整个 RJ 在索引里短暂消失，影响 RJ 号搜索。改成只动 subtitles 子目录：
        - delete `{RJ}/subtitles` 子树清旧字幕条目
        - upsert `{RJ}/subtitles` 子树写新字幕条目
        - RJ 根条目 size 不会刷新，但音频部分根本没变，只有字幕的几十 KB
          误差，下次完整重建索引会修；不影响 RJ 号搜索（RJ 号查的是 RJ
          目录条目而不是 subtitles）

        失败静默。
        """
        try:
            if not subtitle_directory_absolute_path:
                return
            self.library_manager._enqueue_index_replace_subtree_many(
                library, [subtitle_directory_absolute_path],
            )
        except Exception:
            logger.debug(
                "[索引] 字幕落盘后通知索引失败 path=%s",
                subtitle_directory_absolute_path, exc_info=True,
            )

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

        try:
            library = self.library_manager.get_library_definition(library_id)
        except Exception:
            library = None

        deadline = datetime.now().timestamp() + timeout_seconds
        minimum_count = int(expected_count or 0)
        last_error: Optional[Exception] = None
        last_items: List[Dict[str, Any]] = []

        if library and getattr(library, "type", "") == "local":
            try:
                items = await asyncio.to_thread(
                    self._scan_source_subtitles,
                    normalized_dir,
                    normalized_dir,
                )
            except Exception as exc:
                raise RuntimeError(f"目标字幕目录校验失败: {exc}") from exc
            if len(items) >= minimum_count:
                return items
            raise RuntimeError(
                f"目标字幕目录字幕数量不足: expected={minimum_count} actual={len(items)} path={normalized_dir}"
            )

        if minimum_count == 0:
            try:
                contents = await self.library_manager.folder_contents(library_id, normalized_dir, prefer_index=False)
                return [item for item in (contents.get("items") or []) if not item.get("is_directory")]
            except Exception:
                return []

        while datetime.now().timestamp() <= deadline:
            try:
                contents = await self.library_manager.folder_contents(library_id, normalized_dir, prefer_index=False)
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

    async def finalize_manual_match_task(self, task: Task, *, expected_min_files: int = 1) -> Dict[str, Any]:
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
        if expected_file_count <= 0:
            raise ValueError(
                "字幕补配工作台可发布字幕数量异常，已阻止覆盖目标 subtitles 目录: "
                f"expected>=1 actual={expected_file_count}"
            )
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
            "awaiting_manual_match": False,
            "manual_match_completed": True,
            "manual_match_completed_at": datetime.now().isoformat(),
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
        task.current_step = "字幕补配已应用到目标目录"
        task.progress = 100
        task.completed_at = datetime.now()
        return {
            "applied": True,
            "final_subtitle_dir": final_subtitle_dir,
            "final_file_count": len(final_items),
            "expected_file_count": expected_file_count,
        }

    def _refresh_preview_execution_state(self, preview: Dict[str, Any]) -> Dict[str, Any]:
        target_rjcode = str(preview.get("target_rjcode") or "").strip()
        candidates = self._prefer_deepest_target_rj_candidates(
            list(preview.get("candidates") or []),
            target_rjcode,
        )
        preview["candidates"] = candidates
        ready_candidates = [item for item in candidates if bool(item.get("ready_for_import"))]
        selected_candidate = preview.get("selected_candidate")
        if selected_candidate and not bool(selected_candidate.get("ready_for_import")):
            selected_candidate = None
        if selected_candidate and candidates:
            selected_key = (
                str(selected_candidate.get("library_id") or "").strip(),
                str(selected_candidate.get("folder_path") or "").strip(),
            )
            candidate_keys = {
                (
                    str(candidate.get("library_id") or "").strip(),
                    str(candidate.get("folder_path") or "").strip(),
                )
                for candidate in candidates
            }
            if selected_key not in candidate_keys:
                selected_candidate = None
        if not selected_candidate and len(ready_candidates) == 1:
            selected_candidate = ready_candidates[0]

        source_rjcode = str(preview.get("source_rjcode") or "").strip()
        is_translation_work = bool(preview.get("is_translation_work"))
        is_manual_subtitle_source = bool(preview.get("is_manual_subtitle_source"))
        subtitle_count = int(preview.get("subtitle_count") or 0)
        source_exists_in_kikoeru = bool(preview.get("kikoeru_source_found"))
        target_exists_in_kikoeru = bool(preview.get("kikoeru_has_work"))
        target_needs_subtitle_in_kikoeru = bool(preview.get("kikoeru_needs_subtitle"))
        kikoeru_route_confident = bool(preview.get("kikoeru_route_confident", True))
        if candidates:
            target_has_work = True
            target_has_subtitle = all(
                int(item.get("existing_subtitle_count") or 0) > 0 for item in candidates
            )
            target_needs_subtitle = not target_has_subtitle
            target_route_confident = True
        else:
            target_has_work = bool(preview.get("target_has_work", target_exists_in_kikoeru))
            target_has_subtitle = bool(preview.get("target_has_subtitle"))
            target_needs_subtitle = bool(
                preview.get("target_needs_subtitle", target_needs_subtitle_in_kikoeru)
            )
            target_route_confident = bool(
                preview.get("target_route_confident", kikoeru_route_confident)
            )

        stage_reason = str(preview.get("stage_reason") or "")
        source_subtitle_probe_status = str(preview.get("source_subtitle_probe_status") or "").strip().lower()
        source_subtitle_probe_reason = str(preview.get("source_subtitle_probe_reason") or "").strip()
        candidate_search_status = str(preview.get("candidate_search_status") or "")
        candidate_search_reason = str(preview.get("candidate_search_reason") or "")
        source_path = str(preview.get("source_path") or "").strip()
        staged_dirs = [
            str(preview.get("source_subtitle_dir") or "").strip(),
            str(preview.get("staged_subtitle_dir") or "").strip(),
        ]
        staged_dirs = [path for index, path in enumerate(staged_dirs) if path and path not in staged_dirs[:index]]
        has_staged_subtitle_dir = any(os.path.isdir(path) for path in staged_dirs)
        source_path_exists = bool(source_path) and os.path.exists(source_path)
        can_probe_later = self._can_stage_archive_subtitles_later(source_subtitle_probe_status, source_path_exists)

        should_queue_pending = False
        if is_translation_work:
            should_queue_pending = (
                bool(source_rjcode)
                and (
                    target_needs_subtitle_in_kikoeru
                    or target_needs_subtitle
                    or not target_route_confident
                )
                and (subtitle_count > 0 or can_probe_later)
            )
        elif is_manual_subtitle_source:
            should_queue_pending = (
                bool(source_rjcode)
                and (subtitle_count > 0 or can_probe_later)
                and (
                    target_needs_subtitle_in_kikoeru
                    or target_needs_subtitle
                    or not target_route_confident
                )
            )

        treat_as_new_work = bool(preview.get("treat_as_new_work"))
        if (
            is_manual_subtitle_source
            and bool(source_rjcode)
            and target_route_confident
            and not target_has_work
            and not candidates
            and candidate_search_status != "pending_remote"
        ):
            treat_as_new_work = True
            stage_reason = "未命中任何关联作品，按新作直接解压入库"

        can_stage_pending = should_queue_pending and (
            not stage_reason or candidate_search_status == "pending_remote"
        )
        if can_stage_pending and source_path and not source_path_exists and not has_staged_subtitle_dir:
            stage_reason = "来源压缩包和预检字幕工作区都已不存在，无法继续执行"
            can_stage_pending = False
        can_execute = can_stage_pending and len(ready_candidates) > 0 and (
            subtitle_count > 0 or can_probe_later
        )

        execute_reason = ""
        if stage_reason:
            execute_reason = stage_reason
        elif can_probe_later and source_subtitle_probe_status in {
            "missing_password",
            "extract_failed",
            "nested_extract_failed",
        }:
            execute_reason = source_subtitle_probe_reason or "执行时将重新走解压入库链路扫描字幕"
        elif candidate_search_status == "pending_remote":
            execute_reason = candidate_search_reason or self.REMOTE_PENDING_REASON
        elif source_subtitle_probe_status == "timeout":
            execute_reason = source_subtitle_probe_reason or "字幕补配预检超时，执行时将重新解包扫描字幕"
        elif not subtitle_count:
            execute_reason = "压缩包预检临时解包后未发现可导入的字幕文件"
        elif candidates and not ready_candidates:
            execute_reason = "原作目录已有字幕，按重复作品处理"
        elif self._should_direct_import_to_empty_candidate(preview, selected_candidate):
            execute_reason = "目标目录为空且仅命中一个候选目录，将按新作品直接入库"
        elif not candidates:
            execute_reason = "目标作品仍缺字幕，但尚未定位到可用库存目录，可稍后重试或手动选择目标目录"
        elif len(ready_candidates) > 1:
            execute_reason = "命中多个可用目标目录，需要在字幕补配页手动选择"

        preview.update({
            "selected_candidate": selected_candidate,
            "candidate_count": len(candidates),
            "ready_candidate_count": len(ready_candidates),
            "target_has_work": target_has_work,
            "target_has_subtitle": target_has_subtitle,
            "target_needs_subtitle": target_needs_subtitle,
            "target_route_confident": target_route_confident,
            "treat_as_new_work": treat_as_new_work,
            "should_queue_pending": should_queue_pending,
            "stage_reason": stage_reason,
            "can_stage_pending": can_stage_pending,
            "can_execute": can_execute,
            "can_auto_import": bool(selected_candidate and can_execute),
            "execute_reason": execute_reason,
            "reason": stage_reason or execute_reason,
        })
        return preview

    def _can_stage_archive_subtitles_later(self, probe_status: str, source_path_exists: bool) -> bool:
        normalized_status = str(probe_status or "").strip().lower()
        return bool(
            source_path_exists
            and normalized_status in {
                "timeout",
                "missing_password",
                "extract_failed",
                "nested_extract_failed",
            }
        )

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
        hint_password: Optional[str] = None,
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

        stage_dir, source_subtitles, probe_result = await self._collect_archive_subtitles_to_stage(archive_path, hint_password=hint_password)
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
        library_ids: Optional[set[str]] = None,
    ) -> List[Tuple[str, str]]:
        return []

    def _split_candidate_path_segments(self, folder_path: str) -> List[str]:
        normalized = str(folder_path or "").strip().replace("\\", "/").rstrip("/")
        return [segment for segment in normalized.split("/") if segment and segment != "."]

    def _candidate_path_segments_equal(self, left: str, right: str, *, case_sensitive: bool) -> bool:
        if case_sensitive:
            return left == right
        return left.casefold() == right.casefold()

    def _is_candidate_ancestor_path(
        self,
        parent_segments: List[str],
        child_segments: List[str],
        *,
        case_sensitive: bool,
    ) -> bool:
        if not parent_segments or len(parent_segments) >= len(child_segments):
            return False
        return all(
            self._candidate_path_segments_equal(parent, child, case_sensitive=case_sensitive)
            for parent, child in zip(parent_segments, child_segments)
        )

    def _segment_has_target_rjcode(self, segment: str, target_rjcode: str) -> bool:
        normalized_target = str(target_rjcode or "").strip().upper()
        if not normalized_target:
            return False
        return normalized_target in self._extract_all_rjcodes(segment)

    def _prefer_deepest_target_rj_candidates(
        self,
        candidates: List[Dict[str, Any]],
        target_rjcode: str,
    ) -> List[Dict[str, Any]]:
        normalized_target = str(target_rjcode or "").strip().upper()
        if not normalized_target or len(candidates) < 2:
            return candidates

        groups: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            folder_path = str(candidate.get("folder_path") or "").strip()
            if not folder_path:
                groups.append({
                    "index": index,
                    "candidate": candidate,
                    "segments": [],
                    "anchor_segments": [],
                    "library_id": f"__missing_path_{index}",
                    "case_sensitive": False,
                    "is_exact_anchor": False,
                })
                continue
            segments = self._split_candidate_path_segments(folder_path)
            library_id = str(candidate.get("library_id") or "").strip()
            if not library_id or not segments:
                groups.append({
                    "index": index,
                    "candidate": candidate,
                    "segments": segments,
                    "anchor_segments": [],
                    "library_id": f"__invalid_candidate_{index}",
                    "case_sensitive": False,
                    "is_exact_anchor": False,
                })
                continue
            library_type = str(candidate.get("library_type") or "").strip()
            case_sensitive = library_type == "synology_filestation"
            anchor_index = next(
                (
                    position
                    for position in range(len(segments) - 1, -1, -1)
                    if self._segment_has_target_rjcode(segments[position], normalized_target)
                ),
                -1,
            )
            if anchor_index < 0:
                groups.append({
                    "index": index,
                    "candidate": candidate,
                    "segments": segments,
                    "anchor_segments": [],
                    "library_id": f"__unanchored_candidate_{index}",
                    "case_sensitive": case_sensitive,
                    "is_exact_anchor": False,
                })
                continue

            anchor_segments = segments[:anchor_index + 1]
            is_exact_anchor = len(segments) == len(anchor_segments)
            matching_group = next(
                (
                    group
                    for group in groups
                    if group["library_id"] == library_id
                    and len(group["anchor_segments"]) == len(anchor_segments)
                    and all(
                        self._candidate_path_segments_equal(left, right, case_sensitive=case_sensitive)
                        for left, right in zip(group["anchor_segments"], anchor_segments)
                    )
                ),
                None,
            )
            if matching_group is None:
                groups.append({
                    "index": index,
                    "candidate": candidate,
                    "segments": segments,
                    "anchor_segments": anchor_segments,
                    "library_id": library_id,
                    "case_sensitive": case_sensitive,
                    "is_exact_anchor": is_exact_anchor,
                })
                continue

            # 旧索引数据可能给同一 RJ 根目录下的每层子目录都填入 RJ；
            # 优先保留 RJ 根目录自身，根目录缺失时只留最浅的一层。
            should_replace = (
                (is_exact_anchor and not matching_group["is_exact_anchor"])
                or (
                    is_exact_anchor == matching_group["is_exact_anchor"]
                    and len(segments) < len(matching_group["segments"])
                )
            )
            if should_replace:
                matching_group.update({
                    "index": index,
                    "candidate": candidate,
                    "segments": segments,
                    "is_exact_anchor": is_exact_anchor,
                })

        drop_indexes: set[int] = set()
        for parent in groups:
            parent_anchor = list(parent["anchor_segments"])
            if not parent_anchor:
                continue
            for child in groups:
                if child is parent:
                    continue
                if child["library_id"] != parent["library_id"]:
                    continue
                if not self._is_candidate_ancestor_path(
                    parent_anchor,
                    list(child["anchor_segments"]),
                    case_sensitive=bool(parent["case_sensitive"]),
                ):
                    continue
                drop_indexes.add(int(parent["index"]))
                logger.debug(
                    "[字幕补配] 目标目录候选收敛到最里层 RJ 目录: rj=%s parent=%s child=%s",
                    normalized_target,
                    parent["candidate"].get("folder_path") or "",
                    child["candidate"].get("folder_path") or "",
                )
                break

        return [
            group["candidate"]
            for group in sorted(groups, key=lambda item: int(item["index"]))
            if int(group["index"]) not in drop_indexes
        ]

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
            client = self.library_manager.get_cached_synology_client(library.synology)
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

        logger.debug(
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
                logger.debug(
                    "[字幕补配] 远程目标目录未命中，等待后重试: library=%s rj=%s round=%s delay=%.1fs force_refresh=%s",
                    library_id,
                    target_rjcode,
                    round_index,
                    delay_seconds,
                    force_refresh,
                )
                await asyncio.sleep(delay_seconds)

            result = await self.library_manager.list_files(
                library_id,
                page=1,
                page_size=200,
                search=target_rjcode,
                current_path=None,
                sort_by="name",
                sort_order="asc",
                force_refresh=force_refresh,
                search_exact=False,
                search_result_kind="folder",
                remote_warmup_retries=1,
            )
            items = list(result.get("files") or [])
            total = int(result.get("total") or len(items))
            last_items = items
            logger.debug(
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

        folder_info = await self.library_manager.folder_contents(library_id, folder_path, prefer_index=False)
        items = folder_info.get("items") or []

        if library.type == "synology_filestation":
            audio_count = len(self.subtitle_service._collect_remote_audio_entries(items))
            existing_subtitle_count = self.subtitle_service._count_remote_existing_subtitles(items)
            folder_name = folder_path.rstrip("/").split("/")[-1]
            subtitle_dir = f"{folder_path.rstrip('/')}/subtitles"
        else:
            folder = Path(folder_path)
            audio_count, existing_subtitle_count = await asyncio.to_thread(
                self._quick_count_local_candidate_files,
                folder,
            )
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

    def _quick_count_local_candidate_files(self, folder: Path) -> Tuple[int, int]:
        audio_count = 0
        existing_subtitle_count = 0
        try:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [name for name in dirs if name.lower() != "subtitles"]
                for file in files:
                    if os.path.splitext(file)[1].lower() in self.subtitle_service.AUDIO_EXTENSIONS:
                        audio_count += 1
                        if audio_count > 1:
                            break
                if audio_count > 1:
                    break
        except (FileNotFoundError, PermissionError, OSError):
            audio_count = 0

        subtitle_dir = folder / "subtitles"
        if subtitle_dir.is_dir():
            try:
                for _root, _dirs, files in os.walk(subtitle_dir):
                    for file in files:
                        if os.path.splitext(file)[1].lower() in self.subtitle_service.SUBTITLE_EXTENSIONS:
                            existing_subtitle_count += 1
                            if existing_subtitle_count > 1:
                                break
                    if existing_subtitle_count > 1:
                        break
            except (FileNotFoundError, PermissionError, OSError):
                existing_subtitle_count = 0

        return audio_count, existing_subtitle_count

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

    def _get_target_folder_summary_cache_state(self) -> Tuple[TTLCache, Dict[str, asyncio.Task], asyncio.Lock]:
        """兼容测试中绕过 __init__ 构造的轻量 service。"""
        if not hasattr(self, "_target_folder_summary_cache"):
            self._target_folder_summary_cache = TTLCache(
                max_size=self._FOLDER_SUMMARY_CACHE_L1_MAX_SIZE,
                ttl_seconds=self._FOLDER_SUMMARY_CACHE_L1_TTL_SECONDS,
                name="linked_subtitle.target_folder_summary",
            )
        if not hasattr(self, "_target_folder_summary_inflight"):
            self._target_folder_summary_inflight = {}
        if not hasattr(self, "_target_folder_summary_inflight_lock"):
            self._target_folder_summary_inflight_lock = asyncio.Lock()
        return (
            self._target_folder_summary_cache,
            self._target_folder_summary_inflight,
            self._target_folder_summary_inflight_lock,
        )

    def _get_target_folder_summary_generations(self) -> Dict[str, int]:
        """Redis 不可用时仍以进程内版本隔离失效前的慢扫描结果。"""
        if not hasattr(self, "_target_folder_summary_generations"):
            self._target_folder_summary_generations = {}
        return self._target_folder_summary_generations

    def _target_folder_summary_redis_service(self):
        try:
            from .redis_service import get_redis_service

            service = get_redis_service()
            return service if service.is_enabled() else None
        except Exception:
            logger.debug("[字幕补配·缓存] 获取 Redis 服务失败", exc_info=True)
            return None

    def _normalize_target_folder_summary_path(self, library_id: str, folder_path: str) -> str:
        library = self.library_manager.get_library_definition(library_id)
        raw_path = str(folder_path or "").strip()
        if getattr(library, "type", "") == "synology_filestation":
            return self.library_manager._normalize_remote_path(raw_path)
        return os.path.normcase(os.path.abspath(raw_path))

    def _target_folder_summary_library_version(self, library_id: str) -> int:
        service = self._target_folder_summary_redis_service()
        if service is None:
            return 0
        try:
            client = service.client(required=False)
            if client is None:
                return 0
            raw_version = client.get(service.key("rj-subtitle", "folder-summary-version", library_id))
            return max(0, int(raw_version or 0))
        except Exception:
            logger.debug("[字幕补配·缓存] 读取目录摘要版本失败 library=%s", library_id, exc_info=True)
            return 0

    def _target_folder_summary_has_shared_version(self) -> bool:
        service = self._target_folder_summary_redis_service()
        if service is None:
            return False
        try:
            return service.client(required=False) is not None
        except Exception:
            return False

    def _target_folder_summary_cache_key(
        self,
        library_id: str,
        folder_path: str,
        version: int,
        generation: int,
    ) -> str:
        path_hash = hashlib.sha1(folder_path.encode("utf-8", errors="replace")).hexdigest()
        return "|".join([
            str(library_id),
            f"s{self._FOLDER_SUMMARY_CACHE_SCHEMA_VERSION}",
            f"v{max(0, int(version or 0))}",
            f"g{max(0, int(generation or 0))}",
            path_hash,
        ])

    def _get_cached_target_folder_summary(self, cache_key: str) -> Optional[Dict[str, Any]]:
        cache, _inflight, _lock = self._get_target_folder_summary_cache_state()
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return deepcopy(cached)

        service = self._target_folder_summary_redis_service()
        if service is None:
            return None
        try:
            cached = service.get_json("rj-subtitle", "folder-summary", cache_key)
        except Exception:
            logger.debug("[字幕补配·缓存] Redis 读取目录摘要失败 key=%s", cache_key, exc_info=True)
            return None
        if not isinstance(cached, dict):
            return None
        cache[cache_key] = deepcopy(cached)
        return deepcopy(cached)

    def _set_cached_target_folder_summary(self, cache_key: str, payload: Dict[str, Any]) -> None:
        cache, _inflight, _lock = self._get_target_folder_summary_cache_state()
        cache[cache_key] = deepcopy(payload)
        service = self._target_folder_summary_redis_service()
        if service is None:
            return
        try:
            service.set_json(
                "rj-subtitle",
                "folder-summary",
                cache_key,
                payload,
                ttl_seconds=service.short_cache_ttl_seconds(),
            )
        except Exception:
            logger.debug("[字幕补配·缓存] Redis 写入目录摘要失败 key=%s", cache_key, exc_info=True)

    def invalidate_target_folder_summary_cache(self, library_id: str) -> int:
        """使一个库存下的字幕目录摘要立即失效，并跨进程推进 Redis 版本。"""
        normalized_library_id = str(library_id or "").strip()
        if not normalized_library_id:
            return 0
        cache, _inflight, _lock = self._get_target_folder_summary_cache_state()
        generations = self._get_target_folder_summary_generations()
        generations[normalized_library_id] = int(generations.get(normalized_library_id, 0) or 0) + 1
        removed = cache.invalidate_predicate(
            lambda key: isinstance(key, str) and key.startswith(f"{normalized_library_id}|")
        )
        service = self._target_folder_summary_redis_service()
        if service is None:
            return removed
        try:
            client = service.client(required=False)
            if client is not None:
                client.incr(service.key("rj-subtitle", "folder-summary-version", normalized_library_id))
        except Exception:
            logger.debug("[字幕补配·缓存] 推进目录摘要版本失败 library=%s", normalized_library_id, exc_info=True)
        return removed

    async def summarize_target_folder_cached(
        self,
        library_id: str,
        folder_path: str,
    ) -> Optional[Dict[str, Any]]:
        """目录字幕摘要的 L1/L2 缓存入口；同路径并发读取只执行一次真实扫描。"""
        normalized_library_id = str(library_id or "").strip()
        normalized_folder_path = str(folder_path or "").strip()
        if not normalized_library_id or not normalized_folder_path:
            return None
        normalized_folder_path = self._normalize_target_folder_summary_path(
            normalized_library_id,
            normalized_folder_path,
        )
        version = self._target_folder_summary_library_version(normalized_library_id)
        generation = int(self._get_target_folder_summary_generations().get(normalized_library_id, 0) or 0)
        cache_generation = 0 if self._target_folder_summary_has_shared_version() else generation
        cache_key = self._target_folder_summary_cache_key(
            normalized_library_id,
            normalized_folder_path,
            version,
            cache_generation,
        )
        cached = self._get_cached_target_folder_summary(cache_key)
        if cached is not None:
            return cached

        cache, inflight, lock = self._get_target_folder_summary_cache_state()

        async def load() -> Optional[Dict[str, Any]]:
            summary = await self.summarize_target_folder(
                normalized_library_id,
                normalized_folder_path,
            )
            if isinstance(summary, dict):
                current_generation = int(
                    self._get_target_folder_summary_generations().get(normalized_library_id, 0) or 0
                )
                current_version = self._target_folder_summary_library_version(normalized_library_id)
                if current_generation == generation and current_version == version:
                    self._set_cached_target_folder_summary(cache_key, summary)
                return summary
            return None

        async with lock:
            cached = self._get_cached_target_folder_summary(cache_key)
            if cached is not None:
                return cached
            task = inflight.get(cache_key)
            if task is None:
                task = asyncio.create_task(
                    load(),
                    name=f"rj-subtitle-folder-summary:{normalized_library_id}",
                )
                inflight[cache_key] = task

                # 调用方可能全部取消；由完成回调回收槽位，避免过期后继续复用旧 task。
                def cleanup_inflight(completed_task: asyncio.Task) -> None:
                    if inflight.get(cache_key) is completed_task:
                        inflight.pop(cache_key, None)

                task.add_done_callback(cleanup_inflight)

        try:
            # 调用方取消只结束自己的等待，不能取消其他工作台读取正在共享的真实扫描。
            result = await asyncio.shield(task)
            return deepcopy(result) if isinstance(result, dict) else None
        finally:
            # done callback 已负责回收；shield 保证调用方断开不会取消共享扫描。
            pass

    async def _summarize_remote_candidate(self, library: Any, folder_path: str) -> Dict[str, Any]:
        if not getattr(library, "synology", None):
            raise RuntimeError("远程库存缺少群晖连接配置")

        normalized_folder_path = self.library_manager._normalize_remote_path(folder_path)
        folder_name = PurePosixPath(normalized_folder_path).name or normalized_folder_path
        subtitle_dir = f"{normalized_folder_path.rstrip('/')}/subtitles"
        folder_info = await self.library_manager.folder_contents(library.id, normalized_folder_path, prefer_index=False)
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
        try:
            index_hits = self.library_manager.find_rj_in_ready_index([target_rjcode])
        except Exception:
            logger.warning("[字幕补配] ready 库存索引目标目录查询失败: rj=%s", target_rjcode, exc_info=True)
            index_hits = {}

        candidates: List[Dict[str, Any]] = []
        seen_paths: set[Tuple[str, str]] = set()
        for hit in list(index_hits.get(str(target_rjcode or "").strip().upper()) or []):
            library_id = str(hit.get("library_id") or "").strip()
            folder_path = str(hit.get("path") or "").strip()
            if preferred_library_id and library_id != str(preferred_library_id).strip():
                # 优先库不是硬过滤，先排序即可；这里不跳过，避免用户选错库时看不到真实命中。
                pass
            dedupe_key = (library_id, folder_path)
            if not library_id or not folder_path or dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)
            subtitle_count = int(hit.get("subtitle_file_count") or 0)
            candidates.append({
                "library_id": library_id,
                "library_name": str(hit.get("library_name") or library_id),
                "library_type": str(hit.get("library_type") or ""),
                "folder_path": folder_path,
                "folder_name": str(hit.get("name") or os.path.basename(folder_path.rstrip("/\\")) or target_rjcode),
                "audio_count": 0,
                "existing_subtitle_count": subtitle_count,
                "has_existing_subtitles": bool(hit.get("local_subtitle_present")) or subtitle_count > 0,
                "has_audio": True,
                "total_files": int(hit.get("file_count") or 0),
                "total_size": int(hit.get("size") or 0),
                "subtitle_dir": str(hit.get("subtitle_dir") or ""),
                "file_samples": [],
                "ready_for_import": not (bool(hit.get("local_subtitle_present")) or subtitle_count > 0),
            })

        candidates = self._prefer_deepest_target_rj_candidates(candidates, target_rjcode)
        candidates.sort(
            key=lambda item: (
                0 if str(item.get("library_id") or "") == str(preferred_library_id or "") else 1,
                1 if item.get("has_existing_subtitles") else 0,
                item.get("library_name") or "",
                item.get("folder_path") or "",
            )
        )
        search_status = "matched" if candidates else "not_found"
        search_reason = "" if candidates else "ready 库存索引未命中原作目录"
        logger.info(
            "[字幕补配] ready 库存索引目标目录搜索摘要: rj=%s status=%s candidate_count=%s preferred_library=%s",
            target_rjcode,
            search_status,
            len(candidates),
            preferred_library_id or "",
        )
        return {
            "candidates": candidates,
            "search_status": search_status,
            "search_reason": search_reason,
        }

    def _load_local_translation_target_rjcode(self, source_rjcode: str) -> str:
        """从 PostgreSQL 已物化的 canonical 关联链恢复翻译作原作。"""
        normalized_source = self._extract_rjcode(source_rjcode)
        if not normalized_source:
            return ""

        db = SessionLocal()
        try:
            row = (
                db.query(WorkCanonicalLink)
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    WorkCanonicalLink.linked_rjcode == normalized_source,
                    WorkCanonicalLink.link_type.in_(("translation", "child_translation")),
                    WorkCanonicalLink.canonical_rjcode != normalized_source,
                )
                .order_by(WorkCanonicalLink.cached_at.desc())
                .first()
            )
        except Exception:
            logger.warning(
                "[字幕补配] 读取本地 canonical 关联失败: source_rj=%s",
                normalized_source,
                exc_info=True,
            )
            return ""
        finally:
            db.close()

        return self._extract_rjcode(getattr(row, "canonical_rjcode", "") or "") if row else ""

    async def _resolve_translation_target_rjcode(self, source_rjcode: str, translation_info: Any) -> str:
        target_rjcode = ""
        translation_verified = (
            str(getattr(translation_info, "evidence_status", "") or "").strip().lower()
            == "verified"
        )
        if (
            translation_info
            and translation_verified
            and not getattr(translation_info, "is_original", False)
        ):
            target_rjcode = str(getattr(translation_info, "original_workno", "") or "").strip().upper()
        if target_rjcode or not source_rjcode:
            return target_rjcode

        local_target_rjcode = await asyncio.to_thread(
            self._load_local_translation_target_rjcode,
            source_rjcode,
        )
        if local_target_rjcode:
            logger.info(
                "[字幕补配] 实时 DLsite 关联不完整，使用本地 canonical 关联: "
                "source_rj=%s target_rj=%s",
                source_rjcode,
                local_target_rjcode,
            )
            return local_target_rjcode

        try:
            product_info = await self.dlsite_service.get_product_info(source_rjcode)
        except Exception as exc:
            product_info = None
            logger.warning("[字幕补配] 读取作品语言版本失败: source_rj=%s error=%s", source_rjcode, exc)

        if (
            product_info
            and product_info.get("product")
            and str(
                product_info.get("metadata_verification_status") or ""
            ).strip().lower() == "verified"
        ):
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
            if str(
                getattr(work, "evidence_status", "") or ""
            ).strip().lower() != "verified":
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
        _prefetched_translation: Optional[Tuple[Any, str]] = None,
        _prefetched_target_kikoeru=None,
        is_small_archive: bool = False,
    ) -> Dict[str, Any]:
        source_rjcode = self._extract_rjcode(source_rjcode)
        if _prefetched_translation is not None:
            translation_info, resolved_target_rjcode = _prefetched_translation
        else:
            translation_info = await self.dlsite_service.get_translation_info(source_rjcode) if source_rjcode else None
            resolved_target_rjcode = await self._resolve_translation_target_rjcode(source_rjcode, translation_info)
        is_translation_work = bool(source_rjcode and resolved_target_rjcode and resolved_target_rjcode != source_rjcode)
        # Some manually made subtitle packs are placed directly into the original RJ folder.
        # When the source is not a translation work but clearly contains subtitle files,
        # we still treat it as a linked subtitle source and supplement the same RJ work.
        is_manual_subtitle_source = bool(source_rjcode and subtitle_count > 0 and not is_translation_work)
        # 小型压缩包：即使包内未扫到字幕文件，也先用 Kikoeru 判断目标是否需要补配。
        # 只有确认目标作品存在、无字幕、非空壳后才强制进入补配路由。
        if is_small_archive and source_rjcode and not is_translation_work and not is_manual_subtitle_source:
            # 用 source_rjcode 作为临时 target，下方查 Kikoeru 后再修正
            target_rjcode = source_rjcode
        else:
            target_rjcode = resolved_target_rjcode or (source_rjcode if is_manual_subtitle_source else "")
        is_linked_subtitle_source = bool(is_translation_work or is_manual_subtitle_source)
        uncertain_dlsite_translation = await self._detect_uncertain_dlsite_translation(
            source_rjcode,
            source_label,
            translation_info,
            resolved_target_rjcode,
        )
        dlsite_linkage_uncertain = bool(uncertain_dlsite_translation)

        async def _safe_kikoeru(rjcode: str) -> Tuple[Any, bool]:
            try:
                result = await self.kikoeru_service.check_duplicate(rjcode, use_cache=True)
                return result, self._is_kikoeru_result_reliable(result)
            except Exception as exc:
                logger.warning("[字幕补配] Kikoeru 查询失败: rj=%s error=%s", rjcode, exc)
                return None, False

        async def _noop_kikoeru() -> Tuple[None, bool]:
            return None, True

        source_coro = _safe_kikoeru(source_rjcode) if source_rjcode else _noop_kikoeru()
        if _prefetched_target_kikoeru is not None:
            source_kikoeru_result, source_kikoeru_query_ok = await source_coro
            target_kikoeru_result = _prefetched_target_kikoeru
            target_kikoeru_query_ok = (
                self._is_kikoeru_result_reliable(_prefetched_target_kikoeru)
                if target_rjcode
                else True
            )
        elif source_rjcode and target_rjcode and source_rjcode == target_rjcode:
            source_kikoeru_result, source_kikoeru_query_ok = await source_coro
            target_kikoeru_result = source_kikoeru_result
            target_kikoeru_query_ok = source_kikoeru_query_ok
        else:
            target_coro = _safe_kikoeru(target_rjcode) if target_rjcode else _noop_kikoeru()
            (source_kikoeru_result, source_kikoeru_query_ok), (
                target_kikoeru_result,
                target_kikoeru_query_ok,
            ) = await asyncio.gather(source_coro, target_coro)

        source_exists_in_kikoeru = bool(
            source_kikoeru_result and getattr(source_kikoeru_result, "is_found", False)
        )
        target_exists_in_kikoeru = bool(
            target_kikoeru_result and getattr(target_kikoeru_result, "is_found", False)
        )
        target_has_subtitle_in_kikoeru = bool(
            target_kikoeru_result and getattr(target_kikoeru_result, "has_lyric_hint", False)
        )
        target_needs_subtitle_in_kikoeru = bool(target_exists_in_kikoeru and not target_has_subtitle_in_kikoeru)
        kikoeru_route_confident = bool(source_kikoeru_query_ok and target_kikoeru_query_ok)
        target_total_track = -1
        if target_kikoeru_result:
            raw_total_track = getattr(target_kikoeru_result, "total_track_count", -1)
            target_total_track = -1 if raw_total_track is None else int(raw_total_track)
        target_check_source = str(getattr(target_kikoeru_result, "subtitle_check_source", "") or "") if target_kikoeru_result else ""
        target_subtitle_count = int(getattr(target_kikoeru_result, "subtitle_file_count", 0) or 0) if target_kikoeru_result else 0
        kikoeru_target_is_empty_shell = bool(
            target_exists_in_kikoeru
            and target_check_source == "tracks"
            and target_total_track == 0
        )
        # 小型压缩包补配强制路由：Kikoeru 确认目标作品存在、无字幕、非空壳 → 强制视为 manual_subtitle_source。
        # 此时无论压缩包内是否已扫到字幕文件，都进入字幕补配队列，由后续人工筛选 / 自动配对处理。
        if (
            is_small_archive
            and not is_translation_work
            and not is_manual_subtitle_source
            and target_exists_in_kikoeru
            and not target_has_subtitle_in_kikoeru
            and not kikoeru_target_is_empty_shell
            and kikoeru_route_confident
            and source_rjcode
        ):
            is_manual_subtitle_source = True
            is_linked_subtitle_source = True
            logger.info(
                "[字幕补配预检] 小型压缩包按 Kikoeru 状态强制进入补配路由: source_rj=%s target_rj=%s",
                source_rjcode,
                target_rjcode,
            )

        # 只有确认是"有可补配字幕的关联作品"时才查候选目录，非翻译/非手动字幕包时跳过
        candidate_bundle = await self.search_target_candidates(
            target_rjcode,
            preferred_library_id=preferred_library_id,
        ) if target_rjcode and is_linked_subtitle_source else []
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
        has_local_target_candidate = bool(candidates)
        has_ready_target_candidate = bool(ready_candidates)
        local_target_has_subtitle = bool(
            candidates
            and all(int(item.get("existing_subtitle_count") or 0) > 0 for item in candidates)
        )
        target_has_work = bool(target_exists_in_kikoeru or has_local_target_candidate)
        target_has_subtitle = bool(target_has_subtitle_in_kikoeru or local_target_has_subtitle)
        target_needs_subtitle = bool(target_has_work and not target_has_subtitle)
        target_route_confident = bool(kikoeru_route_confident or has_local_target_candidate)

        treat_as_new_work = (
            bool(source_rjcode)
            and target_route_confident
            and not dlsite_linkage_uncertain
            and (
                not target_rjcode
                or (
                    candidate_search_status != "pending_remote"
                    and not target_has_work
                    and not candidates
                )
            )
        )
        should_queue_pending = False
        if is_translation_work:
            should_queue_pending = (
                bool(source_rjcode)
                and bool(target_rjcode)
                and subtitle_count > 0
            )
        elif is_manual_subtitle_source:
            # 小包强制激活路径：subtitle_count 可能为 0（包内字幕未在预检阶段提取），
            # 只要 Kikoeru 确认目标需要字幕就允许进队列，后续在字幕补配页再决定。
            _manual_needs_subtitle = target_needs_subtitle or not target_route_confident
            if is_small_archive and not subtitle_count:
                should_queue_pending = bool(source_rjcode) and _manual_needs_subtitle
            else:
                should_queue_pending = (
                    bool(source_rjcode)
                    and subtitle_count > 0
                    and _manual_needs_subtitle
                )

        stage_reason = ""
        if not source_rjcode:
            stage_reason = "无法识别来源作品 RJ 号"
        elif dlsite_linkage_uncertain:
            stage_reason = uncertain_dlsite_translation.get("reason") or self.DLSITE_LINKAGE_UNCERTAIN_REASON
        elif treat_as_new_work:
            stage_reason = "未命中任何关联作品，按新作直接解压入库"
        elif not target_route_confident:
            stage_reason = ""
        elif kikoeru_target_is_empty_shell:
            stage_reason = "字幕补配时发现服务器作品为空壳"
        elif not is_linked_subtitle_source:
            stage_reason = "当前作品不是可补配到原作的翻译作品"
        elif target_has_subtitle:
            # Kikoeru 原作已有字幕：当前翻译作没有字幕补配价值，统一走"原作已有字幕"
            # 重复路径，由 _is_existing_subtitle_duplicate_preview 识别后转入 LINKED_WORK 问题作品。
            stage_reason = self.EXISTING_SUBTITLE_REASON
        elif candidates and not ready_candidates:
            stage_reason = self.EXISTING_SUBTITLE_REASON
        execute_reason = ""
        if stage_reason:
            execute_reason = stage_reason
        elif not target_route_confident:
            execute_reason = "关联作品库存状态不稳定，暂不自动降级为普通解压，稍后重试"
        elif candidate_search_status == "pending_remote":
            execute_reason = candidate_search_reason or self.REMOTE_PENDING_REASON
        elif not subtitle_count:
            execute_reason = "来源内容中没有可导入的字幕文件"
        elif not candidates:
            execute_reason = "目标作品仍缺字幕，但尚未定位到可用库存目录，可稍后重试或手动选择目标目录"
        elif len(ready_candidates) > 1:
            execute_reason = "命中多个可用目标目录，需要在字幕补配页手动选择"

        can_stage_pending = should_queue_pending and (not stage_reason or candidate_search_status == "pending_remote")
        can_execute = can_stage_pending and subtitle_count > 0 and has_ready_target_candidate

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
            "kikoeru_target_is_empty_shell": kikoeru_target_is_empty_shell,
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
            "kikoeru_subtitle_file_count": target_subtitle_count,
            "target_has_work": target_has_work,
            "target_has_subtitle": target_has_subtitle,
            "target_needs_subtitle": target_needs_subtitle,
            "target_route_confident": target_route_confident,
            "target_state_source": "ready_library_index" if has_local_target_candidate else "kikoeru",
            "dlsite_linkage_uncertain": dlsite_linkage_uncertain,
            "dlsite_linkage_uncertain_reason": uncertain_dlsite_translation.get("reason", ""),
            "dlsite_fallback_source": uncertain_dlsite_translation.get("fallback_source", ""),
            "dlsite_product_title": uncertain_dlsite_translation.get("product_title", ""),
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
        hint_password: Optional[str] = None,
        task: Optional[Task] = None,
        precheck_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        archive_path = await self._wait_for_archive_file(archive_path)
        archive_path = str(archive_path or "").strip()
        if not archive_path:
            raise ValueError("压缩包路径不能为空")
        if not os.path.exists(archive_path):
            raise FileNotFoundError("压缩包不存在")
        if not os.path.isfile(archive_path):
            raise ValueError("指定路径不是压缩包文件")

        return await self._run_archive_preview_inflight(
            archive_path,
            preferred_library_id=preferred_library_id,
            source_rjcode_hint=source_rjcode_hint,
            hint_password=hint_password,
            task=task,
            precheck_timeout=precheck_timeout,
        )

    async def _run_archive_preview_inflight(
        self,
        archive_path: str,
        *,
        preferred_library_id: Optional[str] = None,
        source_rjcode_hint: Optional[str] = None,
        hint_password: Optional[str] = None,
        task: Optional[Task] = None,
        precheck_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        inflight, inflight_lock = self._get_archive_preview_inflight()
        inflight_key = os.path.normcase(os.path.abspath(archive_path))
        async with inflight_lock:
            preview_task = inflight.get(inflight_key)
            if preview_task is None or preview_task.done():
                preview_task = asyncio.create_task(
                    self._preview_archive_import_uncached(
                        archive_path,
                        preferred_library_id=preferred_library_id,
                        source_rjcode_hint=source_rjcode_hint,
                        hint_password=hint_password,
                        task=task,
                    )
                )
                inflight[inflight_key] = preview_task

        try:
            if precheck_timeout and precheck_timeout > 0:
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(preview_task),
                        timeout=float(precheck_timeout),
                    )
                except asyncio.TimeoutError as exc:
                    preview_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await preview_task
                    if task is not None:
                        task.update_progress(5, "字幕补配预检超时，已加入字幕补配待处理")
                    fallback_preview = await self._build_timeout_archive_preview(
                        archive_path,
                        preferred_library_id=preferred_library_id,
                        source_rjcode_hint=source_rjcode_hint,
                    )
                    raise LinkedSubtitleArchivePrecheckTimeout(fallback_preview) from exc
            return await asyncio.shield(preview_task)
        except asyncio.CancelledError:
            preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await preview_task
            raise
        finally:
            if preview_task.done():
                async with inflight_lock:
                    if inflight.get(inflight_key) is preview_task:
                        inflight.pop(inflight_key, None)

    async def _preview_archive_import_uncached(
        self,
        archive_path: str,
        *,
        preferred_library_id: Optional[str] = None,
        source_rjcode_hint: Optional[str] = None,
        hint_password: Optional[str] = None,
        task: Optional[Task] = None,
    ) -> Dict[str, Any]:
        _subtitle_size_threshold = int(self.extract_service.NESTED_SUBTITLE_SIZE_THRESHOLD)
        try:
            _archive_size = os.path.getsize(archive_path)
        except OSError:
            _archive_size = 0
        _is_small_archive = (0 < _archive_size < _subtitle_size_threshold)
        source_rjcode = self._extract_rjcode(source_rjcode_hint) or self._extract_rjcode_from_paths(archive_path)
        archive_info = None
        if not source_rjcode:
            archive_info = await self.extract_service.get_archive_info(
                archive_path,
                task=task,
                list_timeout=self.extract_service.PRECHECK_LIST_TIMEOUT_SECONDS,
            )
            source_rjcode = self._extract_rjcode_from_paths(
                archive_path,
                getattr(archive_info, "inferred_rjcode", "") if archive_info else "",
            )

        stage_dir: str = ""
        source_subtitles: List[Dict[str, Any]] = []
        probe_result: Dict[str, Any] = {}

        if 0 < _archive_size < _subtitle_size_threshold:
            # 小包（< 10MB）：先解压探查字幕，再查 DLsite 确认翻译作关系，
            # 本地字幕状态由 _build_common_preview 读取 ready 库存索引。
            stage_dir, source_subtitles, probe_result = await self._collect_archive_subtitles_to_stage(
                archive_path,
                hint_password=hint_password,
                task=task,
            )
            logger.info(
                "[字幕补配预检] 小型压缩包先解压后判断路由: source=%s source_rj=%s"
                " size=%.1fKB subtitle_count=%s",
                archive_path,
                source_rjcode,
                _archive_size / 1024,
                len(source_subtitles),
            )
            translation_info = await self.dlsite_service.get_translation_info(source_rjcode) if source_rjcode else None
            resolved_target_rjcode = await self._resolve_translation_target_rjcode(source_rjcode, translation_info)
            prefetched_target_kikoeru = None
            prefetched_target_has_subtitle = False
        else:
            # 大包：Step 1 查 DLsite 确认是否翻译作品
            translation_info = await self.dlsite_service.get_translation_info(source_rjcode) if source_rjcode else None
            resolved_target_rjcode = await self._resolve_translation_target_rjcode(source_rjcode, translation_info)
            is_translation_work = bool(source_rjcode and resolved_target_rjcode and resolved_target_rjcode != source_rjcode)

            # Step 2：如果是翻译作品，先查 Kikoeru 确认原作是否已有字幕，有字幕就不需要解包
            prefetched_target_kikoeru = None
            prefetched_target_has_subtitle = False
            if is_translation_work and resolved_target_rjcode:
                try:
                    prefetched_target_kikoeru = await self.kikoeru_service.check_duplicate(
                        resolved_target_rjcode,
                        use_cache=True,
                    )
                    prefetched_target_has_subtitle = bool(
                        prefetched_target_kikoeru
                        and getattr(prefetched_target_kikoeru, "has_lyric_hint", False)
                    )
                except Exception as exc:
                    logger.warning(
                        "[字幕补配预检] 预查 Kikoeru target 失败: rj=%s error=%s",
                        resolved_target_rjcode,
                        exc,
                    )

            # Step 3：决定是否解包——翻译作品且原作缺字幕才解包
            if is_translation_work and not prefetched_target_has_subtitle:
                stage_dir, source_subtitles, probe_result = await self._collect_archive_subtitles_to_stage(
                    archive_path,
                    hint_password=hint_password,
                    task=task,
                )
            elif not is_translation_work:
                logger.info(
                    "[字幕补配预检] 大型非翻译作品压缩包，跳过临时解包: source=%s source_rj=%s size=%s",
                    archive_path,
                    source_rjcode,
                    _archive_size,
                )
            else:
                logger.info(
                    "[字幕补配预检] 原作已有字幕，跳过临时解包: source=%s source_rj=%s target_rj=%s",
                    archive_path,
                    source_rjcode,
                    resolved_target_rjcode,
                )

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
            _prefetched_translation=(translation_info, resolved_target_rjcode),
            _prefetched_target_kikoeru=prefetched_target_kikoeru,
            is_small_archive=_is_small_archive,
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

    async def _build_timeout_archive_preview(
        self,
        archive_path: str,
        *,
        preferred_library_id: Optional[str] = None,
        source_rjcode_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        source_rjcode = self._extract_rjcode(source_rjcode_hint) or self._extract_rjcode_from_paths(archive_path)
        preview = await self._build_common_preview(
            source_rjcode=source_rjcode,
            source_label=os.path.basename(str(archive_path or "")) or "字幕补配预检",
            subtitle_count=0,
            preferred_library_id=preferred_library_id,
        )
        preview.update({
            "mode": "archive",
            "source_path": archive_path,
            "source_has_subtitles": False,
            "source_subtitle_dir": "",
            "staged_subtitle_dir": "",
            "source_subtitle_probe_status": "timeout",
            "source_subtitle_probe_reason": "字幕补配预检超时，执行时将重新解包扫描字幕",
            "fatal_extract_error": "",
            "subtitle_entries": [],
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

    async def _register_import_task(
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
        await asyncio.to_thread(engine.persist_task_snapshot, task)
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
        await asyncio.to_thread(engine.persist_task_snapshot, task)
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
        if int(preview.get("subtitle_count") or 0) <= 0:
            raise ValueError(
                str(
                    preview.get("source_subtitle_probe_reason")
                    or preview.get("reason")
                    or "压缩包内未发现可导入的字幕文件"
                )
            )
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
                if not source_subtitles:
                    logger.warning(
                        "[字幕补配] 预检缓存字幕工作区为空，重新解包来源压缩包: source=%s stage_dir=%s",
                        archive_path,
                        source_dir,
                    )
                    temp_dir, source_subtitles, _probe_result = await self._collect_archive_subtitles_to_stage(archive_path)
            else:
                temp_dir, source_subtitles, _probe_result = await self._collect_archive_subtitles_to_stage(archive_path)
            if self._should_direct_import_to_empty_candidate(preview, target_candidate):
                import_result = await self._direct_import_source_subtitles_to_target(
                    source_subtitles=source_subtitles,
                    target_candidate=target_candidate,
                    use_filter_rules=use_filter_rules,
                    subtitle_filter_rules=subtitle_filter_rules,
                )
            else:
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
                await asyncio.to_thread(shutil.rmtree, temp_dir, True)

        task = None
        if import_result.get("success") and import_result.get("awaiting_manual_match"):
            task = await self._register_import_task(
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
        if self._should_direct_import_to_empty_candidate(preview, target_candidate):
            import_result = await self._direct_import_source_subtitles_to_target(
                source_subtitles=source_subtitles,
                target_candidate=target_candidate,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
            )
        else:
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
            task = await self._register_import_task(
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

    def _build_target_linked_works_info(
        self,
        preview: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        folder_path = str(candidate.get("folder_path") or "").strip()
        target_rjcodes = self._extract_all_rjcodes(
            preview.get("target_rjcode") or ""
        )
        if not folder_path or len(target_rjcodes) != 1:
            return []
        target_rjcode = target_rjcodes[0]
        return [{
            "rjcode": target_rjcode,
            "work_type": "original",
            "lang": "JPN",
            "path": folder_path,
            "work_name": str(
                preview.get("kikoeru_title")
                or candidate.get("folder_name")
                or target_rjcode
            ).strip(),
            "source": "linked_subtitle_preflight",
        }]

    def _upsert_existing_subtitle_conflict(
        self,
        db,
        *,
        source_path: str,
        preview: Dict[str, Any],
        task_id: Optional[str] = None,
        queue_origin: str = "auto_process",
    ) -> Optional[ConflictWork]:
        normalized_source_path = str(source_path or "").strip()
        if not normalized_source_path:
            raise ValueError("缺少来源路径，无法写入问题作品")
        if not self._is_existing_subtitle_duplicate_preview(preview):
            raise ValueError("当前预检结果不是原作已有字幕问题项")

        preview_data = dict(preview or {})
        candidate = self._pick_existing_subtitle_conflict_candidate(preview_data)
        if not candidate:
            return None
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
        linked_works_info = self._build_target_linked_works_info(
            preview_data,
            candidate,
        )

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
            conflict.linked_works_info = linked_works_info
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
            linked_works_info=linked_works_info,
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

        candidate = self._pick_existing_subtitle_conflict_candidate(dict(preview or {}))
        if not candidate:
            logger.info(
                "[字幕补配] 原作仅在 Kikoeru 端确认已有字幕，未命中可操作库存目录，自动跳过: "
                "source=%s source_rj=%s target_rj=%s",
                source_path,
                preview.get("source_rjcode"),
                preview.get("target_rjcode"),
            )
            return {
                "handled": True,
                "auto_skipped": True,
                "reason": self.EXISTING_SUBTITLE_REASON,
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
        if not bool(preview.get("target_route_confident", preview.get("kikoeru_route_confident", True))):
            return True
        if not bool(preview.get("target_has_work", preview.get("kikoeru_has_work"))) and str(preview.get("candidate_search_status") or "").strip().lower() != "pending_remote":
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
        force: bool = False,
    ) -> Dict[str, Any]:
        if not force and not self._should_retry_pending_candidate_search(preview):
            return self._refresh_preview_execution_state(dict(preview or {}))

        next_preview = dict(preview or {})
        target_rjcode = str(next_preview.get("target_rjcode") or "").strip()
        if not target_rjcode:
            return self._refresh_preview_execution_state(next_preview)

        if not bool(next_preview.get("target_route_confident", next_preview.get("kikoeru_route_confident", True))):
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
            "ready_candidate_count": len([item for item in candidates if bool(item.get("ready_for_import"))]),
            "candidate_search_status": candidate_search_status,
            "candidate_search_reason": candidate_search_reason,
        })
        return self._refresh_preview_execution_state(next_preview)

    def _serialize_pending_record(self, conflict: ConflictWork) -> Dict[str, Any]:
        analysis_info = dict(conflict.analysis_info or {})
        preview = dict(analysis_info.get("preview") or {})
        import_result_summary = dict(analysis_info.get("import_result_summary") or {})
        status = str(conflict.status or "").strip().upper()
        preview.setdefault("target_rjcode", self._extract_rjcode((conflict.new_metadata or {}).get("target_rjcode") or ""))
        preview.setdefault("source_rjcode", self._extract_rjcode((conflict.new_metadata or {}).get("source_rjcode") or ""))
        preview.setdefault("source_label", (conflict.new_metadata or {}).get("source_label") or "")
        preview.setdefault("subtitle_count", (conflict.new_metadata or {}).get("subtitle_count") or 0)
        preview["source_rjcode"] = self._extract_rjcode(preview.get("source_rjcode") or "")
        preview["target_rjcode"] = self._extract_rjcode(preview.get("target_rjcode") or "")
        preview = self._refresh_preview_execution_state(preview)
        if status == self.PENDING_EXECUTING_STATUS:
            preview["is_executing"] = True
            preview["reason"] = preview.get("reason") or "字幕补配导入正在执行，请等待当前任务完成"
            preview["execute_reason"] = preview.get("execute_reason") or preview["reason"]
        if import_result_summary:
            preview["import_result_summary"] = import_result_summary
            preview["linked_workbench_task_id"] = import_result_summary.get("task_id") or ""
            preview["awaiting_manual_match"] = bool(import_result_summary.get("awaiting_manual_match"))
        return {
            "id": conflict.id,
            "task_id": conflict.task_id,
            "status": conflict.status,
            "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
            "source_path": conflict.new_path,
            "source_mode": analysis_info.get("source_mode") or self.PENDING_SOURCE_MODE,
            "preview": preview,
            "can_execute": status == "PENDING" and self._can_execute_pending_import(preview),
        }

    def _build_imported_pending_execute_result(self, conflict: ConflictWork) -> Dict[str, Any]:
        item = self._serialize_pending_record(conflict)
        preview = dict(item.get("preview") or {})
        summary = dict(preview.get("import_result_summary") or {})
        task_id = str(summary.get("task_id") or preview.get("linked_workbench_task_id") or "").strip()
        target_candidate = dict(preview.get("selected_candidate") or {})
        task_payload = None
        if task_id:
            task_payload = {
                "id": task_id,
                "folder_path": str(target_candidate.get("folder_path") or ""),
                "library_id": str(target_candidate.get("library_id") or ""),
                "source_mode": str(item.get("source_mode") or self.PENDING_SOURCE_MODE),
            }
            try:
                task = get_task_engine().get_task(task_id)
                metadata = dict(getattr(task, "task_metadata", {}) or {}) if task else {}
                if metadata:
                    task_payload.update({
                        "folder_path": str(metadata.get("folder_path") or task_payload["folder_path"]),
                        "library_id": str(metadata.get("library_id") or task_payload["library_id"]),
                        "source_mode": str(metadata.get("source_mode") or task_payload["source_mode"]),
                    })
            except Exception:
                logger.debug("[字幕补配] 读取已导入工作台任务失败: task_id=%s", task_id, exc_info=True)

        written_count = max(0, int(summary.get("written_count") or 0))
        write_error_count = max(0, int(summary.get("write_error_count") or 0))
        return {
            "success": True,
            "already_imported": True,
            "pending_record": item,
            "preview": preview,
            "target_candidate": target_candidate,
            "import_result": {
                "success": True,
                "partial": False,
                "awaiting_manual_match": bool(summary.get("awaiting_manual_match")),
                "written_files": [{"subtitle_name": "", "output_name": ""} for _ in range(written_count)],
                "write_errors": [{} for _ in range(write_error_count)],
            },
            "task": task_payload,
        }

    def _reset_pending_execute_status_after_failure(
        self,
        record_id: str,
        *,
        fallback_analysis_info: Optional[Dict[str, Any]] = None,
        reason: str = "",
        execution_owner_id: Optional[str] = None,
    ) -> None:
        db = next(get_db())
        try:
            row = db.query(ConflictWork).filter(
                ConflictWork.id == record_id,
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status == self.PENDING_EXECUTING_STATUS,
            ).first()
            if not row:
                return
            analysis_info = dict(row.analysis_info or fallback_analysis_info or {})
            if execution_owner_id and str(analysis_info.get("execution_owner_id") or "") != execution_owner_id:
                logger.info(
                    "[字幕补配] 跳过已被新执行接管的旧执行锁回滚: record_id=%s",
                    record_id,
                )
                return
            preview = dict(analysis_info.get("preview") or {})
            reason_text = str(reason or "字幕补配导入失败，请重试").strip()
            if reason_text:
                preview["execute_reason"] = reason_text
                preview["reason"] = reason_text
            row.status = "PENDING"
            row.analysis_info = {
                **analysis_info,
                "preview": preview,
                "execution_status": "failed",
                "execution_failed_at": datetime.now().isoformat(),
                "execution_error": reason_text,
                "execution_owner_id": "",
                "execution_heartbeat_at": "",
                "execution_lease_until": "",
            }
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[字幕补配] 回滚执行中预检单状态失败: record_id=%s", record_id, exc_info=True)
        finally:
            db.close()

    @staticmethod
    def _parse_pending_execution_time(value: Any) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None

    def _pending_execution_lease_is_active(self, analysis_info: Optional[Dict[str, Any]]) -> bool:
        info = dict(analysis_info or {})
        now = datetime.now()
        lease_until = self._parse_pending_execution_time(info.get("execution_lease_until"))
        if lease_until is not None:
            return lease_until > now

        # 兼容上线前没有租约字段的旧执行：给刚启动的请求一个完整租约窗口，
        # 防止滚动升级期间把真实仍在跑的旧请求误接管；超过窗口即视为僵尸锁。
        started_at = self._parse_pending_execution_time(info.get("execution_started_at"))
        if started_at is None:
            return False
        lease_seconds = max(60, int(getattr(
            self, "PENDING_EXECUTION_LEASE_SECONDS", self.PENDING_EXECUTION_LEASE_SECONDS
        ) or self.PENDING_EXECUTION_LEASE_SECONDS))
        return started_at + timedelta(seconds=lease_seconds) > now

    def _new_pending_execution_owner_id(self) -> str:
        service_owner_id = getattr(self, "_pending_execution_owner_id", "")
        if not service_owner_id:
            service_owner_id = f"{os.getpid()}:{uuid.uuid4()}"
            self._pending_execution_owner_id = service_owner_id
        return f"{service_owner_id}:{uuid.uuid4()}"

    def _claim_pending_execution(self, analysis_info: Dict[str, Any], owner_id: str) -> Dict[str, Any]:
        now = datetime.now()
        lease_seconds = max(60, int(getattr(
            self, "PENDING_EXECUTION_LEASE_SECONDS", self.PENDING_EXECUTION_LEASE_SECONDS
        ) or self.PENDING_EXECUTION_LEASE_SECONDS))
        return {
            **dict(analysis_info or {}),
            "execution_status": "processing",
            "execution_owner_id": owner_id,
            "execution_started_at": now.isoformat(),
            "execution_heartbeat_at": now.isoformat(),
            "execution_lease_until": (now + timedelta(seconds=lease_seconds)).isoformat(),
        }

    def _recover_expired_pending_execution(
        self,
        analysis_info: Optional[Dict[str, Any]],
        *,
        reason: str = "上次字幕补配执行已中断，已自动释放执行锁",
    ) -> Dict[str, Any]:
        next_info = dict(analysis_info or {})
        preview = dict(next_info.get("preview") or {})
        preview["execute_reason"] = reason
        preview["reason"] = reason
        return {
            **next_info,
            "preview": preview,
            "execution_status": "failed",
            "execution_failed_at": datetime.now().isoformat(),
            "execution_error": reason,
            "execution_owner_id": "",
            "execution_heartbeat_at": "",
            "execution_lease_until": "",
        }

    def _renew_pending_execution_lease(self, record_id: str, owner_id: str) -> bool:
        db = next(get_db())
        try:
            row = db.query(ConflictWork).filter(
                ConflictWork.id == record_id,
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status == self.PENDING_EXECUTING_STATUS,
            ).first()
            if not row:
                return False
            analysis_info = dict(row.analysis_info or {})
            if str(analysis_info.get("execution_owner_id") or "") != owner_id:
                return False
            now = datetime.now()
            lease_seconds = max(60, int(getattr(
                self, "PENDING_EXECUTION_LEASE_SECONDS", self.PENDING_EXECUTION_LEASE_SECONDS
            ) or self.PENDING_EXECUTION_LEASE_SECONDS))
            row.analysis_info = {
                **analysis_info,
                "execution_heartbeat_at": now.isoformat(),
                "execution_lease_until": (now + timedelta(seconds=lease_seconds)).isoformat(),
            }
            db.commit()
            return True
        except Exception:
            db.rollback()
            logger.warning(
                "[字幕补配] 更新执行租约失败: record_id=%s",
                record_id,
                exc_info=True,
            )
            return True
        finally:
            db.close()

    async def _heartbeat_pending_execution(self, record_id: str, owner_id: str) -> None:
        interval = max(10, int(getattr(
            self, "PENDING_EXECUTION_HEARTBEAT_SECONDS", self.PENDING_EXECUTION_HEARTBEAT_SECONDS
        ) or self.PENDING_EXECUTION_HEARTBEAT_SECONDS))
        while True:
            await asyncio.sleep(interval)
            # 租约续期会打开同步 SQLAlchemy session；放到线程里避免长 IO 导入时
            # 把事件循环卡住，导致取消和实时状态无法及时处理。
            if not await asyncio.to_thread(
                self._renew_pending_execution_lease,
                record_id,
                owner_id,
            ):
                return

    def _is_imported_record_awaiting_manual_match(self, row: ConflictWork) -> bool:
        if str(row.status or "").upper() != "IMPORTED":
            return False
        analysis_info = dict(row.analysis_info or {})
        import_result_summary = dict(analysis_info.get("import_result_summary") or {})
        return bool(import_result_summary.get("awaiting_manual_match")) and not bool(import_result_summary.get("manual_match_completed"))

    def _should_refresh_pending_record(
        self,
        conflict: ConflictWork,
        preview: Dict[str, Any],
        *,
        refresh_candidates: bool,
        force_refresh_candidates: bool,
        refresh_min_interval_seconds: int,
        current_index_view_token: str,
    ) -> bool:
        if not refresh_candidates:
            return False
        if force_refresh_candidates:
            return bool(
                str(preview.get("target_rjcode") or "").strip()
                and bool(preview.get("is_linked_subtitle_source") or preview.get("is_translation_work"))
                and not str(preview.get("stage_reason") or "").strip()
            )
        if not self._should_retry_pending_candidate_search(preview):
            return False

        analysis_info = dict(conflict.analysis_info or {})
        previous_token = str(
            analysis_info.get("candidate_index_view_token") or ""
        ).strip()
        if previous_token != str(current_index_view_token or "").strip():
            return True

        next_refresh_at = str(
            analysis_info.get("candidate_next_refresh_at") or ""
        ).strip()
        if next_refresh_at:
            try:
                return datetime.now() >= datetime.fromisoformat(next_refresh_at)
            except ValueError:
                return True

        refreshed_at = str(analysis_info.get("candidate_refreshed_at") or "").strip()
        if not refreshed_at:
            return True
        try:
            refreshed_time = datetime.fromisoformat(refreshed_at)
        except ValueError:
            return True

        candidate_search_status = str(preview.get("candidate_search_status") or "").strip().lower()
        effective_interval = 300 if candidate_search_status == "not_found" else max(1, int(refresh_min_interval_seconds or 0))
        return (datetime.now() - refreshed_time).total_seconds() >= effective_interval

    @staticmethod
    def _candidate_refresh_metadata(
        preview: Dict[str, Any],
        *,
        index_view_token: str,
        refresh_min_interval_seconds: int,
    ) -> Dict[str, Any]:
        refreshed_at = datetime.now()
        status = str(preview.get("candidate_search_status") or "").strip().lower()
        interval = (
            300
            if status == "not_found"
            else max(1, int(refresh_min_interval_seconds or 0))
        )
        return {
            "candidate_refreshed_at": refreshed_at.isoformat(),
            "candidate_search_status": status or "unknown",
            "candidate_next_refresh_at": (
                refreshed_at + timedelta(seconds=interval)
            ).isoformat(),
            "candidate_index_view_token": str(index_view_token or ""),
        }

    def _current_candidate_index_view_token(self) -> str:
        manager = getattr(self, "library_manager", None)
        getter = getattr(manager, "inventory_index_view_token", None)
        if not callable(getter):
            return "index-unavailable"
        try:
            return str(getter() or "index-unavailable")
        except Exception:
            logger.debug("[字幕补配] 读取库存索引视图 token 失败", exc_info=True)
            return "index-unavailable"

    async def queue_pending_archive_import(self, task: Task, rjcode: str, hint_password: Optional[str] = None) -> Dict[str, Any]:
        hinted_rjcode = self._extract_rjcode(
            rjcode
            or getattr(task, "rjcode", "")
            or (task.task_metadata or {}).get("rjcode")
            or (task.task_metadata or {}).get("inferred_rjcode")
            or ""
        )
        task.update_progress(5, "预检中（查询翻译信息...）")
        try:
            preview = await self.preview_archive_import(
                task.source_path,
                source_rjcode_hint=hinted_rjcode,
                hint_password=hint_password,
                task=task,
                precheck_timeout=self.ARCHIVE_PRECHECK_TIMEOUT_SECONDS,
            )
        except LinkedSubtitleArchivePrecheckTimeout as exc:
            preview = dict(exc.preview or {})
            logger.warning(
                "[字幕补配预检] 压缩包预检超时，保留补配待处理单: source=%s source_rj=%s target_rj=%s reason=%s",
                task.source_path,
                preview.get("source_rjcode", ""),
                preview.get("target_rjcode", ""),
                preview.get("reason", "") or "字幕补配预检超时",
            )
        task.update_progress(5, "预检中（确认字幕候选...）")
        should_create_pending = self._should_create_pending_import(preview)
        if should_create_pending and str(preview.get("source_subtitle_probe_status") or "").strip().lower() != "timeout":
            source_path_exists = bool(task.source_path) and os.path.exists(task.source_path)
            probe_status = str(preview.get("source_subtitle_probe_status") or "").strip().lower()
            if int(preview.get("subtitle_count") or 0) <= 0 and self._can_stage_archive_subtitles_later(probe_status, source_path_exists):
                preview = self._refresh_preview_execution_state(dict(preview or {}))
            else:
                preview = await self._stage_archive_subtitles_for_preview(task.source_path, preview, hint_password=hint_password)
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
            # 预检未命中字幕补配路径，立即清理临时 stage 目录
            stage_dir = str(
                preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
            ).strip()
            if stage_dir:
                self._cleanup_stage_dir(stage_dir)
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
                "source_subtitle_probe_status": str(preview.get("source_subtitle_probe_status") or ""),
                "queue_origin": "auto_process",
            }
            analysis_info = {
                "preview": preview,
                "source_mode": self.PENDING_SOURCE_MODE,
                "queued_at": datetime.now().isoformat(),
                **self._candidate_refresh_metadata(
                    preview,
                    index_view_token=self._current_candidate_index_view_token(),
                    refresh_min_interval_seconds=self.PENDING_REFRESH_MIN_INTERVAL_SECONDS,
                ),
            }
            selected_candidate = preview.get("selected_candidate") or {}
            existing_path = selected_candidate.get("folder_path") or ""
            linked_works_info = self._build_target_linked_works_info(
                preview,
                selected_candidate,
            )
            related_rjcodes = [
                code for code in [
                    preview.get("source_rjcode"),
                    preview.get("target_rjcode"),
                ] if code
            ]

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
                pending.linked_works_info = linked_works_info
                pending.related_rjcodes = related_rjcodes
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
                    linked_works_info=linked_works_info,
                    analysis_info=analysis_info,
                    related_rjcodes=related_rjcodes,
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
            stage_dir = str(
                preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
            ).strip()
            if stage_dir:
                self._cleanup_stage_dir(stage_dir)
            db.rollback()
            raise
        finally:
            db.close()

    async def list_pending_imports(
        self,
        *,
        refresh_candidates: bool = True,
        force_refresh_candidates: bool = False,
        refresh_min_interval_seconds: int = PENDING_REFRESH_MIN_INTERVAL_SECONDS,
    ) -> List[Dict[str, Any]]:
        # ★ 性能重构：原来一个 db session 跨整个循环 + 多次 await（_repair_cached_preview_rj_fields
        # 和 _refresh_pending_preview_candidates 都是 HTTP IO），同时被字幕补配工作台
        # 高频调用（前端轮询），导致占用 connection pool。改为：
        # Phase A 短读 expunge → Phase B 无 session 跑 IO 算决策 → Phase C 短写落库。
        # Phase A: 短读
        db = next(get_db())
        try:
            rows = db.query(ConflictWork).filter(
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status.in_(["PENDING", self.PENDING_EXECUTING_STATUS, "IMPORTED"]),
            ).order_by(ConflictWork.created_at.desc()).all()
            for row in rows:
                db.expunge(row)
        finally:
            db.close()

        # Phase B: 无 session 跑 IO，算每行的决策
        current_index_view_token = self._current_candidate_index_view_token()
        items: List[Dict[str, Any]] = []
        decisions: List[Dict[str, Any]] = []
        for row in rows:
            try:
                status = str(row.status or "").upper()
                if self._is_imported_record_awaiting_manual_match(row):
                    items.append(self._serialize_pending_record(row))
                    continue
                if status == self.PENDING_EXECUTING_STATUS:
                    if not self._pending_execution_lease_is_active(row.analysis_info):
                        recovered_analysis_info = self._recover_expired_pending_execution(
                            row.analysis_info
                        )
                        row.status = "PENDING"
                        row.analysis_info = recovered_analysis_info
                        decisions.append({
                            "record_id": str(row.id),
                            "action": "recover_execution",
                            "next_analysis_info": recovered_analysis_info,
                        })
                    items.append(self._serialize_pending_record(row))
                    continue
                if status != "PENDING":
                    continue

                original_preview = dict((row.analysis_info or {}).get("preview") or {})
                preview = await self._repair_cached_preview_rj_fields(
                    original_preview,
                    source_path=str(row.new_path or ""),
                )
                did_candidate_query = self._should_refresh_pending_record(
                    row,
                    preview,
                    refresh_candidates=refresh_candidates,
                    force_refresh_candidates=force_refresh_candidates,
                    refresh_min_interval_seconds=refresh_min_interval_seconds,
                    current_index_view_token=current_index_view_token,
                )
                if did_candidate_query:
                    refreshed_preview = await self._refresh_pending_preview_candidates(
                        preview,
                        force=force_refresh_candidates,
                    )
                else:
                    refreshed_preview = self._refresh_preview_execution_state(dict(preview or {}))

                if not self._should_create_pending_import(refreshed_preview):
                    stage_dir = str(
                        refreshed_preview.get("source_subtitle_dir") or refreshed_preview.get("staged_subtitle_dir") or ""
                    ).strip()
                    if stage_dir:
                        self._cleanup_stage_dir(stage_dir)
                    if self._is_existing_subtitle_duplicate_preview(refreshed_preview):
                        decisions.append({
                            "record_id": str(row.id),
                            "action": "convert_existing_subtitle",
                            "source_path": str(row.new_path or ""),
                            "preview": refreshed_preview,
                            "task_id": str(row.task_id or "").strip() or None,
                            "queue_origin": str((row.new_metadata or {}).get("queue_origin") or "auto_process"),
                        })
                    else:
                        decisions.append({
                            "record_id": str(row.id),
                            "action": "delete",
                        })
                    continue

                # 保留为 pending：可能要更新 analysis_info（新 preview）
                next_analysis_info = None
                if refreshed_preview != original_preview or did_candidate_query:
                    next_analysis_info = {
                        **(row.analysis_info or {}),
                        "preview": refreshed_preview,
                        **(
                            self._candidate_refresh_metadata(
                                refreshed_preview,
                                index_view_token=current_index_view_token,
                                refresh_min_interval_seconds=refresh_min_interval_seconds,
                            )
                            if did_candidate_query
                            else {}
                        ),
                    }
                    decisions.append({
                        "record_id": str(row.id),
                        "action": "refresh_preview",
                        "next_analysis_info": next_analysis_info,
                        "linked_works_info": self._build_target_linked_works_info(
                            refreshed_preview,
                            refreshed_preview.get("selected_candidate") or {},
                        ),
                    })
                # 序列化用最新 preview（即使没落库也不影响这次返回值）
                serialize_row = row
                if next_analysis_info is not None:
                    # detached 实例直接改 analysis_info 字段不会影响 db，安全
                    serialize_row.analysis_info = next_analysis_info
                items.append(self._serialize_pending_record(serialize_row))
            except Exception as exc:
                logger.exception(
                    "[字幕补配] 构建待处理预检单失败，已跳过: record_id=%s task_id=%s source=%s",
                    getattr(row, "id", ""),
                    getattr(row, "task_id", ""),
                    getattr(row, "new_path", ""),
                )
                fallback_preview = self._refresh_preview_execution_state(
                    dict((row.analysis_info or {}).get("preview") or {})
                )
                fallback_preview["execute_reason"] = str(
                    fallback_preview.get("execute_reason")
                    or f"预检单刷新失败：{str(exc)}"
                )
                fallback_preview["reason"] = str(
                    fallback_preview.get("reason")
                    or fallback_preview.get("execute_reason")
                    or ""
                )
                items.append({
                    "id": row.id,
                    "task_id": row.task_id,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "source_path": row.new_path,
                    "source_mode": (row.analysis_info or {}).get("source_mode") or self.PENDING_SOURCE_MODE,
                    "preview": fallback_preview,
                    "can_execute": False,
                })

        # Phase C: 短写 —— 应用决策
        if decisions:
            write_db = next(get_db())
            try:
                for decision in decisions:
                    record_id = decision["record_id"]
                    fresh = write_db.query(ConflictWork).filter(
                        ConflictWork.id == record_id,
                    ).first()
                    if not fresh:
                        continue  # 期间已被并发清理
                    action = decision["action"]
                    if action == "refresh_preview":
                        fresh.analysis_info = decision["next_analysis_info"]
                        fresh.linked_works_info = decision["linked_works_info"]
                    elif action == "recover_execution":
                        if str(fresh.status or "").upper() == self.PENDING_EXECUTING_STATUS:
                            fresh.status = "PENDING"
                            fresh.analysis_info = decision["next_analysis_info"]
                    elif action == "convert_existing_subtitle":
                        upserted = self._upsert_existing_subtitle_conflict(
                            write_db,
                            source_path=decision["source_path"],
                            preview=decision["preview"],
                            task_id=decision["task_id"],
                            queue_origin=decision["queue_origin"],
                        )
                        if upserted is None:
                            write_db.delete(fresh)
                            continue
                        # upsert 内部按 path+PENDING 查询，正常情况下命中 fresh 本体
                        if upserted is not fresh and getattr(upserted, "id", None) != getattr(fresh, "id", None):
                            write_db.delete(fresh)
                    elif action == "delete":
                        write_db.delete(fresh)
                write_db.commit()
            finally:
                write_db.close()

        return items

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
            raise ValueError("没有可清除的字幕补配记录")

        def _safe_cleanup_workbench_root(path_value: Optional[str]) -> bool:
            target = str(path_value or "").strip()
            if not target or not os.path.isdir(target):
                return False
            target_path = Path(target).resolve()
            expected_parts = [part.lower() for part in self.WORKBENCH_RELATIVE_DIR.split("/") if part]
            parts = [part.lower() for part in target_path.parts]
            is_workbench_path = any(
                parts[index:index + len(expected_parts)] == expected_parts
                for index in range(0, max(0, len(parts) - len(expected_parts) + 1))
            )
            if not is_workbench_path:
                logger.warning("[字幕补配] 跳过非工作台目录清理: %s", target)
                return False
            shutil.rmtree(target_path, ignore_errors=True)
            self._cleanup_empty_workbench_shell(str(target_path))
            return True

        db = next(get_db())
        try:
            query = db.query(ConflictWork).filter(
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
                ConflictWork.status.in_(["PENDING", "IMPORTED"]),
            )
            if not clear_all:
                query = query.filter(ConflictWork.id.in_(normalized_ids))

            rows = query.all()
            if not rows:
                raise ValueError("未找到可清除的字幕补配记录")

            cleared_ids: List[str] = []
            cleared_stage_dirs = 0
            cleared_workbench_tasks = 0
            cleared_workbench_dirs = 0
            engine = get_task_engine()
            for row in rows:
                analysis_info = dict(row.analysis_info or {})
                preview = dict(analysis_info.get("preview") or {})
                import_result_summary = dict(analysis_info.get("import_result_summary") or {})
                stage_dir = str(
                    preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir") or ""
                ).strip()
                if stage_dir:
                    self._cleanup_stage_dir(stage_dir)
                    cleared_stage_dirs += 1

                workbench_task_id = str(
                    import_result_summary.get("task_id")
                    or preview.get("linked_workbench_task_id")
                    or ""
                ).strip()
                if workbench_task_id:
                    task = engine.get_task(workbench_task_id)
                    if task is not None:
                        metadata = dict(task.task_metadata or {})
                        if _safe_cleanup_workbench_root(metadata.get("linked_workbench_root_dir")):
                            cleared_workbench_dirs += 1
                        try:
                            if await asyncio.to_thread(engine.remove_task, workbench_task_id):
                                cleared_workbench_tasks += 1
                        except RuntimeError:
                            logger.warning("[字幕补配] 工作台任务仍在执行，跳过任务清理: task_id=%s", workbench_task_id)
                    else:
                        try:
                            from ..models.database import Task as TaskRecord

                            task_record = db.query(TaskRecord).filter(TaskRecord.id == workbench_task_id).first()
                            task_metadata = dict(task_record.task_metadata or {}) if task_record else {}
                            if _safe_cleanup_workbench_root(task_metadata.get("linked_workbench_root_dir")):
                                cleared_workbench_dirs += 1
                        except Exception:
                            logger.warning("[字幕补配] 读取工作台任务快照失败: task_id=%s", workbench_task_id, exc_info=True)
                        await asyncio.to_thread(engine.delete_task_snapshot, workbench_task_id)
                        cleared_workbench_tasks += 1

                cleared_ids.append(str(row.id))
                db.delete(row)

            db.commit()
            return {
                "success": True,
                "cleared_count": len(cleared_ids),
                "cleared_ids": cleared_ids,
                "cleared_stage_dirs": cleared_stage_dirs,
                "cleared_workbench_tasks": cleared_workbench_tasks,
                "cleared_workbench_dirs": cleared_workbench_dirs,
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

    async def _archive_source_after_execute_async(
        self,
        *,
        source_path: str,
        task_id: str,
    ) -> None:
        """以 plain 字段将字幕补配源包持久化加入延后归档队列。

        这里不再 fire-and-forget 实际文件搬运：只做一次短事务入队，HTTP 响应仍能
        立即返回工作台任务，同时进程重启不会丢失待归档源文件。
        """
        try:
            if not source_path or not os.path.exists(source_path):
                return
            engine = get_task_engine()
            task = engine.get_task(task_id) if task_id else None
            if task is None:
                task = Task(
                    task_type=TaskType.AUTO_PROCESS,
                    source_path=source_path,
                    auto_classify=False,
                )
            await engine._archive_source_file(task)
        except Exception:
            logger.warning(
                "[字幕补配] 后台源文件归档失败 source=%s task_id=%s",
                source_path, task_id, exc_info=True,
            )

    async def execute_pending_import(
        self,
        record_id: str,
        *,
        target_library_id: Optional[str] = None,
        target_folder_path: Optional[str] = None,
        use_filter_rules: bool = False,
        subtitle_filter_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        # ★ 性能重构：原来一个 db session 跨整个 execute_archive_import（解压 + 复制
        # 数 GB 文件，可能跑分钟级），把 connection pool 槽位长期占住，导致其他
        # 请求拿不到连接。改为：短读拿快照 → 无 session 跑长 IO → 短写落库。
        # Phase A: 短读
        execution_owner_id = self._new_pending_execution_owner_id()
        db = next(get_db())
        try:
            record = db.query(ConflictWork).filter(
                ConflictWork.id == record_id,
                ConflictWork.conflict_type == self.PENDING_CONFLICT_TYPE,
            ).with_for_update().first()
            if not record:
                raise ValueError("字幕补配预检单不存在")
            current_status = str(record.status or "").strip().upper()
            if current_status == "IMPORTED":
                return self._build_imported_pending_execute_result(record)
            if current_status == self.PENDING_EXECUTING_STATUS:
                if self._pending_execution_lease_is_active(record.analysis_info):
                    raise LinkedSubtitleImportAlreadyRunning("这条字幕补配预检单正在导入，请等待当前任务完成")
                logger.warning(
                    "[字幕补配] 接管过期执行锁: record_id=%s previous_owner=%s",
                    record_id,
                    (record.analysis_info or {}).get("execution_owner_id") or "legacy",
                )
                record.analysis_info = self._recover_expired_pending_execution(record.analysis_info)
                record.status = "PENDING"
                current_status = "PENDING"
            if current_status != "PENDING":
                raise ValueError("字幕补配预检单当前状态不可执行")
            cached_analysis_info = dict(record.analysis_info or {})
            record_new_path = str(record.new_path or "")
            record.analysis_info = self._claim_pending_execution(cached_analysis_info, execution_owner_id)
            record.status = self.PENDING_EXECUTING_STATUS
            db.commit()
        finally:
            db.close()

        # Phase B: 无 session 跑长 IO（候选刷新 + 解压导入）
        heartbeat_task = asyncio.create_task(
            self._heartbeat_pending_execution(record_id, execution_owner_id),
            name=f"linked-subtitle-heartbeat:{record_id}",
        )
        try:
            record_preview = await self._refresh_pending_preview_candidates(
                await self._repair_cached_preview_rj_fields(
                    dict(cached_analysis_info.get("preview") or {}),
                    source_path=record_new_path,
                )
            )
            next_analysis_info_after_refresh = {
                **cached_analysis_info,
                "preview": record_preview,
                "candidate_refreshed_at": datetime.now().isoformat(),
                "execution_status": "processing",
            }
            result = await self.execute_archive_import(
                record_new_path,
                target_library_id=target_library_id,
                target_folder_path=target_folder_path,
                prepared_preview=record_preview,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
                import_reason="正常解压检测后的关联字幕补配导入",
                source_mode="linked_translation_archive_import",
            )
        except asyncio.CancelledError:
            self._reset_pending_execute_status_after_failure(
                record_id,
                fallback_analysis_info=cached_analysis_info,
                reason="字幕补配导入已取消，请重试",
                execution_owner_id=execution_owner_id,
            )
            raise
        except Exception as exc:
            self._reset_pending_execute_status_after_failure(
                record_id,
                fallback_analysis_info=cached_analysis_info,
                reason=str(exc),
                execution_owner_id=execution_owner_id,
            )
            raise
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        # Phase C: 短写 —— 重新打开 session，重新 fetch record 落库
        write_db = next(get_db())
        archive_source_path = ""
        archive_task_id = ""
        try:
            fresh_record = write_db.query(ConflictWork).filter(
                ConflictWork.id == record_id,
            ).first()
            if not fresh_record:
                # 极端情况：执行期间 record 被并发删除。导入结果还是返回，但不再落库
                return result
            fresh_analysis_info = dict(fresh_record.analysis_info or {})
            if str(fresh_analysis_info.get("execution_owner_id") or "") != execution_owner_id:
                raise LinkedSubtitleImportAlreadyRunning("字幕补配执行锁已被新的请求接管，本次结果不再写入")

            if not result.get("success"):
                fresh_record.status = "PENDING"
                fresh_record.analysis_info = {
                    **next_analysis_info_after_refresh,
                    "execution_status": "failed",
                    "execution_failed_at": datetime.now().isoformat(),
                    "execution_error": str((result.get("import_result") or {}).get("error") or "字幕补配导入失败"),
                    "execution_owner_id": "",
                    "execution_heartbeat_at": "",
                    "execution_lease_until": "",
                }
                write_db.commit()
                return result

            self._cleanup_stage_dir(
                record_preview.get("source_subtitle_dir") or record_preview.get("staged_subtitle_dir")
            )
            final_preview = dict(result.get("preview") or {})
            final_preview.pop("source_subtitle_dir", None)
            final_preview.pop("staged_subtitle_dir", None)
            fresh_record.status = "IMPORTED"
            fresh_record.analysis_info = {
                **next_analysis_info_after_refresh,
                "preview": final_preview,
                "executed_at": datetime.now().isoformat(),
                "execution_status": "completed",
                "execution_owner_id": "",
                "execution_heartbeat_at": "",
                "execution_lease_until": "",
                "import_result_summary": {
                    "written_count": len((result.get("import_result") or {}).get("written_files") or []),
                    "write_error_count": len((result.get("import_result") or {}).get("write_errors") or []),
                    "awaiting_manual_match": bool((result.get("import_result") or {}).get("awaiting_manual_match")),
                    "task_id": (result.get("task") or {}).get("id"),
                },
            }
            write_db.commit()

            archive_source_path = str(fresh_record.new_path or "").strip()
            archive_task_id = str(fresh_record.task_id or "")
        except Exception as exc:
            write_db.rollback()
            self._reset_pending_execute_status_after_failure(
                record_id,
                fallback_analysis_info=next_analysis_info_after_refresh,
                reason=str(exc),
                execution_owner_id=execution_owner_id,
            )
            raise
        finally:
            write_db.close()

        # 只持久化入队，不在 HTTP 请求内复制 GB 级源包。这样工作台任务能立即
        # 返回，且关机/重启后仍可继续归档。
        engine = get_task_engine()
        if archive_task_id:
            original_task = engine.get_task(archive_task_id)
            if original_task:
                original_task.output_path = (result.get("target_candidate") or {}).get("folder_path", "")
                original_task.status = TaskStatus.COMPLETED
                original_task.progress = 100
                original_task.completed_at = datetime.now()
                if bool((result.get("import_result") or {}).get("awaiting_manual_match")):
                    original_task.current_step = "已转入字幕补配并完成原始字幕导入"
                else:
                    original_task.current_step = "目标目录为空，已按新作品直接导入字幕"

        try:
            await self._archive_source_after_execute_async(
                source_path=archive_source_path,
                task_id=archive_task_id,
            )
        except Exception:
            logger.warning(
                "[字幕补配] 源文件延后归档入队失败（不影响主流程） source=%s",
                archive_source_path, exc_info=True,
            )

        return result


_linked_subtitle_import_service: Optional[LinkedSubtitleImportService] = None


def get_linked_subtitle_import_service() -> LinkedSubtitleImportService:
    global _linked_subtitle_import_service
    if _linked_subtitle_import_service is None:
        _linked_subtitle_import_service = LinkedSubtitleImportService()
    return _linked_subtitle_import_service


def invalidate_target_folder_summary_cache_for_library(library_id: str) -> int:
    """使库存目录摘要缓存失效，但不为普通库存写操作额外构造重型服务实例。"""
    normalized_library_id = str(library_id or "").strip()
    if not normalized_library_id:
        return 0

    service = _linked_subtitle_import_service
    if service is not None:
        return service.invalidate_target_folder_summary_cache(normalized_library_id)

    try:
        from .redis_service import get_redis_service

        redis_service = get_redis_service()
        if not redis_service.is_enabled():
            return 0
        client = redis_service.client(required=False)
        if client is not None:
            client.incr(redis_service.key("rj-subtitle", "folder-summary-version", normalized_library_id))
    except Exception:
        logger.debug(
            "[字幕补配·缓存] 推进未实例化服务的目录摘要版本失败 library=%s",
            normalized_library_id,
            exc_info=True,
        )
    return 0
