"""使用真实 PostgreSQL 验证会话恢复、提交和冲突，不触发扫描或普通任务执行器。"""
import asyncio
import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.browser_upload_service import BrowserUploadService
from app.core.browser_upload_storage import CHUNK_SIZE, receive_chunk
from tests.postgres_test_utils import truncate_all_tables


@pytest.fixture
def setup_upload(db_engine, tmp_path, monkeypatch):
    truncate_all_tables(db_engine)
    root = tmp_path / 'library'
    root.mkdir()
    library = SimpleNamespace(id='test', name='测试库存', type='local', enabled=True,
        writable=True, root_path=str(root), browse_root_path=str(root))
    manager = SimpleNamespace(get_library_definition=lambda _: library,
        _notify_index_self_mutation_upsert_subtree=lambda *args: None)
    monkeypatch.setattr(BrowserUploadService, 'publish', lambda *args: None)
    factory = sessionmaker(bind=db_engine)
    return lambda: BrowserUploadService(factory, manager, tmp_path / 'temp'), root


async def prepare(service, path='source/file.bin', data=b'hello', finished=True):
    created = await service.create('test', '', '来源')
    state = service.get(created['id'], created['token'])
    items = await service.manifest(state, [dict(relative_path=path, size=len(data),
        last_modified=42, is_directory=False)], finished)
    return state, state['files'][items[0]['id']]


async def drain(service, state):
    # 按父目录先后执行，准确观察持久化后的提交状态。
    worker = asyncio.create_task(service.worker())
    try:
        for _ in range(20):
            ready = [f for f in state['files'].values() if f['status'] in {'ready', 'verifying'}]
            if not ready:
                break
            for file in ready:
                await service.queue.put((state['id'], file['id']))
                await service.queue.join()
            await asyncio.sleep(0)
    finally:
        await service.queue.put(None)
        await worker


@pytest.mark.asyncio
async def test_completed_chunk_can_repeat_after_part_removed(setup_upload):
    factory, root = setup_upload
    service = factory()
    data = b'hello'
    state, file = await prepare(service, data=data)
    digest = hashlib.sha256(data).hexdigest()
    await service.chunk(state, file, 0, data, digest)
    await drain(service, state)
    assert file['status'] == 'completed'
    assert not service.part(state['id'], file['id']).exists()
    assert (root / 'source/file.bin').read_bytes() == data
    assert await service.chunk(state, file, 0, data, digest) == {'offset': len(data)}
    with pytest.raises(ValueError, match='不一致'):
        await service.chunk(state, file, 0, b'xxxxx', digest)


