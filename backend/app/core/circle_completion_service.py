from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from collections import defaultdict
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
    LibraryOwnedWork,
    LibrarySnapshot,
    SessionLocal,
    WorkCanonicalLink,
    WorkMetadata,
    get_local_now,
)
from .activity_log_service import log_circle_completion_event
from .asmr_download_service import get_asmr_download_service
from .asmr_resource_service import get_asmr_resource_service
from .circle_image_cache_service import get_circle_image_cache_service
from .dlsite_service import get_dlsite_service
from .kikoeru_duplicate_service import get_kikoeru_service
from .metadata_service import MetadataService
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class CircleCompletionSnapshot:
    """社团补全任务的外部数据快照（Phase 1 一次性收集，Phase 2 纯本地查询不再触网）。

    设计要点：
    - **只显式持有"现有 TTL cache 没有"的数据**：ASMR.one 的 ``fetch_work_info`` /
      ``fetch_track_list`` 没有内部 cache，每次都打 HTTP，必须自建 snapshot。
    - **DLsite metadata / canonical / Kikoeru state** 走现有
      ``_metadata_cache`` / ``_canonical_cache`` / ``_kikoeru_state_cache``——
      Phase 1 prefetch 阶段已经把它们写入 cache，Phase 2 调用时直接命中。
      不在 snapshot 里重复持有,避免内存浪费 + 维护一致性的负担。
    - ``candidate_rjcodes`` 是 Phase 1 的初始候选 RJ 列表（去重，含本地 / Kikoeru /
      DLsite 三个来源）；``all_rjcodes`` 是 candidate ∪ 全部 linked_rjcodes，是
      Phase 2 真正需要查 ASMR / Kikoeru 的 RJ 全集。
    - ``canonical_rj_by_rj`` / ``chain_rjs_by_canonical`` 描述"作品链路"：
      同一部作品的原版 + 各语言翻译/重制版共享同一个 canonical RJ。Wave 1 算
      出每个 candidate 的 canonical 后，Wave 2b 对 Kikoeru 只按 **独立链路** 探测
      一次（``check_duplicate_with_linkages(canonical)`` 内部会展开整条链路、
      查全所有翻译版的 Kikoeru 状态），结果回灌给链上每个 RJ 的 cache。这样
      原本 N=39 次 Kikoeru 查询会降到链路数（典型 13 条），但 Phase 2 对任意
      candidate RJ 仍然能 cache 命中、不会漏作品。

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
    #   各语言翻译版、各重制版）。Wave 2b 按 ``chain_rjs_by_canonical.keys()``
    #   去重 probe，可把 Kikoeru 查询次数从"全 RJ 数"降到"独立链路数"。
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

    def __init__(self):
        self.metadata_service = MetadataService()
        self.kikoeru_service = get_kikoeru_service()
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
        self._canonical_cache: TTLCache = TTLCache(max_size=1024, ttl_seconds=3600, name="circle.canonical")
        self._kikoeru_state_cache: TTLCache = TTLCache(max_size=1024, ttl_seconds=600, name="circle.kikoeru_state")
        # 下面两个原本就有 expires_at 字段，结构不变以兼容现有读写。
        self._kikoeru_circle_id_cache: Dict[str, tuple[str, float]] = {}
        self._local_download_fallback_cache: Dict[str, Any] = {"expires_at": 0.0, "data": {}}

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

    async def _find_public_downloadable_work(
        self,
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Dict[str, Any]]] = None,
        extra_candidates: Optional[List[Any]] = None,
        snapshot: Optional[CircleCompletionSnapshot] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        probe_candidates = await self._build_public_download_probe_candidates(
            canonical_info,
            fallback_rjcode,
            metadata_map=metadata_map,
            extra_candidates=extra_candidates,
        )
        cache_key = "|".join(probe_candidates)
        if cache_key:
            cached = self._asmr_probe_cache.get(cache_key)
            if cached is not None:
                return cached
        for probe_rjcode in probe_candidates:
            # ★ Phase 2 路径：snapshot 已包含全 RJ 的 work_info/tracks，直接查不打 HTTP。
            #   未传 snapshot（如老调用点 / 单 RJ 视图重建）时退回原 HTTP 行为。
            if snapshot is not None:
                work_info = snapshot.get_asmr_work_info(probe_rjcode)
                tracks = snapshot.get_asmr_tracks(probe_rjcode)
            else:
                try:
                    work_info = await self.asmr_service.fetch_work_info(probe_rjcode)
                except Exception:
                    work_info = None
                tracks = None
                if work_info:
                    try:
                        tracks = await self.asmr_service.fetch_track_list(probe_rjcode)
                    except Exception:
                        tracks = None
            if not work_info:
                continue
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
            # 只有明确的 local_download_ready 标志才视为「已下载可入库」，
            # 不能用 local_count > 0 兜底，避免下载了一半的临时文件被误判为完成。
            local_ready = bool(local_root_exists and session.get("local_download_ready"))
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
                    }
                    for row in rows
                    if self.normalize_rjcode(row.linked_rjcode)
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
                if work_type == "original":
                    canonical_rjcode = linked_rj_norm
                link_rows.append({
                    "linked_rjcode": linked_rj_norm,
                    "link_type": work_type,
                    "lang": lang,
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
            canonical_rjcode = normalized_rj

        db = SessionLocal()
        try:
            overlap_codes = [row["linked_rjcode"] for row in link_rows if row.get("linked_rjcode")]
            if overlap_codes:
                existing_overlap_rows = (
                    db.query(WorkCanonicalLink)
                    .filter(
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
                            }
                    link_rows = list(merged_by_rj.values())
                    canonical_rjcode = _select_canonical_from_link_rows(link_rows, canonical_rjcode)
        finally:
            db.close()

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
        if not refresh:
            db = SessionLocal()
            try:
                cached = db.query(WorkMetadata).filter(WorkMetadata.rjcode == normalized_rj).first()
                if cached:
                    payload = cached.to_dict()
                    if not _is_placeholder_metadata(payload):
                        self._metadata_cache[normalized_rj] = payload
                        return payload
            finally:
                db.close()
        fake_task = type("FakeTask", (), {"task_metadata": {"rjcode": normalized_rj}, "rjcode": normalized_rj, "update_progress": lambda *args, **kwargs: None})()
        payload = await self.metadata_service.fetch(normalized_rj, fake_task, force_refresh=refresh)
        self._metadata_cache[normalized_rj] = dict(payload or {})
        return self._metadata_cache[normalized_rj]

    async def _probe_kikoeru_owned_state(self, probe_rjcode: str, *, use_cache: bool = True) -> bool:
        # ★ 性能优化：复用 ``_probe_kikoeru_state`` 的 ``_kikoeru_state_cache``。
        # 之前这里独立调 ``check_duplicate_with_linkages``、没 cache，同一个 RJ 在
        # 多个候选流程里被多次 probe owned_state 时，每次都重新跑一整套 DLsite
        # 关联链 + Kikoeru search 链路。``_probe_kikoeru_state`` 已经把同样的
        # check_duplicate_with_linkages 结果按 RJ cache 在 ``_kikoeru_state_cache``
        # （10 分钟 TTL）里，state 字典本身就含 ``has_kikoeru`` 这个 owned 信号，
        # 直接读即可，避免重复触网。
        state = await self._probe_kikoeru_state(probe_rjcode, use_cache=use_cache)
        return bool(state.get("has_kikoeru"))

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
        found_titles: Dict[str, str] = {}
        for workno, result in (results or {}).items():
            if not getattr(result, "is_found", False):
                continue
            matched_rj = self.normalize_rjcode(
                getattr(result, "matched_rjcode", None) or workno or getattr(result, "rjcode", None)
            )
            if matched_rj and matched_rj not in found_rjcodes:
                found_rjcodes.append(matched_rj)
            matched_title = str(getattr(result, "title", "") or "").strip()
            if matched_rj and self._is_usable_work_title(matched_rj, matched_title):
                found_titles[matched_rj] = matched_title
            subtitle_check_source = str(getattr(result, "subtitle_check_source", "") or "").strip()
            if matched_rj and getattr(result, "has_lyric_hint", False) and subtitle_check_source and subtitle_check_source != "search_only":
                if matched_rj not in subtitle_rjcodes:
                    subtitle_rjcodes.append(matched_rj)
        payload = {
            "has_kikoeru": bool(found_rjcodes),
            "found_rjcodes": found_rjcodes,
            "subtitle_rjcodes": subtitle_rjcodes,
            "found_titles": found_titles,
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
        found_titles: Dict[str, str] = {}
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
            for code, title in dict(state.get("found_titles") or {}).items():
                normalized_code = self.normalize_rjcode(code)
                if normalized_code and self._is_usable_work_title(normalized_code, title):
                    found_titles[normalized_code] = str(title or "").strip()

        return {
            "has_kikoeru": bool(found_rjcodes),
            "found_rjcodes": found_rjcodes,
            "subtitle_rjcodes": subtitle_rjcodes,
            "found_titles": found_titles,
        }

    async def _collect_external_snapshot(
        self,
        candidate_rjcodes: List[str],
        *,
        force_refresh: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
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
          - **Wave 2b / Kikoeru 核对**：按 **作品链路** 去重 probe，每条链路只
            对 canonical RJ 调一次 ``_probe_kikoeru_state``——
            ``check_duplicate_with_linkages`` 内部本来就会展开整条链路、查所有
            翻译版的 Kikoeru 状态，对链上任一 RJ probe 出来的 state 完全一致。
            探测完成后把同一份 state 回灌给链上每个 RJ 的 ``_kikoeru_state_cache``，
            Phase 2 任意候选 RJ probe 时仍然 cache 命中、不会漏作品。

            这步是把 Kikoeru 查询次数从 "候选 + 翻译版全集"（典型 30-50）压到
            "独立作品数"（典型 10-15）的关键，对耗时影响最大。

        关键参数：

        - ``force_refresh`` 透传给 ``resolve_canonical_rj`` 和 ``_probe_kikoeru_state``,
          强刷场景下绕过现有 cache，但仍然把新结果写回 cache 供 Phase 2 复用。
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

        async def prefetch_dlsite(rj: str) -> Tuple[str, str, Set[str], Dict[str, Any]]:
            """返回 ``(原始 rj, canonical rj, 链上所有 rj 的集合, canonical_info)``。

            内部把所有异常吞掉、回 fallback 值（canonical=rj 自身），保证
            上游聚合阶段不需要再处理 BaseException 分支。
            """
            related: Set[str] = {rj}
            canonical: str = rj
            canonical_info: Dict[str, Any] = {}
            async with wave1_sem:
                try:
                    canonical_info = await self.resolve_canonical_rj(rj, refresh=force_refresh) or {}
                except Exception:
                    logger.debug("[社团补全·snapshot] resolve_canonical_rj 失败 rj=%s", rj, exc_info=True)
                canonical = self.normalize_rjcode(canonical_info.get("canonical_rjcode")) or rj
                related.add(canonical)
                for code in canonical_info.get("linked_rjcodes") or []:
                    norm = self.normalize_rjcode(code)
                    if norm:
                        related.add(norm)
            return rj, canonical, related, canonical_info

        safe_progress(
            0,
            f"解析 DLsite 作品关联链 0/{len(snapshot.candidate_rjcodes)} 件",
        )

        wave1_raw = await asyncio.gather(
            *[prefetch_dlsite(rj) for rj in snapshot.candidate_rjcodes],
            return_exceptions=True,
        )

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
            f"{len(unique_canonicals)} 条作品链路，开始核对 ASMR.one 与 Kikoeru",
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
        wave2_asmr_sem = asyncio.Semaphore(30)
        asmr_completed = 0
        # 进度按链路推进而不是按 RJ，避免跳跃
        asmr_total = max(1, len(canonical_to_chain))

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
            """对一条 canonical 链路按 preferred 优先级串行探 ASMR.one，命中即停。

            返回链上每个 RJ 的 ``(rj, work_info, tracks)``：
            - 首个 ``work_info`` & ``tracks`` 双双命中的 RJ 之后停止真探，剩余 RJ 用
              ``(rj, None, None)`` 占位（``snapshot.contains_asmr`` 仍正确返 False）。
            - 全 miss 时链上每个 RJ 都是 ``(rj, None, None)``。
            """
            chain_rjs: Set[str] = set(canonical_to_chain.get(canonical) or {canonical})
            probe_order = _build_chain_probe_order(canonical, chain_rjs)
            results: List[Tuple[str, Optional[Dict[str, Any]], Optional[List[Any]]]] = []
            explored: Set[str] = set()
            async with wave2_asmr_sem:
                for rj in probe_order:
                    work_info: Optional[Dict[str, Any]] = None
                    tracks: Optional[List[Any]] = None
                    try:
                        work_info = await self.asmr_service.fetch_work_info(rj)
                    except Exception:
                        logger.debug("[社团补全·snapshot] ASMR fetch_work_info 失败 rj=%s", rj, exc_info=True)
                    if work_info:
                        try:
                            tracks = await self.asmr_service.fetch_track_list(rj)
                        except Exception:
                            logger.debug("[社团补全·snapshot] ASMR fetch_track_list 失败 rj=%s", rj, exc_info=True)
                    results.append((rj, work_info, tracks))
                    explored.add(rj)
                    if work_info and tracks:
                        break
            # 链上没探过的 RJ 用 (None, None) 占位，让 snapshot.contains_asmr 兼容旧行为。
            for rj in chain_rjs:
                if rj not in explored:
                    results.append((rj, None, None))
            return results

        # ============ Wave 2b：Kikoeru 作品链路核对（按 canonical 去重）============
        # ``check_duplicate_with_linkages(canonical_rj)`` 内部会自动展开整条作品
        # 链路、把每个翻译版都查一遍，返回的 state 对链上任意 RJ 都是等价的。
        # 这里把"按 RJ probe（典型 30-50 次）"压到"按链路 probe（典型 10-15 次）"，
        # 是耗时改善最大的地方。
        wave2_kk_sem = asyncio.Semaphore(20)
        kikoeru_completed = 0
        kikoeru_total = max(1, len(unique_canonicals))

        async def prefetch_kikoeru(canonical_rj: str) -> Tuple[str, Dict[str, Any]]:
            async with wave2_kk_sem:
                try:
                    state = await self._probe_kikoeru_state(
                        canonical_rj, use_cache=not force_refresh
                    )
                except Exception:
                    logger.debug(
                        "[社团补全·snapshot] _probe_kikoeru_state 失败 canonical=%s",
                        canonical_rj, exc_info=True,
                    )
                    state = {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}
            return canonical_rj, state

        # 进度回调用 as_completed 双流合并：每完成一条链路 / Kikoeru 探测就更新一次
        asmr_futures = [prefetch_asmr_chain(c) for c in unique_canonicals]
        kikoeru_futures = [prefetch_kikoeru(c) for c in unique_canonicals]

        async def collect_asmr() -> None:
            nonlocal asmr_completed
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

        async def collect_kikoeru() -> None:
            nonlocal kikoeru_completed
            for future in asyncio.as_completed(kikoeru_futures):
                ensure_not_cancelled()
                try:
                    canonical_rj, state = await future
                except Exception as exc:
                    logger.debug("[社团补全·snapshot] Kikoeru prefetch 任务异常: %s", exc)
                    kikoeru_completed += 1
                    continue
                # 把同一份 state 回灌给链上每个 RJ 的 cache，让 Phase 2 对任意
                # candidate / linked RJ probe 都能直接 cache 命中。
                chain = canonical_to_chain.get(canonical_rj) or {canonical_rj}
                for member in chain:
                    self._kikoeru_state_cache[member] = state
                kikoeru_completed += 1
                if kikoeru_completed % 3 == 0 or kikoeru_completed == kikoeru_total:
                    # snapshot 相对刻度：Kikoeru 占 75→95 段
                    safe_progress(
                        75 + int((kikoeru_completed / kikoeru_total) * 20),
                        f"在 Kikoeru 上核对作品链路 {kikoeru_completed}/{kikoeru_total} 条",
                    )

        # 两组并发同时跑，互不阻塞；耗时 = max(ASMR_total, Kikoeru_chain_total)
        await asyncio.gather(collect_asmr(), collect_kikoeru())

        ensure_not_cancelled()

        asmr_hits = sum(1 for v in snapshot.asmr_work_info_by_rj.values() if v)
        safe_progress(
            100,
            f"外部数据收集完成（候选 {len(snapshot.candidate_rjcodes)} 件 / "
            f"含翻译共 {len(snapshot.all_rjcodes)} 个 RJ / "
            f"ASMR 命中 {asmr_hits} 个 / Kikoeru 链路 {len(unique_canonicals)} 条）",
        )

        logger.info(
            "[社团补全·snapshot] 收集完成: candidates=%s all_rjs=%s "
            "kikoeru_chains=%s asmr_hits=%s",
            len(snapshot.candidate_rjcodes),
            len(snapshot.all_rjcodes),
            len(unique_canonicals),
            asmr_hits,
        )

        return snapshot

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

    async def _search_dlsite_announce_works(self, keyword: str, max_pages: int = 3) -> tuple[List[str], str]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return [], ""
        found: List[str] = []
        seen: Set[str] = set()
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
        for template in url_templates:
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
                    matches = re.findall(r"[RVB]J\d{6,8}", response.text or "", re.IGNORECASE)
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
            for rj in attempt_found:
                if rj not in seen:
                    seen.add(rj)
                    found.append(rj)
            if found:
                break
        return found, failure_reason

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
        dlsite_rjcodes: List[str] = []
        # 只有直接来自 maker 主页的 RJ 码才是可信的，不需要二次校验社团名
        profile_rjcodes: set = set()
        source_mode = "keyword"
        failure_messages: List[str] = []

        # ★ profile_parse_status 用来区分两种"profile + announce 都返回 0"：
        #   - "empty"：DLsite 上 maker_id 真的没作品（多半是脏 maker_id），可以重置走关键字
        #   - "html_decode_failed" / "http_error"：抓取失败（典型现场是 brotlicffi 没装、
        #     代理被墙、临时 5xx），此时 **绝对不能** 重置 maker_id —— 否则下面
        #     fetch_candidate 的 maker_id 白名单失效，关键字搜索抓到的全站推荐位 RJ
        #     就会跨过过滤进入候选，导致"25 个作品的社团变 42 个候选"那种污染。
        profile_parse_status = "ok" if not normalized_maker_id else "skipped"

        if normalized_maker_id:
            try:
                dlsite_rjcodes, profile_parse_status = await self.dlsite_service.list_circle_worknos_by_maker(normalized_maker_id, language="JPN")
                source_mode = "maker_profile"
                profile_rjcodes = set(dlsite_rjcodes)
                if progress_callback:
                    progress_callback(
                        44,
                        "已抓取 DLsite 社团主页原作与预告列表",
                        dlsite_profile_total=len(dlsite_rjcodes),
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
                seen_rjcodes = set(dlsite_rjcodes)
                added_count = 0
                for rjcode in maker_announce_rjcodes:
                    if rjcode not in seen_rjcodes:
                        seen_rjcodes.add(rjcode)
                        dlsite_rjcodes.append(rjcode)
                        added_count += 1
                profile_rjcodes.update(maker_announce_rjcodes)
                source_mode = f"{source_mode}+maker_announce"
                if progress_callback:
                    progress_callback(
                        45,
                        "已补充 DLsite maker 预告作品",
                        dlsite_maker_announce_total=len(maker_announce_rjcodes),
                        dlsite_maker_announce_added=added_count,
                        dlsite_profile_total=len(dlsite_rjcodes),
                        dlsite_maker_id=normalized_maker_id,
                        dlsite_source_mode=source_mode,
                        dlsite_failure_reason=" / ".join(failure_messages),
                    )

        if not dlsite_rjcodes:
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
                normalized_maker_id and profile_parse_status == "empty"
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

        announce_rjcodes, announce_failure_reason = await self._search_dlsite_announce_works(circle_query)
        if announce_failure_reason:
            failure_messages.append(announce_failure_reason)
        if announce_rjcodes:
            seen_rjcodes = set(dlsite_rjcodes)
            added_count = 0
            for rjcode in announce_rjcodes:
                if rjcode not in seen_rjcodes:
                    seen_rjcodes.add(rjcode)
                    dlsite_rjcodes.append(rjcode)
                    added_count += 1
            source_mode = f"{source_mode}+announce"
            if progress_callback:
                progress_callback(
                    45,
                    "已补充 DLsite 发售预告作品",
                    dlsite_profile_total=len(dlsite_rjcodes),
                    dlsite_announce_total=len(announce_rjcodes),
                    dlsite_announce_added=added_count,
                    dlsite_source_mode=source_mode,
                    dlsite_failure_reason=" / ".join(failure_messages),
                )

        candidates: List[Dict[str, Any]] = []
        total_rjcodes = max(1, len(dlsite_rjcodes))
        semaphore = asyncio.Semaphore(10)

        async def fetch_candidate(rjcode: str) -> Optional[Dict[str, Any]]:
            is_from_profile = rjcode in profile_rjcodes
            async with semaphore:
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
                    return None
                asmr_classification = await self._classify_asmr_work_candidate(rjcode, meta)
                # maker 主页会列出同社团全部作品，游戏/漫画也在里面。不能因为
                # 来源可信就放行；必须被 DLsite product 判成 SOU，或 metadata
                # 自身有明确音声/ASMR 信号。
                if asmr_classification is not True:
                    return None
            candidate_maker_id = self._normalize_maker_id(meta.get("maker_id"))
            if normalized_maker_id:
                if is_from_profile:
                    if candidate_maker_id and candidate_maker_id != normalized_maker_id:
                        return None
                else:
                    # 关键字/预告来源启用 maker_id 白名单：已识别到 maker_id 时，
                    # 候选必须携带且必须等于该 maker_id，缺失也直接丢弃。
                    if not candidate_maker_id or candidate_maker_id != normalized_maker_id:
                        return None
            maker_name = str(meta.get("maker_name") or "").strip()
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
            return {
                "rjcode": rjcode,
                "title": meta.get("work_name") or "",
                "maker_id": meta.get("maker_id") or normalized_maker_id or "",
                "maker_name": maker_name or circle_query,
                "price_text": meta.get("price_text") or "",
                "image_url": self._normalize_dlsite_cover_url(
                    meta.get("cover_url"),
                    rjcode,
                    is_unreleased=self._is_future_release_date(meta.get("release_date")),
                ),
                "source": "dlsite",
                "_asmr_checked": True,
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

    async def sync_local_owned_index(self) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            snapshots = db.query(LibrarySnapshot).all()
        finally:
            db.close()

        merged: Dict[str, Dict[str, Any]] = {}
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(16)

        async def _resolve_and_merge(snapshot: Any) -> None:
            rjcode = self.normalize_rjcode(snapshot.rjcode)
            if not rjcode:
                return
            async with sem:
                canonical_info = await self.resolve_canonical_rj(rjcode)
            canonical = canonical_info["canonical_rjcode"] or rjcode
            async with lock:
                bucket = merged.setdefault(canonical, {
                    "owned_rjcodes": set(),
                    "primary_folder_path": snapshot.folder_path,
                    "folder_count": 0,
                })
                bucket["owned_rjcodes"].add(rjcode)
                bucket["folder_count"] += 1

        await asyncio.gather(*[_resolve_and_merge(s) for s in snapshots])

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
        """单 RJ 入库后增量同步本地拥有态索引。

        相对于早期实现，这里多做了两件事：

        1. **反向匹配 linked_rjcodes**：CircleWork 索引时算出来的 canonical 与
           入库时 `resolve_canonical_rj` 算出来的 canonical 可能因为 DLsite
           数据更新或解析逻辑差异而不一致，单写一条 `LibraryOwnedWork(canonical=A)`
           会让 LEFT JOIN 在另一个 canonical 上漏匹配。这里用 SQLite JSON LIKE
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
        from sqlalchemy import or_ as sa_or

        affected_circle_ids: set[str] = set()
        target_canonicals: set[str] = {canonical}
        reverse_match_count = 0

        db = SessionLocal()
        try:
            # === 反向匹配：找出所有 CircleWork 行，其 canonical 或 linked_rjcodes 关联到本次 RJ ===
            # 优先索引点查；linked_rjcodes JSON LIKE 仅作为兜底（覆盖 canonical 不一致的边界）。
            json_pattern = f'%"{normalized_rj}"%'
            related_rows = (
                db.query(
                    CircleWork.canonical_rjcode.label("canonical_rjcode"),
                    CircleWork.circle_id.label("circle_id"),
                )
                .filter(
                    sa_or(
                        CircleWork.canonical_rjcode == canonical,
                        CircleWork.canonical_rjcode == normalized_rj,
                        CircleWork.display_rjcode == normalized_rj,
                        CircleWork.linked_rjcodes.like(json_pattern),
                    )
                )
                .all()
            )
            reverse_match_count = len(related_rows)
            for related in related_rows:
                related_canonical = self.normalize_rjcode(related.canonical_rjcode)
                if related_canonical:
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
                if c != normalized_rj:
                    # 覆盖 canonical 自身也存进 owned_rjcodes，便于 owned_rjcodes 里既能看到
                    # 入库的具体 RJ，又能看到该作品的 canonical RJ。
                    owned_rjcodes.add(c)
                if row is None:
                    row = LibraryOwnedWork(canonical_rjcode=c)
                    db.add(row)
                row.owned_rjcodes = sorted(owned_rjcodes)
                row.primary_folder_path = folder_path or row.primary_folder_path
                row.library_id = library_id or row.library_id
                row.folder_count = max(int(row.folder_count or 0), 1)
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
          ``circle_works`` 行（按关联 RJ 做"任何一个命中即聚合"，和老 bonus
          回写规则保持一致）；
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
        try:
            query = db.query(CircleWork).filter(CircleWork.circle_id == circle_id)
            if normalized_filter is not None:
                query = query.filter(CircleWork.canonical_rjcode.in_(normalized_filter))
            rows = query.all()
            for row in rows:
                related: List[str] = []
                for code in [
                    row.canonical_rjcode,
                    row.display_rjcode,
                    *(row.linked_rjcodes or []),
                ]:
                    normalized = self.normalize_rjcode(code)
                    if normalized and normalized not in related:
                        related.append(normalized)
                new_is_bonus = bool(row.is_bonus_work)
                new_has_bonus = bool(row.has_bonus)
                hit = False
                for rj in related:
                    payload = bonus_updates.get(rj)
                    if not payload:
                        continue
                    hit = True
                    # 多语言版本共享同一行，"或"语义最稳：任何关联 RJ 命中
                    # 'is_bonus / has_bonus' 都同步到 row。
                    new_is_bonus = new_is_bonus or bool(payload.get("is_bonus_work"))
                    new_has_bonus = new_has_bonus or bool(payload.get("has_bonus"))
                if hit and (new_is_bonus != bool(row.is_bonus_work) or new_has_bonus != bool(row.has_bonus)):
                    row.is_bonus_work = new_is_bonus
                    row.has_bonus = new_has_bonus
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("[社团补全] 同步 bonus 字段到 circle_works 失败 circle_id=%s", circle_id, exc_info=True)
        finally:
            db.close()
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
        resolved_kikoeru_circle_id = ""
        if include_kikoeru:
            report(24, "查询 Kikoeru 社团作品", local_candidates_count=len(local_candidates))
            kikoeru_circle_id = ""
            normalized_circle_query = self.normalize_circle_name(circle_query)
            maker_cache_key = ""
            maker_id_hint = ""
            db = SessionLocal()
            try:
                existing_catalog = self._find_catalog_by_normalized_name(db, normalized_circle_query)
                if existing_catalog:
                    kikoeru_circle_id = self._normalize_kikoeru_circle_id(existing_catalog.circle_id)
                    existing_circle_id_text = str(existing_catalog.circle_id or "").strip().upper()
                    if existing_circle_id_text and not existing_circle_id_text.isdigit() and not existing_circle_id_text.startswith("NAME:"):
                        maker_id_hint = existing_circle_id_text
                        maker_cache_key = f"maker:{existing_circle_id_text}"
            finally:
                db.close()
            if not maker_cache_key:
                maker_from_local = next((str(item.get("maker_id") or "").strip().upper() for item in local_candidates if item.get("maker_id")), "")
                if maker_from_local:
                    maker_id_hint = maker_from_local
                    maker_cache_key = f"maker:{maker_from_local}"
            if kikoeru_circle_id:
                self._set_cached_kikoeru_circle_id(kikoeru_circle_id, f"name:{normalized_circle_query}")
                self._save_persisted_kikoeru_circle_id(normalized_circle_query, kikoeru_circle_id, maker_id_hint)
            if not kikoeru_circle_id:
                kikoeru_circle_id = self._get_cached_kikoeru_circle_id(f"name:{normalized_circle_query}")
            if not kikoeru_circle_id and maker_cache_key:
                kikoeru_circle_id = self._get_cached_kikoeru_circle_id(maker_cache_key)
            if not kikoeru_circle_id:
                db = SessionLocal()
                try:
                    kikoeru_circle_id = self._load_persisted_kikoeru_circle_id(db, normalized_circle_query, maker_id_hint)
                finally:
                    db.close()
            if kikoeru_circle_id:
                self._set_cached_kikoeru_circle_id(kikoeru_circle_id, f"name:{normalized_circle_query}", maker_cache_key)
            if not kikoeru_circle_id:
                # ★ 长 query 兜底：Kikoeru 是先按 works keyword 搜作品再抽 circle.id，
                # 整串 "悪女名鑑(常世常闇所々)" 在作品标题里几乎不会重复，会直接 0 命中。
                # 拆出括号内/外子 keyword 重试一遍，匹配到 1 个 work 就能反查 circle.id。
                detected_circle_id = 0
                for variant in self._build_search_keyword_variants(circle_query):
                    try:
                        detected_circle_id = await self.kikoeru_service.find_circle_id_by_keyword(variant)
                    except Exception:
                        detected_circle_id = 0
                    if detected_circle_id:
                        if variant != circle_query:
                            logger.info(
                                "[社团补全] Kikoeru circle_id 通过拆分子 keyword 命中 raw=%s variant=%s id=%s",
                                circle_query, variant, detected_circle_id,
                            )
                        break
                kikoeru_circle_id = self._set_cached_kikoeru_circle_id(
                    detected_circle_id,
                    f"name:{normalized_circle_query}",
                    maker_cache_key,
                )
                if kikoeru_circle_id:
                    self._save_persisted_kikoeru_circle_id(normalized_circle_query, kikoeru_circle_id, maker_id_hint)
            resolved_kikoeru_circle_id = kikoeru_circle_id
            kikoeru_works: List[Dict[str, Any]] = []
            if kikoeru_circle_id:
                report(26, "已识别 Kikoeru 社团，切换直连作品接口", kikoeru_circle_id=kikoeru_circle_id)
                try:
                    kikoeru_works = await self.kikoeru_service.list_circle_works(int(kikoeru_circle_id))
                except Exception:
                    logger.warning("[社团补全] Kikoeru 社团直连拉取失败，回退关键词搜索 circle_query=%s circle_id=%s", circle_query, kikoeru_circle_id, exc_info=True)
                    kikoeru_works = []
            if not kikoeru_works:
                # 直连失败 / 没找到 circle_id 时，依次用 keyword 变种再搜一遍 works，
                # 至少能把"作品标题里出现拆分子串"的作品拉回来给后续 identity 探测用。
                for variant in self._build_search_keyword_variants(circle_query):
                    try:
                        variant_works = await self.kikoeru_service.search_circle_works(variant)
                    except Exception:
                        variant_works = []
                    if variant_works:
                        if variant != circle_query:
                            logger.info(
                                "[社团补全] Kikoeru works 通过拆分子 keyword 命中 raw=%s variant=%s count=%s",
                                circle_query, variant, len(variant_works),
                            )
                        kikoeru_works = variant_works
                        break
            for work in kikoeru_works:
                ensure_not_cancelled()
                circle = work.get("circle", {}) if isinstance(work, dict) else {}
                circle_name = circle.get("name", "") if isinstance(circle, dict) else ""
                rjcode = self._guess_kikoeru_rjcode(work)
                if not rjcode:
                    continue
                kikoeru_tags = self._extract_text_values(work.get("tags"))
                kikoeru_category_values = []
                for key in ("work_category", "category", "category_name", "work_type", "type", "file_type", "file_format"):
                    kikoeru_category_values.extend(self._extract_text_values(work.get(key)))
                kikoeru_haystack = " ".join([
                    str(work.get("title") or ""),
                    *kikoeru_tags,
                    *kikoeru_category_values,
                ])
                if self._is_non_audio_package_text(kikoeru_haystack):
                    continue
                circle_id = ""
                if isinstance(circle, dict):
                    circle_id = self._normalize_kikoeru_circle_id(circle.get("id"))
                    if circle_id:
                        self._set_cached_kikoeru_circle_id(circle_id, f"name:{normalized_circle_query}")
                kikoeru_candidates.append({
                    "rjcode": rjcode,
                    "title": work.get("title", ""),
                    "maker_name": circle_name,
                    "maker_id": "",
                    "circle_id": circle_id,
                    "source": "kikoeru",
                    "kikoeru_work_id": work.get("id"),
                })

            if not resolved_kikoeru_circle_id:
                detected_from_works = next(
                    (self._normalize_kikoeru_circle_id(item.get("circle_id")) for item in kikoeru_candidates if item.get("circle_id")),
                    "",
                )
                if detected_from_works:
                    resolved_kikoeru_circle_id = self._set_cached_kikoeru_circle_id(
                        detected_from_works,
                        f"name:{normalized_circle_query}",
                    )
                    self._save_persisted_kikoeru_circle_id(normalized_circle_query, resolved_kikoeru_circle_id, maker_id_hint)

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
            dlsite_candidates = await self._collect_dlsite_circle_candidates(
                circle_query,
                identity_seed["maker_id"],
                progress_callback=report,
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
        # 新流程把所有外部 HTTP 集中到 ``_collect_external_snapshot()`` 一次跑完：
        #   Wave 1：拉 DLsite 作品资料 + 解析作品链路（candidate × 20 并发）。
        #   Wave 2a：在 ASMR.one 上核对每个 RJ 是否存在（30 并发，含翻译版全集）。
        #   Wave 2b：在 Kikoeru 上 **按作品链路 canonical 去重** 核对（20 并发）。
        #            一次 probe 会展开整条链路、查所有翻译版的查重状态，结果回灌
        #            给链上每个 RJ 的 cache。把 Kikoeru 查询次数从"全 RJ"压到
        #            "独立作品数"是这次优化的关键改动。
        #
        # Phase 2 阶段所有外部调用均 cache 命中（asmr 走 snapshot、Kikoeru 走
        # ``_kikoeru_state_cache``、DLsite 走 ``_metadata_cache`` / ``_canonical_cache``），
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
                f"准备核对 {len(snapshot_candidates)} 件候选作品的 DLsite / ASMR.one / Kikoeru 状态",
                prefetch_count=len(snapshot_candidates),
            )
            external_snapshot = await self._collect_external_snapshot(
                snapshot_candidates,
                force_refresh=force_refresh,
                progress_callback=_snapshot_progress,
                cancel_callback=cancel_callback,
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
                canonical_info = await self.resolve_canonical_rj(rjcode, refresh=force_refresh)
                canonical = canonical_info["canonical_rjcode"] or rjcode

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

        for future in asyncio.as_completed([prepare_candidate(item) for item in combined_candidates]):
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
        asmr_semaphore = asyncio.Semaphore(12)

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

        report(90, "补查 Kikoeru 服务器拥有态", aggregated_count=len(aggregated))
        checked_kikoeru = 0
        kikoeru_owned = 0
        kikoeru_semaphore = asyncio.Semaphore(10)

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

        # 把封面图同步缓存到本地 data/img/，避免前端每次都从 dlsite 加载，
        # dlsite 图片 CDN 在国内偶发抖动 / 代理掉链时整个社团页都会"白板"。
        # 卡片图和列表小图分开缓存：卡片图保留 RJxxxx.jpg，列表图写 RJxxxx_sam.jpg。
        cover_download_pairs: List[Tuple[str, str]] = []
        thumb_download_pairs: List[Tuple[str, str]] = []
        for canonical_rj, item in aggregated.items():
            cover_url = str(item.get("image_url") or "").strip()
            display_rj = self.normalize_rjcode(item.get("display_rjcode")) or canonical_rj
            if not display_rj or not cover_url.startswith(("http://", "https://")):
                continue
            cover_download_pairs.append((display_rj, cover_url))
            thumb_url = self._normalize_dlsite_thumb_url(
                cover_url,
                display_rj,
                is_unreleased=self._is_future_release_date(item.get("release_date")),
            )
            if thumb_url.startswith(("http://", "https://")):
                thumb_download_pairs.append((display_rj, thumb_url))
        if cover_download_pairs or thumb_download_pairs:
            report(
                92,
                f"缓存社团封面 {len(cover_download_pairs)} / 列表小图 {len(thumb_download_pairs)}",
                cover_total=len(cover_download_pairs),
                cover_thumb_total=len(thumb_download_pairs),
            )
            try:
                image_cache_service = get_circle_image_cache_service()
                cover_results = await image_cache_service.download_many(cover_download_pairs)
                thumb_results = await image_cache_service.download_many(thumb_download_pairs, variant="list")
                cover_cached_count = sum(1 for ok in cover_results.values() if ok)
                thumb_cached_count = sum(1 for ok in thumb_results.values() if ok)
                report(
                    93,
                    f"封面缓存完成 {cover_cached_count}/{len(cover_download_pairs)}，列表小图 {thumb_cached_count}/{len(thumb_download_pairs)}",
                    cover_total=len(cover_download_pairs),
                    cover_cached=cover_cached_count,
                    cover_thumb_total=len(thumb_download_pairs),
                    cover_thumb_cached=thumb_cached_count,
                )
            except Exception:
                # 封面缓存失败属于"非关键"路径，远程 URL 仍能展示；只 warning 不抛。
                logger.warning("[社团补全] 批量缓存封面失败", exc_info=True)

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
        report(96, "补刷特典字段", circle_id=circle_id)
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
        await self._refresh_circle_bonus_fields(circle_id, bonus_lookup_rjcodes)

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
        _index_duration_ms = max(0, int((time.monotonic() - _index_start_monotonic) * 1000))
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
                "duration_ms": _index_duration_ms,
                "task_duration_ms": _index_duration_ms,
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
        from sqlalchemy import or_ as sa_or, func as sa_func

        normalized = self.normalize_circle_name(keyword)
        safe_limit = max(1, int(limit))

        db = SessionLocal()
        try:
            catalog_query = db.query(CircleCatalog).order_by(CircleCatalog.last_indexed_at.desc())
            if normalized:
                pattern = f"%{normalized}%"
                # circle_name_normalized 列在写入时已 NFKC + lower 化；
                # circle_name / circle_id 用 SQL lower() 兜底，避免漏匹配。
                catalog_query = catalog_query.filter(
                    sa_or(
                        CircleCatalog.circle_name_normalized.like(pattern),
                        sa_func.lower(CircleCatalog.circle_name).like(pattern),
                        sa_func.lower(CircleCatalog.circle_id).like(pattern),
                    )
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

            if collected_ids:
                # === 完整 owned 计算（与右侧详情对齐）===
                # LEFT JOIN LibraryOwnedWork：CircleWork × LibraryOwnedWork 是 1 对 1，
                # 不会膨胀；在 Python 端做聚合，避免 SQLite case-when 跨方言复杂度。
                work_join_rows = (
                    db.query(
                        CircleWork.circle_id.label("circle_id"),
                        CircleWork.has_kikoeru.label("has_kikoeru"),
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
                    if r.has_kikoeru:
                        s["kikoeru_owned"] += 1
                    if r.has_asmr_one:
                        s["asmr_available"] += 1
                    if r.has_dlsite:
                        s["dl_works"] += 1
                    is_server_owned = bool(r.has_kikoeru)
                    is_local_owned = r.local_canonical is not None
                    if is_local_owned:
                        s["local_owned"] += 1
                    if is_server_owned or is_local_owned:
                        s["owned"] += 1

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

                # 批量统计未发售：左侧目录只提示仍未满足的预售作品，口径和右侧
                # 缺失作品区保持一致。已收录 / 本地已有的历史状态不再污染目录徽章。
                unreleased_rows = (
                    db.query(
                        CircleWork.circle_id,
                        WorkMetadata.release_date,
                        CircleWork.has_kikoeru,
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
                    if bool(ur.has_kikoeru) or ur.local_canonical is not None:
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
                # is_new_work 计算：必须同时满足 email_watcher 来源 + 锚在 48h 内
                row_tags = row.source_tags
                row_has_email_watcher = isinstance(row_tags, list) and "email_watcher" in row_tags
                row_anchor = row.email_watcher_first_seen_at or row.created_at
                _is_new = False
                if row_has_email_watcher and row_anchor and hasattr(row_anchor, "timestamp"):
                    _age = now_local_for_view.timestamp() - row_anchor.timestamp()
                    _is_new = 0 <= _age <= new_work_window_seconds
                item["is_new_work"] = _is_new
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
                release_date = str((metadata_map.get(stored_display_rjcode) or {}).get("release_date") or "").strip()
                if not release_date:
                    for metadata in metadata_map.values():
                        release_date = str((metadata or {}).get("release_date") or "").strip()
                        if release_date:
                            break
                item["release_date"] = release_date
                item["is_unreleased"] = self._is_future_release_date(release_date)
                item["price_text"] = str(getattr(row, "price_text", "") or "").strip()
                normalized_remote_cover = self._normalize_dlsite_cover_url(
                    item.get("image_url"),
                    row.display_rjcode or row.canonical_rjcode,
                    is_unreleased=item["is_unreleased"],
                )
                # 优先返回本地缓存的 API path（/api/circle-completion/cover/RJxxxxxx.jpg），
                # 没缓存就退回到 dlsite 公开 URL；前端 WorkCard.onCoverError 还有第二层
                # fallback（按 RJ 推算多个 dlsite 地址），所以单点失败不会让整页白板。
                local_cover_url = image_cache_service.get_local_url(
                    stored_display_rjcode or row.canonical_rjcode
                )
                local_thumb_url = image_cache_service.get_local_url(
                    stored_display_rjcode or row.canonical_rjcode,
                    variant="list",
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
                item["is_bonus_work"] = bool(getattr(row, "is_bonus_work", False))
                item["has_bonus"] = bool(getattr(row, "has_bonus", False))
                if item["is_bonus_work"]:
                    item["cvs"] = []
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
                completion_owned = bool(local_owned or server_owned)
                local_owned_rjcodes = list((owned_row.owned_rjcodes or []) if owned_row else [])
                owned_primary_rjcode = server_match_primary_rjcode or (local_owned_rjcodes[0] if local_owned_rjcodes else "")
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
                item["subtitle_present"] = bool((kikoeru_compare or {}).get("subtitle_present"))
                item["status_tags"] = [
                    *(["库存已收录"] if local_owned else []),
                    *(["本地已下载"] if item["local_download_ready"] else []),
                    *(["服务器已有"] if server_owned else ["服务器缺失"]),
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
            # 详情视图全程纯读，不再需要 db.commit()。
            # 写入由 index_circle_catalog / refresh_circle_works / email_watcher 直入负责。
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

        # === 阶段 A：短读事务 ===
        # 之前这里是"一个 db session 跨越整个循环"，循环里有十几个 await HTTP IO
        # （resolve_canonical / fetch_metadata / probe kikoeru / download_many 等），
        # SQLAlchemy session 自始至终都占着一个连接，又随 row.x = y 让 sqlite3 driver
        # BEGIN IMMEDIATE 持有写锁——其他任何写库的接口（任务中心写状态、操作日志、
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
                found_titles = {
                    self.normalize_rjcode(code): str(title or "").strip()
                    for code, title in dict(kikoeru_state.get("found_titles") or {}).items()
                    if self.normalize_rjcode(code) and self._is_usable_work_title(code, title)
                }
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
                row.image_url = self._normalize_dlsite_cover_url(
                    display_metadata.get("cover_url") or metadata.get("cover_url") or row.image_url,
                    row.display_rjcode or canonical,
                    is_unreleased=self._is_future_release_date(release_date),
                )
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

            # 把刷新后的封面图同步到本地缓存。force_refresh=True 时强制重新拉一次，
            # 普通刷新有本地缓存会 short-circuit，几乎免费跳过。
            cover_pairs: List[Tuple[str, str]] = []
            thumb_pairs: List[Tuple[str, str]] = []
            for refreshed_row in rows:
                cover_url = str(refreshed_row.image_url or "").strip()
                display_rj = (
                    self.normalize_rjcode(refreshed_row.display_rjcode)
                    or self.normalize_rjcode(refreshed_row.canonical_rjcode)
                )
                if not display_rj or not cover_url.startswith(("http://", "https://")):
                    continue
                cover_pairs.append((display_rj, cover_url))
                thumb_url = self._normalize_dlsite_thumb_url(
                    cover_url,
                    display_rj,
                    is_unreleased=self._is_future_release_date(getattr(refreshed_row, "release_date", "")),
                )
                if thumb_url.startswith(("http://", "https://")):
                    thumb_pairs.append((display_rj, thumb_url))
            if cover_pairs or thumb_pairs:
                try:
                    image_cache_service = get_circle_image_cache_service()
                    await image_cache_service.download_many(
                        cover_pairs, force=bool(force_refresh),
                    )
                    await image_cache_service.download_many(
                        thumb_pairs, variant="list", force=bool(force_refresh),
                    )
                except Exception:
                    logger.warning("[社团补全] refresh 阶段缓存封面失败", exc_info=True)

            # === 阶段 C：短写事务 ===
            # 把脱管的 rows / catalog 一次性 merge 回库并 commit；写锁仅在 commit 期间
            # 短暂持有，全程不阻塞其他写库的接口（任务中心、操作日志、邮件监听等）。
            now_ts = datetime.now()
            catalog.last_indexed_at = now_ts
            catalog.updated_at = now_ts
            write_db = SessionLocal()
            try:
                for refreshed_row in rows:
                    write_db.merge(refreshed_row)
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
