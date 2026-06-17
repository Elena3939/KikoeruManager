"""PostgreSQL baseline schema.

Revision ID: 0001_postgresql_baseline
Revises:
Create Date: 2026-06-12
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

from app.models.database import Base

revision = "0001_postgresql_baseline"
down_revision = None
branch_labels = None
depends_on = None

_TRIGRAM_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_summary_trgm ON activity_logs USING gin (COALESCE(summary, '') gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_source_path_trgm ON activity_logs USING gin (COALESCE(source_path, '') gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_rjcode_trgm ON activity_logs USING gin (COALESCE(rjcode, '') gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_task_id_trgm ON activity_logs USING gin (COALESCE(task_id, '') gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_batch_id_trgm ON activity_logs USING gin (COALESCE(batch_id, '') gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_library_index_search_text_trgm ON library_index_entries USING gin ((COALESCE(name, '') || ' ' || COALESCE(relative_path, '') || ' ' || COALESCE(rjcode, '') || ' ' || COALESCE(parent_path, '')) gin_trgm_ops) WITH (fastupdate = on, gin_pending_list_limit = 65536)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_searchable_text_trgm ON task_center_items USING gin (searchable_text gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_title_trgm ON task_center_items USING gin (title gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_business_key_trgm ON task_center_items USING gin (business_key gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_engine_task_id_trgm ON task_center_items USING gin (engine_task_id gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_processed_archives_filename_trgm ON processed_archives USING gin (filename gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_processed_archives_rjcode_trgm ON processed_archives USING gin (rjcode gin_trgm_ops)",
)

_BUSINESS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_activity_category_created_desc ON activity_logs(category, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_detail_session_id ON activity_logs((detail ->> 'session_id'))",
    "CREATE INDEX IF NOT EXISTS idx_activity_batch_created ON activity_logs(batch_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_session_created ON activity_logs(session_key, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_parent_created ON activity_logs(parent_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_task_created ON activity_logs(task_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_rj_category_status_created ON activity_logs(rjcode, category, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_activity_compact_scan ON activity_logs(created_at ASC, id ASC)",
    "CREATE INDEX IF NOT EXISTS idx_conflict_active_created ON conflict_works(created_at DESC) WHERE status IN ('PENDING', 'PROCESSING') AND conflict_type <> 'LINKED_SUBTITLE_IMPORT'",
    "CREATE INDEX IF NOT EXISTS idx_conflict_task_status ON conflict_works(task_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_conflict_rj_type_status ON conflict_works(rjcode, conflict_type, status)",
    "CREATE INDEX IF NOT EXISTS idx_lie_rj_lookup ON library_index_entries(rjcode, depth, relative_path, library_id, entry_type) WHERE rjcode IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_lie_rj_prefix ON library_index_entries(rjcode varchar_pattern_ops, depth, relative_path, library_id, entry_type) WHERE rjcode IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_lie_circle_dir_lookup ON library_index_entries(library_id, rjcode, relative_path, depth) WHERE entry_type = 'dir' AND rjcode IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_lie_indexed_at_id ON library_index_entries(library_id, indexed_at, id)",
    "CREATE INDEX IF NOT EXISTS idx_lie_children_name ON library_index_entries(library_id, parent_path, name_sort_key, relative_path)",
    "CREATE INDEX IF NOT EXISTS idx_lie_children_size ON library_index_entries(library_id, parent_path, size, name_sort_key, relative_path)",
    "CREATE INDEX IF NOT EXISTS idx_lie_children_size_desc ON library_index_entries(library_id, parent_path, size DESC, name_sort_key, relative_path)",
    "CREATE INDEX IF NOT EXISTS idx_lie_children_time ON library_index_entries(library_id, parent_path, mtime, name_sort_key, relative_path)",
    "CREATE INDEX IF NOT EXISTS idx_lie_children_time_desc ON library_index_entries(library_id, parent_path, mtime DESC NULLS LAST, name_sort_key, relative_path)",
    "CREATE INDEX IF NOT EXISTS idx_lie_subtree_path_pattern ON library_index_entries(library_id, relative_path text_pattern_ops)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_domain_status_updated_created ON task_center_items(domain, status, updated_at DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_domain_updated_created ON task_center_items(domain, updated_at DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_status_updated_created ON task_center_items(status, updated_at DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_updated_created ON task_center_items(updated_at DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_center_engine_updated ON task_center_items(engine_task_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_resource_updated ON asmr_resource_records(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_resource_download_updated ON asmr_resource_records(download_status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_resource_session_updated ON asmr_resource_records(session_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_resource_rj_updated ON asmr_resource_records(rjcode, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_session_status_priority_updated ON asmr_download_sessions(status, queue_priority, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_session_priority_updated ON asmr_download_sessions(queue_priority, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_asmr_session_updated ON asmr_download_sessions(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_processed_archives_processed_at_desc ON processed_archives(processed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_processed_archives_task_processed ON processed_archives(task_id, processed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_processed_archives_status_processed ON processed_archives(status, processed_at ASC)",
    "CREATE INDEX IF NOT EXISTS idx_password_upper_rjcode ON password_entries(upper(rjcode))",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    nested = bind.begin_nested()
    try:
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
        nested.commit()
    except Exception:
        nested.rollback()
    Base.metadata.create_all(bind=bind)
    bind.execute(text(
        """
        ALTER TABLE library_index_entries SET (
            autovacuum_analyze_scale_factor = 0.001,
            autovacuum_analyze_threshold = 500,
            autovacuum_vacuum_scale_factor = 0.005,
            autovacuum_vacuum_threshold = 1000
        )
        """
    ))
    for sql in _TRIGRAM_INDEX_SQL:
        bind.execute(text(sql))
    for sql in _BUSINESS_INDEX_SQL:
        bind.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        bind.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
    bind.execute(text("DROP EXTENSION IF EXISTS pg_stat_statements"))
    bind.execute(text("DROP EXTENSION IF EXISTS pg_trgm"))
