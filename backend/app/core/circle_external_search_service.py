from __future__ import annotations

import asyncio
import hashlib
import hashlib
import logging
import re
from copy import deepcopy
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from ..config.settings import get_config
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


class _AnimeShareResultParser(HTMLParser):
    """只提取 AnimeShare 搜索结果标题里的真实帖子链接。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title_depth = 0
        self._href = ""
        self._text: List[str] = []
        self.results: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h3" and "contentRow-title" in str(attributes.get("class") or "").split():
            self._title_depth = 1
            self._href = ""
            self._text = []
        elif self._title_depth:
            self._title_depth += 1
            if tag == "a" and not self._href:
                self._href = str(attributes.get("href") or "").strip()

    def handle_endtag(self, tag: str) -> None:
        if not self._title_depth:
            return
        self._title_depth -= 1
        if self._title_depth == 0 and self._href:
            title = " ".join("".join(self._text).split())
            self.results.append({"url": self._href, "title": title})
            self._href = ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._text.append(data)


class _SouthPlusResultParser(HTMLParser):
    """南+登录态可用时，提取搜索列表中含精确 RJ 的帖子链接。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href = ""
        self._text: List[str] = []
        self.results: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = str(dict(attrs).get("href") or "").strip()
        if "read.php" not in href and "thread.php" not in href:
            return
        self._href = href
        self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        title = " ".join("".join(self._text).split())
        self.results.append({"url": self._href, "title": title})
        self._href = ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)


