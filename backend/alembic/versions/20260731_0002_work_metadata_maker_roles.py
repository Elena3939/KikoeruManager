"""Persist original maker and translator names.

Revision ID: 20260731_0002_work_metadata_maker_roles
Revises: 20260731_0001_work_metadata_verification
Create Date: 2026-07-31
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260731_0002_work_metadata_maker_roles"
down_revision = "20260731_0001_work_metadata_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for sql in (
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS original_maker_name TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE work_metadata ADD COLUMN IF NOT EXISTS translator_name TEXT NOT NULL DEFAULT ''",
    ):
        bind.execute(text(sql))

    bind.execute(text(
        "UPDATE work_metadata "
        "SET original_maker_name = COALESCE(NULLIF(original_maker_name, ''), maker_name, '') "
        "WHERE original_maker_name = ''"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    for column_name in ("translator_name", "original_maker_name"):
        bind.execute(text(
            f"ALTER TABLE work_metadata DROP COLUMN IF EXISTS {column_name}"
        ))
