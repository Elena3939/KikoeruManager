"""Excel 链接库批次、修订、文件与当前指针。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261109_0005_link_sheet"
down_revision = "20261106_0004_circle_work_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("link_sheet_imports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("statistics", pg.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("affected_circles", pg.JSONB(), nullable=False),
        sa.Column("materialization_targets", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_link_sheet_imports_status", "link_sheet_imports", ["status"])
    op.create_table("link_sheet_revisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("import_id", sa.String(32), sa.ForeignKey("link_sheet_imports.id"), nullable=False),
        sa.Column("rjcode", sa.String(10), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", pg.JSONB(), nullable=False),
        sa.Column("groups", pg.JSONB(), nullable=False),
        sa.Column("errors", pg.JSONB(), nullable=False),
        sa.Column("change_kind", sa.String(24), nullable=False),
        sa.Column("reuse_revision_id", sa.String(32), sa.ForeignKey("link_sheet_revisions.id")))
    for name, cols in (("ix_link_sheet_revisions_import_id", ["import_id"]),
                       ("ix_link_sheet_revisions_rjcode", ["rjcode"]),
                       ("ix_link_sheet_revisions_reuse_revision_id", ["reuse_revision_id"]),
                       ("ix_link_sheet_revision_batch_code", ["import_id", "rjcode"])):
        op.create_index(name, "link_sheet_revisions", cols)
    op.create_table("link_sheet_files",
        sa.Column("revision_id", sa.String(32), sa.ForeignKey("link_sheet_revisions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("raw_size", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False))
    op.create_table("link_sheet_current",
        sa.Column("rjcode", sa.String(10), primary_key=True),
        sa.Column("revision_id", sa.String(32), sa.ForeignKey("link_sheet_revisions.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False))
    op.create_index("ix_link_sheet_current_revision_id", "link_sheet_current", ["revision_id"])


def downgrade():
    for table in ("link_sheet_current", "link_sheet_files", "link_sheet_revisions", "link_sheet_imports"):
        op.drop_table(table)
