"""Add DLsite bonus probe cache tables.

Revision ID: 20260702_0001_dlsite_bonus_probe
Revises: 0001_postgresql_baseline
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from app.models.database import JSON

revision = "20260702_0001_dlsite_bonus_probe"
down_revision = "0001_postgresql_baseline"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar())


def _index_exists(bind, index_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": index_name}).scalar())


def _create_index(bind, index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _table_exists(bind, table_name) or _index_exists(bind, index_name):
        return
    op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "dlsite_bonus_probe_cache"):
        op.create_table(
            "dlsite_bonus_probe_cache",
            sa.Column("rjcode", sa.String(length=20), primary_key=True),
            sa.Column("exists", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("probe_status", sa.String(length=32), nullable=True, server_default=""),
            sa.Column("maker_id", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("release_date", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("work_type", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("price", sa.BigInteger(), nullable=True, server_default="0"),
            sa.Column("is_sale", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("is_free", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("is_oly", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("wishlist_count", sa.BigInteger(), nullable=True, server_default="0"),
            sa.Column("is_hidden_bonus_audio", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("raw_summary_json", JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index(bind, "ix_dlsite_bonus_probe_cache_exists", "dlsite_bonus_probe_cache", ["exists"])
    _create_index(bind, "ix_dlsite_bonus_probe_cache_probe_status", "dlsite_bonus_probe_cache", ["probe_status"])
    _create_index(bind, "ix_dlsite_bonus_probe_cache_maker_id", "dlsite_bonus_probe_cache", ["maker_id"])
    _create_index(bind, "ix_dlsite_bonus_probe_cache_release_date", "dlsite_bonus_probe_cache", ["release_date"])
    _create_index(bind, "ix_dlsite_bonus_probe_cache_is_hidden_bonus_audio", "dlsite_bonus_probe_cache", ["is_hidden_bonus_audio"])
    _create_index(bind, "ix_dlsite_bonus_probe_cache_checked_at", "dlsite_bonus_probe_cache", ["checked_at"])
    _create_index(bind, "idx_dlsite_bonus_probe_cache_maker_date", "dlsite_bonus_probe_cache", ["maker_id", "release_date"])
    _create_index(bind, "idx_dlsite_bonus_probe_cache_status_checked", "dlsite_bonus_probe_cache", ["probe_status", "checked_at"])

    if not _table_exists(bind, "dlsite_bonus_probe_dates"):
        op.create_table(
            "dlsite_bonus_probe_dates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("maker_id", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("circle_id", sa.String(length=120), nullable=True, server_default=""),
            sa.Column("release_date", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("gap_limit", sa.Integer(), nullable=True, server_default="500"),
            sa.Column("mode", sa.String(length=20), nullable=True, server_default="normal"),
            sa.Column("status", sa.String(length=24), nullable=True, server_default="pending"),
            sa.Column("job_id", sa.String(length=36), nullable=True, server_default=""),
            sa.Column("public_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("sou_public_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("gap_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("probe_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("cached_hit_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("request_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("hit_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("inserted_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("budget_reached", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index(bind, "ix_dlsite_bonus_probe_dates_maker_id", "dlsite_bonus_probe_dates", ["maker_id"])
    _create_index(bind, "ix_dlsite_bonus_probe_dates_circle_id", "dlsite_bonus_probe_dates", ["circle_id"])
    _create_index(bind, "ix_dlsite_bonus_probe_dates_release_date", "dlsite_bonus_probe_dates", ["release_date"])
    _create_index(bind, "ix_dlsite_bonus_probe_dates_status", "dlsite_bonus_probe_dates", ["status"])
    _create_index(bind, "ix_dlsite_bonus_probe_dates_job_id", "dlsite_bonus_probe_dates", ["job_id"])
    _create_index(bind, "idx_dlsite_bonus_probe_dates_unique", "dlsite_bonus_probe_dates", ["maker_id", "release_date", "gap_limit"], unique=True)
    _create_index(bind, "idx_dlsite_bonus_probe_dates_status_updated", "dlsite_bonus_probe_dates", ["status", "updated_at"])
    _create_index(bind, "idx_dlsite_bonus_probe_dates_circle_date", "dlsite_bonus_probe_dates", ["circle_id", "release_date"])

    if not _table_exists(bind, "dlsite_bonus_original_probe_states"):
        op.create_table(
            "dlsite_bonus_original_probe_states",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("circle_id", sa.String(length=120), nullable=True, server_default=""),
            sa.Column("maker_id", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("original_rjcode", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("release_date", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("status", sa.String(length=24), nullable=True, server_default="unknown"),
            sa.Column("strategy_version", sa.String(length=40), nullable=True, server_default=""),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_circle_id", "dlsite_bonus_original_probe_states", ["circle_id"])
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_maker_id", "dlsite_bonus_original_probe_states", ["maker_id"])
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_original_rjcode", "dlsite_bonus_original_probe_states", ["original_rjcode"])
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_release_date", "dlsite_bonus_original_probe_states", ["release_date"])
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_status", "dlsite_bonus_original_probe_states", ["status"])
    _create_index(bind, "ix_dlsite_bonus_original_probe_states_checked_at", "dlsite_bonus_original_probe_states", ["checked_at"])
    _create_index(bind, "idx_dlsite_bonus_original_state_unique", "dlsite_bonus_original_probe_states", ["circle_id", "original_rjcode"], unique=True)
    _create_index(bind, "idx_dlsite_bonus_original_state_circle_date", "dlsite_bonus_original_probe_states", ["circle_id", "release_date"])
    _create_index(bind, "idx_dlsite_bonus_original_state_maker_date", "dlsite_bonus_original_probe_states", ["maker_id", "release_date"])

    if not _table_exists(bind, "dlsite_bonus_probe_hit_index"):
        op.create_table(
            "dlsite_bonus_probe_hit_index",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("circle_id", sa.String(length=120), nullable=True, server_default=""),
            sa.Column("maker_id", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("release_date", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("bonus_rjcode", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index(bind, "ix_dlsite_bonus_probe_hit_index_circle_id", "dlsite_bonus_probe_hit_index", ["circle_id"])
    _create_index(bind, "ix_dlsite_bonus_probe_hit_index_maker_id", "dlsite_bonus_probe_hit_index", ["maker_id"])
    _create_index(bind, "ix_dlsite_bonus_probe_hit_index_release_date", "dlsite_bonus_probe_hit_index", ["release_date"])
    _create_index(bind, "ix_dlsite_bonus_probe_hit_index_bonus_rjcode", "dlsite_bonus_probe_hit_index", ["bonus_rjcode"])
    _create_index(bind, "idx_dlsite_bonus_probe_hit_unique", "dlsite_bonus_probe_hit_index", ["maker_id", "bonus_rjcode"], unique=True)
    _create_index(bind, "idx_dlsite_bonus_probe_hit_circle_date", "dlsite_bonus_probe_hit_index", ["circle_id", "release_date"])
    _create_index(bind, "idx_dlsite_bonus_probe_hit_maker_date", "dlsite_bonus_probe_hit_index", ["maker_id", "release_date"])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS dlsite_bonus_probe_hit_index CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS dlsite_bonus_original_probe_states CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS dlsite_bonus_probe_dates CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS dlsite_bonus_probe_cache CASCADE"))
