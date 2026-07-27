import errno
from types import SimpleNamespace

from app.api import routes
from app.core.redis_service import _mask_redis_url, RedisService
import app.core.library_index.mutation_service as mutation_module
import app.core.library_index.watcher_driver as watcher_module
from app.core.library_index.mutation_service import LibraryIndexMutationService
from app.core.library_index.watcher_driver import LibraryIndexWatcherDriver


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
    assert payload["library_index_channel"]["available"] is False
    assert payload["library_index_channel"]["stream"]["group_state"]["exists"] is False
    runtime_status = RedisService().runtime_buffer_status()
    assert runtime_status["redis"]["library_index_channel"]["available"] is False
    assert runtime_status["library_index_channel"]["available"] is False


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


def _library_index_redis_config(*, runtime_backend="redis"):
    return SimpleNamespace(
        redis=SimpleNamespace(
            enabled=True,
            required=True,
            url="redis://localhost:6379/0",
            namespace="kikoerumanager",
            environment="test",
            socket_timeout_seconds=0.1,
            connect_timeout_seconds=0.1,
            runtime_ttl_seconds=60,
            short_cache_ttl_seconds=1,
            event_stream_maxlen=100,
            dirty_stream_maxlen=200,
        ),
        runtime_buffer=SimpleNamespace(
            enabled=True,
            backend=runtime_backend,
            progress_flush_interval_seconds=5,
            log_stream_batch_size=300,
            log_stream_flush_ms=250,
        ),
    )


def test_library_index_mutation_hint_never_uses_memory_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: _library_index_redis_config(runtime_backend="memory"),
    )
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: None)

    result = service.publish_library_index_mutation_hint_sync("library-a", 9, "operation-1")

    assert result == ""
    assert service._memory_status()["streams"] == {}
    runtime = service.library_index_channel_diagnostics_sync()["runtime"]
    assert runtime["published"] == 0
    assert runtime["publish_failures"] == 1
    assert runtime["last_publish_error"] == "Redis client unavailable"

    class BrokenClient:
        def xadd(self, *args, **kwargs):
            raise ConnectionError("redis disconnected")

    monkeypatch.setattr(service, "client", lambda required=False: BrokenClient())
    assert service.publish_library_index_mutation_hint_sync("library-a", 10, "operation-2") == ""
    assert service._memory_status()["streams"] == {}
    runtime = service.library_index_channel_diagnostics_sync()["runtime"]
    assert runtime["publish_failures"] == 2
    assert runtime["last_publish_error"] == "redis disconnected"


def test_library_index_mutation_hint_uses_real_namespaced_stream(monkeypatch):
    calls = []

    class FakeClient:
        def xadd(self, key, fields, maxlen=None, approximate=True):
            calls.append((key, fields, maxlen, approximate))
            return b"12-0"

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: _library_index_redis_config(),
    )
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: FakeClient())

    result = service.publish_library_index_mutation_hint_sync("library-a", 9, "operation-1")

    assert result == "12-0"
    assert calls == [(
        "kikoerumanager:test:library-index-mutation-stream",
        {"payload": '{"library_id":"library-a","accepted_seq":9,"operation_id":"operation-1"}'},
        200,
        True,
    )]
    runtime = service.library_index_channel_diagnostics_sync()["runtime"]
    assert runtime["published"] == 1
    assert runtime["publish_failures"] == 0


def test_library_index_consumer_group_accepts_existing_group(monkeypatch):
    class FakeClient:
        def xgroup_create(self, key, group, id=None, mkstream=False):
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: _library_index_redis_config(),
    )
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: FakeClient())

    assert service.ensure_consumer_group_sync(
        "library-index:mutation:stream",
        "library-index-materializers",
    ) is True


