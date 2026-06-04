import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

from ..config.settings import get_config, save_config
from .http_download_service import sanitize_http_download_item

logger = logging.getLogger(__name__)

BAIDU_NETDISK_LABEL = "百度网盘"
BAIDU_NETDISK_PLATFORM = "baidu_netdisk"
DEFAULT_BAIDUPCS_GO_PATH = "tools/baidupcs-go/BaiduPCS-Go.exe"
BAIDU_OFFICIAL_LOGIN_URL = "https://pan.baidu.com/"
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


class BaiduNetdiskError(ValueError):
    """百度网盘下载的可预期业务错误。"""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


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
    return out


def sanitize_baidu_netdisk_preview(preview: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(preview, dict):
        return {}
    out = dict(preview)
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


def build_baidu_netdisk_batch_title(metadata: Dict[str, Any], item_count: int = 0) -> str:
    count = int(item_count or metadata.get("selected_count") or metadata.get("url_count") or 0)
    if count > 1:
        return f"百度网盘下载 {count} 项"
    return "百度网盘下载"


class BaiduNetdiskService:
    """百度网盘分享下载服务，底层通过 BaiduPCS-Go 子进程执行。"""

    def __init__(self):
        self._task_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._official_login_session: Optional[Dict[str, Any]] = None

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

    def _baidupcs_go_path(self) -> str:
        configured = str(getattr(self._config(), "baidupcs_go_path", "") or "").strip()
        if configured:
            raw_path = Path(configured)
            candidate_paths = [raw_path] if raw_path.is_absolute() else [self._repo_root() / raw_path]
            if raw_path.suffix.lower() == ".exe":
                candidate_paths.append(candidate_paths[0].with_suffix(""))
            else:
                candidate_paths.append(candidate_paths[0].with_suffix(".exe"))
            for candidate in candidate_paths:
                if candidate.exists():
                    return str(candidate)
        env_path = str(os.environ.get("BAIDUPCS_GO_PATH") or "").strip()
        if env_path:
            return env_path
        for candidate_name in ("BaiduPCS-Go", "baidupcs-go"):
            resolved = shutil.which(candidate_name)
            if resolved:
                return resolved
        candidates = [
            self._repo_root() / "tools" / "baidupcs-go" / "BaiduPCS-Go.exe",
            self._repo_root() / "tools" / "baidupcs-go" / "BaiduPCS-Go",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return configured or str(self._repo_root() / DEFAULT_BAIDUPCS_GO_PATH)

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
            "share_id": share_id or hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12],
            "pass_code": pass_code,
            "title": title,
        }

    def _preview_item_from_share(self, share: Dict[str, str], target_subdir: str, output_folder_name: str = "") -> Dict[str, Any]:
        missing_code = self._likely_requires_pass_code(share) and not share.get("pass_code")
        title = self._sanitize_folder_name(output_folder_name or share.get("title") or "百度网盘分享")
        item = {
            "ok": not missing_code,
            "url": share.get("share_url") or "",
            "masked_url": share.get("share_url") or "",
            "host": "pan.baidu.com",
            "source": BAIDU_NETDISK_PLATFORM,
            "share_url": share.get("share_url") or "",
            "share_id": share.get("share_id") or "",
            "pass_code": share.get("pass_code") or "",
            "requires_pass_code": bool(missing_code),
            "filename": title,
            "name": title,
            "relative_path": "/".join(part for part in [self._safe_subdir(target_subdir), title] if part),
            "size_bytes": 0,
            "content_type": "application/x-baidu-netdisk-share",
            "resumable": True,
            "is_dir": True,
            "source_label": BAIDU_NETDISK_LABEL,
        }
        item["selection_key"] = self._selection_key(item)
        if missing_code:
            item["reason"] = "需要输入提取码"
            item["warning"] = "缺提取码，补充后重新预览"
        else:
            item["warning"] = "将使用 BaiduPCS-Go 直接下载分享内容"
        return item

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
        items = [
            self._preview_item_from_share(share, target_subdir, output_folder_name)
            for share in shares
        ]
        ok_count = sum(1 for item in items if item.get("ok"))
        return {
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
        }

    def _is_svip(self) -> bool:
        cfg = self._config()
        vip_type = _safe_int(getattr(cfg, "vip_type", 0))
        vip_label = str(getattr(cfg, "vip_label", "") or "").lower()
        return vip_type >= 2 or "svip" in vip_label or "超级" in vip_label

    async def health(self) -> Dict[str, Any]:
        result = {
            "enabled": bool(getattr(self._config(), "enabled", False)),
            "engine": "BaiduPCS-Go",
            "baidupcs_go_path": self._baidupcs_go_path(),
            "config_dir": self._config_dir(),
            "download_root": self._download_root(),
            "ok": False,
            "message": "",
            "account": self.account_status(),
            "svip_speed": self._is_svip(),
        }
        try:
            proc = await self._run_pcsgo(["-v"], timeout=8)
            output = (proc.get("stdout") or proc.get("stderr") or "").strip()
            result.update({
                "ok": proc.get("returncode") == 0,
                "version": output[:500],
                "message": "BaiduPCS-Go 可用" if proc.get("returncode") == 0 else (output[:300] or "BaiduPCS-Go 执行失败"),
            })
        except Exception as exc:
            result.update({"ok": False, "message": str(exc)})
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
        """从隔离官方登录窗口同步百度账号登录态，并写入 BaiduPCS-Go。"""
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
            "official_login": self.official_login_status(),
        })
        await self.close_official_login_session()
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
        await self._prepare_pcsgo_config(cookie_value)
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
        for key in ("vip_type", "quota_bytes", "used_bytes", "account_cached_at"):
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
            "quota_bytes": _safe_int(account.get("quota_bytes")),
            "used_bytes": _safe_int(account.get("used_bytes")),
            "account_cached_at": _safe_int(account.get("cached_at") or int(time.time())),
        })
        save_config({"baidu_netdisk": cfg})

    async def _fetch_json(self, url: str, cookie: str, timeout: int = 20) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            request = Request(
                url,
                headers={
                    "Cookie": cookie,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            return json.loads(body)

        return await asyncio.to_thread(run)

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
        }

    async def _run_pcsgo(self, args: List[str], *, cwd: str = "", timeout: int = 30) -> Dict[str, Any]:
        config_dir = self._config_dir()
        os.makedirs(config_dir, exist_ok=True)
        command = [self._baidupcs_go_path(), *args]
        env = dict(os.environ)
        env.setdefault("BAIDUPCS_GO_CONFIG_DIR", config_dir)
        env.setdefault("BAIDUPCS_GO_CONFIG_PATH", os.path.join(config_dir, "pcs_config.json"))
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd or None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise BaiduNetdiskError(f"找不到 BaiduPCS-Go: {self._baidupcs_go_path()}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise BaiduNetdiskError("BaiduPCS-Go 执行超时")
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }

    async def _prepare_pcsgo_config(self, cookie: str = "") -> None:
        config_dir = self._config_dir()
        os.makedirs(config_dir, exist_ok=True)
        save_dir = os.path.join(config_dir, "default-save")
        os.makedirs(save_dir, exist_ok=True)
        with contextlib.suppress(Exception):
            await self._run_pcsgo(["config", "set", "-savedir", save_dir], timeout=8)
        cookie_value = str(cookie or getattr(self._config(), "cookie", "") or "").strip()
        if cookie_value and cookie_value != "********":
            proc = await self._run_pcsgo(["login", "-cookies", cookie_value], timeout=30)
            output = f"{proc.get('stdout') or ''}\n{proc.get('stderr') or ''}".strip()
            if proc.get("returncode") != 0 and not self._looks_like_login_already_ok(output):
                raise BaiduNetdiskError(f"BaiduPCS-Go Cookie 登录失败: {output[:300] or proc.get('returncode')}")

    def _looks_like_login_already_ok(self, output: str) -> bool:
        text = str(output or "").lower()
        return any(marker in text for marker in ("登录成功", "login success", "already", "已登录"))

    async def start_download_task(self, task) -> Dict[str, Any]:
        metadata = dict(task.task_metadata or {})
        urls = list(metadata.get("urls") or [])
        preview = await self.preview_urls(
            urls,
            target_subdir=str(metadata.get("target_subdir") or ""),
            conflict_policy=str(metadata.get("conflict_policy") or ""),
            output_folder_name=str(metadata.get("output_folder_name") or ""),
        )
        preview = self.filter_preview_selection(
            preview,
            selected_keys=list(metadata.get("selected_keys") or []),
            selected_items=list(metadata.get("selected_items") or []),
        )
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

        download_files = [
            {
                "gid": item.get("selection_key") or self._selection_key(item),
                "name": item.get("filename") or item.get("name") or "百度网盘分享",
                "relative_path": item.get("relative_path") or "",
                "local_path": "",
                "url": item.get("masked_url") or item.get("share_url") or "",
                "source": BAIDU_NETDISK_PLATFORM,
                "status": "pending",
                "progress": 0,
                "downloaded": 0,
                "total": _safe_int(item.get("size_bytes")),
                "size": _safe_int(item.get("size_bytes")),
                "share_id": item.get("share_id") or "",
                "pass_code": item.get("pass_code") or "",
            }
            for item in items
        ]
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
        started = time.monotonic()

        await self._prepare_pcsgo_config()
        for index, item in enumerate(items):
            await task.wait_if_paused()
            if task.is_cancelled():
                await self.cancel_task(task.id)
                raise asyncio.CancelledError()
            row = download_files[index]
            row["status"] = "downloading"
            self._refresh_runtime(task, download_files, started=started, current=row)
            task.update_progress(max(2, task.progress), f"下载百度网盘 {index + 1}/{len(items)}")
            try:
                await self._download_share_item(task, item, staging_dir, row, download_files, started)
                row["status"] = "completed"
                row["progress"] = 100
            except asyncio.CancelledError:
                if str(getattr(task.status, "value", task.status) or "") == "paused" and not task.is_cancelled():
                    row["status"] = "paused"
                    row["failure_reason"] = "任务已暂停"
                else:
                    row["status"] = "cancelled"
                    await self.cancel_task(task.id)
                raise
            except Exception as exc:
                row["status"] = "failed"
                row["failure_reason"] = self._sanitize_error(exc)
            self._refresh_runtime(task, download_files, started=started, current={})

        success_files = [row for row in download_files if row.get("status") == "completed"]
        failed_files = [row for row in download_files if row.get("status") == "failed"]
        if not success_files:
            task.task_metadata["failed_files"] = failed_files
            raise BaiduNetdiskError(self._first_failure_reason(failed_files) or "没有任何百度网盘文件下载成功")

        finalized = await asyncio.to_thread(self._finalize_output, staging_dir, final_dir, conflict_policy, len(items))
        duration_ms = int((time.monotonic() - started) * 1000)
        downloaded_bytes = self._directory_size(finalized) if os.path.exists(finalized) else 0
        for row in success_files:
            row["local_path"] = finalized
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
        item: Dict[str, Any],
        staging_dir: str,
        row: Dict[str, Any],
        download_files: List[Dict[str, Any]],
        started: float,
    ) -> None:
        await self._set_pcsgo_download_options(staging_dir)
        command = self._build_download_command(item)
        env = dict(os.environ)
        config_dir = self._config_dir()
        env.setdefault("BAIDUPCS_GO_CONFIG_DIR", config_dir)
        env.setdefault("BAIDUPCS_GO_CONFIG_PATH", os.path.join(config_dir, "pcs_config.json"))
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=staging_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise BaiduNetdiskError(f"找不到 BaiduPCS-Go: {self._baidupcs_go_path()}") from exc
        self._task_processes[task.id] = proc
        task.register_process(proc)
        try:
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self._parse_progress_line(line, row)
                self._append_log(task, line)
                self._refresh_runtime(task, download_files, started=started, current=row)
                if task.is_cancelled():
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    raise asyncio.CancelledError()
            returncode = await proc.wait()
            if returncode != 0:
                stop_reason = task.consume_stop_reason()
                if stop_reason in {"pause", "cancel"} or task.is_cancelled():
                    raise asyncio.CancelledError()
                raise BaiduNetdiskError(f"BaiduPCS-Go 下载失败，退出码 {returncode}")
        finally:
            task.unregister_process(proc)
            if self._task_processes.get(task.id) is proc:
                self._task_processes.pop(task.id, None)

    def _build_download_command(self, item: Dict[str, Any]) -> List[str]:
        url = str(item.get("share_url") or item.get("url") or "").strip()
        pass_code = str(item.get("pass_code") or "").strip()
        command = [self._baidupcs_go_path(), "transfer", "--download", "--collect", url]
        if pass_code:
            command.append(pass_code)
        return command

    async def _set_pcsgo_download_options(self, staging_dir: str) -> None:
        cfg = self._config()
        args = ["config", "set", "-savedir", staging_dir]
        max_parallel = max(1, _safe_int(getattr(cfg, "max_parallel", 200), 200))
        args.extend(["-max_parallel", str(max_parallel)])
        max_load = str(getattr(cfg, "max_download_load", "") or "").strip()
        if max_load:
            args.extend(["-max_download_load", max_load])
        with contextlib.suppress(Exception):
            await self._run_pcsgo(args, timeout=10)

    def _parse_progress_line(self, line: str, row: Dict[str, Any]) -> None:
        text = str(line or "")
        percent_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if percent_match:
            row["progress"] = max(0, min(99, int(float(percent_match.group(1)))))
        speed_match = re.search(r"([\d.]+)\s*([KMGT]?i?B|[KMGT]?B)/s", text, re.IGNORECASE)
        if speed_match:
            row["speed_bytes_per_sec"] = self._parse_size(speed_match.group(1), speed_match.group(2))
        size_pair = re.search(
            r"([\d.]+)\s*([KMGT]?i?B|[KMGT]?B)\s*/\s*([\d.]+)\s*([KMGT]?i?B|[KMGT]?B)",
            text,
            re.IGNORECASE,
        )
        if size_pair:
            row["downloaded"] = self._parse_size(size_pair.group(1), size_pair.group(2))
            row["total"] = self._parse_size(size_pair.group(3), size_pair.group(4))
            row["size"] = row["total"]
        name_match = re.search(r"(?:文件|下载|downloading)\s*[:：]\s*(.+)$", text, re.IGNORECASE)
        if name_match:
            row["name"] = name_match.group(1).strip()[:220] or row.get("name")

    def _parse_size(self, value: str, unit: str) -> int:
        try:
            number = float(value)
        except Exception:
            return 0
        normalized = str(unit or "B").upper().replace("IB", "B")
        factors = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 ** 2,
            "GB": 1024 ** 3,
            "TB": 1024 ** 4,
        }
        return int(number * factors.get(normalized, 1))

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
        return re.sub(r"(BDUSS=)[^;\s]+", r"\1***", text)

    async def cancel_task(self, task_id: str) -> None:
        proc = self._task_processes.pop(task_id, None)
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

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
