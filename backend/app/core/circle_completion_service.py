from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import aiohttp

from ..config.settings import get_config
from ..models.database import (
    ASMRWork,
    CircleCatalog,
    CircleWork,
    LibraryOwnedWork,
    LibrarySnapshot,
    SessionLocal,
    WorkCanonicalLink,
    WorkMetadata,
)
from .activity_log_service import log_circle_completion_event
from .asmr_download_service import get_asmr_download_service
from .asmr_resource_service import get_asmr_resource_service
from .dlsite_service import get_dlsite_service
from .kikoeru_duplicate_service import get_kikoeru_service
from .metadata_service import MetadataService

logger = logging.getLogger(__name__)


class CircleCompletionService:
    DL_SEARCH_URL = "https://www.dlsite.com/maniax/fsr/=/keyword/{keyword}"

    def __init__(self):
        self.metadata_service = MetadataService()
        self.kikoeru_service = get_kikoeru_service()
        self.dlsite_service = get_dlsite_service()
        self.asmr_service = get_asmr_download_service()
        self.asmr_resource_service = get_asmr_resource_service()
        self._index_jobs: Dict[str, Dict[str, Any]] = {}

    def normalize_circle_name(self, value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def normalize_rjcode(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", text, re.IGNORECASE)
        return match.group(0).upper() if match else text

    def _normalize_lang_code(self, value: Any) -> str:
        return str(value or "").strip().upper().replace("-", "_")

    def _work_type_priority(self, work_type: Any) -> int:
        normalized = str(work_type or "").strip().lower()
        if normalized in {"translation", "child_translation"}:
            return 0
        if normalized == "self":
            return 1
        if normalized == "original":
            return 2
        return 3

    def _lang_priority(self, lang: Any) -> int:
        normalized = self._normalize_lang_code(lang)
        if normalized in {"CHI_HANS", "ZH_HANS", "ZH_CN", "CHS", "SIMPLIFIED_CHINESE"}:
            return 0
        if normalized in {"CHI_HANT", "ZH_HANT", "ZH_TW", "CHT", "TRADITIONAL_CHINESE"}:
            return 1
        if normalized and normalized != "JPN":
            return 2
        if normalized == "JPN":
            return 3
        return 4

    def _sort_linked_variants(self, canonical_info: Dict[str, Any], fallback_rjcode: str) -> List[Dict[str, Any]]:
        link_map = dict(canonical_info.get("link_map") or {})
        variants = []
        for linked_rj in set(canonical_info.get("linked_rjcodes") or [fallback_rjcode]):
            normalized_rj = self.normalize_rjcode(linked_rj)
            if not normalized_rj:
                continue
            meta = link_map.get(normalized_rj) or {}
            variants.append({
                "rjcode": normalized_rj,
                "link_type": str(meta.get("link_type") or ("self" if normalized_rj == fallback_rjcode else "")).strip().lower() or "self",
                "lang": self._normalize_lang_code(meta.get("lang")),
            })
        variants.sort(key=lambda item: (
            self._work_type_priority(item["link_type"]),
            self._lang_priority(item["lang"]),
            item["rjcode"],
        ))
        return variants

    def _preferred_variant(self, canonical_info: Dict[str, Any], fallback_rjcode: str) -> Dict[str, Any]:
        variants = self._sort_linked_variants(canonical_info, fallback_rjcode)
        return variants[0] if variants else {
            "rjcode": self.normalize_rjcode(fallback_rjcode),
            "link_type": "self",
            "lang": "",
        }

    def _variant_label(self, link_type: Any, lang: Any) -> str:
        normalized_type = str(link_type or "").strip().lower()
        normalized_lang = self._normalize_lang_code(lang)
        lang_label_map = {
            "CHI_HANS": "简中",
            "ZH_HANS": "简中",
            "ZH_CN": "简中",
            "CHS": "简中",
            "SIMPLIFIED_CHINESE": "简中",
            "CHI_HANT": "繁中",
            "ZH_HANT": "繁中",
            "ZH_TW": "繁中",
            "CHT": "繁中",
            "TRADITIONAL_CHINESE": "繁中",
            "ENG": "英文",
            "EN": "英文",
            "JPN": "日文原版",
        }
        lang_label = lang_label_map.get(normalized_lang, normalized_lang or "未标记")
        if normalized_type in {"translation", "child_translation"}:
            return f"优先版本 {lang_label}"
        if normalized_type == "original":
            return "优先版本 原版"
        return f"优先版本 {lang_label}"

    def _snapshot_job(self, job_id: str) -> Dict[str, Any]:
        job = self._index_jobs.get(job_id)
        if not job:
            raise ValueError("索引任务不存在")
        elapsed_seconds = 0.0
        if job.get("started_at"):
            end_time = job.get("finished_at") or datetime.now()
            elapsed_seconds = max(0.0, (end_time - job["started_at"]).total_seconds())
        return {
            "job_id": job_id,
            "status": job.get("status") or "pending",
            "progress": int(job.get("progress") or 0),
            "current_step": str(job.get("current_step") or "").strip() or "等待中",
            "circle_query": job.get("circle_query") or "",
            "circle_id": job.get("circle_id") or "",
            "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
            "finished_at": job["finished_at"].isoformat() if job.get("finished_at") else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": job.get("error_message"),
            "meta": dict(job.get("meta") or {}),
            "result": dict(job.get("result") or {}),
        }

    def _update_job(
        self,
        job_id: str,
        *,
        progress: Optional[int] = None,
        current_step: Optional[str] = None,
        status: Optional[str] = None,
        circle_id: Optional[str] = None,
        error_message: Optional[str] = None,
        meta_patch: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        job = self._index_jobs.get(job_id)
        if not job:
            return
        if progress is not None:
            job["progress"] = min(100, max(0, int(progress)))
        if current_step is not None:
            job["current_step"] = current_step
        if status is not None:
            job["status"] = status
            if status in {"completed", "failed"}:
                job["finished_at"] = datetime.now()
        if circle_id is not None:
            job["circle_id"] = circle_id
        if error_message is not None:
            job["error_message"] = error_message
        if meta_patch:
            meta = job.setdefault("meta", {})
            meta.update({key: value for key, value in meta_patch.items() if value is not None})
        if result is not None:
            job["result"] = dict(result)

    async def start_index_job(
        self,
        circle_query: str,
        *,
        force_refresh: bool = False,
        include_dlsite: bool = True,
        include_kikoeru: bool = True,
    ) -> Dict[str, Any]:
        circle_query = str(circle_query or "").strip()
        if not circle_query:
            raise ValueError("社团名不能为空")

        job_id = str(uuid.uuid4())
        self._index_jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "current_step": "等待开始",
            "circle_query": circle_query,
            "circle_id": "",
            "started_at": datetime.now(),
            "finished_at": None,
            "error_message": None,
            "meta": {
                "force_refresh": bool(force_refresh),
                "include_dlsite": bool(include_dlsite),
                "include_kikoeru": bool(include_kikoeru),
            },
            "result": {},
        }

        async def runner():
            try:
                self._update_job(job_id, status="processing", progress=1, current_step="准备建立社团索引")

                def report(progress: int, step: str, **meta: Any):
                    self._update_job(job_id, progress=progress, current_step=step, meta_patch=meta)

                result = await self.index_circle_catalog(
                    circle_query,
                    force_refresh=force_refresh,
                    include_dlsite=include_dlsite,
                    include_kikoeru=include_kikoeru,
                    progress_callback=report,
                )
                self._update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    current_step="社团索引完成",
                    circle_id=str(result.get("circle_id") or ""),
                    result=result,
                )
            except Exception as exc:
                logger.error("[社团补全] 索引作业失败 job_id=%s", job_id, exc_info=True)
                self._update_job(job_id, status="failed", current_step="社团索引失败", error_message=str(exc))

        asyncio.create_task(runner())
        return self._snapshot_job(job_id)

    def get_index_job(self, job_id: str) -> Dict[str, Any]:
        return self._snapshot_job(str(job_id or "").strip())

    def _guess_kikoeru_rjcode(self, work: Dict[str, Any]) -> str:
        candidates = [
            work.get("sourceWorkno"),
            work.get("source_workno"),
            work.get("workno"),
            work.get("rjcode"),
            work.get("title"),
        ]
        for candidate in candidates:
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized.startswith(("RJ", "BJ", "VJ")):
                return normalized
        try:
            work_id = int(work.get("id") or 0)
        except Exception:
            work_id = 0
        if work_id <= 0:
            return ""
        if work_id < 1_000_000:
            return f"RJ{work_id:06d}"
        return f"RJ{work_id:08d}"

    def resolve_circle_identity(self, maker_id: Any = "", maker_name: Any = "", circle_name: Any = "") -> Dict[str, str]:
        resolved_name = str(maker_name or circle_name or "").strip()
        normalized_name = self.normalize_circle_name(resolved_name)
        resolved_maker_id = str(maker_id or "").strip()
        circle_id = resolved_maker_id or f"name:{normalized_name}" if normalized_name else ""
        return {
            "circle_id": circle_id,
            "circle_name": resolved_name,
            "circle_name_normalized": normalized_name,
            "maker_id": resolved_maker_id,
        }

    async def resolve_canonical_rj(self, rjcode: str, refresh: bool = False) -> Dict[str, Any]:
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return {
                "canonical_rjcode": "",
                "linked_rjcodes": [],
                "link_map": {},
            }

        db = SessionLocal()
        try:
            if not refresh:
                rows = (
                    db.query(WorkCanonicalLink)
                    .filter(
                        (WorkCanonicalLink.linked_rjcode == normalized_rj)
                        | (WorkCanonicalLink.canonical_rjcode == normalized_rj)
                    )
                    .all()
                )
                if rows:
                    canonical = next((row.canonical_rjcode for row in rows if row.canonical_rjcode), normalized_rj)
                    linked = sorted({row.linked_rjcode for row in rows if row.linked_rjcode})
                    return {
                        "canonical_rjcode": canonical,
                        "linked_rjcodes": linked,
                        "link_map": {
                            row.linked_rjcode: {
                                "link_type": row.link_type,
                                "lang": row.lang,
                            }
                            for row in rows
                            if row.linked_rjcode
                        },
                    }
        finally:
            db.close()

        linked_map: Dict[str, Any] = {}
        try:
            linked_map = await self.dlsite_service.get_linked_works(normalized_rj)
        except Exception as exc:
            logger.warning("[社团补全] 获取关联链失败 %s: %s", normalized_rj, exc)

        canonical_rjcode = normalized_rj
        link_rows: List[Dict[str, str]] = []
        if linked_map:
            for linked_rj, linked_work in linked_map.items():
                linked_rj_norm = self.normalize_rjcode(linked_rj)
                if not linked_rj_norm:
                    continue
                work_type = str(getattr(linked_work, "work_type", "") or "linked").strip() or "linked"
                lang = str(getattr(linked_work, "lang", "") or "").strip()
                if work_type == "original":
                    canonical_rjcode = linked_rj_norm
                link_rows.append({
                    "linked_rjcode": linked_rj_norm,
                    "link_type": work_type,
                    "lang": lang,
                })
        if not link_rows:
            link_rows = [{"linked_rjcode": normalized_rj, "link_type": "self", "lang": ""}]

        db = SessionLocal()
        try:
            db.query(WorkCanonicalLink).filter(
                (WorkCanonicalLink.canonical_rjcode == canonical_rjcode)
                | (WorkCanonicalLink.linked_rjcode.in_([row["linked_rjcode"] for row in link_rows]))
            ).delete(synchronize_session=False)
            for row in link_rows:
                db.add(WorkCanonicalLink(
                    id=str(uuid.uuid4()),
                    canonical_rjcode=canonical_rjcode,
                    linked_rjcode=row["linked_rjcode"],
                    link_type=row["link_type"],
                    lang=row["lang"],
                    cached_at=datetime.now(),
                ))
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 写入 canonical 链失败 %s", normalized_rj, exc_info=True)
        finally:
            db.close()

        return {
            "canonical_rjcode": canonical_rjcode,
            "linked_rjcodes": sorted({row["linked_rjcode"] for row in link_rows}),
            "link_map": {
                row["linked_rjcode"]: {
                    "link_type": row["link_type"],
                    "lang": row["lang"],
                }
                for row in link_rows
            },
        }

    async def _fetch_metadata_dict(self, rjcode: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            cached = db.query(WorkMetadata).filter(WorkMetadata.rjcode == rjcode).first()
            if cached:
                return cached.to_dict()
        finally:
            db.close()
        fake_task = type("FakeTask", (), {"task_metadata": {"rjcode": rjcode}, "rjcode": rjcode, "update_progress": lambda *args, **kwargs: None})()
        return await self.metadata_service.fetch(rjcode, fake_task)

    async def _probe_kikoeru_owned_state(self, probe_rjcode: str) -> bool:
        normalized_rj = self.normalize_rjcode(probe_rjcode)
        if not normalized_rj:
            return False
        try:
            results = await self.kikoeru_service.check_duplicate_with_linkages(normalized_rj, use_cache=True)
        except Exception:
            logger.warning("[社团补全] Kikoeru 拥有态补查失败 %s", normalized_rj, exc_info=True)
            return False
        for result in (results or {}).values():
            if getattr(result, "is_found", False):
                return True
        return False

    async def _search_dlsite_circle_works(self, keyword: str, max_pages: int = 2) -> List[str]:
        session = aiohttp.ClientSession()
        found: List[str] = []
        seen = set()
        try:
            for page in range(1, max_pages + 1):
                suffix = "" if page == 1 else f"/page/{page}"
                url = f"{self.DL_SEARCH_URL.format(keyword=quote(keyword))}{suffix}"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as response:
                        if response.status != 200:
                            break
                        text = await response.text()
                except Exception as exc:
                    logger.warning("[社团补全] DLsite 社团搜索失败 keyword=%s page=%s: %s", keyword, page, exc)
                    break
                matches = re.findall(r"[RVB]J\d{6,8}", text, re.IGNORECASE)
                new_count = 0
                for match in matches:
                    normalized = self.normalize_rjcode(match)
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        found.append(normalized)
                        new_count += 1
                if new_count == 0:
                    break
        finally:
            await session.close()
        return found

    async def _collect_dlsite_circle_candidates(
        self,
        circle_query: str,
        maker_id: str = "",
        *,
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_maker_id = str(maker_id or "").strip().upper()
        dlsite_rjcodes: List[str] = []
        source_mode = "keyword"

        if normalized_maker_id:
            try:
                dlsite_rjcodes = await self.dlsite_service.list_circle_worknos_by_maker(normalized_maker_id, language="JPN")
                source_mode = "maker_profile"
                if progress_callback:
                    progress_callback(44, "已抓取 DLsite 社团主页原作列表", dlsite_profile_total=len(dlsite_rjcodes), dlsite_source_mode=source_mode)
            except Exception:
                logger.warning("[社团补全] 按 maker_id 抓取 DLsite 社团主页失败 maker_id=%s", normalized_maker_id, exc_info=True)

        if not dlsite_rjcodes:
            dlsite_rjcodes = await self._search_dlsite_circle_works(circle_query)
            if progress_callback:
                progress_callback(44, "已回退关键字搜索 DLsite", dlsite_profile_total=len(dlsite_rjcodes), dlsite_source_mode=source_mode)

        candidates: List[Dict[str, Any]] = []
        total_rjcodes = max(1, len(dlsite_rjcodes))
        for index, rjcode in enumerate(dlsite_rjcodes, start=1):
            try:
                meta = await self._fetch_metadata_dict(rjcode)
            except Exception:
                meta = {"rjcode": rjcode}
            maker_name = str(meta.get("maker_name") or "").strip()
            if maker_name and self.normalize_circle_name(circle_query) not in self.normalize_circle_name(maker_name) and not normalized_maker_id:
                continue
            candidates.append({
                "rjcode": rjcode,
                "title": meta.get("work_name") or "",
                "maker_id": meta.get("maker_id") or normalized_maker_id or "",
                "maker_name": maker_name or circle_query,
                "source": "dlsite",
            })
            if progress_callback and (index == total_rjcodes or index % 25 == 0):
                progress_callback(
                    44 + int((index / total_rjcodes) * 8),
                    f"解析 DLsite 社团作品 {index}/{total_rjcodes}",
                    dlsite_profile_total=len(dlsite_rjcodes),
                    dlsite_candidates_count=len(candidates),
                    dlsite_source_mode=source_mode,
                )
        return candidates

    async def _collect_local_circle_candidates(self, circle_query: str) -> List[Dict[str, Any]]:
        normalized = self.normalize_circle_name(circle_query)
        db = SessionLocal()
        try:
            rows = (
                db.query(WorkMetadata)
                .filter(WorkMetadata.maker_name.isnot(None))
                .all()
            )
            results = []
            for row in rows:
                maker_name = str(row.maker_name or "").strip()
                maker_id = str(row.maker_id or "").strip()
                if normalized and normalized not in self.normalize_circle_name(maker_name):
                    continue
                results.append({
                    "rjcode": self.normalize_rjcode(row.rjcode),
                    "title": row.work_name,
                    "maker_id": maker_id,
                    "maker_name": maker_name,
                    "source": "local",
                })
            return results
        finally:
            db.close()

    async def sync_local_owned_index(self) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            snapshots = db.query(LibrarySnapshot).all()
        finally:
            db.close()

        merged: Dict[str, Dict[str, Any]] = {}
        for snapshot in snapshots:
            rjcode = self.normalize_rjcode(snapshot.rjcode)
            if not rjcode:
                continue
            canonical_info = await self.resolve_canonical_rj(rjcode)
            canonical = canonical_info["canonical_rjcode"] or rjcode
            bucket = merged.setdefault(canonical, {
                "owned_rjcodes": set(),
                "primary_folder_path": snapshot.folder_path,
                "folder_count": 0,
            })
            bucket["owned_rjcodes"].add(rjcode)
            bucket["folder_count"] += 1

        db = SessionLocal()
        try:
            db.query(LibraryOwnedWork).delete()
            for canonical, info in merged.items():
                db.add(LibraryOwnedWork(
                    canonical_rjcode=canonical,
                    owned_rjcodes=sorted(info["owned_rjcodes"]),
                    primary_folder_path=info["primary_folder_path"],
                    folder_count=info["folder_count"],
                    updated_at=datetime.now(),
                ))
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 重建本地拥有态失败", exc_info=True)
            raise
        finally:
            db.close()
        return {"owned_count": len(merged)}

    async def sync_owned_for_rj(self, rjcode: str, folder_path: str = "", library_id: str = "") -> None:
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return
        canonical_info = await self.resolve_canonical_rj(normalized_rj)
        canonical = canonical_info["canonical_rjcode"] or normalized_rj

        db = SessionLocal()
        try:
            row = db.query(LibraryOwnedWork).filter(LibraryOwnedWork.canonical_rjcode == canonical).first()
            owned_rjcodes = set(row.owned_rjcodes or []) if row else set()
            owned_rjcodes.add(normalized_rj)
            if row is None:
                row = LibraryOwnedWork(canonical_rjcode=canonical)
                db.add(row)
            row.owned_rjcodes = sorted(owned_rjcodes)
            row.primary_folder_path = folder_path or row.primary_folder_path
            row.library_id = library_id or row.library_id
            row.folder_count = max(int(row.folder_count or 0), 1)
            row.updated_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 增量更新拥有态失败 %s", normalized_rj, exc_info=True)
        finally:
            db.close()

    async def index_circle_catalog(
        self,
        circle_query: str,
        *,
        force_refresh: bool = False,
        include_dlsite: bool = True,
        include_kikoeru: bool = True,
        progress_callback: Optional[Callable[..., None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        circle_query = str(circle_query or "").strip()
        if not circle_query:
            raise ValueError("社团名不能为空")

        def ensure_not_cancelled():
            if cancel_callback and cancel_callback():
                raise asyncio.CancelledError()

        def report(progress: int, step: str, **meta: Any):
            ensure_not_cancelled()
            if progress_callback:
                try:
                    progress_callback(progress, step, **meta)
                except Exception:
                    logger.warning("[社团补全] 更新进度回调失败", exc_info=True)

        report(5, "同步本地拥有态索引", circle_query=circle_query)
        await self.sync_local_owned_index()
        ensure_not_cancelled()

        report(12, "收集本地社团候选")
        local_candidates = await self._collect_local_circle_candidates(circle_query)
        kikoeru_candidates: List[Dict[str, Any]] = []
        if include_kikoeru:
            report(24, "查询 Kikoeru 社团作品", local_candidates_count=len(local_candidates))
            for work in await self.kikoeru_service.search_circle_works(circle_query):
                ensure_not_cancelled()
                circle = work.get("circle", {}) if isinstance(work, dict) else {}
                circle_name = circle.get("name", "") if isinstance(circle, dict) else ""
                rjcode = self._guess_kikoeru_rjcode(work)
                if not rjcode:
                    continue
                kikoeru_candidates.append({
                    "rjcode": rjcode,
                    "title": work.get("title", ""),
                    "maker_name": circle_name,
                    "maker_id": "",
                    "source": "kikoeru",
                    "kikoeru_work_id": work.get("id"),
                })

        combined_seed_candidates = local_candidates + kikoeru_candidates
        identity_seed = self.resolve_circle_identity("", circle_query, circle_query)
        if combined_seed_candidates:
            preferred_seed = next((item for item in combined_seed_candidates if item.get("maker_id")), combined_seed_candidates[0])
            identity_seed = self.resolve_circle_identity(preferred_seed.get("maker_id"), preferred_seed.get("maker_name"), circle_query)

        report(
            38,
            "查询 DLsite 社团主页作品",
            local_candidates_count=len(local_candidates),
            kikoeru_candidates_count=len(kikoeru_candidates),
            maker_id=identity_seed["maker_id"],
        )
        dlsite_candidates: List[Dict[str, Any]] = []
        if include_dlsite:
            dlsite_candidates = await self._collect_dlsite_circle_candidates(
                circle_query,
                identity_seed["maker_id"],
                progress_callback=report,
            )
        ensure_not_cancelled()

        combined_candidates = local_candidates + kikoeru_candidates + dlsite_candidates
        report(
            54,
            "归并作品并补全元数据",
            local_candidates_count=len(local_candidates),
            kikoeru_candidates_count=len(kikoeru_candidates),
            dlsite_candidates_count=len(dlsite_candidates),
            combined_candidates_count=len(combined_candidates),
        )
        if not combined_candidates:
            identity = self.resolve_circle_identity("", circle_query, circle_query)
        else:
            preferred = next((item for item in combined_candidates if item.get("maker_id")), combined_candidates[0])
            identity = self.resolve_circle_identity(preferred.get("maker_id"), preferred.get("maker_name"), circle_query)

        circle_id = identity["circle_id"]
        if not circle_id:
            raise ValueError("无法确定社团标识")

        aggregated: Dict[str, Dict[str, Any]] = {}
        total_candidates = max(1, len(combined_candidates))
        metadata_checked = 0
        for item in combined_candidates:
            ensure_not_cancelled()
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                continue
            metadata = {}
            try:
                metadata = await self._fetch_metadata_dict(rjcode)
            except Exception:
                metadata = {}
            canonical_info = await self.resolve_canonical_rj(rjcode, refresh=force_refresh)
            preferred_variant = self._preferred_variant(canonical_info, rjcode)
            canonical = canonical_info["canonical_rjcode"] or rjcode
            bucket = aggregated.setdefault(canonical, {
                "canonical_rjcode": canonical,
                "display_rjcode": preferred_variant["rjcode"] or rjcode,
                "title": str(item.get("title") or metadata.get("work_name") or ""),
                "maker_id": str(metadata.get("maker_id") or item.get("maker_id") or identity["maker_id"] or ""),
                "maker_name": str(metadata.get("maker_name") or item.get("maker_name") or identity["circle_name"] or circle_query),
                "linked_rjcodes": [variant["rjcode"] for variant in self._sort_linked_variants(canonical_info, rjcode)],
                "has_kikoeru": False,
                "has_dlsite": True,
                "has_asmr_one": False,
                "kikoeru_work_id": None,
                "source_flags": set(),
                "preferred_variant_label": self._variant_label(preferred_variant["link_type"], preferred_variant["lang"]),
                "preferred_lang": preferred_variant["lang"],
                "preferred_link_type": preferred_variant["link_type"],
            })
            bucket["display_rjcode"] = bucket["display_rjcode"] or preferred_variant["rjcode"] or rjcode
            bucket["title"] = bucket["title"] or str(item.get("title") or metadata.get("work_name") or "")
            bucket["maker_id"] = bucket["maker_id"] or str(metadata.get("maker_id") or item.get("maker_id") or "")
            bucket["maker_name"] = bucket["maker_name"] or str(metadata.get("maker_name") or item.get("maker_name") or circle_query)
            bucket["linked_rjcodes"] = [variant["rjcode"] for variant in self._sort_linked_variants(
                {
                    "linked_rjcodes": list(set(bucket["linked_rjcodes"]) | set(canonical_info.get("linked_rjcodes") or [rjcode])),
                    "link_map": canonical_info.get("link_map") or {},
                },
                bucket["display_rjcode"] or rjcode,
            )]
            bucket["preferred_variant_label"] = bucket["preferred_variant_label"] or self._variant_label(preferred_variant["link_type"], preferred_variant["lang"])
            bucket["preferred_lang"] = bucket["preferred_lang"] or preferred_variant["lang"]
            bucket["preferred_link_type"] = bucket["preferred_link_type"] or preferred_variant["link_type"]
            source = str(item.get("source") or "").strip()
            if source:
                bucket["source_flags"].add(source)
            if source == "kikoeru":
                bucket["has_kikoeru"] = True
                if item.get("kikoeru_work_id"):
                    bucket["kikoeru_work_id"] = int(item["kikoeru_work_id"])
            if source == "dlsite":
                bucket["has_dlsite"] = True
            if source == "local":
                bucket["source_flags"].add("local")
            bucket["source_flags"].add("dlsite")
            metadata_checked += 1
            report(
                52 + int((metadata_checked / total_candidates) * 18),
                f"整理候选作品 {metadata_checked}/{total_candidates}",
                aggregated_count=len(aggregated),
                metadata_checked_count=metadata_checked,
            )

        if not aggregated:
            db = SessionLocal()
            try:
                row = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
                if row is None:
                    row = CircleCatalog(circle_id=circle_id)
                    db.add(row)
                row.circle_name = identity["circle_name"] or circle_query
                row.circle_name_normalized = identity["circle_name_normalized"]
                row.source_mask = "none"
                row.last_indexed_at = datetime.now()
                db.commit()
            finally:
                db.close()
            report(100, "索引完成", aggregated_count=0)
            return {"circle_id": circle_id, "summary": {"total": 0}, "indexed_counts": {"works": 0}}

        report(74, "检查 asmr.one 可下载状态", aggregated_count=len(aggregated))
        checked_asmr = 0
        asmr_available = 0
        total_aggregated = max(1, len(aggregated))
        for canonical, item in aggregated.items():
            ensure_not_cancelled()
            probe_rj = item["display_rjcode"] or canonical
            try:
                actual_rjcode, work_info = await self.asmr_service.find_best_available_work(probe_rj)
            except Exception:
                actual_rjcode, work_info = None, None
            if actual_rjcode and work_info:
                item["has_asmr_one"] = True
                item["source_flags"].add("asmr_one")
                asmr_available += 1
                actual_norm = self.normalize_rjcode(actual_rjcode)
                if actual_norm:
                    item["linked_rjcodes"] = sorted(set(item["linked_rjcodes"]) | {actual_norm})
            checked_asmr += 1
            report(
                74 + int((checked_asmr / total_aggregated) * 16),
                f"检查可下载资源 {checked_asmr}/{total_aggregated}",
                asmr_checked_count=checked_asmr,
                asmr_available_count=asmr_available,
            )

        report(90, "补查 Kikoeru 服务器拥有态", aggregated_count=len(aggregated))
        checked_kikoeru = 0
        kikoeru_owned = 0
        for canonical, item in aggregated.items():
            ensure_not_cancelled()
            probe_rj = item["display_rjcode"] or canonical
            if not item["has_kikoeru"]:
                item["has_kikoeru"] = await self._probe_kikoeru_owned_state(probe_rj)
                if item["has_kikoeru"]:
                    item["source_flags"].add("kikoeru")
            if item["has_kikoeru"]:
                kikoeru_owned += 1
            checked_kikoeru += 1
            report(
                90 + int((checked_kikoeru / total_aggregated) * 2),
                f"补查服务器拥有态 {checked_kikoeru}/{total_aggregated}",
                kikoeru_checked_count=checked_kikoeru,
                kikoeru_owned_count=kikoeru_owned,
            )

        report(92, "写入社团索引")
        db = SessionLocal()
        try:
            ensure_not_cancelled()
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            if catalog is None:
                catalog = CircleCatalog(circle_id=circle_id)
                db.add(catalog)
            catalog.circle_name = identity["circle_name"] or circle_query
            catalog.circle_name_normalized = identity["circle_name_normalized"]
            catalog.source_mask = ",".join(sorted({flag for item in aggregated.values() for flag in item["source_flags"]}))
            catalog.last_indexed_at = datetime.now()
            catalog.last_local_sync_at = datetime.now()

            existing_rows = {
                row.canonical_rjcode: row
                for row in db.query(CircleWork).filter(CircleWork.circle_id == circle_id).all()
            }
            for canonical, item in aggregated.items():
                row = existing_rows.pop(canonical, None)
                if row is None:
                    row = CircleWork(id=str(uuid.uuid4()), circle_id=circle_id, canonical_rjcode=canonical)
                    db.add(row)
                row.display_rjcode = item["display_rjcode"]
                row.title = item["title"]
                row.maker_id = item["maker_id"]
                row.maker_name = item["maker_name"]
                row.source_mask = ",".join(sorted(item["source_flags"]))
                row.linked_rjcodes = item["linked_rjcodes"]
                row.has_kikoeru = bool(item["has_kikoeru"])
                row.has_dlsite = bool(item["has_dlsite"] or "dlsite" in item["source_flags"])
                row.has_asmr_one = bool(item["has_asmr_one"])
                row.kikoeru_work_id = item["kikoeru_work_id"]
                row.dlsite_cached_at = datetime.now() if row.has_dlsite else row.dlsite_cached_at
                row.asmr_one_cached_at = datetime.now() if row.has_asmr_one else row.asmr_one_cached_at
            for obsolete in existing_rows.values():
                db.delete(obsolete)
            db.commit()
        except Exception:
            db.rollback()
            log_circle_completion_event(
                "index_failed",
                status="failed",
                summary=f"社团索引失败：{circle_query}",
                circle_id=circle_id,
                circle_name=identity["circle_name"] or circle_query,
            )
            raise
        finally:
            db.close()

        report(97, "生成社团视图摘要", circle_id=circle_id)
        summary = await self.build_circle_completion_view(circle_id)
        indexed_counts = {
            "works": len(summary.get("works") or []),
            "local_owned_count": int(summary.get("local_owned_count") or 0),
            "owned_count": int(summary.get("owned_count") or 0),
            "missing_count": int(summary.get("missing_count") or 0),
            "downloadable_count": int(summary.get("downloadable_count") or 0),
            "dl_count": int(summary.get("dl_count") or 0),
        }
        log_circle_completion_event(
            "index_completed",
            summary=(
                f"本地有 {indexed_counts['local_owned_count']} 个 / "
                f"缺失 {indexed_counts['missing_count']} 个 / "
                f"可下载 {indexed_counts['downloadable_count']} 个 / "
                f"DL 有 {indexed_counts['dl_count']} 个"
            ),
            circle_id=circle_id,
            circle_name=identity["circle_name"] or circle_query,
            detail={
                "indexed_counts": indexed_counts,
                "local_owned_count": indexed_counts["local_owned_count"],
                "owned_count": indexed_counts["owned_count"],
                "missing_count": indexed_counts["missing_count"],
                "downloadable_count": indexed_counts["downloadable_count"],
                "dl_count": indexed_counts["dl_count"],
                "works_count": indexed_counts["works"],
                "force_refresh": bool(force_refresh),
                "include_dlsite": bool(include_dlsite),
                "include_kikoeru": bool(include_kikoeru),
            },
        )
        return {
            "circle_id": circle_id,
            "summary": {
                "circle_name": identity["circle_name"] or circle_query,
                **indexed_counts,
            },
            "indexed_counts": indexed_counts,
        }

    async def search_circles(self, keyword: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        normalized = self.normalize_circle_name(keyword)
        db = SessionLocal()
        try:
            rows = db.query(CircleCatalog).order_by(CircleCatalog.last_indexed_at.desc()).all()
            out = []
            for row in rows:
                if normalized:
                    haystack = f"{row.circle_name or ''} {row.circle_id or ''} {row.circle_name_normalized or ''}".lower()
                    if normalized not in haystack:
                        continue
                out.append(row.to_dict())
                if len(out) >= max(1, int(limit)):
                    break
            return out
        finally:
            db.close()

    def _build_filter_skip_reasons(self, resources: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        config = get_config()
        filter_rules = [rule.model_dump() if hasattr(rule, "model_dump") else dict(rule) for rule in (config.filter.rules or [])]
        file_list = []
        path_map = {}
        for item in resources:
            relative_path = str(item.get("relative_path") or item.get("file_name") or "").strip()
            file_list.append({
                "title": str(item.get("file_name") or ""),
                "path": relative_path,
                "type": item.get("resource_type"),
            })
            path_map[relative_path] = item
        allowed = self.asmr_service.filter_files(file_list, filter_rules) if filter_rules else file_list
        allowed_paths = {str(item.get("path") or item.get("title") or "").strip() for item in allowed}
        reasons: Dict[str, List[str]] = defaultdict(list)
        for relative_path, item in path_map.items():
            ext = str(item.get("file_ext") or "").lower()
            if relative_path not in allowed_paths:
                reasons[relative_path].append("命中过滤规则")
            if ext in {".txt", ".json", ".md"}:
                reasons[relative_path].append("扩展名不推荐")
        return reasons

    async def build_circle_completion_view(
        self,
        circle_id_or_query: str,
        *,
        only_missing: bool = False,
        only_downloadable: bool = False,
        include_dl_only: bool = True,
    ) -> Dict[str, Any]:
        circle_id_or_query = str(circle_id_or_query or "").strip()
        if not circle_id_or_query:
            raise ValueError("缺少社团标识")

        db = SessionLocal()
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id_or_query).first()
            if catalog is None:
                normalized = self.normalize_circle_name(circle_id_or_query)
                catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_name_normalized == normalized).first()
            if catalog is None:
                raise ValueError("社团索引不存在")

            owned_rows = {
                row.canonical_rjcode: row
                for row in db.query(LibraryOwnedWork).all()
            }
            works = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == catalog.circle_id)
                .order_by(CircleWork.updated_at.desc())
                .all()
            )
            link_rows = (
                db.query(WorkCanonicalLink)
                .filter(WorkCanonicalLink.canonical_rjcode.in_([row.canonical_rjcode for row in works]))
                .all()
                if works else []
            )
            link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            for link_row in link_rows:
                link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                    "link_type": str(link_row.link_type or ""),
                    "lang": str(link_row.lang or ""),
                }

            items = []
            for row in works:
                owned_row = owned_rows.get(row.canonical_rjcode)
                local_owned = owned_row is not None
                server_owned = bool(row.has_kikoeru)
                has_dlsite = True
                is_unavailable = not server_owned and not bool(row.has_asmr_one)
                if only_missing and server_owned:
                    continue
                if only_downloadable and not row.has_asmr_one:
                    continue
                if not include_dl_only and is_unavailable:
                    continue
                item = row.to_dict()
                item["circle_name"] = catalog.circle_name
                item["owned"] = server_owned
                item["server_owned"] = server_owned
                item["local_owned"] = local_owned
                item["owned_rjcodes"] = list((owned_row.owned_rjcodes or []) if owned_row else [])
                item["primary_folder_path"] = owned_row.primary_folder_path if owned_row else ""
                item["has_dlsite"] = has_dlsite
                item["status_tags"] = [
                    *(["服务器已有"] if server_owned else ["服务器缺失"]),
                    *(["可下载"] if row.has_asmr_one else ["暂不可下载"]),
                ]
                item["download_plan"] = {"rjcode": row.display_rjcode} if row.has_asmr_one else None
                items.append(item)

            result = {
                "circle_id": catalog.circle_id,
                "circle_name": catalog.circle_name,
                "source_mask": catalog.source_mask or "",
                "last_indexed_at": catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None,
                "local_owned_count": sum(1 for item in items if item["local_owned"]),
                "owned_count": sum(1 for item in items if item["server_owned"]),
                "missing_count": sum(1 for item in items if not item["server_owned"]),
                "downloadable_count": sum(1 for item in items if not item["server_owned"] and item["has_asmr_one"]),
                "dl_only_count": sum(1 for item in items if not item["server_owned"] and not item["has_asmr_one"]),
                "dl_count": sum(1 for item in items if item["has_dlsite"]),
                "works": items,
            }
        finally:
            db.close()
        return result

    async def preview_batch_download(self, circle_id: str, canonical_rjcodes: List[str]) -> Dict[str, Any]:
        from ..config.settings import get_config
        from .library_manager import get_library_manager

        db = SessionLocal()
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            if catalog is None:
                raise ValueError("社团不存在")
            rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id, CircleWork.canonical_rjcode.in_(canonical_rjcodes))
                .all()
            )
        finally:
            db.close()

        plans = []
        for row in rows:
            if not row.has_asmr_one:
                continue
            plan = await self.asmr_resource_service.build_download_plan(
                rjcode=row.display_rjcode or row.canonical_rjcode,
                folder_path="",
                filters={},
                refresh=True,
            )
            skip_reasons = self._build_filter_skip_reasons(plan.get("selectable_resources") or [])
            for item in plan.get("selectable_resources") or []:
                reasons = list(skip_reasons.get(str(item.get("relative_path") or ""), []))
                if reasons:
                    item["selected"] = False
                    item["recommended_skip_reasons"] = reasons
            plan["selection_presets"] = self.asmr_resource_service._build_selection_presets(plan.get("selectable_resources") or [])
            plan["circle_id"] = circle_id
            plan["circle_name"] = catalog.circle_name
            plan["canonical_rjcode"] = row.canonical_rjcode
            plan["display_rjcodes"] = row.linked_rjcodes or [row.display_rjcode]
            plans.append(plan)

        manager = get_library_manager()
        libraries = manager.list_libraries()
        default_library = next((item for item in libraries if item.get("is_default")), None) or (libraries[0] if libraries else {})
        download_base_path = os.path.join(get_config().storage.temp_path, "asmr_enhanced")

        return {
            "circle_id": circle_id,
            "circle_name": catalog.circle_name,
            "plans": plans,
            "planned_count": len(plans),
            "download_base_path": download_base_path,
            "default_target_library_id": str(default_library.get("id") or ""),
            "default_target_subdir": "",
        }

    async def list_recent_indexes(self, limit: int = 20) -> List[Dict[str, Any]]:
        return await self.search_circles("", limit=limit)


_circle_completion_service: Optional[CircleCompletionService] = None


def get_circle_completion_service() -> CircleCompletionService:
    global _circle_completion_service
    if _circle_completion_service is None:
        _circle_completion_service = CircleCompletionService()
    return _circle_completion_service
