from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.models import database


class _CompatProbeConnection:
    def execute(self, *_args, **_kwargs):
        return None


@pytest.fixture
def alembic_test_database(db_engine, monkeypatch):
    database_name = f"kikoerumanager_alembic_{uuid4().hex[:12]}_test"
    maintenance_url = db_engine.url.set(database="postgres")
    target_url = db_engine.url.set(database=database_name)
    admin_engine = create_engine(
        maintenance_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{database_name}" TEMPLATE template0'))

    target_engine = create_engine(target_url, pool_pre_ping=True)
    backend_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(backend_root / "alembic"))
    monkeypatch.setenv(
        "DATABASE_URL",
        target_url.render_as_string(hide_password=False),
    )
    try:
        yield target_engine, alembic_config
    finally:
        target_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text("""
                    SELECT pg_terminate_backend(pid)
                      FROM pg_stat_activity
                     WHERE datname = :database_name
                       AND pid <> pg_backend_pid()
                """),
                {"database_name": database_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


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
    monkeypatch.setattr(database, "_migrate_library_index_consistency_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", fake_migrate_library_owned_works_schema)
    monkeypatch.setattr(database, "_migrate_work_canonical_links_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(_CompatProbeConnection())

    assert "library_owned_works" in probed["names"]
    assert "library_owned_works" in received["existing_tables"]


def test_compat_schema_probe_includes_work_canonical_links(monkeypatch):
    probed = {}
    received = {}

    def fake_existing_tables(_conn, table_names):
        names = tuple(table_names)
        probed["names"] = names
        return set(names)

    def fake_migrate_work_canonical_links_schema(_conn, existing_tables=None):
        received["existing_tables"] = set(existing_tables or ())

    monkeypatch.setattr(database, "_existing_tables", fake_existing_tables)
    monkeypatch.setattr(database, "_load_index_definitions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(database, "_ensure_indexes_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_existing_columns", lambda *_args, **_kwargs: set(_args[2] or ()))
    monkeypatch.setattr(database, "_migrate_library_index_entries_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_status_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_consistency_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        database,
        "_migrate_work_canonical_links_schema",
        fake_migrate_work_canonical_links_schema,
    )
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(_CompatProbeConnection())

    assert "work_canonical_links" in probed["names"]
    assert "work_canonical_links" in received["existing_tables"]


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
    monkeypatch.setattr(database, "_migrate_library_index_consistency_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_work_canonical_links_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", fake_migrate_bonus_probe_cache)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(_CompatProbeConnection())

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


def test_library_index_consistency_models_use_generation_constraint():
    entry_table = database.LibraryIndexEntry.__table__
    operation_table = database.LibraryIndexMutationOperation.__table__
    ledger_table = database.LibraryIndexMutationLedger.__table__
    effect_table = database.LibraryIndexMutationEffect.__table__
    mask_table = database.LibraryIndexPendingMask.__table__
    generation_table = database.LibraryIndexGeneration.__table__

    assert {"generation", "materialized_seq"} <= set(entry_table.columns.keys())
    assert {index.name for index in entry_table.indexes} == {
        "idx_lie_library_generation_rel",
    }
    assert operation_table.c.request_fingerprint.nullable is False
    assert operation_table.c.idempotency_key.type.length == 255
    assert "idx_li_mutation_operations_idempotency" in {index.name for index in operation_table.indexes}
    assert "idx_li_mutation_ledger_library_seq" in {index.name for index in ledger_table.indexes}
    assert "idx_li_mutation_ledger_operation_library" in {index.name for index in ledger_table.indexes}
    assert "idx_li_mutation_effects_ledger_no" in {index.name for index in effect_table.indexes}
    assert "idx_li_pending_masks_active_path" in {index.name for index in mask_table.indexes}
    assert "idx_li_generations_library_generation" in {index.name for index in generation_table.indexes}

    operation_foreign_keys = {str(foreign_key.column) for foreign_key in ledger_table.foreign_keys}
    effect_foreign_keys = {str(foreign_key.column) for foreign_key in effect_table.foreign_keys}
    mask_foreign_keys = {str(foreign_key.column) for foreign_key in mask_table.foreign_keys}
    assert "library_index_mutation_operations.operation_id" in operation_foreign_keys
    assert "library_index_mutation_ledger.id" in effect_foreign_keys
    assert "library_index_mutation_operations.operation_id" in mask_foreign_keys


def test_library_index_status_to_dict_exposes_consistent_watermarks():
    status = database.LibraryIndexStatus(
        library_id="local-main",
        status="catching_up",
        accepted_seq=12,
        materialized_seq=9,
        state_revision=7,
        view_revision=11,
        active_generation=1,
        building_generation=2,
        catchup_state="running",
        materializer_epoch=4,
        updated_at=123,
    )

    payload = status.to_dict()

    assert payload["accepted_seq"] == 12
    assert payload["materialized_seq"] == 9
    assert payload["pending_events"] == 3
    assert payload["state_revision"] == 7
    assert payload["view_revision"] == 11
    assert payload["active_generation"] == 1
    assert payload["building_generation"] == 2
    assert payload["materializer_epoch"] == 4


def test_unique_library_index_is_created_concurrently():
    sql = database._concurrent_create_index_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_example ON library_index_entries(library_id)"
    )

    assert sql.startswith("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ")


def test_compat_status_schema_adds_materializer_watermarks(monkeypatch):
    executed = []
    added = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeConn:
        def execute(self, stmt, *_args, **_kwargs):
            executed.append(str(stmt))
            return FakeResult()

    def fake_add_column(
        _conn,
        table_name,
        column_name,
        column_type,
        default_sql=None,
        existing_columns=None,
    ):
        added.append((table_name, column_name, column_type, default_sql))
        if existing_columns is not None:
            existing_columns.add(column_name)
        return True

    monkeypatch.setattr(database, "_existing_columns", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(database, "_add_column_if_missing", fake_add_column)

    database._migrate_library_index_status_schema(FakeConn(), {"library_index_status"})

    names = {column_name for _table, column_name, _type, _default in added}
    assert {
        "accepted_seq",
        "materialized_seq",
        "state_revision",
        "view_revision",
        "active_generation",
        "building_generation",
        "materializer_owner",
        "materializer_lease_until",
        "materializer_epoch",
        "blocked_seq",
        "catchup_error",
    } <= names
    assert any("ALTER COLUMN accepted_seq SET NOT NULL" in sql for sql in executed)


def test_compat_schema_runs_library_index_consistency_upgrade(monkeypatch):
    called = []

    monkeypatch.setattr(database, "_existing_tables", lambda _conn, table_names: set(table_names))
    monkeypatch.setattr(database, "_load_index_definitions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(database, "_ensure_indexes_exist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_existing_columns", lambda *_args, **_kwargs: set(_args[2] or ()))
    monkeypatch.setattr(database, "_migrate_library_index_entries_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_status_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_library_index_consistency_tables", lambda *_args, **_kwargs: called.append(True))
    monkeypatch.setattr(database, "_migrate_library_owned_works_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_work_canonical_links_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_logs_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_activity_log_daily_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_dlsite_bonus_probe_cache_schema", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "_migrate_notification_inbox_items_schema", lambda *_args, **_kwargs: None)

    database._migrate_compat_schema(_CompatProbeConnection())

    assert called == [True]


def test_library_index_consistency_schema_is_created_in_postgresql(db_engine):
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    expected_tables = {
        "library_index_mutation_operations",
        "library_index_mutation_ledger",
        "library_index_mutation_effects",
        "library_index_pending_masks",
        "library_index_generations",
    }
    assert expected_tables <= tables

    entry_columns = {column["name"] for column in inspector.get_columns("library_index_entries")}
    status_columns = {column["name"] for column in inspector.get_columns("library_index_status")}
    assert {"generation", "materialized_seq"} <= entry_columns
    assert {
        "accepted_seq",
        "materialized_seq",
        "state_revision",
        "view_revision",
        "active_generation",
        "building_generation",
        "materializer_owner",
        "materializer_lease_until",
        "materializer_epoch",
        "blocked_seq",
        "catchup_error",
    } <= status_columns

    entry_indexes = {index["name"] for index in inspector.get_indexes("library_index_entries")}
    ledger_indexes = {index["name"] for index in inspector.get_indexes("library_index_mutation_ledger")}
    effect_indexes = {index["name"] for index in inspector.get_indexes("library_index_mutation_effects")}
    mask_indexes = {index["name"] for index in inspector.get_indexes("library_index_pending_masks")}
    assert "idx_lie_library_generation_rel" in entry_indexes
    assert "idx_lie_library_rel" not in entry_indexes
    assert {
        "idx_li_mutation_ledger_library_seq",
        "idx_li_mutation_ledger_operation_library",
    } <= ledger_indexes
    assert "idx_li_mutation_effects_ledger_no" in effect_indexes
    assert "idx_li_pending_masks_active_path" in mask_indexes


def test_library_index_consistency_upgrade_backfills_legacy_library_view(db_engine):
    library_id = "legacy-consistency-library"
    with db_engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM library_index_entries WHERE library_id = :library_id"
        ), {"library_id": library_id})
        conn.execute(text(
            "DELETE FROM library_index_generations WHERE library_id = :library_id"
        ), {"library_id": library_id})
        conn.execute(text(
            "DELETE FROM library_index_status WHERE library_id = :library_id"
        ), {"library_id": library_id})
        conn.execute(text("""
            INSERT INTO library_index_entries(
                library_id,
                generation,
                materialized_seq,
                entry_type,
                relative_path,
                absolute_path,
                name,
                name_sort_key,
                size,
                file_count,
                depth,
                indexed_at
            ) VALUES (
                :library_id,
                1,
                0,
                'dir',
                'RJ00000001',
                'X:/RJ00000001',
                'RJ00000001',
                'rj00000001',
                0,
                0,
                1,
                1
            )
        """), {"library_id": library_id})

        database._migrate_library_index_consistency_tables(conn)

        row = conn.execute(text("""
            SELECT status.active_generation,
                   status.materialized_seq,
                   generation.state
              FROM library_index_status AS status
              JOIN library_index_generations AS generation
                ON generation.library_id = status.library_id
               AND generation.generation = status.active_generation
             WHERE status.library_id = :library_id
        """), {"library_id": library_id}).one()

        assert tuple(row) == (1, 0, "active")


def test_generation_contract_rejects_renamed_legacy_unique_index(db_engine):
    legacy_index_name = "idx_lie_renamed_legacy_contract_probe"
    try:
        with db_engine.begin() as conn:
            conn.execute(text(
                f"CREATE UNIQUE INDEX {legacy_index_name} "
                "ON library_index_entries(library_id, relative_path)"
            ))

        with db_engine.connect() as conn:
            status = database.library_index_generation_contract_status(conn)
            assert status["ready"] is False
            assert status["legacy_unique_indexes"] == [legacy_index_name]
            with pytest.raises(RuntimeError, match=legacy_index_name):
                database.require_library_index_generation_contract_ready(conn)
    finally:
        with db_engine.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {legacy_index_name}"))

    with db_engine.connect() as conn:
        status = database.library_index_generation_contract_status(conn)
        assert status["ready"] is True
        assert status["legacy_unique_indexes"] == []


def test_init_db_contract_gate_uses_database_and_keeps_retryable_state(
    db_engine,
    monkeypatch,
):
    legacy_index_name = "idx_lie_init_db_legacy_contract_probe"
    with db_engine.begin() as conn:
        conn.execute(text(
            f"CREATE UNIQUE INDEX {legacy_index_name} "
            "ON library_index_entries(library_id, relative_path)"
        ))

    monkeypatch.setattr(database, "_init_db_done", False)
    monkeypatch.setattr(database, "engine", db_engine)
    monkeypatch.setitem(database._DB_RUNTIME_CONFIG, "startup_health_check", False)
    monkeypatch.setenv(database._LIBRARY_INDEX_GENERATION_CONTRACT_ENV, "1")
    monkeypatch.setattr(
        database,
        "schedule_library_index_postgres_index_maintenance",
        lambda: None,
    )
    try:
        with pytest.raises(RuntimeError, match=legacy_index_name):
            database.init_db()
        assert database._init_db_done is False
    finally:
        with db_engine.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {legacy_index_name}"))


def test_alembic_library_index_expand_and_guarded_downgrade(
    alembic_test_database,
):
    target_engine, alembic_config = alembic_test_database
    previous_revision = "20260709_0001_bonus_probe_mode_width"
    command.upgrade(alembic_config, previous_revision)

    with target_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS library_index_pending_masks CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS library_index_mutation_effects CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS library_index_mutation_ledger CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS library_index_mutation_operations CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS library_index_generations CASCADE"))
        conn.execute(text("DROP INDEX IF EXISTS idx_lie_library_generation_rel"))
        conn.execute(text("ALTER TABLE library_index_entries DROP COLUMN materialized_seq"))
        conn.execute(text("ALTER TABLE library_index_entries DROP COLUMN generation"))
        for column_name in (
            "catchup_error",
            "blocked_seq",
            "materializer_epoch",
            "materializer_lease_until",
            "materializer_owner",
            "last_operation_id",
            "catchup_state",
            "building_generation",
            "active_generation",
            "view_revision",
            "state_revision",
            "materialized_seq",
            "accepted_seq",
        ):
            conn.execute(text(
                f"ALTER TABLE library_index_status DROP COLUMN IF EXISTS {column_name}"
            ))
        conn.execute(text(
            "CREATE UNIQUE INDEX idx_lie_library_rel "
            "ON library_index_entries(library_id, relative_path)"
        ))
        conn.execute(text("""
            CREATE TABLE library_index_mutation_operations (
                operation_id VARCHAR(36) PRIMARY KEY,
                idempotency_key VARCHAR(255) NOT NULL,
                request_fingerprint VARCHAR(128) NOT NULL,
                kind VARCHAR(40) NOT NULL,
                state VARCHAR(32) NOT NULL DEFAULT 'prepared',
                planned_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
                actual_result JSONB NOT NULL DEFAULT '{}'::jsonb,
                error TEXT,
                prepared_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finalized_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            INSERT INTO library_index_entries(
                library_id,
                entry_type,
                relative_path,
                absolute_path,
                name,
                name_sort_key,
                size,
                file_count,
                depth,
                indexed_at
            ) VALUES (
                'legacy-alembic-library',
                'dir',
                'RJ00000002',
                'X:/RJ00000002',
                'RJ00000002',
                'rj00000002',
                0,
                0,
                1,
                1
            )
        """))

    command.upgrade(alembic_config, "head")

    inspector = inspect(target_engine)
    entry_columns = {
        column["name"]: column
        for column in inspector.get_columns("library_index_entries")
    }
    operation_columns = {
        column["name"]
        for column in inspector.get_columns("library_index_mutation_operations")
    }
    assert entry_columns["generation"]["nullable"] is False
    assert entry_columns["materialized_seq"]["nullable"] is False
    assert "filesystem_started_at" in operation_columns

    with target_engine.connect() as conn:
        entry = conn.execute(text("""
            SELECT generation, materialized_seq
              FROM library_index_entries
             WHERE library_id = 'legacy-alembic-library'
        """)).one()
        assert tuple(entry) == (1, 0)
        defaults = dict(conn.execute(text("""
            SELECT column_name, column_default
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'library_index_entries'
               AND column_name IN ('generation', 'materialized_seq')
        """)).all())
        assert defaults == {"generation": "1", "materialized_seq": "0"}

        status = database.library_index_generation_contract_status(conn)
        assert status["ready"] is False
        assert status["legacy_unique_indexes"] == ["idx_lie_library_rel"]

    with target_engine.begin() as conn:
        conn.execute(text("DROP INDEX idx_lie_library_rel"))
    with target_engine.connect() as conn:
        assert database.library_index_generation_contract_status(conn)["ready"] is True

    with target_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO library_index_entries(
                library_id,
                generation,
                materialized_seq,
                entry_type,
                relative_path,
                absolute_path,
                name,
                name_sort_key,
                size,
                file_count,
                depth,
                indexed_at
            )
            SELECT library_id,
                   2,
                   materialized_seq,
                   entry_type,
                   relative_path,
                   absolute_path || '#generation-2',
                   name,
                   name_sort_key,
                   size,
                   file_count,
                   depth,
                   indexed_at
              FROM library_index_entries
             WHERE library_id = 'legacy-alembic-library'
               AND generation = 1
        """))

    with pytest.raises(RuntimeError, match="跨 generation 的重复路径"):
        command.downgrade(alembic_config, previous_revision)

    with target_engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM library_index_entries "
            "WHERE library_id = 'legacy-alembic-library' AND generation = 2"
        ))
    command.downgrade(alembic_config, previous_revision)

    downgraded_inspector = inspect(target_engine)
    downgraded_columns = {
        column["name"]
        for column in downgraded_inspector.get_columns("library_index_entries")
    }
    downgraded_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in downgraded_inspector.get_indexes("library_index_entries")
    }
    assert "generation" not in downgraded_columns
    assert "materialized_seq" not in downgraded_columns
    assert downgraded_indexes["idx_lie_library_rel"] == (
        "library_id",
        "relative_path",
    )
    assert "idx_lie_library_generation_rel" not in downgraded_indexes
