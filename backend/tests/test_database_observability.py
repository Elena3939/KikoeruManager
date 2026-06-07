import logging
from types import SimpleNamespace

from sqlalchemy import create_engine, text

from app.models import database


def test_slow_sql_param_summary_does_not_log_values():
    params = {
        "token": "secret-token-value",
        "path": "D:/private/library/RJ123456",
        "limit": 50,
        "payload": b"abc",
    }

    summary = database._summarize_sql_params(params)

    assert summary == {
        "token": "str[18]",
        "path": "str[27]",
        "limit": "int",
        "payload": "bytes[3]",
    }
    assert "secret-token-value" not in str(summary)
    assert "D:/private/library" not in str(summary)


def test_slow_sql_logger_records_elapsed_sql_and_param_shapes(monkeypatch, caplog):
    monkeypatch.setattr(database, "_SLOW_SQL_LOG_THRESHOLD_SECONDS", 0.01)
    monkeypatch.setattr(database.time, "perf_counter", lambda: 10.25)
    context = SimpleNamespace(_kikoerumanager_sql_started_at=10.0)
    cursor = SimpleNamespace(rowcount=3)

    with caplog.at_level(logging.WARNING, logger=database.__name__):
        database._slow_sql_after_cursor_execute(
            None,
            cursor,
            "SELECT * FROM activity_logs WHERE source_path = :path",
            {"path": "D:/private/library/RJ123456"},
            context,
            False,
        )

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "慢 SQL 0.250s" in output
    assert "activity_logs" in output
    assert "'path': 'str[27]'" in output
    assert "D:/private/library" not in output


def test_slow_sql_logger_skips_below_threshold(monkeypatch, caplog):
    monkeypatch.setattr(database, "_SLOW_SQL_LOG_THRESHOLD_SECONDS", 1.0)
    monkeypatch.setattr(database.time, "perf_counter", lambda: 10.25)
    context = SimpleNamespace(_kikoerumanager_sql_started_at=10.0)
    cursor = SimpleNamespace(rowcount=1)

    with caplog.at_level(logging.WARNING, logger=database.__name__):
        database._slow_sql_after_cursor_execute(
            None,
            cursor,
            "SELECT 1",
            {},
            context,
            False,
        )

    assert not caplog.records


def test_task_center_items_schema_migration_adds_missing_columns_and_indexes():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE task_center_items (item_id VARCHAR(80) PRIMARY KEY)"))
        database._migrate_task_center_items_schema(conn)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(task_center_items)")).fetchall()}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(task_center_items)")).fetchall()}

    assert "searchable_text" in columns
    assert "payload_json" in columns
    assert "idx_task_center_items_domain_status" in indexes
    assert "ix_task_center_items_business_key" in indexes


def test_activity_log_rollups_schema_migration_adds_missing_columns_and_indexes():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE activity_log_rollups (rollup_key VARCHAR(180) PRIMARY KEY)"))
        database._migrate_activity_log_rollups_schema(conn)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(activity_log_rollups)")).fetchall()}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(activity_log_rollups)")).fetchall()}

    assert "waiting_count" in columns
    assert "latest_activity_at" in columns
    assert "idx_activity_rollup_type_value" in indexes
    assert "idx_activity_rollup_category_status" in indexes


def test_task_phase_metrics_schema_migration_adds_missing_columns_and_indexes():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE task_phase_metrics (id VARCHAR(36) PRIMARY KEY)"))
        database._migrate_task_phase_metrics_schema(conn)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(task_phase_metrics)")).fetchall()}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(task_phase_metrics)")).fetchall()}

    assert "duration_ms" in columns
    assert "bytes_total" in columns
    assert "detail_json" in columns
    assert "idx_task_phase_metrics_task_phase" in indexes
    assert "idx_task_phase_metrics_type_phase" in indexes
