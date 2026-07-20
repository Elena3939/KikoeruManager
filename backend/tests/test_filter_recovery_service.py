import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.filter_recovery_service import (
    FilterRecoveryConflictError,
    FilterRecoveryError,
    FilterRecoveryService,
)
from app.core.filter_service import FilterService
from app.core.task_engine import TaskEngine, TaskStatus, TaskType


class _Task:
    def __init__(self, task_id: str = "task-1") -> None:
        self.id = task_id
        self.progress = []

    def update_progress(self, progress: int, message: str) -> None:
        self.progress.append((progress, message))


def _config(*rules, filter_dir: bool = True):
    return SimpleNamespace(
        filter=SimpleNamespace(
            enabled=True,
            filter_dir=filter_dir,
            rules=list(rules),
        )
    )


def _rule(pattern: str, *, target: str):
    return SimpleNamespace(
        name=pattern,
        pattern=pattern,
        target=target,
        action="exclude",
        enabled=True,
    )


def test_filter_moves_file_to_recovery_and_can_restore(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    removed = source / "remove.tmp"
    removed.write_bytes(b"recover-me")
    (source / "keep.wav").write_bytes(b"keep")

    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    monkeypatch.setattr("app.core.filter_service.get_filter_recovery_service", lambda: recovery)
    monkeypatch.setattr(
        "app.core.filter_service.get_config",
        lambda: _config(_rule(r"\.tmp$", target="file")),
    )

    result = asyncio.run(FilterService().filter(str(source), _Task()))

    assert not removed.exists()
    assert (source / "keep.wav").exists()
    assert result["filtered_count"] == 1
    item = result["filtered_items"][0]
    assert item["relative_path"] == "remove.tmp"
    assert item["recovery_status"] == "available"
    recovery.finalize_task("task-1", final_root=str(source))

    manifest = recovery._read_manifest("task-1")
    payload = recovery._payload_path("task-1", manifest["items"][0])
    restored_path = recovery._restore_local(payload, manifest["target"], manifest["items"][0])
    assert Path(restored_path).read_bytes() == b"recover-me"
    assert not payload.exists()


def test_parent_directory_match_collapses_child_file_match(monkeypatch, tmp_path):
    source = tmp_path / "source"
    removed_dir = source / "delete-me"
    removed_dir.mkdir(parents=True)
    (removed_dir / "also.tmp").write_bytes(b"one")
    (removed_dir / "keep.wav").write_bytes(b"two")

    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    monkeypatch.setattr("app.core.filter_service.get_filter_recovery_service", lambda: recovery)
    monkeypatch.setattr(
        "app.core.filter_service.get_config",
        lambda: _config(
            _rule(r"\.tmp$", target="file"),
            _rule(r"^delete-me$", target="folder"),
        ),
    )

    result = asyncio.run(FilterService().filter(str(source), _Task()))

    assert result["filtered_count"] == 1
    assert result["filtered_items"][0]["type"] == "dir"
    assert result["filtered_items"][0]["size"] == 6
    manifest = recovery._read_manifest("task-1")
    payload = recovery._payload_path("task-1", manifest["items"][0])
    assert (payload / "also.tmp").read_bytes() == b"one"
    assert (payload / "keep.wav").read_bytes() == b"two"


def test_path_transforms_follow_flatten_operations():
    transformed = FilterRecoveryService.apply_path_transforms(
        "wrapper/inner/remove.wav",
        [
            {"parent_relative_path": "", "removed_segment": "wrapper"},
            {"parent_relative_path": "", "removed_segment": "inner"},
        ],
    )
    assert transformed == "remove.wav"


def test_local_restore_blocks_existing_target(tmp_path):
    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    target = tmp_path / "target"
    target.mkdir()
    (target / "same.txt").write_text("existing", encoding="utf-8")
    payload = tmp_path / "same.txt"
    payload.write_text("recovery", encoding="utf-8")

    with pytest.raises(FilterRecoveryConflictError):
        recovery._restore_local(
            payload,
            {"root": str(target)},
            {"restore_relative_path": "same.txt"},
        )
    assert payload.read_text(encoding="utf-8") == "recovery"
    assert (target / "same.txt").read_text(encoding="utf-8") == "existing"


def test_cleanup_removes_task_recovery_directory(tmp_path):
    source = tmp_path / "remove.txt"
    source.write_text("payload", encoding="utf-8")
    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    recovery.capture_item(
        "task-1",
        str(source),
        relative_path="remove.txt",
        entry_type="file",
        size=7,
    )

    assert recovery.cleanup_task("task-1") is True
    assert not (tmp_path / "recovery" / "task-1").exists()


def test_capture_failure_keeps_original_filter_item(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    removed = source / "remove.tmp"
    removed.write_bytes(b"keep-on-failure")

    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    monkeypatch.setattr("app.core.filter_service.get_filter_recovery_service", lambda: recovery)
    monkeypatch.setattr(
        "app.core.filter_service.get_config",
        lambda: _config(_rule(r"\.tmp$", target="file")),
    )
    monkeypatch.setattr(recovery, "capture_item", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))

    result = asyncio.run(FilterService().filter(str(source), _Task()))

    assert removed.read_bytes() == b"keep-on-failure"
    assert result["filtered_count"] == 0


def test_capture_publish_failure_rolls_atomic_move_back(monkeypatch, tmp_path):
    source = tmp_path / "remove.txt"
    source.write_bytes(b"must-survive")
    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    real_replace = os.replace

    def fail_staged_directory_publish(src, dst):
        if Path(src).name.endswith(".part") and Path(src).is_dir():
            raise OSError("publish failed")
        return real_replace(src, dst)

    monkeypatch.setattr("app.core.filter_recovery_service.os.replace", fail_staged_directory_publish)

    with pytest.raises(OSError, match="publish failed"):
        recovery.capture_item(
            "task-1",
            str(source),
            relative_path="remove.txt",
            entry_type="file",
            size=len(b"must-survive"),
        )

    assert source.read_bytes() == b"must-survive"


def test_restore_rejects_path_traversal(tmp_path):
    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    with pytest.raises(FilterRecoveryError):
        recovery._normalize_relative_path("../outside.txt")


def test_remote_restore_reuses_existing_upload_path(tmp_path):
    payload = tmp_path / "remove.txt"
    payload.write_text("payload", encoding="utf-8")
    calls = []

    class _Manager:
        def get_cached_synology_client(self, _config):
            return object()

        def _normalize_remote_path(self, path):
            return path

        async def _remote_path_exists(self, _client, _path):
            return False

        async def upload_directory_to_library(self, library_id, source, relative_target, **kwargs):
            calls.append((library_id, source, relative_target, kwargs))
            return "/volume/library/RJ00000001/sub/remove.txt"

    library = SimpleNamespace(
        id="remote-1",
        root_path="/volume/library",
        synology=SimpleNamespace(),
    )
    recovery = FilterRecoveryService(str(tmp_path / "recovery"))
    restored = asyncio.run(recovery._restore_remote(
        _Manager(),
        library,
        payload,
        {"root": "/volume/library/RJ00000001"},
        {"restore_relative_path": "sub/remove.txt"},
    ))

    assert restored.endswith("/sub/remove.txt")
    assert calls == [(
        "remote-1",
        str(payload),
        "RJ00000001/sub",
        {"delete_source_on_success": False},
    )]


def test_task_engine_finalizes_recovery_metadata(monkeypatch):
    class _Recovery:
        def finalize_task(self, task_id, **kwargs):
            assert task_id == "task-1"
            assert kwargs["final_root"] == "D:/library/RJ00000001"
            return [{
                "recovery_id": "recovery-1",
                "recovery_status": "available",
                "restore_relative_path": "remove.txt",
            }]

        def public_summary(self, _task_id):
            return {"target_ready": True, "available_count": 1}

    monkeypatch.setattr(
        "app.core.filter_recovery_service.get_filter_recovery_service",
        lambda: _Recovery(),
    )
    task = SimpleNamespace(
        id="task-1",
        output_path="D:/library/RJ00000001",
        task_metadata={
            "filter_recovery": {"version": 1},
            "filtered_items": [{"recovery_id": "recovery-1", "relative_path": "wrapper/remove.txt"}],
        },
        touch_metadata=lambda reason: setattr(task, "touch_reason", reason),
    )
    engine = object.__new__(TaskEngine)

    asyncio.run(engine._finalize_filter_recovery(
        task,
        [{"parent_relative_path": "", "removed_segment": "wrapper"}],
        library_id="local-1",
    ))

    assert task.task_metadata["filtered_items"][0]["restore_relative_path"] == "remove.txt"
    assert task.task_metadata["filter_recovery"]["target_ready"] is True
    assert task.touch_reason == "filter_recovery_finalized"


def test_remove_task_cleans_recovery_before_deleting_snapshot(monkeypatch):
    calls = []

    class _Recovery:
        def cleanup_task(self, task_id, *, strict):
            calls.append((task_id, strict))
            return True

    monkeypatch.setattr(
        "app.core.filter_recovery_service.get_filter_recovery_service",
        lambda: _Recovery(),
    )
    task = SimpleNamespace(
        id="task-1",
        status=TaskStatus.COMPLETED,
        rjcode=None,
        type=TaskType.AUTO_PROCESS,
    )
    engine = object.__new__(TaskEngine)
    engine.tasks = {task.id: task}
    engine.processing = set()
    engine._processing_rjcodes = set()
    engine.delete_task_snapshot = lambda task_id: calls.append(("snapshot", task_id))

    assert engine.remove_task(task.id) is True
    assert calls == [("task-1", True), ("snapshot", "task-1")]
