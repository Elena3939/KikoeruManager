import asyncio
import copy
import codecs
import json
import logging
import os
import re
import shutil
import stat
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional
from urllib.parse import quote, unquote

import aiohttp

from ..config.settings import get_config, get_config_file_path


def _robust_rmtree(path: str, retries: int = 3, delay: float = 1.0) -> None:
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
    414: "目标文件已存在",
}


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
                raise RuntimeError(
                    f"群晖 FileStation 响应解析失败: API={api}, HTTP {response.status}, Content-Type={content_type}, Body={snippet}"
                ) from decode_exc

    async def _request(self, api: str, method: str, version: int, params: dict[str, Any], files=None):
        # 最多重试一次：第一次如遇 SID 过期（code 119）自动重登录后重试
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
            return data.get("data") or {}
        return {}  # 不可达，仅供类型检查器

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
            yield bytes(preamble)
            with open(local_path, "rb") as handle:
                while True:
                    chunk = handle.read(1024 * 256)
                    if not chunk:
                        break
                    yield chunk
                    uploaded += len(chunk)
                    if progress_callback:
                        progress_callback(uploaded, file_size)
            yield epilogue

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            # DSM / 公网反代对 chunked multipart upload 很敏感；显式长度能避免
            # aiohttp 走 Transfer-Encoding: chunked 后被对端提前断开。
            "Content-Length": str(len(preamble) + file_size + len(epilogue)),
            "Connection": "close",
        }

        async with session.post(url, params=query_params, data=body_iter(), headers=headers, ssl=self.config.verify_ssl) as response:
            data = await self._read_response_payload(response, api_name)

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
        async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
            data = await self._read_response_payload(response, "SYNO.API.Info")

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
        async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
            data = await response.json()
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

    async def get_storage_info(self) -> dict[str, Any]:
        session = self._ensure_session()
        if not self._sid:
            await self._login(session)
        api_name = "SYNO.Core.System"
        path, version = await self._resolve_api_route(session, api_name, default_path="entry.cgi", default_version=1)
        url = f"{self.config.base_url.rstrip('/')}/webapi/{path.lstrip('/')}"
        params = {
            "api": api_name,
            "method": "info",
            "version": str(version),
            "type": "storage",
            "_sid": self._sid,
        }
        async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
            data = await self._read_response_payload(response, api_name)
        if not data.get("success"):
            raise SynologyError(_format_synology_error(api_name, "查询群晖存储信息", data))
        storage = data.get("data") or {}
        volumes = (
            storage.get("vol_info")
            or storage.get("volume_info")
            or storage.get("volumes")
            or []
        )
        if isinstance(volumes, dict):
            volumes = list(volumes.values())

        total_size = 0
        used_size = 0
        normalized_volumes: list[dict[str, Any]] = []
        for item in volumes:
            if not isinstance(item, dict):
                continue
            total_value = int(
                item.get("total_size")
                or item.get("size_total")
                or item.get("total")
                or 0
            )
            used_value = int(
                item.get("used_size")
                or item.get("size_used")
                or item.get("used")
                or 0
            )
            free_value = int(
                item.get("free_size")
                or item.get("size_free")
                or item.get("free")
                or max(0, total_value - used_value)
                or 0
            )
            if total_value <= 0 and free_value > 0 and used_value > 0:
                total_value = free_value + used_value
            if used_value <= 0 and total_value > 0 and free_value > 0:
                used_value = max(0, total_value - free_value)
            total_size += max(0, total_value)
            used_size += max(0, used_value)
            normalized_volumes.append({
                **item,
                "total_size": max(0, total_value),
                "used_size": max(0, used_value),
                "free_size": max(0, free_value),
            })
        free_size = max(0, total_size - used_size)
        return {
            "total_size_bytes": total_size,
            "used_size_bytes": used_size,
            "free_size_bytes": free_size,
            "free_space_gb": round(free_size / (1024 ** 3), 2) if free_size > 0 else 0,
            "volumes": normalized_volumes,
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
        return await self._request(
            "SYNO.FileStation.Search",
            "start",
            2,
            {
                "folder_path": folder_path,
                "pattern": keyword,
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
            logger.info("[SynologyUpload] 命中已缓存成功变体: %s", preferred_variant_name)
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
                        logger.info(
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
                        self._preferred_upload_variant_name = str(variant.get("name") or "").strip() or None
                        return
                    except Exception as exc:
                        logger.warning(
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
                            logger.info(
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
                                logger.warning(
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
            raise last_error


def build_synology_web_url(base_url: str, root_path: str) -> str:
    normalized_base = (base_url or "").rstrip("/")
    normalized_path = root_path or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    launch_param = quote(f"path={normalized_path}", safe="")
    return f"{normalized_base}//file/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam={launch_param}"


class LibraryManager:
    def __init__(self):
        self._stats_cache: dict[str, dict[str, Any]] = {}
        self._stats_tasks: dict[str, asyncio.Task] = {}
        self._size_cache: dict[str, dict[str, Any]] = {}
        self._remote_size_tasks: dict[str, asyncio.Task] = {}
        self._remote_search_tasks: dict[tuple[str, str, str, int, str, str], asyncio.Task] = {}
        self._remote_search_result_cache: dict[tuple[str, str, str, str, str, int, int], dict[str, Any]] = {}
        self._filter_preview_cancel_flags: dict[str, bool] = {}
        self._filter_preview_jobs: dict[str, dict[str, Any]] = {}
        self._filter_preview_tasks: dict[str, asyncio.Task] = {}
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
        return min(12, max(5, self._remote_search_cache_ttl_seconds() // 6))

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
            logger.info(
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
        logger.info(
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
        logger.info(
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
        except Exception:
            return

    def _persist_stats(self):
        payload = {
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
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
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
            )
        if library.type == "local":
            return await asyncio.to_thread(self._list_local_files, library, page, page_size, search, current_path, sort_by, sort_order)
        return await self._list_remote_files(library, page, page_size, search, current_path, sort_by, sort_order)

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

        keyword = str(search or "").strip()
        rj_only_search = self._is_rj_search_keyword(keyword)
        matches: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
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
                relative_path = os.path.relpath(full_path, search_root).replace("\\", "/")
                rjcode = self._extract_rjcode(relative_path) or self._extract_rjcode(name)
                if self._search_match_text(keyword, name, relative_path, rjcode, exact=search_exact):
                    target_path = full_path
                    target_name = name
                    target_is_directory = is_directory
                    if rj_only_search and self._normalize_search_result_kind(search_result_kind) != "file":
                        nearest_rj_dir = self._find_nearest_local_rj_directory(full_path, search_root)
                        if not nearest_rj_dir:
                            if is_directory:
                                queue.append(full_path)
                            continue
                        target_path = nearest_rj_dir
                        target_name = os.path.basename(nearest_rj_dir)
                        target_is_directory = True
                    if target_path not in seen_paths:
                        try:
                            stat_result = os.stat(target_path)
                        except OSError:
                            stat_result = None
                        if stat_result:
                            if not self._matches_search_result_kind(target_is_directory, search_result_kind):
                                continue
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

                if is_directory:
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
        return {
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

    def _list_local_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
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
        items = []
        try:
            entries = list(os.scandir(target_path))
        except OSError:
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": target_path, "browse_root_path": browse_root}

        # 顶层（社团目录层）不计算大小，避免对慢速网络盘做递归 os.walk。
        # 进入社团目录后（RJ 作品层）才计算各文件夹大小。
        at_root = target_path == browse_root

        for item_id, entry in enumerate(entries):
            if self._should_skip_entry(entry.name):
                continue
            rjcode = self._extract_rjcode(entry.name)
            if search_lower and search_lower not in entry.name.lower() and search_lower not in (rjcode or "").lower():
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            is_directory = entry.is_dir(follow_symlinks=False)
            cached_size, cached_size_status = self._get_cached_size_info(entry.path) if (is_directory and at_root) else (None, "")
            items.append(
                {
                    "id": f"{library.id}:{item_id}",
                    "name": entry.name,
                    "path": entry.path,
                    "rjcode": rjcode,
                    "size": cached_size if (is_directory and at_root) else (self._cached_path_size(entry.path) if is_directory else stat.st_size),
                    "size_status": cached_size_status if (is_directory and at_root) else "ready",
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "unzip_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_directory": is_directory,
                    "library_id": library.id,
                    "library_name": library.name,
                    "_sort_time": stat.st_mtime,
                }
            )

        items = self._sort_local_items(items, sort_by, sort_order)
        total = len(items)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = items[start:end]
        for item in page_items:
            item.pop("_sort_time", None)
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

        logger.info(
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
                logger.info(
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
    ) -> tuple[list[dict[str, Any]], int]:
        request_key = (
            library_id,
            self._normalize_remote_path(scope_path),
            str(keyword or "").strip(),
            min(max(page_size, 200), LIBRARY_SEARCH_RESULT_LIMIT),
            sort_by,
            sort_direction,
        )
        existing_task = self._remote_search_tasks.get(request_key)
        if existing_task and not existing_task.done():
            logger.info(
                "远程搜索复用进行中的请求: library=%s scope=%s keyword=%s",
                library_id,
                scope_path,
                keyword,
            )
            return await existing_task

        async def _execute_search() -> tuple[list[dict[str, Any]], int]:
            request_limit = request_key[3]
            max_warmup_retries = 3
            retry_delay = 2.0
            attempt = 0
            consecutive_start_errors = 0

            while attempt < max_warmup_retries:
                attempt += 1
                task_id = None
                attempt_start = time.time()
                try:
                    logger.info(
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
                    logger.info(
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
                    logger.info(
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
                        logger.info(
                            "远程搜索耗时%.1fs仍无结果，判定为真空: scope=%s keyword=%s",
                            attempt_seconds,
                            scope_path,
                            keyword,
                        )
                        return [], 0

                    if attempt < max_warmup_retries:
                        logger.info(
                            "远程搜索秒回空结果(索引预热中)，%.1fs后重试: scope=%s keyword=%s attempt=%d/%d",
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
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

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
            return cached_result
        browse_root, search_root = self._resolve_remote_target_path(library, current_path)
        keyword = str(search or "").strip()
        rj_only_search = self._is_rj_search_keyword(keyword)
        api_search_root = browse_root if keyword else search_root
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        remote_sort_by = "name" if normalized_sort_by == "name" else "mtime"
        remote_sort_direction = "asc" if normalized_sort_order == "asc" else "desc"
        search_scopes = await self._resolve_remote_search_scopes(client, api_search_root)
        logger.info(
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
                            logger.info(
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
        return self._set_cached_remote_search_result(cache_key, result)

    async def rename(self, library_id: str, path: str, new_name: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_rename, library, path, new_name)
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
        self._append_stats_log(library, "INFO", f"重命名 path={target_path} -> {new_name}")
        return {"message": "重命名成功", "new_path": new_path}

    def _local_rename(self, library: LibraryDefinition, path: str, new_name: str) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        parent_dir = os.path.dirname(path)
        new_path = os.path.join(parent_dir, new_name)
        os.rename(path, new_path)
        self._append_stats_log(library, "INFO", f"重命名 path={path} -> {new_name}")
        return {"message": "重命名成功", "new_path": new_path}

    def _local_delete(self, library: LibraryDefinition, path: str, confirmed: bool) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        if not confirmed:
            size = self._path_size(path)
            self._append_stats_log(
                library,
                "INFO",
                f"删除预检 path={path} type={'folder' if os.path.isdir(path) else 'file'} size={size}",
            )
            return {
                "need_confirm": True,
                "type": "folder" if os.path.isdir(path) else "file",
                "name": os.path.basename(path),
                "path": path,
                "size": size,
            }

        if os.path.isdir(path):
            _robust_rmtree(path)
        else:
            os.remove(path)
        self._append_stats_log(library, "INFO", f"删除完成 path={path}")
        return {"message": "删除成功", "path": path}

    async def batch_delete(self, library_id: str, paths: list[str], confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type != "local":
            raise RuntimeError("当前远程库不支持这里的批量删除")
        return await asyncio.to_thread(self._local_batch_delete, library, paths, confirmed)

    def _local_batch_delete(self, library: LibraryDefinition, paths: list[str], confirmed: bool) -> dict[str, Any]:
        for path in paths:
            self._assert_local_path_in_library(library, path)
        if not confirmed:
            total_size = sum(self._path_size(path) for path in paths)
            self._append_stats_log(library, "INFO", f"批删预检 total={len(paths)} size={total_size}")
            return {"need_confirm": True, "total_count": len(paths), "total_size": total_size}
        success_count = 0
        failed_paths = []
        for path in paths:
            try:
                if os.path.isdir(path):
                    _robust_rmtree(path)
                else:
                    os.remove(path)
                success_count += 1
            except Exception as exc:
                failed_paths.append({"path": path, "error": str(exc)})
        self._append_stats_log(
            library,
            "INFO",
            f"批删完成 success={success_count} failed={len(failed_paths)} total={len(paths)}",
        )
        return {"message": "批量删除完成", "success_count": success_count, "failed_paths": failed_paths}

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
        ttl = int(cfg["stats_cache_ttl_seconds"])
        target_library_id = library_id or None
        for library in self._active_libraries(cfg):
            cached = self._stats_cache.get(library.id)
            expired = not cached or (time.time() - cached.get("updated_at", 0)) > ttl
            task = self._stats_tasks.get(library.id)
            if library.type == "synology_filestation" and cached and cached.get("status") == "pending" and (task is None or task.done()):
                cached["status"] = "error"
                cached["warning"] = "Remote stats task was interrupted; please refresh again"
                cached["updated_at"] = time.time()
                self._stats_cache[library.id] = cached
                self._persist_stats()
                task = None
            force_this_library = force and (not target_library_id or library.id == target_library_id)
            # 本地库和远程库统一策略：只在明确 force=True 时才触发扫描，避免启动/页面加载时自动遍历网络驱动器
            should_refresh = force_this_library
            if should_refresh:
                if task is None or task.done():
                    self._stats_cache[library.id] = {
                        "library_id": library.id,
                        "library_name": library.name,
                        "library_type": library.type,
                        "status": "pending",
                        "folder_count": int((cached or {}).get("folder_count", 0) or 0),
                        "total_size_bytes": int((cached or {}).get("total_size_bytes", 0) or 0),
                        "total_size_gb": _gb(int((cached or {}).get("total_size_bytes", 0) or 0)),
                        "health": self._health_for_library(library, float(cfg["health_warning_free_gb"])),
                        "last_completed_at": (cached or {}).get("last_completed_at"),
                        "updated_at": time.time(),
                    }
                    if library.type == "synology_filestation":
                        self._persist_stats()
                        self._append_stats_log(library, "INFO", "远程统计任务已启动")
                    task = asyncio.create_task(self._refresh_stats_for_library(library))
                    self._stats_tasks[library.id] = task

        libraries = []
        total_folders = 0
        total_bytes = 0
        warning_free_gb = float(cfg["health_warning_free_gb"])
        for library in self._active_libraries(cfg):
            cached = self._stats_cache.get(library.id)
            if not cached:
                cached = {
                    "library_id": library.id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "status": "idle" if library.type == "synology_filestation" else "pending",
                    "folder_count": 0,
                    "total_size_bytes": 0,
                    "total_size_gb": 0,
                    "health": self._health_for_library(library, warning_free_gb),
                    "last_completed_at": None,
                }
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
        if library.type == "synology_filestation":
            self._persist_stats()
        return {
            "ok": True,
            "library_id": library.id,
            "status": "canceled",
            "message": "Stats task canceled",
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
            raise RuntimeError("来源目录名称无效，无法上传到远程库存")

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
        if delete_source_on_success and os.path.isdir(source_dir):
            try:
                _robust_rmtree(source_dir)
            except Exception as exc:
                logger.warning("上传成功后删除本地目录失败: source=%s error=%s", source_dir, exc, exc_info=True)
                raise RuntimeError(f"上传完成，但删除本地目录失败: {source_dir}，{exc}") from exc
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
        for root, dirs, files in os.walk(source_dir):
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
        # FileStation Upload 对同一目录并发写入很容易在公网/反代链路下返回 408。
        # 这里保持单文件流式上传，避免前端等待最终补配时发生超时回滚竞态。
        completed_files = 0
        completed_bytes = 0
        in_flight_bytes: dict[str, int] = {row["local_path"]: 0 for row in file_rows}
        _upload_semaphore = asyncio.Semaphore(1)

        def emit_progress(current_row: dict, uploaded_bytes: int):
            nonlocal last_speed_sample_at, last_speed_sample_bytes
            if not progress_callback:
                return
            transferred_bytes = min(total_bytes, completed_bytes + sum(in_flight_bytes.values()))
            elapsed = max(0.001, time.monotonic() - started_at)
            now = time.monotonic()
            delta_time = max(0.001, now - last_speed_sample_at)
            delta_bytes = max(0, transferred_bytes - last_speed_sample_bytes)
            instant_speed = int(delta_bytes / delta_time) if delta_bytes > 0 else 0
            if instant_speed > 0:
                last_speed_sample_at = now
                last_speed_sample_bytes = transferred_bytes
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
                "speed_bytes_per_sec": instant_speed,
                "average_speed_bytes_per_sec": int(transferred_bytes / elapsed) if transferred_bytes > 0 else 0,
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
        stage_name = f"{target_name}.__prekikoeru_stage__.{uuid.uuid4().hex[:8]}"
        backup_name = f"{target_name}.__prekikoeru_backup__.{uuid.uuid4().hex[:8]}"
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
            except Exception:
                logger.warning("清理远程阶段目录失败: %s", stage_path, exc_info=True)
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
        stage_name = f"{target_name}.__prekikoeru_stage__.{uuid.uuid4().hex[:8]}"
        backup_name = f"{target_name}.__prekikoeru_backup__.{uuid.uuid4().hex[:8]}"
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
            except Exception:
                logger.warning("清理远程合并阶段目录失败: %s", stage_path, exc_info=True)
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

    def _sort_local_items(self, items: list[dict[str, Any]], sort_by: str, sort_order: str) -> list[dict[str, Any]]:
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
        if normalized_sort_by == "name":
            return sorted(
                items,
                key=lambda value: (
                    value.get("name", "").lower(),
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
                    value.get("name", "").lower(),
                    -int(value.get("size") or 0),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_order == "asc":
            return sorted(
                items,
                key=lambda value: (
                    int(value.get("size") or 0),
                    value.get("name", "").lower(),
                    -float(value.get("_sort_time") or 0),
                ),
            )
        return sorted(
            items,
            key=lambda value: (
                -int(value.get("size") or 0),
                value.get("name", "").lower(),
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
                    value.get("name", "").lower(),
                    -float(value.get("_mtime") or 0),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_by == "time":
            return sorted(
                items,
                key=lambda value: (
                    float(value.get("_mtime") or 0),
                    value.get("name", "").lower(),
                ),
                reverse=normalized_sort_order == "desc",
            )
        if normalized_sort_order == "asc":
            return sorted(
                items,
                key=lambda value: (
                    value.get("size") is None,
                    int(value.get("size") or 0),
                    value.get("name", "").lower(),
                    -float(value.get("_mtime") or 0),
                ),
            )
        return sorted(
            items,
            key=lambda value: (
                value.get("size") is None,
                -int(value.get("size") or 0),
                value.get("name", "").lower(),
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
            except Exception:
                logger.warning("远程递归列目录失败: path=%s", current_path, exc_info=True)
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
        self._remote_size_tasks[cache_key] = asyncio.create_task(self._refresh_remote_path_size(library, path, modified_ts))

    async def _refresh_remote_path_size(self, library: LibraryDefinition, path: str, modified_ts: Optional[int]):
        try:
            if not library.synology:
                return
            client = self.get_cached_synology_client(library.synology)
            await self._remote_path_size(client, path, True, modified_ts)
        except Exception:
            pass

    async def _remote_delete_preview(self, client: SynologyFileStationClient, path: str) -> dict[str, Any]:
        normalized_path = self._normalize_remote_path(path)
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

    async def _list_remote_files(
        self,
        library: LibraryDefinition,
        page: int,
        page_size: int,
        search: str,
        current_path: Optional[str],
        sort_by: str,
        sort_order: str,
    ) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")

        client = self.get_cached_synology_client(library.synology)
        browse_root, target_path = self._resolve_remote_target_path(library, current_path)
        search_lower = search.lower().strip()
        normalized_sort_by = self._normalize_library_sort_by(sort_by)
        normalized_sort_order = self._normalize_library_sort_order(sort_order)
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

    async def _remote_folder_contents(self, library: LibraryDefinition, path: str, *, client: Optional[SynologyFileStationClient] = None) -> dict[str, Any]:
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

        async def walk(folder_path: str):
            nonlocal counter
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

    async def folder_contents(self, library_id: str, path: str, *, client: Optional[SynologyFileStationClient] = None) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_folder_contents, library, path)
        return await self._remote_folder_contents(library, path, client=client)

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
    ) -> dict[str, Any]:
        normalized_relative = str(relative_path or "").replace("\\", "/").strip("/")
        normalized_path = str(path or "").replace("\\", "/")
        return {
            "id": f"{item_type}:{normalized_path}",
            "name": PurePosixPath(normalized_relative or normalized_path).name if "/" in normalized_relative else (normalized_relative or os.path.basename(path)),
            "path": path,
            "relative_path": normalized_relative,
            "type": item_type,
            "size": None if size is None else int(size or 0),
            "modified_time": modified_time,
            "matched_rules": matched_rules or [],
            "selectable": selectable,
            "covered_by": covered_by or "",
            "delete_path": delete_path or path,
            "size_status": size_status,
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
        return job

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
            "scanned_entries": int(job.get("scanned_entries") or 0),
            "discovered_entries": int(job.get("discovered_entries") or 0),
            "pending_directories": int(job.get("pending_directories") or 0),
            "status": job.get("status") or "pending",
            "current_path": job.get("current_path") or "",
            "progress_message": job.get("progress_message") or "",
            "warning": job.get("warning") or "",
            "error": job.get("error") or "",
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
                        delete_path=delete_path,
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
                        selectable=False,
                        covered_by=delete_path,
                        delete_path=delete_path,
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
                        )
                    )
                    preview_items.extend(self._collect_local_filter_preview_descendants(target_path, folder_path, folder_path))
                    selected_count += 1
                    selected_size += folder_size
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
                            delete_path=delete_path,
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
                        selectable=False,
                        covered_by=delete_path,
                        delete_path=delete_path,
                        size_status="ready",
                    )
                )
                subtotal += file_size

            return subtotal

        total_size = await walk(folder_path)
        return descendants, total_size

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
        normalized_request_id = str(request_id or "").strip()
        self._begin_filter_preview_request(normalized_request_id)
        client = self._create_filter_preview_client(library)
        info = await client.stat(target_path)
        info_item = self._first_remote_info_item(info)
        if not info_item or not info_item.get("isdir", False):
            raise FileNotFoundError("目标文件夹不存在")

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
                        )
                    )
                    preview_items.extend(descendants)
                    selected_count += 1
                    selected_size += folder_size
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
    ) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_filter_delete_preview, library, path, rules)
        return await self._remote_filter_delete_preview(library, path, rules, request_id)

    async def start_filter_delete_preview_job(
        self,
        library_id: str,
        path: str,
        rules: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
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
                        )
                    )
                    preview_items.extend(descendants)
                    selected_count += 1
                    selected_size += folder_size
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

    async def delete(self, library_id: str, path: str, confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_delete, library, path, confirmed)
        if not library.synology:
            raise RuntimeError("远程库缺少群晖连接配置")
        _, target_path = self._resolve_remote_operation_path(
            library,
            path,
            action="删除",
        )
        client = self.get_cached_synology_client(library.synology)
        if not confirmed:
            preview = await self._remote_delete_preview(client, target_path)
            preview["need_confirm"] = True
            self._append_stats_log(library, "INFO", f"删除预检 path={target_path} type={preview.get('type') or 'unknown'}")
            return preview
        preview = await self._remote_delete_preview(client, target_path)
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
        self._append_stats_log(
            library,
            "INFO",
            f"删除完成 path={target_path} type={preview.get('type') or 'unknown'} size={int(preview.get('size') or 0)}",
        )
        return {"message": "删除成功", "path": target_path}

    async def _remote_batch_delete(self, library: LibraryDefinition, paths: list[str], confirmed: bool) -> dict[str, Any]:
        client = self.get_cached_synology_client(library.synology)
        if not confirmed:
            previews = await asyncio.gather(
                *(self._remote_delete_preview(client, path) for path in paths),
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
            *(self._remote_delete_preview(client, path) for path in paths),
            return_exceptions=True,
        )
        success_count = 0
        deleted_bytes = 0
        deleted_folder_count = 0
        failed_paths = []
        for path, preview in zip(paths, previews):
            if isinstance(preview, Exception):
                failed_paths.append({"path": path, "error": str(preview)})
                self._append_stats_log(library, "ERROR", f"批删预检失败 path={path} error={preview}")
                continue
            try:
                await client.delete(path)
                success_count += 1
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
        self._append_stats_log(
            library,
            "INFO",
            f"批删结束 success={success_count} failed={len(failed_paths)} bytes={deleted_bytes}",
        )
        return {"message": "批量删除完成", "success_count": success_count, "failed_paths": failed_paths}

    async def batch_delete(self, library_id: str, paths: list[str], confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_batch_delete, library, paths, confirmed)
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

    def _collect_local_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        # 只统计顶层目录数量，不做递归 os.walk 大小计算，避免在 SMB 映射盘等慢速路径上阻塞。
        target_root = os.path.abspath(library.browse_root_path or library.root_path)
        if not os.path.exists(target_root):
            return {
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "status": "ready",
                "folder_count": 0,
                "total_size_bytes": 0,
                "total_size_gb": 0,
                "scan_mode": "manual_persisted",
            }
        folder_count = 0
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
            "scan_mode": "manual_persisted",
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
        if library.type == "synology_filestation":
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



