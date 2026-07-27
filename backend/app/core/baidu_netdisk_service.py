import asyncio
import base64
import contextlib
import copy
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

import aiohttp
import requests

from ..config.settings import get_config, save_config
from .fs_utils import move_path_efficient
from .http_download_service import sanitize_http_download_item
from .resource_budget_service import get_resource_budget_service

logger = logging.getLogger(__name__)

BAIDU_NETDISK_LABEL = "百度网盘"
BAIDU_NETDISK_PLATFORM = "baidu_netdisk"
BAIDU_OFFICIAL_LOGIN_URL = "https://pan.baidu.com/"
BAIDU_QR_GET_URL = "https://passport.baidu.com/v2/api/getqrcode"
BAIDU_QR_UNICAST_URL = "https://passport.baidu.com/channel/unicast"
BAIDU_QR_BDUSS_LOGIN_URL = "https://passport.baidu.com/v3/login/main/qrbdusslogin"
BAIDU_QR_LOGIN_TTL_SECONDS = 180
_BAIDU_WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_ILLEGAL_WINDOWS_CHARS = set('<>:"\\|?*')
_BAIDU_COOKIE_PRIORITY = [
    "BDUSS",
    "BDUSS_BFESS",
    "STOKEN",
    "STOKEN_BFESS",
    "PTOKEN",
    "PTOKEN_BFESS",
    "BAIDUID",
    "BAIDUID_BFESS",
    "PANPSC",
    "BDCLND",
]
_BAIDU_COOKIE_NAME_BY_UPPER = {name.upper(): name for name in _BAIDU_COOKIE_PRIORITY}
_BAIDU_RAW_PREVIEW_CACHE_TTL_SECONDS = 10 * 60
_BAIDU_PREVIEW_TOTAL_TIMEOUT_SECONDS = 38.0
_BAIDU_PREVIEW_ITEM_TIMEOUT_SECONDS = 24.0
_BAIDU_PREVIEW_HTTP_TIMEOUT_SECONDS = 8.0
_BAIDU_PREVIEW_MAX_CONCURRENCY = 4
_BAIDU_LOW_SPEED_MIN_FILE_SIZE_BYTES = 512 * 1024 * 1024
_BAIDU_TRANSFER_RETRY_DELAYS_SECONDS = (0, 2, 5, 12, 30)


class BaiduNetdiskError(ValueError):
    """百度网盘下载的可预期业务错误。"""


class BaiduNetdiskLowSpeedError(BaiduNetdiskError):
    """BaiduPCS-Go 持续低速，需要保留断点并重新获取下载线路。"""

    def __init__(self, average_speed_bytes: int, window_seconds: int, checkpoint_bytes: int):
        self.average_speed_bytes = max(0, int(average_speed_bytes or 0))
        self.window_seconds = max(0, int(window_seconds or 0))
        self.checkpoint_bytes = max(0, int(checkpoint_bytes or 0))
        super().__init__(
            f"BaiduPCS-Go 持续低速：近 {self.window_seconds} 秒平均 "
            f"{self.average_speed_bytes / 1024 / 1024:.2f} MB/s"
        )


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _safe_timestamp(value: Any) -> int:
    """把百度接口里秒 / 毫秒 / 日期字符串统一成秒级时间戳。"""
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        number = int(float(text))
        if number > 10_000_000_000:
            number = number // 1000
        return number if number >= 946684800 else 0
    except Exception:
        pass
    normalized = text.replace("T", " ").replace("Z", "").strip()
    normalized = normalized.split(".", 1)[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(normalized, fmt).timestamp())
        except Exception:
            continue
    return 0


def _first_timestamp_field(payload: Dict[str, Any], keys: List[str]) -> int:
    for key in keys:
        value = payload.get(key)
        timestamp = _safe_timestamp(value)
        if timestamp:
            return timestamp
    for value in payload.values():
        if isinstance(value, dict):
            timestamp = _first_timestamp_field(value, keys)
            if timestamp:
                return timestamp
    return 0


