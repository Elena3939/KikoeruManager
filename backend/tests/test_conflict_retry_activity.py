"""问题作品重试批次与原批次结算回归；纯单元用例无需数据库。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import routes
from app.core import activity_log_service as logs
from app.core import conflict_retry_activity as retry
from app.core.activity_log_aggregator import merge_activity_rows_from_dicts
from app.core.activity_log_lite import build_lite_item
from app.core.task_engine import Task, TaskStatus, TaskType


def row(log_id, task_id, batch_id, *, action="task_finished", status="success", **detail):
    return {
        "id": log_id, "task_id": task_id, "batch_id": batch_id,
        "category": "auto_import", "action": action, "status": status,
        "summary": "作品处理完成", "created_at": "2026-10-26T10:00:00",
        "detail": {"batch_id": batch_id, **detail},
    }


@pytest.mark.parametrize("task_type", [TaskType.AUTO_PROCESS, TaskType.PROCESS_EXISTING_FOLDER, TaskType.RENAME])
def test_retry_lifecycle_keeps_two_distinct_idempotent_events(monkeypatch, task_type):
    events = []
    monkeypatch.setattr(logs, "write_activity_log", lambda **event: events.append(event))
    task = Task(task_type, "/missing/RJ01234567.zip", metadata={
        "retry_from_conflicts": True, "retry_batch_id": "retry-batch", "batch_id": "retry-batch",
        "retry_origin_task_id": "original-task", "retry_origin_batch_id": "original-batch",
        "retry_origin_category": "extract", "retry_origin_started_at": "2026-10-25T10:00:00",
    })
    task.status = TaskStatus.FAILED
    task.error_message = "密码未命中"
    logs._build_and_write_task_lifecycle_log(
        logs._snapshot_task_for_lifecycle(task), transaction=object(), event_key="terminal-event",
    )
    origin, current = events
    assert origin["event_key"] == "terminal-event:retry-origin"
    assert current["event_key"] == "terminal-event"
    assert origin["category"] == "extract"
    assert origin["task_id"] == "original-task"
    assert origin["detail"]["batch_id"] == "original-batch"
    assert origin["detail"]["task_started_at"] == "2026-10-25T10:00:00"
    assert origin["detail"]["retry_task_id"] == task.id
    assert current["category"] == "auto_import"
    assert current["task_id"] == task.id
    assert current["detail"]["batch_id"] == "retry-batch"
    assert current["summary"].startswith("重试作品")


def test_legacy_reused_task_does_not_lose_its_original_batch(monkeypatch):
    events = []
    monkeypatch.setattr(logs, "write_activity_log", lambda **event: events.append(event))
    task = Task(TaskType.AUTO_PROCESS, "/missing.zip", metadata={
        "retry_from_conflicts": True, "batch_id": "existing-batch",
    })
    task.status = TaskStatus.FAILED
    logs._build_and_write_task_lifecycle_log(logs._snapshot_task_for_lifecycle(task))
    assert len(events) == 1
    assert events[0]["detail"]["batch_id"] == "existing-batch"


def test_repeated_retry_preserves_root_identity():
    origin = {"retry_origin_task_id": "root", "retry_origin_batch_id": "root-batch"}
    conflict = SimpleNamespace(new_metadata=origin, task_id="previous-retry")
    assert retry.retry_origin(Mock(), Mock(), conflict) == origin


@pytest.mark.asyncio
async def test_batch_submits_once_and_keeps_partial_submission_errors(monkeypatch):
    batches = []

    async def submit(conflict_id, payload, *, batch_id):
        batches.append(batch_id)
        if conflict_id == "missing":
            raise routes.HTTPException(404, "问题作品不存在")
        if conflict_id == "broken":
            raise RuntimeError("提交异常")
        return {"success": True, "task_id": f"task-{conflict_id}", "already_running": False}

    audit = Mock()
    monkeypatch.setattr(routes, "_retry_extract_failed_conflict", submit)
    monkeypatch.setattr(retry, "log_retry_batch", audit)
    result = await routes.retry_conflicts_batch(routes.ConflictBatchRetryRequest(items=[
        {"conflict_id": "first"}, {"conflict_id": "missing"}, {"conflict_id": "broken"},
    ]))
    assert len(set(batches)) == 1
    assert batches[0] == result["batch_id"]
    assert [item["success"] for item in result["items"]] == [True, False, False]
    audit.assert_called_once_with(result["batch_id"], result["items"])


@pytest.mark.asyncio
async def test_duplicate_batch_members_are_rejected_before_submit(monkeypatch):
    submit = AsyncMock()
    monkeypatch.setattr(routes, "_retry_extract_failed_conflict", submit)
    with pytest.raises(routes.HTTPException):
        await routes.retry_conflicts_batch(routes.ConflictBatchRetryRequest(items=[
            {"conflict_id": "same"}, {"conflict_id": "same"},
        ]))
    submit.assert_not_called()


def test_all_submission_failures_are_audited_but_reuse_is_not_a_new_batch(monkeypatch):
    audit = Mock()
    monkeypatch.setattr(logs, "write_activity_log", audit)
    retry.log_retry_batch("failed", [{"conflict_id": "gone", "success": False, "message": "已删除"}])
    event = audit.call_args.kwargs
    assert event["status"] == "failed"
    assert event["detail"]["submission_failed_count"] == 1
    retry.log_retry_batch("reuse", [{"success": True, "already_running": True}])
    assert audit.call_count == 1


@pytest.mark.parametrize("closed", [True, False])
def test_parent_recalculation_respects_scan_barriers(monkeypatch, closed):
    from app.core import activity_log_batch_list

    detail = {
        "created_count": 1, "schema_version": 2, "scan_id": "scan",
        "producer_closed": closed, "scan_closed": closed, "execution_status": "failed",
    }
    parent_row = row("original", "original-batch", "original-batch", action="batch_start", **detail)
    projected = row("projection", "original-task", "original-batch", retry_projection=True)
    projected["created_at"] = "2026-10-26T11:00:00"
    parent = SimpleNamespace(id="original", detail=detail, status="failed")
    db = Mock()
    db.info = {}
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = parent
    monkeypatch.setattr(activity_log_batch_list, "compact_import_rows", lambda *_: deepcopy([parent_row, projected]))
    retry.sync_retry_parent(db, [projected])
    assert parent.status == ("success" if closed else "incomplete")
    assert parent.detail["retry_updated_at"]
    if closed:
        assert parent.detail["execution_status"] == "success"
        assert parent.detail["original_execution_status"] == "failed"
        assert parent.detail["latest_activity_at"] == "2026-10-26T11:00:00"


def test_retry_batch_and_original_batch_each_count_one_member():
    old_parent = row("original", "old-batch", "old-batch", action="batch_start", created_count=1)
    failed = row("failure", "old-task", "old-batch", status="failed")
    projected = row("projection", "old-task", "old-batch", retry_projection=True)
    projected["created_at"] = "2026-10-26T11:00:00"
    new_parent = row(
        "retry", "retry-batch", "retry-batch", action="batch_start",
        mode="conflict_retry_batch", created_count=1, requested_count=1,
    )
    current = row("current", "new-task", "retry-batch", mode="conflict_retry_item")
    roots = merge_activity_rows_from_dicts([old_parent, failed, projected, new_parent, current])
    assert {item["id"] for item in roots} == {"original", "retry"}
    for item in roots:
        assert item["status"] == "success"
        assert item["detail"]["result_task_count"] == 1
    retry_lite = build_lite_item(next(item for item in roots if item["id"] == "retry"))
    assert retry_lite["category_label"] == "重试作品"
    assert retry_lite["outcome_label"] == "重试成功"
    assert retry_lite["summary"].startswith("重试作品")


def test_retry_batch_remains_running_until_all_members_finish():
    parent = row("batch", "batch", "batch", action="batch_start",
                 mode="conflict_retry_batch", created_count=2, requested_count=2)
    failed = row("failed", "one", "batch", status="failed", mode="conflict_retry_item")
    result = merge_activity_rows_from_dicts([parent, failed])[0]
    assert result["status"] == "incomplete"


def test_retry_subtitle_handoff_is_not_reported_as_imported():
    current = row("current", "retry", "batch", mode="conflict_retry_item",
                  source_mode="linked_translation_archive_pending")
    result = merge_activity_rows_from_dicts([current])[0]
    item = build_lite_item(result)
    assert "字幕" in item["outcome_label"]
    assert item["outcome_label"] != "重试成功"
    assert item["category_label"] == "重试作品"
    assert build_lite_item(current)["outcome_label"] == "待字幕补配"


def test_queued_projection_keeps_submission_time_when_writer_is_delayed(monkeypatch):
    audit = Mock()
    monkeypatch.setattr(logs, "write_activity_log", audit)
    task = Task(TaskType.AUTO_PROCESS, "/missing.zip", metadata={
        "retry_origin_task_id": "original", "retry_origin_batch_id": "old",
        "retry_origin_category": "auto_import", "retry_batch_id": "retry",
    })
    retry.log_retry_queued(task)
    assert audit.call_args.kwargs["created_at"] == task.created_at


def test_retry_rollup_waits_for_missing_member_results():
    from app.core.activity_log_rollup_service import _parent_status

    parent = SimpleNamespace(detail={
        "mode": "conflict_retry_batch", "created_count": 2, "submission_failed_count": 1,
    })
    assert _parent_status(parent, "failed", 1) == "incomplete"
    assert _parent_status(parent, "success", 2) == "partial_success"


def test_original_batch_is_running_while_failed_member_is_retried():
    parent = row("parent", "old", "old", action="batch_start", created_count=2)
    failed = row("failed", "one", "old", status="failed")
    queued = row("queued", "two", "old", action="task_finished_incomplete",
                 status="incomplete", retry_projection=True)
    assert merge_activity_rows_from_dicts([parent, failed, queued])[0]["status"] == "incomplete"


def test_parent_cache_is_invalidated_only_after_commit(monkeypatch):
    from sqlalchemy.orm import Session
    from app.core import activity_log_writer

    cache = Mock()
    monkeypatch.setattr(activity_log_writer, "get_activity_log_row_dict_cache", lambda: cache)
    writer = activity_log_writer.ActivityLogWriter()
    with Session() as db:
        db.info["_activity_log_parent_changed"] = True
        writer.invalidate_after_commit(db)
        cache.invalidate.assert_not_called()
        db.commit()
        cache.invalidate.assert_called_once()
