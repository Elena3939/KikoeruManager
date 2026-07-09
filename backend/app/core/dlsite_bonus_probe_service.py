from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from ..config.settings import BonusProbeConfig, get_config
from ..models.database import (
    CircleCatalog,
    CircleExternalIdentity,
    CircleWork,
    DLsiteBonusProbeCache,
    DLsiteBonusProbeDate,
    DLsiteBonusOriginalProbeState,
    DLsiteBonusProbeHitIndex,
    SessionLocal,
    WorkCanonicalLink,
    WorkMetadata,
)
from .dlsite_service import DLsiteProductProbeFeature, get_dlsite_service
from .resource_budget_service import get_resource_budget_service

logger = logging.getLogger(__name__)
_POSTGRES_BIGINT_MAX = 9223372036854775807


class DLsiteBonusProbeService:
    """DLsite 官方数据源隐藏特典探测服务。"""

    DEFAULT_GAP_LIMIT = 500
    DEFAULT_EDGE_WINDOW = 80
    DEFAULT_CIRCLE_EDGE_WINDOW = 2000
    DEFAULT_DATE_RANGE_LIMIT = 80000
    DEFAULT_BATCH_SIZE = 100
    DEFAULT_CONCURRENCY = 1
    DEFAULT_MAX_DATE_WORKERS = 3
    DEFAULT_PRODUCT_INFO_CONCURRENCY = 2
    DEFAULT_CACHE_LOOKUP_BATCH_SIZE = 500
    DEFAULT_CACHE_WRITE_BATCH_SIZE = 100
    PROBE_STRATEGY_VERSION = "date-range-v4"

    def __init__(self) -> None:
        self.dlsite_service = get_dlsite_service()
        self._active_probe_rjcodes: set[str] = set()
        self._active_probe_lock = asyncio.Lock()
        self._active_job_semaphore: Optional[asyncio.Semaphore] = None
        self._active_job_limit = 0
        self._cache_flush_task: Optional[asyncio.Task] = None
        self._cache_flush_stop_event: Optional[asyncio.Event] = None

    def _bonus_probe_config(self) -> BonusProbeConfig:
        try:
            return getattr(get_config(), "bonus_probe", BonusProbeConfig()) or BonusProbeConfig()
        except Exception:
            return BonusProbeConfig()

    def resolve_probe_runtime_limits(
        self,
        *,
        mode: str = "normal",
        batch_size: Optional[int] = None,
        concurrency: Optional[int] = None,
    ) -> Dict[str, int]:
        cfg = self._bonus_probe_config()
        mode_key = str(mode or "normal").strip().lower() or "normal"
        if mode_key == "deep":
            default_batch_size = int(cfg.deep_batch_size)
            default_concurrency = int(cfg.deep_concurrency)
        elif mode_key == "new_release":
            default_batch_size = int(cfg.new_release_batch_size)
            default_concurrency = int(cfg.new_release_concurrency)
        else:
            default_batch_size = int(cfg.normal_batch_size)
            default_concurrency = int(cfg.normal_concurrency)
        max_concurrency = min(max(1, int(cfg.max_concurrency or self.DEFAULT_MAX_DATE_WORKERS)), self.DEFAULT_MAX_DATE_WORKERS)
        date_concurrency = min(max(1, int(concurrency or default_concurrency)), max_concurrency)
        return {
            "batch_size": min(max(1, int(batch_size or default_batch_size)), int(cfg.max_batch_size)),
            "concurrency": date_concurrency,
            "product_info_concurrency": min(date_concurrency, self.DEFAULT_PRODUCT_INFO_CONCURRENCY),
            "max_active_jobs": max(1, int(cfg.max_active_jobs or 1)),
            "cache_lookup_batch_size": max(100, int(cfg.cache_lookup_batch_size or self.DEFAULT_CACHE_LOOKUP_BATCH_SIZE)),
            "cache_write_batch_size": min(
                max(20, int(cfg.cache_write_batch_size or self.DEFAULT_CACHE_WRITE_BATCH_SIZE)),
                self.DEFAULT_CACHE_WRITE_BATCH_SIZE,
            ),
        }

    def _cache_lookup_batch_size(self) -> int:
        return int(self.resolve_probe_runtime_limits()["cache_lookup_batch_size"])

    def _cache_write_batch_size(self) -> int:
        return int(self.resolve_probe_runtime_limits()["cache_write_batch_size"])

    def _active_job_slot(self) -> asyncio.Semaphore:
        max_active_jobs = int(self.resolve_probe_runtime_limits()["max_active_jobs"])
        semaphore = getattr(self, "_active_job_semaphore", None)
        if semaphore is None or int(getattr(self, "_active_job_limit", 0) or 0) != max_active_jobs:
            semaphore = asyncio.Semaphore(max_active_jobs)
            self._active_job_semaphore = semaphore
            self._active_job_limit = max_active_jobs
        return semaphore

    @asynccontextmanager
    async def _acquire_active_job_slot(self, job_id: str = ""):
        semaphore = self._active_job_slot()
        await semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()

    def normalize_rjcode(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.search(r"RJ(\d{6}|\d{8})(?!\d)", text, re.IGNORECASE)
        return f"RJ{match.group(1)}" if match else text

    def normalize_date(self, value: Any) -> str:
        return self.dlsite_service._normalize_date_text(value)

    def _full_release_date(self, value: Any) -> str:
        normalized = str(self.normalize_date(value) or "").strip()
        return normalized if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", normalized) else ""

    def _persist_precise_release_dates(
        self,
        *,
        rjcodes: Sequence[str],
        maker_id: str,
        release_date: str,
        circle_id: str = "",
    ) -> None:
        normalized_date = self._full_release_date(release_date)
        normalized_rjcodes = self._dedupe(rjcodes)
        normalized_maker = str(maker_id or "").strip().upper()
        if not normalized_date or not normalized_rjcodes:
            return

        db = SessionLocal()
        try:
            existing_rows = {
                self.normalize_rjcode(row.rjcode): row
                for row in db.query(WorkMetadata)
                .filter(WorkMetadata.rjcode.in_(normalized_rjcodes))
                .all()
            }
            has_changes = False
            changed_rjcodes: List[str] = []
            now = datetime.now()
            for rjcode in normalized_rjcodes:
                row = existing_rows.get(rjcode)
                if row is None:
                    row = WorkMetadata(rjcode=rjcode)
                    db.add(row)
                    has_changes = True
                if normalized_maker and not str(row.maker_id or "").strip():
                    row.maker_id = normalized_maker
                    has_changes = True
                if str(row.release_date or "").strip() != normalized_date:
                    row.release_date = normalized_date
                    row.cached_at = now
                    has_changes = True
                    changed_rjcodes.append(rjcode)
            if has_changes:
                db.commit()
            if changed_rjcodes:
                try:
                    from .circle_completion_service import get_circle_completion_service

                    circle_service = get_circle_completion_service()
                    if circle_id:
                        circle_service.invalidate_completion_view_cache(circle_id)
                    for rjcode in changed_rjcodes:
                        circle_service._metadata_cache.pop(rjcode, None)
                except Exception:
                    logger.debug(
                        "[DLsite特典探测] 精确发售日写回后清理社团补全缓存失败 circle=%s rjcodes=%s",
                        circle_id,
                        changed_rjcodes[:10],
                        exc_info=True,
                    )
        except Exception:
            db.rollback()
            logger.debug(
                "[DLsite特典探测] 写回作品精确发售日失败 maker=%s date=%s rjcodes=%s",
                normalized_maker,
                normalized_date,
                normalized_rjcodes[:10],
                exc_info=True,
            )
        finally:
            db.close()

    def _rj_number(self, rjcode: Any) -> Optional[Tuple[int, int]]:
        normalized = self.normalize_rjcode(rjcode)
        match = re.fullmatch(r"RJ(\d{6}|\d{8})", normalized)
        if not match:
            return None
        digits = match.group(1)
        return int(digits), len(digits)

    def _dedupe(self, values: Iterable[Any]) -> List[str]:
        result: List[str] = []
        for value in values or []:
            normalized = self.normalize_rjcode(value)
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _public_original_worknos_from_rows(self, rows: Iterable[CircleWork]) -> List[str]:
        return self._dedupe(
            row.canonical_rjcode
            for row in rows or []
            if not bool(row.is_bonus_work) and row.canonical_rjcode
        )

    def _completed_original_state_map(self, db, circle_id: str, rjcodes: Sequence[str]) -> Dict[str, str]:
        normalized = self._dedupe(rjcodes)
        if not circle_id or not normalized:
            return {}
        rows = (
            db.query(DLsiteBonusOriginalProbeState)
            .filter(
                DLsiteBonusOriginalProbeState.circle_id == circle_id,
                DLsiteBonusOriginalProbeState.original_rjcode.in_(normalized),
                DLsiteBonusOriginalProbeState.strategy_version == self.PROBE_STRATEGY_VERSION,
                DLsiteBonusOriginalProbeState.status.in_(("no_bonus", "has_bonus")),
            )
            .all()
        )
        return {
            self.normalize_rjcode(row.original_rjcode): str(row.status or "").strip()
            for row in rows
        }

    def _upsert_original_probe_state(
        self,
        db,
        *,
        circle_id: str,
        maker_id: str,
        original_rjcode: str,
        release_date: str,
        status: str,
    ) -> None:
        normalized_original = self.normalize_rjcode(original_rjcode)
        normalized_status = str(status or "").strip()
        if not circle_id or not normalized_original or normalized_status not in {"no_bonus", "has_bonus"}:
            return
        row = next(
            (
                pending
                for pending in db.new
                if isinstance(pending, DLsiteBonusOriginalProbeState)
                and str(pending.circle_id or "") == circle_id
                and self.normalize_rjcode(pending.original_rjcode) == normalized_original
            ),
            None,
        )
        if row is None:
            row = (
                db.query(DLsiteBonusOriginalProbeState)
                .filter(
                    DLsiteBonusOriginalProbeState.circle_id == circle_id,
                    DLsiteBonusOriginalProbeState.original_rjcode == normalized_original,
                )
                .first()
            )
        if row is None:
            row = DLsiteBonusOriginalProbeState(
                circle_id=circle_id,
                original_rjcode=normalized_original,
            )
            db.add(row)
        row.maker_id = str(maker_id or "").strip().upper()
        row.release_date = self.normalize_date(release_date)
        row.status = normalized_status
        row.strategy_version = self.PROBE_STRATEGY_VERSION
        row.checked_at = datetime.now()
        row.updated_at = datetime.now()

    def _upsert_bonus_hit_index(
        self,
        db,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        bonus_rjcode: str,
    ) -> None:
        normalized_bonus = self.normalize_rjcode(bonus_rjcode)
        normalized_maker = str(maker_id or "").strip().upper()
        if not normalized_maker or not normalized_bonus:
            return
        row = (
            db.query(DLsiteBonusProbeHitIndex)
            .filter(
                DLsiteBonusProbeHitIndex.maker_id == normalized_maker,
                DLsiteBonusProbeHitIndex.bonus_rjcode == normalized_bonus,
            )
            .first()
        )
        if row is None:
            row = DLsiteBonusProbeHitIndex(
                maker_id=normalized_maker,
                bonus_rjcode=normalized_bonus,
            )
            db.add(row)
        row.circle_id = circle_id or row.circle_id or ""
        row.release_date = self.normalize_date(release_date)
        row.updated_at = datetime.now()

    def _build_gap_candidates(
        self,
        public_worknos: Sequence[str],
        gap_limit: int,
        *,
        include_edges: bool = True,
        edge_window_limit: Optional[int] = None,
    ) -> Tuple[List[str], int, bool]:
        parsed: List[Tuple[int, int, str]] = []
        seen: set[str] = set()
        for workno in public_worknos or []:
            normalized = self.normalize_rjcode(workno)
            if not normalized or normalized in seen:
                continue
            number = self._rj_number(normalized)
            if not number:
                continue
            seen.add(normalized)
            parsed.append((number[0], number[1], normalized))
        parsed.sort(key=lambda item: item[0])

        safe_limit = max(1, int(gap_limit or self.DEFAULT_GAP_LIMIT))
        edge_window = min(safe_limit, self.DEFAULT_EDGE_WINDOW)
        if edge_window_limit is not None:
            edge_window = max(1, int(edge_window_limit or 1))
        candidates_by_number: Dict[int, str] = {}
        public_numbers = {item[0] for item in parsed}

        def add_candidate(number: int, width: int) -> None:
            if number <= 0 or number in public_numbers:
                return
            candidates_by_number.setdefault(number, f"RJ{number:0{width}d}")

        gap_count = 0
        budget_reached = False
        for left, right in zip(parsed, parsed[1:]):
            left_number, left_width, _ = left
            right_number, right_width, _ = right
            gap_size = right_number - left_number - 1
            if gap_size <= 0:
                continue
            if gap_size > safe_limit:
                budget_reached = True
                continue
            gap_count += 1
            width = max(left_width, right_width)
            for number in range(left_number + 1, right_number):
                add_candidate(number, width)

        if include_edges:
            # 很多社团一天只发一个公开 RJ，或者公开 RJ 彼此相邻；旧逻辑只探“两个公开
            # RJ 之间”的缺口，这两种现场会直接产生 0 个候选。隐藏特典通常和公开作品
            # 注册号相邻，因此补一个受限边缘窗口，避免单作品日期永远探不到。
            for number, width, _ in parsed:
                for offset in range(1, edge_window + 1):
                    add_candidate(number - offset, width)
                    add_candidate(number + offset, width)

        candidates = [candidates_by_number[number] for number in sorted(candidates_by_number)]
        return candidates, gap_count, budget_reached

    def _build_range_candidates(
        self,
        public_worknos: Sequence[str],
        *,
        range_limit: Optional[int] = None,
        enforce_limit: bool = True,
    ) -> Tuple[List[str], int, bool]:
        parsed: List[Tuple[int, int, str]] = []
        seen: set[str] = set()
        for workno in public_worknos or []:
            normalized = self.normalize_rjcode(workno)
            if not normalized or normalized in seen:
                continue
            number = self._rj_number(normalized)
            if not number:
                continue
            seen.add(normalized)
            parsed.append((number[0], number[1], normalized))
        if len(parsed) < 2:
            return [], 0, False
        parsed.sort(key=lambda item: item[0])
        left_number, left_width, _ = parsed[0]
        right_number, right_width, _ = parsed[-1]
        range_count = max(0, right_number - left_number - 1)
        safe_limit = max(1, int(range_limit if range_limit is not None else self.DEFAULT_DATE_RANGE_LIMIT))
        if enforce_limit and range_count > safe_limit:
            return [], range_count, True
        public_numbers = {item[0] for item in parsed}
        width = max(left_width, right_width)
        candidates = [
            f"RJ{number:0{width}d}"
            for number in range(left_number + 1, right_number)
            if number not in public_numbers
        ]
        return candidates, range_count, False

    def _build_anchor_edge_candidates(
        self,
        anchor_worknos: Sequence[str],
        *,
        edge_window_limit: int,
    ) -> List[str]:
        parsed: List[Tuple[int, int, str]] = []
        seen: set[str] = set()
        for workno in anchor_worknos or []:
            normalized = self.normalize_rjcode(workno)
            if not normalized or normalized in seen:
                continue
            number = self._rj_number(normalized)
            if not number:
                continue
            seen.add(normalized)
            parsed.append((number[0], number[1], normalized))
        if not parsed:
            return []

        edge_window = max(1, int(edge_window_limit or self.DEFAULT_CIRCLE_EDGE_WINDOW))
        anchor_numbers = {item[0] for item in parsed}
        candidates_by_number: Dict[int, str] = {}
        for anchor_number, width, _ in parsed:
            for offset in range(1, edge_window + 1):
                for candidate_number in (anchor_number - offset, anchor_number + offset):
                    if candidate_number <= 0 or candidate_number in anchor_numbers:
                        continue
                    candidates_by_number.setdefault(candidate_number, f"RJ{candidate_number:0{width}d}")
        return [candidates_by_number[number] for number in sorted(candidates_by_number)]

    def _chunk(self, values: Sequence[str], size: int) -> Iterable[List[str]]:
        safe_size = max(1, int(size or self.DEFAULT_BATCH_SIZE))
        for index in range(0, len(values), safe_size):
            yield list(values[index:index + safe_size])

    def _candidate_shard_key(self, rjcode: Any) -> int:
        number = self._rj_number(rjcode)
        return number[0] if number else 0

    def _split_candidate_shards(self, candidates: Sequence[str], shard_size: int) -> List[Dict[str, Any]]:
        ordered = sorted(self._dedupe(candidates), key=lambda item: (self._candidate_shard_key(item), item))
        shards: List[Dict[str, Any]] = []
        for index, values in enumerate(self._chunk(ordered, shard_size), start=1):
            if not values:
                continue
            shards.append({
                "index": index,
                "rjcodes": values,
                "start_rjcode": values[0],
                "end_rjcode": values[-1],
                "count": len(values),
                "range_key": f"{values[0]}:{values[-1]}",
            })
        return shards

    def _exclude_unprobeable_candidates(
        self,
        candidates: Sequence[str],
        *,
        active_rjcodes: Optional[Iterable[str]] = None,
    ) -> Tuple[List[str], Dict[str, int]]:
        normalized = self._dedupe(candidates)
        stats = {"input": len(normalized), "cached": 0, "active": 0, "cooldown": 0, "selected": 0}
        if not normalized:
            return [], stats

        active_set = {self.normalize_rjcode(value) for value in (active_rjcodes or []) if self.normalize_rjcode(value)}
        cached = self._load_cached_features_sync(normalized)
        selected: List[str] = []
        for rjcode in normalized:
            feature = cached.get(rjcode)
            if feature is not None and str(feature.probe_status or "").strip() in {"ok", "missing"}:
                stats["cached"] += 1
                continue
            if rjcode in active_set:
                stats["active"] += 1
                continue
            if feature is not None and str(feature.probe_status or "").strip() == "error":
                stats["cooldown"] += 1
                continue
            selected.append(rjcode)
        stats["selected"] = len(selected)
        return selected, stats

    def _merge_candidate_shards(self, shards: Sequence[Dict[str, Any]]) -> List[str]:
        merged: List[str] = []
        for shard in shards or []:
            for rjcode in list((shard or {}).get("rjcodes") or []):
                normalized = self.normalize_rjcode(rjcode)
                if normalized and normalized not in merged:
                    merged.append(normalized)
        return merged

    def _ensure_active_probe_state(self) -> None:
        if not hasattr(self, "_active_probe_rjcodes"):
            self._active_probe_rjcodes = set()
        if not hasattr(self, "_active_probe_lock"):
            self._active_probe_lock = asyncio.Lock()

    async def _lease_candidate_shards(
        self,
        candidates: Sequence[str],
        *,
        shard_size: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        self._ensure_active_probe_state()
        async with self._active_probe_lock:
            selected, stats = self._exclude_unprobeable_candidates(
                candidates,
                active_rjcodes=self._active_probe_rjcodes,
            )
            shards = self._split_candidate_shards(selected, shard_size)
            leased = self._merge_candidate_shards(shards)
            self._active_probe_rjcodes.update(leased)
            stats["leased"] = len(leased)
            return shards, stats

    async def _release_candidate_shards(self, shards: Sequence[Dict[str, Any]]) -> None:
        self._ensure_active_probe_state()
        leased = set(self._merge_candidate_shards(shards))
        if not leased:
            return
        async with self._active_probe_lock:
            self._active_probe_rjcodes.difference_update(leased)

    def _feature_from_cache_row(self, row: DLsiteBonusProbeCache) -> DLsiteProductProbeFeature:
        return DLsiteProductProbeFeature(
            workno=self.normalize_rjcode(row.rjcode),
            exists=bool(row.exists),
            probe_status=row.probe_status or "missing",
            maker_id=row.maker_id or "",
            release_date=row.release_date or "",
            work_type=row.work_type or "",
            price=int(row.price or 0),
            is_sale=bool(row.is_sale),
            is_free=bool(row.is_free),
            is_oly=bool(row.is_oly),
            wishlist_count=int(row.wishlist_count or 0),
            is_hidden_bonus_audio=bool(row.is_hidden_bonus_audio),
            title=row.title or "",
            raw_summary_json=dict(row.raw_summary_json or {}),
            error_message=row.error_message or "",
        )

    def _cache_bool(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _cache_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _cache_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text:
                try:
                    if text.endswith("Z"):
                        text = f"{text[:-1]}+00:00"
                    return datetime.fromisoformat(text)
                except ValueError:
                    pass
        return datetime.now()

    def _feature_from_cache_payload(self, payload: Dict[str, Any]) -> DLsiteProductProbeFeature:
        return DLsiteProductProbeFeature(
            workno=self.normalize_rjcode(payload.get("rjcode") or payload.get("workno")),
            exists=self._cache_bool(payload.get("exists")),
            probe_status=str(payload.get("probe_status") or "missing"),
            maker_id=str(payload.get("maker_id") or ""),
            release_date=str(payload.get("release_date") or ""),
            work_type=str(payload.get("work_type") or ""),
            price=self._cache_int(payload.get("price")),
            is_sale=self._cache_bool(payload.get("is_sale")),
            is_free=self._cache_bool(payload.get("is_free")),
            is_oly=self._cache_bool(payload.get("is_oly")),
            wishlist_count=self._cache_int(payload.get("wishlist_count")),
            is_hidden_bonus_audio=self._cache_bool(payload.get("is_hidden_bonus_audio")),
            title=str(payload.get("title") or ""),
            raw_summary_json=dict(payload.get("raw_summary_json") or {}),
            error_message=str(payload.get("error_message") or ""),
        )

    def _upsert_cache_row(self, db, feature: DLsiteProductProbeFeature) -> None:
        workno = self.normalize_rjcode(feature.workno)
        if not workno:
            return
        row = db.query(DLsiteBonusProbeCache).filter(DLsiteBonusProbeCache.rjcode == workno).first()
        if row is None:
            row = DLsiteBonusProbeCache(rjcode=workno)
            db.add(row)
        row.exists = bool(feature.exists)
        row.probe_status = feature.probe_status or "missing"
        row.maker_id = feature.maker_id or ""
        row.release_date = feature.release_date or ""
        row.work_type = feature.work_type or ""
        row.price = self._safe_cache_int(feature.price, field="price", workno=feature.workno)
        row.is_sale = bool(feature.is_sale)
        row.is_free = bool(feature.is_free)
        row.is_oly = bool(feature.is_oly)
        row.wishlist_count = self._safe_cache_int(feature.wishlist_count, field="wishlist_count", workno=feature.workno)
        row.is_hidden_bonus_audio = bool(feature.is_hidden_bonus_audio)
        row.title = feature.title or ""
        row.raw_summary_json = dict(feature.raw_summary_json or {})
        row.error_message = feature.error_message or None
        row.checked_at = datetime.now()
        row.updated_at = datetime.now()

    def _load_cached_features_sync(self, normalized: Sequence[str]) -> Dict[str, DLsiteProductProbeFeature]:
        features: Dict[str, DLsiteProductProbeFeature] = {}
        if not normalized:
            return features
        try:
            from .redis_service import get_redis_service

            redis_rows = get_redis_service().read_bonus_probe_cache_rows_sync(normalized)
            for rjcode, payload in redis_rows.items():
                normalized_rjcode = self.normalize_rjcode(rjcode)
                if normalized_rjcode:
                    features[normalized_rjcode] = self._feature_from_cache_payload(payload)
        except Exception:
            logger.debug("[DLsite特典探测] 读取 Redis 缓存 overlay 失败", exc_info=True)

        missing = [workno for workno in normalized if workno not in features]
        if not missing:
            return features
        db = SessionLocal()
        try:
            for batch in self._chunk(list(missing), self._cache_lookup_batch_size()):
                rows = (
                    db.query(DLsiteBonusProbeCache)
                    .filter(DLsiteBonusProbeCache.rjcode.in_(batch))
                    .all()
                )
                for row in rows:
                    features[self.normalize_rjcode(row.rjcode)] = self._feature_from_cache_row(row)
        finally:
            db.close()
        return features

    def _cache_values_from_feature(self, feature: DLsiteProductProbeFeature) -> Dict[str, Any]:
        now = datetime.now()
        return {
            "rjcode": self.normalize_rjcode(feature.workno),
            "exists": bool(feature.exists),
            "probe_status": feature.probe_status or "missing",
            "maker_id": feature.maker_id or "",
            "release_date": feature.release_date or "",
            "work_type": feature.work_type or "",
            "price": self._safe_cache_int(feature.price, field="price", workno=feature.workno),
            "is_sale": bool(feature.is_sale),
            "is_free": bool(feature.is_free),
            "is_oly": bool(feature.is_oly),
            "wishlist_count": self._safe_cache_int(feature.wishlist_count, field="wishlist_count", workno=feature.workno),
            "is_hidden_bonus_audio": bool(feature.is_hidden_bonus_audio),
            "title": feature.title or "",
            "raw_summary_json": dict(feature.raw_summary_json or {}),
            "error_message": feature.error_message or None,
            "checked_at": now,
            "created_at": now,
            "updated_at": now,
        }

    def _safe_cache_int(self, value: Any, *, field: str, workno: str) -> int:
        if value is None or isinstance(value, bool):
            return 0
        try:
            number = int(value)
        except Exception:
            logger.debug("[DLsite特典探测] 缓存数值字段无法解析 workno=%s field=%s value=%r", workno, field, value)
            return 0
        if number < 0:
            return 0
        if number > _POSTGRES_BIGINT_MAX:
            logger.warning(
                "[DLsite特典探测] 缓存数值字段超过 PostgreSQL BIGINT 范围，已按 0 处理 workno=%s field=%s value=%s",
                workno,
                field,
                value,
            )
            return 0
        return number

    def _is_fatal_probe_exception(self, exc: BaseException) -> bool:
        if isinstance(exc, (asyncio.CancelledError, SQLAlchemyError, DBAPIError)):
            return True
        text = str(exc or "").lower()
        fatal_markers = (
            "integer out of range",
            "numericvalueoutofrange",
            "stringdatarighttruncation",
            "value too long for type",
            "transaction is aborted",
            "connection is closed",
            "database is closed",
            "deadlock detected",
        )
        return any(marker in text for marker in fatal_markers)

    def _failed_date_result(self, *, circle_id: str, maker_id: str, release_date: str, exc: BaseException) -> Dict[str, Any]:
        message = str(exc or exc.__class__.__name__).strip() or exc.__class__.__name__
        return {
            "circle_id": circle_id,
            "maker_id": maker_id,
            "release_date": release_date,
            "parse_status": "failed",
            "public_count": 0,
            "date_page_public_count": 0,
            "sou_public_count": 0,
            "gap_count": 0,
            "circle_gap_count": 0,
            "date_page_range_count": 0,
            "probe_count": 0,
            "cached_hit_count": 0,
            "request_count": 0,
            "hit_count": 0,
            "inserted_count": 0,
            "budget_reached": False,
            "failed": True,
            "incomplete": True,
            "error_message": message[:2000],
        }

    def _normalize_cache_value_row(self, value: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(value or {})
        rjcode = self.normalize_rjcode(row.get("rjcode") or row.get("workno"))
        if not rjcode:
            return {}
        return {
            "rjcode": rjcode,
            "exists": self._cache_bool(row.get("exists")),
            "probe_status": str(row.get("probe_status") or "missing"),
            "maker_id": str(row.get("maker_id") or ""),
            "release_date": str(row.get("release_date") or ""),
            "work_type": str(row.get("work_type") or ""),
            "price": self._safe_cache_int(row.get("price"), field="price", workno=rjcode),
            "is_sale": self._cache_bool(row.get("is_sale")),
            "is_free": self._cache_bool(row.get("is_free")),
            "is_oly": self._cache_bool(row.get("is_oly")),
            "wishlist_count": self._safe_cache_int(row.get("wishlist_count"), field="wishlist_count", workno=rjcode),
            "is_hidden_bonus_audio": self._cache_bool(row.get("is_hidden_bonus_audio")),
            "title": str(row.get("title") or ""),
            "raw_summary_json": dict(row.get("raw_summary_json") or {}),
            "error_message": str(row.get("error_message") or "") or None,
            "checked_at": self._cache_datetime(row.get("checked_at")),
            "created_at": self._cache_datetime(row.get("created_at")),
            "updated_at": self._cache_datetime(row.get("updated_at")),
        }

    def _upsert_cache_values_sync(self, values: Sequence[Dict[str, Any]]) -> None:
        rows_by_rjcode: Dict[str, Dict[str, Any]] = {}
        for value in values or []:
            row = self._normalize_cache_value_row(value)
            if row:
                rows_by_rjcode[row["rjcode"]] = row
        rows = list(rows_by_rjcode.values())
        if not rows:
            return
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync(
                "bonus_probe_database_write",
                reason="dlsite_bonus_probe.cache_upsert",
            ):
                table = DLsiteBonusProbeCache.__table__
                for batch in self._chunk(rows, self._cache_write_batch_size()):
                    stmt = pg_insert(table).values(batch)
                    update_columns = {
                        column.name: getattr(stmt.excluded, column.name)
                        for column in table.columns
                        if column.name not in {"rjcode", "created_at"}
                    }
                    changed_columns = [
                        column.name
                        for column in table.columns
                        if column.name not in {"rjcode", "created_at", "checked_at", "updated_at"}
                    ]
                    db.execute(stmt.on_conflict_do_update(
                        index_elements=[table.c.rjcode],
                        set_=update_columns,
                        where=or_(*[
                            table.c[column_name].is_distinct_from(getattr(stmt.excluded, column_name))
                            for column_name in changed_columns
                        ]),
                    ))
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _upsert_cache_features_sync(self, features: Sequence[DLsiteProductProbeFeature]) -> None:
        values = [
            self._cache_values_from_feature(feature)
            for feature in features or []
            if self.normalize_rjcode(feature.workno)
        ]
        if not values:
            return
        try:
            from .redis_service import get_redis_service

            written = get_redis_service().write_bonus_probe_cache_dirty_sync(values)
            if written == len(values):
                return
            logger.warning(
                "[DLsite特典探测] Redis dirty buffer 写入不完整，回退 PostgreSQL 同步写入 written=%s total=%s",
                written,
                len(values),
            )
        except Exception:
            logger.warning("[DLsite特典探测] Redis dirty buffer 写入失败，回退 PostgreSQL 同步写入", exc_info=True)
        self._upsert_cache_values_sync(values)

    def flush_bonus_probe_cache_dirty_once(self, *, limit: int = 500, block_ms: int = 0) -> Dict[str, int]:
        try:
            from .redis_service import get_redis_service

            redis_service = get_redis_service()
            messages = redis_service.read_bonus_probe_cache_dirty_sync(
                count=max(1, int(limit or self._cache_write_batch_size())),
                block_ms=max(0, int(block_ms or 0)),
            )
        except Exception:
            logger.debug("[DLsite特典探测] 读取 Redis dirty buffer 失败", exc_info=True)
            return {"read": 0, "written": 0, "acked": 0}
        if not messages:
            return {"read": 0, "written": 0, "acked": 0}

        latest_by_rjcode: Dict[str, Dict[str, Any]] = {}
        message_ids: List[str] = []
        for message_id, payload in messages:
            message_ids.append(message_id)
            if not isinstance(payload, dict):
                continue
            rjcode = self.normalize_rjcode(payload.get("rjcode") or payload.get("workno"))
            if not rjcode:
                continue
            row = dict(payload)
            row["rjcode"] = rjcode
            row.pop("dirty_at", None)
            latest_by_rjcode[rjcode] = row
        if not latest_by_rjcode:
            acked = redis_service.ack_bonus_probe_cache_dirty_sync(message_ids)
            return {"read": len(messages), "written": 0, "acked": acked}

        rows = list(latest_by_rjcode.values())
        try:
            self._upsert_cache_values_sync(rows)
            acked = redis_service.ack_bonus_probe_cache_dirty_sync(message_ids)
            return {"read": len(messages), "written": len(rows), "acked": acked}
        except Exception as exc:
            acked = redis_service.ack_bonus_probe_cache_dirty_sync(message_ids)
            logger.warning(
                "[DLsite特典探测] Redis dirty buffer 回写失败，已 ACK 本批避免毒消息重放 read=%s rows=%s acked=%s error=%s",
                len(messages),
                len(rows),
                acked,
                exc.__class__.__name__,
            )
            return {"read": len(messages), "written": 0, "acked": acked, "failed": len(rows)}

    async def _bonus_probe_cache_flush_loop(self) -> None:
        stop_event = getattr(self, "_cache_flush_stop_event", None)
        if stop_event is None:
            return
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(
                    self.flush_bonus_probe_cache_dirty_once,
                    limit=self._cache_write_batch_size(),
                    block_ms=1000,
                )
                if not int((result or {}).get("read") or 0):
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[DLsite特典探测] Redis dirty buffer 回写 PostgreSQL 异常: %s",
                    exc.__class__.__name__,
                )
                await asyncio.sleep(2)

    def start_cache_flush_worker(self) -> None:
        task = getattr(self, "_cache_flush_task", None)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cache_flush_stop_event = asyncio.Event()
        self._cache_flush_task = loop.create_task(
            self._bonus_probe_cache_flush_loop(),
            name="dlsite-bonus-probe-cache-flush",
        )

    async def stop_cache_flush_worker(self) -> None:
        stop_event = getattr(self, "_cache_flush_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        task = getattr(self, "_cache_flush_task", None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._cache_flush_task = None
        self._cache_flush_stop_event = None
        await asyncio.to_thread(self.flush_bonus_probe_cache_dirty_once, limit=self._cache_write_batch_size(), block_ms=0)

    async def _load_or_probe_features(
        self,
        rjcodes: Sequence[str],
        *,
        batch_size: int,
        concurrency: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[Dict[str, DLsiteProductProbeFeature], int, int]:
        normalized = self._dedupe(rjcodes)
        if not normalized:
            return {}, 0, 0

        features = await asyncio.to_thread(self._load_cached_features_sync, normalized)

        missing = [workno for workno in normalized if workno not in features]
        request_count = 0
        checked_count = len(normalized) - len(missing)
        cached_count = checked_count
        if progress_callback:
            progress_callback(cached_count, len(normalized))
        for batch in self._chunk(missing, batch_size):
            probed = await self.dlsite_service.probe_product_info_features(batch, concurrency=concurrency)
            request_count += 1
            checked_count += len(batch)
            for workno, feature in probed.items():
                normalized_workno = self.normalize_rjcode(workno)
                features[normalized_workno] = feature
            await asyncio.to_thread(self._upsert_cache_features_sync, list(probed.values()))
            if progress_callback:
                progress_callback(min(len(normalized), checked_count), len(normalized))
            await asyncio.sleep(0)
        return features, len(normalized) - len(missing), request_count

    def _hidden_bonus_matches(self, feature: DLsiteProductProbeFeature, *, maker_id: str, release_date: str) -> bool:
        return bool(
            feature.exists
            and feature.is_hidden_bonus_audio
            and feature.maker_id == maker_id
            and feature.work_type == "SOU"
            and int(feature.price or 0) == 0
            and not bool(feature.is_sale)
            and bool(feature.is_free)
            and bool(feature.is_oly)
            and int(feature.wishlist_count or 0) == 0
        )

    def _public_sou_matches(self, feature: DLsiteProductProbeFeature, *, maker_id: str, release_date: str) -> bool:
        return bool(
            feature.exists
            and feature.maker_id == maker_id
            and feature.release_date == release_date
            and feature.work_type == "SOU"
            and not feature.is_hidden_bonus_audio
        )

    def _parse_status_blocks_conclusion(self, parse_status: str) -> bool:
        return str(parse_status or "").strip() in {"date_page_error", "http_error", "html_decode_failed"}

    def _probe_features_block_conclusion(self, features: Iterable[DLsiteProductProbeFeature]) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        for feature in features or []:
            if str(feature.probe_status or "").strip() != "error":
                continue
            workno = self.normalize_rjcode(feature.workno)
            message = str(feature.error_message or "").strip()
            errors.append(f"{workno}: {message}" if message else workno)
        return bool(errors), errors[:5]

    def _release_date_original_state_summary(
        self,
        db,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        target_original_rjcodes: Optional[Sequence[str]] = None,
    ) -> Dict[str, int]:
        normalized_circle = str(circle_id or "").strip()
        normalized_maker = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        target_set = set(self._dedupe(target_original_rjcodes or []))
        if not normalized_circle or not normalized_date:
            return {
                "original_count": 0,
                "concluded_count": 0,
                "pending_count": 0,
                "has_bonus_count": 0,
                "no_bonus_count": 0,
            }

        original_rows = (
            db.query(CircleWork)
            .filter(CircleWork.circle_id == normalized_circle, CircleWork.is_bonus_work == False)  # noqa: E712
            .all()
        )
        original_rjcodes = self._dedupe(row.canonical_rjcode for row in original_rows)
        if not original_rjcodes:
            return {
                "original_count": 0,
                "concluded_count": 0,
                "pending_count": 0,
                "has_bonus_count": 0,
                "no_bonus_count": 0,
            }

        metadata_by_rj = {
            self.normalize_rjcode(metadata.rjcode): metadata
            for metadata in db.query(WorkMetadata)
            .filter(WorkMetadata.rjcode.in_(original_rjcodes))
            .all()
        }
        same_date_originals: List[str] = []
        for row in original_rows:
            canonical = self.normalize_rjcode(row.canonical_rjcode)
            metadata = metadata_by_rj.get(canonical)
            if metadata is None or bool(metadata.is_bonus_work):
                continue
            if normalized_maker and str(metadata.maker_id or "").strip().upper() != normalized_maker:
                continue
            if target_set and canonical in target_set:
                same_date_originals.append(canonical)
                continue
            if target_set and canonical not in target_set:
                continue
            if self.normalize_date(metadata.release_date) != normalized_date:
                continue
            same_date_originals.append(canonical)

        state_map = self._completed_original_state_map(db, normalized_circle, same_date_originals)
        has_bonus_count = sum(1 for value in state_map.values() if value == "has_bonus")
        no_bonus_count = sum(1 for value in state_map.values() if value == "no_bonus")
        concluded_count = has_bonus_count + no_bonus_count
        original_count = len(same_date_originals)
        return {
            "original_count": original_count,
            "concluded_count": concluded_count,
            "pending_count": max(0, original_count - concluded_count),
            "has_bonus_count": has_bonus_count,
            "no_bonus_count": no_bonus_count,
        }

    def _date_all_originals_completed(self, *, circle_id: str, maker_id: str, release_date: str) -> bool:
        db = SessionLocal()
        try:
            summary = self._release_date_original_state_summary(
                db,
                circle_id=circle_id,
                maker_id=maker_id,
                release_date=release_date,
            )
            return summary["original_count"] > 0 and summary["pending_count"] == 0
        finally:
            db.close()

    def _load_indexed_public_worknos(
        self,
        circle_id: str,
        maker_id: str,
        release_date: str,
        *,
        include_checked: bool = True,
    ) -> List[str]:
        db = SessionLocal()
        try:
            rows = db.query(CircleWork).filter(CircleWork.circle_id == circle_id).all()
            worknos = self._public_original_worknos_from_rows(rows)
            if not worknos:
                return []
            state_map = {} if include_checked else self._completed_original_state_map(db, circle_id, worknos)
            metadata_rows = (
                db.query(WorkMetadata)
                .filter(WorkMetadata.rjcode.in_(worknos))
                .all()
            )
            matched = []
            for metadata in metadata_rows:
                if bool(metadata.is_bonus_work):
                    continue
                if maker_id and str(metadata.maker_id or "").strip().upper() != maker_id:
                    continue
                if release_date and self.normalize_date(metadata.release_date) != release_date:
                    continue
                if state_map.get(self.normalize_rjcode(metadata.rjcode)) in {"no_bonus", "has_bonus"}:
                    continue
                matched.append(metadata.rjcode)
            return self._dedupe(matched)
        finally:
            db.close()

    async def _load_public_worknos_for_date(
        self,
        circle_id: str,
        maker_id: str,
        release_date: str,
    ) -> Tuple[List[str], List[str], str]:
        worknos = self._load_indexed_public_worknos(circle_id, maker_id, release_date)
        date_page_worknos: List[str] = []
        parse_status = "not_requested"
        try:
            summaries, parse_status = await self.dlsite_service.list_new_work_summaries_by_date(release_date, max_pages=20)
            for summary in summaries:
                summary_date = self.normalize_date(summary.release_date)
                if summary.workno and (not summary_date or summary_date == release_date):
                    date_page_worknos.append(summary.workno)
                # 日期页可能解析不到 maker_id；这种条目不作为同社团端点，避免把当天全站新作拉进探测。
                if str(summary.maker_id or "").strip().upper() != maker_id:
                    continue
                if summary_date and summary_date != release_date:
                    continue
                if summary.workno:
                    worknos.append(summary.workno)
        except Exception as exc:
            parse_status = "date_page_error"
            logger.warning("[DLsite特典探测] 日期页公开作品抓取失败 date=%s maker=%s error=%s", release_date, maker_id, exc)
        return self._dedupe(worknos), self._dedupe(date_page_worknos), parse_status

    def _upsert_date_row(self, db, *, maker_id: str, circle_id: str, release_date: str, gap_limit: int) -> DLsiteBonusProbeDate:
        row = (
            db.query(DLsiteBonusProbeDate)
            .filter(
                DLsiteBonusProbeDate.maker_id == maker_id,
                DLsiteBonusProbeDate.release_date == release_date,
                DLsiteBonusProbeDate.gap_limit == int(gap_limit),
            )
            .first()
        )
        if row is None:
            row = DLsiteBonusProbeDate(maker_id=maker_id, release_date=release_date, gap_limit=int(gap_limit))
            db.add(row)
        row.circle_id = circle_id or row.circle_id or ""
        row.updated_at = datetime.now()
        return row

    def _mode_key(self, mode: str) -> str:
        normalized_mode = str(mode or "normal").strip() or "normal"
        if self.PROBE_STRATEGY_VERSION in normalized_mode:
            return normalized_mode
        return f"{normalized_mode}:{self.PROBE_STRATEGY_VERSION}"

    def _can_reuse_completed_date_row(self, row: Optional[DLsiteBonusProbeDate], *, mode: str) -> bool:
        if row is None or str(row.status or "") != "completed":
            return False
        row_mode = str(row.mode or "").strip()
        if row_mode == self._mode_key(mode):
            return True
        if row_mode != (str(mode or "normal").strip() or "normal"):
            return False

        # v4 改为扫描当天公开 RJ 的完整编号范围。旧 deep/v2/v3 完成记录可能
        # 没有扫到 RJ01314197 -> RJ01315736 这种同日远距离特典，必须重新跑。
        return False

    def _completed_date_row_result(
        self,
        row: DLsiteBonusProbeDate,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        mode: str,
    ) -> Dict[str, Any]:
        return {
            "circle_id": circle_id,
            "maker_id": maker_id,
            "release_date": release_date,
            "parse_status": "cached_completed",
            "public_count": int(row.public_count or 0),
            "date_page_public_count": 0,
            "sou_public_count": int(row.sou_public_count or 0),
            "gap_count": int(row.gap_count or 0),
            "circle_gap_count": 0,
            "date_page_range_count": 0,
            "date_page_range_limit": self.DEFAULT_DATE_RANGE_LIMIT,
            "probe_count": int(row.probe_count or 0),
            "cached_hit_count": int(row.cached_hit_count or 0),
            "request_count": 0,
            "hit_count": int(row.hit_count or 0),
            "inserted_count": 0,
            "budget_reached": bool(row.budget_reached),
            "hit_rjcodes": [],
            "skipped": True,
            "skip_reason": f"completed:{self._mode_key(mode)}",
        }

    def _finish_probe_date_result(
        self,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        gap_limit: int,
        mode_key: str,
        hidden_hits: Sequence[DLsiteProductProbeFeature],
        target_original_rjcodes: Optional[Sequence[str]],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        inserted_count = int(result.get("inserted_count") or 0)
        inserted_count += self._upsert_bonus_works(
            circle_id,
            maker_id,
            hidden_hits,
            target_original_rjcodes=target_original_rjcodes,
        )
        result["inserted_count"] = inserted_count

        if not bool(result.get("budget_reached")):
            self._mark_original_probe_states_after_scan(
                circle_id=circle_id,
                maker_id=maker_id,
                release_date=release_date,
                hidden_hits=hidden_hits,
                target_original_rjcodes=target_original_rjcodes,
            )

        db = SessionLocal()
        try:
            original_summary = self._release_date_original_state_summary(
                db,
                circle_id=circle_id,
                maker_id=maker_id,
                release_date=release_date,
                target_original_rjcodes=target_original_rjcodes,
            )
        finally:
            db.close()

        result.update({
            "original_count": original_summary["original_count"],
            "original_concluded_count": original_summary["concluded_count"],
            "original_pending_count": original_summary["pending_count"],
            "original_has_bonus_count": original_summary["has_bonus_count"],
            "original_no_bonus_count": original_summary["no_bonus_count"],
        })
        if result.get("budget_reached"):
            result["incomplete"] = True
            result["error_message"] = (
                f"发售日 {release_date} 的 RJ 探测范围超出预算，已沉淀命中线索但不产出无特典结论"
            )
        elif original_summary["pending_count"] != 0:
            raise RuntimeError(
                f"发售日 {release_date} 仍有 {original_summary['pending_count']} 个原作未形成特典结论"
            )

        db = SessionLocal()
        try:
            date_row = self._upsert_date_row(
                db,
                maker_id=maker_id,
                circle_id=circle_id,
                release_date=release_date,
                gap_limit=gap_limit,
            )
            date_row.mode = mode_key
            date_row.status = "incomplete" if result.get("incomplete") else "completed"
            date_row.public_count = int(result.get("public_count") or 0)
            date_row.sou_public_count = int(result.get("sou_public_count") or 0)
            date_row.gap_count = int(result.get("gap_count") or 0)
            date_row.probe_count = int(result.get("probe_count") or 0)
            date_row.cached_hit_count = int(result.get("cached_hit_count") or 0)
            date_row.request_count = int(result.get("request_count") or 0)
            date_row.hit_count = int(result.get("hit_count") or 0)
            date_row.inserted_count = int(result.get("inserted_count") or 0)
            date_row.budget_reached = bool(result.get("budget_reached"))
            date_row.error_message = str(result.get("error_message") or "")[:2000]
            date_row.finished_at = datetime.now()
            db.commit()
        finally:
            db.close()
        return result

    def reusable_completed_release_dates(
        self,
        *,
        maker_id: str,
        release_dates: Sequence[str],
        mode: str = "normal",
        gap_limit: int = DEFAULT_GAP_LIMIT,
        circle_id: str = "",
    ) -> List[str]:
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_circle_id = str(circle_id or "").strip()
        normalized_dates = [self.normalize_date(value) for value in release_dates or []]
        normalized_dates = [value for value in normalized_dates if value]
        if not normalized_maker_id or not normalized_dates:
            return []

        completed: List[str] = []
        db = SessionLocal()
        try:
            rows = (
                db.query(DLsiteBonusProbeDate)
                .filter(
                    DLsiteBonusProbeDate.maker_id == normalized_maker_id,
                    DLsiteBonusProbeDate.release_date.in_(normalized_dates),
                    DLsiteBonusProbeDate.gap_limit == int(gap_limit),
                )
                .all()
            )
            rows_by_date = {
                self.normalize_date(row.release_date): row
                for row in rows
            }
            for release_date in normalized_dates:
                if not self._can_reuse_completed_date_row(rows_by_date.get(release_date), mode=mode):
                    continue
                if normalized_circle_id and not self._date_all_originals_completed(
                    circle_id=normalized_circle_id,
                    maker_id=normalized_maker_id,
                    release_date=release_date,
                ):
                    continue
                completed.append(release_date)
            return completed
        finally:
            db.close()

    def split_reusable_release_dates(
        self,
        *,
        maker_id: str,
        release_dates: Sequence[str],
        mode: str = "normal",
        gap_limit: int = DEFAULT_GAP_LIMIT,
        circle_id: str = "",
    ) -> Tuple[List[str], List[str]]:
        normalized_dates: List[str] = []
        for value in release_dates or []:
            normalized = self.normalize_date(value)
            if normalized and normalized not in normalized_dates:
                normalized_dates.append(normalized)
        completed = set(self.reusable_completed_release_dates(
            maker_id=maker_id,
            release_dates=normalized_dates,
            mode=mode,
            gap_limit=gap_limit,
            circle_id=circle_id,
        ))
        pending = [release_date for release_date in normalized_dates if release_date not in completed]
        skipped = [release_date for release_date in normalized_dates if release_date in completed]
        return pending, skipped

    def _merge_rjcodes(self, values: Iterable[Any], *extra_values: Any) -> List[str]:
        merged: List[str] = []
        for value in [*(values or []), *extra_values]:
            normalized = self.normalize_rjcode(value)
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    def _select_original_work_for_bonus(
        self,
        rows: Iterable[CircleWork],
        metadata_by_rj: Dict[str, WorkMetadata],
        *,
        bonus_rjcode: str,
        maker_id: str,
        release_date: str,
        trust_request_release_date: bool = False,
    ) -> Optional[CircleWork]:
        normalized_bonus = self.normalize_rjcode(bonus_rjcode)
        normalized_maker = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        bonus_number = self._rj_number(normalized_bonus)
        candidates: List[Tuple[int, str, CircleWork]] = []
        for row in rows or []:
            if bool(getattr(row, "is_bonus_work", False)):
                continue
            canonical = self.normalize_rjcode(getattr(row, "canonical_rjcode", ""))
            if not canonical or canonical == normalized_bonus:
                continue
            metadata = metadata_by_rj.get(canonical)
            if metadata is None or bool(getattr(metadata, "is_bonus_work", False)):
                continue
            if normalized_maker and str(getattr(metadata, "maker_id", "") or "").strip().upper() != normalized_maker:
                continue
            if (
                not trust_request_release_date
                and normalized_date
                and self.normalize_date(getattr(metadata, "release_date", "")) != normalized_date
            ):
                continue
            original_number = self._rj_number(canonical)
            distance = (
                abs(original_number[0] - bonus_number[0])
                if original_number and bonus_number
                else 10**12
            )
            candidates.append((distance, canonical, row))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2] if candidates else None

    def _load_reusable_hidden_bonus_features(
        self,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
    ) -> List[DLsiteProductProbeFeature]:
        normalized_maker = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        if not normalized_maker or not normalized_date:
            return []
        db = SessionLocal()
        try:
            hit_rows = (
                db.query(DLsiteBonusProbeHitIndex)
                .filter(
                    DLsiteBonusProbeHitIndex.maker_id == normalized_maker,
                    DLsiteBonusProbeHitIndex.release_date == normalized_date,
                )
                .all()
            )
            hit_rjcodes = self._dedupe(
                row.bonus_rjcode
                for row in hit_rows
                if not circle_id or str(row.circle_id or "") in {"", circle_id}
            )
            features_by_rjcode: Dict[str, DLsiteProductProbeFeature] = {}
            cache_rows = []
            if hit_rjcodes:
                cache_rows.extend(
                    db.query(DLsiteBonusProbeCache)
                    .filter(DLsiteBonusProbeCache.rjcode.in_(hit_rjcodes))
                    .all()
                )
            cache_rows.extend(
                db.query(DLsiteBonusProbeCache)
                .filter(
                    DLsiteBonusProbeCache.maker_id == normalized_maker,
                    DLsiteBonusProbeCache.release_date == normalized_date,
                    DLsiteBonusProbeCache.is_hidden_bonus_audio == True,  # noqa: E712
                )
                .all()
            )
            for row in cache_rows:
                feature = self._feature_from_cache_row(row)
                if self._hidden_bonus_matches(feature, maker_id=normalized_maker, release_date=normalized_date):
                    normalized_workno = self.normalize_rjcode(feature.workno)
                    if normalized_workno:
                        features_by_rjcode[normalized_workno] = feature
            return [
                features_by_rjcode[rjcode]
                for rjcode in sorted(features_by_rjcode, key=lambda item: (self._candidate_shard_key(item), item))
            ]
        finally:
            db.close()

    def _selected_targets_with_bonus_hits(
        self,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        target_rjcodes: Sequence[str],
        hidden_hits: Sequence[DLsiteProductProbeFeature],
    ) -> set[str]:
        normalized_targets = set(self._dedupe(target_rjcodes))
        if not circle_id or not normalized_targets or not hidden_hits:
            return set()
        normalized_maker = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        db = SessionLocal()
        try:
            target_rows = (
                db.query(CircleWork)
                .filter(
                    CircleWork.circle_id == circle_id,
                    CircleWork.is_bonus_work == False,  # noqa: E712
                    CircleWork.canonical_rjcode.in_(list(normalized_targets)),
                )
                .all()
            )
            target_rjcodes = self._dedupe(row.canonical_rjcode for row in target_rows)
            if not target_rjcodes:
                return set()
            metadata_by_rj = {
                self.normalize_rjcode(metadata.rjcode): metadata
                for metadata in db.query(WorkMetadata)
                .filter(WorkMetadata.rjcode.in_(target_rjcodes))
                .all()
            }
            covered: set[str] = set()
            for feature in hidden_hits or []:
                original_row = self._select_original_work_for_bonus(
                    target_rows,
                    metadata_by_rj,
                    bonus_rjcode=feature.workno,
                    maker_id=normalized_maker,
                    release_date=feature.release_date or normalized_date,
                    trust_request_release_date=True,
                )
                if original_row is not None:
                    normalized_original = self.normalize_rjcode(original_row.canonical_rjcode)
                    if normalized_original:
                        covered.add(normalized_original)
            return covered
        finally:
            db.close()

    def _mark_original_probe_states_after_scan(
        self,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        hidden_hits: Sequence[DLsiteProductProbeFeature],
        target_original_rjcodes: Optional[Sequence[str]] = None,
    ) -> None:
        if not circle_id:
            return
        normalized_maker = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        db = SessionLocal()
        try:
            original_rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id, CircleWork.is_bonus_work == False)  # noqa: E712
                .all()
            )
            target_set = set(self._dedupe(target_original_rjcodes or []))
            if target_set:
                original_rows = [
                    row
                    for row in original_rows
                    if self.normalize_rjcode(row.canonical_rjcode) in target_set
                ]
            original_rjcodes = self._dedupe(row.canonical_rjcode for row in original_rows)
            if not original_rjcodes:
                return
            metadata_by_rj = {
                self.normalize_rjcode(metadata.rjcode): metadata
                for metadata in db.query(WorkMetadata)
                .filter(WorkMetadata.rjcode.in_(original_rjcodes))
                .all()
            }
            same_date_originals = []
            for row in original_rows:
                canonical = self.normalize_rjcode(row.canonical_rjcode)
                metadata = metadata_by_rj.get(canonical)
                if metadata is None or bool(metadata.is_bonus_work):
                    continue
                if normalized_maker and str(metadata.maker_id or "").strip().upper() != normalized_maker:
                    continue
                if (
                    not target_set
                    and normalized_date
                    and self.normalize_date(metadata.release_date) != normalized_date
                ):
                    continue
                same_date_originals.append(row)

            has_bonus_rjcodes: set[str] = set()
            for feature in hidden_hits or []:
                self._upsert_bonus_hit_index(
                    db,
                    circle_id=circle_id,
                    maker_id=normalized_maker,
                    release_date=feature.release_date or normalized_date,
                    bonus_rjcode=feature.workno,
                )
                original_row = self._select_original_work_for_bonus(
                    same_date_originals,
                    metadata_by_rj,
                    bonus_rjcode=feature.workno,
                    maker_id=normalized_maker,
                    release_date=feature.release_date or normalized_date,
                    trust_request_release_date=bool(target_set),
                )
                if original_row is not None:
                    has_bonus_rjcodes.add(self.normalize_rjcode(original_row.canonical_rjcode))

            for row in same_date_originals:
                canonical = self.normalize_rjcode(row.canonical_rjcode)
                status = "has_bonus" if canonical in has_bonus_rjcodes or bool(row.has_bonus) else "no_bonus"
                self._upsert_original_probe_state(
                    db,
                    circle_id=circle_id,
                    maker_id=normalized_maker,
                    original_rjcode=canonical,
                    release_date=normalized_date,
                    status=status,
                )
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[DLsite特典探测] 写入原作特典探测状态失败 circle=%s date=%s", circle_id, release_date, exc_info=True)
        finally:
            db.close()

    def _upsert_bonus_canonical_link(self, db, *, original_rjcode: str, bonus_rjcode: str) -> None:
        original = self.normalize_rjcode(original_rjcode)
        bonus = self.normalize_rjcode(bonus_rjcode)
        if not original or not bonus or original == bonus:
            return
        row = (
            db.query(WorkCanonicalLink)
            .filter(
                WorkCanonicalLink.canonical_rjcode == original,
                WorkCanonicalLink.linked_rjcode == bonus,
            )
            .first()
        )
        if row is None:
            row = WorkCanonicalLink(
                id=str(uuid.uuid4()),
                canonical_rjcode=original,
                linked_rjcode=bonus,
            )
            db.add(row)
        row.link_type = "bonus"
        row.lang = ""
        row.cached_at = datetime.now()
        row.updated_at = datetime.now()

    def _upsert_bonus_works(
        self,
        circle_id: str,
        maker_id: str,
        features: Sequence[DLsiteProductProbeFeature],
        *,
        target_original_rjcodes: Optional[Sequence[str]] = None,
    ) -> int:
        if not circle_id or not features:
            return 0
        db = SessionLocal()
        inserted_or_updated = 0
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            maker_name = str((catalog.circle_name if catalog else "") or "").strip()
            if catalog:
                flags = {item for item in str(catalog.source_mask or "").split(",") if item}
                flags.add("dlsite")
                flags.add("dlsite_bonus_probe")
                catalog.source_mask = ",".join(sorted(flags))
                catalog.updated_at = datetime.now()

            original_rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id, CircleWork.is_bonus_work == False)  # noqa: E712
                .all()
            )
            target_set = set(self._dedupe(target_original_rjcodes or []))
            if target_set:
                original_rows = [
                    row
                    for row in original_rows
                    if self.normalize_rjcode(row.canonical_rjcode) in target_set
                ]
            original_rjcodes = self._dedupe(row.canonical_rjcode for row in original_rows)
            metadata_by_rj: Dict[str, WorkMetadata] = {}
            if original_rjcodes:
                metadata_by_rj = {
                    self.normalize_rjcode(metadata.rjcode): metadata
                    for metadata in db.query(WorkMetadata)
                    .filter(WorkMetadata.rjcode.in_(original_rjcodes))
                    .all()
                }

            for feature in features:
                rjcode = self.normalize_rjcode(feature.workno)
                if not rjcode:
                    continue
                self._upsert_bonus_hit_index(
                    db,
                    circle_id=circle_id,
                    maker_id=maker_id,
                    release_date=feature.release_date,
                    bonus_rjcode=rjcode,
                )
                original_row = self._select_original_work_for_bonus(
                    original_rows,
                    metadata_by_rj,
                    bonus_rjcode=rjcode,
                    maker_id=maker_id,
                    release_date=feature.release_date,
                    trust_request_release_date=bool(target_set),
                )
                original_rjcode = self.normalize_rjcode(original_row.canonical_rjcode) if original_row else ""
                metadata = db.query(WorkMetadata).filter(WorkMetadata.rjcode == rjcode).first()
                if metadata is None:
                    metadata = WorkMetadata(rjcode=rjcode)
                    db.add(metadata)
                metadata.work_name = feature.title or metadata.work_name or rjcode
                metadata.maker_id = maker_id or metadata.maker_id or ""
                metadata.maker_name = maker_name or metadata.maker_name or ""
                metadata.release_date = feature.release_date or metadata.release_date or ""
                metadata.price_text = "0"
                metadata.is_bonus_work = True
                metadata.has_bonus = False
                metadata.bonus_info_checked_at = datetime.now()
                metadata.cached_at = datetime.now()
                metadata.expires_at = None

                row = (
                    db.query(CircleWork)
                    .filter(CircleWork.circle_id == circle_id, CircleWork.canonical_rjcode == rjcode)
                    .first()
                )
                if row is None:
                    row = CircleWork(id=str(uuid.uuid4()), circle_id=circle_id, canonical_rjcode=rjcode)
                    db.add(row)
                row.display_rjcode = rjcode
                row.title = feature.title or row.title or rjcode
                row.maker_id = maker_id or row.maker_id or ""
                row.maker_name = maker_name or row.maker_name or ""
                row.price_text = "0"
                row.is_bonus_work = True
                row.has_bonus = False
                row.has_dlsite = True
                row.has_asmr_one = False
                row.linked_rjcodes = self._merge_rjcodes([], original_rjcode, rjcode)
                flags = {item for item in str(row.source_mask or "").split(",") if item}
                flags.add("dlsite")
                flags.add("dlsite_bonus_probe")
                row.source_mask = ",".join(sorted(flags))
                row.dlsite_cached_at = datetime.now()
                row.updated_at = datetime.now()

                if original_row is not None and original_rjcode:
                    original_row.linked_rjcodes = self._merge_rjcodes(
                        original_row.linked_rjcodes or [original_row.display_rjcode or original_rjcode],
                        original_rjcode,
                        rjcode,
                    )
                    original_row.has_bonus = True
                    original_flags = {item for item in str(original_row.source_mask or "").split(",") if item}
                    original_flags.add("dlsite_bonus_probe")
                    original_row.source_mask = ",".join(sorted(original_flags))
                    original_row.updated_at = datetime.now()
                    original_metadata = metadata_by_rj.get(original_rjcode)
                    if original_metadata is not None:
                        original_metadata.has_bonus = True
                        original_metadata.cached_at = datetime.now()
                    self._upsert_original_probe_state(
                        db,
                        circle_id=circle_id,
                        maker_id=maker_id,
                        original_rjcode=original_rjcode,
                        release_date=feature.release_date,
                        status="has_bonus",
                    )
                    self._upsert_bonus_canonical_link(
                        db,
                        original_rjcode=original_rjcode,
                        bonus_rjcode=rjcode,
                    )
                inserted_or_updated += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            from .circle_completion_service import get_circle_completion_service

            circle_service = get_circle_completion_service()
            circle_service.invalidate_completion_view_cache(circle_id)
            for feature in features:
                circle_service._metadata_cache.pop(self.normalize_rjcode(feature.workno), None)
        except Exception:
            logger.debug("[DLsite特典探测] 失效社团补全缓存失败 circle_id=%s", circle_id, exc_info=True)
        return inserted_or_updated

    def resolve_circle_context(self, circle_id: str, maker_id: str = "") -> Dict[str, str]:
        normalized_circle_id = str(circle_id or "").strip()
        normalized_maker_id = str(maker_id or "").strip().upper()
        db = SessionLocal()
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == normalized_circle_id).first()
            if catalog and not normalized_maker_id:
                identity = (
                    db.query(CircleExternalIdentity)
                    .filter(CircleExternalIdentity.circle_name_normalized == catalog.circle_name_normalized)
                    .first()
                )
                normalized_maker_id = str((identity.maker_id if identity else "") or "").strip().upper()
            if not normalized_maker_id:
                row = (
                    db.query(CircleWork)
                    .filter(CircleWork.circle_id == normalized_circle_id, CircleWork.maker_id != "")
                    .first()
                )
                normalized_maker_id = str((row.maker_id if row else "") or "").strip().upper()
            return {
                "circle_id": normalized_circle_id,
                "circle_name": str((catalog.circle_name if catalog else "") or "").strip(),
                "maker_id": normalized_maker_id,
            }
        finally:
            db.close()

    def list_indexed_release_dates(self, circle_id: str, maker_id: str = "", *, mode: str = "normal") -> List[str]:
        context = self.resolve_circle_context(circle_id, maker_id)
        normalized_maker_id = context["maker_id"]
        normalized_circle_id = context["circle_id"]
        db = SessionLocal()
        try:
            rows = db.query(CircleWork).filter(CircleWork.circle_id == normalized_circle_id).all()
            worknos = self._public_original_worknos_from_rows(rows)
            if not worknos:
                return []
            state_map = self._completed_original_state_map(db, normalized_circle_id, worknos)
            query = db.query(WorkMetadata).filter(WorkMetadata.rjcode.in_(worknos), WorkMetadata.release_date != None)  # noqa: E711
            if normalized_maker_id:
                query = query.filter(WorkMetadata.maker_id == normalized_maker_id)
            dates = []
            for row in query.all():
                if bool(row.is_bonus_work):
                    continue
                if state_map.get(self.normalize_rjcode(row.rjcode)) in {"no_bonus", "has_bonus"}:
                    continue
                normalized_date = self.normalize_date(row.release_date)
                if normalized_date and normalized_date not in dates:
                    dates.append(normalized_date)
            dates.sort(reverse=True)
            if str(mode or "normal") != "deep":
                dates = dates[:10]
            return dates
        finally:
            db.close()

    def _release_date_min_rj_map(self, *, circle_id: str, maker_id: str, dates: Sequence[str]) -> Dict[str, int]:
        normalized_circle_id = str(circle_id or "").strip()
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_dates = [self.normalize_date(value) for value in dates or []]
        normalized_dates = [value for value in normalized_dates if value]
        if not normalized_circle_id or not normalized_dates:
            return {}

        db = SessionLocal()
        try:
            rows = db.query(CircleWork).filter(CircleWork.circle_id == normalized_circle_id).all()
            worknos = self._public_original_worknos_from_rows(rows)
            if not worknos:
                return {}
            query = db.query(WorkMetadata).filter(
                WorkMetadata.rjcode.in_(worknos),
                WorkMetadata.release_date.in_(normalized_dates),
            )
            if normalized_maker_id:
                query = query.filter(WorkMetadata.maker_id == normalized_maker_id)

            min_by_date: Dict[str, int] = {}
            for row in query.all():
                if bool(row.is_bonus_work):
                    continue
                release_date = self.normalize_date(row.release_date)
                number = self._rj_number(row.rjcode)
                if not release_date or not number:
                    continue
                current = min_by_date.get(release_date)
                if current is None or number[0] < current:
                    min_by_date[release_date] = number[0]
            return min_by_date
        finally:
            db.close()

    def _order_probe_release_dates(self, *, circle_id: str, maker_id: str, dates: Sequence[str]) -> List[str]:
        normalized_dates = [self.normalize_date(value) for value in dates or []]
        normalized_dates = [value for value in normalized_dates if value]
        deduped = self._dedupe(normalized_dates)
        min_rj_by_date = self._release_date_min_rj_map(
            circle_id=circle_id,
            maker_id=maker_id,
            dates=deduped,
        )
        return sorted(
            deduped,
            key=lambda release_date: (
                min_rj_by_date.get(release_date, 10**18),
                release_date,
            ),
        )

    async def probe_date(
        self,
        *,
        circle_id: str,
        maker_id: str,
        release_date: str,
        gap_limit: int = DEFAULT_GAP_LIMIT,
        batch_size: int = DEFAULT_BATCH_SIZE,
        concurrency: int = DEFAULT_CONCURRENCY,
        mode: str = "normal",
        job_id: str = "",
        target_rjcodes: Optional[Sequence[str]] = None,
        probe_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        normalized_circle_id = str(circle_id or "").strip()
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_date = self.normalize_date(release_date)
        if not normalized_circle_id:
            raise ValueError("缺少社团 ID")
        if not normalized_maker_id:
            raise ValueError("缺少 DLsite maker_id")
        if not normalized_date:
            raise ValueError("缺少发售日")
        normalized_target_rjcodes = self._dedupe([
            normalized
            for normalized in (self.normalize_rjcode(value) for value in (target_rjcodes or []))
            if normalized
        ])
        if normalized_target_rjcodes:
            self._persist_precise_release_dates(
                rjcodes=normalized_target_rjcodes,
                maker_id=normalized_maker_id,
                release_date=normalized_date,
            )

        mode_key = self._mode_key(mode)
        db = SessionLocal()
        try:
            date_row = (
                db.query(DLsiteBonusProbeDate)
                .filter(
                    DLsiteBonusProbeDate.maker_id == normalized_maker_id,
                    DLsiteBonusProbeDate.release_date == normalized_date,
                    DLsiteBonusProbeDate.gap_limit == int(gap_limit),
                )
                .first()
            )
            if not normalized_target_rjcodes and self._can_reuse_completed_date_row(date_row, mode=mode):
                result = self._completed_date_row_result(
                    date_row,
                    circle_id=normalized_circle_id,
                    maker_id=normalized_maker_id,
                    release_date=normalized_date,
                    mode=mode,
                )
                date_row.circle_id = normalized_circle_id or date_row.circle_id or ""
                date_row.mode = mode_key
                date_row.job_id = str(job_id or date_row.job_id or "")
                date_row.updated_at = datetime.now()
                db.commit()
                return result

            if date_row is None:
                date_row = DLsiteBonusProbeDate(
                    maker_id=normalized_maker_id,
                    release_date=normalized_date,
                    gap_limit=int(gap_limit),
                )
                db.add(date_row)
            date_row.circle_id = normalized_circle_id or date_row.circle_id or ""
            date_row.mode = mode_key
            date_row.status = "processing"
            date_row.job_id = str(job_id or "")
            date_row.started_at = datetime.now()
            date_row.finished_at = None
            date_row.error_message = None
            db.commit()
        finally:
            db.close()

        request_count = 0
        cached_hit_count = 0
        inserted_count = 0
        selected_scope = bool(normalized_target_rjcodes)
        circle_edge_window = max(
            int(gap_limit or self.DEFAULT_GAP_LIMIT),
            self.DEFAULT_CIRCLE_EDGE_WINDOW,
        )
        hidden_hits_by_rjcode: Dict[str, DLsiteProductProbeFeature] = {}

        def remember_hidden_hits(features: Iterable[DLsiteProductProbeFeature]) -> None:
            for feature in features or []:
                if not self._hidden_bonus_matches(feature, maker_id=normalized_maker_id, release_date=normalized_date):
                    continue
                normalized_workno = self.normalize_rjcode(feature.workno)
                if not normalized_workno:
                    continue
                hidden_hits_by_rjcode[normalized_workno] = feature

        try:
            reusable_hidden_hits = self._load_reusable_hidden_bonus_features(
                circle_id=normalized_circle_id,
                maker_id=normalized_maker_id,
                release_date=normalized_date,
            )
            if reusable_hidden_hits:
                cached_hit_count += len(reusable_hidden_hits)
                remember_hidden_hits(reusable_hidden_hits)

            selected_cache_covered = False
            selected_probe_stopped_on_hit = False
            if selected_scope and hidden_hits_by_rjcode:
                covered_targets = self._selected_targets_with_bonus_hits(
                    circle_id=normalized_circle_id,
                    maker_id=normalized_maker_id,
                    release_date=normalized_date,
                    target_rjcodes=normalized_target_rjcodes,
                    hidden_hits=list(hidden_hits_by_rjcode.values()),
                )
                selected_cache_covered = set(normalized_target_rjcodes).issubset(covered_targets)
                if selected_cache_covered:
                    hidden_hits = list(hidden_hits_by_rjcode.values())
                    result = {
                        "circle_id": normalized_circle_id,
                        "maker_id": normalized_maker_id,
                        "release_date": normalized_date,
                        "parse_status": "cached_hidden_bonus",
                        "public_count": 0,
                        "date_page_public_count": 0,
                        "sou_public_count": 0,
                        "gap_count": 0,
                        "circle_gap_count": 0,
                        "circle_edge_window": circle_edge_window,
                        "date_page_range_count": 0,
                        "date_page_range_limit": None,
                        "date_page_range_unbounded": True,
                        "selected_scope": True,
                        "target_rjcodes": normalized_target_rjcodes,
                        "probe_count": 0,
                        "raw_probe_count": 0,
                        "candidate_filter_stats": {
                            "input": 0,
                            "cached": 0,
                            "active": 0,
                            "cooldown": 0,
                            "selected": 0,
                            "leased": 0,
                        },
                        "candidate_shard_count": 0,
                        "selected_cache_covered": True,
                        "selected_probe_stopped_on_hit": False,
                        "candidate_shards": [],
                        "cached_hit_count": cached_hit_count,
                        "request_count": request_count,
                        "hit_count": len(hidden_hits),
                        "inserted_count": inserted_count,
                        "budget_reached": False,
                        "hit_rjcodes": [feature.workno for feature in hidden_hits],
                        "reused_hit_index": bool(reusable_hidden_hits),
                    }
                    return self._finish_probe_date_result(
                        circle_id=normalized_circle_id,
                        maker_id=normalized_maker_id,
                        release_date=normalized_date,
                        gap_limit=gap_limit,
                        mode_key=mode_key,
                        hidden_hits=hidden_hits,
                        target_original_rjcodes=normalized_target_rjcodes,
                        result=result,
                    )

            public_worknos, date_page_worknos, parse_status = await self._load_public_worknos_for_date(
                normalized_circle_id,
                normalized_maker_id,
                normalized_date,
            )
            self._persist_precise_release_dates(
                rjcodes=public_worknos,
                maker_id=normalized_maker_id,
                release_date=normalized_date,
            )
            if self._parse_status_blocks_conclusion(parse_status):
                raise RuntimeError(f"DLsite 日期页解析异常，未产出特典结论：{normalized_date} ({parse_status})")
            public_features, cached_hits, requests = await self._load_or_probe_features(
                public_worknos,
                batch_size=batch_size,
                concurrency=concurrency,
            )
            cached_hit_count += cached_hits
            request_count += requests
            has_errors, error_samples = self._probe_features_block_conclusion(public_features.values())
            if has_errors:
                raise RuntimeError(f"DLsite 公开作品确认异常，未产出特典结论：{'; '.join(error_samples)}")
            sou_public = [
                workno
                for workno, feature in public_features.items()
                if self._public_sou_matches(feature, maker_id=normalized_maker_id, release_date=normalized_date)
            ]
            if selected_scope:
                circle_candidates = self._build_anchor_edge_candidates(
                    normalized_target_rjcodes,
                    edge_window_limit=circle_edge_window,
                )
                circle_gap_count = 0
                circle_budget_reached = False
                date_page_candidates, date_page_range_count, date_page_budget_reached = self._build_range_candidates(
                    date_page_worknos,
                    range_limit=self.DEFAULT_DATE_RANGE_LIMIT,
                    enforce_limit=False,
                )
            else:
                circle_candidates, circle_gap_count, circle_budget_reached = self._build_gap_candidates(
                    sou_public,
                    gap_limit,
                    include_edges=True,
                    edge_window_limit=circle_edge_window,
                )
                date_page_candidates, date_page_range_count, date_page_budget_reached = self._build_range_candidates(
                    date_page_worknos,
                    range_limit=self.DEFAULT_DATE_RANGE_LIMIT,
                )
            raw_probe_candidates = self._dedupe([*circle_candidates, *date_page_candidates])
            cached_candidate_features = await asyncio.to_thread(
                self._load_cached_features_sync,
                raw_probe_candidates,
            )
            gap_count = circle_gap_count
            budget_reached = bool(circle_budget_reached or date_page_budget_reached)

            remember_hidden_hits(cached_candidate_features.values())
            known_hidden_numbers = [
                number[0]
                for number in (
                    self._rj_number(feature.workno)
                    for feature in hidden_hits_by_rjcode.values()
                )
                if number
            ]
            if selected_scope and hidden_hits_by_rjcode:
                covered_targets = self._selected_targets_with_bonus_hits(
                    circle_id=normalized_circle_id,
                    maker_id=normalized_maker_id,
                    release_date=normalized_date,
                    target_rjcodes=normalized_target_rjcodes,
                    hidden_hits=list(hidden_hits_by_rjcode.values()),
                )
                selected_cache_covered = set(normalized_target_rjcodes).issubset(covered_targets)
                if not selected_cache_covered and known_hidden_numbers:
                    last_hidden_number = max(known_hidden_numbers)
                    raw_probe_candidates = [
                        candidate
                        for candidate in raw_probe_candidates
                        if (self._rj_number(candidate) or (0, 0))[0] > last_hidden_number
                    ]

            def emit_probe_progress(checked_count: int, total_count: int) -> None:
                if not probe_progress_callback:
                    return
                probe_progress_callback({
                    "release_date": normalized_date,
                    "checked_probe_count": int(checked_count or 0),
                    "probe_count": int(total_count or 0),
                })

            candidate_features: Dict[str, DLsiteProductProbeFeature] = {}
            cached_hits = 0
            requests = 0
            candidate_shards: List[Dict[str, Any]] = []
            candidate_filter_stats = {"input": 0, "cached": 0, "active": 0, "cooldown": 0, "selected": 0, "leased": 0}
            leased_probe_candidates: List[str] = []
            if not selected_cache_covered:
                candidate_shards, candidate_filter_stats = await self._lease_candidate_shards(
                    raw_probe_candidates,
                    shard_size=batch_size,
                )
                leased_probe_candidates = self._merge_candidate_shards(candidate_shards)
                checked_before = 0
                try:
                    for shard in candidate_shards:
                        shard_candidates = list(shard.get("rjcodes") or [])
                        if not shard_candidates:
                            continue
                        shard_features, shard_cached_hits, shard_requests = await self._load_or_probe_features(
                            shard_candidates,
                            batch_size=batch_size,
                            concurrency=concurrency,
                            progress_callback=lambda checked, total, offset=checked_before: emit_probe_progress(
                                offset + checked,
                                len(leased_probe_candidates),
                            ),
                        )
                        candidate_features.update(shard_features)
                        cached_hits += shard_cached_hits
                        requests += shard_requests
                        checked_before += len(shard_candidates)
                        remember_hidden_hits(shard_features.values())
                        if selected_scope and hidden_hits_by_rjcode:
                            covered_targets = self._selected_targets_with_bonus_hits(
                                circle_id=normalized_circle_id,
                                maker_id=normalized_maker_id,
                                release_date=normalized_date,
                                target_rjcodes=normalized_target_rjcodes,
                                hidden_hits=list(hidden_hits_by_rjcode.values()),
                            )
                            if set(normalized_target_rjcodes).issubset(covered_targets):
                                selected_probe_stopped_on_hit = True
                                break
                finally:
                    await self._release_candidate_shards(candidate_shards)
            cached_hit_count += cached_hits
            request_count += requests
            has_errors, error_samples = self._probe_features_block_conclusion(candidate_features.values())
            if has_errors:
                raise RuntimeError(f"DLsite RJ 探测异常，未产出特典结论：{'; '.join(error_samples)}")
            hidden_hits = list(hidden_hits_by_rjcode.values())
            result = {
                "circle_id": normalized_circle_id,
                "maker_id": normalized_maker_id,
                "release_date": normalized_date,
                "parse_status": parse_status,
                "public_count": len(public_worknos),
                "date_page_public_count": len(date_page_worknos),
                "sou_public_count": len(sou_public),
                "gap_count": gap_count,
                "circle_gap_count": circle_gap_count,
                "circle_edge_window": circle_edge_window,
                "date_page_range_count": date_page_range_count,
                "date_page_range_limit": None if selected_scope else self.DEFAULT_DATE_RANGE_LIMIT,
                "date_page_range_unbounded": bool(selected_scope),
                "selected_scope": selected_scope,
                "target_rjcodes": normalized_target_rjcodes,
                "probe_count": len(leased_probe_candidates),
                "raw_probe_count": len(raw_probe_candidates),
                "candidate_filter_stats": candidate_filter_stats,
                "candidate_shard_count": len(candidate_shards),
                "selected_cache_covered": bool(selected_cache_covered),
                "selected_probe_stopped_on_hit": bool(selected_probe_stopped_on_hit),
                "candidate_shards": [
                    {key: shard[key] for key in ("index", "start_rjcode", "end_rjcode", "count")}
                    for shard in candidate_shards
                ],
                "cached_hit_count": cached_hit_count,
                "request_count": request_count,
                "hit_count": len(hidden_hits),
                "inserted_count": inserted_count,
                "budget_reached": bool(budget_reached),
                "hit_rjcodes": [feature.workno for feature in hidden_hits],
                "reused_hit_index": bool(reusable_hidden_hits),
            }
            return self._finish_probe_date_result(
                circle_id=normalized_circle_id,
                maker_id=normalized_maker_id,
                release_date=normalized_date,
                gap_limit=gap_limit,
                mode_key=mode_key,
                hidden_hits=hidden_hits,
                target_original_rjcodes=normalized_target_rjcodes if selected_scope else None,
                result=result,
            )
        except Exception as exc:
            db = SessionLocal()
            try:
                date_row = self._upsert_date_row(
                    db,
                    maker_id=normalized_maker_id,
                    circle_id=normalized_circle_id,
                    release_date=normalized_date,
                    gap_limit=gap_limit,
                )
                date_row.mode = mode_key
                date_row.status = "failed"
                date_row.error_message = str(exc)[:2000]
                date_row.finished_at = datetime.now()
                db.commit()
            finally:
                db.close()
            raise

    async def probe_circle_dates(
        self,
        *,
        circle_id: str,
        maker_id: str = "",
        release_dates: Optional[List[str]] = None,
        mode: str = "normal",
        gap_limit: int = DEFAULT_GAP_LIMIT,
        batch_size: int = DEFAULT_BATCH_SIZE,
        concurrency: int = DEFAULT_CONCURRENCY,
        job_id: str = "",
        selected_rjcodes_by_date: Optional[Dict[str, Sequence[str]]] = None,
        progress_callback: Optional[Callable[[int, str, Dict[str, Any]], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        limits = self.resolve_probe_runtime_limits(mode=mode, batch_size=batch_size, concurrency=concurrency)
        batch_size = int(limits["batch_size"])
        concurrency = int(limits["concurrency"])
        context = self.resolve_circle_context(circle_id, maker_id)
        normalized_circle_id = context["circle_id"]
        normalized_maker_id = context["maker_id"]
        if not normalized_maker_id:
            raise ValueError("未找到该社团的 DLsite maker_id，请先建立社团索引")
        dates = [self.normalize_date(value) for value in (release_dates or [])]
        dates = [value for value in dates if value]
        if not dates:
            dates = self.list_indexed_release_dates(normalized_circle_id, normalized_maker_id, mode=mode)
        if not dates:
            raise ValueError("没有可探测的已索引发售日")
        dates = self._order_probe_release_dates(
            circle_id=normalized_circle_id,
            maker_id=normalized_maker_id,
            dates=dates,
        )
        normalized_selected_by_date: Dict[str, List[str]] = {}
        for raw_date, raw_codes in dict(selected_rjcodes_by_date or {}).items():
            normalized_date = self.normalize_date(raw_date)
            if not normalized_date:
                continue
            normalized_codes = self._dedupe([
                normalized
                for normalized in (self.normalize_rjcode(value) for value in (raw_codes or []))
                if normalized
            ])
            if normalized_codes:
                normalized_selected_by_date[normalized_date] = normalized_codes

        async with self._acquire_active_job_slot(job_id):
            return await self._probe_circle_dates_locked(
                context=context,
                dates=dates,
                mode=mode,
                gap_limit=gap_limit,
                batch_size=batch_size,
                concurrency=concurrency,
                job_id=job_id,
                selected_rjcodes_by_date=normalized_selected_by_date,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

    async def _probe_circle_dates_locked(
        self,
        *,
        context: Dict[str, str],
        dates: List[str],
        mode: str,
        gap_limit: int,
        batch_size: int,
        concurrency: int,
        job_id: str = "",
        selected_rjcodes_by_date: Optional[Dict[str, Sequence[str]]] = None,
        progress_callback: Optional[Callable[[int, str, Dict[str, Any]], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        normalized_circle_id = context["circle_id"]
        normalized_maker_id = context["maker_id"]
        normalized_selected_by_date = dict(selected_rjcodes_by_date or {})
        results: List[Dict[str, Any]] = []
        total = len(dates)
        date_order = {release_date: index for index, release_date in enumerate(dates)}
        worker_count = max(1, min(int(concurrency or self.DEFAULT_CONCURRENCY), total))
        product_info_concurrency = min(worker_count, self.DEFAULT_PRODUCT_INFO_CONCURRENCY)
        queue: asyncio.Queue[Tuple[int, str]] = asyncio.Queue()
        result_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        for index, release_date in enumerate(dates, start=1):
            queue.put_nowait((index, release_date))

        async def append_result(result: Dict[str, Any]) -> int:
            async with result_lock:
                results.append(result)
                return sum(int(item.get("probe_count") or 0) for item in results)

        def completed_probe_count_snapshot() -> int:
            return sum(int(item.get("probe_count") or 0) for item in results)

        async def probe_worker(worker_index: int) -> None:
            worker_label = f"并发 {worker_index}/{worker_count}"
            while True:
                if stop_event.is_set():
                    return
                if cancel_callback and cancel_callback():
                    stop_event.set()
                    raise asyncio.CancelledError()
                try:
                    index, release_date = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                completed_probe_count = completed_probe_count_snapshot()
                if progress_callback:
                    progress_callback(
                        max(1, int(((index - 1) / max(total, 1)) * 100)),
                        f"{worker_label} 探测 {release_date} 的 RJ 缺口",
                        {
                            "release_date": release_date,
                            "batch_index": index,
                            "batch_total": total,
                            "worker_index": worker_index,
                            "worker_total": worker_count,
                            "checked_probe_count": completed_probe_count,
                            "probe_count": completed_probe_count,
                        },
                    )

                def emit_date_probe_progress(meta: Dict[str, Any]) -> None:
                    if not progress_callback:
                        return
                    current_total = max(0, int((meta or {}).get("probe_count") or 0))
                    current_checked = max(0, int((meta or {}).get("checked_probe_count") or 0))
                    current_checked = min(current_checked, current_total) if current_total else current_checked
                    date_fraction = (current_checked / current_total) if current_total else 0
                    pct = max(1, min(99, int(((index - 1 + date_fraction) / max(total, 1)) * 100)))
                    latest_completed_probe_count = completed_probe_count_snapshot()
                    progress_callback(
                        pct,
                        f"{worker_label} 探测 {release_date} 的 RJ 缺口：{current_checked}/{current_total}",
                        {
                            "release_date": release_date,
                            "batch_index": index,
                            "batch_total": total,
                            "worker_index": worker_index,
                            "worker_total": worker_count,
                            "current_probe_checked_count": current_checked,
                            "current_probe_total_count": current_total,
                            "checked_probe_count": latest_completed_probe_count + current_checked,
                            "probe_count": latest_completed_probe_count + current_total,
                        },
                    )

                try:
                    result = await self.probe_date(
                        circle_id=normalized_circle_id,
                        maker_id=normalized_maker_id,
                        release_date=release_date,
                        gap_limit=gap_limit,
                        batch_size=batch_size,
                        concurrency=product_info_concurrency,
                        mode=mode,
                        job_id=job_id,
                        target_rjcodes=normalized_selected_by_date.get(release_date) or [],
                        probe_progress_callback=emit_date_probe_progress,
                    )
                except asyncio.CancelledError:
                    stop_event.set()
                    raise
                except Exception as exc:
                    if self._is_fatal_probe_exception(exc):
                        stop_event.set()
                        logger.error(
                            "[DLsite特典探测] 致命错误，停止剩余 worker job_id=%s worker=%s release_date=%s error=%s",
                            job_id,
                            worker_index,
                            release_date,
                            exc,
                            exc_info=True,
                        )
                        raise
                    result = self._failed_date_result(
                        circle_id=normalized_circle_id,
                        maker_id=normalized_maker_id,
                        release_date=release_date,
                        exc=exc,
                    )
                    logger.warning(
                        "[DLsite特典探测] 发售日局部失败，继续剩余 worker job_id=%s worker=%s release_date=%s error=%s",
                        job_id,
                        worker_index,
                        release_date,
                        exc,
                    )
                finally:
                    queue.task_done()

                completed_probe_count = await append_result(result)
                if progress_callback:
                    message = (
                        f"{worker_label} 跳过 {release_date}：{str(result.get('error_message') or '')[:80]}"
                        if result.get("failed")
                        else f"{worker_label} 完成 {release_date}：命中 {result.get('hit_count', 0)} 个"
                    )
                    progress_callback(
                        min(99, int((len(results) / max(total, 1)) * 100)),
                        message,
                        {
                            "release_date": release_date,
                            "batch_index": index,
                            "batch_total": total,
                            "worker_index": worker_index,
                            "worker_total": worker_count,
                            "checked_probe_count": completed_probe_count,
                            "probe_count": completed_probe_count,
                            "last_result": result,
                        },
                    )

        worker_tasks = [asyncio.create_task(probe_worker(index)) for index in range(1, worker_count + 1)]
        try:
            await asyncio.gather(*worker_tasks)
        except asyncio.CancelledError:
            stop_event.set()
            for worker_task in worker_tasks:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            raise
        except Exception:
            stop_event.set()
            for worker_task in worker_tasks:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            raise
        results.sort(key=lambda item: date_order.get(str(item.get("release_date") or ""), total))
        failed_dates = [str(item.get("release_date") or "") for item in results if bool(item.get("failed"))]

        summary = {
            "circle_id": normalized_circle_id,
            "circle_name": context.get("circle_name") or "",
            "maker_id": normalized_maker_id,
            "mode": mode or "normal",
            "gap_limit": int(gap_limit or self.DEFAULT_GAP_LIMIT),
            "date_count": len(results),
            "public_count": sum(int(item.get("public_count") or 0) for item in results),
            "date_page_public_count": sum(int(item.get("date_page_public_count") or 0) for item in results),
            "sou_public_count": sum(int(item.get("sou_public_count") or 0) for item in results),
            "gap_count": sum(int(item.get("gap_count") or 0) for item in results),
            "circle_gap_count": sum(int(item.get("circle_gap_count") or 0) for item in results),
            "date_page_range_count": sum(int(item.get("date_page_range_count") or 0) for item in results),
            "probe_count": sum(int(item.get("probe_count") or 0) for item in results),
            "cached_hit_count": sum(int(item.get("cached_hit_count") or 0) for item in results),
            "request_count": sum(int(item.get("request_count") or 0) for item in results),
            "hit_count": sum(int(item.get("hit_count") or 0) for item in results),
            "inserted_count": sum(int(item.get("inserted_count") or 0) for item in results),
            "original_count": sum(int(item.get("original_count") or 0) for item in results),
            "original_concluded_count": sum(int(item.get("original_concluded_count") or 0) for item in results),
            "original_pending_count": sum(int(item.get("original_pending_count") or 0) for item in results),
            "original_has_bonus_count": sum(int(item.get("original_has_bonus_count") or 0) for item in results),
            "original_no_bonus_count": sum(int(item.get("original_no_bonus_count") or 0) for item in results),
            "skipped_count": sum(1 for item in results if bool(item.get("skipped"))),
            "incomplete_count": sum(1 for item in results if bool(item.get("incomplete"))),
            "failed_count": len(failed_dates),
            "failed_dates": failed_dates,
            "budget_reached": any(bool(item.get("budget_reached")) for item in results),
            "dates": results,
        }
        return summary

    def get_circle_status(self, circle_id: str, limit: int = 20) -> Dict[str, Any]:
        normalized_circle_id = str(circle_id or "").strip()
        db = SessionLocal()
        try:
            rows = (
                db.query(DLsiteBonusProbeDate)
                .filter(DLsiteBonusProbeDate.circle_id == normalized_circle_id)
                .order_by(DLsiteBonusProbeDate.updated_at.desc())
                .limit(max(1, int(limit or 20)))
                .all()
            )
            return {
                "circle_id": normalized_circle_id,
                "items": [row.to_dict() for row in rows],
                "total": len(rows),
                "latest": rows[0].to_dict() if rows else None,
            }
        finally:
            db.close()


_dlsite_bonus_probe_service: Optional[DLsiteBonusProbeService] = None


def get_dlsite_bonus_probe_service() -> DLsiteBonusProbeService:
    global _dlsite_bonus_probe_service
    if _dlsite_bonus_probe_service is None:
        _dlsite_bonus_probe_service = DLsiteBonusProbeService()
    return _dlsite_bonus_probe_service
