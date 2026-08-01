"""Add durable circle external search records.

Revision ID: 20260726_0001_circle_external_search_records
Revises: 20260712_0001_deferred_archive_queue
Create Date: 2026-07-26
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260726_0001_circle_external_search_records"
down_revision = "20260712_0001_deferred_archive_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS circle_external_search_records (
            id SERIAL PRIMARY KEY,
            source VARCHAR(40) NOT NULL,
            rjcode VARCHAR(20) NOT NULL,
            probe_schema_version VARCHAR(40) NOT NULL DEFAULT 'v1',
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            results_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            search_url TEXT NOT NULL DEFAULT '',
            checked_at TIMESTAMP WITHOUT TIME ZONE,
            next_probe_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            lease_until TIMESTAMP WITHOUT TIME ZONE,
            priority INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error_code VARCHAR(80) NOT NULL DEFAULT '',
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    for sql in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_circle_external_search_record_unique ON circle_external_search_records(source, rjcode, probe_schema_version)",
        "CREATE INDEX IF NOT EXISTS idx_circle_external_search_record_ready ON circle_external_search_records(next_probe_at, priority, id)",
        "CREATE INDEX IF NOT EXISTS idx_circle_external_search_record_lease ON circle_external_search_records(lease_until, id)",
    ):
        bind.execute(text(sql))


def downgrade() -> None:
    op.drop_table("circle_external_search_records")
