import asyncio
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.task_io_runtime import (
    ProcessReadCounter, TaskIOMeter, current_io_task, current_move_meter, measured_move,
    monitor_extract_reads,
)
from app.core.task_center_event_service import build_task_center_event


def test_meter_uses_actual_byte_delta_and_clears_completed_speed(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("app.core.task_io_runtime.time.monotonic", lambda: clock[0])
    task = SimpleNamespace(task_metadata={}, mark_changed=Mock())
    meter = TaskIOMeter(task, "move", "move")
    clock[0] += 0.8
    meter.sample(8 * 1024 * 1024, 16 * 1024 * 1024)
    assert task.task_metadata["io_runtime"]["speed_bytes_per_sec"] == pytest.approx(10 * 1024 * 1024)
    assert task.task_metadata["io_runtime"]["completed_bytes"] == 8 * 1024 * 1024
    meter.finish()
    assert task.task_metadata["io_runtime"]["io_active"] is False
    assert task.task_metadata["io_runtime"]["speed_bytes_per_sec"] is None


def test_native_read_counter_includes_cached_file_reads(tmp_path):
    path = tmp_path / "input.bin"
    path.write_bytes(b"x" * 2 * 1024 * 1024)
    counter = ProcessReadCounter(os.getpid())
    try:
        before = counter.read()
        with path.open("rb") as stream:
            while stream.read(64 * 1024):
                pass
        after = counter.read()
        assert before is not None and after is not None
        assert after - before >= path.stat().st_size
    finally:
        counter.close()


@pytest.mark.asyncio
async def test_move_scope_preserves_context_and_cleans_up_after_failure():
    task = SimpleNamespace(task_metadata={}, mark_changed=Mock())
    token = current_io_task.set((task, asyncio.get_running_loop()))

    @measured_move
    def operation():
        assert current_move_meter.get() is not None
        raise OSError("模拟移动失败")

    try:
        with pytest.raises(OSError):
            await asyncio.to_thread(operation)
        await asyncio.sleep(0)
        assert task.task_metadata["io_runtime"]["io_active"] is False
        assert current_move_meter.get() is None
    finally:
        current_io_task.reset(token)


@pytest.mark.asyncio
async def test_extract_monitor_cancellation_stops_speed():
    task = SimpleNamespace(task_metadata={}, mark_changed=Mock())
    process = SimpleNamespace(pid=os.getpid(), returncode=None)
    monitor = asyncio.create_task(monitor_extract_reads(process, task))
    await asyncio.sleep(0)
    monitor.cancel()
    with pytest.raises(asyncio.CancelledError):
        await monitor
    assert task.task_metadata["io_runtime"]["io_active"] is False


def test_sse_contains_io_measurement_retry_and_shared_task_classification():
    task = SimpleNamespace(
        id="retry", type="auto_process", status="processing", progress=40,
        task_metadata={
            "retry_from_conflicts": True,
            "io_runtime": {"phase": "extract", "io_active": True, "speed_kind": "read", "speed_bytes_per_sec": 123},
        },
    )
    event = build_task_center_event(task)
    assert event["retry_from_conflicts"] is True
    assert event["domain"] == "import"
    assert event["io_runtime"]["speed_kind"] == "read"
    assert event["io_runtime"]["speed_bytes_per_sec"] == 123


def test_move_meter_does_not_count_hardlinks_as_copied_bytes(monkeypatch, tmp_path):
    from app.core import staged_file_move as fs

    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    (source / "one").write_bytes(b"x" * 1024)
    os.link(source / "one", source / "two")
    monkeypatch.setattr(fs, "move_config", lambda: SimpleNamespace(host_enabled=False))
    meter = Mock()
    token = current_move_meter.set(meter)
    try:
        fs.copy_path_exclusive_sync(source, target)
    finally:
        current_move_meter.reset(token)
    assert meter.sample.call_args_list
    assert max(call.args[0] for call in meter.sample.call_args_list) == 1024
    assert all(call.args[1] == 1024 for call in meter.sample.call_args_list)
    meter.finish.assert_called_once()
