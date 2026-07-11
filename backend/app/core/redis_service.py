from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - 依赖未安装时仍允许 py_compile
    redis = None  # type: ignore

logger = logging.getLogger(__name__)


_TASK_RUNTIME_METADATA_KEYS = (
    'download_files',
    'download_runtime',
    'failed_files',
    'upload_runtime',
    'bonus_probe_meta',
    'awaiting_manual_match',
    'manual_match_completed',
    'manual_match_completed_at',
    'manual_match_applied_pairs',
    'manual_match_deleted_subtitles',
    'naming_strategy',
    'ai_match_status',
    'ai_match_mode',
    'ai_auto_applied',
    'ai_low_confidence_count',
    'ai_unmatched_audio_count',
    'ai_unmatched_subtitle_count',
)

_BONUS_PROBE_CACHE_STREAM = 'bonus-probe:cache:stream'
_BONUS_PROBE_CACHE_GROUP = 'bonus-probe-cache-writers'
_LIBRARY_INDEX_MUTATION_STREAM = 'library-index:mutation:stream'
_LIBRARY_INDEX_MUTATION_GROUP = 'library-index-materializers'
_LIBRARY_INDEX_DIRTY_KEY_PARTS = ('library-index', 'watcher-dirty')

_POP_DUE_ZSET_SCRIPT = """
local rows = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'WITHSCORES', 'LIMIT', 0, ARGV[2])
for index = 1, #rows, 2 do
    redis.call('ZREM', KEYS[1], rows[index])
end
return rows
"""

_REMOVE_DIRTY_PATHS_SCRIPT = """
local roots = cjson.decode(ARGV[1])
local maxScore = tonumber(ARGV[2])
local members = redis.call('ZRANGE', KEYS[1], 0, -1)
local removed = 0
for _, member in ipairs(members) do
    for _, root in ipairs(roots) do
        if root == '/' or member == root or string.sub(member, 1, string.len(root) + 1) == root .. '/' then
            local score = tonumber(redis.call('ZSCORE', KEYS[1], member))
            if not maxScore or (score and score <= maxScore) then
                removed = removed + redis.call('ZREM', KEYS[1], member)
            end
            break
        end
    end
end
return removed
"""


class RedisUnavailableError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _mask_redis_url(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        parts = urlsplit(text)
        if not parts.password:
            return text
        username = parts.username or ''
        host = parts.hostname or ''
        port = f':{parts.port}' if parts.port else ''
        auth = f'{username}:********@' if username else ':********@'
        return urlunsplit((parts.scheme, f'{auth}{host}{port}', parts.path, parts.query, parts.fragment))
    except Exception:
        return re.sub(r'//([^/@:]*):([^/@]*)@', '//***:********@', text)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':'))


