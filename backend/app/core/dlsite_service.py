"""
DLsite API 服务 - 用于获取作品关联信息和翻译链
参考 VoiceLinks 的实现
"""

import asyncio
import html
import httpx
import inspect
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)

_DLSITE_HTTP_CIRCUIT_FAILURE_THRESHOLD = 6
_DLSITE_HTTP_CIRCUIT_OPEN_SECONDS = 45.0
_DLSITE_HTTP_CIRCUIT: Dict[str, Any] = {
    "failures": 0,
    "open_until": 0.0,
    "last_error": "",
}
_POSTGRES_BIGINT_MAX = 9223372036854775807


def _dlsite_http_circuit_is_open() -> bool:
    return float(_DLSITE_HTTP_CIRCUIT.get("open_until") or 0.0) > time.monotonic()


def _dlsite_http_circuit_remaining_seconds() -> float:
    return max(0.0, float(_DLSITE_HTTP_CIRCUIT.get("open_until") or 0.0) - time.monotonic())


def _record_dlsite_http_success() -> None:
    _DLSITE_HTTP_CIRCUIT["failures"] = 0
    _DLSITE_HTTP_CIRCUIT["open_until"] = 0.0
    _DLSITE_HTTP_CIRCUIT["last_error"] = ""


def _record_dlsite_http_failure(error: Any) -> None:
    failures = int(_DLSITE_HTTP_CIRCUIT.get("failures") or 0) + 1
    _DLSITE_HTTP_CIRCUIT["failures"] = failures
    _DLSITE_HTTP_CIRCUIT["last_error"] = str(error or "")[:240]
    if failures >= _DLSITE_HTTP_CIRCUIT_FAILURE_THRESHOLD:
        _DLSITE_HTTP_CIRCUIT["open_until"] = time.monotonic() + _DLSITE_HTTP_CIRCUIT_OPEN_SECONDS
        logger.warning(
            "[DLsite] HTTP 短熔断开启 %.0fs failures=%s last_error=%s",
            _DLSITE_HTTP_CIRCUIT_OPEN_SECONDS,
            failures,
            _DLSITE_HTTP_CIRCUIT["last_error"],
        )


def _detect_brotli_support() -> bool:
    """检测当前 Python 环境是否能解压 Content-Encoding=br 响应。

    httpx 的 BrotliDecoder 会在使用时才尝试 import brotli/brotlicffi；
    如果两个都没装，response.text 就会拿到原始压缩字节，没人解码。
    在启动期主动探测一次，便于把 Accept-Encoding 调整成只用 gzip/deflate，
    避免远端给 br 压缩之后整页变乱码。
    """
    try:
        import brotlicffi  # noqa: F401
        return True
    except Exception:
        pass
    try:
        import brotli  # noqa: F401
        return True
    except Exception:
        return False


_BROTLI_AVAILABLE = _detect_brotli_support()
if not _BROTLI_AVAILABLE:
    logger.warning(
        "[DLsite] 未检测到 brotli/brotlicffi 库，Accept-Encoding 将自动降级为 'gzip, deflate'，"
        "DLsite 不会再返回 br 压缩响应，避免 HTML 解析为乱码导致社团补全 / 关键字搜索全线挂掉。"
        "强烈建议执行 `pip install brotlicffi` 恢复完整压缩支持。"
    )


@dataclass
class TranslationInfo:
    """翻译信息"""
    is_original: bool = False
    is_parent: bool = False
    is_child: bool = False
    parent_workno: Optional[str] = None
    original_workno: Optional[str] = None
    child_worknos: List[str] = field(default_factory=list)
    lang: str = "JPN"


@dataclass
class LinkedWork:
    """关联作品信息"""
    workno: str
    work_type: str  # original, translation, child_translation
    lang: str = "JPN"
    title: str = ""
    
    def to_dict(self) -> dict:
        return {
            'workno': self.workno,
            'work_type': self.work_type,
            'lang': self.lang,
            'title': self.title
        }


@dataclass
class DLsiteWorkSummary:
    """DLsite maker 主页 / announce 列表 HTML 上能直接看到的作品摘要。

    设计目标：

    - **零 product/info/ajax 调用**：纯靠列表 HTML 上 ``data-product_id`` /
      作品标题 / 作品类型 chip / category icon 等字段就能在 ``_collect_dlsite_circle_candidates``
      上反过滤掉漫画 / CG / 游戏 / 视频类作品，让 ``fetch_candidate`` 后面只在
      ASMR 候选上跑昂贵的 metadata 拉取。
    - **不替代 metadata**：列表页 HTML 信号噪音大、字段缺失常见，仍是弱信号；
      ``is_probably_audio`` 三态语义为：
        - ``True``：列表层 90%+ 把握是音声作品（带 SOU/audio 标签 / 文件标识 / 标题里有强信号词）。
        - ``False``：列表层强信号判定为非音声（manga/cg/RPG 等明确文件 type / category）。
        - ``None``：列表层没有足够信号，必须 fallback 到旧的 product/info/ajax 校验。

    历史现场（重构前）：大社团每个 RJ 都要先打 ``product.json`` + ``product/info/ajax``
    才能判定是否音声作品。RaRo 社团 362 件作品里只有 ~58% 是音声，但所有 362 件都得
    打两次 API，HTTP 量 720+ 次。新流程只对列表层 ``is_probably_audio is None``
    的 RJ 才进入 metadata 链路，预期能省 50-70% 的列表阶段 HTTP。
    """
    workno: str
    title: str = ""
    maker_id: str = ""
    maker_name: str = ""
    category_label: str = ""  # 列表 HTML 上的 work_category chip 文案（"音声" / "ボイス・ASMR" / "漫画" 等）
    work_type_code: str = ""  # 列表 HTML 上的 work_type code，如 SOU / RPG / ICG
    file_format_labels: List[str] = field(default_factory=list)  # 文件形态 chip 文案（"音声" / "WAV" / "mp4" 等）
    icon_classes: List[str] = field(default_factory=list)  # work-category icon CSS class，如 "type_SOU" / "type_RPG"
    cover_url: str = ""
    is_probably_audio: Optional[bool] = None  # 列表层判定：True 音声 / False 非音声 / None 不确定
    classification_reason: str = ""  # 为什么判 True/False，纯调试用
    release_date: str = ""  # 发售日列表页上的日期，尽量归一为 YYYY-MM-DD

    def to_dict(self) -> dict:
        return {
            'workno': self.workno,
            'title': self.title,
            'maker_id': self.maker_id,
            'maker_name': self.maker_name,
            'category_label': self.category_label,
            'work_type_code': self.work_type_code,
            'file_format_labels': list(self.file_format_labels),
            'icon_classes': list(self.icon_classes),
            'cover_url': self.cover_url,
            'is_probably_audio': self.is_probably_audio,
            'classification_reason': self.classification_reason,
            'release_date': self.release_date,
        }


@dataclass
class DLsiteProductProbeFeature:
    """隐藏特典探测用的 product/info/ajax 归一字段。"""
    workno: str
    exists: bool = False
    probe_status: str = "missing"
    maker_id: str = ""
    release_date: str = ""
    work_type: str = ""
    price: int = 0
    is_sale: bool = False
    is_free: bool = False
    is_oly: bool = False
    wishlist_count: int = 0
    is_hidden_bonus_audio: bool = False
    title: str = ""
    raw_summary_json: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            'workno': self.workno,
            'exists': bool(self.exists),
            'probe_status': self.probe_status,
            'maker_id': self.maker_id,
            'release_date': self.release_date,
            'work_type': self.work_type,
            'price': int(self.price or 0),
            'is_sale': bool(self.is_sale),
            'is_free': bool(self.is_free),
            'is_oly': bool(self.is_oly),
            'wishlist_count': int(self.wishlist_count or 0),
            'is_hidden_bonus_audio': bool(self.is_hidden_bonus_audio),
            'title': self.title,
            'raw_summary_json': dict(self.raw_summary_json or {}),
            'error_message': self.error_message,
        }


def normalize_product_probe_feature_classification(
    feature: DLsiteProductProbeFeature,
) -> DLsiteProductProbeFeature:
    """按当前结构规则重算特典标记，兼容历史错误缓存。"""
    raw_summary = feature.raw_summary_json or {}
    wishlist_count = raw_summary.get("raw_wishlist_count", feature.wishlist_count)
    wishlist_is_zero = not isinstance(wishlist_count, bool) and wishlist_count == 0
    feature.is_hidden_bonus_audio = bool(
        feature.exists
        and feature.probe_status == "ok"
        and feature.maker_id
        and int(feature.price or 0) == 0
        and not bool(feature.is_sale)
        and bool(feature.is_free)
        and bool(feature.is_oly)
        and wishlist_is_zero
    )
    return feature


# ============ 列表页 summary 分类规则（用于 _classify_listing_summary_audio） ============
# 命中即判 True。这些都是 DLsite 列表 chip / icon 上专属于音声 / ASMR 作品的强信号。
# 注意：``ASMR`` 也是一种音声分类标签，列表层有专属 chip；不需要靠正文 tag 强匹配。
_LISTING_AUDIO_WORK_TYPE_CODES: Set[str] = {"SOU"}
_LISTING_AUDIO_ICON_CLASSES: Set[str] = {"type_SOU", "type_ASMR", "work_audio"}
_LISTING_AUDIO_CATEGORY_KEYWORDS: List[str] = [
    "音声",        # JP "音声作品"
    "ボイス",      # JP "ボイス・ASMR"
    "asmr",        # ENG ASMR chip
    "音声作品",
    "drama",       # drama cd 类
]
_LISTING_AUDIO_FILE_FORMAT_KEYWORDS: List[str] = [
    "mp3",
    "wav",
    "flac",
    "ogg",
    "aac",
    "m4a",
    "音声",
]

# 命中即判 False。这些是列表 chip / icon 上专属于非音声作品的强信号。
# 命中后会让 _classify_listing_summary_audio 直接返回 False，跳过 metadata。
_LISTING_NON_AUDIO_WORK_TYPE_CODES: Set[str] = {
    "RPG", "ADV", "SLN", "TBL", "ACN", "STG", "PZL", "QIZ", "ETC",  # 游戏类
    "ICG", "MNG", "CMC", "DNV",  # 漫画 / 插画 / 数字小说
    "MOV", "VCM",  # 视频 / 动画 / 实拍
    "GAM",  # 通用游戏
}
_LISTING_NON_AUDIO_ICON_CLASSES: Set[str] = {
    "type_RPG", "type_ADV", "type_SLN", "type_TBL",
    "type_ACN", "type_STG", "type_PZL", "type_QIZ",
    "type_ETC", "type_ICG", "type_MNG", "type_CMC",
    "type_DNV", "type_MOV", "type_VCM", "type_GAM",
    "work_game", "work_comic", "work_video",
}
_LISTING_NON_AUDIO_CATEGORY_KEYWORDS: List[str] = [
    "漫画", "manga", "cg", "插画", "插畫", "イラスト",
    "ゲーム", "rpg", "アドベンチャー",
    "动画", "動画", "video", "mov", "实拍",
    "小説", "小说", "novel", "テキスト",
    "ボイスドラマ動画",
]


