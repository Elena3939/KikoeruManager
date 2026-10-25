"""真实 PostgreSQL 扫描协调、短请求、取消和线程退出回归。"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.config.settings import get_config
from app.core import input_scan_service as scan_module
from app.core.input_scan_discovery import InputScanDiscovery
from app.core.input_scan_repository import InputScanRepository, path_key
from app.core.input_scan_service import InputScanService
from app.models.database import ActivityLog, Task as TaskRecord


@pytest.fixture
def service(db_session, db_engine, monkeypatch, tmp_path):
    repository = InputScanRepository(sessionmaker(bind=db_engine))
    value = InputScanService(repository)
    config = get_config().model_copy(deep=True)
    config.storage.input_path = str(tmp_path)
    config.input_scan.progress_interval_seconds = 0.5
    monkeypatch.setattr(scan_module, "get_config", lambda: config)
    monkeypatch.setattr(scan_module, "get_input_scan_service", lambda: value)
    engine = SimpleNamespace(
        get_all_tasks=lambda **kwargs: [], enqueue_once=AsyncMock(),
        try_acquire_input_preflight=lambda candidate_id: True,
        release_input_preflight=lambda candidate_id: None,
        _preflight_auto_process=AsyncMock(return_value=("RJ01234567", True)),
        refresh_input_metadata_window=AsyncMock(),
    )
    monkeypatch.setattr(scan_module, "get_task_engine", lambda: engine)
    from app.core import realtime_event_service
    monkeypatch.setattr(realtime_event_service, "broadcast_event", lambda event: None)
    return value


@pytest.mark.asyncio
async def test_short_request_parent_first_and_idempotent_retry(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(scan_id):
        entered.set()
        await release.wait()

    monkeypatch.setattr(service, "_run", run)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=routes.app), base_url="http://test",
        ) as client:
            first = await client.post("/api/scan?request_key=retry-one")
            assert first.status_code == 202
            job = first.json()
            await asyncio.wait_for(entered.wait(), 2)
            second = await client.post("/api/scan?request_key=retry-one")
            assert second.json()["scan_id"] == job["scan_id"]
            with service.repository.session_factory() as db:
                assert db.query(ActivityLog).count() == 1
                assert db.query(TaskRecord).count() == 0
            assert (await client.get("/api/scan/latest")).json()["scan_id"] == job["scan_id"]
            assert (await client.get("/api/scan/status/missing")).status_code == 404
    finally:
        release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_real_discovery_handoff_and_durable_lookup(service, tmp_path):
    (tmp_path / "RJ01234567.zip").write_bytes(b"PK\x03\x04sample")
    try:
        job = await service.start(request_key="real")
        await asyncio.wait_for(asyncio.shield(service._task), 5)
        result = await service.get(job["scan_id"])
        assert result["status"] == "completed"
        assert result["counts"] == {"submitted": 1}
        assert result["execution_status"] == "waiting"
        engine = scan_module.get_task_engine()
        async with asyncio.timeout(3):
            while not engine.enqueue_once.await_count:
                await asyncio.sleep(0.05)
        engine.refresh_input_metadata_window.assert_awaited()
        restored = InputScanService(service.repository)
        assert (await restored.latest())["scan_id"] == job["scan_id"]
        with service.repository.session_factory() as db:
            task = db.query(TaskRecord).one()
            assert task.task_metadata["scan_id"] == job["scan_id"]
            assert task.task_metadata["input_members"] == [str(tmp_path / "RJ01234567.zip")]
            engine.enqueue_once.assert_any_await(task.id)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_waiting_group_does_not_block_later_single(service, tmp_path):
    changing, ready = tmp_path / "a.zip", tmp_path / "b.zip"
    changing.write_bytes(b"data")
    (tmp_path / "a.zip.aria2").write_bytes(b"downloading")
    ready.write_bytes(b"data")
    scan_id = service.repository.create_run(str(tmp_path), {})
    service.repository.discover(scan_id, [{
        "group_key": path_key(str(path)), "source_path": str(path),
        "members": [str(path)], "needs_stability": path == changing,
    } for path in [changing, ready]])
    service.repository.close_producer(scan_id)
    service._task = asyncio.create_task(service._run(scan_id))
    try:
        async with asyncio.timeout(5):
            while (await service.get(scan_id))["counts"].get("submitted") != 1:
                await asyncio.sleep(0.05)
        assert (await service.get(scan_id))["counts"]["waiting_stable"] == 1
        await service.cancel(scan_id)
        await asyncio.wait_for(asyncio.shield(service._task), 3)
        assert (await service.get(scan_id))["counts"] == {"submitted": 1, "cancelled": 1}
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_discovery_failure_is_queryable(service, monkeypatch):
    def fail(self, loop):
        raise RuntimeError("发现线程失败")

    monkeypatch.setattr(InputScanDiscovery, "_produce", fail)
    try:
        job = await service.start()
        await asyncio.wait_for(asyncio.shield(service._task), 3)
        result = await service.get(job["scan_id"])
        assert result["status"] == "failed"
        assert "发现线程失败" in result["coverage"]["errors"][0]["reason"]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_full_channel_stop_waits_for_real_thread(tmp_path, monkeypatch):
    exited = threading.Event()

    def produce(self, loop):
        try:
            for index in range(100):
                if not self._send(loop, {"groups": [index]}):
                    break
        finally:
            exited.set()

    monkeypatch.setattr(InputScanDiscovery, "_produce", produce)
    discovery = InputScanDiscovery(str(tmp_path), capacity=1)
    await discovery.start()
    async with asyncio.timeout(2):
        while discovery.queue.empty():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(discovery.stop(), 2)
    assert exited.is_set()


@pytest.mark.asyncio
async def test_slow_checks_do_not_stop_discovery_or_duplicate_candidates(service, tmp_path, monkeypatch):
    for index in range(70):
        (tmp_path / f"RJ{index:08d}.zip").write_bytes(b"PK\x03\x04sample")
    active, seen = set(), set()
    entered = asyncio.Event()

    async def slow_check(candidate, policy):
        assert candidate["id"] not in seen
        seen.add(candidate["id"])
        active.add(candidate["id"])
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active.discard(candidate["id"])

    monkeypatch.setattr(service, "_check", slow_check)
    try:
        job = await service.start()
        await asyncio.wait_for(entered.wait(), 3)
        async with asyncio.timeout(5):
            while True:
                result = await service.get(job["scan_id"])
                if result["producer_closed"]:
                    break
                await asyncio.sleep(0.05)
        assert result["discovered_groups"] == 70
        assert 0 < len(active) <= scan_module.get_config().processing.max_workers
        await service.cancel(job["scan_id"])
        await asyncio.wait_for(asyncio.shield(service._task), 3)
        assert not active
        assert (await service.get(job["scan_id"]))["counts"] == {"cancelled": 70}
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_candidate_business_error_does_not_abort_other_sources(service, tmp_path):
    engine = scan_module.get_task_engine()

    async def preflight(task, *_args):
        if task.source_path.endswith("broken.zip"):
            raise RuntimeError("业务预检异常")
        return "RJ01234567", True

    engine._preflight_auto_process.side_effect = preflight
    for name in ("broken.zip", "ready.zip"):
        (tmp_path / name).write_bytes(b"PK\x03\x04sample")
    try:
        job = await service.start()
        await asyncio.wait_for(asyncio.shield(service._task), 5)
        result = await service.get(job["scan_id"])
        assert result["counts"] == {"failed": 1, "submitted": 1}
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_preflight_uses_latest_auto_classify_and_reuses_backpressure_result(
    service, tmp_path, monkeypatch,
):
    path = tmp_path / "ready.zip"
    path.write_bytes(b"sample")
    scan_id = service.repository.create_run(str(tmp_path), {"auto_classify": True})
    service.repository.discover(scan_id, [{
        "group_key": path_key(str(path)), "source_path": str(path), "members": [str(path)],
    }])
    scan_module.get_config().watcher.auto_classify = False
    monkeypatch.setattr(service, "_has_handoff_capacity", lambda config: False)
    engine = scan_module.get_task_engine()
    try:
        candidate = service.repository.due(scan_id)[0]
        await service._check(candidate, {"auto_classify": True})
        assert engine._preflight_auto_process.call_args.args[0].auto_classify is False
        candidate = service.repository.candidate_for_group(scan_id, path_key(str(path)))
        assert candidate["reason"] == "engine_backpressure"
        await service._check(candidate, {})
        assert engine._preflight_auto_process.await_count == 1
        # 策略变化后不能继续复用旧的正常处理决定。
        scan_module.get_config().watcher.auto_classify = True
        candidate = service.repository.candidate_for_group(scan_id, path_key(str(path)))
        await service._check(candidate, {})
        assert engine._preflight_auto_process.await_count == 2
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_watch_and_manual_scan_share_persistent_source_claim(service, tmp_path, monkeypatch):
    from app.core.task_engine import Task, TaskEngine

    engine = TaskEngine(max_concurrent=2)
    monkeypatch.setattr(Task, "_global_event_hook", None)
    monkeypatch.setattr(engine, "_ensure_task_context", lambda task: None)
    monkeypatch.setattr(engine, "_notify_progress", AsyncMock())
    monkeypatch.setattr(engine, "_preflight_auto_process", AsyncMock(return_value=("RJ01234567", True)))
    monkeypatch.setattr(scan_module, "get_task_engine", lambda: engine)
    config = scan_module.get_config()
    config.processing.file_stable_checks = 1
    config.processing.file_stable_interval = 0.1
    path = tmp_path / "RJ01234567.zip"
    path.write_bytes(b"PK\x03\x04sample")
    watch = asyncio.create_task(service.accept_watch_file(str(path)))
    try:
        job = await service.start()
        await asyncio.wait_for(asyncio.gather(asyncio.shield(service._task), watch), 8)
        with service.repository.session_factory() as db:
            records = db.query(TaskRecord).all()
            assert len(records) == 1
            task_id = records[0].id
        async with asyncio.timeout(3):
            while not engine.queue.qsize():
                await asyncio.sleep(0.05)
        assert engine.queue.qsize() == 1
        await engine.enqueue_once(task_id)
        assert engine.queue.qsize() == 1
        assert (await service.get(job["scan_id"]))["pending_count"] == 0
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
        await service.stop()
        engine._materialized_snapshot_executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_manual_and_watch_workers_share_check_limit(service, tmp_path, monkeypatch):
    config = scan_module.get_config()
    config.processing.max_workers = 1
    runs = []
    for index, action in enumerate(("scan_input", "watch_input")):
        path = tmp_path / f"{index}.zip"
        path.write_bytes(b"sample")
        scan_id = service.repository.create_run(str(tmp_path), {"source_action": action})
        service.repository.discover(scan_id, [{
            "group_key": path_key(str(path)), "source_path": str(path), "members": [str(path)],
        }])
        service.repository.close_producer(scan_id)
        runs.append(scan_id)
    active, peak = 0, 0

    async def check(candidate, policy):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.15)
            await service._update(candidate, state="skipped", reason="test")
        finally:
            active -= 1

    monkeypatch.setattr(service, "_check", check)
    try:
        await asyncio.wait_for(asyncio.gather(*(service._run(scan_id) for scan_id in runs)), 5)
        assert peak == 1
    finally:
        await service.stop()
