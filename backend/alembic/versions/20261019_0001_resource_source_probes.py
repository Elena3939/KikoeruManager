"""保存资源站探测结果与可恢复探测队列。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261019_0001_resource_source_probes'
down_revision = '20260802_0001_library_index_children_index_cleanup'
branch_labels = None
depends_on = None


def upgrade():
    # baseline 使用当前 ORM 建表；旧库增量升级时此表则可能尚不存在。
    # 固定迁移自身的结构定义，不依赖运行时 ORM，也不重复创建已有表和索引。
    metadata = sa.MetaData()
    table = sa.Table(
        'resource_source_probes',
        metadata,
        sa.Column('source', sa.String(40), primary_key=True),
        sa.Column('rjcode', sa.String(20), primary_key=True),
        sa.Column('probe_version', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('candidates', JSONB(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('checked_at', sa.DateTime()),
        sa.Column('expires_at', sa.DateTime()),
    )
    bind = op.get_bind()
    table.create(bind, checkfirst=True)
    sa.Index('ix_resource_source_probes_status', table.c.status).create(bind, checkfirst=True)
    sa.Index('ix_resource_source_probes_expires_at', table.c.expires_at).create(bind, checkfirst=True)


def downgrade():
    op.drop_table('resource_source_probes')
