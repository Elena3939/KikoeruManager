"""实际子进程启动才产生解压指标；清单和启动失败不产生。"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.extract_service import ExtractService
from app.core.task_engine import Task, TaskType


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,command,expected", [
    ("7zz", "l", False), ("7zz", "t", False), ("7zz", "x", True),
    ("lsar", "", False), ("unar", "", True),
])
async def test_real_spawn_distinguishes_inspection(monkeypatch, tool, command, expected):
    service = ExtractService()
    task = Task(TaskType.AUTO_PROCESS, "source.zip")
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(return_value=b"")),
        stderr=SimpleNamespace(read=AsyncMock(return_value=b"")),
        wait=AsyncMock(return_value=0), communicate=AsyncMock(return_value=(b"", b"")),
        returncode=0, pid=123,
    )
    monkeypatch.setattr("app.core.extract_service.asyncio.create_subprocess_exec", AsyncMock(return_value=process))

    @contextlib.asynccontextmanager
    async def acquire(**kwargs):
        yield True

    monkeypatch.setattr(service, "_acquire_7z_resource_slot", acquire)
    if tool == "7zz":
        result = await service._run_7z_command_once([tool, command, "source.zip"], task=task)
    else:
        result = await service._run_subprocess_command([tool, "source.zip"], task=task)
    assert result.returncode == 0
    assert bool(task.task_metadata.get("input_first_extract_at")) is expected
    if expected:
        first = task.task_metadata["input_first_extract_at"]
        service._record_extract_process_started(task)
        assert task.task_metadata["input_first_extract_at"] == first


@pytest.mark.asyncio
async def test_spawn_failure_has_no_extract_start(monkeypatch):
    service = ExtractService()
    task = Task(TaskType.AUTO_PROCESS, "source.zip")
    monkeypatch.setattr(
        "app.core.extract_service.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=OSError("无法启动")),
    )

    @contextlib.asynccontextmanager
    async def acquire(**kwargs):
        yield True

    monkeypatch.setattr(service, "_acquire_7z_resource_slot", acquire)
    with pytest.raises(OSError, match="无法启动"):
        await service._run_7z_command_once(["7zz", "x", "source.zip"], task=task)
    assert "input_first_extract_at" not in task.task_metadata
