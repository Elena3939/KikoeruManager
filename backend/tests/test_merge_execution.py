"""后台合并提交幂等、进度可查询、失败后可复用预览重试。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import routes
from app.core import conflict_resolution_service as resolution
from app.core import merge_execution_service as execution


@pytest.mark.asyncio
async def test_submit_returns_before_merge_finishes_and_duplicate_does_not_restart(monkeypatch):
    service = execution.MergeExecutionService()
    monkeypatch.setattr(execution, "merge_execution_service", service)
    preview = SimpleNamespace(_merge_sessions={"session": SimpleNamespace(conflict_id="conflict")},
                              normalize_action=lambda value: value)
    monkeypatch.setattr(resolution, "get_conflict_resolution_service", lambda: preview)
    gate = asyncio.Event()

    async def merge(*args):
        await asyncio.to_thread(execution.merge_progress.get(), "写入 2/3", 60)
        await gate.wait()
        return {"final_path": "/library/work"}

    worker = AsyncMock(side_effect=merge)
    monkeypatch.setattr(routes, "_resolve_conflict_inline", worker)
    payload = {"action": "MERGE", "merge_session_id": "session"}
    response = await routes.resolve_conflict("conflict", payload)
    assert response["async"] and response["status"] == "running"
    await routes.resolve_conflict("conflict", payload)
    # HTTP 提交已经返回，后台仍等待写入完成。
    task = service.workers["conflict"]
    for _ in range(50):
        if service.jobs["conflict"]["percent"] == 60:
            break
        await asyncio.sleep(0.01)
    assert (await routes.get_merge_execution("conflict"))["message"] == "写入 2/3"
    assert worker.call_count == 1 and not task.done()
    with pytest.raises(HTTPException) as error:
        await routes.resolve_conflict("conflict", {"action": "SKIP"})
    assert error.value.status_code == 409
    gate.set()
    await task
    assert (await routes.get_merge_execution("conflict"))["status"] == "completed"
    await routes.resolve_conflict("conflict", payload)
    assert worker.call_count == 1


@pytest.mark.asyncio
async def test_failure_is_visible_and_can_retry_without_reextracting():
    service = execution.MergeExecutionService()

    async def fail():
        raise OSError("目标磁盘空间不足")

    service.submit("conflict", fail)
    await service.workers["conflict"]
    assert service.jobs["conflict"]["error"] == "目标磁盘空间不足"
    operation = AsyncMock(return_value={"final_path": "/work"})
    assert service.submit("conflict", operation)["status"] == "running"
    await service.workers["conflict"]
    assert service.jobs["conflict"]["status"] == "completed"
    operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_preview_rejected_without_implicitly_extracting(monkeypatch):
    monkeypatch.setattr(execution, "merge_execution_service", execution.MergeExecutionService())
    monkeypatch.setattr(resolution, "get_conflict_resolution_service", lambda: SimpleNamespace(
        _merge_sessions={}, normalize_action=lambda value: value,
    ))
    with pytest.raises(HTTPException) as error:
        await routes.resolve_conflict("conflict", {"action": "MERGE", "merge_session_id": "gone"})
    assert error.value.status_code == 409


def test_file_merge_reports_progress_and_preserves_sources_on_write_failure(tmp_path, monkeypatch):
    from app.core import folder_compare_service as folders
    source, target, temp = (tmp_path / name for name in ("new", "old", "temp"))
    for path in (source, target, temp):
        path.mkdir()
    (source / "new.txt").write_text("new")
    (target / "old.txt").write_text("old")
    monkeypatch.setattr(folders, "get_config", lambda: SimpleNamespace(storage=SimpleNamespace(temp_path=str(temp))))
    compare = folders.FolderCompareService()
    messages = []
    token = execution.merge_progress.set(lambda message, percent: messages.append((message, percent)))
    copy = folders.shutil.copy2

    def fail_copy(*args):
        raise OSError("磁盘空间不足")

    try:
        monkeypatch.setattr(folders.shutil, "copy2", fail_copy)
        with pytest.raises(OSError, match="磁盘空间不足"):
            compare.apply_merge(str(source), str(target), {}, str(target))
        assert (source / "new.txt").read_text() == "new"
        assert (target / "old.txt").read_text() == "old"
        assert not list(temp.iterdir())
        monkeypatch.setattr(folders.shutil, "copy2", copy)
        compare.apply_merge(str(source), str(target), {}, str(target))
        assert {path.name for path in target.iterdir()} == {"new.txt", "old.txt"}
        assert messages[-1][1] == 90
        assert any("2/2" in message for message, _ in messages)
    finally:
        execution.merge_progress.reset(token)