def test_library_index_consumer_group_reclaims_reads_and_acks(monkeypatch):
    calls = []

    class FakeClient:
        def xgroup_create(self, key, group, id=None, mkstream=False):
            calls.append(("xgroup_create", key, group, id, mkstream))

        def xautoclaim(self, key, group, consumer, idle_ms, start_id=None, count=None):
            calls.append(("xautoclaim", key, group, consumer, idle_ms, start_id, count))
            return (
                b"18-0",
                [(b"11-0", {b"payload": b'{"library_id":"library-a","accepted_seq":3}'})],
                [],
            )

        def xreadgroup(self, group, consumer, streams, **kwargs):
            calls.append(("xreadgroup", group, consumer, streams, kwargs))
            return [(
                b"ignored-stream",
                [(b"12-0", {b"library_id": b"library-b", b"accepted_seq": b"4"})],
            )]

        def xack(self, key, group, *ids):
            calls.append(("xack", key, group, ids))
            return len(ids)

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: _library_index_redis_config(),
    )
    client = FakeClient()
    service = RedisService()
    monkeypatch.setattr(service, "client", lambda required=False: client)

    cursor, rows = service.read_library_index_mutation_hints_sync(
        "worker-1",
        count=5,
        block_ms=999,
        reclaim_idle_ms=60000,
        reclaim_cursor="7-0",
    )
    acked = service.ack_library_index_mutation_hints_sync([row[0] for row in rows])

    stream_key = "kikoerumanager:test:library-index-mutation-stream"
    assert cursor == "18-0"
    assert rows == [
        ("11-0", {"library_id": "library-a", "accepted_seq": 3}),
        ("12-0", {"library_id": "library-b", "accepted_seq": "4"}),
    ]
    assert calls[0] == (
        "xgroup_create",
        stream_key,
        "library-index-materializers",
        "0-0",
        True,
    )
    assert calls[1] == (
        "xautoclaim",
        stream_key,
        "library-index-materializers",
        "worker-1",
        60000,
        "7-0",
        5,
    )
    assert calls[2] == (
        "xreadgroup",
        "library-index-materializers",
        "worker-1",
        {stream_key: ">"},
        {"count": 4},
    )
    assert calls[3] == (
        "xack",
        stream_key,
        "library-index-materializers",
        ("11-0", "12-0"),
    )
    assert acked == 2


def test_library_index_hint_ack_requires_pg_watermark_or_persisted_retry(monkeypatch):
    acked_ids = []
    service = RedisService()
    monkeypatch.setattr(
        service,
        "ack_library_index_mutation_hints_sync",
        lambda message_ids: acked_ids.extend(message_ids) or len(message_ids),
    )

    result = service.ack_durable_library_index_mutation_hints_sync(
        [
            ("1-0", {"library_id": "library-a", "accepted_seq": 3, "operation_id": "op-1"}),
            ("2-0", {"library_id": "library-a", "accepted_seq": 4, "operation_id": "op-2"}),
            ("3-0", {"library_id": "library-b", "accepted_seq": 7, "operation_id": "op-3"}),
            ("4-0", {"library_id": "library-b", "accepted_seq": 8, "operation_id": "op-4"}),
            ("5-0", {"accepted_seq": "bad"}),
        ],
        materialized_seq_by_library={"library-a": 3, "library-b": 6},
        retry_persisted_seqs=[("library-b", 7)],
    )

    assert acked_ids == ["1-0", "3-0", "5-0"]
    assert result == {
        "ack_requested": 3,
        "acked": 3,
        "ack_message_ids": ["1-0", "3-0", "5-0"],
        "deferred_message_ids": ["2-0", "4-0"],
        "invalid_message_ids": ["5-0"],
    }
    runtime = service.library_index_channel_diagnostics_sync()["runtime"]
    assert runtime["consumer_reads"] == 5
    assert runtime["consumer_acks"] == 3
    assert runtime["consumer_deferred"] == 2
    assert runtime["consumer_invalid"] == 1


def test_library_index_materializer_uses_durable_ack_contract(monkeypatch):
    service = LibraryIndexMutationService()
    hint = (
        "1-0",
        {"library_id": "library-a", "accepted_seq": 3, "operation_id": "operation-1"},
    )
    calls = []

    class FakeRedis:
        def read_library_index_mutation_hints_sync(self, *args, **kwargs):
            calls.append(("read", args, kwargs))
            return "2-0", [hint]

        def ack_durable_library_index_mutation_hints_sync(self, hints, **kwargs):
            calls.append(("durable_ack", hints, kwargs))
            service._stop_event.set()
            return {"acked": 1}

        def ack_library_index_mutation_hints_sync(self, _message_ids):
            raise AssertionError("materializer 不得绕过 PostgreSQL 水位直接 ACK")

    fake_redis = FakeRedis()
    monkeypatch.setattr(mutation_module, "get_redis_service", lambda: fake_redis)
    monkeypatch.setattr(service, "_recover_prepared", lambda: None)
    monkeypatch.setattr(service, "_pending_library_ids", lambda: ["library-a"])
    process_results = iter([True, False])
    monkeypatch.setattr(service, "_process_next", lambda _library_id: next(process_results))
    monkeypatch.setattr(
        service,
        "_hint_ack_state",
        lambda _hints: ({"library-a": 3}, {("library-b", 7)}),
    )

    service._run()

    assert service._reclaim_cursor == "2-0"
    assert calls[-1] == (
        "durable_ack",
        [hint],
        {
            "materialized_seq_by_library": {"library-a": 3},
            "retry_persisted_seqs": {("library-b", 7)},
        },
    )


