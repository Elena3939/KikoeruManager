import asyncio
import hashlib
import logging
import os
import re
import shutil
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_config
from ..models.database import ASMRDownloadSession, ASMRResourceRecord, ASMRWork, SessionLocal

logger = logging.getLogger(__name__)


class ASMRResourceService:
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
    SUBTITLE_EXTENSIONS = {".lrc", ".vtt", ".srt", ".ass", ".ssa"}
    COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    TEXT_EXTENSIONS = {".txt", ".md", ".json", ".cue"}
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

    async def fetch_remote_resources(self, rjcode: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        normalized_rjcode = self.normalize_rjcode(rjcode)
        work_info = await self.asmr_service.fetch_work_info(normalized_rjcode)
        if not work_info:
            raise ValueError(f"未找到作品 {normalized_rjcode}")
        tracks = await self.asmr_service.fetch_track_list(normalized_rjcode)
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
            record.updated_at = datetime.now()
            db.commit()
            return record.to_dict()
        finally:
            db.close()

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            record = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id == session_id).first()
            if record is None:
                raise ValueError("会话不存在")
            return record.to_dict()
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
            elif action == "resume":
                engine.resume_task(task.id)
            else:
                raise ValueError("不支持的会话操作")
        next_status = "paused" if action == "pause" else "downloading"
        updated = self._update_session(session_id, status=next_status)
        log_asmr_sync_event(
            "task_paused" if action == "pause" else "task_resumed",
            summary=f"{updated.get('rjcode') or session_id} 已{'暂停' if action == 'pause' else '恢复'}",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
        )
        return updated

    async def retry_failed_session(self, session_id: str) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event
        from .task_engine import Task, TaskType, get_task_engine

        session = self._get_session(session_id)
        selected_resources = list(session.get("selected_resources") or [])
        failure_summary = dict(session.get("failure_summary") or {})
        failed_paths = {str(item.get("relative_path") or "") for item in failure_summary.get("failed_resources") or []}
        retry_resources = [item for item in selected_resources if str(item.get("relative_path") or "") in failed_paths] or selected_resources
        if not retry_resources:
            raise ValueError("会话中没有可重试资源")

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
                "selected_resources": retry_resources,
                "selected_resource_count": len(retry_resources),
                "queue_priority": int(session.get("queue_priority") or 100),
                "upload_options": {
                    "enabled": str(session.get("upload_mode") or "disabled") != "disabled",
                    "mode": session.get("upload_mode") or "disabled",
                    "target_path": session.get("target_path") or "",
                    "library_id": str((session.get("statistics") or {}).get("upload_library_id") or ""),
                },
                "source_page": session.get("source_page") or "asmr-sync",
                "source_action": "retry_failed_resources",
                "source_label": session.get("source_label") or session.get("rjcode"),
            },
            rjcode=session.get("rjcode"),
        )
        await engine.submit(task)
        updated = self._update_session(session_id, task_id=task.id, status="queued", selected_resources=retry_resources)
        log_asmr_sync_event(
            "task_retried",
            summary=f"{updated.get('rjcode') or session_id} 已重新提交失败资源",
            session_id=session_id,
            rjcode=updated.get("rjcode"),
            task_id=task.id,
            detail={"resource_count": len(retry_resources)},
        )
        return updated

    async def build_download_plan(
        self,
        *,
        rjcode: str,
        folder_path: str = "",
        filters: Optional[Dict[str, Any]] = None,
        refresh: bool = True,
    ) -> Dict[str, Any]:
        del refresh
        from .activity_log_service import log_asmr_sync_event

        normalized_rjcode = self.normalize_rjcode(rjcode)
        try:
            work_info, remote_resources = await self.fetch_remote_resources(normalized_rjcode)
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
            log_asmr_sync_event(
                "enhanced_plan_created",
                summary=f"{normalized_rjcode} 已生成补档计划，候选 {summary['selectable_total']} 个",
                session_id=session_id,
                rjcode=normalized_rjcode,
                detail={"resource_count": summary["selectable_total"], "selected_filters": filters or {}},
            )
            return result
        except Exception as exc:
            log_asmr_sync_event(
                "enhanced_plan_failed",
                status="failed",
                summary=f"{normalized_rjcode} 生成补档计划失败：{str(exc)}",
                rjcode=normalized_rjcode,
                detail={"selected_filters": filters or {}, "exception_type": exc.__class__.__name__},
            )
            raise

    async def _upload_to_local(self, source_path: str, target_root: str, relative_path: str, progress_callback=None) -> str:
        destination = os.path.join(target_root, self._sanitize_relative_path(relative_path))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        uploaded = 0
        total_size = os.path.getsize(source_path) if os.path.exists(source_path) else 0
        with open(source_path, "rb") as src, open(destination, "wb") as dst:
            while True:
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
        from .library_manager import SynologyFileStationClient, get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if not library.synology:
            raise RuntimeError("远程库存未配置群晖参数")
        client = SynologyFileStationClient(library.synology)
        remote_relative = self._sanitize_relative_path(relative_path).replace("\\", "/")
        remote_target = str(PurePosixPath(target_root) / PurePosixPath(remote_relative).parent)
        await manager._ensure_remote_directory(client, remote_target)
        remote_name = PurePosixPath(remote_relative).name
        await client.upload_file(remote_target, source_path, overwrite=True, remote_name=remote_name, progress_callback=progress_callback)
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
        return {
            "enabled": bool(options.get("enabled", False)),
            "target_library_id": str(options.get("target_library_id") or "").strip(),
            "target_subdir": str(options.get("target_subdir") or "").strip().strip("/\\"),
            "naming_mode": str(options.get("naming_mode") or "api").strip().lower() or "api",
            "classify_mode": str(options.get("classify_mode") or "circle").strip().lower() or "circle",
            "circle_name": str(options.get("circle_name") or task_metadata.get("circle_name") or "").strip(),
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
        shutil.move(str(current_path), str(target_path))
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
        from .library_manager import SynologyFileStationClient, get_library_manager
        from .metadata_service import MetadataService
        from .task_engine import Task, TaskType

        config = get_config()
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
        task.update_progress(97, "API 命名")
        renamed_root = download_root
        if postprocess_options.get("naming_mode") == "api":
            renamed_root = await self._api_rename_download_root(download_root, rjcode, final_metadata)

        task.update_progress(98, "按社团入库")
        circle_dir = self._sanitize_folder_name(circle_name or final_metadata.get("maker_name") or "未分类社团", "未分类社团")
        target_subdir = str(postprocess_options.get("target_subdir") or "").strip().strip("/\\")
        manager = get_library_manager()
        target_library_id = str(postprocess_options.get("target_library_id") or "").strip()
        classifier = SmartClassifier()

        if target_library_id:
            target_library = manager.get_library_definition(target_library_id)
            if target_library and target_library.type != "local":
                relative_parts = [part for part in [target_subdir, circle_dir] if part]
                relative_target_dir = "/".join(relative_parts)
                client = SynologyFileStationClient(target_library.synology)
                target_root = PurePosixPath(target_library.root_path)
                if relative_target_dir:
                    target_root = target_root / relative_target_dir
                remote_root = str(target_root / os.path.basename(renamed_root))
                await manager._ensure_remote_directory(client, str(target_root))
                await client.create_folder(str(target_root), os.path.basename(renamed_root))
                file_paths = []
                for root, _, files in os.walk(renamed_root):
                    for filename in files:
                        file_paths.append(os.path.join(root, filename))
                total_upload_files = max(len(file_paths), 1)
                upload_index = 0
                upload_progress_state = {}
                for local_file in file_paths:
                    upload_index += 1
                    relative_file = os.path.relpath(local_file, renamed_root).replace("\\", "/")
                    remote_dir = str(PurePosixPath(remote_root) / PurePosixPath(relative_file).parent)
                    await manager._ensure_remote_directory(client, remote_dir)
                    file_name = os.path.basename(local_file)
                    self._append_task_log(task, f"入库上传 {upload_index}/{total_upload_files}: {relative_file}")
                    def sync_progress(uploaded_bytes: int, total_bytes: int, name=relative_file, index=upload_index):
                        upload_progress_state[name] = {
                            "name": name,
                            "uploaded": uploaded_bytes,
                            "total": total_bytes,
                            "progress": int(uploaded_bytes / total_bytes * 100) if total_bytes else 0,
                            "index": index,
                            "relative_path": name,
                            "stage": "library_upload",
                        }
                        task.task_metadata["upload_files"] = sorted(upload_progress_state.values(), key=lambda item: item.get("index") or 0)
                        task.current_step = f"入库上传 {index}/{total_upload_files}: {file_name}"
                    await client.upload_file(remote_dir, local_file, overwrite=True, remote_name=file_name, progress_callback=sync_progress)
                    uploaded_files = list(task.task_metadata.get("uploaded_files") or [])
                    uploaded_files.append({
                        "name": relative_file,
                        "upload_path": str(PurePosixPath(remote_root) / PurePosixPath(relative_file)),
                        "relative_path": relative_file,
                        "size_bytes": os.path.getsize(local_file) if os.path.exists(local_file) else 0,
                    })
                    task.task_metadata["uploaded_files"] = uploaded_files[-200:]
                    self._append_task_log(task, f"入库完成: {relative_file}")
                final_path = remote_root
                shutil.rmtree(renamed_root, ignore_errors=True)
                return final_path
            if target_library:
                target_root = target_library.root_path
            else:
                target_root = config.storage.library_path
        else:
            target_root = config.storage.library_path

        target_parts = [part for part in [target_root, target_subdir, circle_dir] if part]
        target_dir = os.path.join(*target_parts)
        return classifier._move_with_rename(renamed_root, target_dir)

    async def process_download_task(self, task) -> Dict[str, Any]:
        from .activity_log_service import log_asmr_sync_event

        config = get_config()
        metadata = dict(task.task_metadata or {})
        rjcode = self.normalize_rjcode(metadata.get("rjcode") or task.rjcode or "")
        session_id = str(metadata.get("session_id") or "").strip()
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
        per_session_concurrency = max(1, int(getattr(config.asmr_sync, "enhanced_per_session_concurrency", 3) or 3))

        task.task_metadata["download_files"] = []
        task.task_metadata["upload_files"] = []
        task.task_metadata["uploaded_files"] = []
        task.task_metadata["verification_failures"] = []
        task.task_metadata["failed_files"] = []
        task.task_metadata["progress_log"] = list(task.task_metadata.get("progress_log") or [])
        task.task_metadata["download_mode"] = "enhanced"
        task.task_metadata["session_id"] = session_id

        temp_root = os.path.join(config.storage.temp_path, "asmr_enhanced")
        os.makedirs(temp_root, exist_ok=True)
        download_base_path = str(metadata.get("download_base_path") or "").strip()
        download_root = str(metadata.get("download_root") or "").strip()
        if not download_root:
            if download_base_path:
                download_root = os.path.join(download_base_path, f"{rjcode}_{task.id[:8]}")
            else:
                download_root = os.path.join(temp_root, f"{rjcode}_{task.id[:8]}")
        os.makedirs(download_root, exist_ok=True)

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

        if session_id:
            self._update_session(
                session_id,
                task_id=task.id,
                status="queued",
                target_path=upload_options["target_path"],
                upload_mode=upload_options["mode"],
                selected_resources=selected_resources,
            )
            log_asmr_sync_event(
                "session_started",
                summary=f"{rjcode} 已开始增强下载，共 {len(selected_resources)} 个资源",
                session_id=session_id,
                rjcode=rjcode,
                task_id=task.id,
                detail={"resource_count": len(selected_resources), "upload_mode": upload_options["mode"], "target_path": upload_options["target_path"]},
            )
        self._append_task_log(task, f"{rjcode} 已开始增强下载，共 {len(selected_resources)} 个资源")

        async def handle_resource(index: int, resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            nonlocal completed_count
            await task.wait_if_paused()
            if task.is_cancelled():
                raise RuntimeError("用户取消")

            relative_path = str(resource.get("relative_path") or resource.get("file_name") or f"file_{index:03d}.bin")
            display_name = str(resource.get("file_name") or os.path.basename(relative_path))
            destination = os.path.join(download_root, self._sanitize_relative_path(relative_path))
            remote_url = str(resource.get("remote_url") or "")

            async with semaphore:
                if session_id:
                    self._update_session(session_id, status="downloading")

                def file_progress_callback(downloaded_bytes: int, total_bytes: int, name=display_name, file_index=index):
                    progress_state[name] = {
                        "name": name,
                        "downloaded": downloaded_bytes,
                        "total": total_bytes,
                        "progress": int(downloaded_bytes / total_bytes * 100) if total_bytes else 0,
                        "index": file_index,
                        "total_files": total_files,
                        "relative_path": relative_path,
                    }
                    task.task_metadata["download_files"] = sorted(progress_state.values(), key=lambda item: item.get("index") or 0)
                    task.current_step = f"下载中 {file_index}/{total_files}: {name}"

                if not remote_url:
                    return {"name": display_name, "relative_path": relative_path, "reason": "缺少下载地址", "resource": resource}

                ok = await self.asmr_service.download_file(
                    remote_url,
                    destination,
                    progress_callback=file_progress_callback,
                    max_retries=max_retries,
                    timeout=timeout,
                )
                if not ok:
                    return {"name": display_name, "relative_path": relative_path, "reason": "下载失败", "resource": resource}
                self._append_task_log(task, f"{display_name} 下载完成")

                if session_id:
                    self._update_session(session_id, status="verifying")
                checksum_md5 = self._compute_md5(destination)
                expected_md5 = str(resource.get("checksum_md5") or "").strip().lower()
                verify_status = "skipped"
                verify_ok = True
                if verify_md5 and expected_md5:
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
                if upload_options["enabled"]:
                    if session_id:
                        self._update_session(session_id, status="uploading")
                    def upload_progress_callback(uploaded_bytes: int, total_bytes: int, name=display_name, file_index=index):
                        upload_progress_state[name] = {
                            "name": name,
                            "uploaded": uploaded_bytes,
                            "total": total_bytes,
                            "progress": int(uploaded_bytes / total_bytes * 100) if total_bytes else 0,
                            "index": file_index,
                            "relative_path": relative_path,
                        }
                        task.task_metadata["upload_files"] = sorted(upload_progress_state.values(), key=lambda item: item.get("index") or 0)
                        task.current_step = f"上传中 {file_index}/{total_files}: {name}"
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

            duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
            total_bytes = sum(int(item.get("size_bytes") or 0) for item in success_files)
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
            task.task_metadata.update(
                {
                    "download_root": download_root,
                    "downloaded_resources": success_files,
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
                        "average_speed_bytes": int(total_bytes / max(duration_ms / 1000, 1)) if total_bytes else 0,
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
                        "local_path": "",
                        "upload_path": "",
                        "download_status": "failed",
                        "match_status": "missing_remote" if resource.get("exists_locally") is False else "matched",
                        "verify_status": "pending",
                        "upload_status": "pending",
                        "missing_reason": str(item.get("reason") or ""),
                        "last_error": str(item.get("reason") or ""),
                        "session_id": session_id,
                        "retry_count": max_retries,
                    }
                )
            self._upsert_work_record(rjcode, work_info, status="downloaded" if success_files else "failed")
            self._upsert_resource_records(rjcode, work_info, persisted_resources, session_id=session_id)

            if not success_files:
                if session_id:
                    self._update_session(
                        session_id,
                        status="failed",
                        statistics=task.task_metadata.get("performance_metrics"),
                        failure_summary={"failed_resources": failed_files},
                    )
                    log_asmr_sync_event(
                        "session_partial_failed",
                        status="failed",
                        summary=f"{rjcode} 下载失败，没有任何文件成功",
                        session_id=session_id,
                        rjcode=rjcode,
                        task_id=task.id,
                        detail={"resource_count": len(selected_resources), "target_path": upload_options["target_path"], "network_retry_count": max_retries, "exception_type": "all_failed"},
                    )
                raise ValueError("没有任何文件下载成功")

            if postprocess_options.get("enabled"):
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

            final_status = "partial_failed" if failed_files or verification_failures else "completed"
            if session_id:
                self._update_session(
                    session_id,
                    status=final_status,
                    statistics={**(task.task_metadata.get("performance_metrics") or {}), "verify_summary": verify_summary, "upload_summary": upload_summary},
                    failure_summary={"failed_resources": failed_files, "verification_failures": verification_failures},
                )
                log_asmr_sync_event(
                    "session_partial_failed" if final_status == "partial_failed" else "session_completed",
                    status="partial_success" if final_status == "partial_failed" else "success",
                    summary=f"{rjcode} 增强下载完成，成功 {len(success_files)} 个，失败 {len(failed_files)} 个",
                    session_id=session_id,
                    rjcode=rjcode,
                    task_id=task.id,
                    detail={
                        "resource_count": len(selected_resources),
                        "success_count": len(success_files),
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
            self._append_task_log(task, f"任务失败: {str(exc)}", "error")
            if session_id:
                self._update_session(
                    session_id,
                    status="failed",
                    statistics=task.task_metadata.get("performance_metrics") or {},
                    failure_summary={"failed_resources": failed_files, "verification_failures": verification_failures},
                )
            if not success_files and os.path.isdir(download_root):
                shutil.rmtree(download_root, ignore_errors=True)
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
