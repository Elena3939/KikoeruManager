"""Slow SQL search governance indexes.

Revision ID: 20260703_0001_slow_sql_search_governance
Revises: 20260702_0001_dlsite_bonus_probe
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260703_0001_slow_sql_search_governance"
down_revision = "20260702_0001_dlsite_bonus_probe"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar())


def _execute_if_table_exists(bind, table_name: str, sql: str) -> None:
    if _table_exists(bind, table_name):
        bind.execute(text(sql))


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    if _table_exists(bind, "activity_logs"):
        bind.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS batch_id VARCHAR(80)"))
        bind.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS session_key VARCHAR(120)"))
        bind.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS parent_id VARCHAR(36)"))
        bind.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS searchable_text TEXT"))
        bind.execute(text("""
            UPDATE activity_logs
               SET batch_id = left(COALESCE(detail ->> 'batch_id', ''), 80)
             WHERE batch_id IS NULL
               AND detail ? 'batch_id'
        """))
        bind.execute(text("""
            UPDATE activity_logs
               SET session_key = left(COALESCE(detail ->> 'session_key', detail ->> 'session_id', ''), 120)
             WHERE session_key IS NULL
               AND (detail ? 'session_key' OR detail ? 'session_id')
        """))
        bind.execute(text("""
            UPDATE activity_logs
               SET parent_id = left(COALESCE(detail ->> 'parent_id', ''), 36)
             WHERE parent_id IS NULL
               AND detail ? 'parent_id'
        """))
        bind.execute(text("""
            UPDATE activity_logs
               SET searchable_text = left(concat_ws(' ',
                     COALESCE(summary, ''),
                     COALESCE(source_path, ''),
                     COALESCE(rjcode, ''),
                     COALESCE(task_id, ''),
                     COALESCE(batch_id, ''),
                     COALESCE(session_key, '')
                   ), 12000)
             WHERE searchable_text IS NULL
        """))
        bind.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_activity_logs_searchable_text_trgm "
            "ON activity_logs USING gin (searchable_text gin_trgm_ops)"
        ))
    for table_name, sql in (
        ("password_entries", "CREATE INDEX IF NOT EXISTS idx_password_entries_search_text_trgm ON password_entries USING gin ((COALESCE(rjcode, '') || ' ' || COALESCE(filename, '') || ' ' || COALESCE(password, '') || ' ' || COALESCE(description, '')) gin_trgm_ops)"),
        ("security_gate_auth_logs", "CREATE INDEX IF NOT EXISTS idx_security_gate_auth_logs_ip_trgm ON security_gate_auth_logs USING gin (ip_address gin_trgm_ops)"),
        ("circle_catalogs", "CREATE INDEX IF NOT EXISTS idx_circle_catalogs_search_text_trgm ON circle_catalogs USING gin ((COALESCE(circle_name_normalized, '') || ' ' || COALESCE(circle_name, '') || ' ' || COALESCE(circle_id, '')) gin_trgm_ops)"),
        ("circle_works", "CREATE INDEX IF NOT EXISTS idx_circle_works_search_text_trgm ON circle_works USING gin ((COALESCE(canonical_rjcode, '') || ' ' || COALESCE(display_rjcode, '') || ' ' || COALESCE(title, '')) gin_trgm_ops)"),
    ):
        _execute_if_table_exists(bind, table_name, sql)
    for index_name in (
        "idx_activity_logs_summary_trgm",
        "idx_activity_logs_source_path_trgm",
        "idx_activity_logs_rjcode_trgm",
        "idx_activity_logs_task_id_trgm",
        "idx_activity_logs_batch_id_trgm",
        "idx_task_center_title_trgm",
        "idx_task_center_business_key_trgm",
        "idx_task_center_engine_task_id_trgm",
    ):
        bind.execute(text(f"DROP INDEX IF EXISTS {index_name}"))


def downgrade() -> None:
    bind = op.get_bind()
    for index_name in (
        "idx_activity_logs_searchable_text_trgm",
        "idx_password_entries_search_text_trgm",
        "idx_security_gate_auth_logs_ip_trgm",
        "idx_circle_catalogs_search_text_trgm",
        "idx_circle_works_search_text_trgm",
    ):
        bind.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    bind.execute(text("ALTER TABLE activity_logs DROP COLUMN IF EXISTS searchable_text"))
