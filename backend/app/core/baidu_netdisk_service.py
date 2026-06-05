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
import sqlite3
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

import aiohttp

from ..config.settings import get_config, save_config
from .http_download_service import sanitize_http_download_item

logger = logging.getLogger(__name__)

BAIDU_NETDISK_LABEL = "百度网盘"
BAIDU_NETDISK_PLATFORM = "baidu_netdisk"
BAIDU_OFFICIAL_LOGIN_URL = "https://pan.baidu.com/"
_BAIDU_WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_ILLEGAL_WINDOWS_CHARS = set('<>:"\\|?*')
_BAIDU_COOKIE_PRIORITY = [
    "BDUSS",
    "BDUSS_BFESS",
    "STOKEN",
    "PTOKEN",
    "BAIDUID",
    "BAIDUID_BFESS",
    "PANPSC",
    "BDCLND",
]
_BAIDU_RAW_PREVIEW_CACHE_TTL_SECONDS = 10 * 60


class BaiduNetdiskError(ValueError):
    """百度网盘下载的可预期业务错误。"""


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
    out.pop("cookie", None)
    out.pop("bdstoken", None)
    out.pop("randsk", None)
    out.pop("share_sign", None)
    out.pop("share_timestamp", None)
    out.pop("share_numeric_id", None)
    out.pop("share_uk", None)
    out.pop("shorturl", None)
    out.pop("pass_code", None)
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
    for key in ("download_files", "failed_files", "downloaded_files"):
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
    """百度网盘分享下载服务，通过 BaiduPCS-Go 临时转存后下载。"""

    def __init__(self):
        self._task_cancel_events: Dict[str, asyncio.Event] = {}
        self._official_login_session: Optional[Dict[str, Any]] = None
        self._raw_preview_cache: Dict[str, Dict[str, Any]] = {}

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
        if not keys:
            return preview
        out = dict(preview or {})
        items = [
            item for item in list(out.get("items") or [])
            if isinstance(item, dict) and self._selection_key(item) in keys
        ]
        out["items"] = items
        ok_count = sum(1 for item in items if item.get("ok"))
        out["ok_count"] = ok_count
        out["failed_count"] = len(items) - ok_count
        out["success"] = ok_count > 0
        out["selected_count"] = len(items)
        return out

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
        last_index: Optional[int] = None
        for row in rows:
            if self._looks_like_baidu_url(row):
                parsed = self._parse_share_url(row)
                shares.append(parsed)
                last_index = len(shares) - 1
                continue
            code = self._parse_pass_code_text(row)
            if code and last_index is not None and not shares[last_index].get("pass_code"):
                shares[last_index]["pass_code"] = code
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
        if pass_code and "pwd=" not in cleaned and "passcode=" not in cleaned and "pass_code=" not in cleaned:
            cleaned = f"{cleaned}{'&' if '?' in cleaned else '?'}pwd={quote(pass_code)}"
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
        missing_code = bool(detail.get("requires_pass_code")) or (
            not detail_files
            and self._likely_requires_pass_code(share)
            and not share.get("pass_code")
        )
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
            "filename": title,
            "name": title,
            "relative_path": "/".join(part for part in [self._safe_subdir(target_subdir), title] if part),
            "size_bytes": detail_total_size,
            "size": detail_total_size,
            "content_type": "application/x-baidu-netdisk-share",
            "resumable": True,
            "is_dir": True,
            "source_label": BAIDU_NETDISK_LABEL,
            "preview_files": detail_files[:8],
            "preview_summary": preview_summary,
            "preview_file_count": detail_file_count,
            "preview_folder_count": detail_folder_count,
        }
        item["selection_key"] = self._selection_key(item)
        if missing_code:
            item["reason"] = "需要输入提取码"
            item["warning"] = "缺提取码，补充后重新预览"
        elif detail.get("warning"):
            item["warning"] = str(detail.get("warning") or "").strip()
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
        if any(fragment in text for fragment in ("提取码", "访问码", "密码", "密码错误", "需要输入")):
            return text
        if any(fragment in text for fragment in ("提取", "验证失败", "校验失败")):
            return "需要输入提取码"
        if any(fragment in lowered for fragment in ("verify", "pass", "pwd", "randsk")):
            return "需要输入提取码"
        return text

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
        items = []
        for share in shares:
            detail: Dict[str, Any] = {}
            try:
                detail = await self._fetch_share_detail(share)
            except Exception as exc:
                logger.info("百度网盘分享预览详情读取失败: %s", exc)
                detail = {"warning": f"未能读取分享文件列表: {self._share_preview_warning(exc)}"}
            items.append(self._preview_item_from_share(share, target_subdir, output_folder_name, detail))
        ok_count = sum(1 for item in items if item.get("ok"))
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
            "items": items,
            "source_items": list(items),
            "selected_keys": [item["selection_key"] for item in items if item.get("ok")],
            "ok_count": ok_count,
            "failed_count": len(items) - ok_count,
            "needs_pass_code_count": len([item for item in items if item.get("requires_pass_code")]),
            "svip_speed": self._is_svip(),
            "download_root": self._download_root(),
            "target_subdir": target_subdir,
            "output_folder_name": output_folder_name,
            "conflict_policy": conflict_policy or str(getattr(self._config(), "conflict_policy", "resume") or "resume"),
            "raw_preview_cache_key": cache_key,
        }
        self._cache_raw_preview(cache_key, preview)
        return preview

    async def _fetch_share_detail(self, share: Dict[str, str]) -> Dict[str, Any]:
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
        init_url = f"https://pan.baidu.com/share/init?surl={feature[1:]}"
        tokens = await self._fetch_share_page_tokens(feature, cookie, referer=init_url if pass_code else "https://pan.baidu.com/disk/home")
        if pass_code:
            verify_data = await self._verify_share_pass_code(feature, pass_code, tokens, cookie, init_url)
            verify_errno = _safe_int(verify_data.get("errno", verify_data.get("err_no", 0)), 0)
            if verify_errno:
                return {
                    "title": share.get("title") or "百度网盘分享",
                    "files": [],
                    "file_count": 0,
                    "folder_count": 0,
                    "total_size": 0,
                    "requires_pass_code": True,
                    "warning": self._share_preview_warning(verify_data.get("errmsg") or verify_data.get("show_msg") or verify_data.get("error_msg") or "提取码错误"),
                }
            randsk = str(verify_data.get("randsk") or "").strip()
            if randsk:
                cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
                tokens["randsk"] = randsk
        data = await self._fetch_share_list_payload(tokens, cookie, share_url, feature)
        errno = _safe_int(data.get("errno", data.get("err_no", 0)), 0)
        if errno:
            warning = self._share_preview_warning(data.get("errmsg") or data.get("error_msg") or data.get("show_msg") or f"分享列表读取失败 {errno}")
            return {
                "title": share.get("title") or "百度网盘分享",
                "files": [],
                "file_count": 0,
                "folder_count": 0,
                "total_size": 0,
                "requires_pass_code": bool(not pass_code and self._share_preview_warning(warning) == "需要输入提取码"),
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
        root_files = [item for item in files if str(item.get("relative_path") or "").strip().count("/") == 0]
        title = files[0].get("name") or share.get("title") or "百度网盘分享"
        preview_files = files
        if len(files) == 1 and files[0].get("is_dir") and files[0].get("path"):
            try:
                child_detail = await self._fetch_share_folder_preview(tokens, cookie, share_url, feature, files[0])
                if child_detail.get("files"):
                    preview_files = child_detail["files"]
            except Exception as exc:
                logger.info("百度网盘分享文件夹预览读取失败: %s", exc)
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
            "root_files": root_files,
        }

    async def _verify_share_pass_code(
        self,
        feature: str,
        pass_code: str,
        tokens: Dict[str, Any],
        cookie: str,
        referer: str,
    ) -> Dict[str, Any]:
        query_payload: Dict[str, Any] = {
            "t": str(int(time.time() * 1000)),
        }
        shareid = str(tokens.get("shareid") or tokens.get("share_id") or "").strip()
        share_uk = str(tokens.get("share_uk") or "").strip()
        if shareid and share_uk:
            query_payload.update({
                "shareid": shareid,
                "uk": share_uk,
            })
        else:
            query_payload["surl"] = feature[1:]
        verify_query = urlencode(query_payload)
        return await self._fetch_form_json(
            f"http://pan.baidu.com/share/verify?{verify_query}",
            cookie,
            data={
                "pwd": pass_code,
                "vcode": "",
                "vcode_str": "",
            },
            referer=referer,
        )

    async def _fetch_share_folder_preview(
        self,
        tokens: Dict[str, Any],
        cookie: str,
        share_url: str,
        feature: str,
        folder: Dict[str, Any],
    ) -> Dict[str, Any]:
        folder_path = str(folder.get("path") or "").strip()
        folder_name = str(folder.get("name") or "").strip()
        if not folder_path:
            return {"files": []}
        data = await self._fetch_share_list_payload(tokens, cookie, share_url, feature, dir_path=folder_path, root=False)
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

    async def _fetch_share_list_payload(
        self,
        tokens: Dict[str, Any],
        cookie: str,
        share_url: str,
        feature: str,
        *,
        dir_path: str = "/",
        root: bool = True,
    ) -> Dict[str, Any]:
        share_uk = str(tokens.get("share_uk") or tokens.get("uk") or "").strip()
        shareid = str(tokens.get("shareid") or tokens.get("share_id") or "").strip()
        randsk = str(tokens.get("randsk") or "").strip() or self._cookie_value(cookie, "BDCLND")
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
            "sekey": randsk,
            "shorturl": feature[1:],
            "page": "1",
            "num": "100",
            "dir": str(dir_path or "/"),
            "root": "1" if root else "0",
            "order": "other",
            "desc": "1",
            "showempty": "0",
        }
        query = urlencode({key: value for key, value in query_payload.items() if value != ""})
        return await self._fetch_json(
            f"https://pan.baidu.com/share/list?{query}",
            cookie,
            timeout=20,
            referer=share_url,
        )

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
        ready = bool(str(getattr(self._config(), "cookie", "") or "").strip())
        result = {
            "enabled": bool(getattr(self._config(), "enabled", False)),
            "engine": "baidu_share_direct",
            "config_dir": self._config_dir(),
            "download_root": self._download_root(),
            "ok": ready,
            "message": "百度登录态可用" if ready else "百度账号未登录",
            "account": self.account_status(),
            "svip_speed": self._is_svip(),
        }
        return result

    def account_status(self) -> Dict[str, Any]:
        cfg = self._config()
        quota = max(0, _safe_int(getattr(cfg, "quota_bytes", 0)))
        used = max(0, _safe_int(getattr(cfg, "used_bytes", 0)))
        remaining = max(0, quota - used) if quota else 0
        vip_type = _safe_int(getattr(cfg, "vip_type", 0))
        vip_label = str(getattr(cfg, "vip_label", "") or "").strip()
        if not vip_label:
            vip_label = "SVIP" if vip_type >= 2 else ("VIP" if vip_type == 1 else "普通账号")
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "configured": bool(str(getattr(cfg, "cookie", "") or "").strip()),
            "ready": bool(str(getattr(cfg, "cookie", "") or "").strip()),
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
        result = await self.test_account(cookie_header, persist=persist)
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

    async def test_account(self, cookie: str = "", *, persist: bool = False) -> Dict[str, Any]:
        cookie_value = str(cookie or "").strip() or str(getattr(self._config(), "cookie", "") or "").strip()
        if not cookie_value or cookie_value == "********":
            raise BaiduNetdiskError("百度账号登录态不能为空")
        account = await self._fetch_account_by_web(cookie_value)
        quota_payload = await self._fetch_quota_by_web(cookie_value)
        account.update(quota_payload)
        account["configured"] = True
        account["ready"] = True
        account["cached_at"] = int(time.time())
        if persist:
            self._persist_account(cookie_value, account)
        return {
            "success": True,
            "message": "百度账号检测成功",
            "account": account,
        }

    async def refresh_account_status(self) -> Dict[str, Any]:
        """强制从百度接口重新拉取账号与容量，并更新本地缓存。"""
        result = await self.test_account("", persist=True)
        result["message"] = "百度账号状态已刷新"
        result["official_login"] = self.official_login_status()
        return result

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
        raise BaiduNetdiskError("没有找到可用于官方登录的 Chrome / Edge / Chromium 浏览器")

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
            "account_name": str(account.get("name") or account.get("username") or "").strip(),
            "account_netdisk_name": str(account.get("netdisk_name") or "").strip(),
            "account_avatar_url": str(account.get("avatar_url") or "").strip(),
            "account_uk": str(account.get("uk") or "").strip(),
            "vip_type": _safe_int(account.get("vip_type")),
            "vip_label": str(account.get("vip_label") or "").strip(),
            "vip_level": str(account.get("vip_level") or "").strip(),
            "vip_expire_at": _safe_int(account.get("vip_expire_at")),
            "quota_bytes": _safe_int(account.get("quota_bytes")),
            "used_bytes": _safe_int(account.get("used_bytes")),
            "account_cached_at": _safe_int(account.get("cached_at") or int(time.time())),
        })
        save_config({"baidu_netdisk": cfg})

    async def _fetch_json(self, url: str, cookie: str, timeout: int = 20, referer: str = "") -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            headers = {
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Accept": "application/json,text/plain,*/*",
            }
            if referer:
                headers["Referer"] = referer
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
        timeout: int = 20,
    ) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            body = urlencode({key: str(value or "") for key, value in (data or {}).items()}).encode("utf-8")
            headers = {
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Accept": "application/json,text/plain,*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            if referer:
                headers["Referer"] = referer
            request = Request(url, data=body, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                body_text = response.read().decode("utf-8", errors="replace")
            return json.loads(body_text)

        return await asyncio.to_thread(run)

    async def _fetch_share_page_tokens(self, featurestr: str, cookie: str, *, referer: str = "") -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Referer": referer or "https://pan.baidu.com/disk/home",
                "Cookie": cookie,
            }
            if referer and "/share/init" in referer:
                headers["Referer"] = referer
            share_link = f"https://pan.baidu.com/s/{featurestr}"
            request = Request(share_link, headers=headers)
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
            if "platform-non-found" in body or "error-404" in body:
                raise BaiduNetdiskError("分享链接已失效")
            payload = self._extract_share_page_local_payload(body)
            return {
                "bdstoken": str(payload.get("bdstoken") or "").strip(),
                "uk": str(payload.get("uk") or "").strip(),
                "share_uk": str(payload.get("share_uk") or "").strip(),
                "shareid": str(payload.get("shareid") or "").strip(),
                "sign": "",
                "timestamp": "",
            }

        return await asyncio.to_thread(run)

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
        ]
        last_error = ""
        for endpoint in endpoints:
            try:
                data = await self._fetch_json(endpoint, cookie)
                errno = _safe_int(data.get("errno", data.get("error_code", 0)), 0)
                if errno and errno != 2:
                    raise BaiduNetdiskError(str(data.get("error_msg") or data.get("errmsg") or data))
                quota = _safe_int(data.get("total") or data.get("quota") or data.get("limit"), -1)
                used = _safe_int(data.get("used") or data.get("usage"), -1)
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
            except Exception as exc:
                last_error = str(exc)
                logger.debug("百度容量接口失败: %s %s", endpoint, exc)
        raise BaiduNetdiskError(f"百度容量刷新失败: {last_error or '接口无响应'}")

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
            for file_index, share_file in enumerate(share_files):
                if share_file.get("is_dir"):
                    expanded = await self._collect_share_folder_files(context, share_file)
                    for child_index, child in enumerate(expanded):
                        rows.append(self._download_row_from_share_file(
                            item,
                            child,
                            context,
                            f"{file_index}-{child_index}",
                            keep_share_root=multiple_selected_shares,
                        ))
                    continue
                rows.append(self._download_row_from_share_file(
                    item,
                    share_file,
                    context,
                    str(file_index),
                    keep_share_root=multiple_selected_shares,
                ))
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
        fs_id = str(share_file.get("fs_id") or share_file.get("fsid") or "").strip()
        size = _safe_int(share_file.get("size_bytes") or share_file.get("size"))
        return {
            "gid": f"{item.get('selection_key') or self._selection_key(item)}:{fs_id or index_key}",
            "name": name,
            "relative_path": relative_path,
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
        }

    def _strip_selected_share_root(self, item: Dict[str, Any], relative_path: str) -> str:
        text = str(relative_path or "").replace("\\", "/").strip("/")
        root = str(item.get("filename") or item.get("name") or "").replace("\\", "/").strip("/")
        if root and text.startswith(f"{root}/"):
            return text[len(root) + 1:]
        return text

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
        fallback_folder = output_folder_name or self._sanitize_folder_name(
            str(metadata.get("batch_name") or items[0].get("filename") or "百度网盘下载")
        )
        final_dir = self._safe_join(final_base_dir, fallback_folder)
        final_dir = self._resolve_final_dir_for_policy(final_dir, conflict_policy)
        if conflict_policy == "skip" and os.path.exists(final_dir):
            task.task_metadata.update({
                "download_root": download_root,
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
            for index, row in enumerate(download_files):
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
                self._refresh_runtime(task, download_files, started=started, current={})
        finally:
            if self._task_cancel_events.get(task.id) is cancel_event:
                self._task_cancel_events.pop(task.id, None)

        success_files = [row for row in download_files if row.get("status") == "completed"]
        failed_files = [row for row in download_files if row.get("status") == "failed"]
        if not success_files:
            task.task_metadata["failed_files"] = failed_files
            raise BaiduNetdiskError(self._first_failure_reason(failed_files) or "没有任何百度网盘文件下载成功")

        finalized = await asyncio.to_thread(self._finalize_output, staging_dir, final_dir, conflict_policy, len(items))
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
            "performance_metrics": {
                "duration_ms": duration_ms,
                "downloaded_bytes": downloaded_bytes,
                "transferred_bytes": downloaded_bytes,
                "success_count": len(success_files),
                "failed_count": len(failed_files),
                "average_speed_bytes": int(downloaded_bytes / max(duration_ms / 1000, 1)) if downloaded_bytes else 0,
            },
        })
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
        cookie = str(getattr(self._config(), "cookie", "") or "").strip()
        if not cookie or cookie == "********":
            raise BaiduNetdiskError("百度账号未登录，无法直接下载分享文件")
        randsk = str(row.get("randsk") or "").strip()
        if randsk:
            cookie = self._merge_cookie_header(cookie, {"BDCLND": randsk})
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

    def _baidu_pcs_go_download_config_commands(self, pcsgo_path: str, savedir: str) -> List[List[str]]:
        max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
        return [
            [pcsgo_path, "config", "set", "-savedir", savedir],
            [pcsgo_path, "config", "set", "-max_parallel", str(max_parallel)],
            [pcsgo_path, "config", "set", "-max_download_load", str(max_download_load)],
            [pcsgo_path, "config", "set", "-max_download_rate", "0"],
            [pcsgo_path, "config", "set", "-cache_size", "256KB"],
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
        pass_code = str(row.get("pass_code") or "").strip()
        if pass_code and "pwd=" not in share_url.lower():
            share_url = f"{share_url}{'&' if '?' in share_url else '?'}pwd={quote(pass_code)}"
        cookie = self._share_download_cookie(row)
        expected_name = str(row.get("relative_path") or row.get("name") or "").strip()
        expected_size = _safe_int(row.get("total") or row.get("size"))
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
        remote_tmp_dir = self._remote_temporary_transfer_dir(task)
        remote_tmp_created = False
        try:
            task.update_progress(max(2, task.progress), "准备百度网盘临时转存下载")
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "login", f"-cookies={cookie}"],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
            )
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
            await self._run_baidu_pcs_go_command(
                [pcsgo_path, "transfer", share_url, "--collect"],
                env=env,
                log_path=log_path,
                task=task,
                cancel_event=cancel_event,
                heartbeat_message="BaiduPCS-Go 正在转存分享文件",
            )
            max_parallel, max_download_load = self._baidu_pcs_go_download_limits()
            self._append_log(
                task,
                f"BaiduPCS-Go 高速下载参数：线程 {max_parallel}，同时文件 {max_download_load}，模式 locate，不限速",
                "info",
            )
            task.update_progress(max(2, task.progress), "百度网盘转存完成，开始高速下载")
            progress_state = {"last_emit_at": 0.0, "last_log_at": 0.0}
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
            )
            downloaded_path = self._find_baidu_pcs_go_downloaded_file(savedir, expected_name, expected_size)
            if not downloaded_path:
                tail = self._read_text_tail(log_path)
                raise BaiduNetdiskError(
                    f"BaiduPCS-Go 下载完成但未找到文件: {expected_name or 'download.bin'}"
                    + (f"；日志: {tail}" if tail else "")
                )
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            if os.path.exists(target_path):
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
            shutil.move(downloaded_path, target_path)
            final_size = os.path.getsize(target_path)
            row.update({
                "status": "completed",
                "progress": 100,
                "downloaded": final_size,
                "total": max(int(row.get("total") or 0), final_size),
                "size": max(int(row.get("size") or 0), final_size),
                "local_path": target_path,
                "speed_bytes_per_sec": 0,
            })
            self._refresh_runtime(task, download_files, started=started, current=row)
        finally:
            if remote_tmp_created:
                try:
                    await self._run_baidu_pcs_go_command(
                        [pcsgo_path, "cd", "/"],
                        env=env,
                        log_path=log_path,
                        task=task,
                        cancel_event=asyncio.Event(),
                        ignore_task_cancel=True,
                    )
                    await self._run_baidu_pcs_go_command(
                        [pcsgo_path, "rm", remote_tmp_dir],
                        env=env,
                        log_path=log_path,
                        task=task,
                        cancel_event=asyncio.Event(),
                        ignore_task_cancel=True,
                    )
                    self._append_log(task, f"已删除百度网盘临时转存目录 {remote_tmp_dir}", "info")
                except Exception as cleanup_exc:
                    self._append_log(
                        task,
                        f"百度网盘临时转存目录清理失败，请手动删除 {remote_tmp_dir}: {self._sanitize_error(cleanup_exc)}",
                        "warning",
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

    def _remote_temporary_transfer_dir(self, task) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_part = secrets.token_hex(3)
        return f"/km_{timestamp}_{random_part}"

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
        heartbeat_message: str = "",
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
            if hasattr(task, "register_process"):
                task.register_process(proc)
            output_queue: queue.Queue[Optional[bytes]] = queue.Queue()
            reader = threading.Thread(
                target=self._read_process_output,
                args=(proc.stdout, output_queue),
                daemon=True,
            )
            reader.start()
            last_heartbeat_at = time.monotonic()
            pending_output = b""
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
                        pending_output = self._consume_pcsgo_output_chunk(pending_output + chunk, on_output)
                        last_heartbeat_at = time.monotonic()
                    code = proc.poll()
                    if code is not None:
                        break
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
                if hasattr(task, "unregister_process"):
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
                    pending_output = self._consume_pcsgo_output_chunk(pending_output + chunk, on_output)
            if pending_output and on_output:
                on_output(self._decode_pcsgo_output(pending_output))
        if proc.returncode != 0:
            tail = self._read_text_tail(log_path)
            raise BaiduNetdiskError(self._sanitize_error(tail or f"BaiduPCS-Go 返回退出码 {proc.returncode}"))

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
            if downloaded >= int(row.get("downloaded") or 0):
                row["downloaded"] = downloaded
            if total > int(row.get("total") or 0):
                row["total"] = total
                row["size"] = max(int(row.get("size") or 0), total)
            if total > 0:
                row["progress"] = max(int(row.get("progress") or 0), min(99, int(downloaded / total * 100)))
            parsed_any = True

        speed_match = re.search(
            r"(?P<speed>\d+(?:\.\d+)?)\s*(?P<unit>[KMGTPE]?i?B|B)\s*/\s*s",
            text,
            re.IGNORECASE,
        )
        if speed_match:
            row["speed_bytes_per_sec"] = self._parse_pcsgo_size(speed_match.group("speed"), speed_match.group("unit"))
            parsed_any = True

        if "下载" in text or "转存" in text or "秒传" in text:
            if now - float(state.get("last_log_at") or 0) >= 12:
                self._append_log(task, self._compact_pcsgo_log_line(text), "info")
                state["last_log_at"] = now

        if parsed_any and now - float(state.get("last_emit_at") or 0) >= 0.8:
            self._refresh_runtime(task, download_files, started=started, current=row)
            state["last_emit_at"] = now

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
        runtime = {
            "status": "downloading",
            "total_files": len(download_files),
            "completed_files": len(completed),
            "failed_files": len(failed),
            "active_file_count": len(active),
            "transferred_bytes": transferred,
            "total_bytes": total_bytes,
            "speed_bytes_per_sec": speed,
            "current_file_name": str((current or {}).get("name") or (active[0].get("name") if active else "") or ""),
            "current_relative_path": str((current or {}).get("relative_path") or ""),
            "elapsed_seconds": int(time.monotonic() - started),
            "speed_label": "百度网盘 SVIP 高速" if self._is_svip() else "百度网盘下载",
        }
        task.task_metadata["download_files"] = download_files
        task.task_metadata["download_runtime"] = runtime
        if total_bytes:
            task.progress = max(task.progress, min(99, int(transferred / max(total_bytes, 1) * 100)))
        else:
            unit = 90 / max(len(download_files), 1)
            task.progress = max(task.progress, min(95, int(2 + len(completed) * unit + sum(int(row.get("progress") or 0) for row in active) / 100 * unit)))
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
        return text

    async def cancel_task(self, task_id: str) -> None:
        event = self._task_cancel_events.get(task_id)
        if event:
            event.set()

    async def reset_task_for_retry(self, task) -> None:
        from .task_engine import TaskStatus

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
