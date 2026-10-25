"""验证内层包实际进度及无换行的 7zz 输出能在子进程结束前到达任务。"""
import asyncio
import contextlib
import subprocess
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.extract_runtime import archive_node
from app.core.extract_service import ExtractService
from app.core.task_engine import Task, TaskType


@pytest.mark.asyncio
async def test_nested_zip_reports_local_percent_and_depth(tmp_path, monkeypatch):
    archive = tmp_path / "RJ01502688.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("track.wav", b"payload")
    output = tmp_path / "output"
    output.mkdir()
    service = ExtractService()
    task = Task(task_type=TaskType.EXTRACT, source_path="outer.rar")
    task.progress = 40
    update = Mock(wraps=task.update_progress)
    monkeypatch.setattr(task, "update_progress", update)
    monkeypatch.setattr(service, "_reject_if_garbled_after_extract", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_list_archive_contents", AsyncMock(return_value=[{"name": "track.wav"}]))
    monkeypatch.setattr(service, "_verify_extraction", AsyncMock(return_value=True))

    async def run(cmd, **kwargs):
        assert "-bsp1" in cmd
        assert kwargs["command_timeout"] is None
        assert "层2" in kwargs["progress_label"]
        kwargs["progress_callback"](" 37% 1 - track.wav")
        kwargs["progress_callback"](" 100%")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(service, "_run_7z_command", run)
    async with archive_node(task, "outer.rar", root=True):
        async with archive_node(task, "middle.zip"):
            async with archive_node(task, str(archive)):
                assert await service._try_extract_nested_direct(str(archive), str(output), task=task) == (True, None)
    messages = [call.args[1] for call in update.call_args_list]
    assert any("RJ01502688.zip" in text and "层2" in text and "当前包 37%" in text for text in messages)
    assert task.progress == 40


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks,expected", [
    ([b" 17%"], "17%"),
    ([b" 1", b"7%"], "17%"),
    ([b" 17%\b\b\b\b 18%"], "18%"),
])
async def test_progress_without_newline_arrives_before_process_exit(monkeypatch, chunks, expected):
    service = ExtractService()
    received = asyncio.Event()
    lines = []
    pending = iter(chunks)

    class Output:
        async def read(self, _size):
            chunk = next(pending, None)
            if chunk is not None:
                return chunk
            # 模拟进程仍在运行；必须实时回调，不能等 EOF 才解析。
            await asyncio.wait_for(received.wait(), timeout=2)
            return b""

    class Empty:
        async def read(self, _size):
            return b""

    process = SimpleNamespace(stdout=Output(), stderr=Empty(), wait=AsyncMock(return_value=0), returncode=0)
    monkeypatch.setattr("app.core.extract_service.asyncio.create_subprocess_exec", AsyncMock(return_value=process))

    @contextlib.asynccontextmanager
    async def acquire(**kwargs):
        assert "层1" in kwargs["slot_label"]
        yield True

    monkeypatch.setattr(service, "_acquire_7z_resource_slot", acquire)
    task = Task(task_type=TaskType.EXTRACT, source_path="outer.rar")
    monkeypatch.setattr(task, "register_process", Mock())
    monkeypatch.setattr(task, "unregister_process", Mock())
    update = Mock(wraps=task.update_progress)
    monkeypatch.setattr(task, "update_progress", update)

    def progress(line):
        lines.append(line)
        received.set()

    result = await service._run_7z_command_once(
        [service.seven_zip, "x", "-bsp1", "nested.zip"], task=task,
        progress_callback=progress, progress_label="解压嵌套压缩包 nested.zip (层1)",
    )
    assert result.returncode == 0
    assert any(expected in line for line in lines)
    assert any("nested.zip (层1) · 已启动" in call.args[1] for call in update.call_args_list)
