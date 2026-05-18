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
import random
import re
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


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


class DLsiteApiService:
    """DLsite API 服务"""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
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

    def _build_product_api_url(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={workno}"
        if locale:
            url = f"{url}&locale={locale}"
        return url

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

    def _extract_product_codes_from_url(self, url: str) -> Dict[str, str]:
        parsed = urlparse(str(url or ''))
        path_match = re.search(r'/product_id/([RVB]J(?:\d{8}|\d{6}))\.html', parsed.path, re.IGNORECASE)
        query = parse_qs(parsed.query)
        return {
            'product_workno': path_match.group(1).upper() if path_match else '',
            'translation_workno': str((query.get('translation') or [''])[0] or '').strip().upper(),
        }

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
            'translation_info': {'is_original': True, 'lang': 'JPN'},
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

        fallback = await self._resolve_translation_page_fallback(requested_workno, locale=locale)
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
        if self.client is None or self.client.is_closed:
            from ..config.settings import get_config

            config = get_config()
            proxy_url = None
            if config.metadata.http_proxy:
                proxy_url = self._normalize_proxy_url(config.metadata.http_proxy)
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
        return self.client

    async def _close_client(self):
        if self.client and not self.client.is_closed:
            await self.client.aclose()
        self.client = None

    async def _one_shot_get(self, url: str, **kwargs) -> httpx.Response:
        from ..config.settings import get_config

        config = get_config()
        client_kwargs = {
            'headers': self._get_api_headers(),
            'timeout': httpx.Timeout(connect=25.0, read=60.0, write=10.0, pool=None),
            'verify': False,
            'follow_redirects': True,
            'limits': httpx.Limits(max_connections=1, max_keepalive_connections=0),
            'http2': False,
        }
        proxy_url = self._normalize_proxy_url(config.metadata.http_proxy)
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

    async def _guarded_get(self, url: str, **kwargs) -> httpx.Response:
        """带并发限制的 HTTP GET，超时时指数退避重试（最多 3 次）。

        并发上限设为 3，与 DLsite 的隐式速率限制对齐，避免连接被服务端挂起。
        每次进入 semaphore 后加随机抖动延迟，分散请求时序，降低被限流概率。
        """
        if self._http_semaphore is None:
            # 最多 3 个并发 DLsite 请求，对标 kikoeru 的低并发策略
            self._http_semaphore = asyncio.Semaphore(3)
        for attempt in range(3):
            try:
                async with self._http_semaphore:
                    await asyncio.sleep(random.uniform(0.2, 0.8))
                    client = await self._get_client()
                    return await client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
                wait = 2.0 * (2 ** attempt)  # 2s → 4s → 8s
                await self._close_client()
                if attempt < 2:
                    logger.warning(
                        "[DLsite] 请求失败，等待 %.0fs 后重试（第 %d 次）: %s error=%s",
                        wait, attempt + 1, url, self._format_exc(exc),
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("[DLsite] 复用客户端重试失败，改用一次性客户端: %s error=%s", url, self._format_exc(exc))
                return await self._one_shot_get(url, **kwargs)
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
        logger.info("[DLsite] 正在请求 API: %s", url)

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
                logger.warning("API 返回 404: %s", url)
                return None

            logger.error("API 请求失败: %s, 状态码: %s", url, response.status_code)
            return None
        except httpx.ConnectError as e:
            logger.error("API 连接失败: %s", url)
            logger.error("错误详情: %s", self._format_exc(e))
            logger.error("可能原因: 1) 网络连接异常 2) DLsite 不可达 3) 代理或防火墙拦截")
            return None
        except httpx.ReadTimeout as e:
            logger.error("API 读取超时: %s (超过 45 秒)", url)
            logger.error("错误详情: %s", self._format_exc(e))
            return None
        except Exception as e:
            logger.error("API 请求异常: %s", url)
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
            translation_info = dict((product_info.get('product') or {}).get('translation_info', {}) or {})
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
    
    async def get_linked_works(self, rjcode: str) -> Dict[str, LinkedWork]:
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

        # 1. cache 短路（同一任务内重复调用近乎免费）
        cache_key = f"linked_works:{normalized_rjcode}"
        if cache_key in self.cache:
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
                if original_workno:
                    result[original_workno] = LinkedWork(workno=original_workno, work_type='original', lang='JPN')
                result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='translation', lang=trans.lang or 'JPN')
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
                if parent_workno:
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
                result.update(direct_links)
                logger.info(f"[DLsite] {normalized_rjcode} 关联作品 ({len(result)}个): {list(result.keys())}")
                return result

            result = await _get_direct_linked_works(normalized_rjcode)
            probe_worknos = [
                workno
                for workno, work in list(result.items())
                if workno != normalized_rjcode and str(getattr(work, 'lang', '') or '').strip().upper() != 'JPN'
            ]
            for probe_workno in probe_worknos:
                direct_links = await _get_direct_linked_works(probe_workno)
                result.update(direct_links)

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
