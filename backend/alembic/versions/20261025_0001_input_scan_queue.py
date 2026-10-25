"""扫描批次、候选、源占用及可靠交接事件。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261025_0001_input_scan_queue"
down_revision = "20261023_0001_browser_uploads"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.alter_column("tasks", "type", type_=sa.String(64), existing_type=sa.String(20))
    metadata = sa.MetaData()
    sa.Table("tasks", metadata, sa.Column("id", sa.String(36), primary_key=True))
    runs = sa.Table("input_scan_runs", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(100), unique=True, nullable=False),
        sa.Column("batch_id", sa.String(36), unique=True, nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("scan_status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("execution_status", sa.String(24), nullable=False, server_default="waiting"),
        sa.Column("producer_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("policy", JSONB(), nullable=False, server_default="{}"),
        sa.Column("coverage", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    candidates = sa.Table("input_scan_candidates", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("input_scan_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.String(64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text()),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), unique=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("evidence", JSONB(), nullable=False, server_default="{}"),
        sa.Column("preparation", JSONB(), nullable=False, server_default="{}"),
        sa.Column("destination", sa.String(24)),
        sa.Column("record_id", sa.String(36)),
        sa.Column("next_check_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    entries = sa.Table("input_scan_entries", metadata,
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("input_scan_candidates.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("path_key", sa.String(64), primary_key=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("fingerprint", JSONB(), nullable=False, server_default="{}"))
    claims = sa.Table("input_source_claims", metadata,
        sa.Column("path_key", sa.String(64), primary_key=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.String(24), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    outbox = sa.Table("input_scan_outbox", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_key", sa.String(160), unique=True, nullable=False),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("input_scan_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    directory_entries = sa.Table("input_scan_directory_entries", metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("input_scan_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("directory_key", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("lower_name", sa.Text(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()))
    for table in (runs, candidates, entries, claims, outbox, directory_entries):
        table.create(bind, checkfirst=True)
    for index in (
        sa.Index("ix_input_scan_runs_status_updated", runs.c.scan_status, runs.c.updated_at),
        sa.Index("uq_input_scan_candidate_group", candidates.c.scan_id, candidates.c.group_key, unique=True),
        sa.Index("ix_input_scan_candidate_due", candidates.c.scan_id, candidates.c.state, candidates.c.next_check_at, candidates.c.id),
        sa.Index("ix_input_source_claim_owner", claims.c.owner_type, claims.c.owner_id),
        sa.Index("ix_input_scan_directory_page", directory_entries.c.scan_id, directory_entries.c.directory_key, directory_entries.c.id),
        sa.Index("ix_input_scan_directory_prefix", directory_entries.c.scan_id, directory_entries.c.directory_key,
                 directory_entries.c.lower_name, postgresql_ops={"lower_name": "text_pattern_ops"}),
        sa.Index("ix_input_scan_outbox_due", outbox.c.available_at, outbox.c.id,
                 postgresql_where=outbox.c.delivered_at.is_(None)),
    ):
        index.create(bind, checkfirst=True)
    op.execute("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS event_key VARCHAR(160)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_logs_event_key ON activity_logs(event_key)")


def downgrade():
    # PostgreSQL 缩列前明确拒绝已有长类型，禁止隐式截断真实任务记录。
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM tasks WHERE length(type) > 20)")).scalar():
        raise RuntimeError("tasks 包含超过 20 字符的任务类型，不能安全降级")
    op.alter_column("tasks", "type", type_=sa.String(20), existing_type=sa.String(64))
    op.execute("DROP INDEX IF EXISTS uq_activity_logs_event_key")
    op.execute("ALTER TABLE activity_logs DROP COLUMN IF EXISTS event_key")
    for table in ("input_scan_directory_entries", "input_scan_outbox", "input_source_claims", "input_scan_entries",
                  "input_scan_candidates", "input_scan_runs"):
        op.drop_table(table)
