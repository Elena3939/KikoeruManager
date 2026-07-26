import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.responses import PlainTextResponse

from app.api import routes
from app.config.settings import AppConfig, DatabaseConfig, ResourceBudgetConfig, RedisConfig, BonusProbeConfig


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
        database_write=4,
        library_index_write=1,
        bonus_probe_database_write=1,
    )


def test_redis_and_bonus_probe_defaults_use_parallel_probe_workers():
    config = AppConfig()

    assert config.redis == RedisConfig(
        enabled=True,
        required=True,
        url="redis://localhost:6379/0",
        namespace="kikoerumanager",
        environment="prod",
        socket_timeout_seconds=2.0,
        connect_timeout_seconds=2.0,
        runtime_ttl_seconds=259200,
        short_cache_ttl_seconds=60,
        event_stream_maxlen=50000,
        dirty_stream_maxlen=200000,
    )
    assert config.bonus_probe == BonusProbeConfig(
        max_active_jobs=1,
        normal_batch_size=500,
        normal_concurrency=6,
        deep_batch_size=500,
        deep_concurrency=6,
        new_release_batch_size=100,
        new_release_concurrency=6,
        max_batch_size=500,
        max_concurrency=6,
        product_info_total_concurrency=6,
        cache_lookup_batch_size=1000,
        cache_write_batch_size=100,
    )


def test_database_config_defaults_are_nas_safe():
    config = AppConfig()

    assert config.database == DatabaseConfig(
        host="127.0.0.1",
        port=5432,
        database="kikoerumanager",
        username="kikoerumanager",
        password="",
        sslmode="prefer",
        connect_timeout_seconds=10,
        pool_size=10,
        max_overflow=20,
        pool_recycle_seconds=1800,
        pool_timeout_seconds=30,
        statement_timeout_ms=120000,
        startup_health_check=True,
        slow_query_monitor_enabled=True,
        slow_query_threshold_ms=500,
        auto_explain_enabled=False,
        auto_explain_threshold_ms=1000,
        search_backend="pg_trgm",
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
        "database_write": 4,
        "library_index_write": 1,
        "bonus_probe_database_write": 1,
    }
    assert response.json()["redis"]["url"] == "redis://localhost:6379/0"
    assert response.json()["bonus_probe"]["max_active_jobs"] == 1
    assert response.json()["database"]["host"] == "127.0.0.1"
    assert response.json()["database"]["database"] == "kikoerumanager"
    assert response.json()["database"]["password"] == ""
    assert response.json()["database"]["statement_timeout_ms"] == 120000


def test_reveal_circle_external_search_secret_only_returns_south_plus_cookie(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "_read_circle_external_search_secret_from_disk",
        lambda key: "bbs_lastvisit=actual-cookie" if key == "south_plus_cookie" else "",
    )

    response = client.post(
        "/api/config/circle-external-search/reveal-secret",
        json={"key": "south_plus_cookie"},
    )

    assert response.status_code == 200
    assert response.json() == {"value": "bbs_lastvisit=actual-cookie"}

    rejected = client.post(
        "/api/config/circle-external-search/reveal-secret",
        json={"key": "south_plus_proxy"},
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "不支持读取该敏感字段"


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
                "database_write": 1,
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
        "database_write": 1,
        "library_index_write": 1,
        "bonus_probe_database_write": 1,
    }


def test_update_config_validates_redis_and_bonus_probe(client, monkeypatch):
    captured = {}

    def fake_save_config(payload):
        captured.update(payload)
        return True

    monkeypatch.setattr("app.config.settings.save_config", fake_save_config)
    monkeypatch.setattr(routes, "get_config", lambda: AppConfig())
    monkeypatch.setattr(routes, "_read_redis_url_from_disk", lambda: "redis://:secret@localhost:6379/0")
    monkeypatch.setattr(routes, "_read_redis_url_from_runtime", lambda: "")

    response = client.post(
        "/api/config",
        json={
            "redis": {
                "enabled": True,
                "required": False,
                "url": "redis://:********@localhost:6379/0",
                "namespace": "Prekikoeru",
                "environment": "dev",
            },
            "bonus_probe": {
                "max_active_jobs": 0,
                "normal_batch_size": 1000,
                "normal_concurrency": 9,
                "max_batch_size": 200,
                "max_concurrency": 2,
            },
        },
    )

    assert response.status_code == 200
    assert captured["redis"]["url"] == "redis://:secret@localhost:6379/0"
    assert captured["redis"]["namespace"] == "kikoerumanager"
    assert captured["redis"]["required"] is False
    assert captured["bonus_probe"]["max_active_jobs"] == 1
    assert captured["bonus_probe"]["normal_batch_size"] == 200
    assert captured["bonus_probe"]["normal_concurrency"] == 2


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