@pytest.mark.asyncio
async def test_parent_type_conflict_keep_both_propagates_to_child(setup_upload):
    factory, root = setup_upload
    (root / 'source').write_bytes('原文件'.encode())
    service = factory()
    state, file = await prepare(service)
    await service.chunk(state, file, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    await drain(service, state)
    parent = next(f for f in state['files'].values() if f['relative_path'] == 'source')
    assert parent['status'] == 'conflict'
    assert file['status'] == 'ready'
    with pytest.raises(ValueError, match='类型冲突'):
        await service.action(state, 'conflict', parent['id'], 'replace')
    await service.action(state, 'conflict', parent['id'], 'keep_both')
    await drain(service, state)
    assert file['status'] == 'completed'
    assert (root / 'source').read_bytes() == '原文件'.encode()
    assert Path(file['final_path']).parent.name.startswith('source (')
    assert Path(file['final_path']).read_bytes() == b'hello'


@pytest.mark.asyncio
async def test_restart_finishes_received_file_without_browser_complete(setup_upload):
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service)
    # 模拟块回执已 fsync，PG 中 received/sha256 尚未来得及更新就重启。
    part = service.part(state['id'], file['id'])
    receive_chunk(part, 0, b'hello', hashlib.sha256(b'hello').hexdigest(), 5)
    restarted = factory()
    await restarted.start()
    await restarted.recovery_task
    try:
        restored = restarted.sessions[state['id']]
        for _ in range(100):
            if restored['files'][file['id']]['status'] == 'completed':
                break
            await asyncio.sleep(.05)
        assert restored['files'][file['id']]['status'] == 'completed'
        assert (root / 'source/file.bin').read_bytes() == b'hello'
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_single_retry_retains_completed_sibling(setup_upload):
    factory, root = setup_upload
    service = factory()
    state, first = await prepare(service, path='one.bin', finished=False)
    await service.chunk(state, first, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    await drain(service, state)
    items = await service.manifest(state, [dict(relative_path='two.bin', size=5,
        last_modified=42, is_directory=False)], True)
    second = state['files'][items[0]['id']]
    await service.action(state, 'receive_failed', second['id'], reason='网络中断')
    assert state['status'] == 'failed'
    await service.action(state, 'retry', second['id'])
    assert first['status'] == 'completed'
    await service.chunk(state, second, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    await drain(service, state)
    assert state['status'] == 'completed'
    assert service.summary(state)['counts']['completed'] == 2


@pytest.mark.asyncio
async def test_restart_restores_empty_file_without_browser_complete(setup_upload):
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service, path='empty.bin', data=b'')
    restarted = factory()
    await restarted.start()
    try:
        await restarted.recovery_task
        restored = restarted.sessions[state['id']]
        for _ in range(100):
            if restored['files'][file['id']]['status'] == 'completed':
                break
            await asyncio.sleep(.05)
        assert restored['files'][file['id']]['status'] == 'completed'
        assert (root / 'empty.bin').read_bytes() == b''
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_restart_preserves_received_part_before_atomic_commit(setup_upload):
    from app.core.browser_upload_storage import atomic_json
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    await service.chunk(state, file, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    file['status'] = 'writing'
    await service.save(state, [file])
    atomic_json(service.journal(state, file), {'target': str(root / 'file.bin')})
    restarted = factory()
    await restarted.start()
    try:
        await restarted.recovery_task
        restored = restarted.sessions[state['id']]
        for _ in range(100):
            if restored['files'][file['id']]['status'] == 'completed':
                break
            await asyncio.sleep(.05)
        assert restored['files'][file['id']]['status'] == 'completed'
        assert (root / 'file.bin').read_bytes() == b'hello'
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_background_hash_is_durable_before_install(setup_upload, monkeypatch):
    from app.models.database import BrowserUploadFile
    from app.core import browser_upload_service as module
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    await service.chunk(state, file, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    install = module.install_local
    checked = []
    def verify(*args):
        with service.db() as db:
            row = db.get(BrowserUploadFile, (state['id'], file['id']))
            assert row.state['sha256'] == hashlib.sha256(b'hello').hexdigest()
            assert row.state['status'] == 'writing'
            checked.append(True)
        return install(*args)
    monkeypatch.setattr(module, 'install_local', verify)
    await drain(service, state)
    assert checked == [True] and file['status'] == 'completed'


@pytest.mark.asyncio
async def test_cancel_retains_committed_and_stops_pending(setup_upload):
    factory, root = setup_upload
    service = factory()
    state, first = await prepare(service, path='one.bin', finished=False)
    await service.chunk(state, first, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    await drain(service, state)
    items = await service.manifest(state, [dict(relative_path='two.bin', size=5,
        last_modified=42, is_directory=False)], True)
    second = state['files'][items[0]['id']]
    await service.action(state, 'cancel')
    assert first['status'] == 'completed'
    assert second['status'] == 'cancelled'
    assert (root / 'one.bin').read_bytes() == b'hello'
    assert not (root / 'two.bin').exists()


@pytest.mark.asyncio
async def test_last_chunk_and_complete_never_read_whole_file(setup_upload, monkeypatch):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    from app.core import browser_upload_service as module
    monkeypatch.setattr(module, 'digest_file', lambda *_: pytest.fail('请求内不应读取整文件'))
    assert await asyncio.wait_for(service.chunk(state, file, 0, b'hello', hashlib.sha256(b'hello').hexdigest()), 1) == {'offset': 5}
    assert file['status'] == 'verifying'
    assert file['sha256'] == hashlib.sha256(b'hello').hexdigest()
    assert (await service.complete_file(state, file))['status'] == 'verifying'
    await service.action(state, 'receive_failed', file['id'], reason='最后一块响应丢失')
    assert file['status'] == 'verifying'
    response = await service.action(state, 'retry', file['id'])
    assert response['changed_files'][0]['status'] == 'verifying'
    await drain(service, state)
    assert file['status'] == 'completed'


@pytest.mark.asyncio
async def test_slow_background_digest_does_not_hold_receive_slot_or_file_lock(setup_upload, monkeypatch):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    part = service.part(state['id'], file['id'])
    part.write_bytes(b'hello')
    file['received'] = 5
    await service.complete_file(state, file)
    entered, release = threading.Event(), threading.Event()
    def slow_digest(_):
        entered.set()
        assert release.wait(5)
        return hashlib.sha256(b'hello').hexdigest()
    from app.core import browser_upload_service as module
    monkeypatch.setattr(module, 'digest_file', slow_digest)
    worker = asyncio.create_task(service.worker())
    service.queued.add((state['id'], file['id']))
    await service.queue.put((state['id'], file['id']))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.wait_for(service.action(state, 'receive_failed', file['id']), 1)
        assert file['status'] == 'verifying'
        assert not any(lock.locked() for lock in service.locks.values())
        assert service.receive_slots._value == 3
    finally:
        release.set()
        await service.queue.join()
        await service.queue.put(None)
        await worker
    assert file['status'] == 'completed'


@pytest.mark.asyncio
async def test_retry_batch_persists_only_affected_rows(setup_upload, monkeypatch):
    factory, _ = setup_upload
    service = factory()
    state, first = await prepare(service, path='one.bin', finished=False)
    items = await service.manifest(state, [dict(relative_path=f'{i}.bin', size=1, last_modified=0, is_directory=False) for i in range(100)])
    failed = [state['files'][f['id']] for f in items[:20]]
    for file in failed:
        file['status'] = 'failed'
    await service.save(state, failed)
    persisted = []
    original = service._persist
    def persist(snapshot, files):
        persisted.append([file['id'] for file in files])
        original(snapshot, files)
    monkeypatch.setattr(service, '_persist', persist)
    await service.action(state, 'retry', file_ids=[f['id'] for f in failed])
    assert persisted == [[f['id'] for f in failed]]
    await service.action(state, 'receive_failed', first['id'])
    assert persisted[-1] == [first['id']]


@pytest.mark.asyncio
async def test_cancel_cleans_adjacent_part_and_expiry_removes_records_only(setup_upload):
    from app.models.database import BrowserUploadSession, BrowserUploadFile, ActivityLog
    from sqlalchemy import select
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin', data=b'x' * (CHUNK_SIZE + 1))
    data = b'x' * CHUNK_SIZE
    await service.chunk(state, file, 0, data, hashlib.sha256(data).hexdigest())
    part = service.part(state['id'], file['id'])
    assert part.parent == root and part.exists()
    (root / 'keep.bin').write_bytes('保留'.encode())
    await service.action(state, 'cancel')
    state['_last_save'] = 0
    await service.maintain_session(state)
    assert not part.exists()
    assert not (service.root / state['id']).exists()
    state['last_activity'] = time.time() - 8 * 86400
    await service.maintain_session(state)
    assert state['id'] not in service.sessions
    assert not service.locks and not service.checkpoints and not service.hashers
    with service.db() as db:
        assert db.get(BrowserUploadSession, state['id']) is None
        assert not db.scalars(select(BrowserUploadFile)).all()
        assert len(db.scalars(select(ActivityLog)).all()) == 1
    assert (root / 'keep.bin').read_bytes() == '保留'.encode()


@pytest.mark.asyncio
async def test_start_returns_before_database_recovery_and_missing_session_is_temporary(setup_upload, monkeypatch):
    from app.core.browser_upload_service import UploadRestoring
    factory, _ = setup_upload
    service = factory()
    release = asyncio.Event()
    async def restore():
        await release.wait()
    monkeypatch.setattr(service, '_restore', restore)
    await asyncio.wait_for(service.start(), 1)
    try:
        assert service.recovering
        with pytest.raises(UploadRestoring):
            service.get('not-loaded', 'token')
    finally:
        release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_summary_and_maintenance_do_not_rescan_all_files(setup_upload):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    class NoScan(dict):
        def values(self):
            raise AssertionError('热路径不应重新扫描清单')
    state['files'] = NoScan(state['files'])
    assert service.summary(state)['total_files'] == 1
    await service.maintain_session(state)


@pytest.mark.asyncio
async def test_failed_session_accepts_original_manifest_before_batch_retry(setup_upload):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    await service.action(state, 'receive_failed', file['id'])
    assert state['status'] == 'failed'
    entries = [dict(relative_path='file.bin', size=5, last_modified=42, is_directory=False)]
    assert (await service.manifest(state, entries))[0]['id'] == file['id']
    with pytest.raises(ValueError, match='不能添加新文件'):
        await service.manifest(state, [{**entries[0], 'relative_path': 'other.bin'}])
    await service.action(state, 'retry', file_ids=[file['id']])
    assert state['status'] == file['status'] == 'receiving'


@pytest.mark.asyncio
async def test_bad_receipt_does_not_block_other_files_on_restart(setup_upload):
    factory, _ = setup_upload
    service = factory()
    state, first = await prepare(service, path='one.bin', finished=False)
    items = await service.manifest(state, [dict(relative_path='two.bin', size=5, last_modified=42, is_directory=False)], True)
    service.part(state['id'], first['id']).write_bytes(b'hello')
    service.receipt(state['id'], first['id']).write_text('broken', encoding='utf-8')
    restored = factory()
    await restored.start()
    try:
        await restored.recovery_task
        files = restored.sessions[state['id']]['files']
        assert files[first['id']]['status'] == 'failed'
        assert files[items[0]['id']]['status'] == 'receiving'
        assert not restored.sessions[state['id']]['_restoring']
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_locks_survive_waiters_and_release_after_last_user(setup_upload):
    factory, _ = setup_upload
    service = factory()
    key, order = ('session', 'file'), []
    async with service.locked(service.locks, key):
        original = service.locks[key]
        async def waiter():
            async with service.locked(service.locks, key):
                assert service.locks[key] is original
                order.append('waiting')
        pending = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert service.lock_users[original] == 2
    assert service.locks[key] is original
    await pending
    assert order == ['waiting']
    assert not service.locks and not service.lock_users


@pytest.mark.asyncio
async def test_cleanup_does_not_create_missing_target_directories(setup_upload):
    factory, root = setup_upload
    service = factory()
    state, _ = await prepare(service)
    service.cleanup_files(state)
    assert not (root / 'source').exists()


@pytest.mark.asyncio
async def test_background_validation_rewinds_corrupt_prefix_before_retry(setup_upload, monkeypatch):
    from app.core import browser_upload_storage as storage
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin', data=b'abcdefgh')
    part, receipt = service.part(state['id'], file['id']), service.receipt(state['id'], file['id'])
    receive_chunk(part, 0, b'abcd', hashlib.sha256(b'abcd').hexdigest(), 8, receipt)
    receive_chunk(part, 4, b'efgh', hashlib.sha256(b'efgh').hexdigest(), 8, receipt)
    with part.open('r+b') as output:
        output.write(b'FAIL')
    file['received'] = 8
    await service.complete_file(state, file)
    await drain(service, state)
    assert file['status'] == 'failed' and file['received'] == 0
    assert not (root / 'file.bin').exists()
    await service.action(state, 'retry', file['id'])
    assert file['status'] == 'receiving'


@pytest.mark.asyncio
async def test_receipt_fsync_failure_reloads_checkpoint_before_chunk_retry(setup_upload, monkeypatch):
    from app.core import browser_upload_storage as storage
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    factory, root = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin', data=b'abcdefgh')
    receipt = service.receipt(state['id'], file['id'])
    storage.write_checkpoint(receipt, {'offset': 0, 'chunks': []})
    original = storage.os.fsync
    calls = 0
    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('模拟回执 fsync 失败')
        return original(fd)
    monkeypatch.setattr(storage.os, 'fsync', fsync)
    digest = hashlib.sha256(b'abcd').hexdigest()
    with pytest.raises(OSError, match='fsync'):
        await service.chunk(state, file, 0, b'abcd', digest)
    assert not service.checkpoints and not service.hashers
    assert await service.chunk(state, file, 0, b'abcd', digest) == {'offset': 4}
    await service.chunk(state, file, 4, b'efgh', hashlib.sha256(b'efgh').hexdigest())
    assert storage.read_checkpoint(receipt)['offset'] == 8
    await drain(service, state)
    assert (root / 'file.bin').read_bytes() == b'abcdefgh'


@pytest.mark.asyncio
async def test_expiry_rechecks_inflight_operations_after_waiting_for_save(setup_upload):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    async with state['_save_lock']:
        expiry = asyncio.create_task(service.expire_session(state))
        await asyncio.sleep(0)
        state['_file_operations'] = 1
    await expiry
    assert state['id'] in service.sessions and not state.get('_expiring')
    state['_file_operations'] = 0


class RemoteFiles:
    def __init__(self):
        self.files = {}
        self.lose_response = False
        self.overwrite = False

    async def stat(self, path):
        return {'files': [{'isdir': path == '/library', 'additional': {'real_path': '/volume1' + path}}]}

    async def upload_file(self, parent, source, remote_name, **kwargs):
        self.files[parent + '/' + remote_name] = Path(source).read_bytes()

    async def rename(self, source, name):
        target = str(Path(source).parent).replace('\\', '/') + '/' + name
        if target in self.files and not self.overwrite:
            raise FileExistsError(target)
        self.files[target] = self.files.pop(source)
        if self.lose_response and name == 'file.bin':
            self.lose_response = False
            raise ConnectionError('重命名响应丢失')

    async def delete(self, path):
        self.files.pop(path, None)

    async def stream_download(self, path):
        yield self.files[path]


def remote_service(service):
    service.root.mkdir(parents=True, exist_ok=True)
    client = RemoteFiles()
    library = SimpleNamespace(id='remote', type='synology_filestation', root_path='/library',
        browse_root_path='/library', synology=None)
    service.manager.get_cached_synology_client = lambda _: client
    service.manager._first_remote_info_item = lambda response: response['files'][0]
    async def listing(*args):
        return [{'name': key.rsplit('/', 1)[1]} for key in client.files]
    async def verify(*args, **kwargs):
        assert len(client.files[kwargs['remote_path']]) == kwargs['expected_size']
    service.manager._list_remote_directory = listing
    service.manager._verify_uploaded_remote_file = verify
    service.library = lambda _: library
    return library, client


@pytest.mark.asyncio
async def test_remote_commit_lost_response_keeps_final_and_removes_backup(setup_upload):
    factory, _ = setup_upload
    service = factory()
    state, file = await prepare(service, path='file.bin')
    await service.chunk(state, file, 0, b'hello', hashlib.sha256(b'hello').hexdigest())
    staged = service.part(state['id'], file['id'])
    library, client = remote_service(service)
    # 远程库存接收文件位于暂存盘；模拟器切库时同步迁移测试分块。
    staged.replace(service.part(state['id'], file['id']))
    state['target_path'] = '/library'
    client.files['/library/file.bin'] = b'old'
    client.lose_response = True
    assert await service.install_remote(state, file, library, 'file.bin', 'replace') == '/library/file.bin'
    assert file['status'] == 'completed'
    assert client.files == {'/library/file.bin': b'hello'}


@pytest.mark.asyncio
async def test_remote_probe_rejects_destructive_rename(setup_upload):
    factory, _ = setup_upload
    service = factory()
    library, client = remote_service(service)
    client.overwrite = True
    with pytest.raises(RuntimeError, match='覆盖'):
        await service.verify_remote_commit(library, '/library')
    assert not client.files


@pytest.mark.asyncio
async def test_remote_rejects_symlink_real_path(setup_upload):
    factory, _ = setup_upload
    service = factory()
    library, client = remote_service(service)
    original = client.stat
    async def linked(path):
        if path.endswith('/linked'):
            return {'files': [{'isdir': True, 'additional': {'real_path': '/volume2/outside'}}]}
        return await original(path)
    client.stat = linked
    with pytest.raises(PermissionError, match='链接'):
        await service.validate_remote_path(library, '/library/linked')
