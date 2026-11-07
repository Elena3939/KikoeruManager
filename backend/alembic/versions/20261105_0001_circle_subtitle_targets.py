"""持久化社团字幕目录摘要。"""
from alembic import op
import sqlalchemy as sa

revision = "20261105_0001_subtitle_targets"
down_revision = "20261030_0002_task_list"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    table = sa.Table(
        "circle_subtitle_target_snapshots", metadata,
        sa.Column("rjcode", sa.String(20), primary_key=True),
        sa.Column("index_version", sa.String(64), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    table.create(op.get_bind(), checkfirst=True)
    sa.Index("ix_circle_subtitle_target_snapshots_index_version", table.c.index_version).create(
        op.get_bind(), checkfirst=True)
    sa.Index("ix_circle_subtitle_target_snapshots_notified", table.c.notified).create(
        op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("circle_subtitle_target_snapshots")
