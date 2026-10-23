from unittest.mock import AsyncMock, Mock

import pytest

from app.core.task_center_service import TaskCenterService
from app.core.task_center_event_service import _task_domain
from app.core.task_engine import Task, TaskStatus, TaskType


@pytest.fixture
def service(monkeypatch):
    service = TaskCenterService()
    monkeypatch.setattr(service, "_redis_runtime_for_task", lambda _: None)
    return service


@pytest.mark.parametrize("kind,extra,subtype,label", [
    (TaskType.CIRCLE_COMPLETION_INDEX, {}, "circle_index", "社团索引"),
    (TaskType.CIRCLE_COMPLETION_INDEX, {"is_batch": True, "batch_total": 3}, "circle_index", "社团索引"),
    (TaskType.CIRCLE_COMPLETION_INDEX, {"is_refresh_all": True, "batch_total": 3}, "circle_index", "社团索引"),
    (TaskType.CIRCLE_COMPLETION_INDEX, {"only_new_works": True}, "circle_index", "社团索引"),
    (TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, {}, "work_refresh", "作品状态刷新"),
    (TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, {"owned_only": True}, "owned_check", "本地收录核对"),
    (TaskType.CIRCLE_COMPLETION_BONUS_PROBE, {}, "bonus_probe", "特典探测"),
    (TaskType.ASMR_SYNC_DOWNLOAD, {}, "work_download", "作品下载"),
    (TaskType.HTTP_DOWNLOAD, {"task_domain": "http_download", "download_mode": "imoutoheaven"}, "work_download", "作品下载"),
])
def test_circle_classification_in_summary_detail_and_events(service, kind, extra, subtype, label):
    task = Task(kind, "circle", task_id="circle-task")
    task.task_metadata = {"circle_name": "测试社团", "source_page": "circle-completion", **extra}
    for mode in ("summary", "detail"):
        item = service._serialize_engine_task(task, mode=mode)
        assert (item["domain"], item["subtype"], item["subtype_label"]) == ("circle_completion", subtype, label)
        assert service._summary_item(item)["subtype"] == subtype
        assert item["kind"] == kind.value
        assert item["route_hint"].startswith("/circle-completion")
        if subtype in {"owned_check", "work_refresh"}:
            assert {metric["label"] for metric in item["metrics"]} == {"选中", "已处理", "变化"}
        if extra.get("only_new_works"):
            assert "仅新作" in item["subtitle"]
    assert _task_domain(task) == "circle_completion"


def test_yaas_download_retains_http_capabilities_and_sanitization(service):
    task = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="yaas-task")
    task.status = TaskStatus.COMPLETED
    task.task_metadata = {
        "source_page": "circle-completion", "task_domain": "http_download",
        "download_mode": "imoutoheaven", "circle_id": "RG123", "work_title": "测试作品",
        "rjcode": "RJ12345678", "failed_files": [{"name": "bad"}],
        "download_files": [{"name": "good", "status": "completed", "headers": {"Authorization": "secret"}, "url": "https://example.com/file?token=secret"}],
        "urls": ["https://example.com/file?token=secret"], "progress_log": [],
    }
    item = service._serialize_engine_task(task)
    assert item["status"] == "partial_failed"
    assert item["actions"] == ["retry", "delete"]
    assert item["title"] == "RJ12345678 · 测试作品"
    assert "secret" not in str(item["details"]["metadata"])
    assert item["details"]["metadata"]["download_files"][0]["name"] == "good"


@pytest.mark.asyncio
async def test_subtype_filter_before_pagination_and_materialized_parity(service, monkeypatch, db_session):
    items = []
    for index, owned in enumerate([False, True, True]):
        task = Task(TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, "same-circle", task_id=str(index))
        task.task_metadata = {"owned_only": owned, "circle_name": "同名社团"}
        items.append(service._serialize_engine_task(task, mode="summary"))
    items = service._sort_items(items)
    monkeypatch.setattr(service, "_build_all_items", AsyncMock(return_value=items))
    monkeypatch.delenv("KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY", raising=False)
    from sqlalchemy.orm import sessionmaker
    from app.core import task_center_materialization_service as materialization_module
    monkeypatch.setattr(materialization_module, "SessionLocal", sessionmaker(bind=db_session.connection()))
    materialization = materialization_module.TaskCenterMaterializationService()
    materialization.upsert_items(items)
    monkeypatch.setattr("app.core.task_center_materialization_service.get_task_center_materialization_service", lambda: materialization)
    kwargs = dict(domain="circle_completion", subtype="owned_check", search="本地收录核对", status="pending", offset=1, limit=1)
    regular = await service.list_items(mode="summary", **kwargs)
    materialized = service.list_materialized_items(**kwargs)
    assert regular["total"] == materialized["total"] == 2
    assert [item["id"] for item in regular["items"]] == [item["id"] for item in materialized["items"]]
    assert len(service._dedupe_items(items)) == 3


