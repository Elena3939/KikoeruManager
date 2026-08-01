from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.core import task_phase_metric_service
from app.core.task_phase_metric_service import TaskPhaseMetricService
from app.models.database import Base, TaskPhaseMetric


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_task_phase_metric_service_records_sanitized_detail(monkeypatch):
    SessionLocal = make_session_factory()
    monkeypatch.setattr(task_phase_metric_service, "SessionLocal", SessionLocal)
    service = TaskPhaseMetricService()

    metric_id = service.record(
        task_id="task-1",
        task_type="http_download",
        phase="download",
        resource="network_download",
        status="completed",
        duration_ms=1500,
        bytes_total=1024,
        items_total=2,
        detail={
            "token": "secret-token",
            "file_path": "D:/private/RJ123456/source.zip",
            "retry_count": 1,
            "items": ["a", "b", "c"],
        },
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        ended_at=datetime(2026, 1, 1, 12, 0, 1),
    )

    assert metric_id

    db = SessionLocal()
    try:
        row = db.query(TaskPhaseMetric).first()
        assert row.task_id == "task-1"
        assert row.phase == "download"
        assert row.duration_ms == 1500
        assert row.bytes_total == 1024
        assert row.detail_json["token"] == "[redacted]"
        assert row.detail_json["items"] == "list[3]"
        assert row.detail_json["retry_count"] == 1
    finally:
        db.close()


def test_task_phase_metric_service_lists_recent(monkeypatch):
    SessionLocal = make_session_factory()
    monkeypatch.setattr(task_phase_metric_service, "SessionLocal", SessionLocal)
    service = TaskPhaseMetricService()

    service.record(task_id="task-a", task_type="extract", phase="copy", duration_ms=10)
    service.record(task_id="task-b", task_type="extract", phase="archive", duration_ms=20)

    all_items = service.list_recent(limit=10)
    filtered = service.list_recent(task_id="task-a", limit=10)

    assert len(all_items) == 2
    assert len(filtered) == 1
    assert filtered[0]["task_id"] == "task-a"
    assert filtered[0]["duration_ms"] == 10


def test_task_phase_metric_service_summarizes_recent(monkeypatch):
    SessionLocal = make_session_factory()
    monkeypatch.setattr(task_phase_metric_service, "SessionLocal", SessionLocal)
    service = TaskPhaseMetricService()

    service.record(
        task_id="task-a",
        task_type="http_download",
        phase="download",
        resource="network_download",
        status="completed",
        duration_ms=100,
        bytes_total=1000,
        items_total=1,
    )
    service.record(
        task_id="task-b",
        task_type="http_download",
        phase="download",
        resource="network_download",
        status="partial_failed",
        duration_ms=300,
        bytes_total=2000,
        items_total=2,
    )
    service.record(
        task_id="task-c",
        task_type="extract",
        phase="copy",
        resource="disk_io_local",
        duration_ms=50,
    )

    summary = service.summarize_recent(limit=10)
    http_group = next(item for item in summary["groups"] if item["task_type"] == "http_download")

    assert summary["sample_count"] == 3
    assert http_group["count"] == 2
    assert http_group["duration_avg_ms"] == 200
    assert http_group["duration_p95_ms"] == 300
    assert http_group["duration_max_ms"] == 300
    assert http_group["bytes_total"] == 3000
    assert http_group["items_total"] == 3
    assert http_group["failed_count"] == 1


def test_task_phase_metric_service_cleanup_old_and_overflow(monkeypatch):
    SessionLocal = make_session_factory()
    monkeypatch.setattr(task_phase_metric_service, "SessionLocal", SessionLocal)
    service = TaskPhaseMetricService()
    old_time = datetime(2026, 1, 1, 12, 0, 0)
    new_time = datetime.now()

    service.record(task_id="old", phase="download", duration_ms=10, ended_at=old_time)
    for index in range(101):
        service.record(task_id=f"new-{index}", phase="download", duration_ms=10 + index, ended_at=new_time)
    db = SessionLocal()
    try:
        old_row = db.query(TaskPhaseMetric).filter(TaskPhaseMetric.task_id == "old").first()
        old_row.created_at = old_time
        db.commit()
    finally:
        db.close()

    result = service.cleanup(retain_days=1, max_items=100)
    items = service.list_recent(limit=200)

    assert result["deleted_old"] == 1
    assert result["deleted_overflow"] == 1
    assert result["remaining"] == 100
    assert len(items) == 100
    assert all(item["task_id"] != "old" for item in items)


@pytest.mark.asyncio
async def test_task_phase_metric_service_record_async(monkeypatch):
    SessionLocal = make_session_factory()
    monkeypatch.setattr(task_phase_metric_service, "SessionLocal", SessionLocal)
    service = TaskPhaseMetricService()

    metric_id = await service.record_async(task_id="task-async", phase="download", duration_ms=30)
    items = service.list_recent(task_id="task-async")

    assert metric_id
    assert len(items) == 1
    assert items[0]["phase"] == "download"
