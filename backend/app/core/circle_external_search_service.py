from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import timedelta
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert

from ..config.settings import get_config
from ..models.database import CircleExternalSearchRecord, SessionLocal, get_local_now
from .http_client_lifecycle import HttpClientLifecycle

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
    _HIT_REFRESH_SECONDS = 30 * 24 * 60 * 60
    _MISS_REFRESH_SECONDS = 7 * 24 * 60 * 60
    _UNAVAILABLE_REFRESH_SECONDS = 10 * 60
    _ERROR_REFRESH_SECONDS = 5 * 60
    _MAX_CONCURRENT_REQUESTS = 4
    _SOUTH_PLUS_REQUEST_INTERVAL_SECONDS = 10.0
    _PROBE_SCHEMA_VERSION = "browser-headers-v1"
    _WORKER_IDLE_SECONDS = 1.0
    _WORKER_LEASE_SECONDS = 90
    _SOUTH_PLUS_BROWSER_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.8,en-BG;q=0.7,en-US;q=0.6,ja;q=0.5,zh-TW;q=0.4",
        "Cache-Control": "max-age=0",
        "Referer": "https://bbs.white-plus.net/search.php",
        "Sec-CH-UA": '"Not:A-Brand";v="8", "Chromium";v="150", "Microsoft Edge";v="150"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0",
    }

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_REQUESTS)
        self._south_plus_lock = asyncio.Lock()
        self._south_plus_next_request_at = 0.0
        self._worker_task: asyncio.Task | None = None
        self._worker_stop_event: asyncio.Event | None = None
        self._clients = {}
        self._client_lifecycle = HttpClientLifecycle()
        self._source_backoffs = {}

    @staticmethod
    def _source_signature(source: str) -> str:
        config = get_config().circle_external_search
        values = (
            getattr(config, source + "_enabled", True),
            getattr(config, source + "_cookie", ""),
            getattr(config, source + "_proxy", ""),
        )
        return hashlib.sha256(repr(values).encode()).hexdigest()

    def _source_backoff(self, source: str):
        state = self._source_backoffs.get(source)
        if state and state[0] == self._source_signature(source) and state[1] > time.monotonic():
            return state[2]
        self._source_backoffs.pop(source, None)
        return None

    def _pause_source(self, source: str, code: str, seconds: float, signature: str) -> None:
        if signature != self._source_signature(source):
            return
        if not self._source_backoff(source):
            logger.warning("[社团补全·外部搜索] 暂停来源 source=%s reason=%s seconds=%s", source, code, seconds)
        self._source_backoffs[source] = (signature, time.monotonic() + seconds, code)

    @staticmethod
    def _south_plus_access_error(page: str) -> str:
        if any(text in page for text in ("请先登录论坛", "您还不是论坛会员", "您尚未登录")):
            return "login_required"
        if "不能使用搜索功能" in page or "用户组权限" in page:
            return "permission_denied"
        return ""

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

    @classmethod
    def _south_plus_headers(cls, cookie: str) -> Dict[str, str]:
        return {**cls._SOUTH_PLUS_BROWSER_HEADERS, "Cookie": str(cookie or "").strip()}

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
        # 与 DLsite / ASMR 的代理输入约定一致：host:port 默认使用 HTTP。
        proxy = str(proxy or "").strip()
        if proxy and "://" not in proxy:
            proxy = f"http://{proxy}"
        async with self._semaphore:
            client_kwargs: Dict[str, Any] = {
                "trust_env": False,
                "follow_redirects": True,
                "timeout": httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0),
                "limits": httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=60),
            }
            request_headers = {
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                    "User-Agent": "KikoeruManager/1.0 external-search",
                    **(headers or {}),
            }
            if str(proxy or "").strip():
                client_kwargs["proxy"] = str(proxy).strip()
            key = (urlparse(url).netloc, str(proxy or "").strip())
            client = self._clients.get(key)
            if client is None or client.is_closed:
                client = self._clients[key] = httpx.AsyncClient(**client_kwargs)
            def discard(failed):
                if self._clients.get(key) is failed:
                    self._clients.pop(key, None)

            async with self._client_lifecycle.use(client, discard):
                response = await client.get(url, headers=request_headers)
                response.raise_for_status()
                return response.text

    async def _fetch_south_plus_text(
        self,
        url: str,
        *,
        headers: Dict[str, str] | None = None,
        proxy: str = "",
    ) -> str:
        """南+搜索严格单请求串行，并保证相邻请求间隔至少 10 秒。"""
        async with self._south_plus_lock:
            delay = self._south_plus_next_request_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                return await self._fetch_text(url, headers=headers, proxy=proxy)
            finally:
                self._south_plus_next_request_at = time.monotonic() + self._SOUTH_PLUS_REQUEST_INTERVAL_SECONDS

    async def _search_anime_share(self, rjcode: str) -> Dict[str, Any]:
        search_url = self._anime_share_search_url(rjcode)
        signature = self._source_signature("anime_share")
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
        except Exception as exc:
            code = type(exc).__name__
            self._pause_source("anime_share", code, self._ERROR_REFRESH_SECONDS, signature)
            return {"status": "error", "error_code": code, "results": [], "search_url": search_url}

    async def _search_south_plus(self, rjcode: str) -> Dict[str, Any]:
        search_url = self._south_plus_search_url(rjcode)
        config = get_config().circle_external_search
        signature = self._source_signature("south_plus")
        if not bool(getattr(config, "south_plus_enabled", True)):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        cookie = str(getattr(config, "south_plus_cookie", "") or "").strip()
        proxy = str(getattr(config, "south_plus_proxy", "") or "").strip()
        if not cookie:
            return {"status": "unavailable", "results": [], "search_url": search_url}
        try:
            page = await self._fetch_south_plus_text(
                search_url,
                headers=self._south_plus_headers(cookie),
                proxy=proxy,
            )
            access_error = self._south_plus_access_error(page)
            if access_error:
                self._pause_source("south_plus", access_error, self._UNAVAILABLE_REFRESH_SECONDS, signature)
                return {"status": "unavailable", "error_code": access_error, "results": [], "search_url": search_url}
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
        except Exception as exc:
            code = type(exc).__name__
            self._pause_source("south_plus", code, self._ERROR_REFRESH_SECONDS, signature)
            return {"status": "error", "error_code": code, "results": [], "search_url": search_url}

    async def test_south_plus_connection(self, cookie: str = "", proxy: str = "") -> Dict[str, Any]:
        """只验证南+搜索页可访问性，不写入作品搜索缓存。"""
        cookie = str(cookie or "").strip()
        if not cookie:
            return {"success": False, "status": "missing_cookie", "message": "请先填写南+ Cookie"}
        started_at = time.perf_counter()
        search_url = self._south_plus_search_url("RJ00000000")
        try:
            page = await self._fetch_south_plus_text(
                search_url,
                headers=self._south_plus_headers(cookie),
                proxy=str(proxy or "").strip(),
            )
            access_error = self._south_plus_access_error(page)
            if access_error:
                return {
                    "success": False,
                    "status": access_error,
                    "message": "南+ Cookie 已失效，请重新登录后更新 Cookie" if access_error == "login_required" else "南+ 当前账号没有搜索权限",
                    "latency_ms": round((time.perf_counter() - started_at) * 1000),
                }
            config = get_config().circle_external_search
            if (cookie == str(getattr(config, "south_plus_cookie", "") or "").strip()
                    and str(proxy or "").strip() == str(getattr(config, "south_plus_proxy", "") or "").strip()):
                self._source_backoffs.pop("south_plus", None)
            return {
                "success": True,
                "status": "ok",
                "message": "南+ 搜索连接正常",
                "latency_ms": round((time.perf_counter() - started_at) * 1000),
            }
        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "status": "http_error",
                "message": f"南+ 返回 HTTP {exc.response.status_code}",
                "http_status": exc.response.status_code,
                "latency_ms": round((time.perf_counter() - started_at) * 1000),
            }
        except Exception as exc:
            logger.info("[社团补全·外部搜索] 南+ 连接测试失败 type=%s", type(exc).__name__)
            return {
                "success": False,
                "status": "error",
                "error_code": type(exc).__name__,
                "message": "南+ 连接失败，请检查代理和 Cookie",
                "latency_ms": round((time.perf_counter() - started_at) * 1000),
            }

    async def _fetch_source(self, source: str, rjcode: str) -> Dict[str, Any]:
        """worker 专用的真实外站请求；页面读取路径不得调用此方法。"""
        config = get_config().circle_external_search
        search_url = self._source_search_url(source, rjcode)
        backoff = self._source_backoff(source)
        if backoff:
            return {"status": "unavailable", "error_code": backoff, "results": [], "search_url": search_url}
        if source == "anime_share" and not bool(getattr(config, "anime_share_enabled", True)):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        if source == "south_plus" and (
            not bool(getattr(config, "south_plus_enabled", True))
            or not str(getattr(config, "south_plus_cookie", "") or "").strip()
        ):
            return {"status": "unavailable", "results": [], "search_url": search_url}
        return await (self._search_anime_share(rjcode) if source == "anime_share" else self._search_south_plus(rjcode))

    @classmethod
    def _record_payload(cls, record: CircleExternalSearchRecord) -> Dict[str, Any]:
        return {
            "status": str(record.status or "pending"),
            "results": list(record.results_json or []),
            "search_url": str(record.search_url or cls._source_search_url(record.source, record.rjcode)),
            "checked_at": record.checked_at.isoformat() if record.checked_at else None,
            "error_code": str(record.last_error_code or ""),
        }

    def _load_or_enqueue_records(self, lookup_keys: List[tuple[str, str]]) -> Dict[tuple[str, str], Dict[str, Any]]:
        """批量读取 PostgreSQL 快照；缺失或到期项只入队，绝不在页面请求中访问外站。"""
        if not lookup_keys:
            return {}
        unavailable = {(source, code): {"status": "unavailable", "results": [],
                       "search_url": self._source_search_url(source, code)}
                       for source, code in lookup_keys if not self._source_ready(source)}
        lookup_keys = [key for key in lookup_keys if key not in unavailable]
        if not lookup_keys:
            return unavailable
        now = get_local_now()
        sources = sorted({source for source, _rjcode in lookup_keys})
        rjcodes = sorted({rjcode for _source, rjcode in lookup_keys})
        db = SessionLocal()
        try:
            # 并发页面请求可能同时补同一条快照，由唯一键裁决且不覆盖 worker 的结果。
            db.execute(insert(CircleExternalSearchRecord).values([
                dict(
                    source=source,
                    rjcode=rjcode,
                    probe_schema_version=self._PROBE_SCHEMA_VERSION,
                    status="pending",
                    results_json=[],
                    search_url=self._source_search_url(source, rjcode),
                    next_probe_at=now,
                    priority=100,
                )
                for source, rjcode in sorted(set(lookup_keys))
            ]).on_conflict_do_nothing(
                index_elements=["source", "rjcode", "probe_schema_version"],
            ))
            rows = db.query(CircleExternalSearchRecord).filter(
                CircleExternalSearchRecord.probe_schema_version == self._PROBE_SCHEMA_VERSION,
                CircleExternalSearchRecord.source.in_(sources),
                CircleExternalSearchRecord.rjcode.in_(rjcodes),
            ).all()
            records = {(row.source, row.rjcode): row for row in rows}
            for source, rjcode in lookup_keys:
                record = records.get((source, rjcode))
                if record.next_probe_at <= now and (record.lease_until is None or record.lease_until <= now):
                    record.priority = max(int(record.priority or 0), 100)
            db.commit()
            return {**unavailable, **{key: self._record_payload(record) for key, record in records.items()}}
        except Exception:
            db.rollback()
            logger.warning("[社团补全·外部搜索] 读取持久搜索快照失败", exc_info=True)
            return {**unavailable, **{
                (source, rjcode): {
                    "status": "error",
                    "results": [],
                    "search_url": self._source_search_url(source, rjcode),
                }
                for source, rjcode in lookup_keys
            }}
        finally:
            db.close()

    def _claim_next_record(self, source: str) -> Dict[str, str] | None:
        now = get_local_now()
        db = SessionLocal()
        try:
            row = (
                db.query(CircleExternalSearchRecord)
                .filter(CircleExternalSearchRecord.probe_schema_version == self._PROBE_SCHEMA_VERSION)
                .filter(CircleExternalSearchRecord.source == source)
                .filter(CircleExternalSearchRecord.next_probe_at <= now)
                .filter(or_(CircleExternalSearchRecord.lease_until.is_(None), CircleExternalSearchRecord.lease_until <= now))
                .order_by(CircleExternalSearchRecord.priority.desc(), CircleExternalSearchRecord.next_probe_at.asc(), CircleExternalSearchRecord.id.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                return None
            row.lease_until = now + timedelta(seconds=self._WORKER_LEASE_SECONDS)
            row.priority = 0
            db.commit()
            return {"id": str(row.id), "source": str(row.source), "rjcode": str(row.rjcode)}
        except Exception:
            db.rollback()
            logger.warning("[社团补全·外部搜索] 领取持久搜索任务失败", exc_info=True)
            return None
        finally:
            db.close()

    def requeue_unavailable_source(self, source: str) -> int:
        """登录态或代理变更后，唤醒不可用及请求失败记录，不动已有命中。"""
        self._source_backoffs.pop(source, None)
        now = get_local_now()
        db = SessionLocal()
        try:
            updated = (
                db.query(CircleExternalSearchRecord)
                .filter(CircleExternalSearchRecord.source == str(source or "").strip())
                .filter(CircleExternalSearchRecord.probe_schema_version == self._PROBE_SCHEMA_VERSION)
                .filter(CircleExternalSearchRecord.status.in_(["unavailable", "error"]))
                .update({
                    CircleExternalSearchRecord.next_probe_at: now,
                    CircleExternalSearchRecord.lease_until: None,
                    CircleExternalSearchRecord.priority: 100,
                }, synchronize_session=False)
            )
            db.commit()
            return int(updated or 0)
        except Exception:
            db.rollback()
            logger.warning("[社团补全·外部搜索] 重新入队不可用记录失败 source=%s", source, exc_info=True)
            return 0
        finally:
            db.close()

    @classmethod
    def _next_probe_at(cls, status: str, now):
        if status == "hit":
            seconds = cls._HIT_REFRESH_SECONDS
        elif status == "miss":
            seconds = cls._MISS_REFRESH_SECONDS
        elif status == "unavailable":
            seconds = cls._UNAVAILABLE_REFRESH_SECONDS
        else:
            seconds = cls._ERROR_REFRESH_SECONDS
        return now + timedelta(seconds=seconds)

    def _complete_record(self, record_id: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        now = get_local_now()
        db = SessionLocal()
        try:
            row = db.query(CircleExternalSearchRecord).filter(CircleExternalSearchRecord.id == int(record_id)).first()
            if row is None:
                return None
            status = str(payload.get("status") or "error")
            row.status = status
            row.results_json = list(payload.get("results") or [])
            row.search_url = str(payload.get("search_url") or self._source_search_url(row.source, row.rjcode))
            row.checked_at = now
            row.next_probe_at = self._next_probe_at(status, now)
            row.lease_until = None
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.last_error_code = "" if status in {"hit", "miss"} else str(payload.get("error_code") or status)[:80]
            db.commit()
            return {
                "id": str(row.id),
                "source": row.source,
                "rjcode": row.rjcode,
                "status": row.status,
                "updated_at": row.updated_at.isoformat() if row.updated_at else now.isoformat(),
            }
        except Exception:
            db.rollback()
            logger.warning("[社团补全·外部搜索] 写入持久搜索结果失败 id=%s", record_id, exc_info=True)
            return None
        finally:
            db.close()

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_stop_event = asyncio.Event()
        self._worker_task = asyncio.create_task(self._run_workers(), name="circle-external-search-worker")

    async def stop(self) -> None:
        task = self._worker_task
        if self._worker_stop_event:
            self._worker_stop_event.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))
        self._clients.clear()
        self._worker_task = None
        self._worker_stop_event = None

    @staticmethod
    def _source_ready(source: str) -> bool:
        config = get_config().circle_external_search
        return bool(getattr(config, source + "_enabled", True)) and (
            source != "south_plus" or bool(str(getattr(config, "south_plus_cookie", "") or "").strip()))

    async def _run_workers(self) -> None:
        tasks = [asyncio.create_task(self._worker_loop(source))
                 for source in ("anime_share", "anime_share", "south_plus")]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _worker_loop(self, source: str) -> None:
        while self._worker_stop_event and not self._worker_stop_event.is_set():
            claimed = await asyncio.to_thread(self._claim_next_record, source) if self._source_ready(source) and not self._source_backoff(source) else None
            if claimed is None:
                try:
                    await asyncio.wait_for(self._worker_stop_event.wait(), timeout=self._WORKER_IDLE_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue
            payload = await self._fetch_source(claimed["source"], claimed["rjcode"])
            completed = await asyncio.to_thread(self._complete_record, claimed["id"], payload)
            if completed is None:
                continue
            try:
                from .realtime_event_service import broadcast_event

                broadcast_event({
                    "type": "circle.external_search.changed",
                    "reason": "probe_completed",
                    "id": completed["id"],
                    "domain": "circle_completion",
                    "status": completed["status"],
                    "payload": completed,
                })
            except Exception:
                logger.debug("[社团补全·外部搜索] 广播搜索结果更新失败", exc_info=True)

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
        """读取当前页的持久快照，并为缺失或到期项安排后台探测。"""
        unique_codes = []
        for variants in variants_by_canonical.values():
            for variant in variants:
                rjcode = self._normalize_rjcode(variant.get("rjcode"))
                if rjcode and rjcode not in unique_codes:
                    unique_codes.append(rjcode)

        lookup_keys = [
            (source, rjcode)
            for source in ("anime_share", "south_plus")
            for rjcode in unique_codes
        ]
        lookups = await asyncio.to_thread(self._load_or_enqueue_records, lookup_keys)

        items: Dict[str, Any] = {}
        for canonical, variants in variants_by_canonical.items():
            source_payloads: Dict[str, Any] = {}
            for source in ("anime_share", "south_plus"):
                backoff = self._source_backoff(source)
                entries: List[Dict[str, str]] = []
                search_entries: List[Dict[str, str]] = []
                error_codes = set()
                statuses = []
                for variant in variants:
                    rjcode = self._normalize_rjcode(variant.get("rjcode"))
                    if not rjcode:
                        continue
                    payload = lookups.get((source, rjcode), {
                        "status": "pending",
                        "results": [],
                        "search_url": self._source_search_url(source, rjcode),
                    })
                    if backoff and payload.get("status") != "hit":
                        payload = {**payload, "status": "unavailable", "error_code": backoff}
                    statuses.append(str(payload.get("status") or "error"))
                    if payload.get("error_code"):
                        error_codes.add(str(payload["error_code"]))
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
                elif "pending" in statuses:
                    status = "pending"
                else:
                    status = "unavailable" if "unavailable" in statuses else "error"
                source_payloads[source] = {
                    "status": status,
                    "results": entries,
                    "search_results": search_entries,
                    "error_codes": sorted(error_codes),
                }
            items[str(canonical)] = source_payloads
        return {"items": items}


_service: CircleExternalSearchService | None = None


def get_circle_external_search_service() -> CircleExternalSearchService:
    global _service
    if _service is None:
        _service = CircleExternalSearchService()
    return _service
