"""activity_log_aggregator 的纯辅助函数。

Phase 4B 第 4 步从单文件 1900 行中抽出来，全部是无闭包依赖的纯函数：
- 时间/大小/时长格式化
- tree 子节点构造与去重
- 状态判断
- import 批次恢复标记 / 字幕批次汇总
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Optional

__all__ = [
    "_coerce_dt",
    "_format_bytes_short",
    "_format_duration_short",
    "_make_tree_child",
    "_append_tree_child",
    "_walk_tree_rows",
    "_max_tree_activity",
    "_is_success_status",
    "_is_failed_status",
    "_common_path_prefix",
    "_coalesce_import_batch_rows",
    "_import_row_match_key",
    "_build_latest_import_success_map",
    "_is_recovered_import_failure",
    "_is_successful_pair_state",
    "_recompute_subtitle_batch_rollup",
]


def _coerce_dt(value: Any) -> Optional[datetime]:
    try:
        if not value:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _format_bytes_short(size: Any) -> str:
    try:
        value = float(size or 0)
    except Exception:
        value = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"


def _format_duration_short(duration_ms: Any) -> str:
    try:
        total_seconds = max(0, int(round(float(duration_ms or 0) / 1000)))
    except Exception:
        total_seconds = 0
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}分{seconds}秒" if minutes else f"{seconds}秒"


def _make_tree_child(
    row: dict[str, Any],
    *,
    relation: str,
    category_label: str,
    detail: Optional[dict[str, Any]] = None,
    child_rows: Optional[list[dict[str, Any]]] = None,
    fallback_id: str = "",
) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or fallback_id),
        "relation": relation,
        "category": row.get("category"),
        "category_label": category_label,
        "action": row.get("action"),
        "status": row.get("status"),
        "summary": row.get("summary"),
        "task_id": row.get("task_id"),
        "created_at": row.get("created_at"),
        "source_path": row.get("source_path"),
        "rjcode": row.get("rjcode"),
        "detail": detail if isinstance(detail, dict) else (row.get("detail") if isinstance(row.get("detail"), dict) else {}),
        "child_rows": child_rows if isinstance(child_rows, list) else [],
    }


def _append_tree_child(parent_row: dict[str, Any], child_row: dict[str, Any]) -> None:
    parent_detail = parent_row.get("detail") if isinstance(parent_row.get("detail"), dict) else {}
    child_rows = list(parent_detail.get("child_rows") or [])
    child_rows.append(child_row)
    deduped_child_rows: list[dict[str, Any]] = []
    dedupe_index: dict[str, int] = {}
    for item in child_rows:
        item_detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        dedupe_key = "|".join([
            str(item.get("relation") or item.get("category") or "").strip(),
            str(item.get("task_id") or item_detail.get("task_id") or "").strip(),
            str(item.get("source_path") or item_detail.get("preview_source_path") or "").strip(),
            str(item.get("rjcode") or item_detail.get("target_rjcode") or item_detail.get("source_rjcode") or "").strip().upper(),
            str(item.get("action") or "").strip(),
        ])
        current_dt = _coerce_dt(item.get("latest_activity_at") or item.get("created_at")) or datetime.min
        if dedupe_key in dedupe_index:
            previous_index = dedupe_index[dedupe_key]
            previous_item = deduped_child_rows[previous_index]
            previous_dt = _coerce_dt(previous_item.get("latest_activity_at") or previous_item.get("created_at")) or datetime.min
            if current_dt >= previous_dt:
                deduped_child_rows[previous_index] = item
            continue
        dedupe_index[dedupe_key] = len(deduped_child_rows)
        deduped_child_rows.append(item)
    child_rows = deduped_child_rows
    child_rows = sorted(
        child_rows,
        key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min
    )
    latest_activity = _coerce_dt(parent_row.get("created_at")) or datetime.min
    for item in child_rows:
        latest_activity = max(latest_activity, _coerce_dt(item.get("created_at")) or datetime.min)
    parent_row["detail"] = {
        **parent_detail,
        "child_rows": child_rows,
        "child_row_count": len(child_rows),
        "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at"),
    }
    parent_row["has_child_rows"] = True
    parent_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else parent_row.get("created_at")


def _walk_tree_rows(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        out.append(node)
        child_nodes = node.get("child_rows") if isinstance(node.get("child_rows"), list) else []
        if child_nodes:
            out.extend(_walk_tree_rows(child_nodes))
    return out


def _max_tree_activity(node: dict[str, Any]) -> datetime:
    latest = _coerce_dt(node.get("created_at")) or datetime.min
    for child in node.get("child_rows") if isinstance(node.get("child_rows"), list) else []:
        if not isinstance(child, dict):
            continue
        latest = max(latest, _max_tree_activity(child))
    detail = node.get("detail") if isinstance(node.get("detail"), dict) else {}
    for child in detail.get("child_rows") if isinstance(detail.get("child_rows"), list) else []:
        if not isinstance(child, dict):
            continue
        latest = max(latest, _max_tree_activity(child))
    return latest


def _is_success_status(value: Any) -> bool:
    return str(value or "").strip() in {"success", "completed"}


def _is_failed_status(value: Any) -> bool:
    return str(value or "").strip() in {"failed", "cancelled"}


def _common_path_prefix(paths: list[str]) -> str:
    normalized = [str(path or "").strip() for path in paths if str(path or "").strip()]
    if not normalized:
        return ""
    try:
        return os.path.commonpath(normalized)
    except Exception:
        return ""


def _coalesce_import_batch_rows(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not children:
        return []
    latest_success_by_key: dict[str, datetime] = {}
    for child in children:
        key = str(child.get("source_path") or child.get("rjcode") or "").strip()
        if not key or not _is_success_status(child.get("status")):
            continue
        child_dt = _coerce_dt(child.get("latest_activity_at") or child.get("created_at")) or datetime.min
        previous = latest_success_by_key.get(key)
        if previous is None or child_dt >= previous:
            latest_success_by_key[key] = child_dt

    normalized: list[dict[str, Any]] = []
    for child in children:
        key = str(child.get("source_path") or child.get("rjcode") or "").strip()
        child_dt = _coerce_dt(child.get("latest_activity_at") or child.get("created_at")) or datetime.min
        child_detail = child.get("detail") if isinstance(child.get("detail"), dict) else {}
        recovered_by_success = False
        if key and _is_failed_status(child.get("status")):
            recovered_dt = latest_success_by_key.get(key)
            if recovered_dt and recovered_dt >= child_dt:
                recovered_by_success = True
        next_child = dict(child)
        next_detail = dict(child_detail)
        next_detail["recovered_by_success"] = recovered_by_success
        if recovered_by_success:
            next_detail["recovered_badge"] = "已覆盖"
            next_child["recovered_badge"] = "已覆盖"
        next_child["detail"] = next_detail
        normalized.append(next_child)
    return normalized


def _import_row_match_key(row: dict[str, Any]) -> str:
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    rj_candidates = [
        row.get("rjcode"),
        detail.get("rjcode"),
        detail.get("linked_source_rjcode"),
        detail.get("linked_target_rjcode"),
        detail.get("source_basename"),
        row.get("source_path"),
        detail.get("archive_path"),
        row.get("summary"),
        row.get("task_id"),
    ]
    rjcode = ""
    for candidate in rj_candidates:
        text = str(candidate or "").strip().upper()
        if not text:
            continue
        repeated = re.search(r"(?:RJ)+(\d{4,})", text, re.IGNORECASE)
        if repeated:
            rjcode = f"RJ{repeated.group(1)}"
            break
        matched = re.search(r"RJ\d{4,}", text, re.IGNORECASE)
        if matched:
            rjcode = matched.group(0).upper()
            break
    if rjcode:
        return rjcode
    source_path = str(
        row.get("source_path")
        or detail.get("archive_path")
        or detail.get("source_path")
        or ""
    ).strip()
    if source_path:
        return os.path.normcase(os.path.abspath(source_path))
    return ""


def _build_latest_import_success_map(raw_rows: list[dict[str, Any]]) -> dict[str, datetime]:
    latest_success_by_key: dict[str, datetime] = {}
    for row in raw_rows:
        if str(row.get("category") or "").strip() not in {"auto_import", "process_existing"}:
            continue
        if not _is_success_status(row.get("status")):
            continue
        key = _import_row_match_key(row)
        if not key:
            continue
        row_dt = _coerce_dt(row.get("latest_activity_at") or row.get("created_at")) or datetime.min
        previous = latest_success_by_key.get(key)
        if previous is None or row_dt >= previous:
            latest_success_by_key[key] = row_dt
    return latest_success_by_key


def _is_recovered_import_failure(row: dict[str, Any], latest_success_by_key: dict[str, datetime]) -> bool:
    if str(row.get("category") or "").strip() not in {"auto_import", "process_existing"}:
        return False
    if not _is_failed_status(row.get("status")):
        return False
    key = _import_row_match_key(row)
    if not key:
        return False
    row_dt = _coerce_dt(row.get("latest_activity_at") or row.get("created_at")) or datetime.min
    recovered_dt = latest_success_by_key.get(key)
    return bool(recovered_dt and recovered_dt >= row_dt)


def _is_successful_pair_state(row: dict[str, Any]) -> bool:
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    pair_status = str(
        row.get("merged_pair_status")
        or detail.get("pair_status")
        or ""
    ).strip()
    if pair_status == "success":
        return True
    return bool(detail.get("manual_match_completed"))


def _recompute_subtitle_batch_rollup(batch_row: dict[str, Any]) -> None:
    batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
    child_rows = sorted(
        [
            child for child in (batch_detail.get("child_rows") or [])
            if isinstance(child, dict)
        ],
        key=lambda item: _coerce_dt(item.get("latest_activity_at") or item.get("created_at")) or datetime.min
    )
    if not child_rows:
        return

    descendant_rows = _walk_tree_rows(child_rows)
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
        if _is_successful_pair_state(item)
        or any(
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
        if not _is_successful_pair_state(item)
        and bool((item.get("detail") if isinstance(item.get("detail"), dict) else {}).get("awaiting_manual_match"))
    )
    unpaired_child_count = max(0, len(crawl_descendants) - paired_child_count)

    latest_pair_row = None
    latest_pair_dt = datetime.min
    for pair_item in pair_descendants:
        if str(pair_item.get("status") or "").strip() != "success":
            continue
        pair_dt = _coerce_dt(pair_item.get("created_at")) or datetime.min
        if pair_dt >= latest_pair_dt:
            latest_pair_row = pair_item
            latest_pair_dt = pair_dt
    if not latest_pair_row:
        for crawl_item in crawl_descendants:
            if not _is_successful_pair_state(crawl_item):
                continue
            crawl_detail = crawl_item.get("detail") if isinstance(crawl_item.get("detail"), dict) else {}
            pair_dt = _coerce_dt(crawl_detail.get("pair_created_at") or crawl_item.get("latest_activity_at") or crawl_item.get("created_at")) or datetime.min
            if pair_dt >= latest_pair_dt:
                latest_pair_row = crawl_item
                latest_pair_dt = pair_dt

    latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
    for child in child_rows:
        latest_activity = max(latest_activity, _max_tree_activity(child))

    pair_detail = latest_pair_row.get("detail") if isinstance(latest_pair_row, dict) and isinstance(latest_pair_row.get("detail"), dict) else {}
    batch_row["detail"] = {
        **batch_detail,
        "child_rows": child_rows,
        "child_row_count": len(child_rows),
        "paired_child_count": paired_child_count,
        "awaiting_manual_child_count": awaiting_manual_child_count,
        "unpaired_child_count": unpaired_child_count,
        "pair_linked": bool(latest_pair_row),
        "pair_status": str(
            (latest_pair_row or {}).get("status")
            or pair_detail.get("pair_status")
            or ""
        ).strip() if latest_pair_row else "",
        "pair_summary": str(
            (latest_pair_row or {}).get("summary")
            or pair_detail.get("pair_summary")
            or ""
        ).strip() if latest_pair_row else "",
        "pair_created_at": (
            (latest_pair_row or {}).get("created_at")
            or pair_detail.get("pair_created_at")
            or ""
        ) if latest_pair_row else "",
        "latest_activity_at": latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at"),
    }
    batch_row["has_child_rows"] = True
    batch_row["latest_activity_at"] = latest_activity.isoformat() if latest_activity != datetime.min else batch_row.get("created_at")
    if latest_pair_row:
        batch_row["merged_pair"] = True
        batch_row["merged_pair_status"] = str(
            latest_pair_row.get("status")
            or pair_detail.get("pair_status")
            or ""
        ).strip()
