from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote


from ..config.settings import get_config
from ..models.database import (
    ASMRDownloadSession,
    CircleExternalIdentity,
    ASMRWork,
    CircleCatalog,
    CircleWork,
    DLsiteBonusOriginalProbeState,
    LibraryOwnedWork,
    LibrarySnapshot,
    SessionLocal,
    WorkCanonicalLink,
    WorkMetadata,
    get_local_now,
)
from .activity_log_service import log_circle_completion_event
from .asmr_download_service import (
    ASMR_PROBE_STATUS_AVAILABLE,
    ASMR_PROBE_STATUS_MISSING,
    ASMR_PROBE_STATUS_UNAVAILABLE,
    get_asmr_download_service,
)
from .asmr_resource_service import get_asmr_resource_service
from .circle_image_cache_service import get_circle_image_cache_service
from .dlsite_service import DLsiteWorkSummary, get_dlsite_service
from .metadata_service import MetadataService
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class CircleIndexPerfTracker:
    """单次社团索引的耗时 / 调用次数埋点收集器。

    设计目标：

    - **不引入新依赖**：纯 dataclass + ``time.monotonic()`` + 普通 dict 计数，
      不依赖 Prometheus / OpenTelemetry，避免冷启动复杂度。
    - **阶段维度记账**：以 ``with tracker.timed('candidate_collect')`` 标记阶段，
      自动写入 ``stage_ms``。``timed`` 支持 ``__enter__/__exit__`` 与 ``async with``。
    - **业务计数器维度记账**：``inc('kikoeru_search_calls')`` 风格，可在 P1-P8 各阶段
      累加；只对实际感兴趣的字段累加，未累加的字段不会进 detail，减少噪音。
    - **快照入日志**：``snapshot()`` 把 ``stage_ms`` / ``counters`` / ``total_ms``
      合成一份扁平 dict 写到 ``index_completed.detail['perf']``，方便后续基于
      操作历史导出。``snapshot()`` 可在任意阶段调用，方便 fail 时也能拿到部分数据。

    使用示例：

    ```python
    perf = CircleIndexPerfTracker()
    with perf.timed("phase1_external_snapshot"):
        await self._collect_external_snapshot(..., perf=perf)
    perf.inc("dlsite_summary_calls", 3)
    detail["perf"] = perf.snapshot()
    ```
    """
    stage_ms: Dict[str, float] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    started_at_monotonic: float = field(default_factory=time.monotonic)

    def inc(self, key: str, amount: int = 1) -> None:
        """累加业务计数器。``amount`` 可为负，但通常不应出现。"""
        if not key:
            return
        try:
            self.counters[key] += int(amount)
        except Exception:
            # counters 必须始终是 int → defaultdict(int) 的契约；
            # 任意上游写错类型时不要抛，记录后吞掉。
            logger.debug("[社团补全·perf] inc 类型异常 key=%s amount=%r", key, amount, exc_info=True)

    def add_stage(self, stage: str, duration_ms: float) -> None:
        """直接补登一段阶段耗时；``timed`` 内部就调它。"""
        if not stage:
            return
        try:
            ms = float(duration_ms)
        except Exception:
            return
        self.stage_ms[stage] = max(0.0, ms)

    def timed(self, stage: str) -> "_PerfStageScope":
        """上下文管理：``with perf.timed('phase'): ...``。"""
        return _PerfStageScope(self, stage)

    def snapshot(self) -> Dict[str, Any]:
        """打包写入 ``index_completed.detail['perf']``。``total_ms`` 是从 tracker 实例化
        起到 snapshot 调用为止的总耗时；和外层 ``index_circle_catalog`` 自己算的
        ``duration_ms`` 不必完全相同（外层覆盖 progress callback 等额外阶段）。
        """
        return {
            "total_ms": max(0, int((time.monotonic() - self.started_at_monotonic) * 1000)),
            "stage_ms": {k: int(round(v)) for k, v in self.stage_ms.items()},
            "counters": dict(self.counters),
        }


class _PerfStageScope:
    """``CircleIndexPerfTracker.timed`` 的上下文实现：进入时记 start、退出时算 ms。

    同时支持同步 ``with`` 和异步 ``async with``，因为阶段里既有同步聚合，
    也有 ``await asyncio.gather(...)`` 这种 awaitable。
    """

    __slots__ = ("_tracker", "_stage", "_started_at")

    def __init__(self, tracker: "CircleIndexPerfTracker", stage: str) -> None:
        self._tracker = tracker
        self._stage = stage
        self._started_at = 0.0

    def __enter__(self) -> "_PerfStageScope":
        self._started_at = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._tracker.add_stage(self._stage, (time.monotonic() - self._started_at) * 1000)

    async def __aenter__(self) -> "_PerfStageScope":
        self._started_at = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._tracker.add_stage(self._stage, (time.monotonic() - self._started_at) * 1000)


@dataclass
class CircleCompletionSnapshot:
    """社团补全任务的外部数据快照（Phase 1 一次性收集，Phase 2 纯本地查询不再触网）。

    设计要点：
    - **只显式持有"现有 TTL cache 没有"的数据**：ASMR.one 的 ``fetch_work_info`` /
      ``fetch_track_list`` 没有内部 cache，每次都打 HTTP，必须自建 snapshot。
    - **DLsite metadata / canonical** 走现有 ``_metadata_cache`` /
      ``_canonical_cache``。本地拥有态不在这里查远程服务，而是在聚合阶段由 ready
      库存索引投影到兼容字段。
    - ``candidate_rjcodes`` 是 Phase 1 的初始候选 RJ 列表（去重，含本地 /
      DLsite 等来源）；``all_rjcodes`` 是 candidate ∪ 全部 linked_rjcodes，是
      Phase 2 真正需要查 ASMR 的 RJ 全集。
    - ``canonical_rj_by_rj`` / ``chain_rjs_by_canonical`` 描述"作品链路"：
      同一部作品的原版 + 各语言翻译/重制版共享同一个 canonical RJ。

    用 ``contains_asmr(rj)`` / ``get_asmr_work_info(rj)`` / ``get_asmr_tracks(rj)``
    三个查询接口屏蔽内部 dict 结构，避免下游代码写 ``snapshot.asmr_work_info_by_rj.get()``
    再忘了 normalize。
    """
    candidate_rjcodes: List[str] = field(default_factory=list)
    all_rjcodes: List[str] = field(default_factory=list)
    asmr_work_info_by_rj: Dict[str, Optional[Dict[str, Any]]] = field(default_factory=dict)
    asmr_tracks_by_rj: Dict[str, Optional[List[Any]]] = field(default_factory=dict)
    # ★ 作品链路去重：rj -> 该 rj 所属的 canonical RJ（原版作品 RJ）。
    canonical_rj_by_rj: Dict[str, str] = field(default_factory=dict)
    # ★ 作品链路全集：canonical RJ -> 链上所有 RJ 的有序列表（含 canonical 自身、
    #   各语言翻译版、各重制版）。用于 ASMR 探测和库存索引命中归并。
    chain_rjs_by_canonical: Dict[str, List[str]] = field(default_factory=dict)
    # ★ canonical RJ -> canonical_info dict（含 ``linked_rjcodes`` / ``link_map``）。
    # Wave 2a 用 ``link_map`` 按"简中 > 繁中 > 原作 > 其他"语言优先级选 preferred，
    # 只对每条链路的 preferred 一条 RJ 探测 ASMR.one（命中即停 + miss 时按链上次序
    # fallback），把 ASMR.one HTTP 调用从"链上 N 条全量"压到 1-N 条按需。
    canonical_info_by_canonical: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def contains_asmr(self, rjcode: str) -> bool:
        """RJ 在 asmr.one 是否同时有 work_info + tracks（即可下载）。"""
        rj = (rjcode or "").upper()
        return bool(self.asmr_work_info_by_rj.get(rj)) and bool(self.asmr_tracks_by_rj.get(rj))

    def get_asmr_work_info(self, rjcode: str) -> Optional[Dict[str, Any]]:
        rj = (rjcode or "").upper()
        return self.asmr_work_info_by_rj.get(rj)

    def get_asmr_tracks(self, rjcode: str) -> Optional[List[Any]]:
        rj = (rjcode or "").upper()
        return self.asmr_tracks_by_rj.get(rj)

    def get_canonical_rj(self, rjcode: str) -> Optional[str]:
        """获取某个 RJ 所属作品链路的 canonical RJ；未知则返回 ``None``。"""
        rj = (rjcode or "").upper()
        return self.canonical_rj_by_rj.get(rj)

    def get_chain_rjs(self, canonical_rjcode: str) -> List[str]:
        """获取某个 canonical 链路上的全部 RJ（含 canonical 自身）。"""
        canonical = (canonical_rjcode or "").upper()
        return list(self.chain_rjs_by_canonical.get(canonical, ()))


class CircleCompletionService:
    DL_SEARCH_URL = "https://www.dlsite.com/maniax/fsr/=/keyword/{keyword}"
    _COMPLETION_STATE_REDIS_TTL_SECONDS = 600
    _COMPLETION_PAGE_REDIS_TTL_SECONDS = 120
    _COMPLETION_SUMMARY_REDIS_TTL_SECONDS = 120
    _COMPLETION_CODES_REDIS_TTL_SECONDS = 120
    _COMPLETION_RECENT_REDIS_TTL_SECONDS = 30
    _COMPLETION_BUILD_LOCK_SECONDS = 12
    _COMPLETION_ALIAS_REDIS_TTL_SECONDS = 86400
    # 封面缓存键从展示 RJ 统一为图片 URL 中的真实 RJ；升级版本让 Redis / L1
    # 中仍指向旧文件名的社团视图立即失效并按新键重建。
    _COMPLETION_CACHE_SCHEMA_VERSION = 9

    def __init__(self):
        self.metadata_service = MetadataService()
        self.dlsite_service = get_dlsite_service()
        self.asmr_service = get_asmr_download_service()
        self.asmr_resource_service = get_asmr_resource_service()
        # 长期运行下原裸 dict 会无界增长，全部换成 TTL+LRU 受控缓存：
        # 索引任务保留 24h，足够前端轮询；超 64 个并发任务才挤掉最老。
        self._index_jobs: TTLCache = TTLCache(max_size=64, ttl_seconds=86400, name="circle.index_jobs")
        # variant / probe 是 RJ × link_type × lang 维度，量大但单条小，给较大上限。
        self._public_variant_cache: TTLCache = TTLCache(max_size=4096, ttl_seconds=3600, name="circle.public_variant")
        self._asmr_probe_cache: TTLCache = TTLCache(max_size=2048, ttl_seconds=3600, name="circle.asmr_probe")
        # metadata / canonical 单条体积大，限严些；1h TTL 足以覆盖一次社团补全流程。
        self._metadata_cache: TTLCache = TTLCache(max_size=512, ttl_seconds=3600, name="circle.metadata")
        self._completion_view_cache: TTLCache = TTLCache(max_size=128, ttl_seconds=600, name="circle.completion_view")
        self._completion_state_cache: TTLCache = TTLCache(max_size=128, ttl_seconds=180, name="circle.completion_state")
        self._completion_summary_cache: TTLCache = TTLCache(max_size=256, ttl_seconds=60, name="circle.completion_summary")
        self._completion_page_cache: TTLCache = TTLCache(max_size=512, ttl_seconds=60, name="circle.completion_page")
        self._completion_codes_cache: TTLCache = TTLCache(max_size=256, ttl_seconds=60, name="circle.completion_codes")
        self._completion_recent_cache: TTLCache = TTLCache(max_size=128, ttl_seconds=30, name="circle.completion_recent")
        self._inventory_translation_search_cache: TTLCache = TTLCache(
            max_size=2048,
            ttl_seconds=300,
            name="circle.inventory_translation_search",
        )
        self._completion_state_singleflight_lock = asyncio.Lock()
        self._completion_redis_lock_tokens: Dict[str, str] = {}
        self._completion_redis_lock_guard = threading.Lock()
        # ⚠ canonical cache 必须够大装下"大社团一次索引涉及的所有链路 RJ"：
        # 实测 RaRo（304 件）展开后涉及 ~1600 个 RJ，旧 max_size=1024 会触发 LRU 淘汰，
        # wave1 批量预热写进 1600 条但留下最后 1024 条，前 ~600 条全被踢出，
        # 导致 resolve_canonical_rj 仍然走 DB+HTTP 慢路径。
        self._canonical_cache: TTLCache = TTLCache(max_size=16384, ttl_seconds=3600, name="circle.canonical")
        self._download_preview_jobs: TTLCache = TTLCache(max_size=32, ttl_seconds=3600, name="circle.download_preview_jobs")
        # 下面两个原本就有 expires_at 字段，结构不变以兼容现有读写。
        self._kikoeru_circle_id_cache: Dict[str, tuple[str, float]] = {}
        self._local_download_fallback_cache: Dict[str, Any] = {"expires_at": 0.0, "data": {}}
        # P6 / P7：把"写库后才跑的耗时工作"挪到后台。同 circle_id 同时只跑一个，避免连续点击索引
        # 触发并发任务竞争 DLsite / 图片 CDN，并让上层任务真正能"用户点击 → 索引完成"快速返回。
        self._cover_cache_tasks: Dict[str, asyncio.Task] = {}
        self._cover_alias_restore_tasks: Dict[str, asyncio.Task] = {}
        self._cover_alias_restore_pending: Dict[str, Set[Tuple[str, str]]] = {}
        self._bonus_refresh_tasks: Dict[str, asyncio.Task] = {}
        # 本地拥有态全量快照只允许后台维护；单社团索引点击路径必须走当前社团局部核对。
        # 线上日志显示首次全量 await 会在 "同步本地拥有态索引" 卡 80s+，期间前端轮询和 SSE 都会被拖慢。
        self._local_owned_sync_state: Dict[str, Any] = {
            "last_completed_at": 0.0,
            "background_task": None,  # type: Optional[asyncio.Task]
        }
        # ⚠ 性能优化：wave1 批量写 WorkCanonicalLink 的 buffer。
        # ``resolve_canonical_rj`` 默认每次 RJ 解析完都立即 ``commit()``，wave1 阶段
        # 587 个 RJ 串行触发数据库写入，加上 SessionLocal/SELECT 同步阻塞
        # event loop，让 ``wave1_sem=20`` 实际退化为接近串行（实测 16-19 分）。
        # ``_canonical_buffered_writes()`` with 块期间设为 list，``resolve_canonical_rj``
        # 把待写 ``(canonical_rjcode, link_rows)`` append 到这里，with 退出时一次性
        # 批量 DELETE + INSERT + COMMIT。设为 ``None`` 表示走原直写路径。
        self._canonical_write_buffer: Optional[List[Tuple[str, List[Dict[str, Any]]]]] = None
        # ⚠ 性能修复：`_fetch_metadata_dict` 单飞锁。
        # 实测 322 件作品社团索引 ``stage_prepare_candidates`` 耗时 16 分钟，root cause 是
        # 278 个 candidate 并发 await 同一个 ~150 个 canonical 的 metadata，每个 canonical
        # 都被多个 candidate 同时打 → in-memory cache miss + DB miss + 触网，惊群效应。
        # 单飞锁保证同一 RJ 同一时刻只 await 一次真实 fetch，剩下的等结果。
        # **不**用 Lock，因为锁本身需要先取再释，重入会卡死；用 Future 字典 ``inflight[rj]``：
        #   - first arrival 创建 Future、跑 fetch、set_result
        #   - 后续 arrival 直接 await 现有 Future、零网络
        # Future 完成后立刻清出字典，让后续真正 refresh 的 path 仍能触网。
        self._metadata_inflight: Dict[str, asyncio.Future] = {}

    def _completion_view_cache_key(
        self,
        circle_id_or_query: str,
        *,
        only_missing: bool = False,
        only_downloadable: bool = False,
        include_dl_only: bool = True,
    ) -> str:
        return "|".join([
            str(circle_id_or_query or "").strip(),
            "missing=1" if only_missing else "missing=0",
            "downloadable=1" if only_downloadable else "downloadable=0",
            "dlonly=1" if include_dl_only else "dlonly=0",
        ])

    def _completion_cache_scope(self, value: Any) -> str:
        text = str(value or "").strip() or "_"
        text = re.sub(r"[\s\r\n\t|:]+", "-", text)
        return text[:160] or "_"

    def _completion_hash_payload(self, payload: Any) -> str:
        try:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        except Exception:
            raw = repr(payload)
        return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:24]

    def _completion_state_builder_overridden(self) -> bool:
        return "_build_completion_view_state" in self.__dict__

    def _completion_redis_service(self):
        try:
            from .redis_service import get_redis_service

            service = get_redis_service()
            if not service.is_enabled():
                return None
            return service
        except Exception:
            logger.debug("[社团补全·缓存] Redis service 获取失败", exc_info=True)
            return None

    def _completion_redis_get_json(self, type_name: str, item_id: str) -> Any:
        service = self._completion_redis_service()
        if service is None:
            return None
        try:
            return service.get_json("circle-completion", type_name, item_id)
        except Exception:
            logger.debug("[社团补全·缓存] Redis 读取失败 type=%s key=%s", type_name, item_id, exc_info=True)
            return None

    def _completion_redis_set_json(self, type_name: str, item_id: str, payload: Any, *, ttl_seconds: int) -> None:
        service = self._completion_redis_service()
        if service is None:
            return
        try:
            service.set_json("circle-completion", type_name, item_id, payload, ttl_seconds=ttl_seconds)
        except Exception:
            logger.debug("[社团补全·缓存] Redis 写入失败 type=%s key=%s", type_name, item_id, exc_info=True)

    def _completion_redis_client(self):
        service = self._completion_redis_service()
        if service is None:
            return None, None
        try:
            client = service.client(required=False)
            return service, client
        except Exception:
            logger.debug("[社团补全·缓存] Redis client 获取失败", exc_info=True)
            return service, None

    def _completion_redis_int(self, *parts: Any) -> int:
        service, client = self._completion_redis_client()
        if service is None or client is None:
            return 0
        try:
            raw = client.get(service.key("circle-completion", *parts))
            return max(0, int(raw or 0))
        except Exception:
            logger.debug("[社团补全·缓存] Redis 版本读取失败 parts=%s", parts, exc_info=True)
            return 0

    def _completion_redis_incr(self, *parts: Any) -> int:
        service, client = self._completion_redis_client()
        if service is None or client is None:
            return 0
        try:
            return int(client.incr(service.key("circle-completion", *parts)) or 0)
        except Exception:
            logger.debug("[社团补全·缓存] Redis 版本递增失败 parts=%s", parts, exc_info=True)
            return 0

    def _completion_version_tag(self, circle_id_or_query: str) -> str:
        scope = self._completion_cache_scope(circle_id_or_query)
        epoch = self._completion_redis_int("epoch", "global")
        version = self._completion_redis_int("version", scope)
        return f"s{self._COMPLETION_CACHE_SCHEMA_VERSION}:e{epoch}:v{version}"

    def _completion_state_cache_key(self, circle_id_or_query: str, version_tag: str) -> str:
        return f"{self._completion_cache_scope(circle_id_or_query)}|state|{version_tag}"

    def _completion_query_cache_key(self, kind: str, circle_id_or_query: str, params: Dict[str, Any]) -> str:
        payload = {"scope": self._completion_cache_scope(circle_id_or_query), "params": params}
        return f"{self._completion_cache_scope(circle_id_or_query)}|{kind}|{self._completion_version_tag(circle_id_or_query)}|{self._completion_hash_payload(payload)}"

    def _completion_recent_cache_key(self, keyword: str, limit: int) -> str:
        payload = {
            "keyword": self.normalize_circle_name(keyword),
            "limit": max(1, int(limit or 30)),
            "epoch": self._completion_redis_int("epoch", "global"),
            "recent": self._completion_redis_int("version", "recent"),
        }
        return f"recent|{self._completion_hash_payload(payload)}"

    def _completion_alias_map_key(self, circle_scope: str) -> str:
        return f"{self._completion_cache_scope(circle_scope)}|aliases"

    def _completion_alias_cache_get(self, circle_scope: str) -> List[str]:
        payload = self._completion_redis_get_json("aliases", self._completion_alias_map_key(circle_scope))
        aliases = payload.get("aliases") if isinstance(payload, dict) else []
        result: List[str] = []
        for alias in aliases or []:
            scope = self._completion_cache_scope(alias)
            if scope and scope not in result:
                result.append(scope)
        return result

    def _completion_alias_cache_set(self, circle_scope: str, aliases: List[str]) -> None:
        normalized_circle = self._completion_cache_scope(circle_scope)
        normalized_aliases: List[str] = []
        for alias in [normalized_circle, *(aliases or [])]:
            scope = self._completion_cache_scope(alias)
            if scope and scope not in normalized_aliases:
                normalized_aliases.append(scope)
        self._completion_redis_set_json(
            "aliases",
            self._completion_alias_map_key(normalized_circle),
            {"circle_scope": normalized_circle, "aliases": normalized_aliases, "updated_at": datetime.now().isoformat()},
            ttl_seconds=self._COMPLETION_ALIAS_REDIS_TTL_SECONDS,
        )

    def _completion_register_aliases(self, circle_scope: str, aliases: List[str]) -> List[str]:
        normalized_circle = self._completion_cache_scope(circle_scope)
        merged = self._completion_alias_cache_get(normalized_circle)
        for alias in [normalized_circle, *(aliases or [])]:
            scope = self._completion_cache_scope(alias)
            if scope and scope not in merged:
                merged.append(scope)
        self._completion_alias_cache_set(normalized_circle, merged)
        return merged

    def _completion_alias_scopes_for_invalidation(self, circle_id_or_query: str) -> List[str]:
        normalized_scope = self._completion_cache_scope(circle_id_or_query)
        aliases = self._completion_alias_cache_get(normalized_scope)
        if normalized_scope not in aliases:
            aliases.insert(0, normalized_scope)
        return aliases

    def _completion_l1_l2_get(self, cache: TTLCache, redis_type: str, cache_key: str) -> Optional[Any]:
        cached = cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
        cached = self._completion_redis_get_json(redis_type, cache_key)
        if cached is not None:
            cache[cache_key] = deepcopy(cached)
            return deepcopy(cached)
        return None

    def _completion_l1_l2_set(
        self,
        cache: TTLCache,
        redis_type: str,
        cache_key: str,
        payload: Any,
        *,
        ttl_seconds: int,
    ) -> None:
        cache[cache_key] = deepcopy(payload)
        self._completion_redis_set_json(redis_type, cache_key, payload, ttl_seconds=ttl_seconds)

    def _completion_store_state_cache(self, requested_key: str, state: Dict[str, Any]) -> None:
        catalog = state.get("catalog") if isinstance(state, dict) else {}
        aliases = {self._completion_cache_scope(requested_key)}
        if isinstance(catalog, dict):
            circle_id = self._completion_cache_scope(catalog.get("circle_id"))
            if circle_id:
                aliases.add(circle_id)
                aliases.update(self._completion_register_aliases(circle_id, list(aliases)))
        for alias in aliases:
            cache_key = self._completion_state_cache_key(alias, self._completion_version_tag(alias))
            self._completion_l1_l2_set(
                self._completion_state_cache,
                "state",
                cache_key,
                state,
                ttl_seconds=self._COMPLETION_STATE_REDIS_TTL_SECONDS,
            )

    def _completion_try_acquire_build_lock(self, circle_id_or_query: str) -> Optional[str]:
        service, client = self._completion_redis_client()
        if service is None or client is None:
            return None
        scope = self._completion_cache_scope(circle_id_or_query)
        key = service.key("circle-completion", "build_lock", scope)
        token = uuid.uuid4().hex
        try:
            acquired = bool(client.set(key, token, nx=True, ex=self._COMPLETION_BUILD_LOCK_SECONDS))
        except Exception:
            logger.debug("[社团补全·缓存] Redis build lock 获取失败 circle=%s", circle_id_or_query, exc_info=True)
            return None
        if not acquired:
            return ""
        with self._completion_redis_lock_guard:
            self._completion_redis_lock_tokens[key] = token
        return key

    def _completion_release_build_lock(self, lock_key: Optional[str]) -> None:
        if not lock_key:
            return
        service, client = self._completion_redis_client()
        if service is None or client is None:
            return
        with self._completion_redis_lock_guard:
            token = self._completion_redis_lock_tokens.pop(lock_key, "")
        if not token:
            return
        try:
            if client.get(lock_key) == token:
                client.delete(lock_key)
        except Exception:
            logger.debug("[社团补全·缓存] Redis build lock 释放失败 key=%s", lock_key, exc_info=True)

    async def _wait_for_completion_state_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        for _ in range(20):
            await asyncio.sleep(0.06)
            cached = self._completion_l1_l2_get(self._completion_state_cache, "state", cache_key)
            if isinstance(cached, dict):
                return cached
        return None

    async def _get_completion_view_state(self, circle_id_or_query: str) -> Dict[str, Any]:
        state_key = str(circle_id_or_query or "").strip()
        if not state_key:
            raise ValueError("缺少社团标识")
        if self._completion_state_builder_overridden():
            return deepcopy(self._build_completion_view_state(state_key))
        cache_key = self._completion_state_cache_key(state_key, self._completion_version_tag(state_key))
        cached = self._completion_l1_l2_get(self._completion_state_cache, "state", cache_key)
        if isinstance(cached, dict):
            return cached

        async with self._completion_state_singleflight_lock:
            cache_key = self._completion_state_cache_key(state_key, self._completion_version_tag(state_key))
            cached = self._completion_l1_l2_get(self._completion_state_cache, "state", cache_key)
            if isinstance(cached, dict):
                return cached
            lock_key = self._completion_try_acquire_build_lock(state_key)
            if lock_key == "":
                cached = await self._wait_for_completion_state_cache(cache_key)
                if isinstance(cached, dict):
                    return cached
            try:
                state = self._build_completion_view_state(state_key)
                self._completion_store_state_cache(state_key, state)
                return deepcopy(state)
            finally:
                self._completion_release_build_lock(lock_key)

    def invalidate_completion_view_cache(self, circle_id: str = "") -> int:
        normalized = str(circle_id or "").strip()
        if not normalized:
            size = len(self._completion_view_cache)
            self._completion_view_cache.clear()
            self._completion_state_cache.clear()
            self._completion_summary_cache.clear()
            self._completion_page_cache.clear()
            self._completion_codes_cache.clear()
            self._completion_recent_cache.clear()
            self._completion_redis_incr("epoch", "global")
            self._completion_redis_incr("version", "recent")
            return size
        alias_scopes = self._completion_alias_scopes_for_invalidation(normalized)
        alias_scope_set = set(alias_scopes)
        view_removed = self._completion_view_cache.invalidate_predicate(
            lambda key: isinstance(key, str) and any(key.startswith(f"{scope}|") for scope in alias_scope_set)
        )
        state_removed = self._completion_state_cache.invalidate_predicate(
            lambda key: isinstance(key, str) and any(key.startswith(f"{scope}|state|") for scope in alias_scope_set)
        )
        summary_removed = self._completion_summary_cache.invalidate_predicate(
            lambda key: isinstance(key, str) and any(key.startswith(f"{scope}|summary|") for scope in alias_scope_set)
        )
        page_removed = self._completion_page_cache.invalidate_predicate(
            lambda key: isinstance(key, str) and any(key.startswith(f"{scope}|page|") for scope in alias_scope_set)
        )
        codes_removed = self._completion_codes_cache.invalidate_predicate(
            lambda key: isinstance(key, str) and any(key.startswith(f"{scope}|") for scope in alias_scope_set)
        )
        recent_removed = self._completion_recent_cache.invalidate_predicate(lambda key: isinstance(key, str) and key.startswith("recent|"))
        for scope in alias_scopes:
            self._completion_redis_incr("version", scope)
        self._completion_redis_incr("version", "recent")
        return view_removed + state_removed + summary_removed + page_removed + codes_removed + recent_removed

    def normalize_circle_name(self, value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        text = re.sub(r"\s+", " ", text)
        # 社团名里常混入 ○/●/☆/♡ 等装饰或规避符号；做匹配时去掉符号层差异，
        # 避免 J○大好き / J大好き / J●大好き 这类写法被误判为不同社团。
        text = "".join(
            ch for ch in text
            if not unicodedata.category(ch).startswith(("P", "S"))
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _build_search_keyword_variants(self, keyword: Any) -> List[str]:
        """从原始 circle_query 派生若干变种关键字，按长度优先。

        Kikoeru 的 ``find_circle_id_by_keyword`` 和 ``search_circle_works``
        都是先按 ``works keyword`` 接口搜作品、再从命中作品里抽 ``circle.id``，
        不是直接按 circle 名搜社团实体。如果用户输入的是 Kikoeru 上的全名
        （比如 "悪女名鑑(常世常闇所々)"，前缀是系列名，圆括号内才是真实社团名），
        而作品标题通常不会重复整串 query，整条链路会一路 0 命中，于是
        ``index_circle_catalog`` 最后只能退回 DLsite 关键字搜索，作品就丢了。

        这里把括号内 / 外、以及常见全角分隔符两侧的 token 拆出来当备用关键字，
        让上游能用更精确的子串去 hit 真正属于该社团的作品。变种按"原 query 优先、
        然后越长越优先"排序，避免短 token 过早击中无关 circle。
        """
        raw = unicodedata.normalize("NFKC", str(keyword or "")).strip()
        if not raw:
            return []

        variants: List[str] = [raw]
        bracket_pairs = [("(", ")"), ("[", "]"), ("【", "】"), ("「", "」"), ("『", "』")]
        for left, right in bracket_pairs:
            if left not in raw or right not in raw:
                continue
            head, _, tail = raw.partition(left)
            inner, _, after = tail.partition(right)
            outer = (head + " " + after).strip()
            for part in (inner.strip(), outer):
                if part and part != raw and part not in variants:
                    variants.append(part)
        # 兜底再按全角/半角空格 / 分隔符拆一次，覆盖 "悪女名鑑 常世常闇所々" 这种
        # 不带括号的写法。token 长度 ≥ 2 才接受，避免抓到单字噪音。
        for token in re.split(r"[\s\u3000,，/／・·]+", raw):
            token = token.strip()
            if len(token) >= 2 and token not in variants:
                variants.append(token)
        # 按长度倒序，保留原 query 在最前
        head_keyword = variants[0]
        rest = sorted(variants[1:], key=lambda s: len(s), reverse=True)
        return [head_keyword, *rest]

    def _circle_name_loose_match(self, query: Any, candidate: Any) -> bool:
        """双向宽松匹配 query / candidate 是否同属一个社团。

        Kikoeru 上的社团名常带系列前缀（"悪女名鑑(常世常闇々)"），而 DLsite
        的 maker_name 通常只是核心社团名（"常世常闇々"）。如果只做单向
        ``query in candidate`` 检查，长 query 永远命中不了短 maker_name，
        会让 ``_resolve_seed_maker_id`` / ``fetch_candidate`` 把整社团作品
        误过滤成空。这里对齐 Kikoeru 的 ``find_circle_id_by_keyword``，
        允许双向 substring，并对较短一侧加最低长度阈值，防止
        2~3 字 maker_name 被任意 query 误命中。
        """
        normalized_query = self.normalize_circle_name(query)
        normalized_candidate = self.normalize_circle_name(candidate)
        if not normalized_query or not normalized_candidate:
            # 任意一侧拿不到名字时，让上层根据 maker_id 等更强信号自己决定，
            # 这里返回 True 表示"不要因为名字缺失就否决"。
            return True
        if normalized_query == normalized_candidate:
            return True
        if normalized_query in normalized_candidate:
            return True
        # 反向匹配仅在较短一侧达到最低长度时才接受，避免 "AB" 这种过短串
        # 在 "ABCDE" 系列名里产生大量误命中。CJK 信息密度高，3 字符即有
        # 充分区分度；如果未来遇到误匹配，可调高阈值或改成 token 级匹配。
        if len(normalized_candidate) >= 3 and normalized_candidate in normalized_query:
            return True
        return False

    def _build_circle_name_sql_terms(self, value: Any) -> List[str]:
        """构造数据库粗筛用的社团名片段。

        真正判定仍然走 ``_circle_name_loose_match``。这里的目标只是别在 SQL
        预筛阶段漏掉 ``Lilith [リリス]`` 这类带括号/装饰符的 maker_name。
        """
        raw = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
        normalized = self.normalize_circle_name(value)
        terms: List[str] = []
        for term in [raw, normalized, *self._build_search_keyword_variants(value)]:
            term = unicodedata.normalize("NFKC", str(term or "")).strip().lower()
            if len(term) >= 2 and term not in terms:
                terms.append(term)
        return terms

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

    def _normalize_maker_id(self, value: Any) -> str:
        return str(value or "").strip().upper()

    def _looks_like_non_chinese_translation_title(self, *values: Any) -> str:
        title = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
        if not title:
            return ""
        marker_map = {
            "KO_KR": ["[한국어판]", "한국어판", "韓国語版", "韩语版", "韓語版", "korean ver", "korean version"],
            "ENG": ["english ver", "english version", "英語版", "英文版"],
        }
        for lang, markers in marker_map.items():
            if any(marker in title for marker in markers):
                return lang
        return ""

    def _candidate_belongs_to_identity(
        self,
        *,
        circle_query: str,
        identity: Dict[str, str],
        item: Dict[str, Any],
        metadata: Dict[str, Any],
        canonical_metadata: Dict[str, Any],
    ) -> bool:
        target_maker_id = self._normalize_maker_id(identity.get("maker_id"))
        if target_maker_id:
            maker_ids = {
                self._normalize_maker_id(candidate)
                for candidate in (
                    canonical_metadata.get("maker_id"),
                    metadata.get("maker_id"),
                    item.get("maker_id"),
                )
                if self._normalize_maker_id(candidate)
            }
            if maker_ids:
                return target_maker_id in maker_ids

        target_name = self.normalize_circle_name(identity.get("circle_name") or circle_query)
        if not target_name:
            return True

        maker_name_candidates = [
            str(candidate or "").strip()
            for candidate in (
                canonical_metadata.get("maker_name"),
                metadata.get("maker_name"),
                item.get("maker_name"),
            )
            if str(candidate or "").strip()
        ]
        target_query = identity.get("circle_name") or circle_query
        return any(
            self._circle_name_loose_match(target_query, candidate)
            for candidate in maker_name_candidates
        )

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
        # ★ 优化（C）：简繁中翻译版不再走 ``_is_public_work_available`` HTML probe。
        # 历史现场：一次 33 个候选作品的社团补全任务里，仅这条简繁体 HTML probe
        # 就触发了 698 次页面抓取、其中 580 次 fallback miss——因为 DLsite 公开匿名 API
        # 对 R18 翻译版会返 404，HTML 也不可见，但作品本身 Kikoeru 上能搜到。
        # ``test_dlsite_linkage_no_public_filter`` 已经在 ``get_linked_works`` 路径
        # 验证过：直接信父作品 API 给的 ``language_editions`` 列表才是正确做法。
        # 这里 variant 全部来自上游的 canonical link_map（DLsite 父作品给的关联链），
        # 信它即可，不再用同一个 R18 限制下不可访问的 API 反向验证。
        # 副作用：被默默过滤掉的 R18 翻译版会重新进入候选展示——这本来就是符合
        # Kikoeru 上"能查到 work 就该展示"的设计意图。
        if group_key in {"simplified", "traditional"}:
            result = True
        else:
            try:
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
            # ★ 优化（C）：简繁中翻译版不再用 ``_resolve_translation_page_fallback`` HTML probe
            # 作为"可见性"门禁。变体来自父作品 ``language_editions``，DLsite 在父作品 API
            # 里给的就该信。
            # - cached_title 命中（来自上游 ``metadata_map``）→ 直接返回；
            # - 否则只走 ``get_product_info``（API，带 24h cache + inflight 去重，几乎零成本）
            #   抽 ``work_name``；
            # - API 也没抽到（典型 R18 翻译版匿名 API 404）→ 返回 cached_title（即使是空串），
            #   让上游用别的兜底字段渲染，**不再因为"DLsite 上 HTML probe 未命中"就强行返空串
            #   把翻译版整个挡掉**。
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
    ) -> tuple[Dict[str, Any], str, List[Dict[str, Any]]]:
        metadata_map = metadata_map or {}
        allowed = await self._list_public_display_variants(
            canonical_info,
            fallback_rjcode,
            metadata_map,
        )
        # 并发获取 title，优先读 metadata_map 避免重复 DLsite 请求
        sem = asyncio.Semaphore(6)

        async def _resolve_title(variant: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
            cached = str((metadata_map.get(self.normalize_rjcode(variant.get("rjcode"))) or {}).get("work_name") or "").strip()
            if cached:
                return variant, cached
            async with sem:
                title = await self._resolve_public_display_title(
                    str(variant.get("rjcode") or ""),
                    link_type=variant.get("link_type"),
                    lang=variant.get("lang"),
                    metadata_map=metadata_map,
                )
            return variant, title

        resolved = await asyncio.gather(*[_resolve_title(v) for v in allowed])
        for variant, title in resolved:
            if title:
                return variant, title, allowed
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
        return fallback_variant, fallback_title, allowed

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

        title_probe_items: List[Dict[str, Any]] = []
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
            title_probe_items.append({
                "variant": normalized_variant,
                "link_type": link_type,
                "lang": lang,
            })
            seen.add(normalized)

        # 并发解析非 original variant 的 title，减少串行 DLsite 请求
        sem = asyncio.Semaphore(6)

        async def _resolve_one(item: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
            async with sem:
                title = await self._resolve_public_display_title(
                    item["variant"]["rjcode"],
                    link_type=item["link_type"],
                    lang=item["lang"],
                    metadata_map=metadata_map,
                )
            return item["variant"], title

        resolved = await asyncio.gather(*[_resolve_one(it) for it in title_probe_items])
        for variant, title in resolved:
            if title:
                public_variants.append(variant)

        seen = {self.normalize_rjcode(v.get("rjcode")) for v in public_variants}

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
        sem = asyncio.Semaphore(6)

        async def _check_variant(variant: Dict[str, Any]) -> Optional[str]:
            normalized = self.normalize_rjcode(variant.get("rjcode"))
            if not normalized:
                return None
            async with sem:
                ok = await self._is_public_catalog_variant(
                    normalized,
                    link_type=variant.get("link_type"),
                    lang=variant.get("lang"),
                )
            return normalized if ok else None

        checked = await asyncio.gather(*[_check_variant(v) for v in public_variants])
        for normalized in checked:
            if normalized:
                append_candidate(normalized)

        async def _check_extra(candidate: Any) -> Optional[str]:
            normalized = self.normalize_rjcode(candidate)
            if not normalized:
                return None
            variant = next((
                item for item in public_variants
                if self.normalize_rjcode(item.get("rjcode")) == normalized
            ), None)
            if variant is None:
                return None
            async with sem:
                ok = await self._is_public_catalog_variant(
                    normalized,
                    link_type=variant.get("link_type"),
                    lang=variant.get("lang"),
                )
            return normalized if ok else None

        checked_extra = await asyncio.gather(*[_check_extra(c) for c in list(extra_candidates or [])])
        for normalized in checked_extra:
            if normalized:
                append_candidate(normalized)
        return candidates

    async def _fetch_asmr_work_info_with_status(
        self,
        rjcode: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        probe = getattr(self.asmr_service, "fetch_work_info_with_status", None)
        if callable(probe):
            try:
                return await probe(rjcode)
            except Exception:
                logger.debug("[社团补全·ASMR] 作品信息探测失败 rj=%s", rjcode, exc_info=True)
                return None, ASMR_PROBE_STATUS_UNAVAILABLE
        try:
            work_info = await self.asmr_service.fetch_work_info(rjcode)
        except Exception:
            return None, ASMR_PROBE_STATUS_UNAVAILABLE
        # 兼容旧的 ASMR stub / 外部实现：无法区分 None 是 404 还是网络失败时，
        # 宁可按临时不可用处理，避免把已有可下载状态误清掉。
        return (
            work_info,
            ASMR_PROBE_STATUS_AVAILABLE if work_info else ASMR_PROBE_STATUS_UNAVAILABLE,
        )

    async def _fetch_asmr_track_list_with_status(
        self,
        rjcode: str,
    ) -> Tuple[Optional[List[Any]], str]:
        probe = getattr(self.asmr_service, "fetch_track_list_with_status", None)
        if callable(probe):
            try:
                return await probe(rjcode)
            except Exception:
                logger.debug("[社团补全·ASMR] 文件列表探测失败 rj=%s", rjcode, exc_info=True)
                return None, ASMR_PROBE_STATUS_UNAVAILABLE
        try:
            tracks = await self.asmr_service.fetch_track_list(rjcode)
        except Exception:
            return None, ASMR_PROBE_STATUS_UNAVAILABLE
        return (
            tracks,
            ASMR_PROBE_STATUS_AVAILABLE if tracks else ASMR_PROBE_STATUS_UNAVAILABLE,
        )

    async def _find_public_downloadable_work_with_status(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_candidates: Optional[List[Any]] = None,
        snapshot: Optional[CircleCompletionSnapshot] = None,
        bypass_cache: bool = False,
    ) -> tuple[str, Optional[Dict[str, Any]], str]:
        probe_candidates = await self._build_public_download_probe_candidates(
            canonical_info,
            fallback_rjcode,
            metadata_map=metadata_map,
            extra_candidates=extra_candidates,
        )
        cache_key = "|".join(probe_candidates)
        if cache_key and bypass_cache:
            self._asmr_probe_cache.pop(cache_key, None)
        elif cache_key:
            cached = self._asmr_probe_cache.get(cache_key)
            if cached is not None:
                if len(cached) == 3:
                    return cached
                # 兼容服务热更新前遗留的二元缓存值。
                cached_rjcode, cached_info = cached
                cached_status = ASMR_PROBE_STATUS_AVAILABLE if cached_rjcode else ASMR_PROBE_STATUS_MISSING
                return cached_rjcode, cached_info, cached_status
        unavailable_seen = False
        for probe_rjcode in probe_candidates:
            # ★ Phase 2 路径：snapshot 已包含全 RJ 的 work_info/tracks，直接查不打 HTTP。
            #   未传 snapshot（如老调用点 / 单 RJ 视图重建）时退回原 HTTP 行为。
            if snapshot is not None:
                work_info = snapshot.get_asmr_work_info(probe_rjcode)
                tracks = snapshot.get_asmr_tracks(probe_rjcode)
                work_status = ASMR_PROBE_STATUS_MISSING if not work_info else ASMR_PROBE_STATUS_AVAILABLE
                tracks_status = ASMR_PROBE_STATUS_MISSING if not tracks else ASMR_PROBE_STATUS_AVAILABLE
            else:
                work_info, work_status = await self._fetch_asmr_work_info_with_status(probe_rjcode)
                tracks = None
                if work_info:
                    tracks, tracks_status = await self._fetch_asmr_track_list_with_status(probe_rjcode)
                else:
                    tracks_status = ASMR_PROBE_STATUS_MISSING
            if work_status == ASMR_PROBE_STATUS_UNAVAILABLE or tracks_status == ASMR_PROBE_STATUS_UNAVAILABLE:
                unavailable_seen = True
            if not work_info:
                continue
            if tracks:
                result = (probe_rjcode, work_info)
                if cache_key:
                    self._asmr_probe_cache[cache_key] = (*result, ASMR_PROBE_STATUS_AVAILABLE)
                return (*result, ASMR_PROBE_STATUS_AVAILABLE)
        status = ASMR_PROBE_STATUS_UNAVAILABLE if unavailable_seen else ASMR_PROBE_STATUS_MISSING
        result = ("", None, status)
        if cache_key and status == ASMR_PROBE_STATUS_MISSING:
            self._asmr_probe_cache[cache_key] = result
        return result

    async def _find_public_downloadable_work(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_candidates: Optional[List[Any]] = None,
        snapshot: Optional[CircleCompletionSnapshot] = None,
        bypass_cache: bool = False,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        actual_rjcode, work_info, _status = await self._find_public_downloadable_work_with_status(
            canonical_info,
            fallback_rjcode,
            metadata_map=metadata_map,
            extra_candidates=extra_candidates,
            snapshot=snapshot,
            bypass_cache=bypass_cache,
        )
        return actual_rjcode, work_info

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

    def get_inventory_translation_search_relation(self, rjcode: str) -> Dict[str, Any]:
        """把翻译 RJ 展开为同原作、同语言组的库存搜索别名。

        这里只读 PostgreSQL 的关联表和本地拥有态快照，不触发 DLsite HTTP，
        也不扫描库存目录。原作、英文及未知语言保持精确搜索，避免关联范围过宽。
        """
        from sqlalchemy import or_ as sa_or

        normalized_rj = self.normalize_rjcode(rjcode)
        empty_result = {
            "query_rjcode": normalized_rj,
            "group_key": "",
            "group_label": "",
            "search_rjcodes": [normalized_rj] if normalized_rj else [],
            "related_rjcodes": [],
            "owned_locations": [],
        }
        if not re.fullmatch(r"RJ\d{4,12}", normalized_rj or "", re.IGNORECASE):
            return empty_result

        cached = self._inventory_translation_search_cache.get(normalized_rj)
        if cached is not None:
            return deepcopy(cached)

        db = SessionLocal()
        try:
            anchor_rows = (
                db.query(WorkCanonicalLink)
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    sa_or(
                        WorkCanonicalLink.linked_rjcode == normalized_rj,
                        WorkCanonicalLink.canonical_rjcode == normalized_rj,
                    )
                )
                .all()
            )
            canonical_rjcodes = sorted({
                self.normalize_rjcode(row.canonical_rjcode)
                for row in anchor_rows
                if self.normalize_rjcode(row.canonical_rjcode)
            })
            if not canonical_rjcodes:
                self._inventory_translation_search_cache[normalized_rj] = empty_result
                return deepcopy(empty_result)

            link_rows = (
                db.query(WorkCanonicalLink)
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    WorkCanonicalLink.canonical_rjcode.in_(canonical_rjcodes),
                )
                .all()
            )
            link_meta_by_rj: Dict[str, Dict[str, Any]] = {}
            for row in link_rows:
                linked_rjcode = self.normalize_rjcode(row.linked_rjcode)
                if not linked_rjcode:
                    continue
                link_meta_by_rj[linked_rjcode] = {
                    "link_type": str(row.link_type or "").strip().lower(),
                    "lang": self._normalize_lang_code(row.lang),
                }

            query_meta = link_meta_by_rj.get(normalized_rj) or {}
            if not query_meta and normalized_rj in canonical_rjcodes:
                query_meta = {"link_type": "original", "lang": "JPN"}
            query_group = self._variant_group(
                query_meta.get("link_type"),
                query_meta.get("lang"),
            )
            group_key = str(query_group.get("key") or "")
            if group_key not in {"simplified", "traditional"}:
                result = {
                    **empty_result,
                    "group_key": group_key,
                    "group_label": str(query_group.get("short_label") or ""),
                }
                self._inventory_translation_search_cache[normalized_rj] = result
                return deepcopy(result)

            related_rjcodes = sorted({
                linked_rjcode
                for linked_rjcode, meta in link_meta_by_rj.items()
                if self._variant_group(meta.get("link_type"), meta.get("lang")).get("key") == group_key
            })
            search_rjcodes = [normalized_rj, *[
                candidate for candidate in related_rjcodes if candidate != normalized_rj
            ]]

            owned_locations: List[Dict[str, Any]] = []
            owned_rows = (
                db.query(LibraryOwnedWork)
                .filter(LibraryOwnedWork.canonical_rjcode.in_(canonical_rjcodes))
                .all()
            )
            related_set = set(search_rjcodes)
            for owned_row in owned_rows:
                actual_owned_rjcodes = {
                    self.normalize_rjcode(candidate)
                    for candidate in list(owned_row.owned_rjcodes or [])
                } & related_set
                paths = list(owned_row.owned_paths or [])
                primary_path = str(owned_row.primary_folder_path or "").strip()
                if primary_path and primary_path not in paths:
                    paths.insert(0, primary_path)
                for path_value in paths:
                    path = str(path_value or "").strip()
                    if not path:
                        continue
                    path_rjcodes = {
                        match.upper()
                        for match in re.findall(r"RJ\d{4,12}", path, re.IGNORECASE)
                    }
                    actual_rjcode = next(iter(sorted(path_rjcodes & related_set)), "")
                    if not actual_rjcode and len(actual_owned_rjcodes) == 1:
                        actual_rjcode = next(iter(actual_owned_rjcodes))
                    if not actual_rjcode:
                        continue
                    owned_locations.append({
                        "library_id": str(owned_row.library_id or "").strip(),
                        "path": path,
                        "actual_rjcode": actual_rjcode,
                    })

            result = {
                "query_rjcode": normalized_rj,
                "group_key": group_key,
                "group_label": str(query_group.get("short_label") or ""),
                "search_rjcodes": search_rjcodes,
                "related_rjcodes": [code for code in search_rjcodes if code != normalized_rj],
                "owned_locations": owned_locations,
            }
            self._inventory_translation_search_cache[normalized_rj] = result
            return deepcopy(result)
        finally:
            db.close()

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

    def _is_usable_work_title(self, rjcode: Any, title: Any) -> bool:
        text = str(title or "").strip()
        if not text:
            return False
        normalized_rj = self.normalize_rjcode(rjcode)
        return not (normalized_rj and text.upper() == normalized_rj)

    # 历史上这里曾留过 ``_title_looks_like_bonus_work``：标题级特典兜底正则。
    # 已删——明确禁止用标题判定特典：很多正常作品标题里就含"特典"二字（"早期特典つき"
    # 这种"附带特典的作品本体"反而最容易误命中）。特典识别只走
    # ``DLsiteApiService._product_info_indicates_bonus_work`` 的 4 字段 AND 规则
    # （!is_sale && is_free && is_oly && wishlist_count==0），结构化字段是唯一可信源。

    def _extract_text_values(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("[") or stripped.startswith("{"):
                try:
                    return self._extract_text_values(json.loads(stripped))
                except Exception:
                    return [stripped]
            return [stripped]
        if isinstance(value, dict):
            texts: List[str] = []
            for key in ("name", "label", "title", "value", "text", "work_category", "category", "type"):
                texts.extend(self._extract_text_values(value.get(key)))
            return texts
        if isinstance(value, (list, tuple, set)):
            texts: List[str] = []
            for item in value:
                texts.extend(self._extract_text_values(item))
            return texts
        return [str(value)]

    def _is_non_audio_package_text(self, text: str) -> bool:
        haystack = str(text or "").strip().lower()
        if not haystack:
            return False
        markers = [
            "cg・插画", "cg・イラスト", "cg イラスト", "cg集",
            "jpeg", "jpg", "png", "pdf",
            "漫画", "マンガ", "コミック", "comic",
            "ゲーム", "game", "アドベンチャー", "ノベル", "novel",
            "3dcg", "3d作品",
            # ★ 技术书 / 小说 / 解説書 这些纯文字作品（哪怕主题是"如何制作 ASMR"）
            # 也常会带 "ASMR" / "人头麦" 等 Kikoeru tag，导致 audio 检查误判为音声作品。
            # 这里补上中日双语的"书/小说"关键词，让非音声判定优先级把它们截掉。
            # 案例：RJ01268187《音声作品のつくりかた》(防鯖潤滑剤) 是 JPEG+PDF 技术书，
            # 但分类含 ASMR/双声道立体声/人头麦，社团补全曾把它当作品索引进来。
            "小说", "小説", "技术书", "技術書", "解説書", "解説本",
            "教本", "ハウツー", "ガイドブック",
        ]
        if any(marker in haystack for marker in markers):
            return True
        # RPG/ADV 只认独立词。对魔忍 RPGX 这类品牌词经常出现在 ASMR 标题里，
        # 如果按 substring 命中会把真实音声整批误杀。
        return bool(re.search(r"(?<![0-9a-z])(?:rpg|adv)(?![0-9a-z])", haystack, re.IGNORECASE))

    def _is_audio_package_text(self, text: str) -> bool:
        haystack = str(text or "").strip().lower()
        if not haystack:
            return False
        markers = [
            "sou", "audio", "voice", "asmr", "音声", "ボイス", "ボイス・asmr",
            "囁き", "ささやき", "耳かき", "耳舐め", "舐耳", "バイノーラル",
            "フォーリーサウンド", "フォーリー", "foley", "wav", "ku100",
            "音声・asmr", "双声道立体声", "人头麦", "舔耳", "低语",
            "拟声音效", "拟真音效", "耳语", "耳边",
        ]
        return any(marker in haystack for marker in markers)

    def _metadata_looks_like_asmr_work(self, metadata: Optional[Dict[str, Any]]) -> bool:
        metadata = metadata or {}
        title = str(metadata.get("work_name") or metadata.get("title") or "").strip().lower()

        # 标题中的 KU100/フォーリー/バイノーラル 等是音声作品的强信号
        # 即使 tags 中没有 "ASMR" 也能正确识别
        audio_title_markers = [
            "ku100", "フォーリー", "foley", "バイノーラル", "binaural",
            "拟声音效", "拟真音效", "両耳", "耳语", "耳边", "人头麦",
        ]
        if any(marker in title for marker in audio_title_markers):
            return True

        tags = self._extract_text_values(metadata.get("tags"))
        categories: List[str] = []
        for key in ("work_type", "work_category", "category", "category_name", "genre", "genre_name", "file_type", "file_format"):
            categories.extend(self._extract_text_values(metadata.get(key)))
        haystack = " ".join([title, *tags, *categories])
        # ★ 关键顺序：先判非音声标记，再判音声标记。
        # 一本"如何制作 ASMR"的技术书 / 小说同时会带 "ASMR" / "人头麦" 这种音声 tag
        # 和 "JPEG / PDF / 技术书" 这种非音声 tag。如果先看到音声 tag 就 return True，
        # 这类纯文字作品会被错误索引进社团补全。非音声信号（jpeg/pdf/小说/技术书等）
        # 是文件形态级别的强信号，优先级必须高于主题级别的音声 tag。
        # 案例：RJ01268187《音声作品のつくりかた》(防鯖潤滑剤)
        if self._is_non_audio_package_text(haystack):
            return False
        if self._is_audio_package_text(haystack):
            return True

        # 注意：这里**故意不**用"cvs 非空 → 视为音声"做兜底。
        # 反例：RJ154958《対魔忍ユキカゼ2》是 ADV 游戏（work_type=ADV，文件格式 EXE），
        # 但 DLsite 上有完整声优配音（氷室百合 / 佐藤遼佳 / 花南）。同时其 tags
        # 都是普通 genre（コスプレ / 制服 / 凌辱…），既不含音声 marker 也不含
        # 非音声 marker。如果仅凭 cvs 非空就 return True，这种游戏会直接被
        # 社团补全索引当成音声作品收进 ``circle_works``。
        # 兜底交给上层 ``_classify_asmr_work_candidate`` 用 DLsite ``product.work_type``
        # 做权威判定（白名单只接受 "SOU"）。
        return False

    def _build_dlsite_cover_url(self, rjcode: Any, is_unreleased: bool = False, resized: bool = False) -> str:
        normalized = self.normalize_rjcode(rjcode)
        match = re.match(r"RJ(\d{6}|\d{8})$", normalized)
        if not match:
            return ""
        number = int(match.group(1))
        folder_upper = ((number // 1000) + 1) * 1000
        folder = f"RJ{folder_upper:08d}" if len(match.group(1)) == 8 else f"RJ{folder_upper:06d}"
        path_type = "announce" if is_unreleased else "work"
        if resized:
            return f"https://img.dlsite.jp/resize/images2/{path_type}/doujin/{folder}/{normalized}_img_main_240x240.jpg"
        if is_unreleased:
            return f"https://img.dlsite.jp/modpub/images2/ana/doujin/{folder}/{normalized}_ana_img_main.jpg"
        return f"https://img.dlsite.jp/modpub/images2/{path_type}/doujin/{folder}/{normalized}_img_sam.jpg"

    def _normalize_dlsite_cover_url(self, url: Any, rjcode: Any, *, is_unreleased: bool = False) -> str:
        value = str(url or "").strip()
        if value.startswith("https:https://"):
            value = value.replace("https:https://", "https://", 1)
        elif value.startswith("https:http://"):
            value = value.replace("https:http://", "http://", 1)
        elif value.startswith("http:https://"):
            value = value.replace("http:https://", "https://", 1)
        elif value.startswith("//"):
            value = f"https:{value}"
        if value.startswith("https://"):
            if is_unreleased and "/modpub/images2/work/doujin/" in value:
                return self._build_dlsite_cover_url(rjcode, is_unreleased=True, resized=True) or value
            if "/modpub/images2/" in value and "_img_main.jpg" in value:
                return value.replace("https://img.dlsite.jp/modpub/images2/", "https://img.dlsite.jp/resize/images2/").replace("_img_main.jpg", "_img_main_240x240.jpg")
            return value
        return self._build_dlsite_cover_url(rjcode, is_unreleased=is_unreleased, resized=True)

    def _normalize_dlsite_thumb_url(self, url: Any, rjcode: Any, *, is_unreleased: bool = False) -> str:
        """返回列表模式用的小方图 URL。"""

        value = self._normalize_dlsite_cover_url(url, rjcode, is_unreleased=is_unreleased)
        if value.startswith("https://img.dlsite.jp/resize/images2/") and "_img_main_240x240.jpg" in value:
            return value.replace("https://img.dlsite.jp/resize/images2/", "https://img.dlsite.jp/modpub/images2/").replace("_img_main_240x240.jpg", "_img_sam.jpg")
        if value.startswith("https://img.dlsite.jp/modpub/images2/") and "_img_main.jpg" in value:
            return value.replace("_img_main.jpg", "_img_sam.jpg")
        if value.startswith("https://img.dlsite.jp/modpub/images2/") and "_img_sam.jpg" in value:
            return value
        return self._build_dlsite_cover_url(rjcode, is_unreleased=False, resized=False) or value

    # 预售作品在 DLsite 上常把发售日写成"未定" / "未確定" / "TBD" 等，
    # 没有具体年月可以解析。这种作品同样属于"尚未发售"，应当：
    # 1) 后端给前端置 ``is_unreleased=True``，触发 WorkCard / WorkListRow 上的
    #    📅 未发售 徽章和蓝色光圈，不再"消失成普通卡片"；
    # 2) 前端按发售日排序时把它沉到末尾（发售日最迟），等 DLsite 后续公布
    #    实际日期再随刷新流程归位。
    _UNRELEASED_DATE_KEYWORDS = (
        "未定",
        "未確定",
        "未确定",
        "未発表",
        "未发表",
        "発売日未定",
        "发售日未定",
        "発売予定",
        "予定",
        "tbd",
        "tba",
        "coming soon",
    )

    def _is_future_release_date(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        lowered = text.lower()
        # 关键字优先：含有"未定" / "TBD" / "予定" 等就直接判未发售，
        # 不再去匹配年月日（DLsite 偶尔会写"2026年 予定"这种混合形态，
        # 但只要带上"予定"语义就视同预售）。
        if any(keyword.lower() in lowered for keyword in self._UNRELEASED_DATE_KEYWORDS):
            return True
        match = re.search(r"(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?", text)
        if not match:
            return False
        year = int(match.group(1))
        month = int(match.group(2))
        if match.group(3):
            day = int(match.group(3))
        elif "下旬" in text:
            # 下旬 = 21日以降、月末扱いで 28 日とする
            day = 28
        elif "中旬" in text:
            day = 20
        elif "上旬" in text:
            day = 10
        else:
            day = 1
        try:
            release = date(year, month, day)
        except ValueError:
            return False
        return release > date.today()

    def _product_looks_like_asmr_work(self, product: Optional[Dict[str, Any]]) -> Optional[bool]:
        if not isinstance(product, dict) or not product:
            return None

        # DLsite work_type 代码白名单: SOU = Sound/音声
        # 其他 code 都是非音声形态：RPG/ADV/ACN/SLN/TBL/QIZ/DGT/MUS/ICG/MOV/COM/NRE/IMG/GAM...
        # 即便这些游戏 / CG 集 / 漫画 / 视频里有声优配音（ADV / RPG 经常配 voice_by），
        # 也不能被社团补全索引当作音声作品收进 ``circle_works``。这里把 work_type
        # 当成 DLsite 给出的权威分类信号：非空且非 SOU，直接判非音声，不再走下游
        # 的 voice_by 兜底（那条兜底只在 product 数据极度残缺、所有 category 字段
        # 全空时才有意义）。
        # 案例：RJ154958《対魔忍ユキカゼ2》(Lilith) work_type=ADV、文件 EXE、CV 完整，
        # 旧实现走到下面 voice_by 兜底被错认为 ASMR，整作品被错索引进 Lilith 社团页。
        work_type = str(product.get("work_type") or "").strip().upper()
        if work_type == "SOU":
            return True
        if work_type:
            return False

        # 标题强信号
        title = str(product.get("work_name") or "").strip().lower()
        audio_title_markers = [
            "ku100", "フォーリー", "foley", "バイノーラル", "binaural",
            "拟声音效", "拟真音效", "両耳", "耳语", "耳边", "人头麦",
        ]
        if any(marker in title for marker in audio_title_markers):
            return True

        category_values: List[str] = []
        category_keys = [
            "work_type",
            "work_category",
            "work_category_code",
            "category",
            "category_name",
            "genre",
            "genre_name",
            "work_format",
            "work_type_name",
        ]
        for key in category_keys:
            value = product.get(key)
            if value is None:
                continue
            if isinstance(value, dict):
                category_values.extend(str(v or "") for v in value.values())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        category_values.extend(str(v or "") for v in item.values())
                    else:
                        category_values.append(str(item or ""))
            else:
                category_values.append(str(value or ""))

        category_text = " ".join(category_values).strip().lower()
        if self._is_non_audio_package_text(category_text):
            return False
        if self._is_audio_package_text(category_text):
            return True
        if category_text:
            return False

        creators = product.get("creaters") if isinstance(product.get("creaters"), dict) else {}
        voice_by = creators.get("voice_by") if isinstance(creators, dict) else []
        if voice_by:
            # 有明确声优配音信息 → 大概率是音声作品
            # (游戏/漫画等非音声作品已被 category 检查拦截)
            return True

        metadata_like = {
            "work_name": product.get("work_name") or "",
            "tags": [
                str((genre or {}).get("name") or "")
                for genre in list(product.get("genres") or [])
                if isinstance(genre, dict)
            ],
            "cvs": [],
        }
        return True if self._metadata_looks_like_asmr_work(metadata_like) else None

    async def _classify_asmr_work_candidate(self, rjcode: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[bool]:
        normalized = self.normalize_rjcode(rjcode)
        if not normalized:
            return False
        # metadata 只能做快速强信号；DLsite product.work_type 一旦能拿到，必须
        # 覆盖 metadata 里的题材弱信号。否则 ADV/RPG 游戏常见的「催眠 / 治愈 /
        # 调教」标签会被误当成音声分类，把游戏塞进社团补全。
        if metadata:
            meta_result = self._metadata_looks_like_asmr_work(metadata)
            explicit_audio_type = self._is_audio_package_text(" ".join([
                str(metadata.get("work_name") or metadata.get("title") or ""),
                *self._extract_text_values(metadata.get("tags")),
                *[
                    value
                    for key in ("work_type", "work_category", "category", "category_name", "genre", "genre_name", "file_type", "file_format")
                    for value in self._extract_text_values(metadata.get(key))
                ],
            ]))
            if meta_result is True and explicit_audio_type:
                return True
            # metadata 明确不是 ASMR 时也直接返回，省去 get_product_info
            haystack = " ".join([
                str(metadata.get("work_name") or metadata.get("title") or "").strip().lower(),
                *self._extract_text_values(metadata.get("tags")),
                *self._extract_text_values(metadata.get("work_category")),
                *self._extract_text_values(metadata.get("category")),
                *self._extract_text_values(metadata.get("file_format")),
            ])
            if self._is_non_audio_package_text(haystack):
                return False
        try:
            product_info = await self.dlsite_service.get_product_info(normalized)
        except Exception:
            product_info = None
        product_result = self._product_looks_like_asmr_work((product_info or {}).get("product") if isinstance(product_info, dict) else None)
        if product_result is not None:
            return product_result
        if metadata and self._metadata_looks_like_asmr_work(metadata):
            return True
        return None

    async def _is_asmr_work_candidate(self, rjcode: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        return (await self._classify_asmr_work_candidate(rjcode, metadata)) is True

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

    def _find_circle_catalog_for_view(self, db, circle_id_or_query: str) -> CircleCatalog:
        query = str(circle_id_or_query or "").strip()
        if not query:
            raise ValueError("缺少社团标识")
        catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == query).first()
        if catalog is None:
            normalized = self.normalize_circle_name(query)
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_name_normalized == normalized).first()
        if catalog is None:
            raise ValueError("社团索引不存在")
        return catalog

    def _completion_status_filters(self, value: Any) -> List[str]:
        allowed = {"repairable", "downloadable", "missing", "no_source", "has_early_bonus", "no_early_bonus"}
        raw_values = value
        if isinstance(raw_values, str):
            raw_values = re.split(r"[,，\s]+", raw_values)
        if not isinstance(raw_values, list):
            raw_values = []
        out: List[str] = []
        for item in raw_values:
            key = str(item or "").strip()
            if key in allowed and key not in out:
                out.append(key)
        return out

    def _completion_original_release_date(self, canonical_rjcode: Any, metadata_map_all: Dict[str, Dict[str, Any]]) -> str:
        metadata = metadata_map_all.get(self.normalize_rjcode(canonical_rjcode)) or {}
        return str((metadata or {}).get("release_date") or "").strip()

    def _completion_full_release_date(self, value: Any) -> str:
        normalized = str(self.dlsite_service._normalize_date_text(value) or "").strip()
        return normalized if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", normalized) else ""

    def _completion_persist_precise_release_date(self, rjcode: Any, release_date: str) -> None:
        normalized_rj = self.normalize_rjcode(rjcode)
        normalized_date = self._completion_full_release_date(release_date)
        if not normalized_rj or not normalized_date:
            return
        cached = self._metadata_cache.get(normalized_rj)
        if isinstance(cached, dict) and str(cached.get("release_date") or "").strip() == normalized_date:
            return
        db = SessionLocal()
        try:
            row = db.query(WorkMetadata).filter(WorkMetadata.rjcode == normalized_rj).first()
            if row is None:
                row = WorkMetadata(rjcode=normalized_rj)
                db.add(row)
            if str(row.release_date or "").strip() == normalized_date:
                payload = row.to_dict()
                self._metadata_cache[normalized_rj] = payload
                return
            row.release_date = normalized_date
            row.cached_at = datetime.now()
            db.commit()
            self._metadata_cache[normalized_rj] = row.to_dict()
        except Exception:
            db.rollback()
            logger.debug("[社团补全] 写回作品精确发售日失败 rj=%s date=%s", normalized_rj, normalized_date, exc_info=True)
        finally:
            db.close()

    async def _completion_resolve_bonus_probe_release_date(
        self,
        item: Dict[str, Any],
        candidate_rjcodes: List[str],
    ) -> str:
        original_release_date = item.get("original_release_date")
        normalized_original_date = self._completion_full_release_date(original_release_date)
        if normalized_original_date:
            return normalized_original_date

        fallback_raw_values = [
            item.get("release_date"),
            item.get("date"),
            item.get("release_at"),
        ]
        probe_rjcodes: List[str] = []
        for value in [item.get("canonical_rjcode"), *(candidate_rjcodes or [])]:
            normalized = self.normalize_rjcode(value)
            if normalized and normalized not in probe_rjcodes:
                probe_rjcodes.append(normalized)

        for rjcode in probe_rjcodes:
            try:
                product_info = await self.dlsite_service.get_product_info(rjcode)
            except Exception:
                logger.debug("[社团补全] 补查作品精确发售日失败 rj=%s", rjcode, exc_info=True)
                continue
            product = (product_info or {}).get("product") if isinstance(product_info, dict) else None
            if not isinstance(product, dict):
                continue
            for key in ("regist_date", "release_date", "sales_date", "disp_start_date"):
                normalized = self._completion_full_release_date(product.get(key))
                if normalized:
                    self._completion_persist_precise_release_date(rjcode, normalized)
                    return normalized

        for value in fallback_raw_values:
            normalized = self._completion_full_release_date(value)
            if normalized:
                return normalized

        raw_values = [original_release_date, *fallback_raw_values]
        return next((str(value or "").strip() for value in raw_values if str(value or "").strip()), "")

    def _completion_release_timestamp(self, item: Dict[str, Any]) -> int:
        raw = str(
            item.get("original_release_date")
            or item.get("release_date")
            or item.get("date")
            or item.get("release_at")
            or ""
        ).strip()
        placeholder = int(datetime(2099, 1, 1).timestamp())
        if not raw:
            return placeholder if item.get("is_unreleased") else 0

        full = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", raw)
        if full:
            try:
                return int(datetime(int(full.group(1)), int(full.group(2)), int(full.group(3))).timestamp())
            except Exception:
                pass

        phase = re.search(r"(\d{4})\D+(\d{1,2})\D*(上旬|中旬|下旬)", raw)
        if phase:
            try:
                day = 9 if phase.group(3) == "上旬" else (19 if phase.group(3) == "中旬" else 28)
                return int(datetime(int(phase.group(1)), int(phase.group(2)), day).timestamp())
            except Exception:
                pass

        month = re.search(r"(\d{4})\D+(\d{1,2})", raw)
        if month:
            try:
                return int(datetime(int(month.group(1)), int(month.group(2)), 1).timestamp())
            except Exception:
                pass

        return placeholder if item.get("is_unreleased") else 0

    def _completion_item_matches_status_filter(self, item: Dict[str, Any], key: str) -> bool:
        if key == "repairable":
            return bool(item.get("subtitle_repairable"))
        if key == "downloadable":
            return bool(item.get("has_asmr_one")) and not bool(item.get("is_unreleased"))
        if key == "missing":
            return not bool(item.get("owned"))
        if key == "no_source":
            return not bool(item.get("owned")) and not bool(item.get("has_asmr_one"))
        if key == "has_early_bonus":
            return str(item.get("early_bonus_status") or "").strip() == "has_bonus"
        if key == "no_early_bonus":
            return str(item.get("early_bonus_status") or "").strip() == "no_bonus"
        return True

    def _completion_apply_status_filters(self, rows: List[Dict[str, Any]], status_filters: List[str]) -> List[Dict[str, Any]]:
        if not status_filters:
            return rows
        return [
            item for item in rows
            if any(self._completion_item_matches_status_filter(item, key) for key in status_filters)
        ]

    def _completion_variant_group_key(self, item: Dict[str, Any], owned: bool = False) -> str:
        payload = item.get("owned_variant" if owned else "preferred_variant")
        if not isinstance(payload, dict):
            payload = {}
        return str(payload.get("group_key") or "original").strip() or "original"

    def _completion_search_match(self, item: Dict[str, Any], keyword: str) -> bool:
        query = str(keyword or "").strip().lower()
        if not query:
            return True
        haystack = " ".join([
            str(item.get("canonical_rjcode") or ""),
            str(item.get("display_rjcode") or ""),
            str(item.get("title") or ""),
            *[str(code or "") for code in list(item.get("linked_rjcodes") or [])],
        ]).lower()
        return query in haystack

    def _completion_item_matches_rjcode(self, item: Dict[str, Any], rjcode: str) -> bool:
        target = self.normalize_rjcode(rjcode)
        if not target:
            return False
        candidates = [
            item.get("canonical_rjcode"),
            item.get("display_rjcode"),
            item.get("server_match_primary_rjcode"),
            item.get("asmr_available_rjcode"),
        ]
        for payload_key in ["download_plan", "owned_variant", "preferred_variant"]:
            payload = item.get(payload_key)
            if isinstance(payload, dict):
                candidates.append(payload.get("rjcode"))
        candidates.extend(item.get("linked_rjcodes") or [])
        return any(self.normalize_rjcode(candidate) == target for candidate in candidates)

    def _completion_item_codes(self, item: Dict[str, Any]) -> List[str]:
        codes: List[str] = []
        candidates = [
            item.get("canonical_rjcode"),
            item.get("display_rjcode"),
            item.get("asmr_available_rjcode"),
            item.get("server_match_primary_rjcode"),
        ]
        for payload_key in ["download_plan", "owned_variant", "preferred_variant"]:
            payload = item.get(payload_key)
            if isinstance(payload, dict):
                candidates.append(payload.get("rjcode"))
        candidates.extend(item.get("linked_rjcodes") or [])
        for candidate in candidates:
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized not in codes:
                codes.append(normalized)
        return codes

    def _completion_bonus_own_codes(self, item: Dict[str, Any]) -> Set[str]:
        candidates = [
            item.get("display_rjcode"),
            item.get("rjcode"),
        ]
        return {
            normalized
            for normalized in (self.normalize_rjcode(candidate) for candidate in candidates)
            if normalized
        }

    def _completion_bonus_display_rjcode(
        self,
        canonical_rjcode: Any,
        display_rjcode: Any,
        metadata_map: Dict[str, Dict[str, Any]],
    ) -> str:
        """特典行必须按自身 RJ 展示，不能沿用原作的翻译版。"""
        canonical = self.normalize_rjcode(canonical_rjcode)
        display = self.normalize_rjcode(display_rjcode)
        for candidate in [canonical, display]:
            if candidate and bool((metadata_map.get(candidate) or {}).get("is_bonus_work")):
                return candidate
        return canonical or display

    def _completion_bonus_parent_code(self, item: Dict[str, Any], available_codes: Set[str]) -> str:
        if not bool(item.get("is_bonus_work")):
            return ""
        own_codes = self._completion_bonus_own_codes(item)
        explicit_parent = self.normalize_rjcode(item.get("bonus_parent_rjcode"))
        if explicit_parent and explicit_parent not in own_codes and explicit_parent in available_codes:
            return explicit_parent
        canonical = self.normalize_rjcode(item.get("canonical_rjcode"))
        if canonical and canonical not in own_codes and canonical in available_codes:
            return canonical
        for candidate in item.get("linked_rjcodes") or []:
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized not in own_codes and normalized in available_codes:
                return normalized
        return ""

    def _completion_group_bonus_items(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        code_to_item: Dict[str, Dict[str, Any]] = {}
        for item in rows:
            for code in self._completion_item_codes(item):
                existing = code_to_item.get(code)
                if existing is None or (bool(existing.get("is_bonus_work")) and not bool(item.get("is_bonus_work"))):
                    code_to_item[code] = item

        available_codes = set(code_to_item.keys())
        hidden_ids: Set[int] = set()
        for item in rows:
            parent_code = self._completion_bonus_parent_code(item, available_codes)
            parent_item = code_to_item.get(parent_code) if parent_code else None
            if not parent_item or parent_item is item or bool(parent_item.get("is_bonus_work")):
                continue
            bonuses = parent_item.setdefault("bonus_works", [])
            if item not in bonuses:
                bonuses.append(item)
            hidden_ids.add(id(item))
        return [item for item in rows if id(item) not in hidden_ids]

    def _completion_group_members(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        members = [item]
        for bonus in item.get("bonus_works") or []:
            if isinstance(bonus, dict):
                members.append(bonus)
        return members

    def _completion_apply_card_dim_state(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in rows:
            members = self._completion_group_members(item)
            group_has_owned = any(bool(member.get("owned")) for member in members)
            group_all_missing = not group_has_owned
            for member in members:
                member["completion_card_dimmed"] = bool(group_has_owned and not member.get("owned"))
                member["completion_card_mixed_group"] = bool(not group_all_missing)
        return rows

    def _filter_completion_items_for_card_tab(
        self,
        items: List[Dict[str, Any]],
        *,
        tab: str,
        include_dl_only: bool,
        status_filters: Optional[List[str]] = None,
        owned_filter: str = "all",
        search: str = "",
    ) -> List[Dict[str, Any]]:
        tab_key = str(tab or "missing").strip().lower()
        source_visible_items = [
            dict(item)
            for item in items
            if include_dl_only or item.get("owned") or item.get("has_asmr_one")
        ]
        rows = self._completion_group_bonus_items(source_visible_items)

        if tab_key == "owned":
            rows = [
                item for item in rows
                if any(bool(member.get("owned")) for member in self._completion_group_members(item))
            ]
            owned_filter = str(owned_filter or "all").strip().lower()
            if owned_filter != "all":
                def _owned_filter_match(member: Dict[str, Any]) -> bool:
                    if not bool(member.get("owned")):
                        return False
                    group_key = self._completion_variant_group_key(member, owned=True)
                    has_subtitle = group_key == "original" and bool(member.get("subtitle_present"))
                    if owned_filter == "original":
                        return group_key == "original" and not has_subtitle
                    if owned_filter == "simplified":
                        return group_key == "simplified"
                    if owned_filter == "traditional":
                        return group_key == "traditional"
                    if owned_filter == "subtitle":
                        return has_subtitle
                    if owned_filter == "bonus":
                        return bool(member.get("is_bonus_work"))
                    return True
                rows = [
                    item for item in rows
                    if any(_owned_filter_match(member) for member in self._completion_group_members(item))
                ]
        else:
            rows = [
                item for item in rows
                if not any(bool(member.get("owned")) for member in self._completion_group_members(item))
                and self._is_preferred_missing_completion_item(item)
            ]

        if status_filters:
            rows = [
                item for item in rows
                if any(
                    self._completion_item_matches_status_filter(member, key)
                    for member in self._completion_group_members(item)
                    for key in status_filters
                )
            ]
        if search:
            rows = [
                item for item in rows
                if any(self._completion_search_match(member, search) for member in self._completion_group_members(item))
            ]
        return self._completion_apply_card_dim_state(rows)

    def _completion_rj_number(self, rjcode: Any) -> Optional[int]:
        normalized = self.normalize_rjcode(rjcode)
        if not normalized:
            return None
        match = re.search(r"RJ0*(\d+)", normalized)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _completion_normalized_release_date(self, value: Any) -> str:
        try:
            return str(self.dlsite_service._normalize_date_text(value) or "").strip()
        except Exception:
            return str(value or "").strip()

    def _completion_attach_bonus_parent_codes(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        parents_by_key: Dict[Tuple[str, str], List[Tuple[int, str, Dict[str, Any]]]] = defaultdict(list)
        for item in items:
            if bool(item.get("is_bonus_work")):
                continue
            parent_code = self.normalize_rjcode(item.get("canonical_rjcode") or item.get("display_rjcode"))
            if not parent_code:
                continue
            maker_id = str(item.get("maker_id") or "").strip().upper()
            release_date = self._completion_normalized_release_date(
                item.get("original_release_date") or item.get("release_date")
            )
            if not maker_id or not release_date:
                continue
            parents_by_key[(maker_id, release_date)].append((
                self._completion_rj_number(parent_code) or 10**12,
                parent_code,
                item,
            ))

        if not parents_by_key:
            return items

        for candidates in parents_by_key.values():
            candidates.sort(key=lambda row: (row[0], row[1]))

        for item in items:
            if not bool(item.get("is_bonus_work")) or item.get("bonus_parent_rjcode"):
                continue
            maker_id = str(item.get("maker_id") or "").strip().upper()
            release_date = self._completion_normalized_release_date(item.get("release_date"))
            if not maker_id or not release_date:
                continue
            own_codes = self._completion_bonus_own_codes(item)
            bonus_number = self._completion_rj_number(item.get("display_rjcode") or item.get("canonical_rjcode"))
            candidates: List[Tuple[int, str, Dict[str, Any]]] = []
            for parent_number, parent_code, parent_item in parents_by_key.get((maker_id, release_date), []):
                if parent_code in own_codes:
                    continue
                distance = abs(parent_number - bonus_number) if bonus_number is not None and parent_number < 10**12 else 10**12
                candidates.append((distance, parent_code, parent_item))
            if candidates:
                candidates.sort(key=lambda row: (row[0], row[1]))
                item["bonus_parent_rjcode"] = candidates[0][1]
        return items

    def _completion_apply_explicit_bonus_parent_codes(
        self,
        items: List[Dict[str, Any]],
        link_rows: Iterable[WorkCanonicalLink],
    ) -> List[Dict[str, Any]]:
        explicit_candidates: Dict[str, List[Tuple[datetime, str]]] = defaultdict(list)
        fallback_time = datetime.max
        for row in link_rows or []:
            if str(getattr(row, "link_type", "") or "").strip().lower() != "bonus":
                continue
            parent = self.normalize_rjcode(getattr(row, "canonical_rjcode", ""))
            bonus = self.normalize_rjcode(getattr(row, "linked_rjcode", ""))
            if not parent or not bonus or parent == bonus:
                continue
            created_at = getattr(row, "created_at", None)
            explicit_candidates[bonus].append((created_at if isinstance(created_at, datetime) else fallback_time, parent))

        explicit_parents: Dict[str, str] = {}
        for bonus, candidates in explicit_candidates.items():
            candidates.sort(key=lambda value: (value[0], value[1]))
            explicit_parents[bonus] = candidates[0][1]
            distinct_parents = {parent for _, parent in candidates}
            if len(distinct_parents) > 1:
                logger.warning(
                    "[社团补全] 特典存在多个显式父作品，按最早关系展示 bonus=%s parents=%s selected=%s",
                    bonus,
                    sorted(distinct_parents),
                    explicit_parents[bonus],
                )

        for item in items:
            if not bool(item.get("is_bonus_work")):
                continue
            for candidate in [item.get("display_rjcode"), item.get("canonical_rjcode"), item.get("rjcode")]:
                bonus = self.normalize_rjcode(candidate)
                parent = explicit_parents.get(bonus)
                if parent:
                    item["bonus_parent_rjcode"] = parent
                    break
        return items

    def _completion_apply_early_bonus_status(
        self,
        items: List[Dict[str, Any]],
        original_state_map: Dict[str, str],
    ) -> None:
        bonus_parent_codes: Set[str] = set()
        for item in items:
            if not bool(item.get("is_bonus_work")):
                continue
            own_codes = self._completion_bonus_own_codes(item)
            explicit_parent = self.normalize_rjcode(item.get("bonus_parent_rjcode"))
            if explicit_parent and explicit_parent not in own_codes:
                bonus_parent_codes.add(explicit_parent)
            for candidate in item.get("linked_rjcodes") or []:
                normalized = self.normalize_rjcode(candidate)
                if normalized and normalized not in own_codes:
                    bonus_parent_codes.add(normalized)

        for item in items:
            item["early_bonus_status"] = ""
            if bool(item.get("is_bonus_work")):
                continue
            canonical = self.normalize_rjcode(item.get("canonical_rjcode"))
            state = str(original_state_map.get(canonical) or "").strip()
            if state == "has_bonus" or bool(item.get("has_bonus")) or canonical in bonus_parent_codes:
                item["early_bonus_status"] = "has_bonus"
            elif state == "no_bonus":
                item["early_bonus_status"] = "no_bonus"

    def _build_completion_item(
        self,
        *,
        catalog: CircleCatalog,
        row: CircleWork,
        owned_row: Optional[LibraryOwnedWork],
        link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]],
        metadata_map_all: Dict[str, Dict[str, Any]],
        local_download_session_map: Optional[Dict[str, Dict[str, Any]]] = None,
        image_cache_service: Optional[Any] = None,
        include_source_compare: bool = False,
        include_heavy_fields: bool = False,
        now_local_for_view: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        local_owned = owned_row is not None
        stored_display_rjcode = self.normalize_rjcode(row.display_rjcode) or self.normalize_rjcode(row.canonical_rjcode)
        linked_rjcodes = list(row.linked_rjcodes or [stored_display_rjcode or row.canonical_rjcode])
        canonical_info = {
            "canonical_rjcode": row.canonical_rjcode,
            "linked_rjcodes": linked_rjcodes,
            "link_map": link_map_by_canonical.get(row.canonical_rjcode) or {},
        }
        metadata_map = {
            code: metadata_map_all[code]
            for code in [
                *canonical_info["linked_rjcodes"],
                row.canonical_rjcode,
                stored_display_rjcode,
            ]
            if code in metadata_map_all
        }
        is_bonus_work = bool(getattr(row, "is_bonus_work", False))
        if is_bonus_work:
            stored_display_rjcode = self._completion_bonus_display_rjcode(
                row.canonical_rjcode,
                stored_display_rjcode,
                metadata_map,
            )
            if stored_display_rjcode and stored_display_rjcode not in linked_rjcodes:
                linked_rjcodes.append(stored_display_rjcode)
        title = str(row.title or "").strip()
        if not title:
            title = str((metadata_map.get(stored_display_rjcode) or {}).get("work_name") or "").strip()
        release_date = str((metadata_map.get(stored_display_rjcode) or {}).get("release_date") or "").strip()
        if not release_date:
            for metadata in metadata_map.values():
                release_date = str((metadata or {}).get("release_date") or "").strip()
                if release_date:
                    break
        original_release_date = self._completion_original_release_date(row.canonical_rjcode, metadata_map_all)

        view_canonical_info = {
            **canonical_info,
            "linked_rjcodes": linked_rjcodes,
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
        local_owned_rjcodes = self._actual_owned_rjcodes(owned_row)
        normalized_local_owned_rjcodes: List[str] = []
        for candidate in local_owned_rjcodes:
            normalized_candidate = self.normalize_rjcode(candidate)
            if normalized_candidate and normalized_candidate not in normalized_local_owned_rjcodes:
                normalized_local_owned_rjcodes.append(normalized_candidate)
        source_compare_seed = {
            "canonical_rjcode": row.canonical_rjcode,
            "display_rjcode": stored_display_rjcode,
            "asmr_available_rjcode": row.asmr_available_rjcode,
            "kikoeru_found_rjcodes": normalized_local_owned_rjcodes if local_owned else [],
            "kikoeru_subtitle_rjcodes": normalized_local_owned_rjcodes if bool(getattr(owned_row, "has_local_subtitles", False)) else [],
            "preferred_variant": {
                "rjcode": preferred_variant.get("rjcode"),
                "lang": preferred_variant.get("lang"),
                "link_type": preferred_variant.get("link_type"),
                "label": self._variant_label(preferred_variant.get("link_type"), preferred_variant.get("lang")),
                "group_key": preferred_group["key"],
                "group_label": preferred_group["label"],
                "group_short_label": preferred_group["short_label"],
            },
        }
        source_compare = self._build_source_compare(source_compare_seed, view_canonical_info, metadata_map)
        kikoeru_compare = source_compare.get("kikoeru") if isinstance(source_compare, dict) else {}
        asmr_compare = source_compare.get("asmr_one") if isinstance(source_compare, dict) else {}
        server_match_rjcodes = list((kikoeru_compare or {}).get("matched_rjcodes") or (kikoeru_compare or {}).get("all_rjcodes") or [])
        server_match_primary_rjcode = str(
            (kikoeru_compare or {}).get("matched_rjcode")
            or (kikoeru_compare or {}).get("primary_rjcode")
            or (server_match_rjcodes[0] if server_match_rjcodes else "")
        ).strip()
        local_subtitle_present = bool(getattr(owned_row, "has_local_subtitles", False)) if owned_row else False
        owned_primary_rjcode = self._pick_owned_primary_rjcode(
            view_canonical_info,
            server_match_primary_rjcode=server_match_primary_rjcode,
            local_owned_rjcodes=local_owned_rjcodes,
            local_subtitle_present=local_subtitle_present,
            subtitle_dir=str(getattr(owned_row, "subtitle_dir", "") or "") if owned_row else "",
            primary_folder_path=str(getattr(owned_row, "primary_folder_path", "") or "") if owned_row else "",
        )
        owned_variant = self._build_variant_payload_for_rjcode(
            view_canonical_info,
            owned_primary_rjcode,
            metadata_map,
        ) if owned_primary_rjcode else {
            "rjcode": "",
            "lang": "",
            "link_type": "",
            "group_key": "original",
            "group_label": "原作优先",
            "group_short_label": "原作",
        }
        is_unreleased = self._is_future_release_date(release_date)
        now_local = now_local_for_view or get_local_now()
        row_tags = row.source_tags
        row_has_email_watcher = isinstance(row_tags, list) and "email_watcher" in row_tags
        row_anchor = row.email_watcher_first_seen_at or row.created_at
        is_new = False
        if row_has_email_watcher and row_anchor and hasattr(row_anchor, "timestamp"):
            age = now_local.timestamp() - row_anchor.timestamp()
            is_new = 0 <= age <= 48 * 60 * 60
        local_download = (local_download_session_map or {}).get(self.normalize_rjcode(row.canonical_rjcode)) or {}
        cover_source_url = row.image_url
        if is_bonus_work:
            # 历史索引会把原作封面残留在特典行；没有特典 cover_url 时由自身 RJ
            # 推导 CDN 地址，不能继续沿用原作图。
            cover_source_url = str((metadata_map.get(stored_display_rjcode) or {}).get("cover_url") or "")
        normalized_remote_cover = self._normalize_dlsite_cover_url(
            cover_source_url,
            stored_display_rjcode or row.canonical_rjcode,
            is_unreleased=is_unreleased,
        )
        local_cover_url = ""
        local_thumb_url = ""
        if image_cache_service is not None:
            cover_cache_rjcode = image_cache_service.cache_rjcode_for_url(
                normalized_remote_cover,
                stored_display_rjcode or row.canonical_rjcode,
            )
            if cover_cache_rjcode and cover_cache_rjcode != stored_display_rjcode:
                # 兼容旧版本：它把翻译展示 RJ 当缓存文件名，当前读路径则按图片
                # URL 的真实 RJ 取文件。只复制本地旧文件，不在浏览路径触网。
                image_cache_service.restore_from_legacy_alias(
                    cover_cache_rjcode,
                    [stored_display_rjcode],
                )
                image_cache_service.restore_from_legacy_alias(
                    cover_cache_rjcode,
                    [stored_display_rjcode],
                    variant="list",
                )
            local_cover_url = image_cache_service.get_local_url(
                cover_cache_rjcode,
                allow_missing=True,
            )
            local_thumb_url = image_cache_service.get_local_url(
                cover_cache_rjcode,
                variant="list",
                allow_missing=True,
            )
        cvs = list((metadata_map.get(stored_display_rjcode) or {}).get("cvs") or [])
        if not cvs:
            for metadata in metadata_map.values():
                cvs = list((metadata or {}).get("cvs") or [])
                if cvs:
                    break
        if is_bonus_work:
            cvs = []
        item = {
            "id": row.id,
            "circle_id": row.circle_id,
            "circle_name": catalog.circle_name,
            "canonical_rjcode": row.canonical_rjcode,
            "display_rjcode": stored_display_rjcode,
            "title": title or str(row.title or ""),
            "maker_id": row.maker_id,
            "maker_name": row.maker_name,
            "source_mask": row.source_mask or "",
            "linked_rjcodes": linked_rjcodes,
            "has_dlsite": True,
            "has_asmr_one": bool(row.has_asmr_one),
            "asmr_available_rjcode": row.asmr_available_rjcode,
            "image_url": local_cover_url or normalized_remote_cover,
            "remote_image_url": normalized_remote_cover,
            "thumb_image_url": local_thumb_url or self._normalize_dlsite_thumb_url(
                normalized_remote_cover,
                stored_display_rjcode or row.canonical_rjcode,
                is_unreleased=is_unreleased,
            ),
            "price_text": str(getattr(row, "price_text", "") or "").strip(),
            "release_date": release_date,
            "original_release_date": original_release_date,
            "is_unreleased": is_unreleased,
            "is_new_work": is_new,
            "is_bonus_work": is_bonus_work,
            "has_bonus": bool(getattr(row, "has_bonus", False)),
            "cvs": cvs,
            "local_owned": local_owned,
            "local_folder_size": int(getattr(owned_row, "folder_size", 0) or 0) if owned_row else 0,
            "local_file_count": int(getattr(owned_row, "file_count", 0) or 0) if owned_row else 0,
            "local_subtitle_present": local_subtitle_present,
            "subtitle_file_count": int(getattr(owned_row, "subtitle_file_count", 0) or 0) if owned_row else 0,
            "subtitle_dir": str(getattr(owned_row, "subtitle_dir", "") or "") if owned_row else "",
            "owned_rjcodes": local_owned_rjcodes,
            "primary_folder_path": owned_row.primary_folder_path if owned_row else "",
            "local_download_ready": bool(local_download),
            "local_download_session_id": str(local_download.get("session_id") or "").strip(),
            "local_download_root": str(local_download.get("download_root") or "").strip(),
            "local_downloaded_count": int(local_download.get("downloaded_count") or 0),
            "preferred_variant": source_compare_seed["preferred_variant"],
            "has_kikoeru": bool(local_owned),
            "kikoeru_found_rjcodes": normalized_local_owned_rjcodes if local_owned else [],
            "kikoeru_subtitle_rjcodes": normalized_local_owned_rjcodes if local_subtitle_present else [],
            "owned": bool(local_owned),
            "completion_owned": bool(local_owned),
            "server_owned": bool(local_owned),
            "server_match_rjcodes": server_match_rjcodes,
            "server_match_primary_rjcode": server_match_primary_rjcode,
            "owned_variant": owned_variant,
            "subtitle_present": local_subtitle_present,
            "subtitle_repairable": bool(
                local_owned
                and owned_variant.get("group_key") == "original"
                and not local_subtitle_present
                and str((asmr_compare or {}).get("primary_badge") or "").strip() in {"简中", "繁中"}
            ),
            "status_tags": [
                *(["库存已收录"] if local_owned else []),
                *(["本地已下载"] if local_download else []),
                *(["已收录"] if local_owned else ["未收录"]),
                *(["可下载"] if row.has_asmr_one else ["暂不可下载"]),
            ],
            "download_plan": {"rjcode": row.asmr_available_rjcode or row.display_rjcode} if row.has_asmr_one else None,
            "__release_timestamp": 0,
        }
        item["__release_timestamp"] = self._completion_release_timestamp(item)
        if include_source_compare:
            item["source_compare"] = source_compare
        if include_heavy_fields:
            item["owned_paths"] = list((getattr(owned_row, "owned_paths", None) or []) if owned_row else [])
        return item

    def _build_completion_compare_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        source_compare = item.get("source_compare") if isinstance(item.get("source_compare"), dict) else {}
        kikoeru = source_compare.get("kikoeru") if isinstance(source_compare.get("kikoeru"), dict) else {}
        dlsite = source_compare.get("dlsite") if isinstance(source_compare.get("dlsite"), dict) else {}
        asmr_one = source_compare.get("asmr_one") if isinstance(source_compare.get("asmr_one"), dict) else {}
        status_key = "owned" if item.get("server_owned") else ("downloadable" if item.get("has_asmr_one") else "dl_only")
        return {
            "canonical_rjcode": item.get("canonical_rjcode"),
            "workRjcode": str(source_compare.get("work_rjcode") or item.get("canonical_rjcode") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "preferredVariantLabel": str((item.get("preferred_variant") or {}).get("group_short_label") or (item.get("preferred_variant") or {}).get("label") or "").strip(),
            "statusLabel": "库存已收录" if item.get("server_owned") else ("可下载" if item.get("has_asmr_one") else "暂无来源"),
            "statusKey": status_key,
            "__releaseTimestamp": int(item.get("__release_timestamp") or 0),
            "__releaseDate": str(item.get("release_date") or "").strip(),
            "sourceCompare": {
                "kikoeru": {
                    "primary_rjcode": str(kikoeru.get("primary_rjcode") or "").strip(),
                    "primaryBadge": str(kikoeru.get("primary_badge") or "").strip(),
                    "variantBadges": list(kikoeru.get("variant_badges") or []),
                    "all_rjcodes": list(kikoeru.get("all_rjcodes") or []),
                    "tags": list(kikoeru.get("tags") or []),
                },
                "dlsite": {
                    "all_rjcodes": list(dlsite.get("all_rjcodes") or []),
                },
                "asmr_one": {
                    "primary_rjcode": str(asmr_one.get("primary_rjcode") or "").strip(),
                    "primaryBadge": str(asmr_one.get("primary_badge") or "").strip(),
                    "all_rjcodes": list(asmr_one.get("all_rjcodes") or []),
                },
            },
        }

    def _strip_completion_internal_fields(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(item)
        payload.pop("__release_timestamp", None)
        payload.pop("source_compare", None)
        if isinstance(payload.get("bonus_works"), list):
            payload["bonus_works"] = [
                self._strip_completion_internal_fields(bonus)
                for bonus in payload["bonus_works"]
                if isinstance(bonus, dict)
            ]
        return payload

    def _build_completion_view_state(self, circle_id_or_query: str) -> Dict[str, Any]:
        state_key = str(circle_id_or_query or "").strip()
        if not state_key:
            raise ValueError("缺少社团标识")
        cache_key = self._completion_state_cache_key(state_key, self._completion_version_tag(state_key))
        cached_state = self._completion_state_cache.get(cache_key)
        if cached_state is not None:
            return deepcopy(cached_state)
        state = self._build_completion_view_state_uncached(state_key)
        self._completion_store_state_cache(state_key, state)
        return deepcopy(state)

    def _build_completion_view_state_uncached(self, circle_id_or_query: str) -> Dict[str, Any]:
        state_key = str(circle_id_or_query or "").strip()
        db = SessionLocal()
        try:
            catalog = self._find_circle_catalog_for_view(db, circle_id_or_query)
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
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    WorkCanonicalLink.canonical_rjcode.in_(work_canonical_rjcodes),
                )
                .all()
                if works else []
            )
            early_bonus_state_map: Dict[str, str] = {}
            if work_canonical_rjcodes:
                state_rows = (
                    db.query(DLsiteBonusOriginalProbeState)
                    .filter(
                        DLsiteBonusOriginalProbeState.circle_id == catalog.circle_id,
                        DLsiteBonusOriginalProbeState.original_rjcode.in_(work_canonical_rjcodes),
                        DLsiteBonusOriginalProbeState.strategy_version == "date-range-v4",
                        DLsiteBonusOriginalProbeState.status.in_(("no_bonus", "has_bonus")),
                    )
                    .all()
                )
                early_bonus_state_map = {
                    normalized: str(row.status or "").strip()
                    for row in state_rows
                    for normalized in [self.normalize_rjcode(row.original_rjcode)]
                    if normalized
                }
            link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            for link_row in link_rows:
                link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                    "link_type": str(link_row.link_type or ""),
                    "lang": str(link_row.lang or ""),
                }
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
            local_download_session_map = self._build_local_download_session_map(db, works, link_map_by_canonical)
        finally:
            db.close()

        image_cache_service = get_circle_image_cache_service()
        now_local_for_view = get_local_now()
        items = [
            self._build_completion_item(
                catalog=catalog,
                row=row,
                owned_row=owned_rows.get(row.canonical_rjcode),
                link_map_by_canonical=link_map_by_canonical,
                metadata_map_all=metadata_map_all,
                local_download_session_map=local_download_session_map,
                image_cache_service=image_cache_service,
                include_source_compare=True,
                include_heavy_fields=False,
                now_local_for_view=now_local_for_view,
            )
            for row in works
        ]
        items = self._completion_apply_explicit_bonus_parent_codes(items, link_rows)
        items = self._completion_attach_bonus_parent_codes(items)
        self._completion_apply_early_bonus_status(items, early_bonus_state_map)
        catalog_payload = {
            "circle_id": catalog.circle_id,
            "circle_name": catalog.circle_name,
            "source_mask": catalog.source_mask or "",
            "last_indexed_at": catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None,
        }
        state = {"catalog": catalog_payload, "items": items}
        return state

    def _completion_summary_from_items(self, catalog: Any, items: List[Dict[str, Any]], *, visible_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        visible = items if visible_items is None else visible_items
        owned_items = [item for item in items if item.get("owned")]
        compare_missing = [
            item for item in items
            if not item.get("server_owned") and not item.get("has_dlsite") and not item.get("has_asmr_one")
        ]
        circle_id = catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id
        circle_name = catalog.get("circle_name") if isinstance(catalog, dict) else catalog.circle_name
        source_mask = catalog.get("source_mask") if isinstance(catalog, dict) else (catalog.source_mask or "")
        last_indexed_at = (
            catalog.get("last_indexed_at")
            if isinstance(catalog, dict)
            else (catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None)
        )
        return {
            "circle_id": circle_id,
            "circle_name": circle_name,
            "source_mask": source_mask,
            "last_indexed_at": last_indexed_at,
            "local_owned_count": sum(1 for item in items if item.get("local_owned")),
            "server_owned_count": sum(1 for item in items if item.get("server_owned")),
            "owned_count": sum(1 for item in items if item.get("owned")),
            "missing_count": sum(1 for item in items if not item.get("owned")),
            "downloadable_count": sum(1 for item in items if not item.get("owned") and item.get("has_asmr_one")),
            "dl_only_count": sum(1 for item in items if not item.get("owned") and not item.get("has_asmr_one")),
            "dl_count": sum(1 for item in items if item.get("has_dlsite")),
            "filtered_count": len(visible),
            "total_works": len(items),
            "unreleased_count": sum(1 for item in items if not item.get("owned") and item.get("is_unreleased")),
            "new_works_count": sum(1 for item in items if item.get("is_new_work")),
            "bonus_works_count": sum(1 for item in items if item.get("is_bonus_work")),
            "owned_stats": {
                "total": len(owned_items),
                "original": sum(1 for item in owned_items if self._completion_variant_group_key(item, owned=True) == "original" and not item.get("subtitle_present")),
                "simplified": sum(1 for item in owned_items if self._completion_variant_group_key(item, owned=True) == "simplified"),
                "traditional": sum(1 for item in owned_items if self._completion_variant_group_key(item, owned=True) == "traditional"),
                "subtitle": sum(1 for item in owned_items if self._completion_variant_group_key(item, owned=True) == "original" and item.get("subtitle_present")),
                "bonus": sum(1 for item in owned_items if item.get("is_bonus_work")),
            },
            "compare_stats": {
                "total": len(items),
                "kikoeru": sum(1 for item in items if item.get("server_owned")),
                "dlsite": sum(1 for item in items if item.get("has_dlsite")),
                "asmr_one": sum(1 for item in items if item.get("has_asmr_one")),
                "missing": len(compare_missing),
            },
            "status_filter_counts": {
                "missing": {
                    key: sum(1 for item in items if self._is_preferred_missing_completion_item(item) and self._completion_item_matches_status_filter(item, key))
                    for key in ["repairable", "downloadable", "missing", "no_source", "has_early_bonus", "no_early_bonus"]
                },
                "owned": {
                    key: sum(1 for item in items if item.get("owned") and self._completion_item_matches_status_filter(item, key))
                    for key in ["repairable", "downloadable", "missing", "no_source", "has_early_bonus", "no_early_bonus"]
                },
            },
        }

    def _is_preferred_missing_completion_item(self, item: Dict[str, Any]) -> bool:
        if item.get("owned"):
            return False
        group_key = str((item.get("preferred_variant") or {}).get("group_key") or "original").strip()
        return group_key in {"original", "simplified", "traditional", ""}

    def _filter_completion_items_for_tab(
        self,
        items: List[Dict[str, Any]],
        *,
        tab: str,
        include_dl_only: bool,
        status_filters: Optional[List[str]] = None,
        owned_filter: str = "all",
        compare_filter: str = "all",
        search: str = "",
    ) -> List[Dict[str, Any]]:
        tab_key = str(tab or "missing").strip().lower()
        source_visible_items = [
            item for item in items
            if include_dl_only or item.get("owned") or item.get("has_asmr_one")
        ]
        if tab_key == "owned":
            rows = [item for item in source_visible_items if item.get("owned")]
            owned_filter = str(owned_filter or "all").strip().lower()
            if owned_filter != "all":
                def _owned_filter_match(item: Dict[str, Any]) -> bool:
                    group_key = self._completion_variant_group_key(item, owned=True)
                    has_subtitle = group_key == "original" and bool(item.get("subtitle_present"))
                    if owned_filter == "original":
                        return group_key == "original" and not has_subtitle
                    if owned_filter == "simplified":
                        return group_key == "simplified"
                    if owned_filter == "traditional":
                        return group_key == "traditional"
                    if owned_filter == "subtitle":
                        return has_subtitle
                    if owned_filter == "bonus":
                        return bool(item.get("is_bonus_work"))
                    return True
                rows = [item for item in rows if _owned_filter_match(item)]
        elif tab_key == "compare":
            rows = list(source_visible_items)
            compare_filter = str(compare_filter or "all").strip().lower()
            if compare_filter != "all":
                def _compare_match(item: Dict[str, Any]) -> bool:
                    source_compare = item.get("source_compare") if isinstance(item.get("source_compare"), dict) else {}
                    dlsite = source_compare.get("dlsite") if isinstance(source_compare.get("dlsite"), dict) else {}
                    asmr_one = source_compare.get("asmr_one") if isinstance(source_compare.get("asmr_one"), dict) else {}
                    if compare_filter == "kikoeru":
                        return bool(item.get("server_owned"))
                    if compare_filter == "dlsite":
                        return bool(dlsite.get("all_rjcodes"))
                    if compare_filter == "asmr_one":
                        return bool(asmr_one.get("primary_rjcode"))
                    if compare_filter == "missing":
                        return not item.get("server_owned") and not dlsite.get("all_rjcodes") and not asmr_one.get("primary_rjcode")
                    return True
                rows = [item for item in rows if _compare_match(item)]
        else:
            rows = [item for item in source_visible_items if self._is_preferred_missing_completion_item(item)]

        rows = self._completion_apply_status_filters(rows, status_filters or [])
        if search:
            rows = [item for item in rows if self._completion_search_match(item, search)]
        return rows

    def _sort_completion_items(self, rows: List[Dict[str, Any]], sort: str) -> List[Dict[str, Any]]:
        sort_key = str(sort or "updated_desc").strip().lower()
        if sort_key in {"release_asc", "release_desc"}:
            direction = 1 if sort_key == "release_asc" else -1
            return sorted(
                rows,
                key=lambda item: (
                    self._completion_release_timestamp(item) * direction,
                    str(item.get("title") or ""),
                ),
            )
        return rows

    async def build_circle_completion_summary(self, circle_id_or_query: str, *, include_dl_only: bool = True) -> Dict[str, Any]:

        cache_key = self._completion_query_cache_key(
            "summary",
            circle_id_or_query,
            {"include_dl_only": bool(include_dl_only)},
        )
        cache_enabled = not self._completion_state_builder_overridden()
        if cache_enabled:
            cached = self._completion_l1_l2_get(self._completion_summary_cache, "summary", cache_key)
            if isinstance(cached, dict):
                return cached

        state = await self._get_completion_view_state(circle_id_or_query)
        catalog = state["catalog"]
        items = self._completion_attach_bonus_parent_codes([dict(item) for item in state["items"]])
        visible_items = [
            item for item in items
            if include_dl_only or item.get("owned") or item.get("has_asmr_one")
        ]
        result = self._completion_summary_from_items(catalog, items, visible_items=visible_items)
        if cache_enabled:
            self._completion_l1_l2_set(
                self._completion_summary_cache,
                "summary",
                cache_key,
                result,
                ttl_seconds=self._COMPLETION_SUMMARY_REDIS_TTL_SECONDS,
            )
        return deepcopy(result)

    async def list_circle_completion_works(
        self,
        circle_id_or_query: str,
        *,
        tab: str = "missing",
        page: int = 1,
        page_size: int = 10,
        include_dl_only: bool = True,
        status_filters: Any = None,
        owned_filter: str = "all",
        compare_filter: str = "all",
        search: str = "",
        sort: str = "updated_desc",
        view_mode: str = "list",
    ) -> Dict[str, Any]:
        normalized_filters = self._completion_status_filters(status_filters)
        tab_key = str(tab or "missing").strip().lower()
        card_mode = str(view_mode or "").strip().lower() == "card"
        safe_page_size = max(1, min(200, int(page_size or 10)))
        safe_page_request = max(1, int(page or 1))
        query_cache_key = self._completion_query_cache_key(
            "page",
            circle_id_or_query,
            {
                "tab": tab_key,
                "page": safe_page_request,
                "page_size": safe_page_size,
                "include_dl_only": bool(include_dl_only),
                "status_filters": normalized_filters,
                "owned_filter": str(owned_filter or "all").strip().lower(),
                "compare_filter": str(compare_filter or "all").strip().lower(),
                "search": str(search or "").strip(),
                "sort": str(sort or "updated_desc").strip().lower(),
                "view_mode": "card" if card_mode else "list",
            },
        )
        cache_enabled = not self._completion_state_builder_overridden()
        if cache_enabled:
            cached = self._completion_l1_l2_get(self._completion_page_cache, "page", query_cache_key)
            if isinstance(cached, dict):
                return cached

        state = await self._get_completion_view_state(circle_id_or_query)
        catalog = state["catalog"]
        items = self._completion_attach_bonus_parent_codes([dict(item) for item in state["items"]])
        if card_mode and tab_key in {"missing", "owned"}:
            grouped_filtered = self._filter_completion_items_for_card_tab(
                items,
                tab=tab_key,
                include_dl_only=include_dl_only,
                status_filters=normalized_filters,
                owned_filter=owned_filter,
                search=search,
            )
            grouped_filtered = self._sort_completion_items(grouped_filtered, sort)
            filtered = [
                member
                for item in grouped_filtered
                for member in self._completion_group_members(item)
            ]
        else:
            filtered = self._filter_completion_items_for_tab(
                items,
                tab=tab,
                include_dl_only=include_dl_only,
                status_filters=normalized_filters,
                owned_filter=owned_filter,
                compare_filter=compare_filter,
                search=search,
            )
            filtered = self._sort_completion_items(filtered, sort)
            grouped_filtered = (
                self._completion_group_bonus_items([dict(item) for item in filtered])
                if tab_key in {"missing", "owned"}
                else filtered
            )
        total = len(grouped_filtered)
        page_count = max(1, (total + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(page_count, safe_page_request))
        start = (safe_page - 1) * safe_page_size
        page_items = grouped_filtered[start:start + safe_page_size]
        if tab_key == "compare":
            payload_items = [self._build_completion_compare_item(item) for item in page_items]
        else:
            payload_items = [self._strip_completion_internal_fields(item) for item in page_items]
        summary = self._completion_summary_from_items(catalog, items, visible_items=filtered)
        result = {
            **summary,
            "tab": tab_key,
            "items": payload_items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "page_count": page_count,
            "status_filters": normalized_filters,
        }
        if cache_enabled:
            self._completion_l1_l2_set(
                self._completion_page_cache,
                "page",
                query_cache_key,
                result,
                ttl_seconds=self._COMPLETION_PAGE_REDIS_TTL_SECONDS,
            )
        return deepcopy(result)

    async def list_circle_completion_work_codes(
        self,
        circle_id_or_query: str,
        *,
        tab: str = "missing",
        include_dl_only: bool = True,
        status_filters: Any = None,
        owned_filter: str = "all",
        compare_filter: str = "all",
        search: str = "",
        sort: str = "updated_desc",
        selection_only: bool = False,
    ) -> Dict[str, Any]:
        normalized_filters = self._completion_status_filters(status_filters)
        tab_key = str(tab or "missing").strip().lower()
        query_cache_key = self._completion_query_cache_key(
            "work-codes",
            circle_id_or_query,
            {
                "tab": tab_key,
                "include_dl_only": bool(include_dl_only),
                "status_filters": normalized_filters,
                "owned_filter": str(owned_filter or "all").strip().lower(),
                "compare_filter": str(compare_filter or "all").strip().lower(),
                "search": str(search or "").strip(),
                "sort": str(sort or "updated_desc").strip().lower(),
                "selection_only": bool(selection_only),
            },
        )
        cache_enabled = not self._completion_state_builder_overridden()
        if cache_enabled:
            cached = self._completion_l1_l2_get(self._completion_codes_cache, "work-codes", query_cache_key)
            if isinstance(cached, dict):
                return cached

        state = await self._get_completion_view_state(circle_id_or_query)
        catalog = state["catalog"]
        items = state["items"]
        filtered = self._filter_completion_items_for_tab(
            items,
            tab=tab,
            include_dl_only=include_dl_only,
            status_filters=normalized_filters,
            owned_filter=owned_filter,
            compare_filter=compare_filter,
            search=search,
        )
        filtered = self._sort_completion_items(filtered, sort)
        grouped_for_bonus = (
            self._completion_group_bonus_items([dict(item) for item in filtered])
            if tab_key in {"missing", "owned"}
            else [dict(item) for item in filtered]
        )
        canonical_rjcodes = [
            str(item.get("canonical_rjcode") or "").strip()
            for item in filtered
            if str(item.get("canonical_rjcode") or "").strip()
        ]
        downloadable_rjcodes = [
            str(item.get("canonical_rjcode") or "").strip()
            for item in filtered
            if str(item.get("canonical_rjcode") or "").strip() and item.get("has_asmr_one")
        ]
        if selection_only:
            result = {
                "circle_id": catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id,
                "circle_name": catalog.get("circle_name") if isinstance(catalog, dict) else catalog.circle_name,
                "canonical_rjcodes": canonical_rjcodes,
                "downloadable_rjcodes": downloadable_rjcodes,
                "total": len(canonical_rjcodes),
                "downloadable_count": len(downloadable_rjcodes),
            }
            if cache_enabled:
                self._completion_l1_l2_set(
                    self._completion_codes_cache,
                    "work-codes",
                    query_cache_key,
                    result,
                    ttl_seconds=self._COMPLETION_CODES_REDIS_TTL_SECONDS,
                )
            return deepcopy(result)
        bonus_rjcodes = [
            str(item.get("canonical_rjcode") or "").strip()
            for item in filtered
            if str(item.get("canonical_rjcode") or "").strip() and item.get("is_bonus_work")
        ]
        has_bonus_rjcodes = [
            str(item.get("canonical_rjcode") or "").strip()
            for item in grouped_for_bonus
            if (
                str(item.get("canonical_rjcode") or "").strip()
                and not item.get("is_bonus_work")
                and item.get("bonus_works")
            )
        ]
        no_bonus_rjcodes = []
        if canonical_rjcodes:
            db = SessionLocal()
            try:
                rows = (
                    db.query(DLsiteBonusOriginalProbeState)
                    .filter(
                        DLsiteBonusOriginalProbeState.circle_id == (
                            catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id
                        ),
                        DLsiteBonusOriginalProbeState.original_rjcode.in_(canonical_rjcodes),
                        DLsiteBonusOriginalProbeState.strategy_version == "date-range-v4",
                        DLsiteBonusOriginalProbeState.status == "no_bonus",
                    )
                    .all()
                )
                no_bonus_rjcodes = [
                    self.normalize_rjcode(row.original_rjcode)
                    for row in rows
                    if self.normalize_rjcode(row.original_rjcode)
                ]
            finally:
                db.close()
        requested_rjcodes = {}
        release_dates_by_rjcode = {}
        for item in filtered:
            code = str(item.get("canonical_rjcode") or "").strip()
            if not code:
                continue
            candidates = []
            for candidate in [
                (item.get("download_plan") or {}).get("rjcode") if isinstance(item.get("download_plan"), dict) else "",
                item.get("asmr_available_rjcode"),
                item.get("display_rjcode"),
                item.get("canonical_rjcode"),
                *(item.get("linked_rjcodes") or []),
            ]:
                normalized = self.normalize_rjcode(candidate)
                if normalized and normalized not in candidates:
                    candidates.append(normalized)
            if candidates:
                requested_rjcodes[code] = candidates
            release_date = await self._completion_resolve_bonus_probe_release_date(item, candidates)
            if release_date:
                release_dates_by_rjcode[code] = release_date
        completed_bonus_probe_dates = []
        if release_dates_by_rjcode:
            try:
                from .dlsite_bonus_probe_service import get_dlsite_bonus_probe_service

                bonus_service = get_dlsite_bonus_probe_service()
                context = bonus_service.resolve_circle_context(
                    str(catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id),
                )
                maker_id = str(context.get("maker_id") or "").strip().upper()
                completed_bonus_probe_dates = bonus_service.reusable_completed_release_dates(
                    maker_id=maker_id,
                    release_dates=list(release_dates_by_rjcode.values()),
                    mode="deep",
                    gap_limit=500,
                )
            except Exception:
                logger.debug("[社团补全] 查询已完成特典探测日期失败 circle=%s", circle_id_or_query, exc_info=True)
        result = {
            "circle_id": catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id,
            "circle_name": catalog.get("circle_name") if isinstance(catalog, dict) else catalog.circle_name,
            "canonical_rjcodes": canonical_rjcodes,
            "downloadable_rjcodes": downloadable_rjcodes,
            "bonus_rjcodes": bonus_rjcodes,
            "has_bonus_rjcodes": has_bonus_rjcodes,
            "no_bonus_rjcodes": no_bonus_rjcodes,
            "requested_rjcodes": requested_rjcodes,
            "release_dates_by_rjcode": release_dates_by_rjcode,
            "completed_bonus_probe_dates": completed_bonus_probe_dates,
            "total": len(canonical_rjcodes),
            "downloadable_count": len(downloadable_rjcodes),
        }
        if cache_enabled:
            self._completion_l1_l2_set(
                self._completion_codes_cache,
                "work-codes",
                query_cache_key,
                result,
                ttl_seconds=self._COMPLETION_CODES_REDIS_TTL_SECONDS,
            )
        return deepcopy(result)

    async def list_circle_completion_bonus_work_codes(self, circle_id_or_query: str) -> Dict[str, Any]:
        query_cache_key = self._completion_query_cache_key("bonus-work-codes", circle_id_or_query, {})
        cache_enabled = not self._completion_state_builder_overridden()
        if cache_enabled:
            cached = self._completion_l1_l2_get(self._completion_codes_cache, "bonus-work-codes", query_cache_key)
            if isinstance(cached, dict):
                return cached

        state = await self._get_completion_view_state(circle_id_or_query)
        catalog = state["catalog"]
        items = state["items"]
        seen: Set[str] = set()
        bonus_items: List[Dict[str, Any]] = []

        def add_bonus_item(item: Dict[str, Any]) -> None:
            if not isinstance(item, dict) or not bool(item.get("is_bonus_work")):
                return
            canonical = self.normalize_rjcode(item.get("canonical_rjcode"))
            if not canonical or canonical in seen:
                return
            seen.add(canonical)
            bonus_items.append(item)

        for item in items:
            add_bonus_item(item)
            for bonus in item.get("bonus_works") or []:
                add_bonus_item(bonus)

        # 兼容展示层把特典挂到原作卡片下的聚合形态；只读内存副本，不污染缓存。
        for item in self._completion_group_bonus_items([dict(item) for item in items]):
            for bonus in item.get("bonus_works") or []:
                add_bonus_item(bonus)

        canonical_rjcodes = [self.normalize_rjcode(item.get("canonical_rjcode")) for item in bonus_items]
        canonical_rjcodes = [code for code in canonical_rjcodes if code]
        result = {
            "circle_id": catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id,
            "circle_name": catalog.get("circle_name") if isinstance(catalog, dict) else catalog.circle_name,
            "canonical_rjcodes": canonical_rjcodes,
            "total": len(canonical_rjcodes),
            "items": [
                {
                    "canonical_rjcode": self.normalize_rjcode(item.get("canonical_rjcode")),
                    "display_rjcode": self.normalize_rjcode(item.get("display_rjcode")),
                    "title": str(item.get("title") or "").strip(),
                    "owned": bool(item.get("owned")),
                    "local_owned": bool(item.get("local_owned")),
                    "server_owned": bool(item.get("server_owned")),
                }
                for item in bonus_items
            ],
        }
        if cache_enabled:
            self._completion_l1_l2_set(
                self._completion_codes_cache,
                "bonus-work-codes",
                query_cache_key,
                result,
                ttl_seconds=self._COMPLETION_CODES_REDIS_TTL_SECONDS,
            )
        return deepcopy(result)

    async def locate_circle_completion_work(
        self,
        circle_id_or_query: str,
        *,
        rjcode: str,
        tab: str = "missing",
        page_size: int = 10,
        include_dl_only: bool = True,
        status_filters: Any = None,
        owned_filter: str = "all",
        compare_filter: str = "all",
        search: str = "",
        sort: str = "updated_desc",
    ) -> Dict[str, Any]:
        state = await self._get_completion_view_state(circle_id_or_query)
        catalog = state["catalog"]
        items = state["items"]
        tab_key = str(tab or "missing").strip().lower()
        normalized_filters = self._completion_status_filters(status_filters)
        filtered = self._filter_completion_items_for_tab(
            items,
            tab=tab_key,
            include_dl_only=include_dl_only,
            status_filters=normalized_filters,
            owned_filter=owned_filter,
            compare_filter=compare_filter,
            search=search,
        )
        filtered = self._sort_completion_items(filtered, sort)
        if tab_key in {"missing", "owned"}:
            filtered = self._completion_group_bonus_items([dict(item) for item in filtered])
        safe_page_size = max(1, min(200, int(page_size or 10)))
        matched_index = -1
        matched_item: Optional[Dict[str, Any]] = None
        matched_bonus: Optional[Dict[str, Any]] = None
        for index, item in enumerate(filtered):
            if self._completion_item_matches_rjcode(item, rjcode):
                matched_index = index
                matched_item = item
                break
            for bonus in item.get("bonus_works") or []:
                if isinstance(bonus, dict) and self._completion_item_matches_rjcode(bonus, rjcode):
                    matched_index = index
                    matched_item = item
                    matched_bonus = bonus
                    break
            if matched_item is not None:
                break
        matched = matched_index >= 0 and matched_item is not None
        page = (matched_index // safe_page_size) + 1 if matched else 1
        page_count = max(1, (len(filtered) + safe_page_size - 1) // safe_page_size)
        highlight_item = matched_bonus or matched_item
        return {
            "circle_id": catalog.get("circle_id") if isinstance(catalog, dict) else catalog.circle_id,
            "circle_name": catalog.get("circle_name") if isinstance(catalog, dict) else catalog.circle_name,
            "tab": tab_key,
            "rjcode": self.normalize_rjcode(rjcode),
            "matched": matched,
            "canonical_rjcode": self.normalize_rjcode((highlight_item or {}).get("canonical_rjcode")) if highlight_item else "",
            "display_rjcode": self.normalize_rjcode((highlight_item or {}).get("display_rjcode")) if highlight_item else "",
            "parent_canonical_rjcode": self.normalize_rjcode(matched_item.get("canonical_rjcode")) if matched_item else "",
            "page": max(1, min(page_count, page)),
            "page_size": safe_page_size,
            "page_count": page_count,
            "total": len(filtered),
            "index": matched_index,
        }

    async def search_circle_completion_works(self, keyword: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """按 RJ / 标题在已建立的社团索引里反查作品归属。

        这是社团补全页的定位搜索，只读本地索引表，不触发 DLsite / Kikoeru
        网络请求；用户输入 RJ 后用它找到所属社团，再跳转到该社团详情页。
        """
        from sqlalchemy import Text as sa_Text, cast as sa_cast, or_ as sa_or, text as sa_text

        raw_keyword = str(keyword or "").strip()
        if not raw_keyword:
            return []
        safe_limit = max(1, min(50, int(limit or 20)))
        normalized_rj = self.normalize_rjcode(raw_keyword)
        lowered_keyword = raw_keyword.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        like_pattern = f"%{lowered_keyword}%"
        json_pattern = f"%{normalized_rj}%"

        db = SessionLocal()
        try:
            query = (
                db.query(CircleWork, CircleCatalog, LibraryOwnedWork)
                .join(CircleCatalog, CircleCatalog.circle_id == CircleWork.circle_id)
                .outerjoin(LibraryOwnedWork, LibraryOwnedWork.canonical_rjcode == CircleWork.canonical_rjcode)
            )

            filters = [
                sa_text(
                    """
                    (COALESCE(circle_works.canonical_rjcode, '') || ' ' ||
                     COALESCE(circle_works.display_rjcode, '') || ' ' ||
                     COALESCE(circle_works.title, '')) ILIKE :circle_work_search_pattern ESCAPE '!'
                    """
                ).bindparams(circle_work_search_pattern=like_pattern),
                sa_text(
                    """
                    (COALESCE(circle_catalogs.circle_name_normalized, '') || ' ' ||
                     COALESCE(circle_catalogs.circle_name, '') || ' ' ||
                     COALESCE(circle_catalogs.circle_id, '')) ILIKE :circle_catalog_search_pattern ESCAPE '!'
                    """
                ).bindparams(circle_catalog_search_pattern=like_pattern),
            ]
            if normalized_rj:
                filters.extend([
                    CircleWork.canonical_rjcode == normalized_rj,
                    CircleWork.display_rjcode == normalized_rj,
                    sa_cast(CircleWork.linked_rjcodes, sa_Text).like(json_pattern),
                ])
            rows = (
                query
                .filter(sa_or(*filters))
                .order_by(
                    (CircleWork.canonical_rjcode == normalized_rj).desc(),
                    (CircleWork.display_rjcode == normalized_rj).desc(),
                    CircleCatalog.last_indexed_at.desc(),
                    CircleWork.updated_at.desc(),
                )
                .limit(safe_limit * 2)
                .all()
            )

            metadata_codes: List[str] = []
            for work, _, _ in rows:
                for candidate in [
                    work.canonical_rjcode,
                    work.display_rjcode,
                    *(work.linked_rjcodes or []),
                ]:
                    normalized = self.normalize_rjcode(candidate)
                    if normalized and normalized not in metadata_codes:
                        metadata_codes.append(normalized)
            metadata_map = self._load_cached_metadata_map(db, metadata_codes)
            image_cache_service = get_circle_image_cache_service()

            results: List[Dict[str, Any]] = []
            seen: Set[Tuple[str, str]] = set()
            for work, catalog, owned_row in rows:
                circle_id = str(work.circle_id or "").strip()
                canonical = self.normalize_rjcode(work.canonical_rjcode)
                if not circle_id or not canonical:
                    continue
                dedupe_key = (circle_id, canonical)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                display_rjcode = self.normalize_rjcode(work.display_rjcode) or canonical
                title = str(work.title or "").strip()
                if not title:
                    title = str((metadata_map.get(display_rjcode) or metadata_map.get(canonical) or {}).get("work_name") or "").strip()
                release_date = str((metadata_map.get(display_rjcode) or metadata_map.get(canonical) or {}).get("release_date") or "").strip()
                cvs = list((metadata_map.get(display_rjcode) or metadata_map.get(canonical) or {}).get("cvs") or [])
                normalized_cover = self._normalize_dlsite_cover_url(
                    work.image_url,
                    display_rjcode or canonical,
                    is_unreleased=self._is_future_release_date(release_date),
                )
                cover_cache_rjcode = image_cache_service.cache_rjcode_for_url(
                    normalized_cover,
                    display_rjcode or canonical,
                )
                if cover_cache_rjcode and cover_cache_rjcode != display_rjcode:
                    image_cache_service.restore_from_legacy_alias(
                        cover_cache_rjcode,
                        [display_rjcode],
                    )
                    image_cache_service.restore_from_legacy_alias(
                        cover_cache_rjcode,
                        [display_rjcode],
                        variant="list",
                    )
                local_cover_url = image_cache_service.get_local_url(
                    cover_cache_rjcode,
                    allow_missing=True,
                )
                local_thumb_url = image_cache_service.get_local_url(
                    cover_cache_rjcode,
                    variant="list",
                    allow_missing=True,
                )

                results.append({
                    "circle_id": circle_id,
                    "circle_name": catalog.circle_name or circle_id,
                    "canonical_rjcode": canonical,
                    "display_rjcode": display_rjcode,
                    "title": title or display_rjcode or canonical,
                    "linked_rjcodes": list(work.linked_rjcodes or []),
                    "image_url": local_cover_url or normalized_cover,
                    "remote_image_url": normalized_cover,
                    "thumb_image_url": local_thumb_url or self._normalize_dlsite_thumb_url(
                        normalized_cover,
                        display_rjcode or canonical,
                        is_unreleased=self._is_future_release_date(release_date),
                    ),
                    "cvs": cvs,
                    "release_date": release_date,
                    "owned": owned_row is not None,
                    "server_owned": owned_row is not None,
                    "has_asmr_one": bool(work.has_asmr_one),
                    "asmr_available_rjcode": self.normalize_rjcode(work.asmr_available_rjcode),
                    "last_indexed_at": catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None,
                    "updated_at": work.updated_at.isoformat() if work.updated_at else None,
                })
                if len(results) >= safe_limit:
                    break
            return results
        finally:
            db.close()

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
            {"key": "kikoeru", "label": "库存已收录", "count": sum(1 for item in works if item.get("server_owned"))},
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
                "is_bonus_work": bool(item.get("is_bonus_work")),
                "has_bonus": bool(item.get("has_bonus")),
                "original_subtitle_present": bool(item.get("subtitle_present")),
                "preferred_variant_label": preferred_variant.get("label") or "优先版本 未标记",
                "status_label": "本地已下载" if item.get("local_download_ready") else ("库存已收录" if item.get("server_owned") else ("可下载" if item.get("has_asmr_one") else "暂无来源")),
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

    def get_external_search_variants(
        self,
        circle_id: str,
        canonical_rjcodes: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """读取当前页作品的关联 RJ 及语言分组，供外部搜索接口使用。"""
        normalized_codes = []
        for value in canonical_rjcodes or []:
            normalized = self.normalize_rjcode(value)
            if normalized and normalized not in normalized_codes:
                normalized_codes.append(normalized)
        if not normalized_codes:
            return {}

        db = SessionLocal()
        try:
            rows = db.query(CircleWork).filter(
                CircleWork.circle_id == str(circle_id or "").strip(),
                CircleWork.canonical_rjcode.in_(normalized_codes),
            ).all()
            if not rows:
                return {}
            links = db.query(WorkCanonicalLink).filter(
                WorkCanonicalLink.evidence_status == "verified",
                WorkCanonicalLink.canonical_rjcode.in_([row.canonical_rjcode for row in rows]),
            ).all()
            link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            lookup_codes = set()
            for link in links:
                canonical = self.normalize_rjcode(link.canonical_rjcode)
                linked = self.normalize_rjcode(link.linked_rjcode)
                if not canonical or not linked:
                    continue
                link_map_by_canonical[canonical][linked] = {
                    "link_type": str(link.link_type or ""),
                    "lang": str(link.lang or ""),
                }
                lookup_codes.add(linked)
            for row in rows:
                lookup_codes.add(self.normalize_rjcode(row.canonical_rjcode))
                lookup_codes.add(self.normalize_rjcode(row.display_rjcode))
                lookup_codes.update(self.normalize_rjcode(code) for code in (row.linked_rjcodes or []))
            metadata_rows = db.query(WorkMetadata).filter(WorkMetadata.rjcode.in_(list(lookup_codes))).all()
            metadata_map = {self.normalize_rjcode(row.rjcode): row for row in metadata_rows}
            output: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                canonical = self.normalize_rjcode(row.canonical_rjcode)
                linked_codes = [self.normalize_rjcode(code) for code in (row.linked_rjcodes or []) if self.normalize_rjcode(code)]
                linked_codes.extend(link_map_by_canonical.get(canonical, {}).keys())
                if canonical not in linked_codes:
                    linked_codes.append(canonical)
                info = {
                    "canonical_rjcode": canonical,
                    "linked_rjcodes": list(dict.fromkeys(linked_codes)),
                    "link_map": link_map_by_canonical.get(canonical) or {},
                }
                variants = []
                seen_language_groups = set()
                for variant in self._sort_linked_variants(info, canonical):
                    rjcode = self.normalize_rjcode(variant.get("rjcode"))
                    if not rjcode:
                        continue
                    group = self._variant_group(variant.get("link_type"), variant.get("lang"))
                    group_key = str(group.get("key") or "other")
                    if group_key not in {"original", "simplified", "traditional"}:
                        continue
                    lang = self._normalize_lang_code(variant.get("lang"))
                    language_key = group_key
                    if language_key in seen_language_groups:
                        continue
                    seen_language_groups.add(language_key)
                    metadata = metadata_map.get(rjcode)
                    variants.append({
                        "rjcode": rjcode,
                        "title": str(getattr(metadata, "work_name", "") or row.title or "").strip(),
                        "lang": lang,
                        "group_key": group_key,
                        "group_label": str(group.get("label") or "其他语言"),
                        "group_short_label": str(group.get("short_label") or "其他"),
                    })
                output[canonical] = variants
            return output
        finally:
            db.close()

    def _build_variant_payload_for_rjcode(
        self,
        canonical_info: Dict[str, Any],
        rjcode: Any,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """按实际 RJ 号生成展示版本；用于已拥有态，不参与下载优先级选择。"""

        normalized = self.normalize_rjcode(rjcode)
        canonical = self.normalize_rjcode(canonical_info.get("canonical_rjcode"))
        link_map = dict(canonical_info.get("link_map") or {})
        meta = link_map.get(normalized) or {}
        if normalized and normalized == canonical and not meta:
            meta = {"link_type": "original", "lang": "JPN"}
        group = self._variant_group(meta.get("link_type"), meta.get("lang"))
        if group.get("key") == "other" and metadata_map:
            badge = self._infer_variant_badge_from_metadata(normalized, metadata_map)
            if badge == "简中":
                group = {"key": "simplified", "label": "简体优先", "short_label": "简中"}
            elif badge == "繁中":
                group = {"key": "traditional", "label": "繁体优先", "short_label": "繁中"}
        return {
            "rjcode": normalized,
            "lang": self._normalize_lang_code(meta.get("lang")),
            "link_type": str(meta.get("link_type") or ("original" if normalized == canonical else "")).strip().lower(),
            "group_key": group["key"],
            "group_label": group["label"],
            "group_short_label": group["short_label"],
        }

    def _pick_owned_primary_rjcode(
        self,
        canonical_info: Dict[str, Any],
        *,
        server_match_primary_rjcode: str = "",
        local_owned_rjcodes: Optional[List[str]] = None,
        local_subtitle_present: bool = False,
        subtitle_dir: str = "",
        primary_folder_path: str = "",
    ) -> str:
        canonical = self.normalize_rjcode(canonical_info.get("canonical_rjcode"))
        owned_rjcodes: List[str] = []
        for candidate in list(local_owned_rjcodes or []):
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized not in owned_rjcodes:
                owned_rjcodes.append(normalized)

        # 已收录态单独按真实落盘目录判定；未收录下载 / 展示仍保持 preferred_variant 的翻译优先。
        if local_subtitle_present and canonical:
            path_text = " ".join([str(subtitle_dir or ""), str(primary_folder_path or "")]).upper()
            if canonical in path_text:
                return canonical

        server_primary = self.normalize_rjcode(server_match_primary_rjcode)
        if server_primary:
            return server_primary
        if owned_rjcodes:
            return owned_rjcodes[0]
        return canonical or ""

    def _actual_owned_rjcodes(self, owned_row: Optional[LibraryOwnedWork]) -> List[str]:
        """优先从真实库存路径恢复 RJ，兼容旧快照曾把整条关联链写进 owned_rjcodes。"""
        if owned_row is None:
            return []
        path_rjcodes: List[str] = []
        paths = [
            *list(owned_row.owned_paths or []),
            owned_row.primary_folder_path,
            owned_row.subtitle_dir,
        ]
        for path_value in paths:
            for matched in re.findall(r"RJ\d{4,12}", str(path_value or ""), re.IGNORECASE):
                normalized = self.normalize_rjcode(matched)
                if normalized and normalized not in path_rjcodes:
                    path_rjcodes.append(normalized)
        if path_rjcodes:
            return path_rjcodes

        stored_rjcodes: List[str] = []
        for candidate in list(owned_row.owned_rjcodes or []):
            normalized = self.normalize_rjcode(candidate)
            if normalized and normalized not in stored_rjcodes:
                stored_rjcodes.append(normalized)
        return stored_rjcodes

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
        for row in rows:
            session = row.to_dict()
            statistics = dict(session.get("statistics") or {})
            local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
            local_count = int(session.get("local_downloaded_count") or 0)
            # 详情页切换频繁，这里优先使用数据库中已持久化的下载状态，
            # 避免每次点击社团都触发大量磁盘 exists / walk 检查。
            # 只有明确的 local_download_ready 标志才视为「已下载可入库」，
            # 不能用 local_count > 0 兜底，避免下载了一半的临时文件被误判为完成。
            local_ready = bool(local_root and session.get("local_download_ready"))
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

        result: Dict[str, Dict[str, Any]] = {}
        for canonical, candidates in canonical_candidates.items():
            for code in candidates:
                matched = session_by_rj.get(code)
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
        try:
            work_id = int(work.get("id") or 0)
        except Exception:
            work_id = 0
        if 0 < work_id < 1_000_000:
            return f"RJ{work_id:06d}"
        if work_id > 0:
            return f"RJ{work_id:08d}"

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
        return ""

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

    def _normalize_kikoeru_circle_id(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text if text.isdigit() else ""

    def _get_cached_kikoeru_circle_id(self, cache_key: Any) -> str:
        key = str(cache_key or "").strip()
        if not key:
            return ""
        payload = self._kikoeru_circle_id_cache.get(key)
        if not payload:
            return ""
        circle_id, expires_at = payload
        if float(expires_at or 0) <= time.time():
            self._kikoeru_circle_id_cache.pop(key, None)
            return ""
        return self._normalize_kikoeru_circle_id(circle_id)

    def _set_cached_kikoeru_circle_id(self, circle_id: Any, *cache_keys: Any, ttl_seconds: int = 21600) -> str:
        normalized_circle_id = self._normalize_kikoeru_circle_id(circle_id)
        if not normalized_circle_id:
            return ""
        expires_at = time.time() + max(int(ttl_seconds or 0), 300)
        for cache_key in cache_keys:
            key = str(cache_key or "").strip()
            if not key:
                continue
            self._kikoeru_circle_id_cache[key] = (normalized_circle_id, expires_at)
        return normalized_circle_id

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

    def _load_persisted_kikoeru_circle_id(self, db, normalized_name: str, maker_id: str = "") -> str:
        normalized_name = str(normalized_name or "").strip()
        normalized_maker_id = str(maker_id or "").strip().upper()

        if normalized_name:
            row = (
                db.query(CircleExternalIdentity)
                .filter(CircleExternalIdentity.circle_name_normalized == normalized_name)
                .order_by(CircleExternalIdentity.updated_at.desc(), CircleExternalIdentity.id.desc())
                .first()
            )
            if row:
                circle_id = self._normalize_kikoeru_circle_id(row.kikoeru_circle_id)
                if circle_id:
                    return circle_id

        if normalized_maker_id:
            row = (
                db.query(CircleExternalIdentity)
                .filter(CircleExternalIdentity.maker_id == normalized_maker_id)
                .order_by(CircleExternalIdentity.updated_at.desc(), CircleExternalIdentity.id.desc())
                .first()
            )
            if row:
                circle_id = self._normalize_kikoeru_circle_id(row.kikoeru_circle_id)
                if circle_id:
                    return circle_id

        return ""

    def _save_persisted_kikoeru_circle_id(self, normalized_name: str, circle_id: Any, maker_id: str = "") -> str:
        normalized_name = str(normalized_name or "").strip()
        normalized_circle_id = self._normalize_kikoeru_circle_id(circle_id)
        normalized_maker_id = str(maker_id or "").strip().upper()
        if not normalized_circle_id:
            return ""

        db = SessionLocal()
        try:
            row = None
            if normalized_name:
                row = db.query(CircleExternalIdentity).filter(CircleExternalIdentity.circle_name_normalized == normalized_name).first()
            if row is None and normalized_maker_id:
                row = db.query(CircleExternalIdentity).filter(CircleExternalIdentity.maker_id == normalized_maker_id).first()
            if row is None:
                row = CircleExternalIdentity()
                db.add(row)

            if normalized_name:
                row.circle_name_normalized = normalized_name
            if normalized_maker_id:
                row.maker_id = normalized_maker_id
            row.kikoeru_circle_id = normalized_circle_id
            row.updated_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 持久化 Kikoeru 社团ID失败 normalized_name=%s maker_id=%s", normalized_name, normalized_maker_id, exc_info=True)
        finally:
            db.close()

        return normalized_circle_id

    @contextlib.contextmanager
    def _canonical_buffered_writes(self):
        """wave1 等批量 ``resolve_canonical_rj`` 场景里把"逐 RJ commit"合并为一次 bulk commit。

        ⚠ 性能优化（wave1 16-19 分 → 预期 < 5 分）：
        默认路径每个 RJ 都开一个 ``SessionLocal()`` 跑 ``DELETE + INSERT + COMMIT``，
        在 ``wave1_sem=20`` 协程下触发数据库写入串行化、同步代码独占 event loop，
        实际并发退化为接近串行。with 块期间所有 ``resolve_canonical_rj`` 内的 DB write
        全部 append 到 ``self._canonical_write_buffer``，with 退出时一次性 ``_flush_canonical_write_buffer``。
        Block 1（SELECT cached_rows，refresh=True 时反正不用）和 Block 2（SELECT overlap_codes，
        全量 INSERT 时也能自动覆盖）在 buffered 模式下都跳过，进一步消除 event loop 阻塞。

        with 块内 raise 时主动放弃 buffer（不 flush），下次索引会重新跑出来。
        """
        if self._canonical_write_buffer is not None:
            # 不支持嵌套（理论上不会发生），直接 yield 让外层管理
            yield
            return
        self._canonical_write_buffer = []
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            buffer = self._canonical_write_buffer or []
            self._canonical_write_buffer = None
            if succeeded and buffer:
                try:
                    self._flush_canonical_write_buffer(buffer)
                except Exception:
                    logger.warning(
                        "[社团补全·snapshot] wave1 批量 flush canonical writes 失败 size=%d",
                        len(buffer), exc_info=True,
                    )

    def _flush_canonical_write_buffer(
        self, buffer: List[Tuple[str, List[Dict[str, Any]]]]
    ) -> None:
        """把 ``_canonical_buffered_writes`` 收集的 ``(canonical, link_rows)`` 一次批量落库。

        语义跟 ``resolve_canonical_rj`` 内联的 Block 3 完全一致：先 DELETE 所有相关
        canonical / linked RJ 的旧行，再 INSERT 新的。整批进同一个 SessionLocal，
        一次 commit。数据库写入只串行 1 次而不是 587 次。
        """
        if not buffer:
            return
        # 去重：同一个 canonical_rjcode 可能被多个 RJ 解析出来，留最后一份覆盖
        latest_by_canonical: Dict[str, List[Dict[str, Any]]] = {}
        for canonical, link_rows in buffer:
            if not canonical:
                continue
            latest_by_canonical[canonical] = link_rows
        if not latest_by_canonical:
            return
        all_canonical_codes: Set[str] = set(latest_by_canonical.keys())
        all_linked_codes: Set[str] = set()
        for link_rows in latest_by_canonical.values():
            for row in link_rows:
                code = row.get("linked_rjcode")
                if code:
                    all_linked_codes.add(code)

        db = SessionLocal()
        try:
            # 一次性删除所有相关旧行：DELETE WHERE canonical IN (...) OR linked IN (...)
            db.query(WorkCanonicalLink).filter(
                (WorkCanonicalLink.canonical_rjcode.in_(all_canonical_codes))
                | (WorkCanonicalLink.linked_rjcode.in_(all_linked_codes))
            ).delete(synchronize_session=False)
            # 一次性 INSERT 新的
            now = datetime.now()
            for canonical, link_rows in latest_by_canonical.items():
                for row in link_rows:
                    linked = row.get("linked_rjcode")
                    if not linked:
                        continue
                    db.add(WorkCanonicalLink(
                        id=str(uuid.uuid4()),
                        canonical_rjcode=canonical,
                        linked_rjcode=linked,
                        link_type=row.get("link_type") or "linked",
                        lang=row.get("lang") or "",
                        evidence_source=row.get("evidence_source") or "unknown",
                        evidence_status=row.get("evidence_status") or "unverified",
                        cached_at=now,
                    ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _prewarm_canonical_cache_from_db(self, rjcodes: List[str]) -> int:
        """wave1 前一次性把 ``WorkCanonicalLink`` 里的关联链批量灌进 ``_canonical_cache``。

        ⚠ 性能优化（wave1 19.59 分钟 → 预期秒级）：
        旧实现里每个 RJ 都同步开 ``SessionLocal()`` 查 ``WorkCanonicalLink`` 然后调
        ``dlsite_service.get_linked_works``，587 RJ × ``wave1_sem=20`` 在 SQLAlchemy
        同步 IO 下退化为接近串行（实测 1175s ≈ 串行 2s × 587）。
        改为：一次 ``WHERE linked_rjcode IN (...) OR canonical_rjcode IN (...)``
        拉所有相关行（实测命中率 ~100%），按链路构造 payload 灌进 ``_canonical_cache``。
        wave1 内 ``resolve_canonical_rj`` 见 memory cache 命中直接 return，跳过 DB+HTTP。

        返回预热到 cache 的 RJ 数量（去重后）。
        """
        if not rjcodes:
            return 0
        normalized = list({self.normalize_rjcode(rj) for rj in rjcodes if self.normalize_rjcode(rj)})
        if not normalized:
            return 0

        def _rj_sort_key(value: Any) -> tuple[int, str]:
            v = self.normalize_rjcode(value)
            match = re.search(r"RJ(\d+)", v)
            return (int(match.group(1)) if match else 10**12, v)

        def _select_canonical(rows: List[Any], fallback_rj: str) -> str:
            candidates = []
            for row in rows:
                candidates.append({
                    "rjcode": self.normalize_rjcode(row.linked_rjcode),
                    "link_type": str(row.link_type or "").strip().lower(),
                    "lang": self._normalize_lang_code(str(row.lang or "")),
                })
            candidates = [c for c in candidates if c["rjcode"]]
            original = [c["rjcode"] for c in candidates if c["link_type"] == "original"]
            if original:
                return sorted(original, key=_rj_sort_key)[0]
            jpn = [c["rjcode"] for c in candidates if c["lang"] in {"JPN", "JA", "JP"}]
            if jpn:
                return sorted(jpn, key=_rj_sort_key)[0]
            all_codes = [c["rjcode"] for c in candidates]
            if all_codes:
                return sorted(all_codes, key=_rj_sort_key)[0]
            return self.normalize_rjcode(fallback_rj)

        db = SessionLocal()
        try:
            all_rows = (
                db.query(WorkCanonicalLink)
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    (WorkCanonicalLink.linked_rjcode.in_(normalized))
                    | (WorkCanonicalLink.canonical_rjcode.in_(normalized))
                )
                .all()
            )
        except Exception:
            logger.warning("[社团补全·snapshot] wave1 批量预热 WorkCanonicalLink 失败", exc_info=True)
            return 0
        finally:
            db.close()

        if not all_rows:
            return 0

        # 按 canonical_rjcode 分组，每条 canonical 对应链上所有 link rows
        rows_by_canonical: Dict[str, List[Any]] = {}
        for row in all_rows:
            canonical = self.normalize_rjcode(getattr(row, "canonical_rjcode", "") or "")
            if not canonical:
                continue
            rows_by_canonical.setdefault(canonical, []).append(row)

        warmed = 0
        for canonical, rows in rows_by_canonical.items():
            # 实际 canonical 可能因 link_type='original' 不在 canonical_rjcode 字段里
            # （DLsite 关联链解析存在 BUG 时段），用 _select_canonical 重新计算保持与
            # ``resolve_canonical_rj`` 完全一致的语义。
            actual_canonical = _select_canonical(rows, canonical)
            linked = sorted({
                self.normalize_rjcode(row.linked_rjcode) for row in rows
                if self.normalize_rjcode(row.linked_rjcode)
            }, key=_rj_sort_key)
            payload = {
                "canonical_rjcode": actual_canonical,
                "linked_rjcodes": linked,
                "link_map": {
                    self.normalize_rjcode(row.linked_rjcode): {
                        "link_type": row.link_type,
                        "lang": row.lang,
                        "evidence_source": row.evidence_source or "",
                        "evidence_status": row.evidence_status or "unverified",
                    }
                    for row in rows
                    if self.normalize_rjcode(row.linked_rjcode)
                },
                "evidence_status": "verified",
            }
            # 链路上每个 RJ 共享同一份 payload（与 resolve_canonical_rj 写 cache 时一致）
            for linked_rj in linked or [actual_canonical]:
                if linked_rj and linked_rj not in self._canonical_cache:
                    self._canonical_cache[linked_rj] = payload
                    warmed += 1
        return warmed

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

        def _rj_sort_key(value: Any) -> tuple[int, str]:
            normalized = self.normalize_rjcode(value)
            match = re.search(r"RJ(\d+)", normalized)
            return (int(match.group(1)) if match else 10**12, normalized)

        def _select_canonical_from_link_rows(rows: List[Any], fallback_rj: str) -> str:
            """从一组关联链里选稳定 canonical。

            DLsite 关联链偶尔会把日文原作标成 ``translation/JPN``，只认
            ``link_type == original`` 会让同一作品的原作 / 简中 / 繁中拆成多条。
            选择顺序固定为：original > JPN > 最小 RJ，保证缺 original 标记时仍能
            全链路折到同一个 canonical。
            """
            normalized_fallback = self.normalize_rjcode(fallback_rj)
            candidates = []
            for row in rows:
                if isinstance(row, dict):
                    linked_rjcode = row.get("linked_rjcode")
                    link_type = row.get("link_type")
                    lang = row.get("lang")
                else:
                    linked_rjcode = getattr(row, "linked_rjcode", "")
                    link_type = getattr(row, "link_type", "")
                    lang = getattr(row, "lang", "")
                candidates.append({
                    "rjcode": self.normalize_rjcode(linked_rjcode),
                    "link_type": str(link_type or "").strip().lower(),
                    "lang": self._normalize_lang_code(lang),
                })
            candidates = [item for item in candidates if item["rjcode"]]
            original = [item["rjcode"] for item in candidates if item["link_type"] == "original"]
            if original:
                return sorted(original, key=_rj_sort_key)[0]
            jpn = [item["rjcode"] for item in candidates if item["lang"] in {"JPN", "JA", "JP"}]
            if jpn:
                return sorted(jpn, key=_rj_sort_key)[0]
            all_codes = [item["rjcode"] for item in candidates]
            if all_codes:
                return sorted(all_codes, key=_rj_sort_key)[0]
            return normalized_fallback

        def build_canonical_payload(rows: List[Any], fallback_rj: str) -> Dict[str, Any]:
            canonical = _select_canonical_from_link_rows(rows, fallback_rj)
            linked = sorted({self.normalize_rjcode(row.linked_rjcode) for row in rows if self.normalize_rjcode(row.linked_rjcode)}, key=_rj_sort_key)
            return {
                "canonical_rjcode": canonical,
                "linked_rjcodes": linked,
                "link_map": {
                    self.normalize_rjcode(row.linked_rjcode): {
                        "link_type": row.link_type,
                        "lang": row.lang,
                        "evidence_source": row.evidence_source or "",
                        "evidence_status": row.evidence_status or "unverified",
                    }
                    for row in rows
                    if self.normalize_rjcode(row.linked_rjcode)
                },
                "evidence_status": "verified",
            }

        # ⚠ 性能优化：buffered 模式下（wave1 批量场景）跳过 Block 1 的 DB SELECT。
        # 进入 buffered 模式的调用方典型语义是"强刷场景，cached_rows 反正不用"或
        # "wave1 预热已经填好 memory cache"，多查一次 DB 只是同步阻塞 event loop。
        # 非 buffered 路径保持原行为：先看 DB cache，命中且非强刷时短路 return。
        cached_rows: List[Any] = []
        if self._canonical_write_buffer is None:
            db = SessionLocal()
            try:
                cached_rows = (
                    db.query(WorkCanonicalLink)
                    .filter(
                        WorkCanonicalLink.evidence_status == "verified",
                        (WorkCanonicalLink.linked_rjcode == normalized_rj)
                        | (WorkCanonicalLink.canonical_rjcode == normalized_rj)
                    )
                    .all()
                )
                if cached_rows and not refresh:
                    # 从翻译版 RJ 反查时，上面的条件通常只命中
                    # ``canonical=原作, linked=当前翻译版`` 这一行。若直接用这
                    # 一行构造 payload，会因为看不到原作自身的 JPN 行而把翻译版
                    # 自己误判成 canonical。先按已命中的 canonical 扩回完整关联链。
                    cached_canonicals = {
                        self.normalize_rjcode(row.canonical_rjcode)
                        for row in cached_rows
                        if self.normalize_rjcode(row.canonical_rjcode)
                    }
                    if cached_canonicals and any(
                        self.normalize_rjcode(row.canonical_rjcode) != normalized_rj
                        for row in cached_rows
                    ):
                        cached_rows = (
                            db.query(WorkCanonicalLink)
                            .filter(
                                WorkCanonicalLink.evidence_status == "verified",
                                WorkCanonicalLink.canonical_rjcode.in_(cached_canonicals),
                            )
                            .all()
                        )
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
            # ★ 把 refresh 透传给 dlsite_service：``force_refresh=True`` 路径必须能
            # 绕开 dlsite_service 自己的 24h ``self.cache[linked_works:...]``，否则
            # 旧版本里因为 ``_get_direct_linked_works`` is_parent/is_child 分支的覆盖
            # BUG 写进去的关联链会持续误导 canonical 解析（24h 内同一 RJ 永远拿到
            # 错误的 link_map），用户感受不到代码修复。
            linked_map = await self.dlsite_service.get_linked_works(normalized_rj, refresh=refresh)
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
                evidence_source = str(
                    getattr(linked_work, "evidence_source", "") or "unknown"
                ).strip()
                evidence_status = str(
                    getattr(linked_work, "evidence_status", "") or "unverified"
                ).strip().lower()
                if evidence_status != "verified":
                    continue
                if work_type == "original":
                    canonical_rjcode = linked_rj_norm
                link_rows.append({
                    "linked_rjcode": linked_rj_norm,
                    "link_type": work_type,
                    "lang": lang,
                    "evidence_source": evidence_source,
                    "evidence_status": evidence_status,
                })
            canonical_rjcode = _select_canonical_from_link_rows(link_rows, canonical_rjcode)
        degraded_refresh = bool(refresh and len(link_rows) <= 1 and canonical_rjcode == normalized_rj)
        if degraded_refresh and cached_rows:
            cached_payload = build_canonical_payload(cached_rows, normalized_rj)
            cached_canonical = self.normalize_rjcode(cached_payload.get("canonical_rjcode"))
            if cached_canonical and cached_canonical != normalized_rj:
                try:
                    # 走的是 force_refresh=True 兜底路径，DLsite 端 cache 也要一起强刷，
                    # 避免拿到旧 BUG 时段写入的 ``linked_works:`` 缓存。
                    recovered_linked_map = await self.dlsite_service.get_linked_works(cached_canonical, refresh=refresh)
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
                        evidence_source = str(
                            getattr(linked_work, "evidence_source", "") or "unknown"
                        ).strip()
                        evidence_status = str(
                            getattr(linked_work, "evidence_status", "") or "unverified"
                        ).strip().lower()
                        if evidence_status != "verified":
                            continue
                        if work_type == "original":
                            recovered_canonical = linked_rj_norm
                        recovered_rows.append({
                            "linked_rjcode": linked_rj_norm,
                            "link_type": work_type,
                            "lang": lang,
                            "evidence_source": evidence_source,
                            "evidence_status": evidence_status,
                        })
                    if recovered_rows:
                        link_rows = recovered_rows
                        canonical_rjcode = recovered_canonical
        if not link_rows:
            payload = {
                "canonical_rjcode": normalized_rj,
                "linked_rjcodes": [normalized_rj],
                "link_map": {
                    normalized_rj: {
                        "link_type": "self",
                        "lang": "",
                        "evidence_source": "unknown",
                        "evidence_status": "unverified",
                    }
                },
                "evidence_status": "unverified",
                "evidence_reason": "DLsite 关联链缺少已验证证据",
            }
            self._canonical_cache[normalized_rj] = payload
            return payload

        # ⚠ 性能优化：buffered 模式下跳过 Block 2 的 overlap SELECT。
        # 该 SELECT 的目的是"如果别的链路也包含这些 RJ，合并 link_rows 以避免误删"，
        # 但 buffered 模式下 ``_flush_canonical_write_buffer`` 一次性 DELETE 所有
        # 相关 canonical / linked，再统一 INSERT，逻辑上等价。同时 wave1 批量场景里
        # 多个 RJ 解析同一 chain 时本来就会算出一致的 link_rows，overlap 合并的收益微乎其微。
        if self._canonical_write_buffer is None:
            db = SessionLocal()
            try:
                overlap_codes = [row["linked_rjcode"] for row in link_rows if row.get("linked_rjcode")]
                if overlap_codes:
                    existing_overlap_rows = (
                        db.query(WorkCanonicalLink)
                        .filter(
                            WorkCanonicalLink.evidence_status == "verified",
                            (WorkCanonicalLink.linked_rjcode.in_(overlap_codes))
                            | (WorkCanonicalLink.canonical_rjcode.in_(overlap_codes))
                        )
                        .all()
                    )
                    if existing_overlap_rows:
                        merged_by_rj: Dict[str, Dict[str, str]] = {
                            row["linked_rjcode"]: dict(row)
                            for row in link_rows
                            if row.get("linked_rjcode")
                        }
                        for existing in existing_overlap_rows:
                            linked = self.normalize_rjcode(existing.linked_rjcode)
                            if not linked:
                                continue
                            current = merged_by_rj.get(linked)
                            if current is None or current.get("link_type") in {"self", "unknown"}:
                                merged_by_rj[linked] = {
                                    "linked_rjcode": linked,
                                    "link_type": str(existing.link_type or ""),
                                    "lang": str(existing.lang or ""),
                                    "evidence_source": str(existing.evidence_source or ""),
                                    "evidence_status": str(existing.evidence_status or ""),
                                }
                        link_rows = list(merged_by_rj.values())
                        canonical_rjcode = _select_canonical_from_link_rows(link_rows, canonical_rjcode)
            finally:
                db.close()

        # ⚠ 性能优化：buffered 模式下把 Block 3 的 DELETE + INSERT + COMMIT
        # append 到 ``_canonical_write_buffer``，由 ``_flush_canonical_write_buffer``
        # 在 wave1 结束后一次批量落库。数据库写入只串行 1 次而不是 587 次，
        # 同时同步代码不再独占 event loop，wave1_sem=20 才能真正发挥 20 并发。
        if self._canonical_write_buffer is not None:
            self._canonical_write_buffer.append((canonical_rjcode, list(link_rows)))
        else:
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
                        evidence_source=row.get("evidence_source") or "unknown",
                        evidence_status=row.get("evidence_status") or "unverified",
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
                    "evidence_source": row.get("evidence_source") or "",
                    "evidence_status": row.get("evidence_status") or "unverified",
                }
                for row in link_rows
            },
            "evidence_status": "verified",
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
        def _is_placeholder_metadata(payload: Any) -> bool:
            if not isinstance(payload, dict) or not payload:
                return True
            title = str(payload.get("work_name") or payload.get("title") or "").strip()
            tags = self._extract_text_values(payload.get("tags"))
            categories: List[str] = []
            for key in ("work_type", "work_category", "category", "category_name", "genre", "genre_name", "file_type", "file_format"):
                categories.extend(self._extract_text_values(payload.get(key)))
            title_lower = title.lower()
            looks_like_announce_stub = (
                ("予告作品" in title or "预告作品" in title or "announcement" in title_lower)
                and not str(payload.get("release_date") or "").strip()
                and not tags
                and not categories
            )
            return (
                (
                    title.upper() == normalized_rj
                    and not str(payload.get("maker_name") or "").strip()
                    and not str(payload.get("release_date") or "").strip()
                    and not str(payload.get("cover_url") or "").strip()
                )
                or looks_like_announce_stub
            )
        if refresh:
            self._metadata_cache.pop(normalized_rj, None)
        cached_metadata = self._metadata_cache.get(normalized_rj)
        if not refresh and cached_metadata is not None and not _is_placeholder_metadata(cached_metadata):
            return cached_metadata

        # ⚠ 性能修复：单飞锁。N 个 candidate 同时 await 同一个 canonical 的 metadata
        # 时，让首个进入的 task 负责真实 fetch，其他全部 await 同一份 Future。
        # 这是 ``stage_prepare_candidates`` 16 分钟降到 ~2 分钟的关键改动。
        # ``refresh=True`` 跳过 inflight 复用，因为调用方明确要求重新拉。
        if not refresh:
            existing = self._metadata_inflight.get(normalized_rj)
            if existing is not None and not existing.done():
                return await existing

        future: Optional[asyncio.Future] = None
        if not refresh:
            try:
                # ``_fetch_metadata_dict`` 一定在协程中被调用，``get_running_loop`` 永远可用，
                # 且避开 Python 3.12 ``get_event_loop`` 在无 running loop 时的 deprecation 警告。
                future = asyncio.get_running_loop().create_future()
                self._metadata_inflight[normalized_rj] = future
            except Exception:
                future = None

        try:
            if not refresh:
                db = SessionLocal()
                try:
                    cached = db.query(WorkMetadata).filter(WorkMetadata.rjcode == normalized_rj).first()
                    if cached:
                        payload = cached.to_dict()
                        if not _is_placeholder_metadata(payload):
                            self._metadata_cache[normalized_rj] = payload
                            if future is not None and not future.done():
                                future.set_result(payload)
                            return payload
                finally:
                    db.close()
            fake_task = type("FakeTask", (), {"task_metadata": {"rjcode": normalized_rj}, "rjcode": normalized_rj, "update_progress": lambda *args, **kwargs: None})()
            payload = await self.metadata_service.fetch(normalized_rj, fake_task, force_refresh=refresh)
            self._metadata_cache[normalized_rj] = dict(payload or {})
            if future is not None and not future.done():
                future.set_result(self._metadata_cache[normalized_rj])
            return self._metadata_cache[normalized_rj]
        except Exception as exc:
            if future is not None and not future.done():
                future.set_exception(exc)
            raise
        finally:
            # 不管成功失败，立刻清出 inflight，让下一波调用可以重走 cache 检查路径。
            if future is not None and self._metadata_inflight.get(normalized_rj) is future:
                self._metadata_inflight.pop(normalized_rj, None)

    async def _collect_external_snapshot(
        self,
        candidate_rjcodes: List[str],
        *,
        force_refresh: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
        perf: Optional[CircleIndexPerfTracker] = None,
    ) -> CircleCompletionSnapshot:
        """Phase 1：一次性批量预取所有外部数据，Phase 2 纯本地聚合不再触网。

        分两波并发：

        - **Wave 1** —— DLsite 作品资料 + 作品链路（canonical）：
          ``self._fetch_metadata_dict(rj)`` + ``self.resolve_canonical_rj(rj)``
          覆盖所有候选 RJ。同时把每个候选的"原版 + 全部翻译/重制版 RJ"展开
          出来，得到 ``all_rjcodes``（候选 ∪ 链上其它语言版本）。

        - **Wave 2** —— **两组并发同时跑**：

          - **Wave 2a / ASMR.one 核对**：对 ``all_rjcodes`` 里每个 RJ 拉
            ``fetch_work_info`` + ``fetch_track_list``。ASMR.one 没有内部 cache，
            必须自建 snapshot；写入 ``snapshot.asmr_*_by_rj``。
          - 本地拥有 / 字幕状态由 ready 库存索引在聚合阶段批量投影，不在这里打
            Kikoeru HTTP，也不触发扫盘 fallback。

        关键参数：

        - ``force_refresh`` 透传给 DLsite / ASMR.one 刷新逻辑；库存索引始终是本地
          状态权威源，不受强刷影响。
        - ``progress_callback(percent, step)`` 用业务文案细粒度回报给主流程；
          不传则静默跑。
        - ``cancel_callback`` 在每轮 gather 之前轮询，用户主动取消时立刻 raise
          ``CancelledError``，避免 prefetch 跑完才退出。
        """
        snapshot = CircleCompletionSnapshot()

        def ensure_not_cancelled() -> None:
            if cancel_callback and cancel_callback():
                raise asyncio.CancelledError()

        def safe_progress(pct: int, step: str) -> None:
            if not progress_callback:
                return
            try:
                progress_callback(max(0, min(100, int(pct))), step)
            except Exception:
                logger.debug("[社团补全·snapshot] progress_callback 异常", exc_info=True)

        # 去重 candidate_rjcodes（保留输入顺序）
        seen: Set[str] = set()
        for rj in candidate_rjcodes or []:
            normalized = self.normalize_rjcode(rj)
            if normalized and normalized not in seen:
                seen.add(normalized)
                snapshot.candidate_rjcodes.append(normalized)

        if not snapshot.candidate_rjcodes:
            snapshot.all_rjcodes = []
            return snapshot

        ensure_not_cancelled()

        # ============ Wave 1：解析作品链路 ============
        # ★ P2 优化：本阶段**只**解析关联链（``resolve_canonical_rj``，内部仅拉
        #   ``product.json`` API 拿 ``translation_info``），不再 prefetch
        #   完整 metadata（含 ``product/info/ajax`` 特典字段）。
        #
        # 历史现场：旧实现给每个 candidate 同时拉 ``_fetch_metadata_dict(candidate)``
        # 和 ``_fetch_metadata_dict(canonical)``，每次 metadata fetch 涉及
        # ``product.json`` + ``product/info/ajax`` 两次外部 API。一个简中翻译版被作为
        # candidate、原作 + 繁中也都进 candidate 池时，会对原作 metadata 拉 3 次（每个
        # candidate 都把它当 canonical 拉一遍），尽管 cache 命中也徒增 inflight 抖动。
        #
        # 新实现：candidate 自己 / canonical 的 metadata 都不在 wave 1 拉。
        # ``prepare_candidate`` 阶段按需对 **canonical + preferred** 两条 RJ 拉完整
        # metadata（candidate 本身的 metadata 完全不拉，``_classify_asmr_work_candidate``
        # 用 ``product.json`` cache 兜底，wave 1 已经热好；``_candidate_belongs_to_identity``
        # 用 canonical_metadata 的 maker_name 校验，依然有效）。这样翻译版只要不是 preferred，
        # 它的 ``product/info/ajax`` 一次都不会被打——和"只对最终保留的最优作品做完整爬取"
        # 的设计意图严格对齐。
        wave1_sem = asyncio.Semaphore(20)

        # ⚠ 性能优化 P1：wave1 启动前一次性批量预热 ``_canonical_cache``。
        # 旧实现 587 RJ 各自同步开 ``SessionLocal()`` 查 ``WorkCanonicalLink``，
        # 即使 force_refresh=True 也会跑 Block 1 SELECT 然后丢弃结果，纯属浪费。
        # 这里改为一次性 ``WHERE linked_rjcode IN (...) OR canonical_rjcode IN (...)``
        # 把所有相关行批量拉出来灌进 memory cache。新社团首次索引时 DB 空，方法返回 0 无副作用。
        # 即使 force_refresh=True 也跑：``WorkCanonicalLink`` 是 DLsite 关联链解析结果的
        # 持久化，跟 ``dlsite_service`` 内部的 24h HTTP cache 是两个层，强刷语义针对的是后者。
        prewarm_ctx = perf.timed("stage_snapshot_wave1_prewarm_canonical") if perf else contextlib.nullcontext()
        with prewarm_ctx:
            warmed = await asyncio.to_thread(
                self._prewarm_canonical_cache_from_db, snapshot.candidate_rjcodes
            )
        if perf:
            perf.inc("wave1_canonical_cache_prewarmed", warmed)
        logger.info(
            "[社团补全·snapshot] wave1 批量预热 _canonical_cache: rj=%d cache_warmed=%d force_refresh=%s",
            len(snapshot.candidate_rjcodes), warmed, force_refresh,
        )

        async def prefetch_dlsite(rj: str) -> Tuple[str, str, Set[str], Dict[str, Any]]:
            """返回 ``(原始 rj, canonical rj, 链上所有 rj 的集合, canonical_info)``。

            内部把所有异常吞掉、回 fallback 值（canonical=rj 自身），保证
            上游聚合阶段不需要再处理 BaseException 分支。

            ★ 性能：进入 wave1_sem 之前先看 ``_canonical_cache``（预热已填）。
            memory 命中直接 return，跳过 sem 排队 + HTTP + DB IO。新社团首次索引时
            cache 是空的，这条 fast-path 不命中，正常进入 ``resolve_canonical_rj``
            走 DLsite HTTP；但 buffered 模式下 DB writes 已被合并，sem 真并发。
            """
            cached_payload = self._canonical_cache.get(rj) if not force_refresh else None
            if cached_payload is not None:
                canonical = self.normalize_rjcode(cached_payload.get("canonical_rjcode")) or rj
                related: Set[str] = {rj, canonical}
                for code in cached_payload.get("linked_rjcodes") or []:
                    norm = self.normalize_rjcode(code)
                    if norm:
                        related.add(norm)
                if perf:
                    perf.inc("wave1_chain_memory_hits")
                return rj, canonical, related, cached_payload

            related = {rj}
            canonical = rj
            canonical_info: Dict[str, Any] = {}
            async with wave1_sem:
                chain_t0 = time.monotonic()
                try:
                    canonical_info = await self.resolve_canonical_rj(rj, refresh=force_refresh) or {}
                except Exception:
                    logger.debug("[社团补全·snapshot] resolve_canonical_rj 失败 rj=%s", rj, exc_info=True)
                chain_ms = int((time.monotonic() - chain_t0) * 1000)
                if perf:
                    perf.inc("wave1_chain_count")
                    perf.inc("wave1_chain_total_ms", chain_ms)
                    if chain_ms > 5000:
                        perf.inc("wave1_chain_slow_gt_5s")
                    if chain_ms > 15000:
                        perf.inc("wave1_chain_slow_gt_15s")
                canonical = self.normalize_rjcode(canonical_info.get("canonical_rjcode")) or rj
                related.add(canonical)
                for code in canonical_info.get("linked_rjcodes") or []:
                    norm = self.normalize_rjcode(code)
                    if norm:
                        related.add(norm)
            return rj, canonical, related, canonical_info

        wave1_total = len(snapshot.candidate_rjcodes)
        safe_progress(
            0,
            f"解析 DLsite 作品关联链 0/{wave1_total} 件",
        )

        # ⚠ UX 修复：旧实现用 ``asyncio.gather``，所有 RJ 一起跑、整体完成才返回，
        # progress 在 587 个 RJ 跑完前永远卡在 "0/587"，用户以为系统卡死。实际是
        # 并发的（wave1_sem=20）但前端看不到进度。改成 ``asyncio.as_completed``，
        # 每完成一个立刻推进 progress（按 done/total × 50 缩放，因为 wave1 只占 snapshot
        # 阶段的 0-50 段）。
        wave1_raw: List[Any] = []
        wave1_done = 0
        wave1_tasks = [
            asyncio.ensure_future(prefetch_dlsite(rj))
            for rj in snapshot.candidate_rjcodes
        ]
        # ⚠ 性能诊断：分别记录 wave1 / wave2a / wave2b 耗时，定位 stage_external_snapshot
        # 内部的真实瓶颈。perf 的 stage_ms 用 timed 包装即可。
        # ⚠ 性能优化 P2：把整段 wave1 包进 ``_canonical_buffered_writes`` 上下文。
        # ``resolve_canonical_rj`` 内部检测到 buffered 模式时，所有 ``WorkCanonicalLink``
        # 的 DELETE/INSERT/COMMIT 不再每 RJ 立即提交，而是 append 到 buffer，
        # with 退出时一次批量落库。587 次数据库写入串行 → 1 次，
        # 同步 DB IO 不再独占 event loop，wave1_sem=20 才能真正发挥 20 并发。
        wave1_ctx = perf.timed("stage_snapshot_wave1_dlsite_chains") if perf else contextlib.nullcontext()
        with self._canonical_buffered_writes():
            with wave1_ctx:
                try:
                    for future in asyncio.as_completed(wave1_tasks):
                        ensure_not_cancelled()
                        try:
                            result = await future
                        except BaseException as exc:  # 与原 gather(return_exceptions=True) 等价
                            result = exc
                        wave1_raw.append(result)
                        wave1_done += 1
                        # 节流：每 5 个或最后一个才推 progress，避免 SSE 通道刷爆
                        if wave1_done % 5 == 0 or wave1_done == wave1_total:
                            safe_progress(
                                int(wave1_done / max(1, wave1_total) * 50),
                                f"解析 DLsite 作品关联链 {wave1_done}/{wave1_total} 件",
                            )
                except asyncio.CancelledError:
                    for task in wave1_tasks:
                        if not task.done():
                            task.cancel()
                    raise

            # 记录批量 flush 大小（with 块退出时 _canonical_buffered_writes 才真正 flush）
            if perf and self._canonical_write_buffer is not None:
                perf.inc("wave1_canonical_writes_buffered", len(self._canonical_write_buffer))

        ensure_not_cancelled()

        # 组装：作品链路 canonical -> 链上全部 RJ
        canonical_to_chain: Dict[str, Set[str]] = {}
        rj_to_canonical: Dict[str, str] = {}
        canonical_info_by_canonical: Dict[str, Dict[str, Any]] = {}
        for result in wave1_raw:
            if isinstance(result, BaseException):
                logger.debug("[社团补全·snapshot] Wave 1 任务抛异常: %s", result)
                continue
            rj, canonical, related, canonical_info = result
            canonical_to_chain.setdefault(canonical, set()).update(related)
            canonical_to_chain[canonical].add(canonical)
            rj_to_canonical[rj] = canonical
            for member in related:
                # 链上其它 RJ 也回填到映射里，方便 Phase 2 / 调试
                rj_to_canonical.setdefault(member, canonical)
            # 记录每条 canonical 的 link_map：用现有最完整的（含更多 link_map 条目的）
            # 覆盖之前的，避免某个 candidate 拉到的关联链不全时被覆盖。
            existing_info = canonical_info_by_canonical.get(canonical) or {}
            existing_links = existing_info.get("link_map") if isinstance(existing_info.get("link_map"), dict) else {}
            new_links = canonical_info.get("link_map") if isinstance(canonical_info.get("link_map"), dict) else {}
            if not existing_info or len(new_links or {}) > len(existing_links or {}):
                canonical_info_by_canonical[canonical] = canonical_info or {}

        # 把 candidate 自身也兜底填进映射，避免 Wave 1 全军覆没时下游 KeyError
        for rj in snapshot.candidate_rjcodes:
            if rj not in rj_to_canonical:
                rj_to_canonical[rj] = rj
                canonical_to_chain.setdefault(rj, set()).add(rj)

        snapshot.canonical_rj_by_rj = dict(rj_to_canonical)
        snapshot.chain_rjs_by_canonical = {
            canonical: sorted(chain) for canonical, chain in canonical_to_chain.items()
        }
        snapshot.canonical_info_by_canonical = canonical_info_by_canonical

        # 全 RJ 集合 = 所有链路的并集
        all_rjcodes_set: Set[str] = set()
        for chain in canonical_to_chain.values():
            all_rjcodes_set.update(chain)
        all_rjcodes_set.update(snapshot.candidate_rjcodes)
        snapshot.all_rjcodes = sorted(all_rjcodes_set)

        unique_canonicals = sorted(canonical_to_chain.keys())

        safe_progress(
            50,
            f"展开翻译 / 重制版后共 {len(snapshot.all_rjcodes)} 个 RJ、"
            f"{len(unique_canonicals)} 条作品链路，开始核对 ASMR.one",
        )

        # ============ Wave 2a：ASMR.one 作品核对（按 canonical 链路去重 + preferred 优先 + 命中即停） ============
        # ASMR.one 的 ``fetch_work_info`` / ``fetch_track_list`` 没有内部 cache，
        # 这里把每条 canonical 链路按"简中 > 繁中 > 原作 > 其他"语言优先级排序，依次试到
        # 第一条同时拿到 work_info + tracks 的 RJ 即停。剩余的链上 RJ 不再打 ASMR.one。
        #
        # 历史现场：旧实现对 ``snapshot.all_rjcodes``（candidate ∪ 链上翻译版全集，典型
        # 30-50 个 RJ）每个都拉 work_info + tracks，单次社团补全 ASMR.one HTTP 调用量
        # 超过 60 次。绝大多数翻译版根本不会在 ASMR.one 上有资源，都是浪费请求；少数
        # 链路的 ASMR 命中也只关心"链路上是否任意一条能下载"——下游 ``_find_public_downloadable_work``
        # 也确实只取第一个命中的 RJ 作为 ``asmr_available_rjcode``。
        #
        # 新实现：每条链路按 ``link_map`` 排序选 preferred，命中即停。最差情况（preferred /
        # 翻译版全部 miss、最后只命中原作）的探测次数等于链路长度；正常情况只打 1-2 次。
        # 整体能压到链路数 ~= 10-15，比旧实现省 70-80% 的 ASMR.one HTTP。
        #
        # ⚠ 性能调优历史：
        # - 30（最初）：稳定但 322 件社团需 15 分钟（chain 内部串行 + ASMR.one 单次 5-10s）
        # - 64（一次尝试）：**触发 ASMR.one 限流 / connection pool 打爆**，单次社团索引超过
        #   1 小时还没出 snapshot 阶段（进度卡在 8%）。回退。
        # - 30（当前保守值）：维持原值，ASMR.one 稳定吞吐对外暴露的就是 ~30 并发上限。
        # 真正能进一步压榨的方向是：让 chain 内部 probe 并发（``probe_order`` 短列表内并发，
        # 命中即停），而不是无脑提升 chain-level 并发。如果未来要再优化，从这个方向走。
        wave2_asmr_sem = asyncio.Semaphore(30)
        asmr_completed = 0
        # 进度按链路推进而不是按 RJ，避免跳跃
        asmr_total = max(1, len(canonical_to_chain))

        # P5：snapshot 内局部 ASMR 探测去重 —— ASMR.one 没有持久 cache，但同一轮任务里
        # 同一个 RJ 出现在不同链路（边界情况）时不应该被请求两次。本地 dict + 锁即可，
        # **不**升级为跨任务的 self.* 缓存——ASMR.one 资源变动概率高，跨任务复用会
        # 让用户感觉"明明 ASMR.one 上有了，索引仍说没有"。
        asmr_probe_once: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[List[Any]]]] = {}
        asmr_probe_locks: Dict[str, asyncio.Lock] = {}

        async def probe_asmr_once(
            rjcode: str,
        ) -> Tuple[Optional[Dict[str, Any]], Optional[List[Any]]]:
            normalized = self.normalize_rjcode(rjcode)
            if not normalized:
                return None, None
            if normalized in asmr_probe_once:
                if perf:
                    perf.inc("asmr_probe_once_hits")
                return asmr_probe_once[normalized]
            lock = asmr_probe_locks.setdefault(normalized, asyncio.Lock())
            async with lock:
                if normalized in asmr_probe_once:
                    if perf:
                        perf.inc("asmr_probe_once_hits")
                    return asmr_probe_once[normalized]
                if perf:
                    perf.inc("asmr_probe_once_misses")
                    perf.inc("asmr_work_info_calls")
                # ⚠ 性能修复：``wave2_asmr_sem`` 移到这里（RJ-level 并发上限），
                # 配合 ``prefetch_asmr_chain`` 的 chain 内并发改造，sem 真正控制的就是
                # 同时打 ASMR.one 的请求数（≤ 30），不再是 chain 级并发数。
                work_info: Optional[Dict[str, Any]] = None
                tracks: Optional[List[Any]] = None
                async with wave2_asmr_sem:
                    try:
                        work_info = await self.asmr_service.fetch_work_info(normalized)
                    except Exception:
                        logger.debug("[社团补全·snapshot] ASMR fetch_work_info 失败 rj=%s", normalized, exc_info=True)
                    if work_info:
                        if perf:
                            perf.inc("asmr_track_list_calls")
                        try:
                            tracks = await self.asmr_service.fetch_track_list(normalized)
                        except Exception:
                            logger.debug("[社团补全·snapshot] ASMR fetch_track_list 失败 rj=%s", normalized, exc_info=True)
                asmr_probe_once[normalized] = (work_info, tracks)
                return work_info, tracks

        def _build_chain_probe_order(canonical: str, chain_rjs: Set[str]) -> List[str]:
            """按 ``link_map`` 排序得到这条链路上 ASMR.one 探测顺序。

            ``_sort_linked_variants`` 已经按"翻译版 > 原作"× "简中 > 繁中 > 其他 > 日文"
            的双键排序，第一项就是首选 preferred。链上未在 link_map 出现的 RJ
            （例如本地候选直接补进来、DLsite 关联链没列）按链路 sorted 顺序追加在末尾。
            """
            canonical_info = snapshot.canonical_info_by_canonical.get(canonical) or {}
            sorted_variants = self._sort_linked_variants(canonical_info, canonical)
            seen: Set[str] = set()
            order: List[str] = []
            for variant in sorted_variants:
                rj = self.normalize_rjcode(variant.get("rjcode"))
                if rj and rj in chain_rjs and rj not in seen:
                    order.append(rj)
                    seen.add(rj)
            for rj in sorted(chain_rjs):
                if rj and rj not in seen:
                    order.append(rj)
                    seen.add(rj)
            return order

        async def prefetch_asmr_chain(canonical: str) -> List[Tuple[str, Optional[Dict[str, Any]], Optional[List[Any]]]]:
            """对一条 canonical 链路按 preferred 优先级**串行**探 ASMR.one，命中即停。

            ⚠ 性能修复（27.80 分钟 → 预期 2-3 分钟）：旧实现在这里 ``async with wave2_asmr_sem``
            把 sem 锁在整个 chain 探测过程，导致 sem=30 实际限制的是 **chain 级并发**：
            150 条 chain / 30 = 5 批 × 平均 5.7 RJ × 1.94s/call = 55s/批 → 总 27.8 分钟。

            新实现：sem 已移到 ``probe_asmr_once`` 内部（RJ-level 并发上限），这里**不再**
            在 chain 层加 sem，让所有 chain（典型 150 个）真正并发起来；每个 chain 内仍
            **串行命中即停**，保留旧合约（preferred 命中后不再对原作 / 其他翻译版打 ASMR.one HTTP）。
            预期：
            - 命中（273/304 ≈ 89%）：每 chain 只打 1 次 ASMR.one ≈ 1.94s
            - miss（31/304）：每 chain 打满 ~5.7 RJ ≈ 11s
            - 上层 150 chain 同时跑，RJ-level sem=30 是真实瓶颈：
              总 calls ≈ 273×1 + 31×5.7 = 450 → 450 / 30 = 15 批 × 1.94s ≈ 30s（理论）
            实际受 ASMR.one 单次延时波动影响，预估 2-3 分钟稳定下限。
            """
            chain_rjs: Set[str] = set(canonical_to_chain.get(canonical) or {canonical})
            probe_order = _build_chain_probe_order(canonical, chain_rjs)
            results: List[Tuple[str, Optional[Dict[str, Any]], Optional[List[Any]]]] = []
            explored: Set[str] = set()
            chain_started = time.monotonic()
            for rj in probe_order:
                work_info, tracks = await probe_asmr_once(rj)
                results.append((rj, work_info, tracks))
                explored.add(rj)
                if work_info and tracks:
                    break
            chain_elapsed = time.monotonic() - chain_started
            # ⚠ 性能诊断：累计 chain 耗时分布，对比"理论 ≈ 链长 × 单 RJ 延时"与实际值。
            if perf:
                perf.inc("asmr_chain_total_ms", int(chain_elapsed * 1000))
                perf.inc("asmr_chain_total_count")
                if chain_elapsed > 10:
                    perf.inc("asmr_chain_slow_gt_10s")
                if chain_elapsed > 30:
                    perf.inc("asmr_chain_slow_gt_30s")
            # 链上没探过的 RJ 用 (None, None) 占位，让 snapshot.contains_asmr 兼容旧行为。
            for rj in chain_rjs:
                if rj not in explored:
                    results.append((rj, None, None))
            return results

        # 本地拥有 / 字幕态不在 snapshot 阶段触网，稍后统一从 ready 库存索引投影。
        asmr_futures = [prefetch_asmr_chain(c) for c in unique_canonicals]

        async def collect_asmr() -> None:
            nonlocal asmr_completed
            # ⚠ 性能诊断：单独计时 ASMR.one 链路核对耗时。
            wave2a_ctx = perf.timed("stage_snapshot_wave2a_asmr") if perf else contextlib.nullcontext()
            with wave2a_ctx:
                for future in asyncio.as_completed(asmr_futures):
                    ensure_not_cancelled()
                    try:
                        chain_results = await future
                    except Exception as exc:
                        logger.debug("[社团补全·snapshot] ASMR prefetch 任务异常: %s", exc)
                        asmr_completed += 1
                        continue
                    for rj, work_info, tracks in chain_results:
                        snapshot.asmr_work_info_by_rj[rj] = work_info
                        snapshot.asmr_tracks_by_rj[rj] = tracks
                    asmr_completed += 1
                    if asmr_completed % 3 == 0 or asmr_completed == asmr_total:
                        # snapshot 相对刻度：ASMR 占 50→75 段
                        safe_progress(
                            50 + int((asmr_completed / asmr_total) * 25),
                            f"在 ASMR.one 上核对作品链路 {asmr_completed}/{asmr_total} 条",
                        )

        await collect_asmr()

        ensure_not_cancelled()

        asmr_hits = sum(1 for v in snapshot.asmr_work_info_by_rj.values() if v)
        safe_progress(
            100,
            f"外部数据收集完成（候选 {len(snapshot.candidate_rjcodes)} 件 / "
            f"含翻译共 {len(snapshot.all_rjcodes)} 个 RJ / "
            f"ASMR 命中 {asmr_hits} 个 / 本地收录态稍后由库存索引核对）",
        )

        logger.info(
            "[社团补全·snapshot] 收集完成: candidates=%s all_rjs=%s "
            "local_owned_source=library_index asmr_hits=%s",
            len(snapshot.candidate_rjcodes),
            len(snapshot.all_rjcodes),
            asmr_hits,
        )

        return snapshot

    @staticmethod
    def _extract_dlsite_search_page_identity(text: Any) -> tuple[List[str], List[Dict[str, str]]]:
        """只从 DLsite 真实作品链接和 maker 链接提取候选，拒绝页面级 RJ 扫描。"""
        source = str(text or "")
        worknos: List[str] = []
        seen_worknos: Set[str] = set()
        for match in re.finditer(
            r"/(?:work|announce)/=/product_id/([RVB]J\d{6,8})\.html",
            source,
            re.IGNORECASE,
        ):
            workno = str(match.group(1) or "").strip().upper()
            if workno and workno not in seen_worknos:
                seen_worknos.add(workno)
                worknos.append(workno)

        makers: List[Dict[str, str]] = []
        seen_makers: Set[Tuple[str, str]] = set()
        maker_pattern = re.compile(
            r"<a\b[^>]*href=[\"'][^\"']*/circle/profile/=/maker_id/(RG\d+)\.html[^\"']*[\"'][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        for match in maker_pattern.finditer(source):
            maker_id = str(match.group(1) or "").strip().upper()
            maker_name = html.unescape(re.sub(r"<[^>]+>", "", match.group(2) or "")).strip()
            key = (maker_id, maker_name)
            if not maker_id or not maker_name or key in seen_makers:
                continue
            seen_makers.add(key)
            makers.append({"maker_id": maker_id, "maker_name": maker_name})
        return worknos, makers

    def _choose_dlsite_maker_identity(
        self,
        circle_query: str,
        maker_hits: List[Dict[str, str]],
    ) -> Dict[str, str]:
        """从结构化 maker 链接中选择唯一匹配身份；同名多 ID 时拒绝猜测。"""
        normalized_query = self.normalize_circle_name(circle_query)
        exact: Dict[str, str] = {}
        loose: Dict[str, str] = {}
        for item in maker_hits or []:
            maker_id = self._normalize_maker_id(item.get("maker_id"))
            maker_name = str(item.get("maker_name") or "").strip()
            if not maker_id or not re.fullmatch(r"RG\d+", maker_id, re.IGNORECASE):
                continue
            normalized_name = self.normalize_circle_name(maker_name)
            if normalized_query and normalized_name == normalized_query:
                exact[maker_id] = maker_name
            elif self._circle_name_loose_match(circle_query, maker_name):
                loose[maker_id] = maker_name

        matches = exact or loose
        if len(matches) > 1:
            raise ValueError(
                "DLsite 搜索到多个同名社团，无法自动确定 maker_id："
                + "、".join(sorted(matches))
            )
        if not matches:
            return {"maker_id": "", "maker_name": ""}
        maker_id, maker_name = next(iter(matches.items()))
        return {"maker_id": maker_id, "maker_name": maker_name}

    async def _search_dlsite_circle_works(
        self,
        keyword: str,
        max_pages: int = 2,
    ) -> tuple[List[str], str, List[Dict[str, str]]]:
        found: List[str] = []
        seen = set()
        maker_hits: List[Dict[str, str]] = []
        seen_makers: Set[Tuple[str, str]] = set()
        failure_reason = ""
        client = await self.dlsite_service._get_client()
        headers = self.dlsite_service._get_browser_headers()
        try:
            for page in range(1, max_pages + 1):
                suffix = "" if page == 1 else f"/page/{page}"
                url = f"{self.DL_SEARCH_URL.format(keyword=quote(keyword))}{suffix}"
                try:
                    # ★ 关键修复：禁止跟随重定向。DLsite 对越界关键字翻页（page=N 不存在）
                    #   会 301 到 /maniax/fsr/=/work_category/doujin（默认全站新作页面），
                    #   这个页面有几百个无关 RJ。跟随后 re.findall 会把整页 RJ 当成社团候选，
                    #   污染下游所有过滤逻辑。这里看到 3xx 就停，把 location 写进 failure_reason
                    #   方便排错。
                    response = await client.get(
                        url, headers=headers, timeout=12.0, follow_redirects=False
                    )
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = str(response.headers.get('location') or '').strip()
                        logger.info(
                            "[社团补全] DLsite 关键字搜索第 %s 页 %s 重定向到 %s，停止抓取防止污染 keyword=%s",
                            page,
                            response.status_code,
                            location or '?',
                            keyword,
                        )
                        if page == 1:
                            failure_reason = (
                                f"DLsite 关键字搜索首页 {response.status_code} 重定向到 "
                                f"{location or '未知地址'}，疑似关键字不被搜索引擎收录"
                            )
                        break
                    if response.status_code != 200:
                        if response.status_code == 404 and page > 1:
                            logger.info(
                                "[社团补全] DLsite 社团关键字搜索到第 %s 页返回 404，视为无更多分页 keyword=%s",
                                page,
                                keyword,
                            )
                            break
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
                matches, page_makers = self._extract_dlsite_search_page_identity(text)
                for item in page_makers:
                    key = (item["maker_id"], item["maker_name"])
                    if key not in seen_makers:
                        seen_makers.add(key)
                        maker_hits.append(item)
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
        return found, failure_reason, maker_hits

    async def _search_dlsite_announce_works(
        self,
        keyword: str,
        max_pages: int = 3,
    ) -> tuple[List[str], str, List[Dict[str, str]]]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return [], "", []
        found: List[str] = []
        seen: Set[str] = set()
        maker_hits: List[Dict[str, str]] = []
        seen_makers: Set[Tuple[str, str]] = set()
        failure_reason = ""
        client = await self.dlsite_service._get_client()
        headers = self.dlsite_service._get_browser_headers()
        encoded_keyword = quote(keyword)
        url_templates = [
            "https://www.dlsite.com/maniax/announce/list/day/=/keyword/{keyword}{page_suffix}",
            "https://www.dlsite.com/home-touch/announce/list/day?keyword={keyword}{page_query}",
        ]
        # ★ 关键修复 v2（用户复测：いっしんふらん 16 个真作品但抓到 115 个候选）：
        #   v1 修复只让单 template 在看到 redirect 时丢弃自己的 attempt_found，但**继续 try
        #   下一个 template**。实测下来 home-touch 域名（`home-touch/announce/list/day`）
        #   在 keyword 没命中时不返 301，直接 200 OK 返回 home-touch 端的全站新预告列表，
        #   ``re.findall(r"[RVB]J\d{6,8}", text)`` 把推荐位 / 广告位 / 最新预告里的 RJ
        #   全扫成"keyword 命中"，commit 到 found，污染 100+ 个伪候选。
        #
        #   新策略：**任一 template 出现 redirect_aborted，立即整个函数 abort 返空**。
        #   redirect 是 DLsite 给的强信号"keyword 在 announce 上 0 命中"，下一个 template
        #   跑出来的 200 OK 内容必然也是回退页污染，没有继续尝试的价值。announce keyword
        #   是辅助来源，社团原作 + 翻译版主要靠 maker_id profile + Kikoeru 直连覆盖，
        #   这里宁可漏抓也不能引入大量伪候选拖累 fetch_candidate 链路。
        any_redirect_aborted = False
        no_match_aborted = False
        for template_index, template in enumerate(url_templates):
            attempt_found: List[str] = []
            attempt_seen: Set[str] = set()
            redirect_aborted = False
            empty_streak = 0
            for page in range(1, max(1, int(max_pages)) + 1):
                page_suffix = "" if page == 1 else f"/page/{page}"
                page_query = "" if page == 1 else f"&page={page}"
                url = template.format(keyword=encoded_keyword, page_suffix=page_suffix, page_query=page_query)
                try:
                    response = await client.get(
                        url, headers=headers, timeout=12.0, follow_redirects=False
                    )
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = str(response.headers.get('location') or '').strip()
                        logger.info(
                            "[社团补全] DLsite 预告搜索第 %s 页 %s 重定向到 %s，"
                            "判定本次 keyword 命中无效，撤回 attempt_found %s 个 RJ keyword=%s url=%s",
                            page,
                            response.status_code,
                            location or '?',
                            len(attempt_found),
                            keyword,
                            url,
                        )
                        if not failure_reason:
                            failure_reason = (
                                f"DLsite 预告搜索第 {page} 页 {response.status_code} 重定向到 "
                                f"{location or '未知地址'}，判定 keyword 在 announce 上无真实匹配"
                            )
                        redirect_aborted = True
                        break
                    if response.status_code != 200:
                        failure_reason = f"DLsite 预告搜索返回 HTTP {response.status_code}（第 {page} 页）"
                        logger.warning("[社团补全] DLsite 预告搜索失败 keyword=%s page=%s status=%s url=%s", keyword, page, response.status_code, url)
                        break
                    page_worknos, page_makers = self._extract_dlsite_search_page_identity(response.text)
                    for item in page_makers:
                        key = (item["maker_id"], item["maker_name"])
                        if key not in seen_makers:
                            seen_makers.add(key)
                            maker_hits.append(item)
                    page_identity = self._choose_dlsite_maker_identity(keyword, page_makers)
                    matches = page_worknos if page_identity.get("maker_id") else []
                except ValueError:
                    raise
                except Exception as exc:
                    failure_reason = f"DLsite 预告搜索失败（第 {page} 页）: {str(exc)}"
                    logger.warning("[社团补全] DLsite 预告搜索异常 keyword=%s page=%s url=%s: %s", keyword, page, url, exc)
                    break

                new_count = 0
                for match in matches:
                    normalized = self.normalize_rjcode(match)
                    if normalized and normalized not in seen and normalized not in attempt_seen:
                        attempt_seen.add(normalized)
                        attempt_found.append(normalized)
                        new_count += 1
                if not matches:
                    if template_index == 0 and page == 1 and not attempt_found:
                        no_match_aborted = True
                    break
                if new_count == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0
                if empty_streak >= 2:
                    break
            if redirect_aborted:
                # 整个 attempt_found 当作污染丢弃，并**立即 abort 整个函数**：
                # redirect 是 DLsite 给的强信号"keyword 在 announce 上 0 命中"，
                # 下一个 template 跑出来的 200 OK 内容必然是回退页污染（home-touch
                # 域名实测不返 redirect、直接 200 + 全站新作列表），无价值。
                any_redirect_aborted = True
                break
            if no_match_aborted:
                break
            for rj in attempt_found:
                if rj not in seen:
                    seen.add(rj)
                    found.append(rj)
            if found:
                break
        return found, failure_reason, maker_hits

    async def _list_dlsite_maker_announce_worknos(self, maker_id: str, max_pages: int = 20) -> tuple[List[str], str]:
        normalized_maker_id = str(maker_id or "").strip().upper()
        if not normalized_maker_id:
            return [], ""
        client = await self.dlsite_service._get_client()
        headers = self.dlsite_service._get_browser_headers()
        found: List[str] = []
        seen: Set[str] = set()
        failure_reason = ""
        url_templates = [
            "https://www.dlsite.com/maniax/announce/=/maker_id/{maker_id}.html{page_suffix}",
            "https://www.dlsite.com/maniax/announce/=/maker_id/{maker_id}.html/options[0]/JPN{page_suffix}",
        ]
        for template in url_templates:
            empty_streak = 0
            for page in range(1, max(1, int(max_pages)) + 1):
                page_suffix = "" if page == 1 else f"/page/{page}"
                url = template.format(maker_id=normalized_maker_id, page_suffix=page_suffix)
                try:
                    # ★ 关键修复：禁止跟随重定向。maker 预告 URL 越界翻页或 maker_id 没有预告
                    #   作品时 DLsite 会 301，httpx 默认会被静默跟随到全站列表页，污染候选。
                    #   看到 3xx 立刻 break。
                    response = await client.get(
                        url, headers=headers, timeout=12.0, follow_redirects=False
                    )
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = str(response.headers.get('location') or '').strip()
                        logger.info(
                            "[社团补全] DLsite maker 预告页第 %s 页 %s 重定向到 %s，停止抓取防止污染 maker_id=%s url=%s",
                            page,
                            response.status_code,
                            location or '?',
                            normalized_maker_id,
                            url,
                        )
                        if page == 1 and not failure_reason:
                            failure_reason = (
                                f"DLsite maker 预告页 {response.status_code} 重定向到 "
                                f"{location or '未知地址'}，疑似 maker_id 无预告作品"
                            )
                        break
                    if response.status_code != 200:
                        if page == 1:
                            failure_reason = f"DLsite maker 预告页返回 HTTP {response.status_code}"
                        break
                    text = response.text or ""
                    matches = re.findall(r"/announce/=/product_id/([RVB]J(?:\d{8}|\d{6}))\.html", text, re.IGNORECASE)
                    if not matches:
                        matches = re.findall(r"product_id/([RVB]J(?:\d{8}|\d{6}))\.html", text, re.IGNORECASE)
                except Exception as exc:
                    failure_reason = f"DLsite maker 预告页抓取失败: {str(exc)}"
                    logger.warning("[社团补全] DLsite maker 预告页抓取异常 maker_id=%s page=%s url=%s: %s", normalized_maker_id, page, url, exc)
                    break

                new_count = 0
                for match in matches:
                    normalized = self.normalize_rjcode(match)
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        found.append(normalized)
                        new_count += 1
                if new_count == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0
                if empty_streak >= 2:
                    break
            if found:
                break
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
        sliced = seed_candidates[:total]

        async def _probe_one(index: int, item: Dict[str, Any]) -> Optional[Dict[str, str]]:
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                return None
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
                or self._circle_name_loose_match(circle_query, maker_name)
            ):
                return {"maker_id": maker_id, "maker_name": maker_name}
            return None

        sem = asyncio.Semaphore(6)

        async def _wrapped(index: int, item: Dict[str, Any]) -> Optional[Dict[str, str]]:
            async with sem:
                return await _probe_one(index, item)

        results = await asyncio.gather(*[_wrapped(i, item) for i, item in enumerate(sliced, start=1)])
        for res in results:
            if res:
                return res
        return {"maker_id": "", "maker_name": ""}

    async def _resolve_identity_from_candidates(
        self,
        circle_query: str,
        candidates: List[Dict[str, Any]],
        *,
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> Dict[str, str]:
        normalized_query = self.normalize_circle_name(circle_query)
        if not candidates:
            return {"maker_id": "", "maker_name": ""}

        preferred = next(
            (
                item
                for item in candidates
                if item.get("maker_id")
                and self._circle_name_loose_match(circle_query, item.get("maker_name"))
            ),
            None,
        )
        if preferred:
            return {
                "maker_id": str(preferred.get("maker_id") or "").strip(),
                "maker_name": str(preferred.get("maker_name") or "").strip(),
            }

        total = min(len(candidates), 16)
        sliced = candidates[:total]

        async def _probe_one(index: int, item: Dict[str, Any]) -> Optional[Dict[str, str]]:
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                return None
            try:
                metadata = await self._fetch_metadata_dict(rjcode)
            except Exception:
                metadata = {}
            maker_id = str(metadata.get("maker_id") or item.get("maker_id") or "").strip()
            maker_name = str(metadata.get("maker_name") or item.get("maker_name") or "").strip()
            if progress_callback and (index == 1 or index == total or index % 4 == 0):
                progress_callback(
                    56,
                    f"补查候选社团标识 {index}/{total}",
                    identity_probe_rjcode=rjcode,
                    identity_probe_maker_id=maker_id,
                )
            if maker_id and (
                not normalized_query
                or not maker_name
                or self._circle_name_loose_match(circle_query, maker_name)
            ):
                return {"maker_id": maker_id, "maker_name": maker_name}
            return None

        sem = asyncio.Semaphore(6)

        async def _wrapped(index: int, item: Dict[str, Any]) -> Optional[Dict[str, str]]:
            async with sem:
                return await _probe_one(index, item)

        results = await asyncio.gather(*[_wrapped(i, item) for i, item in enumerate(sliced, start=1)])
        for res in results:
            if res:
                return res
        return {"maker_id": "", "maker_name": ""}

    def _build_invalid_circle_query_hint(
        self,
        circle_query: str,
        *,
        local_candidates_count: int = 0,
        kikoeru_candidates_count: int = 0,
        dlsite_candidates_count: int = 0,
    ) -> str:
        if local_candidates_count or kikoeru_candidates_count or dlsite_candidates_count:
            return ""
        normalized_query = self.normalize_circle_name(circle_query)
        if not normalized_query:
            return ""
        return (
            "当前关键词更像作品关联名而不是社团名；"
            "如果这是翻译者名、汉化者名、配音名或角色名，"
            "DLsite 搜索会命中大量无关作品，无法建立有效社团目录。"
        )

    async def _collect_dlsite_circle_candidates(
        self,
        circle_query: str,
        maker_id: str = "",
        *,
        progress_callback: Optional[Callable[..., None]] = None,
        perf: Optional[CircleIndexPerfTracker] = None,
    ) -> List[Dict[str, Any]]:
        normalized_maker_id = str(maker_id or "").strip().upper()
        if not normalized_maker_id:
            normalized_query = self.normalize_circle_name(circle_query)
            db = SessionLocal()
            try:
                existing_catalog = self._find_catalog_by_normalized_name(db, normalized_query) if normalized_query else None
                if existing_catalog and re.match(r"^RG\d+$", str(existing_catalog.circle_id or "").strip(), re.IGNORECASE):
                    normalized_maker_id = str(existing_catalog.circle_id).strip().upper()
            finally:
                db.close()
        # P2：dlsite_summaries 取代旧的 dlsite_rjcodes —— 列表 HTML 解析出的 chip
        # 信息让 _classify_listing_summary_audio 在零外部 HTTP 的情况下就能把
        # manga/CG/RPG/视频类作品过滤掉。``is_probably_audio is None`` 的条目会在
        # fetch_candidate 中 fallback 到旧的 product/info/ajax 链路，行为完全兼容。
        dlsite_summaries: List[DLsiteWorkSummary] = []
        seen_rjcodes: Set[str] = set()
        # 只有直接来自 maker 主页的 RJ 码才是可信的，不需要二次校验社团名
        profile_rjcodes: Set[str] = set()
        source_mode = "keyword"
        failure_messages: List[str] = []
        keyword_rjcodes: List[str] = []
        keyword_failure_reason = ""
        keyword_maker_hits: List[Dict[str, str]] = []
        keyword_search_completed = False
        announce_rjcodes: List[str] = []
        announce_failure_reason = ""
        announce_maker_hits: List[Dict[str, str]] = []
        announce_search_completed = False
        maker_identity_source = "seed" if normalized_maker_id else ""

        def absorb_summary(summary: DLsiteWorkSummary, *, from_profile: bool) -> bool:
            workno = self.normalize_rjcode(summary.workno)
            if not workno or workno in seen_rjcodes:
                return False
            seen_rjcodes.add(workno)
            summary.workno = workno
            dlsite_summaries.append(summary)
            if from_profile:
                profile_rjcodes.add(workno)
            return True

        def absorb_rjcodes(rjcodes: List[str], *, from_profile: bool) -> int:
            added = 0
            for rj in rjcodes:
                normalized = self.normalize_rjcode(rj)
                if not normalized or normalized in seen_rjcodes:
                    continue
                if absorb_summary(DLsiteWorkSummary(workno=normalized), from_profile=from_profile):
                    added += 1
            return added

        # ★ profile_parse_status 用来区分两种"profile + announce 都返回 0"：
        #   - "empty"：DLsite 上 maker_id 真的没作品（多半是脏 maker_id），可以重置走关键字
        #   - "html_decode_failed" / "http_error"：抓取失败（典型现场是 brotlicffi 没装、
        #     代理被墙、临时 5xx），此时 **绝对不能** 重置 maker_id —— 否则下面
        #     fetch_candidate 的 maker_id 白名单失效，关键字搜索抓到的全站推荐位 RJ
        #     就会跨过过滤进入候选，导致"25 个作品的社团变 42 个候选"那种污染。
        profile_parse_status = "ok" if not normalized_maker_id else "skipped"

        if not normalized_maker_id:
            direct_maker_match = re.search(r"\b(RG\d+)\b", str(circle_query or ""), re.IGNORECASE)
            if direct_maker_match:
                normalized_maker_id = direct_maker_match.group(1).upper()
                maker_identity_source = "direct_query"
                source_mode = "direct_maker_id"

        if not normalized_maker_id:
            keyword_rjcodes, keyword_failure_reason, keyword_maker_hits = await self._search_dlsite_circle_works(circle_query)
            keyword_search_completed = True
            if keyword_failure_reason:
                failure_messages.append(keyword_failure_reason)
            keyword_identity = self._choose_dlsite_maker_identity(circle_query, keyword_maker_hits)
            if keyword_identity.get("maker_id"):
                normalized_maker_id = self._normalize_maker_id(keyword_identity["maker_id"])
                maker_identity_source = "keyword_search"
                source_mode = "keyword_identity"
                if progress_callback:
                    progress_callback(
                        42,
                        "已从 DLsite 作品搜索确认社团身份",
                        dlsite_maker_id=normalized_maker_id,
                        dlsite_maker_name=keyword_identity.get("maker_name") or "",
                        dlsite_identity_source=maker_identity_source,
                    )

        if not normalized_maker_id:
            announce_rjcodes, announce_failure_reason, announce_maker_hits = await self._search_dlsite_announce_works(circle_query)
            announce_search_completed = True
            if announce_failure_reason:
                failure_messages.append(announce_failure_reason)
            announce_identity = self._choose_dlsite_maker_identity(circle_query, announce_maker_hits)
            if announce_identity.get("maker_id"):
                normalized_maker_id = self._normalize_maker_id(announce_identity["maker_id"])
                maker_identity_source = "announce_search"
                source_mode = "announce_identity"
                if progress_callback:
                    progress_callback(
                        43,
                        "已从 DLsite 预告搜索确认社团身份",
                        dlsite_maker_id=normalized_maker_id,
                        dlsite_maker_name=announce_identity.get("maker_name") or "",
                        dlsite_identity_source=maker_identity_source,
                    )

        if (
            not normalized_maker_id
            and keyword_failure_reason
            and announce_failure_reason
            and not keyword_rjcodes
            and not announce_rjcodes
        ):
            raise ValueError("DLsite 社团搜索暂时不可用，无法验证社团身份，请稍后重试")

        if normalized_maker_id:
            try:
                profile_summaries, profile_parse_status = await self.dlsite_service.list_circle_work_summaries_by_maker(
                    normalized_maker_id, language="JPN"
                )
                if perf:
                    perf.inc("dlsite_summary_pages")
                source_mode = "maker_profile"
                for summary in profile_summaries:
                    absorb_summary(summary, from_profile=True)
                if progress_callback:
                    progress_callback(
                        44,
                        "已抓取 DLsite 社团主页原作与预告列表",
                        dlsite_profile_total=len(dlsite_summaries),
                        dlsite_maker_id=normalized_maker_id,
                        dlsite_source_mode=source_mode,
                        dlsite_failure_reason="",
                        dlsite_profile_parse_status=profile_parse_status,
                    )
            except Exception as exc:
                logger.warning("[社团补全] 按 maker_id 抓取 DLsite 社团主页失败 maker_id=%s", normalized_maker_id, exc_info=True)
                failure_messages.append(f"DLsite 社团主页抓取失败: {str(exc)}")
                profile_parse_status = "http_error"
                if progress_callback:
                    progress_callback(44, "DLsite 社团主页抓取失败，准备回退关键字搜索", dlsite_source_mode=source_mode, dlsite_failure_reason=" / ".join(failure_messages))

            maker_announce_rjcodes, maker_announce_failure = await self._list_dlsite_maker_announce_worknos(normalized_maker_id)
            if maker_announce_failure:
                failure_messages.append(maker_announce_failure)
            if maker_announce_rjcodes:
                added_count = absorb_rjcodes(maker_announce_rjcodes, from_profile=True)
                source_mode = f"{source_mode}+maker_announce"
                if progress_callback:
                    progress_callback(
                        45,
                        "已补充 DLsite maker 预告作品",
                        dlsite_maker_announce_total=len(maker_announce_rjcodes),
                        dlsite_maker_announce_added=added_count,
                        dlsite_profile_total=len(dlsite_summaries),
                        dlsite_maker_id=normalized_maker_id,
                        dlsite_source_mode=source_mode,
                        dlsite_failure_reason=" / ".join(failure_messages),
                    )

        if not dlsite_summaries:
            # ★ profile + maker_announce 都返回 0 时，需要区分两种本质不同的情况：
            #
            # (1) parse_status == "empty"：HTTP 都 200 + HTML 也是正常 DLsite 页面，但确实
            #     一个作品都没有。这种通常是 maker_id 脏了（典型现场：RG42470 的
            #     profile/options[0]/JPN 返回 200 但 0 作品，maker_announce 直接 404），
            #     继续保留 maker_id 会让 fetch_candidate 的 maker_id 白名单卡掉所有关键字
            #     候选，整个任务收 0。这种才主动重置 maker_id 退化到关键字模式。
            #
            # (2) parse_status == "html_decode_failed" / "http_error"：抓取失败，例如：
            #     - venv 缺 brotlicffi，DLsite 给 br 压缩响应 → response.text 是乱码
            #     - 代理被墙或临时 5xx
            #     这时 maker_id 大概率仍然有效，**保留它**！让下面 fetch_candidate 用
            #     maker_id 严格白名单卡过关键字搜索结果，避免全站推荐位 RJ 污染候选。
            should_reset_maker_id = bool(
                normalized_maker_id
                and profile_parse_status == "empty"
                and maker_identity_source not in {"keyword_search", "announce_search", "direct_query"}
            )
            if should_reset_maker_id:
                logger.warning(
                    "[社团补全] DLsite maker_id=%s profile 解析正常但作品列表为空（parse_status=%s），"
                    "疑似误识别，已重置为关键字模式，避免连锁误删关键字候选",
                    normalized_maker_id,
                    profile_parse_status,
                )
                failure_messages.append(
                    f"DLsite maker_id={normalized_maker_id} profile/announce 均 0 作品（HTML 健全），"
                    "已重置为关键字模式"
                )
                normalized_maker_id = ""
                if source_mode.startswith("maker_profile"):
                    source_mode = "keyword_after_stale_maker"
            elif normalized_maker_id:
                logger.warning(
                    "[社团补全] DLsite maker_id=%s profile/announce 抓取失败（parse_status=%s），"
                    "保留 maker_id 严格白名单走关键字 fallback，防止全站推荐位 RJ 污染候选；"
                    "若长期复现，请检查 backend venv 是否安装了 brotlicffi、HTTP 代理是否可达日本 IP",
                    normalized_maker_id,
                    profile_parse_status,
                )
                failure_messages.append(
                    f"DLsite maker_id={normalized_maker_id} profile 抓取失败（{profile_parse_status}），"
                    "保留 maker_id 白名单走关键字 fallback"
                )
                if source_mode.startswith("maker_profile"):
                    source_mode = "keyword_with_strict_maker"
            if not keyword_search_completed:
                keyword_rjcodes, keyword_failure_reason, keyword_maker_hits = await self._search_dlsite_circle_works(circle_query)
                keyword_search_completed = True
                if keyword_failure_reason:
                    failure_messages.append(keyword_failure_reason)
            absorb_rjcodes(keyword_rjcodes, from_profile=False)
            if announce_search_completed and normalized_maker_id:
                absorb_rjcodes(announce_rjcodes, from_profile=False)
            if progress_callback:
                progress_callback(
                    44,
                    "已回退关键字搜索 DLsite",
                    dlsite_profile_total=len(dlsite_summaries),
                    dlsite_source_mode=source_mode,
                    dlsite_failure_reason=" / ".join(failure_messages),
                )

        candidates: List[Dict[str, Any]] = []
        # ⚠ P2 回归修复：列表 chip 判 False 时**不再硬过滤**。
        # 之前的版本会把 ``is_probably_audio is False`` 直接 ``continue`` 跳过，
        # 但 ``_classify_listing_summary_audio`` 的"非音声判定常量集合"对 ETC / GAM /
        # 标题里出现"漫画/动画/CG"等关键词的纯音声特典会误杀，导致 RaRo 这种 322
        # 件作品社团索引出来只剩 ~200 件。
        #
        # 新策略：
        # - chip = True  → 加速路径：``get_product_info`` 轻量校验，跳过完整 metadata
        # - chip = False → **降级为弱信号 hint**，仍走完整 fallback；不丢作品
        # - chip = None  → 完整 fallback（旧行为）
        #
        # 性能上仍能享受 chip = True 的加速比，最差情况只是退回旧行为，绝不会丢作品。
        pre_filtered_summaries: List[DLsiteWorkSummary] = list(dlsite_summaries)
        listing_non_audio_hint = 0
        for summary in dlsite_summaries:
            if summary.is_probably_audio is False:
                listing_non_audio_hint += 1
                if perf:
                    perf.inc("dlsite_listing_non_audio_hint")
                logger.debug(
                    "[社团补全·summary] 列表层提示非音声（仅作 hint，仍走 metadata 校验）rj=%s reason=%s",
                    summary.workno, summary.classification_reason,
                )
        if perf:
            perf.inc("dlsite_summary_total_raw", len(dlsite_summaries))
            perf.inc(
                "dlsite_summary_audio_candidates",
                sum(1 for s in pre_filtered_summaries if s.is_probably_audio is True),
            )
            perf.inc(
                "dlsite_summary_unknown",
                sum(1 for s in pre_filtered_summaries if s.is_probably_audio is None),
            )
            perf.inc(
                "dlsite_summary_listing_non_audio_hint",
                listing_non_audio_hint,
            )

        if listing_non_audio_hint and progress_callback:
            progress_callback(
                45,
                f"列表层提示 {listing_non_audio_hint} 件可能非音声（仍走 metadata 校验）",
                dlsite_profile_total=len(dlsite_summaries),
                dlsite_listing_non_audio_hint=listing_non_audio_hint,
                dlsite_source_mode=source_mode,
                dlsite_failure_reason=" / ".join(failure_messages),
            )

        total_summaries = max(1, len(pre_filtered_summaries))
        semaphore = asyncio.Semaphore(10)

        async def fetch_candidate(summary: DLsiteWorkSummary) -> Optional[Dict[str, Any]]:
            rjcode = summary.workno
            is_from_profile = rjcode in profile_rjcodes
            listing_label = summary.is_probably_audio  # True / False / None
            async with semaphore:
                meta: Dict[str, Any]
                product_payload: Optional[Dict[str, Any]] = None

                if listing_label is True:
                    # 列表 chip 已经判定为音声。只做轻量 product.json 校验，
                    # 拿到 maker_id / maker_name 等关键字段；不走 _fetch_metadata_dict
                    # 的完整链路（含 product/info/ajax 特典字段）。
                    try:
                        product_info = await self.dlsite_service.get_product_info(rjcode)
                    except Exception:
                        product_info = None
                    product_payload = dict((product_info or {}).get("product") or {})
                    if perf:
                        perf.inc("dlsite_summary_light_verifications")
                    if product_payload:
                        image_main = product_payload.get("image_main") if isinstance(product_payload.get("image_main"), dict) else {}
                        cover_url = ""
                        if isinstance(image_main, dict):
                            cover_url = str(image_main.get("url") or "")
                        meta = {
                            "rjcode": rjcode,
                            "work_name": product_payload.get("work_name") or summary.title or "",
                            "maker_id": product_payload.get("maker_id") or summary.maker_id or "",
                            "maker_name": product_payload.get("maker_name") or summary.maker_name or "",
                            "cover_url": cover_url or summary.cover_url,
                            "price_text": product_payload.get("price") or "",
                            "release_date": product_payload.get("regist_date") or "",
                        }
                    else:
                        # product.json 失败：退化到旧的 metadata 链路，保留旧鲁棒性。
                        if perf:
                            perf.inc("dlsite_summary_light_verification_misses")
                        try:
                            meta = await self._fetch_metadata_dict(rjcode)
                        except Exception:
                            meta = {"rjcode": rjcode}
                else:
                    # listing_label is None（不确定）或 False（提示非音声但 hint 不可靠）：
                    # 都走旧完整链路，由 ``_is_non_audio_package_text`` + 下方
                    # ``_classify_asmr_work_candidate`` 兜底判定，避免漏作品。
                    if perf:
                        if listing_label is False:
                            perf.inc("dlsite_summary_fallback_after_non_audio_hint")
                        else:
                            perf.inc("dlsite_summary_fallback_full_metadata")
                    try:
                        meta = await self._fetch_metadata_dict(rjcode)
                    except Exception:
                        meta = {"rjcode": rjcode}
                    if self._is_non_audio_package_text(" ".join([
                        str(meta.get("work_name") or meta.get("title") or ""),
                        *self._extract_text_values(meta.get("tags")),
                        *self._extract_text_values(meta.get("work_category")),
                        *self._extract_text_values(meta.get("category")),
                        *self._extract_text_values(meta.get("file_format")),
                    ])):
                        if perf:
                            perf.inc("dlsite_non_audio_filtered_after_metadata")
                        return None
                    asmr_classification = await self._classify_asmr_work_candidate(rjcode, meta)
                    # maker 主页会列出同社团全部作品，游戏/漫画也在里面。不能因为
                    # 来源可信就放行；必须被 DLsite product 判成 SOU，或 metadata
                    # 自身有明确音声/ASMR 信号。
                    if asmr_classification is not True:
                        if perf:
                            perf.inc("dlsite_non_audio_filtered_after_metadata")
                        return None

            candidate_maker_id = self._normalize_maker_id(meta.get("maker_id") or summary.maker_id)
            if normalized_maker_id:
                if is_from_profile:
                    if candidate_maker_id and candidate_maker_id != normalized_maker_id:
                        return None
                else:
                    # 关键字/预告来源启用 maker_id 白名单：已识别到 maker_id 时，
                    # 候选必须携带且必须等于该 maker_id，缺失也直接丢弃。
                    if not candidate_maker_id or candidate_maker_id != normalized_maker_id:
                        return None
            maker_name = str(meta.get("maker_name") or summary.maker_name or "").strip()
            if not is_from_profile:
                # 关键字/预告搜索来源：必须校验社团名，防止不相关社团作品混入。
                # 用双向宽松匹配，避免 query 比 maker_name 长（如 Kikoeru 把系列名
                # 拼进社团名，而 DLsite 上是裸社团名）时所有作品都被误删。
                # 注意：maker_name 为空时，如果继续放行会把无效 RJ（页面404/元数据残缺）
                # 伪装成当前社团，导致列表混入大量无关作品。
                if not maker_name:
                    return None
                if not self._circle_name_loose_match(circle_query, maker_name):
                    return None
            release_date = str(meta.get("release_date") or "")
            return {
                "rjcode": rjcode,
                "title": meta.get("work_name") or summary.title or "",
                "maker_id": meta.get("maker_id") or summary.maker_id or normalized_maker_id or "",
                "maker_name": maker_name or circle_query,
                "price_text": meta.get("price_text") or "",
                "image_url": self._normalize_dlsite_cover_url(
                    meta.get("cover_url") or summary.cover_url,
                    rjcode,
                    is_unreleased=self._is_future_release_date(release_date),
                ),
                "source": "dlsite",
                "_asmr_checked": True,
                "_listing_label": listing_label,
                "_listing_reason": summary.classification_reason,
            }

        completed = 0
        futures = [fetch_candidate(summary) for summary in pre_filtered_summaries]
        for future in asyncio.as_completed(futures):
            candidate = await future
            completed += 1
            if candidate:
                candidates.append(candidate)
            if progress_callback and (completed == total_summaries or completed % 10 == 0):
                progress_callback(
                    44 + int((completed / total_summaries) * 8),
                    f"解析 DLsite 社团作品 {completed}/{total_summaries}",
                    dlsite_profile_total=len(dlsite_summaries),
                    dlsite_candidates_count=len(candidates),
                    dlsite_source_mode=source_mode,
                    dlsite_failure_reason=" / ".join(failure_messages),
                )
        return candidates

    async def _collect_local_circle_candidates(self, circle_query: str) -> List[Dict[str, Any]]:
        normalized = self.normalize_circle_name(circle_query)
        db = SessionLocal()
        try:
            from sqlalchemy import or_ as sa_or, func as sa_func
            query = db.query(WorkMetadata).filter(WorkMetadata.maker_name.isnot(None))
            if normalized:
                sql_terms = self._build_circle_name_sql_terms(circle_query)
                query = query.filter(sa_or(*[
                    sa_func.lower(WorkMetadata.maker_name).like(f"%{term}%")
                    for term in sql_terms
                ]))
            rows = query.all()
            results = []
            for row in rows:
                maker_name = str(row.maker_name or "").strip()
                maker_id = str(row.maker_id or "").strip()
                if normalized and not self._circle_name_loose_match(circle_query, maker_name):
                    continue
                metadata = row.to_dict()
                if not self._metadata_looks_like_asmr_work(metadata):
                    continue
                results.append({
                    "rjcode": self.normalize_rjcode(row.rjcode),
                    "title": row.work_name,
                    "maker_id": maker_id,
                    "maker_name": maker_name,
                    "price_text": metadata.get("price_text") or "",
                    "image_url": self._normalize_dlsite_cover_url(
                        row.cover_url,
                        row.rjcode,
                        is_unreleased=self._is_future_release_date(metadata.get("release_date")),
                    ),
                    "source": "local",
                })
            return results
        finally:
            db.close()

    # 本地拥有态全量重建的后台 TTL（秒）。它不能再阻塞单社团索引入口；
    # 入口只负责派发后台刷新，当前社团拥有态在写入前用 ready 库存索引局部核对。
    _LOCAL_OWNED_SYNC_TTL_SECONDS: float = 30 * 60

    def _is_local_owned_index_fresh(self) -> bool:
        last = float(self._local_owned_sync_state.get("last_completed_at") or 0.0)
        if last <= 0.0:
            return False
        return (time.monotonic() - last) < self._LOCAL_OWNED_SYNC_TTL_SECONDS

    def _schedule_local_owned_index_refresh(self) -> Optional[asyncio.Task]:
        """派一个后台 sync_local_owned_index 任务，已有未完成任务则复用。"""
        if self._is_local_owned_index_fresh():
            return None
        existing = self._local_owned_sync_state.get("background_task")
        if existing and isinstance(existing, asyncio.Task) and not existing.done():
            return existing

        sync_state = self._local_owned_sync_state

        async def _runner() -> None:
            try:
                await self.sync_local_owned_index()
            except Exception:
                logger.warning("[社团补全] 后台 sync_local_owned_index 失败", exc_info=True)
            finally:
                # 自检：只在自己仍是当前注册的 task 时清空，避免误清掉后续新调度的 task。
                running_task = asyncio.current_task()
                if sync_state.get("background_task") is running_task:
                    sync_state["background_task"] = None

        try:
            task = asyncio.create_task(_runner(), name="circle-local-owned-sync")
        except RuntimeError:
            return None
        sync_state["background_task"] = task
        return task

    async def sync_local_owned_index(self) -> Dict[str, Any]:
        from .library_manager import get_library_manager

        db = SessionLocal()
        try:
            circle_rows = db.query(
                CircleWork.canonical_rjcode,
                CircleWork.display_rjcode,
                CircleWork.linked_rjcodes,
                CircleWork.is_bonus_work,
            ).all()
        finally:
            db.close()

        raw_candidate_rjcodes: set[str] = set()
        for row in circle_rows:
            raw_candidate_rjcodes.update({
                self.normalize_rjcode(row.canonical_rjcode),
                self.normalize_rjcode(row.display_rjcode),
                *[self.normalize_rjcode(code) for code in list(row.linked_rjcodes or [])],
            })
        raw_candidate_rjcodes.discard("")
        bonus_rjcodes = self._load_bonus_rjcodes_for_owned_state(raw_candidate_rjcodes)

        candidate_rjcodes: set[str] = set()
        related_canonicals_by_rj: Dict[str, Set[str]] = defaultdict(set)
        for row in circle_rows:
            row_canonical = self.normalize_rjcode(row.canonical_rjcode)
            row_codes = self._owned_state_candidate_codes(row_canonical, {
                "canonical_rjcode": row_canonical,
                "display_rjcode": row.display_rjcode,
                "linked_rjcodes": list(row.linked_rjcodes or []),
                "is_bonus_work": bool(getattr(row, "is_bonus_work", False)),
            }, bonus_rjcodes)
            candidate_rjcodes.update(row_codes)
            if row_canonical:
                for code in row_codes:
                    related_canonicals_by_rj[code].add(row_canonical)

        index_hits = get_library_manager().find_rj_in_ready_index(candidate_rjcodes)
        merged: Dict[str, Dict[str, Any]] = {}
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(16)

        async def _resolve_and_merge(rjcode: str, hit: Dict[str, Any]) -> None:
            normalized_rj = self.normalize_rjcode(rjcode)
            if not normalized_rj:
                return
            async with sem:
                canonical_info = await self.resolve_canonical_rj(normalized_rj)
            canonical = self.normalize_rjcode(canonical_info.get("canonical_rjcode") or normalized_rj) or normalized_rj
            if normalized_rj in bonus_rjcodes:
                target_canonicals = set(related_canonicals_by_rj.get(normalized_rj, set()))
            else:
                target_canonicals = {canonical}
                target_canonicals.update(related_canonicals_by_rj.get(normalized_rj, set()))
                target_canonicals.update(related_canonicals_by_rj.get(canonical, set()))
            if not target_canonicals:
                target_canonicals.add(normalized_rj)
            async with lock:
                for target_canonical in sorted(code for code in target_canonicals if code):
                    bucket = merged.setdefault(target_canonical, {
                        "owned_rjcodes": set(),
                        "owned_paths": [],
                        "primary_folder_path": "",
                        "primary_library_id": "",
                        "folder_count": 0,
                        "folder_size": 0,
                        "file_count": 0,
                        "has_local_subtitles": False,
                        "subtitle_file_count": 0,
                        "subtitle_dir": "",
                    })
                    bucket["owned_rjcodes"].add(normalized_rj)
                    path = str(hit.get("path") or "").strip()
                    if path and path not in bucket["owned_paths"]:
                        bucket["owned_paths"].append(path)
                    if path and not bucket["primary_folder_path"]:
                        bucket["primary_folder_path"] = path
                    library_id = str(hit.get("library_id") or "").strip()
                    if library_id and not bucket["primary_library_id"]:
                        bucket["primary_library_id"] = library_id
                    bucket["folder_count"] += 1
                    bucket["folder_size"] += int(hit.get("size") or 0)
                    bucket["file_count"] += int(hit.get("file_count") or 0)
                    subtitle_count = int(hit.get("subtitle_file_count") or 0)
                    if bool(hit.get("local_subtitle_present")) or subtitle_count > 0:
                        bucket["has_local_subtitles"] = True
                        bucket["subtitle_file_count"] += subtitle_count
                        if hit.get("subtitle_dir") and not bucket["subtitle_dir"]:
                            bucket["subtitle_dir"] = str(hit.get("subtitle_dir") or "")

        merge_tasks = [
            _resolve_and_merge(rjcode, hit)
            for rjcode, hits in index_hits.items()
            for hit in hits
        ]
        if merge_tasks:
            await asyncio.gather(*merge_tasks)
        if not merged:
            logger.info("[社团补全] ready 库存索引无命中，清空本地拥有态快照")

        db = SessionLocal()
        try:
            db.query(LibraryOwnedWork).delete()
            for canonical, info in merged.items():
                db.add(LibraryOwnedWork(
                    canonical_rjcode=canonical,
                    owned_rjcodes=sorted(info["owned_rjcodes"]),
                    primary_folder_path=info["primary_folder_path"],
                    library_id=info["primary_library_id"],
                    folder_count=info["folder_count"],
                    folder_size=info["folder_size"],
                    file_count=info["file_count"],
                    owned_paths=info["owned_paths"],
                    has_local_subtitles=bool(info["has_local_subtitles"]),
                    subtitle_file_count=int(info["subtitle_file_count"] or 0),
                    subtitle_dir=info["subtitle_dir"],
                    updated_at=datetime.now(),
                ))
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 重建本地拥有态失败", exc_info=True)
            raise
        finally:
            db.close()
        # P8：记录完成时间戳，用于 TTL 判断"下一次索引是否还需要 await 全量同步"。
        self._local_owned_sync_state["last_completed_at"] = time.monotonic()
        self.invalidate_completion_view_cache()
        return {"owned_count": len(merged)}

    async def sync_owned_for_rj(self, rjcode: str, folder_path: str = "", library_id: str = "") -> None:
        """单 RJ 入库后增量同步本地拥有态索引。

        相对于早期实现，这里多做了两件事：

        1. **反向匹配 linked_rjcodes**：CircleWork 索引时算出来的 canonical 与
           入库时 `resolve_canonical_rj` 算出来的 canonical 可能因为 DLsite
           数据更新或解析逻辑差异而不一致，单写一条 `LibraryOwnedWork(canonical=A)`
           会让 LEFT JOIN 在另一个 canonical 上漏匹配。这里用 JSON 文本匹配
           兜底：只要 `CircleWork.linked_rjcodes` 含当前 RJ，就把这条 row 的
           `canonical_rjcode` 也写进 LibraryOwnedWork。

        2. **完成后通过 SSE 广播 `circle_owned_synced`**：让正在浏览社团补全
           页的前端可以秒级看到状态翻转，无需手动刷新。
        """
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return
        try:
            canonical_info = await self.resolve_canonical_rj(normalized_rj)
        except Exception:
            logger.warning(
                "[社团补全] sync_owned_for_rj canonical 解析失败 rj=%s，回退使用自身",
                normalized_rj,
                exc_info=True,
            )
            canonical_info = {}
        canonical = self.normalize_rjcode(
            (canonical_info or {}).get("canonical_rjcode") or normalized_rj
        ) or normalized_rj

        # 函数内部局部 import，与本文件其他位置（search_circles）一致，避免污染顶层 import。
        from sqlalchemy import Text as sa_Text, cast as sa_cast, or_ as sa_or

        affected_circle_ids: set[str] = set()
        target_canonicals: set[str] = set()
        reverse_match_count = 0
        from .library_manager import get_library_manager

        index_hits = get_library_manager().find_rj_in_ready_index(
            [normalized_rj, canonical],
            library_ids=[library_id] if library_id else None,
        )
        flat_hits = [hit for hits in index_hits.values() for hit in hits]
        primary_hit = next((hit for hit in flat_hits if str(hit.get("path") or "").strip() == folder_path), None)
        if primary_hit is None and flat_hits:
            primary_hit = flat_hits[0]
        hit_path = str((primary_hit or {}).get("path") or folder_path or "").strip()
        hit_library_id = str((primary_hit or {}).get("library_id") or library_id or "").strip()
        hit_size = int((primary_hit or {}).get("size") or 0)
        hit_file_count = int((primary_hit or {}).get("file_count") or 0)
        hit_subtitle_count = int((primary_hit or {}).get("subtitle_file_count") or 0)
        hit_subtitle_dir = str((primary_hit or {}).get("subtitle_dir") or "").strip()
        hit_has_subtitle = bool((primary_hit or {}).get("local_subtitle_present")) or hit_subtitle_count > 0

        db = SessionLocal()
        try:
            # === 反向匹配：找出所有 CircleWork 行，其 canonical 或 linked_rjcodes 关联到本次 RJ ===
            # 优先索引点查；linked_rjcodes JSON LIKE 仅作为兜底（覆盖 canonical 不一致的边界）。
            json_pattern = f'%"{normalized_rj}"%'
            related_rows = (
                db.query(
                    CircleWork.canonical_rjcode.label("canonical_rjcode"),
                    CircleWork.display_rjcode.label("display_rjcode"),
                    CircleWork.is_bonus_work.label("is_bonus_work"),
                    CircleWork.circle_id.label("circle_id"),
                )
                .filter(
                    sa_or(
                        CircleWork.canonical_rjcode == canonical,
                        CircleWork.canonical_rjcode == normalized_rj,
                        CircleWork.display_rjcode == normalized_rj,
                        sa_cast(CircleWork.linked_rjcodes, sa_Text).like(json_pattern),
                    )
                )
                .all()
            )
            reverse_match_count = len(related_rows)
            related_codes = {normalized_rj, canonical}
            for related in related_rows:
                related_codes.add(self.normalize_rjcode(related.canonical_rjcode))
                related_codes.add(self.normalize_rjcode(related.display_rjcode))
            related_codes.discard("")
            bonus_rjcodes = self._load_bonus_rjcodes_for_owned_state(related_codes)
            incoming_is_bonus = normalized_rj in bonus_rjcodes
            if not incoming_is_bonus:
                target_canonicals.add(canonical)
            for related in related_rows:
                related_canonical = self._owned_sync_row_target_canonical(
                    related,
                    normalized_rj,
                    incoming_is_bonus,
                    bonus_rjcodes,
                )
                if not related_canonical:
                    continue
                target_canonicals.add(related_canonical)
                related_circle_id = str(related.circle_id or "").strip()
                if related_circle_id:
                    affected_circle_ids.add(related_circle_id)

            # === 对每个 canonical upsert LibraryOwnedWork ===
            now_ts = datetime.now()
            for c in target_canonicals:
                row = db.query(LibraryOwnedWork).filter(LibraryOwnedWork.canonical_rjcode == c).first()
                owned_rjcodes = set(row.owned_rjcodes or []) if row else set()
                owned_rjcodes.add(normalized_rj)
                if row is None:
                    row = LibraryOwnedWork(canonical_rjcode=c)
                    db.add(row)
                row.owned_rjcodes = sorted(owned_rjcodes)
                row.primary_folder_path = hit_path or row.primary_folder_path
                row.library_id = hit_library_id or row.library_id
                row.folder_count = max(int(row.folder_count or 0), 1)
                if hit_size:
                    row.folder_size = max(int(row.folder_size or 0), hit_size)
                if hit_file_count:
                    row.file_count = max(int(row.file_count or 0), hit_file_count)
                owned_paths = list(row.owned_paths or [])
                if hit_path and hit_path not in owned_paths:
                    owned_paths.append(hit_path)
                row.owned_paths = owned_paths
                if hit_has_subtitle:
                    row.has_local_subtitles = True
                    row.subtitle_file_count = max(int(row.subtitle_file_count or 0), hit_subtitle_count)
                    row.subtitle_dir = hit_subtitle_dir or row.subtitle_dir
                row.updated_at = now_ts
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 增量更新拥有态失败 %s", normalized_rj, exc_info=True)
            return
        finally:
            db.close()

        logger.info(
            "[社团补全] 入库同步 rj=%s canonical=%s -> 写入 %d 个 canonical(反向匹配 %d 行)，影响社团=%s",
            normalized_rj,
            canonical,
            len(target_canonicals),
            reverse_match_count,
            ",".join(sorted(affected_circle_ids)) if affected_circle_ids else "<无>",
        )
        if affected_circle_ids:
            for affected_circle_id in affected_circle_ids:
                self.invalidate_completion_view_cache(affected_circle_id)
        else:
            self.invalidate_completion_view_cache()

        # === SSE 广播：通知前端"该 RJ 已入库，请刷新相关社团" ===
        # 不挂 NotificationInbox（不是真正的"通知"，只是数据变更信号），所以走轻量事件类型。
        # 任何异常都不能反向影响入库主流程。
        try:
            from .task_notification_service import _sse_broadcast

            _sse_broadcast({
                "type": "circle_owned_synced",
                "rjcode": normalized_rj,
                "canonicals": sorted(target_canonicals),
                "circle_ids": sorted(affected_circle_ids),
            })
        except Exception:
            logger.debug("[社团补全] SSE 广播失败 rj=%s", normalized_rj, exc_info=True)

    async def sync_subtitle_for_rj(
        self,
        rjcode: str,
        *,
        folder_path: str = "",
        library_id: str = "",
        subtitle_dir: str = "",
        subtitle_file_count: int = 0,
    ) -> None:
        normalized_rj = self.normalize_rjcode(rjcode)
        if not normalized_rj:
            return
        try:
            canonical_info = await self.resolve_canonical_rj(normalized_rj)
        except Exception:
            logger.warning("[社团补全] sync_subtitle_for_rj canonical 解析失败 rj=%s", normalized_rj, exc_info=True)
            canonical_info = {}
        canonical = self.normalize_rjcode((canonical_info or {}).get("canonical_rjcode") or normalized_rj) or normalized_rj

        from sqlalchemy import Text as sa_Text, cast as sa_cast, or_ as sa_or

        affected_circle_ids: set[str] = set()
        target_canonicals: set[str] = set()
        db = SessionLocal()
        try:
            json_pattern = f'%"{normalized_rj}"%'
            related_rows = (
                db.query(
                    CircleWork.canonical_rjcode.label("canonical_rjcode"),
                    CircleWork.display_rjcode.label("display_rjcode"),
                    CircleWork.is_bonus_work.label("is_bonus_work"),
                    CircleWork.circle_id.label("circle_id"),
                )
                .filter(
                    sa_or(
                        CircleWork.canonical_rjcode == canonical,
                        CircleWork.canonical_rjcode == normalized_rj,
                        CircleWork.display_rjcode == normalized_rj,
                        sa_cast(CircleWork.linked_rjcodes, sa_Text).like(json_pattern),
                    )
                )
                .all()
            )
            related_codes = {normalized_rj, canonical}
            for related in related_rows:
                related_codes.add(self.normalize_rjcode(related.canonical_rjcode))
                related_codes.add(self.normalize_rjcode(related.display_rjcode))
            related_codes.discard("")
            bonus_rjcodes = self._load_bonus_rjcodes_for_owned_state(related_codes)
            incoming_is_bonus = normalized_rj in bonus_rjcodes
            if not incoming_is_bonus:
                target_canonicals.add(canonical)
            for related in related_rows:
                related_canonical = self._owned_sync_row_target_canonical(
                    related,
                    normalized_rj,
                    incoming_is_bonus,
                    bonus_rjcodes,
                )
                if not related_canonical:
                    continue
                target_canonicals.add(related_canonical)
                related_circle_id = str(related.circle_id or "").strip()
                if related_circle_id:
                    affected_circle_ids.add(related_circle_id)

            now_ts = datetime.now()
            for c in target_canonicals:
                row = db.query(LibraryOwnedWork).filter(LibraryOwnedWork.canonical_rjcode == c).first()
                if row is None:
                    if not folder_path:
                        continue
                    row = LibraryOwnedWork(canonical_rjcode=c)
                    db.add(row)
                owned_rjcodes = set(row.owned_rjcodes or [])
                owned_rjcodes.add(normalized_rj)
                row.owned_rjcodes = sorted(code for code in owned_rjcodes if code)
                row.primary_folder_path = folder_path or row.primary_folder_path
                row.library_id = library_id or row.library_id
                row.folder_count = max(int(row.folder_count or 0), 1)
                owned_paths = list(row.owned_paths or [])
                if folder_path and folder_path not in owned_paths:
                    owned_paths.append(folder_path)
                row.owned_paths = owned_paths
                row.has_local_subtitles = True
                row.subtitle_file_count = max(int(row.subtitle_file_count or 0), int(subtitle_file_count or 0), 1)
                row.subtitle_dir = subtitle_dir or row.subtitle_dir
                row.updated_at = now_ts
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 增量更新字幕态失败 rj=%s", normalized_rj, exc_info=True)
            return
        finally:
            db.close()

        if affected_circle_ids:
            for affected_circle_id in affected_circle_ids:
                self.invalidate_completion_view_cache(affected_circle_id)
        else:
            self.invalidate_completion_view_cache()
        try:
            from .task_notification_service import _sse_broadcast

            _sse_broadcast({
                "type": "circle_subtitle_synced",
                "rjcode": normalized_rj,
                "canonicals": sorted(target_canonicals),
                "circle_ids": sorted(affected_circle_ids),
                "subtitle_file_count": int(subtitle_file_count or 0),
                "subtitle_dir": subtitle_dir,
            })
        except Exception:
            logger.debug("[社团补全] 字幕 SSE 广播失败 rj=%s", normalized_rj, exc_info=True)

    def _load_bonus_rjcodes_for_owned_state(self, rjcodes: Set[str]) -> Set[str]:
        normalized_codes = {
            normalized
            for normalized in (self.normalize_rjcode(code) for code in rjcodes)
            if normalized
        }
        if not normalized_codes:
            return set()
        db = SessionLocal()
        try:
            rows = (
                db.query(WorkCanonicalLink.linked_rjcode)
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    WorkCanonicalLink.linked_rjcode.in_(normalized_codes),
                    WorkCanonicalLink.link_type == "bonus",
                )
                .all()
            )
            return {
                normalized
                for normalized in (self.normalize_rjcode(row[0]) for row in rows)
                if normalized
            }
        finally:
            db.close()

    def _owned_state_candidate_codes(
        self,
        canonical: str,
        item: Dict[str, Any],
        bonus_rjcodes: Set[str],
    ) -> Set[str]:
        own_codes = {
            self.normalize_rjcode(canonical),
            self.normalize_rjcode(item.get("canonical_rjcode")),
            self.normalize_rjcode(item.get("display_rjcode")),
            self.normalize_rjcode(item.get("rjcode")),
        }
        own_codes.discard("")
        if bool(item.get("is_bonus_work")) or bool(own_codes & bonus_rjcodes):
            return own_codes

        candidates = {
            *own_codes,
            self.normalize_rjcode(item.get("asmr_available_rjcode")),
            *[self.normalize_rjcode(code) for code in list(item.get("linked_rjcodes") or [])],
            *[self.normalize_rjcode(code) for code in list(item.get("kikoeru_found_rjcodes") or [])],
        }
        candidates.discard("")
        return candidates - bonus_rjcodes

    def _owned_sync_row_target_canonical(
        self,
        related: Any,
        normalized_rj: str,
        incoming_is_bonus: bool,
        bonus_rjcodes: Set[str],
    ) -> str:
        related_canonical = self.normalize_rjcode(related.canonical_rjcode)
        related_display = self.normalize_rjcode(related.display_rjcode)
        related_is_bonus = (
            bool(related.is_bonus_work)
            or related_canonical in bonus_rjcodes
            or related_display in bonus_rjcodes
        )
        if incoming_is_bonus:
            return related_canonical if normalized_rj in {related_canonical, related_display} else ""
        return "" if related_is_bonus else related_canonical

    def _apply_library_index_owned_state_to_items(self, items_by_canonical: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        if not items_by_canonical:
            return {"owned_count": 0, "subtitle_count": 0, "hit_count": 0, "ready_index_available": False}
        from .library_manager import get_library_manager

        library_manager = get_library_manager()
        try:
            ready_index_available = bool(library_manager.has_ready_index())
        except Exception:
            logger.debug("[社团补全] 判断 ready 库存索引失败，本次不改写本地拥有态", exc_info=True)
            ready_index_available = False
        if not ready_index_available:
            return {"owned_count": 0, "subtitle_count": 0, "hit_count": 0, "ready_index_available": False}

        raw_lookup_codes: set[str] = set()
        for canonical, item in items_by_canonical.items():
            raw_lookup_codes.update({
                self.normalize_rjcode(canonical),
                self.normalize_rjcode(item.get("canonical_rjcode")),
                self.normalize_rjcode(item.get("display_rjcode")),
                self.normalize_rjcode(item.get("rjcode")),
                self.normalize_rjcode(item.get("asmr_available_rjcode")),
                *[self.normalize_rjcode(code) for code in list(item.get("linked_rjcodes") or [])],
                *[self.normalize_rjcode(code) for code in list(item.get("kikoeru_found_rjcodes") or [])],
            })
        raw_lookup_codes.discard("")
        bonus_rjcodes = self._load_bonus_rjcodes_for_owned_state(raw_lookup_codes)

        lookup_codes: set[str] = set()
        canonical_members: Dict[str, set[str]] = {}
        for canonical, item in items_by_canonical.items():
            members = self._owned_state_candidate_codes(canonical, item, bonus_rjcodes)
            canonical_members[canonical] = members
            lookup_codes.update(members)
        index_hits = library_manager.find_rj_in_ready_index(lookup_codes)
        owned_count = 0
        subtitle_count = 0
        hit_count = 0
        for canonical, item in items_by_canonical.items():
            members = canonical_members.get(canonical) or set()
            hits = [
                hit
                for code in members
                for hit in list(index_hits.get(code) or [])
            ]
            if not hits:
                item["has_kikoeru"] = False
                item["kikoeru_found_rjcodes"] = []
                item["kikoeru_subtitle_rjcodes"] = []
                item["local_owned"] = False
                item["local_subtitle_present"] = False
                item["local_folder_size"] = 0
                item["local_file_count"] = 0
                item["subtitle_file_count"] = 0
                item["subtitle_dir"] = ""
                item["owned_paths"] = []
                item["primary_library_id"] = ""
                item["source_flags"].discard("kikoeru") if isinstance(item.get("source_flags"), set) else None
                continue
            hit_count += len(hits)
            found_rjcodes: list[str] = []
            owned_paths: list[str] = []
            primary_library_id = ""
            folder_size = 0
            file_count = 0
            local_subtitle_present = False
            subtitle_file_count = 0
            subtitle_dir = ""
            for hit in hits:
                for code in [hit.get("matched_rjcode"), hit.get("rjcode")]:
                    normalized = self.normalize_rjcode(code)
                    if normalized and normalized not in found_rjcodes:
                        found_rjcodes.append(normalized)
                path = str(hit.get("path") or "").strip()
                if path and path not in owned_paths:
                    owned_paths.append(path)
                if not primary_library_id:
                    primary_library_id = str(hit.get("library_id") or "").strip()
                folder_size += int(hit.get("size") or 0)
                file_count += int(hit.get("file_count") or 0)
                current_subtitle_count = int(hit.get("subtitle_file_count") or 0)
                if bool(hit.get("local_subtitle_present")) or current_subtitle_count > 0:
                    local_subtitle_present = True
                    subtitle_file_count += current_subtitle_count
                    if hit.get("subtitle_dir") and not subtitle_dir:
                        subtitle_dir = str(hit.get("subtitle_dir") or "")
            item["has_kikoeru"] = True
            item["kikoeru_found_rjcodes"] = found_rjcodes
            item["kikoeru_subtitle_rjcodes"] = found_rjcodes if local_subtitle_present else []
            item["local_owned"] = True
            item["local_subtitle_present"] = local_subtitle_present
            item["local_folder_size"] = folder_size
            item["local_file_count"] = file_count
            item["subtitle_file_count"] = subtitle_file_count
            item["subtitle_dir"] = subtitle_dir
            item["owned_paths"] = owned_paths
            item["primary_library_id"] = primary_library_id
            if isinstance(item.get("source_flags"), set):
                item["source_flags"].add("kikoeru")
            owned_count += 1
            if local_subtitle_present:
                subtitle_count += 1
        return {
            "owned_count": owned_count,
            "subtitle_count": subtitle_count,
            "hit_count": hit_count,
            "ready_index_available": True,
        }

    def _upsert_library_owned_rows_from_items(
        self,
        db,
        items_by_canonical: Dict[str, Dict[str, Any]],
        *,
        prune_unmatched: bool = False,
    ) -> int:
        """把当前索引批次已通过库存索引确认的本地拥有态写入快照表。"""
        written = 0
        now_ts = datetime.now()
        for canonical, item in items_by_canonical.items():
            normalized_canonical = self.normalize_rjcode(canonical)
            if not normalized_canonical:
                continue
            row = db.query(LibraryOwnedWork).filter(
                LibraryOwnedWork.canonical_rjcode == normalized_canonical
            ).first()
            if not item.get("local_owned"):
                if prune_unmatched and row is not None:
                    db.delete(row)
                    written += 1
                continue
            owned_paths = [
                str(path or "").strip()
                for path in list(item.get("owned_paths") or [])
                if str(path or "").strip()
            ]
            owned_rjcodes = {
                *[self.normalize_rjcode(code) for code in list(item.get("kikoeru_found_rjcodes") or [])],
            }
            owned_rjcodes.discard("")
            if row is None:
                row = LibraryOwnedWork(canonical_rjcode=normalized_canonical)
                db.add(row)
            row.owned_rjcodes = sorted(owned_rjcodes)
            row.primary_folder_path = owned_paths[0] if owned_paths else ""
            row.library_id = str(item.get("primary_library_id") or "").strip()
            row.folder_count = max(len(owned_paths), 1)
            row.folder_size = int(item.get("local_folder_size") or 0)
            row.file_count = int(item.get("local_file_count") or 0)
            row.owned_paths = owned_paths
            row.has_local_subtitles = bool(item.get("local_subtitle_present"))
            row.subtitle_file_count = int(item.get("subtitle_file_count") or 0)
            row.subtitle_dir = str(item.get("subtitle_dir") or "").strip()
            row.updated_at = now_ts
            written += 1
        return written

    def _schedule_circle_cover_cache(
        self,
        circle_id: str,
        cover_pairs: List[Tuple[str, str]],
        thumb_pairs: List[Tuple[str, str]],
    ) -> Optional[asyncio.Task]:
        """把封面下载挪到后台。同 circle_id 同时只跑一个任务；上次还没完成时复用现有 Task。

        返回新建（或已有）的后台任务对象，方便测试 / 调试 await。主流程不应 await。
        """
        if not cover_pairs and not thumb_pairs:
            return None

        existing = self._cover_cache_tasks.get(circle_id)
        if existing and not existing.done():
            logger.debug("[社团补全] circle_id=%s 已有封面缓存后台任务，跳过新建", circle_id)
            return existing

        async def _runner() -> None:
            try:
                image_cache_service = get_circle_image_cache_service()
                if cover_pairs:
                    await image_cache_service.download_many(cover_pairs)
                if thumb_pairs:
                    await image_cache_service.download_many(thumb_pairs, variant="list")
            except Exception:
                logger.warning("[社团补全] 后台封面缓存失败 circle_id=%s", circle_id, exc_info=True)
            finally:
                # 任务结束后从字典清除，避免长期占用内存
                self._cover_cache_tasks.pop(circle_id, None)

        try:
            task = asyncio.create_task(_runner(), name=f"circle-cover-cache:{circle_id}")
        except RuntimeError:
            # 没运行中的 event loop（极少出现：测试场景 / 同步 caller）→ 静默放弃后台化，
            # 不阻塞主流程。
            logger.debug("[社团补全] 当前无运行中的 event loop，跳过封面缓存后台化 circle_id=%s", circle_id)
            return None
        self._cover_cache_tasks[circle_id] = task
        return task

    def _queue_circle_cover_alias_restore(
        self,
        circle_id: str,
        image_cache_service: Any,
        target_rjcode: Any,
        legacy_rjcode: Any,
    ) -> Optional[asyncio.Task]:
        """后台补建历史 display RJ 封面别名，不阻塞社团浏览读路径。"""

        target = image_cache_service.normalize_rjcode(target_rjcode)
        legacy = image_cache_service.normalize_rjcode(legacy_rjcode)
        if not target or not legacy or target == legacy:
            return None
        # 大多数作品不存在旧错名缓存；先做廉价 stat，避免为每行创建空任务。
        if not (
            image_cache_service.has_local(legacy)
            or image_cache_service.has_local(legacy, variant="list")
        ):
            return None

        scope = str(circle_id or target).strip() or target
        pending = self._cover_alias_restore_pending.setdefault(scope, set())
        pending.add((target, legacy))
        existing = self._cover_alias_restore_tasks.get(scope)
        if existing and not existing.done():
            return existing

        async def _runner() -> None:
            try:
                while True:
                    pairs = self._cover_alias_restore_pending.pop(scope, set())
                    if not pairs:
                        return
                    for target_code, legacy_code in pairs:
                        # restore_from_legacy_alias 是流式磁盘复制；移到线程池避免阻塞
                        # FastAPI 事件循环和 SSE。
                        await asyncio.to_thread(
                            image_cache_service.restore_from_legacy_alias,
                            target_code,
                            [legacy_code],
                        )
                        await asyncio.to_thread(
                            image_cache_service.restore_from_legacy_alias,
                            target_code,
                            [legacy_code],
                            variant="list",
                        )
            except Exception:
                logger.warning(
                    "[社团补全] 修复历史封面缓存别名失败 circle_id=%s",
                    scope,
                    exc_info=True,
                )
            finally:
                current = asyncio.current_task()
                if self._cover_alias_restore_tasks.get(scope) is current:
                    self._cover_alias_restore_tasks.pop(scope, None)
                self._cover_alias_restore_pending.pop(scope, None)

        try:
            task = asyncio.create_task(_runner(), name=f"circle-cover-alias-restore:{scope}")
        except RuntimeError:
            logger.debug(
                "[社团补全] 当前无运行事件循环，跳过历史封面别名修复 circle_id=%s",
                scope,
            )
            return None
        self._cover_alias_restore_tasks[scope] = task
        return task

    def _schedule_circle_bonus_refresh(
        self,
        circle_id: str,
        bonus_lookup_rjcodes: List[str],
        *,
        force: bool = False,
    ) -> Optional[asyncio.Task]:
        """把 bonus 字段补刷挪到后台，保留 ``_refresh_circle_bonus_fields`` 同步版本给
        ``refresh_circle_works`` 这种"选中作品刷新"路径使用（用户主动触发，期望立即看到结果）。
        """
        if not bonus_lookup_rjcodes:
            return None
        existing = self._bonus_refresh_tasks.get(circle_id)
        if existing and not existing.done():
            logger.debug("[社团补全] circle_id=%s 已有 bonus 后台任务，跳过新建", circle_id)
            return existing

        async def _runner() -> None:
            try:
                await self._refresh_circle_bonus_fields(
                    circle_id, bonus_lookup_rjcodes, force=force
                )
            except Exception:
                logger.warning("[社团补全] 后台 bonus 补刷失败 circle_id=%s", circle_id, exc_info=True)
            finally:
                self._bonus_refresh_tasks.pop(circle_id, None)

        try:
            task = asyncio.create_task(_runner(), name=f"circle-bonus-refresh:{circle_id}")
        except RuntimeError:
            logger.debug("[社团补全] 当前无运行中的 event loop，跳过 bonus 后台化 circle_id=%s", circle_id)
            return None
        self._bonus_refresh_tasks[circle_id] = task
        return task

    async def _refresh_circle_bonus_fields(
        self,
        circle_id: str,
        bonus_lookup_rjcodes: List[str],
        *,
        canonical_filter: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """``index_circle_catalog`` / ``refresh_circle_works`` 写入完成后调用：

        - 先走 ``metadata_service.lazy_refresh_bonus_for_cached_rjcodes`` 把
          ``work_metadata.bonus_info_checked_at IS NULL`` 的存量条目补刷一遍；
        - 再把补到的 ``is_bonus_work`` / ``has_bonus`` 同步到当前社团的
          ``circle_works`` 行；``is_bonus_work`` 只看当前行自己的 canonical /
          display RJ，``has_bonus`` 才按关联 RJ 做聚合，避免父作品被关联特典误标；
        - 浏览路径已经退化成纯 DB 读，所以这条同步必须发生在写路径里，
          不然用户在选中刷新后浏览社团页时仍看不到特典 chip。

        参数：
        - ``circle_id``：要回写 ``circle_works`` 的社团；
        - ``bonus_lookup_rjcodes``：当前社团涉及的所有关联 RJ（canonical / display / linked）；
        - ``canonical_filter``：可选，把回写范围进一步限定到这些 canonical RJ（``refresh_circle_works``
          只刷新选中作品时用），``None`` 表示当前社团全量。
        - ``force``：``True`` 时透传给 ``lazy_refresh_bonus_for_cached_rjcodes(force=True)``，
          忽略 ``bonus_info_checked_at`` 时间戳全量重刷——给"刷新选中作品"路径用，
          修复历史 ``get_product_bonus_info`` 异常吞错导致的 ``is_bonus_work=False`` 卡死条目。

        返回 ``lazy_refresh_bonus_for_cached_rjcodes`` 的更新字典，方便上游记录 / 调试。
        """
        normalized_rjcodes: List[str] = []
        for code in bonus_lookup_rjcodes or []:
            normalized = self.normalize_rjcode(code)
            if normalized and normalized not in normalized_rjcodes:
                normalized_rjcodes.append(normalized)
        if not normalized_rjcodes:
            return {}

        try:
            bonus_updates = await self.metadata_service.lazy_refresh_bonus_for_cached_rjcodes(
                normalized_rjcodes,
                force=force,
            )
        except Exception:
            logger.warning("[社团补全] bonus 补刷失败 circle_id=%s force=%s", circle_id, force, exc_info=True)
            return {}
        if not bonus_updates:
            return {}

        normalized_filter: Optional[List[str]] = None
        if canonical_filter is not None:
            normalized_filter = []
            for code in canonical_filter:
                normalized = self.normalize_rjcode(code)
                if normalized and normalized not in normalized_filter:
                    normalized_filter.append(normalized)

        db = SessionLocal()
        changed = False
        try:
            query = db.query(CircleWork).filter(CircleWork.circle_id == circle_id)
            if normalized_filter is not None:
                query = query.filter(CircleWork.canonical_rjcode.in_(normalized_filter))
            rows = query.all()
            for row in rows:
                own_codes: List[str] = []
                for code in [
                    row.canonical_rjcode,
                    row.display_rjcode,
                ]:
                    normalized = self.normalize_rjcode(code)
                    if normalized and normalized not in own_codes:
                        own_codes.append(normalized)
                related: List[str] = list(own_codes)
                for code in row.linked_rjcodes or []:
                    normalized = self.normalize_rjcode(code)
                    if normalized and normalized not in related:
                        related.append(normalized)
                new_is_bonus = bool(row.is_bonus_work)
                new_has_bonus = bool(row.has_bonus)
                hit = False
                own_bonus_seen = False
                own_is_bonus = False
                for rj in related:
                    payload = bonus_updates.get(rj)
                    if not payload:
                        continue
                    hit = True
                    # linked RJ 可能是挂在父作品上的特典，只能影响 has_bonus，
                    # 不能把父行自身误标成 is_bonus_work。
                    if rj in own_codes:
                        own_bonus_seen = True
                        own_is_bonus = own_is_bonus or bool(payload.get("is_bonus_work"))
                    new_has_bonus = new_has_bonus or bool(payload.get("has_bonus"))
                if own_bonus_seen:
                    new_is_bonus = own_is_bonus
                if hit and (new_is_bonus != bool(row.is_bonus_work) or new_has_bonus != bool(row.has_bonus)):
                    row.is_bonus_work = new_is_bonus
                    row.has_bonus = new_has_bonus
                    changed = True
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 同步 bonus 字段到 circle_works 失败 circle_id=%s", circle_id, exc_info=True)
        finally:
            db.close()
        if changed:
            self.invalidate_completion_view_cache(circle_id)
        return bonus_updates

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
        # 单社团索引耗时记账：从"用户点击 → index_completed 写日志"全程，时间线显示这条。
        # 我们在 lite 路径里把 task_finished 行过滤掉了，所以耗时必须直接写进 index_completed.detail。
        _index_start_monotonic = time.monotonic()
        # P0：单次索引埋点对象。所有阶段耗时 / counter 都灌到这里，最后写入
        # index_completed.detail['perf']，方便后续 SQL 聚合分析。
        perf = CircleIndexPerfTracker()

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

        # 本地拥有态全量快照不能进入单社团索引路径，哪怕后台启动也会和后续 DLsite/DB 阶段抢资源。
        # 当前社团会在 90% 阶段用 ready 库存索引局部核对并写回 LibraryOwnedWork。
        report(5, "跳过全量本地拥有态同步，改用当前社团库存索引核对", circle_query=circle_query)
        perf.inc("local_owned_sync_mode_skipped")
        ensure_not_cancelled()

        report(12, "收集本地社团候选")
        local_candidates = await self._collect_local_circle_candidates(circle_query)
        kikoeru_candidates: List[Dict[str, Any]] = []
        resolved_kikoeru_circle_id = ""
        if include_kikoeru:
            report(24, "跳过 Kikoeru 社团作品查询，收录态改由 ready 库存索引核对", local_candidates_count=len(local_candidates))

        combined_seed_candidates = local_candidates + kikoeru_candidates

        identity_seed = self.resolve_circle_identity("", circle_query, circle_query)
        if combined_seed_candidates:
            # 与 `_resolve_identity_from_candidates` 同款修复：preferred 必须先做
            # maker_name 校验，避免误把无关候选的 maker_id 当成 identity 种子。
            preferred_seed = next(
                (
                    item
                    for item in combined_seed_candidates
                    if item.get("maker_id")
                    and self._circle_name_loose_match(circle_query, item.get("maker_name"))
                ),
                None,
            )
            if preferred_seed is None:
                preferred_seed = combined_seed_candidates[0]
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
        if resolved_kikoeru_circle_id and identity_seed["maker_id"]:
            self._set_cached_kikoeru_circle_id(
                resolved_kikoeru_circle_id,
                f"maker:{str(identity_seed['maker_id']).strip().upper()}",
            )
            self._save_persisted_kikoeru_circle_id(
                self.normalize_circle_name(circle_query),
                resolved_kikoeru_circle_id,
                str(identity_seed["maker_id"] or "").strip(),
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
            with perf.timed("stage_dlsite_candidates"):
                dlsite_candidates = await self._collect_dlsite_circle_candidates(
                    circle_query,
                    identity_seed["maker_id"],
                    progress_callback=report,
                    perf=perf,
                )
        ensure_not_cancelled()

        combined_candidates = local_candidates + kikoeru_candidates + dlsite_candidates
        invalid_circle_query_hint = self._build_invalid_circle_query_hint(
            circle_query,
            local_candidates_count=len(local_candidates),
            kikoeru_candidates_count=len(kikoeru_candidates),
            dlsite_candidates_count=len(dlsite_candidates),
        )
        report(
            54,
            "归并作品并补全元数据",
            local_candidates_count=len(local_candidates),
            kikoeru_candidates_count=len(kikoeru_candidates),
            dlsite_candidates_count=len(dlsite_candidates),
            combined_candidates_count=len(combined_candidates),
            circle_query_hint=invalid_circle_query_hint,
        )
        if not combined_candidates:
            identity = self.resolve_circle_identity("", circle_query, circle_query)
        else:
            preferred = next((item for item in combined_candidates if item.get("maker_id")), combined_candidates[0])
            identity = self.resolve_circle_identity(preferred.get("maker_id"), preferred.get("maker_name"), circle_query)

        if not identity.get("maker_id") and combined_candidates:
            fallback_identity = await self._resolve_identity_from_candidates(
                circle_query,
                combined_candidates,
                progress_callback=report,
            )
            if fallback_identity.get("maker_id"):
                identity = self.resolve_circle_identity(
                    fallback_identity.get("maker_id"),
                    fallback_identity.get("maker_name") or circle_query,
                    circle_query,
                )
                if resolved_kikoeru_circle_id:
                    self._set_cached_kikoeru_circle_id(
                        resolved_kikoeru_circle_id,
                        f"maker:{str(identity['maker_id']).strip().upper()}",
                    )
                    self._save_persisted_kikoeru_circle_id(
                        self.normalize_circle_name(circle_query),
                        resolved_kikoeru_circle_id,
                        str(identity["maker_id"] or "").strip(),
                    )

        circle_id = identity["circle_id"]
        if (not circle_id or str(circle_id).strip().lower().startswith("name:")) and resolved_kikoeru_circle_id:
            circle_id = resolved_kikoeru_circle_id
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
            if invalid_circle_query_hint:
                raise ValueError(
                    f"未识别到有效社团标识，已跳过入社团目录。{invalid_circle_query_hint}"
                )
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
        candidate_semaphore = asyncio.Semaphore(16)

        # ============ Phase 1：一次性批量预取所有外部数据 ============
        # 旧流程是 "DLsite metadata 预取 → prepare_candidate → ASMR 检查 → Kikoeru 补查"
        # 4 段串行（每段内有并发，但 bucket 间是 semaphore=10/12 的"中等并发"）。
        #
        # 新流程把 DLsite / ASMR.one 外部 HTTP 集中到 ``_collect_external_snapshot()`` 一次跑完：
        #   Wave 1：拉 DLsite 作品资料 + 解析作品链路（candidate × 20 并发）。
        #   Wave 2a：在 ASMR.one 上核对每个 RJ 是否存在（30 并发，含翻译版全集）。
        #   本地拥有 / 字幕态：后续通过 ready 库存索引批量投影，不在这里触发 Kikoeru HTTP。
        #
        # Phase 2 阶段所有外部调用均 cache 命中（asmr 走 snapshot、DLsite 走
        # ``_metadata_cache`` / ``_canonical_cache``），
        # 不再产生网络往返。
        snapshot_candidates = [self.normalize_rjcode(c.get("rjcode")) for c in combined_candidates]
        snapshot_candidates = [r for r in snapshot_candidates if r]
        if snapshot_candidates:
            # snapshot 内部用 0-100 相对刻度回报，主流程映射到 54-72 区间
            def _snapshot_progress(rel_pct: int, step: str, **meta: Any) -> None:
                rel_pct = max(0, min(100, int(rel_pct)))
                mapped = 54 + int(rel_pct * 0.18)  # 54 + 0..18 → 54..72
                report(mapped, step, **meta)

            report(
                54,
                f"准备核对 {len(snapshot_candidates)} 件候选作品的 DLsite / ASMR.one 状态",
                prefetch_count=len(snapshot_candidates),
            )
            with perf.timed("stage_external_snapshot"):
                external_snapshot = await self._collect_external_snapshot(
                    snapshot_candidates,
                    force_refresh=force_refresh,
                    progress_callback=_snapshot_progress,
                    cancel_callback=cancel_callback,
                    perf=perf,
                )
        else:
            external_snapshot = CircleCompletionSnapshot()

        async def prepare_candidate(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """整理 candidate -> bucket 数据。

            ★ P2 优化：candidate 自己的 metadata 完全不拉，只对 **canonical + preferred**
            两条 RJ 拉完整 metadata（含 product/info/ajax 特典字段）。如果 candidate
            本身就是 canonical 或 preferred，会自然命中 cache 不重复拉。
            ``_classify_asmr_work_candidate`` 用 ``product.json`` API（wave 1 已经
            热好的 cache）兜底，零外部 IO；``_candidate_belongs_to_identity`` 用
            canonical_metadata 的 maker_name 校验，依然有效。
            翻译版只要不是 preferred，``product/info/ajax`` 一次都不会被打。
            """
            ensure_not_cancelled()
            rjcode = self.normalize_rjcode(item.get("rjcode"))
            if not rjcode:
                return None
            async with candidate_semaphore:
                # candidate 自己的 metadata 不再拉。``_classify_asmr_work_candidate``
                # 用 product.json API cache 兜底（wave 1 的 resolve_canonical_rj 已经热好）。
                # dlsite 候选在 fetch_candidate 阶段已完成 ASMR 检查，此处跳过避免重复调用 DLsite API
                if not item.get("_asmr_checked") and not await self._is_asmr_work_candidate(rjcode, None):
                    return None
                # P4：优先复用 external_snapshot 已经算好的 canonical / canonical_info。
                # Wave 1 已经在 force_refresh=True 时刷新过 DLsite 关联链；prepare_candidate
                # 阶段保持 refresh=False 即可保证零重复 resolve_canonical_rj 调用。
                canonical_info = None
                canonical = ""
                snap_canonical = external_snapshot.get_canonical_rj(rjcode) if external_snapshot else None
                if snap_canonical:
                    canonical = snap_canonical
                    canonical_info = (external_snapshot.canonical_info_by_canonical.get(snap_canonical) or {}).copy()
                    if canonical_info and not canonical_info.get("canonical_rjcode"):
                        canonical_info["canonical_rjcode"] = snap_canonical
                if not canonical_info:
                    canonical_info = await self.resolve_canonical_rj(rjcode, refresh=False)
                    canonical = canonical_info.get("canonical_rjcode") or rjcode

                # ★ 修复 BUG #3（韩英 / 其他外语版被独立成卡）：
                # 在 input rjcode 自己的 link_map 信号下，直接判定它是否属于"非简繁日"分组。
                # 配合 ``dlsite_service`` 中的 BUG #1 修复：
                # - 当 DLsite 父作品 API 给出明确 ``language_editions`` 时，input 在 link_map
                #   里的 lang 是真实的（如 ``KO_KR`` / ``ENG``）→ ``_variant_group`` 归为 "other"。
                # - 当 input 自己 API 拿不到（已下架 / R18 限制 / 网络错误）时，``get_translation_info``
                #   不再默认 ``is_original=True``，``_get_direct_linked_works`` 的 else 分支会标
                #   ``work_type='unknown', lang='UNKNOWN'`` → ``_variant_group`` 同样归为 "other"。
                # 命中 "other" 即过滤掉这条 candidate，避免创建独立 bucket 导致同一父作品
                # 多卡片并存（如截图里 RJ01294458 韩语版被错配简中标题独立成卡）。
                # 注意：input 是外语版时，该作品的简繁中/原作版仍会作为其他 candidate 独立
                # 进 ``prepare_candidate``，最终聚合到正确的 canonical bucket，不会丢作品。
                input_link_meta = (canonical_info.get("link_map") or {}).get(rjcode) or {}
                input_group = self._variant_group(
                    input_link_meta.get("link_type"),
                    input_link_meta.get("lang"),
                ).get("key")
                if input_group == "other":
                    return None

                # ★ 只对 canonical 拉一次完整 metadata：用于 OR is_bonus_work、maker_name 校验、
                # foreign_lang 判定、bucket 字段兜底。
                try:
                    canonical_metadata = await self._fetch_metadata_dict(canonical)
                except Exception:
                    canonical_metadata = {}
                display_metadata_map: Dict[str, Dict[str, Any]] = {}
                if canonical:
                    display_metadata_map[self.normalize_rjcode(canonical)] = canonical_metadata or {}
                preferred_variant, preferred_title, allowed_variants = await self._pick_public_display_variant_and_title(
                    canonical_info,
                    canonical or rjcode,
                    display_metadata_map,
                )
                preferred_rjcode = self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical or rjcode
                preferred_metadata = display_metadata_map.get(preferred_rjcode) or {}
                # ★ 只对 preferred 拉一次完整 metadata（用于 title / cover / price / bonus OR）。
                # 如果 preferred 就是 canonical，直接复用 canonical_metadata，零成本。
                if preferred_rjcode and not preferred_metadata:
                    if preferred_rjcode == self.normalize_rjcode(canonical):
                        preferred_metadata = canonical_metadata
                    else:
                        try:
                            preferred_metadata = await self._fetch_metadata_dict(preferred_rjcode)
                        except Exception:
                            preferred_metadata = canonical_metadata
                    display_metadata_map[preferred_rjcode] = preferred_metadata or {}
                foreign_lang = self._looks_like_non_chinese_translation_title(
                    preferred_title,
                    canonical_metadata.get("work_name"),
                    item.get("title"),
                )
                if foreign_lang:
                    return None
                # candidate 自己的 metadata 已不再拉，``_candidate_belongs_to_identity``
                # 用 canonical_metadata 的 maker_name 即可（同一条作品链路 maker_id 必相同）。
                if not self._candidate_belongs_to_identity(
                    circle_query=circle_query,
                    identity=identity,
                    item=item,
                    metadata={},
                    canonical_metadata=canonical_metadata or {},
                ):
                    return None
            return {
                "item": item,
                "rjcode": rjcode,
                # P2: candidate 自己的 metadata 已废弃，下游聚合阶段全部用
                # canonical_metadata / preferred_metadata。这里返 {} 保持字段存在，
                # 让现有 ``prepared["metadata"]`` 调用点不需要 KeyError 防御。
                "metadata": {},
                "canonical_info": canonical_info,
                "canonical": canonical,
                "canonical_metadata": canonical_metadata or {},
                "preferred_variant": preferred_variant,
                "preferred_metadata": preferred_metadata or {},
                "preferred_title": preferred_title,
                "public_linked_rjcodes": [variant["rjcode"] for variant in allowed_variants if variant.get("rjcode")],
            }

        _prepare_started_at = time.monotonic()

        # ⚠ 关键设计修正（用户洞察）：
        # 旧实现对**每个 candidate**单独跑 prepare_candidate，278 candidate × 1-2 次
        # metadata fetch ≈ 16 分钟。但 278 candidate 里**多个翻译版共享同一个 canonical**
        # （278 candidate → 实测 ~150 canonical），重复跑 prepare_candidate 完全是浪费。
        #
        # 正确设计："只对最优 RJ 拉元信息，其他翻译版只记录 RJ 号"。实现方式：
        #   1. 用 ``external_snapshot.get_canonical_rj`` 把 candidates 按 canonical 分组
        #   2. 对每个 canonical 唯一一次跑 prepare_candidate（用任一 primary item 作输入）
        #   3. 聚合阶段对该 canonical 下**所有** items 合并 source_flags
        #
        # 收益：metadata fetch 调用从 278+ → ~150-200 次；prepare wrapping 从 278 → ~150 次。
        # 配合 ``_metadata_inflight`` 单飞锁，stage_prepare_candidates 16 分钟 → ~2 分钟。
        candidates_by_canonical: Dict[str, List[Dict[str, Any]]] = {}
        for raw_item in combined_candidates:
            raw_rj = self.normalize_rjcode(raw_item.get("rjcode"))
            if not raw_rj:
                continue
            snap_canonical = (
                external_snapshot.get_canonical_rj(raw_rj) if external_snapshot else None
            ) or raw_rj
            candidates_by_canonical.setdefault(snap_canonical, []).append(raw_item)
        if perf:
            perf.inc("prepare_canonical_buckets", len(candidates_by_canonical))
            perf.inc("prepare_candidate_inputs", len(combined_candidates))

        async def prepare_canonical(
            canonical_key: str,
            items: List[Dict[str, Any]],
        ) -> Optional[Dict[str, Any]]:
            """对一个 canonical 唯一一次跑 prepare：拉 canonical/preferred metadata、
            校验 ASMR、身份匹配。返回的 ``items`` 里包含所有该 canonical 下的原 candidates，
            供聚合阶段合并 source_flags。
            """
            # 选第一个 dlsite 来源的作为 primary（dlsite 候选 product.json 已 cache 热好；
            # kikoeru/local 来源时缺一些字段也无所谓，因为下游主要用 canonical_metadata）。
            primary_item = next(
                (it for it in items if str(it.get("source") or "") == "dlsite"),
                items[0],
            )
            # 把 primary_item 的 rjcode 设为 canonical（让 prepare_candidate 内部走"input 即
            # canonical"的最优路径，跳过 lang=other 过滤、避免 prepare 内再 resolve_canonical_rj）。
            forwarded_item = dict(primary_item)
            forwarded_item["rjcode"] = canonical_key
            # primary 来自 dlsite 时 _asmr_checked 已经标了；其他 source 时让 prepare 自己 probe。
            prepared = await prepare_candidate(forwarded_item)
            if not prepared:
                return None
            prepared["items"] = items  # 保留所有 candidates，聚合阶段合并 source
            return prepared

        for future in asyncio.as_completed([
            prepare_canonical(canonical_key, items_list)
            for canonical_key, items_list in candidates_by_canonical.items()
        ]):
            prepared = await future
            metadata_checked += 1
            if not prepared:
                report(
                    72 + int((metadata_checked / total_candidates) * 2),
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
            preferred_metadata = prepared["preferred_metadata"]
            preferred_title = prepared["preferred_title"]
            public_linked_rjcodes = prepared["public_linked_rjcodes"]
            if only_new_works and canonical in existing_canonical_rjcodes:
                skipped_existing += 1
                report(
                    72 + int((metadata_checked / total_candidates) * 2),
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
                "price_text": str(
                    preferred_metadata.get("price_text")
                    or metadata.get("price_text")
                    or canonical_metadata.get("price_text")
                    or item.get("price_text")
                    or ""
                ).strip(),
                "is_bonus_work": bool(canonical_metadata.get("is_bonus_work")) or bool(preferred_metadata.get("is_bonus_work")),
                "has_bonus": bool(canonical_metadata.get("has_bonus")) or bool(preferred_metadata.get("has_bonus")),
                "preferred_variant_label": self._variant_label(preferred_variant["link_type"], preferred_variant["lang"]),
                "preferred_lang": preferred_variant["lang"],
                "preferred_link_type": preferred_variant["link_type"],
            })
            bucket["display_rjcode"] = preferred_variant["rjcode"] or canonical or rjcode
            bucket["title"] = preferred_title or bucket["title"] or str(canonical_metadata.get("work_name") or item.get("title") or metadata.get("work_name") or "")
            bucket["maker_id"] = bucket["maker_id"] or str(canonical_metadata.get("maker_id") or metadata.get("maker_id") or item.get("maker_id") or "")
            bucket["maker_name"] = bucket["maker_name"] or str(canonical_metadata.get("maker_name") or metadata.get("maker_name") or item.get("maker_name") or circle_query)
            if not str(bucket.get("price_text") or "").strip():
                bucket["price_text"] = str(preferred_metadata.get("price_text") or metadata.get("price_text") or canonical_metadata.get("price_text") or item.get("price_text") or "").strip()
            bucket["is_bonus_work"] = bool(canonical_metadata.get("is_bonus_work")) or bool(preferred_metadata.get("is_bonus_work"))
            bucket["has_bonus"] = bool(canonical_metadata.get("has_bonus")) or bool(preferred_metadata.get("has_bonus"))
            release_date = str(canonical_metadata.get("release_date") or metadata.get("release_date") or item.get("release_date") or "").strip()
            is_unreleased = self._is_future_release_date(release_date)
            def _valid_cover(*urls: Any) -> str:
                for u in urls:
                    s = str(u or "").strip()
                    if s.startswith("https://"):
                        return s
                return ""
            bucket["image_url"] = self._normalize_dlsite_cover_url(
                _valid_cover(
                    bucket.get("image_url"),
                    canonical_metadata.get("cover_url"),
                    metadata.get("cover_url"),
                    item.get("image_url"),
                ),
                bucket.get("display_rjcode") or canonical or rjcode,
                is_unreleased=is_unreleased,
            )
            bucket["linked_rjcodes"] = public_linked_rjcodes or bucket["linked_rjcodes"]
            bucket["preferred_variant_label"] = self._variant_label(preferred_variant["link_type"], preferred_variant["lang"])
            bucket["preferred_lang"] = preferred_variant["lang"]
            bucket["preferred_link_type"] = preferred_variant["link_type"]
            # ⚠ 设计修正：``prepare_canonical`` 返回的 ``items`` 包含该 canonical 下所有原 candidates。
            # 遍历全部 items 合并 source_flags / kikoeru_found_rjcodes / kikoeru_work_id，
            # 不再像旧实现只看 primary 的 source（旧实现 278 个 candidate 各自进 bucket，
            # 自然把 source 都覆盖到了；新实现按 canonical 一次进 bucket，必须显式合并）。
            sibling_items: List[Dict[str, Any]] = prepared.get("items") or [item]
            for sibling in sibling_items:
                sibling_rj = self.normalize_rjcode(sibling.get("rjcode")) or rjcode
                sibling_source = str(sibling.get("source") or "").strip()
                if sibling_source:
                    bucket["source_flags"].add(sibling_source)
                if sibling_source == "kikoeru":
                    bucket["has_kikoeru"] = True
                    if sibling_rj and sibling_rj not in bucket["kikoeru_found_rjcodes"]:
                        bucket["kikoeru_found_rjcodes"].append(sibling_rj)
                    if sibling.get("kikoeru_work_id") and not bucket.get("kikoeru_work_id"):
                        try:
                            bucket["kikoeru_work_id"] = int(sibling["kikoeru_work_id"])
                        except Exception:
                            pass
                if sibling_source == "dlsite":
                    bucket["has_dlsite"] = True
                if sibling_source == "local":
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

        perf.add_stage("stage_prepare_candidates", (time.monotonic() - _prepare_started_at) * 1000)
        report(74, "检查 asmr.one 可下载状态", aggregated_count=len(aggregated))
        _asmr_check_started_at = time.monotonic()
        checked_asmr = 0
        asmr_available = 0
        total_aggregated = max(1, len(aggregated))
        asmr_semaphore = asyncio.Semaphore(12)

        async def load_probe_inputs() -> List[tuple[str, Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Any]]]:
            db = SessionLocal()
            try:
                link_rows = (
                    db.query(WorkCanonicalLink)
                    .filter(
                        WorkCanonicalLink.evidence_status == "verified",
                        WorkCanonicalLink.canonical_rjcode.in_(list(aggregated.keys())),
                    )
                    .all()
                    if aggregated else []
                )
                link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
                for link_row in link_rows:
                    link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                        "link_type": str(link_row.link_type or ""),
                        "lang": str(link_row.lang or ""),
                    }
                # 一次性收集所有需要查询的 rjcodes，批量查询 metadata，避免 N 次 DB 往返
                all_linked_rjcodes: Set[str] = set()
                for item in aggregated.values():
                    for code in list(item.get("linked_rjcodes") or [item.get("display_rjcode") or ""]):
                        norm = self.normalize_rjcode(code)
                        if norm:
                            all_linked_rjcodes.add(norm)
                bulk_metadata_map = self._load_cached_metadata_map(db, list(all_linked_rjcodes))
                payloads = []
                for canonical, item in aggregated.items():
                    linked_rjcodes = list(item.get("linked_rjcodes") or [item.get("display_rjcode") or canonical])
                    metadata_map = {rj: bulk_metadata_map.get(rj, {}) for rj in linked_rjcodes}
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
                # ★ Phase 2：传 snapshot 让 _find_public_downloadable_work 全本地查询，
                #   不再调 fetch_work_info / fetch_track_list 打 HTTP。
                actual_rjcode, _ = await self._find_public_downloadable_work(
                    canonical_info,
                    item.get("display_rjcode") or canonical,
                    metadata_map=metadata_map,
                    extra_candidates=[item.get("asmr_available_rjcode"), item.get("display_rjcode"), canonical],
                    snapshot=external_snapshot,
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

        perf.add_stage("stage_asmr_check", (time.monotonic() - _asmr_check_started_at) * 1000)
        report(90, "从库存索引核对本地收录态", aggregated_count=len(aggregated))
        _local_owned_check_started_at = time.monotonic()
        local_owned_stats = self._apply_library_index_owned_state_to_items(aggregated)
        if perf:
            perf.inc("local_index_owned_count", int(local_owned_stats.get("owned_count") or 0))
            perf.inc("local_index_subtitle_count", int(local_owned_stats.get("subtitle_count") or 0))
            perf.inc("local_index_hit_count", int(local_owned_stats.get("hit_count") or 0))
        report(
            92,
            "库存索引收录态核对完成",
            local_owned_count=int(local_owned_stats.get("owned_count") or 0),
            local_subtitle_count=int(local_owned_stats.get("subtitle_count") or 0),
            local_index_hit_count=int(local_owned_stats.get("hit_count") or 0),
        )

        perf.add_stage("stage_local_owned_check", (time.monotonic() - _local_owned_check_started_at) * 1000)
        # 把封面图同步缓存到本地 data/img/，避免前端每次都从 dlsite 加载，
        # dlsite 图片 CDN 在国内偶发抖动 / 代理掉链时整个社团页都会"白板"。
        # 卡片图和列表小图分开缓存：卡片图保留 RJxxxx.jpg，列表图写 RJxxxx_sam.jpg。
        image_cache_service = get_circle_image_cache_service()
        cover_download_pairs: List[Tuple[str, str]] = []
        thumb_download_pairs: List[Tuple[str, str]] = []
        for canonical_rj, item in aggregated.items():
            cover_url = str(item.get("image_url") or "").strip()
            display_rj = self.normalize_rjcode(item.get("display_rjcode")) or canonical_rj
            if not display_rj or not cover_url.startswith(("http://", "https://")):
                continue
            cover_cache_rjcode = image_cache_service.cache_rjcode_for_url(cover_url, display_rj)
            if not cover_cache_rjcode:
                continue
            cover_download_pairs.append((cover_cache_rjcode, cover_url))
            thumb_url = self._normalize_dlsite_thumb_url(
                cover_url,
                display_rj,
                is_unreleased=self._is_future_release_date(item.get("release_date")),
            )
            if thumb_url.startswith(("http://", "https://")):
                thumb_download_pairs.append((cover_cache_rjcode, thumb_url))
        if cover_download_pairs or thumb_download_pairs:
            # P6：封面缓存后台化。索引完成即可返回，封面下载不阻塞 progress。
            self._schedule_circle_cover_cache(circle_id, cover_download_pairs, thumb_download_pairs)
            report(
                92,
                f"已派发后台封面缓存任务 {len(cover_download_pairs)} / 列表小图 {len(thumb_download_pairs)}",
                cover_total=len(cover_download_pairs),
                cover_thumb_total=len(thumb_download_pairs),
                cover_background=True,
            )

        report(94, "写入社团索引")
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
                row.price_text = str(item.get("price_text") or "").strip() or None
                row.is_bonus_work = bool(item.get("is_bonus_work"))
                row.has_bonus = bool(item.get("has_bonus"))
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
            owned_rows_written = self._upsert_library_owned_rows_from_items(
                db,
                aggregated,
                prune_unmatched=bool(local_owned_stats.get("ready_index_available")),
            )
            if perf:
                perf.inc("local_owned_rows_written", owned_rows_written)
                perf.inc(
                    "local_index_ready_available",
                    1 if local_owned_stats.get("ready_index_available") else 0,
                )
            if not only_new_works and aggregated:
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

        # ★ bonus 字段补刷统一收口在写路径里跑一次：
        # ``_apply_dlsite_bonus_info`` 只覆盖了"本次真正向 DLsite 拉了一次 product 的"
        # 路径，``_fetch_metadata_dict`` 命中本地 cache 时完全不会触发 bonus 拉取，
        # 这就让"老 schema 留下来的存量条目"永远卡在 bonus_info_checked_at=NULL。
        # 浏览路径已经退化成纯 DB 读、不再补刷，所以必须在这里把当前社团里所有
        # 关联 RJ 走 ``_refresh_circle_bonus_fields``：内部会先调
        # ``lazy_refresh_bonus_for_cached_rjcodes`` 补刷 work_metadata，再把
        # 结果同步到 circle_works。
        # P7：bonus 字段补刷后台化。``_refresh_circle_bonus_fields`` 内部会触发
        # ``lazy_refresh_bonus_for_cached_rjcodes`` 即 DLsite ``product/info/ajax`` 拉取，
        # 全社团范围跑通是分钟级开销。前端可在补刷完后再次刷新拿到特典 chip，无需阻塞索引返回。
        bonus_lookup_rjcodes: List[str] = []
        for canonical, item in aggregated.items():
            for code in [
                canonical,
                item.get("display_rjcode") or "",
                *(item.get("linked_rjcodes") or []),
            ]:
                normalized = self.normalize_rjcode(code)
                if normalized and normalized not in bonus_lookup_rjcodes:
                    bonus_lookup_rjcodes.append(normalized)
        report(
            96,
            "已派发后台特典字段补刷任务",
            circle_id=circle_id,
            bonus_lookup_total=len(bonus_lookup_rjcodes),
            bonus_background=True,
        )
        self._schedule_circle_bonus_refresh(circle_id, bonus_lookup_rjcodes)

        report(97, "生成社团视图摘要", circle_id=circle_id)
        self.invalidate_completion_view_cache(circle_id)
        summary = await self.build_circle_completion_view(circle_id)
        indexed_counts = {
            "works": len(summary.get("works") or []),
            "local_owned_count": int(summary.get("local_owned_count") or 0),
            "owned_count": int(summary.get("owned_count") or 0),
            "missing_count": int(summary.get("missing_count") or 0),
            "downloadable_count": int(summary.get("downloadable_count") or 0),
            "dl_count": int(summary.get("dl_count") or 0),
        }
        _index_duration_ms = max(0, int((time.monotonic() - _index_start_monotonic) * 1000))
        # P0：完整耗时画像写进 detail.perf，方便后续 SQL 聚合 / Grafana 面板。
        perf_payload = perf.snapshot()
        log_circle_completion_event(
            "index_completed",
            summary=(
                f"本地有 {indexed_counts['local_owned_count']} 个 / "
                f"库存已收录 {indexed_counts['owned_count']} 个 / "
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
                "duration_ms": _index_duration_ms,
                "task_duration_ms": _index_duration_ms,
                "perf": perf_payload,
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
        try:
            logger.info(
                "[社团补全·perf] circle_id=%s duration_ms=%s stages=%s counters=%s",
                circle_id, _index_duration_ms,
                perf_payload.get("stage_ms"),
                perf_payload.get("counters"),
            )
        except Exception:
            logger.debug("[社团补全·perf] 日志输出失败", exc_info=True)
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
        """
        返回最近索引的社团目录卡片数据（左侧目录用）。

        关键修复（vs. 旧版）：
        - SQL 端 LIKE 过滤 + 排序 + LIMIT，不再 .all() 拉全表后再 Python 过滤；
          社团数量大时显著降低延迟、降低数据库锁占用。
        - server_owned / missing 与 build_circle_completion_view 对齐：
          通过 LEFT JOIN LibraryOwnedWork 把"本地已有但服务器没有"的作品也算进
          完整 owned，否则左侧"缺失 N 个"和右侧"缺失 M 个"长期对不上。
        - 新作判定改为 48h 窗口；时间基准用 CircleWork.email_watcher_first_seen_at
          （只在邮件首次发现时写入，不会被 onupdate 刷新），fallback 到 created_at。
          避免老作品被全量索引刷新 updated_at 后被误判为"新作"的 BUG。
        """
        from sqlalchemy import text as sa_text

        started_at = time.perf_counter()
        stage_costs: Dict[str, int] = {}
        last_stage_at = started_at

        def mark_stage(name: str) -> None:
            nonlocal last_stage_at
            now = time.perf_counter()
            stage_costs[name] = int((now - last_stage_at) * 1000)
            last_stage_at = now

        normalized = self.normalize_circle_name(keyword)
        safe_limit = max(1, int(limit))

        recent_cache_key = self._completion_recent_cache_key(keyword, safe_limit)
        cached_recent = self._completion_l1_l2_get(self._completion_recent_cache, "recent", recent_cache_key)
        if isinstance(cached_recent, list):
            return cached_recent

        db = SessionLocal()
        try:
            catalog_query = db.query(CircleCatalog).order_by(CircleCatalog.last_indexed_at.desc())
            if normalized:
                escaped = normalized.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                pattern = f"%{escaped}%"
                catalog_query = catalog_query.filter(
                    sa_text(
                        """
                        (COALESCE(circle_name_normalized, '') || ' ' ||
                         COALESCE(circle_name, '') || ' ' ||
                         COALESCE(circle_id, '')) ILIKE :circle_catalog_search_pattern ESCAPE '!'
                        """
                    ).bindparams(circle_catalog_search_pattern=pattern)
                )
            # 留少量冗余给同名去重，避免去重后不足 safe_limit。
            rows = catalog_query.limit(safe_limit * 2 + 16).all()

            out: List[Dict[str, Any]] = []
            seen_keys: Set[str] = set()
            collected_ids: List[str] = []
            for row in rows:
                dedupe_key = str(row.circle_name_normalized or "").strip() or str(row.circle_id or "").strip()
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                out.append(row.to_dict())
                collected_ids.append(row.circle_id)
                if len(out) >= safe_limit:
                    break
            mark_stage("catalog_query")

            if collected_ids:
                # === 完整 owned 计算（与右侧详情对齐）===
                # LEFT JOIN LibraryOwnedWork：CircleWork × LibraryOwnedWork 是 1 对 1，
                # 不会膨胀；在 Python 端做聚合，避免数据库 case-when 跨方言复杂度。
                work_join_rows = (
                    db.query(
                        CircleWork.circle_id.label("circle_id"),
                        CircleWork.has_asmr_one.label("has_asmr_one"),
                        CircleWork.has_dlsite.label("has_dlsite"),
                        LibraryOwnedWork.canonical_rjcode.label("local_canonical"),
                    )
                    .outerjoin(
                        LibraryOwnedWork,
                        LibraryOwnedWork.canonical_rjcode == CircleWork.canonical_rjcode,
                    )
                    .filter(CircleWork.circle_id.in_(collected_ids))
                    .all()
                )
                stats_map: Dict[str, Dict[str, int]] = {}
                for r in work_join_rows:
                    s = stats_map.setdefault(r.circle_id, {
                        "total_works": 0,
                        "kikoeru_owned": 0,
                        "asmr_available": 0,
                        "dl_works": 0,
                        "owned": 0,
                        "local_owned": 0,
                    })
                    s["total_works"] += 1
                    if r.has_asmr_one:
                        s["asmr_available"] += 1
                    if r.has_dlsite:
                        s["dl_works"] += 1
                    is_local_owned = r.local_canonical is not None
                    if is_local_owned:
                        s["local_owned"] += 1
                        s["kikoeru_owned"] += 1
                        s["owned"] += 1
                mark_stage("stats_query")

                for item in out:
                    stats = stats_map.get(item["circle_id"], {})
                    total = int(stats.get("total_works", 0))
                    owned = int(stats.get("owned", 0))
                    item["total_works"] = total
                    item["dl_works"] = int(stats.get("dl_works", 0))
                    item["asmr_available"] = int(stats.get("asmr_available", 0))
                    # server_owned 在新口径下表示"完整已满足"，与右侧 owned_count 对齐；
                    # 同时给前端将来需要分维度展示时用的纯 kikoeru / 本地两个独立字段。
                    item["server_owned"] = owned
                    item["server_owned_count"] = owned
                    item["owned_count"] = owned
                    item["kikoeru_owned_count"] = int(stats.get("kikoeru_owned", 0))
                    item["local_owned_count"] = int(stats.get("local_owned", 0))
                    item["missing"] = max(0, total - owned)

                # === 新作判定：48h 窗口 + email_watcher_first_seen_at 时间锚 ===
                tag_rows = (
                    db.query(
                        CircleWork.circle_id,
                        CircleWork.source_tags,
                        CircleWork.email_watcher_first_seen_at,
                        CircleWork.created_at,
                    )
                    .filter(CircleWork.circle_id.in_(collected_ids))
                    .all()
                )
                new_work_map: Dict[str, int] = {}
                new_work_48h_map: Dict[str, int] = {}
                now_local = get_local_now()
                window_seconds = 48 * 60 * 60
                for tr in tag_rows:
                    tags = tr.source_tags
                    if not (isinstance(tags, list) and "email_watcher" in tags):
                        continue
                    new_work_map[tr.circle_id] = new_work_map.get(tr.circle_id, 0) + 1
                    # 优先 email_watcher_first_seen_at（专用稳定锚），fallback 到 created_at；
                    # 不再使用 updated_at —— 它会被 onupdate 刷新，导致老作品被误判为新作。
                    anchor = tr.email_watcher_first_seen_at or tr.created_at
                    if anchor and hasattr(anchor, "timestamp"):
                        age_seconds = now_local.timestamp() - anchor.timestamp()
                        if 0 <= age_seconds <= window_seconds:
                            new_work_48h_map[tr.circle_id] = new_work_48h_map.get(tr.circle_id, 0) + 1
                mark_stage("new_work_query")

                # 批量统计未发售：左侧目录只提示仍未满足的预售作品，口径和右侧
                # 缺失作品区保持一致。已收录 / 本地已有的历史状态不再污染目录徽章。
                unreleased_rows = (
                    db.query(
                        CircleWork.circle_id,
                        WorkMetadata.release_date,
                        LibraryOwnedWork.canonical_rjcode.label("local_canonical"),
                    )
                    .join(WorkMetadata, WorkMetadata.rjcode == CircleWork.canonical_rjcode)
                    .outerjoin(
                        LibraryOwnedWork,
                        LibraryOwnedWork.canonical_rjcode == CircleWork.canonical_rjcode,
                    )
                    .filter(CircleWork.circle_id.in_(collected_ids))
                    .all()
                )
                unreleased_map: Dict[str, int] = {}
                for ur in unreleased_rows:
                    if ur.local_canonical is not None:
                        continue
                    if self._is_future_release_date(ur.release_date):
                        unreleased_map[ur.circle_id] = unreleased_map.get(ur.circle_id, 0) + 1

                for item in out:
                    cid = item["circle_id"]
                    item["unreleased_count"] = unreleased_map.get(cid, 0)
                    item["new_works_count"] = new_work_map.get(cid, 0)
                    item["new_works_48h_count"] = new_work_48h_map.get(cid, 0)
                    # 兼容字段：老前端 bundle 仍可能读 new_works_24h_count；
                    # 新口径下让它指向 48h 数值，不会出现"显示 24h 但其实是 48h"
                    # 之外的语义偏差，因为本来产品定义就是 48h 内为新作。
                    item["new_works_24h_count"] = new_work_48h_map.get(cid, 0)
                mark_stage("unreleased_query")

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            if elapsed_ms >= 300:
                logger.info(
                    "[社团补全·目录耗时] keyword=%s limit=%s returned=%s elapsed=%sms stages=%s",
                    keyword,
                    safe_limit,
                    len(out),
                    elapsed_ms,
                    stage_costs,
                )
            self._completion_l1_l2_set(
                self._completion_recent_cache,
                "recent",
                recent_cache_key,
                out,
                ttl_seconds=self._COMPLETION_RECENT_REDIS_TTL_SECONDS,
            )
            return deepcopy(out)
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
        cache_key = self._completion_view_cache_key(
            circle_id_or_query,
            only_missing=only_missing,
            only_downloadable=only_downloadable,
            include_dl_only=include_dl_only,
        )
        cached_result = self._completion_view_cache.get(cache_key)
        if cached_result is not None:
            return deepcopy(cached_result)

        started_at = time.perf_counter()
        last_stage_at = started_at
        stage_costs: Dict[str, int] = {}

        def mark_stage(name: str) -> None:
            nonlocal last_stage_at
            now = time.perf_counter()
            stage_costs[name] = int((now - last_stage_at) * 1000)
            last_stage_at = now

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
                .filter(
                    WorkCanonicalLink.evidence_status == "verified",
                    WorkCanonicalLink.canonical_rjcode.in_(work_canonical_rjcodes),
                )
                .all()
                if works else []
            )
            link_map_by_canonical: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            for link_row in link_rows:
                link_map_by_canonical[str(link_row.canonical_rjcode or "")][str(link_row.linked_rjcode or "")] = {
                    "link_type": str(link_row.link_type or ""),
                    "lang": str(link_row.lang or ""),
                }
            mark_stage("db_query")
            local_download_session_map = self._build_local_download_session_map(db, works, link_map_by_canonical)
            mark_stage("local_download_map")

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
            mark_stage("metadata_map")

            # ★ bonus 字段补刷已移到 ``index_circle_catalog`` / ``refresh_circle_works``
            #   写路径里：浏览路径不再做任何外部 HTTP 探测，row.is_bonus_work /
            #   row.has_bonus 直接读 DB 现值即可。
            #   - 旧实现是在这里对每个 ``bonus_info_checked_at IS NULL`` 的条目调
            #     ``lazy_refresh_bonus_for_cached_rjcodes`` "顺手补刷"，DLsite 端
            #     虽有 24h cache，但社团首次浏览仍要等 N 次 product_info_ajax
            #     回来才能渲染，体验和"索引"行为混淆，被用户反馈"点社团特别慢"。
            #   - 现在 bonus 写入只走三条写路径，和 has_kikoeru / has_asmr_one
            #     等其他状态字段对齐：
            #       - index_circle_catalog（建立 / 刷新整个社团索引）
            #       - refresh_circle_works（刷新选中作品）
            #       - email_watcher 直入（_upsert_email_release_work）

            # 注意：详情视图是"纯数据库读"路径，不再做任何 kikoeru / 外部 API 探测。
            # 旧实现里曾经在这里对每个 has_kikoeru=False 的作品同步去 kikoeru 服务器
            # 探一遍（以"顺便回填 has_kikoeru"），结果就是用户点一次社团卡片要等
            # N 个 HTTP 请求，体验和"索引"行为混淆。状态写入应该集中在三个写路径：
            #   - index_circle_catalog（建立 / 刷新整个社团索引）
            #   - refresh_circle_works（刷新选中作品）
            #   - email_watcher 直入（_upsert_email_release_work）
            # 浏览路径只把数据库里的现状直接呈现出来。
            #
            # 这里也顺便给每个作品打 is_new_work 标记，使用与左侧 search_circles
            # 完全一致的口径（email_watcher 来源 + 48h 窗口 + email_watcher_first_seen_at
            # 锚，fallback 到 created_at）。前端 WorkCard / WorkListRow / 工具栏
            # "新作 N" 统一读这一个字段，避免左右两侧出现"左边没有新作但右边
            # 还闪新作特效"这种口径漂移。
            now_local_for_view = get_local_now()
            new_work_window_seconds = 48 * 60 * 60
            # 详情接口必须保持纯读、快返回。封面在索引 / 刷新阶段缓存；
            # 浏览阶段只做本地命中判断，不能再为了补图把整个详情请求拖进网络下载。
            image_cache_service = get_circle_image_cache_service()
            items = []
            for row in works:
                owned_row = owned_rows.get(row.canonical_rjcode)
                local_owned = owned_row is not None
                item = row.to_dict()
                item["circle_name"] = catalog.circle_name
                item["local_owned"] = local_owned
                item["local_folder_size"] = int(getattr(owned_row, "folder_size", 0) or 0) if owned_row else 0
                item["local_file_count"] = int(getattr(owned_row, "file_count", 0) or 0) if owned_row else 0
                item["local_subtitle_present"] = bool(getattr(owned_row, "has_local_subtitles", False)) if owned_row else False
                item["subtitle_file_count"] = int(getattr(owned_row, "subtitle_file_count", 0) or 0) if owned_row else 0
                item["subtitle_dir"] = str(getattr(owned_row, "subtitle_dir", "") or "") if owned_row else ""
                item["owned_paths"] = list((getattr(owned_row, "owned_paths", None) or []) if owned_row else [])
                # is_new_work 计算：必须同时满足 email_watcher 来源 + 锚在 48h 内
                row_tags = row.source_tags
                row_has_email_watcher = isinstance(row_tags, list) and "email_watcher" in row_tags
                row_anchor = row.email_watcher_first_seen_at or row.created_at
                _is_new = False
                if row_has_email_watcher and row_anchor and hasattr(row_anchor, "timestamp"):
                    _age = now_local_for_view.timestamp() - row_anchor.timestamp()
                    _is_new = 0 <= _age <= new_work_window_seconds
                item["is_new_work"] = _is_new
                item["owned_rjcodes"] = self._actual_owned_rjcodes(owned_row)
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
                    for code in [
                        *canonical_info["linked_rjcodes"],
                        row.canonical_rjcode,
                        row.display_rjcode,
                    ]
                    if code in metadata_map_all
                }
                stored_display_rjcode = self.normalize_rjcode(row.display_rjcode) or self.normalize_rjcode(row.canonical_rjcode)
                item["is_bonus_work"] = bool(getattr(row, "is_bonus_work", False))
                if item["is_bonus_work"]:
                    stored_display_rjcode = self._completion_bonus_display_rjcode(
                        row.canonical_rjcode,
                        stored_display_rjcode,
                        metadata_map,
                    )
                item["display_rjcode"] = stored_display_rjcode
                item["linked_rjcodes"] = list(row.linked_rjcodes or [stored_display_rjcode or row.canonical_rjcode])
                if item["is_bonus_work"] and stored_display_rjcode not in item["linked_rjcodes"]:
                    item["linked_rjcodes"].append(stored_display_rjcode)
                if not str(item.get("title") or "").strip():
                    item["title"] = str((metadata_map.get(stored_display_rjcode) or {}).get("work_name") or row.title or "").strip()
                release_date = str((metadata_map.get(stored_display_rjcode) or {}).get("release_date") or "").strip()
                if not release_date:
                    for metadata in metadata_map.values():
                        release_date = str((metadata or {}).get("release_date") or "").strip()
                        if release_date:
                            break
                item["original_release_date"] = self._completion_original_release_date(row.canonical_rjcode, metadata_map_all)
                item["release_date"] = release_date
                item["is_unreleased"] = self._is_future_release_date(release_date)
                item["price_text"] = str(getattr(row, "price_text", "") or "").strip()
                cover_source_url = item.get("image_url")
                if item["is_bonus_work"]:
                    cover_source_url = str((metadata_map.get(stored_display_rjcode) or {}).get("cover_url") or "")
                normalized_remote_cover = self._normalize_dlsite_cover_url(
                    cover_source_url,
                    stored_display_rjcode or row.canonical_rjcode,
                    is_unreleased=item["is_unreleased"],
                )
                # 始终返回本地缓存 API path。文件缺失时 cover API 会从 DLsite
                # 下载一次并落盘，浏览器不直接请求公网封面。
                cover_cache_rjcode = image_cache_service.cache_rjcode_for_url(
                    normalized_remote_cover,
                    stored_display_rjcode or row.canonical_rjcode,
                )
                if cover_cache_rjcode and cover_cache_rjcode != stored_display_rjcode:
                    self._queue_circle_cover_alias_restore(
                        str(row.circle_id or ""),
                        image_cache_service,
                        cover_cache_rjcode,
                        stored_display_rjcode,
                    )
                local_cover_url = image_cache_service.get_local_url(
                    cover_cache_rjcode,
                    allow_missing=True,
                )
                local_thumb_url = image_cache_service.get_local_url(
                    cover_cache_rjcode,
                    variant="list",
                    allow_missing=True,
                )
                item["image_url"] = local_cover_url or normalized_remote_cover
                item["thumb_image_url"] = local_thumb_url or self._normalize_dlsite_thumb_url(
                    normalized_remote_cover,
                    stored_display_rjcode or row.canonical_rjcode,
                    is_unreleased=item["is_unreleased"],
                )
                # 远程 URL 单独再露一份给邮件 / 复制链接等场景使用，前端目前没用，
                # 但保留这个字段成本极低，以后扩展邮件预览 / 复制图片链接时不用回头改 API。
                item["remote_image_url"] = normalized_remote_cover
                # 补充 CV 名列表（来自 work_metadata.cvs）
                if not item.get("cvs"):
                    cvs = list((metadata_map.get(stored_display_rjcode) or {}).get("cvs") or [])
                    # 如果当前 display_rjcode 没有 CV，遍历关联链查找
                    if not cvs:
                        for metadata in metadata_map.values():
                            cvs = list((metadata or {}).get("cvs") or [])
                            if cvs:
                                break
                    item["cvs"] = cvs
                item["has_bonus"] = bool(getattr(row, "has_bonus", False))
                if item["is_bonus_work"]:
                    item["cvs"] = []
                item["__release_timestamp"] = self._completion_release_timestamp(item)
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
                local_owned_rjcodes = self._actual_owned_rjcodes(owned_row)
                normalized_local_owned_rjcodes: List[str] = []
                for candidate in local_owned_rjcodes:
                    normalized_candidate = self.normalize_rjcode(candidate)
                    if normalized_candidate and normalized_candidate not in normalized_local_owned_rjcodes:
                        normalized_local_owned_rjcodes.append(normalized_candidate)
                item["has_kikoeru"] = bool(local_owned)
                item["kikoeru_found_rjcodes"] = normalized_local_owned_rjcodes if local_owned else []
                item["kikoeru_subtitle_rjcodes"] = normalized_local_owned_rjcodes if item["local_subtitle_present"] else []
                item["source_compare"] = self._build_source_compare(item, view_canonical_info, metadata_map)
                kikoeru_compare = item["source_compare"].get("kikoeru") if isinstance(item["source_compare"], dict) else {}
                server_match_rjcodes = list((kikoeru_compare or {}).get("matched_rjcodes") or (kikoeru_compare or {}).get("all_rjcodes") or [])
                server_match_primary_rjcode = str(
                    (kikoeru_compare or {}).get("matched_rjcode")
                    or (kikoeru_compare or {}).get("primary_rjcode")
                    or (server_match_rjcodes[0] if server_match_rjcodes else "")
                ).strip()
                server_owned = bool(local_owned)
                completion_owned = bool(local_owned)
                owned_primary_rjcode = self._pick_owned_primary_rjcode(
                    view_canonical_info,
                    server_match_primary_rjcode=server_match_primary_rjcode,
                    local_owned_rjcodes=local_owned_rjcodes,
                    local_subtitle_present=bool(item["local_subtitle_present"]),
                    subtitle_dir=str(item.get("subtitle_dir") or ""),
                    primary_folder_path=str(item.get("primary_folder_path") or ""),
                )
                item["owned"] = completion_owned
                item["completion_owned"] = completion_owned
                item["server_owned"] = server_owned
                item["server_match_rjcodes"] = server_match_rjcodes
                item["server_match_primary_rjcode"] = server_match_primary_rjcode
                item["owned_variant"] = self._build_variant_payload_for_rjcode(
                    view_canonical_info,
                    owned_primary_rjcode,
                    metadata_map,
                ) if owned_primary_rjcode else {
                    "rjcode": "",
                    "lang": "",
                    "link_type": "",
                    "group_key": "original",
                    "group_label": "原作优先",
                    "group_short_label": "原作",
                }
                item["subtitle_present"] = bool(item["local_subtitle_present"])
                asmr_compare = item["source_compare"].get("asmr_one") if isinstance(item["source_compare"], dict) else {}
                item["subtitle_repairable"] = bool(
                    completion_owned
                    and item["owned_variant"].get("group_key") == "original"
                    and not item["subtitle_present"]
                    and str((asmr_compare or {}).get("primary_badge") or "").strip() in {"简中", "繁中"}
                )
                item["status_tags"] = [
                    *(["库存已收录"] if local_owned else []),
                    *(["本地已下载"] if item["local_download_ready"] else []),
                    *(["已收录"] if server_owned else ["未收录"]),
                    *(["可下载"] if row.has_asmr_one else ["暂不可下载"]),
                ]
                item["download_plan"] = {"rjcode": row.asmr_available_rjcode or row.display_rjcode} if row.has_asmr_one else None
                items.append(item)

            visible_items = []
            for item in items:
                is_unavailable = not bool(item["owned"]) and not bool(item["has_asmr_one"])
                if only_missing and bool(item["owned"]):
                    continue
                if only_downloadable and not bool(item["has_asmr_one"]):
                    continue
                if not include_dl_only and is_unavailable:
                    continue
                visible_items.append(item)

            result = {
                "circle_id": catalog.circle_id,
                "circle_name": catalog.circle_name,
                "source_mask": catalog.source_mask or "",
                "last_indexed_at": catalog.last_indexed_at.isoformat() if catalog.last_indexed_at else None,
                "local_owned_count": sum(1 for item in items if item["local_owned"]),
                "server_owned_count": sum(1 for item in items if item["server_owned"]),
                "owned_count": sum(1 for item in items if item["owned"]),
                "missing_count": sum(1 for item in items if not item["owned"]),
                "downloadable_count": sum(1 for item in items if not item["owned"] and item["has_asmr_one"]),
                "dl_only_count": sum(1 for item in items if not item["owned"] and not item["has_asmr_one"]),
                "dl_count": sum(1 for item in items if item["has_dlsite"]),
                "filtered_count": len(visible_items),
                "works": visible_items,
            }
            mark_stage("payload_build")
            try:
                json_size = len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"))
            except Exception:
                json_size = 0
            # 详情视图全程纯读，不再需要 db.commit()。
            # 写入由 index_circle_catalog / refresh_circle_works / email_watcher 直入负责。
        finally:
            db.close()
        self._completion_view_cache[cache_key] = deepcopy(result)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if elapsed_ms >= 300:
            logger.info(
                "[社团补全·详情耗时] circle_id=%s works=%s visible=%s elapsed=%sms stages=%s json_bytes=%s filters=%s",
                result.get("circle_id") or circle_id_or_query,
                len(works),
                len(result.get("works") or []),
                elapsed_ms,
                stage_costs,
                json_size,
                {
                    "only_missing": bool(only_missing),
                    "only_downloadable": bool(only_downloadable),
                    "include_dl_only": bool(include_dl_only),
                },
            )
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
        started_at = time.perf_counter()
        plan_sem = asyncio.Semaphore(4)
        stage_stats = {
            "selected_count": len(canonical_rjcodes or []),
            "db_rows": len(rows),
            "plan_build_ms": 0,
            "postprocess_ms": 0,
        }

        async def build_row_plan(row: CircleWork) -> Optional[Dict[str, Any]]:
            if not row.has_asmr_one:
                return None
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

            async with plan_sem:
                plan_started = time.perf_counter()
                plan = await self.asmr_resource_service.build_download_plan(
                    rjcode=resolved_rjcode,
                    folder_path="",
                    filters={},
                    refresh=False,
                    emit_activity_log=False,
                )
                stage_stats["plan_build_ms"] += int((time.perf_counter() - plan_started) * 1000)
            post_started = time.perf_counter()
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
            stage_stats["postprocess_ms"] += int((time.perf_counter() - post_started) * 1000)
            return plan

        plan_results = await asyncio.gather(*(build_row_plan(row) for row in rows))
        plans = [plan for plan in plan_results if plan]

        manager = get_library_manager()
        libraries = manager.list_libraries()
        default_library = next((item for item in libraries if item.get("is_default")), None) or (libraries[0] if libraries else {})
        download_base_path = os.path.join(get_config().storage.temp_path, "asmr_enhanced")
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if elapsed_ms >= 500 or len(rows) >= 3:
            logger.info(
                "[社团补全·下载预览耗时] circle_id=%s selected=%s plans=%s elapsed=%sms stats=%s",
                circle_id,
                len(canonical_rjcodes or []),
                len(plans),
                elapsed_ms,
                stage_stats,
            )

        return {
            "circle_id": circle_id,
            "circle_name": catalog.circle_name,
            "plans": plans,
            "planned_count": len(plans),
            "download_base_path": download_base_path,
            "default_target_library_id": str(default_library.get("id") or ""),
            "default_target_subdir": "",
        }

    def _download_preview_job_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": str(payload.get("job_id") or ""),
            "status": str(payload.get("status") or ""),
            "progress": int(payload.get("progress") or 0),
            "current_step": str(payload.get("current_step") or ""),
            "circle_id": str(payload.get("circle_id") or ""),
            "selected_count": int(payload.get("selected_count") or 0),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "elapsed_seconds": float(payload.get("elapsed_seconds") or 0),
            "error_message": str(payload.get("error_message") or ""),
            "result": deepcopy(payload.get("result") or {}),
        }

    async def start_download_preview_job(
        self,
        circle_id: str,
        canonical_rjcodes: List[str],
        requested_rjcodes: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        job_id = uuid.uuid4().hex
        started_at = datetime.now()
        payload: Dict[str, Any] = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "current_step": "等待生成下载预览",
            "circle_id": str(circle_id or "").strip(),
            "selected_count": len(canonical_rjcodes or []),
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "elapsed_seconds": 0.0,
            "error_message": "",
            "result": {},
        }
        self._download_preview_jobs[job_id] = payload

        async def runner() -> None:
            payload["status"] = "processing"
            payload["progress"] = 10
            payload["current_step"] = "正在生成下载预览"
            try:
                result = await self.preview_batch_download(
                    circle_id,
                    canonical_rjcodes,
                    requested_rjcodes,
                )
                payload["status"] = "completed"
                payload["progress"] = 100
                payload["current_step"] = "下载预览已生成"
                payload["result"] = result
            except Exception as exc:
                payload["status"] = "failed"
                payload["progress"] = 100
                payload["current_step"] = "下载预览生成失败"
                payload["error_message"] = str(exc)
                logger.warning(
                    "[社团补全·下载预览任务] 失败: job=%s circle_id=%s selected=%s error=%s",
                    job_id,
                    circle_id,
                    len(canonical_rjcodes or []),
                    exc,
                    exc_info=True,
                )
            finally:
                finished_at = datetime.now()
                payload["finished_at"] = finished_at.isoformat()
                payload["elapsed_seconds"] = max(0.0, (finished_at - started_at).total_seconds())

        asyncio.create_task(runner(), name=f"circle-download-preview:{job_id}")
        return self._download_preview_job_snapshot(payload)

    def get_download_preview_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        payload = self._download_preview_jobs.get(str(job_id or "").strip())
        if not isinstance(payload, dict):
            return None
        if payload.get("status") in {"pending", "processing"}:
            try:
                started_at = datetime.fromisoformat(str(payload.get("started_at") or ""))
                payload["elapsed_seconds"] = max(0.0, (datetime.now() - started_at).total_seconds())
            except Exception:
                pass
        return self._download_preview_job_snapshot(payload)

    async def refresh_circle_owned_state(
        self,
        circle_id: str,
        canonical_rjcodes: List[str],
        *,
        progress_callback: Optional[Callable[..., None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """只从 ready 库存索引批量刷新本地拥有态，不触发任何外部请求。"""
        from .activity_log_service import log_circle_completion_event

        normalized_codes: List[str] = []
        for value in canonical_rjcodes or []:
            code = self.normalize_rjcode(value)
            if code and code not in normalized_codes:
                normalized_codes.append(code)
        if not circle_id:
            raise ValueError("缺少社团标识")
        if not normalized_codes:
            raise ValueError("没有选中要刷新的作品")

        def report(progress: int, step: str, **meta: Any) -> None:
            if progress_callback:
                progress_callback(progress, step, **meta)

        report(5, "读取选中作品", total_count=len(normalized_codes), processed_count=0)
        db = SessionLocal()
        try:
            catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            if catalog is None:
                raise ValueError("社团不存在")
            rows = (
                db.query(CircleWork)
                .filter(
                    CircleWork.circle_id == circle_id,
                    CircleWork.canonical_rjcode.in_(normalized_codes),
                )
                .all()
            )
            if not rows:
                raise ValueError("没有找到选中的作品")
            db.expunge_all()
        finally:
            db.close()

        if cancel_callback and cancel_callback():
            raise RuntimeError("用户取消")

        items_by_canonical: Dict[str, Dict[str, Any]] = {}
        before_by_canonical: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            canonical = self.normalize_rjcode(row.canonical_rjcode)
            if not canonical:
                continue
            source_flags = {flag for flag in str(row.source_mask or "").split(",") if flag}
            items_by_canonical[canonical] = {
                "canonical_rjcode": canonical,
                "display_rjcode": self.normalize_rjcode(row.display_rjcode) or canonical,
                "asmr_available_rjcode": self.normalize_rjcode(row.asmr_available_rjcode),
                "linked_rjcodes": list(row.linked_rjcodes or []),
                "kikoeru_found_rjcodes": list(row.kikoeru_found_rjcodes or []),
                "source_flags": source_flags,
                "is_bonus_work": bool(getattr(row, "is_bonus_work", False)),
            }
            before_by_canonical[canonical] = {
                "has_kikoeru": bool(row.has_kikoeru),
                "found_rjcodes": sorted(self.normalize_rjcode(code) for code in list(row.kikoeru_found_rjcodes or []) if self.normalize_rjcode(code)),
                "subtitle_rjcodes": sorted(self.normalize_rjcode(code) for code in list(row.kikoeru_subtitle_rjcodes or []) if self.normalize_rjcode(code)),
            }

        report(30, "批量查询库存索引", total_count=len(rows), processed_count=0)
        owned_stats = self._apply_library_index_owned_state_to_items(items_by_canonical)
        if not owned_stats.get("ready_index_available"):
            raise ValueError("库存索引尚未就绪，无法刷新本地拥有状态")
        if cancel_callback and cancel_callback():
            raise RuntimeError("用户取消")

        report(
            75,
            "写入本地拥有状态",
            total_count=len(rows),
            processed_count=0,
            kikoeru_owned_count=int(owned_stats.get("owned_count") or 0),
        )
        refreshed_items: List[Dict[str, Any]] = []
        write_db = SessionLocal()
        try:
            now_ts = datetime.now()
            for row in rows:
                canonical = self.normalize_rjcode(row.canonical_rjcode)
                item = items_by_canonical.get(canonical)
                if not item:
                    continue
                found_rjcodes = [
                    code
                    for code in (self.normalize_rjcode(value) for value in list(item.get("kikoeru_found_rjcodes") or []))
                    if code
                ]
                subtitle_rjcodes = [
                    code
                    for code in (self.normalize_rjcode(value) for value in list(item.get("kikoeru_subtitle_rjcodes") or []))
                    if code
                ]
                source_flags = set(item.get("source_flags") or set())
                if item.get("local_owned"):
                    source_flags.add("kikoeru")
                else:
                    source_flags.discard("kikoeru")

                previous = before_by_canonical.get(canonical) or {}
                changed = (
                    bool(previous.get("has_kikoeru")) != bool(item.get("local_owned"))
                    or list(previous.get("found_rjcodes") or []) != sorted(found_rjcodes)
                    or list(previous.get("subtitle_rjcodes") or []) != sorted(subtitle_rjcodes)
                )
                row.has_kikoeru = bool(item.get("local_owned"))
                row.kikoeru_found_rjcodes = found_rjcodes
                row.kikoeru_subtitle_rjcodes = subtitle_rjcodes
                row.source_mask = ",".join(sorted(source_flags))
                row.updated_at = now_ts
                write_db.merge(row)

                refreshed_items.append({
                    "canonical_rjcode": canonical,
                    "title": str(row.title or ""),
                    "display_rjcode": str(row.display_rjcode or canonical),
                    "has_kikoeru": bool(item.get("local_owned")),
                    "local_owned": bool(item.get("local_owned")),
                    "server_match_rjcodes": found_rjcodes,
                    "server_match_primary_rjcode": found_rjcodes[0] if found_rjcodes else "",
                    "subtitle_present": bool(subtitle_rjcodes),
                    "local_subtitle_present": bool(item.get("local_subtitle_present")),
                    "local_folder_size": int(item.get("local_folder_size") or 0),
                    "local_file_count": int(item.get("local_file_count") or 0),
                    "subtitle_file_count": int(item.get("subtitle_file_count") or 0),
                    "subtitle_dir": str(item.get("subtitle_dir") or ""),
                    "changed": changed,
                    "change_count": 1 if changed else 0,
                })

            self._upsert_library_owned_rows_from_items(
                write_db,
                items_by_canonical,
                prune_unmatched=True,
            )
            catalog.last_local_sync_at = now_ts
            catalog.updated_at = now_ts
            write_db.merge(catalog)
            write_db.commit()
        except Exception:
            write_db.rollback()
            raise
        finally:
            write_db.close()

        changed_count = sum(1 for item in refreshed_items if item.get("changed"))
        owned_count = int(owned_stats.get("owned_count") or 0)
        report(
            100,
            "本地拥有状态刷新完成",
            total_count=len(rows),
            processed_count=len(rows),
            changed_count=changed_count,
            kikoeru_owned_count=owned_count,
            owned_only=True,
        )
        log_circle_completion_event(
            "refresh_selected_works",
            summary=f"批量刷新本地拥有状态完成：{catalog.circle_name or circle_id}，共 {len(rows)} 个",
            circle_id=circle_id,
            circle_name=catalog.circle_name,
            detail={
                "selected_count": len(normalized_codes),
                "refreshed_count": len(rows),
                "changed_count": changed_count,
                "kikoeru_owned_count": owned_count,
                "owned_only": True,
                "canonical_rjcodes": normalized_codes[:200],
            },
        )
        self.invalidate_completion_view_cache(circle_id)
        return {
            "circle_id": circle_id,
            "circle_name": catalog.circle_name,
            "selected_count": len(normalized_codes),
            "refreshed_count": len(rows),
            "changed_count": changed_count,
            "asmr_available_count": sum(1 for row in rows if row.has_asmr_one),
            "kikoeru_owned_count": owned_count,
            "owned_only": True,
            "items": refreshed_items,
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

        # === 阶段 A：短读事务 ===
        # 之前这里是"一个 db session 跨越整个循环"，循环里有十几个 await HTTP IO
        # （resolve_canonical / fetch_metadata / probe kikoeru / download_many 等），
        # SQLAlchemy session 自始至终都占着一个连接，又随 row.x = y 长时间持有事务，
        # 其他任何写库的接口（任务中心写状态、操作日志、
        # 邮件监听、库存索引等）就只能排到 30s busy_timeout 兜底队列里慢慢等。
        # 现在拆成"读 → 无 session 跑 IO → 写"三段：循环期间 connection / 写锁
        # 全部释放，其他页面 API 不会再被这条长任务卡住。
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
            # expunge_all 让 catalog / rows 脱管：循环中可以继续读写它们的 attributes，
            # 但 session 不再跟踪 dirty 状态、也不再持有连接。
            db.expunge_all()
        finally:
            db.close()

        try:
            refreshed_items = []
            refreshed_count = 0
            asmr_available_count = 0
            kikoeru_owned_count = 0
            total = len(rows)
            local_owned_items_for_write: Dict[str, Dict[str, Any]] = {}
            local_owned_ready_index_available = False

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
                        "label": "库存收录",
                        "before": "库存已收录" if bool(before_snapshot.get("has_kikoeru")) else "库存未收录",
                        "after": "库存已收录" if bool(after_has_kikoeru) else "库存未收录",
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
                        "label": "库存命中 RJ",
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

                # ★ P2 优化：只拉 canonical + preferred 两条 metadata。旧实现把
                # [canonical, preferred, asmr_available, *linked_rjcodes] 整链全拉，
                # 翻译版的 product/info/ajax 全部被打一遍。新逻辑下游
                # ``_pick_public_display_variant_and_title`` 对未在 metadata_map 里的
                # variant 用 ``get_product_info`` 拉 title（product.json API，cache 命中，
                # 零成本），不影响 preferred 选择正确性。
                metadata_map: Dict[str, Dict[str, Any]] = {}
                first_pass_preferred = self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical
                load_targets: List[str] = []
                for candidate in [canonical, first_pass_preferred]:
                    normalized = self.normalize_rjcode(candidate)
                    if normalized and normalized not in load_targets:
                        load_targets.append(normalized)
                metadata: Dict[str, Any] = {}
                for normalized in load_targets:
                    try:
                        fetched_metadata = await self._fetch_metadata_dict(normalized, refresh=force_refresh)
                    except Exception:
                        fetched_metadata = {}
                    metadata_map[normalized] = fetched_metadata or {}
                    if fetched_metadata and not metadata:
                        metadata = fetched_metadata
                preferred_variant, preferred_title, allowed_variants = await self._pick_public_display_variant_and_title(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map,
                )
                # 二次选出的 preferred 可能不同于 first-pass（title 探测会 fallback 到原作等），
                # 如果二次 preferred 不在 metadata_map 里，按需补拉一次（避免后续 row.title /
                # is_bonus_work / cover 链路缺数据）。
                second_pass_preferred = self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical
                if second_pass_preferred and second_pass_preferred not in metadata_map:
                    try:
                        fetched_metadata = await self._fetch_metadata_dict(second_pass_preferred, refresh=force_refresh)
                    except Exception:
                        fetched_metadata = {}
                    metadata_map[second_pass_preferred] = fetched_metadata or {}
                    if fetched_metadata and not metadata:
                        metadata = fetched_metadata
                linked_rjcodes = [variant["rjcode"] for variant in allowed_variants if variant.get("rjcode")]

                probe_candidates = await self._build_public_download_probe_candidates(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map=metadata_map,
                    extra_candidates=[preferred_variant.get("rjcode"), canonical, row.asmr_available_rjcode, *linked_rjcodes],
                )
                actual_rjcode, _, asmr_probe_status = await self._find_public_downloadable_work_with_status(
                    canonical_info,
                    canonical or preferred_seed,
                    metadata_map=metadata_map,
                    extra_candidates=probe_candidates,
                    bypass_cache=True,
                )
                actual_norm = self.normalize_rjcode(actual_rjcode)
                preserved_asmr_norm = self.normalize_rjcode(row.asmr_available_rjcode)
                resolved_asmr_norm = (
                    preserved_asmr_norm
                    if asmr_probe_status == ASMR_PROBE_STATUS_UNAVAILABLE
                    else actual_norm
                )

                local_state_item = {
                    "canonical_rjcode": canonical,
                    "display_rjcode": self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical or row.display_rjcode,
                    "asmr_available_rjcode": resolved_asmr_norm,
                    "linked_rjcodes": linked_rjcodes or [row.display_rjcode or canonical],
                    "kikoeru_found_rjcodes": [],
                    "source_flags": set(),
                    "is_bonus_work": (
                        bool(row.is_bonus_work)
                        or bool((metadata_map.get(canonical) or {}).get("is_bonus_work"))
                        or bool((metadata_map.get(self.normalize_rjcode(preferred_variant.get("rjcode"))) or {}).get("is_bonus_work"))
                    ),
                }
                local_owned_stats = self._apply_library_index_owned_state_to_items({canonical: local_state_item})
                if local_owned_stats.get("ready_index_available"):
                    local_owned_ready_index_available = True
                    local_owned_items_for_write[canonical] = local_state_item
                found_rjcodes = _normalize_code_list(local_state_item.get("kikoeru_found_rjcodes") or [])
                subtitle_rjcodes = _normalize_code_list(local_state_item.get("kikoeru_subtitle_rjcodes") or [])
                found_titles: Dict[str, str] = {}
                source_flags = {flag for flag in str(row.source_mask or "").split(",") if flag}
                if row.has_dlsite:
                    source_flags.add("dlsite")
                if resolved_asmr_norm:
                    source_flags.add("asmr_one")
                else:
                    source_flags.discard("asmr_one")
                if found_rjcodes:
                    source_flags.add("kikoeru")
                else:
                    source_flags.discard("kikoeru")

                server_match_primary_rjcode = _pick_server_primary(found_rjcodes, canonical_info, preferred_seed or canonical)
                server_title = str(found_titles.get(server_match_primary_rjcode) or "").strip()
                row.display_rjcode = self.normalize_rjcode(preferred_variant.get("rjcode")) or canonical or row.display_rjcode
                preferred_metadata_title = str((metadata_map.get(row.display_rjcode) or {}).get("work_name") or "").strip()
                canonical_metadata_title = str((metadata_map.get(canonical) or {}).get("work_name") or "").strip()
                for candidate_title, candidate_rj in [
                    (server_title, server_match_primary_rjcode),
                    (canonical_metadata_title, canonical),
                    (preferred_title, row.display_rjcode),
                    (preferred_metadata_title, row.display_rjcode),
                    (row.title, row.display_rjcode),
                ]:
                    if self._is_usable_work_title(candidate_rj, candidate_title):
                        row.title = str(candidate_title).strip()
                        break
                row.maker_id = str(metadata.get("maker_id") or row.maker_id or "").strip() or row.maker_id
                row.maker_name = str(metadata.get("maker_name") or row.maker_name or "").strip() or row.maker_name
                display_metadata = metadata_map.get(row.display_rjcode) or metadata or {}
                # canonical 是特典字段权威来源（特典本身只在原作的 product/info/ajax 上成立），
                # display(=preferred) 可能是简中/繁中翻译版，自身的 is_oly 几乎一定是 false。
                # 必须 OR(canonical, display) 才能让原作有特典 / 翻译版被选成 preferred 时
                # 也正确显示特典 chip。
                canonical_metadata_for_row = metadata_map.get(canonical) or {}
                release_date = str(display_metadata.get("release_date") or metadata.get("release_date") or "").strip()
                row.price_text = str(display_metadata.get("price_text") or metadata.get("price_text") or row.price_text or "").strip() or None
                row.is_bonus_work = (
                    bool(canonical_metadata_for_row.get("is_bonus_work"))
                    or bool(display_metadata.get("is_bonus_work"))
                    or bool(metadata.get("is_bonus_work"))
                )
                row.has_bonus = (
                    bool(canonical_metadata_for_row.get("has_bonus"))
                    or bool(display_metadata.get("has_bonus"))
                    or bool(metadata.get("has_bonus"))
                )
                if row.is_bonus_work:
                    # 特典不能继承原作的简中 / 繁中展示 RJ；否则后续浏览会按原作
                    # 元数据取发售日，再被同日分组规则错误挂到另一部作品下。
                    row.display_rjcode = self._completion_bonus_display_rjcode(
                        canonical,
                        row.display_rjcode,
                        metadata_map,
                    )
                    display_metadata = metadata_map.get(row.display_rjcode) or canonical_metadata_for_row
                    release_date = str(display_metadata.get("release_date") or "").strip()
                    row.price_text = str(display_metadata.get("price_text") or row.price_text or "").strip() or None
                    cover_source_url = str(display_metadata.get("cover_url") or "")
                else:
                    cover_source_url = display_metadata.get("cover_url") or metadata.get("cover_url") or row.image_url
                row.image_url = self._normalize_dlsite_cover_url(
                    cover_source_url,
                    row.display_rjcode or canonical,
                    is_unreleased=self._is_future_release_date(release_date),
                )
                row.linked_rjcodes = linked_rjcodes or [row.display_rjcode or canonical]
                if row.is_bonus_work and row.display_rjcode not in row.linked_rjcodes:
                    row.linked_rjcodes.append(row.display_rjcode)
                row.has_kikoeru = bool(found_rjcodes)
                row.kikoeru_found_rjcodes = found_rjcodes
                row.kikoeru_subtitle_rjcodes = subtitle_rjcodes
                row.has_asmr_one = bool(resolved_asmr_norm)
                row.asmr_available_rjcode = resolved_asmr_norm or None
                row.source_mask = ",".join(sorted(source_flags))
                row.updated_at = datetime.now()
                if actual_norm:
                    row.asmr_one_cached_at = datetime.now()

                refreshed_count += 1
                if row.has_asmr_one:
                    asmr_available_count += 1
                if row.has_kikoeru:
                    kikoeru_owned_count += 1
                normalized_found_rjcodes = _normalize_code_list(row.kikoeru_found_rjcodes or [])
                normalized_subtitle_rjcodes = _normalize_code_list(row.kikoeru_subtitle_rjcodes or [])
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
                    "local_owned": bool(local_state_item.get("local_owned")),
                    "local_folder_size": int(local_state_item.get("local_folder_size") or 0),
                    "local_file_count": int(local_state_item.get("local_file_count") or 0),
                    "local_subtitle_present": bool(local_state_item.get("local_subtitle_present")),
                    "subtitle_file_count": int(local_state_item.get("subtitle_file_count") or 0),
                    "subtitle_dir": str(local_state_item.get("subtitle_dir") or ""),
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

            # === 阶段 C：短写事务 ===
            # 把脱管的 rows / catalog 一次性 merge 回库并 commit；写锁仅在 commit 期间
            # 短暂持有，全程不阻塞其他写库的接口（任务中心、操作日志、邮件监听等）。
            # 封面由 /cover 缺失回退链路按需缓存。状态刷新不能在结果落库前等待
            # 非关键图片网络 IO，否则单个封面连接卡住会让整个任务停在 93%。
            if cancel_callback and cancel_callback():
                raise RuntimeError("用户取消")
            report(
                95,
                "写入刷新结果",
                total_count=total,
                processed_count=refreshed_count,
                asmr_available_count=asmr_available_count,
                kikoeru_owned_count=kikoeru_owned_count,
            )
            now_ts = datetime.now()
            catalog.last_indexed_at = now_ts
            catalog.updated_at = now_ts
            write_db = SessionLocal()
            try:
                for refreshed_row in rows:
                    write_db.merge(refreshed_row)
                if local_owned_items_for_write:
                    self._upsert_library_owned_rows_from_items(
                        write_db,
                        local_owned_items_for_write,
                        prune_unmatched=local_owned_ready_index_available,
                    )
                write_db.merge(catalog)
                write_db.commit()
            except Exception:
                write_db.rollback()
                raise
            finally:
                write_db.close()

            # ★ bonus 字段补刷（和 index_circle_catalog 保持一致）：
            # 浏览路径已经退化成纯 DB 读、不再做 lazy_refresh，所以"刷新选中作品"
            # 这条写路径必须把存量 ``bonus_info_checked_at IS NULL`` 的行补齐。
            # ``_refresh_circle_bonus_fields`` 内部走 ``lazy_refresh_bonus_for_cached_rjcodes``
            # 同步到 circle_works。这里只刷新选中的 canonical，scope 给 helper 收窄。
            #
            # ★ 关键：``force=True``——
            # 用户主动点"刷新选中作品"是修复存量错误数据的入口。如果只看
            # ``bonus_info_checked_at IS NULL``，对历史上 ``get_product_bonus_info``
            # 异常吞错（HTTP 失败被错误打了时间戳）导致 ``is_bonus_work=False``
            # 卡死的条目永远救不回来。这里透传 force 让 lazy_refresh 重新拉一次
            # product/info/ajax，DLsite 端 24h cache + inflight 去重防止雪崩。
            # ``index_circle_catalog`` 默认链路保持 force=False，是增量补救语义。
            if cancel_callback and cancel_callback():
                raise RuntimeError("用户取消")
            report(
                97,
                "更新特典状态",
                total_count=total,
                processed_count=refreshed_count,
                asmr_available_count=asmr_available_count,
                kikoeru_owned_count=kikoeru_owned_count,
            )
            bonus_lookup_rjcodes: List[str] = []
            for refreshed_row in rows:
                for code in [
                    refreshed_row.canonical_rjcode,
                    refreshed_row.display_rjcode,
                    *(refreshed_row.linked_rjcodes or []),
                ]:
                    normalized = self.normalize_rjcode(code)
                    if normalized and normalized not in bonus_lookup_rjcodes:
                        bonus_lookup_rjcodes.append(normalized)
            await self._refresh_circle_bonus_fields(
                circle_id,
                bonus_lookup_rjcodes,
                canonical_filter=normalized_codes,
                force=True,
            )

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
            self.invalidate_completion_view_cache(circle_id)
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
            # 阶段 A 的 session 已经在读完 rows / catalog 后立即 close，循环 + 写阶段
            # 都用独立的 short session，所以这里没有 db 需要 rollback——直接向上抛。
            raise

    async def list_recent_indexes(self, limit: int = 20) -> List[Dict[str, Any]]:
        return await self.search_circles("", limit=limit)


_circle_completion_service: Optional[CircleCompletionService] = None


def get_circle_completion_service() -> CircleCompletionService:
    global _circle_completion_service
    if _circle_completion_service is None:
        _circle_completion_service = CircleCompletionService()
    return _circle_completion_service
