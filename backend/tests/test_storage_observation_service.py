"""只读存储观测的脱敏、计数器边界与请求并发回归。"""

import asyncio
import json
import threading
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import event

from app.api import routes
from app.core import storage_observation_service as service


def test_postgres_snapshot_uses_short_read_only_connection(db_engine, monkeypatch):
    monkeypatch.setattr("app.models.database.engine", db_engine)
    original_create = service.create_engine
    states = []

    def create(*args, **kwargs):
        assert kwargs["connect_args"]["connect_timeout"] == 2
        engine = original_create(*args, **kwargs)

        @event.listens_for(engine, "begin")
        def check_read_only(conn):
            states.append((
                conn.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                conn.exec_driver_sql("SHOW transaction_timeout").scalar_one(),
                conn.exec_driver_sql("SHOW statement_timeout").scalar_one(),
            ))

        return engine

    monkeypatch.setattr(service, "create_engine", create)
    before = db_engine.pool.checkedout()
    result = service._postgres_snapshot()
    assert states == [("on", "4s", "1500ms")]
    assert db_engine.pool.checkedout() == before
    assert result["status"] == "ok"
    assert "wal_bytes" in result["wal"]
    assert "num_requested" in result["checkpointer"]
    assert "track_io_timing" in result["settings"]
    assert all(set(row) == {"state", "wait_event_type", "wait_event", "connections"} for row in result["waits"])
    assert "query" not in json.dumps(result)


def test_redis_info_allowlist_preserves_metrics_when_config_acl_denied():
    class Client:
        def pipeline(self, **kwargs):
            assert kwargs == {"transaction": False}
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def info(self, _section):
            return self

        def execute(self):
            return (
                {"aof_enabled": 1, "aof_delayed_fsync": 4, "secret": "do-not-export"},
                {"latest_fork_usec": 300, "total_forks": 2, "secret": "do-not-export"},
                {"uptime_in_seconds": 100, "config_file": "do-not-export"},
            )

        def config_get(self, *_args):
            raise RuntimeError("do-not-export")

    result = service._redis_info(Client())
    assert result["persistence"] == {"aof_enabled": 1, "aof_delayed_fsync": 4}
    assert result["fork"] == {"latest_fork_usec": 300, "total_forks": 2}
    assert result["settings"]["status"] == "unavailable"
    assert "do-not-export" not in json.dumps(result)


def test_linux_diskstats_uses_fixed_512_byte_sectors(monkeypatch):
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.Path, "read_text", lambda path, **_kwargs:
        "8 0 sda 10 0 20 30 40 0 50 60 2 70 80" if path.as_posix() == "/proc/diskstats" else "some avg10=0.00 total=10")
    result = service._disk_snapshot()
    assert result["devices"]["sda"] == {
        "reads": 10, "read_bytes": 20 * 512, "read_ms": 30,
        "writes": 40, "write_bytes": 50 * 512, "write_ms": 60,
        "in_flight": 2, "busy_ms": 70, "weighted_busy_ms": 80,
    }
    assert result["scope"] == "kernel_visible_devices"


def test_windows_diskstats_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")
    assert service._disk_snapshot() == {"status": "unavailable", "reason": "requires_linux_procfs"}


def test_deltas_reject_statistics_reset_and_ignore_inflight_gauge():
    assert service._counter_delta({"stats_reset": "a", "wal_bytes": 10}, {"stats_reset": "b", "wal_bytes": 20})["reason"] == "statistics_reset"
    assert service._counter_delta({"reads": 10}, {"reads": 1})["reason"] == "counter_decreased"
    before = {"postgres": {"status": "unavailable"}, "disk": {"status": "ok", "devices": {"sda": {"reads": 10, "in_flight": 5}}}}
    after = {"postgres": {"status": "unavailable"}, "disk": {"status": "ok", "devices": {"sda": {"reads": 12, "in_flight": 0}}}}
    assert service._deltas(before, after)["disk"]["sda"] == {"status": "ok", "values": {"reads": 2}}


def test_redis_restart_does_not_produce_negative_persistence_delta():
    def snapshot(run_id, count):
        return {"postgres": {}, "disk": {}, "redis": {
            "status": "ok", "server_run_id": run_id,
            "persistence": {"aof_delayed_fsync": count}, "fork": {"total_forks": count},
        }}

    result = service._deltas(snapshot("before", 3), snapshot("after", 1))
    assert result["redis"]["reason"] == "statistics_reset"
    result = service._deltas(snapshot("same", 3), snapshot("same", 5))
    assert result["redis"]["values"] == {"aof_delayed_fsync": 2, "total_forks": 2}


