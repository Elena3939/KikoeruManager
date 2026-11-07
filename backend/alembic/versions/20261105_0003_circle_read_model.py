"""社团补全读模型与事务内变更捕获。"""
from alembic import op

revision = "20261105_0003_circle_read_model"
down_revision = "20261105_0002_subtitle_paths"
branch_labels = None
depends_on = None

TABLES = (
    "circle_completion_heads", "circle_completion_controls", "circle_completion_dirty",
    "circle_completion_work_states", "circle_completion_work_aliases", "circle_completion_groups",
    "circle_completion_group_members", "circle_completion_cover_facts", "circle_completion_publish_outbox",
)


def upgrade():
    from app.models.database import Base
    from app.core.circle_completion_changes import install_change_capture
    conn = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(conn, checkfirst=True)
    install_change_capture(conn)


def downgrade():
    from app.core.circle_completion_changes import SOURCE_TABLES
    for table in SOURCE_TABLES:
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS cc_dirty_{table}_{operation} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS circle_completion_capture()")
    op.execute("DROP FUNCTION IF EXISTS circle_completion_source_value(jsonb,text)")
    op.execute("DROP FUNCTION IF EXISTS circle_completion_enqueue(text[],text[],text,boolean)")
    for name in reversed(TABLES):
        op.drop_table(name)
