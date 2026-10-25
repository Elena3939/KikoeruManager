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
    monkeypatch.setattr(processor, '_load_unresolved_source_paths', lambda: set())
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
    async def submit_input(path):
        return await processor.process_file(
            path, auto_classify=config.watcher.auto_classify,
            wait_stable=True, is_processed=watcher._is_file_processed,
            mark_processed=watcher._mark_file_processed,
        )
    monkeypatch.setattr(watcher, "_submit_input", submit_input)
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
async def test_unresolved_problem_blocks_scan_but_allows_manual_retry(watcher_setup, monkeypatch, tmp_path):
    _, processor, submitted = watcher_setup
    source = tmp_path / 'RJ123456.zip'
    source.write_bytes(b'PK\x03\x04' + b'x' * 1024)
    blocked = {processor._path_key(str(source))}
    monkeypatch.setattr(processor, '_load_unresolved_source_paths', lambda: blocked)
    report = {}
    for _ in range(2):
        assert await processor.process_directory(str(tmp_path), report=report) == []
    assert not submitted
    assert report['skipped_unresolved_count'] == 2
    assert await processor.process_file(str(source), wait_stable=False, manual_retry=True)
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_unresolved_volume_blocks_other_volume_before_rename(watcher_setup, monkeypatch, tmp_path):
    _, processor, submitted = watcher_setup
    first = tmp_path / 'RJ123456.7z.001'
    tail = tmp_path / 'RJ123456.7z.002'
    first.write_bytes(b'7z\xbc\xaf\x27\x1c' + b'x' * 1024)
    tail.write_bytes(b'x' * 1024)
    monkeypatch.setattr(processor, '_load_unresolved_source_paths', lambda: {processor._path_key(str(first))})
    normalize = AsyncMock()
    monkeypatch.setattr(processor, '_normalize_file', normalize)
    assert await processor.process_file(str(tail), wait_stable=False) is None
    normalize.assert_not_awaited()
    assert not submitted


@pytest.mark.asyncio
async def test_same_rj_other_archive_and_resolved_source_remain_scannable(watcher_setup, monkeypatch, tmp_path):
    _, processor, submitted = watcher_setup
    source = tmp_path / 'RJ123456.zip'
    other = tmp_path / 'RJ123456_bonus.zip'
    for path in (source, other):
        path.write_bytes(b'PK\x03\x04' + b'x' * 1024)
    blocked = {processor._path_key(str(source))}
    monkeypatch.setattr(processor, '_load_unresolved_source_paths', lambda: blocked)
    assert await processor.process_file(str(other), wait_stable=False)
    blocked.clear()
    assert await processor.process_file(str(source), wait_stable=False)
    assert len(submitted) == 2


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
async def test_downloaded_archive_waits_when_auto_start_is_disabled(watcher_setup, tmp_path):
    """监视器发现下载好的压缩包，但关闭自动处理时不能提交解压。"""
    watcher, _, submitted = watcher_setup
    watcher._loop = asyncio.get_running_loop()
    watcher.config.watcher.auto_start = False
    path = tmp_path / 'RJ123456.zip'
    path.write_bytes(b'PK\x03\x04')
    watcher.handler.on_created(FileCreatedEvent(str(path)))
    await watcher._scan_folder()
    await drain_events()

    assert submitted == []
    assert path.exists()
    assert str(path) in watcher.pending_files


def test_disguised_z77_7z_is_detected_without_zip_main(watcher_setup, tmp_path):
    """没有对应 .zip 主卷时，伪装成 .z77 的 7z 应按单体压缩包识别。"""
    _, processor, _ = watcher_setup
    path = tmp_path / 'RJ01649699(zwzww).z77'
    path.write_bytes(b'7z\xbc\xaf\x27\x1c' + b'payload')

    assert processor.is_archive(str(path)) is True