def test_database_maintenance_performance_endpoint(client, monkeypatch):
    def fake_snapshot(*, limit=10):
        return {
            "backend": "postgresql",
            "limit": limit,
            "pg_stat_statements": {"queryable": True},
            "slow_queries": [{"queryid": "1", "calls": 2, "query": "SELECT 1"}],
            "table_stats": [{"table": "activity_logs", "seq_scan_percent": 0.0}],
            "search_status": {"all_ready": True, "domains": []},
            "advice": [],
        }

    monkeypatch.setattr("app.core.database_maintenance_service.performance_snapshot", fake_snapshot)

    response = client.get("/api/database/maintenance/performance", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"] == "postgresql"
    assert payload["limit"] == 5
    assert payload["pg_stat_statements"]["queryable"] is True
    assert payload["slow_queries"][0]["query"] == "SELECT 1"
    assert payload["search_status"]["all_ready"] is True


def test_database_maintenance_search_status_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.database_maintenance_service.search_status_snapshot",
        lambda: {
            "backend": "postgresql",
            "default_search_backend": "pg_trgm",
            "pg_trgm_enabled": True,
            "domains": [{"domain": "activity_logs", "search_enabled": True}],
            "all_ready": True,
        },
    )

    response = client.get("/api/database/maintenance/search-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_search_backend"] == "pg_trgm"
    assert payload["domains"][0]["domain"] == "activity_logs"


def test_database_maintenance_reset_pg_stat_statements_conflict(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.database_maintenance_service.reset_pg_stat_statements",
        lambda: {"ok": False, "reset": False, "error": "pg_stat_statements 不可查询"},
    )

    response = client.post("/api/database/maintenance/pg-stat-statements/reset")

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["error"] == "pg_stat_statements 不可查询"


def test_activity_log_search_uses_plain_searchable_text_expression():
    captured = {}

    class Result:
        def fetchall(self):
            return [("log-1",)]

    class FakeDb:
        def execute(self, statement, params):
            captured["statement"] = str(statement)
            captured["params"] = params
            return Result()

    ids, backend = routes._run_activity_log_id_search(FakeDb(), "RJ_100%", 10)

    assert ids == ["log-1"]
    assert backend == "postgresql_pg_trgm"
    assert "WHERE searchable_text ILIKE" in captured["statement"]
    assert "COALESCE(searchable_text" not in captured["statement"]
    assert captured["params"]["p"] == "%RJ!_100!%%"


def test_password_search_uses_expression_trigram_index():
    clause = routes._password_search_filter("RJ_100%")
    normalized_sql = " ".join(str(clause).split())

    assert (
        "COALESCE(rjcode, '') || ' ' || COALESCE(filename, '') || ' ' || "
        "COALESCE(password, '') || ' ' || COALESCE(description, '')"
    ) in normalized_sql
    assert "ILIKE :password_search_pattern ESCAPE '!'" in normalized_sql
    assert " OR " not in f" {normalized_sql.upper()} "
    assert clause.compile().params["password_search_pattern"] == "%RJ!_100!%%"


def test_processed_archive_search_uses_single_column_trigram_filters():
    clause = routes._processed_archive_search_filter("RJ_100%")
    normalized_sql = " ".join(str(clause).split())

    assert "rjcode ILIKE :processed_archive_search_pattern ESCAPE '!'" in normalized_sql
    assert "filename ILIKE :processed_archive_search_pattern ESCAPE '!'" in normalized_sql
    assert "COALESCE" not in normalized_sql
    assert clause.compile().params["processed_archive_search_pattern"] == "%RJ!_100!%%"


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


