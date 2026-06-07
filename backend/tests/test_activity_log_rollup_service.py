from datetime import datetime, timedelta
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.core.activity_log_rollup_service import ActivityLogRollupService
from app.core.activity_log_writer import ActivityLogWriter
from app.models.database import ActivityLog, ActivityLogRollup, Base


def _testing_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _payload(
    log_id: str,
    *,
    status: str,
    batch_id: str = "batch-1",
    created_at: datetime,
):
    return {
        "id": log_id,
        "category": "auto_import",
        "action": "batch_start" if log_id == "parent" else "task_finished",
        "status": status,
        "summary": log_id,
        "detail": {"batch_id": batch_id},
        "rjcode": "RJ123456",
        "task_id": f"task-{log_id}",
        "source_path": f"/tmp/{log_id}.zip",
        "created_at": created_at,
        "batch_id": batch_id,
        "session_key": batch_id,
        "parent_id": None,
    }


def test_activity_log_writer_updates_rollups(monkeypatch):
    SessionLocal = _testing_session()

    import app.models.database as database_module
    import app.core.activity_log_rollup_service as rollup_module

    monkeypatch.setattr(database_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(rollup_module, "SessionLocal", SessionLocal)

    now = datetime(2026, 1, 1, 8, 0, 0)
    writer = ActivityLogWriter()
    writer._flush([
        _payload("parent", status="success", created_at=now),
        _payload("child-ok", status="success", created_at=now + timedelta(seconds=1)),
        _payload("child-fail", status="failed", created_at=now + timedelta(seconds=2)),
    ])

    db = SessionLocal()
    try:
        row = db.query(ActivityLogRollup).filter(ActivityLogRollup.rollup_key == "batch:batch-1").first()
        assert row is not None
        assert row.child_count == 2
        assert row.success_count == 1
        assert row.failed_count == 1
        assert row.latest_status == "partial_success"
        assert row.latest_log_id == "child-fail"
    finally:
        db.close()


def test_activity_log_writer_uses_sqlite_write_budget(monkeypatch):
    SessionLocal = _testing_session()

    import app.models.database as database_module
    import app.core.activity_log_rollup_service as rollup_module
    import app.core.resource_budget_service as budget_module

    monkeypatch.setattr(database_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(rollup_module, "SessionLocal", SessionLocal)
    calls = []

    class Budget:
        @contextmanager
        def acquire_sync(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    monkeypatch.setattr(budget_module, "get_resource_budget_service", lambda: Budget())

    writer = ActivityLogWriter()
    writer._flush([
        _payload("budgeted", status="success", created_at=datetime(2026, 1, 1, 8, 0, 0)),
    ])

    assert calls == [("sqlite_write", 1, "activity_log.flush")]


def test_activity_log_rollup_backfill_and_diff(monkeypatch):
    SessionLocal = _testing_session()

    import app.models.database as database_module
    import app.core.activity_log_rollup_service as rollup_module

    monkeypatch.setattr(database_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(rollup_module, "SessionLocal", SessionLocal)

    now = datetime(2026, 1, 1, 8, 0, 0)
    db = SessionLocal()
    try:
        db.add(ActivityLog(**_payload("parent", status="success", created_at=now)))
        db.add(ActivityLog(**_payload("child-partial", status="partial_success", created_at=now + timedelta(seconds=1))))
        db.commit()
    finally:
        db.close()

    service = ActivityLogRollupService()
    result = service.backfill(limit_groups=10)

    assert result["matched"] is True
    assert result["rebuilt"] >= 1

    db = SessionLocal()
    try:
        row = db.query(ActivityLogRollup).filter(ActivityLogRollup.rollup_key == "batch:batch-1").first()
        row.partial_count = 0
        db.commit()
    finally:
        db.close()

    diff = service.diff(limit_groups=10)
    assert diff["matched"] is False
    assert diff["diff_count"] >= 1


def test_activity_lite_batch_summary_uses_rollup(monkeypatch):
    SessionLocal = _testing_session()

    import app.models.database as database_module
    import app.core.activity_log_rollup_service as rollup_module

    monkeypatch.setattr(database_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(rollup_module, "SessionLocal", SessionLocal)

    db = SessionLocal()
    try:
        db.add(
            ActivityLogRollup(
                rollup_key="batch:batch-1",
                rollup_type="batch",
                group_value="batch-1",
                category="auto_import",
                child_count=3,
                success_count=2,
                failed_count=1,
                partial_count=0,
                waiting_count=0,
                latest_status="partial_success",
                latest_activity_at=datetime(2026, 1, 1, 8, 0, 0),
            )
        )
        db.commit()
        item = {"id": "parent", "batch_id": "batch-1", "has_children": True}
        routes._enrich_lite_items_with_batch_summary([item], db)
    finally:
        db.close()

    assert item["child_total_count"] == 3
    assert item["child_success_count"] == 2
    assert item["child_failed_count"] == 1
