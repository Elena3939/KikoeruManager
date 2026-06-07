from types import SimpleNamespace

import pytest
from starlette.responses import PlainTextResponse

from app.api import routes
from app.config.settings import AppConfig, ResourceBudgetConfig


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
        remote_fs=4,
        network_download=2,
        sqlite_write=0,
    )


def test_get_config_includes_resource_budget(client, monkeypatch):
    monkeypatch.setattr(routes, "get_config", lambda: AppConfig())

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["resource_budget"] == {
        "enabled": True,
        "disk_io_local": 2,
        "archive_cpu": 0,
        "remote_fs": 4,
        "network_download": 2,
        "sqlite_write": 0,
    }


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
        "remote_fs": 3,
        "network_download": 4,
        "sqlite_write": 1,
    }


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