def _first_nonempty_field(payload: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = payload.get(key)
        text = str(value or "").strip()
        if text:
            return text
    for value in payload.values():
        if isinstance(value, dict):
            text = _first_nonempty_field(value, keys)
            if text:
                return text
    return ""


def mask_baidu_cookie(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = []
    for item in text.split(";"):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        if key.upper() in {"BDUSS", "STOKEN", "BAIDUID", "PANPSC"}:
            masked = f"{raw_value[:4]}...{raw_value[-4:]}" if len(raw_value) > 10 else "***"
        else:
            masked = "***"
        parts.append(f"{key}={masked}")
    return "; ".join(parts) if parts else "***"


def sanitize_baidu_netdisk_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    out = sanitize_http_download_item(item)
    has_extract_password = bool(str(item.get("custom_extract_password") or item.get("extract_password") or "").strip())
    out.pop("cookie", None)
    out.pop("bdstoken", None)
    out.pop("randsk", None)
    out.pop("share_sign", None)
    out.pop("share_timestamp", None)
    out.pop("share_numeric_id", None)
    out.pop("share_uk", None)
    out.pop("shorturl", None)
    out.pop("pass_code", None)
    out.pop("custom_extract_password", None)
    out.pop("extract_password", None)
    custom_file_names = out.pop("custom_file_names", None)
    sanitized_file_names: Dict[str, Dict[str, str]] = {}
    if isinstance(custom_file_names, dict):
        for key, value in custom_file_names.items():
            if not isinstance(value, dict):
                continue
            custom_name = str(value.get("custom_name") or value.get("custom_filename") or "").strip()
            file_has_password = bool(str(value.get("custom_extract_password") or value.get("extract_password") or "").strip())
            if file_has_password:
                has_extract_password = True
            if custom_name or file_has_password:
                sanitized_file_names[str(key)] = {
                    "custom_name": custom_name,
                    "has_extract_password": file_has_password,
                    "fs_id": str(value.get("fs_id") or value.get("fsid") or "").strip(),
                    "path": str(value.get("path") or value.get("remote_path") or "").strip(),
                    "relative_path": str(value.get("relative_path") or "").strip(),
                    "name": str(value.get("name") or "").strip(),
                }
    if sanitized_file_names:
        out["custom_file_names"] = sanitized_file_names
    if has_extract_password:
        out["has_extract_password"] = True
    if isinstance(out.get("preview_files"), list):
        clean_preview_files = []
        for file_item in out.get("preview_files") or []:
            if not isinstance(file_item, dict):
                continue
            clean_file = dict(file_item)
            if str(clean_file.get("custom_extract_password") or clean_file.get("extract_password") or "").strip():
                clean_file["has_extract_password"] = True
            clean_file.pop("custom_extract_password", None)
            clean_file.pop("extract_password", None)
            clean_preview_files.append(clean_file)
        out["preview_files"] = clean_preview_files
    out.pop("share_files", None)
    out.pop("share_tokens", None)
    return out


def sanitize_baidu_netdisk_preview(preview: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(preview, dict):
        return {}
    out = dict(preview)
    out.pop("raw_preview_cache_key", None)
    out["items"] = [
        sanitize_baidu_netdisk_item(item)
        for item in list(out.get("items") or [])
        if isinstance(item, dict)
    ]
    if "source_items" in out:
        out["source_items"] = [
            sanitize_baidu_netdisk_item(item)
            for item in list(out.get("source_items") or [])
            if isinstance(item, dict)
        ]
    return out


def sanitize_baidu_netdisk_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    out = dict(metadata)
    out.pop("urls", None)
    out.pop("raw_preview_cache_key", None)
    out.pop("raw_preview_items", None)
    out.pop("raw_selected_items", None)
    for key in ("download_files", "failed_files", "downloaded_files", "upload_files", "uploaded_files"):
        if key in out:
            out[key] = [
                sanitize_baidu_netdisk_item(item)
                for item in list(out.get(key) or [])
                if isinstance(item, dict)
            ]
    for key in ("selected_items", "preview_items", "source_items"):
        if key in out:
            out[key] = [
                sanitize_baidu_netdisk_item(item)
                for item in list(out.get(key) or [])
                if isinstance(item, dict)
            ]
    return out


def build_baidu_netdisk_batch_title(metadata: Dict[str, Any], item_count: int = 0) -> str:
    count = int(item_count or metadata.get("selected_count") or metadata.get("url_count") or 0)
    if count > 1:
        return f"百度网盘下载 {count} 项"
    return "百度网盘下载"


class BaiduNetdiskService:
    """百度网盘分享下载 / 本地上传服务，通过 BaiduPCS-Go 执行传输。"""

    def __init__(self):
        self._task_cancel_events: Dict[str, asyncio.Event] = {}
        self._official_login_session: Optional[Dict[str, Any]] = None
        self._qr_login_sessions: Dict[str, Dict[str, Any]] = {}
        self._raw_preview_cache: Dict[str, Dict[str, Any]] = {}
        self._download_slot_lock = threading.Lock()
        self._download_slot_active = 0
        self._transfer_slot_lock = threading.Lock()
        self._transfer_slot_active = 0

    def _config(self):
        return get_config().baidu_netdisk

    def _download_root(self) -> str:
        cfg = self._config()
        root = str(getattr(cfg, "download_root", "") or "").strip()
        if not root:
            root = str(getattr(get_config().http_downloader, "download_root", "") or "").strip()
        if not root:
            root = str(getattr(get_config().storage, "input_path", "") or "").strip()
        if not root:
            root = os.path.join(get_config().storage.temp_path, "baidu_netdisk_downloads")
        return os.path.abspath(root)

    def _default_upload_remote_dir(self) -> str:
        value = str(getattr(self._config(), "upload_default_remote_dir", "") or "").strip()
        return self._normalize_remote_dir(value or "/KikoeruManager")

    def _normalize_remote_dir(self, value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        text = re.sub(r"/+", "/", text)
        if not text:
            text = "/KikoeruManager"
        if not text.startswith("/"):
            text = f"/{text}"
        if len(text) > 1:
            text = text.rstrip("/")
        parts = [part for part in text.split("/") if part]
        safe_parts = []
        for part in parts:
            clean = self._sanitize_path_part(part, "未命名")
            if clean in {".", ".."}:
                continue
            safe_parts.append(clean)
        return "/" + "/".join(safe_parts) if safe_parts else "/"

    def _join_remote_dir(self, base: Any, child: Any = "") -> str:
        root = self._normalize_remote_dir(base)
        sub = str(child or "").strip().replace("\\", "/").strip("/")
        if not sub:
            return root
        clean_parts = [
            self._sanitize_path_part(part, "未命名")
            for part in sub.split("/")
            if part and part not in {".", ".."}
        ]
        if not clean_parts:
            return root
        return self._normalize_remote_dir(root.rstrip("/") + "/" + "/".join(clean_parts))

    def _upload_conflict_policy(self, value: Any = "") -> str:
        text = str(value or "").strip().lower()
        if text not in {"skip", "overwrite", "rsync"}:
            text = str(getattr(self._config(), "upload_conflict_policy", "") or "skip").strip().lower()
        return text if text in {"skip", "overwrite", "rsync"} else "skip"

    def _configured_baidu_cookie(self) -> str:
        cookie = str(getattr(self._config(), "cookie", "") or "").strip()
        if not cookie or cookie == "********":
            return ""
        return cookie

    def _has_baidu_login_cookie(self, cookie: str = "") -> bool:
        value = str(cookie or "").strip() or self._configured_baidu_cookie()
        return bool(self._cookie_value(value, "BDUSS") or self._cookie_value(value, "BDUSS_BFESS"))

    def raw_preview_cache_key(
        self,
        urls: List[str],
        *,
        target_subdir: str = "",
        conflict_policy: str = "",
        output_folder_name: str = "",
    ) -> str:
        cfg = self._config()
        cookie_digest = hashlib.sha1(str(getattr(cfg, "cookie", "") or "").encode("utf-8", errors="ignore")).hexdigest()
        payload = {
            "urls": [str(url or "").strip() for url in urls or []],
            "target_subdir": str(target_subdir or "").strip(),
            "conflict_policy": str(conflict_policy or "").strip(),
            "output_folder_name": str(output_folder_name or "").strip(),
            "account_uk": str(getattr(cfg, "account_uk", "") or "").strip(),
            "cookie_digest": cookie_digest,
        }
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(body.encode("utf-8", errors="ignore")).hexdigest()

    def get_cached_raw_preview(self, cache_key: str) -> Optional[Dict[str, Any]]:
        key = str(cache_key or "").strip()
        if not key:
            return None
        entry = self._raw_preview_cache.get(key)
        if not entry:
            return None
        if time.monotonic() - float(entry.get("cached_at") or 0) > _BAIDU_RAW_PREVIEW_CACHE_TTL_SECONDS:
            self._raw_preview_cache.pop(key, None)
            return None
        preview = entry.get("preview")
        return copy.deepcopy(preview) if isinstance(preview, dict) else None

    def _cache_raw_preview(self, cache_key: str, preview: Dict[str, Any]) -> None:
        key = str(cache_key or "").strip()
        if not key or not isinstance(preview, dict):
            return
        now = time.monotonic()
        expired = [
            item_key for item_key, entry in self._raw_preview_cache.items()
            if now - float(entry.get("cached_at") or 0) > _BAIDU_RAW_PREVIEW_CACHE_TTL_SECONDS
        ]
        for item_key in expired:
            self._raw_preview_cache.pop(item_key, None)
        self._raw_preview_cache[key] = {
            "cached_at": now,
            "preview": copy.deepcopy(preview),
        }

    def _config_dir(self) -> str:
        cfg = self._config()
        configured = str(getattr(cfg, "config_dir", "") or "").strip()
        if configured:
            return os.path.abspath(configured)
        return os.path.abspath(str(self._repo_root() / ".runtime" / "baidu_netdisk_pcsgo"))

    def _official_login_profile_dir(self) -> str:
        return os.path.abspath(str(self._repo_root() / ".runtime" / "baidu_netdisk_login_browser"))

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _safe_join(self, root: str, *parts: str) -> str:
        root_abs = os.path.abspath(root)
        candidate = os.path.abspath(os.path.join(root_abs, *[str(part or "") for part in parts if str(part or "")]))
        try:
            common = os.path.commonpath([root_abs, candidate])
        except Exception as exc:
            raise BaiduNetdiskError("目标路径非法") from exc
        if common != root_abs:
            raise BaiduNetdiskError("目标路径不能越过下载根目录")
        return candidate

    def _safe_subdir(self, value: str) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            return ""
        parts = []
        for part in text.split("/"):
            part = part.strip()
            if not part:
                continue
            if part in {".", ".."} or ".." in part:
                raise BaiduNetdiskError("目标子目录不能包含 ..")
            if any(ch in _ILLEGAL_WINDOWS_CHARS for ch in part):
                raise BaiduNetdiskError("目标子目录包含 Windows 非法字符")
            parts.append(part.rstrip(" ."))
        return "/".join([part for part in parts if part])

    def validate_output_folder_name(self, value: str, *, allow_empty: bool = True) -> str:
        text = str(value or "").strip()
        if not text:
            if allow_empty:
                return ""
            raise BaiduNetdiskError("保存为文件夹名不能为空")
        text = text.replace("\\", "/")
        if "/" in text:
            raise BaiduNetdiskError("保存为文件夹名只能是单层目录名")
        if text in {".", ".."} or ".." in text:
            raise BaiduNetdiskError("保存为文件夹名不能包含 ..")
        if any(ch in _ILLEGAL_WINDOWS_CHARS for ch in text):
            raise BaiduNetdiskError("保存为文件夹名包含 Windows 非法字符")
        text = text.rstrip(" .")
        if not text:
            raise BaiduNetdiskError("保存为文件夹名不能为空")
        return text[:180]

    def _sanitize_folder_name(self, value: str, fallback: str = "百度网盘下载") -> str:
        text = str(value or "").strip()
        text = re.sub(r'[<>:"\\|?*\x00-\x1f]+', "_", text)
        text = text.replace("/", "_").strip().rstrip(" .")
        return text[:180] or fallback

    def _default_download_batch_folder_name(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = f"{BAIDU_NETDISK_LABEL}_{timestamp}"
        return self._sanitize_folder_name(fallback, fallback=fallback)

    def _download_batch_folder_name(self, metadata: Dict[str, Any]) -> str:
        existing = str((metadata or {}).get("download_batch_folder_name") or "").strip()
        if existing:
            return self._sanitize_folder_name(existing, fallback=self._default_download_batch_folder_name())
        return self._default_download_batch_folder_name()

    def _sanitize_path_part(self, value: Any, fallback: str = "未命名") -> str:
        text = str(value or "").strip()
        text = re.sub(r'[<>:"\\|?*\x00-\x1f]+', "_", text)
        text = text.strip(" .")
        return text[:180] or fallback

    def _safe_relative_path(self, value: Any, fallback: str = "download.bin") -> str:
        text = str(value or "").strip().replace("\\", "/")
        parts = []
        for part in text.split("/"):
            part = part.strip()
            if not part or part in {".", ".."} or ".." in part:
                continue
            safe = self._sanitize_path_part(part, "")
            if safe:
                parts.append(safe)
        if parts:
            return os.path.join(*parts)
        return self._sanitize_path_part(fallback, "download.bin")

    def _selection_key(self, item: Dict[str, Any]) -> str:
        existing = str(item.get("selection_key") or "").strip()
        if existing:
            return existing
        parts = [
            BAIDU_NETDISK_PLATFORM,
            str(item.get("share_id") or ""),
            str(item.get("share_url") or ""),
            str(item.get("filename") or item.get("name") or ""),
            str(item.get("path") or ""),
            str(item.get("pass_code") or ""),
        ]
        digest = hashlib.sha1("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"{BAIDU_NETDISK_PLATFORM}:{digest}"

    def _download_row_identity(self, row: Dict[str, Any]) -> str:
        if not isinstance(row, dict):
            return ""
        gid = str(row.get("gid") or "").strip()
        if gid:
            return gid
        fs_id = str(row.get("fs_id") or row.get("fsid") or "").strip()
        share_key = (
            str(row.get("selection_key") or "").strip()
            or str(row.get("share_id") or "").strip()
            or str(row.get("share_url") or row.get("url") or "").strip()
        )
        if fs_id:
            return f"{BAIDU_NETDISK_PLATFORM}:{share_key}:{fs_id}" if share_key else f"{BAIDU_NETDISK_PLATFORM}:fs:{fs_id}"
        relative_path = str(row.get("relative_path") or row.get("original_relative_path") or "").strip().replace("\\", "/").strip("/")
        remote_path = str(row.get("remote_path") or row.get("path") or "").strip().replace("\\", "/").strip("/")
        name = str(row.get("name") or row.get("filename") or row.get("original_name") or "").strip()
        identity = relative_path or remote_path or name
        if identity:
            return f"{BAIDU_NETDISK_PLATFORM}:{share_key}:{identity.lower()}" if share_key else f"{BAIDU_NETDISK_PLATFORM}:path:{identity.lower()}"
        return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)

    def _download_row_completed(self, row: Dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        status = str(row.get("status") or "").strip().lower()
        if status == "completed":
            return True
        progress = _safe_int(row.get("progress"))
        total = _safe_int(row.get("total") or row.get("size"))
        downloaded = _safe_int(row.get("downloaded"))
        return bool(progress >= 100 or (total > 0 and downloaded >= total))

    def _retry_failed_rows_from_metadata(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        completed_keys = {
            self._download_row_identity(row)
            for row in list((metadata or {}).get("download_files") or [])
            if isinstance(row, dict) and self._download_row_completed(row)
        }

        def add_row(row: Dict[str, Any]) -> None:
            if not isinstance(row, dict):
                return
            key = self._download_row_identity(row)
            if key and key in completed_keys:
                return
            if key and key in seen:
                return
            if key:
                seen.add(key)
            rows.append(dict(row))

        for row in list((metadata or {}).get("failed_files") or []):
            add_row(row)
        for row in list((metadata or {}).get("download_files") or []):
            if not isinstance(row, dict) or self._download_row_completed(row):
                continue
            add_row(row)
        return rows

    def _same_download_row(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        left_key = self._download_row_identity(left)
        right_key = self._download_row_identity(right)
        if left_key and right_key and left_key == right_key:
            return True
        left_fs_id = str(left.get("fs_id") or left.get("fsid") or "").strip()
        right_fs_id = str(right.get("fs_id") or right.get("fsid") or "").strip()
        if left_fs_id and right_fs_id and left_fs_id == right_fs_id:
            return True
        for field in ("relative_path", "original_relative_path", "remote_path", "path", "name", "filename"):
            left_value = str(left.get(field) or "").strip().replace("\\", "/").strip("/").lower()
            right_value = str(right.get(field) or "").strip().replace("\\", "/").strip("/").lower()
            if left_value and right_value and left_value == right_value:
                return True
        return False

    def _item_matches_failed_row(self, item: Dict[str, Any], row: Dict[str, Any], *, only_item_scope: bool = False) -> bool:
        if not isinstance(item, dict) or not isinstance(row, dict):
            return False
        item_selection_key = self._selection_key(item)
        row_gid = str(row.get("gid") or "").strip()
        if item_selection_key and row_gid and row_gid.startswith(f"{item_selection_key}:"):
            return True
        item_share_ids = {
            str(item.get("selection_key") or "").strip(),
            item_selection_key,
            str(item.get("share_id") or "").strip(),
            str(item.get("shorturl") or "").strip(),
            str(item.get("share_url") or item.get("url") or "").strip(),
        }
        row_share_ids = {
            str(row.get("selection_key") or "").strip(),
            str(row.get("share_id") or "").strip(),
            str(row.get("shorturl") or "").strip(),
            str(row.get("share_url") or row.get("url") or "").strip(),
        }
        if any(value and value in item_share_ids for value in row_share_ids):
            return True
        if only_item_scope:
            return False
        item_files = [
            file_item for file_item in list(item.get("share_files") or item.get("preview_files") or [])
            if isinstance(file_item, dict)
        ]
        return any(self._same_download_row(file_item, row) for file_item in item_files)

    def _retry_share_file_from_failed_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row or {})
        remote_path = str(item.get("remote_path") or item.get("path") or "").strip()
        if remote_path:
            item["path"] = remote_path
        item["name"] = str(item.get("name") or item.get("filename") or item.get("original_name") or "百度网盘文件").strip()
        item["relative_path"] = str(item.get("relative_path") or item.get("original_relative_path") or item.get("name") or "").strip()
        item["size"] = _safe_int(item.get("size") or item.get("total") or item.get("size_bytes"))
        item["size_bytes"] = item["size"]
        item["is_dir"] = False
        item["isdir"] = 0
        return item

    def _retry_item_from_failed_rows(self, source_item: Dict[str, Any], failed_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        retry_item = dict(source_item or {})
        retry_files = [self._retry_share_file_from_failed_row(row) for row in failed_rows if isinstance(row, dict)]
        retry_item.pop("custom_group_folder", None)
        retry_item.pop("custom_name", None)
        retry_item.pop("custom_filename", None)
        retry_item["ok"] = True
        retry_item["share_files"] = retry_files
        retry_item["preview_files"] = copy.deepcopy(retry_files)
        retry_item["preview_file_count"] = len(retry_files)
        retry_item["preview_folder_count"] = 0
        retry_item["size"] = sum(_safe_int(row.get("size") or row.get("total") or row.get("size_bytes")) for row in retry_files)
        retry_item["size_bytes"] = retry_item["size"]
        retry_item["selection_key"] = self._selection_key(retry_item)
        return retry_item

    def _retry_items_from_failed_rows(self, metadata: Dict[str, Any], failed_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        source_items = [
            item for item in list((metadata or {}).get("raw_selected_items") or [])
            if isinstance(item, dict)
        ]
        if not source_items:
            source_items = [
                item for item in list((metadata or {}).get("selected_items") or [])
                if isinstance(item, dict)
            ]
        retry_items: List[Dict[str, Any]] = []
        used_row_keys: set[str] = set()
        for source_item in source_items:
            matched_rows = [
                row for row in failed_rows
                if isinstance(row, dict) and self._item_matches_failed_row(source_item, row)
            ]
            if not matched_rows:
                continue
            retry_items.append(self._retry_item_from_failed_rows(source_item, matched_rows))
            used_row_keys.update(self._download_row_identity(row) for row in matched_rows if self._download_row_identity(row))
        for row in failed_rows:
            row_key = self._download_row_identity(row)
            if row_key and row_key in used_row_keys:
                continue
            retry_items.append(self._retry_item_from_failed_rows(row, [row]))
        return retry_items

    def build_retry_selection_for_task(self, task) -> tuple[List[Dict[str, Any]], List[str]]:
        metadata = dict(getattr(task, "task_metadata", None) or {})
        failed_rows = self._retry_failed_rows_from_metadata(metadata)
        retry_items = self._retry_items_from_failed_rows(metadata, failed_rows)
        if not retry_items:
            retry_items = [
                dict(item)
                for item in list(metadata.get("raw_selected_items") or metadata.get("selected_items") or [])
                if isinstance(item, dict)
            ]
        retry_keys = [self._selection_key(item) for item in retry_items if self._selection_key(item)]
        return retry_items, retry_keys

    def build_retry_selection_for_file(self, task, file_row: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
        if not isinstance(file_row, dict):
            return [], []
        metadata = dict(getattr(task, "task_metadata", None) or {})
        candidates = self._retry_failed_rows_from_metadata(metadata)
        matched_rows = [row for row in candidates if self._same_download_row(row, file_row)]
        if not matched_rows:
            requested_identity = self._download_row_identity(file_row)
            matched_rows = [row for row in candidates if requested_identity and self._download_row_identity(row) == requested_identity]
        if not matched_rows:
            return [], []
        retry_items = self._retry_items_from_failed_rows(metadata, matched_rows)
        retry_keys = [self._selection_key(item) for item in retry_items if self._selection_key(item)]
        return retry_items, retry_keys

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
                key = self._selection_key(item)
                if key:
                    keys.add(key)
        selected_overrides = {
            self._selection_key(item): self._baidu_selected_item_overrides(item)
            for item in (selected_items or [])
            if isinstance(item, dict) and self._selection_key(item)
        }
        if not keys:
            return preview
        out = dict(preview or {})
        items = []
        for item in list(out.get("items") or []):
            if not isinstance(item, dict):
                continue
            key = self._selection_key(item)
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

    def _baidu_selected_item_overrides(self, item: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        custom_name = str(item.get("custom_name") or item.get("custom_filename") or "").strip()
        custom_extract_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        custom_file_names = self._baidu_selected_file_overrides(item)
        selected_files = self._baidu_selected_preview_files(item)
        overrides: Dict[str, Any] = {}
        if custom_name:
            overrides["custom_name"] = custom_name
        if custom_extract_password:
            overrides["custom_extract_password"] = custom_extract_password
        if bool(item.get("custom_group_folder")):
            overrides["custom_group_folder"] = True
        if custom_file_names:
            overrides["custom_file_names"] = custom_file_names
        if selected_files:
            selected_size = sum(_safe_int(row.get("size_bytes") or row.get("size")) for row in selected_files)
            selected_folder_count = sum(1 for row in selected_files if row.get("is_dir"))
            overrides["preview_files"] = copy.deepcopy(selected_files)
            overrides["share_files"] = copy.deepcopy(selected_files)
            overrides["preview_file_count"] = len(selected_files)
            overrides["preview_folder_count"] = selected_folder_count
            overrides["size_bytes"] = selected_size
            overrides["size"] = selected_size
        return overrides

    def _baidu_selected_preview_files(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_files = item.get("preview_files")
        if not isinstance(raw_files, list):
            raw_files = item.get("share_files")
        if not isinstance(raw_files, list):
            return []
        files: List[Dict[str, Any]] = []
        for file_item in raw_files:
            if not isinstance(file_item, dict):
                continue
            next_file = dict(file_item)
            files.append(next_file)
        return files

    def _baidu_selected_file_overrides(self, item: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        overrides: Dict[str, Dict[str, str]] = {}

        def add_override(source: Any, base: Optional[Dict[str, Any]] = None) -> None:
            if not isinstance(source, dict):
                return
            custom_name = str(source.get("custom_name") or source.get("custom_filename") or "").strip()
            custom_extract_password = str(source.get("custom_extract_password") or source.get("extract_password") or "").strip()
            if not custom_name and not custom_extract_password:
                return
            merged = dict(base or {})
            merged.update(source)
            normalized = {
                "custom_name": custom_name,
                "custom_extract_password": custom_extract_password,
                "fs_id": str(merged.get("fs_id") or merged.get("fsid") or "").strip(),
                "path": str(merged.get("path") or merged.get("remote_path") or "").strip(),
                "relative_path": str(merged.get("relative_path") or "").strip(),
                "name": str(merged.get("name") or "").strip(),
            }
            keys = [
                normalized["fs_id"],
                normalized["path"],
                normalized["relative_path"],
                normalized["name"],
            ]
            for key in keys:
                if key:
                    overrides[key] = normalized

        raw_overrides = item.get("custom_file_names") or item.get("custom_file_overrides")
        if isinstance(raw_overrides, dict):
            for key, value in raw_overrides.items():
                base = {"relative_path": str(key or "").strip()}
                if isinstance(value, str):
                    add_override({"custom_name": value}, base)
                else:
                    add_override(value, base)
        elif isinstance(raw_overrides, list):
            for value in raw_overrides:
                add_override(value)

        for file_item in list(item.get("preview_files") or []) + list(item.get("share_files") or []):
            add_override(file_item)

        return overrides

    def _preview_from_raw_items(self, items: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        rows = [copy.deepcopy(item) for item in items or [] if isinstance(item, dict)]
        ok_count = sum(1 for item in rows if item.get("ok"))
        return {
            "success": ok_count > 0,
            "source": BAIDU_NETDISK_PLATFORM,
            "source_label": BAIDU_NETDISK_LABEL,
            "download_mode": BAIDU_NETDISK_PLATFORM,
            "items": rows,
            "source_items": copy.deepcopy(rows),
            "selected_keys": [
                self._selection_key(item)
                for item in rows
                if item.get("ok")
            ],
            "ok_count": ok_count,
            "failed_count": len(rows) - ok_count,
            "selected_count": len(rows),
            "svip_speed": self._is_svip(),
            "download_root": self._download_root(),
            "target_subdir": str(metadata.get("target_subdir") or ""),
            "output_folder_name": str(metadata.get("output_folder_name") or ""),
            "conflict_policy": str(metadata.get("conflict_policy") or getattr(self._config(), "conflict_policy", "resume") or "resume"),
        }

    async def _resolve_download_preview(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        raw_selected_items = [
            item for item in list(metadata.get("raw_selected_items") or [])
            if isinstance(item, dict)
        ]
        if raw_selected_items:
            return self._preview_from_raw_items(raw_selected_items, metadata)

        urls = list(metadata.get("urls") or [])
        cache_key = str(metadata.get("raw_preview_cache_key") or "").strip()
        if not cache_key and urls:
            cache_key = self.raw_preview_cache_key(
                urls,
                target_subdir=str(metadata.get("target_subdir") or ""),
                conflict_policy=str(metadata.get("conflict_policy") or ""),
                output_folder_name=str(metadata.get("output_folder_name") or ""),
            )
        cached_preview = self.get_cached_raw_preview(cache_key)
        if cached_preview:
            return self.filter_preview_selection(
                cached_preview,
                selected_keys=list(metadata.get("selected_keys") or []),
                selected_items=list(metadata.get("selected_items") or []),
            )

        preview = await self.preview_urls(
            urls,
            target_subdir=str(metadata.get("target_subdir") or ""),
            conflict_policy=str(metadata.get("conflict_policy") or ""),
            output_folder_name=str(metadata.get("output_folder_name") or ""),
        )
        return self.filter_preview_selection(
            preview,
            selected_keys=list(metadata.get("selected_keys") or []),
            selected_items=list(metadata.get("selected_items") or []),
        )

    def parse_share_inputs(self, urls: List[str]) -> List[Dict[str, str]]:
        rows: List[str] = []
        for raw in urls or []:
            rows.extend(line.strip() for line in re.split(r"[\r\n]+", str(raw or "")) if line.strip())
        shares: List[Dict[str, str]] = []
        seen: Dict[str, int] = {}
        last_index: Optional[int] = None
        for row in rows:
            if self._looks_like_baidu_url(row):
                parsed = self._parse_share_url(row)
                identity = self._share_input_identity(parsed.get("share_url") or row)
                if identity in seen:
                    existing_index = seen[identity]
                    if parsed.get("pass_code") and not shares[existing_index].get("pass_code"):
                        shares[existing_index]["pass_code"] = parsed["pass_code"]
                        shares[existing_index]["share_url"] = self._append_share_pass_code(
                            shares[existing_index].get("share_url") or "",
                            parsed["pass_code"],
                        )
                    last_index = existing_index
                    continue
                shares.append(parsed)
                seen[identity] = len(shares) - 1
                last_index = len(shares) - 1
                continue
            code = self._parse_pass_code_text(row)
            if code and last_index is not None:
                if not shares[last_index].get("pass_code"):
                    shares[last_index]["pass_code"] = code
                    shares[last_index]["share_url"] = self._append_share_pass_code(
                        shares[last_index].get("share_url") or "",
                        code,
                    )
                continue
            raise BaiduNetdiskError(f"无法识别百度网盘分享链接或提取码: {row[:80]}")
        return shares

    def _looks_like_baidu_url(self, value: str) -> bool:
        text = str(value or "").strip().lower()
        return text.startswith(("http://", "https://")) and (
            "pan.baidu.com" in text
            or "yun.baidu.com" in text
            or "eyun.baidu.com" in text
        )

    def _share_feature_str(self, share: Dict[str, str]) -> str:
        raw = str(share.get("shorturl") or share.get("share_id") or "").strip()
        if raw:
            return raw
        parsed = urlparse(str(share.get("raw_url") or share.get("share_url") or ""))
        if parsed.path.rstrip("/").endswith("/init"):
            surl = (parse_qs(parsed.query or "").get("surl") or [""])[0]
            return f"1{surl}".strip()
        match = re.search(r"/s/([A-Za-z0-9_-]+)", parsed.path or "")
        return match.group(1) if match else ""

    def _share_input_identity(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"([?&])(?:pwd|password|passcode|pass_code|code)=[^&#]*", r"\1", text, flags=re.IGNORECASE)
        text = re.sub(r"\?&", "?", text)
        text = re.sub(r"[?&]($|#)", r"\1", text)
        return text.rstrip("?&")

    def _strip_share_pass_code_query(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parsed = urlparse(text)
        if not parsed.query:
            return text
        query_pairs = [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if str(key or "").lower() not in {"pwd", "password", "passcode", "pass_code", "code"}
        ]
        return parsed._replace(query=urlencode(query_pairs)).geturl()

    def _share_url_has_pass_code(self, value: str) -> bool:
        return bool(re.search(r"[?&](?:pwd|password|passcode|pass_code|code)=", str(value or ""), re.IGNORECASE))

    def _append_share_pass_code(self, share_url: str, pass_code: str) -> str:
        code = str(pass_code or "").strip()
        if not code or self._share_url_has_pass_code(share_url):
            return share_url
        return f"{share_url}{'&' if '?' in share_url else '?'}pwd={quote(code)}"

    def _pass_code_from_share_url(self, value: str) -> str:
        parsed = urlparse(str(value or "").strip())
        query = parse_qs(parsed.query or "")
        for key in ("pwd", "password", "passcode", "pass_code", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
        return ""

    def _parse_pass_code_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        match = re.search(
            r"(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)\s*[:：= ]\s*([A-Za-z0-9]{4,12})",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        if re.fullmatch(r"[A-Za-z0-9]{4,12}", text):
            return text
        return ""

    def _parse_share_url(self, raw_url: str) -> Dict[str, str]:
        url = str(raw_url or "").strip()
        separator = str(getattr(self._config(), "share_code_separator", "") or "----").strip()
        inline_pass_code = ""
        if separator and separator in url:
            left, right = url.rsplit(separator, 1)
            code = self._parse_pass_code_text(right)
            if code and self._looks_like_baidu_url(left.strip()):
                url = left.strip()
                inline_pass_code = code
        inline = re.search(
            r"^(https?://\S+?)\s+(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})\s*$",
            url,
            re.IGNORECASE,
        )
        if inline and self._looks_like_baidu_url(inline.group(1)):
            url = inline.group(1).strip()
            inline_pass_code = inline.group(2).strip()
        parsed = urlparse(url)
        query = parse_qs(parsed.query or "")
        pass_code = ""
        for key in ("pwd", "password", "passcode", "pass_code", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                pass_code = str(values[0]).strip()
                break
        if not pass_code:
            pass_code = self._parse_pass_code_text(unquote(parsed.fragment or ""))
        if not pass_code:
            pass_code = inline_pass_code
        share_id = ""
        match = re.search(r"/s/([A-Za-z0-9_-]+)", parsed.path or "")
        if match:
            share_id = match.group(1)
        if not share_id:
            for key in ("surl", "shareid", "uk"):
                values = query.get(key) or []
                if values and str(values[0] or "").strip():
                    share_id = str(values[0]).strip()
                    break
        title = f"百度网盘分享 {share_id[:10]}" if share_id else "百度网盘分享"
        cleaned = url
        if pass_code:
            cleaned = self._append_share_pass_code(cleaned, pass_code)
        return {
            "share_url": cleaned,
            "raw_url": url,
            "shorturl": share_id,
            "share_id": share_id or hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12],
            "pass_code": pass_code,
            "title": title,
        }

    def _preview_item_from_share(
        self,
        share: Dict[str, str],
        target_subdir: str,
        output_folder_name: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        detail = detail or {}
        detail_files = [row for row in list(detail.get("files") or []) if isinstance(row, dict)]
        warning_text = str(detail.get("warning") or "").strip()
        pass_code_invalid = bool(detail.get("pass_code_invalid"))
        missing_code = bool(detail.get("requires_pass_code")) or (
            not detail_files
            and not warning_text
            and self._likely_requires_pass_code(share)
            and not share.get("pass_code")
        )
        has_files = bool(detail_files)
        detail_title = str(detail.get("title") or "").strip()
        detail_file_count = _safe_int(detail.get("file_count") or len(detail_files))
        detail_folder_count = _safe_int(detail.get("folder_count"))
        detail_total_size = _safe_int(detail.get("total_size"))
        title = self._sanitize_folder_name(output_folder_name or detail_title or share.get("title") or "百度网盘分享")
        preview_summary = self._build_share_preview_summary(detail_files, detail_file_count, detail_folder_count)
        item = {
            "ok": not missing_code,
            "url": share.get("share_url") or "",
            "masked_url": share.get("share_url") or "",
            "host": "pan.baidu.com",
            "source": BAIDU_NETDISK_PLATFORM,
            "share_url": share.get("share_url") or "",
            "share_id": share.get("share_id") or "",
            "share_numeric_id": detail.get("share_id") or "",
            "pass_code": share.get("pass_code") or "",
            "shorturl": detail.get("shorturl") or self._share_feature_str(share),
            "share_uk": detail.get("share_uk") or "",
            "bdstoken": detail.get("bdstoken") or "",
            "randsk": detail.get("randsk") or "",
            "share_sign": detail.get("share_sign") or "",
            "share_timestamp": detail.get("share_timestamp") or "",
            "share_files": detail_files,
            "requires_pass_code": bool(missing_code),
            "pass_code_invalid": pass_code_invalid,
            "filename": title,
            "name": title,
            "relative_path": "/".join(part for part in [self._safe_subdir(target_subdir), title] if part),
            "size_bytes": detail_total_size,
            "size": detail_total_size,
            "content_type": "application/x-baidu-netdisk-share",
            "resumable": True,
            "is_dir": True,
            "source_label": BAIDU_NETDISK_LABEL,
            "preview_files": detail_files,
            "preview_summary": preview_summary,
            "preview_file_count": detail_file_count,
            "preview_folder_count": detail_folder_count,
            "preview_root_is_folder": bool(detail.get("preview_root_is_folder")),
        }
        item["selection_key"] = self._selection_key(item)
        item["ok"] = bool(item["ok"] and has_files)
        if missing_code:
            item["reason"] = "提取码错误" if pass_code_invalid else "需要输入提取码"
            item["warning"] = warning_text or ("提取码错误，请重新输入" if pass_code_invalid else "缺提取码，补充后重新预览")
        elif not has_files:
            item["reason"] = warning_text or "未读取到可下载文件"
            if warning_text:
                item["warning"] = warning_text
        elif warning_text:
            item["warning"] = warning_text
        else:
            item.pop("warning", None)
        return item

    def _build_share_preview_summary(self, files: List[Dict[str, Any]], file_count: int = 0, folder_count: int = 0) -> str:
        count = max(_safe_int(file_count), len(files))
        folders = max(_safe_int(folder_count), len([item for item in files if item.get("is_dir")]))
        samples = [
            str(item.get("name") or "").strip()
            for item in files[:3]
            if str(item.get("name") or "").strip()
        ]
        parts: List[str] = []
        if count:
            folder_text = f"，{folders} 个文件夹" if folders else ""
            parts.append(f"包含 {count} 项{folder_text}")
        if samples:
            suffix = " 等" if count > len(samples) else ""
            parts.append(f"{' / '.join(samples)}{suffix}")
        return " · ".join(parts)

    def _share_preview_warning(self, value: Any, fallback: str = "预览失败") -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        lowered = text.lower()
        if any(fragment in lowered for fragment in ("http error 302", "redirect error", "infinite loop")):
            return "百度分享接口跳转异常，已尝试兼容入口；仍失败请确认分享链接和提取码后重试"
        if "params error" in lowered:
            return "百度分享验证接口拒绝当前请求，请确认分享链接和提取码；若浏览器可正常打开，稍后重试或重新绑定百度登录态"
        if any(fragment in text for fragment in ("提取码", "访问码", "密码", "密码错误", "需要输入")):
            return text
        if any(fragment in text for fragment in ("提取", "验证失败", "校验失败")):
            return "需要输入提取码"
        if any(fragment in lowered for fragment in ("verify", "pass", "pwd", "randsk")):
            return "需要输入提取码"
        return text

    def _warning_indicates_pass_code(self, value: Any) -> bool:
        text = str(value or "").strip()
        lowered = text.lower()
        return any(fragment in text for fragment in ("提取码", "访问码", "密码", "需要输入", "验证失败", "校验失败")) or any(
            fragment in lowered for fragment in ("verify", "pass", "pwd", "randsk")
        )

    def _share_verify_error_is_pass_code_invalid(self, errno: int, message: Any) -> bool:
        text = str(message or "").strip()
        lowered = text.lower()
        if errno in {-12, -9, 200025}:
            return True
        return (
            any(fragment in text for fragment in ("提取码错误", "提取码输入错误", "提取码验证失败", "密码错误", "校验失败", "验证码错误"))
            or any(fragment in lowered for fragment in ("invalid pass", "wrong pass", "pwd error"))
        )

    def _likely_requires_pass_code(self, share: Dict[str, str]) -> bool:
        url = str(share.get("raw_url") or share.get("share_url") or "").lower()
        if "pwd=" in url or "pass" in url:
            return False
        return True

    async def preview_urls(self, urls: List[str], target_subdir: str = "", conflict_policy: str = "", output_folder_name: str = "") -> Dict[str, Any]:
        self._safe_subdir(target_subdir)
        self.validate_output_folder_name(output_folder_name, allow_empty=True)
        shares = self.parse_share_inputs(urls)
        if not shares:
            raise BaiduNetdiskError("至少需要一个百度网盘分享链接")

        async def build_preview_item(share: Dict[str, str]) -> Dict[str, Any]:
            detail: Dict[str, Any] = {}
            try:
                detail = await asyncio.wait_for(
                    self._fetch_share_detail(share, request_timeout=_BAIDU_PREVIEW_HTTP_TIMEOUT_SECONDS),
                    timeout=_BAIDU_PREVIEW_ITEM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "百度网盘分享预览详情读取超时: share=%s timeout=%.0fs",
                    share.get("share_id") or share.get("shorturl") or "",
                    _BAIDU_PREVIEW_ITEM_TIMEOUT_SECONDS,
                )
                detail = {
                    "warning": f"百度分享接口超过 {_BAIDU_PREVIEW_ITEM_TIMEOUT_SECONDS:.0f} 秒未响应，已跳过该链接；稍后重试或重新绑定百度登录态",
                }
            except Exception as exc:
                logger.info("百度网盘分享预览详情读取失败: %s", exc)
                detail = {"warning": f"未能读取分享文件列表: {self._share_preview_warning(exc)}"}
            return self._preview_item_from_share(share, target_subdir, output_folder_name, detail)

        semaphore = asyncio.Semaphore(_BAIDU_PREVIEW_MAX_CONCURRENCY)

        async def resolve_share(index: int, share: Dict[str, str]) -> tuple[int, Dict[str, Any]]:
            async with semaphore:
                return index, await build_preview_item(share)

        tasks = [
            asyncio.create_task(resolve_share(index, share))
            for index, share in enumerate(shares)
        ]
        items: List[Optional[Dict[str, Any]]] = [None] * len(shares)
        done, pending = await asyncio.wait(
            tasks,
            timeout=_BAIDU_PREVIEW_TOTAL_TIMEOUT_SECONDS,
            return_when=asyncio.ALL_COMPLETED,
        )
        for task in done:
            try:
                index, item = task.result()
                items[index] = item
            except Exception as exc:
                logger.info("百度网盘分享预览任务失败: %s", exc)
        if pending:
            logger.info(
                "百度网盘分享预览达到总超时，跳过剩余链接: pending=%s total_timeout=%.0fs",
                len(pending),
                _BAIDU_PREVIEW_TOTAL_TIMEOUT_SECONDS,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        for index, item in enumerate(items):
            if item is None:
                share = shares[index]
                timeout_detail = {
                    "warning": f"百度网盘预览超过 {_BAIDU_PREVIEW_TOTAL_TIMEOUT_SECONDS:.0f} 秒总预算，已跳过该链接；稍后重试或重新绑定百度登录态",
                }
                items[index] = self._preview_item_from_share(share, target_subdir, output_folder_name, timeout_detail)
        resolved_items = [item for item in items if isinstance(item, dict)]
        ok_count = sum(1 for item in resolved_items if item.get("ok"))
        cache_key = self.raw_preview_cache_key(
            urls,
            target_subdir=target_subdir,
            conflict_policy=conflict_policy,
            output_folder_name=output_folder_name,
        )
        preview = {
            "success": ok_count > 0,
            "source": BAIDU_NETDISK_PLATFORM,
            "source_label": BAIDU_NETDISK_LABEL,
            "download_mode": BAIDU_NETDISK_PLATFORM,
            "items": resolved_items,
            "source_items": list(resolved_items),
            "selected_keys": [item["selection_key"] for item in resolved_items if item.get("ok")],
            "ok_count": ok_count,
            "failed_count": len(resolved_items) - ok_count,
            "needs_pass_code_count": len([item for item in resolved_items if item.get("requires_pass_code")]),
            "svip_speed": self._is_svip(),
            "download_root": self._download_root(),
            "target_subdir": target_subdir,
            "output_folder_name": output_folder_name,
            "conflict_policy": conflict_policy or str(getattr(self._config(), "conflict_policy", "resume") or "resume"),
            "raw_preview_cache_key": cache_key,
        }
        self._cache_raw_preview(cache_key, preview)
        return preview

    async def _fetch_share_page_tokens_compat(
        self,
        feature: str,
        cookie: str,
        *,
        referer: str = "",
        timeout: float = 20,
    ) -> Dict[str, Any]:
        try:
            return await self._fetch_share_page_tokens(
                feature,
                cookie,
                referer=referer,
                timeout=timeout,
            )
        except TypeError as exc:
            if "timeout" not in str(exc):
                raise
            return await self._fetch_share_page_tokens(
                feature,
                cookie,
                referer=referer,
            )

    async def _fetch_share_detail(self, share: Dict[str, str], *, request_timeout: float = 20) -> Dict[str, Any]:
        cookie = str(getattr(self._config(), "cookie", "") or "").strip()
        if not cookie or cookie == "********":
            raise BaiduNetdiskError("百度账号未登录，无法读取分享文件列表")
        feature = self._share_feature_str(share)
        if not feature:
            raise BaiduNetdiskError("分享链接缺少 shorturl")
        if not feature.startswith("1"):
            feature = f"1{feature}"
        if not re.fullmatch(r"1[A-Za-z0-9_-]{6,32}", feature):
            raise BaiduNetdiskError("分享链接 shorturl 格式异常")
        pass_code = str(share.get("pass_code") or "").strip()
        share_url = f"https://pan.baidu.com/s/{feature}"
        init_url = self._share_init_url(feature)
        tokens = await self._fetch_share_page_tokens_compat(
            feature,
            cookie,
            referer="https://pan.baidu.com/disk/home",
            timeout=request_timeout,
        )
        if pass_code:
            verify_data = await self._verify_share_pass_code(
                feature,
                pass_code,
                tokens,
                cookie,
                share_url,
                timeout=request_timeout,
            )
            verify_errno = _safe_int(verify_data.get("errno", verify_data.get("err_no", 0)), 0)
            if verify_errno:
                raw_verify_message = (
                    verify_data.get("errmsg")
                    or verify_data.get("show_msg")
                    or verify_data.get("error_msg")
                    or f"提取码验证失败 {verify_errno}"
                )
                verify_warning = self._share_preview_warning(
                    raw_verify_message
                )
                pass_code_invalid = self._share_verify_error_is_pass_code_invalid(verify_errno, raw_verify_message)
                if pass_code_invalid:
                    verify_warning = "提取码错误，请重新输入"
                if verify_warning == "需要输入提取码":
                    verify_warning = "提取码验证失败，请确认提取码是否正确"
                return {
                    "title": share.get("title") or "百度网盘分享",
                    "files": [],
                    "file_count": 0,
                    "folder_count": 0,
                    "total_size": 0,
                    "requires_pass_code": pass_code_invalid,
                    "pass_code_invalid": pass_code_invalid,
                    "warning": verify_warning,
                }
            randsk = str(verify_data.get("randsk") or "").strip()
            if randsk:
                cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
                tokens["randsk"] = randsk
                self._persist_cookie_patch({"BDCLND": randsk})
            refreshed_tokens = await self._fetch_share_page_tokens_compat(
                feature,
                cookie,
                referer=init_url,
                timeout=request_timeout,
            )
            refreshed_tokens["randsk"] = randsk or str(tokens.get("randsk") or "").strip()
            tokens = refreshed_tokens
        share_list_referer = init_url if pass_code else share_url
        data = await self._fetch_share_list_payload(
            tokens,
            cookie,
            share_list_referer,
            feature,
            timeout=request_timeout,
        )
        errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
        if errno:
            warning = self._share_preview_warning(data.get("errmsg") or data.get("error_msg") or data.get("show_msg") or f"分享列表读取失败 {errno}")
            return {
                "title": share.get("title") or "百度网盘分享",
                "files": [],
                "file_count": 0,
                "folder_count": 0,
                "total_size": 0,
                "requires_pass_code": bool(not pass_code and self._warning_indicates_pass_code(warning)),
                "warning": warning,
            }
        files = self._normalize_share_file_list(list(data.get("list") or []))
        if not files:
            return {
                "title": share.get("title") or "百度网盘分享",
                "files": [],
                "file_count": 0,
                "folder_count": 0,
                "total_size": 0,
                "requires_pass_code": False,
                "warning": "分享文件列表为空",
            }
        title = files[0].get("name") or share.get("title") or "百度网盘分享"
        preview_files = files
        preview_root_is_folder = False
        if len(files) == 1 and files[0].get("is_dir") and files[0].get("path"):
            preview_root_is_folder = True
            try:
                child_detail = await self._fetch_share_folder_preview(
                    tokens,
                    cookie,
                    share_list_referer,
                    feature,
                    files[0],
                    timeout=request_timeout,
                )
                if child_detail.get("files"):
                    preview_files = child_detail["files"]
            except Exception as exc:
                logger.info("百度网盘分享文件夹预览读取失败: %s", exc)
        else:
            preview_files = self._strip_virtual_common_parent_from_preview_files(preview_files)
        total_size = sum(_safe_int(item.get("size_bytes")) for item in preview_files)
        return {
            "title": title,
            "files": preview_files,
            "file_count": len(preview_files),
            "folder_count": len([item for item in preview_files if item.get("is_dir")]),
            "total_size": total_size,
            "requires_pass_code": False,
            "share_id": str(tokens.get("shareid") or tokens.get("share_id") or "").strip(),
            "share_uk": str(tokens.get("share_uk") or tokens.get("uk") or "").strip(),
            "bdstoken": str(tokens.get("bdstoken") or "").strip(),
            "randsk": str(tokens.get("randsk") or "").strip() or self._cookie_value(cookie, "BDCLND"),
            "shorturl": feature,
            "share_sign": str(tokens.get("sign") or "").strip(),
            "share_timestamp": str(tokens.get("timestamp") or "").strip(),
            "preview_root_is_folder": preview_root_is_folder,
        }

    def _strip_virtual_common_parent_from_preview_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        non_dirs = [item for item in files if isinstance(item, dict) and not item.get("is_dir")]
        if len(non_dirs) <= 1:
            return files
        split_paths = []
        for item in non_dirs:
            parts = [
                part.strip()
                for part in str(item.get("relative_path") or item.get("name") or "").replace("\\", "/").strip("/").split("/")
                if part.strip()
            ]
            if len(parts) <= 1:
                return files
            split_paths.append(parts)
        common_parent = split_paths[0][0]
        if not common_parent or any(parts[0] != common_parent for parts in split_paths):
            return files
        for item in files:
            if not isinstance(item, dict):
                continue
            parts = [
                part.strip()
                for part in str(item.get("relative_path") or item.get("name") or "").replace("\\", "/").strip("/").split("/")
                if part.strip()
            ]
            if parts and parts[0] != common_parent:
                return files
        root_dir_exists = any(
            isinstance(item, dict)
            and item.get("is_dir")
            and str(item.get("relative_path") or item.get("name") or "").replace("\\", "/").strip("/") == common_parent
            for item in files
        )
        if root_dir_exists:
            return files
        stripped: List[Dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            raw_path = str(next_item.get("relative_path") or next_item.get("name") or "").replace("\\", "/").strip("/")
            parts = [part for part in raw_path.split("/") if part]
            if len(parts) > 1 and parts[0] == common_parent:
                next_item["relative_path"] = "/".join(parts[1:])
            stripped.append(next_item)
        return stripped

    async def _verify_share_pass_code(
        self,
        feature: str,
        pass_code: str,
        tokens: Dict[str, Any],
        cookie: str,
        referer: str,
        *,
        timeout: float = 20,
    ) -> Dict[str, Any]:
        shareid = str(tokens.get("shareid") or tokens.get("share_id") or "").strip()
        share_uk = str(tokens.get("share_uk") or "").strip()
        bdstoken = str(tokens.get("bdstoken") or "").strip()
        feature_surl = feature[1:] if str(feature or "").startswith("1") else str(feature or "").strip()
        query_variants: List[tuple[Dict[str, Any], Dict[str, str], str]] = []
        if feature_surl:
            query_variants.append((
                {
                    "t": str(int(time.time() * 1000)),
                    "surl": feature_surl,
                    "channel": "chunlei",
                    "web": "1",
                    "app_id": "250528",
                    "bdstoken": bdstoken,
                    "logid": self._make_web_logid(cookie),
                    "clienttype": "0",
                    "dp-logid": self._make_dp_logid(),
                },
                {"pwd": pass_code, "vcode": "", "vcode_str": ""},
                self._share_init_url(feature),
            ))
        if shareid and share_uk:
            query_variants.append((
                {
                    "shareid": shareid,
                    "time": str(int(time.time() * 1000)),
                    "clienttype": "1",
                    "uk": share_uk,
                },
                {
                    "pwd": pass_code,
                    "vcode": "null",
                    "vcode_str": "null",
                    "bdstoken": bdstoken,
                },
                referer,
            ))
        last_data: Dict[str, Any] = {}
        for query_payload, form_data, request_referer in query_variants:
            verify_query = urlencode({key: value for key, value in query_payload.items() if value != ""})
            data = await self._fetch_form_json(
                f"https://pan.baidu.com/share/verify?{verify_query}",
                cookie,
                data=form_data,
                referer=request_referer,
                timeout=timeout,
                use_requests=True,
            )
            last_data = data
            errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
            if not errno:
                return data
            if errno in {-62, -63, -19}:
                return {
                    **data,
                    "errmsg": data.get("errmsg") or data.get("show_msg") or "百度分享验证触发验证码，请在浏览器打开分享链接完成验证后重试",
                }
            if errno not in {9019}:
                return data
        return last_data or {"errno": 9019, "errmsg": "params error"}

    async def _fetch_share_folder_preview(
        self,
        tokens: Dict[str, Any],
        cookie: str,
        share_url: str,
        feature: str,
        folder: Dict[str, Any],
        *,
        timeout: float = 20,
    ) -> Dict[str, Any]:
        folder_path = str(folder.get("path") or "").strip()
        folder_name = str(folder.get("name") or "").strip()
        if not folder_path:
            return {"files": []}
        data = await self._fetch_share_list_payload(
            tokens,
            cookie,
            share_url,
            feature,
            dir_path=folder_path,
            root=False,
            timeout=timeout,
        )
        errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
        if errno:
            logger.info("百度网盘分享文件夹预览读取失败: %s", data.get("errmsg") or data.get("error_msg") or errno)
            return {"files": []}
        return {
            "files": self._normalize_share_file_list(
                list(data.get("list") or []),
                parent_relative_path=folder_name,
            ),
        }

    def _make_share_logid(self, feature: str, cookie: str) -> str:
        source = "|".join([
            feature,
            str(int(time.time() * 1000)),
            str(self._config().account_uk or ""),
            str(hashlib.sha1(str(cookie or "").encode("utf-8", errors="ignore")).hexdigest()[:12]),
        ])
        return base64.b64encode(source.encode("utf-8", errors="ignore")).decode("ascii").rstrip("=")

    def _make_web_logid(self, cookie: str) -> str:
        baiduid = self._cookie_value(cookie, "BAIDUID") or self._cookie_value(cookie, "BAIDUID_BFESS")
        return base64.b64encode(str(baiduid or "").encode("utf-8", errors="ignore")).decode("ascii")

    def _make_dp_logid(self) -> str:
        return f"{secrets.randbelow(9_000_000_000_000_000_000) + 1_000_000_000_000_000_000}{secrets.randbelow(100):02d}"

    def _share_init_url(self, feature: str) -> str:
        text = str(feature or "").strip()
        surl = text[1:] if text.startswith("1") else text
        return f"https://pan.baidu.com/share/init?surl={quote(surl)}"

    async def _fetch_share_list_payload(
        self,
        tokens: Dict[str, Any],
        cookie: str,
        share_url: str,
        feature: str,
        *,
        dir_path: str = "/",
        root: bool = True,
        timeout: float = 20,
    ) -> Dict[str, Any]:
        share_uk = str(tokens.get("share_uk") or tokens.get("uk") or "").strip()
        shareid = str(tokens.get("shareid") or tokens.get("share_id") or "").strip()
        randsk = str(tokens.get("randsk") or "").strip() or self._cookie_value(cookie, "BDCLND")
        feature_surl = feature[1:] if str(feature or "").startswith("1") else str(feature or "").strip()
        if root:
            query_payload = {
                "web": "5",
                "app_id": "250528",
                "desc": "1",
                "showempty": "0",
                "page": "1",
                "num": "100",
                "order": "time",
                "shorturl": feature_surl,
                "root": "1",
                "view_mode": "1",
                "channel": "chunlei",
                "bdstoken": tokens.get("bdstoken") or "",
                "logid": self._make_web_logid(cookie),
                "clienttype": "0",
                "dp-logid": self._make_dp_logid(),
            }
        else:
            query_payload = {
                "bdstoken": tokens.get("bdstoken") or "",
                "logid": self._make_share_logid(feature, cookie),
                "t": str(int(time.time() * 1000)),
                "channel": "chunlei",
                "clienttype": "0",
                "web": "1",
                "app_id": "250528",
                "uk": share_uk,
                "shareid": shareid,
                "sekey": self._baidu_share_sekey(randsk),
                "shorturl": feature_surl,
                "page": "1",
                "num": "100",
                "dir": str(dir_path or "/"),
                "root": "0",
                "order": "other",
                "desc": "1",
                "showempty": "0",
            }
        query = urlencode({key: value for key, value in query_payload.items() if value != ""})
        list_url = f"https://pan.baidu.com/share/list?{query}"
        referers = []
        for candidate in (
            share_url,
            self._share_init_url(feature),
            f"https://pan.baidu.com/s/{feature}",
            "https://pan.baidu.com/disk/home",
        ):
            clean = str(candidate or "").strip()
            if clean and clean not in referers:
                referers.append(clean)
        last_error = ""
        for referer in referers:
            try:
                return await self._fetch_json(list_url, cookie, timeout=timeout, referer=referer, use_requests=True)
            except Exception as exc:
                last_error = str(exc)
                logger.debug("百度分享文件列表接口失败 referer=%s error=%s", referer, exc)
        if root:
            page_rows = self._extract_share_page_file_rows(tokens.get("_page_payload"))
            if page_rows:
                logger.info("百度分享文件列表接口失败，已从分享页内嵌数据恢复 %s 项", len(page_rows))
                return {"errno": 0, "list": page_rows, "_source": "share_page_payload"}
        raise BaiduNetdiskError(f"分享文件列表读取失败: {last_error or '接口无响应'}")

    def _cookie_value(self, cookie: str, name: str) -> str:
        target = str(name or "").strip()
        if not target:
            return ""
        for part in str(cookie or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            if key.strip() == target:
                return value.strip()
        return ""

    def _normalize_share_file_list(self, rows: List[Any], parent_relative_path: str = "") -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        parent = str(parent_relative_path or "").strip().strip("/\\")
        for index, row in enumerate(rows or []):
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or row.get("server_filename") or "").strip()
            name = str(row.get("server_filename") or os.path.basename(path.rstrip("/")) or f"分享内容 {index + 1}").strip()
            is_dir = bool(_safe_int(row.get("isdir") or row.get("is_dir") or row.get("is_directory")))
            size = 0 if is_dir else _safe_int(row.get("size") or row.get("size_bytes"))
            relative_path = "/".join(part for part in [parent, name] if part)
            files.append({
                "name": name,
                "path": path,
                "relative_path": relative_path or name,
                "size_bytes": size,
                "size": size,
                "is_dir": is_dir,
                "type": "dir" if is_dir else "file",
                "fs_id": str(row.get("fs_id") or row.get("fsid") or "").strip(),
            })
        return files

    def _is_svip(self) -> bool:
        cfg = self._config()
        vip_type = _safe_int(getattr(cfg, "vip_type", 0))
        vip_label = str(getattr(cfg, "vip_label", "") or "").lower()
        return vip_type >= 2 or "svip" in vip_label or "超级" in vip_label

    async def health(self) -> Dict[str, Any]:
        ready = self._has_baidu_login_cookie()
        result = {
            "enabled": bool(getattr(self._config(), "enabled", False) and ready),
            "engine": "baidu_share_direct",
            "config_dir": self._config_dir(),
            "download_root": self._download_root(),
            "ok": ready,
            "message": "百度登录态可用" if ready else "百度账号登录态缺少 BDUSS，请重新扫码或重新绑定 Cookie",
            "account": self.account_status(),
            "svip_speed": self._is_svip(),
        }
        return result

    def account_status(self) -> Dict[str, Any]:
        cfg = self._config()
        ready = self._has_baidu_login_cookie()
        quota = max(0, _safe_int(getattr(cfg, "quota_bytes", 0)))
        used = max(0, _safe_int(getattr(cfg, "used_bytes", 0)))
        remaining = max(0, quota - used) if quota else 0
        vip_type = _safe_int(getattr(cfg, "vip_type", 0))
        vip_label = str(getattr(cfg, "vip_label", "") or "").strip()
        if not vip_label:
            vip_label = "SVIP" if vip_type >= 2 else ("VIP" if vip_type == 1 else "普通账号")
        return {
            "enabled": bool(getattr(cfg, "enabled", False) and ready),
            "configured": ready,
            "ready": ready,
            "login_cookie_valid": ready,
            "name": str(getattr(cfg, "account_name", "") or "").strip(),
            "netdisk_name": str(getattr(cfg, "account_netdisk_name", "") or "").strip(),
            "avatar_url": str(getattr(cfg, "account_avatar_url", "") or "").strip(),
            "uk": str(getattr(cfg, "account_uk", "") or "").strip(),
            "vip_type": vip_type,
            "vip_label": vip_label,
            "vip_level": str(getattr(cfg, "vip_level", "") or "").strip(),
            "vip_expire_at": _safe_int(getattr(cfg, "vip_expire_at", 0)),
            "is_svip": self._is_svip(),
            "quota_bytes": quota,
            "used_bytes": used,
            "remaining_bytes": remaining,
            "cached_at": _safe_int(getattr(cfg, "account_cached_at", 0)),
        }

    def official_login_status(self) -> Dict[str, Any]:
        session = self._official_login_session or {}
        proc = session.get("process")
        active = bool(session)
        if active and proc is not None and proc.poll() is not None:
            self._official_login_session = None
            session = {}
            active = False
        return {
            "active": active,
            "browser": str(session.get("browser_name") or "").strip(),
            "browser_path": str(session.get("browser_path") or "").strip(),
            "profile_dir": str(session.get("profile_dir") or "").strip(),
            "started_at": _safe_int(session.get("started_at")),
            "login_url": BAIDU_OFFICIAL_LOGIN_URL if active else "",
        }

    async def start_official_login_session(self) -> Dict[str, Any]:
        """启动隔离浏览器 Profile，让用户在百度官方页面完成登录。"""
        await self.close_official_login_session()
        display_error = self._official_login_display_error()
        if display_error:
            raise BaiduNetdiskError(display_error)
        browser = self._find_official_login_browser()
        port = self._allocate_local_port()
        profile_dir = self._official_login_profile_dir()
        os.makedirs(profile_dir, exist_ok=True)
        command = [
            browser["path"],
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--new-window",
            "--window-size=520,720",
            "--window-position=120,80",
            f"--app={BAIDU_OFFICIAL_LOGIN_URL}",
        ]
        if os.name != "nt" and self._is_container_runtime():
            command.extend(["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as exc:
            raise BaiduNetdiskError(f"无法启动百度官方登录窗口: {exc}") from exc

        self._official_login_session = {
            "process": proc,
            "port": port,
            "profile_dir": profile_dir,
            "browser_name": browser["name"],
            "browser_path": browser["path"],
            "started_at": int(time.time()),
        }
        try:
            await self._wait_devtools_ready(port)
        except Exception as exc:
            await self.close_official_login_session()
            raise BaiduNetdiskError(f"百度官方登录窗口已启动，但 DevTools 通道未就绪: {exc}") from exc

        return {
            "success": True,
            "message": "已打开百度官方登录窗口",
            "login_url": BAIDU_OFFICIAL_LOGIN_URL,
            "browser": browser["name"],
            "profile_dir": profile_dir,
            "started_at": self._official_login_session["started_at"],
            "official_login": self.official_login_status(),
        }

    async def complete_official_login_session(self, *, persist: bool = True) -> Dict[str, Any]:
        """从隔离官方登录窗口同步百度账号登录态。"""
        session = dict(self._official_login_session or {})
        if not session:
            raise BaiduNetdiskError("没有正在进行的百度官方登录，请先打开官方登录窗口")
        proc = session.get("process")
        if proc and proc.poll() is not None:
            self._official_login_session = None
            raise BaiduNetdiskError("百度官方登录窗口已关闭，请重新打开并完成登录")
        cookie_header, cookie_names = await self._read_baidu_cookies_from_devtools(_safe_int(session.get("port")))
        result = await self.test_account(cookie_header, persist=persist, allow_quota_failure=True)
        account = dict(result.get("account") or {})
        account.update({
            "configured": True,
            "ready": True,
            "login_method": "official_browser",
        })
        result.update({
            "message": "百度官方登录已同步",
            "account": account,
            "browser": session.get("browser_name", ""),
            "profile_dir": session.get("profile_dir", ""),
            "cookie_names": cookie_names,
        })
        await self.close_official_login_session()
        result["official_login"] = self.official_login_status()
        return result

    async def close_official_login_session(self) -> Dict[str, Any]:
        session = self._official_login_session
        self._official_login_session = None
        proc = session.get("process") if isinstance(session, dict) else None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    proc.kill()
        return {"success": True, "message": "百度官方登录窗口已关闭"}

    async def start_qr_login_session(self) -> Dict[str, Any]:
        """创建百度 Passport 扫码登录会话，适配 Docker / 群晖无 GUI 部署。"""
        self._cleanup_qr_login_sessions()
        payload, cookie_header = await self._fetch_baidu_qr_login_payload()
        errno = _safe_int(payload.get("errno"), -1)
        if errno != 0:
            raise BaiduNetdiskError(str(payload.get("errmsg") or payload.get("error_msg") or payload))
        sign = str(payload.get("sign") or "").strip()
        image_url = self._normalize_baidu_qr_image_url(str(payload.get("imgurl") or "").strip())
        if not sign or not image_url:
            raise BaiduNetdiskError(f"百度扫码登录二维码响应缺少 sign/imgurl: {payload}")

        session_id = uuid.uuid4().hex
        now = int(time.time())
        session = {
            "session_id": session_id,
            "sign": sign,
            "image_url": image_url,
            "cookie": cookie_header,
            "gid": self._baidu_qr_gid(),
            "callback": f"tangram_guid_{self._timestamp_ms() + 1}",
            "created_at": now,
            "expires_at": now + BAIDU_QR_LOGIN_TTL_SECONDS,
            "status": "waiting",
            "message": "请使用百度网盘 App 扫码登录",
        }
        self._qr_login_sessions[session_id] = session
        return {
            "success": True,
            "message": "百度扫码登录二维码已生成",
            "qr_login": self._public_qr_login_status(session),
        }

    async def poll_qr_login_session(self, session_id: str, *, persist: bool = True) -> Dict[str, Any]:
        """轮询百度扫码登录状态；确认后换取 Web Cookie 并保存账号。"""
        self._cleanup_qr_login_sessions()
        session = self._qr_login_sessions.get(str(session_id or "").strip())
        if not session:
            return {
                "success": False,
                "message": "百度扫码登录已过期，请重新生成二维码",
                "qr_login": {
                    "active": False,
                    "status": "expired",
                    "message": "二维码已过期，请重新生成",
                },
            }
        if int(time.time()) >= _safe_int(session.get("expires_at")):
            session["status"] = "expired"
            session["message"] = "二维码已过期，请重新生成"
            self._qr_login_sessions.pop(str(session.get("session_id") or ""), None)
            return {"success": False, "message": session["message"], "qr_login": self._public_qr_login_status(session)}

        try:
            payload = await self._poll_baidu_qr_login_payload(session)
        except asyncio.TimeoutError:
            self._set_qr_login_status(session, "waiting", "等待扫码确认")
            return {"success": True, "message": session["message"], "qr_login": self._public_qr_login_status(session)}
        except Exception as exc:
            text = str(exc)
            if "Timeout" in text or "timed out" in text:
                self._set_qr_login_status(session, "waiting", "等待扫码确认")
                return {"success": True, "message": session["message"], "qr_login": self._public_qr_login_status(session)}
            raise

        channel_v = self._extract_qr_channel_value(payload)
        if channel_v:
            cookie_header, cookie_names = await self._complete_baidu_qr_login(session, channel_v)
            result = await self.test_account(cookie_header, persist=persist, allow_quota_failure=True)
            account = dict(result.get("account") or {})
            account.update({
                "configured": True,
                "ready": True,
                "login_method": "qr_login",
            })
            session["status"] = "completed"
            session["message"] = "百度扫码登录已同步"
            self._qr_login_sessions.pop(str(session.get("session_id") or ""), None)
            result.update({
                "message": "百度扫码登录已同步",
                "account": account,
                "cookie_names": cookie_names,
                "qr_login": self._public_qr_login_status(session),
            })
            return result

        status, message = self._normalize_qr_login_poll_status(payload)
        self._set_qr_login_status(session, status, message)
        if status in {"expired", "failed", "cancelled"}:
            self._qr_login_sessions.pop(str(session.get("session_id") or ""), None)
        return {"success": True, "message": session["message"], "qr_login": self._public_qr_login_status(session)}

    def close_qr_login_session(self, session_id: str = "") -> Dict[str, Any]:
        key = str(session_id or "").strip()
        if key:
            self._qr_login_sessions.pop(key, None)
        else:
            self._qr_login_sessions.clear()
        return {"success": True, "message": "百度扫码登录已关闭", "qr_login": {"active": False, "status": "closed"}}

    async def login_with_password(self, username: str, password: str, *, persist: bool = True) -> Dict[str, Any]:
        """通过 BaiduPCS-Go 的账号密码登录拿到 Cookie；二次验证场景交给扫码登录。"""
        login_name = str(username or "").strip()
        login_password = str(password or "")
        if not login_name:
            raise BaiduNetdiskError("百度账号不能为空")
        if not login_password:
            raise BaiduNetdiskError("百度账号密码不能为空")

        pcsgo_path = self._resolve_baidu_pcs_go_path()
        work_root = os.path.join(str(get_config().storage.temp_path or tempfile.gettempdir()), "baidu_netdisk_login")
        os.makedirs(work_root, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="pcsgo_login_", dir=work_root)
        config_dir = os.path.join(work_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        env = os.environ.copy()
        env["BAIDUPCS_GO_CONFIG_DIR"] = config_dir
        try:
            returncode, output = await self._run_baidu_pcs_go_login_command(
                [
                    pcsgo_path,
                    "login",
                    f"--username={login_name}",
                    f"--password={login_password}",
                ],
                env=env,
                timeout=75,
            )
            cookie_header, cookie_names = self._cookie_header_from_pcsgo_config(config_dir)
            if not cookie_header:
                raise BaiduNetdiskError(self._baidu_password_login_error(output, returncode))
            result = await self.test_account(cookie_header, persist=persist, allow_quota_failure=True)
            account = dict(result.get("account") or {})
            account.update({
                "configured": True,
                "ready": True,
                "login_method": "password",
            })
            result.update({
                "message": "百度账号密码登录已同步",
                "account": account,
                "cookie_names": cookie_names,
            })
            return result
        finally:
            with contextlib.suppress(Exception):
                shutil.rmtree(work_dir, ignore_errors=True)

    def _cleanup_qr_login_sessions(self) -> None:
        now = int(time.time())
        expired = [
            key for key, session in self._qr_login_sessions.items()
            if now >= _safe_int(session.get("expires_at"))
        ]
        for key in expired:
            self._qr_login_sessions.pop(key, None)

    def _public_qr_login_status(self, session: Dict[str, Any]) -> Dict[str, Any]:
        status = str(session.get("status") or "").strip() or "waiting"
        active = status not in {"completed", "expired", "failed", "cancelled", "closed"}
        return {
            "active": active,
            "session_id": str(session.get("session_id") or "").strip() if active else "",
            "status": status,
            "message": str(session.get("message") or "").strip(),
            "image_url": str(session.get("image_url") or "").strip() if active else "",
            "created_at": _safe_int(session.get("created_at")),
            "expires_at": _safe_int(session.get("expires_at")),
        }

    def _set_qr_login_status(self, session: Dict[str, Any], status: str, message: str) -> None:
        """扫码状态只允许向前走，避免百度长轮询偶发 waiting 覆盖已扫码状态。"""
        current = str(session.get("status") or "").strip() or "waiting"
        next_status = str(status or "").strip() or "waiting"
        rank = {
            "waiting": 0,
            "scanned": 1,
            "confirmed": 2,
            "completed": 3,
            "expired": 9,
            "failed": 9,
            "cancelled": 9,
            "closed": 9,
        }
        if rank.get(next_status, 0) < rank.get(current, 0):
            return
        session["status"] = next_status
        session["message"] = str(message or "").strip()

    def _baidu_qr_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": _BAIDU_WEB_USER_AGENT,
            "Accept": "application/json,text/javascript,*/*;q=0.01",
            "Referer": "https://passport.baidu.com/v2/?login",
        }

    async def _fetch_baidu_qr_login_payload(self) -> tuple[Dict[str, Any], str]:
        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        async with aiohttp.ClientSession(timeout=timeout, headers=self._baidu_qr_headers()) as session:
            params = {
                "lp": "pc",
                "qrloginfrom": "pc",
                "tpl": "netdisk",
                "apiver": "v3",
                "tt": self._timestamp_ms(),
            }
            async with session.get(BAIDU_QR_GET_URL, params=params) as response:
                body = await response.text()
                if response.status >= 400:
                    raise BaiduNetdiskError(f"百度二维码接口返回 HTTP {response.status}")
                cookie_header = self._cookies_from_response(response)
        return self._parse_baidu_json_payload(body), cookie_header

    async def _poll_baidu_qr_login_payload(self, session: Dict[str, Any]) -> Dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=40, connect=5, sock_read=38)
        headers = self._baidu_qr_headers()
        cookie_header = str(session.get("cookie") or "").strip()
        if cookie_header:
            headers["Cookie"] = cookie_header
        callback = str(session.get("callback") or "").strip() or f"tangram_guid_{self._timestamp_ms() + 1}"
        params = {
            "channel_id": str(session.get("sign") or ""),
            "tpl": "netdisk",
            "gid": str(session.get("gid") or "").strip() or self._baidu_qr_gid(),
            "apiver": "v3",
            "callback": callback,
            "tt": self._timestamp_ms(),
            "_": self._timestamp_ms() + 2,
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
            async with client.get(BAIDU_QR_UNICAST_URL, params=params) as response:
                body = await response.text()
                if response.status >= 400:
                    raise BaiduNetdiskError(f"百度扫码状态接口返回 HTTP {response.status}")
                merged_cookie = self._merge_cookie_header(cookie_header, self._cookies_from_response(response, as_dict=True))
                if merged_cookie:
                    session["cookie"] = merged_cookie
        return self._parse_baidu_json_payload(body)

    async def _complete_baidu_qr_login(self, session: Dict[str, Any], bduss_token: str) -> tuple[str, List[str]]:
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        headers = self._baidu_qr_headers()
        cookie_header = str(session.get("cookie") or "").strip()
        if cookie_header:
            headers["Cookie"] = cookie_header
        now_ms = self._timestamp_ms()
        callback = f"bd__cbs__{uuid.uuid4().hex[:10]}"
        params = {
            "bduss": str(bduss_token or "").strip(),
            "u": "https://pan.baidu.com/",
            "tpl": "netdisk",
            "apiver": "v3",
            "loginVersion": "v4",
            "qrcode": "1",
            "time": now_ms // 1000,
            "tt": now_ms,
            "v": now_ms,
            "callback": callback,
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
            async with client.get(BAIDU_QR_BDUSS_LOGIN_URL, params=params, allow_redirects=False) as response:
                await response.text()
                cookie_header = self._merge_cookie_header(cookie_header, self._cookies_from_response(response, as_dict=True))
                if response.status >= 400:
                    raise BaiduNetdiskError(f"百度扫码登录换取 Cookie 返回 HTTP {response.status}")
        if not (self._cookie_value(cookie_header, "BDUSS") or self._cookie_value(cookie_header, "BDUSS_BFESS")):
            raise BaiduNetdiskError("百度扫码已确认，但未返回 BDUSS 登录态")
        cookie_names = [
            name for name in _BAIDU_COOKIE_PRIORITY if self._cookie_value(cookie_header, name)
        ]
        return cookie_header, cookie_names

    def _normalize_baidu_qr_image_url(self, value: str) -> str:
        text = str(value or "").replace("\\/", "/").strip()
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith("http://") or text.startswith("https://"):
            return text
        if text:
            return f"https://{text.lstrip('/')}"
        return ""

    def _parse_baidu_json_payload(self, body: str) -> Dict[str, Any]:
        text = str(body or "").strip()
        if not text:
            return {}
        if text.startswith("{") and text.endswith("}"):
            return self._decode_baidu_json_object(text)
        match = re.search(r"\((\{.*\})\)\s*;?\s*$", text, re.S)
        if match:
            return self._decode_baidu_json_object(match.group(1))
        match = re.search(r"(\{.*\})", text, re.S)
        if match:
            return self._decode_baidu_json_object(match.group(1))
        raise BaiduNetdiskError(f"无法解析百度接口响应: {text[:160]}")

    def _decode_baidu_json_object(self, text: str) -> Dict[str, Any]:
        normalized = str(text or "").replace("\\/", "/")
        data = json.loads(normalized)
        if not isinstance(data, dict):
            raise BaiduNetdiskError("百度接口响应不是 JSON 对象")
        channel_v = data.get("channel_v")
        if isinstance(channel_v, str) and channel_v.strip():
            with contextlib.suppress(Exception):
                data["channel_v"] = json.loads(channel_v)
        return data

    def _extract_qr_channel_value(self, payload: Dict[str, Any]) -> str:
        channel = payload.get("channel_v")
        if isinstance(channel, dict):
            if _safe_int(channel.get("status"), 1) == 0:
                return str(channel.get("v") or "").strip()
        return str(payload.get("v") or payload.get("bduss") or "").strip()

    def _normalize_qr_login_poll_status(self, payload: Dict[str, Any]) -> tuple[str, str]:
        errno = _safe_int(payload.get("errno"), 1)
        channel = payload.get("channel_v") if isinstance(payload, dict) else {}
        channel_status = _safe_int(channel.get("status"), -1) if isinstance(channel, dict) else -1
        if errno == 0 and channel_status == 1:
            return "scanned", "已扫码，等待手机确认登录"
        if errno == 0 and channel_status == 0:
            return "confirmed", "已确认登录，正在同步账号"
        if errno == 1:
            return "waiting", "等待扫码"
        if errno in {2, 3, 4, 5, 6}:
            return "expired", "二维码已过期，请重新生成"
        return "waiting", str(payload.get("errmsg") or payload.get("error_msg") or "等待扫码确认")

    def _timestamp_ms(self) -> int:
        return int(time.time() * 1000)

    def _baidu_qr_gid(self) -> str:
        return str(uuid.uuid4()).upper()

    def _cookies_from_response(self, response, *, as_dict: bool = False):
        values: Dict[str, str] = {}
        with contextlib.suppress(Exception):
            for key, morsel in response.cookies.items():
                value = getattr(morsel, "value", "")
                if key and value:
                    values[str(key)] = str(value)
        with contextlib.suppress(Exception):
            for header in response.headers.getall("Set-Cookie", []):
                jar = SimpleCookie()
                jar.load(header)
                for key, morsel in jar.items():
                    value = getattr(morsel, "value", "")
                    if key and value:
                        values[str(key)] = str(value)
        if as_dict:
            return values
        return self._merge_cookie_header("", values)

    async def test_account(self, cookie: str = "", *, persist: bool = False, allow_quota_failure: bool = False) -> Dict[str, Any]:
        cookie_value = str(cookie or "").strip() or self._configured_baidu_cookie()
        if not cookie_value:
            raise BaiduNetdiskError("百度账号登录态不能为空")
        if not self._has_baidu_login_cookie(cookie_value):
            raise BaiduNetdiskError("百度账号登录态缺少 BDUSS，请重新扫码或重新绑定 Cookie")
        account = await self._fetch_account_by_web(cookie_value)
        quota_warning = ""
        try:
            quota_payload = await self._fetch_quota_by_web(cookie_value)
            account.update(quota_payload)
        except Exception as exc:
            if not allow_quota_failure:
                raise
            quota_warning = f"容量刷新失败: {self._sanitize_error(exc)}"
            cfg = self._config()
            for key in ("quota_bytes", "used_bytes", "vip_expire_at"):
                cached_value = _safe_int(getattr(cfg, key, 0))
                if cached_value > 0 and _safe_int(account.get(key)) <= 0:
                    account[key] = cached_value
                else:
                    account.setdefault(key, cached_value)
        account["configured"] = True
        account["ready"] = True
        account["cached_at"] = int(time.time())
        if persist:
            self._persist_account(cookie_value, account)
        result = {
            "success": True,
            "message": "百度账号检测成功" if not quota_warning else f"百度账号检测成功，{quota_warning}",
            "account": account,
        }
        if quota_warning:
            result["warning"] = quota_warning
        return result

    async def refresh_account_status(self) -> Dict[str, Any]:
        """刷新账号资料；容量接口异常时保留本地容量缓存，不阻断账号刷新。"""
        result = await self.test_account("", persist=True, allow_quota_failure=True)
        if result.get("warning"):
            result["message"] = "百度账号状态已刷新，容量接口暂不可用，已保留本地容量缓存"
        else:
            result["message"] = "百度账号状态已刷新"
        result["official_login"] = self.official_login_status()
        return result

    def _is_container_runtime(self) -> bool:
        if os.path.exists("/.dockerenv"):
            return True
        with contextlib.suppress(Exception):
            cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore").lower()
            return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "podman"))
        return False

    def _official_login_display_error(self) -> str:
        if os.name == "nt":
            return ""
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return ""
        runtime = "Docker/容器" if self._is_container_runtime() else "Linux 服务"
        return (
            f"当前后端运行在{runtime}无图形界面环境，无法弹出百度官方登录窗口。"
            "请在设置页使用“扫码登录”或“手动 Cookie 绑定”；如果一定要用官方登录，"
            "需要给容器安装 Chrome/Chromium 并配置 X11/VNC。"
        )

    def _find_official_login_browser(self) -> Dict[str, str]:
        candidates: List[tuple[str, str]] = []
        if os.name == "nt":
            env = os.environ
            roots = [
                env.get("PROGRAMFILES", ""),
                env.get("PROGRAMFILES(X86)", ""),
                env.get("LOCALAPPDATA", ""),
            ]
            for root in [Path(item) for item in roots if item]:
                candidates.extend([
                    ("Google Chrome", str(root / "Google" / "Chrome" / "Application" / "chrome.exe")),
                    ("Microsoft Edge", str(root / "Microsoft" / "Edge" / "Application" / "msedge.exe")),
                    ("Chromium", str(root / "Chromium" / "Application" / "chrome.exe")),
                ])
        for name, executable in (
            ("Google Chrome", "chrome"),
            ("Google Chrome", "google-chrome"),
            ("Microsoft Edge", "msedge"),
            ("Microsoft Edge", "microsoft-edge"),
            ("Chromium", "chromium"),
            ("Chromium", "chromium-browser"),
        ):
            resolved = shutil.which(executable)
            if resolved:
                candidates.append((name, resolved))
        seen = set()
        for name, path in candidates:
            clean_path = os.path.abspath(path)
            if clean_path in seen:
                continue
            seen.add(clean_path)
            if os.path.exists(clean_path):
                return {"name": name, "path": clean_path}
        raise BaiduNetdiskError(
            "没有找到可用于官方登录的 Chrome / Edge / Chromium 浏览器。"
            "桌面环境请安装 Chrome/Edge/Chromium；Docker/群晖部署建议使用设置页的“扫码登录”。"
        )

    def _allocate_local_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def _wait_devtools_ready(self, port: int, timeout: float = 15.0) -> None:
        import aiohttp

        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                    async with session.get(f"http://127.0.0.1:{port}/json/version") as response:
                        if response.status < 400:
                            return
                        last_error = f"HTTP {response.status}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(0.25)
        raise BaiduNetdiskError(last_error or "DevTools 未响应")

    async def _read_baidu_cookies_from_devtools(self, port: int) -> tuple[str, List[str]]:
        import aiohttp

        if not port:
            raise BaiduNetdiskError("百度官方登录会话端口无效")
        timeout = aiohttp.ClientTimeout(total=8, connect=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            version = await self._devtools_json(session, port, "/json/version")
            targets = await self._devtools_json(session, port, "/json/list")

        ws_urls: List[str] = []
        for target in targets if isinstance(targets, list) else []:
            if not isinstance(target, dict):
                continue
            url = str(target.get("url") or "").lower()
            ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            if ws_url and "baidu.com" in url:
                ws_urls.append(ws_url)
        browser_ws = str(version.get("webSocketDebuggerUrl") or "").strip() if isinstance(version, dict) else ""
        if browser_ws:
            ws_urls.append(browser_ws)
        if not ws_urls:
            raise BaiduNetdiskError("没有找到百度官方登录窗口，请确认登录窗口仍在打开")

        errors: List[str] = []
        for ws_url in ws_urls:
            try:
                cookies = await self._read_devtools_cookies(ws_url)
                return self._build_cookie_header_from_devtools(cookies)
            except Exception as exc:
                errors.append(str(exc))
        raise BaiduNetdiskError("读取百度官方登录态失败: " + "；".join(errors[-3:]))

    async def _devtools_json(self, session, port: int, path: str) -> Any:
        async with session.get(f"http://127.0.0.1:{port}{path}") as response:
            body = await response.text()
            if response.status >= 400:
                raise BaiduNetdiskError(f"DevTools {path} 返回 HTTP {response.status}")
            return json.loads(body)

    async def _read_devtools_cookies(self, ws_url: str) -> List[Dict[str, Any]]:
        import websockets

        seq = 0
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            async def call(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                nonlocal seq
                seq += 1
                request_id = seq
                await ws.send(json.dumps({
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }))
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                    if message.get("id") != request_id:
                        continue
                    if message.get("error"):
                        raise BaiduNetdiskError(str(message.get("error") or {}))
                    return dict(message.get("result") or {})

            with contextlib.suppress(Exception):
                await call("Network.enable")
            last_error = ""
            for method in ("Network.getAllCookies", "Storage.getCookies"):
                try:
                    result = await call(method)
                    cookies = result.get("cookies")
                    if isinstance(cookies, list):
                        return [cookie for cookie in cookies if isinstance(cookie, dict)]
                except Exception as exc:
                    last_error = str(exc)
            raise BaiduNetdiskError(last_error or "DevTools 未返回 Cookie")

    def _build_cookie_header_from_devtools(self, cookies: List[Dict[str, Any]]) -> tuple[str, List[str]]:
        values: Dict[str, str] = {}
        for cookie in cookies or []:
            domain = str(cookie.get("domain") or "").lower()
            if "baidu.com" not in domain:
                continue
            name = str(cookie.get("name") or "").strip()
            value = str(cookie.get("value") or "").strip()
            if name and value:
                values[name] = value
        if not (values.get("BDUSS") or values.get("BDUSS_BFESS")):
            raise BaiduNetdiskError("未检测到百度登录态，请先在官方登录窗口完成登录")
        ordered_names = [
            name for name in _BAIDU_COOKIE_PRIORITY if values.get(name)
        ] + sorted(name for name in values if name not in _BAIDU_COOKIE_PRIORITY)
        return "; ".join(f"{name}={values[name]}" for name in ordered_names), ordered_names

    def unbind_account(self) -> Dict[str, Any]:
        current = get_config().model_dump()
        cfg = dict(current.get("baidu_netdisk") or {})
        for key in (
            "cookie",
            "account_name",
            "account_netdisk_name",
            "account_avatar_url",
            "account_uk",
            "vip_label",
            "vip_level",
        ):
            cfg[key] = ""
        for key in ("vip_type", "vip_expire_at", "quota_bytes", "used_bytes", "account_cached_at"):
            cfg[key] = 0
        cfg["enabled"] = False
        save_config({"baidu_netdisk": cfg})
        return {"success": True, "message": "百度账号已解绑", "account": self.account_status()}

    def _persist_account(self, cookie: str, account: Dict[str, Any]) -> None:
        current = get_config().model_dump()
        cfg = dict(current.get("baidu_netdisk") or {})
        cfg.update({
            "enabled": True,
            "cookie": cookie,
            "account_cached_at": _safe_int(account.get("cached_at") or int(time.time())),
        })
        if "name" in account or "username" in account:
            cfg["account_name"] = str(account.get("name") or account.get("username") or "").strip()
        for source_key, target_key in (
            ("netdisk_name", "account_netdisk_name"),
            ("avatar_url", "account_avatar_url"),
            ("uk", "account_uk"),
            ("vip_label", "vip_label"),
            ("vip_level", "vip_level"),
        ):
            if source_key in account:
                cfg[target_key] = str(account.get(source_key) or "").strip()
        for key in ("vip_type", "vip_expire_at", "quota_bytes", "used_bytes"):
            if key in account:
                cfg[key] = _safe_int(account.get(key))
        save_config({"baidu_netdisk": cfg})

    def _persist_cookie_patch(self, extra: Dict[str, str]) -> None:
        values = {
            key: str(value or "").strip()
            for key, value in (extra or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        }
        if not values:
            return
        try:
            config_obj = get_config()
            current = config_obj.model_dump() if hasattr(config_obj, "model_dump") else {}
        except Exception as exc:
            logger.debug("百度 Cookie 辅助字段读取配置失败: %s", exc)
            return
        cfg = dict(current.get("baidu_netdisk") or {})
        current_cookie = str(cfg.get("cookie") or "")
        if not (self._cookie_value(current_cookie, "BDUSS") or self._cookie_value(current_cookie, "BDUSS_BFESS")):
            logger.debug("百度 Cookie 辅助字段未写入：当前配置缺少 BDUSS 登录态")
            return
        cookie = self._merge_cookie_header(current_cookie, values)
        if cookie and cookie != current_cookie:
            cfg["cookie"] = cookie
            try:
                save_config({"baidu_netdisk": cfg})
            except Exception as exc:
                logger.debug("百度 Cookie 辅助字段持久化失败: %s", exc)

    def _baidu_web_api_headers(
        self,
        cookie: str,
        *,
        referer: str = "",
        content_type: str = "",
        browser_like: bool = False,
    ) -> Dict[str, str]:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
        headers = {
            "Cookie": cookie,
            "User-Agent": user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01" if browser_like else "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if referer:
            headers["Referer"] = referer
            if not browser_like:
                parsed_referer = urlparse(referer)
                if parsed_referer.scheme and parsed_referer.netloc:
                    headers["Origin"] = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        if browser_like:
            headers.update({
                "sec-ch-ua-platform": '"Windows"',
                "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not/A)Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
            })
        return headers

    async def _fetch_json(
        self,
        url: str,
        cookie: str,
        timeout: float = 20,
        referer: str = "",
        *,
        use_requests: bool = False,
    ) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            headers = self._baidu_web_api_headers(cookie, referer=referer, browser_like=use_requests)
            if use_requests:
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response.json()
            request = Request(
                url,
                headers=headers,
            )
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            return json.loads(body)

        return await asyncio.to_thread(run)

    async def _fetch_form_json(
        self,
        url: str,
        cookie: str,
        *,
        data: Optional[Dict[str, str]] = None,
        referer: str = "",
        timeout: float = 20,
        use_requests: bool = False,
    ) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            body = urlencode({key: str(value or "") for key, value in (data or {}).items()}).encode("utf-8")
            headers = self._baidu_web_api_headers(
                cookie,
                referer=referer,
                content_type="application/x-www-form-urlencoded; charset=UTF-8",
                browser_like=use_requests,
            )
            if use_requests:
                headers["Connection"] = "close"
                with requests.Session() as session:
                    response = session.post(
                        url,
                        data={key: str(value or "") for key, value in (data or {}).items()},
                        headers=headers,
                        timeout=timeout,
                    )
                    response.raise_for_status()
                    return response.json()
            request = Request(url, data=body, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                body_text = response.read().decode("utf-8", errors="replace")
            return json.loads(body_text)

        return await asyncio.to_thread(run)

    async def _fetch_share_page_tokens(
        self,
        featurestr: str,
        cookie: str,
        *,
        referer: str = "",
        timeout: float = 20,
    ) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": referer or "https://pan.baidu.com/disk/home",
                "Cookie": cookie,
            }
            if referer and "/share/init" in referer:
                headers["Referer"] = referer
            urls = []
            for candidate in (
                self._share_init_url(featurestr),
                f"https://pan.baidu.com/s/{featurestr}",
            ):
                if candidate not in urls:
                    urls.append(candidate)
            last_error = ""
            payload: Dict[str, Any] = {}
            session = requests.Session()
            for share_link in urls:
                try:
                    response = session.get(
                        share_link,
                        headers=headers,
                        timeout=timeout,
                        allow_redirects=True,
                    )
                    response.raise_for_status()
                    body = response.text
                    if "platform-non-found" in body or "error-404" in body:
                        raise BaiduNetdiskError("分享链接已失效")
                    payload = self._extract_share_page_local_payload(body)
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.debug("百度分享页参数读取失败 url=%s error=%s", share_link, exc)
            if not payload:
                raise BaiduNetdiskError(f"无法读取百度分享页登录参数: {last_error or '页面无响应'}")
            return {
                "bdstoken": str(payload.get("bdstoken") or "").strip(),
                "uk": str(payload.get("uk") or "").strip(),
                "share_uk": str(payload.get("share_uk") or "").strip(),
                "shareid": str(payload.get("shareid") or "").strip(),
                "sign": "",
                "timestamp": "",
                "_page_payload": payload,
            }

        return await asyncio.to_thread(run)

    def _extract_share_page_file_rows(self, payload: Any) -> List[Dict[str, Any]]:
        if not isinstance(payload, (dict, list)):
            return []
        rows = self._extract_file_rows_from_node(payload)
        return [
            dict(row)
            for row in rows
            if isinstance(row, dict) and self._looks_like_baidu_file_row(row)
        ]

    def _extract_file_rows_from_node(self, node: Any, depth: int = 0) -> List[Dict[str, Any]]:
        if depth > 6:
            return []
        if isinstance(node, list):
            rows = [row for row in node if isinstance(row, dict)]
            return rows if rows and any(self._looks_like_baidu_file_row(row) for row in rows) else []
        if not isinstance(node, dict):
            return []

        for key in ("file_list", "fileList", "filelist", "list", "files"):
            if key not in node:
                continue
            rows = self._extract_file_rows_from_node(node.get(key), depth + 1)
            if rows:
                return rows

        for value in node.values():
            rows = self._extract_file_rows_from_node(value, depth + 1)
            if rows:
                return rows
        return []

    def _looks_like_baidu_file_row(self, row: Dict[str, Any]) -> bool:
        keys = {str(key or "").lower() for key in row.keys()}
        return bool(keys & {"server_filename", "path", "fs_id", "fsid", "isdir", "is_dir"})

    def _extract_share_page_local_payload(self, body: str) -> Dict[str, Any]:
        text = str(body or "")
        match = re.search(r"locals\.mset\s*\(", text, re.S)
        if match:
            payload_text = self._extract_js_object_at(text, match.end())
            try:
                payload = json.loads(payload_text)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                payload = self._parse_share_page_token_fields(payload_text)
                if payload:
                    return payload
        match = re.search(r"window\.yunData\s*=", text, re.S)
        if match:
            payload = self._parse_share_page_token_fields(self._extract_js_object_at(text, match.end()))
            if payload:
                return payload
        raise BaiduNetdiskError("无法读取百度分享页登录参数")

    def _extract_js_object_at(self, text: str, start: int) -> str:
        source = str(text or "")
        brace_start = source.find("{", max(0, start))
        if brace_start < 0:
            return ""
        depth = 0
        quote_char = ""
        escaped = False
        for index in range(brace_start, len(source)):
            char = source[index]
            if quote_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    quote_char = ""
                continue
            if char in {'"', "'", "`"}:
                quote_char = char
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    return source[brace_start:index + 1]
        return ""

    def _parse_share_page_token_fields(self, payload_text: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for key in ("bdstoken", "uk", "share_uk", "shareid"):
            match = re.search(
                rf'["\']?{re.escape(key)}["\']?\s*:\s*(?:"([^"]*)"|\'([^\']*)\'|([0-9]+))',
                str(payload_text or ""),
                re.S,
            )
            if match:
                fields[key] = next((group for group in match.groups() if group is not None), "")
        if not fields:
            raise BaiduNetdiskError("无法解析百度分享页登录参数")
        return fields

    def _merge_cookie_header(self, cookie: str, extra: Dict[str, str]) -> str:
        values: Dict[str, str] = {}
        for part in str(cookie or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                values[key] = value
        for key, value in extra.items():
            if key and value is not None:
                values[str(key).strip()] = str(value).strip()
        ordered_names = [
            name for name in _BAIDU_COOKIE_PRIORITY if values.get(name)
        ] + sorted(name for name in values if name not in _BAIDU_COOKIE_PRIORITY)
        return "; ".join(f"{name}={values[name]}" for name in ordered_names if values.get(name))

    def _baidu_share_sekey(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return unquote(text)

    async def _fetch_account_by_web(self, cookie: str) -> Dict[str, Any]:
        endpoints = [
            "https://pan.baidu.com/rest/2.0/xpan/nas?method=uinfo",
            "https://pan.baidu.com/api/user/getinfo",
        ]
        last_error = ""
        for endpoint in endpoints:
            try:
                data = await self._fetch_json(endpoint, cookie)
                errno = _safe_int(data.get("errno", data.get("error_code", 0)), 0)
                if errno not in {0, 2} and data.get("error_msg"):
                    raise BaiduNetdiskError(str(data.get("error_msg") or data))
                return self._normalize_account_payload(data)
            except Exception as exc:
                last_error = str(exc)
                logger.debug("百度账号接口失败: %s %s", endpoint, exc)
        raise BaiduNetdiskError(f"百度账号检测失败: {last_error or '接口无响应'}")

    async def _fetch_quota_by_web(self, cookie: str) -> Dict[str, Any]:
        endpoints = [
            "https://pan.baidu.com/api/quota?checkfree=1&checkexpire=1",
            "https://pan.baidu.com/rest/2.0/xpan/nas?method=quota",
            "https://pan.baidu.com/api/quota?checkfree=1&checkexpire=1&web=1&app_id=250528",
            "https://pan.baidu.com/api/quota?web=1&app_id=250528",
        ]
        last_error = ""
        for endpoint in endpoints:
            try:
                data = await self._fetch_json(endpoint, cookie)
                return self._normalize_quota_payload(data)
            except Exception as exc:
                last_error = str(exc)
                logger.debug("百度容量接口失败: %s %s", endpoint, exc)
        pcsgo_error = ""
        try:
            return await self._fetch_quota_by_pcsgo(cookie)
        except Exception as exc:
            pcsgo_error = str(exc)
            logger.debug("BaiduPCS-Go 容量查询失败: %s", exc)
        detail = last_error or "接口无响应"
        if pcsgo_error:
            detail = f"{detail}；BaiduPCS-Go: {pcsgo_error}"
        raise BaiduNetdiskError(f"百度容量刷新失败: {detail}")

    def _normalize_quota_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        errno = _safe_int(data.get("errno", data.get("error_code", 0)), 0)
        if errno and errno != 2:
            raise BaiduNetdiskError(str(data.get("error_msg") or data.get("errmsg") or data))
        payload = data.get("quota") if isinstance(data.get("quota"), dict) else data
        quota = _safe_int(
            payload.get("total")
            or payload.get("quota")
            or payload.get("limit")
            or payload.get("total_bytes"),
            -1,
        )
        used = _safe_int(
            payload.get("used")
            or payload.get("usage")
            or payload.get("used_bytes"),
            -1,
        )
        if quota < 0 or used < 0:
            raise BaiduNetdiskError(f"容量接口缺少 total/used 字段: {data}")
        return {
            "quota_bytes": quota,
            "used_bytes": used,
            "vip_expire_at": _first_timestamp_field(data, [
                "vip_expire_at",
                "vip_expire_time",
                "svip_expire_at",
                "svip_expire_time",
                "member_expire_at",
                "member_expire_time",
                "expire_at",
                "expire_time",
                "expire",
            ]),
        }

    async def _fetch_quota_by_pcsgo(self, cookie: str) -> Dict[str, Any]:
        pcsgo_path = self._resolve_baidu_pcs_go_path()
        work_root = os.path.join(str(get_config().storage.temp_path or tempfile.gettempdir()), "baidu_netdisk_quota")
        os.makedirs(work_root, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="pcsgo_quota_", dir=work_root)
        config_dir = os.path.join(work_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        env = os.environ.copy()
        env["BAIDUPCS_GO_CONFIG_DIR"] = config_dir
        try:
            self._write_baidu_pcsgo_cookie_config(config_dir, cookie, workdir="/")
            returncode, quota_output = await self._run_baidu_pcs_go_login_command(
                [pcsgo_path, "quota"],
                env=env,
                timeout=30,
            )
            if returncode != 0:
                raise BaiduNetdiskError(self._sanitize_error(quota_output or f"BaiduPCS-Go quota 返回退出码 {returncode}"))
            return self._parse_pcsgo_quota_output(quota_output)
        finally:
            with contextlib.suppress(Exception):
                shutil.rmtree(work_dir, ignore_errors=True)

    def _parse_pcsgo_quota_output(self, output: str) -> Dict[str, Any]:
        text = str(output or "")
        pairs = re.findall(
            r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B|[KMGTPE]?B)",
            text,
            re.I,
        )
        sizes = [self._parse_pcsgo_size(value, unit) for value, unit in pairs]
        sizes = [size for size in sizes if size > 0]
        if len(sizes) >= 2:
            used, quota = sizes[0], sizes[1]
            if used > quota:
                quota, used = used, quota
            return {
                "quota_bytes": quota,
                "used_bytes": used,
                "vip_expire_at": 0,
            }

        total_match = re.search(r"(?:总|total|quota|limit)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B|[KMGTPE]?B)", text, re.I)
        used_match = re.search(r"(?:已用|使用|used|usage)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B|[KMGTPE]?B)", text, re.I)
        if total_match and used_match:
            return {
                "quota_bytes": self._parse_pcsgo_size(total_match.group(1), total_match.group(2)),
                "used_bytes": self._parse_pcsgo_size(used_match.group(1), used_match.group(2)),
                "vip_expire_at": 0,
            }

        raise BaiduNetdiskError(f"BaiduPCS-Go quota 输出无法解析: {self._sanitize_error(text[:300])}")

    def _normalize_account_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data.get("user_info") if isinstance(data.get("user_info"), dict) else data
        vip_type = _safe_int(payload.get("vip_type") or payload.get("member_type") or payload.get("is_vip"))
        is_svip = vip_type >= 2 or bool(payload.get("is_svip"))
        vip_label = "SVIP" if is_svip else ("VIP" if vip_type else "普通账号")
        avatar = (
            payload.get("avatar_url")
            or payload.get("avatar")
            or payload.get("photo_url")
            or payload.get("portrait")
            or ""
        )
        if avatar and str(avatar).startswith("http://"):
            avatar = "https://" + str(avatar)[7:]
        return {
            "name": str(payload.get("baidu_name") or payload.get("username") or payload.get("uname") or payload.get("name") or "").strip(),
            "netdisk_name": str(payload.get("netdisk_name") or payload.get("uk") or "").strip(),
            "avatar_url": str(avatar or "").strip(),
            "uk": str(payload.get("uk") or payload.get("bdstoken") or "").strip(),
            "vip_type": vip_type,
            "vip_label": vip_label,
            "vip_level": str(payload.get("vip_level") or payload.get("level") or "").strip(),
            "vip_expire_at": _first_timestamp_field(payload, [
                "vip_expire_at",
                "vip_expire_time",
                "svip_expire_at",
                "svip_expire_time",
                "member_expire_at",
                "member_expire_time",
                "expire_at",
                "expire_time",
                "expire",
            ]),
        }

    async def _build_download_file_rows(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        multiple_selected_shares = len(items) > 1
        for item in items:
            context = await self._share_download_context(item)
            share_files = [
                row for row in list(item.get("share_files") or item.get("preview_files") or [])
                if isinstance(row, dict)
            ]
            if not share_files:
                raise BaiduNetdiskError(f"{item.get('filename') or item.get('name') or '百度网盘分享'} 没有可下载文件")
            item_rows: List[Dict[str, Any]] = []
            for file_index, share_file in enumerate(share_files):
                if share_file.get("is_dir"):
                    expanded = await self._collect_share_folder_files(context, share_file)
                    for child_index, child in enumerate(expanded):
                        item_rows.append(self._download_row_from_share_file(
                            item,
                            child,
                            context,
                            f"{file_index}-{child_index}",
                            keep_share_root=multiple_selected_shares,
                        ))
                    continue
                item_rows.append(self._download_row_from_share_file(
                    item,
                    share_file,
                    context,
                    str(file_index),
                    keep_share_root=multiple_selected_shares,
                ))
            rows.extend(self._apply_custom_download_name_to_rows(item, item_rows))
        return [row for row in rows if str(row.get("fs_id") or "").strip()]

    async def _share_download_context(self, item: Dict[str, Any]) -> Dict[str, Any]:
        cookie = str(getattr(self._config(), "cookie", "") or "").strip()
        if not cookie or cookie == "********":
            raise BaiduNetdiskError("百度账号未登录，无法直接下载分享文件")
        randsk = str(item.get("randsk") or "").strip()
        if randsk:
            cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
        shorturl = str(item.get("shorturl") or item.get("share_id") or "").strip()
        if shorturl and not shorturl.startswith("1"):
            shorturl = f"1{shorturl}"
        share_url = str(item.get("share_url") or item.get("url") or "").strip()
        if not share_url and shorturl:
            share_url = f"https://pan.baidu.com/s/{shorturl}"
        shareid = str(item.get("share_numeric_id") or "").strip()
        if not shareid and re.fullmatch(r"\d+", str(item.get("share_id") or "")):
            shareid = str(item.get("share_id") or "").strip()
        context = {
            "cookie": cookie,
            "shorturl": shorturl,
            "share_url": share_url,
            "shareid": shareid,
            "share_uk": str(item.get("share_uk") or "").strip(),
            "bdstoken": str(item.get("bdstoken") or "").strip(),
            "randsk": randsk or self._cookie_value(cookie, "BDCLND"),
            "sign": str(item.get("share_sign") or "").strip(),
            "timestamp": str(item.get("share_timestamp") or "").strip(),
            "tokens": {
                "bdstoken": str(item.get("bdstoken") or "").strip(),
                "shareid": shareid,
                "share_uk": str(item.get("share_uk") or "").strip(),
                "randsk": randsk or self._cookie_value(cookie, "BDCLND"),
            },
        }
        if shorturl and (not context["shareid"] or not context["share_uk"]):
            tokens = await self._fetch_share_page_tokens(shorturl, cookie, referer=share_url or "https://pan.baidu.com/disk/home")
            context["shareid"] = context["shareid"] or str(tokens.get("shareid") or "").strip()
            context["share_uk"] = context["share_uk"] or str(tokens.get("share_uk") or tokens.get("uk") or "").strip()
            context["bdstoken"] = context["bdstoken"] or str(tokens.get("bdstoken") or "").strip()
            context["tokens"].update({
                "bdstoken": context["bdstoken"],
                "shareid": context["shareid"],
                "share_uk": context["share_uk"],
                "randsk": context["randsk"],
            })
        return context

    async def _collect_share_folder_files(self, context: Dict[str, Any], folder: Dict[str, Any], depth: int = 0) -> List[Dict[str, Any]]:
        if depth > 8:
            raise BaiduNetdiskError("百度网盘分享文件夹层级过深")
        folder_path = str(folder.get("path") or "").strip()
        if not folder_path:
            return []
        data = await self._fetch_share_list_payload(
            dict(context.get("tokens") or {}),
            str(context.get("cookie") or ""),
            str(context.get("share_url") or ""),
            str(context.get("shorturl") or ""),
            dir_path=folder_path,
            root=False,
        )
        errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
        if errno:
            raise BaiduNetdiskError(self._baidu_api_error_message(data, f"分享文件夹读取失败 {errno}"))
        children = self._normalize_share_file_list(
            list(data.get("list") or []),
            parent_relative_path=str(folder.get("relative_path") or folder.get("name") or "").strip(),
        )
        files: List[Dict[str, Any]] = []
        for child in children:
            if child.get("is_dir"):
                files.extend(await self._collect_share_folder_files(context, child, depth + 1))
            else:
                files.append(child)
        return files

    def _download_row_from_share_file(
        self,
        item: Dict[str, Any],
        share_file: Dict[str, Any],
        context: Dict[str, Any],
        index_key: str,
        *,
        keep_share_root: bool,
    ) -> Dict[str, Any]:
        name = self._sanitize_path_part(share_file.get("name") or item.get("filename") or "百度网盘文件", "百度网盘文件")
        raw_relative = str(share_file.get("relative_path") or name).strip()
        if not keep_share_root:
            raw_relative = self._strip_selected_share_root(item, raw_relative)
        relative_path = self._safe_relative_path(raw_relative, name)
        custom_extract_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        fs_id = str(share_file.get("fs_id") or share_file.get("fsid") or "").strip()
        size = _safe_int(share_file.get("size_bytes") or share_file.get("size"))
        return {
            "gid": f"{item.get('selection_key') or self._selection_key(item)}:{fs_id or index_key}",
            "name": name,
            "original_name": name,
            "relative_path": relative_path,
            "original_relative_path": relative_path,
            "remote_path": str(share_file.get("path") or "").strip(),
            "local_path": "",
            "url": item.get("masked_url") or item.get("share_url") or "",
            "source": BAIDU_NETDISK_PLATFORM,
            "status": "pending",
            "progress": 0,
            "downloaded": 0,
            "total": size,
            "size": size,
            "fs_id": fs_id,
            "share_id": str(item.get("share_id") or "").strip(),
            "share_numeric_id": context.get("shareid") or "",
            "share_uk": context.get("share_uk") or "",
            "bdstoken": context.get("bdstoken") or "",
            "randsk": context.get("randsk") or "",
            "shorturl": context.get("shorturl") or "",
            "share_url": context.get("share_url") or "",
            "share_sign": context.get("sign") or "",
            "share_timestamp": context.get("timestamp") or "",
            "pass_code": item.get("pass_code") or "",
            "custom_name": str(item.get("custom_name") or item.get("custom_filename") or "").strip(),
            "custom_extract_password": custom_extract_password,
        }

    def _strip_selected_share_root(self, item: Dict[str, Any], relative_path: str) -> str:
        text = str(relative_path or "").replace("\\", "/").strip("/")
        root = str(item.get("filename") or item.get("name") or "").replace("\\", "/").strip("/")
        if root and text.startswith(f"{root}/"):
            return text[len(root) + 1:]
        return text

    def _apply_custom_download_name_to_rows(self, item: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return rows
        file_overrides = self._baidu_selected_file_overrides(item)
        if file_overrides:
            rows = [self._apply_custom_file_override_to_row(row, file_overrides) for row in rows]
        custom_name = str(item.get("custom_name") or item.get("custom_filename") or "").strip()
        custom_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        if not custom_name and not custom_password:
            return rows
        if len(rows) != 1:
            if bool(item.get("custom_group_folder")):
                return self._apply_custom_group_folder_to_rows(rows, custom_name, custom_password)
            for row in rows:
                row["custom_rename_skipped"] = True
                row["custom_rename_skip_reason"] = "多文件分享不自动套用单文件重命名"
            return rows
        row = rows[0]
        custom_relative_path = self._custom_download_relative_path(item, str(row.get("relative_path") or ""))
        if custom_relative_path:
            row["name"] = os.path.basename(custom_relative_path.replace("\\", "/"))
            row["relative_path"] = custom_relative_path
            row["custom_rename_applied"] = True
        return rows

    def _apply_custom_group_folder_to_rows(
        self,
        rows: List[Dict[str, Any]],
        custom_name: str,
        custom_password: str,
    ) -> List[Dict[str, Any]]:
        folder_name = self._filename_with_extract_password(custom_name, custom_password, "")
        if not folder_name:
            return rows
        has_explicit_file_selection = any(
            isinstance(row, dict) and bool(row.get("custom_file_rename_applied"))
            for row in rows
        )

        def original_parent(row: Dict[str, Any]) -> str:
            original = str(
                row.get("original_relative_path")
                or row.get("relative_path")
                or row.get("name")
                or ""
            ).replace("\\", "/").strip("/")
            return os.path.dirname(original.replace("/", os.sep))

        selected_parent_dirs = {
            original_parent(row)
            for row in rows
            if isinstance(row, dict) and (
                bool(row.get("custom_file_rename_applied")) or not has_explicit_file_selection
            )
        }
        has_unrelated_same_level = any(
            isinstance(row, dict)
            and not bool(row.get("custom_file_rename_applied"))
            and original_parent(row) in selected_parent_dirs
            for row in rows
        )
        if has_explicit_file_selection and not has_unrelated_same_level:
            for row in rows:
                if isinstance(row, dict) and bool(row.get("custom_file_rename_applied")) and custom_password:
                    row["custom_extract_password"] = custom_password
            return rows

        next_rows: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if has_explicit_file_selection and not bool(row.get("custom_file_rename_applied")):
                next_rows.append(row)
                continue
            relative_path = str(row.get("relative_path") or row.get("name") or "").strip()
            if not relative_path:
                next_rows.append(row)
                continue
            next_row = dict(row)
            next_row["relative_path"] = self._safe_relative_path(
                os.path.join(folder_name, relative_path),
                relative_path,
            )
            next_row["custom_group_folder"] = folder_name
            next_row["custom_group_folder_applied"] = True
            if custom_password:
                next_row["custom_extract_password"] = custom_password
            next_rows.append(next_row)
        return next_rows

    def _apply_custom_file_override_to_row(self, row: Dict[str, Any], overrides: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        if not isinstance(row, dict) or not overrides:
            return row
        candidates = [
            str(row.get("fs_id") or "").strip(),
            str(row.get("remote_path") or row.get("path") or "").strip(),
            str(row.get("original_relative_path") or "").strip(),
            str(row.get("relative_path") or "").strip(),
            str(row.get("original_name") or row.get("name") or "").strip(),
        ]
        override = next((overrides.get(key) for key in candidates if key and overrides.get(key)), None)
        if not override:
            return row
        custom_name = str(override.get("custom_name") or override.get("custom_filename") or "").strip()
        custom_password = str(override.get("custom_extract_password") or override.get("extract_password") or "").strip()
        if not custom_name and not custom_password:
            return row
        proxy_item = {
            "custom_name": custom_name,
            "custom_extract_password": custom_password,
        }
        custom_relative_path = self._custom_download_relative_path(proxy_item, str(row.get("relative_path") or ""))
        if not custom_relative_path:
            return row
        next_row = dict(row)
        next_row["name"] = os.path.basename(custom_relative_path.replace("\\", "/"))
        next_row["relative_path"] = custom_relative_path
        next_row["custom_name"] = custom_name
        next_row["custom_extract_password"] = custom_password
        next_row["custom_file_rename_applied"] = True
        return next_row

    def _custom_download_relative_path(self, item: Dict[str, Any], relative_path: str) -> str:
        custom_name = self._sanitize_path_part(
            item.get("custom_name") or item.get("custom_filename") or "",
            "",
        )
        custom_password = str(item.get("custom_extract_password") or item.get("extract_password") or "").strip()
        if not custom_name and not custom_password:
            return ""

        normalized = str(relative_path or "").replace("\\", "/").strip("/")
        folder = os.path.dirname(normalized.replace("/", os.sep))
        current_base = os.path.basename(normalized)
        stem, ext = self._split_archive_filename(current_base)
        if not custom_name:
            custom_name = self._sanitize_path_part(stem or current_base or "百度网盘文件", "百度网盘文件")
        custom_stem, custom_ext = self._split_archive_filename(custom_name)
        original_volume = re.match(r"^\.(?P<kind>7z|zip)\.(?P<index>\d{3})$", ext, re.IGNORECASE)
        custom_volume = re.match(r"^\.(?P<kind>7z|zip)\.(?P<index>\d{3})$", custom_ext, re.IGNORECASE)
        volume_base_alias = bool(
            original_volume
            and (
                custom_name.lower().endswith(f".{original_volume.group('kind').lower()}")
                or (
                    custom_volume
                    and custom_volume.group("kind").lower() == original_volume.group("kind").lower()
                )
            )
        )
        if custom_ext and not volume_base_alias:
            # 输入框填写的是完整文件名时，以用户输入为准，不能再把原始（可能乱码的）扩展名追加一次。
            target_name = self._filename_with_extract_password(custom_stem, custom_password, custom_ext)
        else:
            # 兼容“foo.7z”作为“foo.7z.001 / foo.7z.002”的公共基名写法。
            custom_name = self._dedupe_custom_archive_volume_name(custom_name, ext)
            ext = self._normalize_custom_archive_volume_ext(custom_name, ext)
            target_name = self._filename_with_extract_password(custom_name, custom_password, ext)
        if folder:
            return self._safe_relative_path(os.path.join(folder, target_name), target_name)
        return self._safe_relative_path(target_name, target_name)

    def _filename_with_extract_password(self, name: str, password: str, ext: str = "") -> str:
        safe_name = self._sanitize_path_part(name, "百度网盘文件")
        safe_password = self._sanitize_path_part(password, "")
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
            rendered = self._sanitize_path_part(rendered, "")
            if rendered:
                return rendered
        return f"{name}({password})"

    def _normalize_custom_archive_volume_ext(self, custom_name: str, ext: str) -> str:
        custom_lower = str(custom_name or "").strip().lower()
        ext_text = str(ext or "")
        volume_match = re.match(r"^\.(?P<kind>7z|zip)\.(?P<index>\d{3})$", ext_text, re.IGNORECASE)
        if volume_match and custom_lower.endswith(f".{volume_match.group('kind').lower()}"):
            return f".{volume_match.group('index')}"
        return ext_text

    def _dedupe_custom_archive_volume_name(self, custom_name: str, ext: str) -> str:
        name = str(custom_name or "").strip()
        ext_text = str(ext or "").strip()
        if not name or not ext_text:
            return name

        lower_name = name.lower()
        lower_ext = ext_text.lower()

        volume_match = re.match(r"^\.(?P<kind>7z|zip)\.(?P<index>\d{3})$", ext_text, re.IGNORECASE)
        if volume_match:
            same_kind_match = re.match(
                rf"^(?P<base>.+\.{re.escape(volume_match.group('kind'))})\.\d{{3}}$",
                name,
                re.IGNORECASE,
            )
            if same_kind_match:
                return same_kind_match.group("base").strip() or name
            generic_index_match = re.match(r"^(?P<base>.+)\.\d{3}$", name, re.IGNORECASE)
            if generic_index_match:
                return generic_index_match.group("base").strip() or name
            index_suffix = f".{volume_match.group('index')}"
            if lower_name.endswith(index_suffix):
                stripped = name[:-len(index_suffix)].rstrip()
                return stripped or name

        if not lower_name.endswith(lower_ext):
            return name

        stripped = name[:-len(ext_text)].rstrip()
        return stripped or name

    def _split_archive_filename(self, filename: str) -> tuple[str, str]:
        value = str(filename or "").strip()
        lower = value.lower()
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if lower.endswith(suffix):
                return value[:-len(suffix)], value[-len(suffix):]
        volume_match = re.match(r"^(?P<stem>.+?)[._\-\s]+z(?P<index>\d{2})$", value, re.IGNORECASE)
        if volume_match:
            return volume_match.group("stem").strip() or value, f".z{volume_match.group('index')}"
        volume_match = re.match(r"^(?P<stem>.+?)\.(?P<kind>7z|zip)\.(?P<index>\d{3})$", value, re.IGNORECASE)
        if volume_match:
            return volume_match.group("stem").strip() or value, f".{volume_match.group('kind')}.{volume_match.group('index')}"
        volume_match = re.match(r"^(?P<stem>.+?)\.part(?P<index>\d+)(?P<ext>\.(?:rar|zip|7z|exe))?$", value, re.IGNORECASE)
        if volume_match:
            return volume_match.group("stem").strip() or value, f".part{volume_match.group('index')}{volume_match.group('ext') or ''}"
        volume_match = re.match(r"^(?P<stem>.+?)\.(?P<ext>r\d{2}|e\d{2}|\d{3})$", value, re.IGNORECASE)
        if volume_match:
            return volume_match.group("stem").strip() or value, f".{volume_match.group('ext')}"
        stem, ext = os.path.splitext(value)
        return stem or value, ext

    async def start_download_task(self, task) -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        preview = await self._resolve_download_preview(metadata)
        items = [item for item in list(preview.get("items") or []) if item.get("ok")]
        if not items:
            raise BaiduNetdiskError("没有可下载的百度网盘分享")

        target_subdir = self._safe_subdir(str(metadata.get("target_subdir") or ""))
        output_folder_name = self.validate_output_folder_name(str(metadata.get("output_folder_name") or ""), allow_empty=True)
        conflict_policy = str(metadata.get("conflict_policy") or getattr(self._config(), "conflict_policy", "resume") or "resume").lower()
        if conflict_policy not in {"resume", "rename", "skip"}:
            conflict_policy = "resume"

        download_root = self._download_root()
        final_base_dir = self._safe_join(download_root, target_subdir)
        os.makedirs(final_base_dir, exist_ok=True)
        batch_folder = self._download_batch_folder_name(metadata)
        final_dir = self._safe_join(final_base_dir, batch_folder)
        final_dir = self._resolve_final_dir_for_policy(final_dir, conflict_policy)
        if conflict_policy == "skip" and os.path.exists(final_dir):
            task.task_metadata.update({
                "download_root": download_root,
                "download_batch_folder_name": batch_folder,
                "requested_output_folder_name": output_folder_name,
                "final_output_path": final_dir,
                "output_finalize_status": "skipped_existing",
                "download_runtime": {
                    "status": "skipped",
                    "total_files": len(items),
                    "completed_files": 0,
                    "failed_files": 0,
                    "active_file_count": 0,
                    "transferred_bytes": 0,
                    "total_bytes": 0,
                    "speed_bytes_per_sec": 0,
                },
            })
            task.update_progress(100, "目标目录已存在，已按冲突策略跳过")
            return {"success": True, "skipped": True, "download_root": download_root, "downloaded_files": []}

        staging_dir = str(metadata.get("staging_dir") or "").strip()
        if not staging_dir:
            staging_parent = self._safe_join(download_root, ".baidu-netdisk-staging")
            os.makedirs(staging_parent, exist_ok=True)
            staging_dir = os.path.join(staging_parent, task.id)
        os.makedirs(staging_dir, exist_ok=True)

        download_files = await self._build_download_file_rows(items)
        if not download_files:
            raise BaiduNetdiskError("分享里没有可直接下载的文件")
        total_bytes = sum(int(item.get("size") or 0) for item in download_files)
        task.task_metadata.update({
            "download_root": download_root,
            "download_batch_folder_name": batch_folder,
            "requested_output_folder_name": output_folder_name,
            "staging_dir": staging_dir,
            "final_output_path": final_dir,
            "renamed_output_path": "",
            "output_finalize_status": "pending",
            "download_files": download_files,
            "download_runtime": {
                "status": "downloading",
                "total_files": len(download_files),
                "completed_files": 0,
                "failed_files": 0,
                "active_file_count": 1,
                "transferred_bytes": 0,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0,
                "current_file_name": download_files[0]["name"] if download_files else "",
                "current_relative_path": "",
                "speed_label": "百度网盘 SVIP 高速" if self._is_svip() else "百度网盘下载",
            },
            "failed_files": [],
            "progress_log": list(metadata.get("progress_log") or []),
            "source_modes": [BAIDU_NETDISK_PLATFORM],
            "platforms": [BAIDU_NETDISK_PLATFORM],
            "platform_label": BAIDU_NETDISK_LABEL,
        })
        task.output_path = final_dir
        task.update_progress(1, "准备百度网盘下载")
        cancel_event = asyncio.Event()
        self._task_cancel_events[task.id] = cancel_event
        started = time.monotonic()

        try:
            max_concurrent = self._baidu_download_file_concurrency(len(download_files))
            task.task_metadata["download_runtime"]["active_file_limit"] = max_concurrent
            if max_concurrent > 1:
                self._append_log(task, f"百度网盘全局文件下载并发：{max_concurrent} 个", "info")
            budget_limit = self._network_download_budget_limit()
            _max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
            if budget_limit > 0 and budget_limit < max_download_load:
                self._append_log(
                    task,
                    f"全局下载资源预算限制为 {budget_limit}，百度网盘全局同时文件配置 {max_download_load} 已按预算收敛",
                    "info",
                )
            if len(download_files) > 1 and max_concurrent > 1:
                for row_index, row in enumerate(download_files):
                    row["_remote_transfer_scope"] = row_index
            semaphore = asyncio.Semaphore(max_concurrent)
            await asyncio.gather(*[
                self._download_share_item_guarded(
                    task,
                    staging_dir,
                    row,
                    index,
                    download_files,
                    started,
                    cancel_event,
                    semaphore,
                )
                for index, row in enumerate(download_files)
            ])
        except asyncio.CancelledError:
            if task.is_cancelled():
                await self._finalize_cancelled_download_task(
                    task,
                    download_files,
                    started=started,
                    staging_dir=staging_dir,
                    download_root=download_root,
                )
            raise
        finally:
            if self._task_cancel_events.get(task.id) is cancel_event:
                self._task_cancel_events.pop(task.id, None)
            for row in download_files:
                if isinstance(row, dict):
                    row.pop("_remote_transfer_scope", None)

        success_files = [row for row in download_files if row.get("status") == "completed"]
        failed_files = [row for row in download_files if row.get("status") == "failed"]
        if not success_files:
            duration_ms = int((time.monotonic() - started) * 1000)
            transferred_bytes = sum(int(row.get("downloaded") or 0) for row in download_files)
            task.task_metadata["failed_files"] = failed_files
            task.task_metadata["performance_metrics"] = {
                "duration_ms": duration_ms,
                "downloaded_bytes": 0,
                "transferred_bytes": transferred_bytes,
                "success_count": 0,
                "failed_count": len(failed_files),
                "average_speed_bytes": 0,
            }
            runtime = dict(task.task_metadata.get("download_runtime") or {})
            runtime.update({
                "status": "failed",
                "completed_files": 0,
                "failed_files": len(failed_files),
                "active_file_count": 0,
                "transferred_bytes": transferred_bytes,
                "speed_bytes_per_sec": 0,
            })
            task.task_metadata["download_runtime"] = runtime
            try:
                from .task_phase_metric_service import get_task_phase_metric_service

                task_type = getattr(getattr(task, "type", None), "value", getattr(task, "type", ""))
                await get_task_phase_metric_service().record_async(
                    task_id=str(getattr(task, "id", "") or ""),
                    task_type=str(task_type or ""),
                    phase="baidu_netdisk_download",
                    resource="network_download",
                    status="failed",
                    duration_ms=duration_ms,
                    bytes_total=transferred_bytes,
                    items_total=0,
                    detail={
                        "failed_count": len(failed_files),
                        "source": "baidu_netdisk_service",
                    },
                )
            except Exception:
                logger.warning("[百度网盘] 记录失败阶段指标失败 task_id=%s", getattr(task, "id", ""), exc_info=True)
            raise BaiduNetdiskError(self._first_failure_reason(failed_files) or "没有任何百度网盘文件下载成功")

        finalized = await asyncio.to_thread(self._finalize_output, staging_dir, final_dir, conflict_policy, len(items))
        staging_cleanup = await asyncio.to_thread(
            self._cleanup_completed_staging_dir,
            task,
            staging_dir,
            download_root,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        downloaded_bytes = self._directory_size(finalized) if os.path.exists(finalized) else 0
        for row in success_files:
            final_file = self._safe_join(finalized, str(row.get("relative_path") or row.get("name") or ""))
            row["local_path"] = final_file if os.path.exists(final_file) else finalized
        task.task_metadata.update({
            "download_files": download_files,
            "failed_files": failed_files,
            "final_output_path": finalized,
            "renamed_output_path": finalized,
            "output_finalize_status": "completed",
            "staging_cleanup": staging_cleanup,
            "performance_metrics": {
                "duration_ms": duration_ms,
                "downloaded_bytes": downloaded_bytes,
                "transferred_bytes": downloaded_bytes,
                "success_count": len(success_files),
                "failed_count": len(failed_files),
                "average_speed_bytes": int(downloaded_bytes / max(duration_ms / 1000, 1)) if downloaded_bytes else 0,
            },
        })
        try:
            from .task_phase_metric_service import get_task_phase_metric_service

            task_type = getattr(getattr(task, "type", None), "value", getattr(task, "type", ""))
            await get_task_phase_metric_service().record_async(
                task_id=str(getattr(task, "id", "") or ""),
                task_type=str(task_type or ""),
                phase="baidu_netdisk_download",
                resource="network_download",
                status="completed" if not failed_files else "partial_failed",
                duration_ms=duration_ms,
                bytes_total=downloaded_bytes,
                items_total=len(success_files),
                detail={
                    "failed_count": len(failed_files),
                    "source": "baidu_netdisk_service",
                },
            )
        except Exception:
            logger.warning("[百度网盘] 记录下载阶段指标失败 task_id=%s", getattr(task, "id", ""), exc_info=True)
        runtime = dict(task.task_metadata.get("download_runtime") or {})
        runtime.update({
            "status": "completed" if not failed_files else "partial_failed",
            "completed_files": len(success_files),
            "failed_files": len(failed_files),
            "active_file_count": 0,
            "transferred_bytes": downloaded_bytes,
            "total_bytes": max(int(runtime.get("total_bytes") or 0), downloaded_bytes),
            "speed_bytes_per_sec": 0,
            "current_file_name": "",
            "current_relative_path": finalized,
        })
        task.task_metadata["download_runtime"] = runtime
        task.output_path = finalized
        task.update_progress(100, f"百度网盘下载完成，输出到 {finalized}")
        return {
            "success": not bool(failed_files),
            "partial_success": bool(failed_files),
            "download_root": download_root,
            "downloaded_files": success_files,
            "failed_files": failed_files,
            "final_output_path": finalized,
        }

    async def start_upload_task(self, task) -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        source_paths = [
            os.path.abspath(str(path))
            for path in list(metadata.get("source_paths") or [])
            if str(path or "").strip()
        ]
        if not source_paths and task.source_path:
            source_paths = [os.path.abspath(str(task.source_path))]
        source_paths = list(dict.fromkeys(source_paths))
        if not source_paths:
            raise BaiduNetdiskError("没有选中要上传的本地文件或目录")
        missing = [path for path in source_paths if not os.path.exists(path)]
        if missing:
            raise BaiduNetdiskError(f"本地路径不存在，无法上传: {missing[0]}")

        cookie = self._configured_baidu_cookie()
        if not self._has_baidu_login_cookie(cookie):
            raise BaiduNetdiskError("百度账号未登录，无法上传到百度网盘")

        remote_dir = self._join_remote_dir(
            metadata.get("remote_dir") or self._default_upload_remote_dir(),
            metadata.get("create_remote_subdir") or "",
        )
        conflict_policy = self._upload_conflict_policy(metadata.get("conflict_policy"))
        pcsgo_path = self._resolve_baidu_pcs_go_path()
        work_root = os.path.join(get_config().storage.temp_path, "baidu_netdisk_pcsgo")
        os.makedirs(work_root, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix=f"{task.id}_upload_", dir=work_root)
        savedir = os.path.join(work_dir, "upload")
        os.makedirs(savedir, exist_ok=True)
        config_dir = os.path.join(work_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        log_path = os.path.join(work_dir, "baidupcs-go-upload.log")
        env = os.environ.copy()
        env["BAIDUPCS_GO_CONFIG_DIR"] = config_dir

        upload_files = await asyncio.to_thread(self._build_upload_file_rows, source_paths)
        total_bytes = sum(int(item.get("size") or 0) for item in upload_files)
        started = time.monotonic()
        task.task_metadata.update({
            "source_paths": source_paths,
            "remote_dir": remote_dir,
            "conflict_policy": conflict_policy,
            "upload_files": upload_files,
            "uploaded_files": [],
            "failed_files": [],
            "upload_runtime": {
                "status": "uploading",
                "total_files": len(upload_files),
                "completed_files": 0,
                "failed_files": 0,
                "transferred_bytes": 0,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0,
                "current_file_name": upload_files[0]["name"] if upload_files else "",
                "current_relative_path": "",
                "speed_label": "百度网盘上传",
            },
            "progress_log": list(metadata.get("progress_log") or []),
            "platforms": [BAIDU_NETDISK_PLATFORM],
            "platform_label": BAIDU_NETDISK_LABEL,
        })
        task.output_path = remote_dir
        task.update_progress(1, "准备百度网盘上传")
        cancel_event = asyncio.Event()
        self._task_cancel_events[task.id] = cancel_event

        try:
            self._write_baidu_pcsgo_cookie_config(config_dir, cookie, workdir=remote_dir)
            for command in self._baidu_pcs_go_upload_config_commands(pcsgo_path, savedir, conflict_policy):
                await self._run_baidu_pcs_go_command(
                    command,
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cancel_event,
                    ignore_task_cancel=True,
                    max_runtime_seconds=20,
                )
            await self._ensure_pcsgo_remote_dir(
                pcsgo_path,
                remote_dir,
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
            )
            task.update_progress(2, "开始百度网盘上传")
            await self._run_baidu_pcs_go_command(
                self._baidu_pcs_go_upload_args(pcsgo_path, source_paths, remote_dir, conflict_policy),
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
                heartbeat_message="BaiduPCS-Go 正在上传到百度网盘",
                on_output=lambda line: self._update_pcsgo_upload_progress(task, upload_files, started, line),
            )
            uploaded_files = []
            for row in upload_files:
                row["status"] = "completed"
                row["progress"] = 100
                row["uploaded"] = int(row.get("size") or 0)
                uploaded_files.append({**row, "remote_dir": remote_dir})
            duration_ms = int((time.monotonic() - started) * 1000)
            average_speed = int(total_bytes / max(duration_ms / 1000, 1)) if total_bytes else 0
            task.task_metadata["upload_files"] = upload_files
            task.task_metadata["uploaded_files"] = uploaded_files[-200:]
            task.task_metadata["failed_files"] = []
            task.task_metadata["duration_ms"] = duration_ms
            task.task_metadata["upload_runtime"] = {
                "status": "completed",
                "total_files": len(upload_files),
                "completed_files": len(upload_files),
                "failed_files": 0,
                "transferred_bytes": total_bytes,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": 0,
                "average_speed_bytes": average_speed,
                "current_file_name": "",
                "current_relative_path": "",
                "speed_label": "百度网盘上传",
            }
            task.update_progress(100, f"百度网盘上传完成，远端目录 {remote_dir}")
            if metadata.get("cleanup_local_archive"):
                self._cleanup_uploaded_local_archives(source_paths, metadata)
            return {
                "success": True,
                "remote_dir": remote_dir,
                "uploaded_files": uploaded_files,
                "failed_files": [],
            }
        except asyncio.CancelledError:
            for row in upload_files:
                if row.get("status") != "completed":
                    row["status"] = "cancelled"
            task.task_metadata["upload_files"] = upload_files
            raise
        except Exception as exc:
            reason = self._sanitize_error(exc)
            failed_files = []
            for row in upload_files:
                if row.get("status") != "completed":
                    row["status"] = "failed"
                    row["failure_reason"] = reason
                    failed_files.append(dict(row))
            task.task_metadata["upload_files"] = upload_files
            task.task_metadata["failed_files"] = failed_files
            self._refresh_upload_runtime(task, upload_files, started=started, current={}, status="failed")
            raise
        finally:
            if self._task_cancel_events.get(task.id) is cancel_event:
                self._task_cancel_events.pop(task.id, None)
            with contextlib.suppress(Exception):
                shutil.rmtree(work_dir, ignore_errors=True)

    def _resolve_final_dir_for_policy(self, final_dir: str, conflict_policy: str) -> str:
        if conflict_policy != "rename" or not os.path.exists(final_dir):
            return final_dir
        index = 1
        candidate = final_dir
        while os.path.exists(candidate):
            candidate = f"{final_dir} ({index})"
            index += 1
        return candidate

    async def _download_share_item(
        self,
        task,
        staging_dir: str,
        row: Dict[str, Any],
        download_files: List[Dict[str, Any]],
        started: float,
        cancel_event: asyncio.Event,
    ) -> None:
        target_path = self._safe_join(staging_dir, str(row.get("relative_path") or row.get("name") or "download.bin"))
        self._append_log(task, "使用 BaiduPCS-Go 临时转存下载，完成后自动删除远端临时目录", "info")
        await self._download_share_item_via_temporary_transfer(
            task,
            staging_dir,
            target_path,
            row,
            download_files,
            started,
            cancel_event,
        )

    def _share_download_cookie(self, row: Dict[str, Any]) -> str:
        cookie = self._configured_baidu_cookie()
        if not cookie:
            raise BaiduNetdiskError("百度账号未登录，无法直接下载分享文件")
        randsk = str(row.get("randsk") or "").strip()
        if randsk:
            cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
        if not self._has_baidu_login_cookie(cookie):
            raise BaiduNetdiskError("百度账号登录态缺少 BDUSS，请重新扫码或重新绑定 Cookie")
        return cookie

    def _resolve_baidu_pcs_go_path(self) -> str:
        configured = str(getattr(self._config(), "baidupcs_go_path", "") or "").strip()
        candidates = [configured] if configured else []
        candidates.append(str(self._repo_root() / "tools" / "baidupcs-go" / "BaiduPCS-Go.exe"))
        for name in ("BaiduPCS-Go", "baidupcs-go"):
            resolved = shutil.which(name)
            if resolved:
                candidates.append(resolved)
        seen: set[str] = set()
        for candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                path = (self._repo_root() / path).resolve()
            resolved = str(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            if os.path.exists(resolved):
                return resolved
        raise BaiduNetdiskError("没有找到可用于百度分享大文件下载的 BaiduPCS-Go")

    async def _run_baidu_pcs_go_login_command(
        self,
        args: List[str],
        *,
        env: Dict[str, str],
        timeout: int = 75,
    ) -> tuple[int, str]:
        def run() -> tuple[int, str]:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(self._repo_root()),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    timeout=timeout,
                    creationflags=creationflags,
                )
            except subprocess.TimeoutExpired as exc:
                output = self._decode_pcsgo_output(exc.output or b"")
                raise BaiduNetdiskError(
                    "百度账号密码登录超时，可能触发了验证码或安全验证，请改用扫码登录"
                    + (f"；输出: {self._sanitize_error(output)}" if output else "")
                ) from exc
            output = self._decode_pcsgo_output(proc.stdout or b"")
            return int(proc.returncode or 0), output

        return await asyncio.to_thread(run)

    def _cookie_header_from_pcsgo_config(self, config_dir: str) -> tuple[str, List[str]]:
        config_path = os.path.join(config_dir, "pcs_config.json")
        if not os.path.exists(config_path):
            return "", []
        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            raise BaiduNetdiskError(f"BaiduPCS-Go 登录配置读取失败: {exc}") from exc
        values: Dict[str, str] = {}
        self._collect_baidu_cookie_values(data, values)
        if not (values.get("BDUSS") or values.get("BDUSS_BFESS")):
            return "", []
        ordered_names = [
            name for name in _BAIDU_COOKIE_PRIORITY if values.get(name)
        ] + sorted(name for name in values if name not in _BAIDU_COOKIE_PRIORITY)
        return "; ".join(f"{name}={values[name]}" for name in ordered_names if values.get(name)), ordered_names

    def _patch_baidu_pcsgo_config_cookie_fields(self, config_dir: str, cookie: str) -> None:
        config_path = os.path.join(config_dir, "pcs_config.json")
        if not os.path.exists(config_path):
            return
        values: Dict[str, str] = {}
        self._collect_cookie_header_values(cookie, values)
        field_map = {
            "BDUSS": ("bduss", "BDUSS"),
            "BDUSS_BFESS": ("bduss", "BDUSS"),
            "STOKEN": ("stoken", "STOKEN"),
            "STOKEN_BFESS": ("stoken", "STOKEN"),
            "PTOKEN": ("ptoken", "PTOKEN"),
            "PTOKEN_BFESS": ("ptoken", "PTOKEN"),
            "BAIDUID": ("baiduid", "BAIDUID"),
            "BAIDUID_BFESS": ("baiduid", "BAIDUID"),
            "PANPSC": ("panpsc", "PANPSC"),
            "BDCLND": ("bdclnd", "BDCLND"),
        }
        patch: Dict[str, str] = {}
        for cookie_name, target_names in field_map.items():
            value = values.get(cookie_name)
            if not value:
                continue
            for target_name in target_names:
                patch[target_name] = value
        if not patch:
            return
        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            logger.debug("BaiduPCS-Go 配置补齐 Cookie 字段失败: %s", exc)
            return
        changed = self._patch_baidu_pcsgo_cookie_node(data, patch, cookie)
        if not changed:
            return
        try:
            Path(config_path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("BaiduPCS-Go 配置写回 Cookie 字段失败: %s", exc)

    def _write_baidu_pcsgo_cookie_config(self, config_dir: str, cookie: str, *, workdir: str = "/") -> str:
        values: Dict[str, str] = {}
        self._collect_cookie_header_values(cookie, values)
        bduss = values.get("BDUSS") or values.get("BDUSS_BFESS") or ""
        if not bduss:
            raise BaiduNetdiskError("BaiduPCS-Go 配置缺少 BDUSS 登录态")

        cfg = self._config()
        uid = self._baidu_pcsgo_config_uid(cookie)
        account_name = str(
            getattr(cfg, "account_name", "")
            or getattr(cfg, "account_netdisk_name", "")
            or getattr(cfg, "username", "")
            or "baidu"
        ).strip()
        savedir = str(getattr(cfg, "download_root", "") or "").strip()
        if not savedir:
            savedir = str(getattr(get_config().storage, "temp_path", "") or tempfile.gettempdir())
        max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
        cookie_header = self._merge_cookie_header("", values)
        config_path = os.path.join(config_dir, "pcs_config.json")
        user = {
            "uid": uid,
            "name": account_name,
            "sex": "",
            "age": 0,
            "bduss": bduss,
            "ptoken": values.get("PTOKEN") or values.get("PTOKEN_BFESS") or "",
            "stoken": values.get("STOKEN") or values.get("STOKEN_BFESS") or "",
            "baiduid": values.get("BAIDUID") or values.get("BAIDUID_BFESS") or "",
            "sboxtkn": "",
            "panpsc": values.get("PANPSC") or "",
            "bdclnd": values.get("BDCLND") or "",
            "cookies": cookie_header,
            "accesstoken": "",
            "workdir": str(workdir or "/").strip() or "/",
        }
        data = {
            "baidu_active_uid": uid,
            "baidu_user_list": [user],
            "appid": 266719,
            "cache_size": 262144,
            "max_parallel": max_parallel,
            "max_upload_parallel": 4,
            "max_download_load": max_download_load,
            "max_upload_load": 4,
            "max_download_rate": 0,
            "max_upload_rate": 0,
            "user_agent": _BAIDU_WEB_USER_AGENT,
            "pcs_ua": "",
            "pcs_addr": "pcs.baidu.com",
            "pan_ua": "netdisk;P2SP;3.0.0.8;netdisk;11.12.3;ANG-AN00;android-android;10.0;JSbridge4.4.0;jointBridge;1.1.0;",
            "savedir": os.path.abspath(savedir),
            "enable_https": True,
            "fix_pcs_addr": False,
            "force_login_username": "",
            "proxy": "",
            "proxy_hostnames": "",
            "local_addrs": "",
            "no_check": True,
            "ignore_illegal": True,
            "u_policy": "skip",
        }
        os.makedirs(config_dir, exist_ok=True)
        Path(config_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config_path

    def _baidu_pcsgo_config_uid(self, cookie: str) -> int:
        cfg = self._config()
        for value in (
            getattr(cfg, "account_uk", ""),
            getattr(cfg, "uid", ""),
            getattr(cfg, "uk", ""),
        ):
            text = str(value or "").strip()
            if text.isdigit():
                number = int(text)
                if number > 0:
                    return number
        seed = (
            self._cookie_value(cookie, "BDUSS")
            or self._cookie_value(cookie, "BDUSS_BFESS")
            or str(getattr(cfg, "account_name", "") or "").strip()
            or "baidu"
        )
        return max(1, int(hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:8], 16))

    def _patch_baidu_pcsgo_cookie_node(self, node: Any, patch: Dict[str, str], cookie: str) -> bool:
        changed = False
        if isinstance(node, dict):
            user_keys = {"bduss", "stoken", "ptoken", "baiduid", "cookies", "cookie"}
            looks_like_user = any(str(key or "").lower() in user_keys for key in node)
            if looks_like_user:
                for key, value in patch.items():
                    if value and str(node.get(key) or "").strip() != value:
                        node[key] = value
                        changed = True
                if cookie:
                    for cookie_key in ("cookie", "cookies"):
                        if cookie_key in node and str(node.get(cookie_key) or "").strip() != cookie:
                            node[cookie_key] = cookie
                            changed = True
                    if "cookies" not in node and "cookie" not in node:
                        node["cookies"] = cookie
                        changed = True
            for value in node.values():
                if self._patch_baidu_pcsgo_cookie_node(value, patch, cookie):
                    changed = True
            return changed
        if isinstance(node, list):
            for item in node:
                if self._patch_baidu_pcsgo_cookie_node(item, patch, cookie):
                    changed = True
        return changed

    def _collect_baidu_cookie_values(self, node: Any, values: Dict[str, str]) -> None:
        if isinstance(node, dict):
            cookie_text = node.get("cookie") or node.get("cookies")
            if isinstance(cookie_text, str):
                self._collect_cookie_header_values(cookie_text, values)
            for key, value in node.items():
                clean_key = str(key or "").strip()
                upper_key = clean_key.upper()
                canonical_key = _BAIDU_COOKIE_NAME_BY_UPPER.get(upper_key, clean_key)
                if upper_key in _BAIDU_COOKIE_NAME_BY_UPPER and not isinstance(value, (dict, list)):
                    clean_value = str(value or "").strip()
                    if clean_value:
                        values[canonical_key] = clean_value
                elif clean_key in _BAIDU_COOKIE_PRIORITY and not isinstance(value, (dict, list)):
                    clean_value = str(value or "").strip()
                    if clean_value:
                        values[clean_key] = clean_value
                self._collect_baidu_cookie_values(value, values)
            return
        if isinstance(node, list):
            for item in node:
                self._collect_baidu_cookie_values(item, values)

    def _collect_cookie_header_values(self, cookie: str, values: Dict[str, str]) -> None:
        for part in str(cookie or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            clean_key = key.strip()
            clean_value = value.strip()
            if clean_key and clean_value:
                values[clean_key] = clean_value

    def _baidu_password_login_error(self, output: str, returncode: int = 0) -> str:
        text = self._sanitize_error(output or "").strip()[:500]
        lowered = text.lower()
        verification_markers = (
            "verify",
            "captcha",
            "sms",
            "验证码",
            "二次验证",
            "安全验证",
            "手机",
            "邮箱",
            "身份验证",
        )
        if any(marker in lowered or marker in text for marker in verification_markers):
            return f"百度要求验证码或安全验证，账号密码登录无法在 Web 设置页继续，请改用扫码登录。{text}".strip()
        if text:
            return f"百度账号密码登录失败: {text}"
        if returncode:
            return f"百度账号密码登录失败，BaiduPCS-Go 返回退出码 {returncode}，请改用扫码登录"
        return "百度账号密码登录没有拿到登录态，请改用扫码登录"

    def _bounded_pcsgo_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(float(str(value).strip()))
        except Exception:
            number = default
        if number < minimum:
            number = default
        return max(minimum, min(maximum, number))

    def _baidu_pcs_go_download_limits(self) -> tuple[int, int]:
        cfg = self._config()
        max_parallel = self._bounded_pcsgo_int(
            getattr(cfg, "max_parallel", 20),
            default=20,
            minimum=1,
            maximum=20,
        )
        max_download_load = self._bounded_pcsgo_int(
            getattr(cfg, "max_download_load", 5),
            default=5,
            minimum=1,
            maximum=5,
        )
        return max_parallel, max_download_load

    def _baidu_download_file_concurrency(self, file_count: int = 0) -> int:
        _max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
        budget_limit = self._network_download_budget_limit()
        count = max(1, int(file_count or 1))
        if budget_limit > 0:
            return max(1, min(count, max_download_load, budget_limit))
        return max(1, min(count, max_download_load))

    def _baidu_global_download_limit(self) -> int:
        return self._baidu_download_file_concurrency(10_000)

    @contextlib.asynccontextmanager
    async def _acquire_global_download_slot(self, task, row: Dict[str, Any], cancel_event: asyncio.Event) -> AsyncIterator[None]:
        limit = max(1, self._baidu_global_download_limit())
        row["waiting_global_slot"] = True
        wait_started_at = time.monotonic()
        acquired = False
        try:
            while True:
                await self._check_task_active(task, cancel_event)
                limit = max(1, self._baidu_global_download_limit())
                with self._download_slot_lock:
                    if self._download_slot_active < limit:
                        self._download_slot_active += 1
                        acquired = True
                        break
                await asyncio.sleep(0.25)
        except BaseException:
            row["waiting_global_slot"] = False
            raise
        waited = time.monotonic() - wait_started_at
        row["waiting_global_slot"] = False
        row["global_slot_limit"] = limit
        if waited >= 1:
            self._append_log(
                task,
                f"已获取百度网盘全局下载槽：{row.get('name') or '未命名文件'}，等待 {waited:.1f}s",
                "info",
            )
        try:
            yield
        finally:
            row["global_slot_limit"] = limit
            if acquired:
                with self._download_slot_lock:
                    self._download_slot_active = max(0, self._download_slot_active - 1)

    def _baidu_transfer_limits(self) -> tuple[int, int]:
        cfg = self._config()
        max_concurrency = self._bounded_pcsgo_int(
            getattr(cfg, "transfer_max_concurrency", 1),
            default=1,
            minimum=1,
            maximum=5,
        )
        retry_count = self._bounded_pcsgo_int(
            getattr(cfg, "transfer_retry_count", 4),
            default=4,
            minimum=0,
            maximum=8,
        )
        return max_concurrency, retry_count

    @contextlib.asynccontextmanager
    async def _acquire_global_transfer_slot(
        self,
        task,
        row: Dict[str, Any],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[None]:
        limit, _retry_count = self._baidu_transfer_limits()
        row["transfer_status"] = "waiting"
        row["waiting_transfer_slot"] = True
        acquired = False
        try:
            while True:
                await self._check_task_active(task, cancel_event)
                limit, _retry_count = self._baidu_transfer_limits()
                with self._transfer_slot_lock:
                    if self._transfer_slot_active < limit:
                        self._transfer_slot_active += 1
                        acquired = True
                        break
                await asyncio.sleep(0.25)
            row["waiting_transfer_slot"] = False
            row["transfer_slot_limit"] = limit
            row["transfer_status"] = "transferring"
            yield
        finally:
            row["waiting_transfer_slot"] = False
            if acquired:
                with self._transfer_slot_lock:
                    self._transfer_slot_active = max(0, self._transfer_slot_active - 1)

    def _is_transient_baidu_transfer_error(self, exc: Exception) -> bool:
        if isinstance(exc, (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
        )):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            response = getattr(exc, "response", None)
            return int(getattr(response, "status_code", 0) or 0) in {429, 500, 502, 503, 504}
        return False

    async def _wait_baidu_transfer_retry(
        self,
        task,
        cancel_event: asyncio.Event,
        delay_seconds: int,
    ) -> None:
        deadline = time.monotonic() + max(0, delay_seconds)
        while True:
            await self._check_task_active(task, cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            await self._check_task_active(task, cancel_event)

    async def _transfer_share_item_with_retry(
        self,
        task,
        row: Dict[str, Any],
        cookie: str,
        remote_tmp_dir: str,
        *,
        share_url: str,
        pass_code: str,
        download_files: List[Dict[str, Any]],
        started: float,
        cancel_event: asyncio.Event,
        confirm_transferred: Optional[Callable[[], Any]] = None,
    ) -> Dict[str, Any]:
        _max_concurrency, retry_count = self._baidu_transfer_limits()
        total_attempts = retry_count + 1
        transfer_row = dict(row)
        row.update({
            "transfer_attempt": 0,
            "transfer_retry_limit": retry_count,
            "transfer_next_retry_seconds": 0,
        })
        async with self._acquire_global_transfer_slot(task, row, cancel_event):
            for attempt in range(1, total_attempts + 1):
                await self._check_task_active(task, cancel_event)
                row.update({
                    "transfer_status": "transferring",
                    "transfer_attempt": attempt,
                    "transfer_next_retry_seconds": 0,
                })
                self._refresh_runtime(task, download_files, started=started, current=row)
                try:
                    result = await self._transfer_share_item_by_web(
                        transfer_row,
                        cookie,
                        remote_tmp_dir,
                        share_url=share_url,
                        pass_code=pass_code,
                    )
                    row["transfer_status"] = "completed"
                    self._refresh_runtime(task, download_files, started=started, current=row)
                    return result
                except Exception as exc:
                    is_transient = self._is_transient_baidu_transfer_error(exc)
                    if is_transient and confirm_transferred is not None:
                        with contextlib.suppress(Exception):
                            if await confirm_transferred():
                                row.update({
                                    "transfer_status": "completed",
                                    "transfer_next_retry_seconds": 0,
                                    "transfer_confirmed_after_error": True,
                                })
                                self._append_log(
                                    task,
                                    "百度转存响应中断，但已确认远端文件名称和大小一致，继续高速下载",
                                    "warning",
                                )
                                self._refresh_runtime(task, download_files, started=started, current=row)
                                return {"errno": 0, "confirmed_after_error": True}
                    if not is_transient or attempt >= total_attempts:
                        row["transfer_status"] = "failed"
                        self._refresh_runtime(task, download_files, started=started, current=row)
                        raise
                    delay = _BAIDU_TRANSFER_RETRY_DELAYS_SECONDS[
                        min(attempt, len(_BAIDU_TRANSFER_RETRY_DELAYS_SECONDS) - 1)
                    ]
                    row.update({
                        "transfer_status": "retrying",
                        "transfer_next_retry_seconds": delay,
                    })
                    self._append_log(
                        task,
                        f"百度转存连接异常，{delay} 秒后重试 {attempt}/{retry_count}："
                        f"{self._sanitize_error(exc)}",
                        "warning",
                    )
                    self._refresh_runtime(task, download_files, started=started, current=row)
                    await self._wait_baidu_transfer_retry(task, cancel_event, delay)
        raise BaiduNetdiskError("百度分享转存重试流程异常结束")

    def _network_download_budget_limit(self) -> int:
        cfg = getattr(get_config(), "resource_budget", None)
        if cfg is None or not bool(getattr(cfg, "enabled", True)):
            return 0
        try:
            return max(0, int(getattr(cfg, "network_download", 0) or 0))
        except Exception:
            return 0

    async def _download_share_item_guarded(
        self,
        task,
        staging_dir: str,
        row: Dict[str, Any],
        index: int,
        download_files: List[Dict[str, Any]],
        started: float,
        cancel_event: asyncio.Event,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            async with self._acquire_global_download_slot(task, row, cancel_event):
                await self._check_task_active(task, cancel_event)
                row["status"] = "downloading"
                self._refresh_runtime(task, download_files, started=started, current=row)
                task.update_progress(max(2, task.progress), f"下载百度网盘文件 {index + 1}/{len(download_files)}")
                try:
                    await self._download_share_item(task, staging_dir, row, download_files, started, cancel_event)
                    row["status"] = "completed"
                    row["progress"] = 100
                    row["speed_bytes_per_sec"] = 0
                except asyncio.CancelledError:
                    if str(getattr(task.status, "value", task.status) or "") == "paused" and not task.is_cancelled():
                        row["status"] = "paused"
                        row["failure_reason"] = "任务已暂停"
                    else:
                        row["status"] = "cancelled"
                    raise
                except Exception as exc:
                    row["status"] = "failed"
                    row["speed_bytes_per_sec"] = 0
                    row["failure_reason"] = self._sanitize_error(exc)
                finally:
                    self._refresh_runtime(task, download_files, started=started, current={})

    def _baidu_pcs_go_upload_limits(self) -> tuple[int, int]:
        cfg = self._config()
        max_parallel = self._bounded_pcsgo_int(
            getattr(cfg, "upload_max_parallel", 4),
            default=4,
            minimum=1,
            maximum=20,
        )
        max_upload_load = self._bounded_pcsgo_int(
            getattr(cfg, "upload_max_load", 4),
            default=4,
            minimum=1,
            maximum=20,
        )
        return max_parallel, max_upload_load

    def _baidu_pcs_go_download_config_commands(self, pcsgo_path: str, savedir: str) -> List[List[str]]:
        max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
        return [
            [pcsgo_path, "config", "set", "-savedir", savedir],
            [pcsgo_path, "config", "set", "-max_parallel", str(max_parallel)],
            [pcsgo_path, "config", "set", "-max_download_load", str(max_download_load)],
            [pcsgo_path, "config", "set", "-max_download_rate", "0"],
            [pcsgo_path, "config", "set", "-cache_size", "256KB"],
        ]

    def _baidu_pcs_go_upload_config_commands(self, pcsgo_path: str, savedir: str, conflict_policy: str) -> List[List[str]]:
        max_parallel, max_upload_load = self._baidu_pcs_go_upload_limits()
        return [
            [pcsgo_path, "config", "set", "-savedir", savedir],
            [pcsgo_path, "config", "set", "-max_upload_parallel", str(max_parallel)],
            [pcsgo_path, "config", "set", "-max_upload_load", str(max_upload_load)],
            [pcsgo_path, "config", "set", "-max_upload_rate", "0"],
            [pcsgo_path, "config", "set", "-u_policy", conflict_policy],
        ]

    def _baidu_pcs_go_download_args(self, pcsgo_path: str, remote_path: str, savedir: str) -> List[str]:
        max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
        return [
            pcsgo_path,
            "download",
            remote_path,
            "--saveto",
            savedir,
            "--mode",
            "locate",
            "-p",
            str(max_parallel),
            "-l",
            str(max_download_load),
            "--retry",
            "5",
        ]

    def _baidu_low_speed_refresh_policy(self, row: Dict[str, Any]) -> tuple[bool, int, int, int]:
        cfg = self._config()
        total_bytes = _safe_int(row.get("total") or row.get("size"))
        enabled = bool(getattr(cfg, "low_speed_refresh_enabled", True))
        enabled = enabled and self._is_svip() and total_bytes >= _BAIDU_LOW_SPEED_MIN_FILE_SIZE_BYTES
        threshold_mbps = self._bounded_pcsgo_int(
            getattr(cfg, "low_speed_threshold_mbps", 3),
            default=3,
            minimum=1,
            maximum=20,
        )
        duration_seconds = self._bounded_pcsgo_int(
            getattr(cfg, "low_speed_duration_seconds", 180),
            default=180,
            minimum=30,
            maximum=1800,
        )
        refresh_limit = self._bounded_pcsgo_int(
            getattr(cfg, "low_speed_refresh_limit", 2),
            default=2,
            minimum=0,
            maximum=5,
        )
        return enabled and refresh_limit > 0, threshold_mbps * 1024 * 1024, duration_seconds, refresh_limit

    def _check_baidu_low_speed(
        self,
        row: Dict[str, Any],
        state: Dict[str, Any],
        *,
        threshold_bytes: int,
        duration_seconds: int,
        now: Optional[float] = None,
    ) -> Optional[BaiduNetdiskLowSpeedError]:
        current_time = float(now if now is not None else time.monotonic())
        downloaded = max(0, _safe_int(row.get("downloaded")))
        samples = state.setdefault("speed_samples", [])
        last_sample_at = float(state.get("last_sample_at") or 0)
        if not samples or current_time - last_sample_at >= 1:
            samples.append((current_time, downloaded))
            state["last_sample_at"] = current_time

        cutoff = current_time - max(1, int(duration_seconds))
        while len(samples) > 2 and float(samples[1][0]) <= cutoff:
            samples.pop(0)
        if len(samples) < 2:
            return None

        first_at, first_bytes = samples[0]
        window_seconds = current_time - float(first_at)
        if window_seconds < duration_seconds:
            return None

        average_speed = max(0, int((downloaded - int(first_bytes)) / max(window_seconds, 1)))
        state["window_speed_bytes_per_sec"] = average_speed
        state["window_seconds"] = int(window_seconds)
        row["low_speed_window_bytes_per_sec"] = average_speed
        row["low_speed_window_seconds"] = int(window_seconds)
        if average_speed >= max(1, int(threshold_bytes)):
            return None
        return BaiduNetdiskLowSpeedError(average_speed, int(window_seconds), downloaded)

    def _baidu_pcs_go_upload_args(self, pcsgo_path: str, source_paths: List[str], remote_dir: str, conflict_policy: str) -> List[str]:
        max_parallel, max_upload_load = self._baidu_pcs_go_upload_limits()
        return [
            pcsgo_path,
            "upload",
            "-p",
            str(max_parallel),
            "-l",
            str(max_upload_load),
            "--policy",
            conflict_policy,
            *source_paths,
            remote_dir,
        ]

    async def _ensure_pcsgo_remote_dir(
        self,
        pcsgo_path: str,
        remote_dir: str,
        *,
        env: Dict[str, str],
        log_path: str,
        task,
        cancel_event: asyncio.Event,
    ) -> None:
        normalized = self._normalize_remote_dir(remote_dir)
        if normalized == "/":
            return
        current = ""
        for part in [part for part in normalized.split("/") if part]:
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                await self._run_baidu_pcs_go_command(
                    [pcsgo_path, "mkdir", current],
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cancel_event,
                    ignore_task_cancel=True,
                    max_runtime_seconds=30,
                )
            except BaiduNetdiskError as exc:
                text = self._sanitize_error(exc)
                if any(marker in text for marker in ("已存在", "存在", "file exists", "already exists")):
                    continue
                raise

    async def _download_share_item_via_temporary_transfer(
        self,
        task,
        staging_dir: str,
        target_path: str,
        row: Dict[str, Any],
        download_files: List[Dict[str, Any]],
        started: float,
        cancel_event: asyncio.Event,
    ) -> None:
        share_url = str(row.get("share_url") or "").strip()
        if not share_url:
            raise BaiduNetdiskError("百度分享下载缺少 share_url")
        pass_code = str(row.get("pass_code") or "").strip() or self._pass_code_from_share_url(share_url)
        cookie = self._share_download_cookie(row)
        expected_name = str(row.get("relative_path") or row.get("name") or "").strip()
        expected_size = _safe_int(row.get("total") or row.get("size"))
        moving_path = f"{target_path}.kikoerumanager-moving-{task.id}"
        pcsgo_path = self._resolve_baidu_pcs_go_path()
        work_root = os.path.join(get_config().storage.temp_path, "baidu_netdisk_pcsgo")
        os.makedirs(work_root, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix=f"{task.id}_", dir=work_root)
        savedir = os.path.join(work_dir, "download")
        os.makedirs(savedir, exist_ok=True)
        config_dir = os.path.join(work_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        env = os.environ.copy()
        env["BAIDUPCS_GO_CONFIG_DIR"] = config_dir
        log_path = os.path.join(work_dir, "baidupcs-go.log")
        remote_tmp_dir = self._remote_temporary_transfer_dir_for_row(task, row)
        remote_tmp_created = False
        try:
            task.update_progress(max(2, task.progress), "准备百度网盘临时转存下载")
            self._write_baidu_pcsgo_cookie_config(config_dir, cookie, workdir="/")
            for command in self._baidu_pcs_go_download_config_commands(pcsgo_path, savedir):
                await self._run_baidu_pcs_go_command(
                    command,
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cancel_event,
                )
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "cd", "/"],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
            )
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "mkdir", remote_tmp_dir],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
            )
            remote_tmp_created = True
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "cd", remote_tmp_dir],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
            )
            task.update_progress(max(2, task.progress), "已创建百度网盘临时目录，开始转存")
            await self._check_task_active(task, cancel_event)
            await self._transfer_share_item_with_retry(
                task,
                row,
                cookie,
                remote_tmp_dir,
                share_url=share_url,
                pass_code=pass_code,
                download_files=download_files,
                started=started,
                cancel_event=cancel_event,
                confirm_transferred=lambda: self._confirm_remote_temporary_transfer_file(
                    pcsgo_path,
                    remote_tmp_dir,
                    expected_name,
                    expected_size,
                    row=row,
                    cookie=cookie,
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cancel_event,
                ),
            )
            self._append_log(task, f"百度网盘分享文件已转存到临时目录 {remote_tmp_dir}", "info")
            max_parallel, _max_download_load = self._baidu_pcs_go_download_limits()
            max_download_load = self._baidu_global_download_limit()
            self._append_log(
                task,
                f"BaiduPCS-Go 高速下载参数：线程 {max_parallel}，全局同时文件 {max_download_load}，模式 locate，不限速",
                "info",
            )
            task.update_progress(max(2, task.progress), "百度网盘转存完成，开始高速下载")
            low_speed_enabled, low_speed_threshold, low_speed_duration, refresh_limit = (
                self._baidu_low_speed_refresh_policy(row)
            )
            row.update({
                "link_refresh_attempt": 0,
                "link_refresh_limit": refresh_limit if low_speed_enabled else 0,
                "link_refresh_status": "monitoring" if low_speed_enabled else "disabled",
                "low_speed_threshold_bytes_per_sec": low_speed_threshold if low_speed_enabled else 0,
                "low_speed_duration_seconds": low_speed_duration if low_speed_enabled else 0,
            })
            async with get_resource_budget_service().acquire("network_download", reason="baidu.pcsgo_download"):
                total_attempts = refresh_limit + 1 if low_speed_enabled else 1
                for attempt_index in range(total_attempts):
                    resume_checkpoint_bytes = max(0, _safe_int(row.get("checkpoint_bytes"))) if attempt_index > 0 else 0
                    progress_state = {
                        "last_emit_at": 0.0,
                        "last_log_at": 0.0,
                        "resume_checkpoint_bytes": resume_checkpoint_bytes,
                    }
                    low_speed_state: Dict[str, Any] = {}
                    should_monitor_low_speed = low_speed_enabled and attempt_index < refresh_limit
                    if attempt_index > 0:
                        checkpoint_bytes = max(0, _safe_int(row.get("downloaded")))
                        row.update({
                            "link_refresh_attempt": attempt_index,
                            "link_refresh_status": "resuming",
                            "checkpoint_bytes": checkpoint_bytes,
                        })
                        self._append_log(
                            task,
                            f"百度线路已刷新 {attempt_index}/{refresh_limit}，复用旧断点 "
                            f"{checkpoint_bytes / 1024 / 1024:.2f} MB 继续下载",
                            "info",
                        )
                    if low_speed_enabled and not should_monitor_low_speed and attempt_index >= refresh_limit:
                        row["link_refresh_status"] = "limit_reached"
                        self._append_log(
                            task,
                            f"百度线路刷新已达上限 {refresh_limit} 次，保留当前断点并继续下载",
                            "warning",
                        )
                    self._refresh_runtime(task, download_files, started=started, current=row)
                    try:
                        await self._run_baidu_pcs_go_command(
                            self._baidu_pcs_go_download_args(pcsgo_path, remote_tmp_dir, savedir),
                            env=env,
                            log_path=log_path,
                            task=task,
                            cancel_event=cancel_event,
                            heartbeat_message="BaiduPCS-Go 正在高速下载临时目录",
                            on_output=lambda line: self._update_pcsgo_transfer_progress(
                                task,
                                row,
                                download_files,
                                started,
                                line,
                                progress_state,
                            ),
                            abort_check=(
                                lambda: self._check_baidu_low_speed(
                                    row,
                                    low_speed_state,
                                    threshold_bytes=low_speed_threshold,
                                    duration_seconds=low_speed_duration,
                                )
                            ) if should_monitor_low_speed else None,
                        )
                        row["link_refresh_status"] = "completed"
                        break
                    except BaiduNetdiskLowSpeedError as exc:
                        refresh_number = attempt_index + 1
                        row.update({
                            "link_refresh_attempt": refresh_number,
                            "link_refresh_status": "refreshing",
                            "checkpoint_bytes": exc.checkpoint_bytes,
                            "low_speed_window_bytes_per_sec": exc.average_speed_bytes,
                            "low_speed_window_seconds": exc.window_seconds,
                            "speed_bytes_per_sec": 0,
                        })
                        task.current_step = f"持续低速，正在刷新百度线路 {refresh_number}/{refresh_limit}"
                        task.mark_changed("progress")
                        self._append_log(
                            task,
                            f"检测到持续低速：近 {exc.window_seconds} 秒平均 "
                            f"{exc.average_speed_bytes / 1024 / 1024:.2f} MB/s，"
                            f"保留 {exc.checkpoint_bytes / 1024 / 1024:.2f} MB 断点并刷新百度线路 "
                            f"{refresh_number}/{refresh_limit}",
                            "warning",
                        )
                        self._refresh_runtime(task, download_files, started=started, current=row)
                        await self._check_task_active(task, cancel_event)
            downloaded_path = self._find_baidu_pcs_go_downloaded_file(savedir, expected_name, expected_size)
            if not downloaded_path:
                tail = self._read_text_tail(log_path)
                raise BaiduNetdiskError(
                    f"BaiduPCS-Go 下载完成但未找到文件: {expected_name or 'download.bin'}"
                    + (f"；日志: {tail}" if tail else "")
                )
            await self._check_task_active(task, cancel_event)
            source_size = await asyncio.to_thread(os.path.getsize, downloaded_path)
            if expected_size > 0 and source_size != expected_size:
                raise BaiduNetdiskError(
                    f"BaiduPCS-Go 下载文件大小不一致: expected={expected_size} actual={source_size}"
                )

            await asyncio.to_thread(os.makedirs, os.path.dirname(target_path), exist_ok=True)
            if await asyncio.to_thread(os.path.isdir, target_path):
                await asyncio.to_thread(shutil.rmtree, target_path)
            if await asyncio.to_thread(os.path.exists, moving_path):
                if await asyncio.to_thread(os.path.isdir, moving_path):
                    await asyncio.to_thread(shutil.rmtree, moving_path)
                else:
                    await asyncio.to_thread(os.remove, moving_path)

            loop = asyncio.get_running_loop()
            publish_progress = {"last_at": 0.0}

            def apply_publish_progress(copied: int, total: int) -> None:
                now = time.monotonic()
                if copied < total and now - publish_progress["last_at"] < 0.75:
                    return
                publish_progress["last_at"] = now
                row["finalize_copied_bytes"] = max(0, int(copied or 0))
                row["finalize_total_bytes"] = max(0, int(total or 0))
                task.current_step = "百度网盘下载完成，正在发布文件"
                task.mark_changed("progress")
                self._refresh_runtime(task, download_files, started=started, current=row)

            def schedule_publish_progress(copied: int, total: int) -> None:
                loop.call_soon_threadsafe(apply_publish_progress, copied, total)

            async with get_resource_budget_service().acquire(
                "disk_io_local",
                reason="baidu.finalize_download",
            ):
                await move_path_efficient(
                    downloaded_path,
                    moving_path,
                    progress_cb=schedule_publish_progress,
                    cancel_check=lambda: task.is_cancelled() or cancel_event.is_set(),
                    progress_throttle_bytes=64 * 1024 * 1024,
                )
                final_size = await asyncio.to_thread(os.path.getsize, moving_path)
                if final_size != source_size:
                    raise BaiduNetdiskError(
                        f"百度网盘文件发布大小不一致: source={source_size} target={final_size}"
                    )
                await self._check_task_active(task, cancel_event)
                await asyncio.to_thread(os.replace, moving_path, target_path)

            row.update({
                "status": "completed",
                "progress": 100,
                "downloaded": final_size,
                "total": max(int(row.get("total") or 0), final_size),
                "size": max(int(row.get("size") or 0), final_size),
                "local_path": target_path,
                "speed_bytes_per_sec": 0,
                "finalize_copied_bytes": final_size,
                "finalize_total_bytes": final_size,
            })
            self._refresh_runtime(task, download_files, started=started, current=row)
        finally:
            if await asyncio.to_thread(os.path.exists, moving_path):
                if await asyncio.to_thread(os.path.isdir, moving_path):
                    await asyncio.to_thread(shutil.rmtree, moving_path, True)
                else:
                    await asyncio.to_thread(os.remove, moving_path)
            if remote_tmp_created:
                await self._cleanup_remote_temporary_transfer_dir(
                    pcsgo_path,
                    remote_tmp_dir,
                    env=env,
                    log_path=log_path,
                    task=task,
                    retry_delayed=str(row.get("status") or "") != "completed",
                )
            with contextlib.suppress(Exception):
                shutil.rmtree(work_dir, ignore_errors=True)

    async def _download_share_item_with_pcsgo(
        self,
        task,
        staging_dir: str,
        target_path: str,
        row: Dict[str, Any],
        download_files: List[Dict[str, Any]],
        started: float,
        cancel_event: asyncio.Event,
    ) -> None:
        await self._download_share_item_via_temporary_transfer(
            task,
            staging_dir,
            target_path,
            row,
            download_files,
            started,
            cancel_event,
        )

    def _remote_temporary_transfer_dir(self, task, row: Optional[Dict[str, Any]] = None) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_part = secrets.token_hex(3)
        return f"/km_{timestamp}_{random_part}"

    def _remote_temporary_transfer_dir_for_row(self, task, row: Dict[str, Any]) -> str:
        base_dir = self._remote_temporary_transfer_dir(task)
        suffix = ""
        if isinstance(row, dict) and "_remote_transfer_scope" in row:
            raw = str(row.get("fs_id") or row.get("relative_path") or row.get("name") or "").strip()
            if raw:
                digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:6]
                suffix = f"_{digest}"
        return f"{base_dir}{suffix}"

    def _is_safe_remote_temporary_transfer_dir(self, remote_tmp_dir: str) -> bool:
        return bool(re.fullmatch(r"/km_\d{8}_\d{6}_[0-9a-f]{6}(?:_[0-9a-f]{6})?", str(remote_tmp_dir or "").strip()))

    def _remote_cleanup_error_is_missing(self, exc: Exception) -> bool:
        text = self._sanitize_error(exc).lower()
        return any(fragment in text for fragment in (
            "not exist",
            "not found",
            "no such file",
            "不存在",
            "未找到",
            "没有找到",
        ))

    async def _confirm_remote_temporary_transfer_file(
        self,
        pcsgo_path: str,
        remote_tmp_dir: str,
        expected_name: str,
        expected_size: int,
        *,
        row: Optional[Dict[str, Any]] = None,
        cookie: str = "",
        env: Dict[str, str],
        log_path: str,
        task,
        cancel_event: asyncio.Event,
    ) -> bool:
        expected_base = os.path.basename(str(expected_name or "").replace("\\", "/").rstrip("/"))
        expected_bytes = max(0, int(expected_size or 0))
        if not expected_base or expected_bytes <= 0:
            return False
        if cookie:
            query = urlencode({
                "dir": remote_tmp_dir,
                "order": "name",
                "desc": "0",
                "showempty": "0",
                "web": "1",
                "page": "1",
                "num": "100",
                "channel": "chunlei",
                "app_id": "250528",
                "bdstoken": str((row or {}).get("bdstoken") or ""),
                "logid": self._make_web_logid(cookie),
                "clienttype": "0",
            })
            with contextlib.suppress(Exception):
                data = await self._fetch_json(
                    f"https://pan.baidu.com/api/list?{query}",
                    cookie,
                    timeout=20,
                    referer="https://pan.baidu.com/disk/home",
                    use_requests=True,
                )
                if _safe_int(data.get("errno", data.get("err_no", 0)), 0) == 0:
                    for item in list(data.get("list") or []):
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("server_filename") or item.get("name") or "").strip()
                        size = _safe_int(item.get("size") or item.get("size_bytes"))
                        if name == expected_base and size == expected_bytes:
                            return True
        output_lines: List[str] = []
        try:
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "ls", remote_tmp_dir],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
                on_output=output_lines.append,
                heartbeat_message="正在确认百度转存结果",
                max_runtime_seconds=30,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        for raw_line in output_lines:
            line = str(raw_line or "").strip()
            if expected_base not in line:
                continue
            size_text = line.replace(expected_base, " ")
            if re.search(rf"(?<!\d){expected_bytes}(?!\d)", size_text):
                return True
        return False

    async def _cleanup_remote_temporary_transfer_dir(
        self,
        pcsgo_path: str,
        remote_tmp_dir: str,
        *,
        env: Dict[str, str],
        log_path: str,
        task,
        retry_delayed: bool = False,
    ) -> None:
        if not self._is_safe_remote_temporary_transfer_dir(remote_tmp_dir):
            self._append_log(task, f"跳过异常百度网盘临时目录清理: {remote_tmp_dir}", "warning")
            return

        cleanup_error: Optional[Exception] = None
        cleanup_event = asyncio.Event()
        delays = (0, 2, 6) if retry_delayed else (0,)
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._run_baidu_pcs_go_command(
                    [pcsgo_path, "cd", "/"],
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cleanup_event,
                    ignore_task_cancel=True,
                )
                await self._run_baidu_pcs_go_command(
                    [pcsgo_path, "rm", remote_tmp_dir],
                    env=env,
                    log_path=log_path,
                    task=task,
                    cancel_event=cleanup_event,
                    ignore_task_cancel=True,
                )
                cleanup_error = None
                if attempt == 1:
                    self._append_log(task, f"已删除百度网盘临时转存目录 {remote_tmp_dir}", "info")
                else:
                    self._append_log(task, f"已复查并清理百度网盘临时转存目录 {remote_tmp_dir}", "info")
            except Exception as exc:
                if self._remote_cleanup_error_is_missing(exc):
                    cleanup_error = None
                    continue
                cleanup_error = exc
                self._append_log(
                    task,
                    f"百度网盘临时转存目录第 {attempt} 次清理失败 {remote_tmp_dir}: {self._sanitize_error(exc)}",
                    "warning",
                )

        if cleanup_error is not None:
            self._append_log(
                task,
                f"百度网盘临时转存目录清理失败，请手动删除 {remote_tmp_dir}: {self._sanitize_error(cleanup_error)}",
                "warning",
            )

    async def _transfer_share_item_by_web(
        self,
        row: Dict[str, Any],
        cookie: str,
        remote_tmp_dir: str,
        *,
        share_url: str,
        pass_code: str = "",
    ) -> Dict[str, Any]:
        fs_id = str(row.get("fs_id") or row.get("fsid") or "").strip()
        if not fs_id:
            raise BaiduNetdiskError("百度分享转存缺少 fs_id")
        shareid = str(row.get("share_numeric_id") or "").strip()
        share_uk = str(row.get("share_uk") or "").strip()
        randsk = str(row.get("randsk") or "").strip() or self._cookie_value(cookie, "BDCLND")
        bdstoken = str(row.get("bdstoken") or "").strip()
        shorturl = str(row.get("shorturl") or row.get("share_id") or "").strip()
        if shorturl and not shorturl.startswith("1"):
            shorturl = f"1{shorturl}"
        if (not shareid or not share_uk or not randsk) and shorturl:
            tokens = await self._fetch_share_page_tokens(shorturl, cookie, referer=share_url or "https://pan.baidu.com/disk/home")
            shareid = shareid or str(tokens.get("shareid") or tokens.get("share_id") or "").strip()
            share_uk = share_uk or str(tokens.get("share_uk") or tokens.get("uk") or "").strip()
            bdstoken = bdstoken or str(tokens.get("bdstoken") or "").strip()
            randsk = randsk or str(tokens.get("randsk") or "").strip()
        if pass_code and shorturl and not randsk:
            tokens = await self._fetch_share_page_tokens(shorturl, cookie, referer="https://pan.baidu.com/disk/home")
            verify_data = await self._verify_share_pass_code(shorturl, pass_code, tokens, cookie, share_url)
            errno = _safe_int(verify_data.get("errno", verify_data.get("err_no", 0)), 0)
            if errno:
                raise BaiduNetdiskError(self._baidu_api_error_message(verify_data, f"百度分享提取码验证失败 {errno}"))
            randsk = str(verify_data.get("randsk") or "").strip()
            if randsk:
                cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
        if not shareid or not share_uk:
            raise BaiduNetdiskError("百度分享转存缺少 shareid/share_uk")
        if not randsk:
            raise BaiduNetdiskError("百度分享转存缺少 randsk，请重新预览分享链接")

        try:
            fsid_value: Any = int(fs_id)
        except Exception:
            fsid_value = fs_id
        query_payload = {
            "shareid": shareid,
            "from": share_uk,
            "sekey": self._baidu_share_sekey(randsk),
            "channel": "chunlei",
            "web": "1",
            "app_id": "250528",
            "bdstoken": bdstoken,
            "logid": self._make_web_logid(cookie),
            "clienttype": "0",
            "dp-logid": self._make_dp_logid(),
            "ondup": "overwrite",
        }
        transfer_url = "https://pan.baidu.com/share/transfer?" + urlencode({
            key: value
            for key, value in query_payload.items()
            if value != ""
        })
        payload = {
            "fsidlist": json.dumps([fsid_value], ensure_ascii=False),
            "path": remote_tmp_dir,
        }
        referer = self._share_init_url(shorturl) if shorturl else (share_url or "https://pan.baidu.com/disk/home")
        data = await self._fetch_form_json(
            transfer_url,
            cookie,
            data=payload,
            referer=referer,
            timeout=60,
            use_requests=True,
        )
        errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
        info_rows = data.get("info") if isinstance(data.get("info"), list) else []
        item_errors = [
            self._baidu_api_error_message(item, f"转存项失败 {item.get('errno')}")
            for item in info_rows
            if isinstance(item, dict) and _safe_int(item.get("errno"), 0)
        ]
        if errno or item_errors:
            message = self._baidu_api_error_message(data, f"百度分享转存失败 {errno}")
            if item_errors:
                message = "；".join(item_errors) or message
            raise BaiduNetdiskError(message)
        return data

    async def _run_baidu_pcs_go_command(
        self,
        args: List[str],
        *,
        env: Dict[str, str],
        log_path: str,
        task,
        cancel_event: asyncio.Event,
        ignore_task_cancel: bool = False,
        on_output: Optional[Callable[[str], None]] = None,
        abort_check: Optional[Callable[[], Optional[Exception]]] = None,
        heartbeat_message: str = "",
        max_runtime_seconds: int = 0,
    ) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "ab") as log_file:
            proc = subprocess.Popen(
                args,
                cwd=str(self._repo_root()),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
            registered_process = False
            if not ignore_task_cancel and hasattr(task, "register_process"):
                task.register_process(proc)
                registered_process = True
            output_queue: queue.Queue[Optional[bytes]] = queue.Queue()
            reader = threading.Thread(
                target=self._read_process_output,
                args=(proc.stdout, output_queue),
                daemon=True,
            )
            reader.start()
            last_heartbeat_at = time.monotonic()
            command_started_at = time.monotonic()
            pending_output = b""
            command_output = bytearray()
            try:
                while True:
                    if not ignore_task_cancel:
                        await self._check_task_active(task, cancel_event)
                    while True:
                        try:
                            chunk = output_queue.get_nowait()
                        except queue.Empty:
                            break
                        if chunk is None:
                            continue
                        if not chunk:
                            continue
                        log_file.write(chunk)
                        log_file.flush()
                        command_output.extend(chunk)
                        if len(command_output) > 128 * 1024:
                            del command_output[:len(command_output) - 128 * 1024]
                        pending_output = self._consume_pcsgo_output_chunk(pending_output + chunk, on_output)
                        last_heartbeat_at = time.monotonic()
                    code = proc.poll()
                    if code is not None:
                        break
                    abort_error = abort_check() if abort_check else None
                    if abort_error is not None:
                        with contextlib.suppress(Exception):
                            proc.terminate()
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(proc.wait, timeout=5)
                        with contextlib.suppress(Exception):
                            proc.kill()
                        raise abort_error
                    if max_runtime_seconds and time.monotonic() - command_started_at >= max_runtime_seconds:
                        with contextlib.suppress(Exception):
                            proc.terminate()
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(proc.wait, timeout=5)
                        with contextlib.suppress(Exception):
                            proc.kill()
                        tail = self._sanitize_error(
                            self._decode_pcsgo_output(bytes(command_output)) or self._read_text_tail(log_path)
                        )
                        raise BaiduNetdiskError(
                            f"BaiduPCS-Go 命令执行超时 {max_runtime_seconds} 秒"
                            + (f": {tail}" if tail else "")
                        )
                    if heartbeat_message and time.monotonic() - last_heartbeat_at >= 15:
                        self._append_log(task, heartbeat_message, "info")
                        last_heartbeat_at = time.monotonic()
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    proc.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(proc.wait, timeout=5)
                with contextlib.suppress(Exception):
                    proc.kill()
                raise
            finally:
                if registered_process and hasattr(task, "unregister_process"):
                    task.unregister_process(proc)
                with contextlib.suppress(Exception):
                    reader.join(timeout=1)
            while True:
                try:
                    chunk = output_queue.get_nowait()
                except queue.Empty:
                    break
                if chunk:
                    log_file.write(chunk)
                    command_output.extend(chunk)
                    if len(command_output) > 128 * 1024:
                        del command_output[:len(command_output) - 128 * 1024]
                    pending_output = self._consume_pcsgo_output_chunk(pending_output + chunk, on_output)
            if pending_output and on_output:
                on_output(self._decode_pcsgo_output(pending_output))
        if proc.returncode != 0:
            tail = self._read_text_tail(log_path)
            raise BaiduNetdiskError(self._sanitize_error(tail or f"BaiduPCS-Go 返回退出码 {proc.returncode}"))
        failure_message = self._pcsgo_command_failure_message(self._decode_pcsgo_output(bytes(command_output)))
        if failure_message:
            raise BaiduNetdiskError(failure_message)

    def _read_process_output(self, stream, output_queue: "queue.Queue[Optional[bytes]]") -> None:
        try:
            read_available = getattr(stream, "read1", None)
            while True:
                if not stream:
                    chunk = b""
                elif read_available:
                    chunk = read_available(4096)
                else:
                    chunk = stream.read(1)
                if not chunk:
                    break
                output_queue.put(chunk)
        finally:
            output_queue.put(None)

    def _consume_pcsgo_output_chunk(self, data: bytes, on_output: Optional[Callable[[str], None]]) -> bytes:
        if not on_output:
            return b""
        normalized = data.replace(b"\r", b"\n")
        parts = normalized.split(b"\n")
        for part in parts[:-1]:
            line = self._decode_pcsgo_output(part).strip()
            if line:
                on_output(line)
        tail = parts[-1] if not data.endswith((b"\n", b"\r")) else b""
        if len(tail) > 4096:
            line = self._decode_pcsgo_output(tail).strip()
            if line:
                on_output(line)
            tail = b""
        return tail

    def _decode_pcsgo_output(self, data: bytes) -> str:
        for encoding in ("utf-8", "gb18030", "gbk"):
            try:
                return data.decode(encoding)
            except Exception:
                continue
        return data.decode("utf-8", errors="replace")

    def _pcsgo_command_failure_message(self, output: str) -> str:
        for raw_line in str(output or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith("warning:"):
                continue
            if any(marker in line for marker in ("失败", "错误", "异常")) or " error" in lowered or lowered.startswith("error"):
                return self._sanitize_error(line)
        return ""

    def _update_pcsgo_transfer_progress(
        self,
        task,
        row: Dict[str, Any],
        download_files: List[Dict[str, Any]],
        started: float,
        line: str,
        state: Dict[str, Any],
    ) -> None:
        text = str(line or "").strip()
        if not text:
            return
        now = time.monotonic()
        parsed_any = False

        progress_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if progress_match:
            progress = min(99, max(0, int(float(progress_match.group(1)))))
            if progress > int(row.get("progress") or 0):
                row["progress"] = progress
                parsed_any = True

        size_match = re.search(
            r"(?P<done>\d+(?:\.\d+)?)\s*(?P<done_unit>[KMGTPE]?i?B|B)\s*/\s*(?P<total>\d+(?:\.\d+)?)\s*(?P<total_unit>[KMGTPE]?i?B|B)",
            text,
            re.IGNORECASE,
        )
        if size_match:
            downloaded = self._parse_pcsgo_size(size_match.group("done"), size_match.group("done_unit"))
            total = self._parse_pcsgo_size(size_match.group("total"), size_match.group("total_unit"))
            effective_total = max(total, int(row.get("total") or row.get("size") or 0))
            resume_checkpoint = max(0, _safe_int(state.get("resume_checkpoint_bytes")))
            if resume_checkpoint and downloaded < resume_checkpoint:
                downloaded += resume_checkpoint
                if effective_total:
                    downloaded = min(effective_total, downloaded)
            if downloaded >= int(row.get("downloaded") or 0):
                row["downloaded"] = downloaded
            if total > int(row.get("total") or 0):
                row["total"] = total
                row["size"] = max(int(row.get("size") or 0), total)
            if effective_total > 0:
                row["progress"] = max(int(row.get("progress") or 0), min(99, int(downloaded / effective_total * 100)))
            parsed_any = True

        speed_match = re.search(
            r"(?P<speed>\d+(?:\.\d+)?)\s*(?P<unit>[KMGTPE]?i?B|B)\s*/\s*s",
            text,
            re.IGNORECASE,
        )
        if speed_match:
            row["speed_bytes_per_sec"] = self._parse_pcsgo_size(speed_match.group("speed"), speed_match.group("unit"))
            parsed_any = True

        if parsed_any and str(row.get("link_refresh_status") or "") == "resuming":
            row["link_refresh_status"] = "monitoring"

        if "下载" in text or "转存" in text or "秒传" in text:
            if now - float(state.get("last_log_at") or 0) >= 12:
                self._append_log(task, self._compact_pcsgo_log_line(text), "info")
                state["last_log_at"] = now

        if parsed_any and now - float(state.get("last_emit_at") or 0) >= 0.8:
            self._refresh_runtime(task, download_files, started=started, current=row)
            state["last_emit_at"] = now

    def _build_upload_file_rows(self, source_paths: List[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for source_path in source_paths:
            abs_path = os.path.abspath(source_path)
            base_name = os.path.basename(abs_path.rstrip("\\/")) or abs_path
            if os.path.isfile(abs_path):
                size = os.path.getsize(abs_path)
                rows.append({
                    "id": hashlib.sha1(abs_path.encode("utf-8", errors="ignore")).hexdigest()[:16],
                    "name": base_name,
                    "relative_path": base_name,
                    "source_path": abs_path,
                    "is_directory": False,
                    "size": size,
                    "total": size,
                    "uploaded": 0,
                    "progress": 0,
                    "status": "pending",
                })
                continue
            if os.path.isdir(abs_path):
                has_file = False
                for dirpath, _dirnames, filenames in os.walk(abs_path):
                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)
                        try:
                            size = os.path.getsize(full_path)
                        except OSError:
                            size = 0
                        rel = os.path.relpath(full_path, abs_path).replace("\\", "/")
                        upload_rel = f"{base_name}/{rel}" if rel and rel != "." else base_name
                        rows.append({
                            "id": hashlib.sha1(full_path.encode("utf-8", errors="ignore")).hexdigest()[:16],
                            "name": filename,
                            "relative_path": upload_rel,
                            "source_path": full_path,
                            "source_root": abs_path,
                            "is_directory": False,
                            "size": size,
                            "total": size,
                            "uploaded": 0,
                            "progress": 0,
                            "status": "pending",
                        })
                        has_file = True
                if not has_file:
                    rows.append({
                        "id": hashlib.sha1(abs_path.encode("utf-8", errors="ignore")).hexdigest()[:16],
                        "name": base_name,
                        "relative_path": base_name,
                        "source_path": abs_path,
                        "is_directory": True,
                        "size": 0,
                        "total": 0,
                        "uploaded": 0,
                        "progress": 0,
                        "status": "pending",
                    })
        return rows

    def _update_pcsgo_upload_progress(self, task, upload_files: List[Dict[str, Any]], started: float, line: str) -> None:
        text = str(line or "").strip()
        if not text:
            return
        now = time.monotonic()
        state = task.task_metadata.setdefault("_baidu_upload_progress_state", {})
        parsed_any = False
        runtime = dict(task.task_metadata.get("upload_runtime") or {})
        total_bytes = int(runtime.get("total_bytes") or sum(int(row.get("size") or 0) for row in upload_files))
        transferred = int(runtime.get("transferred_bytes") or 0)

        progress_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if progress_match:
            progress = min(99, max(0, int(float(progress_match.group(1)))))
            if total_bytes > 0:
                transferred = max(transferred, int(total_bytes * progress / 100))
            task.progress = max(int(task.progress or 0), max(2, progress))
            parsed_any = True

        size_match = re.search(
            r"(?P<done>\d+(?:\.\d+)?)\s*(?P<done_unit>[KMGTPE]?i?B|B)\s*/\s*(?P<total>\d+(?:\.\d+)?)\s*(?P<total_unit>[KMGTPE]?i?B|B)",
            text,
            re.IGNORECASE,
        )
        if size_match:
            transferred = max(transferred, self._parse_pcsgo_size(size_match.group("done"), size_match.group("done_unit")))
            parsed_total = self._parse_pcsgo_size(size_match.group("total"), size_match.group("total_unit"))
            if parsed_total > total_bytes:
                total_bytes = parsed_total
            parsed_any = True

        speed = int(runtime.get("speed_bytes_per_sec") or 0)
        speed_match = re.search(
            r"(?P<speed>\d+(?:\.\d+)?)\s*(?P<unit>[KMGTPE]?i?B|B)\s*/\s*s",
            text,
            re.IGNORECASE,
        )
        if speed_match:
            speed = self._parse_pcsgo_size(speed_match.group("speed"), speed_match.group("unit"))
            parsed_any = True

        current_file = ""
        for row in upload_files:
            name = str(row.get("name") or "")
            rel = str(row.get("relative_path") or "")
            if name and (name in text or rel in text):
                current_file = name
                row["status"] = "uploading"
                break

        if any(marker in text for marker in ("上传", "秒传", "文件", "目录")):
            if now - float(state.get("last_log_at") or 0) >= 12:
                self._append_log(task, self._compact_pcsgo_log_line(text), "info")
                state["last_log_at"] = now

        if parsed_any and now - float(state.get("last_emit_at") or 0) >= 0.8:
            self._refresh_upload_runtime(
                task,
                upload_files,
                started=started,
                current={"name": current_file} if current_file else {},
                status="uploading",
                transferred_bytes=transferred,
                total_bytes=total_bytes,
                speed_bytes_per_sec=speed,
            )
            state["last_emit_at"] = now

    def _refresh_upload_runtime(
        self,
        task,
        upload_files: List[Dict[str, Any]],
        *,
        started: float,
        current: Dict[str, Any],
        status: str = "uploading",
        transferred_bytes: int = 0,
        total_bytes: int = 0,
        speed_bytes_per_sec: int = 0,
    ) -> None:
        completed = [row for row in upload_files if str(row.get("status") or "") == "completed"]
        failed = [row for row in upload_files if str(row.get("status") or "") == "failed"]
        runtime = dict(task.task_metadata.get("upload_runtime") or {})
        total = int(total_bytes or runtime.get("total_bytes") or sum(int(row.get("size") or 0) for row in upload_files))
        transferred = int(transferred_bytes or runtime.get("transferred_bytes") or sum(int(row.get("uploaded") or 0) for row in upload_files))
        elapsed = max(time.monotonic() - started, 1)
        speed = int(speed_bytes_per_sec or runtime.get("speed_bytes_per_sec") or (transferred / elapsed if transferred else 0))
        runtime.update({
            "status": status,
            "total_files": len(upload_files),
            "completed_files": len(completed),
            "failed_files": len(failed),
            "transferred_bytes": transferred,
            "total_bytes": total,
            "speed_bytes_per_sec": speed,
            "current_file_name": str(current.get("name") or runtime.get("current_file_name") or ""),
            "current_relative_path": str(current.get("relative_path") or ""),
            "speed_label": "百度网盘上传",
        })
        task.task_metadata["upload_runtime"] = runtime
        task.task_metadata["upload_files"] = upload_files
        if total > 0 and transferred > 0:
            task.progress = max(int(task.progress or 0), min(99, int(transferred / total * 100)))
        task.current_step = runtime["current_file_name"] or f"百度网盘上传中 {len(completed)}/{len(upload_files)}"

    def _cleanup_uploaded_local_archives(self, source_paths: List[str], metadata: Dict[str, Any]) -> None:
        allowed = set(str(path) for path in list(metadata.get("cleanup_allowed_paths") or []))
        archive_exts = {".zip", ".7z"}
        for path in source_paths:
            if allowed and path not in allowed:
                continue
            if os.path.isfile(path) and Path(path).suffix.lower() in archive_exts:
                with contextlib.suppress(Exception):
                    os.remove(path)

    def _parse_pcsgo_size(self, value: Any, unit: Any) -> int:
        try:
            number = float(str(value or "0").strip())
        except Exception:
            return 0
        normalized = str(unit or "B").strip().lower().replace("ib", "b")
        multipliers = {
            "b": 1,
            "kb": 1024,
            "mb": 1024 ** 2,
            "gb": 1024 ** 3,
            "tb": 1024 ** 4,
            "pb": 1024 ** 5,
            "eb": 1024 ** 6,
        }
        return int(number * multipliers.get(normalized, 1))

    def _compact_pcsgo_log_line(self, line: str) -> str:
        text = re.sub(r"\s+", " ", str(line or "")).strip()
        return f"BaiduPCS-Go: {text[:180]}"

    def _find_baidu_pcs_go_downloaded_file(self, savedir: str, expected_name: str, expected_size: int = 0) -> str:
        if not os.path.isdir(savedir):
            return ""
        expected_rel = str(expected_name or "").replace("\\", "/").strip("/")
        expected_base = os.path.basename(expected_rel)
        scored: List[tuple[int, float, str]] = []
        for dirpath, _dirnames, filenames in os.walk(savedir):
            for filename in filenames:
                if filename.endswith((".aria2", ".BaiduPCS-Go-downloading")):
                    continue
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, savedir).replace("\\", "/")
                score = 0
                if expected_rel and (rel_path == expected_rel or rel_path.endswith(f"/{expected_rel}")):
                    score += 100
                if expected_base and filename == expected_base:
                    score += 40
                try:
                    file_size = os.path.getsize(full_path)
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    file_size = 0
                    mtime = 0.0
                if expected_size and file_size == expected_size:
                    score += 30
                score += min(file_size // (1024 * 1024), 20)
                scored.append((score, mtime, full_path))
        if not scored:
            return ""
        scored.sort(key=lambda item: (item[0], item[1]))
        return scored[-1][2]

    def _read_text_tail(self, path: str, limit: int = 3000) -> str:
        if not path or not os.path.exists(path):
            return ""
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return ""
        for encoding in ("utf-8", "gb18030", "gbk"):
            try:
                text = data.decode(encoding)
                break
            except Exception:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
        return text.strip()[-limit:]

    async def _check_task_active(self, task, cancel_event: asyncio.Event) -> None:
        if task.is_cancelled() or cancel_event.is_set():
            raise asyncio.CancelledError()
        pause_event = getattr(task, "_pause_event", None)
        if pause_event is not None and not pause_event.is_set():
            cancel_event.set()
            raise asyncio.CancelledError()

    def _baidu_api_error_message(self, payload: Any, fallback: str) -> str:
        if isinstance(payload, dict):
            for key in ("errmsg", "error_msg", "show_msg", "msg", "message"):
                text = str(payload.get(key) or "").strip()
                if text:
                    return text
            errno = payload.get("errno", payload.get("err_no", ""))
            if errno not in ("", None):
                return f"{fallback}: {errno}"
        return fallback

    def _refresh_runtime(self, task, download_files: List[Dict[str, Any]], *, started: float, current: Dict[str, Any]) -> None:
        completed = [row for row in download_files if str(row.get("status") or "") == "completed"]
        failed = [row for row in download_files if str(row.get("status") or "") == "failed"]
        active = [row for row in download_files if str(row.get("status") or "") == "downloading"]
        total_bytes = sum(int(row.get("total") or row.get("size") or 0) for row in download_files)
        transferred = sum(int(row.get("downloaded") or (row.get("size") if row.get("status") == "completed" else 0) or 0) for row in download_files)
        speed = sum(int(row.get("speed_bytes_per_sec") or 0) for row in active)
        previous_runtime = dict(task.task_metadata.get("download_runtime") or {})
        runtime_row = current if isinstance(current, dict) and current else (active[0] if active else {})
        link_refresh_status = str(runtime_row.get("link_refresh_status") or previous_runtime.get("link_refresh_status") or "")
        transfer_status = str(runtime_row.get("transfer_status") or previous_runtime.get("transfer_status") or "")
        if transfer_status in {"waiting", "transferring", "retrying"}:
            runtime_status = transfer_status
        else:
            runtime_status = "refreshing" if link_refresh_status in {"refreshing", "resuming"} else "downloading"
        runtime = {
            "status": runtime_status,
            "total_files": len(download_files),
            "completed_files": len(completed),
            "failed_files": len(failed),
            "active_file_count": len(active),
            "active_file_limit": int(previous_runtime.get("active_file_limit") or 0),
            "transferred_bytes": transferred,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": speed,
            "current_file_name": str(runtime_row.get("name") or ""),
            "current_relative_path": str(runtime_row.get("relative_path") or ""),
            "elapsed_seconds": int(time.monotonic() - started),
            "speed_label": "百度网盘 SVIP 高速" if self._is_svip() else "百度网盘下载",
            "link_refresh_attempt": _safe_int(runtime_row.get("link_refresh_attempt", previous_runtime.get("link_refresh_attempt"))),
            "link_refresh_limit": _safe_int(runtime_row.get("link_refresh_limit", previous_runtime.get("link_refresh_limit"))),
            "link_refresh_status": link_refresh_status,
            "transfer_status": transfer_status,
            "transfer_attempt": _safe_int(runtime_row.get("transfer_attempt", previous_runtime.get("transfer_attempt"))),
            "transfer_retry_limit": _safe_int(
                runtime_row.get("transfer_retry_limit", previous_runtime.get("transfer_retry_limit"))
            ),
            "transfer_next_retry_seconds": _safe_int(
                runtime_row.get("transfer_next_retry_seconds", previous_runtime.get("transfer_next_retry_seconds"))
            ),
            "checkpoint_bytes": _safe_int(runtime_row.get("checkpoint_bytes", previous_runtime.get("checkpoint_bytes"))),
            "low_speed_window_bytes_per_sec": _safe_int(
                runtime_row.get("low_speed_window_bytes_per_sec", previous_runtime.get("low_speed_window_bytes_per_sec"))
            ),
            "low_speed_window_seconds": _safe_int(
                runtime_row.get("low_speed_window_seconds", previous_runtime.get("low_speed_window_seconds"))
            ),
            "low_speed_threshold_bytes_per_sec": _safe_int(
                runtime_row.get("low_speed_threshold_bytes_per_sec", previous_runtime.get("low_speed_threshold_bytes_per_sec"))
            ),
            "low_speed_duration_seconds": _safe_int(
                runtime_row.get("low_speed_duration_seconds", previous_runtime.get("low_speed_duration_seconds"))
            ),
        }
        task.task_metadata["download_files"] = download_files
        task.task_metadata["download_runtime"] = runtime
        if total_bytes:
            task.progress = max(task.progress, min(99, int(transferred / max(total_bytes, 1) * 100)))
        else:
            unit = 90 / max(len(download_files), 1)
            task.progress = max(task.progress, min(95, int(2 + len(completed) * unit + sum(int(row.get("progress") or 0) for row in active) / 100 * unit)))
        if runtime_status == "waiting":
            task.current_step = f"等待百度转存槽：{runtime['current_file_name'] or '未命名文件'}"
        elif runtime_status == "transferring":
            task.current_step = f"正在百度转存：{runtime['current_file_name'] or '未命名文件'}"
        elif runtime_status == "retrying":
            task.current_step = (
                f"百度转存连接异常，等待重试 {runtime['transfer_attempt']}/{runtime['transfer_retry_limit']}"
            )
        elif runtime_status == "refreshing":
            task.current_step = (
                f"持续低速，正在刷新百度线路 {runtime['link_refresh_attempt']}/{runtime['link_refresh_limit']}"
            )
        else:
            task.current_step = runtime["current_file_name"] or f"百度网盘下载中 {len(completed)}/{len(download_files)}"
        task.mark_changed("progress")

    def _append_log(self, task, message: str, level: str = "info") -> None:
        logs = list((task.task_metadata or {}).get("progress_log") or [])
        logs.append({
            "time": _now_iso(),
            "ts": datetime.now().strftime("%H:%M:%S"),
            "progress": int(getattr(task, "progress", 0) or 0),
            "message": str(message or "")[:600],
            "level": level,
        })
        task.task_metadata["progress_log"] = logs[-120:]

    def _finalize_output(self, staging_dir: str, final_dir: str, conflict_policy: str, item_count: int) -> str:
        os.makedirs(os.path.dirname(final_dir), exist_ok=True)
        if conflict_policy == "rename":
            final_dir = self._resolve_final_dir_for_policy(final_dir, "rename")
        elif conflict_policy == "skip" and os.path.exists(final_dir):
            return final_dir
        else:
            os.makedirs(final_dir, exist_ok=True)
        entries = [
            os.path.join(staging_dir, name)
            for name in os.listdir(staging_dir)
            if name not in {".", ".."} and not name.endswith(".aria2")
        ] if os.path.isdir(staging_dir) else []
        if len(entries) == 1 and os.path.isdir(entries[0]) and not os.listdir(final_dir):
            if os.path.exists(final_dir):
                with contextlib.suppress(OSError):
                    os.rmdir(final_dir)
            try:
                shutil.move(entries[0], final_dir)
                return final_dir
            except Exception:
                os.makedirs(final_dir, exist_ok=True)
        os.makedirs(final_dir, exist_ok=True)
        for entry in entries:
            name = os.path.basename(entry.rstrip("\\/"))
            target = os.path.join(final_dir, name)
            if os.path.exists(target):
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
            shutil.move(entry, target)
        return final_dir

    async def _finalize_cancelled_download_task(
        self,
        task,
        download_files: List[Dict[str, Any]],
        *,
        started: float,
        staging_dir: str,
        download_root: str,
    ) -> None:
        for row in download_files:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "") != "completed":
                row["status"] = "cancelled"
                row["failure_reason"] = "用户取消"
            row["speed_bytes_per_sec"] = 0

        completed = [row for row in download_files if str(row.get("status") or "") == "completed"]
        failed = [row for row in download_files if str(row.get("status") or "") == "failed"]
        total_bytes = sum(int(row.get("total") or row.get("size") or 0) for row in download_files)
        transferred = sum(
            int(row.get("downloaded") or (row.get("size") if row.get("status") == "completed" else 0) or 0)
            for row in download_files
        )
        runtime = dict(task.task_metadata.get("download_runtime") or {})
        runtime.update({
            "status": "cancelled",
            "total_files": len(download_files),
            "completed_files": len(completed),
            "failed_files": len(failed),
            "active_file_count": 0,
            "transferred_bytes": transferred,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": 0,
            "current_file_name": "",
            "current_relative_path": "",
            "elapsed_seconds": int(time.monotonic() - started),
            "speed_label": "百度网盘 SVIP 高速" if self._is_svip() else "百度网盘下载",
        })
        task.task_metadata["download_files"] = download_files
        task.task_metadata["download_runtime"] = runtime
        task.task_metadata["failed_files"] = failed
        task.task_metadata["cancel_reason"] = "用户取消"
        task.task_metadata["failure_reason"] = ""
        task.task_metadata["output_finalize_status"] = "cancelled"
        self._append_log(task, "百度网盘下载已取消，清理本地临时下载目录", "info")
        task.task_metadata["staging_cleanup"] = await asyncio.to_thread(
            self._cleanup_completed_staging_dir,
            task,
            staging_dir,
            download_root,
        )
        task.current_step = "已取消"
        task.mark_changed("cancelled")

    def _cleanup_completed_staging_dir(self, task, staging_dir: str, download_root: str) -> Dict[str, Any]:
        staging = os.path.abspath(os.path.normpath(str(staging_dir or "")))
        root = os.path.abspath(os.path.normpath(str(download_root or "")))
        result = {
            "success": False,
            "cleaned": False,
            "path": staging,
            "reason": "",
        }
        if not staging or not root:
            result["reason"] = "missing_path"
            return result
        staging_parent = os.path.abspath(os.path.normpath(os.path.join(root, ".baidu-netdisk-staging")))
        try:
            common = os.path.commonpath([staging_parent, staging])
        except ValueError:
            result["reason"] = "outside_staging_parent"
            return result
        if common != staging_parent or staging == staging_parent:
            result["reason"] = "outside_staging_parent"
            return result
        task_id = str(getattr(task, "id", "") or "").strip()
        basename = os.path.basename(staging)
        if task_id and basename != task_id and task_id[:8] not in basename:
            result["reason"] = "not_task_staging_dir"
            return result
        if not os.path.exists(staging):
            result.update({"success": True, "cleaned": False, "reason": "missing"})
            return result
        try:
            shutil.rmtree(staging)
            result.update({"success": True, "cleaned": True, "reason": "removed"})
            with contextlib.suppress(OSError):
                os.rmdir(staging_parent)
            self._append_log(task, "已清理百度网盘本地临时下载目录", "info")
        except Exception as exc:
            result["reason"] = self._sanitize_error(exc)
            self._append_log(task, f"百度网盘本地临时下载目录清理失败: {result['reason']}", "warning")
        return result

    def _directory_size(self, path: str) -> int:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        if os.path.isdir(path):
            for dirpath, _dirnames, filenames in os.walk(path):
                for filename in filenames:
                    with contextlib.suppress(OSError):
                        total += os.path.getsize(os.path.join(dirpath, filename))
        return total

    def _first_failure_reason(self, rows: List[Dict[str, Any]]) -> str:
        for row in rows or []:
            reason = str((row or {}).get("failure_reason") or "").strip()
            if reason:
                return reason
        return ""

    def _sanitize_error(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        text = re.sub(r"(BDUSS(?:_BFESS)?=)[^;\s]+", r"\1***", text)
        text = re.sub(r"(STOKEN=)[^;\s]+", r"\1***", text)
        text = re.sub(r"(BDCLND=)[^;\s]+", r"\1***", text)
        text = re.sub(
            r"(?i)([?&](?:sekey|logid|dp-logid|randsk|bdstoken)=)[^&\s]+",
            r"\1***",
            text,
        )
        text = re.sub(
            r"(?i)\b(sekey|logid|dp-logid|randsk|bdstoken)\s*[:=]\s*([^&,;\s}]+)",
            lambda match: f"{match.group(1)}=***",
            text,
        )
        return text

    async def cancel_task(self, task_id: str) -> None:
        event = self._task_cancel_events.get(task_id)
        if event:
            event.set()

    async def reset_task_for_retry(
        self,
        task,
        *,
        retry_items: Optional[List[Dict[str, Any]]] = None,
        retry_keys: Optional[List[str]] = None,
    ) -> None:
        from .task_engine import TaskStatus

        if retry_items is None or retry_keys is None:
            retry_items, retry_keys = self.build_retry_selection_for_task(task)
        if not retry_items:
            raise BaiduNetdiskError("没有找到可重试的百度网盘失败项")

        task.task_metadata["raw_selected_items"] = [dict(item) for item in retry_items if isinstance(item, dict)]
        task.task_metadata["selected_items"] = [
            sanitize_baidu_netdisk_item(item)
            for item in retry_items
            if isinstance(item, dict)
        ]
        task.task_metadata["selected_keys"] = list(retry_keys or [])
        task.task_metadata["retry_target_count"] = len(retry_items)
        if str(task.task_metadata.get("download_batch_folder_name") or "").strip():
            task.task_metadata["retry_original_conflict_policy"] = task.task_metadata.get("conflict_policy", "")
            task.task_metadata["conflict_policy"] = "resume"
        task.task_metadata["download_files"] = []
        task.task_metadata["download_runtime"] = {}
        task.task_metadata["failed_files"] = []
        task.task_metadata["performance_metrics"] = {}
        task.task_metadata["failure_reason"] = ""
        task.task_metadata["output_finalize_status"] = "pending"
        task.task_metadata["retry_count"] = int(task.task_metadata.get("retry_count") or 0) + 1
        task.status = TaskStatus.PENDING
        task.progress = 0
        task.current_step = "等待重新下载"
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task._cancelled = False
        task._pause_event.set()
        with task._proc_lock:
            task._active_processes.clear()
            task._stop_reason = None


_baidu_netdisk_service: Optional[BaiduNetdiskService] = None


def get_baidu_netdisk_service() -> BaiduNetdiskService:
    global _baidu_netdisk_service
    if _baidu_netdisk_service is None:
        _baidu_netdisk_service = BaiduNetdiskService()
    return _baidu_netdisk_service