class CircleExternalSearchService:
    """社团补全的外部搜索跳转探测，不参与来源统计或下载链路。"""

    _ANIME_SHARE_BASE_URL = "https://www.anime-sharing.com"
    _SOUTH_PLUS_BASE_URL = "https://bbs.white-plus.net"
    _CACHE_TTL_SECONDS = 6 * 60 * 60
    _UNAVAILABLE_TTL_SECONDS = 10 * 60
    _ERROR_TTL_SECONDS = 5 * 60
    _MAX_CONCURRENT_REQUESTS = 4

    def __init__(self) -> None:
        self._cache = TTLCache(max_size=4096, ttl_seconds=self._CACHE_TTL_SECONDS, name="circle.external_search")
        self._inflight: Dict[str, asyncio.Future] = {}
        self._semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)

    @staticmethod
    def _normalize_rjcode(value: Any) -> str:
        match = re.search(r"[RVB]J(?:\d{6}|\d{8})(?!\d)", str(value or ""), re.IGNORECASE)
        return match.group(0).upper() if match else ""

    @classmethod
    def _matches_nearby_rjcode(cls, target: str, *values: Any) -> bool:
        """外站 RJ 允许 +/-1，避免标题文本相似造成误命中。"""
        normalized_target = cls._normalize_rjcode(target)
        target_match = re.fullmatch(r"([RVB]J)(\d{6}|\d{8})", normalized_target, re.IGNORECASE)
        if not target_match:
            return False
        prefix, digits = target_match.groups()
        target_number = int(digits)
        for value in values:
            for candidate in re.findall(r"[RVB]J(?:\d{6}|\d{8})(?!\d)", str(value or ""), re.IGNORECASE):
                normalized = cls._normalize_rjcode(candidate)
                match = re.fullmatch(r"([RVB]J)(\d{6}|\d{8})", normalized, re.IGNORECASE)
                if not match or match.group(1).upper() != prefix.upper() or len(match.group(2)) != len(digits):
                    continue
                if abs(int(match.group(2)) - target_number) <= 1:
                    return True
        return False

    @staticmethod
    def _cache_key(source: str, rjcode: str) -> str:
        config = get_config().circle_external_search
        if source == "south_plus":
            signature = "|".join([
                str(bool(getattr(config, "south_plus_enabled", True))),
                str(getattr(config, "south_plus_cookie", "") or ""),
                str(getattr(config, "south_plus_proxy", "") or ""),
            ])
            return f"{source}:{hashlib.sha1(signature.encode('utf-8')).hexdigest()[:12]}:{rjcode}"
        return f"{source}:{bool(getattr(config, 'anime_share_enabled', True))}:{rjcode}"

    def _redis_service(self):
        try:
            from .redis_service import get_redis_service

            service = get_redis_service()
            return service if service.is_enabled() else None
        except Exception:
            logger.debug("[社团补全·外部搜索] Redis 不可用", exc_info=True)
            return None

    def _cache_get(self, key: str) -> Dict[str, Any] | None:
        cached = self._cache.get(key)
        if isinstance(cached, dict):
            return deepcopy(cached)
        service = self._redis_service()
        if service is None:
            return None
        try:
            cached = service.get_json("circle-external-search", "result", key)
        except Exception:
            logger.debug("[社团补全·外部搜索] Redis 读取失败 key=%s", key, exc_info=True)
            return None
        if isinstance(cached, dict):
            self._cache[key] = deepcopy(cached)
            return deepcopy(cached)
        return None

    def _cache_set(self, key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds >= self._CACHE_TTL_SECONDS:
            self._cache[key] = deepcopy(payload)
        service = self._redis_service()
        if service is None:
            return
        try:
            service.set_json("circle-external-search", "result", key, payload, ttl_seconds=ttl_seconds)
        except Exception:
            logger.debug("[社团补全·外部搜索] Redis 写入失败 key=%s", key, exc_info=True)

    @staticmethod
    def _is_allowed_url(value: str, host: str, paths: Iterable[str]) -> bool:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != host:
            return False
        return any(parsed.path.startswith(prefix) for prefix in paths)

    def _anime_share_search_url(self, rjcode: str) -> str:
        return f"{self._ANIME_SHARE_BASE_URL}/search/3528560/?{urlencode({'q': rjcode, 'o': 'relevance'})}"

    def _south_plus_search_url(self, rjcode: str) -> str:
        query = {
            "step": "2",
            "keyword": rjcode,
            "method": "OR",
            "pwuser": "",
            "sch_area": "0",
            "f_fid": "all",
            "sch_time": "all",
            "orderway": "postdate",
            "asc": "DESC",
        }
        return f"{self._SOUTH_PLUS_BASE_URL}/search.php?{urlencode(query)}"

    def _source_search_url(self, source: str, rjcode: str) -> str:
        if source == "anime_share":
            return self._anime_share_search_url(rjcode)
        return self._south_plus_search_url(rjcode)

    async def _fetch_text(
        self,
        url: str,
        *,
        headers: Dict[str, str] | None = None,
        proxy: str = "",
    ) -> str:
        async with self._semaphore:
            client_kwargs: Dict[str, Any] = {
                "follow_redirects": True,
                "timeout": httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0),
                "headers": {
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                    "User-Agent": "KikoeruManager/1.0 external-search",
                    **(headers or {}),
                },
            }
            if str(proxy or "").strip():
                client_kwargs["proxy"] = str(proxy).strip()
            async with httpx.AsyncClient(
                **client_kwargs,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text

    async def _search_anime_share(self, rjcode: str) -> Dict[str, Any]:
        search_url = self._anime_share_search_url(rjcode)
        if not bool(getattr(get_config().circle_external_search, "anime_share_enabled", True)):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        try:
            page = await self._fetch_text(search_url)
            parser = _AnimeShareResultParser()
            parser.feed(page)
            results = []
            for result in parser.results:
                title = str(result.get("title") or "").strip()
                url = urljoin(self._ANIME_SHARE_BASE_URL, str(result.get("url") or ""))
                if not self._matches_nearby_rjcode(rjcode, title, url) or not self._is_allowed_url(url, "www.anime-sharing.com", ("/threads/",)):
                    continue
                if not any(item["url"] == url for item in results):
                    results.append({"url": url, "title": title})
            return {"status": "hit" if results else "miss", "results": results, "search_url": search_url}
        except Exception:
            logger.info("[社团补全·外部搜索] AnimeShare 查询失败 rj=%s", rjcode, exc_info=True)
            return {"status": "error", "results": [], "search_url": search_url}

    async def _search_south_plus(self, rjcode: str) -> Dict[str, Any]:
        search_url = self._south_plus_search_url(rjcode)
        config = get_config().circle_external_search
        if not bool(getattr(config, "south_plus_enabled", True)):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        cookie = str(getattr(config, "south_plus_cookie", "") or "").strip()
        proxy = str(getattr(config, "south_plus_proxy", "") or "").strip()
        if not cookie:
            return {"status": "unavailable", "results": [], "search_url": search_url}
        try:
            page = await self._fetch_text(
                search_url,
                headers={"Cookie": cookie} if cookie else None,
                proxy=proxy,
            )
            if "不能使用搜索功能" in page or "用户组权限" in page:
                return {"status": "unavailable", "results": [], "search_url": search_url}
            parser = _SouthPlusResultParser()
            parser.feed(page)
            results = []
            for result in parser.results:
                title = str(result.get("title") or "").strip()
                url = urljoin(self._SOUTH_PLUS_BASE_URL, str(result.get("url") or ""))
                if not self._matches_nearby_rjcode(rjcode, title, url) or not self._is_allowed_url(url, "bbs.white-plus.net", ("/read.php", "/thread.php")):
                    continue
                if not any(item["url"] == url for item in results):
                    results.append({"url": url, "title": title})
            return {"status": "hit" if results else "miss", "results": results, "search_url": search_url}
        except Exception:
            logger.info("[社团补全·外部搜索] 南+ 查询失败 rj=%s", rjcode, exc_info=True)
            return {"status": "error", "results": [], "search_url": search_url}

    async def _lookup_source(self, source: str, rjcode: str) -> Dict[str, Any]:
        config = get_config().circle_external_search
        search_url = self._source_search_url(source, rjcode)
        if source == "anime_share" and not bool(getattr(config, "anime_share_enabled", True)):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        if source == "south_plus" and (
            not bool(getattr(config, "south_plus_enabled", True))
            or not str(getattr(config, "south_plus_cookie", "") or "").strip()
        ):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        key = self._cache_key(source, rjcode)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        existing = self._inflight.get(key)
        if existing is not None:
            return deepcopy(await existing)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._inflight[key] = future
        try:
            payload = await (self._search_anime_share(rjcode) if source == "anime_share" else self._search_south_plus(rjcode))
            status = str(payload.get("status") or "error")
            ttl = self._CACHE_TTL_SECONDS if status in {"hit", "miss"} else (
                self._UNAVAILABLE_TTL_SECONDS if status == "unavailable" else self._ERROR_TTL_SECONDS
            )
            self._cache_set(key, payload, ttl)
            future.set_result(deepcopy(payload))
            return payload
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)

    @staticmethod
    def _result_entry(source: str, variant: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, str]:
        return {
            "source": source,
            "rjcode": str(variant.get("rjcode") or ""),
            "variant_key": str(variant.get("group_key") or "original"),
            "variant_label": str(variant.get("group_short_label") or variant.get("group_label") or "原作"),
            "title": str(result.get("title") or variant.get("title") or ""),
            "url": str(result.get("url") or ""),
        }

    def _search_entry(self, source: str, variant: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, str]:
        rjcode = self._normalize_rjcode(variant.get("rjcode"))
        return self._result_entry(source, variant, {
            "title": f"搜索 {rjcode}",
            "url": str(payload.get("search_url") or self._source_search_url(source, rjcode)),
        })

    async def search_variants(self, variants_by_canonical: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """查询当前页作品；结果只供跳转标签，不会回写 CircleWork。"""
        unique_codes = []
        for variants in variants_by_canonical.values():
            for variant in variants:
                rjcode = self._normalize_rjcode(variant.get("rjcode"))
                if rjcode and rjcode not in unique_codes:
                    unique_codes.append(rjcode)

        lookups = {
            (source, rjcode): asyncio.create_task(self._lookup_source(source, rjcode))
            for source in ("anime_share", "south_plus")
            for rjcode in unique_codes
        }
        if lookups:
            await asyncio.gather(*lookups.values())

        items: Dict[str, Any] = {}
        for canonical, variants in variants_by_canonical.items():
            source_payloads: Dict[str, Any] = {}
            for source in ("anime_share", "south_plus"):
                entries: List[Dict[str, str]] = []
                search_entries: List[Dict[str, str]] = []
                statuses = []
                for variant in variants:
                    rjcode = self._normalize_rjcode(variant.get("rjcode"))
                    if not rjcode:
                        continue
                    payload = lookups[(source, rjcode)].result()
                    statuses.append(str(payload.get("status") or "error"))
                    search_entry = self._search_entry(source, variant, payload)
                    if search_entry["url"] and not any(existing["url"] == search_entry["url"] for existing in search_entries):
                        search_entries.append(search_entry)
                    for result in payload.get("results") or []:
                        entry = self._result_entry(source, variant, result)
                        if entry["url"] and not any(existing["url"] == entry["url"] for existing in entries):
                            entries.append(entry)

                if entries:
                    status = "hit"
                elif statuses and all(status == "miss" for status in statuses):
                    status = "miss"
                else:
                    status = "unavailable" if "unavailable" in statuses else "error"
                source_payloads[source] = {
                    "status": status,
                    "results": entries,
                    "search_results": search_entries,
                }
            items[str(canonical)] = source_payloads
        return {"items": items}


_service: CircleExternalSearchService | None = None


def get_circle_external_search_service() -> CircleExternalSearchService:
    global _service
    if _service is None:
        _service = CircleExternalSearchService()
    return _service
