"""字幕入口共用的任务创建与真实位置去重。"""
import asyncio
import hashlib
import os
import posixpath
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import and_, or_, text

from ..models.database import SessionLocal, Task as TaskRecord

_creation_lock = asyncio.Lock()
ACTIVE_STATUSES = {'pending', 'processing', 'paused', 'waiting_manual', 'waiting_retry'}


def location_key(library_id, path):
    value = str(path or '').replace('\\', '/')
    if not value.startswith('/') or os.name == 'nt' and ':' in value:
        value = os.path.normcase(os.path.realpath(value)).replace('\\', '/')
    else:
        value = posixpath.normpath(value)
    return str(library_id or ''), value.rstrip('/')


def task_payload(task):
    metadata = dict(task.task_metadata or {})
    status = getattr(task.status, 'value', task.status)
    return {
        'task_id': task.id, 'status': status,
        'rjcode': metadata.get('rjcode') or getattr(task, 'rjcode', ''),
        'folder_path': metadata.get('folder_path') or task.source_path,
        'folder_name': metadata.get('folder_name') or '',
        'library_id': metadata.get('library_id') or '',
        'awaiting_manual_match': status not in {'failed', 'cancelled'} and bool(metadata.get('awaiting_manual_match')) and not metadata.get('manual_match_completed'),
        'browser_verification_required': status == 'waiting_manual' and bool(metadata.get('browser_verification_required')),
        'skipped_reason': metadata.get('subtitle_repair_skipped_reason') or '',
        'current_step': task.current_step or '',
    }


def existing_location_task(engine, library_id, folder_path, *, db=None, include_failed=False):
    key = location_key(library_id, folder_path)
    tasks = [task for task in engine.get_all_tasks() if getattr(task.type, 'value', task.type) == 'rj_subtitle_fetch']
    if db is not None:
        known = {task.id for task in tasks}
        statuses = ACTIVE_STATUSES | ({'failed', 'cancelled'} if include_failed else set())
        tasks += [row for row in db.query(TaskRecord).filter(
            TaskRecord.type == 'rj_subtitle_fetch',
            or_(TaskRecord.status.in_(list(statuses)), and_(
                TaskRecord.task_metadata['awaiting_manual_match'].as_boolean().is_(True),
                TaskRecord.task_metadata['manual_match_completed'].as_boolean().is_not(True),
            )),
        ).all() if row.id not in known]
    tasks.sort(key=lambda task: (
        getattr(task.status, 'value', task.status) in ACTIVE_STATUSES or task_payload(task)['awaiting_manual_match'],
        task.created_at or datetime.min,
    ), reverse=True)
    for task in tasks:
        metadata = task.task_metadata or {}
        status = getattr(task.status, 'value', task.status)
        if status not in ACTIVE_STATUSES and not (include_failed and status in {'failed', 'cancelled'}) and not task_payload(task)['awaiting_manual_match']:
            continue
        if location_key(metadata.get('library_id'), metadata.get('folder_path') or task.source_path) == key:
            return task_payload(task)
    return None


@asynccontextmanager
async def subtitle_creation_guard(library_id, folder_path):
    # 同进程串行加跨进程 advisory lock，锁覆盖检查、提交与持久化。
    async with _creation_lock:
        digest = hashlib.sha256(repr(location_key(library_id, folder_path)).encode()).digest()
        key = int.from_bytes(digest[:8], 'big', signed=True)
        db = SessionLocal()
        acquired = False
        try:
            while not acquired:
                acquired = await asyncio.to_thread(lambda: db.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar())
                if not acquired:
                    await asyncio.sleep(.1)
            yield db
        finally:
            try:
                if acquired:
                    await asyncio.to_thread(db.execute, text('SELECT pg_advisory_unlock(:key)'), {'key': key})
            finally:
                db.close()


async def submit_subtitle_task(engine, *, folder_path, metadata):
    from .task_engine import Task, TaskType
    task = Task(TaskType.RJ_SUBTITLE_FETCH, source_path=folder_path, auto_classify=False, metadata=metadata)
    await engine.submit(task)
    await asyncio.to_thread(engine.persist_task_snapshot, task)
    return task


async def create_or_reuse_subtitle_task(engine, *, folder_path, metadata):
    async with subtitle_creation_guard(metadata.get('library_id'), folder_path) as db:
        existing = await asyncio.to_thread(existing_location_task, engine, metadata.get('library_id'), folder_path, db=db)
        if existing:
            return None, existing
        return await submit_subtitle_task(engine, folder_path=folder_path, metadata=metadata), None