def _json_loads(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8', errors='replace')
    if not isinstance(payload, str):
        return payload
    return json.loads(payload)


def _redis_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


def _redis_mapping_value(mapping: Any, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    if key in mapping:
        return mapping[key]
    return mapping.get(key.encode('utf-8'), default)


class RedisService:
    def __init__(self) -> None:
        self._client = None
        self._client_signature: Optional[tuple[Any, ...]] = None
        self._client_lock = threading.Lock()
        self._last_error = ''
        self._last_ping_latency_ms: Optional[float] = None
        self._memory_lock = threading.Lock()
        self._memory_task_runtime: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._memory_streams: dict[str, deque[dict[str, Any]]] = {}
        self._memory_stream_write_counts: dict[str, int] = {}
        self._memory_runtime_write_count = 0
        self._memory_runtime_read_count = 0
        self._memory_last_error = ''
        self._library_index_channel_lock = threading.Lock()
        self._library_index_publish_count = 0
        self._library_index_publish_failure_count = 0
        self._library_index_last_publish_at = ''
        self._library_index_last_publish_error = ''
        self._library_index_consumer_read_count = 0
        self._library_index_consumer_ack_count = 0
        self._library_index_consumer_deferred_count = 0
        self._library_index_consumer_invalid_count = 0

    def _config(self) -> dict[str, Any]:
        from ..config.settings import get_config

        cfg = getattr(get_config(), 'redis', None)
        enabled = bool(getattr(cfg, 'enabled', True))
        required = bool(getattr(cfg, 'required', True))
        url = str(getattr(cfg, 'url', 'redis://localhost:6379/0') or 'redis://localhost:6379/0')
        namespace = str(getattr(cfg, 'namespace', 'kikoerumanager') or 'kikoerumanager').strip() or 'kikoerumanager'
        environment = str(getattr(cfg, 'environment', 'prod') or 'prod').strip() or 'prod'
        socket_timeout = float(getattr(cfg, 'socket_timeout_seconds', 2.0) or 2.0)
        connect_timeout = float(getattr(cfg, 'connect_timeout_seconds', 2.0) or 2.0)
        runtime_ttl = int(getattr(cfg, 'runtime_ttl_seconds', 259200) or 259200)
        short_cache_ttl = int(getattr(cfg, 'short_cache_ttl_seconds', 60) or 60)
        event_stream_maxlen = int(getattr(cfg, 'event_stream_maxlen', 50000) or 50000)
        dirty_stream_maxlen = int(getattr(cfg, 'dirty_stream_maxlen', 200000) or 200000)
        enabled = _env_bool('KIKOERUMANAGER_REDIS_ENABLED', enabled)
        required = _env_bool('KIKOERUMANAGER_REDIS_REQUIRED', required)
        url = os.getenv('KIKOERUMANAGER_REDIS_URL', url).strip() or url
        namespace = os.getenv('KIKOERUMANAGER_REDIS_NAMESPACE', namespace).strip() or namespace
        environment = os.getenv('KIKOERUMANAGER_REDIS_ENVIRONMENT', environment).strip() or environment
        return {
            'enabled': enabled,
            'required': required,
            'url': url,
            'namespace': namespace,
            'environment': environment,
            'socket_timeout': socket_timeout,
            'connect_timeout': connect_timeout,
            'runtime_ttl': max(1, runtime_ttl),
            'short_cache_ttl': max(1, short_cache_ttl),
            'event_stream_maxlen': max(100, event_stream_maxlen),
            'dirty_stream_maxlen': max(100, dirty_stream_maxlen),
        }

    def _runtime_buffer_config(self) -> dict[str, Any]:
        from ..config.settings import get_config

        cfg = getattr(get_config(), 'runtime_buffer', None)
        enabled = bool(getattr(cfg, 'enabled', True))
        backend = str(getattr(cfg, 'backend', 'redis') or 'redis').strip().lower()
        if backend not in {'redis', 'memory'}:
            backend = 'redis'
        return {
            'enabled': enabled,
            'backend': backend,
            'progress_flush_interval_seconds': max(0.5, float(getattr(cfg, 'progress_flush_interval_seconds', 5.0) or 5.0)),
            'log_stream_batch_size': max(50, int(getattr(cfg, 'log_stream_batch_size', 300) or 300)),
            'log_stream_flush_ms': max(100, int(getattr(cfg, 'log_stream_flush_ms', 250) or 250)),
        }

    def _memory_runtime_enabled(self) -> bool:
        cfg = self._runtime_buffer_config()
        return bool(cfg['enabled'] and cfg['backend'] in {'redis', 'memory'})

    def _memory_runtime_set(self, task_id: str, payload: dict[str, Any]) -> None:
        if not task_id or not self._memory_runtime_enabled():
            return
        with self._memory_lock:
            self._memory_task_runtime[task_id] = dict(payload)
            self._memory_task_runtime.move_to_end(task_id)
            while len(self._memory_task_runtime) > 2000:
                self._memory_task_runtime.popitem(last=False)
            self._memory_runtime_write_count += 1

    def _memory_runtime_get(self, task_id: str) -> Optional[dict[str, Any]]:
        if not task_id or not self._memory_runtime_enabled():
            return None
        with self._memory_lock:
            payload = self._memory_task_runtime.get(task_id)
            if not isinstance(payload, dict):
                return None
            self._memory_task_runtime.move_to_end(task_id)
            self._memory_runtime_read_count += 1
            return dict(payload)

    def _memory_stream_append(self, stream_name: str, payload: dict[str, Any]) -> str:
        if not self._memory_runtime_enabled():
            return ''
        name = str(stream_name or '').strip() or 'events:stream'
        with self._memory_lock:
            stream = self._memory_streams.setdefault(name, deque(maxlen=5000))
            message_id = f"memory-{int(time.time() * 1000)}-{len(stream)}"
            stream.append({
                'id': message_id,
                'payload': dict(payload or {}),
                'created_at': datetime.now().isoformat(),
            })
            self._memory_stream_write_counts[name] = int(self._memory_stream_write_counts.get(name, 0)) + 1
            return message_id

    def _memory_status(self) -> dict[str, Any]:
        with self._memory_lock:
            streams = {
                name: {
                    'length': len(stream),
                    'writes': int(self._memory_stream_write_counts.get(name, 0)),
                }
                for name, stream in self._memory_streams.items()
            }
            return {
                'task_runtime_count': len(self._memory_task_runtime),
                'task_runtime_writes': self._memory_runtime_write_count,
                'task_runtime_reads': self._memory_runtime_read_count,
                'streams': streams,
                'last_error': self._memory_last_error,
            }

    def is_enabled(self) -> bool:
        return bool(self._config()['enabled'])

    def is_required(self) -> bool:
        cfg = self._config()
        return bool(cfg['enabled'] and cfg['required'])

    def key(self, *parts: Any) -> str:
        cfg = self._config()
        safe_parts = [str(cfg['namespace']), str(cfg['environment'])]
        for part in parts:
            text = str(part or '').strip().replace(' ', '-')
            text = re.sub(r'[:\r\n\t]+', '-', text)
            if text:
                safe_parts.append(text)
        return ':'.join(safe_parts)

    def stream_key(self, name: str) -> str:
        return self.key(str(name or '').strip().replace(':', '-'))

    def library_index_dirty_key(self, library_id: str) -> str:
        return self.key(*_LIBRARY_INDEX_DIRTY_KEY_PARTS, str(library_id or '').strip())

    def _record_library_index_publish(self, *, success: bool, error: str = '') -> None:
        with self._library_index_channel_lock:
            self._library_index_last_publish_at = datetime.now().isoformat()
            if success:
                self._library_index_publish_count += 1
                self._library_index_last_publish_error = ''
            else:
                self._library_index_publish_failure_count += 1
                self._library_index_last_publish_error = str(error or 'Redis client unavailable')

    def _library_index_publish_runtime_diagnostics(self) -> dict[str, Any]:
        with self._library_index_channel_lock:
            return {
                'published': self._library_index_publish_count,
                'publish_failures': self._library_index_publish_failure_count,
                'last_publish_at': self._library_index_last_publish_at or None,
                'last_publish_error': self._library_index_last_publish_error,
                'consumer_reads': self._library_index_consumer_read_count,
                'consumer_acks': self._library_index_consumer_ack_count,
                'consumer_deferred': self._library_index_consumer_deferred_count,
                'consumer_invalid': self._library_index_consumer_invalid_count,
            }

    def _record_library_index_consumer_result(
        self,
        *,
        reads: int = 0,
        acks: int = 0,
        deferred: int = 0,
        invalid: int = 0,
    ) -> None:
        with self._library_index_channel_lock:
            self._library_index_consumer_read_count += max(0, int(reads or 0))
            self._library_index_consumer_ack_count += max(0, int(acks or 0))
            self._library_index_consumer_deferred_count += max(0, int(deferred or 0))
            self._library_index_consumer_invalid_count += max(0, int(invalid or 0))

    def _signature(self, cfg: dict[str, Any]) -> tuple[Any, ...]:
        return (cfg['enabled'], cfg['url'], cfg['socket_timeout'], cfg['connect_timeout'])

    def client(self, *, required: bool = False):
        cfg = self._config()
        if not cfg['enabled']:
            return None
        if redis is None:
            self._last_error = 'redis Python 依赖未安装'
            if required or cfg['required']:
                raise RedisUnavailableError(self._last_error)
            return None
        signature = self._signature(cfg)
        with self._client_lock:
            if self._client is not None and self._client_signature == signature:
                return self._client
            self._client = redis.Redis.from_url(
                cfg['url'],
                decode_responses=True,
                socket_timeout=cfg['socket_timeout'],
                socket_connect_timeout=cfg['connect_timeout'],
                health_check_interval=30,
            )
            self._client_signature = signature
            return self._client

    def ping(self) -> bool:
        client = self.client(required=False)
        if client is None:
            return not self.is_enabled()
        started = time.perf_counter()
        try:
            client.ping()
            self._last_ping_latency_ms = (time.perf_counter() - started) * 1000
            self._last_error = ''
            return True
        except Exception as exc:
            self._last_error = str(exc)
            self._last_ping_latency_ms = None
            return False

    def startup_check(self) -> None:
        if not self.is_enabled():
            logger.info('[Redis] 已禁用，运行态高频链路不会使用 Redis')
            return
        if self.ping():
            logger.info('[Redis] 连接正常: %s', self.masked_url())
            return
        message = f'Redis 不可用: {self._last_error or "ping failed"} url={self.masked_url()}'
        if self.is_required():
            raise RedisUnavailableError(message)
        logger.warning('[Redis] %s', message)

    def is_available(self) -> bool:
        return self.is_enabled() and self.ping()

    def assert_available_for_high_pressure(self, reason: str) -> None:
        if not self.is_enabled():
            return
        if self.ping():
            return
        raise RedisUnavailableError(f'Redis 不可用，已阻断高频任务: {reason}; {self._last_error}')

    def masked_url(self) -> str:
        return _mask_redis_url(str(self._config()['url']))

    def set_json(self, module: str, type_name: str, item_id: str, payload: Any, *, ttl_seconds: Optional[int] = None) -> bool:
        client = self.client(required=False)
        if client is None:
            return False
        try:
            client.set(
                self.key(module, type_name, item_id),
                _json_dumps(payload),
                ex=int(ttl_seconds or self.runtime_ttl_seconds()),
            )
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 写入 JSON 失败 key=%s:%s:%s', module, type_name, item_id, exc_info=True)
            return False

    def get_json(self, module: str, type_name: str, item_id: str) -> Any:
        client = self.client(required=False)
        if client is None:
            return None
        try:
            raw = client.get(self.key(module, type_name, item_id))
            return _json_loads(raw) if raw else None
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 读取 JSON 失败 key=%s:%s:%s', module, type_name, item_id, exc_info=True)
            return None

    def delete_json(self, module: str, type_name: str, item_id: str) -> None:
        client = self.client(required=False)
        if client is None:
            return
        try:
            client.delete(self.key(module, type_name, item_id))
        except Exception:
            logger.debug('[Redis] 删除 JSON 失败 key=%s:%s:%s', module, type_name, item_id, exc_info=True)

    def get_task_runtime_sync(self, task_id: str) -> Optional[dict[str, Any]]:
        payload = self.get_json('task', 'runtime', str(task_id or ''))
        if isinstance(payload, dict):
            return payload
        return self._memory_runtime_get(str(task_id or ''))

    def write_task_runtime_sync(self, task: Any, *, reason: str = 'progress') -> None:
        buffer_cfg = self._runtime_buffer_config()
        if not buffer_cfg['enabled']:
            return
        status = getattr(task, 'status', '')
        status_value = status.value if hasattr(status, 'value') else str(status or '')
        metadata = getattr(task, 'task_metadata', None) if isinstance(getattr(task, 'task_metadata', None), dict) else {}
        runtime_metadata: dict[str, Any] = {}
        for key in _TASK_RUNTIME_METADATA_KEYS:
            if key not in metadata:
                continue
            value = metadata.get(key)
            if key == 'progress_log':
                runtime_metadata[key] = list(value or [])[-80:]
            else:
                runtime_metadata[key] = value
        payload = {
            'task_id': str(getattr(task, 'id', '') or ''),
            'type': getattr(getattr(task, 'type', None), 'value', str(getattr(task, 'type', '') or '')),
            'domain': str((metadata or {}).get('task_domain') or ''),
            'status': status_value,
            'progress': int(getattr(task, 'progress', 0) or 0),
            'current_step': str(getattr(task, 'current_step', '') or ''),
            'reason': str(reason or ''),
            'progress_log': list((metadata or {}).get('progress_log') or [])[-80:],
            'updated_at': datetime.now().isoformat(),
            **runtime_metadata,
        }
        if not payload['task_id']:
            return
        wrote_redis = False
        if buffer_cfg['backend'] == 'redis' and self.is_enabled():
            wrote_redis = self.set_json('task', 'runtime', payload['task_id'], payload)
        if not wrote_redis:
            self._memory_runtime_set(payload['task_id'], payload)

    def write_realtime_event_sync(self, event: dict[str, Any], *, stream_name: str = 'events:stream') -> str:
        if not isinstance(event, dict) or not event.get('type'):
            return ''
        return self.append_stream_payload_sync(stream_name, dict(event), required=False)

    def append_stream_payload_sync(self, stream_name: str, payload: dict[str, Any], *, maxlen: Optional[int] = None, required: bool = False) -> str:
        buffer_cfg = self._runtime_buffer_config()
        if buffer_cfg['enabled'] and buffer_cfg['backend'] == 'memory':
            return self._memory_stream_append(stream_name, payload)
        client = self.client(required=required)
        if client is None:
            return self._memory_stream_append(stream_name, payload) if buffer_cfg['enabled'] else ''
        resolved_maxlen = int(maxlen or self._config()['event_stream_maxlen'])
        try:
            return str(client.xadd(
                self.stream_key(stream_name),
                {'payload': _json_dumps(payload)},
                maxlen=resolved_maxlen,
                approximate=True,
            ))
        except Exception as exc:
            self._last_error = str(exc)
            if required or self.is_required():
                raise RedisUnavailableError(str(exc)) from exc
            logger.debug('[Redis] 写入 Stream 失败 stream=%s', stream_name, exc_info=True)
            return self._memory_stream_append(stream_name, payload) if buffer_cfg['enabled'] else ''

    def publish_library_index_mutation_hint_sync(
        self,
        library_id: str,
        accepted_seq: int,
        operation_id: str,
    ) -> str:
        normalized_library_id = str(library_id or '').strip()
        normalized_operation_id = str(operation_id or '').strip()
        if not normalized_library_id or not normalized_operation_id:
            return ''
        try:
            normalized_seq = int(accepted_seq)
        except (TypeError, ValueError):
            return ''
        if normalized_seq < 0:
            return ''
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            self._record_library_index_publish(success=False, error=str(exc))
            return ''
        if client is None:
            self._record_library_index_publish(success=False, error=self._last_error)
            return ''
        payload = {
            'library_id': normalized_library_id,
            'accepted_seq': normalized_seq,
            'operation_id': normalized_operation_id,
        }
        try:
            message_id = client.xadd(
                self.stream_key(_LIBRARY_INDEX_MUTATION_STREAM),
                {'payload': _json_dumps(payload)},
                maxlen=self.dirty_stream_maxlen(),
                approximate=True,
            )
            self._record_library_index_publish(success=True)
            return _redis_text(message_id)
        except Exception as exc:
            self._last_error = str(exc)
            self._record_library_index_publish(success=False, error=str(exc))
            logger.debug('[Redis] 发布库存索引 mutation wake hint 失败', exc_info=True)
            return ''

    @staticmethod
    def _append_stream_messages(
        messages: Iterable[Any],
        target: list[tuple[str, dict[str, Any]]],
    ) -> None:
        for message_id, fields in messages or []:
            normalized_fields = {
                _redis_text(key): (_redis_text(value) if isinstance(value, bytes) else value)
                for key, value in (fields.items() if isinstance(fields, dict) else [])
            }
            serialized = normalized_fields.get('payload')
            try:
                payload = _json_loads(serialized) if serialized is not None else dict(normalized_fields)
            except Exception:
                payload = dict(normalized_fields)
            if isinstance(payload, dict):
                target.append((_redis_text(message_id), payload))

    def _ensure_consumer_group_with_client_sync(
        self,
        client: Any,
        stream_name: str,
        group_name: str,
        *,
        start_id: str,
    ) -> None:
        try:
            client.xgroup_create(
                self.stream_key(stream_name),
                group_name,
                id=start_id,
                mkstream=True,
            )
        except Exception as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    def ensure_consumer_group_sync(
        self,
        stream_name: str,
        group_name: str,
        *,
        start_id: str = '0-0',
    ) -> bool:
        normalized_stream = str(stream_name or '').strip()
        normalized_group = str(group_name or '').strip()
        if not normalized_stream or not normalized_group:
            return False
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return False
        if client is None:
            return False
        try:
            self._ensure_consumer_group_with_client_sync(
                client,
                normalized_stream,
                normalized_group,
                start_id=str(start_id or '0-0'),
            )
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug(
                '[Redis] 创建 consumer group 失败 stream=%s group=%s',
                normalized_stream,
                normalized_group,
                exc_info=True,
            )
            return False

    def read_consumer_group_sync(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str = '',
        *,
        count: int = 100,
        block_ms: int = 1000,
        reclaim_idle_ms: int = 0,
        reclaim_cursor: str = '0-0',
    ) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
        normalized_stream = str(stream_name or '').strip()
        normalized_group = str(group_name or '').strip()
        normalized_consumer = str(consumer_name or '').strip() or f'{socket.gethostname()}-{os.getpid()}'
        current_cursor = _redis_text(reclaim_cursor or '0-0')
        if not normalized_stream or not normalized_group:
            return current_cursor, []
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return current_cursor, []
        if client is None:
            return current_cursor, []

        stream_key = self.stream_key(normalized_stream)
        safe_count = max(1, int(count or 100))
        result: list[tuple[str, dict[str, Any]]] = []
        try:
            self._ensure_consumer_group_with_client_sync(
                client,
                normalized_stream,
                normalized_group,
                start_id='0-0',
            )
            if reclaim_idle_ms > 0 and hasattr(client, 'xautoclaim'):
                claimed = client.xautoclaim(
                    stream_key,
                    normalized_group,
                    normalized_consumer,
                    int(reclaim_idle_ms),
                    start_id=current_cursor,
                    count=safe_count,
                )
                if isinstance(claimed, (list, tuple)) and claimed:
                    current_cursor = _redis_text(claimed[0] or '0-0')
                    claimed_messages = claimed[1] if len(claimed) > 1 else []
                    self._append_stream_messages(claimed_messages, result)

            remaining = safe_count - len(result)
            if remaining > 0:
                read_kwargs: dict[str, Any] = {'count': remaining}
                if int(block_ms or 0) > 0 and not result:
                    read_kwargs['block'] = int(block_ms)
                rows = client.xreadgroup(
                    normalized_group,
                    normalized_consumer,
                    {stream_key: '>'},
                    **read_kwargs,
                )
                for _key, messages in rows or []:
                    self._append_stream_messages(messages, result)
            return current_cursor, result
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug(
                '[Redis] 读取 consumer group 失败 stream=%s group=%s',
                normalized_stream,
                normalized_group,
                exc_info=True,
            )
            return current_cursor, []

    def ack_consumer_group_sync(
        self,
        stream_name: str,
        group_name: str,
        message_ids: Iterable[str],
    ) -> int:
        normalized_stream = str(stream_name or '').strip()
        normalized_group = str(group_name or '').strip()
        ids = [_redis_text(message_id) for message_id in message_ids or [] if _redis_text(message_id or '').strip()]
        if not normalized_stream or not normalized_group or not ids:
            return 0
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return 0
        if client is None:
            return 0
        try:
            return int(client.xack(self.stream_key(normalized_stream), normalized_group, *ids) or 0)
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug(
                '[Redis] ACK consumer group 失败 stream=%s group=%s',
                normalized_stream,
                normalized_group,
                exc_info=True,
            )
            return 0

    def read_library_index_mutation_hints_sync(
        self,
        consumer_name: str = '',
        *,
        count: int = 100,
        block_ms: int = 1000,
        reclaim_idle_ms: int = 60000,
        reclaim_cursor: str = '0-0',
    ) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
        return self.read_consumer_group_sync(
            _LIBRARY_INDEX_MUTATION_STREAM,
            _LIBRARY_INDEX_MUTATION_GROUP,
            consumer_name,
            count=count,
            block_ms=block_ms,
            reclaim_idle_ms=reclaim_idle_ms,
            reclaim_cursor=reclaim_cursor,
        )

    def ack_library_index_mutation_hints_sync(self, message_ids: Iterable[str]) -> int:
        return self.ack_consumer_group_sync(
            _LIBRARY_INDEX_MUTATION_STREAM,
            _LIBRARY_INDEX_MUTATION_GROUP,
            message_ids,
        )

    @staticmethod
    def _library_index_hint_identity(payload: Any) -> Optional[tuple[str, int, str]]:
        if not isinstance(payload, dict):
            return None
        library_id = str(payload.get('library_id') or '').strip()
        operation_id = str(payload.get('operation_id') or '').strip()
        try:
            accepted_seq = int(payload.get('accepted_seq'))
        except (TypeError, ValueError):
            return None
        if not library_id or not operation_id or accepted_seq <= 0:
            return None
        return library_id, accepted_seq, operation_id

    def ack_durable_library_index_mutation_hints_sync(
        self,
        hints: Iterable[tuple[str, dict[str, Any]]],
        *,
        materialized_seq_by_library: dict[str, int],
        retry_persisted_seqs: Iterable[tuple[str, int]] = (),
    ) -> dict[str, Any]:
        """只 ACK 已由 PostgreSQL 水位或 retry 状态覆盖的 wake hint。"""
        watermarks: dict[str, int] = {}
        for library_id, seq in (materialized_seq_by_library or {}).items():
            normalized_library_id = str(library_id or '').strip()
            if not normalized_library_id:
                continue
            try:
                watermarks[normalized_library_id] = max(0, int(seq or 0))
            except (TypeError, ValueError):
                continue
        durable_retries: set[tuple[str, int]] = set()
        for library_id, seq in retry_persisted_seqs or []:
            try:
                normalized = (str(library_id or '').strip(), int(seq))
            except (TypeError, ValueError):
                continue
            if normalized[0] and normalized[1] > 0:
                durable_retries.add(normalized)

        ack_message_ids: list[str] = []
        deferred_message_ids: list[str] = []
        invalid_message_ids: list[str] = []
        for message_id, payload in hints or []:
            normalized_message_id = _redis_text(message_id)
            identity = self._library_index_hint_identity(payload)
            if identity is None:
                invalid_message_ids.append(normalized_message_id)
                ack_message_ids.append(normalized_message_id)
                continue
            library_id, accepted_seq, _operation_id = identity
            if (
                int(watermarks.get(library_id, 0)) >= accepted_seq
                or (library_id, accepted_seq) in durable_retries
            ):
                ack_message_ids.append(normalized_message_id)
            else:
                deferred_message_ids.append(normalized_message_id)

        acked = self.ack_library_index_mutation_hints_sync(ack_message_ids)
        self._record_library_index_consumer_result(
            reads=len(ack_message_ids) + len(deferred_message_ids),
            acks=int(acked or 0),
            deferred=len(deferred_message_ids),
            invalid=len(invalid_message_ids),
        )
        return {
            'ack_requested': len(ack_message_ids),
            'acked': int(acked or 0),
            'ack_message_ids': ack_message_ids,
            'deferred_message_ids': deferred_message_ids,
            'invalid_message_ids': invalid_message_ids,
        }

    @staticmethod
    def _normalize_library_index_dirty_path(path: Any) -> str:
        normalized = str(path or '').strip().replace('\\', '/')
        return normalized.rstrip('/') or '/'

    def upsert_library_index_dirty_paths_sync(
        self,
        library_id: str,
        paths: Iterable[str],
        *,
        score_ms: Optional[float] = None,
    ) -> int:
        normalized_library_id = str(library_id or '').strip()
        normalized_paths = {
            self._normalize_library_index_dirty_path(path)
            for path in paths or []
            if path is not None
        }
        if not normalized_library_id or not normalized_paths:
            return 0
        score = float(score_ms if score_ms is not None else time.time() * 1000)
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return 0
        if client is None:
            return 0
        try:
            client.zadd(
                self.library_index_dirty_key(normalized_library_id),
                {path: score for path in normalized_paths},
            )
            return len(normalized_paths)
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 写入库存索引 watcher dirty ZSET 失败', exc_info=True)
            return 0

    def pop_library_index_dirty_paths_sync(
        self,
        library_id: str,
        *,
        count: int = 200,
        max_score_ms: Optional[float] = None,
    ) -> list[tuple[str, float]]:
        normalized_library_id = str(library_id or '').strip()
        if not normalized_library_id:
            return []
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return []
        if client is None:
            return []
        key = self.library_index_dirty_key(normalized_library_id)
        safe_count = max(1, int(count or 200))
        try:
            if max_score_ms is None and hasattr(client, 'zpopmin'):
                rows = client.zpopmin(key, safe_count) or []
                return [(_redis_text(path), float(score)) for path, score in rows]
            if max_score_ms is not None and hasattr(client, 'eval'):
                flat_rows = client.eval(
                    _POP_DUE_ZSET_SCRIPT,
                    1,
                    key,
                    float(max_score_ms),
                    safe_count,
                )
                result: list[tuple[str, float]] = []
                for index in range(0, len(flat_rows or []), 2):
                    if index + 1 >= len(flat_rows):
                        break
                    result.append((_redis_text(flat_rows[index]), float(flat_rows[index + 1])))
                return result

            if not hasattr(client, 'pipeline'):
                return []
            pipe = client.pipeline()
            try:
                for _attempt in range(3):
                    try:
                        pipe.watch(key)
                        if max_score_ms is None:
                            rows = pipe.zrange(key, 0, safe_count - 1, withscores=True) or []
                        else:
                            rows = pipe.zrangebyscore(
                                key,
                                '-inf',
                                float(max_score_ms),
                                start=0,
                                num=safe_count,
                                withscores=True,
                            ) or []
                        if not rows:
                            pipe.unwatch()
                            return []
                        members = [_redis_text(path) for path, _score in rows]
                        pipe.multi()
                        pipe.zrem(key, *members)
                        pipe.execute()
                        return [(path, float(score)) for (path, score), path in zip(rows, members)]
                    except Exception as exc:
                        if exc.__class__.__name__ != 'WatchError':
                            raise
                        pipe.reset()
                return []
            finally:
                pipe.reset()
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 弹出库存索引 watcher dirty ZSET 失败', exc_info=True)
            return []

    def read_library_index_dirty_paths_sync(
        self,
        library_id: str,
        *,
        count: int = 20000,
    ) -> list[tuple[str, float]]:
        normalized_library_id = str(library_id or '').strip()
        if not normalized_library_id:
            return []
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return []
        if client is None:
            return []
        try:
            rows = client.zrange(
                self.library_index_dirty_key(normalized_library_id),
                0,
                max(1, int(count or 20000)) - 1,
                withscores=True,
            ) or []
            return [(_redis_text(path), float(score)) for path, score in rows]
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 读取库存索引 watcher dirty ZSET 失败', exc_info=True)
            return []

    def remove_library_index_dirty_paths_sync(
        self,
        library_id: str,
        paths: Iterable[str],
        *,
        include_descendants: bool = True,
        max_score_ms: Optional[float] = None,
    ) -> int:
        normalized_library_id = str(library_id or '').strip()
        normalized_paths = sorted({
            self._normalize_library_index_dirty_path(path)
            for path in paths or []
            if path is not None
        })
        if not normalized_library_id or not normalized_paths:
            return 0
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            return 0
        if client is None:
            return 0
        key = self.library_index_dirty_key(normalized_library_id)
        try:
            if include_descendants:
                return int(client.eval(
                    _REMOVE_DIRTY_PATHS_SCRIPT,
                    1,
                    key,
                    _json_dumps(normalized_paths),
                    '' if max_score_ms is None else float(max_score_ms),
                ) or 0)
            return int(client.zrem(key, *normalized_paths) or 0)
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 清理库存索引 watcher dirty ZSET 失败', exc_info=True)
            return 0

    def library_index_dirty_diagnostics_sync(self, library_id: str) -> dict[str, Any]:
        normalized_library_id = str(library_id or '').strip()
        payload: dict[str, Any] = {
            'library_id': normalized_library_id,
            'pending_paths': 0,
            'oldest_score_ms': None,
            'newest_score_ms': None,
        }
        if not normalized_library_id:
            return payload
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            payload['error'] = str(exc)
            return payload
        if client is None:
            return payload
        key = self.library_index_dirty_key(normalized_library_id)
        try:
            payload['pending_paths'] = int(client.zcard(key) or 0)
            oldest = client.zrange(key, 0, 0, withscores=True) or []
            newest = client.zrevrange(key, 0, 0, withscores=True) or []
            payload['oldest_score_ms'] = float(oldest[0][1]) if oldest else None
            payload['newest_score_ms'] = float(newest[0][1]) if newest else None
        except Exception as exc:
            self._last_error = str(exc)
            payload['error'] = str(exc)
        return payload

    @staticmethod
    def _pending_count(value: Any) -> int:
        if isinstance(value, dict):
            pending = value.get('pending')
            if pending is None:
                pending = value.get(b'pending')
            return int(pending or 0)
        if isinstance(value, (list, tuple)) and value:
            return int(value[0] or 0)
        return 0

    @classmethod
    def _pending_summary(cls, value: Any) -> dict[str, Any]:
        summary: dict[str, Any] = {
            'pending': cls._pending_count(value),
            'min_id': None,
            'max_id': None,
            'consumers': [],
        }
        if not isinstance(value, dict):
            return summary
        minimum = value.get('min') if value.get('min') is not None else value.get(b'min')
        maximum = value.get('max') if value.get('max') is not None else value.get(b'max')
        summary['min_id'] = _redis_text(minimum) if minimum else None
        summary['max_id'] = _redis_text(maximum) if maximum else None
        consumers: list[dict[str, Any]] = []
        raw_consumers = value.get('consumers')
        if raw_consumers is None:
            raw_consumers = value.get(b'consumers')
        for item in raw_consumers or []:
            if not isinstance(item, dict):
                continue
            name = item.get('name') if item.get('name') is not None else item.get(b'name')
            pending = item.get('pending')
            if pending is None:
                pending = item.get(b'pending')
            consumers.append({
                'name': _redis_text(name or ''),
                'pending': int(pending or 0),
            })
        summary['consumers'] = consumers
        return summary

    def _library_index_channel_diagnostics_with_client(self, client: Any) -> dict[str, Any]:
        stream_key = self.stream_key(_LIBRARY_INDEX_MUTATION_STREAM)
        dirty_prefix = self.key(*_LIBRARY_INDEX_DIRTY_KEY_PARTS) + ':'
        payload: dict[str, Any] = {
            'available': False,
            'stream': {
                'name': _LIBRARY_INDEX_MUTATION_STREAM,
                'key': stream_key,
                'group': _LIBRARY_INDEX_MUTATION_GROUP,
                'group_state': {
                    'exists': False,
                    'consumers': 0,
                    'pending': 0,
                    'last_delivered_id': None,
                    'entries_read': None,
                    'lag': None,
                },
                'length': 0,
                'pending': 0,
                'pel': {
                    'pending': 0,
                    'min_id': None,
                    'max_id': None,
                    'consumers': [],
                },
            },
            'dirty': {
                'queue_count': 0,
                'pending_paths': 0,
                'oldest_score_ms': None,
                'queues': [],
            },
            'runtime': self._library_index_publish_runtime_diagnostics(),
        }
        if client is None:
            return payload

        try:
            payload['stream']['length'] = int(client.xlen(stream_key) or 0)
            payload['available'] = True
        except Exception:
            pass
        try:
            pending_info = client.xpending(stream_key, _LIBRARY_INDEX_MUTATION_GROUP)
            payload['stream']['pel'] = self._pending_summary(pending_info)
            payload['stream']['pending'] = payload['stream']['pel']['pending']
        except Exception:
            pass
        try:
            groups = client.xinfo_groups(stream_key) or []
            for group in groups:
                name = _redis_text(_redis_mapping_value(group, 'name', ''))
                if name != _LIBRARY_INDEX_MUTATION_GROUP:
                    continue
                payload['stream']['group_state'] = {
                    'exists': True,
                    'consumers': int(_redis_mapping_value(group, 'consumers', 0) or 0),
                    'pending': int(_redis_mapping_value(group, 'pending', 0) or 0),
                    'last_delivered_id': (
                        _redis_text(_redis_mapping_value(group, 'last-delivered-id'))
                        if _redis_mapping_value(group, 'last-delivered-id') is not None
                        else None
                    ),
                    'entries_read': (
                        int(_redis_mapping_value(group, 'entries-read'))
                        if _redis_mapping_value(group, 'entries-read') is not None
                        else None
                    ),
                    'lag': (
                        int(_redis_mapping_value(group, 'lag'))
                        if _redis_mapping_value(group, 'lag') is not None
                        else None
                    ),
                }
                break
        except Exception:
            pass

        try:
            keys = list(client.scan_iter(match=f'{dirty_prefix}*', count=200))[:1000]
        except Exception:
            keys = []
        queues: list[dict[str, Any]] = []
        total_pending = 0
        oldest_score: Optional[float] = None
        for raw_key in keys:
            key = _redis_text(raw_key)
            library_id = key[len(dirty_prefix):] if key.startswith(dirty_prefix) else key
            try:
                pending_paths = int(client.zcard(key) or 0)
                oldest = client.zrange(key, 0, 0, withscores=True) or []
                queue_oldest = float(oldest[0][1]) if oldest else None
            except Exception:
                continue
            total_pending += pending_paths
            if queue_oldest is not None:
                oldest_score = queue_oldest if oldest_score is None else min(oldest_score, queue_oldest)
            queues.append({
                'library_id': library_id,
                'pending_paths': pending_paths,
                'oldest_score_ms': queue_oldest,
            })
        payload['dirty'] = {
            'queue_count': len(queues),
            'pending_paths': total_pending,
            'oldest_score_ms': oldest_score,
            'queues': sorted(queues, key=lambda item: item['library_id']),
        }
        return payload

    def library_index_channel_diagnostics_sync(self) -> dict[str, Any]:
        try:
            client = self.client(required=False)
        except Exception as exc:
            self._last_error = str(exc)
            client = None
        return self._library_index_channel_diagnostics_with_client(client)

    def read_stream_payloads_sync(self, stream_name: str, *, last_id: str = '$', block_ms: int = 25000, count: int = 100) -> list[tuple[str, dict[str, Any]]]:
        client = self.client(required=False)
        if client is None:
            return []
        try:
            rows = client.xread({self.stream_key(stream_name): last_id}, count=max(1, int(count or 100)), block=max(0, int(block_ms or 0)))
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 读取 Stream 失败 stream=%s', stream_name, exc_info=True)
            return []
        result: list[tuple[str, dict[str, Any]]] = []
        for _key, messages in rows or []:
            for message_id, fields in messages or []:
                payload = _json_loads((fields or {}).get('payload')) or {}
                if isinstance(payload, dict):
                    result.append((str(message_id), payload))
        return result

    def write_bonus_probe_cache_dirty_sync(self, payloads: Iterable[dict[str, Any]]) -> int:
        values: list[tuple[str, dict[str, Any]]] = []
        for payload in payloads or []:
            if not isinstance(payload, dict):
                continue
            rjcode = str(payload.get('rjcode') or payload.get('workno') or '').strip().upper()
            if not rjcode:
                continue
            values.append((rjcode, {**payload, 'rjcode': rjcode, 'dirty_at': datetime.now().isoformat()}))
        if not values:
            return 0
        client = self.client(required=False)
        if client is None:
            return 0
        cache_ttl = self.runtime_ttl_seconds()
        try:
            pipe = client.pipeline(transaction=False) if hasattr(client, 'pipeline') else client
            for rjcode, payload in values:
                serialized = _json_dumps(payload)
                pipe.set(self.key('bonus-probe', 'cache', rjcode), serialized, ex=cache_ttl)
                pipe.xadd(
                    self.stream_key(_BONUS_PROBE_CACHE_STREAM),
                    {'rjcode': rjcode, 'payload': serialized},
                    maxlen=self.dirty_stream_maxlen(),
                    approximate=True,
                )
            if pipe is not client:
                pipe.execute()
            return len(values)
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 写入 DLsite 特典缓存 dirty buffer 失败', exc_info=True)
            return 0

    def read_bonus_probe_cache_rows_sync(self, rjcodes: Iterable[str]) -> dict[str, dict[str, Any]]:
        normalized: list[str] = []
        for rjcode in rjcodes or []:
            value = str(rjcode or '').strip().upper()
            if value and value not in normalized:
                normalized.append(value)
        if not normalized:
            return {}
        client = self.client(required=False)
        if client is None:
            return {}
        keys = [self.key('bonus-probe', 'cache', rjcode) for rjcode in normalized]
        try:
            if hasattr(client, 'mget'):
                raw_values = client.mget(keys)
            else:
                raw_values = [client.get(key) for key in keys]
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 读取 DLsite 特典缓存 overlay 失败', exc_info=True)
            return {}
        result: dict[str, dict[str, Any]] = {}
        for rjcode, raw in zip(normalized, raw_values or []):
            try:
                payload = _json_loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                result[rjcode] = payload
        return result

    def get_bonus_probe_cache_sync(self, rjcodes: Iterable[str]) -> dict[str, dict[str, Any]]:
        return self.read_bonus_probe_cache_rows_sync(rjcodes)

    def _ensure_bonus_probe_cache_group_sync(self, client: Any) -> None:
        try:
            client.xgroup_create(
                self.stream_key(_BONUS_PROBE_CACHE_STREAM),
                _BONUS_PROBE_CACHE_GROUP,
                id='0',
                mkstream=True,
            )
        except Exception as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    def read_bonus_probe_cache_dirty_sync(
        self,
        *,
        count: int = 500,
        block_ms: int = 1000,
        consumer: str = '',
        reclaim_idle_ms: int = 60000,
    ) -> list[tuple[str, dict[str, Any]]]:
        client = self.client(required=False)
        if client is None:
            return []
        stream_key = self.stream_key(_BONUS_PROBE_CACHE_STREAM)
        consumer_name = str(consumer or '').strip() or f'{socket.gethostname()}-{os.getpid()}'

        def append_messages(messages: Iterable[Any], target: list[tuple[str, dict[str, Any]]]) -> None:
            for message_id, fields in messages or []:
                fields = fields or {}
                payload = None
                if isinstance(fields, dict):
                    payload = fields.get('payload')
                try:
                    data = _json_loads(payload) if payload is not None else dict(fields)
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    target.append((str(message_id), data))

        try:
            self._ensure_bonus_probe_cache_group_sync(client)
            result: list[tuple[str, dict[str, Any]]] = []
            if reclaim_idle_ms > 0 and hasattr(client, 'xautoclaim'):
                claimed = client.xautoclaim(
                    stream_key,
                    _BONUS_PROBE_CACHE_GROUP,
                    consumer_name,
                    int(reclaim_idle_ms),
                    start_id='0-0',
                    count=max(1, int(count or 500)),
                )
                claimed_messages = claimed[1] if isinstance(claimed, (list, tuple)) and len(claimed) > 1 else []
                append_messages(claimed_messages, result)
                if result:
                    return result
            rows = client.xreadgroup(
                _BONUS_PROBE_CACHE_GROUP,
                consumer_name,
                {stream_key: '>'},
                count=max(1, int(count or 500)),
                block=max(0, int(block_ms or 0)),
            )
            for _key, messages in rows or []:
                append_messages(messages, result)
            return result
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] 读取 DLsite 特典缓存 dirty buffer 失败', exc_info=True)
            return []

    def ack_bonus_probe_cache_dirty_sync(self, message_ids: Iterable[str]) -> int:
        ids = [str(message_id) for message_id in message_ids or [] if str(message_id or '').strip()]
        if not ids:
            return 0
        client = self.client(required=False)
        if client is None:
            return 0
        try:
            return int(client.xack(self.stream_key(_BONUS_PROBE_CACHE_STREAM), _BONUS_PROBE_CACHE_GROUP, *ids) or 0)
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug('[Redis] ACK DLsite 特典缓存 dirty buffer 失败', exc_info=True)
            return 0

    def dirty_stream_maxlen(self) -> int:
        return int(self._config()['dirty_stream_maxlen'])

    def short_cache_ttl_seconds(self) -> int:
        return int(self._config()['short_cache_ttl'])

    def runtime_ttl_seconds(self) -> int:
        return int(self._config()['runtime_ttl'])

    def diagnostics(self) -> dict[str, Any]:
        cfg = self._config()
        runtime_cfg = self._runtime_buffer_config()
        available = self.ping() if cfg['enabled'] else False
        payload: dict[str, Any] = {
            'enabled': bool(cfg['enabled']),
            'required': bool(cfg['required']),
            'available': bool(available),
            'url_masked': self.masked_url(),
            'namespace': cfg['namespace'],
            'environment': cfg['environment'],
            'latency_ms': round(self._last_ping_latency_ms, 2) if self._last_ping_latency_ms is not None else None,
            'last_error': self._last_error,
            'streams': {},
            'keys': {},
            'memory': {},
            'runtime_buffer': {
                **runtime_cfg,
                'active_backend': 'redis' if runtime_cfg['backend'] == 'redis' and available else ('memory' if runtime_cfg['enabled'] else 'disabled'),
                'memory_fallback': self._memory_status(),
            },
            'library_index_channel': self._library_index_channel_diagnostics_with_client(None),
            'generated_at': datetime.now().isoformat(),
        }
        client = self.client(required=False) if cfg['enabled'] else None
        if client is None or not available:
            return payload

        def xlen(name: str) -> int:
            try:
                return int(client.xlen(self.stream_key(name)) or 0)
            except Exception:
                return 0

        def pending(name: str, group: str) -> int:
            try:
                info = client.xpending(self.stream_key(name), group)
                if isinstance(info, dict):
                    return int(info.get('pending') or 0)
            except Exception:
                return 0
            return 0

        def count_keys(pattern_parts: Iterable[Any]) -> int:
            pattern = self.key(*pattern_parts) + '*'
            count = 0
            try:
                for _ in client.scan_iter(match=pattern, count=500):
                    count += 1
                    if count >= 10000:
                        break
            except Exception:
                return count
            return count

        payload['streams'] = {
            'events': {'length': xlen('events:stream')},
            'task_center': {'length': xlen('task-center:stream')},
            'bonus_probe_cache': {
                'length': xlen('bonus-probe:cache:stream'),
                'pending': pending('bonus-probe:cache:stream', 'bonus-probe-cache-writers'),
            },
        }
        payload['library_index_channel'] = self._library_index_channel_diagnostics_with_client(client)
        payload['keys'] = {
            'task_runtime': count_keys(['task', 'runtime']),
            'bonus_probe_cache': count_keys(['bonus-probe', 'cache']),
            'bonus_probe_jobs': count_keys(['bonus-probe', 'job']),
            'bonus_probe_dirty_sets': count_keys(['bonus-probe', 'task-dirty']),
            'circle_completion_state': count_keys(['circle-completion', 'state']),
            'circle_completion_summary': count_keys(['circle-completion', 'summary']),
            'circle_completion_page': count_keys(['circle-completion', 'page']),
            'circle_completion_codes': count_keys(['circle-completion', 'work-codes']),
            'circle_completion_bonus_codes': count_keys(['circle-completion', 'bonus-work-codes']),
            'circle_completion_recent': count_keys(['circle-completion', 'recent']),
            'circle_completion_aliases': count_keys(['circle-completion', 'aliases']),
            'circle_completion_versions': count_keys(['circle-completion', 'version']),
            'circle_completion_build_locks': count_keys(['circle-completion', 'build_lock']),
        }
        try:
            memory = client.info('memory')
            payload['memory'] = {
                'used_memory': memory.get('used_memory'),
                'used_memory_human': memory.get('used_memory_human'),
                'maxmemory_human': memory.get('maxmemory_human'),
            }
        except Exception:
            payload['memory'] = {}
        return payload

    def runtime_buffer_status(self) -> dict[str, Any]:
        diagnostics = self.diagnostics()
        return {
            'redis': {
                'enabled': diagnostics.get('enabled'),
                'required': diagnostics.get('required'),
                'available': diagnostics.get('available'),
                'url_masked': diagnostics.get('url_masked'),
                'latency_ms': diagnostics.get('latency_ms'),
                'last_error': diagnostics.get('last_error'),
                'streams': diagnostics.get('streams') or {},
                'keys': diagnostics.get('keys') or {},
                'library_index_channel': diagnostics.get('library_index_channel') or {},
            },
            'runtime_buffer': diagnostics.get('runtime_buffer') or {},
            'library_index_channel': diagnostics.get('library_index_channel') or {},
            'generated_at': datetime.now().isoformat(),
        }

    def close(self) -> None:
        with self._client_lock:
            client = self._client
            self._client = None
            self._client_signature = None
        try:
            if client is not None:
                client.close()
        except Exception:
            pass


_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
