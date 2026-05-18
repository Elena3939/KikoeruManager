"""社团补全封面缓存服务。

负责把社团索引里出现的封面图（默认来自 DLsite 公开 CDN）下载到本地
``data/img/`` 目录，让前端不用每次都跨网请求 dlsite，避免代理 / 网络抖动
导致的图片 broken。

设计要点：

- 单例：通过 ``get_circle_image_cache_service()`` 获取。
- 文件命名：卡片图 ``{RJxxxxxx}.jpg``，列表小图 ``{RJxxxxxx}_sam.jpg``。
- 写入用 ``.tmp`` 中间文件 + ``replace`` 原子化，避免半成品文件被前端读到。
- 并发：``download_many`` 用 ``Semaphore(8)``，对 dlsite CDN 友好且足够快。
- 空文件保护：``has_local`` 必须 size > 0 才算命中，否则会被当作丢失重新下载。
- 复用 dlsite 代理配置：从 ``config.metadata.http_proxy`` 拿，与 DLsite 服务一致。
- 失败不抛异常：所有错误只 log warning / debug，由调用方决定是否 fallback 到远程 URL。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


_RJCODE_PATTERN = re.compile(r"[RVB]J\d{6,8}")


class CircleImageCacheService:
    """封面缓存服务（单例）。"""

    DEFAULT_CONCURRENCY = 8
    CONNECT_TIMEOUT = 10.0
    READ_TIMEOUT = 15.0
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB，DLsite 240x240 缩略图通常 < 50KB
    URL_PATH_PREFIX = "/api/circle-completion/cover/"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock: Optional[asyncio.Lock] = None
        self._cache_dir: Optional[Path] = None

    # ------------------------------------------------------------------
    # 路径 / 命名
    # ------------------------------------------------------------------

    @property
    def cache_dir(self) -> Path:
        """返回封面缓存目录（``data/img/``），首次访问时按需创建。"""
        if self._cache_dir is None:
            from ..models.database import get_db_path

            db_path = get_db_path()
            cache_dir = Path(db_path).parent / "img"
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.warning(
                    "[社团补全/封面缓存] 创建缓存目录失败 path=%s", cache_dir, exc_info=True
                )
            self._cache_dir = cache_dir
        return self._cache_dir

    @staticmethod
    def normalize_rjcode(value: Any) -> str:
        text = str(value or "").strip().upper()
        match = _RJCODE_PATTERN.search(text)
        return match.group(0) if match else ""

    @staticmethod
    def _normalize_variant(variant: str = "card") -> str:
        value = str(variant or "card").strip().lower()
        return "list" if value in {"list", "sam", "thumb", "thumbnail"} else "card"

    def _filename_for(self, rjcode: str, variant: str = "card") -> str:
        normalized = self.normalize_rjcode(rjcode)
        if not normalized:
            return ""
        if self._normalize_variant(variant) == "list":
            return f"{normalized}_sam.jpg"
        return f"{normalized}.jpg"

    def get_local_path(self, rjcode: str, variant: str = "card") -> Optional[Path]:
        filename = self._filename_for(rjcode, variant)
        if not filename:
            return None
        return self.cache_dir / filename

    def has_local(self, rjcode: str, variant: str = "card") -> bool:
        path = self.get_local_path(rjcode, variant)
        if path is None:
            return False
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def get_local_url(self, rjcode: str, variant: str = "card") -> str:
        """如果本地有缓存，返回前端可访问的 API 路径，否则返回空。"""
        if self.has_local(rjcode, variant):
            return f"{self.URL_PATH_PREFIX}{self._filename_for(rjcode, variant)}"
        return ""

    def resolve_display_url(self, rjcode: Any, fallback_url: Any = "", variant: str = "card") -> str:
        """优先返回本地 API URL，本地无则返回 fallback（通常是 dlsite 远程 URL）。"""
        local = self.get_local_url(str(rjcode or ""), variant)
        if local:
            return local
        return str(fallback_url or "")

    def resolve_filename(self, filename: str) -> Optional[Path]:
        """供 API 路由使用：将外部传入的文件名映射回缓存目录下的真实路径。

        会做严格白名单校验，只允许 ``RJ\\d{6,8}.jpg``，避免 ``../`` 路径穿越。
        """

        candidate = str(filename or "").strip()
        if not candidate or "/" in candidate or "\\" in candidate:
            return None
        match = re.fullmatch(r"([RVB]J\d{6,8})(?:_(sam))?\.(?:jpg|jpeg)", candidate, re.IGNORECASE)
        if not match:
            return None
        rjcode = match.group(1).upper()
        variant = "list" if match.group(2) else "card"
        return self.get_local_path(rjcode, variant)

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------

    def _ensure_lock(self) -> asyncio.Lock:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        return self._client_lock

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._ensure_lock():
            if self._client is None or self._client.is_closed:
                from ..config.settings import get_config

                config = get_config()
                proxy_url = ""
                try:
                    raw_proxy = getattr(config.metadata, "http_proxy", "") or ""
                    if raw_proxy:
                        from .dlsite_service import get_dlsite_service

                        proxy_url = get_dlsite_service()._normalize_proxy_url(raw_proxy) or ""
                except Exception:
                    proxy_url = ""

                client_kwargs: Dict[str, Any] = {
                    "headers": {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        "Referer": "https://www.dlsite.com/",
                    },
                    "timeout": httpx.Timeout(
                        connect=self.CONNECT_TIMEOUT,
                        read=self.READ_TIMEOUT,
                        write=10.0,
                        pool=None,
                    ),
                    "verify": False,
                    "follow_redirects": True,
                    "limits": httpx.Limits(
                        max_connections=self.DEFAULT_CONCURRENCY,
                        max_keepalive_connections=4,
                    ),
                    "http2": False,
                }
                if proxy_url:
                    async_client_params = inspect.signature(
                        httpx.AsyncClient.__init__
                    ).parameters
                    if "proxy" in async_client_params:
                        client_kwargs["proxy"] = proxy_url
                    elif "proxies" in async_client_params:
                        client_kwargs["proxies"] = {
                            "http://": proxy_url,
                            "https://": proxy_url,
                        }

                self._client = httpx.AsyncClient(**client_kwargs)
            return self._client

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                logger.debug("[社团补全/封面缓存] 关闭 HTTP 客户端失败", exc_info=True)

    async def download_one(
        self,
        rjcode: str,
        source_url: str,
        *,
        variant: str = "card",
        force: bool = False,
    ) -> bool:
        """下载单张封面到本地，返回是否成功（已存在算成功）。"""

        normalized = self.normalize_rjcode(rjcode)
        if not normalized:
            return False
        url = str(source_url or "").strip()
        if not url.startswith(("http://", "https://")):
            return False

        target_path = self.get_local_path(normalized, variant)
        if target_path is None:
            return False
        if not force and target_path.is_file():
            try:
                if target_path.stat().st_size > 0:
                    return True
            except OSError:
                pass

        tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            client = await self._get_client()
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.debug(
                        "[社团补全/封面缓存] 下载失败 rjcode=%s status=%s url=%s",
                        normalized,
                        response.status_code,
                        url,
                    )
                    return False

                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    declared = int(content_length)
                    if declared > self.MAX_FILE_SIZE:
                        logger.warning(
                            "[社团补全/封面缓存] 跳过过大封面 rjcode=%s declared_size=%s",
                            normalized,
                            declared,
                        )
                        return False

                downloaded = 0
                # 用 with open 同步写文件即可，httpx aiter_bytes 的 chunk 已经在内存里
                with tmp_path.open("wb") as fp:
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > self.MAX_FILE_SIZE:
                            raise RuntimeError(
                                f"封面超过最大尺寸 {self.MAX_FILE_SIZE}"
                            )
                        fp.write(chunk)

                if downloaded == 0:
                    raise RuntimeError("封面下载内容为空")

            # 原子替换：DLsite 偶尔 200 但内容是 1x1 的占位图；这里只防 0 字节，
            # 真要更严还能加 PIL 校验，目前没必要。
            try:
                tmp_path.replace(target_path)
            except OSError:
                # Windows 上偶发，先 unlink 再 rename
                if target_path.exists():
                    target_path.unlink()
                tmp_path.replace(target_path)
            return True
        except Exception as exc:
            logger.debug(
                "[社团补全/封面缓存] 下载异常 rjcode=%s url=%s err=%s",
                normalized,
                url,
                exc,
            )
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False

    async def download_many(
        self,
        items: Iterable[Tuple[Any, Any]],
        *,
        variant: str = "card",
        concurrency: int = DEFAULT_CONCURRENCY,
        force: bool = False,
    ) -> Dict[str, bool]:
        """批量并发下载封面。

        - ``items`` 为 ``[(rjcode, source_url), ...]``，rjcode 已经去重无所谓，
          函数内部会按 normalized rjcode 再去一次重，已存在的也会被快速 short-circuit。
        - 失败不抛异常，结果以 ``{rjcode: bool}`` 返回，可用于 metric。
        """

        variant = self._normalize_variant(variant)
        seen: Set[str] = set()
        deduped: List[Tuple[str, str]] = []
        for raw_rjcode, raw_url in items or []:
            normalized = self.normalize_rjcode(raw_rjcode)
            if not normalized or normalized in seen:
                continue
            url = str(raw_url or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            seen.add(normalized)
            deduped.append((normalized, url))

        results: Dict[str, bool] = {}
        if not deduped:
            return results

        semaphore = asyncio.Semaphore(max(1, int(concurrency or self.DEFAULT_CONCURRENCY)))

        async def _run(rjcode: str, url: str) -> Tuple[str, bool]:
            if not force and self.has_local(rjcode, variant):
                return rjcode, True
            async with semaphore:
                ok = await self.download_one(rjcode, url, variant=variant, force=force)
                return rjcode, ok

        for future in asyncio.as_completed([_run(r, u) for r, u in deduped]):
            try:
                rjcode, ok = await future
            except Exception:
                logger.debug("[社团补全/封面缓存] 批量下载子任务异常", exc_info=True)
                continue
            results[rjcode] = ok
        return results


_service_instance: Optional[CircleImageCacheService] = None


def get_circle_image_cache_service() -> CircleImageCacheService:
    """获取全局封面缓存服务单例。"""

    global _service_instance
    if _service_instance is None:
        _service_instance = CircleImageCacheService()
    return _service_instance
