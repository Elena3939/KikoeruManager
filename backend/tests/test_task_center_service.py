from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.task_center_service import TaskCenterService
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.models.database import Base, TaskCenterItem


@pytest.mark.asyncio
async def test_task_center_cache_uses_engine_version_without_rescanning_tasks(monkeypatch):
    service = TaskCenterService()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-1")
    task.created_at = datetime(2026, 1, 1)

    snapshot = Mock(return_value=[task])
    monkeypatch.setattr(service, "_engine_tasks_snapshot", snapshot)
    monkeypatch.setattr(service, "_engine_change_version", lambda: 7)
    monkeypatch.setattr(service, "_get_pending_items_cached", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_get_waiting_retry_items_cached", Mock(return_value=[]))
    monkeypatch.setattr(service, "_get_active_conflicts_cached", Mock(return_value=[]))
    monkeypatch.setattr(
        service,
        "_safe_serialize_engine_task",
        lambda _task, mode="detail": {
            "id": f"engine:{_task.id}",
            "engine_task_id": _task.id,
            "domain": "system",
            "status": _task.status.value,
            "title": "测试任务",
            "subtitle": "",
            "progress": _task.progress,
            "current_step": _task.current_step,
            "created_at": _task.created_at.isoformat(),
            "updated_at": _task.created_at.isoformat(),
            "metrics": [],
            "actions": [],
            "details": {"metadata": {}},
        },
    )

    first = await service.list_items(mode="summary")
    second = await service.list_items(mode="summary")

    assert first["total"] == 1
    assert second["total"] == 1
    assert snapshot.call_count == 1


def test_task_engine_task_center_version_increments_on_task_event():
    engine = TaskEngine()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-version")
    engine._ensure_task_context(task)

    before = engine.get_task_center_version()
    task.status = TaskStatus.PROCESSING

    assert engine.get_task_center_version() == before + 1


def test_task_center_materialized_item_snapshot_skips_unchanged_payload():
    engine = TaskEngine()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-materialized-version")
    item = {
        "id": f"engine:{task.id}",
        "engine_task_id": task.id,
        "status": TaskStatus.PROCESSING.value,
        "title": "解压任务",
        "progress": 10,
    }

    assert engine._should_upsert_task_center_item_snapshot(task, item) is True

    engine._materialized_task_center_item_versions[item["id"]] = engine._task_metadata_fingerprint(item)

    assert engine._should_upsert_task_center_item_snapshot(task, item) is False

    changed = {**item, "progress": 11}
    assert engine._should_upsert_task_center_item_snapshot(task, changed) is True


def test_task_center_materialized_item_snapshot_keeps_terminal_payload():
    engine = TaskEngine()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-materialized-terminal")
    task.complete()
    item = {
        "id": f"engine:{task.id}",
        "engine_task_id": task.id,
        "status": TaskStatus.COMPLETED.value,
        "title": "解压完成",
        "progress": 100,
    }
    engine._materialized_task_center_item_versions[item["id"]] = engine._task_metadata_fingerprint(item)

    assert engine._should_upsert_task_center_item_snapshot(task, item) is True


def test_http_download_task_subtitle_uses_current_file_name_without_rj():
    service = TaskCenterService()
    task = Task(
        TaskType.HTTP_DOWNLOAD,
        "https://gofile.io/d/content-id",
        task_id="task-gofile-title",
        metadata={
            "download_mode": "gofile",
            "source_modes": ["gofile"],
            "source_page": "asmr-sync",
            "source_action": "manual_gofile_download",
            "source_label": "Gofile 下载",
            "download_files": [
                {
                    "name": "RJ01621622.zip",
                    "relative_path": "RJ01621622.zip",
                    "status": "downloading",
                    "total": 3983571968,
                }
            ],
            "download_runtime": {
                "current_file_name": "RJ01621622.zip",
                "total_files": 1,
                "completed_files": 0,
                "total_bytes": 3983571968,
            },
        },
    )
    task.status = TaskStatus.PROCESSING

    item = service._safe_serialize_engine_task(task, mode="summary")

    assert item["domain"] == "http_download"
    assert item["title"] == "RJ01621622.zip"
    assert item["subtitle"] == "RJ01621622.zip"
    assert item["rjcode"] == ""


def test_summary_engine_item_cache_reuses_unchanged_task(monkeypatch):
    service = TaskCenterService()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-summary-cache")
    serialize = Mock(return_value={"id": f"engine:{task.id}", "status": task.status.value})
    monkeypatch.setattr(service, "_safe_serialize_engine_task", serialize)

    first = service._serialize_engine_task_cached(task, mode="summary")
    second = service._serialize_engine_task_cached(task, mode="summary")

    assert first == second
    assert serialize.call_count == 1

    task.update_progress(10, "解压中")
    third = service._serialize_engine_task_cached(task, mode="summary")

    assert third == first
    assert serialize.call_count == 2


def test_task_snapshot_materializes_task_center_item(monkeypatch):
    engine_db = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_db)
    Base.metadata.create_all(bind=engine_db)

    import app.models.database as database_module
    import app.core.task_center_materialization_service as materialization_module

    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(materialization_module, "SessionLocal", TestingSessionLocal)

    task_engine = TaskEngine()
    task = Task(
        TaskType.HTTP_DOWNLOAD,
        "https://example.test/file.zip",
        task_id="task-materialized",
        metadata={
            "source_page": "asmr-sync",
            "source_action": "manual_http_download",
            "source_label": "HTTP 下载",
            "download_files": [{"name": "file.zip", "status": "completed", "size": 1024}],
            "business_key": "http:file.zip",
        },
    )
    task.created_at = datetime(2026, 1, 1, 8, 0, 0)
    task.update_progress(42, "下载中")

    expected = TaskCenterService()._safe_serialize_engine_task(task, mode="summary")
    task_engine.persist_task_snapshot(task)

    db = TestingSessionLocal()
    try:
        row = db.query(TaskCenterItem).filter(TaskCenterItem.engine_task_id == task.id).first()
        assert row is not None
        assert row.item_id == f"engine:{task.id}"
        assert row.domain == "http_download"
        assert row.status == expected["status"]
        assert row.business_key == "http:file.zip"
        assert row.payload_json == expected
    finally:
        db.close()

    materialized = materialization_module.get_task_center_materialization_service()
    assert materialized.diff_engine_item(expected) == {
        "matched": True,
        "engine_task_id": task.id,
        "missing": False,
        "changed_keys": [],
    }

    db = TestingSessionLocal()
    try:
        row = db.query(TaskCenterItem).filter(TaskCenterItem.engine_task_id == task.id).first()
        row.payload_json = {**dict(row.payload_json or {}), "status": "failed"}
        db.commit()
    finally:
        db.close()

    diff = materialized.diff_engine_item(expected)
    assert diff["matched"] is False
    assert diff["missing"] is False
    assert diff["changed_keys"] == ["status"]

    task_engine.delete_task_snapshot(task.id)
    db = TestingSessionLocal()
    try:
        assert db.query(TaskCenterItem).filter(TaskCenterItem.engine_task_id == task.id).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_task_center_backfill_materialized_items_supports_sql_listing(monkeypatch):
    engine_db = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_db)
    Base.metadata.create_all(bind=engine_db)

    import app.models.database as database_module
    import app.core.task_center_materialization_service as materialization_module

    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(materialization_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(materialization_module, "_task_center_materialization_service", None)

    task = Task(
        TaskType.HTTP_DOWNLOAD,
        "https://example.test/file.zip",
        task_id="task-backfill-http",
        metadata={
            "source_page": "asmr-sync",
            "source_action": "manual_http_download",
            "source_label": "HTTP 下载",
            "download_files": [{"name": "file.zip", "status": "completed", "size": 1024}],
            "business_key": "http:file.zip",
        },
    )
    task.created_at = datetime(2026, 1, 1, 8, 0, 0)
    task.start()

    service = TaskCenterService()
    monkeypatch.setattr(service, "_engine_tasks_snapshot", Mock(return_value=[task]))
    monkeypatch.setattr(service, "_engine_change_version", lambda: 11)
    monkeypatch.setattr(service, "_get_pending_items_cached", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_get_waiting_retry_items_cached", Mock(return_value=[]))
    monkeypatch.setattr(service, "_get_active_conflicts_cached", Mock(return_value=[]))

    result = await service.backfill_materialized_items()
    assert result["matched"] is True
    assert result["item_count"] == 1
    assert result["engine_item_count"] == 1
    assert result["upserted"] == 1

    listed = service.list_materialized_engine_items(
        domain="http_download",
        status=TaskStatus.PROCESSING.value,
        search="file.zip",
        limit=10,
        offset=0,
    )

    assert listed["total"] == 1
    assert listed["items"][0]["id"] == f"engine:{task.id}"
    assert listed["counts_by_domain"] == {"http_download": 1}
    assert listed["counts_by_status"] == {TaskStatus.PROCESSING.value: 1}
    assert listed["highlight_counts"]["processing"] == 1


@pytest.mark.asyncio
async def test_task_center_materialized_summary_can_read_all_item_kinds(monkeypatch):
    engine_db = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_db)
    Base.metadata.create_all(bind=engine_db)

    import app.models.database as database_module
    import app.core.task_center_materialization_service as materialization_module

    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(materialization_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(materialization_module, "_task_center_materialization_service", None)

    service = TaskCenterService()
    task = Task(TaskType.EXTRACT, "/tmp/work.zip", task_id="task-all-kinds")
    task.created_at = datetime(2026, 1, 1, 8, 0, 0)
    pending_item = {
        "id": "pending-1",
        "task_id": "",
        "source_path": "/tmp/subtitle.zip",
        "source_mode": "archive",
        "can_execute": True,
        "created_at": "2026-01-01T08:01:00",
        "preview": {
            "source_label": "字幕补配预检",
            "source_rjcode": "RJ111111",
            "target_rjcode": "RJ222222",
            "candidate_count": 1,
            "ready_candidate_count": 1,
            "execute_reason": "等待确认",
        },
    }

    monkeypatch.setattr(service, "_engine_tasks_snapshot", Mock(return_value=[task]))
    monkeypatch.setattr(service, "_engine_change_version", lambda: 12)
    monkeypatch.setattr(service, "_get_pending_items_cached", AsyncMock(return_value=[pending_item]))
    monkeypatch.setattr(service, "_get_waiting_retry_items_cached", Mock(return_value=[]))
    monkeypatch.setattr(service, "_get_active_conflicts_cached", Mock(return_value=[]))

    backfill = await service.backfill_materialized_items()
    assert backfill["matched"] is True
    assert backfill["item_count"] == 2
    assert backfill["upserted"] == 2

    monkeypatch.setenv("KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY", "1")
    monkeypatch.setattr(service, "_build_all_items", AsyncMock(side_effect=AssertionError("不应走旧聚合")))

    result = await service.list_items(mode="summary", limit=10)

    assert result["mode"] == "materialized_summary"
    assert result["total"] == 2
    assert {item["id"] for item in result["items"]} == {"engine:task-all-kinds", "subtitle-pending:pending-1"}
    assert result["counts_by_domain"]["system"] == 1
    assert result["counts_by_domain"]["subtitle_import"] == 1
