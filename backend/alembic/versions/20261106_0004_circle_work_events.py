"""社团补全作品级增量事件。"""
from alembic import op

revision = "20261106_0004_circle_work_events"
down_revision = "20261105_0003_circle_read_model"
branch_labels = None
depends_on = None


def upgrade():
    from app.models.database import Base
    Base.metadata.tables["circle_completion_work_events"].create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("circle_completion_work_events")
