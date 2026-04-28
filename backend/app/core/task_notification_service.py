import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────
# SSE 广播机制（线程安全，支持多客户端）
# ────────────────────────────────────────────────────────
_sse_subscribers: dict = {}   # sid -> (asyncio.Queue, asyncio.AbstractEventLoop)
_sse_lock = threading.Lock()
_sse_counter = 0


def sse_subscribe(loop: asyncio.AbstractEventLoop):
    """注册 SSE 客户端，返回 (sid, queue)"""
    global _sse_counter
    q: asyncio.Queue = asyncio.Queue(maxsize=30)
    with _sse_lock:
        _sse_counter += 1
        sid = _sse_counter
        _sse_subscribers[sid] = (q, loop)
    return sid, q


def sse_unsubscribe(sid: int) -> None:
    with _sse_lock:
        _sse_subscribers.pop(sid, None)


def _sse_broadcast(event: dict) -> None:
    """从任意线程安全地推送事件到所有已连接 SSE 客户端"""
    with _sse_lock:
        subs = list(_sse_subscribers.values())
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception:
            pass

_NON_TERMINAL = frozenset({'pending', 'processing', 'paused', 'waiting_retry'})


def _task_status(task) -> str:
    return (task.status.value if hasattr(task.status, 'value') else str(task.status)).lower()


def _resolve_group_key(task) -> tuple:
    """确定聚合键和类型，优先级：显式 > parent_session > batch > 单任务

    注意：task_center 的 session_id 是执行会话，会被长期复用挂多批任务，
    不能当作通知聚合键，否则会导致组终态条件永远不满足、inbox 永远不写。
    需要批量聚合的入口必须显式写入 notification_group_key/batch_id/parent_session_id。
    """
    meta = dict(task.task_metadata or {})
    if meta.get('notification_group_key'):
        return str(meta['notification_group_key']), 'explicit'
    if meta.get('parent_session_id'):
        return str(meta['parent_session_id']), 'parent_session'
    if meta.get('batch_id'):
        return str(meta['batch_id']), 'batch'
    return str(task.id), 'task'


def _resolve_group_run_id(task, meta: dict) -> str:
    """确定本次运行 ID，支持重跑后重新通知"""
    if meta.get('batch_id'):
        return str(meta['batch_id'])[:40]
    if task.started_at:
        return task.started_at.strftime('%Y%m%d%H%M')
    return task.id[:12]


def _is_group_terminal(group_key: str, group_type: str, current_task_id: str) -> bool:
    """检查聚合组内所有其他任务是否都已结束"""
    if group_type == 'task':
        return True
    try:
        from .task_engine import get_task_engine
        engine = get_task_engine()
        for tid, t in list(engine.tasks.items()):
            if tid == current_task_id:
                continue
            t_group_key, _ = _resolve_group_key(t)
            if t_group_key != group_key:
                continue
            if _task_status(t) in _NON_TERMINAL:
                return False
    except Exception:
        pass
    return True


def _final_event_type(group_key: str, group_type: str, current_task) -> str:
    """聚合组结束后综合判断最终事件类型"""
    if group_type == 'task':
        status = _task_status(current_task)
        if status in ('failed', 'cancelled'):
            return 'failed'
        if status == 'waiting_manual':
            return 'waiting_manual'
        return 'completed'
    has_failed = False
    has_waiting_manual = False
    try:
        from .task_engine import get_task_engine
        engine = get_task_engine()
        for t in list(engine.tasks.values()):
            t_group_key, _ = _resolve_group_key(t)
            if t_group_key != group_key:
                continue
            st = _task_status(t)
            if st in ('failed', 'cancelled'):
                has_failed = True
            elif st == 'waiting_manual':
                has_waiting_manual = True
    except Exception:
        pass
    if has_failed:
        return 'failed'
    if has_waiting_manual:
        return 'waiting_manual'
    return 'completed'