class DLsiteApiService:
    """DLsite API 服务"""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self._client_proxy_url: str = ""
        # 原 dict cache 在长期运行下会无界增长（HTML 页面 key 尤其大，单条 20-200KB）。
        # 换成 TTL+LRU：容量上限 512，TTL 24h；payload 里仍保留 timestamp 字段，
        # 原代码里自己对比 cache_ttl 的逻辑可以继续生效，功能零侵入。
        self.cache: TTLCache = TTLCache(max_size=512, ttl_seconds=86400, name="dlsite.cache")
        self.cache_ttl = timedelta(hours=24)  # 缓存 24 小时（沿用给现有代码做内层 TTL 判定）
        self._http_semaphore: Optional[asyncio.Semaphore] = None  # 并发限制，惰性初始化
        # 进行中的 HTTP 请求 Task，key=url，实现并发去重（参考 view.txt WorkPromise 机制）
        self._inflight: Dict[str, asyncio.Task] = {}
        # translation_info 专项缓存，key=workno，避免重复走 get_product_info
        self._translation_info_cache: TTLCache = TTLCache(max_size=2048, ttl_seconds=86400, name="dlsite.translation_info")
        # ★ 性能优化：``get_linked_works`` 函数级 inflight 去重 + cache。
        # 之前没 cache 时，一次 33 个候选的社团补全任务跑出了 2819 次 ``get_linked_works`` 调用
        # （每个 candidate 在 prepare_candidate / resolve_canonical_rj / Kikoeru
        # check_duplicate_with_linkages 三处都会触发一次，每次都做完整递归
        # 包括对所有翻译版子探测）。加 cache 后，同一任务内同一个 RJ 只算一次完整递归，
        # 其他调用走 self.cache 短路；inflight 防止并发协程同时算同一 RJ。
        self._linked_works_inflight: Dict[str, asyncio.Task] = {}

    def _normalize_workno(self, rjcode: str) -> str:
        value = str(rjcode or '').strip().upper()
        match = re.search(r'[RVB]J(?:\d{8}|\d{6})(?!\d)', value, re.IGNORECASE)
        return match.group(0).upper() if match else value

    def _safe_product_int(self, value: Any, *, field: str, workno: str) -> int:
        if value is None or isinstance(value, bool):
            return 0
        try:
            if isinstance(value, str):
                text = value.strip().replace(",", "")
                if not text:
                    return 0
                number = int(float(text)) if "." in text else int(text)
            else:
                number = int(value)
        except Exception:
            logger.debug("[DLsite] product/info/ajax 数值字段无法解析 workno=%s field=%s value=%r", workno, field, value)
            return 0
        if number < 0:
            return 0
        if number > _POSTGRES_BIGINT_MAX:
            logger.warning(
                "[DLsite] product/info/ajax 数值字段超过 BIGINT 范围，已按 0 处理 workno=%s field=%s value=%s",
                workno,
                field,
                value,
            )
            return 0
        return number

    def _build_product_api_url(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={workno}"
        if locale:
            url = f"{url}&locale={locale}"
        return url

    def _build_product_info_ajax_url(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        url = f"https://www.dlsite.com/maniax/product/info/ajax?product_id={workno}&cdn_cache_min=1"
        if locale:
            url = f"{url}&locale={locale}"
        return url

    def _build_product_info_ajax_bulk_url(self, rjcodes: List[str], locale: Optional[str] = None) -> str:
        worknos: List[str] = []
        for value in rjcodes or []:
            workno = self._normalize_workno(value)
            if workno and workno not in worknos:
                worknos.append(workno)
        url = f"https://www.dlsite.com/maniax/product/info/ajax?product_id={','.join(worknos)}&cdn_cache_min=1"
        if locale:
            url = f"{url}&locale={locale}"
        return url

    def _format_api_url_for_log(self, url: str) -> str:
        text = str(url or "")
        marker = "/product/info/ajax?product_id="
        if marker not in text:
            return text
        prefix, rest = text.split(marker, 1)
        product_ids = rest.split("&", 1)[0]
        worknos = [item for item in product_ids.split(",") if item]
        if len(worknos) <= 8:
            return text
        suffix = ""
        if "&" in rest:
            suffix = "&" + rest.split("&", 1)[1]
        return (
            f"{prefix}{marker}<bulk:{len(worknos)} rjcodes "
            f"{worknos[0]}..{worknos[-1]}>{suffix}"
        )

    def _build_product_page_url(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        url = f"https://www.dlsite.com/maniax/work/=/product_id/{workno}.html"
        if locale:
            url = f"{url}/?locale={locale}"
        return url

    def _build_announce_product_page_url(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        url = f"https://www.dlsite.com/maniax/announce/=/product_id/{workno}.html"
        if locale:
            url = f"{url}/?locale={locale}"
        return url

    def _build_circle_profile_url(self, maker_id: str, language: str = "JPN", page: int = 1) -> str:
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        base = f"https://www.dlsite.com/maniax/circle/profile/=/maker_id/{normalized_maker_id}.html/options[0]/{normalized_language}"
        if page > 1:
            return f"{base}/page/{page}"
        return base

    def _build_circle_profile_touch_url(self, maker_id: str, page: int = 1) -> str:
        normalized_maker_id = str(maker_id or "").strip().upper()
        base = f"https://www.dlsite.com/maniax-touch/circle/profile/=/maker_id/{normalized_maker_id}.html"
        if page > 1:
            return f"{base}/page/{page}"
        return base

    def _build_circle_announce_url(self, maker_id: str, language: str = "JPN", page: int = 1) -> str:
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        base = f"https://www.dlsite.com/maniax/announce/=/maker_id/{normalized_maker_id}.html/options[0]/{normalized_language}"
        if page > 1:
            return f"{base}/page/{page}"
        return base

    def _build_new_release_date_url(self, release_date: str, *, language: str = "JPN", page: int = 1) -> str:
        normalized_date = self._normalize_date_text(release_date)
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        base = f"https://www.dlsite.com/maniax/new/=/date/{normalized_date}/options[0]/{normalized_language}"
        if page > 1:
            return f"{base}/page/{page}"
        return base

    def _get_browser_headers(self, accept: str = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8') -> Dict[str, str]:
        # ★ 关键安全开关：只有当 brotli/brotlicffi 真的能 import 时才声明支持 br，
        #   否则 DLsite 会按 Accept-Encoding 给我们 br 压缩响应，httpx 不解压，
        #   response.text 直接是乱码二进制 → 社团 profile 解析为 0，整条任务退化
        #   到关键字搜索 + 全站推荐位 RJ 污染。
        accept_encoding = 'gzip, deflate, br' if _BROTLI_AVAILABLE else 'gzip, deflate'
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': accept,
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': accept_encoding,
            'Referer': 'https://www.dlsite.com/maniax/',
            'Origin': 'https://www.dlsite.com',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Sec-CH-UA': '"Chromium";v="120", "Google Chrome";v="120", "Not_A Brand";v="99"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Cookie': 'adultchecked=1; locale=ja-jp',
            'Connection': 'keep-alive',
        }

    def _get_api_headers(self) -> Dict[str, str]:
        headers = self._get_browser_headers('application/json, text/plain, */*')
        headers.update({
            'Upgrade-Insecure-Requests': '0',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'X-Requested-With': 'XMLHttpRequest',
        })
        return headers

    def _format_exc(self, exc: BaseException) -> str:
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    def _normalize_proxy_url(self, proxy: str) -> str:
        value = str(proxy or '').strip()
        if not value:
            return ''
        if re.match(r'^[a-z][a-z0-9+.-]*://', value, re.IGNORECASE):
            return value
        return f"http://{value}"

    def _mask_proxy_url(self, proxy: str) -> str:
        value = self._normalize_proxy_url(proxy)
        if not value:
            return ''
        parsed = urlparse(value)
        if not parsed.username and not parsed.password:
            return value
        host = parsed.hostname or ''
        port = f":{parsed.port}" if parsed.port else ''
        user = parsed.username or ''
        auth = f"{user}:***@" if user else "***@"
        return f"{parsed.scheme}://{auth}{host}{port}"

    def _extract_product_codes_from_url(self, url: str) -> Dict[str, str]:
        parsed = urlparse(str(url or ''))
        path_match = re.search(r'/product_id/([RVB]J(?:\d{8}|\d{6}))\.html', parsed.path, re.IGNORECASE)
        query = parse_qs(parsed.query)
        return {
            'product_workno': path_match.group(1).upper() if path_match else '',
            'translation_workno': str((query.get('translation') or [''])[0] or '').strip().upper(),
        }

    def _normalize_date_text(self, value: Any) -> str:
        text = str(value or '').strip()
        if not text:
            return ''
        match = re.search(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})', text)
        if not match:
            match = re.search(r'(20\d{2})(\d{2})(\d{2})', text)
        if not match:
            return text[:20]
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    def _extract_release_date_from_listing_chunk(self, chunk: str) -> str:
        if not chunk:
            return ''
        for pattern in [
            r'(?:regist_date|release_date|sales_date)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'class="[^"]*(?:regist_date|release_date|work_date|date)[^"]*"[^>]*>\s*([^<\n]+?)\s*</',
            r'(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})',
            r'(20\d{6})',
        ]:
            match = re.search(pattern, chunk, re.IGNORECASE)
            if match:
                normalized = self._normalize_date_text(html.unescape(match.group(1)).strip())
                if normalized:
                    return normalized
        return ''

    def _extract_worknos_from_listing_html(self, text: str) -> List[str]:
        if not text:
            return []
        seen = set()
        result: List[str] = []
        patterns = [
            r'/(?:work|announce)/=/product_id/([RVB]J(?:\d{8}|\d{6}))(?:\.html)?',
            r'product_id["\']?\s*[:=]\s*["\']([RVB]J(?:\d{8}|\d{6}))["\']',
            r'workno["\']?\s*[:=]\s*["\']([RVB]J(?:\d{8}|\d{6}))["\']',
        ]
        for pattern in patterns:
            for matched in re.findall(pattern, text, re.IGNORECASE):
                workno = self._normalize_workno(matched)
                if workno and workno not in seen:
                    seen.add(workno)
                    result.append(workno)
        return result

    def _extract_any_worknos_from_listing_html(self, text: str) -> List[str]:
        if not text:
            return []
        seen = set()
        result: List[str] = []
        for matched in re.findall(r'[RVB]J(?:\d{8}|\d{6})', text, re.IGNORECASE):
            workno = self._normalize_workno(matched)
            if workno and workno not in seen:
                seen.add(workno)
                result.append(workno)
        return result

    def _extract_summaries_from_listing_html(self, text: str) -> List[DLsiteWorkSummary]:
        """从 DLsite maker 主页 / announce 列表页 HTML 提取每个 RJ 的 ``DLsiteWorkSummary``。

        策略：

        - 用 ``<li class="search_result_img_box_inner"> ... </li>`` 这种作品卡片块的边界
          切分 HTML，每一段对应一个 RJ。对每段单独跑字段级正则，避免跨作品串字段。
        - 切分失败 / 块少时 fallback 到 ``_extract_worknos_from_listing_html`` —— 这意味着
          列表层没有 summary 增益，下游会全部走 ``is_probably_audio=None`` 进 metadata 链路，
          降级为旧行为，不会出错。

        提取的字段：

        - ``workno``：必填，从 ``data-product_id`` / href 上 ``product_id/RJ...`` 二选一。
        - ``title``：作品名链接的 ``alt`` 属性或锚文本。
        - ``category_label`` / ``work_type_code`` / ``icon_classes``：DLsite 列表 chip 上的
          ``work_category`` / ``work_type`` 文案 / icon class。
        - ``file_format_labels``：``work_file_format`` chip 数组（实测主要 announce 列表才有）。

        所有字段缺失时回 dataclass 默认值，下游 ``_classify_listing_summary_audio`` 会自动
        转成 ``None`` 让 fallback 接管。
        """
        if not text:
            return []
        chunks: List[str] = []
        for pattern in [
            # maniax new/date PC template
            r'<div[^>]*class="[^"]*n_worklist_item[^"]*"[^>]*>.*?(?=<div[^>]*class="[^"]*n_worklist_item|\Z)',
            # maker_profile 经典 PC 模板
            r'<li[^>]*class="[^"]*search_result_img_box_inner[^"]*"[^>]*>.*?</li>',
            # maniax-touch / SP 模板
            r'<li[^>]*class="[^"]*work_1col[^"]*"[^>]*>.*?</li>',
            r'<li[^>]*class="[^"]*work_2col[^"]*"[^>]*>.*?</li>',
            # announce 列表
            r'<div[^>]*class="[^"]*work_news_each[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
        ]:
            try:
                chunks.extend(re.findall(pattern, text, re.IGNORECASE | re.DOTALL))
            except Exception:
                continue
        # 当所有模板都没匹到时（DLsite 改版 / 极简 SSR），fallback：以 product_id 锚点切片。
        if not chunks:
            anchors = list(re.finditer(r'/(?:work|announce)/=/product_id/([RVB]J(?:\d{8}|\d{6}))', text, re.IGNORECASE))
            for i, m in enumerate(anchors):
                start = max(0, m.start() - 400)
                end = min(len(text), (anchors[i + 1].start() if i + 1 < len(anchors) else m.end() + 1200))
                chunks.append(text[start:end])

        summaries: List[DLsiteWorkSummary] = []
        seen: Set[str] = set()
        for chunk in chunks:
            workno = ""
            # 1) data-product_id 属性优先（HTML5 自定义属性）
            m = re.search(r'data-product_id\s*=\s*["\']([RVB]J(?:\d{8}|\d{6}))["\']', chunk, re.IGNORECASE)
            if m:
                workno = self._normalize_workno(m.group(1))
            # 2) href 上 product_id/RJxxx
            if not workno:
                m = re.search(r'/(?:work|announce)/=/product_id/([RVB]J(?:\d{8}|\d{6}))', chunk, re.IGNORECASE)
                if m:
                    workno = self._normalize_workno(m.group(1))
            if not workno or workno in seen:
                continue
            seen.add(workno)

            summary = DLsiteWorkSummary(workno=workno)

            # 标题：作品链接的 alt / title / 锚文本
            for pat in [
                r'<img[^>]*alt\s*=\s*["\']([^"\']+)["\'][^>]*src=["\'][^"\']*(?:product|resize)[^"\']*' + re.escape(workno.lower()) + r'[^"\']*["\']',
                r'class="[^"]*work_name[^"]*"[^>]*>\s*<a[^>]*title=["\']([^"\']+)["\']',
                r'class="[^"]*work_name[^"]*"[^>]*>\s*<a[^>]*>\s*([^<\n]+?)\s*</a>',
            ]:
                m = re.search(pat, chunk, re.IGNORECASE)
                if m:
                    summary.title = html.unescape(m.group(1)).strip()
                    break

            # maker 链接：href 上 maker_id 与文案
            m = re.search(r'/(?:circle/profile|maker)/=/maker_id/(RG\d+)', chunk, re.IGNORECASE)
            if m:
                summary.maker_id = m.group(1).upper()
            m = re.search(
                r'class="[^"]*maker_name[^"]*"[^>]*>\s*<a[^>]*>\s*([^<\n]+?)\s*</a>',
                chunk,
                re.IGNORECASE,
            )
            if m:
                summary.maker_name = html.unescape(m.group(1)).strip()

            # cover：列表缩略图 src（避免懒加载占位图）
            m = re.search(
                r'<img[^>]*(?:src|data-src)\s*=\s*["\']([^"\']*resize[^"\']*' + re.escape(workno.lower()) + r'[^"\']*)["\']',
                chunk,
                re.IGNORECASE,
            )
            if m:
                summary.cover_url = m.group(1).strip()

            summary.release_date = self._extract_release_date_from_listing_chunk(chunk)

            # work_category / work_type chip：class 名 + 文案分两条解析，避免任一缺失
            for m in re.finditer(
                r'class="[^"]*(work_category|work_genre|category_name)[^"]*"[^>]*>\s*([^<\n]+?)\s*</',
                chunk,
                re.IGNORECASE,
            ):
                label = html.unescape(m.group(2)).strip()
                if label and not summary.category_label:
                    summary.category_label = label
            # work_type chip 在 PC 模板里通常是 type="type_SOU" 的 class
            for m in re.finditer(
                r'class="[^"]*(type_[A-Z]{2,5}|work_audio|work_game|work_comic|work_video)[^"]*"',
                chunk,
            ):
                token = m.group(1).strip()
                if token and token not in summary.icon_classes:
                    summary.icon_classes.append(token)
                    if not summary.work_type_code and token.startswith("type_"):
                        summary.work_type_code = token[len("type_"):]

            # file_format chip（announce + maker 主页都偶尔出现）
            for m in re.finditer(
                r'class="[^"]*work_file_format[^"]*"[^>]*>\s*([^<\n]+?)\s*</',
                chunk,
                re.IGNORECASE,
            ):
                label = html.unescape(m.group(1)).strip()
                if label and label not in summary.file_format_labels:
                    summary.file_format_labels.append(label)

            summary.is_probably_audio, summary.classification_reason = self._classify_listing_summary_audio(summary)
            summaries.append(summary)

        return summaries

    def _classify_listing_summary_audio(
        self, summary: DLsiteWorkSummary
    ) -> tuple[Optional[bool], str]:
        """按列表 chip / icon / 类目文案三态分类音声作品。

        返回 ``(is_probably_audio, reason)``：

        - ``True`` → 列表强信号判定音声，``_collect_dlsite_circle_candidates`` 可跳过 metadata
          只做轻量校验（product.json maker_id + work_type）。
        - ``False`` → 列表强信号判定非音声，直接丢弃这个 RJ，**不** 走 metadata 链路。
        - ``None`` → 列表信号不足，fallback 到旧的 ``_fetch_metadata_dict`` + ``_classify_asmr_work_candidate``。

        分类顺序：work_type_code > icon_classes > category_label > file_format_labels > 标题关键词。
        命中 audio 强信号优先返 True；只在 audio 强信号全部 miss 时才看 non-audio 强信号。
        """
        # work_type_code（最强信号）
        if summary.work_type_code:
            code = summary.work_type_code.strip().upper()
            if code in _LISTING_AUDIO_WORK_TYPE_CODES:
                return True, f"work_type_code={code}"
            if code in _LISTING_NON_AUDIO_WORK_TYPE_CODES:
                return False, f"work_type_code={code} 非音声"

        # icon class（次强信号）
        for icon in summary.icon_classes:
            if icon in _LISTING_AUDIO_ICON_CLASSES:
                return True, f"icon={icon}"
        for icon in summary.icon_classes:
            if icon in _LISTING_NON_AUDIO_ICON_CLASSES:
                return False, f"icon={icon} 非音声"

        # category_label / 标题（中等强度信号）
        category = summary.category_label.lower()
        title_lower = summary.title.lower()
        if category:
            for kw in _LISTING_AUDIO_CATEGORY_KEYWORDS:
                if kw in category or kw in title_lower:
                    return True, f"category 命中 {kw}"
            for kw in _LISTING_NON_AUDIO_CATEGORY_KEYWORDS:
                if kw in category:
                    return False, f"category={kw} 非音声"

        # file_format chip（兜底，主要 announce 列表才有）
        for label in summary.file_format_labels:
            lower = label.lower()
            for kw in _LISTING_AUDIO_FILE_FORMAT_KEYWORDS:
                if kw in lower:
                    return True, f"file_format 命中 {kw}"

        return None, ""

    def _extract_not_product_ids_from_html(self, text: str) -> List[str]:
        """从 maniax-touch 分页 href 的 not_product_ids 参数中提取 RJcode。
        
        当 maniax-touch 页面正文没有标准作品链接时（服务器直连 DLsite），
        页面内的"下一页"href 仍可能包含 not_product_ids[0]=RJxxxxxxxx 参数，
        从中可还原出当前页已展示的作品列表。
        """
        if not text:
            return []
        # 提取 URL 编码或原始格式的 not_product_ids 值
        # 示例: not_product_ids%5B0%5D/RJ01234567 或 not_product_ids[0]/RJ01234567
        pattern = re.compile(
            r'not_product_ids(?:%5B|\[)\d+(?:%5D|\])[/=]([RVB]J(?:\d{8}|\d{6}))',
            re.IGNORECASE,
        )
        seen: set = set()
        result: List[str] = []
        for matched in pattern.findall(text):
            workno = self._normalize_workno(matched)
            if workno and workno not in seen:
                seen.add(workno)
                result.append(workno)
        return result

    def _extract_translation_linkage_from_html(self, html: str, requested_workno: str) -> Dict[str, str]:
        normalized_requested = self._normalize_workno(requested_workno)
        if not html or not normalized_requested:
            return {}

        pattern = re.compile(
            r'product_id/([RVB]J(?:\d{8}|\d{6}))\.html[^"\'>\s]*translation=([RVB]J(?:\d{8}|\d{6}))',
            re.IGNORECASE,
        )
        for match in pattern.finditer(str(html or '')):
            product_workno = match.group(1).upper()
            translation_workno = match.group(2).upper()
            if translation_workno == normalized_requested and product_workno != normalized_requested:
                return {
                    'product_workno': product_workno,
                    'translation_workno': translation_workno,
                }
        return {}

    def _extract_translation_worknos_from_html(self, html: str, base_workno: str = '') -> List[str]:
        normalized_base = self._normalize_workno(base_workno)
        if not html:
            return []

        seen = set()
        result: List[str] = []
        pattern = re.compile(
            r'product_id/([RVB]J(?:\d{8}|\d{6}))\.html[^"\'>\s]*translation=([RVB]J(?:\d{8}|\d{6}))',
            re.IGNORECASE,
        )
        for match in pattern.finditer(str(html or '')):
            product_workno = self._normalize_workno(match.group(1))
            translation_workno = self._normalize_workno(match.group(2))
            if product_workno and product_workno not in seen:
                seen.add(product_workno)
                result.append(product_workno)
            if not translation_workno:
                continue
            if translation_workno not in seen:
                seen.add(translation_workno)
                result.append(translation_workno)
        if normalized_base and normalized_base not in seen:
            result.append(normalized_base)
        return result

    def _decode_html_value(self, value: Optional[str]) -> str:
        return html.unescape(str(value or '').strip())

    def _decode_json_string(self, value: Optional[str]) -> str:
        raw = str(value or '')
        if not raw:
            return ''
        try:
            return html.unescape(json.loads(f'"{raw}"'))
        except Exception:
            return html.unescape(raw.replace('\\"', '"').replace("\\/", "/"))

    def _extract_json_string(self, text: str, key: str) -> str:
        if not text:
            return ''
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            rf"'{re.escape(key)}'\s*:\s*'((?:\\.|[^'\\])*)'",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return self._decode_json_string(match.group(1))
        return ''

    def _extract_html_meta(self, text: str, key: str) -> str:
        if not text:
            return ''
        patterns = [
            rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
            rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._decode_html_value(match.group(1))
        return ''

    def _normalize_image_url(self, url: str) -> str:
        value = self._decode_html_value(url)
        if not value:
            return ''
        if value.startswith('//'):
            return f'https:{value}'
        return value

    def _normalize_release_date(self, value: str) -> str:
        raw = self._decode_html_value(value)
        if not raw:
            return ''
        match = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', raw)
        if not match:
            return raw[:10]
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    def _extract_price_text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return f"{int(value):,}円" if int(value) > 0 else "0円"
        text = self._decode_html_value(str(value))
        if not text:
            return ""
        match = re.search(r'([0-9][0-9,]*)\s*円', text)
        if match:
            return f"{match.group(1)}円"
        if text.isdigit():
            return f"{int(text):,}円" if int(text) > 0 else "0円"
        return text.strip()

    def _extract_product_price_text(self, product: Dict) -> str:
        if not isinstance(product, dict):
            return ""
        for key in ("price_text", "price_str", "price", "official_price", "work_price", "sales_price"):
            price_text = self._extract_price_text(product.get(key))
            if price_text:
                return price_text
        return ""

    def _extract_name_list(self, text: str, section_pattern: str) -> List[Dict[str, str]]:
        if not text:
            return []
        section_match = re.search(section_pattern, text, re.IGNORECASE | re.DOTALL)
        if not section_match:
            return []
        names = []
        seen = set()
        for raw_name in re.findall(r'"name"\s*:\s*"((?:\\.|[^"\\])*)"', section_match.group(1), re.IGNORECASE):
            decoded = self._decode_json_string(raw_name)
            if decoded and decoded not in seen:
                seen.add(decoded)
                names.append({'name': decoded})
        return names

    def _extract_work_category_name(self, text: str) -> str:
        if not text:
            return ''
        match = re.search(
            r'<div[^>]+class="[^"]*\bwork_category\b[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ''
        return self._decode_html_value(re.sub(r'<[^>]+>', '', match.group(1)))

    def _extract_outline_field_values(self, text: str) -> Dict[str, object]:
        if not text:
            return {}
        table_match = re.search(
            r'<table[^>]+id=["\']work_outline["\'][^>]*>(.*?)</table>',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not table_match:
            return {}

        result: Dict[str, object] = {}
        row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL)
        cell_pattern = re.compile(r'<t[hd][^>]*>(.*?)</t[hd]>', re.IGNORECASE | re.DOTALL)
        for row_match in row_pattern.finditer(table_match.group(1)):
            cells = cell_pattern.findall(row_match.group(1))
            if len(cells) < 2:
                continue
            header = self._decode_html_value(re.sub(r'<[^>]+>', '', cells[0])).strip()
            body_html = cells[1]
            body_text = self._decode_html_value(re.sub(r'<[^>]+>', '', body_html)).strip()
            if not header or not body_text:
                continue

            if header in {"販売日", "发售日", "販賣日", "Release date"}:
                result["release_date"] = body_text
                continue
            if header in {"ジャンル", "分类", "分類", "Genre"}:
                tags: List[str] = []
                for tag_html in re.findall(r'<a[^>]*>(.*?)</a>', body_html, re.IGNORECASE | re.DOTALL):
                    tag_text = self._decode_html_value(re.sub(r'<[^>]+>', '', tag_html)).strip()
                    if tag_text and tag_text not in tags:
                        tags.append(tag_text)
                if not tags and body_text:
                    tags = [part.strip() for part in re.split(r'[／/,|]', body_text) if part.strip()]
                if tags:
                    result["genres"] = [{"name": tag} for tag in tags]
                continue
            if header in {"声優", "声优", "聲優", "Voice Actor"}:
                names = [part.strip() for part in re.split(r'[／/,|]', body_text) if part.strip()]
                if names:
                    result["voice_by"] = [{"name": name} for name in names]
                continue
            if header in {"作品形式", "作品类型", "作品類型", "Work format", "作品种类", "作品種類"}:
                result["work_category"] = body_text
                continue

        announce_date_match = re.search(
            r'<strong[^>]+class=["\'][^"\']*\bwork_date_ana\b[^"\']*["\'][^>]*>(.*?)</strong>',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if announce_date_match and not result.get("release_date"):
            result["release_date"] = self._decode_html_value(re.sub(r'<[^>]+>', '', announce_date_match.group(1))).strip()

        return result

    def _extract_image_main_url(self, text: str) -> str:
        if not text:
            return ''
        match = re.search(
            r'"image_main"\s*:\s*\{.*?"url"\s*:\s*"((?:\\.|[^"\\])*)"',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ''
        return self._decode_json_string(match.group(1))

    def _parse_product_from_html(self, requested_workno: str, page_url: str, final_url: str, page_html: str) -> Optional[Dict]:
        if not page_html:
            return None

        title = self._extract_json_string(page_html, 'work_name') or self._extract_html_meta(page_html, 'og:title')
        if title:
            title = re.sub(r'\s*\[[^\]]+\]\s*予告作品\s*\|\s*DLsite\s*$', '', title).strip()
        maker_name = self._extract_json_string(page_html, 'maker_name')
        maker_id = self._extract_json_string(page_html, 'maker_id')
        series_name = self._extract_json_string(page_html, 'series_name')
        series_id = self._extract_json_string(page_html, 'series_id')
        release_date = self._normalize_release_date(
            self._extract_json_string(page_html, 'regist_date')
            or self._extract_html_meta(page_html, 'article:published_time')
            or self._extract_html_meta(page_html, 'release_date')
        )
        image_url = self._normalize_image_url(
            self._extract_image_main_url(page_html)
        ) or self._normalize_image_url(self._extract_html_meta(page_html, 'og:image'))

        genres = self._extract_name_list(page_html, r'"genres"\s*:\s*\[(.*?)\]')
        category_name = self._extract_work_category_name(page_html)
        voice_by = self._extract_name_list(page_html, r'"voice_by"\s*:\s*\[(.*?)\]')
        outline_fields = self._extract_outline_field_values(page_html)
        outline_release_date = self._normalize_release_date(str(outline_fields.get('release_date') or ''))
        if not release_date:
            release_date = outline_release_date
        if not genres:
            genres = list(outline_fields.get('genres') or [])
        if not voice_by:
            voice_by = list(outline_fields.get('voice_by') or [])
        if not category_name:
            category_name = str(outline_fields.get('work_category') or '').strip()
        if category_name and all(item.get('name') != category_name for item in genres):
            genres.insert(0, {'name': category_name})

        if not maker_name:
            maker_match = re.search(
                r'/maker_id/([A-Z]{2}\d+)\.html[^>]*>\s*<[^>]+>\s*([^<]+?)\s*</',
                page_html,
                re.IGNORECASE | re.DOTALL,
            )
            if maker_match:
                maker_id = maker_id or maker_match.group(1).upper()
                maker_name = self._decode_html_value(maker_match.group(2))

        if not title:
            title_match = re.search(r'<h1[^>]*>\s*(.*?)\s*</h1>', page_html, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = self._decode_html_value(re.sub(r'<[^>]+>', '', title_match.group(1)))

        resolved_codes = self._extract_product_codes_from_url(final_url or page_url)
        resolved_workno = self._normalize_workno(
            resolved_codes.get('product_workno')
            or self._extract_json_string(page_html, 'workno')
            or requested_workno
        )

        if not any([title, maker_name, image_url, release_date, genres, voice_by]):
            return None

        return {
            'workno': resolved_workno or requested_workno,
            'work_name': title,
            'maker_id': maker_id,
            'maker_name': maker_name,
            'regist_date': release_date,
            'series_name': series_name,
            'series_id': series_id,
            'image_main': {'url': image_url} if image_url else {},
            'work_category': category_name,
            'category_name': category_name,
            'genres': genres,
            'creaters': {'voice_by': voice_by} if voice_by else {},
            'translation_info': {
                'is_original': False,
                'lang': '',
                'source': 'page_metadata_unverified',
            },
        }

    async def _fetch_page_html_with_url(self, page_url: str) -> tuple[str, str]:
        """统一按 URL 缓存抓取 HTML，返回 (response_text, final_url)。

        ★ 关键去重层：``_resolve_translation_page_fallback`` 和 ``_fetch_product_page_metadata``
        以前各自抓 ``/maniax/work/=/product_id/RJxxx.html``、各自缓存
        （cache_key 一个叫 page_fallback、另一个叫 page_metadata），同一个 RJ
        被同步流程串起来时**同一个 URL 会被抓两次**。日志现场：33 个候选作品就有
        698 次 HTML 抓取、其中 580 次 fallback miss——大部分是这条双抓 BUG 撞出来的。
        这里把 HTML 字节按 URL 集中缓存，下游解析器各取所需，互不重复打网络。
        """
        if not page_url:
            return '', ''

        cache_key = f"page_html_raw:{page_url}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return (
                    str(cached_data.get('data') or ''),
                    str(cached_data.get('final_url') or page_url),
                )

        try:
            response = await self._guarded_get(page_url, headers=self._get_browser_headers())
            text = str(response.text or '')
            final_url = str(response.url or page_url)
            self.cache[cache_key] = {
                'data': text,
                'final_url': final_url,
                'timestamp': datetime.now(),
            }
            return text, final_url
        except Exception as exc:
            logger.warning("[DLsite] 页面 HTML 抓取失败: url=%s error=%s", page_url, exc)
            # 失败也缓存空串，避免短时间内重复打同一个失败 URL
            self.cache[cache_key] = {
                'data': '',
                'final_url': page_url,
                'timestamp': datetime.now(),
            }
            return '', page_url

    async def _fetch_product_page_metadata(self, rjcode: str, locale: Optional[str] = None) -> Optional[Dict]:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return None

        page_urls = [
            self._build_product_page_url(workno, locale=locale),
            self._build_announce_product_page_url(workno, locale=locale),
        ]

        # ★ 性能优化：``work`` 与 ``announce`` 两个 URL 并发抓取（不再串行）。
        # 现场观察：社团补全任务里 242 个候选 RJ 大部分是翻译版/预告作品，对应
        # ``/maniax/work/=/product_id/...`` 几乎都是 404、``/maniax/announce/=/product_id/...``
        # 才命中。原串行实现先打 work 等到 404、再打 announce、总耗时 = sum(404 + 200)，
        # 一条 fallback 0.5–1s。改并发后总耗时 = max(work, announce)，正常 200 OK
        # 时大约腰斩；正式作品 API 已 200 不会进 fallback，不受影响。
        cached_hit: Optional[Dict] = None
        pending_urls: List[str] = []
        for page_url in page_urls:
            cache_key = f"page_metadata:{page_url}"
            if cache_key in self.cache:
                cached_data = self.cache[cache_key]
                if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                    cached_product = cached_data['data']
                    if cached_product:
                        # cache 命中且非空：可以直接 short-circuit，不用再发任何请求
                        cached_hit = cached_product
                        break
                    # cache 是空 None（之前抓过但没解析到字段）：跳过这个 url
                    continue
            pending_urls.append(page_url)

        if cached_hit is not None:
            return cached_hit

        if not pending_urls:
            return None

        # ★ 共享 HTML 层 ``_fetch_page_html_with_url`` 自身有 inflight 去重，
        # 这里 ``asyncio.gather`` 让两个不同 URL 同时跑；另一处任务在并发抓同 URL
        # 时也会在 inflight 层共享字节，零浪费。
        async def fetch_one(url: str) -> tuple[str, Optional[Dict]]:
            logger.info("[DLsite] 尝试页面元数据抓取: %s", url)
            page_text, final_url = await self._fetch_page_html_with_url(url)
            product = self._parse_product_from_html(workno, url, final_url, page_text) if page_text else None
            return url, product

        results = await asyncio.gather(*[fetch_one(url) for url in pending_urls])

        # 全部并发结果都写 cache，无论成功失败——避免下次再发请求
        for url, product in results:
            cache_key = f"page_metadata:{url}"
            self.cache[cache_key] = {
                'data': product,
                'timestamp': datetime.now()
            }

        # 取第一个有效 product 返回（保持原顺序优先级：work 优先于 announce）
        for url, product in results:
            if product:
                logger.info(
                    "[DLsite] 页面元数据抓取成功: requested=%s resolved=%s title=%s",
                    workno,
                    self._normalize_workno(product.get('workno') or workno),
                    product.get('work_name') or '',
                )
                return product

        for url, _ in results:
            logger.info("[DLsite] 页面元数据未提取到有效字段: requested=%s url=%s", workno, url)
        return None

    async def _fetch_product_page_html(self, rjcode: str, locale: Optional[str] = None) -> str:
        """兼容旧外部签名：只返回 HTML 文本。新代码请直接调 ``_fetch_page_html_with_url``。"""
        workno = self._normalize_workno(rjcode)
        if not workno:
            return ''
        text, _ = await self._fetch_page_html_with_url(self._build_product_page_url(workno, locale=locale))
        return text

    async def _fetch_product_payload(self, rjcode: str, locale: Optional[str] = None) -> Optional[Dict]:
        data = await self._fetch_api(self._build_product_api_url(rjcode, locale=locale))
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
        return None

    async def _fetch_product_info_ajax_payload(self, rjcode: str, locale: Optional[str] = None) -> Optional[Dict]:
        workno = self._normalize_workno(rjcode)
        data = await self._fetch_api(self._build_product_info_ajax_url(workno, locale=locale))
        if not isinstance(data, dict):
            return None
        product = data.get(workno)
        if isinstance(product, dict):
            return product
        for key, value in data.items():
            if self._normalize_workno(key) == workno and isinstance(value, dict):
                return value
        return None

    async def _fetch_product_info_ajax_payloads(
        self,
        rjcodes: List[str],
        locale: Optional[str] = None,
    ) -> Optional[Dict[str, Dict]]:
        worknos: List[str] = []
        for value in rjcodes or []:
            workno = self._normalize_workno(value)
            if workno and workno not in worknos:
                worknos.append(workno)
        if not worknos:
            return {}

        data = await self._fetch_api(self._build_product_info_ajax_bulk_url(worknos, locale=locale))
        if not isinstance(data, dict):
            return None

        payloads: Dict[str, Dict] = {}
        for key, value in data.items():
            workno = self._normalize_workno(key)
            if workno in worknos and isinstance(value, dict):
                payloads[workno] = value
        return payloads

    def _wishlist_count_is_zero(self, value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return value == 0
        if isinstance(value, float):
            return value == 0
        return False

    def _product_info_indicates_bonus_work(self, product: Optional[Dict]) -> bool:
        if not isinstance(product, dict):
            return False
        return (
            not bool(product.get("is_sale"))
            and bool(product.get("is_free"))
            and bool(product.get("is_oly"))
            and self._wishlist_count_is_zero(product.get("wishlist_count"))
        )

    def _product_info_indicates_has_bonus(self, product: Optional[Dict]) -> bool:
        bonuses = product.get("bonuses") if isinstance(product, dict) else None
        return isinstance(bonuses, list) and len(bonuses) > 0

    async def get_product_bonus_info(self, rjcode: str, locale: Optional[str] = None) -> Dict[str, bool]:
        """复刻 VoiceLinks 的特典判定：只信 DLsite product/info/ajax 的结构化字段。

        ★ 关键：``_fetch_product_info_ajax_payload`` 内部 ``_fetch_api`` 在 404 / 超时 /
        ConnectError / JSON 解析失败等所有 HTTP 错误下都返回 ``None`` 不抛异常。如果这里
        把 ``product is None`` 也视为"已确认非特典"返回 ``{is_bonus_work: False}``,
        上游 ``_apply_dlsite_bonus_info`` 会顺利打上 ``bonus_info_checked_at=NOW()``,
        从此 ``lazy_refresh_bonus_for_cached_rjcodes`` 永远跳过这条（它只补刷
        ``bonus_info_checked_at IS NULL`` 的存量），漏判的特典作品再也救不回来。
        所以 product 为 None 必须 raise，让 ``_apply_dlsite_bonus_info`` 走 except
        分支保留 ``bonus_info_checked_at=None``，下次浏览仍有机会重试。
        """
        product = await self._fetch_product_info_ajax_payload(rjcode, locale=locale)
        if not isinstance(product, dict):
            raise RuntimeError(
                f"DLsite product/info/ajax 未返回 {rjcode} 的有效 payload (HTTP 失败 / 接口空响应)"
            )
        return {
            "is_bonus_work": self._product_info_indicates_bonus_work(product),
            "has_bonus": self._product_info_indicates_has_bonus(product),
        }

    async def _resolve_translation_page_fallback(self, rjcode: str, locale: Optional[str] = None) -> Dict[str, str]:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return {}

        page_url = self._build_product_page_url(workno, locale=locale)
        cache_key = f"page_fallback:{page_url}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return dict(cached_data['data'] or {})

        logger.info("[DLsite] 尝试页面 fallback: %s", page_url)
        # ★ 走共享 HTML 层：同一个 page_url 已经被 _fetch_product_page_metadata 或别处
        # 拉过时直接复用字节，不再重复打网络。
        page_text, final_url = await self._fetch_page_html_with_url(page_url)
        if not page_text:
            # 抓取失败，照样落 cache 防止短时间重试；返回空 dict
            self.cache[cache_key] = {
                'data': {},
                'timestamp': datetime.now(),
            }
            return {}

        final_codes = self._extract_product_codes_from_url(final_url)
        if final_codes.get('translation_workno') == workno and final_codes.get('product_workno'):
            result = final_codes
        else:
            result = self._extract_translation_linkage_from_html(page_text, workno)

        self.cache[cache_key] = {
            'data': result,
            'timestamp': datetime.now()
        }
        if result:
            logger.info(
                "[DLsite] 页面 fallback 命中: requested=%s product=%s translation=%s",
                workno,
                result.get('product_workno') or '',
                result.get('translation_workno') or '',
            )
        else:
            logger.info("[DLsite] 页面 fallback 未命中: requested=%s", workno)
        return result

    async def _is_public_work_available(self, rjcode: str, locale: Optional[str] = None) -> bool:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return False

        cache_key = f"public_work_available:{workno}:{locale or ''}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return bool(cached_data.get('data'))

        # ★ 优化（B）：先打 product.json API（带 24h cache + inflight 去重）。
        # API 200 即视为公开可见，跳过后续 HTML fallback——这条路径覆盖了绝大多数
        # 非 R18 翻译版 / 原作的情况，把 HTML 抓取开销从 O(N) 降到 O(N - api_hits)。
        # 注意 ``_fetch_product_payload`` 内部已有自己的 cache，重复调用近乎零成本。
        api_payload = await self._fetch_product_payload(workno, locale=locale)
        if api_payload and self._normalize_workno(api_payload.get('workno') or workno):
            self.cache[cache_key] = {
                'data': True,
                'timestamp': datetime.now(),
            }
            return True

        # API 没命中（典型场景：R18 翻译版匿名 API 返 404，需要登录 / 年龄校验）
        # 再走 HTML fallback 链。两条 HTML 路径现在都走 ``_fetch_page_html_with_url``
        # 共享缓存，同一个 URL 只会真正打一次网络。
        fallback = await self._resolve_translation_page_fallback(workno, locale=locale)
        available = bool(
            self._normalize_workno((fallback or {}).get('translation_workno') or '') == workno
            and self._normalize_workno((fallback or {}).get('product_workno') or '')
        )
        if not available:
            page_product = await self._fetch_product_page_metadata(workno, locale=locale)
            available = bool(page_product and self._normalize_workno(page_product.get('workno') or workno))

        self.cache[cache_key] = {
            'data': available,
            'timestamp': datetime.now(),
        }
        return available

    async def get_product_info(self, rjcode: str, locale: Optional[str] = None) -> Optional[Dict]:
        requested_workno = self._normalize_workno(rjcode)
        if not requested_workno:
            return None

        # ★ 性能优化：``get_product_info`` 函数级 cache（含失败结果 cache）。
        # API ``_fetch_product_payload`` 内部已经 cache 成功结果（``self.cache``），
        # 但**失败（返 None）的 RJ 会重复触发下面两层 HTML fallback**：
        # ``_resolve_translation_page_fallback`` + ``_fetch_product_page_metadata``。
        # 一次 33 候选作品的任务里光 HTML 页面 fallback 就被打了 993 次。
        # ``get_linked_works`` 对 R18 翻译版的 probe loop 是元凶——每个翻译版调
        # ``get_product_info``、每次都跑完整 fallback 链。
        # 加函数级 cache 后，同一 RJ 同一任务内的 fallback 链只跑一次；失败也 cache
        # 一份（沿用 self.cache 的 24h TTL，远超单任务时长）。
        cache_key = f"product_info:{requested_workno}:{locale or ''}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                cached_payload = cached_data.get('data')
                # cached_payload 可能是 None（失败 cache）或正常 dict——都直接返回
                return cached_payload if cached_payload is not None else None

        product = await self._fetch_product_payload(requested_workno, locale=locale)
        if product:
            payload = {
                'product': product,
                'requested_workno': requested_workno,
                'resolved_workno': self._normalize_workno(product.get('workno') or requested_workno),
                'fallback_used': False,
                'fallback_source': 'api',
                'parent_workno': '',
                'edition_info': None,
            }
            self.cache[cache_key] = {'data': payload, 'timestamp': datetime.now()}
            return payload

        fallback = await self._resolve_translation_page_fallback(requested_workno, locale=locale) or {}
        parent_workno = self._normalize_workno(fallback.get('product_workno') or '')
        translation_workno = self._normalize_workno(fallback.get('translation_workno') or '')
        if parent_workno and translation_workno == requested_workno:
            parent_product = await self._fetch_product_payload(parent_workno, locale=locale)
            if parent_product:
                language_editions = parent_product.get('language_editions', [])
                if isinstance(language_editions, dict):
                    language_editions = list(language_editions.values())
                edition_info = next(
                    (edition for edition in language_editions if self._normalize_workno(edition.get('workno') or '') == requested_workno),
                    None,
                )

                effective_product = dict(parent_product)
                translation_info = dict(parent_product.get('translation_info') or {})
                effective_product['translation_info'] = {
                    **translation_info,
                    'is_original': False,
                    'is_parent': False,
                    'is_child': True,
                    'parent_workno': parent_workno,
                    'original_workno': translation_info.get('original_workno') or parent_workno,
                    'lang': (edition_info or {}).get('lang') or translation_info.get('lang', 'JPN'),
                }
                effective_product['workno'] = requested_workno
                if edition_info and edition_info.get('work_name'):
                    effective_product['work_name'] = edition_info.get('work_name')

                logger.info(
                    "[DLsite] 使用页面 fallback 补全翻译作品信息: requested=%s parent=%s locale=%s edition_found=%s",
                    requested_workno,
                    parent_workno,
                    locale or '',
                    bool(edition_info),
                )
                payload = {
                    'product': effective_product,
                    'requested_workno': requested_workno,
                    'resolved_workno': parent_workno,
                    'fallback_used': True,
                    'fallback_source': 'translation_page',
                    'parent_workno': parent_workno,
                    'edition_info': edition_info,
                }
                self.cache[cache_key] = {'data': payload, 'timestamp': datetime.now()}
                return payload

            logger.warning(
                "[DLsite] 页面 fallback 找到父作品，但父作品 API 返回空数据: requested=%s parent=%s",
                requested_workno,
                parent_workno,
            )

        page_product = await self._fetch_product_page_metadata(requested_workno, locale=locale)
        if page_product:
            payload = {
                'product': page_product,
                'requested_workno': requested_workno,
                'resolved_workno': self._normalize_workno(page_product.get('workno') or requested_workno),
                'fallback_used': True,
                'fallback_source': 'page_metadata',
                'parent_workno': parent_workno,
                'edition_info': None,
            }
            self.cache[cache_key] = {'data': payload, 'timestamp': datetime.now()}
            return payload

        # ★ 同样 cache 失败结果（None），防止同一任务内重复跑两层 HTML fallback 链。
        self.cache[cache_key] = {'data': None, 'timestamp': datetime.now()}
        return None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        from ..config.settings import get_config

        config = get_config()
        proxy_url = None
        if config.metadata.http_proxy:
            proxy_url = self._normalize_proxy_url(config.metadata.http_proxy)

        normalized_proxy_url = proxy_url or ""
        if (
            self.client is not None
            and not self.client.is_closed
            and self._client_proxy_url != normalized_proxy_url
        ):
            logger.info(
                "[DLsite] 元数据代理已变更，重建 HTTP 客户端: %s",
                normalized_proxy_url or "直连",
            )
            await self._close_client()

        if self.client is None or self.client.is_closed:
            if proxy_url:
                logger.debug("[DLsite] 使用代理: %s", proxy_url)

            client_kwargs = {
                'headers': self._get_api_headers(),
                'timeout': httpx.Timeout(connect=20.0, read=45.0, write=10.0, pool=None),
                'verify': False,
                'follow_redirects': True,
                'limits': httpx.Limits(max_connections=10, max_keepalive_connections=5),
                'http2': False,
            }
            if proxy_url:
                async_client_params = inspect.signature(httpx.AsyncClient.__init__).parameters
                if 'proxy' in async_client_params:
                    client_kwargs['proxy'] = proxy_url
                elif 'proxies' in async_client_params:
                    client_kwargs['proxies'] = {
                        'http://': proxy_url,
                        'https://': proxy_url,
                    }

            self.client = httpx.AsyncClient(**client_kwargs)
            self._client_proxy_url = normalized_proxy_url
        return self.client

    async def _close_client(self):
        if self.client and not self.client.is_closed:
            await self.client.aclose()
        self.client = None
        self._client_proxy_url = ""

    async def _reset_client_after_transport_error(self, exc: BaseException) -> None:
        if not self.client or self.client.is_closed:
            return
        logger.info("[DLsite] HTTP 客户端连接池异常，重建后重试: %s", self._format_exc(exc))
        try:
            await self._close_client()
        except Exception as close_exc:
            logger.debug("[DLsite] 关闭异常 HTTP 客户端失败: %s", self._format_exc(close_exc))
            self.client = None
            self._client_proxy_url = ""

    async def _one_shot_get(self, url: str, *, proxy_url: Optional[str] = None, **kwargs) -> httpx.Response:
        from ..config.settings import get_config

        client_kwargs = {
            'headers': self._get_api_headers(),
            'timeout': httpx.Timeout(connect=25.0, read=60.0, write=10.0, pool=None),
            'verify': False,
            'follow_redirects': True,
            'limits': httpx.Limits(max_connections=1, max_keepalive_connections=0),
            'http2': False,
        }
        if proxy_url is None:
            config = get_config()
            proxy_url = self._normalize_proxy_url(config.metadata.http_proxy)
        else:
            proxy_url = self._normalize_proxy_url(proxy_url)
        if proxy_url:
            async_client_params = inspect.signature(httpx.AsyncClient.__init__).parameters
            if 'proxy' in async_client_params:
                client_kwargs['proxy'] = proxy_url
            elif 'proxies' in async_client_params:
                client_kwargs['proxies'] = {
                    'http://': proxy_url,
                    'https://': proxy_url,
                }
        async with httpx.AsyncClient(**client_kwargs) as client:
            return await client.get(url, **kwargs)

    async def test_connectivity(self, http_proxy: Optional[str] = None) -> Dict[str, Any]:
        """测试当前 DLsite 元数据链路，绕过业务缓存直接请求 product API。"""
        from ..config.settings import get_config

        workno = "RJ01609989"
        url = self._build_product_api_url(workno)
        started_at = time.perf_counter()
        config = get_config()
        proxy_url = self._normalize_proxy_url(
            config.metadata.http_proxy if http_proxy is None else http_proxy
        )
        check: Dict[str, Any] = {
            "name": "DLsite product API",
            "url": url,
            "workno": workno,
            "ok": False,
            "status": "error",
            "http_status": None,
            "latency_ms": 0,
            "message": "",
        }

        try:
            if http_proxy is None:
                response = await self._guarded_get(url, headers=self._get_api_headers())
            else:
                response = await self._one_shot_get(url, proxy_url=proxy_url, headers=self._get_api_headers())
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            check["http_status"] = response.status_code
            check["latency_ms"] = latency_ms
            if response.status_code != 200:
                check["message"] = f"HTTP {response.status_code}"
                return {
                    "success": False,
                    "summary": {"total": 1, "ok": 0, "failed": 1},
                    "checks": [check],
                    "proxy_enabled": bool(proxy_url),
                    "proxy_url": self._mask_proxy_url(proxy_url),
                    "tested_at": datetime.now().isoformat(),
                }

            data = response.json()
            product = None
            if isinstance(data, list):
                product = data[0] if data and isinstance(data[0], dict) else None
            elif isinstance(data, dict):
                product = data.get(workno)
                if not isinstance(product, dict):
                    product_workno = self._normalize_workno(data.get("workno") or data.get("product_id"))
                    product = data if product_workno == workno else None
                if not isinstance(product, dict):
                    product = next(
                        (
                            value
                            for key, value in data.items()
                            if self._normalize_workno(key) == workno and isinstance(value, dict)
                        ),
                        None,
                    )
            if product:
                title = str(product.get("work_name") or product.get("name") or "").strip()
                check.update({
                    "ok": True,
                    "status": "ok",
                    "title": title,
                    "message": f"DLsite 可连接，测试作品 {workno} 返回正常",
                })
            else:
                check["message"] = f"DLsite HTTP 可达，但未返回测试作品 {workno}"
            return {
                "success": bool(check["ok"]),
                "summary": {"total": 1, "ok": 1 if check["ok"] else 0, "failed": 0 if check["ok"] else 1},
                "checks": [check],
                "proxy_enabled": bool(proxy_url),
                "proxy_url": self._mask_proxy_url(proxy_url),
                "tested_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            detail = self._format_exc(exc)
            if isinstance(exc, httpx.ConnectError):
                if proxy_url:
                    message = f"代理连接失败，请确认 {self._mask_proxy_url(proxy_url)} 在当前运行环境内可访问（{detail}）"
                else:
                    message = f"DLsite 连接失败，请确认当前网络可访问 DLsite（{detail}）"
            elif isinstance(exc, httpx.TimeoutException):
                message = f"DLsite 连接超时（{detail}）"
            elif isinstance(exc, (httpx.NetworkError, httpx.ProtocolError)):
                message = f"DLsite 网络请求失败（{detail}）"
            else:
                message = detail
            check.update({
                "latency_ms": latency_ms,
                "message": message,
            })
            return {
                "success": False,
                "summary": {"total": 1, "ok": 0, "failed": 1},
                "checks": [check],
                "proxy_enabled": bool(proxy_url),
                "proxy_url": self._mask_proxy_url(proxy_url),
                "tested_at": datetime.now().isoformat(),
            }

    async def _guarded_get(self, url: str, *, retry: bool = True, **kwargs) -> httpx.Response:
        """带并发限制的 HTTP GET，超时时指数退避重试（最多 3 次）。

        并发上限设为 6，是社团补全 wave1 的核心瓶颈调优：旧值 3 + sleep 0.5s
        在 588 RJ 全量索引下让 wave1 慢到 13 分钟（``wave1_sem=20`` 形同虚设，
        外层 20 并发协程实际全在 dlsite sem=3 排队）。桌面端单 IP 流量稳定，
        DLsite 公开 API 对 6 并发 + 0.1-0.3s 抖动的容忍度足够（实测后续如出现
        ``aiohttp.ClientResponseError 429`` 再回滚）。
        每次进入 semaphore 后加随机抖动延迟，分散请求时序，降低被限流概率。
        """
        if _dlsite_http_circuit_is_open():
            remaining = _dlsite_http_circuit_remaining_seconds()
            raise httpx.ConnectError(f"DLsite HTTP 短熔断中，剩余 {remaining:.1f}s")

        if self._http_semaphore is None:
            # 默认 3 个并发 DLsite 请求 + 0.1-0.3s 抖动：用 ``DLSITE_HTTP_CONCURRENCY``
            # / ``DLSITE_HTTP_SLEEP_MIN`` / ``DLSITE_HTTP_SLEEP_MAX`` 环境变量可在
            # 网络波动时临时压回 1 / 0.2 / 0.8。
            sem_size = max(1, int(os.environ.get("DLSITE_HTTP_CONCURRENCY", "3") or "3"))
            self._http_semaphore = asyncio.Semaphore(sem_size)
        sleep_min = float(os.environ.get("DLSITE_HTTP_SLEEP_MIN", "0.1") or "0.1")
        sleep_max = float(os.environ.get("DLSITE_HTTP_SLEEP_MAX", "0.3") or "0.3")
        max_attempts = 3 if retry else 1
        for attempt in range(max_attempts):
            try:
                async with self._http_semaphore:
                    await asyncio.sleep(random.uniform(sleep_min, sleep_max))
                    client = await self._get_client()
                    response = await client.get(url, **kwargs)
                    _record_dlsite_http_success()
                    return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
                wait = 2.0 * (2 ** attempt)  # 2s → 4s → 8s
                _record_dlsite_http_failure(exc)
                await self._reset_client_after_transport_error(exc)
                if attempt < max_attempts - 1:
                    logger.warning(
                        "[DLsite] 请求失败，等待 %.0fs 后重试（第 %d 次）: %s error=%s",
                        wait, attempt + 1, url, self._format_exc(exc),
                    )
                    await asyncio.sleep(wait)
                    continue
                if not retry:
                    logger.warning("[DLsite] 请求失败，快速返回: %s error=%s", url, self._format_exc(exc))
                    raise
                logger.warning("[DLsite] 复用客户端重试失败，改用一次性客户端: %s error=%s", url, self._format_exc(exc))
                try:
                    response = await self._one_shot_get(url, **kwargs)
                    _record_dlsite_http_success()
                    return response
                except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as one_shot_exc:
                    _record_dlsite_http_failure(one_shot_exc)
                    raise
        raise RuntimeError("unreachable")

    async def _fetch_api(self, url: str) -> Optional[Dict]:
        """从 DLsite API 获取数据，带内存缓存和并发去重（同一 URL 只发一次 HTTP 请求）"""
        cache_key = url

        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug("[DLsite] 使用缓存数据: %s", url)
                return cached_data['data']

        # 进行中的请求复用：若已有相同 URL 的请求在飞，直接等待其结果，不再新发
        if cache_key in self._inflight:
            logger.debug("[DLsite] 复用进行中的请求: %s", url)
            try:
                return await asyncio.shield(self._inflight[cache_key])
            except Exception:
                return None

        task = asyncio.ensure_future(self._do_fetch_api(url))
        self._inflight[cache_key] = task
        try:
            return await task
        finally:
            self._inflight.pop(cache_key, None)

    async def _do_fetch_api(self, url: str) -> Optional[Dict]:
        """实际 HTTP 请求逻辑，由 _fetch_api 唯一调用"""
        log_url = self._format_api_url_for_log(url)
        logger.info("[DLsite] 正在请求 API: %s", log_url)

        try:
            logger.debug("[DLsite] 使用客户端配置: verify=False, timeout=45s, http2=False")
            response = await self._guarded_get(url, headers=self._get_api_headers())

            logger.info("[DLsite] 响应状态码：%s", response.status_code)

            if response.status_code == 200:
                data = response.json()
                self.cache[url] = {
                    'data': data,
                    'timestamp': datetime.now()
                }
                return data
            if response.status_code == 404:
                logger.warning("API 返回 404: %s", log_url)
                return None

            logger.error("API 请求失败: %s, 状态码: %s", log_url, response.status_code)
            return None
        except httpx.ConnectError as e:
            logger.error("API 连接失败: %s", log_url)
            logger.error("错误详情: %s", self._format_exc(e))
            logger.error("可能原因: 1) 网络连接异常 2) DLsite 不可达 3) 代理或防火墙拦截")
            return None
        except httpx.ReadTimeout as e:
            logger.error("API 读取超时: %s (超过 45 秒)", log_url)
            logger.error("错误详情: %s", self._format_exc(e))
            return None
        except Exception as e:
            logger.error("API 请求异常: %s", log_url)
            logger.error("错误类型: %s", type(e).__name__)
            logger.error("错误详情: %s", self._format_exc(e))
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    async def get_translation_info(self, rjcode: str) -> TranslationInfo:
        """
        获取作品的翻译信息
        
        返回:
            TranslationInfo: 包含 is_original, is_parent, is_child 等信息
        """
        workno = self._normalize_workno(rjcode)
        if not workno:
            return TranslationInfo(is_original=True)

        # 专项缓存命中（translation_info 独立缓存，避免每次走完整 get_product_info）
        if workno in self._translation_info_cache:
            cached_result, cached_ts = self._translation_info_cache[workno]
            if datetime.now() - cached_ts < self.cache_ttl:
                logger.debug("[DLsite] translation_info 缓存命中: %s", workno)
                return cached_result

        product_info = await self.get_product_info(workno)
        if product_info and product_info.get('product'):
            product = dict(product_info.get('product') or {})
            translation_info = dict(product.get('translation_info', {}) or {})
            result = TranslationInfo(
                is_original=translation_info.get('is_original', False),
                is_parent=translation_info.get('is_parent', False),
                is_child=translation_info.get('is_child', False),
                parent_workno=translation_info.get('parent_workno'),
                original_workno=translation_info.get('original_workno'),
                child_worknos=[
                    self._normalize_workno(w)
                    for w in list(translation_info.get('child_worknos') or [])
                    if self._normalize_workno(w)
                ],
                lang=translation_info.get('lang', 'JPN')
            )
            has_explicit_linkage = any([
                result.is_original,
                result.is_parent,
                result.is_child,
                self._normalize_workno(result.parent_workno),
                self._normalize_workno(result.original_workno),
                result.child_worknos,
            ])
            fallback_parent = self._normalize_workno(product_info.get('parent_workno'))
            fallback_source = str(product_info.get('fallback_source') or '').strip()
            title = str(product.get('work_name') or product.get('title') or '')
            title_folded = title.casefold()
            if any(marker in title_folded for marker in ('简体', '簡体', '簡體', '简中', '簡中')):
                fallback_lang = 'CHI_HANS'
            elif any(marker in title_folded for marker in ('繁体', '繁體', '繁中')):
                fallback_lang = 'CHI_HANT'
            elif any(marker in title_folded for marker in ('english', '英文', '英語', '英语')):
                fallback_lang = 'ENG'
            else:
                fallback_lang = ''
            looks_like_translation_title = bool(fallback_lang) or any(
                marker in title_folded
                for marker in ('みんなで翻訳', 'みんなで翻译', 'everyone translation')
            )
            if (
                not has_explicit_linkage
                and fallback_parent
                and fallback_parent != workno
                and fallback_source in {'translation_page', 'page_metadata'}
            ):
                result = TranslationInfo(
                    is_child=True,
                    parent_workno=fallback_parent,
                    original_workno=fallback_parent,
                    lang=fallback_lang,
                )
                logger.info(
                    '[DLsite] 使用页面 fallback 补全翻译父作品: requested=%s parent=%s lang=%s source=%s',
                    workno,
                    fallback_parent,
                    fallback_lang or 'UNKNOWN',
                    fallback_source,
                )
            if not any([
                result.is_original,
                result.is_parent,
                result.is_child,
                self._normalize_workno(result.parent_workno),
                self._normalize_workno(result.original_workno),
                result.child_worknos,
            ]) and looks_like_translation_title:
                return TranslationInfo(lang="")
            # 只缓存"成功拿到 product 的"明确结果。
            self._translation_info_cache[workno] = (result, datetime.now())
            return result

        # ★ 修复 BUG #1（韩英版被误认为原作）：
        # 当 DLsite 公开 API 对一个 RJ 拿不到 product（典型场景：已下架 / R18 翻译版需要登录 /
        # 网络错误），**绝对不能默认 is_original=True**。
        # 原先这里默认 is_original=True 导致 ``get_linked_works`` 走 original 分支，
        # 把这个未知 RJ 错认成"日语原作"，link_map 只塞自己一条。社团补全里上游
        # 候选若是一个韩语/英语翻译版，就会被独立成卡（canonical 为它自己），还会因为
        # Kikoeru DB 里 work_name 被脏写成简中标题，最终展示"简中标题 + 韩语 RJ"。
        # 改后：API 失败时返回保守的"全空"信号——is_original=False、lang 显式置空，
        # ``LinkedWork`` 那边的 else 兜底分支会把 work_type 标成 ``unknown``，
        # ``_variant_group`` 会归类为 ``other``，从而被 prepare_candidate 闸门拦掉。
        # 失败结果不写缓存，下次访问可重试（避免 API 临时挂了导致永久误判）。
        # 注意：``TranslationInfo`` dataclass 的 ``lang`` 字段默认值是 "JPN"（向后兼容
        # 历史调用方），这里必须显式传 ``lang=""`` 覆盖，否则下游会误认为是日语原作。
        return TranslationInfo(lang="")
    
    async def get_linked_works(self, rjcode: str, *, refresh: bool = False) -> Dict[str, LinkedWork]:
        """获取作品的关联作品（含 cache + inflight 去重，是性能热点入口）。

        ★ 性能优化（key BUG fix）：
        - 之前 ``get_linked_works`` 完全没 cache，每次调用都重新走 trans + product_info
          + 对所有翻译版子探测，O(N) 个递归 API 调用。
        - 一次 33 候选作品的任务里这条接口被打了 2819 次（每个 candidate 在
          ``prepare_candidate`` / ``resolve_canonical_rj`` / Kikoeru
          ``check_duplicate_with_linkages`` 三处各调一次），是 product.json 累计
          2816 次的主要源头。
        - 改后：同一任务内同一个 RJ 只算一次完整递归，后续调用走 ``self.cache`` 短路。
          ``self._linked_works_inflight`` 防止两个并发协程在 cache miss 瞬间同时
          触发完整计算。
        - 递归调用 ``self.get_linked_works(original_rjcode)`` 也会自动复用 cache。

        ``refresh=True`` 强制清掉 ``linked_works:`` cache 项再重算，专门服务于
        ``resolve_canonical_rj(refresh=True)`` 这条 "用户主动强刷" 路径：v1.5.x
        早期版本里 ``_get_direct_linked_works`` 的 is_parent/is_child 分支存在
        "parent_workno 覆盖 original_workno" 的 BUG，导致 24h cache 里写入的
        关联链没有任何 ``original`` 标记。光修代码不清 cache 的话，旧 cache 在
        TTL 内（24h）会持续把错误结果喂给下游，用户感受不到修复。

        关联作品包括：
        - 原版作品（日文）
        - 所有翻译版本（简中、繁中、英文等不同译者，RJ 号各不相同）
        - 子翻译版本（嵌套翻译）

        返回:
            Dict[str, LinkedWork]: RJ 号到作品信息的映射
        """
        normalized_rjcode = self._normalize_workno(rjcode)
        if not normalized_rjcode:
            return {}

        cache_key = f"linked_works:{normalized_rjcode}"
        if refresh:
            # 主动强刷：把 self.cache 里的关联链以及 translation_info 旁路 cache
            # 一并清掉，避免下面 _compute_linked_works 跑出来还是旧 BUG 时段的
            # 错误标记。translation_info 只在内存，清掉后续 get_translation_info
            # 自动重新打 product.json。
            self.cache.pop(cache_key, None)
            self._translation_info_cache.pop(normalized_rjcode, None)

        # 1. cache 短路（同一任务内重复调用近乎免费）
        if not refresh and cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                # 浅拷贝避免上游误改 cache 内 LinkedWork 引用
                return dict(cached_data['data'] or {})

        # 2. inflight 去重：多个协程同时 cache miss 时只算一次
        existing = self._linked_works_inflight.get(normalized_rjcode)
        if existing is not None and not existing.done():
            return dict(await existing)

        # 3. cache miss + 无 inflight：自己起 task 计算并写 cache
        task = asyncio.create_task(self._compute_linked_works(normalized_rjcode))
        self._linked_works_inflight[normalized_rjcode] = task
        try:
            result = await task
        finally:
            self._linked_works_inflight.pop(normalized_rjcode, None)

        self.cache[cache_key] = {
            'data': dict(result),
            'timestamp': datetime.now(),
        }
        return dict(result)

    async def _compute_linked_works(self, normalized_rjcode: str) -> Dict[str, LinkedWork]:
        """``get_linked_works`` 的内部计算路径——剥出 cache/inflight 包装层后的纯计算。

        递归到 ``self.get_linked_works(original_rjcode)`` 时会自动复用外层 cache。
        """
        def _merge_linked_works(base: Dict[str, LinkedWork], incoming: Dict[str, LinkedWork]) -> Dict[str, LinkedWork]:
            """合并关联链，避免 translation/child_translation 覆盖 original。

            DLsite 某些翻译页会把同一个 RJ 在不同入口下标成不同 link_type。
            只要已有 ``original``，后续同 RJ 的 translation 标记就不能覆盖它；
            否则 canonical 解析会丢掉原作入口，导致多语言版本拆成多张卡。
            """
            priority = {
                "original": 0,
                "translation": 1,
                "child_translation": 2,
                "linked": 3,
                "self": 4,
                "unknown": 5,
            }
            result = dict(base or {})
            for workno, work in (incoming or {}).items():
                existing = result.get(workno)
                if existing is None:
                    result[workno] = work
                    continue
                old_rank = priority.get(str(existing.work_type or "").strip(), 99)
                new_rank = priority.get(str(work.work_type or "").strip(), 99)
                if new_rank < old_rank:
                    result[workno] = work
            return result

        async def _get_direct_linked_works(target_rjcode: str) -> Dict[str, LinkedWork]:
            target_rjcode = self._normalize_workno(target_rjcode)
            trans = await self.get_translation_info(target_rjcode)
            product_info = await self.get_product_info(target_rjcode)
            product = dict((product_info or {}).get('product') or {})
            api = product
            result: Dict[str, LinkedWork] = {}

            if trans.is_original:
                result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='original', lang='JPN')
                language_editions = api.get('language_editions', [])
                if isinstance(language_editions, dict):
                    language_editions = list(language_editions.values())
                # ★ 修复用户反馈痛点（RJ01407907）：直接信 DLsite 父作品 API 返回的
                #   ``language_editions`` 列表，不要再用 ``_is_public_work_available``
                #   做"前台可见性"过滤。R18 翻译版在 DLsite 匿名公开 API 上常 404
                #   （需要登录 / 年龄校验），但 work 本身明明就在 Kikoeru 上能搜到，
                #   过滤后这些 RJ 就再也不会被送到 Kikoeru 查重，整条链路误报未命中。
                #   油猴脚本 view.txt 的 ``getLinkedWorks`` 也是无条件信 ``language_editions``。
                #   误报代价：把不存在的 RJ 多送一次给 Kikoeru，search 返回 0 即可，无副作用。
                for edition in language_editions or []:
                    workno = self._normalize_workno(edition.get('workno'))
                    if not workno:
                        continue
                    edition_lang = str(edition.get('lang') or '').strip() or ''
                    result[workno] = LinkedWork(
                        workno=workno,
                        work_type='translation',
                        lang=edition_lang,
                        title=str(edition.get('work_name') or '').strip(),
                    )
            elif trans.is_parent:
                original_workno = self._normalize_workno(trans.original_workno or '')
                # ★ 修复"同一作品所有翻译版独立成卡"BUG（用户反馈：Lilith 社团补全里
                # RJ01525048/RJ01525054、RJ01605924/RJ01605932 等翻译对各占一张卡）：
                # 当 target_rjcode 本身就是 original_workno（DLsite 偶尔把"原作 + 有翻译子节点"
                # 同时标 is_parent=True），下面 `result[target_rjcode] = translation/...`
                # 会立刻覆盖刚写入的 `original/JPN`，导致整条链路里没有任何 `original` 标记。
                # `resolve_canonical_rj` 找不到 work_type=='original'，canonical 兜底为输入 rj
                # 自己，每个翻译版都会被独立成卡。这里显式保留"target 就是原作"的语义，
                # 别再让自己的 translation 标记把 original 盖掉。
                if original_workno and original_workno != target_rjcode:
                    result[original_workno] = LinkedWork(workno=original_workno, work_type='original', lang='JPN')
                    result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='translation', lang=trans.lang or 'JPN')
                else:
                    # target 自身就是日语原作：保留 original/JPN 标记，避免被翻译/翻译子节点覆盖。
                    result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='original', lang='JPN')
                for child_workno in list(trans.child_worknos or []):
                    normalized_child = self._normalize_workno(child_workno)
                    if not normalized_child:
                        continue
                    result[normalized_child] = LinkedWork(workno=normalized_child, work_type='child_translation', lang=trans.lang or 'JPN')
            elif trans.is_child:
                original_workno = self._normalize_workno(trans.original_workno or '')
                parent_workno = self._normalize_workno(trans.parent_workno or '')
                if original_workno:
                    result[original_workno] = LinkedWork(workno=original_workno, work_type='original', lang='JPN')
                # ★ 修复"同一作品所有翻译版独立成卡"BUG（详见上方 is_parent 分支注释）：
                # 直系翻译版的常见场景是 parent_workno == original_workno（parent 就是日语原作）。
                # 之前这里无条件 `result[parent_workno] = translation/<child.lang>` 会把刚写入的
                # `original/JPN` 直接覆盖成 `translation/CHI_HANS`（或 CHI_HANT）——整条链路里
                # 没有 work_type=='original' 的入口，``resolve_canonical_rj`` 只能兜底用输入 rj
                # 当 canonical，于是同一作品的简繁中版被分别写成两个独立 CircleWork 行、各占
                # 一张卡。父翻译只有在它确实是另一个 RJ（嵌套翻译链：原作 → 父翻译 → 子翻译）
                # 时才需要单独写入。
                if parent_workno and parent_workno != original_workno:
                    result[parent_workno] = LinkedWork(workno=parent_workno, work_type='translation', lang=trans.lang or 'JPN')
                result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='child_translation', lang=trans.lang or 'JPN')
            else:
                # ★ 修复 BUG #1：trans 完全没信号（API 失败或返回空）时，**不要**无中生有
                # 声称这是 'original/JPN'。原先这里硬塞 original/JPN，让下游的 link_map
                # 把已下架的韩英翻译版误认成日语原作。改成 ``unknown / UNKNOWN``，让
                # ``_variant_group`` 归类为 ``other``，下游闸门可识别并过滤。
                result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='unknown', lang='UNKNOWN')

            return result

        try:
            # 入口已 normalize 并通过 cache/inflight 短路过；这里直接用参数即可。
            trans = await self.get_translation_info(normalized_rjcode)
            if not trans.is_original and trans.original_workno:
                original_rjcode = self._normalize_workno(trans.original_workno)
                logger.info(f"[DLsite] {normalized_rjcode} 是翻译版本，从原版 {original_rjcode} 获取完整关联链")
                # 递归调用走 ``get_linked_works`` 的外层 cache/inflight，
                # 原作 RJ 已被算过时近乎免费。
                result = await self.get_linked_works(original_rjcode)
                direct_links = await _get_direct_linked_works(normalized_rjcode)
                result = _merge_linked_works(result, direct_links)
                logger.info(f"[DLsite] {normalized_rjcode} 关联作品 ({len(result)}个): {list(result.keys())}")
                return result

            result = await _get_direct_linked_works(normalized_rjcode)
            probe_worknos = [
                workno
                for workno, work in list(result.items())
                if workno != normalized_rjcode and str(getattr(work, 'lang', '') or '').strip().upper() != 'JPN'
            ]
            # ⚠ 性能优化：原作有 N 个翻译版时，对每个翻译版 ``_get_direct_linked_works``
            # 串行打 2N 次 HTTP（trans + product_info），加上 dlsite sem=3 + 0.1-0.3s 抖动，
            # 单 RJ 内部就能堆出 5-15s 串行延迟。改为并发后由外层 ``_http_semaphore``
            # 统一限流，整体时序不变但单 RJ wall-clock 折叠到 max(单次 probe)。
            if probe_worknos:
                direct_link_results = await asyncio.gather(
                    *[_get_direct_linked_works(p) for p in probe_worknos],
                    return_exceptions=True,
                )
                for direct_links in direct_link_results:
                    if isinstance(direct_links, BaseException):
                        logger.debug("[DLsite] probe 翻译版关联链失败: %s", direct_links)
                        continue
                    result = _merge_linked_works(result, direct_links)

            logger.info(f"[DLsite] {normalized_rjcode} 关联作品 ({len(result)}个): {list(result.keys())}")
            return result
        except Exception as e:
            logger.error(f"获取关联作品失败 {normalized_rjcode}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # ★ 修复 BUG #1：异常 fallback 也不再无中生有声称 original/JPN，
            # 改成 'unknown / UNKNOWN'，避免把可能是韩英版的 RJ 错认成日语原作。
            return {normalized_rjcode: LinkedWork(workno=normalized_rjcode, work_type='unknown', lang='UNKNOWN')}
    
    async def get_full_linkage(self, rjcode: str, cue_languages: List[str] = None) -> Dict[str, LinkedWork]:
        """
        获取作品的完整关联链（包括所有语言版本）
        
        Args:
            rjcode: RJ 号
            cue_languages: 需要查询的语言列表，如 ['CHI_HANS', 'CHI_HANT', 'ENG']
        
        返回:
            Dict[str, LinkedWork]: 所有关联作品的映射
        """
        if cue_languages is None:
            cue_languages = ['CHI_HANS', 'CHI_HANT']
        
        # 首先获取翻译信息
        trans = await self.get_translation_info(rjcode)
        
        # 如果是非原作品，先从原作品开始查询
        original_rjcode = rjcode
        if not trans.is_original and trans.original_workno:
            original_rjcode = trans.original_workno
        
        # 检查缓存
        cache_key = f"{original_rjcode}_{'_'.join(sorted(cue_languages))}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug(f"使用完整关联链缓存：{original_rjcode}")
                return cached_data['data']
        
        # 获取原作品的关联信息
        result = await self.get_linked_works(original_rjcode)
        
        try:
            url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_rjcode}"
            data = await self._fetch_api(url)
            
            if data and isinstance(data, list) and len(data) > 0:
                product = data[0]
                language_editions = product.get('language_editions', [])
                if isinstance(language_editions, dict):
                    language_editions = list(language_editions.values())
                
                # 对每种语言版本递归查询
                for edition in language_editions:
                    lang = edition.get('lang', 'JPN')
                    if lang not in cue_languages:
                        continue
                    
                    workno = edition.get('workno')
                    if workno and workno not in result:
                        # 递归获取该语言版本的关联作品
                        linked = await self.get_linked_works(workno)
                        for k, v in linked.items():
                            if k not in result:
                                result[k] = v
                
                # 保存到缓存
                self.cache[cache_key] = {
                    'data': result,
                    'timestamp': datetime.now()
                }
        
        except Exception as e:
            logger.error(f"获取完整关联链失败 {rjcode}: {e}")
        
        return result

    @staticmethod
    def _looks_like_dlsite_html(text: str) -> bool:
        """判断响应文本是否像一份正常的 DLsite HTML 页面。

        用于区分两种"page_worknos 为空"：
        - 真 0 作品：HTML 文本健全（含 <title>/<html>/dlsite/maniax 等标志），只是确实没有作品；
        - 解析失败：HTML body 里没有任何 ASCII 文本特征（典型现场是 brotli/gzip 没解压
          → response.text 是压缩字节强行 latin-1 解码的乱码）。
        """
        if not text:
            return False
        head = str(text)[:8192]
        if not head:
            return False
        markers = ('<html', '<body', '<title', 'dlsite', 'maniax', '</body>', '<meta')
        lowered = head.lower()
        return any(marker in lowered for marker in markers)

    async def list_circle_work_summaries_by_maker(
        self,
        maker_id: str,
        *,
        language: str = "JPN",
        max_pages: int = 200,
    ) -> tuple[List[DLsiteWorkSummary], str]:
        """抓取 maker_id 名下所有可见作品并返回带 chip 分类的 ``DLsiteWorkSummary``。

        相比 ``list_circle_worknos_by_maker``：

        - 返回的不是裸 RJ 列表，而是每个 RJ 一个 ``DLsiteWorkSummary``，已经在列表 HTML 层
          做了 ``is_probably_audio`` 三态分类。``_collect_dlsite_circle_candidates`` 可
          以直接据此跳过 manga/CG/RPG/视频类作品的 metadata 拉取链路。
        - HTML 解析失败 / DLsite 改版 → 返回的 summary list 仍然带 ``is_probably_audio=None``，
          下游会 fallback 到旧的 metadata 链路，行为完全等价于旧实现。
        - ``parse_status`` 与 ``list_circle_worknos_by_maker`` 同义。

        缓存复用同一份 raw bytes：底层 ``_guarded_get`` + ``self.cache`` 命中后，
        两个对外 API 不会重复打 HTTP。
        """
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        if not normalized_maker_id:
            return [], "empty"

        cache_key = (
            f"circle_profile_summaries_with_announce:"
            f"{normalized_maker_id}:{normalized_language}"
        )
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                cached_payload = list(cached_data.get('data') or [])
                cached_status = str(cached_data.get('parse_status') or ("ok" if cached_payload else "empty"))
                # 重新水合成 dataclass。这里 cache 存的是 dict，避免 dataclass 升级时
                # 撞 backward incompatible。
                hydrated: List[DLsiteWorkSummary] = []
                for item in cached_payload:
                    if isinstance(item, DLsiteWorkSummary):
                        hydrated.append(item)
                        continue
                    if not isinstance(item, dict):
                        continue
                    try:
                        hydrated.append(DLsiteWorkSummary(
                            workno=str(item.get('workno') or '').strip().upper(),
                            title=str(item.get('title') or ''),
                            maker_id=str(item.get('maker_id') or ''),
                            maker_name=str(item.get('maker_name') or ''),
                            category_label=str(item.get('category_label') or ''),
                            work_type_code=str(item.get('work_type_code') or ''),
                            file_format_labels=list(item.get('file_format_labels') or []),
                            icon_classes=list(item.get('icon_classes') or []),
                            cover_url=str(item.get('cover_url') or ''),
                            is_probably_audio=item.get('is_probably_audio'),
                            classification_reason=str(item.get('classification_reason') or ''),
                            release_date=str(item.get('release_date') or ''),
                        ))
                    except Exception:
                        continue
                return hydrated, cached_status

        # 与 list_circle_worknos_by_maker 复用同一套 HTTP 抓取逻辑（profile → profile-touch → announce → filter）。
        # 这里 inline 实现是为了一次抓取既能产出 RJ-only 又能产出 summary，避免对同样 URL 打两遍 HTTP。
        summaries_by_rj: Dict[str, DLsiteWorkSummary] = {}
        seen: Set[str] = set()
        any_http_success = False
        any_html_looked_normal = False
        ordered_rjcodes: List[str] = []

        def absorb_summaries(extracted: List[DLsiteWorkSummary]) -> int:
            new_count = 0
            for summary in extracted:
                if not summary.workno or summary.workno in seen:
                    continue
                seen.add(summary.workno)
                summaries_by_rj[summary.workno] = summary
                ordered_rjcodes.append(summary.workno)
                new_count += 1
            return new_count

        def absorb_raw_worknos(raw_worknos: List[str]) -> int:
            """fallback：HTML 解析不出 summary 时，把裸 RJ 也补进结果。``is_probably_audio=None``。"""
            new_count = 0
            for workno in raw_worknos:
                if not workno or workno in seen:
                    continue
                seen.add(workno)
                summaries_by_rj[workno] = DLsiteWorkSummary(workno=workno)
                ordered_rjcodes.append(workno)
                new_count += 1
            return new_count

        for mode, url_builder in [
            ("profile", self._build_circle_profile_url),
            ("profile-touch", self._build_circle_profile_touch_url),
            ("announce", self._build_circle_announce_url),
        ]:
            if mode == "profile-touch" and summaries_by_rj:
                continue
            empty_streak = 0
            for page in range(1, max(1, int(max_pages)) + 1):
                if mode == "profile-touch":
                    url = url_builder(normalized_maker_id, page=page)
                else:
                    url = url_builder(normalized_maker_id, language=normalized_language, page=page)
                try:
                    response = await self._guarded_get(url, headers=self._get_browser_headers())
                    if response.status_code != 200:
                        logger.warning(
                            "[DLsite] 社团%s summary 抓取失败 maker_id=%s page=%s status=%s",
                            mode, normalized_maker_id, page, response.status_code,
                        )
                        break
                    any_http_success = True
                    if self._looks_like_dlsite_html(response.text):
                        any_html_looked_normal = True

                    page_summaries = self._extract_summaries_from_listing_html(response.text)
                    new_count = absorb_summaries(page_summaries)
                    if new_count == 0:
                        # summary 解析失败时降级到裸 RJ 提取，保持现存 fallback 路径。
                        page_worknos = self._extract_worknos_from_listing_html(response.text)
                        if not page_worknos and mode == "profile-touch":
                            page_worknos = self._extract_any_worknos_from_listing_html(response.text)
                        if not page_worknos and mode == "profile-touch":
                            page_worknos = self._extract_not_product_ids_from_html(response.text)
                        new_count = absorb_raw_worknos(page_worknos)
                except Exception as exc:
                    logger.warning(
                        "[DLsite] 社团%s summary 抓取异常 maker_id=%s page=%s error=%s",
                        mode, normalized_maker_id, page, exc,
                    )
                    break

                if new_count == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0

                logger.info(
                    "[DLsite] 社团%s summary 分页抓取 maker_id=%s lang=%s page=%s new=%s total=%s",
                    mode, normalized_maker_id, normalized_language, page, new_count, len(summaries_by_rj),
                )

                if page == 1 and new_count == 0 and mode in {"profile", "profile-touch"}:
                    break

                if empty_streak >= 2:
                    break

        # 兜底：profile-touch filter URL
        if not summaries_by_rj:
            try:
                filter_url = (
                    f"https://www.dlsite.com/maniax-touch/circle/profile/="
                    f"/options[0]/{normalized_language}/maker_ids[0]/{normalized_maker_id}"
                    f"/per_page/50/work_category/doujin/hd/1"
                )
                response_f = await self._guarded_get(filter_url, headers=self._get_browser_headers())
                if response_f.status_code == 200:
                    any_http_success = True
                    if self._looks_like_dlsite_html(response_f.text):
                        any_html_looked_normal = True
                    page_summaries = self._extract_summaries_from_listing_html(response_f.text)
                    if absorb_summaries(page_summaries) == 0:
                        page_worknos = self._extract_worknos_from_listing_html(response_f.text)
                        if not page_worknos:
                            page_worknos = self._extract_any_worknos_from_listing_html(response_f.text)
                        if not page_worknos:
                            page_worknos = self._extract_not_product_ids_from_html(response_f.text)
                        absorb_raw_worknos(page_worknos)
            except Exception as exc:
                logger.debug("[DLsite] 社团profile-touch-filter summary 异常 maker_id=%s error=%s", normalized_maker_id, exc)

        # 推断 parse_status（与 list_circle_worknos_by_maker 同口径）
        if summaries_by_rj:
            parse_status = "ok"
        elif not any_http_success:
            parse_status = "http_error"
        elif not any_html_looked_normal:
            parse_status = "html_decode_failed"
        else:
            parse_status = "empty"

        ordered_summaries = [summaries_by_rj[rj] for rj in ordered_rjcodes if rj in summaries_by_rj]

        if ordered_summaries:
            self.cache[cache_key] = {
                'data': [s.to_dict() for s in ordered_summaries],
                'parse_status': parse_status,
                'timestamp': datetime.now(),
            }
        return ordered_summaries, parse_status

    async def list_new_work_summaries_by_date(
        self,
        release_date: str,
        *,
        language: str = "JPN",
        max_pages: int = 20,
    ) -> tuple[List[DLsiteWorkSummary], str]:
        """抓取 DLsite 指定发售日的公开作品摘要，只使用官方新作日期页。"""
        normalized_date = self._normalize_date_text(release_date)
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        if not normalized_date:
            return [], "empty"

        cache_key = f"new_work_summaries_by_date:{normalized_date}:{normalized_language}:{int(max_pages or 0)}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                hydrated: List[DLsiteWorkSummary] = []
                for item in list(cached_data.get('data') or []):
                    if isinstance(item, DLsiteWorkSummary):
                        hydrated.append(item)
                        continue
                    if not isinstance(item, dict):
                        continue
                    hydrated.append(DLsiteWorkSummary(
                        workno=str(item.get('workno') or '').strip().upper(),
                        title=str(item.get('title') or ''),
                        maker_id=str(item.get('maker_id') or ''),
                        maker_name=str(item.get('maker_name') or ''),
                        category_label=str(item.get('category_label') or ''),
                        work_type_code=str(item.get('work_type_code') or ''),
                        file_format_labels=list(item.get('file_format_labels') or []),
                        icon_classes=list(item.get('icon_classes') or []),
                        cover_url=str(item.get('cover_url') or ''),
                        is_probably_audio=item.get('is_probably_audio'),
                        classification_reason=str(item.get('classification_reason') or ''),
                        release_date=str(item.get('release_date') or ''),
                    ))
                return hydrated, str(cached_data.get('parse_status') or ("ok" if hydrated else "empty"))

        summaries_by_rj: Dict[str, DLsiteWorkSummary] = {}
        any_http_success = False
        any_html_looked_normal = False
        empty_streak = 0
        for page in range(1, max(1, int(max_pages or 1)) + 1):
            url = self._build_new_release_date_url(normalized_date, language=normalized_language, page=page)
            try:
                response = await self._guarded_get(
                    url,
                    headers=self._get_browser_headers(),
                    timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=None),
                    retry=False,
                )
                if response.status_code != 200:
                    logger.warning(
                        "[DLsite] 新作日期页抓取失败 date=%s page=%s status=%s",
                        normalized_date,
                        page,
                        response.status_code,
                    )
                    break
                any_http_success = True
                if self._looks_like_dlsite_html(response.text):
                    any_html_looked_normal = True
                page_summaries = self._extract_summaries_from_listing_html(response.text)
                new_count = 0
                for summary in page_summaries:
                    if not summary.workno or summary.workno in summaries_by_rj:
                        continue
                    summary.release_date = normalized_date
                    summaries_by_rj[summary.workno] = summary
                    new_count += 1
                if new_count == 0:
                    for workno in self._extract_worknos_from_listing_html(response.text):
                        if workno and workno not in summaries_by_rj:
                            summaries_by_rj[workno] = DLsiteWorkSummary(workno=workno, release_date=normalized_date)
                            new_count += 1
            except Exception as exc:
                logger.warning(
                    "[DLsite] 新作日期页抓取异常 date=%s page=%s error=%s",
                    normalized_date,
                    page,
                    exc,
                )
                break

            empty_streak = empty_streak + 1 if new_count == 0 else 0
            if page == 1 and new_count == 0:
                break
            if empty_streak >= 2:
                break

        summaries = list(summaries_by_rj.values())
        if summaries:
            parse_status = "ok"
        elif not any_http_success:
            parse_status = "http_error"
        elif not any_html_looked_normal:
            parse_status = "html_decode_failed"
        else:
            parse_status = "empty"
        self.cache[cache_key] = {
            'data': [item.to_dict() for item in summaries],
            'parse_status': parse_status,
            'timestamp': datetime.now(),
        }
        return summaries, parse_status

    def normalize_product_probe_feature(self, rjcode: str, product: Optional[Dict]) -> DLsiteProductProbeFeature:
        workno = self._normalize_workno(rjcode)
        if not isinstance(product, dict):
            return DLsiteProductProbeFeature(workno=workno, exists=False, probe_status="missing")
        maker = product.get("maker") if isinstance(product.get("maker"), dict) else {}
        maker_id = str(product.get("maker_id") or maker.get("id") or maker.get("maker_id") or "").strip().upper()
        release_date = self._normalize_date_text(
            product.get("regist_date")
            or product.get("release_date")
            or product.get("sales_date")
            or product.get("disp_start_date")
            or ""
        )
        work_type = str(product.get("work_type") or product.get("work_type_code") or product.get("category") or "").strip().upper()
        raw_price = product.get("price") if product.get("price") is not None else product.get("official_price")
        price = self._safe_product_int(raw_price, field="price", workno=workno)
        wishlist_value = product.get("wishlist_count")
        wishlist_count = self._safe_product_int(wishlist_value, field="wishlist_count", workno=workno)
        feature = DLsiteProductProbeFeature(
            workno=workno,
            exists=True,
            probe_status="ok",
            maker_id=maker_id,
            release_date=release_date,
            work_type=work_type,
            price=price,
            is_sale=bool(product.get("is_sale")),
            is_free=bool(product.get("is_free")),
            is_oly=bool(product.get("is_oly")),
            wishlist_count=wishlist_count,
            title=str(product.get("work_name") or product.get("title") or ""),
            raw_summary_json={
                "workno": product.get("workno") or workno,
                "maker_id": maker_id,
                "regist_date": product.get("regist_date") or product.get("release_date") or "",
                "work_type": work_type,
                "price": price,
                "raw_price": raw_price,
                "is_sale": bool(product.get("is_sale")),
                "is_free": bool(product.get("is_free")),
                "is_oly": bool(product.get("is_oly")),
                "wishlist_count": wishlist_count,
                "raw_wishlist_count": wishlist_value,
            },
        )
        return normalize_product_probe_feature_classification(feature)

    async def probe_product_info_features(
        self,
        rjcodes: List[str],
        *,
        locale: Optional[str] = None,
        concurrency: int = 5,
    ) -> Dict[str, DLsiteProductProbeFeature]:
        """批量拉取 product/info/ajax 并归一成隐藏特典探测字段。"""
        normalized: List[str] = []
        for value in rjcodes or []:
            workno = self._normalize_workno(value)
            if workno and workno not in normalized:
                normalized.append(workno)
        if not normalized:
            return {}
        semaphore = asyncio.Semaphore(max(1, int(concurrency or 1)))
        bulk_size = 500

        async def probe_one(workno: str) -> tuple[str, DLsiteProductProbeFeature]:
            async with semaphore:
                try:
                    product = await self._fetch_product_info_ajax_payload(workno, locale=locale)
                    return workno, self.normalize_product_probe_feature(workno, product)
                except Exception as exc:
                    return workno, DLsiteProductProbeFeature(
                        workno=workno,
                        exists=False,
                        probe_status="error",
                        error_message=self._format_exc(exc),
                    )

        async def probe_bulk(chunk: List[str]) -> Dict[str, DLsiteProductProbeFeature]:
            async with semaphore:
                try:
                    payloads = await self._fetch_product_info_ajax_payloads(chunk, locale=locale)
                except Exception:
                    payloads = None

            if payloads is None:
                pairs = await asyncio.gather(*[probe_one(workno) for workno in chunk])
                return {workno: feature for workno, feature in pairs}

            return {
                workno: self.normalize_product_probe_feature(workno, payloads.get(workno))
                for workno in chunk
            }

        chunks = [normalized[index:index + bulk_size] for index in range(0, len(normalized), bulk_size)]
        bulk_results = await asyncio.gather(*[probe_bulk(chunk) for chunk in chunks])
        features: Dict[str, DLsiteProductProbeFeature] = {}
        for item in bulk_results:
            features.update(item)
        return features

    async def list_circle_worknos_by_maker(
        self,
        maker_id: str,
        *,
        language: str = "JPN",
        max_pages: int = 200,
    ) -> tuple[List[str], str]:
        """抓取 maker_id 名下所有可见作品。

        ★ 返回值升级为 ``(rjcodes, parse_status)``。``parse_status`` 取值：

        - ``"ok"``：至少有一页解析到了 RJ；
        - ``"empty"``：HTTP 都成功、HTML 也是正常 DLsite 页面，但确实一个 RJ 都没解析出来
          （DLsite 上 maker_id 真没作品，多半是误识别的脏 maker_id）；
        - ``"html_decode_failed"``：HTTP 成功但 HTML 文本完全没有 DLsite 页面特征，
          疑似 brotli/gzip 解压失败导致拿到的是压缩字节乱码（应该让上层保留 maker_id 白名单
          继续走关键字 fallback，而不是误判为"真 0"重置 maker_id 退化）；
        - ``"http_error"``：所有 HTTP 请求都没拿到 200。

        历史调用方只读 ``rjcodes`` 即可，加一行解包就兼容；新调用方靠 status 决定是否
        盲目重置 maker_id。
        """
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        if not normalized_maker_id:
            return [], "empty"

        cache_key = f"circle_profile_with_announce:{normalized_maker_id}:{normalized_language}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                cached_list = list(cached_data.get('data') or [])
                cached_status = str(cached_data.get('parse_status') or ("ok" if cached_list else "empty"))
                return cached_list, cached_status

        found: List[str] = []
        seen: Set[str] = set()
        empty_streak = 0
        any_http_success = False
        any_html_looked_normal = False

        for mode, url_builder in [
            ("profile", self._build_circle_profile_url),
            ("profile-touch", self._build_circle_profile_touch_url),
            ("announce", self._build_circle_announce_url),
        ]:
            if mode == "profile-touch" and found:
                continue
            empty_streak = 0
            for page in range(1, max(1, int(max_pages)) + 1):
                if mode == "profile-touch":
                    url = url_builder(normalized_maker_id, page=page)
                else:
                    url = url_builder(normalized_maker_id, language=normalized_language, page=page)
                try:
                    response = await self._guarded_get(url, headers=self._get_browser_headers())
                    if response.status_code != 200:
                        logger.warning("[DLsite] 社团%s抓取失败 maker_id=%s page=%s status=%s", mode, normalized_maker_id, page, response.status_code)
                        break
                    any_http_success = True
                    if self._looks_like_dlsite_html(response.text):
                        any_html_looked_normal = True
                    page_worknos = self._extract_worknos_from_listing_html(response.text)
                    if not page_worknos and mode == "profile-touch":
                        page_worknos = self._extract_any_worknos_from_listing_html(response.text)
                    # profile-touch 专项补充：从页面 href 中的 not_product_ids 参数提取额外 RJcode
                    if not page_worknos and mode == "profile-touch":
                        npi_codes = self._extract_not_product_ids_from_html(response.text)
                        if npi_codes:
                            page_worknos = npi_codes
                            logger.info("[DLsite] 社团profile-touch从not_product_ids提取备选 maker_id=%s count=%s", normalized_maker_id, len(npi_codes))
                except Exception as exc:
                    logger.warning("[DLsite] 社团%s抓取异常 maker_id=%s page=%s error=%s", mode, normalized_maker_id, page, exc)
                    break

                new_count = 0
                for workno in page_worknos:
                    if workno not in seen:
                        seen.add(workno)
                        found.append(workno)
                        new_count += 1

                logger.info("[DLsite] 社团%s分页抓取 maker_id=%s lang=%s page=%s new=%s total=%s", mode, normalized_maker_id, normalized_language, page, new_count, len(found))

                if not page_worknos or new_count == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0

                if page == 1 and not page_worknos and mode in {"profile", "profile-touch"}:
                    html_preview = (response.text or "")[:400].replace("\n", " ").replace("\r", "")
                    html_len = len(response.text or "")
                    logger.info(
                        "[DLsite] 社团%s首页未解析到作品，提前切换入口 maker_id=%s html_len=%s html_preview=%.400s",
                        mode,
                        normalized_maker_id,
                        html_len,
                        html_preview,
                    )
                    break

                if empty_streak >= 2:
                    break

        # 当 profile/touch 均未找到作品时，尝试 maniax-touch 带 maker_ids 参数的 filter 格式 URL
        # 该格式对部分 IP 环境可能更稳定（per_page=50 单页返回更多）
        if not found:
            try:
                filter_url = (
                    f"https://www.dlsite.com/maniax-touch/circle/profile/="
                    f"/options[0]/{normalized_language}/maker_ids[0]/{normalized_maker_id}"
                    f"/per_page/50/work_category/doujin/hd/1"
                )
                response_f = await self._guarded_get(filter_url, headers=self._get_browser_headers())
                if response_f.status_code == 200:
                    any_http_success = True
                    if self._looks_like_dlsite_html(response_f.text):
                        any_html_looked_normal = True
                    filter_worknos = self._extract_worknos_from_listing_html(response_f.text)
                    if not filter_worknos:
                        filter_worknos = self._extract_any_worknos_from_listing_html(response_f.text)
                    if not filter_worknos:
                        filter_worknos = self._extract_not_product_ids_from_html(response_f.text)
                    for workno in filter_worknos:
                        if workno not in seen:
                            seen.add(workno)
                            found.append(workno)
                    logger.info(
                        "[DLsite] 社团profile-touch-filter抓取 maker_id=%s 获得=%s total=%s",
                        normalized_maker_id, len(filter_worknos), len(found),
                    )
                else:
                    logger.info("[DLsite] 社团profile-touch-filter失败 maker_id=%s status=%s", normalized_maker_id, response_f.status_code)
            except Exception as exc:
                logger.debug("[DLsite] 社团profile-touch-filter异常 maker_id=%s error=%s", normalized_maker_id, exc)

        # 推断 parse_status：
        # - 有 RJ → ok
        # - 否则没有任何一次 HTTP 200 → http_error
        # - 否则 HTML 完全不像 DLsite 页面 → html_decode_failed（典型 brotli/gzip 没解压）
        # - 否则 → empty（DLsite 上该 maker_id 名下确实没作品）
        if found:
            parse_status = "ok"
        elif not any_http_success:
            parse_status = "http_error"
        elif not any_html_looked_normal:
            parse_status = "html_decode_failed"
            logger.warning(
                "[DLsite] 社团 profile/announce 全部 HTTP 200 但 HTML 缺乏页面特征，"
                "疑似 br/gzip 未解压（请检查 brotlicffi 是否已安装）maker_id=%s",
                normalized_maker_id,
            )
        else:
            parse_status = "empty"

        if found:
            self.cache[cache_key] = {
                'data': list(found),
                'parse_status': parse_status,
                'timestamp': datetime.now()
            }
        return found, parse_status
    
    async def get_work_info(self, rjcode: str) -> Optional[Dict]:
        """获取作品详细信息"""
        product_info = await self.get_product_info(rjcode)
        
        if product_info and product_info.get('product'):
            product = product_info.get('product') or {}
            return {
                'rjcode': self._normalize_workno(product.get('workno') or rjcode),
                'title': product.get('work_name', ''),
                'maker_name': product.get('maker_name', ''),
                'release_date': product.get('regist_date', ''),
                'file_size': product.get('contents_file_size', 0),
                'cover_url': product.get('image_main', {}).get('url', '')
            }
        return None
    
    def get_rj_chain(self, rjcode: str, trans: TranslationInfo) -> List[str]:
        """获取 RJ 号关联链"""
        chain = [rjcode]
        if trans.is_child:
            if trans.parent_workno:
                chain.append(trans.parent_workno)
            if trans.original_workno:
                chain.append(trans.original_workno)
        elif trans.is_parent:
            if trans.original_workno:
                chain.append(trans.original_workno)
        return chain
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self.client:
            await self.client.aclose()


# 全局服务实例
_dlsite_service: Optional[DLsiteApiService] = None


def get_dlsite_service() -> DLsiteApiService:
    """获取 DLsite API 服务实例（单例）"""
    global _dlsite_service
    if _dlsite_service is None:
        _dlsite_service = DLsiteApiService()
    return _dlsite_service
