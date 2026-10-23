"""使用真实 PostgreSQL 验证会话恢复、提交和冲突，不触发扫描或普通任务执行器。"""
import asyncio
import hashlib
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
            ready = [f for f in state['files'].values() if f['status'] == 'ready']
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
    library, client = remote_service(service)
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
