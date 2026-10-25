"""上传运行态测试不连接生产、数据库或真实 FileStation。"""
import asyncio
import copy
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.upload_task_runtime import UploadTaskRuntime
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.core.task_center_event_service import build_task_center_event


def test_multiple_sources_keep_global_bytes_and_eta():
    runtime = UploadTaskRuntime(4000, 2)
    first = runtime.update({"phase": "uploading", "current_source_dir": "a", "total_bytes": 1000, "transferred_bytes": 1000, "completed_files": 1, "speed_bytes_per_sec": 100})
    assert first["total_bytes"] == 4000
    assert first["eta_seconds"] == 30
    preparing = runtime.update({"phase": "preparing", "current_source_dir": "b", "total_bytes": 0, "transferred_bytes": 0})
    assert preparing["transferred_bytes"] == 1000
    assert preparing["speed_bytes_per_sec"] == 0
    second = runtime.update({"phase": "uploading", "current_source_dir": "b", "total_bytes": 3000, "transferred_bytes": 501, "speed_bytes_per_sec": 100})
    assert second["transferred_bytes"] == 1501
    assert second["completed_files"] == 1
    assert second["eta_seconds"] == 25
    assert runtime.update({"phase": "verifying", "current_source_dir": "b", "transferred_bytes": 3000, "completed_files": 1, "speed_bytes_per_sec": 100})["eta_seconds"] is None


def test_sse_preserves_the_same_runtime_as_status_response():
    task = Task(TaskType.LOCAL_LIBRARY_UPLOAD, "source")
    task.task_metadata["upload_runtime"] = UploadTaskRuntime(1000, 1).update({
        "phase": "uploading", "current_source_dir": "a", "transferred_bytes": 100, "speed_bytes_per_sec": 25,
    })
    runtime = task.task_metadata["upload_runtime"]
    event = build_task_center_event(task, "upload_runtime")
    for field in ["phase", "backend_speed_bytes_per_sec", "speed_bytes_per_sec", "transferred_bytes", "total_bytes", "eta_seconds", "snapshot_at_ms"]:
        assert event["upload_runtime"][field] == runtime[field]


def test_runtime_event_writes_redis_and_sse_without_database_snapshot(monkeypatch):
    from app.core import task_center_event_service

    task = Task(TaskType.LOCAL_LIBRARY_UPLOAD, "source")
    engine = object.__new__(TaskEngine)
    engine.tasks = {task.id: task}
    engine._task_center_version_lock = threading.Lock()
    engine._ensure_task_context = Mock()
    engine._bump_task_center_version = Mock()
    engine._write_task_runtime_to_redis = Mock()
    engine.enqueue_task_center_item_snapshot = Mock()
    broadcast = Mock()
    monkeypatch.setattr(task_center_event_service, "broadcast_task_center_changed", broadcast)
    engine._emit_task_center_event(task, "upload_runtime")
    engine._write_task_runtime_to_redis.assert_called_once_with(task, reason="upload_runtime")
    broadcast.assert_called_once_with(task, reason="upload_runtime")
    engine.enqueue_task_center_item_snapshot.assert_not_called()
    engine._emit_task_center_event(task, "completed")
    engine.enqueue_task_center_item_snapshot.assert_called_once_with(task)


@pytest.mark.asyncio
async def test_same_file_progress_keeps_emitting_and_next_directory_does_not_reset(tmp_path, monkeypatch):
    from app.core import library_manager

    files = [tmp_path / "one.wav", tmp_path / "two.wav"]
    files[0].write_bytes(b"a" * 1000)
    files[1].write_bytes(b"b" * 3000)
    task = Task(TaskType.LOCAL_LIBRARY_UPLOAD, str(tmp_path), metadata={
        "selected_paths": [str(path) for path in files], "target_library_id": "fake",
    })
    task.status = TaskStatus.PROCESSING
    events = []
    task.set_event_hook(lambda task, reason: events.append((reason, copy.deepcopy(task.task_metadata.get("upload_runtime")))))

    async def upload(_library, source, _target, **kwargs):
        size = 1000 if source == str(files[0]) else 3000
        for transferred in (100, 200, size):
            kwargs["progress_callback"]({
                "phase": "uploading", "current_source_dir": source, "current_file_name": "same-name.wav",
                "transferred_bytes": transferred, "total_bytes": size, "completed_files": int(transferred == size),
                "speed_bytes_per_sec": 100,
            })
            await asyncio.sleep(0.51)
        return "/remote/target"

    manager = SimpleNamespace(
        upload_directory_to_library=upload,
        get_library_definition=lambda _: SimpleNamespace(root_path="/remote"),
        _notify_index_self_mutation_upsert_subtree=Mock(),
    )
    monkeypatch.setattr(library_manager, "get_library_manager", lambda: manager)
    engine = object.__new__(TaskEngine)
    engine._extract_rjcode = lambda _: None
    await engine._process_local_library_upload(task)
    snapshots = [runtime for reason, runtime in events if reason == "upload_runtime"]
    assert [item["transferred_bytes"] for item in snapshots] == [100, 200, 1000, 1100, 1200, 4000]
    assert all(item["total_bytes"] == 4000 for item in snapshots)
    assert all(item["speed_bytes_per_sec"] == 100 for item in snapshots)
    assert task.task_metadata["upload_runtime"]["speed_bytes_per_sec"] == 0


@pytest.mark.asyncio
async def test_stalled_network_reports_zero_speed_and_stops_heartbeat(tmp_path, monkeypatch):
    from app.core.library_manager import LibraryManager

    source = tmp_path / "track.wav"
    source.write_bytes(b"a" * 1000)
    snapshots = []
    async def upload(_remote, _local, *, progress_callback):
        progress_callback(100, 1000)
        await asyncio.sleep(0.8)
        progress_callback(200, 1000)
        await asyncio.sleep(1.6)
        progress_callback(1000, 1000)

    manager = object.__new__(LibraryManager)
    monkeypatch.setattr(manager, "_ensure_remote_directory", AsyncMock())
    monkeypatch.setattr(manager, "_verify_uploaded_remote_file", AsyncMock())
    await manager._upload_directory_to_synology(
        SimpleNamespace(upload_file=upload), str(source), "/remote", progress_callback=snapshots.append,
    )
    uploading = [item for item in snapshots if item["phase"] == "uploading"]
    assert any(item["speed_bytes_per_sec"] > 0 for item in uploading)
    assert uploading[-1]["speed_bytes_per_sec"] == 0
    assert snapshots[-1]["completed_files"] == 1
    count = len(snapshots)
    await asyncio.sleep(0.8)
    assert len(snapshots) == count


@pytest.mark.asyncio
async def test_upload_failure_cleans_up_heartbeat(tmp_path, monkeypatch):
    from app.core.library_manager import LibraryManager

    source = tmp_path / "track.wav"
    source.write_bytes(b"payload")
    manager = object.__new__(LibraryManager)
    monkeypatch.setattr(manager, "_ensure_remote_directory", AsyncMock())
    tasks_before = set(asyncio.all_tasks())
    with pytest.raises(OSError, match="连接中断"):
        await manager._upload_directory_to_synology(
            SimpleNamespace(upload_file=AsyncMock(side_effect=OSError("连接中断"))),
            str(source), "/remote", progress_callback=lambda _: None,
        )
    assert set(asyncio.all_tasks()) == tasks_before