def test_library_index_recovery_effects_reconcile_source_and_target():
    effects = LibraryIndexMutationService._recovery_effects([
        {
            "library_id": "library-a",
            "kind": "move",
            "relative_path": r"old\folder",
            "scope": "subtree",
            "target_library_id": "library-b",
            "target_path": "new/folder",
        },
        {
            "library_id": "library-a",
            "kind": "delete",
            "relative_path": "old/folder",
            "scope": "exact",
        },
    ])

    assert effects == {
        "library-a": [{
            "kind": "reconcile",
            "relative_path": "old/folder",
            "scope": "subtree",
        }],
        "library-b": [{
            "kind": "reconcile",
            "relative_path": "new/folder",
            "scope": "subtree",
        }],
    }


def test_library_index_recovery_drains_more_than_one_batch(monkeypatch):
    service = LibraryIndexMutationService()
    candidates = [
        {
            "operation_id": f"operation-{index}",
            "state": "prepared",
            "planned_scopes": [{
                "library_id": "library-a",
                "relative_path": f"folder-{index}",
                "scope": "subtree",
            }],
        }
        for index in range(205)
    ]
    recovered = []

    def load_candidates(_recovery_now, failed, active):
        excluded = failed | active
        remaining = [row for row in candidates if row["operation_id"] not in excluded and row["operation_id"] not in recovered]
        return remaining[:mutation_module.RECOVERY_BATCH_SIZE]

    monkeypatch.setattr(service, "_load_recovery_candidates", load_candidates)
    monkeypatch.setattr(service, "_recover_candidate", lambda candidate: recovered.append(candidate["operation_id"]))

    service._recover_prepared()

    assert recovered == [f"operation-{index}" for index in range(205)]


def test_library_index_recovery_isolates_failed_operation_and_continues(monkeypatch):
    service = LibraryIndexMutationService()
    candidates = [
        {"operation_id": "broken", "state": "prepared", "planned_scopes": []},
        {"operation_id": "healthy", "state": "reconcile_required", "planned_scopes": []},
    ]
    recovered = []

    def load_candidates(_recovery_now, failed, active):
        excluded = failed | active
        return [row for row in candidates if row["operation_id"] not in excluded and row["operation_id"] not in recovered]

    def recover(candidate):
        if candidate["operation_id"] == "broken":
            raise RuntimeError("broken operation")
        recovered.append(candidate["operation_id"])

    monkeypatch.setattr(service, "_load_recovery_candidates", load_candidates)
    monkeypatch.setattr(service, "_recover_candidate", recover)

    service._recover_prepared()

    assert recovered == ["healthy"]


