"""浏览器上传会话：独立接收、有限落地队列、可恢复检查点。"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert

from ..config.settings import get_config
from ..models.database import BrowserUploadSession, BrowserUploadFile, SessionLocal
from .browser_upload_storage import (
    CHUNK_SIZE, atomic_json, digest_file, install_local, local_target,
    receive_chunk, recover_checkpoint, relative_name, read_checkpoint, verify_received_file,
)
from .library_manager import get_library_manager

logger = logging.getLogger(__name__)
TERMINAL = {'completed', 'failed', 'cancelled'}
FILE_TERMINAL = {'completed', 'skipped', 'failed', 'cancelled'}
RETENTION_SECONDS = 7 * 86400


class UploadRestoring(Exception):
    pass


class UploadStopped(Exception):
    pass


class BrowserUploadService:
    def __init__(self, session_factory=None, manager=None, temp_root=None):
        self.db = session_factory or SessionLocal
        self.manager = manager or get_library_manager()
        self.root = Path(temp_root or get_config().storage.temp_path) / 'browser-uploads'
        self.sessions = {}
        self.locks = {}
        self.target_locks = {}
        self.lock_users = {}
        self.receive_slots = asyncio.Semaphore(3)
        self.workers = []
        self.queue = asyncio.Queue(maxsize=100)
        self.queued = set()
        self.stopping = False
        self.remote_commit_locks = {}
        self.remote_commit_verified = {}
        self.checkpoints = {}
        self.hashers = {}
        self.recovering = False
        self.recovery_error = None
        self.recovery_task = None

    @asynccontextmanager
    async def locked(self, mapping, key, state=None):
        lock = mapping.setdefault(key, asyncio.Lock())
        self.lock_users[lock] = self.lock_users.get(lock, 0) + 1
        if state is not None:
            state['_file_operations'] = state.get('_file_operations', 0) + 1
        try:
            async with lock:
                if state is not None and state.get('_expiring'):
                    raise UploadStopped('会话已过期')
                yield
        finally:
            if state is not None:
                state['_file_operations'] -= 1
            self.lock_users[lock] -= 1
            if not self.lock_users[lock]:
                self.lock_users.pop(lock)
                mapping.pop(key, None)

    def _persist(self, state, files):
        with self.db() as db:
            row = db.get(BrowserUploadSession, state['id'])
            previous = dict(row.state) if row is not None else {}
            if row is None:
                row = BrowserUploadSession(id=state['id'], token_hash=state['_token_hash'],
                    library_id=state['library_id'], target_path=state['target_path'])
                db.add(row)
            row.state = {k: v for k, v in state.items() if not k.startswith('_') and k != 'files'}
            if state['status'] in TERMINAL:
                key = self.audit_key(state)
                if state.get('logged_event_key') != key and previous.get('logged_event_key') != key:
                    from .activity_log_service import _build_and_write_task_lifecycle_log
                    _build_and_write_task_lifecycle_log(self.audit_snapshot(state), transaction=db, event_key=key)
                row.state = {**row.state, 'logged_event_key': key}
            row.updated_at = datetime.now()
            for offset in range(0, len(files), 1000):
                statement = insert(BrowserUploadFile).values([
                    dict(session_id=state['id'], id=f['id'], relative_path=f['relative_path'], state=dict(f))
                    for f in files[offset:offset + 1000]
                ])
                db.execute(statement.on_conflict_do_update(
                    index_elements=['session_id', 'id'], set_={'state': statement.excluded.state}))
            db.commit()

    async def save(self, state, files=()):
        # 在事件循环上冻结快照，线程中不读取正被进度回调修改的对象。
        files = list(files)
        for file in files:
            self.track_file(state, file)
        self.finalize_state(state)
        async with state.setdefault('_save_lock', asyncio.Lock()):
            if state.get('_expiring'):
                raise UploadStopped('会话已过期')
            snapshot = {k: v for k, v in state.items() if not k.startswith('_') and k != 'files'}
            snapshot['_token_hash'] = state['_token_hash']
            if state['status'] in TERMINAL:
                snapshot['_audit_summary'] = self.summary(state)
            frozen = [dict(f) for f in files]
            await asyncio.to_thread(self._persist, snapshot, frozen)

    async def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.stopping = False
        self.recovering = True
        self.workers = [asyncio.create_task(self.worker()) for _ in range(3)]
        self.recovery_task = asyncio.create_task(self.restore())
        self.maintenance_task = asyncio.create_task(self.maintenance())

    async def restore(self):
        try:
            await self._restore()
        except Exception as exc:
            self.recovery_error = exc
            logger.exception('浏览器上传会话后台恢复失败')
        finally:
            self.recovering = False

    async def _restore(self):
        def load():
            with self.db() as db:
                sessions = db.scalars(select(BrowserUploadSession).where(
                    BrowserUploadSession.id > cursor).order_by(BrowserUploadSession.id).limit(100)).all()
                return [(r.id, r.token_hash, dict(r.state), r.updated_at) for r in sessions]
        cursor = ''
        while rows := await asyncio.to_thread(load):
            for row in rows:
                try:
                    await self.restore_session(*row)
                except Exception as exc:
                    self.recovery_error = exc
                    logger.exception('浏览器上传会话恢复失败：%s', row[0])
                await asyncio.sleep(0)
            cursor = rows[-1][0]

    async def restore_session(self, sid, token_hash, state, updated):
        def load_files():
            with self.db() as db:
                return [dict(r.state) for r in db.scalars(select(BrowserUploadFile).where(
                    BrowserUploadFile.session_id == sid))]
        files = await asyncio.to_thread(load_files)
        rows = [(sid, token_hash, state, updated)]
        for sid, token_hash, state, updated in rows:
            state.update(id=sid, _token_hash=token_hash, files={}, _dirty=set(), _last_save=time.monotonic())
            if state['status'] in TERMINAL and 'audit_revision' not in state:
                # 旧终态已产生历史；升级恢复只建立基线，绝不重放完成事件。
                state['audit_revision'] = 0
                state['logged_event_key'] = self.audit_key(state)
            state['_restored_terminal'] = state['status'] in {'completed', 'cancelled'}
            if updated < datetime.now() - timedelta(days=7) and state['status'] not in TERMINAL:
                state['status'] = 'cancelled'
                state['reason'] = '会话超过七天无活动，已过期'
            state['_restoring'] = True
            self.sessions[sid] = state
        for file in files:
            state['files'][file['id']] = file
            if state['status'] == 'cancelled':
                if file['status'] not in FILE_TERMINAL:
                    file.update(status='cancelled', reason=state.get('reason', '会话已取消'))
                    state['_dirty'].add(file['id'])
                continue
            if file['status'] not in FILE_TERMINAL:
                try:
                    self.receipt(sid, file['id'])
                    if await self.recover_commit(state, file):
                        state['_dirty'].add(file['id'])
                        continue
                    checkpoint = await asyncio.to_thread(recover_checkpoint, self.part(sid, file['id']),
                        self.receipt(sid, file['id']), False)
                    file['received'] = checkpoint['offset']
                    file['status'] = 'ready' if file.get('is_directory') else 'verifying' if file['received'] == file['size'] else 'receiving'
                    file['written'] = 0
                except Exception as exc:
                    file.update(status='failed', stage='恢复写入', reason=str(exc), retryable=True)
                    state['_dirty'].add(file['id'])
                    logger.exception('恢复浏览器上传失败：%s', file['relative_path'])
                    continue
                state['_dirty'].add(file['id'])
        state['_known_paths'] = {f['relative_path']: f for f in state['files'].values()}
        state.setdefault('last_activity', updated.timestamp())
        for file in state['files'].values():
            self.track_file(state, file)
        dirty = state['_dirty'].copy()
        if dirty:
            await self.save(state, [state['files'][fid] for fid in dirty])
            state['_dirty'].difference_update(dirty)
        state['_restoring'] = False
        if state['status'] in TERMINAL and updated.timestamp() < time.time() - RETENTION_SECONDS:
            await self.expire_session(state)

    async def stop(self):
        self.stopping = True
        if self.recovery_task:
            await self.recovery_task
        self.maintenance_task.cancel()
        await asyncio.gather(self.maintenance_task, return_exceptions=True)
        # 不取消 to_thread：必须等活跃复制结束并记录真实提交结果。
        while not self.queue.empty():
            key = self.queue.get_nowait()
            self.queued.discard(key)
            self.queue.task_done()
        for _ in self.workers:
            await self.queue.put(None)
        await asyncio.gather(*self.workers, return_exceptions=True)
        for state in self.sessions.values():
            if not state.get('_settled'):
                await self.save(state, [state['files'][fid] for fid in state['_dirty']])

    def part(self, sid, fid, create_parent=True):
        state = self.sessions.get(sid)
        file = state and state.get('files', {}).get(fid)
        if state and file:
            library = self.library(state['library_id'])
            if library.type != 'local':
                return self.root / sid / (fid + '.part')
            root = library.browse_root_path or library.root_path
            target = local_target(root, str(Path(state['target_path']) / file['relative_path']))
            if not target.parent.exists() or target.parent.is_dir():
                if create_parent:
                    target.parent.mkdir(parents=True, exist_ok=True)
                return target.parent / ('.kikoerumanager-upload-' + fid + '.part')
        return self.root / sid / (fid + '.part')

    def journal(self, state, file):
        return self.part(state['id'], file['id']).with_suffix('.commit')

    def receipt(self, sid, fid):
        receipt = self.root / sid / (fid + '.json')
        legacy = self.part(sid, fid).with_suffix('.json')
        if legacy != receipt and legacy.exists():
            if receipt.exists():
                if digest_file(receipt) != digest_file(legacy):
                    raise OSError('新旧上传回执不一致，保留两份回执供核对')
                legacy.unlink(missing_ok=True)
            else:
                # 回执与库存可能分属不同挂载点，先提交目标卷上的副本再删除来源。
                receipt.parent.mkdir(parents=True, exist_ok=True)
                pending = receipt.with_name(receipt.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    with legacy.open('rb') as source, pending.open('xb') as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    if digest_file(pending) != digest_file(legacy):
                        raise OSError('上传回执迁移校验失败，保留原回执')
                    os.replace(pending, receipt)
                    from .file_move_protocol import fsync_directory
                    fsync_directory(receipt.parent)
                    legacy.unlink()
                    fsync_directory(legacy.parent)
                finally:
                    pending.unlink(missing_ok=True)
        return receipt

    async def recover_commit(self, state, file):
        journal = self.journal(state, file)
        if not journal.exists():
            return False
        intent = await asyncio.to_thread(lambda: json.loads(journal.read_text('utf-8')))
        library = self.library(state['library_id'])
        target = intent['target']
        committed = False
        if library.type == 'local':
            final = await asyncio.to_thread(local_target, library.browse_root_path or library.root_path, target)
            committed = final.is_file() and await asyncio.to_thread(digest_file, final) == file.get('sha256')
            pending = final.parent / ('.kikoerumanager-upload-' + file['id'] + '.part')
            if committed:
                await asyncio.to_thread(pending.unlink, missing_ok=True)
        else:
            client = self.manager.get_cached_synology_client(library.synology)
            await self.validate_remote_path(library, str(PurePosixPath(target).parent))
            children = await self.manager._list_remote_directory(client, str(PurePosixPath(target).parent))
            paths = {str(PurePosixPath(target).parent / c['name']) for c in children}
            if target in paths:
                h = hashlib.sha256()
                async for block in client.stream_download(target):
                    h.update(block)
                committed = h.hexdigest() == file.get('sha256')
            backup = intent.get('backup')
            if backup in paths:
                if committed:
                    await client.delete(backup)
                elif target not in paths:
                    await client.rename(backup, PurePosixPath(target).name)
                else:
                    raise RuntimeError('恢复上传时发现目标与备份同时存在且摘要不符，请检查：' + backup)
            if intent.get('pending') in paths:
                await client.delete(intent['pending'])
        if committed:
            file.update(status='completed', stage='完成', final_path=target, written=file['size'], received=file['size'], reason='')
            state.setdefault('_index_paths', set()).add(PurePosixPath(file['relative_path']).parts[0])
            await asyncio.to_thread(self.part(state['id'], file['id']).unlink, missing_ok=True)
        await asyncio.to_thread(journal.unlink, missing_ok=True)
        return committed

    def library(self, library_id):
        library = self.manager.get_library_definition(library_id)
        if not library or library.id != library_id or not library.enabled or not library.writable:
            raise PermissionError('目标库存不存在、未启用或不可写')
        return library

    async def resolve_target(self, library_id, incoming):
        library = self.library(library_id)
        if str(incoming).startswith('circle:'):
            raise ValueError('请选择唯一的实际目录')
        if library.type == 'local':
            target = await asyncio.to_thread(local_target, library.browse_root_path or library.root_path, incoming)
            if not target.is_dir() or not os.access(target, os.W_OK):
                raise PermissionError('上传目标必须是可写目录')
            return library, str(target)
        if library.type != 'synology_filestation':
            raise ValueError('该库存类型不支持浏览器上传')
        _, target = self.manager._resolve_remote_operation_path(library, incoming, action='浏览器上传')
        client = self.manager.get_cached_synology_client(library.synology)
        info = await self.validate_remote_path(library, target)
        if not info or not info.get('isdir'):
            raise PermissionError('群晖上传目标不是目录')
        return library, target

    async def validate_remote_path(self, library, target):
        """逐级核对 FileStation 的真实路径，拒绝链接越界及内部链接。"""
        client = self.manager.get_cached_synology_client(library.synology)
        root = PurePosixPath(library.browse_root_path or library.root_path)
        relative = PurePosixPath(target).relative_to(root)
        root_info = self.manager._first_remote_info_item(await client.stat(str(root)))
        root_real = (root_info or {}).get('additional', {}).get('real_path')
        if not root_real:
            raise PermissionError('群晖未提供库存根目录真实路径，无法校验上传边界')
        info = root_info
        current = root
        for part in relative.parts:
            current /= part
            info = self.manager._first_remote_info_item(await client.stat(str(current)))
            actual = (info or {}).get('additional', {}).get('real_path')
            expected = PurePosixPath(root_real) / current.relative_to(root)
            if not actual or PurePosixPath(actual) != expected or (info or {}).get('is_symlink'):
                raise PermissionError('群晖目标包含链接或真实路径超出库存边界：' + str(current))
        return info

    async def ensure_remote_directory(self, library, target):
        client = self.manager.get_cached_synology_client(library.synology)
        root = PurePosixPath(library.browse_root_path or library.root_path)
        current = root
        await self.validate_remote_path(library, str(root))
        for name in PurePosixPath(target).relative_to(root).parts:
            children = await self.manager._list_remote_directory(client, str(current))
            item = next((item for item in children if item.get('name') == name), None)
            if item is None:
                await client.create_folder(str(current), name)
            elif not item.get('isdir'):
                raise FileExistsError('父目录位置已有同名文件：' + str(current / name))
            current /= name
            await self.validate_remote_path(library, str(current))

    async def verify_remote_commit(self, library, parent):
        """仅使用独立探针文件验证重命名碰撞不会覆盖已有内容。"""
        key = (library.id, parent)
        async with self.locked(self.remote_commit_locks, key):
            if time.monotonic() - self.remote_commit_verified.get(key, -3600) < 3600:
                return
            client = self.manager.get_cached_synology_client(library.synology)
            prefix = '.kikoerumanager-probe-' + uuid.uuid4().hex
            source = self.root / (prefix + '.tmp')
            names = [prefix + '-a', prefix + '-b']
            try:
                for index, name in enumerate(names):
                    await asyncio.to_thread(source.write_bytes, bytes([index + 1]))
                    await client.upload_file(parent, str(source), overwrite=False, remote_name=name)
                try:
                    await client.rename(str(PurePosixPath(parent) / names[1]), names[0])
                except Exception:
                    pass
                for index, name in enumerate(names):
                    content = bytearray()
                    async for block in client.stream_download(str(PurePosixPath(parent) / name)):
                        content.extend(block)
                        if len(content) > 1:
                            raise RuntimeError('群晖重命名提交能力验证失败')
                    if content != bytes([index + 1]):
                        raise RuntimeError('群晖重命名会覆盖同名文件，拒绝提交上传')
                self.remote_commit_verified.pop(key, None)
                self.remote_commit_verified[key] = time.monotonic()
                while len(self.remote_commit_verified) > 256:
                    self.remote_commit_verified.pop(next(iter(self.remote_commit_verified)))
            finally:
                await asyncio.to_thread(source.unlink, missing_ok=True)
                for name in names:
                    try:
                        await client.delete(str(PurePosixPath(parent) / name))
                    except Exception:
                        logger.warning('群晖提交探针待清理：%s/%s', parent, name, exc_info=True)

    async def create(self, library_id, target_path, source_label):
        library, target = await self.resolve_target(library_id, target_path)
        sid, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        state = dict(id=sid, library_id=library.id, library_name=library.name,
            target_path=target, target_type=library.type, source_label=source_label[:500],
            created_at=datetime.now().isoformat(), status='receiving', enumerated=False,
            audit_revision=0,
            last_activity=time.time(),
            conflict_policy='', files={}, _token_hash=hashlib.sha256(token.encode()).hexdigest(),
            _dirty=set(), _last_save=time.monotonic())
        (self.root / sid).mkdir(parents=True, exist_ok=False)
        self.sessions[sid] = state
        await self.save(state)
        self.publish(state)
        return {**self.summary(state), 'token': token, 'chunk_size': CHUNK_SIZE}

    def get(self, sid, token):
        state = self.sessions.get(sid)
        if not state:
            if self.recovering or self.recovery_error:
                raise UploadRestoring('上传会话正在后台恢复，请稍后重试')
            raise KeyError('上传会话不存在')
        if state.get('_expiring'):
            raise KeyError('上传会话已过期')
        if not token or not hmac.compare_digest(state['_token_hash'], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError('无权访问该上传会话')
        if state.get('_restoring'):
            raise UploadRestoring('上传会话正在后台恢复，请稍后重试')
        return state

    @staticmethod
    def active(state):
        if state.get('_expiring') or state['status'] == 'paused' or state['status'] in TERMINAL:
            raise UploadStopped('会话已暂停或结束')

    def track_file(self, state, file):
        metrics = state.setdefault('_metrics', dict(total_files=0, total_bytes=0, received_bytes=0, written_bytes=0))
        counters = state.setdefault('_counts', {})
        statuses = state.setdefault('_statuses', {})
        previous = state.setdefault('_tracked', {}).get(file['id'])
        current = (file['status'], not file.get('is_directory'), file['size'], file.get('received', 0), file.get('written', 0))
        if previous != current:
            for item, sign in ((previous, -1), (current, 1)):
                if item is None:
                    continue
                status, regular, size, received, written = item
                statuses[status] = statuses.get(status, 0) + sign
                counters[status] = counters.get(status, 0) + sign * regular
                for name, value in zip(metrics, (regular, size, received, written)):
                    metrics[name] += sign * value
            state['_tracked'][file['id']] = current
        signature = (*current, file.get('reason'), file.get('stage'), file.get('decision'), file.get('resolved_path'))
        ready = state.setdefault('_ready', set())
        if file['status'] in {'ready', 'verifying'}:
            ready.add(file['id'])
        else:
            ready.discard(file['id'])
        if state.setdefault('_signatures', {}).get(file['id']) != signature:
            state['_signatures'][file['id']] = signature
            state.setdefault('_publish_pending', set()).add(file['id'])

    def refresh_metrics(self, state):
        if '_metrics' not in state:
            state['_metrics'] = dict(total_files=0, total_bytes=0, received_bytes=0, written_bytes=0)
            for file in state['files'].values():
                self.track_file(state, file)
        ids = set(state.get('_dirty', ())) | {fid for sid, fid in self.queued if sid == state['id']}
        for fid in ids:
            self.track_file(state, state['files'][fid])

    def summary(self, state):
        self.refresh_metrics(state)
        counters = {name: state.get('_counts', {}).get(name, 0) for name in ('completed', 'failed', 'skipped', 'conflict', 'writing', 'verifying')}
        return {**{k: v for k, v in state.items() if not k.startswith('_') and k != 'files'},
            'counts': counters, 'total_entries': len(state['files']),
            'index_pending': bool(state.get('_index_paths')), **state.get('_metrics', {})}

    async def manifest(self, state, entries, finished=False):
        recovering_failed = state['status'] == 'failed'
        if not recovering_failed:
            self.active(state)
        state['last_activity'] = time.time()
        known = state.get('_known_paths')
        if known is None:
            known = state['_known_paths'] = {f['relative_path']: f for f in state['files'].values()}
        added = []
        result = []
        # 文件选择器可能只提供文件；仍需让每一级父目录进入冲突决策链。
        expanded = []
        for item in entries:
            path = relative_name(item['relative_path'])
            for parent in reversed(PurePosixPath(path).parents):
                if str(parent) != '.' and str(parent) not in known:
                    expanded.append((dict(relative_path=str(parent), size=0, last_modified=0, is_directory=True), False))
            expanded.append((item, True))
        for item, requested in expanded:
            path = relative_name(item['relative_path'])
            size = int(item.get('size', 0))
            if size < 0 or size > 2**53 - 1:
                raise ValueError('文件大小不合法')
            previous = known.get(path)
            if previous:
                if any(previous.get(k) != item.get(k) for k in ('size', 'last_modified', 'is_directory')):
                    raise ValueError(f'重新选择的来源不匹配：{path}')
                if requested:
                    result.append(dict(previous))
                continue
            if recovering_failed:
                raise ValueError('失败会话只能重新选择原来源，不能添加新文件')
            file = dict(id=str(uuid.uuid4()), relative_path=path, size=size,
                last_modified=item.get('last_modified', 0), is_directory=bool(item.get('is_directory')),
                received=0, written=0, status='ready' if item.get('is_directory') else 'receiving',
                reason='', stage='接收清单', retryable=True, decision='')
            known[path] = file
            state['files'][file['id']] = file
            added.append(file)
            if requested:
                result.append(dict(file))
        if finished:
            state['enumerated'] = True
        await self.save(state, added)
        self.finish(state)
        return result

    async def chunk(self, state, file, offset, data, digest):
        async with self.locked(self.locks, (state['id'], file['id']), state):
            if file['status'] != 'completed':
                self.active(state)
            if file['status'] not in {'receiving', 'verifying', 'ready', 'writing', 'completed', 'conflict'}:
                raise ValueError('文件不处于接收阶段')
            if file['status'] != 'receiving':
                receipt = self.receipt(state['id'], file['id'])
                checkpoint = await asyncio.to_thread(read_checkpoint, receipt)
                match = next((c for c in checkpoint['chunks'] if c['offset'] == offset), None)
                if not match or match['sha256'] != hashlib.sha256(data).hexdigest() or match['sha256'] != digest or match['size'] != len(data):
                    raise ValueError('重复分块与已确认数据不一致')
                return {'offset': checkpoint['offset']}
            state['_receivers'] = state.get('_receivers', 0) + 1
            try:
                key = (state['id'], file['id'])
                if key not in self.checkpoints:
                    self.checkpoints[key] = await asyncio.to_thread(read_checkpoint, self.receipt(*key))
                if self.checkpoints[key]['offset'] == 0:
                    self.hashers.setdefault(key, {'offset': 0, 'digest': hashlib.sha256()})
                checkpoint = await asyncio.to_thread(receive_chunk, self.part(state['id'], file['id']), offset,
                    data, digest, file['size'], self.receipt(state['id'], file['id']), self.checkpoints[key], self.hashers.get(key))
            except BaseException:
                # 回执可能已追加而 fsync 未返回，重试必须重新读取磁盘上的确认边界。
                self.checkpoints.pop((state['id'], file['id']), None)
                self.hashers.pop((state['id'], file['id']), None)
                raise
            finally:
                state['_receivers'] -= 1
            file['received'] = checkpoint['offset']
            state['last_activity'] = time.time()
            self.active(state)
            file.update(reason='', stage='上传接收')
            state['_dirty'].add(file['id'])
            if file['received'] == file['size']:
                # 浏览器在最后一块响应前关闭也必须继续落地。
                await self._complete_file(state, file)
            return {'offset': checkpoint['offset']}

    async def complete_file(self, state, file):
        async with self.locked(self.locks, (state['id'], file['id']), state):
            return await self._complete_file(state, file)

    async def _complete_file(self, state, file):
        if file['status'] == 'completed':
            return dict(file)
        self.active(state)
        if file['status'] in {'verifying', 'ready', 'writing', 'completed', 'conflict'}:
            return dict(file)
        path = self.part(state['id'], file['id'])
        if file['received'] != file['size']:
            raise ValueError('文件尚未接收完整')
        if not path.exists() and file['size'] == 0:
            path.touch()
        file.update(status='verifying', stage='等待校验完整文件', reason='')
        hasher = self.hashers.pop((state['id'], file['id']), None)
        if hasher is not None and hasher['offset'] == file['size']:
            file['sha256'] = hasher['digest'].hexdigest()
        self.checkpoints.pop((state['id'], file['id']), None)
        state['_dirty'].add(file['id'])
        return dict(file)

    async def action(self, state, action, file_id=None, decision=None, apply_all=False, reason=None, file_ids=None):
        if state.get('_expiring'):
            raise UploadStopped('会话已过期')
        state.pop('_settled', None)
        state['last_activity'] = time.time()
        changed = {}
        if action == 'pause':
            if state['status'] not in TERMINAL:
                state['status'] = 'paused'
        elif action == 'resume':
            if state['status'] in TERMINAL:
                raise ValueError('已结束会话不能恢复，请重试具体失败文件')
            if state['status'] != 'cancelled':
                state['status'] = 'receiving'
        elif action == 'enumeration_failed':
            if state['status'] not in TERMINAL:
                state.update(status='paused', reason=(reason or '读取来源目录失败，请重新选择原来源')[:2000])
        elif action == 'cancel':
            if state['status'] == 'completed':
                raise ValueError('已完成会话不能取消')
            if state['status'] == 'failed':
                state.pop('completed_at', None)
            state['status'] = 'cancelled'
            for file in state['files'].values():
                if file['status'] not in FILE_TERMINAL and file['status'] != 'writing':
                    file.update(status='cancelled', reason='用户取消')
                    changed[file['id']] = file
            for mapping in (self.hashers, self.checkpoints):
                for key in [key for key in mapping if key[0] == state['id']]:
                    mapping.pop(key, None)
        elif action == 'receive_failed':
            file = state['files'].get(file_id)
            if not file:
                raise ValueError('文件不存在')
            async with self.locked(self.locks, (state['id'], file_id), state):
                if file['status'] == 'receiving':
                    file.update(status='failed', stage='上传接收', reason=(reason or '浏览器传输失败')[:2000], retryable=True)
                changed[file_id] = file
                self.checkpoints.pop((state['id'], file_id), None)
                self.hashers.pop((state['id'], file_id), None)
        elif action in {'retry', 'conflict'}:
            if state['status'] == 'cancelled':
                raise ValueError('已取消会话不能重试')
            ids = list(dict.fromkeys(file_ids or [file_id]))
            selected = [state['files'].get(fid) for fid in ids]
            if not selected or any(f is None for f in selected):
                raise ValueError('文件不存在')
            if action == 'conflict' and (decision not in {'skip', 'replace', 'keep_both'} or
                    any(f['status'] != 'conflict' for f in selected)):
                raise ValueError('冲突选项无效或文件不处于冲突状态')
            if action == 'conflict' and decision == 'replace' and any(f.get('type_conflict') for f in selected):
                raise ValueError('文件与目录类型冲突不允许替换')
            retrying = any(f['status'] in {'failed', 'conflict'} for f in selected)
            if retrying and state['status'] in TERMINAL:
                state['audit_revision'] = int(state.get('audit_revision', 0)) + 1
                state.pop('completed_at', None)
                state.pop('logged_event_key', None)
            if action == 'conflict' and apply_all:
                state['conflict_policy'] = decision
                selected = [f for f in state['files'].values() if f['status'] == 'conflict' and
                    not (decision == 'replace' and f.get('type_conflict'))]
            for file in selected:
                if file['status'] in {'failed', 'conflict'}:
                    if action == 'conflict':
                        file['decision'] = decision
                    file.update(status='ready' if file.get('is_directory') or file.get('sha256') else
                        'verifying' if file.get('received') == file['size'] else 'receiving', reason='')
                    changed[file['id']] = file
            if retrying:
                state['status'] = 'receiving'
        else:
            raise ValueError('不支持的操作')
        await self.save(state, changed.values())
        self.finish(state)
        return {**self.summary(state), 'changed_files': [dict(f) for f in (selected if action in {'retry', 'conflict'} else changed.values())]}

    async def checkpoint(self, state, file):
        state['last_activity'] = time.time()
        async with self.locked(self.locks, (state['id'], file['id']), state):
            if file['status'] in {'receiving', 'failed'}:
                saved = await asyncio.to_thread(recover_checkpoint, self.part(state['id'], file['id']),
                    self.receipt(state['id'], file['id']), False)
                self.checkpoints[(state['id'], file['id'])] = saved
                hasher = self.hashers.get((state['id'], file['id']))
                if hasher is not None and hasher['offset'] != saved['offset']:
                    self.hashers.pop((state['id'], file['id']), None)
                file['received'] = saved['offset']
                state['_dirty'].add(file['id'])
                chunks = saved['chunks']
                # 已 fsync 的前缀无需重读；来源重选只核对首、中、尾三个确认块。
                samples = [chunks[i] for i in sorted({0, len(chunks) // 2, len(chunks) - 1})] if chunks else []
                return {'offset': saved['offset'], 'chunks': samples}
            return {'offset': file.get('received', 0), 'chunks': []}

    def check_writing(self, state):
        if self.stopping or state['status'] == 'cancelled':
            raise UploadStopped('用户取消或服务停止')
        if state['status'] == 'paused':
            raise UploadStopped('已暂停，保留已接收文件')
        if state['status'] == 'cancelled':
            raise UploadStopped('用户取消')

    async def destination(self, state, file, library):
        path = relative_name(file.get('resolved_path') or file['relative_path'])
        # 父目录的跳过／另存决策必须传播到整棵来源子树。
        parents = PurePosixPath(file['relative_path']).parents
        known = state.get('_known_paths') or {f['relative_path']: f for f in state['files'].values()}
        for parent in reversed(parents):
            ancestor = known.get(str(parent))
            if not ancestor or not ancestor.get('is_directory'):
                continue
            if ancestor['status'] in {'failed', 'conflict', 'receiving', 'verifying', 'ready', 'writing'}:
                return path, 'wait_parent'
            if ancestor['status'] in {'skipped', 'cancelled'}:
                return path, 'skip'
            if ancestor.get('resolved_path'):
                suffix = str(PurePosixPath(file['relative_path']).relative_to(parent))
                path = str(PurePosixPath(ancestor['resolved_path']) / suffix)
        if file.get('_alternate_name'):
            path = str(PurePosixPath(path).with_name(file['_alternate_name']))
        file['resolved_path'] = path
        if library.type == 'local':
            target = await asyncio.to_thread(local_target, library.browse_root_path or library.root_path, str(Path(state['target_path']) / path))
            exists, isdir = target.exists(), target.is_dir()
        else:
            client = self.manager.get_cached_synology_client(library.synology)
            parent = str(PurePosixPath(state['target_path']) / str(PurePosixPath(path).parent))
            await self.ensure_remote_directory(library, parent)
            # 枚举父目录区分不存在与连接／权限异常，不能将 stat 异常视为不存在。
            children = await self.manager._list_remote_directory(client, parent)
            item = next((c for c in children if c.get('name') == PurePosixPath(path).name), None)
            exists, isdir = item is not None, bool(item and item.get('isdir'))
            if exists:
                await self.validate_remote_path(library, str(PurePosixPath(parent) / PurePosixPath(path).name))
        if exists and file.get('is_directory') and isdir:
            return path, 'merge'
        if not exists:
            return path, 'create'
        decision = file.get('decision') or state.get('conflict_policy')
        type_conflict = isdir != bool(file.get('is_directory'))
        file['type_conflict'] = type_conflict
        if decision == 'skip':
            return path, 'skip'
        if decision == 'keep_both':
            stem = PurePosixPath(path)
            new_name = f'{stem.stem} ({file["id"][:8]}){stem.suffix}'
            file['_alternate_name'] = new_name
            file['resolved_path'] = str(stem.with_name(new_name))
            file['decision'] = ''
            return await self.destination(state, file, library)
        if decision == 'replace' and not type_conflict:
            return path, 'replace'
        file.update(status='conflict', stage='等待冲突', reason='文件与目录类型冲突' if type_conflict else '目标已有同名文件')
        return path, 'conflict'

    async def install_remote(self, state, file, library, relative_path, decision):
        client = self.manager.get_cached_synology_client(library.synology)
        target = str(PurePosixPath(state['target_path']) / relative_path)
        parent, name = str(PurePosixPath(target).parent), PurePosixPath(target).name
        pending_name = '.kikoerumanager-upload-' + file['id']
        pending = str(PurePosixPath(parent) / pending_name)
        backup_name = '.kikoerumanager-backup-' + file['id']
        backup = str(PurePosixPath(parent) / backup_name)
        moved_old = False
        committed = False
        source = self.part(state['id'], file['id'])
        if not source.exists():
            fallback = self.root / state['id'] / (file['id'] + '.part')
            if fallback.exists():
                source = fallback
        if not source.exists() and state.get('target_type') == 'local':
            local_library = self.library(state['library_id'])
            local_root = local_library.browse_root_path or local_library.root_path
            candidate = local_target(local_root, str(Path(state['target_path']) / file['relative_path']))
            adjacent = candidate.parent / ('.kikoerumanager-upload-' + file['id'] + '.part')
            if adjacent.exists():
                source = adjacent
        def progress(done, total):
            self.check_writing(state)
            file['written'] = done
        try:
            await self.validate_remote_path(library, parent)
            await self.verify_remote_commit(library, parent)
            await asyncio.to_thread(atomic_json, self.journal(state, file), dict(target=target, pending=pending, backup=backup))
            await client.upload_file(parent, str(source), overwrite=False, remote_name=pending_name, progress_callback=progress)
            await self.manager._verify_uploaded_remote_file(client, source_path=str(source), remote_path=pending,
                relative_path=relative_path, expected_size=file['size'])
            h = hashlib.sha256()
            async for chunk in client.stream_download(pending):
                self.check_writing(state)
                h.update(chunk)
            if h.hexdigest() != file['sha256']:
                raise ValueError('群晖暂存文件 SHA-256 不一致')
            self.check_writing(state)
            # 不删除旧文件；改名到备份后再提交新文件，失败恢复原名称。
            if decision == 'replace':
                await client.rename(target, backup_name)
                moved_old = True
            await client.rename(pending, name)
            committed = True
            file.update(status='completed', final_path=target, written=file['size'])
            if moved_old:
                await client.delete(backup)
        except BaseException:
            # 重命名可能已经成功但响应丢失，按最终文件摘要恢复，不能误报取消或重复覆盖。
            if self.journal(state, file).exists() and await asyncio.shield(self.recover_commit(state, file)):
                committed = True
                return target
            raise
        finally:
            if not committed:
                try:
                    await asyncio.shield(client.delete(pending))
                except Exception:
                    file['cleanup_path'] = pending
                    logger.warning('群晖上传临时文件待清理：%s', pending, exc_info=True)
        return target

    async def worker(self):
        while True:
            key = await self.queue.get()
            if key is None:
                self.queue.task_done()
                return
            sid, fid = key
            state, file = self.sessions[sid], self.sessions[sid]['files'][fid]
            try:
                if state['status'] != 'receiving' or file['status'] not in {'ready', 'verifying'}:
                    continue
                if file['status'] == 'verifying':
                    file['stage'] = '校验完整文件'
                    if not file.get('sha256'):
                        part = self.part(sid, fid)
                        if file['size'] == 0:
                            await asyncio.to_thread(part.touch, exist_ok=True)
                        receipt = self.receipt(sid, fid)
                        if receipt.exists():
                            file['sha256'] = await asyncio.to_thread(verify_received_file, part, receipt)
                        else:
                            file['sha256'] = await asyncio.to_thread(digest_file, part)
                    self.check_writing(state)
                file.update(status='writing', stage='写入库存', written=0)
                if self.journal(state, file).exists() and await self.recover_commit(state, file):
                    continue
                # 摘要必须先于提交日志落库，重启才能辨认已完成的原子重命名。
                await self.save(state, [file])
                library, _ = await self.resolve_target(state['library_id'], state['target_path'])
                # 只串行化相同目标；不同文件共享三个落地工作槽。
                lock_key = (state['library_id'], state['target_path'], file['relative_path'])
                async with self.locked(self.target_locks, lock_key):
                    relative_path, decision = await self.destination(state, file, library)
                    if decision == 'wait_parent':
                        file['status'] = 'ready'
                        continue
                    if decision == 'conflict':
                        continue
                    if decision == 'skip':
                        file['status'] = 'skipped'
                        continue
                    self.check_writing(state)
                    if file.get('is_directory'):
                        if library.type == 'local':
                            target = await asyncio.to_thread(local_target, library.browse_root_path or library.root_path, str(Path(state['target_path']) / relative_path))
                            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
                        else:
                            await self.ensure_remote_directory(library, str(PurePosixPath(state['target_path']) / relative_path))
                        final = str(Path(state['target_path']) / relative_path) if library.type == 'local' else str(PurePosixPath(state['target_path']) / relative_path)
                    elif library.type == 'local':
                        final_target = str(Path(state['target_path']) / relative_path)
                        await asyncio.to_thread(atomic_json, self.journal(state, file), dict(target=final_target))
                        from .fs_utils import run_file_operation_async
                        final = await run_file_operation_async(install_local, library.browse_root_path or library.root_path,
                            state['target_path'], relative_path, self.part(sid, fid), file['sha256'], decision,
                            lambda: self.check_writing(state), lambda done: file.update(written=done))
                    else:
                        file['stage'] = '写入群晖'
                        final = await self.install_remote(state, file, library, relative_path, decision)
                    file.update(status='completed', stage='完成', written=file['size'], final_path=final, reason='')
                    state.setdefault('_index_paths', set()).add(str(PurePosixPath(relative_path).parts[0]))
            except UploadStopped:
                if file['status'] != 'completed':
                    file['status'] = 'cancelled' if state['status'] == 'cancelled' else 'ready' if file.get('sha256') else 'verifying'
            except FileExistsError as exc:
                file.update(status='conflict', stage='等待冲突', reason=str(exc))
            except Exception as exc:
                # 提交成功后的清理失败不把已落地文件伪报为失败。
                if file['status'] == 'verifying' and isinstance(exc, ValueError):
                    try:
                        checkpoint = await asyncio.to_thread(recover_checkpoint, self.part(sid, fid), self.receipt(sid, fid))
                        file['received'] = checkpoint['offset']
                    except Exception:
                        logger.exception('损坏分块的断点待重新恢复：%s', fid)
                if file['status'] != 'completed' and (self.stopping or state['status'] in {'paused', 'cancelled'}):
                    file['status'] = 'cancelled' if state['status'] == 'cancelled' else 'ready' if file.get('sha256') else 'verifying'
                elif file['status'] != 'completed':
                    file.update(status='failed', reason=str(exc), retryable=True)
                else:
                    file['reason'] = '文件已落地，备份清理失败：' + str(exc)
                logger.warning('浏览器上传文件处理失败：%s', file['relative_path'], exc_info=True)
            finally:
                try:
                    await self.save(state, [file])
                    if file['status'] == 'completed':
                        await asyncio.to_thread(self.journal(state, file).unlink, missing_ok=True)
                        await asyncio.to_thread(self.part(sid, fid).unlink, missing_ok=True)
                except Exception:
                    state['_dirty'].add(fid)
                    logger.exception('上传结果待重新持久化，保留提交日志：%s', fid)
                finally:
                    self.queued.discard((sid, fid))
                    self.queue.task_done()
                    self.finish(state)

    def finish(self, state):
        self.finalize_state(state)
        self.publish(state)

    def finalize_state(self, state):
        if state['status'] == 'receiving':
            state.setdefault('started_at', datetime.now().isoformat())
        self.refresh_metrics(state)
        counts = state.get('_statuses', {})
        if state['status'] == 'receiving' and state['enumerated'] and sum(counts.get(s, 0) for s in FILE_TERMINAL) == len(state['files']):
            state['status'] = 'failed' if counts.get('failed', 0) else 'completed'
        if state['status'] in TERMINAL and not state.get('_restored_terminal'):
            state.setdefault('completed_at', datetime.now().isoformat())

    def publish(self, state):
        if state['status'] in TERMINAL and not state.get('_restored_terminal'):
            state.setdefault('completed_at', datetime.now().isoformat())
        now = time.monotonic()
        publish_state = (state['status'], bool(state.get('_index_paths')))
        if now - state.get('_last_publish', 0) < .75 and state.get('_published_status') == publish_state:
            return
        state['_last_publish'] = now
        state['_published_status'] = publish_state
        changes = state.setdefault('_changes', deque(maxlen=20000))
        revision = state.setdefault('_revision', 0)
        from_cursor = revision
        self.refresh_metrics(state)
        pending = state.setdefault('_publish_pending', set())
        event_files = []
        for fid in pending:
            revision += 1
            changes.append((revision, dict(state['files'][fid])))
            if len(event_files) < 200:
                event_files.append(state['files'][fid])
        pending.clear()
        state['_revision'] = revision
        if state.get('_restored_terminal'):
            return
        # 挂入同一任务模型与事件物化链，但永不进入普通执行队列。
        from .task_engine import Task, TaskType, TaskStatus, get_task_engine
        engine = get_task_engine()
        task = engine.tasks.get(state['id'])
        summary = self.summary(state)
        # 全局事件流仅携带展示字段，不携带上传令牌、校验摘要或内部路径。
        public = {key: summary[key] for key in (
            'id', 'status', 'enumerated', 'total_files', 'total_bytes', 'received_bytes',
            'written_bytes', 'counts', 'index_pending', 'total_entries',
        ) if key in summary}
        signature = (revision, repr(public))
        if signature != state.get('_sse_signature'):
            from .realtime_event_service import broadcast_event
            fields = ('id', 'relative_path', 'size', 'is_directory', 'last_modified',
                      'received', 'written', 'status', 'stage', 'reason')
            delta = [{key: file[key] for key in fields if key in file}
                     for file in event_files]
            cursor = min(revision, from_cursor + 200)
            broadcast_event({'type': 'library.browser-upload.changed', 'payload': {
                **public, 'from_cursor': from_cursor, 'cursor': cursor,
                'has_more': cursor < revision, 'files': delta,
            }})
            state['_sse_signature'] = signature
        if task is None:
            task = Task(TaskType.BROWSER_UPLOAD, state['source_label'], state['target_path'], task_id=state['id'],
                metadata={'source_page': 'library', 'source_action': 'browser_upload', 'task_domain': 'upload'})
            engine._ensure_task_context(task)
            engine.tasks[task.id] = task
        status = {'receiving': TaskStatus.PROCESSING, 'paused': TaskStatus.PAUSED,
                  'completed': TaskStatus.COMPLETED, 'failed': TaskStatus.FAILED, 'cancelled': TaskStatus.CANCELLED}[state['status']]
        with task._set_state_silent():
            task.created_at = datetime.fromisoformat(state['created_at'])
            task.started_at = datetime.fromisoformat(state.get('started_at') or state['created_at'])
            task.completed_at = datetime.fromisoformat(state['completed_at']) if state.get('completed_at') else None
            task.status = status
            task.current_step = '读取目录' if not state['enumerated'] else ('等待冲突' if summary['counts']['conflict'] else '浏览器上传／写入库存')
            if state['status'] in TERMINAL:
                task.current_step = {'completed': '完成', 'failed': '存在失败文件', 'cancelled': '已取消，已完成文件保留'}[state['status']]
            task.progress = 100 if status == TaskStatus.COMPLETED else min(99, int(100 * summary['written_bytes'] / max(1, summary['total_bytes'])))
            task.task_metadata = {**task.task_metadata, 'browser_upload': summary, 'target_path': state['target_path'],
                'upload_runtime': {'phase': 'upload', 'transferred_bytes': summary['written_bytes'],
                    'total_bytes': summary['total_bytes'], 'total_files': summary.get('total_files', 0),
                    'completed_files': summary['counts']['completed']},
                'source_label': state['source_label'], 'library_id': state['library_id'], 'externally_managed': True}
        task.mark_changed('progress')

    @staticmethod
    def audit_key(state):
        return f"browser-upload:{state['id']}:{int(state.get('audit_revision', 0))}:{state['status']}"

    @staticmethod
    def audit_snapshot(state):
        from .task_engine import TaskType, TaskStatus
        return dict(id=state['id'], type=TaskType.BROWSER_UPLOAD,
            status={'completed': TaskStatus.COMPLETED, 'failed': TaskStatus.FAILED, 'cancelled': TaskStatus.CANCELLED}[state['status']],
            current_step=state.get('reason') or '', error_message=state.get('reason') or '',
            source_path=state['source_label'], output_path=state['target_path'], rjcode='',
            is_cancelled=state['status'] == 'cancelled',
            created_at=datetime.fromisoformat(state['created_at']),
            started_at=datetime.fromisoformat(state.get('started_at') or state['created_at']),
            completed_at=datetime.fromisoformat(state['completed_at']) if state.get('completed_at') else None,
            task_metadata={'source_page': 'library', 'source_action': 'browser_upload',
                'browser_upload': state.get('_audit_summary') or {},
                'library_id': state['library_id'], 'target_path': state['target_path']})

    async def maintenance(self):
        while True:
            for state in list(self.sessions.values()):
                try:
                    await self.maintain_session(state)
                except Exception:
                    logger.exception('浏览器上传维护失败，会保留会话并重试：%s', state['id'])
            await asyncio.sleep(1)

    async def maintain_session(self, state):
        if state.get('_restoring'):
            return
        busy = state.get('_receivers') or state.get('_file_operations') or any(sid == state['id'] for sid, _ in self.queued)
        if state['status'] in TERMINAL and not busy and time.time() - state.get('last_activity', time.time()) > RETENTION_SECONDS:
            await self.expire_session(state)
            return
        if state.get('_settled'):
            return
        if state['status'] not in TERMINAL and time.time() - state.get('last_activity', time.time()) > RETENTION_SECONDS and not busy:
            await self.action(state, 'cancel')
            state['reason'] = '会话超过七天无活动，已过期'
        self.refresh_metrics(state)
        for fid in list(state.get('_ready', ())):
            if self.queue.full():
                break
            file = state['files'][fid]
            key = (state['id'], file['id'])
            known = state.get('_known_paths', {})
            if any(known.get(str(p), {}).get('status') in {'ready', 'writing', 'conflict', 'failed'} for p in PurePosixPath(file['relative_path']).parents):
                continue
            if state['status'] == 'receiving' and file['status'] in {'ready', 'verifying'} and key not in self.queued and not self.queue.full():
                self.queued.add(key)
                self.queue.put_nowait(key)
        if time.monotonic() - state['_last_save'] >= 5:
            dirty = state['_dirty']
            state['_dirty'] = set()
            try:
                await self.save(state, [state['files'][fid] for fid in dirty])
            except Exception:
                state['_dirty'].update(dirty)
                raise
            state['_last_save'] = time.monotonic()
            if paths := state.get('_index_paths', set()).copy():
                library = self.library(state['library_id'])
                for path in paths:
                    absolute = str(Path(state['target_path']) / path) if library.type == 'local' else str(PurePosixPath(state['target_path']) / path)
                    await asyncio.to_thread(self.manager._notify_index_self_mutation_upsert_subtree, library, absolute)
                    state['_index_paths'].discard(path)
            idle = not busy
            if state['status'] == 'cancelled' and idle:
                await asyncio.to_thread(self.cleanup_files, state)
            if state['status'] in TERMINAL and idle and not state.get('_index_paths'):
                state['_settled'] = True
        self.publish(state)
        if state.get('_settled') and len(state.get('_changes', ())) > 200:
            state['_changes'] = deque(list(state['_changes'])[-200:], maxlen=200)

    def cleanup_files(self, state):
        for file in state['files'].values():
            if file.get('is_directory'):
                continue
            part = self.part(state['id'], file['id'], create_parent=False)
            for path in (part, part.with_suffix('.commit'), part.with_suffix('.json'), part.with_suffix('.new')):
                path.unlink(missing_ok=True)
        directory = self.root / state['id']
        if directory.exists():
            shutil.rmtree(directory)

    async def expire_session(self, state):
        async with state.setdefault('_save_lock', asyncio.Lock()):
            if state.get('_file_operations') or any(sid == state['id'] for sid, _ in self.queued):
                return
            state['_expiring'] = True
            try:
                await asyncio.to_thread(self.cleanup_files, state)
                def remove():
                    with self.db() as db:
                        db.execute(delete(BrowserUploadFile).where(BrowserUploadFile.session_id == state['id']))
                        db.execute(delete(BrowserUploadSession).where(BrowserUploadSession.id == state['id']))
                        db.commit()
                await asyncio.to_thread(remove)
            except BaseException:
                state.pop('_expiring', None)
                raise
            self.sessions.pop(state['id'], None)
            for mapping in (self.locks, self.checkpoints, self.hashers):
                for key in [key for key in mapping if key[0] == state['id']]:
                    mapping.pop(key, None)
            if not self.sessions:
                self.remote_commit_locks.clear()
                self.remote_commit_verified.clear()

_service = None


def get_browser_upload_service():
    global _service
    if _service is None:
        _service = BrowserUploadService()
    return _service
