import asyncio
import contextlib
import hashlib
import html
import inspect
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

import aiohttp
import httpx

from ..config.settings import get_config, save_config
from .google_drive_oauth import (
    google_drive_oauth_client_missing_message,
    resolve_google_drive_oauth_client,
    resolve_google_drive_oauth_proxy_url,
)
from .log_sanitizer import sanitize_text_for_log
from .resource_budget_service import get_resource_budget_service

logger = logging.getLogger(__name__)

_BLOCKED_HOST_HINTS = {"tranfile.com", "transfernow.net"}
_PIKPAK_HOST_HINTS = {"mypikpak.com", "www.mypikpak.com", "drive.mypikpak.com"}
_GOFILE_HOST_HINTS = {"gofile.io", "www.gofile.io"}
_TRANSFERIT_HOST_HINTS = {"transfer.it", "www.transfer.it"}
_ONEDRIVE_HOST_HINTS = {"1drv.ms", "onedrive.live.com", "onedrive.com"}
_GOOGLE_DRIVE_HOST_HINTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
_PIKPAK_MAX_SHARE_FILES = 100
_PIKPAK_STATUS_CACHE_TTL_SECONDS = 6 * 60 * 60
_SHARE_PREVIEW_ONLY_SOURCES = {"pikpak", "transferit"}
_GOFILE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_GOFILE_LANGUAGE = "en-US"
_GOFILE_WEBSITE_TOKEN_SALT = "g4f8fd9f12h14g"
_GOFILE_CDN_ERROR_CONTENT_TYPES = ("text/html", "application/json", "text/plain")
GOOGLE_DRIVE_PROBE_BYTES = 1024
GOOGLE_DRIVE_STREAM_CHUNK_BYTES = 1024 * 1024
HTTP_DOWNLOAD_PLATFORM_LABELS = {
    "http": "HTTP",
    "gofile": "Gofile",
    "transferit": "Transfer.it",
    "onedrive": "OneDrive",
    "google_drive": "Google Drive",
    "pikpak": "PikPak",
}
HTTP_DOWNLOAD_PROXY_PLATFORMS = tuple(HTTP_DOWNLOAD_PLATFORM_LABELS.keys())


def normalize_http_download_platform(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "http"
    normalized = re.sub(r"[^a-z0-9._-]+", "_", text)
    if normalized in {"http", "https", "direct", "direct_link"}:
        return "http"
    if normalized in {"gofile", "gofile.io"} or "gofile.io" in text:
        return "gofile"
    if normalized in {"transferit", "transfer.it"} or "transfer.it" in text:
        return "transferit"
    if normalized in {"onedrive", "one_drive", "1drv", "1drv.ms", "onedrive.live.com", "onedrive.com"} or "onedrive" in text or "1drv.ms" in text:
        return "onedrive"
    if normalized in {"google_drive", "google-drive", "googledrive", "drive.google.com", "docs.google.com", "drive.usercontent.google.com"} or "drive.google.com" in text or "docs.google.com" in text or "drive.usercontent.google.com" in text or "google drive" in text:
        return "google_drive"
    if normalized in {"pikpak", "mypikpak.com", "drive.mypikpak.com"} or "pikpak" in text or "mypikpak.com" in text:
        return "pikpak"
    return normalized if normalized in HTTP_DOWNLOAD_PLATFORM_LABELS else "http"


def http_download_platform_label(value: Any) -> str:
    return HTTP_DOWNLOAD_PLATFORM_LABELS.get(normalize_http_download_platform(value), "HTTP")


def http_download_platforms_from_metadata(metadata: Dict[str, Any]) -> List[str]:
    if not isinstance(metadata, dict):
        return ["http"]
    platforms: List[str] = []

    def push(value: Any) -> None:
        key = normalize_http_download_platform(value)
        if key and key not in platforms:
            platforms.append(key)

    for value in list(metadata.get("source_modes") or []):
        push(value)
    for value in list(metadata.get("platforms") or []):
        push(value)
    for key in ("download_mode", "source_action", "source_label", "batch_name"):
        push(metadata.get(key))
    for item in list(metadata.get("download_files") or []):
        if not isinstance(item, dict):
            continue
        push(item.get("source"))
        push(item.get("url"))
    for item in list(metadata.get("preview_items") or []):
        if not isinstance(item, dict):
            continue
        push(item.get("source"))
        push(item.get("masked_url") or item.get("url"))
    if not platforms:
        platforms.append("http")
    return platforms


def http_download_platforms_label(platforms: List[str]) -> str:
    labels = [
        HTTP_DOWNLOAD_PLATFORM_LABELS.get(normalize_http_download_platform(platform), str(platform or "").strip())
        for platform in (platforms or [])
        if str(platform or "").strip()
    ]
    labels = [label for index, label in enumerate(labels) if label and label not in labels[:index]]
    specific = [label for label in labels if label != "HTTP"]
    if not specific:
        return "HTTP"
    if len(specific) <= 2:
        return " / ".join(specific)
    return f"{' / '.join(specific[:2])} 等 {len(specific)} 平台"


def build_http_download_batch_title(metadata: Dict[str, Any], item_count: int = 0, fallback_host: str = "") -> str:
    platforms = http_download_platforms_from_metadata(metadata)
    platform_label = http_download_platforms_label(platforms)
    count = int(item_count or metadata.get("selected_count") or metadata.get("url_count") or 0)
    if count > 1:
        return f"{platform_label} 下载 {count} 项"
    if count == 1:
        return f"{platform_label} 下载"
    return f"{platform_label} 下载" if platform_label != "HTTP" else (fallback_host or "HTTP 下载")


class HttpDownloadError(ValueError):
    """HTTP 外链下载的可预期业务错误。"""


class _TransferitDownloadAbort(RuntimeError):
    """内部控制异常：用于从 transferit-py 的同步流式回调里中止下载。"""


class _GoogleDriveFolderHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: List[Dict[str, str]] = []
        self._current_href = ""
        self._current_class = ""
        self._current_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {str(key or "").lower(): str(value or "") for key, value in attrs}
        href = attr_map.get("href", "")
        if not href:
            return
        self._current_href = href
        self._current_class = attr_map.get("class", "")
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        text = " ".join("".join(self._current_text).split())
        if "/file/d/" in self._current_href or "id=" in self._current_href:
            self.rows.append({
                "href": self._current_href,
                "name": text,
                "class": self._current_class,
            })
        self._current_href = ""
        self._current_class = ""
        self._current_text = []


class _GoogleDriveDownloadFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = ""
        self.inputs: Dict[str, str] = {}
        self._in_download_form = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        attr_map = {str(key or "").lower(): str(value or "") for key, value in attrs}
        if tag_name == "form" and attr_map.get("id") == "download-form":
            self._in_download_form = True
            self.action = attr_map.get("action", "")
            return
        if tag_name == "input" and self._in_download_form:
            name = attr_map.get("name", "")
            if name:
                self.inputs[name] = attr_map.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._in_download_form:
            self._in_download_form = False


def mask_http_download_url(value: str) -> str:
    """Mask URL credentials before anything leaves backend internals."""
    text = str(value or "")
    if not text:
        return ""
    if "://" not in text and "@" in text:
        text = f"http://{text}"
    try:
        parsed = urlparse(text)
        if parsed.username or parsed.password:
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            return urlunparse((
                parsed.scheme,
                f"***:***@{host}",
                parsed.path,
                parsed.params,
                "query=***" if parsed.query else "",
                "fragment=***" if parsed.fragment else "",
            ))
        if parsed.scheme and parsed.netloc and (parsed.query or parsed.fragment):
            return urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                "query=***" if parsed.query else "",
                "fragment=***" if parsed.fragment else "",
            ))
    except Exception:
        pass
    return re.sub(r"//([^/@:]+):([^/@]+)@", "//***:***@", text)


def sanitize_http_download_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a public-safe file/preview row without retry-only raw URLs."""
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    out.pop("headers", None)
    out.pop("aria2_header", None)
    raw_url = str(out.get("url") or out.get("original_url") or "")
    masked_url = str(out.get("masked_url") or "").strip()
    if raw_url and not masked_url:
        masked_url = mask_http_download_url(raw_url)
    out.pop("original_url", None)
    if "url" in out:
        out["url"] = masked_url or mask_http_download_url(str(out.get("url") or ""))
    if masked_url:
        out["masked_url"] = masked_url
    return out


def sanitize_http_download_preview(preview: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize preview/start response payloads before returning to clients."""
    if not isinstance(preview, dict):
        return {}
    out = dict(preview)
    out["items"] = [
        sanitize_http_download_item(item)
        for item in list(out.get("items") or [])
        if isinstance(item, dict)
    ]
    out.pop("resolved_urls", None)
    if "source_items" in out:
        out["source_items"] = [
            sanitize_http_download_item(item)
            for item in list(out.get("source_items") or [])
            if isinstance(item, dict)
        ]
    return out