def test_library_index_reconcile_required_is_not_hidden_by_active_prepared(monkeypatch):
    from sqlalchemy.dialects import postgresql

    service = LibraryIndexMutationService()
    conditions = []

    class FakeQuery:
        def filter(self, *args):
            conditions.extend(args)
            return self

        def order_by(self, *args):
            return self

        def limit(self, _limit):
            return self

        def all(self):
            return []

    class FakeSession:
        def query(self, _model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(mutation_module, "SessionLocal", FakeSession)

    service._load_recovery_candidates(
        mutation_module.get_local_now(),
        {"failed-operation"},
        {"active-prepared-operation"},
    )

    sql = " ".join(
        str(condition.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        for condition in conditions
    )
    assert "reconcile_required" in sql
    assert "updated_at" in sql
    assert "active-prepared-operation" in sql


def test_library_index_watcher_writes_hot_dirty_and_clears_after_ledger(monkeypatch, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    changed = root / "folder" / "file.txt"
    calls = []

    class FakeRedis:
        def upsert_library_index_dirty_paths_sync(self, library_id, paths, **kwargs):
            calls.append(("upsert", library_id, list(paths), kwargs))
            return len(list(paths))

        def remove_library_index_dirty_paths_sync(self, library_id, paths, **kwargs):
            calls.append(("remove", library_id, list(paths), kwargs))
            return len(list(paths))

    class FakeMutationService:
        def should_suppress_watcher(self, _library_id, _relative_path):
            return False

        def prepare(self, **kwargs):
            calls.append(("prepare", kwargs))
            return SimpleNamespace(operation_id="watcher-operation")

        def mark_filesystem_started(self, operation_id):
            calls.append(("filesystem_started", operation_id))
            return {"operation_id": operation_id}

        def finalize(self, operation_id, **kwargs):
            calls.append(("finalize", operation_id, kwargs))
            return {"operation_id": operation_id}

    fake_redis = FakeRedis()
    fake_mutation = FakeMutationService()
    monkeypatch.setattr(watcher_module, "get_redis_service", lambda: fake_redis)
    monkeypatch.setattr(watcher_module, "get_library_index_mutation_service", lambda: fake_mutation)
    driver = LibraryIndexWatcherDriver()
    driver._roots["library-a"] = str(root)

    driver.mark_dirty("library-a", str(root), str(changed))
    with driver._lock:
        for row in driver._dirty["library-a"].values():
            row.last_at -= watcher_module.QUIET_SECONDS + 1
    due = driver._take_due()
    driver._dispatch("library-a", due["library-a"])

    assert calls[0][0:3] == ("upsert", "library-a", ["folder/file.txt"])
    assert calls.index(("filesystem_started", "watcher-operation")) < next(
        index for index, call in enumerate(calls) if call[0] == "finalize"
    )
    assert calls[-1][0:3] == ("remove", "library-a", ["folder/file.txt"])
    assert calls[-1][3]["include_descendants"] is True
    assert isinstance(calls[-1][3]["max_score_ms"], float)
    assert driver.diagnostics()["dirty_paths"] == {}
    assert driver.diagnostics()["dispatched_count"] == 1


def test_library_index_watcher_keeps_memory_dirty_when_redis_or_ledger_fails(monkeypatch, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    changed = root / "file.txt"

    class BrokenRedis:
        def upsert_library_index_dirty_paths_sync(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    class BrokenMutationService:
        def should_suppress_watcher(self, _library_id, _relative_path):
            return False

        def prepare(self, **_kwargs):
            raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(watcher_module, "get_redis_service", lambda: BrokenRedis())
    monkeypatch.setattr(watcher_module, "get_library_index_mutation_service", lambda: BrokenMutationService())
    driver = LibraryIndexWatcherDriver()
    driver._roots["library-a"] = str(root)

    driver.mark_dirty("library-a", str(root), str(changed))
    with driver._lock:
        for row in driver._dirty["library-a"].values():
            row.last_at -= watcher_module.QUIET_SECONDS + 1
    due = driver._take_due()["library-a"]
    try:
        driver._dispatch("library-a", due)
    except RuntimeError:
        driver._requeue("library-a", due)

    assert driver.diagnostics()["dirty_paths"] == {"library-a": 1}


def test_library_index_watcher_degrades_cleanly_when_inotify_limit_is_reached(monkeypatch, tmp_path):
    first_root = tmp_path / "library-a"
    second_root = tmp_path / "library-b"
    first_root.mkdir()
    second_root.mkdir()
    observers = []

    class FakeManager:
        def list_libraries(self):
            return [
                {"id": "library-a", "type": "local", "root_path": str(first_root)},
                {"id": "library-b", "type": "local", "root_path": str(second_root)},
            ]

    class FakeRedis:
        def read_library_index_dirty_paths_sync(self, _library_id):
            return []

    class CapacityLimitedObserver:
        def __init__(self):
            self.stopped = False
            self.joined = False
            observers.append(self)

        def schedule(self, *_args, **_kwargs):
            return None

        def start(self):
            if len(observers) == 2:
                raise OSError(errno.ENOSPC, "inotify watch limit reached")

        def stop(self):
            self.stopped = True

        def join(self, **_kwargs):
            self.joined = True

    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: FakeManager())
    monkeypatch.setattr(watcher_module, "get_redis_service", lambda: FakeRedis())
    monkeypatch.setattr(watcher_module, "Observer", CapacityLimitedObserver)
    monkeypatch.setattr(
        watcher_module,
        "_read_inotify_limits",
        lambda: {"max_user_watches": 8192, "max_user_instances": 128},
    )

    driver = LibraryIndexWatcherDriver()
    try:
        driver.start()
        diagnostics = driver.diagnostics()

        assert diagnostics["running"] is True
        assert diagnostics["watcher_mode"] == "inotify_limit"
        assert diagnostics["live_events_available"] is False
        assert diagnostics["scrub_fallback_running"] is True
        assert diagnostics["start_errno"] == errno.ENOSPC
        assert diagnostics["inotify_limits"] == {
            "max_user_watches": 8192,
            "max_user_instances": 128,
        }
        assert diagnostics["observed_libraries"] == ["library-a", "library-b"]
        assert len(observers) == 2
        assert all(observer.stopped for observer in observers)
        assert all(observer.joined for observer in observers)
    finally:
        driver.stop(timeout=0.5)


def test_library_index_dirty_zset_and_channel_diagnostics(monkeypatch):
    zsets = {}
    eval_calls = []

    class FakeClient:
        def zadd(self, key, mapping):
            zsets.setdefault(key, {}).update(mapping)
            return len(mapping)

        def zpopmin(self, key, count):
            values = sorted(zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))[:count]
            for member, _score in values:
                zsets[key].pop(member, None)
            return [(member.encode(), score) for member, score in values]

        def eval(self, script, numkeys, key, roots_json, max_score):
            import json

            eval_calls.append((script, numkeys, key, roots_json, max_score))
            roots = json.loads(roots_json)
            cutoff = float(max_score) if max_score != "" else None
            removed = 0
            for member, score in list(zsets.get(key, {}).items()):
                if not any(
                    root == "/" or member == root or member.startswith(root + "/")
                    for root in roots
                ):
                    continue
                if cutoff is not None and score > cutoff:
                    continue
                zsets[key].pop(member, None)
                removed += 1
            return removed

        def zcard(self, key):
            return len(zsets.get(key, {}))

        def zrange(self, key, start, end, withscores=False):
            values = sorted(zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))
            selected = values[start:] if end == -1 else values[start:end + 1]
            return selected if withscores else [member for member, _score in selected]

        def zrevrange(self, key, start, end, withscores=False):
            values = sorted(zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]), reverse=True)
            selected = values[start:] if end == -1 else values[start:end + 1]
            return selected if withscores else [member for member, _score in selected]

        def scan_iter(self, match=None, count=None):
            prefix = str(match or "").rstrip("*")
            return iter([key.encode() for key in zsets if key.startswith(prefix)])

        def xlen(self, key):
            return 7

        def xpending(self, key, group):
            return {
                b"pending": 2,
                b"min": b"4-0",
                b"max": b"6-0",
                b"consumers": [{b"name": b"worker-1", b"pending": 2}],
            }

        def xinfo_groups(self, key):
            return [{
                b"name": b"library-index-materializers",
                b"consumers": 1,
                b"pending": 2,
                b"last-delivered-id": b"6-0",
                b"entries-read": 6,
                b"lag": 1,
            }]

    monkeypatch.setattr(
        "app.config.settings.get_config",
        lambda: _library_index_redis_config(),
    )
    service = RedisService()
    client = FakeClient()
    monkeypatch.setattr(service, "client", lambda required=False: client)

    written = service.upsert_library_index_dirty_paths_sync(
        "library-a",
        [r"circle\RJ001", "circle/RJ001/", "circle/RJ002"],
        score_ms=1000,
    )
    popped = service.pop_library_index_dirty_paths_sync("library-a", count=1)
    diagnostics = service.library_index_channel_diagnostics_sync()

    assert written == 2
    assert popped == [("circle/RJ001", 1000.0)]
    assert diagnostics["available"] is True
    assert diagnostics["stream"] == {
        "name": "library-index:mutation:stream",
        "key": "kikoerumanager:test:library-index-mutation-stream",
        "group": "library-index-materializers",
        "group_state": {
            "exists": True,
            "consumers": 1,
            "pending": 2,
            "last_delivered_id": "6-0",
            "entries_read": 6,
            "lag": 1,
        },
        "length": 7,
        "pending": 2,
        "pel": {
            "pending": 2,
            "min_id": "4-0",
            "max_id": "6-0",
            "consumers": [{"name": "worker-1", "pending": 2}],
        },
    }
    assert diagnostics["dirty"] == {
        "queue_count": 1,
        "pending_paths": 1,
        "oldest_score_ms": 1000.0,
        "queues": [{
            "library_id": "library-a",
            "pending_paths": 1,
            "oldest_score_ms": 1000.0,
        }],
    }

    service.upsert_library_index_dirty_paths_sync(
        "library-a",
        ["folder", "folder/old.txt"],
        score_ms=2000,
    )
    service.upsert_library_index_dirty_paths_sync(
        "library-a",
        ["folder/new.txt"],
        score_ms=4000,
    )
    removed = service.remove_library_index_dirty_paths_sync(
        "library-a",
        ["folder"],
        max_score_ms=3000,
    )
    remaining = service.read_library_index_dirty_paths_sync("library-a")

    assert removed == 2
    assert remaining == [("circle/RJ002", 1000.0), ("folder/new.txt", 4000.0)]
    assert eval_calls[-1][1:] == (
        1,
        "kikoerumanager:test:library-index:watcher-dirty:library-a",
        '["folder"]',
        3000.0,
    )