def test_legacy_materialized_task_reloads_missing_owned_only(service, monkeypatch):
    task = Task(TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, "circle", task_id="old")
    task.task_metadata = {"owned_only": True}
    engine = Mock()
    engine.get_task.return_value = task
    monkeypatch.setattr("app.core.task_center_service.get_task_engine", lambda: engine)
    rows = service._refresh_legacy_materialized_items([{"kind": task.type.value, "engine_task_id": "old"}])
    assert rows[0]["subtype"] == "owned_check"


def test_other_download_is_not_circle_task(service):
    task = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="other")
    item = service._serialize_engine_task(task, mode="summary")
    assert item["domain"] == "http_download"
    assert item["subtype"] == item["subtype_label"] == ""


def test_waiting_retry_preserves_circle_origin(service):
    item = service._serialize_waiting_retry_item({
        "id": "waiting", "rjcode": "RJ12345678", "work_title": "测试作品",
        "task_metadata": {"source_page": "circle-completion", "circle_id": "RG123"},
    })
    assert item["domain"] == "circle_completion"
    assert item["subtype"] == "work_download"
    assert item["actions"] == ["retry_waiting", "delete_waiting_retry"]
    assert "RG123" in item["route_hint"]


def test_completed_other_subtype_does_not_hide_active_task(service):
    active = Task(TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, "same-circle", task_id="active")
    active.task_metadata = {"owned_only": True}
    completed = Task(TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, "same-circle", task_id="done")
    completed.status = TaskStatus.COMPLETED
    items = [service._serialize_engine_task(task, mode="summary") for task in [active, completed]]
    assert len(service._dedupe_items(items)) == 2


def test_legacy_materialized_task_loads_database_metadata(service, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace

    engine = Mock()
    engine.get_task.return_value = None
    monkeypatch.setattr("app.core.task_center_service.get_task_engine", lambda: engine)
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = [SimpleNamespace(
        id="old-db", type=TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED.value,
        status=TaskStatus.COMPLETED.value, source_path="circle", task_metadata={"owned_only": True},
        created_at=datetime.now(), progress=100,
    )]
    monkeypatch.setattr("app.core.task_center_service.SessionLocal", lambda: db)
    rows = service._refresh_legacy_materialized_items([{
        "kind": TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED.value, "engine_task_id": "old-db",
    }])
    assert rows[0]["subtype"] == "owned_check"
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_circle_http_file_page_remains_sanitized(service, monkeypatch):
    task = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="files")
    task.task_metadata = {
        "source_page": "circle-completion",
        "download_files": [{"name": "audio", "headers": {"Authorization": "secret"},
                            "url": "https://example.com/file?token=secret"}],
    }
    engine = Mock()
    engine.get_task.return_value = task
    monkeypatch.setattr("app.core.task_center_service.get_task_engine", lambda: engine)
    page = await service.get_item_files(engine_task_id=task.id)
    assert page["total"] == 1
    assert page["items"][0]["name"] == "audio"
    assert "secret" not in str(page)


@pytest.mark.asyncio
async def test_circle_http_retry_and_cancel_use_engine_capabilities(service, monkeypatch):
    task = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="retry")
    task.status = TaskStatus.FAILED
    task.task_metadata = {"source_page": "circle-completion", "circle_id": "RG123"}
    engine = Mock()
    engine.get_task.return_value = task
    engine.queue.put = AsyncMock()
    downloader = Mock()
    downloader.reset_task_for_retry = AsyncMock()
    monkeypatch.setattr("app.core.task_center_service.get_task_engine", lambda: engine)
    monkeypatch.setattr("app.core.http_download_service.get_http_download_service", lambda: downloader)
    result = await service.execute_action("engine:retry", "retry")
    downloader.reset_task_for_retry.assert_awaited_once_with(task)
    engine.queue.put.assert_awaited_once_with(task)
    assert "RG123" in result["route_hint"]
    await service.execute_action("engine:retry", "cancel")
    engine.cancel_task.assert_called_once_with(task.id)
