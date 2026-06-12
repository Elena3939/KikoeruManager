from types import SimpleNamespace

import pytest
from starlette.responses import PlainTextResponse

from app.api import routes
from app.config.settings import AppConfig, DatabaseConfig, ResourceBudgetConfig


def test_notification_cleanup_config_reads_notification_center(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_config",
        lambda: SimpleNamespace(
            notification_center=SimpleNamespace(retain_days=14, max_items=321),
        ),
    )

    assert routes._notification_cleanup_config() == (14, 321)


def test_resource_budget_config_defaults_are_conservative():
    config = AppConfig()

    assert config.resource_budget == ResourceBudgetConfig(
        enabled=True,
        disk_io_local=2,
        archive_cpu=0,
        archive_inspect=0,
        remote_fs=4,
        network_download=5,
        sqlite_write=1,
    )


def test_database_config_defaults_are_nas_safe():
    config = AppConfig()

    assert config.database == DatabaseConfig(
        journal_mode="WAL",
        synchronous="FULL",
        busy_timeout_ms=60000,
        wal_autocheckpoint=500,
        cache_size_kb=20000,
        pool_size=2,
        max_overflow=2,
        pool_recycle_seconds=1800,
        startup_quick_check=True,
        startup_integrity_check=False,
    )


def test_get_config_includes_resource_budget(client, monkeypatch):
    monkeypatch.setattr(routes, "get_config", lambda: AppConfig())

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["resource_budget"] == {
        "enabled": True,
        "disk_io_local": 2,
        "archive_cpu": 0,
        "archive_inspect": 0,
        "remote_fs": 4,
        "network_download": 5,
        "sqlite_write": 1,
    }
    assert response.json()["database"]["synchronous"] == "FULL"
    assert response.json()["database"]["busy_timeout_ms"] == 60000


def test_update_config_validates_resource_budget(client, monkeypatch):
    captured = {}

    def fake_save_config(payload):
        captured.update(payload)
        return True

    monkeypatch.setattr("app.config.settings.save_config", fake_save_config)
    monkeypatch.setattr(routes, "get_config", lambda: AppConfig())

    response = client.post(
        "/api/config",
        json={
            "resource_budget": {
                "enabled": True,
                "disk_io_local": 1,
                "archive_cpu": 2,
                "archive_inspect": 3,
                "remote_fs": 3,
                "network_download": 4,
                "sqlite_write": 1,
            }
        },
    )

    assert response.status_code == 200
    assert captured["resource_budget"] == {
        "enabled": True,
        "disk_io_local": 1,
        "archive_cpu": 2,
        "archive_inspect": 3,
        "remote_fs": 3,
        "network_download": 4,
        "sqlite_write": 1,
    }


def test_database_maintenance_health_returns_503_on_failed_check(client, monkeypatch):
    monkeypatch.setattr(
        "app.models.database.check_database_health",
        lambda *, full=False: {
            "ok": False,
            "check": "quick_check",
            "messages": ["database disk image is malformed"],
        },
    )

    response = client.get("/api/database/maintenance/health")

    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["messages"] == ["database disk image is malformed"]


def test_notification_cleanup_config_clamps_invalid_values(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_config",
        lambda: SimpleNamespace(
            notification_center=SimpleNamespace(retain_days=0, max_items=-10),
        ),
    )

    assert routes._notification_cleanup_config() == (30, 1)


def test_activity_log_compact_config_reads_environment(monkeypatch):
    monkeypatch.setenv("KIKOERUMANAGER_ACTIVITY_COMPACT_DAYS", "45")
    monkeypatch.setenv("KIKOERUMANAGER_ACTIVITY_COMPACT_MIN_BYTES", "4096")
    monkeypatch.setenv("KIKOERUMANAGER_ACTIVITY_COMPACT_MAX_ROWS", "1200")
    monkeypatch.setenv("KIKOERUMANAGER_ACTIVITY_COMPACT_SECONDS", "3.5")

    assert routes._activity_log_compact_config() == {
        "older_than_days": 45,
        "min_detail_bytes": 4096,
        "max_rows": 1200,
        "time_budget_seconds": 3.5,
    }


