"""保存任务列表轻量投影并回填既有快照。"""
from alembic import op

revision = "20261030_0002_task_list"
down_revision = "20261030_0001_circle_linked_rj"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE task_center_items ADD COLUMN IF NOT EXISTS list_projection JSONB")
    from app.core.task_center_list_projection import backfill_list_projections

    backfill_list_projections(op.get_bind())


def downgrade():
    op.execute("ALTER TABLE task_center_items DROP COLUMN IF EXISTS list_projection")
