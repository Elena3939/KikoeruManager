import asyncio
import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_subscribers: dict[int, tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = {}
_subscribers_lock = threading.Lock()
_subscriber_counter = 0


def _now_iso() -> str:
    return datetime.now().isoformat()


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    updated_at = str(event.get("updated_at") or payload.get("updated_at") or _now_iso())
    event_type = str(event.get("type") or "").strip()
    return {
        "type": event_type,
        "reason": str(event.get("reason") or payload.get("reason") or ""),
        "id": str(event.get("id") or payload.get("id") or ""),
        "domain": str(event.get("domain") or payload.get("domain") or ""),
        "status": str(event.get("status") or payload.get("status") or ""),
        "progress": int(event.get("progress") or payload.get("progress") or 0),
        "current_step": str(event.get("current_step") or payload.get("current_step") or ""),
        "updated_at": updated_at,
        "payload": payload,
    }


def sse_subscribe(loop: asyncio.AbstractEventLoop):
    global _subscriber_counter
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _subscribers_lock:
        _subscriber_counter += 1
        sid = _subscriber_counter
        _subscribers[sid] = (queue, loop)
    return sid, queue


def sse_unsubscribe(sid: int) -> None:
    with _subscribers_lock:
        _subscribers.pop(sid, None)


def broadcast_event(event: dict[str, Any]) -> None:
    if not event:
        return
    try:
        payload = normalize_event(event)
        if not payload["type"]:
            return
    except Exception:
        logger.debug("实时事件标准化失败", exc_info=True)
        return

    with _subscribers_lock:
        subscribers = list(_subscribers.values())
    if not subscribers:
        return

    def _safe_put(queue: asyncio.Queue, next_event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(next_event)
            return
        except asyncio.QueueFull:
            pass
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(next_event)
        except asyncio.QueueFull:
            logger.debug("实时事件客户端队列已满，跳过事件: %s", next_event.get("type"))

    for queue, loop in subscribers:
        try:
            loop.call_soon_threadsafe(_safe_put, queue, payload)
        except Exception:
            logger.debug("实时事件广播失败", exc_info=True)
