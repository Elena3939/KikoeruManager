from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import quote


from ..config.settings import get_config
from ..models.database import (
    ASMRDownloadSession,
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
        self._public_variant_cache: Dict[str, bool] = {}
        self._asmr_probe_cache: Dict[str, tuple[str, Optional[Dict[str, Any]]]] = {}
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        self._canonical_cache: Dict[str, Dict[str, Any]] = {}
        self._kikoeru_state_cache: Dict[str, Dict[str, Any]] = {}
        self._local_download_fallback_cache: Dict[str, Any] = {"expires_at": 0.0, "data": {}}

    def normalize_circle_name(self, value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def normalize_rjcode(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", text, re.IGNORECASE)
        return match.group(0).upper() if match else text

    def _normalize_lang_code(self, value: Any) -> str:
        normalized = str(value or "").strip().upper().replace("-", "_")
        alias_map = {
            "CHN": "CHI_HANS",
            "CHI_SIMP": "CHI_HANS",
            "ZH": "CHI_HANS",
            "CN": "CHI_HANS",
            "TWN": "CHI_HANT",
            "CHI_TRAD": "CHI_HANT",
            "TW": "CHI_HANT",
        }
        return alias_map.get(normalized, normalized)

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

    def _is_displayable_variant(self, link_type: Any, lang: Any) -> bool:
        group_key = str(self._variant_group(link_type, lang).get("key") or "").strip()
        return group_key in {"simplified", "traditional", "original"}

    async def _is_public_catalog_variant(self, rjcode: str, *, link_type: Any, lang: Any) -> bool:
        normalized = self.normalize_rjcode(rjcode)
        if not normalized or not self._is_displayable_variant(link_type, lang):
            return False
        cache_key = f"{normalized}:{str(link_type or '').strip().lower()}:{self._normalize_lang_code(lang)}"
        cached = self._public_variant_cache.get(cache_key)
        if cached is not None:
            return cached
        group_key = str(self._variant_group(link_type, lang).get("key") or "").strip()
        try:
            if group_key in {"simplified", "traditional"}:
                result = bool(await self.dlsite_service._is_public_work_available(normalized))
            else:
                result = bool(await self.dlsite_service.get_product_info(normalized))
        except Exception:
            result = False
        self._public_variant_cache[cache_key] = result
        return result

    def _pick_display_variant(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        variants = self._sort_linked_variants(canonical_info, fallback_rjcode)
        allowed = [
            variant for variant in variants
            if self._is_displayable_variant(variant.get("link_type"), variant.get("lang"))
        ]
        metadata_map = metadata_map or {}
        for variant in allowed:
            normalized = self.normalize_rjcode(variant.get("rjcode"))
            title = str((metadata_map.get(normalized) or {}).get("work_name") or "").strip()
            if title:
                return variant
        canonical_rjcode = self.normalize_rjcode(canonical_info.get("canonical_rjcode") or fallback_rjcode)
        for variant in allowed:
            normalized = self.normalize_rjcode(variant.get("rjcode"))
            if normalized == canonical_rjcode or self._variant_group(variant.get("link_type"), variant.get("lang")).get("key") == "original":
                return variant
        if allowed:
            return allowed[0]
        return self._preferred_variant(canonical_info, fallback_rjcode)

    async def _resolve_public_display_title(
        self,
        rjcode: str,
        *,
        link_type: Any,
        lang: Any,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        normalized = self.normalize_rjcode(rjcode)
        if not normalized or not self._is_displayable_variant(link_type, lang):
            return ""
        metadata_map = metadata_map or {}
        cached_title = str((metadata_map.get(normalized) or {}).get("work_name") or "").strip()
        group_key = str(self._variant_group(link_type, lang).get("key") or "").strip()
        if group_key in {"simplified", "traditional"}:
            try:
                fallback = await self.dlsite_service._resolve_translation_page_fallback(normalized)
            except Exception:
                fallback = None
            if self.normalize_rjcode((fallback or {}).get("translation_workno")) != normalized:
                return ""
            if cached_title:
                return cached_title
            try:
                info = await self.dlsite_service.get_product_info(normalized)
            except Exception:
                info = None
            return str((((info or {}).get("product") or {}).get("work_name")) or "").strip()
        return cached_title

    async def _pick_public_display_variant_and_title(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[Dict[str, Any], str]:
        metadata_map = metadata_map or {}
        allowed = await self._list_public_display_variants(
            canonical_info,
            fallback_rjcode,
            metadata_map,
        )
        for variant in allowed:
            title = await self._resolve_public_display_title(
                str(variant.get("rjcode") or ""),
                link_type=variant.get("link_type"),
                lang=variant.get("lang"),
                metadata_map=metadata_map,
            )
            if title:
                return variant, title
        canonical_rjcode = self.normalize_rjcode(canonical_info.get("canonical_rjcode") or fallback_rjcode)
        fallback_variant = next((
            variant for variant in allowed
            if self.normalize_rjcode(variant.get("rjcode")) == canonical_rjcode
            or str(self._variant_group(variant.get("link_type"), variant.get("lang")).get("key") or "").strip() == "original"
        ), None)
        if fallback_variant is None:
            fallback_variant = allowed[0] if allowed else {
                "rjcode": canonical_rjcode,
                "link_type": "original",
                "lang": "JPN",
            }
        fallback_title = str((metadata_map.get(self.normalize_rjcode(fallback_variant.get("rjcode"))) or {}).get("work_name") or "").strip()
        return fallback_variant, fallback_title

    async def _list_public_display_variants(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        metadata_map = metadata_map or {}
        variants = self._sort_linked_variants(canonical_info, fallback_rjcode)
        public_variants: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        original_variant: Optional[Dict[str, Any]] = None
        canonical_rjcode = self.normalize_rjcode(canonical_info.get("canonical_rjcode") or fallback_rjcode)

        for variant in variants:
            normalized = self.normalize_rjcode(variant.get("rjcode"))
            if not normalized or normalized in seen:
                continue
            link_type = variant.get("link_type")
            lang = variant.get("lang")
            if not self._is_displayable_variant(link_type, lang):
                continue
            normalized_variant = {
                "rjcode": normalized,
                "link_type": str(link_type or "").strip().lower() or "self",
                "lang": self._normalize_lang_code(lang),
            }
            group_key = str(self._variant_group(link_type, lang).get("key") or "").strip()
            if group_key == "original" or normalized == canonical_rjcode:
                if original_variant is None:
                    original_variant = normalized_variant
                continue
            title = await self._resolve_public_display_title(
                normalized,
                link_type=link_type,
                lang=lang,
                metadata_map=metadata_map,
            )
            if not title:
                continue
            public_variants.append(normalized_variant)
            seen.add(normalized)

        if original_variant is not None:
            original_code = self.normalize_rjcode(original_variant.get("rjcode"))
            if original_code and original_code not in seen:
                public_variants.append(original_variant)
                seen.add(original_code)
        elif canonical_rjcode and canonical_rjcode not in seen:
            public_variants.append({
                "rjcode": canonical_rjcode,
                "link_type": "original",
                "lang": "JPN",
            })
        return public_variants

    async def _build_public_download_probe_candidates(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_candidates: Optional[List[Any]] = None,
    ) -> List[str]:
        metadata_map = metadata_map or {}
        candidates: List[str] = []
        seen: Set[str] = set()

        def append_candidate(value: Any) -> None:
            normalized = self.normalize_rjcode(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        public_variants = await self._list_public_display_variants(canonical_info, fallback_rjcode, metadata_map)
        for variant in public_variants:
            normalized = self.normalize_rjcode(variant.get("rjcode"))
            if not normalized:
                continue
            if not await self._is_public_catalog_variant(
                normalized,
                link_type=variant.get("link_type"),
                lang=variant.get("lang"),
            ):
                continue
            append_candidate(normalized)

        for candidate in list(extra_candidates or []):
            normalized = self.normalize_rjcode(candidate)
            if not normalized:
                continue
            variant = next((
                item for item in public_variants
                if self.normalize_rjcode(item.get("rjcode")) == normalized
            ), None)
            if variant is None:
                continue
            if not await self._is_public_catalog_variant(
                normalized,
                link_type=variant.get("link_type"),
                lang=variant.get("lang"),
            ):
                continue
            append_candidate(normalized)
        return candidates

    async def _find_public_downloadable_work(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_candidates: Optional[List[Any]] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        cache_key = "|".join(await self._build_public_download_probe_candidates(
            canonical_info,
            fallback_rjcode,
            metadata_map=metadata_map,
            extra_candidates=extra_candidates,
        ))
        if cache_key:
            cached = self._asmr_probe_cache.get(cache_key)
            if cached is not None:
                return cached
        probe_candidates = await self._build_public_download_probe_candidates(
            canonical_info,
            fallback_rjcode,
            metadata_map=metadata_map,
            extra_candidates=extra_candidates,
        )
        for probe_rjcode in probe_candidates:
            try:
                work_info = await self.asmr_service.fetch_work_info(probe_rjcode)
            except Exception:
                work_info = None
            if not work_info:
                continue
            try:
                tracks = await self.asmr_service.fetch_track_list(probe_rjcode)
            except Exception:
                tracks = None
            if tracks:
                result = (probe_rjcode, work_info)
                if cache_key:
                    self._asmr_probe_cache[cache_key] = result
                return result
        result = ("", None)
        if cache_key:
            self._asmr_probe_cache[cache_key] = result
        return result

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

    def _variant_group(self, link_type: Any, lang: Any) -> Dict[str, str]:
        normalized_type = str(link_type or "").strip().lower()
        normalized_lang = self._normalize_lang_code(lang)
        if normalized_lang in {"CHI_HANS", "ZH_HANS", "ZH_CN", "CHS", "SIMPLIFIED_CHINESE"}:
            return {"key": "simplified", "label": "简体优先", "short_label": "简中"}
        if normalized_lang in {"CHI_HANT", "ZH_HANT", "ZH_TW", "CHT", "TRADITIONAL_CHINESE"}:
            return {"key": "traditional", "label": "繁体优先", "short_label": "繁中"}
        if normalized_type == "original" or normalized_lang in {"", "JPN"}:
            return {"key": "original", "label": "原作优先", "short_label": "原作"}
        return {"key": "other", "label": "其他语言", "short_label": "其他"}

    def _infer_variant_badge_from_metadata(self, rjcode: str, metadata_map: Dict[str, Dict[str, Any]]) -> str:
        metadata = metadata_map.get(rjcode) or {}
        title = str(metadata.get("work_name") or "").strip().lower()
        if not title:
            return ""
        simplified_markers = [
            "简体中文版",
            "簡体中文版",
            "简体中文",
            "簡体中文",
            "简中",
            "簡中",
            "chs",
            "chi_hans",
            "simplified chinese",
        ]
        traditional_markers = [
            "繁体中文版",
            "繁體中文版",
            "繁体中文",
            "繁體中文",
            "繁中",
            "cht",
            "chi_hant",
            "traditional chinese",
        ]
        if any(marker in title for marker in simplified_markers):
            return "简中"
        if any(marker in title for marker in traditional_markers):
            return "繁中"
        return ""

    def _load_cached_metadata_map(self, db, rjcodes: List[str]) -> Dict[str, Dict[str, Any]]:
        normalized_codes = []
        for code in rjcodes or []:
            normalized = self.normalize_rjcode(code)
            if normalized and normalized not in normalized_codes:
                normalized_codes.append(normalized)
        if not normalized_codes:
            return {}
        cached_map = {
            code: self._metadata_cache[code]
            for code in normalized_codes
            if code in self._metadata_cache
        }
        missing_codes = [code for code in normalized_codes if code not in cached_map]
        if not missing_codes:
            return cached_map
        rows = db.query(WorkMetadata).filter(WorkMetadata.rjcode.in_(missing_codes)).all()
        db_map = {
            str(row.rjcode or "").strip().upper(): row.to_dict()
            for row in rows
            if str(row.rjcode or "").strip()
        }
        self._metadata_cache.update(db_map)
        cached_map.update(db_map)
        return cached_map

    def _build_circle_index_log_detail(
        self,
        summary: Dict[str, Any],
        *,
        force_refresh: bool,
        include_dlsite: bool,
        include_kikoeru: bool,
    ) -> Dict[str, Any]:
        works = list(summary.get("works") or [])
        source_breakdown = [
            {"key": "kikoeru", "label": "Kikoeru", "count": sum(1 for item in works if item.get("server_owned"))},
            {"key": "dlsite", "label": "DLsite", "count": sum(1 for item in works if item.get("has_dlsite"))},
            {"key": "asmr_one", "label": "asmr.one", "count": sum(1 for item in works if item.get("has_asmr_one"))},
            {"key": "local_downloaded", "label": "本地已下载", "count": sum(1 for item in works if item.get("local_download_ready"))},
            {"key": "downloadable", "label": "可下载", "count": sum(1 for item in works if not item.get("server_owned") and item.get("has_asmr_one"))},
            {"key": "dl_only", "label": "暂无来源", "count": sum(1 for item in works if not item.get("server_owned") and item.get("has_dlsite") and not item.get("has_asmr_one"))},
        ]
        section_meta = {
            "simplified": {"label": "简体优先", "description": "优先命中简体中文版本"},
            "traditional": {"label": "繁体优先", "description": "未命中简体时回落到繁体版本"},
            "original": {"label": "原作优先", "description": "未命中翻译作时回落到原作版本"},
            "other": {"label": "其他语言", "description": "存在其他语言版本，但不属于简繁原作优先链"},
        }
        grouped_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in works:
            preferred_variant = item.get("preferred_variant") if isinstance(item.get("preferred_variant"), dict) else {}
            group_key = str(preferred_variant.get("group_key") or "original")
            source_compare = item.get("source_compare") if isinstance(item.get("source_compare"), dict) else {}
            grouped_rows[group_key].append({
                "canonical_rjcode": item.get("canonical_rjcode"),
                "work_rjcode": source_compare.get("work_rjcode") or item.get("canonical_rjcode"),
                "display_rjcode": item.get("display_rjcode"),
                "asmr_available_rjcode": item.get("asmr_available_rjcode"),
                "title": item.get("title"),
                "preferred_variant_label": preferred_variant.get("label") or "优先版本 未标记",
                "status_label": "本地已下载" if item.get("local_download_ready") else ("服务器已有" if item.get("server_owned") else ("可下载" if item.get("has_asmr_one") else "暂无来源")),
                "status_key": "local" if item.get("local_download_ready") else ("owned" if item.get("server_owned") else ("downloadable" if item.get("has_asmr_one") else "dl_only")),
                "source_compare": source_compare,
            })
        work_sections = []
        for group_key in ["simplified", "traditional", "original", "other"]:
            rows = grouped_rows.get(group_key) or []
            if not rows:
                continue
            rows.sort(key=lambda item: (str(item.get("canonical_rjcode") or ""), str(item.get("title") or "")))
            work_sections.append({
                "key": group_key,
                "label": section_meta[group_key]["label"],
                "description": section_meta[group_key]["description"],
                "count": len(rows),
                "rows": rows,
            })
        return {
            "priority_rule": "简体 > 繁体 > 原作",
            "source_breakdown": source_breakdown,
            "work_sections": work_sections,
            "force_refresh": bool(force_refresh),
            "include_dlsite": bool(include_dlsite),
            "include_kikoeru": bool(include_kikoeru),
        }

    def _build_source_compare(
        self,
        item: Dict[str, Any],
        canonical_info: Dict[str, Any],
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        original_rjcode = str(item.get("canonical_rjcode") or "").strip()
        preferred_variant = item.get("preferred_variant") if isinstance(item.get("preferred_variant"), dict) else {}
        preferred_rjcode = str(preferred_variant.get("rjcode") or item.get("display_rjcode") or original_rjcode).strip()
        kikoeru_found_rjcodes = []
        for code in list(item.get("kikoeru_found_rjcodes") or []):
            normalized = self.normalize_rjcode(code)
            if normalized and normalized not in kikoeru_found_rjcodes:
                kikoeru_found_rjcodes.append(normalized)
        kikoeru_subtitle_rjcodes = []
        for code in list(item.get("kikoeru_subtitle_rjcodes") or []):
            normalized = self.normalize_rjcode(code)
            if normalized and normalized not in kikoeru_subtitle_rjcodes:
                kikoeru_subtitle_rjcodes.append(normalized)
        linked_rjcodes = [
            variant["rjcode"]
            for variant in self._sort_linked_variants(canonical_info, preferred_rjcode or original_rjcode)
            if variant.get("rjcode")
        ]
        sorted_variants = self._sort_linked_variants(canonical_info, preferred_rjcode or original_rjcode)
        link_map = dict(canonical_info.get("link_map") or {})

        def resolve_variant_badge(rjcode: str) -> str:
            normalized = self.normalize_rjcode(rjcode)
            if not normalized or normalized == original_rjcode:
                return ""
            meta = link_map.get(normalized) or {}
            group = self._variant_group(meta.get("link_type"), meta.get("lang"))
            short_label = str(group.get("short_label") or "").strip()
            return short_label if short_label not in {"原作", "其他", ""} else ""

        def collect_variant_badges(rjcodes: List[str]) -> List[str]:
            badges: List[str] = []
            for code in rjcodes:
                badge = resolve_variant_badge(code)
                if not badge and metadata_map:
                    badge = self._infer_variant_badge_from_metadata(code, metadata_map)
                if badge and badge not in badges:
                    badges.append(badge)
            return badges

        asmr_available_rjcode = self.normalize_rjcode(item.get("asmr_available_rjcode"))
        kikoeru_primary = ""
        for variant in sorted_variants:
            candidate = self.normalize_rjcode(variant.get("rjcode"))
            if candidate and candidate in kikoeru_found_rjcodes:
                kikoeru_primary = candidate
                break
        if not kikoeru_primary:
            kikoeru_primary = original_rjcode if original_rjcode in kikoeru_found_rjcodes else (kikoeru_found_rjcodes[0] if kikoeru_found_rjcodes else "")
        kikoeru_variant_badges = collect_variant_badges(kikoeru_found_rjcodes)
        ordered_variant_badges: List[str] = []
        for badge in ["简中", "繁中"]:
            if badge in kikoeru_variant_badges and badge not in ordered_variant_badges:
                ordered_variant_badges.append(badge)
        kikoeru_tags: List[str] = []
        has_translation_variant = bool(ordered_variant_badges)
        if not has_translation_variant and kikoeru_subtitle_rjcodes:
            kikoeru_tags.append("字幕")
        matched_server_rjcodes = list(kikoeru_found_rjcodes)
        matched_server_primary = kikoeru_primary or (matched_server_rjcodes[0] if matched_server_rjcodes else "")
        subtitle_present = bool(kikoeru_subtitle_rjcodes)
        return {
            "work_rjcode": original_rjcode,
            "preferred_rjcode": preferred_rjcode,
            "kikoeru": {
                "primary_rjcode": matched_server_primary,
                "matched_rjcode": matched_server_primary,
                "matched_rjcodes": matched_server_rjcodes,
                "all_rjcodes": matched_server_rjcodes,
                "subtitle_rjcodes": kikoeru_subtitle_rjcodes,
                "subtitle_present": subtitle_present,
                "primary_badge": resolve_variant_badge(matched_server_primary),
                "variant_badges": ordered_variant_badges,
                "tags": kikoeru_tags,
                "status": "owned" if matched_server_rjcodes else "missing",
            },
            "dlsite": {
                "all_rjcodes": linked_rjcodes,
                "status": "available" if linked_rjcodes else "missing",
            },
            "asmr_one": {
                "primary_rjcode": asmr_available_rjcode,
                "all_rjcodes": [asmr_available_rjcode] if asmr_available_rjcode else [],
                "primary_badge": resolve_variant_badge(asmr_available_rjcode),
                "status": "available" if asmr_available_rjcode else "missing",
            },
        }

    def _build_local_download_session_map(self, db, works: List[CircleWork], link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        lookup_rjcodes: List[str] = []
        canonical_candidates: Dict[str, List[str]] = {}
        for row in works or []:
            canonical = self.normalize_rjcode(row.canonical_rjcode)
            linked_codes = [canonical]
            for code in list(row.linked_rjcodes or []):
                normalized = self.normalize_rjcode(code)
                if normalized and normalized not in linked_codes:
                    linked_codes.append(normalized)
            link_map = link_map_by_canonical.get(row.canonical_rjcode) or {}
            for code in link_map.keys():
                normalized = self.normalize_rjcode(code)
                if normalized and normalized not in linked_codes:
                    linked_codes.append(normalized)
            canonical_candidates[canonical] = [code for code in linked_codes if code]
            for code in linked_codes:
                if code and code not in lookup_rjcodes:
                    lookup_rjcodes.append(code)

        if not lookup_rjcodes:
            return {}

        rows = (
            db.query(ASMRDownloadSession)
            .filter(ASMRDownloadSession.rjcode.in_(lookup_rjcodes))
            .order_by(ASMRDownloadSession.updated_at.desc())
            .all()
        )
        session_by_rj: Dict[str, Dict[str, Any]] = {}
        stale_rows_corrected = False
        for row in rows:
            session = row.to_dict()
            statistics = dict(session.get("statistics") or {})
            local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
            local_count = int(session.get("local_downloaded_count") or 0)
            # 详情页切换频繁，这里优先使用数据库中已持久化的下载状态，
            # 避免每次点击社团都触发大量磁盘 exists / walk 检查。
            local_root_exists = bool(local_root and os.path.isdir(local_root))
            local_ready = bool(local_root_exists and (session.get("local_download_ready") or local_count > 0))
            if not local_root_exists and (
                bool(session.get("local_download_ready"))
                or local_count > 0
                or str(row.local_download_root or "").strip()
            ):
                row.local_download_ready = False
                row.local_download_root = None
                row.local_downloaded_count = 0
                stale_rows_corrected = True
            if not local_ready:
                continue
            normalized_rj = self.normalize_rjcode(session.get("rjcode"))
            if normalized_rj and normalized_rj not in session_by_rj:
                session_by_rj[normalized_rj] = {
                    "session_id": str(session.get("id") or "").strip(),
                    "download_root": local_root,
                    "downloaded_count": local_count,
                    "updated_at": session.get("updated_at"),
                }
        if stale_rows_corrected:
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.warning("[社团补全] 自动清理失效本地下载标记失败", exc_info=True)

        result: Dict[str, Dict[str, Any]] = {}
        for canonical, candidates in canonical_candidates.items():
            for code in candidates:
                matched = session_by_rj.get(code)
                if matched:
                    result[canonical] = matched
                    break
        unresolved = {
            canonical: candidates
            for canonical, candidates in canonical_candidates.items()
            if canonical and canonical not in result
        }
        if unresolved:
            fallback_roots = self._scan_local_download_root_fallback()
            for canonical, candidates in unresolved.items():
                for code in candidates:
                    matched = fallback_roots.get(code)
                    if matched:
                        result[canonical] = matched
                        break
        return result

    def _scan_local_download_root_fallback(self) -> Dict[str, Dict[str, Any]]:
        cache_expires_at = float(self._local_download_fallback_cache.get("expires_at") or 0.0)
        if cache_expires_at > time.time():
            return dict(self._local_download_fallback_cache.get("data") or {})

        config = get_config()
        temp_root = os.path.join(str(config.storage.temp_path or "").strip(), "asmr_enhanced")
        if not temp_root or not os.path.isdir(temp_root):
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        try:
            entries = list(os.scandir(temp_root))
        except Exception:
            return {}
        entries.sort(key=lambda entry: entry.stat().st_mtime if entry.is_dir() else 0, reverse=True)
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except Exception:
                continue
            rjcode = self.normalize_rjcode(entry.name)
            if not rjcode or rjcode in result:
                continue
            file_count = 0
            try:
                for _, _, files in os.walk(entry.path):
                    file_count += len(files)
                    if file_count > 0:
                        break
            except Exception:
                file_count = 0
            if file_count <= 0:
                continue
            result[rjcode] = {
                "session_id": "",
                "download_root": entry.path,
                "downloaded_count": file_count,
                "updated_at": datetime.fromtimestamp(entry.stat().st_mtime).isoformat() if entry.stat() else None,
            }
        self._local_download_fallback_cache = {
            "expires_at": time.time() + 30,
            "data": dict(result),
        }
        return result

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

    def _find_catalog_by_normalized_name(self, db, normalized_name: str) -> Optional[CircleCatalog]:
        normalized_name = str(normalized_name or "").strip()
        if not normalized_name:
            return None
        return (
            db.query(CircleCatalog)
            .filter(CircleCatalog.circle_name_normalized == normalized_name)
            .order_by(CircleCatalog.last_indexed_at.desc(), CircleCatalog.updated_at.desc(), CircleCatalog.created_at.desc())
            .first()
        )

    async def resolve_canonical_rj(self, rjcode: str, refresh: bool = False) -> Dict[str, Any]:
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return {
                "canonical_rjcode": "",
                "linked_rjcodes": [],
                "link_map": {},
            }
        if not refresh:
            cached_payload = self._canonical_cache.get(normalized_rj)
            if cached_payload is not None:
                return cached_payload

        def build_canonical_payload(rows: List[Any], fallback_rj: str) -> Dict[str, Any]:
            canonical = next((row.canonical_rjcode for row in rows if row.canonical_rjcode), fallback_rj)
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

        cached_rows: List[Any] = []
        db = SessionLocal()
        try:
            cached_rows = (
                db.query(WorkCanonicalLink)
                .filter(
                    (WorkCanonicalLink.linked_rjcode == normalized_rj)
                    | (WorkCanonicalLink.canonical_rjcode == normalized_rj)
                )
                .all()
            )
            if cached_rows and not refresh:
                payload = build_canonical_payload(cached_rows, normalized_rj)
                for linked_rjcode in payload.get("linked_rjcodes") or [normalized_rj]:
                    normalized_linked = self.normalize_rjcode(linked_rjcode)
                    if normalized_linked:
                        self._canonical_cache[normalized_linked] = payload
                self._canonical_cache[normalized_rj] = payload
                return payload
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
        degraded_refresh = bool(refresh and len(link_rows) <= 1 and canonical_rjcode == normalized_rj)
        if degraded_refresh and cached_rows:
            cached_payload = build_canonical_payload(cached_rows, normalized_rj)
            cached_canonical = self.normalize_rjcode(cached_payload.get("canonical_rjcode"))
            if cached_canonical and cached_canonical != normalized_rj:
                try:
                    recovered_linked_map = await self.dlsite_service.get_linked_works(cached_canonical)
                except Exception as exc:
                    logger.warning("[社团补全] 使用缓存 canonical 纠正关联链失败 %s -> %s: %s", normalized_rj, cached_canonical, exc)
                    recovered_linked_map = {}
                if recovered_linked_map:
                    recovered_rows: List[Dict[str, str]] = []
                    recovered_canonical = cached_canonical
                    for linked_rj, linked_work in recovered_linked_map.items():
                        linked_rj_norm = self.normalize_rjcode(linked_rj)
                        if not linked_rj_norm:
                            continue
                        work_type = str(getattr(linked_work, "work_type", "") or "linked").strip() or "linked"
                        lang = str(getattr(linked_work, "lang", "") or "").strip()
                        if work_type == "original":
                            recovered_canonical = linked_rj_norm
                        recovered_rows.append({
                            "linked_rjcode": linked_rj_norm,
                            "link_type": work_type,
                            "lang": lang,
                        })
                    if recovered_rows:
                        link_rows = recovered_rows
                        canonical_rjcode = recovered_canonical
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

        payload = {
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
        for linked_rjcode in payload.get("linked_rjcodes") or [normalized_rj]:
            normalized_linked = self.normalize_rjcode(linked_rjcode)
            if normalized_linked:
                self._canonical_cache[normalized_linked] = payload
        self._canonical_cache[normalized_rj] = payload
        return payload

    async def _fetch_metadata_dict(self, rjcode: str, *, refresh: bool = False) -> Dict[str, Any]:
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return {}
        if refresh:
            self._metadata_cache.pop(normalized_rj, None)
        cached_metadata = self._metadata_cache.get(normalized_rj)
        if not refresh and cached_metadata is not None:
            return cached_metadata
        if not refresh:
            db = SessionLocal()
            try:
                cached = db.query(WorkMetadata).filter(WorkMetadata.rjcode == normalized_rj).first()
                if cached:
                    payload = cached.to_dict()
                    self._metadata_cache[normalized_rj] = payload
                    return payload
            finally:
                db.close()
        fake_task = type("FakeTask", (), {"task_metadata": {"rjcode": normalized_rj}, "rjcode": normalized_rj, "update_progress": lambda *args, **kwargs: None})()
        payload = await self.metadata_service.fetch(normalized_rj, fake_task, force_refresh=refresh)
        self._metadata_cache[normalized_rj] = dict(payload or {})
        return self._metadata_cache[normalized_rj]

    async def _probe_kikoeru_owned_state(self, probe_rjcode: str, *, use_cache: bool = True) -> bool:
        normalized_rj = self.normalize_rjcode(probe_rjcode)
        if not normalized_rj:
            return False
        try:
            results = await self.kikoeru_service.check_duplicate_with_linkages(normalized_rj, use_cache=use_cache)
        except Exception:
            logger.warning("[社团补全] Kikoeru 拥有态补查失败 %s", normalized_rj, exc_info=True)
            return False
        for result in (results or {}).values():
            if getattr(result, "is_found", False):
                return True
        return False

    async def _probe_kikoeru_state(self, probe_rjcode: str, *, use_cache: bool = True) -> Dict[str, Any]:
        normalized_rj = self.normalize_rjcode(probe_rjcode)
        if not normalized_rj:
            return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}
        cached_state = self._kikoeru_state_cache.get(normalized_rj)
        if use_cache and cached_state is not None:
            return cached_state
        if not use_cache:
            self._kikoeru_state_cache.pop(normalized_rj, None)
        try:
            results = await self.kikoeru_service.check_duplicate_with_linkages(normalized_rj, use_cache=use_cache)
        except Exception:
            logger.warning("[社团补全] Kikoeru 状态补查失败 %s", normalized_rj, exc_info=True)
            return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

        found_rjcodes: List[str] = []
        subtitle_rjcodes: List[str] = []
        for workno, result in (results or {}).items():
            if not getattr(result, "is_found", False):
                continue
            matched_rj = self.normalize_rjcode(
                getattr(result, "matched_rjcode", None) or workno or getattr(result, "rjcode", None)
            )
            if matched_rj and matched_rj not in found_rjcodes:
                found_rjcodes.append(matched_rj)
            subtitle_check_source = str(getattr(result, "subtitle_check_source", "") or "").strip()
            if matched_rj and getattr(result, "has_lyric_hint", False) and subtitle_check_source and subtitle_check_source != "search_only":
                if matched_rj not in subtitle_rjcodes:
                    subtitle_rjcodes.append(matched_rj)
        payload = {
            "has_kikoeru": bool(found_rjcodes),
            "found_rjcodes": found_rjcodes,
            "subtitle_rjcodes": subtitle_rjcodes,
        }
        self._kikoeru_state_cache[normalized_rj] = payload
        return payload

    async def _probe_kikoeru_state_for_candidates(self, candidates: List[str], *, use_cache: bool = True) -> Dict[str, Any]:
        normalized_candidates: List[str] = []
        for candidate in candidates or []:
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized not in normalized_candidates:
                normalized_candidates.append(normalized)
        if not normalized_candidates:
            return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

        found_rjcodes: List[str] = []
        subtitle_rjcodes: List[str] = []
        semaphore = asyncio.Semaphore(8)

        async def probe_candidate(candidate: str) -> Dict[str, Any]:
            async with semaphore:
                return await self._probe_kikoeru_state(candidate, use_cache=use_cache)

        for future in asyncio.as_completed([probe_candidate(candidate) for candidate in normalized_candidates]):
            state = await future
            for code in list(state.get("found_rjcodes") or []):
                normalized_code = self.normalize_rjcode(code)
                if normalized_code and normalized_code not in found_rjcodes:
                    found_rjcodes.append(normalized_code)
            for code in list(state.get("subtitle_rjcodes") or []):
                normalized_code = self.normalize_rjcode(code)
                if normalized_code and normalized_code not in subtitle_rjcodes:
                    subtitle_rjcodes.append(normalized_code)

        return {
            "has_kikoeru": bool(found_rjcodes),
            "found_rjcodes": found_rjcodes,
            "subtitle_rjcodes": subtitle_rjcodes,
        }

    async def _search_dlsite_circle_works(self, keyword: str, max_pages: int = 2) -> tuple[List[str], str]:
        found: List[str] = []
        seen = set()
        failure_reason = ""
        client = await self.dlsite_service._get_client()
        headers = self.dlsite_service._get_browser_headers()
        try:
            for page in range(1, max_pages + 1):
                suffix = "" if page == 1 else f"/page/{page}"
                url = f"{self.DL_SEARCH_URL.format(keyword=quote(keyword))}{suffix}"
                try:
                    response = await client.get(url, headers=headers, timeout=12.0)
                    if response.status_code != 200:
                        logger.warning(
                            "[社团补全] DLsite 社团关键字搜索失败 keyword=%s page=%s status=%s",
                            keyword,
                            page,
                            response.status_code,
                        )
                        failure_reason = f"DLsite 关键字搜索返回 HTTP {response.status_code}（第 {page} 页）"
                        break
                    text = response.text
                except Exception as exc:
                    logger.warning("[社团补全] DLsite 社团搜索失败 keyword=%s page=%s: %s", keyword, page, exc)
                    failure_reason = f"DLsite 关键字搜索失败（第 {page} 页）: {str(exc)}"
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
            pass
        return found, failure_reason

    async def _resolve_seed_maker_id(
        self,
        circle_query: str,
        seed_candidates: List[Dict[str, Any]],
        *,
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> Dict[str, str]:
        normalized_query = self.normalize_circle_name(circle_query)
        if not seed_candidates:
            return {"maker_id": "", "maker_name": ""}

        total = min(len(seed_candidates), 8)
        for index, item in enumerate(seed_candidates[:total], start=1):
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                continue
            try:
                metadata = await self._fetch_metadata_dict(rjcode)
            except Exception:
                metadata = {}
            maker_id = str(metadata.get("maker_id") or item.get("maker_id") or "").strip()
            maker_name = str(metadata.get("maker_name") or item.get("maker_name") or "").strip()
            if progress_callback and (index == 1 or index == total):
                progress_callback(
                    34,
                    f"补查 DLsite 社团标识 {index}/{total}",
                    seed_probe_rjcode=rjcode,
                    seed_probe_maker_id=maker_id,
                )
            if maker_id and (
                not normalized_query
                or not maker_name
                or normalized_query in self.normalize_circle_name(maker_name)
            ):
                return {
                    "maker_id": maker_id,
                    "maker_name": maker_name,
                }
        return {"maker_id": "", "maker_name": ""}

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
        failure_messages: List[str] = []

        if normalized_maker_id:
            try:
                dlsite_rjcodes = await self.dlsite_service.list_circle_worknos_by_maker(normalized_maker_id, language="JPN")
                source_mode = "maker_profile"
                if progress_callback:
                    progress_callback(44, "已抓取 DLsite 社团主页原作列表", dlsite_profile_total=len(dlsite_rjcodes), dlsite_source_mode=source_mode, dlsite_failure_reason="")
            except Exception as exc:
                logger.warning("[社团补全] 按 maker_id 抓取 DLsite 社团主页失败 maker_id=%s", normalized_maker_id, exc_info=True)
                failure_messages.append(f"DLsite 社团主页抓取失败: {str(exc)}")
                if progress_callback:
                    progress_callback(44, "DLsite 社团主页抓取失败，准备回退关键字搜索", dlsite_source_mode=source_mode, dlsite_failure_reason=" / ".join(failure_messages))

        if not dlsite_rjcodes:
            dlsite_rjcodes, keyword_failure_reason = await self._search_dlsite_circle_works(circle_query)
            if keyword_failure_reason:
                failure_messages.append(keyword_failure_reason)
            if progress_callback:
                progress_callback(
                    44,
                    "已回退关键字搜索 DLsite",
                    dlsite_profile_total=len(dlsite_rjcodes),
                    dlsite_source_mode=source_mode,
                    dlsite_failure_reason=" / ".join(failure_messages),
                )

        candidates: List[Dict[str, Any]] = []
        total_rjcodes = max(1, len(dlsite_rjcodes))
        semaphore = asyncio.Semaphore(10)

        async def fetch_candidate(rjcode: str) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    meta = await self._fetch_metadata_dict(rjcode)
                except Exception:
                    meta = {"rjcode": rjcode}
            maker_name = str(meta.get("maker_name") or "").strip()
            if maker_name and self.normalize_circle_name(circle_query) not in self.normalize_circle_name(maker_name) and not normalized_maker_id:
                return None
            return {
                "rjcode": rjcode,
                "title": meta.get("work_name") or "",
                "maker_id": meta.get("maker_id") or normalized_maker_id or "",
                "maker_name": maker_name or circle_query,
                "image_url": meta.get("cover_url") or "",
                "source": "dlsite",
            }

        completed = 0
        futures = [fetch_candidate(rjcode) for rjcode in dlsite_rjcodes]
        for future in asyncio.as_completed(futures):
            candidate = await future
            completed += 1
            if candidate:
                candidates.append(candidate)
            if progress_callback and (completed == total_rjcodes or completed % 10 == 0):
                progress_callback(
                    44 + int((completed / total_rjcodes) * 8),
                    f"解析 DLsite 社团作品 {completed}/{total_rjcodes}",
                    dlsite_profile_total=len(dlsite_rjcodes),
                    dlsite_candidates_count=len(candidates),
                    dlsite_source_mode=source_mode,
                    dlsite_failure_reason=" / ".join(failure_messages),
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
                    "image_url": row.cover_url or "",
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
        only_new_works: bool = False,
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
        if not identity_seed["maker_id"] and combined_seed_candidates:
            seed_identity = await self._resolve_seed_maker_id(
                circle_query,
                combined_seed_candidates,
                progress_callback=progress_callback,
            )
            if seed_identity["maker_id"]:
                identity_seed = self.resolve_circle_identity(
                    seed_identity["maker_id"],
                    seed_identity["maker_name"] or circle_query,
                    circle_query,
                )

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
        normalized_circle_name = str(identity.get("circle_name_normalized") or "").strip()
        if normalized_circle_name:
            db = SessionLocal()
            try:
                existing_catalog = self._find_catalog_by_normalized_name(db, normalized_circle_name)
                if existing_catalog and str(existing_catalog.circle_id or "").strip():
                    circle_id = str(existing_catalog.circle_id).strip()
            finally:
                db.close()
        if not circle_id or str(circle_id).strip().lower().startswith("name:"):
            raise ValueError("未识别到有效社团标识，已跳过入社团目录")

        existing_canonical_rjcodes: set[str] = set()
        if only_new_works and circle_id:
            db = SessionLocal()
            try:
                existing_canonical_rjcodes = {
                    str(row.canonical_rjcode or "").strip().upper()
                    for row in db.query(CircleWork).filter(CircleWork.circle_id == circle_id).all()
                    if str(row.canonical_rjcode or "").strip()
                }
            finally:
                db.close()

        aggregated: Dict[str, Dict[str, Any]] = {}
        total_candidates = max(1, len(combined_candidates))
        metadata_checked = 0
        skipped_existing = 0
        candidate_semaphore = asyncio.Semaphore(8)

        async def prepare_candidate(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            ensure_not_cancelled()
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                return None
            async with candidate_semaphore:
                try:
                    metadata = await self._fetch_metadata_dict(rjcode)
                except Exception:
                    metadata = {}
                canonical_info = await self.resolve_canonical_rj(rjcode, refresh=force_refresh)
                canonical = canonical_info["canonical_rjcode"] or rjcode
                canonical_metadata = metadata
                if canonical and canonical != rjcode:
                    try:
                        canonical_metadata = await self._fetch_metadata_dict(canonical)
                    except Exception:
                        canonical_metadata = metadata
                display_metadata_map = {
                    self.normalize_rjcode(rjcode): metadata or {},
                    self.normalize_rjcode(canonical): canonical_metadata or {},
                }
                public_variants = await self._list_public_display_variants(
                    canonical_info,
                    canonical or rjcode,
                    display_metadata_map,
                )
                preferred_variant, preferred_title = await self._pick_public_display_variant_and_title(
                    canonical_info,
                    canonical or rjcode,
                    display_metadata_map,
                )
            return {
                "item": item,
                "rjcode": rjcode,
                "metadata": metadata or {},
                "canonical_info": canonical_info,
                "canonical": canonical,
                "canonical_metadata": canonical_metadata or {},
                "preferred_variant": preferred_variant,
                "preferred_title": preferred_title,
                "public_linked_rjcodes": [variant["rjcode"] for variant in public_variants if variant.get("rjcode")],
            }

        for future in asyncio.as_completed([prepare_candidate(item) for item in combined_candidates]):
            prepared = await future
            metadata_checked += 1
            if not prepared:
                report(
                    52 + int((metadata_checked / total_candidates) * 18),
                    f"整理候选作品 {metadata_checked}/{total_candidates}",
                    aggregated_count=len(aggregated),
                    metadata_checked_count=metadata_checked,
                )
                continue
            item = prepared["item"]
            rjcode = prepared["rjcode"]
            metadata = prepared["metadata"]
            canonical = prepared["canonical"]
            canonical_metadata = prepared["canonical_metadata"]
            preferred_variant = prepared["preferred_variant"]
            preferred_title = prepared["preferred_title"]
            public_linked_rjcodes = prepared["public_linked_rjcodes"]
            if only_new_works and canonical in existing_canonical_rjcodes:
                skipped_existing += 1
                report(
                    52 + int((metadata_checked / total_candidates) * 18),
                    f"整理候选作品 {metadata_checked}/{total_candidates}",
                    aggregated_count=len(aggregated),
                    metadata_checked_count=metadata_checked,
                    skipped_existing_count=skipped_existing,
                    existing_indexed_count=len(existing_canonical_rjcodes),
                )
                continue
            bucket = aggregated.setdefault(canonical, {
                "canonical_rjcode": canonical,
                "display_rjcode": preferred_variant["rjcode"] or rjcode,
                "title": preferred_title or str(canonical_metadata.get("work_name") or item.get("title") or metadata.get("work_name") or ""),
                "maker_id": str(canonical_metadata.get("maker_id") or metadata.get("maker_id") or item.get("maker_id") or identity["maker_id"] or ""),
                "maker_name": str(canonical_metadata.get("maker_name") or metadata.get("maker_name") or item.get("maker_name") or identity["circle_name"] or circle_query),
                "linked_rjcodes": public_linked_rjcodes or [preferred_variant["rjcode"] or canonical or rjcode],
                "has_kikoeru": False,
                "kikoeru_found_rjcodes": [],
                "kikoeru_subtitle_rjcodes": [],
                "has_dlsite": True,
                "has_asmr_one": False,
                "asmr_available_rjcode": "",
                "kikoeru_work_id": None,
                "source_flags": set(),
                "preferred_variant_label": self._variant_label(preferred_variant["link_type"], preferred_variant["lang"]),
                "preferred_lang": preferred_variant["lang"],
                "preferred_link_type": preferred_variant["link_type"],
            })
            bucket["display_rjcode"] = preferred_variant["rjcode"] or canonical or rjcode
            bucket["title"] = preferred_title or bucket["title"] or str(canonical_metadata.get("work_name") or item.get("title") or metadata.get("work_name") or "")
            bucket["maker_id"] = bucket["maker_id"] or str(canonical_metadata.get("maker_id") or metadata.get("maker_id") or item.get("maker_id") or "")
            bucket["maker_name"] = bucket["maker_name"] or str(canonical_metadata.get("maker_name") or metadata.get("maker_name") or item.get("maker_name") or circle_query)
            bucket["image_url"] = bucket.get("image_url") or str(canonical_metadata.get("cover_url") or metadata.get("cover_url") or item.get("image_url") or "")
            bucket["linked_rjcodes"] = public_linked_rjcodes or bucket["linked_rjcodes"]
            bucket["preferred_variant_label"] = self._variant_label(preferred_variant["link_type"], preferred_variant["lang"])
            bucket["preferred_lang"] = preferred_variant["lang"]
            bucket["preferred_link_type"] = preferred_variant["link_type"]
            source = str(item.get("source") or "").strip()
            if source:
                bucket["source_flags"].add(source)
            if source == "kikoeru":
                bucket["has_kikoeru"] = True
                if rjcode not in bucket["kikoeru_found_rjcodes"]:
                    bucket["kikoeru_found_rjcodes"].append(rjcode)
                if item.get("kikoeru_work_id"):
                    bucket["kikoeru_work_id"] = int(item["kikoeru_work_id"])
            if source == "dlsite":
                bucket["has_dlsite"] = True
            if source == "local":
                bucket["source_flags"].add("local")
            bucket["source_flags"].add("dlsite")
            report(
                52 + int((metadata_checked / total_candidates) * 18),
                f"整理候选作品 {metadata_checked}/{total_candidates}",
                aggregated_count=len(aggregated),
                metadata_checked_count=metadata_checked,
                skipped_existing_count=skipped_existing,
                existing_indexed_count=len(existing_canonical_rjcodes),
            )

        if not aggregated:
            if only_new_works and existing_canonical_rjcodes:
                summary = await self.build_circle_completion_view(circle_id)
                indexed_counts = {
                    "works": len(summary.get("works") or []),
                    "local_owned_count": int(summary.get("local_owned_count") or 0),
                    "owned_count": int(summary.get("owned_count") or 0),
                    "missing_count": int(summary.get("missing_count") or 0),
                    "downloadable_count": int(summary.get("downloadable_count") or 0),
                    "dl_count": int(summary.get("dl_count") or 0),
                }
                report(100, "索引完成", aggregated_count=0, skipped_existing_count=skipped_existing)
                return {
                    "circle_id": circle_id,
                    "summary": {
                        "circle_name": identity["circle_name"] or circle_query,
                        **indexed_counts,
                    },
                    "indexed_counts": indexed_counts,
                    "incremental": {
                        "only_new_works": True,
                        "existing_indexed_count": len(existing_canonical_rjcodes),
                        "skipped_existing_count": skipped_existing,
                        "newly_indexed_count": 0,
                    },
                }

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
            return {
                "circle_id": circle_id,
                "summary": {"total": 0},
                "indexed_counts": {"works": 0},
                "incremental": {
                    "only_new_works": bool(only_new_works),
                    "existing_indexed_count": len(existing_canonical_rjcodes),
                    "skipped_existing_count": skipped_existing,
                    "newly_indexed_count": 0,
                },
            }

        report(74, "检查 asmr.one 可下载状态", aggregated_count=len(aggregated))
        checked_asmr = 0
        asmr_available = 0
        total_aggregated = max(1, len(aggregated))
        asmr_semaphore = asyncio.Semaphore(6)

        async def load_probe_inputs() -> List[tuple[str, Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Any]]]:
            db = SessionLocal()
            try:
                link_rows = (
                    db.query(WorkCanonicalLink)
                    .filter(WorkCanonicalLink.canonical_rjcode.in_(list(aggregated.keys())))
                    .all()
                    if aggregated else []
                )
                link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
                for link_row in link_rows:
                    link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                        "link_type": str(link_row.link_type or ""),
                        "lang": str(link_row.lang or ""),
                    }
                payloads = []
                for canonical, item in aggregated.items():
                    linked_rjcodes = list(item.get("linked_rjcodes") or [item.get("display_rjcode") or canonical])
                    metadata_map = self._load_cached_metadata_map(db, linked_rjcodes)
                    canonical_info = {
                        "canonical_rjcode": canonical,
                        "linked_rjcodes": linked_rjcodes,
                        "link_map": link_map_by_canonical.get(canonical) or {},
                    }
                    payloads.append((canonical, item, metadata_map, canonical_info))
                return payloads
            finally:
                db.close()

        probe_payloads = await load_probe_inputs()
        async def run_payload(payload: tuple[str, Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Any]]) -> tuple[str, str]:
            canonical, item, metadata_map, canonical_info = payload
            async with asmr_semaphore:
                actual_rjcode, _ = await self._find_public_downloadable_work(
                    canonical_info,
                    item.get("display_rjcode") or canonical,
                    metadata_map=metadata_map,
                    extra_candidates=[item.get("asmr_available_rjcode"), item.get("display_rjcode"), canonical],
                )
            return canonical, self.normalize_rjcode(actual_rjcode)

        for future in asyncio.as_completed([run_payload(payload) for payload in probe_payloads]):
            ensure_not_cancelled()
            canonical, actual_norm = await future
            item = aggregated.get(canonical) or {}
            if actual_norm:
                item["has_asmr_one"] = True
                item["source_flags"].add("asmr_one")
                item["asmr_available_rjcode"] = actual_norm
                item["linked_rjcodes"] = sorted(set(item["linked_rjcodes"]) | {actual_norm})
                asmr_available += 1
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
        kikoeru_semaphore = asyncio.Semaphore(6)

        async def run_kikoeru_probe(canonical: str, item: Dict[str, Any]) -> tuple[str, Optional[Dict[str, Any]]]:
            ensure_not_cancelled()
            if item["has_kikoeru"] and item["kikoeru_found_rjcodes"] and item["kikoeru_subtitle_rjcodes"]:
                return canonical, None
            probe_candidates = [
                item.get("display_rjcode"),
                canonical,
                item.get("asmr_available_rjcode"),
                *(item.get("linked_rjcodes") or []),
                *(item.get("kikoeru_found_rjcodes") or []),
            ]
            async with kikoeru_semaphore:
                state = await self._probe_kikoeru_state_for_candidates(probe_candidates)
            return canonical, state

        for future in asyncio.as_completed([run_kikoeru_probe(canonical, item) for canonical, item in aggregated.items()]):
            ensure_not_cancelled()
            canonical, kikoeru_state = await future
            item = aggregated.get(canonical) or {}
            if kikoeru_state is not None:
                found_rjcodes = [self.normalize_rjcode(code) for code in list(kikoeru_state.get("found_rjcodes") or [])]
                found_rjcodes = [code for code in found_rjcodes if code]
                subtitle_rjcodes = [self.normalize_rjcode(code) for code in list(kikoeru_state.get("subtitle_rjcodes") or [])]
                subtitle_rjcodes = [code for code in subtitle_rjcodes if code]
                item["has_kikoeru"] = bool(found_rjcodes)
                item["kikoeru_found_rjcodes"] = found_rjcodes
                item["kikoeru_subtitle_rjcodes"] = subtitle_rjcodes
                if item["has_kikoeru"] or found_rjcodes:
                    item["source_flags"].add("kikoeru")
            if item.get("has_kikoeru"):
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
                row.image_url = item.get("image_url") or ""
                row.source_mask = ",".join(sorted(item["source_flags"]))
                row.linked_rjcodes = item["linked_rjcodes"]
                row.has_kikoeru = bool(item["has_kikoeru"])
                row.kikoeru_found_rjcodes = list(item["kikoeru_found_rjcodes"] or [])
                row.kikoeru_subtitle_rjcodes = list(item["kikoeru_subtitle_rjcodes"] or [])
                row.has_dlsite = bool(item["has_dlsite"] or "dlsite" in item["source_flags"])
                row.has_asmr_one = bool(item["has_asmr_one"])
                row.asmr_available_rjcode = item["asmr_available_rjcode"] or None
                row.kikoeru_work_id = item["kikoeru_work_id"]
                row.dlsite_cached_at = datetime.now() if row.has_dlsite else row.dlsite_cached_at
                row.asmr_one_cached_at = datetime.now() if row.has_asmr_one else row.asmr_one_cached_at
            if not only_new_works:
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
                f"Kikoeru 有 {indexed_counts['owned_count']} 个 / "
                f"DL 有 {indexed_counts['dl_count']} 个 / "
                f"asmr.one 有 {sum(1 for item in summary.get('works') or [] if item.get('has_asmr_one'))} 个 / "
                f"可下载 {indexed_counts['downloadable_count']} 个 / "
                f"暂无来源 {sum(1 for item in summary.get('works') or [] if not item.get('server_owned') and item.get('has_dlsite') and not item.get('has_asmr_one'))} 个"
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
                **self._build_circle_index_log_detail(
                    summary,
                    force_refresh=force_refresh,
                    include_dlsite=include_dlsite,
                    include_kikoeru=include_kikoeru,
                ),
                "only_new_works": bool(only_new_works),
                "existing_indexed_count": len(existing_canonical_rjcodes),
                "skipped_existing_count": skipped_existing,
                "newly_indexed_count": len(aggregated),
            },
        )
        return {
            "circle_id": circle_id,
            "summary": {
                "circle_name": identity["circle_name"] or circle_query,
                **indexed_counts,
            },
            "indexed_counts": indexed_counts,
            "incremental": {
                "only_new_works": bool(only_new_works),
                "existing_indexed_count": len(existing_canonical_rjcodes),
                "skipped_existing_count": skipped_existing,
                "newly_indexed_count": len(aggregated),
            },
        }

    async def search_circles(self, keyword: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        normalized = self.normalize_circle_name(keyword)
        db = SessionLocal()
        try:
            rows = db.query(CircleCatalog).order_by(CircleCatalog.last_indexed_at.desc()).all()
            out = []
            seen_keys = set()
            collected_ids = []
            for row in rows:
                if normalized:
                    haystack = f"{row.circle_name or ''} {row.circle_id or ''} {row.circle_name_normalized or ''}".lower()
                    if normalized not in haystack:
                        continue
                dedupe_key = str(row.circle_name_normalized or "").strip() or str(row.circle_id or "").strip()
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                out.append(row.to_dict())
                collected_ids.append(row.circle_id)
                if len(out) >= max(1, int(limit)):
                    break

            # 批量查询每个社团的作品计数
            if collected_ids:
                from sqlalchemy import func as sa_func, Integer
                count_rows = (
                    db.query(
                        CircleWork.circle_id,
                        sa_func.count(CircleWork.id).label("total"),
                        sa_func.sum(sa_func.cast(CircleWork.has_kikoeru, Integer)).label("kikoeru"),
                        sa_func.sum(sa_func.cast(CircleWork.has_asmr_one, Integer)).label("asmr"),
                        sa_func.sum(sa_func.cast(CircleWork.has_dlsite, Integer)).label("dlsite"),
                    )
                    .filter(CircleWork.circle_id.in_(collected_ids))
                    .group_by(CircleWork.circle_id)
                    .all()
                )
                counts_map = {
                    r.circle_id: {
                        "total_works": int(r.total or 0),
                        "server_owned": int(r.kikoeru or 0),
                        "asmr_available": int(r.asmr or 0),
                        "dl_works": int(r.dlsite or 0),
                    }
                    for r in count_rows
                }
                for item in out:
                    stats = counts_map.get(item["circle_id"], {})
                    item["total_works"] = stats.get("total_works", 0)
                    item["server_owned"] = stats.get("server_owned", 0)
                    item["missing"] = item["total_works"] - item["server_owned"]
                    item["asmr_available"] = stats.get("asmr_available", 0)
                    item["dl_works"] = stats.get("dl_works", 0)

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

            works = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == catalog.circle_id)
                .order_by(CircleWork.updated_at.desc())
                .all()
            )
            work_canonical_rjcodes = [row.canonical_rjcode for row in works if str(row.canonical_rjcode or "").strip()]
            owned_rows = (
                {
                    row.canonical_rjcode: row
                    for row in db.query(LibraryOwnedWork)
                    .filter(LibraryOwnedWork.canonical_rjcode.in_(work_canonical_rjcodes))
                    .all()
                }
                if work_canonical_rjcodes else {}
            )
            link_rows = (
                db.query(WorkCanonicalLink)
                .filter(WorkCanonicalLink.canonical_rjcode.in_(work_canonical_rjcodes))
                .all()
                if works else []
            )
            link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            for link_row in link_rows:
                link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                    "link_type": str(link_row.link_type or ""),
                    "lang": str(link_row.lang or ""),
                }
            local_download_session_map = self._build_local_download_session_map(db, works, link_map_by_canonical)

            metadata_lookup_rjcodes: List[str] = []
            for row in works:
                for candidate in [
                    row.canonical_rjcode,
                    row.display_rjcode,
                    *(row.linked_rjcodes or []),
                    *(link_map_by_canonical.get(str(row.canonical_rjcode or ""), {}).keys()),
                ]:
                    normalized_candidate = self.normalize_rjcode(candidate)
                    if normalized_candidate and normalized_candidate not in metadata_lookup_rjcodes:
                        metadata_lookup_rjcodes.append(normalized_candidate)
            metadata_map_all = self._load_cached_metadata_map(db, metadata_lookup_rjcodes)

            items = []
            for row in works:
                owned_row = owned_rows.get(row.canonical_rjcode)
                local_owned = owned_row is not None
                item = row.to_dict()
                item["circle_name"] = catalog.circle_name
                item["local_owned"] = local_owned
                item["owned_rjcodes"] = list((owned_row.owned_rjcodes or []) if owned_row else [])
                item["primary_folder_path"] = owned_row.primary_folder_path if owned_row else ""
                item["has_dlsite"] = True
                local_download = local_download_session_map.get(self.normalize_rjcode(row.canonical_rjcode)) or {}
                item["local_download_ready"] = bool(local_download)
                item["local_download_session_id"] = str(local_download.get("session_id") or "").strip()
                item["local_download_root"] = str(local_download.get("download_root") or "").strip()
                item["local_downloaded_count"] = int(local_download.get("downloaded_count") or 0)
                canonical_info = {
                    "canonical_rjcode": row.canonical_rjcode,
                    "linked_rjcodes": list(row.linked_rjcodes or [row.display_rjcode or row.canonical_rjcode]),
                    "link_map": link_map_by_canonical.get(row.canonical_rjcode) or {},
                }
                metadata_map = {
                    code: metadata_map_all[code]
                    for code in canonical_info["linked_rjcodes"]
                    if code in metadata_map_all
                }
                stored_display_rjcode = self.normalize_rjcode(row.display_rjcode) or self.normalize_rjcode(row.canonical_rjcode)
                item["display_rjcode"] = stored_display_rjcode
                item["linked_rjcodes"] = list(row.linked_rjcodes or [stored_display_rjcode or row.canonical_rjcode])
                if not str(item.get("title") or "").strip():
                    item["title"] = str((metadata_map.get(stored_display_rjcode) or {}).get("work_name") or row.title or "").strip()
                view_canonical_info = {
                    **canonical_info,
                    "linked_rjcodes": item["linked_rjcodes"],
                }
                preferred_variant = next((
                    variant
                    for variant in self._sort_linked_variants(view_canonical_info, stored_display_rjcode or row.canonical_rjcode)
                    if self.normalize_rjcode(variant.get("rjcode")) == stored_display_rjcode
                ), None)
                if preferred_variant is None:
                    preferred_variant = self._pick_display_variant(
                        view_canonical_info,
                        stored_display_rjcode or row.canonical_rjcode,
                        metadata_map,
                    )
                preferred_group = self._variant_group(preferred_variant.get("link_type"), preferred_variant.get("lang"))
                item["preferred_variant"] = {
                    "rjcode": preferred_variant.get("rjcode"),
                    "lang": preferred_variant.get("lang"),
                    "link_type": preferred_variant.get("link_type"),
                    "label": self._variant_label(preferred_variant.get("link_type"), preferred_variant.get("lang")),
                    "group_key": preferred_group["key"],
                    "group_label": preferred_group["label"],
                    "group_short_label": preferred_group["short_label"],
                }
                item["source_compare"] = self._build_source_compare(item, view_canonical_info, metadata_map)
                kikoeru_compare = item["source_compare"].get("kikoeru") if isinstance(item["source_compare"], dict) else {}
                server_match_rjcodes = list((kikoeru_compare or {}).get("matched_rjcodes") or (kikoeru_compare or {}).get("all_rjcodes") or [])
                server_match_primary_rjcode = str(
                    (kikoeru_compare or {}).get("matched_rjcode")
                    or (kikoeru_compare or {}).get("primary_rjcode")
                    or (server_match_rjcodes[0] if server_match_rjcodes else "")
                ).strip()
                server_owned = bool(server_match_rjcodes)
                completion_owned = bool(server_owned or local_owned)
                is_unavailable = not completion_owned and not bool(row.has_asmr_one)
                if only_missing and completion_owned:
                    continue
                if only_downloadable and not row.has_asmr_one:
                    continue
                if not include_dl_only and is_unavailable:
                    continue
                item["owned"] = completion_owned
                item["completion_owned"] = completion_owned
                item["server_owned"] = server_owned
                item["server_match_rjcodes"] = server_match_rjcodes
                item["server_match_primary_rjcode"] = server_match_primary_rjcode
                item["subtitle_present"] = bool((kikoeru_compare or {}).get("subtitle_present"))
                item["status_tags"] = [
                    *(["库存已收录"] if local_owned else []),
                    *(["本地已下载"] if item["local_download_ready"] else []),
                    *(["服务器已有"] if server_owned else ["服务器缺失"]),
                    *(["可下载"] if row.has_asmr_one else ["暂不可下载"]),
                ]
                item["download_plan"] = {"rjcode": row.asmr_available_rjcode or row.display_rjcode} if row.has_asmr_one else None
                items.append(item)

            result = {
                "circle_id": catalog.circle_id,
                "circle_name": catalog.circle_name,
                "source_mask": catalog.source_mask or "",
                "last_indexed_at": catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None,
                "local_owned_count": sum(1 for item in items if item["local_owned"]),
                "owned_count": sum(1 for item in items if item["server_owned"]),
                "missing_count": sum(1 for item in items if not item["owned"]),
                "downloadable_count": sum(1 for item in items if not item["owned"] and item["has_asmr_one"]),
                "dl_only_count": sum(1 for item in items if not item["owned"] and not item["has_asmr_one"]),
                "dl_count": sum(1 for item in items if item["has_dlsite"]),
                "works": items,
            }
        finally:
            db.close()
        return result

    async def preview_batch_download(
        self,
        circle_id: str,
        canonical_rjcodes: List[str],
        requested_rjcodes: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
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

        requested_rjcodes = dict(requested_rjcodes or {})
        plans = []
        for row in rows:
            if not row.has_asmr_one:
                continue
            explicit_candidates = []
            for candidate in requested_rjcodes.get(str(row.canonical_rjcode or "").strip(), []) or []:
                normalized = self.normalize_rjcode(candidate)
                if normalized and normalized not in explicit_candidates:
                    explicit_candidates.append(normalized)

            resolved_rjcode = next((candidate for candidate in explicit_candidates if candidate), "") or self.normalize_rjcode(row.asmr_available_rjcode)
            probe_candidates: List[str] = []
            for candidate in [*explicit_candidates, resolved_rjcode, row.asmr_available_rjcode, row.display_rjcode, row.canonical_rjcode, *(row.linked_rjcodes or [])]:
                normalized = self.normalize_rjcode(candidate)
                if normalized and normalized not in probe_candidates:
                    probe_candidates.append(normalized)

            if not resolved_rjcode:
                for probe_rjcode in probe_candidates:
                    try:
                        actual_rjcode, work_info = await self.asmr_service.find_best_available_work(probe_rjcode)
                    except Exception:
                        continue
                    if actual_rjcode and work_info:
                        resolved_rjcode = self.normalize_rjcode(actual_rjcode)
                        break

            if not resolved_rjcode:
                raise ValueError(f"未找到可下载作品 {row.display_rjcode or row.canonical_rjcode}")

            plan = await self.asmr_resource_service.build_download_plan(
                rjcode=resolved_rjcode,
                folder_path="",
                filters={},
                refresh=True,
                emit_activity_log=False,
            )
            skip_reasons = self._build_filter_skip_reasons(plan.get("selectable_resources") or [])
            kept_resources = []
            filtered_out_resources = []
            for item in plan.get("selectable_resources") or []:
                reasons = list(skip_reasons.get(str(item.get("relative_path") or ""), []))
                if reasons:
                    item["selected"] = False
                    item["recommended_skip_reasons"] = reasons
                    filtered_out_resources.append(item)
                    continue
                kept_resources.append(item)
            plan["selectable_resources"] = kept_resources
            plan["filtered_out_resources"] = filtered_out_resources
            plan["filtered_out_count"] = len(filtered_out_resources)
            plan["summary"] = {
                **dict(plan.get("summary") or {}),
                "selectable_total": len(kept_resources),
                "selected_total": len([item for item in kept_resources if item.get("selected")]),
                "filtered_out_total": len(filtered_out_resources),
            }
            plan["grouped_resources"] = self.asmr_resource_service._group_resources(kept_resources)
            plan["selection_presets"] = self.asmr_resource_service._build_selection_presets(kept_resources)
            plan["circle_id"] = circle_id
            plan["circle_name"] = catalog.circle_name
            plan["canonical_rjcode"] = row.canonical_rjcode
            plan["requested_rjcode"] = row.display_rjcode or row.canonical_rjcode
            plan["resolved_rjcode"] = resolved_rjcode
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

    async def refresh_circle_works(
        self,
        circle_id: str,
        canonical_rjcodes: List[str],
        *,
        force_refresh: bool = False,
        progress_callback: Optional[Callable[..., None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        from .activity_log_service import log_circle_completion_event

        normalized_codes = []
        for value in canonical_rjcodes or []:
            code = self.normalize_rjcode(value)
            if code and code not in normalized_codes:
                normalized_codes.append(code)
        if not circle_id:
            raise ValueError("缺少社团标识")
        if not normalized_codes:
            raise ValueError("没有选中要刷新的作品")

        db = SessionLocal()
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            if catalog is None:
                raise ValueError("社团不存在")
            rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id, CircleWork.canonical_rjcode.in_(normalized_codes))
                .all()
            )
            if not rows:
                raise ValueError("没有找到选中的作品")

            refreshed_items = []
            refreshed_count = 0
            asmr_available_count = 0
            kikoeru_owned_count = 0
            total = len(rows)

            def _normalize_code_list(values: Any) -> List[str]:
                normalized_codes: List[str] = []
                for value in list(values or []):
                    normalized = self.normalize_rjcode(value)
                    if normalized and normalized not in normalized_codes:
                        normalized_codes.append(normalized)
                return normalized_codes

            def _pick_server_primary(target_rjcodes: List[str], canonical_info_map: Dict[str, Any], fallback_rjcode: str) -> str:
                normalized_targets = _normalize_code_list(target_rjcodes)
                if not normalized_targets:
                    return ""
                for variant in self._sort_linked_variants(canonical_info_map, fallback_rjcode):
                    candidate = self.normalize_rjcode(variant.get("rjcode"))
                    if candidate and candidate in normalized_targets:
                        return candidate
                return normalized_targets[0]

            def _build_refresh_change_details(
                before_snapshot: Dict[str, Any],
                *,
                after_display_rjcode: str,
                after_asmr_rjcode: str,
                after_has_asmr_one: bool,
                after_has_kikoeru: bool,
                after_source_mask: str,
                after_found_rjcodes: List[str],
                after_subtitle_rjcodes: List[str],
                canonical_info_map: Dict[str, Any],
            ) -> List[Dict[str, Any]]:
                changes: List[Dict[str, Any]] = []

                before_asmr_rjcode = str(before_snapshot.get("asmr_available_rjcode") or "").strip()
                before_found_rjcodes = _normalize_code_list(before_snapshot.get("found_rjcodes") or [])
                before_subtitle_rjcodes = _normalize_code_list(before_snapshot.get("subtitle_rjcodes") or [])
                before_server_primary = _pick_server_primary(before_found_rjcodes, canonical_info_map, after_display_rjcode or canonical)
                after_server_primary = _pick_server_primary(after_found_rjcodes, canonical_info_map, after_display_rjcode or canonical)
                before_subtitle_present = bool(before_subtitle_rjcodes)
                after_subtitle_present = bool(after_subtitle_rjcodes)

                if bool(before_snapshot.get("has_kikoeru")) != bool(after_has_kikoeru):
                    changes.append({
                        "key": "server_state",
                        "label": "服务器状态",
                        "before": "服务器已有" if bool(before_snapshot.get("has_kikoeru")) else "服务器缺失",
                        "after": "服务器已有" if bool(after_has_kikoeru) else "服务器缺失",
                        "change_type": "gain" if after_has_kikoeru else "loss",
                    })

                if bool(before_snapshot.get("has_asmr_one")) != bool(after_has_asmr_one):
                    changes.append({
                        "key": "asmr_available",
                        "label": "asmr.one",
                        "before": "可下载" if bool(before_snapshot.get("has_asmr_one")) else "暂无来源",
                        "after": "可下载" if bool(after_has_asmr_one) else "暂无来源",
                        "change_type": "gain" if after_has_asmr_one else "loss",
                    })

                if before_asmr_rjcode != after_asmr_rjcode:
                    changes.append({
                        "key": "asmr_rjcode",
                        "label": "asmr.one RJ",
                        "before": before_asmr_rjcode or "—",
                        "after": after_asmr_rjcode or "—",
                        "change_type": "switch" if before_asmr_rjcode and after_asmr_rjcode else ("gain" if after_asmr_rjcode else "loss"),
                    })

                if str(before_snapshot.get("display_rjcode") or "").strip() != after_display_rjcode:
                    changes.append({
                        "key": "preferred_rjcode",
                        "label": "优先RJ",
                        "before": str(before_snapshot.get("display_rjcode") or "").strip() or "—",
                        "after": after_display_rjcode or "—",
                        "change_type": "switch",
                    })

                if before_server_primary != after_server_primary:
                    changes.append({
                        "key": "server_rjcode",
                        "label": "服务器RJ",
                        "before": before_server_primary or "—",
                        "after": after_server_primary or "—",
                        "change_type": "switch" if before_server_primary and after_server_primary else ("gain" if after_server_primary else "loss"),
                    })

                if before_subtitle_present != after_subtitle_present:
                    changes.append({
                        "key": "subtitle_state",
                        "label": "字幕状态",
                        "before": "有" if before_subtitle_present else "无",
                        "after": "有" if after_subtitle_present else "无",
                        "change_type": "gain" if after_subtitle_present else "loss",
                    })

                if str(before_snapshot.get("source_mask") or "").strip() != after_source_mask:
                    before_sources = [flag for flag in str(before_snapshot.get("source_mask") or "").split(",") if flag]
                    after_sources = [flag for flag in str(after_source_mask or "").split(",") if flag]
                    changes.append({
                        "key": "source_mask",
                        "label": "来源集合",
                        "before": before_sources,
                        "after": after_sources,
                        "change_type": "switch",
                    })
                return changes

            def report(progress: int, step: str, **meta: Any):
                if progress_callback:
                    progress_callback(progress, step, **meta)

            report(2, "准备刷新选中作品", total_count=total, processed_count=0, changed_count=0)

            for index, row in enumerate(rows, start=1):
                if cancel_callback and cancel_callback():
                    raise RuntimeError("用户取消")
                canonical = self.normalize_rjcode(row.canonical_rjcode)
                preferred_seed = row.display_rjcode or canonical
                previous_snapshot = {
                    "display_rjcode": str(row.display_rjcode or "").strip(),
                    "asmr_available_rjcode": str(row.asmr_available_rjcode or "").strip(),
                    "has_asmr_one": bool(row.has_asmr_one),
                    "has_kikoeru": bool(row.has_kikoeru),
                    "source_mask": str(row.source_mask or "").strip(),
                    "found_rjcodes": list(row.kikoeru_found_rjcodes or []),
                    "subtitle_rjcodes": list(row.kikoeru_subtitle_rjcodes or []),
                }
                report(
                    min(96, 5 + int(((index - 1) / max(total, 1)) * 88)),
                    f"刷新作品 {index}/{total}",
                    total_count=total,
                    processed_count=index - 1,
                    current_rjcode=canonical,
                    current_display_rjcode=preferred_seed,
                )
                canonical_info = await self.resolve_canonical_rj(canonical, refresh=force_refresh)
                preferred_variant = self._preferred_variant(canonical_info, preferred_seed)

                metadata = {}
                metadata_map: Dict[str, Dict[str, Any]] = {}
                for candidate in [canonical, preferred_variant.get("rjcode"), row.asmr_available_rjcode, *(row.linked_rjcodes or [])]:
                    normalized = self.normalize_rjcode(candidate)
                    if not normalized:
                        continue
                    try:
                        fetched_metadata = await self._fetch_metadata_dict(normalized, refresh=force_refresh)
                    except Exception:
                        fetched_metadata = {}
                    metadata_map[normalized] = fetched_metadata or {}
                    if fetched_metadata and not metadata:
                        metadata = fetched_metadata
                public_variants = await self._list_public_display_variants(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map,
                )
                linked_rjcodes = [variant["rjcode"] for variant in public_variants if variant.get("rjcode")]
                preferred_variant, preferred_title = await self._pick_public_display_variant_and_title(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map,
                )

                probe_candidates = await self._build_public_download_probe_candidates(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map=metadata_map,
                    extra_candidates=[preferred_variant.get("rjcode"), canonical, row.asmr_available_rjcode, *linked_rjcodes],
                )
                actual_rjcode, _ = await self._find_public_downloadable_work(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map=metadata_map,
                    extra_candidates=probe_candidates,
                )
                actual_norm = self.normalize_rjcode(actual_rjcode)

                kikoeru_state = await self._probe_kikoeru_state_for_candidates(
                    probe_candidates or [canonical],
                    use_cache=not force_refresh,
                )
                found_rjcodes = _normalize_code_list(kikoeru_state.get("found_rjcodes") or [])
                subtitle_rjcodes = _normalize_code_list(kikoeru_state.get("subtitle_rjcodes") or [])
                source_flags = {flag for flag in str(row.source_mask or "").split(",") if flag}
                if row.has_dlsite:
                    source_flags.add("dlsite")
                if actual_norm:
                    source_flags.add("asmr_one")
                else:
                    source_flags.discard("asmr_one")
                if found_rjcodes:
                    source_flags.add("kikoeru")
                else:
                    source_flags.discard("kikoeru")

                row.display_rjcode = self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical or row.display_rjcode
                row.title = preferred_title or str((metadata_map.get(row.display_rjcode) or {}).get("work_name") or row.title or "").strip() or row.title
                row.maker_id = str(metadata.get("maker_id") or row.maker_id or "").strip() or row.maker_id
                row.maker_name = str(metadata.get("maker_name") or row.maker_name or "").strip() or row.maker_name
                row.linked_rjcodes = linked_rjcodes or [row.display_rjcode or canonical]
                row.has_kikoeru = bool(found_rjcodes)
                row.kikoeru_found_rjcodes = found_rjcodes
                row.kikoeru_subtitle_rjcodes = subtitle_rjcodes
                row.has_asmr_one = bool(actual_norm)
                row.asmr_available_rjcode = actual_norm or None
                row.source_mask = ",".join(sorted(source_flags))
                row.updated_at = datetime.now()
                row.asmr_one_cached_at = datetime.now() if actual_norm else None

                refreshed_count += 1
                if row.has_asmr_one:
                    asmr_available_count += 1
                if row.has_kikoeru:
                    kikoeru_owned_count += 1
                normalized_found_rjcodes = _normalize_code_list(row.kikoeru_found_rjcodes or [])
                normalized_subtitle_rjcodes = _normalize_code_list(row.kikoeru_subtitle_rjcodes or [])
                server_match_primary_rjcode = _pick_server_primary(normalized_found_rjcodes, canonical_info, preferred_seed or canonical)
                subtitle_present = bool(normalized_subtitle_rjcodes)
                change_details = _build_refresh_change_details(
                    previous_snapshot,
                    after_display_rjcode=str(row.display_rjcode or "").strip(),
                    after_asmr_rjcode=str(row.asmr_available_rjcode or "").strip(),
                    after_has_asmr_one=bool(row.has_asmr_one),
                    after_has_kikoeru=bool(row.has_kikoeru),
                    after_source_mask=str(row.source_mask or "").strip(),
                    after_found_rjcodes=normalized_found_rjcodes,
                    after_subtitle_rjcodes=normalized_subtitle_rjcodes,
                    canonical_info_map=canonical_info,
                )
                changed = bool(change_details)
                source_compare = self._build_source_compare({
                    "canonical_rjcode": row.canonical_rjcode,
                    "display_rjcode": row.display_rjcode,
                    "asmr_available_rjcode": row.asmr_available_rjcode,
                    "kikoeru_found_rjcodes": normalized_found_rjcodes,
                    "kikoeru_subtitle_rjcodes": normalized_subtitle_rjcodes,
                    "preferred_variant": preferred_variant,
                }, canonical_info, metadata_map=None)
                refreshed_items.append({
                    "canonical_rjcode": row.canonical_rjcode,
                    "title": row.title or "",
                    "display_rjcode": row.display_rjcode,
                    "preferred_variant_label": (self._variant_group(preferred_variant.get("link_type"), preferred_variant.get("lang")).get("short_label") or "其他"),
                    "has_asmr_one": bool(row.has_asmr_one),
                    "has_kikoeru": bool(row.has_kikoeru),
                    "asmr_available_rjcode": row.asmr_available_rjcode or "",
                    "server_match_rjcodes": normalized_found_rjcodes,
                    "server_match_primary_rjcode": server_match_primary_rjcode,
                    "subtitle_present": subtitle_present,
                    "changed": changed,
                    "change_count": len(change_details),
                    "change_flags": {
                        "server_state_changed": any(change.get("key") == "server_state" for change in change_details),
                        "server_rjcode_changed": any(change.get("key") == "server_rjcode" for change in change_details),
                        "subtitle_state_changed": any(change.get("key") == "subtitle_state" for change in change_details),
                        "asmr_state_changed": any(change.get("key") in {"asmr_available", "asmr_rjcode"} for change in change_details),
                        "preferred_rj_changed": any(change.get("key") == "preferred_rjcode" for change in change_details),
                    },
                    "change_details": change_details,
                    "source_compare": source_compare,
                })
                report(
                    min(96, 5 + int((index / max(total, 1)) * 88)),
                    f"已刷新 {index}/{total}",
                    total_count=total,
                    processed_count=index,
                    changed_count=len([item for item in refreshed_items if item.get("changed")]),
                    current_rjcode=canonical,
                    current_display_rjcode=row.display_rjcode,
                    asmr_available_count=asmr_available_count,
                    kikoeru_owned_count=kikoeru_owned_count,
                    force_refresh=bool(force_refresh),
                )

            catalog.last_indexed_at = datetime.now()
            catalog.updated_at = datetime.now()
            db.commit()
            changed_count = len([item for item in refreshed_items if item.get("changed")])
            report(
                100,
                "批量刷新完成",
                total_count=total,
                processed_count=refreshed_count,
                changed_count=changed_count,
                asmr_available_count=asmr_available_count,
                kikoeru_owned_count=kikoeru_owned_count,
                force_refresh=bool(force_refresh),
            )

            log_circle_completion_event(
                "refresh_selected_works",
                summary=f"批量刷新社团作品状态完成：{catalog.circle_name or circle_id}，共 {refreshed_count} 个",
                circle_id=circle_id,
                circle_name=catalog.circle_name,
                detail={
                    "selected_count": len(normalized_codes),
                    "refreshed_count": refreshed_count,
                    "changed_count": changed_count,
                    "asmr_available_count": asmr_available_count,
                    "kikoeru_owned_count": kikoeru_owned_count,
                    "force_refresh": bool(force_refresh),
                    "canonical_rjcodes": normalized_codes[:200],
                    "refreshed_items": refreshed_items[:50],
                },
            )
            return {
                "circle_id": circle_id,
                "circle_name": catalog.circle_name,
                "selected_count": len(normalized_codes),
                "refreshed_count": refreshed_count,
                "changed_count": changed_count,
                "asmr_available_count": asmr_available_count,
                "kikoeru_owned_count": kikoeru_owned_count,
                "force_refresh": bool(force_refresh),
                "items": refreshed_items,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def list_recent_indexes(self, limit: int = 20) -> List[Dict[str, Any]]:
        return await self.search_circles("", limit=limit)


_circle_completion_service: Optional[CircleCompletionService] = None


def get_circle_completion_service() -> CircleCompletionService:
    global _circle_completion_service
    if _circle_completion_service is None:
        _circle_completion_service = CircleCompletionService()
    return _circle_completion_service
