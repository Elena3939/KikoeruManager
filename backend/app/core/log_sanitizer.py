"""日志脱敏工具。

系统日志只用于定位现场，不能输出密码、Token、Cookie 这类运行态密钥。
这里保持无业务依赖，避免配置加载 / 路由 / 下载服务之间互相 import。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "********"

_SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "cookie",
    "secret",
    "authorization",
    "apikey",
    "api_key",
    "clientsecret",
    "refresh",
    "encodedtoken",
    "accesstoken",
    "bduss",
    "stoken",
    "ptoken",
    "bdclnd",
    "otpcode",
    "deviceid",
)

_EXTRACT_PASSWORD_KEYS = {
    "passwordlist",
    "extractpassword",
    "archivepassword",
    "manualretrypassword",
    "resolvedpassword",
    "hintpassword",
    "filenamepassword",
    "filenamepasswordsnifftemplates",
}

_URL_RE = re.compile(r"(?P<url>https?://[^\s'\"<>]+)", re.IGNORECASE)
_AUTH_RE = re.compile(r"\b(?P<scheme>Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_COOKIE_RE = re.compile(
    r"\b(?P<key>BDUSS(?:_BFESS)?|STOKEN(?:_BFESS)?|PTOKEN(?:_BFESS)?|BDCLND|Cookie)\s*=\s*[^;\s,]+",
    re.IGNORECASE,
)
_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b")


def _normalize_key(key: Any) -> str:
    return re.sub(r"[\s_.:-]+", "", str(key or "").strip().lower())


def is_sensitive_log_key(key: Any) -> bool:
    normalized = _normalize_key(key)
    if not normalized:
        return False
    if normalized in _EXTRACT_PASSWORD_KEYS:
        return False
    return any(marker.replace("_", "") in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _mask_url(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    try:
        parts = urlsplit(text)
    except Exception:
        return text
    if not parts.scheme or not parts.netloc:
        return text

    netloc = parts.netloc
    if "@" in netloc:
        host_part = netloc.rsplit("@", 1)[1]
        netloc = f"***:***@{host_part}"

    query_pairs = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        query_pairs.append((key, REDACTED if is_sensitive_log_key(key) and val else val))
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def mask_url_for_log(value: str) -> str:
    """脱敏单个 URL 或文本中出现的 http(s) URL。"""
    text = str(value or "")
    if not text:
        return text
    if _URL_RE.fullmatch(text):
        return _mask_url(text)
    return _URL_RE.sub(lambda match: _mask_url(match.group("url")), text)


def sanitize_text_for_log(value: Any, *, max_length: int = 1000) -> str:
    text = str(value or "")
    if not text:
        return text
    text = mask_url_for_log(text)
    text = _AUTH_RE.sub(lambda match: f"{match.group('scheme')} {REDACTED}", text)
    text = _COOKIE_RE.sub(lambda match: f"{match.group('key')}={REDACTED}", text)
    text = _API_KEY_RE.sub(REDACTED, text)
    if max_length > 0 and len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def sanitize_for_log(
    value: Any,
    *,
    max_depth: int = 6,
    max_items: int = 80,
    max_string: int = 1000,
    _depth: int = 0,
) -> Any:
    """递归脱敏可写入日志的值，保留结构但移除密钥内容。"""
    if _depth >= max_depth:
        return "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text_for_log(value, max_length=max_string)
    if isinstance(value, bytes):
        return sanitize_text_for_log(value.decode("utf-8", errors="replace"), max_length=max_string)

    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            return sanitize_text_for_log(value, max_length=max_string)
    elif hasattr(value, "dict") and callable(getattr(value, "dict", None)):
        try:
            value = value.dict()
        except Exception:
            return sanitize_text_for_log(value, max_length=max_string)

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["..."] = f"{len(value) - max_items} more"
                break
            if is_sensitive_log_key(key):
                result[key] = REDACTED if item not in (None, "", [], {}) else item
            else:
                result[key] = sanitize_for_log(
                    item,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string=max_string,
                    _depth=_depth + 1,
                )
        return result

    if isinstance(value, (list, tuple, set, frozenset)):
        sequence = list(value)
        result = [
            sanitize_for_log(
                item,
                max_depth=max_depth,
                max_items=max_items,
                max_string=max_string,
                _depth=_depth + 1,
            )
            for item in sequence[:max_items]
        ]
        if len(sequence) > max_items:
            result.append(f"... {len(sequence) - max_items} more")
        return result

    return sanitize_text_for_log(value, max_length=max_string)