def test_postgres_io_delta_matches_identity_and_only_cumulative_fields():
    def row(backend, count, reset="same"):
        return {"backend_type": backend, "object": "wal", "context": "normal",
                "writes": count, "write_time": count * 2, "fsyncs": None,
                "stats_reset": reset, "op_bytes": 8192, "in_flight": count}

    def snapshot(rows):
        return {"postgres": {"status": "ok", "wal": {}, "checkpointer": {},
                             "bgwriter": {}, "io": rows}, "disk": {}}

    before = snapshot([row("client backend", 3), row("walwriter", 10)])
    after = snapshot([row("walwriter", 12), row("client backend", 8), row("new backend", 1)])
    result = service._deltas(before, after)["postgres"]["io"]
    assert result[0]["backend_type"] == "walwriter"
    assert result[0]["values"] == {"writes": 2, "write_time": 4}
    assert result[1]["values"] == {"writes": 5, "write_time": 10}
    assert result[2]["reason"] == "baseline_unavailable"
    for field in ("backend_type", "object", "context"):
        changed = row("client backend", 8)
        changed[field] = "other"
        assert service._deltas(before, snapshot([changed]))["postgres"]["io"][0]["reason"] == "baseline_unavailable"
    reset = service._deltas(before, snapshot([row("client backend", 8, "reset")]))
    assert reset["postgres"]["io"][0]["reason"] == "statistics_reset"


def test_redis_missing_instance_identity_rejects_delta():
    snapshot = {"postgres": {}, "disk": {}, "redis": {"status": "ok"}}
    assert service._deltas(snapshot, snapshot)["redis"]["reason"] == "instance_identity_unavailable"


def test_capture_reports_failure_type_without_credentials(monkeypatch):
    def fail():
        raise RuntimeError("postgres://secret:password@private/ sensitive SQL")

    for name in ("_postgres_snapshot", "_redis_snapshot", "_disk_snapshot"):
        monkeypatch.setattr(service, name, fail)
    result = service._capture()
    assert "password" not in json.dumps(result)
    assert all(result[key]["error_type"] == "RuntimeError" for key in ("postgres", "redis", "disk"))


def test_sampling_rejects_overlap_and_releases_lock_after_failure(monkeypatch):
    monkeypatch.setattr(service, "_capture", lambda: (_ for _ in ()).throw(RuntimeError("failure")))
    with pytest.raises(RuntimeError):
        service.sample_storage_observation(0.1)
    assert service._SAMPLE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(service.StorageObservationBusyError):
            service.sample_storage_observation(0.1)
    finally:
        service._SAMPLE_LOCK.release()
    with pytest.raises(ValueError):
        service.sample_storage_observation(11)


@pytest.mark.asyncio
async def test_sampling_route_does_not_block_health_and_rejects_overlap(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def capture():
        entered.set()
        assert release.wait(2)
        return {"postgres": {"status": "unavailable"}, "disk": {"status": "unavailable"}}

    monkeypatch.setattr(service, "_capture", capture)
    monkeypatch.setattr("app.core.resource_budget_service.get_resource_budget_service", lambda: SimpleNamespace(snapshot=lambda: {}))
    app = FastAPI()
    app.add_api_route("/api/system/storage-observation", routes.get_storage_observation)
    app.add_api_route("/api/health", lambda: {"status": "ok"})
    assert "/api/system/storage-observation" not in routes.SECURITY_GATE_PUBLIC_API_PATHS
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.get("/api/system/storage-observation?interval_seconds=0.1"))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert (await asyncio.wait_for(client.get("/api/health"), timeout=1)).status_code == 200
            assert (await client.get("/api/system/storage-observation")).status_code == 409
            assert (await client.get("/api/system/storage-observation?interval_seconds=11")).status_code == 422
        finally:
            release.set()
        assert (await pending).json()["read_only"] is True


@pytest.mark.asyncio
async def test_storage_observation_inherits_existing_security_gate(monkeypatch):
    gate = SimpleNamespace(
        is_enforced=lambda: True, get_client_ip=lambda _request: "test",
        get_active_blacklist=lambda _ip: None, verify_cookie=lambda _token: False,
    )
    monkeypatch.setattr(routes, "get_security_gate_service", lambda: gate)
    monkeypatch.setattr(routes, "_log_gate_api_rejection", lambda *_args: None)
    monkeypatch.setattr(service, "sample_storage_observation", lambda *_args: pytest.fail("未验证门禁不得执行采样"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routes.app), base_url="http://test") as client:
        response = await client.get("/api/system/storage-observation")
    assert response.status_code == 401
    assert response.json()["gate_required"] is True
