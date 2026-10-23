"""库存重命名结果与问题作品之间的关联回归。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.api_rename_failure_service import resolve_api_rename_successes
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


def problem(identifier, library="a", path="/library/RJ01000001", operation="api_rename"):
    return SimpleNamespace(
        id=identifier, rjcode="RJ01000001", new_path=path, task_id=None,
        new_metadata={"library_id": library, "source_operation": operation, "error_message": "之前查询失败"},
    )


@pytest.fixture
def recovery_db(monkeypatch):
    db = Mock()
    query = db.query.return_value.filter.return_value
    query.all.return_value = []
    monkeypatch.setattr("app.models.database.get_db", lambda: iter([db]))
    audit = Mock()
    notify = Mock()
    monkeypatch.setattr("app.core.activity_log_service.log_conflict_resolution_activity", audit)
    monkeypatch.setattr("app.core.api_rename_failure_service.notify_api_rename_problem_changed", notify)
    return db, query, audit, notify


@pytest.mark.parametrize("new_path", ["/library/新名称", "/library/RJ01000001"])
def test_success_and_verified_no_change_close_only_same_library_source(recovery_db, new_path):
    db, query, audit, notify = recovery_db
    matched = problem("原问题")
    query.all.return_value = [
        matched, problem("同RJ其它库存", library="b"),
        problem("同RJ其它路径", path="/library/copy/RJ01000001"),
        problem("同路径其它业务", operation="import"),
    ]
    ids = resolve_api_rename_successes([
        {"library_id": "a", "path": matched.new_path, "new_path": new_path, "success": True},
    ], batch_id="batch")
    assert ids == ["原问题"]
    db.delete.assert_called_once_with(matched)
    db.commit.assert_called_once()
    assert audit.call_args.kwargs["source_path"] == matched.new_path
    assert audit.call_args.kwargs["final_path"] == new_path
    assert audit.call_args.kwargs["extra_detail"]["batch_id"] == "batch"
    assert audit.call_args.kwargs["extra_detail"]["original_failure_reason"] == "之前查询失败"
    notify.assert_called_once()


def test_partial_batch_only_closes_confirmed_successes_in_one_transaction(recovery_db):
    db, query, audit, _ = recovery_db
    first, second, failed = problem("成功a"), problem("成功b", library="b"), problem("失败", path="/library/RJ01000002")
    query.all.return_value = [first, second, failed]
    ids = resolve_api_rename_successes([
        {"library_id": "a", "path": first.new_path, "success": True},
        {"library_id": "b", "path": second.new_path, "success": True},
        {"library_id": "a", "path": failed.new_path, "success": False},
    ])
    assert ids == ["成功a", "成功b"]
    assert db.delete.call_count == 2
    assert audit.call_count == 2
    db.commit.assert_called_once()


def test_failed_or_unconfirmed_results_cannot_close_problems(recovery_db):
    db, _, audit, notify = recovery_db
    assert resolve_api_rename_successes([
        {"library_id": "a", "path": "/library/RJ01000001", "success": False},
        {"library_id": "a", "path": "/library/RJ01000002"},
    ]) == []
    db.query.assert_not_called()
    audit.assert_not_called()
    notify.assert_not_called()


def test_failed_commit_does_not_emit_recovery_or_success_audit(recovery_db):
    db, query, audit, notify = recovery_db
    query.all.return_value = [problem("原问题")]
    db.commit.side_effect = RuntimeError("写入失败")
    assert resolve_api_rename_successes([
        {"library_id": "a", "path": "/library/RJ01000001", "success": True},
    ]) == []
    db.rollback.assert_called_once()
    audit.assert_not_called()
    notify.assert_not_called()


def test_import_success_cannot_close_api_rename_problem_with_same_rj(recovery_db):
    db, query, _, _ = recovery_db
    renamed = problem("库存重命名失败")
    query.filter.return_value.all.return_value = [renamed]
    engine = TaskEngine(max_concurrent=1)
    task = Task(task_type=TaskType.AUTO_PROCESS, source_path="/download/RJ01000001.zip", rjcode="RJ01000001")
    task.status = TaskStatus.COMPLETED
    task.output_path = "/library/new/RJ01000001"
    engine._resolve_completed_failure_followups(task)
    db.delete.assert_not_called()


@pytest.mark.parametrize("explicit_id", [False, True])
def test_extract_retry_cannot_close_api_rename_problem_at_same_path(recovery_db, explicit_id):
    db, query, audit, _ = recovery_db
    renamed = problem("库存重命名失败")
    query.filter.return_value.first.return_value = renamed
    engine = TaskEngine(max_concurrent=1)
    task = Task(task_type=TaskType.AUTO_PROCESS, source_path=renamed.new_path, rjcode=renamed.rjcode)
    task.status = TaskStatus.COMPLETED
    if explicit_id:
        task.task_metadata = {"retry_conflict_id": renamed.id}
    engine._resolve_retry_extract_conflict(task)
    db.delete.assert_not_called()
    audit.assert_not_called()
