"""解压证据、资源取消与恢复持久化的行为回归。"""
import asyncio
import contextlib
import errno
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

import pytest

from app.core.extract_runtime import ArchiveFingerprintCache, AdjustableLimiter, archive_node
from app.core.extract_service import ExtractService, ArchiveInfo
from app.core.filter_recovery_service import FilterRecoveryService
from app.core.task_engine import Task, TaskType


def test_encoding_evidence_expires_when_archive_replaced(tmp_path):
    archive = tmp_path / 'archive'
    archive.write_bytes(b'first')
    cache = ArchiveFingerprintCache()
    cache[str(archive)] = 'gbk'
    assert cache[str(archive)] == 'gbk'
    replacement = tmp_path / 'replacement'
    replacement.write_bytes(b'other')
    os.replace(replacement, archive)
    assert cache.get(str(archive)) is None


def test_mixed_archive_selects_encrypted_entry_only():
    service = ExtractService()
    entries = [{'name': 'plain', 'size': 1, 'encrypted': False},
               {'name': 'encrypted', 'size': 1024, 'encrypted': True}]
    assert service._pick_probe_entry(entries)['name'] == 'encrypted'
    entries[1]['size'] = service.PROBE_ENTRY_MAX_SIZE + 1
    assert service._pick_probe_entry(entries) is None


