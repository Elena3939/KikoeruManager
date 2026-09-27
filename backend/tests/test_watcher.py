"""监视器任务提交、扫描线程与下载分卷回归。"""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent

from app.core import file_processor as processor_module
from app.core import watcher as watcher_module
from app.core.file_processor import FileProcessor, VolumeSet
from app.core.task_engine import TaskStatus


@pytest.fixture
def watcher_setup(monkeypatch, tmp_path):
    processor = FileProcessor()
    config = SimpleNamespace(
        storage=SimpleNamespace(input_path=str(tmp_path)),
        watcher=SimpleNamespace(auto_start=True, auto_classify=False, delete_after_process=False),
    )
    monkeypatch.setattr(watcher_module, 'get_config', lambda: config)
    monkeypatch.setattr(watcher_module, 'get_file_processor', lambda: processor)
    archive = SimpleNamespace(is_source_claimed=AsyncMock(return_value=False))
    monkeypatch.setattr(watcher_module, 'get_deferred_archive_service', lambda: archive)
    monkeypatch.setattr(processor_module, 'get_deferred_archive_service', lambda: archive)
    submitted = []

    async def submit(task):
        submitted.append(task)
        with task._set_state_silent():
            task.status = TaskStatus.COMPLETED

    engine = SimpleNamespace(get_all_tasks=lambda **kwargs: submitted, submit=submit)
    monkeypatch.setattr(watcher_module, 'get_task_engine', lambda: engine)
    monkeypatch.setattr(processor_module, 'get_task_engine', lambda: engine)
    monkeypatch.setattr(processor, 'wait_file_stable', AsyncMock())
    monkeypatch.setattr(processor, '_inherit_download_password_metadata', lambda *_: {})
    monkeypatch.setattr(processor, '_normalize_file', AsyncMock(side_effect=lambda path, **kwargs: path))
    watcher = watcher_module.FolderWatcher()
    watcher.is_running = True
    monkeypatch.setattr(watcher, '_broadcast_status', lambda *_: None)
    watcher.handler = watcher_module.ArchiveHandler(
        watcher._on_archive_detected, watcher._get_excluded_paths,
        lambda: watcher._paused, watcher._mark_file_processed,
    )
    return watcher, processor, submitted


async def drain_events():
    # 先消费跨线程调度回调，再明确等待处理协程，避免线程尚未返回就断言。
    for _ in range(3):
        await asyncio.sleep(0)
    processing = [
        task for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and getattr(task.get_coro(), '__qualname__', '') == 'FolderWatcher._process_file'
    ]
    if processing:
        await asyncio.wait_for(asyncio.gather(*processing), timeout=5)


@pytest.mark.asyncio
async def test_detected_archive_reaches_real_processor_and_submits_once(watcher_setup, tmp_path):
    watcher, _, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    path = tmp_path / 'RJ123456.zip'
    path.write_bytes(b'PK\x03\x04')
    watcher.handler.on_created(FileCreatedEvent(str(path)))
    watcher.handler.on_modified(FileModifiedEvent(str(path)))
    await drain_events()
    assert len(submitted) == 1
    assert submitted[0].source_path == str(path)
    assert str(path) not in watcher.pending_files


@pytest.mark.parametrize('name', ['RJ123456.7z.001', 'RJ123456.7z.002', 'RJ123456.part1.rar', 'RJ123456.part2.rar'])
def test_downloading_volume_is_never_marked_processed(watcher_setup, tmp_path, name):
    watcher, _, _ = watcher_setup
    path = tmp_path / name
    path.write_bytes(b'')
    path.with_name(name + '.aria2').write_bytes(b'active')
    watcher.handler.on_created(FileCreatedEvent(str(path)))
    watcher.handler.on_modified(FileModifiedEvent(str(path)))
    assert str(path) not in watcher._processed_files
    assert str(path) not in watcher.pending_files


@pytest.mark.asyncio
async def test_scan_traversal_and_detection_run_off_event_loop(watcher_setup, monkeypatch, tmp_path):
    watcher, processor, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    path = tmp_path / 'RJ123456.zip'
    path.write_bytes(b'PK\x03\x04')
    original_walk = watcher_module.os.walk
    original_detect = processor.is_archive
    visited = []

    def walk(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        visited.append('walk')
        yield from original_walk(*args, **kwargs)

    def detect(value):
        assert threading.get_ident() != loop_thread
        visited.append('detect')
        return original_detect(value)

    monkeypatch.setattr(watcher_module.os, 'walk', walk)
    monkeypatch.setattr(processor, 'is_archive', detect)
    await watcher._scan_folder()
    await drain_events()
    await watcher._scan_folder()
    assert 'walk' in visited and 'detect' in visited
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_active_tail_volume_does_not_freeze_processed_state(watcher_setup, tmp_path):
    watcher, processor, _ = watcher_setup
    first = tmp_path / 'RJ123456.7z.001'
    tail = tmp_path / 'RJ123456.7z.002'
    first.write_bytes(b'first')
    tail.write_bytes(b'tail')
    tail.with_name(tail.name + '.aria2').write_bytes(b'active')
    volume_set = VolumeSet('RJ123456', [str(first), str(tail)], '7z', str(first))
    result = await processor._process_volume_set(
        str(first), volume_set, is_processed=watcher._is_file_processed,
        mark_processed=watcher._mark_file_processed,
    )
    assert result is None
    assert watcher._processed_files == set()


@pytest.mark.asyncio
@pytest.mark.parametrize('first_name,tail_name,magic', [
    ('RJ123456.7z.001', 'RJ123456.7z.002', b'7z\xbc\xaf\x27\x1c'),
    ('RJ123456.part1.rar', 'RJ123456.part2.rar', b'Rar!\x1a\x07\x00'),
])
async def test_scan_rediscovers_group_after_download_finishes(
    watcher_setup, tmp_path, first_name, tail_name, magic,
):
    watcher, _, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    first = tmp_path / first_name
    tail = tmp_path / tail_name
    first.write_bytes(magic + b'x' * 1024)
    tail.write_bytes(b'y' * 1024)
    sidecar = tail.with_name(tail.name + '.aria2')
    sidecar.write_bytes(b'active')
    await watcher._scan_folder()
    await drain_events()
    assert submitted == []
    assert str(first) not in watcher._processed_files
    sidecar.unlink()
    await watcher._scan_folder()
    await drain_events()
    assert len(submitted) == 1
    assert submitted[0].source_path == str(first)
    assert {str(first), str(tail)} <= watcher._processed_files


@pytest.mark.asyncio
async def test_scan_and_watchdog_event_share_pending_reservation(watcher_setup, tmp_path):
    watcher, _, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    path = tmp_path / 'RJ123456.zip'
    path.write_bytes(b'PK\x03\x04')
    await asyncio.gather(
        watcher._scan_folder(),
        asyncio.to_thread(watcher.handler.on_created, FileCreatedEvent(str(path))),
    )
    await drain_events()
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_scan_does_not_submit_after_stop(watcher_setup, monkeypatch, tmp_path):
    watcher, _, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    path = tmp_path / 'RJ123456.zip'
    path.write_bytes(b'PK\x03\x04')
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def collect(*_args):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return [str(path)]

    monkeypatch.setattr(watcher, '_collect_archive_candidates', collect)
    scan = asyncio.create_task(watcher._scan_folder())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        watcher.is_running = False
    finally:
        release.set()
        await scan
    await drain_events()
    assert submitted == []
    assert watcher.pending_files == set()
