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
import re
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


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
        self.cache: Dict[str, Dict] = {}  # 缓存 API 响应
        self.cache_ttl = timedelta(hours=24)  # 缓存 24 小时

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

    def _build_circle_announce_url(self, maker_id: str, language: str = "JPN", page: int = 1) -> str:
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        base = f"https://www.dlsite.com/maniax/announce/=/maker_id/{normalized_maker_id}.html/options[0]/{normalized_language}"
        if page > 1:
            return f"{base}/page/{page}"
        return base

    def _get_browser_headers(self, accept: str = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8') -> Dict[str, str]:
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': accept,
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }

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
        for matched in re.findall(r'/(?:work|announce)/=/product_id/([RVB]J(?:\d{8}|\d{6}))\.html', text, re.IGNORECASE):
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

    async def _fetch_product_page_metadata(self, rjcode: str, locale: Optional[str] = None) -> Optional[Dict]:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return None

        page_urls = [
            self._build_product_page_url(workno, locale=locale),
            self._build_announce_product_page_url(workno, locale=locale),
        ]
        client = await self._get_client()
        for page_url in page_urls:
            cache_key = f"page_metadata:{page_url}"
            if cache_key in self.cache:
                cached_data = self.cache[cache_key]
                if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                    cached_product = cached_data['data']
                    if cached_product:
                        return cached_product
                    continue

            logger.info("[DLsite] 尝试页面元数据抓取: %s", page_url)
            try:
                response = await client.get(page_url, headers=self._get_browser_headers())
                product = self._parse_product_from_html(workno, page_url, str(response.url), response.text)
                self.cache[cache_key] = {
                    'data': product,
                    'timestamp': datetime.now()
                }
                if product:
                    logger.info(
                        "[DLsite] 页面元数据抓取成功: requested=%s resolved=%s title=%s",
                        workno,
                        self._normalize_workno(product.get('workno') or workno),
                        product.get('work_name') or '',
                    )
                    return product
                logger.info("[DLsite] 页面元数据未提取到有效字段: requested=%s url=%s", workno, page_url)
            except Exception as exc:
                logger.warning("[DLsite] 页面元数据抓取失败: requested=%s url=%s error=%s", workno, page_url, exc)
        return None

    async def _fetch_product_page_html(self, rjcode: str, locale: Optional[str] = None) -> str:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return ''

        page_url = self._build_product_page_url(workno, locale=locale)
        cache_key = f"page_html:{page_url}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return str(cached_data.get('data') or '')

        try:
            client = await self._get_client()
            response = await client.get(page_url, headers=self._get_browser_headers())
            text = str(response.text or '')
            self.cache[cache_key] = {
                'data': text,
                'timestamp': datetime.now(),
            }
            return text
        except Exception as exc:
            logger.warning("[DLsite] 页面 HTML 抓取失败: requested=%s error=%s", workno, exc)
            return ''

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
        try:
            client = await self._get_client()
            response = await client.get(
                page_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                },
            )
            final_codes = self._extract_product_codes_from_url(str(response.url))
            if final_codes.get('translation_workno') == workno and final_codes.get('product_workno'):
                result = final_codes
            else:
                result = self._extract_translation_linkage_from_html(response.text, workno)

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
        except Exception as exc:
            logger.warning("[DLsite] 页面 fallback 失败: requested=%s error=%s", workno, exc)
            return {}

    async def _is_public_work_available(self, rjcode: str, locale: Optional[str] = None) -> bool:
        workno = self._normalize_workno(rjcode)
        if not workno:
            return False

        cache_key = f"public_work_available:{workno}:{locale or ''}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return bool(cached_data.get('data'))

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

        product = await self._fetch_product_payload(requested_workno, locale=locale)
        if product:
            return {
                'product': product,
                'requested_workno': requested_workno,
                'resolved_workno': self._normalize_workno(product.get('workno') or requested_workno),
                'fallback_used': False,
                'fallback_source': 'api',
                'parent_workno': '',
                'edition_info': None,
            }

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
                return {
                    'product': effective_product,
                    'requested_workno': requested_workno,
                    'resolved_workno': parent_workno,
                    'fallback_used': True,
                    'fallback_source': 'translation_page',
                    'parent_workno': parent_workno,
                    'edition_info': edition_info,
                }

            logger.warning(
                "[DLsite] 页面 fallback 找到父作品，但父作品 API 返回空数据: requested=%s parent=%s",
                requested_workno,
                parent_workno,
            )

        page_product = await self._fetch_product_page_metadata(requested_workno, locale=locale)
        if page_product:
            return {
                'product': page_product,
                'requested_workno': requested_workno,
                'resolved_workno': self._normalize_workno(page_product.get('workno') or requested_workno),
                'fallback_used': True,
                'fallback_source': 'page_metadata',
                'parent_workno': parent_workno,
                'edition_info': None,
            }

        return None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self.client is None or self.client.is_closed:
            from ..config.settings import get_config

            config = get_config()
            proxy_url = None
            if config.metadata.http_proxy:
                proxy_url = f"http://{config.metadata.http_proxy}"
                logger.debug("[DLsite] 使用代理: %s", proxy_url)

            client_kwargs = {
                'headers': self._get_browser_headers('application/json, text/plain, */*'),
                'timeout': httpx.Timeout(30.0, connect=10.0),
                'verify': False,  # 避免部分网络环境下的 SSL 问题
                'follow_redirects': True,
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
    
    async def _fetch_api(self, url: str) -> Optional[Dict]:
        """从 DLsite API 获取数据"""
        cache_key = url

        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug("[DLsite] 使用缓存数据: %s", url)
                return cached_data['data']

        logger.info("[DLsite] 正在请求 API: %s", url)

        try:
            client = await self._get_client()
            logger.debug("[DLsite] 使用客户端配置: verify=False, timeout=30s")
            response = await client.get(url)

            logger.info("[DLsite] 响应状态码：%s", response.status_code)

            if response.status_code == 200:
                data = response.json()
                self.cache[cache_key] = {
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
            logger.error("错误详情: %s", str(e))
            logger.error("可能原因: 1) 网络连接异常 2) DLsite 不可达 3) 代理或防火墙拦截")
            return None
        except httpx.ReadTimeout as e:
            logger.error("API 读取超时: %s (超过 30 秒)", url)
            logger.error("错误详情: %s", str(e))
            return None
        except Exception as e:
            logger.error("API 请求异常: %s", url)
            logger.error("错误类型: %s", type(e).__name__)
            logger.error("错误详情: %s", str(e))
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    async def get_translation_info(self, rjcode: str) -> TranslationInfo:
        """
        获取作品的翻译信息
        
        返回:
            TranslationInfo: 包含 is_original, is_parent, is_child 等信息
        """
        product_info = await self.get_product_info(rjcode)
        if product_info and product_info.get('product'):
            translation_info = dict((product_info.get('product') or {}).get('translation_info', {}) or {})

            return TranslationInfo(
                is_original=translation_info.get('is_original', False),
                is_parent=translation_info.get('is_parent', False),
                is_child=translation_info.get('is_child', False),
                parent_workno=translation_info.get('parent_workno'),
                original_workno=translation_info.get('original_workno'),
                child_worknos=[
                    self._normalize_workno(workno)
                    for workno in list(translation_info.get('child_worknos') or [])
                    if self._normalize_workno(workno)
                ],
                lang=translation_info.get('lang', 'JPN')
            )
        
        return TranslationInfo(is_original=True)
    
    async def get_linked_works(self, rjcode: str) -> Dict[str, LinkedWork]:
        """
        获取作品的关联作品（包括原版和所有翻译版本）
        
        关联作品包括：
        - 原版作品（日文）
        - 所有翻译版本（简中、繁中、英文等不同译者，RJ 号各不相同）
        - 子翻译版本（嵌套翻译）
        
        返回:
            Dict[str, LinkedWork]: RJ 号到作品信息的映射
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
                for edition in language_editions or []:
                    workno = self._normalize_workno(edition.get('workno'))
                    if not workno:
                        continue
                    edition_lang = str(edition.get('lang') or '').strip() or ''
                    if workno != target_rjcode and edition_lang.upper() != 'JPN':
                        is_public = await self._is_public_work_available(workno)
                        if not is_public:
                            logger.info(
                                "[DLsite] 跳过前台不可见的翻译版本: parent=%s edition=%s lang=%s",
                                target_rjcode,
                                workno,
                                edition_lang,
                            )
                            continue
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
                result[target_rjcode] = LinkedWork(workno=target_rjcode, work_type='original', lang='JPN')

            return result

        try:
            normalized_rjcode = self._normalize_workno(rjcode)
            trans = await self.get_translation_info(normalized_rjcode)
            if not trans.is_original and trans.original_workno:
                original_rjcode = self._normalize_workno(trans.original_workno)
                logger.info(f"[DLsite] {normalized_rjcode} 是翻译版本，从原版 {original_rjcode} 获取完整关联链")
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
            logger.error(f"获取关联作品失败 {rjcode}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {rjcode: LinkedWork(workno=rjcode, work_type='original', lang='JPN')}
    
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

    async def list_circle_worknos_by_maker(
        self,
        maker_id: str,
        *,
        language: str = "JPN",
        max_pages: int = 200,
    ) -> List[str]:
        normalized_maker_id = str(maker_id or "").strip().upper()
        normalized_language = str(language or "JPN").strip().upper() or "JPN"
        if not normalized_maker_id:
            return []

        cache_key = f"circle_profile_with_announce:{normalized_maker_id}:{normalized_language}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                return list(cached_data.get('data') or [])

        client = await self._get_client()
        found: List[str] = []
        seen: Set[str] = set()
        empty_streak = 0

        for mode, url_builder in [
            ("profile", self._build_circle_profile_url),
            ("announce", self._build_circle_announce_url),
        ]:
            empty_streak = 0
            for page in range(1, max(1, int(max_pages)) + 1):
                url = url_builder(normalized_maker_id, language=normalized_language, page=page)
                try:
                    response = await client.get(url, headers=self._get_browser_headers())
                    if response.status_code != 200:
                        logger.warning("[DLsite] 社团%s抓取失败 maker_id=%s page=%s status=%s", mode, normalized_maker_id, page, response.status_code)
                        break
                    page_worknos = self._extract_worknos_from_listing_html(response.text)
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

                if empty_streak >= 2:
                    break

        self.cache[cache_key] = {
            'data': list(found),
            'timestamp': datetime.now()
        }
        return found
    
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
