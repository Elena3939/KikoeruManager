"""加速库存变更定位受影响的字幕作品。"""
from alembic import op

revision = "20261105_0002_subtitle_paths"
down_revision = "20261105_0001_subtitle_targets"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_library_index_rj_entries_path
            ON library_index_rj_entries (library_id, generation, relative_path)
            WHERE entry_type = 'dir'
        """)


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_library_index_rj_entries_path")
