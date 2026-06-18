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

    database._migrate_compat_schema(object())

    assert "library_owned_works" in probed["names"]
    assert "library_owned_works" in received["existing_tables"]
