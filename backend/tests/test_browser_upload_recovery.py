"""上传重启、跨卷回执和事务审计的回归验证。"""
import errno
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.browser_upload_service import BrowserUploadService
from app.models.database import ActivityLog, BrowserUploadSession
from tests.postgres_test_utils import truncate_all_tables


@pytest.fixture
def upload_service(db_engine, tmp_path, monkeypatch):
    truncate_all_tables(db_engine)
    root = tmp_path / 'library'
    root.mkdir()
    library = SimpleNamespace(id='test', name='测试库存', type='local', enabled=True,
        writable=True, root_path=str(root), browse_root_path=str(root))
    manager = SimpleNamespace(get_library_definition=lambda _: library,
        _notify_index_self_mutation_upsert_subtree=lambda *args: None)
    service = BrowserUploadService(sessionmaker(bind=db_engine), manager, tmp_path / 'temp')
    monkeypatch.setattr(service, 'publish', lambda state: None)
    return service


def receipt_paths(service):
    legacy = service.root.parent / 'old' / 'receipt.json'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"offset":5,"chunks":[]}')
    service.part = lambda sid, fid: legacy.with_suffix('.part')
    return legacy, service.root / 'session' / 'file.json'


def test_receipt_never_renames_across_volumes(tmp_path, monkeypatch):
    service = BrowserUploadService(manager=SimpleNamespace(), temp_root=tmp_path)
    legacy, target = receipt_paths(service)
    original = Path.replace
    def replace(path, destination):
        if path == legacy:
            raise OSError(errno.EXDEV, '跨卷')
        return original(path, destination)
    monkeypatch.setattr(Path, 'replace', replace)
    assert service.receipt('session', 'file') == target
    assert target.read_bytes() == b'{"offset":5,"chunks":[]}'
    assert not legacy.exists()
    assert service.receipt('session', 'file') == target


def test_receipt_failed_publication_retains_source(tmp_path, monkeypatch):
    import app.core.browser_upload_service as module
    service = BrowserUploadService(manager=SimpleNamespace(), temp_root=tmp_path)
    legacy, target = receipt_paths(service)
    def fail(*args):
        raise OSError('目标卷写入失败')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError, match='写入失败'):
        service.receipt('session', 'file')
    assert legacy.exists()
    assert not target.exists()
    assert not list(target.parent.glob('*.tmp'))


def test_receipt_conflict_retains_both_versions(tmp_path):
    service = BrowserUploadService(manager=SimpleNamespace(), temp_root=tmp_path)
    legacy, target = receipt_paths(service)
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"offset":8,"chunks":[]}')
    with pytest.raises(OSError, match='不一致'):
        service.receipt('session', 'file')
    assert legacy.exists()
    assert target.read_bytes() == b'{"offset":8,"chunks":[]}'


@pytest.mark.asyncio
async def test_terminal_audit_is_atomic_idempotent_and_restart_silent(upload_service, monkeypatch):
    service = upload_service
    created = await service.create('test', '', '文件.zip')
    state = service.sessions[created['id']]
    state['enumerated'] = True
    await service.save(state)
    await service.save(state)
    with service.db() as db:
        rows = db.scalars(select(ActivityLog).where(ActivityLog.task_id == state['id'])).all()
        assert len(rows) == 1
        assert rows[0].category == 'upload'
        assert rows[0].event_key == service.audit_key(state)
        assert 'archive_input' not in rows[0].detail
        assert rows[0].created_at == datetime.fromisoformat(state['completed_at'])
        assert db.get(BrowserUploadSession, state['id']).state['logged_event_key'] == rows[0].event_key
    restarted = BrowserUploadService(service.db, service.manager, service.root.parent)
    from app.core import task_engine
    def unexpected():
        raise AssertionError('历史终态不能重新创建引擎任务')
    monkeypatch.setattr(task_engine, 'get_task_engine', unexpected)
    await restarted.start()
    await restarted.recovery_task
    try:
        restored = restarted.sessions[state['id']]
        assert restored['_restored_terminal']
        restarted.publish(restored)
        await restarted.save(restored)
        with service.db() as db:
            assert len(db.scalars(select(ActivityLog)).all()) == 1
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_retry_records_new_attempt_without_replaying_old_result(upload_service):
    service = upload_service
    created = await service.create('test', '', '重试文件')
    state = service.sessions[created['id']]
    entries = await service.manifest(state, [dict(relative_path='file.bin', size=1,
        last_modified=0, is_directory=False)], True)
    file = state['files'][entries[0]['id']]
    await service.action(state, 'receive_failed', file['id'], reason='断网')
    failed_key = service.audit_key(state)
    await service.action(state, 'retry', file['id'])
    assert state['audit_revision'] == 1
    assert 'completed_at' not in state
    file.update(status='completed', written=1, received=1)
    await service.save(state, [file])
    await service.save(state, [file])
    with service.db() as db:
        rows = db.scalars(select(ActivityLog).where(ActivityLog.task_id == state['id'])).all()
        assert {row.event_key for row in rows} == {failed_key, service.audit_key(state)}
        assert {row.status for row in rows} == {'failed', 'success'}


@pytest.mark.asyncio
async def test_failed_audit_rollback_retries_with_same_key(upload_service, monkeypatch):
    service = upload_service
    created = await service.create('test', '', '失败文件')
    state = service.sessions[created['id']]
    state.update(status='failed')
    from app.core import activity_log_service
    build = activity_log_service._build_and_write_task_lifecycle_log
    def fail(*args, **kwargs):
        build(*args, **kwargs)
        raise RuntimeError('模拟事务中断')
    monkeypatch.setattr(activity_log_service, '_build_and_write_task_lifecycle_log', fail)
    with pytest.raises(RuntimeError, match='事务中断'):
        await service.save(state)
    with service.db() as db:
        assert not db.scalars(select(ActivityLog)).all()
        assert db.get(BrowserUploadSession, state['id']).state['status'] == 'receiving'
    monkeypatch.setattr(activity_log_service, '_build_and_write_task_lifecycle_log', build)
    await service.save(state)
    await service.save(state)
    with service.db() as db:
        assert len(db.scalars(select(ActivityLog)).all()) == 1


@pytest.mark.asyncio
async def test_legacy_terminal_recovery_does_not_replay(upload_service, monkeypatch):
    service = upload_service
    created = await service.create('test', '', '历史文件')
    with service.db() as db:
        row = db.get(BrowserUploadSession, created['id'])
        row.state = {k: v for k, v in row.state.items() if k != 'audit_revision'}
        row.state = {**row.state, 'status': 'completed', 'enumerated': True}
        db.commit()
    restarted = BrowserUploadService(service.db, service.manager, service.root.parent)
    from app.core import task_engine
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: pytest.fail('历史任务重放'))
    await restarted.start()
    await restarted.recovery_task
    try:
        await restarted.maintain_session(restarted.sessions[created['id']])
        with service.db() as db:
            assert not db.scalars(select(ActivityLog)).all()
    finally:
        await restarted.stop()