def test_redis_status_endpoint(client, monkeypatch):
    class Service:
        def diagnostics(self):
            return {"enabled": True, "available": True, "url_masked": "redis://:********@localhost:6379/0"}

    monkeypatch.setattr(
        "app.core.redis_service.get_redis_service",
        lambda: Service(),
    )

    response = client.get("/api/system/redis/status")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert "secret" not in response.text


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
    routes._LIBRARY_STORAGE_INFO_REFRESH_TASKS.clear()

    class Library:
        id = "nas"
        name = "NAS"
        type = "synology_filestation"
        synology = object()
        root_path = "/NAS"

    class SlowClient:
        async def get_storage_info(self, root_path):
            assert root_path == "/NAS"
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


@pytest.mark.asyncio
async def test_library_storage_info_cold_requests_share_singleflight(monkeypatch):
    routes._LIBRARY_STORAGE_INFO_CACHE.clear()
    routes._LIBRARY_STORAGE_INFO_REFRESH_TASKS.clear()
    calls = 0

    class Library:
        id = "nas"
        name = "NAS"
        type = "synology_filestation"
        synology = object()
        root_path = "/ASMR"

    class Client:
        async def get_storage_info(self, root_path):
            nonlocal calls
            calls += 1
            assert root_path == "/ASMR"
            await asyncio.sleep(0.01)
            return {
                "total_size_bytes": 100,
                "used_size_bytes": 40,
                "free_size_bytes": 60,
                "free_space_gb": 0,
                "volumes": [],
            }

    class Manager:
        def get_library_definition(self, library_id):
            assert library_id == "nas"
            return Library()

        def get_cached_synology_client(self, synology):
            return Client()

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(routes, "_LIBRARY_STORAGE_INFO_COLD_TIMEOUT_SECONDS", 0.2)

    first, second = await asyncio.gather(
        routes.get_library_storage_info("nas"),
        routes.get_library_storage_info("nas"),
    )

    assert first["free_size_bytes"] == 60
    assert second["free_size_bytes"] == 60
    assert calls == 1


@pytest.mark.asyncio
async def test_global_search_suggest_never_runs_remote_fallback(monkeypatch):
    class Manager:
        def list_libraries(self):
            return [{
                "id": "nas",
                "name": "NAS",
                "type": "synology_filestation",
                "root_path": "/ASMR",
            }]

        async def list_files(self, *_args, **_kwargs):
            raise AssertionError("suggest 模式不得触发远程搜索")

    class Service:
        def get_status(self, _library_id):
            return None

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(routes, "get_library_index_service", lambda: Service())

    payload = await routes.global_search_library_index(keyword="missing", mode="suggest", limit=6)

    assert payload["items"] == []
    assert payload["fallback_used"] is False
    assert payload["library_status"][0]["search_mode"] == "skipped_suggest"


@pytest.mark.asyncio
async def test_global_search_marks_same_language_translation_as_related(monkeypatch):
    query_rjcode = "RJ01700002"
    actual_rjcode = "RJ01700003"

    class Manager:
        def list_libraries(self):
            return [{
                "id": "local",
                "name": "本地库存",
                "type": "local",
                "root_path": "D:/library",
            }]

    class Service:
        def get_status(self, _library_id):
            return SimpleNamespace(status="ready", total_entries=1)

        def has_usable_snapshot(self, _library_id):
            return True

        def find_by_rjcodes(self, rjcodes, library_id=None, entry_type="dir", limit=100):
            assert rjcodes == [query_rjcode, actual_rjcode]
            assert library_id == "local"
            return [SimpleNamespace(
                library_id="local",
                entry_type="dir",
                name=f"[{actual_rjcode}] 翻译作",
                relative_path=f"circle/[{actual_rjcode}] 翻译作",
                absolute_path=f"D:/library/circle/[{actual_rjcode}] 翻译作",
                parent_path="circle",
                depth=1,
                size=1024,
                file_count=4,
                mtime=1,
                rjcode=actual_rjcode,
            )]

    async def fake_relation(_matched_rjcode):
        return {
            "query_rjcode": query_rjcode,
            "group_key": "simplified",
            "group_label": "简中",
            "search_rjcodes": [query_rjcode, actual_rjcode],
            "related_rjcodes": [actual_rjcode],
            "owned_locations": [],
        }

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(routes, "get_library_index_service", lambda: Service())
    monkeypatch.setattr(routes, "_resolve_global_index_translation_relation", fake_relation)

    payload = await routes.global_search_library_index(
        keyword=query_rjcode,
        mode="suggest",
        limit=6,
    )

    assert payload["related_rjcodes"] == [actual_rjcode]
    assert payload["items"][0]["rjcode"] == actual_rjcode
    assert payload["items"][0]["search_match_type"] == "related_translation"
    assert payload["items"][0]["search_relation_label"] == "简中"


