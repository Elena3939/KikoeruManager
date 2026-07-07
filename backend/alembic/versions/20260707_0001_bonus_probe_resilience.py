"""Harden bonus probe cache and notification keys.

Revision ID: 20260707_0001_bonus_probe_resilience
Revises: 20260703_0001_slow_sql_search_governance
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260707_0001_bonus_probe_resilience"
down_revision = "20260703_0001_slow_sql_search_governance"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar())


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    return bool(bind.execute(
        text("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = :table_name
               AND column_name = :column_name
        """),
        {"table_name": table_name, "column_name": column_name},
    ).first())


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "dlsite_bonus_probe_cache"):
        if _column_exists(bind, "dlsite_bonus_probe_cache", "price"):
            bind.execute(text("ALTER TABLE dlsite_bonus_probe_cache ALTER COLUMN price TYPE BIGINT USING COALESCE(price, 0)::bigint"))
        if _column_exists(bind, "dlsite_bonus_probe_cache", "wishlist_count"):
            bind.execute(text("ALTER TABLE dlsite_bonus_probe_cache ALTER COLUMN wishlist_count TYPE BIGINT USING COALESCE(wishlist_count, 0)::bigint"))
    if _table_exists(bind, "notification_inbox_items") and _column_exists(bind, "notification_inbox_items", "business_key"):
        bind.execute(text("ALTER TABLE notification_inbox_items ALTER COLUMN business_key TYPE TEXT"))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "notification_inbox_items") and _column_exists(bind, "notification_inbox_items", "business_key"):
        bind.execute(text("ALTER TABLE notification_inbox_items ALTER COLUMN business_key TYPE VARCHAR(120) USING left(COALESCE(business_key, ''), 120)"))
    if _table_exists(bind, "dlsite_bonus_probe_cache"):
        if _column_exists(bind, "dlsite_bonus_probe_cache", "price"):
            bind.execute(text("ALTER TABLE dlsite_bonus_probe_cache ALTER COLUMN price TYPE INTEGER USING LEAST(GREATEST(COALESCE(price, 0), 0), 2147483647)::integer"))
        if _column_exists(bind, "dlsite_bonus_probe_cache", "wishlist_count"):
            bind.execute(text("ALTER TABLE dlsite_bonus_probe_cache ALTER COLUMN wishlist_count TYPE INTEGER USING LEAST(GREATEST(COALESCE(wishlist_count, 0), 0), 2147483647)::integer"))
