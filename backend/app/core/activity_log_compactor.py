"""操作记录归档压缩。

问题
====
- ``activity_logs.detail`` 是 JSON 列，业务侧塞了大量"全量"对象：
  - circle_completion: 单条平均 41KB，最大 485KB；
  - pipeline_filter:   单条平均 146KB，最大 660KB；
  - auto_import:       单条平均 7KB（带 file_tree_items / filtered_items）。
- 用户要求"保留所有操作记录可以回顾"，但**不需要**保留旧记录里的全量子数据（比如 200 条 file_tree、240 条 filtered_items），
  那些只在执行后第 1~7 天复盘有意义，过了就是死重量。

策略
====
- 不删除任何 ``activity_logs`` 行；只裁剪 ``detail`` 字段中体积大的列表 / 内嵌对象。
- 保留摘要类字段（``*_count`` / ``*_bytes`` / ``duration_ms`` / ``summary`` / 状态）；裁剪：
  - ``file_tree_items`` / ``filtered_items`` / ``items`` / ``succeeded_items`` / ``failed_items``
  - ``created_tasks`` / ``skipped_items`` / ``scan_targets`` / ``source_directories``
  - ``results`` / ``uploaded_files`` / ``selected_resources``
  - ``recovered_items`` / ``failed_targets`` / ``retry_targets``
  - ``batch_circle_summaries`` / ``circle_index_rows`` / ``circle_refresh_items``
  - ``pair_changes`` / ``manual_match_groups`` / ``crawl_results``
- 写入新字段 ``__compacted`` = True，``__compacted_at`` 标记，前端可视情况显示"已归档"小标签。
- 接口分批处理 + 时间预算，避免锁表。

适用阈值
========
- 默认压缩 30 天前的记录，且只压超过 8KB 的 detail。
- 最近的不动，便于复盘；阈值都可改。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

# detail 里可以裁剪的"大列表"字段。压缩时直接把这些键的内容删掉，并把长度记到 __compacted_lengths。
_COMPACTABLE_LIST_KEYS = (
    "file_tree_items",
    "filtered_items",
    "items",
    "succeeded_items",
    "failed_items",
    "attempted_items",
    "recovered_items",
    "failed_targets",
    "retry_targets",
    "created_tasks",
    "skipped_items",
    "scan_targets",
    "source_directories",
    "source_paths",
    "results",
    "uploaded_files",
    "selected_resources",
    "batch_circle_summaries",
    "circle_index_rows",
    "circle_refresh_items",
    "pair_changes",
    "manual_match_groups",
    "crawl_results",
    "child_rows",  # 合并算法运行时填充的，过期后没必要保留
)

# 大字符串字段（一般是错误堆栈 / 日志 dump）也限长
_COMPACTABLE_TEXT_KEYS = (
    "stack",
    "traceback",
    "raw_log",
    "raw_response",
    "raw_payload",
)
_TEXT_KEY_MAX_BYTES = 1024


def _compact_detail(detail: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, Dict[str, int]]:
    """对单行 detail 做就地裁剪，返回新 detail / 是否真的有改动 / 裁剪长度统计。"""
    if not isinstance(detail, dict):
        return detail, False, {}
    if detail.get("__compacted"):
        # 已经压缩过，跳过
        return detail, False, {}

    new_detail: Dict[str, Any] = {}
    lengths: Dict[str, int] = {}
    changed = False

    for key, value in detail.items():
        if key in _COMPACTABLE_LIST_KEYS and isinstance(value, list) and value:
            lengths[key] = len(value)
            changed = True
            continue
        if key in _COMPACTABLE_TEXT_KEYS and isinstance(value, str) and len(value.encode("utf-8")) > _TEXT_KEY_MAX_BYTES:
            new_detail[key] = value[: _TEXT_KEY_MAX_BYTES // 2] + "…[truncated]"
            changed = True
            continue
        new_detail[key] = value

    if changed:
        new_detail["__compacted"] = True
        new_detail["__compacted_at"] = datetime.now().isoformat()
        if lengths:
            new_detail["__compacted_lengths"] = lengths
    return new_detail, changed, lengths


def _detail_size_bytes(detail: Any) -> int:
    if not isinstance(detail, dict):
        return 0
    try:
        return len(json.dumps(detail, ensure_ascii=False, default=str))
    except Exception:
        return 0


def compact_old_activity_logs(
    *,
    older_than_days: int = 30,
    min_detail_bytes: int = 8 * 1024,
    max_rows: Optional[int] = None,
    chunk_size: int = 200,
    time_budget_seconds: float = 5.0,
) -> Dict[str, Any]:
    """分批压缩老的操作记录 detail。

    Args:
        older_than_days: 多老的记录可以压缩。默认 30 天前。
        min_detail_bytes: detail JSON 体积小于此值的不动（避免给小记录瞎折腾）。
        max_rows: 本次最多扫描多少行。None=直到耗尽 time_budget。
        chunk_size: 每批 SQL 加载行数。
        time_budget_seconds: 单次调用软上限。

    Returns:
        ``scanned/updated/skipped/failed/done/saved_bytes``
    """
    from ..models.database import ActivityLog, SessionLocal

    older_than_days = max(1, int(older_than_days or 30))
    min_detail_bytes = max(0, int(min_detail_bytes or 0))
    chunk_size = max(20, min(1000, int(chunk_size or 200)))
    deadline = time.monotonic() + max(1.0, float(time_budget_seconds))
    remaining = int(max_rows) if max_rows is not None else None

    cutoff = datetime.now() - timedelta(days=older_than_days)

    scanned = 0
    updated = 0
    skipped = 0
    failed = 0
    saved_bytes = 0
    last_cursor: Optional[tuple[datetime, str]] = None

    while True:
        if remaining is not None and remaining <= 0:
            break
        if time.monotonic() > deadline:
            break

        this_chunk = chunk_size
        if remaining is not None:
            this_chunk = min(this_chunk, remaining)

        db = SessionLocal()
        try:
            query = (
                db.query(ActivityLog)
                .filter(ActivityLog.created_at < cutoff)
                .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
            )
            if last_cursor is not None:
                # keyset 必须和 ORDER BY (created_at, id) 完全一致。
                # id 是 UUID，不能单独拿它做时间序分页游标，否则会跳过 created_at 更晚但 UUID 更小的旧记录。
                last_created_at, last_id = last_cursor
                query = query.filter(
                    or_(
                        ActivityLog.created_at > last_created_at,
                        (ActivityLog.created_at == last_created_at) & (ActivityLog.id > last_id),
                    )
                )
            rows = query.limit(this_chunk).all()
            if not rows:
                db.close()
                return {
                    "scanned": scanned,
                    "updated": updated,
                    "skipped": skipped,
                    "failed": failed,
                    "saved_bytes": saved_bytes,
                    "done": True,
                }

            for row in rows:
                scanned += 1
                if remaining is not None:
                    remaining -= 1
                last_cursor = (row.created_at, row.id)
                try:
                    detail = row.detail if isinstance(row.detail, dict) else None
                    if not detail:
                        skipped += 1
                        continue
                    if detail.get("__compacted"):
                        skipped += 1
                        continue
                    before = _detail_size_bytes(detail)
                    if before < min_detail_bytes:
                        skipped += 1
                        continue
                    new_detail, changed, _ = _compact_detail(detail)
                    if not changed:
                        skipped += 1
                        continue
                    after = _detail_size_bytes(new_detail)
                    saved_bytes += max(0, before - after)
                    row.detail = new_detail
                    flag_modified(row, "detail")
                    updated += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "[操作记录] 压缩 detail 失败 id=%s",
                        getattr(row, "id", None),
                        exc_info=True,
                    )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "saved_bytes": saved_bytes,
        "done": False,
    }


def estimate_compact_savings(
    *,
    older_than_days: int = 30,
    min_detail_bytes: int = 8 * 1024,
    sample_limit: int = 200,
) -> Dict[str, Any]:
    """快速估算压缩能省多少空间，不写表。在 Settings 页可以暴露给用户参考。

    会在符合条件的旧记录里采样最多 ``sample_limit`` 行，对采样行做"如果压缩"模拟，
    再按候选总数线性外推。
    """
    from ..models.database import ActivityLog, SessionLocal

    older_than_days = max(1, int(older_than_days or 30))
    min_detail_bytes = max(0, int(min_detail_bytes or 0))
    sample_limit = max(20, min(2000, int(sample_limit or 200)))

    cutoff = datetime.now() - timedelta(days=older_than_days)

    db = SessionLocal()
    try:
        candidate_total = (
            db.query(ActivityLog)
            .filter(ActivityLog.created_at < cutoff)
            .count()
        )
        sample_rows = (
            db.query(ActivityLog)
            .filter(ActivityLog.created_at < cutoff)
            .order_by(ActivityLog.created_at.desc())
            .limit(sample_limit)
            .all()
        )
        sample_count = len(sample_rows)
        sample_before_total = 0
        sample_after_total = 0
        compactable_count = 0
        for row in sample_rows:
            detail = row.detail if isinstance(row.detail, dict) else None
            if not detail or detail.get("__compacted"):
                continue
            before = _detail_size_bytes(detail)
            if before < min_detail_bytes:
                continue
            new_detail, changed, _ = _compact_detail(detail)
            if not changed:
                continue
            after = _detail_size_bytes(new_detail)
            sample_before_total += before
            sample_after_total += after
            compactable_count += 1

        if sample_count > 0 and compactable_count > 0:
            ratio = compactable_count / sample_count
            avg_save = (sample_before_total - sample_after_total) / compactable_count
            estimated_compactable = int(candidate_total * ratio)
            estimated_saved_bytes = int(estimated_compactable * avg_save)
        else:
            estimated_compactable = 0
            estimated_saved_bytes = 0

        return {
            "candidate_total": candidate_total,
            "sample_count": sample_count,
            "compactable_in_sample": compactable_count,
            "sample_before_bytes": sample_before_total,
            "sample_after_bytes": sample_after_total,
            "estimated_compactable_total": estimated_compactable,
            "estimated_saved_bytes": estimated_saved_bytes,
            "older_than_days": older_than_days,
            "min_detail_bytes": min_detail_bytes,
        }
    finally:
        db.close()
