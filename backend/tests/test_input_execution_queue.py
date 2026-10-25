"""正式任务等待源时不占业务名额，也不提前结算生命周期。"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.core.input_stability import InputSourceNotReady


@pytest.mark.asyncio
async def test_source_wait_is_pending_and_later_task_can_run(tmp_path, monkeypatch):
    from app.core import task_engine as module

    engine = TaskEngine(max_concurrent=1)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    engine._notify_progress = AsyncMock()
    engine.persist_task_snapshot = lambda task: None
    source = tmp_path / "a.zip"
    source.write_bytes(b"data")
    task = Task(TaskType.AUTO_PROCESS, str(source), metadata={"scan_id": "scan"})
    engine.tasks[task.id] = task
    engine.processing.add(task.id)
    engine._running_task_ids.add(task.id)
    engine._preflight_auto_process = AsyncMock(side_effect=InputSourceNotReady("file_changing"))
    # 真实解压等待会写到期状态；这里只隔离预检之后的异常交接。
    task.task_metadata["input_source_wait"] = {"next_check_at": 9999999999}
    try:
        await engine._process_task(task)
        started = task.started_at
        assert task.status == TaskStatus.PENDING
        assert task.id not in engine.processing
        assert not getattr(task, "_input_lifecycle_pending", False)
        engine._finish_running_task(None, task)
        assert engine.queue.qsize() == 1
        assert not await engine._input_source_ready(task)
        other = Task(TaskType.AUTO_PROCESS, str(source))
        assert engine._task_lane_has_capacity(other)
        assert task.started_at == started
    finally:
        engine.stop()


@pytest.mark.asyncio
async def test_worker_rotates_unstable_source_without_starting_it(tmp_path, monkeypatch):
    engine = TaskEngine(max_concurrent=1)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    path = tmp_path / "a.zip"
    path.write_bytes(b"data")
    waiting = Task(TaskType.AUTO_PROCESS, str(path), metadata={"scan_id": "scan"})
    ready = Task(TaskType.AUTO_PROCESS, str(path))
    engine.tasks.update({waiting.id: waiting, ready.id: ready})
    await engine.queue.put(waiting)
    await engine.queue.put(ready)
    engine._input_source_ready = AsyncMock(side_effect=lambda task: task is ready)
    finished = asyncio.Event()

    async def run(task):
        assert task is ready
        assert engine.processing == {ready.id}
        task.complete()
        engine.processing.discard(task.id)
        finished.set()

    engine._process_task = run
    worker = asyncio.create_task(engine._worker())
    try:
        await asyncio.wait_for(finished.wait(), 2)
        assert waiting.status == TaskStatus.PENDING and waiting.started_at is None
    finally:
        engine.stop()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
