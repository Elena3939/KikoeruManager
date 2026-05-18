"""activity_log_aggregator 的 orchestrator（主流程）。

Phase 4B 第 4 步：把纯辅助函数拆到 ``_helpers``，本文件只保留 merge_activity_rows
的顺序编排：helper 调用 + 各 domain pass。Pass 之间通过局部闭包变量（``rows`` /
``merged_*_ids`` / ``*_by_id`` 等 20+ 个共享容器）交接状态。

Pass 顺序（不可随意重排，按被动依赖顺序编排）：
1. to_dict + category_label 填充
2. import 恢复标记（latest_import_success_by_key 消费）
3. subtitle_crawl 批次聚合 + 父子关系构建
4. auto_import / process_existing 批次聚合（真 batch_start + synthetic）
5. subtitle_import 预处理索引
6. pipeline_rename / pipeline_delete 的 key / batch / session 索引
7. subtitle_pair 合并（消费第 3、5 步的映射）
8. subtitle_import 合并（消费第 5 步）
9. pipeline_rename 合并（key cluster + batch）
10. pipeline_delete 合并（key cluster + batch + time cluster）
11. pipeline_filter 合并（retry session、preview pairing）
12. circle_completion 合并
13. asmr_sync 合并
14. 未被 merged 的 rows → items 输出

后续拆子模块时，每个 pass 应该提取为 ``pass_xxx(ctx)`` 接收 MergeContext；
当前先把 helpers 抽出来作为第一步。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..activity_log_service import CATEGORY_LABELS
from ._helpers import (
    _coerce_dt,
    _format_bytes_short,
    _format_duration_short,
    _make_tree_child,
    _append_tree_child,
    _walk_tree_rows,
    _max_tree_activity,
    _is_success_status,
    _is_failed_status,
    _common_path_prefix,
    _coalesce_import_batch_rows,
    _import_row_match_key,
    _build_latest_import_success_map,
    _is_recovered_import_failure,
    _is_successful_pair_state,
    _recompute_subtitle_batch_rollup,
)

__all__ = ["merge_activity_rows", "merge_activity_rows_from_dicts"]


def merge_activity_rows(raw_rows: List[Any]) -> List[Dict[str, Any]]:
    """合并原始 ActivityLog ORM 行为前端需要的合并结构。

    入参是带 ``to_dict()`` 方法的 ORM 行列表（通常是 ``models.ActivityLog``）。
    具体 domain 合并规则保持从 routes.py 搬迁过来的原貌，详见模块 docstring。
    """
    return merge_activity_rows_from_dicts([row.to_dict() for row in raw_rows])


def merge_activity_rows_from_dicts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同 ``merge_activity_rows``，但直接接 dict 列表入参，省掉 to_dict 步骤。

    给调用方自己管理行级缓存（writer 层的 row_dict_cache）时用：列表接口可以在
    ORM 反序列化前就用缓存命中，只对未命中的 id 批量实体化 ORM 对象，极大降低
    首屏 JSON 反序列化成本。入参 ``rows`` 的顺序即输出 ``items`` 的候选顺序。
    """
    rows = [dict(row) for row in rows]
    for row in rows:
        row["category_label"] = CATEGORY_LABELS.get(row.get("category"), row.get("category"))

    crawl_by_task: dict[str, dict[str, Any]] = {}
    crawl_rows_by_task: dict[str, list[dict[str, Any]]] = {}
    pair_rows_by_task: dict[str, list[dict[str, Any]]] = {}
    merged_pair_ids: set[str] = set()
    merged_filter_preview_ids: set[str] = set()
    merged_filter_retry_ids: set[str] = set()
    merged_subtitle_import_ids: set[str] = set()
    merged_import_batch_child_ids: set[str] = set()
    import_batch_child_rows_by_source_id: dict[str, dict[str, Any]] = {}

    latest_import_success_by_key = _build_latest_import_success_map(rows)

    for row in rows:
        if str(row.get("category") or "").strip() not in {"auto_import", "process_existing"}:
            continue
        if not _is_failed_status(row.get("status")):
            continue
        if not _is_recovered_import_failure(row, latest_import_success_by_key):
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        row["detail"] = {
            **detail,
            "recovered_by_success": True,
            "recovered_badge": "已覆盖",
        }
        row["recovered_badge"] = "已覆盖"

    for row in rows:
        if row.get("category") == "subtitle_crawl" and row.get("task_id"):
            task_id = str(row["task_id"])
            crawl_by_task.setdefault(task_id, row)
            crawl_rows_by_task.setdefault(task_id, []).append(row)
        elif row.get("category") == "subtitle_pair" and row.get("task_id"):
            task_id = str(row["task_id"])
            pair_rows_by_task.setdefault(task_id, []).append(row)

    superseded_crawl_ids: set[str] = set()
    for task_id, crawl_rows in crawl_rows_by_task.items():
        ordered_crawls = sorted(crawl_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        if not ordered_crawls:
            continue
        root_row = ordered_crawls[0]
        root_detail = root_row.get("detail") if isinstance(root_row.get("detail"), dict) else {}
        latest_activity = _coerce_dt(root_row.get("created_at")) or datetime.min
        child_rows: list[dict[str, Any]] = []
        rerun_child_map: dict[str, dict[str, Any]] = {}

        for rerun_index, crawl_row in enumerate(ordered_crawls[1:], start=1):
            child = {
                "id": str(crawl_row.get("id") or f"{task_id}-rerun-{rerun_index}"),
                "relation": "rerun",
                "category": crawl_row.get("category"),
                "category_label": "字幕爬取",
                "action": crawl_row.get("action"),
                "status": crawl_row.get("status"),
                "summary": crawl_row.get("summary"),
                "created_at": crawl_row.get("created_at"),
                "source_path": crawl_row.get("source_path"),
                "rjcode": crawl_row.get("rjcode"),
                "detail": crawl_row.get("detail") if isinstance(crawl_row.get("detail"), dict) else {},
                "child_rows": [],
            }
            child_rows.append(child)
            rerun_child_map[str(crawl_row.get("id") or "")] = child
            superseded_crawl_ids.add(str(crawl_row.get("id") or ""))
            latest_activity = max(latest_activity, _coerce_dt(crawl_row.get("created_at")) or datetime.min)

        for pair_row in sorted(pair_rows_by_task.get(task_id, []), key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min):
            pair_dt = _coerce_dt(pair_row.get("created_at")) or datetime.min
            attach_child_list = child_rows
            attach_crawl = root_row
            for crawl_row in ordered_crawls[1:]:
                crawl_dt = _coerce_dt(crawl_row.get("created_at")) or datetime.min
                if crawl_dt <= pair_dt:
                    attach_crawl = crawl_row
            if attach_crawl is not root_row:
                attach_child_list = rerun_child_map.get(str(attach_crawl.get("id") or ""), {}).get("child_rows", child_rows)
            attach_child_list.append({
                "id": str(pair_row.get("id") or f"{task_id}-pair-{pair_dt.isoformat()}"),
                "relation": "pair",
                "category": pair_row.get("category"),
                "category_label": "字幕配对",
                "action": pair_row.get("action"),
                "status": pair_row.get("status"),
                "summary": pair_row.get("summary"),
                "created_at": pair_row.get("created_at"),
                "source_path": pair_row.get("source_path"),
                "rjcode": pair_row.get("rjcode"),
                "detail": pair_row.get("detail") if isinstance(pair_row.get("detail"), dict) else {},
                "child_rows": [],
            })
            merged_pair_ids.add(str(pair_row.get("id") or ""))
            latest_activity = max(latest_activity, pair_dt)

        if child_rows:
            root_row["detail"] = {
                **root_detail,
                "child_rows": child_rows,
                "child_row_count": len(child_rows),
                "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at"),
            }
            root_row["has_child_rows"] = True
            root_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at")
            root_row["rerun"] = len(ordered_crawls) > 1

    merged_batch_child_ids: set[str] = set()
    batch_rows_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        if row.get("category") == "subtitle_crawl" and row.get("action") == "batch_start":
            batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
            if batch_id:
                batch_rows_by_id[batch_id] = row

    for batch_id, batch_row in batch_rows_by_id.items():
        batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
        child_rows: list[dict[str, Any]] = []
        latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id == str(batch_row.get("id") or ""):
                continue
            if row_id in superseded_crawl_ids or row_id in merged_pair_ids:
                continue
            if row.get("category") != "subtitle_crawl":
                continue
            if row.get("action") == "batch_start":
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            if str(detail.get("batch_id") or "").strip() != batch_id:
                continue
            child_rows.append(row)
            merged_batch_child_ids.add(row_id)
            latest_activity = max(
                latest_activity,
                _coerce_dt(row.get("latest_activity_at") or row.get("created_at")) or datetime.min,
            )
        if child_rows:
            ordered_child_rows = sorted(
                child_rows,
                key=lambda item: _coerce_dt(item.get("latest_activity_at") or item.get("created_at")) or datetime.min
            )
            descendant_rows = _walk_tree_rows(ordered_child_rows)
            crawl_descendants = [
                item for item in descendant_rows
                if str(item.get("category") or "").strip() == "subtitle_crawl"
            ]
            pair_descendants = [
                item for item in descendant_rows
                if str(item.get("relation") or "").strip() == "pair"
                or str(item.get("category") or "").strip() == "subtitle_pair"
            ]
            paired_child_count = sum(
                1
                for item in crawl_descendants
                if any(
                    str(pair_item.get("status") or "").strip() == "success"
                    and (
                        str(pair_item.get("rjcode") or "").strip().upper()
                        == str(item.get("rjcode") or "").strip().upper()
                        or (
                            str(pair_item.get("source_path") or "").strip()
                            and str(pair_item.get("source_path") or "").strip()
                            == str(item.get("source_path") or "").strip()
                        )
                    )
                    for pair_item in pair_descendants
                )
            )
            awaiting_manual_child_count = sum(
                1
                for item in crawl_descendants
                if bool((item.get("detail") if isinstance(item.get("detail"), dict) else {}).get("awaiting_manual_match"))
            )
            unpaired_child_count = max(0, len(crawl_descendants) - paired_child_count)
            latest_pair_row = None
            for pair_item in sorted(pair_descendants, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min):
                if str(pair_item.get("status") or "").strip() == "success":
                    latest_pair_row = pair_item
            batch_row["detail"] = {
                **batch_detail,
                "child_rows": ordered_child_rows,
                "child_row_count": len(child_rows),
                "paired_child_count": paired_child_count,
                "awaiting_manual_child_count": awaiting_manual_child_count,
                "unpaired_child_count": unpaired_child_count,
                "pair_linked": bool(latest_pair_row),
                "pair_status": str(latest_pair_row.get("status") or "").strip() if latest_pair_row else "",
                "pair_summary": str(latest_pair_row.get("summary") or "").strip() if latest_pair_row else "",
                "pair_created_at": latest_pair_row.get("created_at") if latest_pair_row else "",
                "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at"),
            }
            batch_row["has_child_rows"] = True
            batch_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at")
            if latest_pair_row:
                batch_row["merged_pair"] = True
                batch_row["merged_pair_status"] = str(latest_pair_row.get("status") or "").strip()

    import_batch_rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("action") != "batch_start":
            continue
        if row.get("category") not in {"auto_import", "process_existing"}:
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
        if batch_id:
            import_batch_rows_by_key[(str(row.get("category") or "").strip(), batch_id)] = row

    synthetic_import_batch_keys: set[tuple[str, str]] = set()
    for row in rows:
        category_key = str(row.get("category") or "").strip()
        if category_key not in {"auto_import", "process_existing"}:
            continue
        if str(row.get("action") or "").strip() == "batch_start":
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        batch_id = str(detail.get("batch_id") or detail.get("session_id") or "").strip()
        if not batch_id:
            continue
        batch_key = (category_key, batch_id)
        if batch_key in import_batch_rows_by_key:
            continue

        source_action = str(
            detail.get("batch_source_action")
            or detail.get("source_action")
            or ""
        ).strip()
        source_label = str(
            detail.get("batch_source_label")
            or detail.get("source_label")
            or ""
        ).strip()
        source_page = str(
            detail.get("batch_source_page")
            or detail.get("source_page")
            or ""
        ).strip()

        synthetic_row = {
            "id": f"synthetic-import-batch:{category_key}:{batch_id}",
            "category": category_key,
            "category_label": CATEGORY_LABELS.get(category_key, category_key),
            "action": "batch_start",
            "status": "incomplete",
            "summary": "批量任务自动聚合",
            "task_id": batch_id,
            "source_path": str(row.get("source_path") or "").strip() or None,
            "rjcode": None,
            "created_at": row.get("created_at"),
            "latest_activity_at": row.get("created_at"),
            "detail": {
                "mode": "import_batch_start_synthetic",
                "batch_id": batch_id,
                "requested_count": 0,
                "created_count": 0,
                "archive_count": 0,
                "extracted_count": 0,
                "source_action": source_action or None,
                "source_label": source_label or None,
                "source_page": source_page or None,
                "source_paths": [],
                "created_tasks": [],
                "synthetic_parent": True,
            },
        }
        import_batch_rows_by_key[batch_key] = synthetic_row
        synthetic_import_batch_keys.add(batch_key)

    for (category_key, batch_id), batch_row in import_batch_rows_by_key.items():
        batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
        child_rows: list[dict[str, Any]] = []
        latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
        batch_created_at = _coerce_dt(batch_row.get("created_at")) or datetime.min
        extract_completed_count = 0
        extract_output_total = 0
        archive_size_total = 0
        batch_created_task_ids = {
            str(item.get("task_id") or "").strip()
            for item in (batch_detail.get("created_tasks") or [])
            if isinstance(item, dict) and str(item.get("task_id") or "").strip()
        }
        batch_source_paths = {
            str(path).strip()
            for path in (batch_detail.get("source_paths") or [])
            if str(path).strip()
        }
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id == str(batch_row.get("id") or ""):
                continue
            if str(row.get("category") or "").strip() != category_key:
                continue
            if str(row.get("action") or "").strip() == "batch_start":
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            row_batch_id = str(detail.get("batch_id") or "").strip()
            row_task_id = str(row.get("task_id") or "").strip()
            row_source_path = str(row.get("source_path") or "").strip()
            row_created_at = _coerce_dt(row.get("created_at")) or datetime.min
            matched_by_batch_id = bool(row_batch_id) and row_batch_id == batch_id
            matched_by_created_task = bool(row_task_id) and row_task_id in batch_created_task_ids
            matched_by_source_path_fallback = False
            if (
                not matched_by_batch_id
                and not matched_by_created_task
                and not batch_created_task_ids
                and row_source_path
                and row_source_path in batch_source_paths
                and batch_created_at != datetime.min
                and row_created_at != datetime.min
            ):
                fallback_seconds = abs((row_created_at - batch_created_at).total_seconds())
                matched_by_source_path_fallback = fallback_seconds <= 1800
            matched_by_parent_manifest = matched_by_created_task or matched_by_source_path_fallback
            if not matched_by_batch_id and not matched_by_parent_manifest:
                continue
            merged_import_batch_child_ids.add(row_id)
            child_row = _make_tree_child(
                row,
                relation="import_item",
                category_label="子解压任务" if category_key == "auto_import" else "子处理任务",
            )
            child_rows.append(child_row)
            import_batch_child_rows_by_source_id[row_id] = child_rows[-1]
            if str(row.get("status") or "").strip() in {"success", "completed"}:
                extract_completed_count += 1
            extract_output_total += int(detail.get("extract_output_bytes") or 0)
            archive_size_total += int(detail.get("archive_size_bytes") or 0)
            latest_activity = max(
                latest_activity,
                _coerce_dt(row.get("latest_activity_at") or row.get("created_at")) or datetime.min,
            )
        if child_rows:
            child_rows = _coalesce_import_batch_rows(child_rows)
            extract_completed_count = sum(1 for item in child_rows if _is_success_status(item.get("status")))
            failed_child_count = sum(
                1 for item in child_rows
                if _is_failed_status(item.get("status"))
                and not bool(((item.get("detail") if isinstance(item.get("detail"), dict) else {}) or {}).get("recovered_by_success"))
            )
            partial_child_count = sum(1 for item in child_rows if str(item.get("status") or "").strip() == "partial_success")
            latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
            earliest_child_activity = datetime.max
            max_child_duration_ms = 0
            latest_child_completed_at = datetime.min
            for item in child_rows:
                item_created_at = _coerce_dt(item.get("created_at"))
                item_latest_at = _coerce_dt(item.get("latest_activity_at") or item.get("created_at")) or datetime.min
                latest_activity = max(latest_activity, item_latest_at)
                if item_created_at:
                    earliest_child_activity = min(earliest_child_activity, item_created_at)
                item_detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
                item_duration_ms = int(item_detail.get("duration_ms") or 0)
                max_child_duration_ms = max(max_child_duration_ms, item_duration_ms)
                if item_created_at and item_duration_ms > 0:
                    item_completed_at = item_created_at + timedelta(milliseconds=item_duration_ms)
                    latest_child_completed_at = max(latest_child_completed_at, item_completed_at)
            batch_duration_ms = 0
            duration_end_at = latest_child_completed_at if latest_child_completed_at != datetime.min else latest_activity
            if earliest_child_activity != datetime.max and duration_end_at != datetime.min and duration_end_at >= earliest_child_activity:
                batch_duration_ms = int((duration_end_at - earliest_child_activity).total_seconds() * 1000)
            batch_duration_ms = max(batch_duration_ms, max_child_duration_ms)

            if failed_child_count > 0 and extract_completed_count > 0:
                batch_row["status"] = "partial_success"
            elif failed_child_count > 0:
                batch_row["status"] = "failed"
            elif partial_child_count > 0:
                batch_row["status"] = "partial_success"
            else:
                batch_row["status"] = "success"

            summary_parts = []
            requested_count = int(batch_detail.get("requested_count") or len(child_rows) or 0)
            archive_count = int(batch_detail.get("archive_count") or requested_count or 0)
            if (category_key, batch_id) in synthetic_import_batch_keys:
                requested_count = max(requested_count, len(child_rows))
                archive_count = max(archive_count, len(child_rows))
            if requested_count > 0:
                summary_parts.append(f"候选 {requested_count} 个")
            if archive_count > 0:
                summary_parts.append(f"压缩包 {archive_count} 个")
            if extract_completed_count > 0:
                summary_parts.append(f"已提交解压 {extract_completed_count} 个")
            if failed_child_count > 0:
                summary_parts.append(f"失败 {failed_child_count} 个")
            if batch_duration_ms > 0:
                total_seconds = max(0, int(round(batch_duration_ms / 1000)))
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                summary_parts.append(f"耗时 {minutes} 分 {seconds} 秒" if minutes else f"耗时 {seconds} 秒")
            batch_row["summary"] = f"{'批量创建解压任务' if category_key == 'auto_import' else '批量创建已有目录处理任务'}，{'，'.join(summary_parts)}"
            batch_row["detail"] = {
                **batch_detail,
                "child_rows": sorted(
                    child_rows,
                    key=lambda item: _coerce_dt(item.get("latest_activity_at") or item.get("created_at")) or datetime.min
                ),
                "child_row_count": len(child_rows),
                "extract_completed_count": extract_completed_count,
                "failed_child_count": failed_child_count,
                "partial_child_count": partial_child_count,
                "aggregate_extract_output_bytes": extract_output_total,
                "aggregate_archive_size_bytes": archive_size_total,
                "batch_duration_ms": batch_duration_ms,
                "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at"),
            }
            batch_row["has_child_rows"] = True
            batch_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at")
            # 没有真实 batch_start 锚点但有 batch_id 的 import 行，会生成 synthetic 父行；
            # 这里补齐把它塞进主 rows，否则子行已被标 merged，父行又不进输出，整个批次就消失了。
            if (category_key, batch_id) in synthetic_import_batch_keys:
                rows.append(batch_row)

    auto_import_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("category") == "auto_import":
            auto_import_rows.append(row)

    subtitle_import_rows: list[dict[str, Any]] = []
    subtitle_import_by_task: dict[str, dict[str, Any]] = {}
    subtitle_import_rows_by_rj: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("category") != "subtitle_import":
            continue
        subtitle_import_rows.append(row)
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        import_task_id = str(detail.get("task_id") or row.get("task_id") or "").strip()
        if import_task_id:
            subtitle_import_by_task.setdefault(import_task_id, row)
        import_rj = str(
            row.get("rjcode")
            or detail.get("target_rjcode")
            or detail.get("source_rjcode")
            or ""
        ).strip().upper()
        if import_rj:
            subtitle_import_rows_by_rj.setdefault(import_rj, []).append(row)

    preview_by_session: dict[str, dict[str, Any]] = {}
    preview_rows: list[dict[str, Any]] = []
    retry_rows_by_session: dict[str, list[dict[str, Any]]] = {}
    rename_rows_by_key: dict[str, list[dict[str, Any]]] = {}
    rename_batch_rows_by_id: dict[str, dict[str, Any]] = {}
    delete_rows_by_key: dict[str, list[dict[str, Any]]] = {}
    delete_batch_rows_by_id: dict[str, dict[str, Any]] = {}
    merged_rename_ids: set[str] = set()
    merged_rename_batch_child_ids: set[str] = set()
    merged_delete_ids: set[str] = set()
    merged_delete_batch_child_ids: set[str] = set()
    merged_circle_completion_ids: set[str] = set()
    merged_asmr_sync_ids: set[str] = set()
    for row in rows:
        if row.get("category") == "pipeline_rename":
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
            rename_key = str(detail.get("rename_key") or row.get("source_path") or "").strip()
            if row.get("action") in {"batch_api_rename", "batch_manual_rename"}:
                if batch_id:
                    rename_batch_rows_by_id[batch_id] = row
                continue
            if batch_id:
                continue
            if rename_key:
                rename_rows_by_key.setdefault(rename_key, []).append(row)
        if row.get("category") == "pipeline_delete":
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
            delete_key = str(detail.get("delete_key") or row.get("source_path") or "").strip()
            if row.get("action") == "batch_api_delete":
                if batch_id:
                    delete_batch_rows_by_id[batch_id] = row
                continue
            if batch_id:
                continue
            if delete_key:
                delete_rows_by_key.setdefault(delete_key, []).append(row)
        if row.get("category") != "pipeline_filter" or row.get("action") != "filter_delete_preview":
            if row.get("category") == "pipeline_filter" and row.get("action") == "filter_delete_preview_retry":
                detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
                session_key = str(detail.get("session_key") or "").strip()
                if session_key:
                    retry_rows_by_session.setdefault(session_key, []).append(row)
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        session_key = str(detail.get("session_key") or "").strip()
        if session_key:
            preview_by_session.setdefault(session_key, row)
        preview_rows.append(row)

    for row in rows:
        if row.get("category") != "subtitle_pair":
            continue
        if str(row.get("id") or "") in merged_pair_ids:
            continue
        task_id = str(row.get("task_id") or "").strip()
        pair_dt = _coerce_dt(row.get("created_at"))
        import_row = subtitle_import_by_task.get(task_id) if task_id else None
        if not import_row:
            pair_rj = str(row.get("rjcode") or "").strip().upper()
            best_import_row = None
            best_import_seconds = None
            for candidate in subtitle_import_rows_by_rj.get(pair_rj, []):
                if str(candidate.get("id") or "") in merged_subtitle_import_ids:
                    continue
                candidate_dt = _coerce_dt(candidate.get("created_at"))
                if not pair_dt or not candidate_dt or candidate_dt > pair_dt:
                    continue
                seconds = (pair_dt - candidate_dt).total_seconds()
                if seconds < 0 or seconds > 7 * 24 * 3600:
                    continue
                if best_import_seconds is None or seconds < best_import_seconds:
                    best_import_seconds = seconds
                    best_import_row = candidate
            import_row = best_import_row
        if import_row:
            import_detail = import_row.get("detail") if isinstance(import_row.get("detail"), dict) else {}
            pair_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            import_row["detail"] = {
                **import_detail,
                "pair_summary": row.get("summary") or "",
                "pair_status": row.get("status") or "",
                "pair_action": row.get("action") or "",
                "pair_applied_pairs": int(pair_detail.get("applied_pairs") or pair_detail.get("manual_match_applied_pairs") or 0),
                "pair_deleted_subtitles": int(pair_detail.get("deleted_subtitles") or 0),
                "pair_final_file_count": int(pair_detail.get("final_file_count") or 0),
                "pair_linked": True,
                "pair_created_at": row.get("created_at") or "",
            }
            _append_tree_child(
                import_row,
                _make_tree_child(
                    row,
                    relation="pair",
                    category_label="字幕配对",
                    detail=pair_detail,
                    fallback_id=f"{task_id}-pair-{pair_detail.get('final_file_count') or row.get('created_at') or '0'}",
                ),
            )
            import_row["merged_pair"] = True
            import_row["merged_pair_status"] = row.get("status") or ""
            merged_pair_ids.add(str(row.get("id") or ""))
            continue
        if not task_id:
            continue
        crawl_row = crawl_by_task.get(task_id)
        if not crawl_row:
            continue
        crawl_detail = crawl_row.get("detail") if isinstance(crawl_row.get("detail"), dict) else {}
        pair_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        crawl_detail = {
            **crawl_detail,
            "awaiting_manual_match": False,
            "manual_match_completed": str(row.get("status") or "").strip() == "success",
            "pair_summary": row.get("summary") or "",
            "pair_status": row.get("status") or "",
            "pair_action": row.get("action") or "",
            "pair_applied_pairs": int(pair_detail.get("applied_pairs") or pair_detail.get("manual_match_applied_pairs") or 0),
            "pair_deleted_subtitles": int(pair_detail.get("deleted_subtitles") or 0),
            "pair_final_file_count": int(pair_detail.get("final_file_count") or 0),
            "pair_linked": True,
            "pair_created_at": row.get("created_at") or "",
            "manual_match_applied_pairs": int(pair_detail.get("applied_pairs") or pair_detail.get("manual_match_applied_pairs") or 0),
            "manual_match_deleted_subtitles": int(pair_detail.get("deleted_subtitles") or 0),
        }
        crawl_row["detail"] = crawl_detail
        crawl_row["summary"] = f"{crawl_row.get('summary') or '字幕爬取完成'}，{row.get('summary') or '已完成手动配对'}"
        crawl_row["merged_pair"] = True
        crawl_row["merged_pair_status"] = row.get("status") or ""
        merged_pair_ids.add(str(row.get("id") or ""))

    for batch_row in batch_rows_by_id.values():
        _recompute_subtitle_batch_rollup(batch_row)

    for row in subtitle_import_rows:
        if str(row.get("action") or "").strip() not in {"archive_import", "folder_import"}:
            continue
        row_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        detail = row_detail
        if not _is_success_status(row.get("status")) and int(row_detail.get("final_file_count") or 0) <= 0:
            continue
        import_source_path = str(
            row.get("source_path")
            or detail.get("preview_source_path")
            or ""
        ).strip()
        import_rj = str(
            row.get("rjcode")
            or detail.get("target_rjcode")
            or detail.get("source_rjcode")
            or ""
        ).strip().upper()
        import_dt = _coerce_dt(row.get("created_at"))
        best_auto_row = None
        best_seconds = None
        for candidate in auto_import_rows:
            candidate_detail = candidate.get("detail") if isinstance(candidate.get("detail"), dict) else {}
            candidate_source_mode = str(candidate_detail.get("source_mode") or "").strip()
            if candidate_source_mode != "linked_translation_archive_pending":
                continue
            candidate_source_path = str(candidate.get("source_path") or "").strip()
            if import_source_path and candidate_source_path != import_source_path:
                continue
            candidate_target_rj = str(
                candidate_detail.get("linked_target_rjcode")
                or candidate.get("rjcode")
                or ""
            ).strip().upper()
            candidate_source_rj = str(
                candidate_detail.get("linked_source_rjcode")
                or candidate.get("rjcode")
                or ""
            ).strip().upper()
            if import_rj and candidate_target_rj and candidate_target_rj != import_rj:
                continue
            import_source_rj = str(detail.get("source_rjcode") or "").strip().upper()
            if import_source_rj and candidate_source_rj and candidate_source_rj != import_source_rj:
                continue
            candidate_dt = _coerce_dt(candidate.get("created_at"))
            if not import_dt or not candidate_dt or candidate_dt > import_dt:
                continue
            seconds = (import_dt - candidate_dt).total_seconds()
            if seconds < 0 or seconds > 1800:
                continue
            if best_seconds is None or seconds < best_seconds:
                best_seconds = seconds
                best_auto_row = candidate
        if not best_auto_row:
            continue

        import_child_rows = list(row_detail.get("child_rows") or [])
        import_child_detail = {
            **row_detail,
            "import_task_id": str(row_detail.get("task_id") or row.get("task_id") or "").strip() or None,
            "import_final_file_count": int(row_detail.get("final_file_count") or 0),
            "import_record_id": row_detail.get("record_id"),
        }
        target_import_row = import_batch_child_rows_by_source_id.get(str(best_auto_row.get("id") or "")) or best_auto_row
        _append_tree_child(
            target_import_row,
            _make_tree_child(
                row,
                relation="subtitle_import",
                category_label="字幕补配",
                detail=import_child_detail,
                child_rows=import_child_rows,
                fallback_id=f"{str(target_import_row.get('id') or best_auto_row.get('id') or 'auto')}-subtitle-import",
            ),
        )
        target_import_row["merged_subtitle_import"] = True
        target_import_row["merged_subtitle_import_status"] = row.get("status") or ""
        target_import_row["detail"] = {
            **(target_import_row.get("detail") if isinstance(target_import_row.get("detail"), dict) else {}),
            "import_linked": True,
            "import_status": row.get("status") or "",
            "import_summary": row.get("summary") or "",
            "import_target_rjcode": str(row.get("rjcode") or row_detail.get("target_rjcode") or "").strip().upper() or None,
        }
        if target_import_row is not best_auto_row:
            best_auto_row["merged_subtitle_import"] = True
            best_auto_row["merged_subtitle_import_status"] = row.get("status") or ""
        merged_subtitle_import_ids.add(str(row.get("id") or ""))

    for rename_key, rename_rows in rename_rows_by_key.items():
        ordered_rows = sorted(rename_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        if len(ordered_rows) <= 1:
            continue
        root_row = ordered_rows[0]
        root_detail = root_row.get("detail") if isinstance(root_row.get("detail"), dict) else {}
        latest_activity = _coerce_dt(root_row.get("created_at")) or datetime.min
        child_rows: list[dict[str, Any]] = []
        for rerun_index, rename_row in enumerate(ordered_rows[1:], start=1):
            child_rows.append(
                _make_tree_child(
                    rename_row,
                    relation="rerun",
                    category_label="API 重命名",
                    fallback_id=f"{rename_key}-rename-rerun-{rerun_index}",
                )
            )
            merged_rename_ids.add(str(rename_row.get("id") or ""))
            latest_activity = max(latest_activity, _coerce_dt(rename_row.get("created_at")) or datetime.min)
        root_row["detail"] = {
            **root_detail,
            "child_rows": child_rows,
            "child_row_count": len(child_rows),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at"),
        }
        root_row["has_child_rows"] = True
        root_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at")
        root_row["rerun"] = True

    for batch_id, batch_row in rename_batch_rows_by_id.items():
        batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
        child_rows: list[dict[str, Any]] = []
        latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id == str(batch_row.get("id") or ""):
                continue
            if row.get("category") != "pipeline_rename":
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            if str(detail.get("batch_id") or "").strip() != batch_id:
                continue
            child_rows.append(
                _make_tree_child(
                    row,
                    relation="rename_item",
                    category_label="子重命名",
                )
            )
            merged_rename_batch_child_ids.add(row_id)
            latest_activity = max(latest_activity, _coerce_dt(row.get("created_at")) or datetime.min)
        if child_rows:
            batch_row["detail"] = {
                **batch_detail,
                "child_rows": sorted(
                    child_rows,
                    key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
                ),
                "child_row_count": len(child_rows),
                "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at"),
            }
            batch_row["has_child_rows"] = True
            batch_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at")

    for delete_key, delete_rows in delete_rows_by_key.items():
        ordered_rows = sorted(delete_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        if len(ordered_rows) <= 1:
            continue
        root_row = ordered_rows[0]
        root_detail = root_row.get("detail") if isinstance(root_row.get("detail"), dict) else {}
        latest_activity = _coerce_dt(root_row.get("created_at")) or datetime.min
        child_rows: list[dict[str, Any]] = []
        for rerun_index, delete_row in enumerate(ordered_rows[1:], start=1):
            child_rows.append(
                _make_tree_child(
                    delete_row,
                    relation="delete_item",
                    category_label="子删除",
                    fallback_id=f"{delete_key}-delete-rerun-{rerun_index}",
                )
            )
            merged_delete_ids.add(str(delete_row.get("id") or ""))
            latest_activity = max(latest_activity, _coerce_dt(delete_row.get("created_at")) or datetime.min)
        root_row["detail"] = {
            **root_detail,
            "child_rows": child_rows,
            "child_row_count": len(child_rows),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at"),
        }
        root_row["has_child_rows"] = True
        root_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at")
        root_row["rerun"] = True

    for batch_id, batch_row in delete_batch_rows_by_id.items():
        batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
        child_rows: list[dict[str, Any]] = []
        latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id == str(batch_row.get("id") or ""):
                continue
            if row.get("category") != "pipeline_delete":
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            if str(detail.get("batch_id") or "").strip() != batch_id:
                continue
            child_rows.append(
                _make_tree_child(
                    row,
                    relation="delete_item",
                    category_label="子删除",
                )
            )
            merged_delete_batch_child_ids.add(row_id)
            latest_activity = max(latest_activity, _coerce_dt(row.get("created_at")) or datetime.min)
        if child_rows:
            batch_row["detail"] = {
                **batch_detail,
                "child_rows": sorted(
                    child_rows,
                    key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
                ),
                "child_row_count": len(child_rows),
                "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at"),
            }
            batch_row["has_child_rows"] = True
            batch_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at")

    delete_time_clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_id = str(row.get("id") or "")
        if row.get("category") != "pipeline_delete":
            continue
        if str(row.get("action") or "").strip() != "delete":
            continue
        if row_id in merged_delete_ids or row_id in merged_delete_batch_child_ids:
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        if str(detail.get("batch_id") or "").strip():
            continue
        source_path = str(row.get("source_path") or "").strip()
        created_at = str(row.get("created_at") or "").strip()
        if not source_path or not created_at:
            continue
        second_key = created_at[:19]
        cluster_key = f"{second_key}|{str(row.get('status') or '').strip()}|{str(detail.get('library_id') or '').strip()}"
        delete_time_clusters.setdefault(cluster_key, []).append(row)

    for cluster_rows in delete_time_clusters.values():
        ordered_rows = sorted(cluster_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        if len(ordered_rows) <= 1:
            continue
        source_paths = [str(item.get("source_path") or "").strip() for item in ordered_rows if str(item.get("source_path") or "").strip()]
        common_root = _common_path_prefix(source_paths)
        if not common_root:
            continue
        path_depth = len([part for part in re.split(r"[\\/]+", common_root) if part])
        if path_depth < 3:
            continue

        root_row = ordered_rows[0]
        root_detail = root_row.get("detail") if isinstance(root_row.get("detail"), dict) else {}
        latest_activity = _coerce_dt(root_row.get("created_at")) or datetime.min
        child_rows: list[dict[str, Any]] = []
        success_count = 0
        failed_count = 0
        for cluster_index, delete_row in enumerate(ordered_rows, start=1):
            if str(delete_row.get("status") or "").strip() in {"success", "completed"}:
                success_count += 1
            else:
                failed_count += 1
            child_rows.append(
                _make_tree_child(
                    delete_row,
                    relation="delete_item",
                    category_label="子删除",
                    fallback_id=f"{str(root_row.get('id') or 'delete-cluster')}-delete-item-{cluster_index}",
                )
            )
            latest_activity = max(latest_activity, _coerce_dt(delete_row.get("created_at")) or datetime.min)

        root_row["summary"] = f"批量删除完成，成功 {success_count} 项，失败 {failed_count} 项"
        root_row["source_path"] = common_root
        root_row["action"] = "batch_delete_item"
        root_row["detail"] = {
            **root_detail,
            "child_rows": child_rows,
            "child_row_count": len(child_rows),
            "success_count": success_count,
            "failed_count": failed_count,
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at"),
            "derived_batch_group": True,
            "derived_batch_root": common_root,
        }
        root_row["has_child_rows"] = True
        root_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else root_row.get("created_at")

        for delete_row in ordered_rows[1:]:
            merged_delete_ids.add(str(delete_row.get("id") or ""))

    for row in rows:
        if row.get("category") != "pipeline_filter" or row.get("action") != "filter_delete_apply":
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        session_key = str(detail.get("session_key") or "").strip()
        preview_row = preview_by_session.get(session_key) if session_key else None
        if not preview_row:
            apply_path = str(row.get("source_path") or "").strip()
            apply_dt = _coerce_dt(row.get("created_at"))
            closest_row = None
            closest_seconds = None
            for candidate in preview_rows:
                if str(candidate.get("id") or "") in merged_filter_preview_ids:
                    continue
                if str(candidate.get("source_path") or "").strip() != apply_path:
                    continue
                candidate_dt = _coerce_dt(candidate.get("created_at"))
                if not apply_dt or not candidate_dt or candidate_dt > apply_dt:
                    continue
                seconds = (apply_dt - candidate_dt).total_seconds()
                if seconds < 0 or seconds > 1800:
                    continue
                if closest_seconds is None or seconds < closest_seconds:
                    closest_seconds = seconds
                    closest_row = candidate
            preview_row = closest_row
        if not preview_row:
            continue

        preview_detail = preview_row.get("detail") if isinstance(preview_row.get("detail"), dict) else {}
        preview_child_list = list(preview_detail.get("child_rows") or [])
        apply_child = {
            "id": str(row.get("id") or f"{session_key}-apply"),
            "relation": "delete_apply",
            "category": row.get("category"),
            "category_label": "删除执行",
            "action": row.get("action"),
            "status": row.get("status"),
            "summary": row.get("summary"),
            "created_at": row.get("created_at"),
            "source_path": row.get("source_path"),
            "rjcode": row.get("rjcode"),
            "detail": detail,
            "child_rows": [],
        }
        preview_child_list.append(apply_child)
        preview_selected_count = int(preview_detail.get("selected_count") or 0)
        preview_selected_size = int(preview_detail.get("selected_size") or 0)
        success_count = int(detail.get("success_count") or 0)
        failed_count = int(detail.get("failed_count") or 0)
        deleted_bytes = int(detail.get("deleted_bytes") or 0)
        latest_activity = _coerce_dt(row.get("created_at")) or _coerce_dt(preview_row.get("created_at")) or datetime.min
        preview_row["detail"] = {
            **preview_detail,
            "preview_linked": True,
            "preview_status": preview_row.get("status") or "",
            "preview_action": preview_row.get("action") or "",
            "preview_created_at": preview_row.get("created_at") or "",
            "delete_status": row.get("status") or "",
            "delete_action": row.get("action") or "",
            "delete_created_at": row.get("created_at") or "",
            "delete_success_count": success_count,
            "delete_failed_count": failed_count,
            "delete_deleted_bytes": deleted_bytes,
            "child_rows": sorted(
                preview_child_list,
                key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
            ),
            "child_row_count": len(preview_child_list),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else preview_row.get("created_at"),
        }
        preview_row["has_child_rows"] = True
        preview_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else preview_row.get("created_at")
        preview_row["merged_filter_delete"] = True
        preview_row["merged_filter_delete_status"] = row.get("status") or ""
        merged_filter_retry_ids.add(str(row.get("id") or ""))

    for session_key, retry_rows in retry_rows_by_session.items():
        if not retry_rows:
            continue
        parent_row = preview_by_session.get(session_key)
        if not parent_row:
            continue
        ordered_retry_rows = sorted(retry_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        latest_retry_row = ordered_retry_rows[-1]
        latest_retry_detail = latest_retry_row.get("detail") if isinstance(latest_retry_row.get("detail"), dict) else {}
        parent_detail = parent_row.get("detail") if isinstance(parent_row.get("detail"), dict) else {}
        child_rows = list(parent_detail.get("child_rows") or [])
        target_apply_child = None
        for child in sorted(child_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min):
            if str(child.get("relation") or "").strip() != "delete_apply":
                continue
            child_detail = child.get("detail") if isinstance(child.get("detail"), dict) else {}
            child_session_key = str(child_detail.get("session_key") or "").strip()
            if child_session_key and child_session_key == session_key:
                target_apply_child = child
        if not target_apply_child:
            latest_retry_path = str(latest_retry_row.get("source_path") or parent_row.get("source_path") or "").strip()
            latest_retry_dt = _coerce_dt(latest_retry_row.get("created_at"))
            closest_child = None
            closest_seconds = None
            for child in sorted(child_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min):
                if str(child.get("relation") or "").strip() != "delete_apply":
                    continue
                child_path = str(child.get("source_path") or "").strip()
                child_dt = _coerce_dt(child.get("created_at"))
                if latest_retry_path and child_path and child_path != latest_retry_path:
                    continue
                if not latest_retry_dt or not child_dt or child_dt > latest_retry_dt:
                    continue
                seconds = (latest_retry_dt - child_dt).total_seconds()
                if seconds < 0 or seconds > 1800:
                    continue
                if closest_seconds is None or seconds < closest_seconds:
                    closest_seconds = seconds
                    closest_child = child
            target_apply_child = closest_child
        retry_children = []
        for retry_row in ordered_retry_rows:
            retry_children.append({
                "id": str(retry_row.get("id") or f"{session_key}-retry"),
                "relation": "retry_preview",
                "category": retry_row.get("category"),
                "category_label": "补充删除",
                "action": retry_row.get("action"),
                "status": retry_row.get("status"),
                "summary": retry_row.get("summary"),
                "created_at": retry_row.get("created_at"),
                "source_path": retry_row.get("source_path"),
                "rjcode": retry_row.get("rjcode"),
                "detail": retry_row.get("detail") if isinstance(retry_row.get("detail"), dict) else {},
                "child_rows": [],
            })
        latest_activity = _coerce_dt(latest_retry_row.get("created_at")) or _coerce_dt(parent_row.get("created_at")) or datetime.min
        retry_status = str(latest_retry_detail.get("retry_status") or latest_retry_row.get("status") or "").strip()
        if target_apply_child:
            apply_detail = target_apply_child.get("detail") if isinstance(target_apply_child.get("detail"), dict) else {}
            apply_child_rows = list(target_apply_child.get("child_rows") or [])
            apply_child_rows.extend(retry_children)
            target_apply_child["detail"] = {
                **apply_detail,
                "retry_linked": True,
                "retry_status": retry_status,
                "retry_summary": latest_retry_row.get("summary") or "",
                "retry_target_count": int(latest_retry_detail.get("retry_target_count") or apply_detail.get("retry_target_count") or 0),
                "retry_success_count": int(latest_retry_detail.get("retry_success_count") or apply_detail.get("retry_success_count") or 0),
                "retry_failed_count": int(latest_retry_detail.get("retry_failed_count") or apply_detail.get("retry_failed_count") or 0),
                "recovered_item_count": int(latest_retry_detail.get("recovered_item_count") or apply_detail.get("recovered_item_count") or 0),
                "recovered_selected_size": int(latest_retry_detail.get("recovered_selected_size") or apply_detail.get("recovered_selected_size") or 0),
            }
            target_apply_child["child_rows"] = sorted(
                apply_child_rows,
                key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
            )
        else:
            child_rows.extend(retry_children)
        parent_row["detail"] = {
            **parent_detail,
            "retry_linked": True,
            "retry_summary": latest_retry_row.get("summary") or "",
            "retry_action": latest_retry_row.get("action") or "",
            "retry_row_status": latest_retry_row.get("status") or "",
            "retry_created_at": latest_retry_row.get("created_at") or "",
            "retry_target_count": int(latest_retry_detail.get("retry_target_count") or parent_detail.get("retry_target_count") or 0),
            "retry_success_count": int(latest_retry_detail.get("retry_success_count") or parent_detail.get("retry_success_count") or 0),
            "retry_failed_count": int(latest_retry_detail.get("retry_failed_count") or parent_detail.get("retry_failed_count") or 0),
            "recovered_item_count": int(latest_retry_detail.get("recovered_item_count") or parent_detail.get("recovered_item_count") or 0),
            "recovered_selected_size": int(latest_retry_detail.get("recovered_selected_size") or parent_detail.get("recovered_selected_size") or 0),
            "retry_targets": latest_retry_detail.get("retry_targets") or parent_detail.get("retry_targets") or [],
            "recovered_items": latest_retry_detail.get("recovered_items") or parent_detail.get("recovered_items") or [],
            "failed_targets": latest_retry_detail.get("failed_targets") or parent_detail.get("failed_targets") or [],
            "retry_status": latest_retry_detail.get("retry_status") or parent_detail.get("retry_status") or "",
            "repair_status": retry_status,
            "repair_summary": latest_retry_row.get("summary") or "",
            "repair_completed_at": latest_retry_row.get("created_at") or "",
            "child_rows": sorted(
                child_rows,
                key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
            ),
            "child_row_count": len(child_rows),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at"),
        }
        if retry_status == "success":
            parent_row["retry_badge"] = "已修复"
        elif retry_status == "partial_success":
            parent_row["retry_badge"] = "部分修复"
        elif retry_status == "failed":
            parent_row["retry_badge"] = "未修复"
        parent_row["merged_filter_retry"] = True
        parent_row["merged_filter_retry_status"] = retry_status
        parent_row["has_child_rows"] = True
        parent_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at")
        for retry_row in retry_rows:
            merged_filter_retry_ids.add(str(retry_row.get("id") or ""))

    for preview_row in preview_rows:
        parent_detail = preview_row.get("detail") if isinstance(preview_row.get("detail"), dict) else {}
        original_children = sorted(
            [
                child for child in (parent_detail.get("child_rows") or [])
                if isinstance(child, dict)
            ],
            key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
        )
        if not original_children:
            continue

        normalized_children: list[dict[str, Any]] = []
        pending_apply_child: Optional[dict[str, Any]] = None
        repair_status = str(parent_detail.get("repair_status") or "").strip()
        repair_summary = str(parent_detail.get("repair_summary") or "").strip()
        repair_completed_at = str(parent_detail.get("repair_completed_at") or "").strip()

        for child in original_children:
            relation = str(child.get("relation") or "").strip()
            if relation != "delete_apply":
                normalized_children.append(child)
                continue

            child_status = str(child.get("status") or "").strip()
            if pending_apply_child and child_status:
                retry_apply_child = {
                    **child,
                    "relation": "retry_apply",
                    "category_label": "补充删除",
                }
                pending_detail = pending_apply_child.get("detail") if isinstance(pending_apply_child.get("detail"), dict) else {}
                pending_child_rows = list(pending_apply_child.get("child_rows") or [])
                pending_child_rows.append(retry_apply_child)
                pending_apply_child["child_rows"] = sorted(
                    pending_child_rows,
                    key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
                )
                pending_apply_child["detail"] = {
                    **pending_detail,
                    "retry_linked": True,
                    "retry_status": "failed" if child_status == "cancelled" else child_status,
                    "retry_summary": child.get("summary") or "",
                    "repair_status": "failed" if child_status == "cancelled" else child_status,
                    "repair_summary": child.get("summary") or "",
                    "repair_completed_at": child.get("created_at") or "",
                }
                repair_status = "failed" if child_status == "cancelled" else child_status
                repair_summary = str(child.get("summary") or "").strip()
                repair_completed_at = str(child.get("created_at") or "").strip()
                if child_status == "success":
                    pending_apply_child = None
                else:
                    pending_apply_child = pending_apply_child
                continue

            normalized_children.append(child)
            if child_status in {"partial_success", "failed", "cancelled"}:
                pending_apply_child = child
            else:
                pending_apply_child = None

        latest_activity = _coerce_dt(preview_row.get("created_at")) or datetime.min
        for child in normalized_children:
            latest_activity = max(latest_activity, _max_tree_activity(child))

        preview_row["detail"] = {
            **parent_detail,
            "child_rows": normalized_children,
            "child_row_count": len(normalized_children),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else preview_row.get("created_at"),
            "repair_status": repair_status,
            "repair_summary": repair_summary,
            "repair_completed_at": repair_completed_at,
            "retry_linked": bool(repair_status) or bool(parent_detail.get("retry_linked")),
        }
        if repair_status:
            if repair_status == "success":
                preview_row["retry_badge"] = "已修复"
            elif repair_status == "partial_success":
                preview_row["retry_badge"] = "部分修复"
            elif repair_status == "failed":
                preview_row["retry_badge"] = "未修复"
            preview_row["merged_filter_retry"] = True
            preview_row["merged_filter_retry_status"] = repair_status
        preview_row["has_child_rows"] = True
        preview_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else preview_row.get("created_at")

    # 社团补全操作记录聚合
    circle_index_rows_by_circle: dict[str, list[dict[str, Any]]] = {}
    circle_refresh_rows_by_circle: dict[str, list[dict[str, Any]]] = {}
    circle_download_batches: dict[str, dict[str, Any]] = {}  # batch_id -> row
    email_watcher_batches: dict[str, dict[str, Any]] = {}

    def _circle_source_label(row: dict[str, Any], detail: dict[str, Any]) -> str:
        action = str(row.get("action") or "").strip()
        circle_name = str(detail.get("circle_name") or "").strip()
        circle_id = str(detail.get("circle_id") or "").strip()
        title = str(detail.get("work_title") or detail.get("source_label") or "").strip()
        rjcode = str(row.get("rjcode") or detail.get("rjcode") or detail.get("canonical_rjcode") or "").strip()
        source_action = str(row.get("source_action") or detail.get("source_action") or "").strip()
        target_subdir = str(detail.get("target_subdir") or "").strip()
        download_base_path = str(detail.get("download_base_path") or "").strip()
        circle_label = circle_name or circle_id
        work_label = " / ".join(item for item in [rjcode, title] if item)
        if action == "index_completed":
            return f"社团：{circle_label}" if circle_label else ""
        if action == "refresh_selected_works":
            return f"社团状态刷新：{circle_label}" if circle_label else ""
        if action == "download_batch_start":
            target_label = target_subdir or download_base_path
            if circle_label and target_label:
                return f"批量下载：{circle_label} → {target_label}"
            return f"批量下载：{circle_label}" if circle_label else target_label
        if action == "download_item_queued":
            return f"作品：{work_label}" if work_label else ""
        if action in {"task_finished", "task_finished_incomplete"}:
            if source_action == "refresh_selected":
                return f"社团状态刷新：{circle_label}" if circle_label else ""
            if work_label:
                return f"作品：{work_label}"
            return f"社团：{circle_label}" if circle_label else ""
        return f"社团：{circle_label}" if circle_label else ""

    def _merge_circle_task_finish_duration(parent_row: dict[str, Any], finish_row: dict[str, Any]) -> None:
        parent_detail = parent_row.get("detail") if isinstance(parent_row.get("detail"), dict) else {}
        finish_detail = finish_row.get("detail") if isinstance(finish_row.get("detail"), dict) else {}
        duration_ms = int(finish_detail.get("duration_ms") or 0)
        if duration_ms <= 0:
            start_at = _coerce_dt(finish_row.get("task_created_at") or finish_row.get("created_at"))
            end_at = _coerce_dt(finish_row.get("created_at"))
            if start_at and end_at and end_at >= start_at:
                duration_ms = int((end_at - start_at).total_seconds() * 1000)
        if duration_ms > 0:
            parent_row["detail"] = {
                **parent_detail,
                "duration_ms": duration_ms,
                "task_duration_ms": duration_ms,
            }
        parent_row["latest_activity_at"] = finish_row.get("created_at") or parent_row.get("latest_activity_at") or parent_row.get("created_at")
    
    # 第一步：收集索引和刷新记录
    for row in rows:
        if str(row.get("category") or "").strip() == "email_watcher":
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
            mode = str(detail.get("mode") or "").strip()
            if str(row.get("action") or "").strip() == "fetch_check" and batch_id:
                email_watcher_batches[batch_id] = row
                row["is_parent_task"] = True
                row["child_rows"] = []
            elif str(row.get("action") or "").strip() == "circle_index_triggered" and batch_id and batch_id in email_watcher_batches:
                parent_row = email_watcher_batches[batch_id]
                child_detail = detail or {}
                child_row = _make_tree_child(
                    row,
                    relation="email_new_release_item" if mode == "email_new_release_item" else "email_watcher",
                    category_label="新作项",
                    detail=child_detail,
                )
                _append_tree_child(parent_row, child_row)
                merged_circle_completion_ids.add(str(row.get("id") or ""))
            continue

        if str(row.get("category") or "").strip() != "circle_completion":
            continue
        action = str(row.get("action") or "").strip()
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        row["source_path"] = row.get("source_path") or _circle_source_label(row, detail)
        circle_id = str(detail.get("circle_id") or "").strip()
        if not circle_id:
            continue
            
        if action == "index_completed":
            circle_index_rows_by_circle.setdefault(circle_id, []).append(row)
        elif action == "refresh_selected_works":
            circle_refresh_rows_by_circle.setdefault(circle_id, []).append(row)
        elif action == "download_batch_start":
            # 批量下载任务作为独立的父任务，不关联到索引记录
            batch_id = str(detail.get("batch_id") or row.get("task_id") or "").strip()
            if batch_id:
                circle_download_batches[batch_id] = row
                # 标记为父任务
                row["is_parent_task"] = True
                row["child_rows"] = []

    # 排序
    for circle_id, circle_rows in circle_index_rows_by_circle.items():
        circle_rows.sort(key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
    for circle_id, circle_rows in circle_refresh_rows_by_circle.items():
        circle_rows.sort(key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)

    # 第二步：处理批量下载任务的子任务
    for row in rows:
        if str(row.get("category") or "").strip() != "circle_completion":
            continue
        if str(row.get("action") or "").strip() != "download_item_queued":
            continue

        row_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        batch_id = str(row_detail.get("parent_session_id") or "").strip()
        if not batch_id:
            continue
            
        parent_batch_row = circle_download_batches.get(batch_id)
        if not parent_batch_row:
            continue
            
        # 将下载项作为子任务关联到批量下载任务
        child_row = _make_tree_child(
            row,
            relation="download_item",
            category_label="下载项",
            detail=row_detail,
        )
        _append_tree_child(parent_batch_row, child_row)
        merged_circle_completion_ids.add(str(row.get("id") or ""))

    # 第三步：处理任务完成状态
    for row in rows:
        if str(row.get("category") or "").strip() != "circle_completion":
            continue
        if str(row.get("action") or "").strip() not in {"task_finished", "task_finished_incomplete"}:
            continue

        row_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        circle_id = str(row_detail.get("circle_id") or "").strip()
        source_action = str(row.get("source_action") or row_detail.get("source_action") or "").strip()
        batch_id = str(row_detail.get("batch_id") or row_detail.get("parent_session_id") or "").strip()
        batch_circle_summaries = [
            item for item in list(row_detail.get("batch_circle_summaries") or [])
            if isinstance(item, dict)
        ]

        if batch_circle_summaries:
            if len(batch_circle_summaries) == 1:
                item_circle_id = str((batch_circle_summaries[0] or {}).get("circle_id") or circle_id).strip()
                parent_candidates = circle_index_rows_by_circle.get(item_circle_id) or circle_index_rows_by_circle.get(circle_id) or []
                if parent_candidates:
                    row_dt = _coerce_dt(row.get("created_at")) or datetime.min
                    parent_row = None
                    for candidate in parent_candidates:
                        candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
                        if candidate_dt <= row_dt:
                            parent_row = candidate
                    if parent_row is None:
                        parent_row = parent_candidates[-1]
                    _merge_circle_task_finish_duration(parent_row, row)
                merged_circle_completion_ids.add(str(row.get("id") or ""))
                continue

            row["is_parent_task"] = True
            row["child_rows"] = []
            for index, item in enumerate(batch_circle_summaries, start=1):
                success = bool(item.get("success", True))
                circle_label = str(item.get("circle_name") or item.get("circle_query") or item.get("circle_id") or f"社团 {index}").strip()
                child_detail = {
                    **item,
                    "circle_name": circle_label,
                    "source_action": "circle_batch_index_item",
                }
                child_row = {
                    **row,
                    "id": f"{row.get('id')}:circle:{index}",
                    "relation": "circle_batch_index_item",
                    "category_label": "社团索引项",
                    "status": "success" if success else "failed",
                    "summary": (
                        f"{circle_label} 索引完成：Kikoeru {item.get('kikoeru_owned_count') or 0} / "
                        f"DL {item.get('dl_count') or 0} / 可下载 {item.get('downloadable_count') or 0} / "
                        f"缺失 {item.get('missing_count') or 0}"
                        if success else f"{circle_label} 索引失败：{item.get('error_message') or '未知错误'}"
                    ),
                    "source_path": f"社团：{circle_label}",
                    "detail": child_detail,
                    "child_rows": [],
                }
                _append_tree_child(row, child_row)
            continue
        
        # 跳过全量刷新
        if source_action == "refresh_all_circles":
            continue
        if source_action in {"", "index_start", "circle_index", "index_completed"} and not batch_id:
            parent_candidates = circle_index_rows_by_circle.get(circle_id) or []
            if parent_candidates:
                row_dt = _coerce_dt(row.get("created_at")) or datetime.min
                parent_row = None
                for candidate in parent_candidates:
                    candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
                    if candidate_dt <= row_dt:
                        parent_row = candidate
                if parent_row is None:
                    parent_row = parent_candidates[-1]
                _merge_circle_task_finish_duration(parent_row, row)
            merged_circle_completion_ids.add(str(row.get("id") or ""))
            continue
        if not circle_id:
            continue

        # 优先关联到批量下载任务
        if batch_id and batch_id in circle_download_batches:
            parent_batch_row = circle_download_batches[batch_id]
            # 更新批量下载任务的状态
            if str(row.get("action") or "").strip() == "task_finished":
                parent_batch_row["status"] = "success"
            elif str(row.get("action") or "").strip() == "task_finished_incomplete":
                parent_batch_row["status"] = "partial_success"
            
            # 作为子任务添加
            child_row = _make_tree_child(
                row,
                relation="task_completion",
                category_label="任务完成",
                detail=row_detail,
            )
            _append_tree_child(parent_batch_row, child_row)
            merged_circle_completion_ids.add(str(row.get("id") or ""))
            continue

        # 关联到刷新任务
        if source_action == "refresh_selected":
            parent_candidates = circle_refresh_rows_by_circle.get(circle_id) or []
            if parent_candidates:
                row_dt = _coerce_dt(row.get("created_at")) or datetime.min
                parent_row = None
                for candidate in parent_candidates:
                    candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
                    if candidate_dt <= row_dt:
                        parent_row = candidate
                if parent_row is None:
                    parent_row = parent_candidates[-1]
                parent_row["latest_activity_at"] = row.get("created_at") or parent_row.get("latest_activity_at") or parent_row.get("created_at")
                
                # 添加任务完成状态
                child_row = _make_tree_child(
                    row,
                    relation="task_completion",
                    category_label="任务完成",
                    detail=row_detail,
                )
                _append_tree_child(parent_row, child_row)
            merged_circle_completion_ids.add(str(row.get("id") or ""))
            continue

        # 兼容旧日志：早期 refresh_selected 的 task_finished 没带 source_action，
        # 这里按同社团 + 时间邻近的 refresh_selected_works 父记录兜底归并。
        refresh_parent_candidates = circle_refresh_rows_by_circle.get(circle_id) or []
        if refresh_parent_candidates:
            row_dt = _coerce_dt(row.get("created_at")) or datetime.min
            fallback_parent = None
            fallback_delta_seconds = None
            for candidate in refresh_parent_candidates:
                candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
                delta_seconds = abs((row_dt - candidate_dt).total_seconds())
                if fallback_parent is None or delta_seconds < (fallback_delta_seconds or float("inf")):
                    fallback_parent = candidate
                    fallback_delta_seconds = delta_seconds
            if fallback_parent is not None and (fallback_delta_seconds or 0) <= 120:
                fallback_parent["latest_activity_at"] = row.get("created_at") or fallback_parent.get("latest_activity_at") or fallback_parent.get("created_at")
                merged_circle_completion_ids.add(str(row.get("id") or ""))
                continue

        # 兼容更老的 refresh_selected 收尾日志：没有 source_action，
        # 但 source_path 往往就是社团名，且不会附着到 index_completed。
        circle_name = str(row_detail.get("circle_name") or "").strip()
        row_source_path = str(row.get("source_path") or "").strip()
        if circle_name and row_source_path and row_source_path == circle_name:
            merged_circle_completion_ids.add(str(row.get("id") or ""))
            continue

        parent_candidates = circle_index_rows_by_circle.get(circle_id) or []
        if not parent_candidates:
            continue

        row_dt = _coerce_dt(row.get("created_at")) or datetime.min
        parent_row = None
        for candidate in parent_candidates:
            candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
            if candidate_dt <= row_dt:
                parent_row = candidate
        if parent_row is None:
            parent_row = parent_candidates[-1]

        child_row = _make_tree_child(
            row,
            relation="circle_task_finish",
            category_label="任务收尾",
            detail=row_detail,
        )
        _append_tree_child(parent_row, child_row)
        merged_circle_completion_ids.add(str(row.get("id") or ""))

    asmr_rows_by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("category") or "").strip() != "asmr_sync":
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        session_id = str(detail.get("session_id") or row.get("task_id") or "").strip()
        if not session_id:
            continue
        asmr_rows_by_session.setdefault(session_id, []).append(row)

    parent_action_priority = {
        "session_completed": 90,
        "session_partial_failed": 85,
        "task_finished": 80,
        "task_finished_incomplete": 75,
        "session_started": 60,
        "enhanced_plan_created": 40,
        "task_failed": 30,
        "task_cancelled": 25,
    }
    child_action_relations = {
        "resource_downloaded": ("asmr_resource", "下载文件"),
        "resource_uploaded": ("asmr_upload", "上传文件"),
        "resource_verify_failed": ("asmr_verify_failed", "校验失败"),
        "session_started": ("asmr_session", "下载开始"),
        "enhanced_plan_created": ("asmr_plan", "下载计划"),
        "queue_reordered": ("asmr_session", "队列调整"),
        "task_paused": ("asmr_session", "任务暂停"),
        "task_resumed": ("asmr_session", "任务恢复"),
        "task_cancelled": ("asmr_session", "任务取消"),
        "task_retried": ("asmr_session", "任务重试"),
        "task_failed": ("asmr_session", "任务失败"),
        "task_queued": ("asmr_session", "任务排队"),
    }

    for session_id, session_rows in asmr_rows_by_session.items():
        if len(session_rows) <= 1:
            continue
        ordered_rows = sorted(session_rows, key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)
        parent_row = max(
            ordered_rows,
            key=lambda item: (
                parent_action_priority.get(str(item.get("action") or "").strip(), 0),
                _coerce_dt(item.get("created_at")) or datetime.min,
            ),
        )
        parent_detail = parent_row.get("detail") if isinstance(parent_row.get("detail"), dict) else {}
        task_finished_row = next(
            (item for item in reversed(ordered_rows) if str(item.get("action") or "").strip() == "task_finished"),
            None,
        )
        task_finished_detail = task_finished_row.get("detail") if isinstance(task_finished_row and task_finished_row.get("detail"), dict) else {}
        session_complete_row = next(
            (
                item for item in reversed(ordered_rows)
                if str(item.get("action") or "").strip() in {"session_completed", "session_partial_failed"}
            ),
            None,
        )
        session_complete_detail = session_complete_row.get("detail") if isinstance(session_complete_row and session_complete_row.get("detail"), dict) else {}
        session_started_row = next(
            (item for item in ordered_rows if str(item.get("action") or "").strip() == "session_started"),
            None,
        )
        session_started_detail = session_started_row.get("detail") if isinstance(session_started_row and session_started_row.get("detail"), dict) else {}
        resource_rows = [
            item for item in ordered_rows
            if str(item.get("action") or "").strip() == "resource_downloaded"
        ]
        success_count = int(
            session_complete_detail.get("success_count")
            or task_finished_detail.get("success_count")
            or len(resource_rows)
            or 0
        )
        failed_count = int(
            session_complete_detail.get("failed_count")
            or task_finished_detail.get("failed_count")
            or 0
        )
        downloaded_bytes = int(
            session_complete_detail.get("downloaded_bytes")
            or task_finished_detail.get("downloaded_bytes")
            or sum(int((item.get("detail") if isinstance(item.get("detail"), dict) else {}).get("size_bytes") or 0) for item in resource_rows)
            or 0
        )
        duration_ms = int(
            session_complete_detail.get("duration_ms")
            or task_finished_detail.get("duration_ms")
            or 0
        )
        download_root = str(
            session_complete_detail.get("download_root")
            or task_finished_detail.get("download_root")
            or parent_detail.get("download_root")
            or ""
        ).strip()
        target_path = str(
            session_complete_detail.get("target_path")
            or session_started_detail.get("target_path")
            or task_finished_detail.get("target_path")
            or parent_detail.get("target_path")
            or ""
        ).strip()
        upload_mode = str(
            session_complete_detail.get("upload_mode")
            or session_started_detail.get("upload_mode")
            or task_finished_detail.get("upload_mode")
            or parent_detail.get("upload_mode")
            or ""
        ).strip()
        uploaded_count = int(
            session_complete_detail.get("uploaded_count")
            or task_finished_detail.get("uploaded_count")
            or 0
        )
        uploaded_files = list(
            session_complete_detail.get("uploaded_files")
            or task_finished_detail.get("uploaded_files")
            or parent_detail.get("uploaded_files")
            or []
        )
        uploaded_bytes = int(
            session_complete_detail.get("uploaded_bytes")
            or task_finished_detail.get("uploaded_bytes")
            or sum(int((item or {}).get("size_bytes") or 0) for item in uploaded_files)
            or 0
        )
        average_upload_speed_bytes = int(
            session_complete_detail.get("average_upload_speed_bytes")
            or task_finished_detail.get("average_upload_speed_bytes")
            or (uploaded_bytes / max(duration_ms / 1000, 1) if uploaded_bytes > 0 and duration_ms > 0 else 0)
            or 0
        )
        original_parent_status = str(parent_row.get("status") or "").strip() or "success"
        # 计算任务状态
        rollup_status = original_parent_status
        if success_count > 0 and failed_count <= 0:
            rollup_status = "success"
        elif success_count > 0 and failed_count > 0:
            rollup_status = "partial_success"
        elif failed_count > 0:
            rollup_status = "failed"
        elif upload_mode == "disabled" and (download_root or downloaded_bytes > 0):
            rollup_status = "success"
        elif str(parent_row.get("status") or "").strip() in {"pending", "processing", "paused", "waiting_retry"}:
            rollup_status = str(parent_row.get("status") or "").strip()

        child_rows: list[dict[str, Any]] = []
        latest_activity = _coerce_dt(parent_row.get("created_at")) or datetime.min
        for row in ordered_rows:
            if row is parent_row:
                continue
            action = str(row.get("action") or "").strip()
            relation_info = child_action_relations.get(action)
            if not relation_info:
                merged_asmr_sync_ids.add(str(row.get("id") or ""))
                continue
            relation, category_label = relation_info
            child_row = _make_tree_child(
                row,
                relation=relation,
                category_label=category_label,
            )
            child_rows.append(child_row)
            merged_asmr_sync_ids.add(str(row.get("id") or ""))
            latest_activity = max(latest_activity, _coerce_dt(row.get("created_at")) or datetime.min)

        if success_count > 0 or downloaded_bytes > 0 or duration_ms > 0 or uploaded_count > 0:
            summary_parts = [f"{'上传' if uploaded_count > 0 else '下载'} {uploaded_count if uploaded_count > 0 else success_count} 个文件"]
            if uploaded_bytes > 0:
                summary_parts.append(_format_bytes_short(uploaded_bytes))
            elif downloaded_bytes > 0:
                summary_parts.append(_format_bytes_short(downloaded_bytes))
            if average_upload_speed_bytes > 0:
                summary_parts.append(f"平均 {_format_bytes_short(average_upload_speed_bytes)}/s")
            if duration_ms > 0:
                summary_parts.append(f"耗时 {_format_duration_short(duration_ms)}")
            parent_row["summary"] = " / ".join(summary_parts)

        parent_row["status"] = rollup_status
        if rollup_status == "success":
            parent_row["action"] = "session_completed"
        elif rollup_status == "partial_success":
            parent_row["action"] = "session_partial_failed"
        elif rollup_status == "failed":
            parent_row["action"] = "session_failed"
        elif rollup_status in {"pending", "processing", "paused", "waiting_retry"}:
            parent_row["action"] = f"session_{rollup_status}"

        parent_row["detail"] = {
            **parent_detail,
            "session_id": session_id,
            "success_count": success_count,
            "failed_count": failed_count,
            "downloaded_bytes": downloaded_bytes,
            "duration_ms": duration_ms,
            "download_root": download_root or None,
            "target_path": target_path or None,
            "upload_mode": upload_mode or None,
            "uploaded_count": uploaded_count,
            "uploaded_bytes": uploaded_bytes,
            "average_upload_speed_bytes": average_upload_speed_bytes,
            "uploaded_files": uploaded_files[:200],
            "recovered_by_success": rollup_status == "success" and original_parent_status == "failed",
            "child_rows": child_rows,
            "child_row_count": len(child_rows),
            "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at"),
        }
        parent_row["source_path"] = target_path or download_root or parent_row.get("source_path")
        parent_row["has_child_rows"] = bool(child_rows)
        parent_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at")

    def _circle_finish_match_key(row: dict[str, Any]) -> str:
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        return str(
            detail.get("circle_id")
            or detail.get("circle_name")
            or row.get("source_path")
            or ""
        ).strip()

    def _should_hide_single_circle_index_finish(row: dict[str, Any]) -> bool:
        if str(row.get("category") or "").strip() != "circle_completion":
            return False
        if str(row.get("action") or "").strip() not in {"task_finished", "task_finished_incomplete"}:
            return False
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        source_action = str(row.get("source_action") or detail.get("source_action") or "").strip()
        if source_action in {"refresh_selected", "refresh_all_circles", "download_batch"}:
            return False
        if str(detail.get("batch_id") or detail.get("parent_session_id") or "").strip():
            return False
        summaries = [item for item in list(detail.get("batch_circle_summaries") or []) if isinstance(item, dict)]
        return len(summaries) <= 1

    circle_index_candidates = [
        row for row in rows
        if str(row.get("category") or "").strip() == "circle_completion"
        and str(row.get("action") or "").strip() == "index_completed"
    ]
    for finish_row in rows:
        if not _should_hide_single_circle_index_finish(finish_row):
            continue
        finish_key = _circle_finish_match_key(finish_row)
        finish_dt = _coerce_dt(finish_row.get("created_at")) or datetime.min
        best_parent = None
        best_delta = None
        for candidate in circle_index_candidates:
            candidate_key = _circle_finish_match_key(candidate)
            if finish_key and candidate_key and finish_key != candidate_key:
                continue
            candidate_dt = _coerce_dt(candidate.get("created_at")) or datetime.min
            if candidate_dt == datetime.min or finish_dt == datetime.min:
                continue
            delta = abs((finish_dt - candidate_dt).total_seconds())
            if delta > 300:
                continue
            if best_delta is None or delta < best_delta:
                best_parent = candidate
                best_delta = delta
        if best_parent is not None:
            _merge_circle_task_finish_duration(best_parent, finish_row)
        merged_circle_completion_ids.add(str(finish_row.get("id") or ""))

    items: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("id") or "") in merged_batch_child_ids:
            continue
        if str(row.get("id") or "") in superseded_crawl_ids:
            continue
        if str(row.get("id") or "") in merged_pair_ids:
            continue
        if str(row.get("id") or "") in merged_subtitle_import_ids:
            continue
        if str(row.get("category") or "").strip() == "subtitle_import" and str(row.get("action") or "").strip() == "pending_execute":
            continue
        if str(row.get("id") or "") in merged_import_batch_child_ids:
            continue
        if str(row.get("id") or "") in merged_rename_ids:
            continue
        if str(row.get("id") or "") in merged_rename_batch_child_ids:
            continue
        if str(row.get("id") or "") in merged_filter_preview_ids:
            continue
        if str(row.get("id") or "") in merged_filter_retry_ids:
            continue
        if str(row.get("id") or "") in merged_delete_ids:
            continue
        if str(row.get("id") or "") in merged_delete_batch_child_ids:
            continue
        if str(row.get("id") or "") in merged_circle_completion_ids:
            continue
        if _should_hide_single_circle_index_finish(row):
            continue
        if str(row.get("id") or "") in merged_asmr_sync_ids:
            continue
        items.append(row)
    items.sort(key=lambda item: str(item.get("latest_activity_at") or item.get("created_at") or ""), reverse=True)
    return items
