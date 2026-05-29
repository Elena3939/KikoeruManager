import asyncio
import contextlib
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
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse, urlunparse
from urllib.request import Request, urlopen

import aiohttp

from ..config.settings import get_config

logger = logging.getLogger(__name__)

_BLOCKED_HOST_HINTS = {"gofile.io", "tranfile.com", "transfernow.net"}
_PIKPAK_HOST_HINTS = {"mypikpak.com", "www.mypikpak.com", "drive.mypikpak.com"}
_PIKPAK_MAX_SHARE_FILES = 100


class HttpDownloadError(ValueError):
    """HTTP 外链下载的可预期业务错误。"""


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
    text = str(value or "")
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


class HttpDownloadService:
    """通用 HTTP/HTTPS 外链下载服务，底层通过 aria2 RPC 驱动。"""

    def __init__(self):
        self._daemon: Optional[Aria2Daemon] = None
        self._daemon_lock = asyncio.Lock()
        self._task_gids: Dict[str, List[str]] = {}
        self._rpc_id = 0

    def _config(self):
        return get_config().http_downloader

    def _storage_temp_root(self) -> str:
        return str(getattr(get_config().storage, "temp_path", "") or tempfile.gettempdir())

    def _download_root(self) -> str:
        cfg = self._config()
        root = str(getattr(cfg, "download_root", "") or "").strip()
        if not root:
            root = os.path.join(get_config().storage.temp_path, "http_downloads")
        return os.path.abspath(root)

    def _mask_url(self, value: str) -> str:
        return mask_http_download_url(value)

    def _sanitize_error(self, value: Any) -> str:
        return sanitize_http_download_error(value)

    def _proxy_url(self) -> str:
        proxy = str(getattr(self._config(), "proxy_url", "") or "").strip()
        if proxy and "://" not in proxy:
            proxy = f"http://{proxy}"
        return proxy

    def _pikpak_enabled(self) -> bool:
        return bool(getattr(self._config(), "pikpak_enabled", False))

    def _is_pikpak_url(self, raw_url: str) -> bool:
        try:
            parsed = urlparse(str(raw_url or "").strip())
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return host in _PIKPAK_HOST_HINTS or host.endswith(".mypikpak.com")

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
        parsed = urlparse(url)
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
        return ""

    async def _save_pikpak_token_callback(self, client, **_kwargs) -> None:
        token = str(getattr(client, "encoded_token", "") or "").strip()
        if not token:
            return
        try:
            from ..config.settings import save_config

            await asyncio.to_thread(save_config, {"http_downloader": {"pikpak_encoded_token": token}})
        except Exception:
            logger.warning("[PikPak] 保存刷新后的 token 失败", exc_info=True)

    async def _pikpak_client(self):
        cfg = self._config()
        if not self._pikpak_enabled():
            raise HttpDownloadError("PikPak 下载未启用，请先在设置页启用并配置账号")
        token = str(getattr(cfg, "pikpak_encoded_token", "") or "").strip()
        username = str(getattr(cfg, "pikpak_username", "") or "").strip()
        password = str(getattr(cfg, "pikpak_password", "") or "").strip()
        if not token and not (username and password):
            raise HttpDownloadError("PikPak 未配置账号或 token")
        try:
            from pikpakapi import PikPakApi
            import httpx
        except Exception as exc:
            raise HttpDownloadError("后端缺少 pikpakapi 依赖，请重新安装 backend/requirements.txt") from exc
        httpx_args: Dict[str, Any] = {
            "timeout": max(10, int(getattr(cfg, "timeout_seconds", 60) or 60)),
        }
        proxy = self._proxy_url()
        if proxy:
            async_client_params = inspect.signature(httpx.AsyncClient).parameters
            httpx_args["proxy" if "proxy" in async_client_params else "proxies"] = proxy
        kwargs = {
            "encoded_token": token or None,
            "username": username or None,
            "password": password or None,
            "device_id": str(getattr(cfg, "pikpak_device_id", "") or "").strip() or None,
            "httpx_client_args": httpx_args,
            "request_max_retries": max(1, int(getattr(cfg, "retry_count", 5) or 5)),
            "request_initial_backoff": max(0.5, float(getattr(cfg, "retry_wait_seconds", 5) or 5)),
            "token_refresh_callback": self._save_pikpak_token_callback,
        }
        client = PikPakApi(**kwargs)
        if not token:
            await client.login()
            await self._save_pikpak_token_callback(client)
        return client

    async def _close_pikpak_client(self, client) -> None:
        with contextlib.suppress(Exception):
            await client.httpx_client.aclose()

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

    async def _collect_pikpak_share_files(self, client, share_link: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        pass_code = self._parse_pikpak_pass_code(share_link)
        info = await client.get_share_info(share_link, pass_code=pass_code or None)
        if isinstance(info, Exception):
            raise HttpDownloadError(str(info))
        if not isinstance(info, dict):
            raise HttpDownloadError("PikPak 分享信息返回异常")
        share_id = str(info.get("share_id") or self._pikpak_share_id_from_url(share_link))
        token = str(info.get("pass_code_token") or "")
        files = [item for item in list(info.get("files") or []) if isinstance(item, dict)]
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
                    detail = await client.get_share_folder(share_id, token, parent_id=folder_id or None)
                    children = [child for child in list((detail or {}).get("files") or []) if isinstance(child, dict)]
                    await walk(children, "/".join([part for part in (prefix, name) if part]))
                    continue
                row = dict(item)
                row["_relative_dir"] = prefix
                collected.append(row)

        await walk(files)
        return info, collected

    async def _copy_pikpak_share_files(self, client, file_ids: List[str]) -> Dict[str, str]:
        id_map = {str(item): str(item) for item in file_ids if str(item or "").strip()}
        if not file_ids:
            return id_map
        cfg = self._config()
        transfer_dir = str(getattr(cfg, "pikpak_transfer_dir", "") or "/KikoeruManager").strip() or "/KikoeruManager"
        parent_id = None
        try:
            path_rows = await client.path_to_id(transfer_dir, create=True)
            if path_rows:
                parent_id = path_rows[-1].get("id")
        except Exception:
            logger.warning("[PikPak] 创建/定位转存目录失败，将转存到根目录: %s", transfer_dir, exc_info=True)
        result = await client.file_batch_copy(file_ids, to_parent_id=parent_id)
        for item in list((result or {}).get("files") or []):
            if not isinstance(item, dict):
                continue
            original_id = str(item.get("original_file_id") or item.get("from_id") or item.get("source_id") or "")
            copied_id = str(item.get("id") or item.get("file_id") or "")
            if original_id and copied_id:
                id_map[original_id] = copied_id
        tasks = list((result or {}).get("tasks") or [])
        for item in tasks:
            if not isinstance(item, dict):
                continue
            original_id = str(item.get("original_file_id") or item.get("from_id") or item.get("source_id") or "")
            copied_id = str(item.get("file_id") or item.get("id") or "")
            if original_id and copied_id:
                id_map[original_id] = copied_id
        return id_map

    async def _pikpak_download_link(self, client, file_id: str, *, allow_missing: bool = False) -> Dict[str, Any]:
        try:
            info = await client.get_download_url(file_id)
        except Exception as exc:
            if allow_missing:
                return {}
            raise exc
        if not isinstance(info, dict):
            raise HttpDownloadError("PikPak 下载链接返回异常")
        url = str(info.get("web_content_link") or "").strip()
        if not url:
            media = list(info.get("medias") or [])
            if media:
                link = media[0].get("link") if isinstance(media[0], dict) else None
                if isinstance(link, dict):
                    url = str(link.get("url") or "").strip()
        if not url and allow_missing:
            return info
        if not url:
            raise HttpDownloadError("PikPak 未返回可下载链接，可能需要会员权限或文件仍在转码/审核")
        info["_download_url"] = url
        return info

    async def resolve_source_urls(self, urls: List[str], *, materialize: bool = False) -> Dict[str, Any]:
        resolved: List[str] = []
        source_items: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        pikpak_links = [url for url in urls if self._is_pikpak_url(url)]
        direct_links = [url for url in urls if not self._is_pikpak_url(url)]
        resolved.extend(direct_links)
        for url in direct_links:
            source_items.append({"source": "http", "url": url, "masked_url": self._mask_url(url)})
        if not pikpak_links:
            return {"urls": resolved, "source_items": source_items, "failed_items": failed, "source_modes": ["http"] if direct_links else []}

        client = await self._pikpak_client()
        try:
            for raw_url in pikpak_links:
                try:
                    info, files = await self._collect_pikpak_share_files(client, raw_url)
                    if not files:
                        failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "PikPak 分享中没有可下载文件", "source": "pikpak"})
                        continue
                    file_ids = []
                    for item in files:
                        file_id = str(item.get("id") or item.get("file_id") or "")
                        if file_id and file_id not in file_ids:
                            file_ids.append(file_id)
                    copied_id_map = {item: item for item in file_ids}
                    if materialize and bool(getattr(self._config(), "pikpak_auto_save_share", True)):
                        copied_id_map = await self._copy_pikpak_share_files(client, file_ids)
                    for item in files:
                        file_id = str(item.get("id") or item.get("file_id") or "")
                        if not file_id:
                            failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": "PikPak 文件缺少 file_id", "source": "pikpak"})
                            continue
                        download_file_id = copied_id_map.get(file_id, file_id)
                        detail = await self._pikpak_download_link(client, download_file_id, allow_missing=not materialize)
                        download_url = str(detail.get("_download_url") or "")
                        name = self._sanitize_filename(detail.get("name") or item.get("name") or "pikpak-file")
                        relative_dir = str(item.get("_relative_dir") or "").strip("/")
                        if download_url:
                            resolved.append(download_url)
                        source_items.append({
                            "source": "pikpak",
                            "share_url": self._mask_url(raw_url),
                            "url": self._mask_url(download_url) if download_url else self._mask_url(raw_url),
                            "original_url": download_url,
                            "file_id": file_id,
                            "download_file_id": download_file_id,
                            "name": name,
                            "filename": name,
                            "relative_dir": relative_dir,
                            "size_bytes": self._pikpak_file_size(detail) or self._pikpak_file_size(item),
                            "share_id": info.get("share_id") or self._pikpak_share_id_from_url(raw_url),
                        })
                        if not download_url:
                            source_items[-1]["preview_only"] = True
                except Exception as exc:
                    failed.append({"ok": False, "url": raw_url, "masked_url": self._mask_url(raw_url), "reason": self._sanitize_error(exc), "source": "pikpak"})
        finally:
            await self._close_pikpak_client(client)

        modes = []
        if direct_links:
            modes.append("http")
        if pikpak_links:
            modes.append("pikpak")
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

    async def preview_urls(self, urls: List[str], target_subdir: str = "", conflict_policy: str = "", *, materialize_sources: bool = False) -> Dict[str, Any]:
        source = await self.resolve_source_urls(urls, materialize=materialize_sources)
        items = []
        for raw_url in source.get("urls") or []:
            item = await self.preview_url(raw_url, target_subdir=target_subdir, conflict_policy=conflict_policy)
            items.append(item)
        if not materialize_sources:
            for source_item in source.get("source_items") or []:
                if not isinstance(source_item, dict) or source_item.get("source") != "pikpak" or not source_item.get("preview_only"):
                    continue
                filename = self._sanitize_filename(source_item.get("filename") or source_item.get("name") or "pikpak-file")
                subdir = "/".join([part for part in (target_subdir, source_item.get("relative_dir")) if str(part or "").strip()])
                try:
                    target = self._resolve_target(filename, subdir, conflict_policy)
                    items.append({
                        "ok": True,
                        "url": source_item.get("url") or source_item.get("share_url") or "",
                        "masked_url": source_item.get("share_url") or "",
                        "host": "mypikpak.com",
                        "source": "pikpak",
                        "filename": target["filename"],
                        "relative_path": target["relative_path"],
                        "final_path": target["final_path"],
                        "target_dir": target["target_dir"],
                        "size_bytes": int(source_item.get("size_bytes") or 0),
                        "content_type": "",
                        "resumable": True,
                        "warning": "PikPak 分享将在开始下载时转存并解析直链。",
                    })
                except Exception as exc:
                    items.append({
                        "ok": False,
                        "url": source_item.get("share_url") or "",
                        "masked_url": source_item.get("share_url") or "",
                        "reason": self._sanitize_error(exc),
                        "source": "pikpak",
                    })
        items.extend(source.get("failed_items") or [])
        ok_count = sum(1 for item in items if item.get("ok"))
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

    async def preview_url(self, raw_url: str, target_subdir: str = "", conflict_policy: str = "") -> Dict[str, Any]:
        try:
            url = await self.validate_url(raw_url)
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            hint = ""
            if any(host == item or host.endswith(f".{item}") for item in _BLOCKED_HOST_HINTS):
                hint = "该站点常见页面链接需要登录/验证码；首版只支持真实文件直链。"
            headers: Dict[str, str] = {}
            status = None
            size = 0
            content_type = ""
            timeout = aiohttp.ClientTimeout(total=20, connect=8)
            proxy = self._proxy_url() or None
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.head(url, allow_redirects=True, proxy=proxy) as response:
                        status = response.status
                        headers = {k.lower(): v for k, v in response.headers.items()}
                        url = str(response.url)
                except Exception:
                    async with session.get(url, allow_redirects=True, headers={"Range": "bytes=0-0"}, proxy=proxy) as response:
                        status = response.status
                        headers = {k.lower(): v for k, v in response.headers.items()}
                        url = str(response.url)
            url = await self.validate_url(url)
            if status and status >= 400:
                raise HttpDownloadError(f"源站返回 HTTP {status}")
            content_type = str(headers.get("content-type") or "")
            if "text/html" in content_type.lower() and not hint:
                hint = "源站返回 HTML 页面，可能不是可直接下载的文件链接。"
            size = self._content_length_from_headers(headers)
            filename = self._filename_from_headers(headers) or self._filename_from_url(url)
            target = self._resolve_target(filename, target_subdir, conflict_policy)
            return {
                "ok": True,
                "url": url,
                "masked_url": self._mask_url(url),
                "host": urlparse(url).hostname or "",
                "source": "http",
                "filename": target["filename"],
                "relative_path": target["relative_path"],
                "final_path": target["final_path"],
                "target_dir": target["target_dir"],
                "size_bytes": size,
                "content_type": content_type,
                "resumable": "bytes" in str(headers.get("accept-ranges") or "").lower(),
                "warning": hint,
            }
        except Exception as exc:
            return {
                "ok": False,
                "url": str(raw_url or "").strip(),
                "masked_url": self._mask_url(str(raw_url or "")),
                "reason": self._sanitize_error(exc),
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

    def _aria2_options(self, item: Dict[str, Any], target_dir: str) -> Dict[str, str]:
        cfg = self._config()
        options = {
            "dir": target_dir,
            "out": item["filename"],
            "continue": "true",
            "max-tries": str(max(1, int(getattr(cfg, "retry_count", 5) or 5))),
            "retry-wait": str(max(0, int(getattr(cfg, "retry_wait_seconds", 5) or 5))),
            "connect-timeout": str(max(1, int(getattr(cfg, "connect_timeout_seconds", 15) or 15))),
            "timeout": str(max(1, int(getattr(cfg, "timeout_seconds", 60) or 60))),
            "split": str(max(1, int(getattr(cfg, "split", 8) or 8))),
            "max-connection-per-server": str(max(1, int(getattr(cfg, "max_connection_per_server", 8) or 8))),
            "min-split-size": str(getattr(cfg, "min_split_size", "1M") or "1M"),
            "auto-file-renaming": "false",
            "allow-overwrite": "true",
        }
        proxy = self._proxy_url()
        if proxy:
            options["all-proxy"] = proxy
        return options

    async def start_download_task(self, task) -> Dict[str, Any]:
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
        preview = await self.preview_urls(raw_urls, target_subdir=target_subdir, conflict_policy=conflict_policy, materialize_sources=True)
        items = [item for item in preview.get("items") or [] if item.get("ok")]
        failed_items = [item for item in preview.get("items") or [] if not item.get("ok")]
        if not items:
            raise HttpDownloadError("没有通过校验的直链")
        resolved_urls = list(preview.get("resolved_urls") or [])
        source_items = list(preview.get("source_items") or [])
        source_modes = list(preview.get("source_modes") or [])

        os.makedirs(self._download_root(), exist_ok=True)
        gids: List[str] = []
        download_files = []
        total_bytes = 0
        for item in items:
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
        })
        task.output_path = self._download_root()
        task.task_metadata["final_output_path"] = self._download_root()
        task.update_progress(1, f"已提交 {len(gids)} 个 aria2 下载")

        started = time.monotonic()
        last_log_at = 0.0
        while True:
            await task.wait_if_paused()
            if task.is_cancelled():
                await self.cancel_task(task.id)
                raise HttpDownloadError("用户取消")
            rows, runtime, done, failed = await self._poll_task(gids, download_files)
            task.task_metadata["download_files"] = rows
            task.task_metadata["download_runtime"] = runtime
            task.current_step = runtime.get("current_file_name") or "下载中"
            total = max(1, int(runtime.get("total_bytes") or total_bytes or 0))
            transferred = int(runtime.get("transferred_bytes") or 0)
            progress = 95 if total <= 1 else min(99, int(transferred / total * 100))
            task.progress = max(task.progress, progress)
            now = time.monotonic()
            if now - last_log_at > 5:
                last_log_at = now
                task.update_progress(task.progress, f"下载中 {runtime.get('completed_files', 0)}/{len(rows)}")
            if done:
                break
            await asyncio.sleep(1.0)

        success_files = [row for row in rows if row.get("status") == "completed"]
        failed_rows = [row for row in rows if row.get("status") == "failed"]
        duration_ms = int((time.monotonic() - started) * 1000)
        downloaded_bytes = sum(int(row.get("downloaded") or row.get("size") or 0) for row in success_files)
        task.task_metadata.update({
            "download_files": rows,
            "failed_files": [*failed_items, *failed_rows],
            "final_output_path": self._download_root(),
            "performance_metrics": {
                "duration_ms": duration_ms,
                "downloaded_bytes": downloaded_bytes,
                "success_count": len(success_files),
                "failed_count": len(failed_items) + len(failed_rows),
                "average_speed_bytes": int(downloaded_bytes / max(duration_ms / 1000, 1)) if downloaded_bytes else 0,
            },
        })
        final_status = "completed" if success_files and not failed_items and not failed_rows else "partial_failed"
        runtime["status"] = final_status
        runtime["speed_bytes_per_sec"] = 0
        task.task_metadata["download_runtime"] = runtime
        if not success_files:
            raise HttpDownloadError("没有任何文件下载成功")
        task.update_progress(100, f"下载完成，成功 {len(success_files)} 个，失败 {len(failed_items) + len(failed_rows)} 个")
        return {
            "success": True,
            "download_root": self._download_root(),
            "downloaded_files": success_files,
            "failed_files": [*failed_items, *failed_rows],
        }

    def _content_length_from_headers(self, headers: Dict[str, str]) -> int:
        content_range = str(headers.get("content-range") or "")
        match = re.search(r"/(\d+)\s*$", content_range)
        if match:
            return int(match.group(1))
        return int(headers.get("content-length") or 0)

    async def reset_task_for_retry(self, task) -> None:
        urls = list((task.task_metadata or {}).get("urls") or [])
        from .task_engine import TaskStatus

        task.task_metadata["urls"] = urls
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
            cfg = self._config()
            pikpak_ready = bool(
                str(getattr(cfg, "pikpak_encoded_token", "") or "").strip()
                or (
                    str(getattr(cfg, "pikpak_username", "") or "").strip()
                    and str(getattr(cfg, "pikpak_password", "") or "").strip()
                )
            )
            pikpak_message = "PikPak 已配置" if pikpak_ready else "PikPak 已启用但缺少账号或 token"
        result.update({
            "pikpak_enabled": self._pikpak_enabled(),
            "pikpak_ready": pikpak_ready,
            "pikpak_message": pikpak_message,
        })
        return result


_http_download_service: Optional[HttpDownloadService] = None


def get_http_download_service() -> HttpDownloadService:
    global _http_download_service
    if _http_download_service is None:
        _http_download_service = HttpDownloadService()
    return _http_download_service
