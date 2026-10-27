"""持久化社团补全查询统计与有序作品组。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "20261027_0001_circle_projection"
down_revision = "20261025_0001_input_scan_queue"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    metadata = sa.MetaData()
    header = sa.Table("circle_completion_projections", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("circle_id", sa.String(120), nullable=False, index=True),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, index=True))
    rows = sa.Table("circle_completion_projection_rows", metadata,
        sa.Column("projection_id", sa.String(64), sa.ForeignKey(header.c.id, ondelete="CASCADE"), primary_key=True),
        sa.Column("variant", sa.String(32), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("aliases", ARRAY(sa.Text()), nullable=False),
        sa.Column("parent_codes", ARRAY(sa.Text()), nullable=False),
        sa.Column("is_bonus", sa.Boolean(), nullable=False),
        sa.Column("release_timestamp", sa.Float(), nullable=False),
        sa.Column("unreleased", sa.Boolean(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("compare_payload", JSONB()))
    sa.Index("ix_circle_projection_tags", rows.c.tags, postgresql_using="gin")
    sa.Index("ix_circle_projection_search", rows.c.search_text, postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"})
    sa.Index("ix_circle_projection_release", rows.c.projection_id, rows.c.variant, rows.c.unreleased, rows.c.release_timestamp, rows.c.title, rows.c.position)
    metadata.create_all(bind, tables=[header, rows], checkfirst=True)


def downgrade():
    op.drop_table("circle_completion_projection_rows")
    op.drop_table("circle_completion_projections")
