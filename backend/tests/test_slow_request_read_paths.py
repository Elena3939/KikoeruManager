"""慢请求读路径：验证命令数、缓存隔离、分页语义和线程边界。"""

import asyncio
import random
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api import routes
from app.core.redis_service import RedisService
from app.core.request_performance import request_metrics, run_sync_stage
from app.core.task_center_service import TaskCenterService
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


@pytest.mark.asyncio
async def test_concurrent_download_polls_share_build_and_refresh_on_progress(monkeypatch):
    engine = TaskEngine()
    task = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="active")
    task.status = TaskStatus.PROCESSING
    engine.tasks = {task.id: task}
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: engine)
    redis = Mock()
    redis.get_task_runtimes_sync.return_value = {}
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: redis)
    monkeypatch.setattr(routes, "_DOWNLOAD_STATUS_CACHE", {})
    monkeypatch.setattr(routes, "_DOWNLOAD_STATUS_LOCKS", {})
    results = await asyncio.gather(*(routes.http_download_status(compact=True) for _ in range(8)))
    assert all(result == results[0] for result in results)
    redis.get_task_runtimes_sync.assert_called_once()
    monkeypatch.setattr(engine, "_write_task_runtime_to_redis", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "enqueue_task_center_item_snapshot", lambda *a, **kw: None)
    task.progress = 50
    engine._emit_task_center_event(task)
    refreshed = await routes.http_download_status(compact=True)
    assert refreshed["tasks"][0]["progress"] == 50
    assert redis.get_task_runtimes_sync.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(200, "请求耗时告警"), (404, "请求失败"), (500, "请求失败")])
async def test_slow_log_distinguishes_http_success_from_failure(monkeypatch, status, reason):
    from starlette.requests import Request
    from starlette.responses import Response

    log = Mock()
    monkeypatch.setattr(routes, "logger", log)
    monkeypatch.setattr(routes, "_SLOW_API_LOG_THRESHOLD_SECONDS", 1e-12)
    monkeypatch.setattr(routes, "_slow_api_resource_budget_snapshot", lambda: {})
    request = Request({"type": "http", "method": "GET", "path": "/api/probe",
                       "query_string": b"", "headers": [(b"x-request-id", b"read-probe")]})
    async def call_next(_):
        assert request_metrics.get()["request_id"] == "read-probe"
        return Response(status_code=status)

    response = await routes._call_next_with_perf_log(request, call_next)
    call = (log.error if status >= 500 else log.warning).call_args
    assert call.args[1] == reason
    assert call.args[5] == status
    assert response.headers["X-Request-ID"] == "read-probe"
    assert request_metrics.get() is None


def test_runtime_batch_reads_once_and_isolates_corrupt_values(monkeypatch):
    service = RedisService()
    client = Mock()
    client.mget.return_value = ['{"progress":42}', 'broken', None]
    monkeypatch.setattr(service, "client", lambda **kwargs: client)
    monkeypatch.setattr(service, "_memory_runtime_get", lambda task_id: {"id": task_id})
    result = service.get_task_runtimes_sync(["a", "b", "a", "c"])
    assert result == {"a": {"progress": 42}, "b": {"id": "b"}, "c": {"id": "c"}}
    client.mget.assert_called_once()
    assert len(client.mget.call_args.args[0]) == 3
    assert service.get_task_runtimes_sync([]) == {}
    client.mget.assert_called_once()


@pytest.mark.asyncio
async def test_download_status_compact_full_and_terminal_runtime(monkeypatch):
    engine = TaskEngine()
    completed = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="completed")
    active = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="active")
    completed.status = TaskStatus.COMPLETED
    active.status = TaskStatus.PROCESSING
    completed.task_metadata = {"download_files": [
        {"name": str(index), "status": "completed"} for index in range(120)
    ]}
    engine.tasks = {task.id: task for task in (completed, active)}
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: engine)
    redis = Mock()
    batches = []
    redis.get_task_runtimes_sync.side_effect = lambda ids: batches.append(list(ids)) or {}
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: redis)
    monkeypatch.setattr(routes, "_DOWNLOAD_STATUS_CACHE", {})
    compact = await routes.http_download_status(compact=True)
    full = await routes.http_download_status(compact=False)
    again = await routes.http_download_status(compact=True)
    compact_task = next(task for task in compact["tasks"] if task["id"] == "completed")
    full_task = next(task for task in full["tasks"] if task["id"] == "completed")
    assert compact_task["download_files_total"] == full_task["download_files_total"] == 120
    assert len(compact_task["download_files"]) == routes._TRANSFER_STATUS_PREVIEW_LIMIT
    assert len(full_task["download_files"]) == 120
    assert compact == again
    assert batches == [["active"], ["active"]]
    assert compact["completed"] == compact["processing"] == 1
    redis.get_task_runtime_sync.assert_not_called()