def test_global_search_exact_rj_collapses_descendant_directories():
    items = [
        {
            "library_id": "local",
            "entry_type": "dir",
            "relative_path": "circle/[RJ01624471] work",
            "rjcode": "RJ01624471",
        },
        {
            "library_id": "local",
            "entry_type": "dir",
            "relative_path": "circle/[RJ01624471] work/05_特典",
            "rjcode": "RJ01624471",
        },
        {
            "library_id": "local",
            "entry_type": "dir",
            "relative_path": "archive/[RJ01624471] another copy",
            "rjcode": "RJ01624471",
        },
        {
            "library_id": "nas",
            "entry_type": "dir",
            "relative_path": "ASMR/[RJ01624471] remote copy",
            "rjcode": "RJ01624471",
        },
    ]

    collapsed = routes._collapse_exact_rj_descendants(items, "RJ01624471")

    assert [item["relative_path"] for item in collapsed] == [
        "circle/[RJ01624471] work",
        "archive/[RJ01624471] another copy",
        "ASMR/[RJ01624471] remote copy",
    ]


def test_circle_cover_miss_downloads_and_returns_local_file(client, monkeypatch, tmp_path):
    from app.core import circle_image_cache_service
    from app.core.circle_image_cache_service import CircleImageCacheService

    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    downloaded = []

    async def ensure_local(filename, **_kwargs):
        downloaded.append(filename)
        path = image_cache.resolve_filename(filename)
        path.write_bytes(b"cached-cover")
        return path

    image_cache.ensure_local_for_filename = ensure_local

    monkeypatch.setattr(
        circle_image_cache_service,
        "get_circle_image_cache_service",
        lambda: image_cache,
    )

    response = client.get("/api/circle-completion/cover/RJ01012345.jpg")

    assert response.status_code == 200
    assert response.content == b"cached-cover"
    assert downloaded == ["RJ01012345.jpg"]


def test_asmr_status_returns_requested_tasks_beyond_default_window(client, monkeypatch):
    from app.core.task_engine import TaskType

    tasks = [
        SimpleNamespace(
            id=f"asmr-task-{index}",
            type=TaskType.ASMR_SYNC_DOWNLOAD,
            status=SimpleNamespace(value="completed"),
            task_metadata={},
        )
        for index in range(25)
    ]

    class Engine:
        def get_all_tasks(self):
            return tasks

    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: Engine())
    monkeypatch.setattr(
        routes,
        "_serialize_asmr_sync_task_status",
        lambda task, session_map: {"id": task.id},
    )

    response = client.get(
        "/api/asmr-sync/status",
        params={"task_ids": "asmr-task-24,asmr-task-0"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tasks"] == 2
    assert [item["id"] for item in payload["tasks"]] == ["asmr-task-24", "asmr-task-0"]


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


def test_tail_lines_reads_traceback_context_for_timestamp(tmp_path):
    log_file = tmp_path / "app.log"
    traceback_lines = [
        f'  File "D:/app/service_{index}.py", line {index}, in run'
        for index in range(400)
    ]
    log_file.write_text(
        "2026-07-12 15:00:00 [ERROR] app.worker - 处理失败\n"
        "Traceback (most recent call last):\n"
        + "\n".join(traceback_lines)
        + "\nRuntimeError: failed\n",
        encoding="utf-8",
    )

    result = routes._tail_lines(str(log_file), 100)

    assert len(result) == 1
    assert result[0].startswith(routes._LOG_TRACEBACK_BLOCK_PREFIX)
    payload = json.loads(result[0][len(routes._LOG_TRACEBACK_BLOCK_PREFIX):])
    assert payload["time"] == "2026-07-12 15:00:00"
    assert payload["level"] == "ERROR"
