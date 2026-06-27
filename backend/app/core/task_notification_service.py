import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qsl, urlsplit

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


def _broadcast_realtime_notification(event: dict) -> None:
    try:
        from .realtime_event_service import broadcast_event as broadcast_realtime_event

        event_type = str((event or {}).get('type') or '').strip()
        if event_type == 'new_notification':
            item = event.get('item') if isinstance(event.get('item'), dict) else {}
            broadcast_realtime_event({
                'type': 'notification.new',
                'reason': 'created',
                'id': str(item.get('id') or ''),
                'domain': 'notification',
                'status': 'unread',
                'updated_at': datetime.now().isoformat(),
                'payload': dict(event),
            })
            return

        if event_type == 'circle_owned_synced':
            canonicals = event.get('canonicals') if isinstance(event.get('canonicals'), list) else []
            broadcast_realtime_event({
                'type': 'circle.owned.synced',
                'reason': 'owned_synced',
                'id': str(event.get('rjcode') or (canonicals[0] if canonicals else '') or ''),
                'domain': 'circle_completion',
                'status': 'completed',
                'updated_at': datetime.now().isoformat(),
                'payload': dict(event),
            })
            return

        if event_type == 'circle_subtitle_synced':
            canonicals = event.get('canonicals') if isinstance(event.get('canonicals'), list) else []
            broadcast_realtime_event({
                'type': 'circle.subtitle.synced',
                'reason': 'subtitle_synced',
                'id': str(event.get('rjcode') or (canonicals[0] if canonicals else '') or ''),
                'domain': 'circle_completion',
                'status': 'completed',
                'updated_at': datetime.now().isoformat(),
                'payload': dict(event),
            })
    except Exception:
        logger.debug("桥接通知统一实时事件失败", exc_info=True)


def _sse_broadcast(event: dict) -> None:
    """从任意线程安全地推送事件到所有已连接 SSE 客户端"""
    _broadcast_realtime_notification(event)
    with _sse_lock:
        subs = list(_sse_subscribers.values())
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception:
            pass

_NON_TERMINAL = frozenset({'pending', 'processing', 'paused', 'waiting_retry'})
_IMPORT_TASK_KINDS = frozenset({'auto_process', 'process_existing_folder', 'extract'})


