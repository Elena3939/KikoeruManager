"""单包执行计时排除槽位等待，旧记录不得把任务总耗时当成解压耗时。"""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.core import extract_service as module
from app.core.extract_service import ExtractService
from app.core.activity_log_relations import normalize_import_summary


@pytest.mark.asyncio
async def test_execution_clock_starts_after_resource_wait_and_is_per_task(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Semaphore:
        async def acquire(self):
            clock[0] += 100

        def release(self):
            pass

    class Budget:
        def snapshot(self):
            return {}

        @asynccontextmanager
        async def acquire(self, *args, **kwargs):
            clock[0] += 50
            yield

    monkeypatch.setattr(module, "get_resource_budget_service", lambda: Budget())
    service = ExtractService()
    first, second = SimpleNamespace(task_metadata={}), SimpleNamespace(task_metadata={})
    for task, elapsed in ((first, 3), (second, 7), (first, 2)):
        async with service._acquire_7z_resource_slot(
            semaphore=Semaphore(), budget_resource="archive_cpu", reason="test",
            archive_path="test.zip", slot_label="解压", slot_limit=1,
            wait_timeout=None, task=task, update_task_progress=False,
        ) as acquired:
            assert acquired
            clock[0] += elapsed
    assert first.task_metadata["extract_execution_duration_ms"] == 5000
    assert second.task_metadata["extract_execution_duration_ms"] == 7000


@pytest.mark.asyncio
async def test_failed_attempt_is_timed_and_inspection_is_excluded(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    service = ExtractService()
    task = SimpleNamespace(task_metadata={})
    with pytest.raises(RuntimeError):
        async with service._measure_extract_execution(task):
            clock[0] += 2
            raise RuntimeError("密码错误")
    async with service._measure_extract_execution(task, enabled=False):
        clock[0] += 100
    assert task.task_metadata["extract_execution_duration_ms"] == 2000


def test_summary_uses_execution_time_and_is_idempotent():
    row = dict(category="auto_import", action="task_finished", summary="完成，压缩包 1 GB，总耗时 7 分 53 秒",
               detail={"duration_ms": 473000, "extract_execution_duration_ms": 12000})
    row["summary"] = normalize_import_summary(row)
    assert "解压进程累计耗时 12.0 秒" in row["summary"]
    assert "7 分" not in row["summary"]
    assert normalize_import_summary(row) == row["summary"]
    row["detail"] = {"duration_ms": 473000}
    row["summary"] = normalize_import_summary(row)
    assert row["summary"].endswith("解压耗时未记录")
    assert normalize_import_summary(row) == row["summary"]


@pytest.mark.asyncio
async def test_restarting_extraction_resets_previous_attempt_clock(monkeypatch):
    service = ExtractService()
    task = SimpleNamespace(task_metadata={"extract_execution_duration_ms": 999999, "extract_finished_at": "old"})

    async def extract(current):
        assert "extract_execution_duration_ms" not in current.task_metadata
        assert "extract_finished_at" not in current.task_metadata
        current.task_metadata["extract_execution_duration_ms"] = 5000
        return "output"

    monkeypatch.setattr(service, "_extract", extract)
    assert await service.extract(task) == "output"
    assert task.task_metadata["extract_execution_duration_ms"] == 5000