def sanitize_http_download_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize task metadata for task center, activity logs, and diagnostics."""
    if not isinstance(metadata, dict):
        return {}
    out = dict(metadata)
    out.pop("urls", None)
    out.pop("resolved_urls", None)
    for key in ("download_files", "failed_files", "downloaded_files"):
        if key in out:
            out[key] = [
                sanitize_http_download_item(item)
                for item in list(out.get(key) or [])
                if isinstance(item, dict)
            ]
    if "preview_items" in out:
        out["preview_items"] = [
            sanitize_http_download_item(item)
            for item in list(out.get("preview_items") or [])
            if isinstance(item, dict)
        ]
    if "source_items" in out:
        out["source_items"] = [
            sanitize_http_download_item(item)
            for item in list(out.get("source_items") or [])
            if isinstance(item, dict)
        ]
    return out


def sanitize_http_download_error(value: Any) -> str:
    """Mask URL-like substrings that may appear inside exception messages."""
    text = sanitize_text_for_log(value)
    if not text:
        return ""
    return re.sub(
        r"https?://[^\s'\"<>）)]*",
        lambda match: mask_http_download_url(match.group(0)),
        text,
    )


@dataclass
class Aria2Daemon:
    process: subprocess.Popen
    endpoint: str
    secret: str


@dataclass
class PikPakAccount:
    id: str
    label: str
    enabled: bool
    username: str
    password: str
    encoded_token: str
    device_id: str
    transfer_dir: str
    legacy: bool = False


class HttpDownloadService:
    """通用 HTTP/HTTPS 外链下载服务，底层通过 aria2 RPC 驱动。"""

    def __init__(self):
        self._daemon: Optional[Aria2Daemon] = None
        self._daemon_lock = asyncio.Lock()
        self._task_gids: Dict[str, List[str]] = {}
        self._active_download_tasks: Dict[str, asyncio.Task] = {}
        self._rpc_id = 0
        self._gofile_guest_token_cache: tuple[str, float] = ("", 0.0)
        self._gofile_guest_token_lock = asyncio.Lock()
        self._google_drive_access_token_cache: tuple[str, float] = ("", 0.0)
        self._google_drive_access_token_lock = asyncio.Lock()

    def _config(self):
        return get_config().http_downloader

    def _storage_temp_root(self) -> str:
        return str(getattr(get_config().storage, "temp_path", "") or tempfile.gettempdir())

    def _download_root(self) -> str:
        cfg = self._config()
        root = str(getattr(cfg, "download_root", "") or "").strip()
        if not root:
            root = str(getattr(get_config().storage, "input_path", "") or "").strip()
        if not root:
            root = os.path.join(get_config().storage.temp_path, "http_downloads")
        return os.path.abspath(root)

    def _mask_url(self, value: str) -> str:
        return mask_http_download_url(value)

    def _sanitize_error(self, value: Any) -> str:
        return sanitize_http_download_error(value)

    def _pikpak_error(self, value: Any, stage: str = "") -> HttpDownloadError:
        text = self._sanitize_error(value)
        lowered = text.lower()
        prefix = f"PikPak {stage}失败" if stage else "PikPak 操作失败"
        if lowered.strip() in {"not found", "404", "404 not found"}:
            return HttpDownloadError(f"{prefix}: PikPak 返回 404。若这是账号检测，通常是旧 token 已失效或后端接口版本未重启；请重新输入密码保存后重试。原始错误: {text}")
        if any(marker in lowered for marker in ("current region", "region", "prohibited", "not available")) or any(marker in text for marker in ("地区", "区域", "不可用", "禁止")):
            return HttpDownloadError(f"{prefix}: 分享在当前账号/地区不可用，通常需要更换 PikPak 账号地区或代理节点后重试。原始错误: {text}")
        if any(marker in lowered for marker in ("insufficient", "quota", "space", "not enough", "capacity", "storage")) or any(marker in text for marker in ("空间", "容量", "配额", "不足")):
            return HttpDownloadError(f"{prefix}: 账号空间不足，先在设置页清理转存目录或更换账号后重试。原始错误: {text}")
        if any(marker in lowered for marker in ("invalid username", "invalid account", "invalid_account_or_password", "password", "unauthorized", "token", "login")) or any(marker in text for marker in ("账号", "密码", "登录", "token", "Token", "授权")):
            return HttpDownloadError(f"{prefix}: 账号登录或 token 已失效，请在设置页重新保存账号/密码或清空缓存 Token 后重试。原始错误: {text}")
        if any(marker in lowered for marker in ("phone_number", "meta.username", "captcha init params")):
            return HttpDownloadError(f"{prefix}: 触发 PikPak 验证/验证码，当前后端不能自动处理；如果这是手机号账号，试试在号码前补所属国家码，例如 +86。原始错误: {text}")
        if any(marker in lowered for marker in ("captcha", "verification", "verify")) or any(marker in text for marker in ("验证码", "验证")):
            return HttpDownloadError(f"{prefix}: 触发 PikPak 验证/验证码，当前后端不能自动处理，请稍后重试或换账号；如果这是手机号账号，试试在号码前补所属国家码，例如 +86。原始错误: {text}")
        if any(marker in lowered for marker in ("vip", "privilege", "permission", "forbidden", "403")) or any(marker in text for marker in ("会员", "权限", "无权")):
            return HttpDownloadError(f"{prefix}: 账号权限不足或文件需要会员能力。原始错误: {text}")
        if any(marker in lowered for marker in ("not found", "expired", "deleted", "share")) or any(marker in text for marker in ("不存在", "过期", "删除", "分享")):
            return HttpDownloadError(f"{prefix}: 分享不存在、已过期或提取码不对。原始错误: {text}")
        if any(marker in lowered for marker in ("timeout", "timed out", "connection", "network")) or any(marker in text for marker in ("超时", "网络", "连接")):
            return HttpDownloadError(f"{prefix}: 连接 PikPak 超时或网络不可用，请检查代理/网络。原始错误: {text}")
        return HttpDownloadError(f"{prefix}: {text or value.__class__.__name__}")

    def _is_pikpak_token_error(self, value: Any) -> bool:
        text = self._sanitize_error(value).lower()
        return any(marker in text for marker in (
            "not found",
            "404",
            "unauthorized",
            "token",
            "login",
            "invalid",
            "expired",
        ))

    def _proxy_platforms(self) -> set[str]:
        raw_values = getattr(self._config(), "proxy_platforms", None)
        if raw_values is None:
            return set(HTTP_DOWNLOAD_PROXY_PLATFORMS)
        if not isinstance(raw_values, list):
            raw_values = [raw_values]
        platforms = {
            normalize_http_download_platform(value)
            for value in raw_values
            if str(value or "").strip()
        }
        return {platform for platform in platforms if platform in HTTP_DOWNLOAD_PLATFORM_LABELS}

    def _proxy_enabled_for(self, platform: Any = "http") -> bool:
        return normalize_http_download_platform(platform) in self._proxy_platforms()

    def _proxy_url(self, platform: Any = "http") -> str:
        if not self._proxy_enabled_for(platform):
            return ""
        proxy = str(getattr(self._config(), "proxy_url", "") or "").strip()
        if not proxy:
            proxy = str(getattr(getattr(get_config(), "metadata", None), "http_proxy", "") or "").strip()
        if proxy and "://" not in proxy:
            proxy = f"http://{proxy}"
        return proxy

    def _pikpak_enabled(self) -> bool:
        return bool(getattr(self._config(), "pikpak_enabled", False))

    def _pikpak_account_id(self, account: Dict[str, Any], index: int) -> str:
        raw_id = str(account.get("id") or "").strip()
        if raw_id:
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_id).strip("-")
            if safe:
                return safe[:80]
        raw_identity = str(account.get("username") or account.get("label") or "").strip()
        if raw_identity:
            digest = hashlib.sha1(raw_identity.encode("utf-8", errors="ignore")).hexdigest()[:10]
            return f"account-{digest}"
        return f"account-{index + 1}"

    def _pikpak_accounts(self, *, include_disabled: bool = False) -> List[PikPakAccount]:
        cfg = self._config()
        accounts: List[PikPakAccount] = []
        seen: set[str] = set()
        configured = list(getattr(cfg, "pikpak_accounts", []) or [])
        for index, raw in enumerate(configured):
            if hasattr(raw, "model_dump"):
                data = raw.model_dump()
            elif isinstance(raw, dict):
                data = dict(raw)
            else:
                continue
            account_id = self._pikpak_account_id(data, index)
            if account_id in seen:
                suffix = 2
                base_id = account_id
                while f"{base_id}-{suffix}" in seen:
                    suffix += 1
                account_id = f"{base_id}-{suffix}"
            seen.add(account_id)
            username = str(data.get("username") or "").strip()
            label = str(data.get("label") or "").strip() or username or account_id
            transfer_dir = str(data.get("transfer_dir") or "").strip() or "/KikoeruManager"
            accounts.append(PikPakAccount(
                id=account_id,
                label=label,
                enabled=bool(data.get("enabled", True)),
                username=username,
                password=str(data.get("password") or "").strip(),
                encoded_token=str(data.get("encoded_token") or "").strip(),
                device_id=str(data.get("device_id") or "").strip(),
                transfer_dir=transfer_dir,
            ))

        legacy_token = str(getattr(cfg, "pikpak_encoded_token", "") or "").strip()
        legacy_username = str(getattr(cfg, "pikpak_username", "") or "").strip()
        legacy_password = str(getattr(cfg, "pikpak_password", "") or "").strip()
        if legacy_token or (legacy_username and legacy_password):
            legacy_id = "default"
            if legacy_id in seen:
                legacy_id = "legacy-default"
            legacy_label = str(getattr(cfg, "pikpak_label", "") or "").strip() or legacy_username or "PikPak 账号"
            accounts.insert(0, PikPakAccount(
                id=legacy_id,
                label=legacy_label,
                enabled=bool(getattr(cfg, "pikpak_default_enabled", True)),
                username=legacy_username,
                password=legacy_password,
                encoded_token=legacy_token,
                device_id=str(getattr(cfg, "pikpak_device_id", "") or "").strip(),
                transfer_dir=str(getattr(cfg, "pikpak_transfer_dir", "") or "/KikoeruManager").strip() or "/KikoeruManager",
                legacy=True,
            ))
        if include_disabled:
            return accounts
        return [item for item in accounts if item.enabled]

    def _pikpak_account_public(self, account: PikPakAccount) -> Dict[str, Any]:
        return {
            "id": account.id,
            "label": account.label,
            "username": account.username,
            "enabled": account.enabled,
            "transfer_dir": account.transfer_dir,
            "legacy": account.legacy,
            "configured": bool(account.encoded_token or (account.username and account.password)),
        }

    def _mask_pikpak_username_for_cache(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "@" in text:
            name, domain = text.split("@", 1)
            if len(name) <= 2:
                masked = f"{name[:1]}***"
            else:
                masked = f"{name[:2]}***{name[-1:]}"
            return f"{masked}@{domain}"
        prefix = "+" if text.startswith("+") else ""
        raw = text[1:] if prefix else text
        if raw.isdigit() and len(raw) >= 6:
            return f"{prefix}{raw[:3]}****{raw[-2:]}"
        if len(text) <= 4:
            return f"{text[:1]}***"
        return f"{text[:2]}***{text[-1:]}"

    def _pikpak_status_cache_ttl_seconds(self) -> int:
        return _PIKPAK_STATUS_CACHE_TTL_SECONDS

    def _pikpak_status_cache_is_fresh(self, updated_at: Optional[datetime]) -> bool:
        if not updated_at:
            return False
        return (datetime.now() - updated_at).total_seconds() <= self._pikpak_status_cache_ttl_seconds()

    def _pikpak_public_status(
        self,
        account: PikPakAccount,
        *,
        success: bool,
        ready: bool,
        quota: Optional[Dict[str, Any]] = None,
        transfer_quota: Optional[Dict[str, Any]] = None,
        vip: Optional[Dict[str, Any]] = None,
        message: str = "",
        source: str = "live",
        cached: bool = False,
        updated_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "success": bool(success),
            "enabled": True,
            "ready": bool(ready),
            "account": self._pikpak_account_public(account),
            "account_id": account.id,
            "account_label": account.label,
            "transfer_dir": account.transfer_dir,
            "quota": quota or {},
            "transfer_quota": transfer_quota or {},
            "vip": vip or {},
            "source": source,
            "cached": cached,
        }
        if message:
            payload["message"] = message
        if updated_at:
            payload["updated_at"] = updated_at.isoformat()
            payload["cache_updated_at"] = updated_at.isoformat()
        return payload

    def _pikpak_status_cache_read(self, account: PikPakAccount, *, require_fresh: bool = True) -> Optional[Dict[str, Any]]:
        try:
            from ..models.database import PikPakStatusCache, SessionLocal
        except Exception:
            return None
        db = SessionLocal()
        try:
            row = db.query(PikPakStatusCache).filter(PikPakStatusCache.account_id == account.id).first()
            if not row:
                return None
            if require_fresh and not self._pikpak_status_cache_is_fresh(row.updated_at):
                return None
            payload = row.to_status_dict()
            payload["account"] = {
                **payload.get("account", {}),
                **self._pikpak_account_public(account),
                "username": self._mask_pikpak_username_for_cache(account.username),
            }
            payload["account_label"] = account.label
            payload["transfer_dir"] = account.transfer_dir
            payload["source"] = "cache"
            payload["cached"] = True
            return payload
        except Exception:
            logger.debug("[PikPak] 读取状态缓存失败 account=%s", account.id, exc_info=True)
            return None
        finally:
            db.close()

    def _pikpak_status_cache_write(self, status: Dict[str, Any], account: PikPakAccount, *, source: str = "live") -> None:
        try:
            from ..models.database import PikPakStatusCache, SessionLocal
        except Exception:
            return
        now = datetime.now()
        db = SessionLocal()
        try:
            row = db.query(PikPakStatusCache).filter(PikPakStatusCache.account_id == account.id).first()
            if row is None:
                row = PikPakStatusCache(account_id=account.id)
                db.add(row)
            row.account_label = str(status.get("account_label") or account.label or account.id)
            row.username_hint = self._mask_pikpak_username_for_cache(account.username)
            row.transfer_dir = str(status.get("transfer_dir") or account.transfer_dir or "/KikoeruManager")
            row.success = bool(status.get("success"))
            row.ready = bool(status.get("ready") or status.get("success"))
            row.quota = dict(status.get("quota") or {})
            row.transfer_quota = dict(status.get("transfer_quota") or {})
            row.vip = dict(status.get("vip") or {})
            row.message = str(status.get("message") or "")
            row.source = source or "live"
            row.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            logger.debug("[PikPak] 写入状态缓存失败 account=%s", account.id, exc_info=True)
        finally:
            db.close()

    def _pikpak_status_cache_delete_missing(self, active_account_ids: set[str]) -> None:
        try:
            from ..models.database import PikPakStatusCache, SessionLocal
        except Exception:
            return
        db = SessionLocal()
        try:
            query = db.query(PikPakStatusCache)
            if active_account_ids:
                query = query.filter(~PikPakStatusCache.account_id.in_(active_account_ids))
            query.delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            logger.debug("[PikPak] 清理已移除账号状态缓存失败", exc_info=True)
        finally:
            db.close()

    def _pikpak_merge_statuses(self, statuses: List[Dict[str, Any]]) -> Dict[str, Any]:
        primary = next((item for item in statuses if item.get("success")), statuses[0])
        result = dict(primary)
        result["accounts"] = statuses
        result["total_remaining_bytes"] = sum(int((item.get("quota") or {}).get("remaining_bytes") or 0) for item in statuses if item.get("success"))
        result["ready"] = any(item.get("success") for item in statuses)
        result["success"] = result["ready"]
        result["cached"] = all(bool(item.get("cached")) for item in statuses)
        cache_times = [str(item.get("cache_updated_at") or item.get("updated_at") or "") for item in statuses if item.get("cache_updated_at") or item.get("updated_at")]
        if cache_times:
            result["cache_updated_at"] = max(cache_times)
            result["updated_at"] = max(cache_times)
        return result

    def _pikpak_account_from_payload(self, data: Dict[str, Any], *, fallback_id: str = "") -> PikPakAccount:
        payload = dict(data or {})
        account_id = self._pikpak_account_id(payload, 0)
        if fallback_id:
            account_id = str(fallback_id).strip() or account_id
        username = str(payload.get("username") or "").strip()
        label = str(payload.get("label") or "").strip() or username or account_id
        return PikPakAccount(
            id=account_id,
            label=label,
            enabled=bool(payload.get("enabled", True)),
            username=username,
            password=str(payload.get("password") or "").strip(),
            encoded_token=str(payload.get("encoded_token") or "").strip(),
            device_id=str(payload.get("device_id") or "").strip(),
            transfer_dir=str(payload.get("transfer_dir") or "").strip() or "/KikoeruManager",
            legacy=bool(payload.get("legacy", False)),
        )

    def _select_pikpak_account(self, account_id: str = "") -> PikPakAccount:
        accounts = self._pikpak_accounts()
        if not accounts:
            raise HttpDownloadError("PikPak 未配置可用账号或 token")
        wanted = str(account_id or "").strip()
        if not wanted:
            return accounts[0]
        for account in accounts:
            if account.id == wanted:
                return account
        raise HttpDownloadError(f"PikPak 账号不存在或已禁用: {wanted}")

    def _host_matches(self, raw_url: str, hosts: set[str]) -> bool:
        try:
            parsed = urlparse(str(raw_url or "").strip())
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return any(host == item or host.endswith(f".{item}") for item in hosts)

    def _is_pikpak_url(self, raw_url: str) -> bool:
        return self._host_matches(raw_url, _PIKPAK_HOST_HINTS)

    def _is_gofile_url(self, raw_url: str) -> bool:
        return self._host_matches(raw_url, _GOFILE_HOST_HINTS)

    def _is_transferit_url(self, raw_url: str) -> bool:
        return self._host_matches(raw_url, _TRANSFERIT_HOST_HINTS)

    def _is_onedrive_url(self, raw_url: str) -> bool:
        return self._host_matches(raw_url, _ONEDRIVE_HOST_HINTS)

    def _is_google_drive_url(self, raw_url: str) -> bool:
        return self._host_matches(raw_url, _GOOGLE_DRIVE_HOST_HINTS)

    def _provider_source(self, raw_url: str) -> str:
        if self._is_pikpak_url(raw_url):
            return "pikpak"
        if self._is_gofile_url(raw_url):
            return "gofile"
        if self._is_transferit_url(raw_url):
            return "transferit"
        if self._is_onedrive_url(raw_url):
            return "onedrive"
        if self._is_google_drive_url(raw_url):
            return "google_drive"
        return "http"

    def _gofile_cdn_preview_failure_reason(self, item: Dict[str, Any], source_item: Dict[str, Any]) -> str:
        if str(source_item.get("source") or "").strip().lower() != "gofile":
            return ""
        if not isinstance(item, dict) or not item.get("ok"):
            reason = str((item or {}).get("reason") or (item or {}).get("failure_reason") or "").strip()
            return f"Gofile CDN 预览校验失败，已阻止下载，避免保存源站错误页: {reason or '源站未返回可校验的文件响应'}"
        content_type = str(item.get("content_type") or "").strip().lower()
        if any(marker in content_type for marker in _GOFILE_CDN_ERROR_CONTENT_TYPES):
            return f"Gofile CDN 返回 {content_type or '非文件响应'}，已阻止下载，避免把错误页保存为压缩包"
        api_size = int(source_item.get("size_bytes") or 0)
        probed_size = int(item.get("size_bytes") or 0)
        if api_size > 0 and probed_size > 0 and probed_size < api_size:
            return (
                f"Gofile CDN 返回大小 {probed_size} bytes，小于 API 文件大小 {api_size} bytes，"
                "已阻止下载，避免保存不完整的错误响应"
            )
        return ""

    def _preview_item_selection_key(self, item: Dict[str, Any]) -> str:
        """Build a public-safe stable key used by the UI to select preview rows."""
        if not isinstance(item, dict):
            return ""
        existing = str(item.get("selection_key") or "").strip()
        if existing:
            return existing
        source = str(item.get("source") or "http").strip().lower() or "http"
        stable_source_id = (
            str(item.get("content_id") or "").strip()
            or str(item.get("file_id") or "").strip()
            or str(item.get("transferit_node_handle") or "").strip()
            or str(item.get("download_file_id") or "").strip()
            or str(item.get("share_id") or "").strip()
        )
        share_url = str(item.get("share_url") or "").strip()
        share_url_identity = share_url
        url_identity = ""
        if source == "http" or (not stable_source_id and not share_url):
            url_identity = str(item.get("masked_url") or item.get("url") or "").strip()
        filename_identity = str(item.get("filename") or item.get("name") or "").strip()
        relative_path_identity = str(item.get("relative_path") or "").strip()
        size_identity = str(item.get("size_bytes") or item.get("size") or "").strip()
        if source in _SHARE_PREVIEW_ONLY_SOURCES and (stable_source_id or share_url):
            if stable_source_id:
                share_url_identity = ""
            filename_identity = ""
            relative_path_identity = str(item.get("relative_dir") or "").strip()
            size_identity = ""
        parts = [
            source,
            share_url_identity,
            stable_source_id,
            url_identity,
            relative_path_identity,
            str(item.get("relative_dir") or "").strip(),
            filename_identity,
            size_identity,
        ]
        digest = hashlib.sha1("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"{source}:{digest}"

    def filter_preview_selection(
        self,
        preview: Dict[str, Any],
        selected_keys: Optional[List[str]] = None,
        selected_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        keys = {
            str(key or "").strip()
            for key in (selected_keys or [])
            if str(key or "").strip()
        }
        for item in selected_items or []:
            if isinstance(item, dict):
                key = self._preview_item_selection_key(item)
                if key:
                    keys.add(key)
        if not keys:
            return preview

        selected_overrides = {
            self._preview_item_selection_key(item): self._http_selected_item_overrides(item)
            for item in (selected_items or [])
            if isinstance(item, dict) and self._preview_item_selection_key(item)
        }
        out = dict(preview or {})
        items = []
        for item in list(out.get("items") or []):
            if not isinstance(item, dict):
                continue
            key = self._preview_item_selection_key(item)
            if key not in keys:
                continue
            merged = dict(item)
            overrides = selected_overrides.get(key) or {}
            if overrides:
                merged.update(overrides)
            items.append(merged)
        out["items"] = items
        ok_count = sum(1 for item in items if item.get("ok"))
        out["ok_count"] = ok_count
        out["failed_count"] = len(items) - ok_count
        out["success"] = ok_count > 0
        out["selected_count"] = len(items)
        return out

    def _http_selected_item_overrides(self, item: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        custom_name = str(item.get("custom_name") or item.get("custom_filename") or "").strip()
        custom_extract_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        overrides: Dict[str, Any] = {}
        if custom_name:
            overrides["custom_name"] = custom_name
        if custom_extract_password:
            overrides["custom_extract_password"] = custom_extract_password
        if bool(item.get("custom_group_folder")):
            overrides["custom_group_folder"] = True
        return overrides

    def _normalize_url(self, raw_url: str) -> str:
        url = str(raw_url or "").strip()
        if not url:
            raise HttpDownloadError("下载链接不能为空")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise HttpDownloadError("仅支持 http/https 下载链接")
        if not parsed.hostname:
            raise HttpDownloadError("下载链接缺少主机名")
        return url

    def _is_private_ip(self, address: str) -> bool:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)

    async def _resolve_host_ips(self, host: str) -> List[str]:
        loop = asyncio.get_running_loop()

        def resolve() -> List[str]:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            result = []
            for info in infos:
                addr = info[4][0]
                if addr not in result:
                    result.append(addr)
            return result

        return await loop.run_in_executor(None, resolve)

    async def validate_url(self, raw_url: str, *, allow_private_network: Optional[bool] = None) -> str:
        url = self._normalize_url(raw_url)
        parsed = urlparse(url)
        cfg = self._config()
        allow_private = bool(getattr(cfg, "allow_private_network", False) if allow_private_network is None else allow_private_network)
        host = parsed.hostname or ""
        if not allow_private:
            if self._is_private_ip(host):
                raise HttpDownloadError("默认禁止下载内网 / 本机地址，请在设置页显式允许内网 URL")
            try:
                ips = await self._resolve_host_ips(host)
            except Exception as exc:
                raise HttpDownloadError(f"解析下载域名失败: {exc}") from exc
            blocked = [ip for ip in ips if self._is_private_ip(ip)]
            if blocked:
                raise HttpDownloadError("默认禁止下载解析到内网 / 本机地址的 URL")
        return url

    def _parse_pikpak_pass_code(self, url: str) -> str:
        raw_text = str(url or "")
        parsed = urlparse(raw_text)
        query = {}
        if parsed.query:
            from urllib.parse import parse_qs

            query = parse_qs(parsed.query)
        for key in ("pwd", "pass_code", "passcode", "password", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        fragment = parsed.fragment or ""
        for pattern in (r"(?:pwd|pass_code|passcode|password|code)=([^&]+)", r"(?:提取码|密码)[:：\s]*([A-Za-z0-9]{4,8})"):
            match = re.search(pattern, fragment, re.IGNORECASE)
            if match:
                return unquote(match.group(1)).strip()
        for pattern in (
            r"(?:pwd|pass_code|passcode|password|code)\s*[=:：]\s*([A-Za-z0-9]{4,12})",
            r"(?:提取码|访问码|密[码碼])[:：\s]*([A-Za-z0-9]{4,12})",
        ):
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                return unquote(match.group(1)).strip()
        return ""

    def _pikpak_share_url(self, value: str) -> str:
        text = str(value or "").strip()
        match = re.search(r"https?://[^\s<>'\"）)]+", text)
        if match:
            text = match.group(0).rstrip(".,，。;；")
        return text

    async def _save_pikpak_token_callback(self, client, *, account: Optional[PikPakAccount] = None, **_kwargs) -> None:
        token = str(getattr(client, "encoded_token", "") or "").strip()
        if not token:
            return
        try:
            from ..config.settings import save_config

            if not account or account.legacy:
                await asyncio.to_thread(save_config, {"http_downloader": {"pikpak_encoded_token": token}})
                return

            cfg = self._config()
            next_accounts = []
            updated = False
            for index, raw in enumerate(list(getattr(cfg, "pikpak_accounts", []) or [])):
                data = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw or {})
                raw_id = self._pikpak_account_id(data, index)
                if raw_id == account.id:
                    data["id"] = account.id
                    data["encoded_token"] = token
                    updated = True
                next_accounts.append(data)
            if updated:
                await asyncio.to_thread(save_config, {"http_downloader": {"pikpak_accounts": next_accounts}})
        except Exception as exc:
            logger.warning("[PikPak] 保存刷新后的 token 失败: %s", sanitize_http_download_error(exc))

    async def _pikpak_client(self, account_id: str = "", *, account: Optional[PikPakAccount] = None):
        cfg = self._config()
        if not self._pikpak_enabled():
            raise HttpDownloadError("PikPak 下载未启用，请先在设置页启用并配置账号")
        account = account or self._select_pikpak_account(account_id)
        token = "" if account.encoded_token == "********" else account.encoded_token
        username = account.username
        password = "" if account.password == "********" else account.password
        if not token and not (username and password):
            raise HttpDownloadError(f"PikPak 账号 {account.label} 未配置账号密码或 token")
        try:
            from pikpakapi import PikPakApi
            import httpx
        except Exception as exc:
            raise HttpDownloadError("后端缺少 pikpakapi 依赖，请重新安装 backend/requirements.txt") from exc
        httpx_args: Dict[str, Any] = {
            "timeout": max(10, int(getattr(cfg, "timeout_seconds", 60) or 60)),
        }
        proxy = self._proxy_url("pikpak")
        if proxy:
            async_client_params = inspect.signature(httpx.AsyncClient).parameters
            httpx_args["proxy" if "proxy" in async_client_params else "proxies"] = proxy
        kwargs = {
            "encoded_token": token or None,
            "username": username or None,
            "password": password or None,
            "device_id": account.device_id or None,
            "httpx_client_args": httpx_args,
            "request_max_retries": max(1, int(getattr(cfg, "retry_count", 5) or 5)),
            "request_initial_backoff": max(0.5, float(getattr(cfg, "retry_wait_seconds", 5) or 5)),
            "token_refresh_callback": lambda callback_client, **kwargs: self._save_pikpak_token_callback(callback_client, account=account, **kwargs),
        }
        client = PikPakApi(**kwargs)
        setattr(client, "_kikoeru_pikpak_account", account)
        if not token:
            try:
                await client.login()
                await self._save_pikpak_token_callback(client, account=account)
            except Exception as exc:
                raise self._pikpak_error(exc, f"登录账号 {account.label}") from exc
        else:
            await self._ensure_pikpak_logged_in(client, account)
        return client

    async def _ensure_pikpak_logged_in(self, client, account: PikPakAccount) -> None:
        """让检测/状态接口把旧 token 失效和密码登录失败区分开。"""
        try:
            if hasattr(client, "user_info"):
                await client.user_info()
            elif hasattr(client, "get_quota_info"):
                await client.get_quota_info()
            else:
                return
        except Exception as exc:
            if not self._is_pikpak_token_error(exc) or not account.username or not account.password or account.password == "********":
                raise self._pikpak_error(exc, f"校验账号 {account.label}") from exc
            with contextlib.suppress(Exception):
                setattr(client, "encoded_token", None)
            try:
                await client.login()
                await self._save_pikpak_token_callback(client, account=account)
            except Exception as login_exc:
                raise self._pikpak_error(login_exc, f"重新登录账号 {account.label}") from login_exc

    async def _refresh_pikpak_login_with_password(self, client, account: PikPakAccount, *, stage: str) -> None:
        if not account.username or not account.password or account.password == "********":
            raise HttpDownloadError(
                f"PikPak {stage}失败: 旧 token 已失效，但账号 {account.label} 没有可用密码，请重新输入密码保存后重试。"
            )
        with contextlib.suppress(Exception):
            setattr(client, "encoded_token", None)
        try:
            await client.login()
            await self._save_pikpak_token_callback(client, account=account)
        except Exception as login_exc:
            raise self._pikpak_error(login_exc, f"重新登录账号 {account.label}") from login_exc

    async def _pikpak_client_with_account(self, account_id: str = "", *, account: Optional[PikPakAccount] = None) -> tuple[Any, PikPakAccount]:
        selected = account or self._select_pikpak_account(account_id)
        client = await self._pikpak_client(account=selected)
        return client, selected

    async def _close_pikpak_client(self, client) -> None:
        with contextlib.suppress(Exception):
            await client.httpx_client.aclose()

    def _int_value(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _pikpak_file_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("id") or item.get("file_id") or "").strip()

    def _normalize_pikpak_file_row(self, item: Dict[str, Any], *, parent_id: str = "") -> Dict[str, Any]:
        return {
            "id": self._pikpak_file_id(item),
            "name": str(item.get("name") or item.get("file_name") or "").strip(),
            "kind": str(item.get("kind") or item.get("mime_type") or item.get("type") or ""),
            "is_folder": self._pikpak_is_folder(item),
            "size_bytes": self._pikpak_file_size(item),
            "parent_id": parent_id,
            "created_time": item.get("created_time") or item.get("created_at") or "",
            "modified_time": item.get("modified_time") or item.get("updated_at") or "",
            "phase": item.get("phase") or "",
        }

    def _normalize_pikpak_quota(self, data: Dict[str, Any]) -> Dict[str, Any]:
        quota = data.get("quota") if isinstance(data, dict) else {}
        if not isinstance(quota, dict):
            quota = {}
        limit = self._int_value(quota.get("limit"))
        usage = self._int_value(quota.get("usage"))
        trash = self._int_value(quota.get("usage_in_trash"))
        remaining = max(0, limit - usage) if limit > 0 else 0
        return {
            "limit_bytes": limit,
            "usage_bytes": usage,
            "usage_in_trash_bytes": trash,
            "remaining_bytes": remaining,
            "used_percent": round((usage / limit) * 100, 2) if limit > 0 else 0,
        }

    async def _pikpak_transfer_parent_id(self, client, *, create: bool = False, account: Optional[PikPakAccount] = None) -> str:
        account = account or getattr(client, "_kikoeru_pikpak_account", None)
        transfer_dir = str(getattr(account, "transfer_dir", "") or "").strip()
        if not transfer_dir:
            transfer_dir = str(getattr(self._config(), "pikpak_transfer_dir", "") or "/KikoeruManager").strip() or "/KikoeruManager"
        try:
            path_rows = await client.path_to_id(transfer_dir, create=create)
        except Exception as exc:
            raise self._pikpak_error(exc, "定位转存目录") from exc
        if not path_rows:
            if create:
                raise HttpDownloadError(f"PikPak 转存目录创建失败: {transfer_dir}")
            return ""
        return str(path_rows[-1].get("id") or "").strip()

    async def _pikpak_account_status(self, account: PikPakAccount, *, include_files: bool = False, limit: int = 100) -> Dict[str, Any]:
        client = await self._pikpak_client(account=account)
        try:
            quota = {}
            transfer_quota = {}
            vip = {}
            await self._ensure_pikpak_logged_in(client, account)
            try:
                quota = self._normalize_pikpak_quota(await client.get_quota_info())
            except Exception as exc:
                if self._is_pikpak_token_error(exc):
                    await self._refresh_pikpak_login_with_password(client, account, stage=f"读取账号 {account.label} 容量")
                    try:
                        quota = self._normalize_pikpak_quota(await client.get_quota_info())
                    except Exception as retry_exc:
                        raise self._pikpak_error(retry_exc, f"读取账号 {account.label} 容量") from retry_exc
                else:
                    raise self._pikpak_error(exc, f"读取账号 {account.label} 容量") from exc
            with contextlib.suppress(Exception):
                transfer_quota = await client.get_transfer_quota()
            with contextlib.suppress(Exception):
                vip = await client.vip_info()
            result = self._pikpak_public_status(
                account,
                success=True,
                ready=True,
                quota=quota,
                transfer_quota=transfer_quota,
                vip=vip,
                source="live",
                cached=False,
                updated_at=datetime.now(),
            )
            self._pikpak_status_cache_write(result, account, source="live")
            if include_files:
                listing = await self.pikpak_transfer_files(client=client, account=account, limit=limit)
                result["files"] = listing.get("files") or []
                result["folder_id"] = listing.get("folder_id") or ""
            return result
        finally:
            await self._close_pikpak_client(client)

    async def pikpak_status(self, *, include_files: bool = False, limit: int = 100, account_id: str = "", force_refresh: bool = False) -> Dict[str, Any]:
        accounts = self._pikpak_accounts(include_disabled=True)
        enabled_accounts = [item for item in accounts if item.enabled]
        if not self._pikpak_enabled():
            return {"success": True, "enabled": False, "ready": False, "accounts": [self._pikpak_account_public(item) for item in accounts]}
        if account_id:
            account = self._select_pikpak_account(account_id)
            if not force_refresh and not include_files:
                cached = self._pikpak_status_cache_read(account)
                if cached:
                    return cached
            try:
                return await self._pikpak_account_status(account, include_files=include_files, limit=limit)
            except Exception as exc:
                if not force_refresh and not include_files:
                    stale = self._pikpak_status_cache_read(account, require_fresh=False)
                    if stale:
                        stale["stale"] = True
                        stale["message"] = f"缓存已过期，刷新失败: {self._sanitize_error(exc)}"
                        return stale
                raise
        if not enabled_accounts:
            raise HttpDownloadError("PikPak 未配置可用账号或 token")
        self._pikpak_status_cache_delete_missing({item.id for item in accounts})
        statuses = []
        for account in enabled_accounts:
            if not force_refresh and not include_files:
                cached = self._pikpak_status_cache_read(account)
                if cached:
                    statuses.append(cached)
                    continue
            try:
                statuses.append(await self._pikpak_account_status(account, include_files=include_files, limit=limit))
            except Exception as exc:
                if not force_refresh and not include_files:
                    stale = self._pikpak_status_cache_read(account, require_fresh=False)
                    if stale:
                        stale["stale"] = True
                        stale["message"] = f"缓存已过期，刷新失败: {self._sanitize_error(exc)}"
                        statuses.append(stale)
                        continue
                status = self._pikpak_public_status(
                    account,
                    success=False,
                    ready=False,
                    quota={},
                    message=self._sanitize_error(exc),
                    source="live",
                    cached=False,
                    updated_at=datetime.now(),
                )
                status["files"] = []
                self._pikpak_status_cache_write(status, account, source="live")
                statuses.append(status)
        return self._pikpak_merge_statuses(statuses)

    async def test_pikpak_account(self, payload: Optional[Dict[str, Any]] = None, *, account_id: str = "") -> Dict[str, Any]:
        data = dict(payload or {})
        use_saved = bool(data.get("use_saved"))
        if account_id and use_saved:
            return await self._pikpak_account_status(self._select_pikpak_account(account_id), include_files=False, limit=1)

        # 前端配置里的密码/token 可能是脱敏占位符；这种情况下回退到已保存账号。
        password = str(data.get("password") or "").strip()
        encoded_token = str(data.get("encoded_token") or "").strip()
        masked_secret = password == "********" or encoded_token == "********"
        if account_id and masked_secret:
            return await self._pikpak_account_status(self._select_pikpak_account(account_id), include_files=False, limit=1)

        account = self._pikpak_account_from_payload(data, fallback_id=account_id)
        if account.password and account.password != "********":
            account.encoded_token = ""
        if not account.username and not account.encoded_token:
            raise HttpDownloadError("PikPak 账号缺少邮箱/手机号")
        if not account.encoded_token and not account.password:
            raise HttpDownloadError(f"PikPak 账号 {account.label} 缺少密码")
        return await self._pikpak_account_status(account, include_files=False, limit=1)

    async def pikpak_transfer_files(
        self,
        *,
        client=None,
        account: Optional[PikPakAccount] = None,
        account_id: str = "",
        limit: int = 100,
        root: bool = False,
        parent_id: str = "",
    ) -> Dict[str, Any]:
        owns_client = client is None
        if client is None:
            client, account = await self._pikpak_client_with_account(account_id)
        account = account or getattr(client, "_kikoeru_pikpak_account", None)
        requested_parent_id = str(parent_id or "").strip()
        try:
            folder_id = requested_parent_id or ("" if root else await self._pikpak_transfer_parent_id(client, create=False, account=account))
            if not folder_id:
                if root:
                    folder_id = None
                else:
                    return {"success": True, "folder_id": "", "files": [], "message": "转存目录还不存在"}
            if not root and not folder_id:
                return {"success": True, "folder_id": "", "files": [], "message": "转存目录还不存在"}
            files: List[Dict[str, Any]] = []
            next_page_token = None
            while len(files) < max(1, min(500, int(limit or 100))):
                data = await client.file_list(size=min(100, max(1, int(limit or 100)) - len(files)), parent_id=folder_id, next_page_token=next_page_token)
                for item in list((data or {}).get("files") or []):
                    if isinstance(item, dict):
                        files.append(self._normalize_pikpak_file_row(item, parent_id=str(folder_id or "")))
                next_page_token = (data or {}).get("next_page_token")
                if not next_page_token:
                    break
            account_public = self._pikpak_account_public(account) if account else {}
            return {
                "success": True,
                "folder_id": folder_id or "",
                "parent_id": requested_parent_id,
                "files": files,
                "message": "",
                "root": root,
                "account": account_public,
                "account_id": account_public.get("id", ""),
            }
        except Exception as exc:
            if isinstance(exc, HttpDownloadError):
                raise
            raise self._pikpak_error(exc, "读取转存目录") from exc
        finally:
            if owns_client:
                await self._close_pikpak_client(client)

    async def _collect_pikpak_delete_ids(self, client, file_ids: List[str]) -> List[str]:
        """Expand folder ids before delete so folder cleanup frees quota reliably."""
        result: List[tuple[int, str]] = []
        seen: set[str] = set()

        async def walk(parent_id: str, depth: int = 0) -> None:
            if not parent_id or parent_id in seen or depth > 16:
                return
            seen.add(parent_id)
            children: List[Dict[str, Any]] = []
            next_page_token = None
            try:
                while True:
                    data = await client.file_list(size=100, parent_id=parent_id, next_page_token=next_page_token)
                    rows = [item for item in list((data or {}).get("files") or []) if isinstance(item, dict)]
                    children.extend(rows)
                    next_page_token = (data or {}).get("next_page_token")
                    if not next_page_token:
                        break
            except Exception:
                children = []
            for child in children:
                child_id = self._pikpak_file_id(child)
                if child_id:
                    await walk(child_id, depth + 1)
            result.append((depth, parent_id))

        for file_id in file_ids:
            await walk(file_id, 0)
        return [file_id for _depth, file_id in sorted(result, key=lambda item: item[0], reverse=True)]

    async def _list_pikpak_children(
        self,
        client,
        *,
        parent_id: Optional[str],
        trashed: bool = False,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        next_page_token = None
        filters = {"trashed": {"eq": bool(trashed)}}
        while True:
            data = await client.file_list(
                size=100,
                parent_id=parent_id,
                next_page_token=next_page_token,
                additional_filters=filters,
            )
            rows.extend([item for item in list((data or {}).get("files") or []) if isinstance(item, dict)])
            next_page_token = (data or {}).get("next_page_token")
            if not next_page_token:
                break
        return rows

    async def _update_pikpak_quota_cache(self, client, account: PikPakAccount, *, source: str) -> Dict[str, Any]:
        quota = {}
        with contextlib.suppress(Exception):
            quota = self._normalize_pikpak_quota(await client.get_quota_info())
        if quota:
            self._pikpak_status_cache_write(
                self._pikpak_public_status(
                    account,
                    success=True,
                    ready=True,
                    quota=quota,
                    source=source,
                    cached=False,
                    updated_at=datetime.now(),
                ),
                account,
                source=source,
            )
        return quota

    async def _delete_pikpak_ids_forever(self, client, ids: List[str]) -> int:
        file_ids = [str(item or "").strip() for item in ids or [] if str(item or "").strip()]
        deleted_count = 0
        for index in range(0, len(file_ids), 100):
            chunk = file_ids[index:index + 100]
            if not chunk:
                continue
            await client.delete_forever(chunk)
            deleted_count += len(chunk)
        return deleted_count

    async def delete_pikpak_transfer_items(self, ids: List[str], *, permanent: bool = False, account_id: str = "") -> Dict[str, Any]:
        file_ids = [str(item or "").strip() for item in ids or [] if str(item or "").strip()]
        if not file_ids:
            raise HttpDownloadError("请选择要删除的 PikPak 转存文件")
        account = self._select_pikpak_account(account_id)
        client = await self._pikpak_client(account=account)
        try:
            delete_ids = await self._collect_pikpak_delete_ids(client, file_ids)
            if permanent:
                result = await client.delete_forever(delete_ids)
            else:
                result = await client.delete_to_trash(delete_ids)
            quota = await self._update_pikpak_quota_cache(client, account, source="delete")
            return {
                "success": True,
                "deleted_count": len(delete_ids),
                "requested_count": len(file_ids),
                "permanent": permanent,
                "result": result,
                "quota": quota,
                "account": self._pikpak_account_public(account),
                "account_id": account.id,
            }
        except Exception as exc:
            if isinstance(exc, HttpDownloadError):
                raise
            raise self._pikpak_error(exc, "删除转存文件") from exc
        finally:
            await self._close_pikpak_client(client)

    async def clear_pikpak_account_transfer_space(self, *, account_id: str = "") -> Dict[str, Any]:
        account = self._select_pikpak_account(account_id)
        client = await self._pikpak_client(account=account)
        root_deleted_count = 0
        trash_deleted_count = 0
        try:
            root_rows = await self._list_pikpak_children(client, parent_id=None, trashed=False)
            root_ids = [self._pikpak_file_id(item) for item in root_rows if self._pikpak_file_id(item)]
            if root_ids:
                delete_ids = await self._collect_pikpak_delete_ids(client, root_ids)
                root_deleted_count = await self._delete_pikpak_ids_forever(client, delete_ids)

            trash_rows = await self._list_pikpak_children(client, parent_id="*", trashed=True)
            trash_ids = [self._pikpak_file_id(item) for item in trash_rows if self._pikpak_file_id(item)]
            if trash_ids:
                trash_deleted_count = await self._delete_pikpak_ids_forever(client, trash_ids)

            quota = await self._update_pikpak_quota_cache(client, account, source="clear")
            return {
                "success": True,
                "account": self._pikpak_account_public(account),
                "account_id": account.id,
                "deleted_count": root_deleted_count + trash_deleted_count,
                "root_deleted_count": root_deleted_count,
                "trash_deleted_count": trash_deleted_count,
                "quota": quota,
            }
        except Exception as exc:
            if isinstance(exc, HttpDownloadError):
                raise
            raise self._pikpak_error(exc, f"清空账号 {account.label} 转存空间") from exc
        finally:
            await self._close_pikpak_client(client)

    async def clear_all_pikpak_transfer_space(self) -> Dict[str, Any]:
        accounts = self._pikpak_accounts()
        if not self._pikpak_enabled():
            raise HttpDownloadError("PikPak 未启用")
        if not accounts:
            raise HttpDownloadError("PikPak 未配置可用账号或 token")

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for account in accounts:
            try:
                results.append(await self.clear_pikpak_account_transfer_space(account_id=account.id))
            except Exception as exc:
                errors.append({
                    "account": self._pikpak_account_public(account),
                    "account_id": account.id,
                    "message": self._sanitize_error(exc),
                })

        total_deleted = sum(int(item.get("deleted_count") or 0) for item in results)
        total_root_deleted = sum(int(item.get("root_deleted_count") or 0) for item in results)
        total_trash_deleted = sum(int(item.get("trash_deleted_count") or 0) for item in results)
        return {
            "success": not errors,
            "partial_success": bool(results) and bool(errors),
            "account_count": len(accounts),
            "cleared_account_count": len(results),
            "failed_account_count": len(errors),
            "deleted_count": total_deleted,
            "root_deleted_count": total_root_deleted,
            "trash_deleted_count": total_trash_deleted,
            "accounts": results,
            "errors": errors,
        }

    def _pikpak_cleanup_targets_from_rows(self, rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        targets: Dict[str, List[str]] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("source") or "").strip().lower() != "pikpak":
                continue
            if str(row.get("status") or "").strip().lower() != "completed":
                continue
            cleanup_id = str(row.get("pikpak_cleanup_file_id") or "").strip()
            if not cleanup_id and bool(row.get("pikpak_materialized")):
                cleanup_id = str(row.get("download_file_id") or "").strip()
            if not cleanup_id:
                continue
            account_id = str(row.get("pikpak_account_id") or "").strip()
            bucket = targets.setdefault(account_id, [])
            if cleanup_id not in bucket:
                bucket.append(cleanup_id)
        return targets

    async def cleanup_completed_pikpak_transfer_items(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        targets = self._pikpak_cleanup_targets_from_rows(rows)
        if not targets:
            return {
                "success": True,
                "status": "skipped",
                "requested_count": 0,
                "deleted_count": 0,
                "accounts": [],
                "errors": [],
            }

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for account_id, file_ids in targets.items():
            try:
                results.append(
                    await self.delete_pikpak_transfer_items(
                        file_ids,
                        permanent=True,
                        account_id=account_id,
                    )
                )
            except Exception as exc:
                errors.append({
                    "account_id": account_id,
                    "requested_count": len(file_ids),
                    "file_ids": file_ids,
                    "message": self._sanitize_error(exc),
                })

        deleted_count = sum(int(item.get("deleted_count") or 0) for item in results)
        requested_count = sum(len(item) for item in targets.values())
        status = "completed" if results and not errors else ("partial_failed" if results else "failed")
        return {
            "success": not errors,
            "status": status,
            "requested_count": requested_count,
            "deleted_count": deleted_count,
            "accounts": results,
            "errors": errors,
        }

    def _direct_link_preview_provider(self, raw_url: str) -> str:
        source = self._provider_source(raw_url)
        return source if source in {"gofile", "onedrive", "google_drive"} else "http"

    def _is_direct_download_item(self, item: Dict[str, Any]) -> bool:
        if item.get("preview_only"):
            return False
        source = str(item.get("source") or "http")
        if source == "transferit":
            return False
        return bool(str(item.get("url") or "").strip())

    def _transferit_api_client(self):
        try:
            import transferit
        except Exception as exc:
            raise HttpDownloadError("后端缺少 transferit-py 依赖，请重新安装 backend/requirements.txt") from exc

        Transferit = getattr(transferit, "Transferit")
        MegaAPI = getattr(transferit, "MegaAPI", None)
        if MegaAPI is None:
            return Transferit()

        cfg = self._config()
        timeout_seconds = max(30, int(getattr(cfg, "timeout_seconds", 60) or 60))
        api = MegaAPI(timeout=timeout_seconds)
        proxy = self._proxy_url("transferit") or None
        if proxy and hasattr(api, "_http"):
            try:
                api._http.close()
            except Exception:
                pass
            api._http = httpx.Client(
                timeout=httpx.Timeout(timeout_seconds, connect=max(10, int(getattr(cfg, "connect_timeout_seconds", 15) or 15))),
                http2=False,
                proxy=proxy,
                headers={"User-Agent": f"KikoeruManager transferit-py"},
                trust_env=True,
            )
        return Transferit(api=api)

    def _transferit_row_identity(self, item: Dict[str, Any]) -> str:
        return (
            str(item.get("transferit_node_handle") or "").strip()
            or str(item.get("relative_path") or "").strip()
            or str(item.get("filename") or item.get("name") or "").strip()
        )

    def _close_transferit_client(self, client) -> None:
        if not client:
            return
        with contextlib.suppress(Exception):
            client.close()
        api = getattr(client, "api", None)
        if getattr(client, "_owns_api", True) is False and api and hasattr(api, "close"):
            with contextlib.suppress(Exception):
                api.close()

    async def _fetch_json_once(self, url: str, *, method: str = "GET", headers: Optional[Dict[str, str]] = None, platform: Any = "http") -> Dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=max(20, int(getattr(self._config(), "timeout_seconds", 60) or 60)), connect=10)
        proxy = self._proxy_url(platform) or None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            request_method = str(method or "GET").upper()
            request = session.post if request_method == "POST" else session.get
            async with request(url, headers=headers or {}, allow_redirects=True, proxy=proxy) as response:
                body = await response.text()
                if response.status >= 400:
                    raise HttpDownloadError(f"源站 API 返回 HTTP {response.status}: {body[:160]}")
                try:
                    data = json.loads(body)
                except Exception as exc:
                    raise HttpDownloadError("源站 API 返回不是 JSON") from exc
        if not isinstance(data, dict):
            raise HttpDownloadError("源站 API 返回结构异常")
        return data

    async def _fetch_json(self, url: str, *, method: str = "GET", headers: Optional[Dict[str, str]] = None, platform: Any = "http") -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                return await self._fetch_json_once(url, method=method, headers=headers, platform=platform)
            except HttpDownloadError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1))
        raise HttpDownloadError(f"源站 API 请求失败: {self._sanitize_error(last_error)}") from last_error

    def _gofile_content_id_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        match = re.search(r"/(?:d|contents?)/([^/?#]+)", parsed.path, re.IGNORECASE)
        if match:
            return match.group(1)
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[-1]
        raise HttpDownloadError("Gofile 分享链接格式不正确")

    def _gofile_token(self) -> str:
        return str(getattr(self._config(), "gofile_token", "") or "").strip()

    def _gofile_website_token(self, token: str) -> str:
        slot = str(int(time.time() // 14400))
        payload = f"{_GOFILE_USER_AGENT}::{_GOFILE_LANGUAGE}::{token}::{slot}::{_GOFILE_WEBSITE_TOKEN_SALT}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _gofile_guest_token(self) -> str:
        cached_token, expires_at = self._gofile_guest_token_cache
        if cached_token and expires_at > time.time():
            return cached_token
        async with self._gofile_guest_token_lock:
            cached_token, expires_at = self._gofile_guest_token_cache
            if cached_token and expires_at > time.time():
                return cached_token
            data = await self._fetch_json(
                "https://api.gofile.io/accounts",
                method="POST",
                headers={"User-Agent": _GOFILE_USER_AGENT, "X-BL": _GOFILE_LANGUAGE},
                platform="gofile",
            )
            if str(data.get("status") or "").lower() != "ok":
                raise HttpDownloadError(f"Gofile 创建访客账号失败: {data.get('status') or 'unknown'}")
            token = str((data.get("data") or {}).get("token") or "").strip()
            if not token:
                raise HttpDownloadError("Gofile 未返回访客 token")
            self._gofile_guest_token_cache = (token, time.time() + 6 * 60 * 60)
            return token

    def _gofile_password(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        query = parse_qs(parsed.query or "")
        for key in ("password", "pwd", "pass", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        fragment = parsed.fragment or ""
        match = re.search(r"(?:password|pwd|pass|code)=([^&]+)", fragment, re.IGNORECASE)
        return unquote(match.group(1)).strip() if match else ""

    def _gofile_public_token(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        query = parse_qs(parsed.query or "")
        for key in ("publicToken", "public_token"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        return ""

    async def _collect_gofile_files(self, raw_url: str) -> Dict[str, Any]:
        content_id = self._gofile_content_id_from_url(raw_url)
        token = self._gofile_token() or await self._gofile_guest_token()
        params: Dict[str, str] = {}
        public_token = self._gofile_public_token(raw_url)
        if public_token:
            params["publicToken"] = public_token
        password = self._gofile_password(raw_url)
        if password:
            params["password"] = password
        api_url = f"https://api.gofile.io/contents/{content_id}"
        if params:
            api_url = f"{api_url}?{urlencode(params)}"
        data = await self._fetch_json(
            api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Website-Token": self._gofile_website_token(token),
                "X-BL": _GOFILE_LANGUAGE,
                "User-Agent": _GOFILE_USER_AGENT,
            },
            platform="gofile",
        )
        if str(data.get("status") or "").lower() != "ok":
            raise HttpDownloadError(f"Gofile 解析失败: {data.get('status') or 'unknown'}")
        root = data.get("data") or {}
        if not isinstance(root, dict):
            raise HttpDownloadError("Gofile 返回数据结构异常")
        files: List[Dict[str, Any]] = []

        def walk(node: Dict[str, Any], prefix: str = "") -> None:
            if not isinstance(node, dict):
                return
            kind = str(node.get("type") or "").lower()
            if kind == "folder":
                folder_name = self._sanitize_filename(node.get("name") or "", fallback="")
                next_prefix = "/".join([part for part in (prefix, folder_name) if part])
                children = node.get("children") or {}
                if isinstance(children, dict):
                    for child in children.values():
                        if isinstance(child, dict):
                            walk(child, next_prefix)
                elif isinstance(children, list):
                    for child in children:
                        if isinstance(child, dict):
                            walk(child, next_prefix)
                return
            link = str(node.get("link") or node.get("downloadPage") or "").strip()
            if not link:
                return
            name = self._sanitize_filename(node.get("name") or node.get("filename") or "gofile-file")
            files.append({
                "source": "gofile",
                "share_url": self._mask_url(raw_url),
                "url": link,
                "masked_url": self._mask_url(link),
                "name": name,
                "filename": name,
                "relative_dir": prefix.strip("/"),
                "size_bytes": int(node.get("size") or 0),
                "content_id": str(node.get("id") or content_id),
                "headers": {"Cookie": f"accountToken={token}"},
                "aria2_header": [f"Cookie: accountToken={token}"],
            })

        walk(root)
        return {"files": files, "token_configured": bool(self._gofile_token())}

    def _google_drive_file_id_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        match = re.search(r"/file/d/([^/]+)", parsed.path)
        if match:
            return match.group(1)
        query = parse_qs(parsed.query or "")
        for key in ("id", "docid"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        match = re.search(r"/(?:document|spreadsheets|presentation)/d/([^/]+)", parsed.path)
        if match:
            return match.group(1)
        raise HttpDownloadError("Google Drive 分享链接缺少文件 ID")

    def _google_drive_folder_id_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        match = re.search(r"/(?:drive/)?folders/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)
        query = parse_qs(parsed.query or "")
        for key in ("folder_id", "folderId"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        return ""

    def _google_drive_is_folder_url(self, raw_url: str) -> bool:
        return bool(self._google_drive_folder_id_from_url(raw_url))

    def _google_drive_direct_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if (parsed.hostname or "").lower() == "drive.usercontent.google.com":
            return raw_url
        file_id = self._google_drive_file_id_from_url(raw_url)
        return f"https://drive.usercontent.google.com/download?{urlencode({'id': file_id, 'export': 'download'})}"

    def _google_drive_direct_url_from_id(self, file_id: str) -> str:
        return f"https://drive.usercontent.google.com/download?{urlencode({'id': str(file_id or '').strip(), 'export': 'download'})}"

    def _google_drive_api_download_url_from_id(self, file_id: str, resource_key: str = "") -> str:
        query = {
            "alt": "media",
            "supportsAllDrives": "true",
            "acknowledgeAbuse": "true",
        }
        if str(resource_key or "").strip():
            query["resourceKey"] = str(resource_key or "").strip()
        return f"https://www.googleapis.com/drive/v3/files/{str(file_id or '').strip()}?{urlencode(query)}"

    def _google_drive_resource_key_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        query = parse_qs(parsed.query or "")
        for key in ("resourcekey", "resourceKey"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        fragment_query = parse_qs(parsed.fragment or "")
        for key in ("resourcekey", "resourceKey"):
            values = fragment_query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        match = re.search(r"(?:resourcekey|resourceKey)=([^&#?]+)", raw_url)
        return unquote(match.group(1)) if match else ""

    def _google_drive_oauth_enabled(self) -> bool:
        cfg = self._config()
        oauth_client = resolve_google_drive_oauth_client(
            config=cfg,
            mode=getattr(cfg, "google_drive_oauth_client_mode", "builtin"),
        )
        return bool(
            getattr(cfg, "google_drive_oauth_enabled", False)
            and oauth_client
            and str(getattr(cfg, "google_drive_refresh_token", "") or "").strip()
        )

    @staticmethod
    def _google_drive_oauth_refresh_expired(status: int, body: str) -> bool:
        text = str(body or "")
        error = ""
        description = ""
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                error = str(data.get("error") or "").strip().lower()
                description = str(data.get("error_description") or data.get("errorMessage") or "").strip().lower()
        except Exception:
            description = text.lower()
        return (
            int(status or 0) in {400, 401}
            and (
                error == "invalid_grant"
                or "expired" in description
                or "revoked" in description
                or "refresh token" in description and "invalid" in description
            )
        )

    def _clear_google_drive_oauth_authorization(self) -> None:
        self._google_drive_access_token_cache = ("", 0.0)
        try:
            save_config({
                "http_downloader": {
                    "google_drive_refresh_token": "",
                    "google_drive_oauth_expired": True,
                }
            })
        except Exception:
            logger.warning("[HTTP下载] Google Drive OAuth 过期状态写入配置失败", exc_info=True)

    async def _google_drive_access_token(self, *, force_refresh: bool = False) -> str:
        if not self._google_drive_oauth_enabled():
            raise HttpDownloadError("Google Drive OAuth 未配置")
        cached_token, expires_at = self._google_drive_access_token_cache
        if cached_token and not force_refresh and time.time() < expires_at - 60:
            return cached_token
        async with self._google_drive_access_token_lock:
            cached_token, expires_at = self._google_drive_access_token_cache
            if cached_token and not force_refresh and time.time() < expires_at - 60:
                return cached_token
            cfg = self._config()
            oauth_client = resolve_google_drive_oauth_client(
                config=cfg,
                mode=getattr(cfg, "google_drive_oauth_client_mode", "builtin"),
            )
            if not oauth_client:
                raise HttpDownloadError(google_drive_oauth_client_missing_message(
                    getattr(cfg, "google_drive_oauth_client_mode", "builtin")
                ))
            payload = {
                "client_id": oauth_client.client_id,
                "refresh_token": str(getattr(cfg, "google_drive_refresh_token", "") or "").strip(),
                "grant_type": "refresh_token",
            }
            if oauth_client.client_secret:
                payload["client_secret"] = oauth_client.client_secret
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            proxy = resolve_google_drive_oauth_proxy_url(get_config()) if self._proxy_enabled_for("google_drive") else ""
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("https://oauth2.googleapis.com/token", data=payload, proxy=proxy) as response:
                    body = await response.text()
                    if response.status >= 400:
                        if self._google_drive_oauth_refresh_expired(response.status, body):
                            self._clear_google_drive_oauth_authorization()
                            raise HttpDownloadError("Google Drive OAuth 授权已过期或被撤销，请在设置页重新进行 Google 登录")
                        raise HttpDownloadError(f"Google Drive OAuth 刷新 token 失败: HTTP {response.status}: {body[:160]}")
                    try:
                        data = json.loads(body)
                    except Exception as exc:
                        raise HttpDownloadError("Google Drive OAuth 返回不是 JSON") from exc
            token = str(data.get("access_token") or "").strip()
            if not token:
                raise HttpDownloadError("Google Drive OAuth 未返回 access_token")
            expires_in = int(data.get("expires_in") or 3600)
            self._google_drive_access_token_cache = (token, time.time() + max(60, expires_in))
            return token

    def _google_drive_api_headers(self, token: str, *, resource_keys: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": _GOFILE_USER_AGENT,
        }
        pairs = [
            f"{file_id}/{resource_key}"
            for file_id, resource_key in (resource_keys or {}).items()
            if str(file_id or "").strip() and str(resource_key or "").strip()
        ]
        if pairs:
            headers["X-Goog-Drive-Resource-Keys"] = ",".join(pairs)
        return headers

    def _google_drive_api_error_message(self, status: int, body: str) -> str:
        message = ""
        try:
            data = json.loads(body or "{}")
            error = data.get("error") if isinstance(data, dict) else {}
            if isinstance(error, dict):
                message = str(error.get("message") or "").strip()
        except Exception:
            message = ""
        return f"Google Drive API 返回 HTTP {status}: {message or str(body or '')[:160]}"

    async def _google_drive_api_json(self, url: str, *, resource_keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        last_body = ""
        for attempt in range(2):
            token = await self._google_drive_access_token(force_refresh=attempt > 0)
            headers = self._google_drive_api_headers(token, resource_keys=resource_keys)
            timeout = aiohttp.ClientTimeout(total=max(20, int(getattr(self._config(), "timeout_seconds", 60) or 60)), connect=10)
            proxy = self._proxy_url("google_drive") or None
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=True, proxy=proxy) as response:
                    body = await response.text(errors="ignore")
                    last_body = body
                    if response.status == 401 and attempt == 0:
                        continue
                    if response.status >= 400:
                        raise HttpDownloadError(self._google_drive_api_error_message(response.status, body))
                    try:
                        data = json.loads(body)
                    except Exception as exc:
                        raise HttpDownloadError("Google Drive API 返回不是 JSON") from exc
                    if not isinstance(data, dict):
                        raise HttpDownloadError("Google Drive API 返回结构异常")
                    return data
        raise HttpDownloadError(self._google_drive_api_error_message(401, last_body))

    async def _google_drive_api_file_metadata(self, file_id: str, resource_key: str = "") -> Dict[str, Any]:
        file_id = str(file_id or "").strip()
        if not file_id:
            raise HttpDownloadError("Google Drive API 缺少文件 ID")
        query = {
            "fields": "id,name,mimeType,size,resourceKey,shortcutDetails",
            "supportsAllDrives": "true",
        }
        if str(resource_key or "").strip():
            query["resourceKey"] = str(resource_key or "").strip()
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?{urlencode(query)}"
        return await self._google_drive_api_json(
            url,
            resource_keys={file_id: resource_key} if resource_key else None,
        )

    def _google_drive_api_item_from_metadata(self, metadata: Dict[str, Any], raw_url: str, *, relative_dir: str = "") -> Optional[Dict[str, Any]]:
        file_id = str(metadata.get("id") or "").strip()
        if not file_id:
            return None
        mime_type = str(metadata.get("mimeType") or "").strip()
        if mime_type == "application/vnd.google-apps.folder":
            return None
        name = self._sanitize_filename(metadata.get("name") or "google-drive-file", fallback="google-drive-file")
        resource_key = str(metadata.get("resourceKey") or "").strip()
        size_bytes = int(metadata.get("size") or 0)
        direct_url = self._google_drive_api_download_url_from_id(file_id, resource_key)
        return {
            "source": "google_drive",
            "share_url": self._mask_url(raw_url),
            "url": direct_url,
            "masked_url": self._mask_url(direct_url),
            "name": name,
            "filename": name,
            "relative_dir": relative_dir.strip("/"),
            "size_bytes": size_bytes,
            "file_id": file_id,
            "resource_key": resource_key,
            "content_type": mime_type,
            "google_drive_api": True,
            "resumable": True,
            "warning": "Google Drive 已使用 OAuth Drive API 下载。",
        }

    async def _google_drive_api_single_file_item(self, raw_url: str) -> Dict[str, Any]:
        file_id = self._google_drive_file_id_from_url(raw_url)
        resource_key = self._google_drive_resource_key_from_url(raw_url)
        metadata = await self._google_drive_api_file_metadata(file_id, resource_key)
        item = self._google_drive_api_item_from_metadata(metadata, raw_url)
        if not item:
            raise HttpDownloadError("Google Drive API 返回的不是可下载文件")
        if resource_key and not item.get("resource_key"):
            item["resource_key"] = resource_key
            item["url"] = self._google_drive_api_download_url_from_id(file_id, resource_key)
            item["masked_url"] = self._mask_url(item["url"])
        return item

    async def _collect_google_drive_folder_files_api(self, raw_url: str) -> Dict[str, Any]:
        folder_id = self._google_drive_folder_id_from_url(raw_url)
        if not folder_id:
            raise HttpDownloadError("Google Drive 文件夹分享链接缺少文件夹 ID")
        folder_resource_key = self._google_drive_resource_key_from_url(raw_url)
        files: List[Dict[str, Any]] = []
        page_token = ""
        resource_keys = {folder_id: folder_resource_key} if folder_resource_key else None
        while True:
            query = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType,size,resourceKey,shortcutDetails)",
                "pageSize": "100",
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
            }
            if page_token:
                query["pageToken"] = page_token
            url = f"https://www.googleapis.com/drive/v3/files?{urlencode(query)}"
            data = await self._google_drive_api_json(url, resource_keys=resource_keys)
            for row in list(data.get("files") or []):
                if not isinstance(row, dict):
                    continue
                item = self._google_drive_api_item_from_metadata(row, raw_url)
                if item:
                    files.append(item)
            page_token = str(data.get("nextPageToken") or "").strip()
            if not page_token:
                break
        return {"folder_id": folder_id, "files": self._google_drive_dedupe_files(files), "source": "google_drive_api"}

    async def _fetch_text(self, url: str, *, headers: Optional[Dict[str, str]] = None, platform: Any = "http") -> str:
        timeout = aiohttp.ClientTimeout(total=max(20, int(getattr(self._config(), "timeout_seconds", 60) or 60)), connect=10)
        proxy = self._proxy_url(platform) or None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers or {}, allow_redirects=True, proxy=proxy) as response:
                body = await response.text(errors="ignore")
                if response.status >= 400:
                    raise HttpDownloadError(f"分享页返回 HTTP {response.status}")
                return body

    async def _google_drive_probe_download(self, url: str) -> Dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        proxy = self._proxy_url("google_drive") or None
        headers = {"User-Agent": _GOFILE_USER_AGENT, "Range": f"bytes=0-{GOOGLE_DRIVE_PROBE_BYTES - 1}"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True, proxy=proxy) as response:
                chunk = await response.content.read(GOOGLE_DRIVE_PROBE_BYTES)
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                return {
                    "status": response.status,
                    "url": str(response.url),
                    "content_type": str(response_headers.get("content-type") or ""),
                    "content_length": self._content_length_from_headers(response_headers),
                    "content_range": str(response_headers.get("content-range") or ""),
                    "content_disposition": str(response_headers.get("content-disposition") or ""),
                    "prefix": chunk[:32].hex(),
                }

    def _google_drive_extract_json_arrays(self, html_text: str) -> List[Any]:
        text = str(html_text or "")
        arrays: List[Any] = []
        decoder = json.JSONDecoder()
        markers = ("AF_initDataCallback", "window['_DRIVE_ivd']")
        for marker in markers:
            start = 0
            while True:
                marker_index = text.find(marker, start)
                if marker_index < 0:
                    break
                bracket_index = text.find("[", marker_index)
                if bracket_index < 0:
                    break
                try:
                    value, offset = decoder.raw_decode(text[bracket_index:])
                except Exception:
                    start = bracket_index + 1
                    continue
                if isinstance(value, list):
                    arrays.append(value)
                start = bracket_index + max(offset, 1)
        return arrays

    def _google_drive_find_folder_rows(self, value: Any) -> List[List[Any]]:
        rows: List[List[Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                if self._google_drive_node_looks_like_file_row(node):
                    rows.append(node)
                    return
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                for child in node.values():
                    walk(child)

        walk(value)
        return rows

    def _google_drive_node_looks_like_file_row(self, node: List[Any]) -> bool:
        if len(node) < 3:
            return False
        file_id = str(node[0] or "").strip() if isinstance(node[0], str) else ""
        name = str(node[2] or "").strip() if isinstance(node[2], str) else ""
        if not file_id or not name:
            return False
        if not re.fullmatch(r"[-_A-Za-z0-9]{16,}", file_id):
            return False
        if name.startswith(("https://", "http://")):
            return False
        return True

    def _google_drive_file_row(self, row: List[Any], raw_url: str) -> Optional[Dict[str, Any]]:
        file_id = str(row[0] or "").strip()
        name = self._sanitize_filename(str(row[2] or "").strip(), fallback="google-drive-file")
        if not file_id or not name:
            return None
        mime_type = str(row[3] or "").strip() if len(row) > 3 else ""
        if mime_type == "application/vnd.google-apps.folder":
            return None
        size_bytes = 0
        for value in row:
            if isinstance(value, int) and value > 0:
                size_bytes = value
                break
            if isinstance(value, str) and value.isdigit():
                number = int(value)
                if number > 0:
                    size_bytes = number
                    break
        direct_url = self._google_drive_direct_url_from_id(file_id)
        return {
            "source": "google_drive",
            "share_url": self._mask_url(raw_url),
            "url": direct_url,
            "masked_url": self._mask_url(direct_url),
            "name": name,
            "filename": name,
            "relative_dir": "",
            "size_bytes": size_bytes,
            "file_id": file_id,
            "content_type": mime_type,
        }

    def _google_drive_size_from_warning_html(self, html_text: str) -> int:
        text = html.unescape(str(html_text or ""))
        match = re.search(r"\(([\d.]+)\s*([KMGT]?B?)\)", text, re.IGNORECASE)
        if not match:
            return 0
        value = float(match.group(1))
        unit = match.group(2).upper()
        multiplier = {
            "K": 1024,
            "KB": 1024,
            "M": 1024 ** 2,
            "MB": 1024 ** 2,
            "G": 1024 ** 3,
            "GB": 1024 ** 3,
            "T": 1024 ** 4,
            "TB": 1024 ** 4,
        }.get(unit, 1)
        return int(value * multiplier)

    def _google_drive_filename_from_warning_html(self, html_text: str) -> str:
        text = html.unescape(str(html_text or ""))
        match = re.search(
            r'class=["\']uc-name-size["\'][^>]*>\s*<a\b[^>]*>([^<]+)</a>',
            text,
            re.IGNORECASE,
        )
        if not match:
            return ""
        return self._sanitize_filename(match.group(1), fallback="")

    def _google_drive_html_error_message(self, html_text: str) -> str:
        text = html.unescape(str(html_text or ""))
        normalized = re.sub(r"\s+", " ", text).lower()
        chinese_text = text
        if any(marker in normalized for marker in (
            "quota exceeded",
            "download quota",
            "too many users have viewed or downloaded",
            "too many users",
            "exceeded the download quota",
        )):
            return "Google Drive 后端直链被配额/登录态拦截：Google 返回 Quota exceeded HTML 页；浏览器登录态可能仍可下载，但当前后端请求无法复用浏览器 Cookie，请稍后重试或换源"
        if any(marker in normalized for marker in (
            "request access",
            "you need access",
            "access denied",
            "permission denied",
            "you don't have access",
        )) or any(marker in chinese_text for marker in (
            "需要访问权限",
            "请求访问权限",
            "没有访问权限",
            "权限不足",
        )):
            return "Google Drive 文件需要访问权限，当前分享不是公开可下载"
        return "Google Drive 返回 HTML 页面，确认参数或访问权限已失效"

    def _google_drive_confirm_url_from_warning_html(self, html_text: str, fallback_url: str) -> str:
        parser = _GoogleDriveDownloadFormParser()
        parser.feed(str(html_text or ""))
        if not parser.action or not parser.inputs:
            return ""
        query = {
            key: value
            for key, value in parser.inputs.items()
            if str(key or "").strip() and str(value or "").strip()
        }
        if not query:
            return ""
        parsed_fallback = urlparse(fallback_url)
        fallback_query = parse_qs(parsed_fallback.query or "")
        for key in ("id", "export"):
            if key not in query and fallback_query.get(key):
                query[key] = str(fallback_query[key][0])
        return f"{parser.action}?{urlencode(query)}"

    def _google_drive_cookie_header_from_session(self, session: aiohttp.ClientSession, url: str) -> str:
        try:
            cookies = session.cookie_jar.filter_cookies(url)
        except Exception:
            return ""
        parts = []
        for name, morsel in cookies.items():
            value = getattr(morsel, "value", morsel)
            if str(name or "").strip() and str(value or "").strip():
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    async def _google_drive_resolve_confirm_url(self, url: str) -> Dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        proxy = self._proxy_url("google_drive") or None
        headers = {"User-Agent": _GOFILE_USER_AGENT}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True, proxy=proxy) as response:
                body = await response.text(errors="ignore")
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                content_type = str(response_headers.get("content-type") or "")
                if response.status >= 400:
                    raise HttpDownloadError(f"Google Drive 返回 HTTP {response.status}")
                if "text/html" not in content_type.lower():
                    cookie_header = self._google_drive_cookie_header_from_session(session, str(response.url))
                    return {
                        "url": str(response.url),
                        "size_bytes": self._content_length_from_headers(response_headers),
                        "content_type": content_type,
                        "warning": "",
                        "headers": {"Cookie": cookie_header} if cookie_header else {},
                        "aria2_header": [f"Cookie: {cookie_header}"] if cookie_header else [],
                    }
        confirm_url = self._google_drive_confirm_url_from_warning_html(body, url)
        cookie_header = self._google_drive_cookie_header_from_session(session, confirm_url or url)
        if not confirm_url:
            warning = self._google_drive_html_error_message(body)
            if warning == "Google Drive 返回 HTML 页面，确认参数或访问权限已失效":
                warning = "Google Drive 返回确认页，未解析到确认下载参数。"
            return {
                "url": url,
                "size_bytes": self._google_drive_size_from_warning_html(body),
                "content_type": content_type,
                "warning": warning,
                "filename": self._google_drive_filename_from_warning_html(body),
                "headers": {"Cookie": cookie_header} if cookie_header else {},
                "aria2_header": [f"Cookie: {cookie_header}"] if cookie_header else [],
            }
        return {
            "url": confirm_url,
            "size_bytes": self._google_drive_size_from_warning_html(body),
            "content_type": content_type,
            "warning": "Google Drive 大文件已自动附加确认下载参数。",
            "filename": self._google_drive_filename_from_warning_html(body),
            "headers": {"Cookie": cookie_header} if cookie_header else {},
            "aria2_header": [f"Cookie: {cookie_header}"] if cookie_header else [],
        }

    def _google_drive_dedupe_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in files:
            file_id = str(item.get("file_id") or "").strip()
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            unique.append(item)
        return unique

    def _google_drive_file_id_from_href(self, href: str) -> str:
        absolute = urljoin("https://drive.google.com", html.unescape(str(href or "").strip()))
        try:
            return self._google_drive_file_id_from_url(absolute)
        except HttpDownloadError:
            return ""

    def _google_drive_files_from_embedded_html(self, html_text: str, raw_url: str) -> List[Dict[str, Any]]:
        parser = _GoogleDriveFolderHTMLParser()
        parser.feed(str(html_text or ""))
        files: List[Dict[str, Any]] = []
        for row in parser.rows:
            href = str(row.get("href") or "")
            file_id = self._google_drive_file_id_from_href(href)
            if not file_id:
                continue
            name = self._sanitize_filename(row.get("name") or "google-drive-file", fallback="google-drive-file")
            direct_url = self._google_drive_direct_url_from_id(file_id)
            files.append({
                "source": "google_drive",
                "share_url": self._mask_url(raw_url),
                "url": direct_url,
                "masked_url": self._mask_url(direct_url),
                "name": name,
                "filename": name,
                "relative_dir": "",
                "size_bytes": 0,
                "file_id": file_id,
                "content_type": "",
            })
        return self._google_drive_dedupe_files(files)

    async def _collect_google_drive_folder_files(self, raw_url: str) -> Dict[str, Any]:
        folder_id = self._google_drive_folder_id_from_url(raw_url)
        if not folder_id:
            raise HttpDownloadError("Google Drive 文件夹分享链接缺少文件夹 ID")
        if self._google_drive_oauth_enabled():
            try:
                return await self._collect_google_drive_folder_files_api(raw_url)
            except Exception as exc:
                logger.warning("[HTTP下载] Google Drive API 解析文件夹失败，回退页面解析: %s", self._sanitize_error(exc))
        embedded_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
        html_text = await self._fetch_text(
            embedded_url,
            headers={
                "User-Agent": _GOFILE_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            platform="google_drive",
        )
        files = self._google_drive_files_from_embedded_html(html_text, raw_url)
        if not files:
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
            html_text = await self._fetch_text(
                folder_url,
                headers={
                    "User-Agent": _GOFILE_USER_AGENT,
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                platform="google_drive",
            )
            for payload in self._google_drive_extract_json_arrays(html_text):
                for row in self._google_drive_find_folder_rows(payload):
                    item = self._google_drive_file_row(row, raw_url)
                    if item:
                        files.append(item)
        files = self._google_drive_dedupe_files(files)
        if not files:
            lowered = html_text.lower()
            if "request access" in lowered or "需要访问权限" in html_text or "请求访问权限" in html_text:
                raise HttpDownloadError("Google Drive 文件夹需要访问权限，当前分享不是公开可读")
            raise HttpDownloadError("Google Drive 文件夹页未解析到可下载文件")
        return {"files": files, "folder_id": folder_id}

    def _onedrive_direct_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        query = parse_qs(parsed.query or "")
        if query.get("download") == ["1"]:
            return raw_url
        query["download"] = ["1"]
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment))

    async def _extract_html_download_links(self, raw_url: str, *, source: str) -> List[Dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        proxy = self._proxy_url(source) or None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(raw_url, allow_redirects=True, proxy=proxy) as response:
                body = await response.text(errors="ignore")
                base_url = str(response.url)
                if response.status >= 400:
                    raise HttpDownloadError(f"分享页返回 HTTP {response.status}")
        links = []
        for match in re.finditer(r'''(?:href|data-href|data-url)=["']([^"']+)["']''', body, re.IGNORECASE):
            href = html.unescape(match.group(1)).strip()
            if not href:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            label = absolute.lower()
            if "download" not in label and "/dl" not in label and "/api/" not in label:
                continue
            links.append({
                "source": source,
                "url": absolute,
                "masked_url": self._mask_url(absolute),
                "share_url": self._mask_url(raw_url),
            })
        unique = []
        seen = set()
        for item in links:
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            unique.append(item)
        return unique

    def _transferit_id_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        match = re.search(r"/t/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[-1]
        raise HttpDownloadError("Transfer.it 分享链接格式不正确")

    def _transferit_password(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        query = parse_qs(parsed.query or "")
        for key in ("password", "pwd", "pass", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        fragment = parsed.fragment or ""
        match = re.search(r"(?:password|pwd|pass|code)=([^&]+)", fragment, re.IGNORECASE)
        return unquote(match.group(1)).strip() if match else ""

    def _is_transferit_transient_error(self, exc: BaseException) -> bool:
        text = self._sanitize_error(exc).lower()
        return any(marker in text for marker in (
            "server is busy",
            "try again",
            "temporarily",
            "timeout",
            "timed out",
            "too many requests",
            "429",
            "502",
            "503",
            "504",
        ))

    def _transferit_node_row(self, item: Any, index: int, relative_dir: str = "") -> Optional[Dict[str, Any]]:
        if isinstance(item, dict):
            kind = str(item.get("type") or item.get("kind") or "").lower()
            if kind and "folder" in kind:
                return None
            name = (
                item.get("name")
                or item.get("filename")
                or item.get("file_name")
                or f"transferit-file-{index + 1}"
            )
            size = item.get("size") or item.get("byte_size") or item.get("bytes") or item.get("total_bytes") or 0
            handle = str(item.get("handle") or item.get("h") or item.get("id") or "").strip()
            return {
                "name": str(name),
                "size_bytes": int(size or 0),
                "transferit_node_handle": handle,
                "relative_dir": relative_dir,
            }
        if hasattr(item, "to_json_dict"):
            row = self._transferit_node_row(item.to_json_dict(), index, relative_dir)
            if row:
                row["transferit_node_handle"] = (
                    str(getattr(item, "handle", "") or "").strip()
                    or str(row.get("transferit_node_handle") or "").strip()
                )
            return row
        is_file = getattr(item, "is_file", True)
        if callable(is_file):
            is_file = is_file()
        if is_file is False:
            return None
        name = (
            getattr(item, "name", "")
            or getattr(item, "filename", "")
            or getattr(item, "file_name", "")
            or f"transferit-file-{index + 1}"
        )
        size = (
            getattr(item, "size", 0)
            or getattr(item, "byte_size", 0)
            or getattr(item, "bytes", 0)
            or getattr(item, "total_bytes", 0)
            or 0
        )
        return {
            "name": str(name),
            "size_bytes": int(size or 0),
            "transferit_node_handle": str(getattr(item, "handle", "") or "").strip(),
            "relative_dir": relative_dir,
        }

    def _transferit_metadata_row(self, metadata: Any, share_id: str) -> Optional[Dict[str, Any]]:
        if hasattr(metadata, "to_json_dict"):
            data = metadata.to_json_dict()
        elif isinstance(metadata, dict):
            data = dict(metadata)
        else:
            data = {
                "title": getattr(metadata, "title", ""),
                "total_bytes": getattr(metadata, "total_bytes", 0),
                "file_count": getattr(metadata, "file_count", 0),
                "folder_count": getattr(metadata, "folder_count", 0),
                "password_protected": getattr(metadata, "password_protected", False),
                "zip_pending": getattr(metadata, "zip_pending", False),
                "zip_handle": getattr(metadata, "zip_handle", None),
            }
        if bool(data.get("password_protected")):
            return None
        try:
            file_count = int(data.get("file_count") or 0)
        except Exception:
            file_count = 0
        if file_count and file_count != 1:
            return None
        title = (
            data.get("title")
            or data.get("name")
            or data.get("filename")
            or f"transferit-{share_id}"
        )
        filename = self._sanitize_filename(str(title), fallback=f"transferit-{share_id}.zip")
        if not os.path.splitext(filename)[1]:
            filename = self._sanitize_filename(f"{filename}.zip", fallback=f"transferit-{share_id}.zip")
        return {
            "name": filename,
            "size_bytes": int(data.get("total_bytes") or data.get("size_bytes") or 0),
            "metadata_fallback": True,
        }

    async def _collect_transferit_files(self, raw_url: str) -> Dict[str, Any]:
        share_id = self._transferit_id_from_url(raw_url)
        url = self._normalize_url(raw_url)
        password = self._transferit_password(raw_url) or None

        metadata_row: Optional[Dict[str, Any]] = None

        def collect() -> List[Dict[str, Any]]:
            client = self._transferit_api_client()
            try:
                info = client.info(url, password=password) if password else client.info(url)
            finally:
                self._close_transferit_client(client)
            rows: List[Dict[str, Any]] = []
            candidates: Any = info
            if isinstance(info, dict):
                candidates = info.get("files") or info.get("children") or info.get("items") or [info]
            elif hasattr(info, "to_json_dict"):
                candidates = info.to_json_dict()
            if isinstance(candidates, dict):
                candidates = list(candidates.values())
            if not isinstance(candidates, list):
                candidates = [candidates]

            def node_kind(node: Any) -> str:
                raw_kind = getattr(node, "kind", None)
                if raw_kind is None and isinstance(node, dict):
                    raw_kind = node.get("kind") or node.get("type") or node.get("t")
                text = str(raw_kind or "").lower()
                if text in {"1", "folder"} or "folder" in text:
                    return "folder"
                if bool(getattr(node, "is_folder", False)):
                    return "folder"
                return "file"

            folder_names: Dict[str, str] = {}
            folder_parents: Dict[str, str] = {}
            for node in candidates:
                if node_kind(node) != "folder":
                    continue
                handle = str(
                    getattr(node, "handle", "")
                    or (node.get("handle") or node.get("h") or node.get("id") if isinstance(node, dict) else "")
                    or ""
                ).strip()
                if not handle:
                    continue
                folder_names[handle] = self._sanitize_filename(
                    str(
                        getattr(node, "name", "")
                        or (node.get("name") if isinstance(node, dict) else "")
                        or handle
                    ),
                    fallback=handle,
                )
                folder_parents[handle] = str(
                    getattr(node, "parent", "")
                    or (node.get("parent") or node.get("p") if isinstance(node, dict) else "")
                    or ""
                ).strip()

            folder_paths: Dict[str, str] = {}

            def folder_path(handle: str) -> str:
                handle = str(handle or "").strip()
                if not handle or handle not in folder_names:
                    return ""
                if handle in folder_paths:
                    return folder_paths[handle]
                parent = folder_parents.get(handle, "")
                parent_path = folder_path(parent) if parent and parent in folder_names else ""
                path = "/".join(part for part in (parent_path, folder_names[handle]) if part)
                folder_paths[handle] = path
                return path

            def node_relative_dir(node: Any) -> str:
                parent = str(
                    getattr(node, "parent", "")
                    or (node.get("parent") or node.get("p") if isinstance(node, dict) else "")
                    or ""
                ).strip()
                return folder_path(parent).strip("/")

            for index, item in enumerate(candidates):
                row = self._transferit_node_row(item, index, node_relative_dir(item))
                if row:
                    rows.append(row)
            if not rows and isinstance(info, dict):
                nested = info.get("files") or info.get("children") or info.get("items") or []
                if isinstance(nested, dict):
                    nested = list(nested.values())
                for index, item in enumerate(nested):
                    row = self._transferit_node_row(item, index, node_relative_dir(item))
                    if row:
                        rows.append(row)
            if not rows and not isinstance(info, dict) and hasattr(info, "to_json_dict"):
                data = info.to_json_dict()
                candidates = data.get("files") or data.get("children") or data.get("items") or []
                if isinstance(candidates, dict):
                    candidates = list(candidates.values())
                for index, item in enumerate(candidates):
                    row = self._transferit_node_row(item, index, node_relative_dir(item))
                    if row:
                        rows.append(row)
            if not rows:
                fallback_name = (
                    (info.get("name") if isinstance(info, dict) else "")
                    or getattr(info, "name", "")
                    or getattr(info, "title", "")
                    or "transferit-download"
                )
                fallback_size = (
                    (info.get("size") if isinstance(info, dict) else 0)
                    or getattr(info, "size", 0)
                    or getattr(info, "total_bytes", 0)
                    or 0
                )
                rows.append({"name": str(fallback_name), "size_bytes": int(fallback_size or 0)})
            return rows

        def collect_metadata_row() -> Optional[Dict[str, Any]]:
            client = self._transferit_api_client()
            try:
                metadata = client.metadata(url)
            finally:
                self._close_transferit_client(client)
            return self._transferit_metadata_row(metadata, share_id)

        files: List[Dict[str, Any]] = []
        resolved_files = False
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                files = await asyncio.wait_for(asyncio.to_thread(collect), timeout=25)
                resolved_files = True
                break
            except asyncio.TimeoutError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
                if not self._is_transferit_transient_error(exc):
                    raise
            if last_error and self._is_transferit_transient_error(last_error) and metadata_row is None:
                try:
                    metadata_row = await asyncio.wait_for(asyncio.to_thread(collect_metadata_row), timeout=15)
                except Exception as meta_exc:
                    logger.debug("Transfer.it 元数据兜底解析失败: %s", meta_exc)
            if attempt < 2:
                await asyncio.sleep(1.2 * (attempt + 1))
        else:
            if metadata_row:
                files = [metadata_row]
                resolved_files = True
            else:
                if isinstance(last_error, asyncio.TimeoutError):
                    raise HttpDownloadError("Transfer.it 解析超时，请稍后重试或确认分享链接仍有效") from last_error
                if last_error and self._is_transferit_transient_error(last_error):
                    raise HttpDownloadError("Transfer.it 服务器忙，请稍后重试") from last_error
                if last_error:
                    raise last_error
                files = []

        if not files and metadata_row:
            files = [metadata_row]
            resolved_files = True

        if not resolved_files and last_error:
            raise last_error

        return {
            "share_id": share_id,
            "files": [
                {
                    "source": "transferit",
                    "share_url": self._mask_url(raw_url),
                    "url": self._mask_url(raw_url),
                    "original_url": raw_url,
                    "name": self._sanitize_filename(item.get("name") or "transferit-download"),
                    "filename": self._sanitize_filename(item.get("name") or "transferit-download"),
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "preview_only": True,
                    "share_id": share_id,
                    "transferit_node_handle": str(item.get("transferit_node_handle") or ""),
                    "relative_dir": str(item.get("relative_dir") or "").strip("/"),
                    "metadata_fallback": bool(item.get("metadata_fallback")),
                }
                for item in files
            ],
        }

    def _pikpak_file_size(self, item: Dict[str, Any]) -> int:
        for key in ("size", "file_size", "bytes"):
            try:
                value = int(item.get(key) or 0)
                if value > 0:
                    return value
            except Exception:
                pass
        return 0

    def _pikpak_is_folder(self, item: Dict[str, Any]) -> bool:
        kind = str(item.get("kind") or item.get("mime_type") or item.get("type") or "").lower()
        return "folder" in kind

    def _pikpak_share_id_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        match = re.search(r"/s/([^/?#]+)", parsed.path)
        if not match:
            raise HttpDownloadError("PikPak 分享链接格式不正确")
        return match.group(1)

    def _normalize_pikpak_share_access(self, info: Any, share_link: str, stage: str = "读取分享") -> tuple[str, str]:
        if isinstance(info, Exception):
            raise self._pikpak_error(info, stage)
        if not isinstance(info, dict):
            raise HttpDownloadError("PikPak 分享信息返回异常")
        share_status = str(info.get("share_status") or info.get("status") or "").strip()
        share_status_text = str(info.get("share_status_text") or info.get("message") or info.get("error") or "").strip()
        bad_share_statuses = {"PROHIBITED", "EXPIRED", "DELETED", "BANNED", "FORBIDDEN", "VIOLATION", "INVALID"}
        if share_status.upper() in bad_share_statuses or "current region" in share_status_text.lower():
            detail = f"{share_status}: {share_status_text}" if share_status_text else share_status
            raise self._pikpak_error(detail, stage)
        share_id = str(info.get("share_id") or self._pikpak_share_id_from_url(share_link))
        token = str(info.get("pass_code_token") or "")
        return share_id, token

    async def _pikpak_share_page_request(
        self,
        client,
        *,
        endpoint: str,
        share_id: str,
        order: str,
        parent_id: Optional[str],
        page_token: str,
        pass_code: Optional[str] = None,
        pass_code_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        # pikpakapi 的 get_share_info/get_share_folder 写死 limit=100 且不支持 page_token，
        # 这里直接复刻底层请求补上 page_token 用于翻页，参数与上游保持一致。
        host = getattr(client, "PIKPAK_API_HOST", "api-drive.mypikpak.com")
        data: Dict[str, Any] = {
            "limit": "100",
            "thumbnail_size": "SIZE_LARGE",
            "order": order,
            "share_id": share_id,
            "parent_id": parent_id,
            "page_token": page_token,
        }
        if pass_code is not None:
            data["pass_code"] = pass_code
        if pass_code_token is not None:
            data["pass_code_token"] = pass_code_token
        result = await client._request_get(f"https://{host}/{endpoint}", params=data)
        return result if isinstance(result, dict) else {}

    async def _pikpak_collect_all_pages(
        self,
        client,
        first_page: Dict[str, Any],
        *,
        fetch_next,
        max_pages: int = 50,
    ) -> List[Dict[str, Any]]:
        # 合并首页 files 与后续 next_page_token 翻页，确保 >100 或被 PikPak 分页的分享不丢文件；
        # 翻页失败时按已取得的文件继续，不退化为报错。
        files = [it for it in list((first_page or {}).get("files") or []) if isinstance(it, dict)]
        page_token = str((first_page or {}).get("next_page_token") or "").strip()
        if not page_token or not hasattr(client, "_request_get"):
            return files
        seen = set()
        for _ in range(max(1, max_pages)):
            if not page_token or page_token in seen:
                break
            seen.add(page_token)
            try:
                resp = await fetch_next(page_token)
            except Exception as exc:
                logger.warning(
                    "[PikPak] 分享翻页失败，按已取得的 %s 个文件继续: %s",
                    len(files),
                    self._sanitize_error(exc),
                )
                break
            if not isinstance(resp, dict):
                break
            files.extend([it for it in list(resp.get("files") or []) if isinstance(it, dict)])
            page_token = str(resp.get("next_page_token") or "").strip()
        return files

    async def _collect_pikpak_share_files(self, client, share_link: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        clean_share_link = self._pikpak_share_url(share_link)
        pass_code = self._parse_pikpak_pass_code(share_link) or self._parse_pikpak_pass_code(clean_share_link)
        try:
            info = await client.get_share_info(clean_share_link, pass_code=pass_code or None)
        except Exception as exc:
            raise self._pikpak_error(exc, "读取分享") from exc
        share_id, token = self._normalize_pikpak_share_access(info, clean_share_link, "读取分享")
        root_match = re.search(r"/s/[^/]+/([^/?#]+)", urlparse(clean_share_link).path)
        root_parent_id = root_match.group(1) if root_match else None
        files = await self._pikpak_collect_all_pages(
            client,
            info,
            fetch_next=lambda pt: self._pikpak_share_page_request(
                client,
                endpoint="drive/v1/share",
                share_id=share_id,
                order="3",
                parent_id=root_parent_id,
                page_token=pt,
                pass_code=pass_code or None,
            ),
        )
        collected: List[Dict[str, Any]] = []

        async def walk(items: List[Dict[str, Any]], prefix: str = "") -> None:
            for item in items:
                if len(collected) >= _PIKPAK_MAX_SHARE_FILES:
                    raise HttpDownloadError(f"PikPak 单次最多解析 {_PIKPAK_MAX_SHARE_FILES} 个文件")
                name = self._sanitize_filename(item.get("name") or item.get("file_name") or "pikpak-file")
                if self._pikpak_is_folder(item):
                    if not token:
                        raise HttpDownloadError("PikPak 文件夹分享缺少访问 token")
                    folder_id = str(item.get("id") or item.get("file_id") or "")
                    try:
                        detail = await client.get_share_folder(share_id, token, parent_id=folder_id or None)
                    except Exception as exc:
                        raise self._pikpak_error(exc, "读取分享文件夹") from exc
                    children = await self._pikpak_collect_all_pages(
                        client,
                        detail or {},
                        fetch_next=lambda pt, fid=folder_id: self._pikpak_share_page_request(
                            client,
                            endpoint="drive/v1/share/detail",
                            share_id=share_id,
                            order="6",
                            parent_id=fid or None,
                            page_token=pt,
                            pass_code_token=token,
                        ),
                    )
                    await walk(children, "/".join([part for part in (prefix, name) if part]))
                    continue
                row = dict(item)
                row["_relative_dir"] = prefix
                collected.append(row)

        await walk(files)
        logger.info(
            "[PikPak诊断] collect 翻页后顶层=%s 收集=%s 首页还有下页=%s 文件名=%s",
            len(files),
            len(collected),
            bool(info.get("next_page_token")),
            [self._sanitize_filename(str(r.get("name") or "")) for r in collected],
        )
        return info, collected

    async def _touch_pikpak_share(self, client, share_link: str, *, account: Optional[PikPakAccount] = None) -> tuple[str, str]:
        if not share_link:
            return "", ""
        clean_share_link = self._pikpak_share_url(share_link)
        pass_code = self._parse_pikpak_pass_code(share_link) or self._parse_pikpak_pass_code(clean_share_link)
        label = getattr(account, "label", "") or "账号"
        try:
            info = await client.get_share_info(clean_share_link, pass_code=pass_code or None)
        except Exception as exc:
            raise self._pikpak_error(exc, f"账号 {label} 读取分享") from exc
        return self._normalize_pikpak_share_access(info, clean_share_link, f"账号 {label} 读取分享")

    async def _restore_pikpak_share_files(
        self,
        client,
        *,
        share_id: str,
        pass_code_token: str,
        file_ids: List[str],
        parent_id: str,
    ) -> Dict[str, Any]:
        payload = {
            "share_id": share_id,
            "pass_code_token": pass_code_token or "",
            "file_ids": file_ids,
        }
        if parent_id:
            payload["parent_id"] = parent_id
        if hasattr(client, "_request_post"):
            host = str(getattr(client, "PIKPAK_API_HOST", "") or "api-drive.mypikpak.com")
            return await client._request_post(
                url=f"https://{host}/drive/v1/share/restore",
                data=payload,
            )

        restore = getattr(client, "restore", None)
        if not callable(restore):
            raise HttpDownloadError("当前 pikpakapi 客户端不支持分享转存接口")
        try:
            signature = inspect.signature(restore)
            if "parent_id" in signature.parameters:
                return await restore(share_id, pass_code_token or "", file_ids, parent_id=parent_id or None)
        except (TypeError, ValueError):
            pass
        result = await restore(share_id, pass_code_token or "", file_ids)
        if parent_id:
            id_map = self._extract_pikpak_restore_id_map(result, file_ids)
            restored_ids = list(dict.fromkeys(id_map.values()))
            if restored_ids and hasattr(client, "file_batch_move"):
                await client.file_batch_move(restored_ids, to_parent_id=parent_id)
        return result

    def _extract_pikpak_restore_id_map(self, result: Any, file_ids: List[str]) -> Dict[str, str]:
        source_ids = {str(item) for item in file_ids if str(item or "").strip()}
        id_map: Dict[str, str] = {}

        def add_mapping(source_id: Any, target_id: Any) -> None:
            source = str(source_id or "").strip()
            target = str(target_id or "").strip()
            if source in source_ids and target and target != source:
                id_map[source] = target

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key in ("file_id_map", "id_map", "restore_map", "file_map"):
                    nested = value.get(key)
                    if isinstance(nested, dict):
                        for source_id, target_id in nested.items():
                            add_mapping(source_id, target_id)
                original_id = ""
                for key in ("original_file_id", "from_id", "source_id", "src_file_id", "share_file_id", "origin_file_id"):
                    if value.get(key):
                        original_id = str(value.get(key) or "")
                        break
                target_id = ""
                for key in ("restored_file_id", "new_file_id", "target_file_id", "to_id", "file_id", "id"):
                    if value.get(key):
                        target_id = str(value.get(key) or "")
                        break
                add_mapping(original_id, target_id)
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(result)
        return id_map

    async def _match_pikpak_restored_files_from_listing(
        self,
        client,
        *,
        parent_id: str,
        source_id_map: Dict[str, str],
        file_ids: List[str],
        share_files: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        unresolved = [file_id for file_id in file_ids if source_id_map.get(file_id) == file_id]
        if not unresolved or not parent_id:
            return
        try:
            listing = await self.pikpak_transfer_files(client=client, parent_id=parent_id, root=False, limit=500)
        except Exception:
            logger.debug("[PikPak] 转存后读取目录匹配文件失败", exc_info=True)
            return
        rows = [item for item in list((listing or {}).get("files") or []) if isinstance(item, dict)]
        source_files = {
            self._pikpak_file_id(item): item
            for item in list(share_files or [])
            if self._pikpak_file_id(item)
        }
        for file_id in unresolved:
            source = source_files.get(file_id, {})
            source_name = self._sanitize_filename(source.get("name") or source.get("file_name") or "")
            source_size = self._pikpak_file_size(source)
            candidates = []
            for row in rows:
                row_id = self._pikpak_file_id(row)
                if not row_id or row_id in source_id_map.values():
                    continue
                row_name = self._sanitize_filename(row.get("name") or row.get("file_name") or "")
                if source_name and row_name != source_name:
                    continue
                row_size = self._pikpak_file_size(row)
                if source_size and row_size and source_size != row_size:
                    continue
                candidates.append(row_id)
            if len(candidates) == 1:
                source_id_map[file_id] = candidates[0]

    async def _list_pikpak_folder_files(
        self,
        client,
        folder_id: str,
        *,
        limit: int = 500,
        depth: int = 0,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not folder_id or depth > 8:
            return rows
        try:
            listing = await self.pikpak_transfer_files(client=client, parent_id=folder_id, root=False, limit=limit)
        except Exception:
            return rows
        for item in list((listing or {}).get("files") or []):
            if not isinstance(item, dict):
                continue
            if self._pikpak_is_folder(item):
                rows.extend(await self._list_pikpak_folder_files(client, self._pikpak_file_id(item), limit=limit, depth=depth + 1))
            else:
                rows.append(item)
        return rows

    async def _resolve_pikpak_restored_via_container(
        self,
        client,
        *,
        container_id: str,
        source_id_map: Dict[str, str],
        file_ids: List[str],
        share_files: Optional[List[Dict[str, Any]]] = None,
        wait_seconds: float = 30.0,
    ) -> None:
        unresolved = [file_id for file_id in file_ids if source_id_map.get(file_id) == file_id]
        if not unresolved or not container_id:
            return
        source_by_id = {
            self._pikpak_file_id(item): item
            for item in list(share_files or [])
            if self._pikpak_file_id(item)
        }
        deadline = time.monotonic() + max(2.0, float(wait_seconds))
        while unresolved and time.monotonic() < deadline:
            rows = await self._list_pikpak_folder_files(client, container_id, limit=500)
            taken = set(source_id_map.values())
            for file_id in list(unresolved):
                source = source_by_id.get(file_id, {})
                source_name = self._sanitize_filename(source.get("name") or source.get("file_name") or "")
                source_size = self._pikpak_file_size(source)
                candidates: List[str] = []
                for row in rows:
                    row_id = self._pikpak_file_id(row)
                    if not row_id or row_id in taken:
                        continue
                    row_name = self._sanitize_filename(row.get("name") or row.get("file_name") or "")
                    if source_name and row_name != source_name:
                        continue
                    row_size = self._pikpak_file_size(row)
                    if source_size and row_size and source_size != row_size:
                        continue
                    candidates.append(row_id)
                if len(candidates) == 1:
                    source_id_map[file_id] = candidates[0]
                    taken.add(candidates[0])
                    unresolved.remove(file_id)
            if unresolved:
                await asyncio.sleep(1.5)

    async def _copy_pikpak_share_files(
        self,
        client,
        file_ids: List[str],
        share_files: Optional[List[Dict[str, Any]]] = None,
        *,
        account: Optional[PikPakAccount] = None,
        share_id: str = "",
        pass_code_token: str = "",
    ) -> Dict[str, str]:
        id_map = {str(item): str(item) for item in file_ids if str(item or "").strip()}
        if not file_ids:
            return id_map
        if not share_id:
            raise HttpDownloadError("PikPak 转存分享文件缺少 share_id")
        account = account or getattr(client, "_kikoeru_pikpak_account", None)
        parent_id = None
        try:
            parent_id = await self._pikpak_transfer_parent_id(client, create=True, account=account)
        except HttpDownloadError:
            raise
        except Exception as exc:
            raise self._pikpak_error(exc, "创建/定位转存目录") from exc
        try:
            quota = self._normalize_pikpak_quota(await client.get_quota_info())
            if account:
                self._pikpak_status_cache_write(
                    self._pikpak_public_status(
                        account,
                        success=True,
                        ready=True,
                        quota=quota,
                        source="quota-check",
                        cached=False,
                        updated_at=datetime.now(),
                    ),
                    account,
                    source="quota-check",
                )
            needed = 0
            if int(quota.get("limit_bytes") or 0) > 0:
                file_id_set = set(file_ids)
                needed = sum(
                    self._pikpak_file_size(item)
                    for item in list(share_files or [])
                    if self._pikpak_file_id(item) in file_id_set
                )
            if needed and needed > int(quota.get("remaining_bytes") or 0):
                raise HttpDownloadError(
                    f"PikPak 转存空间不足: 账号 {getattr(account, 'label', '') or '默认账号'} 需要 {needed} 字节，剩余 {quota.get('remaining_bytes', 0)} 字节。请在设置页清理转存目录或换账号。"
                )
        except HttpDownloadError:
            raise
        except Exception:
            logger.debug("[PikPak] 容量预检失败，继续尝试转存", exc_info=True)
        try:
            result = await self._restore_pikpak_share_files(
                client,
                share_id=share_id,
                pass_code_token=pass_code_token,
                file_ids=file_ids,
                parent_id=parent_id or "",
            )
        except Exception as exc:
            raise self._pikpak_error(exc, "转存分享文件") from exc
        try:
            restore_keys = list(result.keys()) if isinstance(result, dict) else type(result).__name__
            restore_dump = (
                json.dumps(result, ensure_ascii=False, default=str)[:3000]
                if isinstance(result, (dict, list))
                else str(result)[:3000]
            )
            share_brief = [
                {
                    "id": self._pikpak_file_id(item),
                    "name": str(item.get("name") or item.get("file_name") or ""),
                    "size": self._pikpak_file_size(item),
                    "is_folder": self._pikpak_is_folder(item),
                }
                for item in list(share_files or [])[:12]
            ]
            logger.info(
                "[PikPak诊断] 转存入参 account=%s share_id=%s 传入parent_id=%s file_ids=%s share_files=%s",
                getattr(account, "label", "") or "默认",
                share_id,
                parent_id,
                file_ids,
                share_brief,
            )
            logger.info("[PikPak诊断] restore 返回 keys=%s 原始=%s", restore_keys, restore_dump)
            try:
                root_listing = await self.pikpak_transfer_files(client=client, root=True, limit=200)
                root_rows = [
                    (r.get("name"), r.get("id"), r.get("is_folder"), r.get("size_bytes"))
                    for r in (root_listing.get("files") or [])
                ]
                logger.info("[PikPak诊断] 转存后根目录(%s 项)=%s", len(root_rows), root_rows)
            except Exception as exc:
                logger.warning("[PikPak诊断] 列根目录失败: %s", exc)
            try:
                dir_listing = await self.pikpak_transfer_files(client=client, parent_id=parent_id or "", root=False, limit=200)
                dir_rows = [
                    (r.get("name"), r.get("id"), r.get("is_folder"), r.get("size_bytes"))
                    for r in (dir_listing.get("files") or [])
                ]
                logger.info("[PikPak诊断] 转存目录 parent_id=%s(%s 项)=%s", parent_id, len(dir_rows), dir_rows)
            except Exception as exc:
                logger.warning("[PikPak诊断] 列转存目录失败: %s", exc)
        except Exception as exc:
            logger.warning("[PikPak诊断] 诊断日志输出失败: %s", exc)
        id_map.update(self._extract_pikpak_restore_id_map(result, file_ids))
        restore_container_id = str(result.get("file_id") or "").strip() if isinstance(result, dict) else ""
        if restore_container_id:
            await self._resolve_pikpak_restored_via_container(
                client,
                container_id=restore_container_id,
                source_id_map=id_map,
                file_ids=file_ids,
                share_files=share_files,
            )
        await self._match_pikpak_restored_files_from_listing(
            client,
            parent_id=parent_id or "",
            source_id_map=id_map,
            file_ids=file_ids,
            share_files=share_files,
        )
        with contextlib.suppress(Exception):
            logger.info(
                "[PikPak诊断] 匹配后 id_map=%s unresolved=%s",
                id_map,
                [fid for fid in file_ids if id_map.get(fid) == fid],
            )
        unresolved_ids = [file_id for file_id in file_ids if id_map.get(file_id) == file_id]
        if unresolved_ids:
            unresolved_names = []
            source_by_id = {
                self._pikpak_file_id(item): item
                for item in list(share_files or [])
                if self._pikpak_file_id(item)
            }
            for file_id in unresolved_ids[:5]:
                source = source_by_id.get(file_id, {})
                unresolved_names.append(str(source.get("name") or source.get("file_name") or file_id))
            suffix = "、".join(unresolved_names)
            raise HttpDownloadError(f"PikPak 转存成功但未能定位转存后的文件 ID: {suffix}")
        restored_ids = [
            id_map[file_id]
            for file_id in file_ids
            if id_map.get(file_id) and id_map.get(file_id) != file_id
        ]
        if restored_ids and parent_id and hasattr(client, "file_batch_move"):
            with contextlib.suppress(Exception):
                await client.file_batch_move(restored_ids, to_parent_id=parent_id)
        if account:
            with contextlib.suppress(Exception):
                self._pikpak_status_cache_write(
                    self._pikpak_public_status(
                        account,
                        success=True,
                        ready=True,
                        quota=self._normalize_pikpak_quota(await client.get_quota_info()),
                        source="copy",
                        cached=False,
                        updated_at=datetime.now(),
                    ),
                    account,
                    source="copy",
                )
        return id_map

    async def _copy_pikpak_share_files_multi(
        self,
        collector_client,
        file_ids: List[str],
        share_files: Optional[List[Dict[str, Any]]] = None,
        *,
        share_link: str = "",
        share_id: str = "",
        pass_code_token: str = "",
    ) -> tuple[Dict[str, str], Dict[str, PikPakAccount]]:
        source_id_map = {str(item): str(item) for item in file_ids if str(item or "").strip()}
        account_by_source: Dict[str, PikPakAccount] = {}
        if not file_ids:
            return source_id_map, account_by_source

        accounts = self._pikpak_accounts()
        if not accounts:
            raise HttpDownloadError("PikPak 未配置可用账号或 token")

        item_by_id: Dict[str, Dict[str, Any]] = {}
        for item in list(share_files or []):
            file_id = self._pikpak_file_id(item)
            if file_id:
                item_by_id[file_id] = item
        file_rows = [
            {
                "id": file_id,
                "size": self._pikpak_file_size(item_by_id.get(file_id, {})),
            }
            for file_id in file_ids
            if str(file_id or "").strip()
        ]
        if not file_rows:
            return source_id_map, account_by_source

        clients: Dict[str, Any] = {}
        quotas: Dict[str, Dict[str, Any]] = {}
        failures: Dict[str, str] = {}
        collector_account_id = getattr(getattr(collector_client, "_kikoeru_pikpak_account", None), "id", None)
        try:
            for account in accounts:
                try:
                    if account.id == collector_account_id:
                        client = collector_client
                    else:
                        client = await self._pikpak_client(account=account)
                    clients[account.id] = client
                    quotas[account.id] = self._normalize_pikpak_quota(await client.get_quota_info())
                except Exception as exc:
                    failures[account.id] = self._sanitize_error(exc)

            available_accounts = [
                account
                for account in accounts
                if account.id in clients and int((quotas.get(account.id) or {}).get("limit_bytes") or 0) > 0
            ]
            if not available_accounts:
                if len(accounts) == 1:
                    return await self._copy_pikpak_share_files(
                        collector_client,
                        file_ids,
                        share_files,
                        account=accounts[0],
                        share_id=share_id or (self._pikpak_share_id_from_url(share_link) if share_link else ""),
                        pass_code_token=pass_code_token,
                    ), {file_id: accounts[0] for file_id in file_ids}
                detail = "；".join(f"{account.label}: {failures.get(account.id, '无法读取容量')}" for account in accounts)
                raise HttpDownloadError(f"PikPak 无法读取任何账号容量，不能安全分配转存。{detail}")

            remaining = {
                account.id: int((quotas.get(account.id) or {}).get("remaining_bytes") or 0)
                for account in available_accounts
            }
            assigned: Dict[str, List[str]] = {account.id: [] for account in available_accounts}
            unassigned: List[Dict[str, Any]] = []
            for row in sorted(file_rows, key=lambda item: int(item.get("size") or 0), reverse=True):
                size = int(row.get("size") or 0)
                candidates = sorted(available_accounts, key=lambda account: remaining.get(account.id, 0), reverse=True)
                target = next((account for account in candidates if size <= 0 or remaining.get(account.id, 0) >= size), None)
                if not target:
                    unassigned.append(row)
                    continue
                assigned[target.id].append(str(row["id"]))
                if size > 0:
                    remaining[target.id] = max(0, remaining.get(target.id, 0) - size)

            if unassigned:
                need = sum(int(item.get("size") or 0) for item in unassigned)
                quota_text = "；".join(
                    f"{account.label} 剩余 {self._format_bytes_for_error(int((quotas.get(account.id) or {}).get('remaining_bytes') or 0))}"
                    for account in available_accounts
                )
                raise HttpDownloadError(
                    f"PikPak 多账号空间仍不足: 未能分配 {len(unassigned)} 个文件，共 {self._format_bytes_for_error(need)}。{quota_text}。请清理空间或添加账号。"
                )

            for account in available_accounts:
                ids_for_account = assigned.get(account.id) or []
                if not ids_for_account:
                    continue
                client = clients[account.id]
                account_share_id = share_id or (self._pikpak_share_id_from_url(share_link) if share_link else "")
                account_token = pass_code_token
                if account.id != collector_account_id and share_link:
                    account_share_id, account_token = await self._touch_pikpak_share(client, share_link, account=account)
                id_map = await self._copy_pikpak_share_files(
                    client,
                    ids_for_account,
                    [item_by_id.get(file_id, {"id": file_id}) for file_id in ids_for_account],
                    account=account,
                    share_id=account_share_id,
                    pass_code_token=account_token,
                )
                source_id_map.update(id_map)
                for file_id in ids_for_account:
                    account_by_source[file_id] = account
            return source_id_map, account_by_source
        finally:
            for account_id, client in list(clients.items()):
                if account_id != collector_account_id:
                    await self._close_pikpak_client(client)

    def _format_bytes_for_error(self, value: Any) -> str:
        size = float(self._int_value(value))
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        if index == 0:
            return f"{int(size)} {units[index]}"
        return f"{size:.1f} {units[index]}"

    async def _pikpak_download_link(self, client, file_id: str, *, allow_missing: bool = False, max_attempts: int = 5) -> Dict[str, Any]:
        # captcha/init 对副账号偶发 400，单次失败极易丢分卷。下载阶段多次重试(失败则重新登录刷新匹配 token + 退避)，
        # 预览阶段(allow_missing)只试一次保持响应速度。
        attempts = 1 if allow_missing else max(1, max_attempts)
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            info: Any = None
            try:
                info = await client.get_download_url(file_id)
            except Exception as exc:
                last_error = exc
                info = None
            if isinstance(info, dict):
                url = str(info.get("web_content_link") or "").strip()
                if not url:
                    media = list(info.get("medias") or [])
                    if media:
                        link = media[0].get("link") if isinstance(media[0], dict) else None
                        if isinstance(link, dict):
                            url = str(link.get("url") or "").strip()
                if url:
                    info["_download_url"] = url
                    return info
                last_error = HttpDownloadError("PikPak 未返回可下载链接，可能需要会员权限或文件仍在转码/审核")
            if attempt < attempts:
                account = getattr(client, "_kikoeru_pikpak_account", None)
                if account and account.username and account.password and account.password != "********":
                    with contextlib.suppress(Exception):
                        await self._refresh_pikpak_login_with_password(client, account, stage="解析下载直链")
                await asyncio.sleep(min(1.0 * attempt, 4.0))
        if allow_missing:
            return {}
        if isinstance(last_error, HttpDownloadError):
            raise last_error
        if last_error is not None:
            raise self._pikpak_error(last_error, "解析下载直链") from last_error
        raise HttpDownloadError("PikPak 解析下载直链失败")

    def _selection_filter_from_items(self, items: Optional[List[Dict[str, Any]]]) -> Optional[set[str]]:
        keys: set[str] = set()
        for item in items or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip().lower()
            if source not in _SHARE_PREVIEW_ONLY_SOURCES:
                continue
            for field in ("file_id", "content_id", "download_file_id", "transferit_node_handle"):
                value = str(item.get(field) or "").strip()
                if value:
                    keys.add(f"{source}:id:{value}")
            for field in ("relative_path", "relative_dir", "filename", "name"):
                value = str(item.get(field) or "").strip().replace("\\", "/").strip("/")
                if value:
                    keys.add(f"{source}:path:{value.lower()}")
        return keys or None

    def _share_item_matches_selection(self, source: str, item: Dict[str, Any], selection_filter: Optional[set[str]]) -> bool:
        if not selection_filter:
            return True
        source_name = str(source or "").strip().lower()
        file_id = str(item.get("id") or item.get("file_id") or item.get("content_id") or item.get("download_file_id") or item.get("transferit_node_handle") or "").strip()
        if file_id and f"{source_name}:id:{file_id}" in selection_filter:
            return True
        name = str(item.get("name") or item.get("filename") or "").strip().replace("\\", "/").strip("/")
        relative_dir = str(item.get("_relative_dir") or item.get("relative_dir") or "").strip().replace("\\", "/").strip("/")
        relative_path = "/".join(part for part in (relative_dir, name) if part).strip("/")
        for value in (relative_path, relative_dir, name):
            if value and f"{source_name}:path:{value.lower()}" in selection_filter:
                return True
        return False

    def _retry_selection_items_from_task_metadata(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        completed_keys = {
            self._download_attempt_row_key(row)
            for row in list(metadata.get("download_files") or [])
            if (
                isinstance(row, dict)
                and str(row.get("status") or "").strip().lower() == "completed"
            )
        }

        def add_row(row: Dict[str, Any]) -> None:
            if not isinstance(row, dict):
                return
            row_key = self._download_attempt_row_key(row)
            if row_key and row_key in completed_keys:
                return
            source = str(row.get("source") or "").strip().lower()
            if not source:
                return
            if source == "transferit":
                identity = self._transferit_row_identity(row)
            else:
                identity = (
                    str(row.get("file_id") or "").strip()
                    or str(row.get("download_file_id") or "").strip()
                    or str(row.get("relative_path") or "").strip()
                    or str(row.get("name") or row.get("filename") or "").strip()
                )
            key = f"{source}:{identity}" if identity else json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                return
            seen.add(key)
            rows.append(dict(row))

        for row in list(metadata.get("failed_files") or []):
            if isinstance(row, dict):
                add_row(row)
        for row in list(metadata.get("download_files") or []):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            progress = int(row.get("progress") or 0)
            total = int(row.get("total") or row.get("size") or 0)
            downloaded = int(row.get("downloaded") or 0)
            if status == "completed" or progress >= 100 or (total > 0 and downloaded >= total):
                continue
            add_row(row)
        return rows

    def build_retry_selection_for_file(self, task, file_row: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
        if not isinstance(file_row, dict):
            return [], []
        metadata = dict(getattr(task, "task_metadata", None) or {})
        candidates = self._retry_selection_items_from_task_metadata(metadata)
        wanted_key = self._download_attempt_row_key(file_row)
        wanted_selection_key = self._preview_item_selection_key(file_row)
        wanted_relative = str(file_row.get("relative_path") or "").strip().replace("\\", "/").strip("/").lower()
        wanted_name = str(file_row.get("name") or file_row.get("filename") or "").strip().lower()
        wanted_file_id = str(file_row.get("file_id") or file_row.get("download_file_id") or "").strip()

        def matches(row: Dict[str, Any]) -> bool:
            row_key = self._download_attempt_row_key(row)
            if wanted_key and row_key == wanted_key:
                return True
            if wanted_selection_key and self._preview_item_selection_key(row) == wanted_selection_key:
                return True
            if wanted_file_id and wanted_file_id in {
                str(row.get("file_id") or "").strip(),
                str(row.get("download_file_id") or "").strip(),
            }:
                return True
            row_relative = str(row.get("relative_path") or "").strip().replace("\\", "/").strip("/").lower()
            if wanted_relative and row_relative == wanted_relative:
                return True
            row_name = str(row.get("name") or row.get("filename") or "").strip().lower()
            return bool(wanted_name and row_name == wanted_name)

        retry_items = [dict(row) for row in candidates if isinstance(row, dict) and matches(row)]
        if not retry_items:
            retry_items = [dict(file_row)]
        retry_keys = [
            self._preview_item_selection_key(item)
            for item in retry_items
            if self._preview_item_selection_key(item)
        ]
        return retry_items, retry_keys

    def _download_attempt_row_key(self, row: Dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        source = str(row.get("source") or "http").strip().lower() or "http"
        if source == "transferit":
            identity = self._transferit_row_identity(row) or str(row.get("share_id") or "").strip()
        else:
            identity = (
                str(row.get("file_id") or "").strip()
                or str(row.get("download_file_id") or "").strip()
                or str(row.get("pikpak_cleanup_file_id") or "").strip()
                or str(row.get("share_id") or "").strip()
                or str(row.get("relative_path") or "").strip()
                or str(row.get("local_path") or "").strip()
                or str(row.get("name") or row.get("filename") or "").strip()
            )
        if identity:
            return f"{source}:{identity}"
        return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)

    def merge_download_attempt_rows(self, *groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge rows from original download + retry attempts, with later attempts winning."""
        merged: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for group in groups:
            for row in group or []:
                if not isinstance(row, dict):
                    continue
                key = self._download_attempt_row_key(row)
                if not key:
                    continue
                if key not in merged:
                    order.append(key)
                next_row = {**merged.get(key, {}), **dict(row)}
                if str(next_row.get("status") or "").strip().lower() == "completed":
                    for stale_key in ("failure_reason", "reason", "error_message"):
                        next_row.pop(stale_key, None)
                merged[key] = next_row
        return [merged[key] for key in order if key in merged]

    def merge_download_failed_rows(
        self,
        download_files: List[Dict[str, Any]],
        failed_files: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        completed_keys = {
            self._download_attempt_row_key(item)
            for item in list(download_files or [])
            if (
                isinstance(item, dict)
                and str(item.get("status") or "").strip().lower() == "completed"
            )
        }
        for row in list(failed_files or []) + [
            item for item in list(download_files or [])
            if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "failed"
        ]:
            if not isinstance(row, dict):
                continue
            key = self._download_attempt_row_key(row)
            if key and key in completed_keys:
                continue
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            rows.append(dict(row))
        return rows

    def build_retry_selection_for_task(self, task) -> tuple[List[Dict[str, Any]], List[str]]:
        metadata = dict(getattr(task, "task_metadata", None) or {})
        retry_items = self._retry_selection_items_from_task_metadata(metadata)
        retry_keys = [
            self._preview_item_selection_key(item)
            for item in retry_items
            if self._preview_item_selection_key(item)
        ]
        return retry_items, retry_keys

    async def resolve_source_urls(
        self,
        urls: List[str],
        *,
        materialize: bool = False,
        selected_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        resolved: List[str] = []
        source_items: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        selection_filter = self._selection_filter_from_items(selected_items)
        direct_links = [
            url
            for url in urls
            if self._provider_source(url) == "http"
        ]
        resolved.extend(direct_links)
        for url in direct_links:
            source_items.append({"source": "http", "url": url, "masked_url": self._mask_url(url)})

        gofile_links = [url for url in urls if self._is_gofile_url(url)]
        for raw_url in gofile_links:
            try:
                data = await self._collect_gofile_files(raw_url)
                files = data.get("files") or []
                if not files:
                    failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "Gofile 分享中没有可下载文件", "source": "gofile"})
                    continue
                for item in files:
                    download_url = str(item.get("url") or "")
                    if not download_url:
                        continue
                    resolved.append(download_url)
                    source_items.append(item)
            except Exception as exc:
                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "gofile"})

        onedrive_links = [url for url in urls if self._is_onedrive_url(url)]
        for raw_url in onedrive_links:
            try:
                direct_url = self._onedrive_direct_url(raw_url)
                resolved.append(direct_url)
                source_items.append({
                    "source": "onedrive",
                    "share_url": self._mask_url(raw_url),
                    "url": direct_url,
                    "masked_url": self._mask_url(direct_url),
                })
            except Exception as exc:
                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "onedrive"})

        google_links = [url for url in urls if self._is_google_drive_url(url)]
        for raw_url in google_links:
            try:
                if self._google_drive_is_folder_url(raw_url):
                    data = await self._collect_google_drive_folder_files(raw_url)
                    files = data.get("files") or []
                    if not files:
                        failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "Google Drive 文件夹中没有可下载文件", "source": "google_drive"})
                        continue
                    for item in files:
                        download_url = str(item.get("url") or "")
                        if not download_url:
                            continue
                        resolved.append(download_url)
                        source_items.append(item)
                else:
                    if self._google_drive_oauth_enabled():
                        try:
                            item = await self._google_drive_api_single_file_item(raw_url)
                            direct_url = str(item.get("url") or "")
                            if direct_url:
                                resolved.append(direct_url)
                            source_items.append(item)
                            continue
                        except Exception as api_exc:
                            logger.warning("[HTTP下载] Google Drive API 解析文件失败，回退直链: %s", self._sanitize_error(api_exc))
                    direct_url = self._google_drive_direct_url(raw_url)
                    resolved.append(direct_url)
                    source_items.append({
                        "source": "google_drive",
                        "share_url": self._mask_url(raw_url),
                        "url": direct_url,
                        "masked_url": self._mask_url(direct_url),
                        "file_id": self._google_drive_file_id_from_url(raw_url),
                        "resource_key": self._google_drive_resource_key_from_url(raw_url),
                    })
            except Exception as exc:
                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "google_drive"})

        transferit_links = [url for url in urls if self._is_transferit_url(url)]
        for raw_url in transferit_links:
            try:
                data = await self._collect_transferit_files(raw_url)
                files = data.get("files") or []
                if not files:
                    failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "Transfer.it 分享中没有可下载文件", "source": "transferit"})
                    continue
                source_items.extend(files)
            except Exception as exc:
                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "transferit"})

        pikpak_links = [url for url in urls if self._is_pikpak_url(url)]
        if pikpak_links:
            collector_account = self._select_pikpak_account()
            client = await self._pikpak_client(account=collector_account)
            try:
                for raw_url in pikpak_links:
                    try:
                        download_clients: Dict[str, Any] = {}
                        info, files = await self._collect_pikpak_share_files(client, raw_url)
                        if not files:
                            failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "PikPak 分享中没有可下载文件", "source": "pikpak"})
                            continue
                        share_id = str(info.get("share_id") or self._pikpak_share_id_from_url(raw_url))
                        pass_code_token = str(info.get("pass_code_token") or "")
                        if selection_filter:
                            files = [
                                item for item in files
                                if self._share_item_matches_selection("pikpak", item, selection_filter)
                            ]
                            if not files:
                                continue
                        file_ids = []
                        for item in files:
                            file_id = str(item.get("id") or item.get("file_id") or "")
                            if file_id and file_id not in file_ids:
                                file_ids.append(file_id)
                        copied_id_map = {item: item for item in file_ids}
                        account_by_source: Dict[str, PikPakAccount] = {item: collector_account for item in file_ids}
                        download_clients = {collector_account.id: client}
                        if materialize and bool(getattr(self._config(), "pikpak_auto_save_share", True)):
                            copied_id_map, account_by_source = await self._copy_pikpak_share_files_multi(
                                client,
                                file_ids,
                                files,
                                share_link=raw_url,
                                share_id=share_id,
                                pass_code_token=pass_code_token,
                            )
                            for account in account_by_source.values():
                                if account.id not in download_clients:
                                    download_clients[account.id] = await self._pikpak_client(account=account)
                        for item in files:
                            file_id = str(item.get("id") or item.get("file_id") or "")
                            if not file_id:
                                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "PikPak 文件缺少 file_id", "source": "pikpak"})
                                continue
                            download_file_id = copied_id_map.get(file_id, file_id)
                            item_account = account_by_source.get(file_id) or collector_account
                            detail_client = download_clients.get(item_account.id) or client
                            item_name = self._sanitize_filename(item.get("name") or "pikpak-file")
                            try:
                                detail = await self._pikpak_download_link(detail_client, download_file_id, allow_missing=not materialize)
                            except Exception as item_exc:
                                # 单个分卷解析失败不再跳出整批，记录后继续，避免静默丢掉后续分卷
                                failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": f"{item_name}: {self._sanitize_error(item_exc)}", "source": "pikpak", "name": item_name, "filename": item_name, "file_id": file_id})
                                continue
                            download_url = str(detail.get("_download_url") or "")
                            name = self._sanitize_filename(detail.get("name") or item.get("name") or "pikpak-file")
                            relative_dir = str(item.get("_relative_dir") or "").strip("/")
                            if download_url:
                                resolved.append(download_url)
                            pikpak_materialized = bool(
                                materialize
                                and getattr(self._config(), "pikpak_auto_save_share", True)
                                and download_file_id
                                and download_file_id != file_id
                            )
                            source_items.append({
                                "source": "pikpak",
                                "share_url": self._mask_url(raw_url),
                                "url": self._mask_url(download_url) if download_url else self._mask_url(raw_url),
                                "original_url": download_url,
                                "file_id": file_id,
                                "download_file_id": download_file_id,
                                "pikpak_cleanup_file_id": download_file_id if pikpak_materialized else "",
                                "pikpak_materialized": pikpak_materialized,
                                "name": name,
                                "filename": name,
                                "relative_dir": relative_dir,
                                "size_bytes": self._pikpak_file_size(detail) or self._pikpak_file_size(item),
                                "share_id": share_id,
                                "pikpak_account_id": item_account.id,
                                "pikpak_account_label": item_account.label,
                                "pikpak_transfer_dir": item_account.transfer_dir,
                            })
                            if not download_url:
                                source_items[-1]["preview_only"] = True
                    except Exception as exc:
                        failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "pikpak"})
                    finally:
                        for account_id, detail_client in list(download_clients.items()):
                            if account_id != collector_account.id:
                                await self._close_pikpak_client(detail_client)
            finally:
                await self._close_pikpak_client(client)

        modes = []
        for url in urls:
            mode = self._provider_source(url)
            if mode not in modes:
                modes.append(mode)
        return {"urls": resolved, "source_items": source_items, "failed_items": failed, "source_modes": modes}

    def _sanitize_filename(self, name: str, fallback: str = "download.bin") -> str:
        text = unquote(str(name or "").strip()).replace("\\", "/").rsplit("/", 1)[-1].strip()
        text = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", text)
        text = text.strip(" .")
        return text[:180] or fallback

    def _safe_subdir(self, value: str) -> str:
        parts = []
        for part in Path(str(value or "").replace("\\", "/")).parts:
            if part == "..":
                raise HttpDownloadError("目标子目录不能包含上级路径")
            if part in {"", "."}:
                continue
            safe = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", part).strip(" .")
            if safe:
                parts.append(safe[:80])
        return os.path.join(*parts) if parts else ""

    def _safe_join(self, root: str, *parts: str) -> str:
        root_abs = os.path.abspath(root)
        target = os.path.abspath(os.path.join(root_abs, *[p for p in parts if p]))
        try:
            common = os.path.commonpath([root_abs, target])
        except ValueError as exc:
            raise HttpDownloadError("目标路径越界") from exc
        if common != root_abs:
            raise HttpDownloadError("目标路径不能跳出下载根目录")
        return target

    def _filename_from_headers(self, headers: Dict[str, str]) -> str:
        disposition = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
        match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
        if match:
            return self._sanitize_filename(match.group(1))
        match = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
        if match:
            return self._sanitize_filename(match.group(1))
        return ""

    def _filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        candidate = self._sanitize_filename(parsed.path.rsplit("/", 1)[-1] or "")
        if candidate and "." in candidate:
            return candidate
        guessed = mimetypes.guess_extension(mimetypes.guess_type(candidate)[0] or "") or ""
        return candidate + guessed if candidate else "download.bin"

    def _append_collision_suffix(self, path: str) -> str:
        base, ext = os.path.splitext(path)
        index = 1
        candidate = path
        while os.path.exists(candidate) or os.path.exists(candidate + ".aria2"):
            candidate = f"{base} ({index}){ext}"
            index += 1
        return candidate

    def _resolve_target(self, filename: str, target_subdir: str = "", conflict_policy: str = "") -> Dict[str, str]:
        cfg = self._config()
        root = self._download_root()
        subdir = self._safe_subdir(target_subdir)
        target_dir = self._safe_join(root, subdir)
        safe_name = self._sanitize_filename(filename)
        final_path = self._safe_join(target_dir, safe_name)
        policy = str(conflict_policy or getattr(cfg, "conflict_policy", "resume") or "resume").strip().lower()
        if policy == "rename" and (os.path.exists(final_path) or os.path.exists(final_path + ".aria2")):
            final_path = self._append_collision_suffix(final_path)
            safe_name = os.path.basename(final_path)
        elif policy == "skip" and os.path.exists(final_path):
            raise HttpDownloadError(f"目标文件已存在: {final_path}")
        return {
            "download_root": root,
            "target_dir": target_dir,
            "filename": safe_name,
            "final_path": final_path,
            "relative_path": os.path.relpath(final_path, root).replace("\\", "/"),
        }

    def _split_custom_archive_filename(self, filename: str) -> tuple[str, str]:
        value = str(filename or "").strip()
        lower = value.lower()
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if lower.endswith(suffix):
                return value[:-len(suffix)], value[-len(suffix):]
        volume_match = re.match(r"^(?P<stem>.+?)[._\-\s]+z(?P<index>\d{2})$", value, re.IGNORECASE)
        if volume_match:
            return volume_match.group("stem").strip() or value, f".z{volume_match.group('index')}"
        stem, ext = os.path.splitext(value)
        return stem or value, ext

    def _filename_with_extract_password(self, name: str, password: str, ext: str = "") -> str:
        safe_name = self._sanitize_filename(name, "download")
        safe_password = self._sanitize_filename(password, "")
        if safe_password:
            safe_name = self._render_filename_password_template(safe_name, safe_password)
        return f"{safe_name}{ext or ''}"

    def _render_filename_password_template(self, name: str, password: str) -> str:
        extract_config = getattr(get_config(), "extract", None)
        templates = list(getattr(extract_config, "filename_password_sniff_templates", None) or [])
        for template in templates:
            raw = str(template or "").strip()
            if not raw or "{password}" not in raw:
                continue
            rendered = raw.replace("{name}", name).replace("{password}", password)
            if "{name}" not in raw:
                rendered = f"{name}{rendered}"
            rendered = self._sanitize_filename(rendered, "")
            if rendered:
                return rendered
        return f"{name}({password})"

    def _apply_custom_download_name_to_item(
        self,
        item: Dict[str, Any],
        *,
        conflict_policy: str = "",
    ) -> Dict[str, Any]:
        custom_name = str(item.get("custom_name") or item.get("custom_filename") or "").strip()
        custom_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        if not custom_name and not custom_password:
            return item

        current_name = self._sanitize_filename(item.get("filename") or item.get("name") or "download.bin")
        stem, ext = self._split_custom_archive_filename(current_name)
        if not custom_name:
            custom_name = stem or current_name
        else:
            custom_stem, custom_ext = self._split_custom_archive_filename(custom_name)
            if custom_ext:
                custom_name = custom_stem
                ext = custom_ext
        safe_custom_name = self._sanitize_filename(custom_name, stem or "download")
        use_group_folder = bool(item.get("custom_group_folder"))
        target_name = f"{safe_custom_name}{ext or ''}" if use_group_folder else self._filename_with_extract_password(safe_custom_name, custom_password, ext)
        relative_path = str(item.get("relative_path") or current_name).replace("\\", "/").strip("/")
        parent = os.path.dirname(relative_path.replace("/", os.sep))
        if use_group_folder:
            folder_name = self._filename_with_extract_password(safe_custom_name, custom_password, "")
            parent = os.path.join(parent, folder_name) if parent else folder_name

        root = self._download_root()
        target_dir = self._safe_join(root, self._safe_subdir(parent))
        final_path = self._safe_join(target_dir, target_name)
        policy = str(conflict_policy or getattr(self._config(), "conflict_policy", "resume") or "resume").strip().lower()
        if policy == "rename" and (os.path.exists(final_path) or os.path.exists(final_path + ".aria2")):
            final_path = self._append_collision_suffix(final_path)
            target_name = os.path.basename(final_path)
        elif policy == "skip" and os.path.exists(final_path):
            raise HttpDownloadError(f"目标文件已存在: {final_path}")

        next_item = dict(item)
        next_item.update({
            "filename": target_name,
            "name": target_name,
            "relative_path": os.path.relpath(final_path, root).replace("\\", "/"),
            "final_path": final_path,
            "target_dir": os.path.dirname(final_path),
            "custom_rename_applied": True,
        })
        return next_item

    async def _preview_google_drive_download_item(
        self,
        source_item: Dict[str, Any],
        *,
        target_subdir: str = "",
        conflict_policy: str = "",
    ) -> Dict[str, Any]:
        raw_url = str(source_item.get("url") or source_item.get("original_url") or "").strip()
        if not raw_url:
            raise HttpDownloadError("Google Drive 下载缺少直链")
        probe = await self._google_drive_probe_download(raw_url)
        status = int(probe.get("status") or 0)
        if status >= 400:
            raise HttpDownloadError(f"Google Drive 返回 HTTP {status}")
        content_type = str(probe.get("content_type") or "")
        if "text/html" in content_type.lower():
            raise HttpDownloadError(str(source_item.get("warning") or "Google Drive 返回 HTML 页面，确认参数或访问权限已失效"))
        filename = (
            self._filename_from_headers({"content-disposition": str(probe.get("content_disposition") or "")})
            or self._sanitize_filename(source_item.get("filename") or source_item.get("name") or "google-drive-file")
        )
        subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
        target = self._resolve_target(filename, subdir, conflict_policy)
        return {
            "ok": True,
            "url": str(probe.get("url") or raw_url),
            "masked_url": source_item.get("masked_url") or self._mask_url(str(probe.get("url") or raw_url)),
            "host": urlparse(str(probe.get("url") or raw_url)).hostname or "drive.usercontent.google.com",
            "source": "google_drive",
            "share_url": source_item.get("share_url"),
            "filename": target["filename"],
            "relative_path": target["relative_path"],
            "final_path": target["final_path"],
            "target_dir": target["target_dir"],
            "size_bytes": int(probe.get("content_length") or source_item.get("size_bytes") or 0),
            "content_type": content_type,
            "resumable": "bytes" in str(probe.get("content_range") or "").lower(),
            "warning": source_item.get("warning") or "",
        }

    async def preview_urls(
        self,
        urls: List[str],
        target_subdir: str = "",
        conflict_policy: str = "",
        *,
        materialize_sources: bool = False,
        selected_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        try:
            source = await self.resolve_source_urls(
                urls,
                materialize=materialize_sources,
                selected_items=selected_items,
            )
        except TypeError as exc:
            if "selected_items" not in str(exc):
                raise
            source = await self.resolve_source_urls(urls, materialize=materialize_sources)
        items = []
        source_by_url = {}
        for source_item in source.get("source_items") or []:
            if not isinstance(source_item, dict):
                continue
            raw = str(source_item.get("original_url") or source_item.get("url") or "").strip()
            if raw and not source_item.get("preview_only"):
                source_by_url.setdefault(raw, source_item)
        for raw_url in source.get("urls") or []:
            source_item = source_by_url.get(str(raw_url or "").strip())
            preview_url = raw_url
            if isinstance(source_item, dict) and source_item.get("source") == "google_drive":
                if source_item.get("google_drive_api"):
                    filename = self._sanitize_filename(source_item.get("filename") or source_item.get("name") or "google-drive-file")
                    subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
                    target = self._resolve_target(filename, subdir, conflict_policy)
                    item = {
                        "ok": True,
                        "url": str(source_item.get("url") or raw_url),
                        "masked_url": source_item.get("masked_url") or self._mask_url(str(source_item.get("url") or raw_url)),
                        "host": "www.googleapis.com",
                        "source": "google_drive",
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                        "size_bytes": int(source_item.get("size_bytes") or 0),
                        "content_type": str(source_item.get("content_type") or ""),
                        "resumable": True,
                        "warning": source_item.get("warning") or "Google Drive 已使用 OAuth Drive API 下载。",
                    }
                else:
                    try:
                        drive_resolved = await self._google_drive_resolve_confirm_url(raw_url)
                        if drive_resolved.get("url"):
                            preview_url = str(drive_resolved.get("url") or raw_url)
                            source_item["url"] = preview_url
                            source_item["original_url"] = preview_url
                            source_item["masked_url"] = self._mask_url(preview_url)
                        if drive_resolved.get("size_bytes"):
                            source_item["size_bytes"] = int(drive_resolved.get("size_bytes") or 0)
                        if drive_resolved.get("content_type"):
                            source_item["content_type"] = str(drive_resolved.get("content_type") or "")
                        if drive_resolved.get("filename"):
                            source_item["filename"] = str(drive_resolved.get("filename") or "")
                            source_item["name"] = str(drive_resolved.get("filename") or "")
                        if drive_resolved.get("warning"):
                            source_item["warning"] = str(drive_resolved.get("warning") or "")
                        if drive_resolved.get("headers"):
                            existing_headers = dict(source_item.get("headers") or {})
                            existing_headers.update(dict(drive_resolved.get("headers") or {}))
                            source_item["headers"] = existing_headers
                        if drive_resolved.get("aria2_header"):
                            existing_aria2_headers = [
                                str(header).strip()
                                for header in list(source_item.get("aria2_header") or [])
                                if str(header or "").strip()
                            ]
                            for header in list(drive_resolved.get("aria2_header") or []):
                                header_text = str(header or "").strip()
                                if header_text and header_text not in existing_aria2_headers:
                                    existing_aria2_headers.append(header_text)
                            source_item["aria2_header"] = existing_aria2_headers
                    except Exception as exc:
                        source_item["google_drive_confirm_error"] = self._sanitize_error(exc)
                    try:
                        item = await self._preview_google_drive_download_item(
                            source_item,
                            target_subdir=target_subdir,
                            conflict_policy=conflict_policy,
                        )
                    except Exception:
                        item = await self.preview_url(
                            preview_url,
                            target_subdir=target_subdir,
                            conflict_policy=conflict_policy,
                            headers=dict(source_item.get("headers") or {}) if isinstance(source_item, dict) else None,
                        )
            else:
                item = await self.preview_url(
                    preview_url,
                    target_subdir=target_subdir,
                    conflict_policy=conflict_policy,
                    headers=dict(source_item.get("headers") or {}) if isinstance(source_item, dict) else None,
                )
            if isinstance(source_item, dict) and source_item.get("source") == "gofile":
                gofile_failure_reason = self._gofile_cdn_preview_failure_reason(item, source_item)
                if gofile_failure_reason:
                    item = {
                        "ok": False,
                        "url": str(source_item.get("url") or raw_url),
                        "masked_url": source_item.get("masked_url") or self._mask_url(str(source_item.get("url") or raw_url)),
                        "reason": gofile_failure_reason,
                        "source": "gofile",
                        "share_url": source_item.get("share_url"),
                        "filename": source_item.get("filename") or source_item.get("name"),
                        "size_bytes": int(source_item.get("size_bytes") or 0),
                        "content_id": source_item.get("content_id"),
                    }
            if (
                isinstance(source_item, dict)
                and not item.get("ok")
                and source_item.get("source") in {"gofile", "google_drive"}
                and source_item.get("filename")
            ):
                if source_item.get("source") == "gofile":
                    items.append(item)
                    continue
                try:
                    subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
                    source_name = str(source_item.get("source") or "http")
                    fallback_name = "gofile-file" if source_name == "gofile" else "google-drive-file"
                    target = self._resolve_target(str(source_item.get("filename") or fallback_name), subdir, conflict_policy)
                    item = {
                        "ok": True,
                        "url": str(source_item.get("url") or raw_url),
                        "masked_url": source_item.get("masked_url") or self._mask_url(str(source_item.get("url") or raw_url)),
                        "host": urlparse(str(source_item.get("url") or raw_url)).hostname or ("gofile.io" if source_name == "gofile" else "drive.google.com"),
                        "source": source_name,
                        "share_url": source_item.get("share_url"),
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                        "size_bytes": int(source_item.get("size_bytes") or 0),
                        "content_type": str(source_item.get("content_type") or ""),
                        "resumable": True,
                        "warning": (
                            "Gofile CDN 未响应预览探测，已使用 API 返回的文件名和大小创建下载项。"
                            if source_name == "gofile"
                            else "Google Drive 未响应预览探测，已使用文件夹页返回的文件名和大小创建下载项。"
                        ),
                    }
                except Exception as exc:
                    item["reason"] = self._sanitize_error(exc) or exc.__class__.__name__
            if source_item and item.get("ok"):
                item["source"] = str(source_item.get("source") or item.get("source") or "http")
                if source_item.get("share_url"):
                    item["share_url"] = source_item.get("share_url")
                if source_item.get("source") == "google_drive" and source_item.get("filename"):
                    filename = self._sanitize_filename(source_item.get("filename") or source_item.get("name") or item.get("filename") or "google-drive-file")
                    subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
                    target = self._resolve_target(filename, subdir, conflict_policy)
                    item.update({
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                    })
                for meta_key in (
                    "content_id",
                    "file_id",
                    "download_file_id",
                    "pikpak_cleanup_file_id",
                    "pikpak_materialized",
                    "share_id",
                    "pikpak_account_id",
                    "pikpak_account_label",
                    "pikpak_transfer_dir",
                    "resource_key",
                    "google_drive_api",
                ):
                    if source_item.get(meta_key) is not None and source_item.get(meta_key) != "":
                        item[meta_key] = source_item.get(meta_key)
                relative_dir = str(source_item.get("relative_dir") or "").strip("/")
                if relative_dir:
                    filename = self._sanitize_filename(source_item.get("filename") or source_item.get("name") or item.get("filename") or "download.bin")
                    subdir = "/".join([part for part in (target_subdir, relative_dir) if str(part or "").strip()])
                    target = self._resolve_target(filename, subdir, conflict_policy)
                    item.update({
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                    })
                if source_item.get("size_bytes") and not int(item.get("size_bytes") or 0):
                    item["size_bytes"] = int(source_item.get("size_bytes") or 0)
                if source_item.get("warning"):
                    item["warning"] = source_item.get("warning")
                if source_item.get("aria2_header"):
                    item["aria2_header"] = list(source_item.get("aria2_header") or [])
                if source_item.get("headers"):
                    item["headers"] = dict(source_item.get("headers") or {})
            items.append(item)
        for source_item in source.get("source_items") or []:
            if (
                not isinstance(source_item, dict)
                or source_item.get("source") not in _SHARE_PREVIEW_ONLY_SOURCES
                or not source_item.get("preview_only")
            ):
                continue
            source_name = str(source_item.get("source") or "http")
            if materialize_sources and source_name != "transferit":
                continue
            if not materialize_sources or source_name == "transferit":
                filename = self._sanitize_filename(source_item.get("filename") or source_item.get("name") or f"{source_name}-file")
                subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
                try:
                    target = self._resolve_target(filename, subdir, conflict_policy)
                    items.append({
                        "ok": True,
                        "url": source_item.get("url") or source_item.get("share_url") or "",
                        "masked_url": source_item.get("share_url") or "",
                        "original_url": source_item.get("original_url") or source_item.get("url") or source_item.get("share_url") or "",
                        "host": "transfer.it" if source_name == "transferit" else "mypikpak.com",
                        "source": source_name,
                        "share_url": source_item.get("share_url"),
                        "file_id": source_item.get("file_id"),
                        "download_file_id": source_item.get("download_file_id"),
                        "pikpak_cleanup_file_id": source_item.get("pikpak_cleanup_file_id"),
                        "pikpak_materialized": bool(source_item.get("pikpak_materialized")),
                        "share_id": source_item.get("share_id"),
                        "transferit_node_handle": source_item.get("transferit_node_handle"),
                        "pikpak_account_id": source_item.get("pikpak_account_id"),
                        "pikpak_account_label": source_item.get("pikpak_account_label"),
                        "pikpak_transfer_dir": source_item.get("pikpak_transfer_dir"),
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                        "size_bytes": int(source_item.get("size_bytes") or 0),
                        "content_type": "",
                        "resumable": source_name != "transferit",
                        "warning": (
                            "Transfer.it 分享将在开始下载时用专用下载器拉取。"
                            if source_name == "transferit"
                            else "PikPak 分享将在开始下载时转存并解析直链。"
                        ),
                    })
                except Exception as exc:
                    items.append({
                        "ok": False,
                        "url": source_item.get("share_url") or "",
                        "masked_url": source_item.get("share_url") or "",
                        "reason": self._sanitize_error(exc),
                        "source": source_name,
                    })
        items.extend(source.get("failed_items") or [])
        ok_count = sum(1 for item in items if item.get("ok"))
        for item in items:
            if isinstance(item, dict):
                item["selection_key"] = self._preview_item_selection_key(item)
        return {
            "success": ok_count > 0,
            "items": items,
            "ok_count": ok_count,
            "failed_count": len(items) - ok_count,
            "download_root": self._download_root(),
            "resolved_urls": source.get("urls") or [],
            "source_items": source.get("source_items") or [],
            "source_modes": source.get("source_modes") or [],
            "needs_materialize": any(bool(item.get("preview_only")) for item in source.get("source_items") or [] if isinstance(item, dict)),
        }

    async def preview_url(self, raw_url: str, target_subdir: str = "", conflict_policy: str = "", headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        try:
            url = await self.validate_url(raw_url)
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            hint = ""
            if any(host == item or host.endswith(f".{item}") for item in _BLOCKED_HOST_HINTS):
                hint = "该站点常见页面链接需要登录/验证码；首版只支持真实文件直链。"
            response_headers: Dict[str, str] = {}
            status = None
            size = 0
            content_type = ""
            timeout = aiohttp.ClientTimeout(total=20, connect=8)
            proxy = self._proxy_url(self._direct_link_preview_provider(url)) or None
            request_headers = dict(headers or {})
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.head(url, allow_redirects=True, headers=request_headers, proxy=proxy) as response:
                        status = response.status
                        response_headers = {k.lower(): v for k, v in response.headers.items()}
                        url = str(response.url)
                except Exception:
                    async with session.get(url, allow_redirects=True, headers={**request_headers, "Range": "bytes=0-0"}, proxy=proxy) as response:
                        status = response.status
                        response_headers = {k.lower(): v for k, v in response.headers.items()}
                        url = str(response.url)
            url = await self.validate_url(url)
            if status and status >= 400:
                raise HttpDownloadError(f"源站返回 HTTP {status}")
            content_type = str(response_headers.get("content-type") or "")
            if "text/html" in content_type.lower() and not hint:
                hint = "源站返回 HTML 页面，可能不是可直接下载的文件链接。"
            size = self._content_length_from_headers(response_headers)
            filename = self._filename_from_headers(response_headers) or self._filename_from_url(url)
            target = self._resolve_target(filename, target_subdir, conflict_policy)
            return {
                "ok": True,
                "url": url,
                "masked_url": self._mask_url(url),
                "host": urlparse(url).hostname or "",
                "source": self._direct_link_preview_provider(raw_url),
                "filename": target["filename"],
                "relative_path": target["relative_path"],
                "final_path": target["final_path"],
                "target_dir": target["target_dir"],
                "size_bytes": size,
                "content_type": content_type,
                "resumable": "bytes" in str(response_headers.get("accept-ranges") or "").lower(),
                "warning": hint,
            }
        except Exception as exc:
            return {
                "ok": False,
                "url": str(raw_url or "").strip(),
                "masked_url": self._mask_url(str(raw_url or "")),
                "reason": self._sanitize_error(exc) or exc.__class__.__name__,
            }

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def _ensure_daemon(self) -> Aria2Daemon:
        async with self._daemon_lock:
            if self._daemon and self._daemon.process.poll() is None:
                return self._daemon
            cfg = self._config()
            port = self._find_free_port()
            secret = secrets.token_urlsafe(24)
            session_dir = os.path.join(self._download_root(), ".aria2-rpc")
            os.makedirs(session_dir, exist_ok=True)
            session_file = os.path.join(session_dir, "session.txt")
            Path(session_file).touch(exist_ok=True)
            command = [
                str(getattr(cfg, "aria2_path", "") or "aria2c"),
                "--enable-rpc=true",
                "--rpc-listen-all=false",
                "--rpc-listen-port", str(port),
                "--rpc-secret", secret,
                "--max-concurrent-downloads", str(max(1, int(getattr(cfg, "max_concurrent_downloads", 3) or 3))),
                "--allow-overwrite=true",
                "--auto-file-renaming=false",
                "--continue=true",
                "--summary-interval=0",
                "--console-log-level=warn",
                "--dir", self._download_root(),
                "--input-file", session_file,
                "--save-session", session_file,
                "--save-session-interval=30",
            ]
            popen_kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                process = subprocess.Popen(command, **popen_kwargs)
            except FileNotFoundError as exc:
                raise HttpDownloadError(f"找不到 aria2 可执行文件: {getattr(cfg, 'aria2_path', 'aria2c')}") from exc
            except Exception as exc:
                raise HttpDownloadError(f"启动 aria2 失败: {exc}") from exc
            daemon = Aria2Daemon(process=process, endpoint=f"http://127.0.0.1:{port}/jsonrpc", secret=secret)
            for _ in range(30):
                if process.poll() is not None:
                    raise HttpDownloadError("aria2 进程启动后立即退出")
                try:
                    await self._rpc_call_raw(daemon, "aria2.getVersion", [])
                    self._daemon = daemon
                    return daemon
                except Exception:
                    await asyncio.sleep(0.1)
            with contextlib.suppress(Exception):
                process.kill()
            raise HttpDownloadError("aria2 RPC 启动超时")

    async def _rpc_call_raw(self, daemon: Aria2Daemon, method: str, params: List[Any]) -> Any:
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": method,
            "params": [f"token:{daemon.secret}", *params],
        }

        def call():
            data = json.dumps(payload).encode("utf-8")
            request = Request(
                daemon.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=8) as response:
                body = json.loads(response.read().decode("utf-8"))
            if body.get("error"):
                raise HttpDownloadError(body["error"].get("message") or "aria2 RPC 调用失败")
            return body.get("result")

        return await asyncio.to_thread(call)

    async def _rpc_call(self, method: str, params: List[Any]) -> Any:
        daemon = await self._ensure_daemon()
        return await self._rpc_call_raw(daemon, method, params)

    def _aria2_options(self, item: Dict[str, Any], target_dir: str) -> Dict[str, Any]:
        cfg = self._config()
        source = str(item.get("source") or "").strip().lower()
        split = max(1, int(getattr(cfg, "split", 8) or 8))
        max_connection = max(1, int(getattr(cfg, "max_connection_per_server", 8) or 8))
        options = {
            "dir": target_dir,
            "out": item["filename"],
            "continue": "true",
            "max-tries": str(max(1, int(getattr(cfg, "retry_count", 5) or 5))),
            "retry-wait": str(max(0, int(getattr(cfg, "retry_wait_seconds", 5) or 5))),
            "connect-timeout": str(max(1, int(getattr(cfg, "connect_timeout_seconds", 15) or 15))),
            "timeout": str(max(1, int(getattr(cfg, "timeout_seconds", 60) or 60))),
            "split": str(split),
            "max-connection-per-server": str(max_connection),
            "min-split-size": str(getattr(cfg, "min_split_size", "1M") or "1M"),
            "auto-file-renaming": "false",
            "allow-overwrite": "true",
        }
        if source == "pikpak":
            options["user-agent"] = _GOFILE_USER_AGENT
        proxy = self._proxy_url(source or "http")
        if proxy:
            options["all-proxy"] = proxy
        headers = [
            str(header).strip()
            for header in list(item.get("aria2_header") or [])
            if str(header or "").strip()
        ]
        if headers:
            options["header"] = headers
        return options

    async def _download_google_drive_item(self, item: Dict[str, Any], task=None, progress_callback=None) -> Dict[str, Any]:
        async with get_resource_budget_service().acquire("network_download", reason="http.google_drive"):
            return await self._download_google_drive_item_inner(item, task=task, progress_callback=progress_callback)

    async def _download_google_drive_item_inner(self, item: Dict[str, Any], task=None, progress_callback=None) -> Dict[str, Any]:
        raw_url = str(item.get("original_url") or item.get("url") or "").strip()
        if not raw_url:
            raise HttpDownloadError("Google Drive 下载缺少直链")
        target_dir = str(item.get("target_dir") or self._download_root())
        os.makedirs(target_dir, exist_ok=True)
        final_path = str(item.get("final_path") or os.path.join(target_dir, item.get("filename") or "google-drive-file"))
        filename = self._sanitize_filename(item.get("filename") or os.path.basename(final_path) or "google-drive-file")
        relative_path = str(item.get("relative_path") or os.path.relpath(final_path, self._download_root()).replace("\\", "/"))
        expected_total = int(item.get("size_bytes") or item.get("size") or 0)
        headers = {
            "User-Agent": _GOFILE_USER_AGENT,
            "Accept": "application/octet-stream,application/zip,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        headers.update({
            str(key): str(value)
            for key, value in dict(item.get("headers") or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        })
        if "Cookie" not in headers:
            for header in list(item.get("aria2_header") or []):
                header_text = str(header or "").strip()
                if header_text.lower().startswith("cookie:"):
                    headers["Cookie"] = header_text.split(":", 1)[1].strip()
                    break

        existing_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
        if existing_size and expected_total and existing_size >= expected_total:
            if task:
                await task.wait_if_paused()
                if task.is_cancelled():
                    raise asyncio.CancelledError()
            return {
                "gid": str(item.get("gid") or f"google_drive:{item.get('file_id') or filename}"),
                "name": os.path.basename(final_path) or filename,
                "relative_path": relative_path,
                "local_path": final_path,
                "url": item.get("masked_url") or self._mask_url(raw_url),
                "source": "google_drive",
                "status": "completed",
                "progress": 100,
                "downloaded": existing_size,
                "total": expected_total,
                "size": existing_size,
                "speed_bytes_per_sec": 0,
                "file_id": item.get("file_id", ""),
            }
        cfg = self._config()
        connect_timeout = max(10, int(getattr(cfg, "connect_timeout_seconds", 15) or 15))
        read_timeout = max(30, int(getattr(cfg, "timeout_seconds", 60) or 60))
        retry_count = max(1, int(getattr(cfg, "retry_count", 5) or 5))
        retry_wait = max(0, int(getattr(cfg, "retry_wait_seconds", 5) or 5))
        timeout = aiohttp.ClientTimeout(total=None, connect=connect_timeout, sock_read=read_timeout)
        proxy = self._proxy_url("google_drive") or None
        google_drive_api = bool(item.get("google_drive_api"))
        file_id = str(item.get("file_id") or "").strip()
        resource_key = str(item.get("resource_key") or "").strip()
        downloaded = existing_size
        speed_base = existing_size
        started_at = time.monotonic()
        last_emit_at = 0.0
        row = {
            "gid": str(item.get("gid") or f"google_drive:{item.get('file_id') or filename}"),
            "name": filename,
            "relative_path": relative_path,
            "local_path": final_path,
            "url": item.get("masked_url") or self._mask_url(raw_url),
            "source": "google_drive",
            "status": "downloading",
            "progress": 0,
            "downloaded": downloaded,
            "total": expected_total,
            "size": expected_total,
            "speed_bytes_per_sec": 0,
            "file_id": item.get("file_id", ""),
        }

        def current_file_size() -> int:
            try:
                return os.path.getsize(final_path)
            except OSError:
                return int(downloaded or 0)

        async def emit_progress(force: bool = False) -> None:
            nonlocal last_emit_at
            now = time.monotonic()
            if not force and now - last_emit_at < 0.8:
                return
            last_emit_at = now
            elapsed = max(now - started_at, 0.001)
            current_downloaded = current_file_size()
            row["downloaded"] = current_downloaded
            if str(row.get("status") or "") == "completed":
                row["speed_bytes_per_sec"] = 0
            else:
                row["speed_bytes_per_sec"] = int(max(0, current_downloaded - speed_base) / elapsed)
            if int(row.get("total") or 0) > 0:
                progress_cap = 100 if str(row.get("status") or "") == "completed" else 99
                row["progress"] = min(progress_cap, int(current_downloaded / int(row["total"]) * 100))
            if progress_callback:
                public_row = {key: value for key, value in row.items() if not str(key).startswith("_")}
                result = progress_callback(public_row)
                if inspect.isawaitable(result):
                    await result

        def should_flush_download_file(force: bool = False) -> bool:
            if force:
                return True
            now = time.monotonic()
            last_flush_at = float(row.get("_last_flush_at") or 0)
            last_flush_downloaded = int(row.get("_last_flush_downloaded") or 0)
            current_downloaded = int(downloaded or 0)
            if now - last_flush_at >= 1.0:
                return True
            return current_downloaded - last_flush_downloaded >= 8 * 1024 * 1024

        def mark_download_file_flushed() -> None:
            row["_last_flush_at"] = time.monotonic()
            row["_last_flush_downloaded"] = int(downloaded or 0)

        last_error: Optional[BaseException] = None
        for attempt_index in range(retry_count):
            if task:
                await task.wait_if_paused()
                if task.is_cancelled():
                    raise asyncio.CancelledError()

            existing_size = current_file_size()
            downloaded = existing_size
            if existing_size and expected_total and existing_size >= expected_total:
                if task:
                    await task.wait_if_paused()
                    if task.is_cancelled():
                        raise asyncio.CancelledError()
                row.update({"status": "completed", "progress": 100, "downloaded": existing_size, "size": existing_size})
                await emit_progress(force=True)
                return row

            request_headers = dict(headers)
            if google_drive_api:
                token = await self._google_drive_access_token(force_refresh=attempt_index > 0)
                request_headers.update(self._google_drive_api_headers(
                    token,
                    resource_keys={file_id: resource_key} if file_id and resource_key else None,
                ))
            mode = "ab" if existing_size > 0 else "wb"
            if existing_size > 0:
                request_headers["Range"] = f"bytes={existing_size}-"

            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(raw_url, headers=request_headers, allow_redirects=True, proxy=proxy) as response:
                        if response.status == 401 and google_drive_api and attempt_index < retry_count - 1:
                            self._google_drive_access_token_cache = ("", 0.0)
                            last_error = HttpDownloadError("Google Drive OAuth access token 已失效，已刷新后重试")
                            continue
                        if response.status == 416 and expected_total and existing_size >= expected_total:
                            row.update({"status": "completed", "progress": 100, "downloaded": existing_size, "size": existing_size})
                            await emit_progress(force=True)
                            return row
                        if response.status >= 400:
                            raise HttpDownloadError(f"Google Drive 下载返回 HTTP {response.status}")
                        response_headers = {k.lower(): v for k, v in response.headers.items()}
                        content_type = str(response_headers.get("content-type") or "")
                        if "text/html" in content_type.lower():
                            body = await response.text(errors="ignore")
                            raise HttpDownloadError(self._google_drive_html_error_message(body))
                        content_range = str(response_headers.get("content-range") or "")
                        content_total = self._content_length_from_headers(response_headers)
                        if response.status != 206 and existing_size > 0:
                            existing_size = 0
                            downloaded = 0
                            speed_base = 0
                            mode = "wb"
                        if content_total and "/" in content_range:
                            total = max(expected_total, content_total)
                        else:
                            total = max(expected_total, content_total + downloaded if response.status == 206 and content_total else content_total)
                        if total > 0:
                            row["total"] = total
                            row["size"] = total
                        with open(final_path, mode + ("" if "b" in mode else "b")) as target:
                            downloaded = target.tell()
                            async for chunk in response.content.iter_chunked(GOOGLE_DRIVE_STREAM_CHUNK_BYTES):
                                if not chunk:
                                    continue
                                if task:
                                    await task.wait_if_paused()
                                    if task.is_cancelled():
                                        raise asyncio.CancelledError()
                                target.write(chunk)
                                downloaded = target.tell()
                                if should_flush_download_file():
                                    target.flush()
                                    mark_download_file_flushed()
                                await emit_progress()
                            target.flush()
                            mark_download_file_flushed()
            except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as exc:
                last_error = exc
                downloaded = current_file_size()
                await emit_progress(force=True)
                if attempt_index < retry_count - 1:
                    if retry_wait:
                        await asyncio.sleep(retry_wait)
                    continue
                partial = f"，已保留 {downloaded} bytes" if downloaded else ""
                raise HttpDownloadError(f"Google Drive 下载中断{partial}，可重试续传: {self._sanitize_error(exc)}") from exc

            final_size = current_file_size()
            downloaded = final_size
            if expected_total and final_size < expected_total:
                last_error = HttpDownloadError(f"Google Drive 下载不完整: {final_size}/{expected_total} bytes")
                await emit_progress(force=True)
                if attempt_index < retry_count - 1:
                    if retry_wait:
                        await asyncio.sleep(retry_wait)
                    continue
                raise last_error
            break
        else:
            if last_error:
                raise HttpDownloadError(f"Google Drive 下载失败: {self._sanitize_error(last_error)}") from last_error

        final_size = os.path.getsize(final_path) if os.path.exists(final_path) else downloaded
        if task:
            await task.wait_if_paused()
            if task.is_cancelled():
                raise asyncio.CancelledError()
        if expected_total and final_size < expected_total:
            raise HttpDownloadError(f"Google Drive 下载不完整: {final_size}/{expected_total} bytes")
        row.update({
            "name": os.path.basename(final_path) or filename,
            "status": "completed",
            "progress": 100,
            "downloaded": final_size,
            "total": max(int(row.get("total") or 0), final_size),
            "size": max(int(row.get("size") or 0), final_size),
            "speed_bytes_per_sec": 0,
        })
        row.pop("_last_flush_at", None)
        row.pop("_last_flush_downloaded", None)
        await emit_progress(force=True)
        return row

    async def _download_transferit_item(self, item: Dict[str, Any], task=None, progress_callback=None) -> Dict[str, Any]:
        async with get_resource_budget_service().acquire("network_download", reason="http.transferit"):
            return await self._download_transferit_item_inner(item, task=task, progress_callback=progress_callback)

    async def _download_transferit_item_inner(self, item: Dict[str, Any], task=None, progress_callback=None) -> Dict[str, Any]:
        raw_url = str(item.get("original_url") or item.get("url") or "").strip()
        if not raw_url:
            raise HttpDownloadError("Transfer.it 下载缺少分享链接")
        target_dir = str(item.get("target_dir") or self._download_root())
        os.makedirs(target_dir, exist_ok=True)
        final_path = str(item.get("final_path") or os.path.join(target_dir, item.get("filename") or "transferit-download"))
        filename = self._sanitize_filename(item.get("filename") or os.path.basename(final_path) or "transferit-download")
        relative_path = str(item.get("relative_path") or filename).replace("\\", "/")
        expected_size = int(item.get("size_bytes") or item.get("total") or item.get("size") or 0)
        gid = f"transferit:{self._transferit_row_identity(item) or item.get('share_id') or filename}"
        row = {
            "gid": gid,
            "name": filename,
            "relative_path": relative_path,
            "local_path": final_path,
            "url": item.get("masked_url") or self._mask_url(raw_url),
            "source": "transferit",
            "status": "downloading",
            "progress": 0,
            "downloaded": 0,
            "total": expected_size,
            "size": expected_size,
            "speed_bytes_per_sec": 0,
            "share_id": item.get("share_id", ""),
            "transferit_node_handle": item.get("transferit_node_handle", ""),
        }
        cfg = self._config()
        connect_timeout = max(10, int(getattr(cfg, "connect_timeout_seconds", 15) or 15))
        read_timeout = max(30, int(getattr(cfg, "timeout_seconds", 60) or 60))
        retry_count = max(1, int(getattr(cfg, "retry_count", 5) or 5))
        retry_wait = max(0, int(getattr(cfg, "retry_wait_seconds", 5) or 5))
        stall_timeout = max(read_timeout * 2, 120)
        proxy = self._proxy_url("transferit") or None

        progress_queue: asyncio.Queue = asyncio.Queue()
        abort_event = threading.Event()
        loop = asyncio.get_running_loop()
        stream_state: Dict[str, Any] = {"response": None}

        def publish_progress(payload: Dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(progress_queue.put_nowait, dict(payload))
            except RuntimeError:
                pass

        def run_download_once() -> str:
            client = self._transferit_api_client()
            if not hasattr(client, "api") or not hasattr(getattr(client, "api", None), "fetch_transfer") or not hasattr(getattr(client, "api", None), "get_download_url"):
                password = self._transferit_password(raw_url)
                try:
                    download_dir = os.path.dirname(final_path) or target_dir
                    if password:
                        result = client.download(raw_url, download_dir, password=password)
                    else:
                        result = client.download(raw_url, download_dir)
                    expected_path = os.path.join(download_dir, filename)
                    if expected_path != final_path and os.path.exists(expected_path) and not os.path.exists(final_path):
                        os.replace(expected_path, final_path)
                        return final_path
                    paths = list(getattr(result, "paths", []) or [])
                    file_paths = [path for path in paths if os.path.isfile(path)]
                    if file_paths:
                        return file_paths[0]
                    return expected_path
                finally:
                    self._close_transferit_client(client)

            from Cryptodome.Cipher import AES
            from Cryptodome.Util import Counter
            from transferit import MegaAPI
            from transferit._crypto import a32_to_bytes, attr_key
            from transferit._download import compute_folder_paths
            from transferit._models import TransferNode

            xh = MegaAPI.parse_xh(raw_url)
            password = self._transferit_password(raw_url) or None
            target_handle = str(item.get("transferit_node_handle") or "").strip()
            target_identity = (
                str(item.get("relative_path") or "").strip().replace("\\", "/").strip("/")
                or str(item.get("filename") or item.get("name") or "").strip()
            ).lower()

            try:
                node_dicts, pw_token = client.api.fetch_transfer(xh, password=password)
                nodes = [TransferNode.from_dict(node) for node in node_dicts]
                root = next((node.handle for node in nodes if node.is_folder and not node.parent), None)
                folder_paths = compute_folder_paths(node_dicts, root) if root else {}
                files = [node for node in nodes if node.is_file]
                if not files:
                    raise HttpDownloadError("Transfer.it 分享中没有可下载文件")

                def node_rel(node) -> str:
                    rel_dir = folder_paths.get(node.parent, "").strip("/")
                    name = self._sanitize_filename(node.name or node.handle)
                    return "/".join(part for part in (rel_dir, name) if part).strip("/")

                selected = None
                if target_handle:
                    selected = next((node for node in files if node.handle == target_handle), None)
                if selected is None and target_identity:
                    selected = next((node for node in files if node_rel(node).lower() == target_identity), None)
                if selected is None and target_identity:
                    selected = next((node for node in files if self._sanitize_filename(node.name or node.handle).lower() == target_identity), None)
                if selected is None and len(files) == 1:
                    selected = files[0]
                if selected is None:
                    raise HttpDownloadError("Transfer.it 文件定位失败，请重新预览后再下载")

                dl = client.api.get_download_url(xh, selected.handle, pw_token=pw_token)
                download_url = str(dl.get("g") or "")
                total_size = int(dl.get("s") or selected.size or expected_size or 0)
                if not download_url:
                    raise HttpDownloadError("Transfer.it 未返回下载地址")

                out_path = Path(final_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = out_path.with_name(out_path.name + ".part")
                if tmp_path.exists():
                    with contextlib.suppress(OSError):
                        tmp_path.unlink()

                aes_key = attr_key(selected.key)
                nonce = a32_to_bytes(selected.key[4:6])
                ctr = Counter.new(64, prefix=nonce, initial_value=0)
                cipher = AES.new(aes_key, AES.MODE_CTR, counter=ctr)
                written = 0
                started_at = time.monotonic()
                last_emit_at = 0.0
                last_progress_at = started_at

                publish_progress({
                    **row,
                    "name": self._sanitize_filename(selected.name or filename),
                    "status": "downloading",
                    "downloaded": 0,
                    "total": total_size,
                    "size": total_size,
                    "progress": 0,
                    "speed_bytes_per_sec": 0,
                    "transferit_node_handle": selected.handle,
                })
                with httpx.stream(
                    "GET",
                    download_url,
                    timeout=httpx.Timeout(None, connect=connect_timeout, read=read_timeout),
                    proxy=proxy,
                    follow_redirects=True,
                ) as response:
                    stream_state["response"] = response
                    response.raise_for_status()
                    with tmp_path.open("wb") as target:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if abort_event.is_set():
                                raise _TransferitDownloadAbort("Transfer.it 下载已取消")
                            if not chunk:
                                if time.monotonic() - last_progress_at > stall_timeout:
                                    raise TimeoutError(f"Transfer.it 下载 {stall_timeout}s 无进度")
                                continue
                            target.write(cipher.decrypt(chunk))
                            written += len(chunk)
                            last_progress_at = time.monotonic()
                            now = last_progress_at
                            if now - last_emit_at >= 0.8:
                                last_emit_at = now
                                elapsed = max(now - started_at, 0.001)
                                publish_progress({
                                    **row,
                                    "name": self._sanitize_filename(selected.name or filename),
                                    "status": "downloading",
                                    "downloaded": written,
                                    "total": total_size,
                                    "size": total_size,
                                    "progress": min(99, int(written / total_size * 100)) if total_size else 0,
                                    "speed_bytes_per_sec": int(written / elapsed),
                                    "transferit_node_handle": selected.handle,
                                })
                        target.flush()
                if total_size and written < total_size:
                    raise HttpDownloadError(f"Transfer.it 下载不完整: {written}/{total_size} bytes")
                if out_path.exists():
                    with contextlib.suppress(OSError):
                        out_path.unlink()
                tmp_path.replace(out_path)
                return str(out_path)
            finally:
                stream_state["response"] = None
                self._close_transferit_client(client)

        downloaded_path = ""
        last_error: Optional[BaseException] = None

        async def drain_progress(download_task: asyncio.Task) -> None:
            while not download_task.done():
                pause_event = getattr(task, "_pause_event", None) if task else None
                should_stop = bool(
                    task
                    and (
                        task.is_cancelled()
                        or (pause_event is not None and not pause_event.is_set())
                    )
                )
                if should_stop:
                    abort_event.set()
                    response = stream_state.get("response")
                    if response is not None:
                        with contextlib.suppress(Exception):
                            response.close()
                try:
                    progress_row = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                row.update(progress_row)
                if progress_callback:
                    result = progress_callback(dict(row))
                    if inspect.isawaitable(result):
                        await result
                if task:
                    task.task_metadata["transferit_active_row"] = dict(row)
            while not progress_queue.empty():
                row.update(progress_queue.get_nowait())
                if progress_callback:
                    result = progress_callback(dict(row))
                    if inspect.isawaitable(result):
                        await result

        for attempt in range(retry_count):
            abort_event.clear()
            if task:
                await task.wait_if_paused()
                if task.is_cancelled():
                    raise asyncio.CancelledError()
            try:
                worker = asyncio.create_task(asyncio.to_thread(run_download_once))
                watcher = asyncio.create_task(drain_progress(worker))
                try:
                    downloaded_path = await worker
                finally:
                    abort_event.set()
                    await watcher
                break
            except _TransferitDownloadAbort as exc:
                pause_event = getattr(task, "_pause_event", None) if task else None
                if task and (
                    task.is_cancelled()
                    or (pause_event is not None and not pause_event.is_set())
                ):
                    raise asyncio.CancelledError()
                last_error = exc
            except Exception as exc:
                last_error = exc
                if not self._is_transferit_transient_error(exc):
                    raise
            if attempt < retry_count - 1:
                if retry_wait:
                    await asyncio.sleep(retry_wait)
                else:
                    await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise HttpDownloadError("Transfer.it 服务器忙，请稍后重试") from last_error

        if item.get("metadata_fallback") and downloaded_path and os.path.isfile(downloaded_path):
            final_path = downloaded_path
            filename = self._sanitize_filename(os.path.basename(final_path) or filename)
        elif downloaded_path and os.path.isfile(downloaded_path) and downloaded_path != final_path and not os.path.exists(final_path):
            os.replace(downloaded_path, final_path)
        if not os.path.exists(final_path):
            matches = [
                os.path.join(target_dir, name)
                for name in os.listdir(target_dir)
                if os.path.isfile(os.path.join(target_dir, name))
            ]
            if len(matches) == 1:
                os.replace(matches[0], final_path)
        if not os.path.exists(final_path):
            raise HttpDownloadError("Transfer.it 下载完成后未找到输出文件")
        size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
        row.update({
            "gid": gid,
            "name": os.path.basename(final_path) or filename,
            "relative_path": os.path.relpath(final_path, self._download_root()).replace("\\", "/"),
            "local_path": final_path,
            "url": item.get("masked_url") or self._mask_url(raw_url),
            "source": "transferit",
            "status": "completed",
            "progress": 100,
            "downloaded": size,
            "total": max(int(row.get("total") or 0), size),
            "size": max(int(row.get("size") or 0), size),
            "speed_bytes_per_sec": 0,
        })
        return {
            **row,
        }

    async def start_download_task(self, task) -> Dict[str, Any]:
        task_id = str(getattr(task, "id", "") or "").strip()
        current_task = asyncio.current_task()
        if task_id and current_task is not None:
            self._active_download_tasks[task_id] = current_task
        try:
            return await self._start_download_task_inner(task)
        finally:
            if task_id and self._active_download_tasks.get(task_id) is current_task:
                self._active_download_tasks.pop(task_id, None)

    async def _start_download_task_inner(self, task) -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        raw_urls = list(metadata.get("urls") or [])
        if not raw_urls:
            raise HttpDownloadError("没有可下载链接")
        cfg = self._config()
        if not bool(getattr(cfg, "enabled", True)):
            raise HttpDownloadError("HTTP 外链下载未启用")
        if str(getattr(cfg, "engine", "aria2") or "aria2").lower() != "aria2":
            raise HttpDownloadError("当前仅支持 aria2 下载引擎")

        target_subdir = str(metadata.get("target_subdir") or "").strip()
        conflict_policy = str(metadata.get("conflict_policy") or getattr(cfg, "conflict_policy", "resume") or "resume")
        selected_items = [
            item for item in list(metadata.get("selected_items") or [])
            if isinstance(item, dict)
        ]
        preview = await self.preview_urls(
            raw_urls,
            target_subdir=target_subdir,
            conflict_policy=conflict_policy,
            materialize_sources=True,
            selected_items=selected_items,
        )
        preview = self.filter_preview_selection(
            preview,
            selected_keys=list(metadata.get("selected_keys") or []),
            selected_items=selected_items,
        )
        items = [
            self._apply_custom_download_name_to_item(item, conflict_policy=conflict_policy)
            for item in (preview.get("items") or [])
            if item.get("ok")
        ]
        failed_items = [item for item in preview.get("items") or [] if not item.get("ok")]
        if not items:
            reasons = []
            for item in failed_items[:5]:
                reason = str(item.get("reason") or item.get("failure_reason") or "").strip()
                target = str(item.get("filename") or item.get("masked_url") or item.get("url") or "").strip()
                if reason:
                    reasons.append(f"{target}: {reason}" if target else reason)
            detail = "；".join(reasons)
            raise HttpDownloadError(f"没有通过校验的下载项: {detail}" if detail else "没有通过校验的下载项")
        # 分享类(PikPak/Transfer.it)通常是同一作品的分卷，缺任一文件即无法解压；
        # 只要有分享文件解析失败就整体中止并报明细，避免下载残缺分卷后续解压必然失败。
        share_failed = [
            item for item in failed_items
            if str(item.get("source") or "") in _SHARE_PREVIEW_ONLY_SOURCES
        ]
        if share_failed:
            reasons = []
            for item in share_failed[:8]:
                reason = str(item.get("reason") or item.get("failure_reason") or "").strip()
                target = str(item.get("filename") or item.get("name") or item.get("masked_url") or "").strip()
                if target and reason:
                    reasons.append(f"{target}: {reason}")
                elif target or reason:
                    reasons.append(target or reason)
            detail = "；".join(r for r in reasons if r)
            raise HttpDownloadError(
                f"分享中有 {len(share_failed)} 个文件解析失败，已中止以避免下载残缺分卷：{detail}"
                if detail else f"分享中有 {len(share_failed)} 个文件解析失败，已中止以避免下载残缺分卷"
            )
        resolved_urls = list(preview.get("resolved_urls") or [])
        source_items = list(preview.get("source_items") or [])
        source_modes = list(preview.get("source_modes") or [])
        google_drive_items = [item for item in items if str(item.get("source") or "") == "google_drive"]
        transferit_items = [item for item in items if str(item.get("source") or "") == "transferit"]
        aria2_items = [
            item for item in items
            if str(item.get("source") or "") not in {"google_drive", "transferit"}
            and self._is_direct_download_item(item)
        ]

        os.makedirs(self._download_root(), exist_ok=True)
        gids: List[str] = []
        download_files = []
        total_bytes = 0
        for item in google_drive_items:
            total_bytes += int(item.get("size_bytes") or 0)
            gid = f"google_drive:{item.get('file_id') or item.get('filename')}"
            item["gid"] = gid
            download_files.append({
                "gid": gid,
                "name": item["filename"],
                "relative_path": item["relative_path"],
                "local_path": item["final_path"],
                "url": item["masked_url"],
                "original_url": item["url"],
                "source": "google_drive",
                "status": "pending",
                "progress": 0,
                "downloaded": 0,
                "total": int(item.get("size_bytes") or 0),
                "size": int(item.get("size_bytes") or 0),
                "file_id": item.get("file_id", ""),
                "resource_key": item.get("resource_key", ""),
                "google_drive_api": bool(item.get("google_drive_api")),
            })
        for item in aria2_items:
            os.makedirs(item["target_dir"], exist_ok=True)
            options = self._aria2_options(item, item["target_dir"])
            gid = await self._rpc_call("aria2.addUri", [[item["url"]], options])
            gids.append(str(gid))
            total_bytes += int(item.get("size_bytes") or 0)
            download_files.append({
                "gid": str(gid),
                "name": item["filename"],
                "relative_path": item["relative_path"],
                "local_path": item["final_path"],
                "url": item["masked_url"],
                "original_url": item["url"],
                "source": item.get("source", "http"),
                "status": "pending",
                "progress": 0,
                "downloaded": 0,
                "total": int(item.get("size_bytes") or 0),
                "size": int(item.get("size_bytes") or 0),
                "expected_size_bytes": int(item.get("size_bytes") or 0),
                "file_id": item.get("file_id", ""),
                "download_file_id": item.get("download_file_id", ""),
                "pikpak_cleanup_file_id": item.get("pikpak_cleanup_file_id", ""),
                "pikpak_materialized": bool(item.get("pikpak_materialized")),
                "share_id": item.get("share_id", ""),
                "pikpak_account_id": item.get("pikpak_account_id", ""),
                "pikpak_account_label": item.get("pikpak_account_label", ""),
                "pikpak_transfer_dir": item.get("pikpak_transfer_dir", ""),
            })
        for item in transferit_items:
            total_bytes += int(item.get("size_bytes") or 0)
            gid = f"transferit:{self._transferit_row_identity(item) or item.get('share_id') or item.get('filename')}"
            item["gid"] = gid
            download_files.append({
                "gid": gid,
                "name": item["filename"],
                "relative_path": item["relative_path"],
                "local_path": item["final_path"],
                "url": item.get("masked_url") or self._mask_url(str(item.get("url") or "")),
                "original_url": item.get("original_url") or item.get("url"),
                "source": "transferit",
                "status": "pending",
                "progress": 0,
                "downloaded": 0,
                "total": int(item.get("size_bytes") or 0),
                "size": int(item.get("size_bytes") or 0),
                "share_id": item.get("share_id", ""),
                "transferit_node_handle": item.get("transferit_node_handle", ""),
            })

        self._task_gids[task.id] = gids
        task.task_metadata.update({
            "resolved_urls": resolved_urls,
            "source_items": [
                sanitize_http_download_item(item)
                for item in source_items
                if isinstance(item, dict)
            ],
            "source_modes": source_modes,
            "download_root": self._download_root(),
            "download_files": download_files,
            "download_runtime": {
                "status": "downloading",
                "total_files": len(download_files),
                "completed_files": 0,
                "failed_files": len(failed_items),
                "active_file_count": 0,
                "transferred_bytes": 0,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0,
                "current_file_name": "",
                "current_relative_path": "",
            },
            "failed_files": failed_items,
            "progress_log": list(task.task_metadata.get("progress_log") or []),
            "final_output_path": self._download_root(),
            "cleanup_mode": "files_only",
        })
        task.output_path = self._download_root()
        task.task_metadata["final_output_path"] = self._download_root()
        submit_parts = []
        if google_drive_items:
            submit_parts.append(f"{len(google_drive_items)} 个 Google Drive 下载")
        if gids:
            submit_parts.append(f"{len(gids)} 个 aria2 下载")
        if transferit_items:
            submit_parts.append(f"{len(transferit_items)} 个专用下载")
        task.update_progress(1, f"已提交 {'，'.join(submit_parts) if submit_parts else '0 个下载'}")

        started = time.monotonic()
        google_success_files = []
        google_failed_rows = []
        transfer_success_files = []
        transfer_failed_rows = []

        def merge_download_row(row: Dict[str, Any]) -> None:
            row_gid = str(row.get("gid") or "")
            for existing in download_files:
                if row_gid and str(existing.get("gid") or "") == row_gid:
                    existing.update(row)
                    return
                if (
                    str(existing.get("source") or "") == str(row.get("source") or "")
                    and str(existing.get("relative_path") or "") == str(row.get("relative_path") or "")
                ):
                    existing.update(row)
                    return
            download_files.append(row)

        def refresh_download_runtime() -> Dict[str, Any]:
            active_rows = [row for row in download_files if str(row.get("status") or "") == "downloading"]
            completed_rows = [row for row in download_files if str(row.get("status") or "") == "completed"]
            failed_rows_now = [row for row in download_files if str(row.get("status") or "") == "failed"]
            current_row = active_rows[0] if active_rows else {}
            runtime = {
                "status": "downloading",
                "total_files": len(download_files),
                "completed_files": len(completed_rows),
                "failed_files": len(failed_items) + len(failed_rows_now),
                "active_file_count": len(active_rows),
                "transferred_bytes": sum(int(row.get("downloaded") or 0) for row in download_files),
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": sum(int(row.get("speed_bytes_per_sec") or 0) for row in active_rows),
                "current_file_name": str(current_row.get("name") or ""),
                "current_relative_path": str(current_row.get("relative_path") or ""),
            }
            task.task_metadata["download_files"] = download_files
            task.task_metadata["download_runtime"] = runtime
            task.current_step = runtime.get("current_file_name") or "下载中"
            total = max(1, int(runtime.get("total_bytes") or total_bytes or 0))
            transferred = int(runtime.get("transferred_bytes") or 0)
            task.progress = max(task.progress, 95 if total <= 1 else min(99, int(transferred / total * 100)))
            return runtime

        google_last_log_at = 0.0
        transfer_last_log_at = 0.0

        def handle_google_progress(row: Dict[str, Any]) -> None:
            nonlocal google_last_log_at
            merge_download_row(row)
            runtime = refresh_download_runtime()
            now = time.monotonic()
            if now - google_last_log_at > 5:
                google_last_log_at = now
                task.update_progress(task.progress, f"下载中 {runtime.get('completed_files', 0)}/{len(download_files)}")

        def handle_transfer_progress(row: Dict[str, Any]) -> None:
            nonlocal transfer_last_log_at
            merge_download_row(row)
            runtime = refresh_download_runtime()
            now = time.monotonic()
            if now - transfer_last_log_at > 5:
                transfer_last_log_at = now
                task.update_progress(task.progress, f"下载中 {runtime.get('completed_files', 0)}/{len(download_files)}")

        if google_drive_items:
            for index, item in enumerate(google_drive_items, start=1):
                await task.wait_if_paused()
                if task.is_cancelled():
                    await self.cancel_task(task.id)
                    raise asyncio.CancelledError()
                task.current_step = f"下载 Google Drive {index}/{len(google_drive_items)}"
                task.update_progress(max(task.progress, 3), task.current_step)
                try:
                    row = await self._download_google_drive_item(item, task=task, progress_callback=handle_google_progress)
                    google_success_files.append(row)
                    merge_download_row(row)
                except asyncio.CancelledError:
                    await self.cancel_task(task.id)
                    raise
                except Exception as exc:
                    partial_downloaded = 0
                    partial_path = str(item.get("final_path") or "")
                    if partial_path:
                        with contextlib.suppress(OSError):
                            partial_downloaded = os.path.getsize(partial_path)
                    expected_size = int(item.get("size_bytes") or 0)
                    failed_row = {
                        "gid": str(item.get("gid") or f"google_drive:{item.get('file_id') or item.get('filename')}"),
                        "name": item.get("filename") or "google-drive-file",
                        "relative_path": item.get("relative_path") or "",
                        "local_path": partial_path,
                        "url": item.get("masked_url") or self._mask_url(str(item.get("url") or "")),
                        "source": "google_drive",
                        "status": "failed",
                        "failure_reason": self._sanitize_error(exc),
                        "progress": min(99, int(partial_downloaded / expected_size * 100)) if expected_size else 0,
                        "downloaded": partial_downloaded,
                        "total": expected_size,
                        "size": expected_size,
                        "speed_bytes_per_sec": 0,
                        "file_id": item.get("file_id", ""),
                        "resource_key": item.get("resource_key", ""),
                        "google_drive_api": bool(item.get("google_drive_api")),
                    }
                    google_failed_rows.append(failed_row)
                    merge_download_row(failed_row)
                refresh_download_runtime()

        if transferit_items:
            for index, item in enumerate(transferit_items, start=1):
                await task.wait_if_paused()
                if task.is_cancelled():
                    await self.cancel_task(task.id)
                    raise asyncio.CancelledError()
                task.current_step = f"下载 Transfer.it {index}/{len(transferit_items)}"
                task.update_progress(max(task.progress, 3), task.current_step)
                try:
                    row = await self._download_transferit_item(item, task=task, progress_callback=handle_transfer_progress)
                    transfer_success_files.append(row)
                    merge_download_row(row)
                except asyncio.CancelledError:
                    await self.cancel_task(task.id)
                    raise
                except Exception as exc:
                    partial_downloaded = 0
                    partial_path = str(item.get("final_path") or "")
                    if partial_path:
                        with contextlib.suppress(OSError):
                            partial_downloaded = os.path.getsize(partial_path)
                        part_path = partial_path + ".part"
                        with contextlib.suppress(OSError):
                            partial_downloaded = max(partial_downloaded, os.path.getsize(part_path))
                    expected_size = int(item.get("size_bytes") or 0)
                    failed_row = {
                        "gid": str(item.get("gid") or f"transferit:{self._transferit_row_identity(item) or item.get('share_id') or item.get('filename')}"),
                        "name": item.get("filename") or "transferit-download",
                        "relative_path": item.get("relative_path") or "",
                        "local_path": partial_path,
                        "url": item.get("masked_url") or self._mask_url(str(item.get("url") or "")),
                        "source": "transferit",
                        "status": "failed",
                        "failure_reason": self._sanitize_error(exc),
                        "progress": min(99, int(partial_downloaded / expected_size * 100)) if expected_size else 0,
                        "downloaded": partial_downloaded,
                        "total": expected_size,
                        "size": expected_size,
                        "speed_bytes_per_sec": 0,
                        "share_id": item.get("share_id", ""),
                        "transferit_node_handle": item.get("transferit_node_handle", ""),
                    }
                    transfer_failed_rows.append(failed_row)
                    merge_download_row(failed_row)
                refresh_download_runtime()

        last_log_at = 0.0
        if gids:
            while True:
                await task.wait_if_paused()
                if task.is_cancelled():
                    await self.cancel_task(task.id)
                    raise asyncio.CancelledError()
                gid_set = set(gids)
                aria_rows = [row for row in download_files if str(row.get("gid") or "") in gid_set]
                rows, runtime, done, _failed = await self._poll_task(gids, aria_rows)
                for row in rows:
                    for existing in download_files:
                        if existing.get("gid") == row.get("gid"):
                            existing.update(row)
                            break
                google_done = len(google_success_files)
                google_failed = len(google_failed_rows)
                transfer_done = len(transfer_success_files)
                transfer_failed = len(transfer_failed_rows)
                runtime.update({
                    "total_files": len(download_files),
                    "completed_files": int(runtime.get("completed_files") or 0) + google_done + transfer_done,
                    "failed_files": int(runtime.get("failed_files") or 0) + google_failed + transfer_failed,
                    "transferred_bytes": (
                        int(runtime.get("transferred_bytes") or 0)
                        + sum(int(row.get("downloaded") or 0) for row in google_success_files)
                        + sum(int(row.get("downloaded") or 0) for row in transfer_success_files)
                    ),
                    "total_bytes": total_bytes,
                })
                task.task_metadata["download_files"] = download_files
                task.task_metadata["download_runtime"] = runtime
                task.current_step = runtime.get("current_file_name") or "下载中"
                total = max(1, int(runtime.get("total_bytes") or total_bytes or 0))
                transferred = int(runtime.get("transferred_bytes") or 0)
                progress = 95 if total <= 1 else min(99, int(transferred / total * 100))
                task.progress = max(task.progress, progress)
                now = time.monotonic()
                if now - last_log_at > 5:
                    last_log_at = now
                    task.update_progress(task.progress, f"下载中 {runtime.get('completed_files', 0)}/{len(download_files)}")
                if done:
                    break
                await asyncio.sleep(1.0)
        else:
            runtime = task.task_metadata.get("download_runtime") or {}

        success_files = [row for row in download_files if row.get("status") == "completed"]
        failed_rows = [row for row in download_files if row.get("status") == "failed"]
        duration_ms = int((time.monotonic() - started) * 1000)
        downloaded_bytes = sum(int(row.get("downloaded") or row.get("size") or 0) for row in success_files)
        transferred_bytes = sum(int(row.get("downloaded") or 0) for row in download_files)
        task.task_metadata.update({
            "download_files": download_files,
            "failed_files": [*failed_items, *[row for row in failed_rows if row not in failed_items]],
            "final_output_path": self._download_root(),
            "performance_metrics": {
                "duration_ms": duration_ms,
                "downloaded_bytes": downloaded_bytes,
                "transferred_bytes": transferred_bytes,
                "success_count": len(success_files),
                "failed_count": len(failed_items) + len([row for row in failed_rows if row not in failed_items]),
                "average_speed_bytes": int(downloaded_bytes / max(duration_ms / 1000, 1)) if downloaded_bytes else 0,
            },
        })
        merged_failed_rows = [*failed_items, *[row for row in failed_rows if row not in failed_items]]
        if success_files and not merged_failed_rows:
            final_status = "completed"
        elif success_files:
            final_status = "partial_failed"
        else:
            final_status = "failed"
        try:
            from .task_phase_metric_service import get_task_phase_metric_service

            task_type = getattr(getattr(task, "type", None), "value", getattr(task, "type", ""))
            await get_task_phase_metric_service().record_async(
                task_id=str(getattr(task, "id", "") or ""),
                task_type=str(task_type or ""),
                phase="http_download",
                resource="network_download",
                status=final_status,
                duration_ms=duration_ms,
                bytes_total=downloaded_bytes,
                items_total=len(success_files),
                detail={
                    "failed_count": len(merged_failed_rows),
                    "transferred_bytes": transferred_bytes,
                    "source": "http_download_service",
                },
            )
        except Exception:
            logger.warning("[HTTP下载] 记录任务阶段指标失败 task_id=%s", getattr(task, "id", ""), exc_info=True)
        runtime.update({
            "total_files": len(download_files),
            "completed_files": len(success_files),
            "failed_files": len(merged_failed_rows),
            "transferred_bytes": transferred_bytes,
            "total_bytes": total_bytes,
        })
        runtime["status"] = final_status
        runtime["speed_bytes_per_sec"] = 0
        task.task_metadata["download_runtime"] = runtime
        if not success_files:
            reasons = []
            for row in merged_failed_rows[:5]:
                if not isinstance(row, dict):
                    continue
                reason = str(row.get("failure_reason") or row.get("reason") or "").strip()
                target = str(row.get("name") or row.get("filename") or row.get("relative_path") or "").strip()
                if reason:
                    reasons.append(f"{target}: {reason}" if target else reason)
            detail = "；".join(reason for reason in reasons if reason)
            raise HttpDownloadError(f"没有任何文件下载成功：{detail}" if detail else "没有任何文件下载成功")
        try:
            pikpak_cleanup_result = await self.cleanup_completed_pikpak_transfer_items(success_files)
        except Exception as exc:
            pikpak_cleanup_result = {
                "success": False,
                "status": "failed",
                "requested_count": 0,
                "deleted_count": 0,
                "accounts": [],
                "errors": [{"message": self._sanitize_error(exc)}],
            }
        task.task_metadata["pikpak_cleanup_result"] = pikpak_cleanup_result
        self._task_gids.pop(task.id, None)

        cleanup_suffix = ""
        cleanup_requested = int(pikpak_cleanup_result.get("requested_count") or 0)
        cleanup_deleted = int(pikpak_cleanup_result.get("deleted_count") or 0)
        if cleanup_requested > 0 and pikpak_cleanup_result.get("success"):
            cleanup_suffix = f"，PikPak 已清理 {cleanup_deleted} 个"
        elif cleanup_requested > 0:
            errors = list(pikpak_cleanup_result.get("errors") or [])
            first_error = str((errors[0] or {}).get("message") or "").strip() if errors else ""
            cleanup_suffix = f"，PikPak 清理失败: {first_error or '请在设置页手动清理'}"
        if task.is_cancelled():
            raise asyncio.CancelledError()
        final_message = "下载完成" if not merged_failed_rows else "下载部分成功"
        task.update_progress(100, f"{final_message}，成功 {len(success_files)} 个，失败 {len(merged_failed_rows)} 个{cleanup_suffix}")
        return {
            "success": not bool(merged_failed_rows),
            "partial_success": bool(success_files and merged_failed_rows),
            "status": final_status,
            "download_root": self._download_root(),
            "downloaded_files": success_files,
            "failed_files": merged_failed_rows,
            "pikpak_cleanup_result": pikpak_cleanup_result,
        }

    def _content_length_from_headers(self, headers: Dict[str, str]) -> int:
        content_range = str(headers.get("content-range") or "")
        match = re.search(r"/(\d+)\s*$", content_range)
        if match:
            return int(match.group(1))
        return int(headers.get("content-length") or 0)

    async def reset_task_for_retry(
        self,
        task,
        *,
        retry_items: Optional[List[Dict[str, Any]]] = None,
        retry_keys: Optional[List[str]] = None,
    ) -> None:
        metadata = dict(task.task_metadata or {})
        urls = list(metadata.get("urls") or [])
        if retry_items is None or retry_keys is None:
            retry_items, retry_keys = self.build_retry_selection_for_task(task)
        from .task_engine import TaskStatus

        attempt_history = self.merge_download_attempt_rows(
            [
                item for item in list(metadata.get("download_attempt_history") or [])
                if isinstance(item, dict)
            ],
            [
                item for item in list(metadata.get("download_files") or [])
                if isinstance(item, dict)
            ],
            [
                item for item in list(metadata.get("failed_files") or [])
                if isinstance(item, dict)
            ],
        )
        if attempt_history:
            task.task_metadata["download_attempt_history"] = [
                sanitize_http_download_item(item)
                for item in attempt_history
            ]
        task.task_metadata["urls"] = urls
        if retry_items:
            task.task_metadata["selected_items"] = [
                sanitize_http_download_item(item)
                for item in retry_items
            ]
            task.task_metadata["selected_keys"] = retry_keys
            task.task_metadata["retry_target_count"] = len(retry_items)
        else:
            task.task_metadata["retry_target_count"] = 0
        task.task_metadata["resolved_urls"] = []
        task.task_metadata["download_files"] = []
        task.task_metadata["download_runtime"] = {}
        task.task_metadata["failed_files"] = []
        task.task_metadata["performance_metrics"] = {}
        task.task_metadata["failure_reason"] = ""
        task.task_metadata["retry_count"] = int(task.task_metadata.get("retry_count") or 0) + 1
        task.status = TaskStatus.PENDING
        task.progress = 0
        task.current_step = "等待重试 HTTP 下载"
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task._cancelled = False
        task._pause_event.set()

    def _append_control_log(self, task, message: str, level: str = "info") -> None:
        if not task:
            return
        logs = list((task.task_metadata or {}).get("progress_log") or [])
        logs.append({
            "time": datetime.now().isoformat(),
            "ts": datetime.now().strftime("%H:%M:%S"),
            "progress": int(getattr(task, "progress", 0) or 0),
            "message": message,
            "level": level,
        })
        task.task_metadata["progress_log"] = logs[-80:]

    async def _tell_status(self, gid: str) -> Dict[str, Any]:
        keys = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "files", "errorMessage"]
        try:
            return await self._rpc_call("aria2.tellStatus", [gid, keys])
        except Exception as exc:
            stopped = await self._rpc_call("aria2.tellStopped", [0, 100, keys])
            for item in stopped or []:
                if str(item.get("gid") or "") == str(gid):
                    return item
            raise exc

    async def _poll_task(self, gids: List[str], rows: List[Dict[str, Any]]):
        row_by_gid = {str(row.get("gid")): row for row in rows}
        total_bytes = 0
        transferred = 0
        speed = 0
        completed = 0
        active_count = 0
        active_name = ""
        active_rel = ""
        failed_count = 0
        for gid in gids:
            try:
                status = await self._tell_status(gid)
            except Exception as exc:
                row = row_by_gid.get(str(gid))
                if row and str(row.get("status") or "") != "completed":
                    row["status"] = "failed"
                    row["failure_reason"] = str(exc)
                    failed_count += 1
                continue
            row = row_by_gid.get(str(gid))
            if not row:
                continue
            aria_status = str(status.get("status") or "")
            total = int(status.get("totalLength") or row.get("total") or 0)
            done = int(status.get("completedLength") or 0)
            total_bytes += total
            transferred += done
            row_speed = int(status.get("downloadSpeed") or 0)
            speed += row_speed
            row["total"] = total
            row["size"] = total
            row["downloaded"] = done
            row["speed_bytes_per_sec"] = row_speed
            row["progress"] = 100 if aria_status == "complete" else (int(done / total * 100) if total else 0)
            if aria_status == "complete":
                expected_size = int(row.get("expected_size_bytes") or 0)
                if (
                    str(row.get("source") or "").strip().lower() == "gofile"
                    and expected_size > 0
                    and done < expected_size
                ):
                    row["status"] = "failed"
                    row["failure_reason"] = (
                        f"Gofile 下载结果大小异常: 实际 {done} bytes，小于 API 文件大小 {expected_size} bytes，"
                        "可能下载到了源站错误页"
                    )
                    row["total"] = expected_size
                    row["size"] = expected_size
                    row["progress"] = min(99, int(done / expected_size * 100)) if expected_size else 0
                    failed_count += 1
                    local_path = str(row.get("local_path") or "").strip()
                    if local_path and done <= max(64 * 1024, int(expected_size * 0.01)):
                        with contextlib.suppress(OSError):
                            os.remove(local_path)
                else:
                    row["status"] = "completed"
                    completed += 1
            elif aria_status in {"error", "removed"}:
                row["status"] = "failed"
                row["failure_reason"] = status.get("errorMessage") or aria_status
                failed_count += 1
            elif aria_status == "paused":
                row["status"] = "paused"
            else:
                row["status"] = "downloading"
                active_count += 1
                if not active_name:
                    active_name = str(row.get("name") or "")
                    active_rel = str(row.get("relative_path") or "")
        runtime = {
            "status": "downloading",
            "total_files": len(rows),
            "completed_files": completed,
            "failed_files": failed_count,
            "active_file_count": active_count,
            "transferred_bytes": transferred,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": speed,
            "current_file_name": active_name,
            "current_relative_path": active_rel,
        }
        all_done = completed + failed_count >= len(rows)
        return rows, runtime, all_done, failed_count

    async def pause_task(self, task_id: str) -> None:
        for gid in self._task_gids.get(task_id, []):
            with contextlib.suppress(Exception):
                await self._rpc_call("aria2.pause", [gid])

    async def resume_task(self, task_id: str) -> None:
        for gid in self._task_gids.get(task_id, []):
            with contextlib.suppress(Exception):
                await self._rpc_call("aria2.unpause", [gid])

    async def cancel_task(self, task_id: str) -> None:
        active_task = self._active_download_tasks.pop(task_id, None)
        if active_task and not active_task.done():
            active_task.cancel()
        for gid in self._task_gids.get(task_id, []):
            with contextlib.suppress(Exception):
                await self._rpc_call("aria2.remove", [gid])
        self._task_gids.pop(task_id, None)

    async def health(self) -> Dict[str, Any]:
        cfg = self._config()
        result = {
            "enabled": bool(getattr(cfg, "enabled", True)),
            "engine": str(getattr(cfg, "engine", "aria2") or "aria2"),
            "download_root": self._download_root(),
            "aria2_path": str(getattr(cfg, "aria2_path", "aria2c") or "aria2c"),
            "proxy_configured": bool(str(getattr(cfg, "proxy_url", "") or "").strip()),
            "proxy": self._mask_url(str(getattr(cfg, "proxy_url", "") or "")),
            "ok": False,
            "message": "",
        }
        try:
            version = await self._rpc_call("aria2.getVersion", [])
            result.update({"ok": True, "version": version, "message": "aria2 可用"})
        except Exception as exc:
            result.update({"ok": False, "message": str(exc)})
        pikpak_ready = False
        pikpak_message = ""
        if self._pikpak_enabled():
            accounts = self._pikpak_accounts()
            pikpak_ready = bool(accounts)
            pikpak_message = f"PikPak 已配置 {len(accounts)} 个账号" if pikpak_ready else "PikPak 已启用但缺少账号或 token"
        result.update({
            "pikpak_enabled": self._pikpak_enabled(),
            "pikpak_ready": pikpak_ready,
            "pikpak_message": pikpak_message,
            "gofile_ready": bool(self._gofile_token()),
        })
        return result


_http_download_service: Optional[HttpDownloadService] = None


def get_http_download_service() -> HttpDownloadService:
    global _http_download_service
    if _http_download_service is None:
        _http_download_service = HttpDownloadService()
    return _http_download_service