def _build_notification_info(event_type: str, group_key: str, group_type: str, current_task) -> dict:
    """构建通知摘要和路由信息"""
    try:
        from .task_center_service import TaskCenterService
        tcs = TaskCenterService()
        serialized = tcs._serialize_engine_task(current_task)
        domain = serialized.get('domain', 'task')
        domain_label = serialized.get('domain_label') or tcs.DOMAIN_LABELS.get(domain, domain)
        title = serialized.get('title') or serialized.get('source_label') or current_task.id[:8]
        rjcode = serialized.get('rjcode', '')
        route_hint = serialized.get('route_hint') or {}
    except Exception:
        domain = 'task'
        domain_label = '任务'
        title = current_task.id[:8]
        rjcode = ''
        route_hint = {}

    # route_hint 在不同 domain 序列化下可能是 str / None / dict，统一兜底成 dict
    if not isinstance(route_hint, dict):
        route_hint = {'path': str(route_hint)} if route_hint else {}

    severity_map = {'completed': 'success', 'failed': 'danger', 'waiting_manual': 'warning'}
    label_map = {'completed': '已完成', 'failed': '执行失败', 'waiting_manual': '等待处理'}

    if group_type != 'task':
        try:
            from .task_engine import get_task_engine
            engine = get_task_engine()
            group_tasks = [t for t in engine.tasks.values() if _resolve_group_key(t)[0] == group_key]
            total = len(group_tasks)
            failed = sum(1 for t in group_tasks if _task_status(t) in ('failed', 'cancelled'))
            if event_type == 'failed':
                summary = f'{domain_label}批量任务结束，{failed}/{total} 个失败'
            elif event_type == 'waiting_manual':
                summary = f'{domain_label}批量任务等待人工处理，共 {total} 个'
            else:
                summary = f'{domain_label}批量任务完成，共 {total} 个'
        except Exception:
            summary = f'{domain_label}{label_map.get(event_type, event_type)}'
    else:
        summary = f'{domain_label}{label_map.get(event_type, event_type)}'

    meta = dict(current_task.task_metadata or {})
    return {
        'title': title,
        'summary': summary,
        'severity': severity_map.get(event_type, 'info'),
        'domain': domain,
        'domain_label': domain_label,
        'rjcode': rjcode,
        'source_page': meta.get('source_page', ''),
        'source_action': meta.get('source_action', ''),
        'source_label': meta.get('source_label', ''),
        'business_key': str(meta.get('business_key') or ''),
        'route_path': route_hint.get('path', ''),
        'route_query': route_hint.get('query') or {},
        'task_kind': (current_task.type.value if hasattr(current_task.type, 'value') else str(current_task.type)),
    }


async def enqueue_notification_check(task) -> None:
    """任务状态变化后的轻量通知入口（从任务引擎 finally 调用）"""
    try:
        await _check_and_write(task)
    except Exception:
        logger.warning("[通知] 通知处理异常", exc_info=True)


async def _check_and_write(task) -> None:
    status = _task_status(task)
    tid = getattr(task, 'id', '?')
    if status not in ('completed', 'failed', 'cancelled', 'waiting_manual'):
        logger.debug(f"[通知] 跳过 task={tid} status={status} 不在通知白名单")
        return

    meta = dict(task.task_metadata or {})
    if meta.get('notification_suppress'):
        logger.info(f"[通知] 跳过 task={tid} 显式 notification_suppress=True")
        return

    from ..config.settings import get_config
    cfg = get_config()
    if not cfg.notification_center.enabled:
        logger.info(f"[通知] 跳过 task={tid} notification_center.enabled=False")
        return

    group_key, group_type = _resolve_group_key(task)
    group_run_id = _resolve_group_run_id(task, meta)
    logger.info(
        f"[通知] 处理 task={tid} status={status} group_type={group_type} group_key={group_key[:32]}"
    )

    if status == 'waiting_manual':
        event_key = f"waiting_manual:{group_key}:{group_run_id}"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_sync, event_key, 'waiting_manual', task, group_key, group_type, group_run_id)
        return

    # cancelled 仅当用户开启 send_on_cancelled 时才写邮件 outbox，
    # 但站内通知（inbox）始终落库，避免铃铛漏报
    if not _is_group_terminal(group_key, group_type, task.id):
        logger.info(f"[通知] 跳过 task={tid} group 尚未全部终态 group_key={group_key[:32]}")
        return

    evt = _final_event_type(group_key, group_type, task)
    event_key = f"{evt}:{group_key}:{group_run_id}"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_sync, event_key, evt, task, group_key, group_type, group_run_id)


