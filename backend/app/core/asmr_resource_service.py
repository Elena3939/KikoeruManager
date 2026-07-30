import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_config
from ..models.database import ASMRDownloadSession, ASMRResourceRecord, ASMRWork, SessionLocal
from .fs_utils import move_path_efficient
from .resource_budget_service import get_resource_budget_service
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


class ASMRResourceService:
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
    SUBTITLE_EXTENSIONS = {".lrc", ".vtt", ".srt", ".ass", ".ssa"}
    COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    TEXT_EXTENSIONS = {".txt", ".md", ".json", ".cue"}
    RETRY_ACTIVE_SESSION_STATUSES = {"queued", "downloading", "verifying", "uploading"}
    AUDIO_TYPE = "audio"
    SUBTITLE_TYPE = "subtitle"
    COVER_TYPE = "cover"
    OTHER_TYPE = "other"

    LANGUAGE_MARKERS = {
        "zh": ["中文", "汉化", "汉化版", "中字", "字幕", "简中", "繁中", "chs", "cht", "chi", "zh"],
        "ja": ["日文", "日语", "日本語", "jpn", "japanese", "jp", "ja"],
        "en": ["英文", "英语", "english", "eng", "en"],
    }

    def __init__(self, asmr_service=None):
        if asmr_service is None:
            from .asmr_download_service import get_asmr_download_service

            asmr_service = get_asmr_download_service()
        self.asmr_service = asmr_service
        self._global_upload_lock = asyncio.Lock()
        self._retry_locks: Dict[str, asyncio.Lock] = {}
        self._synology_clients: Dict[str, Any] = {}
        self._remote_source_cache: TTLCache = TTLCache(max_size=512, ttl_seconds=1800, name="asmr.remote_source")
        self._remote_source_inflight: Dict[str, asyncio.Future] = {}

    def _get_retry_lock(
        self,
        session_id: str,
        relative_paths: Optional[List[str]] = None,
    ) -> asyncio.Lock:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("会话 ID 不能为空")
        normalized_paths = sorted({
            str(path or "").strip()
            for path in (relative_paths or [])
            if str(path or "").strip()
        })
        scope = "|".join(normalized_paths) if normalized_paths else "*"
        lock_key = f"{normalized_session_id}:{scope}"
        lock = self._retry_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._retry_locks[lock_key] = lock
        return lock

    @staticmethod
    def _find_active_session_download_task(
        engine,
        session_id: str,
        retry_paths: Optional[set[str]] = None,
    ):
        active_statuses = {"pending", "processing", "paused", "waiting_retry", "waiting_manual"}
        normalized_retry_paths = {
            str(path or "").strip()
            for path in (retry_paths or set())
            if str(path or "").strip()
        }
        matching = []
        for task in engine.get_tasks_by_session(session_id):
            task_type = str(getattr(getattr(task, "type", ""), "value", getattr(task, "type", ""))).strip()
            task_status = str(getattr(getattr(task, "status", ""), "value", getattr(task, "status", ""))).strip().lower()
            if task_type != "asmr_sync_download" or task_status not in active_statuses:
                continue
            if normalized_retry_paths:
                task_paths = {
                    str(item.get("relative_path") or item.get("file_name") or "").strip()
                    for item in ((getattr(task, "task_metadata", None) or {}).get("selected_resources") or [])
                    if str(item.get("relative_path") or item.get("file_name") or "").strip()
                }
                if not task_paths.intersection(normalized_retry_paths):
                    continue
            matching.append(task)
        if not matching:
            return None
        return max(matching, key=lambda item: getattr(item, "created_at", datetime.min))

    @staticmethod
    def _build_active_retry_session(session: Dict[str, Any], task) -> Dict[str, Any]:
        active_session = dict(session)
        active_session["task_id"] = task.id
        active_session["status"] = str(getattr(getattr(task, "status", ""), "value", getattr(task, "status", "")))
        active_session["retry_reused_active_task"] = True
        return active_session

    def _build_synology_config_signature(self, synology_config: Any) -> str:
        if synology_config is None:
            return ""
        if is_dataclass(synology_config):
            payload = asdict(synology_config)
        elif hasattr(synology_config, "model_dump"):
            payload = synology_config.model_dump()
        elif hasattr(synology_config, "__dict__"):
            payload = dict(vars(synology_config))
        else:
            payload = {"value": str(synology_config)}
        return hashlib.sha1(repr(sorted(payload.items())).encode("utf-8")).hexdigest()

    def _get_synology_client(self, library_id: str, synology_config: Any):
        from .library_manager import SynologyFileStationClient

        cache_key = str(library_id or "").strip() or str(getattr(synology_config, "base_url", "") or "").strip()
        config_signature = self._build_synology_config_signature(synology_config)
        cached = self._synology_clients.get(cache_key)
        client = cached.get("client") if isinstance(cached, dict) else cached
        cached_signature = cached.get("signature") if isinstance(cached, dict) else ""
        if client is None or cached_signature != config_signature:
            client = SynologyFileStationClient(synology_config)
            self._synology_clients[cache_key] = {
                "client": client,
                "signature": config_signature,
            }
        return client

    def normalize_rjcode(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", text, re.IGNORECASE)
        return match.group(0).upper() if match else text

    def normalize_name(self, value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"\.(mp3|wav|flac|m4a|ogg|aac|wma|lrc|vtt|srt|ass|ssa|jpg|jpeg|png|webp|gif|bmp)$", "", text)
        text = re.sub(r"^(track|trk|tr)[\s._-]*", "", text)
        text = re.sub(r"[\s._-]+", "", text)
        text = re.sub(r"[『』「」\[\]【】（）()<>《》]", "", text)
        text = re.sub(r"[^\w\u4e00-\u9fff\u3040-\u30ff]+", "", text)
        return text

    def detect_language(self, *values: Any) -> str:
        combined = " ".join(str(value or "").lower() for value in values)
        for code, markers in self.LANGUAGE_MARKERS.items():
            if any(marker in combined for marker in markers):
                return code
        return ""

    def classify_resource_type(self, name: str, relative_path: str = "") -> str:
        ext = os.path.splitext(str(name or ""))[1].lower()
        if ext in self.AUDIO_EXTENSIONS:
            return self.AUDIO_TYPE
        if ext in self.SUBTITLE_EXTENSIONS:
            return self.SUBTITLE_TYPE
        if ext in self.COVER_EXTENSIONS:
            return self.COVER_TYPE
        if ext in self.TEXT_EXTENSIONS:
            lowered_path = str(relative_path or name or "").lower()
            if "cover" in lowered_path or "package" in lowered_path or "ジャケット" in lowered_path:
                return self.COVER_TYPE
        return self.OTHER_TYPE

    def _append_task_log(self, task, message: str, level: str = "info") -> None:
        if not message:
            return
        logs = list(task.task_metadata.get("progress_log") or [])
        logs.append({
            "time": datetime.now().isoformat(),
            "level": level,
            "message": str(message),
        })
        task.task_metadata["progress_log"] = logs[-80:]

    def _update_download_runtime(
        self,
        task,
        download_progress_state: Dict[str, Dict[str, Any]],
        *,
        file_key: str,
        file_name: str,
        relative_path: str,
        downloaded_bytes: int,
        total_bytes: int,
        index: int,
        total_files: int,
        stage: str,
    ) -> None:
        now = datetime.now()
        runtime = dict(task.task_metadata.get("download_runtime") or {})
        started_at = str(runtime.get("started_at") or "").strip() or now.isoformat()
        previous = dict(download_progress_state.get(file_key) or {})
        normalized_total = max(0, int(total_bytes or previous.get("total") or 0))
        normalized_downloaded = max(0, int(downloaded_bytes or 0))
        if normalized_total > 0:
            normalized_downloaded = min(normalized_downloaded, normalized_total)
        failed_stage = str(stage or "").endswith("_failed")
        file_started_at = str(previous.get("started_at") or "").strip() or now.isoformat()
        previous_updated_at = str(previous.get("updated_at") or "").strip()
        previous_downloaded = int(previous.get("downloaded") or 0)
        previous_speed = int(previous.get("speed_bytes_per_sec") or 0)
        try:
            previous_updated = datetime.fromisoformat(previous_updated_at) if previous_updated_at else None
        except Exception:
            previous_updated = None
        try:
            file_elapsed = max(0.001, (now - datetime.fromisoformat(file_started_at)).total_seconds())
        except Exception:
            file_elapsed = 0.001
            file_started_at = now.isoformat()

        if previous_updated is not None:
            speed_window = max(0.001, (now - previous_updated).total_seconds())
            speed_delta = max(0, normalized_downloaded - previous_downloaded)
            if speed_delta > 0 and speed_window >= 0.35:
                instant_speed = int(speed_delta / speed_window)
            else:
                instant_speed = 0
        else:
            instant_speed = 0
        average_speed = int(normalized_downloaded / file_elapsed) if normalized_downloaded > 0 else 0
        if instant_speed > 0 and average_speed > 0:
            file_speed = int((instant_speed * 0.75) + (average_speed * 0.25))
        else:
            file_speed = instant_speed or average_speed or previous_speed
        if previous_speed > 0 and file_speed > 0:
            file_speed = int((previous_speed * 0.45) + (file_speed * 0.55))
        file_remaining = max(0, normalized_total - normalized_downloaded)
        file_eta = int(file_remaining / file_speed) if file_speed > 0 and file_remaining > 0 else 0
        file_progress = int(normalized_downloaded / normalized_total * 100) if normalized_total else 0
        if failed_stage:
            file_progress = min(file_progress, 99)

        download_progress_state[file_key] = {
            **previous,
            "name": file_name,
            "downloaded": normalized_downloaded,
            "total": normalized_total,
            "progress": file_progress,
            "index": index,
            "relative_path": relative_path,
            "stage": stage,
            "started_at": file_started_at,
            "updated_at": now.isoformat(),
            "speed_bytes_per_sec": file_speed,
            "eta_seconds": file_eta,
        }
        ordered_files = sorted(download_progress_state.values(), key=lambda item: item.get("index") or 0)
        task.task_metadata["download_files"] = ordered_files

        transferred_bytes = sum(
            min(
                max(0, int(item.get("downloaded") or 0)),
                max(0, int(item.get("total") or 0)),
            )
            for item in ordered_files
        )
        known_total_bytes = max(0, int(runtime.get("expected_total_bytes") or runtime.get("total_bytes") or 0))
        aggregate_total = max(
            known_total_bytes,
            sum(max(0, int(item.get("total") or 0)) for item in ordered_files),
        )
        completed_stages = {"downloaded", "download_reused", "ready_for_upload"}
        completed_files = sum(
            1
            for item in ordered_files
            if str(item.get("stage") or "") in completed_stages
            and int(item.get("progress") or 0) >= 100
        )
        has_failed_file = any(str(item.get("stage") or "").endswith("_failed") for item in ordered_files)
        active_items = [
            item for item in ordered_files
            if 0 < int(item.get("downloaded") or 0) < max(1, int(item.get("total") or 0))
        ]
        aggregate_speed = 0
        remaining_bytes = max(0, aggregate_total - transferred_bytes)
        # 总速度必须按整个任务的字节增量采样。逐文件平均速度会把已启动但未实际并发传输的文件全部相加，
        # 在增强下载中会明显高于真实网络吞吐（例如 30 个文件的平均速度被累加）。
        previous_aggregate_at = str(runtime.get("speed_sample_at") or "").strip()
        previous_aggregate_bytes = int(runtime.get("speed_sample_transferred_bytes") or transferred_bytes)
        try:
            aggregate_sample_at = datetime.fromisoformat(previous_aggregate_at) if previous_aggregate_at else None
        except Exception:
            aggregate_sample_at = None
        aggregate_sample_speed = 0
        if aggregate_sample_at is not None:
            sample_elapsed = max(0.001, (now - aggregate_sample_at).total_seconds())
            sample_delta = max(0, transferred_bytes - previous_aggregate_bytes)
            if sample_elapsed >= 0.35 and sample_delta > 0:
                aggregate_sample_speed = int(sample_delta / sample_elapsed)
        if aggregate_sample_speed > 0:
            previous_aggregate_speed = int(runtime.get("speed_bytes_per_sec") or 0)
            aggregate_speed = (
                int(previous_aggregate_speed * 0.35 + aggregate_sample_speed * 0.65)
                if previous_aggregate_speed > 0
                else aggregate_sample_speed
            )
        elif aggregate_sample_at is not None:
            try:
                sample_age = (now - aggregate_sample_at).total_seconds()
            except Exception:
                sample_age = 0
            if sample_age >= 1.5:
                aggregate_speed = 0
            else:
                aggregate_speed = int(runtime.get("speed_bytes_per_sec") or 0)
        aggregate_eta = int(remaining_bytes / aggregate_speed) if aggregate_speed > 0 and remaining_bytes > 0 else 0

        aggregate_progress = int(transferred_bytes / aggregate_total * 100) if aggregate_total else 0
        if has_failed_file:
            aggregate_progress = min(aggregate_progress, 99)
        task.task_metadata["download_runtime"] = {
            **runtime,
            "started_at": started_at,
            "updated_at": now.isoformat(),
            "stage": stage,
            "current_file_name": file_name,
            "current_relative_path": relative_path,
            "current_file_index": index,
            "total_files": total_files,
            "completed_files": completed_files,
            "active_file_count": len(active_items),
            "transferred_bytes": transferred_bytes,
            "total_bytes": aggregate_total,
            "expected_total_bytes": known_total_bytes,
            "progress": aggregate_progress,
            "speed_bytes_per_sec": aggregate_speed,
            "eta_seconds": aggregate_eta,
            "speed_sample_at": now.isoformat(),
            "speed_sample_transferred_bytes": transferred_bytes,
        }

    def _finalize_download_runtime(self, task, status: str = "completed") -> None:
        runtime = dict(task.task_metadata.get("download_runtime") or {})
        if not runtime:
            return
        now = datetime.now()
        runtime["updated_at"] = now.isoformat()
        runtime["status"] = status
        runtime["active_file_count"] = 0
        runtime["speed_bytes_per_sec"] = 0
        runtime["eta_seconds"] = 0
        if status in {"completed", "failed"}:
            runtime["ended_at"] = now.isoformat()
        if status == "completed":
            if int(runtime.get("total_bytes") or 0) > 0:
                runtime["progress"] = 100
        task.task_metadata["download_runtime"] = runtime

    def _update_upload_runtime(
        self,
        task,
        upload_progress_state: Dict[str, Dict[str, Any]],
        *,
        file_key: str,
        file_name: str,
        relative_path: str,
        uploaded_bytes: int,
        total_bytes: int,
        index: int,
        total_files: int,
        stage: str,
        target_path: str = "",
    ) -> None:
        now = datetime.now()
        runtime = dict(task.task_metadata.get("upload_runtime") or {})
        started_at = str(runtime.get("started_at") or "").strip() or now.isoformat()
        previous = dict(upload_progress_state.get(file_key) or {})
        file_started_at = str(previous.get("started_at") or "").strip() or now.isoformat()
        previous_updated_at = str(previous.get("updated_at") or "").strip()
        previous_uploaded = int(previous.get("uploaded") or 0)
        previous_speed = int(previous.get("speed_bytes_per_sec") or 0)
        try:
            aggregate_elapsed = max(0.001, (now - datetime.fromisoformat(started_at)).total_seconds())
        except Exception:
            aggregate_elapsed = 0.001
            started_at = now.isoformat()
        try:
            file_elapsed = max(0.001, (now - datetime.fromisoformat(file_started_at)).total_seconds())
        except Exception:
            file_elapsed = 0.001
            file_started_at = now.isoformat()
        try:
            previous_updated = datetime.fromisoformat(previous_updated_at) if previous_updated_at else None
        except Exception:
            previous_updated = None
        if previous_updated is not None:
            speed_window = max(0.001, (now - previous_updated).total_seconds())
            speed_delta = max(0, int(uploaded_bytes or 0) - previous_uploaded)
            instant_speed = int(speed_delta / speed_window) if speed_delta > 0 and speed_window >= 0.35 else 0
        else:
            instant_speed = 0
        average_speed = int(uploaded_bytes / file_elapsed) if uploaded_bytes > 0 else 0
        if instant_speed > 0 and average_speed > 0:
            file_speed = int((instant_speed * 0.75) + (average_speed * 0.25))
        else:
            file_speed = instant_speed or average_speed or previous_speed
        if previous_speed > 0 and file_speed > 0:
            file_speed = int((previous_speed * 0.45) + (file_speed * 0.55))
        file_remaining = max(0, int(total_bytes or 0) - int(uploaded_bytes or 0))
        file_eta = int(file_remaining / file_speed) if file_speed > 0 and file_remaining > 0 else 0

        upload_progress_state[file_key] = {
            **previous,
            "name": file_name,
            "uploaded": int(uploaded_bytes or 0),
            "total": int(total_bytes or 0),
            "progress": int(uploaded_bytes / total_bytes * 100) if total_bytes else 0,
            "index": index,
            "relative_path": relative_path,
            "stage": stage,
            "target_path": target_path,
            "started_at": file_started_at,
            "updated_at": now.isoformat(),
            "speed_bytes_per_sec": file_speed,
            "eta_seconds": file_eta,
        }
        ordered_files = sorted(upload_progress_state.values(), key=lambda item: item.get("index") or 0)
        task.task_metadata["upload_files"] = ordered_files

        transferred_bytes = sum(max(0, int(item.get("uploaded") or 0)) for item in ordered_files)
        aggregate_total = sum(max(0, int(item.get("total") or 0)) for item in ordered_files)
        completed_files = sum(1 for item in ordered_files if int(item.get("progress") or 0) >= 100)
        active_items = [
            item for item in ordered_files
            if 0 < int(item.get("uploaded") or 0) < max(1, int(item.get("total") or 0))
        ]
        aggregate_speed = sum(max(0, int(item.get("speed_bytes_per_sec") or 0)) for item in active_items)
        if aggregate_speed <= 0 and transferred_bytes > 0:
            aggregate_speed = int(transferred_bytes / aggregate_elapsed)
        remaining_bytes = max(0, aggregate_total - transferred_bytes)
        aggregate_eta = int(remaining_bytes / aggregate_speed) if aggregate_speed > 0 and remaining_bytes > 0 else 0

        task.task_metadata["upload_runtime"] = {
            **runtime,
            "started_at": started_at,
            "updated_at": now.isoformat(),
            "stage": stage,
            "current_file_name": file_name,
            "current_relative_path": relative_path,
            "current_file_index": index,
            "total_files": total_files,
            "completed_files": completed_files,
            "active_file_count": len(active_items),
            "transferred_bytes": transferred_bytes,
            "total_bytes": aggregate_total,
            "progress": int(transferred_bytes / aggregate_total * 100) if aggregate_total else 0,
            "speed_bytes_per_sec": aggregate_speed,
            "eta_seconds": aggregate_eta,
            "is_waiting_turn": False,
            "target_path": target_path or str(runtime.get("target_path") or ""),
        }

    def _finalize_upload_runtime(self, task, status: str = "completed") -> None:
        runtime = dict(task.task_metadata.get("upload_runtime") or {})
        if not runtime:
            return
        now = datetime.now()
        runtime["updated_at"] = now.isoformat()
        runtime["status"] = status
        runtime["active_file_count"] = 0
        runtime["speed_bytes_per_sec"] = 0
        runtime["eta_seconds"] = 0
        runtime["is_waiting_turn"] = False
        if status in {"completed", "failed"}:
            runtime["ended_at"] = now.isoformat()
        if status == "completed":
            if int(runtime.get("total_bytes") or 0) > 0:
                runtime["progress"] = 100
        task.task_metadata["upload_runtime"] = runtime

    def _set_runtime_paused(self, task) -> None:
        for key in ("download_runtime", "upload_runtime"):
            runtime = dict(task.task_metadata.get(key) or {})
            if not runtime:
                continue
            runtime["updated_at"] = datetime.now().isoformat()
            runtime["status"] = "paused"
            runtime["active_file_count"] = 0
            runtime["speed_bytes_per_sec"] = 0
            runtime["eta_seconds"] = 0
            runtime["is_waiting_turn"] = False
            task.task_metadata[key] = runtime

    def _mark_upload_waiting(
        self,
        task,
        *,
        file_name: str,
        relative_path: str,
        index: int,
        total_files: int,
    ) -> None:
        runtime = dict(task.task_metadata.get("upload_runtime") or {})
        now = datetime.now().isoformat()
        task.task_metadata["upload_runtime"] = {
            **runtime,
            "updated_at": now,
            "stage": "waiting_upload_turn",
            "current_file_name": file_name,
            "current_relative_path": relative_path,
            "current_file_index": index,
            "total_files": total_files,
            "active_file_count": 0,
            "speed_bytes_per_sec": 0,
            "eta_seconds": 0,
            "is_waiting_turn": True,
        }

    def _extract_track_number(self, value: Any) -> Optional[int]:
        text = str(value or "")
        match = re.search(r"(?:^|[^\d])0*(\d{1,3})(?:[^\d]|$)", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def _read_audio_duration(self, file_path: str) -> Optional[float]:
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(file_path)
            if audio and getattr(audio, "info", None) and getattr(audio.info, "length", None):
                return round(float(audio.info.length), 3)
        except Exception:
            return None
        return None

    def _match_tolerances(self) -> tuple[float, float]:
        config = get_config().asmr_sync
        return (
            float(getattr(config, "match_duration_tolerance_seconds", 3.0) or 3.0),
            float(getattr(config, "match_size_tolerance_ratio", 0.08) or 0.08),
        )

    def _build_local_resource(self, root_folder: str, file_path: str) -> Dict[str, Any]:
        relative_path = os.path.relpath(file_path, root_folder).replace("\\", "/")
        name = os.path.basename(file_path)
        file_type = self.classify_resource_type(name, relative_path)
        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        duration_seconds = self._read_audio_duration(file_path) if file_type == self.AUDIO_TYPE else None
        return {
            "id": uuid.uuid4().hex,
            "source": "local",
            "resource_type": file_type,
            "language": self.detect_language(name, relative_path),
            "file_name": name,
            "relative_path": relative_path,
            "normalized_name": self.normalize_name(name),
            "track_number": self._extract_track_number(name),
            "size_bytes": int(size_bytes or 0),
            "duration_seconds": duration_seconds,
            "local_path": file_path,
            "remote_url": "",
            "checksum_md5": "",
            "selected": False,
        }

    def scan_local_resources(self, folder_path: str) -> List[Dict[str, Any]]:
        if not folder_path or not os.path.isdir(folder_path):
            return []
        resources: List[Dict[str, Any]] = []
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [name for name in dirs if name.lower() not in {"subtitles", "__pycache__"}]
            for file_name in files:
                file_path = os.path.join(root, file_name)
                resources.append(self._build_local_resource(folder_path, file_path))
        resources.sort(key=lambda item: (item["resource_type"], item["relative_path"]))
        return resources

    def _build_remote_resource(self, rjcode: str, work_info: Dict[str, Any], file_info: Dict[str, Any]) -> Dict[str, Any]:
        relative_path = str(file_info.get("path") or file_info.get("title") or "").replace("\\", "/").strip("/")
        file_name = os.path.basename(relative_path or str(file_info.get("title") or ""))
        checksum_md5 = str(file_info.get("hash") or "").strip()
        if checksum_md5 and not re.fullmatch(r"[a-fA-F0-9]{32}", checksum_md5):
            checksum_md5 = ""
        return {
            "id": uuid.uuid4().hex,
            "source": "asmr.one",
            "source_workno": self.normalize_rjcode(rjcode),
            "resource_type": self.classify_resource_type(file_name, relative_path),
            "language": self.detect_language(file_name, relative_path, work_info.get("title")),
            "file_name": file_name,
            "relative_path": relative_path or file_name,
            "normalized_name": self.normalize_name(file_name),
            "track_number": self._extract_track_number(relative_path or file_name),
            "size_bytes": int(file_info.get("size") or 0),
            "duration_seconds": None,
            "local_path": "",
            "remote_url": str(file_info.get("media_download_url") or file_info.get("download_url") or ""),
            "checksum_md5": checksum_md5,
            "title": str(work_info.get("title") or ""),
            "selected": False,
        }

    async def _fetch_remote_source_payload(self, normalized_rjcode: str) -> Tuple[Dict[str, Any], List[Any]]:
        work_info = await self.asmr_service.fetch_work_info(normalized_rjcode)
        if not work_info:
            raise ValueError(f"未找到作品 {normalized_rjcode}")
        tracks = await self.asmr_service.fetch_track_list(normalized_rjcode)
        return dict(work_info or {}), list(tracks or [])

    async def _get_remote_source_payload(self, normalized_rjcode: str, *, refresh: bool = False) -> Tuple[Dict[str, Any], List[Any]]:
        cache_key = self.normalize_rjcode(normalized_rjcode)
        if not refresh:
            cached = self._remote_source_cache.get(cache_key)
            if cached is not None:
                work_info, tracks = cached
                return deepcopy(work_info), deepcopy(tracks)

        future = self._remote_source_inflight.get(cache_key)
        if future is not None and not future.done():
            work_info, tracks = await future
            return deepcopy(work_info), deepcopy(tracks)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._remote_source_inflight[cache_key] = future
        started_at = time.monotonic()
        try:
            payload = await self._fetch_remote_source_payload(cache_key)
            self._remote_source_cache[cache_key] = deepcopy(payload)
            future.set_result(deepcopy(payload))
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            if elapsed_ms >= 1000:
                logger.info("[ASMR增强] 远程资源源数据拉取耗时: rj=%s elapsed=%sms", cache_key, elapsed_ms)
            work_info, tracks = payload
            return deepcopy(work_info), deepcopy(tracks)
        except Exception as exc:
            future.set_exception(exc)
            future.add_done_callback(lambda item: item.exception())
            raise
        finally:
            self._remote_source_inflight.pop(cache_key, None)

    def invalidate_remote_source_cache(self, rjcode: str = "") -> None:
        normalized = self.normalize_rjcode(rjcode)
        if normalized:
            self._remote_source_cache.pop(normalized, None)
        else:
            self._remote_source_cache.clear()

    async def fetch_remote_resources(self, rjcode: str, *, refresh: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        normalized_rjcode = self.normalize_rjcode(rjcode)
        work_info, tracks = await self._get_remote_source_payload(normalized_rjcode, refresh=refresh)
        flat_files = self.asmr_service._flatten_tracks(tracks or [])
        resources = [
            self._build_remote_resource(normalized_rjcode, work_info, file_info)
            for file_info in flat_files
            if (file_info.get("media_download_url") or file_info.get("download_url"))
        ]
        resources.sort(key=lambda item: (item["resource_type"], item["relative_path"]))
        return work_info, resources

    def _match_score(self, local_item: Dict[str, Any], remote_item: Dict[str, Any]) -> Tuple[int, List[str]]:
        if local_item.get("resource_type") != remote_item.get("resource_type"):
            return 0, []

        duration_tolerance, size_tolerance = self._match_tolerances()
        score = 0
        basis: List[str] = []

        local_name = str(local_item.get("normalized_name") or "")
        remote_name = str(remote_item.get("normalized_name") or "")
        if local_name and local_name == remote_name:
            score += 70
            basis.append("normalized_name")

        local_track = local_item.get("track_number")
        remote_track = remote_item.get("track_number")
        if local_track is not None and local_track == remote_track:
            score += 20
            basis.append("track_number")

        local_size = int(local_item.get("size_bytes") or 0)
        remote_size = int(remote_item.get("size_bytes") or 0)
        if local_size > 0 and remote_size > 0:
            delta = abs(local_size - remote_size)
            ratio = delta / max(remote_size, 1)
            if delta == 0:
                score += 20
                basis.append("size_exact")
            elif ratio <= min(size_tolerance / 2, 0.02):
                score += 14
                basis.append("size_close")
            elif ratio <= size_tolerance:
                score += 8
                basis.append("size_tolerant")

        local_duration = local_item.get("duration_seconds")
        remote_duration = remote_item.get("duration_seconds")
        if (
            local_item.get("resource_type") == self.AUDIO_TYPE
            and local_duration is not None
            and remote_duration is not None
            and abs(float(local_duration) - float(remote_duration)) <= duration_tolerance
        ):
            score += 15
            basis.append("duration_tolerant")

        if local_item.get("language") and local_item.get("language") == remote_item.get("language"):
            score += 5
            basis.append("language")
        return score, basis

    def _match_remote_with_local(
        self,
        local_resources: List[Dict[str, Any]],
        remote_resources: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        available_local = list(local_resources)
        matched: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        pairing_conflicts: List[Dict[str, Any]] = []

        for remote_item in remote_resources:
            best_local = None
            best_score = 0
            best_basis: List[str] = []
            candidates = []
            for local_item in available_local:
                score, basis = self._match_score(local_item, remote_item)
                if score <= 0:
                    continue
                candidates.append(
                    {
                        "local_path": local_item.get("relative_path"),
                        "local_name": local_item.get("file_name"),
                        "score": score,
                        "match_basis": basis,
                    }
                )
                if score > best_score:
                    best_local = local_item
                    best_score = score
                    best_basis = basis

            if best_local and best_score >= 70:
                available_local.remove(best_local)
                matched.append(
                    {
                        "remote": remote_item,
                        "local": best_local,
                        "score": best_score,
                        "match_basis": best_basis,
                    }
                )
                if len([item for item in candidates if item["score"] == best_score]) > 1:
                    pairing_conflicts.append(
                        {
                            "relative_path": remote_item.get("relative_path"),
                            "file_name": remote_item.get("file_name"),
                            "score": best_score,
                            "candidates": candidates,
                        }
                    )
            else:
                missing.append(
                    {
                        **remote_item,
                        "missing_reason": "local_not_found",
                        "match_score": best_score,
                        "match_basis": best_basis,
                    }
                )
        return matched, missing, available_local, pairing_conflicts

    def _detect_local_pair_issues(self, local_resources: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        audios = [item for item in local_resources if item.get("resource_type") == self.AUDIO_TYPE]
        subtitles = [item for item in local_resources if item.get("resource_type") == self.SUBTITLE_TYPE]
        subtitle_by_name = defaultdict(list)
        subtitle_by_track = defaultdict(list)
        for subtitle in subtitles:
            subtitle_by_name[subtitle.get("normalized_name")].append(subtitle)
            if subtitle.get("track_number") is not None:
                subtitle_by_track[subtitle.get("track_number")].append(subtitle)

        missing_subtitles: List[Dict[str, Any]] = []
        for audio in audios:
            matches = list(subtitle_by_name.get(audio.get("normalized_name"), []))
            if not matches and audio.get("track_number") is not None:
                matches = list(subtitle_by_track.get(audio.get("track_number"), []))
            if matches:
                continue
            missing_subtitles.append(
                {
                    "audio_name": audio.get("file_name"),
                    "audio_path": audio.get("relative_path"),
                    "duration_seconds": audio.get("duration_seconds"),
                    "size_bytes": audio.get("size_bytes"),
                    "comparison_basis": ["file_name", "track_number", "duration_seconds", "size_bytes"],
                }
            )

        audio_by_name = defaultdict(list)
        audio_by_track = defaultdict(list)
        for audio in audios:
            audio_by_name[audio.get("normalized_name")].append(audio)
            if audio.get("track_number") is not None:
                audio_by_track[audio.get("track_number")].append(audio)

        orphan_subtitles: List[Dict[str, Any]] = []
        for subtitle in subtitles:
            matches = list(audio_by_name.get(subtitle.get("normalized_name"), []))
            if not matches and subtitle.get("track_number") is not None:
                matches = list(audio_by_track.get(subtitle.get("track_number"), []))
            if matches:
                continue
            orphan_subtitles.append(
                {
                    "subtitle_name": subtitle.get("file_name"),
                    "subtitle_path": subtitle.get("relative_path"),
                    "size_bytes": subtitle.get("size_bytes"),
                    "comparison_basis": ["file_name", "track_number", "size_bytes"],
                }
            )

        return {
            "missing_subtitles_for_audio": missing_subtitles,
            "orphan_subtitles_without_audio": orphan_subtitles,
        }

    def _apply_filters(self, resources: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not filters:
            return list(resources)
        allowed_types = {str(item).strip().lower() for item in (filters.get("resource_types") or []) if str(item).strip()}
        allowed_audio_formats = {f".{str(item).strip().lower().lstrip('.')}" for item in (filters.get("audio_formats") or []) if str(item).strip()}
        allowed_subtitle_languages = {str(item).strip().lower() for item in (filters.get("subtitle_languages") or []) if str(item).strip()}
        include_existing = bool(filters.get("include_existing"))

        filtered: List[Dict[str, Any]] = []
        for item in resources:
            resource_type = str(item.get("resource_type") or "").lower()
            ext = os.path.splitext(str(item.get("file_name") or ""))[1].lower()
            language = str(item.get("language") or "").lower()
            if allowed_types and resource_type not in allowed_types:
                continue
            if resource_type == self.AUDIO_TYPE and allowed_audio_formats and ext not in allowed_audio_formats:
                continue
            if resource_type == self.SUBTITLE_TYPE and allowed_subtitle_languages and language not in allowed_subtitle_languages:
                continue
            if not include_existing and item.get("exists_locally"):
                continue
            filtered.append(item)
        return filtered

    def _select_default_resources(self, resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected = []
        for item in resources:
            next_item = dict(item)
            next_item["selected"] = bool(not item.get("exists_locally"))
            selected.append(next_item)
        return selected

    def _group_resources(self, resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in resources:
            ext = os.path.splitext(str(item.get("file_name") or ""))[1].lower().lstrip(".") or "other"
            key = f"{item.get('resource_type')}:{item.get('language') or 'unknown'}:{ext}"
            bucket = grouped.setdefault(
                key,
                {
                    "group_key": key,
                    "resource_type": item.get("resource_type"),
                    "language": item.get("language") or "",
                    "extension": ext,
                    "count": 0,
                    "selected_count": 0,
                    "items": [],
                },
            )
            bucket["count"] += 1
            if item.get("selected"):
                bucket["selected_count"] += 1
            bucket["items"].append(item)
        return list(grouped.values())

    def _build_selection_presets(self, resources: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        presets = {
            "missing_audio": [],
            "missing_subtitle": [],
            "covers": [],
        }
        for item in resources:
            relative_path = str(item.get("relative_path") or "")
            if item.get("resource_type") == self.AUDIO_TYPE and not item.get("exists_locally"):
                presets["missing_audio"].append(relative_path)
            elif item.get("resource_type") == self.SUBTITLE_TYPE and not item.get("exists_locally"):
                presets["missing_subtitle"].append(relative_path)
            elif item.get("resource_type") == self.COVER_TYPE:
                presets["covers"].append(relative_path)
        return presets

    def _sanitize_relative_path(self, relative_path: str) -> str:
        parts = []
        for part in Path(relative_path).parts:
            if part in {"", ".", ".."}:
                continue
            safe_part = re.sub(r'[<>:"|?*]', "_", part).strip()
            if safe_part:
                parts.append(safe_part)
        if not parts:
            return "resource.bin"
        return os.path.join(*parts)

    def _compute_md5(self, file_path: str) -> str:
        hasher = hashlib.md5()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _upsert_work_record(self, rjcode: str, work_info: Dict[str, Any], status: str = "cataloged", error: str = "") -> None:
        normalized_rjcode = self.normalize_rjcode(rjcode)
        db = SessionLocal()
        try:
            record = db.query(ASMRWork).filter(ASMRWork.rjcode == normalized_rjcode).first()
            if record is None:
                record = ASMRWork(rjcode=normalized_rjcode)
                db.add(record)
            record.title = str(work_info.get("title") or "")
            record.circle = str(work_info.get("circle") or "")
            record.source_provider = "asmr.one"
            record.tags = work_info.get("tags") or []
            record.work_status = status
            record.last_error = error or None
            record.last_scraped_at = datetime.now()
            record.updated_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[ASMR增强] 写入作品表失败", exc_info=True)
        finally:
            db.close()

    def _upsert_resource_records(
        self,
        rjcode: str,
        work_info: Dict[str, Any],
        resources: List[Dict[str, Any]],
        *,
        session_id: str = "",
    ) -> None:
        normalized_rjcode = self.normalize_rjcode(rjcode)
        db = SessionLocal()
        try:
            for item in resources:
                key_relative_path = str(item.get("relative_path") or item.get("file_name") or "").strip()
                record = (
                    db.query(ASMRResourceRecord)
                    .filter(
                        ASMRResourceRecord.rjcode == normalized_rjcode,
                        ASMRResourceRecord.source_provider == str(item.get("source") or "asmr.one"),
                        ASMRResourceRecord.relative_path == key_relative_path,
                    )
                    .first()
                )
                if record is None:
                    record = ASMRResourceRecord(
                        id=str(uuid.uuid4()),
                        rjcode=normalized_rjcode,
                        work_rjcode=normalized_rjcode,
                        source_provider=str(item.get("source") or "asmr.one"),
                        relative_path=key_relative_path,
                    )
                    db.add(record)
                record.work_rjcode = normalized_rjcode
                record.source_workno = str(item.get("source_workno") or normalized_rjcode)
                record.work_title = str(work_info.get("title") or item.get("title") or "")
                record.resource_type = str(item.get("resource_type") or self.OTHER_TYPE)
                record.language = str(item.get("language") or "")
                record.file_name = str(item.get("file_name") or "")
                record.normalized_name = str(item.get("normalized_name") or "")
                record.file_ext = os.path.splitext(str(item.get("file_name") or ""))[1].lower()
                record.size_bytes = int(item.get("size_bytes") or 0)
                record.duration_seconds = item.get("duration_seconds")
                record.remote_url = str(item.get("remote_url") or "")
                record.checksum_md5 = str(item.get("checksum_md5") or "")
                record.local_path = str(item.get("local_path") or "")
                record.upload_path = str(item.get("upload_path") or "")
                record.download_status = str(item.get("download_status") or "cataloged")
                record.match_status = str(item.get("match_status") or record.match_status or "unmatched")
                record.verify_status = str(item.get("verify_status") or record.verify_status or "pending")
                record.upload_status = str(item.get("upload_status") or record.upload_status or "pending")
                record.missing_reason = str(item.get("missing_reason") or "") or None
                record.session_id = str(item.get("session_id") or session_id or "") or record.session_id
                record.retry_count = int(item.get("retry_count") or record.retry_count or 0)
                record.last_seen_at = datetime.now()
                record.last_error = str(item.get("last_error") or "") or None
                record.extra_metadata = {
                    "track_number": item.get("track_number"),
                    "selected": bool(item.get("selected")),
                    "exists_locally": bool(item.get("exists_locally")),
                    "match_score": item.get("match_score"),
                    "match_basis": item.get("match_basis") or [],
                }
                record.updated_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[ASMR增强] 写入资源库失败", exc_info=True)
        finally:
            db.close()

    def _create_download_session(
        self,
        *,
        rjcode: str,
        work_title: str,
        folder_path: str,
        target_path: str,
        upload_mode: str,
        selected_filters: Dict[str, Any],
        selected_resources: List[Dict[str, Any]],
        source_page: str = "asmr-sync",
        source_action: str = "enhanced_download",
        source_label: str = "",
        queue_priority: int = 100,
        status: str = "planning",
    ) -> str:
        session_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            record = ASMRDownloadSession(
                id=session_id,
                rjcode=self.normalize_rjcode(rjcode),
                source_page=source_page,
                source_action=source_action,
                source_label=source_label or work_title or self.normalize_rjcode(rjcode),
                status=status,
                queue_priority=max(1, int(queue_priority or 100)),
                folder_path=folder_path,
                target_path=target_path,
                upload_mode=upload_mode,
                selected_filters=selected_filters or {},
                selected_resources=selected_resources or [],
                statistics={"selected_resource_count": len(selected_resources or [])},
                local_download_ready=False,
                local_download_root="",
                local_downloaded_count=0,
            )
            db.add(record)
            db.commit()
            return session_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _update_session(
        self,
        session_id: str,
        *,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        queue_priority: Optional[int] = None,
        target_path: Optional[str] = None,
        upload_mode: Optional[str] = None,
        statistics: Optional[Dict[str, Any]] = None,
        failure_summary: Optional[Dict[str, Any]] = None,
        selected_resources: Optional[List[Dict[str, Any]]] = None,
        local_download_ready: Optional[bool] = None,
        local_download_root: Optional[str] = None,
        local_downloaded_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            record = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id == session_id).first()
            if record is None:
                raise ValueError("会话不存在")
            if task_id is not None:
                record.task_id = task_id
            if status:
                record.status = status
                if status in self.RETRY_ACTIVE_SESSION_STATUSES:
                    record.completed_at = None
                if status in {"downloading", "verifying", "uploading"} and not record.started_at:
                    record.started_at = datetime.now()
                if status in {"completed", "partial_failed", "failed"}:
                    record.completed_at = datetime.now()
            if queue_priority is not None:
                record.queue_priority = max(1, int(queue_priority))
            if target_path is not None:
                record.target_path = target_path
            if upload_mode is not None:
                record.upload_mode = upload_mode
            if statistics is not None:
                current_stats = dict(record.statistics or {})
                current_stats.update(statistics)
                record.statistics = current_stats
            if failure_summary is not None:
                record.failure_summary = failure_summary
            if selected_resources is not None:
                record.selected_resources = selected_resources
            if local_download_ready is not None:
                record.local_download_ready = bool(local_download_ready)
            if local_download_root is not None:
                record.local_download_root = str(local_download_root or "").strip() or None
            if local_downloaded_count is not None:
                record.local_downloaded_count = max(0, int(local_downloaded_count or 0))
            record.updated_at = datetime.now()
            db.commit()
            return record.to_dict()
        finally:
            db.close()

    def _claim_session_retry(
        self,
        session_id: str,
        task_id: str,
    ) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
        db = SessionLocal()
        try:
            record = (
                db.query(ASMRDownloadSession)
                .filter(ASMRDownloadSession.id == session_id)
                .with_for_update()
                .first()
            )
            if record is None:
                raise ValueError("会话不存在")

            current_status = str(record.status or "").strip().lower()
            current_task_id = str(record.task_id or "").strip()
            if current_task_id and current_status in self.RETRY_ACTIVE_SESSION_STATUSES:
                active_session = record.to_dict()
                active_session["retry_reused_active_task"] = True
                db.commit()
                return False, active_session, {}

            previous = {
                "task_id": record.task_id,
                "status": record.status,
                "completed_at": record.completed_at,
            }
            record.task_id = task_id
            record.status = "queued"
            record.completed_at = None
            record.updated_at = datetime.now()
            db.commit()
            return True, record.to_dict(), previous
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _rollback_session_retry_claim(
        self,
        session_id: str,
        task_id: str,
        previous: Dict[str, Any],
    ) -> None:
        db = SessionLocal()
        try:
            record = (
                db.query(ASMRDownloadSession)
                .filter(ASMRDownloadSession.id == session_id)
                .with_for_update()
                .first()
            )
            if record is None or str(record.task_id or "") != str(task_id or ""):
                db.rollback()
                return
            record.task_id = previous.get("task_id")
            record.status = str(previous.get("status") or "partial_failed")
            record.completed_at = previous.get("completed_at")
            record.updated_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning(
                "[ASMR增强] 回滚重试任务认领失败 session=%s task=%s",
                session_id,
                task_id,
                exc_info=True,
            )
        finally:
            db.close()

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            record = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id == session_id).first()
            if record is None:
                raise ValueError("会话不存在")
            session = record.to_dict()
            statistics = dict(session.get("statistics") or {})
            local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
            # 只读取 DB 中的明确标志，不用文件计数升级 ready 状态
            local_ready = bool(session.get("local_download_ready"))
            local_count = int(session.get("local_downloaded_count") or 0)
            if local_root and os.path.isdir(local_root):
                if local_count <= 0:
                    local_count = sum(
                        1
                        for item in (session.get("selected_resources") or [])
                        if os.path.exists(os.path.join(local_root, self._sanitize_relative_path(str(item.get("relative_path") or item.get("file_name") or ""))))
                    )
                # 不再用 local_count > 0 升级 local_ready，避免半程下载被误判为可入库
            else:
                local_ready = False
                local_count = 0
                local_root = ""
            if (
                bool(record.local_download_ready) != bool(local_ready)
                or int(record.local_downloaded_count or 0) != int(local_count)
                or str(record.local_download_root or "").strip() != str(local_root or "").strip()
            ):
                record.local_download_ready = bool(local_ready)
                record.local_downloaded_count = int(local_count)
                record.local_download_root = str(local_root or "").strip() or None
                record.updated_at = datetime.now()
                db.commit()
            session["local_download_ready"] = local_ready
            session["local_download_root"] = local_root
            session["local_downloaded_count"] = local_count
            return session
        finally:
            db.close()

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            rows = (
                db.query(ASMRDownloadSession)
                .order_by(ASMRDownloadSession.queue_priority.asc(), ASMRDownloadSession.updated_at.desc())
                .limit(max(1, int(limit)))
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            db.close()

    def get_session_detail(self, session_id: str) -> Dict[str, Any]:
        session = self._get_session(session_id)
        db = SessionLocal()
        try:
            resources = (
                db.query(ASMRResourceRecord)
                .filter(
                    (ASMRResourceRecord.session_id == session_id)
                    | (ASMRResourceRecord.rjcode == session["rjcode"])
                )
                .order_by(ASMRResourceRecord.updated_at.desc())
                .limit(300)
                .all()
            )
            session["resources"] = [row.to_dict() for row in resources]
            return session
        finally:
            db.close()

    async def update_session_priority(self, session_id: str, queue_priority: int) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event
        from .task_engine import get_task_engine

        session = self._update_session(session_id, queue_priority=queue_priority)
        engine = get_task_engine()
        for task in engine.get_tasks_by_session(session_id):
            engine.update_task_priority(task.id, queue_priority)
        log_asmr_sync_event(
            "queue_reordered",
            summary=f"{session.get('rjcode') or session_id} 队列优先级已调整为 {queue_priority}",
            session_id=session_id,
            rjcode=session.get("rjcode"),
            detail={"queue_priority": queue_priority},
        )
        return session

    async def control_session(self, session_id: str, action: str) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event
        from .task_engine import get_task_engine

        engine = get_task_engine()
        session = self._get_session(session_id)
        tasks = engine.get_tasks_by_session(session_id)
        if not tasks and session.get("task_id"):
            task = engine.get_task(str(session["task_id"]))
            tasks = [task] if task else []
        if not tasks:
            raise ValueError("会话没有可操作任务")
        for task in tasks:
            if not task:
                continue
            if action == "pause":
                engine.pause_task(task.id)
                self._set_runtime_paused(task)
                task.current_step = "已暂停"
            elif action == "resume":
                engine.resume_task(task.id)
                task.current_step = "恢复中"
            elif action == "cancel":
                engine.cancel_task(task.id)
            else:
                raise ValueError("不支持的会话操作")
        if action == "cancel":
            next_status = "failed"
            event_type = "task_cancelled"
            label = "已取消"
        elif action == "pause":
            next_status = "paused"
            event_type = "task_paused"
            label = "已暂停"
        else:
            next_status = "downloading"
            event_type = "task_resumed"
            label = "已恢复"
        updated = self._update_session(session_id, status=next_status)
        log_asmr_sync_event(
            event_type,
            summary=f"{updated.get('rjcode') or session_id} {label}",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
        )
        return updated

    async def cancel_session_with_cleanup(self, session_id: str) -> Dict[str, Any]:
        """取消会话并清理已下载的临时文件。"""
        session = await self.control_session(session_id, "cancel")
        cleaned = False
        download_root = ""
        latest_metadata = self._get_latest_session_task_metadata(
            session_id,
            str(session.get("task_id") or "").strip(),
        )
        source_action = str(latest_metadata.get("source_action") or session.get("source_action") or "").strip()
        if source_action in {"reimport_local_download_root", "reimport_downloaded_session"}:
            logger.info("取消本地重导入会话，跳过用户下载目录清理: session_id=%s source_action=%s", session_id, source_action)
            return {**session, "cleaned": False, "cleaned_path": ""}
        statistics = dict(session.get("statistics") or {})
        download_root = str(
            session.get("local_download_root")
            or statistics.get("download_root")
            or ""
        ).strip()
        if not download_root:
            download_root = str(latest_metadata.get("download_root") or "").strip()
        if download_root:
            await self._wait_session_tasks_released(session_id)
            cleaned = await self._cleanup_download_root(download_root)
        return {**session, "cleaned": cleaned, "cleaned_path": download_root if cleaned else ""}

    async def _wait_session_tasks_released(self, session_id: str, timeout_seconds: float = 5.0) -> None:
        from .task_engine import get_task_engine

        engine = get_task_engine()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            task_ids = {
                str(task.id)
                for task in engine.get_tasks_by_session(session_id)
                if task is not None
            }
            if not task_ids or not any(task_id in engine.processing for task_id in task_ids):
                return
            await asyncio.sleep(0.15)

    async def _cleanup_download_root(self, download_root: str) -> bool:
        normalized_root = str(download_root or "").strip()
        if not normalized_root:
            return False
        for attempt in range(8):
            if not os.path.exists(normalized_root):
                return True
            try:
                await asyncio.to_thread(shutil.rmtree, normalized_root)
                logger.info("已清理会话下载目录: %s", normalized_root)
                return True
            except Exception:
                if attempt >= 7:
                    break
                await asyncio.sleep(0.25)
        def _best_effort_cleanup(root: str) -> bool:
            removed_any = False
            if os.path.isdir(root):
                for path in Path(root).rglob("*"):
                    if path.is_file() and (path.name.endswith(".downloading") or path.stat().st_size > 0):
                        try:
                            path.unlink()
                            removed_any = True
                        except Exception:
                            logger.debug("删除下载残留文件失败: %s", path, exc_info=True)
                shutil.rmtree(root, ignore_errors=True)
                if not os.path.exists(root):
                    return True
            return removed_any and not os.path.exists(root)

        try:
            cleaned = await asyncio.to_thread(_best_effort_cleanup, normalized_root)
            if cleaned:
                logger.info("已清理会话下载目录: %s", normalized_root)
                return True
            return False
        except Exception:
            logger.warning("清理会话下载目录失败: %s", normalized_root, exc_info=True)
            return False

    def _get_latest_session_task_metadata(self, session_id: str, fallback_task_id: str = "") -> Dict[str, Any]:
        from .task_engine import get_task_engine

        engine = get_task_engine()
        tasks = [task for task in engine.get_tasks_by_session(session_id) if task]
        if not tasks and fallback_task_id:
            fallback_task = engine.get_task(str(fallback_task_id))
            if fallback_task:
                tasks = [fallback_task]
        if not tasks:
            return {}

        def task_sort_value(task: Any) -> float:
            for attr in ("completed_at", "started_at", "created_at"):
                value = getattr(task, attr, None)
                if isinstance(value, datetime):
                    return value.timestamp()
            return 0.0

        latest_task = max(tasks, key=task_sort_value)
        return dict(latest_task.task_metadata or {})

    def _build_retry_task_options(self, session: Dict[str, Any]) -> Dict[str, Any]:
        statistics = dict(session.get("statistics") or {})
        latest_task_metadata = self._get_latest_session_task_metadata(
            str(session.get("id") or "").strip(),
            str(session.get("task_id") or "").strip(),
        )
        upload_source = dict(latest_task_metadata.get("upload_options") or {})
        postprocess_source = dict(latest_task_metadata.get("postprocess_options") or {})
        circle_name = str(
            postprocess_source.get("circle_name")
            or latest_task_metadata.get("circle_name")
            or statistics.get("circle_name")
            or session.get("source_label")
            or session.get("rjcode")
            or ""
        ).strip()
        target_library_id = str(
            postprocess_source.get("target_library_id")
            or statistics.get("target_library_id")
            or statistics.get("postprocess_target_library_id")
            or statistics.get("upload_library_id")
            or upload_source.get("library_id")
            or ""
        ).strip()
        target_subdir = str(
            postprocess_source.get("target_subdir")
            or statistics.get("target_subdir")
            or statistics.get("postprocess_target_subdir")
            or ""
        ).strip().strip("/\\")
        naming_mode = str(
            postprocess_source.get("naming_mode")
            or statistics.get("naming_mode")
            or statistics.get("postprocess_naming_mode")
            or "api"
        ).strip().lower() or "api"
        classify_mode = str(
            postprocess_source.get("classify_mode")
            or statistics.get("classify_mode")
            or statistics.get("postprocess_classify_mode")
            or "circle"
        ).strip().lower() or "circle"
        upload_options = {
            "enabled": bool(upload_source.get("enabled", str(session.get("upload_mode") or "disabled") != "disabled")),
            "mode": str(upload_source.get("mode") or session.get("upload_mode") or "disabled"),
            "target_path": str(upload_source.get("target_path") or session.get("target_path") or ""),
            "library_id": str(upload_source.get("library_id") or statistics.get("upload_library_id") or "").strip(),
        }
        postprocess_options = {
            "enabled": bool(postprocess_source.get("enabled")) or bool(target_library_id),
            "target_library_id": target_library_id,
            "target_subdir": target_subdir,
            "naming_mode": naming_mode,
            "classify_mode": classify_mode,
            "circle_name": circle_name,
            "skip_metadata_fetch": bool(postprocess_source.get("skip_metadata_fetch")),
        }
        return {
            "latest_task_metadata": latest_task_metadata,
            "upload_options": upload_options,
            "postprocess_options": postprocess_options,
        }

    def _build_retry_download_metadata(
        self,
        session: Dict[str, Any],
        retry_paths: set[str],
    ) -> Dict[str, Any]:
        statistics = dict(session.get("statistics") or {})
        download_root = str(
            session.get("local_download_root")
            or statistics.get("download_root")
            or ""
        ).strip()
        if not download_root or not os.path.isdir(download_root):
            raise ValueError("原下载缓存目录不存在，无法断点续传；请重新创建增强下载任务")

        failure_summary = dict(session.get("failure_summary") or {})
        remaining_failed_resources = [
            dict(item)
            for item in failure_summary.get("failed_resources") or []
            if str(item.get("relative_path") or "").strip() not in retry_paths
        ]
        return {
            "download_root": download_root,
            "remaining_failed_resources": remaining_failed_resources,
            "session_selected_resource_count": len(session.get("selected_resources") or []),
        }

    async def retry_failed_session(self, session_id: str) -> Dict[str, Any]:
        async with self._get_retry_lock(session_id):
            return await self._retry_failed_session_unlocked(session_id)

    async def _retry_failed_session_unlocked(self, session_id: str) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event
        from .task_engine import Task, TaskType, get_task_engine

        session = self._get_session(session_id)
        engine = get_task_engine()
        active_task = self._find_active_session_download_task(engine, session_id)
        if active_task is not None:
            return self._build_active_retry_session(session, active_task)
        selected_resources = list(session.get("selected_resources") or [])
        failure_summary = dict(session.get("failure_summary") or {})
        failed_paths = {str(item.get("relative_path") or "") for item in failure_summary.get("failed_resources") or []}
        retry_resources = [item for item in selected_resources if str(item.get("relative_path") or "") in failed_paths] or selected_resources
        if not retry_resources:
            raise ValueError("会话中没有可重试资源")

        retry_options = self._build_retry_task_options(session)
        retry_metadata = self._build_retry_download_metadata(
            session,
            {
                str(item.get("relative_path") or "").strip()
                for item in retry_resources
                if str(item.get("relative_path") or "").strip()
            },
        )
        latest_task_metadata = dict(retry_options.get("latest_task_metadata") or {})
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(session.get("folder_path") or session.get("rjcode") or ""),
            metadata={
                "rjcode": session.get("rjcode"),
                "work_title": session.get("source_label") or session.get("rjcode"),
                "folder_path": session.get("folder_path") or "",
                "download_mode": "enhanced",
                "session_id": session_id,
                "selected_resources": retry_resources,
                "selected_resource_count": len(retry_resources),
                "download_root": retry_metadata["download_root"],
                "remaining_failed_resources": retry_metadata["remaining_failed_resources"],
                "session_selected_resource_count": retry_metadata["session_selected_resource_count"],
                "queue_priority": int(session.get("queue_priority") or 100),
                "upload_options": retry_options.get("upload_options") or {},
                "postprocess_options": retry_options.get("postprocess_options") or {},
                "verify_md5_after_download": latest_task_metadata.get("verify_md5_after_download", True),
                "download_timeout_seconds": int(latest_task_metadata.get("download_timeout_seconds") or 0),
                "circle_name": str(
                    (retry_options.get("postprocess_options") or {}).get("circle_name")
                    or latest_task_metadata.get("circle_name")
                    or ""
                ).strip(),
                "source_page": session.get("source_page") or "asmr-sync",
                "source_action": "retry_failed_resources",
                "source_label": session.get("source_label") or session.get("rjcode"),
            },
            rjcode=session.get("rjcode"),
        )
        claimed, updated, previous = self._claim_session_retry(session_id, task.id)
        if not claimed:
            return updated
        try:
            await engine.submit(task)
        except Exception:
            self._rollback_session_retry_claim(session_id, task.id, previous)
            raise
        log_asmr_sync_event(
            "task_retried",
            summary=f"{updated.get('rjcode') or session_id} 已重新提交失败资源",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
            task_id=task.id,
            detail={"resource_count": len(retry_resources)},
        )
        return updated

    async def retry_failed_session_resources(self, session_id: str, relative_paths: List[str]) -> Dict[str, Any]:
        async with self._get_retry_lock(session_id, relative_paths):
            return await self._retry_failed_session_resources_unlocked(session_id, relative_paths)

    async def _retry_failed_session_resources_unlocked(self, session_id: str, relative_paths: List[str]) -> Dict[str, Any]:
        normalized_paths = [str(path or "").strip() for path in (relative_paths or []) if str(path or "").strip()]
        if not normalized_paths:
            raise ValueError("没有可重试的失败文件")

        session = self._get_session(session_id)
        selected_resources = list(session.get("selected_resources") or [])
        failure_summary = dict(session.get("failure_summary") or {})
        failed_items = list(failure_summary.get("failed_resources") or [])
        failed_paths = {str(item.get("relative_path") or "").strip() for item in failed_items if str(item.get("relative_path") or "").strip()}
        selected_paths = {
            str(item.get("relative_path") or item.get("file_name") or "").strip()
            for item in selected_resources
            if str(item.get("relative_path") or item.get("file_name") or "").strip()
        }
        target_paths = {path for path in normalized_paths if path in failed_paths}
        if not target_paths:
            target_paths = {path for path in normalized_paths if path in selected_paths}
        if not target_paths:
            raise ValueError("指定文件不在失败列表中")

        retry_resources = [
            item for item in selected_resources
            if str(item.get("relative_path") or "").strip() in target_paths
        ]
        if not retry_resources:
            raise ValueError("会话中没有匹配到可重试资源")

        from .activity_log_service import log_asmr_sync_event
        from .task_engine import Task, TaskType, get_task_engine

        engine = get_task_engine()
        active_task = self._find_active_session_download_task(engine, session_id, target_paths)
        if active_task is not None:
            return self._build_active_retry_session(session, active_task)
        retry_options = self._build_retry_task_options(session)
        retry_metadata = self._build_retry_download_metadata(session, target_paths)
        latest_task_metadata = dict(retry_options.get("latest_task_metadata") or {})
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(session.get("folder_path") or session.get("rjcode") or ""),
            metadata={
                "rjcode": session.get("rjcode"),
                "work_title": session.get("source_label") or session.get("rjcode"),
                "folder_path": session.get("folder_path") or "",
                "download_mode": "enhanced",
                "session_id": session_id,
                "selected_resources": retry_resources,
                "selected_resource_count": len(retry_resources),
                "download_root": retry_metadata["download_root"],
                "remaining_failed_resources": retry_metadata["remaining_failed_resources"],
                "session_selected_resource_count": retry_metadata["session_selected_resource_count"],
                "queue_priority": int(session.get("queue_priority") or 100),
                "upload_options": retry_options.get("upload_options") or {},
                "postprocess_options": retry_options.get("postprocess_options") or {},
                "verify_md5_after_download": latest_task_metadata.get("verify_md5_after_download", True),
                "download_timeout_seconds": int(latest_task_metadata.get("download_timeout_seconds") or 0),
                "circle_name": str(
                    (retry_options.get("postprocess_options") or {}).get("circle_name")
                    or latest_task_metadata.get("circle_name")
                    or ""
                ).strip(),
                "source_page": session.get("source_page") or "asmr-sync",
                "source_action": "retry_failed_resource_item",
                "source_label": session.get("source_label") or session.get("rjcode"),
            },
            rjcode=session.get("rjcode"),
        )
        await engine.submit(task)
        updated = self._update_session(session_id, task_id=task.id, status="queued")
        log_asmr_sync_event(
            "task_retried",
            summary=f"{updated.get('rjcode') or session_id} 已重新提交 {len(retry_resources)} 个失败文件",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
            task_id=task.id,
            detail={"resource_count": len(retry_resources), "relative_paths": list(target_paths)},
        )
        return updated

    async def reimport_downloaded_session(
        self,
        session_id: str,
        *,
        target_library_id: str,
        target_subdir: str = "",
    ) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event
        from .task_engine import Task, TaskType, get_task_engine

        session = self._get_session(session_id)
        statistics = dict(session.get("statistics") or {})
        download_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
        if not download_root or not os.path.isdir(download_root):
            raise ValueError("本地已下载目录不存在，无法直接入库")

        selected_resources = list(session.get("selected_resources") or [])
        reusable_resources = []
        for item in selected_resources:
            relative_path = self._sanitize_relative_path(str(item.get("relative_path") or item.get("file_name") or ""))
            if not relative_path:
                continue
            local_path = os.path.join(download_root, relative_path)
            if os.path.exists(local_path):
                reusable_resources.append(item)
        if not reusable_resources:
            raise ValueError("当前会话没有可复用的已下载文件")

        engine = get_task_engine()
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(session.get("folder_path") or session.get("rjcode") or ""),
            metadata={
                "rjcode": session.get("rjcode"),
                "work_title": session.get("source_label") or session.get("rjcode"),
                "folder_path": session.get("folder_path") or "",
                "download_mode": "enhanced",
                "session_id": session_id,
                "selected_resources": reusable_resources,
                "selected_resource_count": len(reusable_resources),
                "download_root": download_root,
                "queue_priority": int(session.get("queue_priority") or 100),
                "upload_options": {
                    "enabled": False,
                    "mode": "disabled",
                    "target_path": "",
                    "library_id": "",
                },
                "postprocess_options": {
                    "enabled": True,
                    "target_library_id": str(target_library_id or "").strip(),
                    "target_subdir": str(target_subdir or "").strip().strip("/\\"),
                    "naming_mode": "preserve",
                    "classify_mode": "circle",
                    "circle_name": str((statistics.get("circle_name") or session.get("source_label") or "")).strip(),
                    "skip_metadata_fetch": True,
                },
                "verify_md5_after_download": False,
                "source_page": session.get("source_page") or "circle-completion",
                "source_action": "reimport_downloaded_session",
                "source_label": session.get("source_label") or session.get("rjcode"),
            },
            rjcode=session.get("rjcode"),
        )
        await engine.submit(task)
        updated = self._update_session(session_id, task_id=task.id, status="queued")
        log_asmr_sync_event(
            "task_retried",
            summary=f"{updated.get('rjcode') or session_id} 已从本地已下载内容重新入库",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
            task_id=task.id,
            detail={
                "resource_count": len(reusable_resources),
                "download_root": download_root,
                "target_library_id": str(target_library_id or "").strip(),
                "target_subdir": str(target_subdir or "").strip().strip("/\\"),
            },
        )
        return updated

    async def reimport_local_download_root(
        self,
        *,
        download_root: str,
        rjcode: str,
        target_library_id: str,
        target_subdir: str = "",
        circle_name: str = "",
    ) -> Dict[str, Any]:
        from .task_engine import Task, TaskType, get_task_engine

        normalized_root = str(download_root or "").strip()
        normalized_rjcode = self.normalize_rjcode(rjcode)
        if not normalized_root or not os.path.isdir(normalized_root):
            raise ValueError("本地已下载目录不存在，无法直接入库")
        if not normalized_rjcode:
            raise ValueError("缺少 RJ 号，无法直接入库")
        if not str(target_library_id or "").strip():
            raise ValueError("缺少目标库存，无法直接入库")

        reusable_resources: List[Dict[str, Any]] = []
        for root, _, files in os.walk(normalized_root):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, normalized_root).replace("\\", "/")
                reusable_resources.append({
                    "file_name": filename,
                    "relative_path": relative_path,
                    "local_path": local_path,
                    "size_bytes": os.path.getsize(local_path) if os.path.exists(local_path) else 0,
                    "resource_type": self.classify_resource_type(filename, relative_path),
                    "language": self.detect_language(filename, relative_path),
                    "selected": True,
                })
        if not reusable_resources:
            raise ValueError("本地下载目录中没有可入库的文件")

        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=normalized_root,
            metadata={
                "rjcode": normalized_rjcode,
                "work_title": normalized_rjcode,
                "session_id": "",
                "download_mode": "enhanced",
                "download_root": normalized_root,
                "selected_resources": reusable_resources,
                "selected_resource_count": len(reusable_resources),
                "upload_options": {
                    "enabled": False,
                    "mode": "disabled",
                    "target_path": "",
                    "library_id": "",
                },
                "postprocess_options": {
                    "enabled": True,
                    "target_library_id": str(target_library_id or "").strip(),
                    "target_subdir": str(target_subdir or "").strip().strip("/\\"),
                    "naming_mode": "preserve",
                    "classify_mode": "circle",
                    "circle_name": str(circle_name or "").strip(),
                    "skip_metadata_fetch": True,
                },
                "verify_md5_after_download": False,
                "source_page": "circle-completion",
                "source_action": "reimport_local_download_root",
                "source_label": str(circle_name or normalized_rjcode).strip() or normalized_rjcode,
                "circle_name": str(circle_name or "").strip(),
            },
            rjcode=normalized_rjcode,
        )
        engine = get_task_engine()
        await engine.submit(task)
        return {
            "success": True,
            "rjcode": normalized_rjcode,
            "download_root": normalized_root,
            "task_id": task.id,
            "resource_count": len(reusable_resources),
        }

    async def build_download_plan(
        self,
        *,
        rjcode: str,
        folder_path: str = "",
        filters: Optional[Dict[str, Any]] = None,
        refresh: bool = True,
        emit_activity_log: bool = True,
    ) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event

        normalized_rjcode = self.normalize_rjcode(rjcode)
        try:
            work_info, remote_resources = await self.fetch_remote_resources(normalized_rjcode, refresh=bool(refresh))
            local_resources = self.scan_local_resources(folder_path) if folder_path else []
            matched_resources, missing_resources, local_only_resources, pairing_conflicts = self._match_remote_with_local(local_resources, remote_resources)

            remote_catalog: List[Dict[str, Any]] = []
            existing_relative_paths = {
                str((item.get("remote") or {}).get("relative_path") or "").strip() for item in matched_resources
            }
            match_map = {str((item.get("remote") or {}).get("relative_path") or "").strip(): item for item in matched_resources}
            for item in remote_resources:
                key = str(item.get("relative_path") or "").strip()
                next_item = dict(item)
                next_item["exists_locally"] = key in existing_relative_paths
                next_item["match_status"] = "matched" if key in existing_relative_paths else "missing_remote"
                next_item["match_score"] = int((match_map.get(key) or {}).get("score") or 0)
                next_item["match_basis"] = list((match_map.get(key) or {}).get("match_basis") or [])
                remote_catalog.append(next_item)

            filtered_resources = self._apply_filters(remote_catalog, filters or {})
            selectable_resources = self._select_default_resources(filtered_resources)
            session_id = self._create_download_session(
                rjcode=normalized_rjcode,
                work_title=str(work_info.get("title") or ""),
                folder_path=folder_path,
                target_path="",
                upload_mode="disabled",
                selected_filters=filters or {},
                selected_resources=selectable_resources,
                source_label=str(work_info.get("title") or normalized_rjcode),
                status="planning",
            )

            persisted_resources = []
            for item in remote_catalog:
                next_item = dict(item)
                next_item["download_status"] = "downloaded" if next_item.get("exists_locally") else "cataloged"
                next_item["match_status"] = next_item.get("match_status") or ("matched" if next_item.get("exists_locally") else "missing_remote")
                next_item["verify_status"] = "pending"
                next_item["upload_status"] = "pending"
                next_item["session_id"] = session_id
                persisted_resources.append(next_item)
            self._upsert_work_record(normalized_rjcode, work_info, status="cataloged")
            self._upsert_resource_records(normalized_rjcode, work_info, persisted_resources, session_id=session_id)

            local_pair_issues = self._detect_local_pair_issues(local_resources)
            summary = {
                "remote_total": len(remote_catalog),
                "local_total": len(local_resources),
                "missing_total": len(missing_resources),
                "matched_total": len(matched_resources),
                "local_only_total": len(local_only_resources),
                "selectable_total": len(selectable_resources),
                "selected_total": len([item for item in selectable_resources if item.get("selected")]),
            }
            result = {
                "success": True,
                "session_id": session_id,
                "rjcode": normalized_rjcode,
                "title": str(work_info.get("title") or ""),
                "cover_url": str(work_info.get("mainCoverUrl") or ""),
                "source_provider": "asmr.one",
                "folder_path": folder_path,
                "summary": summary,
                "work_info": {
                    "rjcode": normalized_rjcode,
                    "title": str(work_info.get("title") or ""),
                    "circle": work_info.get("circle"),
                    "tags": work_info.get("tags") or [],
                },
                "local_pair_issues": local_pair_issues,
                "missing_remote_resources": missing_resources,
                "missing_resources": missing_resources,
                "matched_resources": matched_resources,
                "local_orphan_resources": local_only_resources,
                "local_only_resources": local_only_resources,
                "pairing_conflicts": pairing_conflicts,
                "match_conflicts": pairing_conflicts,
                "selectable_resources": selectable_resources,
                "grouped_resources": self._group_resources(selectable_resources),
                "selection_presets": self._build_selection_presets(selectable_resources),
            }
            if emit_activity_log:
                log_asmr_sync_event(
                    "enhanced_plan_created",
                    summary=f"{normalized_rjcode} 已生成补档计划，候选 {summary['selectable_total']} 个",
                    session_id=session_id,
                    rjcode=normalized_rjcode,
                    detail={"resource_count": summary["selectable_total"], "selected_filters": filters or {}},
                )
            return result
        except Exception as exc:
            if emit_activity_log:
                log_asmr_sync_event(
                    "enhanced_plan_failed",
                    status="failed",
                    summary=f"{normalized_rjcode} 生成补档计划失败：{str(exc)}",
                    rjcode=normalized_rjcode,
                    detail={"selected_filters": filters or {}, "exception_type": exc.__class__.__name__},
                )
            raise

    async def _upload_to_local(self, source_path: str, target_root: str, relative_path: str, progress_callback=None, cancel_check=None, pause_wait=None) -> str:
        destination = os.path.join(target_root, self._sanitize_relative_path(relative_path))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        uploaded = 0
        total_size = os.path.getsize(source_path) if os.path.exists(source_path) else 0
        async with get_resource_budget_service().acquire("disk_io_local", reason="asmr.upload_local"):
            with open(source_path, "rb") as src, open(destination, "wb") as dst:
                while True:
                    if cancel_check and cancel_check():
                        return ""
                    if pause_wait:
                        await pause_wait()
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    dst.write(chunk)
                    uploaded += len(chunk)
                    if progress_callback:
                        progress_callback(uploaded, total_size)
        return destination

    async def _upload_to_synology(
        self,
        source_path: str,
        library_id: str,
        target_root: str,
        relative_path: str,
        progress_callback=None,
    ) -> str:
        from .library_manager import get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if not library.synology:
            raise RuntimeError("远程库存未配置群晖参数")
        client = self._get_synology_client(library_id, library.synology)
        remote_relative = self._sanitize_relative_path(relative_path).replace("\\", "/")
        remote_target = str(PurePosixPath(target_root) / PurePosixPath(remote_relative).parent)
        remote_name = PurePosixPath(remote_relative).name
        try:
            await manager._ensure_remote_directory(client, remote_target)
            await client.upload_file(remote_target, source_path, overwrite=True, remote_name=remote_name, progress_callback=progress_callback)
        except Exception as exc:
            library_name = str(getattr(library, "name", "") or library_id).strip() or library_id
            base_url = str(getattr(library.synology, "base_url", "") or "").strip()
            raise RuntimeError(
                f"上传到远程库存失败: 库={library_name}({library_id}) 地址={base_url} 目录={remote_target} 文件={remote_name} 原因={exc}"
            ) from exc
        return str(PurePosixPath(remote_target) / remote_name)

    def _resolve_upload_options(self, task_metadata: Dict[str, Any]) -> Dict[str, Any]:
        config = get_config().asmr_sync
        upload_options = dict(task_metadata.get("upload_options") or {})
        return {
            "enabled": bool(upload_options.get("enabled", getattr(config, "auto_upload_enabled", False))),
            "mode": str(upload_options.get("mode") or getattr(config, "auto_upload_mode", "local")).lower(),
            "target_path": str(upload_options.get("target_path") or getattr(config, "auto_upload_target_path", "")).strip(),
            "library_id": str(upload_options.get("library_id") or getattr(config, "auto_upload_library_id", "")).strip(),
        }

    def _resolve_postprocess_options(self, task_metadata: Dict[str, Any]) -> Dict[str, Any]:
        options = dict(task_metadata.get("postprocess_options") or {})
        flatten_files = bool(options.get("flatten_files"))
        naming_mode = str(options.get("naming_mode") or "api").strip().lower() or "api"
        classify_mode = str(options.get("classify_mode") or "circle").strip().lower() or "circle"
        # flatten 直放：兜底强制 preserve / none，archive 路径只到 target_subdir，无作品 / 社团目录。
        if flatten_files:
            naming_mode = "preserve"
            classify_mode = "none"
        return {
            "enabled": bool(options.get("enabled", False)),
            "target_library_id": str(options.get("target_library_id") or "").strip(),
            "target_subdir": str(options.get("target_subdir") or "").strip().strip("/\\"),
            "naming_mode": naming_mode,
            "classify_mode": classify_mode,
            "flatten_files": flatten_files,
            "circle_name": str(options.get("circle_name") or task_metadata.get("circle_name") or "").strip(),
            "skip_metadata_fetch": bool(options.get("skip_metadata_fetch")),
        }

    async def _prepare_circle_completion_synology_upload_target(
        self,
        *,
        rjcode: str,
        metadata: Dict[str, Any],
        upload_options: Dict[str, Any],
        postprocess_options: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        from .library_manager import get_library_manager

        target_library_id = str(upload_options.get("library_id") or postprocess_options.get("target_library_id") or "").strip()
        if not target_library_id:
            return None
        manager = get_library_manager()
        target_library = manager.get_library_definition(target_library_id)
        if not target_library or target_library.type != "synology_filestation" or not target_library.synology:
            return None

        final_metadata = dict(metadata or {})
        final_metadata["rjcode"] = rjcode
        final_metadata["work_name"] = str(final_metadata.get("work_name") or final_metadata.get("work_title") or metadata.get("work_title") or rjcode).strip() or rjcode
        final_metadata["work_title"] = str(final_metadata.get("work_title") or final_metadata["work_name"]).strip() or final_metadata["work_name"]
        circle_name = str(postprocess_options.get("circle_name") or final_metadata.get("maker_name") or "").strip()
        if circle_name:
            final_metadata["classification_maker_name"] = circle_name
            final_metadata["original_maker_name"] = circle_name
            final_metadata["maker_name"] = str(final_metadata.get("maker_name") or circle_name).strip() or circle_name

        flatten_files = bool(postprocess_options.get("flatten_files"))
        target_root = PurePosixPath(target_library.root_path)
        target_subdir = str(postprocess_options.get("target_subdir") or "").strip().strip("/\\")
        if target_subdir:
            target_root = target_root / target_subdir
        classify_mode = str(postprocess_options.get("classify_mode") or "").strip().lower()
        if classify_mode == "circle" and not flatten_files:
            circle_dir = self._sanitize_folder_name(circle_name or final_metadata.get("maker_name") or "未分类社团", "未分类社团")
            target_root = target_root / circle_dir

        client = self._get_synology_client(target_library_id, target_library.synology)
        await manager._ensure_remote_directory(client, str(target_root))

        # flatten 直放：所有文件直接上传到 target_root（即 root_path/target_subdir），不创建作品目录
        if flatten_files:
            return {
                "final_metadata": final_metadata,
                "upload_options": {
                    **upload_options,
                    "enabled": True,
                    "mode": "synology",
                    "library_id": target_library_id,
                    "target_path": str(target_root),
                },
                "final_output_path": str(target_root),
                "immediate_synology_upload": True,
            }

        folder_name = await self._build_api_rename_name(rjcode, final_metadata) if postprocess_options.get("naming_mode") == "api" else self._sanitize_folder_name(final_metadata["work_name"], rjcode)
        remote_root = str(target_root / folder_name)
        if not await manager._remote_path_exists(client, remote_root):
            await client.create_folder(str(target_root), folder_name)

        return {
            "final_metadata": final_metadata,
            "upload_options": {
                **upload_options,
                "enabled": True,
                "mode": "synology",
                "library_id": target_library_id,
                "target_path": remote_root,
            },
            "final_output_path": remote_root,
            "immediate_synology_upload": True,
        }

    def _sanitize_folder_name(self, value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r'[<>:"/\\|?*]', "", text).strip(" .")
        return text or fallback

    async def _build_api_rename_name(self, rjcode: str, metadata: Dict[str, Any]) -> str:
        from .rename_service import RenameService

        config = get_config()
        rename_service = RenameService()
        work_name = str(metadata.get("work_name") or metadata.get("work_title") or rjcode).strip() or rjcode
        if config.rename.api_rename_follow_template:
            japanese_metadata = None
            if config.rename.use_japanese_metadata:
                japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
            new_name = rename_service._compile_name(metadata, japanese_metadata)
            return rename_service._sanitize_filename(new_name)
        simple_name = f"{rjcode} {work_name}".strip()
        return rename_service._sanitize_filename(simple_name)

    async def _api_rename_download_root(self, folder_path: str, rjcode: str, metadata: Dict[str, Any]) -> str:
        renamed_name = await self._build_api_rename_name(rjcode, metadata)
        current_path = Path(folder_path)
        target_path = current_path.parent / renamed_name
        if current_path.name == renamed_name:
            return str(current_path)
        counter = 1
        while target_path.exists() and target_path.resolve() != current_path.resolve():
            target_path = current_path.parent / f"{renamed_name}({counter})"
            counter += 1
        await asyncio.to_thread(shutil.move, str(current_path), str(target_path))
        return str(target_path)

    async def _finalize_circle_completion_download(
        self,
        task,
        download_root: str,
        rjcode: str,
        metadata: Dict[str, Any],
        postprocess_options: Dict[str, Any],
    ) -> str:
        from .classifier import SmartClassifier
        from .library_manager import get_library_manager
        from .metadata_service import MetadataService
        from .task_engine import Task, TaskType

        config = get_config()
        skip_metadata_fetch = bool(postprocess_options.get("skip_metadata_fetch"))
        final_metadata = {}
        if not skip_metadata_fetch:
            temp_task = Task(task_type=TaskType.METADATA, source_path=download_root, rjcode=rjcode)
            temp_task.task_metadata = {"rjcode": rjcode}
            fetched_metadata = await MetadataService().fetch(download_root, temp_task)
            final_metadata = dict(fetched_metadata or {})
        final_metadata["rjcode"] = rjcode
        final_metadata["work_name"] = str(final_metadata.get("work_name") or metadata.get("work_title") or metadata.get("title") or rjcode).strip() or rjcode
        final_metadata["work_title"] = final_metadata["work_name"]
        circle_name = str(postprocess_options.get("circle_name") or final_metadata.get("maker_name") or "").strip()
        if circle_name:
            final_metadata["classification_maker_name"] = circle_name
            final_metadata["original_maker_name"] = circle_name
            final_metadata["maker_name"] = str(final_metadata.get("maker_name") or circle_name).strip() or circle_name

        task.task_metadata.update(final_metadata)
        task.update_progress(97, "准备入库")
        renamed_root = download_root
        if postprocess_options.get("naming_mode") == "api":
            renamed_root = await self._api_rename_download_root(download_root, rjcode, final_metadata)

        target_subdir = str(postprocess_options.get("target_subdir") or "").strip().strip("/\\")
        classify_mode = str(postprocess_options.get("classify_mode") or "").strip().lower()
        flatten_files = bool(postprocess_options.get("flatten_files"))
        if classify_mode == "circle" and not flatten_files:
            circle_dir = self._sanitize_folder_name(circle_name or final_metadata.get("maker_name") or "未分类社团", "未分类社团")
            task.update_progress(98, "按社团入库")
        else:
            circle_dir = ""
            if flatten_files:
                task.update_progress(98, "直放到指定目录" if target_subdir else "直放到库存根目录")
            else:
                task.update_progress(98, "入库到指定目录" if target_subdir else "入库")
        manager = get_library_manager()
        target_library_id = str(postprocess_options.get("target_library_id") or "").strip()
        classifier = SmartClassifier()

        if target_library_id:
            target_library = manager.get_library_definition(target_library_id)
            if target_library and target_library.type != "local":
                relative_parts = [part for part in [target_subdir, circle_dir] if part]
                relative_target_dir = "/".join(relative_parts)
                client = manager.get_cached_synology_client(target_library.synology)
                target_root = PurePosixPath(target_library.root_path)
                if relative_target_dir:
                    target_root = target_root / relative_target_dir
                # flatten 直放：所有文件直接到 target_root，不创建作品目录层
                if flatten_files:
                    remote_root = str(target_root)
                else:
                    remote_root = str(target_root / os.path.basename(renamed_root))
                await manager._ensure_remote_directory(client, str(target_root))
                if not flatten_files:
                    # 容忍目录已存在（error 117），支持重试场景
                    try:
                        await client.create_folder(str(target_root), os.path.basename(renamed_root))
                    except Exception as _ce:
                        if "already exists" not in str(_ce).lower() and not client._is_error_code(_ce, 117):
                            raise

                # 预走目录树，收集文件列表
                file_rows_lib = []
                for root, _, files in os.walk(renamed_root):
                    for filename in files:
                        local_file = os.path.join(root, filename)
                        relative_file = os.path.relpath(local_file, renamed_root).replace("\\", "/")
                        remote_dir_for_file = str(PurePosixPath(remote_root) / PurePosixPath(relative_file).parent)
                        file_rows_lib.append({
                            "local": local_file,
                            "name": filename,
                            "relative": relative_file,
                            "remote_dir": remote_dir_for_file,
                            "remote_path": str(PurePosixPath(remote_root) / PurePosixPath(relative_file)),
                            "size": os.path.getsize(local_file) if os.path.exists(local_file) else 0,
                        })

                total_upload_files = max(len(file_rows_lib), 1)
                upload_progress_state = {}

                # Phase 1: 并发创建所有需要的远程子目录（保序去重）
                unique_remote_dirs = list(dict.fromkeys(row["remote_dir"] for row in file_rows_lib))
                await asyncio.gather(*[manager._ensure_remote_directory(client, d) for d in unique_remote_dirs])

                # Phase 2: 并发上传所有文件，Semaphore(4) 控速
                _lib_upload_sem = asyncio.Semaphore(4)

                async def upload_lib_file(row: dict, index: int) -> None:
                    async with _lib_upload_sem:
                        self._append_task_log(task, f"入库上传 {index}/{total_upload_files}: {row['relative']}")

                        def sync_progress(uploaded_bytes: int, total_bytes: int, _row=row, _idx=index):
                            self._update_upload_runtime(
                                task,
                                upload_progress_state,
                                file_key=_row["relative"],
                                file_name=_row["name"],
                                relative_path=_row["relative"],
                                uploaded_bytes=uploaded_bytes,
                                total_bytes=total_bytes,
                                index=_idx,
                                total_files=total_upload_files,
                                stage="library_upload",
                                target_path=_row["remote_path"],
                            )
                            task.current_step = f"入库上传 {_idx}/{total_upload_files}: {_row['name']}"

                        try:
                            await client.upload_file(
                                row["remote_dir"], row["local"],
                                overwrite=True, remote_name=row["name"],
                                progress_callback=sync_progress,
                            )
                        except Exception as exc:
                            base_url = str(getattr(target_library.synology, "base_url", "") or "").strip()
                            raise RuntimeError(
                                f"直接入库上传失败: 库={target_library.name}({target_library.id}) 地址={base_url} 目录={row['remote_dir']} 文件={row['name']} 原因={exc}"
                            ) from exc
                        # asyncio 单线程，以下三行无并发竞争
                        all_uploaded = list(task.task_metadata.get("uploaded_files") or [])
                        all_uploaded.append({
                            "name": row["relative"],
                            "upload_path": row["remote_path"],
                            "relative_path": row["relative"],
                            "size_bytes": row["size"],
                        })
                        task.task_metadata["uploaded_files"] = all_uploaded[-200:]
                        self._append_task_log(task, f"入库完成: {row['relative']}")

                await asyncio.gather(*[upload_lib_file(row, idx + 1) for idx, row in enumerate(file_rows_lib)])
                self._finalize_upload_runtime(task, "completed")
                final_path = remote_root
                await asyncio.to_thread(shutil.rmtree, renamed_root, True)
                # 远程库不维护库存索引；本调用只兼容本地库路径。
                try:
                    manager._notify_index_self_mutation_upsert_subtree(target_library, final_path)
                except Exception:
                    logger.debug(
                        "[索引] 社团补全入库后通知 upsert 失败 path=%s",
                        final_path, exc_info=True,
                    )
                return final_path
            if target_library:
                target_root = target_library.root_path
            else:
                target_root = config.storage.library_path
        else:
            target_root = config.storage.library_path

        target_parts = [part for part in [target_root, target_subdir, circle_dir] if part]
        target_dir = os.path.join(*target_parts)
        if flatten_files:
            # 直放模式：把 renamed_root 内的文件直接搬到 target_dir 根，跳过作品目录层；
            # 同名文件用 (1)/(2) 后缀避免覆盖。
            os.makedirs(target_dir, exist_ok=True)
            async with get_resource_budget_service().acquire(
                "disk_io_local",
                reason="asmr.finalize_flatten",
            ):
                for entry in os.listdir(renamed_root):
                    src = os.path.join(renamed_root, entry)
                    if not os.path.isfile(src):
                        continue
                    stem, ext = os.path.splitext(entry)
                    dst = os.path.join(target_dir, entry)
                    counter = 1
                    while os.path.exists(dst):
                        dst = os.path.join(target_dir, f"{stem}({counter}){ext}")
                        counter += 1
                    await move_path_efficient(src, dst)
            try:
                await asyncio.to_thread(shutil.rmtree, renamed_root, True)
            except Exception:
                logger.debug("[直放] 清理临时下载目录失败 path=%s", renamed_root, exc_info=True)
            final_path = target_dir
        else:
            async with get_resource_budget_service().acquire(
                "disk_io_local",
                reason="asmr.finalize_classified",
            ):
                final_path = await asyncio.to_thread(
                    classifier._move_with_rename,
                    renamed_root,
                    target_dir,
                )
        # 索引同步：本地落地后按路径反查 library 通知（target_library 可能是 None）
        try:
            if target_library is not None:
                manager._notify_index_self_mutation_upsert_subtree(target_library, final_path)
            else:
                manager.notify_index_upsert_by_path(final_path)
        except Exception:
            logger.debug(
                "[索引] 社团补全本地入库后通知 upsert 失败 path=%s",
                final_path, exc_info=True,
            )
        return final_path

    async def _sync_circle_completion_owned_state(self, rjcode: str, folder_path: str, library_id: str = "") -> None:
        if not rjcode or not folder_path:
            return
        try:
            from .circle_completion_service import get_circle_completion_service

            await get_circle_completion_service().sync_owned_for_rj(
                rjcode,
                folder_path=folder_path,
                library_id=library_id,
            )
        except Exception:
            logger.warning("[社团补全] 回写库存拥有态失败 rj=%s path=%s", rjcode, folder_path, exc_info=True)

    async def _refresh_library_after_full_upload(self, rjcode: str, folder_path: str, library_id: str = "") -> None:
        if not rjcode or not folder_path:
            return
        await self._sync_circle_completion_owned_state(rjcode, folder_path, library_id=library_id)
        if not library_id:
            return
        try:
            from .library_manager import get_library_manager

            manager = get_library_manager()
            await manager.ensure_stats(force=True, library_id=library_id)
            manager.notify_index_upsert_by_path(folder_path)
        except Exception:
            logger.warning("[库存] 上传完成后刷新库存统计失败 library=%s path=%s", library_id, folder_path, exc_info=True)

    async def process_download_task(self, task) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event

        config = get_config()
        metadata = dict(task.task_metadata or {})
        rjcode = self.normalize_rjcode(metadata.get("rjcode") or task.rjcode or "")
        session_id = str(metadata.get("session_id") or "").strip()
        source_action = str(metadata.get("source_action") or "").strip()
        selected_resources = list(metadata.get("selected_resources") or [])
        if not rjcode:
            raise ValueError("缺少 RJ 号")
        if not selected_resources:
            raise ValueError("没有可下载的资源")

        timeout = int(metadata.get("download_timeout_seconds") or getattr(config.asmr_sync, "download_timeout_seconds", 60) or 60)
        max_retries = int(metadata.get("retry_count") or getattr(config.asmr_sync, "retry_count", 3) or 3)
        verify_md5 = bool(
            metadata.get("verify_md5_after_download", getattr(config.asmr_sync, "verify_md5_after_download", True))
            and getattr(config.asmr_sync, "md5_verify_required", True)
        )
        upload_options = self._resolve_upload_options(metadata)
        postprocess_options = self._resolve_postprocess_options(metadata)
        target_library_id = str(postprocess_options.get("target_library_id") or "").strip()
        if target_library_id and upload_options.get("mode") != "synology":
            try:
                from .library_manager import get_library_manager
                target_library = get_library_manager().get_library_definition(target_library_id)
                if target_library and target_library.type == "synology_filestation":
                    upload_options = {
                        **upload_options,
                        "enabled": True,
                        "mode": "synology",
                        "library_id": target_library_id,
                    }
            except Exception:
                logger.warning("推断群晖即时上传配置失败: rj=%s target_library_id=%s", rjcode, target_library_id, exc_info=True)
        immediate_synology_upload = False
        if postprocess_options.get("enabled") and upload_options.get("enabled") and upload_options.get("mode") == "synology":
            prepared_remote_upload = await self._prepare_circle_completion_synology_upload_target(
                rjcode=rjcode,
                metadata=metadata,
                upload_options=upload_options,
                postprocess_options=postprocess_options,
            )
            if prepared_remote_upload:
                upload_options = dict(prepared_remote_upload.get("upload_options") or upload_options)
                metadata.update(dict(prepared_remote_upload.get("final_metadata") or {}))
                metadata["final_output_path"] = str(prepared_remote_upload.get("final_output_path") or "")
                immediate_synology_upload = bool(prepared_remote_upload.get("immediate_synology_upload"))
        per_session_concurrency = max(1, int(getattr(config.asmr_sync, "enhanced_per_session_concurrency", 3) or 3))

        task.task_metadata["download_files"] = []
        task.task_metadata["download_runtime"] = {}
        task.task_metadata["upload_files"] = []
        task.task_metadata["uploaded_files"] = []
        task.task_metadata["upload_runtime"] = {}
        task.task_metadata["verification_failures"] = []
        task.task_metadata["failed_files"] = []
        task.task_metadata["progress_log"] = list(task.task_metadata.get("progress_log") or [])
        task.task_metadata["download_mode"] = "enhanced"
        task.task_metadata["session_id"] = session_id
        task.task_metadata["upload_options"] = upload_options
        task.task_metadata["target_path"] = str(upload_options.get("target_path") or "").strip()
        if metadata.get("final_output_path"):
            task.task_metadata["final_output_path"] = metadata.get("final_output_path")
            self._append_task_log(task, f"已准备群晖即时上传目录: {metadata.get('final_output_path')}")

        temp_root = os.path.join(config.storage.temp_path, "asmr_enhanced")
        os.makedirs(temp_root, exist_ok=True)
        download_base_path = str(metadata.get("download_base_path") or "").strip()
        download_root = str(metadata.get("download_root") or "").strip()
        is_retry_download = source_action in {"retry_failed_resources", "retry_failed_resource_item"}
        if is_retry_download and (not download_root or not os.path.isdir(download_root)):
            raise ValueError("原下载缓存目录不存在，无法断点续传；请重新创建增强下载任务")
        if not download_root:
            if download_base_path:
                download_root = os.path.join(download_base_path, f"{rjcode}_{task.id[:8]}")
            else:
                download_root = os.path.join(temp_root, f"{rjcode}_{task.id[:8]}")
        os.makedirs(download_root, exist_ok=True)
        task.task_metadata["download_root"] = download_root

        started_at = datetime.now()
        success_files: List[Dict[str, Any]] = []
        failed_files: List[Dict[str, Any]] = []
        uploaded_files: List[Dict[str, Any]] = []
        verification_failures: List[Dict[str, Any]] = []
        progress_state: Dict[str, Dict[str, Any]] = {}
        upload_progress_state: Dict[str, Dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(per_session_concurrency)
        state_lock = asyncio.Lock()
        completed_count = 0
        total_files = max(len(selected_resources), 1)
        expected_download_total_bytes = sum(
            max(0, int(resource.get("size_bytes") or resource.get("size") or 0))
            for resource in selected_resources
        )
        for resource_index, resource in enumerate(selected_resources, start=1):
            resource_path = str(
                resource.get("relative_path")
                or resource.get("file_name")
                or f"file_{resource_index:03d}.bin"
            )
            resource_name = str(resource.get("file_name") or os.path.basename(resource_path))
            resource_total = max(0, int(resource.get("size_bytes") or resource.get("size") or 0))
            progress_state[resource_path or resource_name] = {
                "name": resource_name,
                "downloaded": 0,
                "total": resource_total,
                "progress": 0,
                "index": resource_index,
                "relative_path": resource_path,
                "stage": "pending",
                "speed_bytes_per_sec": 0,
                "eta_seconds": 0,
            }
        task.task_metadata["download_files"] = sorted(
            progress_state.values(),
            key=lambda item: item.get("index") or 0,
        )
        if expected_download_total_bytes > 0:
            task.task_metadata["download_runtime"] = {
                "total_files": total_files,
                "total_bytes": expected_download_total_bytes,
                "expected_total_bytes": expected_download_total_bytes,
                "transferred_bytes": 0,
                "progress": 0,
                "speed_bytes_per_sec": 0,
                "eta_seconds": 0,
            }
        reimport_only = source_action in {"reimport_local_download_root", "reimport_downloaded_session"}
        if reimport_only:
            verify_md5 = bool(metadata.get("verify_md5_after_download", False))
        start_summary = (
            f"{rjcode} 已开始直接入库，共 {len(selected_resources)} 个资源"
            if reimport_only
            else f"{rjcode} 已开始增强下载，共 {len(selected_resources)} 个资源"
        )

        if session_id:
            self._update_session(
                session_id,
                task_id=task.id,
                status="queued",
                target_path=upload_options["target_path"],
                upload_mode=upload_options["mode"],
                statistics={**(task.task_metadata.get("performance_metrics") or {}), "download_root": download_root},
                local_download_root=download_root,
            )
            log_asmr_sync_event(
                "session_started",
                summary=start_summary,
                session_id=session_id,
                rjcode=rjcode,
                task_id=task.id,
                detail={"resource_count": len(selected_resources), "upload_mode": upload_options["mode"], "target_path": upload_options["target_path"]},
            )
        self._append_task_log(task, start_summary)

        async def handle_resource(index: int, resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            nonlocal completed_count
            await task.wait_if_paused()
            if task.is_cancelled():
                raise RuntimeError("用户取消")

            relative_path = str(resource.get("relative_path") or resource.get("file_name") or f"file_{index:03d}.bin")
            display_name = str(resource.get("file_name") or os.path.basename(relative_path))
            destination = os.path.join(download_root, self._sanitize_relative_path(relative_path))
            remote_url = str(resource.get("remote_url") or "")
            expected_size = max(0, int(resource.get("size_bytes") or resource.get("size") or 0))
            last_download_error = ""

            async with semaphore:
                try:
                    if session_id:
                        self._update_session(session_id, status="downloading")

                    def file_progress_callback(downloaded_bytes: int, total_bytes: int, name=display_name, file_index=index):
                        self._update_download_runtime(
                            task,
                            progress_state,
                            file_key=relative_path or name,
                            file_name=name,
                            relative_path=relative_path,
                            downloaded_bytes=downloaded_bytes,
                            total_bytes=max(expected_size, int(total_bytes or 0)),
                            index=file_index,
                            total_files=total_files,
                            stage="download",
                        )
                        runtime = dict(task.task_metadata.get("download_runtime") or {})
                        completed_files = int(runtime.get("completed_files") or 0)
                        task.current_step = f"{'资源检查中' if reimport_only else '下载中'} {completed_files}/{total_files}: {name}"

                    file_exists = os.path.exists(destination) and os.path.getsize(destination) > 0
                    existing_size = os.path.getsize(destination) if file_exists else 0
                    reuse_existing = bool(
                        file_exists
                        and (
                            reimport_only
                            or expected_size <= 0
                            or existing_size == expected_size
                        )
                    )
                    if reuse_existing:
                        self._update_download_runtime(
                            task,
                            progress_state,
                            file_key=relative_path or display_name,
                            file_name=display_name,
                            relative_path=relative_path,
                            downloaded_bytes=existing_size,
                            total_bytes=max(expected_size, existing_size),
                            index=index,
                            total_files=total_files,
                            stage="download_reused" if not reimport_only else "ready_for_upload",
                        )
                        task.current_step = f"{'准备入库' if reimport_only else '复用已下载文件'} {index}/{total_files}: {display_name}"
                        self._append_task_log(task, f"{display_name} {'准备直接入库' if reimport_only else '复用已下载文件'}")
                    else:
                        if file_exists and expected_size > 0 and existing_size != expected_size:
                            self._append_task_log(
                                task,
                                f"{display_name} 已存在文件大小异常"
                                f"({existing_size}/{expected_size})，重新校验下载",
                                "warning",
                            )
                        if not remote_url:
                            return {"name": display_name, "relative_path": relative_path, "reason": "缺少下载地址", "resource": resource, "stage": "download"}
                        self._append_task_log(task, f"{display_name} 开始请求资源 {index}/{total_files}")

                        def download_log_callback(message: str, level: str = "info", current_task=task):
                            nonlocal last_download_error
                            text = str(message or "").strip()
                            normalized_level = str(level or "info").lower()
                            self._append_task_log(current_task, text, normalized_level)
                            if (
                                normalized_level == "error"
                                and text
                                and "下载失败，已尝试" not in text
                            ):
                                last_download_error = text

                        ok = await self.asmr_service.download_file(
                            remote_url,
                            destination,
                            progress_callback=file_progress_callback,
                            log_callback=download_log_callback,
                            max_retries=max_retries,
                            timeout=timeout,
                            cancel_check=task.is_cancelled,
                            pause_wait=task.wait_if_paused,
                        )
                        if not ok:
                            if task.is_cancelled():
                                raise RuntimeError("用户取消")
                            partial_path = destination + ".downloading"
                            partial_size = 0
                            for candidate_path in (partial_path, destination):
                                if os.path.exists(candidate_path):
                                    partial_size = max(partial_size, os.path.getsize(candidate_path))
                            self._update_download_runtime(
                                task,
                                progress_state,
                                file_key=relative_path or display_name,
                                file_name=display_name,
                                relative_path=relative_path,
                                downloaded_bytes=partial_size,
                                total_bytes=expected_size or partial_size,
                                index=index,
                                total_files=total_files,
                                stage="download_failed",
                            )
                            return {
                                "name": display_name,
                                "relative_path": relative_path,
                                "reason": last_download_error or "下载失败",
                                "resource": resource,
                                "stage": "download",
                                "local_path": destination if os.path.exists(destination) else "",
                            }
                        completed_size = os.path.getsize(destination) if os.path.exists(destination) else expected_size
                        self._update_download_runtime(
                            task,
                            progress_state,
                            file_key=relative_path or display_name,
                            file_name=display_name,
                            relative_path=relative_path,
                            downloaded_bytes=completed_size,
                            total_bytes=max(expected_size, completed_size),
                            index=index,
                            total_files=total_files,
                            stage="downloaded",
                        )
                        self._append_task_log(task, f"{display_name} 下载完成")

                    checksum_md5 = ""
                    expected_md5 = str(resource.get("checksum_md5") or "").strip().lower()
                    verify_status = "skipped"
                    verify_ok = True
                    if verify_md5 and expected_md5:
                        if session_id:
                            self._update_session(session_id, status="verifying")
                        task.current_step = f"校验中 {index}/{total_files}: {display_name}"
                        checksum_md5 = await asyncio.to_thread(self._compute_md5, destination)
                        verify_ok = checksum_md5.lower() == expected_md5
                        verify_status = "passed" if verify_ok else "failed"
                        if not verify_ok:
                            verification_failures.append(
                                {
                                    "name": display_name,
                                    "relative_path": relative_path,
                                    "expected_md5": expected_md5,
                                    "actual_md5": checksum_md5,
                                }
                            )
                            if session_id:
                                log_asmr_sync_event(
                                    "resource_verify_failed",
                                    status="failed",
                                    summary=f"{rjcode} / {display_name} MD5 校验失败",
                                    session_id=session_id,
                                    rjcode=rjcode,
                                    task_id=task.id,
                                    detail={"target_path": upload_options["target_path"], "exception_type": "md5_mismatch", "expected_md5": expected_md5, "actual_md5": checksum_md5},
                                )

                    uploaded_path = ""
                    upload_status = "skipped" if not upload_options["enabled"] else "pending"
                    # 上传前再次检查暂停/取消信号
                    await task.wait_if_paused()
                    if task.is_cancelled():
                        raise RuntimeError("用户取消")
                    if upload_options["enabled"]:
                        self._mark_upload_waiting(
                            task,
                            file_name=display_name,
                            relative_path=relative_path,
                            index=index,
                            total_files=total_files,
                        )
                        async with self._global_upload_lock:
                            if session_id:
                                self._update_session(session_id, status="uploading")

                            def upload_progress_callback(uploaded_bytes: int, total_bytes: int, name=display_name, file_index=index):
                                self._update_upload_runtime(
                                    task,
                                    upload_progress_state,
                                    file_key=relative_path or name,
                                    file_name=name,
                                    relative_path=relative_path,
                                    uploaded_bytes=uploaded_bytes,
                                    total_bytes=total_bytes,
                                    index=file_index,
                                    total_files=total_files,
                                    stage="upload",
                                    target_path=uploaded_path or upload_options["target_path"],
                                )
                                runtime = dict(task.task_metadata.get("upload_runtime") or {})
                                completed_files = int(runtime.get("completed_files") or 0)
                                task.current_step = f"上传中 {completed_files}/{total_files}: {name}"

                            if upload_options["mode"] == "synology" and upload_options["library_id"] and upload_options["target_path"]:
                                uploaded_path = await self._upload_to_synology(
                                    destination,
                                    upload_options["library_id"],
                                    upload_options["target_path"],
                                    relative_path,
                                    progress_callback=upload_progress_callback,
                                )
                            elif upload_options["target_path"]:
                                uploaded_path = await self._upload_to_local(
                                    destination,
                                    upload_options["target_path"],
                                    relative_path,
                                    progress_callback=upload_progress_callback,
                                    cancel_check=task.is_cancelled,
                                    pause_wait=task.wait_if_paused,
                                )
                        upload_status = "uploaded" if uploaded_path else "failed"
                        if uploaded_path and session_id:
                            log_asmr_sync_event(
                                "resource_uploaded",
                                summary=f"{rjcode} / {display_name} 已上传",
                                session_id=session_id,
                                rjcode=rjcode,
                                task_id=task.id,
                                detail={"target_path": uploaded_path, "upload_mode": upload_options["mode"]},
                            )
                        if uploaded_path:
                            self._append_task_log(task, f"{display_name} 上传完成 -> {uploaded_path}")
                except Exception as exc:
                    return {
                        "name": display_name,
                        "relative_path": relative_path,
                        "reason": str(exc),
                        "exception_type": exc.__class__.__name__,
                        "resource": resource,
                        "stage": "upload" if upload_options["enabled"] else "download",
                        "local_path": destination if os.path.exists(destination) else "",
                    }

                result = {
                    "name": display_name,
                    "relative_path": relative_path,
                    "local_path": destination,
                    "size_bytes": os.path.getsize(destination) if os.path.exists(destination) else 0,
                    "checksum_md5": checksum_md5,
                    "verify_ok": verify_ok,
                    "verify_status": verify_status,
                    "upload_path": uploaded_path,
                    "upload_status": upload_status,
                    "resource_type": resource.get("resource_type"),
                    "resource": resource,
                }
                if session_id:
                    log_asmr_sync_event(
                        "resource_downloaded",
                        summary=f"{rjcode} / {display_name} 下载完成",
                        session_id=session_id,
                        rjcode=rjcode,
                        task_id=task.id,
                        detail={
                            "resource_count": total_files,
                            "network_retry_count": max_retries,
                            "resource_name": display_name,
                            "resource_path": relative_path,
                            "local_path": destination,
                            "upload_path": uploaded_path,
                            "size_bytes": os.path.getsize(destination) if os.path.exists(destination) else 0,
                            "upload_mode": upload_options["mode"],
                            "target_path": upload_options["target_path"],
                        },
                    )
                async with state_lock:
                    completed_count += 1
                    task.update_progress(min(96, 5 + int(completed_count / total_files * 86)), f"已完成 {completed_count}/{total_files} 个文件")
                return result

        try:
            results = await asyncio.gather(
                *[handle_resource(index, resource) for index, resource in enumerate(selected_resources, start=1)],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    failed_files.append({"name": "unknown", "reason": str(result), "exception_type": result.__class__.__name__})
                    self._append_task_log(task, f"未知文件失败: {str(result)}", "error")
                    continue
                if result is None:
                    continue
                if result.get("reason"):
                    failed_files.append(result)
                    self._append_task_log(task, f"{result.get('name') or '未知文件'} 失败: {result.get('reason') or '未知原因'}", "error")
                    continue
                success_files.append(result)
                if result.get("upload_path"):
                    uploaded_files.append({"name": result.get("name"), "upload_path": result.get("upload_path"), "relative_path": result.get("relative_path")})

            carried_failed_files = [
                dict(item)
                for item in metadata.get("remaining_failed_resources") or []
                if str(item.get("relative_path") or "").strip()
            ]
            if carried_failed_files:
                failed_by_path = {
                    str(item.get("relative_path") or "").strip(): item
                    for item in carried_failed_files
                }
                for item in failed_files:
                    failed_by_path[str(item.get("relative_path") or "").strip()] = item
                failed_files = list(failed_by_path.values())

            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            total_bytes = sum(int(item.get("size_bytes") or 0) for item in success_files)
            uploaded_bytes = sum(int(item.get("size_bytes") or 0) for item in uploaded_files)
            final_output_path = ""
            verify_summary = {
                "passed": len([item for item in success_files if item.get("verify_status") == "passed"]),
                "failed": len([item for item in success_files if item.get("verify_status") == "failed"]),
                "skipped": len([item for item in success_files if item.get("verify_status") == "skipped"]),
            }
            upload_summary = {
                "uploaded": len(uploaded_files),
                "skipped": len([item for item in success_files if item.get("upload_status") == "skipped"]),
                "failed": len([item for item in success_files if item.get("upload_status") == "failed"]),
            }
            retry_summary = {"network_retry_count": max_retries, "failed_resource_count": len(failed_files)}
            session_selected_resource_count = max(
                len(selected_resources),
                int(metadata.get("session_selected_resource_count") or 0),
            )
            session_success_count = max(0, session_selected_resource_count - len(failed_files))
            session_performance_metrics = {
                "selected_resource_count": session_selected_resource_count,
                "success_count": session_success_count,
                "failed_count": len(failed_files),
                "duration_ms": duration_ms,
                "downloaded_bytes": total_bytes,
                "uploaded_count": len(uploaded_files),
                "uploaded_bytes": uploaded_bytes,
                "average_speed_bytes": int(total_bytes / max(duration_ms / 1000, 1)) if total_bytes else 0,
                "average_upload_speed_bytes": int(uploaded_bytes / max(duration_ms / 1000, 1)) if uploaded_bytes else 0,
                "upload_runtime": dict(task.task_metadata.get("upload_runtime") or {}),
            }
            self._finalize_download_runtime(task, "completed" if success_files else "failed")
            task.task_metadata.update(
                {
                    "download_root": download_root,
                    "downloaded_resources": success_files,
                    "download_runtime": dict(task.task_metadata.get("download_runtime") or {}),
                    "uploaded_files": uploaded_files,
                    "verification_failures": verification_failures,
                    "failed_files": failed_files,
                    "verify_summary": verify_summary,
                    "upload_summary": upload_summary,
                    "retry_summary": retry_summary,
                    "performance_metrics": {
                        "duration_ms": duration_ms,
                        "downloaded_bytes": total_bytes,
                        "success_count": len(success_files),
                        "failed_count": len(failed_files),
                        "uploaded_count": len(uploaded_files),
                        "uploaded_bytes": uploaded_bytes,
                        "average_speed_bytes": int(total_bytes / max(duration_ms / 1000, 1)) if total_bytes else 0,
                        "average_upload_speed_bytes": int(uploaded_bytes / max(duration_ms / 1000, 1)) if uploaded_bytes else 0,
                        "upload_runtime": dict(task.task_metadata.get("upload_runtime") or {}),
                    },
                }
            )

            work_info = {"title": metadata.get("work_title") or metadata.get("title") or ""}
            persisted_resources = []
            for item in success_files:
                original = dict(item.get("resource") or {})
                persisted_resources.append(
                    {
                        "source": "asmr.one",
                        "source_workno": rjcode,
                        "resource_type": item.get("resource_type") or self.OTHER_TYPE,
                        "language": original.get("language") or "",
                        "file_name": item.get("name") or "",
                        "relative_path": item.get("relative_path") or item.get("name") or "",
                        "normalized_name": self.normalize_name(item.get("name") or ""),
                        "size_bytes": item.get("size_bytes") or 0,
                        "duration_seconds": None,
                        "remote_url": str(original.get("remote_url") or ""),
                        "checksum_md5": item.get("checksum_md5") or "",
                        "local_path": item.get("local_path") or "",
                        "upload_path": item.get("upload_path") or "",
                        "download_status": "uploaded" if item.get("upload_path") else "downloaded",
                        "match_status": "matched",
                        "verify_status": item.get("verify_status") or "skipped",
                        "upload_status": item.get("upload_status") or "skipped",
                        "missing_reason": "",
                        "session_id": session_id,
                        "selected": True,
                    }
                )
            for item in failed_files:
                resource = dict(item.get("resource") or {})
                persisted_resources.append(
                    {
                        "source": "asmr.one",
                        "source_workno": rjcode,
                        "resource_type": resource.get("resource_type") or self.OTHER_TYPE,
                        "language": resource.get("language") or "",
                        "file_name": item.get("name") or resource.get("file_name") or "",
                        "relative_path": item.get("relative_path") or resource.get("relative_path") or "",
                        "normalized_name": self.normalize_name(item.get("name") or resource.get("file_name") or ""),
                        "size_bytes": int(resource.get("size_bytes") or 0),
                        "duration_seconds": resource.get("duration_seconds"),
                        "remote_url": str(resource.get("remote_url") or ""),
                        "checksum_md5": str(resource.get("checksum_md5") or ""),
                        "local_path": str(item.get("local_path") or ""),
                        "upload_path": "",
                        "download_status": "downloaded" if str(item.get("local_path") or "").strip() else "failed",
                        "match_status": "missing_remote" if resource.get("exists_locally") is False else "matched",
                        "verify_status": "pending",
                        "upload_status": "failed" if str(item.get("stage") or "") == "upload" else "pending",
                        "missing_reason": str(item.get("reason") or ""),
                        "last_error": str(item.get("reason") or ""),
                        "session_id": session_id,
                        "retry_count": max_retries,
                    }
                )
            self._upsert_work_record(rjcode, work_info, status="downloaded" if success_files else "failed")
            self._upsert_resource_records(rjcode, work_info, persisted_resources, session_id=session_id)

            if not success_files:
                has_previous_success = session_success_count > 0
                session_failure_status = "partial_failed" if has_previous_success else "failed"
                failure_message = (
                    f"{rjcode} 本轮重试失败，会话仍已完成 {session_success_count} 个文件"
                    if has_previous_success
                    else f"{rjcode} 下载失败，没有任何文件成功"
                )
                if session_id:
                    self._update_session(
                        session_id,
                        status=session_failure_status,
                        statistics={**session_performance_metrics, "download_root": download_root},
                        failure_summary={"failed_resources": failed_files},
                        local_download_ready=False,
                        local_download_root=download_root,
                        local_downloaded_count=session_success_count,
                    )
                    log_asmr_sync_event(
                        "session_partial_failed",
                        status="partial_success" if has_previous_success else "failed",
                        summary=failure_message,
                        session_id=session_id,
                        rjcode=rjcode,
                        task_id=task.id,
                        detail={"resource_count": len(selected_resources), "target_path": upload_options["target_path"], "network_retry_count": max_retries, "exception_type": "all_failed"},
                    )
                raise ValueError("本轮没有任何文件下载成功" if has_previous_success else "没有任何文件下载成功")

            if failed_files:
                self._append_task_log(
                    task,
                    f"仍有 {len(failed_files)} 个文件未完成，保留原下载目录等待断点续传",
                    "warning",
                )
            elif postprocess_options.get("enabled"):
                if immediate_synology_upload and upload_options.get("target_path"):
                    final_output_path = str(upload_options.get("target_path") or "").strip()
                    task.task_metadata["final_output_path"] = final_output_path
                    self._finalize_upload_runtime(task, "completed" if uploaded_files else "failed")
                    if uploaded_files and len(uploaded_files) == len(success_files) and not failed_files and os.path.isdir(download_root):
                        await asyncio.to_thread(shutil.rmtree, download_root, True)
                else:
                    final_output_path = await self._finalize_circle_completion_download(
                        task,
                        download_root,
                        rjcode,
                        metadata,
                        postprocess_options,
                    )
                task.output_path = final_output_path
                task.task_metadata["final_output_path"] = final_output_path
                self._append_task_log(task, f"已入库到: {final_output_path}")
            elif (
                upload_options.get("enabled")
                and upload_options.get("target_path")
                and uploaded_files
                and len(uploaded_files) == len(success_files)
                and not failed_files
            ):
                # 模式 B：直放已有路径 / 即时上传到指定 target_path，无后处理归类
                final_output_path = str(upload_options.get("target_path") or "").strip()
                task.output_path = final_output_path
                task.task_metadata["final_output_path"] = final_output_path
                self._finalize_upload_runtime(task, "completed")
                if os.path.isdir(download_root):
                    await asyncio.to_thread(shutil.rmtree, download_root, True)
                self._append_task_log(task, f"已上传到: {final_output_path}")

            final_status = "partial_failed" if failed_files or verification_failures else "completed"
            target_owned_library_id = str(
                postprocess_options.get("target_library_id")
                or upload_options.get("library_id")
                or ""
            ).strip()
            all_files_uploaded = bool(
                final_status == "completed"
                and success_files
                and upload_options.get("enabled")
                and len(uploaded_files) == len(success_files)
                and final_output_path
            )
            if all_files_uploaded:
                await self._refresh_library_after_full_upload(
                    rjcode,
                    final_output_path,
                    library_id=target_owned_library_id,
                )
            if (
                final_status == "completed"
                and postprocess_options.get("enabled")
                and final_output_path
                and not all_files_uploaded
                and (
                    str(metadata.get("source_page") or "").strip() == "circle-completion"
                    or str(metadata.get("task_domain") or "").strip() == "circle_completion"
                )
            ):
                await self._sync_circle_completion_owned_state(
                    rjcode,
                    final_output_path,
                    library_id=target_owned_library_id,
                )
            self._finalize_upload_runtime(task, "completed" if (uploaded_files or task.task_metadata.get("upload_runtime")) else final_status)
            persisted_local_root = download_root if os.path.isdir(download_root) else ""
            persisted_local_count = len(success_files) if persisted_local_root else 0
            if session_id:
                self._update_session(
                    session_id,
                    status=final_status,
                    statistics={**session_performance_metrics, "verify_summary": verify_summary, "upload_summary": upload_summary, "download_root": download_root},
                    failure_summary={"failed_resources": failed_files, "verification_failures": verification_failures},
                    local_download_ready=bool(final_status == "completed" and persisted_local_root and persisted_local_count > 0),
                    local_download_root=persisted_local_root,
                    local_downloaded_count=session_success_count if persisted_local_root else 0,
                )
                log_asmr_sync_event(
                    "session_partial_failed" if final_status == "partial_failed" else "session_completed",
                    status="partial_success" if final_status == "partial_failed" else "success",
                    summary=f"{rjcode} 增强下载完成，累计成功 {session_success_count} 个，失败 {len(failed_files)} 个",
                    session_id=session_id,
                    rjcode=rjcode,
                    task_id=task.id,
                    detail={
                        "resource_count": session_selected_resource_count,
                        "success_count": session_success_count,
                        "failed_count": len(failed_files),
                        "downloaded_bytes": total_bytes,
                        "duration_ms": duration_ms,
                        "download_root": download_root,
                        "target_path": final_output_path or upload_options["target_path"],
                        "upload_mode": upload_options["mode"],
                        "uploaded_count": len(uploaded_files),
                        "network_retry_count": max_retries,
                        "uploaded_files": uploaded_files,
                        "final_output_path": final_output_path or None,
                        "target_library_id": postprocess_options.get("target_library_id") or None,
                        "target_subdir": postprocess_options.get("target_subdir") or None,
                        "circle_name": postprocess_options.get("circle_name") or None,
                    },
                )

            task.update_progress(100, f"完成，成功 {len(success_files)} 个文件")
            if failed_files:
                task.task_metadata["failure_reason"] = " / ".join(
                    [str(item.get("reason") or item.get("exception_type") or "未知原因") for item in failed_files[:5]]
                )
            self._append_task_log(task, f"任务完成，成功 {len(success_files)} 个，失败 {len(failed_files)} 个", "success" if not failed_files else "warning")
            return {
                "success": True,
                "download_root": download_root,
                "final_output_path": final_output_path,
                "downloaded_resources": success_files,
                "failed_files": failed_files,
                "uploaded_files": uploaded_files,
                "verification_failures": verification_failures,
            }
        except Exception as exc:
            task.task_metadata["failure_reason"] = str(exc)
            self._finalize_download_runtime(task, "failed")
            self._finalize_upload_runtime(task, "failed")
            self._append_task_log(task, f"任务失败: {str(exc)}", "error")
            if session_id:
                session_selected_resource_count = max(
                    len(selected_resources),
                    int(metadata.get("session_selected_resource_count") or 0),
                )
                session_success_count = max(0, session_selected_resource_count - len(failed_files))
                self._update_session(
                    session_id,
                    status="partial_failed" if session_success_count > 0 else "failed",
                    statistics={
                        **(task.task_metadata.get("performance_metrics") or {}),
                        "selected_resource_count": session_selected_resource_count,
                        "success_count": session_success_count,
                        "failed_count": len(failed_files),
                        "download_root": download_root,
                    },
                    failure_summary={"failed_resources": failed_files, "verification_failures": verification_failures},
                    local_download_ready=False,  # 下载失败/异常，不标记为可入库
                    local_download_root=download_root if os.path.isdir(download_root) else "",
                    local_downloaded_count=session_success_count,
                )
            if os.path.isdir(download_root):
                self._append_task_log(task, "已保留未完成下载片段，后续重试将优先尝试断点续传")
            raise

    def get_dashboard_summary(self) -> Dict[str, Any]:
        from .task_engine import TaskType, get_task_engine

        db = SessionLocal()
        try:
            total_rj = db.query(ASMRWork).count()
            total_resources = db.query(ASMRResourceRecord).count()
            downloaded_count = db.query(ASMRResourceRecord).filter(ASMRResourceRecord.download_status.in_(["downloaded", "uploaded"])).count()
            uploaded_count = db.query(ASMRResourceRecord).filter(ASMRResourceRecord.download_status == "uploaded").count()
            latest_items = db.query(ASMRResourceRecord).order_by(ASMRResourceRecord.updated_at.desc()).limit(8).all()
            latest_sessions = db.query(ASMRDownloadSession).order_by(ASMRDownloadSession.updated_at.desc()).limit(12).all()
            engine = get_task_engine()
            active_tasks = [task for task in engine.get_all_tasks() if task.type == TaskType.ASMR_SYNC_DOWNLOAD]
            return {
                "total_rj": total_rj,
                "total_resources": total_resources,
                "downloaded_resources": downloaded_count,
                "uploaded_resources": uploaded_count,
                "processing_tasks": len([task for task in active_tasks if task.status.value == "processing"]),
                "pending_tasks": len([task for task in active_tasks if task.status.value == "pending"]),
                "failed_tasks": len([task for task in active_tasks if task.status.value == "failed"]),
                "latest_resources": [
                    {
                        "rjcode": item.rjcode,
                        "file_name": item.file_name,
                        "resource_type": item.resource_type,
                        "download_status": item.download_status,
                        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    }
                    for item in latest_items
                ],
                "recent_sessions": [item.to_dict() for item in latest_sessions],
            }
        finally:
            db.close()


_asmr_resource_service: Optional[ASMRResourceService] = None


def get_asmr_resource_service() -> ASMRResourceService:
    global _asmr_resource_service
    if _asmr_resource_service is None:
        _asmr_resource_service = ASMRResourceService()
    return _asmr_resource_service
