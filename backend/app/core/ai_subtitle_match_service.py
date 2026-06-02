"""AI 字幕文件名配对服务。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)

MASKED_SECRET = "********"
AI_MATCH_MODES = {"rule", "ai_auto", "rule_ai_auto", "ai_assist"}
AI_ACTIVE_MODES = {"ai_auto", "rule_ai_auto", "ai_assist"}
_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_proxy_lock = asyncio.Lock()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_ai_match_mode(value: Any) -> str:
    mode = _safe_text(value).lower()
    return mode if mode in AI_MATCH_MODES else "rule_ai_auto"


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
        return "", {
            "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
            "completion_tokens": _safe_int(usage.get("completion_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
        }
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
    if isinstance(message, dict):
        content = message.get("content") or ""
    else:
        content = getattr(message, "content", "") if message is not None else ""
    return str(content or ""), {
        "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
        "completion_tokens": _safe_int(usage.get("completion_tokens")),
        "total_tokens": _safe_int(usage.get("total_tokens")),
    }


def _is_azure_config(config: Dict[str, Any]) -> bool:
    base_url = _safe_text(config.get("api_base")).lower()
    api_version = _safe_text(config.get("api_version"))
    return bool(api_version and ("azure" in base_url or ".openai.azure.com" in base_url))


def _normalize_openai_compatible_model_id(model: str, config: Dict[str, Any]) -> str:
    raw = _safe_text(model)
    if not raw or not config.get("api_base") or _is_azure_config(config):
        return raw
    if "/" not in raw:
        return raw
    prefix, rest = raw.split("/", 1)
    if prefix.strip().lower() == "openai" and rest.strip():
        return rest.strip()
    return raw


def _parse_json_content(content: str) -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ValueError("模型返回为空")
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回 JSON 顶层不是对象")
    return parsed


def _normalize_error(exc: Exception) -> Dict[str, str]:
    raw = str(exc or "")
    lowered = raw.lower()
    exc_name = exc.__class__.__name__.lower()
    code = "unknown_error"
    title = "未知错误"
    suggestion = "查看 raw_summary，确认模型服务和配置是否可用"

    if "timeout" in lowered or "timeout" in exc_name:
        code, title, suggestion = "timeout", "请求超时", "调大超时时间，或检查代理/模型服务响应速度"
    elif "rate" in lowered and "limit" in lowered or "ratelimit" in exc_name:
        code, title, suggestion = "rate_limited", "触发限流", "稍后重试，或降低并发/更换模型"
    elif "quota" in lowered or "insufficient" in lowered:
        code, title, suggestion = "quota_exceeded", "额度不足", "检查账号额度、账单状态或模型调用配额"
    elif "unauthorized" in lowered or "forbidden" in lowered or "api key" in lowered or "authentication" in exc_name:
        code, title, suggestion = "auth_failed", "API Key 无效", "检查 Key 是否填错、是否过期、是否有当前模型权限"
    elif "not found" in lowered or "model" in lowered and "does not exist" in lowered or "notfound" in exc_name:
        code, title, suggestion = "model_not_found", "模型不存在", "检查模型名是否符合 LiteLLM 格式，或账号是否有该模型权限"
    elif "proxy" in lowered:
        code, title, suggestion = "proxy_error", "代理不可用", "检查代理地址格式和代理服务是否正在运行"
    elif "base url" in lowered or "api_base" in lowered or "invalid url" in lowered:
        code, title, suggestion = "base_url_invalid", "Base URL 无效", "检查 Base URL 是否包含协议、路径是否正确"
    elif any(token in lowered for token in ("connection", "connect", "dns", "network", "ssl")):
        code, title, suggestion = "network_error", "网络连接失败", "检查网络、代理、DNS 和模型服务地址"
    elif "json" in lowered:
        code, title, suggestion = "json_output_failed", "JSON 输出不可用", "换用支持 JSON 输出的模型，或调整提示词"
    elif "request was blocked" in lowered or "blocked" in lowered:
        code, title, suggestion = "provider_error", "模型服务拦截请求", "当前 Key/Base URL 已连到上游，但上游拒绝了这次聊天请求；可尝试刷新模型列表后选择原始模型 ID，或检查中转站模型权限/风控"
    elif raw:
        code, title, suggestion = "provider_error", "模型服务返回错误", "查看 raw_summary 并按上游服务错误处理"

    return {
        "code": code,
        "title": title,
        "message": raw[:500] or title,
        "suggestion": suggestion,
        "raw_summary": raw[:800],
    }


@asynccontextmanager
async def _temporary_proxy(proxy_url: str):
    proxy = _safe_text(proxy_url)
    if not proxy:
        yield
        return
    async with _proxy_lock:
        previous = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
        try:
            for key in _PROXY_ENV_KEYS:
                os.environ[key] = proxy
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class AISubtitleMatchService:
    """封装 LiteLLM 调用、配对校验和 usage 记录。"""

    def _normalize_runtime_config(self, raw_config: Any, *, saved_api_key: str = "") -> Dict[str, Any]:
        config = _config_to_dict(raw_config)
        api_key = _safe_text(config.get("api_key"))
        if api_key == MASKED_SECRET:
            config["api_key"] = saved_api_key
        config["model"] = _safe_text(config.get("model"))
        config["api_key"] = _safe_text(config.get("api_key"))
        config["api_base"] = _safe_text(config.get("api_base"))
        config["api_version"] = _safe_text(config.get("api_version"))
        config["organization"] = _safe_text(config.get("organization"))
        config["proxy_url"] = _safe_text(config.get("proxy_url"))
        config["timeout_seconds"] = max(1, min(_safe_int(config.get("timeout_seconds"), 30), 300))
        config["max_retries"] = max(0, min(_safe_int(config.get("max_retries"), 2), 10))
        config["temperature"] = _safe_float(config.get("temperature"), 0)
        config["confidence_threshold"] = max(0, min(_safe_int(config.get("confidence_threshold"), 85), 100))
        config["max_items_per_request"] = max(1, min(_safe_int(config.get("max_items_per_request"), 120), 500))
        config["prompt_template"] = _safe_text(config.get("prompt_template"))
        config["model"] = _normalize_openai_compatible_model_id(config["model"], config)
        return config

    def _build_messages(self, config: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, str]]:
        prompt = config.get("prompt_template") or (
            "你是字幕文件名匹配器。只根据文件名输出 JSON。"
            "一个 audio_id 最多匹配一个 subtitle_group_id，不确定就放入 unmatched。"
        )
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ]

    def _request_hash(self, config: Dict[str, Any], payload: Dict[str, Any]) -> str:
        data = {
            "model": config.get("model") or "",
            "prompt": config.get("prompt_template") or "",
            "payload": payload,
        }
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    async def _call_model(self, config: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
        if not config.get("model"):
            raise ValueError("missing_config: model 不能为空")
        if not config.get("api_key"):
            raise ValueError("missing_config: api_key 不能为空")

        try:
            import litellm
        except Exception as exc:
            raise RuntimeError(f"missing_config: 后端未安装 litellm: {exc}") from exc

        kwargs = {
            "model": config["model"],
            "messages": self._build_messages(config, payload),
            "temperature": config["temperature"],
            "timeout": config["timeout_seconds"],
            "num_retries": config["max_retries"],
            "api_key": config["api_key"],
            "response_format": {"type": "json_object"},
        }
        if config.get("api_base") and not _is_azure_config(config):
            kwargs["custom_llm_provider"] = "openai"
            kwargs["extra_headers"] = {"User-Agent": "KikoeruManager/AI-Subtitle"}
        if config.get("api_base"):
            kwargs["api_base"] = config["api_base"]
        if config.get("api_version"):
            kwargs["api_version"] = config["api_version"]
        if config.get("organization"):
            kwargs["organization"] = config["organization"]

        async with _temporary_proxy(config.get("proxy_url", "")):
            response = await litellm.acompletion(**kwargs)
        content, usage = _extract_litellm_content(response)
        try:
            return _parse_json_content(content), usage
        except Exception as exc:
            raise ValueError(f"json_output_failed: {exc}") from exc

    def _models_endpoint(self, config: Dict[str, Any]) -> Tuple[str, bool]:
        base_url = (config.get("api_base") or "https://api.openai.com/v1").strip().rstrip("/")
        api_version = _safe_text(config.get("api_version"))
        lowered = base_url.lower()
        is_azure = bool(api_version and ("azure" in lowered or ".openai.azure.com" in lowered))
        if is_azure:
            if "/openai/deployments" in lowered:
                url = base_url
            elif lowered.endswith("/openai"):
                url = f"{base_url}/deployments"
            else:
                url = f"{base_url}/openai/deployments"
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}api-version={api_version}", True
        if lowered.endswith("/models"):
            return base_url, False
        return f"{base_url}/models", False

    def _model_value_for_litellm(self, model_id: str, config: Dict[str, Any], *, is_azure: bool = False) -> str:
        clean_id = _safe_text(model_id)
        if not clean_id or "/" in clean_id:
            return clean_id
        if is_azure:
            return f"azure/{clean_id}"
        return clean_id

    def _normalize_model_entries(self, payload: Any, config: Dict[str, Any], *, is_azure: bool = False) -> List[Dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        models: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            model_id = _safe_text(item.get("id") or item.get("model"))
            if not model_id:
                continue
            value = self._model_value_for_litellm(model_id, config, is_azure=is_azure)
            if not value or value in seen:
                continue
            seen.add(value)
            models.append({
                "id": model_id,
                "value": value,
                "label": model_id,
                "owned_by": _safe_text(item.get("owned_by") or item.get("owner") or item.get("model")),
                "created": item.get("created"),
                "source": "azure_deployments" if is_azure else "openai_compatible_models",
            })
        return sorted(models, key=lambda row: str(row.get("id") or "").lower())

    async def list_models(self, raw_config: Any, *, saved_api_key: str = "") -> Dict[str, Any]:
        config = self._normalize_runtime_config(raw_config, saved_api_key=saved_api_key)
        started = time.perf_counter()
        if not config.get("api_key"):
            return {
                "success": False,
                "status": "failed",
                "error": {
                    "code": "missing_config",
                    "title": "AI 配置不完整",
                    "message": "API Key 必填",
                    "suggestion": "填写 API Key 后再获取模型列表",
                    "raw_summary": "",
                },
                "models": [],
                "duration_ms": 0,
            }
        try:
            import httpx

            url, is_azure = self._models_endpoint(config)
            headers = {"Accept": "application/json"}
            if is_azure:
                headers["api-key"] = config["api_key"]
            else:
                headers["Authorization"] = f"Bearer {config['api_key']}"
            timeout_seconds = max(1, min(_safe_int(config.get("timeout_seconds"), 30), 300))
            async with _temporary_proxy(config.get("proxy_url", "")):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout_seconds, connect=min(10, timeout_seconds)),
                    trust_env=True,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                try:
                    summary = json.dumps(response.json(), ensure_ascii=False)[:800]
                except Exception:
                    summary = response.text[:800]
                raise RuntimeError(f"{response.status_code} {response.reason_phrase}: {summary}")
            payload = response.json()
            models = self._normalize_model_entries(payload, config, is_azure=is_azure)
            return {
                "success": True,
                "status": "ok",
                "message": f"已获取 {len(models)} 个模型",
                "models": models,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "base_url": config.get("api_base") or "https://api.openai.com/v1",
            }
        except Exception as exc:
            return {
                "success": False,
                "status": "failed",
                "error": _normalize_error(exc),
                "models": [],
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "base_url": config.get("api_base") or "https://api.openai.com/v1",
            }

    def _build_safe_payload(
        self,
        audio_index: List[Dict[str, Any]],
        subtitle_groups: List[Dict[str, Any]],
        *,
        selected_audio_paths: Optional[set[str]] = None,
        selected_group_keys: Optional[set[str]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        audio_by_id: Dict[str, Dict[str, Any]] = {}
        group_by_id: Dict[str, Dict[str, Any]] = {}
        audio_files = []
        group_items = []

        for index, audio in enumerate(audio_index, start=1):
            audio_path = _safe_text(audio.get("path"))
            if selected_audio_paths is not None and audio_path not in selected_audio_paths:
                continue
            audio_id = f"a{len(audio_files) + 1}"
            audio_by_id[audio_id] = audio
            audio_files.append({
                "id": audio_id,
                "filename": _safe_text(audio.get("display_name")) or os.path.basename(audio_path),
            })

        for group in subtitle_groups:
            group_key = _safe_text(group.get("base_name"))
            if selected_group_keys is not None and group_key not in selected_group_keys:
                continue
            group_id = f"g{len(group_items) + 1}"
            group_by_id[group_id] = group
            group_items.append({
                "id": group_id,
                "base_name": group_key,
                "files": [
                    {
                        "id": f"{group_id}_s{file_index}",
                        "filename": _safe_text(item.get("name")),
                    }
                    for file_index, item in enumerate(group.get("files") or [], start=1)
                ],
            })

        return {
            "audio_files": audio_files,
            "subtitle_groups": group_items,
        }, audio_by_id, group_by_id

    def _group_key_by_subtitle_path(self, subtitle_groups: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
        by_path = {}
        by_name = {}
        for group in subtitle_groups:
            group_key = _safe_text(group.get("base_name"))
            for item in group.get("files") or []:
                path = _safe_text(item.get("path"))
                name = _safe_text(item.get("name"))
                if path:
                    by_path[path] = group_key
                if name:
                    by_name.setdefault(name, group_key)
        return by_path, by_name

    def _preserved_rule_matches(
        self,
        base_match_result: Dict[str, Any],
        subtitle_groups: List[Dict[str, Any]],
        threshold: int,
    ) -> Tuple[List[Dict[str, Any]], set[str], set[str]]:
        group_by_path, group_by_name = self._group_key_by_subtitle_path(subtitle_groups)
        preserved = []
        used_audio = set()
        used_groups = set()
        for match in base_match_result.get("matches") or []:
            score = _safe_int(match.get("match_score"))
            if score < threshold:
                continue
            audio_path = _safe_text(match.get("audio_path"))
            group_key = group_by_path.get(_safe_text(match.get("subtitle_path"))) or group_by_name.get(_safe_text(match.get("subtitle_name")))
            if not audio_path or not group_key:
                continue
            preserved.append(dict(match))
            used_audio.add(audio_path)
            used_groups.add(group_key)
        return preserved, used_audio, used_groups

    def _expand_match(
        self,
        audio: Dict[str, Any],
        group: Dict[str, Any],
        *,
        naming_strategy: str,
        match_type: str,
        score: int,
        reason: str = "",
    ) -> List[Dict[str, Any]]:
        output = []
        for subtitle in group.get("files") or []:
            ext = _safe_text(subtitle.get("ext")) or os.path.splitext(_safe_text(subtitle.get("name")))[1].lower() or ".vtt"
            subtitle_base = _safe_text(subtitle.get("base_name")) or os.path.splitext(_safe_text(subtitle.get("name")))[0]
            output_base = _safe_text(audio.get("base_name")) if naming_strategy == "audio" else subtitle_base
            row = {
                "audio_path": _safe_text(audio.get("path")),
                "audio_name": _safe_text(audio.get("display_name")) or os.path.basename(_safe_text(audio.get("path"))),
                "subtitle_path": _safe_text(subtitle.get("path")),
                "subtitle_name": _safe_text(subtitle.get("name")),
                "output_subtitle_name": f"{output_base}{ext}",
                "match_type": match_type,
                "match_score": score,
            }
            if reason:
                row["match_reason"] = reason
            output.append(row)
        return output

    def _validate_ai_response(
        self,
        response: Dict[str, Any],
        audio_by_id: Dict[str, Dict[str, Any]],
        group_by_id: Dict[str, Dict[str, Any]],
        threshold: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        matches = response.get("matches") or []
        if not isinstance(matches, list):
            raise ValueError("json_output_failed: matches 必须是数组")

        used_audio = set()
        used_groups = set()
        valid_matches = []
        low_confidence = []
        errors = []

        for item in matches:
            if not isinstance(item, dict):
                errors.append("match_item_not_object")
                continue
            audio_id = _safe_text(item.get("audio_id"))
            group_id = _safe_text(item.get("subtitle_group_id"))
            confidence = max(0, min(_safe_int(item.get("confidence")), 100))
            reason = _safe_text(item.get("reason"))
            if audio_id not in audio_by_id:
                errors.append(f"unknown_audio_id:{audio_id}")
                continue
            if group_id not in group_by_id:
                errors.append(f"unknown_subtitle_group_id:{group_id}")
                continue
            if audio_id in used_audio:
                errors.append(f"duplicate_audio_id:{audio_id}")
                continue
            if group_id in used_groups:
                errors.append(f"duplicate_subtitle_group_id:{group_id}")
                continue
            row = {
                "audio_id": audio_id,
                "subtitle_group_id": group_id,
                "confidence": confidence,
                "reason": reason,
            }
            valid_matches.append(row)
            used_audio.add(audio_id)
            used_groups.add(group_id)
            if confidence < threshold:
                low_confidence.append(row)

        return valid_matches, low_confidence, errors

    def _build_unmatched(
        self,
        audio_index: List[Dict[str, Any]],
        subtitle_groups: List[Dict[str, Any]],
        used_audio_paths: set[str],
        used_group_keys: set[str],
    ) -> Tuple[List[str], List[str]]:
        unmatched_audio = [
            _safe_text(audio.get("display_name")) or os.path.basename(_safe_text(audio.get("path")))
            for audio in audio_index
            if _safe_text(audio.get("path")) not in used_audio_paths
        ]
        unmatched_subtitles = [
            _safe_text(item.get("name"))
            for group in subtitle_groups
            if _safe_text(group.get("base_name")) not in used_group_keys
            for item in group.get("files") or []
        ]
        return unmatched_audio, unmatched_subtitles

    def _duplicate_outputs(self, matches: List[Dict[str, Any]]) -> List[str]:
        seen = set()
        duplicated = set()
        for match in matches:
            output_name = _safe_text(match.get("output_subtitle_name"))
            if not output_name:
                continue
            key = output_name.lower()
            if key in seen:
                duplicated.add(output_name)
            seen.add(key)
        return sorted(duplicated)

    async def build_auto_match_result(
        self,
        *,
        config: Any,
        audio_index: List[Dict[str, Any]],
        subtitle_groups: List[Dict[str, Any]],
        base_match_result: Dict[str, Any],
        mode: str,
        naming_strategy: str,
        threshold: Optional[int] = None,
        task_id: str = "",
        rjcode: str = "",
    ) -> Dict[str, Any]:
        runtime_config = self._normalize_runtime_config(config)
        resolved_mode = normalize_ai_match_mode(mode)
        resolved_threshold = max(0, min(_safe_int(threshold, runtime_config.get("confidence_threshold", 85)), 100))
        started = time.perf_counter()

        if not runtime_config.get("enabled") or resolved_mode not in {"ai_auto", "rule_ai_auto", "ai_assist"}:
            return {
                "used": False,
                "status": "skipped",
                "match_result": base_match_result,
                "metadata": {
                    "ai_match_status": "skipped",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": False,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                },
            }
        if resolved_mode in {"ai_auto", "rule_ai_auto"} and not runtime_config.get("auto_apply_enabled"):
            return {
                "used": False,
                "status": "disabled",
                "match_result": base_match_result,
                "metadata": {
                    "ai_match_status": "disabled",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": False,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                },
            }
        if resolved_mode == "ai_assist" and not runtime_config.get("manual_assist_enabled"):
            return {
                "used": False,
                "status": "disabled",
                "match_result": base_match_result,
                "metadata": {
                    "ai_match_status": "disabled",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": False,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                },
            }

        preserved = []
        preserved_audio = set()
        preserved_groups = set()
        if resolved_mode == "rule_ai_auto":
            preserved, preserved_audio, preserved_groups = self._preserved_rule_matches(
                base_match_result,
                subtitle_groups,
                resolved_threshold,
            )
            selected_audio = {
                _safe_text(audio.get("path"))
                for audio in audio_index
                if _safe_text(audio.get("path")) not in preserved_audio
            }
            selected_groups = {
                _safe_text(group.get("base_name"))
                for group in subtitle_groups
                if _safe_text(group.get("base_name")) not in preserved_groups
            }
        else:
            selected_audio = None
            selected_groups = None

        payload, audio_by_id, group_by_id = self._build_safe_payload(
            audio_index,
            subtitle_groups,
            selected_audio_paths=selected_audio,
            selected_group_keys=selected_groups,
        )
        request_hash = self._request_hash(runtime_config, payload)
        request_item_count = len(payload["audio_files"]) + len(payload["subtitle_groups"])
        if request_item_count > int(runtime_config.get("max_items_per_request") or 120):
            unmatched_audio, unmatched_subtitles = self._build_unmatched(audio_index, subtitle_groups, preserved_audio, preserved_groups)
            match_result = {
                "matches": preserved,
                "matched_group_count": len(preserved_groups),
                "matched_subtitle_count": len(preserved),
                "unmatched_audio": unmatched_audio,
                "unmatched_subtitles": unmatched_subtitles,
                "ai_validation_errors": [f"request_too_large:{request_item_count}>{runtime_config.get('max_items_per_request')}"],
            }
            return {
                "used": True,
                "status": "awaiting_manual",
                "auto_safe": False,
                "match_result": match_result,
                "metadata": {
                    "ai_match_status": "awaiting_manual",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": False,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                    "ai_low_confidence_count": 0,
                    "ai_unmatched_audio_count": len(unmatched_audio),
                    "ai_unmatched_subtitle_count": len(unmatched_subtitles),
                    "ai_match_result": match_result,
                },
            }
        if not payload["audio_files"] or not payload["subtitle_groups"]:
            unmatched_audio, unmatched_subtitles = self._build_unmatched(audio_index, subtitle_groups, preserved_audio, preserved_groups)
            duplicate_outputs = self._duplicate_outputs(preserved)
            auto_safe = (
                resolved_mode == "rule_ai_auto"
                and bool(preserved)
                and not unmatched_audio
                and not unmatched_subtitles
                and not duplicate_outputs
            )
            status = "succeeded" if auto_safe else ("awaiting_manual" if resolved_mode == "rule_ai_auto" else "skipped_no_items")
            match_result = {
                "matches": preserved,
                "matched_group_count": len(preserved_groups),
                "matched_subtitle_count": len(preserved),
                "unmatched_audio": unmatched_audio,
                "unmatched_subtitles": unmatched_subtitles,
                "ai_validation_errors": [],
                "ai_duplicate_outputs": duplicate_outputs,
            }
            return {
                "used": resolved_mode == "rule_ai_auto",
                "status": status,
                "auto_safe": auto_safe,
                "match_result": match_result,
                "metadata": {
                    "ai_match_status": status if resolved_mode == "rule_ai_auto" else "skipped",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": auto_safe,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                    "ai_low_confidence_count": 0,
                    "ai_unmatched_audio_count": len(unmatched_audio),
                    "ai_unmatched_subtitle_count": len(unmatched_subtitles),
                    "ai_match_result": match_result,
                },
            }

        try:
            response, usage = await self._call_model(runtime_config, payload)
            ai_matches, low_confidence, validation_errors = self._validate_ai_response(
                response,
                audio_by_id,
                group_by_id,
                resolved_threshold,
            )
            final_matches = list(preserved)
            used_audio_paths = set(preserved_audio)
            used_group_keys = set(preserved_groups)
            ai_result_items = []
            for item in ai_matches:
                audio = audio_by_id[item["audio_id"]]
                group = group_by_id[item["subtitle_group_id"]]
                reason = item.get("reason") or ""
                expanded = self._expand_match(
                    audio,
                    group,
                    naming_strategy=naming_strategy,
                    match_type=f"AI自动配对: {reason}" if reason else "AI自动配对",
                    score=item["confidence"],
                    reason=reason,
                )
                for row in expanded:
                    row["ai_confidence"] = item["confidence"]
                    row["ai_reason"] = reason
                final_matches.extend(expanded)
                used_audio_paths.add(_safe_text(audio.get("path")))
                used_group_keys.add(_safe_text(group.get("base_name")))
                ai_result_items.append({
                    "audio_name": _safe_text(audio.get("display_name")),
                    "subtitle_group": _safe_text(group.get("base_name")),
                    "confidence": item["confidence"],
                    "reason": reason,
                })

            unmatched_audio, unmatched_subtitles = self._build_unmatched(
                audio_index,
                subtitle_groups,
                used_audio_paths,
                used_group_keys,
            )
            duplicate_outputs = self._duplicate_outputs(final_matches)
            auto_safe = (
                resolved_mode != "ai_assist"
                and not low_confidence
                and not validation_errors
                and not unmatched_audio
                and not unmatched_subtitles
                and not duplicate_outputs
            )
            match_result = {
                "matches": final_matches,
                "matched_group_count": len(used_group_keys),
                "matched_subtitle_count": len(final_matches),
                "unmatched_audio": unmatched_audio,
                "unmatched_subtitles": unmatched_subtitles,
                "ai_result_items": ai_result_items,
                "ai_validation_errors": validation_errors,
                "ai_duplicate_outputs": duplicate_outputs,
            }
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = "preview" if resolved_mode == "ai_assist" else ("succeeded" if auto_safe else "awaiting_manual")
            await self.record_usage(
                task_id=task_id,
                rjcode=rjcode,
                mode=resolved_mode,
                model=runtime_config.get("model", ""),
                request_hash=request_hash,
                audio_count=len(payload["audio_files"]),
                subtitle_group_count=len(payload["subtitle_groups"]),
                matched_count=len(ai_matches),
                low_confidence_count=len(low_confidence),
                unmatched_audio_count=len(unmatched_audio),
                unmatched_subtitle_count=len(unmatched_subtitles),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                duration_ms=duration_ms,
                status=status,
                error_summary=";".join(validation_errors + duplicate_outputs)[:800],
                auto_applied=auto_safe,
            )
            return {
                "used": True,
                "status": status,
                "auto_safe": auto_safe,
                "match_result": match_result,
                "metadata": {
                    "ai_match_status": status,
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": auto_safe,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                    "ai_low_confidence_count": len(low_confidence),
                    "ai_unmatched_audio_count": len(unmatched_audio),
                    "ai_unmatched_subtitle_count": len(unmatched_subtitles),
                    "ai_match_result": match_result,
                },
            }
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            normalized = _normalize_error(exc)
            if str(exc).startswith("missing_config"):
                normalized.update({
                    "code": "missing_config",
                    "title": "AI 配置不完整",
                    "suggestion": "检查模型名和 API Key 是否已填写",
                })
            await self.record_usage(
                task_id=task_id,
                rjcode=rjcode,
                mode=resolved_mode,
                model=runtime_config.get("model", ""),
                request_hash=request_hash,
                audio_count=len(payload.get("audio_files") or []),
                subtitle_group_count=len(payload.get("subtitle_groups") or []),
                duration_ms=duration_ms,
                status="failed",
                error_summary=normalized.get("raw_summary", ""),
                auto_applied=False,
            )
            return {
                "used": True,
                "status": "failed",
                "auto_safe": False,
                "match_result": base_match_result,
                "error": normalized,
                "metadata": {
                    "ai_match_status": "failed",
                    "ai_match_mode": resolved_mode,
                    "ai_auto_applied": False,
                    "ai_match_model": runtime_config.get("model", ""),
                    "ai_confidence_threshold": resolved_threshold,
                    "ai_low_confidence_count": 0,
                    "ai_unmatched_audio_count": len(base_match_result.get("unmatched_audio") or []),
                    "ai_unmatched_subtitle_count": len(base_match_result.get("unmatched_subtitles") or []),
                    "ai_match_error": normalized,
                },
            }

    async def test_connection(self, raw_config: Any, *, saved_api_key: str = "") -> Dict[str, Any]:
        config = self._normalize_runtime_config(raw_config, saved_api_key=saved_api_key)
        started = time.perf_counter()
        if not config.get("model") or not config.get("api_key"):
            return {
                "success": False,
                "status": "failed",
                "error": {
                    "code": "missing_config",
                    "title": "AI 配置不完整",
                    "message": "模型名和 API Key 必填",
                    "suggestion": "填写模型名和 API Key 后再测试",
                    "raw_summary": "",
                },
                "model": config.get("model", ""),
                "duration_ms": 0,
            }
        payload = {
            "audio_files": [{"id": "a1", "filename": "01_耳かき.wav"}],
            "subtitle_groups": [{"id": "g1", "base_name": "01_耳かき", "files": [{"id": "g1_s1", "filename": "01_耳かき.srt"}]}],
        }
        try:
            response, _usage = await self._call_model(config, payload)
            matches = response.get("matches") or []
            if not isinstance(matches, list):
                raise ValueError("json_output_failed: matches 必须是数组")
            return {
                "success": True,
                "status": "ok",
                "message": "模型连接正常，JSON 输出可用",
                "model": config.get("model", ""),
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "capabilities": {"json_output": True},
                "sample": {
                    "matched_count": len(matches),
                    "low_confidence_count": len([item for item in matches if _safe_int((item or {}).get("confidence")) < config["confidence_threshold"]]),
                },
            }
        except Exception as exc:
            error = _normalize_error(exc)
            if str(exc).startswith("missing_config"):
                error.update({
                    "code": "missing_config",
                    "title": "AI 配置不完整",
                    "suggestion": "检查模型名、API Key 和 LiteLLM 依赖是否可用",
                })
            return {
                "success": False,
                "status": "failed",
                "error": error,
                "model": config.get("model", ""),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }

    async def record_usage(self, **kwargs) -> None:
        try:
            from ..models.database import AISubtitleMatchUsage, SessionLocal

            db = SessionLocal()
            try:
                row = AISubtitleMatchUsage(
                    id=str(uuid.uuid4()),
                    task_id=_safe_text(kwargs.get("task_id")),
                    rjcode=_safe_text(kwargs.get("rjcode")).upper(),
                    mode=_safe_text(kwargs.get("mode")),
                    model=_safe_text(kwargs.get("model")),
                    request_hash=_safe_text(kwargs.get("request_hash")),
                    audio_count=_safe_int(kwargs.get("audio_count")),
                    subtitle_group_count=_safe_int(kwargs.get("subtitle_group_count")),
                    matched_count=_safe_int(kwargs.get("matched_count")),
                    low_confidence_count=_safe_int(kwargs.get("low_confidence_count")),
                    unmatched_audio_count=_safe_int(kwargs.get("unmatched_audio_count")),
                    unmatched_subtitle_count=_safe_int(kwargs.get("unmatched_subtitle_count")),
                    prompt_tokens=_safe_int(kwargs.get("prompt_tokens")),
                    completion_tokens=_safe_int(kwargs.get("completion_tokens")),
                    total_tokens=_safe_int(kwargs.get("total_tokens")),
                    duration_ms=_safe_int(kwargs.get("duration_ms")),
                    status=_safe_text(kwargs.get("status")),
                    error_summary=_safe_text(kwargs.get("error_summary"))[:800],
                    auto_applied=bool(kwargs.get("auto_applied")),
                )
                db.add(row)
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.warning("[AI字幕] usage 记录失败", exc_info=True)

    def list_usage(self, limit: int = 100) -> Dict[str, Any]:
        from ..models.database import AISubtitleMatchUsage, SessionLocal

        safe_limit = max(1, min(int(limit or 100), 500))
        db = SessionLocal()
        try:
            rows = (
                db.query(AISubtitleMatchUsage)
                .order_by(AISubtitleMatchUsage.created_at.desc())
                .limit(safe_limit)
                .all()
            )
            items = [row.to_dict() for row in rows]
            summary = {
                "total_requests": len(items),
                "total_tokens": sum(int(item.get("total_tokens") or 0) for item in items),
                "auto_applied": sum(1 for item in items if item.get("auto_applied")),
                "failed": sum(1 for item in items if item.get("status") == "failed"),
            }
            return {"items": items, "summary": summary}
        finally:
            db.close()


_ai_subtitle_match_service: Optional[AISubtitleMatchService] = None


def get_ai_subtitle_match_service() -> AISubtitleMatchService:
    global _ai_subtitle_match_service
    if _ai_subtitle_match_service is None:
        _ai_subtitle_match_service = AISubtitleMatchService()
    return _ai_subtitle_match_service