def _write_sync(event_key: str, event_type: str, task, group_key: str, group_type: str, group_run_id: str) -> None:
    from ..models.database import SessionLocal, NotificationInboxItem, NotificationOutbox
    from ..config.settings import get_config
    db = SessionLocal()
    try:
        if db.query(NotificationInboxItem).filter(NotificationInboxItem.event_key == event_key).first():
            return

        info = _build_notification_info(event_type, group_key, group_type, task)
        meta = dict(task.task_metadata or {})
        now = datetime.now()
        item_id = str(uuid.uuid4())

        task_ids = [task.id]
        try:
            from .task_engine import get_task_engine
            engine = get_task_engine()
            for t in list(engine.tasks.values()):
                if t.id != task.id and _resolve_group_key(t)[0] == group_key:
                    task_ids.append(t.id)
        except Exception:
            pass

        inbox = NotificationInboxItem(
            id=item_id,
            event_key=event_key,
            event_type=event_type,
            severity=info['severity'],
            group_key=group_key,
            group_type=group_type,
            group_run_id=group_run_id,
            primary_task_id=task.id,
            task_ids=task_ids,
            session_id=str(task.session_id or ''),
            parent_session_id=str(meta.get('parent_session_id') or ''),
            batch_id=str(meta.get('batch_id') or ''),
            task_domain=info['domain'],
            task_kind=info['task_kind'],
            source_page=info['source_page'],
            source_action=info['source_action'],
            source_label=info['source_label'],
            business_key=info['business_key'],
            title=info['title'],
            summary=info['summary'],
            rjcode=info['rjcode'],
            route_path=info['route_path'],
            route_query=info['route_query'],
            is_read=False,
            created_at=now,
            updated_at=now,
        )
        db.add(inbox)

        cfg = get_config().notification_email
        # domain 过滤：enabled_domains 非空时仅发清单内的 domain
        domain_allowed = (
            not cfg.enabled_domains
            or info['domain'] in cfg.enabled_domains
        )
        should_email = (
            cfg.enabled and cfg.to_email and cfg.smtp_host and domain_allowed and (
                (event_type == 'completed' and cfg.send_on_completed) or
                (event_type == 'failed' and cfg.send_on_failed) or
                (event_type == 'waiting_manual' and cfg.send_on_waiting_manual)
            )
        )
        if cfg.enabled and not domain_allowed:
            logger.info(
                f"[通知] 跳过邮件 event_key={event_key} domain={info['domain']} 不在 enabled_domains"
            )
        if should_email:
            try:
                from .notification_helper import build_notification_extra_for_task
                auto_extra = build_notification_extra_for_task(task)
            except Exception:
                logger.warning("[通知] 构建邮件业务块失败 task=%s", getattr(task, "id", "?"), exc_info=True)
                auto_extra = {}
            extra = {
                **(auto_extra if isinstance(auto_extra, dict) else {}),
                **(meta.get('notification_extra') or {}),
            }
            if not isinstance(extra, dict):
                extra = {}
            outbox = NotificationOutbox(
                id=str(uuid.uuid4()),
                inbox_item_id=item_id,
                event_key=event_key,
                channel='email',
                status='pending',
                attempt_count=0,
                payload={
                    'event_type': event_type,
                    'title': info['title'],
                    'summary': info['summary'],
                    'domain': info['domain'],
                    'domain_label': info['domain_label'],
                    'rjcode': info['rjcode'],
                    'source_label': info['source_label'],
                    'task_ids': task_ids,
                    'group_type': group_type,
                    'severity': info['severity'],
                    **extra,
                },
                created_at=now,
            )
            db.add(outbox)

        db.commit()
        logger.info(f"[通知] 写入通知 event_key={event_key}")
        # SSE 实时推送
        try:
            unread_n = db.query(NotificationInboxItem).filter(NotificationInboxItem.is_read.is_(False)).count()
            _sse_broadcast({
                'type': 'new_notification',
                'unread_count': unread_n,
                'item': inbox.to_dict(),
            })
        except Exception:
            pass
    except Exception:
        db.rollback()
        logger.error("[通知] 写入通知失败", exc_info=True)
    finally:
        db.close()


