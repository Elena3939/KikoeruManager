"""真实 PostgreSQL：提交、回滚、幂等、分页与批次结算。"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.activity_log_writer import ActivityLogWriter
from app.core.input_scan_repository import InputScanRepository, path_key
from app.core.input_stability import observe_sources
from app.core.task_engine import Task, TaskType, TaskStatus
from app.models.database import (
    ActivityLog, ActivityLogDailyStats, ConflictWork, InputScanCandidate, InputScanOutbox,
    InputSourceClaim, InputScanRun, Task as TaskRecord,
)


@pytest.fixture
def repository(db_session, db_engine):
    return InputScanRepository(sessionmaker(bind=db_engine))


def discover(repository, tmp_path, name="a.zip"):
    path = tmp_path / name
    path.write_bytes(b"archive")
    scan_id = repository.create_run(str(tmp_path), {})
    repository.discover(scan_id, [{
        "group_key": path_key(str(path)), "source_path": str(path), "members": [str(path)],
    }])
    candidate = repository.due(scan_id)[0]
    evidence, _ = observe_sources([str(path)], {}, checks=3, interval=2, needs_stability=False)
    repository.update_candidate(candidate["id"], candidate["version"], state="ready", evidence=evidence)
    return scan_id, repository.due(scan_id)[0], path


def test_parent_before_atomic_handoff_and_replay(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    assert repository.create_run(str(tmp_path), {}, request_key="another") == scan_id
    with repository.session_factory() as db:
        assert db.query(ActivityLog).count() == 1
        assert db.query(TaskRecord).count() == 0
    assert repository.claim(candidate["id"], candidate["version"])
    task = Task(TaskType.AUTO_PROCESS, str(path))
    assert repository.commit_candidate(candidate["id"], candidate["version"], task) == task.id
    assert repository.commit_candidate(candidate["id"], candidate["version"], task) == task.id
    with repository.session_factory() as db:
        assert db.query(TaskRecord).count() == 1
        assert db.query(InputScanOutbox).count() == 1
        assert db.query(InputSourceClaim).one().owner_id == task.id
        assert db.query(TaskRecord).one().task_metadata["scan_id"] == scan_id
    repository.close_producer(scan_id)
    status = repository.snapshot(scan_id, materialize=True)
    assert status["scan_status"] == "completed"
    assert status["execution_status"] == "waiting"


def test_changed_source_and_failed_commit_leave_no_task(repository, tmp_path, monkeypatch):
    _, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="重新采样"):
        repository.commit_candidate(candidate["id"], candidate["version"], task)
    with repository.session_factory() as db:
        assert db.query(TaskRecord).count() == 0
        assert db.query(InputScanOutbox).count() == 0
        assert db.query(InputScanCandidate).one().state == "ready"


def test_cancel_fences_late_commit_and_preserves_submitted(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    assert repository.cancel(scan_id)
    assert repository.commit_candidate(
        candidate["id"], candidate["version"], Task(TaskType.AUTO_PROCESS, str(path)),
    ) is None
    repository.finish_cancel(scan_id)
    assert repository.snapshot(scan_id)["counts"] == {"cancelled": 1}


def test_due_rotation_does_not_block_later_candidates(repository, tmp_path):
    scan_id = repository.create_run(str(tmp_path), {})
    groups = [{
        "group_key": str(index), "source_path": str(tmp_path / str(index)),
        "members": [str(tmp_path / str(index))],
    } for index in range(270)]
    repository.discover(scan_id, groups)
    first = repository.due(scan_id)
    assert len(first) == 256
    for row in first:
        repository.update_candidate(row["id"], row["version"], state="waiting_stable", delay=60)
    assert len(repository.due(scan_id)) == 14


def test_reliable_log_replay_counts_once_and_rollback_invalidates_nothing(repository):
    writer = ActivityLogWriter()
    payload = {
        "id": "event-id", "event_key": "unique-event", "category": "test",
        "action": "test", "status": "success", "detail": {},
    }
    with repository.session_factory() as db:
        assert writer.insert_once(db, payload)
        assert writer.last_write_ts == 0
        db.rollback()
        assert writer.last_write_ts == 0
        assert db.query(ActivityLog).count() == 0
        assert writer.insert_once(db, payload)
        db.commit()
        assert writer.last_write_ts > 0
        assert not writer.insert_once(db, payload)
        db.commit()
        assert db.query(ActivityLog).count() == 1
        assert db.query(ActivityLogDailyStats.count).scalar() == 1


def test_execution_status_and_lifecycle_survive_replay(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    stale = Task(TaskType.AUTO_PROCESS, str(path), task_id=task.id, metadata=dict(task.task_metadata))
    task.start()
    assert repository.persist_execution(task)
    task.complete()
    assert repository.persist_execution(task, lifecycle=True)
    assert not repository.persist_execution(stale)
    repository.persist_execution(task, lifecycle=True)
    with repository.session_factory() as db:
        assert db.query(TaskRecord).one().status == "completed"
        event = db.query(InputScanOutbox).filter_by(kind="task_lifecycle").one()
        event_id = event.id
    repository.deliver_lifecycle(event_id)
    repository.deliver_lifecycle(event_id)
    with repository.session_factory() as db:
        logs = db.query(ActivityLog).filter_by(task_id=task.id).all()
        assert len(logs) == 1
        assert logs[0].status == "success"
        assert db.get(InputScanOutbox, event_id).delivered_at
    repository.close_producer(scan_id)
    assert repository.snapshot(scan_id, materialize=True)["execution_status"] == "success"
    assert repository.snapshot(scan_id)["coverage"]["first_normal_task_start_at"] == task.started_at.isoformat()
    assert "first_extract_at" not in repository.snapshot(scan_id)["coverage"]


def test_progress_does_not_wait_for_batch_row_lock(repository, tmp_path):
    from sqlalchemy import text

    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    task.start()
    assert repository.persist_execution(task)
    with repository.session_factory.begin() as blocker:
        blocker.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
        with repository.session_factory.kw["bind"].connect() as connection:
            connection.execute(text("SET lock_timeout = '300ms'"))
            connection.commit()
            scoped = InputScanRepository(sessionmaker(bind=connection))
            task.current_step = "测试进度"
            assert scoped.persist_execution(task)
    with repository.session_factory() as db:
        assert db.get(TaskRecord, task.id).current_step == "测试进度"


def test_lifecycle_failure_rolls_back_delivery(repository, tmp_path, monkeypatch):
    from app.core import activity_log_service
    _, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    task.fail("测试失败")
    repository.persist_execution(task, lifecycle=True)
    with repository.session_factory() as db:
        event_id = db.query(InputScanOutbox).filter_by(kind="task_lifecycle").one().id

    def fail(*args, **kwargs):
        raise RuntimeError("测试日志不可用")

    monkeypatch.setattr(activity_log_service, "_build_and_write_task_lifecycle_log", fail)
    with pytest.raises(RuntimeError, match="测试日志不可用"):
        repository.deliver_lifecycle(event_id)
    with repository.session_factory() as db:
        assert db.get(InputScanOutbox, event_id).delivered_at is None
        assert db.query(TaskRecord).one().status == "failed"


def test_ready_backpressure_can_be_excluded(repository, tmp_path):
    scan_id, candidate, _ = discover(repository, tmp_path)
    assert not repository.due(scan_id, include_ready=False)
    assert repository.due(scan_id)[0]["id"] == candidate["id"]


def test_problem_route_is_atomic_and_ignores_normal_watermark(repository, tmp_path):
    from app.core.task_engine import TaskStatus
    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    task.status = TaskStatus.WAITING_MANUAL
    conflict = ConflictWork(
        id="prepared-problem", task_id=task.id, rjcode="RJ01234567",
        conflict_type="DUPLICATE", new_path=str(path), existing_path="owned", status="PENDING",
    )
    repository.commit_candidate(
        candidate["id"], candidate["version"], task, pending_limit=0,
        routed=True, prepared_conflicts=[conflict],
    )
    repository.close_producer(scan_id)
    with repository.session_factory() as db:
        row = db.query(InputScanCandidate).one()
        assert (row.state, row.destination, row.record_id) == ("routed", "problem", "prepared-problem")
        assert db.query(TaskRecord).one().status == "waiting_manual"
        assert db.query(ConflictWork).one().analysis_info["input_scan"]["scan_id"] == scan_id
        assert db.query(InputScanOutbox).count() == 2
    assert repository.snapshot(scan_id)["execution_status"] == "waiting"


def test_failed_route_rolls_back_problem_task_and_outbox(repository, tmp_path, monkeypatch):
    _, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    task.status = TaskStatus.WAITING_MANUAL
    conflict = ConflictWork(
        id="rolled-back-problem", task_id=task.id, rjcode="RJ01234567",
        conflict_type="DUPLICATE", new_path=str(path), status="PENDING",
    )
    def fail(*args, **kwargs):
        raise RuntimeError("提交失败")
    monkeypatch.setattr(repository, "_outbox", fail)
    with pytest.raises(RuntimeError, match="提交失败"):
        repository.commit_candidate(
            candidate["id"], candidate["version"], task,
            routed=True, prepared_conflicts=[conflict],
        )
    with repository.session_factory() as db:
        assert db.query(ConflictWork).count() == 0
        assert db.query(TaskRecord).count() == 0
        assert db.query(InputScanOutbox).count() == 0
        assert db.query(InputScanCandidate).one().task_id is None


def test_stage_preparation_survives_restart_and_handoff(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    stage = str(tmp_path / ("scan_stage_" + "a" * 32))
    repository.prepare_stage(candidate["id"], candidate["version"], stage)
    from pathlib import Path
    Path(stage).mkdir()
    assert repository.stage_paths(scan_id) == [(candidate["id"], stage)]
    task = Task(TaskType.AUTO_PROCESS, str(path), metadata={"linked_subtitle_import": {"id": "pending"}})
    task.status = TaskStatus.COMPLETED
    conflict = ConflictWork(
        id="pending", rjcode="RJ01234567", new_path=str(path), status="PENDING",
        conflict_type="LINKED_SUBTITLE_IMPORT", analysis_info={"preview": {"source_subtitle_dir": stage}},
    )
    repository.commit_candidate(
        candidate["id"], candidate["version"], task, routed=True, prepared_conflicts=[conflict],
    )
    assert repository.stage_paths(scan_id) == []


def test_subtitle_route_without_record_does_not_steal_stage(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    stage = str(tmp_path / ("scan_stage_" + "b" * 32))
    repository.prepare_stage(candidate["id"], candidate["version"], stage)
    task = Task(TaskType.AUTO_PROCESS, str(path), metadata={"linked_subtitle_import": {"id": "missing"}})
    task.status = TaskStatus.COMPLETED
    with pytest.raises(ValueError, match="缺少对应"):
        repository.commit_candidate(candidate["id"], candidate["version"], task, routed=True)
    assert repository.stage_paths(scan_id) == [(candidate["id"], stage)]
    with repository.session_factory() as db:
        assert db.query(TaskRecord).count() == 0


def test_member_replacement_invalidates_evidence_and_releases_removed_claim(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    assert repository.claim(candidate["id"], candidate["version"])
    replacement = tmp_path / "replacement.zip"
    replacement.write_bytes(b"new")
    repository.discover(scan_id, [{
        "group_key": candidate["group_key"], "source_path": str(replacement),
        "members": [str(replacement)], "needs_stability": True,
    }])
    changed = repository.candidate_by_id(candidate["id"])
    assert changed["version"] > candidate["version"]
    assert changed["members"] == [str(replacement)]
    assert changed["source_path"] == str(replacement)
    assert changed["evidence"] == {"needs_stability": True}
    with repository.session_factory() as db:
        assert db.get(InputSourceClaim, path_key(str(path))) is None


def test_route_metrics_and_history_do_not_claim_unperformed_extraction(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    task.start()
    task.status = TaskStatus.WAITING_MANUAL
    problem = ConflictWork(
        id="no-extract", rjcode="RJ01234567", new_path=str(path),
        conflict_type="DUPLICATE", status="PENDING",
    )
    repository.commit_candidate(
        candidate["id"], candidate["version"], task, routed=True, prepared_conflicts=[problem],
    )
    status = repository.snapshot(scan_id)
    assert status["coverage"]["first_task_start_at"] == task.started_at.isoformat()
    assert "first_normal_task_start_at" not in status["coverage"]
    assert "first_extract_at" not in status["coverage"]
    with repository.session_factory() as db:
        event = db.query(InputScanOutbox).filter_by(kind="task_lifecycle").one()
        event_id = event.id
    repository.deliver_lifecycle(event_id)
    with repository.session_factory() as db:
        log = db.query(ActivityLog).filter_by(task_id=task.id).one()
        assert log.detail["extract_performed"] is False
        assert log.detail["scan_id"] == scan_id
        assert log.detail["input_route"]["destination"] == "problem"


def test_extract_milestone_is_monotonic_under_out_of_order_snapshots(repository, tmp_path):
    from datetime import timedelta
    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    task.start()
    first = task.started_at - timedelta(seconds=1)
    task.task_metadata["input_first_extract_at"] = task.started_at.isoformat()
    task.touch_metadata()
    repository.persist_execution(task)
    task.task_metadata["input_first_extract_at"] = first.isoformat()
    task.touch_metadata()
    repository.persist_execution(task)
    assert repository.snapshot(scan_id)["coverage"]["first_extract_at"] == first.isoformat()


def test_derived_task_is_durable_and_root_waits_for_child(repository, tmp_path):
    scan_id, candidate, path = discover(repository, tmp_path)
    parent = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], parent)
    child = Task(TaskType.PROCESS_EXISTING_FOLDER, str(tmp_path / "child"), metadata={
        "scan_id": scan_id, "candidate_id": candidate["id"], "parent_task_id": parent.id,
    })
    repository.register_derived_task(child)
    repository.register_derived_task(child)
    assert set(repository.pending_tasks()) == {parent.id, child.id}
    with repository.session_factory() as db:
        assert db.query(TaskRecord).count() == 2
        assert db.query(InputScanOutbox).filter_by(kind="task_dispatch").count() == 2
        from app.models.database import get_local_now
        for event in db.query(InputScanOutbox).filter_by(kind="task_dispatch"):
            event.delivered_at = get_local_now()
        db.commit()
    assert set(repository.pending_tasks()) == {parent.id, child.id}
    parent.complete()
    repository.persist_execution(parent)
    repository.close_producer(scan_id)
    assert repository.snapshot(scan_id)["execution_status"] == "waiting"
    child.start()
    repository.persist_execution(child)
    assert repository.snapshot(scan_id)["execution_status"] == "running"
    child.complete()
    repository.persist_execution(child, lifecycle=True)
    final = repository.snapshot(scan_id, materialize=True)
    assert final["execution_status"] == "success"
    assert final["task_outcomes"] == {"completed": 1}
    assert final["counts"] == {"submitted": 1}


def test_derived_task_cannot_join_unrelated_scan(repository, tmp_path):
    scan_id, _, _ = discover(repository, tmp_path)
    child = Task(TaskType.PROCESS_EXISTING_FOLDER, "missing", metadata={
        "scan_id": scan_id, "parent_task_id": "missing",
    })
    with pytest.raises(ValueError, match="持久父任务"):
        repository.register_derived_task(child)
    with repository.session_factory() as db:
        assert db.query(TaskRecord).count() == 0
        assert db.query(InputScanOutbox).count() == 0


@pytest.mark.asyncio
async def test_submit_persists_child_before_queue_and_rejects_orphan(repository, tmp_path, monkeypatch):
    from app.core import input_scan_repository
    from app.core.task_engine import TaskEngine

    scan_id, candidate, path = discover(repository, tmp_path)
    parent = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], parent)
    engine = TaskEngine(max_concurrent=1)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    monkeypatch.setattr(engine, "_ensure_task_context", lambda task: None)
    monkeypatch.setattr(input_scan_repository, "InputScanRepository", lambda: repository)
    child = Task(TaskType.PROCESS_EXISTING_FOLDER, str(tmp_path / "child"), metadata={
        "scan_id": scan_id, "parent_task_id": parent.id,
    })
    try:
        await engine.submit(child)
        assert child.id in repository.pending_tasks()
        assert engine.queue.get_nowait() is child
        orphan = Task(TaskType.PROCESS_EXISTING_FOLDER, "missing", metadata={
            "scan_id": scan_id, "parent_task_id": "missing",
        })
        with pytest.raises(ValueError, match="持久父任务"):
            await engine.submit(orphan)
        assert orphan.id not in engine.tasks
        assert engine.queue.empty()
    finally:
        engine.stop()


@pytest.mark.asyncio
async def test_scan_notification_waits_for_producer_and_survives_empty_engine(
    repository, tmp_path, monkeypatch,
):
    from app.config.settings import AppConfig
    from app.core import task_notification_service as notifications
    from app.models.database import NotificationInboxItem

    config = AppConfig()
    config.notification_center.enabled = True
    config.notification_email.enabled = False
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    monkeypatch.setattr("app.models.database.SessionLocal", repository.session_factory)
    monkeypatch.setattr(notifications, "_sse_broadcast", lambda event: None)
    scan_id, candidate, path = discover(repository, tmp_path)
    parent = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], parent)
    parent.complete()
    repository.persist_execution(parent)
    await notifications._check_and_write(parent)
    notifications.write_input_scan_notification(scan_id, repository=repository)
    repository.snapshot(scan_id, materialize=True)
    with repository.session_factory() as db:
        assert db.query(NotificationInboxItem).count() == 0
        assert db.query(InputScanOutbox).filter_by(kind="scan_notification").count() == 0

    child = Task(TaskType.PROCESS_EXISTING_FOLDER, "child", metadata={
        "scan_id": scan_id, "parent_task_id": parent.id,
    })
    repository.register_derived_task(child)
    repository.close_producer(scan_id)
    pending = repository.snapshot(scan_id, materialize=True)
    assert pending["task_outcomes"] == {"pending": 1}
    notifications.write_input_scan_notification(scan_id, repository=repository)
    with repository.session_factory() as db:
        assert db.query(NotificationInboxItem).count() == 0
        assert db.query(InputScanOutbox).filter_by(kind="scan_notification").count() == 0
    child.complete()
    repository.persist_execution(child)
    repository.snapshot(scan_id, materialize=True)
    repository.snapshot(scan_id, materialize=True)
    with repository.session_factory() as db:
        assert db.query(InputScanOutbox).filter_by(kind="scan_notification").count() == 1

    # 写入失败必须留给扫描 outbox 重试，不能被原来的 best-effort 路径吞掉。
    def unavailable():
        raise RuntimeError("通知数据库暂时不可用")
    with monkeypatch.context() as scoped:
        scoped.setattr("app.models.database.SessionLocal", unavailable)
        with pytest.raises(RuntimeError, match="暂时不可用"):
            notifications.write_input_scan_notification(scan_id, repository=repository)
    notifications.write_input_scan_notification(scan_id, repository=repository)
    notifications.write_input_scan_notification(scan_id, repository=repository)
    with repository.session_factory() as db:
        inbox = db.query(NotificationInboxItem).one()
        assert inbox.event_type == "completed"
        assert set(inbox.task_ids) == {parent.id, child.id}
        assert "共 1 组" in inbox.summary
        assert inbox.batch_id == repository.snapshot(scan_id)["batch_id"]


@pytest.mark.parametrize("status", ["paused", "waiting_retry", "waiting_manual", "processing"])
def test_notification_distinguishes_manual_from_unfinished_work(repository, tmp_path, status):
    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    with repository.session_factory.begin() as db:
        db.get(TaskRecord, task.id).status = status
    repository.close_producer(scan_id)
    snapshot = repository.snapshot(scan_id, materialize=True)
    assert snapshot["task_outcomes"] == {status: 1}
    with repository.session_factory() as db:
        events = db.query(InputScanOutbox).filter_by(kind="scan_notification").all()
        assert len(events) == (1 if status == "waiting_manual" else 0)


@pytest.mark.parametrize("producer,closed,execution,expected", [
    (False, False, "success", "incomplete"),
    (True, False, "success", "incomplete"),
    (True, True, "waiting", "incomplete"),
    (True, True, "running", "incomplete"),
    (True, True, "success", "success"),
    (True, True, "partial", "partial_success"),
    (True, True, "failed", "failed"),
    (True, True, "cancelled", "cancelled"),
])
def test_scan_history_protocol_requires_both_closure_barriers(producer, closed, execution, expected):
    from app.core.input_scan_protocol import scan_batch_status
    assert scan_batch_status({
        "schema_version": 2, "scan_id": "scan", "producer_closed": producer,
        "scan_closed": closed, "execution_status": execution,
    }) == expected
    assert scan_batch_status({"execution_status": execution}) is None


def test_scan_failure_notifies_without_creating_a_task(repository, tmp_path, monkeypatch):
    from app.config.settings import AppConfig
    from app.core import task_notification_service as notifications
    from app.models.database import NotificationInboxItem

    config = AppConfig()
    config.notification_center.enabled = True
    config.notification_email.enabled = False
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    monkeypatch.setattr("app.models.database.SessionLocal", repository.session_factory)
    monkeypatch.setattr(notifications, "_sse_broadcast", lambda event: None)
    scan_id, candidate, _ = discover(repository, tmp_path)
    repository.update_candidate(
        candidate["id"], candidate["version"], state="failed", reason="源文件不可读",
    )
    repository.close_producer(scan_id)
    repository.snapshot(scan_id, materialize=True)
    notifications.write_input_scan_notification(scan_id, repository=repository)
    notifications.write_input_scan_notification(scan_id, repository=repository)
    with repository.session_factory() as db:
        inbox = db.query(NotificationInboxItem).one()
        assert inbox.event_type == "failed"
        assert inbox.primary_task_id is None
        assert inbox.task_ids == []
        assert "失败 1 组" in inbox.summary
        assert db.query(TaskRecord).count() == 0


def test_scan_history_aggregate_and_persisted_rollup_agree(repository, tmp_path):
    from app.core.activity_log_aggregator import merge_activity_rows
    from app.models.database import ActivityLogRollup

    scan_id, candidate, path = discover(repository, tmp_path)
    task = Task(TaskType.AUTO_PROCESS, str(path))
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    task.complete()
    repository.persist_execution(task, lifecycle=True)
    with repository.session_factory() as db:
        event_id = db.query(InputScanOutbox).filter_by(kind="task_lifecycle").one().id
    repository.deliver_lifecycle(event_id)
    for close, expected in [(False, "incomplete"), (True, "success")]:
        if close:
            repository.close_producer(scan_id)
        snapshot = repository.snapshot(scan_id, materialize=True)
        with repository.session_factory() as db:
            items = merge_activity_rows(db.query(ActivityLog).all())
            parent = next(item for item in items if item["id"] == snapshot["batch_id"])
            assert parent["status"] == expected
            rollup = db.query(ActivityLogRollup).filter_by(
                rollup_key=f"batch:{snapshot['batch_id']}",
            ).one()
            assert rollup.latest_status == expected
