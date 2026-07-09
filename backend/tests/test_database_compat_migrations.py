import pytest

from app.models import database


def test_compat_schema_probe_includes_library_owned_works(monkeypatch):
    probed = {}
    received = {}

    def fake_existing_tables(_conn, table_names):
        names = tuple(table_names)
        probed["names"] = names
        return set(names)

    def fake_migrate_library_owned_works_schema(_conn, existing_tables=None):
        received["existing_tables"] = set(existing_tables or ())

    monkeypatch.setattr(database, "_existing_tables", fake_existing_tables)
    monkeypatch.setattr(database, "_load_index_definitions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(database, "_ensure_indexes_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_existing_columns", lambda *_args, **_kwargs: set(_args[2] or ()))
    monkeypatch.setattr(database, "_migrate_library_index_entries_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_status_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", fake_migrate_library_owned_works_schema)
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(object())

    assert "library_owned_works" in probed["names"]
    assert "library_owned_works" in received["existing_tables"]


def test_compat_schema_probe_includes_bonus_probe_cache(monkeypatch):
    probed = {}
    received = {}

    def fake_existing_tables(_conn, table_names):
        names = tuple(table_names)
        probed["names"] = names
        return set(names)

    def fake_migrate_bonus_probe_cache(_conn, existing_tables=None):
        received["existing_tables"] = set(existing_tables or ())

    monkeypatch.setattr(database, "_existing_tables", fake_existing_tables)
    monkeypatch.setattr(database, "_load_index_definitions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(database, "_ensure_indexes_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_existing_columns", lambda *_args, **_kwargs: set(_args[2] or ()))
    monkeypatch.setattr(database, "_migrate_library_index_entries_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_status_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", fake_migrate_bonus_probe_cache)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(object())

    assert "dlsite_bonus_probe_cache" in probed["names"]
    assert "dlsite_bonus_probe_cache" in received["existing_tables"]


def test_migrate_bonus_probe_cache_promotes_int4_columns(monkeypatch):
    executed = []

    class FakeConn:
        def execute(self, stmt, *_args, **_kwargs):
            sql = str(stmt)
            executed.append(sql)
            if "ALTER COLUMN price TYPE BIGINT" in sql:
                column_types["price"] = "int8"
            if "ALTER COLUMN wishlist_count TYPE BIGINT" in sql:
                column_types["wishlist_count"] = "int8"

    column_types = {"price": "int4", "wishlist_count": "int4"}

    def fake_column_udt_name(_conn, _table_name, column_name):
        return column_types[column_name]

    monkeypatch.setattr(database, "_column_udt_name", fake_column_udt_name)

    database._migrate_dlsite_bonus_probe_cache_schema(FakeConn(), {"dlsite_bonus_probe_cache"})

    assert any("ALTER COLUMN price TYPE BIGINT" in sql for sql in executed)
    assert any("ALTER COLUMN wishlist_count TYPE BIGINT" in sql for sql in executed)
    assert column_types == {"price": "int8", "wishlist_count": "int8"}


def test_migrate_bonus_probe_cache_raises_when_type_stays_int4(monkeypatch):
    class FakeConn:
        def execute(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(database, "_column_udt_name", lambda *_args, **_kwargs: "int4")

    with pytest.raises(RuntimeError, match="dlsite_bonus_probe_cache.price"):
        database._migrate_dlsite_bonus_probe_cache_schema(FakeConn(), {"dlsite_bonus_probe_cache"})


def test_migrate_bonus_probe_cache_skips_existing_bigint(monkeypatch):
    executed = []

    class FakeConn:
        def execute(self, stmt, *_args, **_kwargs):
            executed.append(str(stmt))

    monkeypatch.setattr(database, "_column_udt_name", lambda *_args, **_kwargs: "int8")

    database._migrate_dlsite_bonus_probe_cache_schema(FakeConn(), {"dlsite_bonus_probe_cache"})

    assert executed == []


def test_init_db_does_not_mark_done_when_migration_fails(monkeypatch):
    monkeypatch.setattr(database, "_init_db_done", False)
    monkeypatch.setitem(database._DB_RUNTIME_CONFIG, "startup_health_check", False)
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda **_kwargs: None)
    monkeypatch.setattr(database, "schedule_library_index_postgres_index_maintenance", lambda: None)

    class FakeBegin:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(database, "engine", FakeEngine())
    monkeypatch.setattr(database, "_create_postgres_extensions_and_indexes", lambda _conn: None)

    def raise_migration_error(_conn):
        raise RuntimeError("schema drift")

    monkeypatch.setattr(database, "_migrate_compat_schema", raise_migration_error)

    with pytest.raises(RuntimeError, match="schema drift"):
        database.init_db()

    assert database._init_db_done is False