async def start_outbox_worker() -> None:
    """后台 outbox 邮件发送 worker，在应用启动时作为 asyncio 任务运行"""
    logger.info("[通知] outbox worker 启动")
    # 回收上一次进程被旧 bug 卡死的 sending 记录，重新排队发送
    try:
        from ..models.database import SessionLocal, NotificationOutbox
        db = SessionLocal()
        try:
            stuck = db.query(NotificationOutbox).filter(NotificationOutbox.status == 'sending').all()
            for s in stuck:
                s.status = 'pending'
                s.next_retry_at = None
            if stuck:
                logger.info(f"[通知] outbox 启动时回收卡死 sending 记录 {len(stuck)} 条")
            template_failed = (
                db.query(NotificationOutbox)
                .filter(
                    NotificationOutbox.status == 'failed',
                    NotificationOutbox.last_error.in_(["'任务类型'", "'任务标题'"]),
                )
                .all()
            )
            for s in template_failed:
                s.status = 'pending'
                s.attempt_count = 0
                s.next_retry_at = None
                s.last_error = None
            if template_failed:
                logger.info(f"[通知] outbox 启动时恢复模板变量失败记录 {len(template_failed)} 条")
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.warning("[通知] outbox 启动回收失败", exc_info=True)
    while True:
        try:
            await _process_outbox_once()
        except Exception:
            logger.warning("[通知] outbox worker 异常", exc_info=True)
        await asyncio.sleep(30)


async def _process_outbox_once() -> None:
    from ..models.database import SessionLocal, NotificationOutbox
    from ..config.settings import get_config
    from .notification_email_service import send_notification_email
    from .notification_template_service import render_email_for_outbox

    cfg = get_config().notification_email
    if not cfg.enabled:
        return

    now = datetime.now()
    db = SessionLocal()
    # 提交前把需要的字段拷成纯 Python 数据，避免 close() 后访问 detached 实例
    pending_snapshots: list[dict] = []
    try:
        pending_items = (
            db.query(NotificationOutbox)
            .filter(
                NotificationOutbox.status == 'pending',
                (NotificationOutbox.next_retry_at == None) | (NotificationOutbox.next_retry_at <= now),
            )
            .limit(5)
            .all()
        )
        for item in pending_items:
            item.status = 'sending'
            item.attempt_count = (item.attempt_count or 0) + 1
            pending_snapshots.append({
                'id': item.id,
                'payload': dict(item.payload) if item.payload else {},
            })
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("[通知] outbox 标记 sending 失败", exc_info=True)
        return
    finally:
        db.close()

    if not pending_snapshots:
        return

    logger.info(f"[通知] outbox 准备发送 {len(pending_snapshots)} 封邮件")
    for snap in pending_snapshots:
        item_id = snap['id']
        try:
            subject, html_body, text_body = render_email_for_outbox(snap['payload'])
            ok = await send_notification_email(subject, html_body, text_body)
            _update_outbox_status(item_id, ok, cfg, error='' if ok else '发送失败')
            logger.info(f"[通知] outbox 发送结果 id={item_id} ok={ok}")
        except Exception as e:
            logger.error(f"[通知] outbox 发送异常 id={item_id}: {e}", exc_info=True)
            _update_outbox_status(item_id, False, cfg, error=str(e))