def _normalize_route_hint(route_hint) -> dict:
    if isinstance(route_hint, dict):
        normalized = dict(route_hint)
    else:
        normalized = {'path': str(route_hint)} if route_hint else {}
    path = str(normalized.get('path') or '').strip()
    if '?' not in path:
        normalized['path'] = path
        normalized['query'] = dict(normalized.get('query') or {})
        return normalized
    parsed = urlsplit(path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(dict(normalized.get('query') or {}))
    normalized['path'] = parsed.path or path.split('?', 1)[0]
    normalized['query'] = query
    return normalized


def _task_status(task) -> str:
    return (task.status.value if hasattr(task.status, 'value') else str(task.status)).lower()


def _task_kind(task) -> str:
    return (task.type.value if hasattr(getattr(task, 'type', None), 'value') else str(getattr(task, 'type', '')))


def _is_http_download_partial_success(task) -> bool:
    meta = dict(getattr(task, 'task_metadata', None) or {})
    task_kind = _task_kind(task)
    if task_kind == 'baidu_netdisk_upload' or str(meta.get('source_action') or '') == 'manual_baidu_netdisk_upload':
        return False
    if task_kind not in {'http_download', 'baidu_netdisk_download'} and str(meta.get('task_domain') or '') not in {'http_download', 'baidu_netdisk'}:
        return False
    failed = list(meta.get('failed_files') or [])
    metrics = meta.get('performance_metrics') if isinstance(meta.get('performance_metrics'), dict) else {}
    success_count = int(metrics.get('success_count') or 0)
    if not success_count:
        success_count = sum(
            1 for row in list(meta.get('download_files') or [])
            if isinstance(row, dict) and str(row.get('status') or '').lower() == 'completed'
        )
    return bool(success_count and failed)


def _get_group_tasks(group_key: str) -> list:
    try:
        from .task_engine import get_task_engine
        engine = get_task_engine()
        return [t for t in list(engine.tasks.values()) if _resolve_group_key(t)[0] == group_key]
    except Exception:
        return []


def _select_notification_context_task(current_task, group_key: str, group_type: str):
    if group_type == 'task':
        return current_task
    group_tasks = _get_group_tasks(group_key)
    import_tasks = [t for t in group_tasks if _task_kind(t) in _IMPORT_TASK_KINDS]
    if not import_tasks:
        return current_task
    if _task_kind(current_task) in _IMPORT_TASK_KINDS:
        return current_task
    import_tasks.sort(key=lambda t: getattr(t, 'started_at', None) or getattr(t, 'created_at', None) or datetime.min)
    return import_tasks[0]


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
        if _is_http_download_partial_success(current_task):
            return 'failed'
        if status == 'failed':
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
            if _is_http_download_partial_success(t):
                has_failed = True
            elif st == 'failed':
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
    context_task = _select_notification_context_task(current_task, group_key, group_type)
    try:
        # 这里只需要 domain / title / rjcode / route_hint 等轻量字段，
        # 走 summary 序列化避免触发文件树 os.walk；并且复用单例不重复建实例
        from .task_center_service import get_task_center_service
        tcs = get_task_center_service()
        serialized = tcs._serialize_engine_task(context_task, mode="summary")
        domain = serialized.get('domain', 'task')
        domain_label = serialized.get('domain_label') or tcs.DOMAIN_LABELS.get(domain, domain)
        title = serialized.get('title') or serialized.get('source_label') or context_task.id[:8]
        rjcode = serialized.get('rjcode', '')
        route_hint = serialized.get('route_hint') or {}
    except Exception:
        domain = 'task'
        domain_label = '任务'
        title = context_task.id[:8]
        rjcode = ''
        route_hint = {}

    route_hint = _normalize_route_hint(route_hint)

    is_partial_http = _is_http_download_partial_success(context_task)
    severity_map = {'completed': 'success', 'failed': 'danger', 'waiting_manual': 'warning'}
    label_map = {'completed': '已完成', 'failed': '执行失败', 'waiting_manual': '等待处理'}
    if is_partial_http:
        severity_map['failed'] = 'warning'
        label_map['failed'] = '部分成功'

    if group_type != 'task':
        try:
            from .task_engine import get_task_engine
            engine = get_task_engine()
            group_tasks = [t for t in engine.tasks.values() if _resolve_group_key(t)[0] == group_key]
            total = len(group_tasks)
            failed = sum(1 for t in group_tasks if _task_status(t) == 'failed')
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

    meta = dict(context_task.task_metadata or {})
    task_kind = _task_kind(context_task)
    is_baidu_upload = task_kind == 'baidu_netdisk_upload' or str(meta.get('source_action') or '') == 'manual_baidu_netdisk_upload'
    if not is_baidu_upload and (task_kind in {'http_download', 'baidu_netdisk_download'} or domain in {'http_download', 'baidu_netdisk'}):
        try:
            if task_kind == 'baidu_netdisk_download' or domain == 'baidu_netdisk':
                platforms = ['baidu_netdisk']
                platform_label = str(meta.get('platform_label') or '').strip() or '百度网盘'
            else:
                from .http_download_service import http_download_platforms_from_metadata, http_download_platforms_label
                platforms = http_download_platforms_from_metadata(meta)
                platform_label = str(meta.get('platform_label') or '').strip() or http_download_platforms_label(platforms)
        except Exception:
            platforms = list(meta.get('platforms') or meta.get('source_modes') or [])
            platform_label = str(meta.get('platform_label') or '').strip() or domain_label
        if platform_label and platform_label != 'HTTP':
            domain_label = f'{platform_label} 下载'
        title = str(meta.get('batch_name') or meta.get('source_label') or title or '').strip() or domain_label
        if group_type == 'task':
            summary = f'{domain_label}{label_map.get(event_type, event_type)}'
        if is_partial_http:
            metrics = meta.get('performance_metrics') if isinstance(meta.get('performance_metrics'), dict) else {}
            success_count = int(metrics.get('success_count') or 0)
            failed_count = int(metrics.get('failed_count') or len(meta.get('failed_files') or []) or 0)
            if success_count or failed_count:
                summary = f'{domain_label}部分成功：成功 {success_count} 个，失败 {failed_count} 个'
        route_query = dict(route_hint.get('query') or {})
        route_query.update({
            'platforms': ','.join(str(item) for item in platforms if str(item or '').strip()),
            'platform_label': platform_label,
            'download_mode': str(meta.get('download_mode') or '').strip(),
        })
        route_hint = {**route_hint, 'query': route_query}
        meta['platforms'] = platforms
        meta['platform_label'] = platform_label
    if task_kind == 'circle_completion_refresh_selected':
        title, summary, rjcode = _build_refresh_selected_notification_text(meta, domain_label, label_map.get(event_type, event_type))
    return {
        'title': title,
        'summary': summary,
        'severity': severity_map.get(event_type, 'info'),
        'event_label': label_map.get(event_type, event_type),
        'event_icon': '⚠️' if is_partial_http else '',
        'domain': domain,
        'domain_label': domain_label,
        'rjcode': rjcode,
        'source_page': meta.get('source_page', ''),
        'source_action': meta.get('source_action', ''),
        'source_label': meta.get('source_label', '') or meta.get('platform_label', ''),
        'business_key': str(meta.get('business_key') or ''),
        'route_path': route_hint.get('path', ''),
        'route_query': route_hint.get('query') or {},
        'task_kind': task_kind,
        'platforms': list(meta.get('platforms') or []),
        'platform_label': meta.get('platform_label', ''),
        'download_mode': meta.get('download_mode', ''),
        'source_modes': list(meta.get('source_modes') or []),
    }


def _build_refresh_selected_notification_text(meta: dict, domain_label: str, event_label: str) -> tuple[str, str, str]:
    """手动刷新选中作品的站内通知文案。"""
    result = dict(meta.get('refresh_result') or {})
    items = [item for item in list(result.get('items') or []) if isinstance(item, dict)]
    selected_count = _safe_int(result.get('selected_count') or meta.get('selected_count') or len(items))
    refreshed_count = _safe_int(result.get('refreshed_count') or len(items) or selected_count)
    changed_count = _safe_int(result.get('changed_count') or sum(1 for item in items if item.get('changed')))
    if len(items) == 1:
        item = items[0]
        rjcode = str(item.get('display_rjcode') or item.get('canonical_rjcode') or '').strip().upper()
        title = str(item.get('title') or rjcode or meta.get('source_label') or '社团作品信息更新').strip()
        status_text = '有更新' if item.get('changed') else '无变化'
        summary = f'{domain_label}{event_label}：{rjcode} {status_text}'
        return title, summary, rjcode
    circle_name = str(result.get('circle_name') or meta.get('circle_name') or '').strip()
    title = f'{circle_name} · 已刷新 {refreshed_count} 个作品' if circle_name else f'已刷新 {refreshed_count} 个作品'
    summary = f'{domain_label}{event_label}：已选 {selected_count} 个，已刷新 {refreshed_count} 个，有更新 {changed_count} 个'
    return title, summary, ''


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


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

    # 用户主动取消只写操作记录，不写站内通知 / 邮件通知。
    if status == 'cancelled' or (status == 'failed' and getattr(task, 'error_message', '') == '用户取消'):
        logger.info(f"[通知] 跳过 task={tid} 用户主动取消")
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

    if status == 'waiting_manual' and group_type == 'task':
        event_key = f"waiting_manual:{group_key}:{group_run_id}"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_sync, event_key, 'waiting_manual', task, group_key, group_type, group_run_id)
        return

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
                from .notification_helper import (
                    build_notification_extra_for_task,
                    aggregate_import_batch_extras,
                )
                auto_extra = build_notification_extra_for_task(task)
            except Exception:
                logger.warning("[通知] 构建邮件业务块失败 task=%s", getattr(task, "id", "?"), exc_info=True)
                auto_extra = {}

            # 批量任务聚合：把组内所有任务的 rj_work_cards / file_tree / 错误日志合并展示
            batch_extra: dict = {}
            if group_type != 'task':
                try:
                    from .task_engine import get_task_engine
                    engine = get_task_engine()
                    group_tasks = [
                        t for t in list(engine.tasks.values())
                        if _resolve_group_key(t)[0] == group_key
                    ]
                    has_import_task = any(_task_kind(t) in _IMPORT_TASK_KINDS for t in group_tasks)
                    # 只要组内包含解压 / 入库任务，就按入库批量聚合；
                    # 当前触发通知的任务可能是字幕补配 waiting_manual，不能用它的 kind 判断。
                    if has_import_task:
                        batch_extra = aggregate_import_batch_extras(task, group_tasks)
                except Exception:
                    logger.warning("[通知] 批量聚合业务块失败 task=%s", getattr(task, "id", "?"), exc_info=True)
                    batch_extra = {}

            extra = {
                **(auto_extra if isinstance(auto_extra, dict) else {}),
                **(meta.get('notification_extra') or {}),
                **(batch_extra if isinstance(batch_extra, dict) else {}),
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
                    'event_label': info.get('event_label') or '',
                    'event_icon': info.get('event_icon') or '',
                    'domain': info['domain'],
                    'domain_label': info['domain_label'],
                    'rjcode': info['rjcode'],
                    'source_label': info['source_label'],
                    'platforms': info.get('platforms') or [],
                    'platform_label': info.get('platform_label') or '',
                    'download_mode': info.get('download_mode') or '',
                    'source_modes': info.get('source_modes') or [],
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

    # 有限并发：串行 await 时单封 SMTP 30 秒超时会把整批邮件全部卡住，
    # 一次性炸出多封通知就会引发用户感知的"接口都不动了"现象。
    # 用 Semaphore(2) 控制并发数：足以让单封超时不影响其他通道，
    # 同时保守避免 QQ/163 SMTP 单 IP 限速。
    send_sem = asyncio.Semaphore(2)

    async def _send_one(snap: dict) -> None:
        item_id = snap['id']
        async with send_sem:
            try:
                subject, html_body, text_body = render_email_for_outbox(snap['payload'])
                ok = await send_notification_email(subject, html_body, text_body)
                _update_outbox_status(item_id, ok, cfg, error='' if ok else '发送失败')
                logger.info(f"[通知] outbox 发送结果 id={item_id} ok={ok}")
            except Exception as e:
                logger.error(f"[通知] outbox 发送异常 id={item_id}: {e}", exc_info=True)
                _update_outbox_status(item_id, False, cfg, error=str(e))

    await asyncio.gather(
        *[_send_one(s) for s in pending_snapshots],
        return_exceptions=True,
    )


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


def create_custom_notification(
    *,
    event_key: str,
    event_type: str,
    title: str,
    summary: str,
    severity: str = 'info',
    task_domain: str = 'system',
    task_kind: str = 'custom',
    source_page: str = '',
    source_action: str = '',
    source_label: str = '',
    business_key: str = '',
    rjcode: str = '',
    route_path: str = '',
    route_query: Optional[dict] = None,
) -> str:
    """写一条自定义站内通知，并通过 SSE 推送。"""
    from ..models.database import SessionLocal, NotificationInboxItem

    db = SessionLocal()
    try:
        existing = db.query(NotificationInboxItem).filter(NotificationInboxItem.event_key == event_key).first()
        if existing:
            return str(existing.id or '')

        now = datetime.now()
        item = NotificationInboxItem(
            id=str(uuid.uuid4()),
            event_key=event_key,
            event_type=str(event_type or 'custom'),
            severity=str(severity or 'info'),
            group_key=str(business_key or event_key),
            group_type='custom',
            group_run_id='',
            primary_task_id='',
            task_ids=[],
            session_id='',
            parent_session_id='',
            batch_id='',
            task_domain=str(task_domain or 'system'),
            task_kind=str(task_kind or 'custom'),
            source_page=str(source_page or ''),
            source_action=str(source_action or ''),
            source_label=str(source_label or ''),
            business_key=str(business_key or ''),
            title=str(title or '').strip(),
            summary=str(summary or '').strip(),
            rjcode=str(rjcode or '').strip().upper(),
            route_path=str(route_path or ''),
            route_query=dict(route_query or {}),
            is_read=False,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db.commit()
        try:
            unread_n = db.query(NotificationInboxItem).filter(NotificationInboxItem.is_read.is_(False)).count()
            _sse_broadcast({
                'type': 'new_notification',
                'unread_count': unread_n,
                'item': item.to_dict(),
            })
        except Exception:
            pass
        return item.id
    except Exception:
        db.rollback()
        logger.error("[通知] 写入自定义通知失败", exc_info=True)
        return ''
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


def cleanup_old_notifications(retain_days: int = 30, max_items: int = 200, outbox_max_items: int | None = None) -> int:
    """清理过期和超量通知。

    outbox 只清理 sent/failed 终态记录，不碰 pending/sending，避免误删待发送邮件。
    """
    from ..models.database import SessionLocal, NotificationInboxItem, NotificationOutbox
    db = SessionLocal()
    deleted = 0
    try:
        cutoff = datetime.now() - timedelta(days=retain_days)
        active_outbox_inbox_ids = (
            db.query(NotificationOutbox.inbox_item_id)
            .filter(
                NotificationOutbox.status.in_(["pending", "sending"]),
                NotificationOutbox.inbox_item_id.isnot(None),
            )
        )
        old_items = db.query(NotificationInboxItem).filter(
            NotificationInboxItem.is_read == True,
            NotificationInboxItem.created_at < cutoff,
            ~NotificationInboxItem.id.in_(active_outbox_inbox_ids),
        ).all()
        for item in old_items:
            db.query(NotificationOutbox).filter(
                NotificationOutbox.inbox_item_id == item.id,
                NotificationOutbox.status.in_(["sent", "failed"]),
            ).delete(synchronize_session=False)
            db.delete(item)
            deleted += 1
        count = db.query(NotificationInboxItem).count()
        if count > max_items:
            oldest = (
                db.query(NotificationInboxItem)
                .filter(
                    NotificationInboxItem.is_read == True,
                    ~NotificationInboxItem.id.in_(active_outbox_inbox_ids),
                )
                .order_by(NotificationInboxItem.created_at)
                .limit(count - max_items)
                .all()
            )
            for item in oldest:
                db.query(NotificationOutbox).filter(
                    NotificationOutbox.inbox_item_id == item.id,
                    NotificationOutbox.status.in_(["sent", "failed"]),
                ).delete(synchronize_session=False)
                db.delete(item)
                deleted += 1
        terminal_outbox = db.query(NotificationOutbox).filter(
            NotificationOutbox.status.in_(["sent", "failed"]),
            NotificationOutbox.created_at < cutoff,
        )
        deleted += int(terminal_outbox.delete(synchronize_session=False) or 0)
        safe_outbox_max = max(1, int(outbox_max_items if outbox_max_items is not None else max_items))
        outbox_count = db.query(NotificationOutbox).filter(NotificationOutbox.status.in_(["sent", "failed"])).count()
        if outbox_count > safe_outbox_max:
            oldest_outbox_ids = [
                row.id
                for row in (
                    db.query(NotificationOutbox.id)
                    .filter(NotificationOutbox.status.in_(["sent", "failed"]))
                    .order_by(NotificationOutbox.created_at)
                    .limit(outbox_count - safe_outbox_max)
                    .all()
                )
            ]
            if oldest_outbox_ids:
                deleted += int(
                    db.query(NotificationOutbox)
                    .filter(NotificationOutbox.id.in_(oldest_outbox_ids))
                    .delete(synchronize_session=False)
                    or 0
                )
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()
