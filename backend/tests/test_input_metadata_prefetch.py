"""预取身份、刷新隔离、请求合并及取消订阅。"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.metadata_service import MetadataService, _METADATA_FLIGHTS
from app.core.task_engine import Task, TaskType


@pytest.mark.asyncio
async def test_shared_request_survives_one_subscriber_cancel(monkeypatch):
    service = MetadataService()
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"rjcode": "RJ01234567", "metadata_verification_status": "verified"}

    request = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(service, "_fetch_by_rj", request)
    first = asyncio.create_task(service.fetch_by_rj("RJ01234567"))
    await entered.wait()
    second = asyncio.create_task(service.fetch_by_rj("RJ01234567"))
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    release.set()
    assert (await second)["rjcode"] == "RJ01234567"
    assert request.await_count == 1
    assert not _METADATA_FLIGHTS


@pytest.mark.asyncio
async def test_force_refresh_is_separate_from_prefetch(monkeypatch):
    service = MetadataService()
    request = AsyncMock(return_value={
        "rjcode": "RJ01234567", "metadata_verification_status": "verified",
    })
    monkeypatch.setattr(service, "_fetch_by_rj", request)
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip")
    service.start_prefetch(task, "RJ01234567")
    await task._metadata_prefetch
    result = await service.fetch("RJ01234567", task, force_refresh=True)
    assert result["rjcode"] == "RJ01234567"
    assert request.await_count == 2
    assert request.await_args.kwargs["force_refresh"] is True
    assert not task.task_metadata["metadata_prefetch"]["consumed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("final_rj,verified,expected_calls", [
    ("RJ01234567", True, 1),
    ("RJ01234568", True, 2),
    ("RJ01234567", False, 2),
])
async def test_only_verified_matching_identity_consumes(
    monkeypatch, final_rj, verified, expected_calls,
):
    service = MetadataService()
    request = AsyncMock(return_value={
        "rjcode": "RJ01234567", "work_name": "作品", "maker_name": "社团",
        "metadata_evidence_source": "dlsite_product",
        "metadata_verification_status": "verified" if verified else "unverified",
    })
    monkeypatch.setattr(service, "_fetch_by_rj", request)
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip")
    service.start_prefetch(task, "RJ01234567")
    await task._metadata_prefetch
    await service.fetch(final_rj, task)
    assert request.await_count == expected_calls
    assert task.task_metadata["metadata_prefetch"]["consumed"] is (expected_calls == 1)


@pytest.mark.asyncio
async def test_expired_or_incomplete_prefetch_is_not_consumed(monkeypatch):
    service = MetadataService()
    request = AsyncMock(return_value={
        "rjcode": "RJ01234567", "metadata_verification_status": "verified",
    })
    monkeypatch.setattr(service, "_fetch_by_rj", request)
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip")
    service.start_prefetch(task, "RJ01234567")
    await task._metadata_prefetch
    await service.fetch("RJ01234567", task)
    assert request.await_count == 2
    task._metadata_prefetch_credential["started_monotonic"] -= 301
    await service.fetch("RJ01234567", task)
    assert request.await_count == 3
    assert not task.task_metadata["metadata_prefetch"]["consumed"]


@pytest.mark.asyncio
async def test_pending_prefetch_shares_capacity_and_yields_to_ready_task(monkeypatch):
    from app.config.settings import AppConfig
    from app.core.task_engine import TaskEngine
    config = AppConfig()
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    engine = TaskEngine(max_concurrent=1)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"rjcode": "RJ01234567"}

    monkeypatch.setattr(MetadataService, "_fetch_by_rj", fetch)
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip", metadata={
        "scan_id": "scan", "rjcode": "RJ01234567",
        "input_source_wait": {"next_check_at": 9999999999},
    })
    ready = Task(TaskType.AUTO_PROCESS, "other.zip")
    engine.tasks.update({task.id: task, ready.id: ready})
    try:
        await engine.refresh_input_metadata_window()
        assert not entered.is_set()
        engine.tasks.pop(ready.id)
        await engine.refresh_input_metadata_window()
        await asyncio.wait_for(entered.wait(), 1)
        assert engine._input_metadata_slots == {task.id}
        assert not engine.try_acquire_input_preflight("other")
        assert engine._task_lane_has_capacity(task)
        assert not engine._task_lane_has_capacity(ready)
        future = task._metadata_prefetch
        engine.tasks.pop(task.id)
        await engine.refresh_input_metadata_window()
        assert future.cancelled()
        assert not engine._input_metadata_slots
    finally:
        release.set()
        engine.stop()


@pytest.mark.asyncio
async def test_japanese_failure_preserves_verified_primary_result(monkeypatch):
    from app.config.settings import AppConfig
    config = AppConfig()
    config.auto_process.rename = True
    config.rename.use_japanese_metadata = True
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: config)
    service = MetadataService()
    payload = {
        "rjcode": "RJ01234567", "work_name": "作品", "maker_name": "社团",
        "metadata_evidence_source": "dlsite_product",
        "metadata_verification_status": "verified",
    }
    request = AsyncMock(return_value=payload)
    monkeypatch.setattr(service, "_fetch_by_rj", request)
    monkeypatch.setattr(service, "fetch_japanese_metadata", AsyncMock(side_effect=RuntimeError("日语超时")))
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip")
    await service.start_prefetch(task, "RJ01234567")
    result = await service.fetch("RJ01234567", task)
    assert result["work_name"] == payload["work_name"]
    assert result["metadata_verification_status"] == "verified"
    assert request.await_count == 1
    assert task._japanese_metadata_prefetch is None
    assert task.task_metadata["metadata_prefetch"]["japanese_error"] == "日语超时"


@pytest.mark.asyncio
async def test_pending_window_replaces_expired_or_changed_policy(monkeypatch):
    from app.config.settings import AppConfig
    from app.core.task_engine import TaskEngine
    config = AppConfig()
    config.rename.use_japanese_metadata = False
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: config)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    monkeypatch.setattr(MetadataService, "_fetch_by_rj", AsyncMock(return_value={"rjcode": "RJ01234567"}))
    engine = TaskEngine(max_concurrent=1)
    task = Task(TaskType.AUTO_PROCESS, "RJ01234567.zip", metadata={
        "scan_id": "scan", "rjcode": "RJ01234567",
        "input_source_wait": {"next_check_at": 9999999999},
    })
    engine.tasks[task.id] = task
    try:
        await engine.refresh_input_metadata_window()
        first = task._metadata_prefetch
        await first
        task._metadata_prefetch_credential["started_monotonic"] -= 301
        await engine.refresh_input_metadata_window()
        second = task._metadata_prefetch
        assert second is not first
        await second
        config.metadata.locale = "ja-JP"
        await engine.refresh_input_metadata_window()
        third = task._metadata_prefetch
        assert third is not second
        await third
        assert task._metadata_prefetch_credential["locale"] == "ja-JP"
        config.auto_process.fetch_metadata = False
        await engine.refresh_input_metadata_window()
        assert not hasattr(task, "_metadata_prefetch")
        assert not engine._input_metadata_slots
    finally:
        engine.stop()


@pytest.mark.asyncio
async def test_smaller_pending_window_cancels_distant_prefetch_and_releases_slots(monkeypatch):
    from app.config.settings import AppConfig
    from app.core.task_engine import TaskEngine
    config = AppConfig()
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: config)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    release = asyncio.Event()

    async def fetch(rjcode, *args, **kwargs):
        await release.wait()
        return {"rjcode": rjcode}

    monkeypatch.setattr(MetadataService, "_fetch_by_rj", fetch)
    engine = TaskEngine(max_concurrent=4)
    tasks = [Task(TaskType.AUTO_PROCESS, f"RJ0123456{index}.zip", metadata={
        "scan_id": "scan", "rjcode": f"RJ0123456{index}",
        "input_source_wait": {"next_check_at": 9999999999},
    }) for index in range(4)]
    engine.tasks.update({task.id: task for task in tasks})
    try:
        await engine.refresh_input_metadata_window()
        assert len(engine._input_metadata_slots) == 4
        distant = [task._metadata_prefetch for task in tasks[2:]]
        engine.set_max_concurrent(1)
        await engine.refresh_input_metadata_window()
        assert all(future.cancelled() for future in distant)
        assert engine._input_metadata_slots == {task.id for task in tasks[:2]}
        assert not engine.try_acquire_input_preflight("another")
        config.auto_process.fetch_metadata = False
        await engine.refresh_input_metadata_window()
        assert not engine._input_metadata_slots
        assert not engine._input_metadata_window
    finally:
        release.set()
        engine.stop()
