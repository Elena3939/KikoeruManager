import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_subscribers: dict[int, tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = {}
_subscribers_lock = threading.Lock()
_subscriber_counter = 0

_last_emit_by_task: dict[str, tuple[float, tuple[Any, ...]]] = {}
_last_emit_lock = threading.Lock()
_THROTTLE_SECONDS = 0.5
_IMMEDIATE_REASONS = frozenset({
    "submitted",
    "started",
    "status",
    "completed",
    "failed",
    "cancelled",
    "cleanup",
    "filtered_item_restored",
    "connected",
})


def sse_subscribe(loop: asyncio.AbstractEventLoop):
    """注册任务中心 SSE 客户端，返回 (sid, queue)。"""
    global _subscriber_counter
    queue: asyncio.Queue = asyncio.Queue(maxsize=60)
    with _subscribers_lock:
        _subscriber_counter += 1
        sid = _subscriber_counter
        _subscribers[sid] = (queue, loop)
    return sid, queue


def sse_unsubscribe(sid: int) -> None:
    with _subscribers_lock:
        _subscribers.pop(sid, None)


def _task_status(task) -> str:
    status = getattr(task, "status", "")
    return status.value if hasattr(status, "value") else str(status or "")


def _task_domain(task) -> str:
    metadata = dict(getattr(task, "task_metadata", None) or {})
    domain = str(metadata.get("task_domain") or "").strip()
    if domain:
        return domain
    task_type = getattr(getattr(task, "type", None), "value", str(getattr(task, "type", "") or ""))
    mapping = {
        "auto_process": "import",
        "process_existing_folder": "existing_folder",
        "rj_subtitle_fetch": "rj_subtitle",
        "asmr_sync_download": "asmr_sync",
        "library_folder_completion_preview": "asmr_sync",
        "http_download": "http_download",
        "baidu_netdisk_download": "baidu_netdisk",
        "baidu_netdisk_upload": "baidu_netdisk",
        "local_library_upload": "upload",
        "circle_completion_index": "circle_completion",
        "circle_completion_refresh_selected": "circle_completion",
        "circle_completion_download_batch": "circle_completion",
    }
    return mapping.get(task_type, "system")


def build_task_center_event(task, reason: str = "progress") -> dict[str, Any]:
    task_id = str(getattr(task, "id", "") or "")
    now = datetime.now().isoformat()
    metadata = dict(getattr(task, "task_metadata", None) or {})
    event = {
        "type": "task_center_changed",
        "reason": str(reason or "progress"),
        "item_id": f"engine:{task_id}" if task_id else "",
        "engine_task_id": task_id,
        "domain": _task_domain(task),
        "status": _task_status(task),
        "progress": int(getattr(task, "progress", 0) or 0),
        "current_step": str(getattr(task, "current_step", "") or ""),
        "updated_at": now,
    }
    bonus_probe_meta = metadata.get("bonus_probe_meta")
    if isinstance(bonus_probe_meta, dict):
        event["bonus_probe_meta"] = {
            key: bonus_probe_meta.get(key)
            for key in (
                "release_date",
                "batch_index",
                "batch_total",
                "worker_index",
                "worker_total",
                "current_probe_checked_count",
                "current_probe_total_count",
                "checked_probe_count",
                "probe_count",
            )
            if key in bonus_probe_meta
        }
    return event


def _should_emit(event: dict[str, Any]) -> bool:
    task_id = str(event.get("engine_task_id") or "")
    reason = str(event.get("reason") or "progress")
    if not task_id or reason in _IMMEDIATE_REASONS:
        return True

    signature = (
        event.get("status"),
        event.get("progress"),
        event.get("current_step"),
    )
    now = time.monotonic()
    with _last_emit_lock:
        last_at, last_signature = _last_emit_by_task.get(task_id, (0.0, None))
        if signature == last_signature and now - last_at < _THROTTLE_SECONDS:
            return False
        if now - last_at < _THROTTLE_SECONDS and signature[0] == (last_signature or (None,))[0]:
            return False
        _last_emit_by_task[task_id] = (now, signature)
    return True


def _broadcast_realtime_event(event: dict[str, Any]) -> None:
    try:
        from .realtime_event_service import broadcast_event as broadcast_realtime_event

        event_type = str(event.get("type") or "")
        if event_type == "task_center_changed":
            broadcast_realtime_event({
                "type": "task.center.changed",
                "reason": event.get("reason") or "progress",
                "id": event.get("item_id") or event.get("engine_task_id") or "",
                "domain": event.get("domain") or "",
                "status": event.get("status") or "",
                "progress": int(event.get("progress") or 0),
                "current_step": event.get("current_step") or "",
                "updated_at": event.get("updated_at") or datetime.now().isoformat(),
                "payload": dict(event),
            })
            return

        if event_type == "processed_archive_changed":
            broadcast_realtime_event({
                "type": "processed_archive.changed",
                "reason": event.get("reason") or "archive_changed",
                "id": event.get("archive_id") or "",
                "domain": "processed_archive",
                "status": event.get("status") or "",
                "updated_at": event.get("updated_at") or datetime.now().isoformat(),
                "payload": dict(event),
            })
            return

        if event_type == "library_index_status_changed":
            broadcast_realtime_event({
                "type": "library.index.status.changed",
                "reason": event.get("reason") or "library_index_status",
                "id": event.get("library_id") or "",
                "domain": "library_index",
                "status": event.get("status") or "",
                "updated_at": event.get("updated_at") or datetime.now().isoformat(),
                "payload": dict(event),
            })
    except Exception:
        logger.debug("桥接统一实时事件失败", exc_info=True)


def _write_task_center_event_to_redis(event: dict[str, Any]) -> None:
    try:
        from .redis_service import get_redis_service

        get_redis_service().append_stream_payload_sync('task-center:stream', dict(event), required=False)
    except Exception:
        logger.debug("[Redis] 写入任务中心事件流失败", exc_info=True)


def broadcast_event(event: dict[str, Any]) -> None:
    if not event or not _should_emit(event):
        return
    _write_task_center_event_to_redis(event)
    _broadcast_realtime_event(event)
    with _subscribers_lock:
        subscribers = list(_subscribers.values())
    if not subscribers:
        return

    def _safe_put(queue: asyncio.Queue, payload: dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.debug("任务中心 SSE 客户端队列已满，跳过一次事件")

    for queue, loop in subscribers:
        try:
            loop.call_soon_threadsafe(_safe_put, queue, event)
        except Exception:
            logger.debug("任务中心 SSE 广播失败", exc_info=True)


def broadcast_task_center_changed(task, reason: str = "progress") -> None:
    try:
        broadcast_event(build_task_center_event(task, reason=reason))
    except Exception:
        logger.debug("构建任务中心 SSE 事件失败", exc_info=True)


async def broadcast_task_center_changed_async(task, reason: str = "progress") -> None:
    broadcast_task_center_changed(task, reason=reason)


def broadcast_processed_archive_changed(archive, reason: str = "archive_changed") -> None:
    """广播已处理归档记录变化，复用任务中心 SSE 通道驱动概览刷新。"""
    try:
        broadcast_event({
            "type": "processed_archive_changed",
            "reason": str(reason or "archive_changed"),
            "archive_id": str(getattr(archive, "id", "") or ""),
            "filename": str(getattr(archive, "filename", "") or ""),
            "status": str(getattr(archive, "status", "") or ""),
            "processed_at": getattr(getattr(archive, "processed_at", None), "isoformat", lambda: "")(),
            "updated_at": datetime.now().isoformat(),
        })
    except Exception:
        logger.debug("构建归档 SSE 事件失败", exc_info=True)


def broadcast_library_index_status_changed(status, reason: str = "library_index_status") -> None:
    """广播库存索引状态变化，驱动库存页统计快照实时更新。"""
    try:
        if status is None:
            return
        if hasattr(status, "to_dict"):
            snapshot = dict(status.to_dict() or {})
        else:
            accepted_seq = int(getattr(status, "accepted_seq", 0) or 0)
            materialized_seq = int(getattr(status, "materialized_seq", 0) or 0)
            snapshot = {
                "library_id": str(getattr(status, "library_id", "") or ""),
                "status": str(getattr(status, "status", "") or ""),
                "watcher_mode": getattr(status, "watcher_mode", None),
                "total_entries": int(getattr(status, "total_entries", 0) or 0),
                "total_size_bytes": int(getattr(status, "total_size_bytes", 0) or 0),
                "folder_count": int(getattr(status, "folder_count", 0) or 0),
                "last_full_scan_at": getattr(status, "last_full_scan_at", None),
                "last_event_at": getattr(status, "last_event_at", None),
                "accepted_seq": accepted_seq,
                "materialized_seq": materialized_seq,
                "pending_events": max(accepted_seq - materialized_seq, 0),
                "state_revision": int(getattr(status, "state_revision", 0) or 0),
                "view_revision": int(getattr(status, "view_revision", 0) or 0),
                "active_generation": int(getattr(status, "active_generation", 1) or 1),
                "building_generation": getattr(status, "building_generation", None),
                "catchup_state": str(getattr(status, "catchup_state", "idle") or "idle"),
                "last_operation_id": getattr(status, "last_operation_id", None),
                "materializer_owner": getattr(status, "materializer_owner", None),
                "materializer_lease_until": getattr(status, "materializer_lease_until", None),
                "materializer_epoch": int(getattr(status, "materializer_epoch", 0) or 0),
                "blocked_seq": getattr(status, "blocked_seq", None),
                "catchup_error": getattr(status, "catchup_error", None),
                "error": getattr(status, "error", None),
                "updated_at": int(getattr(status, "updated_at", 0) or 0),
            }
        broadcast_event({
            "type": "library_index_status_changed",
            "reason": str(reason or "library_index_status"),
            **snapshot,
        })
    except Exception:
        logger.debug("构建库存索引 SSE 事件失败", exc_info=True)
