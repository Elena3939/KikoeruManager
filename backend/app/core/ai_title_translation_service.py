"""AI 标题汉化服务。复用 LiteLLM 基础设施，将日文作品标题翻译为中文。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import logging

from .log_sanitizer import mask_url_for_log, sanitize_text_for_log

logger = logging.getLogger(__name__)

MASKED_SECRET = "********"
_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_proxy_lock = asyncio.Lock()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _config_to_dict(config: Any) -> Dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    if hasattr(config, "model_dump"):
        return dict(config.model_dump())
    return {
        key: getattr(config, key)
        for key in dir(config)
        if not key.startswith("_") and not callable(getattr(config, key, None))
    }


def _extract_litellm_content(response: Any) -> Tuple[str, Dict[str, int]]:
    usage_obj = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if usage_obj is None:
        usage = {}
    elif isinstance(usage_obj, dict):
        usage = usage_obj
    else:
        usage = {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
            "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
            "total_tokens": getattr(usage_obj, "total_tokens", 0),
        }
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not choices:
        return "", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    choice = choices[0]
    if isinstance(choice, dict):
        message = choice.get("message", {})
        content = message.get("content", "")
    else:
        content = getattr(getattr(choice, "message", None), "content", "")
    return str(content or "").strip(), {
        "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
        "completion_tokens": _safe_int(usage.get("completion_tokens")),
        "total_tokens": _safe_int(usage.get("total_tokens")),
    }


def _is_azure_config(config: Dict[str, Any]) -> bool:
    base_url = _safe_text(config.get("api_base")).lower()
    api_version = _safe_text(config.get("api_version"))
    return bool(api_version and ("azure" in base_url or ".openai.azure.com" in base_url))


def _normalize_error(exc: Exception) -> Dict[str, str]:
    raw = str(exc or "")
    lowered = raw.lower()
    exc_name = exc.__class__.__name__.lower()
    code = "unknown"
    title = "未知错误"
    suggestion = "请检查日志获取详细信息"
    if "model_not_found" in lowered or "model" in lowered and "not found" in lowered:
        code, title, suggestion = "model_not_found", "模型不存在", "检查模型名是否有效"
    elif "proxy" in lowered:
        code, title, suggestion = "proxy_error", "代理不可用", "检查代理地址格式"
    elif "authentication" in lowered or "unauthorized" in lowered or "invalid_api_key" in exc_name:
        code, title, suggestion = "auth_error", "认证失败", "检查 API Key 是否有效"
    elif "rate" in lowered and "limit" in lowered:
        code, title, suggestion = "rate_limit", "请求频率限制", "请稍后重试"
    elif "timeout" in lowered:
        code, title, suggestion = "timeout", "请求超时", "检查网络连接或增加超时时间"
    return {"code": code, "title": title, "suggestion": suggestion}


async def _temporary_proxy(proxy_url: str):
    proxy = _safe_text(proxy_url)
    if not proxy:
        yield
        return
    saved = {}
    async with _proxy_lock:
        for key in _PROXY_ENV_KEYS:
            saved[key] = os.environ.get(key, "")
            os.environ[key] = proxy
        try:
            yield
        finally:
            for key in _PROXY_ENV_KEYS:
                if saved.get(key):
                    os.environ[key] = saved[key]
                else:
                    os.environ.pop(key, None)


class AITitleTranslationService:
    """AI 标题翻译服务。将日文作品标题翻译为中文。"""

    def _normalize_runtime_config(self, raw_config: Any, *, saved_api_key: str = "") -> Dict[str, Any]:
        config = _config_to_dict(raw_config)
        api_key = _safe_text(config.get("api_key"))
        if api_key == MASKED_SECRET:
            config["api_key"] = saved_api_key or ""
        return config

    def _build_messages(self, config: Dict[str, Any], work_name: str) -> List[Dict[str, str]]:
        prompt_template = config.get("prompt_template") or "请将以下日文作品标题翻译成中文，只输出翻译结果：\n{work_name}"
        prompt = prompt_template.replace("{work_name}", work_name)
        return [
            {"role": "system", "content": "你是一个专业的日文标题翻译助手。请根据用户提供的标题进行翻译。"},
            {"role": "user", "content": prompt},
        ]

    def _completion_kwargs(
        self,
        config: Dict[str, Any],
        messages: List[Dict[str, str]],
        *,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": _safe_text(config.get("model")),
            "messages": messages,
            "temperature": float(config.get("temperature", 0.1)),
            "max_tokens": 200,
        }
        api_key = _safe_text(config.get("api_key"))
        if api_key:
            kwargs["api_key"] = api_key
        api_base = _safe_text(config.get("api_base"))
        if api_base:
            kwargs["api_base"] = api_base.rstrip("/")
        api_version = _safe_text(config.get("api_version"))
        if api_version:
            kwargs["api_version"] = api_version
        organization = _safe_text(config.get("organization"))
        if organization:
            kwargs["organization"] = organization
        kwargs["timeout"] = float(timeout_seconds or _safe_int(config.get("timeout_seconds"), 30))
        return kwargs

    async def _call_model(self, config: Dict[str, Any], work_name: str) -> Tuple[str, Dict[str, int]]:
        """调用 LLM 翻译标题。返回 (翻译文本, usage)。"""
        if not config.get("model"):
            raise ValueError("missing_config: model 不能为空")
        if not config.get("api_key"):
            raise ValueError("missing_config: api_key 不能为空")

        try:
            import litellm
        except Exception as exc:
            raise RuntimeError(f"missing_config: 后端未安装 litellm: {exc}") from exc

        request_label = f"标题翻译[{uuid.uuid4().hex[:8]}]"
        messages = self._build_messages(config, work_name)
        kwargs = self._completion_kwargs(config, messages)
        max_retries = _safe_int(config.get("max_retries"), 2)

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                async with _temporary_proxy(config.get("proxy_url", "")):
                    response = await litellm.acompletion(**kwargs)
                content, usage = _extract_litellm_content(response)
                if not content:
                    raise ValueError("模型返回为空")
                # 清理输出：去除引号、多余空白
                content = content.strip().strip('"').strip("'").strip("「").strip("」").strip()
                logger.info(
                    "[AI标题] %s 翻译成功: work_name=%s -> %s tokens=%s",
                    request_label,
                    work_name[:40],
                    content[:60],
                    usage.get("total_tokens", 0),
                )
                return content, usage
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    wait = 1.0 * (attempt + 1)
                    logger.warning(
                        "[AI标题] %s 第%s次重试: %s", request_label, attempt + 1, exc
                    )
                    await asyncio.sleep(wait)
                continue

        raise last_error or RuntimeError("翻译失败")

    async def translate_single(
        self,
        work_name: str,
        config: Any,
        *,
        saved_api_key: str = "",
    ) -> Dict[str, Any]:
        """翻译单个作品标题。"""
        cfg = self._normalize_runtime_config(config, saved_api_key=saved_api_key)
        if not cfg.get("enabled", False):
            return {"success": False, "status": "disabled", "translated_title": None}

        started = time.perf_counter()
        try:
            translated, usage = await self._call_model(cfg, work_name)
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "success": True,
                "translated_title": translated,
                "original_title": work_name,
                "duration_ms": duration_ms,
                "tokens": usage.get("total_tokens", 0),
                "model": cfg.get("model", ""),
            }
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_info = _normalize_error(exc)
            logger.warning("[AI标题] 翻译失败: work_name=%s error=%s", work_name[:40], exc)
            return {
                "success": False,
                "status": "failed",
                "translated_title": None,
                "original_title": work_name,
                "error": error_info,
                "duration_ms": duration_ms,
            }

    async def translate_batch(
        self,
        items: List[Dict[str, str]],
        config: Any,
        *,
        saved_api_key: str = "",
    ) -> List[Dict[str, Any]]:
        """批量翻译多个作品标题。
        items: [{"rjcode": "RJ123456", "work_name": "..."}, ...]
        """
        cfg = self._normalize_runtime_config(config, saved_api_key=saved_api_key)
        if not cfg.get("enabled", False):
            return [{"success": False, "status": "disabled", "rjcode": item.get("rjcode"), "translated_title": None} for item in items]

        batch_size = _safe_int(cfg.get("batch_size"), 5)
        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_tasks = []
            for item in batch:
                work_name = _safe_text(item.get("work_name", ""))
                if not work_name:
                    results.append({
                        "success": False,
                        "status": "skipped_empty",
                        "rjcode": item.get("rjcode"),
                        "translated_title": None,
                    })
                    continue
                batch_tasks.append(self.translate_single(work_name, config, saved_api_key=saved_api_key))

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "success": False,
                        "status": "error",
                        "rjcode": batch[j].get("rjcode"),
                        "translated_title": None,
                        "error": str(result),
                    })
                else:
                    result["rjcode"] = batch[j].get("rjcode")
                    results.append(result)

        return results

    async def test_connection(self, raw_config: Any, *, saved_api_key: str = "") -> Dict[str, Any]:
        """测试 AI 模型连接。"""
        config = self._normalize_runtime_config(raw_config, saved_api_key=saved_api_key)
        started = time.perf_counter()
        try:
            import litellm
        except Exception as exc:
            return {"success": False, "error": f"缺少 litellm 依赖: {exc}"}

        if not config.get("model"):
            return {"success": False, "error": "model 不能为空"}
        if not config.get("api_key"):
            return {"success": False, "error": "api_key 不能为空"}

        messages = [
            {"role": "user", "content": "你好，请回复\"OK\"表示连接正常。"}
        ]
        kwargs = self._completion_kwargs(config, messages, timeout_seconds=15)
        try:
            async with _temporary_proxy(config.get("proxy_url", "")):
                response = await litellm.acompletion(**kwargs)
            content, usage = _extract_litellm_content(response)
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "success": True,
                "duration_ms": duration_ms,
                "model": config.get("model", ""),
                "response": content[:200],
                "tokens": usage.get("total_tokens", 0),
            }
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_info = _normalize_error(exc)
            return {
                "success": False,
                "error": error_info,
                "duration_ms": duration_ms,
                "model": config.get("model", ""),
            }


_ai_title_translation_service: Optional[AITitleTranslationService] = None


def get_ai_title_translation_service() -> AITitleTranslationService:
    global _ai_title_translation_service
    if _ai_title_translation_service is None:
        _ai_title_translation_service = AITitleTranslationService()
    return _ai_title_translation_service