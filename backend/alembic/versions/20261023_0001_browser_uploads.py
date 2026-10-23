"""持久化浏览器分块上传会话及文件恢复检查点。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261023_0001_browser_uploads'
down_revision = '20261019_0002_external_source_queue_index'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('browser_upload_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('library_id', sa.String(100), nullable=False),
        sa.Column('target_path', sa.Text(), nullable=False),
        sa.Column('state', JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_browser_upload_sessions_updated_at', 'browser_upload_sessions', ['updated_at'])
    op.create_table('browser_upload_files',
        sa.Column('session_id', sa.String(36), sa.ForeignKey('browser_upload_sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('relative_path', sa.Text(), nullable=False),
        sa.Column('state', JSONB(), nullable=False))


def downgrade():
    op.drop_table('browser_upload_files')
    op.drop_table('browser_upload_sessions')