def test_z77_with_zip_main_remains_zip_volume(watcher_setup, tmp_path):
    """同目录存在对应 .zip 主卷时，.z77 仍按 ZIP 分卷跳过。"""
    _, processor, _ = watcher_setup
    path = tmp_path / 'archive.z77'
    path.write_bytes(b'7z\xbc\xaf\x27\x1c' + b'payload')
    (tmp_path / 'archive.zip').write_bytes(b'PK\x03\x04')

    assert processor.is_archive(str(path)) is False


@pytest.mark.asyncio
async def test_orphan_z77_does_not_wait_as_zip_volume(watcher_setup, monkeypatch, tmp_path):
    """没有 .zip 主卷的伪装 .z77 不应进入分卷等待分支。"""
    _, processor, _ = watcher_setup
    path = tmp_path / 'archive.z77'
    path.write_bytes(b'7z\xbc\xaf\x27\x1c' + b'payload')
    sleep = AsyncMock()
    monkeypatch.setattr(processor_module.asyncio, 'sleep', sleep)

    assert await processor._handle_potential_volume(str(path)) == str(path)
    sleep.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_manual_scan_collects_off_loop_and_only_checks_archive_claims(
    watcher_setup, monkeypatch, tmp_path,
):
    _, processor, submitted = watcher_setup
    loop_thread = threading.get_ident()
    source = tmp_path / 'RJ123456.zip'
    source.write_bytes(b'PK\x03\x04' + b'x' * 1024)
    for index in range(20):
        (tmp_path / f'notes{index}.txt').write_text('notes')
    original_detect = processor.is_archive

    def detect(path):
        assert threading.get_ident() != loop_thread
        return original_detect(path)

    monkeypatch.setattr(processor, 'is_archive', detect)
    archive = processor_module.get_deferred_archive_service()
    result = await processor.process_directory(str(tmp_path))
    assert result == submitted
    assert len(result) == 1
    # 仅在候选规范化前、提交前查询，不为每个普通文件查询数据库。
    assert archive.is_source_claimed.await_count == 2


@pytest.mark.asyncio
async def test_manual_scan_keeps_live_archive_claim_check(watcher_setup, monkeypatch, tmp_path):
    _, processor, submitted = watcher_setup
    source = tmp_path / 'RJ123456.zip'
    source.write_bytes(b'PK\x03\x04' + b'x' * 1024)
    archive = processor_module.get_deferred_archive_service()
    archive.is_source_claimed.return_value = True
    normalize = processor._normalize_file
    assert await processor.process_directory(str(tmp_path)) == []
    normalize.assert_not_awaited()
    assert submitted == []


@pytest.mark.asyncio
async def test_volume_stability_checks_share_observation_window(watcher_setup, monkeypatch):
    _, processor, _ = watcher_setup
    volumes = ['archive.zip'] + [f'archive.z{index:02}' for index in range(1, 11)]
    entered = set()
    ready = asyncio.Event()

    async def wait(path, **kwargs):
        entered.add(path)
        if len(entered) == 10:
            ready.set()
        # 串行实现会在第一卷卡住，无法满足整组已开始观察。
        await asyncio.wait_for(ready.wait(), timeout=2)

    monkeypatch.setattr(processor, 'wait_file_stable', wait)
    volume_set = VolumeSet('archive', volumes, 'zip_volume_main', volumes[0])
    assert await processor._process_volume_set(volumes[0], volume_set) == volumes[0]
    assert entered == set(volumes[1:])


@pytest.mark.asyncio
async def test_volume_timeout_or_new_download_prevents_submission(watcher_setup, monkeypatch, tmp_path):
    _, processor, submitted = watcher_setup
    first = tmp_path / 'archive.zip'
    tail = tmp_path / 'archive.z01'
    for path in (first, tail):
        path.write_bytes(b'x' * 1024)
    processor.wait_file_stable.side_effect = TimeoutError('仍在写入')
    assert await processor.process_file(str(first), wait_stable=False) is None
    assert not submitted

    async def begin_download(*args, **kwargs):
        tail.with_name(tail.name + '.aria2').write_bytes(b'active')

    processor.wait_file_stable.side_effect = begin_download
    assert await processor.process_file(str(first), wait_stable=False) is None
    assert not submitted
