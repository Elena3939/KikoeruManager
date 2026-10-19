"""按资源来源及优先级领取探测任务，避免百万队列全量排序。"""
from alembic import op

revision = '20261019_0002_external_source_queue_index'
down_revision = '20261019_0001_resource_source_probes'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS '
                   'idx_circle_external_search_record_source_ready '
                   'ON circle_external_search_records '
                   '(source, probe_schema_version, priority DESC, next_probe_at, id)')


def downgrade():
    with op.get_context().autocommit_block():
        op.execute('DROP INDEX CONCURRENTLY IF EXISTS idx_circle_external_search_record_source_ready')
