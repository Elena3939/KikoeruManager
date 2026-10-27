"""不依赖数据库服务的占用交接与重试接口契约测试。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import input_scan_repository as repository
from app.models import database


def fake_db(tmp_path):
    source = str(tmp_path / "RJ14131437.7z")
    conflict = SimpleNamespace(
        id="problem", task_id="old", new_path=source, status="PENDING",
        conflict_type="EXTRACT_FAILED", rjcode="RJ14131437",
        new_metadata={"failed_task_id": "old"},
    )
    claims = [
        SimpleNamespace(
            owner_type="task", owner_id="old", source_path=path,
            path_key=repository.path_key(path),
        ) for path in (source, source + ".002")
    ]
    record = SimpleNamespace(status="waiting_manual", source_path=source)
    db = Mock()

    def query(model):
        result = Mock()
        result.filter.return_value = result
        result.filter_by.return_value = result
        result.all.return_value = claims if model is database.InputSourceClaim else [conflict]
        result.first.return_value = conflict if model is database.ConflictWork else None
        result.__iter__ = lambda _: iter(claims)
        return result

    db.query.side_effect = query
    db.get.return_value = record
    return db, conflict, claims, record


def test_handoff_preserves_whole_group_and_checks_remaining_owners(tmp_path):
    db, conflict, claims, _ = fake_db(tmp_path)
    repository.handoff_conflict_claims(db, conflict, "new")
    assert [claim.owner_id for claim in claims] == ["new", "new"]
    db.flush.assert_called_once()


@pytest.mark.parametrize("status", ["processing", "pending", "paused", "waiting_retry"])
def test_active_owner_is_not_transferred(tmp_path, status):
    db, conflict, claims, record = fake_db(tmp_path)
    record.status = status
    with pytest.raises(repository.SourceOccupied):
        repository.handoff_conflict_claims(db, conflict, "new")
    assert [claim.owner_id for claim in claims] == ["old", "old"]


def test_same_task_but_different_source_is_not_transferred(tmp_path):
    db, conflict, claims, record = fake_db(tmp_path)
    record.source_path += ".other"
    with pytest.raises(repository.SourceOccupied):
        repository.handoff_conflict_claims(db, conflict, "new")
    assert [claim.owner_id for claim in claims] == ["old", "old"]


@pytest.mark.parametrize("blocker", ["prepared_candidate", "other_pending_problem"])
def test_handoff_keeps_other_unfinished_work_protected(tmp_path, blocker):
    db, conflict, claims, _ = fake_db(tmp_path)
    original_query = db.query.side_effect

    def query(model):
        result = original_query(model)
        if blocker == "prepared_candidate" and model is database.InputScanCandidate:
            result.first.return_value = SimpleNamespace(
                preparation={"normalization": {"status": "prepared"}},
            )
        if blocker == "other_pending_problem" and model is database.ConflictWork.id:
            result.first.return_value = ("another-problem",)
        return result

    db.query.side_effect = query
    with pytest.raises(repository.SourceOccupied):
        repository.handoff_conflict_claims(db, conflict, "new")
    assert [claim.owner_id for claim in claims] == ["old", "old"]


def test_legacy_retry_repairs_claims_before_archive(tmp_path):
    db, conflict, claims, _ = fake_db(tmp_path)
    conflict.task_id = "new"
    repository.check_input_claims(db, [conflict.new_path], task_id="new")
    assert [claim.owner_id for claim in claims] == ["new", "new"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse", [False, True])
async def test_retry_hands_off_before_dispatch(tmp_path, monkeypatch, reuse):
    from app.api import routes
    from app.core import conflict_retry_activity
    from app.core.task_engine import Task, TaskStatus, TaskType

    db, conflict, claims, _ = fake_db(tmp_path)
    (tmp_path / "RJ14131437.7z").write_bytes(b"archive")
    existing = Task(TaskType.AUTO_PROCESS, conflict.new_path)
    existing.status = TaskStatus.PENDING
    engine = SimpleNamespace(
        get_all_tasks=lambda: [existing] if reuse else [],
        get_task=lambda _: None, cleanup_retry_output_artifacts=Mock(),
    )
    submitted = []

    async def submit(task):
        db.commit.assert_called_once()
        assert conflict.task_id == task.id
        assert [claim.owner_id for claim in claims] == [task.id, task.id]
        submitted.append(task)

    engine.submit = AsyncMock(side_effect=submit)
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)
    monkeypatch.setattr(conflict_retry_activity, "retry_origin", lambda *args: {})
    monkeypatch.setattr(conflict_retry_activity, "log_retry_queued", Mock())
    result = await routes._retry_extract_failed_conflict(conflict.id, None, batch_id="batch")
    assert result["success"]
    assert result["already_running"] == reuse
    assert [claim.owner_id for claim in claims] == [result["task_id"], result["task_id"]]
    assert len(submitted) == (0 if reuse else 1)


@pytest.mark.asyncio
async def test_rejected_handoff_never_dispatches(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app.api import routes
    from app.core import conflict_retry_activity

    db, conflict, claims, record = fake_db(tmp_path)
    record.status = "processing"
    (tmp_path / "RJ14131437.7z").write_bytes(b"archive")
    engine = SimpleNamespace(
        get_all_tasks=lambda: [], get_task=lambda _: None,
        cleanup_retry_output_artifacts=Mock(), submit=AsyncMock(),
    )
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)
    monkeypatch.setattr(conflict_retry_activity, "retry_origin", lambda *args: {})
    with pytest.raises(HTTPException) as error:
        await routes._retry_extract_failed_conflict(conflict.id, None, batch_id="batch")
    assert error.value.status_code == 409
    engine.submit.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_called_once()
    assert [claim.owner_id for claim in claims] == ["old", "old"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["commit", "submit"])
async def test_failed_submission_restores_problem_ownership(tmp_path, monkeypatch, failure):
    from app.api import routes
    from app.core import conflict_retry_activity

    db, conflict, claims, _ = fake_db(tmp_path)
    (tmp_path / "RJ14131437.7z").write_bytes(b"archive")
    engine = SimpleNamespace(
        get_all_tasks=lambda: [], get_task=lambda _: None,
        cleanup_retry_output_artifacts=Mock(), submit=AsyncMock(),
    )
    if failure == "commit":
        db.commit.side_effect = RuntimeError("提交失败")
    else:
        engine.submit.side_effect = RuntimeError("入队失败")
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)
    monkeypatch.setattr(conflict_retry_activity, "retry_origin", lambda *args: {})
    with pytest.raises(RuntimeError):
        await routes._retry_extract_failed_conflict(conflict.id, None, batch_id="batch")
    if failure == "commit":
        engine.submit.assert_not_called()
    else:
        assert db.commit.call_count == 2
        assert conflict.status == "PENDING"
        assert conflict.task_id == "old"
        assert conflict.new_metadata == {"failed_task_id": "old"}
        assert [claim.owner_id for claim in claims] == ["old", "old"]


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict_type", ["EXTRACT_FAILED", "PROCESS_FAILED"])
async def test_retry_dispatch_can_immediately_enqueue_real_volume_group(
    tmp_path, monkeypatch, conflict_type,
):
    from app.api import routes
    from app.core import conflict_retry_activity, deferred_archive_service

    db, conflict, claims, record = fake_db(tmp_path)
    members = [tmp_path / f"RJ14131437.7z.{index:03d}" for index in (1, 2)]
    for index, (path, claim) in enumerate(zip(members, claims)):
        path.write_bytes(bytes([index]) * 32)
        claim.source_path = str(path)
        claim.path_key = repository.path_key(str(path))
    conflict.new_path = record.source_path = str(members[0])
    conflict.conflict_type = conflict_type
    original_query = db.query.side_effect

    def query(model):
        if model is database.DeferredArchiveJob or model is database.DeferredArchiveJob.target_manifest:
            result = Mock()
            result.filter.return_value = result
            result.first.return_value = None
            result.all.return_value = []
            return result
        result = original_query(model)
        if model is database.ConflictWork:
            # 旧问题尚未关联新任务，不能伪造出可用于历史交接的重试记录。
            result.all.return_value = []
        return result

    db.query.side_effect = query
    monkeypatch.setattr(deferred_archive_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(deferred_archive_service, "get_config", lambda: SimpleNamespace(
        storage=SimpleNamespace(processed_archives_path=str(tmp_path / "processed")),
    ))
    archive_service = deferred_archive_service.DeferredArchiveService()
    monkeypatch.setattr(archive_service, "_write_activity", Mock())
    with pytest.raises(repository.SourceOccupied, match="task:old"):
        archive_service.enqueue_sync(str(members[0]), task_id="new")
    db.add.assert_not_called()
    queued = []

    async def submit(task):
        # 模拟执行器立即跑完入库，归档不能依赖 submit 返回后的数据库更新。
        db.commit.assert_called_once()
        assert conflict.task_id == task.id
        queued.append(await archive_service.enqueue_task(task))
        assert task.task_metadata["archive_queue_status"] == "pending"
        assert task.task_metadata["archive_volume_count"] == 2

    engine = SimpleNamespace(
        get_all_tasks=lambda: [], get_task=lambda _: None,
        cleanup_retry_output_artifacts=Mock(), submit=AsyncMock(side_effect=submit),
    )
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)
    monkeypatch.setattr(conflict_retry_activity, "retry_origin", lambda *args: {})
    monkeypatch.setattr(conflict_retry_activity, "log_retry_queued", Mock())

    result = await routes._retry_extract_failed_conflict(conflict.id, None, batch_id="batch")

    assert queued[0]["queued"] is True
    assert {claim.owner_id for claim in claims} == {result["task_id"]}
    job = db.add.call_args.args[0]
    assert job.task_id == result["task_id"]
    assert {item["source_path"] for item in job.source_manifest} == {str(path) for path in members}
    assert record.status == "waiting_manual"
    assert all(path.exists() for path in members)
