"""
删除库存目录浏览已不再需要的重复排序索引。

generation 版 size/time 查询使用同一个升序 B-tree，PostgreSQL 可以反向扫描
满足 desc 排序，不需要额外维护 DESC 索引。
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260802_0001_library_index_children_index_cleanup"
down_revision = "20260801_0001_work_canonical_link_evidence"
branch_labels = None
depends_on = None


_OBSOLETE_INDEX_NAMES = (
    "idx_lie_children_name",
    "idx_lie_children_size",
    "idx_lie_children_size_desc",
    "idx_lie_children_time",
    "idx_lie_children_time_desc",
    "idx_lie_generation_children_size_desc",
    "idx_lie_generation_children_time_desc",
)


def _table_exists(bind, table_name: str) -> bool:
    return bool(bind.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"),
        {"name": table_name},
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "library_index_entries"):
        return

    with op.get_context().autocommit_block():
        autocommit_bind = op.get_bind()
        for index_name in _OBSOLETE_INDEX_NAMES:
            autocommit_bind.execute(
                text(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')
            )

    bind = op.get_bind()
    bind.execute(text("ANALYZE library_index_entries"))


def downgrade() -> None:
    # 降级不恢复重复索引，避免回滚业务代码时重新放大索引写入成本。
    return
