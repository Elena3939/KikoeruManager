"""操作身份投影、执行指标与可恢复代际重建。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261111_0006_activity_ops"
down_revision = "20261109_0005_link_sheet"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("idx_activity_parent", "activity_logs", ["parent_id"])
    op.create_index("idx_activity_detail_parent", "activity_logs", [sa.text("(detail ->> 'parent_id')")])
    op.create_table("activity_log_detail_archives",
        sa.Column("event_id", sa.String(36), sa.ForeignKey("activity_logs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("activity_log_operations",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("identity_kind", sa.String(24), nullable=False),
        sa.Column("identity_value", sa.Text(), nullable=False),
        sa.Column("root_log_id", sa.String(36)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("original_status", sa.String(24)),
        sa.Column("initiated_at", sa.DateTime(), nullable=False),
        sa.Column("latest_activity_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("counts", JSONB(), nullable=False),
        sa.Column("presentation", JSONB(), nullable=False),
        sa.Column("integrity", JSONB(), nullable=False))
    for name, fields in (
        ("page", ["generation", "latest_activity_at", "operation_id"]),
        ("date", ["generation", "initiated_at"]),
        ("filter", ["generation", "category", "status", "initiated_at"]),
    ):
        op.create_index(f"idx_activity_operation_{name}", "activity_log_operations", fields)
    op.create_table("activity_log_operation_members",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("member_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("original_status", sa.String(24)),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("is_projection", sa.Boolean(), nullable=False))
    op.create_table("activity_log_operation_events",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(64), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False))
    op.create_index("idx_activity_operation_events_page", "activity_log_operation_events",
                    ["generation", "operation_id", "event_at", "event_id"])
    op.create_table("activity_log_metric_facts",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("execution_id", sa.String(64), primary_key=True),
        sa.Column("phase", sa.String(24), primary_key=True),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("operation_id", sa.String(64), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("authority", sa.Integer(), nullable=False))
    op.create_index("idx_activity_metric_date", "activity_log_metric_facts",
                    ["generation", "completed_at", "phase", "metric"])
    op.create_index("idx_activity_metric_operation", "activity_log_metric_facts", ["generation", "operation_id"])
    op.create_table("activity_log_operation_files",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), primary_key=True),
        sa.Column("phase", sa.String(24), primary_key=True),
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False))
    op.create_index("idx_activity_operation_file_page", "activity_log_operation_files",
                    ["generation", "operation_id", "phase", "file_id", "execution_id"])
    op.create_table("activity_log_operation_daily",
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("category", sa.String(40), primary_key=True),
        sa.Column("status", sa.String(24), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("phase", sa.String(24), primary_key=True),
        sa.Column("metric", sa.String(32), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False))
    op.create_table("activity_log_projection_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active_generation", sa.Integer(), nullable=False),
        sa.Column("building_generation", sa.Integer()),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("checkpoint", JSONB(), nullable=False))
    op.create_table("activity_log_projection_repairs",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("component", sa.String(24), primary_key=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade():
    for table in ("activity_log_projection_repairs", "activity_log_projection_state", "activity_log_operation_daily",
                  "activity_log_operation_files", "activity_log_metric_facts",
                  "activity_log_operation_events", "activity_log_operation_members", "activity_log_operations"):
        op.drop_table(table)
    op.drop_table("activity_log_detail_archives")
    op.drop_index("idx_activity_parent", table_name="activity_logs")
    op.drop_index("idx_activity_detail_parent", table_name="activity_logs")
