"""监听缓存只适用于同一代成功源，失败和替换文件必须可重扫。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import watcher as watcher_module
from app.core.task_engine import Task, TaskStatus, TaskType
from app.core.input_stability import observe_sources


def test_processed_cache_expires_after_source_replacement(tmp_path):
    watcher = watcher_module.FolderWatcher()
    path = tmp_path / "work.zip"
    path.write_bytes(b"first")
    watcher._mark_file_processed(str(path))
    assert str(path) in watcher._get_excluded_paths(str(path))
    path.unlink()
    path.write_bytes(b"replacement")
    assert not watcher._is_file_processed(str(path))
    assert str(path) not in watcher._processed_fingerprints
    assert str(path) not in watcher._get_excluded_paths(str(path))


def test_processed_cache_keeps_verified_generation_during_replacement(tmp_path):
    watcher = watcher_module.FolderWatcher()
    path = tmp_path / "work.zip"
    path.write_bytes(b"first")
    verified = watcher._source_fingerprint(str(path))
    path.write_bytes(b"replacement")
    watcher._mark_file_processed(str(path), verified)
    assert not watcher._is_file_processed(str(path))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.WAITING_RETRY])
async def test_failed_or_unsettled_task_does_not_freeze_source(tmp_path, monkeypatch, status):
    watcher = watcher_module.FolderWatcher()
    source = tmp_path / "work.zip"
    source.write_bytes(b"sample")
    task = Task(TaskType.AUTO_PROCESS, str(source), status=status)
    monkeypatch.setattr(watcher, "_submit_input", AsyncMock(return_value=task))
    monkeypatch.setattr(watcher, "_broadcast_status", lambda *_: None)
    monkeypatch.setattr(
        watcher_module, "get_config",
        lambda: SimpleNamespace(watcher=SimpleNamespace(delete_after_process=False)),
    )
    await watcher._process_file(str(source))
    assert not watcher._is_file_processed(str(source))


@pytest.mark.asyncio
async def test_replaced_companion_is_preserved_after_source_rename(tmp_path, monkeypatch):
    watcher = watcher_module.FolderWatcher()
    old = tmp_path / "39.RJ123456.part1.rar"
    main = tmp_path / "RJ123456.part1.rar"
    companion = tmp_path / "RJ123456.part2.rar"
    old.write_bytes(b"main")
    companion.write_bytes(b"old member")

    async def submit(path):
        old.rename(main)
        members = [str(main), str(companion)]
        evidence, _ = observe_sources(members, {}, checks=1, interval=0.1, needs_stability=False)
        task = Task(TaskType.AUTO_PROCESS, str(main), status=TaskStatus.COMPLETED, metadata={
            "candidate_id": "scan-candidate", "input_members": members, "input_stability": evidence,
        })
        companion.write_bytes(b"replacement member")
        return task

    monkeypatch.setattr(watcher, "_submit_input", submit)
    monkeypatch.setattr(watcher, "_broadcast_status", lambda *_: None)
    monkeypatch.setattr(
        watcher_module, "get_config",
        lambda: SimpleNamespace(watcher=SimpleNamespace(delete_after_process=True)),
    )
    await watcher._process_file(str(old))
    assert main.read_bytes() == b"main"
    assert companion.read_bytes() == b"replacement member"
    assert not watcher._processed_files


@pytest.mark.asyncio
async def test_replaced_source_is_neither_cached_nor_deleted(tmp_path, monkeypatch):
    watcher = watcher_module.FolderWatcher()
    source = tmp_path / "work.zip"
    source.write_bytes(b"first")

    async def submit(path):
        source.write_bytes(b"new generation")
        return Task(TaskType.AUTO_PROCESS, path, status=TaskStatus.COMPLETED)

    monkeypatch.setattr(watcher, "_submit_input", submit)
    monkeypatch.setattr(watcher, "_broadcast_status", lambda *_: None)
    monkeypatch.setattr(
        watcher_module, "get_config",
        lambda: SimpleNamespace(watcher=SimpleNamespace(delete_after_process=True)),
    )
    await watcher._process_file(str(source))
    assert source.read_bytes() == b"new generation"
    assert not watcher._is_file_processed(str(source))
