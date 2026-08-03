"""Persist DLsite metadata verification evidence.

Revision ID: 20260731_0001_work_metadata_verification
Revises: 20260726_0001_circle_external_search_records
Create Date: 2026-07-31
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260731_0001_work_metadata_verification"
down_revision = "20260726_0001_circle_external_search_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for sql in (
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS metadata_verification_status VARCHAR(20) NOT NULL DEFAULT 'unverified'",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS metadata_verification_reason TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS metadata_evidence_source VARCHAR(80) NOT NULL DEFAULT ''",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS resolved_workno VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS verified_parent_workno VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS verified_parent_child_relation BOOLEAN NOT NULL DEFAULT FALSE",
    ):
        bind.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    for column_name in (
        "verified_parent_child_relation",
        "verified_parent_workno",
        "resolved_workno",
        "metadata_evidence_source",
        "metadata_verification_reason",
        "metadata_verification_status",
    ):
        bind.execute(text(
            f"ALTER TABLE work_metadata DROP COLUMN IF EXISTS {column_name}"
        ))