def test_terminal_summary_does_not_read_redis(monkeypatch):
    service = TaskCenterService()
    task = Task(TaskType.EXTRACT, "/input/a.zip")
    task.status = TaskStatus.COMPLETED
    runtime = Mock(side_effect=AssertionError("终态不得读取 Redis"))
    monkeypatch.setattr(service, "_redis_runtime_for_task", runtime)
    assert service._serialize_engine_task(task, mode="summary")["status"] == "completed"
    runtime.assert_not_called()


def test_dedupe_index_matches_reference_with_retry_time_and_self_edges():
    service = TaskCenterService()
    rng = random.Random(42)
    for _ in range(25):
        items = [{
            "id": f"engine:{index}", "entity_id": str(index),
            "status": rng.choice(["pending", "processing", "completed", "failed"]),
            "kind": rng.choice(["a", "b"]), "subtype": rng.choice([None, "x"]),
            "source_path": rng.choice(["", "/input/a", "/input/b"]),
            "created_at": rng.choice([None, "2026-01-01", "2026-01-02"]),
            "details": {"metadata": {
                "retry_failed_task_id": str(rng.randrange(40)),
                "recovered_failure_ids": [str(rng.randrange(40))],
            }},
        } for index in range(40)]
        expected = [item for item in items if not service._is_superseded_active_engine_item(item, items)]
        assert service._dedupe_items(items) == expected


@pytest.mark.asyncio
async def test_sync_stage_runs_off_loop_and_propagates_metrics():
    loop_thread = threading.get_ident()
    metrics = {}
    token = request_metrics.set(metrics)
    try:
        assert await run_sync_stage("probe", threading.get_ident) != loop_thread
        assert metrics["probe_queue_ms"] >= 0
        assert metrics["probe_ms"] >= 0
    finally:
        request_metrics.reset(token)


@pytest.mark.asyncio
async def test_materialized_empty_does_not_trigger_full_aggregation(monkeypatch):
    service = TaskCenterService()
    monkeypatch.setenv("KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY", "1")
    monkeypatch.setattr(service, "list_materialized_items", lambda **kwargs: {"items": [], "total": 0})
    monkeypatch.setattr(service, "_build_all_items", Mock(side_effect=AssertionError("合法空集合")))
    assert await service.list_items(mode="summary", search="不存在") == {"items": [], "total": 0}


def test_type_index_reuses_membership_during_progress(monkeypatch):
    engine = TaskEngine()
    download = Task(TaskType.HTTP_DOWNLOAD, "https://example.com", task_id="download")
    other = Task(TaskType.EXTRACT, "/a.zip", task_id="other")
    engine.tasks = {task.id: task for task in (download, other)}
    assert engine.get_tasks_by_type(download.type) == [download]
    membership = engine._typed_task_membership
    monkeypatch.setattr(engine, "_write_task_runtime_to_redis", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "enqueue_task_center_item_snapshot", lambda *a, **kw: None)
    version = engine.get_task_type_version(download.type)
    engine._emit_task_center_event(other)
    assert engine.get_task_type_version(download.type) == version
    engine._emit_task_center_event(download)
    assert engine.get_tasks_by_type(download.type) == [download]
    assert engine._typed_task_membership is membership


@pytest.mark.asyncio
async def test_inventory_health_cache_and_stats_thread(monkeypatch):
    from app.core.library_manager import LibraryManager

    manager = object.__new__(LibraryManager)
    manager._health_read_lock = threading.RLock()
    manager._health_read_cache = {}
    library = SimpleNamespace(id="local", type="local", root_path="/library")
    collect = Mock(return_value={"warnings": []})
    monkeypatch.setattr(manager, "_collect_library_health", collect)
    first = manager._health_for_library(library, 10)
    first["warnings"].append("不得污染缓存")
    assert manager._health_for_library(library, 10) == {"warnings": []}
    collect.assert_called_once()
    manager._health_for_library(library, 20)
    assert collect.call_count == 2
    loop_thread = threading.get_ident()
    monkeypatch.setattr(manager, "_ensure_stats_sync", lambda *a: threading.get_ident())
    assert await manager.ensure_stats() != loop_thread


@pytest.mark.parametrize("search", ["字", "%", "_"])
def test_materialized_literal_search_and_pagination(monkeypatch, db_session, search):
    from sqlalchemy.orm import sessionmaker
    from app.core import task_center_materialization_service as module

    monkeypatch.setattr(module, "SessionLocal", sessionmaker(bind=db_session.connection()))
    materialization = module.TaskCenterMaterializationService()
    items = [{"id": str(index), "domain": "import", "status": "pending", "title": title}
             for index, title in enumerate(["字 % _", "字 % _", "其它"])]
    materialization.upsert_items(items)
    result = materialization.list_items(search=search, ordered_ids=["0", "1", "2"], limit=1, offset=1)
    assert result["total"] == 2
    assert [item["id"] for item in result["items"]] == ["1"]
