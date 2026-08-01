"""Add canonical-link evidence fields.

Revision ID: 20260801_0001_work_canonical_link_evidence
Revises: 20260726_0001_circle_external_search_records
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260801_0001_work_canonical_link_evidence"
down_revision = "20260726_0001_circle_external_search_records"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"),
        {"name": table_name},
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "work_canonical_links"):
        return

    bind.execute(text("""
        ALTER TABLE work_canonical_links
            ADD COLUMN IF NOT EXISTS evidence_source VARCHAR(80),
            ADD COLUMN IF NOT EXISTS evidence_status VARCHAR(30)
    """))
    bind.execute(text("""
        UPDATE work_canonical_links
           SET evidence_source = COALESCE(NULLIF(evidence_source, ''), 'legacy'),
               evidence_status = COALESCE(NULLIF(evidence_status, ''), 'legacy_unverified')
         WHERE evidence_source IS NULL
            OR evidence_source = ''
            OR evidence_status IS NULL
            OR evidence_status = ''
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_work_canonical_links_evidence_status
            ON work_canonical_links(evidence_status)
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "work_canonical_links"):
        return

    bind.execute(text(
        "DROP INDEX IF EXISTS ix_work_canonical_links_evidence_status"
    ))
    bind.execute(text("""
        ALTER TABLE work_canonical_links
            DROP COLUMN IF EXISTS evidence_status,
            DROP COLUMN IF EXISTS evidence_source
    """))