def test_task_phase_metric_cleanup_config_reads_environment(monkeypatch):
    monkeypatch.setenv("KIKOERUMANAGER_TASK_PHASE_METRIC_RETAIN_DAYS", "9")
    monkeypatch.setenv("KIKOERUMANAGER_TASK_PHASE_METRIC_MAX_ITEMS", "1234")

    assert routes._task_phase_metric_cleanup_config() == {
        "retain_days": 9,
        "max_items": 1234,
    }


def test_task_center_materialized_backfill_endpoint(client, monkeypatch):
    class Service:
        async def backfill_materialized_items(self):
            return {
                "engine_item_count": 2,
                "upserted": 2,
                "pruned": 0,
                "matched": True,
                "diff_count": 0,
                "diffs": [],
            }

    monkeypatch.setattr(
        "app.core.task_center_service.get_task_center_service",
        lambda: Service(),
    )

    response = client.post("/api/task-center/materialized/backfill")

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["upserted"] == 2


def test_task_center_materialized_list_endpoint(client, monkeypatch):
    captured = {}

    class Service:
        def list_materialized_items(self, **kwargs):
            captured.update(kwargs)
            return {
                "items": [{"id": "subtitle-pending:pending-1"}],
                "total": 1,
                "offset": kwargs["offset"],
                "limit": kwargs["limit"],
                "counts_by_domain": {"subtitle_import": 1},
                "counts_by_status": {"waiting_manual": 1},
                "highlight_counts": {"waiting_manual": 1},
                "mode": "materialized_summary",
                "generated_at": "2026-01-01T00:00:00",
            }

    monkeypatch.setattr(
        "app.core.task_center_service.get_task_center_service",
        lambda: Service(),
    )

    response = client.get(
        "/api/task-center/materialized/list",
        params={
            "domain": "http_download",
            "status": "processing",
            "search": "file.zip",
            "offset": 5,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert response.json()["items"] == [{"id": "subtitle-pending:pending-1"}]
    assert captured == {
        "domain": "http_download",
        "status": "processing",
        "search": "file.zip",
        "offset": 5,
        "limit": 20,
    }


def test_activity_log_rollup_backfill_endpoint(client, monkeypatch):
    captured = {}

    class Service:
        def trigger_backfill(self, *, limit_groups):
            captured["limit_groups"] = limit_groups
            return {
                "started": True,
                "already_running": False,
                "status": {"state": "running", "total_groups": 0, "rebuilt_groups": 0},
            }

    monkeypatch.setattr(
        "app.core.activity_log_rollup_service.get_activity_log_rollup_service",
        lambda: Service(),
    )

    response = client.post("/api/activity-logs/rollups/backfill", params={"limit_groups": 123})

    assert response.status_code == 200
    assert response.json()["started"] is True
    assert response.json()["status"]["state"] == "running"
    assert captured == {"limit_groups": 123}


def test_activity_log_rollup_backfill_status_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.activity_log_rollup_service.get_activity_log_rollup_backfill_state",
        lambda: {"state": "done", "total_groups": 3, "rebuilt_groups": 3},
    )

    response = client.get("/api/activity-logs/rollups/backfill/status")

    assert response.status_code == 200
    assert response.json() == {"state": "done", "total_groups": 3, "rebuilt_groups": 3}


def test_activity_log_rollup_diff_endpoint(client, monkeypatch):
    captured = {}

    class Service:
        def diff(self, *, limit_groups):
            captured["limit_groups"] = limit_groups
            return {"matched": False, "diff_count": 1, "diffs": [{"rollup_key": "batch:x"}]}

    monkeypatch.setattr(
        "app.core.activity_log_rollup_service.get_activity_log_rollup_service",
        lambda: Service(),
    )

    response = client.get("/api/activity-logs/rollups/diff", params={"limit_groups": 456})

    assert response.status_code == 200
    assert response.json()["diff_count"] == 1
    assert captured == {"limit_groups": 456}


def test_resource_budget_snapshot_endpoint(client, monkeypatch):
    class Service:
        def snapshot(self):
            return {
                "enabled": True,
                "resources": {
                    "remote_fs": {
                        "configured_limit": 4,
                        "active_limit": 4,
                        "active": 2,
                        "available": 2,
                        "passthrough": False,
                    }
                },
                "generated_at": "2026-01-01T00:00:00",
            }

    monkeypatch.setattr(
        "app.core.resource_budget_service.get_resource_budget_service",
        lambda: Service(),
    )

    response = client.get("/api/system/resource-budget")

    assert response.status_code == 200
    assert response.json()["resources"]["remote_fs"]["active"] == 2


def test_system_storage_info_uses_ttl_cache(client, monkeypatch):
    routes._SYSTEM_STORAGE_INFO_CACHE.update({"key": None, "expires_at": 0.0, "payload": None})

    class Storage:
        temp_path = "D:/temp"
        library_path = "D:/library"
        input_path = "D:/input"

    class Extract:
        max_concurrent_extractions = 0

    class Processing:
        max_workers = 4

    class Config:
        storage = Storage()
        extract = Extract()
        processing = Processing()

    class Service:
        def _resolve_extract_concurrency(self):
            return 3, "auto: 测试"

    calls = {"detect": 0}

    class ExtractService:
        @staticmethod
        def _detect_storage_type(path):
            calls["detect"] += 1
            return "ssd"

        def _resolve_extract_concurrency(self):
            return Service()._resolve_extract_concurrency()

    monkeypatch.setattr(routes, "get_config", lambda: Config())
    monkeypatch.setattr("app.core.extract_service.ExtractService", ExtractService)

    first = client.get("/api/system/storage-info")
    second = client.get("/api/system/storage-info")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["primary_type"] == "ssd"
    assert second.json()["resolved_limit"] == 3
    assert calls["detect"] == 3


def test_library_storage_info_returns_cached_value_when_refresh_times_out(client, monkeypatch):
    routes._LIBRARY_STORAGE_INFO_CACHE.clear()

    class Library:
        id = "nas"
        name = "NAS"
        type = "synology_filestation"
        synology = object()

    class SlowClient:
        async def get_storage_info(self):
            import asyncio

            await asyncio.sleep(0.05)
            return {
                "total_size_bytes": 20,
                "used_size_bytes": 10,
                "free_size_bytes": 10,
                "free_space_gb": 0,
                "volumes": [],
            }

    class Manager:
        def get_library_definition(self, library_id):
            assert library_id == "nas"
            return Library()

        def get_cached_synology_client(self, synology):
            return SlowClient()

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(routes, "_LIBRARY_STORAGE_INFO_STALE_TIMEOUT_SECONDS", 0.001)
    routes._LIBRARY_STORAGE_INFO_CACHE["nas"] = {
        "expires_at": 0.0,
        "payload": {
            "library_id": "nas",
            "library_name": "NAS",
            "total_size_bytes": 100,
            "used_size_bytes": 40,
            "free_size_bytes": 60,
            "free_space_gb": 60,
            "volumes": [],
            "stale": False,
            "cached_at": "2026-01-01T00:00:00",
        },
    }

    response = client.get("/api/library/storage-info", params={"library_id": "nas"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["free_size_bytes"] == 60
    assert payload["stale"] is True
    assert payload["stale_reason"] == "timeout"


def test_remote_fs_health_snapshot_endpoint(client, monkeypatch):
    class Manager:
        def remote_health_snapshot(self):
            return {
                "total": 1,
                "degraded_count": 1,
                "items": [{
                    "library_id": "nas-main",
                    "library_name": "NAS",
                    "status": "degraded",
                    "failure_count": 2,
                    "circuit_remaining_seconds": 30,
                }],
                "generated_at": "2026-01-01T00:00:00",
            }

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())

    response = client.get("/api/system/remote-fs-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["degraded_count"] == 1
    assert payload["items"][0]["library_id"] == "nas-main"
    assert payload["items"][0]["circuit_remaining_seconds"] == 30


def test_task_phase_metrics_endpoint_returns_items_and_summary(client, monkeypatch):
    class Service:
        def list_recent(self, *, task_id="", limit=100):
            return [{
                "task_id": task_id or "task-1",
                "phase": "download",
                "duration_ms": 120,
            }]

        def summarize_recent(self, *, task_id="", limit=1000):
            return {
                "sample_count": 1,
                "group_count": 1,
                "groups": [{
                    "task_type": "http_download",
                    "phase": "download",
                    "duration_p95_ms": 120,
                }],
            }

    monkeypatch.setattr(
        "app.core.task_phase_metric_service.get_task_phase_metric_service",
        lambda: Service(),
    )

    response = client.get("/api/system/task-phase-metrics", params={"task_id": "task-1", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["task_id"] == "task-1"
    assert payload["summary"]["groups"][0]["duration_p95_ms"] == 120


def test_task_phase_metrics_cleanup_endpoint(client, monkeypatch):
    captured = {}

    class Service:
        def cleanup(self, **kwargs):
            captured.update(kwargs)
            return {
                "deleted": 3,
                "remaining": 10,
                "retain_days": kwargs["retain_days"],
                "max_items": kwargs["max_items"],
            }

    monkeypatch.setattr(
        "app.core.task_phase_metric_service.get_task_phase_metric_service",
        lambda: Service(),
    )

    response = client.post("/api/system/task-phase-metrics/cleanup", params={"retain_days": 7, "max_items": 300})

    assert response.status_code == 200
    assert response.json()["deleted"] == 3
    assert captured == {"retain_days": 7, "max_items": 300}


def test_slow_api_resource_budget_snapshot_only_keeps_active_and_waiting(monkeypatch):
    class Service:
        def snapshot(self):
            return {
                "enabled": True,
                "resources": {
                    "remote_fs": {
                        "configured_limit": 4,
                        "active_limit": 4,
                        "active": 2,
                        "available": 2,
                        "waiting": 1,
                        "passthrough": False,
                    },
                    "network_download": {
                        "configured_limit": 2,
                        "active_limit": 2,
                        "active": 0,
                        "available": 2,
                        "waiting": 0,
                        "passthrough": False,
                    },
                },
                "generated_at": "2026-01-01T00:00:00",
            }

    monkeypatch.setattr(
        "app.core.resource_budget_service.get_resource_budget_service",
        lambda: Service(),
    )

    assert routes._slow_api_resource_budget_snapshot() == {
        "remote_fs": {"active": 2, "waiting": 1},
    }


@pytest.mark.asyncio
async def test_slow_api_log_includes_query_allowlist_and_resource_budget(monkeypatch, caplog):
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/activity-logs"),
        query_params=SimpleNamespace(
            multi_items=lambda: [
                ("lite", "true"),
                ("token", "secret-token-value"),
                ("path", "D:/private/library/RJ123456"),
            ],
        ),
    )

    async def fake_call_next(_request):
        return PlainTextResponse("ok", status_code=200)

    times = iter([10.0, 10.8])
    monkeypatch.setattr(routes.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(routes, "_SLOW_API_LOG_THRESHOLD_SECONDS", 0.5)
    monkeypatch.setattr(
        routes,
        "_slow_api_resource_budget_snapshot",
        lambda: {"remote_fs": {"active": 2, "waiting": 1}},
    )

    with caplog.at_level("WARNING", logger=routes.__name__):
        response = await routes._call_next_with_perf_log(request, fake_call_next)

    assert response.status_code == 200
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "慢请求" in output
    assert "/api/activity-logs" in output
    assert "'lite': 'true'" in output
    assert "'remote_fs': {'active': 2, 'waiting': 1}" in output
    assert "secret-token-value" not in output
    assert "D:/private/library" not in output


def test_log_file_signature_changes_when_log_grows(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("line 1\n", encoding="utf-8")

    first = routes._log_file_signature(str(log_file))

    log_file.write_text("line 1\nline 2\n", encoding="utf-8")
    second = routes._log_file_signature(str(log_file))

    assert first[0] < second[0]
    assert second[0] == log_file.stat().st_size
    assert second != first
