"""保存资源站探测结果与可恢复探测队列。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261019_0001_resource_source_probes'
down_revision = '20260802_0001_library_index_children_index_cleanup'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'resource_source_probes',
        sa.Column('source', sa.String(40), primary_key=True),
        sa.Column('rjcode', sa.String(20), primary_key=True),
        sa.Column('probe_version', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('candidates', JSONB(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('checked_at', sa.DateTime()),
        sa.Column('expires_at', sa.DateTime()),
    )
    op.create_index('ix_resource_source_probes_status', 'resource_source_probes', ['status'])
    op.create_index('ix_resource_source_probes_expires_at', 'resource_source_probes', ['expires_at'])


def downgrade():
    op.drop_table('resource_source_probes')
