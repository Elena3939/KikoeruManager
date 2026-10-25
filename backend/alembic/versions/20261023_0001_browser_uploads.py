"""持久化浏览器分块上传会话及文件恢复检查点。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261023_0001_browser_uploads'
down_revision = '20261019_0002_external_source_queue_index'
branch_labels = None
depends_on = None


def upgrade():
    # 新库的 baseline 已创建这些表；旧库仍需按会话、文件的依赖顺序补建。
    metadata = sa.MetaData()
    sessions = sa.Table('browser_upload_sessions', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('library_id', sa.String(100), nullable=False),
        sa.Column('target_path', sa.Text(), nullable=False),
        sa.Column('state', JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    files = sa.Table('browser_upload_files', metadata,
        sa.Column('session_id', sa.String(36), sa.ForeignKey('browser_upload_sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('relative_path', sa.Text(), nullable=False),
        sa.Column('state', JSONB(), nullable=False))
    bind = op.get_bind()
    sessions.create(bind, checkfirst=True)
    sa.Index('ix_browser_upload_sessions_updated_at', sessions.c.updated_at).create(bind, checkfirst=True)
    files.create(bind, checkfirst=True)


def downgrade():
    op.drop_table('browser_upload_files')
    op.drop_table('browser_upload_sessions')
