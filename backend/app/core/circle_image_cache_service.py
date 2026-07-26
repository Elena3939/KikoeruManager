"""社团补全封面缓存服务。

负责把社团索引里出现的封面图（默认来自 DLsite 公开 CDN）下载到本地
``data/img/`` 目录，让前端不用每次都跨网请求 dlsite，避免代理 / 网络抖动
导致的图片 broken。

设计要点：

- 单例：通过 ``get_circle_image_cache_service()`` 获取。
- 文件命名：卡片图 ``{RJxxxxxx}.jpg``，列表小图 ``{RJxxxxxx}_sam.jpg``。
- 写入用 ``.tmp`` 中间文件 + ``replace`` 原子化，避免半成品文件被前端读到。
- 并发：批量预热与按需下载共享受控的 ``Semaphore(6)``，避免一批缺图同时占满
  连接池导致排队请求把总超时预算耗尽。
- 空文件保护：``has_local`` 必须 size > 0 才算命中，否则会被当作丢失重新下载。
- 复用 dlsite 代理配置：从 ``config.metadata.http_proxy`` 拿，与 DLsite 服务一致。
- 失败不抛异常：所有错误只 log warning / debug，由调用方展示占位图或提供重试。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


_RJCODE_PATTERN = re.compile(r"[RVB]J\d{6,8}")


class CircleImageCacheService:
    """封面缓存服务（单例）。"""

    DEFAULT_CONCURRENCY = 6
    CONNECT_TIMEOUT = 10.0
    READ_TIMEOUT = 15.0
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB，DLsite 240x240 缩略图通常 < 50KB
    URL_PATH_PREFIX = "/api/circle-completion/cover/"
    MAX_TRANSIENT_RETRIES = 1
    RETRY_DELAY_SECONDS = 0.4
    ON_DEMAND_TOTAL_TIMEOUT_SECONDS = 12.0
    FAILURE_COOLDOWN_SECONDS = 45.0
    MAX_FAILURE_CACHE_ENTRIES = 1024

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._client_proxy_url: str = ""
        self._client_lock: Optional[asyncio.Lock] = None
        self._cache_dir: Optional[Path] = None
        self._download_locks: Dict[str, asyncio.Lock] = {}
        self._background_download_tasks: Dict[str, asyncio.Task] = {}
        self._failed_until: Dict[str, float] = {}
        self._download_semaphore: Optional[asyncio.Semaphore] = None

    # ------------------------------------------------------------------
    # 路径 / 命名
    # ------------------------------------------------------------------

    @property
    def cache_dir(self) -> Path:
        """返回封面缓存目录（``data/img/``），首次访问时按需创建。"""
        if self._cache_dir is None:
            from ..config.settings import get_config_file_path

            data_path = str(os.environ.get("DATA_PATH") or "").strip()
            if data_path:
                data_dir = Path(data_path).resolve()
            else:
                config_path = Path(get_config_file_path()).resolve()
                data_dir = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
            cache_dir = data_dir / "img"
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info("[社团补全/封面缓存] 使用缓存目录 path=%s", cache_dir)
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
    def extract_image_rjcode(value: Any) -> str:
        """从 DLsite 图片 URL 里取真实作品 RJ。

        图片路径通常同时包含目录 RJ bucket 和文件名 RJ：
        ``.../RJ01202000/RJ01201316_img_sam.jpg``。用于缓存文件名时必须取最后一个。
        """
        matches = _RJCODE_PATTERN.findall(str(value or "").strip().upper())
        return matches[-1] if matches else ""

    def cache_rjcode_for_url(self, source_url: Any, fallback_rjcode: Any = "") -> str:
        """返回封面实际文件名对应的缓存键。

        DLsite 图片 URL 同时包含目录 bucket 与图片所属作品 RJ。缓存键必须使用
        URL 最后的作品 RJ，而不能使用当前展示的翻译版本 RJ；否则写入和读取会
        落在两个不同文件名下。
        """

        return self.extract_image_rjcode(source_url) or self.normalize_rjcode(fallback_rjcode)

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

    def _get_download_semaphore(self) -> asyncio.Semaphore:
        """限制真实 CDN 传输并发；队列等待不计入单张下载超时。"""
        if self._download_semaphore is None:
            self._download_semaphore = asyncio.Semaphore(self.DEFAULT_CONCURRENCY)
        return self._download_semaphore

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

    def get_local_url(self, rjcode: str, variant: str = "card", *, allow_missing: bool = False) -> str:
        """返回前端可访问的本地缓存 API 路径。

        默认只在文件已存在时返回；社团补全卡片列表会传 ``allow_missing=True``，
        让首屏直接打本地 cover API，缺图时由 API 做一次按需下载并落盘。
        """
        filename = self._filename_for(rjcode, variant)
        if filename and (allow_missing or self.has_local(rjcode, variant)):
            return f"{self.URL_PATH_PREFIX}{filename}"
        return ""

    def resolve_display_url(self, rjcode: Any, fallback_url: Any = "", variant: str = "card") -> str:
        """优先返回本地 API URL，本地无则返回 fallback（通常是 dlsite 远程 URL）。"""
        local = self.get_local_url(str(rjcode or ""), variant)
        if local:
            return local
        return str(fallback_url or "")

    def restore_from_legacy_alias(
        self,
        target_rjcode: Any,
        aliases: Iterable[Any],
        *,
        variant: str = "card",
    ) -> Optional[Path]:
        """把历史上按展示 RJ 写入的缓存补到图片实际 RJ 名下。

        旧版本把翻译版 ``display_rjcode`` 当作缓存文件名，而视图读取使用
        图片 URL 中的原作 RJ。这里仅在目标文件缺失时从已存在的旧别名流式复制，
        通过原子替换落盘，不触发网络请求，也不删除原文件。
        """

        target = self.get_local_path(str(target_rjcode or ""), variant)
        if target is None or self.has_local(str(target_rjcode or ""), variant):
            return target

        normalized_target = self.normalize_rjcode(target_rjcode)
        for raw_alias in aliases or []:
            alias = self.normalize_rjcode(raw_alias)
            if not alias or alias == normalized_target:
                continue
            source = self.get_local_path(alias, variant)
            if source is None:
                continue
            try:
                if not source.is_file() or source.stat().st_size <= 0:
                    continue
            except OSError:
                continue

            tmp_path: Optional[Path] = None
            try:
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    dir=str(target.parent),
                )
                tmp_path = Path(tmp_name)
                copied = 0
                with os.fdopen(fd, "wb") as target_fp:
                    with source.open("rb") as source_fp:
                        while chunk := source_fp.read(64 * 1024):
                            copied += len(chunk)
                            target_fp.write(chunk)
                if copied <= 0:
                    raise OSError("历史封面缓存为空")
                if target.is_file() and target.stat().st_size > 0:
                    return target
                os.replace(tmp_path, target)
                tmp_path = None
                logger.info(
                    "[社团补全/封面缓存] 已修复历史别名 target=%s alias=%s variant=%s",
                    normalized_target,
                    alias,
                    self._normalize_variant(variant),
                )
                return target
            except OSError:
                logger.warning(
                    "[社团补全/封面缓存] 修复历史别名失败 target=%s alias=%s variant=%s",
                    normalized_target,
                    alias,
                    self._normalize_variant(variant),
                    exc_info=True,
                )
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        return target

    def _parse_filename(self, filename: str) -> Tuple[str, str]:
        candidate = str(filename or "").strip()
        if not candidate or "/" in candidate or "\\" in candidate:
            return "", ""
        match = re.fullmatch(r"([RVB]J\d{6,8})(?:_(sam))?\.(?:jpg|jpeg)", candidate, re.IGNORECASE)
        if not match:
            return "", ""
        return match.group(1).upper(), "list" if match.group(2) else "card"

    def _failure_key(self, rjcode: str, variant: str) -> str:
        return self._filename_for(rjcode, variant)

    def _download_lock_for(self, rjcode: str, variant: str) -> Optional[asyncio.Lock]:
        key = self._filename_for(rjcode, variant)
        if not key:
            return None
        lock = self._download_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._download_locks[key] = lock
        return lock

    def _is_in_failure_cooldown(self, rjcode: str, variant: str) -> bool:
        key = self._failure_key(rjcode, variant)
        if not key:
            return False
        until = self._failed_until.get(key, 0.0)
        if until <= time.monotonic():
            self._failed_until.pop(key, None)
            return False
        return True

    def _remember_failure(self, rjcode: str, variant: str) -> None:
        key = self._failure_key(rjcode, variant)
        if not key:
            return
        now = time.monotonic()
        if len(self._failed_until) >= self.MAX_FAILURE_CACHE_ENTRIES:
            for cached_key, until in list(self._failed_until.items()):
                if until <= now:
                    self._failed_until.pop(cached_key, None)
            if len(self._failed_until) >= self.MAX_FAILURE_CACHE_ENTRIES:
                oldest_key = min(self._failed_until, key=self._failed_until.get)
                self._failed_until.pop(oldest_key, None)
        self._failed_until[key] = now + self.FAILURE_COOLDOWN_SECONDS

    def _clear_failure(self, rjcode: str, variant: str) -> None:
        key = self._failure_key(rjcode, variant)
        if key:
            self._failed_until.pop(key, None)

    def resolve_filename(self, filename: str) -> Optional[Path]:
        """供 API 路由使用：将外部传入的文件名映射回缓存目录下的真实路径。

        会做严格白名单校验，只允许 ``RJ\\d{6,8}.jpg``，避免 ``../`` 路径穿越。
        """

        rjcode, variant = self._parse_filename(filename)
        if not rjcode:
            return None
        return self.get_local_path(rjcode, variant)

    @staticmethod
    def _dlsite_folder_for(rjcode: str) -> str:
        match = re.fullmatch(r"[RVB]J(\d{6}|\d{8})", str(rjcode or "").strip().upper())
        if not match:
            return ""
        digits = match.group(1)
        folder_upper = (int(digits) // 1000 + 1) * 1000
        return f"RJ{folder_upper:08d}" if len(digits) == 8 else f"RJ{folder_upper:06d}"

    def _candidate_source_urls(self, rjcode: str, variant: str) -> List[str]:
        normalized = self.normalize_rjcode(rjcode)
        folder = self._dlsite_folder_for(normalized)
        if not normalized or not folder:
            return []
        work_base = f"https://img.dlsite.jp/modpub/images2/work/doujin/{folder}/{normalized}"
        work_resize = f"https://img.dlsite.jp/resize/images2/work/doujin/{folder}/{normalized}"
        announce_base = f"https://img.dlsite.jp/modpub/images2/announce/doujin/{folder}/{normalized}"
        announce_resize = f"https://img.dlsite.jp/resize/images2/announce/doujin/{folder}/{normalized}"
        ana_base = f"https://img.dlsite.jp/modpub/images2/ana/doujin/{folder}/{normalized}"
        if self._normalize_variant(variant) == "list":
            return [
                f"{work_base}_img_sam.jpg",
                f"{work_resize}_img_main_240x240.jpg",
                f"{work_base}_img_main.jpg",
                f"{ana_base}_ana_img_main.jpg",
                f"{announce_resize}_img_main_240x240.jpg",
                f"{announce_base}_img_main.jpg",
            ]
        return [
            f"{work_resize}_img_main_240x240.jpg",
            f"{work_base}_img_main.jpg",
            f"{work_base}_img_sam.jpg",
            f"{announce_resize}_img_main_240x240.jpg",
            f"{announce_base}_img_main.jpg",
            f"{ana_base}_ana_img_main.jpg",
        ]

    async def ensure_local_for_filename(
        self,
        filename: str,
        *,
        force: bool = False,
        log_failure: bool = True,
    ) -> Optional[Path]:
        """按需下载并返回本地缓存路径。

        用于前端首屏直接请求 ``/api/circle-completion/cover/RJxxxx_sam.jpg`` 的场景：
        文件已存在时只走本地磁盘；文件缺失时按 RJ 推导 DLsite CDN 地址下载一次。
        """

        rjcode, variant = self._parse_filename(filename)
        if not rjcode:
            return None
        target = self.get_local_path(rjcode, variant)
        if target is None:
            return None
        if self.has_local(rjcode, variant):
            return target
        if not force and self._is_in_failure_cooldown(rjcode, variant):
            logger.debug(
                "[社团补全/封面缓存] 命中失败冷却 rjcode=%s variant=%s",
                rjcode,
                variant,
            )
            return None

        lock = self._download_lock_for(rjcode, variant)
        if lock is None:
            return None
        async with lock:
            if self.has_local(rjcode, variant):
                return target
            if not force and self._is_in_failure_cooldown(rjcode, variant):
                return None
            failures: List[str] = []
            try:
                # 先进入全局下载闸门，再开始计算单张网络超时；连接池排队不能算作
                # 当前 RJ 的下载失败。批量预热与按需下载共用该预算，避免互相打满。
                async with self._get_download_semaphore():
                    async with asyncio.timeout(self.ON_DEMAND_TOTAL_TIMEOUT_SECONDS):
                        for source_url in self._candidate_source_urls(rjcode, variant):
                            ok, outcome, retryable = await self._download_with_outcome(
                                rjcode,
                                source_url,
                                variant=variant,
                            )
                            if ok:
                                self._clear_failure(rjcode, variant)
                                return target if self.has_local(rjcode, variant) else None
                            if outcome:
                                failures.append(outcome)
                            # 同一 CDN 的传输异常通常意味着网络或代理暂时不可用；继续穷举
                            # 同域候选只会把首屏卡成几十秒，直接进入短冷却即可。
                            if retryable:
                                break
            except TimeoutError:
                failures.append("total-timeout")
            self._remember_failure(rjcode, variant)
            log = logger.warning if log_failure else logger.debug
            log(
                "[社团补全/封面缓存] 按需下载失败 rjcode=%s variant=%s outcomes=%s deadline_seconds=%s cooldown_seconds=%s",
                rjcode,
                variant,
                ",".join(failures) or "unknown",
                int(self.ON_DEMAND_TOTAL_TIMEOUT_SECONDS),
                int(self.FAILURE_COOLDOWN_SECONDS),
            )
            return None

    async def fetch_local_for_rjcode(
        self,
        rjcode: str,
        *,
        variant: str = "card",
        force: bool = False,
    ) -> Optional[Path]:
        """立即补齐指定 RJ 的本地封面缓存。

        只根据 RJ 推导 DLsite CDN 候选地址，不接收外部 URL，避免把这个交互入口
        变成服务端请求任意地址的通道。手动补图可跳过短失败冷却。
        """

        normalized = self.normalize_rjcode(rjcode)
        filename = self._filename_for(normalized, variant)
        if not filename:
            return None
        return await self.ensure_local_for_filename(filename, force=force)

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------

    def _ensure_lock(self) -> asyncio.Lock:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        return self._client_lock

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._ensure_lock():
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

            if (
                self._client is not None
                and not self._client.is_closed
                and self._client_proxy_url != proxy_url
            ):
                logger.info(
                    "[社团补全/封面缓存] 元数据代理已变更，重建 HTTP 客户端: %s",
                    proxy_url or "直连",
                )
                await self._client.aclose()
                self._client = None
                self._client_proxy_url = ""

            if self._client is None or self._client.is_closed:

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
                self._client_proxy_url = proxy_url
            return self._client

    async def close(self) -> None:
        for task in list(self._background_download_tasks.values()):
            if not task.done():
                task.cancel()
        self._background_download_tasks.clear()
        client = self._client
        self._client = None
        self._client_proxy_url = ""
        if client and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                logger.debug("[社团补全/封面缓存] 关闭 HTTP 客户端失败", exc_info=True)
        self._download_semaphore = None

    def schedule_download(
        self,
        rjcode: str,
        source_url: str,
        *,
        variant: str = "card",
        force: bool = False,
    ) -> Optional[asyncio.Task]:
        """将非关键封面下载放到受控后台，不阻塞邮件等业务主链路。"""

        normalized = self.cache_rjcode_for_url(source_url, rjcode)
        if not normalized:
            return None
        task_key = self._filename_for(normalized, variant)
        if not task_key:
            return None
        existing = self._background_download_tasks.get(task_key)
        if existing and not existing.done():
            return existing

        async def _runner() -> None:
            try:
                await self.download_one(normalized, source_url, variant=variant, force=force)
            except Exception:
                logger.warning(
                    "[社团补全/封面缓存] 后台下载异常 rjcode=%s variant=%s",
                    normalized,
                    self._normalize_variant(variant),
                    exc_info=True,
                )
            finally:
                current = asyncio.current_task()
                if self._background_download_tasks.get(task_key) is current:
                    self._background_download_tasks.pop(task_key, None)

        try:
            task = asyncio.create_task(_runner(), name=f"circle-cover-download:{task_key}")
        except RuntimeError:
            logger.debug(
                "[社团补全/封面缓存] 当前无运行事件循环，跳过后台下载 rjcode=%s",
                normalized,
            )
            return None
        self._background_download_tasks[task_key] = task
        return task

    def schedule_ensure_for_filename(self, filename: str) -> Optional[asyncio.Task]:
        """后台补齐缺失封面；同一文件只保留一个在途任务。"""

        rjcode, variant = self._parse_filename(filename)
        if not rjcode or self.has_local(rjcode, variant):
            return None
        task_key = self._filename_for(rjcode, variant)
        if not task_key:
            return None
        existing = self._background_download_tasks.get(task_key)
        if existing and not existing.done():
            return existing

        async def _runner() -> None:
            try:
                # 页面首次加载的缺图属于后台预热，失败后仍可由用户主动重试；
                # 不应让短暂 CDN 抖动把日志面板刷成一屏 WARN。
                await self.ensure_local_for_filename(filename, log_failure=False)
            except Exception:
                logger.warning(
                    "[社团补全/封面缓存] 后台按需下载异常 filename=%s",
                    filename,
                    exc_info=True,
                )
            finally:
                current = asyncio.current_task()
                if self._background_download_tasks.get(task_key) is current:
                    self._background_download_tasks.pop(task_key, None)

        try:
            task = asyncio.create_task(_runner(), name=f"circle-cover-ensure:{task_key}")
        except RuntimeError:
            return None
        self._background_download_tasks[task_key] = task
        return task

    async def _download_once(
        self,
        rjcode: str,
        source_url: str,
        *,
        variant: str = "card",
    ) -> Tuple[bool, str, bool]:
        """执行一次下载，返回 ``成功 / 诊断 / 是否为瞬态失败``。"""

        normalized = self.cache_rjcode_for_url(source_url, rjcode)
        if not normalized:
            return False, "invalid-rjcode", False
        url = str(source_url or "").strip()
        if not url.startswith(("http://", "https://")):
            return False, "invalid-url", False

        target_path = self.get_local_path(normalized, variant)
        if target_path is None:
            return False, "invalid-target", False

        tmp_path: Optional[Path] = None
        try:
            client = await self._get_client()
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    status = int(response.status_code)
                    return False, f"status={status}", status == 429 or status >= 500

                content_type = str(response.headers.get("Content-Type") or "").lower()
                if content_type and not content_type.startswith("image/"):
                    return False, f"content-type={content_type[:40]}", False

                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    declared = int(content_length)
                    if declared > self.MAX_FILE_SIZE:
                        logger.warning(
                            "[社团补全/封面缓存] 跳过过大封面 rjcode=%s declared_size=%s",
                            normalized,
                            declared,
                        )
                        return False, "declared-too-large", False

                downloaded = 0
                # 用唯一临时文件 + 原子 replace，避免并发下载同一封面时互相覆盖。
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{target_path.name}.",
                    suffix=".tmp",
                    dir=target_path.parent,
                    delete=False,
                ) as fp:
                    tmp_path = Path(fp.name)
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

            # 原子替换不删除已有目标；另一并发请求或读者始终只会看到完整文件。
            os.replace(tmp_path, target_path)
            tmp_path = None
            return True, "", False
        except httpx.TransportError as exc:
            return False, type(exc).__name__, True
        except Exception as exc:
            return False, type(exc).__name__, False
        finally:
            try:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    async def _download_with_outcome(
        self,
        rjcode: str,
        source_url: str,
        *,
        variant: str = "card",
    ) -> Tuple[bool, str, bool]:
        """对瞬态网络错误执行有限重试，避免封面请求无限占用首屏。"""

        outcome = "unknown"
        retryable = False
        for attempt in range(self.MAX_TRANSIENT_RETRIES + 1):
            ok, outcome, retryable = await self._download_once(
                rjcode,
                source_url,
                variant=variant,
            )
            if ok or not retryable or attempt >= self.MAX_TRANSIENT_RETRIES:
                return ok, outcome, retryable
            await asyncio.sleep(self.RETRY_DELAY_SECONDS * (attempt + 1))
        return False, outcome, retryable

    async def download_one(
        self,
        rjcode: str,
        source_url: str,
        *,
        variant: str = "card",
        force: bool = False,
    ) -> bool:
        """下载单张封面到本地，返回是否成功（已存在算成功）。"""

        url = str(source_url or "").strip()
        normalized = self.cache_rjcode_for_url(url, rjcode)
        if not normalized or not url.startswith(("http://", "https://")):
            return False
        lock = self._download_lock_for(normalized, variant)
        if lock is None:
            return False
        async with lock:
            if not force and self.has_local(normalized, variant):
                self._clear_failure(normalized, variant)
                return True

            async with self._get_download_semaphore():
                ok, outcome, _ = await self._download_with_outcome(
                    normalized,
                    url,
                    variant=variant,
                )
            if ok:
                self._clear_failure(normalized, variant)
                return True
            logger.debug(
                "[社团补全/封面缓存] 下载失败 rjcode=%s variant=%s outcome=%s",
                normalized,
                self._normalize_variant(variant),
                outcome,
            )
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

        - ``items`` 为 ``[(rjcode, source_url), ...]``；缓存键优先取 source URL 中的
          实际图片 RJ，避免翻译版展示 RJ 与原图 RJ 不一致时写错文件名。
        - 函数内部会按真实缓存键去重，已存在的也会被快速 short-circuit。
        - 失败不抛异常，结果以 ``{rjcode: bool}`` 返回，可用于 metric。
        """

        variant = self._normalize_variant(variant)
        seen: Set[str] = set()
        deduped: List[Tuple[str, str]] = []
        for raw_rjcode, raw_url in items or []:
            url = str(raw_url or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            normalized = self.cache_rjcode_for_url(url, raw_rjcode)
            if not normalized or normalized in seen:
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
