"""为社团作品关联 RJ 的精确包含查询建立索引。"""
from alembic import op

revision = "20261030_0001_circle_linked_rj"
down_revision = "20261027_0001_circle_projection"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_circle_works_linked_rjcodes_gin "
            "ON circle_works USING gin (linked_rjcodes jsonb_path_ops)"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_circle_works_linked_rjcodes_gin")
