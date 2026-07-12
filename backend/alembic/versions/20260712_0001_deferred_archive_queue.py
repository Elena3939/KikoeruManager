"""Add durable low-priority archive queue.

Revision ID: 20260712_0001_deferred_archive_queue
Revises: 20260710_0001_library_index_consistency
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260712_0001_deferred_archive_queue"
down_revision = "20260710_0001_library_index_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE IF EXISTS processed_archives
        ADD COLUMN IF NOT EXISTS archive_manifest JSONB NOT NULL DEFAULT '[]'::jsonb
    """))
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS deferred_archive_jobs (
            id VARCHAR(36) PRIMARY KEY,
            idempotency_key VARCHAR(128) NOT NULL,
            task_id VARCHAR(36),
            rjcode VARCHAR(20),
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            source_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
            target_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
            available_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            lease_owner VARCHAR(120),
            lease_epoch BIGINT NOT NULL DEFAULT 0,
            lease_until TIMESTAMP WITHOUT TIME ZONE,
            cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP WITHOUT TIME ZONE
        )
    """))
    for sql in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_deferred_archive_jobs_idempotency ON deferred_archive_jobs(idempotency_key)",
        "CREATE INDEX IF NOT EXISTS idx_deferred_archive_jobs_ready ON deferred_archive_jobs(status, available_at, id)",
        "CREATE INDEX IF NOT EXISTS idx_deferred_archive_jobs_lease ON deferred_archive_jobs(lease_until, id)",
        "CREATE INDEX IF NOT EXISTS idx_deferred_archive_jobs_task ON deferred_archive_jobs(task_id)",
    ):
        bind.execute(text(sql))


def downgrade() -> None:
    op.drop_table("deferred_archive_jobs")
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE IF EXISTS processed_archives
        DROP COLUMN IF EXISTS archive_manifest
    """))
