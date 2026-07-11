"""Expand library index consistency schema.

Revision ID: 20260710_0001_library_index_consistency
Revises: 20260709_0001_bonus_probe_mode_width
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260710_0001_library_index_consistency"
down_revision = "20260709_0001_bonus_probe_mode_width"
branch_labels = None
depends_on = None


_ENTRY_INDEX_SQL = (
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_library_generation_rel ON library_index_entries(library_id, generation, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_rj_lookup ON library_index_entries(rjcode, library_id, generation, depth, relative_path, entry_type) WHERE rjcode IS NOT NULL",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_rj_prefix ON library_index_entries(rjcode varchar_pattern_ops, library_id, generation, depth, relative_path, entry_type) WHERE rjcode IS NOT NULL",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_circle_dir ON library_index_entries(library_id, generation, rjcode, relative_path, depth) WHERE entry_type = 'dir' AND rjcode IS NOT NULL",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_indexed_at ON library_index_entries(library_id, generation, indexed_at, id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_children_name ON library_index_entries(library_id, generation, parent_path, name_sort_key, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_children_size ON library_index_entries(library_id, generation, parent_path, size, name_sort_key, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_children_size_desc ON library_index_entries(library_id, generation, parent_path, size DESC, name_sort_key, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_children_time ON library_index_entries(library_id, generation, parent_path, mtime, name_sort_key, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_children_time_desc ON library_index_entries(library_id, generation, parent_path, mtime DESC NULLS LAST, name_sort_key, relative_path)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_subtree_path ON library_index_entries(library_id, generation, relative_path text_pattern_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_generation_materialized_seq ON library_index_entries(library_id, generation, materialized_seq, id)",
)


_ENTRY_INDEX_NAMES = tuple(
    sql.split(" IF NOT EXISTS ", 1)[1].split(" ON ", 1)[0]
    for sql in _ENTRY_INDEX_SQL
)

_LEGACY_UNIQUE_INDEX_NAME = "idx_lie_library_rel"
_LEGACY_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_lie_library_rel "
    "ON library_index_entries(library_id, relative_path)"
)


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table_name}).scalar())


def _prepare_concurrent_index(bind, index_name: str) -> None:
    """清理上次中断留下的 invalid index，否则 IF NOT EXISTS 会永久跳过重建。"""
    state = bind.execute(
        text("""
            SELECT i.indisvalid, i.indisready
              FROM pg_class AS index_class
              JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace
              JOIN pg_index AS i ON i.indexrelid = index_class.oid
             WHERE namespace.nspname = current_schema()
               AND index_class.relname = :index_name
        """),
        {"index_name": index_name},
    ).mappings().first()
    if state and (not bool(state["indisvalid"]) or not bool(state["indisready"])):
        bind.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'))


def _ensure_legacy_unique_index_for_downgrade(bind) -> None:
    duplicate = bind.execute(text("""
        SELECT library_id, relative_path
          FROM library_index_entries
         GROUP BY library_id, relative_path
        HAVING COUNT(*) > 1
         LIMIT 1
    """)).first()
    if duplicate is not None:
        raise RuntimeError(
            "库存索引 downgrade 前必须先删除非 active generation；"
            "当前存在跨 generation 的重复路径，无法恢复旧二列唯一索引"
        )
    _prepare_concurrent_index(bind, _LEGACY_UNIQUE_INDEX_NAME)
    bind.execute(text(_LEGACY_UNIQUE_INDEX_SQL))


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "library_index_entries"):
        bind.execute(text("ALTER TABLE library_index_entries ADD COLUMN IF NOT EXISTS generation INTEGER DEFAULT 1"))
        bind.execute(text("ALTER TABLE library_index_entries ADD COLUMN IF NOT EXISTS materialized_seq BIGINT DEFAULT 0"))
        bind.execute(text("""
            UPDATE library_index_entries
               SET generation = COALESCE(generation, 1),
                   materialized_seq = COALESCE(materialized_seq, 0)
             WHERE generation IS NULL OR materialized_seq IS NULL
        """))
        bind.execute(text("""
            ALTER TABLE library_index_entries
                ALTER COLUMN generation SET DEFAULT 1,
                ALTER COLUMN generation SET NOT NULL,
                ALTER COLUMN materialized_seq SET DEFAULT 0,
                ALTER COLUMN materialized_seq SET NOT NULL
        """))

    if _table_exists(bind, "library_index_status"):
        status_columns = (
            ("accepted_seq", "BIGINT DEFAULT 0"),
            ("materialized_seq", "BIGINT DEFAULT 0"),
            ("state_revision", "BIGINT DEFAULT 0"),
            ("view_revision", "BIGINT DEFAULT 0"),
            ("active_generation", "INTEGER DEFAULT 1"),
            ("building_generation", "INTEGER"),
            ("catchup_state", "VARCHAR(24) DEFAULT 'idle'"),
            ("last_operation_id", "VARCHAR(36)"),
            ("materializer_owner", "VARCHAR(120)"),
            ("materializer_lease_until", "TIMESTAMP WITHOUT TIME ZONE"),
            ("materializer_epoch", "BIGINT DEFAULT 0"),
            ("blocked_seq", "BIGINT"),
            ("catchup_error", "TEXT"),
        )
        for column_name, column_sql in status_columns:
            bind.execute(text(
                f"ALTER TABLE library_index_status ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
            ))
        bind.execute(text("""
            UPDATE library_index_status
               SET accepted_seq = COALESCE(accepted_seq, 0),
                   materialized_seq = COALESCE(materialized_seq, 0),
                   state_revision = COALESCE(state_revision, 0),
                   view_revision = COALESCE(view_revision, 0),
                   active_generation = COALESCE(active_generation, 1),
                   catchup_state = COALESCE(NULLIF(catchup_state, ''), 'idle'),
                   materializer_epoch = COALESCE(materializer_epoch, 0)
        """))
        bind.execute(text("""
            ALTER TABLE library_index_status
                ALTER COLUMN accepted_seq SET DEFAULT 0,
                ALTER COLUMN accepted_seq SET NOT NULL,
                ALTER COLUMN materialized_seq SET DEFAULT 0,
                ALTER COLUMN materialized_seq SET NOT NULL,
                ALTER COLUMN state_revision SET DEFAULT 0,
                ALTER COLUMN state_revision SET NOT NULL,
                ALTER COLUMN view_revision SET DEFAULT 0,
                ALTER COLUMN view_revision SET NOT NULL,
                ALTER COLUMN active_generation SET DEFAULT 1,
                ALTER COLUMN active_generation SET NOT NULL,
                ALTER COLUMN catchup_state SET DEFAULT 'idle',
                ALTER COLUMN catchup_state SET NOT NULL,
                ALTER COLUMN materializer_epoch SET DEFAULT 0,
                ALTER COLUMN materializer_epoch SET NOT NULL
        """))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS library_index_mutation_operations (
            operation_id VARCHAR(36) PRIMARY KEY,
            idempotency_key VARCHAR(255) NOT NULL,
            request_fingerprint VARCHAR(128) NOT NULL,
            kind VARCHAR(40) NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'prepared',
            planned_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
            actual_result JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT,
            prepared_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            filesystem_started_at TIMESTAMP WITHOUT TIME ZONE,
            finalized_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_li_mutation_operations_fingerprint_nonempty CHECK (request_fingerprint <> '')
        )
    """))
    bind.execute(text("""
        ALTER TABLE library_index_mutation_operations
            ADD COLUMN IF NOT EXISTS filesystem_started_at TIMESTAMP WITHOUT TIME ZONE
    """))
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS library_index_mutation_ledger (
            id BIGSERIAL PRIMARY KEY,
            operation_id VARCHAR(36) NOT NULL REFERENCES library_index_mutation_operations(operation_id) ON DELETE CASCADE,
            library_id VARCHAR(60) NOT NULL,
            seq BIGINT NOT NULL,
            kind VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMP WITHOUT TIME ZONE,
            applied_at TIMESTAMP WITHOUT TIME ZONE,
            error TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS library_index_mutation_effects (
            id BIGSERIAL PRIMARY KEY,
            ledger_id BIGINT NOT NULL REFERENCES library_index_mutation_ledger(id) ON DELETE CASCADE,
            operation_id VARCHAR(36) NOT NULL REFERENCES library_index_mutation_operations(operation_id) ON DELETE CASCADE,
            library_id VARCHAR(60) NOT NULL,
            seq BIGINT NOT NULL,
            effect_no INTEGER NOT NULL,
            kind VARCHAR(24) NOT NULL,
            relative_path TEXT NOT NULL,
            scope VARCHAR(12) NOT NULL DEFAULT 'exact',
            target_library_id VARCHAR(60),
            target_path TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS library_index_pending_masks (
            id BIGSERIAL PRIMARY KEY,
            operation_id VARCHAR(36) NOT NULL REFERENCES library_index_mutation_operations(operation_id) ON DELETE CASCADE,
            library_id VARCHAR(60) NOT NULL,
            ledger_seq BIGINT,
            effect_no INTEGER NOT NULL,
            kind VARCHAR(24) NOT NULL,
            relative_path TEXT NOT NULL,
            scope VARCHAR(12) NOT NULL DEFAULT 'exact',
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS library_index_generations (
            id BIGSERIAL PRIMARY KEY,
            library_id VARCHAR(60) NOT NULL,
            generation INTEGER NOT NULL,
            state VARCHAR(24) NOT NULL DEFAULT 'building',
            build_base_seq BIGINT NOT NULL DEFAULT 0,
            reconciled_seq BIGINT NOT NULL DEFAULT 0,
            total_entries INTEGER NOT NULL DEFAULT 0,
            total_size_bytes BIGINT NOT NULL DEFAULT 0,
            folder_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            scan_completed_at TIMESTAMP WITHOUT TIME ZONE,
            cutover_at TIMESTAMP WITHOUT TIME ZONE,
            retired_at TIMESTAMP WITHOUT TIME ZONE,
            delete_after TIMESTAMP WITHOUT TIME ZONE,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    index_sql = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_mutation_operations_idempotency ON library_index_mutation_operations(idempotency_key)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_operations_state_updated ON library_index_mutation_operations(state, updated_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_mutation_ledger_library_seq ON library_index_mutation_ledger(library_id, seq)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_mutation_ledger_operation_library ON library_index_mutation_ledger(operation_id, library_id)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_ledger_pending ON library_index_mutation_ledger(library_id, applied_at, seq)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_ledger_retry ON library_index_mutation_ledger(next_retry_at, library_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_ledger_retention ON library_index_mutation_ledger(applied_at, id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_mutation_effects_ledger_no ON library_index_mutation_effects(ledger_id, effect_no)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_effects_library_seq ON library_index_mutation_effects(library_id, seq, effect_no)",
        "CREATE INDEX IF NOT EXISTS idx_li_mutation_effects_path ON library_index_mutation_effects(library_id, relative_path)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_pending_masks_operation_effect ON library_index_pending_masks(operation_id, library_id, effect_no)",
        "CREATE INDEX IF NOT EXISTS idx_li_pending_masks_active_path ON library_index_pending_masks(library_id, relative_path, scope)",
        "CREATE INDEX IF NOT EXISTS idx_li_pending_masks_ledger_seq ON library_index_pending_masks(library_id, ledger_seq)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_li_generations_library_generation ON library_index_generations(library_id, generation)",
        "CREATE INDEX IF NOT EXISTS idx_li_generations_state_updated ON library_index_generations(state, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_li_generations_delete_after ON library_index_generations(delete_after, id)",
    )
    for sql in index_sql:
        bind.execute(text(sql))

    if _table_exists(bind, "library_index_status"):
        bind.execute(text("""
            INSERT INTO library_index_status(
                library_id,
                status,
                watcher_mode,
                total_entries,
                total_size_bytes,
                folder_count,
                accepted_seq,
                materialized_seq,
                state_revision,
                view_revision,
                active_generation,
                catchup_state,
                materializer_epoch,
                updated_at
            )
            SELECT entries.library_id,
                   'ready',
                   'disabled',
                   COUNT(*)::integer,
                   COALESCE(SUM(CASE WHEN entries.entry_type = 'file' THEN entries.size ELSE 0 END), 0),
                   COUNT(*) FILTER (
                       WHERE entries.entry_type = 'dir'
                         AND entries.relative_path <> ''
                         AND COALESCE(entries.parent_path, '') = ''
                   )::integer,
                   0,
                   0,
                   0,
                   0,
                   1,
                   'idle',
                   0,
                   (EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) * 1000)::bigint
              FROM library_index_entries AS entries
             GROUP BY entries.library_id
            ON CONFLICT (library_id) DO NOTHING
        """))
        bind.execute(text("""
            INSERT INTO library_index_generations(
                library_id,
                generation,
                state,
                build_base_seq,
                reconciled_seq,
                total_entries,
                total_size_bytes,
                folder_count,
                created_at,
                updated_at
            )
            SELECT status.library_id,
                   status.active_generation,
                   'active',
                   status.materialized_seq,
                   status.materialized_seq,
                   COALESCE(status.total_entries, 0),
                   COALESCE(status.total_size_bytes, 0),
                   COALESCE(status.folder_count, 0),
                   CURRENT_TIMESTAMP,
                   CURRENT_TIMESTAMP
              FROM library_index_status AS status
            ON CONFLICT (library_id, generation) DO NOTHING
        """))

    if _table_exists(bind, "library_index_entries"):
        # 大库存表使用在线索引，expand 阶段明确保留 idx_lie_library_rel。
        with op.get_context().autocommit_block():
            autocommit_bind = op.get_bind()
            for index_name, sql in zip(_ENTRY_INDEX_NAMES, _ENTRY_INDEX_SQL):
                _prepare_concurrent_index(autocommit_bind, index_name)
                autocommit_bind.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "library_index_entries"):
        with op.get_context().autocommit_block():
            autocommit_bind = op.get_bind()
            _ensure_legacy_unique_index_for_downgrade(autocommit_bind)
            for index_name in reversed(_ENTRY_INDEX_NAMES):
                autocommit_bind.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'))

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS library_index_pending_masks CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS library_index_mutation_effects CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS library_index_mutation_ledger CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS library_index_mutation_operations CASCADE"))
    bind.execute(text("DROP TABLE IF EXISTS library_index_generations CASCADE"))

    if _table_exists(bind, "library_index_status"):
        for column_name in (
            "catchup_error",
            "blocked_seq",
            "materializer_epoch",
            "materializer_lease_until",
            "materializer_owner",
            "last_operation_id",
            "catchup_state",
            "building_generation",
            "active_generation",
            "view_revision",
            "state_revision",
            "materialized_seq",
            "accepted_seq",
        ):
            bind.execute(text(f"ALTER TABLE library_index_status DROP COLUMN IF EXISTS {column_name}"))
    if _table_exists(bind, "library_index_entries"):
        bind.execute(text("ALTER TABLE library_index_entries DROP COLUMN IF EXISTS materialized_seq"))
        bind.execute(text("ALTER TABLE library_index_entries DROP COLUMN IF EXISTS generation"))
