from types import SimpleNamespace

from app.api import routes
from app.core.redis_service import _mask_redis_url, RedisService


def test_mask_redis_url_hides_password():
    assert _mask_redis_url("redis://user:secret@localhost:6379/0") == "redis://user:********@localhost:6379/0"
    assert _mask_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


def test_mask_redis_config_hides_url_password():
    config = SimpleNamespace(
        redis=SimpleNamespace(
            model_dump=lambda: {
                "enabled": True,
                "required": True,
                "url": "redis://:secret@localhost:6379/0",
                "namespace": "kikoerumanager",
                "environment": "prod",
            }
        )
    )

    masked = routes._mask_redis_config(config)

    assert masked["url"] == "redis://:********@localhost:6379/0"


def test_redis_service_diagnostics_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: SimpleNamespace(
            redis=SimpleNamespace(
                enabled=False,
                required=False,
                url="redis://:secret@localhost:6379/0",
                namespace="kikoerumanager",
                environment="test",
                socket_timeout_seconds=0.1,
                connect_timeout_seconds=0.1,
                runtime_ttl_seconds=60,
                short_cache_ttl_seconds=1,
                event_stream_maxlen=100,
                dirty_stream_maxlen=100,
            )
        ),
    )

    payload = RedisService().diagnostics()

    assert payload["enabled"] is False
    assert payload["available"] is False
    assert payload["url_masked"] == "redis://:********@localhost:6379/0"


def test_redis_service_task_runtime_helpers(monkeypatch):
    store = {}

    class FakeClient:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: SimpleNamespace(
            redis=SimpleNamespace(
                enabled=True,
                required=False,
                url="redis://localhost:6379/0",
                namespace="kikoerumanager",
                environment="test",
                socket_timeout_seconds=0.1,
                connect_timeout_seconds=0.1,
                runtime_ttl_seconds=60,
                short_cache_ttl_seconds=1,
                event_stream_maxlen=100,
                dirty_stream_maxlen=100,
            )
        ),
    )
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: FakeClient())

    task = SimpleNamespace(
        id="task-runtime-helper",
        type=SimpleNamespace(value="extract"),
        status=SimpleNamespace(value="processing"),
        progress=44,
        current_step="Redis runtime helper",
        task_metadata={
            "task_domain": "system",
            "progress_log": [{"message": "ok"}],
            "download_runtime": {"speed_bytes_per_sec": 2048},
            "upload_runtime": {"current_file_name": "upload.wav"},
            "bonus_probe_meta": {"release_date": "2026-01-06"},
            "awaiting_manual_match": True,
        },
    )

    service.write_task_runtime_sync(task, reason="progress")
    payload = service.get_task_runtime_sync("task-runtime-helper")

    assert payload["task_id"] == "task-runtime-helper"
    assert payload["progress"] == 44
    assert payload["current_step"] == "Redis runtime helper"
    assert payload["progress_log"] == [{"message": "ok"}]
    assert payload["download_runtime"] == {"speed_bytes_per_sec": 2048}
    assert payload["upload_runtime"] == {"current_file_name": "upload.wav"}
    assert payload["bonus_probe_meta"] == {"release_date": "2026-01-06"}
    assert payload["awaiting_manual_match"] is True


def test_redis_service_write_realtime_event_uses_events_stream(monkeypatch):
    calls = []
    service = RedisService()
    monkeypatch.setattr(
        service,
        "append_stream_payload_sync",
        lambda stream_name, payload, **kwargs: calls.append((stream_name, payload, kwargs)) or "1-0",
    )

    result = service.write_realtime_event_sync({"type": "task.center.changed", "id": "engine:1"})

    assert result == "1-0"
    assert calls == [("events:stream", {"type": "task.center.changed", "id": "engine:1"}, {"required": False})]


def test_redis_service_bonus_probe_cache_dirty_helpers(monkeypatch):
    store = {}
    stream = []

    class FakePipeline:
        def __init__(self, client):
            self.client = client

        def set(self, key, value, ex=None):
            self.client.set(key, value, ex=ex)
            return self

        def xadd(self, key, fields, maxlen=None, approximate=True):
            self.client.xadd(key, fields, maxlen=maxlen, approximate=approximate)
            return self

        def execute(self):
            return []

    class FakeClient:
        def pipeline(self, transaction=False):
            return FakePipeline(self)

        def set(self, key, value, ex=None):
            store[key] = value

        def mget(self, keys):
            return [store.get(key) for key in keys]

        def xadd(self, key, fields, maxlen=None, approximate=True):
            stream.append((key, fields, maxlen, approximate))
            return f"{len(stream)}-0"

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: SimpleNamespace(
            redis=SimpleNamespace(
                enabled=True,
                required=False,
                url="redis://localhost:6379/0",
                namespace="kikoerumanager",
                environment="test",
                socket_timeout_seconds=0.1,
                connect_timeout_seconds=0.1,
                runtime_ttl_seconds=60,
                short_cache_ttl_seconds=1,
                event_stream_maxlen=100,
                dirty_stream_maxlen=100,
            )
        ),
    )
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: FakeClient())

    written = service.write_bonus_probe_cache_dirty_sync([
        {"rjcode": "rj01000001", "exists": True, "probe_status": "ok", "raw_summary_json": {"a": 1}}
    ])
    rows = service.read_bonus_probe_cache_rows_sync(["RJ01000001"])

    assert written == 1
    assert rows["RJ01000001"]["rjcode"] == "RJ01000001"
    assert rows["RJ01000001"]["raw_summary_json"] == {"a": 1}
    assert stream[0][0] == service.stream_key("bonus-probe:cache:stream")
