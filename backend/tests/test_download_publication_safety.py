"""下载发布失败不得删除完整文件，也不得把内部暂存文件送入解压。"""

import asyncio
import contextlib
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import baidu_netdisk_service as baidu
from app.core.baidu_netdisk_service import BaiduNetdiskService
from app.core.extract_service import ExtractService
from app.core.file_processor import FileProcessor
from app.core.input_scan_discovery import InputScanDiscovery
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [TaskType.BAIDU_NETDISK_DOWNLOAD, TaskType.HTTP_DOWNLOAD])
@pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.CANCELLED])
async def test_download_cleanup_preserves_completed_files(tmp_path, kind, status):
    output = tmp_path / "downloads"
    output.mkdir()
    for name in ("RJ01621654.7z", "RJ01694783.7z"):
        (output / name).write_bytes(name.encode())
    task = Task(kind, "share", output_path=str(output), status=status)

    await TaskEngine()._cleanup_failed_task(task)

    assert sorted(path.name for path in output.iterdir()) == ["RJ01621654.7z", "RJ01694783.7z"]


def test_baidu_publication_ignores_clone_and_move_files(tmp_path, monkeypatch):
    staging, output = tmp_path / "staging", tmp_path / "output"
    staging.mkdir()
    (staging / "RJ01621654.7z").write_bytes(b"complete")
    for name in (".kikoerumanager-clone-abcd.part", "file.7z.kikoerumanager-move-abcd.part", "x.aria2"):
        (staging / name).write_bytes(b"unfinished")
    monkeypatch.setattr(baidu, "move_path_replacing_sync", shutil.move)

    BaiduNetdiskService()._finalize_output(str(staging), str(output), "resume", 1)

    assert [path.name for path in output.iterdir()] == ["RJ01621654.7z"]
    assert len(list(staging.iterdir())) == 3
    assert not BaiduNetdiskService()._directory_has_files(str(staging))


@pytest.mark.asyncio
async def test_partial_publication_failure_keeps_already_published_files(tmp_path, monkeypatch):
    staging, output = tmp_path / "staging", tmp_path / "output"
    staging.mkdir()
    for name in ("a.7z", "b.7z", "c.7z"):
        (staging / name).write_bytes(b"complete")
    original_listdir = baidu.os.listdir
    monkeypatch.setattr(baidu.os, "listdir", lambda path: sorted(original_listdir(path)))

    def move(source, target):
        if Path(source).name == "c.7z":
            raise OSError("发布中断")
        shutil.move(source, target)

    monkeypatch.setattr(baidu, "move_path_replacing_sync", move)
    with pytest.raises(OSError, match="发布中断"):
        BaiduNetdiskService()._finalize_output(str(staging), str(output), "resume", 1)
    task = Task(TaskType.BAIDU_NETDISK_DOWNLOAD, "share", output_path=str(output), status=TaskStatus.FAILED)
    await TaskEngine()._cleanup_failed_task(task)
    assert (output / "a.7z").read_bytes() == b"complete"
    assert (output / "b.7z").read_bytes() == b"complete"
    assert (staging / "c.7z").read_bytes() == b"complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_during_download", [False, True])
async def test_baidu_task_exception_keeps_staging_files(tmp_path, monkeypatch, fail_during_download):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_download_root", lambda: str(tmp_path))
    monkeypatch.setattr(service, "_config", lambda: SimpleNamespace(conflict_policy="resume"))
    monkeypatch.setattr(service, "_is_svip", lambda: False)
    monkeypatch.setattr(service, "_baidu_download_file_concurrency", lambda _: 1)
    monkeypatch.setattr(service, "_network_download_budget_limit", lambda: 0)
    monkeypatch.setattr(service, "_baidu_pcs_go_download_limits", lambda: (1, 1))
    monkeypatch.setattr(service, "_resolve_download_preview", AsyncMock(return_value={"items": [{"ok": True}]}))
    rows = [{"name": "a.7z", "status": "pending", "size": 8}]
    monkeypatch.setattr(service, "_build_download_file_rows", AsyncMock(return_value=rows))

    async def download(task, staging_dir, row, *args):
        Path(staging_dir, row["name"]).write_bytes(b"complete")
        row["status"] = "completed"
        if fail_during_download:
            raise OSError("下载调度中断")

    def publish(*args):
        raise OSError("发布中断")

    monkeypatch.setattr(service, "_download_share_item_guarded", download)
    monkeypatch.setattr(service, "_finalize_output", publish)
    task = Task(TaskType.BAIDU_NETDISK_DOWNLOAD, "share", metadata={"batch_name": "safety"})
    with pytest.raises(OSError, match="中断"):
        await service.start_download_task(task)
    task.fail("中断")
    await TaskEngine()._cleanup_failed_task(task)
    staging = Path(task.task_metadata["staging_dir"])
    assert (staging / "a.7z").read_bytes() == b"complete"
    assert task.task_metadata["staging_cleanup"]["retained_for_retry"] is True


@pytest.mark.asyncio
async def test_discovery_skips_download_staging_and_internal_files(tmp_path, monkeypatch):
    from app.core import input_scan_discovery as discovery_module

    staging = tmp_path / ".baidu-netdisk-staging" / "task-id"
    staging.mkdir(parents=True)
    (staging / "RJ01621654.7z").write_bytes(b"complete")
    (tmp_path / ".kikoerumanager-move-abcd.part").write_bytes(b"7z\xbc\xaf\x27\x1c")
    (tmp_path / ".normal.7z").write_bytes(b"x" * 2048)
    processor = FileProcessor()
    assert not processor.is_archive(str(staging / "RJ01621654.7z"))
    assert not processor.is_archive(str(tmp_path / ".kikoerumanager-move-abcd.part"))
    assert processor.is_archive(str(tmp_path / ".normal.7z"))
    assert processor._collect_directory_archives(str(tmp_path)) == [str(tmp_path / ".normal.7z")]

    monkeypatch.setattr(discovery_module.InputScanDiscovery, "_io", lambda *_: contextlib.nullcontext())
    discovery = InputScanDiscovery(str(tmp_path))
    await discovery.start()
    groups = []
    try:
        while True:
            message = await asyncio.wait_for(discovery.receive(), 5)
            groups.extend(message.get("groups", []))
            if message.get("closed"):
                break
    finally:
        await discovery.stop()
    assert [Path(group["source_path"]).name for group in groups] == [".normal.7z"]


@pytest.mark.asyncio
async def test_missing_archive_fails_without_password_attempts(tmp_path, monkeypatch):
    service = ExtractService()
    monkeypatch.setattr(service, "_ensure_7z_available", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_try_extract", AsyncMock())
    task = Task(TaskType.EXTRACT, str(tmp_path / "missing.7z"))
    assert await service._extract(task) is None
    assert task.status == TaskStatus.FAILED
    assert task.task_metadata["extract_failure_reason"] == "source_missing"
    assert "源文件不存在" in task.error_message
    service._try_extract.assert_not_awaited()
    assert TaskEngine()._record_problem_work_for_extract_failure(task, None, task.error_message) is False
