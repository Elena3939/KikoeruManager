from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipResponder, IdentityResponder
from starlette.responses import FileResponse as StarletteFileResponse
from starlette.staticfiles import NotModifiedResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, text
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import base64
import copy
import concurrent.futures
from collections import defaultdict, deque
import contextlib
import functools
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import sys
import time
from urllib.parse import quote, unquote, urlencode, urlsplit
import html
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import traceback
from types import SimpleNamespace
import uuid
import yaml

# Create logger instance
logger = logging.getLogger(__name__)

_SYSTEM_STORAGE_INFO_CACHE: Dict[str, Any] = {"key": None, "expires_at": 0.0, "payload": None}
_LIBRARY_STORAGE_INFO_CACHE: Dict[str, Dict[str, Any]] = {}
_STORAGE_INFO_TTL_SECONDS = 60.0
_LIBRARY_STORAGE_INFO_STALE_TIMEOUT_SECONDS = 0.35
_LIBRARY_STORAGE_INFO_COLD_TIMEOUT_SECONDS = 2.0
_LIBRARY_STORAGE_INFO_REFRESH_TASKS: Dict[str, asyncio.Task] = {}
_BATCH_API_RENAME_INFLIGHT: Dict[str, asyncio.Task] = {}
_DOWNLOAD_STATUS_CACHE_TTL_SECONDS = 1.0
_DOWNLOAD_STATUS_CACHE: Dict[str, Dict[str, Any]] = {}
_EVENT_LOOP_WATCHDOG_TASK: Optional[asyncio.Task] = None
_EVENT_LOOP_WATCHDOG_THREAD: Optional[threading.Thread] = None
_EVENT_LOOP_WATCHDOG_STOP_EVENT: Optional[threading.Event] = None
_EVENT_LOOP_WATCHDOG_LAST_BEAT = time.monotonic()
_LOG_IO_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_LOG_SEARCH_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_LOG_IO_EXECUTOR_LOCK = threading.Lock()
_LOG_STREAM_ACTIVE_COUNT = 0
_LOG_STREAM_TOTAL_CONNECTIONS = 0
_LOG_STREAM_DROPPED_COUNT = 0
_LOG_STREAM_STATUS_LOCK = threading.Lock()


def _env_float(name: str, default: float, *, min_value: float = 0.1, max_value: float = 3600.0) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, min_value), max_value)


def _format_all_thread_stacks() -> str:
    frames = sys._current_frames()
    lines: List[str] = []
    for thread in threading.enumerate():
        lines.append(f"\n--- thread name={thread.name} ident={thread.ident} daemon={thread.daemon} ---")
        frame = frames.get(thread.ident)
        if frame is None:
            lines.append("<no python frame>")
            continue
        lines.extend(traceback.format_stack(frame))
    return "".join(lines)


async def _event_loop_watchdog_loop() -> None:
    interval = _env_float("KIKOERUMANAGER_EVENT_LOOP_WATCHDOG_INTERVAL", 1.0, min_value=0.2, max_value=60.0)
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval
    global _EVENT_LOOP_WATCHDOG_LAST_BEAT
    _EVENT_LOOP_WATCHDOG_LAST_BEAT = time.monotonic()
    while True:
        await asyncio.sleep(interval)
        now = loop.time()
        lag = max(0.0, now - expected)
        expected = now + interval
        _EVENT_LOOP_WATCHDOG_LAST_BEAT = time.monotonic()
        warn_threshold = _env_float("KIKOERUMANAGER_EVENT_LOOP_LAG_WARN_SECONDS", 2.0, min_value=0.2, max_value=600.0)
        if lag >= warn_threshold:
            logger.warning("[事件循环] 主循环延迟 %.3fs，HTTP 请求和后台任务可能被同步阻塞拖慢", lag)


def _event_loop_watchdog_thread(stop_event: threading.Event) -> None:
    interval = _env_float("KIKOERUMANAGER_EVENT_LOOP_WATCHDOG_INTERVAL", 1.0, min_value=0.2, max_value=60.0)
    warn_threshold = _env_float("KIKOERUMANAGER_EVENT_LOOP_LAG_WARN_SECONDS", 2.0, min_value=0.2, max_value=600.0)
    stack_threshold = _env_float("KIKOERUMANAGER_EVENT_LOOP_STACK_SECONDS", 8.0, min_value=1.0, max_value=1800.0)
    stack_cooldown = _env_float("KIKOERUMANAGER_EVENT_LOOP_STACK_COOLDOWN_SECONDS", 60.0, min_value=5.0, max_value=3600.0)
    last_warn = 0.0
    last_stack_dump = 0.0
    while not stop_event.wait(interval):
        now = time.monotonic()
        lag = max(0.0, now - _EVENT_LOOP_WATCHDOG_LAST_BEAT)
        if lag < warn_threshold or now - last_warn < stack_cooldown:
            continue
        last_warn = now
        logger.warning("[事件循环] 心跳停顿 %.3fs，主循环可能被同步阻塞", lag)
        if lag >= stack_threshold and now - last_stack_dump >= stack_cooldown:
            last_stack_dump = now
            logger.error("[事件循环] 心跳停顿 %.3fs，线程栈如下:%s", lag, _format_all_thread_stacks())


def _start_event_loop_watchdog() -> None:
    global _EVENT_LOOP_WATCHDOG_TASK, _EVENT_LOOP_WATCHDOG_THREAD, _EVENT_LOOP_WATCHDOG_STOP_EVENT, _EVENT_LOOP_WATCHDOG_LAST_BEAT
    if os.environ.get("KIKOERUMANAGER_EVENT_LOOP_WATCHDOG", "1").strip().lower() in {"0", "false", "no", "off"}:
        logger.info("[事件循环] watchdog 已通过环境变量禁用")
        return
    if _EVENT_LOOP_WATCHDOG_TASK and not _EVENT_LOOP_WATCHDOG_TASK.done():
        return
    _EVENT_LOOP_WATCHDOG_LAST_BEAT = time.monotonic()
    _EVENT_LOOP_WATCHDOG_STOP_EVENT = threading.Event()
    _EVENT_LOOP_WATCHDOG_THREAD = threading.Thread(
        target=_event_loop_watchdog_thread,
        args=(_EVENT_LOOP_WATCHDOG_STOP_EVENT,),
        name="event-loop-watchdog-thread",
        daemon=True,
    )
    _EVENT_LOOP_WATCHDOG_THREAD.start()
    _EVENT_LOOP_WATCHDOG_TASK = asyncio.create_task(_event_loop_watchdog_loop(), name="event-loop-watchdog")
    logger.info("[事件循环] watchdog 已启动")


async def _stop_event_loop_watchdog() -> None:
    global _EVENT_LOOP_WATCHDOG_TASK, _EVENT_LOOP_WATCHDOG_THREAD, _EVENT_LOOP_WATCHDOG_STOP_EVENT
    stop_event = _EVENT_LOOP_WATCHDOG_STOP_EVENT
    _EVENT_LOOP_WATCHDOG_STOP_EVENT = None
    if stop_event:
        stop_event.set()
    task = _EVENT_LOOP_WATCHDOG_TASK
    _EVENT_LOOP_WATCHDOG_TASK = None
    if not task:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    thread = _EVENT_LOOP_WATCHDOG_THREAD
    _EVENT_LOOP_WATCHDOG_THREAD = None
    if thread:
        thread.join(timeout=2.0)


def _get_log_io_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _LOG_IO_EXECUTOR
    with _LOG_IO_EXECUTOR_LOCK:
        if _LOG_IO_EXECUTOR is None:
            workers = int(os.environ.get("KIKOERUMANAGER_LOG_IO_WORKERS", "2") or 2)
            _LOG_IO_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(workers, 8)),
                thread_name_prefix="system-log-io",
            )
        return _LOG_IO_EXECUTOR


def _get_log_search_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _LOG_SEARCH_EXECUTOR
    with _LOG_IO_EXECUTOR_LOCK:
        if _LOG_SEARCH_EXECUTOR is None:
            workers = int(os.environ.get("KIKOERUMANAGER_LOG_SEARCH_WORKERS", "1") or 1)
            _LOG_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(workers, 4)),
                thread_name_prefix="system-log-search",
            )
        return _LOG_SEARCH_EXECUTOR


async def _run_log_io(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_log_io_executor(), functools.partial(func, *args, **kwargs))


async def _run_log_search_io(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_log_search_executor(), functools.partial(func, *args, **kwargs))


def _shutdown_log_io_executor() -> None:
    global _LOG_IO_EXECUTOR, _LOG_SEARCH_EXECUTOR
    with _LOG_IO_EXECUTOR_LOCK:
        executor = _LOG_IO_EXECUTOR
        search_executor = _LOG_SEARCH_EXECUTOR
        _LOG_IO_EXECUTOR = None
        _LOG_SEARCH_EXECUTOR = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    if search_executor is not None:
        search_executor.shutdown(wait=False, cancel_futures=True)


def _is_media_response_for_gzip(headers: Headers, status_code: int) -> bool:
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if status_code == 206 or headers.get("content-range"):
        return True
    return content_type.startswith(("video/", "audio/", "image/")) or content_type == "application/octet-stream"


class MediaAwareGZipResponder(GZipResponder):
    async def send_with_compression(self, message):
        message_type = message["type"]
        if message_type == "http.response.start":
            self.initial_message = message
            headers = Headers(raw=self.initial_message["headers"])
            self.content_encoding_set = "content-encoding" in headers
            self.content_type_is_excluded = (
                headers.get("content-type", "").startswith(DEFAULT_EXCLUDED_CONTENT_TYPES)
                or _is_media_response_for_gzip(headers, int(self.initial_message.get("status") or 200))
            )
        elif message_type == "http.response.body" and (self.content_encoding_set or self.content_type_is_excluded):
            if not self.started:
                self.started = True
                await self.send(self.initial_message)
            await self.send(message)
        elif message_type == "http.response.body" and not self.started:
            self.started = True
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) < self.minimum_size and not more_body:
                await self.send(self.initial_message)
                await self.send(message)
            elif not more_body:
                body = self.apply_compression(body, more_body=False)

                headers = MutableHeaders(raw=self.initial_message["headers"])
                headers.add_vary_header("Accept-Encoding")
                if body != message["body"]:
                    headers["Content-Encoding"] = self.content_encoding
                    headers["Content-Length"] = str(len(body))
                    message["body"] = body

                await self.send(self.initial_message)
                await self.send(message)
            else:
                body = self.apply_compression(body, more_body=True)

                headers = MutableHeaders(raw=self.initial_message["headers"])
                headers.add_vary_header("Accept-Encoding")
                if body != message["body"]:
                    headers["Content-Encoding"] = self.content_encoding
                    del headers["Content-Length"]
                    message["body"] = body

                await self.send(self.initial_message)
                await self.send(message)
        elif message_type == "http.response.pathsend":  # pragma: no branch
            await self.send(self.initial_message)
            await self.send(message)


class MediaAwareGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path.startswith("/assets/"):
            responder = IdentityResponder(self.app, self.minimum_size)
            await responder(scope, receive, send)
            return

        headers = Headers(scope=scope)
        responder = MediaAwareGZipResponder(self.app, self.minimum_size, compresslevel=self.compresslevel) if "gzip" in headers.get("Accept-Encoding", "") else IdentityResponder(self.app, self.minimum_size)
        await responder(scope, receive, send)


class PrecompressedStaticFiles(StaticFiles):
    _ENCODING_CANDIDATES = (
        ("br", ".br"),
        ("gzip", ".gz"),
    )

    @staticmethod
    def _accepted_encodings(value: str) -> set:
        encodings = set()
        wildcard_allowed = False
        for part in str(value or "").split(","):
            pieces = [piece.strip() for piece in part.split(";")]
            token = pieces[0].lower() if pieces else ""
            if not token:
                continue
            quality = 1.0
            for param in pieces[1:]:
                key, _, raw_value = param.partition("=")
                if key.strip().lower() != "q":
                    continue
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
            if quality <= 0:
                continue
            if token == "*":
                wildcard_allowed = True
            else:
                encodings.add(token)
        if wildcard_allowed:
            encodings.update(encoding for encoding, _suffix in PrecompressedStaticFiles._ENCODING_CANDIDATES)
        return encodings

    def file_response(self, full_path, stat_result, scope, status_code=200):
        request_headers = Headers(scope=scope)
        accept_encodings = self._accepted_encodings(request_headers.get("accept-encoding", ""))

        for encoding, suffix in self._ENCODING_CANDIDATES:
            if encoding not in accept_encodings:
                continue
            compressed_path = f"{full_path}{suffix}"
            try:
                compressed_stat = os.stat(compressed_path)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(compressed_stat.st_mode):
                continue

            response = StarletteFileResponse(
                compressed_path,
                status_code=status_code,
                media_type=mimetypes.guess_type(str(full_path))[0],
                stat_result=compressed_stat,
            )
            response.headers["Content-Encoding"] = encoding
            response.headers["Vary"] = "Accept-Encoding"
            response.headers["Content-Length"] = str(compressed_stat.st_size)
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
            if self.is_not_modified(response.headers, request_headers):
                return NotModifiedResponse(response.headers)
            return response

        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Vary"] = "Accept-Encoding"
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return response


def _batch_api_rename_request_key(library_id: Any, paths: List[Any]) -> str:
    payload = {
        "library_id": str(library_id or "").strip(),
        "paths": [str(path or "").strip() for path in paths],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _circle_bonus_probe_business_key(
    *,
    maker_id: Any,
    mode: Any,
    release_dates: List[Any],
    gap_limit: Any,
    selected_rjcodes_by_date: Dict[str, Any],
) -> str:
    payload = {
        "maker_id": str(maker_id or "").strip().upper(),
        "mode": str(mode or "normal").strip() or "normal",
        "release_dates": [str(value or "").strip() for value in release_dates or []],
        "gap_limit": int(gap_limit or 0),
        "selected_rjcodes_by_date": {
            str(date or "").strip(): [str(code or "").strip().upper() for code in (codes or [])]
            for date, codes in sorted(dict(selected_rjcodes_by_date or {}).items())
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{payload['maker_id']}:{payload['mode']}:bonus_probe:{digest}"


def _api_rename_metadata_skip_reason(metadata: Dict[str, Any], rjcode: str) -> str:
    from ..core.dlsite_metadata_trust import attach_dlsite_metadata_verification

    source = str(metadata.get("metadata_source") or "").strip().lower()
    if source == "minimal":
        if metadata.get("dlsite_circuit_open"):
            return "DLsite 元数据短熔断中，已跳过重命名"
        return "DLsite 元数据不可用，已跳过重命名"

    attach_dlsite_metadata_verification(metadata, rjcode)
    verification_status = str(
        metadata.get("metadata_verification_status") or ""
    ).strip().lower()
    verification_reason = str(
        metadata.get("metadata_verification_reason") or ""
    ).strip()
    if verification_status != "verified":
        return verification_reason or "DLsite 元数据未经验证，已跳过重命名"

    normalized_rj = str(rjcode or metadata.get("rjcode") or "").strip().upper()
    work_name = str(metadata.get("work_name") or "").strip()
    maker_name = str(metadata.get("maker_name") or "").strip()
    has_any_detail = any(
        [
            str(metadata.get("cover_url") or "").strip(),
            str(metadata.get("release_date") or "").strip(),
            metadata.get("tags") or [],
            metadata.get("cvs") or [],
        ]
    )

    if not maker_name and work_name.upper() == normalized_rj and not has_any_detail:
        return "元数据不完整，已跳过重命名"
    return ""

from ..models.database import init_db, get_db, get_db_path_info, ActivityLog, ASMRDownloadSession, SessionLocal
from ..core.task_engine import TaskEngine, Task, TaskType, get_task_engine
from ..core.watcher import get_watcher
from ..core.password_cleanup import get_cleanup_service
from ..core.processed_archive_cleanup import get_processed_archive_cleanup_service
from ..core.backup_zip_service import get_backup_zip_service
from ..core.file_processor import get_file_processor
from ..core.library_manager import get_library_manager, shutdown_library_manager_background_workers, SynologyError
from ..core.library_index import (
    get_library_index_service,
    get_library_index_mutation_service,
    start_library_index_mutation_service,
    start_library_index_watcher_driver,
    stop_library_index_mutation_service,
    stop_library_index_watcher_driver,
)
from ..core.rjcode_utils import extract_rjcode, extract_rjcode_from_path, scan_existing_folder_candidates
from ..core.password_utils import (
    normalize_filename_value,
    normalize_optional_text,
    normalize_password_value,
    normalize_rjcode_value,
)
from ..core.google_drive_oauth import (
    google_drive_oauth_client_missing_message,
    resolve_google_drive_oauth_client,
    resolve_google_drive_oauth_proxy_url,
)
from ..core.log_sanitizer import sanitize_for_log, sanitize_text_for_log
from ..core.activity_log_service import CATEGORY_LABELS
from ..config.settings import get_config, save_config
from ..core.security_gate_service import COOKIE_NAME, get_security_gate_service
from ..version import get_app_version

# 初始化FastAPI应用
app = FastAPI(
    title="KikoeruManager API",
    description="DLsite作品整理工具API",
    version=get_app_version()
)
app.add_middleware(MediaAwareGZipMiddleware, minimum_size=1024)

# ========== 工具函数 ==========
def _mask_url_credentials(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        from ..core.http_download_service import mask_http_download_url
        return mask_http_download_url(text)
    except Exception:
        return re.sub(r"//([^/@:]+):([^/@]+)@", "//***:***@", text)


def _route_path_basename(value: Any) -> str:
    text = str(value or "").strip().rstrip("/\\")
    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _mask_http_downloader_config_for_log(value: dict) -> dict:
    data = dict(sanitize_for_log(value or {}))
    if "proxy_url" in data:
        data["proxy_url"] = _mask_url_credentials(data.get("proxy_url") or "")
    for key in ("google_drive_client_secret", "google_drive_refresh_token"):
        if data.get(key):
            data[key] = "********"
    if data.get("pikpak_password"):
        data["pikpak_password"] = "********"
    if data.get("pikpak_encoded_token"):
        data["pikpak_encoded_token"] = "********"
    if isinstance(data.get("pikpak_accounts"), list):
        masked_accounts = []
        for account in data.get("pikpak_accounts") or []:
            if not isinstance(account, dict):
                continue
            row = dict(account)
            if row.get("password"):
                row["password"] = "********"
            if row.get("encoded_token"):
                row["encoded_token"] = "********"
            masked_accounts.append(row)
        data["pikpak_accounts"] = masked_accounts
    if data.get("gofile_token"):
        data["gofile_token"] = "********"
    return data


def _mask_baidu_netdisk_config_for_log(value: dict) -> dict:
    data = dict(sanitize_for_log(value or {}))
    if data.get("cookie"):
        data["cookie"] = "********"
    return data


def _mask_circle_external_search_config_for_log(value: dict) -> dict:
    data = dict(sanitize_for_log(value or {}))
    if data.get("south_plus_cookie"):
        data["south_plus_cookie"] = "********"
    if data.get("south_plus_proxy"):
        data["south_plus_proxy"] = _mask_url_credentials(data.get("south_plus_proxy") or "")
    return data


def _has_baidu_login_cookie(value: str) -> bool:
    return bool(re.search(r"(?:^|;\s*)BDUSS(?:_BFESS)?=", str(value or ""), re.I))


def _synology_http_status(exc: Exception) -> int:
    """将群晖 API 错误码映射到合适的 HTTP 状态码。
    119: SID 过期/无效路径; 121: 无效参数; 401: 无权限; 408: 操作超时
    以上均视为上游服务（群晖）异常，返回 502 Bad Gateway。
    """
    msg = str(exc)
    if isinstance(exc, SynologyError):
        if "远程库存暂时退化" in msg:
            return 503
        return 502
    for code in (119, 121, 401, 408):
        if re.search(rf'"code"\s*:\s*{code}\b', msg) or re.search(rf"'code'\s*:\s*{code}\b", msg):
            return 502
    return 500



def _log_synology_err(msg: str, exc: Exception) -> None:
    """群晖/认证可预期错误降级为 WARNING（不打堆栈）；其他意外错误仍用 ERROR + traceback。"""
    if isinstance(exc, SynologyError):
        logger.warning(msg)
    else:
        logger.error(msg, exc_info=True)

# ========== 健康检查 API ==========
@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "kikoerumanager",
        "version": get_app_version(),
        "timestamp": datetime.now().isoformat()
    }


# 注意：以下高频读接口刻意保持同步 def，让 FastAPI 调度到 starlette threadpool，
# 而不是 async def 直接占用事件循环。配合 run.py 的 anyio threadpool=80，群晖
# 慢 IO 场景下接口之间不再连环阻塞。
# lite 模式默认会从时间线里隐藏的"子动作"——它们由 merge_activity_rows 在
# 详情接口里挂回到父行内，前端不需要在时间线里再摆一遍。
_LITE_HIDDEN_ACTIONS = (
    "resource_downloaded",
    "resource_uploaded",
    "resource_verify_failed",
    "download_item_queued",
    "queue_reordered",
    "task_paused",
    "task_resumed",
    "task_retried",
    "session_started",
    "enhanced_plan_created",
    "view_built",
)

# 哪些类目下的失败任务，可以由"同 RJ 的后续成功"覆盖修复。
# 这里和前端 ActivityHistory.vue 的 RECOVERY_CATEGORIES 保持一致。
_LITE_RECOVERY_CATEGORIES = ("extract", "auto_import", "process_existing", "asmr_sync")

_ACTIVITY_LOG_VISIBLE_CATEGORIES = tuple(CATEGORY_LABELS.keys())

# 单次搜索命中上限：避免关键词过宽时把大量 id 塞回 ORM 查询。
_SEARCH_MATCH_CAP = 2000

# 搜索关键词长度上限（字符）。短到 1 字符也允许（trigram 友好），但太长无意义。
_SEARCH_TEXT_MAX_LEN = 200

_SEARCH_DANGER_CHARS = ("\x00",)


def _sanitize_search_text(raw: str) -> str:
    """清洗搜索文本：去除控制字符并截断长度。"""
    if not raw:
        return ""
    text_value = "".join(ch for ch in str(raw) if ch.isprintable() or ch in (" ", "\t"))
    for danger in _SEARCH_DANGER_CHARS:
        text_value = text_value.replace(danger, " ")
    text_value = " ".join(text_value.split())
    return text_value[:_SEARCH_TEXT_MAX_LEN]


def _escape_ilike_pattern(value: str) -> str:
    return str(value or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")


_PASSWORD_SEARCH_FILTER_SQL = """
(COALESCE(rjcode, '') || ' ' ||
 COALESCE(filename, '') || ' ' ||
 COALESCE(password, '') || ' ' ||
 COALESCE(description, '')) ILIKE :password_search_pattern ESCAPE '!'
"""


def _password_search_filter(search: str):
    return text(_PASSWORD_SEARCH_FILTER_SQL).bindparams(
        password_search_pattern=f"%{_escape_ilike_pattern(search)}%"
    )


_PROCESSED_ARCHIVE_SEARCH_FILTER_SQL = """
(rjcode ILIKE :processed_archive_search_pattern ESCAPE '!' OR
 filename ILIKE :processed_archive_search_pattern ESCAPE '!')
"""


def _processed_archive_search_filter(search: str):
    return text(_PROCESSED_ARCHIVE_SEARCH_FILTER_SQL).bindparams(
        processed_archive_search_pattern=f"%{_escape_ilike_pattern(search)}%"
    )


def _run_activity_log_id_search(db: Session, search_text: str, cap: int) -> tuple[List[Any], str]:
    pattern = f"%{_escape_ilike_pattern(search_text)}%"
    rows = db.execute(
        text(
            """
            SELECT id
              FROM activity_logs
             WHERE searchable_text ILIKE :p ESCAPE '!'
             ORDER BY created_at DESC
             LIMIT :cap
            """
        ),
        {"p": pattern, "cap": cap},
    ).fetchall()
    ids = [row[0] for row in rows if row and row[0]]
    return ids, "postgresql_pg_trgm"


def _enrich_lite_items_with_recovery(items: List[Dict[str, Any]], db: Session) -> None:
    """给 lite 列表里的失败行回填"已被后续成功覆盖"标记。

    aggregator 主流程会按 (source_path, rjcode) 在合并时打这个标记，但 lite 路径
    没走 aggregator。前端要显示"已修复"绿底徽章 + 红→绿渐变色条，依赖
    ``recovered_by_success`` / ``recovered_badge`` 这两个直通字段。

    实现思路：
    1) 找出当前页里 status=failed && category 在恢复白名单里 && 有 RJ 的行；
    2) 对这些 RJ 批量查一次"任意时间点的最新 success / partial_success 时间"，
       走 idx_rjcode 索引，单次 GROUP BY 即可；
    3) 比较时间戳，晚于失败行就打标记。
    """
    if not items:
        return
    candidates = []
    rjcodes_seen = set()
    for it in items:
        if str(it.get("status") or "").strip() != "failed":
            continue
        cat = str(it.get("category") or "").strip()
        if cat not in _LITE_RECOVERY_CATEGORIES:
            continue
        rj = str(it.get("rjcode") or "").strip().upper()
        if not rj:
            continue
        candidates.append((it, rj))
        rjcodes_seen.add(rj)
    if not candidates:
        return

    rjcodes = list(rjcodes_seen)
    # 单次 GROUP BY：每个 RJ 在恢复类目里最新一次 success / partial_success 的时间
    rows = (
        db.query(ActivityLog.rjcode, func.max(ActivityLog.created_at))
        .filter(
            ActivityLog.rjcode.in_(rjcodes),
            ActivityLog.category.in_(list(_LITE_RECOVERY_CATEGORIES)),
            ActivityLog.status.in_(("success", "partial_success")),
        )
        .group_by(ActivityLog.rjcode)
        .all()
    )
    latest_by_rj: Dict[str, Any] = {}
    for row in rows:
        if not row or not row[0]:
            continue
        latest_by_rj[str(row[0]).strip().upper()] = row[1]
    if not latest_by_rj:
        return

    for it, rj in candidates:
        latest = latest_by_rj.get(rj)
        if latest is None:
            continue
        failed_at_raw = it.get("created_at")
        try:
            if isinstance(failed_at_raw, str):
                failed_at = datetime.fromisoformat(failed_at_raw)
            else:
                failed_at = failed_at_raw
        except Exception:
            continue
        if failed_at is None or latest <= failed_at:
            continue
        it["recovered_by_success"] = True
        it["recovered_badge"] = "已覆盖"


# 与前端 ActivityHistory.vue / useActivityDetailModels.js 保持完全一致的关键词集合：
# raw status 是 success 但 summary / detail 暗示"实际进了问题作品列表 / 按重复处理"
# 等"任务跑完但没真正入库"的场景，三端口径必须一致。
_BATCH_SUMMARY_PARTIAL_KEYWORDS: tuple[str, ...] = (
    "加入问题作品列表",
    "已转入问题作品",
    "按重复作品处理",
    "转入问题作品列表",
)


def _looks_like_partial_success(summary: str, detail: Optional[Dict[str, Any]]) -> bool:
    """判断一条 raw=success 的子任务是否在语义上等价于 partial_success。

    依据：
    1. summary 里出现 ``加入问题作品列表 / 已转入问题作品 / 按重复作品处理 / 转入问题作品列表``
       等关键词 —— 任务跑完了但作品被转到问题作品列表，没真正入库。
    2. detail.linked_subtitle_problem / detail.existing_subtitle_problem 显式标记。
    3. detail.source_mode 以 ``_existing_subtitle_conflict`` 结尾。
    """
    if isinstance(summary, str) and summary:
        for kw in _BATCH_SUMMARY_PARTIAL_KEYWORDS:
            if kw in summary:
                return True
    if isinstance(detail, dict):
        if detail.get("linked_subtitle_problem") or detail.get("existing_subtitle_problem"):
            return True
        source_mode = str(detail.get("source_mode") or "")
        if source_mode.endswith("_existing_subtitle_conflict"):
            return True
    return False


def _enrich_baidu_netdisk_activity_detail_from_task(row: Dict[str, Any], db: Session) -> None:
    """详情页按 task_id 从任务表补全百度网盘文件清单的脱敏扩展字段。"""
    if not isinstance(row, dict):
        return
    if str(row.get("category") or "").strip() != "baidu_netdisk":
        return
    task_id = str(row.get("task_id") or "").strip()
    if not task_id:
        return
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    needs_password_or_rename = not any(
        bool(item.get("has_extract_password") or item.get("custom_file_names"))
        for item in list(detail.get("download_files") or [])
        if isinstance(item, dict)
    )
    if list(detail.get("download_files") or []) and not needs_password_or_rename:
        return
    try:
        from ..core.baidu_netdisk_service import sanitize_baidu_netdisk_item
        from ..models.database import Task as TaskRecord

        task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
        metadata = task.task_metadata if task and isinstance(task.task_metadata, dict) else {}
        if not metadata:
            return
        enriched = dict(detail)
        for key in ("download_files", "failed_files"):
            raw_items = [item for item in list(metadata.get(key) or []) if isinstance(item, dict)]
            if raw_items:
                enriched[key] = [sanitize_baidu_netdisk_item(item) for item in raw_items[:200]]
        for key in (
            "download_root",
            "target_subdir",
            "output_folder_name",
            "staging_dir",
            "final_output_path",
            "renamed_output_path",
            "output_finalize_status",
            "download_mode",
            "platform_label",
        ):
            value = metadata.get(key)
            if value not in (None, "", []):
                enriched[key] = value
        row["detail"] = enriched
    except Exception:
        logger.debug("[操作记录] 百度网盘详情按任务补全失败: task_id=%s", task_id, exc_info=True)


def _enrich_lite_items_with_batch_summary(
    items: List[Dict[str, Any]],
    db: Session,
    *,
    force: bool = False,
) -> None:
    """给 lite 列表里的批次父行回填同 batch_id 子任务的状态聚合。

    用户场景：批次启动行（如 ``batch_start`` action）写日志时 status="success"，
    因为创建任务这一刻确实成功了。但子任务是后续异步跑出来的，可能 failed，
    这种情况下前端原本会看到"处理完成"绿条，点开抽屉才发现子任务实际失败。

    aggregator 路径会按 batch_id 聚合子任务 status 重写父行（``_main.py`` 里的
    ``failed_child_count`` / ``partial_child_count`` 判断），lite 路径跳过 aggregator
    则没人做这件事。这里在 list 接口返回前做一次轻量回查：

    1) 收集本页 ``has_children=True && batch_id`` 的"父行候选"
    2) 单次 SQL 拉同 batch_id 的所有兄弟行 (id, status)
    3) 排除父行自身，按 (batch_id × status) 聚合计数
    4) 把 ``child_failed_count`` / ``child_success_count`` / ``child_partial_count``
       / ``child_total_count`` 挂到父行 item，前端 effectiveStatus 据此把
       "success" 升级为 "partial_success"（子任务有成功也有失败）或 "failed"
       （子任务全失败）。

    ``force=True`` 时跳过 ``has_children`` 过滤（用于 detail 接口单行兜底，
    aggregator 没识别成 batch 但实际有同 batch_id 子任务的场景）。

    性能：单次 IN 查询，配 ``idx_batch_id`` 走索引；不再对每行做 N+1 子查询。
    """
    if not items:
        return
    candidates: List[Dict[str, Any]] = []
    batch_ids: set[str] = set()
    parent_ids_per_batch: Dict[str, set[str]] = {}
    for it in items:
        if not force and not it.get("has_children") and not it.get("has_child_rows"):
            continue
        bid_raw = it.get("batch_id")
        bid = str(bid_raw or "").strip()
        if not bid:
            continue
        candidates.append(it)
        batch_ids.add(bid)
        parent_ids_per_batch.setdefault(bid, set()).add(str(it.get("id") or ""))
    if not batch_ids:
        return

    try:
        from ..core.activity_log_rollup_service import get_activity_log_rollup_service

        rollup_stats = get_activity_log_rollup_service().summary_for_batch_ids(db, batch_ids)
        if rollup_stats and all(bid in rollup_stats for bid in batch_ids):
            for it in candidates:
                bid = str(it.get("batch_id") or "").strip()
                s = rollup_stats.get(bid)
                if not s or int(s.get("child_total_count") or 0) <= 0:
                    continue
                it.update(s)
            return
    except Exception:
        logger.warning("[操作记录] lite 批次 rollup 读取失败，回退即时 SQL 聚合", exc_info=True)

    try:
        rows = (
            db.query(
                ActivityLog.batch_id,
                ActivityLog.id,
                ActivityLog.status,
                ActivityLog.summary,
                ActivityLog.detail,
            )
            .filter(ActivityLog.batch_id.in_(list(batch_ids)))
            .all()
        )
    except Exception:
        logger.warning("[操作记录] lite 批次状态聚合 SQL 失败（不阻断主流程）", exc_info=True)
        return

    stats: Dict[str, Dict[str, int]] = {
        bid: {"failed": 0, "success": 0, "partial_success": 0, "total": 0}
        for bid in batch_ids
    }
    for row in rows:
        bid = str(row[0] or "").strip()
        rid = str(row[1] or "")
        status_text = str(row[2] or "").strip()
        summary_text = str(row[3] or "")
        detail_obj = row[4] if isinstance(row[4], dict) else None
        if bid not in stats:
            continue
        # 排除父行自身：父行的 status 已经在 item 上，不能把它算进子任务统计里
        if rid in parent_ids_per_batch.get(bid, set()):
            continue

        # 关键修复：raw status 是 success，但 summary / detail 实际语义是 partial_success
        # 的子任务（"加入问题作品列表"等）必须按 partial_success 计数，否则父行永远
        # 看不到 child_partial_count > 0，永远不会升级。
        # 这套关键词与前端 effectiveStatus / effectiveRowStatus 完全一致，三端口径统一。
        if status_text in {"success", "completed"} and _looks_like_partial_success(summary_text, detail_obj):
            status_text = "partial_success"

        stats[bid]["total"] += 1
        if status_text in {"failed", "error"}:
            stats[bid]["failed"] += 1
        elif status_text in {"success", "completed"}:
            stats[bid]["success"] += 1
        elif status_text == "partial_success":
            stats[bid]["partial_success"] += 1

    for it in candidates:
        bid = str(it.get("batch_id") or "").strip()
        s = stats.get(bid)
        if not s or s["total"] == 0:
            continue
        it["child_failed_count"] = s["failed"]
        it["child_success_count"] = s["success"]
        it["child_partial_count"] = s["partial_success"]
        it["child_total_count"] = s["total"]


@app.get("/api/activity-logs")
def list_activity_logs(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    since_days: Optional[int] = None,
    batch_id: Optional[str] = None,
    session_key: Optional[str] = None,
    lite: bool = False,
    show_subactions: bool = False,
    db: Session = Depends(get_db),
):
    """分页查询操作审计记录。

    Phase 1/2 优化：
    - 原始查询强制加载上限（MAX_MERGE_WINDOW），避免随审计表无界增长拖慢接口。
    - 支持 since_days 指定仅合并最近 N 天；0/None=仅按 MAX 窗口截取。
    - 结果按 (筛选条件, 页码, writer.last_write_ts) TTL 缓存；有新审计写入时自动失效。
    - q 参数走 PostgreSQL pg_trgm 加速的 ILIKE 搜索，命中后再按主键回查。
    - Phase 2：新增 batch_id / session_key 查询参数，用于 workbench 里
      "拉取某批次全部子任务"这种精准场景，直接走新索引。
    - Phase 5：``lite=true`` 进入快速路径：跳过 1700+ 行合并算法和整段 detail
      回传，只在数据库层做 ORDER BY + LIMIT 分页，配合 ``activity_log_lite``
      抽 metric chips。响应体从 ~5MB 压到 ~150KB，主要面向新版时间线视图。
    """
    from ..core.activity_log_service import CATEGORY_LABELS
    from ..core.activity_log_writer import (
        get_activity_log_lite_item_cache,
        get_activity_log_query_cache,
        get_activity_log_row_dict_cache,
        get_activity_log_writer,
    )

    MAX_MERGE_WINDOW = 5000
    writer = get_activity_log_writer()
    query_cache = get_activity_log_query_cache()
    cache_key = (
        "list" if not lite else "list_lite",
        int(page or 1),
        int(limit or 50),
        (category or "").strip(),
        (status or "").strip(),
        (q or "").strip(),
        int(since_days) if since_days is not None else None,
        (batch_id or "").strip(),
        (session_key or "").strip(),
        bool(show_subactions),
    )
    cached = query_cache.get(cache_key, writer.last_write_ts)
    if cached is not None:
        return cached

    # Phase 3: 1800+ 行合并算法已搬到 activity_log_aggregator 模块
    # Phase 4D: 用 merge_activity_rows_from_dicts 入口配合 row-dict 缓存，避免每请求重新
    # orjson.loads 所有 detail
    from ..core.activity_log_aggregator import merge_activity_rows_from_dicts
    from ..core.activity_log_lite import build_lite_item

    page = max(1, page)
    limit = max(1, min(200, limit))
    query = db.query(ActivityLog)
    query = query.filter(ActivityLog.category.in_(list(_ACTIVITY_LOG_VISIBLE_CATEGORIES)))
    if category:
        query = query.filter(ActivityLog.category == category)
    if status:
        query = query.filter(ActivityLog.status == status)

    # Phase 2：精准过滤走新索引列，跳过合并 / FTS 分支
    batch_id_value = (batch_id or "").strip()
    if batch_id_value:
        query = query.filter(ActivityLog.batch_id == batch_id_value[:80])
    session_key_value = (session_key or "").strip()
    if session_key_value:
        query = query.filter(ActivityLog.session_key == session_key_value[:120])

    # 搜索路径：PostgreSQL pg_trgm GIN 索引加速 ILIKE，多列搜索仍先截断 id 集合。
    search_backend = "none"
    search_text_raw = (q or "").strip()
    search_text = _sanitize_search_text(search_text_raw)
    search_match_count: Optional[int] = None

    def _empty_search_payload(reason: str) -> Dict[str, Any]:
        payload_empty = {
            "total": 0,
            "page": page,
            "limit": limit,
            "items": [],
            "window": {
                "since_days": None,
                "search_backend": reason,
                "search_text": search_text,
            },
        }
        query_cache.set(cache_key, writer.last_write_ts, payload_empty)
        return payload_empty

    if search_text_raw and not search_text:
        # 用户输入了关键词但清洗后为空（全是 FTS 危险字符）
        return _empty_search_payload("sanitized_empty")

    if search_text:
        try:
            matched_ids, backend_tag = _run_activity_log_id_search(db, search_text, _SEARCH_MATCH_CAP)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("[操作记录] PostgreSQL trigram 搜索失败 text=%r", search_text, exc_info=True)
            return _empty_search_payload("postgresql_pg_trgm_error")

        if not matched_ids:
            return _empty_search_payload(backend_tag or "postgresql_pg_trgm")

        query = query.filter(ActivityLog.id.in_(matched_ids))
        search_backend = backend_tag
        search_match_count = len(matched_ids)

    # since_days=None: 默认仅合并 MAX_MERGE_WINDOW 条（按 created_at 倒序）；
    # since_days>0:   仅加载最近 N 天，配合上限兜底；
    # since_days=0:   显式放开时间过滤，仍有 MAX_MERGE_WINDOW 上限保护。
    effective_since_days = None
    if since_days is not None:
        try:
            sd = int(since_days)
        except (TypeError, ValueError):
            sd = None
        if sd is not None and sd > 0:
            effective_since_days = max(1, min(365, sd))
    if effective_since_days is not None:
        cutoff = datetime.now() - timedelta(days=effective_since_days)
        query = query.filter(ActivityLog.created_at >= cutoff)

    # Phase 5：lite 快速路径——SQL 层直接 LIMIT/OFFSET 分页，不再加载 5000 行。
    # 对于新版时间线视图，列表只需要 chips + 摘要，不再走合并算法。
    if lite:
        # 默认隐藏"子动作"行（resource_downloaded / resource_uploaded 等），它们在详情接口里会通过 merge_activity_rows 重新挂回父行的 child_rows。
        # 用户显式带 show_subactions=true 时可以打破这层过滤，看完整事件流。
        # 例外：失败 / 部分失败的子动作（resource_verify_failed 这种）保留在列表里，
        # 否则用户在时间线里完全看不到失败子任务，体感像"失败任务消失了"。
        if not show_subactions:
            query = query.filter(
                or_(
                    ~ActivityLog.action.in_(_LITE_HIDDEN_ACTIONS),
                    ActivityLog.status.in_(("failed", "partial_success")),
                )
            )
        # 社团索引的 task_finished / task_finished_incomplete 生命周期行只是 "完成" 的占位摘要，
        # 真正的信息（社团 / 索引计数 / 耗时）都在同时刻写入的 index_completed domain event 里。
        # 特典探测没有额外 domain event，必须保留这条生命周期行，否则操作记录会看不到刚执行的特典查找。
        circle_source_action = func.coalesce(ActivityLog.detail.op("->>")("source_action"), "")
        query = query.filter(
            ~(
                (ActivityLog.category == "circle_completion")
                & ActivityLog.action.in_(("task_finished", "task_finished_incomplete"))
                & ~circle_source_action.in_(("bonus_probe", "new_release_bonus_probe"))
            )
        )
        # 搜索分支：search_match_count 已是索引命中上限内的总数（≤ _SEARCH_MATCH_CAP），
        # 直接用作 total，跳过 COUNT(*) 全表扫描；hidden actions 过滤的少量误差在 UI 上不显眼。
        # 非搜索分支：维持原 COUNT(*) 逻辑（有 created_at + category 索引保护，开销可接受）。
        if search_match_count is not None:
            total = int(search_match_count)
        else:
            total = query.with_entities(func.count(ActivityLog.id)).scalar() or 0
        offset = max(0, (page - 1) * limit)
        page_id_rows = (
            query.with_entities(ActivityLog.id)
            .order_by(desc(ActivityLog.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        page_ids = [row[0] for row in page_id_rows if row and row[0]]

        lite_item_cache = get_activity_log_lite_item_cache()
        lite_hits = lite_item_cache.get_many(page_ids)
        row_cache = get_activity_log_row_dict_cache()
        row_candidate_ids = [rid for rid in page_ids if str(rid) not in lite_hits]
        cache_hits = row_cache.get_many(row_candidate_ids)
        missing_ids = [rid for rid in row_candidate_ids if str(rid) not in cache_hits]
        fresh_dict_map: Dict[str, Dict[str, Any]] = {}
        if missing_ids:
            fresh_orm_rows = (
                db.query(ActivityLog)
                .filter(ActivityLog.id.in_(missing_ids))
                .all()
            )
            fresh_pairs = []
            for orm_row in fresh_orm_rows:
                rid = str(orm_row.id)
                row_dict = orm_row.to_dict()
                fresh_dict_map[rid] = row_dict
                fresh_pairs.append((rid, row_dict))
            row_cache.put_many(fresh_pairs)

        items: List[Dict[str, Any]] = []
        fresh_lite_pairs = []
        for rid in page_ids:
            key = str(rid)
            cached_lite = lite_hits.get(key)
            if cached_lite is not None:
                items.append(cached_lite)
                continue
            row_dict = cache_hits.get(key) or fresh_dict_map.get(key)
            if row_dict is None:
                continue
            lite_item = build_lite_item(row_dict)
            items.append(lite_item)
            fresh_lite_pairs.append((rid, lite_item))
        if fresh_lite_pairs:
            lite_item_cache.put_many(fresh_lite_pairs)

        # lite 路径不走 aggregator，失败行没人给打"已被覆盖"标记。
        # 这里对当前页的失败行做一次批量回查：同 RJ 的后续 success / partial_success
        # 时间晚于该失败行 → 标记为已修复。前端列表行据此显示绿底"已修复"徽章。
        try:
            _enrich_lite_items_with_recovery(items, db)
        except Exception:
            logger.warning("[操作记录] lite 已修复回填失败（不阻断主流程）", exc_info=True)

        # 批次父行子任务状态聚合：把同 batch_id 的子任务 failed/success 计数挂到父行，
        # 前端 effectiveStatus 据此把"创建任务成功但子任务失败"的批次父行升级为
        # partial_success / failed，避免出现"处理完成 ✓"但点开看到"失败 1 个"的认知错位。
        try:
            _enrich_lite_items_with_batch_summary(items, db)
        except Exception:
            logger.warning("[操作记录] lite 批次状态聚合回填失败（不阻断主流程）", exc_info=True)

        payload = {
            "total": int(total),
            "page": page,
            "limit": limit,
            "items": items,
            "window": {
                "lite": True,
                "search_backend": search_backend,
                "since_days": effective_since_days,
            },
        }
        query_cache.set(cache_key, writer.last_write_ts, payload)
        return payload

    # Phase 4D：ID 先筛 → 行缓存命中 → 只拉未命中行。以前是 `.all()` 整列物化把所有 detail
    # JSON 都 orjson.loads 一遍（~90ms/762行，5000 行上 ~460ms）。现在稳态下 95%+ 请求
    # 能从 LRU 直接拿 row dict，整段下来只剩 ID 扫描 + 合并算法的 ~20ms 开销。
    ordered_id_rows = (
        query.with_entities(ActivityLog.id)
        .order_by(desc(ActivityLog.created_at))
        .limit(MAX_MERGE_WINDOW)
        .all()
    )
    ordered_ids = [row[0] for row in ordered_id_rows if row and row[0]]
    truncated = len(ordered_ids) >= MAX_MERGE_WINDOW

    row_cache = get_activity_log_row_dict_cache()
    cache_hits = row_cache.get_many(ordered_ids)
    missing_ids = [rid for rid in ordered_ids if str(rid) not in cache_hits]
    fresh_dict_map: Dict[str, Dict[str, Any]] = {}
    if missing_ids:
        fresh_orm_rows = (
            db.query(ActivityLog)
            .filter(ActivityLog.id.in_(missing_ids))
            .all()
        )
        fresh_pairs = []
        for orm_row in fresh_orm_rows:
            rid = str(orm_row.id)
            row_dict = orm_row.to_dict()
            fresh_dict_map[rid] = row_dict
            fresh_pairs.append((rid, row_dict))
        row_cache.put_many(fresh_pairs)

    rows_dict: List[Dict[str, Any]] = []
    for rid in ordered_ids:
        key = str(rid)
        row_dict = cache_hits.get(key) or fresh_dict_map.get(key)
        if row_dict is not None:
            rows_dict.append(row_dict)

    merged_items = merge_activity_rows_from_dicts(rows_dict)
    total = len(merged_items)
    start = (page - 1) * limit
    end = start + limit
    payload = {
        "total": total,
        "page": page,
        "limit": limit,
        "items": merged_items[start:end],
        "window": {
            "max_merge_window": MAX_MERGE_WINDOW,
            "raw_loaded": len(ordered_ids),
            "truncated": truncated,
            "since_days": effective_since_days,
            "search_backend": search_backend,
        },
    }
    query_cache.set(cache_key, writer.last_write_ts, payload)
    return payload


@app.get("/api/activity-logs/stats")
def activity_logs_stats(
    days: int = 14,
    db: Session = Depends(get_db),
):
    """按天、分类、状态聚合（用于图表）。

    Phase 1 优化：
    - 指标聚合不再整表读 detail JSON，改用 PostgreSQL JSONB ->> 只取用到的字段，
      省去全列 deserialize 带来的 IO + 反序列化成本。
    - 聚合结果按 (days, writer.last_write_ts) TTL 缓存（30s），读多写少场景命中率高。
    """
    from ..core.activity_log_service import CATEGORY_LABELS
    from ..core.activity_log_writer import (
        get_activity_log_query_cache,
        get_activity_log_writer,
    )

    days = int(days)
    all_time = days <= 0
    days = 0 if all_time else max(1, min(90, days))

    writer = get_activity_log_writer()
    query_cache = get_activity_log_query_cache()
    cache_key = ("stats", days, bool(all_time))
    cached = query_cache.get(cache_key, writer.last_write_ts)
    if cached is not None:
        return cached

    cutoff = None if all_time else (datetime.now() - timedelta(days=days))
    cutoff_date_str = None if cutoff is None else cutoff.strftime("%Y-%m-%d")

    # Phase 4A：by_day / by_category / by_status 改读 activity_log_daily_stats 聚合表，
    # 不再扫 activity_logs 全表做 GROUP BY。聚合表由 Writer 增量维护 + 启动时回填。
    from ..models.database import ActivityLogDailyStats

    rollup_query = db.query(
        ActivityLogDailyStats.date,
        ActivityLogDailyStats.category,
        ActivityLogDailyStats.status,
        ActivityLogDailyStats.count,
    )
    if cutoff_date_str is not None:
        rollup_query = rollup_query.filter(ActivityLogDailyStats.date >= cutoff_date_str)
    rollup_rows = rollup_query.all()

    by_day_map: Dict[str, int] = {}
    cat_counter: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for date_str, cat, st, cnt in rollup_rows:
        if not date_str:
            continue
        n = int(cnt or 0)
        by_day_map[date_str] = by_day_map.get(date_str, 0) + n
        if cat:
            cat_counter[cat] = cat_counter.get(cat, 0) + n
        if st:
            by_status[str(st)] = by_status.get(str(st), 0) + n
    by_day = [{"date": d, "count": c} for d, c in sorted(by_day_map.items())]
    by_category = [
        {"category": c, "label": CATEGORY_LABELS.get(c, c), "count": n}
        for c, n in sorted(cat_counter.items(), key=lambda kv: -kv[1])
    ]
    total_in_range = sum(by_status.values())

    # 只选指标计算用得上的字段（category/action/status + detail.* 单项），
    # 避免把整个 detail JSON 拉回 Python 做反序列化。
    def _jx(path: str):
        return ActivityLog.detail.op("->>")(path)

    metric_query = db.query(
        ActivityLog.category,
        ActivityLog.action,
        ActivityLog.status,
        _jx("downloaded_count"),
        _jx("applied_pairs"),
        _jx("manual_match_applied_pairs"),
        _jx("matched_group_count"),
        _jx("final_file_count"),
        _jx("extract_output_bytes"),
        _jx("output_size_bytes"),
        _jx("extract_performed"),
        _jx("archive_input"),
        _jx("success_count"),
        _jx("deleted_bytes"),
    )
    if cutoff is not None:
        metric_query = metric_query.filter(ActivityLog.created_at >= cutoff)
    # 只对会贡献指标的 category 做过滤，进一步缩小扫描面
    relevant_categories = {
        "subtitle_crawl", "subtitle_pair", "subtitle_import",
        "extract", "auto_import",
        "pipeline_filter", "pipeline_delete",
    }
    metric_query = metric_query.filter(ActivityLog.category.in_(relevant_categories))
    metric_rows = metric_query.all()

    def _int(value: Any) -> int:
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0

    def _truthy(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "null", "none"}
        return bool(value)

    metrics = {
        "subtitle_download_count": 0,
        "subtitle_match_count": 0,
        "subtitle_crawl_count": 0,
        "subtitle_import_count": 0,
        "extract_count": 0,
        "delete_count": 0,
        "delete_bytes": 0,
        "extract_bytes": 0,
    }
    for (
        category,
        action,
        status,
        downloaded_count,
        applied_pairs,
        manual_match_applied_pairs,
        matched_group_count,
        final_file_count,
        extract_output_bytes,
        output_size_bytes,
        extract_performed,
        archive_input,
        success_count,
        deleted_bytes,
    ) in metric_rows:
        if status not in {"success", "completed", "partial_success"}:
            continue
        if category == "subtitle_crawl":
            metrics["subtitle_crawl_count"] += 1
            metrics["subtitle_download_count"] += _int(downloaded_count)
        elif category == "subtitle_pair":
            metrics["subtitle_match_count"] += (
                _int(applied_pairs)
                or _int(manual_match_applied_pairs)
                or _int(matched_group_count)
                or _int(final_file_count)
                or 0
            )
        elif category == "subtitle_import":
            metrics["subtitle_import_count"] += _int(final_file_count) or 1
        elif category == "extract":
            metrics["extract_count"] += 1
            metrics["extract_bytes"] += _int(extract_output_bytes) or _int(output_size_bytes)
        elif category == "auto_import":
            if _truthy(extract_performed) or _truthy(archive_input):
                metrics["extract_count"] += 1
                metrics["extract_bytes"] += _int(extract_output_bytes) or _int(output_size_bytes)
        elif category == "pipeline_filter" and action == "filter_delete_apply":
            metrics["delete_count"] += _int(success_count)
            metrics["delete_bytes"] += _int(deleted_bytes)
        elif category == "pipeline_delete":
            if action == "batch_api_delete":
                metrics["delete_count"] += _int(success_count)
            elif action in {"delete", "batch_delete_item"} and status in {"success", "completed"}:
                metrics["delete_count"] += 1

    payload = {
        "days": days,
        "total_in_range": total_in_range,
        "by_day": by_day,
        "by_category": by_category,
        "by_status": by_status,
        "metrics": metrics,
        "db_path": get_db_path_info(),
    }
    query_cache.set(cache_key, writer.last_write_ts, payload)
    return payload


@app.post("/api/activity-logs/filter-delete")
async def create_filter_delete_activity_log(request: Request):
    """写入删除过滤预审 / 执行的操作记录。"""
    from ..core.activity_log_service import (
        log_filter_delete_apply_result,
        log_filter_delete_preview_result,
        log_filter_delete_retry_result,
    )

    try:
        data = await request.json()
        mode = str(data.get("mode") or "").strip()
        if mode == "preview":
            log_filter_delete_preview_result(data)
        elif mode == "retry_preview":
            log_filter_delete_retry_result(data)
        elif mode == "apply":
            log_filter_delete_apply_result(data)
        else:
            raise HTTPException(status_code=400, detail="不支持的删除过滤日志类型")
        return {"message": "操作记录已写入"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"写入删除过滤操作记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"写入删除过滤操作记录失败: {str(e)}")


@app.get("/api/activity-logs/{log_id}/children")
def get_activity_log_children(
    log_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """懒拉取某条操作记录下挂的全部子记录。

    Phase 3：前端查看批量任务（解压入库 / 社团下载 / 字幕抓取批次等）详情时，
    不再需要把整窗口 5000 行一次性拉回来交给合并算法拆分；
    直接按 Phase 2 新建的 ``batch_id`` / ``session_key`` 索引做单次 SQL 查询即可。

    匹配策略（按优先级回退）：
    1. 当前行自身的 ``batch_id`` 命中其他行的 ``batch_id``
    2. 当前行的 ``id`` 命中其他行的 ``parent_id``
    3. 当前行的 ``session_key`` 命中其他行的 ``session_key``
    """
    from ..core.activity_log_aggregator import merge_activity_rows

    limit = max(1, min(1000, int(limit or 200)))
    parent = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if parent is None:
        raise HTTPException(status_code=404, detail="未找到对应操作记录")

    children: List[ActivityLog] = []
    seen_ids = {parent.id}

    def _extend(rows):
        for row in rows:
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            children.append(row)

    if parent.batch_id:
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.batch_id == parent.batch_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(limit)
            .all()
        )

    if len(children) < limit:
        remaining = limit - len(children)
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.parent_id == parent.id)
            .order_by(desc(ActivityLog.created_at))
            .limit(remaining)
            .all()
        )

    if len(children) < limit and parent.session_key:
        remaining = limit - len(children)
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.session_key == parent.session_key)
            .order_by(desc(ActivityLog.created_at))
            .limit(remaining)
            .all()
        )

    # 复用聚合器规范化 to_dict + category_label 等字段，保证和列表接口 item 结构一致
    parent_item = merge_activity_rows([parent])
    child_items = merge_activity_rows(children) if children else []
    return {
        "parent": parent_item[0] if parent_item else parent.to_dict(),
        "total": len(child_items),
        "items": child_items,
        "match": {
            "by_batch_id": parent.batch_id,
            "by_parent_id": parent.id,
            "by_session_key": parent.session_key,
        },
    }


@app.get("/api/activity-logs/{log_id}/detail")
def get_activity_log_detail(
    log_id: str,
    db: Session = Depends(get_db),
):
    """单行详情接口（Phase 5）。

    新版时间线列表用 lite 模式拉条目，点开抽屉时再调本接口拿完整 detail：
    - 单行返回，开销可忽略；
    - 顺手把同链路子行（合并算法的复杂结果）一起塞进 ``children`` 数组，
      复用现有 ``/children`` 的关联策略，保证抽屉渲染和旧版一致。
    """
    from ..core.activity_log_aggregator import merge_activity_rows

    parent = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if parent is None:
        raise HTTPException(status_code=404, detail="未找到对应操作记录")

    related_rows: List[ActivityLog] = []
    seen_ids = {parent.id}

    def _extend(rows):
        for row in rows:
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            related_rows.append(row)

    if parent.batch_id:
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.batch_id == parent.batch_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(500)
            .all()
        )
    _extend(
        db.query(ActivityLog)
        .filter(ActivityLog.parent_id == parent.id)
        .order_by(desc(ActivityLog.created_at))
        .limit(500)
        .all()
    )
    if parent.session_key:
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.session_key == parent.session_key)
            .order_by(desc(ActivityLog.created_at))
            .limit(500)
            .all()
        )
    # 1) subtitle_crawl / subtitle_pair / subtitle_import 用 task_id 关联
    # 2) asmr_sync 的 resource_downloaded / resource_uploaded 子行也通过 task_id 关联
    # 3) circle_completion 的 download_item_queued 也走 task_id
    if parent.task_id and parent.category in {
        "subtitle_crawl", "subtitle_pair", "subtitle_import",
        "asmr_sync", "circle_completion",
        "auto_import", "process_existing", "extract", "upload", "pipeline_rename", "pipeline_delete",
    }:
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.task_id == parent.task_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(500)
            .all()
        )

    # session_id 是 detail JSON 里常见的强关联字段（asmr_sync / circle_completion / pipeline_filter）
    # SQL 层用 JSONB 反查出来，避免漏拉子行
    parent_detail = parent.detail if isinstance(parent.detail, dict) else {}
    related_session_id = str(
        parent_detail.get("session_id")
        or parent_detail.get("execution_key")
        or ""
    ).strip()
    if related_session_id and len(related_session_id) >= 8:
        try:
            session_rows = (
                db.query(ActivityLog)
                .filter(
                    or_(
                        ActivityLog.session_key == related_session_id,
                        ActivityLog.detail.op("->>")("session_id") == related_session_id,
                    )
                )
                .order_by(desc(ActivityLog.created_at))
                .limit(500)
                .all()
            )
            _extend(session_rows)
        except Exception:
            logger.debug("[操作记录] 按 session_id 反查关联行失败", exc_info=True)

    merged = merge_activity_rows([parent] + related_rows)

    # 三种情况：
    # 1) parent 自己就是 merge 的顶级行（多数情况）→ 直接拿
    # 2) parent 被合并成 root 的某个 child_rows 节点 → 返回那个 root，更完整
    # 3) parent 没被合并 / merge 没产生输出 → 兜底返回 parent.to_dict()
    main_row = None
    container_root = None

    def _find_in_tree(node):
        if not isinstance(node, dict):
            return False
        if str(node.get("id")) == str(parent.id):
            return True
        children = node.get("detail", {}).get("child_rows") if isinstance(node.get("detail"), dict) else None
        if isinstance(children, list):
            for child in children:
                if _find_in_tree(child):
                    return True
        return False

    for item in merged:
        if str(item.get("id")) == str(parent.id):
            main_row = item
            break
        if _find_in_tree(item):
            container_root = item
            # 不立刻 break：继续看后面是不是有 parent 自己作为 root（更精确）

    if main_row is None and container_root is not None:
        main_row = container_root
    if main_row is None:
        main_row = parent.to_dict()

    # 复用 list 接口的"批次父行子任务状态聚合"，保证抽屉头部状态徽章和列表行口径一致。
    # aggregator 已经在 main_row 是 batch_start 时跑过一次 partial_success/failed 升级，
    # 但实际生产里子任务 detail 里 batch_id 可能没写（task.metadata 没正确注入等），
    # aggregator 就匹配不上、status 留在原始 success。这里再做一次基于 ActivityLog.batch_id
    # 列的轻量回查兜底（拿同一条 SQL 也能补 lite 路径的口径）。
    try:
        if isinstance(main_row, dict):
            _enrich_lite_items_with_batch_summary([main_row], db, force=True)
    except Exception:
        logger.debug("[操作记录] detail 批次状态聚合回填失败（不阻断主流程）", exc_info=True)
    try:
        if isinstance(main_row, dict):
            _enrich_baidu_netdisk_activity_detail_from_task(main_row, db)
    except Exception:
        logger.debug("[操作记录] detail 百度网盘字段回填失败（不阻断主流程）", exc_info=True)

    return {
        "row": main_row,
    }


@app.post("/api/activity-logs/compact")
async def compact_activity_logs(
    older_than_days: int = 30,
    min_detail_bytes: int = 8192,
    max_rows: Optional[int] = None,
    chunk_size: int = 200,
    time_budget_seconds: float = 5.0,
):
    """归档压缩老的操作记录 detail。

    用户场景：长期使用后 ``activity_logs.detail`` 会被批量任务 / 删除预审 / 社团补全
    塞进大量"全量 items"，单条最高 660KB。本接口把 ``older_than_days`` 之前的
    detail 中可裁剪的列表 / 大字符串字段清掉，只保留 metric / 摘要 / 关键字段。

    特点：
    - **不删除任何行**——所有操作记录都还在，只是详情瘦身了；
    - 分批执行，可多次调用直到 ``done=True``；
    - 仅压缩 ``detail`` 大于 ``min_detail_bytes`` 的记录；
    - 每条压缩后的记录会标 ``__compacted=True``，前端可显示"已归档"小标签。
    """
    from ..core.activity_log_compactor import compact_old_activity_logs
    from ..core.activity_log_writer import get_activity_log_query_cache, get_activity_log_row_dict_cache

    try:
        result = compact_old_activity_logs(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            max_rows=max_rows,
            chunk_size=chunk_size,
            time_budget_seconds=time_budget_seconds,
        )
        # 压缩动了底表 → 让缓存失效，避免下次列表请求拿到旧的合并结果
        if result.get("updated"):
            try:
                get_activity_log_query_cache().invalidate()
                get_activity_log_row_dict_cache().invalidate()
            except Exception:
                logger.debug("[操作记录] 压缩后失效缓存出错（非致命）", exc_info=True)
        return {
            "message": (
                f"压缩完成，更新 {result.get('updated', 0)} 行，节省约 "
                f"{result.get('saved_bytes', 0) / 1024 / 1024:.2f} MB"
                if result.get("done")
                else f"本轮处理 {result.get('scanned')} 行，仍未结束，请再次调用"
            ),
            **result,
        }
    except Exception as e:
        logger.error(f"压缩操作记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"压缩操作记录失败: {str(e)}")


@app.get("/api/activity-logs/compact/estimate")
def estimate_activity_logs_compact(
    older_than_days: int = 30,
    min_detail_bytes: int = 8192,
    sample_limit: int = 200,
):
    """快速估算"压缩老操作记录"能省多少空间，不写表。前端用于显示按钮文案。"""
    from ..core.activity_log_compactor import estimate_compact_savings

    try:
        return estimate_compact_savings(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            sample_limit=sample_limit,
        )
    except Exception as e:
        logger.error(f"估算操作记录压缩收益失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"估算操作记录压缩收益失败: {str(e)}")


@app.get("/api/activity-logs/search-status")
def activity_logs_search_status():
    """查询当前操作记录搜索引擎状态 + 后台重建进度。

    返回：
    - search_enabled: 是否启用 PostgreSQL pg_trgm 索引
    - tokenizer: 固定为 pg_trgm
    - trigram_supported: 当前库是否已启用 pg_trgm 扩展
    - row_count / fts_row_count: 主表行数 / 已被索引覆盖的行数
    - needs_upgrade: PostgreSQL 下固定 false
    - rebuild: 后台重建任务的最新状态（running / copied / total / ok / reason）

    前端：
    - ActivityHistory 搜索框旁的小指示灯 / Settings 维护卡片
    """
    from ..models.database import (
        activity_logs_fts_status,
        get_activity_logs_fts_rebuild_state,
    )
    info = activity_logs_fts_status()
    info["rebuild"] = get_activity_logs_fts_rebuild_state()
    return info


@app.post("/api/activity-logs/rebuild-fts")
def trigger_activity_logs_rebuild_fts(
    target_tokenizer: Optional[str] = None,
):
    """手动触发后台重建操作记录 PostgreSQL trigram 索引。

    返回：
    - started: True 表示新启动了任务；False = 已经在跑（带 reason: already_running）
    - state: 当前任务快照（running / copied / total / ok / reason）
    """
    from ..models.database import (
        activity_logs_fts_status,
        trigger_activity_logs_fts_rebuild,
    )
    desired = (target_tokenizer or "trigram").strip().lower()
    info = activity_logs_fts_status()
    if not info.get("fts_enabled"):
        raise HTTPException(status_code=400, detail="当前 PostgreSQL 未启用 pg_trgm，无法重建搜索索引")
    if desired in {"trigram", "pg_trgm"} and not info.get("trigram_supported"):
        raise HTTPException(status_code=400, detail="当前 PostgreSQL 未启用 pg_trgm 扩展")
    return trigger_activity_logs_fts_rebuild(target_tokenizer=desired)


@app.get("/api/database/maintenance/estimate")
def database_maintenance_estimate(
    older_than_days: int = 30,
    min_detail_bytes: int = 8192,
    sample_limit: int = 200,
):
    """估算 PostgreSQL 维护能释放多少空间，并返回库、表、索引大小。

    上层 Settings 维护卡片就用这一个接口渲染：
    - database / activity_logs / library_index_entries 当前字节
    - compact 估算（采样外推）
    - pg_trgm 索引大小
    """
    from ..core.database_maintenance_service import estimate as _estimate

    try:
        return _estimate(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            sample_limit=sample_limit,
        )
    except Exception as e:
        logger.error(f"数据库瘦身估算失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"数据库瘦身估算失败: {str(e)}")


@app.get("/api/database/maintenance/health")
def database_maintenance_health(full: bool = False):
    """执行 PostgreSQL SELECT 1 健康检查；full=true 时额外 ANALYZE 热点表。"""
    from ..models.database import check_database_health

    try:
        result = check_database_health(full=full)
        status = 200 if result.get("ok") else 503
        return JSONResponse(status_code=status, content=result)
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"数据库健康检查失败: {str(e)}")


@app.get("/api/database/maintenance/performance")
def database_maintenance_performance(limit: int = 10):
    """读取 PostgreSQL 性能快照：关键运行参数、慢 SQL Top N、热点表扫描/死元组统计。"""
    from ..core.database_maintenance_service import performance_snapshot

    try:
        return performance_snapshot(limit=limit)
    except Exception as e:
        logger.error(f"读取 PostgreSQL 性能快照失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取 PostgreSQL 性能快照失败: {str(e)}")


@app.get("/api/database/maintenance/search-status")
def database_maintenance_search_status():
    """读取各业务搜索域的 PostgreSQL trigram 索引状态。"""
    from ..core.database_maintenance_service import search_status_snapshot

    try:
        return search_status_snapshot()
    except Exception as e:
        logger.error(f"读取 PostgreSQL 搜索索引状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取 PostgreSQL 搜索索引状态失败: {str(e)}")


@app.post("/api/database/maintenance/pg-stat-statements/reset")
def database_maintenance_reset_pg_stat_statements():
    """重置 pg_stat_statements 统计，用于优化前后对比。"""
    from ..core.database_maintenance_service import reset_pg_stat_statements

    result = reset_pg_stat_statements()
    if not result.get("ok"):
        return JSONResponse(status_code=409, content=result)
    return result


@app.post("/api/database/maintenance/shrink")
async def database_maintenance_shrink(
    older_than_days: int = 30,
    min_detail_bytes: int = 8192,
):
    """启动一次 PostgreSQL 数据库维护（异步线程，立即返回）。

    串联：
    1. ``compact_old_activity_logs`` 直到 done
    2. ``VACUUM (ANALYZE)``
    3. ``REINDEX`` pg_trgm 搜索索引

    幂等：同一时刻只允许一个瘦身在跑。已经在跑时返回 ``already_running=True``。
    前端拿到响应后用 ``GET /api/database/maintenance/shrink/status`` 轮询进度。
    """
    from ..core.database_maintenance_service import start_shrink

    try:
        return start_shrink(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
        )
    except Exception as e:
        logger.error(f"启动数据库瘦身失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动数据库瘦身失败: {str(e)}")


@app.get("/api/database/maintenance/shrink/status")
def database_maintenance_shrink_status():
    """读当前瘦身任务的状态机快照。"""
    from ..core.database_maintenance_service import get_status

    try:
        return get_status()
    except Exception as e:
        logger.error(f"读取数据库瘦身状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取数据库瘦身状态失败: {str(e)}")


@app.post("/api/database/maintenance/shrink/reset")
def database_maintenance_shrink_reset():
    """瘦身完成 / 失败后，前端可以通过这个接口把状态机清回 idle，
    便于下次进入卡片时不再看到上一次的结果残留。运行中调用无效。"""
    from ..core.database_maintenance_service import reset_status, get_status

    try:
        reset_status()
        return get_status()
    except Exception as e:
        logger.error(f"重置数据库瘦身状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重置数据库瘦身状态失败: {str(e)}")


@app.get("/api/database/maintenance/library-index-fts/status")
def library_index_fts_maintenance_status():
    """读取库存 PostgreSQL 搜索索引状态和后台重建进度。"""
    from ..core.library_index.fts import (
        get_library_index_fts_rebuild_state,
        library_index_fts_status,
    )

    try:
        info = library_index_fts_status()
        rebuild = get_library_index_fts_rebuild_state()
        return {
            **info,
            "state": rebuild.get("state"),
            "total_entries": rebuild.get("total_entries", info.get("row_count", 0)),
            "indexed_entries": rebuild.get("indexed_entries", info.get("fts_row_count", 0)),
            "started_at": rebuild.get("started_at"),
            "finished_at": rebuild.get("finished_at"),
            "error": rebuild.get("error"),
            "rebuild": rebuild,
        }
    except Exception as e:
        logger.error(f"读取库存搜索索引状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取库存搜索索引状态失败: {str(e)}")


@app.post("/api/database/maintenance/library-index-fts/rebuild")
def trigger_library_index_fts_maintenance_rebuild(
    target_tokenizer: Optional[str] = None,
):
    """后台重建库存 PostgreSQL trigram 搜索索引。"""
    from ..core.library_index.fts import (
        FTS_PREFERRED_TOKENIZE,
        library_index_fts_status,
        trigger_library_index_fts_rebuild,
    )

    try:
        desired = (target_tokenizer or FTS_PREFERRED_TOKENIZE).strip().lower()
        info = library_index_fts_status()
        if not info.get("fts_enabled"):
            raise HTTPException(status_code=400, detail="当前 PostgreSQL 未启用 pg_trgm，无法重建库存搜索索引")
        if desired == FTS_PREFERRED_TOKENIZE and not info.get("trigram_supported"):
            raise HTTPException(status_code=400, detail="当前 PostgreSQL 未启用 pg_trgm 扩展")
        return trigger_library_index_fts_rebuild(target_tokenizer=desired)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动库存搜索索引重建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动库存搜索索引重建失败: {str(e)}")


@app.post("/api/activity-logs/backfill-auto-import-extract")
async def backfill_auto_import_extract_activity_logs(
    start_offset: int = 0,
    chunk_size: int = 200,
    max_rows: Optional[int] = None,
    time_budget_seconds: float = 8.0,
):
    """分片回填旧导入链操作记录中的解压字段与文件树。

    Phase 1：不再一次性全表扫描 + os.walk，改为 offset 分片 + 时间预算。
    若返回 done=false，前端应带 next_offset 再次调用直到 done=true。
    """
    from ..core.activity_log_service import backfill_auto_import_extract_fields

    try:
        result = backfill_auto_import_extract_fields(
            chunk_size=chunk_size,
            start_offset=start_offset,
            max_rows=max_rows,
            time_budget_seconds=time_budget_seconds,
        )
        return {
            "message": (
                "导入链操作记录字段与文件树回填完成"
                if result.get("done")
                else f"本轮处理 {result.get('scanned')} 行，未完成，请带 next_offset 继续"
            ),
            **result,
        }
    except Exception as e:
        logger.error(f"回填导入链操作记录字段失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"回填导入链操作记录字段失败: {str(e)}")


@app.post("/api/activity-logs/rollups/backfill")
def backfill_activity_log_rollups(limit_groups: int = 2000):
    """后台回填操作历史轻量 rollup。"""
    from ..core.activity_log_rollup_service import get_activity_log_rollup_service

    try:
        return get_activity_log_rollup_service().trigger_backfill(limit_groups=limit_groups)
    except Exception as e:
        logger.error(f"启动操作历史 rollup 回填失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动操作历史 rollup 回填失败: {str(e)}")


@app.get("/api/activity-logs/rollups/backfill/status")
def activity_log_rollup_backfill_status():
    """读取操作历史 rollup 后台回填状态。"""
    from ..core.activity_log_rollup_service import get_activity_log_rollup_backfill_state

    return get_activity_log_rollup_backfill_state()


@app.get("/api/activity-logs/rollups/diff")
def diff_activity_log_rollups(limit_groups: int = 2000):
    """对照操作历史 rollup 与原始 activity_logs 聚合计数。"""
    from ..core.activity_log_rollup_service import get_activity_log_rollup_service

    try:
        return get_activity_log_rollup_service().diff(limit_groups=limit_groups)
    except Exception as e:
        logger.error(f"校验操作历史 rollup 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"校验操作历史 rollup 失败: {str(e)}")


CORS_ALLOWED_ORIGINS = [
    "http://localhost:5556",
    "http://127.0.0.1:5556",
]
CORS_ALLOWED_ORIGIN_RE = re.compile(
    r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$"
)


def _is_allowed_cors_origin(origin: str) -> bool:
    text = str(origin or "").strip()
    return text in CORS_ALLOWED_ORIGINS or bool(CORS_ALLOWED_ORIGIN_RE.match(text))


def _append_vary_origin(response: Response) -> None:
    current = str(response.headers.get("Vary") or "").strip()
    values = [item.strip() for item in current.split(",") if item.strip()]
    if not any(item.lower() == "origin" for item in values):
        values.append("Origin")
    response.headers["Vary"] = ", ".join(values)


def _with_gate_cors_headers(request: Request, response: Response) -> Response:
    origin = str(request.headers.get("origin") or "").strip()
    if origin and _is_allowed_cors_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        _append_vary_origin(response)
    return response


# CORS配置
app.add_middleware(
    CORSMiddleware,
    # 开发态前端走 5556，API 直连 5555，避免大量 /api 代理请求占满 Vite
    # 同源连接后把页面 HTML / JS 也一起堵住。由于安全门依赖 cookie，
    # 这里不能再用 allow_origins=["*"] + allow_credentials=True。
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=CORS_ALLOWED_ORIGIN_RE.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SECURITY_GATE_PUBLIC_API_PATHS = {
    "/api/health",
    "/api/http-download/google-drive/oauth-callback",
    "/api/security-gate/status",
    "/api/security-gate/verify",
}

_SLOW_API_LOG_THRESHOLD_SECONDS = float(os.getenv("KIKOERUMANAGER_SLOW_API_SECONDS", "0.5") or 0.5)
_IMPORTANT_API_4XX_STATUSES = {400, 401, 403, 409, 422}
_SLOW_API_QUERY_ALLOWLIST = {
    "category",
    "circle_id",
    "include_stats",
    "include_dl_only",
    "library_id",
    "limit",
    "lite",
    "mode",
    "offset",
    "only_downloadable",
    "only_missing",
    "page",
    "page_size",
    "q",
    "query",
    "status",
    "type",
}


def _slow_api_query_snapshot(request: Request) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key in _SLOW_API_QUERY_ALLOWLIST:
            params[key] = str(value)[:120]
    return params


def _slow_api_context_snapshot(request: Request) -> Dict[str, Any]:
    state = getattr(request, "state", None)
    context = getattr(state, "slow_api_context", None)
    if not isinstance(context, dict):
        return {}
    safe: Dict[str, Any] = {}
    for key, value in context.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float)):
            safe[key] = value
        elif isinstance(value, (list, tuple, set)):
            safe[key] = len(value)
        else:
            safe[key] = str(value)[:120]
    return safe


def _slow_api_resource_budget_snapshot() -> Dict[str, Dict[str, int]]:
    """慢请求日志里的资源预算摘要，只保留活跃/等待计数。"""
    try:
        from ..core.resource_budget_service import get_resource_budget_service

        snapshot = get_resource_budget_service().snapshot()
        resources = snapshot.get("resources") if isinstance(snapshot, dict) else {}
        if not isinstance(resources, dict):
            return {}
        result: Dict[str, Dict[str, int]] = {}
        for name, state in resources.items():
            if not isinstance(state, dict):
                continue
            active = int(state.get("active") or 0)
            waiting = int(state.get("waiting") or 0)
            if active <= 0 and waiting <= 0:
                continue
            result[str(name)] = {"active": active, "waiting": waiting}
        return result
    except Exception:
        return {}


async def _call_next_with_perf_log(request: Request, call_next):
    headers = getattr(request, "headers", {}) or {}
    request_id = str(headers.get("X-Request-ID") or "").strip()[:80] or uuid.uuid4().hex[:12]
    state = getattr(request, "state", None)
    if state is None:
        state = SimpleNamespace()
        try:
            request.state = state
        except Exception:
            pass
    state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = time.perf_counter() - started
        if request.url.path.startswith("/api/"):
            logger.exception(
                "[API请求] request_id=%s method=%s path=%s status=exception elapsed_ms=%.0f query=%s context=%s resource_budget=%s",
                request_id,
                request.method,
                request.url.path,
                elapsed * 1000,
                _slow_api_query_snapshot(request),
                _slow_api_context_snapshot(request),
                _slow_api_resource_budget_snapshot(),
            )
        raise
    elapsed = time.perf_counter() - started
    path = request.url.path
    status_code = int(getattr(response, "status_code", 0) or 0)
    if path.startswith("/api/"):
        is_slow = _SLOW_API_LOG_THRESHOLD_SECONDS > 0 and elapsed >= _SLOW_API_LOG_THRESHOLD_SECONDS
        is_error = status_code >= 500
        is_important_4xx = status_code in _IMPORTANT_API_4XX_STATUSES
        if is_slow or is_error or is_important_4xx:
            log_method = logger.error if is_error else logger.warning
            reason = "慢请求" if is_slow else ("异常请求" if is_error else "重要4xx")
            log_method(
                "[API请求] %s request_id=%s method=%s path=%s status=%s elapsed_ms=%.0f query=%s context=%s resource_budget=%s slow=%s",
                reason,
                request_id,
                request.method,
                path,
                status_code,
                elapsed * 1000,
                _slow_api_query_snapshot(request),
                _slow_api_context_snapshot(request),
                _slow_api_resource_budget_snapshot(),
                is_slow,
            )
    try:
        response.headers["X-Request-ID"] = request_id
    except Exception:
        pass
    return response


def _log_gate_api_rejection(request: Request, status_code: int, reason: str) -> None:
    request_id = str(request.headers.get("X-Request-ID") or "").strip()[:80] or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    logger.warning(
        "[API请求] request_id=%s method=%s path=%s status=%s reason=%s query=%s context=%s resource_budget=%s",
        request_id,
        request.method,
        request.url.path,
        status_code,
        reason,
        _slow_api_query_snapshot(request),
        _slow_api_context_snapshot(request),
        _slow_api_resource_budget_snapshot(),
    )


@app.middleware("http")
async def security_gate_middleware(request: Request, call_next):
    """系统入口门禁：启用且完成绑定后，默认保护所有业务页面和 API。"""
    service = get_security_gate_service()
    path = request.url.path

    if (
        not service.is_enforced()
        or request.method.upper() == "OPTIONS"
        or path in ("/verify", "/blocked", "/favicon.ico")
        or path.startswith("/assets/")
        or path.startswith("/docs")
        or path.startswith("/openapi.json")
        or path in SECURITY_GATE_PUBLIC_API_PATHS
    ):
        return await _call_next_with_perf_log(request, call_next)

    ip_address = service.get_client_ip(request)
    blocked = service.get_active_blacklist(ip_address)
    if blocked:
        service.record_blocked_visit(request, blocked)
        if path.startswith("/api/"):
            _log_gate_api_rejection(request, 403, "security_gate_blocked")
            response = _with_gate_cors_headers(
                request,
                JSONResponse({"detail": "当前来源已被系统阻止", "blocked": True}, status_code=403),
            )
            response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")
            return response
        return RedirectResponse(url="/blocked", status_code=303)

    token = request.cookies.get(COOKIE_NAME, "")
    if service.verify_cookie(token):
        return await _call_next_with_perf_log(request, call_next)

    if path.startswith("/api/"):
        _log_gate_api_rejection(request, 401, "security_gate_required")
        response = _with_gate_cors_headers(
            request,
            JSONResponse({"detail": "需要通过系统门禁验证", "gate_required": True}, status_code=401),
        )
        response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")
        return response
    next_path_raw = str(request.url.path or "/")
    if request.url.query:
        next_path_raw = f"{next_path_raw}?{request.url.query}"
    next_path = quote(next_path_raw, safe="/")
    return RedirectResponse(url=f"/verify?next={next_path}", status_code=303)

def _notification_cleanup_config() -> tuple[int, int]:
    """读取通知清理策略，避免后台任务使用硬编码保留期。"""
    cfg = getattr(get_config(), "notification_center", None)
    retain_days = int(getattr(cfg, "retain_days", 30) or 30)
    max_items = int(getattr(cfg, "max_items", 200) or 200)
    return max(1, retain_days), max(1, max_items)


def _activity_log_compact_config() -> dict:
    """后台操作记录压缩参数。用环境变量微调，默认保持温和。"""
    return {
        "older_than_days": max(1, int(os.getenv("KIKOERUMANAGER_ACTIVITY_COMPACT_DAYS", "30") or 30)),
        "min_detail_bytes": max(0, int(os.getenv("KIKOERUMANAGER_ACTIVITY_COMPACT_MIN_BYTES", str(8 * 1024)) or (8 * 1024))),
        "max_rows": max(100, int(os.getenv("KIKOERUMANAGER_ACTIVITY_COMPACT_MAX_ROWS", "5000") or 5000)),
        "time_budget_seconds": max(1.0, float(os.getenv("KIKOERUMANAGER_ACTIVITY_COMPACT_SECONDS", "8.0") or 8.0)),
    }


def _task_phase_metric_cleanup_config() -> dict:
    """任务阶段指标清理参数。只清理性能观测表，不影响业务数据。"""
    return {
        "retain_days": max(1, int(os.getenv("KIKOERUMANAGER_TASK_PHASE_METRIC_RETAIN_DAYS", "14") or 14)),
        "max_items": max(100, int(os.getenv("KIKOERUMANAGER_TASK_PHASE_METRIC_MAX_ITEMS", "5000") or 5000)),
    }


# 通知定期清理协程（每24h按 notification_center.retain_days / max_items 清理已读通知）
async def _periodic_notification_cleanup():
    while True:
        try:
            await asyncio.sleep(24 * 3600)
            from ..core.task_notification_service import cleanup_old_notifications
            retain_days, max_items = _notification_cleanup_config()
            deleted = cleanup_old_notifications(retain_days=retain_days, max_items=max_items)
            if deleted > 0:
                logger.info(
                    "[通知清理] 已清理 %s 条旧通知 retain_days=%s max_items=%s",
                    deleted,
                    retain_days,
                    max_items,
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[通知清理] 定期清理异常: {e}")


# 操作记录后台压缩协程（每 24h 跑一次，把 30 天前的大 detail 瘦身）
async def _periodic_activity_log_compact():
    # 启动 30 分钟后再开第一次，避免和首屏抢 IO
    await asyncio.sleep(30 * 60)
    while True:
        try:
            from ..core.activity_log_compactor import compact_old_activity_logs

            # 单次有行数和时间预算，剩下的下次再来。
            result = compact_old_activity_logs(**_activity_log_compact_config())
            if result.get("updated"):
                logger.info(
                    "[操作记录] 自动压缩 %d 行，节省 %.2f MB",
                    result.get("updated", 0),
                    result.get("saved_bytes", 0) / 1024 / 1024,
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[操作记录] 自动压缩异常: {e}")
        await asyncio.sleep(24 * 3600)


# 任务阶段指标后台清理协程（每 24h 控制观测表体积）
async def _periodic_task_phase_metric_cleanup():
    await asyncio.sleep(45 * 60)
    while True:
        try:
            from ..core.task_phase_metric_service import get_task_phase_metric_service

            result = get_task_phase_metric_service().cleanup(**_task_phase_metric_cleanup_config())
            if result.get("deleted"):
                logger.info(
                    "[任务阶段指标] 自动清理 %s 条 retain_days=%s max_items=%s",
                    result.get("deleted", 0),
                    result.get("retain_days"),
                    result.get("max_items"),
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[任务阶段指标] 自动清理异常: {e}")
        await asyncio.sleep(24 * 3600)


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    _start_event_loop_watchdog()

    # 抬高 starlette 默认 threadpool 上限：FastAPI 的同步路由（def 而非 async def）
    # 都跑在这个池里，默认 40 在群晖 + SMB + 多任务并发时容易顶满，连环超时。
    # 80 对单实例桌面 / 中小 NAS 已经很宽裕，CPU / 内存压力可控。
    try:
        from anyio import to_thread as _anyio_to_thread
        _anyio_to_thread.current_default_thread_limiter().total_tokens = 80
    except Exception:
        logger.warning("[启动] 调整 anyio threadpool 上限失败，沿用默认值", exc_info=True)

    # 抬高 asyncio 默认 ThreadPoolExecutor 上限：
    # asyncio.to_thread 和 loop.run_in_executor(None, ...) 走这个池——
    # 和 anyio 那个池是两个独立的池！
    # 默认大小 = min(32, cpu_count + 4)，Docker 容器里 cpu_count 常常只有 2-4，
    # 真实槽位只有 6-8 个。一旦多个并发 IO（shutil.move / rmtree、数据库写、
    # task_engine 的清理动作）撞上来，槽就吃光了，新调用得排队。
    # 这里固定 32 槽，兜底防止再出现"邮件卡死把整个后台 IO 拖跨"那种连锁。
    try:
        import concurrent.futures as _cf
        _default_pool = _cf.ThreadPoolExecutor(max_workers=32, thread_name_prefix="asyncio-default")
        asyncio.get_event_loop().set_default_executor(_default_pool)
        logger.info("[启动] asyncio 默认线程池扩容: max_workers=32")
    except Exception:
        logger.warning("[启动] 调整 asyncio 默认线程池失败，沿用默认值", exc_info=True)

    # 初始化数据库
    init_db()

    # Redis 是运行态高频链路的外部依赖；required=true 时不可用则阻断启动。
    from ..core.redis_service import get_redis_service
    redis_service = get_redis_service()
    redis_service.startup_check()
    if redis_service.is_enabled():
        from ..core.dlsite_bonus_probe_service import get_dlsite_bonus_probe_service
        get_dlsite_bonus_probe_service().start_cache_flush_worker()

    from ..core.circle_external_search_service import get_circle_external_search_service
    await get_circle_external_search_service().start()

    # 只纠正上次进程中断遗留的 syncing 状态；不自动重建库存索引。
    try:
        get_library_index_service().normalize_all_interrupted_syncing_statuses()
    except Exception:
        logger.warning("[启动] 纠正库存索引同步状态失败", exc_info=True)
    try:
        start_library_index_mutation_service()
    except Exception:
        logger.warning("[启动] 库存索引 materializer 启动失败", exc_info=True)
    try:
        start_library_index_watcher_driver()
    except Exception:
        logger.warning("[启动] 库存索引 watcher 启动失败", exc_info=True)

    # 启动任务引擎
    engine = get_task_engine()
    engine.start()

    # 如果配置了自动启动监视器，则启动
    config = get_config()
    if config.watcher.enabled:
        watcher = get_watcher()
        watcher.start()

    # 启动密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.start()

    # 启动已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.start()

    # 扫描已处理压缩包目录，同步数据库（根据配置决定是否启用）
    config = get_config()
    if config.processed_archive_cleanup.scan_on_startup:
        try:
            await scan_processed_archives()
        except Exception:
            # 远程挂载短暂不可读时不能阻断服务启动；扫描本身已保证不会把失败
            # 快照当作空目录清理数据库记录。
            logger.warning("启动时扫描已处理压缩包目录失败，已保留现有记录", exc_info=True)
    else:
        logger.info("启动时扫描已处理压缩包目录已禁用")

    # 必须在启动扫描完成后再消费队列，避免扫描观察到半组已发布分卷。
    try:
        from ..core.deferred_archive_service import get_deferred_archive_service

        await get_deferred_archive_service().start()
    except Exception:
        logger.warning("启动空闲归档队列失败，待归档源文件将保留等待下次恢复", exc_info=True)

    # 启动 DLsite 邮件监听服务（IMAP IDLE）
    from ..core.email_watcher_service import get_email_watcher_service
    email_watcher = get_email_watcher_service()
    await email_watcher.start()

    # 启动通知中心 outbox 发件 worker
    from ..core.notification_template_service import ensure_default_email_templates
    ensure_default_email_templates()
    from ..core.task_notification_service import start_outbox_worker
    asyncio.create_task(start_outbox_worker())

    # 启动通知定期清理任务（每天清理超7天的旧通知）
    asyncio.create_task(_periodic_notification_cleanup())

    # 启动操作记录定期压缩任务（每天压缩 30 天前的大 detail，避免无限膨胀）
    asyncio.create_task(_periodic_activity_log_compact())

    # 启动任务阶段指标清理任务（性能观测表只保留近期样本）
    asyncio.create_task(_periodic_task_phase_metric_cleanup())

# 关闭事件
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    try:
        stop_library_index_watcher_driver()
    except Exception:
        logger.warning("关闭库存索引 watcher 失败", exc_info=True)
    try:
        stop_library_index_mutation_service()
    except Exception:
        logger.warning("关闭库存索引 materializer 失败", exc_info=True)
    await _stop_event_loop_watchdog()
    _shutdown_log_io_executor()

    # 停止 DLsite 邮件监听服务
    from ..core.email_watcher_service import get_email_watcher_service
    await get_email_watcher_service().stop()

    # 先停止低优先级归档。它会在安全复制边界释放 lease，不能与后续 task engine
    # 关闭并发让出前台资源。
    try:
        from ..core.deferred_archive_service import get_deferred_archive_service

        await get_deferred_archive_service().stop()
    except Exception:
        logger.warning("关闭空闲归档队列失败，将等待 lease 过期恢复", exc_info=True)

    # 停止任务引擎
    engine = get_task_engine()
    engine.stop()

    # 停止监视器
    watcher = get_watcher()
    watcher.stop()

    # 停止库存后台 worker（本地索引追赶等）
    try:
        shutdown_library_manager_background_workers()
    except Exception:
        logger.warning("关闭库存后台 worker 失败", exc_info=True)

    # 停止密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.stop()

    # 停止已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.stop()

    # Flush DLsite 特典探测 Redis dirty buffer，确保关停前尽量回写 PostgreSQL。
    try:
        from ..core.dlsite_bonus_probe_service import get_dlsite_bonus_probe_service
        await get_dlsite_bonus_probe_service().stop_cache_flush_worker()
    except Exception:
        logger.warning("关闭 DLsite 特典缓存回写 worker 失败", exc_info=True)

    try:
        from ..core.circle_external_search_service import get_circle_external_search_service

        await get_circle_external_search_service().stop()
    except Exception:
        logger.warning("关闭社团外部搜索 worker 失败", exc_info=True)

    # Flush 操作记录后台写入器，确保任务 finally 刚入队的审计不丢
    try:
        from ..core.activity_log_writer import (
            shutdown_activity_log_writer,
            shutdown_lifecycle_executor,
        )
        shutdown_lifecycle_executor(timeout=5.0)
        shutdown_activity_log_writer(timeout=5.0)
    except Exception:
        logger.warning("关闭操作记录写入器失败", exc_info=True)

# Pydantic模型
class TaskCreate(BaseModel):
    source_path: str
    task_type: str = "auto_process"
    auto_classify: bool = True
    target_library_id: Optional[str] = None

class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    source_path: str
    output_path: Optional[str]
    progress: int
    current_step: str
    error_message: Optional[str]
    rjcode: Optional[str] = None
    
    class Config:
        from_attributes = True


_TASK_RUNTIME_ACTIVE_STATUSES = {"pending", "processing", "paused", "waiting_manual", "waiting_retry"}
_TASK_RUNTIME_METADATA_OVERLAY_KEYS = (
    "download_files",
    "download_runtime",
    "failed_files",
    "upload_runtime",
    "bonus_probe_meta",
    "progress_log",
    "awaiting_manual_match",
    "manual_match_completed",
    "manual_match_completed_at",
    "manual_match_applied_pairs",
    "manual_match_deleted_subtitles",
    "naming_strategy",
    "ai_match_status",
    "ai_match_mode",
    "ai_auto_applied",
    "ai_low_confidence_count",
    "ai_unmatched_audio_count",
    "ai_unmatched_subtitle_count",
)


def _task_enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else (value or ""))


def _task_status_value(task: Any) -> str:
    return _task_enum_value(getattr(task, "status", ""))


def _task_type_value(task: Any) -> str:
    return _task_enum_value(getattr(task, "type", ""))


def _redis_runtime_for_route_task(task: Any) -> Dict[str, Any]:
    task_id = str(getattr(task, "id", "") or "").strip()
    if not task_id:
        return {}
    try:
        from ..core.redis_service import get_redis_service

        payload = get_redis_service().get_task_runtime_sync(task_id)
        return dict(payload or {}) if isinstance(payload, dict) else {}
    except Exception:
        logger.debug("[Redis] 路由读取任务运行态失败: task_id=%s", task_id, exc_info=True)
        return {}


def _should_apply_redis_task_runtime(task: Any, runtime: Dict[str, Any]) -> bool:
    if not runtime:
        return False
    if _task_status_value(task) not in _TASK_RUNTIME_ACTIVE_STATUSES:
        return False
    runtime_status = str(runtime.get("status") or "").strip()
    return not runtime_status or runtime_status in _TASK_RUNTIME_ACTIVE_STATUSES


def _task_runtime_response_values(task: Any, runtime: Optional[Dict[str, Any]] = None) -> tuple[str, int, str]:
    runtime = runtime if isinstance(runtime, dict) else _redis_runtime_for_route_task(task)
    status_value = _task_status_value(task)
    progress = int(getattr(task, "progress", 0) or 0)
    current_step = str(getattr(task, "current_step", "") or "")
    if not _should_apply_redis_task_runtime(task, runtime):
        return status_value, progress, current_step
    runtime_status = str(runtime.get("status") or "").strip()
    if runtime_status:
        status_value = runtime_status
    if runtime.get("progress") is not None:
        try:
            progress = int(runtime.get("progress") or 0)
        except Exception:
            pass
    runtime_step = str(runtime.get("current_step") or "").strip()
    if runtime_step:
        current_step = runtime_step
    return status_value, progress, current_step


def _task_metadata_with_redis_runtime(task: Any) -> Dict[str, Any]:
    metadata = dict(getattr(task, "task_metadata", None) or {})
    runtime = _redis_runtime_for_route_task(task)
    if not _should_apply_redis_task_runtime(task, runtime):
        return metadata
    for key in _TASK_RUNTIME_METADATA_OVERLAY_KEYS:
        if key not in runtime:
            continue
        value = runtime.get(key)
        metadata[key] = list(value)[-80:] if key == "progress_log" and isinstance(value, list) else copy.deepcopy(value)
    updated_at = str(runtime.get("updated_at") or "").strip()
    if updated_at:
        metadata["redis_runtime_updated_at"] = updated_at
    return metadata


def _serialize_task_response(task: Any) -> TaskResponse:
    runtime = _redis_runtime_for_route_task(task)
    status_value, progress, current_step = _task_runtime_response_values(task, runtime)
    return TaskResponse(
        id=str(getattr(task, "id", "") or ""),
        type=_task_type_value(task),
        status=status_value,
        source_path=str(getattr(task, "source_path", "") or ""),
        output_path=getattr(task, "output_path", None),
        progress=progress,
        current_step=current_step,
        error_message=getattr(task, "error_message", None),
        rjcode=getattr(task, "rjcode", None),
    )


class TaskCenterOverviewResponse(BaseModel):
    generated_at: str
    total: int
    counts_by_domain: Dict[str, int]
    counts_by_status: Dict[str, int]
    highlight_counts: Dict[str, int]
    recent_items: List[Dict[str, Any]]
    active_items: List[Dict[str, Any]]


class TaskCenterListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    offset: int
    limit: int
    mode: str
    generated_at: str
    counts_by_domain: Dict[str, int] = Field(default_factory=dict)
    counts_by_status: Dict[str, int] = Field(default_factory=dict)
    highlight_counts: Dict[str, int] = Field(default_factory=dict)


class TaskCenterItemResponse(BaseModel):
    id: str
    entity_id: str
    engine_task_id: Optional[str] = None
    record_id: Optional[str] = None
    domain: str
    domain_label: str
    kind: str
    kind_label: str
    title: str
    subtitle: str
    source_label: str
    source_page: str
    source_action: str
    route_hint: str
    status: str
    status_label: str
    progress: int
    current_step: str
    error_message: str
    source_path: str
    target_path: str
    rjcode: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metrics: List[Dict[str, str]]
    actions: List[str]
    details: Dict[str, Any]


class TaskCenterActionRequest(BaseModel):
    action: str


class FilteredItemRestoreRequest(BaseModel):
    relative_path: Optional[str] = None


class ConfigResponse(BaseModel):
    storage: dict
    processing: dict
    watcher: dict
    extract: Optional[dict] = None
    filter: dict
    metadata: dict
    rename: dict
    classification: list
    password_cleanup: Optional[dict] = None
    processed_archive_cleanup: Optional[dict] = None
    path_mapping: Optional[dict] = None
    kikoeru_server: Optional[dict] = None
    asmr_sync: Optional[dict] = None
    http_downloader: Optional[dict] = None
    baidu_netdisk: Optional[dict] = None
    circle_external_search: Optional[dict] = None
    auto_process: Optional[dict] = None
    process_existing: Optional[dict] = None
    asmr_sync_step: Optional[dict] = None
    rj_subtitle: Optional[dict] = None
    ai_subtitle_matching: Optional[dict] = None
    backup_zip: Optional[dict] = None
    email_watcher: Optional[dict] = None
    notification_email: Optional[dict] = None
    notification_center: Optional[dict] = None
    redis: Optional[dict] = None
    bonus_probe: Optional[dict] = None
    resource_budget: Optional[dict] = None
    database: Optional[dict] = None
    security_gate: Optional[dict] = None
    ui: Optional[dict] = None


class LibraryViewPreferencesRequest(BaseModel):
    view_mode: str


class HttpDownloaderSecretRevealRequest(BaseModel):
    key: str
    account_id: Optional[str] = None


class BaiduNetdiskSecretRevealRequest(BaseModel):
    key: str


class NotificationEmailSecretRevealRequest(BaseModel):
    key: str


class AISubtitleSecretRevealRequest(BaseModel):
    key: str


class CircleExternalSearchSecretRevealRequest(BaseModel):
    key: str


class DatabaseSecretRevealRequest(BaseModel):
    key: str


class RedisSecretRevealRequest(BaseModel):
    key: str


class AISubtitleMatchTestRequest(BaseModel):
    config: Optional[dict] = None


class AISubtitleMatchModelsRequest(BaseModel):
    config: Optional[dict] = None


class AISubtitleProviderIconRequest(BaseModel):
    model: str = ""
    api_base: str = ""
    proxy_url: str = ""


class AISubtitleMatchPreviewRequest(BaseModel):
    audio_files: List[dict] = []
    subtitle_files: List[dict] = []
    ai_match_mode: str = "ai_assist"
    naming_strategy: str = "audio"
    enable_metadata_match: bool = True
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []
    ai_confidence_threshold: Optional[int] = None


# API路由
# 兼容层：旧任务接口仅保留给少数历史入口使用，新功能统一走 /api/task-center/*
@app.post("/api/tasks", response_model=TaskResponse, deprecated=True, summary="兼容层：创建原始引擎任务")
async def create_task(task_create: TaskCreate):
    """兼容层：创建原始引擎任务，新功能请改用任务中心聚合接口。"""
    from ..core.file_processor import get_file_processor

    file_processor = get_file_processor()
    config = get_config()

    # 使用 FileProcessor 处理文件
    task = await file_processor.process_file(
        task_create.source_path,
        auto_classify=task_create.auto_classify,
        wait_stable=False,  # 手动创建任务时不等待稳定
        is_processed=lambda path: False,  # 允许重新处理
        mark_processed=None
    )

    if not task:
        raise HTTPException(status_code=400, detail=f"无法处理文件: {task_create.source_path}")

    if task_create.target_library_id:
        task.task_metadata["target_library_id"] = task_create.target_library_id

    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        source_path=task.source_path,
        output_path=task.output_path,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        rjcode=task.rjcode
    )

# ========== 文件上传 API ==========
@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), target_library_id: Optional[str] = Form(None)):
    """上传文件并触发扫描（复用分卷识别逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 确保输入目录存在
    os.makedirs(input_path, exist_ok=True)

    uploaded_files = []

    for file in files:
        if not file.filename:
            continue

        # 保存文件到输入目录
        file_path = os.path.join(input_path, file.filename)

        _file_obj = file.file

        def _write_upload():
            with open(file_path, "wb") as _buf:
                shutil.copyfileobj(_file_obj, _buf)

        await asyncio.to_thread(_write_upload)

        uploaded_files.append(file_path)
        logger.info(f"上传文件: {file.filename} -> {file_path}")

    # 不再为每个文件单独创建任务
    # 改为调用扫描逻辑，复用分卷文件识别
    # 扫描逻辑会正确识别分卷文件，只为主文件创建任务
    scan_result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="upload_scan",
        source_label="仪表盘 / 上传后扫描",
        target_library_id=target_library_id,
    )
    if target_library_id and scan_result["task_ids"]:
        engine = get_task_engine()
        for task_id in scan_result["task_ids"]:
            task = engine.get_task(task_id)
            if task:
                task.task_metadata["target_library_id"] = target_library_id

    return {
        "message": f"成功上传 {len(uploaded_files)} 个文件，{scan_result['message']}",
        "uploaded_count": len(uploaded_files),
        "found_count": scan_result["found_count"],
        "task_ids": scan_result["task_ids"]
    }


async def _scan_and_create_tasks(
    *,
    source_page: str = "dashboard",
    source_action: str = "scan_input",
    source_label: str = "仪表盘 / 扫描导入",
    target_library_id: Optional[str] = None,
):
    """扫描输入目录并创建任务（使用 FileProcessor 统一处理逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 自动创建目录（如果不存在）
    if not os.path.exists(input_path):
        try:
            os.makedirs(input_path, exist_ok=True)
            logger.info(f"自动创建输入目录: {input_path}")
        except Exception as e:
            return {"message": f"无法创建输入目录: {str(e)}", "found_count": 0, "task_ids": []}

    watcher = get_watcher()
    file_processor = get_file_processor()
    from ..core.activity_log_service import log_import_batch_start_result

    batch_id = str(uuid.uuid4())
    batch_context = {
        "batch_id": batch_id,
        "session_id": batch_id,
        "batch_title": "批量解压入库",
        "batch_label": "解压入库批次",
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "log_parent": True,
    }
    report: dict[str, Any] = {
        "requested_count": 0,
        "created_count": 0,
        "skipped_processed_count": 0,
        "skipped_duplicate_count": 0,
    }

    # 使用 FileProcessor 统一处理目录
    tasks = await file_processor.process_directory(
        input_path,
        auto_classify=config.watcher.auto_classify,
        is_processed=lambda path: (
            path in watcher.pending_files or
            path in watcher._processed_files or
            any(t.source_path == path and t.status.value in ["pending", "processing"]
                for t in get_task_engine().get_all_tasks())
        ),
        mark_processed=watcher._mark_file_processed,
        task_metadata={"target_library_id": target_library_id} if target_library_id else None,
        batch_context=batch_context,
        report=report,
    )

    created_task_ids = [task.id for task in tasks]
    requested_count = int(report.get("requested_count") or len(tasks))
    created_tasks = [{"task_id": task.id, "source_path": task.source_path} for task in tasks]
    log_import_batch_start_result({
        "batch_id": batch_id,
        "requested_count": requested_count,
        "created_count": len(tasks),
        "skipped_total": int(report.get("skipped_processed_count") or 0) + int(report.get("skipped_duplicate_count") or 0),
        "skipped_processed": int(report.get("skipped_processed_count") or 0),
        "skipped_duplicate": int(report.get("skipped_duplicate_count") or 0),
        "archive_count": requested_count,
        "extracted_count": len(tasks),
        "auto_classify": bool(config.watcher.auto_classify),
        "target_library_id": target_library_id,
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "source_paths": [task.source_path for task in tasks],
        "created_tasks": created_tasks,
        "skipped_items": [],
        "source_path": input_path,
    })

    return {
        "message": f"找到 {len(tasks)} 个待处理文件",
        "found_count": len(tasks),
        "task_ids": created_task_ids,
        "batch_id": batch_id,
    }

@app.get("/api/backup/history")
def get_backup_history():
    """获取备份历史记录"""
    from ..models.database import BackupRecord, get_db
    
    db = next(get_db())
    try:
        records = db.query(BackupRecord).order_by(desc(BackupRecord.created_at)).all()
        return [record.to_dict() for record in records]
    finally:
        db.close()

@app.get("/api/tasks", response_model=List[TaskResponse], deprecated=True, summary="兼容层：获取原始引擎任务列表")
async def get_tasks(status: Optional[str] = None):
    """兼容层：获取原始引擎任务列表，新功能请改用 /api/task-center/list。"""
    engine = get_task_engine()
    
    if status == "pending":
        tasks = engine.get_pending_tasks()
    elif status == "processing":
        tasks = engine.get_processing_tasks()
    elif status == "completed":
        tasks = engine.get_completed_tasks()
    else:
        tasks = engine.get_all_tasks()
    
    return [_serialize_task_response(task) for task in tasks]


@app.get("/api/task-center/overview", response_model=TaskCenterOverviewResponse)
async def get_task_center_overview():
    """获取任务中心总览摘要。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.get_overview()


@app.get("/api/task-center/list", response_model=TaskCenterListResponse)
async def get_task_center_list(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    mode: str = "detail",
    offset: int = 0,
    limit: int = 200,
):
    """获取任务中心统一任务列表。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.list_items(domain=domain, status=status, search=search, mode=mode, offset=offset, limit=limit)


@app.get("/api/task-center/item", response_model=Optional[TaskCenterItemResponse])
async def get_task_center_item(item_id: Optional[str] = None, engine_task_id: Optional[str] = None):
    """按任务中心 ID 或引擎任务 ID 获取单项。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.get_item(item_id=item_id, engine_task_id=engine_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/task-center/stream")
async def stream_task_center_events(request: Request):
    """任务中心实时变更事件流。"""
    from ..core.task_center_event_service import sse_subscribe, sse_unsubscribe
    from ..core.redis_service import get_redis_service

    loop = asyncio.get_event_loop()
    sid, queue = sse_subscribe(loop)

    async def generator():
        last_redis_id = "$"
        try:
            yield f"data: {json.dumps({'type': 'connected', 'reason': 'connected'}, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    redis_events = await asyncio.to_thread(
                        get_redis_service().read_stream_payloads_sync,
                        'task-center:stream',
                        last_id=last_redis_id,
                        block_ms=1,
                        count=50,
                    )
                    if redis_events:
                        for message_id, event in redis_events:
                            last_redis_id = message_id
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif int(time.time()) % 25 == 0:
                        yield ": keepalive\n\n"
        finally:
            sse_unsubscribe(sid)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/events/stream")
async def stream_realtime_events(request: Request):
    """统一业务实时事件流。"""
    from ..core.realtime_event_service import sse_subscribe, sse_unsubscribe
    from ..core.redis_service import get_redis_service

    loop = asyncio.get_event_loop()
    sid, queue = sse_subscribe(loop)

    async def generator():
        last_redis_id = "$"
        try:
            yield f"data: {json.dumps({'type': 'connected'}, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    redis_events = await asyncio.to_thread(
                        get_redis_service().read_stream_payloads_sync,
                        'events:stream',
                        last_id=last_redis_id,
                        block_ms=1,
                        count=50,
                    )
                    if redis_events:
                        for message_id, event in redis_events:
                            last_redis_id = message_id
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif int(time.time()) % 25 == 0:
                        yield ": keepalive\n\n"
        finally:
            sse_unsubscribe(sid)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/task-center/diagnose")
async def diagnose_task_center_serialization():
    """诊断任务中心聚合中具体是哪条数据序列化失败。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.diagnose_serialization_failures()


@app.post("/api/task-center/materialized/backfill")
async def backfill_task_center_materialized_items():
    """回填任务中心物化快照，并返回旧聚合器对照 diff。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.backfill_materialized_items()
    except Exception as exc:
        logger.error("回填任务中心物化快照失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"回填任务中心物化快照失败: {str(exc)}")


@app.get("/api/task-center/materialized/list")
async def list_task_center_materialized_items(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = 200,
):
    """读取任务中心物化表预览，用于切换正式读路径前验证。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await asyncio.to_thread(
            service.list_materialized_items,
            domain=domain,
            status=status,
            search=search,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        logger.error("读取任务中心物化快照失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取任务中心物化快照失败: {str(exc)}")


@app.post("/api/task-center/{item_id}/action")
async def execute_task_center_action(item_id: str, payload: TaskCenterActionRequest):
    """执行任务中心统一动作。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.execute_action(item_id, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/task-center/{item_id}/filtered-items/{recovery_id}/restore")
async def restore_task_center_filtered_item(
    item_id: str,
    recovery_id: str,
    payload: Optional[FilteredItemRestoreRequest] = None,
):
    """把解压入库任务中进入恢复区的过滤项写回最终库存。"""
    from ..core.filter_recovery_service import (
        FilterRecoveryConflictError,
        FilterRecoveryError,
        get_filter_recovery_service,
    )

    try:
        return await get_filter_recovery_service().restore_item(
            item_id,
            recovery_id,
            relative_path=payload.relative_path if payload else None,
        )
    except FilterRecoveryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FilterRecoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(
            "还原任务过滤项失败: item_id=%s recovery_id=%s error=%s",
            item_id,
            recovery_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"还原过滤项失败: {str(exc)}")

@app.get("/api/tasks/{task_id}", response_model=TaskResponse, deprecated=True, summary="兼容层：获取原始引擎任务")
async def get_task(task_id: str):
    """兼容层：获取原始引擎任务详情，新功能请改用 /api/task-center/item。"""
    engine = get_task_engine()
    task = engine.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    return _serialize_task_response(task)

@app.post("/api/tasks/{task_id}/pause", deprecated=True, summary="兼容层：暂停原始引擎任务")
async def pause_task(task_id: str):
    """兼容层：暂停原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.pause_task(task_id)
    return {"message": "任务已暂停"}

@app.post("/api/tasks/{task_id}/resume", deprecated=True, summary="兼容层：恢复原始引擎任务")
async def resume_task(task_id: str):
    """兼容层：恢复原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.resume_task(task_id)
    return {"message": "任务已恢复"}

@app.post("/api/tasks/{task_id}/cancel", deprecated=True, summary="兼容层：取消原始引擎任务")
async def cancel_task(task_id: str):
    """兼容层：取消原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.cancel_task(task_id)
    return {"message": "任务已取消"}

@app.post("/api/tasks/batch-cancel-cleanup", summary="批量取消任务并清理已下载文件")
async def batch_cancel_cleanup(request: Request):
    """批量取消任务并删除对应的已下载临时文件。"""
    from ..core.task_cleanup_service import cleanup_task_download_artifacts
    from ..core.task_engine import TaskStatus
    body = await request.json()
    task_ids = body.get("task_ids") or []
    if not task_ids:
        return {"cancelled": 0, "cleaned": 0}
    engine = get_task_engine()
    cancelled = 0
    cleaned = 0
    for tid in task_ids:
        task = engine.get_task(str(tid))
        if not task:
            continue
        if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED):
            engine.cancel_task(str(tid))
            if task.type == TaskType.HTTP_DOWNLOAD:
                try:
                    from ..core.http_download_service import get_http_download_service

                    await get_http_download_service().cancel_task(str(tid))
                except Exception:
                    logger.debug("等待 HTTP 下载取消失败: task_id=%s", tid, exc_info=True)
            elif task.type == TaskType.BAIDU_NETDISK_DOWNLOAD:
                try:
                    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

                    await get_baidu_netdisk_service().cancel_task(str(tid))
                except Exception:
                    logger.debug("等待百度网盘下载取消失败: task_id=%s", tid, exc_info=True)
            cancelled += 1
        cleanup_result = cleanup_task_download_artifacts(task)
        cleaned += int(cleanup_result.get("cleaned") or 0)
        logger.info(
            "取消任务清理完成: task_id=%s mode=%s cleaned=%s skipped=%s errors=%s",
            getattr(task, "id", ""),
            cleanup_result.get("mode"),
            cleanup_result.get("cleaned"),
            len(cleanup_result.get("skipped_paths") or []),
            len(cleanup_result.get("errors") or []),
        )
    return {"cancelled": cancelled, "cleaned": cleaned, "message": f"已取消 {cancelled} 个任务，清理 {cleaned} 个下载产物"}

def _mask_notification_email_config(config) -> Optional[dict]:
    """返回 notification_email 配置，密码脱敏"""
    if not hasattr(config, 'notification_email'):
        return None
    data = config.notification_email.model_dump()
    if data.get('password'):
        data['password'] = '********'
    return data


def _mask_database_config(config) -> Optional[dict]:
    """返回 PostgreSQL 配置，密码脱敏。"""
    if not hasattr(config, 'database'):
        return None
    data = config.database.model_dump()
    if data.get('password') or _read_database_secret_from_runtime('password'):
        data['password'] = '********'
    return data


def _mask_redis_config(config) -> Optional[dict]:
    """返回 Redis 配置，URL 密码脱敏。"""
    if not hasattr(config, 'redis'):
        return None
    from ..core.redis_service import _mask_redis_url

    data = config.redis.model_dump()
    data['url'] = _mask_redis_url(data.get('url') or '')
    return data


def _mask_ai_subtitle_matching_config(config) -> Optional[dict]:
    """返回 AI 字幕配对配置，API Key 脱敏。"""
    if not hasattr(config, 'ai_subtitle_matching'):
        return None
    data = config.ai_subtitle_matching.model_dump()
    if data.get('api_key'):
        data['api_key'] = '********'
    return data


def _mask_http_downloader_config(config) -> Optional[dict]:
    """返回 HTTP 下载配置，PikPak 密码和 token 脱敏。"""
    if not hasattr(config, 'http_downloader'):
        return None
    data = config.http_downloader.model_dump()
    if data.get('google_drive_client_secret'):
        data['google_drive_client_secret'] = '********'
    if data.get('google_drive_refresh_token'):
        data['google_drive_refresh_token'] = '********'
    if data.get('pikpak_password'):
        data['pikpak_password'] = '********'
    if data.get('pikpak_encoded_token'):
        data['pikpak_encoded_token'] = '********'
    if isinstance(data.get('pikpak_accounts'), list):
        for account in data['pikpak_accounts']:
            if not isinstance(account, dict):
                continue
            if account.get('password'):
                account['password'] = '********'
            if account.get('encoded_token'):
                account['encoded_token'] = '********'
    if data.get('gofile_token'):
        data['gofile_token'] = '********'
    return data


def _mask_baidu_netdisk_config(config) -> Optional[dict]:
    """返回百度网盘配置，Cookie 脱敏。"""
    if not hasattr(config, 'baidu_netdisk'):
        return None
    data = config.baidu_netdisk.model_dump()
    if _has_baidu_login_cookie(data.get('cookie') or ''):
        data['cookie'] = '********'
    else:
        data['cookie'] = ''
    return data


def _mask_circle_external_search_config(config) -> Optional[dict]:
    if not hasattr(config, "circle_external_search"):
        return None
    data = config.circle_external_search.model_dump()
    data["south_plus_cookie"] = "********" if data.get("south_plus_cookie") else ""
    return data


def _runtime_config_path_from_settings() -> str:
    from ..config.settings import get_config_file_path, get_config_runtime_state

    config_path = get_config_file_path()
    state = get_config_runtime_state()
    config_path = state.get("path") or config_path
    if os.path.isabs(config_path):
        return config_path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    return os.path.abspath(os.path.join(project_root, config_path))


def _read_notification_email_password_from_disk() -> str:
    """读取磁盘原始配置，避免把前端脱敏占位符写回真实配置。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        password = data.get("notification_email", {}).get("password", "")
        return password if password != "********" else ""
    except Exception:
        logger.warning("[NOTIFICATION] 读取磁盘 notification_email 密码失败", exc_info=True)
        return ""


def _read_database_secret_from_disk(key: str) -> str:
    """读取磁盘原始 PostgreSQL 敏感配置，避免把脱敏占位符写回。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("database", {}).get(key, "")
        return value if value != "********" else ""
    except Exception:
        logger.warning("[数据库] 读取磁盘敏感配置失败: %s", key, exc_info=True)
        return ""


def _read_database_secret_from_runtime(key: str) -> str:
    """读取 DATABASE_URL 里的运行态 PostgreSQL 密码。Docker 内置库会通过它覆盖配置文件。"""
    if key != "password":
        return ""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return ""
    try:
        parts = urlsplit(database_url)
        if parts.scheme != "postgresql+psycopg":
            return ""
        return unquote(parts.password or "")
    except Exception:
        logger.warning("[数据库] 解析 DATABASE_URL 敏感配置失败", exc_info=True)
        return ""


def _read_redis_url_from_disk() -> str:
    """读取磁盘原始 Redis URL，避免把脱敏占位符写回。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = str(data.get("redis", {}).get("url") or "")
        return value if "********" not in value else ""
    except Exception:
        logger.warning("[Redis] 读取磁盘 Redis URL 失败", exc_info=True)
        return ""


def _read_redis_url_from_runtime() -> str:
    return os.environ.get("KIKOERUMANAGER_REDIS_URL", "").strip()


def _read_ai_subtitle_api_key_from_disk() -> str:
    """读取磁盘原始 AI 字幕配对 API Key，避免脱敏占位符覆盖真实配置。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("ai_subtitle_matching", {}).get("api_key", "")
        return value if value != "********" else ""
    except Exception:
        logger.warning("[AI字幕] 读取磁盘 API Key 失败", exc_info=True)
        return ""


def _read_http_downloader_secret_from_disk(key: str) -> str:
    """读取磁盘原始 HTTP 下载敏感配置，避免把脱敏占位符写回。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("http_downloader", {}).get(key, "")
        return value if value != "********" else ""
    except Exception:
        logger.warning("[HTTP下载] 读取磁盘敏感配置失败: %s", key, exc_info=True)
        return ""


def _read_baidu_netdisk_secret_from_disk(key: str) -> str:
    """读取磁盘原始百度网盘敏感配置，避免把脱敏占位符写回。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("baidu_netdisk", {}).get(key, "")
        return value if value != "********" else ""
    except Exception:
        logger.warning("[百度网盘] 读取磁盘敏感配置失败: %s", key, exc_info=True)
        return ""


def _read_circle_external_search_secret_from_disk(key: str) -> str:
    """读取外部搜索原始 Cookie，避免保存设置时覆盖成脱敏占位符。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("circle_external_search", {}).get(key, "")
        return value if value != "********" else ""
    except Exception:
        logger.warning("[社团补全·外部搜索] 读取敏感配置失败: %s", key, exc_info=True)
        return ""


def _read_http_downloader_accounts_from_disk() -> list[dict]:
    """读取磁盘原始 PikPak 多账号，保存脱敏表单时保留真实 token/password。"""
    try:
        config_path = _runtime_config_path_from_settings()
        if not os.path.exists(config_path):
            return []
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        accounts = data.get("http_downloader", {}).get("pikpak_accounts", [])
        return [dict(item) for item in accounts if isinstance(item, dict)]
    except Exception:
        logger.warning("[HTTP下载] 读取磁盘 PikPak 多账号失败", exc_info=True)
        return []


def _read_http_downloader_account_secret_from_disk(account_id: str, key: str) -> str:
    """按账号 id 读取磁盘原始 PikPak 多账号敏感字段。"""
    wanted = str(account_id or "").strip()
    if not wanted:
        return ""
    for account in _read_http_downloader_accounts_from_disk():
        if str(account.get("id") or "").strip() != wanted:
            continue
        value = str(account.get(key) or "")
        return value if value != "********" else ""
    return ""


def _merge_masked_pikpak_accounts(accounts: list, current_accounts: list, disk_accounts: list) -> list[dict]:
    current_by_id = {
        str((item.model_dump() if hasattr(item, "model_dump") else item).get("id") or "").strip(): (
            item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
        )
        for item in current_accounts or []
        if hasattr(item, "model_dump") or isinstance(item, dict)
    }
    disk_by_id = {
        str(item.get("id") or "").strip(): dict(item)
        for item in disk_accounts or []
        if isinstance(item, dict)
    }
    result = []
    for index, raw in enumerate(accounts or []):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        account_id = str(row.get("id") or "").strip()
        candidates = []
        if account_id:
            candidates.extend([disk_by_id.get(account_id), current_by_id.get(account_id)])
        if index < len(disk_accounts):
            candidates.append(disk_accounts[index])
        if index < len(current_accounts or []):
            current_item = current_accounts[index]
            candidates.append(current_item.model_dump() if hasattr(current_item, "model_dump") else current_item)
        for secret_key in ("password", "encoded_token"):
            if row.get(secret_key) == "********" or secret_key not in row:
                preserved = ""
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        value = str(candidate.get(secret_key) or "")
                        if value and value != "********":
                            preserved = value
                            break
                row[secret_key] = preserved
        result.append(row)
    return result


@app.get("/api/config", response_model=ConfigResponse)
def get_configuration():
    """获取配置"""
    config = get_config()
    storage_data = config.storage.model_dump()
    library_cfg = get_library_manager().load_config()
    storage_data["default_library_id"] = library_cfg["default_library_id"]
    storage_data["default_extract_library_id"] = library_cfg["default_extract_library_id"]
    storage_data["health_warning_free_gb"] = library_cfg["health_warning_free_gb"]
    storage_data["stats_cache_ttl_seconds"] = library_cfg["stats_cache_ttl_seconds"]
    return ConfigResponse(
        storage=storage_data,
        processing=config.processing.model_dump(),
        watcher=config.watcher.model_dump(),
        extract=config.extract.model_dump(),
        filter=config.filter.model_dump(),
        metadata=config.metadata.model_dump(),
        rename=config.rename.model_dump(),
        classification=[rule.model_dump() for rule in config.classification],
        password_cleanup=config.password_cleanup.model_dump(),
        processed_archive_cleanup=config.processed_archive_cleanup.model_dump(),
        path_mapping=config.path_mapping.model_dump(),
        kikoeru_server=config.kikoeru_server.model_dump() if hasattr(config, 'kikoeru_server') else None,
        asmr_sync=config.asmr_sync.model_dump() if hasattr(config, 'asmr_sync') else None,
        http_downloader=_mask_http_downloader_config(config),
        baidu_netdisk=_mask_baidu_netdisk_config(config),
        circle_external_search=_mask_circle_external_search_config(config),
        auto_process=config.auto_process.model_dump() if hasattr(config, 'auto_process') else None,
        process_existing=config.process_existing.model_dump() if hasattr(config, 'process_existing') else None,
        asmr_sync_step=config.asmr_sync_step.model_dump() if hasattr(config, 'asmr_sync_step') else None,
        rj_subtitle=config.rj_subtitle.model_dump() if hasattr(config, 'rj_subtitle') else None,
        ai_subtitle_matching=_mask_ai_subtitle_matching_config(config),
        backup_zip=config.backup_zip.model_dump() if hasattr(config, 'backup_zip') else None,
        email_watcher=config.email_watcher.model_dump() if hasattr(config, 'email_watcher') else None,
        notification_email=_mask_notification_email_config(config),
        notification_center=config.notification_center.model_dump() if hasattr(config, 'notification_center') else None,
        redis=_mask_redis_config(config),
        bonus_probe=config.bonus_probe.model_dump() if hasattr(config, 'bonus_probe') else None,
        resource_budget=config.resource_budget.model_dump() if hasattr(config, 'resource_budget') else None,
        database=_mask_database_config(config),
        security_gate=get_security_gate_service().sanitize_config() if hasattr(config, 'security_gate') else None,
        ui=config.ui.model_dump() if hasattr(config, 'ui') else None,
    )

@app.get("/api/config/state")
def get_configuration_state():
    """获取配置运行态，便于排查首屏配置抖动。"""
    from ..config.settings import get_config_runtime_state

    return get_config_runtime_state()


@app.post("/api/config/http-downloader/reveal-secret")
def reveal_http_downloader_secret(payload: HttpDownloaderSecretRevealRequest):
    """从本地配置文件读取 HTTP 下载敏感字段，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    account_id = str(payload.account_id or "").strip()
    if key not in {"pikpak_password", "gofile_token", "google_drive_client_secret", "google_drive_refresh_token", "password", "encoded_token"}:
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    if account_id:
        if key not in {"password", "encoded_token"}:
            raise HTTPException(status_code=400, detail="账号敏感字段只能读取 password 或 encoded_token")
        value = _read_http_downloader_account_secret_from_disk(account_id, key)
    else:
        value = _read_http_downloader_secret_from_disk(key)
    return {"value": value}


@app.post("/api/config/baidu-netdisk/reveal-secret")
def reveal_baidu_netdisk_secret(payload: BaiduNetdiskSecretRevealRequest):
    """从本地配置文件读取百度网盘 Cookie，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    if key != "cookie":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_baidu_netdisk_secret_from_disk(key)}


@app.post("/api/config/notification-email/reveal-secret")
def reveal_notification_email_secret(payload: NotificationEmailSecretRevealRequest):
    """从本地配置文件读取通知邮件授权码，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    if key != "password":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_notification_email_password_from_disk()}


@app.post("/api/config/ai-subtitle-match/reveal-secret")
def reveal_ai_subtitle_match_secret(payload: AISubtitleSecretRevealRequest):
    """从本地配置文件读取 AI 字幕配对敏感字段，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    if key != "api_key":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_ai_subtitle_api_key_from_disk()}


@app.post("/api/config/circle-external-search/reveal-secret")
def reveal_circle_external_search_secret(payload: CircleExternalSearchSecretRevealRequest):
    """从本地配置文件读取南+ Cookie，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    if key != "south_plus_cookie":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_circle_external_search_secret_from_disk(key)}


@app.post("/api/config/database/reveal-secret")
def reveal_database_secret(payload: DatabaseSecretRevealRequest):
    """从本地配置文件读取 PostgreSQL 密码，只供设置页显隐使用。"""
    key = str(payload.key or "").strip()
    if key != "password":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_database_secret_from_disk(key) or _read_database_secret_from_runtime(key)}


@app.post("/api/config/redis/reveal-secret")
def reveal_redis_secret(payload: RedisSecretRevealRequest):
    """从运行环境或本地配置文件读取 Redis URL，只供设置页显隐和编辑使用。"""
    key = str(payload.key or "").strip()
    if key != "url":
        raise HTTPException(status_code=400, detail="不支持读取该敏感字段")
    return {"value": _read_redis_url_from_runtime() or _read_redis_url_from_disk()}


class SecurityGateVerifyRequest(BaseModel):
    code: str
    remember: bool = False


class SecurityGateSetupConfirmRequest(BaseModel):
    code: str


class SecurityGateUnblockRequest(BaseModel):
    reason: str = ""


@app.get("/api/security-gate/status")
def get_security_gate_status(request: Request):
    """返回门禁公开状态。不会泄露验证器密钥。"""
    return get_security_gate_service().public_state(request)


@app.post("/api/security-gate/verify")
def verify_security_gate(payload: SecurityGateVerifyRequest, request: Request):
    """校验 Google Authenticator 动态验证码并写入门禁会话 Cookie。"""
    service = get_security_gate_service()
    result = service.verify_access(payload.code, payload.remember, request)
    if result.get("blocked"):
        return JSONResponse(result, status_code=403)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    response = JSONResponse({
        "ok": True,
        "message": "验证通过",
        "expires_at": result.get("expires_at"),
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=result["token"],
        max_age=result["max_age"],
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response


@app.post("/api/security-gate/logout")
def logout_security_gate():
    """清除当前浏览器的门禁会话。"""
    response = JSONResponse({"ok": True})
    response.delete_cookie(**get_security_gate_service().clear_cookie_kwargs())
    return response


@app.post("/api/security-gate/setup")
def create_security_gate_setup():
    """生成 Google Authenticator 绑定密钥和二维码。"""
    return get_security_gate_service().create_setup()


@app.post("/api/security-gate/setup/confirm")
def confirm_security_gate_setup(payload: SecurityGateSetupConfirmRequest, request: Request):
    """确认绑定 Google Authenticator。"""
    try:
        return get_security_gate_service().confirm_setup(payload.code, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/security-gate/setup/reset")
def reset_security_gate_setup(request: Request):
    """重置验证器绑定，并自动关闭门禁防止锁死。"""
    return get_security_gate_service().reset_setup(request)


@app.get("/api/security-gate/logs")
def list_security_gate_logs(
    result: str = "all",
    ip: str = "",
    limit: int = 80,
    db: Session = Depends(get_db),
):
    """查看最近门禁认证记录。"""
    return {"items": get_security_gate_service().list_logs(db, result=result, ip=ip, limit=limit)}


@app.get("/api/security-gate/blacklist")
def list_security_gate_blacklist(include_inactive: bool = False, db: Session = Depends(get_db)):
    """查看门禁黑名单。"""
    return {"items": get_security_gate_service().list_blacklist(db, include_inactive=include_inactive)}


@app.post("/api/security-gate/blacklist/{item_id}/unblock")
def unblock_security_gate_item(item_id: str, payload: SecurityGateUnblockRequest, request: Request, db: Session = Depends(get_db)):
    """手动解除黑名单。"""
    try:
        return get_security_gate_service().unblock(db, item_id, payload.reason, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/system/storage-info")
def get_storage_info(refresh: bool = False):
    """返回 temp_path / library_path / input_path 所在盘的存储类型探测结果。

    前端设置页用它在"解压并发"下拉旁展示实际生效值（例如 "auto → 检测到 SSD，并发 3"）。
    """
    from ..core.extract_service import ExtractService

    cfg = get_config()
    storage_cfg = getattr(cfg, 'storage', None)
    cache_key = (
        str(getattr(storage_cfg, "temp_path", "") or ""),
        str(getattr(storage_cfg, "library_path", "") or ""),
        str(getattr(storage_cfg, "input_path", "") or ""),
        int(getattr(cfg.extract, 'max_concurrent_extractions', 0) or 0),
        int(getattr(cfg.processing, 'max_workers', 1) or 1),
    )
    now = time.monotonic()
    cached_payload = _SYSTEM_STORAGE_INFO_CACHE.get("payload")
    if (
        not refresh
        and cached_payload is not None
        and _SYSTEM_STORAGE_INFO_CACHE.get("key") == cache_key
        and float(_SYSTEM_STORAGE_INFO_CACHE.get("expires_at") or 0.0) > now
    ):
        return dict(cached_payload)

    probe_targets = []
    for attr, label in (
        ("temp_path", "临时目录"),
        ("library_path", "库存目录"),
        ("input_path", "待处理目录"),
    ):
        value = getattr(storage_cfg, attr, None) if storage_cfg else None
        if value:
            probe_targets.append({
                "label": label,
                "attr": attr,
                "path": str(value),
                "type": ExtractService._detect_storage_type(str(value)),
            })

    # 再给一个"auto 模式下实际会选的并发值"，方便前端直接显示
    service = ExtractService()
    resolved_limit, resolved_reason = service._resolve_extract_concurrency()
    primary_type = probe_targets[0]["type"] if probe_targets else "unknown"

    payload = {
        "primary_type": primary_type,  # 'ssd' / 'hdd' / 'unknown'
        "probes": probe_targets,
        "resolved_limit": resolved_limit,
        "resolved_reason": resolved_reason,
        "configured": int(getattr(cfg.extract, 'max_concurrent_extractions', 0) or 0),
        "max_workers": int(getattr(cfg.processing, 'max_workers', 1) or 1),
    }
    _SYSTEM_STORAGE_INFO_CACHE.update({
        "key": cache_key,
        "expires_at": now + _STORAGE_INFO_TTL_SECONDS,
        "payload": dict(payload),
    })
    return payload


@app.get("/api/system/resource-budget")
def get_resource_budget_snapshot():
    """返回全局资源预算运行态，用于压测和现场调参。"""
    from ..core.resource_budget_service import get_resource_budget_service

    return get_resource_budget_service().snapshot()


@app.get("/api/system/redis/status")
def get_redis_status():
    """返回 Redis 运行态诊断。"""
    from ..core.redis_service import get_redis_service

    return get_redis_service().diagnostics()


@app.get("/api/system/library-index/status")
def get_library_index_runtime_status():
    """返回库存索引水位、账本、Redis hint 与 watcher 诊断。"""
    from ..core.library_index import (
        get_library_index_mutation_service,
        get_library_index_watcher_driver,
    )
    from ..core.redis_service import get_redis_service

    mutation = get_library_index_mutation_service().diagnostics()
    watcher = get_library_index_watcher_driver().diagnostics()
    redis_status = get_redis_service().diagnostics()
    pending_libraries = []
    for item in mutation.get("pending_libraries") or []:
        row = dict(item or {})
        row["watermark_lag"] = max(
            int(row.get("accepted_seq") or 0) - int(row.get("materialized_seq") or 0),
            0,
        )
        pending_libraries.append(row)
    return {
        "libraries": pending_libraries,
        "oldest_prepared_at": mutation.get("oldest_prepared_at"),
        "oldest_ledger_by_library": mutation.get("oldest_ledger_by_library") or {},
        "pending_mask_count_by_library": mutation.get("pending_mask_count_by_library") or {},
        "replay_count": int(mutation.get("replay_count") or 0),
        "materializer": {
            "worker_alive": bool(mutation.get("worker_alive")),
            "publisher_alive": bool(mutation.get("publisher_alive")),
            "listener_alive": bool(mutation.get("listener_alive")),
            "listener_hint_batches": int(
                mutation.get("listener_hint_batches") or 0
            ),
            "consumer": mutation.get("consumer"),
            "fast_path": mutation.get("fast_path") or {},
            "pool": mutation.get("materializer_pool") or {},
        },
        "watcher": watcher,
        "redis": redis_status,
        "generated_at": datetime.now().isoformat(),
    }


@app.get("/api/system/runtime-buffer/status")
def get_runtime_buffer_status():
    """返回运行态缓冲状态。Redis 失败时可看到 memory fallback 是否接管。"""
    from ..core.redis_service import get_redis_service

    return get_redis_service().runtime_buffer_status()


@app.get("/api/system/pressure")
def get_system_pressure():
    """返回控制面压力快照，不触发下载队列或远程库探测。"""
    from ..core.redis_service import get_redis_service
    from ..core.resource_budget_service import get_resource_budget_service
    from ..models import database as database_module

    engine = get_task_engine()
    db_pool_status = ""
    db_pool_checked_out = None
    try:
        pool = getattr(database_module.engine, "pool", None)
        if pool is not None:
            db_pool_status = pool.status()
            checked_out = getattr(pool, "checkedout", None)
            if callable(checked_out):
                db_pool_checked_out = checked_out()
    except Exception:
        db_pool_status = "unavailable"

    return {
        "resource_budget": get_resource_budget_service().snapshot(),
        "runtime_buffer": get_redis_service().runtime_buffer_status(),
        "logs": _log_stream_status_payload(),
        "task_engine": {
            "queue_size": engine.queue.qsize() if getattr(engine, "queue", None) is not None else 0,
            "processing_count": len(getattr(engine, "processing", set()) or set()),
            "task_count": len(getattr(engine, "tasks", {}) or {}),
            "task_center_version": engine.get_task_center_version(),
            "materialized_pending_count": len(getattr(engine, "_materialized_snapshot_pending", {}) or {}),
            "max_concurrent": getattr(engine, "max_concurrent", None),
        },
        "database": {
            "pool_status": db_pool_status,
            "checked_out": db_pool_checked_out,
        },
        "generated_at": datetime.now().isoformat(),
    }


@app.get("/api/system/runtime/status")
def get_runtime_status():
    """返回运行态依赖和关键限流配置。"""
    from ..core.redis_service import get_redis_service
    from ..core.resource_budget_service import get_resource_budget_service

    config = get_config()
    return {
        "redis": get_redis_service().diagnostics(),
        "runtime_buffer": get_redis_service().runtime_buffer_status(),
        "resource_budget": get_resource_budget_service().snapshot(),
        "bonus_probe": config.bonus_probe.model_dump() if hasattr(config, 'bonus_probe') else None,
        "generated_at": datetime.now().isoformat(),
    }


@app.get("/api/system/remote-fs-health")
def get_remote_fs_health_snapshot():
    """返回远程库存健康状态，不触发远程探测。"""
    return get_library_manager().remote_health_snapshot()


@app.get("/api/system/task-phase-metrics")
def get_task_phase_metrics(task_id: Optional[str] = None, limit: int = 100):
    """返回最近任务阶段耗时指标，用于定位下载/上传/解压等慢阶段。"""
    from ..core.task_phase_metric_service import get_task_phase_metric_service

    service = get_task_phase_metric_service()
    items = service.list_recent(task_id=task_id or "", limit=limit)
    summary = service.summarize_recent(task_id=task_id or "", limit=max(limit, 1000))
    return {"items": items, "total": len(items), "summary": summary}


@app.post("/api/system/task-phase-metrics/cleanup")
def cleanup_task_phase_metrics(retain_days: Optional[int] = None, max_items: Optional[int] = None):
    """手动清理任务阶段耗时指标，控制观测表增长。"""
    from ..core.task_phase_metric_service import get_task_phase_metric_service

    config = _task_phase_metric_cleanup_config()
    if retain_days is not None:
        config["retain_days"] = max(1, int(retain_days))
    if max_items is not None:
        config["max_items"] = max(100, int(max_items))
    return get_task_phase_metric_service().cleanup(**config)


_CONFIG_SAVE_INFO_DEDUP_SECONDS = 30.0
_CONFIG_SAVE_INFO_LAST: Dict[str, float] = {}
_QUIET_CONFIG_SAVE_KEYS = {"rj_subtitle"}


def _should_log_config_save_info(keys: List[str]) -> bool:
    normalized = tuple(sorted(str(key or "").strip() for key in keys if str(key or "").strip()))
    if not normalized:
        return False
    if set(normalized).issubset(_QUIET_CONFIG_SAVE_KEYS):
        return False
    signature = ",".join(normalized)
    now = time.monotonic()
    last = _CONFIG_SAVE_INFO_LAST.get(signature, 0.0)
    _CONFIG_SAVE_INFO_LAST[signature] = now
    return now - last >= _CONFIG_SAVE_INFO_DEDUP_SECONDS


@app.post("/api/config")
async def update_configuration(request: Request):
    """更新配置"""
    from ..config.settings import save_config, ClassificationRule, FilterRule, PathMappingRule
    try:
        config_data = await request.json()
        config_keys = sorted(config_data.keys()) if isinstance(config_data, dict) else []
        logger.debug(
            "接收到配置保存请求: keys=%s classification=%s filter_rules=%s path_mapping_rules=%s",
            config_keys,
            len(config_data.get('classification') or []) if isinstance(config_data, dict) else 0,
            len(((config_data.get('filter') or {}).get('rules') or [])) if isinstance(config_data, dict) else 0,
            len(((config_data.get('path_mapping') or {}).get('rules') or [])) if isinstance(config_data, dict) else 0,
        )
        
        # 记录重命名模板用于调试
        if 'rename' in config_data and config_data['rename']:
            template = config_data['rename'].get('template', 'NOT SET')
            logger.debug(f"[CONFIG SAVE] 接收到的模板: '{template}'")
        
        # 确保 classification 字段格式正确
        if 'classification' in config_data and config_data['classification']:
            validated_rules = []
            for rule_data in config_data['classification']:
                try:
                    # 清理 None 值
                    rule_data_cleaned = {k: v for k, v in rule_data.items() if v is not None}
                    # 使用 Pydantic 验证每个规则
                    rule = ClassificationRule(**rule_data_cleaned)
                    validated_rules.append(rule.dict())
                    logger.debug(f"规则验证通过: {rule_data_cleaned}")
                except Exception as e:
                    logger.warning(f"分类规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['classification'] = validated_rules
            logger.debug(f"验证后的分类规则: {validated_rules}")
        
        # 确保 filter 字段格式正确
        if 'filter' in config_data and config_data['filter'] and 'rules' in config_data['filter']:
            validated_filter_rules = []
            for rule_data in config_data['filter']['rules']:
                try:
                    # 确保 target 字段存在
                    if 'target' not in rule_data or not rule_data['target']:
                        rule_data['target'] = 'file'
                    # 使用 Pydantic 验证
                    rule = FilterRule(**rule_data)
                    validated_filter_rules.append(rule.dict())
                    logger.debug(f"过滤规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"过滤规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['filter']['rules'] = validated_filter_rules
            logger.debug(f"验证后的过滤规则数: {len(validated_filter_rules)}")
        
        # 确保 path_mapping 字段格式正确
        if 'path_mapping' in config_data and config_data['path_mapping'] and 'rules' in config_data['path_mapping']:
            validated_path_rules = []
            for rule_data in config_data['path_mapping']['rules']:
                try:
                    rule = PathMappingRule(**rule_data)
                    validated_path_rules.append(rule.dict())
                    logger.debug(f"路径映射规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"路径映射规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['path_mapping']['rules'] = validated_path_rules
            logger.debug(f"验证后的路径映射规则数: {len(validated_path_rules)}")
        
        # 处理 Kikoeru 服务器配置
        if 'kikoeru_server' in config_data:
            logger.info(
                "[KIKOERU] 接收到 Kikoeru 服务器配置: %s",
                sanitize_for_log({
                    "enabled": (config_data.get("kikoeru_server") or {}).get("enabled"),
                    "server_url": (config_data.get("kikoeru_server") or {}).get("server_url"),
                    "username": (config_data.get("kikoeru_server") or {}).get("username"),
                    "has_token": bool((config_data.get("kikoeru_server") or {}).get("api_token")),
                }),
            )
            try:
                # 验证 KikoeruServerConfig
                from ..config.settings import KikoeruServerConfig
                kikoeru_config = KikoeruServerConfig(**config_data['kikoeru_server'])
                config_data['kikoeru_server'] = kikoeru_config.model_dump()
                logger.info(f"[KIKOERU] 配置验证通过: enabled={kikoeru_config.enabled}, server_url={kikoeru_config.server_url}")
            except Exception as e:
                logger.error(f"[KIKOERU] Kikoeru 配置验证失败: {e}")
                # 如果验证失败，保留原始配置
        else:
            logger.debug("[KIKOERU] 未接收到 Kikoeru 服务器配置")

        # 处理 ASMR 同步配置
        if 'asmr_sync' in config_data:
            logger.info(
                "[ASMR] 接收到 ASMR 同步配置: enabled=%s retry_cron=%s max_concurrent_downloads=%s",
                (config_data.get("asmr_sync") or {}).get("enabled"),
                (config_data.get("asmr_sync") or {}).get("retry_cron"),
                (config_data.get("asmr_sync") or {}).get("max_concurrent_downloads"),
            )
            try:
                from ..config.settings import ASMRSyncConfig
                asmr_config = ASMRSyncConfig(**config_data['asmr_sync'])
                config_data['asmr_sync'] = asmr_config.model_dump()
                logger.info(f"[ASMR] 配置验证通过: retry_cron={asmr_config.retry_cron}")
            except Exception as e:
                logger.error(f"[ASMR] ASMR 同步配置验证失败: {e}")
        else:
            logger.debug("[ASMR] 未接收到 ASMR 同步配置")

        if 'http_downloader' in config_data:
            logger.info("[HTTP下载] 接收到 HTTP 外链下载配置: %s", _mask_http_downloader_config_for_log(config_data['http_downloader']))
            try:
                from ..config.settings import HttpDownloaderConfig
                http_data = dict(config_data['http_downloader'])
                current_cfg = get_config()
                if http_data.get('pikpak_password') == '********' or 'pikpak_password' not in http_data:
                    current_password = getattr(current_cfg.http_downloader, 'pikpak_password', '')
                    http_data['pikpak_password'] = (
                        _read_http_downloader_secret_from_disk('pikpak_password')
                        or (current_password if current_password != '********' else '')
                    )
                if http_data.get('pikpak_encoded_token') == '********' or 'pikpak_encoded_token' not in http_data:
                    current_token = getattr(current_cfg.http_downloader, 'pikpak_encoded_token', '')
                    http_data['pikpak_encoded_token'] = (
                        _read_http_downloader_secret_from_disk('pikpak_encoded_token')
                        or (current_token if current_token != '********' else '')
                    )
                if http_data.get('gofile_token') == '********' or 'gofile_token' not in http_data:
                    current_gofile_token = getattr(current_cfg.http_downloader, 'gofile_token', '')
                    http_data['gofile_token'] = (
                        _read_http_downloader_secret_from_disk('gofile_token')
                        or (current_gofile_token if current_gofile_token != '********' else '')
                    )
                for secret_key in ('google_drive_client_secret', 'google_drive_refresh_token'):
                    if http_data.get(secret_key) == '********' or secret_key not in http_data:
                        current_secret = getattr(current_cfg.http_downloader, secret_key, '')
                        http_data[secret_key] = (
                            _read_http_downloader_secret_from_disk(secret_key)
                            or (current_secret if current_secret != '********' else '')
                        )
                if isinstance(http_data.get('pikpak_accounts'), list):
                    http_data['pikpak_accounts'] = _merge_masked_pikpak_accounts(
                        http_data.get('pikpak_accounts') or [],
                        list(getattr(current_cfg.http_downloader, 'pikpak_accounts', []) or []),
                        _read_http_downloader_accounts_from_disk(),
                    )
                http_downloader_config = HttpDownloaderConfig(**http_data)
                config_data['http_downloader'] = http_downloader_config.model_dump()
                logger.info(f"[HTTP下载] 配置验证通过: engine={http_downloader_config.engine}, aria2_path={http_downloader_config.aria2_path}")
            except Exception as e:
                logger.error(f"[HTTP下载] 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"HTTP 外链下载配置无效: {e}")

        if 'baidu_netdisk' in config_data:
            logger.info("[百度网盘] 接收到百度网盘下载配置: %s", _mask_baidu_netdisk_config_for_log(config_data['baidu_netdisk']))
            try:
                from ..config.settings import BaiduNetdiskConfig
                baidu_data = dict(config_data['baidu_netdisk'])
                current_cfg = get_config()
                if not str(baidu_data.get('baidupcs_go_path') or '').strip():
                    baidu_data['baidupcs_go_path'] = BaiduNetdiskConfig().baidupcs_go_path
                incoming_cookie = str(baidu_data.get('cookie') or '').strip()
                if incoming_cookie == '********' or 'cookie' not in baidu_data:
                    current_cookie = getattr(current_cfg.baidu_netdisk, 'cookie', '')
                    baidu_data['cookie'] = (
                        _read_baidu_netdisk_secret_from_disk('cookie')
                        or (current_cookie if _has_baidu_login_cookie(current_cookie) else '')
                    )
                elif incoming_cookie and not _has_baidu_login_cookie(incoming_cookie):
                    raise HTTPException(status_code=400, detail="百度网盘配置缺少 BDUSS 登录态，请重新扫码或重新绑定 Cookie")
                baidu_config = BaiduNetdiskConfig(**baidu_data)
                config_data['baidu_netdisk'] = baidu_config.model_dump()
                logger.info("[百度网盘] 配置验证通过: enabled=%s, baidupcs_go_path=%s", baidu_config.enabled, baidu_config.baidupcs_go_path)
            except Exception as e:
                logger.error("[百度网盘] 配置验证失败: %s", e)
                raise HTTPException(status_code=400, detail=f"百度网盘配置无效: {e}")

        if 'circle_external_search' in config_data:
            logger.info(
                "[社团补全·外部搜索] 接收到配置: %s",
                _mask_circle_external_search_config_for_log(config_data['circle_external_search']),
            )
            try:
                from ..config.settings import CircleExternalSearchConfig

                external_search_data = dict(config_data['circle_external_search'])
                current_cfg = get_config()
                incoming_cookie = str(external_search_data.get('south_plus_cookie') or '').strip()
                if incoming_cookie == '********' or 'south_plus_cookie' not in external_search_data:
                    current_cookie = str(getattr(current_cfg.circle_external_search, 'south_plus_cookie', '') or '')
                    external_search_data['south_plus_cookie'] = (
                        _read_circle_external_search_secret_from_disk('south_plus_cookie')
                        or (current_cookie if current_cookie != '********' else '')
                    )
                external_config = CircleExternalSearchConfig(**external_search_data)
                config_data['circle_external_search'] = external_config.model_dump()
            except Exception as e:
                logger.error("[社团补全·外部搜索] 配置验证失败: %s", e)
                raise HTTPException(status_code=400, detail=f"社团外部搜索配置无效: {e}")

        if 'backup_zip' in config_data:
            try:
                from ..config.settings import BackupZipConfig
                backup_zip_config = BackupZipConfig(**config_data['backup_zip'])
                config_data['backup_zip'] = backup_zip_config.model_dump()
            except Exception as e:
                logger.error(f"[BACKUP_ZIP] 配置验证失败: {e}")

        if 'rj_subtitle' in config_data:
            try:
                from ..config.settings import RJSubtitleConfig
                rj_subtitle_config = RJSubtitleConfig(**config_data['rj_subtitle'])
                config_data['rj_subtitle'] = rj_subtitle_config.model_dump()
            except Exception as e:
                logger.error(f"[RJ_SUBTITLE] 配置验证失败: {e}")

        if 'ai_subtitle_matching' in config_data and config_data['ai_subtitle_matching']:
            try:
                from ..config.settings import AISubtitleMatchingConfig
                ai_data = dict(config_data['ai_subtitle_matching'])
                if 'api_key' not in ai_data or ai_data.get('api_key') == '********':
                    current_cfg = get_config()
                    current_key = getattr(current_cfg.ai_subtitle_matching, 'api_key', '')
                    ai_data['api_key'] = (
                        _read_ai_subtitle_api_key_from_disk()
                        or (current_key if current_key != '********' else '')
                    )
                ai_cfg = AISubtitleMatchingConfig(**ai_data)
                config_data['ai_subtitle_matching'] = ai_cfg.model_dump()
            except Exception as e:
                logger.error(f"[AI字幕] 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"AI 字幕配对配置无效: {e}")

        if 'notification_email' in config_data and config_data['notification_email']:
            try:
                from ..config.settings import NotificationEmailConfig
                ne_data = dict(config_data['notification_email'])
                if 'password' not in ne_data or ne_data.get('password') == '********':
                    current_cfg = get_config()
                    current_password = current_cfg.notification_email.password
                    ne_data['password'] = (
                        _read_notification_email_password_from_disk()
                        or (current_password if current_password != '********' else '')
                    )
                ne_cfg = NotificationEmailConfig(**ne_data)
                config_data['notification_email'] = ne_cfg.model_dump()
            except Exception as e:
                logger.error(f"[NOTIFICATION] notification_email 配置验证失败: {e}")

        if 'notification_center' in config_data and config_data['notification_center']:
            try:
                from ..config.settings import NotificationCenterConfig
                nc_cfg = NotificationCenterConfig(**config_data['notification_center'])
                config_data['notification_center'] = nc_cfg.model_dump()
            except Exception as e:
                logger.error(f"[NOTIFICATION] notification_center 配置验证失败: {e}")

        if 'resource_budget' in config_data and config_data['resource_budget']:
            try:
                from ..config.settings import ResourceBudgetConfig
                rb_cfg = ResourceBudgetConfig(**config_data['resource_budget'])
                config_data['resource_budget'] = rb_cfg.model_dump()
            except Exception as e:
                logger.error(f"[资源预算] resource_budget 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"资源预算配置无效: {e}")

        if 'redis' in config_data and config_data['redis']:
            try:
                from ..config.settings import RedisConfig
                redis_data = dict(config_data['redis'])
                incoming_url = str(redis_data.get('url') or '').strip()
                if '********' in incoming_url or 'url' not in redis_data:
                    current_cfg = get_config()
                    current_url = getattr(current_cfg.redis, 'url', '') if hasattr(current_cfg, 'redis') else ''
                    redis_data['url'] = (
                        _read_redis_url_from_runtime()
                        or _read_redis_url_from_disk()
                        or (current_url if '********' not in str(current_url or '') else '')
                    )
                redis_cfg = RedisConfig(**redis_data)
                config_data['redis'] = redis_cfg.model_dump()
            except Exception as e:
                logger.error(f"[Redis] redis 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"Redis 配置无效: {e}")

        if 'bonus_probe' in config_data and config_data['bonus_probe']:
            try:
                from ..config.settings import BonusProbeConfig
                bp_cfg = BonusProbeConfig(**config_data['bonus_probe'])
                config_data['bonus_probe'] = bp_cfg.model_dump()
            except Exception as e:
                logger.error(f"[特典补全] bonus_probe 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"特典补全配置无效: {e}")

        if 'database' in config_data and config_data['database']:
            try:
                from ..config.settings import DatabaseConfig
                db_data = dict(config_data['database'])
                if db_data.get('password') == '********' or 'password' not in db_data:
                    current_cfg = get_config()
                    current_password = getattr(current_cfg.database, 'password', '')
                    db_data['password'] = (
                        _read_database_secret_from_disk('password')
                        or (current_password if current_password != '********' else '')
                    )
                db_cfg = DatabaseConfig(**db_data)
                config_data['database'] = db_cfg.model_dump()
            except Exception as e:
                logger.error(f"[数据库] database 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"数据库配置无效: {e}")

        if 'security_gate' in config_data and config_data['security_gate']:
            try:
                from ..config.settings import SecurityGateConfig
                current_gate = get_config().security_gate
                gate_data = dict(config_data['security_gate'])
                if gate_data.get('secret') == '********' or 'secret' not in gate_data:
                    gate_data['secret'] = current_gate.secret
                if gate_data.get('pending_secret') == '********' or 'pending_secret' not in gate_data:
                    gate_data['pending_secret'] = current_gate.pending_secret
                if gate_data.get('enabled') and not gate_data.get('secret'):
                    raise HTTPException(status_code=400, detail="启用安全门禁前必须先绑定 Google Authenticator")
                gate_cfg = SecurityGateConfig(**gate_data)
                config_data['security_gate'] = gate_cfg.model_dump()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[SECURITY_GATE] security_gate 配置验证失败: {e}")
                raise HTTPException(status_code=400, detail=f"安全门禁配置无效: {e}")

        result = save_config(config_data)
        if _should_log_config_save_info(config_keys):
            logger.info(
                "配置保存摘要: keys=%s classification=%s",
                config_keys,
                len(config_data.get('classification', [])),
            )
        else:
            logger.debug("配置已保存: keys=%s classification=%s", config_keys, len(config_data.get('classification', [])))

        if 'kikoeru_server' in config_data:
            try:
                kikoeru_service = get_kikoeru_service()
                kikoeru_service.config = kikoeru_service._load_config()
                kikoeru_service.clear_cache()
                logger.info(
                    "[KIKOERU] 运行时配置已刷新: enabled=%s, server_url=%s",
                    kikoeru_service.config.enabled,
                    kikoeru_service.config.server_url,
                )
            except Exception:
                logger.warning("[KIKOERU] 刷新运行时配置失败", exc_info=True)

        # 重新读取配置文件确保数据已写入
        current_config = get_config()
        get_task_engine()
        logger.debug(f"当前配置中的分类规则: {[r.dict() for r in current_config.classification]}")

        if 'circle_external_search' in config_data:
            try:
                from ..core.circle_external_search_service import get_circle_external_search_service

                requeued = await asyncio.to_thread(
                    get_circle_external_search_service().requeue_unavailable_source,
                    'south_plus',
                )
                if requeued:
                    logger.info("[社团补全·外部搜索] 南+配置变更，重新入队 %s 条不可用记录", requeued)
            except Exception:
                logger.warning("[社团补全·外部搜索] 南+配置变更后重新入队失败", exc_info=True)

        # 如果密码清理配置变更，重启清理服务
        if 'password_cleanup' in config_data:
            logger.info("密码清理配置已变更，重启清理服务...")
            cleanup_service = get_cleanup_service()
            await cleanup_service.restart()
            logger.info("密码清理服务已重启")

        # 如果已处理压缩包清理配置变更，重启清理服务
        if 'processed_archive_cleanup' in config_data:
            logger.info("已处理压缩包清理配置已变更，重启清理服务...")
            archive_cleanup_service = get_processed_archive_cleanup_service()
            await archive_cleanup_service.restart()
            logger.info("已处理压缩包清理服务已重启")

        return {"message": "配置已保存", "config": config_data}
    except Exception as e:
        logger.error(f"保存配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")

@app.post("/api/config/reload")
async def reload_configuration():
    """重新加载配置文件（从磁盘重新读取）"""
    from ..config.settings import reload_config, get_config_file_path
    import os
    
    try:
        config_file_path = get_config_file_path()
        logger.info(f"[CONFIG RELOAD] 重新加载配置文件：{config_file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(config_file_path):
            logger.warning(f"[CONFIG RELOAD] 配置文件不存在：{config_file_path}")
            raise HTTPException(status_code=404, detail=f"配置文件不存在：{config_file_path}")
        
        # 重新加载配置
        new_config = reload_config()
        get_task_engine()
        
        logger.info(f"[CONFIG RELOAD] 配置重新加载成功")
        logger.info(f"[CONFIG RELOAD] storage.input_path = {new_config.storage.input_path}")
        logger.info(f"[CONFIG RELOAD] rename.template = '{new_config.rename.template}'")
        
        return {
            "message": "配置重新加载成功",
            "config_file": config_file_path,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新加载配置失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新加载配置失败：{str(e)}")


@app.get("/api/library-backup/status")
async def get_library_backup_status():
    service = get_backup_zip_service()
    return service.get_status()


@app.post("/api/library-backup/start")
async def start_library_backup():
    service = get_backup_zip_service()
    try:
        return await service.start()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动库存打包失败: {str(e)}")


@app.post("/api/library-backup/cancel")
async def cancel_library_backup():
    service = get_backup_zip_service()
    return await service.cancel()


@app.post("/api/library-backup/resume")
async def resume_library_backup():
    """从断点恢复库存打包任务"""
    service = get_backup_zip_service()
    try:
        return await service.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复库存打包失败: {str(e)}")


@app.get("/api/library-backup/checkpoint")
async def get_library_backup_checkpoint():
    """获取库存打包断点信息"""
    service = get_backup_zip_service()
    checkpoint = service.get_checkpoint_info()
    return checkpoint or {"has_checkpoint": False}


@app.post("/api/watcher/start")
async def start_watcher():
    """启动文件夹监视器"""
    watcher = get_watcher()
    watcher.start()
    return {"message": "监视器已启动"}

@app.post("/api/watcher/stop")
async def stop_watcher():
    """停止文件夹监视器"""
    watcher = get_watcher()
    watcher.stop()
    return {"message": "监视器已停止"}

@app.get("/api/watcher/status")
async def get_watcher_status():
    """获取监视器状态"""
    watcher = get_watcher()
    return {
        "is_running": watcher.is_running,
        "watch_path": get_config().storage.input_path,
        "pending_files": list(watcher.pending_files)
    }

@app.post("/api/scan")
async def scan_input_directory():
    """手动扫描输入目录"""
    result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="scan_input",
        source_label="仪表盘 / 扫描导入",
    )
    return {
        "message": f"扫描完成，找到 {result['found_count']} 个文件",
        "found_count": result["found_count"],
        "task_ids": result["task_ids"],
        "batch_id": result.get("batch_id"),
    }

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ========== 密码库管理 API ==========

class PasswordEntryCreate(BaseModel):
    """创建密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: str
    description: Optional[str] = None
    source: str = "manual"

class PasswordEntryUpdate(BaseModel):
    """更新密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None

class PasswordEntryResponse(BaseModel):
    """密码响应模型"""
    id: str
    rjcode: Optional[str]
    filename: Optional[str]
    password: str
    description: Optional[str]
    source: str
    use_count: int
    last_used_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    # 仅 create 接口在命中通用密码合并分支时返回 True，其他场景默认 False
    merged: bool = False

class PasswordListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PasswordEntryResponse]


class ConflictRetryRequest(BaseModel):
    # 兼容旧调用：单密码字段（前端老版本/外部脚本仍可能只传这个）。
    password: Optional[str] = None
    # 新增：多密码候选列表，按顺序依次尝试。
    # 前端新版重试弹窗会传这个。后端落到 task.task_metadata["manual_retry_passwords"]，
    # extract_service 在 manual_retry_password_only=True 时改用整张候选列表代替单密码。
    passwords: Optional[List[str]] = None
    filename_encoding: Optional[str] = None
    ignore_garbled: bool = False


class ConflictFilenamePreviewRequest(BaseModel):
    filename_encoding: Optional[str] = None
    password: Optional[str] = None
    limit: int = 80


class ConflictVolumeRenamePair(BaseModel):
    """单条分卷重命名映射，由前端"手动重命名分卷"弹窗逐行编辑产出。"""
    old: str
    new: str


class ConflictRenameVolumesRequest(BaseModel):
    """伪装多卷 conflict 的"手动重命名分卷"提交体。

    后端会把 ``renames`` 视为原子事务：所有 old 必须在 detection payload
    的 ``suspect_files`` 集合内，所有 new 必须落在同一目录、不与现有非 suspect
    文件冲突；任意一卷重命名失败立即回滚。``auto_retry=True`` 时重命名成功后
    自动起一个解压重试任务，跟现有 ``/api/conflicts/{id}/retry`` 同款逻辑。
    """
    renames: List[ConflictVolumeRenamePair]
    auto_retry: bool = True

@app.get("/api/passwords", response_model=PasswordListResponse)
async def get_passwords(
    rjcode: Optional[str] = None,
    filename: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20
):
    """获取密码列表，支持筛选和排序
    
    Args:
        rjcode: 按RJ号筛选
        filename: 按文件名筛选
        search: 搜索关键词
        sort_by: 排序字段（created_at, updated_at, rjcode, filename, use_count）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        query = db.query(PasswordEntry)
        
        if rjcode:
            query = query.filter(PasswordEntry.rjcode == rjcode)
        if filename:
            filename_pattern = f"%{_escape_ilike_pattern(filename)}%"
            query = query.filter(PasswordEntry.filename.ilike(filename_pattern, escape="!"))
        if search:
            query = query.filter(_password_search_filter(search))
        
        # 排序功能
        valid_sort_fields = {
            "created_at": PasswordEntry.created_at,
            "updated_at": PasswordEntry.updated_at,
            "rjcode": PasswordEntry.rjcode,
            "filename": PasswordEntry.filename,
            "use_count": PasswordEntry.use_count
        }
        
        # 设置默认排序字段
        sort_field_key = sort_by if sort_by else "created_at"
        sort_field = valid_sort_fields.get(sort_field_key, PasswordEntry.created_at)
        
        # 设置默认排序方向
        order = sort_order.lower() if sort_order else "desc"
        if order == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 200)
        total = query.order_by(None).count()
        passwords = query.offset((safe_page - 1) * safe_page_size).limit(safe_page_size).all()
        return PasswordListResponse(
            total=total,
            page=safe_page,
            page_size=safe_page_size,
            items=[PasswordEntryResponse(**p.to_dict()) for p in passwords]
        )
    finally:
        db.close()

@app.post("/api/passwords", response_model=PasswordEntryResponse)
async def create_password(entry: PasswordEntryCreate):
    """创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    try:
        normalized_rjcode = normalize_rjcode_value(entry.rjcode)
        normalized_filename = normalize_filename_value(entry.filename)
        normalized_password = normalize_password_value(entry.password)
        normalized_description = normalize_optional_text(entry.description)

        # 记录接收到的数据（用于调试）
        logger.info(
            f"创建密码条目 - RJ={normalized_rjcode}, File={normalized_filename}, "
            f"Password长度={len(normalized_password) if normalized_password else 0}"
        )
        
        # 确保密码不为空
        if not normalized_password:
            raise HTTPException(status_code=400, detail="密码不能为空")
        
        # 检查是否已存在相同RJ号或文件名的密码
        existing = None
        if normalized_rjcode:
            existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
        if not existing and normalized_filename:
            existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
        
        if existing:
            # 更新现有密码
            existing.rjcode = normalized_rjcode
            existing.filename = normalized_filename
            existing.password = normalized_password
            existing.description = normalized_description if entry.description is not None else existing.description
            existing.updated_at = datetime.now()
            db.commit()
            logger.info(f"更新密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
            return PasswordEntryResponse(**existing.to_dict())

        # 通用密码去重：未填 RJ号 / 文件名 时，把 password 字段相同的通用条目视为重复，自动合并
        if not normalized_rjcode and not normalized_filename:
            generic_existing = (
                db.query(PasswordEntry)
                .filter(
                    PasswordEntry.rjcode.is_(None),
                    PasswordEntry.filename.is_(None),
                    PasswordEntry.password == normalized_password,
                )
                .first()
            )
            if generic_existing:
                # 仅在原备注为空且新输入有备注时补充，避免覆盖已有备注
                changed = False
                if normalized_description and not (generic_existing.description or "").strip():
                    generic_existing.description = normalized_description
                    changed = True
                if changed:
                    generic_existing.updated_at = datetime.now()
                    db.commit()
                else:
                    # 不修改任何字段就不要刷新 updated_at，避免误触发"最近更新"排序
                    db.rollback()
                logger.info(
                    f"通用密码已存在，自动合并: id={generic_existing.id}, 备注补充={changed}"
                )
                return PasswordEntryResponse(**generic_existing.to_dict(), merged=True)

        # 创建新密码条目
        new_entry = PasswordEntry(
            id=str(uuid.uuid4()),
            rjcode=normalized_rjcode,
            filename=normalized_filename,
            password=normalized_password,
            description=normalized_description,
            source=entry.source
        )
        db.add(new_entry)
        db.commit()
        logger.info(f"创建密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
        return PasswordEntryResponse(**new_entry.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建密码条目失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存密码失败: {str(e)}")
    finally:
        db.close()

@app.post("/api/passwords/batch")
async def batch_create_passwords(entries: List[PasswordEntryCreate]):
    """批量创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    created_count = 0
    updated_count = 0
    
    try:
        for entry in entries:
            normalized_rjcode = normalize_rjcode_value(entry.rjcode)
            normalized_filename = normalize_filename_value(entry.filename)
            normalized_password = normalize_password_value(entry.password)
            normalized_description = normalize_optional_text(entry.description)

            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")

            # 检查是否已存在
            existing = None
            if normalized_rjcode:
                existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
            if not existing and normalized_filename:
                existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
            
            if existing:
                # 更新
                existing.rjcode = normalized_rjcode
                existing.filename = normalized_filename
                existing.password = normalized_password
                existing.description = normalized_description if entry.description is not None else existing.description
                existing.updated_at = datetime.now()
                updated_count += 1
            else:
                # 创建新条目
                new_entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    rjcode=normalized_rjcode,
                    filename=normalized_filename,
                    password=normalized_password,
                    description=normalized_description,
                    source=entry.source
                )
                db.add(new_entry)
                created_count += 1
        
        db.commit()
        logger.info(f"批量导入密码: 新建 {created_count} 条, 更新 {updated_count} 条")
        return {
            "message": f"批量导入完成",
            "created": created_count,
            "updated": updated_count
        }
    except Exception as e:
        db.rollback()
        logger.error(f"批量导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量导入失败: {str(e)}")
    finally:
        db.close()

@app.put("/api/passwords/{password_id}", response_model=PasswordEntryResponse)
async def update_password(password_id: str, entry: PasswordEntryUpdate):
    """更新密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")

        provided_fields = getattr(entry, "model_fields_set", None)
        if provided_fields is None:
            provided_fields = getattr(entry, "__fields_set__", set())

        if "rjcode" in provided_fields:
            password_entry.rjcode = normalize_rjcode_value(entry.rjcode)
        if "filename" in provided_fields:
            password_entry.filename = normalize_filename_value(entry.filename)
        if "password" in provided_fields:
            normalized_password = normalize_password_value(entry.password)
            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")
            password_entry.password = normalized_password
        if "description" in provided_fields:
            password_entry.description = normalize_optional_text(entry.description)
        
        password_entry.updated_at = datetime.now()
        db.commit()
        
        return PasswordEntryResponse(**password_entry.to_dict())
    finally:
        db.close()

@app.delete("/api/passwords/{password_id}")
async def delete_password(password_id: str):
    """删除密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")
        
        db.delete(password_entry)
        db.commit()
        return {"message": "密码已删除"}
    finally:
        db.close()

@app.get("/api/passwords/find-for-archive")
async def find_password_for_archive(archive_path: str):
    """查找适合指定压缩包的密码"""
    from ..models.database import PasswordEntry, get_db
    from pathlib import Path
    import re
    
    db = next(get_db())
    try:
        filename = Path(archive_path).name
        
        # 提取RJ号
        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
        rjcode = rj_match.group(0).upper() if rj_match else None
        
        # 首先尝试精确匹配RJ号
        if rjcode:
            entry = db.query(PasswordEntry).filter(PasswordEntry.rjcode == rjcode).first()
            if entry:
                return {
                    "found": True,
                    "password": normalize_password_value(entry.password),
                    "match_type": "rjcode",
                    "rjcode": rjcode,
                    "entry": entry.to_dict()
                }
        
        # 其次尝试文件名匹配
        entry = db.query(PasswordEntry).filter(PasswordEntry.filename == filename).first()
        if entry:
            return {
                "found": True,
                "password": normalize_password_value(entry.password),
                "match_type": "filename",
                "entry": entry.to_dict()
            }
        
        return {"found": False, "rjcode": rjcode}
    finally:
        db.close()

@app.post("/api/passwords/import-from-text")
async def import_passwords_from_text(request: Request):
    """从文本批量导入密码 - 每行一个密码，只添加密码不解析RJ号
    
    格式：每行一个密码，系统自动尝试匹配
    """
    from ..models.database import PasswordEntry, get_db
    import uuid
    
    data = await request.json()
    text = data.get("text", "")
    
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    
    db = next(get_db())
    entries = []
    lines = text.strip().split('\n')
    
    try:
        for line in lines:
            password = normalize_password_value(line)
            if not password:
                continue
            
            # 检查该密码是否已存在（避免重复）
            existing = db.query(PasswordEntry).filter(PasswordEntry.password == password).first()
            if existing:
                # 密码已存在，跳过
                entries.append({"password": password, "status": "skipped", "reason": "已存在"})
            else:
                # 创建新的密码条目（只存储密码，不关联RJ号或文件名）
                entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    password=password,
                    source='batch',
                    description='批量导入'
                )
                db.add(entry)
                entries.append({"password": password, "status": "success"})
        
        db.commit()
        success_count = sum(1 for e in entries if e["status"] == "success")
        skipped_count = sum(1 for e in entries if e["status"] == "skipped")
        
        return {
            "message": f"导入完成：新建 {success_count} 个，跳过 {skipped_count} 个（已存在）",
            "imported": success_count,
            "skipped": skipped_count,
            "entries": entries
        }
    except Exception as e:
        db.rollback()
        logger.error(f"导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        db.close()

_LOG_LINE_LEVEL_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]'
    r'|^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+-\s+\S+\s+-\s+(\w+)\s+-'
)
_LOG_LINE_STRUCT_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+\S+\s+-\s+(.+)$'
    r'|^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+-\s+\S+\s+-\s+(\w+)\s+-\s+(.+)$'
)
_LOG_TRACEBACK_BLOCK_PREFIX = "__KIKOERUMANAGER_LOG_BLOCK__"
_LOG_TRACEBACK_FRAGMENT_RE = re.compile(
    r'^(File ".+", line \d+, in .+'
    r'|During handling of the above exception'
    r'|The above exception was the direct cause'
    r'|Traceback \(most recent call last\):'
    r'|[A-Za-z_][\w.]+(?:Error|Exception)(?::|$)'
    r'|[\^~]{3,})'
)


def _parse_log_entry_line(line: str) -> tuple[str, str, str]:
    match = _LOG_LINE_STRUCT_RE.match(str(line or ""))
    if not match:
        return "", "ERROR", str(line or "")
    return (
        match.group(1) or match.group(4) or "",
        (match.group(2) or match.group(5) or "ERROR").upper(),
        match.group(3) or match.group(6) or "",
    )


def _looks_like_traceback_fragment(line: str) -> bool:
    return bool(_LOG_TRACEBACK_FRAGMENT_RE.match(str(line or "").strip()))


def _build_traceback_log_block(previous_line: str, stack_lines: List[str], *, fragment: bool = False) -> str:
    time_text, level_text, message = _parse_log_entry_line(previous_line)
    raw_lines = ([previous_line] if previous_line else []) + stack_lines
    stack_count = len(stack_lines)
    notice = (
        f"异常堆栈片段已折叠 {stack_count} 行，点击查看完整"
        if fragment
        else f"异常堆栈已折叠 {stack_count} 行，点击查看完整"
    )
    summary = f"{message}（{notice}）" if message else notice
    payload = {
        "type": "traceback",
        "time": time_text,
        "level": level_text,
        "message": summary,
        "full_message": "\n".join(raw_lines),
        "raw_line": "\n".join(raw_lines),
    }
    return _LOG_TRACEBACK_BLOCK_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _compact_traceback_log_lines(lines: List[str]) -> List[str]:
    """把 Python traceback 折叠成单条日志视图，避免前端系统日志被调用栈刷屏。"""
    if not lines:
        return []

    compacted: List[str] = []
    index = 0
    total = len(lines)
    while index < total:
        line = str(lines[index] or "")
        if line != "Traceback (most recent call last):" and not _LOG_LINE_LEVEL_RE.match(line):
            run_end = index + 1
            while run_end < total:
                next_line = str(lines[run_end] or "")
                if next_line == "Traceback (most recent call last):" or _LOG_LINE_LEVEL_RE.match(next_line):
                    break
                run_end += 1
            run_lines = [str(item or "") for item in lines[index:run_end]]
            if any(_looks_like_traceback_fragment(item) for item in run_lines):
                previous_line = ""
                if compacted and _LOG_LINE_LEVEL_RE.match(str(compacted[-1] or "")):
                    previous_line = compacted.pop()
                compacted.append(_build_traceback_log_block(previous_line, run_lines, fragment=True))
                index = run_end
                continue

        if line != "Traceback (most recent call last):":
            compacted.append(line)
            index += 1
            continue

        stack_lines = [line]
        index += 1
        while index < total:
            next_line = str(lines[index] or "")
            if _LOG_LINE_LEVEL_RE.match(next_line):
                break
            stack_lines.append(next_line)
            index += 1

        previous_line = compacted.pop() if compacted else ""
        compacted.append(_build_traceback_log_block(previous_line, stack_lines))

    return compacted


def _resolve_main_log_path() -> Optional[str]:
    """返回当前应使用的主日志文件路径，找不到时回退为 None。"""
    from ..core.app_logging import get_main_log_path, get_log_dir
    main = get_main_log_path()
    if os.path.exists(main):
        return main
    # 桌面独立入口可能仍然使用 desktop_app.log
    fallback = os.path.join(get_log_dir(), 'desktop_app.log')
    if os.path.exists(fallback):
        return fallback
    return None


def _iter_log_files_for_search() -> List[str]:
    """返回搜索时应该扫描的文件列表：主日志 + 轮转备份 + 旧 desktop_app.log。

    优先级（从"新"到"旧"）：主 app.log -> app.log.1 -> app.log.2 -> ...
    -> desktop_app.log。按这个顺序扫描，用户搜关键词时通常关心最近的命中。
    """
    from ..core.app_logging import list_log_files
    infos = list_log_files()
    ordered: List[str] = []
    # 主日志
    for info in infos:
        if info.is_main:
            ordered.append(info.path)
            break
    # 按 app.log.N 的 N 从小到大（即时间上从近到远）
    backups = [info for info in infos if info.is_backup]

    def _backup_index(name: str) -> int:
        # app.log.3 -> 3；解析不到放最大值，保证它排最后
        try:
            return int(name.rsplit('.', 1)[-1])
        except (ValueError, TypeError):
            return 10_000

    backups.sort(key=lambda info: _backup_index(info.name))
    ordered.extend(info.path for info in backups)

    # 额外兜底：非轮转命名的历史文件
    for info in infos:
        if not info.is_main and not info.is_backup and info.path not in ordered:
            ordered.append(info.path)

    return ordered


def _tail_lines(path: str, n: int) -> List[str]:
    """反向块读取文件末尾 n 行。避免大文件全文遍历。"""
    if n <= 0:
        return []
    chunk_size = 64 * 1024
    data = b''
    with open(path, 'rb') as bf:
        bf.seek(0, os.SEEK_END)
        pos = bf.tell()
        lines_found = 0
        while pos > 0 and lines_found <= n * 2:
            read_size = chunk_size if pos >= chunk_size else pos
            pos -= read_size
            bf.seek(pos)
            block = bf.read(read_size)
            data = block + data
            lines_found = data.count(b'\n')
            if lines_found >= n + 1:
                break
        # 尾窗可能完全落在 traceback 中间。仅在窗口里没有任何结构化日志头时，
        # 再向前补有限上下文，让堆栈块继承真实时间而不是显示 --:--:--。
        context_bytes = 0
        max_context_bytes = 512 * 1024
        window_lines = data.decode('utf-8', errors='ignore').splitlines()
        has_log_boundary = any(_LOG_LINE_LEVEL_RE.match(line.strip()) for line in window_lines)
        while pos > 0 and not has_log_boundary and context_bytes < max_context_bytes:
            read_size = min(chunk_size, pos, max_context_bytes - context_bytes)
            pos -= read_size
            bf.seek(pos)
            block = bf.read(read_size)
            data = block + data
            context_bytes += len(block)
            block_lines = block.decode('utf-8', errors='ignore').splitlines()
            has_log_boundary = any(_LOG_LINE_LEVEL_RE.match(line.strip()) for line in block_lines)
    text = data.decode('utf-8', errors='ignore')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return _compact_traceback_log_lines(lines)[-n:]


def _read_log_payload(log_file: str, line_limit: int, since_offset: int = -1) -> Dict[str, Any]:
    file_size = os.path.getsize(log_file)
    if 0 <= since_offset <= file_size:
        if since_offset == file_size:
            return {"logs": [], "next_offset": file_size, "is_full": False}
        # 增量窗口太大时直接回落到尾部 line_limit 行，避免暂停很久后一次性 read()
        # 几十 MB 文本并把前端/后端都拖住。
        max_incremental_bytes = 2 * 1024 * 1024
        if file_size - since_offset > max_incremental_bytes:
            result = _tail_lines(log_file, line_limit)
            return {"logs": result, "next_offset": file_size, "is_full": True}
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(since_offset)
            new_lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        new_lines = _compact_traceback_log_lines(new_lines)
        if len(new_lines) > line_limit:
            new_lines = new_lines[-line_limit:]
        return {"logs": new_lines, "next_offset": file_size, "is_full": False}

    result = _tail_lines(log_file, line_limit)
    return {"logs": result, "next_offset": file_size, "is_full": True}


def _runtime_log_stream_config() -> Dict[str, int]:
    cfg = getattr(get_config(), "runtime_buffer", None)
    return {
        "batch_size": max(50, min(int(getattr(cfg, "log_stream_batch_size", 300) or 300), 5000)),
        "flush_ms": max(100, min(int(getattr(cfg, "log_stream_flush_ms", 250) or 250), 5000)),
    }


def _trim_log_stream_payload(payload: Dict[str, Any], batch_size: int) -> Dict[str, Any]:
    next_payload = dict(payload or {})
    logs = list(next_payload.get("logs") or [])
    original_count = len(logs)
    dropped_count = 0
    if original_count > batch_size:
        dropped_count = original_count - batch_size
        logs = logs[-batch_size:]
        next_payload["logs"] = logs
        next_payload["is_truncated_batch"] = True
        with _LOG_STREAM_STATUS_LOCK:
            global _LOG_STREAM_DROPPED_COUNT
            _LOG_STREAM_DROPPED_COUNT += dropped_count
    next_payload["batch_size"] = len(logs)
    next_payload["original_count"] = original_count
    next_payload["dropped_count"] = dropped_count
    return next_payload


def _log_stream_status_payload() -> Dict[str, Any]:
    from ..core.app_logging import get_app_logging_status

    config = _runtime_log_stream_config()
    log_file = _resolve_main_log_path()
    stat_payload: Dict[str, Any] = {
        "path": os.path.basename(log_file) if log_file else "",
        "size_bytes": 0,
        "mtime": None,
    }
    if log_file:
        try:
            stat_result = os.stat(log_file)
            stat_payload.update({
                "size_bytes": int(stat_result.st_size),
                "mtime": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
            })
        except OSError:
            pass
    with _LOG_STREAM_STATUS_LOCK:
        active_count = _LOG_STREAM_ACTIVE_COUNT
        total_connections = _LOG_STREAM_TOTAL_CONNECTIONS
        dropped_count = _LOG_STREAM_DROPPED_COUNT
    executor = _LOG_IO_EXECUTOR
    search_executor = _LOG_SEARCH_EXECUTOR
    return {
        "enabled": True,
        "batch_size": config["batch_size"],
        "flush_ms": config["flush_ms"],
        "active_streams": active_count,
        "total_connections": total_connections,
        "dropped_count": dropped_count,
        "log_file": stat_payload,
        "executor": {
            "max_workers": getattr(executor, "_max_workers", None) if executor else 0,
            "threads": len(getattr(executor, "_threads", []) or []) if executor else 0,
            "queue_size": getattr(getattr(executor, "_work_queue", None), "qsize", lambda: None)() if executor else 0,
        },
        "search_executor": {
            "max_workers": getattr(search_executor, "_max_workers", None) if search_executor else 0,
            "threads": len(getattr(search_executor, "_threads", []) or []) if search_executor else 0,
            "queue_size": getattr(getattr(search_executor, "_work_queue", None), "qsize", lambda: None)() if search_executor else 0,
        },
        "writer": get_app_logging_status(),
        "generated_at": datetime.now().isoformat(),
    }


def _sse_payload(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _log_file_signature(log_file: str) -> tuple[int, int]:
    """日志流空闲轮询用的轻量文件签名。"""
    stat_result = os.stat(log_file)
    return int(stat_result.st_size), int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))


@app.get("/api/logs")
async def get_logs(lines: int = 100, since_offset: int = -1):
    """获取日志文件内容。

    - ``since_offset=-1``：全量模式，返回末尾 lines 条日志及当前文件字节偏移量。
    - ``since_offset>=0``：增量模式，仅返回该字节偏移后的新内容（文件未轮转时）。
      若文件已轮转（size < since_offset），自动退回全量模式。
    响应格式：``{ "logs": [...], "next_offset": N, "is_full": bool }``
    """
    log_file = _resolve_main_log_path()
    if not log_file:
        return {"logs": [], "next_offset": 0, "is_full": True}

    try:
        line_limit = max(50, min(int(lines or 100), 5000))
        _log_file = log_file

        def _read_log():
            return _read_log_payload(_log_file, line_limit, since_offset)

        return await _run_log_io(_read_log)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")


@app.get("/api/logs/stream")
async def stream_logs(request: Request, lines: int = 300, since_offset: int = -1):
    """SSE 推送系统日志增量。

    连接建立后先补一段最近历史或 since_offset 之后的新内容；之后按运行态
    flush 间隔检查主日志文件偏移。心跳用于防止代理/浏览器静默断开。
    """
    line_limit = max(50, min(int(lines or 300), 5000))
    stream_config = _runtime_log_stream_config()
    batch_size = int(stream_config["batch_size"])
    poll_interval = max(0.1, int(stream_config["flush_ms"]) / 1000.0)

    async def generator():
        current_offset = max(-1, int(since_offset or -1))
        last_heartbeat_at = time.monotonic()
        active_log_path = ""
        active_log_signature: tuple[int, int] | None = None
        sent_missing_notice = False
        global _LOG_STREAM_ACTIVE_COUNT, _LOG_STREAM_TOTAL_CONNECTIONS
        with _LOG_STREAM_STATUS_LOCK:
            _LOG_STREAM_ACTIVE_COUNT += 1
            _LOG_STREAM_TOTAL_CONNECTIONS += 1
        try:
            while True:
                log_file = _resolve_main_log_path()
                if not log_file:
                    yield _sse_payload("connected", {
                        "logs": [],
                        "next_offset": 0,
                        "is_full": True,
                        "message": "日志文件尚未创建",
                        "time": datetime.now().isoformat(),
                    })
                    sent_missing_notice = True
                    break

                active_log_path = log_file
                payload = await _run_log_io(_read_log_payload, log_file, line_limit, current_offset)
                payload = _trim_log_stream_payload(payload, batch_size)
                current_offset = int(payload.get("next_offset") or 0)
                try:
                    active_log_signature = await _run_log_io(_log_file_signature, log_file)
                except OSError:
                    active_log_signature = None
                yield _sse_payload("connected", {
                    **payload,
                    "path": os.path.basename(log_file),
                    "time": datetime.now().isoformat(),
                })
                break

            while True:
                if await request.is_disconnected():
                    break

                log_file = _resolve_main_log_path()
                if not log_file:
                    now = time.monotonic()
                    if not sent_missing_notice:
                        sent_missing_notice = True
                        yield _sse_payload("reset", {
                            "logs": [],
                            "next_offset": 0,
                            "is_full": True,
                            "message": "日志文件尚未创建",
                            "time": datetime.now().isoformat(),
                        })
                    elif now - last_heartbeat_at >= 20:
                        last_heartbeat_at = now
                        yield _sse_payload("heartbeat", {
                            "next_offset": 0,
                            "time": datetime.now().isoformat(),
                        })
                    await asyncio.sleep(poll_interval)
                    continue
                sent_missing_notice = False

                if log_file != active_log_path:
                    active_log_path = log_file
                    current_offset = -1
                    active_log_signature = None

                try:
                    current_signature = await _run_log_io(_log_file_signature, log_file)
                except OSError:
                    await asyncio.sleep(poll_interval)
                    continue

                if active_log_signature == current_signature:
                    now = time.monotonic()
                    if now - last_heartbeat_at >= 20:
                        last_heartbeat_at = now
                        yield _sse_payload("heartbeat", {
                            "next_offset": current_offset,
                            "time": datetime.now().isoformat(),
                        })
                    await asyncio.sleep(poll_interval)
                    continue

                try:
                    payload = await _run_log_io(_read_log_payload, log_file, line_limit, current_offset)
                    payload = _trim_log_stream_payload(payload, batch_size)
                except OSError:
                    await asyncio.sleep(poll_interval)
                    continue

                current_offset = int(payload.get("next_offset") or current_offset or 0)
                active_log_signature = current_signature
                log_lines = payload.get("logs") or []
                if log_lines:
                    event_name = "reset" if payload.get("is_full") else "log"
                    yield _sse_payload(event_name, {
                        **payload,
                        "path": os.path.basename(log_file),
                        "time": datetime.now().isoformat(),
                    })

                now = time.monotonic()
                if now - last_heartbeat_at >= 20:
                    last_heartbeat_at = now
                    yield _sse_payload("heartbeat", {
                        "next_offset": current_offset,
                        "time": datetime.now().isoformat(),
                    })
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[系统日志流] SSE 异常: %s", sanitize_text_for_log(exc))
            yield _sse_payload("stream_error", {
                "message": str(exc),
                "time": datetime.now().isoformat(),
            })
        finally:
            with _LOG_STREAM_STATUS_LOCK:
                _LOG_STREAM_ACTIVE_COUNT = max(0, _LOG_STREAM_ACTIVE_COUNT - 1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# 全文检索硬上限：保护后端在「用户搜了一个高频词」场景下不耗光内存 / CPU。
_LOG_SEARCH_TOTAL_SCAN_MB_CAP = 96    # 跨所有文件总和 max 96MB
_LOG_SEARCH_PER_FILE_SCAN_MB_CAP = 64  # 单文件 max 64MB
_LOG_SEARCH_LIMIT_MAX = 1000           # 单页返回上限
_LOG_SEARCH_KEYWORD_MAX_LEN = 200
_LOG_LINE_LENGTH_CAP = 16 * 1024       # 单行字符上限：超长 traceback 截断，避免响应膨胀
_LOG_SEARCH_RAW_FRAGMENT_BYTES = 64 * 1024
_LOG_SEARCH_CURSOR_VERSION = 2


def _encode_log_search_cursor(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_log_search_cursor(value: str) -> Optional[Dict[str, Any]]:
    token = str(value or "").strip()
    if not token or token == "0" or len(token) > 4096:
        return None
    try:
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("v") or 0) != _LOG_SEARCH_CURSOR_VERSION:
        return None
    return payload


def _log_search_query_signature(
    keyword: str,
    levels: set[str],
    per_file_scan_bytes: int,
    include_backups: bool,
) -> str:
    source = json.dumps(
        {
            "q": keyword,
            "levels": sorted(levels),
            "scan": per_file_scan_bytes,
            "backups": include_backups,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _build_log_search_snapshots(
    candidates: List[str],
    per_file_scan_bytes: int,
    cursor_payload: Optional[Dict[str, Any]],
    query_signature: str,
) -> tuple[List[Dict[str, Any]], int, int, int, bool]:
    current_by_name = {os.path.basename(path): path for path in candidates}
    cursor_reset = False
    snapshots: List[Dict[str, Any]] = []

    if cursor_payload and cursor_payload.get("query") == query_signature:
        raw_files = cursor_payload.get("files")
        if isinstance(raw_files, list) and raw_files:
            for raw in raw_files:
                if not isinstance(raw, dict):
                    snapshots = []
                    break
                name = str(raw.get("name") or "")
                path = current_by_name.get(name)
                expected_size = int(raw.get("size") or 0)
                if not path or expected_size < 0:
                    snapshots = []
                    break
                try:
                    current_size = os.path.getsize(path)
                except OSError:
                    snapshots = []
                    break
                # 主日志允许继续增长；缩小代表轮转/截断，旧游标必须失效。
                if current_size < expected_size:
                    snapshots = []
                    break
                snapshots.append({
                    "name": name,
                    "path": path,
                    "size": expected_size,
                    "start": max(0, expected_size - per_file_scan_bytes),
                })
        if not snapshots:
            cursor_reset = True
    elif cursor_payload:
        cursor_reset = True

    if not snapshots:
        for path in candidates:
            try:
                file_size = os.path.getsize(path)
            except OSError:
                continue
            snapshots.append({
                "name": os.path.basename(path),
                "path": path,
                "size": file_size,
                "start": max(0, file_size - per_file_scan_bytes),
            })
        return snapshots, 0, snapshots[0]["start"] if snapshots else 0, 0, cursor_reset

    file_index = max(0, min(int(cursor_payload.get("file") or 0), len(snapshots) - 1))
    snapshot = snapshots[file_index]
    offset = max(snapshot["start"], min(int(cursor_payload.get("offset") or snapshot["start"]), snapshot["size"]))
    matched = max(0, int(cursor_payload.get("matched") or 0))
    return snapshots, file_index, offset, matched, cursor_reset


def _log_search_cursor_payload(
    snapshots: List[Dict[str, Any]],
    query_signature: str,
    file_index: int,
    offset: int,
    matched: int,
) -> str:
    return _encode_log_search_cursor({
        "v": _LOG_SEARCH_CURSOR_VERSION,
        "query": query_signature,
        "file": file_index,
        "offset": offset,
        "matched": matched,
        "files": [{"name": item["name"], "size": item["size"]} for item in snapshots],
    })


def _search_log_snapshots(
    snapshots: List[Dict[str, Any]],
    *,
    keyword: str,
    levels: set[str],
    limit: int,
    total_scan_budget: int,
    query_signature: str,
    start_file_index: int,
    start_offset: int,
    matched_before: int,
    cancel_event: threading.Event,
    cursor_reset: bool,
) -> Dict[str, Any]:
    results: List[str] = []
    full_results: List[str] = []
    total_scan_bytes = 0
    scanned_files: List[Dict[str, Any]] = []
    next_file_index = start_file_index
    next_offset = start_offset
    has_more = False
    stopped_early = False
    cancelled = False

    for file_index in range(start_file_index, len(snapshots)):
        snapshot = snapshots[file_index]
        file_start = int(snapshot["start"])
        file_end = int(snapshot["size"])
        offset = start_offset if file_index == start_file_index else file_start
        offset = max(file_start, min(offset, file_end))
        file_scan_bytes = 0
        budget_exhausted = False
        extra_match_offset: Optional[int] = None

        try:
            with open(snapshot["path"], "rb") as handle:
                handle.seek(offset)
                if offset == file_start and file_start > 0:
                    # 初始窗口可能落在一条超长日志中间，分块丢弃残片，避免 readline()
                    # 因无换行一次分配整段文本。
                    while handle.tell() < file_end:
                        if cancel_event.is_set():
                            cancelled = True
                            break
                        remaining = min(_LOG_SEARCH_RAW_FRAGMENT_BYTES, file_end - handle.tell())
                        fragment = handle.readline(remaining)
                        if not fragment:
                            break
                        consumed = len(fragment)
                        file_scan_bytes += consumed
                        total_scan_bytes += consumed
                        if fragment.endswith((b"\n", b"\r")):
                            break
                        if total_scan_bytes >= total_scan_budget:
                            budget_exhausted = True
                            break
                if cancelled:
                    break
                if budget_exhausted:
                    next_file_index = file_index
                    next_offset = handle.tell()
                    has_more = True
                    stopped_early = True
                    break

                logical_start = handle.tell()
                logical_level = "INFO"
                logical_match = False
                logical_display = ""
                logical_fragments: List[str] = []
                overlap = ""
                first_fragment = True

                while handle.tell() < file_end:
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    if total_scan_bytes >= total_scan_budget:
                        budget_exhausted = True
                        next_file_index = file_index
                        next_offset = logical_start
                        break

                    remaining = min(
                        _LOG_SEARCH_RAW_FRAGMENT_BYTES,
                        file_end - handle.tell(),
                        total_scan_budget - total_scan_bytes,
                    )
                    if remaining <= 0:
                        budget_exhausted = True
                        next_file_index = file_index
                        next_offset = logical_start
                        break
                    raw_bytes = handle.readline(remaining)
                    if not raw_bytes:
                        break
                    consumed = len(raw_bytes)
                    file_scan_bytes += consumed
                    total_scan_bytes += consumed
                    line_complete = raw_bytes.endswith((b"\n", b"\r")) or handle.tell() >= file_end
                    text = raw_bytes.decode("utf-8", errors="ignore").rstrip("\r\n")
                    logical_fragments.append(text)

                    if first_fragment:
                        match = _LOG_LINE_LEVEL_RE.match(text)
                        logical_level = (match.group(2) or match.group(4) or "INFO").upper() if match else "INFO"
                        first_fragment = False

                    if not levels or logical_level in levels:
                        lowered = text.lower()
                        search_text = overlap + lowered
                        if not keyword or keyword in search_text:
                            logical_match = True
                            if not logical_display:
                                display = (overlap + text).strip()
                                logical_display = display[:_LOG_LINE_LENGTH_CAP]
                                if len(display) > _LOG_LINE_LENGTH_CAP or not line_complete:
                                    logical_display += "…"
                        overlap = lowered[-max(0, len(keyword) - 1):] if keyword else ""

                    if not line_complete:
                        continue

                    if logical_match:
                        full_line = "".join(logical_fragments).strip()
                        if not logical_display:
                            logical_display = full_line[:_LOG_LINE_LENGTH_CAP]
                            if len(full_line) > _LOG_LINE_LENGTH_CAP:
                                logical_display += "…"
                        if len(results) < limit:
                            results.append(logical_display)
                            full_results.append(full_line)
                        else:
                            extra_match_offset = logical_start
                            has_more = True
                            break

                    logical_start = handle.tell()
                    logical_level = "INFO"
                    logical_match = False
                    logical_display = ""
                    logical_fragments = []
                    overlap = ""
                    first_fragment = True

                if cancelled:
                    break
                if extra_match_offset is not None:
                    next_file_index = file_index
                    next_offset = extra_match_offset
                    break
                if budget_exhausted:
                    has_more = True
                    stopped_early = True
                    break
                next_file_index = file_index + 1
                next_offset = snapshots[file_index + 1]["start"] if file_index + 1 < len(snapshots) else file_end
        except OSError:
            next_file_index = file_index + 1
            continue
        finally:
            scanned_files.append({
                "name": snapshot["name"],
                "bytes": file_scan_bytes,
                "total_bytes": file_end,
            })

        if has_more or stopped_early:
            break

    if not cancelled and not has_more and next_file_index < len(snapshots):
        has_more = True
    matched_after = matched_before + len(results)
    next_cursor = ""
    if has_more and snapshots:
        safe_file_index = min(next_file_index, len(snapshots) - 1)
        next_cursor = _log_search_cursor_payload(
            snapshots,
            query_signature,
            safe_file_index,
            next_offset,
            matched_after,
        )
    return {
        "logs": results,
        "full_logs": full_results,
        "total_matched": matched_after + (1 if has_more else 0),
        "matched_before": matched_before,
        "matched_after": matched_after,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total_is_estimate": has_more,
        "scan_bytes": total_scan_bytes,
        "scanned_files": scanned_files,
        "stopped_early": stopped_early,
        "cursor_reset": cursor_reset,
        "cancelled": cancelled,
    }


@app.get("/api/logs/search")
async def search_logs(
    request: Request,
    q: str = '',
    levels: str = '',
    limit: int = 500,
    cursor: str = '',
    max_scan_mb: int = 16,
    include_backups: bool = True,
):
    """全文检索，跨主日志 + 所有轮转备份。

    - ``q``：关键词（大小写不敏感，空则不过滤）
    - ``levels``：逗号分隔的级别列表，如 ``INFO,ERROR``（空则不过滤）
    - ``limit``：单页返回条数（默认 500，上限 1000）
    - ``cursor``：不透明续扫游标（翻页时原样传回上一次的 next_cursor）
    - ``max_scan_mb``：单文件扫描窗口上限（默认 16MB，硬上限 64MB）
    - ``include_backups``：是否搜索轮转备份（关闭时只扫主日志）

    大文本搜索保护：
    - **streaming 逐行扫描**：不再一次性 ``decode + splitlines`` 整段（16MB 文本
      会膨胀成 30~60MB Python str + list of str，跨 6 个文件就上百 MB），
      改成 ``for raw_bytes in f`` 逐行迭代，每行独立 decode，Python 内存占用
      恒定在几 KB（单行 buffer + results list）。
    - **总扫描预算**：跨所有文件 max 96MB，触顶立即停。
    - **单行截断**：超过 16KB 的行（典型 traceback dump）截到 16KB + ``…``，
      避免少数长行把单页响应撑到几十 MB。
    - **续扫游标**：下一页从上次文件字节位置继续，不重复扫描和跳过旧命中。
    - **协作取消**：浏览器 abort 后通知搜索线程尽快退出，不继续占用唯一 worker。
    - **有界行读取**：无换行大文本按 64KB 片段匹配，不一次分配整条超长行。

    响应：``{ logs, total_matched, next_cursor, has_more, scan_bytes, scanned_files }``
    """
    kw_raw = (q or '').strip()
    if kw_raw and len(kw_raw) > _LOG_SEARCH_KEYWORD_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"关键词最多 {_LOG_SEARCH_KEYWORD_MAX_LEN} 字符")
    if not kw_raw and not levels:
        raise HTTPException(status_code=400, detail="请提供关键词或日志级别筛选条件")

    candidates = _iter_log_files_for_search() if include_backups else []
    if not candidates:
        main = _resolve_main_log_path()
        candidates = [main] if main else []
    if not candidates:
        return {
            "logs": [],
            "total_matched": 0,
            "next_cursor": "",
            "has_more": False,
            "scan_bytes": 0,
            "scanned_files": [],
        }

    try:
        max_limit = max(50, min(int(limit or 500), _LOG_SEARCH_LIMIT_MAX))
        kw = kw_raw.lower()
        lvl_set = {v.strip().upper() for v in levels.split(',') if v.strip()} if levels else set()
        per_file_scan_bytes = max(
            1 * 1024 * 1024,
            min(int(max_scan_mb or 16), _LOG_SEARCH_PER_FILE_SCAN_MB_CAP) * 1024 * 1024,
        )
        total_scan_budget = _LOG_SEARCH_TOTAL_SCAN_MB_CAP * 1024 * 1024
        query_signature = _log_search_query_signature(kw, lvl_set, per_file_scan_bytes, include_backups)
        cursor_payload = _decode_log_search_cursor(cursor)
        snapshots, file_index, start_offset, matched_before, cursor_reset = _build_log_search_snapshots(
            candidates,
            per_file_scan_bytes,
            cursor_payload,
            query_signature,
        )
        cancel_event = threading.Event()

        def _search():
            return _search_log_snapshots(
                snapshots,
                keyword=kw,
                levels=lvl_set,
                limit=max_limit,
                total_scan_budget=total_scan_budget,
                query_signature=query_signature,
                start_file_index=file_index,
                start_offset=start_offset,
                matched_before=matched_before,
                cancel_event=cancel_event,
                cursor_reset=cursor_reset,
            )

        search_task = asyncio.create_task(_run_log_search_io(_search))
        try:
            while True:
                done, _ = await asyncio.wait({search_task}, timeout=0.1)
                if done:
                    return await search_task
                if await request.is_disconnected():
                    cancel_event.set()
                    return await search_task
        finally:
            if not search_task.done():
                cancel_event.set()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[日志检索] 失败 q=%r levels=%r: %s", kw_raw, levels, sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"日志检索失败: {str(e)}")


@app.get("/api/logs/info")
async def get_logs_info():
    """返回日志目录下所有 app.log / app.log.N / desktop_app.log 的尺寸信息。

    前端的"日志管理"面板据此展示，并给出"清理备份 / 截断主日志"入口。
    """
    from ..core.app_logging import list_log_files, get_log_dir, get_main_log_path

    def _collect():
        files = [info.to_dict() for info in list_log_files()]
        total = sum(int(item.get("size_bytes") or 0) for item in files)
        main_size = 0
        backup_size = 0
        for item in files:
            size = int(item.get("size_bytes") or 0)
            if item.get("is_main"):
                main_size += size
            elif item.get("is_backup"):
                backup_size += size
        return {
            "log_dir": get_log_dir(),
            "main_log_path": get_main_log_path(),
            "files": files,
            "total_bytes": total,
            "main_bytes": main_size,
            "backup_bytes": backup_size,
            "max_mb_per_file": int(
                os.environ.get("KIKOERUMANAGER_LOG_MAX_MB", "20") or 20
            ),
            "backup_count": int(
                os.environ.get("KIKOERUMANAGER_LOG_BACKUPS", "5") or 5
            ),
        }

    return await _run_log_io(_collect)


@app.get("/api/logs/stream/status")
async def get_log_stream_status():
    """返回系统日志流运行态，不扫描历史日志。"""
    return await _run_log_io(_log_stream_status_payload)


class LogCleanupRequest(BaseModel):
    purge_backups: bool = False
    truncate_main: bool = False
    keep_tail_mb: float = 2.0
    rotate: bool = False


@app.post("/api/logs/cleanup")
async def cleanup_logs(payload: LogCleanupRequest):
    """清理日志文件。

    参数均为布尔开关，可叠加（按 rotate -> purge_backups -> truncate_main 顺序执行）：
    - ``rotate``：立即触发一次 RotatingFileHandler.doRollover，把当前主日志滚到 .1。
    - ``purge_backups``：删除所有 app.log.N 备份文件。
    - ``truncate_main``：把主日志截断到最后 ``keep_tail_mb`` MB（默认 2MB）。
    """
    from ..core.app_logging import (
        cleanup_log_files,
        force_rotate_main_log,
    )

    if not (payload.purge_backups or payload.truncate_main or payload.rotate):
        raise HTTPException(status_code=400, detail="至少要选一种清理动作")

    keep_bytes = max(0, int(float(payload.keep_tail_mb or 0) * 1024 * 1024))

    def _run() -> Dict[str, Any]:
        rotate_summary: Dict[str, Any] = {}
        if payload.rotate:
            rotate_summary = force_rotate_main_log()

        cleanup_summary = cleanup_log_files(
            purge_backups=payload.purge_backups,
            truncate_main=payload.truncate_main,
            keep_tail_bytes=keep_bytes,
        )
        return {
            "rotate": rotate_summary,
            "cleanup": cleanup_summary,
        }

    try:
        result = await _run_log_io(_run)
    except Exception as exc:  # pragma: no cover - 兜底
        logger.warning("[日志管理] 清理日志失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"清理日志失败: {exc}")

    logger.info(
        "[日志管理] cleanup rotate=%s purge_backups=%s truncate_main=%s keep_tail_mb=%s",
        payload.rotate,
        payload.purge_backups,
        payload.truncate_main,
        payload.keep_tail_mb,
    )
    return {"ok": True, **result}

@app.get("/api/conflicts")
async def get_conflicts(include_stats: bool = False):
    """获取问题作品列表"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..core.task_engine import TaskStatus
    from ..models.database import ConflictWork, Task as TaskRecord, get_db
    from ..core.json_safety import safe_json_value

    def _normalize_conflict_metadata(raw_metadata):
        if isinstance(raw_metadata, dict):
            return safe_json_value(dict(raw_metadata))
        if raw_metadata in (None, "", []):
            return {}
        if isinstance(raw_metadata, str):
            with contextlib.suppress(Exception):
                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    return safe_json_value(parsed)
            return safe_json_value({"raw_metadata": raw_metadata})
        if isinstance(raw_metadata, list):
            return safe_json_value({"raw_metadata": raw_metadata})
        with contextlib.suppress(Exception):
            return safe_json_value(dict(raw_metadata))
        return safe_json_value({"raw_metadata": str(raw_metadata)})

    active_task_statuses = {
        TaskStatus.PENDING.value,
        TaskStatus.PROCESSING.value,
        TaskStatus.PAUSED.value,
        TaskStatus.WAITING_MANUAL.value,
        TaskStatus.WAITING_RETRY.value,
    }

    def _get_linked_task_status(task_id: Any) -> str:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return ""

        linked_task = engine.get_task(normalized_task_id)
        if linked_task is not None:
            linked_status = getattr(linked_task, "status", "")
            if isinstance(linked_status, TaskStatus):
                return linked_status.value
            return str(linked_status or "").strip().lower()

        db_task = db.query(TaskRecord.status).filter(TaskRecord.id == normalized_task_id).first()
        return str((db_task[0] if db_task else "") or "").strip().lower()

    db = next(get_db())
    _route_t_start = time.monotonic()
    try:
        resolution_service = get_conflict_resolution_service()
        engine = get_task_engine()
        # 之前这里有一个 _backfill_failed_import_conflicts 兑底回扫：
        # 每次列表请求都拉最近 200 条 failed task → 200×N+1 ConflictWork.exists query
        # → 200 次同步 os.path.exists(source_path)（远程挂载累计 60s+ 直接打死接口）
        # → 写一个名为 source_missing 的字段。
        # 经全局 grep 确认 source_missing 字段在前后端 0 处读取（死字段），
        # 任务失败 → 写问题作品的主路径已经在 task_engine._record_problem_work_for_*
        # 稳定运行（产物：当前 conflict_works 285 条全是主路径写的）。
        # 这个函数只是历史包袱，删掉。
        _t_query_start = time.monotonic()
        conflicts = db.query(ConflictWork).filter(
            ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
        ).order_by(desc(ConflictWork.created_at)).all()
        _t_query_ms = (time.monotonic() - _t_query_start) * 1000
        logger.debug(
            "[/api/conflicts] include_stats=%s db_query=%.0fms count=%s",
            include_stats, _t_query_ms, len(conflicts),
        )

        # ---- 第一阶段：串行处理 DB 写入（状态恢复）和纯计算字段 ----
        # SQLAlchemy session 不能并发使用，所以这一段保持串行。
        _t_phase1_start = time.monotonic()
        per_conflict_actions: list[list[str]] = []
        for conflict in conflicts:
            try:
                conflict.new_metadata = _normalize_conflict_metadata(conflict.new_metadata)
                normalized_status = str(conflict.status or "").strip().upper()
                if normalized_status == "PROCESSING":
                    _nm = _normalize_conflict_metadata(conflict.new_metadata)
                    _recovery_task_id = str((_nm.get("resolution_task_id") or conflict.task_id or "")).strip()
                    linked_task_status = _get_linked_task_status(_recovery_task_id)
                    # 特殊情况：resolution_task_id 未设置（KEEP_NEW 历史 bug，已补存）且
                    # fallback 的原始任务是 WAITING_MANUAL（等待用户处理）。
                    # 此时 resolution_task_state=="queued" 说明 KEEP_NEW 曾被触发但任务从未真正创建，
                    # WAITING_MANUAL 不代表 resolution 任务仍在运行，应强制恢复为 PENDING。
                    _is_stale_keep_new = (
                        not _nm.get("resolution_task_id")
                        and str(_nm.get("resolution_task_state") or "").lower() == "queued"
                        and str(_nm.get("resolution_action") or "").upper() == "KEEP_NEW"
                        and linked_task_status == "waiting_manual"
                    )
                    _is_retry_waiting_manual_done = (
                        str(_nm.get("resolution_action") or "").upper() == "RETRY"
                        and linked_task_status == "waiting_manual"
                    )
                    if linked_task_status not in active_task_statuses or _is_stale_keep_new or _is_retry_waiting_manual_done:
                        conflict.status = "PENDING"
                        next_metadata = _normalize_conflict_metadata(conflict.new_metadata)
                        if _is_retry_waiting_manual_done:
                            next_metadata["retry_result"] = "failed"
                            next_metadata["resolution_task_state"] = "failed"
                            next_metadata.setdefault("resolution_error", "重试失败，仍需人工处理")
                        else:
                            next_metadata["resolution_task_state"] = "stale_processing_recovered"
                            next_metadata["resolution_recovered_at"] = datetime.now().isoformat()
                        conflict.new_metadata = next_metadata
                        db.commit()
            except Exception as exc:
                logger.error(
                    "恢复问题作品状态失败 conflict_id=%s task_id=%s error=%s",
                    getattr(conflict, "id", None),
                    getattr(conflict, "task_id", None),
                    exc,
                    exc_info=True,
                )
                db.rollback()
                conflict.new_metadata = _normalize_conflict_metadata(getattr(conflict, "new_metadata", None))

            try:
                actions = resolution_service.get_available_actions(conflict)
            except Exception as exc:
                logger.error(
                    "计算问题作品可用操作失败 conflict_id=%s error=%s",
                    getattr(conflict, "id", None),
                    exc,
                    exc_info=True,
                )
                actions = ["SKIP"]
            per_conflict_actions.append(actions)

        _t_phase1_ms = (time.monotonic() - _t_phase1_start) * 1000
        logger.debug(
            "[/api/conflicts] phase1_serial=%.0fms (status_recover + actions × %s)",
            _t_phase1_ms, len(conflicts),
        )

        # db.commit() 会让 SQLAlchemy 默认 expire ORM 字段；后面 phase2 会 await
        # 远程 stat / 本地 IO，并且会主动 close session。这里先拍成普通对象，避免
        # close 后再访问 conflict.new_metadata / new_path 触发 DetachedInstanceError。
        conflict_snapshots = [
            SimpleNamespace(
                id=str(conflict.id or ""),
                task_id=str(conflict.task_id or ""),
                rjcode=str(conflict.rjcode or ""),
                conflict_type=str(conflict.conflict_type or ""),
                existing_path=str(conflict.existing_path or ""),
                new_path=str(conflict.new_path or ""),
                new_metadata=_normalize_conflict_metadata(conflict.new_metadata),
                status=str(conflict.status or ""),
                created_at=conflict.created_at,
            )
            for conflict in conflicts
        ]

        # ★ 性能修复：phase1 已经把需要持久化的状态恢复（PROCESSING -> PENDING）commit
        # 完毕；phase2 的 describe_conflict_async 会调用远程 stat / IO，期间不需要 db。
        # 把 conflict expunge 后立即 close，避免 connection pool 槽位被 phase2 长 IO 占用。
        for _c in conflicts:
            try:
                db.expunge(_c)
            except Exception:
                # 极端情况下 expunge 失败也不致命，detached / transient 都能继续走
                logger.debug("expunge conflict %s 失败，忽略", getattr(_c, "id", None), exc_info=True)
        try:
            db.close()
        except Exception:
            logger.debug("phase1 后关闭 db session 失败", exc_info=True)
        db = None  # 顶层 except 不再使用

        # ---- 第二阶段：并行计算 conflict 上下文（远程 stat 是 IO 密集，并发能显著降低串行延迟） ----
        # 用信号量限制群晖并发，避免对 NAS 造成压力或触发限流。
        _t_phase2_start = time.monotonic()
        gather_semaphore = asyncio.Semaphore(8)

        async def _build_context(conflict_obj):
            async with gather_semaphore:
                try:
                    return await resolution_service.describe_conflict_async(
                        conflict_obj, include_stats=include_stats,
                    )
                except Exception as exc:
                    logger.error(
                        "构建问题作品上下文失败 conflict_id=%s error=%s",
                        getattr(conflict_obj, "id", None),
                        exc,
                        exc_info=True,
                    )
                    return {
                        "existing": {
                            "library_id": None,
                            "library_type": "local",
                            "library_name": "",
                            "path": str(conflict_obj.existing_path or "").strip(),
                            "is_remote": False,
                            "stats": None,
                        },
                        "source": {
                            "library_id": None,
                            "library_type": "local",
                            "library_name": "",
                            "path": str(conflict_obj.new_path or "").strip(),
                            "is_remote": False,
                            "stats": None,
                        },
                        "new_path_kind": "archive" if os.path.isfile(str(conflict_obj.new_path or "")) else "folder",
                        "metadata": _normalize_conflict_metadata(conflict_obj.new_metadata),
                        "context_error": str(exc),
                    }

        contexts = await asyncio.gather(*(_build_context(c) for c in conflict_snapshots)) if conflict_snapshots else []
        _t_phase2_ms = (time.monotonic() - _t_phase2_start) * 1000
        logger.debug(
            "[/api/conflicts] phase2_parallel_context=%.0fms (× %s)",
            _t_phase2_ms, len(conflict_snapshots),
        )

        # ---- 第三阶段：装配响应 ----
        conflict_items = []
        for index, conflict in enumerate(conflict_snapshots):
            available_actions = per_conflict_actions[index]
            context = contexts[index]

            linked_task_info = None
            linked_task_id = str(
                (_normalize_conflict_metadata(conflict.new_metadata).get("resolution_task_id") or conflict.task_id or "")
            ).strip()
            if linked_task_id:
                linked_task = engine.get_task(linked_task_id)
                if linked_task is not None:
                    linked_task_info = {
                        "id": linked_task.id,
                        "status": linked_task.status.value if isinstance(linked_task.status, TaskStatus) else str(linked_task.status or ""),
                        "progress": int(getattr(linked_task, "progress", 0) or 0),
                        "current_step": str(getattr(linked_task, "current_step", "") or ""),
                        "error_message": str(getattr(linked_task, "error_message", "") or ""),
                    }

            conflict_items.append(
                {
                    "id": conflict.id,
                    "task_id": conflict.task_id,
                    "rjcode": conflict.rjcode,
                    "conflict_type": conflict.conflict_type,
                    "existing_path": conflict.existing_path,
                    "new_path": conflict.new_path,
                    "new_metadata": _normalize_conflict_metadata(conflict.new_metadata),
                    "status": conflict.status,
                    "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
                    "available_actions": available_actions,
                    "linked_task": linked_task_info,
                    "context": context,
                }
            )
        _t_total_ms = (time.monotonic() - _route_t_start) * 1000
        _conflict_log = logger.info if include_stats or _t_total_ms >= (_SLOW_API_LOG_THRESHOLD_SECONDS * 1000) else logger.debug
        _conflict_log(
            "[/api/conflicts] 完成 total=%.0fms include_stats=%s items=%s db_query=%.0fms phase1_serial=%.0fms phase2_parallel_context=%.0fms",
            _t_total_ms,
            include_stats,
            len(conflict_items),
            _t_query_ms,
            _t_phase1_ms,
            _t_phase2_ms,
        )
        return {
            "conflicts": conflict_items
        }
    except Exception as exc:
        logger.error("获取问题作品列表失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取问题作品失败: {str(exc)}")
    finally:
        # phase1 后已经 close + db=None，但 phase1 抛异常时 db 仍是活的；这里兜底
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.debug("/api/conflicts finally 关闭 db 失败", exc_info=True)

@app.get("/api/conflicts/count")
def get_conflicts_count(db: Session = Depends(get_db)):
    """获取问题作品数量（轻量接口，供首页轮询使用）。"""
    from ..models.database import ConflictWork

    try:
        total = (
            db.query(func.count(ConflictWork.id))
            .filter(
                ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
            )
            .scalar()
        )
        return {"count": int(total or 0)}
    except Exception as exc:
        logger.error("获取问题作品数量失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取问题作品数量失败: {exc}")

@app.post("/api/conflicts/{conflict_id}/filename-preview")
async def preview_conflict_archive_filenames(conflict_id: str, payload: Optional[ConflictFilenamePreviewRequest] = None):
    """按指定文件名编码预览压缩包目录，用于乱码失败重试前确认。"""
    from ..models.database import ConflictWork, get_db
    from ..core.extract_service import ExtractService

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")
        if conflict.conflict_type not in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            raise HTTPException(status_code=400, detail="只有失败问题项支持文件名预览")
        source_path = str(conflict.new_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="待预览的源文件不存在")
        request_payload = payload or ConflictFilenamePreviewRequest()
        service = ExtractService()
        specified_password = normalize_password_value(request_payload.password)

        password_attempts: list[tuple[str, str]] = []

        def add_password_attempt(password: Optional[str], source: str):
            normalized_password = normalize_password_value(password)
            if any(item[0] == normalized_password for item in password_attempts):
                return
            password_attempts.append((normalized_password, source))

        if specified_password:
            add_password_attempt(specified_password, "指定密码")
        else:
            with contextlib.suppress(Exception):
                for item in await service._get_password_candidates_for_archive(source_path):
                    add_password_attempt(item.get("password"), item.get("source") or "密码库")
            with contextlib.suppress(Exception):
                for password in service._get_rj_passwords(source_path):
                    add_password_attempt(password, "RJ号")
            add_password_attempt(conflict.rjcode, "RJ号")
            add_password_attempt("", "无密码")

        last_error: Optional[Exception] = None
        preview = None
        for password, password_source in password_attempts:
            try:
                preview = await service.preview_archive_filenames_with_encoding(
                    source_path,
                    filename_encoding=request_payload.filename_encoding,
                    password=password,
                    limit=request_payload.limit,
                )
                preview["password_source"] = password_source
                break
            except Exception as exc:
                last_error = exc
                continue
        if preview is None:
            raise last_error or RuntimeError("无法读取压缩包目录")
        from ..core.json_safety import safe_json_value
        return {"success": True, "preview": safe_json_value(preview)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("预览压缩包文件名失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"预览文件名失败: {exc}")
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/retry")
async def retry_extract_failed_conflict(conflict_id: str, payload: Optional[ConflictRetryRequest] = None):
    """重试问题作品中的失败项。"""
    from ..models.database import ConflictWork, get_db
    from ..core.task_engine import TaskStatus

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")
        if conflict.status != "PENDING":
            raise HTTPException(status_code=400, detail="当前问题项已不是待处理状态")
        if conflict.conflict_type not in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            raise HTTPException(status_code=400, detail="只有失败问题项支持重试")

        conflict_metadata = dict(conflict.new_metadata or {})
        failed_task_id = str(conflict.task_id or "").strip()
        failure_stage = str(conflict_metadata.get("failure_stage") or "").strip().lower()
        is_rename_retry = failure_stage == "rename"
        source_path = str(
            conflict_metadata.get("rename_retry_source_path")
            or conflict_metadata.get("retry_source_path")
            or conflict.new_path
            or ""
        ).strip()
        if not source_path:
            raise HTTPException(status_code=400, detail="缺少待重试的源路径")
        if not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="待重试的源文件不存在")

        # 把 payload.password (旧单字段) + payload.passwords (新 list) 合并成有序去重 list。
        # 前端老版本只传 password；新版可以同时传 passwords 让后端依次试。
        specified_passwords: List[str] = []
        _seen_passwords: set[str] = set()
        if payload:
            for raw in (payload.passwords or []):
                normalized = normalize_password_value(raw)
                if normalized and normalized not in _seen_passwords:
                    _seen_passwords.add(normalized)
                    specified_passwords.append(normalized)
            legacy_single = normalize_password_value(payload.password)
            if legacy_single and legacy_single not in _seen_passwords:
                _seen_passwords.add(legacy_single)
                specified_passwords.append(legacy_single)
        specified_filename_encoding = str((payload.filename_encoding if payload else None) or "").strip()
        ignore_garbled = bool(payload.ignore_garbled) if payload else False

        engine = get_task_engine()
        normalized_source_path = os.path.normcase(os.path.normpath(source_path))
        existing_task = next(
            (
                task for task in engine.get_all_tasks()
                if os.path.normcase(os.path.normpath(str(task.source_path or ""))) == normalized_source_path
                and task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}
            ),
            None,
        )
        if existing_task:
            existing_metadata = existing_task.task_metadata or {}
            # 同源任务密码一致性检查：优先比较 list，没有 list 时回退到旧单字段
            existing_manual_passwords = [
                p for p in (
                    [normalize_password_value(item) for item in (existing_metadata.get("manual_retry_passwords") or [])]
                ) if p
            ]
            if not existing_manual_passwords:
                legacy_existing = normalize_password_value(existing_metadata.get("manual_retry_password"))
                if legacy_existing:
                    existing_manual_passwords = [legacy_existing]
            if specified_passwords and existing_manual_passwords != specified_passwords:
                if existing_task.status == TaskStatus.PROCESSING:
                    raise HTTPException(
                        status_code=409,
                        detail="同源任务已经开始解压，不能把指定密码热替换到正在运行的 7z 进程；请取消或等待本次失败后再重试",
                    )
                if existing_task.status != TaskStatus.PENDING:
                    raise HTTPException(
                        status_code=409,
                        detail="同源任务已存在但不是可注入密码的等待态，请等待当前任务结束后再用指定密码重试",
                    )
            conflict.status = "PROCESSING"
            conflict.task_id = existing_task.id
            next_metadata = dict(conflict.new_metadata or {})
            next_metadata["resolution_task_state"] = "running"
            next_metadata["resolution_action"] = "RETRY"
            next_metadata["resolution_requested_at"] = datetime.now().isoformat()
            next_metadata["resolution_task_id"] = existing_task.id
            conflict.new_metadata = next_metadata
            existing_task.task_metadata["retry_conflict_id"] = conflict.id
            existing_task.task_metadata["retry_conflict_source_path"] = source_path
            existing_task.task_metadata["retry_conflict_type"] = conflict.conflict_type
            existing_task.task_metadata["retry_from_conflicts"] = True
            existing_task.task_metadata["conflict_resolution_conflict_id"] = conflict.id
            existing_task.task_metadata["conflict_resolution_action"] = "RETRY"
            if conflict.conflict_type == "EXTRACT_FAILED":
                existing_task.task_metadata["skip_retry_precheck"] = True
            if specified_passwords:
                # 落 list（新消费路径）+ 单字段（老消费路径兜底）
                existing_task.task_metadata["manual_retry_passwords"] = list(specified_passwords)
                existing_task.task_metadata["manual_retry_password"] = specified_passwords[0]
                existing_task.task_metadata["manual_retry_password_only"] = True
                existing_task.task_metadata["manual_retry_password_requested"] = True
            if specified_filename_encoding:
                existing_task.task_metadata["manual_retry_filename_encoding"] = specified_filename_encoding
            if ignore_garbled:
                existing_task.task_metadata["manual_retry_ignore_garbled"] = True
            if failed_task_id:
                existing_task.task_metadata["retry_failed_task_id"] = failed_task_id
            db.commit()
            return {
                "success": True,
                "message": "已存在同源重试任务，继续跟踪当前任务",
                "task_id": existing_task.id,
                "already_running": True,
            }

        source_task_type = str(conflict_metadata.get("source_task_type") or TaskType.AUTO_PROCESS.value).strip()
        retry_task_type = TaskType(source_task_type) if source_task_type in {task_type.value for task_type in TaskType} else TaskType.AUTO_PROCESS
        if is_rename_retry:
            retry_task_type = TaskType.PROCESS_EXISTING_FOLDER

        if failed_task_id and not is_rename_retry:
            engine.cleanup_retry_output_artifacts(failed_task_id, source_path)

        retry_metadata = dict(conflict_metadata) if is_rename_retry else {}
        for key in (
            "failure_stage",
            "error_message",
            "failed_step",
            "failed_progress",
            "resolution_error",
            "resolution_task_state",
            "resolution_task_id",
        ):
            retry_metadata.pop(key, None)
        if is_rename_retry:
            retry_metadata.update({
                "resume_from_stage": "rename",
                "skip_duplicate_precheck": True,
            })

        task = Task(
            task_type=retry_task_type,
            source_path=source_path,
            auto_classify=True,
            metadata=retry_metadata,
        )
        task.task_metadata["retry_conflict_id"] = conflict.id
        task.task_metadata["retry_conflict_source_path"] = source_path
        task.task_metadata["retry_conflict_type"] = conflict.conflict_type
        task.task_metadata["retry_from_conflicts"] = True
        if conflict.conflict_type == "EXTRACT_FAILED":
            task.task_metadata["skip_retry_precheck"] = True
        task.task_metadata["conflict_resolution_conflict_id"] = conflict.id
        task.task_metadata["conflict_resolution_action"] = "RETRY"
        if specified_passwords:
            task.task_metadata["manual_retry_passwords"] = list(specified_passwords)
            task.task_metadata["manual_retry_password"] = specified_passwords[0]
            task.task_metadata["manual_retry_password_only"] = True
            task.task_metadata["manual_retry_password_requested"] = True
        if specified_filename_encoding:
            task.task_metadata["manual_retry_filename_encoding"] = specified_filename_encoding
        if ignore_garbled:
            task.task_metadata["manual_retry_ignore_garbled"] = True
        if failed_task_id:
            task.task_metadata["retry_failed_task_id"] = failed_task_id
        if conflict.rjcode:
            task.task_metadata["inferred_rjcode"] = conflict.rjcode

        # 问题作品重试会创建新的引擎任务，但旧的 waiting_manual 任务仍然保留。
        # 标记旧任务已被本次重试替代，任务中心据此隐藏旧行；状态保持原样，审计仍可追溯。
        if failed_task_id:
            failed_task = engine.get_task(failed_task_id)
            if failed_task and failed_task.id != task.id:
                failed_metadata = dict(failed_task.task_metadata or {})
                failed_metadata["superseded_by_task_id"] = task.id
                failed_metadata["superseded_at"] = datetime.now().isoformat()
                failed_metadata["superseded_reason"] = "retry_replaced"
                failed_metadata["hidden_in_task_lists"] = True
                failed_task.task_metadata = failed_metadata
                failed_task.touch_metadata("retry_superseded")
                with contextlib.suppress(Exception):
                    from ..core.task_center_materialization_service import get_task_center_materialization_service

                    get_task_center_materialization_service().delete_engine_item(failed_task.id)

        conflict.status = "PROCESSING"
        next_metadata = dict(conflict.new_metadata or {})
        next_metadata["resolution_task_state"] = "queued"
        next_metadata["resolution_action"] = "RETRY"
        next_metadata["resolution_requested_at"] = datetime.now().isoformat()
        conflict.new_metadata = next_metadata
        await engine.submit(task)
        conflict.task_id = task.id
        conflict.new_metadata = {
            **dict(conflict.new_metadata or {}),
            "resolution_task_id": task.id,
        }
        db.commit()
        if specified_passwords:
            if len(specified_passwords) > 1:
                message = f"已开始使用 {len(specified_passwords)} 个指定密码依次重试失败问题项"
            else:
                message = "已开始使用指定密码重试失败问题项"
        else:
            message = "已开始重试失败问题项"
        return {
            "success": True,
            "message": message,
            "task_id": task.id,
            "already_running": False,
        }
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/rename-volumes")
async def rename_disguised_volume_conflict(
    conflict_id: str,
    payload: ConflictRenameVolumesRequest,
):
    """对伪装多卷 conflict 执行用户确认后的逐卷重命名，可选自动起重试任务。

    流程：
    1. 校验 conflict 状态 + 类型（必须是 PENDING + 分卷压缩包后缀无法识别）。
    2. 让 ConflictResolutionService 做"全套校验 + 两阶段原子重命名"。
    3. 把 conflict.new_path 切到首卷新路径、清掉 ``disguised_volume_set`` payload。
    4. ``auto_retry=True`` 时立刻起一个 RETRY 任务（复用 ``/retry`` 路径的元数据约定）。
    """
    from ..core.activity_log_service import log_conflict_resolution_activity
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..models.database import ConflictWork, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")
        if conflict.status != "PENDING":
            raise HTTPException(status_code=400, detail="当前问题项已不是待处理状态")
        if str(conflict.conflict_type or "").upper() != "分卷压缩包后缀无法识别":
            raise HTTPException(status_code=400, detail="只有伪装多卷问题项支持重命名")

        service = get_conflict_resolution_service()
        renames_payload = [{"old": item.old, "new": item.new} for item in payload.renames]
        try:
            result = await service.rename_disguised_volumes(conflict, renames_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        # 写一条活动日志
        try:
            log_conflict_resolution_activity(
                conflict_id=str(conflict.id),
                action="RENAME_VOLUMES",
                status="success",
                rjcode=conflict.rjcode,
                task_id=conflict.task_id,
                source_path=str(result.get("first_volume") or ""),
                final_path=str(result.get("first_volume") or ""),
                extra_detail={
                    "renamed_count": len(result.get("renamed") or []),
                    "directory": result.get("directory"),
                },
            )
        except Exception:
            logger.warning("写入伪装多卷重命名操作记录失败: conflict_id=%s", conflict.id, exc_info=True)

        db.commit()

        retry_task_id: Optional[str] = None
        if payload.auto_retry:
            # 重命名后立即起一个 RETRY 任务，逻辑跟 /retry 一致：把 conflict 切到 PROCESSING、
            # 复用元数据约定（retry_conflict_id / retry_from_conflicts / skip_retry_precheck），
            # 让 task_engine 的 _is_retry_from_conflicts_task / _resolve_retry_extract_conflict
            # 链路能识别这是问题作品页发起的重试。
            source_path = str(conflict.new_path or "").strip()
            if not source_path or not os.path.exists(source_path):
                # 重命名都做完了，首卷却又消失：极端边界，不阻断 rename，转 SKIP-only 状态
                logger.warning(
                    "[RenameVolumes] 重命名后首卷路径不存在，跳过自动重试: conflict_id=%s path=%s",
                    conflict.id,
                    source_path,
                )
            else:
                engine = get_task_engine()
                source_task_type_raw = str(
                    (conflict.new_metadata or {}).get("source_task_type")
                    or TaskType.AUTO_PROCESS.value
                ).strip()
                retry_task_type = (
                    TaskType(source_task_type_raw)
                    if source_task_type_raw in {t.value for t in TaskType}
                    else TaskType.AUTO_PROCESS
                )
                if conflict.task_id:
                    engine.cleanup_retry_output_artifacts(str(conflict.task_id), source_path)

                retry_task = Task(
                    task_type=retry_task_type,
                    source_path=source_path,
                    auto_classify=True,
                )
                retry_task.task_metadata["retry_conflict_id"] = conflict.id
                retry_task.task_metadata["retry_conflict_source_path"] = source_path
                retry_task.task_metadata["retry_conflict_type"] = conflict.conflict_type
                retry_task.task_metadata["retry_from_conflicts"] = True
                retry_task.task_metadata["skip_retry_precheck"] = True
                retry_task.task_metadata["conflict_resolution_conflict_id"] = conflict.id
                retry_task.task_metadata["conflict_resolution_action"] = "RENAME_VOLUMES"
                if conflict.task_id:
                    retry_task.task_metadata["retry_failed_task_id"] = str(conflict.task_id)
                if conflict.rjcode:
                    retry_task.task_metadata["inferred_rjcode"] = conflict.rjcode

                conflict.status = "PROCESSING"
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["resolution_task_state"] = "queued"
                next_metadata["resolution_action"] = "RENAME_VOLUMES"
                next_metadata["resolution_requested_at"] = datetime.now().isoformat()
                conflict.new_metadata = next_metadata
                await engine.submit(retry_task)
                conflict.task_id = retry_task.id
                conflict.new_metadata = {
                    **dict(conflict.new_metadata or {}),
                    "resolution_task_id": retry_task.id,
                }
                db.commit()
                retry_task_id = retry_task.id

        return {
            "success": True,
            "conflict_id": conflict.id,
            "renamed": result.get("renamed") or [],
            "first_volume": result.get("first_volume"),
            "directory": result.get("directory"),
            "task_id": retry_task_id,
            "auto_retry": payload.auto_retry,
            "message": (
                f"已重命名 {len(result.get('renamed') or [])} 个分卷"
                + ("，并已开始重试解压" if retry_task_id else "")
            ),
        }
    finally:
        db.close()


@app.post("/api/conflicts/{conflict_id}/preview")
async def preview_conflict_resolution(conflict_id: str, payload: dict):
    """生成问题作品处理预览"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..models.database import ConflictWork, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action = service.normalize_action(payload.get("action"))
        if action not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")

        if action == "KEEP_NEW":
            preview = await service.get_delete_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                "preview": preview,
            }

        if action == "MERGE":
            # 合并预览改成异步 job 模式：HTTP 立即返回 job_id，前端轮询
            # /api/conflicts/{id}/preview-job/{job_id} 拿真实阶段。
            # 避免大压缩包 + 嵌套包必 504 网关超时。
            job_status = await service.start_merge_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                "async": True,
                **job_status,
            }

        raise HTTPException(status_code=400, detail="当前动作不需要预览")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("生成问题作品预览失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成处理预览失败: {exc}")
    finally:
        db.close()


@app.get("/api/conflicts/{conflict_id}/preview-job/{job_id}")
async def get_conflict_preview_job(conflict_id: str, job_id: str):
    """合并预览异步 job 状态查询：前端轮询拉真实阶段 / 百分比 / message / result。

    返回字段（来自 ConflictResolutionService._serialize_merge_preview_job）：
      - status: running | completed | failed
      - stage / stage_label / message / percent：实时进度
      - result: status=completed 时携带完整 preview 数据（含 session_id / items / 默认 decisions）
      - error: status=failed 时的错误描述（FileNotFoundError 已中文化）
    """
    from ..core.conflict_resolution_service import get_conflict_resolution_service

    service = get_conflict_resolution_service()
    job = service.get_merge_preview_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="合并预览任务不存在或已过期")
    if str(job.get("conflict_id") or "") != str(conflict_id or ""):
        # 防御：job_id 和 conflict_id 不匹配（前端串了 / 旧 job 漂移）
        raise HTTPException(status_code=400, detail="任务 ID 与问题作品不匹配")
    return job

def _collect_split_archive_siblings(main_path: str):
    """收集与主文件同目录的所有分卷兄弟文件（含主文件自身）。

    支持以下格式：
    - X.zip.001 / X.zip.002 / ...（标准 7-zip 多卷 / zip 多卷带扩展）
    - X.zip + X.002 / X.003 / ...（zip_numeric_split 回滚后形态）
    - X.7z.001 / X.7z.002 / ...
    - X.part1.rar / X.part2.rar / ...（含 .exe/.rar 混用）
    - X.rar + X.r00 / X.r01 / ...（旧式 RAR 多卷）
    返回：存在于磁盘的相关文件列表（不保证顺序）。若无分卷，返回 [main_path]。
    """
    import re as _re
    if not os.path.isfile(main_path):
        return [main_path] if os.path.exists(main_path) else []

    parent_dir = os.path.dirname(main_path)
    filename = os.path.basename(main_path)

    patterns = []

    # X.zip.NNN / X.7z.NNN / X.tar.NNN / X.rar.NNN 等
    m = _re.match(r'^(.+\.[a-zA-Z][a-zA-Z0-9]{0,3})\.\d{3}$', filename, _re.IGNORECASE)
    if m:
        base_stem = _re.escape(m.group(1))
        patterns.append(_re.compile(rf'^{base_stem}\.\d+$', _re.IGNORECASE))

    # X.partN.rar / X.partN.exe（WinRAR 自解压多卷）
    m = _re.match(r'^(.+)\.part\d+\.(rar|exe)$', filename, _re.IGNORECASE)
    if m:
        base_stem = _re.escape(m.group(1))
        patterns.append(_re.compile(rf'^{base_stem}\.part\d+\.(rar|exe)$', _re.IGNORECASE))

    # X.zip + X.002, X.003, ... (zip_numeric_split 回滚后：主卷 .zip，其余 .NNN)
    m = _re.match(r'^(.+)\.zip$', filename, _re.IGNORECASE)
    if m:
        base_stem = _re.escape(m.group(1))
        patterns.append(_re.compile(rf'^{base_stem}\.\d+$', _re.IGNORECASE))

    # X.rar + X.r00, X.r01, ... (旧式 RAR 多卷)
    m = _re.match(r'^(.+)\.rar$', filename, _re.IGNORECASE)
    if m:
        base_stem = _re.escape(m.group(1))
        patterns.append(_re.compile(rf'^{base_stem}\.r\d+$', _re.IGNORECASE))

    if not patterns:
        return [main_path]

    siblings = set()
    siblings.add(main_path)
    try:
        for entry in os.scandir(parent_dir):
            if entry.is_file() and entry.path != main_path:
                for pat in patterns:
                    if pat.match(entry.name):
                        siblings.add(entry.path)
                        break
    except Exception:
        pass
    return list(siblings)


@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, action: dict):
    """处理问题作品"""
    from ..core.activity_log_service import (
        build_file_tree_diff_items,
        log_conflict_resolution_activity,
        mark_task_conflict_resolved_activity_log,
        snapshot_file_tree_for_activity,
    )
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..core.task_engine import Task, TaskStatus, TaskType, get_task_engine
    from ..models.database import ConflictWork, ProcessedArchive, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action_type = service.normalize_action(action.get("action"))
        if action_type not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")
        confirmed = bool(action.get("confirmed"))
        skip_activity_snapshot = bool(action.get("skip_activity_snapshot"))
        engine = get_task_engine()
        # KEEP_NEW 分支会用新任务 ID 覆盖 conflict.task_id，必须在覆盖前
        # 记下原任务 ID 才能定位到那条 task_finished/waiting 的活动日志。
        original_task_id = str(conflict.task_id).strip() if conflict.task_id else None
        resolution_diff_items = []

        try:
            if action_type == "KEEP_NEW":
                if not confirmed:
                    raise HTTPException(status_code=400, detail="保留新版前必须先完成删除审查确认")
                source_path = str(conflict.new_path or "").strip()
                existing_path = str(conflict.existing_path or "").strip()
                if not source_path:
                    raise HTTPException(status_code=400, detail="缺少待处理源路径")
                if not existing_path:
                    raise HTTPException(status_code=400, detail="缺少待替换目标路径")
                if not os.path.exists(source_path):
                    raise HTTPException(status_code=404, detail="待处理源文件不存在")

                existing_task = None
                if conflict.task_id:
                    existing_task = engine.get_task(str(conflict.task_id))
                if existing_task and existing_task.status == TaskStatus.PROCESSING:
                    # 任务还在跑也代表用户已经拍板"保留新版"——把原 waiting
                    # 那条活动日志同步回写，避免操作记录上一直挂着"等待处理"。
                    # 内部走独立 SQLAlchemy session + commit，是同步阻塞调用，
                    # 批量 KEEP_NEW 时会卡事件循环，统一下沉到线程池。
                    await asyncio.to_thread(
                        mark_task_conflict_resolved_activity_log,
                        original_task_id,
                        action_type,
                        conflict_id=conflict.id,
                    )
                    return {
                        "success": True,
                        "conflict_id": conflict.id,
                        "action": action_type,
                        "task_id": existing_task.id,
                        "already_running": True,
                        "message": "保留新版任务已在执行中",
                    }

                conflict.status = "PROCESSING"
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["resolution_task_state"] = "queued"
                next_metadata["resolution_action"] = action_type
                next_metadata["resolution_requested_at"] = datetime.now().isoformat()
                # KEEP_NEW 这里必须保持轻量：真实解压 / 替换目录会进任务队列执行。
                # 旧逻辑在 HTTP 请求里同步生成旧目录文件树快照，大目录或 NAS 上批量执行
                # 会把请求和其它接口一起拖慢。快照改由任务真正替换前在后台线程里采集。
                next_metadata["resolution_before_tree_items"] = []
                if skip_activity_snapshot:
                    next_metadata["resolution_activity_snapshot_skipped"] = True
                    next_metadata["resolution_before_tree_deferred"] = False
                else:
                    next_metadata["resolution_before_tree_deferred"] = True
                conflict.new_metadata = next_metadata

                duplicate_conflicts = []
                if source_path:
                    duplicate_conflicts.extend(
                        db.query(ConflictWork).filter(
                            ConflictWork.id != conflict.id,
                            ConflictWork.status == "PENDING",
                            ConflictWork.new_path == source_path,
                        ).all()
                    )
                if conflict.rjcode and conflict.conflict_type and existing_path:
                    duplicate_conflicts.extend(
                        db.query(ConflictWork).filter(
                            ConflictWork.id != conflict.id,
                            ConflictWork.status == "PENDING",
                            ConflictWork.rjcode == conflict.rjcode,
                            ConflictWork.conflict_type == conflict.conflict_type,
                            ConflictWork.existing_path == existing_path,
                        ).all()
                    )
                seen_duplicate_ids = set()
                for duplicate in duplicate_conflicts:
                    if duplicate.id in seen_duplicate_ids:
                        continue
                    seen_duplicate_ids.add(duplicate.id)
                    logger.info(
                        "保留新版任务合并重复问题项: current=%s duplicate=%s rj=%s",
                        conflict.id,
                        duplicate.id,
                        conflict.rjcode,
                    )
                    db.delete(duplicate)

                source_is_file = await asyncio.to_thread(os.path.isfile, source_path)
                task_type = TaskType.AUTO_PROCESS if source_is_file else TaskType.PROCESS_EXISTING_FOLDER
                task = Task(
                    task_type=task_type,
                    source_path=source_path,
                    auto_classify=True,
                    metadata={
                        **next_metadata,
                        "existing_folder_resolution": "KEEP_NEW",
                        "existing_path": existing_path,
                        "conflict_resolution_conflict_id": conflict.id,
                        "conflict_resolution_action": "KEEP_NEW",
                        "source_page": "conflicts",
                        "source_action": "keep_new",
                        "source_label": conflict.rjcode or os.path.basename(source_path),
                        "business_key": conflict.rjcode or conflict.id,
                        "target_library_id": next_metadata.get("existing_library_id") or next_metadata.get("target_library_id") or "",
                    },
                    rjcode=conflict.rjcode or None,
                )
                if conflict.task_id:
                    task.task_metadata["parent_conflict_task_id"] = str(conflict.task_id)
                await engine.submit(task)
                conflict.task_id = task.id
                conflict.new_metadata = {
                    **dict(conflict.new_metadata or {}),
                    "resolution_task_id": task.id,
                    "resolution_task_state": "queued",
                }
                db.commit()
                # 提交完新任务后，再把原 waiting 那条活动日志改写为"已保留新版"，
                # 避免操作记录里关联事件长期停留在"等待处理"。
                # 同步函数 + 内部 commit，下沉到线程池避免阻塞事件循环。
                await asyncio.to_thread(
                    mark_task_conflict_resolved_activity_log,
                    original_task_id,
                    action_type,
                    conflict_id=conflict.id,
                )
                await asyncio.to_thread(
                    log_conflict_resolution_activity,
                    conflict_id=conflict.id,
                    action=action_type,
                    status="waiting",
                    rjcode=conflict.rjcode,
                    task_id=task.id,
                    source_path=source_path,
                    target_path=existing_path,
                    before_tree_items=next_metadata.get("resolution_before_tree_items") or [],
                    after_tree_items=[],
                )
                return {
                    "success": True,
                    "conflict_id": conflict.id,
                    "action": action_type,
                    "task_id": task.id,
                    "already_running": False,
                    "message": "已提交保留新版后台任务，任务状态已切换为解压中",
                }
            elif action_type == "MERGE":
                previous_conflict_status = str(conflict.status or "PENDING").strip() or "PENDING"
                previous_task_status = None
                previous_task_step = None
                conflict_task = None
                if conflict.task_id:
                    conflict_task = engine.get_task(str(conflict.task_id))
                    if conflict_task:
                        previous_task_status = conflict_task.status
                        previous_task_step = conflict_task.current_step
                conflict.status = "PROCESSING"
                if conflict_task:
                    conflict_task.status = TaskStatus.PROCESSING
                    conflict_task.started_at = conflict_task.started_at or datetime.now()
                    conflict_task.update_progress(max(int(conflict_task.progress or 0), 10), "合并中")
                db.commit()
                merge_session_id = str(action.get("merge_session_id") or "").strip()
                merge_session = getattr(service, "_merge_sessions", {}).get(merge_session_id)
                merge_decisions = action.get("merge_decisions") or {}
                if merge_session and getattr(merge_session, "compare_items", None):
                    predicted = []
                    for item in list(merge_session.compare_items or []):
                        relative_path = str(item.get("relative_path") or "").strip()
                        if not relative_path:
                            continue
                        status = str(item.get("status") or "").strip()
                        item_type = str(item.get("type") or "file").strip() or "file"
                        decision = str(merge_decisions.get(relative_path) or "").strip().lower()
                        variant = ""
                        if status == "new_only":
                            variant = "added"
                        elif status == "old_only" and decision == "delete":
                            variant = "deleted"
                        elif status == "modified" and decision in {"", "use_new"}:
                            variant = "changed"
                        if not variant:
                            continue
                        predicted.append({
                            "relative_path": relative_path,
                            "name": os.path.basename(relative_path) or relative_path,
                            "type": item_type,
                            "size": item.get("new_size") or item.get("old_size") or 0,
                            "variant": variant,
                        })
                    resolution_diff_items = predicted
                result = await service.resolve_merge(
                    conflict,
                    action.get("merge_session_id"),
                    action.get("merge_decisions") or {},
                )
                conflict.status = action_type
                if conflict_task:
                    conflict_task.update_progress(100, "合并完成")
                    conflict_task.complete()
            else:
                source_for_skip = str(conflict.new_path or "").strip()
                # 与 KEEP_NEW 同因：批量 SKIP 走同步 os.walk 会卡死事件循环，
                # 必须把目录探测和文件树快照都丢到线程池里。
                if source_for_skip:
                    try:
                        skip_is_dir = await asyncio.to_thread(os.path.isdir, source_for_skip)
                    except Exception:
                        skip_is_dir = False
                    if skip_is_dir:
                        skip_tree_items = await asyncio.to_thread(
                            snapshot_file_tree_for_activity, source_for_skip, 300,
                        )
                    else:
                        skip_tree_items = []
                else:
                    skip_tree_items = []
                resolution_diff_items = [
                    {**item, "variant": "deleted"}
                    for item in skip_tree_items
                ]
                result = await service.resolve_skip(conflict)
                conflict.status = action_type
                if conflict.task_id:
                    engine.update_task_status(str(conflict.task_id), TaskStatus.COMPLETED, "跳过完成")
        except Exception:
            if action_type == "MERGE":
                conflict.status = previous_conflict_status
                if conflict_task and previous_task_status:
                    conflict_task.status = previous_task_status
                    if previous_task_step:
                        conflict_task.current_step = previous_task_step
            db.commit()
            raise

        archive_record = None
        if conflict.new_path:
            archive_record = db.query(ProcessedArchive).filter(
                ProcessedArchive.filename == os.path.basename(str(conflict.new_path))
            ).first()
            if archive_record:
                archive_record.status = "completed"
                archive_record.processed_at = datetime.now()

        db.commit()
        if archive_record:
            _broadcast_processed_archive_changed_safe(archive_record)
        # MERGE / SKIP 完成后同步把原 waiting 那条 task_finished 行回写成
        # "已合并" / "已跳过"，否则操作记录的关联事件依然停留在"等待处理"。
        # 同步函数 + 内部 commit，下沉到线程池避免阻塞事件循环。
        await asyncio.to_thread(
            mark_task_conflict_resolved_activity_log,
            original_task_id,
            action_type,
            conflict_id=conflict.id,
        )
        if action_type in {"MERGE", "SKIP"}:
            await asyncio.to_thread(
                log_conflict_resolution_activity,
                conflict_id=conflict.id,
                action=action_type,
                status="success",
                rjcode=conflict.rjcode,
                task_id=conflict.task_id,
                source_path=str(conflict.new_path or ""),
                target_path=str(conflict.existing_path or ""),
                final_path=str((result or {}).get("final_path") or conflict.existing_path or ""),
                diff_items=resolution_diff_items,
            )
        return {
            "success": True,
            "conflict_id": conflict.id,
            "action": action_type,
            **result,
        }
        
        # 检查new_path是否是压缩包（预检阶段的冲突）
        from ..core.watcher import ArchiveHandler
        temp_handler = ArchiveHandler(lambda x: None, lambda: set(), lambda: False, lambda x: None)
        is_archive = temp_handler._is_archive(conflict.new_path)
        
        if action_type == "KEEP_NEW":
            if os.path.exists(conflict.existing_path):
                shutil.rmtree(conflict.existing_path)
            
            if is_archive:
                logger.info(f"保留新版：先解压压缩包 {conflict.new_path}")
                
                is_in_processed = conflict.new_path.startswith(config.storage.processed_archives_path)
                if is_in_processed:
                    logger.info(f"检测到文件已在 processed 目录中，设置 skip_archive=True: {conflict.new_path}")
                
                # 检查冲突前先确认没有正在执行同RJ编号的操作
                engine = get_task_engine()
                rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path)) 
                
                skip_archive_bool = bool(conflict.new_path.startswith(config.storage.processed_archives_path)) 
                
                # 如果正在处理同样的RJ号，优先复用正在处理的同RJ号的任务
                if rjcode_of_new_path and engine.is_rjcode_processing(rjcode_of_new_path):
                    # 查找正在处理同RJ号的任务
                    existing_tasks_for_rj = [t for t in engine.get_all_tasks() 
                                           if t.rjcode == rjcode_of_new_path and t.status == TaskStatus.PROCESSING]
                    if existing_tasks_for_rj:
                        task = existing_tasks_for_rj[0]
                        # 复用当前正在处理的同RJ号任务
                        original_source = task.source_path
                        task.source_path = str(conflict.new_path)
                        task.skip_archive = skip_archive_bool
                        # 确保任务状态为PROCESSED，以便继续执行
                        task.status = TaskStatus.PROCESSING
                        task.update_progress(10, "解压中")
                        logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                    else:
                        # 使用原有的冲突task_id逻辑
                        original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None
                        
                        if original_task:
                            # 更新原有任务的源路径，复用任务ID
                            original_source = original_task.source_path
                            original_task.source_path = str(conflict.new_path)
                            original_task.skip_archive = skip_archive_bool
                            original_task.status = TaskStatus.PROCESSING
                            original_task.update_progress(10, "解压中")
                            task = original_task
                            logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                        else:
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                else:
                    # 没有正在处理的同RJ任务时，使用原有的逻辑
                    original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None

                    if original_task:
                        # 更新原有任务的源路径，复用任务ID
                        original_source = original_task.source_path
                        original_task.source_path = str(conflict.new_path)
                        original_task.skip_archive = skip_archive_bool
                        original_task.status = TaskStatus.PROCESSING
                        original_task.update_progress(10, "解压中")
                        task = original_task
                        logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                    else:
                        # 检查是否有其他同RJ号的任务存在，如果有就复用
                        rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path))
                        if rjcode_of_new_path:
                            existing_rj_tasks = [t for t in engine.get_all_tasks() 
                                               if t.rjcode == rjcode_of_new_path]
                            if existing_rj_tasks:
                                task = existing_rj_tasks[0]
                                original_source = task.source_path
                                task.source_path = str(conflict.new_path)
                                task.skip_archive = skip_archive_bool
                                task.status = TaskStatus.PROCESSING
                                task.update_progress(10, "解压中")
                                logger.info(f"复用同RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                            else:
                                # 创建新任务
                                task = Task(
                                    task_type=TaskType.AUTO_PROCESS,
                                    source_path=str(conflict.new_path),
                                    auto_classify=True,
                                    skip_archive=skip_archive_bool
                                )
                                engine.tasks[task.id] = task
                                logger.info(f"创建新任务处理: {task.id}")
                        else:
                            # 创建新任务
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                
                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()
                
                extracted_path = await extract_service.extract(task)
                if not extracted_path:
                    error_msg = task.error_message or "解压失败"
                    logger.error(f"处理冲突失败: {error_msg}")
                    return {"success": False, "error": error_msg}
                
                metadata = await metadata_service.fetch(extracted_path, task)
                task.task_metadata = metadata
                
                task.update_progress(60, "重命名文件夹")
                from app.core.rename_service import RenameService
                rename_service = RenameService()
                renamed_path = await rename_service.rename(extracted_path, task)
                
                task.update_progress(75, "过滤文件中")
                filter_result = await filter_service.filter(renamed_path, task)
                task.task_metadata = {
                    **(task.task_metadata or {}),
                    **dict(filter_result or {}),
                }
                
                filter_path_transforms: list[dict[str, str]] = []
                if config.rename.flatten_single_subfolder:
                    renamed_path = rename_service._flatten_single_subfolder(
                        renamed_path,
                        operation_sink=filter_path_transforms,
                    )
                    logger.info(f"保留新版 - 扁平化后路径: {renamed_path}")

                if config.rename.remove_empty_folders:
                    rename_service.remove_empty_folders(renamed_path, remove_root=False)

                # 简繁转换（与 AUTO_PROCESS 流程保持一致）
                if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                    from ..core.subtitle_sync_service import get_subtitle_sync_service
                    subtitle_svc = get_subtitle_sync_service()
                    task.update_progress(80, "字幕繁简转换中")
                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                    if simplify_result['converted_files'] > 0:
                        logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                   f"转换 {simplify_result['converted_files']} 个文件")

                task.update_progress(85, "移动到库存")
                final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                task.output_path = final_path
                await get_task_engine()._finalize_filter_recovery(
                    task,
                    filter_path_transforms,
                    library_id=str((task.task_metadata or {}).get("target_library_id") or ""),
                )
                
                # 归档不再占用问题作品处理请求；统一进入可恢复的空闲归档队列。
                await get_task_engine()._archive_source_file(task)
                
                task.status = TaskStatus.COMPLETED
                task.update_progress(100, f"问题作品已处理: {action_type}")
                task.completed_at = datetime.now()
                
                logger.info(f"保留新版完成：已解压并移动到 {final_path}，压缩包已归档")
                
                # 更新 ProcessedArchive 状态为 completed
                if is_in_processed:
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        _broadcast_processed_archive_changed_safe(archive_record)
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            else:
                # 如果是已解压的文件夹，直接移动
                if os.path.exists(conflict.new_path):
                    target_path = os.path.join(config.storage.library_path, os.path.basename(conflict.new_path))
                    await asyncio.to_thread(shutil.move, conflict.new_path, target_path)
                    logger.info(f"保留新版完成：已移动到 {target_path}")
            
            conflict.status = "KEEP_NEW"
            
        elif action_type == "KEEP_OLD":
            # 删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    os.remove(conflict.new_path)  # 删除压缩包
                else:
                    shutil.rmtree(conflict.new_path)  # 删除文件夹
            # 更新 ProcessedArchive 状态为 completed（用户选择保留旧版，新版任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    _broadcast_processed_archive_changed_safe(archive_record)
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (KEEP_OLD): {filename}")
            
            conflict.status = "KEEP_OLD"
            
        elif action_type == "MERGE":
            # 合并：保留两个版本，新版本加编号
            if is_archive:
                logger.info(f"合并：先解压压缩包 {conflict.new_path}")
                task = Task(
                    task_type=TaskType.AUTO_PROCESS,
                    source_path=conflict.new_path,
                    auto_classify=True
                )
                engine._ensure_task_context(task)
                engine.tasks[task.id] = task

                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()

                extracted_path = await extract_service.extract(task)
                if extracted_path:
                    metadata = await metadata_service.fetch(extracted_path, task)

                    # 重命名
                    from app.core.rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = await rename_service.rename(extracted_path, task)

                    filter_result = await filter_service.filter(renamed_path, task)
                    task.task_metadata = {
                        **(task.task_metadata or {}),
                        **dict(filter_result or {}),
                    }

                    filter_path_transforms: list[dict[str, str]] = []
                    if config.rename.flatten_single_subfolder:
                        renamed_path = rename_service._flatten_single_subfolder(
                            renamed_path,
                            operation_sink=filter_path_transforms,
                        )

                    if config.rename.remove_empty_folders:
                        rename_service.remove_empty_folders(renamed_path, remove_root=False)

                    # 简繁转换
                    if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                        from ..core.subtitle_sync_service import get_subtitle_sync_service
                        subtitle_svc = get_subtitle_sync_service()
                        simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                        if simplify_result['converted_files'] > 0:
                            logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                       f"转换 {simplify_result['converted_files']} 个文件")

                    # 修改metadata使文件夹名加编号
                    rjcode = metadata.get('rjcode', '')
                    target_base = os.path.join(config.storage.library_path, conflict.rjcode)
                    counter = 1
                    while os.path.exists(f"{target_base}({counter})"):
                        counter += 1
                    metadata['work_name'] = f"{metadata.get('work_name', '')}({counter})"

                    final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                    task.output_path = final_path
                    await engine._finalize_filter_recovery(
                        task,
                        filter_path_transforms,
                        library_id=str((task.task_metadata or {}).get("target_library_id") or ""),
                    )
                    task.update_progress(100, "问题作品合并完成")
                    task.complete()
                    os.remove(conflict.new_path)
                    logger.info(f"合并完成：新版本已保存为 {final_path}")
                    
                    # 更新 ProcessedArchive 状态为 completed
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        _broadcast_processed_archive_changed_safe(archive_record)
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            
            conflict.status = "MERGE"
            
        elif action_type == "SKIP":
            # 跳过，删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    # 收集所有分卷兄弟文件一并删除，避免只删主卷留下残余分卷
                    siblings = _collect_split_archive_siblings(conflict.new_path)
                    for sibling in siblings:
                        try:
                            if os.path.exists(sibling):
                                os.remove(sibling)
                                logger.info(f"[SKIP] 已删除文件: {sibling}")
                        except Exception as exc:
                            logger.warning(f"[SKIP] 删除分卷文件失败: {sibling}, error={exc}")
                    # 所有分卷删完后，若父目录为空则一并清理
                    parent_dir = os.path.dirname(conflict.new_path)
                    if parent_dir and os.path.isdir(parent_dir):
                        try:
                            remaining = os.listdir(parent_dir)
                            if not remaining:
                                os.rmdir(parent_dir)
                                logger.info(f"[SKIP] 已删除空父目录: {parent_dir}")
                        except Exception as exc:
                            logger.warning(f"[SKIP] 清理空父目录失败: {parent_dir}, error={exc}")
                else:
                    shutil.rmtree(conflict.new_path)
            # 更新 ProcessedArchive 状态为 completed（用户选择跳过，任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    _broadcast_processed_archive_changed_safe(archive_record)
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (SKIP): {filename}")
            
            conflict.status = "SKIP"
        
        # 更新关联任务的状态
        if conflict.task_id:
            engine = get_task_engine()
            from ..core.task_engine import TaskStatus
            engine.update_task_status(
                conflict.task_id, 
                TaskStatus.COMPLETED,
                f"问题作品已处理: {action_type}"
            )
        
        db.commit()
        return {"message": "处理成功"}
        
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as e:
        db.rollback()
        logger.error(f"处理冲突失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

async def scan_processed_archives():
    """启动时扫描已处理压缩包目录，同步数据库"""
    import os
    import re
    from datetime import datetime
    from ..models.database import ProcessedArchive, get_db
    import uuid
    
    config = get_config()
    processed_dir = config.storage.processed_archives_path
    
    if not os.path.exists(processed_dir):
        logger.info(f"已处理压缩包目录不存在: {processed_dir}")
        return

    # 延后归档会在最终完成前短暂发布单个成员以支持崩溃恢复。扫描若把这类
    # 文件写成 ProcessedArchive，后续清理可能删除唯一已发布副本，因此队列
    # 状态不可读时直接跳过本轮扫描。
    try:
        from ..core.deferred_archive_service import get_deferred_archive_service

        active_target_paths = await asyncio.to_thread(
            get_deferred_archive_service().active_target_paths_sync
        )
    except Exception:
        logger.warning("读取延后归档目标声明失败，跳过已处理压缩包扫描", exc_info=True)
        return

    def _normalized_archive_path(path: str) -> str:
        return os.path.normcase(os.path.abspath(str(path or "")))

    def _archive_paths(archive: Any) -> set[str]:
        manifest_paths = {
            _normalized_archive_path(str((item or {}).get("target_path") or ""))
            for item in list(getattr(archive, "archive_manifest", None) or [])
            if str((item or {}).get("target_path") or "").strip()
        }
        if manifest_paths:
            return manifest_paths
        current_path = _normalized_archive_path(str(getattr(archive, "current_path", "") or ""))
        return {current_path} if current_path else set()

    def _uses_active_target(archive: Any) -> bool:
        return bool(_archive_paths(archive) & active_target_paths)
    
    logger.info(f"开始扫描已处理压缩包目录: {processed_dir}")
    
    db = next(get_db())
    try:
        # 清理重复记录（保留最新的）
        all_archives = db.query(ProcessedArchive).order_by(ProcessedArchive.processed_at.desc()).all()
        seen_filenames = {}
        duplicates = []
        for archive in all_archives:
            if archive.filename in seen_filenames:
                # 不在扫描期清理仍被队列保护的记录；下一次完整扫描会自然收敛。
                if not _uses_active_target(archive) and not _uses_active_target(seen_filenames[archive.filename]):
                    duplicates.append(archive)
            else:
                seen_filenames[archive.filename] = archive
        
        if duplicates:
            logger.info(f"发现 {len(duplicates)} 个重复记录，正在清理...")
            for dup in duplicates:
                db.delete(dup)
            db.commit()
            logger.info("重复记录清理完成")
        
        # 重新获取清理后的记录
        db_archives = {a.filename: a for a in db.query(ProcessedArchive).all()}

        # 把目录扫描 + 每个文件的 isfile / getsize 一次性下放到线程池，
        # 远程挂载（NAS / SMB）大目录时 N 次同步 stat 会阻塞 event loop。
        def _collect_processed_files() -> tuple[bool, list[tuple[str, str, int, list[str]]]]:
            """同步扫描 processed_dir；任何成员元信息失败都不能被当作缺失。"""
            try:
                names = os.listdir(processed_dir)
            except Exception as exc:
                logger.warning(f"列出已处理压缩包目录失败: {processed_dir} - {exc}")
                return False, []
            collected: list[tuple[str, str, int]] = []
            for name in names:
                fp = os.path.join(processed_dir, name)
                try:
                    if not os.path.isfile(fp):
                        continue
                    collected.append((name, fp, os.path.getsize(fp)))
                except Exception as exc:
                    logger.warning(f"获取压缩包元信息失败: {fp} - {exc}")
                    # SMB/NAS 的单文件 stat 失败无法区分“真删除”与“短暂不可读”。
                    # 这轮扫描若继续，会把 DB 中未出现在 collected 的记录误删。
                    return False, []
            file_names = [item[0] for item in collected]
            return True, [(name, fp, size, file_names) for name, fp, size in collected]

        scan_succeeded, scanned_files = await asyncio.to_thread(_collect_processed_files)
        if not scan_succeeded:
            # NAS / SMB 短暂不可用时，不能把一次失败的 listdir 解释成目录为空，
            # 否则会批量删除仍然真实存在的 ProcessedArchive 记录。
            logger.warning("已处理压缩包目录扫描未完成，保留现有数据库记录: %s", processed_dir)
            return

        # 扫描目录中的文件（DB 写入留在 event loop，操作短，不会阻塞）
        from ..core.archive_volume_utils import detect_archive_volume_group

        size_by_path = {file_path: file_size for _, file_path, file_size, _ in scanned_files}
        found_files = set()
        visited_members = set()
        for filename, file_path, file_size, file_names in scanned_files:
            if file_path in visited_members:
                continue

            group = detect_archive_volume_group(file_path, sibling_names=file_names)
            group_members = group.volumes if group else [file_path]
            if any(_normalized_archive_path(path) in active_target_paths for path in group_members):
                # 同组任一成员仍属于未完成队列时，整组都不能被当作独立已处理文件。
                visited_members.update(group_members)
                continue
            volume_count = 1
            archive_manifest = []
            if group:
                main_path = group.main_path
                main_filename = group.main_filename
                grouped_size = sum(int(size_by_path.get(path, 0) or 0) for path in group.volumes)
                volume_count = max(1, len(group.volumes))
                archive_manifest = [
                    {
                        "target_path": path,
                        "filename": os.path.basename(path),
                        "size": int(size_by_path.get(path, 0) or 0),
                        "state": "completed",
                    }
                    for path in group.volumes
                ]
                for member_path in group.volumes:
                    visited_members.add(member_path)
                filename = main_filename
                file_path = main_path
                file_size = grouped_size
                logger.info(
                    f"已处理压缩包扫描聚合分卷: {main_filename}, "
                    f"volumes={len(group.volumes)}, total_size={grouped_size}"
                )
            else:
                visited_members.add(file_path)
                archive_manifest = [{
                    "target_path": file_path,
                    "filename": filename,
                    "size": int(file_size or 0),
                    "state": "completed",
                }]

            found_files.add(filename)

            # 提取RJ号
            rjcode = None
            match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
            if match:
                rjcode = match.group(0).upper()

            if filename in db_archives:
                # 更新现有记录（只更新路径和大小，不更新时间）
                archive = db_archives[filename]
                archive.current_path = file_path
                archive.file_size = file_size
                archive.volume_count = volume_count
                archive.archive_manifest = archive_manifest
                # 注意：不要在这里更新 processed_at，扫描只是同步文件状态，不是重新处理
                logger.info(f"更新已处理压缩包记录路径: {filename}")
            else:
                # 创建新记录
                new_archive = ProcessedArchive(
                    id=str(uuid.uuid4()),
                    original_path=file_path,
                    current_path=file_path,
                    filename=filename,
                    rjcode=rjcode or '',
                    file_size=file_size,
                    volume_count=volume_count,
                    archive_manifest=archive_manifest,
                    processed_at=datetime.now(),
                    process_count=1,
                    task_id='',
                    status='completed'
                )
                db.add(new_archive)
                logger.info(f"添加新的已处理压缩包记录: {filename}")

        # 清理数据库中不存在的记录
        # found_files 已经覆盖了"目录里实际存在的文件"，db 中其他 filename 直接判定为缺失。
        # 不再做额外的 os.path.exists 同步 IO（也避免 db_archives 数量大时 N 次远程 stat）。
        for filename, archive in list(db_archives.items()):
            if filename not in found_files:
                if _uses_active_target(archive):
                    logger.info("保留仍受延后归档队列保护的已处理记录: %s", filename)
                    continue
                logger.info(f"删除不存在的压缩包记录: {filename}")
                db.delete(archive)
        
        db.commit()
        logger.info(f"已处理压缩包目录扫描完成，共发现 {len(found_files)} 个文件")
        
    except Exception as e:
        logger.error(f"扫描已处理压缩包目录失败: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

# 已处理压缩包API
@app.post("/api/processed-archives/scan")
async def scan_processed_archives_api():
    """手动触发扫描已处理压缩包目录"""
    try:
        await scan_processed_archives()
        return {"message": "扫描完成"}
    except Exception as e:
        logger.error(f"手动扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")

@app.get("/api/processed-archives")
async def get_processed_archives(
    search: Optional[str] = None,
    sort_by: Optional[str] = "processed_at",
    sort_order: Optional[str] = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """获取已处理压缩包列表，支持搜索和排序
    
    Args:
        search: 搜索关键词（匹配RJ号、文件名）
        sort_by: 排序字段（rjcode, file_size, process_count, status, processed_at）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        query = db.query(ProcessedArchive)
        
        # 搜索功能
        if search:
            query = query.filter(_processed_archive_search_filter(search))
        
        # 排序功能
        valid_sort_fields = {
            "rjcode": ProcessedArchive.rjcode,
            "file_size": ProcessedArchive.file_size,
            "process_count": ProcessedArchive.process_count,
            "status": ProcessedArchive.status,
            "processed_at": ProcessedArchive.processed_at
        }
        
        sort_field = valid_sort_fields.get(sort_by, ProcessedArchive.processed_at)
        
        if sort_order.lower() == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        total = query.count()
        safe_limit = max(1, min(int(limit or 50), 500))
        safe_offset = max(0, int(offset or 0))
        archives = query.offset(safe_offset).limit(safe_limit).all()
        return {
            "archives": [archive.to_dict() for archive in archives],
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
        }
    finally:
        db.close()

@app.post("/api/processed-archives/{archive_id}/reprocess")
async def reprocess_archive(archive_id: str):
    """重新处理已归档的压缩包"""
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        archive = db.query(ProcessedArchive).filter(ProcessedArchive.id == archive_id).first()
        if not archive:
            raise HTTPException(status_code=404, detail="压缩包记录不存在")
        
        # 检查文件是否还存在
        if not os.path.exists(archive.current_path):
            raise HTTPException(status_code=404, detail="压缩包文件不存在，可能已被删除")
        
        # 直接从 processed 目录解压，避免复制到 SSD
        logger.info(f"直接从 processed 目录重新解压: {archive.current_path}")
        
        # 检查是否已有处理同RJ号的现存任务
        engine = get_task_engine()
        existing_tasks_for_rj = [t for t in engine.get_all_tasks()
                               if t.rjcode == archive.rjcode]

        if existing_tasks_for_rj:
            # 复用已有任务
            task = existing_tasks_for_rj[0]
            original_source = task.source_path
            old_status = task.status
            task.source_path = archive.current_path
            task.skip_archive = True  # 标记跳过归档（因为文件已在 processed 目录）
            task.status = TaskStatus.PENDING
            task.update_progress(0, "待处理")
            # 将任务加入队列以供 worker 执行
            await engine.queue.put(task)
            logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {archive.rjcode}, 状态: {old_status} -> {task.status}")
        else:
            # 创建新任务（标记为重新处理，直接从 processed 目录解压）
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=archive.current_path,  # 直接使用 processed 目录中的文件
                auto_classify=get_config().watcher.auto_classify,
                skip_archive=True  # 标记跳过归档（因为文件已在 processed 目录）
            )
            await engine.submit(task)
            # 注意：submit 会自动添加 task 到 engine.tasks 和队列中
        
        # 更新记录状态和重新处理时间
        archive.status = 'reprocessing'
        archive.processed_at = datetime.now()
        archive.process_count = (archive.process_count or 0) + 1
        db.commit()
        
        return {
            "message": "已创建重新处理任务",
            "task_id": task.id,
            "filename": archive.filename,
            "rjcode": archive.rjcode
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新处理压缩包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新处理失败: {str(e)}")
    finally:
        db.close()

# 库存管理API
@app.get("/api/library/libraries")
async def get_library_definitions():
    manager = get_library_manager()
    current_library = manager.get_library_definition()
    return {
        "libraries": manager.list_libraries(),
        "default_library_id": current_library.id,
        "default_extract_library_id": manager.default_extract_library_id(),
    }


@app.get("/api/library/view-preferences")
async def get_library_view_preferences():
    config = get_config()
    view_mode = getattr(getattr(getattr(config, "ui", None), "library", None), "view_mode", "directory")
    normalized = str(view_mode or "directory").strip().lower()
    if normalized not in {"directory", "circle"}:
        normalized = "directory"
    return {"view_mode": normalized}


@app.post("/api/library/view-preferences")
async def update_library_view_preferences(payload: LibraryViewPreferencesRequest):
    view_mode = str(payload.view_mode or "").strip().lower()
    if view_mode not in {"directory", "circle"}:
        raise HTTPException(status_code=400, detail="view_mode 只能是 directory 或 circle")
    config = save_config({"ui": {"library": {"view_mode": view_mode}}})
    next_mode = getattr(getattr(getattr(config, "ui", None), "library", None), "view_mode", view_mode)
    return {"view_mode": str(next_mode or view_mode)}


@app.post("/api/library/test-connection")
async def test_library_connection(request: Request):
    try:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="请求体必须为有效 JSON")
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="请求体必须为 JSON 对象")
        library = data.get("library") or data
        manager = get_library_manager()
        return await manager.test_connection(library)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存连接测试失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存连接测试失败: {str(e)}")


@app.get("/api/library/storage-info")
async def get_library_storage_info(library_id: str, refresh: bool = False):
    try:
        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if library.type != "synology_filestation" or not library.synology:
            raise HTTPException(status_code=400, detail="目标库存不是群晖库存")
        client = manager.get_cached_synology_client(library.synology)

        cache_key = str(library.id or library_id or "").strip()
        now = time.monotonic()
        cached = _LIBRARY_STORAGE_INFO_CACHE.get(cache_key)
        cached_payload = dict(cached.get("payload") or {}) if isinstance(cached, dict) else None
        if (
            not refresh
            and cached_payload
            and float(cached.get("expires_at") or 0.0) > now
        ):
            return dict(cached_payload)

        async def _load_storage_info() -> Dict[str, Any]:
            storage_info = await client.get_storage_info(library.root_path)
            payload = {
                "library_id": library.id,
                "library_name": library.name,
                **storage_info,
                "stale": False,
                "cached_at": datetime.now().isoformat(),
            }
            _LIBRARY_STORAGE_INFO_CACHE[cache_key] = {
                "expires_at": time.monotonic() + _STORAGE_INFO_TTL_SECONDS,
                "payload": dict(payload),
            }
            return payload

        def _refresh_task() -> asyncio.Task:
            existing = _LIBRARY_STORAGE_INFO_REFRESH_TASKS.get(cache_key)
            if existing is not None and not existing.done():
                return existing
            task = asyncio.create_task(_load_storage_info(), name=f"library-storage-info:{cache_key}")
            _LIBRARY_STORAGE_INFO_REFRESH_TASKS[cache_key] = task

            def _cleanup(done_task: asyncio.Task) -> None:
                if _LIBRARY_STORAGE_INFO_REFRESH_TASKS.get(cache_key) is done_task:
                    _LIBRARY_STORAGE_INFO_REFRESH_TASKS.pop(cache_key, None)
                if not done_task.cancelled():
                    done_task.exception()

            task.add_done_callback(_cleanup)
            return task

        if cached_payload and not refresh:
            refresh_task = _refresh_task()
            try:
                return await asyncio.wait_for(
                    asyncio.shield(refresh_task),
                    timeout=_LIBRARY_STORAGE_INFO_STALE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                refresh_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                stale_payload = dict(cached_payload)
                stale_payload["stale"] = True
                stale_payload["stale_reason"] = "timeout"
                return stale_payload

        try:
            return await asyncio.wait_for(
                asyncio.shield(_refresh_task()),
                timeout=_LIBRARY_STORAGE_INFO_COLD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="群晖存储空间查询超时，后台仍在刷新")
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"获取库存空间失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"获取库存空间失败: {str(e)}")


@app.get("/api/library/circle-groups")
async def list_library_circle_groups(
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
    sort_by: str = "name",
    sort_order: str = "asc",
):
    try:
        from ..core.library_circle_aggregation_service import get_library_circle_aggregation_service

        payload = await asyncio.to_thread(
            get_library_circle_aggregation_service().list_circle_groups,
            page=page,
            page_size=page_size,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        payload["libraries"] = get_library_manager().list_libraries()
        return payload
    except Exception as e:
        logger.error("读取库存社团聚合失败: %s", sanitize_text_for_log(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取库存社团聚合失败: {str(e)}")


@app.get("/api/library/circle-groups/{circle_key}/works")
async def list_library_circle_group_works(
    circle_key: str,
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
):
    try:
        from ..core.library_circle_aggregation_service import get_library_circle_aggregation_service

        payload = await asyncio.to_thread(
            get_library_circle_aggregation_service().list_circle_works,
            circle_key,
            page=page,
            page_size=page_size,
            keyword=keyword,
        )
        payload["libraries"] = get_library_manager().list_libraries()
        return payload
    except Exception as e:
        logger.error("读取库存社团作品失败: %s", sanitize_text_for_log(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取库存社团作品失败: {str(e)}")


@app.get("/api/library/circle-browser/files")
async def browse_library_circle_files(
    current_path: str = "circle:/",
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
    sort_by: str = "name",
    sort_order: str = "asc",
    force_refresh: bool = False,
):
    try:
        from ..core.library_circle_aggregation_service import get_library_circle_aggregation_service

        service = get_library_circle_aggregation_service()
        if service.should_thread_browse(current_path):
            payload = await asyncio.to_thread(
                service.browse_circle_listing,
                current_path=current_path,
                page=page,
                page_size=page_size,
                keyword=keyword,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
            )
        else:
            payload = await service.browse_circle_path(
                current_path=current_path,
                page=page,
                page_size=page_size,
                keyword=keyword,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
            )
        index_views, view_token = service._load_index_views()
        payload["index_views"] = index_views
        payload["view_token"] = view_token
        payload["libraries"] = get_library_manager().list_libraries()
        return payload
    except Exception as e:
        logger.error("读取库存社团浏览失败: %s", sanitize_text_for_log(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取库存社团浏览失败: {str(e)}")


class LibraryCircleActionTargetsRequest(BaseModel):
    current_path: str = "circle:/"
    paths: List[str] = Field(default_factory=list)
    max_targets: int = 5000


@app.post("/api/library/circle-browser/action-targets")
async def resolve_library_circle_action_targets(request: LibraryCircleActionTargetsRequest):
    try:
        from ..core.library_circle_aggregation_service import get_library_circle_aggregation_service

        return get_library_circle_aggregation_service().resolve_action_targets(
            current_path=request.current_path,
            paths=request.paths,
            max_targets=request.max_targets,
        )
    except Exception as e:
        logger.error("解析库存社团操作目标失败: %s", sanitize_text_for_log(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"解析库存社团操作目标失败: {str(e)}")


# ========== 库存搜索索引 API ==========
# 由 library_index 模块提供：在 PostgreSQL 里常驻一份"库存 → 条目"快照，
# 用 SQL 查询替代群晖几十万级目录上的实时 walk / SYNO.FileStation.Search。
# 当前批次仅支持 local 库存的重建与查询，synology_filestation 库存
# 由后续批次新增 RemoteScanner 后再扩展。

class LibraryIndexRebuildRequest(BaseModel):
    """重建库存搜索索引请求。"""
    library_id: str


class LibraryIndexRetryBlockedRequest(BaseModel):
    library_id: str
    expected_blocked_seq: int


def _request_idempotency_key(request: Request) -> str:
    return str(request.headers.get("Idempotency-Key") or "").strip()


def _local_relative_path(library, absolute_path: str) -> str:
    root = os.path.abspath(library.root_path)
    target = os.path.abspath(absolute_path)
    try:
        if os.path.normcase(os.path.commonpath([root, target])) != os.path.normcase(root):
            raise ValueError("路径不在库存根目录内")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径不在库存根目录内") from exc
    relative = os.path.relpath(target, root).replace("\\", "/")
    return "" if relative == "." else relative.strip("/")


def _local_rename_effects(library, source_path: str, target_path: str) -> List[Dict[str, Any]]:
    scope = "subtree" if os.path.isdir(source_path) else "exact"
    relative_target = _local_relative_path(library, target_path)
    return [
        {
            "kind": "move",
            "relative_path": _local_relative_path(library, source_path),
            "scope": scope,
            "target_library_id": library.id,
            "target_path": relative_target,
        },
        {
            "kind": "reconcile",
            "relative_path": relative_target,
            "scope": scope,
        },
    ]


def _prepared_replay_response(prepared) -> Optional[Dict[str, Any]]:
    if not prepared.replayed:
        return None
    if prepared.state == "committed":
        return dict(prepared.result or {})
    return {
        "operation_id": prepared.operation_id,
        "operation_state": prepared.state,
        "processing": prepared.state in {"prepared", "reconcile_required"},
    }


def _stored_mutation_replay_response(
    operation: Optional[Dict[str, Any]],
    *,
    expected_kind: str,
    expected_sources: Dict[str, set[str]],
) -> Optional[Dict[str, Any]]:
    if operation is None:
        return None
    if str(operation.get("kind") or "") != expected_kind:
        raise HTTPException(status_code=409, detail="Idempotency-Key 已用于不同操作")
    actual_sources: Dict[str, set[str]] = {}
    for scope in operation.get("planned_scopes") or []:
        if str(scope.get("kind") or "") != "move":
            continue
        library_id = str(scope.get("library_id") or "")
        relative_path = str(scope.get("relative_path") or "").strip("/")
        actual_sources.setdefault(library_id, set()).add(relative_path)
    if actual_sources != expected_sources:
        raise HTTPException(status_code=409, detail="Idempotency-Key 对应的库存或路径与当前请求不一致")
    state = str(operation.get("state") or "prepared")
    if state == "committed":
        return dict(operation.get("actual_result") or {})
    return {
        "operation_id": str(operation.get("operation_id") or ""),
        "operation_state": state,
        "processing": state in {"prepared", "reconcile_required"},
    }


def _index_status_to_dict(status, fallback_library_id: Optional[str] = None) -> Dict[str, Any]:
    if status is None:
        return {
            "library_id": fallback_library_id or "",
            "status": "idle",
            "watcher_mode": None,
            "total_entries": 0,
            "total_size_bytes": 0,
            "folder_count": 0,
            "last_full_scan_at": None,
            "last_event_at": None,
            "error": None,
            "updated_at": None,
            "accepted_seq": 0,
            "materialized_seq": 0,
            "pending_events": 0,
            "state_revision": 0,
            "view_revision": 0,
            "active_generation": 1,
            "building_generation": None,
            "catchup_state": "idle",
        }
    payload = {
        "library_id": status.library_id,
        "status": status.status,
        "watcher_mode": status.watcher_mode,
        "total_entries": status.total_entries,
        "total_size_bytes": status.total_size_bytes,
        "folder_count": status.folder_count,
        "last_full_scan_at": status.last_full_scan_at,
        "last_event_at": status.last_event_at,
        "error": status.error,
        "updated_at": status.updated_at,
        "accepted_seq": int(getattr(status, "accepted_seq", 0) or 0),
        "materialized_seq": int(getattr(status, "materialized_seq", 0) or 0),
        "pending_events": int(getattr(status, "pending_events", 0) or 0),
        "state_revision": int(getattr(status, "state_revision", 0) or 0),
        "view_revision": int(getattr(status, "view_revision", 0) or 0),
        "active_generation": int(getattr(status, "active_generation", 1) or 1),
        "building_generation": getattr(status, "building_generation", None),
        "catchup_state": str(getattr(status, "catchup_state", "idle") or "idle"),
        "last_operation_id": getattr(status, "last_operation_id", None),
        "materializer_epoch": int(getattr(status, "materializer_epoch", 0) or 0),
        "blocked_seq": getattr(status, "blocked_seq", None),
        "catchup_error": getattr(status, "catchup_error", None),
    }
    return payload


def _disabled_remote_index_status(library) -> Dict[str, Any]:
    return {
        "library_id": library.id,
        "library_name": library.name,
        "library_type": library.type,
        "status": "disabled",
        "watcher_mode": "disabled",
        "total_entries": 0,
        "total_size_bytes": 0,
        "folder_count": 0,
        "last_full_scan_at": None,
        "last_event_at": None,
        "error": None,
        "updated_at": int(time.time() * 1000),
        "disabled_reason": "remote_filestation",
    }


def _index_entry_to_dict(entry) -> Dict[str, Any]:
    return {
        "library_id": entry.library_id,
        "entry_type": entry.entry_type,
        "relative_path": entry.relative_path,
        "absolute_path": entry.absolute_path,
        "name": entry.name,
        "rjcode": entry.rjcode,
        "parent_path": entry.parent_path,
        "size": entry.size,
        "file_count": entry.file_count,
        "mtime": entry.mtime,
        "depth": entry.depth,
        "index_generation": int(getattr(entry, "generation", 1) or 1),
        "materialized_seq": int(getattr(entry, "materialized_seq", 0) or 0),
    }


def _library_index_view(library_id: str) -> Dict[str, Any]:
    status = get_library_index_service().get_status(library_id)
    payload = _index_status_to_dict(status, library_id)
    return {
        "library_id": library_id,
        "index_generation": int(payload.get("active_generation") or 1),
        "accepted_seq": int(payload.get("accepted_seq") or 0),
        "materialized_seq": int(payload.get("materialized_seq") or 0),
        "state_revision": int(payload.get("state_revision") or 0),
        "view_revision": int(payload.get("view_revision") or 0),
        "stats_as_of_seq": int(payload.get("materialized_seq") or 0),
    }


def _library_index_views(library_ids: list[str]) -> tuple[list[Dict[str, Any]], str]:
    views = [
        _library_index_view(library_id)
        for library_id in sorted({str(item or "").strip() for item in library_ids if str(item or "").strip()})
    ]
    token = "|".join(
        f"{item['library_id']}:{item['index_generation']}:{item['view_revision']}"
        for item in views
    )
    return views, token


@app.post("/api/library/index/rebuild")
async def post_library_index_rebuild(request: LibraryIndexRebuildRequest):
    """异步触发库存搜索索引的全量重建。

    仅支持 local 库存：
    - local：本地 os.scandir 扫描，后台 thread 跑
    - synology_filestation：远程库走群晖 FileStation 原生接口，不创建库存索引

    立即把状态置为 syncing 并返回，前端通过 /api/library/index/status 轮询
    status 字段判断 ready / error。
    """
    library_id = (request.library_id or "").strip()
    if not library_id:
        raise HTTPException(status_code=400, detail="library_id 不能为空")

    manager = get_library_manager()
    try:
        library = manager.get_library_definition(library_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"未找到库存: {exc}")

    service = get_library_index_service()

    if library.type == "local":
        if not library.path:
            raise HTTPException(status_code=400, detail="本地库存未配置 path")
        if service._generation_contract_enabled():
            async def _run_generation_rebuild() -> None:
                try:
                    await asyncio.to_thread(
                        service.rebuild_local_generation,
                        library.id,
                        library.path,
                    )
                except Exception:
                    logger.exception("[索引] generation rebuild 失败 library=%s", library.id)

            task = asyncio.create_task(_run_generation_rebuild())
            service._track_rebuild_task(library.id, task)
            await asyncio.sleep(0)
            status = service.get_status(library.id)
        else:
            status = await service.schedule_rebuild_local(library.id, library.path)
    elif library.type == "synology_filestation":
        raise HTTPException(
            status_code=400,
            detail="远程群晖库存不再创建库存索引，请使用群晖 FileStation 原生浏览/搜索",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"未支持的库存类型：{library.type}",
        )

    payload = _index_status_to_dict(status, fallback_library_id=library.id)
    payload["library_name"] = library.name
    payload["library_type"] = library.type
    return payload


@app.get("/api/library/index/status")
async def get_library_index_status(library_id: Optional[str] = None):
    """查询索引状态。

    - 传 library_id：返回单库状态；从未重建过会返回伪 idle 状态
    - 不传 library_id：返回 status 表里所有库的状态列表
    """
    service = get_library_index_service()
    if library_id:
        normalized = library_id.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="library_id 不能为空字符串")
        manager = get_library_manager()
        try:
            library = manager.get_library_definition(normalized)
        except Exception:
            library = None
        if library is not None and library.type == "synology_filestation":
            return _disabled_remote_index_status(library)
        return _index_status_to_dict(service.get_status(normalized), fallback_library_id=normalized)

    manager = get_library_manager()
    remote_library_ids = {
        str(item.get("id") or "")
        for item in manager.list_libraries()
        if item.get("id") and item.get("type") == "synology_filestation"
    }
    statuses = [
        item for item in service.list_all_status()
        if item.library_id not in remote_library_ids
    ]
    return {
        "items": [_index_status_to_dict(item) for item in statuses],
        "count": len(statuses),
    }


@app.post("/api/library/index/mutations/retry-blocked")
async def retry_blocked_library_index_mutation(
    request: LibraryIndexRetryBlockedRequest,
):
    library_id = str(request.library_id or "").strip()
    if not library_id:
        raise HTTPException(status_code=400, detail="library_id 不能为空")
    try:
        return get_library_index_mutation_service().retry_blocked(
            library_id,
            expected_blocked_seq=request.expected_blocked_seq,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/library/index/search")
async def search_library_index(
    library_id: Optional[str] = None,
    rjcode: Optional[str] = None,
    name: Optional[str] = None,
    entry_type: Optional[str] = None,
    limit: int = 100,
):
    """基于本地索引的搜索接口。rjcode 优先匹配，否则按 name 模糊。

    供前端调试 + 后续业务接入前的快速验证。批次 5 会把库存浏览 / RJ
    字幕扫描 / 大小统计这些业务点切到此索引上。
    """
    service = get_library_index_service()
    rjcode_normalized = (rjcode or "").strip().upper()
    name_normalized = (name or "").strip()
    if not rjcode_normalized and not name_normalized:
        raise HTTPException(status_code=400, detail="请至少传 rjcode 或 name 之一")
    capped_limit = max(1, min(int(limit or 100), 1000))
    library_scope = (library_id or "").strip() or None
    manager = get_library_manager()
    local_library_ids = [
        str(item.get("id") or "")
        for item in manager.list_libraries()
        if item.get("id") and item.get("type") != "synology_filestation"
    ]
    if library_scope:
        library_def = manager.get_library_definition(library_scope)
        if library_def.type == "synology_filestation":
            return {
                "items": [],
                "count": 0,
                "index_status": _disabled_remote_index_status(library_def),
            }
    else:
        if not local_library_ids:
            return {"items": [], "count": 0}
        library_scope = local_library_ids

    if rjcode_normalized:
        entries = service.find_by_rjcode(
            rjcode_normalized,
            library_scope,
            entry_type=entry_type,
            limit=capped_limit,
        )
    else:
        if not library_scope:
            raise HTTPException(status_code=400, detail="按 name 搜索时 library_id 必填")
        entries = service.find_by_name(
            library_scope,
            name_normalized,
            entry_type=entry_type,
            limit=capped_limit,
        )

    response = {
        "items": [_index_entry_to_dict(entry) for entry in entries],
        "count": len(entries),
    }
    scope_ids = [library_scope] if isinstance(library_scope, str) else list(library_scope or [])
    if len(scope_ids) == 1:
        response["index_view"] = _library_index_view(scope_ids[0])
    else:
        index_views, view_token = _library_index_views(scope_ids)
        response["index_views"] = index_views
        response["view_token"] = view_token
    return response


_GLOBAL_INDEX_SEARCH_LIMIT_MAX = 500
_GLOBAL_INDEX_SEARCH_LIMIT_DEFAULT = 50
_GLOBAL_INDEX_SEARCH_RJ_RE = re.compile(r"^RJ\d{4,12}$", re.IGNORECASE)
_GLOBAL_INDEX_SEARCH_RJ_DIGITS_RE = re.compile(r"^\d{6,12}$")


def _normalize_global_index_entry_type(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip().lower()
    if normalized in ("", "all", "any"):
        return None
    if normalized in ("dir", "folder", "directory"):
        return "dir"
    if normalized in ("file", "files"):
        return "file"
    return None


def _detect_global_index_rjcode(keyword: str) -> Optional[str]:
    if not keyword:
        return None
    text = keyword.strip().upper().replace(" ", "")
    if _GLOBAL_INDEX_SEARCH_RJ_RE.match(text):
        return text
    if _GLOBAL_INDEX_SEARCH_RJ_DIGITS_RE.match(text):
        return f"RJ{text}"
    return None


def _collapse_exact_rj_descendants(
    items: list[Dict[str, Any]],
    matched_rjcode: Optional[str],
) -> list[Dict[str, Any]]:
    """完整 RJ 搜索只保留每个真实收录位置的最上层作品目录。

    库存索引会把作品 RJ 传播到其后代目录。若直接展示 find_by_rjcode 的
    全部结果，特典、台本、图片等子目录会挤满搜索建议。这里按库和路径
    折叠已命中作品目录的后代，同时保留同库不同路径、多库收录的位置。
    """
    normalized_rj = str(matched_rjcode or "").strip().upper()
    if not normalized_rj:
        return items

    kept: list[Dict[str, Any]] = []
    kept_roots: Dict[str, list[str]] = {}
    for item in items:
        item_rj = str(item.get("rjcode") or "").strip().upper()
        is_related_translation = item.get("search_match_type") == "related_translation"
        if (item_rj != normalized_rj and not is_related_translation) or item.get("entry_type") != "dir":
            kept.append(item)
            continue

        library_id = str(item.get("library_id") or "")
        relative_path = str(item.get("relative_path") or "").replace("\\", "/").strip("/")
        roots = kept_roots.setdefault(library_id, [])
        if relative_path and any(
            relative_path == root or relative_path.startswith(f"{root}/")
            for root in roots
        ):
            continue

        kept.append(item)
        if relative_path:
            roots.append(relative_path)

    return kept


async def _resolve_global_index_translation_relation(matched_rjcode: Optional[str]) -> Dict[str, Any]:
    normalized = str(matched_rjcode or "").strip().upper()
    empty = {
        "query_rjcode": normalized,
        "group_key": "",
        "group_label": "",
        "search_rjcodes": [normalized] if normalized else [],
        "related_rjcodes": [],
        "owned_locations": [],
    }
    if not normalized:
        return empty
    try:
        from ..core.circle_completion_service import get_circle_completion_service

        relation = await asyncio.to_thread(
            get_circle_completion_service().get_inventory_translation_search_relation,
            normalized,
        )
        return relation if isinstance(relation, dict) else empty
    except Exception:
        logger.warning("[索引搜索] 解析翻译 RJ 关联失败：rj=%s", normalized, exc_info=True)
        return empty


def _annotate_translation_search_item(
    item: Dict[str, Any],
    relation: Dict[str, Any],
) -> Dict[str, Any]:
    query_rjcode = str(relation.get("query_rjcode") or "").strip().upper()
    actual_rjcode = str(item.get("rjcode") or "").strip().upper()
    related_rjcodes = {
        str(code or "").strip().upper()
        for code in relation.get("related_rjcodes") or []
        if str(code or "").strip()
    }
    if query_rjcode and actual_rjcode == query_rjcode:
        item["search_match_type"] = "exact"
    elif actual_rjcode and actual_rjcode in related_rjcodes:
        item["search_match_type"] = "related_translation"
    else:
        return item
    item["search_query_rjcode"] = query_rjcode
    item["search_actual_rjcode"] = actual_rjcode
    item["search_relation_group"] = str(relation.get("group_key") or "")
    item["search_relation_label"] = str(relation.get("group_label") or "")
    return item


def _build_owned_translation_relation_items(
    relation: Dict[str, Any],
    library_lookup: Dict[str, Dict[str, Any]],
) -> list[Dict[str, Any]]:
    query_rjcode = str(relation.get("query_rjcode") or "").strip().upper()
    items: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for location in relation.get("owned_locations") or []:
        library_id = str(location.get("library_id") or "").strip()
        path = str(location.get("path") or "").strip()
        actual_rjcode = str(location.get("actual_rjcode") or "").strip().upper()
        if not library_id or not path or not actual_rjcode or actual_rjcode == query_rjcode:
            continue
        library_info = library_lookup.get(library_id)
        if not library_info:
            continue
        item = _fallback_entry_to_uniform_item(
            {
                "path": path,
                "name": os.path.basename(path.rstrip("/\\")) or path,
                "is_directory": True,
                "rjcode": actual_rjcode,
            },
            library_info,
        )
        if item is None:
            continue
        item["source"] = "owned_relation"
        _annotate_translation_search_item(item, relation)
        key = (library_id, str(item.get("relative_path") or item.get("absolute_path") or ""))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _resolve_global_index_library_scope(
    manager,
    library_ids_csv: Optional[str],
) -> tuple[list[str], list[Dict[str, Any]]]:
    """把传入的 library_ids（CSV 字符串）解析成实际可用的 library_id 列表 +
    库存信息字典列表，便于结果里塞 library_name / library_type。

    - 不传 / 空 → 默认全部启用的库存
    - 任意一个未在配置中的 ID 都会被过滤掉，避免越权访问
    """
    libraries = manager.list_libraries()  # 已按可见性过滤
    library_map: Dict[str, Dict[str, Any]] = {
        str(item.get("id") or ""): item for item in libraries if item.get("id")
    }
    if not library_ids_csv or not library_ids_csv.strip():
        scoped = list(library_map.values())
    else:
        wanted = {
            piece.strip()
            for piece in library_ids_csv.split(",")
            if piece.strip()
        }
        scoped = [library_map[item_id] for item_id in wanted if item_id in library_map]
    library_ids = [str(item.get("id") or "") for item in scoped if item.get("id")]
    return library_ids, scoped


# ===== 全局跨库搜索：未就绪库的非索引兜底 =====
# 让索引未建好（比如远程库刚加上、扫描还没跑完）的库也能搜出来：
# 直接复用 LibraryManager.list_files 的搜索能力——本地走 os.walk，远程走 SYNO.Search。
# 每个库独立计时，超时 / 出错只影响该库，不拖垮整体响应。
#
# 现在的设计是"索引零命中才回退到这条路径"，所以这是用户搜索"未匹配"时的等待上限。
# 5s 是平衡点：足够慢的远程库返回，也不会让"明明搜不到"等太久。
_GLOBAL_FALLBACK_PER_LIBRARY_TIMEOUT_S = 5.0


def _entry_type_to_search_kind(normalized: Optional[str]) -> str:
    if normalized == "dir":
        return "folder"
    if normalized == "file":
        return "file"
    return "all"


def _build_uniform_search_item(
    *,
    library_id: str,
    library_name: str,
    library_type: str,
    entry_type: str,
    name: str,
    relative_path: str,
    absolute_path: str,
    parent_path: str,
    depth: Optional[int],
    size: Optional[int],
    mtime: Optional[int],
    rjcode: Optional[str],
    file_count: Optional[int] = None,
    source: str = "index",
) -> Dict[str, Any]:
    return {
        "library_id": library_id,
        "library_name": library_name,
        "library_type": library_type,
        "entry_type": entry_type,
        "name": name,
        "relative_path": relative_path,
        "absolute_path": absolute_path,
        "parent_path": parent_path,
        "depth": depth,
        "size": size,
        "file_count": file_count,
        "mtime": mtime,
        "rjcode": rjcode,
        "source": source,  # 'index' / 'fallback' —— 前端可据此提示该结果来自非索引搜索
    }


def _index_entry_to_uniform_item(entry, library_info: Dict[str, Any]) -> Dict[str, Any]:
    return _build_uniform_search_item(
        library_id=entry.library_id,
        library_name=str(library_info.get("name") or entry.library_id),
        library_type=str(library_info.get("type") or "local"),
        entry_type=entry.entry_type,
        name=entry.name,
        relative_path=entry.relative_path,
        absolute_path=entry.absolute_path,
        parent_path=entry.parent_path or "",
        depth=entry.depth,
        size=entry.size,
        file_count=entry.file_count,
        mtime=entry.mtime,
        rjcode=entry.rjcode,
        source="index",
    )


def _fallback_entry_to_uniform_item(
    raw_entry: Dict[str, Any],
    library_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """list_files 返回的一条记录 → 统一形态。无法识别的条目返回 None。"""
    abs_path = str(raw_entry.get("path") or "").strip()
    name = str(raw_entry.get("name") or "").strip()
    if not name and abs_path:
        name = os.path.basename(abs_path.rstrip("/")) or abs_path
    if not name and not abs_path:
        return None
    is_dir = bool(raw_entry.get("is_directory"))

    library_type = str(library_info.get("type") or "local")
    library_id = str(library_info.get("id") or "")
    library_name = str(library_info.get("name") or library_id)
    root = str(library_info.get("root_path") or library_info.get("path") or "").strip()

    rel = ""
    if abs_path:
        if library_type == "synology_filestation":
            norm_root = root.rstrip("/")
            norm_path = abs_path.rstrip("/") or abs_path
            if norm_root and norm_path == norm_root:
                rel = ""
            elif norm_root and norm_path.startswith(norm_root + "/"):
                rel = norm_path[len(norm_root) + 1:]
            else:
                rel = norm_path.lstrip("/") or name
        else:
            try:
                rel_local = os.path.relpath(abs_path, root) if root else ""
            except ValueError:
                rel_local = ""
            if not rel_local or rel_local in {".", ""} or rel_local.startswith(".."):
                rel = name
            else:
                rel = rel_local.replace(os.sep, "/")
    else:
        rel = name

    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    depth = rel.count("/") if rel else 0

    mtime_ms: Optional[int] = None
    mtime_iso = raw_entry.get("modified_time") or raw_entry.get("unzip_time")
    if mtime_iso:
        try:
            mtime_ms = int(datetime.fromisoformat(str(mtime_iso)).timestamp() * 1000)
        except Exception:
            mtime_ms = None

    rjcode_raw = raw_entry.get("rjcode")
    rjcode = str(rjcode_raw).strip().upper() if rjcode_raw else None

    return _build_uniform_search_item(
        library_id=library_id,
        library_name=library_name,
        library_type=library_type,
        entry_type="dir" if is_dir else "file",
        name=name,
        relative_path=rel,
        absolute_path=abs_path,
        parent_path=parent,
        depth=depth,
        size=raw_entry.get("size"),
        mtime=mtime_ms,
        rjcode=rjcode,
        source="fallback",
    )


async def _global_search_fallback_one_library(
    manager,
    library_info: Dict[str, Any],
    keywords: Any,
    normalized_entry_type: Optional[str],
    fetch_limit: int,
) -> tuple[str, list[Dict[str, Any]], Optional[str]]:
    """对单个未就绪的库走 list_files 兜底搜索。

    返回 (library_id, items, error_or_none)：
    - error == 'timeout'：超过 _GLOBAL_FALLBACK_PER_LIBRARY_TIMEOUT_S
    - error == '<exc str>'：业务异常
    - error is None：成功（items 可能为空）
    """
    library_id = str(library_info.get("id") or "")
    if not library_id:
        return library_id, [], "missing_library_id"
    search_kind = _entry_type_to_search_kind(normalized_entry_type)

    if isinstance(keywords, str):
        search_keywords = [keywords]
    else:
        search_keywords = [str(item or "").strip() for item in list(keywords or [])]
    search_keywords = list(dict.fromkeys(item for item in search_keywords if item))[:8]
    if not search_keywords:
        return library_id, [], None

    async def _search_one(keyword: str) -> Dict[str, Any]:
        return await asyncio.wait_for(
            manager.list_files(
                library_id,
                page=1,
                page_size=max(50, min(fetch_limit, 200)),
                search=keyword,
                current_path=None,
                sort_by="name",
                sort_order="asc",
                search_exact=False,
                search_result_kind=search_kind,
            ),
            timeout=_GLOBAL_FALLBACK_PER_LIBRARY_TIMEOUT_S,
        )

    results = await asyncio.gather(
        *[_search_one(keyword) for keyword in search_keywords],
        return_exceptions=True,
    )
    payloads: list[Dict[str, Any]] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, asyncio.TimeoutError):
            errors.append("timeout")
            continue
        if isinstance(result, Exception):
            errors.append(str(result) or result.__class__.__name__)
            continue
        payloads.append(result)
    if errors:
        logger.info(
            "[索引搜索] 兜底部分失败：library_id=%s keywords=%s errors=%s",
            library_id,
            search_keywords,
            errors,
        )
    if not payloads:
        return library_id, [], errors[0] if errors else None

    items: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for data in payloads:
        for raw_entry in (data.get("files") or []):
            normalized = _fallback_entry_to_uniform_item(raw_entry, library_info)
            if normalized is None:
                continue
            key = str(normalized.get("relative_path") or normalized.get("absolute_path") or normalized.get("name") or "")
            if key in seen:
                continue
            seen.add(key)
            items.append(normalized)
    return library_id, items, None


@app.get("/api/library/index/global-search")
async def global_search_library_index(
    keyword: str = "",
    library_ids: Optional[str] = None,
    entry_type: str = "all",
    limit: int = _GLOBAL_INDEX_SEARCH_LIMIT_DEFAULT,
    mode: str = "full",
):
    """跨库存的索引搜索，专为库存页搜索框 / 全屏搜索面板服务。

    特性：
    - 默认跨全部启用库存（local + synology_filestation）；可通过 library_ids
      （CSV）收窄到指定库
    - 关键字会自动尝试 RJ 号识别（"RJ01234567" / "01234567" 都会命中）+
      名字模糊匹配，结果合并去重
    - 本地库只读库存索引；远程群晖库不建索引，必要时走 FileStation 搜索兜底
    - mode=suggest 时只返回前 limit 条用于自动补全；mode=full 时按 cap
      返回更多条目用于全屏搜索结果列表

    返回字段：
    - items：每条带 library_name / library_type，便于 UI 直接渲染来源标签
    - library_status：被搜索的库的索引就绪状态，UI 可据此提示"索引未就绪"
    - matched_rjcode：检测到的 RJ 号（如有），方便 UI 高亮
    """
    started_at = time.perf_counter()
    keyword_raw = (keyword or "").strip()
    if not keyword_raw:
        return {
            "items": [],
            "count": 0,
            "limit": 0,
            "truncated": False,
            "library_scope": [],
            "library_status": [],
            "matched_rjcode": None,
            "elapsed_ms": 0,
            "mode": mode or "full",
        }

    normalized_mode = "suggest" if (mode or "").strip().lower() == "suggest" else "full"
    raw_limit = max(1, int(limit or _GLOBAL_INDEX_SEARCH_LIMIT_DEFAULT))
    if normalized_mode == "suggest":
        capped_limit = min(raw_limit, 20)
    else:
        capped_limit = min(raw_limit, _GLOBAL_INDEX_SEARCH_LIMIT_MAX)

    manager = get_library_manager()
    library_ids_list, scoped_libraries = _resolve_global_index_library_scope(
        manager, library_ids
    )
    library_lookup: Dict[str, Dict[str, Any]] = {
        str(item.get("id") or ""): item for item in scoped_libraries if item.get("id")
    }

    if not library_ids_list:
        return {
            "items": [],
            "count": 0,
            "limit": capped_limit,
            "truncated": False,
            "library_scope": [],
            "library_status": [],
            "matched_rjcode": None,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            "mode": normalized_mode,
        }

    service = get_library_index_service()
    normalized_entry_type = _normalize_global_index_entry_type(entry_type)
    matched_rjcode = _detect_global_index_rjcode(keyword_raw)
    translation_relation = await _resolve_global_index_translation_relation(matched_rjcode)
    search_rjcodes = list(translation_relation.get("search_rjcodes") or [])

    # ===== Phase 1：先抓每个库的索引就绪状态，决定走索引还是走兜底 =====
    library_status_map: Dict[str, Dict[str, Any]] = {}
    ready_library_ids: list[str] = []
    unready_library_infos: list[Dict[str, Any]] = []
    for library_id in library_ids_list:
        info = library_lookup.get(library_id, {})
        library_type = str(info.get("type") or "local")
        if library_type == "synology_filestation":
            library_status_map[library_id] = {
                "library_id": library_id,
                "library_name": info.get("name") or library_id,
                "library_type": library_type,
                "index_status": "disabled",
                "total_entries": 0,
                "search_mode": "fallback",
                "fallback_error": None,
            }
            unready_library_infos.append(info or {"id": library_id, "type": library_type})
            continue
        try:
            status_obj = service.get_status(library_id)
        except Exception:  # noqa: BLE001 - 状态查询独立兜底
            logger.debug(
                "[索引搜索] 读取库存索引状态失败：library_id=%s",
                library_id,
                exc_info=True,
            )
            status_obj = None
        index_status_name = status_obj.status if status_obj else "idle"
        library_status_map[library_id] = {
            "library_id": library_id,
            "library_name": info.get("name") or library_id,
            "library_type": library_type,
            "index_status": index_status_name,
            "total_entries": int(getattr(status_obj, "total_entries", 0) or 0) if status_obj else 0,
            "search_mode": "index",  # 默认假设走索引；下面会根据 ready / fallback 调整
            "fallback_error": None,
        }
        if status_obj is not None and service.has_usable_snapshot(library_id):
            ready_library_ids.append(library_id)
        else:
            # syncing / idle / error 都视为未就绪 → 走非索引兜底
            unready_library_infos.append(info or {"id": library_id})
            library_status_map[library_id]["search_mode"] = "fallback_pending"

    # 给非索引库的状态先打个标，未就绪的库按 fallback 处理
    for info in unready_library_infos:
        lid = str(info.get("id") or "")
        if lid in library_status_map:
            library_status_map[lid]["search_mode"] = "fallback"

    # 拉一份比 limit 略大的中间结果，方便后续合并 / 排序后再裁剪
    fetch_limit = min(_GLOBAL_INDEX_SEARCH_LIMIT_MAX, max(capped_limit * 3, capped_limit + 50))

    # ===== Phase 2：对就绪的库走索引（毫秒级 SQL） =====
    # 关键性能优化：
    # 1) RJ 搜索时**只**跑 find_by_rjcode（exact match + 索引覆盖，~ms 级）；
    #    跳过 find_by_name(`%RJ01234567%`)——这是个不走索引的全表扫描，
    #    在 1M 级索引上要 1~2 秒，且 rjcode 已经精确命中，name LIKE 命中是噪声。
    # 2) 索引层任何异常都不让接口 500，转 200 + error 字段。
    error_payload: Optional[Dict[str, Any]] = None
    index_items: list[Dict[str, Any]] = []
    rj_hit_keys: set[tuple[str, str]] = set()

    def _run_phase2_index_sync() -> tuple[list[Any], list[Any], Optional[Dict[str, Any]]]:
        """同步索引查询，返回 (rj_entries, name_entries, error_payload)。
        放在 to_thread 里跑，避免阻塞 event loop。"""
        if not ready_library_ids:
            return [], [], None
        scope_param: Any = ready_library_ids[0] if len(ready_library_ids) == 1 else ready_library_ids
        try:
            rj_entries: list[Any] = []
            name_entries: list[Any] = []
            if matched_rjcode:
                if len(search_rjcodes) > 1 and hasattr(service, "find_by_rjcodes"):
                    rj_entries = service.find_by_rjcodes(
                        search_rjcodes,
                        scope_param,
                        entry_type="dir" if normalized_entry_type in (None, "dir") else normalized_entry_type,
                        limit=fetch_limit,
                    ) or []
                else:
                    rj_entries = service.find_by_rjcode(
                        matched_rjcode,
                        scope_param,
                        entry_type="dir" if normalized_entry_type in (None, "dir") else normalized_entry_type,
                        limit=fetch_limit,
                    ) or []
                # RJ 已命中：跳过 find_by_name 的全表扫描（性能关键）
            else:
                name_entries = service.find_by_name(
                    scope_param,
                    keyword_raw,
                    entry_type=normalized_entry_type,
                    limit=fetch_limit,
                ) or []
            return rj_entries, name_entries, None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[索引搜索] 索引查询失败，已降级：keyword=%r ready=%s err=%s",
                keyword_raw, ready_library_ids, exc, exc_info=True,
            )
            return [], [], {
                "code": "index_search_failed",
                "message": str(exc) or exc.__class__.__name__,
            }

    # ===== Phase 2：先跑索引（同步走 to_thread，不阻塞 event loop） =====
    # 设计原则：索引搜索是"快路径"，本地库存扫描（list_files / SYNO.Search）是"慢兜底"。
    # 两者不能并行——并行的话索引哪怕秒回，整体响应仍要等慢扫描，索引就失去意义了。
    # 流程：
    #   1) 先在所有 ready 的库里走索引（毫秒级 SQL）
    #   2) 命中任一条结果 → 立即返回，未就绪的库标 "skipped_index_hit"，不去扫描
    #   3) 索引一无所获 → 才把未就绪的库的 list_files 兜底跑起来
    try:
        rj_entries, name_entries, error_payload = await asyncio.to_thread(_run_phase2_index_sync)
    except Exception as exc:  # noqa: BLE001 - 极端兜底
        logger.warning(
            "[索引搜索] Phase 2 任务异常：keyword=%r err=%s",
            keyword_raw, exc, exc_info=True,
        )
        rj_entries, name_entries, error_payload = [], [], {
            "code": "index_search_failed",
            "message": str(exc) or exc.__class__.__name__,
        }

    # 索引挂了 → 把就绪库也丢回 fallback 候选（让兜底能覆盖它们）
    if error_payload is not None:
        for lid in ready_library_ids:
            if not any(str(x.get("id") or "") == lid for x in unready_library_infos):
                info = library_lookup.get(lid, {}) or {"id": lid}
                unready_library_infos.append(info)
                library_status_map[lid]["search_mode"] = "fallback"

    rj_hit_keys = {(e.library_id, e.relative_path) for e in rj_entries}
    seen_index: set[tuple[str, str]] = set()
    for entry in list(rj_entries) + list(name_entries):
        key = (entry.library_id, entry.relative_path)
        if key in seen_index:
            continue
        seen_index.add(key)
        info = library_lookup.get(entry.library_id, {})
        item = _index_entry_to_uniform_item(entry, info)
        index_items.append(_annotate_translation_search_item(item, translation_relation))

    owned_relation_items = _build_owned_translation_relation_items(
        translation_relation,
        library_lookup,
    )
    if owned_relation_items:
        index_items.extend(owned_relation_items)

    # ===== Phase 3：仅在索引一无所获时才跑兜底扫描 =====
    # - 索引命中（index_items 非空）：未就绪的库标 skipped_index_hit，**不扫描**
    # - 索引零结果 + 有未就绪库：才跑 list_files 兜底（远程走 SYNO.Search、本地走 os.walk）
    # - 没有未就绪库：自然没有 Phase 3
    fallback_items: list[Dict[str, Any]] = []
    fallback_attempted = False
    if not unready_library_infos:
        pass  # 全部库都已就绪，索引说啥就是啥
    elif normalized_mode == "suggest":
        for info in unready_library_infos:
            lid = str(info.get("id") or "")
            if lid in library_status_map:
                library_status_map[lid]["search_mode"] = "skipped_suggest"
                library_status_map[lid]["fallback_error"] = None
    elif index_items:
        # 索引已经给出答案 → 跳过慢扫描，让响应保持索引级速度
        for info in unready_library_infos:
            lid = str(info.get("id") or "")
            if lid in library_status_map:
                library_status_map[lid]["search_mode"] = "skipped_index_hit"
                library_status_map[lid]["fallback_error"] = None
    else:
        # 索引零命中，进入兜底扫描；并行 + 单库超时
        fallback_attempted = True
        try:
            results = await asyncio.gather(
                *[
                    _global_search_fallback_one_library(
                        manager,
                        info,
                        search_rjcodes or [keyword_raw],
                        normalized_entry_type,
                        fetch_limit,
                    )
                    for info in unready_library_infos
                ],
                return_exceptions=False,
            )
        except Exception as exc:  # noqa: BLE001 - 极端兜底
            logger.warning(
                "[索引搜索] 全部兜底搜索 gather 失败：keyword=%r err=%s",
                keyword_raw, exc, exc_info=True,
            )
            results = []
        for library_id_done, items_done, err in results:
            if library_id_done in library_status_map:
                library_status_map[library_id_done]["search_mode"] = (
                    "fallback_failed" if err else "fallback"
                )
                library_status_map[library_id_done]["fallback_error"] = err
            fallback_items.extend(
                _annotate_translation_search_item(item, translation_relation)
                for item in items_done
            )

    # ===== Phase 4：合并 + 去重 + 排序 + 裁剪 =====
    seen_global: set[tuple[str, str]] = set()
    merged_items: list[Dict[str, Any]] = []
    for item in index_items + fallback_items:
        # 优先用 (library_id, relative_path) 作为去重键；relative_path 可能为空时退回 absolute_path
        rel = item.get("relative_path") or item.get("absolute_path") or item.get("name") or ""
        key = (item.get("library_id") or "", str(rel))
        if key in seen_global:
            continue
        seen_global.add(key)
        merged_items.append(item)

    def _sort_item(item: Dict[str, Any]):
        rj_key = (item.get("library_id") or "", item.get("relative_path") or "")
        is_rj_hit = rj_key in rj_hit_keys or (
            matched_rjcode is not None
            and (item.get("rjcode") or "").upper() == matched_rjcode
        )
        relation_rank = 1 if item.get("search_match_type") == "related_translation" else 0
        is_dir = item.get("entry_type") == "dir"
        depth = item.get("depth")
        depth_val = depth if isinstance(depth, int) else 99
        # index 来源略优先于 fallback，给用户更稳定的 ranking
        is_index = item.get("source") == "index"
        name_lower = str(item.get("name") or "").lower()
        return (
            0 if is_rj_hit else 1,
            relation_rank,
            0 if is_index else 1,
            0 if is_dir else 1,
            depth_val,
            name_lower,
        )

    merged_items.sort(key=_sort_item)
    merged_items = _collapse_exact_rj_descendants(merged_items, matched_rjcode)
    truncated = len(merged_items) > capped_limit
    capped_items = merged_items[:capped_limit]

    library_status: list[Dict[str, Any]] = [library_status_map[lid] for lid in library_ids_list]

    response: Dict[str, Any] = {
        "items": capped_items,
        "count": len(capped_items),
        "total": len(merged_items),
        "limit": capped_limit,
        "truncated": truncated,
        "library_scope": library_ids_list,
        "library_status": library_status,
        "matched_rjcode": matched_rjcode,
        "related_rjcodes": list(translation_relation.get("related_rjcodes") or []),
        "search_relation_group": str(translation_relation.get("group_key") or ""),
        "search_relation_label": str(translation_relation.get("group_label") or ""),
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        "mode": normalized_mode,
        # 让前端区分：是否走过 fallback、有几个库走 fallback、有几个 fallback 失败
        "fallback_used": fallback_attempted,
        "fallback_failed": [
            entry["library_id"]
            for entry in library_status
            if entry.get("search_mode") == "fallback_failed"
        ],
    }
    if error_payload is not None:
        response["error"] = error_payload
    return response


@app.get("/api/library/index/global-search/stream")
async def global_search_library_index_stream(
    keyword: str = "",
    library_ids: Optional[str] = None,
    entry_type: str = "all",
    limit: int = _GLOBAL_INDEX_SEARCH_LIMIT_DEFAULT,
    mode: str = "full",
):
    """流式版本的跨库搜索：先把索引结果推回去，再把每个未就绪库的兜底扫描结果
    按完成顺序逐条推回，让前端在第一个库返回时就能看到结果，而不是等所有库扫完。

    NDJSON 协议（每行一个事件）：
    - {"type": "initial", "items": [...index 结果...], "library_status": [...],
       "matched_rjcode": "RJxxx", "elapsed_ms": N, "will_run_fallback": bool, ...}
    - {"type": "library", "library_id": "xxx", "items": [...该库 fallback 结果...],
       "error": null|"timeout"|"<exc>", "library_status": {...}, "elapsed_ms": N}
    - {"type": "done", "elapsed_ms": N, "fallback_used": bool, "fallback_failed": [...]}

    设计与同步版 /api/library/index/global-search 一致：本地索引为快路径，
    远程群晖库走 FileStation fallback；区别是 fallback 阶段改为流式推送，
    不再阻塞到全部完成才响应。
    """
    started_at = time.perf_counter()
    keyword_raw = (keyword or "").strip()
    normalized_mode = "suggest" if (mode or "").strip().lower() == "suggest" else "full"
    raw_limit = max(1, int(limit or _GLOBAL_INDEX_SEARCH_LIMIT_DEFAULT))
    if normalized_mode == "suggest":
        capped_limit = min(raw_limit, 20)
    else:
        capped_limit = min(raw_limit, _GLOBAL_INDEX_SEARCH_LIMIT_MAX)

    async def stream_events():
        # 空 keyword：直接发 done
        if not keyword_raw:
            yield json.dumps({
                "type": "done",
                "elapsed_ms": 0,
                "fallback_used": False,
                "fallback_failed": [],
            }) + "\n"
            return

        manager = get_library_manager()
        library_ids_list, scoped_libraries = _resolve_global_index_library_scope(
            manager, library_ids
        )
        library_lookup: Dict[str, Dict[str, Any]] = {
            str(item.get("id") or ""): item for item in scoped_libraries if item.get("id")
        }
        if not library_ids_list:
            yield json.dumps({
                "type": "initial",
                "items": [],
                "total": 0,
                "library_scope": [],
                "library_status": [],
                "matched_rjcode": None,
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                "mode": normalized_mode,
                "limit": capped_limit,
                "will_run_fallback": False,
            }) + "\n"
            yield json.dumps({
                "type": "done",
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                "fallback_used": False,
                "fallback_failed": [],
            }) + "\n"
            return

        service = get_library_index_service()
        normalized_entry_type = _normalize_global_index_entry_type(entry_type)
        matched_rjcode = _detect_global_index_rjcode(keyword_raw)
        translation_relation = await _resolve_global_index_translation_relation(matched_rjcode)
        search_rjcodes = list(translation_relation.get("search_rjcodes") or [])

        # === Phase 1：库就绪状态分组 ===
        library_status_map: Dict[str, Dict[str, Any]] = {}
        ready_library_ids: list[str] = []
        unready_library_infos: list[Dict[str, Any]] = []
        for lib_id in library_ids_list:
            info = library_lookup.get(lib_id, {})
            library_type = str(info.get("type") or "local")
            if library_type == "synology_filestation":
                library_status_map[lib_id] = {
                    "library_id": lib_id,
                    "library_name": info.get("name") or lib_id,
                    "library_type": library_type,
                    "index_status": "disabled",
                    "total_entries": 0,
                    "search_mode": "fallback_pending",
                    "fallback_error": None,
                }
                unready_library_infos.append(info or {"id": lib_id, "type": library_type})
                continue
            try:
                status_obj = service.get_status(lib_id)
            except Exception:  # noqa: BLE001
                status_obj = None
            index_status_name = status_obj.status if status_obj else "idle"
            library_status_map[lib_id] = {
                "library_id": lib_id,
                "library_name": info.get("name") or lib_id,
                "library_type": library_type,
                "index_status": index_status_name,
                "total_entries": int(getattr(status_obj, "total_entries", 0) or 0) if status_obj else 0,
                "search_mode": "index",
                "fallback_error": None,
            }
            if status_obj is not None and service.has_usable_snapshot(lib_id):
                ready_library_ids.append(lib_id)
            else:
                unready_library_infos.append(info or {"id": lib_id})
                library_status_map[lib_id]["search_mode"] = "fallback_pending"

        fetch_limit = min(_GLOBAL_INDEX_SEARCH_LIMIT_MAX, max(capped_limit * 3, capped_limit + 50))

        # === Phase 2：索引（毫秒级，跑在 to_thread） ===
        def _phase2_sync():
            if not ready_library_ids:
                return [], [], None
            scope_param: Any = ready_library_ids[0] if len(ready_library_ids) == 1 else ready_library_ids
            try:
                rj_inner: list[Any] = []
                name_inner: list[Any] = []
                if matched_rjcode:
                    if len(search_rjcodes) > 1 and hasattr(service, "find_by_rjcodes"):
                        rj_inner = service.find_by_rjcodes(
                            search_rjcodes,
                            scope_param,
                            entry_type="dir" if normalized_entry_type in (None, "dir") else normalized_entry_type,
                            limit=fetch_limit,
                        ) or []
                    else:
                        rj_inner = service.find_by_rjcode(
                            matched_rjcode,
                            scope_param,
                            entry_type="dir" if normalized_entry_type in (None, "dir") else normalized_entry_type,
                            limit=fetch_limit,
                        ) or []
                else:
                    name_inner = service.find_by_name(
                        scope_param,
                        keyword_raw,
                        entry_type=normalized_entry_type,
                        limit=fetch_limit,
                    ) or []
                return rj_inner, name_inner, None
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[索引搜索·流式] 索引查询失败：keyword=%r ready=%s err=%s",
                    keyword_raw, ready_library_ids, exc, exc_info=True,
                )
                return [], [], {
                    "code": "index_search_failed",
                    "message": str(exc) or exc.__class__.__name__,
                }

        try:
            rj_entries, name_entries, error_payload = await asyncio.to_thread(_phase2_sync)
        except Exception as exc:  # noqa: BLE001
            rj_entries, name_entries, error_payload = [], [], {
                "code": "index_search_failed",
                "message": str(exc) or exc.__class__.__name__,
            }

        # 索引整段挂了：把就绪库丢回 fallback 候选
        if error_payload is not None:
            for lid in ready_library_ids:
                if not any(str(x.get("id") or "") == lid for x in unready_library_infos):
                    info = library_lookup.get(lid, {}) or {"id": lid}
                    unready_library_infos.append(info)
                    library_status_map[lid]["search_mode"] = "fallback"

        # 合并 + 去重 + 排序索引结果
        rj_hit_keys = {(e.library_id, e.relative_path) for e in rj_entries}
        seen_global: set[tuple[str, str]] = set()
        index_items: list[Dict[str, Any]] = []
        for entry in list(rj_entries) + list(name_entries):
            key = (entry.library_id, entry.relative_path)
            if key in seen_global:
                continue
            seen_global.add(key)
            info = library_lookup.get(entry.library_id, {})
            item = _index_entry_to_uniform_item(entry, info)
            index_items.append(_annotate_translation_search_item(item, translation_relation))

        owned_relation_items = _build_owned_translation_relation_items(
            translation_relation,
            library_lookup,
        )
        for item in owned_relation_items:
            key = (item.get("library_id") or "", item.get("relative_path") or item.get("absolute_path") or "")
            if key in seen_global:
                continue
            seen_global.add(key)
            index_items.append(item)

        def _sort_item(item: Dict[str, Any]):
            rj_key = (item.get("library_id") or "", item.get("relative_path") or "")
            is_rj_hit = rj_key in rj_hit_keys or (
                matched_rjcode is not None
                and (item.get("rjcode") or "").upper() == matched_rjcode
            )
            relation_rank = 1 if item.get("search_match_type") == "related_translation" else 0
            is_dir = item.get("entry_type") == "dir"
            depth = item.get("depth")
            depth_val = depth if isinstance(depth, int) else 99
            is_index = item.get("source") == "index"
            name_lower = str(item.get("name") or "").lower()
            return (
                0 if is_rj_hit else 1,
                relation_rank,
                0 if is_index else 1,
                0 if is_dir else 1,
                depth_val,
                name_lower,
            )

        index_items.sort(key=_sort_item)
        index_items = _collapse_exact_rj_descendants(index_items, matched_rjcode)

        # 决定是否要跑 Phase 3：仅当索引零命中 + 有未就绪库
        will_run_fallback = bool(unready_library_infos) and not index_items
        if not will_run_fallback and unready_library_infos:
            # 索引有命中 → 标记跳过远程，不打扰用户
            for info in unready_library_infos:
                lid = str(info.get("id") or "")
                if lid in library_status_map:
                    library_status_map[lid]["search_mode"] = "skipped_index_hit"
                    library_status_map[lid]["fallback_error"] = None

        # ===== 推送 initial 事件（带索引结果） =====
        initial_event: Dict[str, Any] = {
            "type": "initial",
            "items": index_items[:capped_limit],
            "total": len(index_items),
            "truncated": len(index_items) > capped_limit,
            "library_scope": library_ids_list,
            "library_status": [library_status_map[lid] for lid in library_ids_list],
            "matched_rjcode": matched_rjcode,
            "related_rjcodes": list(translation_relation.get("related_rjcodes") or []),
            "search_relation_group": str(translation_relation.get("group_key") or ""),
            "search_relation_label": str(translation_relation.get("group_label") or ""),
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            "mode": normalized_mode,
            "limit": capped_limit,
            "will_run_fallback": will_run_fallback,
        }
        if error_payload is not None:
            initial_event["error"] = error_payload
        yield json.dumps(initial_event, ensure_ascii=False) + "\n"

        # 不需要兜底：done
        if not will_run_fallback:
            yield json.dumps({
                "type": "done",
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                "fallback_used": False,
                "fallback_failed": [],
            }, ensure_ascii=False) + "\n"
            return

        # ===== Phase 3：每个未就绪库各自独立扫描，按完成顺序流式推送 =====
        fallback_failed: list[str] = []
        # 用 task 关联回 library_info，便于在出错或取消时快速定位
        per_task_info: Dict[asyncio.Task, Dict[str, Any]] = {
            asyncio.create_task(
                _global_search_fallback_one_library(
                    manager,
                    info,
                    search_rjcodes or [keyword_raw],
                    normalized_entry_type,
                    fetch_limit,
                )
            ): info
            for info in unready_library_infos
        }
        try:
            for finished in asyncio.as_completed(list(per_task_info.keys())):
                try:
                    library_id_done, items_done, err = await finished
                except Exception as exc:  # noqa: BLE001
                    library_id_done, items_done, err = "", [], (str(exc) or "fallback_error")

                if library_id_done in library_status_map:
                    library_status_map[library_id_done]["search_mode"] = (
                        "fallback_failed" if err else "fallback"
                    )
                    library_status_map[library_id_done]["fallback_error"] = err
                    if err:
                        fallback_failed.append(library_id_done)

                # 去掉与索引结果 / 之前 fallback 重复的项
                deduped: list[Dict[str, Any]] = []
                for item in items_done:
                    rel = item.get("relative_path") or item.get("absolute_path") or item.get("name") or ""
                    key = (item.get("library_id") or "", str(rel))
                    if key in seen_global:
                        continue
                    seen_global.add(key)
                    deduped.append(item)

                yield json.dumps({
                    "type": "library",
                    "library_id": library_id_done,
                    "items": [
                        _annotate_translation_search_item(item, translation_relation)
                        for item in deduped
                    ],
                    "error": err,
                    "library_status": library_status_map.get(library_id_done),
                    "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                }, ensure_ascii=False) + "\n"
        finally:
            # 客户端断开 / generator 退出：cancel 还在跑的库扫描，避免后台空跑
            for t in per_task_info:
                if not t.done():
                    t.cancel()

        yield json.dumps({
            "type": "done",
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            "fallback_used": True,
            "fallback_failed": fallback_failed,
            "library_status": [library_status_map[lid] for lid in library_ids_list],
        }, ensure_ascii=False) + "\n"

    return StreamingResponse(
        stream_events(),
        media_type="application/x-ndjson",
        headers={
            # 避免代理 / 浏览器缓冲，让事件能尽快推到前端
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/library/browser/files")
async def browse_library_files(
    library_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
    search: str = "",
    current_path: Optional[str] = None,
    sort_by: str = "size",
    sort_order: str = "desc",
    force_refresh: bool = False,
    search_exact: bool = False,
    search_result_kind: str = "all",
    scope: str = "global",
    page_cursor: Optional[str] = None,
):
    """``scope`` 控制远程搜索范围：

    - ``global``（默认）：跨所有 active 远程库搜索 + 合并（库存页用，保留旧行为）
    - ``current``：只搜 ``library_id`` 指定的那一个远程库（picker 用，避免等最慢的库）
    """
    try:
        manager = get_library_manager()
        current_library = manager.get_library_definition(library_id)
        keyword = str(search or "").strip()
        scope_normalized = str(scope or "global").strip().lower()
        use_remote_global_search = (
            bool(keyword)
            and current_library.type == "synology_filestation"
            and scope_normalized != "current"
        )
        if use_remote_global_search:
            data = await manager.global_search_files(
                current_library.id,
                keyword,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
                page_cursor=page_cursor,
            )
            browse_root_path = current_library.browse_root_path or current_library.root_path
            display_current_path = current_path or browse_root_path
            data["browse_root_path"] = browse_root_path
            data["current_path"] = display_current_path
            normalized_browse_root = str(PurePosixPath(browse_root_path or "/"))
            normalized_current_path = str(PurePosixPath(display_current_path or normalized_browse_root))
            if normalized_current_path in {"", "."}:
                normalized_current_path = normalized_browse_root or "/"
            if normalized_current_path == normalized_browse_root:
                data["parent_path"] = None
            else:
                data["parent_path"] = str(PurePosixPath(normalized_current_path).parent)
        else:
            data = await manager.list_files(
                library_id,
                page=page,
                page_size=page_size,
                search=search,
                current_path=current_path,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
                page_cursor=page_cursor,
            )
        data["libraries"] = manager.list_libraries()
        data["library_id"] = data.get("library_id") or current_library.id
        if current_library.type == "local":
            data["index_view"] = _library_index_view(current_library.id)
        return data
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存浏览失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存浏览失败: {str(e)}")


@app.get("/api/library/browser/stats")
async def get_library_browser_stats(force_refresh: bool = False, library_id: Optional[str] = None):
    try:
        manager = get_library_manager()
        payload = await manager.ensure_stats(force=force_refresh, library_id=library_id)
        if library_id:
            library = manager.get_library_definition(library_id)
            if library.type == "local" and isinstance(payload, dict):
                payload["index_view"] = _library_index_view(library.id)
        elif isinstance(payload, dict):
            local_ids = [
                str(item.get("id") or "")
                for item in manager.list_libraries()
                if item.get("id") and item.get("type") == "local"
            ]
            index_views, view_token = _library_index_views(local_ids)
            payload["index_views"] = index_views
            payload["view_token"] = view_token
        return payload
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存统计失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存统计失败: {str(e)}")


@app.post("/api/library/browser/stats/cancel")
async def cancel_library_browser_stats(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少库存 ID")
        manager = get_library_manager()
        return await manager.cancel_stats(library_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消库存统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消库存统计失败: {str(e)}")


def _normalize_library_size_target(data: dict[str, Any]) -> dict[str, str]:
    return {
        "library_id": str(data.get("library_id") or data.get("libraryId") or "").strip(),
        "path": str(data.get("path") or "").strip(),
    }


def _optional_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def _compute_library_folder_size_target(
    manager,
    target: dict[str, str],
    *,
    include_counts: bool = False,
    max_entries: Optional[int] = None,
    max_seconds: Optional[float] = None,
) -> dict[str, Any]:
    library_id = str(target.get("library_id") or "").strip()
    folder_path = str(target.get("path") or "").strip()
    if not folder_path:
        return {
            "library_id": library_id,
            "path": folder_path,
            "success": False,
            "error": "缺少文件夹路径",
        }

    try:
        library = manager.get_library_definition(library_id or None)
        resolved_library_id = library.id
        if library_id and resolved_library_id != library_id:
            return {
                "library_id": library_id,
                "path": folder_path,
                "success": False,
                "error": "库存不存在",
            }
        if library.type == "synology_filestation":
            if not library.synology:
                return {
                    "library_id": resolved_library_id,
                    "path": folder_path,
                    "success": False,
                    "error": "远程库存缺少群晖连接配置",
                }
            normalized_path = manager._normalize_remote_path(folder_path)
            browse_root = manager._normalize_remote_path(library.browse_root_path or library.root_path or "/")
            if not manager._remote_path_is_within_root(normalized_path, browse_root):
                return {
                    "library_id": resolved_library_id,
                    "path": normalized_path,
                    "success": False,
                    "error": "文件夹不在当前库存范围内",
                }
            client = manager.get_cached_synology_client(library.synology)
            if include_counts:
                summary = await manager._remote_folder_summary(
                    client,
                    normalized_path,
                    max_entries=max_entries,
                    max_seconds=max_seconds,
                )
                return {
                    "library_id": resolved_library_id,
                    "path": normalized_path,
                    "success": True,
                    **summary,
                }
            size = await manager._remote_path_size(client, normalized_path, True, max_wait_seconds=300)
            return {
                "library_id": resolved_library_id,
                "path": normalized_path,
                "success": True,
                "size": size,
            }

        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        normalized_path = os.path.abspath(os.path.normpath(folder_path))
        if not manager._local_path_is_within_root(normalized_path, browse_root):
            return {
                "library_id": resolved_library_id,
                "path": normalized_path,
                "success": False,
                "error": "文件夹不在当前库存范围内",
            }
        if not os.path.isdir(normalized_path):
            return {
                "library_id": resolved_library_id,
                "path": normalized_path,
                "success": False,
                "error": "文件夹不存在",
            }
        indexed_summary = manager.folder_size_summary_via_index(
            library,
            normalized_path,
            include_counts=include_counts,
        )
        if indexed_summary is not None:
            return {
                "library_id": resolved_library_id,
                "path": normalized_path,
                "success": True,
                **indexed_summary,
            }
        manager._enqueue_index_read_repair_upserts(library, [normalized_path])
        pending_result = {
            "library_id": resolved_library_id,
            "path": normalized_path,
            "success": True,
            "size": None,
            "size_status": "pending",
            "index_refresh_pending": True,
            "browse_via_index": False,
            "partial": False,
            "scanned_entries": 0,
        }
        if include_counts:
            pending_result.update({
                "file_count": 0,
                "folder_count": 0,
                "count_status": "pending",
            })
        return pending_result
    except Exception as exc:
        return {
            "library_id": library_id,
            "path": folder_path,
            "success": False,
            "error": str(exc),
        }


@app.post("/api/library/browser/compute-folder-size")
async def compute_folder_size(request: Request):
    """手动计算并缓存指定文件夹的大小（供社团目录右键菜单触发）。"""
    try:
        data = await request.json()
        manager = get_library_manager()
        target = _normalize_library_size_target(data)
        result = await _compute_library_folder_size_target(
            manager,
            target,
            include_counts=bool(data.get("include_counts") or data.get("includeCounts")),
            max_entries=_optional_positive_int(data.get("max_entries") or data.get("maxEntries")),
            max_seconds=_optional_positive_float(data.get("max_seconds") or data.get("maxSeconds")),
        )
        if not result.get("success"):
            status_code = 404 if result.get("error") == "文件夹不存在" else 400
            raise HTTPException(status_code=status_code, detail=result.get("error") or "计算文件夹大小失败")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"计算文件夹大小失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"计算文件夹大小失败: {str(e)}")


@app.post("/api/library/browser/compute-folder-sizes")
async def compute_folder_sizes(request: Request):
    """批量计算并缓存文件夹大小，减少库存页右键批量操作的 HTTP 往返。"""
    try:
        data = await request.json()
        raw_items = data.get("items")
        targets = []
        include_counts = bool(data.get("include_counts") or data.get("includeCounts"))
        max_entries = _optional_positive_int(data.get("max_entries") or data.get("maxEntries"))
        max_seconds = _optional_positive_float(data.get("max_seconds") or data.get("maxSeconds"))
        if isinstance(raw_items, list) and raw_items:
            for raw_item in raw_items:
                if isinstance(raw_item, dict):
                    target = _normalize_library_size_target(raw_item)
                    if target.get("path"):
                        targets.append(target)
        else:
            paths = data.get("paths") or []
            if not isinstance(paths, list) or not paths:
                raise HTTPException(status_code=400, detail="缺少文件夹路径列表")
            library_id = str(data.get("library_id") or "").strip()
            for raw_path in paths:
                folder_path = str(raw_path or "").strip()
                if not folder_path:
                    continue
                targets.append({"library_id": library_id, "path": folder_path})

        if not targets:
            raise HTTPException(status_code=400, detail="缺少有效文件夹路径")

        manager = get_library_manager()
        results = []
        for target in targets:
            results.append(await _compute_library_folder_size_target(
                manager,
                target,
                include_counts=include_counts,
                max_entries=max_entries,
                max_seconds=max_seconds,
            ))
        success_count = sum(1 for item in results if item.get("success"))
        failed_count = len(results) - success_count
        return {
            "message": "批量计算文件夹大小完成",
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量计算文件夹大小失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量计算文件夹大小失败: {str(e)}")


@app.get("/api/library/browser/stats/logs")
async def get_library_browser_stats_logs(library_id: Optional[str] = None, lines: int = 200):
    try:
        manager = get_library_manager()
        return await asyncio.to_thread(manager.read_stats_logs, library_id=library_id, lines=lines)
    except Exception as e:
        logger.error("获取库存统计日志失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"获取库存统计日志失败: {str(e)}")


@app.post("/api/library/browser/folder-contents")
async def get_library_browser_folder_contents(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        recursive = data.get("recursive", True)
        prefer_index = data.get("prefer_index", True)
        include_dirs = data.get("include_dirs", False)
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        manager = get_library_manager()
        payload = await manager.folder_contents(
            library_id,
            folder_path,
            recursive=bool(recursive),
            prefer_index=bool(prefer_index),
            include_dirs=bool(include_dirs),
        )
        library = manager.get_library_definition(library_id)
        if library.type == "local":
            payload["index_view"] = _library_index_view(library.id)
        return payload
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"获取库存文件夹内容失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"获取库存文件夹内容失败: {str(e)}")


class LibraryListSubdirectoriesRequest(BaseModel):
    """列出库存路径下一级子目录请求"""
    library_id: str
    path: Optional[str] = ""


class LibraryFolderCompletionPreviewRequest(BaseModel):
    """库存页“补全文件夹”检查请求。"""
    library_id: str
    selected_paths: List[str] = []


class LibraryFolderCompletionStartRequest(BaseModel):
    """库存页“补全文件夹”启动请求。"""
    library_id: str
    items: List[dict] = []


@app.post("/api/library/list-subdirectories")
async def list_library_subdirectories(request: LibraryListSubdirectoriesRequest):
    """列出指定库存路径下一级子目录（不递归）。"""
    if not str(request.library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少 library_id")
    try:
        manager = get_library_manager()
        return await manager.list_first_level_directories(request.library_id, request.path)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"列子目录失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"列子目录失败: {str(e)}")


@app.post("/api/library/folder-completion/preview")
async def preview_library_folder_completion(request: LibraryFolderCompletionPreviewRequest):
    from ..core.library_folder_completion_service import get_library_folder_completion_service

    try:
        return await get_library_folder_completion_service().build_preview(
            request.library_id,
            list(request.selected_paths or []),
        )
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("库存补全文件夹检查失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存补全文件夹检查失败: {str(e)}")


@app.post("/api/library/folder-completion/preview/start")
async def start_library_folder_completion_preview(request: LibraryFolderCompletionPreviewRequest):
    from ..core.task_engine import Task, TaskStatus, TaskType, get_task_engine

    try:
        selected_paths = [str(path or "").strip() for path in list(request.selected_paths or []) if str(path or "").strip()]
        if not request.library_id:
            raise ValueError("缺少库存")
        if not selected_paths:
            raise ValueError("没有选中要补全的目录")
        task = Task(
            task_type=TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW,
            source_path=selected_paths[0],
            auto_classify=False,
            metadata={
                "library_id": request.library_id,
                "selected_paths": selected_paths,
                "selected_count": len(selected_paths),
                "task_domain": "asmr_sync",
                "source_page": "library",
                "source_action": "folder_completion",
                "source_label": "音声补全 / 补全文件夹检查",
                "business_key": f"{request.library_id}:folder_completion_preview:{uuid.uuid4().hex[:8]}",
            },
        )
        task.ensure_business_context("asmr_sync", {
            "source_page": "library",
            "source_action": "folder_completion",
            "source_label": "音声补全 / 补全文件夹检查",
            "business_key": task.task_metadata["business_key"],
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("启动库存补全文件夹检查任务失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动库存补全文件夹检查任务失败: {str(e)}")


@app.get("/api/library/folder-completion/preview/jobs/{job_id}")
async def get_library_folder_completion_preview_job(job_id: str):
    from ..core.task_engine import TaskType, get_task_engine

    task = get_task_engine().get_task(job_id)
    if not task or task.type != TaskType.LIBRARY_FOLDER_COMPLETION_PREVIEW:
        raise HTTPException(status_code=404, detail="补全文件夹检查任务不存在")
    metadata = dict(task.task_metadata or {})
    return {
        "success": True,
        "job_id": task.id,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status or ""),
        "progress": int(task.progress or 0),
        "current_step": task.current_step,
        "error_message": task.error_message,
        "result": metadata.get("folder_completion_preview_result") or {},
        "summary": metadata.get("folder_completion_summary") or {},
        "selected_count": int(metadata.get("selected_count") or 0),
        "downloadable_count": int(metadata.get("downloadable_count") or 0),
        "missing_file_count": int(metadata.get("missing_file_count") or 0),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@app.post("/api/library/folder-completion/start")
async def start_library_folder_completion(request: LibraryFolderCompletionStartRequest):
    from ..core.library_folder_completion_service import get_library_folder_completion_service

    try:
        return await get_library_folder_completion_service().start_downloads(
            request.library_id,
            list(request.items or []),
        )
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("启动库存补全文件夹任务失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动库存补全文件夹任务失败: {str(e)}")


@app.post("/api/library/browser/mojibake-preview")
async def get_library_browser_mojibake_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        selected_paths = data.get("selected_paths") or []
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        manager = get_library_manager()
        return await manager.preview_mojibake_repairs(library_id, folder_path, selected_paths=selected_paths)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"获取乱码修复预览失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取乱码修复预览失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview")
async def get_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        target_items = data.get("target_items") if isinstance(data.get("target_items"), list) else None
        request_id = data.get("request_id")
        rules = data.get("rules")
        if not folder_path and not target_items:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        try:
            return await manager.filter_delete_preview(library_id, folder_path, rules=rules, request_id=request_id, target_items=target_items)
        finally:
            manager._finish_filter_preview_request(request_id)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"过滤删除预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"过滤删除预览失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/start")
async def start_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        target_items = data.get("target_items") if isinstance(data.get("target_items"), list) else None
        rules = data.get("rules")
        if not folder_path and not target_items:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        return await manager.start_filter_delete_preview_job(library_id, folder_path, rules=rules, target_items=target_items)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"启动过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动过滤删除预审失败: {str(e)}")


@app.get("/api/library/browser/filter-delete-preview/status")
async def get_library_browser_filter_delete_preview_status(job_id: str):
    try:
        manager = get_library_manager()
        return manager.get_filter_delete_preview_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except Exception as e:
        _log_synology_err(f"获取过滤删除预审状态失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取过滤删除预审状态失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/cancel")
async def cancel_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        request_id = data.get("request_id")
        job_id = data.get("job_id")
        manager = get_library_manager()
        if job_id:
            return await manager.cancel_filter_delete_preview_job(job_id)
        return manager.cancel_filter_delete_preview(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消过滤删除预审失败: {str(e)}")


@app.post("/api/library/browser/create-folder")
async def create_library_browser_folder(request: Request):
    prepared = None
    mutation_service = None
    try:
        data = await request.json()
        library_id = str(data.get("library_id") or "").strip()
        parent_path = str(data.get("parent_path") or "").strip()
        name = str(data.get("name") or "").strip()
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少 library_id")
        if not name:
            raise HTTPException(status_code=400, detail="请输入文件夹名称")

        manager = get_library_manager()
        library, _, target_path, _ = manager.resolve_create_folder_target(
            library_id,
            parent_path or None,
            name,
        )
        mutation_effect = None
        if library.type == "local":
            mutation_effect = {
                "kind": "upsert",
                "relative_path": _local_relative_path(library, target_path),
                "scope": "subtree",
            }
            mutation_service = get_library_index_mutation_service()
            prepared = mutation_service.prepare(
                kind="create_folder",
                effects_by_library={library.id: [mutation_effect]},
                idempotency_key=_request_idempotency_key(request),
            )
            replay = _prepared_replay_response(prepared)
            if replay is not None:
                return replay

        try:
            if prepared is not None:
                mutation_service.mark_filesystem_started(prepared.operation_id)
            result = await manager.create_folder(
                library_id,
                parent_path or None,
                name,
                skip_index_mutation=prepared is not None,
            )
            _invalidate_rj_subtitle_folder_summary_cache(library_id)
        except Exception as exc:
            if prepared is not None:
                mutation_service.fail_prepared(prepared.operation_id, exc)
            raise

        if prepared is not None:
            try:
                result = mutation_service.finalize(
                    prepared.operation_id,
                    actual_effects_by_library={library.id: [mutation_effect]},
                    actual_result=result,
                )
            except Exception as exc:
                mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                return JSONResponse(
                    status_code=202,
                    content={
                        **result,
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
        return result
    except HTTPException:
        raise
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log_synology_err(f"新建库存文件夹失败: {exc}", exc)
        raise HTTPException(
            status_code=_synology_http_status(exc),
            detail=f"新建文件夹失败: {str(exc)}",
        )


@app.post("/api/library/browser/rename")
async def rename_library_browser_item(request: Request):
    path = ""
    new_name = ""
    library_id = None
    skip_activity_log = False
    batch_id = ""
    rename_context = ""
    prepared = None
    mutation_service = None
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        new_name = str(data.get("new_name") or "").strip()
        library_id = data.get("library_id")
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        rename_context = str(data.get("rename_context") or "").strip()
        skip_index_mutation = bool(data.get("skip_index_mutation"))
        if not path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if not skip_index_mutation else None
        planned_effects = []
        if library is not None and library.type == "local":
            new_path = os.path.join(os.path.dirname(path), new_name)
            scope = "subtree" if os.path.isdir(path) else "exact"
            planned_effects = [
                {
                    "kind": "move",
                    "relative_path": _local_relative_path(library, path),
                    "scope": scope,
                    "target_library_id": library.id,
                    "target_path": _local_relative_path(library, new_path),
                },
                {
                    "kind": "reconcile",
                    "relative_path": _local_relative_path(library, new_path),
                    "scope": scope,
                },
            ]
            mutation_service = get_library_index_mutation_service()
            prepared = mutation_service.prepare(
                kind="rename",
                effects_by_library={library.id: planned_effects},
                idempotency_key=_request_idempotency_key(request),
            )
            replay = _prepared_replay_response(prepared)
            if replay is not None:
                return replay
        try:
            if prepared is not None:
                mutation_service.mark_filesystem_started(prepared.operation_id)
            result = await manager.rename(
                library_id,
                path,
                new_name,
                skip_index_mutation=skip_index_mutation or prepared is not None,
                sync_index_mutation=False,
            )
            _invalidate_rj_subtitle_folder_summary_cache(library_id)
        except Exception as exc:
            if prepared is not None:
                mutation_service.fail_prepared(prepared.operation_id, exc)
            raise
        if prepared is not None:
            try:
                result = mutation_service.finalize(
                    prepared.operation_id,
                    actual_effects_by_library={library.id: planned_effects},
                    actual_result=result,
                )
            except Exception as exc:
                mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                return JSONResponse(
                    status_code=202,
                    content={
                        **result,
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
        try:
            from ..core.activity_log_service import log_api_rename_action
            if not skip_activity_log:
                new_path = str(result.get("new_path") or result.get("path") or "").strip() if isinstance(result, dict) else ""
                log_api_rename_action(
                    action="rename",
                    success=True,
                    source_path=path,
                    new_path=new_path,
                    old_name=_route_path_basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=_route_path_basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名失败记录失败", exc_info=True)
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存重命名失败: {e}", e)
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=_route_path_basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存重命名失败: {str(e)}")


@app.post("/api/library/browser/batch-rename")
async def batch_rename_library_browser_items(request: Request):
    prepared = None
    mutation_service = None
    try:
        data = await request.json()
        library_id = data.get("library_id")
        items = data.get("items") or []
        skip_activity_log = bool(data.get("skip_activity_log"))
        requested_batch_id = str(data.get("batch_id") or "").strip()
        rename_context = str(data.get("rename_context") or "").strip()
        skip_index_mutation = bool(data.get("skip_index_mutation"))
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="缺少批量重命名项")

        from ..core.activity_log_service import log_api_rename_action, log_batch_manual_rename_result

        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if not skip_index_mutation else None
        batch_prefix = "mojibake" if rename_context == "folder_contents_mojibake_repair" else "manual-rename"
        batch_id = requested_batch_id or f"{batch_prefix}-{uuid.uuid4().hex}"
        normalized_items: list[dict[str, str]] = []
        item_lookup: dict[int, dict] = {}
        invalid_results: list[dict] = []

        for index, item in enumerate(items):
            item = item or {}
            source_path = str(item.get("path") or "").strip()
            new_name = str(item.get("new_name") or "").strip()
            current_name = str(item.get("current_name") or _route_path_basename(source_path) or "").strip()
            item_lookup[index] = {
                "path": source_path,
                "new_name": new_name,
                "current_name": current_name,
            }
            if not source_path or not new_name or new_name == current_name:
                invalid_results.append({
                    "index": index,
                    "path": source_path,
                    "source_path": source_path,
                    "old_name": current_name,
                    "new_name": new_name,
                    "success": False,
                    "error": "目标名称无效或无变化",
                })
                continue
            normalized_items.append({
                "index": index,
                "path": source_path,
                "new_name": new_name,
                "current_name": current_name,
            })

        planned_effects_by_index: dict[int, list[dict[str, Any]]] = {}
        if library is not None and library.type == "local":
            for item in normalized_items:
                source_path = str(item["path"])
                target_path = os.path.join(os.path.dirname(source_path), str(item["new_name"]))
                scope = "subtree" if os.path.isdir(source_path) else "exact"
                relative_target = _local_relative_path(library, target_path)
                planned_effects_by_index[int(item["index"])] = [
                    {
                        "kind": "move",
                        "relative_path": _local_relative_path(library, source_path),
                        "scope": scope,
                        "target_library_id": library.id,
                        "target_path": relative_target,
                    },
                    {
                        "kind": "reconcile",
                        "relative_path": relative_target,
                        "scope": scope,
                    },
                ]
            if planned_effects_by_index:
                mutation_service = get_library_index_mutation_service()
                prepared = mutation_service.prepare(
                    kind="batch_rename",
                    effects_by_library={
                        library.id: [
                            effect
                            for effects in planned_effects_by_index.values()
                            for effect in effects
                        ]
                    },
                    idempotency_key=_request_idempotency_key(request),
                )
                replay = _prepared_replay_response(prepared)
                if replay is not None:
                    return replay

        try:
            if prepared is not None:
                mutation_service.mark_filesystem_started(prepared.operation_id)
            batch_result = await manager.batch_rename(
                library_id,
                normalized_items,
                skip_index_mutation=skip_index_mutation or prepared is not None,
                sync_index_mutation=False if prepared is not None else not skip_index_mutation,
            )
        except Exception as exc:
            if prepared is not None:
                mutation_service.fail_prepared(prepared.operation_id, exc)
            raise
        raw_success_results = list(batch_result.get("results") or [])
        raw_failed_results = list(batch_result.get("failed") or [])
        if raw_success_results:
            _invalidate_rj_subtitle_folder_summary_cache(library_id)

        results: list[dict] = []
        for item in raw_success_results:
            index = int(item.get("index") or 0)
            request_item = item_lookup.get(index, {})
            results.append({
                "index": index,
                "path": str(item.get("path") or request_item.get("path") or "").strip(),
                "source_path": str(item.get("source_path") or request_item.get("path") or "").strip(),
                "old_name": str(request_item.get("current_name") or _route_path_basename(item.get("path")) or "").strip(),
                "new_name": str(item.get("new_name") or request_item.get("new_name") or "").strip(),
                "new_path": str(item.get("new_path") or "").strip(),
                "success": True,
            })

        failed_items: list[dict] = []
        for item in raw_failed_results:
            index = int(item.get("index") or 0)
            request_item = item_lookup.get(index, {})
            failed_items.append({
                "index": index,
                "path": str(item.get("path") or request_item.get("path") or "").strip(),
                "source_path": str(item.get("source_path") or request_item.get("path") or "").strip(),
                "old_name": str(request_item.get("current_name") or _route_path_basename(item.get("path")) or "").strip(),
                "new_name": str(item.get("new_name") or request_item.get("new_name") or "").strip(),
                "success": False,
                "error": str(item.get("error") or "重命名失败"),
            })
        failed_items.extend(invalid_results)
        results.extend(failed_items)
        results.sort(key=lambda item: int(item.get("index") or 0))

        success_count = len([item for item in results if item.get("success")])
        failed_count = len([item for item in results if not item.get("success")])

        if not skip_activity_log:
            for item in results:
                log_api_rename_action(
                    action="batch_rename_item",
                    success=bool(item.get("success")),
                    source_path=str(item.get("path") or item.get("source_path") or "").strip(),
                    new_path=str(item.get("new_path") or "").strip() or None,
                    old_name=str(item.get("old_name") or "").strip(),
                    new_name=str(item.get("new_name") or "").strip(),
                    batch_id=batch_id,
                    library_id=str(library_id or "") or None,
                    error=str(item.get("error") or "").strip() or None,
                    status="failed" if not item.get("success") else "success",
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
            log_batch_manual_rename_result(
                batch_id=batch_id,
                total_count=len(items),
                success_count=success_count,
                failed_count=failed_count,
                results=results,
                source_path=str(data.get("path") or (results[0].get("path") if results else "") or "").strip(),
                rename_context=rename_context,
            )
        response = {
            "batch_id": batch_id,
            "success_count": success_count,
            "failed_count": failed_count,
            "failed": [item for item in results if not item.get("success")],
            "failed_items": [item for item in results if not item.get("success")],
            "results": results,
        }
        if prepared is not None:
            actual_effects = [
                effect
                for item in results
                if item.get("success") and int(item.get("index") or 0) in planned_effects_by_index
                for effect in planned_effects_by_index[int(item.get("index") or 0)]
            ]
            try:
                response = mutation_service.finalize(
                    prepared.operation_id,
                    actual_effects_by_library={library.id: actual_effects} if actual_effects else {},
                    actual_result=response,
                )
            except Exception as exc:
                mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                return JSONResponse(
                    status_code=202,
                    content={
                        **response,
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
        return response
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存批量重命名失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量重命名失败: {str(e)}")


@app.post("/api/library/browser/index-move-batch")
async def notify_library_browser_index_move_batch(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        moves = data.get("moves") or []
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少库存 ID")
        if not isinstance(moves, list) or not moves:
            raise HTTPException(status_code=400, detail="缺少索引移动项")
        manager = get_library_manager()
        return manager.notify_index_move_batch(library_id, moves)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("调度库存索引移动失败: %s", sanitize_text_for_log(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"调度库存索引移动失败: {str(e)}")


@app.post("/api/library/browser/delete")
async def delete_library_browser_item(request: Request):
    path = ""
    library_id = None
    skip_activity_log = False
    batch_id = ""
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="缺少路径")
        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        prepared = None
        mutation_effect = None
        if confirmed and library.type == "local":
            service = get_library_index_mutation_service()
            mutation_effect = {
                "kind": "delete",
                "relative_path": _local_relative_path(library, path),
                "scope": "subtree" if os.path.isdir(path) else "exact",
            }
            prepared = service.prepare(
                kind="delete",
                effects_by_library={library.id: [mutation_effect]},
                idempotency_key=_request_idempotency_key(request),
            )
            replay = _prepared_replay_response(prepared)
            if replay is not None:
                return replay
        try:
            if prepared is not None:
                service.mark_filesystem_started(prepared.operation_id)
            result = await manager.delete(
                library_id,
                path,
                confirmed=confirmed,
                skip_index_mutation=prepared is not None,
            )
            if confirmed:
                _invalidate_rj_subtitle_folder_summary_cache(library_id)
        except Exception as exc:
            if prepared is not None:
                service.fail_prepared(prepared.operation_id, exc)
            raise
        if prepared is not None:
            try:
                result = service.finalize(
                    prepared.operation_id,
                    actual_effects_by_library={library.id: [mutation_effect]},
                    actual_result=result,
                )
            except Exception as exc:
                service.mark_reconcile_required(prepared.operation_id, exc)
                return JSONResponse(
                    status_code=202,
                    content={
                        **result,
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
        try:
            from ..core.activity_log_service import log_api_delete_action
            if confirmed and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=True,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="dir" if str(result.get("type") or "").strip() == "folder" else "file",
                    library_id=str(library_id or "") or None,
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除失败记录失败", exc_info=True)
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存删除失败: {e}", e)
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存删除失败: {str(e)}")


@app.post("/api/library/browser/batch-delete")
async def batch_delete_library_browser_items(request: Request):
    paths: list[str] = []
    library_id = None
    skip_activity_log = False
    batch_id = ""
    try:
        data = await request.json()
        paths = [str(p or "").strip() for p in (data.get("paths") or []) if str(p or "").strip()]
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        known_items = data.get("known_items") if isinstance(data.get("known_items"), list) else []
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        prepared = None
        planned_effects = []
        if confirmed and library.type == "local":
            planned_effects = [
                {
                    "kind": "delete",
                    "relative_path": _local_relative_path(library, path),
                    "scope": "subtree" if os.path.isdir(path) else "exact",
                }
                for path in paths
            ]
            mutation_service = get_library_index_mutation_service()
            prepared = mutation_service.prepare(
                kind="batch_delete",
                effects_by_library={library.id: planned_effects},
                idempotency_key=_request_idempotency_key(request),
            )
            replay = _prepared_replay_response(prepared)
            if replay is not None:
                return replay
        try:
            if prepared is not None:
                mutation_service.mark_filesystem_started(prepared.operation_id)
            result = await manager.batch_delete(
                library_id,
                paths,
                confirmed=confirmed,
                skip_index_mutation=prepared is not None,
            )
            if confirmed and int((result or {}).get("success_count") or 0) > 0:
                _invalidate_rj_subtitle_folder_summary_cache(library_id)
        except Exception as exc:
            if prepared is not None:
                mutation_service.fail_prepared(prepared.operation_id, exc)
            raise
        if confirmed and isinstance(result, dict):
            failed_paths = result.get("failed_paths") or []
            failed_set = {
                str((item or {}).get("path") or "").strip()
                for item in failed_paths
                if isinstance(item, dict)
            }
            result["success_paths"] = [path for path in paths if path not in failed_set]
            result["failed_paths"] = failed_paths
            result["index_mutation_queued"] = int(result.get("success_count") or 0) > 0
            if batch_id:
                result["batch_id"] = batch_id
            if prepared is not None:
                success_set = set(result.get("success_paths") or [])
                actual_effects = [
                    effect
                    for path, effect in zip(paths, planned_effects)
                    if path in success_set
                ]
                try:
                    result = mutation_service.finalize(
                        prepared.operation_id,
                        actual_effects_by_library=(
                            {library.id: actual_effects} if actual_effects else {}
                        ),
                        actual_result=result,
                    )
                except Exception as exc:
                    mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                    return JSONResponse(
                        status_code=202,
                        content={
                            **result,
                            "operation_id": prepared.operation_id,
                            "operation_state": "reconcile_required",
                            "reconciliation_pending": True,
                        },
                    )
        try:
            from ..core.activity_log_service import log_api_delete_action, log_batch_api_delete_result
            if confirmed and isinstance(result, dict) and not skip_activity_log:
                batch_id = batch_id or str(uuid.uuid4())
                success_count = int(result.get("success_count") or 0)
                failed_paths = result.get("failed_paths") or []
                failed_count = len(failed_paths) if isinstance(failed_paths, list) else 0
                per_item_results = []

                failed_map = {}
                if isinstance(failed_paths, list):
                    for item in failed_paths:
                        p = str((item or {}).get("path") or "").strip()
                        if p:
                            failed_map[p] = str((item or {}).get("error") or "").strip()
                known_lookup = {}
                for item in known_items:
                    if not isinstance(item, dict):
                        continue
                    item_path = str(item.get("path") or "").strip()
                    if item_path:
                        known_lookup[item_path] = item

                for p in paths:
                    err = failed_map.get(p, "")
                    ok = not bool(err)
                    known = known_lookup.get(p, {})
                    item_name = str(known.get("name") or os.path.basename(p) or "").strip()
                    item_type = str(known.get("type") or known.get("item_type") or "unknown").strip() or "unknown"
                    log_api_delete_action(
                        action="batch_delete_item",
                        success=ok,
                        source_path=p,
                        item_name=item_name,
                        item_type=item_type,
                        library_id=str(library_id or "") or None,
                        error=err,
                        batch_id=batch_id,
                    )
                    per_item_results.append({
                        "path": p,
                        "success": ok,
                        "error": err,
                    })

                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=success_count,
                    failed_count=failed_count,
                    results=per_item_results,
                    source_path=paths[0] if paths else "",
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除记录失败", exc_info=True)
        return result
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存批量删除失败: {e}", e)
        try:
            from ..core.activity_log_service import log_batch_api_delete_result
            if paths and not skip_activity_log:
                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=0,
                    failed_count=len(paths),
                    results=[{"path": p, "success": False, "error": str(e)} for p in paths],
                    source_path=paths[0],
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量删除失败: {str(e)}")


@app.post("/api/library/browser/batch-delete-targets")
async def batch_delete_library_browser_targets(request: Request):
    targets: list[dict[str, Any]] = []
    skip_activity_log = False
    batch_id = ""
    try:
        data = await request.json()
        raw_targets = data.get("targets") if isinstance(data.get("targets"), list) else []
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            library_id = str(item.get("library_id") or "").strip()
            path = str(item.get("path") or item.get("delete_path") or "").strip()
            if library_id and path:
                targets.append({"library_id": library_id, "path": path})
        confirmed = data.get("confirmed", False)
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        known_items = data.get("known_items") if isinstance(data.get("known_items"), list) else []
        if not targets:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        manager = get_library_manager()
        prepared = None
        mutation_service = None
        planned_effects_by_target: dict[tuple[str, str], dict[str, Any]] = {}
        if confirmed:
            planned_by_library: dict[str, list[dict[str, Any]]] = {}
            for target in targets:
                library = manager.get_library_definition(target["library_id"])
                if library.type != "local":
                    continue
                path = target["path"]
                effect = {
                    "kind": "delete",
                    "relative_path": _local_relative_path(library, path),
                    "scope": "subtree" if os.path.isdir(path) else "exact",
                }
                key = (library.id, os.path.normcase(os.path.abspath(path)))
                planned_effects_by_target[key] = effect
                planned_by_library.setdefault(library.id, []).append(effect)
            if planned_by_library:
                mutation_service = get_library_index_mutation_service()
                prepared = mutation_service.prepare(
                    kind="batch_delete_targets",
                    effects_by_library=planned_by_library,
                    idempotency_key=_request_idempotency_key(request),
                )
                replay = _prepared_replay_response(prepared)
                if replay is not None:
                    return replay
        try:
            if prepared is not None:
                mutation_service.mark_filesystem_started(prepared.operation_id)
            result = await manager.batch_delete_targets(
                targets,
                confirmed=confirmed,
                skip_index_mutation=prepared is not None,
            )
            if confirmed:
                for item in list((result or {}).get("success_paths") or []):
                    if isinstance(item, dict):
                        _invalidate_rj_subtitle_folder_summary_cache(item.get("library_id"))
        except Exception as exc:
            if prepared is not None:
                mutation_service.fail_prepared(prepared.operation_id, exc)
            raise
        if confirmed and isinstance(result, dict):
            success_targets = result.get("success_paths") or []
            result["index_mutation_queued"] = int(result.get("success_count") or 0) > 0
            if batch_id:
                result["batch_id"] = batch_id
            try:
                from ..core.activity_log_service import log_api_delete_action, log_batch_api_delete_result
                if not skip_activity_log:
                    batch_id = batch_id or str(uuid.uuid4())
                    failed_paths = result.get("failed_paths") or []
                    failed_count = len(failed_paths) if isinstance(failed_paths, list) else 0
                    failed_map = {}
                    for item in (failed_paths if isinstance(failed_paths, list) else []):
                        if not isinstance(item, dict):
                            continue
                        key = f"{item.get('library_id') or ''}::{item.get('path') or ''}"
                        failed_map[key] = str(item.get("error") or "").strip()
                    known_lookup = {}
                    for item in known_items:
                        if not isinstance(item, dict):
                            continue
                        key = f"{item.get('library_id') or ''}::{item.get('path') or item.get('delete_path') or ''}"
                        if key.strip(":"):
                            known_lookup[key] = item
                    per_item_results = []
                    for target in targets:
                        key = f"{target['library_id']}::{target['path']}"
                        err = failed_map.get(key, "")
                        known = known_lookup.get(key, {})
                        ok = not bool(err)
                        log_api_delete_action(
                            action="batch_delete_item",
                            success=ok,
                            source_path=target["path"],
                            item_name=str(known.get("name") or os.path.basename(target["path"]) or "").strip(),
                            item_type=str(known.get("type") or known.get("item_type") or "unknown").strip() or "unknown",
                            library_id=target["library_id"],
                            error=err,
                            batch_id=batch_id,
                        )
                        per_item_results.append({
                            "library_id": target["library_id"],
                            "path": target["path"],
                            "success": ok,
                            "error": err,
                        })
                    log_batch_api_delete_result(
                        batch_id=batch_id,
                        total_count=len(targets),
                        success_count=int(result.get("success_count") or 0),
                        failed_count=failed_count,
                        results=per_item_results,
                        source_path=targets[0]["path"] if targets else "",
                    )
                    result["success_paths"] = success_targets
            except Exception:
                logger.debug("[操作记录] 跨库存批量删除记录失败", exc_info=True)
            if prepared is not None:
                actual_by_library: dict[str, list[dict[str, Any]]] = {}
                for item in success_targets:
                    if not isinstance(item, dict):
                        continue
                    library_id = str(item.get("library_id") or "").strip()
                    path = str(item.get("path") or "").strip()
                    if not library_id or not path:
                        continue
                    effect = planned_effects_by_target.get(
                        (library_id, os.path.normcase(os.path.abspath(path)))
                    )
                    if effect is not None:
                        actual_by_library.setdefault(library_id, []).append(effect)
                try:
                    result = mutation_service.finalize(
                        prepared.operation_id,
                        actual_effects_by_library=actual_by_library,
                        actual_result=result,
                    )
                except Exception as exc:
                    mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                    return JSONResponse(
                        status_code=202,
                        content={
                            **result,
                            "operation_id": prepared.operation_id,
                            "operation_state": "reconcile_required",
                            "reconciliation_pending": True,
                        },
                    )
        return result
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"跨库存批量删除失败: {e}", e)
        try:
            from ..core.activity_log_service import log_batch_api_delete_result
            if targets and not skip_activity_log:
                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(targets),
                    success_count=0,
                    failed_count=len(targets),
                    results=[{"library_id": item["library_id"], "path": item["path"], "success": False, "error": str(e)} for item in targets],
                    source_path=targets[0]["path"],
                )
        except Exception:
            logger.debug("[操作记录] 跨库存批量删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"跨库存批量删除失败: {str(e)}")


class LibraryBrowserListFoldersRequest(BaseModel):
    """轻量目录浏览请求（仅本地库）。

    - 默认仅返回子目录；当 ``include_files=True`` 时文件也会作为返回项加入,
      每条带 ``is_directory`` 字段区分。
    - 默认仅读 size 缓存，不主动递归计算大小，避免压垮慢速盘。
    - 当 ``compute_size=True`` 且当前路径不是浏览根（即进入了 RJ 父级目录之类的层级）时，
      允许对未命中缓存的子目录按需计算大小，并通过 ``compute_size_cap`` 限制最大计算条目数。
    """
    library_id: str
    path: Optional[str] = ""
    compute_size: bool = False
    compute_size_cap: int = 256
    include_files: bool = False


class LibraryBrowserNavigationSnapshotRequest(BaseModel):
    """移动弹窗的版本化索引导航快照请求。"""
    library_id: str
    path: Optional[str] = ""
    include_files: bool = True
    include_ancestors: bool = True


@app.post("/api/library/browser/navigation-snapshot")
async def get_library_browser_navigation_snapshot(request: LibraryBrowserNavigationSnapshotRequest):
    if not str(request.library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少 library_id")
    try:
        manager = get_library_manager()
        payload = await asyncio.to_thread(
            manager.navigation_snapshot_via_index,
            request.library_id,
            request.path or None,
            include_files=bool(request.include_files),
            include_ancestors=bool(request.include_ancestors),
        )
        if payload is None:
            return {
                "library_id": request.library_id,
                "index_available": False,
                "browse_via_index": False,
            }
        payload["index_available"] = True
        return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("读取移动弹窗索引导航快照失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取索引导航快照失败: {str(e)}")


@app.post("/api/library/browser/list-folders")
async def list_library_browser_folders(request: LibraryBrowserListFoldersRequest):
    """供"移动到..."/"指定上传子目录"对话框使用：列出指定路径下的一级子项（默认仅子目录，可选包含文件）。

    - 同时支持本地库与远程 synology 库；远程库忽略 compute_size，目录统一不算 size。
    - 进入子目录后，前端可以传 ``compute_size=true`` 让接口对未命中缓存的项按需计算（仅本地库生效）。
    - 传 ``include_files=true`` 时，返回的 folders 数组里会同时包含文件，每项带 ``is_directory`` 字段。
    """
    if not str(request.library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少 library_id")
    try:
        manager = get_library_manager()
        return await manager.list_local_folders_only(
            request.library_id,
            request.path or None,
            compute_size=bool(request.compute_size),
            compute_size_cap=int(request.compute_size_cap or 0),
            include_files=bool(request.include_files),
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log_synology_err(f"列出库存子目录失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"列出库存子目录失败: {str(e)}")


class LibraryBrowserMoveRequest(BaseModel):
    """本地库批量移动请求（源/目标都必须是本地库）。"""
    source_library_id: str
    target_library_id: str
    paths: list[str]
    target_path: Optional[str] = ""
    conflict_strategy: Optional[str] = "suffix"  # suffix / overwrite / skip
    overwrite: bool = False  # 兼容旧字段
    move_plan_id: Optional[str] = None


@app.post("/api/library/browser/move-preview")
async def preview_library_browser_move(request: LibraryBrowserMoveRequest):
    if not request.paths:
        raise HTTPException(status_code=400, detail="待移动项不能为空")
    if not str(request.source_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少源库存")
    if not str(request.target_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少目标库存")
    try:
        manager = get_library_manager()
        return await manager.preview_move_local_items(
            source_library_id=request.source_library_id,
            target_library_id=request.target_library_id,
            paths=list(request.paths or []),
            target_path=request.target_path or None,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存移动预检失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存移动预检失败: {str(e)}")


@app.post("/api/library/browser/move")
async def move_library_browser_items(request: LibraryBrowserMoveRequest, raw_request: Request):
    if not request.paths:
        raise HTTPException(status_code=400, detail="待移动项不能为空")
    if not str(request.source_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少源库存")
    if not str(request.target_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少目标库存")
    try:
        manager = get_library_manager()
        source_library = manager.get_library_definition(request.source_library_id)
        target_library = manager.get_library_definition(request.target_library_id)
        target_dir = os.path.abspath(request.target_path or target_library.root_path)
        source_effects = []
        target_effects = []
        for path in request.paths:
            source_effects.append({
                "kind": "move",
                "relative_path": _local_relative_path(source_library, path),
                "scope": "subtree" if os.path.isdir(path) else "exact",
                "target_library_id": target_library.id,
                "target_path": _local_relative_path(
                    target_library,
                    os.path.join(target_dir, os.path.basename(path)),
                ),
            })
            target_effects.append({
                "kind": "reconcile",
                "relative_path": _local_relative_path(
                    target_library,
                    os.path.join(target_dir, os.path.basename(path)),
                ),
                "scope": "subtree" if os.path.isdir(path) else "exact",
            })
        effects_by_library = {source_library.id: source_effects}
        if target_library.id == source_library.id:
            effects_by_library[source_library.id] = [*source_effects, *target_effects]
        else:
            effects_by_library[target_library.id] = target_effects
        planned_source_by_path = {
            str(effect["relative_path"]): effect
            for effect in source_effects
        }
        mutation_service = get_library_index_mutation_service()
        idempotency_key = _request_idempotency_key(raw_request)
        lookup = getattr(mutation_service, "get_operation_by_idempotency_key", None)

        def replay_existing_move():
            if not callable(lookup) or lookup(idempotency_key) is None:
                return None
            prepared = mutation_service.prepare(
                kind="move",
                effects_by_library=effects_by_library,
                idempotency_key=idempotency_key,
            )
            return _prepared_replay_response(prepared)

        replay = replay_existing_move()
        if replay is not None:
            return replay

        plan_valid = manager.validate_move_preview_plan(
            request.move_plan_id or "",
            source_library_id=request.source_library_id,
            target_library_id=request.target_library_id,
            paths=list(request.paths or []),
            target_path=request.target_path or target_library.root_path,
        ) if request.move_plan_id else None
        if plan_valid is False:
            replay = replay_existing_move()
            if replay is not None:
                return replay
            raise HTTPException(status_code=409, detail="目录索引已变化，请重新确认移动冲突")
        prepared = mutation_service.prepare(
            kind="move",
            effects_by_library=effects_by_library,
            idempotency_key=idempotency_key,
        )
        replay = _prepared_replay_response(prepared)
        if replay is not None:
            return replay
        try:
            mutation_service.mark_filesystem_started(prepared.operation_id)
            result = await manager.move_local_items(
            source_library_id=request.source_library_id,
            target_library_id=request.target_library_id,
            paths=list(request.paths or []),
            target_path=request.target_path or None,
            conflict_strategy=str(request.conflict_strategy or "suffix"),
            overwrite=bool(request.overwrite),
            skip_index_mutation=True,
            )
            if list((result or {}).get("moved") or []):
                _invalidate_rj_subtitle_folder_summary_cache(source_library.id)
                _invalidate_rj_subtitle_folder_summary_cache(target_library.id)
        except Exception as exc:
            mutation_service.fail_prepared(prepared.operation_id, exc)
            raise
        moved = list(result.get("moved") or [])
        actual_by_library: dict[str, list[dict[str, Any]]] = {}
        for item in moved:
            source_path = str(item.get("source") or "")
            destination = str(item.get("destination") or "")
            if not source_path or not destination:
                continue
            source_relative = _local_relative_path(source_library, source_path)
            source_scope = str(
                planned_source_by_path.get(source_relative, {}).get("scope") or "exact"
            )
            actual_by_library.setdefault(source_library.id, []).append({
                "kind": "move",
                "relative_path": source_relative,
                "scope": source_scope,
                "target_library_id": target_library.id,
                "target_path": _local_relative_path(target_library, destination),
            })
            actual_by_library.setdefault(target_library.id, []).append({
                "kind": "reconcile",
                "relative_path": _local_relative_path(target_library, destination),
                "scope": source_scope,
            })
        try:
            return mutation_service.finalize(
                prepared.operation_id,
                actual_effects_by_library=actual_by_library,
                actual_result=result,
            )
        except Exception as exc:
            mutation_service.mark_reconcile_required(prepared.operation_id, exc)
            return JSONResponse(
                status_code=202,
                content={
                    **result,
                    "operation_id": prepared.operation_id,
                    "operation_state": "reconcile_required",
                    "reconciliation_pending": True,
                },
            )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存批量移动失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量移动失败: {str(e)}")


class LibraryAutoCircleGroupRequest(BaseModel):
    """根据 RJ 号把目录自动归类到《库根》/《社团名》/ 下。"""
    library_id: str
    row_path: str
    preview: bool = False


class LibraryBatchAutoCircleGroupRequest(BaseModel):
    """批量按社团把 RJ 文件夹移动到《库根》/《社团名》/ 下。"""
    library_id: str
    row_paths: List[str]


def _parse_circle_name_from_folder(folder_name: str) -> str:
    """从文件夹名解析社团名。
    
    主模板（默认）：[社团][RJxxxxxx]xxx
    兼容模板：[RJxxxxxx][社团]xxx
    解析失败返回空字符串。
    """
    if not folder_name:
        return ""
    from ..core.rename_service import normalize_template_maker_name

    def _leading_bracket_payload(raw: str) -> str:
        text = str(raw or "").strip()
        if not text.startswith("["):
            return ""
        depth = 0
        for index, char in enumerate(text):
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[1:index].strip()
        return text.strip("[] \t\r\n")

    def _clean_candidate(raw: str) -> str:
        candidate = normalize_template_maker_name(raw)
        if candidate and not re.match(r'^[RVB]J\d{6,8}$', candidate, re.IGNORECASE):
            return candidate
        return ""

    # 默认模板：[maker_name][RJxxxxxx]xxx。这里不能只用简单方括号正则：
    # 社团名本身可能包含方括号，例如 ". [Dot-Space]"，模板外层再包一层后会
    # 变成 "[. [Dot-Space]][RJ...]"。
    rj_match = re.search(r'[RVB]J\d{6,8}', folder_name, re.IGNORECASE)
    if rj_match:
        before_rj = folder_name[:rj_match.start()]
        if "[" in before_rj:
            prefix = before_rj.strip()
            if prefix.endswith("["):
                prefix = prefix[:-1].rstrip()
            if prefix.count("[") == prefix.count("]"):
                candidate = _clean_candidate(_leading_bracket_payload(prefix) or prefix)
                if candidate:
                    return candidate

        # 兼容：[RJxxx][maker_name]，也兼容 maker_name 自身带括号的脏数据。
        after_rj = folder_name[rj_match.end():]
        if "[" in after_rj:
            suffix = after_rj.strip()
            if suffix.startswith("]"):
                suffix = suffix[1:].lstrip()
            if suffix.count("[") == suffix.count("]"):
                candidate = _clean_candidate(_leading_bracket_payload(suffix) or suffix)
                if candidate:
                    return candidate
    return ""


def _resolve_local_auto_circle_group_context(library_id: str):
    from ..core.library_manager import get_library_manager

    library_id = str(library_id or "").strip()
    if not library_id:
        raise HTTPException(status_code=400, detail="缺少 library_id")

    manager = get_library_manager()
    try:
        library = manager.get_library_definition(library_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"库存不存在: {exc}")
    if library.type != "local":
        raise HTTPException(status_code=400, detail="按社团分类仅支持本地库")
    return manager, library


async def _auto_circle_group_by_path(
    manager,
    library,
    library_id: str,
    row_path: str,
    *,
    preview: bool = False,
) -> Dict[str, Any]:
    row_path = str(row_path or "").strip()
    if not row_path:
        raise HTTPException(status_code=400, detail="缺少 row_path")

    abs_row_path = os.path.abspath(row_path)
    if not os.path.isdir(abs_row_path):
        raise HTTPException(status_code=400, detail="目标必须是文件夹")

    library_root = os.path.abspath(library.root_path)
    try:
        if os.path.commonpath([library_root, abs_row_path]) != library_root:
            raise HTTPException(status_code=400, detail="目标文件夹不在所选库存内")
    except ValueError:
        raise HTTPException(status_code=400, detail="目标文件夹不在所选库存内")

    folder_name = os.path.basename(abs_row_path)
    rj_match = re.search(r'[RVB]J\d{6,8}', folder_name, re.IGNORECASE)
    rjcode = rj_match.group(0).upper() if rj_match else ""

    circle_name = _parse_circle_name_from_folder(folder_name)
    if not circle_name:
        # 文件夹名里没有社团前缀 → 让前端先做 API 重命名再重试
        return {
            "success": False,
            "need_api_rename": True,
            "rjcode": rjcode,
            "row_path": abs_row_path,
            "folder_name": folder_name,
            "message": "未在文件夹名中识别到社团前缀，请先执行 API 重命名后再试",
        }

    safe_circle_name = re.sub(r'[<>:"/\\|?*]', '_', circle_name)
    safe_circle_name = re.sub(r'[\x00-\x1f\x7f]', '', safe_circle_name).rstrip(' .')
    if not safe_circle_name:
        raise HTTPException(status_code=500, detail=f"社团名 '{circle_name}' 无法转换为合法文件夹名")

    target_circle_dir = os.path.join(library_root, safe_circle_name)

    parent_norm = os.path.normcase(os.path.dirname(abs_row_path))
    target_norm = os.path.normcase(target_circle_dir)
    if parent_norm == target_norm:
        return {
            "success": True,
            "skipped": True,
            "rjcode": rjcode,
            "circle_name": circle_name,
            "safe_circle_name": safe_circle_name,
            "target_dir": target_circle_dir,
            "final_path": abs_row_path,
            "message": f"已经在《{safe_circle_name}》目录下，无需移动",
        }

    if preview:
        return {
            "success": True,
            "preview": True,
            "rjcode": rjcode,
            "circle_name": circle_name,
            "safe_circle_name": safe_circle_name,
            "target_dir": target_circle_dir,
            "final_path": os.path.join(target_circle_dir, os.path.basename(abs_row_path)),
            "message": f"将移动到 {target_circle_dir}",
        }

    try:
        os.makedirs(target_circle_dir, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"创建社团目录失败: {exc}")

    try:
        result = await manager.move_local_items(
            source_library_id=library_id,
            target_library_id=library_id,
            paths=[abs_row_path],
            target_path=target_circle_dir,
            conflict_strategy="suffix",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[auto-circle-group][%s] 移动失败: %s", rjcode, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"移动失败: {exc}")

    final_path = ""
    moved = (result or {}).get("moved") or []
    if moved:
        final_path = str((moved[0] or {}).get("destination") or "")

    return {
        "success": True,
        "rjcode": rjcode,
        "circle_name": circle_name,
        "safe_circle_name": safe_circle_name,
        "target_dir": target_circle_dir,
        "final_path": final_path or os.path.join(target_circle_dir, os.path.basename(abs_row_path)),
        "message": f"已移动到《{safe_circle_name}》",
        "result": result,
    }


@app.post("/api/library/auto-circle-group")
async def auto_circle_group_by_rj(request: LibraryAutoCircleGroupRequest):
    """自动按社团把 RJ 文件夹移动到 库根/社团名/ 下。

    社团名从文件夹名直接解析（默认模板 [社团][RJxxx]xxx）。
    解析失败则返回 need_api_rename=True，由前端串联先调 API 重命名后再次发起。
    """
    library_id = str(request.library_id or "").strip()
    manager, library = _resolve_local_auto_circle_group_context(library_id)
    return await _auto_circle_group_by_path(
        manager,
        library,
        library_id,
        request.row_path,
        preview=bool(request.preview),
    )


@app.post("/api/library/batch-auto-circle-group")
async def batch_auto_circle_group_by_rj(request: LibraryBatchAutoCircleGroupRequest):
    """批量自动按社团分类。

    这里不自动串联 API 重命名；识别不到社团前缀的项会返回 need_api_rename，
    前端继续复用原来的单项重命名兜底链路，保证行为不缩水。
    """
    library_id = str(request.library_id or "").strip()
    row_paths = [str(path or "").strip() for path in (request.row_paths or []) if str(path or "").strip()]
    if not row_paths:
        raise HTTPException(status_code=400, detail="缺少 row_paths")

    manager, library = _resolve_local_auto_circle_group_context(library_id)

    results = []
    success_count = 0
    skipped_count = 0
    need_api_rename_count = 0
    failed_count = 0

    for row_path in row_paths:
        try:
            data = await _auto_circle_group_by_path(
                manager,
                library,
                library_id,
                row_path,
                preview=False,
            )
            data["path"] = row_path
            if data.get("success"):
                if data.get("skipped"):
                    skipped_count += 1
                else:
                    success_count += 1
            elif data.get("need_api_rename"):
                need_api_rename_count += 1
            else:
                failed_count += 1
            results.append(data)
        except HTTPException as exc:
            failed_count += 1
            results.append({
                "path": row_path,
                "success": False,
                "error": str(exc.detail or exc),
            })
        except Exception as exc:
            failed_count += 1
            logger.error("[batch-auto-circle-group] %s 分类失败: %s", row_path, exc, exc_info=True)
            results.append({
                "path": row_path,
                "success": False,
                "error": str(exc),
            })

    return {
        "message": "批量按社团分类完成",
        "success_count": success_count,
        "skipped_count": skipped_count,
        "need_api_rename_count": need_api_rename_count,
        "failed_count": failed_count,
        "results": results,
    }


@app.post("/api/library/browser/open-folder")
async def open_library_browser_folder(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        library_id = data.get("library_id")
        force_local = data.get("force_local", False)
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        manager = get_library_manager()
        return await manager.open_folder(library_id, path, force_local=force_local)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存打开目录失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"库存打开目录失败: {str(e)}")


LIBRARY_PREVIEW_MIME_PREFIXES = ("image/", "video/", "audio/", "text/")
LIBRARY_PREVIEW_MIME_TYPES = {
    "application/pdf",
    "application/json",
    "application/xml",
    "application/x-subrip",
    "application/ass",
}
LIBRARY_PREVIEW_EXTENSION_TYPES = {
    ".ass": "text/plain; charset=utf-8",
    ".avif": "image/avif",
    ".lrc": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".ssa": "text/plain; charset=utf-8",
    ".srt": "application/x-subrip; charset=utf-8",
    ".vtt": "text/vtt; charset=utf-8",
}


def _guess_library_preview_media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in LIBRARY_PREVIEW_EXTENSION_TYPES:
        return LIBRARY_PREVIEW_EXTENSION_TYPES[suffix]
    guessed, _encoding = mimetypes.guess_type(path)
    if guessed:
        if guessed.startswith("text/") and "charset=" not in guessed:
            return f"{guessed}; charset=utf-8"
        return guessed
    return "application/octet-stream"


def _is_library_preview_media_type(media_type: str) -> bool:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    return normalized in LIBRARY_PREVIEW_MIME_TYPES or any(normalized.startswith(prefix) for prefix in LIBRARY_PREVIEW_MIME_PREFIXES)


LIBRARY_TEXT_PREVIEW_MAX_BYTES = 12 * 1024 * 1024
LIBRARY_TEXT_PREVIEW_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "cp932",
    "shift_jis",
    "gb18030",
    "big5",
)


def _is_library_text_preview_type(media_type: str) -> bool:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    return (
        normalized.startswith("text/")
        or normalized in {"application/json", "application/xml", "application/x-subrip", "application/ass"}
    )


def _score_decoded_preview_text(text_value: str) -> float:
    if not text_value:
        return 999999.0
    replacement_count = text_value.count("\ufffd")
    control_count = sum(1 for ch in text_value if ord(ch) < 32 and ch not in "\r\n\t")
    cjk_count = sum(1 for ch in text_value if "\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff")
    printable_count = sum(1 for ch in text_value if ch.isprintable() or ch in "\r\n\t")
    return replacement_count * 1000 + control_count * 40 - cjk_count * 0.2 - printable_count * 0.01


def _decode_library_preview_text(raw_bytes: bytes) -> tuple[str, str]:
    best_text = raw_bytes.decode("utf-8", errors="replace")
    best_encoding = "utf-8"
    best_score = _score_decoded_preview_text(best_text)
    for encoding in LIBRARY_TEXT_PREVIEW_ENCODINGS:
        try:
            decoded = raw_bytes.decode(encoding, errors="strict")
            score = _score_decoded_preview_text(decoded)
        except Exception:
            decoded = raw_bytes.decode(encoding, errors="replace")
            score = _score_decoded_preview_text(decoded) + 25
        if score < best_score:
            best_text = decoded
            best_encoding = encoding
            best_score = score
    return best_text, best_encoding


def _normalize_library_preview_encoding(encoding: Optional[str]) -> str:
    encoding_value = str(encoding or "").strip().lower().replace("-", "_")
    aliases = {
        "auto": "",
        "utf8": "utf-8",
        "utf_8": "utf-8",
        "utf8_sig": "utf-8-sig",
        "utf_8_sig": "utf-8-sig",
        "utf16": "utf-16",
        "utf_16": "utf-16",
        "utf16le": "utf-16-le",
        "utf_16_le": "utf-16-le",
        "utf16be": "utf-16-be",
        "utf_16_be": "utf-16-be",
        "sjis": "shift_jis",
        "shift_jis": "shift_jis",
        "shiftjis": "shift_jis",
        "cp932": "cp932",
        "gbk": "gb18030",
        "gb18030": "gb18030",
        "big5": "big5",
    }
    return aliases.get(encoding_value, "")


def _build_library_text_preview_response(
    raw_bytes: bytes,
    media_type: str,
    headers: dict[str, str],
    encoding: Optional[str] = None,
) -> Response:
    requested_encoding = _normalize_library_preview_encoding(encoding)
    if requested_encoding:
        text_value = raw_bytes.decode(requested_encoding, errors="replace")
        detected_encoding = requested_encoding
    else:
        text_value, detected_encoding = _decode_library_preview_text(raw_bytes)
    response_headers = dict(headers)
    response_headers["X-KikoeruManager-Detected-Encoding"] = detected_encoding
    normalized_type = str(media_type or "text/plain").split(";", 1)[0].strip().lower() or "text/plain"
    return Response(
        content=text_value.encode("utf-8"),
        media_type=f"{normalized_type}; charset=utf-8",
        headers=response_headers,
    )


async def _collect_library_preview_stream_bytes(stream) -> bytes:
    chunks: list[bytes] = []
    total_size = 0
    async for chunk in stream:
        if not chunk:
            continue
        total_size += len(chunk)
        if total_size > LIBRARY_TEXT_PREVIEW_MAX_BYTES:
            raise HTTPException(status_code=413, detail="文本文件过大，暂不支持浏览器预览")
        chunks.append(chunk)
    return b"".join(chunks)


def _prepare_local_library_preview(
    *,
    manager,
    library,
    path: str,
    encoding: Optional[str],
) -> dict[str, Any]:
    browse_root = os.path.abspath(library.browse_root_path or library.root_path)
    target_path = os.path.abspath(path)
    if not manager._local_path_is_within_root(target_path, browse_root):
        raise HTTPException(status_code=403, detail="文件不在当前库存范围内")
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    if not os.path.isfile(target_path):
        raise HTTPException(status_code=400, detail="只能观看文件")

    media_type = _guess_library_preview_media_type(target_path)
    if not _is_library_preview_media_type(media_type):
        raise HTTPException(status_code=415, detail="该文件类型暂不支持浏览器观看")

    filename = os.path.basename(target_path)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store, max-age=0",
        "X-Content-Type-Options": "nosniff",
    }
    payload: dict[str, Any] = {
        "target_path": target_path,
        "media_type": media_type,
        "headers": headers,
        "text_bytes": None,
        "encoding": encoding,
    }
    if _is_library_text_preview_type(media_type):
        if os.path.getsize(target_path) > LIBRARY_TEXT_PREVIEW_MAX_BYTES:
            raise HTTPException(status_code=413, detail="文本文件过大，暂不支持浏览器预览")
        with open(target_path, "rb") as handle:
            payload["text_bytes"] = handle.read()
    return payload


@app.get("/api/library/browser/preview")
async def preview_library_browser_file(library_id: str, path: str, encoding: Optional[str] = None):
    """在浏览器内预览库存里的安全媒体 / 文本文件。"""
    try:
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少库存 ID")
        if not path:
            raise HTTPException(status_code=400, detail="缺少文件路径")

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if library.type == "synology_filestation":
            if not library.synology:
                raise HTTPException(status_code=400, detail="远程库存缺少群晖连接配置")
            target_path = manager._normalize_remote_path(path)
            browse_root = manager._normalize_remote_path(library.browse_root_path or library.root_path or "/")
            if not manager._remote_path_is_within_root(target_path, browse_root):
                raise HTTPException(status_code=403, detail="文件不在当前库存范围内")

            media_type = _guess_library_preview_media_type(target_path)
            if not _is_library_preview_media_type(media_type):
                raise HTTPException(status_code=415, detail="该文件类型暂不支持浏览器观看")

            client = manager.get_cached_synology_client(library.synology)
            filename = PurePosixPath(target_path).name or "preview"
            headers = {
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            }
            if _is_library_text_preview_type(media_type):
                raw_bytes = await _collect_library_preview_stream_bytes(client.stream_download(target_path))
                return _build_library_text_preview_response(raw_bytes, media_type, headers, encoding=encoding)
            return StreamingResponse(
                client.stream_download(target_path),
                media_type=media_type,
                headers=headers,
            )

        local_preview = await asyncio.to_thread(
            _prepare_local_library_preview,
            manager=manager,
            library=library,
            path=path,
            encoding=encoding,
        )
        media_type = str(local_preview["media_type"])
        headers = dict(local_preview["headers"])
        text_bytes = local_preview.get("text_bytes")
        if text_bytes is not None:
            return _build_library_text_preview_response(text_bytes, media_type, headers, encoding=encoding)
        return FileResponse(str(local_preview["target_path"]), media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存文件观看失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"库存文件观看失败: {str(e)}")


@app.get("/api/library/files")
async def get_library_files():
    """获取库内所有文件（只扫描前两级目录）"""
    try:
        config = get_config()
        library_path = config.storage.library_path

        if not os.path.exists(library_path):
            return {"files": []}

        # 查询 ProcessedArchive 数据库获取解压时间（DB 操作走主 event loop，本身够快）
        # ★ 性能修复：原实现拿到 db 后没有 close，整段 await asyncio.to_thread 期间
        # 一直占着 connection pool 一个槽位（且没 finally 释放）。改为读完立刻 close。
        from ..models.database import ProcessedArchive, get_db
        archive_times: dict[str, Any] = {}
        db = next(get_db())
        try:
            for archive in db.query(ProcessedArchive).all():
                archive_name = os.path.basename(archive.current_path)
                archive_times[archive_name] = archive.processed_at
        finally:
            db.close()

        # 整库扫描包含三层嵌套同步 IO（os.listdir × 2 + os.walk + 每个文件 os.stat / getsize），
        # 远程挂载或大库存上能阻塞 event loop 几分钟。整段下放到线程池跑，
        # 期间 API 仍可正常响应其他请求。
        def _scan_library_two_levels() -> list[dict]:
            collected: list[dict] = []
            local_id = 0
            for item in os.listdir(library_path):
                item_path = os.path.join(library_path, item)
                # 跳过冲突文件夹和隐藏文件
                if item.startswith('_') or item.startswith('.'):
                    continue

                if os.path.isdir(item_path):
                    # 二级：RJ 文件夹下面的子目录 / 单个文件
                    for subitem in os.listdir(item_path):
                        subitem_path = os.path.join(item_path, subitem)
                        if subitem.startswith('.'):
                            continue
                        try:
                            st = os.stat(subitem_path)
                            rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', subitem, re.IGNORECASE)
                            rjcode = rj_match.group(0).upper() if rj_match else None

                            # 计算文件夹大小或获取文件大小
                            size = 0
                            sub_is_dir = os.path.isdir(subitem_path)
                            if sub_is_dir:
                                for dirpath, _, filenames in os.walk(subitem_path):
                                    for f in filenames:
                                        fp = os.path.join(dirpath, f)
                                        try:
                                            size += os.path.getsize(fp)
                                        except Exception:
                                            pass
                            else:
                                size = st.st_size

                            # 解压时间（优先 processed_at，否则文件系统 mtime）
                            if subitem in archive_times:
                                unzip_time = archive_times[subitem].isoformat()
                            else:
                                unzip_time = datetime.fromtimestamp(st.st_mtime).isoformat()

                            collected.append({
                                "id": str(local_id),
                                "name": subitem,
                                "path": subitem_path,
                                "rjcode": rjcode,
                                "size": size,
                                "modified_time": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                "unzip_time": unzip_time,
                                "is_directory": sub_is_dir,
                            })
                            local_id += 1
                        except Exception as e:
                            logger.warning(f"获取项目信息失败: {subitem_path}, {e}")
                else:
                    # 根目录下的文件
                    try:
                        st = os.stat(item_path)
                        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                        rjcode = rj_match.group(0).upper() if rj_match else None

                        if item in archive_times:
                            unzip_time = archive_times[item].isoformat()
                        else:
                            unzip_time = datetime.fromtimestamp(st.st_mtime).isoformat()

                        collected.append({
                            "id": str(local_id),
                            "name": item,
                            "path": item_path,
                            "rjcode": rjcode,
                            "size": st.st_size,
                            "modified_time": datetime.fromtimestamp(st.st_mtime).isoformat(),
                            "unzip_time": unzip_time,
                            "is_directory": False,
                        })
                        local_id += 1
                    except Exception as e:
                        logger.warning(f"获取项目信息失败: {item_path}, {e}")
            return collected

        items = await asyncio.to_thread(_scan_library_two_levels)

        # 按解压时间排序（最新的在前）
        items.sort(key=lambda x: x["unzip_time"] or x["modified_time"], reverse=True)

        return {"files": items}
        
    except Exception as e:
        _log_synology_err(f"获取库文件失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取库文件失败: {str(e)}")

@app.post("/api/library/folder-contents")
@app.post("/api/library/folder-content")
async def get_library_folder_contents(request: Request):
    """获取指定本地文件夹的所有子文件（递归）"""
    try:
        data = await request.json()
        folder_path = str(data.get("path") or "").strip()
        library_id = str(data.get("library_id") or "").strip()
        recursive = bool(data.get("recursive", True))
        prefer_index = bool(data.get("prefer_index", False))
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")

        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if library_id else manager.find_local_library_for_path(folder_path)
        if library is None:
            target_path = os.path.abspath(folder_path)

            def _walk_and_stat() -> tuple[bool, bool, list[dict]]:
                if not os.path.exists(target_path):
                    return False, False, []
                if not os.path.isdir(target_path):
                    return True, False, []
                collected: list[dict] = []
                local_id = 0
                if recursive:
                    walker = os.walk(target_path)
                    for root, _, files in walker:
                        for filename in files:
                            if filename.startswith('.'):
                                continue
                            file_path = os.path.join(root, filename)
                            try:
                                st = os.stat(file_path)
                                relative_path = os.path.relpath(file_path, target_path).replace("\\", "/")
                                collected.append({
                                    "id": str(local_id),
                                    "name": filename,
                                    "path": file_path,
                                    "relative_path": relative_path,
                                    "size": st.st_size,
                                    "modified_time": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                })
                                local_id += 1
                            except Exception as exc:
                                logger.warning("读取子文件失败: %s, %s", file_path, exc)
                    return True, True, collected
                try:
                    with os.scandir(target_path) as entries:
                        for entry in entries:
                            if entry.name.startswith('.'):
                                continue
                            try:
                                st = entry.stat(follow_symlinks=False)
                                is_directory = entry.is_dir(follow_symlinks=False)
                            except Exception as exc:
                                logger.warning("读取子项失败: %s, %s", entry.path, exc)
                                continue
                            collected.append({
                                "id": str(local_id),
                                "name": entry.name,
                                "path": entry.path,
                                "relative_path": entry.name,
                                "size": None if is_directory else st.st_size,
                                "size_status": "disabled" if is_directory else "ready",
                                "modified_time": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                "type": "dir" if is_directory else "file",
                                "is_directory": is_directory,
                                "has_children": is_directory,
                                "children_loaded": False if is_directory else True,
                            })
                            local_id += 1
                except Exception:
                    raise
                return True, True, collected

            path_exists, path_is_dir, items = await asyncio.to_thread(_walk_and_stat)
            if not path_exists:
                raise HTTPException(status_code=404, detail="文件夹不存在")
            if not path_is_dir:
                raise HTTPException(status_code=400, detail="目标不是文件夹")
            if recursive:
                items.sort(key=lambda x: x["relative_path"])
            else:
                items.sort(key=lambda x: (0 if x.get("is_directory") else 1, str(x.get("name") or "").lower()))
            total_files = len(items) if recursive else sum(1 for item in items if not item.get("is_directory"))
            return {
                "folder_name": os.path.basename(target_path),
                "folder_path": target_path,
                "total_files": total_files,
                "total_items": len(items),
                "recursive": recursive,
                "browse_via_index": False,
                "items": items,
            }
        payload = await manager.folder_contents(
            library.id,
            folder_path,
            recursive=recursive,
            prefer_index=prefer_index,
        )
        if library.type == "local":
            payload["index_view"] = _library_index_view(library.id)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"获取文件夹内容失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取文件夹内容失败: {str(e)}")

@app.post("/api/library/rename")
async def rename_library_file(request: Request):
    """重命名库内文件或文件夹"""
    try:
        data = await request.json()
        old_path = str(data.get("path") or "").strip()
        new_name = str(data.get("new_name") or "").strip()
        library_id = str(data.get("library_id") or "").strip()
        
        if not old_path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")

        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if library_id else manager.find_local_library_for_path(old_path)
        if library is None:
            raise HTTPException(status_code=403, detail="只能重命名库存内的文件")

        result = await manager.rename(library.id, old_path, new_name)
        _invalidate_rj_subtitle_folder_summary_cache(library.id)
        logger.info("重命名成功: library=%s %s -> %s", library.id, old_path, result.get("new_path"))
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重命名失败: {str(e)}")

@app.post("/api/library/api-rename")
async def api_rename_library_file(request: Request):
    """使用API重新获取元数据并重命名"""
    file_path = ""
    library_id = None
    rjcode = ""
    old_name = ""
    new_name = ""
    batch_id = ""
    metadata_source = ""
    dlsite_circuit_open = False
    rename_skipped_reason = ""
    metadata_verification_status = "unverified"
    metadata_verification_reason = ""
    prepared = None
    mutation_service = None
    planned_effects: List[Dict[str, Any]] = []
    filesystem_started = False
    try:
        data = await request.json()
        file_path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        batch_id = str(data.get("batch_id") or "").strip()
        force_refresh = bool(data.get("force_refresh") or data.get("forceRefresh"))
        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if library_id else None
        if library is None and file_path:
            library = manager.find_local_library_for_path(file_path)
            if library:
                library_id = library.id
        if library is None:
            raise HTTPException(status_code=403, detail="只能 API 重命名库存内的文件")
        is_remote_library = bool(library and library.type == "synology_filestation")
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")

        if library.type == "local":
            mutation_service = get_library_index_mutation_service()
            lookup = getattr(mutation_service, "get_operation_by_idempotency_key", None)
            if callable(lookup):
                replay = _stored_mutation_replay_response(
                    lookup(_request_idempotency_key(request)),
                    expected_kind="api_rename",
                    expected_sources={library.id: {_local_relative_path(library, file_path)}},
                )
                if replay is not None:
                    return replay
        
        if not is_remote_library and not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 提取RJ号
        import re
        target_name = str(PurePosixPath(file_path).name) if is_remote_library else os.path.basename(file_path)
        rj_match = re.search(r'[RVB]J\d{6,8}', target_name, re.IGNORECASE)
        if not rj_match:
            raise HTTPException(status_code=400, detail="无法从文件名提取RJ号")
        
        rjcode = rj_match.group(0).upper()
        old_name = target_name
        logger.info(f"API重新命名: {file_path}, RJ号: {rjcode}")
        
        # 获取元数据；默认复用有效缓存，只有 force_refresh 才清缓存。
        from ..core.metadata_service import MetadataService
        from ..models.database import WorkMetadata as WorkMetadataModel, get_db
        metadata_service = MetadataService()
        
        try:
            if force_refresh:
                db = next(get_db())
                try:
                    deleted_count = db.query(WorkMetadataModel).filter(
                        WorkMetadataModel.rjcode == rjcode
                    ).delete()
                    db.commit()
                    logger.info("[%s] force_refresh 已清除缓存 count=%s", rjcode, deleted_count)
                except Exception as e:
                    logger.warning(f"[{rjcode}] 清除缓存失败: {e}")
                    db.rollback()
                finally:
                    db.close()
            else:
                logger.info("[%s] API 重命名优先复用有效元数据缓存", rjcode)
            
            # 创建临时任务对象（用于进度更新，虽然这里不需要）
            from ..core.task_engine import Task, TaskType
            temp_task = Task(
                task_type=TaskType.METADATA,
                source_path=file_path,
                rjcode=rjcode,
            )
            temp_task.task_metadata = {
                "rjcode": rjcode,
                "rjcode_lock": True,
            }
            
            metadata = await metadata_service.fetch(file_path, temp_task, force_refresh=force_refresh)
            skip_reason = _api_rename_metadata_skip_reason(metadata, rjcode)
            metadata_source = str(metadata.get("metadata_source") or "")
            dlsite_circuit_open = bool(metadata.get("dlsite_circuit_open"))
            rename_skipped_reason = skip_reason
            metadata_verification_status = str(
                metadata.get("metadata_verification_status") or "unverified"
            )
            metadata_verification_reason = str(
                metadata.get("metadata_verification_reason") or skip_reason or ""
            )
            logger.info(
                "获取到元数据: %s metadata_source=%s dlsite_circuit_open=%s rename_skipped_reason=%s",
                metadata,
                metadata_source,
                dlsite_circuit_open,
                skip_reason,
            )
            if skip_reason:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": skip_reason,
                        "skipped": True,
                        "metadata_verification_status": metadata_verification_status,
                        "metadata_verification_reason": metadata_verification_reason,
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取元数据失败: {e}")
            raise HTTPException(status_code=_synology_http_status(e), detail=f"获取元数据失败: {str(e)}")
        
        # 生成新名称
        work_name = metadata.get('work_name', '')
        if not work_name:
            raise HTTPException(status_code=422, detail="获取到的作品名称为空，请检查 DLsite 元数据是否可用")
        
        config = get_config()
        logger.info(f"[API RENAME] 读取到的模板: '{config.rename.template}' (长度: {len(config.rename.template)})")
        logger.info(f"[API RENAME] use_japanese_metadata: {config.rename.use_japanese_metadata}")

        from ..core.rename_service import RenameService
        rename_service = RenameService()

        # 创建临时任务对象用于重命名
        from ..core.task_engine import Task, TaskType
        temp_task = Task(
            task_type=TaskType.RENAME,
            source_path=file_path
        )
        temp_task.task_metadata = metadata

        # 如果启用了日语元数据，获取日语版本
        japanese_metadata = None
        if config.rename.use_japanese_metadata:
            logger.info(f"[{rjcode}] 启用日语元数据，正在获取...")
            japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
            if japanese_metadata:
                logger.info(f"[{rjcode}] 日语元数据获取成功: maker_name={japanese_metadata.get('maker_name')}")
            else:
                logger.warning(f"[{rjcode}] 日语元数据获取失败，将使用当前语言元数据")

        new_name = rename_service._compile_name(metadata, japanese_metadata)
        new_name = rename_service._sanitize_filename(new_name)
        logger.info(f"[{rjcode}] 使用重命名模板生成名称: {new_name}")
        
        # 构建新路径
        if is_remote_library:
            parent_dir = str(PurePosixPath(file_path).parent)
            new_path = str(PurePosixPath(parent_dir) / new_name)
        else:
            parent_dir = os.path.dirname(file_path)
            new_path = os.path.join(parent_dir, new_name)
        
        # 检查新名称是否已存在
        if not is_remote_library and os.path.exists(new_path) and new_path != file_path:
            raise HTTPException(status_code=400, detail="新名称已存在")
        
        if new_path == file_path:
            try:
                from ..core.activity_log_service import log_api_rename_action

                log_api_rename_action(
                    action="api_rename",
                    success=True,
                    source_path=file_path,
                    new_path=new_path,
                    old_name=old_name,
                    new_name=new_name,
                    rjcode=rjcode or None,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    extra_detail={"no_change": True},
                )
            except Exception:
                logger.debug("[操作记录] API 重命名无变化记录失败", exc_info=True)
            return {
                "message": "名称已是最新，无需重命名",
                "name": new_name,
                "new_name": new_name,
                "path": file_path,
                "new_path": file_path,
                "metadata_verification_status": metadata_verification_status,
                "metadata_verification_reason": metadata_verification_reason,
            }

        # 执行重命名
        if library.type == "local":
            planned_effects = _local_rename_effects(library, file_path, new_path)
            mutation_service = mutation_service or get_library_index_mutation_service()
            prepared = mutation_service.prepare(
                kind="api_rename",
                effects_by_library={library.id: planned_effects},
                idempotency_key=_request_idempotency_key(request),
            )
            replay = _prepared_replay_response(prepared)
            if replay is not None:
                return replay
            mutation_service.mark_filesystem_started(prepared.operation_id)
            filesystem_started = True
        try:
            if prepared is not None:
                rename_result = await manager.rename(
                    library.id,
                    file_path,
                    new_name,
                    skip_index_mutation=True,
                    sync_index_mutation=False,
                )
            else:
                rename_result = await manager.rename(
                    library.id,
                    file_path,
                    new_name,
                    sync_index_mutation=True,
                )
        except Exception as exc:
            if prepared is not None:
                source_still_exists = os.path.exists(file_path)
                target_exists = os.path.exists(new_path)
                if source_still_exists and not target_exists:
                    mutation_service.fail_prepared(prepared.operation_id, exc)
                    prepared = None
                else:
                    mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                    return JSONResponse(
                        status_code=202,
                        content={
                            "message": "文件系统结果待核对，后台将自动恢复索引",
                            "operation_id": prepared.operation_id,
                            "operation_state": "reconcile_required",
                            "reconciliation_pending": True,
                            "path": new_path if target_exists else file_path,
                            "new_path": new_path if target_exists else "",
                            "new_name": new_name,
                        },
                    )
            raise
        new_path = str(rename_result.get("new_path") or new_path)
        logger.info(f"API重命名成功: {file_path} -> {new_path}")
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=True,
                source_path=file_path,
                new_path=new_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                batch_id=batch_id or None,
                library_id=str(library_id or "") or None,
            )
        except Exception:
            logger.debug("[操作记录] API 重命名成功记录失败", exc_info=True)

        response = {
            "message": "API重命名成功",
            "old_name": os.path.basename(file_path),
            "new_name": new_name,
            "path": new_path,
            "new_path": new_path,
            "metadata": metadata,
            "metadata_verification_status": metadata_verification_status,
            "metadata_verification_reason": metadata_verification_reason,
        }
        if prepared is not None:
            try:
                response = mutation_service.finalize(
                    prepared.operation_id,
                    actual_effects_by_library={library.id: planned_effects},
                    actual_result=response,
                )
            except Exception as exc:
                mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                return JSONResponse(
                    status_code=202,
                    content={
                        **response,
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
        _invalidate_rj_subtitle_folder_summary_cache(library.id)
        return response
        
    except HTTPException as exc:
        if prepared is not None and not filesystem_started:
            mutation_service.fail_prepared(prepared.operation_id, exc.detail or exc)
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                batch_id=batch_id or None,
                library_id=str(library_id or "") or None,
                error=str(exc.detail or exc),
                status="skipped" if exc.status_code == 422 and rename_skipped_reason else "failed",
                extra_detail={
                    "metadata_source": metadata_source,
                    "dlsite_circuit_open": dlsite_circuit_open,
                    "rename_skipped_reason": rename_skipped_reason,
                } if rename_skipped_reason else None,
            )
        except Exception:
            logger.debug("[操作记录] API 重命名 HTTP 异常记录失败", exc_info=True)
        raise
    except Exception as e:
        if prepared is not None:
            if filesystem_started:
                mutation_service.mark_reconcile_required(prepared.operation_id, e)
                return JSONResponse(
                    status_code=202,
                    content={
                        "message": "文件系统结果待核对，后台将自动恢复索引",
                        "operation_id": prepared.operation_id,
                        "operation_state": "reconcile_required",
                        "reconciliation_pending": True,
                    },
                )
            mutation_service.fail_prepared(prepared.operation_id, e)
        logger.error(f"API重命名失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                batch_id=batch_id or None,
                library_id=str(library_id or "") or None,
                error=str(e),
            )
        except Exception:
            logger.debug("[操作记录] API 重命名失败记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"API重命名失败: {str(e)}")

def map_path_to_local(remote_path: str) -> tuple[str, bool]:
    """
    将远程路径映射到本地路径
    返回: (映射后的路径, 是否成功映射)
    """
    config = get_config()
    if not config.path_mapping.enabled:
        return remote_path, False
    
    # 统一路径分隔符为 /
    remote_path_normalized = remote_path.replace("\\", "/")
    
    for rule in config.path_mapping.rules:
        if not rule.enabled:
            continue
        
        # 统一规则路径分隔符
        rule_remote = rule.remote_path.replace("\\", "/")
        
        # 检查路径是否匹配
        if remote_path_normalized.startswith(rule_remote):
            # 替换前缀
            relative_path = remote_path_normalized[len(rule_remote):]
            # 移除开头的 / 或 \
            relative_path = relative_path.lstrip("/\\")
            
            # 组合成本地路径
            local_path = os.path.join(rule.local_path, relative_path)
            return local_path, True
    
    return remote_path, False


def _robust_rmtree(path: str, retries: int = 3, delay: float = 1.0) -> None:
    """删除目录树，自动处理只读文件(WinError 5)和文件被占用(WinError 32)。"""
    import stat

    def _onerror(func, fpath, exc_info):
        exc = exc_info[1]
        if getattr(exc, 'winerror', None) == 5:
            try:
                os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
                func(fpath)
                return
            except Exception:
                pass
        raise exc

    import time as _time
    last_exc = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except Exception as exc:
            last_exc = exc
            if getattr(exc, 'winerror', None) == 32 and attempt < retries - 1:
                _time.sleep(delay)
                continue
            break
    if last_exc:
        raise last_exc


def _is_path_under_base(path: str, base_path: str) -> bool:
    try:
        if not path or not base_path:
            return False
        target = os.path.abspath(os.path.normpath(path))
        base = os.path.abspath(os.path.normpath(base_path))
        if os.name == "nt":
            target = os.path.normcase(target)
            base = os.path.normcase(base)
        return os.path.commonpath([base, target]) == base
    except Exception:
        return False


@app.post("/api/library/delete")
async def delete_library_file(request: Request):
    """删除库内文件或文件夹（需要确认）"""
    try:
        data = await request.json()
        file_path = str(data.get("path") or "").strip()
        confirmed = data.get("confirmed", False)
        library_id = str(data.get("library_id") or "").strip()
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")

        manager = get_library_manager()
        library = manager.get_library_definition(library_id) if library_id else manager.find_local_library_for_path(file_path)
        if library is None:
            raise HTTPException(status_code=403, detail="只能删除库存内的文件")

        result = await manager.delete(library.id, file_path, confirmed=bool(confirmed))
        if confirmed:
            _invalidate_rj_subtitle_folder_summary_cache(library.id)
        logger.info("删除接口完成: library=%s path=%s confirmed=%s", library.id, file_path, bool(confirmed))
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

# 批量删除 API
@app.post("/api/library/batch-delete")
async def batch_delete_library_items(request: Request):
    """批量删除库内文件或文件夹"""
    try:
        data = await request.json()
        paths = [str(path or "").strip() for path in (data.get("paths", []) or []) if str(path or "").strip()]
        confirmed = data.get("confirmed", False)
        library_id = data.get("library_id")
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")

        manager = get_library_manager()
        fixed_library = manager.get_library_definition(library_id) if library_id else None
        grouped: dict[str, dict[str, Any]] = {}
        for path in paths:
            library = fixed_library or manager.find_local_library_for_path(path)
            if library is None:
                raise HTTPException(status_code=403, detail=f"只能删除库存内的文件：{path}")
            grouped.setdefault(library.id, {"library": library, "paths": []})["paths"].append(path)

        if not confirmed:
            previews = []
            for group in grouped.values():
                previews.append(await manager.batch_delete(group["library"].id, group["paths"], confirmed=False))
            size_disabled = any(bool(item.get("size_disabled")) for item in previews if isinstance(item, dict))
            total_size = None if size_disabled else sum(int((item or {}).get("total_size") or 0) for item in previews)
            return {
                "need_confirm": True,
                "total_count": len(paths),
                "total_size": total_size,
                "size_disabled": size_disabled,
            }

        success_count = 0
        failed_paths: list[dict[str, str]] = []
        success_paths: list[str] = []
        for group in grouped.values():
            try:
                result = await manager.batch_delete(group["library"].id, group["paths"], confirmed=True)
                group_failed = result.get("failed_paths") or []
                failed_lookup = {
                    str((item or {}).get("path") or "").strip()
                    for item in group_failed
                    if isinstance(item, dict)
                }
                failed_paths.extend(group_failed)
                group_success_paths = [path for path in group["paths"] if path not in failed_lookup]
                success_paths.extend(group_success_paths)
                success_count += int(result.get("success_count") or len(group_success_paths))
                if group_success_paths:
                    _invalidate_rj_subtitle_folder_summary_cache(group["library"].id)
            except Exception as e:
                logger.error(f"批量删除失败：library={group['library'].id}, {e}", exc_info=True)
                failed_paths.extend({"path": path, "error": str(e)} for path in group["paths"])

        return {
            "message": "批量删除完成",
            "success_count": success_count,
            "success_paths": success_paths,
            "failed_paths": failed_paths,
            "index_mutation_queued": success_count > 0,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量删除失败：{str(e)}")


# 批量 API 重命名 API
@app.post("/api/library/batch-api-rename")
async def batch_api_rename_library_items(request: Request, background_tasks: BackgroundTasks):
    """批量 API重命名（异步处理）"""
    try:
        data = await request.json()
        paths = data.get("paths", [])
        library_id = data.get("library_id")
        idempotency_key = _request_idempotency_key(request)
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")

        manager = get_library_manager()
        request_library = manager.get_library_definition(library_id) if library_id else None

        if request_library is not None and request_library.type == "local":
            mutation_service = get_library_index_mutation_service()
            lookup = getattr(mutation_service, "get_operation_by_idempotency_key", None)
            if callable(lookup):
                replay = _stored_mutation_replay_response(
                    lookup(idempotency_key),
                    expected_kind="batch_api_rename",
                    expected_sources={
                        request_library.id: {
                            _local_relative_path(request_library, str(path or "").strip())
                            for path in paths
                        }
                    },
                )
                if replay is not None:
                    return replay

        # 验证路径。远程库路径由 manager.rename/FileStation 负责校验，本地库仍先做快速存在性检查。
        for path in paths:
            raw_path = str(path or "").strip()
            item_library = request_library
            if item_library is None:
                item_library = manager.find_local_library_for_path(raw_path)
            if not item_library or item_library.type != "synology_filestation":
                if not os.path.exists(raw_path):
                    raise HTTPException(status_code=404, detail=f"路径不存在：{raw_path}")
        
        # 创建任务 ID
        import uuid
        request_key = _batch_api_rename_request_key(library_id, paths)
        existing_task = _BATCH_API_RENAME_INFLIGHT.get(request_key)
        if existing_task is not None:
            if not existing_task.done():
                logger.info("批量 API重命名复用运行中请求：items=%s", len(paths))
                return await asyncio.shield(existing_task)
            if _BATCH_API_RENAME_INFLIGHT.get(request_key) is existing_task:
                _BATCH_API_RENAME_INFLIGHT.pop(request_key, None)

        batch_id = str(uuid.uuid4())
        
        # 在后台处理
        async def process_batch():
            from ..core.task_engine import Task, TaskType
            from ..core.metadata_service import MetadataService
            from ..core.rename_service import RenameService
            from ..core.activity_log_service import log_api_rename_action, log_batch_api_rename_result
            
            results = []
            manager = get_library_manager()
            request_library = manager.get_library_definition(library_id) if library_id else None
            rename_service = RenameService()
            plan_semaphore = asyncio.Semaphore(max(1, min(2, len(paths))))
            rename_plans_by_library: dict[str, dict[str, Any]] = {}
            mutation_service = None
            prepared = None
            planned_effects_by_library: dict[str, list[dict[str, Any]]] = {}
            actual_effects_by_library: dict[str, list[dict[str, Any]]] = {}
            successful_library_ids: set[str] = set()
            ambiguous_local_error: Optional[Exception] = None

            def _plan_library(path_value: str):
                if request_library is not None:
                    return request_library
                return manager.find_local_library_for_path(path_value)

            async def _build_item_plan(item_index: int, raw_path: Any) -> dict[str, Any]:
                async with plan_semaphore:
                    path = str(raw_path or "").strip()
                    item_library = _plan_library(path)
                    item_is_remote = bool(item_library and item_library.type == "synology_filestation")
                    child_rjcode = ""
                    old_name = str(PurePosixPath(path).name) if item_is_remote else (os.path.basename(path) if path else "")
                    new_name = ""
                    try:
                        # 提取 RJ 号
                        rj_match = re.search(r'[RVB]J\d{6,8}', old_name, re.IGNORECASE)
                        if not rj_match:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=False,
                                source_path=path,
                                old_name=old_name,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                error="无法提取 RJ 号",
                            )
                            return {
                                "item_index": item_index,
                                "result": {
                                    "path": path,
                                    "success": False,
                                    "error": "无法提取 RJ 号",
                                },
                            }
                        if item_library is None:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=False,
                                source_path=path,
                                old_name=old_name,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                error="无法匹配库存库",
                            )
                            return {
                                "item_index": item_index,
                                "result": {
                                    "path": path,
                                    "success": False,
                                    "error": "无法匹配库存库",
                                },
                            }

                        rjcode = rj_match.group(0).upper()
                        child_rjcode = rjcode

                        # 创建临时任务
                        temp_task = Task(task_type=TaskType.METADATA, source_path=path, rjcode=rjcode)
                        temp_task.task_metadata = {
                            "rjcode": rjcode,
                            "rjcode_lock": True,
                        }

                        # 获取元数据
                        metadata_service = MetadataService()
                        metadata = await metadata_service.fetch(path, temp_task)
                        skip_reason = _api_rename_metadata_skip_reason(metadata, rjcode)
                        verification_status = str(
                            metadata.get("metadata_verification_status") or "unverified"
                        )
                        verification_reason = str(
                            metadata.get("metadata_verification_reason") or skip_reason or ""
                        )
                        logger.info(
                            "[批量 API重命名] 元数据结果 path=%s rj=%s metadata_source=%s dlsite_circuit_open=%s skip=%s",
                            path,
                            rjcode,
                            metadata.get("metadata_source") or "",
                            bool(metadata.get("dlsite_circuit_open")),
                            skip_reason,
                        )
                        if skip_reason:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=False,
                                source_path=path,
                                old_name=old_name,
                                rjcode=child_rjcode or None,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                error=skip_reason,
                                status="skipped",
                                extra_detail={
                                    "metadata_source": metadata.get("metadata_source") or "",
                                    "dlsite_circuit_open": bool(metadata.get("dlsite_circuit_open")),
                                    "rename_skipped_reason": skip_reason,
                                    "metadata_verification_status": verification_status,
                                    "metadata_verification_reason": verification_reason,
                                },
                            )
                            return {
                                "item_index": item_index,
                                "result": {
                                    "path": path,
                                    "success": False,
                                    "skipped": True,
                                    "error": skip_reason,
                                    "metadata_source": metadata.get("metadata_source") or "",
                                    "metadata_verification_status": verification_status,
                                    "metadata_verification_reason": verification_reason,
                                },
                            }

                        # 生成新名称
                        config = get_config()
                        japanese_metadata = None
                        if config.rename.use_japanese_metadata:
                            japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
                        new_name = rename_service._compile_name(metadata, japanese_metadata)
                        new_name = rename_service._sanitize_filename(new_name)

                        # 只生成计划；真实重命名按 library 聚合后一次 manager.batch_rename()。
                        if item_is_remote:
                            parent_dir = str(PurePosixPath(path).parent)
                            new_path = str(PurePosixPath(parent_dir) / new_name)
                        else:
                            parent_dir = os.path.dirname(path)
                            new_path = os.path.join(parent_dir, new_name)

                        if not item_is_remote and os.path.exists(new_path) and new_path != path:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=False,
                                source_path=path,
                                old_name=old_name,
                                new_name=new_name,
                                rjcode=child_rjcode or None,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                error="新名称已存在",
                            )
                            return {
                                "item_index": item_index,
                                "result": {
                                    "path": path,
                                    "success": False,
                                    "error": "新名称已存在",
                                },
                            }
                        if new_path == path:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=True,
                                source_path=path,
                                new_path=new_path,
                                old_name=old_name,
                                new_name=new_name,
                                rjcode=child_rjcode or None,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                extra_detail={"no_change": True},
                            )
                            return {
                                "item_index": item_index,
                                "result": {
                                    "path": path,
                                    "success": True,
                                    "message": "名称已是最新",
                                    "new_name": new_name,
                                    "new_path": path,
                                    "metadata_verification_status": verification_status,
                                    "metadata_verification_reason": verification_reason,
                                },
                            }

                        return {
                            "item_index": item_index,
                            "plan": {
                                "library": item_library,
                                "path": path,
                                "new_path": new_path,
                                "old_name": old_name,
                                "new_name": new_name,
                                "rjcode": child_rjcode,
                                "metadata_verification_status": verification_status,
                                "metadata_verification_reason": verification_reason,
                            },
                        }

                    except Exception as e:
                        logger.error(f"批量 API 重命名失败：{path}, {e}")
                        try:
                            log_api_rename_action(
                                action="batch_api_rename_item",
                                success=False,
                                source_path=path,
                                old_name=old_name,
                                new_name=new_name,
                                rjcode=child_rjcode or None,
                                batch_id=batch_id,
                                library_id=str(library_id or "") or None,
                                error=str(e),
                            )
                        except Exception:
                            logger.debug("[操作记录] 批量 API 重命名子项失败记录失败", exc_info=True)
                        return {
                            "item_index": item_index,
                            "result": {
                                "path": path,
                                "success": False,
                                "error": str(e),
                            },
                        }

            item_outputs = await asyncio.gather(
                *(_build_item_plan(index, path) for index, path in enumerate(paths))
            )

            for output in item_outputs:
                immediate_result = output.get("result")
                if immediate_result is not None:
                    results.append(immediate_result)
                    continue
                plan = output.get("plan")
                if not plan:
                    continue
                bucket = rename_plans_by_library.setdefault(
                    plan["library"].id,
                    {"library": plan["library"], "items": [], "meta": {}},
                )
                index = len(bucket["items"])
                bucket["items"].append({"index": index, "path": plan["path"], "new_name": plan["new_name"]})
                bucket["meta"][index] = {
                    "path": plan["path"],
                    "new_path": plan["new_path"],
                    "old_name": plan["old_name"],
                    "new_name": plan["new_name"],
                    "rjcode": plan["rjcode"],
                    "metadata_verification_status": plan["metadata_verification_status"],
                    "metadata_verification_reason": plan["metadata_verification_reason"],
                }

            for bucket in rename_plans_by_library.values():
                item_library = bucket["library"]
                if item_library.type != "local":
                    continue
                for index, meta in bucket["meta"].items():
                    effects = _local_rename_effects(
                        item_library,
                        meta["path"],
                        meta["new_path"],
                    )
                    meta["index_effects"] = effects
                    planned_effects_by_library.setdefault(item_library.id, []).extend(effects)

            if planned_effects_by_library:
                mutation_service = get_library_index_mutation_service()
                prepared = mutation_service.prepare(
                    kind="batch_api_rename",
                    effects_by_library=planned_effects_by_library,
                    idempotency_key=idempotency_key,
                )
                replay = _prepared_replay_response(prepared)
                if replay is not None:
                    return {"replay": replay}
                mutation_service.mark_filesystem_started(prepared.operation_id)

            for bucket in rename_plans_by_library.values():
                item_library = bucket["library"]
                try:
                    batch_result = await manager.batch_rename(
                        item_library.id,
                        bucket["items"],
                        skip_index_mutation=prepared is not None and item_library.type == "local",
                        sync_index_mutation=False,
                    )
                except Exception as exc:
                    for index, meta in bucket["meta"].items():
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=meta["path"],
                            old_name=meta["old_name"],
                            new_name=meta["new_name"],
                            rjcode=meta["rjcode"] or None,
                            batch_id=batch_id,
                            library_id=item_library.id,
                            error=str(exc),
                        )
                        results.append({"path": meta["path"], "success": False, "error": str(exc)})
                    if prepared is not None and item_library.type == "local":
                        ambiguous_local_error = exc
                        break
                    continue

                failed_by_index = {
                    int(item.get("index") or 0): str(item.get("error") or "重命名失败")
                    for item in (batch_result.get("failed") or [])
                }
                success_indexes = {
                    int(item.get("index") or 0): item
                    for item in (batch_result.get("results") or [])
                }
                for index, meta in bucket["meta"].items():
                    error = failed_by_index.get(index, "")
                    if error:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=meta["path"],
                            old_name=meta["old_name"],
                            new_name=meta["new_name"],
                            rjcode=meta["rjcode"] or None,
                            batch_id=batch_id,
                            library_id=item_library.id,
                            error=error,
                        )
                        results.append({"path": meta["path"], "success": False, "error": error})
                        continue
                    rename_result = success_indexes.get(index) or {}
                    new_path = str(rename_result.get("new_path") or meta["new_path"])
                    log_api_rename_action(
                        action="batch_api_rename_item",
                        success=True,
                        source_path=meta["path"],
                        new_path=new_path,
                        old_name=meta["old_name"],
                        new_name=meta["new_name"],
                        rjcode=meta["rjcode"] or None,
                        batch_id=batch_id,
                        library_id=item_library.id,
                    )
                    results.append({
                        "path": meta["path"],
                        "success": True,
                        "new_path": new_path,
                        "new_name": meta["new_name"],
                        "metadata_verification_status": meta["metadata_verification_status"],
                        "metadata_verification_reason": meta["metadata_verification_reason"],
                    })
                    successful_library_ids.add(item_library.id)
                    if meta.get("index_effects"):
                        actual_effects_by_library.setdefault(item_library.id, []).extend(
                            meta["index_effects"]
                        )
            
            # 保存结果（可选：保存到文件或数据库）
            logger.info(f"批量 API重命名完成：batch_id={batch_id}, success={sum(1 for r in results if r['success'])}/{len(results)}")
            try:
                log_batch_api_rename_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=sum(1 for r in results if r.get('success')),
                    failed_count=sum(1 for r in results if not r.get('success')),
                    results=results,
                    source_path=str(paths[0] or "").strip() if paths else "",
                )
            except Exception:
                logger.debug("[操作记录] 批量 API 重命名汇总记录失败", exc_info=True)
            for successful_library_id in successful_library_ids:
                _invalidate_rj_subtitle_folder_summary_cache(successful_library_id)
            return {
                "results": results,
                "prepared": prepared,
                "mutation_service": mutation_service,
                "actual_effects_by_library": actual_effects_by_library,
                "ambiguous_local_error": ambiguous_local_error,
            }
        
        async def process_batch_response():
            outcome = await process_batch()
            if outcome.get("replay") is not None:
                return outcome["replay"]
            results = outcome["results"]
            success_count = sum(1 for item in results if item.get("success"))
            failed_count = sum(1 for item in results if not item.get("success"))

            response = {
                "batch_id": batch_id,
                "message": f"批量重命名完成，共 {len(paths)} 项",
                "total_count": len(paths),
                "success_count": success_count,
                "failed_count": failed_count,
                "results": results,
                "failed": [item for item in results if not item.get("success")],
            }
            prepared = outcome.get("prepared")
            mutation_service = outcome.get("mutation_service")
            if prepared is not None:
                ambiguous_local_error = outcome.get("ambiguous_local_error")
                if ambiguous_local_error is not None:
                    mutation_service.mark_reconcile_required(prepared.operation_id, ambiguous_local_error)
                    return JSONResponse(
                        status_code=202,
                        content={
                            **response,
                            "operation_id": prepared.operation_id,
                            "operation_state": "reconcile_required",
                            "reconciliation_pending": True,
                        },
                    )
                try:
                    response = mutation_service.finalize(
                        prepared.operation_id,
                        actual_effects_by_library=outcome["actual_effects_by_library"],
                        actual_result=response,
                    )
                except Exception as exc:
                    mutation_service.mark_reconcile_required(prepared.operation_id, exc)
                    return JSONResponse(
                        status_code=202,
                        content={
                            **response,
                            "operation_id": prepared.operation_id,
                            "operation_state": "reconcile_required",
                            "reconciliation_pending": True,
                        },
                    )
            return response

        batch_task = asyncio.create_task(process_batch_response())
        _BATCH_API_RENAME_INFLIGHT[request_key] = batch_task

        def _cleanup_batch_api_rename(done_task):
            if _BATCH_API_RENAME_INFLIGHT.get(request_key) is done_task:
                _BATCH_API_RENAME_INFLIGHT.pop(request_key, None)

        batch_task.add_done_callback(_cleanup_batch_api_rename)
        return await asyncio.shield(batch_task)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量 API 重命名失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量重命名失败：{str(e)}")


@app.post("/api/library/open-folder")
async def open_library_folder(request: Request):
    """打开文件夹位置"""
    try:
        data = await request.json()
        path = data.get("path")
        force_local = data.get("force_local", False)  # 是否强制使用本地映射
        
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        # 检查路径映射配置
        config = get_config()
        mapped_path, is_mapped = map_path_to_local(path)
        
        # 判断打开模式
        open_mode = config.path_mapping.open_mode
        if force_local or open_mode == "mapped":
            # 使用映射路径打开
            target_path = mapped_path
            # 在映射模式下，不检查路径是否存在（因为后端无法访问客户端路径）
            logger.info(f"使用映射路径打开: {path} -> {target_path}")
            
            return {
                "message": "请使用本地路径打开",
                "mode": "mapped",
                "original_path": path,
                "mapped_path": target_path,
                "is_mapped": is_mapped
            }
        
        # 直接模式：后端直接打开（同设备部署）
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="路径不存在")
        
        # 获取文件夹路径（如果是文件，则获取所在文件夹）
        folder_path = path if os.path.isdir(path) else os.path.dirname(path)
        
        # 根据操作系统打开文件夹
        import platform
        import subprocess
        
        system = platform.system()
        if system == "Windows":
            # 使用 os.startfile 打开文件夹，更好地支持中文和特殊字符
            if os.path.isdir(path):
                # 如果是文件夹，直接打开
                os.startfile(path)
            else:
                # 如果是文件，使用 explorer /select 选中它
                # 使用字符串形式避免引号问题
                cmd = f'explorer /select,"{path}"'
                subprocess.run(cmd, shell=True, check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", "-R", path], check=True)
        else:  # Linux
            subprocess.run(["xdg-open", folder_path], check=True)
        
        return {"message": "已打开文件夹", "mode": "direct"}
        
    except Exception as e:
        logger.error(f"打开文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {str(e)}")

# 路径映射配置API
@app.get("/api/path-mapping/config")
async def get_path_mapping_config():
    """获取路径映射配置"""
    config = get_config().path_mapping
    return {
        "enabled": config.enabled,
        "open_mode": config.open_mode,
        "rules": [
            {
                "remote_path": rule.remote_path,
                "local_path": rule.local_path,
                "enabled": rule.enabled
            }
            for rule in config.rules
        ]
    }

@app.post("/api/path-mapping/config")
async def update_path_mapping_config(request: Request):
    """更新路径映射配置"""
    try:
        data = await request.json()
        config = get_config()
        
        # 更新配置
        config.path_mapping.enabled = data.get("enabled", config.path_mapping.enabled)
        config.path_mapping.open_mode = data.get("open_mode", config.path_mapping.open_mode)
        
        # 更新规则
        if "rules" in data:
            from app.config.settings import PathMappingRule
            config.path_mapping.rules = [
                PathMappingRule(**rule) for rule in data["rules"]
            ]
        
        # 保存配置
        save_config(config)
        
        return {"message": "路径映射配置已更新"}
        
    except Exception as e:
        logger.error(f"更新路径映射配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@app.post("/api/path-mapping/test")
async def test_path_mapping(request: Request):
    """测试路径映射"""
    try:
        data = await request.json()
        remote_path = data.get("path")
        
        if not remote_path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        mapped_path, is_mapped = map_path_to_local(remote_path)
        
        return {
            "original_path": remote_path,
            "mapped_path": mapped_path,
            "is_mapped": is_mapped
        }
        
    except Exception as e:
        logger.error(f"测试路径映射失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")

# 密码库智能清理API
@app.get("/api/password-cleanup/status")
async def get_cleanup_status():
    """获取清理服务状态"""
    service = get_cleanup_service()
    config = get_config().password_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "max_use_count": config.max_use_count,
        "preserve_days": config.preserve_days,
        "exclude_sources": config.exclude_sources,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/password-cleanup/preview")
async def preview_cleanup():
    """预览将要清理的密码（不实际删除）"""
    service = get_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/password-cleanup/run")
async def run_cleanup():
    """手动执行清理"""
    service = get_cleanup_service()
    result = await service.cleanup_passwords(dry_run=False)
    return result

@app.get("/api/password-cleanup/history")
async def get_cleanup_history(limit: int = 50):
    """获取清理历史记录"""
    service = get_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/password-cleanup/restart")
async def restart_cleanup_service():
    """重启清理服务（配置变更后调用）"""
    service = get_cleanup_service()
    await service.restart()
    return {
        "message": "密码库清理服务已重启",
        "status": await get_cleanup_status()
    }

# 已处理压缩包智能清理API
@app.get("/api/processed-archive-cleanup/status")
async def get_archive_cleanup_status():
    """获取已处理压缩包清理服务状态"""
    service = get_processed_archive_cleanup_service()
    config = get_config().processed_archive_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "strategy": config.strategy,
        "preserve_days": config.preserve_days,
        "max_count": config.max_count,
        "max_size_gb": config.max_size_gb,
        "exclude_reprocessing": config.exclude_reprocessing,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/processed-archive-cleanup/preview")
async def preview_archive_cleanup():
    """预览将要清理的已处理压缩包（不实际删除）"""
    service = get_processed_archive_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/processed-archive-cleanup/run")
async def run_archive_cleanup():
    """手动执行已处理压缩包清理"""
    service = get_processed_archive_cleanup_service()
    result = await service.cleanup_archives(dry_run=False)
    return result

@app.get("/api/processed-archive-cleanup/history")
async def get_archive_cleanup_history(limit: int = 50):
    """获取已处理压缩包清理历史记录"""
    service = get_processed_archive_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/processed-archive-cleanup/restart")
async def restart_archive_cleanup_service():
    """重启已处理压缩包清理服务（配置变更后调用）"""
    service = get_processed_archive_cleanup_service()
    await service.restart()
    return {
        "message": "已处理压缩包清理服务已重启",
        "status": await get_archive_cleanup_status()
    }

# ========== 已存在文件夹处理 API ==========

class ExistingFolderResponse(BaseModel):
    """已存在文件夹响应模型"""
    name: str
    path: str
    rjcode: Optional[str]
    modified_time: str
    size: int
    is_directory: bool
    relative_path: Optional[str] = None
    source_root: Optional[str] = None
    source_root_name: Optional[str] = None
    is_nested: bool = False
    scan_depth: int = 1
    rjcode_source: Optional[str] = None


def _normalize_existing_folder_resolution_options(options: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    alias_map = {
        "KEEP_OLD": "SKIP",
        "KEEP_BOTH": "MERGE",
        "MERGE_LANG": "MERGE",
    }
    label_map = {
        "KEEP_NEW": "保留新版",
        "MERGE": "合并",
        "SKIP": "跳过",
    }
    description_map = {
        "KEEP_NEW": "采用当前新目录作为最终结果，并在确认后替换已存在目录",
        "MERGE": "进入文件级对比视图，按文件决定保留新旧内容后生成最终目录",
        "SKIP": "放弃当前目录，保持已有目录不变并删除当前待处理目录",
    }

    for option in options or []:
        action = alias_map.get(str(option.get("action") or "").strip().upper(), str(option.get("action") or "").strip().upper())
        if action not in {"KEEP_NEW", "MERGE", "SKIP"} or action in seen:
            continue
        normalized.append({
            "action": action,
            "label": label_map[action],
            "description": option.get("description") or description_map[action],
            "recommend": bool(option.get("recommend")),
        })
        seen.add(action)

    if normalized:
        return normalized

    return [
        {
            "action": "KEEP_NEW",
            "label": "保留新版",
            "description": description_map["KEEP_NEW"],
            "recommend": True,
        },
        {
            "action": "MERGE",
            "label": "合并",
            "description": description_map["MERGE"],
            "recommend": False,
        },
        {
            "action": "SKIP",
            "label": "跳过",
            "description": description_map["SKIP"],
            "recommend": False,
        },
    ]


def _build_existing_folder_info(candidate: dict) -> dict:
    path = str(candidate.get("path") or "")
    name = str(candidate.get("name") or os.path.basename(path.rstrip("\\/")) or path)
    folder_info = {
        "name": name,
        "path": path,
        "rjcode": candidate.get("rjcode"),
        "status": "pending",
        "relative_path": candidate.get("relative_path") or name,
        "source_root": candidate.get("source_root") or path,
        "source_root_name": candidate.get("source_root_name") or name,
        "is_nested": bool(candidate.get("is_nested")),
        "scan_depth": int(candidate.get("scan_depth") or 1),
        "rjcode_source": candidate.get("rjcode_source") or "",
    }
    try:
        stat = os.stat(path)
        folder_info["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except Exception:
        folder_info["modified_time"] = ""
    return folder_info


def _collect_existing_folder_stats(folder_path: str) -> tuple[int, int]:
    folder_size = 0
    file_count = 0
    try:
        for root, _dirs, files in os.walk(folder_path):
            file_count += len(files)
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    folder_size += os.path.getsize(file_path)
    except Exception:
        pass
    return file_count, folder_size


def _existing_folder_path_key(path: str) -> str:
    normalized = os.path.abspath(os.path.normpath(str(path or "")))
    return os.path.normcase(normalized) if os.name == "nt" else normalized


def _existing_folder_source_root(path: str, existing_root: str) -> tuple[str, str, str, bool]:
    base = os.path.abspath(os.path.normpath(str(existing_root or "")))
    target = os.path.abspath(os.path.normpath(str(path or "")))
    try:
        relative_path = os.path.relpath(target, base).replace("\\", "/")
    except Exception:
        relative_path = os.path.basename(target.rstrip("\\/")) or target

    first_part = relative_path.split("/", 1)[0] if relative_path and relative_path != "." else ""
    source_root = os.path.join(base, first_part) if first_part else target
    source_root = os.path.abspath(os.path.normpath(source_root))
    source_root_name = os.path.basename(source_root.rstrip("\\/")) or source_root
    is_nested = _existing_folder_path_key(source_root) != _existing_folder_path_key(target)
    return relative_path, source_root, source_root_name, is_nested


def _existing_folder_candidate_result(candidate: dict, resolved_from: str | None = None) -> dict:
    path = os.path.abspath(os.path.normpath(str(candidate.get("path") or "")))
    return {
        "ok": True,
        "path": path,
        "folder_name": candidate.get("name") or os.path.basename(path.rstrip("\\/")) or path,
        "rjcode": candidate.get("rjcode"),
        "resolved_from": os.path.abspath(os.path.normpath(str(resolved_from or path))),
        "source_root": candidate.get("source_root") or path,
        "source_root_name": candidate.get("source_root_name") or os.path.basename(path.rstrip("\\/")) or path,
        "relative_path": candidate.get("relative_path") or os.path.basename(path.rstrip("\\/")) or path,
        "is_nested": bool(candidate.get("is_nested")),
        "scan_depth": int(candidate.get("scan_depth") or 1),
        "rjcode_source": candidate.get("rjcode_source") or "folder_name",
    }


def _resolve_existing_folder_candidate_path(
    folder_path: str,
    existing_root: str,
    candidates: list[dict] | None = None,
) -> dict:
    """把请求中的路径解析成单个可处理候选目录。"""
    normalized_path = os.path.abspath(os.path.normpath(str(folder_path or "")))
    if not _is_path_under_base(normalized_path, existing_root):
        return {"ok": False, "path": normalized_path, "reason": "路径不在已存在文件夹目录下"}
    if not os.path.exists(normalized_path) or not os.path.isdir(normalized_path):
        return {"ok": False, "path": normalized_path, "reason": "路径不存在或不是文件夹"}

    known_candidates = candidates if candidates is not None else scan_existing_folder_candidates(existing_root)
    rj_candidates = [item for item in known_candidates if item.get("rjcode")]
    target_key = _existing_folder_path_key(normalized_path)

    for candidate in rj_candidates:
        if _existing_folder_path_key(candidate.get("path") or "") == target_key:
            return _existing_folder_candidate_result(candidate, normalized_path)

    nested_candidates = [
        item for item in rj_candidates
        if _is_path_under_base(item.get("path") or "", normalized_path)
    ]
    if len(nested_candidates) == 1:
        return _existing_folder_candidate_result(nested_candidates[0], normalized_path)
    if len(nested_candidates) > 1:
        return {
            "ok": False,
            "path": normalized_path,
            "reason": "该目录下包含多个 RJ 作品，请刷新后选择具体作品目录",
            "candidate_count": len(nested_candidates),
        }

    folder_name = os.path.basename(normalized_path.rstrip("\\/")) or normalized_path
    rjcode = extract_rjcode(folder_name)
    if rjcode:
        relative_path, source_root, source_root_name, is_nested = _existing_folder_source_root(normalized_path, existing_root)
        return {
            "ok": True,
            "path": normalized_path,
            "folder_name": folder_name,
            "rjcode": rjcode,
            "resolved_from": normalized_path,
            "source_root": source_root,
            "source_root_name": source_root_name,
            "relative_path": relative_path,
            "is_nested": is_nested,
            "scan_depth": len([part for part in relative_path.split("/") if part and part != "."]),
            "rjcode_source": "folder_name",
        }
    return {"ok": False, "path": normalized_path, "reason": "无法提取RJ号"}


async def _resolve_existing_folder_conflict_path(folder_path: str, preferred_path: str | None = None) -> str | None:
    if preferred_path and os.path.exists(preferred_path):
        return preferred_path

    from ..core.duplicate_service import get_duplicate_service

    rjcode = extract_rjcode_from_path(folder_path, search_subfolders=True)
    if not rjcode:
        return None

    duplicate_service = get_duplicate_service()
    check_result = await duplicate_service.check_duplicate_enhanced(
        rjcode,
        check_linked_works=True,
        cue_languages=["CHI_HANS", "CHI_HANT", "ENG"],
    )
    if check_result.direct_duplicate:
        return check_result.direct_duplicate.get("path")
    if check_result.linked_works_found:
        return check_result.linked_works_found[0].get("path")
    return None

@app.get("/api/existing-folders", response_model=List[ExistingFolderResponse])
async def get_existing_folders():
    """获取已存在文件夹目录中的所有文件夹"""
    try:
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        # 如果目录不存在，返回空列表
        if not os.path.exists(existing_folders_path):
            return []
        
        folders = []
        for candidate in scan_existing_folder_candidates(existing_folders_path):
            folder_info = _build_existing_folder_info(candidate)
            item_path = folder_info["path"]
            try:
                stat = os.stat(item_path)
                _file_count, size = _collect_existing_folder_stats(item_path)
                
                folders.append(ExistingFolderResponse(
                    name=folder_info["name"],
                    path=item_path,
                    rjcode=folder_info.get("rjcode"),
                    modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    size=size,
                    is_directory=True,
                    relative_path=folder_info.get("relative_path"),
                    source_root=folder_info.get("source_root"),
                    source_root_name=folder_info.get("source_root_name"),
                    is_nested=bool(folder_info.get("is_nested")),
                    scan_depth=int(folder_info.get("scan_depth") or 1),
                    rjcode_source=folder_info.get("rjcode_source"),
                ))
            except Exception as e:
                logger.warning(f"获取文件夹信息失败: {item_path}, {e}")
        
        # 按修改时间排序（最新的在前）
        folders.sort(key=lambda x: x.modified_time, reverse=True)
        
        return folders
        
    except Exception as e:
        logger.error(f"获取已存在文件夹列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")

@app.post("/api/existing-folders/scan")
async def scan_existing_folders(check_duplicates: bool = True, force_refresh: bool = False):
    """扫描已存在文件夹目录，先快速列出所有文件夹，再后台查重
    
    Args:
        check_duplicates: 是否执行查重检查
        force_refresh: 是否强制刷新缓存
    """
    async def generate_folders():
        queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=100)

        async def emit(payload: dict):
            await queue.put(payload)

        async def scan_worker():
            db = None
            folders = []
            conflict_count = 0
            try:
                config = get_config()
                existing_folders_path = config.storage.existing_folders_path

                # 自动创建目录（如果不存在）
                if not os.path.exists(existing_folders_path):
                    try:
                        os.makedirs(existing_folders_path, exist_ok=True)
                        logger.info(f"自动创建已存在文件夹目录: {existing_folders_path}")
                    except Exception as e:
                        await emit({"type": "error", "error": f"无法创建目录: {str(e)}"})
                        return

                # 第一步：快速列出所有 RJ 作品候选（支持 已有目录/社团名/RJxxxx 这种嵌套结构）
                candidates = await asyncio.to_thread(scan_existing_folder_candidates, existing_folders_path)

                await emit({
                    "type": "start",
                    "total": len(candidates),
                    "message": f"开始扫描，共 {len(candidates)} 个候选目录"
                })

                # 先发送所有文件夹基本信息（立即可见）
                for index, candidate in enumerate(candidates):
                    folder_info = _build_existing_folder_info(candidate)
                    folders.append(folder_info)

                    await emit({
                        "type": "folder",
                        "index": index,
                        "total": len(candidates),
                        "folder": folder_info,
                        "progress": f"{index + 1}/{len(candidates)}"
                    })

                # 第二步：后台逐个查重（如果有RJ号且需要检查）
                if check_duplicates:
                    await emit({
                        "type": "checking_start",
                        "message": f"开始查重检查，共 {len(folders)} 个文件夹"
                    })

                    from ..core.duplicate_service import get_duplicate_service
                    from ..models.database import ExistingFolderCache, get_db
                    db = next(get_db())
                    duplicate_service = get_duplicate_service()
                    cache_by_path = {}
                    if not force_refresh:
                        try:
                            paths = [item["path"] for item in folders if item.get("path") and item.get("rjcode")]
                            if paths:
                                cache_rows = db.query(ExistingFolderCache).filter(
                                    ExistingFolderCache.folder_path.in_(paths)
                                ).all()
                                cache_by_path = {row.folder_path: row for row in cache_rows}
                        except Exception as e:
                            logger.warning(f"批量查询已有文件夹缓存失败: {e}")

                    for index, folder_info in enumerate(folders):
                        item_path = folder_info["path"]
                        item = folder_info["name"]
                        rjcode = folder_info["rjcode"]

                        if not rjcode:
                            folder_info["status"] = "unrecognized"
                            await emit({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "error": "无法提取RJ号"
                            })
                            continue

                        # 检查缓存
                        cache = None if force_refresh else cache_by_path.get(item_path)

                        # 如果有缓存且不需要刷新，直接使用缓存
                        if cache and not force_refresh and not cache.needs_refresh:
                            folder_info["duplicate_info"] = cache.duplicate_info
                            folder_info["file_count"] = cache.file_count
                            folder_info["folder_size"] = cache.folder_size
                            folder_info["status"] = "cached"
                            if cache.duplicate_info:
                                conflict_count += 1

                            await emit({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": True
                            })
                            continue

                        # 没有缓存，执行API查询
                        try:
                            # 添加延时避免429
                            if index > 0 and index % 5 == 0:
                                await asyncio.sleep(1)

                            check_result = await duplicate_service.check_duplicate_enhanced(
                                rjcode,
                                check_linked_works=True,
                                cue_languages=['CHI_HANS', 'CHI_HANT', 'ENG']
                            )

                            if check_result.is_duplicate:
                                folder_info["duplicate_info"] = {
                                    "is_duplicate": True,
                                    "conflict_type": check_result.conflict_type,
                                    "direct_duplicate": check_result.direct_duplicate,
                                    "linked_works_found": check_result.linked_works_found,
                                    "related_rjcodes": check_result.related_rjcodes,
                                    "analysis_info": check_result.analysis_info
                                }

                                # 获取推荐的解决选项
                                resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                                folder_info["duplicate_info"]["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)
                                conflict_count += 1

                            folder_info["status"] = "checked"

                            # 计算文件夹大小
                            file_count, folder_size = await asyncio.to_thread(_collect_existing_folder_stats, item_path)

                            folder_info["file_count"] = file_count
                            folder_info["folder_size"] = folder_size

                            # 保存到缓存
                            try:
                                from ..models.database import ExistingFolderCache
                                if cache:
                                    cache.duplicate_info = folder_info.get("duplicate_info")
                                    cache.file_count = file_count
                                    cache.folder_size = folder_size
                                    cache.updated_at = datetime.now()
                                    cache.needs_refresh = False
                                else:
                                    cache = ExistingFolderCache(
                                        folder_path=item_path,
                                        folder_name=item,
                                        rjcode=rjcode,
                                        duplicate_info=folder_info.get("duplicate_info"),
                                        file_count=file_count,
                                        folder_size=folder_size
                                    )
                                    db.add(cache)
                                db.commit()
                            except Exception as e:
                                logger.warning(f"保存缓存失败: {e}")
                                db.rollback()

                            await emit({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": False
                            })

                        except Exception as e:
                            logger.warning(f"查重检查失败 {rjcode}: {e}")
                            folder_info["status"] = "error"
                            await emit({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "error": str(e)
                            })

                    await emit({
                        "type": "complete",
                        "count": len(folders),
                        "conflict_count": conflict_count,
                        "folders": folders,
                        "message": f"扫描完成，找到 {len(folders)} 个文件夹" + (f"，其中 {conflict_count} 个可能有冲突" if conflict_count > 0 else "")
                    })
                else:
                    await emit({
                        "type": "complete",
                        "count": len(folders),
                        "conflict_count": 0,
                        "folders": folders,
                        "message": f"扫描完成，找到 {len(folders)} 个文件夹"
                    })

            except Exception as e:
                logger.error(f"扫描已存在文件夹目录失败: {e}", exc_info=True)
                await emit({"type": "error", "error": f"扫描失败: {str(e)}"})
            finally:
                if db is not None:
                    db.close()
                await queue.put(None)

        worker = asyncio.create_task(scan_worker())
        yield json.dumps({
            "type": "start",
            "total": 0,
            "message": "准备扫描已有文件夹目录"
        }) + "\n"

        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=4)
                except asyncio.TimeoutError:
                    yield json.dumps({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat(),
                    }) + "\n"
                    continue

                if payload is None:
                    break
                yield json.dumps(payload) + "\n"
        finally:
            if not worker.done():
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
    
    return StreamingResponse(
        generate_folders(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity"
        }
    )

@app.post("/api/existing-folders/refresh-cache")
async def refresh_existing_folders_cache():
    """刷新所有已有文件夹的缓存信息"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 标记所有缓存需要刷新
            db.query(ExistingFolderCache).update({"needs_refresh": True})
            db.commit()
            
            return {"message": "已标记所有缓存需要刷新，下次扫描时将重新获取信息"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"刷新缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"刷新缓存失败: {str(e)}")

@app.post("/api/existing-folders/clear-cache")
async def clear_existing_folders_cache():
    """清除所有已有文件夹的缓存"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 删除所有缓存
            deleted_count = db.query(ExistingFolderCache).delete()
            db.commit()
            
            return {"message": f"已清除 {deleted_count} 条缓存"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"清除缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/existing-folders/check-duplicates")
async def check_existing_folders_duplicates(request: Request):
    """批量检查已有文件夹的查重情况
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "check_linked_works": true,
        "cue_languages": ["CHI_HANS", "CHI_HANT", "ENG"]
    }
    """
    db = None
    try:
        data = await request.json()
        folder_paths = data.get("folders", [])
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT", "ENG"])
        
        if not folder_paths:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        from ..core.duplicate_service import get_duplicate_service
        duplicate_service = get_duplicate_service()
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        candidates = None
        try:
            from ..models.database import ExistingFolderCache, get_db
            db = next(get_db())
        except Exception as e:
            logger.warning(f"打开已有文件夹缓存数据库失败，查重结果仅返回前端: {e}")
        
        resolved_items = []
        results = []
        for requested_path in folder_paths:
            normalized_requested_path = os.path.abspath(os.path.normpath(str(requested_path or "")))
            folder_name = os.path.basename(normalized_requested_path.rstrip("\\/")) or normalized_requested_path
            rjcode = extract_rjcode(folder_name)
            if (
                rjcode
                and _is_path_under_base(normalized_requested_path, existing_folders_path)
                and os.path.isdir(normalized_requested_path)
            ):
                relative_path, source_root, source_root_name, is_nested = _existing_folder_source_root(normalized_requested_path, existing_folders_path)
                resolved = {
                    "ok": True,
                    "path": normalized_requested_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "resolved_from": normalized_requested_path,
                    "source_root": source_root,
                    "source_root_name": source_root_name,
                    "relative_path": relative_path,
                    "is_nested": is_nested,
                    "scan_depth": len([part for part in relative_path.split("/") if part and part != "."]),
                    "rjcode_source": "folder_name",
                }
            else:
                if candidates is None:
                    candidates = scan_existing_folder_candidates(existing_folders_path)
                resolved = _resolve_existing_folder_candidate_path(requested_path, existing_folders_path, candidates)
            resolved_items.append((requested_path, resolved))

        cache_by_path = {}
        if db is not None:
            try:
                resolved_paths = [
                    item[1].get("path")
                    for item in resolved_items
                    if item[1].get("ok") and item[1].get("path")
                ]
                if resolved_paths:
                    cache_rows = db.query(ExistingFolderCache).filter(
                        ExistingFolderCache.folder_path.in_(resolved_paths)
                    ).all()
                    cache_by_path = {row.folder_path: row for row in cache_rows}
            except Exception as cache_error:
                logger.warning(f"批量读取已有文件夹查重缓存失败: {cache_error}")

        for requested_path, resolved in resolved_items:
            folder_path = resolved.get("path") or requested_path
            folder_name = resolved.get("folder_name") or os.path.basename(str(folder_path).rstrip("\\/"))
            rjcode = resolved.get("rjcode")
            
            if not resolved.get("ok") or not rjcode:
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": None,
                    "error": resolved.get("reason") or "无法提取RJ号"
                })
                continue
            
            try:
                check_result = await duplicate_service.check_duplicate_enhanced(
                    rjcode,
                    check_linked_works=check_linked,
                    cue_languages=cue_languages
                )
                
                result = {
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "is_duplicate": check_result.is_duplicate,
                    "conflict_type": check_result.conflict_type,
                }
                
                if check_result.is_duplicate:
                    result.update({
                        "direct_duplicate": check_result.direct_duplicate,
                        "linked_works_found": check_result.linked_works_found,
                        "related_rjcodes": check_result.related_rjcodes,
                        "analysis_info": check_result.analysis_info
                    })
                    
                    # 获取推荐的解决选项
                    resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                    result["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)

                if db is not None:
                    try:
                        file_count, folder_size = await asyncio.to_thread(_collect_existing_folder_stats, folder_path)
                        duplicate_info = None
                        if check_result.is_duplicate:
                            duplicate_info = {
                                "is_duplicate": True,
                                "conflict_type": check_result.conflict_type,
                                "direct_duplicate": check_result.direct_duplicate,
                                "linked_works_found": check_result.linked_works_found,
                                "related_rjcodes": check_result.related_rjcodes,
                                "analysis_info": check_result.analysis_info,
                                "resolution_options": result.get("resolution_options"),
                            }
                        cache = cache_by_path.get(folder_path)
                        if cache:
                            cache.folder_name = folder_name
                            cache.rjcode = rjcode
                            cache.duplicate_info = duplicate_info
                            cache.file_count = file_count
                            cache.folder_size = folder_size
                            cache.updated_at = datetime.now()
                            cache.needs_refresh = False
                        else:
                            cache = ExistingFolderCache(
                                folder_path=folder_path,
                                folder_name=folder_name,
                                rjcode=rjcode,
                                duplicate_info=duplicate_info,
                                file_count=file_count,
                                folder_size=folder_size,
                            )
                            db.add(cache)
                            cache_by_path[folder_path] = cache
                        db.commit()
                    except Exception as cache_error:
                        logger.warning(f"保存已有文件夹查重缓存失败: {folder_path}, error={cache_error}")
                        db.rollback()
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"查重检查失败 {rjcode}: {e}")
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "error": str(e)
                })
        
        # 统计
        duplicate_count = sum(1 for r in results if r.get("is_duplicate"))
        
        return {
            "message": f"检查完成，发现 {duplicate_count}/{len(results)} 个冲突",
            "total": len(results),
            "duplicate_count": duplicate_count,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")
    finally:
        if db is not None:
            db.close()

@app.post("/api/existing-folders/process")
async def process_existing_folders(request: Request):
    """处理选中的已存在文件夹
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "auto_classify": true
    }
    """
    try:
        from ..core.activity_log_service import log_import_batch_start_result
        data = await request.json()
        folders = data.get("folders", [])
        auto_classify = data.get("auto_classify", True)
        
        if not folders:
            raise HTTPException(status_code=400, detail="未选择任何文件夹")
        
        # 验证所有路径是否有效
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        candidates = scan_existing_folder_candidates(existing_folders_path)
        
        valid_folders = []
        skipped_folders = []
        for folder_path in folders:
            resolved = _resolve_existing_folder_candidate_path(folder_path, existing_folders_path, candidates)
            if not resolved.get("ok"):
                reason = resolved.get("reason") or "invalid_path"
                logger.warning(f"已有文件夹路径不可处理，跳过: {folder_path}, reason={reason}")
                skipped_folders.append({"folder_path": folder_path, "reason": reason})
                continue
            valid_folders.append(resolved)
        
        if not valid_folders:
            raise HTTPException(status_code=400, detail="没有有效的文件夹可以处理")
        
        # 创建处理任务
        engine = get_task_engine()
        created_tasks = []
        batch_id = str(uuid.uuid4())
        cache_by_path = {}
        try:
            from ..models.database import ExistingFolderCache, get_db
            db = next(get_db())
            try:
                cache_rows = db.query(ExistingFolderCache).filter(
                    ExistingFolderCache.folder_path.in_([item["path"] for item in valid_folders])
                ).all()
                cache_by_path = {row.folder_path: row for row in cache_rows}
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"读取已有文件夹查重缓存失败，将保留任务内预检: {e}")

        for folder_info in valid_folders:
            folder_path = folder_info["path"]
            folder_name = folder_info["folder_name"]
            inferred_rjcode = folder_info.get("rjcode")
            cache = cache_by_path.get(folder_path)
            cached_duplicate_info = getattr(cache, "duplicate_info", None) if cache else None
            skip_duplicate_precheck = (
                bool(cache)
                and not bool(getattr(cache, "needs_refresh", False))
                and (
                    cached_duplicate_info is None
                    or (
                        isinstance(cached_duplicate_info, dict)
                        and cached_duplicate_info.get("is_duplicate") is False
                    )
                )
            )
            task = Task(
                task_type=TaskType.PROCESS_EXISTING_FOLDER,
                source_path=folder_path,
                auto_classify=auto_classify,
                metadata={
                    "batch_id": batch_id,
                    "session_id": batch_id,
                    "batch_title": "批量已有目录处理",
                    "batch_label": "已有目录处理批次",
                    "batch_requested_count": len(valid_folders),
                    "batch_log_parent": True,
                    "source_page": "existing-folders",
                    "source_action": "process_existing_batch",
                    "source_label": "已有目录页 / 批量处理",
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "original_folder_path": folder_info.get("resolved_from") or folder_path,
                    "relative_path": folder_info.get("relative_path") or "",
                    "source_root": folder_info.get("source_root") or "",
                    "source_root_name": folder_info.get("source_root_name") or "",
                    "is_nested": bool(folder_info.get("is_nested")),
                    "scan_depth": int(folder_info.get("scan_depth") or 1),
                    "rjcode_source": folder_info.get("rjcode_source") or "existing_folder_scan",
                    "inferred_rjcode": inferred_rjcode,
                    "rjcode": inferred_rjcode,
                    "auto_classify": bool(auto_classify),
                    "skip_duplicate_precheck": bool(skip_duplicate_precheck),
                    "duplicate_precheck_source": "existing_folder_cache" if skip_duplicate_precheck else "",
                }
            )
            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "folder_path": folder_path,
                "rjcode": inferred_rjcode,
            })

        log_import_batch_start_result(
            {
                "batch_id": batch_id,
                "requested_count": len(valid_folders),
                "created_count": len(created_tasks),
                "skipped_total": max(0, len(folders) - len(valid_folders)),
                "archive_count": 0,
                "extracted_count": 0,
                "auto_classify": bool(auto_classify),
                "source_page": "existing-folders",
                "source_action": "process_existing_batch",
                "source_label": "已有目录页 / 批量处理",
                "source_paths": [item["path"] for item in valid_folders],
                "created_tasks": created_tasks,
                "skipped_items": skipped_folders,
                "source_path": valid_folders[0]["path"] if valid_folders else None,
            },
            category="process_existing",
        )

        return {
            "message": f"已创建 {len(created_tasks)} 个处理任务",
            "requested": len(folders),
            "created": len(created_tasks),
            "batch_id": batch_id,
            "tasks": created_tasks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理已存在文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@app.post("/api/existing-folders/delete")
async def delete_existing_folder(request: Request):
    """删除已有文件夹（用于抛弃新版）
    
    请求体格式：
    {
        "path": "/path/to/folder"
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("path")
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        folder_path = os.path.abspath(os.path.normpath(str(folder_path or "")))
        
        if not _is_path_under_base(folder_path, existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录下")
        
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="路径不是文件夹")
        
        # 删除文件夹
        import shutil
        _robust_rmtree(folder_path)
        logger.info(f"已删除文件夹: {folder_path}")
        
        return {"message": "文件夹已删除", "path": folder_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@app.post("/api/existing-folders/merge-preview")
async def get_existing_folder_merge_preview(request: Request):
    """生成已存在文件夹的合并对比预览"""
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        existing_path = data.get("existing_path")

        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供待处理文件夹路径")

        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        resolved_folder = _resolve_existing_folder_candidate_path(folder_path, existing_folders_path)
        if not resolved_folder.get("ok"):
            raise HTTPException(status_code=400, detail=resolved_folder.get("reason") or "待处理文件夹不可合并")
        folder_path = resolved_folder["path"]

        resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, existing_path)
        if not resolved_existing_path:
            raise HTTPException(status_code=404, detail="未找到可合并的现有目录")
        if not os.path.exists(resolved_existing_path):
            raise HTTPException(status_code=404, detail="目标现有目录不存在")

        from ..core.folder_compare_service import get_folder_compare_service

        compare_service = get_folder_compare_service()
        items = compare_service.build_compare_items(folder_path, resolved_existing_path)
        decisions = compare_service.build_default_decisions(items)

        summary = {
            "new_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "new_only"),
            "old_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "old_only"),
            "modified": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "modified"),
            "unchanged": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "unchanged"),
        }

        return {
            "folder_path": folder_path,
            "existing_path": resolved_existing_path,
            "items": items,
            "default_decisions": decisions,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成合并预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成合并预览失败: {str(e)}")

@app.post("/api/existing-folders/process-with-resolution")
async def process_existing_folder_with_resolution(request: Request):
    """使用指定的解决方案处理已有文件夹
    
    请求体格式：
    {
        "folder_path": "/path/to/folder",
        "resolution": "KEEP_NEW|MERGE|SKIP",
        "auto_classify": true,
        "existing_path": "/path/to/current/library/folder",
        "merge_decisions": {"relative/path.txt": "use_new"}
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        resolution = data.get("resolution")
        auto_classify = data.get("auto_classify", True)
        preferred_existing_path = data.get("existing_path")
        merge_decisions = data.get("merge_decisions") or {}
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        if not resolution:
            raise HTTPException(status_code=400, detail="未提供解决方案")
        normalized_resolution = str(resolution).strip().upper()
        if normalized_resolution == "KEEP_OLD":
            normalized_resolution = "SKIP"
        if normalized_resolution in {"KEEP_BOTH", "MERGE_LANG"}:
            normalized_resolution = "MERGE"
        if normalized_resolution not in {"KEEP_NEW", "MERGE", "SKIP"}:
            raise HTTPException(status_code=400, detail="不支持的解决方案")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        resolved_folder = _resolve_existing_folder_candidate_path(folder_path, existing_folders_path)
        if not resolved_folder.get("ok"):
            raise HTTPException(status_code=400, detail=resolved_folder.get("reason") or "路径不在已存在文件夹目录下")
        folder_path = resolved_folder["path"]
        
        # 根据解决方案执行不同操作
        if normalized_resolution == "SKIP":
            # 抛弃新版 - 删除文件夹
            import shutil
            _robust_rmtree(folder_path)
            logger.info(f"已抛弃新版（删除文件夹）: {folder_path}")
            return {"message": "已跳过当前目录，待处理文件夹已删除", "resolution": normalized_resolution}
        
        elif normalized_resolution in ["KEEP_NEW", "MERGE"]:
            resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, preferred_existing_path)
            if not resolved_existing_path:
                raise HTTPException(status_code=404, detail="未找到要替换或合并的现有目录")
            if not os.path.exists(resolved_existing_path):
                raise HTTPException(status_code=404, detail="现有目录不存在")

            # 这些操作都需要创建处理任务
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                # 提取RJ号
                folder_name = resolved_folder.get("folder_name") or os.path.basename(folder_path)
                rjcode = resolved_folder.get("rjcode") or extract_rjcode_from_path(folder_path, search_subfolders=True)
                
                if rjcode:
                    # 查找对应的冲突记录并更新状态
                    conflict = db.query(ConflictWork).filter(
                        ConflictWork.rjcode == rjcode,
                        ConflictWork.status == 'PENDING'
                    ).first()
                    
                    if conflict:
                        conflict.status = normalized_resolution
                        db.commit()
                        logger.info(f"更新冲突记录状态: {rjcode} -> {normalized_resolution}")
                
                # 创建处理任务
                engine = get_task_engine()
                task = Task(
                    task_type=TaskType.PROCESS_EXISTING_FOLDER,
                    source_path=folder_path,
                    auto_classify=auto_classify,
                    metadata={
                        "existing_folder_resolution": normalized_resolution,
                        "existing_path": resolved_existing_path,
                        "merge_decisions": merge_decisions if normalized_resolution == "MERGE" else {},
                        "folder_path": folder_path,
                        "folder_name": folder_name,
                        "original_folder_path": resolved_folder.get("resolved_from") or folder_path,
                        "relative_path": resolved_folder.get("relative_path") or "",
                        "source_root": resolved_folder.get("source_root") or "",
                        "source_root_name": resolved_folder.get("source_root_name") or "",
                        "is_nested": bool(resolved_folder.get("is_nested")),
                        "scan_depth": int(resolved_folder.get("scan_depth") or 1),
                        "rjcode_source": resolved_folder.get("rjcode_source") or "existing_folder_scan",
                        "inferred_rjcode": rjcode,
                        "rjcode": rjcode,
                        "auto_classify": bool(auto_classify),
                    }
                )
                await engine.submit(task)
                
                return {
                    "message": f"已创建处理任务，解决方案: {normalized_resolution}",
                    "resolution": normalized_resolution,
                    "task_id": task.id,
                    "folder_path": folder_path,
                    "existing_path": resolved_existing_path,
                }
                
            finally:
                db.close()
        
        else:
            raise HTTPException(status_code=400, detail=f"未知的解决方案: {resolution}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

# ========== 关联作品查询 API（改进的查重功能）==========

@app.get("/api/linked-works/{rjcode}")
async def get_linked_works(
    rjcode: str,
    include_full_linkage: bool = True,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    获取作品的关联作品链
    
    Args:
        rjcode: RJ号
        include_full_linkage: 是否包含完整关联链（包括所有语言版本）
        cue_languages: 需要查询的语言列表，逗号分隔
    """
    from ..core.dlsite_service import get_dlsite_service
    
    try:
        service = get_dlsite_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        if include_full_linkage:
            linked_works = await service.get_full_linkage(rjcode, languages)
        else:
            linked_works = await service.get_linked_works(rjcode)
        
        # 获取翻译信息
        trans_info = await service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "translation_info": {
                "is_original": trans_info.is_original,
                "is_parent": trans_info.is_parent,
                "is_child": trans_info.is_child,
                "parent_workno": trans_info.parent_workno,
                "original_workno": trans_info.original_workno,
                "lang": trans_info.lang
            },
            "linked_works": {k: v.to_dict() for k, v in linked_works.items()},
            "total_count": len(linked_works)
        }
        
    except Exception as e:
        logger.warning("获取关联作品失败 %s: %s", rjcode, e)
        raise HTTPException(status_code=500, detail=f"获取关联作品失败: {str(e)}")


@app.get("/api/linked-works/{rjcode}/check-library")
async def check_linked_works_in_library(
    rjcode: str,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    检查作品的关联作品是否在库中
    
    返回库中已存在的所有关联作品
    """
    from ..core.dlsite_service import get_dlsite_service
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        dlsite_service = get_dlsite_service()
        duplicate_service = get_duplicate_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        # 获取完整关联链
        linked_works = await dlsite_service.get_full_linkage(rjcode, languages)
        
        # 检查哪些在库中
        found_in_library = await duplicate_service._check_linked_works_in_library(
            linked_works, rjcode
        )
        
        # 获取翻译信息
        trans_info = await dlsite_service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "is_original": trans_info.is_original,
            "is_in_library": len(found_in_library) > 0,
            "library_works": [
                {
                    "rjcode": w.rjcode,
                    "work_type": w.work_type,
                    "lang": w.lang,
                    "work_name": w.work_name,
                    "path": w.folder_path,
                    "size": w.folder_size,
                    "file_count": w.file_count
                }
                for w in found_in_library
            ],
            "total_linked": len(linked_works),
            "found_in_library": len(found_in_library)
        }
        
    except Exception as e:
        logger.warning("检查库中关联作品失败 %s: %s", rjcode, e)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@app.post("/api/conflicts/enhanced-check")
async def enhanced_duplicate_check(request: Request):
    """
    改进的查重检查
    
    支持检测关联作品冲突
    """
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        data = await request.json()
        rjcode = data.get("rjcode")
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT"])
        
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")
        
        service = get_duplicate_service()
        result = await service.check_duplicate_enhanced(
            rjcode, 
            check_linked_works=check_linked,
            cue_languages=cue_languages
        )
        
        # 获取推荐的解决选项
        resolution_options = _normalize_existing_folder_resolution_options(
            await service.get_conflict_resolution_options(result)
        )
        
        return {
            "is_duplicate": result.is_duplicate,
            "conflict_type": result.conflict_type,
            "direct_duplicate": result.direct_duplicate,
            "linked_works_found": result.linked_works_found,
            "related_rjcodes": result.related_rjcodes,
            "analysis_info": result.analysis_info,
            "resolution_options": resolution_options
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"改进查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


# ========== Kikoeru 搜索配置 API ==========

@app.get("/api/kikoeru-configs")
async def get_kikoeru_configs():
    """获取所有 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        configs = db.query(KikoeruSearchConfig).all()
        return {
            "configs": [config.to_dict() for config in configs]
        }
    finally:
        db.close()


@app.post("/api/kikoeru-configs")
async def create_kikoeru_config(request: Request):
    """创建 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    import uuid
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = KikoeruSearchConfig(
            id=str(uuid.uuid4()),
            name=data.get("name", "Kikoeru"),
            search_url_template=data.get("search_url_template", ""),
            show_url_template=data.get("show_url_template", ""),
            enabled=data.get("enabled", False),
            custom_headers=data.get("custom_headers", {})
        )
        
        db.add(config)
        db.commit()
        
        return {
            "message": "配置已创建",
            "config": config.to_dict()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"创建 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")
    finally:
        db.close()


@app.put("/api/kikoeru-configs/{config_id}")
async def update_kikoeru_config(config_id: str, request: Request):
    """更新 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        if "name" in data:
            config.name = data["name"]
        if "search_url_template" in data:
            config.search_url_template = data["search_url_template"]
        if "show_url_template" in data:
            config.show_url_template = data["show_url_template"]
        if "enabled" in data:
            config.enabled = data["enabled"]
        if "custom_headers" in data:
            config.custom_headers = data["custom_headers"]
        
        db.commit()
        
        return {
            "message": "配置已更新",
            "config": config.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    finally:
        db.close()


@app.delete("/api/kikoeru-configs/{config_id}")
async def delete_kikoeru_config(config_id: str):
    """删除 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        db.delete(config)
        db.commit()
        
        return {"message": "配置已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()


# ========== Kikoeru 服务器查重配置 API ==========
from ..core.kikoeru_duplicate_service import get_kikoeru_service, KikoeruDuplicateService, KikoeruCheckResult

class KikoeruServerConfig(BaseModel):
    """Kikoeru 服务器配置模型"""
    enabled: bool = False
    server_url: str = ""
    username: str = ""
    password: str = ""
    api_token: str = ""
    token_expires: int = 0
    timeout: int = 10
    cache_ttl: int = 300
    enable_fuzzy_rj_match: bool = False

@app.get("/api/kikoeru-server/config")
async def get_kikoeru_server_config():
    """获取 Kikoeru 服务器查重配置"""
    try:
        config = get_config()
        kikoeru_config = config.kikoeru_server if hasattr(config, 'kikoeru_server') else None
        
        if kikoeru_config:
            return {
                "enabled": kikoeru_config.enabled,
                "server_url": kikoeru_config.server_url,
                "username": kikoeru_config.username,
                "password": kikoeru_config.password,
                "api_token": kikoeru_config.api_token,
                "token_expires": kikoeru_config.token_expires,
                "timeout": kikoeru_config.timeout,
                "cache_ttl": kikoeru_config.cache_ttl,
                "enable_fuzzy_rj_match": bool(getattr(kikoeru_config, 'enable_fuzzy_rj_match', False)),
            }
        else:
            return {
                "enabled": False,
                "server_url": "",
                "username": "",
                "password": "",
                "api_token": "",
                "token_expires": 0,
                "timeout": 10,
                "cache_ttl": 300,
                "enable_fuzzy_rj_match": False,
            }
    except Exception as e:
        logger.error(f"获取 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")

@app.post("/api/kikoeru-server/config")
async def update_kikoeru_server_config(config: KikoeruServerConfig):
    """更新 Kikoeru 服务器查重配置（已弃用，请使用 /api/config）"""
    try:
        from ..config.settings import save_config
        
        config_to_save = {
            'kikoeru_server': {
                'enabled': config.enabled,
                'server_url': config.server_url.rstrip('/'),
                'username': config.username,
                'password': config.password,
                'api_token': config.api_token,
                'token_expires': config.token_expires,
                'timeout': config.timeout,
                'cache_ttl': config.cache_ttl,
                'enable_fuzzy_rj_match': config.enable_fuzzy_rj_match,
            }
        }
        
        save_config(config_to_save)
        
        service = get_kikoeru_service()
        service.config = service._load_config()
        
        return {
            "message": "Kikoeru 服务器配置已更新",
            "config": {
                "enabled": config.enabled,
                "server_url": config.server_url,
                "timeout": config.timeout,
                "cache_ttl": config.cache_ttl,
                "enable_fuzzy_rj_match": config.enable_fuzzy_rj_match,
            }
        }
    except Exception as e:
        logger.error(f"更新 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

@app.post("/api/kikoeru-server/test")
async def test_kikoeru_server_connection():
    """测试 Kikoeru 服务器连接"""
    try:
        service = get_kikoeru_service()
        result = await service.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"测试 Kikoeru 服务器连接失败: {e}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
            "latency": 0
        }

@app.post("/api/kikoeru-server/check")
async def check_kikoeru_duplicate(
    rjcode: str,
    check_linkages: bool = True,
    cue_languages: str = "CHI_HANS CHI_HANT ENG JPN"
):
    """检查作品及其关联作品是否在 Kikoeru 服务器中

    Args:
        rjcode: RJ号
        check_linkages: 是否检查关联作品
        cue_languages: 语言列表，空格分隔（如 'CHI_HANS CHI_HANT ENG JPN'）
    """
    logger.info(f"=" * 60)
    logger.info(f"[Kikoeru查重] 开始查询: {rjcode}, check_linkages={check_linkages}")

    try:
        # 解析语言列表
        lang_list = cue_languages.split() if cue_languages else ["CHI_HANS", "CHI_HANT", "ENG", "JPN"]
        logger.info(f"[Kikoeru查重] 检查语言: {lang_list}")
        
        service = get_kikoeru_service()
        
        if check_linkages:
            # 查询关联作品
            logger.info(f"[Kikoeru查重] 执行关联作品查询...")
            results = await service.check_duplicate_with_linkages(rjcode, lang_list, use_cache=True)

            # 格式化返回结果
            found_works = []
            for rj, res in results.items():
                if res.is_found:
                    matched_rjcode = str(res.matched_rjcode or rj or res.rjcode or "").strip().upper()
                    found_works.append({
                        "rjcode": rj,
                        "matched_rjcode": matched_rjcode,
                        "title": res.title,
                        "circle_name": res.circle_name,
                        "tags": res.tags,
                        "source": res.source,
                    })
            
            primary_result = results.get(rjcode, KikoeruCheckResult(rjcode=rjcode))
            matched_result = next((item for item in found_works if item.get("matched_rjcode")), None)
            
            logger.info(f"[Kikoeru查重] 关联查询完成: 总共 {len(results)} 个作品，找到 {len(found_works)} 个")
            
            return {
                "rjcode": rjcode,
                "is_found": primary_result.is_found or len(found_works) > 0,
                "matched_rjcode": (
                    primary_result.matched_rjcode
                    or (matched_result or {}).get("matched_rjcode")
                    or (matched_result or {}).get("rjcode")
                    or ""
                ),
                "title": primary_result.title,
                "circle_name": primary_result.circle_name,
                "tags": primary_result.tags,
                "primary_result": {
                    "rjcode": primary_result.rjcode,
                    "is_found": primary_result.is_found,
                    "matched_rjcode": primary_result.matched_rjcode,
                    "title": primary_result.title,
                    "circle_name": primary_result.circle_name,
                    "source": primary_result.source,
                },
                "linked_works_found": found_works,
                "total_checked": len(results),
                "source": "kikoeru_with_linkages",
                "checked_at": datetime.now().isoformat()
            }
        else:
            # 只查询单个作品
            result = await service.check_duplicate(rjcode, use_cache=True)
            
            return {
                "rjcode": result.rjcode,
                "is_found": result.is_found,
                "title": result.title,
                "circle_name": result.circle_name,
                "tags": result.tags,
                "linked_works_found": [],
                "total_checked": 1,
                "source": result.source,
                "checked_at": result.checked_at.isoformat() if result.checked_at else None
            }
    except Exception as e:
        logger.warning("[Kikoeru查重] 查询失败: %s, 错误: %s", rjcode, e)
        raise HTTPException(status_code=500, detail=f"查重检查失败: {str(e)}")
    finally:
        logger.info(f"[Kikoeru查重] 查询结束: {rjcode}")
        logger.info(f"=" * 60)

@app.post("/api/kikoeru-server/clear-cache")
async def clear_kikoeru_cache():
    """清除 Kikoeru 查重缓存"""
    try:
        service = get_kikoeru_service()
        service.clear_cache()

        return {"message": "Kikoeru 查重缓存已清除"}
    except Exception as e:
        logger.error(f"清除 Kikoeru 缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/kikoeru-server/get-token")
async def get_kikoeru_token():
    """手动获取 Kikoeru 服务器的 Token"""
    try:
        service = get_kikoeru_service()

        # 重新加载配置，确保使用最新的配置
        service.config = service._load_config()

        # 检查配置
        if not service.config.server_url:
            raise HTTPException(status_code=400, detail="请先配置服务器地址")

        if not service.config.username or not service.config.password:
            raise HTTPException(status_code=400, detail="请先配置用户名和密码")

        logger.info(f"[Kikoeru] 使用服务器地址: {_mask_url_credentials(service.config.server_url)}")
        logger.info(f"[Kikoeru] 使用用户名: {service.config.username}")

        # 调用登录方法获取 Token
        success = await service._login()

        if success:
            return {
                "success": True,
                "token": service.config.api_token,
                "expires": service.config.token_expires,
                "message": "Token 获取成功"
            }
        else:
            raise HTTPException(status_code=401, detail="获取 Token 失败，请检查用户名和密码")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取 Kikoeru Token 失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"获取 Token 失败: {str(e)}")


# ========== ASMR 同步下载 API ==========

class RJSubtitleScanRequest(BaseModel):
    """RJ 字幕扫描请求"""
    folder_path: str
    library_id: Optional[str] = None
    scan_depth: int = 3
    scan_one_level_only: Optional[bool] = None


class RJSubtitleStartRequest(BaseModel):
    """RJ 字幕抓取开始请求"""
    items: List[dict]  # [{rjcode, folder_path, folder_name}]
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    skip_if_existing_subtitles: bool = False
    force_rerun: bool = False
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []
    ai_match_mode: str = "rule_ai_auto"
    ai_confidence_threshold: Optional[int] = None
    batch_context: Optional[dict] = None


class RJSubtitleManualCompleteRequest(BaseModel):
    applied_pairs: int = 0
    deleted_subtitles: int = 0
    naming_strategy: str = "audio"
    pair_changes: List[dict] = []
    folder_path: str = ""
    library_id: Optional[str] = None
    rjcode: str = ""


class RJSubtitleRerunRequest(BaseModel):
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []
    ai_match_mode: str = "rule_ai_auto"
    ai_confidence_threshold: Optional[int] = None


class RJSubtitleAvailabilityRequest(BaseModel):
    rjcode: str


class RJSubtitleFolderSubtitleStateRequest(BaseModel):
    folder_path: str
    library_id: Optional[str] = None


class RJSubtitleKikoeruSubtitleStateRequest(BaseModel):
    rjcode: str


def _invalidate_rj_subtitle_folder_summary_cache(library_id: Any) -> None:
    """库存写操作后让字幕工作台的目录摘要立即过期。"""
    try:
        from ..core.linked_subtitle_import_service import (
            invalidate_target_folder_summary_cache_for_library,
        )

        invalidate_target_folder_summary_cache_for_library(str(library_id or ""))
    except Exception:
        logger.debug(
            "[RJ字幕·缓存] 目录摘要失效失败 library=%s",
            library_id,
            exc_info=True,
        )


def _normalize_rj_for_library_index(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.isdigit():
        text = f"RJ{text}"
    if re.fullmatch(r"RJ\d{4,}", text):
        return text
    matched = re.search(r"RJ\d{4,}", text, re.IGNORECASE)
    return matched.group(0).upper() if matched else ""


def _library_index_subtitle_state(rjcode: str, library_id: Optional[str] = None) -> Dict[str, Any]:
    normalized_rjcode = _normalize_rj_for_library_index(rjcode)
    empty_state = {
        "checked": False,
        "checked_rjcode": normalized_rjcode,
        "has_work": False,
        "has_existing_subtitles": False,
        "matched_rjcode": "",
        "subtitle_file_count": 0,
        "subtitle_check_source": "library_index",
        "title": "",
        "matches": [],
        "error": "",
        "local_owned": False,
        "local_subtitle_present": False,
        "subtitle_dir": "",
    }
    if not normalized_rjcode:
        return empty_state

    manager = get_library_manager()
    library_ids = [library_id] if library_id else None
    if not manager.has_ready_index(library_ids=library_ids):
        return {
            **empty_state,
            "checked": True,
            "error": "library_index_not_ready",
        }

    index_hits = manager.find_rj_in_ready_index([normalized_rjcode], library_ids=library_ids)
    hits = list(index_hits.get(normalized_rjcode) or [])
    subtitle_hits = [
        hit for hit in hits
        if bool(hit.get("local_subtitle_present")) or int(hit.get("subtitle_file_count") or 0) > 0
    ]
    primary_hit = subtitle_hits[0] if subtitle_hits else (hits[0] if hits else {})
    matched_rjcode = str(
        primary_hit.get("matched_rjcode")
        or primary_hit.get("rjcode")
        or normalized_rjcode
    ).upper() if primary_hit else ""
    subtitle_count = sum(int(hit.get("subtitle_file_count") or 0) for hit in subtitle_hits)
    subtitle_dir = next((str(hit.get("subtitle_dir") or "").strip() for hit in subtitle_hits if hit.get("subtitle_dir")), "")
    matches = [
        {
            "rjcode": str(hit.get("matched_rjcode") or hit.get("rjcode") or normalized_rjcode).upper(),
            "subtitle_file_count": int(hit.get("subtitle_file_count") or 0),
            "subtitle_check_source": "library_index",
            "title": "",
            "match_type": "library_index",
            "path": str(hit.get("path") or ""),
            "subtitle_dir": str(hit.get("subtitle_dir") or ""),
        }
        for hit in subtitle_hits
    ]
    return {
        **empty_state,
        "checked": True,
        "has_work": bool(hits),
        "has_existing_subtitles": bool(subtitle_hits),
        "matched_rjcode": matched_rjcode,
        "subtitle_file_count": subtitle_count,
        "matches": matches,
        "local_owned": bool(hits),
        "local_subtitle_present": bool(subtitle_hits),
        "subtitle_dir": subtitle_dir,
    }


@app.post("/api/ai-subtitle-match/test")
async def ai_subtitle_match_test(request: AISubtitleMatchTestRequest):
    """测试 AI 字幕配对模型连接和 JSON 输出能力。"""
    from ..core.ai_subtitle_match_service import get_ai_subtitle_match_service

    try:
        cfg_dict = request.config or {}
        if not cfg_dict:
            cfg_dict = get_config().ai_subtitle_matching.model_dump()
        return await get_ai_subtitle_match_service().test_connection(
            cfg_dict,
            saved_api_key=_read_ai_subtitle_api_key_from_disk() or getattr(get_config().ai_subtitle_matching, 'api_key', ''),
        )
    except Exception as exc:
        logger.warning("[AI字幕] 测试连接失败: %s", exc)
        return {
            "success": False,
            "status": "failed",
            "error": {
                "code": "unknown_error",
                "title": "测试失败",
                "message": str(exc),
                "suggestion": "检查后端日志和 AI 配置",
                "raw_summary": str(exc)[:800],
            },
            "model": str((request.config or {}).get("model") or ""),
            "duration_ms": 0,
        }


@app.post("/api/ai-subtitle-match/models")
async def ai_subtitle_match_models(request: AISubtitleMatchModelsRequest):
    """使用当前草稿配置获取模型列表。"""
    from ..core.ai_subtitle_match_service import get_ai_subtitle_match_service

    try:
        cfg_dict = request.config or {}
        if not cfg_dict:
            cfg_dict = get_config().ai_subtitle_matching.model_dump()
        return await get_ai_subtitle_match_service().list_models(
            cfg_dict,
            saved_api_key=_read_ai_subtitle_api_key_from_disk() or getattr(get_config().ai_subtitle_matching, 'api_key', ''),
        )
    except Exception as exc:
        logger.warning("[AI字幕] 获取模型列表失败: %s", exc)
        return {
            "success": False,
            "status": "failed",
            "error": {
                "code": "unknown_error",
                "title": "获取模型失败",
                "message": str(exc),
                "suggestion": "检查后端日志和 AI 配置",
                "raw_summary": str(exc)[:800],
            },
            "models": [],
            "duration_ms": 0,
        }


@app.post("/api/ai-subtitle-match/provider-icon")
async def ai_subtitle_match_provider_icon(request: AISubtitleProviderIconRequest):
    """识别 AI 模型平台，并把对应 favicon 缓存在本地。"""
    from ..core.ai_provider_icon_service import get_ai_provider_icon_service

    try:
        return await get_ai_provider_icon_service().resolve_provider_icon(
            model=request.model,
            api_base=request.api_base,
            proxy_url=request.proxy_url,
        )
    except Exception as exc:
        logger.warning("[AI字幕] 获取平台图标失败: %s", sanitize_text_for_log(exc))
        return {
            "success": False,
            "key": "custom",
            "label": "自定义模型服务",
            "host": "",
            "icon_path": "",
            "icon_url": "",
            "source": "error",
            "error": str(exc)[:300],
        }


@app.get("/api/ai-subtitle-match/provider-icon/file/{filename}")
async def ai_subtitle_match_provider_icon_file(filename: str):
    """返回本地缓存的 AI 模型平台图标。"""
    from ..core.ai_provider_icon_service import get_ai_provider_icon_service

    file_path = get_ai_provider_icon_service().resolve_cached_file(filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="图标不存在")
    media_type = mimetypes.guess_type(str(file_path))[0] or "image/x-icon"
    return FileResponse(str(file_path), media_type=media_type)


@app.get("/api/ai-subtitle-match/usage")
async def ai_subtitle_match_usage(limit: int = 100):
    """查看 AI 字幕配对 usage 摘要。"""
    from ..core.ai_subtitle_match_service import get_ai_subtitle_match_service

    return get_ai_subtitle_match_service().list_usage(limit=limit)


@app.post("/api/ai-subtitle-match/preview")
async def ai_subtitle_match_preview(request: AISubtitleMatchPreviewRequest):
    """生成 AI 配对草稿。只返回建议，不写入文件。"""
    from ..core.ai_subtitle_match_service import get_ai_subtitle_match_service
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        service = get_rj_subtitle_service()
        audio_index = service._build_audio_index(
            request.audio_files or [],
            enable_metadata_match=bool(request.enable_metadata_match),
        )
        subtitle_files = request.subtitle_files or []
        if request.use_filter_rules:
            subtitle_files = service._apply_subtitle_filter_rules(
                subtitle_files,
                request.subtitle_filter_rules or [],
            )
        subtitle_groups = service._group_subtitles(subtitle_files)
        empty_base = {
            "matches": [],
            "matched_group_count": 0,
            "matched_subtitle_count": 0,
            "unmatched_audio": [],
            "unmatched_subtitles": [],
        }
        ai_config = get_config().ai_subtitle_matching
        ai_config_for_preview = ai_config.model_dump() if hasattr(ai_config, "model_dump") else dict(ai_config or {})
        # 配对台的“自动预配对”按钮按最新口径：只要 AI 总开关和模型配置可用，就优先用 AI 生成草稿。
        # 这里不让“辅助草稿”子开关阻断 preview；正式 RJ 任务模式仍走保存的配置。
        ai_config_for_preview["manual_assist_enabled"] = True
        result = await get_ai_subtitle_match_service().build_auto_match_result(
            config=ai_config_for_preview,
            audio_index=audio_index,
            subtitle_groups=subtitle_groups,
            base_match_result=empty_base,
            mode=request.ai_match_mode or "ai_assist",
            naming_strategy=request.naming_strategy or "audio",
            threshold=request.ai_confidence_threshold,
        )
        success_statuses = {"preview", "succeeded", "awaiting_manual"}
        return {
            "success": result.get("status") in success_statuses,
            "status": result.get("status"),
            "match_result": result.get("match_result") or empty_base,
            "metadata": result.get("metadata") or {},
            "error": result.get("error"),
        }
    except Exception as exc:
        logger.error("[AI字幕] 生成配对草稿失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI 配对失败: {exc}")


class LinkedSubtitleArchivePreviewRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None


class LinkedSubtitleFolderPreviewRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    source_rjcode_hint: Optional[str] = None


class LinkedSubtitleArchiveImportRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitleFolderImportRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    source_rjcode_hint: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitlePendingImportExecuteRequest(BaseModel):
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []

class LinkedSubtitlePendingClearRequest(BaseModel):
    record_ids: List[str] = []
    clear_all: bool = False


@app.post("/api/rj-subtitle/scan")
async def rj_subtitle_scan(request: RJSubtitleScanRequest):
    """扫描单个 RJ 文件夹或批量父目录"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        folder_path = request.folder_path
        service = get_rj_subtitle_service()
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)
        if request.library_id:
            manager = get_library_manager()
            library = manager.get_library_definition(request.library_id)
            if library.type == "synology_filestation":
                items = await service.scan_remote(
                    request.library_id,
                    folder_path,
                    scan_depth=scan_depth,
                )
                return {
                    "success": True,
                    "folder_path": folder_path,
                    "total_found": len(items),
                    "ready_count": len([item for item in items if item["status"] == "ready"]),
                    "items": items,
                }
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")
        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        items = service.scan(
            folder_path,
            scan_depth=scan_depth,
        )

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(items),
            "ready_count": len([item for item in items if item["status"] == "ready"]),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描 RJ 字幕目录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/rj-subtitle/scan-stream")
async def rj_subtitle_scan_stream(request: RJSubtitleScanRequest):
    """流式扫描 RJ 目录，发现一个就返回一个。"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    async def generate():
        service = get_rj_subtitle_service()
        folder_path = request.folder_path
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)

        total_found = 0
        ready_count = 0
        existing_count = 0
        no_audio_count = 0
        event_queue: asyncio.Queue = asyncio.Queue()

        def dump(payload):
            return json.dumps(payload, ensure_ascii=False) + "\n"

        def enqueue(payload):
            try:
                event_queue.put_nowait(payload)
            except Exception:
                logger.debug("RJ 字幕扫描流事件入队失败: %s", payload, exc_info=True)

        display_name = PurePosixPath(folder_path).name or os.path.basename(folder_path) or folder_path
        enqueue({
            "type": "target_result",
            "path": folder_path,
            "name": display_name,
            "status": "pending",
            "message": "正在扫描..."
        })

        def emit_progress(current_scan_path: str):
            current_display = PurePosixPath(current_scan_path).name or os.path.basename(current_scan_path) or current_scan_path
            enqueue({
                "type": "progress",
                "path": folder_path,
                "current_path": current_scan_path,
                "message": f"正在扫描 {current_display}..."
            })

        async def produce():
            nonlocal total_found, ready_count, existing_count, no_audio_count
            try:
                if request.library_id:
                    manager = get_library_manager()
                    library = manager.get_library_definition(request.library_id)
                    if library.type == "synology_filestation":
                        async for item in service.scan_remote_iter(
                            request.library_id,
                            folder_path,
                            scan_depth=scan_depth,
                            progress_callback=emit_progress,
                        ):
                            total_found += 1
                            if item.get("status") == "ready":
                                ready_count += 1
                            elif item.get("status") == "existing":
                                existing_count += 1
                            elif item.get("status") == "no_audio":
                                no_audio_count += 1
                            enqueue({"type": "item", "item": item})
                        enqueue({
                            "type": "target_result",
                            "path": folder_path,
                            "name": display_name,
                            "status": "success" if total_found else "no_match",
                            "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                            "summary": {
                                "found": total_found,
                                "ready": ready_count,
                                "existing": existing_count,
                                "no_audio": no_audio_count,
                            }
                        })
                        enqueue({
                            "type": "complete",
                            "folder_path": folder_path,
                            "total_found": total_found,
                            "ready_count": ready_count,
                            "existing_count": existing_count,
                            "no_audio_count": no_audio_count,
                        })
                        return

                if not os.path.exists(folder_path):
                    raise HTTPException(status_code=400, detail="指定的文件夹不存在")
                if not os.path.isdir(folder_path):
                    raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

                for item in service.scan_iter(folder_path, scan_depth=scan_depth, progress_callback=emit_progress):
                    total_found += 1
                    if item.get("status") == "ready":
                        ready_count += 1
                    elif item.get("status") == "existing":
                        existing_count += 1
                    elif item.get("status") == "no_audio":
                        no_audio_count += 1
                    enqueue({"type": "item", "item": item})

                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "success" if total_found else "no_match",
                    "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                    "summary": {
                        "found": total_found,
                        "ready": ready_count,
                        "existing": existing_count,
                        "no_audio": no_audio_count,
                    }
                })
                enqueue({
                    "type": "complete",
                    "folder_path": folder_path,
                    "total_found": total_found,
                    "ready_count": ready_count,
                    "existing_count": existing_count,
                    "no_audio_count": no_audio_count,
                })
            except HTTPException as exc:
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": exc.detail,
                })
                enqueue({"type": "error", "error": exc.detail})
            except Exception as exc:
                logger.error(f"流式扫描 RJ 字幕目录失败: {exc}", exc_info=True)
                message = f"扫描失败: {str(exc)}"
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": message,
                })
                enqueue({"type": "error", "error": message})
            finally:
                enqueue({"type": "stream_end"})

        producer = asyncio.create_task(produce())
        try:
            while True:
                payload = await event_queue.get()
                if payload.get("type") == "stream_end":
                    break
                yield dump(payload)
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/rj-subtitle/start")
async def rj_subtitle_start(request: RJSubtitleStartRequest):
    """开始 RJ 字幕抓取任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine
    from ..core.activity_log_service import log_subtitle_batch_start_result

    try:
        engine = get_task_engine()
        created_tasks = []
        skipped_existing = 0
        skipped_duplicate = 0
        skipped_items = []
        batch_context = request.batch_context if isinstance(request.batch_context, dict) else {}
        batch_id = str(batch_context.get("batch_id") or "").strip()
        log_parent = bool(batch_context.get("log_parent"))
        source_directories = batch_context.get("source_directories") if isinstance(batch_context.get("source_directories"), list) else []
        scan_targets = batch_context.get("scan_targets") if isinstance(batch_context.get("scan_targets"), list) else []
        should_log_batch = bool(batch_id) and log_parent

        if not request.items:
            if should_log_batch:
                summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
                recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or 0)
                skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
                failure_reason = str(batch_context.get("failure_reason") or "").strip()
                if not failure_reason and recognized_rj_count <= 0:
                    failure_reason = "扫描未返回可执行 RJ 项"
                elif not failure_reason and skipped_no_subtitle > 0:
                    failure_reason = "远程未找到可用字幕"
                elif not failure_reason:
                    failure_reason = "本次批量扫描未命中可创建的 RJ 字幕任务"
                log_subtitle_batch_start_result({
                    "batch_id": batch_id,
                    "requested_count": int(batch_context.get("requested_count") or 0),
                    "recognized_rj_count": recognized_rj_count,
                    "created_count": 0,
                    "skipped_total": skipped_no_subtitle,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "skipped_no_subtitle": skipped_no_subtitle,
                    "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                    "force_rerun": request.force_rerun,
                    "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                    "naming_strategy": request.naming_strategy,
                    "ai_match_mode": request.ai_match_mode,
                    "ai_confidence_threshold": request.ai_confidence_threshold,
                    "source_directories": source_directories,
                    "scan_targets": scan_targets,
                    "created_tasks": [],
                    "skipped_items": [],
                    "failure_reason": failure_reason,
                    "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
                })
                return {
                    "success": True,
                    "message": failure_reason,
                    "created_count": 0,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "batch_id": batch_id or None,
                    "failure_reason": failure_reason,
                    "skipped_items": [],
                    "tasks": [],
                }
            raise HTTPException(status_code=400, detail="没有可执行的 RJ 文件夹")

        for item in request.items:
            folder_path = str(item.get("folder_path") or "").strip()
            rjcode = str(item.get("rjcode") or "").strip().upper()
            folder_name = str(item.get("folder_name") or "")
            library_id = str(item.get("library_id") or "").strip() or None
            if not folder_path:
                continue

            resolved_existing_subtitle_count = int(item.get("existing_subtitle_count") or 0)
            kikoeru_state = None

            if request.skip_if_existing_subtitles and rjcode:
                try:
                    kikoeru_state = _library_index_subtitle_state(rjcode, library_id)
                except Exception as exc:
                    logger.warning(
                        "[RJ字幕] 查询 ready 库存索引字幕状态失败，继续后续流程: rj=%s error=%s",
                        rjcode,
                        exc,
                    )
                    kikoeru_state = None

                if kikoeru_state and bool(kikoeru_state.get("has_existing_subtitles")):
                    skipped_existing += 1
                    matched_rjcode = str(kikoeru_state.get("matched_rjcode") or rjcode).upper()
                    subtitle_file_count = int(kikoeru_state.get("subtitle_file_count") or 0)
                    queue_message = f"本地库存已有字幕（{matched_rjcode}"
                    if subtitle_file_count > 0:
                        queue_message += f" / {subtitle_file_count} 个"
                    queue_message += "），未加入抓取任务"
                    skipped_items.append({
                        "rjcode": rjcode,
                        "folder_name": folder_name,
                        "folder_path": folder_path,
                        "library_id": library_id,
                        "existing_subtitle_count": resolved_existing_subtitle_count,
                        "queue_state": "skipped_kikoeru_existing",
                        "queue_message": queue_message,
                        "kikoeru_checked_rjcode": kikoeru_state.get("checked_rjcode", rjcode),
                        "kikoeru_has_work": bool(kikoeru_state.get("has_work")),
                        "kikoeru_has_existing_subtitles": True,
                        "kikoeru_matched_rjcode": matched_rjcode,
                        "kikoeru_subtitle_file_count": subtitle_file_count,
                        "kikoeru_subtitle_check_source": kikoeru_state.get("subtitle_check_source", ""),
                    })
                    continue

            duplicate_task = next((
                current_task for current_task in engine.get_all_tasks()
                if current_task.type == TaskType.RJ_SUBTITLE_FETCH
                and str(current_task.task_metadata.get("folder_path") or current_task.source_path) == str(folder_path)
                and current_task.status.value in {"pending", "processing", "paused"}
            ), None)
            if duplicate_task:
                skipped_duplicate += 1
                skipped_items.append({
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "folder_path": folder_path,
                    "library_id": library_id,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "task_id": duplicate_task.id,
                    "queue_state": "existing_task",
                    "queue_message": "任务已存在",
                })
                continue

            task = Task(
                task_type=TaskType.RJ_SUBTITLE_FETCH,
                source_path=folder_path,
                auto_classify=False,
                metadata={
                    "folder_path": folder_path,
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "library_id": library_id,
                    "overwrite": request.overwrite_existing,
                    "enable_metadata_match": request.enable_metadata_match,
                    "skip_if_existing_subtitles": False if request.force_rerun else request.skip_if_existing_subtitles,
                    "force_rerun": request.force_rerun,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "naming_strategy": request.naming_strategy,
                    "use_filter_rules": request.use_filter_rules,
                    "subtitle_filter_rules": request.subtitle_filter_rules,
                    "ai_match_mode": request.ai_match_mode,
                    "ai_confidence_threshold": request.ai_confidence_threshold,
                    "batch_id": batch_id or None,
                    "kikoeru_checked_rjcode": (kikoeru_state or {}).get("checked_rjcode", rjcode),
                    "kikoeru_has_work": bool((kikoeru_state or {}).get("has_work")),
                    "kikoeru_has_existing_subtitles": bool((kikoeru_state or {}).get("has_existing_subtitles")),
                    "kikoeru_matched_rjcode": (kikoeru_state or {}).get("matched_rjcode", ""),
                    "kikoeru_subtitle_file_count": int((kikoeru_state or {}).get("subtitle_file_count") or 0),
                    "kikoeru_subtitle_check_source": (kikoeru_state or {}).get("subtitle_check_source", ""),
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "folder_name": folder_name,
                "folder_path": folder_path,
                "library_id": library_id,
            })

        if should_log_batch:
            summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
            requested_count = int(batch_context.get("requested_count") or len(request.items))
            recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or len(request.items))
            skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
            log_subtitle_batch_start_result({
                "batch_id": batch_id,
                "requested_count": requested_count,
                "recognized_rj_count": recognized_rj_count,
                "created_count": len(created_tasks),
                "skipped_total": skipped_existing + skipped_duplicate + skipped_no_subtitle,
                "skipped_existing": skipped_existing,
                "skipped_duplicate": skipped_duplicate,
                "skipped_no_subtitle": skipped_no_subtitle,
                "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                "force_rerun": request.force_rerun,
                "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                "naming_strategy": request.naming_strategy,
                "ai_match_mode": request.ai_match_mode,
                "ai_confidence_threshold": request.ai_confidence_threshold,
                "source_directories": source_directories,
                "scan_targets": scan_targets,
                "created_tasks": created_tasks,
                "skipped_items": skipped_items,
                "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个 RJ 字幕抓取任务",
            "created_count": len(created_tasks),
            "skipped_existing": skipped_existing,
            "skipped_duplicate": skipped_duplicate,
            "batch_id": batch_id or None,
            "skipped_items": skipped_items,
            "tasks": created_tasks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动 RJ 字幕抓取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/rj-subtitle/folder-subtitle-state")
async def rj_subtitle_folder_subtitle_state(request: RJSubtitleFolderSubtitleStateRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        folder_path = str(request.folder_path or "").strip()
        library_id = str(request.library_id or "").strip()
        if not folder_path:
            raise HTTPException(status_code=400, detail="目录路径不能为空")
        if not library_id:
            raise HTTPException(status_code=400, detail="库存 ID 不能为空")

        summary = await get_linked_subtitle_import_service().summarize_target_folder_cached(
            library_id,
            folder_path,
        )
        if not summary:
            raise HTTPException(status_code=404, detail="未找到目录摘要")

        return {
            "success": True,
            "folder_path": folder_path,
            "library_id": library_id,
            "has_existing_subtitles": bool(summary.get("has_existing_subtitles")),
            "existing_subtitle_count": int(summary.get("existing_subtitle_count") or 0),
            "subtitle_dir": str(summary.get("subtitle_dir") or ""),
            "audio_count": int(summary.get("audio_count") or 0),
            "ready_for_import": bool(summary.get("ready_for_import")),
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RJ 目录字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/kikoeru-subtitle-state")
async def rj_subtitle_kikoeru_subtitle_state(request: RJSubtitleKikoeruSubtitleStateRequest):
    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        state = _library_index_subtitle_state(rjcode)
        return {
            "success": True,
            **state,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取本地库存字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/manual-complete")
async def rj_subtitle_manual_complete(
    task_id: str,
    request: RJSubtitleManualCompleteRequest,
    db: Session = Depends(get_db),
):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        applied_pairs = max(0, int(request.applied_pairs or 0))
        deleted_subtitles = max(0, int(request.deleted_subtitles or 0))
        fallback_folder_path = str(request.folder_path or "").strip()
        fallback_rjcode = str(request.rjcode or "").strip().upper()
        pair_changes = request.pair_changes if isinstance(request.pair_changes, list) else []
        pair_changes = pair_changes[:200]
        fallback_crawl_row = None

        if task and task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")

        if not task:
            crawl_query = (
                db.query(ActivityLog)
                .filter(ActivityLog.category == "subtitle_crawl")
                .order_by(desc(ActivityLog.created_at))
            )
            if task_id:
                fallback_crawl_row = crawl_query.filter(ActivityLog.task_id == task_id).first()
            if not fallback_crawl_row and fallback_folder_path:
                path_query = crawl_query.filter(ActivityLog.source_path == fallback_folder_path)
                if fallback_rjcode:
                    path_query = path_query.filter(ActivityLog.rjcode == fallback_rjcode)
                fallback_crawl_row = path_query.first()
            if not fallback_crawl_row and fallback_rjcode:
                fallback_crawl_row = crawl_query.filter(ActivityLog.rjcode == fallback_rjcode).first()
            if not fallback_crawl_row:
                raise HTTPException(status_code=404, detail="任务不存在，且未找到对应的字幕抓取记录")

            crawl_detail = fallback_crawl_row.detail if isinstance(fallback_crawl_row.detail, dict) else {}
            naming_strategy = str(request.naming_strategy or crawl_detail.get("naming_strategy") or "audio").lower()
            rj_log = fallback_rjcode or str(fallback_crawl_row.rjcode or "").strip().upper()
            source_path = fallback_folder_path or str(fallback_crawl_row.source_path or "").strip()
            summary_parts = [f"已应用 {applied_pairs} 组配对"]
            if deleted_subtitles:
                summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
            summary = "，".join(summary_parts)

            from ..core.activity_log_service import log_subtitle_pair_complete

            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "batch_id": str(crawl_detail.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": source_path or None,
                    "library_id": str(request.library_id or crawl_detail.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                    "manual_match_completed": True,
                },
                source_path=source_path or None,
            )
            _fallback_library_id = str(request.library_id or crawl_detail.get("library_id") or "").strip()
            _fallback_subtitle_count = max(1, applied_pairs)

            async def _sync_circle_subtitle_state_after_fallback_complete() -> None:
                try:
                    from ..core.circle_completion_service import get_circle_completion_service

                    await get_circle_completion_service().sync_subtitle_for_rj(
                        rj_log,
                        folder_path=source_path or "",
                        library_id=_fallback_library_id,
                        subtitle_file_count=_fallback_subtitle_count,
                    )
                except Exception:
                    logger.warning("[社团补全] 字幕配对 fallback 完成后同步字幕态失败 task=%s", task_id, exc_info=True)

            try:
                asyncio.create_task(_sync_circle_subtitle_state_after_fallback_complete())
            except Exception:
                logger.warning("[社团补全] 字幕配对 fallback 完成后调度字幕态同步失败 task=%s", task_id, exc_info=True)
            return {
                "success": True,
                "message": summary,
                "task_id": task_id,
                "fallback_logged": True,
            }

        naming_strategy = str(request.naming_strategy or task.task_metadata.get("naming_strategy") or "audio").lower()
        linked_finalize_result = await get_linked_subtitle_import_service().finalize_manual_match_task(
            task,
            expected_min_files=1,
        )

        task.task_metadata = task.task_metadata or {}
        task.task_metadata["awaiting_manual_match"] = False
        task.task_metadata["manual_match_completed"] = True
        task.task_metadata["manual_match_completed_at"] = datetime.now().isoformat()
        task.task_metadata["manual_match_applied_pairs"] = applied_pairs
        task.task_metadata["manual_match_deleted_subtitles"] = deleted_subtitles
        task.task_metadata["naming_strategy"] = naming_strategy

        summary_parts = [f"已应用 {applied_pairs} 组配对"]
        if deleted_subtitles:
            summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
        if linked_finalize_result.get("applied"):
            summary_parts.append(
                f"已确认导入目标目录，共 {int(linked_finalize_result.get('final_file_count') or 0)} 个字幕"
            )
        summary = "，".join(summary_parts)

        task.progress = 100
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.current_step = summary

        if linked_finalize_result.get("applied"):
            _target_rj = str(
                task.task_metadata.get("target_rjcode")
                or task.task_metadata.get("actual_rjcode")
                or task.task_metadata.get("rjcode")
                or request.rjcode
                or ""
            ).strip().upper()
            _target_folder = str(
                task.task_metadata.get("target_folder_path")
                or task.task_metadata.get("folder_path")
                or request.folder_path
                or task.source_path
                or ""
            ).strip()
            _target_library_id = str(
                task.task_metadata.get("target_library_id")
                or task.task_metadata.get("library_id")
                or request.library_id
                or ""
            ).strip()
            _target_subtitle_dir = str(
                linked_finalize_result.get("final_subtitle_dir")
                or task.task_metadata.get("subtitle_dir")
                or ""
            )
            _target_subtitle_count = int(linked_finalize_result.get("final_file_count") or 0)

            async def _sync_circle_subtitle_state_after_manual_complete() -> None:
                try:
                    from ..core.circle_completion_service import get_circle_completion_service

                    await get_circle_completion_service().sync_subtitle_for_rj(
                        _target_rj,
                        folder_path=_target_folder,
                        library_id=_target_library_id,
                        subtitle_dir=_target_subtitle_dir,
                        subtitle_file_count=_target_subtitle_count,
                    )
                except Exception:
                    logger.warning("[社团补全] 手动字幕配对完成后同步字幕态失败 task=%s", task_id, exc_info=True)

            try:
                asyncio.create_task(_sync_circle_subtitle_state_after_manual_complete())
            except Exception:
                logger.warning("[社团补全] 手动字幕配对完成后调度字幕态同步失败 task=%s", task_id, exc_info=True)

        logs = task.task_metadata.get("progress_log", [])
        logs.append({
            "time": datetime.now().isoformat(),
            "progress": 100,
            "level": "success",
            "message": summary,
        })
        task.task_metadata["progress_log"] = logs

        try:
            from ..core.activity_log_service import log_subtitle_pair_complete, log_subtitle_import_action

            rj_log = str(task.task_metadata.get("rjcode") or "").strip().upper()
            _lf = linked_finalize_result if isinstance(linked_finalize_result, dict) else {}
            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "applied": _lf.get("applied"),
                    "final_file_count": _lf.get("final_file_count"),
                    "reason": _lf.get("reason"),
                    "batch_id": str(task.task_metadata.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
                    "library_id": str(task.task_metadata.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                },
                source_path=str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
            )
            if _lf.get("applied"):
                imported_count = int(_lf.get("final_file_count") or 0)
                import_target_rj = str(
                    task.task_metadata.get("target_rjcode")
                    or task.task_metadata.get("actual_rjcode")
                    or rj_log
                    or ""
                ).strip().upper()
                import_source_path = str(
                    task.task_metadata.get("source_archive_path")
                    or task.task_metadata.get("source_subtitle_folder_path")
                    or task.source_path
                    or ""
                ).strip() or None
                import_action = (
                    "archive_import"
                    if str(task.task_metadata.get("source_mode") or "").strip() == "linked_translation_archive_import"
                    else "folder_import"
                )
                log_subtitle_import_action(
                    action=import_action,
                    success=True,
                    summary=f"字幕补配完成，共导入 {imported_count} 个字幕文件",
                    detail={
                        "task_id": task_id,
                        "final_file_count": imported_count,
                        "target_rjcode": import_target_rj or None,
                        "source_rjcode": str(task.task_metadata.get("rjcode") or "").strip().upper() or None,
                        "manual_match_completed": True,
                        "manual_match_applied_pairs": applied_pairs,
                        "manual_match_deleted_subtitles": deleted_subtitles,
                    },
                    rjcode=import_target_rj or rj_log or None,
                    task_id=task_id,
                    source_path=import_source_path,
                )
        except Exception:
            logger.warning("[操作记录] 字幕配对记录失败", exc_info=True)

        source_mode = str(task.task_metadata.get("source_mode") or "").strip().lower()
        if source_mode in {"linked_translation_archive_import", "subtitle_folder_import"}:
            try:
                from ..models.database import ConflictWork

                source_path = str(
                    task.task_metadata.get("source_archive_path")
                    or task.task_metadata.get("source_subtitle_folder_path")
                    or ""
                ).strip()
                conflict_query = db.query(ConflictWork).filter(
                    ConflictWork.conflict_type == "LINKED_SUBTITLE_IMPORT",
                    ConflictWork.status == "IMPORTED",
                )
                if source_path:
                    conflict_query = conflict_query.filter(ConflictWork.new_path == source_path)
                else:
                    conflict_query = conflict_query.filter(ConflictWork.task_id == task_id)
                for conflict in conflict_query.all():
                    analysis_info = dict(conflict.analysis_info or {})
                    import_summary = dict(analysis_info.get("import_result_summary") or {})
                    import_summary["manual_match_completed"] = True
                    import_summary["manual_match_completed_at"] = datetime.now().isoformat()
                    import_summary["manual_match_applied_pairs"] = applied_pairs
                    analysis_info["import_result_summary"] = import_summary
                    conflict.analysis_info = analysis_info
                db.commit()
            except Exception:
                db.rollback()
                logger.warning("[字幕补配] 标记预检单配对完成失败: task_id=%s", task_id, exc_info=True)
            try:
                await asyncio.to_thread(engine.persist_task_snapshot, task)
            except Exception:
                logger.warning("[任务中心] 字幕补配完成后保留任务快照失败: task_id=%s", task_id, exc_info=True)
        else:
            try:
                await asyncio.to_thread(engine.remove_task, task_id)
            except Exception:
                logger.warning("[任务中心] 字幕配对完成后清理任务记录失败: task_id=%s", task_id, exc_info=True)

        return {"success": True, "task_id": task_id, "message": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记 RJ 字幕后处理完成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"标记失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/rerun")
async def rj_subtitle_rerun_task(task_id: str, request: RJSubtitleRerunRequest):
    from ..core.task_engine import get_task_engine

    try:
        task = await get_task_engine().rerun_rj_subtitle_task(task_id, {
            "overwrite": request.overwrite_existing,
            "enable_metadata_match": request.enable_metadata_match,
            "naming_strategy": request.naming_strategy,
            "use_filter_rules": request.use_filter_rules,
            "subtitle_filter_rules": request.subtitle_filter_rules,
            "ai_match_mode": request.ai_match_mode,
            "ai_confidence_threshold": request.ai_confidence_threshold,
        })
        return {
            "success": True,
            "task_id": task.id,
            "message": "任务已重置并重新加入抓取队列"
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        logger.error(f"重跑 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重跑失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/clear")
async def rj_subtitle_clear_task(task_id: str):
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task or task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status.value in {"pending", "processing", "paused"}:
            raise HTTPException(status_code=400, detail="任务仍在执行中，不能清理")

        metadata = dict(task.task_metadata or {})
        source_mode = str(metadata.get("source_mode") or "").strip().lower()
        if (
            source_mode in {"linked_translation_archive_import", "subtitle_folder_import"}
            and metadata.get("awaiting_manual_match")
            and not metadata.get("manual_match_completed")
        ):
            raise HTTPException(status_code=400, detail="字幕补配仍在等待筛选与配对，不能清理")

        if (
            source_mode in {"linked_translation_archive_import", "subtitle_folder_import"}
            and metadata.get("manual_match_completed")
        ):
            workbench_root = str(metadata.get("linked_workbench_root_dir") or "").strip()
            if workbench_root:
                try:
                    from pathlib import Path
                    import os
                    import shutil

                    target = Path(workbench_root).resolve()
                    parts = [part.lower() for part in target.parts]
                    marker = ["_kikoerumanager_subtitle_workbench", "linked"]
                    is_workbench_path = any(
                        parts[index:index + len(marker)] == marker
                        for index in range(0, max(0, len(parts) - len(marker) + 1))
                    )
                    if is_workbench_path and os.path.isdir(target):
                        await asyncio.to_thread(shutil.rmtree, target, True)
                except Exception:
                    logger.warning("[字幕补配] 清理未完成工作台目录失败: task_id=%s path=%s", task_id, workbench_root, exc_info=True)

        await asyncio.to_thread(engine.remove_task, task_id)
        return {"success": True, "task_id": task_id, "message": "任务已清理"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@app.post("/api/rj-subtitle/subtitle-availability")
async def rj_subtitle_availability(request: RJSubtitleAvailabilityRequest):
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        payload = await get_rj_subtitle_service().probe_cached_subtitle_availability(rjcode)
        return {"success": True, **payload}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检测 RJ 字幕可用性失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@app.get("/api/rj-subtitle/status")
async def rj_subtitle_status():
    """获取 RJ 字幕抓取任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()
        rj_tasks = [task for task in all_tasks if task.type == TaskType.RJ_SUBTITLE_FETCH]
        status_weight = {
            "processing": 0,
            "pending": 1,
            "paused": 2,
            "completed": 3,
            "failed": 4,
        }
        rj_tasks.sort(
            key=lambda task: (
                status_weight.get(task.status.value, 99),
                -(task.created_at.timestamp() if task.created_at else 0),
            )
        )

        return {
            "total_tasks": len(rj_tasks),
            "processing": len([task for task in rj_tasks if task.status.value == "processing"]),
            "pending": len([task for task in rj_tasks if task.status.value == "pending"]),
            "completed": len([task for task in rj_tasks if task.status.value == "completed"]),
            "failed": len([task for task in rj_tasks if task.status.value == "failed"]),
            "tasks": [_serialize_rj_subtitle_task_status(task) for task in rj_tasks]
        }
    except Exception as e:
        logger.error(f"获取 RJ 字幕抓取状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/subtitle-import/pending")
async def list_pending_linked_subtitle_imports(force_refresh_candidates: bool = False):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        items = await service.list_pending_imports(
            force_refresh_candidates=force_refresh_candidates,
        )
        return {
            "success": True,
            "items": items,
        }
    except Exception as e:
        logger.error(f"获取字幕补配预检列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取预检列表失败: {str(e)}")


@app.post("/api/subtitle-import/pending/{record_id}/execute")
async def execute_pending_linked_subtitle_import(record_id: str, request: LinkedSubtitlePendingImportExecuteRequest):
    from ..core.linked_subtitle_import_service import (
        LinkedSubtitleImportAlreadyRunning,
        get_linked_subtitle_import_service,
    )

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_pending_import(
            record_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            activity_result = result if isinstance(result, dict) else {"success": True}
            activity_preview = activity_result.get("preview") if isinstance(activity_result.get("preview"), dict) else {}
            activity_archive_path = str(
                activity_result.get("source_path")
                or activity_preview.get("source_path")
                or ""
            ).strip()
            log_from_subtitle_import_result(
                "pending_execute",
                activity_result,
                archive_path=activity_archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 字幕补配预检执行记录失败", exc_info=True)
        return result
    except LinkedSubtitleImportAlreadyRunning as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"执行字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行补配失败: {str(e)}")


@app.post("/api/subtitle-import/pending/clear")
async def clear_pending_linked_subtitle_imports(request: LinkedSubtitlePendingClearRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.clear_pending_imports(
            record_ids=request.record_ids,
            clear_all=request.clear_all,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"清除字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除预检单失败: {str(e)}")


@app.post("/api/subtitle-import/archive/preview")
async def preview_linked_subtitle_archive_import(request: LinkedSubtitleArchivePreviewRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        preview = await service.preview_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/archive/import")
async def execute_linked_subtitle_archive_import(request: LinkedSubtitleArchiveImportRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "archive_import",
                result if isinstance(result, dict) else {},
                archive_path=request.archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 压缩包补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/folder/preview")
async def preview_linked_subtitle_folder_import(
    payload: LinkedSubtitleFolderPreviewRequest,
    http_request: Request,
):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        http_request.state.slow_api_context = {
            "preferred_library_id": payload.preferred_library_id,
            "source_rjcode_hint": payload.source_rjcode_hint,
        }
        service = get_linked_subtitle_import_service()
        preview = await service.preview_subtitle_folder_import(
            payload.folder_path,
            preferred_library_id=payload.preferred_library_id,
            source_rjcode_hint=payload.source_rjcode_hint,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/folder/import")
async def execute_linked_subtitle_folder_import(
    payload: LinkedSubtitleFolderImportRequest,
    http_request: Request,
):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        http_request.state.slow_api_context = {
            "preferred_library_id": payload.preferred_library_id,
            "target_library_id": payload.target_library_id,
            "source_rjcode_hint": payload.source_rjcode_hint,
            "use_filter_rules": bool(payload.use_filter_rules),
            "subtitle_filter_rules": len(payload.subtitle_filter_rules or []),
        }
        service = get_linked_subtitle_import_service()
        result = await service.execute_subtitle_folder_import(
            payload.folder_path,
            preferred_library_id=payload.preferred_library_id,
            target_library_id=payload.target_library_id,
            target_folder_path=payload.target_folder_path,
            source_rjcode_hint=payload.source_rjcode_hint,
            use_filter_rules=payload.use_filter_rules,
            subtitle_filter_rules=payload.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "folder_import",
                result if isinstance(result, dict) else {},
                folder_path=payload.folder_path,
            )
        except Exception:
            logger.debug("[操作记录] 文件夹补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/task/{task_id}/cleanup")
async def cleanup_linked_subtitle_workbench(task_id: str):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.cleanup_workbench_subtitles(task_id)
        return {"success": True, "result": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("字幕补配工作台文件清理失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@app.get("/api/rj-subtitle/connectivity-test")
async def rj_subtitle_connectivity_test():
    """测试 RJ 字幕流程依赖的远端连通性。"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        service = get_asmr_download_service()
        return await service.test_connectivity()
    except Exception as e:
        logger.error("RJ 字幕连通性测试失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"连通性测试失败: {str(e)}")


class DLsiteConnectivityTestRequest(BaseModel):
    http_proxy: Optional[str] = None


@app.post("/api/dlsite/connectivity-test")
async def dlsite_connectivity_test(payload: DLsiteConnectivityTestRequest):
    """测试 DLsite 元数据链路连通性。"""
    from ..core.dlsite_service import get_dlsite_service

    try:
        service = get_dlsite_service()
        return await service.test_connectivity(http_proxy=payload.http_proxy)
    except Exception as e:
        logger.error("DLsite 连通性测试失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"DLsite 连通性测试失败: {str(e)}")


class ASMRSyncScanRequest(BaseModel):
    """ASMR 同步扫描请求"""
    folder_path: str

class ASMRSyncStartRequest(BaseModel):
    """ASMR 同步开始请求"""
    items: List[dict]  # [{rjcode, subtitle_folder, work_title}]
    auto_classify: bool = True


class ASMRSyncEnhancedPlanRequest(BaseModel):
    """增强下载计划请求"""
    rjcodes: List[str]
    folder_path: Optional[str] = ""
    resource_types: List[str] = []
    audio_formats: List[str] = []
    subtitle_languages: List[str] = []
    include_existing: bool = False
    refresh: bool = False


class ASMRSyncEnhancedStartRequest(BaseModel):
    """增强下载启动请求"""
    items: List[dict]  # [{rjcode, work_title, selected_resources, folder_path, upload_options}]
    auto_classify: bool = False


class ASMRSyncEnhancedPriorityRequest(BaseModel):
    queue_priority: int


class CircleCompletionIndexRequest(BaseModel):
    circle_query: str
    force_refresh: bool = False
    include_dlsite: bool = True
    include_kikoeru: bool = True
    only_new_works: bool = False


class CircleCompletionIndexJobRequest(BaseModel):
    circle_query: str
    circle_queries: List[str] = []
    force_refresh: bool = True
    include_dlsite: bool = True
    include_kikoeru: bool = True
    only_new_works: bool = False
    is_refresh_all: bool = False


class CircleCompletionBonusProbeStartRequest(BaseModel):
    circle_id: str
    maker_id: str = ""
    release_dates: List[str] = []
    selected_rjcodes_by_date: Dict[str, List[str]] = {}
    mode: str = "normal"
    gap_limit: int = 500
    batch_size: Optional[int] = None
    concurrency: Optional[int] = None


class CircleCompletionDownloadPreviewRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]
    requested_rjcodes: Dict[str, List[str]] = {}


class CircleCompletionRefreshSelectedRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]
    force_refresh: bool = False
    owned_only: bool = False


class CircleCompletionRefreshSelectedJobRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    canonical_rjcodes: List[str]
    force_refresh: bool = False
    owned_only: bool = False


class CircleCompletionCoverFetchRequest(BaseModel):
    rjcode: str
    variant: str = "card"
    force: bool = False


class CircleCompletionExternalSearchRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]


class CircleCompletionExternalSearchTestRequest(BaseModel):
    south_plus_cookie: Optional[str] = None
    south_plus_proxy: Optional[str] = None


class CircleCompletionDownloadStartRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    items: List[dict]
    batch_options: Dict[str, Any] = {}


class ASMRRetryFailedResourcesRequest(BaseModel):
    relative_paths: List[str] = []


class ASMRReimportDownloadedRequest(BaseModel):
    target_library_id: str
    target_subdir: str = ""


class ASMRReimportLocalDownloadRequest(BaseModel):
    download_root: str
    rjcode: str
    circle_name: str = ""
    target_library_id: str
    target_subdir: str = ""


class ASMRSyncLocateRJRequest(BaseModel):
    """跨库存按 RJ 号定位作品文件夹请求"""
    rjcodes: List[str]
    library_ids: Optional[List[str]] = None


class HttpDownloadPreviewRequest(BaseModel):
    urls: List[str]
    target_subdir: str = ""
    conflict_policy: str = ""


class HttpDownloadStartRequest(BaseModel):
    urls: List[str]
    target_subdir: str = ""
    conflict_policy: str = ""
    batch_name: str = ""
    selected_keys: List[str] = []
    selected_items: List[dict] = []


class HttpDownloadRetryFileRequest(BaseModel):
    file: dict = Field(default_factory=dict)


class BaiduNetdiskRetryFileRequest(BaseModel):
    file: dict = Field(default_factory=dict)


class BaiduNetdiskPreviewRequest(BaseModel):
    urls: List[str]
    target_subdir: str = ""
    output_folder_name: str = ""
    batch_name: str = ""
    conflict_policy: str = ""
    selected_keys: List[str] = []
    selected_items: List[dict] = []


class BaiduNetdiskStartRequest(BaseModel):
    urls: List[str]
    target_subdir: str = ""
    output_folder_name: str = ""
    batch_name: str = ""
    conflict_policy: str = ""
    selected_keys: List[str] = []
    selected_items: List[dict] = []


class BaiduNetdiskCancelRequest(BaseModel):
    task_id: str = ""


class BaiduNetdiskUploadStartRequest(BaseModel):
    source_paths: List[str] = []
    remote_dir: str = "/KikoeruManager"
    create_remote_subdir: str = ""
    compress_enabled: bool = False
    backup_zip_options: Dict[str, Any] = Field(default_factory=dict)
    conflict_policy: str = "skip"
    cleanup_local_archive: bool = False
    batch_name: str = ""


class BaiduNetdiskAccountTestRequest(BaseModel):
    cookie: str = ""
    persist: bool = False
    allow_quota_failure: bool = False


class BaiduNetdiskPasswordLoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    persist: bool = True


class BaiduNetdiskOfficialLoginCompleteRequest(BaseModel):
    persist: bool = True


class BaiduNetdiskQrLoginPollRequest(BaseModel):
    session_id: str = ""
    persist: bool = True


class BaiduNetdiskQrLoginCloseRequest(BaseModel):
    session_id: str = ""


class GoogleDriveOAuthTokenRequest(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    authorization_code: str = ""
    redirect_uri: str = "http://localhost:5555/api/http-download/google-drive/oauth-callback"
    code_verifier: str = ""


class GoogleDriveOAuthBeginRequest(BaseModel):
    client_mode: str = "builtin"
    client_id: str = ""
    client_secret: str = ""
    opener_origin: str = ""


class PikPakTransferDeleteRequest(BaseModel):
    ids: List[str]
    permanent: bool = False
    account_id: str = ""


class PikPakAccountTestRequest(BaseModel):
    account_id: str = ""
    account: dict = Field(default_factory=dict)
    use_saved: bool = False


_GOOGLE_DRIVE_OAUTH_STATE_TTL_SECONDS = 600
_google_drive_oauth_states: dict[str, dict[str, Any]] = {}


_circle_completion_refresh_history: dict[str, deque[float]] = defaultdict(deque)


def _resolve_circle_completion_force_refresh(circle_id: str, requested_force_refresh: bool = False) -> tuple[bool, str]:
    if requested_force_refresh:
        return True, "manual"
    normalized_circle_id = str(circle_id or "").strip()
    if not normalized_circle_id:
        return False, ""
    now_ts = datetime.now().timestamp()
    history = _circle_completion_refresh_history[normalized_circle_id]
    while history and now_ts - history[0] > 60:
        history.popleft()
    history.append(now_ts)
    if len(history) >= 3:
        return True, "auto_threshold"
    return False, ""


def _download_status_cache_get(cache_key: str, version: int) -> Optional[Dict[str, Any]]:
    cached = _DOWNLOAD_STATUS_CACHE.get(cache_key)
    if not cached:
        return None
    cached_at = float(cached.get("cached_at") or 0.0)
    cached_version = int(cached.get("version") or -1)
    # 进度 tick 高频变化时允许 1 秒内复用，避免状态轮询重复清洗大 metadata。
    if cached_version == version and time.monotonic() - cached_at <= _DOWNLOAD_STATUS_CACHE_TTL_SECONDS:
        payload = cached.get("payload")
        if isinstance(payload, dict):
            return copy.deepcopy(payload)
    return None


def _download_status_cache_set(cache_key: str, version: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    _DOWNLOAD_STATUS_CACHE[cache_key] = {
        "version": int(version or 0),
        "cached_at": time.monotonic(),
        "payload": copy.deepcopy(payload),
    }
    return payload


class LocalUploadStartRequest(BaseModel):
    source_library_id: str
    source_base_path: str
    selected_paths: List[str]
    target_library_id: str
    target_subdir: str = ""
    circle_name: str = ""


def _serialize_http_download_task(task) -> dict:
    from ..core.baidu_netdisk_service import build_baidu_netdisk_batch_title, sanitize_baidu_netdisk_item
    from ..core.http_download_service import build_http_download_batch_title, sanitize_http_download_item

    metadata = _task_metadata_with_redis_runtime(task)
    download_mode = str(metadata.get("download_mode") or "http")
    is_baidu_netdisk = download_mode == "baidu_netdisk" or metadata.get("task_domain") == "baidu_netdisk"
    failed_files = list(metadata.get("failed_files") or [])
    status_value, progress, current_step = _task_runtime_response_values(task)
    sanitize_download_item = sanitize_baidu_netdisk_item if is_baidu_netdisk else sanitize_http_download_item
    download_files = [
        sanitize_download_item(item)
        for item in list(metadata.get("download_files") or [])
    ]
    performance_metrics = metadata.get("performance_metrics") if isinstance(metadata.get("performance_metrics"), dict) else {}
    success_count = int(performance_metrics.get("success_count") or 0)
    if not success_count:
        success_count = len([item for item in download_files if str((item or {}).get("status") or "") == "completed"])
    display_status = "partial_failed" if failed_files and success_count > 0 else status_value
    work_title = (
        metadata.get("batch_name")
        or metadata.get("source_label")
        or (
            build_baidu_netdisk_batch_title(metadata, item_count=len(download_files))
            if is_baidu_netdisk
            else build_http_download_batch_title(metadata, item_count=len(download_files))
        )
        or ("百度网盘下载" if is_baidu_netdisk else "HTTP 下载")
    )
    return {
        "id": task.id,
        "rjcode": "",
        "work_title": work_title,
        "source_label": metadata.get("source_label", ""),
        "status": status_value,
        "display_status": display_status,
        "progress": progress,
        "current_step": current_step,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "started_at": task.started_at.isoformat() if getattr(task, "started_at", None) else None,
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "output_path": getattr(task, "output_path", ""),
        "download_files": download_files,
        "download_runtime": metadata.get("download_runtime", {}),
        "failed_files": [sanitize_download_item(item) for item in failed_files if isinstance(item, dict)],
        "progress_log": metadata.get("progress_log", []),
        "performance_metrics": performance_metrics,
        "download_mode": download_mode,
        "session_id": metadata.get("session_id", ""),
        "queue_priority": metadata.get("queue_priority", metadata.get("priority", 100)),
        "task_metadata": {
            "source_action": metadata.get("source_action", ""),
            "download_root": metadata.get("download_root", ""),
            "target_subdir": metadata.get("target_subdir", ""),
            "output_folder_name": metadata.get("output_folder_name", ""),
            "staging_dir": metadata.get("staging_dir", ""),
            "final_output_path": metadata.get("final_output_path", ""),
            "renamed_output_path": metadata.get("renamed_output_path", ""),
            "output_finalize_status": metadata.get("output_finalize_status", ""),
            "failure_reason": metadata.get("failure_reason", ""),
            "url_count": metadata.get("url_count", 0),
            "retry_count": metadata.get("retry_count", 0),
            "download_mode": download_mode,
            "source_modes": metadata.get("source_modes", []),
            "platforms": metadata.get("platforms", []),
            "platform_label": metadata.get("platform_label", ""),
            "svip_speed": bool(metadata.get("svip_speed")),
        },
    }


def _serialize_local_upload_task_status(task) -> dict:
    metadata = _task_metadata_with_redis_runtime(task)
    status_value, progress, current_step = _task_runtime_response_values(task)
    return {
        "id": task.id,
        "status": status_value,
        "display_status": (
            "partial_failed"
            if (
                metadata.get("local_cleanup_status") == "failed"
                or metadata.get("verification_failures")
                or metadata.get("failed_files")
            )
            else status_value
        ),
        "progress": progress,
        "current_step": current_step,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "started_at": task.started_at.isoformat() if getattr(task, "started_at", None) else None,
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "source_path": task.source_path,
        "output_path": getattr(task, "output_path", ""),
        "upload_files": metadata.get("upload_files", []),
        "uploaded_files": metadata.get("uploaded_files", []),
        "failed_files": metadata.get("failed_files", []),
        "verification_failures": metadata.get("verification_failures", []),
        "source_lock_failures": metadata.get("source_lock_failures", []),
        "upload_runtime": metadata.get("upload_runtime", {}),
        "progress_log": metadata.get("progress_log", []),
        "task_metadata": {
            "source_library_id": metadata.get("source_library_id", ""),
            "source_base_path": metadata.get("source_base_path", ""),
            "selected_paths": metadata.get("selected_paths", []),
            "selected_items": metadata.get("selected_items", []),
            "selected_dir_count": metadata.get("selected_dir_count", 0),
            "target_library_id": metadata.get("target_library_id", ""),
            "target_subdir": metadata.get("target_subdir", ""),
            "circle_name": metadata.get("circle_name", ""),
            "target_path": metadata.get("target_path", ""),
            "final_output_path": metadata.get("final_output_path", ""),
            "upload_result": metadata.get("upload_result", {}),
            "failure_reason": metadata.get("failure_reason", ""),
            "source_lock_failures": metadata.get("source_lock_failures", []),
            "local_cleanup_status": metadata.get("local_cleanup_status", ""),
            "local_cleanup_error": metadata.get("local_cleanup_error", ""),
            "remote_upload_verified": bool(metadata.get("remote_upload_verified")),
            "source_action": metadata.get("source_action", ""),
            "source_label": metadata.get("source_label", ""),
        },
    }


def _serialize_asmr_sync_task_status(task, session_map: Dict[str, dict]) -> dict:
    metadata = _task_metadata_with_redis_runtime(task)
    status_value, progress, current_step = _task_runtime_response_values(task)
    session_id = str(metadata.get("session_id") or "").strip()
    session_state = session_map.get(session_id, {})
    return {
        "session_state": session_state,
        "id": task.id,
        "rjcode": metadata.get("rjcode", ""),
        "actual_rjcode": metadata.get("actual_rjcode", ""),
        "work_title": metadata.get("work_title", ""),
        "source_label": metadata.get("source_label", ""),
        "status": status_value,
        "display_status": "partial_failed" if (status_value == "completed" and (metadata.get("failed_files") or metadata.get("verification_failures") or metadata.get("failure_reason"))) else status_value,
        "progress": progress,
        "current_step": current_step,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "started_at": task.started_at.isoformat() if getattr(task, "started_at", None) else None,
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "output_path": getattr(task, "output_path", ""),
        "download_files": metadata.get("download_files", []),
        "download_runtime": metadata.get("download_runtime", {}),
        "upload_files": metadata.get("upload_files", []),
        "upload_runtime": metadata.get("upload_runtime", {}),
        "failed_files": metadata.get("failed_files", []),
        "uploaded_files": metadata.get("uploaded_files", []),
        "verification_failures": metadata.get("verification_failures", []),
        "progress_log": metadata.get("progress_log", []),
        "performance_metrics": metadata.get("performance_metrics", {}),
        "sync_result": metadata.get("sync_result", {}),
        "subtitle_moved_to": metadata.get("subtitle_moved_to", ""),
        "download_mode": metadata.get("download_mode", "legacy"),
        "session_id": session_id,
        "queue_priority": metadata.get("queue_priority", metadata.get("priority", 100)),
        "task_metadata": {
            "retry_reason": metadata.get("retry_reason", ""),
            "retry_count": metadata.get("retry_count", 0),
            "retry_after": metadata.get("retry_after", ""),
            "selected_resource_count": metadata.get("selected_resource_count", 0),
            "selected_resources": metadata.get("selected_resources", []),
            "verify_summary": metadata.get("verify_summary", {}),
            "upload_summary": metadata.get("upload_summary", {}),
            "retry_summary": metadata.get("retry_summary", {}),
            "source_action": metadata.get("source_action", ""),
            "circle_name": metadata.get("circle_name", ""),
            "download_root": session_state.get("local_download_root") or metadata.get("download_root", ""),
            "download_base_path": metadata.get("download_base_path", ""),
            "final_output_path": metadata.get("final_output_path", ""),
            "target_path": metadata.get("target_path", ""),
            "failure_reason": metadata.get("failure_reason", ""),
            "local_download_ready": session_state.get("local_download_ready", False),
            "local_download_root": session_state.get("local_download_root", ""),
            "local_downloaded_count": session_state.get("local_downloaded_count", 0),
        }
    }


def _serialize_rj_subtitle_task_status(task) -> dict:
    metadata = _task_metadata_with_redis_runtime(task)
    status_value, progress, current_step = _task_runtime_response_values(task)
    return {
        "id": task.id,
        "rjcode": metadata.get("rjcode", ""),
        "actual_rjcode": metadata.get("actual_rjcode", ""),
        "folder_name": metadata.get("folder_name", ""),
        "folder_path": metadata.get("folder_path", task.source_path),
        "library_id": metadata.get("library_id", ""),
        "status": status_value,
        "is_cancelled": task.is_cancelled(),
        "progress": progress,
        "current_step": current_step,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "source_lang": metadata.get("source_lang", ""),
        "source_work_type": metadata.get("source_work_type", ""),
        "source_title": metadata.get("source_title", ""),
        "source_mode": metadata.get("source_mode", ""),
        "target_rjcode": metadata.get("target_rjcode", ""),
        "target_folder_path": metadata.get("target_folder_path", ""),
        "target_library_id": metadata.get("target_library_id", ""),
        "subtitle_library_id": metadata.get("subtitle_library_id", metadata.get("library_id", "")),
        "source_archive_path": metadata.get("source_archive_path", ""),
        "source_subtitle_folder_path": metadata.get("source_subtitle_folder_path", ""),
        "import_reason": metadata.get("import_reason", ""),
        "kikoeru_checked_rjcode": metadata.get("kikoeru_checked_rjcode", ""),
        "kikoeru_has_work": metadata.get("kikoeru_has_work", False),
        "kikoeru_has_existing_subtitles": metadata.get("kikoeru_has_existing_subtitles", False),
        "kikoeru_matched_rjcode": metadata.get("kikoeru_matched_rjcode", ""),
        "kikoeru_subtitle_file_count": metadata.get("kikoeru_subtitle_file_count", 0),
        "kikoeru_subtitle_check_source": metadata.get("kikoeru_subtitle_check_source", ""),
        "downloaded_count": metadata.get("downloaded_count", 0),
        "existing_subtitle_count": metadata.get("existing_subtitle_count", 0),
        "subtitle_dir": metadata.get("subtitle_dir", ""),
        "linked_workbench_root_dir": metadata.get("linked_workbench_root_dir", ""),
        "written_files": metadata.get("written_files", []),
        "skipped_files": metadata.get("skipped_files", []),
        "write_errors": metadata.get("write_errors", []),
        "failed_files": metadata.get("failed_files", []),
        "match_result": metadata.get("match_result", {}),
        "search_attempts": metadata.get("search_attempts", []),
        "download_files": metadata.get("download_files", []),
        "filtered_out_count": metadata.get("filtered_out_count", 0),
        "content_deduped_count": metadata.get("content_deduped_count", 0),
        "content_deduped_files": metadata.get("content_deduped_files", []),
        "renamed_collision_files": metadata.get("renamed_collision_files", []),
        "progress_log": metadata.get("progress_log", []),
        "awaiting_manual_match": metadata.get("awaiting_manual_match", False),
        "manual_match_completed": metadata.get("manual_match_completed", False),
        "manual_match_applied_pairs": metadata.get("manual_match_applied_pairs", 0),
        "manual_match_deleted_subtitles": metadata.get("manual_match_deleted_subtitles", 0),
        "naming_strategy": metadata.get("naming_strategy", "audio"),
        "linked_subtitle_cleanup_result": metadata.get("linked_subtitle_cleanup_result"),
    }


def _http_download_urls_from_payload(urls: List[str]) -> list[str]:
    result = []
    last_pikpak_index: Optional[int] = None
    for raw in urls or []:
        for line in re.split(r"[\r\n]+", str(raw or "")):
            value = line.strip()
            if not value:
                continue
            if last_pikpak_index is not None and not value.lower().startswith(("http://", "https://")):
                match = re.search(r"(?:pwd|pass_code|passcode|password|code)\s*[=:：]\s*([A-Za-z0-9]{4,12})|(?:提取码|访问码|密[码碼])[:：\s]*([A-Za-z0-9]{4,12})|^([A-Za-z0-9]{4,12})$", value, re.IGNORECASE)
                if match and ("mypikpak.com" in result[last_pikpak_index] or "drive.mypikpak.com" in result[last_pikpak_index]):
                    code = next((group for group in match.groups() if group), "")
                    if code and "pwd=" not in result[last_pikpak_index] and "pass_code=" not in result[last_pikpak_index]:
                        separator = "&" if "?" in result[last_pikpak_index] else "?"
                        result[last_pikpak_index] = f"{result[last_pikpak_index]}{separator}pwd={quote(code)}"
                        continue
            result.append(value)
            last_pikpak_index = len(result) - 1 if "mypikpak.com" in value or "drive.mypikpak.com" in value else None
    return result


def _baidu_netdisk_urls_from_payload(urls: List[str]) -> list[str]:
    config = get_config()
    separator = str(getattr(config.baidu_netdisk, "share_code_separator", "") or "----").strip()
    result = []
    seen: dict[str, int] = {}
    last_baidu_index: Optional[int] = None
    for raw in urls or []:
        for line in re.split(r"[\r\n]+", str(raw or "")):
            value = line.strip()
            if not value:
                continue
            normalized = _normalize_baidu_netdisk_share_line(value, separator)
            if _is_baidu_netdisk_share_url(normalized):
                key = _baidu_netdisk_share_identity(normalized)
                if key in seen:
                    existing_index = seen[key]
                    if not _baidu_netdisk_share_has_code(result[existing_index]) and _baidu_netdisk_share_has_code(normalized):
                        result[existing_index] = normalized
                    last_baidu_index = existing_index
                    continue
                result.append(normalized)
                seen[key] = len(result) - 1
                last_baidu_index = len(result) - 1
                continue
            code = _baidu_netdisk_pass_code_from_text(value)
            if code and last_baidu_index is not None:
                if not _baidu_netdisk_share_has_code(result[last_baidu_index]):
                    result[last_baidu_index] = _append_baidu_netdisk_pass_code(result[last_baidu_index], code)
                continue
            result.append(normalized)
    return result


def _broadcast_processed_archive_changed_safe(archive) -> None:
    try:
        from ..core.task_center_event_service import broadcast_processed_archive_changed
        broadcast_processed_archive_changed(archive)
    except Exception:
        logger.debug("广播归档更新事件失败", exc_info=True)


def _is_baidu_netdisk_share_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://")) and (
        "pan.baidu.com" in text
        or "yun.baidu.com" in text
        or "eyun.baidu.com" in text
    )


def _baidu_netdisk_pass_code_from_text(value: str) -> str:
    match = re.search(
        r"(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})$",
        str(value or "").strip(),
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _baidu_netdisk_share_has_code(value: str) -> bool:
    return bool(re.search(r"[?&](?:pwd|password|passcode|pass_code|code)=", str(value or ""), re.IGNORECASE))


def _append_baidu_netdisk_pass_code(share_url: str, code: str) -> str:
    if not code or _baidu_netdisk_share_has_code(share_url):
        return share_url
    return f"{share_url}{'&' if '?' in share_url else '?'}pwd={quote(code)}"


def _baidu_netdisk_share_identity(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"([?&])(?:pwd|password|passcode|pass_code|code)=[^&#]*", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\?&", "?", text)
    text = re.sub(r"[?&]($|#)", r"\1", text)
    return text.rstrip("?&")


def _normalize_baidu_netdisk_share_line(value: str, separator: str) -> str:
    text = str(value or "").strip()
    if not text or not separator or separator not in text:
        inline = re.search(
            r"^(https?://\S+?)\s+(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})\s*$",
            text,
            re.IGNORECASE,
        )
        if not inline:
            return text
        share_url = inline.group(1).strip()
        code = inline.group(2).strip()
    else:
        left, right = text.rsplit(separator, 1)
        share_url = left.strip()
        code_text = right.strip()
        match = re.search(
            r"(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})$",
            code_text,
            re.IGNORECASE,
        )
        if not match:
            return text
        code = match.group(1).strip()
    if not _is_baidu_netdisk_share_url(share_url):
        return text
    return _append_baidu_netdisk_pass_code(share_url, code)


def _google_drive_oauth_redirect_uri(request: Request) -> str:
    return str(request.url_for("http_download_google_drive_oauth_callback"))


def _google_drive_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _google_drive_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(str(verifier or "").encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _cleanup_google_drive_oauth_states() -> None:
    now = time.time()
    expired = [
        key for key, value in _google_drive_oauth_states.items()
        if now - float(value.get("created_at") or 0) > _GOOGLE_DRIVE_OAUTH_STATE_TTL_SECONDS
    ]
    for key in expired:
        _google_drive_oauth_states.pop(key, None)


def _normalize_google_drive_oauth_opener_origin(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "*"
    if re.match(r"^https?://[^/\s]+$", text):
        return text
    return "*"


def _google_drive_account_from_about_payload(data: dict) -> dict:
    user = data.get("user") if isinstance(data, dict) else {}
    if not isinstance(user, dict):
        user = {}
    return {
        "name": str(user.get("displayName") or "").strip(),
        "email": str(user.get("emailAddress") or "").strip(),
        "avatar_url": str(user.get("photoLink") or "").strip(),
        "permission_id": str(user.get("permissionId") or "").strip(),
        "cached_at": int(time.time()),
    }


def _persist_google_drive_oauth_payload(session: dict, token_payload: dict) -> dict:
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise HTTPException(status_code=502, detail="Google OAuth 未返回 Refresh Token")

    account = token_payload.get("account") if isinstance(token_payload.get("account"), dict) else {}
    account_payload = {
        "name": str(account.get("name") or "").strip(),
        "email": str(account.get("email") or "").strip(),
        "avatar_url": str(account.get("avatar_url") or "").strip(),
        "permission_id": str(account.get("permission_id") or "").strip(),
        "cached_at": int(account.get("cached_at") or time.time()),
    } if account else {
        "name": "",
        "email": "",
        "avatar_url": "",
        "permission_id": "",
        "cached_at": 0,
    }
    client_mode = str(session.get("client_mode") or "builtin").strip() or "builtin"
    updates = {
        "google_drive_oauth_enabled": True,
        "google_drive_oauth_client_mode": client_mode,
        "google_drive_refresh_token": refresh_token,
        "google_drive_account_name": account_payload["name"],
        "google_drive_account_email": account_payload["email"],
        "google_drive_account_avatar_url": account_payload["avatar_url"],
        "google_drive_account_permission_id": account_payload["permission_id"],
        "google_drive_account_cached_at": account_payload["cached_at"],
        "google_drive_oauth_expired": False,
    }
    if client_mode == "custom":
        updates["google_drive_client_id"] = str(session.get("client_id") or "").strip()
        updates["google_drive_client_secret"] = str(session.get("client_secret") or "").strip()
    try:
        save_config({"http_downloader": updates})
    except Exception as exc:
        logger.warning("Google Drive OAuth 授权结果保存失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"Google Drive OAuth 授权成功但保存配置失败: {str(exc)}") from exc
    return {
        **token_payload,
        "account": account_payload,
        "persisted": True,
    }


async def _exchange_google_drive_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    authorization_code: str,
    redirect_uri: str,
    code_verifier: str = "",
) -> dict:
    client_id = str(client_id or "").strip()
    client_secret = str(client_secret or "").strip()
    authorization_code = str(authorization_code or "").strip()
    redirect_uri = str(redirect_uri or "").strip()
    code_verifier = str(code_verifier or "").strip()
    if not client_id or not authorization_code:
        raise HTTPException(status_code=400, detail="Client ID 和授权码不能为空")
    proxy = ""
    try:
        import aiohttp

        payload = {
            "client_id": client_id,
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if client_secret:
            payload["client_secret"] = client_secret
        if code_verifier:
            payload["code_verifier"] = code_verifier
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        proxy = resolve_google_drive_oauth_proxy_url(get_config())
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://oauth2.googleapis.com/token", data=payload, proxy=proxy or None) as response:
                body = await response.text()
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Google OAuth 返回 HTTP {response.status}: {body[:160]}")
                try:
                    data = json.loads(body)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail="Google OAuth 返回不是 JSON") from exc
        refresh_token = str(data.get("refresh_token") or "").strip()
        if not refresh_token:
            raise HTTPException(status_code=502, detail="Google OAuth 未返回 refresh_token；请在授权弹窗里重新同意 Drive 访问权限")
        account = {}
        access_token = str(data.get("access_token") or "").strip()
        if access_token:
            about_url = "https://www.googleapis.com/drive/v3/about?fields=user(displayName,emailAddress,photoLink,permissionId)"
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(about_url, headers=headers, proxy=proxy or None) as response:
                        body = await response.text()
                        if response.status >= 400:
                            logger.warning(
                                "Google Drive OAuth 账号信息读取失败: HTTP %s: %s",
                                response.status,
                                sanitize_text_for_log(body, max_length=160),
                            )
                        else:
                            account = _google_drive_account_from_about_payload(json.loads(body))
            except Exception as exc:
                logger.warning("Google Drive OAuth 账号信息读取失败，已跳过账号缓存: %s", sanitize_text_for_log(exc))
        return {
            "success": True,
            "refresh_token": refresh_token,
            "scope": str(data.get("scope") or ""),
            "token_type": str(data.get("token_type") or ""),
            "expires_in": int(data.get("expires_in") or 0),
            "account": account,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Google Drive OAuth 换取 refresh token 失败: %s", sanitize_text_for_log(exc))
        error_text = str(exc) or exc.__class__.__name__
        if isinstance(exc, asyncio.TimeoutError) or "timeout" in error_text.lower():
            proxy_state = f"当前 OAuth 代理: {_mask_url_credentials(proxy)}" if proxy else "当前 OAuth 请求未配置代理"
            raise HTTPException(
                status_code=502,
                detail=(
                    "Google Drive OAuth 换取超时：后端无法连接 https://oauth2.googleapis.com/token。"
                    f"{proxy_state}，请检查 HTTP 下载代理或全局 metadata.http_proxy。"
                ),
            )
        raise HTTPException(status_code=500, detail=f"Google Drive OAuth 换取失败: {str(exc)}")


def _safe_json_for_inline_script(payload: Any) -> str:
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _google_drive_oauth_popup_html(payload: dict, target_origin: str = "*") -> str:
    payload_json = _safe_json_for_inline_script(payload)
    target_origin_json = _safe_json_for_inline_script(target_origin or "*")
    safe_message = html.escape(str(payload.get("message") or "Google Drive 授权完成"))
    safe_status = html.escape("授权成功" if payload.get("success") else "授权失败")
    return f"""
    <!doctype html>
    <html lang="zh-CN"><head><meta charset="utf-8"><title>Google Drive OAuth</title></head>
    <body style="font-family: system-ui, sans-serif; padding: 32px; color: #111827;">
      <h2>{safe_status}</h2>
      <p>{safe_message}</p>
      <p style="color: #6b7280;">这个窗口会自动关闭。</p>
      <script>
        const payload = {payload_json};
        const targetOrigin = {target_origin_json} || "*";
        if (window.opener) {{
          window.opener.postMessage({{ type: "kikoerumanager:google-drive-oauth", payload }}, targetOrigin);
        }}
        setTimeout(() => window.close(), 450);
      </script>
    </body></html>
    """


@app.get("/api/http-download/health")
async def http_download_health():
    from ..core.http_download_service import get_http_download_service

    try:
        return await get_http_download_service().health()
    except Exception as exc:
        logger.warning("HTTP 下载健康检查失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(exc)}")


@app.post("/api/http-download/preview")
async def http_download_preview(request: HttpDownloadPreviewRequest):
    from ..core.http_download_service import get_http_download_service, sanitize_http_download_preview

    urls = _http_download_urls_from_payload(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="至少需要一个下载链接")
    if len(urls) > 100:
        raise HTTPException(status_code=400, detail="单次最多预览 100 个链接")
    try:
        preview = await get_http_download_service().preview_urls(
            urls,
            target_subdir=request.target_subdir,
            conflict_policy=request.conflict_policy,
        )
        return sanitize_http_download_preview(preview)
    except Exception as exc:
        logger.warning("HTTP 下载预览失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"预览失败: {str(exc)}")


@app.post("/api/http-download/start")
async def http_download_start(request: HttpDownloadStartRequest):
    from ..core.http_download_service import (
        build_http_download_batch_title,
        get_http_download_service,
        http_download_platforms_label,
        normalize_http_download_platform,
        sanitize_http_download_preview,
    )
    from ..core.task_engine import Task, TaskType, get_task_engine

    urls = _http_download_urls_from_payload(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="至少需要一个下载链接")
    if len(urls) > 100:
        raise HTTPException(status_code=400, detail="单次最多创建 100 个下载链接")

    service = get_http_download_service()
    preview = await service.preview_urls(urls, target_subdir=request.target_subdir, conflict_policy=request.conflict_policy)
    preview = service.filter_preview_selection(
        preview,
        selected_keys=request.selected_keys,
        selected_items=request.selected_items,
    )
    public_preview = sanitize_http_download_preview(preview)
    ok_items = [item for item in preview.get("items") or [] if item.get("ok")]
    if not ok_items:
        return JSONResponse({"success": False, "message": "没有可下载直链", "preview": public_preview}, status_code=400)

    def _item_source(item: dict) -> str:
        return normalize_http_download_platform(
            (item or {}).get("source")
            or (item or {}).get("host")
            or (item or {}).get("masked_url")
            or (item or {}).get("url")
        )

    source_order: list[str] = []
    ok_items_by_source: dict[str, list[dict]] = {}
    for item in ok_items:
        source = _item_source(item)
        if source not in ok_items_by_source:
            ok_items_by_source[source] = []
            source_order.append(source)
        ok_items_by_source[source].append(item)

    urls_by_source: dict[str, list[str]] = {}
    for raw_url in urls:
        source = normalize_http_download_platform(service._provider_source(raw_url))
        urls_by_source.setdefault(source, []).append(raw_url)

    public_items_by_source: dict[str, list[dict]] = {}
    for item in public_preview.get("items") or []:
        if not isinstance(item, dict):
            continue
        public_items_by_source.setdefault(_item_source(item), []).append(item)

    public_source_items_by_source: dict[str, list[dict]] = {}
    for item in public_preview.get("source_items") or []:
        if not isinstance(item, dict):
            continue
        public_source_items_by_source.setdefault(_item_source(item), []).append(item)

    requested_batch_name = str(request.batch_name or "").strip()
    engine = get_task_engine()
    created_tasks = []
    multi_platform = len(source_order) > 1

    for source in source_order:
        group_ok_items = ok_items_by_source[source]
        group_public_items = public_items_by_source.get(source) or (
            sanitize_http_download_preview({"items": group_ok_items}).get("items") or []
        )
        group_urls = urls_by_source.get(source) or urls
        group_first_host = str(group_ok_items[0].get("host") or "").strip()
        source_modes = [source]
        source_action = f"manual_{source}_download" if source != "http" else "manual_http_download"
        platform_label = http_download_platforms_label(source_modes)
        default_title = build_http_download_batch_title(
            {
                "source_modes": source_modes,
                "download_mode": source,
                "url_count": len(group_ok_items),
            },
            item_count=len(group_ok_items),
            fallback_host=group_first_host,
        )
        label = (
            f"{requested_batch_name} · {platform_label}"
            if requested_batch_name and multi_platform and platform_label != "HTTP"
            else (requested_batch_name or default_title)
        )
        selected_keys = [
            str(item.get("selection_key") or "").strip()
            for item in group_public_items
            if str(item.get("selection_key") or "").strip()
        ]
        task = Task(
            task_type=TaskType.HTTP_DOWNLOAD,
            source_path=group_first_host or f"{source}-download",
            metadata={
                "urls": group_urls,
                "url_count": len(group_ok_items),
                "source_url_count": len(group_urls),
                "selected_keys": selected_keys,
                "selected_items": [
                    {k: v for k, v in dict(item or {}).items() if k != "original_url"}
                    for item in group_public_items
                    if item.get("ok")
                ],
                "target_subdir": request.target_subdir,
                "conflict_policy": request.conflict_policy,
                "batch_name": label,
                "download_mode": source,
                "source_modes": source_modes,
                "platforms": source_modes,
                "platform_label": platform_label,
                "task_domain": "http_download",
                "task_kind": TaskType.HTTP_DOWNLOAD.value,
                "source_page": "asmr-sync",
                "source_action": source_action,
                "source_label": label,
                "business_key": f"http_download:{source}:{uuid.uuid4().hex}",
                "preview_items": [
                    {k: v for k, v in dict(item or {}).items() if k != "url"}
                    for item in group_public_items
                ],
                "source_items": public_source_items_by_source.get(source) or [],
            },
        )
        await engine.submit(task)
        created_tasks.append({"task_id": task.id, "id": task.id, "platform": source, "platform_label": platform_label})

    message = (
        f"已按平台创建 {len(created_tasks)} 个 HTTP 下载任务，共 {len(ok_items)} 个直链"
        if len(created_tasks) > 1
        else f"已创建 {created_tasks[0]['platform_label']} 下载任务，共 {len(ok_items)} 个直链"
    )
    return {
        "success": True,
        "message": message,
        "task": created_tasks[0],
        "tasks": created_tasks,
        "preview": public_preview,
    }


@app.post("/api/http-download/google-drive/oauth-begin")
async def http_download_google_drive_oauth_begin(payload: GoogleDriveOAuthBeginRequest, request: Request):
    client_secret = str(payload.client_secret or "").strip()
    if client_secret == "********":
        current_secret = str(getattr(get_config().http_downloader, "google_drive_client_secret", "") or "")
        client_secret = _read_http_downloader_secret_from_disk("google_drive_client_secret") or (
            current_secret if current_secret != "********" else ""
        )
    oauth_client = resolve_google_drive_oauth_client(
        config=get_config(),
        mode=payload.client_mode,
        client_id=payload.client_id,
        client_secret=client_secret,
    )
    if not oauth_client:
        raise HTTPException(status_code=400, detail=google_drive_oauth_client_missing_message(payload.client_mode))

    _cleanup_google_drive_oauth_states()
    state = secrets.token_urlsafe(32)
    code_verifier = _google_drive_pkce_verifier()
    redirect_uri = _google_drive_oauth_redirect_uri(request)
    opener_origin = _normalize_google_drive_oauth_opener_origin(payload.opener_origin)
    _google_drive_oauth_states[state] = {
        "client_id": oauth_client.client_id,
        "client_secret": oauth_client.client_secret,
        "client_mode": oauth_client.mode,
        "client_source": oauth_client.source,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "opener_origin": opener_origin,
        "created_at": time.time(),
    }
    params = {
        "client_id": oauth_client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": _google_drive_pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return {
        "success": True,
        "auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}",
        "redirect_uri": redirect_uri,
        "client_mode": oauth_client.mode,
        "client_source": oauth_client.source,
        "expires_in": _GOOGLE_DRIVE_OAUTH_STATE_TTL_SECONDS,
    }


@app.get("/api/http-download/google-drive/oauth-callback")
async def http_download_google_drive_oauth_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    _cleanup_google_drive_oauth_states()
    state_key = str(state or "").strip()
    session = _google_drive_oauth_states.pop(state_key, None) if state_key else None
    target_origin = _normalize_google_drive_oauth_opener_origin(session.get("opener_origin") if session else "")

    if not session:
        body = _google_drive_oauth_popup_html({
            "success": False,
            "message": "Google Drive OAuth 会话已过期，请回到设置页重新登录",
        }, target_origin)
        return Response(content=body, media_type="text/html; charset=utf-8", status_code=400)

    if error:
        body = _google_drive_oauth_popup_html({
            "success": False,
            "message": f"Google 授权失败: {str(error or '')[:160]}",
        }, target_origin)
        return Response(content=body, media_type="text/html; charset=utf-8", status_code=400)

    authorization_code = str(code or "").strip()
    if not authorization_code:
        body = _google_drive_oauth_popup_html({
            "success": False,
            "message": "Google 回调没有返回授权码",
        }, target_origin)
        return Response(content=body, media_type="text/html; charset=utf-8", status_code=400)

    try:
        token_payload = await _exchange_google_drive_authorization_code(
            client_id=session["client_id"],
            client_secret=session["client_secret"],
            authorization_code=authorization_code,
            redirect_uri=session["redirect_uri"],
            code_verifier=session.get("code_verifier", ""),
        )
        token_payload = _persist_google_drive_oauth_payload(session, token_payload)
        body = _google_drive_oauth_popup_html({
            **token_payload,
            "message": "Google Drive 授权已保存到本地配置",
        }, target_origin)
        return Response(content=body, media_type="text/html; charset=utf-8")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        body = _google_drive_oauth_popup_html({
            "success": False,
            "message": detail,
        }, target_origin)
        return Response(content=body, media_type="text/html; charset=utf-8", status_code=exc.status_code)


@app.post("/api/http-download/google-drive/oauth-token")
async def http_download_google_drive_oauth_token(request: GoogleDriveOAuthTokenRequest):
    return await _exchange_google_drive_authorization_code(
        client_id=request.client_id,
        client_secret=request.client_secret,
        authorization_code=request.authorization_code,
        redirect_uri=request.redirect_uri or "http://localhost:5555/api/http-download/google-drive/oauth-callback",
        code_verifier=request.code_verifier,
    )


@app.get("/api/http-download/status")
async def http_download_status():
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        version_getter = getattr(engine, "get_task_center_version", None)
        version = int(version_getter()) if callable(version_getter) else 0
        cached = _download_status_cache_get("http_download", version)
        if cached is not None:
            return cached
        all_tasks = engine.get_all_tasks()
        tasks = [task for task in all_tasks if task.type == TaskType.HTTP_DOWNLOAD]
        payload = {
            "total_tasks": len(tasks),
            "processing": len([t for t in tasks if t.status.value == "processing"]),
            "pending": len([t for t in tasks if t.status.value == "pending"]),
            "completed": len([t for t in tasks if t.status.value == "completed"]),
            "failed": len([t for t in tasks if t.status.value == "failed"]),
            "tasks": [_serialize_http_download_task(t) for t in tasks[:50]],
        }
        return _download_status_cache_set("http_download", version, payload)
    except Exception as exc:
        logger.warning("获取 HTTP 下载状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(exc)}")


@app.get("/api/baidu-netdisk/backend-health")
async def baidu_netdisk_backend_health():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().health()
    except Exception as exc:
        logger.warning("百度网盘后端健康检查失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(exc)}")


@app.get("/api/baidu-netdisk/status")
async def baidu_netdisk_status():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        version_getter = getattr(engine, "get_task_center_version", None)
        version = int(version_getter()) if callable(version_getter) else 0
        cached = _download_status_cache_get("baidu_netdisk", version)
        if cached is not None:
            return cached
        all_tasks = engine.get_all_tasks()
        tasks = [task for task in all_tasks if task.type == TaskType.BAIDU_NETDISK_DOWNLOAD]
        service = get_baidu_netdisk_service()
        payload = {
            "success": True,
            "account": service.account_status(),
            "official_login": service.official_login_status(),
            "total_tasks": len(tasks),
            "processing": len([t for t in tasks if t.status.value == "processing"]),
            "pending": len([t for t in tasks if t.status.value == "pending"]),
            "completed": len([t for t in tasks if t.status.value == "completed"]),
            "failed": len([t for t in tasks if t.status.value == "failed"]),
            "tasks": [_serialize_http_download_task(t) for t in tasks[:50]],
        }
        return _download_status_cache_set("baidu_netdisk", version, payload)
    except Exception as exc:
        logger.warning("获取百度网盘状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(exc)}")


@app.post("/api/baidu-netdisk/preview")
async def baidu_netdisk_preview(request: BaiduNetdiskPreviewRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service, sanitize_baidu_netdisk_preview

    urls = _baidu_netdisk_urls_from_payload(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="至少需要一个百度网盘分享链接")
    if len(urls) > 100:
        raise HTTPException(status_code=400, detail="单次最多预览 100 行链接/提取码")
    try:
        preview = await get_baidu_netdisk_service().preview_urls(
            urls,
            target_subdir=request.target_subdir,
            conflict_policy=request.conflict_policy,
            output_folder_name=request.output_folder_name,
        )
        return sanitize_baidu_netdisk_preview(preview)
    except Exception as exc:
        logger.warning("百度网盘预览失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"预览失败: {str(exc)}")


@app.post("/api/baidu-netdisk/start")
async def baidu_netdisk_start(request: BaiduNetdiskStartRequest):
    from ..core.baidu_netdisk_service import (
        build_baidu_netdisk_batch_title,
        get_baidu_netdisk_service,
        sanitize_baidu_netdisk_preview,
    )
    from ..core.task_engine import Task, TaskType, get_task_engine

    urls = _baidu_netdisk_urls_from_payload(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="至少需要一个百度网盘分享链接")
    if len(urls) > 100:
        raise HTTPException(status_code=400, detail="单次最多创建 100 行链接/提取码")

    service = get_baidu_netdisk_service()
    raw_preview_cache_key = service.raw_preview_cache_key(
        urls,
        target_subdir=request.target_subdir,
        conflict_policy=request.conflict_policy,
        output_folder_name=request.output_folder_name,
    )
    preview = service.get_cached_raw_preview(raw_preview_cache_key)
    if not preview:
        preview = await service.preview_urls(
            urls,
            target_subdir=request.target_subdir,
            conflict_policy=request.conflict_policy,
            output_folder_name=request.output_folder_name,
        )
        raw_preview_cache_key = str(preview.get("raw_preview_cache_key") or raw_preview_cache_key)
    preview = service.filter_preview_selection(
        preview,
        selected_keys=request.selected_keys,
        selected_items=request.selected_items,
    )
    public_preview = sanitize_baidu_netdisk_preview(preview)
    ok_items = [item for item in preview.get("items") or [] if item.get("ok")]
    if not ok_items:
        return JSONResponse({"success": False, "message": "没有可下载的百度网盘分享", "preview": public_preview}, status_code=400)

    requested_batch_name = str(request.batch_name or "").strip()
    default_title = build_baidu_netdisk_batch_title({"url_count": len(ok_items)}, item_count=len(ok_items))
    label = requested_batch_name or default_title
    selected_keys = [
        str(item.get("selection_key") or "").strip()
        for item in public_preview.get("items") or []
        if item.get("ok") and str(item.get("selection_key") or "").strip()
    ]
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": urls,
            "url_count": len(ok_items),
            "source_url_count": len(urls),
            "selected_keys": selected_keys,
            "selected_items": [
                {k: v for k, v in dict(item or {}).items() if k not in {"url", "original_url"}}
                for item in public_preview.get("items") or []
                if item.get("ok")
            ],
            "raw_preview_cache_key": raw_preview_cache_key,
            "raw_selected_items": [
                dict(item or {})
                for item in preview.get("items") or []
                if isinstance(item, dict) and item.get("ok")
            ],
            "target_subdir": request.target_subdir,
            "output_folder_name": request.output_folder_name,
            "conflict_policy": request.conflict_policy,
            "batch_name": label,
            "download_mode": "baidu_netdisk",
            "source_modes": ["baidu_netdisk"],
            "platforms": ["baidu_netdisk"],
            "platform_label": "百度网盘",
            "svip_speed": bool(service.account_status().get("is_svip")),
            "task_domain": "baidu_netdisk",
            "task_kind": TaskType.BAIDU_NETDISK_DOWNLOAD.value,
            "source_page": "asmr-sync",
            "source_action": "manual_baidu_netdisk_download",
            "source_label": label,
            "business_key": f"baidu_netdisk:{uuid.uuid4().hex}",
            "preview_items": [
                {k: v for k, v in dict(item or {}).items() if k != "url"}
                for item in public_preview.get("items") or []
            ],
            "source_items": public_preview.get("source_items") or [],
        },
    )
    await get_task_engine().submit(task)
    return {
        "success": True,
        "message": f"已创建百度网盘下载任务，共 {len(ok_items)} 项",
        "task": {"task_id": task.id, "id": task.id, "platform": "baidu_netdisk", "platform_label": "百度网盘"},
        "tasks": [{"task_id": task.id, "id": task.id, "platform": "baidu_netdisk", "platform_label": "百度网盘"}],
        "preview": public_preview,
    }


@app.post("/api/baidu-netdisk/upload/start")
async def baidu_netdisk_upload_start(request: BaiduNetdiskUploadStartRequest):
    from ..core.backup_zip_service import get_backup_zip_service
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    source_paths = [os.path.abspath(str(path)) for path in request.source_paths if str(path or "").strip()]
    if not source_paths and request.compress_enabled:
        backup_options = dict(request.backup_zip_options or {})
        fallback_source = str(backup_options.get("source_path") or get_config().backup_zip.source_path or get_config().storage.library_path or "").strip()
        if fallback_source:
            source_paths = [os.path.abspath(fallback_source)]
    source_paths = list(dict.fromkeys(source_paths))
    if not source_paths:
        raise HTTPException(status_code=400, detail="没有选中要上传的本地文件或目录")
    for path in source_paths:
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"本地路径不存在: {path}")

    service = get_baidu_netdisk_service()
    remote_dir = service._join_remote_dir(request.remote_dir or "/KikoeruManager", request.create_remote_subdir or "")
    conflict_policy = service._upload_conflict_policy(request.conflict_policy)
    if request.compress_enabled and conflict_policy == "rsync":
        conflict_policy = "skip"
    upload_sources = source_paths
    cleanup_allowed_paths: list[str] = []
    archive_path = ""

    try:
        if request.compress_enabled:
            archive_path = await get_backup_zip_service().create_archive_for_paths(
                source_paths,
                options=dict(request.backup_zip_options or {}),
                output_name=request.batch_name or "",
            )
            upload_sources = [archive_path]
            cleanup_allowed_paths = [archive_path]

        batch_name = (
            str(request.batch_name or "").strip()
            or (os.path.basename(upload_sources[0].rstrip("\\/")) if len(upload_sources) == 1 else f"百度网盘上传 {len(upload_sources)} 项")
        )
        task = Task(
            task_type=TaskType.BAIDU_NETDISK_UPLOAD,
            source_path=upload_sources[0],
            output_path=remote_dir,
            metadata={
                "source_paths": upload_sources,
                "original_source_paths": source_paths,
                "remote_dir": remote_dir,
                "create_remote_subdir": "",
                "conflict_policy": conflict_policy,
                "cleanup_local_archive": bool(request.cleanup_local_archive and archive_path),
                "cleanup_allowed_paths": cleanup_allowed_paths,
                "compressed_before_upload": bool(request.compress_enabled),
                "local_archive_path": archive_path,
                "batch_name": batch_name,
                "source_count": len(source_paths),
                "source_page": "library",
                "source_action": "manual_baidu_netdisk_upload",
                "source_label": batch_name,
                "task_domain": "baidu_netdisk",
                "task_kind": TaskType.BAIDU_NETDISK_UPLOAD.value,
                "platforms": ["baidu_netdisk"],
                "platform_label": "百度网盘",
                "business_key": f"baidu_netdisk_upload:{uuid.uuid4().hex}",
                "upload_files": [],
                "uploaded_files": [],
                "failed_files": [],
                "upload_runtime": {},
                "progress_log": [],
            },
        )
        task_id = await get_task_engine().submit(task)
        return {
            "success": True,
            "message": f"已创建百度网盘上传任务：{batch_name}",
            "task": {"task_id": task_id, "id": task_id, "platform": "baidu_netdisk", "platform_label": "百度网盘"},
            "tasks": [{"task_id": task_id, "id": task_id, "platform": "baidu_netdisk", "platform_label": "百度网盘"}],
            "remote_dir": remote_dir,
            "local_archive_path": archive_path,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("创建百度网盘上传任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"创建百度网盘上传任务失败: {str(exc)}")


@app.post("/api/baidu-netdisk/cancel")
async def baidu_netdisk_cancel(request: BaiduNetdiskCancelRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import TaskType, get_task_engine

    task_id = str(request.task_id or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id 不能为空")
    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
        raise HTTPException(status_code=404, detail="百度网盘任务不存在")
    engine.cancel_task(task_id)
    await get_baidu_netdisk_service().cancel_task(task_id)
    return {"success": True, "message": "任务已取消"}


@app.post("/api/baidu-netdisk/task/{task_id}/pause")
async def baidu_netdisk_pause_task(task_id: str):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
        raise HTTPException(status_code=404, detail="百度网盘任务不存在")
    task.pause()
    await get_baidu_netdisk_service().cancel_task(task_id)
    task.task_metadata["cancel_reason"] = ""
    task.task_metadata["pause_reason"] = "用户暂停"
    return {"success": True, "message": "任务已暂停"}


@app.post("/api/baidu-netdisk/task/{task_id}/resume")
async def baidu_netdisk_resume_task(task_id: str):
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
        raise HTTPException(status_code=404, detail="百度网盘任务不存在")
    engine.resume_task(task_id)
    return {"success": True, "message": "任务已恢复"}


@app.post("/api/baidu-netdisk/task/{task_id}/cancel")
async def baidu_netdisk_cancel_task(task_id: str):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
        raise HTTPException(status_code=404, detail="百度网盘任务不存在")
    engine.cancel_task(task_id)
    await get_baidu_netdisk_service().cancel_task(task_id)
    return {"success": True, "message": "任务已取消"}


@app.post("/api/baidu-netdisk/task/{task_id}/retry")
async def baidu_netdisk_retry_task(task_id: str):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.BAIDU_NETDISK_UPLOAD}:
        raise HTTPException(status_code=404, detail="百度网盘任务不存在")
    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
        raise HTTPException(status_code=400, detail="任务仍在执行中，不能重试")
    if task.type == TaskType.BAIDU_NETDISK_UPLOAD:
        task.task_metadata["upload_files"] = []
        task.task_metadata["uploaded_files"] = []
        task.task_metadata["failed_files"] = []
        task.task_metadata["upload_runtime"] = {}
        task.task_metadata["failure_reason"] = ""
        task.status = TaskStatus.PENDING
        task.progress = 0
        task.current_step = "等待重新上传"
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task._cancelled = False
        task._pause_event.set()
    else:
        await get_baidu_netdisk_service().reset_task_for_retry(task)
    await engine.queue.put(task)
    return {"success": True, "message": "任务已加入重试队列"}


@app.post("/api/baidu-netdisk/task/{task_id}/retry-file")
async def baidu_netdisk_retry_task_file(task_id: str, request: BaiduNetdiskRetryFileRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service, sanitize_baidu_netdisk_item
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.BAIDU_NETDISK_DOWNLOAD:
        raise HTTPException(status_code=404, detail="百度网盘下载任务不存在")
    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
        raise HTTPException(status_code=400, detail="任务仍在执行中，不能重试")

    file_row = request.file if isinstance(request.file, dict) else {}
    if not file_row:
        raise HTTPException(status_code=400, detail="缺少要重试的百度网盘文件")

    service = get_baidu_netdisk_service()
    retry_items, retry_keys = service.build_retry_selection_for_file(task, file_row)
    if not retry_items:
        raise HTTPException(status_code=400, detail="无法识别要重试的百度网盘失败文件")

    task.task_metadata["retry_file"] = sanitize_baidu_netdisk_item(file_row)
    await service.reset_task_for_retry(task, retry_items=retry_items, retry_keys=retry_keys)
    await engine.queue.put(task)
    return {"success": True, "message": "该百度网盘文件已加入重试队列"}


@app.post("/api/baidu-netdisk/account/test")
async def baidu_netdisk_account_test(request: BaiduNetdiskAccountTestRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().test_account(
            request.cookie,
            persist=request.persist,
            allow_quota_failure=request.allow_quota_failure,
        )
    except Exception as exc:
        logger.error("检测百度网盘账号失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/refresh")
async def baidu_netdisk_account_refresh():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().refresh_account_status()
    except Exception as exc:
        logger.error("刷新百度网盘账号状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/password-login")
async def baidu_netdisk_account_password_login(request: BaiduNetdiskPasswordLoginRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().login_with_password(
            request.username,
            request.password,
            persist=request.persist,
        )
    except Exception as exc:
        logger.error("百度账号密码登录失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/official-login/start")
async def baidu_netdisk_account_official_login_start():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().start_official_login_session()
    except Exception as exc:
        logger.warning("打开百度官方登录失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/baidu-netdisk/account/official-login/status")
async def baidu_netdisk_account_official_login_status():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        service = get_baidu_netdisk_service()
        return {
            "success": True,
            "account": service.account_status(),
            "official_login": service.official_login_status(),
        }
    except Exception as exc:
        logger.warning("读取百度官方登录状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/official-login/complete")
async def baidu_netdisk_account_official_login_complete(request: BaiduNetdiskOfficialLoginCompleteRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().complete_official_login_session(persist=request.persist)
    except Exception as exc:
        logger.warning("同步百度官方登录失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/official-login/close")
async def baidu_netdisk_account_official_login_close():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().close_official_login_session()
    except Exception as exc:
        logger.warning("关闭百度官方登录窗口失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/qr-login/start")
async def baidu_netdisk_account_qr_login_start():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().start_qr_login_session()
    except Exception as exc:
        logger.warning("生成百度扫码登录二维码失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/qr-login/poll")
async def baidu_netdisk_account_qr_login_poll(request: BaiduNetdiskQrLoginPollRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return await get_baidu_netdisk_service().poll_qr_login_session(request.session_id, persist=request.persist)
    except Exception as exc:
        logger.warning("轮询百度扫码登录状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/qr-login/close")
async def baidu_netdisk_account_qr_login_close(request: BaiduNetdiskQrLoginCloseRequest):
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return get_baidu_netdisk_service().close_qr_login_session(request.session_id)
    except Exception as exc:
        logger.warning("关闭百度扫码登录失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/baidu-netdisk/account/unbind")
async def baidu_netdisk_account_unbind():
    from ..core.baidu_netdisk_service import get_baidu_netdisk_service

    try:
        return get_baidu_netdisk_service().unbind_account()
    except Exception as exc:
        logger.warning("解绑百度网盘账号失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/http-download/pikpak/status")
async def http_download_pikpak_status(include_files: bool = False, limit: int = 100, account_id: str = "", force_refresh: bool = False):
    from ..core.http_download_service import get_http_download_service

    try:
        return await get_http_download_service().pikpak_status(
            include_files=include_files,
            limit=limit,
            account_id=account_id,
            force_refresh=force_refresh,
        )
    except Exception as exc:
        logger.warning("获取 PikPak 状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/http-download/pikpak/test-account")
async def http_download_pikpak_test_account(request: PikPakAccountTestRequest):
    from ..core.http_download_service import get_http_download_service

    try:
        account = dict(request.account or {})
        if request.use_saved:
            account["use_saved"] = True
        return await get_http_download_service().test_pikpak_account(account, account_id=request.account_id)
    except Exception as exc:
        logger.warning("检测 PikPak 账号失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/http-download/pikpak/files")
async def http_download_pikpak_files(limit: int = 100, root: bool = False, account_id: str = "", parent_id: str = ""):
    from ..core.http_download_service import get_http_download_service

    try:
        return await get_http_download_service().pikpak_transfer_files(limit=limit, root=root, account_id=account_id, parent_id=parent_id)
    except Exception as exc:
        logger.warning("获取 PikPak 转存目录失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/http-download/pikpak/delete")
async def http_download_pikpak_delete(request: PikPakTransferDeleteRequest):
    from ..core.http_download_service import get_http_download_service

    try:
        return await get_http_download_service().delete_pikpak_transfer_items(request.ids, permanent=request.permanent, account_id=request.account_id)
    except Exception as exc:
        logger.warning("删除 PikPak 转存文件失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/http-download/pikpak/clear")
async def http_download_pikpak_clear():
    from ..core.http_download_service import get_http_download_service

    try:
        return await get_http_download_service().clear_all_pikpak_transfer_space()
    except Exception as exc:
        logger.warning("清空 PikPak 转存空间失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/http-download/task/{task_id}/pause")
async def http_download_pause_task(task_id: str):
    from ..core.http_download_service import get_http_download_service
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.HTTP_DOWNLOAD:
        raise HTTPException(status_code=404, detail="HTTP 下载任务不存在")
    task.pause()
    await get_http_download_service().pause_task(task_id)
    return {"success": True, "message": "任务已暂停"}


@app.post("/api/http-download/task/{task_id}/resume")
async def http_download_resume_task(task_id: str):
    from ..core.http_download_service import get_http_download_service
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.HTTP_DOWNLOAD:
        raise HTTPException(status_code=404, detail="HTTP 下载任务不存在")
    engine.resume_task(task_id)
    await get_http_download_service().resume_task(task_id)
    return {"success": True, "message": "任务已恢复"}


@app.post("/api/http-download/task/{task_id}/cancel")
async def http_download_cancel_task(task_id: str):
    from ..core.http_download_service import get_http_download_service
    from ..core.task_engine import TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.HTTP_DOWNLOAD:
        raise HTTPException(status_code=404, detail="HTTP 下载任务不存在")
    engine.cancel_task(task_id)
    await get_http_download_service().cancel_task(task_id)
    return {"success": True, "message": "任务已取消"}


@app.post("/api/http-download/task/{task_id}/retry")
async def http_download_retry_task(task_id: str):
    from ..core.http_download_service import get_http_download_service
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.HTTP_DOWNLOAD:
        raise HTTPException(status_code=404, detail="HTTP 下载任务不存在")
    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
        raise HTTPException(status_code=400, detail="任务仍在执行中，不能重试")
    await get_http_download_service().reset_task_for_retry(task)
    await engine.queue.put(task)
    return {"success": True, "message": "任务已加入重试队列"}


@app.post("/api/http-download/task/{task_id}/retry-file")
async def http_download_retry_task_file(task_id: str, request: HttpDownloadRetryFileRequest):
    from ..core.http_download_service import get_http_download_service, sanitize_http_download_item
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type != TaskType.HTTP_DOWNLOAD:
        raise HTTPException(status_code=404, detail="HTTP 下载任务不存在")
    if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}:
        raise HTTPException(status_code=400, detail="任务仍在执行中，不能重试")

    file_row = request.file if isinstance(request.file, dict) else {}
    if not file_row:
        raise HTTPException(status_code=400, detail="缺少要重试的文件")

    service = get_http_download_service()
    retry_items, retry_keys = service.build_retry_selection_for_file(task, file_row)
    if not retry_items:
        raise HTTPException(status_code=400, detail="无法识别要重试的文件")

    task.task_metadata["retry_file"] = sanitize_http_download_item(file_row)
    await service.reset_task_for_retry(task, retry_items=retry_items, retry_keys=retry_keys)
    await engine.queue.put(task)
    return {"success": True, "message": "该文件已加入重试队列"}

@app.post("/api/asmr-sync/scan")
async def asmr_sync_scan(request: ASMRSyncScanRequest):
    """扫描指定文件夹，返回发现的 RJ 号和字幕文件列表"""
    from ..core.subtitle_sync_service import get_subtitle_sync_service

    try:
        folder_path = request.folder_path

        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")

        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        subtitle_service = get_subtitle_sync_service()
        results = subtitle_service.scan_subtitle_folders(folder_path)

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(results),
            "items": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描字幕文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/asmr-sync/preview")
async def asmr_sync_preview(request: Request):
    """预览下载任务（获取文件列表、预估下载量、搜索最佳版本）"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        data = await request.json()
        rjcode = data.get("rjcode")

        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        asmr_service = get_asmr_download_service()

        # 获取所有关联版本
        linked_works = await asmr_service.get_linked_works_from_dlsite(rjcode)
        available_versions = []

        for work in linked_works:
            work_info = await asmr_service.fetch_work_info(work.workno)
            tracks = await asmr_service.fetch_track_list(work.workno) if work_info else None

            available_versions.append({
                "rjcode": work.workno,
                "lang": work.lang,
                "priority": work.priority,
                "available": work_info is not None and tracks is not None and len(tracks) > 0,
                "title": work_info.get('title', '') if work_info else '',
                "file_count": len(tracks) if tracks else 0
            })

            # 添加延迟避免请求过快
            await asyncio.sleep(0.3)

        # 找到最佳可用版本
        actual_rjcode, work_info = await asmr_service.find_best_available_work(rjcode)

        if not work_info:
            return {
                "success": False,
                "rjcode": rjcode,
                "error": "在 asmr.one 上未找到该作品的任何版本",
                "tried_versions": [
                    {"rjcode": v["rjcode"], "lang": v["lang"]}
                    for v in available_versions
                ]
            }

        # 获取文件列表
        tracks = await asmr_service.fetch_track_list(actual_rjcode)
        if tracks is None:
            return {
                "success": False,
                "rjcode": rjcode,
                "actual_rjcode": actual_rjcode,
                "error": "无法获取文件列表"
            }

        # 扁平化文件列表
        all_files = asmr_service._flatten_tracks(tracks)

        # 应用筛选规则
        config = get_config()
        filter_rules = config.filter.rules
        filtered_files = asmr_service.filter_files(all_files, filter_rules) if filter_rules else all_files

        # 计算总大小
        total_size = sum(f.get('size', 0) for f in filtered_files)

        # 获取实际版本的语言
        actual_version = next((v for v in available_versions if v["rjcode"] == actual_rjcode), {})

        return {
            "success": True,
            "rjcode": rjcode,
            "actual_rjcode": actual_rjcode,
            "title": work_info.get('title', '未知标题'),
            "lang": actual_version.get("lang", "JPN"),
            "total_files": len(all_files),
            "filtered_files": len(filtered_files),
            "total_size": total_size,
            "available_versions": available_versions,
            "files": [
                {
                    "title": f.get('title'),
                    "size": f.get('size', 0),
                    "type": f.get('type')
                }
                for f in filtered_files[:50]  # 只返回前50个用于预览
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("预览下载任务失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"预览失败: {str(e)}")


@app.post("/api/asmr-sync/start")
async def asmr_sync_start(request: ASMRSyncStartRequest):
    """开始同步下载任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine

    try:
        items = request.items
        auto_classify = request.auto_classify

        if not items:
            raise HTTPException(status_code=400, detail="没有要下载的作品")

        engine = get_task_engine()
        created_tasks = []

        for item in items:
            rjcode = item.get("rjcode")
            subtitle_folder = item.get("subtitle_folder")
            work_title = item.get("work_title", "")

            if not rjcode or not subtitle_folder:
                continue

            # 创建任务
            task = Task(
                task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                source_path=subtitle_folder,
                auto_classify=auto_classify,
                metadata={
                    "rjcode": rjcode,
                    "subtitle_folder": subtitle_folder,
                    "work_title": work_title,
                    "download_mode": "legacy",
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "work_title": work_title
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个下载任务",
            "tasks": created_tasks
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("开始同步下载失败: %s", sanitize_text_for_log(e))
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/asmr-sync/enhanced/plan")
async def asmr_sync_enhanced_plan(request: ASMRSyncEnhancedPlanRequest):
    """为输入的 RJ 号构建增强下载计划。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    if not request.rjcodes:
        raise HTTPException(status_code=400, detail="至少需要一个 RJ 号")

    service = get_asmr_resource_service()
    plans = []
    errors = []
    filters = {
        "resource_types": request.resource_types,
        "audio_formats": request.audio_formats,
        "subtitle_languages": request.subtitle_languages,
        "include_existing": request.include_existing,
    }

    for raw_rjcode in request.rjcodes:
        normalized_rjcode = service.normalize_rjcode(raw_rjcode)
        if not normalized_rjcode:
            continue
        try:
            plan = await service.build_download_plan(
                rjcode=normalized_rjcode,
                folder_path=str(request.folder_path or "").strip(),
                filters=filters,
                refresh=bool(request.refresh),
            )
            plans.append(plan)
        except Exception as exc:
            logger.warning("构建增强下载计划失败: %s (%s)", normalized_rjcode, exc)
            errors.append({
                "rjcode": normalized_rjcode,
                "error": str(exc),
            })

    return {
        "success": len(plans) > 0,
        "plans": plans,
        "errors": errors,
        "requested_count": len(request.rjcodes),
        "planned_count": len(plans),
    }


@app.post("/api/asmr-sync/enhanced/start")
async def asmr_sync_enhanced_start(request: ASMRSyncEnhancedStartRequest):
    """启动增强下载任务，支持按文件清单下载。"""
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    config = get_config()

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可启动的增强下载任务")

    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    service = get_asmr_resource_service()
    created_tasks = []
    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode:
            continue
        if not session_id:
            raise HTTPException(status_code=400, detail=f"{rjcode} 缺少 session_id")
        if not selected_resources:
            raise HTTPException(status_code=400, detail=f"{rjcode} 没有选中任何资源")

        raw_postprocess_options = dict(item.get("postprocess_options") or {})
        raw_download_base_path = str(item.get("download_base_path") or "").strip()
        task_metadata = {
            "rjcode": rjcode,
            "work_title": str(item.get("work_title") or ""),
            "cover_url": str(item.get("cover_url") or item.get("image_url") or item.get("mainCoverUrl") or ""),
            "folder_path": str(item.get("folder_path") or ""),
            "download_mode": "enhanced",
            "session_id": session_id,
            "selected_resources": selected_resources,
            "selected_resource_count": len(selected_resources),
            "upload_options": dict(item.get("upload_options") or {}),
            "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
            "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
            "priority": int(item.get("queue_priority") or item.get("priority") or 100),
            "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
            "verify_summary": {},
            "upload_summary": {},
            "retry_summary": {},
            "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
            "source_page": "asmr-sync",
            "source_action": "enhanced_download",
            "source_label": str(item.get("work_title") or rjcode),
        }
        if raw_postprocess_options:
            task_metadata["postprocess_options"] = raw_postprocess_options
        if raw_download_base_path:
            task_metadata["download_base_path"] = raw_download_base_path
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=bool(request.auto_classify),
            metadata=task_metadata,
        )
        await engine.submit(task)
        service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })

    return {
        "success": len(created_tasks) > 0,
        "message": f"已创建 {len(created_tasks)} 个增强下载任务",
        "tasks": created_tasks,
    }


_LOCATE_RJ_CONCURRENCY = 4
_locate_rj_semaphore: Optional[asyncio.Semaphore] = None


def _get_locate_rj_semaphore() -> asyncio.Semaphore:
    global _locate_rj_semaphore
    if _locate_rj_semaphore is None:
        _locate_rj_semaphore = asyncio.Semaphore(_LOCATE_RJ_CONCURRENCY)
    return _locate_rj_semaphore


@app.post("/api/asmr-sync/enhanced/locate-rj")
async def asmr_sync_enhanced_locate_rj(request: ASMRSyncLocateRJRequest):
    """跨库存按 RJ 号定位作品文件夹（用于"直放已有路径"模式）。

    多个 RJ 用 asyncio.gather 并发，但加全局信号量限流，避免对群晖 / NAS
    打出过多并发请求；本地搜索靠 LibraryManager 内部的结果 TTL 缓存复用。
    """
    from ..core.library_manager import get_library_manager

    manager = get_library_manager()
    rjcodes_norm: list[str] = []
    seen: set[str] = set()
    for raw in request.rjcodes or []:
        normalized = str(raw or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rjcodes_norm.append(normalized)
    if not rjcodes_norm:
        return {"success": True, "results": []}

    library_ids = list(request.library_ids) if request.library_ids else None
    semaphore = _get_locate_rj_semaphore()

    async def _locate_one(rj: str) -> dict[str, Any]:
        async with semaphore:
            try:
                matches = await manager.find_rj_in_libraries(rj, library_ids=library_ids)
            except Exception as exc:
                logger.warning("locate-rj 失败: rj=%s err=%s", rj, sanitize_text_for_log(exc))
                matches = []
            return {"rjcode": rj, "matches": matches}

    results = await asyncio.gather(*[_locate_one(rj) for rj in rjcodes_norm])
    return {"success": True, "results": list(results)}


@app.get("/api/asmr-sync/enhanced/dashboard")
async def asmr_sync_enhanced_dashboard():
    """增强下载监控看板摘要。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "dashboard": get_asmr_resource_service().get_dashboard_summary(),
        }
    except Exception as exc:
        logger.error("获取增强下载看板失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取监控看板失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions")
async def asmr_sync_enhanced_sessions(limit: int = 50):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "sessions": get_asmr_resource_service().list_sessions(limit=limit),
        }
    except Exception as exc:
        logger.error("获取增强下载会话列表失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions/{session_id}")
async def asmr_sync_enhanced_session_detail(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": get_asmr_resource_service().get_session_detail(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("获取增强下载会话详情失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/priority")
async def asmr_sync_enhanced_session_priority(session_id: str, request: ASMRSyncEnhancedPriorityRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().update_session_priority(session_id, request.queue_priority),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("调整增强下载会话优先级失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"调整优先级失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/pause")
async def asmr_sync_enhanced_session_pause(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "pause"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("暂停增强下载会话失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"暂停会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/resume")
async def asmr_sync_enhanced_session_resume(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "resume"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("恢复增强下载会话失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"恢复会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/cancel", summary="取消增强下载会话")
async def asmr_sync_enhanced_session_cancel(session_id: str, request: Request):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        cleanup = bool(body.get("cleanup", True))
        service = get_asmr_resource_service()
        if cleanup:
            session = await service.cancel_session_with_cleanup(session_id)
        else:
            session = await service.control_session(session_id, "cancel")
        return {"success": True, "session": session}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("取消增强下载会话失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"取消会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-failed")
async def asmr_sync_enhanced_session_retry_failed(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话失败资源失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"重试失败资源失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-files")
async def asmr_sync_enhanced_session_retry_files(session_id: str, request: ASMRRetryFailedResourcesRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session_resources(session_id, request.relative_paths),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话指定失败文件失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"重试指定失败文件失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/reimport-downloaded")
async def asmr_sync_enhanced_session_reimport_downloaded(session_id: str, request: ASMRReimportDownloadedRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().reimport_downloaded_session(
                session_id,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("从本地已下载内容重新入库失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"重新入库失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/reimport-local-download")
async def asmr_sync_enhanced_reimport_local_download(request: ASMRReimportLocalDownloadRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "result": await get_asmr_resource_service().reimport_local_download_root(
                download_root=request.download_root,
                rjcode=request.rjcode,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
                circle_name=request.circle_name,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("从本地下载目录直接入库失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"从本地下载目录直接入库失败: {str(exc)}")


@app.post("/api/circle-completion/index")
async def circle_completion_index(
    payload: CircleCompletionIndexRequest,
    http_request: Request,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_query": payload.circle_query,
            "force_refresh": bool(payload.force_refresh),
            "include_dlsite": bool(payload.include_dlsite),
            "include_kikoeru": bool(payload.include_kikoeru),
            "only_new_works": bool(payload.only_new_works),
            "deprecated_sync_api": True,
        }
        logger.warning(
            "[社团补全] 同步索引接口已弃用，建议使用 /api/circle-completion/index/start: circle_query=%s",
            payload.circle_query,
        )
        result = await get_circle_completion_service().index_circle_catalog(
            payload.circle_query,
            force_refresh=bool(payload.force_refresh),
            include_dlsite=bool(payload.include_dlsite),
            include_kikoeru=bool(payload.include_kikoeru),
            only_new_works=bool(payload.only_new_works),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("社团索引失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"建立社团索引失败: {str(exc)}")


@app.post("/api/circle-completion/index/start")
async def circle_completion_index_start(request: CircleCompletionIndexJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_queries = []
        for value in list(request.circle_queries or []):
            query = str(value or "").strip()
            if query and query not in circle_queries:
                circle_queries.append(query)
        single_circle_query = str(request.circle_query or "").strip()
        if single_circle_query and single_circle_query not in circle_queries:
            circle_queries.append(single_circle_query)
        if not circle_queries:
            raise ValueError("社团名不能为空")
        circle_query = circle_queries[0]
        is_batch = len(circle_queries) > 1
        is_refresh_all = bool(request.is_refresh_all) and is_batch
        if is_refresh_all:
            source_label = f"全部刷新 {len(circle_queries)} 个社团"
            source_action_kind = "refresh_all_circles"
        elif is_batch:
            source_label = f"批量补全 {len(circle_queries)} 个社团"
            source_action_kind = "index_start"
        else:
            source_label = circle_query
            source_action_kind = "index_start"
        business_key = circle_query if not is_batch else f"batch:{'|'.join(circle_queries[:20])}"

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_INDEX,
            source_path=source_label,
            auto_classify=False,
            metadata={
                "circle_query": circle_query,
                "circle_queries": circle_queries,
                "circle_name": circle_query,
                "force_refresh": bool(request.force_refresh),
                "include_dlsite": bool(request.include_dlsite),
                "include_kikoeru": bool(request.include_kikoeru),
                "only_new_works": bool(request.only_new_works),
                "is_batch": is_batch,
                "batch_total": len(circle_queries),
                "is_refresh_all": is_refresh_all,
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": source_action_kind,
                "source_label": source_label,
                "business_key": business_key,
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": source_action_kind,
            "source_label": source_label,
            "business_key": business_key,
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": circle_query,
            "circle_id": "",
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {
                "only_new_works": bool(request.only_new_works),
                "is_batch": is_batch,
                "batch_total": len(circle_queries),
                "completed_queries": 0,
                "failed_queries": 0,
                "current_circle_query": circle_query,
            },
            "result": {},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动社团索引任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"启动社团索引任务失败: {str(exc)}")


@app.get("/api/circle-completion/index/jobs/{job_id}")
async def circle_completion_index_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("索引任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": str(metadata.get("current_circle_query") or metadata.get("circle_query") or task.source_path or "").strip(),
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": {
                **dict(metadata.get("index_meta") or {}),
                "only_new_works": bool(metadata.get("only_new_works")),
                "is_batch": bool(metadata.get("is_batch")),
                "is_refresh_all": bool(metadata.get("is_refresh_all")),
                "batch_total": int(metadata.get("batch_total") or 0),
            },
            "result": {
                **dict(metadata.get("index_result") or {}),
                "batch_results": list(metadata.get("index_batch_results") or []),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团索引任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团索引任务失败: {str(exc)}")


@app.post("/api/circle-completion/bonus-probe/start")
async def circle_completion_bonus_probe_start(request: CircleCompletionBonusProbeStartRequest):
    from ..core.dlsite_bonus_probe_service import get_dlsite_bonus_probe_service
    from ..core.task_engine import Task, TaskStatus, TaskType, get_task_engine

    try:
        circle_id = str(request.circle_id or "").strip()
        if not circle_id:
            raise ValueError("缺少社团 ID")
        service = get_dlsite_bonus_probe_service()
        context = service.resolve_circle_context(circle_id, request.maker_id)
        maker_id = str(context.get("maker_id") or "").strip().upper()
        if not maker_id:
            raise ValueError("未找到该社团的 DLsite maker_id，请先建立社团索引")
        mode = str(request.mode or "normal").strip() or "normal"
        release_dates = [service.normalize_date(value) for value in list(request.release_dates or [])]
        release_dates = [value for value in release_dates if value]
        selected_rjcodes_by_date: Dict[str, List[str]] = {}
        for raw_date, raw_codes in dict(request.selected_rjcodes_by_date or {}).items():
            normalized_date = service.normalize_date(raw_date)
            if not normalized_date:
                continue
            normalized_codes = []
            for raw_code in raw_codes or []:
                normalized_code = service.normalize_rjcode(raw_code)
                if normalized_code and normalized_code not in normalized_codes:
                    normalized_codes.append(normalized_code)
            if normalized_codes:
                selected_rjcodes_by_date[normalized_date] = normalized_codes
        if not release_dates:
            release_dates = service.list_indexed_release_dates(circle_id, maker_id, mode=mode)
        if not release_dates:
            raise ValueError("没有可探测的已索引发售日")

        gap_limit = max(1, int(request.gap_limit or 500))
        batch_size = int(request.batch_size) if request.batch_size is not None else None
        concurrency = int(request.concurrency) if request.concurrency is not None else None
        runtime_limits = service.resolve_probe_runtime_limits(
            mode=mode,
            batch_size=batch_size,
            concurrency=concurrency,
        )
        batch_size = int(runtime_limits["batch_size"])
        concurrency = int(runtime_limits["concurrency"])
        requested_release_dates = list(release_dates)
        if selected_rjcodes_by_date:
            release_dates = requested_release_dates
            skipped_completed_release_dates = []
        else:
            release_dates, skipped_completed_release_dates = service.split_reusable_release_dates(
                circle_id=circle_id,
                maker_id=maker_id,
                release_dates=requested_release_dates,
                mode=mode,
                gap_limit=gap_limit,
            )
        selected_rjcodes_by_date = {
            date: selected_rjcodes_by_date.get(date, [])
            for date in release_dates
            if selected_rjcodes_by_date.get(date)
        }
        if not release_dates:
            return {
                "success": True,
                "job_id": "",
                "status": "completed",
                "progress": 100,
                "current_step": "这些发售日已完成特典探测，无需重复查找",
                "circle_id": circle_id,
                "circle_name": context.get("circle_name") or "",
                "maker_id": maker_id,
                "release_dates": [],
                "requested_release_dates": requested_release_dates,
                "skipped_completed_release_dates": skipped_completed_release_dates,
                "already_completed": True,
                "duplicate": False,
                "result": {
                    "date_count": 0,
                    "skipped_count": len(skipped_completed_release_dates),
                    "skipped_completed_release_dates": skipped_completed_release_dates,
                    "probe_count": 0,
                    "request_count": 0,
                    "hit_count": 0,
                    "inserted_count": 0,
                },
            }
        business_key = _circle_bonus_probe_business_key(
            maker_id=maker_id,
            mode=mode,
            release_dates=release_dates,
            gap_limit=gap_limit,
            selected_rjcodes_by_date=selected_rjcodes_by_date,
        )
        engine = get_task_engine()
        active_statuses = {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}
        for current_task in engine.get_all_tasks(include_hidden=True):
            if current_task.type != TaskType.CIRCLE_COMPLETION_BONUS_PROBE:
                continue
            metadata = dict(current_task.task_metadata or {})
            if str(metadata.get("business_key") or "").strip() != business_key:
                continue
            if current_task.status in active_statuses:
                return {
                    "success": True,
                    "job_id": current_task.id,
                    "status": current_task.status.value if isinstance(current_task.status, TaskStatus) else str(current_task.status),
                    "progress": int(current_task.progress or 0),
                    "current_step": current_task.current_step,
                    "circle_id": circle_id,
                    "maker_id": maker_id,
                    "release_dates": release_dates,
                    "requested_release_dates": requested_release_dates,
                    "skipped_completed_release_dates": skipped_completed_release_dates,
                    "selected_rjcodes_by_date": selected_rjcodes_by_date,
                    "duplicate": True,
                    "runtime_limits": runtime_limits,
                    "result": dict(metadata.get("bonus_probe_result") or {}),
                }

        source_label = f"{context.get('circle_name') or circle_id} 特典补全"
        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_BONUS_PROBE,
            source_path=circle_id,
            auto_classify=False,
            metadata={
                "circle_id": circle_id,
                "circle_name": context.get("circle_name") or "",
                "maker_id": maker_id,
                "release_dates": release_dates,
                "requested_release_dates": requested_release_dates,
                "skipped_completed_release_dates": skipped_completed_release_dates,
                "selected_rjcodes_by_date": selected_rjcodes_by_date,
                "mode": mode,
                "gap_limit": gap_limit,
                "batch_size": batch_size,
                "concurrency": concurrency,
                "bonus_probe_runtime_limits": runtime_limits,
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "bonus_probe",
                "source_label": source_label,
                "business_key": business_key,
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": "bonus_probe",
            "source_label": source_label,
            "business_key": business_key,
        })
        await engine.submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": circle_id,
            "maker_id": maker_id,
            "release_dates": release_dates,
            "requested_release_dates": requested_release_dates,
            "skipped_completed_release_dates": skipped_completed_release_dates,
            "selected_rjcodes_by_date": selected_rjcodes_by_date,
            "duplicate": False,
            "runtime_limits": runtime_limits,
            "result": {},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动 DLsite 特典探测任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"启动 DLsite 特典探测任务失败: {str(exc)}")


@app.get("/api/circle-completion/bonus-probe/jobs/{job_id}")
async def circle_completion_bonus_probe_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("特典探测任务不存在")
        metadata = _task_metadata_with_redis_runtime(task)
        status_value, progress, current_step = _task_runtime_response_values(task)
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            elapsed_seconds = max(0.0, ((finished_at or datetime.now()) - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": status_value,
            "progress": progress,
            "current_step": current_step,
            "circle_id": str(metadata.get("circle_id") or task.source_path or "").strip(),
            "circle_name": str(metadata.get("circle_name") or "").strip(),
            "maker_id": str(metadata.get("maker_id") or "").strip(),
            "release_dates": list(metadata.get("release_dates") or []),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": dict(metadata.get("bonus_probe_meta") or {}),
            "summary": dict(metadata.get("bonus_probe_summary") or {}),
            "result": dict(metadata.get("bonus_probe_result") or {}),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询 DLsite 特典探测任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询 DLsite 特典探测任务失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}/bonus-probe-status")
async def circle_completion_bonus_probe_status(circle_id: str, limit: int = 20):
    from ..core.dlsite_bonus_probe_service import get_dlsite_bonus_probe_service

    try:
        return {"success": True, **get_dlsite_bonus_probe_service().get_circle_status(circle_id, limit=limit)}
    except Exception as exc:
        logger.error("查询 DLsite 特典探测状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询 DLsite 特典探测状态失败: {str(exc)}")


@app.get("/api/circle-completion/circles")
async def circle_completion_circles(keyword: str = "", limit: int = 30):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().search_circles(keyword, limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询社团索引失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/recent")
async def circle_completion_recent(limit: int = 20):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().list_recent_indexes(limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询最近社团索引失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询最近社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/work-search")
async def circle_completion_work_search(
    http_request: Request,
    keyword: str = "",
    limit: int = 20,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "keyword": bool(str(keyword or "").strip()),
            "limit": limit,
            "view": "work_search",
        }
        works = await get_circle_completion_service().search_circle_completion_works(keyword, limit=limit)
        return {"success": True, "items": works, "total": len(works)}
    except Exception as exc:
        logger.error("搜索社团补全作品失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"搜索社团补全作品失败: {str(exc)}")


@app.get("/api/circle-completion/circles/names")
async def circle_completion_all_circle_names():
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().search_circles("", limit=9999)
        names = [c["circle_name"] for c in circles if c.get("circle_name")]
        return {"success": True, "names": names, "total": len(names)}
    except Exception as exc:
        logger.error("获取所有社团名失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取所有社团名失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}/summary")
async def circle_completion_summary(
    http_request: Request,
    circle_id: str,
    include_dl_only: bool = True,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "include_dl_only": bool(include_dl_only),
            "view": "summary",
        }
        result = await get_circle_completion_service().build_circle_completion_summary(
            circle_id,
            include_dl_only=bool(include_dl_only),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全摘要失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团补全摘要失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}/works")
async def circle_completion_works(
    http_request: Request,
    circle_id: str,
    tab: str = "missing",
    page: int = 1,
    page_size: int = 10,
    include_dl_only: bool = True,
    status_filters: str = "",
    owned_filter: str = "all",
    compare_filter: str = "all",
    search: str = "",
    sort: str = "updated_desc",
    view_mode: str = "list",
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "tab": tab,
            "page": page,
            "page_size": page_size,
            "include_dl_only": bool(include_dl_only),
            "status_filters": status_filters,
            "owned_filter": owned_filter,
            "compare_filter": compare_filter,
            "search": bool(str(search or "").strip()),
            "sort": sort,
            "view_mode": view_mode,
            "view": "works",
        }
        result = await get_circle_completion_service().list_circle_completion_works(
            circle_id,
            tab=tab,
            page=page,
            page_size=page_size,
            include_dl_only=bool(include_dl_only),
            status_filters=status_filters,
            owned_filter=owned_filter,
            compare_filter=compare_filter,
            search=search,
            sort=sort,
            view_mode=view_mode,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全作品分页失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团补全作品分页失败: {str(exc)}")


@app.post("/api/circle-completion/external-search")
async def circle_completion_external_search(payload: CircleCompletionExternalSearchRequest):
    """异步探测 AnimeShare / 南+，仅返回外部跳转标签。"""
    circle_id = str(payload.circle_id or "").strip()
    canonical_codes = list(dict.fromkeys(
        str(code or "").strip().upper()
        for code in payload.canonical_rjcodes or []
        if str(code or "").strip()
    ))
    if not circle_id:
        raise HTTPException(status_code=400, detail="缺少社团标识")
    if not canonical_codes:
        return {"success": True, "items": {}}
    if len(canonical_codes) > 100:
        raise HTTPException(status_code=400, detail="单次外部搜索最多 100 个作品")
    try:
        from ..core.circle_completion_service import get_circle_completion_service
        from ..core.circle_external_search_service import get_circle_external_search_service

        variants = await asyncio.to_thread(
            get_circle_completion_service().get_external_search_variants,
            circle_id,
            canonical_codes,
        )
        result = await get_circle_external_search_service().search_variants(variants)
        return {"success": True, **result}
    except Exception as exc:
        logger.warning("[社团补全·外部搜索] 批量查询失败 circle=%s: %s", circle_id, sanitize_text_for_log(exc))
        raise HTTPException(status_code=502, detail="外部搜索暂时不可用")


@app.post("/api/circle-completion/external-search/test")
async def circle_completion_external_search_test(payload: CircleCompletionExternalSearchTestRequest):
    """测试南+搜索连接，不触发作品扫描或缓存写入。"""
    from ..core.circle_external_search_service import get_circle_external_search_service

    config = get_config().circle_external_search
    cookie = str(payload.south_plus_cookie or "").strip()
    if not cookie or cookie == "********":
        cookie = str(getattr(config, "south_plus_cookie", "") or "").strip()
    proxy = str(payload.south_plus_proxy if payload.south_plus_proxy is not None else getattr(config, "south_plus_proxy", "") or "").strip()
    return await get_circle_external_search_service().test_south_plus_connection(cookie, proxy)


@app.get("/api/circle-completion/circles/{circle_id}/work-codes")
async def circle_completion_work_codes(
    http_request: Request,
    circle_id: str,
    tab: str = "missing",
    include_dl_only: bool = True,
    status_filters: str = "",
    owned_filter: str = "all",
    compare_filter: str = "all",
    search: str = "",
    sort: str = "updated_desc",
    selection_only: bool = False,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "tab": tab,
            "include_dl_only": bool(include_dl_only),
            "status_filters": status_filters,
            "owned_filter": owned_filter,
            "compare_filter": compare_filter,
            "search": bool(str(search or "").strip()),
            "sort": sort,
            "selection_only": bool(selection_only),
            "view": "work_codes",
        }
        result = await get_circle_completion_service().list_circle_completion_work_codes(
            circle_id,
            tab=tab,
            include_dl_only=bool(include_dl_only),
            status_filters=status_filters,
            owned_filter=owned_filter,
            compare_filter=compare_filter,
            search=search,
            sort=sort,
            selection_only=bool(selection_only),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全作品编号失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团补全作品编号失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}/bonus-work-codes")
async def circle_completion_bonus_work_codes(
    http_request: Request,
    circle_id: str,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "view": "bonus_work_codes",
        }
        result = await get_circle_completion_service().list_circle_completion_bonus_work_codes(circle_id)
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团特典作品编号失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团特典作品编号失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}/work-location")
async def circle_completion_work_location(
    http_request: Request,
    circle_id: str,
    rjcode: str,
    tab: str = "missing",
    page_size: int = 10,
    include_dl_only: bool = True,
    status_filters: str = "",
    owned_filter: str = "all",
    compare_filter: str = "all",
    search: str = "",
    sort: str = "updated_desc",
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "tab": tab,
            "page_size": page_size,
            "include_dl_only": bool(include_dl_only),
            "status_filters": status_filters,
            "owned_filter": owned_filter,
            "compare_filter": compare_filter,
            "search": bool(str(search or "").strip()),
            "sort": sort,
            "view": "work_location",
        }
        result = await get_circle_completion_service().locate_circle_completion_work(
            circle_id,
            rjcode=rjcode,
            tab=tab,
            page_size=page_size,
            include_dl_only=bool(include_dl_only),
            status_filters=status_filters,
            owned_filter=owned_filter,
            compare_filter=compare_filter,
            search=search,
            sort=sort,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("定位社团补全作品失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"定位社团补全作品失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}")
async def circle_completion_detail(
    http_request: Request,
    circle_id: str,
    only_missing: bool = False,
    only_downloadable: bool = False,
    include_dl_only: bool = True,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": circle_id,
            "only_missing": bool(only_missing),
            "only_downloadable": bool(only_downloadable),
            "include_dl_only": bool(include_dl_only),
        }
        result = await get_circle_completion_service().build_circle_completion_view(
            circle_id,
            only_missing=bool(only_missing),
            only_downloadable=bool(only_downloadable),
            include_dl_only=bool(include_dl_only),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全详情失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询社团补全详情失败: {str(exc)}")


@app.get("/api/circle-completion/cover/{filename}")
async def circle_completion_cover(filename: str):
    """返回社团补全本地缓存的封面图（``data/img/RJxxxxxx.jpg``）。

    - 文件名通过 ``CircleImageCacheService.resolve_filename`` 做严格白名单
      校验（只允许 ``RJ\\d{6,8}.jpg``），杜绝 ``../`` 路径穿越。
    - 文件不存在时由服务端按 RJ 下载一次并原子落盘；成功后当前请求直接返回
      本地文件，浏览器不再额外直连 DLsite CDN。
    - 30 天 ``public`` 缓存：索引刷新会原子重写同名文件，浏览器拿旧缓存的
      代价仅是封面没及时换，可接受。
    """
    from ..core.circle_image_cache_service import get_circle_image_cache_service

    image_cache_service = get_circle_image_cache_service()
    rjcode, variant = image_cache_service._parse_filename(filename)
    cache_path = image_cache_service.resolve_filename(filename)
    if cache_path is not None and not image_cache_service.has_local(rjcode, variant):
        cache_path = await image_cache_service.ensure_local_for_filename(filename)
    if cache_path is None or not image_cache_service.has_local(rjcode, variant):
        raise HTTPException(status_code=404, detail="封面未缓存")
    return FileResponse(
        str(cache_path),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=2592000, immutable",
        },
    )


@app.post("/api/circle-completion/cover/fetch")
async def circle_completion_fetch_cover(payload: CircleCompletionCoverFetchRequest):
    """按 RJ 立即补齐社团补全封面缓存。"""

    from ..core.circle_image_cache_service import get_circle_image_cache_service

    service = get_circle_image_cache_service()
    rjcode = service.normalize_rjcode(payload.rjcode)
    variant = service._normalize_variant(payload.variant)
    if not rjcode:
        raise HTTPException(status_code=400, detail="RJ 编号无效")

    path = await service.fetch_local_for_rjcode(
        rjcode,
        variant=variant,
        force=bool(payload.force),
    )
    if path is None or not path.is_file():
        return {
            "success": False,
            "rjcode": rjcode,
            "variant": variant,
            "detail": "封面暂时无法下载",
        }
    return {
        "success": True,
        "rjcode": rjcode,
        "variant": variant,
        "filename": path.name,
        "cover_url": service.get_local_url(rjcode, variant),
    }


@app.post("/api/circle-completion/download/preview")
async def circle_completion_download_preview(
    payload: CircleCompletionDownloadPreviewRequest,
    http_request: Request,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": payload.circle_id,
            "selected_count": len(payload.canonical_rjcodes or []),
            "requested_rjcode_groups": len(payload.requested_rjcodes or {}),
        }
        result = await get_circle_completion_service().preview_batch_download(
            payload.circle_id,
            payload.canonical_rjcodes,
            payload.requested_rjcodes,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("预览社团批量下载失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"预览批量下载失败: {str(exc)}")


@app.post("/api/circle-completion/download/preview/start")
async def circle_completion_download_preview_start(
    payload: CircleCompletionDownloadPreviewRequest,
    http_request: Request,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": payload.circle_id,
            "selected_count": len(payload.canonical_rjcodes or []),
            "requested_rjcode_groups": len(payload.requested_rjcodes or {}),
            "job_api": True,
        }
        result = await get_circle_completion_service().start_download_preview_job(
            payload.circle_id,
            payload.canonical_rjcodes,
            payload.requested_rjcodes,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("启动社团批量下载预览任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"启动预览任务失败: {str(exc)}")


@app.get("/api/circle-completion/download/preview/jobs/{job_id}")
async def circle_completion_download_preview_job_status(job_id: str):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = get_circle_completion_service().get_download_preview_job(job_id)
        if result is None:
            raise ValueError("下载预览任务不存在")
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团批量下载预览任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询预览任务失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected")
async def circle_completion_refresh_selected(
    payload: CircleCompletionRefreshSelectedRequest,
    http_request: Request,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        http_request.state.slow_api_context = {
            "circle_id": payload.circle_id,
            "selected_count": len(payload.canonical_rjcodes or []),
            "force_refresh": bool(payload.force_refresh),
            "owned_only": bool(payload.owned_only),
            "deprecated_sync_api": True,
        }
        logger.warning(
            "[社团补全] 同步刷新接口已弃用，建议使用 /api/circle-completion/refresh-selected/start: circle_id=%s selected_count=%s",
            payload.circle_id,
            len(payload.canonical_rjcodes or []),
        )
        if payload.owned_only:
            force_refresh, force_refresh_reason = False, "owned_only"
            result = await get_circle_completion_service().refresh_circle_owned_state(
                payload.circle_id,
                payload.canonical_rjcodes,
            )
        else:
            force_refresh, force_refresh_reason = _resolve_circle_completion_force_refresh(
                payload.circle_id,
                bool(payload.force_refresh),
            )
            result = await get_circle_completion_service().refresh_circle_works(
                payload.circle_id,
                payload.canonical_rjcodes,
                force_refresh=force_refresh,
            )
        return {
            "success": True,
            **result,
            "meta": {
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
                "owned_only": bool(payload.owned_only),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("批量刷新社团作品状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"批量刷新社团作品状态失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected/start")
async def circle_completion_refresh_selected_start(request: CircleCompletionRefreshSelectedJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_id = str(request.circle_id or "").strip()
        circle_name = str(request.circle_name or "").strip()
        canonical_rjcodes = [str(code or "").strip() for code in list(request.canonical_rjcodes or []) if str(code or "").strip()]
        if not circle_id:
            raise ValueError("缺少社团标识")
        if not canonical_rjcodes:
            raise ValueError("没有选中要刷新的作品")
        owned_only = bool(request.owned_only)
        if owned_only:
            force_refresh, force_refresh_reason = False, "owned_only"
        else:
            force_refresh, force_refresh_reason = _resolve_circle_completion_force_refresh(
                circle_id,
                bool(request.force_refresh),
            )
        source_action = "refresh_owned" if owned_only else "refresh_selected"

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED,
            source_path=circle_name or circle_id,
            auto_classify=False,
            metadata={
                "circle_id": circle_id,
                "circle_name": circle_name,
                "canonical_rjcodes": canonical_rjcodes,
                "selected_count": len(canonical_rjcodes),
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
                "owned_only": owned_only,
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": source_action,
                "source_label": circle_name or circle_id,
                "business_key": f"{circle_id}:{source_action}",
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": source_action,
            "source_label": circle_name or circle_id,
            "business_key": f"{circle_id}:{source_action}",
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": circle_id,
            "circle_name": circle_name,
            "selected_count": len(canonical_rjcodes),
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
                "owned_only": owned_only,
            },
            "result": {},
            "progress_log": [],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动批量刷新社团作品任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"启动批量刷新社团作品任务失败: {str(exc)}")


@app.get("/api/circle-completion/refresh-selected/jobs/{job_id}")
async def circle_completion_refresh_selected_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("刷新任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "circle_name": str(metadata.get("circle_name") or task.source_path or "").strip(),
            "selected_count": int(metadata.get("selected_count") or 0),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": {
                **dict(metadata.get("refresh_meta") or {}),
                "force_refresh": bool(metadata.get("force_refresh")),
                "force_refresh_reason": str(metadata.get("force_refresh_reason") or ""),
                "owned_only": bool(metadata.get("owned_only")),
            },
            "result": dict(metadata.get("refresh_result") or {}),
            "progress_log": list(metadata.get("progress_log") or []),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询批量刷新社团作品任务失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"查询批量刷新社团作品任务失败: {str(exc)}")


@app.post("/api/circle-completion/download/start")
async def circle_completion_download_start(request: CircleCompletionDownloadStartRequest):
    from ..core.activity_log_service import log_circle_completion_event
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可创建的下载项")

    config = get_config()
    batch_id = str(uuid.uuid4())
    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    session_service = get_asmr_resource_service()
    created_tasks = []
    child_rows = []
    batch_options = dict(request.batch_options or {})
    download_base_path = str(batch_options.get("download_base_path") or "").strip()
    target_library_id = str(batch_options.get("target_library_id") or "").strip()
    target_subdir = str(batch_options.get("target_subdir") or "").strip()
    naming_mode = str(batch_options.get("naming_mode") or "api").strip().lower() or "api"
    classify_mode = str(batch_options.get("classify_mode") or "circle").strip().lower() or "circle"
    # flatten_files：直放指定目录开关。开启时所有文件直接落到 target_subdir 下，
    # 不再创建社团目录 / 作品目录层；前端已强制 naming/classify 退化但这里再兜底一次。
    flatten_files = bool(batch_options.get("flatten_files"))
    if flatten_files:
        naming_mode = "preserve"
        classify_mode = "none"

    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode or not session_id or not selected_resources:
            continue
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=False,
            metadata={
                "rjcode": rjcode,
                "work_title": str(item.get("work_title") or rjcode),
                "cover_url": str(item.get("cover_url") or item.get("image_url") or item.get("mainCoverUrl") or ""),
                "folder_path": str(item.get("folder_path") or ""),
                "download_mode": "enhanced",
                "session_id": session_id,
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
                "circle_name": request.circle_name,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "selected_resources": selected_resources,
                "selected_resource_count": len(selected_resources),
                "upload_options": dict(item.get("upload_options") or {}),
                "download_base_path": download_base_path,
                "postprocess_options": {
                    "enabled": True,
                    "target_library_id": target_library_id,
                    "target_subdir": target_subdir,
                    "naming_mode": naming_mode,
                    "classify_mode": classify_mode,
                    "flatten_files": flatten_files,
                    "circle_name": str((item.get("postprocess_options") or {}).get("circle_name") or request.circle_name or ""),
                },
                "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
                "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
                "priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "batch_download",
                "source_label": str(item.get("work_title") or rjcode),
                "business_key": str(item.get("canonical_rjcode") or rjcode),
            },
            rjcode=rjcode,
        )
        await engine.submit(task)
        session_service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
                "target_library_id": target_library_id,
                "target_subdir": target_subdir,
                "naming_mode": naming_mode,
                "classify_mode": classify_mode,
                "circle_name": str((item.get("postprocess_options") or {}).get("circle_name") or request.circle_name or ""),
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })
        child_rows.append({
            "id": task.id,
            "category": "circle_completion",
            "category_label": "社团补全",
            "action": "download_item_queued",
            "status": "success",
            "summary": f"{rjcode} 已加入下载队列，共 {len(selected_resources)} 个资源",
            "detail": {
                "session_id": session_id,
                "parent_session_id": batch_id,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "downloadable": True,
                "selected_resource_count": len(selected_resources),
                "download_base_path": download_base_path or None,
                "target_library_id": target_library_id or None,
                "target_subdir": target_subdir or None,
                "naming_mode": naming_mode,
                "classify_mode": classify_mode,
            },
            "task_id": task.id,
            "rjcode": rjcode,
            "created_at": datetime.now().isoformat(),
        })

    if not created_tasks:
        raise HTTPException(status_code=400, detail="没有有效下载项")

    log_circle_completion_event(
        "download_batch_start",
        summary=f"{request.circle_name or request.circle_id} 已创建 {len(created_tasks)} 个下载子任务",
        circle_id=request.circle_id,
        circle_name=request.circle_name or request.circle_id,
        batch_id=batch_id,
        detail={
            "items": created_tasks,
            "child_rows": child_rows,
            "download_base_path": download_base_path or None,
            "target_library_id": target_library_id or None,
            "target_subdir": target_subdir or None,
            "naming_mode": naming_mode,
            "classify_mode": classify_mode,
        },
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "circle_id": request.circle_id,
        "tasks": created_tasks,
        "message": f"已创建 {len(created_tasks)} 个社团补全下载任务",
    }

@app.post("/api/local-upload/start")
async def local_upload_start(request: LocalUploadStartRequest):
    from pathlib import PurePosixPath
    from ..core.library_manager import get_library_manager
    from ..core.task_engine import Task, TaskType, get_task_engine
    try:
        source_library_id = str(request.source_library_id or "").strip()
        source_base_path = str(request.source_base_path or "").strip()
        selected_paths = [str(p or "").strip() for p in (request.selected_paths or []) if str(p or "").strip()]
        target_library_id = str(request.target_library_id or "").strip()
        target_subdir = str(request.target_subdir or "").strip()
        circle_name = str(request.circle_name or "").strip()
        if not source_base_path:
            raise HTTPException(status_code=400, detail="缺少来源目录")
        if not selected_paths:
            raise HTTPException(status_code=400, detail="没有选中要上传的目录")
        if not target_library_id:
            raise HTTPException(status_code=400, detail="缺少目标库存")
        if source_library_id:
            manager = get_library_manager()
        else:
            manager = get_library_manager()
            source_base_real = os.path.abspath(source_base_path)
            if not os.path.isdir(source_base_real):
                raise HTTPException(status_code=400, detail="来源目录不存在")
            invalid_paths = [
                path for path in selected_paths
                if not os.path.isdir(path) or os.path.commonpath([source_base_real, os.path.abspath(path)]) != source_base_real
            ]
            if invalid_paths:
                raise HTTPException(status_code=400, detail="选中的来源目录无效或不在来源根目录内")

        target_library = manager.get_library_definition(target_library_id)
        target_root = PurePosixPath(str(target_library.root_path or "").replace("\\", "/"))
        normalized_target_subdir = target_subdir.replace("\\", "/").strip("/")
        target_root_text = str(target_root).replace("\\", "/").rstrip("/")
        target_root_name = PurePosixPath(target_root_text or "/").name
        if normalized_target_subdir in {target_root_name, target_root_text.lstrip("/")}:
            normalized_target_subdir = ""
        target_root_without_slash = target_root_text.lstrip("/")
        if normalized_target_subdir and target_root_without_slash and normalized_target_subdir.startswith(f"{target_root_without_slash}/"):
            normalized_target_subdir = normalized_target_subdir[len(target_root_without_slash):].strip("/")
        elif normalized_target_subdir and target_root_name and normalized_target_subdir.startswith(f"{target_root_name}/"):
            normalized_target_subdir = normalized_target_subdir[len(target_root_name):].strip("/")

        relative_target_parts = [part.strip("/\\") for part in (normalized_target_subdir, circle_name) if str(part or "").strip("/\\")]
        relative_target_dir = "/".join(relative_target_parts)
        preview_target_root = target_root / relative_target_dir if relative_target_dir else target_root
        selected_items = []
        for selected_path in selected_paths:
            selected_items.append({
                "source_path": selected_path,
                "relative_target_dir": relative_target_dir,
            })

        preview_target_path = str(preview_target_root)
        if len(selected_paths) == 1:
            preview_target_path = str(PurePosixPath(preview_target_path) / os.path.basename(os.path.abspath(selected_paths[0])))

        task_source_path = selected_paths[0] if len(selected_paths) == 1 else source_base_path
        task = Task(
            task_type=TaskType.LOCAL_LIBRARY_UPLOAD,
            source_path=task_source_path,
            metadata={
                "source_library_id": source_library_id,
                "source_base_path": source_base_path,
                "selected_paths": selected_paths,
                "selected_items": selected_items,
                "target_library_id": target_library_id,
                "target_subdir": normalized_target_subdir,
                "circle_name": circle_name,
                "target_path": preview_target_path.replace("\\", "/"),
                "selected_dir_count": len(selected_paths),
                "source_page": "circle_completion" if not source_library_id else "library",
                "source_action": "direct_reimport_upload" if not source_library_id else "upload_to_server",
                "source_label": circle_name or os.path.basename(source_base_path.rstrip("\\/")) or "上传到服务器",
            },
        )
        task.task_metadata["upload_files"] = []
        task.task_metadata["uploaded_files"] = []
        task.task_metadata["progress_log"] = []
        task.task_metadata["upload_runtime"] = {}
        task.ensure_business_context(
            "upload",
            defaults={
                "source_page": "library",
                "source_page": "circle_completion" if not source_library_id else "library",
                "source_action": "direct_reimport_upload" if not source_library_id else "upload_to_server",
                "source_label": circle_name or os.path.basename(source_base_path.rstrip("\\/")) or "上传到服务器",
                "business_key": f"{target_library_id}:{'|'.join(selected_paths)}",
            },
        )

        engine = get_task_engine()
        task_id = await engine.submit(task)
        return {
            "success": True,
            "task_id": task_id,
            "count": len(selected_paths),
            "message": f"已创建 {len(selected_paths)} 个目录上传任务",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("本地库存上传到群晖失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"上传失败: {str(exc)}")


@app.get("/api/local-upload/status")
async def local_upload_status(task_ids: str = "", include_hidden: bool = True):
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        requested_ids = [
            str(item or "").strip()
            for item in str(task_ids or "").split(",")
            if str(item or "").strip()
        ]
        if requested_ids:
            await engine.revive_superseded_local_upload_tasks(requested_ids)
        all_tasks = engine.get_all_tasks(include_hidden=bool(include_hidden))
        upload_tasks = [t for t in all_tasks if t.type == TaskType.LOCAL_LIBRARY_UPLOAD]
        upload_task_map = {str(t.id): t for t in upload_tasks}
        if requested_ids:
            selected_tasks = [upload_task_map[task_id] for task_id in requested_ids if task_id in upload_task_map]
            upload_tasks = selected_tasks

        return {
            "total_tasks": len(upload_tasks),
            "processing": len([t for t in upload_tasks if t.status.value == "processing"]),
            "pending": len([t for t in upload_tasks if t.status.value == "pending"]),
            "completed": len([t for t in upload_tasks if t.status.value == "completed"]),
            "failed": len([t for t in upload_tasks if t.status.value == "failed"]),
            "tasks": [_serialize_local_upload_task_status(t) for t in upload_tasks],
        }
    except Exception as exc:
        logger.error("获取本地上传任务状态失败: %s", sanitize_text_for_log(exc))
        raise HTTPException(status_code=500, detail=f"获取上传状态失败: {str(exc)}")


@app.get("/api/asmr-sync/status")
async def asmr_sync_status(task_ids: str = ""):
    """获取当前同步任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()
        requested_ids = list(dict.fromkeys(
            str(item or "").strip()
            for item in str(task_ids or "").split(",")
            if str(item or "").strip()
        ))

        # 过滤出 ASMR 同步任务
        asmr_tasks = [t for t in all_tasks if t.type == TaskType.ASMR_SYNC_DOWNLOAD]
        if requested_ids:
            task_map = {str(task.id): task for task in asmr_tasks}
            asmr_tasks = [task_map[task_id] for task_id in requested_ids if task_id in task_map]
        session_ids = {
            str(t.task_metadata.get("session_id") or "").strip()
            for t in asmr_tasks
            if str(t.task_metadata.get("session_id") or "").strip()
        }
        session_map = {}
        if session_ids:
            db = SessionLocal()
            try:
                rows = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id.in_(list(session_ids))).all()
                stale_rows_corrected = False
                for row in rows:
                    session = row.to_dict()
                    statistics = dict(session.get("statistics") or {})
                    local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
                    local_count = int(session.get("local_downloaded_count") or 0)
                    local_ready = bool(session.get("local_download_ready"))
                    if local_root and os.path.isdir(local_root):
                        if local_count <= 0:
                            local_count = sum(
                                1
                                for item in (session.get("selected_resources") or [])
                                if os.path.exists(
                                    os.path.join(
                                        local_root,
                                        str(item.get("relative_path") or item.get("file_name") or "").strip().replace("/", os.sep),
                                    )
                                )
                            )
                        local_ready = local_ready or local_count > 0
                    else:
                        if local_ready or local_count > 0 or str(row.local_download_root or "").strip():
                            row.local_download_ready = False
                            row.local_download_root = None
                            row.local_downloaded_count = 0
                            stale_rows_corrected = True
                        local_root = ""
                        local_count = 0
                        local_ready = False
                    session_map[str(row.id)] = {
                        "local_download_ready": local_ready,
                        "local_download_root": local_root,
                        "local_downloaded_count": local_count,
                    }
                if stale_rows_corrected:
                    db.commit()
            finally:
                db.close()

        return {
            "total_tasks": len(asmr_tasks),
            "processing": len([t for t in asmr_tasks if t.status.value == "processing"]),
            "pending": len([t for t in asmr_tasks if t.status.value == "pending"]),
            "completed": len([t for t in asmr_tasks if t.status.value == "completed"]),
            "failed": len([t for t in asmr_tasks if t.status.value == "failed"]),
            "waiting_retry": len([t for t in asmr_tasks if t.status.value == "waiting_retry"]),
            "tasks": [_serialize_asmr_sync_task_status(t, session_map) for t in (asmr_tasks if requested_ids else asmr_tasks[:20])]
        }

    except Exception as e:
        logger.error(f"获取同步状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/asmr-sync/waiting-retry")
async def asmr_sync_waiting_retry():
    """获取等待重试的任务列表及下次重试时间"""
    from ..core.task_engine import get_task_engine, TaskType
    from ..config.settings import get_config
    from datetime import datetime

    try:
        engine = get_task_engine()
        config = get_config()

        # 获取 cron 表达式
        cron_expr = "0 */1 * * *"  # 默认值
        if hasattr(config, 'asmr_sync') and config.asmr_sync:
            if hasattr(config.asmr_sync, 'retry_cron'):
                cron_expr = config.asmr_sync.retry_cron

        # 计算下次重试时间
        try:
            from croniter import croniter
            now = datetime.now()
            cron = croniter(cron_expr, now)
            next_retry_time = cron.get_next(datetime)
        except Exception as cron_err:
            logger.warning(f"解析cron表达式失败: {cron_err}, 使用默认值")
            next_retry_time = datetime.now()

        # 从数据库获取等待重试任务
        try:
            waiting_tasks = engine.get_waiting_retry_tasks_from_db()
        except Exception as db_err:
            logger.error(f"获取等待重试任务失败: {db_err}", exc_info=True)
            waiting_tasks = []

        return {
            "cron_expression": cron_expr,
            "next_retry_time": next_retry_time.isoformat(),
            "tasks": waiting_tasks
        }

    except Exception as e:
        logger.error(f"获取等待重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/pause")
async def asmr_sync_pause_task(task_id: str):
    """暂停任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.pause()
        return {"success": True, "message": "任务已暂停"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"暂停失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/resume")
async def asmr_sync_resume_task(task_id: str):
    """恢复任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.resume()
        return {"success": True, "message": "任务已恢复"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry")
async def asmr_sync_retry_failed(task_id: str):
    """重试失败的文件"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        failed_files = task.task_metadata.get('failed_files', [])
        if not failed_files:
            return {"success": True, "message": "没有失败的文件需要重试"}

        # 清除失败文件列表，重新触发下载
        task.task_metadata['retry_failed'] = True
        task.resume()

        return {"success": True, "message": f"正在重试 {len(failed_files)} 个失败文件"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试失败文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry-waiting")
async def asmr_sync_retry_waiting_task(task_id: str):
    """手动重试等待中的任务（未找到版本的任务）"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        if engine.retry_task(task_id):
            return {"success": True, "message": "任务已加入重试队列"}
        else:
            raise HTTPException(status_code=400, detail="任务不在等待重试状态")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.delete("/api/asmr-sync/task/{task_id}/waiting-retry")
async def asmr_sync_delete_waiting_retry_task(task_id: str):
    """删除等待重试的任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()

        # 从内存中删除任务
        if task_id in engine.tasks:
            task = engine.tasks[task_id]
            rjcode = task.rjcode
            del engine.tasks[task_id]
            logger.info(f"[等待重试] 从内存中删除任务: {task_id}")

            # 从数据库中删除
            engine._remove_waiting_retry_task(rjcode)

            return {"success": True, "message": "任务已删除"}
        else:
            # 任务不在内存中，尝试从数据库删除
            engine._remove_waiting_retry_task_by_id(task_id)
            return {"success": True, "message": "任务已从数据库删除"}

    except Exception as e:
        logger.error(f"删除任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ========== 邮件监听 API ==========

class EmailWatcherTestRequest(BaseModel):
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"


@app.get("/api/email-watcher/status")
async def email_watcher_status():
    """返回邮件监听服务的当前状态。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    service = get_email_watcher_service()
    status = service.get_status()
    status["enabled"] = config.email_watcher.enabled
    if not config.email_watcher.enabled:
        status["mode"] = "disabled"
    return {"success": True, **status}


@app.post("/api/email-watcher/test")
async def email_watcher_test(request: EmailWatcherTestRequest):
    """测试 IMAP 连接是否正常。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    # 使用请求参数，如果为空则回退到已保存配置
    host = request.imap_host or config.email_watcher.imap_host
    port = request.imap_port or config.email_watcher.imap_port
    ssl = request.imap_ssl if request.imap_host else config.email_watcher.imap_ssl
    username = request.username or config.email_watcher.username
    password = request.password or config.email_watcher.password
    mailbox = request.mailbox or config.email_watcher.mailbox
    if not username or not password:
        raise HTTPException(status_code=400, detail="邮箱账号和密码不能为空")
    result = await get_email_watcher_service().test_connection(host, port, ssl, username, password, mailbox)
    return {"success": result.get("success", False), **result}


@app.post("/api/email-watcher/poll-now")
async def email_watcher_poll_now():
    """手动立即触发一次邮件检查（调试用）。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    if not config.email_watcher.enabled:
        raise HTTPException(status_code=400, detail="邮件监听未启用")
    if not config.email_watcher.username:
        raise HTTPException(status_code=400, detail="邮箱账号未配置")
    result = await get_email_watcher_service().poll_once()
    return result


# ========== 通知中心 API ==========

@app.get("/api/notifications/stream")
async def notifications_sse(request: Request):
    """兼容旧通知 SSE：从统一实时事件流筛出通知事件。"""
    import json as _json
    from starlette.responses import StreamingResponse as _SR
    from ..core.redis_service import get_redis_service

    async def generator():
        last_redis_id = "$"
        try:
            yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                redis_events = await asyncio.to_thread(
                    get_redis_service().read_stream_payloads_sync,
                    'events:stream',
                    last_id=last_redis_id,
                    block_ms=1000,
                    count=50,
                )
                if redis_events:
                    for message_id, event in redis_events:
                        last_redis_id = message_id
                        if str((event or {}).get("type") or "") != "notification.new":
                            continue
                        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                        if payload:
                            yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
                elif int(time.time()) % 25 == 0:
                    yield ": keepalive\n\n"
        finally:
            pass

    return _SR(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/notifications/unread-count")
async def notifications_unread_count():
    """获取未读通知数"""
    from ..core.task_notification_service import get_unread_count
    count = await asyncio.to_thread(get_unread_count)
    return {"count": count}


@app.get("/api/notifications")
async def list_notifications(
    page: int = 1,
    limit: int = 30,
    unread_only: bool = False,
):
    """获取通知列表"""
    from ..core.task_notification_service import list_notifications as _list
    return await asyncio.to_thread(_list, page=page, limit=limit, unread_only=unread_only)


class NotificationReadRequest(BaseModel):
    ids: List[str]


@app.post("/api/notifications/read")
async def mark_notifications_read(body: NotificationReadRequest):
    """标记指定通知为已读"""
    from ..core.task_notification_service import mark_read
    count = await asyncio.to_thread(mark_read, body.ids)
    return {"updated": count}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read():
    """标记全部通知为已读"""
    from ..core.task_notification_service import mark_all_read
    count = await asyncio.to_thread(mark_all_read)
    return {"updated": count}


@app.delete("/api/notifications/{item_id}")
async def delete_notification(item_id: str):
    """删除单条通知"""
    from ..core.task_notification_service import delete_notification as _delete
    ok = await asyncio.to_thread(_delete, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"ok": True}


class TestEmailRequest(BaseModel):
    config: Optional[dict] = None


@app.post("/api/notifications/test-email")
async def test_notification_email(body: TestEmailRequest):
    """测试 SMTP 发送配置"""
    from ..core.notification_email_service import test_smtp_connection, get_smtp_executor
    cfg_dict = body.config or {}
    if not cfg_dict:
        config = get_config()
        cfg_dict = config.notification_email.model_dump()
    loop = asyncio.get_event_loop()
    # 用专用 SMTP 线程池，防止用户点测试按钮时一旦卡住把 default executor 污染掉，
    # 拖累其他同步路由 / 后台 run_in_executor 调用。
    result = await loop.run_in_executor(get_smtp_executor(), test_smtp_connection, cfg_dict)
    return result


# ---- 通知模板 API ----

@app.get("/api/notifications/templates")
async def list_notification_templates():
    """获取所有通知模板"""
    from ..core.notification_template_service import list_templates
    return {"items": list_templates()}


@app.post("/api/notifications/templates")
async def create_notification_template(request: Request):
    """创建通知模板"""
    from ..core.notification_template_service import create_template
    data = await request.json()
    return create_template(data)


@app.put("/api/notifications/templates/{template_id}")
async def update_notification_template(template_id: str, request: Request):
    """更新通知模板"""
    from ..core.notification_template_service import update_template
    data = await request.json()
    result = update_template(template_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="模板不存在")
    return result


@app.delete("/api/notifications/templates/{template_id}")
async def delete_notification_template(template_id: str):
    """删除通知模板"""
    from ..core.notification_template_service import delete_template
    ok = delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True}


class TemplatePreviewRequest(BaseModel):
    template_id: Optional[str] = None
    payload: Optional[dict] = None


@app.post("/api/notifications/templates/preview")
async def preview_notification_template(body: TemplatePreviewRequest):
    """预览模板渲染结果"""
    from ..core.notification_template_service import preview_template
    sample_payload = body.payload or {
        'event_type': 'completed',
        'title': '示例任务',
        'domain_label': '解压入库',
        'summary': '解压入库任务完成',
        'rjcode': 'RJ123456',
    }
    return preview_template(body.template_id, sample_payload)


# ---- Block 编辑器 API ----

@app.get("/api/notifications/blocks/schema")
async def get_blocks_schema():
    """返回 Block 类型 Schema、默认 props、属性定义和变量列表。"""
    from ..core.block_renderers import BLOCK_SCHEMA
    from ..core.variable_registry import VARIABLE_REGISTRY
    variables = [
        {"key": k, "label": v["label"], "example": v["example"]}
        for k, v in VARIABLE_REGISTRY.items()
    ]
    return {"blocks": BLOCK_SCHEMA, "variables": variables}


class PreviewBlocksRequest(BaseModel):
    requestId: Optional[str] = None
    blocks: list = []
    event_type: str = "completed"
    domain: str = "import"
    subject_template: Optional[str] = ""


@app.post("/api/notifications/templates/preview-blocks")
async def preview_notification_blocks(body: PreviewBlocksRequest):
    """用 blocks 数组 + 示例 payload 渲染预览 HTML，支持 requestId 校验乱序。"""
    from ..core.notification_template_service import preview_blocks
    result = preview_blocks(
        blocks=body.blocks,
        event_type=body.event_type,
        domain=body.domain,
        subject_template=body.subject_template or "",
    )
    return {"requestId": body.requestId, **result}



from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    # 返回项目根目录 (backend/app/api -> ../../../)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_base_path = get_base_path()

static_files_path = os.environ.get('STATIC_FILES_PATH', os.path.join(_base_path, "static"))
frontend_path = os.environ.get('FRONTEND_PATH', os.path.join(_base_path, "frontend", "dist"))

possible_paths = [
    frontend_path,
    static_files_path,
    os.path.join(_base_path, "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "../frontend/dist"),
    "/app/static",
]

frontend_build_path = None
logger.info(f"检查静态文件路径，当前工作目录: {os.getcwd()}")
logger.info(f"基础路径: {_base_path}")
for path in possible_paths:
    index_file = os.path.join(path, "index.html")
    path_exists = os.path.exists(path)
    index_exists = os.path.exists(index_file)
    logger.info(f"检查路径: {path} - 目录存在: {path_exists}, index.html存在: {index_exists}")
    if path_exists and index_exists:
        frontend_build_path = path
        logger.info(f"找到前端构建文件: {path}")
        break

# 注册静态文件服务（放在子路径，避免覆盖 API）
if frontend_build_path:
    # 提供静态资源文件（JS、CSS、图片等）
    app.mount("/assets", PrecompressedStaticFiles(directory=os.path.join(frontend_build_path, "assets")), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        favicon_path = os.path.join(frontend_build_path, "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path, media_type="image/x-icon")
        raise HTTPException(status_code=404, detail="Favicon not found")
    
    # 捕获所有非 API 路由，返回 index.html（SPA 支持）
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API 路由不应该被拦截
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # 对于前端路由，返回 index.html
        index_path = os.path.join(frontend_build_path, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")
