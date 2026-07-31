import asyncio
import copy
import codecs
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional
from urllib.parse import quote, unquote

import aiohttp

from ..config.settings import get_config, get_config_file_path
from .log_sanitizer import sanitize_text_for_log
from .resource_budget_service import get_resource_budget_service
from .ttl_cache import TTLCache


class LocalUploadVerificationError(RuntimeError):
    """远端上传校验失败：不能删除本地源，也不能把文件标成已上传。"""

    def __init__(self, message: str, *, source_path: str, remote_path: str, failures: list[dict[str, Any]]):
        super().__init__(message)
        self.source_path = source_path
        self.remote_path = remote_path
        self.failures = failures


class LocalUploadCleanupError(RuntimeError):
    """远端已确认上传成功，但本地源清理失败。"""

    def __init__(self, message: str, *, source_path: str, remote_path: str, cleanup_error: str):
        super().__init__(message)
        self.source_path = source_path
        self.remote_path = remote_path
        self.cleanup_error = cleanup_error


class LocalUploadSourceLockedError(RuntimeError):
    """本地源仍被占用，不能开始“上传后删除源”的任务。"""

    def __init__(self, message: str, *, source_path: str, locked_paths: list[dict[str, Any]]):
        super().__init__(message)
        self.source_path = source_path
        self.locked_paths = locked_paths


def _robust_rmtree(path: str, retries: int = 10, delay: float = 1.5) -> None:
    """删除目录树，自动处理只读文件(WinError 5)和文件被占用(WinError 32)。"""

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

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except Exception as exc:
            last_exc = exc
            if getattr(exc, 'winerror', None) == 32 and attempt < retries - 1:
                time.sleep(delay)
                continue
            break
    if last_exc:
        raise last_exc


def _probe_delete_access(path: str) -> Optional[str]:
    if os.name != "nt" or not os.path.exists(path):
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    DELETE_ACCESS = 0x00010000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    flags = FILE_FLAG_BACKUP_SEMANTICS if os.path.isdir(path) else FILE_ATTRIBUTE_NORMAL
    handle = create_file(
        path,
        DELETE_ACCESS,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        flags,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        return f"[WinError {err}] {ctypes.FormatError(err).strip()}"
    close_handle(handle)
    return None


def _collect_delete_locked_paths(path: str, limit: int = 8) -> list[dict[str, Any]]:
    locked: list[dict[str, Any]] = []

    def check_one(target: str):
        if len(locked) >= limit:
            return
        reason = _probe_delete_access(target)
        if reason:
            locked.append({"path": target, "reason": reason})

    if os.path.isfile(path):
        check_one(path)
        return locked

    if os.path.isdir(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for filename in files:
                check_one(os.path.join(root, filename))
                if len(locked) >= limit:
                    return locked
            for dirname in dirs:
                check_one(os.path.join(root, dirname))
                if len(locked) >= limit:
                    return locked
        check_one(path)
    return locked


def _robust_unlink(path: str, retries: int = 10, delay: float = 1.5) -> None:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            os.unlink(path)
            return
        except Exception as exc:
            last_exc = exc
            if getattr(exc, "winerror", None) == 5:
                try:
                    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                    os.unlink(path)
                    return
                except Exception as chmod_exc:
                    last_exc = chmod_exc
            if getattr(exc, "winerror", None) == 32 and attempt < retries - 1:
                time.sleep(delay)
                continue
            break
    if last_exc:
        raise last_exc

logger = logging.getLogger(__name__)

LIBRARY_SEARCH_RESULT_LIMIT = 2000
MOJIBAKE_SOURCE_ENCODINGS = ("gbk", "gb18030", "big5", "utf-8", "latin-1")
MOJIBAKE_TARGET_ENCODINGS = ("cp932", "shift_jis", "utf-8", "gb18030", "big5", "euc_jp")
MOJIBAKE_PROTECTED_SUFFIX_PATTERNS = (
    re.compile(r"(\.part\d+\.(?:rar|zip|7z|exe))$", re.IGNORECASE),
    re.compile(r"(\.part\d+)$", re.IGNORECASE),
    re.compile(r"(\.7z\.\d{3})$", re.IGNORECASE),
    re.compile(r"(\.z\d{2})$", re.IGNORECASE),
    re.compile(r"(\.r\d{2})$", re.IGNORECASE),
)


def _config_file_path() -> str:
    return os.path.abspath(get_config_file_path())


def _stats_cache_file_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "library_stats_cache.json")


def _stats_log_file_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "library_stats.log")


def _gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def _safe_encode_text(value: str, encoding: str) -> Optional[bytes]:
    try:
        return value.encode(encoding, errors="strict")
    except Exception:
        return None


def _safe_decode_text(value: bytes, encoding: str) -> Optional[str]:
    try:
        return value.decode(encoding, errors="strict")
    except Exception:
        return None


def _mojibake_score(text: str) -> int:
    if not text:
        return -999
    score = 0
    if "\ufffd" in text:
        score -= 20
    if re.search(r"[ÃÂÐæçéèêïîöôåäüë鈥鐩鍙彇瀛侀濂彂鍥犺诲悕浜嬩负澶ф湰]", text):
        score -= 10
    if re.search(r"[\u3040-\u309f]", text):
        score += 14
    if re.search(r"[\u30a0-\u30ff]", text):
        score += 14
    if re.search(r"[\u4e00-\u9fff]", text):
        score += 8
    if re.search(r"[A-Za-z0-9]", text):
        score += 2
    if re.search(r"[一-龥]{6,}", text) and not re.search(r"[\u3040-\u30ff]", text):
        score -= 8
    if re.search(r"(Track\d+|トラック\d+)", text, re.IGNORECASE):
        score += 2
    if re.search(r"[僧偺傍價側係價億偉]", text):
        score -= 4
    if re.search(r"[^\w\s\-\.\(\)\[\]{}~!@#$%^&,+=;\u3040-\u30ff\u4e00-\u9fff]", text):
        score -= 2
    return score


def _looks_like_safe_repair(original: str, candidate: str) -> bool:
    original = str(original or "").strip()
    candidate = str(candidate or "").strip()
    if not original or not candidate or original == candidate:
        return False
    original_ext = os.path.splitext(original)[1].lower()
    candidate_ext = os.path.splitext(candidate)[1].lower()
    if original_ext and candidate_ext and original_ext != candidate_ext:
        return False
    delta = _mojibake_score(candidate) - _mojibake_score(original)
    if re.search(r"Track\d+", original, re.IGNORECASE):
        return delta >= 4 and bool(re.search(r"[\u3040-\u30ff]", candidate))
    return delta >= 5


def _guess_mojibake_name_repairs(name: str, *, relaxed: bool = False) -> list[dict[str, Any]]:
    original = str(name or "").strip()
    if not original:
        return []

    protected_suffix = ""
    repair_target = original
    for pattern in MOJIBAKE_PROTECTED_SUFFIX_PATTERNS:
        match = pattern.search(original)
        if not match:
            continue
        protected_suffix = match.group(1)
        repair_target = original[:-len(protected_suffix)]
        break

    if not repair_target:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = {original}
    for source_encoding in MOJIBAKE_SOURCE_ENCODINGS:
        encoded = _safe_encode_text(repair_target, source_encoding)
        if not encoded:
            continue
        for target_encoding in MOJIBAKE_TARGET_ENCODINGS:
            if source_encoding == target_encoding:
                continue
            decoded = _safe_decode_text(encoded, target_encoding)
            if not decoded:
                continue
            candidate = f"{decoded.strip()}{protected_suffix}"
            if candidate in seen:
                continue
            seen.add(candidate)
            if not relaxed and not _looks_like_safe_repair(original, candidate):
                continue
            candidates.append({
                "name": candidate,
                "score": _mojibake_score(candidate),
                "source_encoding": source_encoding,
                "target_encoding": target_encoding,
            })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _track_group_key(relative_path: str) -> str:
    normalized = str(relative_path or "").replace("\\", "/").strip()
    directory = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
    return directory.lower()


def _looks_like_track_bundle(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"track\s*\d+", text, re.IGNORECASE)
        and re.search(r"(?:~|-|〜|～|to)\s*track\s*\d+", text, re.IGNORECASE)
    )


def _extract_title_from_readme_text(text: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    quoted = re.search(r"「([^」]{4,200})」", content)
    if quoted:
        return quoted.group(1).strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines[:8]:
        if len(line) >= 6 and re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", line):
            return line
    return ""


def _guess_local_title_from_readme(parent_dir: str) -> str:
    if not parent_dir or not os.path.isdir(parent_dir):
        return ""
    for candidate_name in ("readme.txt", "README.txt", "Readme.txt"):
        candidate_path = os.path.join(parent_dir, candidate_name)
        if not os.path.isfile(candidate_path):
            continue
        for encoding in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "gb18030"):
            try:
                with open(candidate_path, "r", encoding=encoding, errors="strict") as handle:
                    return _extract_title_from_readme_text(handle.read())
            except Exception:
                continue
    return ""


def _is_audio_filename(name: str) -> bool:
    return bool(re.search(r"\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$", str(name or ""), re.IGNORECASE))


def _source_name_suspiciousness(name: str) -> int:
    text = str(name or "").strip()
    if not text:
        return -999
    score = 0
    if _looks_like_track_bundle(text):
        score += 5
    if _is_audio_filename(text):
        score += 3
    if re.search(r"Track\d+", text, re.IGNORECASE):
        score += 3
    base_name = os.path.splitext(text)[0]
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]+", base_name)
    if cjk_chunks:
        longest = max(len(chunk) for chunk in cjk_chunks)
        if longest <= 3:
            score += 4
    if re.search(r"[A-Za-z0-9].*[\u4e00-\u9fff]|[\u4e00-\u9fff].*[A-Za-z0-9]", text):
        score += 2
    return score


SYNOLOGY_COMMON_ERROR_MESSAGES: dict[int, str] = {
    100: "未知错误",
    101: "参数错误",
    102: "API not found",
    103: "Method not found",
    104: "API version not supported",
    105: "当前账号权限不足",
    106: "Login session expired, please sign in again",
    107: "Login session interrupted, please sign in again",
}

SYNOLOGY_AUTH_ERROR_MESSAGES: dict[int, str] = {
    400: "Invalid username or password",
    401: "Account disabled",
    402: "账号权限不足",
    403: "需要二步验证或设备验证",
    404: "OTP verification failed",
}

SYNOLOGY_FILESTATION_ERROR_MESSAGES: dict[int, str] = {
    117: "Target file or folder already exists",
    118: "Target file or folder does not exist or was moved",
    119: "目标路径无效、不存在，或当前账号无权访问",
    408: "FileStation 请求超时或远程服务繁忙",
    414: "目标文件已存在",
}

SYNOLOGY_REMOTE_DEGRADED_ERROR_CODES = {408}


def _synology_error_message(api: str, code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    if code in SYNOLOGY_COMMON_ERROR_MESSAGES:
        return SYNOLOGY_COMMON_ERROR_MESSAGES[code]
    if api == "SYNO.API.Auth":
        return SYNOLOGY_AUTH_ERROR_MESSAGES.get(code)
    if api.startswith("SYNO.FileStation."):
        return SYNOLOGY_FILESTATION_ERROR_MESSAGES.get(code)
    return None


def _format_synology_error(api: str, action: str, data: dict[str, Any]) -> str:
    error = data.get("error") or {}
    code = error.get("code")
    readable = _synology_error_message(api, code)
    code_text = f"code {code}" if code is not None else "unknown code"
    if readable:
        return f"Synology {action} failed ({code_text}: {readable}): {json.dumps(data, ensure_ascii=False)}"
    return f"Synology {action} failed ({code_text}): {json.dumps(data, ensure_ascii=False)}"


class SynologyError(RuntimeError):
    """群晖 API 通信错误（可预期的认证/权限/参数/超时错误）。日志只打 WARNING，不打堆栈。"""


class SynologyTransportError(SynologyError):
    """群晖远程连接错误（DNS/TCP/TLS/超时/断连）。"""


@dataclass
class SynologyConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    root_path: str = "/"
    session_name: str = "FileStation"
    timeout: int = 30
    verify_ssl: bool = True
    otp_code: str = ""
    device_name: str = ""
    device_id: str = ""
    enable_device_token: bool = True


@dataclass
class LibraryDefinition:
    id: str
    name: str
    type: str = "local"
    path: str = ""
    browse_path: str = ""
    enabled: bool = True
    writable: bool = True
    description: str = ""
    tags: list[str] = field(default_factory=list)
    synology_profile_id: str = ""
    synology: Optional[SynologyConfig] = None

    @property
    def root_path(self) -> str:
        if self.type == "synology_filestation" and self.synology:
            return self.synology.root_path or self.path or "/"
        return self.path

    @property
    def browse_root_path(self) -> str:
        browse_path = self.browse_path or ""
        if self.type == "synology_filestation":
            return browse_path or self.root_path or "/"
        return browse_path or self.root_path


def load_library_config() -> dict[str, Any]:
    runtime_config = get_config().storage
    storage = runtime_config.model_dump()
    profile_map = {
        str(item.get("id") or "").strip(): copy.deepcopy(item)
        for item in storage.get("synology_profiles") or []
        if str(item.get("id") or "").strip()
    }

    libraries: list[LibraryDefinition] = []
    for item in storage.get("libraries") or []:
        synology_profile_id = str(item.get("synology_profile_id") or "").strip()
        profile_raw = copy.deepcopy(profile_map.get(synology_profile_id) or {})
        profile_raw.pop("id", None)
        profile_raw.pop("name", None)
        synology_raw = copy.deepcopy(item.get("synology") or {})
        if (item.get("type") or "local").lower() == "synology_filestation":
            root_path = synology_raw.get("root_path") or item.get("path") or "/"
            if synology_profile_id:
                # 绑定模板的远程库存只允许库存自身覆盖目录路径。
                # 认证相关字段统一以模板为准，避免库存条目残留旧密码 / 旧 OTP / 旧 device_id。
                merged = {
                    **synology_raw,
                    **profile_raw,
                    "root_path": root_path,
                }
            else:
                merged = {
                    **synology_raw,
                    "root_path": root_path,
                }
            synology_raw = merged
        else:
            synology_raw = None
        synology = SynologyConfig(**synology_raw) if synology_raw else None
        libraries.append(
            LibraryDefinition(
                id=item["id"],
                name=item.get("name") or item["id"],
                type=(item.get("type") or "local").lower(),
                path=item.get("path") or "",
                browse_path=item.get("browse_path") or "",
                enabled=item.get("enabled", True),
                writable=item.get("writable", True),
                description=item.get("description") or "",
                tags=item.get("tags") or [],
                synology_profile_id=synology_profile_id,
                synology=synology,
            )
        )

    active_libraries = [library for library in libraries if library.enabled] or libraries

    if not libraries:
        libraries = [
            LibraryDefinition(
                id="default-local",
                name="默认库存",
                type="local",
                path=runtime_config.library_path,
                browse_path="",
                enabled=True,
                writable=True,
            )
        ]
        active_libraries = libraries

    return {
        "libraries": libraries,
        "default_library_id": storage.get("default_library_id") or active_libraries[0].id,
        "default_extract_library_id": storage.get("default_extract_library_id") or storage.get("default_library_id") or active_libraries[0].id,
        "health_warning_free_gb": storage.get("health_warning_free_gb", 200.0),
        "stats_cache_ttl_seconds": storage.get("stats_cache_ttl_seconds", 300),
        "remote_search_cache_ttl_seconds": storage.get("remote_search_cache_ttl_seconds", 60),
    }


class SynologyFileStationClient:
    def __init__(self, config: SynologyConfig):
        self.config = config
        self._sid: Optional[str] = None
        self._device_id: str = config.device_id or ""
        self._api_info_cache: dict[str, tuple[str, int]] = {}
        self._preferred_upload_variant_name: Optional[str] = "minimal_form"
        # 持久化 HTTP session，避免每次请求重建 TCP 连接
        self._session: Optional[aiohttp.ClientSession] = None
        self._remote_failures = 0
        self._remote_circuit_until = 0.0

    @staticmethod
    def build_cache_auth_signature(config: SynologyConfig) -> str:
        return "|".join([
            str(config.password or ""),
            str(config.otp_code or ""),
            str(config.device_id or ""),
            str(config.device_name or ""),
            str(config.session_name or ""),
            "1" if bool(config.enable_device_token) else "0",
        ])

    def _ensure_session(self) -> aiohttp.ClientSession:
        """返回持久化 HTTP session，不存在或已关闭时重建。"""
        if self._session is None or self._session.closed:
            timeout_value = int(self.config.timeout or 0)
            timeout = aiohttp.ClientTimeout(total=None if timeout_value <= 0 else timeout_value)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _remote_circuit_remaining_seconds(self) -> float:
        return max(0.0, self._remote_circuit_until - time.monotonic())

    def _is_transport_error(self, exc: Exception) -> bool:
        if isinstance(exc, (FileNotFoundError, PermissionError)):
            return False
        if isinstance(exc, SynologyTransportError):
            return True
        if isinstance(exc, SynologyError) and self._synology_error_code(exc) in SYNOLOGY_REMOTE_DEGRADED_ERROR_CODES:
            return True
        return isinstance(exc, (
            aiohttp.ClientError,
            ConnectionError,
            TimeoutError,
            asyncio.TimeoutError,
        ))

    def _wrap_transport_error(self, api: str, action: str, exc: Exception) -> SynologyError:
        base_url = str(self.config.base_url or "").rstrip("/")
        detail = str(exc) or exc.__class__.__name__
        if isinstance(exc, aiohttp.ClientSSLError):
            return SynologyTransportError(f"群晖{action}失败：TLS/SSL 握手失败（{detail}）")
        if isinstance(exc, aiohttp.ClientConnectorError):
            host = getattr(exc, "host", None) or ""
            port = getattr(exc, "port", None) or ""
            target = f"{host}:{port}" if host and port else base_url
            return SynologyTransportError(f"群晖{action}失败：无法连接到 {target}（{detail}）")
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return SynologyTransportError(f"群晖{action}失败：请求超时（{detail}）")
        if isinstance(exc, (aiohttp.ClientConnectionError, ConnectionError)):
            return SynologyTransportError(f"群晖{action}失败：连接被中断（{detail}）")
        if isinstance(exc, aiohttp.ClientError):
            return SynologyTransportError(f"群晖{action}失败：HTTP 客户端错误（{detail}）")
        return SynologyTransportError(f"群晖{action}失败：远程通信异常（{detail}）")

    def _raise_wrapped_transport_error(self, api: str, action: str, exc: Exception) -> None:
        if isinstance(exc, SynologyError):
            if not getattr(exc, "_remote_failure_recorded", False):
                self._record_remote_failure(api, exc)
                setattr(exc, "_remote_failure_recorded", True)
            raise exc
        if not self._is_transport_error(exc):
            raise exc
        wrapped = self._wrap_transport_error(api, action, exc)
        self._record_remote_failure(api, wrapped)
        setattr(wrapped, "_remote_failure_recorded", True)
        raise wrapped from exc

    def _synology_error_code(self, exc: Exception) -> Optional[int]:
        message = str(exc or "")
        patterns = [
            r"code\s+(\d+)\b",
            r'"code"\s*:\s*(\d+)\b',
            r"'code'\s*:\s*(\d+)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
        return None

    def _record_remote_failure(self, api: str, exc: Exception) -> None:
        if not self._is_transport_error(exc):
            return
        self._remote_failures += 1
        timeout_seconds = max(30.0, min(180.0, 15.0 * self._remote_failures))
        self._remote_circuit_until = time.monotonic() + timeout_seconds
        logger.warning(
            "[远程库存] %s 失败，已熔断 %.0f 秒 (failures=%s): %s",
            api,
            timeout_seconds,
            self._remote_failures,
            exc,
        )

    def _record_remote_success(self) -> None:
        if self._remote_failures or self._remote_circuit_until:
            self._remote_failures = 0
            self._remote_circuit_until = 0.0

    def _check_remote_circuit(self, api: str) -> None:
        remaining = self._remote_circuit_remaining_seconds()
        if remaining <= 0:
            return
        if api in {"SYNO.API.Auth"}:
            return
        raise SynologyError(f"远程库存暂时退化，已熔断 {remaining:.0f} 秒后重试")

    def remote_health_snapshot(self) -> dict[str, Any]:
        remaining = self._remote_circuit_remaining_seconds()
        session_open = bool(self._session and not self._session.closed)
        return {
            "status": "degraded" if remaining > 0 else "healthy",
            "failure_count": int(self._remote_failures or 0),
            "circuit_remaining_seconds": int(round(remaining)),
            "session_open": session_open,
            "has_sid": bool(self._sid),
        }

    async def close(self) -> None:
        """关闭持久化 HTTP session（可选，进程退出时 GC 会处理）。"""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _read_response_payload(self, response: aiohttp.ClientResponse, api: str) -> dict[str, Any]:
        try:
            return await response.json(content_type=None)
        except Exception as exc:
            body = await response.text()
            try:
                return json.loads(body)
            except Exception as decode_exc:
                content_type = response.headers.get("Content-Type", "")
                snippet = (body or "").strip().replace("\n", " ")
                snippet = snippet[:200]
                raise SynologyError(
                    f"群晖 FileStation 响应解析失败: API={api}, HTTP {response.status}, Content-Type={content_type}, Body={snippet}"
                ) from decode_exc

    async def _request(self, api: str, method: str, version: int, params: dict[str, Any], files=None):
        self._check_remote_circuit(api)
        # 最多重试一次：第一次如遇 SID 过期（code 119）自动重登录后重试
        async with get_resource_budget_service().acquire("remote_fs", reason=f"synology.{api}.{method}"):
            started = time.perf_counter()
            try:
                for _attempt in range(2):
                    session = self._ensure_session()
                    if not self._sid and api != "SYNO.API.Auth":
                        await self._login(session)

                    payload = {"api": api, "method": method, "version": str(version), **params}
                    if self._sid and api != "SYNO.API.Auth":
                        payload["_sid"] = self._sid

                    url = f"{self.config.base_url.rstrip('/')}/webapi/entry.cgi"
                    if files:
                        form = aiohttp.FormData()
                        query_payload = {
                            "api": api,
                            "method": method,
                            "version": str(version),
                        }
                        if self._sid and api != "SYNO.API.Auth":
                            query_payload["_sid"] = self._sid
                        for key, value in params.items():
                            form.add_field(key, str(value))
                        for file_key, file_value in files:
                            form.add_field(file_key, file_value[0], filename=file_value[1], content_type="application/octet-stream")
                        async with session.post(url, params=query_payload, data=form, ssl=self.config.verify_ssl) as response:
                            data = await self._read_response_payload(response, api)
                    else:
                        async with session.get(url, params=payload, ssl=self.config.verify_ssl) as response:
                            data = await self._read_response_payload(response, api)

                    if not data.get("success"):
                        error_code = int((data.get("error") or {}).get("code") or 0)
                        if _attempt == 0 and error_code == 119:
                            # SID 过期 — 清除 SID，下一轮循环重新登录
                            logger.info("群晖 SID 过期（code 119），自动重新登录: api=%s", api)
                            self._sid = None
                            continue
                        raise SynologyError(_format_synology_error(api, "\u6587\u4ef6\u7ad9\u8bf7\u6c42", data))
                    self._record_remote_success()
                    elapsed = time.perf_counter() - started
                    if elapsed >= 2.0:
                        logger.info("[远程库存] 慢请求 %s.%s %.0fms", api, method, elapsed * 1000)
                    return data.get("data") or {}
            except Exception as exc:
                self._raise_wrapped_transport_error(api, "文件站请求", exc)
        return {}  # 不可达，仅供类型检查器

    async def stream_download(self, path: str, *, chunk_size: int = 1024 * 256):
        """从群晖 FileStation 流式读取单个文件。"""
        normalized_path = str(PurePosixPath(path or "/"))
        self._check_remote_circuit("SYNO.FileStation.Download")
        for attempt in range(2):
            async with get_resource_budget_service().acquire("remote_fs", reason="synology.download"):
                try:
                    session = self._ensure_session()
                    if not self._sid:
                        await self._login(session)

                    api_path, api_version = await self._resolve_api_route(
                        session,
                        "SYNO.FileStation.Download",
                        default_path="entry.cgi",
                        default_version=2,
                    )
                    url = f"{self.config.base_url.rstrip('/')}/webapi/{api_path.lstrip('/')}"
                    params = {
                        "api": "SYNO.FileStation.Download",
                        "method": "download",
                        "version": str(api_version),
                        "path": normalized_path,
                        "mode": "open",
                        "_sid": self._sid,
                    }
                    async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
                        content_type = str(response.headers.get("Content-Type") or "").lower()
                        if "application/json" in content_type or "text/json" in content_type:
                            data = await self._read_response_payload(response, "SYNO.FileStation.Download")
                            error_code = int((data.get("error") or {}).get("code") or 0)
                            if attempt == 0 and error_code == 119:
                                logger.info("群晖 SID 过期（code 119），自动重新登录: api=%s", "SYNO.FileStation.Download")
                                self._sid = None
                                continue
                            raise SynologyError(_format_synology_error("SYNO.FileStation.Download", "下载文件", data))
                        if response.status >= 400:
                            snippet = (await response.text()).strip()[:200]
                            raise SynologyError(f"群晖文件下载失败: HTTP {response.status} {snippet}")
                        self._record_remote_success()
                        async for chunk in response.content.iter_chunked(chunk_size):
                            if chunk:
                                yield chunk
                        return
                except Exception as exc:
                    self._raise_wrapped_transport_error("SYNO.FileStation.Download", "下载文件", exc)

    def _is_error_code(self, exc: Exception, code: int) -> bool:
        message = str(exc)
        patterns = [
            rf'浠ｇ爜\s*{code}\b',
            rf'"code"\s*:\s*{code}\b',
            rf"'code'\s*:\s*{code}\b",
        ]
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)

    def _first_info_item(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        files = data.get("files") or []
        return files[0] if files else None

    async def _get_remote_file_info_if_exists(self, path: str) -> Optional[dict[str, Any]]:
        normalized_path = str(PurePosixPath(path or "/"))
        try:
            info = await self.stat(normalized_path)
            return self._first_info_item(info)
        except Exception:
            return None

    def _is_retryable_upload_error(self, exc: Exception) -> bool:
        if isinstance(exc, (aiohttp.ClientConnectionError, ConnectionError, TimeoutError, asyncio.TimeoutError)):
            return True
        message = str(exc or "")
        lowered = message.lower()
        return any(token in lowered for token in [
            "winerror 64",
            "指定的网络名不再可用",
            "connection lost",
            "connection reset",
            "server disconnected",
            "broken pipe",
            "cannot write request body",
            "timeout",
        ])

    async def _remote_file_matches_local_size(self, path: str, local_file_size: int) -> bool:
        remote_info = await self._get_remote_file_info_if_exists(path)
        remote_size = int((remote_info or {}).get("additional", {}).get("size") or (remote_info or {}).get("size") or 0)
        return remote_size > 0 and remote_size == local_file_size

    async def _post_file_upload(
        self,
        session: aiohttp.ClientSession,
        url: str,
        api_name: str,
        query_params: dict[str, Any],
        form_fields: dict[str, Any],
        local_path: str,
        remote_name: Optional[str] = None,
        *,
        quote_fields: bool = False,
        include_content_type: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> dict[str, Any]:
        file_name = remote_name or os.path.basename(local_path)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"待上传本地文件不存在: {local_path}")

        boundary = f"----CodexSynology{uuid.uuid4().hex}"
        file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        preamble = bytearray()
        for key, value in form_fields.items():
            preamble.extend(f"--{boundary}\r\n".encode("utf-8"))
            preamble.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            preamble.extend(str(value).encode("utf-8"))
            preamble.extend(b"\r\n")

        preamble.extend(f"--{boundary}\r\n".encode("utf-8"))
        preamble.extend(f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"))
        if include_content_type:
            preamble.extend(b"Content-Type: application/octet-stream\r\n")
        preamble.extend(b"\r\n")
        epilogue = b"\r\n" + f"--{boundary}--\r\n".encode("utf-8")

        async def body_iter():
            uploaded = 0
            handle = None
            try:
                yield bytes(preamble)
                handle = open(local_path, "rb")
                while True:
                    chunk = handle.read(1024 * 256)
                    if not chunk:
                        break
                    yield chunk
                    uploaded += len(chunk)
                    if progress_callback:
                        progress_callback(uploaded, file_size)
                handle.close()
                handle = None
                yield epilogue
            finally:
                if handle is not None:
                    handle.close()

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            # DSM / 公网反代对 chunked multipart upload 很敏感；显式长度能避免
            # aiohttp 走 Transfer-Encoding: chunked 后被对端提前断开。
            "Content-Length": str(len(preamble) + file_size + len(epilogue)),
            "Connection": "close",
        }

        body = body_iter()
        try:
            async with session.post(url, params=query_params, data=body, headers=headers, ssl=self.config.verify_ssl) as response:
                data = await self._read_response_payload(response, api_name)
        finally:
            await body.aclose()
            await asyncio.sleep(0)

        if not data.get("success"):
            raise SynologyError(_format_synology_error(api_name, "\u6587\u4ef6\u7ad9\u8bf7\u6c42", data))
        return data.get("data") or {}

    async def _resolve_api_route(self, session: aiohttp.ClientSession, api_name: str, default_path: str = "entry.cgi", default_version: int = 2) -> tuple[str, int]:
        cached = self._api_info_cache.get(api_name)
        if cached:
            return cached

        url = f"{self.config.base_url.rstrip('/')}/webapi/query.cgi"
        params = {
            "api": "SYNO.API.Info",
            "method": "query",
            "version": "1",
            "query": api_name,
        }
        try:
            async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
                data = await self._read_response_payload(response, "SYNO.API.Info")
        except SynologyError:
            raise
        except Exception as exc:
            self._raise_wrapped_transport_error("SYNO.API.Info", "查询 API 信息", exc)

        path = default_path
        version = default_version
        if data.get("success"):
            info = (data.get("data") or {}).get(api_name) or {}
            raw_path = str(info.get("path") or default_path).lstrip("/")
            path = raw_path or default_path
            version = int(info.get("maxVersion") or default_version)

        resolved = (path, version)
        self._api_info_cache[api_name] = resolved
        return resolved

    async def _login(self, session: aiohttp.ClientSession):
        url = f"{self.config.base_url.rstrip('/')}/webapi/auth.cgi"
        params = {
            "api": "SYNO.API.Auth",
            "method": "login",
            "version": "6",
            "account": self.config.username,
            "passwd": self.config.password,
            "session": self.config.session_name,
            "format": "sid",
        }
        if self.config.otp_code:
            params["otp_code"] = self.config.otp_code
        if self.config.device_name:
            params["device_name"] = self.config.device_name
        if self.config.device_id:
            params["device_id"] = self.config.device_id
        if self.config.enable_device_token:
            params["enable_device_token"] = "yes"
        try:
            async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
                data = await self._read_response_payload(response, "SYNO.API.Auth")
        except SynologyError:
            self._sid = None
            raise
        except Exception as exc:
            self._sid = None
            self._raise_wrapped_transport_error("SYNO.API.Auth", "登录", exc)
        if not data.get("success") and (data.get("error") or {}).get("code") == 403:
            auth_errors = (data.get("error") or {}).get("errors") or {}
            auth_types = [item.get("type") for item in auth_errors.get("types") or [] if item.get("type")]
            if "otp" in auth_types:
                raise SynologyError(f"\u7fa4\u6656\u767b\u5f55\u5931\u8d25\uff08\u4ee3\u7801 403\uff1a\u9700\u8981\u4e8c\u6b65\u9a8c\u8bc1\uff0c\u8bf7\u586b\u5199\u4e00\u6b21\u6027\u9a8c\u8bc1\u7801 OTP\uff09: {json.dumps(data, ensure_ascii=False)}")
        if not data.get("success"):
            raise SynologyError(_format_synology_error("SYNO.API.Auth", "\u767b\u5f55", data))
        login_data = data.get("data") or {}
        self._sid = login_data.get("sid")
        self._device_id = login_data.get("did") or self._device_id
        if not self._sid:
            raise SynologyError("\u7fa4\u6656\u767b\u5f55\u6210\u529f\u4f46\u672a\u8fd4\u56de sid")

    @property
    def device_id(self) -> str:
        return self._device_id

    async def get_storage_info(self, root_path: str) -> dict[str, Any]:
        normalized_root = "/" + str(root_path or "").strip().strip("/")
        share_name = normalized_root.strip("/").split("/", 1)[0]
        if not share_name:
            raise SynologyError("库存根路径未指定群晖共享文件夹，无法确定所属存储空间")

        data = await self._request(
            "SYNO.FileStation.List",
            "list_share",
            2,
            {
                "offset": 0,
                "limit": 1000,
                "sort_by": "name",
                "sort_direction": "asc",
                "additional": '["volume_status"]',
            },
        )
        matched_share: Optional[dict[str, Any]] = None
        for item in data.get("shares") or []:
            if not isinstance(item, dict):
                continue
            item_path = "/" + str(item.get("path") or item.get("name") or "").strip().strip("/")
            if item_path.casefold() == f"/{share_name}".casefold():
                matched_share = item
                break
        if matched_share is None:
            raise SynologyError(f"未找到库存根路径对应的群晖共享文件夹: /{share_name}")

        additional = matched_share.get("additional") or {}
        volume_status = additional.get("volume_status") or matched_share.get("volume_status") or {}
        if not isinstance(volume_status, dict):
            volume_status = {}
        total_size = max(0, int(volume_status.get("totalspace") or volume_status.get("total_size") or 0))
        free_size = max(0, int(volume_status.get("freespace") or volume_status.get("free_size") or 0))
        if total_size <= 0:
            raise SynologyError(f"群晖未返回共享文件夹 /{share_name} 所属存储空间的容量")
        free_size = min(free_size, total_size)
        used_size = max(0, total_size - free_size)
        normalized_volume = {
            **volume_status,
            "total_size": total_size,
            "used_size": used_size,
            "free_size": free_size,
        }
        return {
            "total_size_bytes": total_size,
            "used_size_bytes": used_size,
            "free_size_bytes": free_size,
            "free_space_gb": round(free_size / (1024 ** 3), 2) if free_size > 0 else 0,
            "storage_scope": "share_volume",
            "share_name": str(matched_share.get("name") or share_name),
            "share_path": str(matched_share.get("path") or f"/{share_name}"),
            "volumes": [normalized_volume],
        }

    async def test_connection(self, folder_path: str) -> dict[str, Any]:
        if folder_path in ("", "/"):
            await self.list_share(offset=0, limit=1, sort_by="name", sort_direction="asc")
        else:
            await self.list(folder_path, offset=0, limit=1, sort_by="name", sort_direction="asc")
        return {
            "device_id": self.device_id,
            "web_url": build_synology_web_url(self.config.base_url, folder_path),
        }

    async def list(self, folder_path: str, offset: int = 0, limit: int = 200, sort_by: str = "name", sort_direction: str = "asc"):
        return await self._request(
            "SYNO.FileStation.List",
            "list",
            2,
            {
                "folder_path": folder_path,
                "offset": offset,
                "limit": limit,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "additional": '["time","size"]',
            },
        )

    async def list_share(self, offset: int = 0, limit: int = 200, sort_by: str = "name", sort_direction: str = "asc"):
        return await self._request(
            "SYNO.FileStation.List",
            "list_share",
            2,
            {
                "offset": offset,
                "limit": limit,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "additional": '["time","size"]',
            },
        )

    async def start_search(self, folder_path: str, keyword: str, recursive: bool = True):
        # 群晖 FileStation Search 的 pattern 是 glob 模式（默认完整匹配），
        # 要让它做"包含"匹配必须显式包通配符；否则像 [社团][RJ01214501] 这种
        # 含 RJ 号的文件夹会被判定为不匹配。
        raw_pattern = str(keyword or "").strip()
        pattern = raw_pattern
        if pattern and "*" not in pattern and "?" not in pattern:
            pattern = f"*{pattern}*"
        return await self._request(
            "SYNO.FileStation.Search",
            "start",
            2,
            {
                "folder_path": folder_path,
                "pattern": pattern,
                "recursive": "true" if recursive else "false",
            },
        )

    async def search_status(self, taskid: str):
        return await self._request(
            "SYNO.FileStation.Search",
            "status",
            2,
            {
                "taskid": taskid,
            },
        )

    async def list_search(self, taskid: str, offset: int = 0, limit: int = 200, sort_by: str = "name", sort_direction: str = "asc"):
        return await self._request(
            "SYNO.FileStation.Search",
            "list",
            2,
            {
                "taskid": taskid,
                "offset": offset,
                "limit": limit,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "additional": '["time","size","real_path"]',
            },
        )

    async def stop_search(self, taskid: str):
        return await self._request(
            "SYNO.FileStation.Search",
            "stop",
            2,
            {
                "taskid": taskid,
            },
        )

    async def stat(self, path: str):
        return await self._request(
            "SYNO.FileStation.List",
            "getinfo",
            2,
            {
                "path": f'["{path}"]',
                "additional": '["real_path","size","time","perm"]',
            },
        )

    async def start_dir_size(self, path: str):
        return await self._request(
            "SYNO.FileStation.DirSize",
            "start",
            2,
            {
                "path": f'"{path}"',
            },
        )

    async def dir_size_status(self, taskid: str):
        return await self._request(
            "SYNO.FileStation.DirSize",
            "status",
            2,
            {
                "taskid": f'"{taskid}"',
            },
        )

    async def create_folder(self, parent_path: str, name: str):
        normalized_parent = str(PurePosixPath(parent_path or "/"))
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        variants = [
            {
                "folder_path": normalized_parent,
                "name": name,
                "force_parent": "true",
            },
            {
                "folder_path": f'["{normalized_parent}"]',
                "name": f'["{name}"]',
                "force_parent": "true",
            },
            {
                "folder_path": normalized_parent,
                "name": name,
            },
            {
                "folder_path": f'["{normalized_parent}"]',
                "name": name,
            },
        ]
        last_error: Optional[Exception] = None

        session = self._ensure_session()
        if not self._sid:
            await self._login(session)
        api_path, api_version = await self._resolve_api_route(session, "SYNO.FileStation.CreateFolder", default_path="entry.cgi", default_version=2)
        url = f"{self.config.base_url.rstrip('/')}/webapi/{api_path.lstrip('/')}"
        for variant in variants:
            params = {
                "api": "SYNO.FileStation.CreateFolder",
                "method": "create",
                "version": str(api_version),
                **variant,
            }
            if self._sid:
                params["_sid"] = self._sid
            try:
                async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
                    data = await self._read_response_payload(response, "SYNO.FileStation.CreateFolder")
                if not data.get("success"):
                    raise SynologyError(_format_synology_error("SYNO.FileStation.CreateFolder", "create folder", data))
                return data.get("data") or {}
            except Exception as exc:
                last_error = exc
                if not (self._is_error_code(exc, 101) or self._is_error_code(exc, 119)):
                    continue

        if last_error:
            raise last_error
        raise SynologyError("群晖创建目录失败")

    async def rename(self, path: str, new_name: str):
        return await self._request(
            "SYNO.FileStation.Rename",
            "rename",
            2,
            {
                "path": f'["{path}"]',
                "name": f'["{new_name}"]',
            },
        )

    async def delete(self, path: str):
        return await self._request(
            "SYNO.FileStation.Delete",
            "delete",
            2,
            {
                "path": f'["{path}"]',
                "accurate_progress": "true",
            },
        )

    async def copy(self, path: str, dest_folder_path: str, overwrite: bool = True):
        task = await self._request(
            "SYNO.FileStation.CopyMove",
            "start",
            3,
            {
                "path": f'["{path}"]',
                "dest_folder_path": f'"{dest_folder_path}"',
                "remove_src": "false",
                "overwrite": "true" if overwrite else "false",
                "accurate_progress": "true",
            },
        )
        task_id = task.get("taskid")
        if task_id:
            await self._wait_copy_move_task(str(task_id))
        return task

    async def move(self, path: str, dest_folder_path: str, overwrite: bool = True):
        task = await self._request(
            "SYNO.FileStation.CopyMove",
            "start",
            3,
            {
                "path": f'["{path}"]',
                "dest_folder_path": f'"{dest_folder_path}"',
                "remove_src": "true",
                "overwrite": "true" if overwrite else "false",
                "accurate_progress": "true",
            },
        )
        task_id = task.get("taskid")
        if task_id:
            await self._wait_copy_move_task(str(task_id))
        return task

    async def _wait_copy_move_task(self, task_id: str, timeout_seconds: int = 300):
        started = time.time()
        last_status = None
        while time.time() - started <= max(10, timeout_seconds):
            status = await self._request(
                "SYNO.FileStation.CopyMove",
                "status",
                3,
                {
                    "taskid": f'"{task_id}"',
                },
            )
            last_status = status
            finished = bool(status.get("finished")) or bool(status.get("result"))
            if finished:
                return status
            await asyncio.sleep(1.0)
        raise SynologyError(f"Synology CopyMove task timed out: {task_id}, status={last_status}")

    async def upload_file(
        self,
        dest_folder: str,
        local_path: str,
        overwrite: bool = False,
        remote_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        self._check_remote_circuit("SYNO.FileStation.Upload")
        normalized_path = str(PurePosixPath(dest_folder or "/"))
        overwrite_value = "true" if overwrite else "false"
        local_file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        connect_timeout = max(10, int(self.config.timeout or 30))
        if local_file_size <= 10 * 1024 * 1024:
            response_timeout = max(30, min(45, connect_timeout * 2))
        else:
            response_timeout = max(90, connect_timeout * 6)
        estimated_transfer_timeout = (local_file_size // (512 * 1024)) + 180 if local_file_size > 0 else 180
        total_timeout = max(response_timeout, connect_timeout * 4, estimated_transfer_timeout)
        total_timeout = min(max(total_timeout, 180), 6 * 60 * 60)
        timeout = aiohttp.ClientTimeout(
            total=total_timeout,
            connect=connect_timeout,
            sock_connect=connect_timeout,
            sock_read=response_timeout,
        )
        payload_variants = [
            {
                "name": "minimal_form",
                "query": {},
                "form": {
                    "path": normalized_path,
                    "overwrite": overwrite_value,
                },
                "quote_fields": True,
                "include_content_type": False,
                "include_sid": True,
            },
            {
                "name": "query_only",
                "query": {"path": normalized_path, "overwrite": overwrite_value},
                "form": {},
                "quote_fields": True,
                "include_content_type": False,
                "include_sid": True,
            },
            {
                "name": "content_type_form",
                "query": {},
                "form": {
                    "path": normalized_path,
                    "overwrite": overwrite_value,
                },
                "quote_fields": False,
                "include_content_type": True,
                "include_sid": True,
            },
            {
                "name": "no_sid_form",
                "query": {},
                "form": {
                    "path": normalized_path,
                    "overwrite": overwrite_value,
                },
                "quote_fields": True,
                "include_content_type": True,
                "include_sid": False,
            },
            {
                "name": "json_path_form",
                "query": {},
                "form": {
                    "path": f'["{normalized_path}"]',
                    "overwrite": overwrite_value,
                },
                "quote_fields": True,
                "include_content_type": True,
                "include_sid": True,
            },
            {
                "name": "create_parents_form",
                "query": {},
                "form": {
                    "path": normalized_path,
                    "create_parents": "true",
                    "overwrite": overwrite_value,
                },
                "quote_fields": True,
                "include_content_type": False,
                "include_sid": True,
            },
            {
                "name": "duplicate_api_fields",
                "query": {},
                "form": {
                    "api": "SYNO.FileStation.Upload",
                    "method": "upload",
                    "version": "2",
                    "_sid": "",
                    "path": normalized_path,
                    "overwrite": overwrite_value,
                },
                "quote_fields": True,
                "include_content_type": False,
                "include_sid": True,
            },
        ]
        preferred_variant_name = str(self._preferred_upload_variant_name or "").strip()
        per_variant_retry_limit = 3
        if preferred_variant_name:
            logger.debug("[SynologyUpload] 命中已缓存成功变体: %s", preferred_variant_name)
            payload_variants = sorted(
                payload_variants,
                key=lambda item: (
                    0 if item.get("name") == "minimal_form" else
                    1 if item.get("name") == preferred_variant_name else
                    2
                ),
            )
        last_error: Optional[Exception] = None
        file_name = remote_name or os.path.basename(local_path)
        remote_file_path = str(PurePosixPath(normalized_path) / file_name)
        local_file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

        async with aiohttp.ClientSession(timeout=timeout) as session:
            if not self._sid:
                await self._login(session)
            api_path, api_version = await self._resolve_api_route(session, "SYNO.FileStation.Upload", default_path="entry.cgi", default_version=2)
            upload_url = f"{self.config.base_url.rstrip('/')}/webapi/{api_path.lstrip('/')}"
            base_query = {
                "api": "SYNO.FileStation.Upload",
                "method": "upload",
                "version": str(api_version),
            }

            for index, variant in enumerate(payload_variants):
                for attempt in range(1, per_variant_retry_limit + 1):
                    try:
                        query = dict(base_query)
                        query.update(variant["query"])
                        form = dict(variant["form"])
                        include_sid = variant.get("include_sid", True)
                        if self._sid and include_sid:
                            query.setdefault("_sid", self._sid)
                            if "_sid" in form:
                                form["_sid"] = self._sid
                        logger.debug(
                            "[SynologyUpload] 尝试变体 %s/%s name=%s attempt=%s/%s path=%s local=%s size=%s api_path=%s api_version=%s query_keys=%s form_keys=%s",
                            index + 1,
                            len(payload_variants),
                            variant.get("name"),
                            attempt,
                            per_variant_retry_limit,
                            normalized_path,
                            local_path,
                            local_file_size,
                            api_path,
                            api_version,
                            sorted(query.keys()),
                            sorted(form.keys()),
                        )
                        async with get_resource_budget_service().acquire("remote_fs", reason="synology.upload"):
                            await self._post_file_upload(
                                session,
                                upload_url,
                                "SYNO.FileStation.Upload",
                                query,
                                form,
                                local_path,
                                remote_name=remote_name,
                                quote_fields=variant["quote_fields"],
                                include_content_type=variant["include_content_type"],
                                progress_callback=progress_callback,
                            )
                        self._record_remote_success()
                        self._preferred_upload_variant_name = str(variant.get("name") or "").strip() or None
                        return
                    except Exception as exc:
                        self._record_remote_failure("SYNO.FileStation.Upload", exc)
                        logger.debug(
                            "[SynologyUpload] 变体失败 %s/%s name=%s attempt=%s/%s path=%s error=%s",
                            index + 1,
                            len(payload_variants),
                            variant.get("name"),
                            attempt,
                            per_variant_retry_limit,
                            normalized_path,
                            exc,
                        )
                        last_error = exc
                        if isinstance(exc, FileNotFoundError):
                            raise
                        if self._is_error_code(exc, 414) or self._is_error_code(exc, 408):
                            error_code = 414 if self._is_error_code(exc, 414) else 408
                            if await self._remote_file_matches_local_size(remote_file_path, local_file_size):
                                logger.info(
                                    "[SynologyUpload] %s 后远端校验命中，直接判定成功 path=%s size=%s variant=%s",
                                    error_code,
                                    remote_file_path,
                                    local_file_size,
                                    variant.get("name"),
                                )
                                self._preferred_upload_variant_name = str(variant.get("name") or "").strip() or self._preferred_upload_variant_name
                                if progress_callback:
                                    progress_callback(local_file_size, local_file_size)
                                return
                            logger.warning(
                                "[SynologyUpload] %s 后远端校验未命中，停止当前文件上传 path=%s local_size=%s",
                                error_code,
                                remote_file_path,
                                local_file_size,
                            )
                            raise
                        if self._is_retryable_upload_error(exc):
                            if await self._remote_file_matches_local_size(remote_file_path, local_file_size):
                                logger.info(
                                    "[SynologyUpload] 网络中断后远端校验命中，直接判定成功 path=%s size=%s variant=%s",
                                    remote_file_path,
                                    local_file_size,
                                    variant.get("name"),
                                )
                                self._preferred_upload_variant_name = str(variant.get("name") or "").strip() or self._preferred_upload_variant_name
                                if progress_callback:
                                    progress_callback(local_file_size, local_file_size)
                                return
                            if attempt < per_variant_retry_limit:
                                retry_wait = min(8.0, 1.5 * attempt)
                                logger.debug(
                                    "[SynologyUpload] 检测到可恢复网络中断，准备重试同一变体 name=%s attempt=%s/%s wait=%.1fs",
                                    variant.get("name"),
                                    attempt,
                                    per_variant_retry_limit,
                                    retry_wait,
                                )
                                await asyncio.sleep(retry_wait)
                                continue
                        break

        if last_error:
            logger.warning(
                "[SynologyUpload] 上传失败摘要: path=%s local=%s size=%s error=%s",
                remote_file_path,
                local_path,
                local_file_size,
                last_error,
            )
            raise last_error


def build_synology_web_url(base_url: str, root_path: str) -> str:
    normalized_base = (base_url or "").rstrip("/")
    normalized_path = root_path or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    launch_param = quote(f"path={normalized_path}", safe="")
    return f"{normalized_base}//file/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam={launch_param}"


class LibraryManager:
    SUBTITLE_EXTENSIONS = {".lrc", ".vtt", ".srt", ".ass", ".ssa"}

    def __init__(self):
        self._stats_cache: dict[str, dict[str, Any]] = {}
        self._stats_tasks: dict[str, asyncio.Task] = {}
        # 路径 size 缓存：每查过 size 的目录都会落库 ⇒ 必须有上限 + TTL
        # 4h TTL 配合签名校验（mtime / hash），既保住命中率又不至于无限增长
        self._size_cache: TTLCache = TTLCache(max_size=4096, ttl_seconds=14400, name="library.size")
        self._remote_size_tasks: dict[str, asyncio.Task] = {}
        self._remote_search_tasks: dict[tuple[str, str, str, int, str, str], asyncio.Task] = {}
        self._remote_search_result_cache: dict[tuple[str, str, str, str, str, int, int], dict[str, Any]] = {}
        # 本地搜索结果缓存：缓存完整返回值，TTL 由 local_search_cache_ttl_seconds 控制
        self._local_search_result_cache: dict[tuple, dict[str, Any]] = {}
        self._local_dir_listing_cache: TTLCache = TTLCache(max_size=128, ttl_seconds=8, name="library.local_dir_listing")
        # 群晖 share 列表缓存：避免多 RJ 并发时重复 list_share；key=auth_sig，TTL 5 分钟
        self._share_list_cache: dict[str, dict[str, Any]] = {}
        self._filter_preview_cancel_flags: dict[str, bool] = {}
        # 删除过滤预审任务：完成后不会被显式清理 ⇒ 用 LRU 上限兜底（不设 TTL，避免进行中任务被清）
        self._filter_preview_jobs: TTLCache = TTLCache(max_size=32, ttl_seconds=0, name="library.filter_preview_jobs")
        self._filter_preview_tasks: dict[str, asyncio.Task] = {}
        # 本地库存索引 upsert 可能要 stat 上万文件并分批写 PostgreSQL。
        # 移动/重命名接口只负责文件系统变更，索引追赶放到单 worker 后台串行执行。
        self._local_index_upsert_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="library-index-upsert",
        )
        self._index_mutation_lock = threading.Lock()
        self._index_mutation_timer: Optional[threading.Timer] = None
        self._index_mutation_pending_deletes: dict[str, dict[str, Any]] = {}
        self._index_mutation_pending_upserts: dict[str, dict[str, Any]] = {}
        self._index_mutation_pending_replaces: dict[str, dict[str, Any]] = {}
        self._index_mutation_pending_moves: dict[tuple[str, str], dict[str, Any]] = {}
        self._index_read_repair_lock = threading.Lock()
        self._index_read_repair_last_seen: dict[str, float] = {}
        self._list_files_inflight_lock: Optional[asyncio.Lock] = None
        self._list_files_inflight: dict[tuple[Any, ...], asyncio.Future] = {}
        self._folder_contents_inflight_lock: Optional[asyncio.Lock] = None
        self._folder_contents_inflight: dict[tuple[Any, ...], asyncio.Future] = {}
        # 远程子树 upsert 的跨 flush 合并/去抖缓冲。
        # 背景：_flush_index_mutations 的 timer 只有 0.1s，零散写操作（解压入库 /
        # rename / 字幕落盘）会触发多轮 flush，每轮都给远程库起一次 serial dispatch
        # ⇒ 群晖端反复起 SYNO.Search task。即便已串行（见 service 全局锁），仍是 N 次
        # 独立重活 task。这里再加一层更长的去抖窗口，把短时间内多轮 flush 的远程路径
        # 攒成一次 serial dispatch，从源头减少远程 search task 数量。
        # 仅远程库走这层；本地库 os.scandir 廉价，仍即时执行不去抖。
        self._remote_upsert_debounce_lock = threading.Lock()
        self._remote_upsert_debounce: dict[str, dict[str, Any]] = {}
        self._remote_upsert_debounce_timers: dict[str, threading.Timer] = {}
        # 全局 Synology client 缓存：避免每次操作重复登录（key = base_url::username::auth_sig）
        self._synology_client_cache: dict[str, SynologyFileStationClient] = {}
        self._load_persisted_stats()

    def get_cached_synology_client(self, config: SynologyConfig) -> SynologyFileStationClient:
        """返回长期缓存的 SynologyFileStationClient（同一账号复用同一 session+sid）。"""
        base_key = f"{(config.base_url or '').rstrip('/')}::{config.username or ''}"
        auth_sig = SynologyFileStationClient.build_cache_auth_signature(config)
        full_key = f"{base_key}::{auth_sig}"
        if full_key not in self._synology_client_cache:
            # 清理同一账号但认证参数已变化的旧缓存条目
            stale_keys = [k for k in self._synology_client_cache if k.startswith(f"{base_key}::")]
            for stale_key in stale_keys:
                stale_client = self._synology_client_cache.pop(stale_key, None)
                if stale_client:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and not loop.is_closed():
                        loop.create_task(stale_client.close())
            self._synology_client_cache[full_key] = SynologyFileStationClient(config)
        return self._synology_client_cache[full_key]

    async def close_cached_synology_clients(self) -> None:
        """应用关闭时统一关闭缓存客户端，避免 aiohttp session 泄漏告警。"""
        if not self._synology_client_cache:
            return
        clients = list(self._synology_client_cache.values())
        self._synology_client_cache.clear()
        for client in clients:
            try:
                await client.close()
            except Exception:
                logger.warning("关闭 Synology 客户端失败", exc_info=True)

    def shutdown_background_workers(self) -> None:
        """应用关闭时停止 LibraryManager 持有的后台 worker。"""
        timer = getattr(self, "_index_mutation_timer", None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                logger.debug("取消库存索引变更 flush timer 失败", exc_info=True)
            self._index_mutation_timer = None
        # 取消所有远程子树 upsert 去抖 timer（缓冲里未刷新的路径会丢失，但数据已落盘，
        # 下次手动重建会补齐索引，关闭时不强行起远程 search task）。
        debounce_lock = getattr(self, "_remote_upsert_debounce_lock", None)
        if debounce_lock is not None:
            with debounce_lock:
                for debounce_timer in self._remote_upsert_debounce_timers.values():
                    try:
                        debounce_timer.cancel()
                    except Exception:
                        logger.debug("取消远程子树 upsert 去抖 timer 失败", exc_info=True)
                self._remote_upsert_debounce_timers.clear()
                self._remote_upsert_debounce.clear()
        executor = getattr(self, "_local_index_upsert_executor", None)
        if executor is None:
            return
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.warning("关闭本地库存索引后台 worker 失败", exc_info=True)

    def remote_health_snapshot(self) -> dict[str, Any]:
        """返回远程库存当前健康状态，不触发登录或远程探测。"""
        libraries = self._active_libraries()
        items: list[dict[str, Any]] = []
        for library in libraries:
            if library.type != "synology_filestation":
                continue
            client = self.get_cached_synology_client(library.synology) if library.synology else None
            health = client.remote_health_snapshot() if client else {
                "status": "unconfigured",
                "failure_count": 0,
                "circuit_remaining_seconds": 0,
                "session_open": False,
                "has_sid": False,
            }
            items.append({
                "library_id": library.id,
                "library_name": library.name,
                "type": library.type,
                **health,
            })
        degraded_count = sum(1 for item in items if item.get("status") == "degraded")
        return {
            "total": len(items),
            "degraded_count": degraded_count,
            "items": items,
            "generated_at": datetime.now().isoformat(),
        }

    def load_config(self) -> dict[str, Any]:
        return load_library_config()

    def _remote_search_cache_ttl_seconds(self) -> int:
        raw_value = self.load_config().get("remote_search_cache_ttl_seconds", 60)
        try:
            ttl = int(raw_value)
        except Exception:
            ttl = 60
        return max(30, min(ttl, 120))

    def _remote_empty_search_cache_ttl_seconds(self) -> int:
        # 空结果 TTL 至少 15s，确保 >= PENDING_REFRESH_MIN_INTERVAL_SECONDS(12)，
        # 避免每次 pending 刷新都因缓存已过期而再次触发真实远程搜索
        return max(15, min(60, self._remote_search_cache_ttl_seconds() // 4))

    def _remote_search_timeout_seconds(self) -> float:
        raw = self.load_config().get("remote_search_timeout_seconds", 30)
        try:
            val = float(raw)
        except Exception:
            val = 30.0
        return max(10.0, min(val, 120.0))

    def _build_remote_search_cache_key(
        self,
        *,
        library_id: str,
        current_path: Optional[str],
        keyword: str,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
        search_exact: bool = False,
        search_result_kind: str = "all",
    ) -> tuple[str, str, str, str, str, int, int, bool, str]:
        return (
            library_id,
            self._normalize_remote_path(current_path or "/"),
            str(keyword or "").strip(),
            sort_by,
            sort_order,
            int(page),
            int(page_size),
            bool(search_exact),
            self._normalize_search_result_kind(search_result_kind),
        )

    def _get_cached_remote_search_result(
        self,
        cache_key: tuple[str, str, str, str, str, int, int, bool, str],
        *,
        force_refresh: bool = False,
    ) -> Optional[dict[str, Any]]:
        if force_refresh:
            logger.debug(
                "远程搜索绕过缓存: library=%s current_path=%s keyword=%s reason=force_refresh",
                cache_key[0],
                cache_key[1],
                cache_key[2],
            )
            return None
        cached = self._remote_search_result_cache.get(cache_key)
        if not cached:
            return None
        expires_at = float(cached.get("expires_at", 0) or 0)
        if expires_at <= time.time():
            self._remote_search_result_cache.pop(cache_key, None)
            return None
        logger.debug(
            "远程搜索命中缓存: library=%s current_path=%s keyword=%s cache=%s total=%s ttl_remaining=%.1fs",
            cache_key[0],
            cache_key[1],
            cache_key[2],
            cached.get("cache_kind") or "result",
            int(cached.get("total", 0) or 0),
            max(0.0, expires_at - time.time()),
        )
        return copy.deepcopy(cached.get("data") or {})

    def _set_cached_remote_search_result(
        self,
        cache_key: tuple[str, str, str, str, str, int, int, bool, str],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        total = int(data.get("total", 0) or 0)
        cache_kind = "empty" if total <= 0 else "result"
        ttl_seconds = self._remote_empty_search_cache_ttl_seconds() if cache_kind == "empty" else self._remote_search_cache_ttl_seconds()
        logger.debug(
            "远程搜索写入缓存: library=%s current_path=%s keyword=%s cache=%s total=%s ttl=%.1fs",
            cache_key[0],
            cache_key[1],
            cache_key[2],
            cache_kind,
            total,
            float(ttl_seconds),
        )
        self._remote_search_result_cache[cache_key] = {
            "expires_at": time.time() + ttl_seconds,
            "cache_kind": cache_kind,
            "total": total,
            "data": copy.deepcopy(data),
        }
        return copy.deepcopy(data)

    # ---------------------- 本地搜索 TTL 缓存 ----------------------
    def _local_search_cache_ttl_seconds(self) -> int:
        raw = self.load_config().get("local_search_cache_ttl_seconds", 10)
        try:
            ttl = int(raw)
        except Exception:
            ttl = 10
        return max(0, min(ttl, 120))

    def _build_local_search_cache_key(
        self,
        *,
        library_id: str,
        search_root: str,
        keyword: str,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
        search_exact: bool,
        search_result_kind: str,
    ) -> tuple:
        return (
            library_id,
            os.path.normcase(os.path.abspath(search_root)),
            str(keyword or "").strip().lower(),
            sort_by,
            sort_order,
            int(page),
            int(page_size),
            bool(search_exact),
            self._normalize_search_result_kind(search_result_kind),
        )

    def _get_cached_local_search_result(self, cache_key: tuple) -> Optional[dict[str, Any]]:
        cached = self._local_search_result_cache.get(cache_key)
        if not cached:
            return None
        expires_at = float(cached.get("expires_at", 0) or 0)
        if expires_at <= time.time():
            self._local_search_result_cache.pop(cache_key, None)
            return None
        return copy.deepcopy(cached.get("data") or {})

    def _set_cached_local_search_result(self, cache_key: tuple, data: dict[str, Any]) -> dict[str, Any]:
        ttl = self._local_search_cache_ttl_seconds()
        if ttl <= 0:
            return data
        # 命中数过大时仍然缓存，但不复制超大对象 — 用 deepcopy 隔离调用方修改
        self._local_search_result_cache[cache_key] = {
            "expires_at": time.time() + ttl,
            "data": copy.deepcopy(data),
        }
        # 简单上限：超 256 条不同 key 时清掉过期项
        if len(self._local_search_result_cache) > 256:
            now_ts = time.time()
            stale_keys = [k for k, v in self._local_search_result_cache.items() if float(v.get("expires_at", 0) or 0) <= now_ts]
            for stale in stale_keys:
                self._local_search_result_cache.pop(stale, None)
        return data

    def _invalidate_local_search_cache(self, library_id: Optional[str] = None) -> None:
        """文件结构变更（rename/move/delete/导入完成）后调用，让缓存失效。"""
        cache = getattr(self, "_local_search_result_cache", None)
        if not cache:
            return
        if not library_id:
            cache.clear()
            return
        keys_to_drop = [k for k in cache if k and k[0] == library_id]
        for k in keys_to_drop:
            cache.pop(k, None)

    def _invalidate_local_dir_listing_cache(self, library_id: Optional[str] = None) -> None:
        """本地目录列表变更后调用，避免浏览接口读到 8 秒 TTL 内的旧行。"""
        cache = getattr(self, "_local_dir_listing_cache", None)
        if not cache:
            return
        if not library_id:
            cache.clear()
            return
        for key in list(cache.keys()):
            if key and key[0] == library_id:
                cache.pop(key, None)

    def _invalidate_local_browse_caches(self, library_id: Optional[str] = None) -> None:
        self._invalidate_local_search_cache(library_id)
        self._invalidate_local_dir_listing_cache(library_id)

    # ---------------------- 群晖 share 列表 TTL 缓存 ----------------------
    def _share_list_cache_ttl_seconds(self) -> int:
        raw = self.load_config().get("share_list_cache_ttl_seconds", 300)
        try:
            ttl = int(raw)
        except Exception:
            ttl = 300
        return max(30, min(ttl, 3600))

    def _share_list_cache_key(self, client: "SynologyFileStationClient") -> str:
        cfg = client.config
        base = (cfg.base_url or "").rstrip("/")
        username = cfg.username or ""
        return f"{base}::{username}"

    def _get_cached_share_list(self, client: "SynologyFileStationClient") -> Optional[list[str]]:
        key = self._share_list_cache_key(client)
        cached = self._share_list_cache.get(key)
        if not cached:
            return None
        expires_at = float(cached.get("expires_at", 0) or 0)
        if expires_at <= time.time():
            self._share_list_cache.pop(key, None)
            return None
        return list(cached.get("shares") or [])

    def _set_cached_share_list(self, client: "SynologyFileStationClient", shares: list[str]) -> list[str]:
        key = self._share_list_cache_key(client)
        ttl = self._share_list_cache_ttl_seconds()
        self._share_list_cache[key] = {
            "expires_at": time.time() + ttl,
            "shares": list(shares),
        }
        return shares

    def _active_libraries(self, cfg: Optional[dict[str, Any]] = None) -> list[LibraryDefinition]:
        cfg = cfg or self.load_config()
        active = [library for library in cfg["libraries"] if library.enabled]
        return active or cfg["libraries"]

    def _load_persisted_stats(self):
        path = _stats_cache_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
            remote_stats = data.get("remote_stats") or {}
            if isinstance(remote_stats, dict):
                self._stats_cache.update(remote_stats)
            library_stats = data.get("library_stats") or {}
            if isinstance(library_stats, dict):
                self._stats_cache.update(library_stats)
        except Exception:
            return

    def _persist_stats(self):
        payload = {
            "library_stats": dict(self._stats_cache),
            "remote_stats": {
                key: value
                for key, value in self._stats_cache.items()
                if value.get("library_type") == "synology_filestation"
            }
        }
        path = _stats_cache_file_path()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception:
            return

    @staticmethod
    def _remote_stats_uses_inventory_index(cached: dict[str, Any]) -> bool:
        scan_mode = str(cached.get("scan_mode") or "")
        status = str(cached.get("status") or "")
        return bool(
            scan_mode in {"library_index", "index_required"}
            or cached.get("index_status")
            or status == "syncing"
        )

    @staticmethod
    def _remote_filestation_stats_placeholder(library: LibraryDefinition) -> dict[str, Any]:
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "unsupported",
            "folder_count": 0,
            "total_size_bytes": 0,
            "total_size_gb": 0,
            "last_completed_at": None,
            "updated_at": time.time(),
            "scan_mode": "filestation",
            "warning": "远程库使用群晖 FileStation 原生接口，不创建库存索引",
        }

    def _append_stats_log(self, library: LibraryDefinition, level: str, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] [{library.id}] [{library.name}] {message}\n"
        path = _stats_log_file_path()
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            return

    def read_stats_logs(self, library_id: Optional[str] = None, lines: int = 200) -> dict[str, Any]:
        path = _stats_log_file_path()
        if not os.path.exists(path):
            return {
                "path": path,
                "lines": [],
                "total": 0,
            }
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.readlines()
        except Exception as exc:
            raise RuntimeError(f"读取库存日志失败: {exc}") from exc

        filtered = content
        if library_id:
            filtered = [line for line in content if f"[{library_id}]" in line]

        limit = max(1, min(int(lines or 200), 2000))
        tail = filtered[-limit:]
        return {
            "path": path,
            "lines": [line.rstrip("\n") for line in tail],
            "total": len(filtered),
        }

    def list_libraries(self) -> list[dict[str, Any]]:
        cfg = self.load_config()
        warning_free_gb = float(cfg["health_warning_free_gb"])
        result = []
        for library in self._active_libraries(cfg):
            health = self._health_for_library(library, warning_free_gb)
            result.append(
                {
                    "id": library.id,
                    "name": library.name,
                    "type": library.type,
                    "path": library.browse_root_path,
                    "root_path": library.root_path,
                    "browse_path": library.browse_path or "",
                    "synology_profile_id": library.synology_profile_id or "",
                    "browse_root_path": library.browse_root_path,
                    "web_url": build_synology_web_url(library.synology.base_url, library.root_path) if library.type == "synology_filestation" and library.synology else None,
                    "description": library.description,
                    "writable": library.writable,
                    "health": health,
                }
            )
        return result

    def get_library_definition(self, library_id: Optional[str] = None) -> LibraryDefinition:
        cfg = self.load_config()
        selected = library_id or cfg["default_library_id"]
        for library in self._active_libraries(cfg):
            if library.id == selected:
                return library
        return self._active_libraries(cfg)[0]

    def _library_from_payload(self, payload: dict[str, Any]) -> LibraryDefinition:
        library_id = str(payload.get("id") or "").strip()
        library_type = (payload.get("type") or "local").lower()
        synology_payload = copy.deepcopy(payload.get("synology") or {})
        synology_profile_id = str(payload.get("synology_profile_id") or "").strip()
        if library_id and library_type == "synology_filestation" and not synology_payload:
            try:
                existing = self.get_library_definition(library_id)
                if existing and existing.type == "synology_filestation" and existing.synology:
                    return existing
            except Exception:
                pass
        if library_type == "synology_filestation" and synology_profile_id:
            storage = get_config().storage.model_dump()
            profile_map = {
                str(item.get("id") or "").strip(): copy.deepcopy(item)
                for item in storage.get("synology_profiles") or []
                if str(item.get("id") or "").strip()
            }
            profile_payload = profile_map.get(synology_profile_id) or {}
            profile_payload.pop("id", None)
            profile_payload.pop("name", None)
            synology_payload = {
                **synology_payload,
                **profile_payload,
            }
        if library_type == "synology_filestation":
            root_path = synology_payload.get("root_path") or payload.get("path") or "/"
            synology_payload = {
                **synology_payload,
                "root_path": root_path,
            }
        synology = SynologyConfig(**synology_payload) if library_type == "synology_filestation" else None
        return LibraryDefinition(
            id=payload.get("id") or "temp-library",
            name=payload.get("name") or payload.get("id") or "临时库存",
            type=library_type,
            path=(payload.get("path") or (synology.root_path if synology else "")),
            browse_path=payload.get("browse_path") or "",
            enabled=payload.get("enabled", True),
            writable=payload.get("writable", True),
            description=payload.get("description") or "",
            tags=payload.get("tags") or [],
            synology_profile_id=synology_profile_id,
            synology=synology,
        )

    def default_extract_library_id(self) -> str:
        cfg = self.load_config()
        extract_id = cfg["default_extract_library_id"]
        for library in self._active_libraries(cfg):
            if library.id == extract_id:
                return extract_id
        return self._active_libraries(cfg)[0].id

    def _health_for_library(self, library: LibraryDefinition, warning_free_gb: float) -> dict[str, Any]:
        if library.type == "local":
            if not library.root_path:
                return {"status": "error", "warnings": [], "errors": ["Path is not configured"]}
            exists = os.path.exists(library.root_path)
            readable = exists and os.access(library.root_path, os.R_OK)
            writable = readable and os.access(library.root_path, os.W_OK)
            warnings: list[str] = []
            errors: list[str] = []
            free_gb = None
            total_gb = None
            if not readable:
                errors.append("Path does not exist or is not readable")
            else:
                try:
                    usage = shutil.disk_usage(library.root_path)
                    free_gb = _gb(usage.free)
                    total_gb = _gb(usage.total)
                    if warning_free_gb and usage.free < warning_free_gb * (1024 ** 3):
                        warnings.append(f"剩余空间低于 {warning_free_gb:.0f} GB")
                except Exception as exc:
                    warnings.append(f"无法读取磁盘空间: {exc}")
            status = "healthy"
            if errors:
                status = "error"
            elif warnings:
                status = "warning"
            return {
                "status": status,
                "warnings": warnings,
                "errors": errors,
                "is_accessible": readable,
                "is_writable": writable,
                "free_space_gb": free_gb,
                "total_space_gb": total_gb,
            }

        warnings = []
        errors = []
        accessible = bool(library.synology and library.synology.base_url and library.synology.username)
        if not accessible:
            errors.append("远程库配置不完整")
        status = "healthy"
        if errors:
            status = "error"
        elif warnings:
            status = "warning"
        return {
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "is_accessible": accessible,
            "is_writable": accessible and library.writable,
            "free_space_gb": None,
            "total_space_gb": None,
        }

    async def list_files(
        self,
        library_id: Optional[str],
        page: int = 1,
        page_size: int = 200,
        search: str = "",
        current_path: Optional[str] = None,
        sort_by: str = "size",
        sort_order: str = "desc",
        force_refresh: bool = False,
        search_exact: bool = False,
        search_result_kind: str = "all",
        remote_warmup_retries: int = 3,
        page_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        inflight_key = self._list_files_inflight_key(
            library,
            page=page,
            page_size=page_size,
            search=search,
            current_path=current_path,
            sort_by=sort_by,
            sort_order=sort_order,
            force_refresh=force_refresh,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
            remote_warmup_retries=remote_warmup_retries,
            page_cursor=page_cursor,
        )
        if inflight_key is not None:
            return await self._run_list_files_inflight(inflight_key, lambda: self._list_files_uncached(
                library,
                page=page,
                page_size=page_size,
                search=search,
                current_path=current_path,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
                remote_warmup_retries=remote_warmup_retries,
                page_cursor=page_cursor,
            ))
        return await self._list_files_uncached(
            library,
            page=page,
            page_size=page_size,
            search=search,
            current_path=current_path,
            sort_by=sort_by,
            sort_order=sort_order,
            force_refresh=force_refresh,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
            remote_warmup_retries=remote_warmup_retries,
            page_cursor=page_cursor,
        )

    async def _list_files_uncached(
        self,
        library: LibraryDefinition,
        *,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        force_refresh: bool,
        search_exact: bool,
        search_result_kind: str,
        remote_warmup_retries: int,
        page_cursor: Optional[str],
    ) -> dict[str, Any]:
        if str(search or "").strip():
            if library.type == "local":
                return await asyncio.to_thread(
                    self._search_local_files,
                    library,
                    page,
                    page_size,
                    search,
                    current_path,
                    sort_by,
                    sort_order,
                    search_exact,
                    search_result_kind,
                )
            return await self._search_remote_files(
                library,
                page,
                page_size,
                search,
                current_path,
                sort_by,
                sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
                remote_warmup_retries=remote_warmup_retries,
            )
        if library.type == "local":
            indexed_result = self._list_files_via_index(
                library,
                page=page,
                page_size=page_size,
                current_path=current_path or (library.browse_root_path or library.root_path),
                browse_root=library.browse_root_path or library.root_path,
                parent_path=self._index_parent_path_for_target(
                    library,
                    current_path or (library.browse_root_path or library.root_path),
                ) or "",
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                page_cursor=page_cursor,
            )
            if indexed_result is not None:
                return indexed_result
            return await asyncio.to_thread(
                self._list_local_files,
                library,
                page,
                page_size,
                search,
                current_path,
                sort_by,
                sort_order,
                force_refresh,
                page_cursor,
            )
        return await self._list_remote_files(library, page, page_size, search, current_path, sort_by, sort_order, page_cursor)

    def _list_files_inflight_key(
        self,
        library: LibraryDefinition,
        *,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        force_refresh: bool,
        search_exact: bool,
        search_result_kind: str,
        remote_warmup_retries: int,
        page_cursor: Optional[str],
    ) -> Optional[tuple[Any, ...]]:
        normalized_path = str(current_path or "").strip()
        if library.type == "local":
            try:
                browse_root = os.path.abspath(library.browse_root_path or library.root_path)
                normalized_path = os.path.normcase(os.path.abspath(normalized_path or browse_root))
            except Exception:
                normalized_path = normalized_path.replace("\\", "/")
        else:
            normalized_path = self._normalize_remote_path(normalized_path or library.browse_root_path or library.root_path or "/")
        return (
            library.id,
            library.type,
            int(page or 1),
            int(page_size or 200),
            str(search or "").strip(),
            normalized_path,
            self._normalize_library_sort_by(sort_by),
            self._normalize_library_sort_order(sort_order),
            bool(force_refresh),
            bool(search_exact),
            self._normalize_search_result_kind(search_result_kind),
            int(remote_warmup_retries or 0),
            str(page_cursor or ""),
        )

    async def _run_list_files_inflight(self, key: tuple[Any, ...], factory: Callable[[], Any]) -> dict[str, Any]:
        if not hasattr(self, "_list_files_inflight"):
            self._list_files_inflight = {}
        lock = getattr(self, "_list_files_inflight_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._list_files_inflight_lock = lock
        async with lock:
            future = self._list_files_inflight.get(key)
            owner = False
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._list_files_inflight[key] = future
                owner = True
        if not owner:
            return copy.deepcopy(await future)
        try:
            result = await factory()
            future.set_result(copy.deepcopy(result))
            return result
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with lock:
                self._list_files_inflight.pop(key, None)

    def _index_has_usable_snapshot(self, service: Any, library_id: str) -> bool:
        checker = getattr(service, "has_usable_snapshot", None)
        if callable(checker):
            return bool(checker(library_id))
        return bool(service.is_ready(library_id))

    def _index_status_name(self, service: Any, library_id: str) -> str:
        try:
            status = service.get_status(library_id)
            return str(getattr(status, "status", "") or "not_ready")
        except Exception:
            logger.debug("读取库存索引状态失败: lib=%s", library_id, exc_info=True)
            return "unknown"

    async def find_rj_in_libraries(
        self,
        rjcode: str,
        *,
        library_ids: Optional[list[str]] = None,
        per_library_timeout: float = 8.0,
        include_remote: bool = True,
    ) -> list[dict[str, Any]]:
        """跨所有活跃库存按 RJ 号定位作品文件夹。

        仅返回 entry.rjcode == rjcode 且 is_directory=True 的命中。
        若没有任何配置完整的远程库存，则只走本地库存搜索；
        远程库凭据缺失时也会跳过该库以免触发无效请求。

        批次 5 索引加速：每个库独立判断 LibraryIndexService.is_ready，
        ready 的库直接走 PostgreSQL 查询（毫秒级），其余仍走原 SYNO.Search /
        os.walk 路径并合并去重。索引层任意异常都自动 fallback，保证零回归。
        """

        normalized_rj = (rjcode or "").strip().upper()
        if not normalized_rj:
            return []
        libraries = self._active_libraries()
        if library_ids:
            wanted = {str(lid).strip() for lid in library_ids if lid}
            libraries = [lib for lib in libraries if lib.id in wanted]
        if not libraries:
            return []

        def _is_remote_library_searchable(library: LibraryDefinition) -> bool:
            if library.type != "synology_filestation":
                return True
            syn = library.synology
            if not syn:
                return False
            base_url = str(getattr(syn, "base_url", "") or "").strip()
            account = str(getattr(syn, "username", "") or getattr(syn, "account", "") or "").strip()
            password = str(getattr(syn, "password", "") or getattr(syn, "passwd", "") or "").strip()
            return bool(base_url and account and password)

        filtered_libraries: list[LibraryDefinition] = []
        skipped_remote = 0
        for library in libraries:
            if library.type == "synology_filestation":
                if not include_remote:
                    skipped_remote += 1
                    continue
                if not _is_remote_library_searchable(library):
                    logger.info(
                        "find_rj_in_libraries 跳过未完整配置的远程库: rj=%s lib=%s",
                        normalized_rj,
                        library.id,
                    )
                    skipped_remote += 1
                    continue
            filtered_libraries.append(library)
        if skipped_remote:
            logger.debug(
                "find_rj_in_libraries 跳过 %s 个远程库 (无远程仓库或凭据缺失) rj=%s",
                skipped_remote,
                normalized_rj,
            )
        if not filtered_libraries:
            return []

        # === 批次 5：索引优先 ===
        indexed_matches, libraries_for_fallback = self._find_rj_via_index(
            normalized_rj, filtered_libraries,
        )
        if indexed_matches:
            logger.info(
                "find_rj_in_libraries 索引命中: rj=%s indexed=%s fallback_libs=%s",
                normalized_rj,
                len(indexed_matches),
                len(libraries_for_fallback),
            )
        if not libraries_for_fallback:
            return indexed_matches

        # === fallback：原 SYNO.Search / os.walk 路径，处理仍未 ready 的库 ===
        async def _search_one(library: LibraryDefinition) -> tuple[LibraryDefinition, list[dict[str, Any]]]:
            try:
                data = await asyncio.wait_for(
                    self.list_files(
                        library.id,
                        page=1,
                        page_size=200,
                        search=normalized_rj,
                        current_path=None,
                        sort_by="name",
                        sort_order="asc",
                        search_exact=False,
                        search_result_kind="folder_only",
                    ),
                    timeout=per_library_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("跨库查 RJ 超时: rj=%s lib=%s", normalized_rj, library.id)
                return library, []
            except Exception as exc:
                logger.warning("跨库查 RJ 失败: rj=%s lib=%s err=%s", normalized_rj, library.id, sanitize_text_for_log(exc))
                return library, []
            return library, list(data.get("files") or [])

        results = await asyncio.gather(
            *[_search_one(lib) for lib in libraries_for_fallback],
            return_exceptions=False,
        )
        matches: list[dict[str, Any]] = list(indexed_matches)
        seen_paths: set[str] = {f"{m['library_id']}::{m['path']}" for m in matches}
        for library, files in results:
            for entry in files:
                entry_rj = str(entry.get("rjcode") or "").upper()
                if entry_rj != normalized_rj:
                    continue
                if not entry.get("is_directory", False):
                    continue
                full_path = str(entry.get("path") or "")
                if not full_path:
                    continue
                dedupe_key = f"{library.id}::{full_path}"
                if dedupe_key in seen_paths:
                    continue
                seen_paths.add(dedupe_key)
                matches.append({
                    "library_id": library.id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "library_root_path": library.root_path,
                    "library_writable": bool(library.writable),
                    "path": full_path,
                    "name": str(entry.get("name") or ""),
                    "size": entry.get("size"),
                    "modified_time": entry.get("modified_time"),
                })
        return matches

    def _find_rj_via_index(
        self,
        normalized_rj: str,
        libraries: list[LibraryDefinition],
    ) -> tuple[list[dict[str, Any]], list[LibraryDefinition]]:
        """对索引 ready 的库直接走 SQL 查询。

        返回二元组：(已命中的 match 列表, 仍需要 fallback 扫描的库列表)。
        任意异常都把对应库丢回 fallback，保证零回归。
        """
        try:
            from .library_index import get_library_index_service
            service = get_library_index_service()
        except Exception:
            logger.debug("library_index 不可用，全部库走 fallback", exc_info=True)
            return [], list(libraries)

        indexed: list[dict[str, Any]] = []
        fallback: list[LibraryDefinition] = []
        seen: set[str] = set()

        for library in libraries:
            if not self._library_uses_inventory_index(library):
                fallback.append(library)
                continue
            try:
                has_snapshot = (
                    service.has_usable_snapshot(library.id)
                    if hasattr(service, "has_usable_snapshot")
                    else service.is_ready(library.id)
                )
                if not has_snapshot:
                    fallback.append(library)
                    continue
                entries = service.find_by_rjcode(
                    normalized_rj,
                    library.id,
                    entry_type='dir',
                    limit=50,
                )
            except Exception:
                logger.warning(
                    "索引查询异常，转 fallback: rj=%s lib=%s",
                    normalized_rj, library.id, exc_info=True,
                )
                fallback.append(library)
                continue

            for entry in entries:
                key = f"{library.id}::{entry.absolute_path}"
                if key in seen:
                    continue
                seen.add(key)
                indexed.append({
                    "library_id": library.id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "library_root_path": library.root_path,
                    "library_writable": bool(library.writable),
                    "path": entry.absolute_path,
                    "name": entry.name,
                    "size": entry.size or None,
                    "modified_time": None,
                })

        return indexed, fallback

    @staticmethod
    def _library_uses_inventory_index(library: LibraryDefinition) -> bool:
        """库存索引只用于本地库；群晖远程库始终走 FileStation 原接口。"""
        return getattr(library, "type", None) == "local"

    def find_rj_in_ready_index(
        self,
        rjcodes: list[str] | tuple[str, ...] | set[str] | str,
        *,
        library_ids: Optional[list[str]] = None,
        include_subtitle_state: bool = True,
        per_rj_limit: int = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        """只从可用库存索引批量查 RJ 目录，绝不触发扫盘/远程 fallback。

        社团补全把库存索引当作“作品是否存在”的权威源；索引不可用时这里直接
        返回空命中，让调用方保持外部刷新流程但不额外打群晖/FileStation。
        """
        if isinstance(rjcodes, str):
            raw_codes = [rjcodes]
        else:
            raw_codes = list(rjcodes or [])
        normalized_codes: list[str] = []
        seen_codes: set[str] = set()
        for raw in raw_codes:
            code = str(raw or "").strip().upper()
            if not code:
                continue
            if code.isdigit():
                code = f"RJ{code}"
            if not re.fullmatch(r"RJ\d{4,}", code):
                matched = re.search(r"RJ\d{4,}", code, re.IGNORECASE)
                code = matched.group(0).upper() if matched else ""
            if code and code not in seen_codes:
                seen_codes.add(code)
                normalized_codes.append(code)
        if not normalized_codes:
            return {}

        libraries = self._active_libraries()
        if library_ids:
            wanted = {str(lid).strip() for lid in library_ids if str(lid).strip()}
            libraries = [lib for lib in libraries if lib.id in wanted]
        libraries = [lib for lib in libraries if self._library_uses_inventory_index(lib)]
        if not libraries:
            return {}

        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
        except Exception:
            logger.debug("[索引] 批量 RJ 查询不可用，跳过本地拥有态", exc_info=True)
            return {}

        usable_libraries: list[LibraryDefinition] = []
        for library in libraries:
            try:
                has_snapshot = self._index_has_usable_snapshot(service, library.id)
            except Exception:
                logger.debug("[索引] 判断库存快照可用性失败 library=%s", library.id, exc_info=True)
                has_snapshot = False
            if has_snapshot:
                usable_libraries.append(library)
        if not usable_libraries:
            return {code: [] for code in normalized_codes}

        library_by_id = {library.id: library for library in usable_libraries}
        result: dict[str, list[dict[str, Any]]] = {code: [] for code in normalized_codes}
        seen_paths: set[tuple[str, str, str]] = set()

        def _subtitle_state_for_entry(entry) -> dict[str, Any]:
            state = {
                "local_subtitle_present": False,
                "subtitle_file_count": 0,
                "subtitle_dir": "",
            }
            if not include_subtitle_state:
                return state
            try:
                subtree_entries = service.list_subtree_entries(
                    entry.library_id,
                    entry.relative_path,
                    include_self=False,
                    entry_type=None,
                    limit=10000,
                )
            except Exception:
                logger.debug(
                    "[索引] 查询字幕子树失败 library=%s path=%s",
                    entry.library_id,
                    entry.relative_path,
                    exc_info=True,
                )
                return state

            subtitle_count = 0
            subtitle_dir = ""
            has_subtitle_dir = False
            entry_relative = str(entry.relative_path or "").strip("/")
            for child in subtree_entries:
                rel = str(child.relative_path or "").replace("\\", "/").strip("/")
                under = self._index_relative_path_under_target(rel, entry_relative)
                parts = [part for part in under.split("/") if part]
                if not parts:
                    continue
                child_type = str(getattr(child, "entry_type", "") or "").lower()
                if child_type == "dir" and parts[-1].lower() == "subtitles":
                    has_subtitle_dir = True
                    if not subtitle_dir:
                        subtitle_dir = str(getattr(child, "absolute_path", "") or "")
                    continue
                if child_type and child_type != "file":
                    continue
                ext = os.path.splitext(str(child.name or rel))[1].lower()
                in_subtitles_dir = any(part.lower() == "subtitles" for part in parts[:-1])
                if in_subtitles_dir or ext in self.SUBTITLE_EXTENSIONS:
                    subtitle_count += 1
                    if not subtitle_dir and in_subtitles_dir:
                        prefix_parts: list[str] = []
                        for part in parts[:-1]:
                            prefix_parts.append(part)
                            if part.lower() == "subtitles":
                                break
                        subtitle_rel = "/".join([p for p in [entry_relative, *prefix_parts] if p])
                        subtitle_entry = service.get_entry(entry.library_id, subtitle_rel)
                        subtitle_dir = (
                            str(getattr(subtitle_entry, "absolute_path", "") or "")
                            if subtitle_entry
                            else ""
                        )
            state["local_subtitle_present"] = has_subtitle_dir or subtitle_count > 0
            state["subtitle_file_count"] = subtitle_count
            state["subtitle_dir"] = subtitle_dir
            return state

        for code in normalized_codes:
            for library in usable_libraries:
                try:
                    entries = service.find_by_rjcode(
                        code,
                        library.id,
                        entry_type="dir",
                        limit=per_rj_limit,
                    )
                except Exception:
                    logger.debug("[索引] 批量 RJ 查询失败 rj=%s library=%s", code, library.id, exc_info=True)
                    continue
                for entry in entries:
                    key = (code, str(entry.library_id or ""), str(entry.relative_path or ""))
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    library_info = library_by_id.get(entry.library_id)
                    subtitle_state = _subtitle_state_for_entry(entry)
                    result.setdefault(code, []).append({
                        "rjcode": code,
                        "matched_rjcode": str(entry.rjcode or code).upper(),
                        "library_id": entry.library_id,
                        "library_name": library_info.name if library_info else entry.library_id,
                        "library_type": library_info.type if library_info else "",
                        "library_root_path": library_info.root_path if library_info else "",
                        "path": entry.absolute_path,
                        "relative_path": entry.relative_path,
                        "name": entry.name,
                        "size": int(entry.size or 0),
                        "file_count": int(entry.file_count or 0),
                        "modified_time": entry.mtime,
                        **subtitle_state,
                    })
        return result

    def inventory_index_view_token(
        self,
        *,
        library_ids: Optional[list[str]] = None,
    ) -> str:
        """返回候选查询依赖的 active index view 版本，不触发扫盘。"""
        libraries = self._active_libraries()
        if library_ids:
            wanted = {str(lid).strip() for lid in library_ids if str(lid).strip()}
            libraries = [library for library in libraries if library.id in wanted]
        libraries = [
            library
            for library in libraries
            if self._library_uses_inventory_index(library)
        ]
        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
        except Exception:
            return "index-unavailable"

        tokens: list[str] = []
        for library in sorted(libraries, key=lambda item: str(item.id)):
            try:
                status = service.get_status(library.id)
            except Exception:
                status = None
            if status is None:
                tokens.append(f"{library.id}:missing")
                continue
            tokens.append(
                ":".join([
                    str(library.id),
                    str(getattr(status, "status", "") or ""),
                    str(int(getattr(status, "active_generation", 1) or 1)),
                    str(int(getattr(status, "materialized_seq", 0) or 0)),
                    str(int(getattr(status, "view_revision", 0) or 0)),
                ])
            )
        return "|".join(tokens) if tokens else "no-local-library"

    def has_ready_index(self, *, library_ids: Optional[list[str]] = None) -> bool:
        """是否至少有一个活动库存的索引处于 ready；不触发扫描。"""
        libraries = self._active_libraries()
        if library_ids:
            wanted = {str(lid).strip() for lid in library_ids if str(lid).strip()}
            libraries = [lib for lib in libraries if lib.id in wanted]
        libraries = [lib for lib in libraries if self._library_uses_inventory_index(lib)]
        if not libraries:
            return False
        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
        except Exception:
            return False
        for library in libraries:
            try:
                if self._index_has_usable_snapshot(service, library.id):
                    return True
            except Exception:
                logger.debug("[索引] 判断 ready 状态失败 library=%s", library.id, exc_info=True)
        return False

    def _index_relative_path(
        self,
        library: LibraryDefinition,
        absolute_path: str,
    ) -> Optional[str]:
        """把库存绝对路径转为索引用的 posix relative_path（用于 self_mutation 通知）。

        - 群晖远程库：原生 posix，简单字符串前缀剥离
        - 本地库：os.path.relpath 后把 OS sep 替换成 /
        - 路径不在库存根下 / 越界 / 路径就是库存根本身：都返回 None
          根路径返回 None 是安全设计：避免业务在异常调用路径时
          误把"" 传到 SnapshotStore.delete_subtree 触发整库删除。
        """
        if not absolute_path:
            return None
        root = library.root_path
        if not root:
            return None
        if library.type == "synology_filestation":
            norm_root = root.rstrip("/")
            norm_path = absolute_path.rstrip("/")
            if norm_path == norm_root:
                return None  # 根路径不参与 self_mutation
            prefix = norm_root + "/" if norm_root else "/"
            if norm_path.startswith(prefix):
                return norm_path[len(prefix):]
            return None
        try:
            rel = os.path.relpath(absolute_path, root)
        except ValueError:
            return None
        if rel in {".", ""} or rel.startswith(".."):
            return None
        return rel.replace(os.sep, "/")

    def _normalize_index_abs_key(self, library: LibraryDefinition, path: str) -> str:
        value = str(path or "").strip()
        if not value:
            return ""
        if library.type == "synology_filestation":
            return value.replace("\\", "/").rstrip("/")
        try:
            return os.path.normcase(os.path.normpath(os.path.abspath(value))).rstrip("\\/")
        except Exception:
            return value.replace("\\", "/").rstrip("/")

    def _is_linked_subtitle_workbench_path(self, library: LibraryDefinition, path: str) -> bool:
        """字幕补配临时工作台路径不进入库存索引。

        工作台位于库存根下的 `_kikoerumanager_subtitle_workbench/linked/...`。
        这些文件最终会发布到真实 RJ/subtitles，再由发布阶段刷新目标子树。
        """
        value = str(path or "").strip()
        if not value:
            return False
        marker = "_kikoerumanager_subtitle_workbench/linked"
        if library.type == "synology_filestation":
            normalized = self._normalize_remote_path(value).strip("/").lower()
            return normalized == marker or normalized.startswith(f"{marker}/") or f"/{marker}/" in f"/{normalized}/"
        try:
            root = os.path.abspath(library.root_path or "")
            target = os.path.abspath(value)
            if not self._local_path_is_within_root(target, root):
                return False
            relative = os.path.relpath(target, root).replace("\\", "/").strip("/").lower()
        except Exception:
            normalized = value.replace("\\", "/").strip("/").lower()
            return normalized == marker or normalized.startswith(f"{marker}/") or f"/{marker}/" in f"/{normalized}/"
        return relative == marker or relative.startswith(f"{marker}/")

    def _filter_index_move_items(
        self,
        library: LibraryDefinition,
        moved_items: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """过滤不应进入索引的内部临时路径。"""
        kept: list[dict[str, str]] = []
        for item in moved_items or []:
            source = str((item or {}).get("source") or "")
            destination = str((item or {}).get("destination") or "")
            if (
                self._is_linked_subtitle_workbench_path(library, source)
                or self._is_linked_subtitle_workbench_path(library, destination)
            ):
                continue
            kept.append(item)
        return kept

    def _compress_index_absolute_paths(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
    ) -> list[str]:
        """压缩同批路径：父目录变更覆盖子路径时只保留父路径。"""
        deduped: dict[str, str] = {}
        for raw in absolute_paths or []:
            path = str(raw or "").strip()
            if not path:
                continue
            key = self._normalize_index_abs_key(library, path)
            if key:
                deduped[key] = path
        if not deduped:
            return []

        sep = "/" if library.type == "synology_filestation" else os.sep
        kept: list[tuple[str, str]] = []
        for key, path in sorted(deduped.items(), key=lambda item: (item[0].count(sep), len(item[0]))):
            child_of_existing = False
            for existing_key, _existing_path in kept:
                if key == existing_key or key.startswith(existing_key.rstrip("\\/") + sep):
                    child_of_existing = True
                    break
            if not child_of_existing:
                kept.append((key, path))
        return [path for _key, path in kept]

    def _index_mutation_pending_count_locked(self) -> int:
        return (
            sum(len(item.get("paths") or []) for item in self._index_mutation_pending_deletes.values())
            + sum(len(item.get("paths") or []) for item in self._index_mutation_pending_upserts.values())
            + sum(len(item.get("paths") or []) for item in self._index_mutation_pending_replaces.values())
            + sum(len(item.get("items") or []) for item in self._index_mutation_pending_moves.values())
        )

    def _schedule_index_mutation_flush_locked(self, *, delay_seconds: float = 0.1) -> None:
        timer = self._index_mutation_timer
        if timer is not None and timer.is_alive():
            if delay_seconds > 0:
                return
            try:
                timer.cancel()
            except Exception:
                logger.debug("取消库存索引变更 flush timer 失败", exc_info=True)
            self._index_mutation_timer = None
        delay = max(0.0, float(delay_seconds or 0))
        timer = threading.Timer(delay, self._flush_index_mutations)
        timer.daemon = True
        self._index_mutation_timer = timer
        timer.start()

    def _queue_index_paths(
        self,
        bucket: dict[str, dict[str, Any]],
        library: LibraryDefinition,
        absolute_paths: list[str],
    ) -> bool:
        paths = [str(path or "").strip() for path in absolute_paths or [] if str(path or "").strip()]
        if not paths:
            return False
        loop = None
        if library.type == "synology_filestation":
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        force_flush = False
        with self._index_mutation_lock:
            entry = bucket.setdefault(library.id, {"library": library, "paths": []})
            entry["library"] = library
            if loop is not None:
                entry["loop"] = loop
            entry["paths"] = self._compress_index_absolute_paths(
                library,
                [*(entry.get("paths") or []), *paths],
            )
            force_flush = self._index_mutation_pending_count_locked() >= 200
            self._schedule_index_mutation_flush_locked(delay_seconds=0 if force_flush else 0.1)
        return True

    def _queue_index_moves(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        moved_items: list[dict[str, Any]],
    ) -> bool:
        items = [dict(item or {}) for item in moved_items or [] if item]
        if not items:
            return False
        loop = None
        if source_library.type == "synology_filestation" or target_library.type == "synology_filestation":
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        force_flush = False
        with self._index_mutation_lock:
            key = (source_library.id, target_library.id)
            entry = self._index_mutation_pending_moves.setdefault(
                key,
                {"source_library": source_library, "target_library": target_library, "items": []},
            )
            entry["source_library"] = source_library
            entry["target_library"] = target_library
            if loop is not None:
                entry["loop"] = loop
            entry["items"].extend(items)
            force_flush = self._index_mutation_pending_count_locked() >= 200
            self._schedule_index_mutation_flush_locked(delay_seconds=0 if force_flush else 0.1)
        return True

    def _enqueue_index_delete_many(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        scopes_by_path: Optional[dict[str, str]] = None,
    ) -> bool:
        return self._record_index_reconcile_many(
            library,
            absolute_paths,
            kind="delete",
            source="self_mutation_delete",
            scopes_by_path=scopes_by_path,
        )

    def _enqueue_index_upsert_subtree_many(self, library: LibraryDefinition, absolute_paths: list[str]) -> bool:
        return self._record_index_reconcile_many(
            library,
            absolute_paths,
            kind="reconcile",
            source="self_mutation_upsert",
        )

    def _enqueue_index_replace_subtree_many(self, library: LibraryDefinition, absolute_paths: list[str]) -> bool:
        return self._record_index_reconcile_many(
            library,
            absolute_paths,
            kind="reconcile",
            source="self_mutation_replace",
        )

    def _enqueue_index_move_many(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        moved_items: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        return self._record_index_move_many(
            source_library,
            target_library,
            moved_items,
            source="self_mutation_move",
        )

    def _flush_index_move_many_now(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        moved_items: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        items = [dict(item or {}) for item in moved_items or [] if item]
        if not items:
            return None
        try:
            return self._record_index_move_many(
                source_library,
                target_library,
                items,
                source="self_mutation_move_sync",
            )
        except Exception:
            logger.warning(
                "[索引] 同步追赶 move 失败 source=%s target=%s count=%s",
                source_library.id,
                target_library.id,
                len(items),
                exc_info=True,
            )
            return None

    def _flush_index_delete_many_now(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        scopes_by_path: Optional[dict[str, str]] = None,
    ) -> None:
        paths = self._compress_index_absolute_paths(library, absolute_paths or [])
        if not paths:
            return
        try:
            self._record_index_reconcile_many(
                library,
                paths,
                kind="delete",
                source="self_mutation_delete_sync",
                scopes_by_path=scopes_by_path,
            )
        except Exception:
            logger.warning(
                "[索引] 同步追赶 delete 失败 library=%s count=%s",
                library.id,
                len(paths),
                exc_info=True,
            )

    def _flush_index_mutations(self) -> None:
        with self._index_mutation_lock:
            timer = self._index_mutation_timer
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    logger.debug("取消库存索引变更 flush timer 失败", exc_info=True)
            self._index_mutation_timer = None

            deletes = self._index_mutation_pending_deletes
            upserts = self._index_mutation_pending_upserts
            replaces = self._index_mutation_pending_replaces
            moves = self._index_mutation_pending_moves

            self._index_mutation_pending_deletes = {}
            self._index_mutation_pending_upserts = {}
            self._index_mutation_pending_replaces = {}
            self._index_mutation_pending_moves = {}

        if not (deletes or upserts or replaces or moves):
            return

        def _runner() -> None:
            self._run_index_mutation_flush(
                deletes=deletes,
                upserts=upserts,
                replaces=replaces,
                moves=moves,
            )

        try:
            future = self._local_index_upsert_executor.submit(_runner)
            self._track_index_upsert_future(future)
        except RuntimeError:
            logger.warning("[索引] 后台 worker 已关闭，跳过库存索引变更 flush")
        except Exception:
            logger.warning("[索引] 提交库存索引变更 flush 失败", exc_info=True)

    def _run_index_mutation_flush(
        self,
        *,
        deletes: dict[str, dict[str, Any]],
        upserts: dict[str, dict[str, Any]],
        replaces: dict[str, dict[str, Any]],
        moves: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
            for entry in deletes.values():
                self._run_index_delete_flush(service, entry)

            for entry in moves.values():
                self._run_index_move_flush(service, entry)

            for entry in replaces.values():
                self._run_index_replace_flush(service, entry)

            for entry in upserts.values():
                self._run_index_upsert_flush(service, entry)
        except Exception:
            logger.warning("[索引] 库存索引变更 flush 失败", exc_info=True)

    def _run_index_delete_flush(self, service, entry: dict[str, Any]) -> None:
        library: LibraryDefinition = entry["library"]
        if not service.is_ready(library.id):
            return
        rels = [
            self._index_relative_path(library, path)
            for path in self._compress_index_absolute_paths(library, entry.get("paths") or [])
        ]
        rels = [rel for rel in rels if rel]
        if rels:
            service.handle_self_mutation_batch(library.id, deletes=rels)

    def _run_index_move_flush(self, service, entry: dict[str, Any]) -> None:
        source_library: LibraryDefinition = entry["source_library"]
        target_library: LibraryDefinition = entry["target_library"]
        loop = entry.get("loop")
        source_ready = service.is_ready(source_library.id)
        target_ready = service.is_ready(target_library.id)
        if not source_ready and not target_ready:
            return

        move_payload: list[dict[str, str]] = []
        fallback_upserts: list[str] = []
        fallback_deletes: list[str] = []
        for item in entry.get("items") or []:
            source_path = str(item.get("source") or item.get("old_path") or item.get("from") or "")
            dest_path = str(item.get("destination") or item.get("new_path") or item.get("to") or "")
            if not source_path or not dest_path:
                continue
            old_rel = self._index_relative_path(source_library, source_path)
            new_rel = self._index_relative_path(target_library, dest_path)
            if old_rel and source_ready:
                fallback_deletes.append(old_rel)
            if new_rel and target_ready:
                fallback_upserts.append(dest_path)
            if old_rel and new_rel and source_ready and target_ready:
                move_payload.append({
                    "source_library_id": source_library.id,
                    "target_library_id": target_library.id,
                    "old_relative_path": old_rel,
                    "new_relative_path": new_rel,
                    "old_absolute_path": source_path,
                    "new_absolute_path": dest_path,
                })

        moved_counts = service.handle_self_mutation_move_many(move_payload) if move_payload else []
        moved_destinations = {
            move_payload[index]["new_absolute_path"]
            for index, moved in enumerate(moved_counts)
            if int(moved or 0) > 0
        }
        moved_sources = {
            move_payload[index]["old_relative_path"]
            for index, moved in enumerate(moved_counts)
            if int(moved or 0) > 0
        }

        remaining_deletes = [rel for rel in fallback_deletes if rel not in moved_sources]
        if remaining_deletes and source_ready:
            service.handle_self_mutation_batch(source_library.id, deletes=remaining_deletes)

        remaining_upserts = [path for path in fallback_upserts if path not in moved_destinations]
        if remaining_upserts and target_ready:
            self._upsert_index_subtrees_now(service, target_library, remaining_upserts, loop=loop)

    def _run_index_replace_flush(self, service, entry: dict[str, Any]) -> None:
        library: LibraryDefinition = entry["library"]
        if not service.is_ready(library.id):
            return
        paths = self._compress_index_absolute_paths(library, entry.get("paths") or [])
        rels = [self._index_relative_path(library, path) for path in paths]
        rels = [rel for rel in rels if rel]
        if rels:
            service.handle_self_mutation_batch(library.id, deletes=rels)
        self._upsert_index_subtrees_now(service, library, paths, loop=entry.get("loop"))

    def _run_index_upsert_flush(self, service, entry: dict[str, Any]) -> None:
        library: LibraryDefinition = entry["library"]
        if not service.is_ready(library.id):
            return
        self._upsert_index_subtrees_now(
            service,
            library,
            self._compress_index_absolute_paths(library, entry.get("paths") or []),
            loop=entry.get("loop"),
        )

    def _upsert_index_subtrees_now(
        self,
        service,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        loop=None,
    ) -> None:
        paths = [path for path in absolute_paths or [] if self._index_relative_path(library, path)]
        if not paths:
            return
        if library.type == "synology_filestation":
            # 不再直接 dispatch：先进跨 flush 去抖缓冲，攒一会儿合并成一次 serial
            # dispatch，减少群晖端 SYNO.Search task 数量（见 __init__ 注释）。
            self._enqueue_remote_upsert_debounced(library, paths, loop=loop)
            return
        root = library.root_path or ""
        for path in paths:
            try:
                service.upsert_subtree_local(library.id, root, path)
            except FileNotFoundError:
                logger.debug(
                    "[索引] 本地子树已不存在，跳过 upsert library=%s path=%s",
                    library.id,
                    path,
                )
            except Exception:
                logger.warning(
                    "[索引] 本地子树 upsert 失败 library=%s path=%s",
                    library.id,
                    path,
                    exc_info=True,
                )

    @staticmethod
    def _remote_upsert_debounce_seconds() -> float:
        """远程子树 upsert 去抖窗口：最后一次入队后静默多久才真正 dispatch。

        可用 KIKOERUMANAGER_REMOTE_UPSERT_DEBOUNCE_SECONDS 覆盖，默认 3s。
        """
        raw = os.getenv("KIKOERUMANAGER_REMOTE_UPSERT_DEBOUNCE_SECONDS", "")
        try:
            value = float(raw)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
        return 3.0

    @staticmethod
    def _remote_upsert_debounce_max_seconds() -> float:
        """去抖封顶：距首次入队超过此秒数即强制 dispatch，避免持续写入导致永不刷新。

        可用 KIKOERUMANAGER_REMOTE_UPSERT_DEBOUNCE_MAX_SECONDS 覆盖，默认 30s。
        """
        raw = os.getenv("KIKOERUMANAGER_REMOTE_UPSERT_DEBOUNCE_MAX_SECONDS", "")
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        return 30.0

    def _enqueue_remote_upsert_debounced(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        loop=None,
    ) -> None:
        """把远程子树 upsert 路径攒进去抖缓冲，跨 flush 周期合并成一次 dispatch。

        - 同 library 的路径累积到一个 bucket，最后一次入队后静默
          _remote_upsert_debounce_seconds 才触发 dispatch
        - 距首次入队超过 _remote_upsert_debounce_max_seconds 立即触发（封顶），
          避免持续写入把 flush 无限推后
        - loop：远程 dispatch 需要的 event loop（由上游 _queue_index_paths 捕获）。
          timer 在独立线程触发，必须用保存的 loop 而不是当时的 running loop。
        """
        paths = [str(p) for p in absolute_paths or [] if p]
        if not paths:
            return
        debounce = self._remote_upsert_debounce_seconds()
        # 去抖关闭（<=0）：退化为原即时 dispatch，保持旧行为可回退
        if debounce <= 0:
            self._dispatch_remote_upsert_subtrees_serial(library, paths, loop=loop)
            return

        fire_now = False
        with self._remote_upsert_debounce_lock:
            bucket = self._remote_upsert_debounce.get(library.id)
            if bucket is None:
                bucket = {
                    "library": library,
                    "paths": [],
                    "loop": loop,
                    "first_enqueued_at": time.monotonic(),
                }
                self._remote_upsert_debounce[library.id] = bucket
            bucket["library"] = library
            if loop is not None:
                bucket["loop"] = loop
            bucket["paths"] = self._compress_index_absolute_paths(
                library, [*(bucket.get("paths") or []), *paths],
            )
            # 封顶判定：距首次入队已超过 max，立刻 fire，不再续 timer
            first_at = float(bucket.get("first_enqueued_at") or time.monotonic())
            if time.monotonic() - first_at >= self._remote_upsert_debounce_max_seconds():
                fire_now = True
            else:
                old_timer = self._remote_upsert_debounce_timers.pop(library.id, None)
                if old_timer is not None:
                    try:
                        old_timer.cancel()
                    except Exception:
                        logger.debug("取消远程 upsert 去抖 timer 失败", exc_info=True)
                timer = threading.Timer(
                    debounce, self._fire_remote_upsert_debounced, args=(library.id,),
                )
                timer.daemon = True
                self._remote_upsert_debounce_timers[library.id] = timer
                timer.start()
        if fire_now:
            self._fire_remote_upsert_debounced(library.id)

    def _fire_remote_upsert_debounced(self, library_id: str) -> None:
        """去抖窗口到期：取出该 library 攒下的远程路径，合并成一次 serial dispatch。"""
        with self._remote_upsert_debounce_lock:
            timer = self._remote_upsert_debounce_timers.pop(library_id, None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    logger.debug("取消远程 upsert 去抖 timer 失败", exc_info=True)
            bucket = self._remote_upsert_debounce.pop(library_id, None)
        if not bucket:
            return
        library = bucket.get("library")
        paths = bucket.get("paths") or []
        loop = bucket.get("loop")
        if library is None or not paths:
            return
        try:
            self._dispatch_remote_upsert_subtrees_serial(library, paths, loop=loop)
        except Exception:
            logger.warning(
                "[索引] 远程 upsert 去抖 dispatch 失败 library=%s count=%s",
                library_id, len(paths), exc_info=True,
            )

    def _notify_index_self_mutation_delete(
        self,
        library: LibraryDefinition,
        absolute_path: str,
        *,
        sync: bool = False,
        scope: Optional[str] = None,
    ) -> None:
        """本地写操作完成后，后台批量通知索引删除。

        - 索引未就绪 / 模块异常时静默跳过，不影响业务返回值
        - 路径不在库存根下时静默跳过（不应发生但兜底）
        """
        if not self._library_uses_inventory_index(library):
            return
        scopes_by_path = None
        if scope in {"exact", "subtree"}:
            scopes_by_path = {os.path.normcase(os.path.abspath(absolute_path)): scope}
        try:
            if sync:
                self._flush_index_delete_many_now(
                    library,
                    [absolute_path],
                    scopes_by_path=scopes_by_path,
                )
            else:
                self._enqueue_index_delete_many(
                    library,
                    [absolute_path],
                    scopes_by_path=scopes_by_path,
                )
        except Exception:
            logger.debug(
                "通知索引删除失败 library=%s path=%s",
                library.id, absolute_path, exc_info=True,
            )

    def _notify_index_self_mutation_delete_batch(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        sync: bool = False,
        scopes_by_path: Optional[dict[str, str]] = None,
    ) -> None:
        """批量通知索引删除：后台队列合并执行，避免阻塞业务请求。"""
        if not self._library_uses_inventory_index(library):
            return
        try:
            if sync:
                self._flush_index_delete_many_now(
                    library,
                    absolute_paths,
                    scopes_by_path=scopes_by_path,
                )
            else:
                self._enqueue_index_delete_many(
                    library,
                    absolute_paths,
                    scopes_by_path=scopes_by_path,
                )
        except Exception:
            logger.debug(
                "批量通知索引删除失败 library=%s count=%s",
                library.id, len(absolute_paths or []), exc_info=True,
            )

    def _notify_index_self_mutation_move_batch(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        moved_items: list[dict[str, Any]],
        *,
        sync: bool = False,
    ) -> Optional[dict[str, Any]]:
        if not self._library_uses_inventory_index(source_library) and not self._library_uses_inventory_index(target_library):
            return None
        try:
            if sync:
                return self._flush_index_move_many_now(source_library, target_library, moved_items)
            return self._enqueue_index_move_many(source_library, target_library, moved_items)
        except Exception:
            logger.debug(
                "[索引] 本地移动索引追赶调度失败 source=%s target=%s",
                source_library.id,
                target_library.id,
                exc_info=True,
            )
            return None

    def notify_index_move_batch(
        self,
        library_id: str,
        moved_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """提交最终索引 move 批次。

        字幕补配会先做两阶段安全重命名，全部成功后再用原始路径 -> 最终路径
        一次性提交索引最终状态；不把 Phase1/Phase2 临时名逐条写进索引。
        """
        library = self.get_library_definition(library_id)
        if not self._library_uses_inventory_index(library):
            return {
                "submitted": False,
                "submitted_count": 0,
                "submit_error": "remote_library_index_disabled",
                "queued": False,
                "queued_count": 0,
                "filtered_count": len(moved_items or []),
                "total_count": len(moved_items or []),
            }
        normalized_items: list[dict[str, str]] = []
        for raw in moved_items or []:
            source = str((raw or {}).get("source") or "").strip()
            destination = str((raw or {}).get("destination") or "").strip()
            if not source or not destination or source == destination:
                continue
            normalized_items.append({"source": source, "destination": destination})
        indexable_items = self._filter_index_move_items(library, normalized_items)
        submitted = False
        submit_error = ""
        if indexable_items:
            try:
                submitted = bool(self._record_index_move_many(
                    library,
                    library,
                    indexable_items,
                    source="subtitle_final_move",
                ))
            except Exception as exc:
                submit_error = str(exc)
                logger.warning(
                    "[索引] 字幕补配最终索引批量提交失败 library=%s count=%s",
                    library.id,
                    len(indexable_items),
                    exc_info=True,
                )
        return {
            "submitted": submitted,
            "submitted_count": len(indexable_items) if submitted else 0,
            "submit_error": submit_error,
            "queued": False,
            "queued_count": 0,
            "filtered_count": max(0, len(normalized_items) - len(indexable_items)),
            "total_count": len(normalized_items),
        }

    def _notify_index_self_mutation_upsert_subtree(
        self,
        library: LibraryDefinition,
        absolute_path: str,
    ) -> None:
        """业务自身写操作创建/落地新子树后调用，后台批量 upsert 索引。

        - 索引未就绪 / 模块异常时静默跳过
        - 路径不在库存根下 / 越界：静默跳过
        """
        if not absolute_path:
            return
        if not self._library_uses_inventory_index(library):
            return
        try:
            self._record_index_reconcile_by_path(
                library,
                absolute_path,
                source="self_mutation_upsert",
            )
        except Exception:
            logger.debug(
                "通知索引 upsert 子树失败 library=%s path=%s",
                library.id, absolute_path, exc_info=True,
            )

    def _dispatch_local_upsert_subtree(
        self,
        library: LibraryDefinition,
        absolute_path: str,
    ) -> None:
        """本地子树 upsert 调度：后台串行扫盘，避免阻塞业务接口。

        I/O 风险：本地 LocalScanner 对每个文件都会 os.stat。
        - 本地 SSD 上 100 个文件大约 5-20ms（可忽略）
        - NAS / SMB / NFS 挂载上同样规模可能 200-1000ms
        - 几千 / 上万图片的目录会把移动接口拖到前端 axios 超时

        移动接口本身已在 asyncio.to_thread 内执行；如果这里继续同步扫盘，
        HTTP 响应会等索引追赶完成才返回。统一扔到单 worker executor：
        - 用户操作先返回；
        - 库存索引写入串行，避免和操作历史 writer 互相抢写入预算。
        """
        from .library_index import get_library_index_service
        service = get_library_index_service()
        root = library.root_path or ""

        def _sync_runner() -> None:
            try:
                service.upsert_subtree_local(library.id, root, absolute_path)
            except Exception:
                logger.warning(
                    "[索引] 本地 upsert 子树后台任务失败 library=%s path=%s",
                    library.id, absolute_path, exc_info=True,
                )

        try:
            future = self._local_index_upsert_executor.submit(_sync_runner)
            self._track_index_upsert_future(future)
        except RuntimeError:
            logger.warning(
                "[索引] 本地 upsert executor 已关闭，跳过索引追赶 library=%s path=%s",
                library.id, absolute_path,
            )
        except Exception:
            logger.debug(
                "[索引] 本地 upsert 调度失败，退化为同步扫盘 library=%s",
                library.id, exc_info=True,
            )
            _sync_runner()

    def _dispatch_remote_upsert_subtree(
        self,
        library: LibraryDefinition,
        absolute_path: str,
    ) -> None:
        """远程子树 upsert 调度：fire-and-forget。

        SYNO.FileStation.Search 起一次 task 通常 0.5-3 秒，不能阻塞主路径。
        这里：
        1. 优先在当前 running loop 上 create_task
        2. 不在 asyncio 上下文（如同步 ThreadPool worker）→ 走 LibraryManager
           已有的远程 watcher loop（如果初始化过），否则记日志放弃
        """
        from .library_index import get_library_index_service
        service = get_library_index_service()
        client = self.get_cached_synology_client(library.synology)
        root = library.root_path or "/"
        coro = service.upsert_subtree_remote(
            library.id, client, root, absolute_path,
        )

        async def _runner() -> None:
            try:
                await coro
            except Exception:
                logger.warning(
                    "[索引] 远程 upsert 子树后台任务失败 library=%s path=%s",
                    library.id, absolute_path, exc_info=True,
                )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            task = loop.create_task(_runner())
            self._track_index_upsert_task(task)
            return

        # 没有 running loop：尽量走 LibraryManager 复用的后台 loop（如果存在），
        # 否则只能 close coroutine 并记日志，等下次手动重建
        bg_loop = getattr(self, "_remote_upsert_loop", None)
        if bg_loop is not None and not bg_loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(_runner(), bg_loop)
            self._track_index_upsert_future(future)
            return

        logger.warning(
            "[索引] 没有可用 asyncio loop，跳过远程子树 upsert library=%s path=%s "
            "（数据已落盘但索引会 stale，建议触发一次重建）",
            library.id, absolute_path,
        )
        coro.close()

    def _track_index_upsert_task(self, task) -> None:
        """跟踪 fire-and-forget 的 asyncio.Task，避免被 GC 警告。"""
        bucket = getattr(self, "_index_upsert_tasks", None)
        if bucket is None:
            bucket = set()
            self._index_upsert_tasks = bucket
        bucket.add(task)
        task.add_done_callback(bucket.discard)

    def _track_index_upsert_future(self, future) -> None:
        """跟踪跨线程 run_coroutine_threadsafe 返回的 Future。"""
        bucket = getattr(self, "_index_upsert_futures", None)
        if bucket is None:
            bucket = set()
            self._index_upsert_futures = bucket
        bucket.add(future)
        future.add_done_callback(bucket.discard)

    def _dispatch_remote_upsert_subtrees_serial(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        loop=None,
    ) -> None:
        """远程批量子树 upsert：把 N 个路径合并成 **1 个串行后台 task**。

        I/O 风险背景：
        - SYNO.FileStation.Search 起一次 task 通常 0.5-3 秒
        - 群晖搜索 task pool 上限通常 5-10 个
        - 批量 rename 30 条用 30 个并发 task 会被群晖端拒一部分

        所以这里串行执行：起 1 个后台 coroutine 顺序 await 每个子树扫描，
        群晖端最多 1 个搜索 task 在跑，避免打爆 pool。代价是 30 条 = 30×平均
        ~1s = 30s 的索引追赶时间，但不阻塞用户请求；用户也很少在 batch
        rename 后立刻搜刚改名的 RJ。
        """
        if not absolute_paths or not library.synology:
            return
        from .library_index import get_library_index_service
        service = get_library_index_service()
        if not service.is_ready(library.id):
            return
        client = self.get_cached_synology_client(library.synology)
        root = library.root_path or "/"
        # 复制一份路径列表，外部 list 后续修改不影响 task
        paths = [str(p) for p in absolute_paths if p]
        if not paths:
            return

        async def _runner() -> None:
            for path in paths:
                try:
                    await service.upsert_subtree_remote(library.id, client, root, path)
                except Exception:
                    logger.warning(
                        "[索引] 串行远程 upsert 失败 library=%s path=%s",
                        library.id, path, exc_info=True,
                    )

        if loop is not None:
            if not getattr(loop, "is_closed", lambda: True)() and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(_runner(), loop)
                self._track_index_upsert_future(future)
                return
            loop = None

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None:
            task = running_loop.create_task(_runner())
            self._track_index_upsert_task(task)
            return

        bg_loop = getattr(self, "_remote_upsert_loop", None)
        if bg_loop is not None and not bg_loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(_runner(), bg_loop)
            self._track_index_upsert_future(future)
            return

        logger.warning(
            "[索引] 没有可用 asyncio loop，跳过批量远程子树 upsert library=%s count=%s",
            library.id, len(paths),
        )

    def find_local_library_for_path(self, absolute_path: str) -> Optional[LibraryDefinition]:
        """按本地绝对路径反查所属 library。

        给那些「没有 library 上下文，只有一个 path」的兜底链路用
        （比如 ASMRSync 禁用 classify 时直接 shutil.move 到 storage.library_path）。
        路径不在任何 local 库存根下时返回 None。
        """
        if not absolute_path:
            return None
        try:
            normalized = os.path.abspath(absolute_path)
        except Exception:
            return None
        try:
            config = self.load_config()
        except Exception:
            return None
        candidates = [
            lib for lib in self._active_libraries(config)
            if getattr(lib, "type", None) == "local"
        ]
        # 选最长前缀匹配，避免一个 library 是另一个 library 的子目录时选错
        best: Optional[LibraryDefinition] = None
        best_root_len = -1
        for lib in candidates:
            root = getattr(lib, "root_path", None) or ""
            if not root:
                continue
            try:
                if not self._local_path_is_within_root(normalized, root):
                    continue
            except Exception:
                continue
            root_len = len(os.path.normcase(os.path.abspath(root)))
            if root_len > best_root_len:
                best = lib
                best_root_len = root_len
        return best

    def notify_index_upsert_by_path(self, absolute_path: str) -> None:
        """无 library 上下文时的便捷入口：按路径反查 library 后 upsert 子树。

        路径不在任何已知 local 库存根下时静默忽略。
        """
        try:
            library = self.find_local_library_for_path(absolute_path)
            if library is None:
                return
            self._record_index_reconcile_by_path(library, absolute_path, source="self_mutation")
        except Exception:
            logger.debug(
                "[索引] 按路径反查 library 后 upsert 失败 path=%s",
                absolute_path, exc_info=True,
            )

    # ========== 第一梯队接入 1：库存浏览搜索走索引 ==========
    # 本地库存搜索优先使用索引。命中时绕过 os.walk；
    # 远程群晖库存不使用库存索引，始终走 FileStation.Search。
    # 索引不可用或索引无命中时 fallback 到原逻辑，避免旧快照漏结果。

    def _build_browse_result_from_index(
        self,
        library: LibraryDefinition,
        *,
        files: list[dict[str, Any]],
        total: int,
        page: int,
        page_size: int,
        current_path: str,
        browse_root: str,
        next_page_cursor: Optional[str] = None,
        used_page_cursor: bool = False,
    ) -> dict[str, Any]:
        result = {
            "files": files,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": current_path,
            "browse_root_path": browse_root,
            "browse_via_index": True,
            "next_page_cursor": next_page_cursor,
            "used_page_cursor": bool(used_page_cursor),
        }
        if library.type == "synology_filestation":
            result["parent_path"] = None if current_path == browse_root else self._remote_parent_path(current_path)
            result["library_id"] = library.id
        else:
            result["parent_path"] = None if current_path == browse_root else os.path.dirname(current_path)
        return result

    def _build_index_pending_browse_result(
        self,
        library: LibraryDefinition,
        *,
        page: int,
        page_size: int,
        current_path: str,
        browse_root: str,
        index_status: str,
    ) -> dict[str, Any]:
        result = {
            "files": [],
            "page": page,
            "page_size": page_size,
            "total": 0,
            "current_path": current_path,
            "browse_root_path": browse_root,
            "browse_via_index": False,
            "index_refresh_pending": True,
            "index_status": index_status or "not_ready",
            "error": "library_index_not_ready",
            "next_page_cursor": None,
            "used_page_cursor": False,
        }
        if library.type == "synology_filestation":
            result["parent_path"] = None if current_path == browse_root else self._remote_parent_path(current_path)
            result["library_id"] = library.id
        else:
            result["parent_path"] = None if current_path == browse_root else os.path.dirname(current_path)
        return result

    def _build_search_entry_from_index(
        self,
        library: LibraryDefinition,
        *,
        item_id: int,
        search_root: str,
        entry,
    ) -> dict[str, Any]:
        """IndexEntry → list_files 输出格式的 file dict。"""
        is_directory = entry.entry_type == 'dir'
        full_path = entry.absolute_path

        if library.type == "synology_filestation":
            norm_search = (search_root or "/").rstrip("/") or "/"
            if full_path == norm_search:
                relative_path = entry.name
            elif norm_search and full_path.startswith(norm_search + "/"):
                relative_path = full_path[len(norm_search) + 1:]
            else:
                relative_path = entry.relative_path or entry.name
            try:
                parent_path = (
                    str(PurePosixPath(full_path).parent)
                    if full_path and full_path != "/"
                    else "/"
                )
            except Exception:
                parent_path = ""
        else:
            try:
                relative_path = os.path.relpath(full_path, search_root).replace("\\", "/")
            except ValueError:
                relative_path = entry.relative_path or entry.name
            parent_path = os.path.dirname(full_path)

        if entry.mtime:
            try:
                mtime_iso = datetime.fromtimestamp(entry.mtime / 1000.0).isoformat()
            except (OSError, ValueError, OverflowError):
                mtime_iso = None
        else:
            mtime_iso = None

        if is_directory:
            if library.type == "synology_filestation":
                size = None
                size_status = "disabled"
            else:
                size = int(entry.size or 0)
                size_status = "ready"
        else:
            size = int(entry.size or 0)
            size_status = "ready"

        return {
            "id": f"{library.id}:search:{item_id}",
            "name": entry.name,
            "path": full_path,
            "relative_path": relative_path,
            "parent_path": parent_path,
            "rjcode": entry.rjcode,
            "size": size,
            "size_status": size_status,
            "modified_time": mtime_iso,
            "unzip_time": mtime_iso,
            "is_directory": is_directory,
            "library_id": library.id,
            "library_name": library.name,
            "file_count": int(entry.file_count or 0) if is_directory else 1,
            "folder_count": None if is_directory else 0,
            "folder_count_status": "lazy" if is_directory else "ready",
            "size_via_index": bool(is_directory and library.type == "local"),
            "search_hit": True,
            "search_via_index": True,
        }

    def _index_entry_stat_is_stale(self, entry: Any, stat_result: os.stat_result) -> bool:
        indexed_mtime = getattr(entry, "mtime", None)
        try:
            current_mtime = int(stat_result.st_mtime * 1000)
        except (TypeError, ValueError, OSError, OverflowError):
            current_mtime = None
        if indexed_mtime and current_mtime and abs(int(indexed_mtime) - current_mtime) > 1000:
            return True
        if getattr(entry, "entry_type", "") == "file":
            try:
                return int(getattr(entry, "size", 0) or 0) != int(stat_result.st_size or 0)
            except (TypeError, ValueError):
                return True
        return False

    def _validate_local_index_entries_for_read(
        self,
        library: LibraryDefinition,
        entries: list[Any],
        *,
        return_stale_paths: bool = False,
    ):
        if library.type != "local" or not entries:
            return (entries, set()) if return_stale_paths else entries
        valid_entries: list[Any] = []
        missing_paths: list[str] = []
        stale_paths: list[str] = []
        stale_relative_paths: set[str] = set()
        for entry in entries:
            path = str(getattr(entry, "absolute_path", "") or "")
            if not path:
                continue
            try:
                stat_result = os.stat(path)
                is_dir = os.path.isdir(path)
            except OSError:
                missing_paths.append(path)
                continue
            if (getattr(entry, "entry_type", "") == "dir") != bool(is_dir):
                missing_paths.append(path)
                continue
            if self._index_entry_stat_is_stale(entry, stat_result):
                stale_paths.append(path)
                stale_relative_paths.add(str(getattr(entry, "relative_path", "") or ""))
            valid_entries.append(entry)

        if missing_paths:
            self._notify_index_self_mutation_delete_batch(library, missing_paths)
        if stale_paths:
            self._enqueue_index_read_repair_upserts(library, stale_paths)
        return (valid_entries, stale_relative_paths) if return_stale_paths else valid_entries

    def _enqueue_index_read_repair_upserts(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
    ) -> None:
        paths = [str(path or "").strip() for path in absolute_paths or [] if str(path or "").strip()]
        if not paths:
            return
        if not hasattr(self, "_index_read_repair_lock"):
            self._index_read_repair_lock = threading.Lock()
        if not hasattr(self, "_index_read_repair_last_seen"):
            self._index_read_repair_last_seen = {}
        now = time.monotonic()
        selected: list[str] = []
        with self._index_read_repair_lock:
            for path in paths:
                key = f"{library.id}\0{self._normalize_index_abs_key(library, path)}"
                if not key.strip("\0"):
                    continue
                last_seen = float(self._index_read_repair_last_seen.get(key) or 0)
                if now - last_seen < 5.0:
                    continue
                self._index_read_repair_last_seen[key] = now
                selected.append(path)
            if len(self._index_read_repair_last_seen) > 4096:
                cutoff = now - 60.0
                self._index_read_repair_last_seen = {
                    key: value
                    for key, value in self._index_read_repair_last_seen.items()
                    if value >= cutoff
                }
        if selected:
            try:
                self._enqueue_index_upsert_subtree_many(library, selected)
            except Exception:
                logger.debug(
                    "[索引] 读路径修补 upsert 入队失败 library=%s count=%s",
                    library.id,
                    len(selected),
                    exc_info=True,
                )

    def _local_index_entry_for_current_child(
        self,
        library: LibraryDefinition,
        service: Any,
        *,
        absolute_path: str,
        is_directory: bool,
        stat_result: os.stat_result,
    ) -> tuple[Optional[Any], bool, bool]:
        relative_path = self._index_parent_path_for_target(library, absolute_path)
        if relative_path is None:
            return None, False, False
        try:
            entry = service.get_entry(library.id, relative_path)
        except Exception:
            logger.debug(
                "[索引] 当前层条目索引读取失败 library=%s path=%s",
                library.id,
                absolute_path,
                exc_info=True,
            )
            return None, True, False
        if not entry:
            return None, True, False
        if (getattr(entry, "entry_type", "") == "dir") != bool(is_directory):
            self._notify_index_self_mutation_delete_batch(library, [absolute_path])
            return None, True, False
        return entry, False, self._index_entry_stat_is_stale(entry, stat_result)

    def _index_service_for_local_size_overlay(self, library: LibraryDefinition):
        if library.type != "local":
            return None
        return self._index_service_if_ready(library)

    def _apply_descendant_dir_counts_for_page(
        self,
        library: LibraryDefinition,
        service: Any,
        items_with_entries: list[tuple[dict[str, Any], Any]],
        *,
        include_folder_count: bool = False,
        max_paths: int = 100,
    ) -> None:
        if not include_folder_count or not items_with_entries:
            for item, _entry in items_with_entries:
                if item.get("is_directory"):
                    item["folder_count"] = None
                    item["folder_count_status"] = "lazy"
            return
        selected: list[tuple[dict[str, Any], str]] = []
        for item, entry in items_with_entries:
            if not item.get("is_directory") or not entry:
                continue
            relative_path = str(getattr(entry, "relative_path", "") or "")
            if not relative_path:
                continue
            selected.append((item, relative_path))
            if len(selected) >= max(1, int(max_paths or 1)):
                break
        if not selected:
            return
        paths = [relative_path for _item, relative_path in selected]
        try:
            descendant_dirs = service.count_descendant_dirs_many(library.id, paths)
        except Exception:
            logger.debug(
                "[索引] 当前页 folder_count 批量读取失败 library=%s count=%s",
                library.id,
                len(paths),
                exc_info=True,
            )
            for item, _relative_path in selected:
                item["folder_count"] = None
                item["folder_count_status"] = "lazy"
            return
        for item, relative_path in selected:
            item["folder_count"] = 1 + int(descendant_dirs.get(relative_path, 0) or 0)
            item["folder_count_status"] = "ready"

    def _build_local_dir_listing_cache_key(
        self,
        library: LibraryDefinition,
        *,
        target_path: str,
        search: str,
        sort_by: str,
        sort_order: str,
    ) -> tuple[Any, ...]:
        try:
            stat_result = os.stat(target_path)
            version = int(stat_result.st_mtime_ns)
        except OSError:
            version = 0
        index_generation = 1
        view_revision = 0
        try:
            from .library_index import get_library_index_service

            status = get_library_index_service().get_status(library.id)
            index_generation = int(getattr(status, "active_generation", 1) or 1)
            view_revision = int(getattr(status, "view_revision", 0) or 0)
        except Exception:
            logger.debug("读取库存目录缓存版本失败 library=%s", library.id, exc_info=True)
        return (
            library.id,
            index_generation,
            view_revision,
            os.path.normcase(os.path.abspath(target_path)),
            str(search or "").strip().lower(),
            self._normalize_library_sort_by(sort_by),
            self._normalize_library_sort_order(sort_order),
            version,
        )

    def _get_cached_local_dir_listing(self, cache_key: tuple[Any, ...]) -> Optional[dict[str, Any]]:
        if not hasattr(self, "_local_dir_listing_cache"):
            self._local_dir_listing_cache = TTLCache(max_size=128, ttl_seconds=8, name="library.local_dir_listing")
        cached = self._local_dir_listing_cache.get(cache_key)
        if not cached:
            return None
        return copy.deepcopy(cached.get("data") or {})

    def _set_cached_local_dir_listing(self, cache_key: tuple[Any, ...], data: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self, "_local_dir_listing_cache"):
            self._local_dir_listing_cache = TTLCache(max_size=128, ttl_seconds=8, name="library.local_dir_listing")
        self._local_dir_listing_cache[cache_key] = {
            "data": copy.deepcopy(data),
        }
        return data

    def _list_files_via_index(
        self,
        library: LibraryDefinition,
        *,
        page: int,
        page_size: int,
        current_path: str,
        browse_root: str,
        parent_path: str,
        sort_by: str,
        sort_order: str,
        force_refresh: bool = False,
        page_cursor: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not self._library_uses_inventory_index(library):
            return None
        try:
            from .library_index import get_library_index_service

            normalized_sort_by = self._normalize_library_sort_by(sort_by)
            service = get_library_index_service()
            if not self._index_has_usable_snapshot(service, library.id):
                if library.type == "local":
                    return None
                index_status = self._index_status_name(service, library.id)
                logger.info(
                    "库存浏览索引未就绪，返回 pending: lib=%s path=%s page=%s page_size=%s status=%s",
                    library.id,
                    current_path,
                    page,
                    page_size,
                    index_status,
                )
                return self._build_index_pending_browse_result(
                    library,
                    page=page,
                    page_size=page_size,
                    current_path=current_path,
                    browse_root=browse_root,
                    index_status=index_status,
                )
            if (
                library.type == "local"
                and hasattr(service, "has_library_entries")
                and not service.has_library_entries(library.id)
            ):
                return None
            offset = max(0, (int(page or 1) - 1) * int(page_size or 200))
            payload = service.list_children_page(
                library.id,
                parent_path,
                sort_by=normalized_sort_by,
                sort_order=self._normalize_library_sort_order(sort_order),
                offset=offset,
                limit=page_size,
                page_cursor=page_cursor,
            )

            entries = list(payload.get("entries") or [])
            raw_entry_count = len(entries)
            stale_relative_paths: set[str] = set()
            if library.type == "local":
                entries, stale_relative_paths = self._validate_local_index_entries_for_read(
                    library,
                    entries,
                    return_stale_paths=True,
                )
            if force_refresh and library.type == "local":
                refresh_paths = [
                    str(getattr(entry, "absolute_path", "") or "")
                    for entry in entries
                    if str(getattr(entry, "absolute_path", "") or "")
                ]
                if refresh_paths:
                    self._enqueue_index_read_repair_upserts(library, refresh_paths)
                    stale_relative_paths.update({
                        str(getattr(entry, "relative_path", "") or "")
                        for entry in entries
                        if str(getattr(entry, "relative_path", "") or "")
                    })
            files = []
            for index, entry in enumerate(entries):
                if self._should_skip_entry(getattr(entry, "name", "")):
                    continue
                item = self._build_search_entry_from_index(
                    library,
                    item_id=offset + index,
                    search_root=current_path,
                    entry=entry,
                )
                item["id"] = f"{library.id}:{offset + index}"
                if str(getattr(entry, "relative_path", "") or "") in stale_relative_paths:
                    item["size_status"] = "stale"
                    item["index_refresh_pending"] = True
                files.append(item)
            for item in files:
                item["browse_via_index"] = True
                item.pop("search_hit", None)
                item.pop("search_via_index", None)
                item.pop("_sort_time", None)
                item.pop("_mtime", None)
            indexed_total = max(
                0,
                int(payload.get("total") or len(files)) - max(0, raw_entry_count - len(entries)),
            )
            logger.info(
                "库存浏览走索引: lib=%s path=%s page=%s page_size=%s total=%s returned=%s cursor=%s",
                library.id,
                current_path,
                page,
                page_size,
                indexed_total,
                len(files),
                bool(payload.get("next_page_cursor")),
            )
            return self._build_browse_result_from_index(
                library,
                files=files,
                total=indexed_total,
                page=page,
                page_size=page_size,
                current_path=current_path,
                browse_root=browse_root,
                next_page_cursor=payload.get("next_page_cursor"),
                used_page_cursor=bool(payload.get("used_page_cursor")),
            )
        except Exception:
            logger.warning(
                "库存浏览索引路径异常转 fallback: lib=%s path=%s",
                library.id,
                current_path,
                exc_info=True,
            )
            return None

    def _record_index_reconcile_by_path(
        self,
        library: LibraryDefinition,
        absolute_path: str,
        *,
        source: str,
    ) -> Optional[dict[str, Any]]:
        """无 HTTP 请求上下文的落地操作统一追加 reconcile ledger。"""
        if not self._library_uses_inventory_index(library):
            return None
        relative_path = self._index_relative_path(library, absolute_path)
        if relative_path is None:
            return None
        from .library_index import get_library_index_mutation_service

        effect = {
            "kind": "reconcile",
            "relative_path": relative_path,
            "scope": "subtree" if os.path.isdir(absolute_path) else "exact",
        }
        service = get_library_index_mutation_service()
        prepared = service.prepare(
            kind="reconcile",
            effects_by_library={library.id: [effect]},
            idempotency_key=f"{source}:{library.id}:{uuid.uuid4()}",
        )
        service.mark_filesystem_started(prepared.operation_id)
        return service.finalize(
            prepared.operation_id,
            actual_effects_by_library={library.id: [effect]},
            actual_result={"source": source, "path": absolute_path},
        )

    def _record_index_reconcile_many(
        self,
        library: LibraryDefinition,
        absolute_paths: list[str],
        *,
        kind: str,
        source: str,
        scopes_by_path: Optional[dict[str, str]] = None,
    ) -> bool:
        if not self._library_uses_inventory_index(library):
            return False
        effects: list[dict[str, Any]] = []
        seen: set[str] = set()
        for absolute_path in self._compress_index_absolute_paths(library, absolute_paths or []):
            relative_path = self._index_relative_path(library, absolute_path)
            if relative_path is None or relative_path in seen:
                continue
            seen.add(relative_path)
            explicit_scope = (scopes_by_path or {}).get(
                os.path.normcase(os.path.abspath(absolute_path))
            )
            effects.append({
                "kind": kind,
                "relative_path": relative_path,
                "scope": explicit_scope
                if explicit_scope in {"exact", "subtree"}
                else (
                    "subtree"
                    if os.path.isdir(absolute_path) or not os.path.exists(absolute_path)
                    else "exact"
                ),
            })
        if not effects:
            return False
        from .library_index import get_library_index_mutation_service

        service = get_library_index_mutation_service()
        prepared = service.prepare(
            kind=source,
            effects_by_library={library.id: effects},
            idempotency_key=f"{source}:{library.id}:{uuid.uuid4()}",
        )
        service.mark_filesystem_started(prepared.operation_id)
        service.finalize(
            prepared.operation_id,
            actual_effects_by_library={library.id: effects},
            actual_result={"source": source, "path_count": len(effects)},
        )
        return True

    def _record_index_move_many(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        moved_items: list[dict[str, Any]],
        *,
        source: str,
    ) -> Optional[dict[str, Any]]:
        effects_by_library: dict[str, list[dict[str, Any]]] = {}
        for item in moved_items or []:
            source_path = str(item.get("source") or item.get("old_path") or item.get("from") or "").strip()
            destination = str(item.get("destination") or item.get("new_path") or item.get("to") or "").strip()
            if not source_path or not destination:
                continue
            old_relative = self._index_relative_path(source_library, source_path)
            new_relative = self._index_relative_path(target_library, destination)
            if old_relative is None or new_relative is None:
                continue
            scope = "subtree" if os.path.isdir(destination) or not os.path.splitext(source_path)[1] else "exact"
            effects_by_library.setdefault(source_library.id, []).append({
                "kind": "move",
                "relative_path": old_relative,
                "scope": scope,
                "target_library_id": target_library.id,
                "target_path": new_relative,
            })
            effects_by_library.setdefault(target_library.id, []).append({
                "kind": "reconcile",
                "relative_path": new_relative,
                "scope": scope,
            })
        effects_by_library = {
            library_id: effects
            for library_id, effects in effects_by_library.items()
            if effects
        }
        if not effects_by_library:
            return None
        from .library_index import get_library_index_mutation_service

        service = get_library_index_mutation_service()
        prepared = service.prepare(
            kind=source,
            effects_by_library=effects_by_library,
            idempotency_key=f"{source}:{uuid.uuid4()}",
        )
        service.mark_filesystem_started(prepared.operation_id)
        return service.finalize(
            prepared.operation_id,
            actual_effects_by_library=effects_by_library,
            actual_result={"source": source, "move_count": len(moved_items or [])},
        )

    def _build_index_search_result(
        self,
        library: LibraryDefinition,
        *,
        files: list[dict[str, Any]],
        total: int,
        page: int,
        page_size: int,
        current_path: str,
        browse_root: str,
        keyword: str,
        search_exact: bool,
        search_result_kind: str,
    ) -> dict[str, Any]:
        """为 list_files 走索引快速路径返回与原状一致的结构。"""
        result = {
            "files": files,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": current_path,
            "browse_root_path": browse_root,
            "search_mode": True,
            "search_root_path": current_path,
            "search_query": keyword,
            "search_truncated": False,
            "search_exact": bool(search_exact),
            "search_result_kind": self._normalize_search_result_kind(search_result_kind),
            "search_via_index": True,
        }
        if library.type == "synology_filestation":
            try:
                result["parent_path"] = (
                    None
                    if current_path == browse_root
                    else str(PurePosixPath(current_path).parent)
                )
            except Exception:
                result["parent_path"] = None
            result["search_scope_count"] = 0
            result["library_id"] = library.id
            result["search_global_remote"] = False
        else:
            result["parent_path"] = (
                None
                if current_path == browse_root
                else os.path.dirname(current_path)
            )
            result["scanned_directories"] = 0
        return result

    def _search_files_via_index(
        self,
        library: LibraryDefinition,
        *,
        keyword: str,
        search_root: str,
        browse_root: str,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
        search_exact: bool,
        search_result_kind: str,
    ) -> Optional[dict[str, Any]]:
        """库存搜索走索引的快速路径。返回 None 表示 fallback。"""
        if not self._library_uses_inventory_index(library):
            return None
        try:
            kind = self._normalize_search_result_kind(search_result_kind)
            normalized_keyword = str(keyword or "").strip()
            if not normalized_keyword:
                return None
            is_rj_keyword = self._is_rj_search_keyword(normalized_keyword)
            if is_rj_keyword and kind != "file":
                entry_type = "dir"
            else:
                entry_type = "dir" if kind == "folder" else ("file" if kind == "file" else None)
            from .library_index import get_library_index_service
            service = get_library_index_service()
            if not self._index_has_usable_snapshot(service, library.id):
                index_status = self._index_status_name(service, library.id)
                logger.info(
                    "库存搜索索引未就绪，返回 pending: lib=%s keyword=%s page=%s page_size=%s status=%s",
                    library.id,
                    normalized_keyword,
                    page,
                    page_size,
                    index_status,
                )
                result = self._build_index_search_result(
                    library,
                    files=[],
                    total=0,
                    page=page,
                    page_size=page_size,
                    current_path=search_root,
                    browse_root=browse_root,
                    keyword=normalized_keyword,
                    search_exact=search_exact,
                    search_result_kind=kind,
                )
                result.update({
                    "search_via_index": False,
                    "index_refresh_pending": True,
                    "index_status": index_status,
                    "error": "library_index_not_ready",
                })
                return result
            if (
                library.type == "synology_filestation"
                and hasattr(service, "has_library_entries")
                and not service.has_library_entries(library.id)
            ):
                return None
            if is_rj_keyword:
                entries = service.find_by_rjcode(
                    normalized_keyword.upper(),
                    library.id,
                    entry_type=entry_type,
                    limit=LIBRARY_SEARCH_RESULT_LIMIT,
                )
            else:
                entries = service.find_by_name(
                    library.id,
                    normalized_keyword,
                    entry_type=entry_type,
                    limit=LIBRARY_SEARCH_RESULT_LIMIT,
                )
            scoped_entries = []
            for entry in entries:
                entry_path = str(getattr(entry, "absolute_path", "") or "")
                if library.type == "synology_filestation":
                    if not self._remote_path_is_within_root(entry_path, search_root):
                        continue
                elif not self._local_path_is_within_root(entry_path, search_root):
                    continue
                scoped_entries.append(entry)
            items = [
                self._build_search_entry_from_index(
                    library, item_id=i, search_root=search_root, entry=entry,
                )
                for i, entry in enumerate(scoped_entries)
            ]
            items = [
                item for item in items
                if self._search_match_text(
                    normalized_keyword,
                    item.get("name"),
                    item.get("relative_path"),
                    item.get("rjcode"),
                    exact=search_exact,
                )
                and self._matches_search_result_kind(bool(item.get("is_directory")), kind)
            ]
            if not items:
                logger.info(
                    "库存搜索走索引无命中: lib=%s keyword=%s page=%s page_size=%s",
                    library.id,
                    normalized_keyword,
                    page,
                    page_size,
                )
                return self._build_index_search_result(
                    library,
                    files=[],
                    total=0,
                    page=page,
                    page_size=page_size,
                    current_path=search_root,
                    browse_root=browse_root,
                    keyword=normalized_keyword,
                    search_exact=search_exact,
                    search_result_kind=kind,
                )
            if library.type == "synology_filestation":
                items = self._sort_remote_page_items(items, sort_by, sort_order)
            else:
                items = self._sort_local_items(items, sort_by, sort_order)
            total = len(items)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_items = items[start:end]
            for it in page_items:
                it.pop("_sort_time", None)
                it.pop("_mtime", None)
            logger.info(
                "库存搜索走索引: lib=%s keyword=%s hits=%s page=%s page_size=%s truncated=%s",
                library.id, normalized_keyword, total, page, page_size, total >= LIBRARY_SEARCH_RESULT_LIMIT,
            )
            result = self._build_index_search_result(
                library,
                files=page_items,
                total=total,
                page=page,
                page_size=page_size,
                current_path=search_root,
                browse_root=browse_root,
                keyword=normalized_keyword,
                search_exact=search_exact,
                search_result_kind=kind,
            )
            result["search_truncated"] = total >= LIBRARY_SEARCH_RESULT_LIMIT
            return result
        except Exception:
            logger.warning(
                "索引快速搜索异常转 fallback: lib=%s keyword=%s",
                library.id, keyword, exc_info=True,
            )
            return None

    def _collect_local_stats_via_index(
        self, library: LibraryDefinition,
    ) -> Optional[dict[str, Any]]:
        """从索引状态表读取持久化聚合快照，不在热路径 SUM entries。"""
        try:
            from .library_index import get_library_index_service
            service = get_library_index_service()
            status = service.get_status(library.id)
            if not status or status.status == 'idle':
                return None
            total_size = int(status.total_size_bytes or 0)
            stats_status = (
                'ready'
                if status.status == 'ready'
                and int(getattr(status, 'accepted_seq', 0) or 0)
                == int(getattr(status, 'materialized_seq', 0) or 0)
                and getattr(status, 'building_generation', None) is None
                else ('catching_up' if status.status == 'ready' else status.status)
            )
            return {
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "status": stats_status,
                "folder_count": int(status.folder_count or 0),
                "total_size_bytes": total_size,
                "total_size_gb": _gb(total_size),
                "scan_mode": "library_index",
                "index_status": status.status,
                "progress_done": int(status.total_entries or 0),
                "progress_total": 0,
                "progress_percent": 0.0,
                "last_completed_at": (status.last_full_scan_at / 1000) if status.last_full_scan_at else None,
                "updated_at": (status.updated_at / 1000) if status.updated_at else time.time(),
                "last_error": status.error,
            }
        except Exception:
            logger.warning("本地 stats 走索引异常，fallback lib=%s",
                           library.id, exc_info=True)
            return None

    async def _collect_remote_stats_via_index(
        self, library: LibraryDefinition,
    ) -> Optional[dict[str, Any]]:
        """兼容旧调用：远程群晖库不再读取库存索引统计。"""
        return None

    def _index_parent_path_for_browse_root(self, library: LibraryDefinition) -> str:
        """把 browse_root 映射成索引 parent_path；库根对应空字符串。"""
        root = library.root_path or "/"
        browse_root = library.browse_root_path or root
        parent = self._index_parent_path_for_target(library, browse_root)
        return parent or ''

    def _index_parent_path_for_target(self, library: LibraryDefinition, target_path: str) -> Optional[str]:
        """把任意浏览路径映射成索引 parent_path；路径越界时返回 None。"""
        root = library.root_path or "/"
        if library.type == "synology_filestation":
            normalized_root = self._normalize_remote_path(root)
            normalized_target = self._normalize_remote_path(target_path or root)
            if normalized_target == normalized_root:
                return ''
            if self._remote_path_is_within_root(normalized_target, normalized_root):
                return str(PurePosixPath(normalized_target).relative_to(PurePosixPath(normalized_root))).strip('/')
            return None
        normalized_root = os.path.normcase(os.path.abspath(root))
        normalized_target = os.path.normcase(os.path.abspath(target_path or root))
        if normalized_target == normalized_root:
            return ''
        if self._local_path_is_within_root(target_path, root):
            return os.path.relpath(os.path.abspath(target_path), os.path.abspath(root)).replace("\\", "/").strip('/')
        return None

    def _stats_index_ready(self, library: LibraryDefinition) -> bool:
        """统计刷新只认 ready 索引，避免无索引时触发磁盘或远程 IO。"""
        try:
            from .library_index import get_library_index_service
            return bool(get_library_index_service().is_ready(library.id))
        except Exception:
            logger.warning("统计索引状态检查失败 lib=%s", library.id, exc_info=True)
            return False

    async def list_first_level_directories(
        self,
        library_id: str,
        path: Optional[str] = None,
        *,
        page_size: int = 500,
    ) -> dict[str, Any]:
        """列出指定路径下的一级子目录（不递归）。"""

        library = self.get_library_definition(library_id)
        target_path = (path or "").strip() or None
        data = await self.list_files(
            library.id,
            page=1,
            page_size=page_size,
            search="",
            current_path=target_path,
            sort_by="name",
            sort_order="asc",
        )
        directories: list[dict[str, Any]] = []
        for entry in list(data.get("files") or []):
            if not entry.get("is_directory", False):
                continue
            directories.append({
                "name": str(entry.get("name") or ""),
                "path": str(entry.get("path") or ""),
                "size": entry.get("size"),
                "modified_time": entry.get("modified_time"),
            })
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "current_path": data.get("current_path") or target_path or library.root_path,
            "browse_root_path": data.get("browse_root_path") or library.browse_root_path,
            "directories": directories,
            "total": len(directories),
        }

    async def global_search_files(
        self,
        library_id: Optional[str],
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 200,
        sort_by: str = "name",
        sort_order: str = "asc",
        force_refresh: bool = False,
        search_exact: bool = False,
        search_result_kind: str = "all",
        remote_warmup_retries: int = 3,
        page_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_keyword = str(keyword or "").strip()
        requested_library = self.get_library_definition(library_id) if library_id else None
        remote_libraries = [
            library
            for library in self._active_libraries()
            if library.type == "synology_filestation"
        ]
        if remote_libraries and (requested_library is None or requested_library.type == "synology_filestation"):
            tasks: dict[asyncio.Task, LibraryDefinition] = {
                asyncio.create_task(
                    self.list_files(
                        library.id,
                        page=1,
                        page_size=LIBRARY_SEARCH_RESULT_LIMIT,
                        search=normalized_keyword,
                        current_path=None,
                        sort_by=sort_by,
                        sort_order=sort_order,
                        force_refresh=force_refresh,
                        search_exact=search_exact,
                        search_result_kind=search_result_kind,
                        remote_warmup_retries=remote_warmup_retries,
                    )
                ): library
                for library in remote_libraries
            }
            try:
                combined_files: list[dict[str, Any]] = []
                searched_library_count = 0
                hit_library_count = 0
                search_scope_count = 0
                truncated = False
                for task, library in tasks.items():
                    try:
                        result = await task
                    except Exception:
                        logger.warning(
                            "远程全局搜索失败: keyword=%s library=%s",
                            normalized_keyword,
                            library.id,
                            exc_info=True,
                        )
                        continue
                    searched_library_count += 1
                    files = list(result.get("files") or [])
                    total = int(result.get("total") or len(files))
                    if files or total:
                        hit_library_count += 1
                        logger.info(
                            "远程全局搜索命中: keyword=%s library=%s total=%s",
                            normalized_keyword,
                            library.id,
                            total,
                        )
                    search_scope_count += int(result.get("search_scope_count") or 0)
                    truncated = truncated or bool(result.get("search_truncated"))
                    combined_files.extend(files)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()

            combined_files = self._sort_remote_page_items(combined_files, sort_by, sort_order)
            if len(combined_files) > LIBRARY_SEARCH_RESULT_LIMIT:
                combined_files = combined_files[:LIBRARY_SEARCH_RESULT_LIMIT]
                truncated = True
            combined_total = len(combined_files)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_items = combined_files[start:end]
            for item in page_items:
                item.pop("_mtime", None)
            display_library = requested_library or remote_libraries[0]
            return {
                "files": page_items,
                "page": page,
                "page_size": page_size,
                "total": combined_total,
                "current_path": display_library.browse_root_path or display_library.root_path,
                "browse_root_path": display_library.browse_root_path or display_library.root_path,
                "parent_path": None,
                "search_mode": True,
                "search_root_path": "/",
                "search_query": normalized_keyword,
                "search_truncated": truncated,
                "search_scope_count": search_scope_count,
                "search_global_remote": True,
                "searched_library_count": searched_library_count,
                "hit_library_count": hit_library_count,
                "search_exact": bool(search_exact),
                "search_result_kind": self._normalize_search_result_kind(search_result_kind),
                "library_id": display_library.id,
            }
        return await self.list_files(
            library_id,
            page=page,
            page_size=page_size,
            search=keyword,
            current_path=None,
            sort_by=sort_by,
            sort_order=sort_order,
            force_refresh=force_refresh,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
            remote_warmup_retries=remote_warmup_retries,
            page_cursor=page_cursor,
        )

    def _normalize_search_result_kind(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"folder", "dir", "directory"}:
            return "folder"
        if normalized in {"file", "files"}:
            return "file"
        return "all"

    def _matches_search_result_kind(self, is_directory: bool, search_result_kind: str) -> bool:
        normalized_kind = self._normalize_search_result_kind(search_result_kind)
        if normalized_kind == "folder":
            return bool(is_directory)
        if normalized_kind == "file":
            return not bool(is_directory)
        return True

    def _search_match_text(self, keyword: str, *values: Any, exact: bool = False) -> bool:
        normalized_keyword = str(keyword or "").strip().lower()
        if not normalized_keyword:
            return False
        for value in values:
            text = str(value or "").lower()
            if exact and text == normalized_keyword:
                return True
            if not exact and normalized_keyword in text:
                return True
        return False

    def _is_rj_search_keyword(self, keyword: str) -> bool:
        normalized = str(keyword or "").strip().upper()
        if not normalized:
            return False
        return self._extract_rjcode(normalized) == normalized

    def _local_path_is_within_root(self, path: str, root_path: str) -> bool:
        try:
            normalized_path = os.path.normcase(os.path.abspath(path))
            normalized_root = os.path.normcase(os.path.abspath(root_path))
            return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
        except (OSError, ValueError):
            return False

    def _find_nearest_local_rj_directory(self, path: str, search_root: str) -> Optional[str]:
        current = os.path.abspath(path)
        root = os.path.abspath(search_root)
        if os.path.isfile(current):
            current = os.path.dirname(current)
        while current and self._local_path_is_within_root(current, root):
            if self._extract_rjcode(os.path.basename(current) or current):
                return current
            if current == root:
                break
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return None

    def _find_nearest_remote_rj_directory(self, path: str, search_root: str) -> Optional[str]:
        current = PurePosixPath(self._normalize_remote_path(path))
        root = PurePosixPath(self._normalize_remote_path(search_root))
        if "." in current.name:
            current = current.parent
        while True:
            current_str = str(current)
            if current_str == ".":
                current_str = "/"
            if current_str != str(root) and not current_str.startswith(str(root).rstrip("/") + "/"):
                return None
            if self._extract_rjcode(current.name or current_str):
                return current_str
            if current == root or str(current) in {"", "/"}:
                break
            current = current.parent
        return None

    def _build_local_search_entry(
        self,
        library: LibraryDefinition,
        *,
        item_id: int,
        search_root: str,
        full_path: str,
        name: str,
        is_directory: bool,
        stat_result: os.stat_result,
    ) -> dict[str, Any]:
        relative_path = os.path.relpath(full_path, search_root).replace("\\", "/")
        parent_path = os.path.dirname(full_path)
        cached_size, cached_size_status = self._get_cached_size_info(full_path) if is_directory else (stat_result.st_size, "ready")
        return {
            "id": f"{library.id}:search:{item_id}",
            "name": name,
            "path": full_path,
            "relative_path": relative_path,
            "parent_path": parent_path,
            "rjcode": self._extract_rjcode(relative_path) or self._extract_rjcode(name),
            "size": cached_size,
            "size_status": cached_size_status,
            "modified_time": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
            "unzip_time": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
            "is_directory": is_directory,
            "library_id": library.id,
            "library_name": library.name,
            "search_hit": True,
            "_sort_time": stat_result.st_mtime,
        }

    def _search_local_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        search_exact: bool = False,
        search_result_kind: str = "all",
    ) -> dict[str, Any]:
        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        search_root = os.path.abspath(current_path or browse_root)
        if not os.path.exists(browse_root):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": browse_root, "browse_root_path": browse_root, "search_mode": True}
        if not self._local_path_is_within_root(search_root, browse_root):
            search_root = browse_root
        if not os.path.isdir(search_root):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": search_root, "browse_root_path": browse_root, "search_mode": True}

        # 命中缓存就直接返回，避免重复扫盘
        cache_key = self._build_local_search_cache_key(
            library_id=library.id,
            search_root=search_root,
            keyword=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
        )
        cached = self._get_cached_local_search_result(cache_key)
        if cached is not None:
            logger.debug(
                "本地搜索命中缓存: library=%s keyword=%s page=%s",
                library.id,
                search,
                page,
            )
            return cached

        keyword = str(search or "").strip()
        rj_only_search = self._is_rj_search_keyword(keyword)

        # === 第一梯队接入 1：RJ 搜索走索引快速路径 ===
        indexed_result = self._search_files_via_index(
            library,
            keyword=keyword,
            search_root=search_root,
            browse_root=browse_root,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
        )
        if indexed_result is not None:
            if indexed_result.get("index_refresh_pending"):
                return indexed_result
            return self._set_cached_local_search_result(cache_key, indexed_result)
        normalized_result_kind = self._normalize_search_result_kind(search_result_kind)
        treat_rj_dir_as_terminal = rj_only_search and normalized_result_kind != "file"
        matches: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        # pruned_dirs：已命中 RJ 目录后剪枝（不再深入这个 RJ 目录树），避免重复 IO。
        pruned_dirs: set[str] = set()
        queue: list[str] = [search_root]
        visited_dirs = 0
        truncated = False

        while queue:
            current_dir = queue.pop()
            visited_dirs += 1
            try:
                with os.scandir(current_dir) as entries:
                    children = list(entries)
            except OSError:
                continue

            for entry in children:
                name = entry.name
                if self._should_skip_entry(name):
                    continue

                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue

                full_path = entry.path
                # 优先用文件名直接提取 RJ 号；只有当文件名没有时才回退到相对路径，
                # 避免每个深层文件都做重复的 relpath 计算。
                rjcode = self._extract_rjcode(name)
                relative_path: Optional[str] = None
                if not rjcode:
                    relative_path = os.path.relpath(full_path, search_root).replace("\\", "/")
                    rjcode = self._extract_rjcode(relative_path)
                if relative_path is None:
                    relative_path = name  # _search_match_text 仅用于 keyword 匹配，name 已足够

                should_dive = is_directory  # 默认是否进入这个目录递归
                if self._search_match_text(keyword, name, relative_path, rjcode, exact=search_exact):
                    target_path = full_path
                    target_name = name
                    target_is_directory = is_directory
                    if treat_rj_dir_as_terminal:
                        nearest_rj_dir = self._find_nearest_local_rj_directory(full_path, search_root)
                        if not nearest_rj_dir:
                            # 命中但不在 RJ 目录里（如 share 顶层散文件），允许继续往下找
                            if is_directory:
                                queue.append(full_path)
                            continue
                        target_path = nearest_rj_dir
                        target_name = os.path.basename(nearest_rj_dir)
                        target_is_directory = True
                        # 关键剪枝：找到 RJ 目录后不再扫它的子项（音轨 / 字幕 / 封面 …）。
                        should_dive = False
                        pruned_dirs.add(target_path)
                    if target_path not in seen_paths:
                        try:
                            stat_result = os.stat(target_path)
                        except OSError:
                            stat_result = None
                        if stat_result:
                            if not self._matches_search_result_kind(target_is_directory, search_result_kind):
                                # 类型不匹配跳过，但也别再深入扫这个分支
                                if treat_rj_dir_as_terminal:
                                    continue
                            else:
                                seen_paths.add(target_path)
                                matches.append(
                                    self._build_local_search_entry(
                                        library,
                                        item_id=len(matches),
                                        search_root=search_root,
                                        full_path=target_path,
                                        name=target_name,
                                        is_directory=target_is_directory,
                                        stat_result=stat_result,
                                    )
                                )
                                if len(matches) >= LIBRARY_SEARCH_RESULT_LIMIT:
                                    truncated = True
                                    queue.clear()
                                    break
                    # 命中即视为"这个分支已经处理"，不再深入
                    if not should_dive:
                        continue

                # 没命中或不需剪枝，按需进入子目录
                if is_directory and full_path not in pruned_dirs:
                    queue.append(full_path)

            if truncated:
                break

        matches = self._sort_local_items(matches, sort_by, sort_order)
        total = len(matches)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = matches[start:end]
        for item in page_items:
            item.pop("_sort_time", None)
        result = {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": search_root,
            "browse_root_path": browse_root,
            "parent_path": None if search_root == browse_root else os.path.dirname(search_root),
            "search_mode": True,
            "search_root_path": search_root,
            "search_query": keyword,
            "search_truncated": truncated,
            "scanned_directories": visited_dirs,
            "search_exact": bool(search_exact),
            "search_result_kind": self._normalize_search_result_kind(search_result_kind),
        }
        return self._set_cached_local_search_result(cache_key, result)

    def _list_local_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        force_refresh: bool = False,
        page_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        target_path = os.path.abspath(current_path or browse_root)
        if not os.path.exists(browse_root):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": browse_root, "browse_root_path": browse_root}
        if not self._local_path_is_within_root(target_path, browse_root):
            target_path = browse_root
        if not os.path.isdir(target_path):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": target_path, "browse_root_path": browse_root}

        search_lower = search.lower().strip()
        cache_key = self._build_local_dir_listing_cache_key(
            library,
            target_path=target_path,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        cached_listing = None if force_refresh else self._get_cached_local_dir_listing(cache_key)
        if cached_listing:
            items = list(cached_listing.get("items") or [])
        else:
            items = []
            try:
                entries = list(os.scandir(target_path))
            except OSError:
                return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": target_path, "browse_root_path": browse_root}

            for item_id, entry in enumerate(entries):
                if self._should_skip_entry(entry.name):
                    continue
                rjcode = self._extract_rjcode(entry.name)
                if search_lower and search_lower not in entry.name.lower() and search_lower not in (rjcode or "").lower():
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                child_path = os.path.abspath(entry.path)
                relative_path = self._index_parent_path_for_target(library, child_path) or entry.name
                items.append({
                    "id": f"{library.id}:{item_id}",
                    "name": entry.name,
                    "path": child_path,
                    "relative_path": relative_path,
                    "parent_path": target_path,
                    "rjcode": rjcode,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "unzip_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_directory": is_directory,
                    "library_id": library.id,
                    "library_name": library.name,
                    "_sort_time": stat.st_mtime,
                    "_stat_size": int(stat.st_size),
                    "_stat_mtime_ms": int(stat.st_mtime * 1000),
                })
            items = self._sort_local_items(items, sort_by, sort_order)
            self._set_cached_local_dir_listing(cache_key, {"items": items})

        # 列表行以磁盘当前层为事实源；索引只叠加目录大小/数量等摘要。
        # 索引缺失或旧了只排后台修补，绝不在列表请求里递归 os.walk。
        index_service = self._index_service_for_local_size_overlay(library)
        repair_paths: list[str] = []
        entries_with_index: list[tuple[dict[str, Any], Optional[Any]]] = []

        total = len(items)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = copy.deepcopy(items[start:end])

        for item in page_items:
            is_directory = bool(item.get("is_directory"))
            child_path = str(item.get("path") or "")
            index_entry = None
            index_missing = False
            index_stale = False
            stat_result = None
            if index_service is not None:
                try:
                    stat_result = os.stat(child_path)
                    index_entry, index_missing, index_stale = self._local_index_entry_for_current_child(
                        library,
                        index_service,
                        absolute_path=child_path,
                        is_directory=is_directory,
                        stat_result=stat_result,
                    )
                    if index_missing or index_stale:
                        repair_paths.append(child_path)
                except OSError:
                    index_missing = True
            if is_directory:
                size = int(getattr(index_entry, "size", 0) or 0) if index_entry else None
                size_status = "stale" if index_stale else ("ready" if index_entry else "pending")
                file_count = int(getattr(index_entry, "file_count", 0) or 0) if index_entry else None
                folder_count = None
            else:
                size = int(getattr(stat_result, "st_size", item.get("_stat_size") or 0) or 0)
                size_status = "stale" if index_stale else "ready"
                file_count = 1
                folder_count = 0
            item["rjcode"] = item.get("rjcode") or (getattr(index_entry, "rjcode", None) if index_entry else None)
            item["size"] = size
            item["size_status"] = size_status
            item["file_count"] = file_count
            item["folder_count"] = folder_count
            item["size_via_index"] = bool(is_directory and index_entry)
            item["index_refresh_pending"] = bool(index_missing or index_stale)
            entries_with_index.append((item, index_entry))
        if repair_paths:
            self._enqueue_index_read_repair_upserts(library, repair_paths)

        page_item_ids = {id(item) for item in page_items}
        if index_service is not None:
            page_entries = [
                (item, index_entry)
                for item, index_entry in entries_with_index
                if id(item) in page_item_ids
            ]
            self._apply_descendant_dir_counts_for_page(
                library,
                index_service,
                page_entries,
                include_folder_count=False,
            )
        for item in page_items:
            item.pop("_sort_time", None)
            item.pop("_stat_size", None)
            item.pop("_stat_mtime_ms", None)
        return {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if target_path == browse_root else os.path.dirname(target_path),
        }

    async def _list_remote_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        page_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

        client = self.get_cached_synology_client(library.synology)
        offset = max(0, (page - 1) * page_size)
        browse_root, target_path = self._resolve_remote_target_path(library, current_path)
        if browse_root in ("", "/") and target_path in ("", "/"):
            data = await client.list_share(offset=offset, limit=page_size, sort_by="name", sort_direction="asc")
            raw_items = data.get("shares") or data.get("files") or []
        else:
            normalized_sort_by = self._normalize_library_sort_by(sort_by)
            normalized_sort_order = self._normalize_library_sort_order(sort_order)
            remote_sort_by = "name" if normalized_sort_by == "name" else "mtime"
            remote_sort_direction = "asc" if normalized_sort_order == "asc" else "desc"
            data = await client.list(target_path, offset=offset, limit=page_size, sort_by=remote_sort_by, sort_direction=remote_sort_direction)
            raw_items = data.get("files") or []
        files = []
        for index, item in enumerate(raw_items, start=offset):
            name = item.get("name") or ""
            if search and search.lower() not in name.lower():
                continue
            additional = item.get("additional", {}) or {}
            timestamp = additional.get("time", {}).get("mtime", int(time.time()))
            files.append(
                {
                    "id": f"{library.id}:{index}",
                    "name": name,
                    "path": item.get("path") or item.get("real_path") or name,
                    "rjcode": self._extract_rjcode(name),
                    "size": additional.get("size"),
                    "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "unzip_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "is_directory": item.get("isdir", True),
                    "library_id": library.id,
                    "library_name": library.name,
                }
            )
        return {
            "files": files,
            "page": page,
            "page_size": page_size,
            "total": data.get("total", len(files)),
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if target_path == browse_root else self._remote_parent_path(target_path),
        }

    async def folder_contents(self, library_id: str, path: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_folder_contents, library, path)
        if library.type == "synology_filestation":
            return await self._remote_folder_contents(library, path)
        raise RuntimeError(f"不支持此库存类型的文件树预览: {library.type}")

    async def _remote_folder_contents(self, library: LibraryDefinition, path: str) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        client = self.get_cached_synology_client(library.synology)
        normalized_path = self._normalize_remote_path(path)
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        if not self._remote_path_is_within_root(normalized_path, browse_root):
            raise PermissionError("只能查看当前库存根目录内的文件夹")
        all_raw = await self._list_remote_directory_recursive(client, normalized_path)
        items: list[dict[str, Any]] = []
        item_id = 0
        prefix = normalized_path.rstrip("/") + "/"
        for raw in all_raw:
            if raw.get("isdir", False):
                continue
            name = raw.get("name") or ""
            if name.startswith("."):
                continue
            item_path = self._normalize_remote_path(raw.get("path") or raw.get("real_path") or name)
            if item_path.startswith(prefix):
                relative_path = item_path[len(prefix):]
            else:
                relative_path = name
            additional = raw.get("additional") or {}
            size = additional.get("size") or raw.get("size") or 0
            mtime = (additional.get("time") or {}).get("mtime") or 0
            items.append({
                "id": f"{library.id}:content:{item_id}",
                "name": name,
                "path": item_path,
                "relative_path": relative_path,
                "size": int(size),
                "modified_time": datetime.fromtimestamp(mtime).isoformat() if mtime else None,
            })
            item_id += 1
        items.sort(key=lambda x: x["relative_path"])
        folder_name = PurePosixPath(normalized_path).name
        return {
            "folder_name": folder_name,
            "folder_path": normalized_path,
            "total_files": len(items),
            "items": items,
        }

    def _local_folder_contents(self, library: LibraryDefinition, path: str) -> dict[str, Any]:
        library_root = os.path.abspath(library.root_path)
        target_path = os.path.abspath(path)
        if not self._local_path_is_within_root(target_path, library_root):
            raise PermissionError("只能查看当前库存根目录内的文件夹")
        if not os.path.isdir(target_path):
            raise FileNotFoundError("目标文件夹不存在")

        items = []
        item_id = 0
        for root, _, filenames in os.walk(target_path):
            for filename in filenames:
                if filename.startswith("."):
                    continue
                file_path = os.path.join(root, filename)
                stat = os.stat(file_path)
                relative_path = os.path.relpath(file_path, target_path).replace("\\", "/")
                items.append(
                    {
                        "id": f"{library.id}:content:{item_id}",
                        "name": filename,
                        "path": file_path,
                        "relative_path": relative_path,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
                item_id += 1
        items.sort(key=lambda item: item["relative_path"])
        result = {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "total_files": len(items),
            "items": items,
        }
        self._append_stats_log(library, "INFO", f"文件树读取 path={target_path} total={len(items)}")
        return result

    async def _wait_remote_search_ready(
        self,
        client: SynologyFileStationClient,
        task_id: str,
        *,
        timeout_seconds: float = 30.0,
        initial_delay: float = 0.15,
        max_delay: float = 3.0,
    ) -> dict[str, Any]:
        """轮询 search_status 直到搜索完成或超时，使用指数退避。"""
        start_time = time.monotonic()
        deadline = start_time + timeout_seconds
        delay = initial_delay
        poll_count = 0
        last_probe: dict[str, Any] = {}

        logger.debug(
            "远程搜索开始轮询等待: task_id=%s timeout=%.1fs",
            task_id,
            timeout_seconds,
        )

        while True:
            await asyncio.sleep(delay)
            poll_count += 1
            elapsed = time.monotonic() - start_time

            try:
                probe = await client.list_search(
                    task_id, offset=0, limit=1,
                    sort_by="name", sort_direction="asc",
                )
                last_probe = probe or {}
                finished = last_probe.get("finished", False)
                probe_total = int(last_probe.get("total", 0) or 0)
                logger.debug(
                    "远程搜索状态轮询: task_id=%s poll=%d elapsed=%.1fs finished=%s total=%d",
                    task_id,
                    poll_count,
                    elapsed,
                    finished,
                    probe_total,
                )
                if finished:
                    return last_probe
            except Exception:
                logger.warning(
                    "远程搜索轮询查询失败: task_id=%s poll=%d",
                    task_id,
                    poll_count,
                    exc_info=True,
                )

            if time.monotonic() >= deadline:
                logger.warning(
                    "远程搜索等待超时: task_id=%s timeout=%.1fs polls=%d",
                    task_id,
                    timeout_seconds,
                    poll_count,
                )
                return last_probe

            delay = min(delay * 2, max_delay)

    def _build_remote_search_entry(
        self,
        library: LibraryDefinition,
        *,
        item_id: int,
        search_root: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        name = item.get("name") or ""
        path = self._normalize_remote_path(item.get("path") or item.get("real_path") or name)
        relative_path = str(PurePosixPath(path).relative_to(PurePosixPath(search_root))).replace("\\", "/") if path.startswith(search_root.rstrip("/") + "/") or path == search_root else name
        additional = item.get("additional", {}) or {}
        timestamp = additional.get("time", {}).get("mtime", int(time.time()))
        is_directory = bool(item.get("isdir", False))
        return {
            "id": f"{library.id}:search:{item_id}",
            "name": name,
            "path": path,
            "relative_path": relative_path,
            "parent_path": str(PurePosixPath(path).parent) if path != "/" else "/",
            "rjcode": self._extract_rjcode(relative_path) or self._extract_rjcode(name),
            "size": None if is_directory else int(additional.get("size") or 0),
            "size_status": "disabled" if is_directory else "ready",
            "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
            "unzip_time": datetime.fromtimestamp(timestamp).isoformat(),
            "is_directory": is_directory,
            "library_id": library.id,
            "library_name": library.name,
            "search_hit": True,
            "_mtime": timestamp,
        }

    async def _resolve_remote_search_scopes(
        self,
        client: SynologyFileStationClient,
        search_root: str,
    ) -> list[str]:
        normalized_root = self._normalize_remote_path(search_root)
        if normalized_root != "/":
            return [normalized_root]

        # 命中 share 列表缓存（多 RJ 并发时不必重复打 list_share）
        cached_shares = self._get_cached_share_list(client)
        if cached_shares is not None:
            return cached_shares or [normalized_root]

        scopes: list[str] = []
        seen_paths: set[str] = set()
        offset = 0
        limit = 200
        while True:
            data = await client.list_share(offset=offset, limit=limit, sort_by="name", sort_direction="asc")
            raw_items = data.get("shares") or data.get("files") or []
            for item in raw_items:
                raw_path = item.get("path") or item.get("real_path") or item.get("name") or ""
                normalized_path = self._normalize_remote_path(raw_path)
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)
                scopes.append(normalized_path)
            total = int(data.get("total", len(raw_items)) or len(raw_items))
            offset += len(raw_items)
            if not raw_items or offset >= total:
                break
        self._set_cached_share_list(client, scopes)
        return scopes or [normalized_root]

    async def _run_remote_search_scope(
        self,
        client: SynologyFileStationClient,
        *,
        library_id: str,
        scope_path: str,
        keyword: str,
        page_size: int,
        sort_by: str,
        sort_direction: str,
        max_warmup_retries: int = 3,
    ) -> tuple[list[dict[str, Any]], int]:
        request_key = (
            library_id,
            self._normalize_remote_path(scope_path),
            str(keyword or "").strip(),
            min(max(page_size, 200), LIBRARY_SEARCH_RESULT_LIMIT),
            sort_by,
            sort_direction,
            max(1, int(max_warmup_retries or 1)),
        )
        existing_task = self._remote_search_tasks.get(request_key)
        if existing_task and not existing_task.done():
            logger.debug(
                "远程搜索复用进行中的请求: library=%s scope=%s keyword=%s",
                library_id,
                scope_path,
                keyword,
            )
            return await existing_task

        async def _execute_search() -> tuple[list[dict[str, Any]], int]:
            request_limit = request_key[3]
            max_warmup_retries = request_key[6]
            retry_delay = 2.0
            attempt = 0
            consecutive_start_errors = 0

            while attempt < max_warmup_retries:
                attempt += 1
                task_id = None
                attempt_start = time.time()
                try:
                    logger.debug(
                        "远程搜索开始: scope=%s keyword=%s recursive=%s attempt=%d/%d",
                        scope_path,
                        keyword,
                        True,
                        attempt,
                        max_warmup_retries,
                    )
                    started = await client.start_search(scope_path, keyword, recursive=True)
                    task_id = started.get("taskid") or started.get("task_id")
                    if not task_id:
                        raise RuntimeError("群晖搜索接口未返回 taskid")
                    consecutive_start_errors = 0
                    logger.debug(
                        "远程搜索任务已创建: scope=%s keyword=%s task_id=%s attempt=%d/%d",
                        scope_path,
                        keyword,
                        task_id,
                        attempt,
                        max_warmup_retries,
                    )
                    await self._wait_remote_search_ready(
                        client,
                        task_id,
                        timeout_seconds=self._remote_search_timeout_seconds(),
                    )

                    offset = 0
                    total = 0
                    raw_items: list[dict[str, Any]] = []
                    while offset < LIBRARY_SEARCH_RESULT_LIMIT:
                        data = await client.list_search(
                            task_id,
                            offset=offset,
                            limit=request_limit,
                            sort_by=sort_by,
                            sort_direction=sort_direction,
                        )
                        page_items = data.get("files") or data.get("items") or []
                        page_total = int(data.get("total", len(page_items)) or len(page_items))
                        if page_total > total:
                            total = page_total
                        raw_items.extend(page_items)
                        offset += len(page_items)
                        if not page_items or offset >= page_total:
                            break
                    attempt_seconds = max(0.0, time.time() - attempt_start)
                    logger.debug(
                        "远程搜索结果: scope=%s keyword=%s task_id=%s attempt=%d/%d attempt_time=%.1fs raw_items=%s total=%s",
                        scope_path,
                        keyword,
                        task_id,
                        attempt,
                        max_warmup_retries,
                        attempt_seconds,
                        len(raw_items),
                        total,
                    )
                    if raw_items or total:
                        return raw_items[:LIBRARY_SEARCH_RESULT_LIMIT], total

                    if attempt_seconds >= 3.0:
                        logger.debug(
                            "远程搜索耗时%.1fs仍无结果，判定为真空: scope=%s keyword=%s",
                            attempt_seconds,
                            scope_path,
                            keyword,
                        )
                        return [], 0

                    if attempt < max_warmup_retries:
                        logger.debug(
                            "远程 FileStation 搜索秒回空结果，%.1fs后重试: scope=%s keyword=%s attempt=%d/%d",
                            retry_delay,
                            scope_path,
                            keyword,
                            attempt,
                            max_warmup_retries,
                        )
                except Exception as exc:
                    consecutive_start_errors += 1
                    logger.warning(
                        "远程搜索异常: scope=%s keyword=%s attempt=%d/%d consecutive_errors=%d",
                        scope_path,
                        keyword,
                        attempt,
                        max_warmup_retries,
                        consecutive_start_errors,
                        exc_info=True,
                    )
                    if consecutive_start_errors >= 2:
                        logger.warning(
                            "远程搜索连续%d次异常，放弃: scope=%s keyword=%s",
                            consecutive_start_errors,
                            scope_path,
                            keyword,
                        )
                        return [], 0
                finally:
                    if task_id:
                        try:
                            await client.stop_search(task_id)
                        except Exception:
                            logger.debug("停止群晖搜索任务失败: %s", task_id, exc_info=True)

                if attempt < max_warmup_retries:
                    await asyncio.sleep(retry_delay)

            return [], 0

        search_task = asyncio.create_task(_execute_search())
        self._remote_search_tasks[request_key] = search_task
        try:
            return await search_task
        finally:
            current_task = self._remote_search_tasks.get(request_key)
            if current_task is search_task:
                self._remote_search_tasks.pop(request_key, None)

    async def _search_remote_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        *,
        force_refresh: bool = False,
        search_exact: bool = False,
        search_result_kind: str = "all",
        remote_warmup_retries: int = 3,
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

        search_started = time.monotonic()
        client = self.get_cached_synology_client(library.synology)
        cache_key = self._build_remote_search_cache_key(
            library_id=library.id,
            current_path=current_path,
            keyword=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
        )
        cached_result = self._get_cached_remote_search_result(cache_key, force_refresh=force_refresh)
        if cached_result is not None:
            logger.info(
                "远程库存搜索摘要: library=%s keyword=%s cache=hit total=%s returned=%s scopes=0 elapsed=%.0fms",
                library.id,
                str(search or "").strip(),
                int(cached_result.get("total", 0) or 0),
                len(cached_result.get("files") or []),
                (time.monotonic() - search_started) * 1000,
            )
            return cached_result
        browse_root, search_root = self._resolve_remote_target_path(library, current_path)
        keyword = str(search or "").strip()
        rj_only_search = self._is_rj_search_keyword(keyword)
        api_search_root = browse_root if keyword else search_root
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        indexed_result = self._search_files_via_index(
            library,
            keyword=keyword,
            search_root=search_root,
            browse_root=browse_root,
            sort_by=normalized_sort_by,
            sort_order=normalized_sort_order,
            page=page,
            page_size=page_size,
            search_exact=search_exact,
            search_result_kind=search_result_kind,
        )
        if indexed_result is not None:
            logger.info(
                "库存搜索命中索引: library=%s keyword=%s total=%s returned=%s elapsed=%.0fms",
                library.id,
                keyword,
                int(indexed_result.get("total", 0) or 0),
                len(indexed_result.get("files") or []),
                (time.monotonic() - search_started) * 1000,
            )
            return self._set_cached_remote_search_result(cache_key, indexed_result)

        remote_sort_by = "name" if normalized_sort_by == "name" else "mtime"
        remote_sort_direction = "asc" if normalized_sort_order == "asc" else "desc"
        search_scopes = await self._resolve_remote_search_scopes(client, api_search_root)
        logger.debug(
            "远程库存搜索: library=%s browse_root=%s search_root=%s api_search_root=%s keyword=%s scopes=%s",
            library.id,
            browse_root,
            search_root,
            api_search_root,
            keyword,
            search_scopes,
        )
        collected_raw_items: list[dict[str, Any]] = []
        total = 0
        search_scope_count = 0
        if rj_only_search and len(search_scopes) > 1:
            scope_tasks: dict[asyncio.Task, str] = {
                asyncio.create_task(
                    self._run_remote_search_scope(
                        client,
                        library_id=library.id,
                        scope_path=scope_path,
                        keyword=keyword,
                        page_size=page_size,
                        sort_by=remote_sort_by,
                        sort_direction=remote_sort_direction,
                        max_warmup_retries=remote_warmup_retries,
                    )
                ): scope_path
                for scope_path in search_scopes
            }
            try:
                pending = set(scope_tasks.keys())
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    search_scope_count += len(done)
                    for task in done:
                        raw_items, scope_total = await task
                        total += scope_total
                        collected_raw_items.extend(raw_items)
                        if raw_items or scope_total:
                            logger.debug(
                                "远程 RJ 搜索提前命中: library=%s keyword=%s scope=%s raw_items=%s total=%s",
                                library.id,
                                keyword,
                                scope_tasks[task],
                                len(raw_items),
                                scope_total,
                            )
                            for pending_task in pending:
                                pending_task.cancel()
                            pending.clear()
                            break
            finally:
                for task in scope_tasks:
                    if not task.done():
                        task.cancel()
        else:
            for scope_path in search_scopes:
                raw_items, scope_total = await self._run_remote_search_scope(
                    client,
                    library_id=library.id,
                    scope_path=scope_path,
                    keyword=keyword,
                    page_size=page_size,
                    sort_by=remote_sort_by,
                    sort_direction=remote_sort_direction,
                    max_warmup_retries=remote_warmup_retries,
                )
                search_scope_count += 1
                total += scope_total
                collected_raw_items.extend(raw_items)

        files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        remote_stat_cache: dict[str, dict[str, Any]] = {}

        # 第一遍：过滤并收集需要 stat() 的唯一 RJ 目录路径（不发任何请求）
        pre_filtered: list[tuple[int, dict, str, str | None]] = []
        paths_needing_stat: set[str] = set()
        for index, item in enumerate(collected_raw_items):
            item_name = item.get("name") or ""
            if self._should_skip_entry(item_name):
                continue
            target_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or item_name)
            if not self._remote_path_is_within_root(target_path, browse_root):
                continue
            rj_dir_path: str | None = None
            if rj_only_search and self._normalize_search_result_kind(search_result_kind) != "file":
                nearest_rj_dir = self._find_nearest_remote_rj_directory(target_path, browse_root)
                if not nearest_rj_dir:
                    continue
                if not self._remote_path_is_within_root(nearest_rj_dir, browse_root):
                    continue
                rj_dir_path = nearest_rj_dir
                if nearest_rj_dir not in remote_stat_cache:
                    paths_needing_stat.add(nearest_rj_dir)
            pre_filtered.append((index, item, target_path, rj_dir_path))

        # 第二遍：批量并发 stat()（最多 5 路），把结果写入 remote_stat_cache
        if paths_needing_stat:
            _stat_sem = asyncio.Semaphore(5)

            async def _fetch_stat(path: str):
                async with _stat_sem:
                    try:
                        info = await client.stat(path)
                        return path, self._first_remote_info_item(info) or {
                            "name": PurePosixPath(path).name,
                            "path": path,
                            "real_path": path,
                            "isdir": True,
                            "additional": {},
                        }
                    except Exception as exc:
                        logger.debug("stat 查询失败，使用默认信息: path=%s error=%s", path, exc)
                        return path, {
                            "name": PurePosixPath(path).name,
                            "path": path,
                            "real_path": path,
                            "isdir": True,
                            "additional": {},
                        }

            _stat_results = await asyncio.gather(
                *[_fetch_stat(p) for p in paths_needing_stat],
                return_exceptions=True,
            )
            for _res in _stat_results:
                if isinstance(_res, tuple):
                    _path, _info = _res
                    remote_stat_cache[_path] = _info

        # 第三遍：用缓存的 stat 结果构建最终文件列表
        for index, item, target_path, rj_dir_path in pre_filtered:
            if rj_dir_path is not None:
                target_path = rj_dir_path
                target_item = remote_stat_cache.get(rj_dir_path) or {
                    "name": PurePosixPath(rj_dir_path).name,
                    "path": rj_dir_path,
                    "real_path": rj_dir_path,
                    "isdir": True,
                    "additional": {},
                }
            else:
                target_item = item

            normalized_target_path = self._normalize_remote_path(target_path)
            if normalized_target_path in seen_paths:
                continue
            entry = self._build_remote_search_entry(
                library,
                item_id=index,
                search_root=browse_root,
                item=target_item,
            )
            if not self._search_match_text(
                keyword,
                entry.get("name"),
                entry.get("relative_path"),
                entry.get("rjcode"),
                exact=search_exact,
            ):
                continue
            if not self._matches_search_result_kind(bool(entry.get("is_directory")), search_result_kind):
                continue
            seen_paths.add(normalized_target_path)
            files.append(entry)

        files = self._sort_remote_page_items(files, normalized_sort_by, normalized_sort_order)
        deduped_total = len(files)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = files[start:end]
        for item in page_items:
            item.pop("_mtime", None)
        result = {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": deduped_total,
            "current_path": search_root,
            "browse_root_path": browse_root,
            "parent_path": None if search_root == browse_root else self._remote_parent_path(search_root),
            "search_mode": True,
            "search_root_path": search_root,
            "search_query": keyword,
            "search_truncated": deduped_total >= LIBRARY_SEARCH_RESULT_LIMIT,
            "search_scope_count": search_scope_count,
            "search_exact": bool(search_exact),
            "search_result_kind": self._normalize_search_result_kind(search_result_kind),
        }
        logger.info(
            "远程库存搜索摘要: library=%s keyword=%s cache=miss scopes=%s attempts=%s elapsed=%.0fms raw_total=%s total=%s returned=%s",
            library.id,
            keyword,
            len(search_scopes),
            max(1, int(remote_warmup_retries or 1)),
            (time.monotonic() - search_started) * 1000,
            total,
            deduped_total,
            len(page_items),
        )
        return self._set_cached_remote_search_result(cache_key, result)

    def resolve_create_folder_target(
        self,
        library_id: str,
        parent_path: Optional[str],
        name: str,
    ) -> tuple[LibraryDefinition, str, str, str]:
        """解析库存新建目录目标，并保证目标只能落在当前 browse root 内。"""
        library = self.get_library_definition(library_id)
        if not library.writable:
            raise PermissionError("当前库存为只读，不能新建文件夹")

        safe_name = self._validate_remote_new_name(name)
        if library.type == "local":
            browse_root = os.path.abspath(library.browse_root_path or library.root_path)
            raw_parent = str(parent_path or "").strip()
            resolved_parent = (
                os.path.abspath(raw_parent)
                if raw_parent and os.path.isabs(raw_parent)
                else os.path.abspath(os.path.join(browse_root, raw_parent))
            )
            if not self._local_path_is_within_root(resolved_parent, browse_root):
                raise PermissionError("新建文件夹失败：目标路径超出当前库存浏览根目录")
            target_path = os.path.abspath(os.path.join(resolved_parent, safe_name))
            if not self._local_path_is_within_root(target_path, browse_root):
                raise PermissionError("新建文件夹失败：目标路径超出当前库存浏览根目录")
            return library, resolved_parent, target_path, safe_name

        _, resolved_parent = self._resolve_remote_operation_path(
            library,
            parent_path,
            action="新建文件夹",
            new_name=safe_name,
        )
        target_path = self._normalize_remote_path(
            str(PurePosixPath(resolved_parent) / safe_name)
        )
        return library, resolved_parent, target_path, safe_name

    async def create_folder(
        self,
        library_id: str,
        parent_path: Optional[str],
        name: str,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        library, resolved_parent, target_path, safe_name = self.resolve_create_folder_target(
            library_id,
            parent_path,
            name,
        )
        if library.type == "local":
            def _create_local_folder() -> None:
                if not os.path.isdir(resolved_parent):
                    raise FileNotFoundError("当前目录不存在或已被移动")
                if os.path.exists(target_path):
                    raise FileExistsError("同名文件或文件夹已存在")
                os.mkdir(target_path)

            await asyncio.to_thread(_create_local_folder)
            self._invalidate_local_browse_caches(library.id)
            if not skip_index_mutation:
                self._notify_index_self_mutation_upsert_subtree(library, target_path)
        else:
            client = self.get_cached_synology_client(library.synology)
            if await self._remote_path_exists(client, target_path):
                raise FileExistsError("同名文件或文件夹已存在")
            try:
                await client.create_folder(resolved_parent, safe_name)
            except Exception as exc:
                if client._is_error_code(exc, 117) or client._is_error_code(exc, 414):
                    raise FileExistsError("同名文件或文件夹已存在") from exc
                raise

        self._append_stats_log(library, "INFO", f"新建文件夹 path={target_path}")
        return {
            "message": "文件夹创建成功",
            "library_id": library.id,
            "library_type": library.type,
            "parent_path": resolved_parent,
            "path": target_path,
            "name": safe_name,
            "is_directory": True,
        }

    async def rename(
        self,
        library_id: str,
        path: str,
        new_name: str,
        *,
        skip_index_mutation: bool = False,
        sync_index_mutation: bool = False,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(
                self._local_rename,
                library,
                path,
                new_name,
                skip_index_mutation=skip_index_mutation,
                sync_index_mutation=sync_index_mutation,
            )
        new_name = self._validate_remote_new_name(new_name)
        _, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="库存重命名",
            new_name=new_name,
        )
        client = self.get_cached_synology_client(library.synology)
        try:
            if not await self._remote_path_exists(client, target_path):
                raise FileNotFoundError("目标路径不存在")
        except FileNotFoundError:
            raise
        except Exception as exc:
            if client._is_error_code(exc, 119):
                await self._raise_remote_code_119_context(
                    client=client,
                    library=library,
                    action="库存重命名预检",
                    incoming_path=path,
                    target_path=target_path,
                    original_error=exc,
                    new_name=new_name,
                )
            raise
        try:
            await self._retry_remote_rename(client, target_path, new_name)
        except Exception as exc:
            if client._is_error_code(exc, 119):
                await self._raise_remote_code_119_context(
                    client=client,
                    library=library,
                    action="库存重命名",
                    incoming_path=path,
                    target_path=target_path,
                    original_error=exc,
                    new_name=new_name,
                )
            raise
        new_path = str(PurePosixPath(target_path).parent / new_name)
        if not skip_index_mutation:
            indexable_moved_items = self._filter_index_move_items(
                library,
                [{"source": target_path, "destination": new_path}],
            )
            if indexable_moved_items:
                self._notify_index_self_mutation_move_batch(
                    library,
                    library,
                    indexable_moved_items,
                    sync=sync_index_mutation,
                )
        self._append_stats_log(library, "INFO", f"重命名 path={target_path} -> {new_name}")
        return {"message": "重命名成功", "new_path": new_path}

    def _local_rename(
        self,
        library: LibraryDefinition,
        path: str,
        new_name: str,
        *,
        skip_index_mutation: bool = False,
        sync_index_mutation: bool = False,
    ) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        parent_dir = os.path.dirname(path)
        new_path = os.path.join(parent_dir, new_name)
        os.rename(path, new_path)
        # 文件夹改名后 keyword→matches 里旧 path 不再有效
        self._invalidate_local_browse_caches(library.id)
        if not skip_index_mutation:
            indexable_moved_items = self._filter_index_move_items(
                library,
                [{"source": path, "destination": new_path}],
            )
            if indexable_moved_items:
                self._notify_index_self_mutation_move_batch(
                    library,
                    library,
                    indexable_moved_items,
                    sync=sync_index_mutation,
                )
        self._append_stats_log(library, "INFO", f"重命名 path={path} -> {new_name}")
        return {"message": "重命名成功", "new_path": new_path}

    async def batch_rename(
        self,
        library_id: str,
        items: list[dict[str, str]],
        *,
        skip_index_mutation: bool = False,
        sync_index_mutation: bool = False,
    ) -> dict[str, Any]:
        """批量重命名。

        ★ 性能修复（修复用户痛点：字幕工作台应用配对 30 次串行 HTTP 慢到几十秒）：
        每次单条 ``rename`` API 都要：
        1. 1 次 HTTP 往返（前端 → 后端）
        2. 1 次 SQLAlchemy session 创建 / 索引 DELETE / commit / close
        3. 1 次清搜索缓存
        4. 1 次 stats_log 写文件
        N 条 = N 倍开销，单条 5-30ms 在 N=30 时累积到 1-3 秒；HTTP 往返 N=30 时
        即便受控并发 6 也至少 0.5-1 秒。

        本方法把 N 条 rename 在**一次后端调用**里完成：os.rename 仍然串行（避免
        同目录下并发 rename 触发的 ENOTDIR 等竞争），但**索引同步 / 缓存清理 /
        stats_log 全部聚合**，数据库 commit 从 N 次降到 1 次。

        ``items``: ``[{"path": "...", "new_name": "..."}, ...]``
        返回 ``{"results": [...], "success_count": int, "failed": [...]}``。
        失败项不影响其他项继续处理。
        """
        if not items:
            return {"success_count": 0, "results": [], "failed": []}
        library = self.get_library_definition(library_id)
        if library.type != "local":
            # 远程库存（群晖 FileStation）走单条 rename 路径，远程 API 没有原生批接口；
            # 但仍然把索引同步聚合成 1 次。这种场景较少见，先简单循环 + 集中 sync。
            return await self._batch_rename_remote_collected(
                library,
                items,
                skip_index_mutation=skip_index_mutation,
                sync_index_mutation=sync_index_mutation,
            )
        return await asyncio.to_thread(
            self._local_batch_rename,
            library,
            items,
            skip_index_mutation=skip_index_mutation,
            sync_index_mutation=sync_index_mutation,
        )

    def _local_batch_rename(
        self,
        library: LibraryDefinition,
        items: list[dict[str, str]],
        *,
        skip_index_mutation: bool = False,
        sync_index_mutation: bool = False,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        success_count = 0
        moved_index_items: list[dict[str, str]] = []
        log_lines: list[str] = []
        path_replacements: list[dict[str, str]] = []

        def remap_path(raw_path: str) -> str:
            current = str(raw_path or "").replace("\\", "/").rstrip("/")
            for replacement in path_replacements:
                old_path = str(replacement.get("old_path") or "").replace("\\", "/").rstrip("/")
                new_path = str(replacement.get("new_path") or "").replace("\\", "/").rstrip("/")
                if not old_path or not new_path:
                    continue
                if current == old_path:
                    current = new_path
                    continue
                if current.startswith(f"{old_path}/"):
                    current = f"{new_path}{current[len(old_path):]}"
            return current

        for index, raw in enumerate(items):
            try:
                request_index = int((raw or {}).get("index"))
            except (TypeError, ValueError):
                request_index = index
            source_path = str((raw or {}).get("path") or "").strip()
            path = remap_path(source_path)
            new_name = str((raw or {}).get("new_name") or "").strip()
            if not path or not new_name:
                failed.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name, "error": "缺少路径或新名"})
                continue
            try:
                self._assert_local_path_in_library(library, path)
                parent_dir = os.path.dirname(path)
                new_path = os.path.join(parent_dir, new_name)
                os.rename(path, new_path)
                results.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name, "new_path": new_path})
                success_count += 1
                moved_index_items.append({"source": path, "destination": new_path})
                if new_path and new_path != path:
                    path_replacements.append({"old_path": path, "new_path": new_path})
                log_lines.append(f"重命名 path={path} -> {new_name}")
            except Exception as exc:
                failed.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name, "error": str(exc)})

        # 一次性清浏览缓存（关键：从 N 次降到 1 次）
        if success_count:
            self._invalidate_local_browse_caches(library.id)

        # 一次性索引移动通知：后台 micro-batch，命中索引 fast-path 时不扫磁盘。
        # 字幕补配工作台的临时字幕路径会被过滤；真实 RJ 音频改名必须继续同步索引。
        if moved_index_items and not skip_index_mutation:
            indexable_moved_items = self._filter_index_move_items(library, moved_index_items)
            if indexable_moved_items:
                self._notify_index_self_mutation_move_batch(
                    library,
                    library,
                    indexable_moved_items,
                    sync=sync_index_mutation,
                )

        # 聚合 stats_log（合并成 1 次 open / write，原本 N 次）
        if log_lines:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                stats_path = _stats_log_file_path()
                payload = "".join(
                    f"[{timestamp}] [INFO] [{library.id}] [{library.name}] {line}\n"
                    for line in log_lines
                )
                payload += (
                    f"[{timestamp}] [INFO] [{library.id}] [{library.name}] "
                    f"批量重命名完成 success={success_count} failed={len(failed)} total={len(items)}\n"
                )
                with open(stats_path, "a", encoding="utf-8") as handle:
                    handle.write(payload)
            except Exception:
                logger.debug("[批量重命名] stats_log 写入失败", exc_info=True)

        return {
            "success_count": success_count,
            "results": results,
            "failed": failed,
        }

    async def _batch_rename_remote_collected(
        self,
        library: "LibraryDefinition",
        items: list[dict[str, str]],
        *,
        skip_index_mutation: bool = False,
        sync_index_mutation: bool = False,
    ) -> dict[str, Any]:
        """远程库批量重命名：单条 rename 走原 FileStation API。"""
        results: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        success_count = 0
        moved_index_items: list[dict[str, str]] = []
        path_replacements: list[dict[str, str]] = []

        def remap_path(raw_path: str) -> str:
            current = str(raw_path or "").replace("\\", "/").rstrip("/")
            for replacement in path_replacements:
                old_path = str(replacement.get("old_path") or "").replace("\\", "/").rstrip("/")
                new_path = str(replacement.get("new_path") or "").replace("\\", "/").rstrip("/")
                if not old_path or not new_path:
                    continue
                if current == old_path:
                    current = new_path
                    continue
                if current.startswith(f"{old_path}/"):
                    current = f"{new_path}{current[len(old_path):]}"
            return current

        client = self.get_cached_synology_client(library.synology)
        for index, raw in enumerate(items):
            try:
                request_index = int((raw or {}).get("index"))
            except (TypeError, ValueError):
                request_index = index
            source_path = str((raw or {}).get("path") or "").strip()
            path = remap_path(source_path)
            new_name = str((raw or {}).get("new_name") or "").strip()
            if not path or not new_name:
                failed.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name, "error": "缺少路径或新名"})
                continue
            try:
                new_name_safe = self._validate_remote_new_name(new_name)
                _, target_path = self._resolve_remote_operation_path(
                    library, path, action="批量库存重命名", new_name=new_name_safe,
                )
                await self._retry_remote_rename(client, target_path, new_name_safe)
                new_path = str(PurePosixPath(target_path).parent / new_name_safe)
                results.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name_safe, "new_path": new_path})
                success_count += 1
                moved_index_items.append({"source": target_path, "destination": new_path})
                if new_path and new_path != target_path:
                    path_replacements.append({"old_path": target_path, "new_path": new_path})
            except Exception as exc:
                failed.append({"index": request_index, "path": path, "source_path": source_path, "new_name": new_name, "error": str(exc)})

        if moved_index_items and not skip_index_mutation:
            indexable_moved_items = self._filter_index_move_items(library, moved_index_items)
            if indexable_moved_items:
                self._notify_index_self_mutation_move_batch(
                    library,
                    library,
                    indexable_moved_items,
                    sync=sync_index_mutation,
                )
        self._append_stats_log(
            library, "INFO",
            f"远程批量重命名完成 success={success_count} failed={len(failed)} total={len(items)}",
        )
        return {"success_count": success_count, "results": results, "failed": failed}

    def _local_delete(
        self,
        library: LibraryDefinition,
        path: str,
        confirmed: bool,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        if not confirmed:
            indexed_preview = self._delete_preview_via_index(library, path)
            if indexed_preview is not None:
                self._append_stats_log(
                    library,
                    "INFO",
                    f"删除预检读取索引 path={path} type={indexed_preview.get('type')} size={indexed_preview.get('size')}",
                )
                return indexed_preview
            preview = self._local_delete_preview_from_filesystem(path)
            self._append_stats_log(
                library,
                "INFO",
                f"删除预检读取本地文件系统 path={path} type={preview.get('type')} size={preview.get('size')}",
            )
            return preview

        was_top_level_dir = os.path.isdir(path)
        if was_top_level_dir:
            _robust_rmtree(path)
        else:
            os.remove(path)
        self._invalidate_local_browse_caches(library.id)
        if was_top_level_dir:
            self._local_top_level_delta(library, path, -1)
        # 索引同步：删除完成后立即同步索引（不依赖 watcher）
        if not skip_index_mutation:
            self._notify_index_self_mutation_delete(
                library,
                path,
                sync=True,
                scope="subtree" if was_top_level_dir else "exact",
            )
        self._append_stats_log(library, "INFO", f"删除完成 path={path}")
        return {"message": "删除成功", "path": path}

    async def batch_delete(
        self,
        library_id: str,
        paths: list[str],
        confirmed: bool = False,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type != "local":
            raise RuntimeError("当前远程库不支持这里的批量删除")
        return await asyncio.to_thread(
            self._local_batch_delete,
            library,
            paths,
            confirmed,
            skip_index_mutation=skip_index_mutation,
        )

    def _local_batch_delete(
        self,
        library: LibraryDefinition,
        paths: list[str],
        confirmed: bool,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        for path in paths:
            self._assert_local_path_in_library(library, path)
        if not confirmed:
            indexed_preview = self._batch_delete_preview_via_index(library, paths)
            if indexed_preview is not None:
                self._append_stats_log(
                    library,
                    "INFO",
                    f"批删预检读取索引 total={len(paths)} size={indexed_preview.get('total_size')}",
                )
                return indexed_preview
            previews = [self._local_delete_preview_from_filesystem(path) for path in paths]
            roots: list[dict[str, Any]] = []
            root_paths: list[str] = []
            for preview in sorted(previews, key=lambda item: len(str(item.get("path") or ""))):
                normalized_path = os.path.normcase(os.path.abspath(str(preview.get("path") or ""))).rstrip("\\/")
                if any(
                    normalized_path == root
                    or normalized_path.startswith(root.rstrip("\\/") + os.sep)
                    for root in root_paths
                ):
                    continue
                root_paths.append(normalized_path)
                roots.append(preview)
            total_size = sum(int(item.get("size") or 0) for item in roots)
            self._append_stats_log(library, "INFO", f"批删预检读取本地文件系统 total={len(paths)} size={total_size}")
            return {
                "need_confirm": True,
                "total_count": len(paths),
                "total_size": total_size,
                "total_file_count": sum(int(item.get("file_count") or 0) for item in roots),
                "total_folder_count": sum(int(item.get("folder_count") or 0) for item in roots),
                "size_disabled": False,
                "browse_via_index": False,
            }
        success_count = 0
        failed_paths: list[dict[str, str]] = []
        successful_paths: list[str] = []
        successful_scopes: dict[str, str] = {}
        for path in paths:
            try:
                was_top_level_dir = os.path.isdir(path)
                if was_top_level_dir:
                    _robust_rmtree(path)
                else:
                    os.remove(path)
                if was_top_level_dir:
                    self._local_top_level_delta(library, path, -1)
                success_count += 1
                successful_paths.append(path)
                successful_scopes[os.path.normcase(os.path.abspath(path))] = (
                    "subtree" if was_top_level_dir else "exact"
                )
            except Exception as exc:
                failed_paths.append({"path": path, "error": str(exc)})
        if successful_paths:
            self._invalidate_local_browse_caches(library.id)
        # 索引同步：批量通知删除（单事务一次提交）
        if not skip_index_mutation:
            self._notify_index_self_mutation_delete_batch(
                library,
                successful_paths,
                sync=True,
                scopes_by_path=successful_scopes,
            )
        self._append_stats_log(
            library,
            "INFO",
            f"批删完成 success={success_count} failed={len(failed_paths)} total={len(paths)}",
        )
        return {"message": "批量删除完成", "success_count": success_count, "failed_paths": failed_paths}

    # ---------------------- 本地库浏览 / 批量移动（移动对话框专用） ----------------------
    async def list_local_folders_only(
        self,
        library_id: str,
        path: Optional[str] = None,
        *,
        compute_size: bool = False,
        compute_size_cap: int = 256,
        include_files: bool = False,
    ) -> dict[str, Any]:
        """轻量浏览：返回当前目录下的子目录（可选地也返回文件）。

        给"移动到..."对话框使用，避免触碰慢速 size 计算路径。

        - 默认仅读 size 缓存，不主动递归计算大小。
        - 当 ``compute_size=True`` 且当前路径不是浏览根（社团目录之类的层级）时，
          允许按需计算未命中缓存的子目录大小，单次最多计算 ``compute_size_cap`` 个，
          其余保持 ``size_status='pending'``，下次浏览再补。
        - 当 ``include_files=True`` 时，文件也作为返回项加入 ``folders`` 数组，
          每项带 ``is_directory`` 字段区分；文件大小从 stat 取，不走递归缓存。

        远程（synology_filestation）库：忽略 ``compute_size`` / ``compute_size_cap``，
        目录统一返回 ``size=None, size_status="disabled"``；走 FileStation 单层 list，
        ``include_files`` 同样生效（文件项 size 取自 additional.size）。
        """
        library = self.get_library_definition(library_id)
        indexed = self._list_folders_only_via_index(library, path, include_files=include_files)
        if indexed is not None:
            self._append_stats_log(
                library,
                "INFO",
                f"目录浏览读取索引 path={indexed.get('current_path')} total={len(indexed.get('folders') or [])}",
            )
            return indexed
        if library.type == "local":
            return await asyncio.to_thread(
                self._list_local_folders_only,
                library,
                path,
                compute_size,
                compute_size_cap,
                include_files,
            )
        if library.type == "synology_filestation":
            return await self._list_remote_folders_only(
                library,
                path,
                include_files=include_files,
            )
        raise RuntimeError(f"不支持此库存类型的目录浏览: {library.type}")

    def navigation_snapshot_via_index(
        self,
        library_id: str,
        path: Optional[str] = None,
        *,
        include_files: bool = True,
        include_ancestors: bool = True,
    ) -> Optional[dict[str, Any]]:
        """移动弹窗专用的纯索引导航快照。

        索引可用时不对目标目录和直接子项执行 ``stat/isdir``。最终移动预检与
        执行仍会检查真实文件系统；这里仅负责快速构建可浏览的目录树读模型。
        Redis 只缓存带 generation/view_revision 的短期快照，不作为事实源。
        """
        library = self.get_library_definition(library_id)
        if library.type != "local":
            return None
        service = self._index_service_if_ready(library)
        if service is None:
            return None
        if hasattr(service, "has_library_entries") and not service.has_library_entries(library.id):
            return None

        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        target_path = os.path.abspath(path) if path else browse_root
        if not self._local_path_is_within_root(target_path, browse_root):
            raise PermissionError("只能浏览当前库存根目录内的文件夹")
        target_relative = self._index_parent_path_for_target(library, target_path)
        if target_relative is None:
            raise PermissionError("只能浏览当前库存根目录内的文件夹")
        browse_relative = self._index_parent_path_for_target(library, browse_root) or ""
        if target_relative:
            target_entry = service.get_entry(library.id, target_relative)
            if not target_entry or target_entry.entry_type != "dir":
                return None

        status = service.get_status(library.id)
        active_generation = int(getattr(status, "active_generation", 1) or 1)
        view_revision = int(getattr(status, "view_revision", 0) or 0)
        materialized_seq = int(getattr(status, "materialized_seq", 0) or 0)
        view_token = f"{library.id}:{active_generation}:{view_revision}"
        cache_identity = hashlib.sha1(
            f"{target_relative}|{int(include_files)}|{int(include_ancestors)}".encode("utf-8")
        ).hexdigest()
        cache_item_id = f"{library.id}-{active_generation}-{view_revision}-{cache_identity}"

        try:
            from .redis_service import get_redis_service

            redis_service = get_redis_service()
            cached = redis_service.get_json("library", "move-nav", cache_item_id)
            if isinstance(cached, dict):
                return {**cached, "cache_source": "redis"}
        except Exception:
            redis_service = None
            logger.debug("读取移动弹窗导航 Redis 缓存失败", exc_info=True)

        relative_parents = [target_relative]
        if include_ancestors:
            relative_parents = [browse_relative]
            cursor = browse_relative
            relative_tail = target_relative[len(browse_relative):].strip("/") if browse_relative else target_relative
            for segment in [part for part in relative_tail.split("/") if part]:
                cursor = f"{cursor}/{segment}".strip("/")
                relative_parents.append(cursor)

        def absolute_parent(relative_parent: str) -> str:
            if not relative_parent:
                return browse_root
            return os.path.abspath(os.path.join(library.root_path, *relative_parent.split("/")))

        def map_entry(entry) -> dict[str, Any]:
            try:
                modified_time = (
                    datetime.fromtimestamp((entry.mtime or 0) / 1000.0).isoformat()
                    if entry.mtime else None
                )
            except (OSError, ValueError, OverflowError):
                modified_time = None
            is_directory = entry.entry_type == "dir"
            return {
                "name": entry.name,
                "path": entry.absolute_path,
                "relative_path": entry.relative_path,
                "is_directory": is_directory,
                "modified_time": modified_time,
                "size": int(entry.size or 0),
                "size_status": "ready",
                "file_count": int(entry.file_count or 0) if is_directory else 1,
                "folder_count": None if is_directory else 0,
                "size_via_index": bool(is_directory),
                "browse_via_index": True,
            }

        tree_children: list[dict[str, Any]] = []
        current_folders: list[dict[str, Any]] = []
        for relative_parent in relative_parents:
            is_current = relative_parent == target_relative
            payload = service.list_children_page(
                library.id,
                relative_parent,
                entry_type=None if (is_current and include_files) else "dir",
                sort_by="name",
                sort_order="asc",
                offset=0,
                limit=None,
            )
            mapped = [
                map_entry(entry)
                for entry in list(payload.get("entries") or [])
                if not self._should_skip_entry(getattr(entry, "name", ""))
            ]
            if is_current:
                current_folders = mapped
            tree_children.append({
                "path": absolute_parent(relative_parent),
                "relative_path": relative_parent,
                "folders": [item for item in mapped if item.get("is_directory")],
            })

        result = {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "library_root_path": library.root_path,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if os.path.normcase(target_path) == os.path.normcase(browse_root) else os.path.dirname(target_path),
            "folders": current_folders,
            "tree_children": tree_children,
            "browse_via_index": True,
            "cache_source": "postgresql",
            "index_view": {
                "library_id": library.id,
                "index_generation": active_generation,
                "accepted_seq": int(getattr(status, "accepted_seq", 0) or 0),
                "materialized_seq": materialized_seq,
                "state_revision": int(getattr(status, "state_revision", 0) or 0),
                "view_revision": view_revision,
                "stats_as_of_seq": materialized_seq,
            },
            "view_token": view_token,
        }
        if redis_service is not None:
            try:
                redis_service.set_json(
                    "library",
                    "move-nav",
                    cache_item_id,
                    result,
                    ttl_seconds=redis_service.short_cache_ttl_seconds(),
                )
            except Exception:
                logger.debug("写入移动弹窗导航 Redis 缓存失败", exc_info=True)
        return result

    def _list_local_folders_only(
        self,
        library: LibraryDefinition,
        path: Optional[str],
        compute_size: bool = False,
        compute_size_cap: int = 256,
        include_files: bool = False,
    ) -> dict[str, Any]:
        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        target_path = os.path.abspath(path) if path else browse_root
        empty_payload = {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "library_root_path": library.root_path,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None,
            "folders": [],
        }
        if not os.path.exists(browse_root):
            empty_payload["current_path"] = browse_root
            return empty_payload
        if not self._local_path_is_within_root(target_path, browse_root):
            target_path = browse_root
            empty_payload["current_path"] = target_path
        if not os.path.isdir(target_path):
            empty_payload["current_path"] = target_path
            return empty_payload

        index_service = self._index_service_for_local_size_overlay(library)
        repair_paths: list[str] = []
        folders: list[dict[str, Any]] = []
        try:
            with os.scandir(target_path) as iterator:
                for entry in iterator:
                    if self._should_skip_entry(entry.name):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if not is_dir and not include_files:
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        mtime_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except OSError:
                        stat = None
                        mtime_iso = ""
                    if is_dir:
                        child_path = os.path.abspath(entry.path)
                        index_entry = None
                        index_missing = False
                        index_stale = False
                        if index_service is not None and stat is not None:
                            index_entry, index_missing, index_stale = self._local_index_entry_for_current_child(
                                library,
                                index_service,
                                absolute_path=child_path,
                                is_directory=True,
                                stat_result=stat,
                            )
                            if index_missing or index_stale:
                                repair_paths.append(child_path)
                        folders.append({
                            "name": entry.name,
                            "path": child_path,
                            "is_directory": True,
                            "modified_time": mtime_iso,
                            "size": int(getattr(index_entry, "size", 0) or 0) if index_entry is not None else None,
                            "size_status": "stale" if index_stale else ("ready" if index_entry is not None else "pending"),
                            "file_count": int(getattr(index_entry, "file_count", 0) or 0) if index_entry is not None else None,
                            "folder_count": None,
                            "folder_count_status": "lazy",
                            "size_via_index": index_entry is not None,
                            "index_refresh_pending": bool(index_missing or index_stale),
                        })
                    else:
                        # 文件大小直接来自 stat，开销可忽略
                        file_size = int(stat.st_size) if stat is not None else 0
                        folders.append({
                            "name": entry.name,
                            "path": os.path.abspath(entry.path),
                            "is_directory": False,
                            "modified_time": mtime_iso,
                            "size": file_size,
                            "size_status": "ready",
                            "file_count": 1,
                            "folder_count": 0,
                        })
        except OSError as exc:
            raise RuntimeError(f"读取目录失败: {exc}") from exc
        if repair_paths:
            self._enqueue_index_read_repair_upserts(library, repair_paths)

        # 排序：目录优先（is_directory=True 排在前），同类按名字字母序
        folders.sort(key=lambda item: (
            0 if item.get("is_directory") else 1,
            (item.get("name") or "").lower(),
        ))
        parent_path = (
            None
            if os.path.normcase(target_path) == os.path.normcase(browse_root)
            else os.path.dirname(target_path)
        )
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "library_root_path": library.root_path,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": parent_path,
            "folders": folders,
        }

    async def _list_remote_folders_only(
        self,
        library: LibraryDefinition,
        path: Optional[str],
        *,
        include_files: bool = False,
    ) -> dict[str, Any]:
        """远程（synology_filestation）版本的轻量浏览。

        - 用 FileStation list 单层枚举，跳过隐藏 / 系统目录（``_should_skip_entry``）。
        - 目录统一不算 size（远程递归计算 size 太贵），``size=None, size_status="disabled"``。
        - 文件项 size 取 ``additional.size``。
        - 路径越界统一抛 PermissionError，由路由层映射为 403。
        """
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

        browse_root, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="浏览远程目录",
        )

        client = self.get_cached_synology_client(library.synology)
        try:
            raw_items = await self._list_remote_directory(client, target_path)
        except Exception as exc:
            logger.warning(
                "浏览远程目录失败: library_id=%s target_path=%s err=%s",
                library.id,
                target_path,
                exc,
                exc_info=True,
            )
            raise

        folders: list[dict[str, Any]] = []
        for item in raw_items:
            name = str(item.get("name") or "")
            if not name or self._should_skip_entry(name):
                continue
            is_dir = bool(item.get("isdir", False))
            if not is_dir and not include_files:
                continue

            child_path = self._normalize_remote_path(
                item.get("path") or item.get("real_path") or name
            )
            additional = item.get("additional") or {}
            time_section = additional.get("time") or {}
            mtime_ts = time_section.get("mtime")
            try:
                mtime_iso = (
                    datetime.fromtimestamp(int(mtime_ts)).isoformat()
                    if mtime_ts is not None
                    else ""
                )
            except (TypeError, ValueError, OSError, OverflowError):
                mtime_iso = ""

            if is_dir:
                folders.append({
                    "name": name,
                    "path": child_path,
                    "is_directory": True,
                    "modified_time": mtime_iso,
                    "size": None,
                    "size_status": "disabled",
                })
            else:
                file_size_raw = additional.get("size")
                try:
                    file_size = int(file_size_raw) if file_size_raw is not None else 0
                except (TypeError, ValueError):
                    file_size = 0
                folders.append({
                    "name": name,
                    "path": child_path,
                    "is_directory": False,
                    "modified_time": mtime_iso,
                    "size": file_size,
                    "size_status": "ready",
                })

        # 与本地版一致：目录在前，文件在后；同类按名字小写字典序
        folders.sort(key=lambda entry: (
            0 if entry.get("is_directory") else 1,
            (entry.get("name") or "").lower(),
        ))

        normalized_target = self._normalize_remote_path(target_path)
        normalized_browse_root = self._normalize_remote_path(browse_root)
        parent_path = (
            None
            if normalized_target == normalized_browse_root
            else self._remote_parent_path(normalized_target)
        )

        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "library_root_path": library.root_path,
            "current_path": normalized_target,
            "browse_root_path": normalized_browse_root,
            "parent_path": parent_path,
            "folders": folders,
        }

    async def move_local_items(
        self,
        *,
        source_library_id: str,
        target_library_id: str,
        paths: list[str],
        target_path: Optional[str] = None,
        conflict_strategy: str = "suffix",
        overwrite: bool = False,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        if not paths:
            raise ValueError("缺少待移动项")
        source_library = self.get_library_definition(source_library_id)
        target_library = self.get_library_definition(target_library_id)
        if source_library.type != "local":
            raise RuntimeError("仅支持本地库内/之间移动")
        if target_library.type != "local":
            raise RuntimeError("仅支持移动到本地库")
        # 兼容旧 overwrite=True 的调用
        strategy = (conflict_strategy or "").strip().lower()
        if overwrite and strategy not in {"overwrite", "skip", "suffix"}:
            strategy = "overwrite"
        if strategy not in {"suffix", "overwrite", "skip"}:
            strategy = "suffix"
        return await asyncio.to_thread(
            self._move_local_items_sync,
            source_library,
            target_library,
            list(paths),
            target_path,
            strategy,
            skip_index_mutation,
        )

    async def preview_move_local_items(
        self,
        *,
        source_library_id: str,
        target_library_id: str,
        paths: list[str],
        target_path: Optional[str] = None,
    ) -> dict[str, Any]:
        if not paths:
            raise ValueError("缺少待移动项")
        source_library = self.get_library_definition(source_library_id)
        target_library = self.get_library_definition(target_library_id)
        if source_library.type != "local":
            raise RuntimeError("仅支持本地库内/之间移动")
        if target_library.type != "local":
            raise RuntimeError("仅支持移动到本地库")
        indexed = await asyncio.to_thread(
            self._preview_move_local_items_via_index,
            source_library,
            target_library,
            list(paths),
            target_path,
        )
        if indexed is not None:
            return indexed
        return await asyncio.to_thread(
            self._preview_move_local_items_sync,
            source_library,
            target_library,
            list(paths),
            target_path,
        )

    @staticmethod
    def _move_index_view(service: Any, library_id: str) -> dict[str, Any]:
        status = service.get_status(library_id)
        return {
            "library_id": library_id,
            "index_generation": int(getattr(status, "active_generation", 1) or 1),
            "accepted_seq": int(getattr(status, "accepted_seq", 0) or 0),
            "materialized_seq": int(getattr(status, "materialized_seq", 0) or 0),
            "state_revision": int(getattr(status, "state_revision", 0) or 0),
            "view_revision": int(getattr(status, "view_revision", 0) or 0),
        }

    def _store_move_preview_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from .redis_service import get_redis_service

            redis_service = get_redis_service()
            plan_id = uuid.uuid4().hex
            stored = redis_service.set_json(
                "library",
                "move-plan",
                plan_id,
                payload,
                ttl_seconds=max(60, min(redis_service.short_cache_ttl_seconds() * 2, 300)),
            )
            if stored:
                return {**payload, "move_plan_id": plan_id}
        except Exception:
            logger.debug("写入移动预检 Redis 计划失败", exc_info=True)
        return payload

    def validate_move_preview_plan(
        self,
        plan_id: str,
        *,
        source_library_id: str,
        target_library_id: str,
        paths: list[str],
        target_path: Optional[str],
    ) -> Optional[bool]:
        """校验短期预检计划；Redis 不可用或计划过期返回 None，不阻断移动。"""
        normalized_plan_id = str(plan_id or "").strip()
        if not normalized_plan_id:
            return None
        try:
            from .redis_service import get_redis_service

            payload = get_redis_service().get_json("library", "move-plan", normalized_plan_id)
        except Exception:
            logger.debug("读取移动预检 Redis 计划失败", exc_info=True)
            return None
        if not isinstance(payload, dict):
            return None

        expected_paths = sorted(os.path.normcase(os.path.abspath(path)) for path in paths)
        stored_paths = sorted(
            os.path.normcase(os.path.abspath(path))
            for path in list(payload.get("source_paths") or [])
        )
        if (
            str(payload.get("source_library_id") or "") != str(source_library_id or "")
            or str(payload.get("target_library_id") or "") != str(target_library_id or "")
            or stored_paths != expected_paths
            or os.path.normcase(os.path.abspath(payload.get("target_path") or ""))
            != os.path.normcase(os.path.abspath(target_path or ""))
        ):
            return False

        stored_views = {
            str(item.get("library_id") or ""): item
            for item in list(payload.get("index_views") or [])
            if isinstance(item, dict)
        }
        for library_id in {source_library_id, target_library_id}:
            library = self.get_library_definition(library_id)
            service = self._index_service_if_ready(library)
            stored = stored_views.get(library_id)
            if service is None or not stored:
                return False
            current = self._move_index_view(service, library_id)
            if (
                int(current.get("index_generation") or 0) != int(stored.get("index_generation") or 0)
                or int(current.get("view_revision") or 0) != int(stored.get("view_revision") or 0)
            ):
                return False
        return True

    def _preview_move_local_items_via_index(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        paths: list[str],
        target_path: Optional[str],
    ) -> Optional[dict[str, Any]]:
        """用库存索引比较源/目标子树，避免预检阶段递归扫盘。

        只对目标目录和每个顶层源做存在性检查；索引缺失或单棵子树超过
        安全上限时返回 ``None``，调用方回退到原文件系统预检。
        """
        source_service = self._index_service_if_ready(source_library)
        target_service = self._index_service_if_ready(target_library)
        if source_service is None or target_service is None:
            return None

        target_root = os.path.abspath(target_library.root_path)
        target_dir = os.path.abspath(target_path) if target_path else target_root
        if not self._local_path_is_within_root(target_dir, target_root):
            raise PermissionError("目标目录必须在所选库存内")
        if not os.path.isdir(target_dir):
            raise FileNotFoundError(f"目标目录不存在: {target_dir}")
        target_parent_relative = self._index_parent_path_for_target(target_library, target_dir)
        if target_parent_relative is None:
            return None
        if target_parent_relative:
            target_parent_entry = target_service.get_entry(target_library.id, target_parent_relative)
            if not target_parent_entry or target_parent_entry.entry_type != "dir":
                return None

        conflicts: list[dict[str, Any]] = []
        merge_folders: list[dict[str, Any]] = []
        conflict_count = 0
        merge_folder_count = 0
        subtree_limit = 100001

        for raw in paths:
            source_path = os.path.abspath(raw)
            self._assert_local_path_in_library(source_library, source_path)
            if not os.path.exists(source_path):
                raise FileNotFoundError(f"源路径不存在: {source_path}")
            if os.path.normcase(os.path.dirname(source_path)) == os.path.normcase(target_dir):
                continue
            if os.path.isdir(source_path):
                source_norm = os.path.normcase(source_path)
                target_norm = os.path.normcase(target_dir)
                if target_norm == source_norm or target_norm.startswith(source_norm + os.sep):
                    conflict_count += 1
                    conflicts.append({
                        "path": source_path,
                        "source_path": source_path,
                        "existing_path": target_dir,
                        "name": os.path.basename(source_path),
                        "is_directory": True,
                        "existing_is_directory": True,
                        "relative_path": os.path.basename(source_path),
                        "conflict_type": "invalid_target",
                        "reason": "无法将目录移入自身或其子目录",
                    })
                    continue

            source_relative = self._index_parent_path_for_target(source_library, source_path)
            if source_relative is None:
                return None
            source_entry = source_service.get_entry(source_library.id, source_relative)
            if not source_entry:
                return None
            source_is_directory_on_disk = os.path.isdir(source_path)
            if (source_entry.entry_type == "dir") != source_is_directory_on_disk:
                return None
            destination_path = os.path.join(target_dir, os.path.basename(source_path))
            destination_relative = self._index_parent_path_for_target(target_library, destination_path)
            if destination_relative is None:
                return None
            destination_entry = target_service.get_entry(target_library.id, destination_relative)
            if destination_entry is None:
                if os.path.exists(destination_path):
                    return None
                continue
            if not os.path.exists(destination_path):
                return None

            source_is_dir = source_entry.entry_type == "dir"
            destination_is_dir = destination_entry.entry_type == "dir"
            if not source_is_dir or not destination_is_dir:
                conflict_count += 1
                if len(conflicts) < 200:
                    conflicts.append({
                        "path": source_path,
                        "source_path": source_path,
                        "existing_path": destination_path,
                        "name": os.path.basename(source_path),
                        "relative_path": os.path.basename(source_path),
                        "is_directory": source_is_dir,
                        "existing_is_directory": destination_is_dir,
                        "conflict_type": "type_mismatch" if source_is_dir != destination_is_dir else "name_conflict",
                        "reason": "目标位置已存在同名项",
                    })
                continue

            source_entries = source_service.list_subtree_entries(
                source_library.id,
                source_relative,
                include_self=True,
                limit=subtree_limit,
            )
            destination_entries = target_service.list_subtree_entries(
                target_library.id,
                destination_relative,
                include_self=True,
                limit=subtree_limit,
            )
            if len(source_entries) >= subtree_limit or len(destination_entries) >= subtree_limit:
                return None

            def suffix_map(entries, root_relative: str) -> dict[str, tuple[str, Any]]:
                root = str(root_relative or "").strip("/")
                mapped = {}
                for entry in entries:
                    relative = str(entry.relative_path or "").strip("/")
                    suffix = "" if relative == root else relative[len(root) + 1:]
                    key = os.path.normcase(suffix.replace("/", os.sep))
                    mapped[key] = (suffix, entry)
                return mapped

            source_by_suffix = suffix_map(source_entries, source_relative)
            destination_by_suffix = suffix_map(destination_entries, destination_relative)
            for suffix_key, (suffix, source_child) in source_by_suffix.items():
                destination_match = destination_by_suffix.get(suffix_key)
                if destination_match is None:
                    continue
                _, destination_child = destination_match
                relative_display = os.path.join(os.path.basename(source_path), *suffix.split("/")) if suffix else os.path.basename(source_path)
                source_child_is_dir = source_child.entry_type == "dir"
                destination_child_is_dir = destination_child.entry_type == "dir"
                if source_child_is_dir and destination_child_is_dir:
                    merge_folder_count += 1
                    if len(merge_folders) < 200:
                        merge_folders.append({
                            "path": source_child.absolute_path,
                            "source_path": source_child.absolute_path,
                            "existing_path": destination_child.absolute_path,
                            "name": source_child.name,
                            "relative_path": relative_display,
                            "is_directory": True,
                            "existing_is_directory": True,
                        })
                    continue
                conflict_count += 1
                if len(conflicts) < 200:
                    conflicts.append({
                        "path": source_child.absolute_path,
                        "source_path": source_child.absolute_path,
                        "existing_path": destination_child.absolute_path,
                        "name": source_child.name,
                        "relative_path": relative_display,
                        "is_directory": source_child_is_dir,
                        "existing_is_directory": destination_child_is_dir,
                        "conflict_type": "type_mismatch" if source_child_is_dir != destination_child_is_dir else "name_conflict",
                        "reason": "目标位置已存在同名项",
                    })

        payload = {
            "source_library_id": source_library.id,
            "source_paths": [os.path.abspath(path) for path in paths],
            "target_path": target_dir,
            "target_library_id": target_library.id,
            "conflict_count": conflict_count,
            "merge_folder_count": merge_folder_count,
            "has_conflicts": conflict_count > 0,
            "conflicts": conflicts,
            "conflicts_truncated": conflict_count > len(conflicts),
            "merge_folders": merge_folders,
            "merge_folders_truncated": merge_folder_count > len(merge_folders),
            "preview_source": "index",
            "index_views": [
                self._move_index_view(source_service, source_library.id),
                self._move_index_view(target_service, target_library.id),
            ],
        }
        return self._store_move_preview_plan(payload)

    def _preview_move_local_items_sync(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        paths: list[str],
        target_path: Optional[str],
    ) -> dict[str, Any]:
        target_root = os.path.abspath(target_library.root_path)
        target_dir = os.path.abspath(target_path) if target_path else target_root
        if not self._local_path_is_within_root(target_dir, target_root):
            raise PermissionError("目标目录必须在所选库存内")
        if not os.path.isdir(target_dir):
            raise FileNotFoundError(f"目标目录不存在: {target_dir}")

        conflicts: list[dict[str, Any]] = []
        merge_folders: list[dict[str, Any]] = []
        for raw in paths:
            source_path = os.path.abspath(raw)
            self._assert_local_path_in_library(source_library, source_path)
            if not os.path.exists(source_path):
                raise FileNotFoundError(f"源路径不存在: {source_path}")

            if os.path.normcase(os.path.dirname(source_path)) == os.path.normcase(target_dir):
                continue
            if os.path.isdir(source_path):
                source_norm = os.path.normcase(source_path)
                target_norm = os.path.normcase(target_dir)
                if target_norm == source_norm or target_norm.startswith(source_norm + os.sep):
                    conflicts.append({
                        "path": source_path,
                        "source_path": source_path,
                        "existing_path": target_dir,
                        "name": os.path.basename(source_path),
                        "is_directory": True,
                        "existing_is_directory": True,
                        "relative_path": os.path.basename(source_path),
                        "conflict_type": "invalid_target",
                        "reason": "无法将目录移入自身或其子目录",
                    })
                    continue

            dest_path = os.path.join(target_dir, os.path.basename(source_path))
            self._collect_local_move_conflicts(
                source_path,
                dest_path,
                os.path.basename(source_path),
                conflicts,
                merge_folders,
            )

        return {
            "target_path": target_dir,
            "target_library_id": target_library.id,
            "conflict_count": len(conflicts),
            "merge_folder_count": len(merge_folders),
            "has_conflicts": bool(conflicts),
            "conflicts": conflicts,
            "merge_folders": merge_folders[:200],
            "merge_folders_truncated": len(merge_folders) > 200,
        }

    def _collect_local_move_conflicts(
        self,
        source_path: str,
        dest_path: str,
        relative_path: str,
        conflicts: list[dict[str, Any]],
        merge_folders: list[dict[str, Any]],
    ) -> None:
        if not os.path.exists(dest_path):
            return

        source_is_dir = os.path.isdir(source_path)
        dest_is_dir = os.path.isdir(dest_path)
        name = os.path.basename(source_path)

        if source_is_dir and dest_is_dir:
            merge_folders.append({
                "path": source_path,
                "source_path": source_path,
                "existing_path": dest_path,
                "name": name,
                "relative_path": relative_path,
                "is_directory": True,
                "existing_is_directory": True,
            })
            try:
                with os.scandir(source_path) as iterator:
                    for entry in iterator:
                        child_rel = os.path.join(relative_path, entry.name)
                        self._collect_local_move_conflicts(
                            entry.path,
                            os.path.join(dest_path, entry.name),
                            child_rel,
                            conflicts,
                            merge_folders,
                        )
            except OSError as exc:
                conflicts.append({
                    "path": source_path,
                    "source_path": source_path,
                    "existing_path": dest_path,
                    "name": name,
                    "relative_path": relative_path,
                    "is_directory": True,
                    "existing_is_directory": True,
                    "conflict_type": "scan_failed",
                    "reason": str(exc),
                })
            return

        conflict_type = "type_mismatch" if source_is_dir != dest_is_dir else "name_conflict"
        conflicts.append({
            "path": source_path,
            "source_path": source_path,
            "existing_path": dest_path,
            "name": name,
            "relative_path": relative_path,
            "is_directory": source_is_dir,
            "existing_is_directory": dest_is_dir,
            "conflict_type": conflict_type,
            "reason": "目标位置已存在同名项",
        })

    def _unique_local_destination_path(self, target_dir: str, base_name: str, is_dir: bool) -> str:
        if is_dir:
            stem, ext = base_name, ""
        else:
            stem, ext = os.path.splitext(base_name)
        counter = 1
        candidate = os.path.join(target_dir, f"{stem}_{counter}{ext}")
        while os.path.exists(candidate):
            counter += 1
            candidate = os.path.join(target_dir, f"{stem}_{counter}{ext}")
        return candidate

    def _merge_local_directory_into(
        self,
        source_dir: str,
        dest_dir: str,
        conflict_strategy: str,
    ) -> dict[str, Any]:
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        try:
            names = os.listdir(source_dir)
        except OSError as exc:
            return {
                "removed_source": False,
                "skipped": skipped,
                "failed": [{"path": source_dir, "name": os.path.basename(source_dir), "error": str(exc)}],
            }

        for name in names:
            source_child = os.path.join(source_dir, name)
            dest_child = os.path.join(dest_dir, name)
            try:
                source_is_dir = os.path.isdir(source_child)
                if os.path.exists(dest_child):
                    if source_is_dir and os.path.isdir(dest_child):
                        child_result = self._merge_local_directory_into(
                            source_child,
                            dest_child,
                            conflict_strategy,
                        )
                        skipped.extend(child_result.get("skipped") or [])
                        failed.extend(child_result.get("failed") or [])
                        continue
                    if conflict_strategy == "skip":
                        skipped.append({
                            "path": source_child,
                            "name": name,
                            "reason": "目标已存在同名项，按策略跳过",
                        })
                        continue
                    if conflict_strategy == "overwrite":
                        if os.path.isdir(dest_child):
                            _robust_rmtree(dest_child)
                        else:
                            os.remove(dest_child)
                    else:
                        dest_child = self._unique_local_destination_path(dest_dir, name, source_is_dir)

                shutil.move(source_child, dest_child)
            except Exception as exc:
                failed.append({"path": source_child, "name": name, "error": str(exc)})

        removed_source = False
        try:
            if not os.listdir(source_dir):
                os.rmdir(source_dir)
                removed_source = True
        except OSError:
            removed_source = False

        return {
            "removed_source": removed_source,
            "skipped": skipped,
            "failed": failed,
        }

    def _move_local_items_sync(
        self,
        source_library: LibraryDefinition,
        target_library: LibraryDefinition,
        paths: list[str],
        target_path: Optional[str],
        conflict_strategy: str,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        target_root = os.path.abspath(target_library.root_path)
        target_dir = os.path.abspath(target_path) if target_path else target_root
        if not self._local_path_is_within_root(target_dir, target_root):
            raise PermissionError("目标目录必须在所选库存内")
        if not os.path.isdir(target_dir):
            raise FileNotFoundError(f"目标目录不存在: {target_dir}")

        normalized_paths: list[str] = []
        for raw in paths:
            normalized = os.path.abspath(raw)
            self._assert_local_path_in_library(source_library, normalized)
            if not os.path.exists(normalized):
                raise FileNotFoundError(f"源路径不存在: {normalized}")
            normalized_paths.append(normalized)

        target_dir_norm = os.path.normcase(target_dir)
        success: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        moved_index_items: list[dict[str, str]] = []
        deleted_index_paths: list[str] = []
        replace_index_paths: dict[str, tuple[LibraryDefinition, set[str]]] = {}
        index_mutation: Optional[dict[str, Any]] = None

        def queue_replace_index(library: LibraryDefinition, path: str) -> None:
            if not path:
                return
            bucket = replace_index_paths.setdefault(library.id, (library, set()))
            bucket[1].add(path)

        for path in normalized_paths:
            try:
                base_name = os.path.basename(path)
                is_dir = os.path.isdir(path)
                parent_norm = os.path.normcase(os.path.dirname(path))
                # 目标目录与源所在父目录相同 -> 等于不动，跳过
                if parent_norm == target_dir_norm:
                    skipped.append({"path": path, "name": base_name, "reason": "目标目录与源相同"})
                    continue
                # 不能把目录移入自身或自身的子目录
                if is_dir:
                    source_norm = os.path.normcase(path)
                    if target_dir_norm == source_norm or target_dir_norm.startswith(source_norm + os.sep):
                        failed.append({"path": path, "name": base_name, "error": "无法将目录移入自身或其子目录"})
                        continue

                dest_path = os.path.join(target_dir, base_name)
                if os.path.exists(dest_path):
                    if is_dir and os.path.isdir(dest_path):
                        merge_result = self._merge_local_directory_into(path, dest_path, conflict_strategy)
                        skipped.extend(merge_result.get("skipped") or [])
                        failed.extend(merge_result.get("failed") or [])
                        queue_replace_index(target_library, dest_path)
                        if merge_result.get("removed_source"):
                            self._local_top_level_delta(source_library, path, -1)
                            deleted_index_paths.append(path)
                            success.append({
                                "source": path,
                                "destination": dest_path,
                                "name": base_name,
                                "merged": True,
                            })
                        else:
                            queue_replace_index(source_library, path)
                        continue
                    if conflict_strategy == "skip":
                        skipped.append({"path": path, "name": base_name, "reason": "目标已存在同名项，按策略跳过"})
                        continue
                    if conflict_strategy == "overwrite":
                        if os.path.isdir(dest_path):
                            _robust_rmtree(dest_path)
                        else:
                            os.remove(dest_path)
                    else:  # suffix（默认）
                        dest_path = self._unique_local_destination_path(target_dir, base_name, is_dir)

                shutil.move(path, dest_path)

                # 顶层判定 / search cache 失效 / folder_count 增减全部由 _local_top_level_delta 内部处理
                if is_dir:
                    self._local_top_level_delta(source_library, path, -1)
                    self._local_top_level_delta(target_library, dest_path, 1)
                moved_index_items.append({"source": path, "destination": dest_path})
                success.append({
                    "source": path,
                    "destination": dest_path,
                    "name": base_name,
                })
            except Exception as exc:
                failed.append({"path": path, "name": os.path.basename(path), "error": str(exc)})

        # 文件级移动不会触发 _local_top_level_delta，这里兜底清一次本地浏览缓存
        self._invalidate_local_browse_caches(source_library.id)
        if target_library.id != source_library.id:
            self._invalidate_local_browse_caches(target_library.id)

        # 索引同步：普通移动走 fast-path；目录合并会影响已有目标目录，改为 delete 源 + replace 目标。
        if moved_index_items and not skip_index_mutation:
            index_mutation = self._notify_index_self_mutation_move_batch(
                source_library,
                target_library,
                moved_index_items,
            )
        if deleted_index_paths and not skip_index_mutation:
            self._notify_index_self_mutation_delete_batch(source_library, deleted_index_paths)
        for library, paths_to_replace in ([] if skip_index_mutation else replace_index_paths.values()):
            try:
                self._enqueue_index_replace_subtree_many(library, list(paths_to_replace))
            except Exception:
                logger.debug(
                    "[索引] 目录合并后 replace 子树调度失败 library=%s count=%s",
                    library.id,
                    len(paths_to_replace),
                    exc_info=True,
                )

        self._append_stats_log(
            source_library,
            "INFO",
            f"批量移动 -> {target_library.id}:{target_dir} success={len(success)} skipped={len(skipped)} failed={len(failed)}",
        )

        result = {
            "message": "批量移动完成",
            "success_count": len(success),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "moved": success,
            "skipped": skipped,
            "failed": failed,
            "target_path": target_dir,
            "target_library_id": target_library.id,
        }
        if index_mutation:
            result.update({
                "operation_id": index_mutation.get("operation_id"),
                "operation_state": index_mutation.get("operation_state"),
                "index_fences": list(index_mutation.get("index_fences") or []),
            })
        return result

    async def open_folder(self, library_id: str, path: str, force_local: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "synology_filestation":
            return {
                "message": "远程库请通过群晖链接打开",
                "mode": "remote",
                "remote_url": library.synology.base_url if library.synology else "",
                "web_url": build_synology_web_url(library.synology.base_url, path) if library.synology else "",
                "path": path,
            }
        return {"message": "可直接打开", "mode": "direct", "path": path}

    async def test_connection(self, library_data: dict[str, Any]) -> dict[str, Any]:
        library = self._library_from_payload(library_data)
        health = self._health_for_library(library, warning_free_gb=0)
        if library.type == "local":
            return {
                "ok": health.get("is_accessible", False),
                "type": "local",
                "health": health,
                "message": "本地库存可访问" if health.get("is_accessible", False) else "本地库存不可访问",
            }

        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接参数")
        client = self.get_cached_synology_client(library.synology)
        result = await client.test_connection(library.root_path)
        return {
            "ok": True,
            "type": "synology_filestation",
            "health": health,
            "device_id": result.get("device_id") or "",
            "web_url": result.get("web_url") or "",
            "message": "群晖连接成功",
        }

    async def ensure_stats(self, force: bool = False, library_id: Optional[str] = None) -> dict[str, Any]:
        cfg = self.load_config()
        libraries = []
        total_folders = 0
        total_bytes = 0
        warning_free_gb = float(cfg["health_warning_free_gb"])
        for library in self._active_libraries(cfg):
            if library.type == "local":
                cached = self._collect_local_stats_via_index(library)
            else:
                cached = dict(self._stats_cache.get(library.id) or {})
                if not cached or self._remote_stats_uses_inventory_index(cached):
                    cached = self._remote_filestation_stats_placeholder(library)
            if cached is None:
                cached = {
                    "library_id": library.id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "status": "idle",
                    "folder_count": 0,
                    "total_size_bytes": 0,
                    "total_size_gb": 0,
                    "last_completed_at": None,
                    "updated_at": time.time(),
                    "scan_mode": "index_required",
                    "warning": "索引未就绪，请先重建索引",
                }
            cached["health"] = self._health_for_library(library, warning_free_gb)
            self._stats_cache[library.id] = cached
            libraries.append(cached)
            total_folders += int(cached.get("folder_count", 0) or 0)
            total_bytes += int(cached.get("total_size_bytes", 0) or 0)

        return {
            "libraries": libraries,
            "all_libraries": {
                "folder_count": total_folders,
                "total_size_bytes": total_bytes,
                "total_size_gb": _gb(total_bytes),
            },
        }

    async def cancel_stats(self, library_id: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        task = self._stats_tasks.get(library.id)
        cached = self._stats_cache.get(library.id) or {}
        if task and not task.done():
            task.cancel()
            self._append_stats_log(library, "WARN", "收到远程统计取消请求")
        cached["library_id"] = library.id
        cached["library_name"] = library.name
        cached["library_type"] = library.type
        cached["status"] = "canceled"
        cached["updated_at"] = time.time()
        cached["health"] = self._health_for_library(library, float(self.load_config()["health_warning_free_gb"]))
        self._stats_cache[library.id] = cached
        self._persist_stats()
        return {
            "ok": True,
            "library_id": library.id,
            "status": "canceled",
            "message": "统计任务已取消",
        }

    async def _refresh_stats_for_library(self, library: LibraryDefinition):
        if library.type == "local":
            stats = await asyncio.to_thread(self._collect_local_stats, library)
        else:
            stats = {
                "library_id": library.id,
                "library_name": library.name,
                "status": "unsupported",
                "folder_count": 0,
                "total_size_bytes": 0,
                "total_size_gb": 0,
                "warning": "远程库统计仍依赖群晖目录遍历，当前版本先返回健康信息",
            }
        health = self._health_for_library(library, float(self.load_config()["health_warning_free_gb"]))
        stats["health"] = health
        stats["updated_at"] = time.time()
        self._stats_cache[library.id] = stats

    def _collect_local_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        # 只统计顶层目录数量，不做递归 os.walk 大小计算，避免在 SMB 映射盘等慢速路径上阻塞。
        target_root = os.path.abspath(library.root_path)
        folder_count = 0
        if os.path.exists(target_root):
            try:
                folder_count = sum(1 for e in os.scandir(target_root) if e.is_dir())
            except OSError:
                pass
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "ready",
            "folder_count": folder_count,
            "total_size_bytes": 0,
            "total_size_gb": 0,
        }

    async def _remote_file_size(self, client: SynologyFileStationClient, remote_path: str) -> Optional[int]:
        try:
            info = await client.stat(self._normalize_remote_path(remote_path))
            item = self._first_remote_info_item(info)
            if not item:
                return None
            additional = item.get("additional") or {}
            if "size" in additional:
                return int(additional.get("size") or 0)
            if "size" in item:
                return int(item.get("size") or 0)
        except Exception:
            return None
        return None

    async def _verify_uploaded_remote_file(
        self,
        client: SynologyFileStationClient,
        *,
        source_path: str,
        remote_path: str,
        relative_path: str,
        expected_size: int,
        retries: int = 4,
    ) -> None:
        actual_size: Optional[int] = None
        for attempt in range(retries):
            actual_size = await self._remote_file_size(client, remote_path)
            if actual_size is not None and actual_size == expected_size:
                return
            if attempt < retries - 1:
                await asyncio.sleep(min(2.0, 0.4 * (attempt + 1)))

        failure = {
            "source_path": source_path,
            "remote_path": remote_path,
            "relative_path": relative_path,
            "expected_size": expected_size,
            "actual_size": actual_size,
            "reason": "远端文件不存在" if actual_size is None else "远端文件大小不一致",
        }
        raise LocalUploadVerificationError(
            f"上传后远端校验失败: {relative_path or os.path.basename(source_path)}",
            source_path=source_path,
            remote_path=remote_path,
            failures=[failure],
        )

    def _cleanup_uploaded_source(self, source_path: str, remote_path: str) -> None:
        try:
            if os.path.isfile(source_path):
                _robust_unlink(source_path)
                return
            if os.path.isdir(source_path):
                _robust_rmtree(source_path)
                return
        except Exception as exc:
            raise LocalUploadCleanupError(
                f"远端已确认上传完成，但删除本地源失败: {source_path}，{exc}",
                source_path=source_path,
                remote_path=remote_path,
                cleanup_error=str(exc),
            ) from exc

    async def _wait_for_source_delete_access(
        self,
        source_path: str,
        *,
        timeout_seconds: float = 20.0,
        stage: str = "上传前",
    ) -> None:
        deadline = time.monotonic() + max(0.5, timeout_seconds)
        locked: list[dict[str, Any]] = []
        while True:
            locked = await asyncio.to_thread(_collect_delete_locked_paths, source_path)
            if not locked:
                return
            if time.monotonic() >= deadline:
                sample = locked[0]
                raise LocalUploadSourceLockedError(
                    f"{stage}检测到本地文件仍被占用，已停止上传: {sample.get('path')}，{sample.get('reason')}",
                    source_path=source_path,
                    locked_paths=locked,
                )
            await asyncio.sleep(0.75)

    async def upload_directory_to_library(
        self,
        library_id: str,
        source_dir: str,
        relative_target_dir: Optional[str] = None,
        *,
        delete_source_on_success: bool = False,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        file_completed_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> str:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._move_directory_to_local_library, library, source_dir, relative_target_dir)

        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        client = self.get_cached_synology_client(library.synology)
        target_root = PurePosixPath(library.root_path)
        if relative_target_dir:
            target_root = target_root / relative_target_dir
        target_root_path = self._normalize_remote_path(str(target_root))
        await self._ensure_remote_directory(client, target_root_path)

        normalized_source_dir = str(source_dir or "").rstrip("\\/")
        source_name = os.path.basename(os.path.abspath(normalized_source_dir))
        if not source_name:
            raise RuntimeError("来源名称无效，无法上传到远程库存")
        if delete_source_on_success:
            await self._wait_for_source_delete_access(
                normalized_source_dir,
                timeout_seconds=20.0,
                stage="上传前",
            )

        # 单文件场景：直接将文件上传到 target_root_path，不再套一层同名子目录
        if os.path.isfile(normalized_source_dir):
            final_remote_path = self._normalize_remote_path(str(PurePosixPath(target_root_path) / source_name))
            await self._upload_directory_to_synology(
                client,
                source_dir,
                target_root_path,
                progress_callback=progress_callback,
                file_completed_callback=file_completed_callback,
            )
            if delete_source_on_success:
                await self._wait_for_source_delete_access(
                    source_dir,
                    timeout_seconds=15.0,
                    stage="本地清理前",
                )
                self._cleanup_uploaded_source(source_dir, final_remote_path)
            return final_remote_path

        final_remote_path = self._normalize_remote_path(str(PurePosixPath(target_root_path) / source_name))
        if not await self._remote_path_exists(client, final_remote_path):
            await self._ensure_remote_directory(client, final_remote_path)

        await self._upload_directory_to_synology(
            client,
            source_dir,
            final_remote_path,
            progress_callback=progress_callback,
            file_completed_callback=file_completed_callback,
        )
        if delete_source_on_success:
            await self._wait_for_source_delete_access(
                source_dir,
                timeout_seconds=15.0,
                stage="本地清理前",
            )
            self._cleanup_uploaded_source(source_dir, final_remote_path)
        return final_remote_path

    def _move_directory_to_local_library(self, library: LibraryDefinition, source_dir: str, relative_target_dir: Optional[str]) -> str:
        target_root = library.root_path
        if relative_target_dir:
            target_root = os.path.join(target_root, relative_target_dir)
        os.makedirs(target_root, exist_ok=True)
        final_path = os.path.join(target_root, os.path.basename(source_dir))
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(target_root, f"{os.path.basename(source_dir)}_{counter}")
            counter += 1
        shutil.move(source_dir, final_path)
        self._local_top_level_delta(library, final_path, 1)
        return final_path

    async def _upload_directory_to_synology(
        self,
        client: SynologyFileStationClient,
        source_dir: str,
        remote_root: str,
        *,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        file_completed_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        remote_root = remote_root.rstrip("/")
        await self._ensure_remote_directory(client, remote_root)
        if progress_callback:
            progress_callback({
                "phase": "preparing",
                "current_file_name": "",
                "current_relative_path": "",
                "current_source_dir": source_dir,
                "current_file_total_bytes": 0,
                "current_file_uploaded_bytes": 0,
                "completed_files": 0,
                "total_files": 0,
                "transferred_bytes": 0,
                "total_bytes": 0,
                "speed_bytes_per_sec": 0,
            })
        file_rows = []
        # 单文件场景：直接构造唯一一条 file_row，复用下面的并发上传通道
        if os.path.isfile(source_dir):
            try:
                file_size = int(os.path.getsize(source_dir))
            except OSError:
                file_size = 0
            filename = os.path.basename(source_dir)
            file_rows.append({
                "local_path": source_dir,
                "relative_path": filename,
                "name": filename,
                "size": file_size,
                "remote_dir": remote_root,
                "source_dir": source_dir,
            })
            file_iteration = []
        else:
            file_iteration = list(os.walk(source_dir))

        for root, dirs, files in file_iteration:
            relative = os.path.relpath(root, source_dir)
            remote_dir = remote_root if relative == "." else f"{remote_root}/{relative.replace(os.sep, '/')}"
            if dirs:
                if progress_callback:
                    for directory in dirs:
                        progress_callback({
                            "phase": "preparing",
                            "current_file_name": directory,
                            "current_relative_path": os.path.join(relative if relative != "." else "", directory).replace(os.sep, "/"),
                            "current_source_dir": source_dir,
                            "current_file_total_bytes": 0,
                            "current_file_uploaded_bytes": 0,
                            "completed_files": 0,
                            "total_files": len(file_rows),
                            "transferred_bytes": 0,
                            "total_bytes": 0,
                            "speed_bytes_per_sec": 0,
                        })
                # U4: 同层目录并发创建，父目录由 os.walk 自顶向下保证先于子目录
                # 容忍 error 117 / "already exists"（重传场景目录可能已存在）
                async def _create_folder_safe(parent: str, name: str) -> None:
                    try:
                        await client.create_folder(parent, name)
                    except Exception as _exc:
                        if "already exists" in str(_exc).lower() or client._is_error_code(_exc, 117):
                            return
                        raise
                await asyncio.gather(*[_create_folder_safe(remote_dir, directory) for directory in dirs])
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, source_dir).replace(os.sep, "/")
                try:
                    file_size = int(os.path.getsize(local_path))
                except OSError:
                    file_size = 0
                file_rows.append({
                    "local_path": local_path,
                    "relative_path": relative_path,
                    "name": filename,
                    "size": file_size,
                    "remote_dir": remote_dir,
                    "source_dir": source_dir,
                })

        total_bytes = sum(int(item.get("size") or 0) for item in file_rows)
        started_at = time.monotonic()
        last_speed_sample_at = started_at
        last_speed_sample_bytes = 0
        stable_speed_bytes_per_sec = 0
        speed_sample_interval = 0.75
        # FileStation Upload 对同一目录并发写入很容易在公网/反代链路下返回 408。
        # 这里保持单文件流式上传，避免前端等待最终补配时发生超时回滚竞态。
        completed_files = 0
        completed_bytes = 0
        in_flight_bytes: dict[str, int] = {row["local_path"]: 0 for row in file_rows}
        _upload_semaphore = asyncio.Semaphore(1)

        def emit_progress(current_row: dict, uploaded_bytes: int):
            nonlocal last_speed_sample_at, last_speed_sample_bytes, stable_speed_bytes_per_sec
            if not progress_callback:
                return
            transferred_bytes = min(total_bytes, completed_bytes + sum(in_flight_bytes.values()))
            now = time.monotonic()
            elapsed = max(0.001, now - started_at)
            delta_time = now - last_speed_sample_at
            delta_bytes = max(0, transferred_bytes - last_speed_sample_bytes)
            if transferred_bytes >= total_bytes and total_bytes > 0:
                stable_speed_bytes_per_sec = 0
                last_speed_sample_at = now
                last_speed_sample_bytes = transferred_bytes
            elif delta_time >= speed_sample_interval:
                sample_speed = int(delta_bytes / max(delta_time, 0.001)) if delta_bytes > 0 else 0
                if sample_speed > 0 and stable_speed_bytes_per_sec > 0:
                    stable_speed_bytes_per_sec = int((stable_speed_bytes_per_sec * 0.65) + (sample_speed * 0.35))
                else:
                    stable_speed_bytes_per_sec = sample_speed
                last_speed_sample_at = now
                last_speed_sample_bytes = transferred_bytes
            remaining_bytes = max(0, total_bytes - transferred_bytes)
            progress_callback({
                "phase": "uploading",
                "current_file_name": current_row.get("name") or "",
                "current_relative_path": current_row.get("relative_path") or "",
                "current_source_dir": current_row.get("source_dir") or "",
                "current_file_total_bytes": int(current_row.get("size") or 0),
                "current_file_uploaded_bytes": max(0, int(uploaded_bytes or 0)),
                "completed_files": completed_files,
                "total_files": len(file_rows),
                "transferred_bytes": transferred_bytes,
                "total_bytes": total_bytes,
                "speed_bytes_per_sec": stable_speed_bytes_per_sec,
                "average_speed_bytes_per_sec": int(transferred_bytes / elapsed) if transferred_bytes > 0 else 0,
                "eta_seconds": int(remaining_bytes / stable_speed_bytes_per_sec) if stable_speed_bytes_per_sec > 0 and remaining_bytes > 0 else 0,
                "active_file_count": 1 if remaining_bytes > 0 else 0,
            })

        async def upload_one(row: dict):
            nonlocal completed_files, completed_bytes
            key = row["local_path"]
            async with _upload_semaphore:
                def on_file_progress(uploaded: int, _total: int, _row=row, _key=key):
                    in_flight_bytes[_key] = uploaded
                    emit_progress(_row, uploaded)

                await client.upload_file(
                    row["remote_dir"],
                    row["local_path"],
                    progress_callback=on_file_progress,
                )
                remote_file_path = self._normalize_remote_path(
                    str(PurePosixPath(row["remote_dir"]) / str(row.get("name") or os.path.basename(row["local_path"])))
                )
                await self._verify_uploaded_remote_file(
                    client,
                    source_path=row["local_path"],
                    remote_path=remote_file_path,
                    relative_path=str(row.get("relative_path") or row.get("name") or ""),
                    expected_size=int(row.get("size") or 0),
                )
                in_flight_bytes[key] = 0
                completed_files += 1
                completed_bytes += int(row.get("size") or 0)
                emit_progress(row, int(row.get("size") or 0))
                if file_completed_callback:
                    file_completed_callback({
                        "name": row.get("name") or "",
                        "relative_path": row.get("relative_path") or "",
                        "size": int(row.get("size") or 0),
                        "uploaded_bytes": int(row.get("size") or 0),
                        "progress": 100,
                        "status": "completed",
                        "source_dir": row.get("source_dir") or "",
                        "remote_dir": row.get("remote_dir") or "",
                    })

        upload_tasks = [asyncio.create_task(upload_one(row)) for row in file_rows]
        try:
            await asyncio.gather(*upload_tasks)
        except Exception:
            for upload_task in upload_tasks:
                if not upload_task.done():
                    upload_task.cancel()
            await asyncio.gather(*upload_tasks, return_exceptions=True)
            raise

    async def _ensure_remote_directory(self, client: SynologyFileStationClient, remote_dir: str):
        normalized = self._normalize_remote_path(remote_dir)
        if normalized in {"", "/"}:
            return
        parts = PurePosixPath(normalized).parts
        current = parts[0] if parts and parts[0] == "/" else ""
        for part in parts[1:] if current == "/" else parts:
            parent = current or "/"
            next_path = str(PurePosixPath(parent) / part)
            try:
                await client.create_folder(parent, part)
            except Exception as exc:
                if "already exists" not in str(exc).lower():
                    info = await client.stat(next_path)
                    item = self._first_remote_info_item(info)
                    if not item or not item.get("isdir", False):
                        raise
            current = next_path

    async def replace_remote_directory_with_local(self, library_id: str, source_dir: str, target_path: str) -> str:
        library = self.get_library_definition(library_id)
        if library.type != "synology_filestation" or not library.synology:
            raise RuntimeError("目标库存不是群晖远程库存")

        client = self.get_cached_synology_client(library.synology)
        target = self._normalize_remote_path(target_path)
        parent = str(PurePosixPath(target).parent)
        target_name = PurePosixPath(target).name
        stage_name = f"{target_name}.__kikoerumanager_stage__.{uuid.uuid4().hex[:8]}"
        backup_name = f"{target_name}.__kikoerumanager_backup__.{uuid.uuid4().hex[:8]}"
        stage_path = str(PurePosixPath(parent) / stage_name)
        backup_path = str(PurePosixPath(parent) / backup_name)
        target_exists = await self._remote_path_exists(client, target)

        await self._upload_directory_to_synology(client, source_dir, stage_path)
        try:
            if target_exists:
                await self._retry_remote_rename(client, target, backup_name)
            try:
                await self._retry_remote_rename(client, stage_path, target_name)
            except Exception:
                if target_exists:
                    await self._retry_remote_rename(client, backup_path, target_name)
                raise
            if target_exists:
                await self._retry_remote_delete(client, backup_path)
            return target
        except Exception:
            try:
                await self._retry_remote_delete(client, stage_path)
            except Exception as exc:
                logger.warning("清理远程阶段目录失败: %s err=%s", stage_path, sanitize_text_for_log(exc))
            raise

    async def merge_remote_directory_with_local(
        self,
        library_id: str,
        target_path: str,
        source_dir: str,
        compare_items: list[dict[str, Any]],
        decisions: dict[str, str],
    ) -> str:
        library = self.get_library_definition(library_id)
        if library.type != "synology_filestation" or not library.synology:
            raise RuntimeError("目标库存不是群晖远程库存")

        client = self.get_cached_synology_client(library.synology)
        target = self._normalize_remote_path(target_path)
        parent = str(PurePosixPath(target).parent)
        target_name = PurePosixPath(target).name
        stage_name = f"{target_name}.__kikoerumanager_stage__.{uuid.uuid4().hex[:8]}"
        backup_name = f"{target_name}.__kikoerumanager_backup__.{uuid.uuid4().hex[:8]}"
        stage_path = str(PurePosixPath(parent) / stage_name)
        backup_path = str(PurePosixPath(parent) / backup_name)

        normalized_decisions = {
            str(relative_path or ""): str(action or "").strip().lower()
            for relative_path, action in (decisions or {}).items()
        }

        await self._upload_directory_to_synology(client, source_dir, stage_path)

        for item in compare_items:
            relative_path = str(item.get("relative_path") or "")
            if not relative_path:
                continue
            decision = normalized_decisions.get(relative_path)
            item_type = str(item.get("type") or "")
            if item_type == "dir":
                if decision == "delete":
                    continue
                if str(item.get("status") or "") == "old_only":
                    await self._ensure_remote_directory(client, str(PurePosixPath(stage_path) / relative_path))
                continue

            if item_type != "file":
                continue

            old_path = str(item.get("old_path") or "")
            new_path = str(item.get("new_path") or "")
            if decision == "delete":
                stage_file = self._normalize_remote_path(str(PurePosixPath(stage_path) / relative_path))
                try:
                    await client.delete(stage_file)
                except Exception:
                    pass
                continue
            if decision == "use_old" and old_path:
                remote_dir = self._normalize_remote_path(str(PurePosixPath(stage_path) / PurePosixPath(relative_path).parent))
                await self._ensure_remote_directory(client, remote_dir)
                await client.copy(old_path, remote_dir, overwrite=True)
                continue
            if decision == "use_new" and not new_path:
                stage_file = self._normalize_remote_path(str(PurePosixPath(stage_path) / relative_path))
                try:
                    await client.delete(stage_file)
                except Exception:
                    pass

        target_exists = await self._remote_path_exists(client, target)
        try:
            if target_exists:
                await self._retry_remote_rename(client, target, backup_name)
            try:
                await self._retry_remote_rename(client, stage_path, target_name)
            except Exception:
                if target_exists:
                    await self._retry_remote_rename(client, backup_path, target_name)
                raise
            if target_exists:
                await self._retry_remote_delete(client, backup_path)
            return target
        except Exception:
            try:
                await self._retry_remote_delete(client, stage_path)
            except Exception as exc:
                logger.warning("清理远程合并阶段目录失败: %s err=%s", stage_path, sanitize_text_for_log(exc))
            raise

    def _assert_local_path_in_library(self, library: LibraryDefinition, path: str):
        library_root = os.path.abspath(library.root_path)
        target_path = os.path.abspath(path)
        if not self._local_path_is_within_root(target_path, library_root):
            raise PermissionError("目标路径超出当前库存根目录")

    def _path_size(self, path: str) -> int:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename))
                except OSError:
                    continue
        return total

    def _local_folder_summary_from_filesystem(
        self,
        path: str,
        *,
        max_entries: Optional[int] = None,
        max_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        if not os.path.isdir(path):
            stat_result = os.stat(path)
            return {
                "size": int(stat_result.st_size),
                "file_count": 1,
                "folder_count": 0,
                "size_status": "ready",
                "count_status": "ready",
                "partial": False,
                "scanned_entries": 1,
            }

        total_size = 0
        file_count = 0
        folder_count = 0
        scanned_entries = 0
        partial = False
        deadline = time.monotonic() + float(max_seconds) if max_seconds and max_seconds > 0 else None
        stack = [path]

        while stack:
            if deadline and time.monotonic() >= deadline:
                partial = True
                break
            current_path = stack.pop()
            try:
                with os.scandir(current_path) as entries:
                    for entry in entries:
                        if self._should_skip_entry(entry.name):
                            continue
                        if max_entries and scanned_entries >= max_entries:
                            partial = True
                            break
                        if deadline and time.monotonic() >= deadline:
                            partial = True
                            break
                        try:
                            stat_result = entry.stat(follow_symlinks=False)
                            is_directory = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        scanned_entries += 1
                        if is_directory:
                            folder_count += 1
                            stack.append(entry.path)
                        else:
                            file_count += 1
                            total_size += int(stat_result.st_size)
            except OSError:
                continue
            if partial:
                break

        status = "partial" if partial else "ready"
        if not partial:
            try:
                root_stat = os.stat(path)
                self._size_cache[os.path.abspath(path)] = {
                    "signature": root_stat.st_mtime_ns,
                    "size": total_size,
                    "updated_at": time.time(),
                }
            except OSError:
                pass
        return {
            "size": total_size,
            "file_count": file_count,
            "folder_count": folder_count,
            "size_status": status,
            "count_status": status,
            "partial": partial,
            "scanned_entries": scanned_entries,
        }

    def _local_delete_preview_from_filesystem(self, path: str) -> dict[str, Any]:
        is_directory = os.path.isdir(path)
        if not is_directory:
            return {
                "need_confirm": True,
                "type": "file",
                "name": os.path.basename(path),
                "path": path,
                "size": os.path.getsize(path),
                "file_count": 1,
                "folder_count": 0,
                "size_status": "ready",
                "size_disabled": False,
                "browse_via_index": False,
            }

        total_size = 0
        file_count = 0
        folder_count = 1
        for root, dirs, files in os.walk(path):
            folder_count += len(dirs)
            for filename in files:
                try:
                    total_size += os.path.getsize(os.path.join(root, filename))
                    file_count += 1
                except OSError:
                    continue
        return {
            "need_confirm": True,
            "type": "folder",
            "name": os.path.basename(path),
            "path": path,
            "size": total_size,
            "file_count": file_count,
            "folder_count": folder_count,
            "size_status": "ready",
            "size_disabled": False,
            "browse_via_index": False,
        }

    def _get_cached_size_only(self, path: str) -> int:
        """仅返回已缓存的目录大小，不触发实时计算（避免列表接口阻塞在慢速网络盘上）。
        缓存未命中时返回 0；后台 ensure_stats 任务会填充缓存。
        """
        cache_key = os.path.abspath(path)
        cached = self._size_cache.get(cache_key)
        return int(cached.get("size", 0)) if cached else 0

    def _get_cached_size_info(self, path: str) -> tuple[Optional[int], str]:
        """读取目录大小缓存，不触发递归统计。"""
        try:
            stat = os.stat(path)
        except OSError:
            return None, "pending"
        cache_key = os.path.abspath(path)
        cached = self._size_cache.get(cache_key)
        if cached and cached.get("signature") == stat.st_mtime_ns:
            return int(cached.get("size", 0)), "ready"
        if cached:
            return int(cached.get("size", 0)), "stale"
        return None, "pending"

    def _cached_path_size(self, path: str) -> int:
        try:
            stat = os.stat(path)
        except OSError:
            return 0

        if not os.path.isdir(path):
            return stat.st_size

        cache_key = os.path.abspath(path)
        current_signature = stat.st_mtime_ns
        cached = self._size_cache.get(cache_key)
        if cached and cached.get("signature") == current_signature:
            return int(cached.get("size", 0))

        size = self._path_size(path)
        self._size_cache[cache_key] = {
            "signature": current_signature,
            "size": size,
            "updated_at": time.time(),
        }
        return size

    def _normalize_library_sort_by(self, sort_by: Optional[str]) -> str:
        return sort_by if sort_by in {"name", "size", "time"} else "size"

    def _normalize_library_sort_order(self, sort_order: Optional[str]) -> str:
        return "asc" if str(sort_order).lower() == "asc" else "desc"

    @staticmethod
    def _natural_name_key(name: Any) -> tuple[tuple[int, Any], ...]:
        raw = str(name or "").casefold()
        parts: list[tuple[int, Any]] = []
        for part in re.split(r"(\d+)", raw):
            if not part:
                continue
            if part.isdigit():
                parts.append((1, int(part), len(part)))
            else:
                parts.append((0, part))
        return tuple(parts)

    def _sort_local_items(self, items: list[dict[str, Any]], sort_by: str, sort_order: str) -> list[dict[str, Any]]:
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        if normalized_sort_by == "name":
            return sorted(
                items,
                key=lambda value: (
                    self._natural_name_key(value.get("name", "")),
                    -float(value.get("_sort_time") or 0),
                    -int(value.get("size") or 0),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_by == "time":
            return sorted(
                items,
                key=lambda value: (
                    float(value.get("_sort_time") or 0),
                    self._natural_name_key(value.get("name", "")),
                    -int(value.get("size") or 0),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_order == "asc":
            return sorted(
                items,
                key=lambda value: (
                    int(value.get("size") or 0),
                    self._natural_name_key(value.get("name", "")),
                    -float(value.get("_sort_time") or 0),
                ),
            )
        return sorted(
            items,
            key=lambda value: (
                -int(value.get("size") or 0),
                self._natural_name_key(value.get("name", "")),
                -float(value.get("_sort_time") or 0),
            ),
        )

    def _sort_remote_page_items(self, items: list[dict[str, Any]], sort_by: str, sort_order: str) -> list[dict[str, Any]]:
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        if normalized_sort_by == "name":
            return sorted(
                items,
                key=lambda value: (
                    self._natural_name_key(value.get("name", "")),
                    -float(value.get("_mtime") or 0),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_by == "time":
            return sorted(
                items,
                key=lambda value: (
                    float(value.get("_mtime") or 0),
                    self._natural_name_key(value.get("name", "")),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_order == "asc":
            return sorted(
                items,
                key=lambda value: (
                    value.get("size") is None,
                    int(value.get("size") or 0),
                    self._natural_name_key(value.get("name", "")),
                    -float(value.get("_mtime") or 0),
                ),
            )
        return sorted(
            items,
            key=lambda value: (
                value.get("size") is None,
                -int(value.get("size") or 0),
                self._natural_name_key(value.get("name", "")),
                -float(value.get("_mtime") or 0),
            ),
        )

    def _should_skip_entry(self, name: str) -> bool:
        return name.startswith("_") or name.startswith(".") or name.lower() in {"#recycle", "@eadir"}

    def _normalize_remote_path(self, path: str) -> str:
        if not path:
            return "/"
        raw = unquote(str(path).strip()).replace("\\", "/")
        normalized = str(PurePosixPath(raw))
        if normalized in {".", ""}:
            return "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _remote_path_is_within_root(self, path: str, root_path: str) -> bool:
        normalized_path = self._normalize_remote_path(path)
        normalized_root = self._normalize_remote_path(root_path)
        if normalized_root == "/":
            return True
        return normalized_path == normalized_root or normalized_path.startswith(f"{normalized_root}/")

    def _resolve_remote_target_path(self, library: LibraryDefinition, current_path: Optional[str]) -> tuple[str, str]:
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        target_path = self._normalize_remote_path(current_path or browse_root)
        if not self._remote_path_is_within_root(target_path, browse_root):
            target_path = browse_root
        return browse_root, target_path

    def _has_illegal_remote_path_segments(self, path: Optional[str]) -> bool:
        raw = unquote(str(path or "").strip()).replace("\\", "/")
        if not raw:
            return False
        if "\x00" in raw:
            return True
        parts = [segment for segment in raw.split("/") if segment]
        return any(segment in {".", ".."} for segment in parts)

    def _validate_remote_new_name(self, new_name: str) -> str:
        normalized = str(new_name or "").strip()
        if not normalized:
            raise ValueError("新名称不能为空")
        if normalized in {".", ".."}:
            raise ValueError("新名称非法")
        if any(char in normalized for char in ('/', '\\', '\x00')):
            raise ValueError("新名称包含非法路径字符")
        return normalized

    def _log_remote_path_resolution(
        self,
        *,
        action: str,
        library: LibraryDefinition,
        incoming_path: Optional[str],
        target_path: str,
        resolution_source: str,
        new_name: Optional[str] = None,
    ) -> None:
        logger.info(
            "远程路径解析: action=%s library_id=%s library_root=%s browse_root=%s incoming_path=%s computed_target_path=%s resolution_source=%s new_name=%s",
            action,
            library.id,
            self._normalize_remote_path(library.root_path or "/"),
            self._normalize_remote_path(library.browse_root_path or library.root_path or "/"),
            incoming_path,
            target_path,
            resolution_source,
            new_name,
        )

    def _resolve_remote_operation_path(
        self,
        library: LibraryDefinition,
        incoming_path: Optional[str],
        *,
        action: str,
        new_name: Optional[str] = None,
    ) -> tuple[str, str]:
        library_root = self._normalize_remote_path(library.root_path or "/")
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        raw_incoming_path = str(incoming_path or "").strip()
        decoded_incoming_path = unquote(raw_incoming_path).strip().replace("\\", "/")

        if self._has_illegal_remote_path_segments(decoded_incoming_path):
            raise ValueError(
                f"{action}失败：incoming path 非法，禁止使用相对路径跳转（library_id={library.id}, incoming_path={incoming_path})"
            )

        if not decoded_incoming_path:
            target_path = browse_root
            resolution_source = "default_browse_root"
        elif decoded_incoming_path.startswith("/"):
            target_path = self._normalize_remote_path(decoded_incoming_path)
            resolution_source = "absolute"
        else:
            target_path = self._normalize_remote_path(str(PurePosixPath(browse_root) / decoded_incoming_path))
            resolution_source = "relative_to_browse_root"

        if not self._remote_path_is_within_root(target_path, browse_root):
            logger.warning(
                "远程路径越界: action=%s library_id=%s library_root=%s browse_root=%s incoming_path=%s computed_target_path=%s new_name=%s",
                action,
                library.id,
                library_root,
                browse_root,
                incoming_path,
                target_path,
                new_name,
            )
            if self._remote_path_is_within_root(target_path, library_root):
                raise PermissionError(
                    f"{action}失败：incoming path 落在 library root 内，但不在当前 browse root 下，疑似 library/root 不匹配 "
                    f"(library_id={library.id}, library_root={library_root}, browse_root={browse_root}, incoming_path={incoming_path}, computed_target_path={target_path})"
                )
            raise PermissionError(
                f"{action}失败：incoming path 与当前库存不匹配，可能传入了其他库的路径 "
                f"(library_id={library.id}, library_root={library_root}, browse_root={browse_root}, incoming_path={incoming_path}, computed_target_path={target_path})"
            )

        self._log_remote_path_resolution(
            action=action,
            library=library,
            incoming_path=incoming_path,
            target_path=target_path,
            resolution_source=resolution_source,
            new_name=new_name,
        )
        return browse_root, target_path

    async def _probe_remote_path(self, client: SynologyFileStationClient, path: str) -> dict[str, Any]:
        normalized_path = self._normalize_remote_path(path)
        try:
            info = await client.stat(normalized_path)
            return {
                "exists": True,
                "path": normalized_path,
                "item": self._first_remote_info_item(info),
                "error": None,
            }
        except Exception as exc:
            try:
                if normalized_path == "/":
                    data = await client.list_share(offset=0, limit=1, sort_by="name", sort_direction="asc")
                    sample_items = data.get("shares") or data.get("files") or []
                else:
                    data = await client.list(normalized_path, offset=0, limit=1, sort_by="name", sort_direction="asc")
                    sample_items = data.get("files") or []
                return {
                    "exists": True,
                    "path": normalized_path,
                    "item": sample_items[0] if sample_items else {"path": normalized_path, "isdir": True},
                    "error": f"stat_failed_then_list_succeeded: {exc}",
                }
            except Exception as list_exc:
                return {
                    "exists": False,
                    "path": normalized_path,
                    "item": None,
                    "error": f"stat={exc}; list={list_exc}",
                }

    async def _remote_child_visible(self, client: SynologyFileStationClient, parent_path: str, child_name: str) -> Optional[bool]:
        try:
            children = await self._list_remote_directory(client, parent_path)
        except Exception:
            return None
        target_name = str(child_name or "")
        return any(str(child.get("name") or "") == target_name for child in children)

    async def _raise_remote_code_119_context(
        self,
        *,
        client: SynologyFileStationClient,
        library: LibraryDefinition,
        action: str,
        incoming_path: Optional[str],
        target_path: str,
        original_error: Exception,
        new_name: Optional[str] = None,
    ) -> None:
        library_root = self._normalize_remote_path(library.root_path or "/")
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        parent_path = self._remote_parent_path(target_path)
        root_probe = await self._probe_remote_path(client, browse_root)
        parent_probe = root_probe if parent_path == browse_root else await self._probe_remote_path(client, parent_path)
        child_visible = None
        if parent_probe.get("exists") and parent_path != target_path:
            child_visible = await self._remote_child_visible(client, parent_path, PurePosixPath(target_path).name)

        logger.warning(
            "远程路径诊断(code=119): action=%s library_id=%s library_root=%s browse_root=%s incoming_path=%s computed_target_path=%s parent_path=%s new_name=%s root_exists=%s parent_exists=%s child_visible=%s original_error=%s",
            action,
            library.id,
            library_root,
            browse_root,
            incoming_path,
            target_path,
            parent_path,
            new_name,
            root_probe.get("exists"),
            parent_probe.get("exists"),
            child_visible,
            original_error,
        )

        if not root_probe.get("exists"):
            raise PermissionError(
                f"{action}失败：当前库存根目录不可访问，可能是 library/root 配置错误，或当前账号无权访问 "
                f"(library_id={library.id}, library_root={library_root}, browse_root={browse_root}, incoming_path={incoming_path}, computed_target_path={target_path})"
            )
        if parent_path != target_path and not parent_probe.get("exists"):
            raise FileNotFoundError(
                f"{action}失败：目标父目录不存在或不可访问，可能是路径已被改名/删除，或 library/root 不匹配 "
                f"(library_id={library.id}, incoming_path={incoming_path}, computed_target_path={target_path}, parent_path={parent_path})"
            )
        if child_visible is False:
            raise FileNotFoundError(
                f"{action}失败：目标路径不存在，或操作前已被改名/删除 "
                f"(library_id={library.id}, incoming_path={incoming_path}, computed_target_path={target_path})"
            )
        if child_visible is True:
            raise PermissionError(
                f"{action}失败：目标路径已定位，但当前账号可能无权访问，或路径/名称包含群晖不接受的字符 "
                f"(library_id={library.id}, incoming_path={incoming_path}, computed_target_path={target_path}, new_name={new_name})"
            )
        raise RuntimeError(
            f"{action}失败：群晖返回 code 119，无法确认是路径不存在、路径非法还是权限不足 "
            f"(library_id={library.id}, library_root={library_root}, browse_root={browse_root}, incoming_path={incoming_path}, computed_target_path={target_path}, new_name={new_name})"
        )

    def _remote_parent_path(self, path: str) -> str:
        normalized = self._normalize_remote_path(path)
        if normalized == "/":
            return "/"
        parent = str(PurePosixPath(normalized).parent)
        return "/" if parent in {".", ""} else parent

    async def _list_remote_directory(self, client: SynologyFileStationClient, folder_path: str) -> list[dict[str, Any]]:
        folder_path = self._normalize_remote_path(folder_path)
        chunk_size = 3000
        offset = 0
        items: list[dict[str, Any]] = []
        while True:
            if folder_path == "/":
                data = await client.list_share(offset=offset, limit=chunk_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("shares") or data.get("files") or []
            else:
                data = await client.list(folder_path, offset=offset, limit=chunk_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("files") or []
            items.extend(raw_items)
            total = int(data.get("total", len(items)) or len(items))
            if not raw_items or len(items) >= total:
                break
            offset += len(raw_items)
        return items

    async def _list_remote_directory_recursive(self, client: SynologyFileStationClient, folder_path: str) -> list[dict[str, Any]]:
        root_path = self._normalize_remote_path(folder_path)
        queue: list[str] = [root_path]
        visited: set[str] = set()
        items: list[dict[str, Any]] = []

        while queue:
            current_path = self._normalize_remote_path(queue.pop(0))
            if current_path in visited:
                continue
            visited.add(current_path)

            try:
                children = await self._list_remote_directory(client, current_path)
            except Exception as exc:
                logger.warning("远程递归列目录失败: path=%s err=%s", current_path, sanitize_text_for_log(exc))
                continue

            for child in children:
                name = child.get("name") or ""
                if self._should_skip_entry(name):
                    continue
                child_path = self._normalize_remote_path(child.get("path") or child.get("real_path") or name)
                items.append(child)
                if child.get("isdir", False) and child_path not in visited:
                    queue.append(child_path)

        logger.info("远程递归列目录完成: root=%s visited=%s items=%s", root_path, len(visited), len(items))
        return items

    def _first_remote_info_item(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        files = data.get("files") or []
        return files[0] if files else None

    async def _remote_collect_stats(self, client: SynologyFileStationClient, folder_path: str) -> tuple[int, int]:
        total_size = 0
        folder_count = 0
        for item in await self._list_remote_directory(client, folder_path):
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            additional = item.get("additional", {}) or {}
            child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
            timestamp = additional.get("time", {}).get("mtime")
            if item.get("isdir", False):
                folder_count += 1
                child_folders, child_size = await self._remote_collect_stats(client, child_path)
                folder_count += child_folders
                total_size += child_size
                self._size_cache[f"remote::{child_path}"] = {
                    "signature": timestamp,
                    "size": child_size,
                    "updated_at": time.time(),
                }
            else:
                total_size += int(additional.get("size") or 0)
        return folder_count, total_size

    async def _remote_collect_folder_count(self, client: SynologyFileStationClient, folder_path: str) -> int:
        total = 0
        for item in await self._list_remote_directory(client, folder_path):
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            if item.get("isdir", False):
                child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
                total += 1
                total += await self._remote_collect_folder_count(client, child_path)
        return total

    async def _remote_folder_summary(
        self,
        client: SynologyFileStationClient,
        folder_path: str,
        *,
        max_entries: Optional[int] = None,
        max_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        normalized_path = self._normalize_remote_path(folder_path)
        total_size = 0
        file_count = 0
        folder_count = 0
        scanned_entries = 0
        partial = False
        deadline = time.monotonic() + float(max_seconds) if max_seconds and max_seconds > 0 else None
        queue: list[str] = [normalized_path]
        visited: set[str] = set()

        while queue:
            if deadline and time.monotonic() >= deadline:
                partial = True
                break
            current_path = self._normalize_remote_path(queue.pop(0))
            if current_path in visited:
                continue
            visited.add(current_path)
            try:
                children = await self._list_remote_directory(client, current_path)
            except Exception as exc:
                logger.warning("远程目录摘要读取失败: path=%s err=%s", current_path, sanitize_text_for_log(exc))
                continue

            for child in children:
                name = child.get("name") or ""
                if self._should_skip_entry(name):
                    continue
                if max_entries and scanned_entries >= max_entries:
                    partial = True
                    break
                if deadline and time.monotonic() >= deadline:
                    partial = True
                    break
                additional = child.get("additional", {}) or {}
                child_path = self._normalize_remote_path(child.get("path") or child.get("real_path") or "")
                scanned_entries += 1
                if child.get("isdir", False):
                    folder_count += 1
                    if child_path and child_path not in visited:
                        queue.append(child_path)
                else:
                    file_count += 1
                    total_size += int(additional.get("size") or child.get("size") or 0)
            if partial:
                break

        status = "partial" if partial else "ready"
        if not partial:
            self._size_cache[f"remote::{normalized_path}"] = {
                "signature": None,
                "size": total_size,
                "updated_at": time.time(),
            }
        return {
            "size": total_size,
            "file_count": file_count,
            "folder_count": folder_count,
            "size_status": status,
            "count_status": status,
            "partial": partial,
            "scanned_entries": scanned_entries,
        }

    def _update_remote_stats_progress(
        self,
        library: LibraryDefinition,
        folder_count: int,
        total_size: int,
        completed: int,
        total: int,
        last_completed_at: Optional[float],
        current_item: Optional[str] = None,
        warning_count: int = 0,
        last_error: Optional[str] = None,
    ):
        progress_percent = round((completed / total) * 100, 2) if total else 100.0
        self._stats_cache[library.id] = {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "pending",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
            "progress_done": completed,
            "progress_total": total,
            "progress_percent": progress_percent,
            "current_item": current_item,
            "warning_count": warning_count,
            "last_error": last_error,
            "health": self._health_for_library(library, float(self.load_config()["health_warning_free_gb"])),
            "last_completed_at": last_completed_at,
            "updated_at": time.time(),
        }
        self._persist_stats()

    async def _remote_path_size(
        self,
        client: SynologyFileStationClient,
        path: str,
        is_directory: bool,
        modified_ts: Optional[int] = None,
        initial_size: Optional[int] = None,
        max_wait_seconds: Optional[int] = None,
    ) -> int:
        normalized_path = self._normalize_remote_path(path)
        cache_key = f"remote::{normalized_path}"
        cached = self._size_cache.get(cache_key)
        if cached and modified_ts is not None and cached.get("signature") == modified_ts:
            return int(cached.get("size", 0))

        if is_directory:
            start_data = await client.start_dir_size(normalized_path)
            taskid = str(start_data.get("taskid") or start_data.get("task_id") or "")
            size = 0
            if taskid:
                wait_seconds = max_wait_seconds or max(int(client.config.timeout), 30)
                deadline = time.time() + wait_seconds
                while time.time() < deadline:
                    status_data = await client.dir_size_status(taskid)
                    size = self._extract_dir_size_value(status_data)
                    if self._dir_size_finished(status_data):
                        break
                    await asyncio.sleep(0.5)
        else:
            size = int(initial_size or 0)
            if not size:
                info = await client.stat(normalized_path)
                item = self._first_remote_info_item(info) or {}
                additional = item.get("additional", {}) or {}
                size = int(additional.get("size") or item.get("size") or 0)

        self._size_cache[cache_key] = {
            "signature": modified_ts,
            "size": size,
            "updated_at": time.time(),
        }
        return size

    def _dir_size_finished(self, data: dict[str, Any]) -> bool:
        for key in ("finished", "is_finished", "complete"):
            value = data.get(key)
            if isinstance(value, bool):
                return value
        if data.get("status") in {"finished", "done", "completed"}:
            return True
        if data.get("progress") == 100:
            return True
        return False

    def _extract_dir_size_value(self, data: dict[str, Any]) -> int:
        for key in ("total_size", "size"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        for key in ("result", "results", "files"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        nested = self._extract_dir_size_value(item)
                        if nested:
                            return nested
            elif isinstance(value, dict):
                nested = self._extract_dir_size_value(value)
                if nested:
                    return nested
        return 0

    def _get_remote_cached_size(self, path: str, modified_ts: Optional[int], is_directory: bool) -> tuple[Optional[int], str]:
        if not is_directory:
            return None, "ready"
        cache_key = f"remote::{self._normalize_remote_path(path)}"
        cached = self._size_cache.get(cache_key)
        if cached and modified_ts is not None and cached.get("signature") == modified_ts:
            return int(cached.get("size", 0)), "ready"
        if cached:
            return int(cached.get("size", 0)), "stale"
        return None, "pending"

    def _ensure_remote_size_task(self, library: LibraryDefinition, path: str, modified_ts: Optional[int]):
        cache_key = f"remote::{self._normalize_remote_path(path)}"
        running = self._remote_size_tasks.get(cache_key)
        if running and not running.done():
            return
        task = asyncio.create_task(self._refresh_remote_path_size(library, path, modified_ts))
        self._remote_size_tasks[cache_key] = task
        # task 完成后自动 pop，避免长期运行下 dict 只增不减
        task.add_done_callback(lambda _t: self._remote_size_tasks.pop(cache_key, None))

    async def _refresh_remote_path_size(self, library: LibraryDefinition, path: str, modified_ts: Optional[int]):
        try:
            if not library.synology:
                return
            client = self.get_cached_synology_client(library.synology)
            await self._remote_path_size(client, path, True, modified_ts)
        except Exception:
            pass

    async def _remote_delete_preview(
        self,
        client: SynologyFileStationClient,
        path: str,
        library: Optional[LibraryDefinition] = None,
    ) -> dict[str, Any]:
        normalized_path = self._normalize_remote_path(path)
        if library is not None:
            indexed_preview = self._delete_preview_via_index(library, normalized_path)
            if indexed_preview is not None:
                return indexed_preview
        info = await client.stat(normalized_path)
        item = self._first_remote_info_item(info)
        if not item:
            raise FileNotFoundError("目标路径不存在")
        is_directory = bool(item.get("isdir", False))
        return {
            "type": "folder" if is_directory else "file",
            "name": item.get("name") or PurePosixPath(normalized_path).name,
            "path": normalized_path,
            "size": None,
            "folder_count": 0,
            "size_disabled": True,
        }

    def _apply_remote_stats_deletion(
        self,
        library: LibraryDefinition,
        deleted_bytes: int = 0,
        deleted_folder_count: int = 0,
    ) -> None:
        if library.type != "synology_filestation":
            return

        cached = self._stats_cache.get(library.id)
        if not cached or cached.get("status") == "pending":
            return

        next_total_size = max(0, int(cached.get("total_size_bytes", 0) or 0) - max(0, int(deleted_bytes or 0)))
        next_folder_count = max(0, int(cached.get("folder_count", 0) or 0) - max(0, int(deleted_folder_count or 0)))

        cached["total_size_bytes"] = next_total_size
        cached["total_size_gb"] = _gb(next_total_size)
        cached["folder_count"] = next_folder_count
        cached["updated_at"] = time.time()
        self._stats_cache[library.id] = cached
        self._persist_stats()

    def _local_top_level_delta(self, library: LibraryDefinition, path: str, delta: int) -> None:
        # 顶层目录数量发生变化 ⇒ 本地搜索缓存里的 keyword→matches 可能不再准确，主动失效
        self._invalidate_local_browse_caches(library.id)
        cached = self._stats_cache.get(library.id)
        if library.type != "local" or not cached or cached.get("status") == "pending":
            return
        if cached.get("scan_mode") != "manual_persisted" and not cached.get("last_completed_at"):
            return
        try:
            root = os.path.abspath(library.browse_root_path or library.root_path)
            target = os.path.abspath(path)
            parent = os.path.abspath(os.path.dirname(target))
            if os.path.normcase(parent) != os.path.normcase(root):
                return
        except Exception:
            return
        next_folder_count = max(0, int(cached.get("folder_count", 0) or 0) + int(delta or 0))
        cached["folder_count"] = next_folder_count
        cached["updated_at"] = time.time()
        self._stats_cache[library.id] = cached
        self._persist_stats()

    async def _list_remote_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
        page_cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

        browse_root, target_path = self._resolve_remote_target_path(library, current_path)
        search_lower = search.lower().strip()
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        if not search_lower:
            index_parent = self._index_parent_path_for_target(library, target_path)
            if index_parent is not None:
                indexed_result = self._list_files_via_index(
                    library,
                    page=page,
                    page_size=page_size,
                    current_path=target_path,
                    browse_root=browse_root,
                    parent_path=index_parent,
                    sort_by=normalized_sort_by,
                    sort_order=normalized_sort_order,
                    page_cursor=page_cursor,
                )
                if indexed_result is not None:
                    return indexed_result

        client = self.get_cached_synology_client(library.synology)
        remote_sort_by = "name" if normalized_sort_by == "name" else "mtime"
        remote_sort_direction = "asc" if normalized_sort_order == "asc" else "desc"
        if search_lower:
            raw_items = await self._list_remote_directory(client, target_path)
            items_with_index = list(enumerate(raw_items))
        else:
            offset = max(0, (page - 1) * page_size)
            if target_path == "/":
                data = await client.list_share(offset=offset, limit=page_size, sort_by=remote_sort_by, sort_direction=remote_sort_direction)
                raw_items = data.get("shares") or data.get("files") or []
            else:
                data = await client.list(target_path, offset=offset, limit=page_size, sort_by=remote_sort_by, sort_direction=remote_sort_direction)
                raw_items = data.get("files") or []
            items_with_index = list(enumerate(raw_items, start=offset))
        files = []
        for index, item in items_with_index:
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            rjcode = self._extract_rjcode(name)
            if search_lower and search_lower not in name.lower() and search_lower not in (rjcode or "").lower():
                continue
            additional = item.get("additional", {}) or {}
            timestamp = additional.get("time", {}).get("mtime", int(time.time()))
            files.append(
                {
                    "id": f"{library.id}:{index}",
                    "name": name,
                    "path": self._normalize_remote_path(item.get("path") or item.get("real_path") or name),
                    "rjcode": rjcode,
                    "size": additional.get("size"),
                    "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "unzip_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "is_directory": item.get("isdir", True),
                    "library_id": library.id,
                    "library_name": library.name,
                    "_mtime": timestamp,
                }
            )
        if search_lower:
            files = self._sort_remote_page_items(files, normalized_sort_by, normalized_sort_order)
            total = len(files)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_items = files[start:end]
        else:
            total = int(data.get("total", len(files)) or len(files))
            page_items = files
        for item in page_items:
            is_directory = bool(item["is_directory"])
            if is_directory:
                item["size"] = None
                item["size_status"] = "disabled"
            else:
                item["size"] = int(item.get("size") or 0)
                item["size_status"] = "ready"
        if normalized_sort_by == "size" or search_lower:
            page_items = self._sort_remote_page_items(page_items, normalized_sort_by, normalized_sort_order)
        for item in page_items:
            item.pop("_mtime", None)
        return {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if target_path == browse_root else self._remote_parent_path(target_path),
        }

    def _folder_content_item_from_index(
        self,
        library: LibraryDefinition,
        entry,
        *,
        item_id: int,
        parent_relative_path: str,
        descendant_folder_count: Optional[int],
    ) -> dict[str, Any]:
        is_directory = entry.entry_type == "dir"
        relative_path = self._index_relative_path_under_target(entry.relative_path, parent_relative_path)
        try:
            modified_time = datetime.fromtimestamp((entry.mtime or 0) / 1000.0).isoformat() if entry.mtime else None
        except (OSError, ValueError, OverflowError):
            modified_time = None
        file_count = int(entry.file_count or 0) if is_directory else 1
        folder_count = int(descendant_folder_count or 0) if descendant_folder_count is not None else None
        size_value = int(entry.size or 0)
        has_children = bool(is_directory and (file_count > 0 or int(folder_count or 0) > 0))
        return {
            "id": f"{library.id}:content:index:{item_id}",
            "name": entry.name,
            "path": entry.absolute_path,
            "relative_path": relative_path,
            "size": size_value,
            "size_status": "ready",
            "modified_time": modified_time,
            "type": "dir" if is_directory else "file",
            "is_directory": is_directory,
            "has_children": has_children,
            "children_loaded": False if has_children else True,
            "file_count": file_count,
            "folder_count": folder_count if is_directory else 0,
            "folder_count_status": "ready" if (not is_directory or descendant_folder_count is not None) else "lazy",
            "browse_via_index": True,
        }

    def _index_relative_path_under_target(self, entry_relative_path: str, target_relative_path: str) -> str:
        entry_relative = str(entry_relative_path or "").strip("/")
        target_relative = str(target_relative_path or "").strip("/")
        if target_relative and entry_relative.startswith(f"{target_relative}/"):
            return entry_relative[len(target_relative) + 1:]
        if entry_relative == target_relative:
            return ""
        return entry_relative

    def _index_relative_path_has_skipped_part(self, relative_path: str) -> bool:
        parts = [part for part in str(relative_path or "").replace("\\", "/").split("/") if part]
        return any(self._should_skip_entry(part) for part in parts)

    def _folder_contents_via_index(
        self,
        library: LibraryDefinition,
        path: str,
        *,
        recursive: bool,
        include_dirs: bool = False,
    ) -> Optional[dict[str, Any]]:
        if not self._library_uses_inventory_index(library):
            return None
        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
            has_snapshot = (
                service.has_usable_snapshot(library.id)
                if hasattr(service, "has_usable_snapshot")
                else service.is_ready(library.id)
            )
            if not has_snapshot:
                return None
            if (
                library.type == "local"
                and hasattr(service, "has_library_entries")
                and not service.has_library_entries(library.id)
            ):
                return None
            library_root = os.path.abspath(library.root_path)
            target_path = os.path.abspath(path)
            if not self._local_path_is_within_root(target_path, library_root):
                raise PermissionError("只能查看当前库存根目录内的文件夹")
            if not os.path.isdir(target_path):
                raise FileNotFoundError("目标文件夹不存在")
            folder_name = os.path.basename(target_path)

            parent_relative_path = self._index_parent_path_for_target(library, target_path)
            if parent_relative_path is None:
                raise PermissionError("只能查看当前库存根目录内的文件夹")

            target_entry = service.get_entry(library.id, parent_relative_path) if parent_relative_path else None
            if parent_relative_path and (not target_entry or target_entry.entry_type != "dir"):
                return None
            target_entry_stale = False
            if target_entry and library.type == "local":
                target_entries, target_stale_paths = self._validate_local_index_entries_for_read(
                    library,
                    [target_entry],
                    return_stale_paths=True,
                )
                if not target_entries:
                    return None
                target_entry = target_entries[0]
                target_entry_stale = str(getattr(target_entry, "relative_path", "") or "") in target_stale_paths

            if recursive:
                requested_entry_type = None if include_dirs else "file"
                raw_entries = []
                for entry in service.list_subtree_entries(
                        library.id,
                        parent_relative_path,
                        include_self=False,
                        entry_type=requested_entry_type,
                ):
                    relative_under_target = self._index_relative_path_under_target(
                        entry.relative_path,
                        parent_relative_path,
                    )
                    if not relative_under_target:
                        continue
                    if self._index_relative_path_has_skipped_part(relative_under_target):
                        continue
                    raw_entries.append(entry)
                if include_dirs:
                    entries = raw_entries
                    stale_relative_paths = set()
                else:
                    entries, stale_relative_paths = self._validate_local_index_entries_for_read(
                        library,
                        raw_entries,
                        return_stale_paths=True,
                    )
                entries.sort(key=lambda entry: self._index_relative_path_under_target(
                    getattr(entry, "relative_path", "") or "",
                    parent_relative_path,
                ))
                items = []
                for index, entry in enumerate(entries):
                    item = self._folder_content_item_from_index(
                        library,
                        entry,
                        item_id=index,
                        parent_relative_path=parent_relative_path,
                        descendant_folder_count=None if getattr(entry, "entry_type", "") == "dir" else 0,
                    )
                    item["children_loaded"] = True
                    if entry.relative_path in stale_relative_paths:
                        item["size_status"] = "stale"
                        item["index_refresh_pending"] = True
                    items.append(item)
                file_entries = [entry for entry in entries if getattr(entry, "entry_type", "") == "file"]
                dir_entries = [entry for entry in entries if getattr(entry, "entry_type", "") == "dir"]
                if target_entry and not target_entry_stale:
                    total_size = int(target_entry.size or 0)
                    total_files = int(target_entry.file_count or 0)
                else:
                    total_size = sum(int(entry.size or 0) for entry in file_entries)
                    total_files = len(file_entries)
                result = {
                    "folder_name": folder_name,
                    "folder_path": target_path,
                    "total_files": total_files,
                    "total_items": len(items),
                    "total_size": total_size,
                    "total_size_bytes": total_size,
                    "total_folder_count": len(dir_entries),
                    "recursive": True,
                    "browse_via_index": True,
                    "include_dirs": bool(include_dirs),
                    "items": items,
                }
                self._append_stats_log(library, "INFO", f"文件树索引递归读取 path={target_path} total={len(items)}")
                return result

            payload = service.list_children_page(
                library.id,
                parent_relative_path,
                sort_by="name",
                sort_order="asc",
                offset=0,
                limit=None,
            )
            entries, stale_relative_paths = self._validate_local_index_entries_for_read(
                library,
                [
                    entry for entry in list(payload.get("entries") or [])
                    if not self._should_skip_entry(getattr(entry, "name", ""))
                ],
                return_stale_paths=True,
            )
            entries.sort(key=lambda entry: (
                0 if entry.entry_type == "dir" else 1,
                self._natural_name_key(getattr(entry, "name", "") or ""),
                getattr(entry, "relative_path", "") or "",
            ))

            dir_counts = {}
            dir_relative_paths = [
                str(getattr(entry, "relative_path", "") or "")
                for entry in entries
                if getattr(entry, "entry_type", "") == "dir"
            ]
            if dir_relative_paths:
                dir_counts = service.count_descendant_dirs_many(library.id, dir_relative_paths)

            items = []
            for index, entry in enumerate(entries):
                item = self._folder_content_item_from_index(
                    library,
                    entry,
                    item_id=index,
                    parent_relative_path=parent_relative_path,
                    descendant_folder_count=dir_counts.get(str(getattr(entry, "relative_path", "") or ""), 0),
                )
                if entry.entry_type == "dir":
                    item["folder_count_status"] = "ready"
                if entry.relative_path in stale_relative_paths:
                    item["size_status"] = "stale"
                    item["index_refresh_pending"] = True
                items.append(item)

            if target_entry:
                if target_entry_stale:
                    total_size = sum(int(entry.size or 0) for entry in entries)
                    total_files = sum(
                        int(entry.file_count or 0) if entry.entry_type == "dir" else 1
                        for entry in entries
                    )
                else:
                    total_size = int(target_entry.size or 0)
                    total_files = int(target_entry.file_count or 0)
                total_folders = None
            else:
                status = service.get_status(library.id)
                total_size = sum(int(entry.size or 0) for entry in entries)
                total_files = sum(
                    int(entry.file_count or 0) if entry.entry_type == "dir" else 1
                    for entry in entries
                )
                total_folders = int(getattr(status, "folder_count", 0) or 0) if status else sum(
                    1 for entry in entries if entry.entry_type == "dir"
                )

            result = {
                "folder_name": folder_name,
                "folder_path": target_path,
                "total_files": total_files,
                "total_items": len(items),
                "total_size": total_size,
                "total_size_bytes": total_size,
                "total_folder_count": total_folders,
                "recursive": False,
                "browse_via_index": True,
                "items": items,
            }
            self._append_stats_log(library, "INFO", f"文件树索引浅层读取 path={target_path} total={len(items)}")
            return result
        except (FileNotFoundError, PermissionError, ValueError):
            raise
        except Exception:
            logger.warning(
                "文件树索引浅层读取异常转 fallback: lib=%s path=%s",
                library.id,
                path,
                exc_info=True,
            )
            return None

    def _index_entry_modified_time(self, entry) -> Optional[str]:
        try:
            return datetime.fromtimestamp((entry.mtime or 0) / 1000.0).isoformat() if entry.mtime else None
        except (OSError, ValueError, OverflowError):
            return None

    def _index_service_if_ready(self, library: LibraryDefinition):
        if not self._library_uses_inventory_index(library):
            return None
        try:
            from .library_index import get_library_index_service

            service = get_library_index_service()
            return service if self._index_has_usable_snapshot(service, library.id) else None
        except Exception:
            logger.warning("库存索引状态检查失败: lib=%s", library.id, exc_info=True)
            return None

    def folder_size_summary_via_index(
        self,
        library: LibraryDefinition,
        path: str,
        *,
        include_counts: bool = False,
    ) -> Optional[dict[str, Any]]:
        service = self._index_service_if_ready(library)
        if service is None:
            return None
        try:
            target_path, relative_path, _name = self._index_target_for_operation(
                library,
                path,
                action="计算文件夹大小",
            )
            entry = service.get_entry(library.id, relative_path) if relative_path else None
            if relative_path and not entry:
                return None
            stale = False
            directory_snapshot_refresh_pending = False
            if entry and library.type == "local":
                checked_entries, stale_paths = self._validate_local_index_entries_for_read(
                    library,
                    [entry],
                    return_stale_paths=True,
                )
                if not checked_entries:
                    raise FileNotFoundError("目标路径不存在")
                entry = checked_entries[0]
                stale = entry.relative_path in stale_paths
                if entry.entry_type == "dir":
                    # 目录自身 mtime 不能代表整棵子树：子文件内容修改时父目录 mtime
                    # 可能不变。读路径仍用索引秒回，但明确告诉前端这是快照值，
                    # 并把子树刷新排到索引后台队列，避免同步 os.walk 卡住业务接口。
                    directory_snapshot_refresh_pending = True
                    self._enqueue_index_read_repair_upserts(library, [target_path])
            elif library.type == "local" and os.path.isdir(target_path):
                directory_snapshot_refresh_pending = True
                self._enqueue_index_read_repair_upserts(library, [target_path])
            if entry and entry.entry_type == "file":
                result: dict[str, Any] = {
                    "size": int(entry.size or 0),
                    "size_status": "stale" if stale else "ready",
                    "browse_via_index": True,
                }
                if stale:
                    result["index_refresh_pending"] = True
                if include_counts:
                    result.update({
                        "file_count": 1,
                        "folder_count": 0,
                        "count_status": "ready",
                        "partial": False,
                        "scanned_entries": 1,
                    })
                return result
            if entry:
                size = int(entry.size or 0)
                file_count = int(entry.file_count or 0)
                folder_count = None
            else:
                stats = service.get_library_stats(library.id)
                size = int(stats.get("total_size_bytes") or 0)
                file_count = sum(
                    int(child.file_count or 0) if child.entry_type == "dir" else 1
                    for child in service.list_children(library.id, "", entry_type=None)
                )
                folder_count = int(stats.get("folder_count") or 0)
            result = {
                "size": size,
                "size_status": "stale" if stale or directory_snapshot_refresh_pending else "ready",
                "browse_via_index": True,
            }
            if stale or directory_snapshot_refresh_pending:
                result["index_refresh_pending"] = True
            if include_counts:
                result.update({
                    "file_count": file_count,
                    "folder_count": folder_count,
                    "count_status": "lazy" if folder_count is None else (
                        "stale" if stale or directory_snapshot_refresh_pending else "ready"
                    ),
                    "partial": False,
                    "scanned_entries": file_count + int(folder_count or 0),
                })
            self._append_stats_log(
                library,
                "INFO",
                f"目录大小读取索引 path={target_path} size={size} counts={bool(include_counts)}",
            )
            return result
        except (FileNotFoundError, PermissionError, ValueError):
            raise
        except Exception:
            logger.warning("目录大小索引读取异常转 fallback: lib=%s path=%s", library.id, path, exc_info=True)
            return None

    def _index_target_for_operation(
        self,
        library: LibraryDefinition,
        path: str,
        *,
        action: str,
        require_local_dir: bool = False,
    ) -> tuple[str, str, str]:
        if library.type == "synology_filestation":
            _browse_root, target_path = self._resolve_remote_operation_path(library, path, action=action)
            relative_path = self._index_parent_path_for_target(library, target_path)
            folder_name = PurePosixPath(target_path).name or target_path
        else:
            self._assert_local_path_in_library(library, path)
            target_path = os.path.abspath(path)
            if require_local_dir and not os.path.isdir(target_path):
                raise FileNotFoundError("目标文件夹不存在")
            relative_path = self._index_parent_path_for_target(library, target_path)
            folder_name = os.path.basename(target_path)
        if relative_path is None:
            raise PermissionError("目标路径超出当前库存根目录")
        return target_path, relative_path, folder_name

    def _delete_preview_via_index(self, library: LibraryDefinition, path: str) -> Optional[dict[str, Any]]:
        service = self._index_service_if_ready(library)
        if service is None:
            return None
        try:
            target_path, relative_path, name = self._index_target_for_operation(
                library,
                path,
                action="删除预检",
            )
            if library.type == "local" and not os.path.exists(target_path):
                raise FileNotFoundError("目标路径不存在")
            if not relative_path:
                return None
            entry = service.get_entry(library.id, relative_path)
            if not entry:
                return None
            if library.type == "local":
                checked_entries, stale_paths = self._validate_local_index_entries_for_read(
                    library,
                    [entry],
                    return_stale_paths=True,
                )
                if not checked_entries:
                    raise FileNotFoundError("目标路径不存在")
                entry = checked_entries[0]
            is_directory = entry.entry_type == "dir"
            descendant_folder_count = 0
            if is_directory:
                descendant_folder_count = int(
                    service.count_descendant_dirs_many(library.id, [relative_path]).get(relative_path, 0)
                    or 0
                )
            is_stale = False
            if library.type == "local":
                try:
                    stat_result = os.stat(target_path)
                    is_stale = self._index_entry_stat_is_stale(entry, stat_result)
                except OSError:
                    is_stale = False
            if library.type == "local" and is_directory:
                is_stale = True
                self._enqueue_index_read_repair_upserts(library, [target_path])
            return {
                "need_confirm": True,
                "type": "folder" if is_directory else "file",
                "name": entry.name or name,
                "path": target_path,
                "size": int(entry.size or 0),
                "file_count": int(entry.file_count or (0 if is_directory else 1)),
                "folder_count": (1 + descendant_folder_count) if is_directory else 0,
                "size_status": "stale" if is_stale else "ready",
                "size_disabled": False,
                "index_refresh_pending": bool(is_stale),
                "browse_via_index": True,
            }
        except (FileNotFoundError, PermissionError, ValueError):
            raise
        except Exception:
            logger.warning("删除预检索引路径异常转 fallback: lib=%s path=%s", library.id, path, exc_info=True)
            return None

    def _batch_delete_preview_via_index(self, library: LibraryDefinition, paths: list[str]) -> Optional[dict[str, Any]]:
        service = self._index_service_if_ready(library)
        if service is None:
            return None
        try:
            previews: list[dict[str, Any]] = []
            for path in paths:
                preview = self._delete_preview_via_index(library, path)
                if preview is None:
                    return None
                previews.append(preview)

            roots: list[dict[str, Any]] = []
            root_paths: list[str] = []
            for preview in sorted(previews, key=lambda item: len(str(item.get("path") or ""))):
                normalized_path = str(preview.get("path") or "").replace("\\", "/").rstrip("/")
                if any(normalized_path == root or normalized_path.startswith(f"{root}/") for root in root_paths):
                    continue
                root_paths.append(normalized_path)
                roots.append(preview)
            has_stale_root = any(str(item.get("size_status") or "") == "stale" for item in roots)

            return {
                "need_confirm": True,
                "total_count": len(paths),
                "total_size": sum(int(item.get("size") or 0) for item in roots),
                "total_file_count": sum(int(item.get("file_count") or 0) for item in roots),
                "total_folder_count": sum(int(item.get("folder_count") or 0) for item in roots),
                "size_disabled": False,
                "size_status": "stale" if has_stale_root else "ready",
                "index_refresh_pending": has_stale_root,
                "browse_via_index": True,
            }
        except (FileNotFoundError, PermissionError, ValueError):
            raise
        except Exception:
            logger.warning("批删预检索引路径异常转 fallback: lib=%s", library.id, exc_info=True)
            return None

    def _filter_delete_preview_via_index(
        self,
        library: LibraryDefinition,
        path: str,
        active_rules: list[dict[str, str]],
    ) -> Optional[dict[str, Any]]:
        service = self._index_service_if_ready(library)
        if service is None:
            return None
        try:
            target_path, target_relative_path, folder_name = self._index_target_for_operation(
                library,
                path,
                action="删除过滤预审",
                require_local_dir=library.type == "local",
            )
            if target_relative_path:
                target_entry = service.get_entry(library.id, target_relative_path)
                if not target_entry or target_entry.entry_type != "dir":
                    return None
            entries = service.list_subtree_entries(
                library.id,
                target_relative_path,
                include_self=False,
            )
            entries, stale_relative_paths = self._validate_local_index_entries_for_read(
                library,
                entries,
                return_stale_paths=True,
            )
            entries.sort(key=lambda entry: (
                int(entry.depth or 0),
                str(entry.relative_path or "").lower(),
                0 if entry.entry_type == "dir" else 1,
            ))

            preview_items: list[dict[str, Any]] = []
            selected_count = 0
            selected_size = 0
            covered_roots: list[tuple[str, str]] = []

            def relative_to_target(entry_relative_path: str) -> str:
                current = str(entry_relative_path or "").strip("/")
                if target_relative_path and current.startswith(f"{target_relative_path}/"):
                    return current[len(target_relative_path) + 1:]
                return current

            for entry in entries:
                name = str(entry.name or "")
                if self._should_skip_filter_preview_name(name):
                    continue
                entry_relative = str(entry.relative_path or "").strip("/")
                item_relative = relative_to_target(entry_relative)
                covered_by = ""
                for covered_relative, covered_path in covered_roots:
                    if entry_relative == covered_relative or entry_relative.startswith(f"{covered_relative}/"):
                        covered_by = covered_path
                        break
                item_type = "dir" if entry.entry_type == "dir" else "file"
                if covered_by:
                    covered_selectable = item_type != "dir"
                    item_size = int(entry.size or 0)
                    is_stale = entry_relative in stale_relative_paths
                    preview_items.append(
                        self._build_preview_item(
                            path=entry.absolute_path,
                            relative_path=item_relative,
                            item_type=item_type,
                            size=item_size,
                            modified_time=self._index_entry_modified_time(entry),
                            selectable=covered_selectable,
                            covered_by=covered_by,
                            delete_path=entry.absolute_path,
                            size_status="stale" if is_stale else "ready",
                            delete_scope="self" if covered_selectable else "preview_child",
                        )
                    )
                    if is_stale and preview_items:
                        preview_items[-1]["index_refresh_pending"] = True
                    if covered_selectable:
                        selected_count += 1
                        selected_size += item_size
                    continue

                matched_rules = self._match_filter_rule_names(
                    name,
                    "folder" if item_type == "dir" else "file",
                    active_rules,
                    relative_path=item_relative,
                    full_path=entry.absolute_path,
                )
                if not matched_rules:
                    continue
                is_stale = entry_relative in stale_relative_paths
                preview_items.append(
                    self._build_preview_item(
                        path=entry.absolute_path,
                        relative_path=item_relative,
                        item_type=item_type,
                        size=int(entry.size or 0),
                        modified_time=self._index_entry_modified_time(entry),
                        matched_rules=matched_rules,
                        size_status="stale" if is_stale else "ready",
                        delete_scope="preview_parent" if item_type == "dir" else "self",
                    )
                )
                if is_stale and preview_items:
                    preview_items[-1]["index_refresh_pending"] = True
                if item_type == "dir":
                    covered_roots.append((entry_relative, entry.absolute_path))
                else:
                    selected_count += 1
                    selected_size += int(entry.size or 0)

            preview_items.sort(key=lambda item: (item["relative_path"].count("/"), item["relative_path"].lower(), item["type"] != "dir"))
            return {
                "folder_name": folder_name,
                "folder_path": target_path,
                "rules": active_rules,
                "items": preview_items,
                "selected_count": selected_count,
                "selected_size": selected_size,
                "selected_size_exact": True,
                "size_disabled": False,
                "truncated": False,
                "truncated_reason": "",
                "scanned_entries": len(entries),
                "discovered_entries": len(entries),
                "pending_directories": 0,
                "browse_via_index": True,
            }
        except (FileNotFoundError, PermissionError, ValueError):
            raise
        except Exception:
            logger.warning("删除过滤预审索引路径异常转 fallback: lib=%s path=%s", library.id, path, exc_info=True)
            return None

    def _empty_filter_delete_preview(
        self,
        path: str,
        active_rules: list[dict[str, str]],
        *,
        folder_name: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_path = str(path or "")
        return {
            "folder_name": folder_name or PurePosixPath(normalized_path).name or os.path.basename(normalized_path) or normalized_path,
            "folder_path": normalized_path,
            "rules": active_rules,
            "items": [],
            "selected_count": 0,
            "selected_size": 0,
            "selected_size_exact": True,
            "size_disabled": False,
            "truncated": False,
            "truncated_reason": "",
            "scanned_entries": 0,
            "discovered_entries": 0,
            "pending_directories": 0,
        }

    def _normalize_filter_delete_targets(
        self,
        library_id: Optional[str],
        path: Optional[str],
        target_items: Optional[list[Any]],
    ) -> list[dict[str, Any]]:
        raw_items = target_items if isinstance(target_items, list) and target_items else []
        if not raw_items and path:
            raw_items = [{"library_id": library_id, "path": path}]
        targets: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_library_id = str(item.get("library_id") or library_id or "").strip()
            item_path = str(item.get("path") or "").strip()
            if not item_library_id or not item_path:
                continue
            library = self.get_library_definition(item_library_id)
            if library.type == "synology_filestation":
                _, target_path = self._resolve_remote_operation_path(
                    library,
                    item_path,
                    action="删除过滤预审",
                )
            else:
                self._assert_local_path_in_library(library, item_path)
                target_path = os.path.abspath(item_path)
                if not os.path.isdir(target_path):
                    raise FileNotFoundError("目标文件夹不存在")
            key = (library.id, target_path.replace("\\", "/").rstrip("/") or "/")
            if key in seen:
                continue
            seen.add(key)
            targets.append({
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "path": target_path,
                "name": str(item.get("name") or (PurePosixPath(target_path).name if library.type == "synology_filestation" else os.path.basename(target_path)) or target_path),
                "library": library,
            })
        return targets

    def _decorate_filter_delete_preview_items(
        self,
        items: list[dict[str, Any]],
        target: dict[str, Any],
        *,
        multi_target: bool,
    ) -> list[dict[str, Any]]:
        library_id = str(target.get("library_id") or "")
        library_name = str(target.get("library_name") or library_id)
        root_path = str(target.get("path") or "")
        root_name = str(target.get("name") or PurePosixPath(root_path).name or root_path)
        normalized_root_path = root_path.replace("\\", "/").rstrip("/") or "/"
        target_key = f"{library_id}::{normalized_root_path}"
        display_prefix = f"{library_name} / {root_name}" if multi_target else ""
        decorated: list[dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            original_relative = str(next_item.get("relative_path") or next_item.get("name") or "").replace("\\", "/").strip("/")
            next_item["library_id"] = library_id
            next_item["library_name"] = library_name
            next_item["target_root_path"] = root_path
            next_item["target_root_name"] = root_name
            next_item["target_key"] = target_key
            next_item["target_display_prefix"] = display_prefix
            next_item["original_relative_path"] = original_relative
            if multi_target and display_prefix:
                next_item["relative_path"] = f"{display_prefix}/{original_relative}" if original_relative else display_prefix
            decorated.append(next_item)
        return decorated

    def _merge_filter_delete_preview_results(
        self,
        targets: list[dict[str, Any]],
        results: list[dict[str, Any]],
        active_rules: list[dict[str, str]],
    ) -> dict[str, Any]:
        multi_target = len(targets) > 1
        merged_items: list[dict[str, Any]] = []
        selected_count = 0
        selected_size = 0
        scanned_entries = 0
        discovered_entries = 0
        selected_size_exact = True
        size_disabled = False
        truncated = False
        warnings: list[str] = []
        errors: list[str] = []
        failed_targets: list[dict[str, str]] = []

        for target, result in zip(targets, results):
            status = str(result.get("status") or "completed")
            if status == "error":
                error = str(result.get("error") or "预审失败")
                errors.append(error)
                failed_targets.append({
                    "library_id": str(target.get("library_id") or ""),
                    "library_name": str(target.get("library_name") or ""),
                    "path": str(target.get("path") or ""),
                    "name": str(target.get("name") or ""),
                    "error": error,
                })
                continue
            merged_items.extend(self._decorate_filter_delete_preview_items(
                list(result.get("items") or []),
                target,
                multi_target=multi_target,
            ))
            selected_count += int(result.get("selected_count") or 0)
            selected_size += int(result.get("selected_size") or 0)
            scanned_entries += int(result.get("scanned_entries") or 0)
            discovered_entries += int(result.get("discovered_entries") or 0)
            selected_size_exact = selected_size_exact and bool(result.get("selected_size_exact", True))
            size_disabled = size_disabled or bool(result.get("size_disabled", False))
            truncated = truncated or bool(result.get("truncated", False))
            warning = str(result.get("warning") or "").strip()
            if warning:
                warnings.append(warning)
            error = str(result.get("error") or "").strip()
            if error:
                errors.append(error)

        folder_name = targets[0]["name"] if len(targets) == 1 else f"已选目录（{len(targets)} 项）"
        folder_path = targets[0]["path"] if len(targets) == 1 else ""
        status = "error" if failed_targets and len(failed_targets) == len(targets) else "completed"
        return {
            "folder_name": folder_name,
            "folder_path": folder_path,
            "rules": active_rules,
            "items": merged_items,
            "selected_count": selected_count,
            "selected_size": selected_size,
            "selected_size_exact": selected_size_exact,
            "size_disabled": size_disabled,
            "truncated": truncated,
            "truncated_reason": "；".join(warnings),
            "scanned_entries": scanned_entries,
            "discovered_entries": discovered_entries,
            "pending_directories": 0,
            "status": status,
            "current_path": "",
            "progress_message": "删除过滤预审完成" if status == "completed" else "删除过滤预审失败",
            "warning": "；".join(warnings),
            "error": "；".join(errors),
            "failed_targets": failed_targets,
            "target_items": [
                {
                    "library_id": str(target.get("library_id") or ""),
                    "library_name": str(target.get("library_name") or ""),
                    "path": str(target.get("path") or ""),
                    "name": str(target.get("name") or ""),
                }
                for target in targets
            ],
        }

    def _list_folders_only_via_index(
        self,
        library: LibraryDefinition,
        path: Optional[str],
        *,
        include_files: bool = False,
    ) -> Optional[dict[str, Any]]:
        target_path = path
        if not target_path:
            target_path = library.browse_root_path or library.root_path or ("/" if library.type == "synology_filestation" else "")
        indexed = self._folder_contents_via_index(library, target_path, recursive=False)
        if indexed is None:
            return None

        if library.type == "synology_filestation":
            browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
            current_path = self._normalize_remote_path(indexed.get("folder_path") or target_path or browse_root)
            parent_path = None if current_path == browse_root else self._remote_parent_path(current_path)
        else:
            browse_root = os.path.abspath(library.browse_root_path or library.root_path)
            current_path = os.path.abspath(indexed.get("folder_path") or target_path or browse_root)
            parent_path = None if os.path.normcase(current_path) == os.path.normcase(browse_root) else os.path.dirname(current_path)

        folders = []
        for item in list(indexed.get("items") or []):
            is_directory = bool(item.get("is_directory"))
            if not is_directory and not include_files:
                continue
            folders.append({
                "name": item.get("name") or "",
                "path": item.get("path") or "",
                "is_directory": is_directory,
                "modified_time": item.get("modified_time"),
                "size": item.get("size"),
                "size_status": item.get("size_status") or ("ready" if not is_directory else "pending"),
                "file_count": item.get("file_count"),
                "folder_count": item.get("folder_count"),
                "size_via_index": bool(is_directory and library.type == "local"),
                "browse_via_index": True,
            })
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "library_root_path": library.root_path,
            "current_path": current_path,
            "browse_root_path": browse_root,
            "parent_path": parent_path,
            "folders": folders,
            "browse_via_index": True,
        }

    async def _remote_folder_contents(self, library: LibraryDefinition, path: str, *, client: Optional[SynologyFileStationClient] = None, recursive: bool = True) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        browse_root, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="获取库存文件夹内容",
        )

        # 优先复用传入的 client（避免重复登录），否则使用全局缓存 client
        if client is None:
            client = self.get_cached_synology_client(library.synology)
        info_item: Optional[dict[str, Any]] = None
        try:
            info = await client.stat(target_path)
            info_item = self._first_remote_info_item(info)
        except Exception as exc:
            if client._is_error_code(exc, 119):
                try:
                    fallback_data = (
                        await client.list_share(offset=0, limit=1, sort_by="name", sort_direction="asc")
                        if target_path == "/"
                        else await client.list(target_path, offset=0, limit=1, sort_by="name", sort_direction="asc")
                    )
                    fallback_items = fallback_data.get("shares") or fallback_data.get("files") or []
                    info_item = fallback_items[0] if fallback_items else {"path": target_path, "isdir": True}
                    logger.warning(
                        "远程文件夹摘要回退到 list: library_id=%s path=%s original_error=%s",
                        library.id,
                        target_path,
                        exc,
                    )
                    info_item = info_item or {"path": target_path, "isdir": True}
                except Exception:
                    await self._raise_remote_code_119_context(
                        client=client,
                        library=library,
                        action="获取库存文件夹内容",
                        incoming_path=path,
                        target_path=target_path,
                        original_error=exc,
                    )
                    raise
            else:
                raise
        if not info_item or not info_item.get("isdir", False):
            raise FileNotFoundError("目标文件夹不存在")

        items: list[dict[str, Any]] = []
        counter = 0

        if not recursive:
            children = await self._list_remote_directory(client, target_path)
            for child in children:
                name = child.get("name") or ""
                if self._should_skip_entry(name):
                    continue
                child_path = self._normalize_remote_path(child.get("path") or child.get("real_path") or "")
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime", int(time.time()))
                is_directory = bool(child.get("isdir", False))
                items.append(
                    {
                        "id": f"{library.id}:content:{counter}",
                        "name": name,
                        "path": child_path,
                        "relative_path": name,
                        "size": None if is_directory else int(additional.get("size") or 0),
                        "size_status": "disabled" if is_directory else "ready",
                        "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                        "type": "dir" if is_directory else "file",
                        "is_directory": is_directory,
                        "has_children": is_directory,
                        "children_loaded": False if is_directory else True,
                        "file_count": None if is_directory else 1,
                        "folder_count": None if is_directory else 0,
                    }
                )
                counter += 1
            items.sort(key=lambda item: (0 if item.get("is_directory") else 1, self._natural_name_key(item.get("name", ""))))
            result = {
                "folder_name": PurePosixPath(target_path).name or target_path,
                "folder_path": target_path,
                "total_files": sum(1 for item in items if not item.get("is_directory")),
                "total_items": len(items),
                "recursive": False,
                "items": items,
            }
            self._append_stats_log(library, "INFO", f"文件树浅层读取 path={target_path} total={len(items)}")
            return result

        walk_semaphore = asyncio.Semaphore(4)

        async def walk(folder_path: str):
            nonlocal counter
            async with walk_semaphore:
                children = await self._list_remote_directory(client, folder_path)
            subdirs: list[str] = []
            for child in children:
                name = child.get("name") or ""
                if self._should_skip_entry(name):
                    continue
                child_path = self._normalize_remote_path(child.get("path") or child.get("real_path") or "")
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime", int(time.time()))
                if child.get("isdir", False):
                    subdirs.append(child_path)
                    continue
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                items.append(
                    {
                        "id": f"{library.id}:content:{counter}",
                        "name": name,
                        "path": child_path,
                        "relative_path": relative_path,
                        "size": int(additional.get("size") or 0),
                        "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    }
                )
                counter += 1
            # 并发递归子目录，消除串行等待
            if subdirs:
                await asyncio.gather(*[walk(sd) for sd in subdirs], return_exceptions=True)

        await walk(target_path)
        items.sort(key=lambda item: item["relative_path"])
        result = {
            "folder_name": PurePosixPath(target_path).name or target_path,
            "folder_path": target_path,
            "total_files": len(items),
            "items": items,
        }
        self._append_stats_log(library, "INFO", f"文件树读取 path={target_path} total={len(items)}")
        return result

    def _local_folder_contents_shallow(self, library: LibraryDefinition, path: str) -> dict[str, Any]:
        library_root = os.path.abspath(library.root_path)
        target_path = os.path.abspath(path)
        if not self._local_path_is_within_root(target_path, library_root):
            raise PermissionError("只能查看当前库存根目录内的文件夹")
        if not os.path.isdir(target_path):
            raise FileNotFoundError("目标文件夹不存在")

        items: list[dict[str, Any]] = []
        index_service = self._index_service_for_local_size_overlay(library)
        repair_paths: list[str] = []
        with os.scandir(target_path) as entries:
            for index, entry in enumerate(entries):
                name = entry.name
                if self._should_skip_entry(name):
                    continue
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                item_path = os.path.abspath(os.path.join(target_path, name))
                index_entry = None
                index_missing = False
                index_stale = False
                if index_service is not None:
                    index_entry, index_missing, index_stale = self._local_index_entry_for_current_child(
                        library,
                        index_service,
                        absolute_path=item_path,
                        is_directory=is_directory,
                        stat_result=stat_result,
                    )
                    if index_missing or index_stale:
                        repair_paths.append(item_path)
                if is_directory:
                    size = int(getattr(index_entry, "size", 0) or 0) if index_entry is not None else None
                    size_status = "stale" if index_stale else ("ready" if index_entry is not None else "pending")
                    file_count = int(getattr(index_entry, "file_count", 0) or 0) if index_entry is not None else None
                    folder_count = None
                else:
                    size = int(stat_result.st_size)
                    size_status = "ready"
                    file_count = 1
                    folder_count = 0
                items.append({
                    "id": f"{library.id}:content:{index}",
                    "name": name,
                    "path": item_path,
                    "relative_path": name,
                    "size": size,
                    "size_status": size_status,
                    "modified_time": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
                    "type": "dir" if is_directory else "file",
                    "is_directory": is_directory,
                    "has_children": is_directory,
                    "children_loaded": False if is_directory else True,
                    "file_count": file_count,
                    "folder_count": folder_count,
                    "folder_count_status": "lazy" if is_directory else "ready",
                    "size_via_index": bool(is_directory and index_entry),
                    "index_refresh_pending": bool(index_missing or index_stale),
                })
        if repair_paths:
            self._enqueue_index_read_repair_upserts(library, repair_paths)

        items.sort(key=lambda item: (0 if item.get("is_directory") else 1, self._natural_name_key(item.get("name", ""))))
        result = {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "total_files": sum(1 for item in items if not item.get("is_directory")),
            "total_items": len(items),
            "recursive": False,
            "items": items,
        }
        self._append_stats_log(library, "INFO", f"文件树浅层读取 path={target_path} total={len(items)}")
        return result

    async def folder_contents(
        self,
        library_id: str,
        path: str,
        *,
        client: Optional[SynologyFileStationClient] = None,
        recursive: bool = True,
        prefer_index: bool = True,
        include_dirs: bool = False,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        inflight_key = self._folder_contents_inflight_key(
            library,
            path=path,
            recursive=recursive,
            prefer_index=prefer_index,
            include_dirs=include_dirs,
        )
        return await self._run_folder_contents_inflight(
            inflight_key,
            lambda: self._folder_contents_uncached(
                library,
                path,
                client=client,
                recursive=recursive,
                prefer_index=prefer_index,
                include_dirs=include_dirs,
            ),
        )

    def _folder_contents_inflight_key(
        self,
        library: LibraryDefinition,
        *,
        path: str,
        recursive: bool,
        prefer_index: bool,
        include_dirs: bool,
    ) -> tuple[Any, ...]:
        if library.type == "local":
            try:
                normalized_path = os.path.normcase(os.path.abspath(path))
            except Exception:
                normalized_path = str(path or "")
        else:
            normalized_path = self._normalize_remote_path(path or "/")
        return (library.id, library.type, normalized_path, bool(recursive), bool(prefer_index), bool(include_dirs))

    async def _run_folder_contents_inflight(self, key: tuple[Any, ...], factory: Callable[[], Any]) -> dict[str, Any]:
        if not hasattr(self, "_folder_contents_inflight"):
            self._folder_contents_inflight = {}
        lock = getattr(self, "_folder_contents_inflight_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._folder_contents_inflight_lock = lock
        async with lock:
            future = self._folder_contents_inflight.get(key)
            owner = False
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._folder_contents_inflight[key] = future
                owner = True
        if not owner:
            return copy.deepcopy(await future)
        try:
            result = await factory()
            future.set_result(copy.deepcopy(result))
            return result
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with lock:
                self._folder_contents_inflight.pop(key, None)

    async def _folder_contents_uncached(
        self,
        library: LibraryDefinition,
        path: str,
        *,
        client: Optional[SynologyFileStationClient] = None,
        recursive: bool = True,
        prefer_index: bool = True,
        include_dirs: bool = False,
    ) -> dict[str, Any]:
        if library.type == "local":
            if prefer_index:
                indexed = self._folder_contents_via_index(library, path, recursive=recursive, include_dirs=include_dirs)
                if indexed is not None:
                    return indexed
            if recursive:
                return await asyncio.to_thread(self._local_folder_contents, library, path)
            return await asyncio.to_thread(self._local_folder_contents_shallow, library, path)
        if prefer_index:
            indexed = self._folder_contents_via_index(library, path, recursive=recursive, include_dirs=include_dirs)
            if indexed is not None:
                return indexed
        return await self._remote_folder_contents(library, path, client=client, recursive=recursive)

    async def preview_mojibake_repairs(self, library_id: str, path: str, selected_paths: Optional[list[str]] = None) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        contents = await self.folder_contents(library_id, path)
        items = contents.get("items") or []
        forced_paths = {str(item or "").strip() for item in (selected_paths or []) if str(item or "").strip()}
        repairs: list[dict[str, Any]] = []
        directory_rows: dict[str, dict[str, Any]] = {}
        item_rows: list[dict[str, Any]] = []
        track_group_pairs: dict[str, dict[str, int]] = {}

        def build_dir_path(relative_dir: str) -> str:
            base_path = str(contents.get("folder_path") or path or "").strip()
            normalized_relative = str(relative_dir or "").strip().replace("\\", "/")
            if not normalized_relative:
                return base_path
            if library.type == "local":
                return os.path.join(base_path, *[part for part in normalized_relative.split("/") if part])
            return str(PurePosixPath(base_path) / normalized_relative)

        for item in items:
            current_name = str(item.get("name") or "").strip()
            item_path = str(item.get("path") or "").strip()
            relative_path = str(item.get("relative_path") or current_name)
            if not current_name or not item_path:
                continue
            item_rows.append({
                "path": item_path,
                "relative_path": relative_path,
                "current_name": current_name,
                "item_type": "file",
            })
            parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
            current_dir = []
            for part in parts[:-1]:
                current_dir.append(part)
                relative_dir = "/".join(current_dir)
                if relative_dir in directory_rows:
                    continue
                dir_candidates = _guess_mojibake_name_repairs(part)
                if not dir_candidates:
                    continue
                best_dir = dir_candidates[0]
                directory_rows[relative_dir] = {
                    "path": build_dir_path(relative_dir),
                    "relative_path": relative_dir,
                    "current_name": part,
                    "suggested_name": best_dir["name"],
                    "score": best_dir["score"],
                    "encoding_pair": f"{best_dir['source_encoding']} -> {best_dir['target_encoding']}",
                    "item_type": "dir",
                    "needs_manual_input": False,
                }
            candidates = _guess_mojibake_name_repairs(current_name)
            if not candidates:
                continue
            best = candidates[0]
            group_key = _track_group_key(relative_path)
            pair_key = f"{best['source_encoding']}->{best['target_encoding']}"
            track_group_pairs.setdefault(group_key, {})
            track_group_pairs[group_key][pair_key] = track_group_pairs[group_key].get(pair_key, 0) + 1
            repairs.append({
                "path": item_path,
                "relative_path": relative_path,
                "current_name": current_name,
                "suggested_name": best["name"],
                "score": best["score"],
                "encoding_pair": f"{best['source_encoding']} -> {best['target_encoding']}",
                "item_type": "file",
                "needs_manual_input": False,
                "forced_include": False,
            })

        repair_paths = {str(item.get("path") or "") for item in repairs}
        for row in item_rows:
            if row["path"] in repair_paths:
                continue
            group_key = _track_group_key(row["relative_path"])
            pair_counts = track_group_pairs.get(group_key) or {}
            if not pair_counts:
                continue
            dominant_pair, dominant_count = max(pair_counts.items(), key=lambda item: item[1])
            if dominant_count < 2:
                continue
            relaxed_candidates = _guess_mojibake_name_repairs(row["current_name"], relaxed=True)
            if not relaxed_candidates:
                continue
            source_encoding, target_encoding = dominant_pair.split("->", 1)
            matched = next(
                (
                    candidate for candidate in relaxed_candidates
                    if candidate["source_encoding"] == source_encoding and candidate["target_encoding"] == target_encoding
                ),
                None
            )
            if not matched:
                matched = relaxed_candidates[0]
            if _mojibake_score(matched["name"]) < _mojibake_score(row["current_name"]) + 2:
                continue
            repairs.append({
                "path": row["path"],
                "relative_path": row["relative_path"],
                "current_name": row["current_name"],
                "suggested_name": matched["name"],
                "score": matched["score"],
                "encoding_pair": f"{matched['source_encoding']} -> {matched['target_encoding']}",
                "item_type": "file",
                "needs_manual_input": False,
                "forced_include": False,
            })
            repair_paths.add(row["path"])

        for row in item_rows:
            if row["path"] in repair_paths:
                continue
            group_key = _track_group_key(row["relative_path"])
            pair_counts = track_group_pairs.get(group_key) or {}
            if sum(pair_counts.values()) < 2:
                continue
            if not _is_audio_filename(row["current_name"]):
                continue
            dominant_pair, _ = max(pair_counts.items(), key=lambda item: item[1])
            repairs.append({
                "path": row["path"],
                "relative_path": row["relative_path"],
                "current_name": row["current_name"],
                "suggested_name": row["current_name"],
                "score": _mojibake_score(row["current_name"]),
                "encoding_pair": dominant_pair.replace("->", " -> "),
                "item_type": "file",
                "needs_manual_input": True,
                "forced_include": False,
            })
            repair_paths.add(row["path"])

        for row in item_rows:
            if row["path"] in repair_paths or row["path"] not in forced_paths:
                continue
            repairs.append({
                "path": row["path"],
                "relative_path": row["relative_path"],
                "current_name": row["current_name"],
                "suggested_name": row["current_name"],
                "score": _mojibake_score(row["current_name"]),
                "encoding_pair": "",
                "item_type": "file",
                "needs_manual_input": True,
                "forced_include": True,
            })
        repairs.extend(directory_rows.values())
        repairs.sort(key=lambda item: (0 if item.get("item_type") == "dir" else 1, str(item.get("relative_path") or "").count("/"), str(item.get("relative_path") or "")))
        return {
            "folder_path": contents.get("folder_path") or path,
            "folder_name": contents.get("folder_name") or os.path.basename(path),
            "total_candidates": len(repairs),
            "items": repairs,
        }

    def _normalize_filter_rules(self, rules: Optional[list[Any]] = None) -> list[dict[str, str]]:
        source_rules = rules if rules is not None else (get_config().filter.rules or [])
        normalized_rules: list[dict[str, str]] = []
        for index, rule in enumerate(source_rules):
            if isinstance(rule, dict):
                name = str(rule.get("name") or f"规则 {index + 1}")
                pattern = str(rule.get("pattern") or "").strip()
                target = str(rule.get("target") or "file").lower()
                enabled = bool(rule.get("enabled", True))
            else:
                name = str(getattr(rule, "name", f"规则 {index + 1}"))
                pattern = str(getattr(rule, "pattern", "") or "").strip()
                target = str(getattr(rule, "target", "file") or "file").lower()
                enabled = bool(getattr(rule, "enabled", True))
            target_alias = {
                "name": "file",
                "filename": "file",
                "file": "file",
                "folder": "folder",
                "dir": "folder",
                "directory": "folder",
                "path": "path",
                "filepath": "path",
                "all": "all",
            }
            normalized_target = target_alias.get(target, target)
            if not enabled or not pattern or normalized_target not in {"file", "folder", "path", "all"}:
                continue
            normalized_rules.append({
                "name": name,
                "pattern": pattern,
                "target": normalized_target,
            })
        return normalized_rules

    def _match_filter_rule_names(
        self,
        name: str,
        target_type: str,
        rules: list[dict[str, str]],
        *,
        relative_path: str = "",
        full_path: str = "",
    ) -> list[str]:
        matched: list[str] = []
        normalized_relative_path = str(relative_path or "").replace("\\", "/")
        normalized_full_path = str(full_path or "").replace("\\", "/")
        for rule in rules:
            target = rule["target"]
            if target not in {target_type, "all", "path"}:
                continue
            try:
                candidates = [str(name or "")]
                if target in {"path", "all"}:
                    candidates.extend([
                        normalized_relative_path,
                        normalized_full_path,
                    ])
                if any(candidate and re.search(rule["pattern"], candidate, re.IGNORECASE) for candidate in candidates):
                    matched.append(rule["name"])
            except re.error as exc:
                logger.warning("过滤规则正则无效，已跳过: %s (%s)", rule["pattern"], exc)
        return matched

    def _should_skip_filter_preview_name(self, name: str) -> bool:
        return str(name or "").lower() in {"#recycle", "@eadir"}

    def _build_preview_item(
        self,
        *,
        path: str,
        relative_path: str,
        item_type: str,
        size: Optional[int] = 0,
        modified_time: Optional[str] = None,
        matched_rules: Optional[list[str]] = None,
        selectable: bool = True,
        covered_by: str = "",
        delete_path: Optional[str] = None,
        size_status: str = "ready",
        delete_scope: str = "",
    ) -> dict[str, Any]:
        normalized_relative = str(relative_path or "").replace("\\", "/").strip("/")
        normalized_item_type = "dir" if item_type == "dir" else "file"
        normalized_delete_scope = str(delete_scope or ("self" if selectable else "preview_child")).strip().lower()
        if normalized_item_type == "dir":
            normalized_delete_scope = "preview_parent" if matched_rules else "preview_child"
            selectable = False
        elif normalized_delete_scope not in {"self", "preview_child", "preview_parent"}:
            normalized_delete_scope = "self" if selectable else "preview_child"
        normalized_path = str(path or "").replace("\\", "/")
        return {
            "id": f"{normalized_item_type}:{normalized_path}",
            "name": PurePosixPath(normalized_relative or normalized_path).name if "/" in normalized_relative else (normalized_relative or os.path.basename(path)),
            "path": path,
            "relative_path": normalized_relative,
            "type": normalized_item_type,
            "size": None if size is None else int(size or 0),
            "modified_time": modified_time,
            "matched_rules": matched_rules or [],
            "selectable": bool(selectable) and normalized_item_type == "file" and normalized_delete_scope == "self",
            "covered_by": covered_by or "",
            "delete_path": delete_path or path,
            "size_status": size_status,
            "delete_scope": normalized_delete_scope,
        }

    def _begin_filter_preview_request(self, request_id: Optional[str]) -> None:
        if request_id:
            self._filter_preview_cancel_flags[request_id] = False

    def _finish_filter_preview_request(self, request_id: Optional[str]) -> None:
        if request_id:
            self._filter_preview_cancel_flags.pop(request_id, None)

    def cancel_filter_delete_preview(self, request_id: str) -> dict[str, Any]:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            raise ValueError("缺少预审请求 ID")
        self._filter_preview_cancel_flags[normalized_request_id] = True
        return {"message": "已发送删除过滤预审取消请求", "request_id": normalized_request_id}

    def _create_filter_preview_client(self, library: LibraryDefinition) -> SynologyFileStationClient:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        preview_timeout = 0
        return SynologyFileStationClient(replace(library.synology, timeout=preview_timeout))

    def _init_filter_preview_job(
        self,
        job_id: str,
        library: LibraryDefinition,
        target_path: str,
        rules: list[dict[str, str]],
    ) -> dict[str, Any]:
        payload = {
            "job_id": job_id,
            "library_id": library.id,
            "library_name": library.name,
            "folder_name": PurePosixPath(target_path).name or target_path,
            "folder_path": target_path,
            "rules": rules,
            "items": [],
            "selected_count": 0,
            "selected_size": 0,
            "selected_size_exact": True,
            "size_disabled": False,
            "scanned_entries": 0,
            "discovered_entries": 0,
            "pending_directories": 1,
            "status": "pending",
            "current_path": target_path,
            "progress_message": "已创建删除过滤预审任务",
            "warning": "",
            "error": "",
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        self._filter_preview_jobs[job_id] = payload
        return payload

    def _update_filter_preview_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        job = self._filter_preview_jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        job.update(fields)
        job["updated_at"] = time.time()
        self._broadcast_filter_preview_job(job)
        return job

    def _broadcast_filter_preview_job(self, job: dict[str, Any]) -> None:
        try:
            from .realtime_event_service import broadcast_event

            status = str(job.get("status") or "pending")
            updated_ts = float(job.get("updated_at") or time.time())
            scanned = int(job.get("scanned_entries") or 0)
            discovered = int(job.get("discovered_entries") or 0)
            pending = int(job.get("pending_directories") or 0)
            selected_count = int(job.get("selected_count") or 0)
            selected_size = int(job.get("selected_size") or 0)
            broadcast_event({
                "type": "job.filter_delete_preview.changed",
                "reason": status,
                "id": str(job.get("job_id") or ""),
                "domain": "library",
                "status": status,
                "current_step": str(job.get("progress_message") or ""),
                "updated_at": datetime.fromtimestamp(updated_ts).isoformat(),
                "payload": {
                    "job_id": job.get("job_id"),
                    "library_id": job.get("library_id"),
                    "library_name": job.get("library_name"),
                    "folder_name": job.get("folder_name"),
                    "folder_path": job.get("folder_path"),
                    "status": status,
                    "current_path": job.get("current_path") or "",
                    "progress_message": job.get("progress_message") or "",
                    "selected_count": selected_count,
                    "selected_size": selected_size,
                    "selected_size_exact": bool(job.get("selected_size_exact", True)),
                    "size_disabled": bool(job.get("size_disabled", False)),
                    "scanned_entries": scanned,
                    "discovered_entries": discovered,
                    "pending_directories": pending,
                    "warning": job.get("warning") or "",
                    "error": job.get("error") or "",
                    "updated_at": updated_ts,
                },
            })
        except Exception:
            logger.debug("广播删除过滤预审实时事件失败", exc_info=True)

    def _build_filter_preview_job_response(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job.get("job_id"),
            "library_id": job.get("library_id"),
            "library_name": job.get("library_name"),
            "folder_name": job.get("folder_name"),
            "folder_path": job.get("folder_path"),
            "rules": job.get("rules") or [],
            "items": job.get("items") or [],
            "selected_count": int(job.get("selected_count") or 0),
            "selected_size": int(job.get("selected_size") or 0),
            "selected_size_exact": bool(job.get("selected_size_exact", True)),
            "size_disabled": bool(job.get("size_disabled", False)),
            "truncated": bool(job.get("truncated", False)),
            "truncated_reason": job.get("truncated_reason") or "",
            "scanned_entries": int(job.get("scanned_entries") or 0),
            "discovered_entries": int(job.get("discovered_entries") or 0),
            "pending_directories": int(job.get("pending_directories") or 0),
            "status": job.get("status") or "pending",
            "current_path": job.get("current_path") or "",
            "progress_message": job.get("progress_message") or "",
            "warning": job.get("warning") or "",
            "error": job.get("error") or "",
            "failed_targets": job.get("failed_targets") or [],
            "target_items": job.get("target_items") or [],
            "started_at": job.get("started_at"),
            "updated_at": job.get("updated_at"),
        }

    def _create_remote_filter_preview_state(self, client: SynologyFileStationClient, request_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "visited_entries": 0,
            "max_entries": 0,
            "truncated": False,
            "reason": "",
            "request_id": str(request_id or "").strip(),
        }

    async def _list_remote_directory_with_retry(
        self,
        client: SynologyFileStationClient,
        current_path: str,
        *,
        retries: int = 3,
        retry_delay_seconds: float = 1.5,
    ) -> list[dict[str, Any]]:
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                return await self._list_remote_directory(client, current_path)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                await asyncio.sleep(retry_delay_seconds * attempt)
        if last_error:
            raise last_error
        return []

    def _is_retryable_synology_remote_error(self, exc: Exception) -> bool:
        message = str(exc or "")
        lowered = message.lower()
        return any(token in lowered for token in [
            "code 408",
            '"code": 408',
            "code 1200",
            '"code": 1200',
            "信号灯超时时间已到",
            "winerror 64",
            "指定的网络名不再可用",
            "connection lost",
            "connection reset",
            "timeout",
        ])

    async def _remote_path_exists(self, client: SynologyFileStationClient, path: str) -> bool:
        normalized_path = self._normalize_remote_path(path)
        try:
            info = await client.stat(normalized_path)
            item = self._first_remote_info_item(info)
            if item:
                return True
        except Exception:
            pass

        parent_path = self._remote_parent_path(normalized_path)
        if parent_path == normalized_path:
            return False
        child_visible = await self._remote_child_visible(client, parent_path, PurePosixPath(normalized_path).name)
        return bool(child_visible)

    async def _retry_remote_rename(
        self,
        client: SynologyFileStationClient,
        path: str,
        new_name: str,
        *,
        retries: int = 4,
        retry_delay_seconds: float = 5.0,
    ) -> None:
        normalized_path = self._normalize_remote_path(path)
        target_path = str(PurePosixPath(normalized_path).parent / new_name)
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                await client.rename(normalized_path, new_name)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if self._is_retryable_synology_remote_error(exc):
                    try:
                        if await self._remote_path_exists(client, target_path):
                            return
                    except Exception:
                        logger.debug("远程重命名结果校验失败: %s -> %s", normalized_path, target_path, exc_info=True)
                    if attempt < retries:
                        logger.warning(
                            "远程重命名超时，准备重试: path=%s target=%s attempt=%s/%s error=%s",
                            normalized_path,
                            target_path,
                            attempt,
                            retries,
                            exc,
                        )
                        await asyncio.sleep(retry_delay_seconds * attempt)
                        continue
                raise
        if last_error:
            raise last_error

    async def _retry_remote_delete(
        self,
        client: SynologyFileStationClient,
        path: str,
        *,
        retries: int = 4,
        retry_delay_seconds: float = 5.0,
    ) -> None:
        normalized_path = self._normalize_remote_path(path)
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                await client.delete(normalized_path)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if self._is_error_code(exc, 119):
                    return
                if self._is_retryable_synology_remote_error(exc):
                    try:
                        if not await self._remote_path_exists(client, normalized_path):
                            return
                    except Exception:
                        logger.debug("远程删除结果校验失败: %s", normalized_path, exc_info=True)
                    if attempt < retries:
                        logger.warning(
                            "远程删除超时，准备重试: path=%s attempt=%s/%s error=%s",
                            normalized_path,
                            attempt,
                            retries,
                            exc,
                        )
                        await asyncio.sleep(retry_delay_seconds * attempt)
                        continue
                raise
        if last_error:
            raise last_error

    def _mark_remote_filter_preview_truncated(self, state: dict[str, Any], reason: str) -> None:
        if state.get("truncated"):
            return
        state["truncated"] = True
        state["reason"] = reason

    def _touch_remote_filter_preview_entry(self, state: dict[str, Any]) -> bool:
        if state.get("truncated"):
            return False
        request_id = str(state.get("request_id") or "").strip()
        if request_id and self._filter_preview_cancel_flags.get(request_id):
            self._mark_remote_filter_preview_truncated(state, "删除过滤预审已手动取消")
            return False
        state["visited_entries"] = int(state.get("visited_entries") or 0) + 1
        max_entries = int(state.get("max_entries") or 0)
        if max_entries > 0 and int(state["visited_entries"]) > max_entries:
            self._mark_remote_filter_preview_truncated(state, "远程目录条目过多，预览仅显示前一部分结果")
            return False
        return True

    def _collect_local_filter_preview_descendants(
        self,
        target_path: str,
        folder_path: str,
        delete_path: str,
    ) -> list[dict[str, Any]]:
        descendants: list[dict[str, Any]] = []
        for root, dirs, files in os.walk(folder_path):
            dirs.sort()
            files.sort()
            if os.path.abspath(root) != os.path.abspath(folder_path):
                stat = os.stat(root)
                descendants.append(
                    self._build_preview_item(
                        path=root,
                        relative_path=os.path.relpath(root, target_path).replace("\\", "/"),
                        item_type="dir",
                        size=self._path_size(root),
                        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        selectable=False,
                        covered_by=delete_path,
                        delete_path=root,
                    )
                )
            for filename in files:
                file_path = os.path.join(root, filename)
                stat = os.stat(file_path)
                descendants.append(
                    self._build_preview_item(
                        path=file_path,
                        relative_path=os.path.relpath(file_path, target_path).replace("\\", "/"),
                        item_type="file",
                        size=stat.st_size,
                        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        selectable=True,
                        covered_by=delete_path,
                        delete_path=file_path,
                    )
                )
        return descendants

    def _local_filter_delete_preview(
        self,
        library: LibraryDefinition,
        path: str,
        rules: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        target_path = os.path.abspath(path)
        if not os.path.isdir(target_path):
            raise FileNotFoundError("目标文件夹不存在")

        active_rules = self._normalize_filter_rules(rules)
        if not active_rules:
            return self._empty_filter_delete_preview(target_path, active_rules, folder_name=os.path.basename(target_path))
        indexed_preview = self._filter_delete_preview_via_index(library, target_path, active_rules)
        if indexed_preview is not None:
            self._append_stats_log(
                library,
                "INFO",
                f"本地删除过滤预审读取索引 path={target_path} matched={indexed_preview.get('selected_count')}",
            )
            return indexed_preview
        preview_items: list[dict[str, Any]] = []
        selected_count = 0
        selected_size = 0

        for root, dirs, files in os.walk(target_path, topdown=True):
            dirs.sort()
            files.sort()
            remaining_dirs: list[str] = []
            for directory in dirs:
                if self._should_skip_filter_preview_name(directory):
                    continue
                folder_path = os.path.join(root, directory)
                matched_rules = self._match_filter_rule_names(
                    directory,
                    "folder",
                    active_rules,
                    relative_path=os.path.relpath(folder_path, target_path).replace("\\", "/"),
                    full_path=folder_path,
                )
                if matched_rules:
                    stat = os.stat(folder_path)
                    folder_size = self._path_size(folder_path)
                    preview_items.append(
                        self._build_preview_item(
                            path=folder_path,
                            relative_path=os.path.relpath(folder_path, target_path).replace("\\", "/"),
                            item_type="dir",
                            size=folder_size,
                            modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            matched_rules=matched_rules,
                            delete_scope="preview_parent",
                        )
                    )
                    descendants = self._collect_local_filter_preview_descendants(target_path, folder_path, folder_path)
                    preview_items.extend(descendants)
                    selected_count += sum(1 for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    selected_size += sum(int(item.get("size") or 0) for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    continue
                remaining_dirs.append(directory)
            dirs[:] = remaining_dirs

            for filename in files:
                if self._should_skip_filter_preview_name(filename):
                    continue
                file_path = os.path.join(root, filename)
                matched_rules = self._match_filter_rule_names(
                    filename,
                    "file",
                    active_rules,
                    relative_path=os.path.relpath(file_path, target_path).replace("\\", "/"),
                    full_path=file_path,
                )
                if not matched_rules:
                    continue
                stat = os.stat(file_path)
                preview_items.append(
                    self._build_preview_item(
                        path=file_path,
                        relative_path=os.path.relpath(file_path, target_path).replace("\\", "/"),
                        item_type="file",
                        size=stat.st_size,
                        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        matched_rules=matched_rules,
                    )
                )
                selected_count += 1
                selected_size += stat.st_size

        preview_items.sort(key=lambda item: (item["relative_path"].count("/"), item["relative_path"].lower(), item["type"] != "dir"))
        return {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "rules": active_rules,
            "items": preview_items,
            "selected_count": selected_count,
            "selected_size": selected_size,
            "selected_size_exact": True,
            "truncated": False,
            "truncated_reason": "",
            "scanned_entries": len(preview_items),
        }

    async def _collect_remote_filter_preview_descendants(
        self,
        client: SynologyFileStationClient,
        target_path: str,
        folder_path: str,
        delete_path: str,
        state: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        descendants: list[dict[str, Any]] = []
        preview_state = state or self._create_remote_filter_preview_state(client)

        async def walk(current_path: str) -> int:
            subtotal = 0
            if preview_state.get("truncated"):
                return subtotal
            try:
                children = await self._list_remote_directory(client, current_path)
            except Exception as exc:
                logger.warning("远程过滤删除预览读取目录失败 %s: %s", current_path, exc)
                self._mark_remote_filter_preview_truncated(
                    preview_state,
                    f"Failed to read remote directory; preview stopped at {PurePosixPath(current_path).name or current_path}",
                )
                return subtotal
            for child in children:
                if not self._touch_remote_filter_preview_entry(preview_state):
                    break
                name = child.get("name") or ""
                if self._should_skip_filter_preview_name(name):
                    continue
                raw_child_path = child.get("path") or child.get("real_path") or ""
                child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime")
                modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                if child.get("isdir", False):
                    folder_size = await walk(child_path)
                    descendants.append(
                        self._build_preview_item(
                            path=child_path,
                            relative_path=relative_path,
                            item_type="dir",
                            size=folder_size,
                            modified_time=modified_time,
                            selectable=False,
                            covered_by=delete_path,
                            delete_path=child_path,
                            size_status="partial" if preview_state.get("truncated") else "estimated",
                        )
                    )
                    subtotal += folder_size
                    continue
                file_size = int(additional.get("size") or 0)
                descendants.append(
                    self._build_preview_item(
                        path=child_path,
                        relative_path=relative_path,
                        item_type="file",
                        size=file_size,
                        modified_time=modified_time,
                        selectable=True,
                        covered_by=delete_path,
                        delete_path=child_path,
                        size_status="ready",
                    )
                )
                subtotal += file_size

            return subtotal

        total_size = await walk(folder_path)
        return descendants, total_size

    async def _remote_filter_delete_preview_via_search(
        self,
        client: SynologyFileStationClient,
        library: LibraryDefinition,
        target_path: str,
        active_rules: list[dict[str, str]],
    ) -> Optional[dict[str, Any]]:
        task_id = None
        started_at = time.time()
        try:
            started = await client.start_search(target_path, "*", recursive=True)
            task_id = started.get("taskid") or started.get("task_id")
            if not task_id:
                return None
            await self._wait_remote_search_ready(
                client,
                task_id,
                timeout_seconds=self._remote_search_timeout_seconds(),
            )

            offset = 0
            page_size = 1000
            total = 0
            max_entries = 50000
            truncated = False
            entries: list[dict[str, Any]] = []
            while offset < max_entries:
                data = await client.list_search(
                    task_id,
                    offset=offset,
                    limit=page_size,
                    sort_by="name",
                    sort_direction="asc",
                )
                raw_items = data.get("files") or data.get("items") or []
                page_total = int(data.get("total", len(raw_items)) or len(raw_items))
                total = max(total, page_total)
                if not raw_items:
                    break
                for raw in raw_items:
                    name = str(raw.get("name") or "")
                    if self._should_skip_filter_preview_name(name):
                        continue
                    raw_path = raw.get("path") or raw.get("real_path") or name
                    item_path = self._normalize_remote_path(raw_path)
                    if not (item_path == target_path or item_path.startswith(f"{target_path.rstrip('/')}/")):
                        continue
                    try:
                        relative_path = str(PurePosixPath(item_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                    except Exception:
                        relative_path = name
                    additional = raw.get("additional", {}) or {}
                    timestamp = additional.get("time", {}).get("mtime")
                    modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                    is_directory = bool(raw.get("isdir", False))
                    entries.append({
                        "name": name,
                        "path": item_path,
                        "relative_path": relative_path,
                        "type": "dir" if is_directory else "file",
                        "size": 0 if is_directory else int(additional.get("size") or 0),
                        "modified_time": modified_time,
                    })
                offset += len(raw_items)
                if offset >= max_entries and offset < page_total:
                    truncated = True
                    break
                if len(raw_items) < page_size or offset >= page_total:
                    break

            dir_size_by_path: dict[str, int] = {}
            for entry in entries:
                if entry["type"] != "file":
                    continue
                size = int(entry.get("size") or 0)
                parent = str(PurePosixPath(str(entry["path"])).parent)
                while parent and parent != "/" and (parent == target_path or parent.startswith(f"{target_path.rstrip('/')}/")):
                    dir_size_by_path[parent] = int(dir_size_by_path.get(parent, 0)) + size
                    parent = str(PurePosixPath(parent).parent)

            entries.sort(key=lambda item: (
                str(item["relative_path"]).count("/"),
                str(item["relative_path"]).lower(),
                0 if item["type"] == "dir" else 1,
            ))
            preview_items: list[dict[str, Any]] = []
            selected_count = 0
            selected_size = 0
            covered_roots: list[str] = []
            for entry in entries:
                item_path = str(entry["path"])
                item_type = str(entry["type"])
                covered_by = next(
                    (
                        root
                        for root in covered_roots
                        if item_path == root or item_path.startswith(f"{root.rstrip('/')}/")
                    ),
                    "",
                )
                if covered_by:
                    selectable = item_type != "dir"
                    item_size = int(entry.get("size") or 0) if selectable else int(dir_size_by_path.get(item_path, 0))
                    preview_items.append(
                        self._build_preview_item(
                            path=item_path,
                            relative_path=str(entry.get("relative_path") or ""),
                            item_type=item_type,
                            size=item_size,
                            modified_time=entry.get("modified_time"),
                            selectable=selectable,
                            covered_by=covered_by,
                            delete_path=item_path,
                            size_status="ready" if selectable else "estimated",
                            delete_scope="self" if selectable else "preview_child",
                        )
                    )
                    if selectable:
                        selected_count += 1
                        selected_size += item_size
                    continue

                matched_rules = self._match_filter_rule_names(
                    str(entry.get("name") or ""),
                    "folder" if item_type == "dir" else "file",
                    active_rules,
                    relative_path=str(entry.get("relative_path") or ""),
                    full_path=item_path,
                )
                if not matched_rules:
                    continue
                item_size = int(dir_size_by_path.get(item_path, 0)) if item_type == "dir" else int(entry.get("size") or 0)
                preview_items.append(
                    self._build_preview_item(
                        path=item_path,
                        relative_path=str(entry.get("relative_path") or ""),
                        item_type=item_type,
                        size=item_size,
                        modified_time=entry.get("modified_time"),
                        matched_rules=matched_rules,
                        size_status="estimated" if item_type == "dir" else "ready",
                        delete_scope="preview_parent" if item_type == "dir" else "self",
                    )
                )
                if item_type == "dir":
                    covered_roots.append(item_path)
                else:
                    selected_count += 1
                    selected_size += item_size

            preview_items.sort(key=lambda item: (item["relative_path"].count("/"), item["relative_path"].lower(), item["type"] != "dir"))
            self._append_stats_log(
                library,
                "INFO",
                f"远程删除过滤预审读取 Search path={target_path} scanned={len(entries)} matched={selected_count} elapsed={time.time() - started_at:.2f}s truncated={truncated}",
            )
            return {
                "folder_name": PurePosixPath(target_path).name or target_path,
                "folder_path": target_path,
                "rules": active_rules,
                "items": preview_items,
                "selected_count": selected_count,
                "selected_size": selected_size,
                "selected_size_exact": not truncated,
                "size_disabled": False,
                "truncated": truncated,
                "truncated_reason": f"远程搜索结果超过 {max_entries} 项，当前仅显示前 {max_entries} 项预审结果" if truncated else "",
                "scanned_entries": len(entries),
                "discovered_entries": total or len(entries),
                "browse_via_search": True,
            }
        except Exception:
            logger.warning("远程删除过滤预审 Search 快速路径失败，回退目录遍历: lib=%s path=%s", library.id, target_path, exc_info=True)
            return None
        finally:
            if task_id:
                try:
                    await client.stop_search(task_id)
                except Exception:
                    logger.debug("停止远程删除过滤 Search 任务失败: task_id=%s", task_id, exc_info=True)

    async def _remote_filter_delete_preview(
        self,
        library: LibraryDefinition,
        path: str,
        rules: Optional[list[Any]] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        _, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="删除过滤预审",
        )

        active_rules = self._normalize_filter_rules(rules)
        if not active_rules:
            return self._empty_filter_delete_preview(target_path, active_rules, folder_name=PurePosixPath(target_path).name or target_path)
        indexed_preview = self._filter_delete_preview_via_index(library, target_path, active_rules)
        if indexed_preview is not None:
            self._append_stats_log(
                library,
                "INFO",
                f"远程删除过滤预审读取索引 path={target_path} matched={indexed_preview.get('selected_count')}",
            )
            return indexed_preview
        normalized_request_id = str(request_id or "").strip()
        self._begin_filter_preview_request(normalized_request_id)
        client = self._create_filter_preview_client(library)
        info = await client.stat(target_path)
        info_item = self._first_remote_info_item(info)
        if not info_item or not info_item.get("isdir", False):
            raise FileNotFoundError("目标文件夹不存在")

        search_preview = await self._remote_filter_delete_preview_via_search(client, library, target_path, active_rules)
        if search_preview is not None:
            return search_preview

        preview_items: list[dict[str, Any]] = []
        selected_count = 0
        selected_size = 0
        preview_state = self._create_remote_filter_preview_state(client, normalized_request_id)

        async def walk(current_path: str):
            nonlocal selected_count, selected_size
            if preview_state.get("truncated"):
                return
            try:
                children = await self._list_remote_directory(client, current_path)
            except Exception as exc:
                logger.warning("远程过滤删除预览读取目录失败 %s: %s", current_path, exc)
                self._mark_remote_filter_preview_truncated(
                    preview_state,
                    f"Failed to read remote directory; preview stopped at {PurePosixPath(current_path).name or current_path}",
                )
                return
            remaining_directories: list[dict[str, Any]] = []
            for child in children:
                if not self._touch_remote_filter_preview_entry(preview_state):
                    break
                name = child.get("name") or ""
                if self._should_skip_filter_preview_name(name):
                    continue
                if child.get("isdir", False):
                    remaining_directories.append(child)
                    continue
                raw_child_path = child.get("path") or child.get("real_path") or ""
                child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                matched_rules = self._match_filter_rule_names(
                    name,
                    "file",
                    active_rules,
                    relative_path=relative_path,
                    full_path=child_path,
                )
                if not matched_rules:
                    continue
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime")
                modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                size = int(additional.get("size") or 0)
                preview_items.append(
                    self._build_preview_item(
                        path=child_path,
                        relative_path=relative_path,
                        item_type="file",
                        size=size,
                        modified_time=modified_time,
                        matched_rules=matched_rules,
                        size_status="ready",
                    )
                )
                selected_count += 1
                selected_size += size

            for child in remaining_directories:
                name = child.get("name") or ""
                raw_child_path = child.get("path") or child.get("real_path") or ""
                child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime")
                modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                matched_rules = self._match_filter_rule_names(
                    name,
                    "folder",
                    active_rules,
                    relative_path=relative_path,
                    full_path=child_path,
                )
                if matched_rules:
                    descendants, folder_size = await self._collect_remote_filter_preview_descendants(
                        client,
                        target_path,
                        child_path,
                        child_path,
                        preview_state,
                    )
                    preview_items.append(
                        self._build_preview_item(
                            path=child_path,
                            relative_path=relative_path,
                            item_type="dir",
                            size=folder_size,
                            modified_time=modified_time,
                            matched_rules=matched_rules,
                            size_status="partial" if preview_state.get("truncated") else "estimated",
                            delete_scope="preview_parent",
                        )
                    )
                    preview_items.extend(descendants)
                    selected_count += sum(1 for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    selected_size += sum(int(item.get("size") or 0) for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    continue
                await walk(child_path)

        await walk(target_path)
        preview_items.sort(key=lambda item: (item["relative_path"].count("/"), item["relative_path"].lower(), item["type"] != "dir"))
        return {
            "folder_name": PurePosixPath(target_path).name or target_path,
            "folder_path": target_path,
            "rules": active_rules,
            "items": preview_items,
            "selected_count": selected_count,
            "selected_size": selected_size,
            "selected_size_exact": not preview_state.get("truncated"),
            "size_disabled": False,
            "truncated": bool(preview_state.get("truncated")),
            "truncated_reason": str(preview_state.get("reason") or ""),
            "scanned_entries": int(preview_state.get("visited_entries") or 0),
        }

    async def filter_delete_preview(
        self,
        library_id: str,
        path: str,
        rules: Optional[list[Any]] = None,
        request_id: Optional[str] = None,
        target_items: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        targets = self._normalize_filter_delete_targets(library_id, path, target_items)
        if target_items is not None and targets:
            active_rules = self._normalize_filter_rules(rules)
            if not active_rules:
                merged = self._merge_filter_delete_preview_results(
                    targets,
                    [self._empty_filter_delete_preview(str(target["path"]), active_rules, folder_name=str(target.get("name") or "")) for target in targets],
                    active_rules,
                )
                merged["status"] = "completed"
                merged["progress_message"] = "没有启用的过滤规则"
                return merged
            results: list[dict[str, Any]] = []
            for target in targets:
                library = target["library"]
                target_path = str(target["path"])
                if library.type == "local":
                    result = await asyncio.to_thread(self._local_filter_delete_preview, library, target_path, active_rules)
                else:
                    result = await self._remote_filter_delete_preview(library, target_path, active_rules, request_id)
                results.append(result)
            return self._merge_filter_delete_preview_results(targets, results, active_rules)
        if targets:
            library = targets[0]["library"]
            path = str(targets[0]["path"])
        else:
            library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_filter_delete_preview, library, path, rules)
        return await self._remote_filter_delete_preview(library, path, rules, request_id)

    async def start_filter_delete_preview_job(
        self,
        library_id: str,
        path: str,
        rules: Optional[list[Any]] = None,
        target_items: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        targets = self._normalize_filter_delete_targets(library_id, path, target_items)
        if target_items is not None and targets:
            active_rules = self._normalize_filter_rules(rules)
            if not active_rules:
                merged = self._merge_filter_delete_preview_results(
                    targets,
                    [self._empty_filter_delete_preview(str(target["path"]), active_rules, folder_name=str(target.get("name") or "")) for target in targets],
                    active_rules,
                )
                merged["status"] = "completed"
                merged["progress_message"] = "没有启用的过滤规则"
                return merged
            indexed_results: list[dict[str, Any]] = []
            all_indexed = True

            for target in targets:
                library = target["library"]
                target_path = str(target["path"])
                indexed_preview = self._filter_delete_preview_via_index(library, target_path, active_rules)
                if indexed_preview is not None:
                    indexed_preview["status"] = "completed"
                    indexed_preview["progress_message"] = "索引预审完成"
                    indexed_preview["current_path"] = target_path
                    indexed_preview["pending_directories"] = 0
                    indexed_results.append(indexed_preview)
                    self._append_stats_log(
                        library,
                        "INFO",
                        f"批量删除过滤预审读取索引 path={target_path} matched={indexed_preview.get('selected_count')}",
                    )
                    continue
                all_indexed = False
                break

            if all_indexed:
                merged = self._merge_filter_delete_preview_results(targets, indexed_results, active_rules)
                merged["status"] = "completed"
                merged["progress_message"] = "索引预审完成"
                return merged

            # 只要存在非索引目标，就保持后台任务模型；批任务内部仍会逐目标优先读索引。
            job_id = uuid.uuid4().hex
            job = self._init_filter_preview_job(job_id, targets[0]["library"], "", active_rules)
            job.update({
                "library_id": "",
                "library_name": "多个库存",
                "folder_name": f"已选目录（{len(targets)} 项）",
                "folder_path": "",
                "pending_directories": len(targets),
                "progress_message": "已创建批量删除过滤预审任务",
                "target_items": [
                    {
                        "library_id": str(target.get("library_id") or ""),
                        "library_name": str(target.get("library_name") or ""),
                        "path": str(target.get("path") or ""),
                        "name": str(target.get("name") or ""),
                    }
                    for target in targets
                ],
            })
            task = asyncio.create_task(self._run_filter_delete_preview_batch_job(job_id, targets, active_rules))
            self._filter_preview_tasks[job_id] = task
            return self._build_filter_preview_job_response(self._filter_preview_jobs[job_id])

        if targets:
            library = targets[0]["library"]
            path = str(targets[0]["path"])
        else:
            library = self.get_library_definition(library_id)
        if library.type == "local":
            preview = await asyncio.to_thread(self._local_filter_delete_preview, library, path, rules)
            preview["status"] = "completed"
            preview["progress_message"] = "本地预审完成"
            preview["current_path"] = path
            preview["scanned_entries"] = int(preview.get("selected_count") or len(preview.get("items") or []))
            preview["discovered_entries"] = int(preview.get("scanned_entries") or 0)
            preview["pending_directories"] = 0
            return preview
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        _, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="删除过滤预审",
        )

        active_rules = self._normalize_filter_rules(rules)
        if not active_rules:
            preview = self._empty_filter_delete_preview(target_path, active_rules, folder_name=PurePosixPath(target_path).name or target_path)
            preview["status"] = "completed"
            preview["progress_message"] = "没有启用的过滤规则"
            return preview
        indexed_preview = self._filter_delete_preview_via_index(library, target_path, active_rules)
        if indexed_preview is not None:
            indexed_preview["status"] = "completed"
            indexed_preview["progress_message"] = "索引预审完成"
            indexed_preview["current_path"] = target_path
            indexed_preview["pending_directories"] = 0
            self._append_stats_log(
                library,
                "INFO",
                f"远程删除过滤预审任务读取索引 path={target_path} matched={indexed_preview.get('selected_count')}",
            )
            return indexed_preview
        job_id = uuid.uuid4().hex
        self._append_stats_log(
            library,
            "INFO",
            f"预审开始 job={job_id} path={target_path} rules={len(active_rules)}",
        )
        self._init_filter_preview_job(job_id, library, target_path, active_rules)
        logger.info("删除过滤预审开始 library=%s job=%s path=%s rules=%s", library.id, job_id, target_path, len(active_rules))
        task = asyncio.create_task(self._run_remote_filter_delete_preview_job(job_id, library, target_path, active_rules))
        self._filter_preview_tasks[job_id] = task
        return self._build_filter_preview_job_response(self._filter_preview_jobs[job_id])

    def get_filter_delete_preview_job(self, job_id: str) -> dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("缺少预审任务 ID")
        job = self._filter_preview_jobs.get(normalized_job_id)
        if not job:
            raise KeyError(normalized_job_id)
        return self._build_filter_preview_job_response(job)

    async def cancel_filter_delete_preview_job(self, job_id: str) -> dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("缺少预审任务 ID")
        task = self._filter_preview_tasks.get(normalized_job_id)
        job = self._filter_preview_jobs.get(normalized_job_id)
        if not task and not job:
            raise KeyError(normalized_job_id)
        if task and not task.done():
            task.cancel()
        if job:
            library_id = str(job.get("library_id") or "").strip()
            if library_id:
                self._append_stats_log(
                    self.get_library_definition(library_id),
                    "WARN",
                    f"预审取消请求 job={normalized_job_id} path={job.get('folder_path') or ''}",
                )
        logger.warning("删除过滤预审取消请求 job=%s", normalized_job_id)
        if job:
            self._update_filter_preview_job(
                normalized_job_id,
                status="canceled",
                progress_message="删除过滤预审已取消",
                warning="预审已取消，请重新扫描后再删除",
            )
            return self._build_filter_preview_job_response(job)
        return {
            "job_id": normalized_job_id,
            "status": "canceled",
            "progress_message": "删除过滤预审已取消",
            "warning": "预审已取消，请重新扫描后再删除",
        }

    async def _run_remote_filter_delete_preview_job(
        self,
        job_id: str,
        library: LibraryDefinition,
        target_path: str,
        active_rules: list[dict[str, str]],
    ) -> None:
        client = self._create_filter_preview_client(library)
        preview_items: list[dict[str, Any]] = []
        selected_count = 0
        selected_size = 0
        scanned_entries = 0
        discovered_entries = 0
        pending_directories = 1
        last_publish_at = 0.0
        last_progress_log_at = 0.0
        last_progress_log_entries = 0
        request_semaphore = asyncio.Semaphore(1)
        skipped_directory_count = 0
        skipped_directory_examples: list[str] = []
        self._update_filter_preview_job(job_id, status="running", items=preview_items)

        search_preview = await self._remote_filter_delete_preview_via_search(client, library, target_path, active_rules)
        if search_preview is not None:
            self._update_filter_preview_job(
                job_id,
                status="completed",
                items=list(search_preview.get("items") or []),
                selected_count=int(search_preview.get("selected_count") or 0),
                selected_size=int(search_preview.get("selected_size") or 0),
                selected_size_exact=bool(search_preview.get("selected_size_exact", True)),
                size_disabled=bool(search_preview.get("size_disabled", False)),
                scanned_entries=int(search_preview.get("scanned_entries") or 0),
                discovered_entries=int(search_preview.get("discovered_entries") or 0),
                pending_directories=0,
                current_path=target_path,
                progress_message="删除过滤预审完成",
                warning=str(search_preview.get("warning") or ""),
                error="",
                truncated=bool(search_preview.get("truncated", False)),
                truncated_reason=str(search_preview.get("truncated_reason") or ""),
            )
            self._filter_preview_tasks.pop(job_id, None)
            return

        def build_scan_warning() -> str:
            if skipped_directory_count <= 0:
                return ""
            sample = ""
            if skipped_directory_examples:
                sample = f"，例如 {skipped_directory_examples[0]}"
            return f"扫描时跳过 {skipped_directory_count} 个目录，当前结果不完整{sample}"

        def publish(force: bool = False, **fields: Any) -> None:
            nonlocal last_publish_at, last_progress_log_at, last_progress_log_entries
            now = time.time()
            if not force and (now - last_publish_at) < 0.4:
                return
            last_publish_at = now
            payload = dict(fields)
            if skipped_directory_count > 0 and "warning" not in payload and str(payload.get("status") or "") not in {"error", "canceled"}:
                payload["warning"] = build_scan_warning()
            self._update_filter_preview_job(job_id, **payload)
            should_log_progress = (
                force
                or scanned_entries == 0
                or (scanned_entries - last_progress_log_entries) >= 200
                or (now - last_progress_log_at) >= 10
            )
            if should_log_progress:
                current_path = str(fields.get("current_path") or self._filter_preview_jobs.get(job_id, {}).get("current_path") or target_path)
                progress_message = str(fields.get("progress_message") or self._filter_preview_jobs.get(job_id, {}).get("progress_message") or "")
                status = str(fields.get("status") or self._filter_preview_jobs.get(job_id, {}).get("status") or "pending")
                self._append_stats_log(
                    library,
                    "INFO",
                    f"预审进度 job={job_id} status={status} scanned={scanned_entries} matched={selected_count} pending={pending_directories} current={current_path} message={progress_message}",
                )
                last_progress_log_at = now
                last_progress_log_entries = scanned_entries

        async def record_skipped_directory(current_path: str, exc: Exception) -> None:
            nonlocal skipped_directory_count
            skipped_directory_count += 1
            example = PurePosixPath(current_path).name or current_path
            if len(skipped_directory_examples) < 3:
                skipped_directory_examples.append(example)
            logger.warning("删除过滤预审跳过目录 %s: %s", current_path, exc)
            self._append_stats_log(
                library,
                "WARN",
                f"预审跳过目录 path={current_path} error={exc}",
            )
            publish(
                True,
                current_path=current_path,
                warning=build_scan_warning(),
                progress_message=f"跳过目录 {example}",
                scanned_entries=scanned_entries,
                discovered_entries=discovered_entries,
                pending_directories=pending_directories,
            )

        def is_retryable_preview_error(exc: Exception) -> bool:
            if isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError, OSError)):
                return True
            message = str(exc or "").lower()
            return (
                "cannot connect to host" in message
                or "timeout" in message
                or "信号灯超时时间已到" in str(exc)
                or "由本地系统中止网络连接" in str(exc)
            )

        async def list_children(current_path: str) -> Optional[list[dict[str, Any]]]:
            retry_attempt = 0
            while True:
                async with request_semaphore:
                    try:
                        return await self._list_remote_directory_with_retry(
                            client,
                            current_path,
                            retries=1,
                            retry_delay_seconds=2.0,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if is_retryable_preview_error(exc):
                            retry_attempt += 1
                            retry_wait = min(15.0, max(2.0, retry_attempt * 2.0))
                            if retry_attempt == 1 or retry_attempt % 5 == 0:
                                self._append_stats_log(
                                    library,
                                    "WARN",
                                    f"预审重试 path={current_path} attempt={retry_attempt} error={exc}",
                                )
                            publish(
                                True,
                                current_path=current_path,
                                progress_message=f"目录响应超时，正在重试（第 {retry_attempt} 次）",
                                scanned_entries=scanned_entries,
                                discovered_entries=discovered_entries,
                                pending_directories=pending_directories,
                            )
                        else:
                            await record_skipped_directory(current_path, exc)
                            return None
                await asyncio.sleep(retry_wait)

        async def stat_target(current_path: str) -> dict[str, Any]:
            attempt = 0
            while True:
                try:
                    return await client.stat(current_path)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    attempt += 1
                    if not is_retryable_preview_error(exc):
                        raise
                    retry_wait = min(15.0, max(2.0, attempt * 2.0))
                    if attempt == 1 or attempt % 5 == 0:
                        self._append_stats_log(
                            library,
                            "WARN",
                            f"预审根目录重试 path={current_path} attempt={attempt} error={exc}",
                        )
                    publish(
                        True,
                        current_path=current_path,
                        progress_message=f"根目录读取超时，正在重试（第 {attempt} 次）",
                        scanned_entries=scanned_entries,
                        discovered_entries=discovered_entries,
                        pending_directories=pending_directories,
                    )
                    await asyncio.sleep(retry_wait)

        async def collect_descendants(folder_path: str) -> int:
            nonlocal scanned_entries, discovered_entries, pending_directories

            async def walk(current_path: str) -> int:
                nonlocal scanned_entries, discovered_entries, pending_directories
                subtotal = 0
                publish(current_path=current_path, progress_message=f"正在扫描 {PurePosixPath(current_path).name or current_path}", scanned_entries=scanned_entries)
                children = await list_children(current_path)
                if children is None:
                    pending_directories = max(0, pending_directories - 1)
                    publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                    return subtotal
                discovered_entries += len(children)
                publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                child_tasks: list[asyncio.Task[int]] = []
                for child in children:
                    scanned_entries += 1
                    name = child.get("name") or ""
                    if self._should_skip_filter_preview_name(name):
                        continue
                    raw_child_path = child.get("path") or child.get("real_path") or ""
                    child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                    additional = child.get("additional", {}) or {}
                    if child.get("isdir", False):
                        pending_directories += 1
                        child_tasks.append(asyncio.create_task(walk(child_path)))
                        publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                        continue
                    file_size = int(additional.get("size") or 0)
                    subtotal += file_size
                    publish(
                        scanned_entries=scanned_entries,
                        discovered_entries=discovered_entries,
                        pending_directories=pending_directories,
                        selected_count=selected_count,
                        selected_size=selected_size,
                    )
                if child_tasks:
                    subtotal += sum(int(value or 0) for value in await asyncio.gather(*child_tasks))
                pending_directories = max(0, pending_directories - 1)
                publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                return subtotal

            return await walk(folder_path)

        async def walk(current_path: str) -> None:
            nonlocal selected_count, selected_size, scanned_entries, discovered_entries, pending_directories
            publish(status="pending", current_path=current_path, progress_message=f"正在扫描 {PurePosixPath(current_path).name or current_path}", scanned_entries=scanned_entries)
            children = await list_children(current_path)
            if children is None:
                pending_directories = max(0, pending_directories - 1)
                publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                return
            discovered_entries += len(children)
            publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
            matched_directories: list[tuple[str, str, Optional[str], list[str]]] = []
            unmatched_directory_paths: list[str] = []
            for child in children:
                scanned_entries += 1
                name = child.get("name") or ""
                if self._should_skip_filter_preview_name(name):
                    continue
                if child.get("isdir", False):
                    raw_child_path = child.get("path") or child.get("real_path") or ""
                    child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                    additional = child.get("additional", {}) or {}
                    timestamp = additional.get("time", {}).get("mtime")
                    modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                    relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                    matched_rules = self._match_filter_rule_names(
                        name,
                        "folder",
                        active_rules,
                        relative_path=relative_path,
                        full_path=child_path,
                    )
                    if matched_rules:
                        matched_directories.append((child_path, relative_path, modified_time, matched_rules))
                    else:
                        unmatched_directory_paths.append(child_path)
                    continue
                raw_child_path = child.get("path") or child.get("real_path") or ""
                child_path = self._normalize_remote_path(raw_child_path or str(PurePosixPath(current_path) / name))
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                matched_rules = self._match_filter_rule_names(
                    name,
                    "file",
                    active_rules,
                    relative_path=relative_path,
                    full_path=child_path,
                )
                if not matched_rules:
                    continue
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime")
                modified_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else None
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                size = int(additional.get("size") or 0)
                preview_items.append(
                    self._build_preview_item(
                        path=child_path,
                        relative_path=relative_path,
                        item_type="file",
                        size=size,
                        modified_time=modified_time,
                        matched_rules=matched_rules,
                        size_status="ready",
                    )
                )
                selected_count += 1
                selected_size += size
                publish(
                    scanned_entries=scanned_entries,
                    discovered_entries=discovered_entries,
                    pending_directories=pending_directories,
                    selected_count=selected_count,
                    selected_size=selected_size,
                )

            if matched_directories:
                pending_directories += len(matched_directories)
                publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                folder_descendants = await asyncio.gather(
                    *(
                        self._collect_remote_filter_preview_descendants(
                            client,
                            target_path,
                            item[0],
                            item[0],
                        )
                        for item in matched_directories
                    )
                )
                for directory_item, descendant_result in zip(matched_directories, folder_descendants):
                    child_path, relative_path, modified_time, matched_rules = directory_item
                    descendants, folder_size = descendant_result
                    folder_size_status = "partial" if any(str(item.get("size_status") or "") == "partial" for item in descendants) else "estimated"
                    preview_items.append(
                        self._build_preview_item(
                            path=child_path,
                            relative_path=relative_path,
                            item_type="dir",
                            size=folder_size,
                            modified_time=modified_time,
                            matched_rules=matched_rules,
                            size_status=folder_size_status,
                            delete_scope="preview_parent",
                        )
                    )
                    preview_items.extend(descendants)
                    selected_count += sum(1 for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    selected_size += sum(int(item.get("size") or 0) for item in descendants if item.get("type") == "file" and item.get("delete_scope") == "self")
                    publish(
                        scanned_entries=scanned_entries,
                        discovered_entries=discovered_entries,
                        pending_directories=pending_directories,
                        selected_count=selected_count,
                        selected_size=selected_size,
                    )
            if unmatched_directory_paths:
                pending_directories += len(unmatched_directory_paths)
                publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)
                await asyncio.gather(*(walk(child_path) for child_path in unmatched_directory_paths))
            pending_directories = max(0, pending_directories - 1)
            publish(scanned_entries=scanned_entries, discovered_entries=discovered_entries, pending_directories=pending_directories)

        try:
            info = await stat_target(target_path)
            info_item = self._first_remote_info_item(info)
            if not info_item or not info_item.get("isdir", False):
                raise FileNotFoundError("目标文件夹不存在")
            await walk(target_path)
            preview_items.sort(key=lambda item: (item["relative_path"].count("/"), item["relative_path"].lower(), item["type"] != "dir"))
            publish(
                True,
                status="completed",
                selected_count=selected_count,
                selected_size=selected_size,
                scanned_entries=scanned_entries,
                discovered_entries=discovered_entries,
                pending_directories=0,
                current_path=target_path,
                progress_message="删除过滤预审完成",
                warning=build_scan_warning(),
                error="",
                selected_size_exact=skipped_directory_count == 0,
            )
            logger.info("删除过滤预审完成 job=%s path=%s scanned=%s matched=%s size=%s", job_id, target_path, scanned_entries, selected_count, selected_size)
            self._append_stats_log(
                library,
                "INFO",
                f"预审完成 job={job_id} path={target_path} scanned={scanned_entries} matched={selected_count} size={selected_size} skipped={skipped_directory_count}",
            )
        except asyncio.CancelledError:
            publish(
                True,
                status="canceled",
                items=list(preview_items),
                selected_count=selected_count,
                selected_size=selected_size,
                selected_size_exact=False,
                scanned_entries=scanned_entries,
                discovered_entries=discovered_entries,
                pending_directories=0,
                progress_message="删除过滤预审已取消",
                warning="预审已取消，请重新扫描后再删除",
            )
            logger.warning("删除过滤预审已取消 job=%s path=%s scanned=%s matched=%s", job_id, target_path, scanned_entries, selected_count)
            self._append_stats_log(
                library,
                "WARN",
                f"预审取消 job={job_id} path={target_path} scanned={scanned_entries} matched={selected_count}",
            )
            raise
        except Exception as exc:
            logger.error("删除过滤预审失败 %s: %s", target_path, exc, exc_info=True)
            publish(
                True,
                status="error",
                items=list(preview_items),
                selected_count=selected_count,
                selected_size=selected_size,
                selected_size_exact=False,
                scanned_entries=scanned_entries,
                discovered_entries=discovered_entries,
                pending_directories=0,
                progress_message="删除过滤预审失败",
                warning="预审未完整完成，当前结果不可直接用于删除",
                error=str(exc),
            )
            self._append_stats_log(
                library,
                "ERROR",
                f"预审失败 job={job_id} path={target_path} scanned={scanned_entries} matched={selected_count} error={exc}",
            )
        finally:
            self._filter_preview_tasks.pop(job_id, None)

    async def _run_filter_delete_preview_batch_job(
        self,
        job_id: str,
        targets: list[dict[str, Any]],
        active_rules: list[dict[str, str]],
    ) -> None:
        results: list[dict[str, Any]] = []
        scanned_entries = 0
        discovered_entries = 0
        pending_directories = len(targets)
        failed_targets: list[dict[str, str]] = []
        try:
            self._update_filter_preview_job(
                job_id,
                status="running",
                pending_directories=pending_directories,
                progress_message=f"正在预审 1 / {len(targets)}",
            )
            for index, target in enumerate(targets):
                library = target["library"]
                target_path = str(target["path"])
                self._update_filter_preview_job(
                    job_id,
                    status="running",
                    current_path=target_path,
                    pending_directories=max(0, pending_directories),
                    progress_message=f"正在预审 {index + 1} / {len(targets)}: {target.get('name') or target_path}",
                )
                try:
                    indexed_preview = self._filter_delete_preview_via_index(library, target_path, active_rules)
                    if indexed_preview is not None:
                        result = indexed_preview
                        result["status"] = "completed"
                        result["progress_message"] = "索引预审完成"
                    elif library.type == "local":
                        result = await asyncio.to_thread(self._local_filter_delete_preview, library, target_path, active_rules)
                    else:
                        result = await self._remote_filter_delete_preview(library, target_path, active_rules)
                    result["status"] = result.get("status") or "completed"
                    results.append(result)
                    scanned_entries += int(result.get("scanned_entries") or 0)
                    discovered_entries += int(result.get("discovered_entries") or 0)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error = str(exc)
                    logger.warning("批量删除过滤预审单项目标失败 library=%s path=%s error=%s", library.id, target_path, error, exc_info=True)
                    result = {
                        "status": "error",
                        "error": error,
                        "items": [],
                        "selected_count": 0,
                        "selected_size": 0,
                        "scanned_entries": 0,
                        "discovered_entries": 0,
                    }
                    results.append(result)
                    failed_targets.append({
                        "library_id": library.id,
                        "library_name": library.name,
                        "path": target_path,
                        "name": str(target.get("name") or ""),
                        "error": error,
                    })
                pending_directories = max(0, pending_directories - 1)
                self._update_filter_preview_job(
                    job_id,
                    scanned_entries=scanned_entries,
                    discovered_entries=discovered_entries,
                    pending_directories=pending_directories,
                )

            merged = self._merge_filter_delete_preview_results(targets, results, active_rules)
            merged_status = "error" if failed_targets and len(failed_targets) == len(targets) else "completed"
            self._update_filter_preview_job(
                job_id,
                **{
                    **merged,
                    "status": merged_status,
                    "progress_message": "删除过滤预审完成" if merged_status == "completed" else "删除过滤预审失败",
                    "pending_directories": 0,
                    "failed_targets": merged.get("failed_targets") or failed_targets,
                },
            )
        except asyncio.CancelledError:
            self._update_filter_preview_job(
                job_id,
                status="canceled",
                pending_directories=0,
                selected_size_exact=False,
                progress_message="删除过滤预审已取消",
                warning="预审已取消，请重新扫描后再删除",
            )
            raise
        except Exception as exc:
            logger.error("批量删除过滤预审失败 job=%s: %s", job_id, exc, exc_info=True)
            self._update_filter_preview_job(
                job_id,
                status="error",
                pending_directories=0,
                selected_size_exact=False,
                progress_message="删除过滤预审失败",
                warning="预审未完整完成，当前结果不可直接用于删除",
                error=str(exc),
            )
        finally:
            self._filter_preview_tasks.pop(job_id, None)

    async def delete(
        self,
        library_id: str,
        path: str,
        confirmed: bool = False,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(
                self._local_delete,
                library,
                path,
                confirmed,
                skip_index_mutation=skip_index_mutation,
            )
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        _, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="删除",
        )
        client = self.get_cached_synology_client(library.synology)
        if not confirmed:
            preview = await self._remote_delete_preview(client, target_path, library)
            preview["need_confirm"] = True
            self._append_stats_log(library, "INFO", f"删除预检 path={target_path} type={preview.get('type') or 'unknown'}")
            return preview
        preview = await self._remote_delete_preview(client, target_path, library)
        self._append_stats_log(
            library,
            "INFO",
            f"删除开始 path={target_path} type={preview.get('type') or 'unknown'} size={int(preview.get('size') or 0)}",
        )
        await client.delete(target_path)
        self._apply_remote_stats_deletion(
            library,
            deleted_bytes=int(preview.get("size") or 0),
            deleted_folder_count=int(preview.get("folder_count") or 0),
        )
        # 远程库不维护库存索引；通知方法会直接跳过，仅保留兼容调用。
        self._notify_index_self_mutation_delete(library, target_path)
        self._append_stats_log(
            library,
            "INFO",
            f"删除完成 path={target_path} type={preview.get('type') or 'unknown'} size={int(preview.get('size') or 0)}",
        )
        return {"message": "删除成功", "path": target_path}

    async def _remote_batch_delete(self, library: LibraryDefinition, paths: list[str], confirmed: bool) -> dict[str, Any]:
        client = self.get_cached_synology_client(library.synology)
        if not confirmed:
            indexed_preview = self._batch_delete_preview_via_index(library, paths)
            if indexed_preview is not None:
                self._append_stats_log(library, "INFO", f"批删预检读取索引 total={len(paths)} size={indexed_preview.get('total_size')}")
                return indexed_preview
            previews = await asyncio.gather(
                *(self._remote_delete_preview(client, path, library) for path in paths),
                return_exceptions=True,
            )
            for preview in previews:
                if isinstance(preview, Exception):
                    continue
            self._append_stats_log(library, "INFO", f"批删预检 total={len(paths)}")
            return {
                "need_confirm": True,
                "total_count": len(paths),
                "total_size": None,
                "total_folder_count": 0,
                "size_disabled": True,
            }

        self._append_stats_log(
            library,
            "INFO",
            f"批删开始 total={len(paths)}",
        )
        previews = await asyncio.gather(
            *(self._remote_delete_preview(client, path, library) for path in paths),
            return_exceptions=True,
        )
        success_count = 0
        deleted_bytes = 0
        deleted_folder_count = 0
        failed_paths: list[dict[str, str]] = []
        successful_paths: list[str] = []
        for path, preview in zip(paths, previews):
            if isinstance(preview, Exception):
                failed_paths.append({"path": path, "error": str(preview)})
                self._append_stats_log(library, "ERROR", f"批删预检失败 path={path} error={preview}")
                continue
            try:
                await client.delete(path)
                success_count += 1
                successful_paths.append(path)
                deleted_bytes += int(preview.get("size") or 0)
                deleted_folder_count += int(preview.get("folder_count") or 0)
                self._append_stats_log(
                    library,
                    "INFO",
                    f"批删单项完成 path={path} size={int(preview.get('size') or 0)} success={success_count}/{len(paths)}",
                )
            except Exception as exc:
                failed_paths.append({"path": path, "error": str(exc)})
                self._append_stats_log(library, "ERROR", f"批删单项失败 path={path} error={exc}")
        if success_count:
            self._apply_remote_stats_deletion(
                library,
                deleted_bytes=deleted_bytes,
                deleted_folder_count=deleted_folder_count,
            )
        # 远程库不维护库存索引；通知方法会直接跳过，仅保留兼容调用。
        self._notify_index_self_mutation_delete_batch(library, successful_paths)
        self._append_stats_log(
            library,
            "INFO",
            f"批删结束 success={success_count} failed={len(failed_paths)} bytes={deleted_bytes}",
        )
        return {"message": "批量删除完成", "success_count": success_count, "failed_paths": failed_paths}

    async def batch_delete(
        self,
        library_id: str,
        paths: list[str],
        confirmed: bool = False,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(
                self._local_batch_delete,
                library,
                paths,
                confirmed,
                skip_index_mutation=skip_index_mutation,
            )
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        normalized_paths = [
            self._resolve_remote_operation_path(
                library,
                path,
                action="批量删除",
            )[1]
            for path in paths
        ]
        return await self._remote_batch_delete(library, normalized_paths, confirmed)

    async def batch_delete_targets(
        self,
        targets: list[dict[str, Any]],
        confirmed: bool = False,
        *,
        skip_index_mutation: bool = False,
    ) -> dict[str, Any]:
        grouped: dict[str, list[str]] = {}
        ordered_targets: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in targets or []:
            if not isinstance(item, dict):
                continue
            library_id = str(item.get("library_id") or "").strip()
            path = str(item.get("path") or item.get("delete_path") or "").strip()
            if not library_id or not path:
                continue
            library = self.get_library_definition(library_id)
            if library.type == "synology_filestation":
                _, normalized_path = self._resolve_remote_operation_path(library, path, action="批量删除")
            else:
                self._assert_local_path_in_library(library, path)
                normalized_path = os.path.abspath(path)
            key = (library.id, normalized_path.replace("\\", "/").rstrip("/") or "/")
            if key in seen:
                continue
            seen.add(key)
            grouped.setdefault(library.id, []).append(normalized_path)
            ordered_targets.append({"library_id": library.id, "path": normalized_path})

        if not ordered_targets:
            raise ValueError("路径列表不能为空")

        success_count = 0
        failed_paths: list[dict[str, str]] = []
        success_paths: list[dict[str, str]] = []
        total_size = 0
        total_file_count = 0
        total_folder_count = 0
        size_disabled = False

        for item_library_id, paths in grouped.items():
            result = await self.batch_delete(
                item_library_id,
                paths,
                confirmed=confirmed,
                skip_index_mutation=skip_index_mutation,
            )
            failed_set = {
                str((failed or {}).get("path") or "").strip()
                for failed in (result.get("failed_paths") or [])
                if isinstance(failed, dict)
            }
            if confirmed:
                group_success = int(result.get("success_count") or 0)
                success_count += group_success
                for path in paths:
                    if path in failed_set:
                        continue
                    success_paths.append({"library_id": item_library_id, "path": path})
            else:
                total_size += int(result.get("total_size") or 0)
                total_file_count += int(result.get("total_file_count") or 0)
                total_folder_count += int(result.get("total_folder_count") or 0)
                size_disabled = size_disabled or bool(result.get("size_disabled", False))
            for failed in result.get("failed_paths") or []:
                if not isinstance(failed, dict):
                    continue
                failed_paths.append({
                    "library_id": item_library_id,
                    "path": str(failed.get("path") or ""),
                    "error": str(failed.get("error") or ""),
                })

        if confirmed:
            return {
                "message": "批量删除完成",
                "success_count": success_count,
                "failed_paths": failed_paths,
                "success_paths": success_paths,
            }
        return {
            "need_confirm": True,
            "total_count": len(ordered_targets),
            "total_size": None if size_disabled else total_size,
            "total_file_count": total_file_count,
            "total_folder_count": total_folder_count,
            "size_disabled": size_disabled,
        }

    def _collect_local_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        # 统计只允许走索引。索引未就绪时不做 os.scandir / os.walk，避免慢盘或网络盘 IO。
        indexed = self._collect_local_stats_via_index(library)
        if indexed is not None:
            return indexed
        self._append_stats_log(library, "WARN", "索引未就绪，跳过库存统计以避免磁盘 IO")
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "idle",
            "folder_count": 0,
            "total_size_bytes": 0,
            "total_size_gb": 0,
            "scan_mode": "index_required",
            "warning": "索引未就绪，请先重建索引",
        }

    async def _collect_remote_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        client = self.get_cached_synology_client(library.synology)
        start_path = self._normalize_remote_path(library.browse_root_path or library.root_path)
        top_level_items = [
            item for item in await self._list_remote_directory(client, start_path)
            if not self._should_skip_entry(item.get("name") or "")
        ]
        folder_count = 0
        total_size = 0
        completed = 0
        warning_count = 0
        last_error = None
        cached = self._stats_cache.get(library.id) or {}
        last_completed_at = cached.get("last_completed_at")
        self._append_stats_log(
            library,
            "INFO",
            f"远程统计开始 path={start_path} top={len(top_level_items)}",
        )
        self._update_remote_stats_progress(
            library,
            folder_count,
            total_size,
            completed,
            len(top_level_items),
            last_completed_at,
            current_item=None,
            warning_count=warning_count,
            last_error=last_error,
        )
        for item in top_level_items:
            additional = item.get("additional", {}) or {}
            item_name = item.get("name") or ""
            try:
                if item.get("isdir", False):
                    child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
                    nested_folder_count = await self._remote_collect_folder_count(client, child_path)
                    nested_size = await self._remote_path_size(
                        client,
                        child_path,
                        True,
                        additional.get("time", {}).get("mtime"),
                        initial_size=additional.get("size"),
                        max_wait_seconds=max(int(client.config.timeout) * 10, 300),
                    )
                    folder_count += 1 + nested_folder_count
                    total_size += nested_size
                    self._append_stats_log(
                        library,
                        "INFO",
                        f"统计目录 item={item_name} folders={1 + nested_folder_count} total={_gb(total_size)}GB",
                    )
                else:
                    file_size = int(additional.get("size") or 0)
                    total_size += file_size
                    self._append_stats_log(
                        library,
                        "INFO",
                        f"统计文件 item={item_name} total={_gb(total_size)}GB",
                    )
            except asyncio.CancelledError:
                self._append_stats_log(library, "WARN", f"远程统计取消 item={item_name}")
                raise
            except Exception as exc:
                warning_count += 1
                last_error = f"{item_name}: {exc}"
                self._append_stats_log(library, "ERROR", f"统计项失败 item={item_name} error={exc}")
            completed += 1
            self._update_remote_stats_progress(
                library,
                folder_count,
                total_size,
                completed,
                len(top_level_items),
                last_completed_at,
                current_item=item_name,
                warning_count=warning_count,
                last_error=last_error,
            )
        self._append_stats_log(
            library,
            "INFO",
            f"远程统计完成 folders={folder_count} size={_gb(total_size)}GB warnings={warning_count}",
        )
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "ready",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
            "scan_mode": "manual_persisted",
            "progress_done": completed,
            "progress_total": len(top_level_items),
            "progress_percent": 100.0,
            "warning_count": warning_count,
            "last_error": last_error,
        }

    async def _refresh_stats_for_library(self, library: LibraryDefinition):
        previous = dict(self._stats_cache.get(library.id) or {})
        try:
            if library.type == "local":
                stats = await asyncio.to_thread(self._collect_local_stats, library)
            else:
                stats = await self._collect_remote_stats(library)
        except asyncio.CancelledError:
            stats = {
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "status": "canceled",
                "folder_count": int(previous.get("folder_count", 0) or 0),
                "total_size_bytes": int(previous.get("total_size_bytes", 0) or 0),
                "total_size_gb": _gb(int(previous.get("total_size_bytes", 0) or 0)),
                "progress_done": int(previous.get("progress_done", 0) or 0),
                "progress_total": int(previous.get("progress_total", 0) or 0),
                "progress_percent": float(previous.get("progress_percent", 0) or 0),
                "current_item": previous.get("current_item"),
                "warning_count": int(previous.get("warning_count", 0) or 0),
                "last_error": previous.get("last_error"),
                "last_completed_at": previous.get("last_completed_at"),
            }
            self._append_stats_log(library, "WARN", "远程统计已取消，保留当前进度")
        except Exception as exc:
            stats = {
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "status": "error",
                "folder_count": int(previous.get("folder_count", 0) or 0),
                "total_size_bytes": int(previous.get("total_size_bytes", 0) or 0),
                "total_size_gb": _gb(int(previous.get("total_size_bytes", 0) or 0)),
                "progress_done": int(previous.get("progress_done", 0) or 0),
                "progress_total": int(previous.get("progress_total", 0) or 0),
                "progress_percent": float(previous.get("progress_percent", 0) or 0),
                "current_item": previous.get("current_item"),
                "warning_count": int(previous.get("warning_count", 0) or 0),
                "last_error": previous.get("last_error") or str(exc),
                "last_completed_at": previous.get("last_completed_at"),
                "warning": str(exc),
            }
            self._append_stats_log(library, "ERROR", f"远程统计异常结束: {exc}")
        health = self._health_for_library(library, float(self.load_config()["health_warning_free_gb"]))
        stats["health"] = health
        stats["updated_at"] = time.time()
        if stats.get("status") == "ready":
            stats["last_completed_at"] = time.time()
        else:
            stats["last_completed_at"] = stats.get("last_completed_at") or previous.get("last_completed_at")
        self._stats_cache[library.id] = stats
        self._persist_stats()
        self._stats_tasks.pop(library.id, None)

    def _extract_rjcode(self, value: str) -> Optional[str]:
        import re

        match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", value, re.IGNORECASE)
        return match.group(0).upper() if match else None


_library_manager: Optional[LibraryManager] = None


def get_library_manager() -> LibraryManager:
    global _library_manager
    if _library_manager is None:
        _library_manager = LibraryManager()
    return _library_manager


def shutdown_library_manager_background_workers() -> None:
    if _library_manager is None:
        return
    _library_manager.shutdown_background_workers()