@pytest.mark.asyncio
async def test_second_resource_queue_cancel_releases_first_slot(monkeypatch):
    service = ExtractService()
    entered = asyncio.Event()
    released = asyncio.Event()
    @contextlib.asynccontextmanager
    async def acquire(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
            yield
        finally:
            released.set()
    budget = SimpleNamespace(snapshot=lambda: {}, acquire=acquire)
    monkeypatch.setattr('app.core.extract_service.get_resource_budget_service', lambda: budget)
    limiter = AdjustableLimiter(1)
    task = SimpleNamespace(task_metadata={})
    async def run():
        async with archive_node(task, 'archive', root=True):
            async with service._acquire_7z_resource_slot(
                semaphore=limiter, budget_resource='archive_inspect', reason='test',
                archive_path='archive', slot_label='测试', slot_limit=1, wait_timeout=None,
            ):
                pytest.fail('资源未就绪不能执行')
    pending = asyncio.create_task(run())
    await entered.wait()
    assert limiter.active == 1
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert released.is_set()
    assert limiter.active == 0
    assert task.task_metadata['extract_timing']['counts'].get('queued') == 0


def test_cross_volume_restore_publishes_only_verified_copy(tmp_path, monkeypatch):
    from app.core import staged_file_move as mover
    service = FilterRecoveryService(str(tmp_path / 'recovery'))
    payload = tmp_path / 'payload'
    content = b'content' * 100
    payload.write_bytes(content)
    target = tmp_path / 'target'
    target.mkdir()
    publish = mover.publish_path
    def cross_volume(source, destination, **kwargs):
        if Path(source) == payload:
            raise OSError(errno.EXDEV, '跨卷')
        return publish(source, destination, **kwargs)
    monkeypatch.setattr(mover, 'publish_path', cross_volume)
    monkeypatch.setattr(mover, '_journal_root', lambda: tmp_path / 'journal')
    output = service._restore_local(payload, {'root': str(target)}, {'restore_relative_path': 'a'})
    assert Path(output).read_bytes() == content
    assert not payload.exists()
    assert not list(target.glob('*.part'))


def test_cross_volume_copy_failure_keeps_payload_and_no_partial_target(tmp_path, monkeypatch):
    from app.core import staged_file_move as mover
    service = FilterRecoveryService(str(tmp_path / 'recovery'))
    payload = tmp_path / 'payload'
    payload.write_bytes(b'content')
    target = tmp_path / 'target'
    target.mkdir()
    monkeypatch.setattr(mover, 'publish_path', Mock(side_effect=OSError(errno.EXDEV, '跨卷')))
    monkeypatch.setattr(mover, '_journal_root', lambda: tmp_path / 'journal')
    def fail(source, destination, **kwargs):
        Path(destination).write_bytes(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr(mover, 'copy_path_exclusive_sync', fail)
    with pytest.raises(OSError, match='disk full'):
        service._restore_local(payload, {'root': str(target)}, {'restore_relative_path': 'a'})
    assert payload.read_bytes() == b'content'
    assert not (target / 'a').exists()
    # 新移动协议保留隐藏暂存及 journal，供恢复工具核对，不发布半文件。
    assert len(list(target.glob('.kikoerumanager-move-*.part'))) == 1
    assert len(list((tmp_path / 'journal').glob('*.json'))) == 1


def test_cross_volume_directory_mutation_never_deletes_source(tmp_path, monkeypatch):
    from app.core import staged_file_move as mover
    service = FilterRecoveryService(str(tmp_path / 'recovery'))
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'abc')
    destination = tmp_path / 'copy'
    monkeypatch.setattr(mover, 'publish_path', Mock(side_effect=OSError(errno.EXDEV, '跨卷')))
    monkeypatch.setattr(mover, '_journal_root', lambda: tmp_path / 'journal')
    copy_path = mover.copy_path_exclusive_sync
    def mutate(incoming, outgoing, **kwargs):
        result = copy_path(incoming, outgoing, **kwargs)
        (source / 'new').write_bytes(b'new')
        return result
    monkeypatch.setattr(mover, 'copy_path_exclusive_sync', mutate)
    with pytest.raises(RuntimeError, match='来源在移动期间变化'):
        service._move_to_recovery(source, destination, expected_size=3)
    assert (source / 'a').read_bytes() == b'abc'
    assert (source / 'new').read_bytes() == b'new'
    assert not destination.exists()


@pytest.mark.asyncio
async def test_complete_validation_rejects_one_missing_entry_among_ten_thousand(tmp_path, monkeypatch):
    service = ExtractService()
    monkeypatch.setattr(service.config.extract, 'verify_after_extract', True)
    entries = [{'name': f'{i}.wav', 'size': 1, 'is_dir': False} for i in range(10001)]
    # 模拟扫描结果，缺失条目位于旧抽样校验无法覆盖的末尾。
    monkeypatch.setattr(service, '_repair_mojibake_relative_path', lambda path: path)
    class Entry:
        def __init__(self, i):
            self.path = str(tmp_path / f'{i}.wav')
        def is_dir(self, **kwargs): return False
        def is_file(self, **kwargs): return True
        def stat(self, **kwargs): return SimpleNamespace(st_size=1)
    @contextlib.contextmanager
    def scan(path):
        yield iter(Entry(i) for i in range(10000))
    monkeypatch.setattr('app.core.extract_service.os.scandir', scan)
    assert not await service._verify_extraction(ArchiveInfo('archive.7z', entries), str(tmp_path))


@pytest.mark.asyncio
async def test_password_evidence_isolated_between_parent_and_siblings():
    from app.core.extract_runtime import candidate_evidence
    task = SimpleNamespace(task_metadata={})
    async with archive_node(task, 'parent', root=True):
        candidate_evidence(' same ', ['手动输入'], content='passed')
        async with archive_node(task, 'first'):
            candidate_evidence(' same ', ['父层成功密码'], content='wrong_password')
        async with archive_node(task, 'second'):
            candidate_evidence(' same ', ['父层成功密码'])
            candidate_evidence(' same ', ['密码库'])
    nodes = task.task_metadata['extract_timing']['nodes']
    evidence = [next(iter(n['password_candidates'].values())) for n in nodes]
    assert evidence[0]['content'] == 'passed'
    assert evidence[1]['content'] == 'wrong_password'
    assert 'content' not in evidence[2]
    assert evidence[2]['sources'] == ['父层成功密码', '密码库']
    assert ' same ' not in str(task.task_metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize('format,password,extensionless', [
    ('zip', '', False), ('zip', 'different', False),
    ('7z', '中文密码', True), ('7z', 'different', True),
])
async def test_real_nested_extraction_checks_final_payload(tmp_path, monkeypatch, format, password, extensionless):
    service = ExtractService()
    executable = service.seven_zip
    if not shutil.which(executable) and not Path(executable).is_file():
        pytest.skip('本机未安装 7-Zip')
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    content = b'actual decoded payload' * 100
    (incoming / 'track.wav').write_bytes(content)
    archive = tmp_path / ('archive.' + format)
    cmd = [executable, 'a', '-t' + format, str(archive), str(incoming / 'track.wav')]
    if password:
        cmd += ['-p' + password]
        if format == '7z':
            cmd += ['-mhe=on']
        elif not password.isascii():
            cmd += ['-mem=AES256']
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True)
    assert result.returncode == 0
    if extensionless:
        archive = archive.rename(tmp_path / 'opaque')
    output = tmp_path / 'output'
    output.mkdir()
    task = Task(task_type=TaskType.EXTRACT, source_path=str(archive))
    # 隔离密码库和资源服务；实际清单、探测、执行及最终校验均使用真实工具。
    monkeypatch.setattr(service, '_get_password_candidates_for_archive', AsyncMock(return_value=[]))
    @contextlib.asynccontextmanager
    async def acquire(*args, **kwargs):
        yield
    monkeypatch.setattr('app.core.extract_service.get_resource_budget_service',
                        lambda: SimpleNamespace(snapshot=lambda: {}, acquire=acquire))
    async with archive_node(task, str(archive), root=True):
        success, used = await service._try_extract_nested_direct(
            str(archive), str(output), parent_password='outer-password', task=task,
            inherited_passwords=[password] if password else [],
        )
    assert success
    assert used == (password or None)
    assert (output / 'track.wav').read_bytes() == content
    assert task.task_metadata['extract_timing']['totals_ms']['execution'] >= 0


@pytest.mark.asyncio
async def test_real_nested_gbk_password_zip_uses_byte_compatible_backend(tmp_path, monkeypatch):
    from tests.test_extract_service import TestExtractService
    service = ExtractService()
    archive = tmp_path / 'opaque'
    TestExtractService().create_gbk_password_zipcrypto_zip_with_plain_entry(
        str(archive), '中文密码', encrypted_name='track.wav', encrypted_payload=b'actual payload',
        plain_name='readme.txt', plain_payload=b'x',
    )
    output = tmp_path / 'output'
    output.mkdir()
    task = Task(task_type=TaskType.EXTRACT, source_path=str(archive))
    monkeypatch.setattr(service, '_get_password_candidates_for_archive', AsyncMock(return_value=[]))
    @contextlib.asynccontextmanager
    async def acquire(*args, **kwargs):
        yield
    monkeypatch.setattr('app.core.extract_service.get_resource_budget_service',
                        lambda: SimpleNamespace(snapshot=lambda: {}, acquire=acquire))
    async with archive_node(task, str(archive), root=True):
        result = await service._try_extract_nested_direct(
            str(archive), str(output), parent_password='outer', task=task,
            inherited_passwords=['中文密码'],
        )
    assert result == (True, '中文密码')
    assert (output / 'track.wav').read_bytes() == b'actual payload'
    assert (output / 'readme.txt').read_bytes() == b'x'


def test_startup_reconciles_interrupted_records_without_removing_unknown_payload(tmp_path, monkeypatch):
    service = FilterRecoveryService(str(tmp_path / 'recovery'))
    source = tmp_path / 'source'
    source.write_bytes(b'kept')
    service.begin_capture('task')
    write_item = service._write_item
    def interrupt(task_id, item):
        if item['recovery_status'] == 'available':
            raise SystemExit('模拟发布后退出')
        write_item(task_id, item)
    monkeypatch.setattr(service, '_write_item', interrupt)
    with pytest.raises(SystemExit):
        service.capture_item('task', str(source), relative_path='source', entry_type='file', size=4)
    unknown = service.recovery_root() / 'unknown' / 'orphan'
    unknown.mkdir(parents=True)
    (unknown / 'file').write_bytes(b'unknown')
    restarted = FilterRecoveryService(str(service.recovery_root()))
    assert restarted.reconcile_all() == {}
    assert restarted.public_summary('task')['available_count'] == 1
    assert (unknown / 'file').read_bytes() == b'unknown'