def _update_outbox_status(item_id: str, ok: bool, cfg, error: str = '') -> None:
    from ..models.database import SessionLocal, NotificationOutbox
    db = SessionLocal()
    try:
        o = db.query(NotificationOutbox).filter(NotificationOutbox.id == item_id).first()
        if not o:
            return
        if ok:
            o.status = 'sent'
            o.sent_at = datetime.now()
        else:
            if (o.attempt_count or 0) >= cfg.max_retry_count:
                o.status = 'failed'
            else:
                o.status = 'pending'
                o.next_retry_at = datetime.now() + timedelta(seconds=cfg.retry_interval_seconds)
            o.last_error = error or '发送失败'
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def get_unread_count() -> int:
    from ..models.database import SessionLocal, NotificationInboxItem
    db = SessionLocal()
    try:
        return db.query(NotificationInboxItem).filter(NotificationInboxItem.is_read == False).count()
    except Exception:
        return 0
    finally:
        db.close()


def list_notifications(page: int = 1, limit: int = 30, unread_only: bool = False) -> dict:
    from ..models.database import SessionLocal, NotificationInboxItem
    db = SessionLocal()
    try:
        q = db.query(NotificationInboxItem)
        if unread_only:
            q = q.filter(NotificationInboxItem.is_read == False)
        total = q.count()
        items = q.order_by(NotificationInboxItem.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {'total': total, 'items': [i.to_dict() for i in items]}
    finally:
        db.close()


def mark_read(ids: list) -> int:
    from ..models.database import SessionLocal, NotificationInboxItem
    db = SessionLocal()
    try:
        now = datetime.now()
        updated = (
            db.query(NotificationInboxItem)
            .filter(NotificationInboxItem.id.in_(ids), NotificationInboxItem.is_read == False)
            .all()
        )
        for item in updated:
            item.is_read = True
            item.read_at = now
        db.commit()
        return len(updated)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_all_read() -> int:
    from ..models.database import SessionLocal, NotificationInboxItem
    db = SessionLocal()
    try:
        now = datetime.now()
        updated = db.query(NotificationInboxItem).filter(NotificationInboxItem.is_read == False).all()
        for item in updated:
            item.is_read = True
            item.read_at = now
        db.commit()
        return len(updated)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_notification(item_id: str) -> bool:
    from ..models.database import SessionLocal, NotificationInboxItem, NotificationOutbox
    db = SessionLocal()
    try:
        item = db.query(NotificationInboxItem).filter(NotificationInboxItem.id == item_id).first()
        if not item:
            return False
        db.query(NotificationOutbox).filter(NotificationOutbox.inbox_item_id == item_id).delete()
        db.delete(item)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cleanup_old_notifications(retain_days: int = 30, max_items: int = 200) -> int:
    """清理过期和超量通知"""
    from ..models.database import SessionLocal, NotificationInboxItem, NotificationOutbox
    db = SessionLocal()
    deleted = 0
    try:
        cutoff = datetime.now() - timedelta(days=retain_days)
        old_items = db.query(NotificationInboxItem).filter(
            NotificationInboxItem.is_read == True,
            NotificationInboxItem.created_at < cutoff
        ).all()
        for item in old_items:
            db.query(NotificationOutbox).filter(NotificationOutbox.inbox_item_id == item.id).delete()
            db.delete(item)
            deleted += 1
        count = db.query(NotificationInboxItem).count()
        if count > max_items:
            oldest = (
                db.query(NotificationInboxItem)
                .filter(NotificationInboxItem.is_read == True)
                .order_by(NotificationInboxItem.created_at)
                .limit(count - max_items)
                .all()
            )
            for item in oldest:
                db.query(NotificationOutbox).filter(NotificationOutbox.inbox_item_id == item.id).delete()
                db.delete(item)
                deleted += 1
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()
