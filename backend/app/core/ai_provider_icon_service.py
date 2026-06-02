"""AI 模型平台图标识别与本地 favicon 缓存。"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import mimetypes
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_MAX_ICON_BYTES = 256 * 1024
_CACHE_TTL_SECONDS = 30 * 24 * 3600
_FILENAME_RE = re.compile(r"^[a-f0-9]{24}\.(?:ico|png|jpg|jpeg|webp|gif|svg)$", re.IGNORECASE)
_HTML_ICON_RE = re.compile(
    r"""<link[^>]+rel=["'][^"']*(?:shortcut\s+icon|icon|apple-touch-icon)[^"']*["'][^>]*>""",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)

_PROVIDER_HINTS = {
    "openai": {
        "label": "OpenAI",
        "home_url": "https://openai.com",
        "icon_urls": ["https://cdn.simpleicons.org/openai", "https://openai.com/favicon.ico"],
    },
    "azure": {
        "label": "Azure OpenAI",
        "home_url": "https://azure.microsoft.com",
        "icon_urls": ["https://cdn.simpleicons.org/microsoftazure", "https://azure.microsoft.com/favicon.ico"],
    },
    "anthropic": {
        "label": "Anthropic",
        "home_url": "https://www.anthropic.com",
        "icon_urls": ["https://cdn.simpleicons.org/anthropic", "https://www.anthropic.com/favicon.ico"],
    },
    "claude": {
        "label": "Anthropic",
        "home_url": "https://www.anthropic.com",
        "icon_urls": ["https://cdn.simpleicons.org/anthropic", "https://www.anthropic.com/favicon.ico"],
    },
    "gemini": {
        "label": "Google AI",
        "home_url": "https://ai.google.dev",
        "icon_urls": ["https://cdn.simpleicons.org/google", "https://ai.google.dev/favicon.ico"],
    },
    "google": {
        "label": "Google AI",
        "home_url": "https://ai.google.dev",
        "icon_urls": ["https://cdn.simpleicons.org/google", "https://ai.google.dev/favicon.ico"],
    },
    "vertex_ai": {
        "label": "Google Cloud",
        "home_url": "https://cloud.google.com",
        "icon_urls": ["https://cdn.simpleicons.org/googlecloud", "https://cloud.google.com/favicon.ico"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "home_url": "https://www.deepseek.com",
        "icon_urls": ["https://cdn.simpleicons.org/deepseek", "https://www.deepseek.com/favicon.ico"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "home_url": "https://openrouter.ai",
        "icon_urls": ["https://cdn.simpleicons.org/openrouter", "https://openrouter.ai/favicon.ico"],
    },
    "groq": {
        "label": "Groq",
        "home_url": "https://groq.com",
        "icon_urls": ["https://cdn.simpleicons.org/groq", "https://groq.com/favicon.ico"],
    },
    "mistral": {
        "label": "Mistral AI",
        "home_url": "https://mistral.ai",
        "icon_urls": ["https://cdn.simpleicons.org/mistralai", "https://mistral.ai/favicon.ico"],
    },
    "xai": {
        "label": "xAI",
        "home_url": "https://x.ai",
        "icon_urls": ["https://cdn.simpleicons.org/x", "https://x.ai/favicon.ico"],
    },
    "ollama": {
        "label": "Ollama",
        "home_url": "https://ollama.com",
        "icon_urls": ["https://cdn.simpleicons.org/ollama", "https://ollama.com/favicon.ico"],
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "home_url": "https://siliconflow.cn",
        "icon_urls": ["https://siliconflow.cn/favicon.ico"],
    },
    "moonshot": {
        "label": "Moonshot",
        "home_url": "https://www.moonshot.cn",
        "icon_urls": ["https://www.moonshot.cn/favicon.ico"],
    },
    "zhipu": {
        "label": "智谱 AI",
        "home_url": "https://www.bigmodel.cn",
        "icon_urls": ["https://www.bigmodel.cn/favicon.ico"],
    },
    "qwen": {
        "label": "通义千问",
        "home_url": "https://tongyi.aliyun.com",
        "icon_urls": ["https://cdn.simpleicons.org/alibabacloud", "https://tongyi.aliyun.com/favicon.ico"],
    },
    "dashscope": {
        "label": "阿里云百炼",
        "home_url": "https://www.aliyun.com",
        "icon_urls": ["https://cdn.simpleicons.org/alibabacloud", "https://www.aliyun.com/favicon.ico"],
    },
    "baichuan": {
        "label": "百川智能",
        "home_url": "https://www.baichuan-ai.com",
        "icon_urls": ["https://www.baichuan-ai.com/favicon.ico"],
    },
    "volcengine": {
        "label": "火山引擎",
        "home_url": "https://www.volcengine.com",
        "icon_urls": ["https://www.volcengine.com/favicon.ico"],
    },
    "perplexity": {
        "label": "Perplexity",
        "home_url": "https://www.perplexity.ai",
        "icon_urls": ["https://cdn.simpleicons.org/perplexity", "https://www.perplexity.ai/favicon.ico"],
    },
    "cohere": {
        "label": "Cohere",
        "home_url": "https://cohere.com",
        "icon_urls": ["https://cohere.com/favicon.ico"],
    },
    "pqapi": {
        "label": "PQAPI",
        "home_url": "https://www.pqapi.store",
        "icon_urls": ["https://www.pqapi.store/favicon.ico"],
    },
}

_HOST_HINTS = [
    ("openai.azure.com", "azure"),
    ("api.openai.com", "openai"),
    ("openai.com", "openai"),
    ("anthropic.com", "anthropic"),
    ("claude.ai", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("googleapis.com", "google"),
    ("deepseek.com", "deepseek"),
    ("openrouter.ai", "openrouter"),
    ("groq.com", "groq"),
    ("mistral.ai", "mistral"),
    ("x.ai", "xai"),
    ("siliconflow.cn", "siliconflow"),
    ("moonshot.cn", "moonshot"),
    ("bigmodel.cn", "zhipu"),
    ("dashscope.aliyuncs.com", "dashscope"),
    ("aliyun.com", "dashscope"),
    ("baichuan-ai.com", "baichuan"),
    ("volcengine.com", "volcengine"),
    ("perplexity.ai", "perplexity"),
    ("cohere.com", "cohere"),
    ("pqapi.store", "pqapi"),
]

_MODEL_ALIAS_HINTS = [
    ("azure_openai", "azure"),
    ("azure-openai", "azure"),
    ("anthropic", "anthropic"),
    ("claude", "anthropic"),
    ("gemini", "gemini"),
    ("google", "google"),
    ("vertex_ai", "vertex_ai"),
    ("vertex-ai", "vertex_ai"),
    ("deepseek", "deepseek"),
    ("openrouter", "openrouter"),
    ("mistralai", "mistral"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("codestral", "mistral"),
    ("ollama", "ollama"),
    ("groq", "groq"),
    ("grok", "xai"),
    ("xai", "xai"),
    ("siliconflow", "siliconflow"),
    ("moonshot", "moonshot"),
    ("kimi", "moonshot"),
    ("bigmodel", "zhipu"),
    ("zhipu", "zhipu"),
    ("glm", "zhipu"),
    ("dashscope", "dashscope"),
    ("qwen", "qwen"),
    ("qwq", "qwen"),
    ("qvq", "qwen"),
    ("tongyi", "qwen"),
    ("baichuan", "baichuan"),
    ("volcengine", "volcengine"),
    ("doubao", "volcengine"),
    ("ark", "volcengine"),
    ("perplexity", "perplexity"),
    ("sonar", "perplexity"),
    ("cohere", "cohere"),
    ("command-r", "cohere"),
    ("command", "cohere"),
    ("openai", "openai"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
]


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _host_label(host: str) -> str:
    clean = str(host or "").strip().lower()
    clean = clean[4:] if clean.startswith("www.") else clean
    if not clean:
        return "自定义模型服务"
    first = clean.split(".", 1)[0]
    return first.upper() if len(first) <= 4 else first.replace("-", " ").title()


def _normalize_url(value: str) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _provider_key_from_model(model: str) -> str:
    text = _safe_text(model).lower()
    if text.startswith("models/"):
        text = text[7:]
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    parts = [part for part in text.split("/") if part]
    prefix = parts[0] if parts else ""
    if prefix in _PROVIDER_HINTS:
        return prefix
    model_id = parts[-1] if parts else text
    for alias, key in _MODEL_ALIAS_HINTS:
        if (
            prefix == alias
            or model_id == alias
            or model_id.startswith(f"{alias}-")
            or model_id.startswith(f"{alias}_")
            or f"-{alias}-" in model_id
        ):
            return key
    return ""


def _provider_key_from_host(host: str) -> str:
    clean = str(host or "").lower()
    for needle, key in _HOST_HINTS:
        if needle in clean:
            return key
    return ""


def _extension_from_response(url: str, content_type: str) -> str:
    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "image/svg+xml":
        return "svg"
    guessed = mimetypes.guess_extension(content_type) or ""
    if guessed:
        ext = guessed.lstrip(".").lower()
        if ext == "jpe":
            return "jpg"
        if ext in {"ico", "png", "jpg", "jpeg", "webp", "gif", "svg"}:
            return ext
    suffix = Path(urlparse(url).path).suffix.lstrip(".").lower()
    if suffix in {"ico", "png", "jpg", "jpeg", "webp", "gif", "svg"}:
        return suffix
    return "ico"


def _looks_like_image(content_type: str, content: bytes) -> bool:
    lowered = str(content_type or "").lower()
    if lowered.startswith("image/"):
        return True
    return (
        content.startswith(b"\x00\x00\x01\x00")
        or content.startswith(b"\x89PNG")
        or content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"GIF8")
        or content.lstrip()[:5].lower() == b"<svg "
    )


def _is_public_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        parsed.is_loopback
        or parsed.is_private
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _resolve_host_is_public(host: str) -> bool:
    clean = str(host or "").strip()
    if not clean or clean.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ipaddress.ip_address(clean)
        return _is_public_ip(clean)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(clean, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {item[4][0] for item in infos if item and item[4]}
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)


async def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        return await asyncio.wait_for(asyncio.to_thread(_resolve_host_is_public, parsed.hostname), timeout=4)
    except Exception:
        return False


class AIProviderIconService:
    """把模型服务 favicon 缓存在本地，只给前端返回缓存 URL。"""

    def __init__(self) -> None:
        self._cache_dir: Optional[Path] = None

    @property
    def cache_dir(self) -> Path:
        if self._cache_dir is None:
            from ..models.database import get_db_path

            base_dir = Path(get_db_path()).parent / "cache" / "ai_provider_icons"
            base_dir.mkdir(parents=True, exist_ok=True)
            self._cache_dir = base_dir
        return self._cache_dir

    def _detect_provider(self, model: str, api_base: str) -> Dict[str, str]:
        normalized = _normalize_url(api_base)
        host = urlparse(normalized).hostname or ""
        model_key = _provider_key_from_model(model)
        host_key = _provider_key_from_host(host)
        key = model_key or host_key
        hint = _PROVIDER_HINTS.get(key, {})
        label = hint.get("label") or _host_label(host)
        home_url = hint.get("home_url") or normalized
        if not home_url and host:
            home_url = f"https://{host}"
        cache_key_src = f"{key or host or 'custom'}|{home_url}|{normalized}"
        return {
            "key": key or hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()[:10],
            "label": label,
            "host": host,
            "home_url": home_url,
            "api_origin": normalized,
            "icon_urls": list(hint.get("icon_urls") or []),
            "detected_by": "model" if model_key else ("host" if host_key else "custom"),
        }

    def _cache_key(self, provider: Dict[str, str]) -> str:
        raw = json.dumps(provider, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _meta_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def _load_cached(self, cache_key: str) -> Optional[Dict[str, Any]]:
        meta_path = self._meta_path(cache_key)
        if not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            filename = str(meta.get("filename") or "")
            file_path = self.resolve_cached_file(filename)
            if not file_path:
                return None
            if time.time() - float(meta.get("fetched_at") or 0) > _CACHE_TTL_SECONDS:
                return None
            return meta
        except Exception:
            return None

    def _save_cached(self, cache_key: str, filename: str, source_url: str, content_type: str) -> Dict[str, Any]:
        meta = {
            "filename": filename,
            "source_url": source_url,
            "content_type": content_type,
            "fetched_at": time.time(),
        }
        self._meta_path(cache_key).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta

    async def _fetch_icon_from_url(self, client: Any, icon_url: str) -> Optional[Dict[str, Any]]:
        if not await _is_public_http_url(icon_url):
            return None
        response = await client.get(icon_url)
        if response.status_code >= 400:
            return None
        content = response.content[:_MAX_ICON_BYTES + 1]
        if len(content) > _MAX_ICON_BYTES:
            return None
        content_type = response.headers.get("content-type") or ""
        if not _looks_like_image(content_type, content):
            return None
        return {
            "url": str(response.url),
            "content": content,
            "content_type": content_type or mimetypes.guess_type(icon_url)[0] or "image/x-icon",
            "extension": _extension_from_response(str(response.url), content_type),
        }

    async def _candidate_icon_urls(self, client: Any, base_url: str) -> List[str]:
        if not await _is_public_http_url(base_url):
            return []
        urls = [urljoin(base_url.rstrip("/") + "/", "favicon.ico")]
        try:
            response = await client.get(base_url)
            if response.status_code < 400 and "text/html" in str(response.headers.get("content-type") or "").lower():
                html = response.text[:128 * 1024]
                for tag in _HTML_ICON_RE.findall(html):
                    match = _HREF_RE.search(tag)
                    if match:
                        urls.append(urljoin(str(response.url), match.group(1)))
        except Exception:
            pass
        unique: List[str] = []
        for url in urls:
            if url not in unique:
                unique.append(url)
        return unique[:8]

    async def _fetch_and_cache(self, cache_key: str, provider: Dict[str, str], *, proxy_url: str = "") -> Optional[Dict[str, Any]]:
        import httpx
        from .ai_subtitle_match_service import _temporary_proxy

        candidates = []
        # 模型 ID 已经能识别出平台时，品牌官网优先，不能被中转 Base URL 的 favicon 抢走。
        origin_candidates = (
            (provider.get("home_url"),)
            if provider.get("detected_by") == "model"
            else (provider.get("api_origin"), provider.get("home_url"))
        )
        for value in origin_candidates:
            clean = _normalize_url(value or "")
            if clean and clean not in candidates:
                candidates.append(clean)
        if not candidates:
            return None

        headers = {
            "User-Agent": "KikoeruManager/AIProviderIconCache",
            "Accept": "image/*,text/html;q=0.8,*/*;q=0.5",
        }
        async with _temporary_proxy(proxy_url):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8, connect=5),
                follow_redirects=True,
                trust_env=True,
                headers=headers,
            ) as client:
                for icon_url in provider.get("icon_urls") or []:
                    try:
                        fetched = await self._fetch_icon_from_url(client, icon_url)
                    except Exception:
                        logger.debug("[AI平台图标] 品牌图标抓取失败: %s", icon_url, exc_info=True)
                        continue
                    if not fetched:
                        continue
                    filename = f"{cache_key}.{fetched['extension']}"
                    file_path = self.cache_dir / filename
                    file_path.write_bytes(fetched["content"])
                    return self._save_cached(cache_key, filename, fetched["url"], fetched["content_type"])

                for base_url in candidates:
                    icon_urls = await self._candidate_icon_urls(client, base_url)
                    for icon_url in icon_urls:
                        try:
                            fetched = await self._fetch_icon_from_url(client, icon_url)
                        except Exception:
                            logger.debug("[AI平台图标] favicon 抓取失败: %s", icon_url, exc_info=True)
                            continue
                        if not fetched:
                            continue
                        filename = f"{cache_key}.{fetched['extension']}"
                        file_path = self.cache_dir / filename
                        file_path.write_bytes(fetched["content"])
                        return self._save_cached(cache_key, filename, fetched["url"], fetched["content_type"])
        return None

    async def resolve_provider_icon(self, model: str = "", api_base: str = "", proxy_url: str = "") -> Dict[str, Any]:
        provider = self._detect_provider(model, api_base)
        cache_key = self._cache_key(provider)
        cached = self._load_cached(cache_key)
        source = "cache"
        if cached is None:
            cached = await self._fetch_and_cache(cache_key, provider, proxy_url=proxy_url)
            source = "fetched" if cached else "fallback"
        filename = str((cached or {}).get("filename") or "")
        icon_path = f"/ai-subtitle-match/provider-icon/file/{filename}" if filename else ""
        return {
            "success": True,
            "key": provider["key"],
            "label": provider["label"],
            "host": provider["host"],
            "icon_path": icon_path,
            "icon_url": f"/api{icon_path}" if icon_path else "",
            "source": source,
        }

    def resolve_cached_file(self, filename: str) -> Optional[Path]:
        clean = str(filename or "").strip()
        if not _FILENAME_RE.match(clean):
            return None
        path = (self.cache_dir / clean).resolve()
        if self.cache_dir.resolve() not in path.parents and path != self.cache_dir.resolve():
            return None
        return path if path.is_file() else None


_service: Optional[AIProviderIconService] = None


def get_ai_provider_icon_service() -> AIProviderIconService:
    global _service
    if _service is None:
        _service = AIProviderIconService()
    return _service
