"""分块、恢复与原子落地的数据完整性测试。"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.core import browser_upload_storage as storage


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_chunk_idempotence_and_digest_rejection(tmp_path):
    part = tmp_path / 'file.part'
    data = '原始内容'.encode()
    result = storage.receive_chunk(part, 0, data, sha(data), len(data))
    assert result['offset'] == len(data)
    assert storage.receive_chunk(part, 0, data, sha(data), len(data)) == result
    with pytest.raises(ValueError, match='SHA-256'):
        storage.receive_chunk(part, 0, data, '0' * 64, len(data))
    assert part.read_bytes() == data


def test_recovery_discards_unconfirmed_and_corrupt_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    part = tmp_path / 'file.part'
    storage.receive_chunk(part, 0, b'abcd', sha(b'abcd'), 8)
    storage.receive_chunk(part, 4, b'efgh', sha(b'efgh'), 8)
    part.write_bytes(b'abcdFAILunconfirmed')
    checkpoint = storage.recover_checkpoint(part)
    assert checkpoint['offset'] == 4
    assert part.read_bytes() == b'abcd'
    storage.receive_chunk(part, 4, b'efgh', sha(b'efgh'), 8)
    assert part.read_bytes() == b'abcdefgh'


def test_no_space_preserves_checkpoint(tmp_path, monkeypatch):
    part = tmp_path / 'file.part'
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(OSError, match='空间不足'):
        storage.receive_chunk(part, 0, b'abc', sha(b'abc'), 3)
    assert not part.exists()


def test_receipts_append_and_repair_torn_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    part = tmp_path / 'file.part'
    checkpoint = {'offset': 0, 'chunks': []}
    sizes = []
    for offset in range(0, 400, 4):
        storage.receive_chunk(part, offset, b'abcd', sha(b'abcd'), 400, checkpoint=checkpoint)
        sizes.append(part.with_suffix('.json').stat().st_size)
    assert max(b - a for a, b in zip(sizes, sizes[1:])) < 150
    with part.with_suffix('.json').open('ab') as output:
        output.write(b'{"offset":400')
    assert storage.read_checkpoint(part.with_suffix('.json')) == checkpoint
    assert part.with_suffix('.json').stat().st_size == sizes[-1]


def test_missing_part_resets_stale_receipt_before_restart(tmp_path):
    part = tmp_path / 'file.part'
    storage.receive_chunk(part, 0, b'old', sha(b'old'), 3)
    part.unlink()
    assert storage.recover_checkpoint(part, full=False)['offset'] == 0
    storage.receive_chunk(part, 0, b'new', sha(b'new'), 3)
    assert storage.verify_received_file(part, part.with_suffix('.json')) == sha(b'new')


def test_complete_json_without_newline_is_not_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    part = tmp_path / 'file.part'
    storage.receive_chunk(part, 0, b'abcd', sha(b'abcd'), 8)
    receipt = part.with_suffix('.json')
    with receipt.open('ab') as output:
        output.write(json.dumps({'offset': 4, 'size': 4, 'sha256': sha(b'efgh')}).encode())
    assert storage.read_checkpoint(receipt)['offset'] == 4
    storage.receive_chunk(part, 4, b'efgh', sha(b'efgh'), 8)
    assert storage.read_checkpoint(receipt)['offset'] == 8
    assert storage.verify_received_file(part, receipt) == sha(b'abcdefgh')


def test_fast_checkpoint_hashes_only_tail_and_keeps_full_validation_available(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    part = tmp_path / 'file.part'
    for offset in range(0, 20, 4):
        storage.receive_chunk(part, offset, b'abcd', sha(b'abcd'), 24)
    original = storage.hashlib.sha256
    reads = []
    def digest(data=b''):
        reads.append(len(data))
        return original(data)
    monkeypatch.setattr(storage.hashlib, 'sha256', digest)
    assert storage.recover_checkpoint(part, full=False)['offset'] == 20
    assert reads == [4]
    with part.open('r+b') as output:
        output.write(b'FAIL')
    assert storage.recover_checkpoint(part)['offset'] == 0


def test_legacy_receipt_migrates_once_and_incremental_hash_ignores_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'CHUNK_SIZE', 4)
    part = tmp_path / 'file.part'
    part.write_bytes(b'abcd')
    storage.atomic_json(part.with_suffix('.json'), {'offset': 4, 'chunks': [
        {'offset': 0, 'size': 4, 'sha256': sha(b'abcd')}]})
    hasher = {'offset': 4, 'digest': hashlib.sha256(b'abcd')}
    checkpoint = storage.receive_chunk(part, 4, b'efgh', sha(b'efgh'), 8, hasher=hasher)
    storage.receive_chunk(part, 4, b'efgh', sha(b'efgh'), 8, checkpoint=checkpoint, hasher=hasher)
    assert storage.read_checkpoint(part.with_suffix('.json')) == checkpoint
    assert hasher['offset'] == 8
    assert hasher['digest'].hexdigest() == sha(b'abcdefgh')


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../b', 'a\\b', 'CON.txt', 'a:b', 'a//b'])
def test_reject_path_escape(name):
    with pytest.raises(ValueError):
        storage.relative_name(name)


def test_atomic_replace_and_cancel_retains_old_file(tmp_path):
    source = tmp_path / 'source.part'
    source.write_bytes(b'new data')
    target = tmp_path / 'library'
    target.mkdir()
    destination = target / 'file.bin'
    destination.write_bytes(b'old data')

    def cancelled():
        raise InterruptedError('取消')

    with pytest.raises(InterruptedError):
        storage.install_local(target, target, 'file.bin', source, sha(b'new data'), 'replace', cancelled, lambda _: None)
    assert destination.read_bytes() == b'old data'
    assert not list(target.glob('*.part'))
    with pytest.raises(FileExistsError):
        storage.install_local(target, target, 'file.bin', source, sha(b'new data'), 'create', lambda: None, lambda _: None)
    storage.install_local(target, target, 'file.bin', source, sha(b'new data'), 'replace', lambda: None, lambda _: None)
    assert destination.read_bytes() == b'new data'


def test_symlink_target_is_rejected(tmp_path):
    root = tmp_path / 'library'
    root.mkdir()
    try:
        (root / 'link').symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip('系统未授予创建符号链接权限')
    with pytest.raises(PermissionError):
        storage.local_target(root, str(root / 'link' / 'escape'))
