"""Widen bonus probe date mode.

Revision ID: 20260709_0001_bonus_probe_mode_width
Revises: 20260707_0001_bonus_probe_resilience
Create Date: 2026-07-09
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260709_0001_bonus_probe_mode_width"
down_revision = "20260707_0001_bonus_probe_resilience"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "dlsite_bonus_probe_dates"):
        bind.execute(text("ALTER TABLE dlsite_bonus_probe_dates ALTER COLUMN mode TYPE VARCHAR(64)"))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "dlsite_bonus_probe_dates"):
        bind.execute(text(
            "ALTER TABLE dlsite_bonus_probe_dates "
            "ALTER COLUMN mode TYPE VARCHAR(20) USING left(COALESCE(mode, ''), 20)"
        ))
