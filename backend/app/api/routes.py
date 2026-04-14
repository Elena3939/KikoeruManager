from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import uuid

# Create logger instance
logger = logging.getLogger(__name__)

from ..models.database import init_db, get_db, get_db_path_info, ActivityLog, ASMRDownloadSession, SessionLocal
from ..core.task_engine import TaskEngine, Task, TaskType, get_task_engine
from ..core.watcher import get_watcher
from ..core.password_cleanup import get_cleanup_service
from ..core.processed_archive_cleanup import get_processed_archive_cleanup_service
from ..core.backup_zip_service import get_backup_zip_service
from ..core.file_processor import get_file_processor
from ..core.library_manager import get_library_manager
from ..core.password_utils import (
    normalize_filename_value,
    normalize_optional_text,
    normalize_password_value,
    normalize_rjcode_value,
)
from ..config.settings import get_config, save_config

# 初始化FastAPI应用
app = FastAPI(
    title="Prekikoeru API",
    description="DLsite作品整理工具API",
    version="1.0.0"
)

# ========== 健康检查 API ==========
@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "prekikoeru",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/activity-logs")
async def list_activity_logs(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """分页查询操作审计记录。"""
    from ..core.activity_log_service import CATEGORY_LABELS

    def _merge_activity_rows(raw_rows: List[ActivityLog]) -> List[Dict[str, Any]]:
        rows = [row.to_dict() for row in raw_rows]
        for row in rows:
            row["category_label"] = CATEGORY_LABELS.get(row.get("category"), row.get("category"))

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

        crawl_by_task: dict[str, dict[str, Any]] = {}
        crawl_rows_by_task: dict[str, list[dict[str, Any]]] = {}
        pair_rows_by_task: dict[str, list[dict[str, Any]]] = {}
        merged_pair_ids: set[str] = set()
        merged_filter_preview_ids: set[str] = set()
        merged_filter_retry_ids: set[str] = set()
        merged_subtitle_import_ids: set[str] = set()
        merged_import_batch_child_ids: set[str] = set()
        import_batch_child_rows_by_source_id: dict[str, dict[str, Any]] = {}

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

        for (category_key, batch_id), batch_row in import_batch_rows_by_key.items():
            batch_detail = batch_row.get("detail") if isinstance(batch_row.get("detail"), dict) else {}
            child_rows: list[dict[str, Any]] = []
            latest_activity = _coerce_dt(batch_row.get("created_at")) or datetime.min
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
                matched_by_batch_id = bool(row_batch_id) and row_batch_id == batch_id
                matched_by_parent_manifest = (
                    (row_task_id and row_task_id in batch_created_task_ids)
                    or (row_source_path and row_source_path in batch_source_paths)
                )
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
                if row.get("action") == "batch_api_rename":
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

        circle_index_rows_by_circle: dict[str, list[dict[str, Any]]] = {}
        circle_refresh_rows_by_circle: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if str(row.get("category") or "").strip() != "circle_completion":
                continue
            action = str(row.get("action") or "").strip()
            if action not in {"index_completed", "refresh_selected_works"}:
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            circle_id = str(detail.get("circle_id") or "").strip()
            if not circle_id:
                continue
            if action == "index_completed":
                circle_index_rows_by_circle.setdefault(circle_id, []).append(row)
            elif action == "refresh_selected_works":
                circle_refresh_rows_by_circle.setdefault(circle_id, []).append(row)

        for circle_id, circle_rows in circle_index_rows_by_circle.items():
            circle_rows.sort(key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)

        for circle_id, circle_rows in circle_refresh_rows_by_circle.items():
            circle_rows.sort(key=lambda item: _coerce_dt(item.get("created_at")) or datetime.min)

        for row in rows:
            if str(row.get("category") or "").strip() != "circle_completion":
                continue
            if str(row.get("action") or "").strip() != "download_batch_start":
                continue

            row_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            circle_id = str(row_detail.get("circle_id") or "").strip()
            if not circle_id:
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

            child_detail = {
                **row_detail,
                "batch_task_count": len(row_detail.get("items") or []),
            }
            child_row = _make_tree_child(
                row,
                relation="download_batch",
                category_label="下载任务",
                detail=child_detail,
            )
            _append_tree_child(parent_row, child_row)
            parent_row["merged_circle_completion_download"] = True
            parent_row["merged_circle_completion_download_status"] = row.get("status") or ""
            merged_circle_completion_ids.add(str(row.get("id") or ""))

        for row in rows:
            if str(row.get("category") or "").strip() != "circle_completion":
                continue
            if str(row.get("action") or "").strip() not in {"task_finished", "task_finished_incomplete"}:
                continue

            row_detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            circle_id = str(row_detail.get("circle_id") or "").strip()
            if not circle_id:
                continue

            source_action = str(row.get("source_action") or row_detail.get("source_action") or "").strip()
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
            "task_retried": ("asmr_session", "任务重试"),
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
            rollup_status = original_parent_status
            if success_count > 0 and failed_count <= 0:
                rollup_status = "success"
            elif success_count > 0 and failed_count > 0:
                rollup_status = "partial_success"
            elif failed_count > 0:
                rollup_status = "failed"
            elif upload_mode == "disabled" and (download_root or downloaded_bytes > 0):
                rollup_status = "success"

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
                child_rows.append(
                    _make_tree_child(
                        row,
                        relation=relation,
                        category_label=category_label,
                    )
                )
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
            if str(row.get("id") or "") in merged_asmr_sync_ids:
                continue
            items.append(row)
        items.sort(key=lambda item: str(item.get("latest_activity_at") or item.get("created_at") or ""), reverse=True)
        return items

    page = max(1, page)
    limit = max(1, min(200, limit))
    query = db.query(ActivityLog)
    if category:
        query = query.filter(ActivityLog.category == category)
    if status:
        query = query.filter(ActivityLog.status == status)
    if q and str(q).strip():
        term = f"%{str(q).strip()}%"
        query = query.filter(
            or_(
                ActivityLog.summary.like(term),
                ActivityLog.rjcode.like(term),
                ActivityLog.source_path.like(term),
                ActivityLog.task_id.like(term),
            )
        )
    raw_rows = query.order_by(desc(ActivityLog.created_at)).all()
    merged_items = _merge_activity_rows(raw_rows)
    total = len(merged_items)
    start = (page - 1) * limit
    end = start + limit
    return {"total": total, "page": page, "limit": limit, "items": merged_items[start:end]}


@app.get("/api/activity-logs/stats")
async def activity_logs_stats(
    days: int = 14,
    db: Session = Depends(get_db),
):
    """按天、分类、状态聚合（用于图表）。"""
    from ..core.activity_log_service import CATEGORY_LABELS
    from datetime import timedelta

    days = int(days)
    all_time = days <= 0
    days = 0 if all_time else max(1, min(90, days))
    cutoff = None if all_time else (datetime.now() - timedelta(days=days))
    day_expr = func.strftime("%Y-%m-%d", ActivityLog.created_at)

    day_query = db.query(day_expr.label("day"), func.count(ActivityLog.id))
    if cutoff is not None:
        day_query = day_query.filter(ActivityLog.created_at >= cutoff)
    day_rows = day_query.group_by(day_expr).order_by(day_expr).all()
    by_day = [{"date": a, "count": b} for a, b in day_rows if a]

    cat_query = db.query(ActivityLog.category, func.count(ActivityLog.id))
    if cutoff is not None:
        cat_query = cat_query.filter(ActivityLog.created_at >= cutoff)
    cat_rows = cat_query.group_by(ActivityLog.category).all()
    by_category = [
        {
            "category": c,
            "label": CATEGORY_LABELS.get(c, c),
            "count": n,
        }
        for c, n in sorted(cat_rows, key=lambda x: -x[1])
    ]

    status_query = db.query(ActivityLog.status, func.count(ActivityLog.id))
    if cutoff is not None:
        status_query = status_query.filter(ActivityLog.created_at >= cutoff)
    status_rows = status_query.group_by(ActivityLog.status).all()
    by_status = {str(s): int(n) for s, n in status_rows if s}
    total_in_range = sum(by_status.values())

    metric_query = db.query(ActivityLog.category, ActivityLog.action, ActivityLog.status, ActivityLog.detail)
    if cutoff is not None:
        metric_query = metric_query.filter(ActivityLog.created_at >= cutoff)
    metric_rows = metric_query.all()
    metrics = {
        "subtitle_download_count": 0,
        "subtitle_match_count": 0,
        "subtitle_crawl_count": 0,
        "subtitle_import_count": 0,
        "extract_count": 0,
        "delete_count": 0,
        "delete_bytes": 0,
        "extract_bytes": 0,
    }
    for category, action, status, detail in metric_rows:
        if status not in {"success", "completed", "partial_success"}:
            continue
        payload = detail if isinstance(detail, dict) else {}
        if category == "subtitle_crawl":
            metrics["subtitle_crawl_count"] += 1
            metrics["subtitle_download_count"] += int(payload.get("downloaded_count") or 0)
        elif category == "subtitle_pair":
            metrics["subtitle_match_count"] += int(
                payload.get("applied_pairs")
                or payload.get("manual_match_applied_pairs")
                or payload.get("matched_group_count")
                or payload.get("final_file_count")
                or 0
            )
        elif category == "subtitle_import":
            metrics["subtitle_import_count"] += int(payload.get("final_file_count") or 1)
        elif category == "extract":
            metrics["extract_count"] += 1
            metrics["extract_bytes"] += int(
                payload.get("extract_output_bytes")
                or payload.get("output_size_bytes")
                or 0
            )
        elif category == "auto_import":
            if payload.get("extract_performed") or payload.get("archive_input"):
                metrics["extract_count"] += 1
                metrics["extract_bytes"] += int(
                    payload.get("extract_output_bytes")
                    or payload.get("output_size_bytes")
                    or 0
                )
        elif category == "pipeline_filter" and action == "filter_delete_apply":
            metrics["delete_count"] += int(payload.get("success_count") or 0)
            metrics["delete_bytes"] += int(payload.get("deleted_bytes") or 0)
        elif category == "pipeline_delete":
            if action == "batch_api_delete":
                metrics["delete_count"] += int(payload.get("success_count") or 0)
            elif action in {"delete", "batch_delete_item"} and status in {"success", "completed"}:
                metrics["delete_count"] += 1

    return {
        "days": days,
        "total_in_range": total_in_range,
        "by_day": by_day,
        "by_category": by_category,
        "by_status": by_status,
        "metrics": metrics,
        "db_path": get_db_path_info(),
    }


@app.post("/api/activity-logs/filter-delete")
async def create_filter_delete_activity_log(request: Request):
    """写入删除过滤预审 / 执行的操作记录。"""
    from ..core.activity_log_service import (
        log_filter_delete_apply_result,
        log_filter_delete_preview_result,
        log_filter_delete_retry_result,
    )

    try:
        data = await request.json()
        mode = str(data.get("mode") or "").strip()
        if mode == "preview":
            log_filter_delete_preview_result(data)
        elif mode == "retry_preview":
            log_filter_delete_retry_result(data)
        elif mode == "apply":
            log_filter_delete_apply_result(data)
        else:
            raise HTTPException(status_code=400, detail="不支持的删除过滤日志类型")
        return {"message": "操作记录已写入"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"写入删除过滤操作记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"写入删除过滤操作记录失败: {str(e)}")


@app.post("/api/activity-logs/backfill-auto-import-extract")
async def backfill_auto_import_extract_activity_logs():
    """一次性回填旧 auto_import 操作记录中的解压字段。"""
    from ..core.activity_log_service import backfill_auto_import_extract_fields

    try:
        result = backfill_auto_import_extract_fields()
        return {
            "message": "auto_import 解压字段回填完成",
            **result,
        }
    except Exception as e:
        logger.error(f"回填 auto_import 解压字段失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"回填 auto_import 解压字段失败: {str(e)}")


# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    # 初始化数据库
    init_db()

    # 启动任务引擎
    engine = get_task_engine()
    engine.start()

    # 如果配置了自动启动监视器，则启动
    config = get_config()
    if config.watcher.enabled:
        watcher = get_watcher()
        watcher.start()

    # 启动密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.start()

    # 启动已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.start()

    # 扫描已处理压缩包目录，同步数据库（根据配置决定是否启用）
    config = get_config()
    if config.processed_archive_cleanup.scan_on_startup:
        await scan_processed_archives()
    else:
        logger.info("启动时扫描已处理压缩包目录已禁用")

# 关闭事件
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    # 停止任务引擎
    engine = get_task_engine()
    engine.stop()

    # 停止监视器
    watcher = get_watcher()
    watcher.stop()

    # 停止密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.stop()

    # 停止已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.stop()

# Pydantic模型
class TaskCreate(BaseModel):
    source_path: str
    task_type: str = "auto_process"
    auto_classify: bool = True
    target_library_id: Optional[str] = None

class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    source_path: str
    output_path: Optional[str]
    progress: int
    current_step: str
    error_message: Optional[str]
    rjcode: Optional[str] = None
    
    class Config:
        from_attributes = True


class TaskCenterOverviewResponse(BaseModel):
    generated_at: str
    total: int
    counts_by_domain: Dict[str, int]
    counts_by_status: Dict[str, int]
    highlight_counts: Dict[str, int]
    recent_items: List[Dict[str, Any]]
    active_items: List[Dict[str, Any]]


class TaskCenterItemResponse(BaseModel):
    id: str
    entity_id: str
    engine_task_id: Optional[str] = None
    record_id: Optional[str] = None
    domain: str
    domain_label: str
    kind: str
    kind_label: str
    title: str
    subtitle: str
    source_label: str
    source_page: str
    source_action: str
    route_hint: str
    status: str
    status_label: str
    progress: int
    current_step: str
    error_message: str
    source_path: str
    target_path: str
    rjcode: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metrics: List[Dict[str, str]]
    actions: List[str]
    details: Dict[str, Any]


class TaskCenterActionRequest(BaseModel):
    action: str

class ConfigResponse(BaseModel):
    storage: dict
    processing: dict
    watcher: dict
    extract: Optional[dict] = None
    filter: dict
    metadata: dict
    rename: dict
    classification: list
    password_cleanup: Optional[dict] = None
    processed_archive_cleanup: Optional[dict] = None
    path_mapping: Optional[dict] = None
    kikoeru_server: Optional[dict] = None
    asmr_sync: Optional[dict] = None
    auto_process: Optional[dict] = None
    process_existing: Optional[dict] = None
    asmr_sync_step: Optional[dict] = None
    rj_subtitle: Optional[dict] = None
    backup_zip: Optional[dict] = None

# API路由
# 兼容层：旧任务接口仅保留给少数历史入口使用，新功能统一走 /api/task-center/*
@app.post("/api/tasks", response_model=TaskResponse, deprecated=True, summary="兼容层：创建原始引擎任务")
async def create_task(task_create: TaskCreate):
    """兼容层：创建原始引擎任务，新功能请改用任务中心聚合接口。"""
    from ..core.file_processor import get_file_processor

    file_processor = get_file_processor()
    config = get_config()

    # 使用 FileProcessor 处理文件
    task = await file_processor.process_file(
        task_create.source_path,
        auto_classify=task_create.auto_classify,
        wait_stable=False,  # 手动创建任务时不等待稳定
        is_processed=lambda path: False,  # 允许重新处理
        mark_processed=None
    )

    if not task:
        raise HTTPException(status_code=400, detail=f"无法处理文件: {task_create.source_path}")

    if task_create.target_library_id:
        task.task_metadata["target_library_id"] = task_create.target_library_id

    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        source_path=task.source_path,
        output_path=task.output_path,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        rjcode=task.rjcode
    )

# ========== 文件上传 API ==========
@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), target_library_id: Optional[str] = Form(None)):
    """上传文件并触发扫描（复用分卷识别逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 确保输入目录存在
    os.makedirs(input_path, exist_ok=True)

    uploaded_files = []

    for file in files:
        if not file.filename:
            continue

        # 保存文件到输入目录
        file_path = os.path.join(input_path, file.filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        uploaded_files.append(file_path)
        logger.info(f"上传文件: {file.filename} -> {file_path}")

    # 不再为每个文件单独创建任务
    # 改为调用扫描逻辑，复用分卷文件识别
    # 扫描逻辑会正确识别分卷文件，只为主文件创建任务
    scan_result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="upload_scan",
        source_label="仪表盘 / 上传后扫描",
        target_library_id=target_library_id,
    )
    if target_library_id and scan_result["task_ids"]:
        engine = get_task_engine()
        for task_id in scan_result["task_ids"]:
            task = engine.get_task(task_id)
            if task:
                task.task_metadata["target_library_id"] = target_library_id

    return {
        "message": f"成功上传 {len(uploaded_files)} 个文件，{scan_result['message']}",
        "uploaded_count": len(uploaded_files),
        "found_count": scan_result["found_count"],
        "task_ids": scan_result["task_ids"]
    }


async def _scan_and_create_tasks(
    *,
    source_page: str = "dashboard",
    source_action: str = "scan_input",
    source_label: str = "仪表盘 / 扫描导入",
    target_library_id: Optional[str] = None,
):
    """扫描输入目录并创建任务（使用 FileProcessor 统一处理逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 自动创建目录（如果不存在）
    if not os.path.exists(input_path):
        try:
            os.makedirs(input_path, exist_ok=True)
            logger.info(f"自动创建输入目录: {input_path}")
        except Exception as e:
            return {"message": f"无法创建输入目录: {str(e)}", "found_count": 0, "task_ids": []}

    watcher = get_watcher()
    file_processor = get_file_processor()
    from ..core.activity_log_service import log_import_batch_start_result

    batch_id = str(uuid.uuid4())
    batch_context = {
        "batch_id": batch_id,
        "session_id": batch_id,
        "batch_title": "批量解压入库",
        "batch_label": "解压入库批次",
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "log_parent": True,
    }
    report: dict[str, Any] = {
        "requested_count": 0,
        "created_count": 0,
        "skipped_processed_count": 0,
        "skipped_duplicate_count": 0,
    }

    # 使用 FileProcessor 统一处理目录
    tasks = await file_processor.process_directory(
        input_path,
        auto_classify=config.watcher.auto_classify,
        is_processed=lambda path: (
            path in watcher.pending_files or
            path in watcher._processed_files or
            any(t.source_path == path and t.status.value in ["pending", "processing"]
                for t in get_task_engine().get_all_tasks())
        ),
        mark_processed=watcher._mark_file_processed,
        task_metadata={"target_library_id": target_library_id} if target_library_id else None,
        batch_context=batch_context,
        report=report,
    )

    created_task_ids = [task.id for task in tasks]
    requested_count = int(report.get("requested_count") or len(tasks))
    created_tasks = [{"task_id": task.id, "source_path": task.source_path} for task in tasks]
    log_import_batch_start_result({
        "batch_id": batch_id,
        "requested_count": requested_count,
        "created_count": len(tasks),
        "skipped_total": int(report.get("skipped_processed_count") or 0) + int(report.get("skipped_duplicate_count") or 0),
        "skipped_processed": int(report.get("skipped_processed_count") or 0),
        "skipped_duplicate": int(report.get("skipped_duplicate_count") or 0),
        "archive_count": requested_count,
        "extracted_count": len(tasks),
        "auto_classify": bool(config.watcher.auto_classify),
        "target_library_id": target_library_id,
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "source_paths": [task.source_path for task in tasks],
        "created_tasks": created_tasks,
        "skipped_items": [],
        "source_path": input_path,
    })

    return {
        "message": f"找到 {len(tasks)} 个待处理文件",
        "found_count": len(tasks),
        "task_ids": created_task_ids,
        "batch_id": batch_id,
    }

@app.get("/api/backup/history")
async def get_backup_history():
    """获取备份历史记录"""
    from ..models.database import BackupRecord, get_db
    
    db = next(get_db())
    try:
        records = db.query(BackupRecord).order_by(desc(BackupRecord.created_at)).all()
        return [record.to_dict() for record in records]
    finally:
        db.close()

@app.get("/api/tasks", response_model=List[TaskResponse], deprecated=True, summary="兼容层：获取原始引擎任务列表")
async def get_tasks(status: Optional[str] = None):
    """兼容层：获取原始引擎任务列表，新功能请改用 /api/task-center/list。"""
    engine = get_task_engine()
    
    if status == "pending":
        tasks = engine.get_pending_tasks()
    elif status == "processing":
        tasks = engine.get_processing_tasks()
    elif status == "completed":
        tasks = engine.get_completed_tasks()
    else:
        tasks = engine.get_all_tasks()
    
    return [
        TaskResponse(
            id=task.id,
            type=task.type.value,
            status=task.status.value,
            source_path=task.source_path,
            output_path=task.output_path,
            progress=task.progress,
            current_step=task.current_step,
            error_message=task.error_message,
            rjcode=task.rjcode
        )
        for task in tasks
    ]


@app.get("/api/task-center/overview", response_model=TaskCenterOverviewResponse)
async def get_task_center_overview():
    """获取任务中心总览摘要。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.get_overview()


@app.get("/api/task-center/list", response_model=List[TaskCenterItemResponse])
async def get_task_center_list(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
):
    """获取任务中心统一任务列表。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.list_items(domain=domain, status=status, search=search, limit=limit)


@app.get("/api/task-center/item", response_model=Optional[TaskCenterItemResponse])
async def get_task_center_item(item_id: Optional[str] = None, engine_task_id: Optional[str] = None):
    """按任务中心 ID 或引擎任务 ID 获取单项。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.get_item(item_id=item_id, engine_task_id=engine_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/task-center/diagnose")
async def diagnose_task_center_serialization():
    """诊断任务中心聚合中具体是哪条数据序列化失败。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.diagnose_serialization_failures()


@app.post("/api/task-center/{item_id}/action")
async def execute_task_center_action(item_id: str, payload: TaskCenterActionRequest):
    """执行任务中心统一动作。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.execute_action(item_id, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/tasks/{task_id}", response_model=TaskResponse, deprecated=True, summary="兼容层：获取原始引擎任务")
async def get_task(task_id: str):
    """兼容层：获取原始引擎任务详情，新功能请改用 /api/task-center/item。"""
    engine = get_task_engine()
    task = engine.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        source_path=task.source_path,
        output_path=task.output_path,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        rjcode=task.rjcode
    )

@app.post("/api/tasks/{task_id}/pause", deprecated=True, summary="兼容层：暂停原始引擎任务")
async def pause_task(task_id: str):
    """兼容层：暂停原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.pause_task(task_id)
    return {"message": "任务已暂停"}

@app.post("/api/tasks/{task_id}/resume", deprecated=True, summary="兼容层：恢复原始引擎任务")
async def resume_task(task_id: str):
    """兼容层：恢复原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.resume_task(task_id)
    return {"message": "任务已恢复"}

@app.post("/api/tasks/{task_id}/cancel", deprecated=True, summary="兼容层：取消原始引擎任务")
async def cancel_task(task_id: str):
    """兼容层：取消原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.cancel_task(task_id)
    return {"message": "任务已取消"}

@app.get("/api/config", response_model=ConfigResponse)
async def get_configuration():
    """获取配置"""
    config = get_config()
    storage_data = config.storage.model_dump()
    library_cfg = get_library_manager().load_config()
    storage_data["default_library_id"] = library_cfg["default_library_id"]
    storage_data["default_extract_library_id"] = library_cfg["default_extract_library_id"]
    storage_data["health_warning_free_gb"] = library_cfg["health_warning_free_gb"]
    storage_data["stats_cache_ttl_seconds"] = library_cfg["stats_cache_ttl_seconds"]
    return ConfigResponse(
        storage=storage_data,
        processing=config.processing.model_dump(),
        watcher=config.watcher.model_dump(),
        extract=config.extract.model_dump(),
        filter=config.filter.model_dump(),
        metadata=config.metadata.model_dump(),
        rename=config.rename.model_dump(),
        classification=[rule.model_dump() for rule in config.classification],
        password_cleanup=config.password_cleanup.model_dump(),
        processed_archive_cleanup=config.processed_archive_cleanup.model_dump(),
        path_mapping=config.path_mapping.model_dump(),
        kikoeru_server=config.kikoeru_server.model_dump() if hasattr(config, 'kikoeru_server') else None,
        asmr_sync=config.asmr_sync.model_dump() if hasattr(config, 'asmr_sync') else None,
        auto_process=config.auto_process.model_dump() if hasattr(config, 'auto_process') else None,
        process_existing=config.process_existing.model_dump() if hasattr(config, 'process_existing') else None,
        asmr_sync_step=config.asmr_sync_step.model_dump() if hasattr(config, 'asmr_sync_step') else None,
        rj_subtitle=config.rj_subtitle.model_dump() if hasattr(config, 'rj_subtitle') else None,
        backup_zip=config.backup_zip.model_dump() if hasattr(config, 'backup_zip') else None
    )

@app.post("/api/config")
async def update_configuration(request: Request):
    """更新配置"""
    from ..config.settings import save_config, ClassificationRule, FilterRule, PathMappingRule
    try:
        config_data = await request.json()
        logger.info(f"接收到配置保存请求，classification: {config_data.get('classification')}")
        
        # 记录重命名模板用于调试
        if 'rename' in config_data and config_data['rename']:
            template = config_data['rename'].get('template', 'NOT SET')
            logger.info(f"[CONFIG SAVE] 接收到的模板: '{template}'")
        
        # 确保 classification 字段格式正确
        if 'classification' in config_data and config_data['classification']:
            validated_rules = []
            for rule_data in config_data['classification']:
                try:
                    # 清理 None 值
                    rule_data_cleaned = {k: v for k, v in rule_data.items() if v is not None}
                    # 使用 Pydantic 验证每个规则
                    rule = ClassificationRule(**rule_data_cleaned)
                    validated_rules.append(rule.dict())
                    logger.info(f"规则验证通过: {rule_data_cleaned}")
                except Exception as e:
                    logger.warning(f"分类规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['classification'] = validated_rules
            logger.info(f"验证后的分类规则: {validated_rules}")
        
        # 确保 filter 字段格式正确
        if 'filter' in config_data and config_data['filter'] and 'rules' in config_data['filter']:
            validated_filter_rules = []
            for rule_data in config_data['filter']['rules']:
                try:
                    # 确保 target 字段存在
                    if 'target' not in rule_data or not rule_data['target']:
                        rule_data['target'] = 'file'
                    # 使用 Pydantic 验证
                    rule = FilterRule(**rule_data)
                    validated_filter_rules.append(rule.dict())
                    logger.info(f"过滤规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"过滤规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['filter']['rules'] = validated_filter_rules
            logger.info(f"验证后的过滤规则数: {len(validated_filter_rules)}")
        
        # 确保 path_mapping 字段格式正确
        if 'path_mapping' in config_data and config_data['path_mapping'] and 'rules' in config_data['path_mapping']:
            validated_path_rules = []
            for rule_data in config_data['path_mapping']['rules']:
                try:
                    rule = PathMappingRule(**rule_data)
                    validated_path_rules.append(rule.dict())
                    logger.info(f"路径映射规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"路径映射规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['path_mapping']['rules'] = validated_path_rules
            logger.info(f"验证后的路径映射规则数: {len(validated_path_rules)}")
        
        # 处理 Kikoeru 服务器配置
        if 'kikoeru_server' in config_data:
            logger.info(f"[KIKOERU] 接收到 Kikoeru 服务器配置: {config_data['kikoeru_server']}")
            try:
                # 验证 KikoeruServerConfig
                from ..config.settings import KikoeruServerConfig
                kikoeru_config = KikoeruServerConfig(**config_data['kikoeru_server'])
                config_data['kikoeru_server'] = kikoeru_config.model_dump()
                logger.info(f"[KIKOERU] 配置验证通过: enabled={kikoeru_config.enabled}, server_url={kikoeru_config.server_url}")
            except Exception as e:
                logger.error(f"[KIKOERU] Kikoeru 配置验证失败: {e}")
                # 如果验证失败，保留原始配置
        else:
            logger.info("[KIKOERU] 未接收到 Kikoeru 服务器配置")

        # 处理 ASMR 同步配置
        if 'asmr_sync' in config_data:
            logger.info(f"[ASMR] 接收到 ASMR 同步配置: {config_data['asmr_sync']}")
            try:
                from ..config.settings import ASMRSyncConfig
                asmr_config = ASMRSyncConfig(**config_data['asmr_sync'])
                config_data['asmr_sync'] = asmr_config.model_dump()
                logger.info(f"[ASMR] 配置验证通过: retry_cron={asmr_config.retry_cron}")
            except Exception as e:
                logger.error(f"[ASMR] ASMR 同步配置验证失败: {e}")
        else:
            logger.info("[ASMR] 未接收到 ASMR 同步配置")

        if 'backup_zip' in config_data:
            try:
                from ..config.settings import BackupZipConfig
                backup_zip_config = BackupZipConfig(**config_data['backup_zip'])
                config_data['backup_zip'] = backup_zip_config.model_dump()
            except Exception as e:
                logger.error(f"[BACKUP_ZIP] 配置验证失败: {e}")

        if 'rj_subtitle' in config_data:
            try:
                from ..config.settings import RJSubtitleConfig
                rj_subtitle_config = RJSubtitleConfig(**config_data['rj_subtitle'])
                config_data['rj_subtitle'] = rj_subtitle_config.model_dump()
            except Exception as e:
                logger.error(f"[RJ_SUBTITLE] 配置验证失败: {e}")

        result = save_config(config_data)
        logger.info(f"配置已保存，分类规则数: {len(config_data.get('classification', []))}")

        # 重新读取配置文件确保数据已写入
        from ..config.settings import get_config
        current_config = get_config()
        get_task_engine()
        logger.info(f"当前配置中的分类规则: {[r.dict() for r in current_config.classification]}")

        # 如果密码清理配置变更，重启清理服务
        if 'password_cleanup' in config_data:
            logger.info("密码清理配置已变更，重启清理服务...")
            cleanup_service = get_cleanup_service()
            await cleanup_service.restart()
            logger.info("密码清理服务已重启")

        # 如果已处理压缩包清理配置变更，重启清理服务
        if 'processed_archive_cleanup' in config_data:
            logger.info("已处理压缩包清理配置已变更，重启清理服务...")
            archive_cleanup_service = get_processed_archive_cleanup_service()
            await archive_cleanup_service.restart()
            logger.info("已处理压缩包清理服务已重启")

        return {"message": "配置已保存", "config": config_data}
    except Exception as e:
        logger.error(f"保存配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")

@app.post("/api/config/reload")
async def reload_configuration():
    """重新加载配置文件（从磁盘重新读取）"""
    from ..config.settings import reload_config, get_config_file_path
    import os
    
    try:
        config_file_path = get_config_file_path()
        logger.info(f"[CONFIG RELOAD] 重新加载配置文件：{config_file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(config_file_path):
            logger.warning(f"[CONFIG RELOAD] 配置文件不存在：{config_file_path}")
            raise HTTPException(status_code=404, detail=f"配置文件不存在：{config_file_path}")
        
        # 重新加载配置
        new_config = reload_config()
        get_task_engine()
        
        logger.info(f"[CONFIG RELOAD] 配置重新加载成功")
        logger.info(f"[CONFIG RELOAD] storage.input_path = {new_config.storage.input_path}")
        logger.info(f"[CONFIG RELOAD] rename.template = '{new_config.rename.template}'")
        
        return {
            "message": "配置重新加载成功",
            "config_file": config_file_path,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新加载配置失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新加载配置失败：{str(e)}")


@app.get("/api/library-backup/status")
async def get_library_backup_status():
    service = get_backup_zip_service()
    return service.get_status()


@app.post("/api/library-backup/start")
async def start_library_backup():
    service = get_backup_zip_service()
    try:
        return await service.start()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动库存打包失败: {str(e)}")


@app.post("/api/library-backup/cancel")
async def cancel_library_backup():
    service = get_backup_zip_service()
    return await service.cancel()


@app.post("/api/library-backup/resume")
async def resume_library_backup():
    """从断点恢复库存打包任务"""
    service = get_backup_zip_service()
    try:
        return await service.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复库存打包失败: {str(e)}")


@app.get("/api/library-backup/checkpoint")
async def get_library_backup_checkpoint():
    """获取库存打包断点信息"""
    service = get_backup_zip_service()
    checkpoint = service.get_checkpoint_info()
    return checkpoint or {"has_checkpoint": False}


@app.post("/api/watcher/start")
async def start_watcher():
    """启动文件夹监视器"""
    watcher = get_watcher()
    watcher.start()
    return {"message": "监视器已启动"}

@app.post("/api/watcher/stop")
async def stop_watcher():
    """停止文件夹监视器"""
    watcher = get_watcher()
    watcher.stop()
    return {"message": "监视器已停止"}

@app.get("/api/watcher/status")
async def get_watcher_status():
    """获取监视器状态"""
    watcher = get_watcher()
    return {
        "is_running": watcher.is_running,
        "watch_path": get_config().storage.input_path,
        "pending_files": list(watcher.pending_files)
    }

@app.post("/api/scan")
async def scan_input_directory():
    """手动扫描输入目录"""
    result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="scan_input",
        source_label="仪表盘 / 扫描导入",
    )
    return {
        "message": f"扫描完成，找到 {result['found_count']} 个文件",
        "found_count": result["found_count"],
        "task_ids": result["task_ids"],
        "batch_id": result.get("batch_id"),
    }

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ========== 密码库管理 API ==========

class PasswordEntryCreate(BaseModel):
    """创建密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: str
    description: Optional[str] = None
    source: str = "manual"

class PasswordEntryUpdate(BaseModel):
    """更新密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None

class PasswordEntryResponse(BaseModel):
    """密码响应模型"""
    id: str
    rjcode: Optional[str]
    filename: Optional[str]
    password: str
    description: Optional[str]
    source: str
    use_count: int
    last_used_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

class PasswordListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PasswordEntryResponse]

@app.get("/api/passwords", response_model=PasswordListResponse)
async def get_passwords(
    rjcode: Optional[str] = None,
    filename: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20
):
    """获取密码列表，支持筛选和排序
    
    Args:
        rjcode: 按RJ号筛选
        filename: 按文件名筛选
        search: 搜索关键词
        sort_by: 排序字段（created_at, updated_at, rjcode, filename, use_count）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        query = db.query(PasswordEntry)
        
        if rjcode:
            query = query.filter(PasswordEntry.rjcode == rjcode)
        if filename:
            query = query.filter(PasswordEntry.filename.contains(filename))
        if search:
            query = query.filter(
                (PasswordEntry.rjcode.contains(search)) |
                (PasswordEntry.filename.contains(search)) |
                (PasswordEntry.password.contains(search)) |
                (PasswordEntry.description.contains(search))
            )
        
        # 排序功能
        valid_sort_fields = {
            "created_at": PasswordEntry.created_at,
            "updated_at": PasswordEntry.updated_at,
            "rjcode": PasswordEntry.rjcode,
            "filename": PasswordEntry.filename,
            "use_count": PasswordEntry.use_count
        }
        
        # 设置默认排序字段
        sort_field_key = sort_by if sort_by else "created_at"
        sort_field = valid_sort_fields.get(sort_field_key, PasswordEntry.created_at)
        
        # 设置默认排序方向
        order = sort_order.lower() if sort_order else "desc"
        if order == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 200)
        total = query.order_by(None).count()
        passwords = query.offset((safe_page - 1) * safe_page_size).limit(safe_page_size).all()
        return PasswordListResponse(
            total=total,
            page=safe_page,
            page_size=safe_page_size,
            items=[PasswordEntryResponse(**p.to_dict()) for p in passwords]
        )
    finally:
        db.close()

@app.post("/api/passwords", response_model=PasswordEntryResponse)
async def create_password(entry: PasswordEntryCreate):
    """创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    try:
        normalized_rjcode = normalize_rjcode_value(entry.rjcode)
        normalized_filename = normalize_filename_value(entry.filename)
        normalized_password = normalize_password_value(entry.password)
        normalized_description = normalize_optional_text(entry.description)

        # 记录接收到的数据（用于调试）
        logger.info(
            f"创建密码条目 - RJ={normalized_rjcode}, File={normalized_filename}, "
            f"Password长度={len(normalized_password) if normalized_password else 0}"
        )
        
        # 确保密码不为空
        if not normalized_password:
            raise HTTPException(status_code=400, detail="密码不能为空")
        
        # 检查是否已存在相同RJ号或文件名的密码
        existing = None
        if normalized_rjcode:
            existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
        if not existing and normalized_filename:
            existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
        
        if existing:
            # 更新现有密码
            existing.rjcode = normalized_rjcode
            existing.filename = normalized_filename
            existing.password = normalized_password
            existing.description = normalized_description if entry.description is not None else existing.description
            existing.updated_at = datetime.now()
            db.commit()
            logger.info(f"更新密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
            return PasswordEntryResponse(**existing.to_dict())
        
        # 创建新密码条目
        new_entry = PasswordEntry(
            id=str(uuid.uuid4()),
            rjcode=normalized_rjcode,
            filename=normalized_filename,
            password=normalized_password,
            description=normalized_description,
            source=entry.source
        )
        db.add(new_entry)
        db.commit()
        logger.info(f"创建密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
        return PasswordEntryResponse(**new_entry.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建密码条目失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存密码失败: {str(e)}")
    finally:
        db.close()

@app.post("/api/passwords/batch")
async def batch_create_passwords(entries: List[PasswordEntryCreate]):
    """批量创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    created_count = 0
    updated_count = 0
    
    try:
        for entry in entries:
            normalized_rjcode = normalize_rjcode_value(entry.rjcode)
            normalized_filename = normalize_filename_value(entry.filename)
            normalized_password = normalize_password_value(entry.password)
            normalized_description = normalize_optional_text(entry.description)

            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")

            # 检查是否已存在
            existing = None
            if normalized_rjcode:
                existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
            if not existing and normalized_filename:
                existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
            
            if existing:
                # 更新
                existing.rjcode = normalized_rjcode
                existing.filename = normalized_filename
                existing.password = normalized_password
                existing.description = normalized_description if entry.description is not None else existing.description
                existing.updated_at = datetime.now()
                updated_count += 1
            else:
                # 创建新条目
                new_entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    rjcode=normalized_rjcode,
                    filename=normalized_filename,
                    password=normalized_password,
                    description=normalized_description,
                    source=entry.source
                )
                db.add(new_entry)
                created_count += 1
        
        db.commit()
        logger.info(f"批量导入密码: 新建 {created_count} 条, 更新 {updated_count} 条")
        return {
            "message": f"批量导入完成",
            "created": created_count,
            "updated": updated_count
        }
    except Exception as e:
        db.rollback()
        logger.error(f"批量导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量导入失败: {str(e)}")
    finally:
        db.close()

@app.put("/api/passwords/{password_id}", response_model=PasswordEntryResponse)
async def update_password(password_id: str, entry: PasswordEntryUpdate):
    """更新密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")
        
        if entry.rjcode is not None:
            password_entry.rjcode = normalize_rjcode_value(entry.rjcode)
        if entry.filename is not None:
            password_entry.filename = normalize_filename_value(entry.filename)
        if entry.password is not None:
            normalized_password = normalize_password_value(entry.password)
            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")
            password_entry.password = normalized_password
        if entry.description is not None:
            password_entry.description = normalize_optional_text(entry.description)
        
        password_entry.updated_at = datetime.now()
        db.commit()
        
        return PasswordEntryResponse(**password_entry.to_dict())
    finally:
        db.close()

@app.delete("/api/passwords/{password_id}")
async def delete_password(password_id: str):
    """删除密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")
        
        db.delete(password_entry)
        db.commit()
        return {"message": "密码已删除"}
    finally:
        db.close()

@app.get("/api/passwords/find-for-archive")
async def find_password_for_archive(archive_path: str):
    """查找适合指定压缩包的密码"""
    from ..models.database import PasswordEntry, get_db
    from pathlib import Path
    import re
    
    db = next(get_db())
    try:
        filename = Path(archive_path).name
        
        # 提取RJ号
        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
        rjcode = rj_match.group(0).upper() if rj_match else None
        
        # 首先尝试精确匹配RJ号
        if rjcode:
            entry = db.query(PasswordEntry).filter(PasswordEntry.rjcode == rjcode).first()
            if entry:
                return {
                    "found": True,
                    "password": normalize_password_value(entry.password),
                    "match_type": "rjcode",
                    "rjcode": rjcode,
                    "entry": entry.to_dict()
                }
        
        # 其次尝试文件名匹配
        entry = db.query(PasswordEntry).filter(PasswordEntry.filename == filename).first()
        if entry:
            return {
                "found": True,
                "password": normalize_password_value(entry.password),
                "match_type": "filename",
                "entry": entry.to_dict()
            }
        
        return {"found": False, "rjcode": rjcode}
    finally:
        db.close()

@app.post("/api/passwords/import-from-text")
async def import_passwords_from_text(request: Request):
    """从文本批量导入密码 - 每行一个密码，只添加密码不解析RJ号
    
    格式：每行一个密码，系统自动尝试匹配
    """
    from ..models.database import PasswordEntry, get_db
    import uuid
    
    data = await request.json()
    text = data.get("text", "")
    
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    
    db = next(get_db())
    entries = []
    lines = text.strip().split('\n')
    
    try:
        for line in lines:
            password = normalize_password_value(line)
            if not password:
                continue
            
            # 检查该密码是否已存在（避免重复）
            existing = db.query(PasswordEntry).filter(PasswordEntry.password == password).first()
            if existing:
                # 密码已存在，跳过
                entries.append({"password": password, "status": "skipped", "reason": "已存在"})
            else:
                # 创建新的密码条目（只存储密码，不关联RJ号或文件名）
                entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    password=password,
                    source='batch',
                    description='批量导入'
                )
                db.add(entry)
                entries.append({"password": password, "status": "success"})
        
        db.commit()
        success_count = sum(1 for e in entries if e["status"] == "success")
        skipped_count = sum(1 for e in entries if e["status"] == "skipped")
        
        return {
            "message": f"导入完成：新建 {success_count} 个，跳过 {skipped_count} 个（已存在）",
            "imported": success_count,
            "skipped": skipped_count,
            "entries": entries
        }
    except Exception as e:
        db.rollback()
        logger.error(f"导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        db.close()

@app.get("/api/logs")
async def get_logs(lines: int = 100):
    """获取日志文件内容"""
    import os
    from collections import deque
    log_dir = os.environ.get('DATA_PATH', './data')
    log_files = [
        os.path.join(log_dir, 'app.log'),
        os.path.join(log_dir, 'desktop_app.log'),
    ]
    log_file = next((path for path in log_files if os.path.exists(path)), None)
    if not log_file:
        return {"logs": []}
    
    try:
        line_limit = max(50, min(int(lines or 100), 5000))
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            recent_lines = deque((line.strip() for line in f if line.strip()), maxlen=line_limit)
            return {"logs": list(recent_lines)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")

@app.get("/api/conflicts")
async def get_conflicts():
    """获取问题作品列表"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..models.database import ConflictWork, get_db

    db = next(get_db())
    try:
        resolution_service = get_conflict_resolution_service()
        conflicts = db.query(ConflictWork).filter(
            ConflictWork.status == "PENDING",
            ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
        ).all()
        return {
            "conflicts": [
                {
                    "id": conflict.id,
                    "task_id": conflict.task_id,
                    "rjcode": conflict.rjcode,
                    "conflict_type": conflict.conflict_type,
                    "existing_path": conflict.existing_path,
                    "new_path": conflict.new_path,
                    "new_metadata": conflict.new_metadata,
                    "status": conflict.status,
                    "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
                    "available_actions": resolution_service.get_available_actions(conflict),
                    "context": resolution_service.describe_conflict(conflict),
                }
                for conflict in conflicts
            ]
        }
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/retry")
async def retry_extract_failed_conflict(conflict_id: str):
    """重试问题作品中的失败项。"""
    from ..models.database import ConflictWork, get_db
    from ..core.task_engine import TaskStatus

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")
        if conflict.status != "PENDING":
            raise HTTPException(status_code=400, detail="当前问题项已不是待处理状态")
        if conflict.conflict_type not in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            raise HTTPException(status_code=400, detail="只有失败问题项支持重试")

        source_path = str(conflict.new_path or "").strip()
        if not source_path:
            raise HTTPException(status_code=400, detail="缺少待重试的源路径")
        if not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="待重试的源文件不存在")

        engine = get_task_engine()
        normalized_source_path = os.path.normcase(os.path.normpath(source_path))
        existing_task = next(
            (
                task for task in engine.get_all_tasks()
                if os.path.normcase(os.path.normpath(str(task.source_path or ""))) == normalized_source_path
                and task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}
            ),
            None,
        )
        if existing_task:
            existing_task.task_metadata["retry_conflict_id"] = conflict.id
            existing_task.task_metadata["retry_conflict_source_path"] = source_path
            if conflict.task_id:
                existing_task.task_metadata["retry_failed_task_id"] = str(conflict.task_id)
            return {
                "success": True,
                "message": "已存在同源重试任务，继续跟踪当前任务",
                "task_id": existing_task.id,
                "already_running": True,
            }

        source_task_type = str((conflict.new_metadata or {}).get("source_task_type") or TaskType.AUTO_PROCESS.value).strip()
        retry_task_type = TaskType(source_task_type) if source_task_type in {task_type.value for task_type in TaskType} else TaskType.AUTO_PROCESS

        task = Task(
            task_type=retry_task_type,
            source_path=source_path,
            auto_classify=True,
        )
        task.task_metadata["retry_conflict_id"] = conflict.id
        task.task_metadata["retry_conflict_source_path"] = source_path
        task.task_metadata["retry_from_conflicts"] = True
        if conflict.task_id:
            task.task_metadata["retry_failed_task_id"] = str(conflict.task_id)
        if conflict.rjcode:
            task.task_metadata["inferred_rjcode"] = conflict.rjcode

        await engine.submit(task)
        return {
            "success": True,
            "message": "已开始重试失败问题项",
            "task_id": task.id,
            "already_running": False,
        }
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/preview")
async def preview_conflict_resolution(conflict_id: str, payload: dict):
    """生成问题作品处理预览"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..models.database import ConflictWork, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action = service.normalize_action(payload.get("action"))
        if action not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")

        if action == "KEEP_NEW":
            preview = await service.get_delete_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                "preview": preview,
            }

        if action == "MERGE":
            merge_preview = await service.create_merge_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                **merge_preview,
            }

        raise HTTPException(status_code=400, detail="当前动作不需要预览")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("生成问题作品预览失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成处理预览失败: {exc}")
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, action: dict):
    """处理问题作品"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..core.task_engine import TaskStatus, get_task_engine
    from ..models.database import ConflictWork, ProcessedArchive, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action_type = service.normalize_action(action.get("action"))
        if action_type not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")
        confirmed = bool(action.get("confirmed"))

        if action_type == "KEEP_NEW":
            if not confirmed:
                raise HTTPException(status_code=400, detail="保留新版前必须先完成删除审查确认")
            result = await service.resolve_keep_new(conflict)
        elif action_type == "MERGE":
            result = await service.resolve_merge(
                conflict,
                action.get("merge_session_id"),
                action.get("merge_decisions") or {},
            )
        else:
            result = await service.resolve_skip(conflict)

        conflict.status = action_type

        engine = get_task_engine()
        if conflict.task_id:
            engine.update_task_status(str(conflict.task_id), TaskStatus.COMPLETED, f"冲突已处理: {action_type}")

        if conflict.new_path:
            archive_record = db.query(ProcessedArchive).filter(
                ProcessedArchive.filename == os.path.basename(str(conflict.new_path))
            ).first()
            if archive_record:
                archive_record.status = "completed"
                archive_record.processed_at = datetime.now()

        db.commit()
        return {
            "success": True,
            "conflict_id": conflict.id,
            "action": action_type,
            **result,
        }
        
        # 检查new_path是否是压缩包（预检阶段的冲突）
        from ..core.watcher import ArchiveHandler
        temp_handler = ArchiveHandler(lambda x: None, lambda: set(), lambda: False, lambda x: None)
        is_archive = temp_handler._is_archive(conflict.new_path)
        
        if action_type == "KEEP_NEW":
            if os.path.exists(conflict.existing_path):
                shutil.rmtree(conflict.existing_path)
            
            if is_archive:
                logger.info(f"保留新版：先解压压缩包 {conflict.new_path}")
                
                is_in_processed = conflict.new_path.startswith(config.storage.processed_archives_path)
                if is_in_processed:
                    logger.info(f"检测到文件已在 processed 目录中，设置 skip_archive=True: {conflict.new_path}")
                
                # 检查冲突前先确认没有正在执行同RJ编号的操作
                engine = get_task_engine()
                rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path)) 
                
                skip_archive_bool = bool(conflict.new_path.startswith(config.storage.processed_archives_path)) 
                
                # 如果正在处理同样的RJ号，优先复用正在处理的同RJ号的任务
                if rjcode_of_new_path and engine.is_rjcode_processing(rjcode_of_new_path):
                    # 查找正在处理同RJ号的任务
                    existing_tasks_for_rj = [t for t in engine.get_all_tasks() 
                                           if t.rjcode == rjcode_of_new_path and t.status == TaskStatus.PROCESSING]
                    if existing_tasks_for_rj:
                        task = existing_tasks_for_rj[0]
                        # 复用当前正在处理的同RJ号任务
                        original_source = task.source_path
                        task.source_path = str(conflict.new_path)
                        task.skip_archive = skip_archive_bool
                        # 确保任务状态为PROCESSED，以便继续执行
                        task.status = TaskStatus.PROCESSING
                        task.update_progress(10, "解压中")
                        logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                    else:
                        # 使用原有的冲突task_id逻辑
                        original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None
                        
                        if original_task:
                            # 更新原有任务的源路径，复用任务ID
                            original_source = original_task.source_path
                            original_task.source_path = str(conflict.new_path)
                            original_task.skip_archive = skip_archive_bool
                            original_task.status = TaskStatus.PROCESSING
                            original_task.update_progress(10, "解压中")
                            task = original_task
                            logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                        else:
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                else:
                    # 没有正在处理的同RJ任务时，使用原有的逻辑
                    original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None

                    if original_task:
                        # 更新原有任务的源路径，复用任务ID
                        original_source = original_task.source_path
                        original_task.source_path = str(conflict.new_path)
                        original_task.skip_archive = skip_archive_bool
                        original_task.status = TaskStatus.PROCESSING
                        original_task.update_progress(10, "解压中")
                        task = original_task
                        logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                    else:
                        # 检查是否有其他同RJ号的任务存在，如果有就复用
                        rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path))
                        if rjcode_of_new_path:
                            existing_rj_tasks = [t for t in engine.get_all_tasks() 
                                               if t.rjcode == rjcode_of_new_path]
                            if existing_rj_tasks:
                                task = existing_rj_tasks[0]
                                original_source = task.source_path
                                task.source_path = str(conflict.new_path)
                                task.skip_archive = skip_archive_bool
                                task.status = TaskStatus.PROCESSING
                                task.update_progress(10, "解压中")
                                logger.info(f"复用同RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                            else:
                                # 创建新任务
                                task = Task(
                                    task_type=TaskType.AUTO_PROCESS,
                                    source_path=str(conflict.new_path),
                                    auto_classify=True,
                                    skip_archive=skip_archive_bool
                                )
                                engine.tasks[task.id] = task
                                logger.info(f"创建新任务处理: {task.id}")
                        else:
                            # 创建新任务
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                
                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()
                
                extracted_path = await extract_service.extract(task)
                if not extracted_path:
                    error_msg = task.error_message or "解压失败"
                    logger.error(f"处理冲突失败: {error_msg}")
                    return {"success": False, "error": error_msg}
                
                metadata = await metadata_service.fetch(extracted_path, task)
                task.task_metadata = metadata
                
                task.update_progress(60, "重命名文件夹")
                from app.core.rename_service import RenameService
                rename_service = RenameService()
                renamed_path = await rename_service.rename(extracted_path, task)
                
                task.update_progress(75, "过滤文件中")
                await filter_service.filter(renamed_path, task)
                
                if config.rename.flatten_single_subfolder:
                    renamed_path = rename_service._flatten_single_subfolder(renamed_path)
                    logger.info(f"保留新版 - 扁平化后路径: {renamed_path}")

                if config.rename.remove_empty_folders:
                    rename_service.remove_empty_folders(renamed_path, remove_root=False)

                # 简繁转换（与 AUTO_PROCESS 流程保持一致）
                if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                    from ..core.subtitle_sync_service import get_subtitle_sync_service
                    subtitle_svc = get_subtitle_sync_service()
                    task.update_progress(80, "字幕繁简转换中")
                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                    if simplify_result['converted_files'] > 0:
                        logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                   f"转换 {simplify_result['converted_files']} 个文件")

                task.update_progress(85, "移动到库存")
                final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                
                from app.core.task_engine import TaskEngine
                task_engine = TaskEngine()
                await task_engine._archive_source_file(task)
                
                task.status = TaskStatus.COMPLETED
                task.update_progress(100, f"问题作品已处理: {action_type}")
                task.completed_at = datetime.now()
                
                logger.info(f"保留新版完成：已解压并移动到 {final_path}，压缩包已归档")
                
                # 更新 ProcessedArchive 状态为 completed
                if is_in_processed:
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            else:
                # 如果是已解压的文件夹，直接移动
                if os.path.exists(conflict.new_path):
                    target_path = os.path.join(config.storage.library_path, os.path.basename(conflict.new_path))
                    shutil.move(conflict.new_path, target_path)
                    logger.info(f"保留新版完成：已移动到 {target_path}")
            
            conflict.status = "KEEP_NEW"
            
        elif action_type == "KEEP_OLD":
            # 删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    os.remove(conflict.new_path)  # 删除压缩包
                else:
                    shutil.rmtree(conflict.new_path)  # 删除文件夹
            # 更新 ProcessedArchive 状态为 completed（用户选择保留旧版，新版任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (KEEP_OLD): {filename}")
            
            conflict.status = "KEEP_OLD"
            
        elif action_type == "MERGE":
            # 合并：保留两个版本，新版本加编号
            if is_archive:
                logger.info(f"合并：先解压压缩包 {conflict.new_path}")
                task = Task(
                    task_type=TaskType.AUTO_PROCESS,
                    source_path=conflict.new_path,
                    auto_classify=True
                )

                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()

                extracted_path = await extract_service.extract(task)
                if extracted_path:
                    metadata = await metadata_service.fetch(extracted_path, task)

                    # 重命名
                    from app.core.rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = await rename_service.rename(extracted_path, task)

                    await filter_service.filter(renamed_path, task)

                    if config.rename.flatten_single_subfolder:
                        renamed_path = rename_service._flatten_single_subfolder(renamed_path)

                    if config.rename.remove_empty_folders:
                        rename_service.remove_empty_folders(renamed_path, remove_root=False)

                    # 简繁转换
                    if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                        from ..core.subtitle_sync_service import get_subtitle_sync_service
                        subtitle_svc = get_subtitle_sync_service()
                        simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                        if simplify_result['converted_files'] > 0:
                            logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                       f"转换 {simplify_result['converted_files']} 个文件")

                    # 修改metadata使文件夹名加编号
                    rjcode = metadata.get('rjcode', '')
                    target_base = os.path.join(config.storage.library_path, conflict.rjcode)
                    counter = 1
                    while os.path.exists(f"{target_base}({counter})"):
                        counter += 1
                    metadata['work_name'] = f"{metadata.get('work_name', '')}({counter})"

                    final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                    os.remove(conflict.new_path)
                    logger.info(f"合并完成：新版本已保存为 {final_path}")
                    
                    # 更新 ProcessedArchive 状态为 completed
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            
            conflict.status = "MERGE"
            
        elif action_type == "SKIP":
            # 跳过，删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    os.remove(conflict.new_path)
                else:
                    shutil.rmtree(conflict.new_path)
            # 更新 ProcessedArchive 状态为 completed（用户选择跳过，任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (SKIP): {filename}")
            
            conflict.status = "SKIP"
        
        # 更新关联任务的状态
        if conflict.task_id:
            engine = get_task_engine()
            from ..core.task_engine import TaskStatus
            engine.update_task_status(
                conflict.task_id, 
                TaskStatus.COMPLETED,
                f"问题作品已处理: {action_type}"
            )
        
        db.commit()
        return {"message": "处理成功"}
        
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as e:
        db.rollback()
        logger.error(f"处理冲突失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

async def scan_processed_archives():
    """启动时扫描已处理压缩包目录，同步数据库"""
    import os
    import re
    from datetime import datetime
    from ..models.database import ProcessedArchive, get_db
    from ..config.settings import get_config
    import uuid
    
    config = get_config()
    processed_dir = config.storage.processed_archives_path
    
    if not os.path.exists(processed_dir):
        logger.info(f"已处理压缩包目录不存在: {processed_dir}")
        return
    
    logger.info(f"开始扫描已处理压缩包目录: {processed_dir}")
    
    db = next(get_db())
    try:
        # 清理重复记录（保留最新的）
        all_archives = db.query(ProcessedArchive).order_by(ProcessedArchive.processed_at.desc()).all()
        seen_filenames = {}
        duplicates = []
        for archive in all_archives:
            if archive.filename in seen_filenames:
                duplicates.append(archive)
            else:
                seen_filenames[archive.filename] = archive
        
        if duplicates:
            logger.info(f"发现 {len(duplicates)} 个重复记录，正在清理...")
            for dup in duplicates:
                db.delete(dup)
            db.commit()
            logger.info("重复记录清理完成")
        
        # 重新获取清理后的记录
        db_archives = {a.filename: a for a in db.query(ProcessedArchive).all()}
        
        # 扫描目录中的文件
        found_files = []
        for filename in os.listdir(processed_dir):
            file_path = os.path.join(processed_dir, filename)
            if os.path.isfile(file_path):
                found_files.append(filename)
                file_size = os.path.getsize(file_path)
                
                # 提取RJ号
                rjcode = None
                match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
                if match:
                    rjcode = match.group(0).upper()
                
                if filename in db_archives:
                    # 更新现有记录（只更新路径和大小，不更新时间）
                    archive = db_archives[filename]
                    archive.current_path = file_path
                    archive.file_size = file_size
                    # 注意：不要在这里更新 processed_at，扫描只是同步文件状态，不是重新处理
                    logger.info(f"更新已处理压缩包记录路径: {filename}")
                else:
                    # 创建新记录
                    new_archive = ProcessedArchive(
                        id=str(uuid.uuid4()),
                        original_path=file_path,
                        current_path=file_path,
                        filename=filename,
                        rjcode=rjcode or '',
                        file_size=file_size,
                        processed_at=datetime.now(),
                        process_count=1,
                        task_id='',
                        status='completed'
                    )
                    db.add(new_archive)
                    logger.info(f"添加新的已处理压缩包记录: {filename}")
        
        # 清理数据库中不存在的记录
        for filename, archive in list(db_archives.items()):
            if filename not in found_files:
                archive_path = os.path.join(processed_dir, filename)
                if not os.path.exists(archive_path):
                    logger.info(f"删除不存在的压缩包记录: {filename}")
                    db.delete(archive)
        
        db.commit()
        logger.info(f"已处理压缩包目录扫描完成，共发现 {len(found_files)} 个文件")
        
    except Exception as e:
        logger.error(f"扫描已处理压缩包目录失败: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

# 已处理压缩包API
@app.post("/api/processed-archives/scan")
async def scan_processed_archives_api():
    """手动触发扫描已处理压缩包目录"""
    try:
        await scan_processed_archives()
        return {"message": "扫描完成"}
    except Exception as e:
        logger.error(f"手动扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")

@app.get("/api/processed-archives")
async def get_processed_archives(
    search: Optional[str] = None,
    sort_by: Optional[str] = "processed_at",
    sort_order: Optional[str] = "desc"
):
    """获取已处理压缩包列表，支持搜索和排序
    
    Args:
        search: 搜索关键词（匹配RJ号、文件名）
        sort_by: 排序字段（rjcode, file_size, process_count, status, processed_at）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        query = db.query(ProcessedArchive)
        
        # 搜索功能
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (ProcessedArchive.rjcode.contains(search)) |
                (ProcessedArchive.filename.contains(search))
            )
        
        # 排序功能
        valid_sort_fields = {
            "rjcode": ProcessedArchive.rjcode,
            "file_size": ProcessedArchive.file_size,
            "process_count": ProcessedArchive.process_count,
            "status": ProcessedArchive.status,
            "processed_at": ProcessedArchive.processed_at
        }
        
        sort_field = valid_sort_fields.get(sort_by, ProcessedArchive.processed_at)
        
        if sort_order.lower() == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        archives = query.all()
        return {
            "archives": [archive.to_dict() for archive in archives]
        }
    finally:
        db.close()

@app.post("/api/processed-archives/{archive_id}/reprocess")
async def reprocess_archive(archive_id: str):
    """重新处理已归档的压缩包"""
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        archive = db.query(ProcessedArchive).filter(ProcessedArchive.id == archive_id).first()
        if not archive:
            raise HTTPException(status_code=404, detail="压缩包记录不存在")
        
        # 检查文件是否还存在
        if not os.path.exists(archive.current_path):
            raise HTTPException(status_code=404, detail="压缩包文件不存在，可能已被删除")
        
        # 直接从 processed 目录解压，避免复制到 SSD
        logger.info(f"直接从 processed 目录重新解压: {archive.current_path}")
        
        # 检查是否已有处理同RJ号的现存任务
        engine = get_task_engine()
        existing_tasks_for_rj = [t for t in engine.get_all_tasks()
                               if t.rjcode == archive.rjcode]

        if existing_tasks_for_rj:
            # 复用已有任务
            task = existing_tasks_for_rj[0]
            original_source = task.source_path
            old_status = task.status
            task.source_path = archive.current_path
            task.skip_archive = True  # 标记跳过归档（因为文件已在 processed 目录）
            task.status = TaskStatus.PENDING
            task.update_progress(0, "待处理")
            # 将任务加入队列以供 worker 执行
            await engine.queue.put(task)
            logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {archive.rjcode}, 状态: {old_status} -> {task.status}")
        else:
            # 创建新任务（标记为重新处理，直接从 processed 目录解压）
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=archive.current_path,  # 直接使用 processed 目录中的文件
                auto_classify=get_config().watcher.auto_classify,
                skip_archive=True  # 标记跳过归档（因为文件已在 processed 目录）
            )
            await engine.submit(task)
            # 注意：submit 会自动添加 task 到 engine.tasks 和队列中
        
        # 更新记录状态和重新处理时间
        archive.status = 'reprocessing'
        archive.processed_at = datetime.now()
        archive.process_count = (archive.process_count or 0) + 1
        db.commit()
        
        return {
            "message": "已创建重新处理任务",
            "task_id": task.id,
            "filename": archive.filename,
            "rjcode": archive.rjcode
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新处理压缩包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新处理失败: {str(e)}")
    finally:
        db.close()

# 库存管理API
@app.get("/api/library/libraries")
async def get_library_definitions():
    manager = get_library_manager()
    current_library = manager.get_library_definition()
    return {
        "libraries": manager.list_libraries(),
        "default_library_id": current_library.id,
        "default_extract_library_id": manager.default_extract_library_id(),
    }


@app.post("/api/library/test-connection")
async def test_library_connection(request: Request):
    try:
        data = await request.json()
        library = data.get("library") or data
        manager = get_library_manager()
        return await manager.test_connection(library)
    except Exception as e:
        logger.error(f"库存连接测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存连接测试失败: {str(e)}")


@app.get("/api/library/browser/files")
async def browse_library_files(
    library_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
    search: str = "",
    current_path: Optional[str] = None,
    sort_by: str = "size",
    sort_order: str = "desc",
    force_refresh: bool = False,
    search_exact: bool = False,
    search_result_kind: str = "all",
):
    try:
        manager = get_library_manager()
        current_library = manager.get_library_definition(library_id)
        keyword = str(search or "").strip()
        use_remote_global_search = (
            bool(keyword)
            and current_library.type == "synology_filestation"
        )
        if use_remote_global_search:
            data = await manager.global_search_files(
                current_library.id,
                keyword,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
            )
            browse_root_path = current_library.browse_root_path or current_library.root_path
            display_current_path = current_path or browse_root_path
            data["browse_root_path"] = browse_root_path
            data["current_path"] = display_current_path
            normalized_browse_root = str(PurePosixPath(browse_root_path or "/"))
            normalized_current_path = str(PurePosixPath(display_current_path or normalized_browse_root))
            if normalized_current_path in {"", "."}:
                normalized_current_path = normalized_browse_root or "/"
            if normalized_current_path == normalized_browse_root:
                data["parent_path"] = None
            else:
                data["parent_path"] = str(PurePosixPath(normalized_current_path).parent)
        else:
            data = await manager.list_files(
                library_id,
                page=page,
                page_size=page_size,
                search=search,
                current_path=current_path,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
            )
        data["libraries"] = manager.list_libraries()
        data["library_id"] = data.get("library_id") or current_library.id
        return data
    except Exception as e:
        logger.error(f"库存浏览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存浏览失败: {str(e)}")


@app.get("/api/library/browser/stats")
async def get_library_browser_stats(force_refresh: bool = False, library_id: Optional[str] = None):
    try:
        manager = get_library_manager()
        return await manager.ensure_stats(force=force_refresh, library_id=library_id)
    except Exception as e:
        logger.error(f"库存统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存统计失败: {str(e)}")


@app.post("/api/library/browser/stats/cancel")
async def cancel_library_browser_stats(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少库存 ID")
        manager = get_library_manager()
        return await manager.cancel_stats(library_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消库存统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消库存统计失败: {str(e)}")


@app.get("/api/library/browser/stats/logs")
async def get_library_browser_stats_logs(library_id: Optional[str] = None, lines: int = 200):
    try:
        manager = get_library_manager()
        return manager.read_stats_logs(library_id=library_id, lines=lines)
    except Exception as e:
        logger.error(f"鑾峰彇搴撳瓨缁熻鏃ュ織澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"鑾峰彇搴撳瓨缁熻鏃ュ織澶辫触: {str(e)}")


@app.post("/api/library/browser/folder-contents")
async def get_library_browser_folder_contents(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        manager = get_library_manager()
        return await manager.folder_contents(library_id, folder_path)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取库存文件夹内容失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取库存文件夹内容失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview")
async def get_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        request_id = data.get("request_id")
        rules = data.get("rules")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        try:
            return await manager.filter_delete_preview(library_id, folder_path, rules=rules, request_id=request_id)
        finally:
            manager._finish_filter_preview_request(request_id)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"过滤删除预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"过滤删除预览失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/start")
async def start_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        rules = data.get("rules")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        return await manager.start_filter_delete_preview_job(library_id, folder_path, rules=rules)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"启动过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动过滤删除预审失败: {str(e)}")


@app.get("/api/library/browser/filter-delete-preview/status")
async def get_library_browser_filter_delete_preview_status(job_id: str):
    try:
        manager = get_library_manager()
        return manager.get_filter_delete_preview_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except Exception as e:
        logger.error(f"获取过滤删除预审状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取过滤删除预审状态失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/cancel")
async def cancel_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        request_id = data.get("request_id")
        job_id = data.get("job_id")
        manager = get_library_manager()
        if job_id:
            return await manager.cancel_filter_delete_preview_job(job_id)
        return manager.cancel_filter_delete_preview(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消过滤删除预审失败: {str(e)}")


@app.post("/api/library/browser/rename")
async def rename_library_browser_item(request: Request):
    path = ""
    new_name = ""
    library_id = None
    skip_activity_log = False
    rename_context = ""
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        new_name = str(data.get("new_name") or "").strip()
        library_id = data.get("library_id")
        skip_activity_log = bool(data.get("skip_activity_log"))
        rename_context = str(data.get("rename_context") or "").strip()
        if not path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        manager = get_library_manager()
        result = await manager.rename(library_id, path, new_name)
        try:
            from ..core.activity_log_service import log_api_rename_action
            if not skip_activity_log:
                new_path = str(result.get("new_path") or result.get("path") or "").strip() if isinstance(result, dict) else ""
                log_api_rename_action(
                    action="rename",
                    success=True,
                    source_path=path,
                    new_path=new_path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    library_id=str(library_id or "") or None,
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名失败记录失败", exc_info=True)
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"库存重命名失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名异常记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存重命名失败: {str(e)}")


@app.post("/api/library/browser/delete")
async def delete_library_browser_item(request: Request):
    path = ""
    library_id = None
    skip_activity_log = False
    batch_id = ""
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="缺少路径")
        manager = get_library_manager()
        result = await manager.delete(library_id, path, confirmed=confirmed)
        try:
            from ..core.activity_log_service import log_api_delete_action
            if confirmed and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=True,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="dir" if str(result.get("type") or "").strip() == "folder" else "file",
                    library_id=str(library_id or "") or None,
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除失败记录失败", exc_info=True)
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"库存删除失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存删除失败: {str(e)}")


@app.post("/api/library/browser/batch-delete")
async def batch_delete_library_browser_items(request: Request):
    paths: list[str] = []
    library_id = None
    batch_id = ""
    try:
        data = await request.json()
        paths = [str(p or "").strip() for p in (data.get("paths") or []) if str(p or "").strip()]
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        manager = get_library_manager()
        result = await manager.batch_delete(library_id, paths, confirmed=confirmed)
        try:
            from ..core.activity_log_service import log_api_delete_action, log_batch_api_delete_result
            if confirmed and isinstance(result, dict):
                batch_id = str(data.get("batch_id") or "").strip() or str(uuid.uuid4())
                success_count = int(result.get("success_count") or 0)
                failed_paths = result.get("failed_paths") or []
                failed_count = len(failed_paths) if isinstance(failed_paths, list) else 0
                per_item_results = []

                failed_map = {}
                if isinstance(failed_paths, list):
                    for item in failed_paths:
                        p = str((item or {}).get("path") or "").strip()
                        if p:
                            failed_map[p] = str((item or {}).get("error") or "").strip()

                for p in paths:
                    err = failed_map.get(p, "")
                    ok = not bool(err)
                    log_api_delete_action(
                        action="batch_delete_item",
                        success=ok,
                        source_path=p,
                        item_name=os.path.basename(p),
                        item_type="unknown",
                        library_id=str(library_id or "") or None,
                        error=err,
                        batch_id=batch_id,
                    )
                    per_item_results.append({
                        "path": p,
                        "success": ok,
                        "error": err,
                    })

                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=success_count,
                    failed_count=failed_count,
                    results=per_item_results,
                    source_path=paths[0] if paths else "",
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除记录失败", exc_info=True)
        return result
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"库存批量删除失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_batch_api_delete_result
            if paths:
                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=0,
                    failed_count=len(paths),
                    results=[{"path": p, "success": False, "error": str(e)} for p in paths],
                    source_path=paths[0],
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存批量删除失败: {str(e)}")


@app.post("/api/library/browser/open-folder")
async def open_library_browser_folder(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        library_id = data.get("library_id")
        force_local = data.get("force_local", False)
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        manager = get_library_manager()
        return await manager.open_folder(library_id, path, force_local=force_local)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"库存打开目录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"库存打开目录失败: {str(e)}")


@app.get("/api/library/files")
async def get_library_files():
    """获取库内所有文件（只扫描前两级目录）"""
    try:
        config = get_config()
        library_path = config.storage.library_path
        
        if not os.path.exists(library_path):
            return {"files": []}
        
        # 查询 ProcessedArchive 数据库获取解压时间
        from ..models.database import ProcessedArchive, get_db
        db = next(get_db())
        
        # 构建文件名到解压时间的映射
        archive_times = {}
        for archive in db.query(ProcessedArchive).all():
            archive_name = os.path.basename(archive.current_path)
            archive_times[archive_name] = archive.processed_at
        
        items = []
        item_id = 0
        
        # 只遍历前两级目录
        for item in os.listdir(library_path):
            item_path = os.path.join(library_path, item)
            
            # 跳过冲突文件夹和隐藏文件
            if item.startswith('_') or item.startswith('.'):
                continue
            
            # 如果是文件夹（如 RJ012xxxxx），遍历其子目录
            if os.path.isdir(item_path):
                for subitem in os.listdir(item_path):
                    subitem_path = os.path.join(item_path, subitem)
                    
                    # 跳过隐藏文件
                    if subitem.startswith('.'):
                        continue
                    
                    try:
                        stat = os.stat(subitem_path)
                        # 提取RJ号
                        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', subitem, re.IGNORECASE)
                        rjcode = rj_match.group(0).upper() if rj_match else None
                        
                        # 计算文件夹大小或获取文件大小
                        size = 0
                        if os.path.isdir(subitem_path):
                            for dirpath, dirnames, filenames in os.walk(subitem_path):
                                for f in filenames:
                                    fp = os.path.join(dirpath, f)
                                    try:
                                        size += os.path.getsize(fp)
                                    except:
                                        pass
                        else:
                            size = stat.st_size
                        
                        # 获取解压时间（优先使用 processed_at，否则使用文件系统时间）
                        unzip_time = None
                        if subitem in archive_times:
                            unzip_time = archive_times[subitem].isoformat()
                        else:
                            unzip_time = datetime.fromtimestamp(stat.st_mtime).isoformat()
                        
                        items.append({
                            "id": str(item_id),
                            "name": subitem,
                            "path": subitem_path,
                            "rjcode": rjcode,
                            "size": size,
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "unzip_time": unzip_time,
                            "is_directory": os.path.isdir(subitem_path)
                        })
                        item_id += 1
                    except Exception as e:
                        logger.warning(f"获取项目信息失败: {subitem_path}, {e}")
            else:
                # 根目录下的文件
                try:
                    stat = os.stat(item_path)
                    rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                    rjcode = rj_match.group(0).upper() if rj_match else None
                    
                    # 获取解压时间
                    unzip_time = None
                    if item in archive_times:
                        unzip_time = archive_times[item].isoformat()
                    else:
                        unzip_time = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    
                    items.append({
                        "id": str(item_id),
                        "name": item,
                        "path": item_path,
                        "rjcode": rjcode,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "unzip_time": unzip_time,
                        "is_directory": False
                    })
                    item_id += 1
                except Exception as e:
                    logger.warning(f"获取项目信息失败: {item_path}, {e}")
        
        # 按解压时间排序（最新的在前）
        items.sort(key=lambda x: x["unzip_time"] or x["modified_time"], reverse=True)
        
        return {"files": items}
        
    except Exception as e:
        logger.error(f"获取库文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取库文件失败: {str(e)}")

@app.post("/api/library/folder-contents")
@app.post("/api/library/folder-content")
async def get_library_folder_contents(request: Request):
    """获取指定库内文件夹的所有子文件（递归）"""
    try:
        data = await request.json()
        folder_path = data.get("path")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")

        config = get_config()
        library_path = os.path.abspath(config.storage.library_path)
        target_path = os.path.abspath(folder_path)

        if not os.path.exists(target_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        if not os.path.isdir(target_path):
            raise HTTPException(status_code=400, detail="目标不是文件夹")
        if not (target_path == library_path or target_path.startswith(library_path + os.sep)):
            raise HTTPException(status_code=403, detail="只能查看库内文件夹")

        items = []
        item_id = 0
        for root, _, files in os.walk(target_path):
            for filename in files:
                if filename.startswith('.'):
                    continue
                file_path = os.path.join(root, filename)
                try:
                    stat = os.stat(file_path)
                    relative_path = os.path.relpath(file_path, target_path).replace("\\", "/")
                    items.append({
                        "id": str(item_id),
                        "name": filename,
                        "path": file_path,
                        "relative_path": relative_path,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                    item_id += 1
                except Exception as e:
                    logger.warning(f"读取子文件失败: {file_path}, {e}")

        items.sort(key=lambda x: x["relative_path"])
        return {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "total_files": len(items),
            "items": items
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件夹内容失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文件夹内容失败: {str(e)}")

@app.post("/api/library/rename")
async def rename_library_file(request: Request):
    """重命名库内文件或文件夹"""
    try:
        data = await request.json()
        old_path = data.get("path")
        new_name = data.get("new_name")
        
        if not old_path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        
        if not os.path.exists(old_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 构建新路径
        parent_dir = os.path.dirname(old_path)
        new_path = os.path.join(parent_dir, new_name)
        
        # 检查新名称是否已存在
        if os.path.exists(new_path):
            raise HTTPException(status_code=400, detail="新名称已存在")
        
        # 执行重命名
        os.rename(old_path, new_path)
        logger.info(f"重命名成功: {old_path} -> {new_path}")
        
        return {"message": "重命名成功", "new_path": new_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重命名失败: {str(e)}")

@app.post("/api/library/api-rename")
async def api_rename_library_file(request: Request):
    """使用API重新获取元数据并重命名"""
    file_path = ""
    library_id = None
    rjcode = ""
    old_name = ""
    new_name = ""
    try:
        data = await request.json()
        file_path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        manager = get_library_manager() if library_id else None
        library = manager.get_library_definition(library_id) if library_id else None
        is_remote_library = bool(library and library.type == "synology_filestation")
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")
        
        if not is_remote_library and not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 提取RJ号
        import re
        target_name = str(PurePosixPath(file_path).name) if is_remote_library else os.path.basename(file_path)
        rj_match = re.search(r'[RVB]J\d{6,8}', target_name, re.IGNORECASE)
        if not rj_match:
            raise HTTPException(status_code=400, detail="无法从文件名提取RJ号")
        
        rjcode = rj_match.group(0).upper()
        old_name = target_name
        logger.info(f"API重新命名: {file_path}, RJ号: {rjcode}")
        
        # 获取元数据（强制刷新，不使用缓存）
        from ..core.metadata_service import MetadataService
        from ..models.database import WorkMetadata as WorkMetadataModel, get_db
        metadata_service = MetadataService()
        
        try:
            # 清除该RJ号的缓存（强制重新获取）
            db = next(get_db())
            try:
                deleted_count = db.query(WorkMetadataModel).filter(
                    WorkMetadataModel.rjcode == rjcode
                ).delete()
                db.commit()
                if deleted_count > 0:
                    logger.info(f"[{rjcode}] 已清除缓存，准备重新获取元数据")
                else:
                    logger.info(f"[{rjcode}] 无缓存，将直接获取元数据")
            except Exception as e:
                logger.warning(f"[{rjcode}] 清除缓存失败: {e}")
                db.rollback()
            finally:
                db.close()
            
            # 创建临时任务对象（用于进度更新，虽然这里不需要）
            from ..core.task_engine import Task, TaskType
            temp_task = Task(
                task_type=TaskType.METADATA,
                source_path=file_path
            )
            
            metadata = await metadata_service.fetch(file_path, temp_task)
            logger.info(f"获取到元数据: {metadata}")
        except Exception as e:
            logger.error(f"获取元数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取元数据失败: {str(e)}")
        
        # 生成新名称
        work_name = metadata.get('work_name', '')
        if not work_name:
            raise HTTPException(status_code=500, detail="获取到的作品名称为空")
        
        config = get_config()
        logger.info(f"[API RENAME] 读取到的模板: '{config.rename.template}' (长度: {len(config.rename.template)})")
        logger.info(f"[API RENAME] api_rename_follow_template: {config.rename.api_rename_follow_template}")
        logger.info(f"[API RENAME] use_japanese_metadata: {config.rename.use_japanese_metadata}")

        # 根据配置决定是否遵循重命名模板
        if config.rename.api_rename_follow_template:
            # 使用重命名服务生成名称
            from ..core.rename_service import RenameService
            rename_service = RenameService()

            # 创建临时任务对象用于重命名
            from ..core.task_engine import Task, TaskType
            temp_task = Task(
                task_type=TaskType.RENAME,
                source_path=file_path
            )
            temp_task.task_metadata = metadata

            # 如果启用了日语元数据，获取日语版本
            japanese_metadata = None
            if config.rename.use_japanese_metadata:
                logger.info(f"[{rjcode}] 启用日语元数据，正在获取...")
                japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
                if japanese_metadata:
                    logger.info(f"[{rjcode}] 日语元数据获取成功: maker_name={japanese_metadata.get('maker_name')}")
                else:
                    logger.warning(f"[{rjcode}] 日语元数据获取失败，将使用当前语言元数据")

            # 编译名称
            new_name = rename_service._compile_name(metadata, japanese_metadata)
            new_name = rename_service._sanitize_filename(new_name)
            logger.info(f"[{rjcode}] 使用重命名模板生成名称: {new_name}")
        else:
            # 简单格式：RJ号 + 作品名
            import re
            def sanitize_filename(name):
                # 移除或替换Windows不允许的字符
                name = re.sub(r'[<>:"/\\|?*]', '_', name)
                # 移除控制字符
                name = re.sub(r'[\x00-\x1f\x7f]', '', name)
                # 移除末尾的空格和点
                name = name.rstrip(' .')
                return name
            
            new_name = f"{rjcode} {sanitize_filename(work_name)}"
            logger.info(f"[{rjcode}] 使用简单格式生成名称: {new_name}")
        
        # 构建新路径
        if is_remote_library:
            parent_dir = str(PurePosixPath(file_path).parent)
            new_path = str(PurePosixPath(parent_dir) / new_name)
        else:
            parent_dir = os.path.dirname(file_path)
            new_path = os.path.join(parent_dir, new_name)
        
        # 检查新名称是否已存在
        if not is_remote_library and os.path.exists(new_path) and new_path != file_path:
            raise HTTPException(status_code=400, detail="新名称已存在")
        
        if new_path == file_path:
            try:
                from ..core.activity_log_service import log_api_rename_action

                log_api_rename_action(
                    action="api_rename",
                    success=True,
                    source_path=file_path,
                    new_path=new_path,
                    old_name=old_name,
                    new_name=new_name,
                    rjcode=rjcode or None,
                    library_id=str(library_id or "") or None,
                    extra_detail={"no_change": True},
                )
            except Exception:
                logger.debug("[操作记录] API 重命名无变化记录失败", exc_info=True)
            return {"message": "名称已是最新，无需重命名", "name": new_name}

        # 执行重命名
        if is_remote_library:
            await manager.rename(library_id, file_path, new_name)
        else:
            os.rename(file_path, new_path)
        logger.info(f"API重命名成功: {file_path} -> {new_path}")
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=True,
                source_path=file_path,
                new_path=new_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
            )
        except Exception:
            logger.debug("[操作记录] API 重命名成功记录失败", exc_info=True)

        return {
            "message": "API重命名成功",
            "old_name": os.path.basename(file_path),
            "new_name": new_name,
            "path": new_path,
            "metadata": metadata
        }
        
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
                error=str(exc.detail or exc),
                status="failed",
            )
        except Exception:
            logger.debug("[操作记录] API 重命名 HTTP 异常记录失败", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"API重命名失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
                error=str(e),
            )
        except Exception:
            logger.debug("[操作记录] API 重命名失败记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"API重命名失败: {str(e)}")

def map_path_to_local(remote_path: str) -> tuple[str, bool]:
    """
    将远程路径映射到本地路径
    返回: (映射后的路径, 是否成功映射)
    """
    config = get_config()
    if not config.path_mapping.enabled:
        return remote_path, False
    
    # 统一路径分隔符为 /
    remote_path_normalized = remote_path.replace("\\", "/")
    
    for rule in config.path_mapping.rules:
        if not rule.enabled:
            continue
        
        # 统一规则路径分隔符
        rule_remote = rule.remote_path.replace("\\", "/")
        
        # 检查路径是否匹配
        if remote_path_normalized.startswith(rule_remote):
            # 替换前缀
            relative_path = remote_path_normalized[len(rule_remote):]
            # 移除开头的 / 或 \
            relative_path = relative_path.lstrip("/\\")
            
            # 组合成本地路径
            local_path = os.path.join(rule.local_path, relative_path)
            return local_path, True
    
    return remote_path, False

@app.post("/api/library/delete")
async def delete_library_file(request: Request):
    """删除库内文件或文件夹（需要确认）"""
    try:
        data = await request.json()
        file_path = data.get("path")
        confirmed = data.get("confirmed", False)
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 安全检查：确保在库目录内
        config = get_config()
        library_path = config.storage.library_path
        if not file_path.startswith(library_path):
            raise HTTPException(status_code=403, detail="只能删除库内的文件")
        
        if not confirmed:
            # 返回需要确认的信息
            import shutil
            if os.path.isdir(file_path):
                # 计算文件夹大小
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(file_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        total_size += os.path.getsize(fp)
                return {
                    "need_confirm": True,
                    "type": "folder",
                    "name": os.path.basename(file_path),
                    "path": file_path,
                    "size": total_size
                }
            else:
                return {
                    "need_confirm": True,
                    "type": "file",
                    "name": os.path.basename(file_path),
                    "path": file_path,
                    "size": os.path.getsize(file_path)
                }
        
        # 执行删除
        import shutil
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
            logger.info(f"删除文件夹: {file_path}")
        else:
            os.remove(file_path)
            logger.info(f"删除文件: {file_path}")
        
        return {"message": "删除成功", "path": file_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

# 批量删除 API
@app.post("/api/library/batch-delete")
async def batch_delete_library_items(request: Request):
    """批量删除库内文件或文件夹"""
    try:
        data = await request.json()
        paths = data.get("paths", [])
        confirmed = data.get("confirmed", False)
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        
        # 安全检查
        config = get_config()
        library_path = config.storage.library_path
        
        for path in paths:
            if not path.startswith(library_path):
                raise HTTPException(status_code=403, detail="只能删除库内的文件")
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"路径不存在：{path}")
        
        if not confirmed:
            # 返回需要确认的信息
            import shutil
            total_size = 0
            total_count = len(paths)
            
            for path in paths:
                if os.path.isdir(path):
                    for dirpath, dirnames, filenames in os.walk(path):
                        for f in filenames:
                            total_size += os.path.getsize(os.path.join(dirpath, f))
                else:
                    total_size += os.path.getsize(path)
            
            return {
                "need_confirm": True,
                "total_count": total_count,
                "total_size": total_size
            }
        
        # 执行删除
        import shutil
        success_count = 0
        failed_paths = []
        
        for path in paths:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    logger.info(f"批量删除 - 删除文件夹：{path}")
                else:
                    os.remove(path)
                    logger.info(f"批量删除 - 删除文件：{path}")
                success_count += 1
            except Exception as e:
                logger.error(f"批量删除失败：{path}, {e}")
                failed_paths.append({"path": path, "error": str(e)})
        
        return {
            "message": f"批量删除完成",
            "success_count": success_count,
            "failed_paths": failed_paths
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量删除失败：{str(e)}")


# 批量 API 重命名 API
@app.post("/api/library/batch-api-rename")
async def batch_api_rename_library_items(request: Request, background_tasks: BackgroundTasks):
    """批量 API重命名（异步处理）"""
    try:
        data = await request.json()
        paths = data.get("paths", [])
        library_id = data.get("library_id")
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        
        # 验证路径
        for path in paths:
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"路径不存在：{path}")
        
        # 创建任务 ID
        import uuid
        batch_id = str(uuid.uuid4())
        
        # 在后台处理
        async def process_batch():
            from ..core.task_engine import Task, TaskType
            from ..core.metadata_service import MetadataService
            from ..core.rename_service import RenameService
            from ..core.activity_log_service import log_api_rename_action, log_batch_api_rename_result
            
            results = []
            for path in paths:
                path = str(path or "").strip()
                child_rjcode = ""
                old_name = os.path.basename(path) if path else ""
                new_name = ""
                try:
                    # 提取 RJ 号
                    rj_match = re.search(r'[RVB]J\d{6,8}', os.path.basename(path), re.IGNORECASE)
                    if not rj_match:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error="无法提取 RJ 号",
                        )
                        results.append({
                            "path": path,
                            "success": False,
                            "error": "无法提取 RJ 号"
                        })
                        continue
                    
                    rjcode = rj_match.group(0).upper()
                    child_rjcode = rjcode
                    
                    # 创建临时任务
                    temp_task = Task(task_type=TaskType.METADATA, source_path=path)
                    
                    # 获取元数据
                    metadata_service = MetadataService()
                    metadata = await metadata_service.fetch(path, temp_task)
                    
                    # 生成新名称
                    rename_service = RenameService()
                    config = get_config()
                    
                    if config.rename.api_rename_follow_template:
                        japanese_metadata = None
                        if config.rename.use_japanese_metadata:
                            japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
                        new_name = rename_service._compile_name(metadata, japanese_metadata)
                        new_name = rename_service._sanitize_filename(new_name)
                    else:
                        work_name = metadata.get('work_name', '')
                        def sanitize_filename(name):
                            name = re.sub(r'[<>:"/\\|?*]', '_', name)
                            name = re.sub(r'[\x00-\x1f\x7f]', '', name)
                            name = name.rstrip(' .')
                            return name
                        new_name = f"{rjcode} {sanitize_filename(work_name)}"
                    
                    # 执行重命名
                    parent_dir = os.path.dirname(path)
                    new_path = os.path.join(parent_dir, new_name)
                    
                    if os.path.exists(new_path) and new_path != path:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error="新名称已存在",
                        )
                        results.append({
                            "path": path,
                            "success": False,
                            "error": "新名称已存在"
                        })
                    elif new_path == path:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=True,
                            source_path=path,
                            new_path=new_path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            extra_detail={"no_change": True},
                        )
                        results.append({
                            "path": path,
                            "success": True,
                            "message": "名称已是最新",
                            "new_name": new_name
                        })
                    else:
                        os.rename(path, new_path)
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=True,
                            source_path=path,
                            new_path=new_path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                        )
                        results.append({
                            "path": path,
                            "success": True,
                            "new_path": new_path,
                            "new_name": new_name
                        })
                    
                except Exception as e:
                    logger.error(f"批量 API 重命名失败：{path}, {e}")
                    try:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error=str(e),
                        )
                    except Exception:
                        logger.debug("[操作记录] 批量 API 重命名子项失败记录失败", exc_info=True)
                    results.append({
                        "path": path,
                        "success": False,
                        "error": str(e)
                    })
            
            # 保存结果（可选：保存到文件或数据库）
            logger.info(f"批量 API重命名完成：batch_id={batch_id}, success={sum(1 for r in results if r['success'])}/{len(results)}")
            try:
                log_batch_api_rename_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=sum(1 for r in results if r.get('success')),
                    failed_count=sum(1 for r in results if not r.get('success')),
                    results=results,
                    source_path=str(paths[0] or "").strip() if paths else "",
                )
            except Exception:
                logger.debug("[操作记录] 批量 API 重命名汇总记录失败", exc_info=True)
        
        background_tasks.add_task(process_batch)
        
        return {
            "batch_id": batch_id,
            "message": f"已创建批量重命名任务，共 {len(paths)} 项",
            "total_count": len(paths)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量 API 重命名失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量重命名失败：{str(e)}")


@app.post("/api/library/open-folder")
async def open_library_folder(request: Request):
    """打开文件夹位置"""
    try:
        data = await request.json()
        path = data.get("path")
        force_local = data.get("force_local", False)  # 是否强制使用本地映射
        
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        # 检查路径映射配置
        config = get_config()
        mapped_path, is_mapped = map_path_to_local(path)
        
        # 判断打开模式
        open_mode = config.path_mapping.open_mode
        if force_local or open_mode == "mapped":
            # 使用映射路径打开
            target_path = mapped_path
            # 在映射模式下，不检查路径是否存在（因为后端无法访问客户端路径）
            logger.info(f"使用映射路径打开: {path} -> {target_path}")
            
            return {
                "message": "请使用本地路径打开",
                "mode": "mapped",
                "original_path": path,
                "mapped_path": target_path,
                "is_mapped": is_mapped
            }
        
        # 直接模式：后端直接打开（同设备部署）
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="路径不存在")
        
        # 获取文件夹路径（如果是文件，则获取所在文件夹）
        folder_path = path if os.path.isdir(path) else os.path.dirname(path)
        
        # 根据操作系统打开文件夹
        import platform
        import subprocess
        
        system = platform.system()
        if system == "Windows":
            # 使用 os.startfile 打开文件夹，更好地支持中文和特殊字符
            if os.path.isdir(path):
                # 如果是文件夹，直接打开
                os.startfile(path)
            else:
                # 如果是文件，使用 explorer /select 选中它
                # 使用字符串形式避免引号问题
                cmd = f'explorer /select,"{path}"'
                subprocess.run(cmd, shell=True, check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", "-R", path], check=True)
        else:  # Linux
            subprocess.run(["xdg-open", folder_path], check=True)
        
        return {"message": "已打开文件夹", "mode": "direct"}
        
    except Exception as e:
        logger.error(f"打开文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {str(e)}")

# 路径映射配置API
@app.get("/api/path-mapping/config")
async def get_path_mapping_config():
    """获取路径映射配置"""
    config = get_config().path_mapping
    return {
        "enabled": config.enabled,
        "open_mode": config.open_mode,
        "rules": [
            {
                "remote_path": rule.remote_path,
                "local_path": rule.local_path,
                "enabled": rule.enabled
            }
            for rule in config.rules
        ]
    }

@app.post("/api/path-mapping/config")
async def update_path_mapping_config(request: Request):
    """更新路径映射配置"""
    try:
        data = await request.json()
        config = get_config()
        
        # 更新配置
        config.path_mapping.enabled = data.get("enabled", config.path_mapping.enabled)
        config.path_mapping.open_mode = data.get("open_mode", config.path_mapping.open_mode)
        
        # 更新规则
        if "rules" in data:
            from app.config.settings import PathMappingRule
            config.path_mapping.rules = [
                PathMappingRule(**rule) for rule in data["rules"]
            ]
        
        # 保存配置
        save_config(config)
        
        return {"message": "路径映射配置已更新"}
        
    except Exception as e:
        logger.error(f"更新路径映射配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@app.post("/api/path-mapping/test")
async def test_path_mapping(request: Request):
    """测试路径映射"""
    try:
        data = await request.json()
        remote_path = data.get("path")
        
        if not remote_path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        mapped_path, is_mapped = map_path_to_local(remote_path)
        
        return {
            "original_path": remote_path,
            "mapped_path": mapped_path,
            "is_mapped": is_mapped
        }
        
    except Exception as e:
        logger.error(f"测试路径映射失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")

# 密码库智能清理API
@app.get("/api/password-cleanup/status")
async def get_cleanup_status():
    """获取清理服务状态"""
    service = get_cleanup_service()
    config = get_config().password_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "max_use_count": config.max_use_count,
        "preserve_days": config.preserve_days,
        "exclude_sources": config.exclude_sources,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/password-cleanup/preview")
async def preview_cleanup():
    """预览将要清理的密码（不实际删除）"""
    service = get_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/password-cleanup/run")
async def run_cleanup():
    """手动执行清理"""
    service = get_cleanup_service()
    result = await service.cleanup_passwords(dry_run=False)
    return result

@app.get("/api/password-cleanup/history")
async def get_cleanup_history(limit: int = 50):
    """获取清理历史记录"""
    service = get_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/password-cleanup/restart")
async def restart_cleanup_service():
    """重启清理服务（配置变更后调用）"""
    service = get_cleanup_service()
    await service.restart()
    return {
        "message": "密码库清理服务已重启",
        "status": await get_cleanup_status()
    }

# 已处理压缩包智能清理API
@app.get("/api/processed-archive-cleanup/status")
async def get_archive_cleanup_status():
    """获取已处理压缩包清理服务状态"""
    service = get_processed_archive_cleanup_service()
    config = get_config().processed_archive_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "strategy": config.strategy,
        "preserve_days": config.preserve_days,
        "max_count": config.max_count,
        "max_size_gb": config.max_size_gb,
        "exclude_reprocessing": config.exclude_reprocessing,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/processed-archive-cleanup/preview")
async def preview_archive_cleanup():
    """预览将要清理的已处理压缩包（不实际删除）"""
    service = get_processed_archive_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/processed-archive-cleanup/run")
async def run_archive_cleanup():
    """手动执行已处理压缩包清理"""
    service = get_processed_archive_cleanup_service()
    result = await service.cleanup_archives(dry_run=False)
    return result

@app.get("/api/processed-archive-cleanup/history")
async def get_archive_cleanup_history(limit: int = 50):
    """获取已处理压缩包清理历史记录"""
    service = get_processed_archive_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/processed-archive-cleanup/restart")
async def restart_archive_cleanup_service():
    """重启已处理压缩包清理服务（配置变更后调用）"""
    service = get_processed_archive_cleanup_service()
    await service.restart()
    return {
        "message": "已处理压缩包清理服务已重启",
        "status": await get_archive_cleanup_status()
    }

# ========== 已存在文件夹处理 API ==========

class ExistingFolderResponse(BaseModel):
    """已存在文件夹响应模型"""
    name: str
    path: str
    rjcode: Optional[str]
    modified_time: str
    size: int
    is_directory: bool


def _normalize_existing_folder_resolution_options(options: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    alias_map = {
        "KEEP_OLD": "SKIP",
        "KEEP_BOTH": "MERGE",
        "MERGE_LANG": "MERGE",
    }
    label_map = {
        "KEEP_NEW": "保留新版",
        "MERGE": "合并",
        "SKIP": "跳过",
    }
    description_map = {
        "KEEP_NEW": "采用当前新目录作为最终结果，并在确认后替换已存在目录",
        "MERGE": "进入文件级对比视图，按文件决定保留新旧内容后生成最终目录",
        "SKIP": "放弃当前目录，保持已有目录不变并删除当前待处理目录",
    }

    for option in options or []:
        action = alias_map.get(str(option.get("action") or "").strip().upper(), str(option.get("action") or "").strip().upper())
        if action not in {"KEEP_NEW", "MERGE", "SKIP"} or action in seen:
            continue
        normalized.append({
            "action": action,
            "label": label_map[action],
            "description": option.get("description") or description_map[action],
            "recommend": bool(option.get("recommend")),
        })
        seen.add(action)

    if normalized:
        return normalized

    return [
        {
            "action": "KEEP_NEW",
            "label": "保留新版",
            "description": description_map["KEEP_NEW"],
            "recommend": True,
        },
        {
            "action": "MERGE",
            "label": "合并",
            "description": description_map["MERGE"],
            "recommend": False,
        },
        {
            "action": "SKIP",
            "label": "跳过",
            "description": description_map["SKIP"],
            "recommend": False,
        },
    ]


async def _resolve_existing_folder_conflict_path(folder_path: str, preferred_path: str | None = None) -> str | None:
    if preferred_path and os.path.exists(preferred_path):
        return preferred_path

    from ..core.duplicate_service import get_duplicate_service

    folder_name = os.path.basename(folder_path)
    rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
    rjcode = rj_match.group(0).upper() if rj_match else None
    if not rjcode:
        return None

    duplicate_service = get_duplicate_service()
    check_result = await duplicate_service.check_duplicate_enhanced(
        rjcode,
        check_linked_works=True,
        cue_languages=["CHI_HANS", "CHI_HANT", "ENG"],
    )
    if check_result.direct_duplicate:
        return check_result.direct_duplicate.get("path")
    if check_result.linked_works_found:
        return check_result.linked_works_found[0].get("path")
    return None

@app.get("/api/existing-folders", response_model=List[ExistingFolderResponse])
async def get_existing_folders():
    """获取已存在文件夹目录中的所有文件夹"""
    try:
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        # 如果目录不存在，返回空列表
        if not os.path.exists(existing_folders_path):
            return []
        
        folders = []
        for item in os.listdir(existing_folders_path):
            item_path = os.path.join(existing_folders_path, item)
            
            # 跳过隐藏文件和非文件夹项目
            if item.startswith('.') or not os.path.isdir(item_path):
                continue
            
            try:
                stat = os.stat(item_path)
                # 提取RJ号
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                # 计算文件夹大小（简化版，只统计直接子项）
                size = 0
                try:
                    for subitem in os.listdir(item_path):
                        subitem_path = os.path.join(item_path, subitem)
                        if os.path.isfile(subitem_path):
                            size += os.path.getsize(subitem_path)
                except:
                    pass
                
                folders.append(ExistingFolderResponse(
                    name=item,
                    path=item_path,
                    rjcode=rjcode,
                    modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    size=size,
                    is_directory=True
                ))
            except Exception as e:
                logger.warning(f"获取文件夹信息失败: {item_path}, {e}")
        
        # 按修改时间排序（最新的在前）
        folders.sort(key=lambda x: x.modified_time, reverse=True)
        
        return folders
        
    except Exception as e:
        logger.error(f"获取已存在文件夹列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")

@app.post("/api/existing-folders/scan")
async def scan_existing_folders(check_duplicates: bool = True, force_refresh: bool = False):
    """扫描已存在文件夹目录，先快速列出所有文件夹，再后台查重
    
    Args:
        check_duplicates: 是否执行查重检查
        force_refresh: 是否强制刷新缓存
    """
    async def generate_folders():
        try:
            config = get_config()
            existing_folders_path = config.storage.existing_folders_path
            
            # 自动创建目录（如果不存在）
            if not os.path.exists(existing_folders_path):
                try:
                    os.makedirs(existing_folders_path, exist_ok=True)
                    logger.info(f"自动创建已存在文件夹目录: {existing_folders_path}")
                except Exception as e:
                    yield json.dumps({"error": f"无法创建目录: {str(e)}"}) + "\n"
                    return
            
            # 第一步：快速列出所有文件夹（不查重）
            items = os.listdir(existing_folders_path)
            folders = []
            
            yield json.dumps({
                "type": "start",
                "total": len(items),
                "message": f"开始扫描，共 {len(items)} 个项目"
            }) + "\n"
            
            # 先发送所有文件夹基本信息（立即可见）
            for index, item in enumerate(items):
                item_path = os.path.join(existing_folders_path, item)
                
                # 跳过隐藏文件和非文件夹项目
                if item.startswith('.') or not os.path.isdir(item_path):
                    continue
                
                # 提取RJ号
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                folder_info = {
                    "name": item,
                    "path": item_path,
                    "rjcode": rjcode,
                    "status": "pending"  # 待检查状态
                }
                
                folders.append(folder_info)
                
                # 立即发送，让前端显示
                yield json.dumps({
                    "type": "folder",
                    "index": index,
                    "total": len(items),
                    "folder": folder_info,
                    "progress": f"{index + 1}/{len(items)}"
                }) + "\n"
            
            # 第二步：后台逐个查重（如果有RJ号且需要检查）
            if check_duplicates:
                conflict_count = 0
                
                yield json.dumps({
                    "type": "checking_start",
                    "message": f"开始查重检查，共 {len(folders)} 个文件夹"
                }) + "\n"
                
                # 获取数据库会话
                from ..models.database import get_db
                db = next(get_db())
                
                try:
                    for index, folder_info in enumerate(folders):
                        item_path = folder_info["path"]
                        item = folder_info["name"]
                        rjcode = folder_info["rjcode"]
                        
                        if not rjcode:
                            continue
                        
                        # 检查缓存
                        cache = None
                        if not force_refresh:
                            try:
                                from ..models.database import ExistingFolderCache
                                cache = db.query(ExistingFolderCache).filter(
                                    ExistingFolderCache.folder_path == item_path
                                ).first()
                            except Exception as e:
                                logger.warning(f"查询缓存失败: {e}")
                        
                        # 如果有缓存且不需要刷新，直接使用缓存
                        if cache and not force_refresh and not cache.needs_refresh:
                            folder_info["duplicate_info"] = cache.duplicate_info
                            folder_info["file_count"] = cache.file_count
                            folder_info["folder_size"] = cache.folder_size
                            folder_info["status"] = "cached"
                            if cache.duplicate_info:
                                conflict_count += 1
                            
                            # 发送更新
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": True
                            }) + "\n"
                            continue
                        
                        # 没有缓存，执行API查询
                        try:
                            from ..core.duplicate_service import get_duplicate_service
                            duplicate_service = get_duplicate_service()
                            
                            # 添加延时避免429
                            if index > 0 and index % 5 == 0:
                                await asyncio.sleep(1)
                            
                            check_result = await duplicate_service.check_duplicate_enhanced(
                                rjcode, 
                                check_linked_works=True,
                                cue_languages=['CHI_HANS', 'CHI_HANT', 'ENG']
                            )
                            
                            if check_result.is_duplicate:
                                folder_info["duplicate_info"] = {
                                    "is_duplicate": True,
                                    "conflict_type": check_result.conflict_type,
                                    "direct_duplicate": check_result.direct_duplicate,
                                    "linked_works_found": check_result.linked_works_found,
                                    "related_rjcodes": check_result.related_rjcodes,
                                    "analysis_info": check_result.analysis_info
                                }
                                
                                # 获取推荐的解决选项
                                resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                                folder_info["duplicate_info"]["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)
                                conflict_count += 1
                            
                            folder_info["status"] = "checked"
                            
                            # 计算文件夹大小
                            folder_size = 0
                            file_count = 0
                            try:
                                for root, dirs, files in os.walk(item_path):
                                    file_count += len(files)
                                    for file in files:
                                        file_path = os.path.join(root, file)
                                        if os.path.isfile(file_path):
                                            folder_size += os.path.getsize(file_path)
                            except:
                                pass
                            
                            folder_info["file_count"] = file_count
                            folder_info["folder_size"] = folder_size
                            
                            # 保存到缓存
                            try:
                                from ..models.database import ExistingFolderCache
                                if cache:
                                    cache.duplicate_info = folder_info.get("duplicate_info")
                                    cache.file_count = file_count
                                    cache.folder_size = folder_size
                                    cache.updated_at = datetime.now()
                                    cache.needs_refresh = False
                                else:
                                    cache = ExistingFolderCache(
                                        folder_path=item_path,
                                        folder_name=item,
                                        rjcode=rjcode,
                                        duplicate_info=folder_info.get("duplicate_info"),
                                        file_count=file_count,
                                        folder_size=folder_size
                                    )
                                    db.add(cache)
                                db.commit()
                            except Exception as e:
                                logger.warning(f"保存缓存失败: {e}")
                                db.rollback()
                            
                            # 发送更新
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": False
                            }) + "\n"
                            
                        except Exception as e:
                            logger.warning(f"查重检查失败 {rjcode}: {e}")
                            folder_info["status"] = "error"
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "error": str(e)
                            }) + "\n"
                
                finally:
                    db.close()
                
                # 发送完成消息
                yield json.dumps({
                    "type": "complete",
                    "count": len(folders),
                    "conflict_count": conflict_count,
                    "folders": folders,
                    "message": f"扫描完成，找到 {len(folders)} 个文件夹" + (f"，其中 {conflict_count} 个可能有冲突" if conflict_count > 0 else "")
                }) + "\n"
            else:
                # 不检查重复，直接完成
                yield json.dumps({
                    "type": "complete",
                    "count": len(folders),
                    "conflict_count": 0,
                    "folders": folders,
                    "message": f"扫描完成，找到 {len(folders)} 个文件夹"
                }) + "\n"
            
        except Exception as e:
            logger.error(f"扫描已存在文件夹目录失败: {e}", exc_info=True)
            yield json.dumps({"type": "error", "error": f"扫描失败: {str(e)}"}) + "\n"
    
    return StreamingResponse(
        generate_folders(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/existing-folders/refresh-cache")
async def refresh_existing_folders_cache():
    """刷新所有已有文件夹的缓存信息"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 标记所有缓存需要刷新
            db.query(ExistingFolderCache).update({"needs_refresh": True})
            db.commit()
            
            return {"message": "已标记所有缓存需要刷新，下次扫描时将重新获取信息"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"刷新缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"刷新缓存失败: {str(e)}")

@app.post("/api/existing-folders/clear-cache")
async def clear_existing_folders_cache():
    """清除所有已有文件夹的缓存"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 删除所有缓存
            deleted_count = db.query(ExistingFolderCache).delete()
            db.commit()
            
            return {"message": f"已清除 {deleted_count} 条缓存"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"清除缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/existing-folders/check-duplicates")
async def check_existing_folders_duplicates(request: Request):
    """批量检查已有文件夹的查重情况
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "check_linked_works": true,
        "cue_languages": ["CHI_HANS", "CHI_HANT", "ENG"]
    }
    """
    try:
        data = await request.json()
        folder_paths = data.get("folders", [])
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT", "ENG"])
        
        if not folder_paths:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        from ..core.duplicate_service import get_duplicate_service
        duplicate_service = get_duplicate_service()
        
        results = []
        for folder_path in folder_paths:
            # 提取RJ号
            folder_name = os.path.basename(folder_path)
            rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
            rjcode = rj_match.group(0).upper() if rj_match else None
            
            if not rjcode:
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": None,
                    "error": "无法提取RJ号"
                })
                continue
            
            try:
                check_result = await duplicate_service.check_duplicate_enhanced(
                    rjcode,
                    check_linked_works=check_linked,
                    cue_languages=cue_languages
                )
                
                result = {
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "is_duplicate": check_result.is_duplicate,
                    "conflict_type": check_result.conflict_type,
                }
                
                if check_result.is_duplicate:
                    result.update({
                        "direct_duplicate": check_result.direct_duplicate,
                        "linked_works_found": check_result.linked_works_found,
                        "related_rjcodes": check_result.related_rjcodes,
                        "analysis_info": check_result.analysis_info
                    })
                    
                    # 获取推荐的解决选项
                    resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                    result["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"查重检查失败 {rjcode}: {e}")
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "error": str(e)
                })
        
        # 统计
        duplicate_count = sum(1 for r in results if r.get("is_duplicate"))
        
        return {
            "message": f"检查完成，发现 {duplicate_count}/{len(results)} 个冲突",
            "total": len(results),
            "duplicate_count": duplicate_count,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")

@app.post("/api/existing-folders/process")
async def process_existing_folders(request: Request):
    """处理选中的已存在文件夹
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "auto_classify": true
    }
    """
    try:
        from ..core.activity_log_service import log_import_batch_start_result
        data = await request.json()
        folders = data.get("folders", [])
        auto_classify = data.get("auto_classify", True)
        
        if not folders:
            raise HTTPException(status_code=400, detail="未选择任何文件夹")
        
        # 验证所有路径是否有效
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        valid_folders = []
        for folder_path in folders:
            # 安全检查：确保路径在 existing_folders_path 目录下
            if not folder_path.startswith(existing_folders_path):
                logger.warning(f"路径不在已存在文件夹目录下，跳过: {folder_path}")
                continue
            
            if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
                logger.warning(f"路径不存在或不是文件夹，跳过: {folder_path}")
                continue
            
            valid_folders.append(folder_path)
        
        if not valid_folders:
            raise HTTPException(status_code=400, detail="没有有效的文件夹可以处理")
        
        # 创建处理任务
        engine = get_task_engine()
        created_tasks = []
        batch_id = str(uuid.uuid4())

        for folder_path in valid_folders:
            task = Task(
                task_type=TaskType.PROCESS_EXISTING_FOLDER,
                source_path=folder_path,
                auto_classify=auto_classify,
                metadata={
                    "batch_id": batch_id,
                    "session_id": batch_id,
                    "batch_title": "批量已有目录处理",
                    "batch_label": "已有目录处理批次",
                    "batch_requested_count": len(valid_folders),
                    "batch_log_parent": True,
                    "source_page": "existing-folders",
                    "source_action": "process_existing_batch",
                    "source_label": "已有目录页 / 批量处理",
                }
            )
            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "folder_path": folder_path
            })

        log_import_batch_start_result(
            {
                "batch_id": batch_id,
                "requested_count": len(valid_folders),
                "created_count": len(created_tasks),
                "skipped_total": max(0, len(folders) - len(valid_folders)),
                "archive_count": 0,
                "extracted_count": 0,
                "auto_classify": bool(auto_classify),
                "source_page": "existing-folders",
                "source_action": "process_existing_batch",
                "source_label": "已有目录页 / 批量处理",
                "source_paths": valid_folders,
                "created_tasks": created_tasks,
                "skipped_items": [
                    {"folder_path": folder_path, "reason": "invalid_path"}
                    for folder_path in folders
                    if folder_path not in valid_folders
                ],
                "source_path": valid_folders[0] if valid_folders else None,
            },
            category="process_existing",
        )

        return {
            "message": f"已创建 {len(created_tasks)} 个处理任务",
            "requested": len(folders),
            "created": len(created_tasks),
            "batch_id": batch_id,
            "tasks": created_tasks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理已存在文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@app.post("/api/existing-folders/delete")
async def delete_existing_folder(request: Request):
    """删除已有文件夹（用于抛弃新版）
    
    请求体格式：
    {
        "path": "/path/to/folder"
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("path")
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        if not folder_path.startswith(existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录下")
        
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        
        # 删除文件夹
        import shutil
        shutil.rmtree(folder_path)
        logger.info(f"已删除文件夹: {folder_path}")
        
        return {"message": "文件夹已删除", "path": folder_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@app.post("/api/existing-folders/merge-preview")
async def get_existing_folder_merge_preview(request: Request):
    """生成已存在文件夹的合并对比预览"""
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        existing_path = data.get("existing_path")

        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供待处理文件夹路径")

        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        if not folder_path.startswith(existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录中")
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="待处理文件夹不存在")

        resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, existing_path)
        if not resolved_existing_path:
            raise HTTPException(status_code=404, detail="未找到可合并的现有目录")
        if not os.path.exists(resolved_existing_path):
            raise HTTPException(status_code=404, detail="目标现有目录不存在")

        from ..core.folder_compare_service import get_folder_compare_service

        compare_service = get_folder_compare_service()
        items = compare_service.build_compare_items(folder_path, resolved_existing_path)
        decisions = compare_service.build_default_decisions(items)

        summary = {
            "new_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "new_only"),
            "old_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "old_only"),
            "modified": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "modified"),
            "unchanged": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "unchanged"),
        }

        return {
            "folder_path": folder_path,
            "existing_path": resolved_existing_path,
            "items": items,
            "default_decisions": decisions,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成合并预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成合并预览失败: {str(e)}")

@app.post("/api/existing-folders/process-with-resolution")
async def process_existing_folder_with_resolution(request: Request):
    """使用指定的解决方案处理已有文件夹
    
    请求体格式：
    {
        "folder_path": "/path/to/folder",
        "resolution": "KEEP_NEW|MERGE|SKIP",
        "auto_classify": true,
        "existing_path": "/path/to/current/library/folder",
        "merge_decisions": {"relative/path.txt": "use_new"}
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        resolution = data.get("resolution")
        auto_classify = data.get("auto_classify", True)
        preferred_existing_path = data.get("existing_path")
        merge_decisions = data.get("merge_decisions") or {}
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        if not resolution:
            raise HTTPException(status_code=400, detail="未提供解决方案")
        normalized_resolution = str(resolution).strip().upper()
        if normalized_resolution == "KEEP_OLD":
            normalized_resolution = "SKIP"
        if normalized_resolution in {"KEEP_BOTH", "MERGE_LANG"}:
            normalized_resolution = "MERGE"
        if normalized_resolution not in {"KEEP_NEW", "MERGE", "SKIP"}:
            raise HTTPException(status_code=400, detail="不支持的解决方案")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        if not folder_path.startswith(existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录下")
        
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        
        # 根据解决方案执行不同操作
        if normalized_resolution == "SKIP":
            # 抛弃新版 - 删除文件夹
            import shutil
            shutil.rmtree(folder_path)
            logger.info(f"已抛弃新版（删除文件夹）: {folder_path}")
            return {"message": "已跳过当前目录，待处理文件夹已删除", "resolution": normalized_resolution}
        
        elif normalized_resolution in ["KEEP_NEW", "MERGE"]:
            resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, preferred_existing_path)
            if not resolved_existing_path:
                raise HTTPException(status_code=404, detail="未找到要替换或合并的现有目录")
            if not os.path.exists(resolved_existing_path):
                raise HTTPException(status_code=404, detail="现有目录不存在")

            # 这些操作都需要创建处理任务
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                # 提取RJ号
                folder_name = os.path.basename(folder_path)
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                if rjcode:
                    # 查找对应的冲突记录并更新状态
                    conflict = db.query(ConflictWork).filter(
                        ConflictWork.rjcode == rjcode,
                        ConflictWork.status == 'PENDING'
                    ).first()
                    
                    if conflict:
                        conflict.status = normalized_resolution
                        db.commit()
                        logger.info(f"更新冲突记录状态: {rjcode} -> {normalized_resolution}")
                
                # 创建处理任务
                engine = get_task_engine()
                task = Task(
                    task_type=TaskType.PROCESS_EXISTING_FOLDER,
                    source_path=folder_path,
                    auto_classify=auto_classify,
                    metadata={
                        "existing_folder_resolution": normalized_resolution,
                        "existing_path": resolved_existing_path,
                        "merge_decisions": merge_decisions if normalized_resolution == "MERGE" else {},
                    }
                )
                await engine.submit(task)
                
                return {
                    "message": f"已创建处理任务，解决方案: {normalized_resolution}",
                    "resolution": normalized_resolution,
                    "task_id": task.id,
                    "folder_path": folder_path,
                    "existing_path": resolved_existing_path,
                }
                
            finally:
                db.close()
        
        else:
            raise HTTPException(status_code=400, detail=f"未知的解决方案: {resolution}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

# ========== 关联作品查询 API（改进的查重功能）==========

@app.get("/api/linked-works/{rjcode}")
async def get_linked_works(
    rjcode: str,
    include_full_linkage: bool = True,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    获取作品的关联作品链
    
    Args:
        rjcode: RJ号
        include_full_linkage: 是否包含完整关联链（包括所有语言版本）
        cue_languages: 需要查询的语言列表，逗号分隔
    """
    from ..core.dlsite_service import get_dlsite_service
    
    try:
        service = get_dlsite_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        if include_full_linkage:
            linked_works = await service.get_full_linkage(rjcode, languages)
        else:
            linked_works = await service.get_linked_works(rjcode)
        
        # 获取翻译信息
        trans_info = await service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "translation_info": {
                "is_original": trans_info.is_original,
                "is_parent": trans_info.is_parent,
                "is_child": trans_info.is_child,
                "parent_workno": trans_info.parent_workno,
                "original_workno": trans_info.original_workno,
                "lang": trans_info.lang
            },
            "linked_works": {k: v.to_dict() for k, v in linked_works.items()},
            "total_count": len(linked_works)
        }
        
    except Exception as e:
        logger.error(f"获取关联作品失败 {rjcode}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取关联作品失败: {str(e)}")


@app.get("/api/linked-works/{rjcode}/check-library")
async def check_linked_works_in_library(
    rjcode: str,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    检查作品的关联作品是否在库中
    
    返回库中已存在的所有关联作品
    """
    from ..core.dlsite_service import get_dlsite_service
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        dlsite_service = get_dlsite_service()
        duplicate_service = get_duplicate_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        # 获取完整关联链
        linked_works = await dlsite_service.get_full_linkage(rjcode, languages)
        
        # 检查哪些在库中
        found_in_library = await duplicate_service._check_linked_works_in_library(
            linked_works, rjcode
        )
        
        # 获取翻译信息
        trans_info = await dlsite_service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "is_original": trans_info.is_original,
            "is_in_library": len(found_in_library) > 0,
            "library_works": [
                {
                    "rjcode": w.rjcode,
                    "work_type": w.work_type,
                    "lang": w.lang,
                    "work_name": w.work_name,
                    "path": w.folder_path,
                    "size": w.folder_size,
                    "file_count": w.file_count
                }
                for w in found_in_library
            ],
            "total_linked": len(linked_works),
            "found_in_library": len(found_in_library)
        }
        
    except Exception as e:
        logger.error(f"检查库中关联作品失败 {rjcode}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@app.post("/api/conflicts/enhanced-check")
async def enhanced_duplicate_check(request: Request):
    """
    改进的查重检查
    
    支持检测关联作品冲突
    """
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        data = await request.json()
        rjcode = data.get("rjcode")
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT"])
        
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")
        
        service = get_duplicate_service()
        result = await service.check_duplicate_enhanced(
            rjcode, 
            check_linked_works=check_linked,
            cue_languages=cue_languages
        )
        
        # 获取推荐的解决选项
        resolution_options = _normalize_existing_folder_resolution_options(
            await service.get_conflict_resolution_options(result)
        )
        
        return {
            "is_duplicate": result.is_duplicate,
            "conflict_type": result.conflict_type,
            "direct_duplicate": result.direct_duplicate,
            "linked_works_found": result.linked_works_found,
            "related_rjcodes": result.related_rjcodes,
            "analysis_info": result.analysis_info,
            "resolution_options": resolution_options
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"改进查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


# ========== Kikoeru 搜索配置 API ==========

@app.get("/api/kikoeru-configs")
async def get_kikoeru_configs():
    """获取所有 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        configs = db.query(KikoeruSearchConfig).all()
        return {
            "configs": [config.to_dict() for config in configs]
        }
    finally:
        db.close()


@app.post("/api/kikoeru-configs")
async def create_kikoeru_config(request: Request):
    """创建 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    import uuid
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = KikoeruSearchConfig(
            id=str(uuid.uuid4()),
            name=data.get("name", "Kikoeru"),
            search_url_template=data.get("search_url_template", ""),
            show_url_template=data.get("show_url_template", ""),
            enabled=data.get("enabled", False),
            custom_headers=data.get("custom_headers", {})
        )
        
        db.add(config)
        db.commit()
        
        return {
            "message": "配置已创建",
            "config": config.to_dict()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"创建 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")
    finally:
        db.close()


@app.put("/api/kikoeru-configs/{config_id}")
async def update_kikoeru_config(config_id: str, request: Request):
    """更新 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        if "name" in data:
            config.name = data["name"]
        if "search_url_template" in data:
            config.search_url_template = data["search_url_template"]
        if "show_url_template" in data:
            config.show_url_template = data["show_url_template"]
        if "enabled" in data:
            config.enabled = data["enabled"]
        if "custom_headers" in data:
            config.custom_headers = data["custom_headers"]
        
        db.commit()
        
        return {
            "message": "配置已更新",
            "config": config.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    finally:
        db.close()


@app.delete("/api/kikoeru-configs/{config_id}")
async def delete_kikoeru_config(config_id: str):
    """删除 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        db.delete(config)
        db.commit()
        
        return {"message": "配置已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()


# ========== Kikoeru 服务器查重配置 API ==========
from ..core.kikoeru_duplicate_service import get_kikoeru_service, KikoeruDuplicateService, KikoeruCheckResult

class KikoeruServerConfig(BaseModel):
    """Kikoeru 服务器配置模型"""
    enabled: bool = False
    server_url: str = ""
    username: str = ""
    password: str = ""
    api_token: str = ""
    token_expires: int = 0
    timeout: int = 10
    cache_ttl: int = 300
    enable_fuzzy_rj_match: bool = False

@app.get("/api/kikoeru-server/config")
async def get_kikoeru_server_config():
    """获取 Kikoeru 服务器查重配置"""
    try:
        config = get_config()
        kikoeru_config = config.kikoeru_server if hasattr(config, 'kikoeru_server') else None
        
        if kikoeru_config:
            return {
                "enabled": kikoeru_config.enabled,
                "server_url": kikoeru_config.server_url,
                "username": kikoeru_config.username,
                "password": kikoeru_config.password,
                "api_token": kikoeru_config.api_token,
                "token_expires": kikoeru_config.token_expires,
                "timeout": kikoeru_config.timeout,
                "cache_ttl": kikoeru_config.cache_ttl,
                "enable_fuzzy_rj_match": bool(getattr(kikoeru_config, 'enable_fuzzy_rj_match', False)),
            }
        else:
            return {
                "enabled": False,
                "server_url": "",
                "username": "",
                "password": "",
                "api_token": "",
                "token_expires": 0,
                "timeout": 10,
                "cache_ttl": 300,
                "enable_fuzzy_rj_match": False,
            }
    except Exception as e:
        logger.error(f"获取 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")

@app.post("/api/kikoeru-server/config")
async def update_kikoeru_server_config(config: KikoeruServerConfig):
    """更新 Kikoeru 服务器查重配置（已弃用，请使用 /api/config）"""
    try:
        from ..config.settings import save_config
        
        config_to_save = {
            'kikoeru_server': {
                'enabled': config.enabled,
                'server_url': config.server_url.rstrip('/'),
                'username': config.username,
                'password': config.password,
                'api_token': config.api_token,
                'token_expires': config.token_expires,
                'timeout': config.timeout,
                'cache_ttl': config.cache_ttl,
                'enable_fuzzy_rj_match': config.enable_fuzzy_rj_match,
            }
        }
        
        save_config(config_to_save)
        
        service = get_kikoeru_service()
        service.config = service._load_config()
        
        return {
            "message": "Kikoeru 服务器配置已更新",
            "config": {
                "enabled": config.enabled,
                "server_url": config.server_url,
                "timeout": config.timeout,
                "cache_ttl": config.cache_ttl,
                "enable_fuzzy_rj_match": config.enable_fuzzy_rj_match,
            }
        }
    except Exception as e:
        logger.error(f"更新 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

@app.post("/api/kikoeru-server/test")
async def test_kikoeru_server_connection():
    """测试 Kikoeru 服务器连接"""
    try:
        service = get_kikoeru_service()
        result = await service.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"测试 Kikoeru 服务器连接失败: {e}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
            "latency": 0
        }

@app.post("/api/kikoeru-server/check")
async def check_kikoeru_duplicate(
    rjcode: str,
    check_linkages: bool = True,
    cue_languages: str = "CHI_HANS CHI_HANT ENG JPN"
):
    """检查作品及其关联作品是否在 Kikoeru 服务器中

    Args:
        rjcode: RJ号
        check_linkages: 是否检查关联作品
        cue_languages: 语言列表，空格分隔（如 'CHI_HANS CHI_HANT ENG JPN'）
    """
    logger.info(f"=" * 60)
    logger.info(f"[Kikoeru查重] 开始查询: {rjcode}, check_linkages={check_linkages}")

    try:
        # 解析语言列表
        lang_list = cue_languages.split() if cue_languages else ["CHI_HANS", "CHI_HANT", "ENG", "JPN"]
        logger.info(f"[Kikoeru查重] 检查语言: {lang_list}")
        
        service = get_kikoeru_service()
        
        if check_linkages:
            # 查询关联作品
            logger.info(f"[Kikoeru查重] 执行关联作品查询...")
            results = await service.check_duplicate_with_linkages(rjcode, lang_list, use_cache=True)
            
            # 格式化返回结果
            found_works = []
            for rj, res in results.items():
                if res.is_found:
                    found_works.append({
                        "rjcode": rj,
                        "title": res.title,
                        "circle_name": res.circle_name,
                        "tags": res.tags
                    })
            
            primary_result = results.get(rjcode, KikoeruCheckResult(rjcode=rjcode))
            
            logger.info(f"[Kikoeru查重] 关联查询完成: 总共 {len(results)} 个作品，找到 {len(found_works)} 个")
            
            return {
                "rjcode": rjcode,
                "is_found": primary_result.is_found or len(found_works) > 0,
                "title": primary_result.title,
                "circle_name": primary_result.circle_name,
                "tags": primary_result.tags,
                "linked_works_found": found_works,
                "total_checked": len(results),
                "source": "kikoeru_with_linkages",
                "checked_at": datetime.now().isoformat()
            }
        else:
            # 只查询单个作品
            result = await service.check_duplicate(rjcode, use_cache=True)
            
            return {
                "rjcode": result.rjcode,
                "is_found": result.is_found,
                "title": result.title,
                "circle_name": result.circle_name,
                "tags": result.tags,
                "linked_works_found": [],
                "total_checked": 1,
                "source": result.source,
                "checked_at": result.checked_at.isoformat() if result.checked_at else None
            }
    except Exception as e:
        logger.error(f"[Kikoeru查重] 查询失败: {rjcode}, 错误: {e}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"查重检查失败: {str(e)}")
    finally:
        logger.info(f"[Kikoeru查重] 查询结束: {rjcode}")
        logger.info(f"=" * 60)

@app.post("/api/kikoeru-server/clear-cache")
async def clear_kikoeru_cache():
    """清除 Kikoeru 查重缓存"""
    try:
        service = get_kikoeru_service()
        service.clear_cache()

        return {"message": "Kikoeru 查重缓存已清除"}
    except Exception as e:
        logger.error(f"清除 Kikoeru 缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/kikoeru-server/get-token")
async def get_kikoeru_token():
    """手动获取 Kikoeru 服务器的 Token"""
    try:
        service = get_kikoeru_service()

        # 重新加载配置，确保使用最新的配置
        service.config = service._load_config()

        # 检查配置
        if not service.config.server_url:
            raise HTTPException(status_code=400, detail="请先配置服务器地址")

        if not service.config.username or not service.config.password:
            raise HTTPException(status_code=400, detail="请先配置用户名和密码")

        logger.info(f"[Kikoeru] 使用服务器地址: {service.config.server_url}")
        logger.info(f"[Kikoeru] 使用用户名: {service.config.username}")

        # 调用登录方法获取 Token
        success = await service._login()

        if success:
            return {
                "success": True,
                "token": service.config.api_token,
                "expires": service.config.token_expires,
                "message": "Token 获取成功"
            }
        else:
            raise HTTPException(status_code=401, detail="获取 Token 失败，请检查用户名和密码")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Kikoeru Token 失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Token 失败: {str(e)}")


# ========== ASMR 同步下载 API ==========

class RJSubtitleScanRequest(BaseModel):
    """RJ 字幕扫描请求"""
    folder_path: str
    library_id: Optional[str] = None
    scan_depth: int = 3
    scan_one_level_only: Optional[bool] = None


class RJSubtitleStartRequest(BaseModel):
    """RJ 字幕抓取开始请求"""
    items: List[dict]  # [{rjcode, folder_path, folder_name}]
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    skip_if_existing_subtitles: bool = False
    force_rerun: bool = False
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []
    batch_context: Optional[dict] = None


class RJSubtitleManualCompleteRequest(BaseModel):
    applied_pairs: int = 0
    deleted_subtitles: int = 0
    naming_strategy: str = "audio"
    pair_changes: List[dict] = []
    folder_path: str = ""
    library_id: Optional[str] = None
    rjcode: str = ""


class RJSubtitleRerunRequest(BaseModel):
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class RJSubtitleAvailabilityRequest(BaseModel):
    rjcode: str


class RJSubtitleFolderSubtitleStateRequest(BaseModel):
    folder_path: str
    library_id: Optional[str] = None


class RJSubtitleKikoeruSubtitleStateRequest(BaseModel):
    rjcode: str


class LinkedSubtitleArchivePreviewRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None


class LinkedSubtitleFolderPreviewRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    source_rjcode_hint: Optional[str] = None


class LinkedSubtitleArchiveImportRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitleFolderImportRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    source_rjcode_hint: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitlePendingImportExecuteRequest(BaseModel):
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []

class LinkedSubtitlePendingClearRequest(BaseModel):
    record_ids: List[str] = []
    clear_all: bool = False


@app.post("/api/rj-subtitle/scan")
async def rj_subtitle_scan(request: RJSubtitleScanRequest):
    """扫描单个 RJ 文件夹或批量父目录"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        folder_path = request.folder_path
        service = get_rj_subtitle_service()
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)
        if request.library_id:
            manager = get_library_manager()
            library = manager.get_library_definition(request.library_id)
            if library.type == "synology_filestation":
                items = await service.scan_remote(
                    request.library_id,
                    folder_path,
                    scan_depth=scan_depth,
                )
                return {
                    "success": True,
                    "folder_path": folder_path,
                    "total_found": len(items),
                    "ready_count": len([item for item in items if item["status"] == "ready"]),
                    "items": items,
                }
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")
        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        items = service.scan(
            folder_path,
            scan_depth=scan_depth,
        )

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(items),
            "ready_count": len([item for item in items if item["status"] == "ready"]),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描 RJ 字幕目录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/rj-subtitle/scan-stream")
async def rj_subtitle_scan_stream(request: RJSubtitleScanRequest):
    """流式扫描 RJ 目录，发现一个就返回一个。"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    async def generate():
        service = get_rj_subtitle_service()
        folder_path = request.folder_path
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)

        total_found = 0
        ready_count = 0
        existing_count = 0
        no_audio_count = 0
        event_queue: asyncio.Queue = asyncio.Queue()

        def dump(payload):
            return json.dumps(payload, ensure_ascii=False) + "\n"

        def enqueue(payload):
            try:
                event_queue.put_nowait(payload)
            except Exception:
                logger.debug("RJ 字幕扫描流事件入队失败: %s", payload, exc_info=True)

        display_name = PurePosixPath(folder_path).name or os.path.basename(folder_path) or folder_path
        enqueue({
            "type": "target_result",
            "path": folder_path,
            "name": display_name,
            "status": "pending",
            "message": "正在扫描..."
        })

        def emit_progress(current_scan_path: str):
            current_display = PurePosixPath(current_scan_path).name or os.path.basename(current_scan_path) or current_scan_path
            enqueue({
                "type": "progress",
                "path": folder_path,
                "current_path": current_scan_path,
                "message": f"正在扫描 {current_display}..."
            })

        async def produce():
            nonlocal total_found, ready_count, existing_count, no_audio_count
            try:
                if request.library_id:
                    manager = get_library_manager()
                    library = manager.get_library_definition(request.library_id)
                    if library.type == "synology_filestation":
                        async for item in service.scan_remote_iter(
                            request.library_id,
                            folder_path,
                            scan_depth=scan_depth,
                            progress_callback=emit_progress,
                        ):
                            total_found += 1
                            if item.get("status") == "ready":
                                ready_count += 1
                            elif item.get("status") == "existing":
                                existing_count += 1
                            elif item.get("status") == "no_audio":
                                no_audio_count += 1
                            enqueue({"type": "item", "item": item})
                        enqueue({
                            "type": "target_result",
                            "path": folder_path,
                            "name": display_name,
                            "status": "success" if total_found else "no_match",
                            "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                            "summary": {
                                "found": total_found,
                                "ready": ready_count,
                                "existing": existing_count,
                                "no_audio": no_audio_count,
                            }
                        })
                        enqueue({
                            "type": "complete",
                            "folder_path": folder_path,
                            "total_found": total_found,
                            "ready_count": ready_count,
                            "existing_count": existing_count,
                            "no_audio_count": no_audio_count,
                        })
                        return

                if not os.path.exists(folder_path):
                    raise HTTPException(status_code=400, detail="指定的文件夹不存在")
                if not os.path.isdir(folder_path):
                    raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

                for item in service.scan_iter(folder_path, scan_depth=scan_depth, progress_callback=emit_progress):
                    total_found += 1
                    if item.get("status") == "ready":
                        ready_count += 1
                    elif item.get("status") == "existing":
                        existing_count += 1
                    elif item.get("status") == "no_audio":
                        no_audio_count += 1
                    enqueue({"type": "item", "item": item})

                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "success" if total_found else "no_match",
                    "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                    "summary": {
                        "found": total_found,
                        "ready": ready_count,
                        "existing": existing_count,
                        "no_audio": no_audio_count,
                    }
                })
                enqueue({
                    "type": "complete",
                    "folder_path": folder_path,
                    "total_found": total_found,
                    "ready_count": ready_count,
                    "existing_count": existing_count,
                    "no_audio_count": no_audio_count,
                })
            except HTTPException as exc:
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": exc.detail,
                })
                enqueue({"type": "error", "error": exc.detail})
            except Exception as exc:
                logger.error(f"流式扫描 RJ 字幕目录失败: {exc}", exc_info=True)
                message = f"扫描失败: {str(exc)}"
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": message,
                })
                enqueue({"type": "error", "error": message})
            finally:
                enqueue({"type": "stream_end"})

        producer = asyncio.create_task(produce())
        try:
            while True:
                payload = await event_queue.get()
                if payload.get("type") == "stream_end":
                    break
                yield dump(payload)
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/rj-subtitle/start")
async def rj_subtitle_start(request: RJSubtitleStartRequest):
    """开始 RJ 字幕抓取任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine
    from ..core.rj_subtitle_service import get_rj_subtitle_service
    from ..core.activity_log_service import log_subtitle_batch_start_result

    try:
        engine = get_task_engine()
        rj_service = get_rj_subtitle_service()
        created_tasks = []
        skipped_existing = 0
        skipped_duplicate = 0
        skipped_items = []
        batch_context = request.batch_context if isinstance(request.batch_context, dict) else {}
        batch_id = str(batch_context.get("batch_id") or "").strip()
        log_parent = bool(batch_context.get("log_parent"))
        source_directories = batch_context.get("source_directories") if isinstance(batch_context.get("source_directories"), list) else []
        scan_targets = batch_context.get("scan_targets") if isinstance(batch_context.get("scan_targets"), list) else []
        should_log_batch = bool(batch_id) and log_parent

        if not request.items:
            if should_log_batch:
                summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
                recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or 0)
                skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
                log_subtitle_batch_start_result({
                    "batch_id": batch_id,
                    "requested_count": int(batch_context.get("requested_count") or 0),
                    "recognized_rj_count": recognized_rj_count,
                    "created_count": 0,
                    "skipped_total": skipped_no_subtitle,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "skipped_no_subtitle": skipped_no_subtitle,
                    "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                    "force_rerun": request.force_rerun,
                    "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                    "naming_strategy": request.naming_strategy,
                    "source_directories": source_directories,
                    "scan_targets": scan_targets,
                    "created_tasks": [],
                    "skipped_items": [],
                    "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
                })
                return {
                    "success": True,
                    "message": "本次批量扫描未命中可创建的 RJ 字幕任务",
                    "created_count": 0,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "batch_id": batch_id or None,
                    "skipped_items": [],
                    "tasks": [],
                }
            raise HTTPException(status_code=400, detail="没有可执行的 RJ 文件夹")

        for item in request.items:
            folder_path = str(item.get("folder_path") or "").strip()
            rjcode = str(item.get("rjcode") or "").strip().upper()
            folder_name = str(item.get("folder_name") or "")
            library_id = str(item.get("library_id") or "").strip() or None
            if not folder_path:
                continue

            resolved_existing_subtitle_count = int(item.get("existing_subtitle_count") or 0)
            kikoeru_state = None

            if request.skip_if_existing_subtitles and rjcode:
                try:
                    kikoeru_state = await rj_service.check_kikoeru_existing_subtitles(rjcode)
                except Exception as exc:
                    logger.warning(
                        "[RJ字幕] 查询 Kikoeru 字幕状态失败，继续后续流程: rj=%s error=%s",
                        rjcode,
                        exc,
                    )
                    kikoeru_state = None

                if kikoeru_state and bool(kikoeru_state.get("has_existing_subtitles")):
                    skipped_existing += 1
                    matched_rjcode = str(kikoeru_state.get("matched_rjcode") or rjcode).upper()
                    subtitle_file_count = int(kikoeru_state.get("subtitle_file_count") or 0)
                    queue_message = f"Kikoeru 已有字幕（{matched_rjcode}"
                    if subtitle_file_count > 0:
                        queue_message += f" / {subtitle_file_count} 个"
                    queue_message += "），未加入抓取任务"
                    skipped_items.append({
                        "rjcode": rjcode,
                        "folder_name": folder_name,
                        "folder_path": folder_path,
                        "library_id": library_id,
                        "existing_subtitle_count": resolved_existing_subtitle_count,
                        "queue_state": "skipped_kikoeru_existing",
                        "queue_message": queue_message,
                        "kikoeru_checked_rjcode": kikoeru_state.get("checked_rjcode", rjcode),
                        "kikoeru_has_work": bool(kikoeru_state.get("has_work")),
                        "kikoeru_has_existing_subtitles": True,
                        "kikoeru_matched_rjcode": matched_rjcode,
                        "kikoeru_subtitle_file_count": subtitle_file_count,
                        "kikoeru_subtitle_check_source": kikoeru_state.get("subtitle_check_source", ""),
                    })
                    continue

            duplicate_task = next((
                current_task for current_task in engine.get_all_tasks()
                if current_task.type == TaskType.RJ_SUBTITLE_FETCH
                and str(current_task.task_metadata.get("folder_path") or current_task.source_path) == str(folder_path)
                and current_task.status.value in {"pending", "processing", "paused"}
            ), None)
            if duplicate_task:
                skipped_duplicate += 1
                skipped_items.append({
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "folder_path": folder_path,
                    "library_id": library_id,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "task_id": duplicate_task.id,
                    "queue_state": "existing_task",
                    "queue_message": "任务已存在",
                })
                continue

            task = Task(
                task_type=TaskType.RJ_SUBTITLE_FETCH,
                source_path=folder_path,
                auto_classify=False,
                metadata={
                    "folder_path": folder_path,
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "library_id": library_id,
                    "overwrite": request.overwrite_existing,
                    "enable_metadata_match": request.enable_metadata_match,
                    "skip_if_existing_subtitles": False if request.force_rerun else request.skip_if_existing_subtitles,
                    "force_rerun": request.force_rerun,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "naming_strategy": request.naming_strategy,
                    "use_filter_rules": request.use_filter_rules,
                    "subtitle_filter_rules": request.subtitle_filter_rules,
                    "batch_id": batch_id or None,
                    "kikoeru_checked_rjcode": (kikoeru_state or {}).get("checked_rjcode", rjcode),
                    "kikoeru_has_work": bool((kikoeru_state or {}).get("has_work")),
                    "kikoeru_has_existing_subtitles": bool((kikoeru_state or {}).get("has_existing_subtitles")),
                    "kikoeru_matched_rjcode": (kikoeru_state or {}).get("matched_rjcode", ""),
                    "kikoeru_subtitle_file_count": int((kikoeru_state or {}).get("subtitle_file_count") or 0),
                    "kikoeru_subtitle_check_source": (kikoeru_state or {}).get("subtitle_check_source", ""),
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "folder_name": folder_name,
                "folder_path": folder_path,
                "library_id": library_id,
            })

        if should_log_batch:
            summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
            requested_count = int(batch_context.get("requested_count") or len(request.items))
            recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or len(request.items))
            skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
            log_subtitle_batch_start_result({
                "batch_id": batch_id,
                "requested_count": requested_count,
                "recognized_rj_count": recognized_rj_count,
                "created_count": len(created_tasks),
                "skipped_total": skipped_existing + skipped_duplicate + skipped_no_subtitle,
                "skipped_existing": skipped_existing,
                "skipped_duplicate": skipped_duplicate,
                "skipped_no_subtitle": skipped_no_subtitle,
                "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                "force_rerun": request.force_rerun,
                "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                "naming_strategy": request.naming_strategy,
                "source_directories": source_directories,
                "scan_targets": scan_targets,
                "created_tasks": created_tasks,
                "skipped_items": skipped_items,
                "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个 RJ 字幕抓取任务",
            "created_count": len(created_tasks),
            "skipped_existing": skipped_existing,
            "skipped_duplicate": skipped_duplicate,
            "batch_id": batch_id or None,
            "skipped_items": skipped_items,
            "tasks": created_tasks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动 RJ 字幕抓取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/rj-subtitle/folder-subtitle-state")
async def rj_subtitle_folder_subtitle_state(request: RJSubtitleFolderSubtitleStateRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        folder_path = str(request.folder_path or "").strip()
        library_id = str(request.library_id or "").strip()
        if not folder_path:
            raise HTTPException(status_code=400, detail="目录路径不能为空")
        if not library_id:
            raise HTTPException(status_code=400, detail="库存 ID 不能为空")

        summary = await get_linked_subtitle_import_service().summarize_target_folder(library_id, folder_path)
        if not summary:
            raise HTTPException(status_code=404, detail="未找到目录摘要")

        return {
            "success": True,
            "folder_path": folder_path,
            "library_id": library_id,
            "has_existing_subtitles": bool(summary.get("has_existing_subtitles")),
            "existing_subtitle_count": int(summary.get("existing_subtitle_count") or 0),
            "subtitle_dir": str(summary.get("subtitle_dir") or ""),
            "audio_count": int(summary.get("audio_count") or 0),
            "ready_for_import": bool(summary.get("ready_for_import")),
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RJ 目录字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/kikoeru-subtitle-state")
async def rj_subtitle_kikoeru_subtitle_state(request: RJSubtitleKikoeruSubtitleStateRequest):
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        state = await get_rj_subtitle_service().check_kikoeru_existing_subtitles(rjcode)
        return {
            "success": True,
            **state,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Kikoeru 字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/manual-complete")
async def rj_subtitle_manual_complete(
    task_id: str,
    request: RJSubtitleManualCompleteRequest,
    db: Session = Depends(get_db),
):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        applied_pairs = max(0, int(request.applied_pairs or 0))
        deleted_subtitles = max(0, int(request.deleted_subtitles or 0))
        fallback_folder_path = str(request.folder_path or "").strip()
        fallback_rjcode = str(request.rjcode or "").strip().upper()
        pair_changes = request.pair_changes if isinstance(request.pair_changes, list) else []
        pair_changes = pair_changes[:200]
        fallback_crawl_row = None

        if task and task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")

        if not task:
            crawl_query = (
                db.query(ActivityLog)
                .filter(ActivityLog.category == "subtitle_crawl")
                .order_by(desc(ActivityLog.created_at))
            )
            if task_id:
                fallback_crawl_row = crawl_query.filter(ActivityLog.task_id == task_id).first()
            if not fallback_crawl_row and fallback_folder_path:
                path_query = crawl_query.filter(ActivityLog.source_path == fallback_folder_path)
                if fallback_rjcode:
                    path_query = path_query.filter(ActivityLog.rjcode == fallback_rjcode)
                fallback_crawl_row = path_query.first()
            if not fallback_crawl_row and fallback_rjcode:
                fallback_crawl_row = crawl_query.filter(ActivityLog.rjcode == fallback_rjcode).first()
            if not fallback_crawl_row:
                raise HTTPException(status_code=404, detail="任务不存在，且未找到对应的字幕抓取记录")

            crawl_detail = fallback_crawl_row.detail if isinstance(fallback_crawl_row.detail, dict) else {}
            naming_strategy = str(request.naming_strategy or crawl_detail.get("naming_strategy") or "audio").lower()
            rj_log = fallback_rjcode or str(fallback_crawl_row.rjcode or "").strip().upper()
            source_path = fallback_folder_path or str(fallback_crawl_row.source_path or "").strip()
            summary_parts = [f"后处理完成，已应用 {applied_pairs} 组配对"]
            if deleted_subtitles:
                summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
            summary = "，".join(summary_parts)

            from ..core.activity_log_service import log_subtitle_pair_complete

            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "batch_id": str(crawl_detail.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": source_path or None,
                    "library_id": str(request.library_id or crawl_detail.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                    "manual_match_completed": True,
                },
                source_path=source_path or None,
            )
            return {
                "success": True,
                "message": summary,
                "task_id": task_id,
                "fallback_logged": True,
            }

        naming_strategy = str(request.naming_strategy or task.task_metadata.get("naming_strategy") or "audio").lower()
        linked_finalize_result = await get_linked_subtitle_import_service().finalize_manual_match_task(task)

        task.task_metadata = task.task_metadata or {}
        task.task_metadata["awaiting_manual_match"] = False
        task.task_metadata["manual_match_completed"] = True
        task.task_metadata["manual_match_completed_at"] = datetime.now().isoformat()
        task.task_metadata["manual_match_applied_pairs"] = applied_pairs
        task.task_metadata["manual_match_deleted_subtitles"] = deleted_subtitles
        task.task_metadata["naming_strategy"] = naming_strategy

        summary_parts = [f"后处理完成，已应用 {applied_pairs} 组配对"]
        if deleted_subtitles:
            summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
        if linked_finalize_result.get("applied"):
            summary_parts.append(
                f"已确认导入目标目录，共 {int(linked_finalize_result.get('final_file_count') or 0)} 个字幕"
            )
        summary = "，".join(summary_parts)

        task.progress = 100
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.current_step = summary

        logs = task.task_metadata.get("progress_log", [])
        logs.append({
            "time": datetime.now().isoformat(),
            "progress": 100,
            "level": "success",
            "message": summary,
        })
        task.task_metadata["progress_log"] = logs[-30:]

        try:
            from ..core.activity_log_service import log_subtitle_pair_complete, log_subtitle_import_action

            rj_log = str(task.task_metadata.get("rjcode") or "").strip().upper()
            _lf = linked_finalize_result if isinstance(linked_finalize_result, dict) else {}
            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "applied": _lf.get("applied"),
                    "final_file_count": _lf.get("final_file_count"),
                    "reason": _lf.get("reason"),
                    "batch_id": str(task.task_metadata.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
                    "library_id": str(task.task_metadata.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                },
                source_path=str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
            )
            if _lf.get("applied"):
                imported_count = int(_lf.get("final_file_count") or 0)
                import_target_rj = str(
                    task.task_metadata.get("target_rjcode")
                    or task.task_metadata.get("actual_rjcode")
                    or rj_log
                    or ""
                ).strip().upper()
                import_source_path = str(
                    task.task_metadata.get("source_archive_path")
                    or task.task_metadata.get("source_subtitle_folder_path")
                    or task.source_path
                    or ""
                ).strip() or None
                import_action = (
                    "archive_import"
                    if str(task.task_metadata.get("source_mode") or "").strip() == "linked_translation_archive_import"
                    else "folder_import"
                )
                log_subtitle_import_action(
                    action=import_action,
                    success=True,
                    summary=f"字幕补配完成，共导入 {imported_count} 个字幕文件",
                    detail={
                        "task_id": task_id,
                        "final_file_count": imported_count,
                        "target_rjcode": import_target_rj or None,
                        "source_rjcode": str(task.task_metadata.get("rjcode") or "").strip().upper() or None,
                        "manual_match_completed": True,
                        "manual_match_applied_pairs": applied_pairs,
                        "manual_match_deleted_subtitles": deleted_subtitles,
                    },
                    rjcode=import_target_rj or rj_log or None,
                    task_id=task_id,
                    source_path=import_source_path,
                )
        except Exception:
            logger.warning("[操作记录] 字幕配对记录失败", exc_info=True)

        return {"success": True, "task_id": task_id, "message": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记 RJ 字幕后处理完成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"标记失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/rerun")
async def rj_subtitle_rerun_task(task_id: str, request: RJSubtitleRerunRequest):
    from ..core.task_engine import get_task_engine

    try:
        task = await get_task_engine().rerun_rj_subtitle_task(task_id, {
            "overwrite": request.overwrite_existing,
            "enable_metadata_match": request.enable_metadata_match,
            "naming_strategy": request.naming_strategy,
            "use_filter_rules": request.use_filter_rules,
            "subtitle_filter_rules": request.subtitle_filter_rules,
        })
        return {
            "success": True,
            "task_id": task.id,
            "message": "任务已重置并重新加入抓取队列"
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        logger.error(f"重跑 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重跑失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/clear")
async def rj_subtitle_clear_task(task_id: str):
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task or task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status.value in {"pending", "processing", "paused"}:
            raise HTTPException(status_code=400, detail="任务仍在执行中，不能清理")

        engine.remove_task(task_id)
        return {"success": True, "task_id": task_id, "message": "任务已清理"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@app.post("/api/rj-subtitle/subtitle-availability")
async def rj_subtitle_availability(request: RJSubtitleAvailabilityRequest):
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        service = get_rj_subtitle_service()
        source, attempts = await service.find_best_subtitle_source(rjcode)

        return {
            "success": True,
            "rjcode": rjcode,
            "has_subtitle": bool(source),
            "selected_source": {
                "rjcode": source.get("rjcode", ""),
                "lang": source.get("lang", ""),
                "work_type": source.get("work_type", ""),
                "title": source.get("title", ""),
                "subtitle_count": len(source.get("subtitle_files", []) or []),
            } if source else None,
            "attempts": attempts,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检测 RJ 字幕可用性失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@app.get("/api/rj-subtitle/status")
async def rj_subtitle_status():
    """获取 RJ 字幕抓取任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()
        rj_tasks = [task for task in all_tasks if task.type == TaskType.RJ_SUBTITLE_FETCH]
        status_weight = {
            "processing": 0,
            "pending": 1,
            "paused": 2,
            "completed": 3,
            "failed": 4,
        }
        rj_tasks.sort(
            key=lambda task: (
                status_weight.get(task.status.value, 99),
                -(task.created_at.timestamp() if task.created_at else 0),
            )
        )

        return {
            "total_tasks": len(rj_tasks),
            "processing": len([task for task in rj_tasks if task.status.value == "processing"]),
            "pending": len([task for task in rj_tasks if task.status.value == "pending"]),
            "completed": len([task for task in rj_tasks if task.status.value == "completed"]),
            "failed": len([task for task in rj_tasks if task.status.value == "failed"]),
            "tasks": [
                {
                    "id": task.id,
                    "rjcode": task.task_metadata.get("rjcode", ""),
                    "actual_rjcode": task.task_metadata.get("actual_rjcode", ""),
                    "folder_name": task.task_metadata.get("folder_name", ""),
                    "folder_path": task.task_metadata.get("folder_path", task.source_path),
                    "library_id": task.task_metadata.get("library_id", ""),
                    "status": task.status.value,
                    "is_cancelled": task.is_cancelled(),
                    "progress": task.progress,
                    "current_step": task.current_step,
                    "error_message": task.error_message,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "source_lang": task.task_metadata.get("source_lang", ""),
                    "source_work_type": task.task_metadata.get("source_work_type", ""),
                    "source_title": task.task_metadata.get("source_title", ""),
                    "source_mode": task.task_metadata.get("source_mode", ""),
                    "target_rjcode": task.task_metadata.get("target_rjcode", ""),
                    "target_folder_path": task.task_metadata.get("target_folder_path", ""),
                    "target_library_id": task.task_metadata.get("target_library_id", ""),
                    "subtitle_library_id": task.task_metadata.get("subtitle_library_id", task.task_metadata.get("library_id", "")),
                    "source_archive_path": task.task_metadata.get("source_archive_path", ""),
                    "source_subtitle_folder_path": task.task_metadata.get("source_subtitle_folder_path", ""),
                    "import_reason": task.task_metadata.get("import_reason", ""),
                    "kikoeru_checked_rjcode": task.task_metadata.get("kikoeru_checked_rjcode", ""),
                    "kikoeru_has_work": task.task_metadata.get("kikoeru_has_work", False),
                    "kikoeru_has_existing_subtitles": task.task_metadata.get("kikoeru_has_existing_subtitles", False),
                    "kikoeru_matched_rjcode": task.task_metadata.get("kikoeru_matched_rjcode", ""),
                    "kikoeru_subtitle_file_count": task.task_metadata.get("kikoeru_subtitle_file_count", 0),
                    "kikoeru_subtitle_check_source": task.task_metadata.get("kikoeru_subtitle_check_source", ""),
                    "downloaded_count": task.task_metadata.get("downloaded_count", 0),
                    "existing_subtitle_count": task.task_metadata.get("existing_subtitle_count", 0),
                    "subtitle_dir": task.task_metadata.get("subtitle_dir", ""),
                    "written_files": task.task_metadata.get("written_files", []),
                    "skipped_files": task.task_metadata.get("skipped_files", []),
                    "write_errors": task.task_metadata.get("write_errors", []),
                    "failed_files": task.task_metadata.get("failed_files", []),
                    "match_result": task.task_metadata.get("match_result", {}),
                    "search_attempts": task.task_metadata.get("search_attempts", []),
                    "download_files": task.task_metadata.get("download_files", []),
                    "filtered_out_count": task.task_metadata.get("filtered_out_count", 0),
                    "content_deduped_count": task.task_metadata.get("content_deduped_count", 0),
                    "content_deduped_files": task.task_metadata.get("content_deduped_files", []),
                    "renamed_collision_files": task.task_metadata.get("renamed_collision_files", []),
                    "progress_log": task.task_metadata.get("progress_log", []),
                    "awaiting_manual_match": task.task_metadata.get("awaiting_manual_match", False),
                    "manual_match_completed": task.task_metadata.get("manual_match_completed", False),
                    "manual_match_applied_pairs": task.task_metadata.get("manual_match_applied_pairs", 0),
                    "manual_match_deleted_subtitles": task.task_metadata.get("manual_match_deleted_subtitles", 0),
                    "naming_strategy": task.task_metadata.get("naming_strategy", "audio"),
                    "linked_subtitle_cleanup_result": task.task_metadata.get("linked_subtitle_cleanup_result"),
                }
                for task in rj_tasks
            ]
        }
    except Exception as e:
        logger.error(f"获取 RJ 字幕抓取状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/subtitle-import/pending")
async def list_pending_linked_subtitle_imports():
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        items = await service.list_pending_imports()
        return {
            "success": True,
            "items": items,
        }
    except Exception as e:
        logger.error(f"获取字幕补配预检列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取预检列表失败: {str(e)}")


@app.post("/api/subtitle-import/pending/{record_id}/execute")
async def execute_pending_linked_subtitle_import(record_id: str, request: LinkedSubtitlePendingImportExecuteRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_pending_import(
            record_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            activity_result = result if isinstance(result, dict) else {"success": True}
            activity_preview = activity_result.get("preview") if isinstance(activity_result.get("preview"), dict) else {}
            activity_archive_path = str(
                activity_result.get("source_path")
                or activity_preview.get("source_path")
                or ""
            ).strip()
            log_from_subtitle_import_result(
                "pending_execute",
                activity_result,
                archive_path=activity_archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 字幕补配预检执行记录失败", exc_info=True)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"执行字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行补配失败: {str(e)}")


@app.post("/api/subtitle-import/pending/clear")
async def clear_pending_linked_subtitle_imports(request: LinkedSubtitlePendingClearRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.clear_pending_imports(
            record_ids=request.record_ids,
            clear_all=request.clear_all,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"清除字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除预检单失败: {str(e)}")


@app.post("/api/subtitle-import/archive/preview")
async def preview_linked_subtitle_archive_import(request: LinkedSubtitleArchivePreviewRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        preview = await service.preview_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/archive/import")
async def execute_linked_subtitle_archive_import(request: LinkedSubtitleArchiveImportRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "archive_import",
                result if isinstance(result, dict) else {},
                archive_path=request.archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 压缩包补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/folder/preview")
async def preview_linked_subtitle_folder_import(request: LinkedSubtitleFolderPreviewRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        preview = await service.preview_subtitle_folder_import(
            request.folder_path,
            preferred_library_id=request.preferred_library_id,
            source_rjcode_hint=request.source_rjcode_hint,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/folder/import")
async def execute_linked_subtitle_folder_import(request: LinkedSubtitleFolderImportRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_subtitle_folder_import(
            request.folder_path,
            preferred_library_id=request.preferred_library_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            source_rjcode_hint=request.source_rjcode_hint,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "folder_import",
                result if isinstance(result, dict) else {},
                folder_path=request.folder_path,
            )
        except Exception:
            logger.debug("[操作记录] 文件夹补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/task/{task_id}/cleanup")
async def cleanup_linked_subtitle_workbench(task_id: str):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.cleanup_workbench_subtitles(task_id)
        return {"success": True, "result": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"瀛楀箷琛ラ厤宸ヤ綔鍙版枃鏈竻鐞嗗け璐? {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"娓呯悊澶辫触: {str(e)}")


@app.get("/api/rj-subtitle/connectivity-test")
async def rj_subtitle_connectivity_test():
    """测试 RJ 字幕流程依赖的远端连通性。"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        service = get_asmr_download_service()
        return await service.test_connectivity()
    except Exception as e:
        logger.error(f"RJ 字幕连通性测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"连通性测试失败: {str(e)}")


class ASMRSyncScanRequest(BaseModel):
    """ASMR 同步扫描请求"""
    folder_path: str

class ASMRSyncStartRequest(BaseModel):
    """ASMR 同步开始请求"""
    items: List[dict]  # [{rjcode, subtitle_folder, work_title}]
    auto_classify: bool = True


class ASMRSyncEnhancedPlanRequest(BaseModel):
    """增强下载计划请求"""
    rjcodes: List[str]
    folder_path: Optional[str] = ""
    resource_types: List[str] = []
    audio_formats: List[str] = []
    subtitle_languages: List[str] = []
    include_existing: bool = False


class ASMRSyncEnhancedStartRequest(BaseModel):
    """增强下载启动请求"""
    items: List[dict]  # [{rjcode, work_title, selected_resources, folder_path, upload_options}]
    auto_classify: bool = False


class ASMRSyncEnhancedPriorityRequest(BaseModel):
    queue_priority: int


class CircleCompletionIndexRequest(BaseModel):
    circle_query: str
    force_refresh: bool = False
    include_dlsite: bool = True
    include_kikoeru: bool = True


class CircleCompletionIndexJobRequest(BaseModel):
    circle_query: str
    force_refresh: bool = True
    include_dlsite: bool = True
    include_kikoeru: bool = True


class CircleCompletionDownloadPreviewRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]


class CircleCompletionRefreshSelectedRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]


class CircleCompletionRefreshSelectedJobRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    canonical_rjcodes: List[str]


class CircleCompletionDownloadStartRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    items: List[dict]
    batch_options: Dict[str, Any] = {}


class ASMRRetryFailedResourcesRequest(BaseModel):
    relative_paths: List[str] = []


class ASMRReimportDownloadedRequest(BaseModel):
    target_library_id: str
    target_subdir: str = ""


class ASMRReimportLocalDownloadRequest(BaseModel):
    download_root: str
    rjcode: str
    circle_name: str = ""
    target_library_id: str
    target_subdir: str = ""

@app.post("/api/asmr-sync/scan")
async def asmr_sync_scan(request: ASMRSyncScanRequest):
    """扫描指定文件夹，返回发现的 RJ 号和字幕文件列表"""
    from ..core.subtitle_sync_service import get_subtitle_sync_service

    try:
        folder_path = request.folder_path

        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")

        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        subtitle_service = get_subtitle_sync_service()
        results = subtitle_service.scan_subtitle_folders(folder_path)

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(results),
            "items": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描字幕文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/asmr-sync/preview")
async def asmr_sync_preview(request: Request):
    """预览下载任务（获取文件列表、预估下载量、搜索最佳版本）"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        data = await request.json()
        rjcode = data.get("rjcode")

        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        asmr_service = get_asmr_download_service()

        # 获取所有关联版本
        linked_works = await asmr_service.get_linked_works_from_dlsite(rjcode)
        available_versions = []

        for work in linked_works:
            work_info = await asmr_service.fetch_work_info(work.workno)
            tracks = await asmr_service.fetch_track_list(work.workno) if work_info else None

            available_versions.append({
                "rjcode": work.workno,
                "lang": work.lang,
                "priority": work.priority,
                "available": work_info is not None and tracks is not None and len(tracks) > 0,
                "title": work_info.get('title', '') if work_info else '',
                "file_count": len(tracks) if tracks else 0
            })

            # 添加延迟避免请求过快
            await asyncio.sleep(0.3)

        # 找到最佳可用版本
        actual_rjcode, work_info = await asmr_service.find_best_available_work(rjcode)

        if not work_info:
            return {
                "success": False,
                "rjcode": rjcode,
                "error": "在 asmr.one 上未找到该作品的任何版本",
                "tried_versions": [
                    {"rjcode": v["rjcode"], "lang": v["lang"]}
                    for v in available_versions
                ]
            }

        # 获取文件列表
        tracks = await asmr_service.fetch_track_list(actual_rjcode)
        if tracks is None:
            return {
                "success": False,
                "rjcode": rjcode,
                "actual_rjcode": actual_rjcode,
                "error": "无法获取文件列表"
            }

        # 扁平化文件列表
        all_files = asmr_service._flatten_tracks(tracks)

        # 应用筛选规则
        config = get_config()
        filter_rules = config.filter.rules
        filtered_files = asmr_service.filter_files(all_files, filter_rules) if filter_rules else all_files

        # 计算总大小
        total_size = sum(f.get('size', 0) for f in filtered_files)

        # 获取实际版本的语言
        actual_version = next((v for v in available_versions if v["rjcode"] == actual_rjcode), {})

        return {
            "success": True,
            "rjcode": rjcode,
            "actual_rjcode": actual_rjcode,
            "title": work_info.get('title', '未知标题'),
            "lang": actual_version.get("lang", "JPN"),
            "total_files": len(all_files),
            "filtered_files": len(filtered_files),
            "total_size": total_size,
            "available_versions": available_versions,
            "files": [
                {
                    "title": f.get('title'),
                    "size": f.get('size', 0),
                    "type": f.get('type')
                }
                for f in filtered_files[:50]  # 只返回前50个用于预览
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"预览下载任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预览失败: {str(e)}")


@app.post("/api/asmr-sync/start")
async def asmr_sync_start(request: ASMRSyncStartRequest):
    """开始同步下载任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine

    try:
        items = request.items
        auto_classify = request.auto_classify

        if not items:
            raise HTTPException(status_code=400, detail="没有要下载的作品")

        engine = get_task_engine()
        created_tasks = []

        for item in items:
            rjcode = item.get("rjcode")
            subtitle_folder = item.get("subtitle_folder")
            work_title = item.get("work_title", "")

            if not rjcode or not subtitle_folder:
                continue

            # 创建任务
            task = Task(
                task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                source_path=subtitle_folder,
                auto_classify=auto_classify,
                metadata={
                    "rjcode": rjcode,
                    "subtitle_folder": subtitle_folder,
                    "work_title": work_title,
                    "download_mode": "legacy",
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "work_title": work_title
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个下载任务",
            "tasks": created_tasks
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"开始同步下载失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/asmr-sync/enhanced/plan")
async def asmr_sync_enhanced_plan(request: ASMRSyncEnhancedPlanRequest):
    """为输入的 RJ 号构建增强下载计划。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    if not request.rjcodes:
        raise HTTPException(status_code=400, detail="至少需要一个 RJ 号")

    service = get_asmr_resource_service()
    plans = []
    errors = []
    filters = {
        "resource_types": request.resource_types,
        "audio_formats": request.audio_formats,
        "subtitle_languages": request.subtitle_languages,
        "include_existing": request.include_existing,
    }

    for raw_rjcode in request.rjcodes:
        normalized_rjcode = service.normalize_rjcode(raw_rjcode)
        if not normalized_rjcode:
            continue
        try:
            plan = await service.build_download_plan(
                rjcode=normalized_rjcode,
                folder_path=str(request.folder_path or "").strip(),
                filters=filters,
                refresh=True,
            )
            plans.append(plan)
        except Exception as exc:
            logger.warning("构建增强下载计划失败: %s (%s)", normalized_rjcode, exc)
            errors.append({
                "rjcode": normalized_rjcode,
                "error": str(exc),
            })

    return {
        "success": len(plans) > 0,
        "plans": plans,
        "errors": errors,
        "requested_count": len(request.rjcodes),
        "planned_count": len(plans),
    }


@app.post("/api/asmr-sync/enhanced/start")
async def asmr_sync_enhanced_start(request: ASMRSyncEnhancedStartRequest):
    """启动增强下载任务，支持按文件清单下载。"""
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    config = get_config()

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可启动的增强下载任务")

    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    service = get_asmr_resource_service()
    created_tasks = []
    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode:
            continue
        if not session_id:
            raise HTTPException(status_code=400, detail=f"{rjcode} 缺少 session_id")
        if not selected_resources:
            raise HTTPException(status_code=400, detail=f"{rjcode} 没有选中任何资源")

        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=bool(request.auto_classify),
            metadata={
                "rjcode": rjcode,
                "work_title": str(item.get("work_title") or ""),
                "folder_path": str(item.get("folder_path") or ""),
                "download_mode": "enhanced",
                "session_id": session_id,
                "selected_resources": selected_resources,
                "selected_resource_count": len(selected_resources),
                "upload_options": dict(item.get("upload_options") or {}),
                "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
                "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
                "priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "verify_summary": {},
                "upload_summary": {},
                "retry_summary": {},
                "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
                "source_page": "asmr-sync",
                "source_action": "enhanced_download",
                "source_label": str(item.get("work_title") or rjcode),
            }
        )
        await engine.submit(task)
        service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })

    return {
        "success": len(created_tasks) > 0,
        "message": f"已创建 {len(created_tasks)} 个增强下载任务",
        "tasks": created_tasks,
    }


@app.get("/api/asmr-sync/enhanced/dashboard")
async def asmr_sync_enhanced_dashboard():
    """增强下载监控看板摘要。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "dashboard": get_asmr_resource_service().get_dashboard_summary(),
        }
    except Exception as exc:
        logger.error("获取增强下载看板失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取监控看板失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions")
async def asmr_sync_enhanced_sessions(limit: int = 50):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "sessions": get_asmr_resource_service().list_sessions(limit=limit),
        }
    except Exception as exc:
        logger.error("获取增强下载会话列表失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions/{session_id}")
async def asmr_sync_enhanced_session_detail(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": get_asmr_resource_service().get_session_detail(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("获取增强下载会话详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/priority")
async def asmr_sync_enhanced_session_priority(session_id: str, request: ASMRSyncEnhancedPriorityRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().update_session_priority(session_id, request.queue_priority),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("调整增强下载会话优先级失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"调整优先级失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/pause")
async def asmr_sync_enhanced_session_pause(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "pause"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("暂停增强下载会话失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"暂停会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/resume")
async def asmr_sync_enhanced_session_resume(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "resume"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("恢复增强下载会话失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-failed")
async def asmr_sync_enhanced_session_retry_failed(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话失败资源失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败资源失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-files")
async def asmr_sync_enhanced_session_retry_files(session_id: str, request: ASMRRetryFailedResourcesRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session_resources(session_id, request.relative_paths),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话指定失败文件失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试指定失败文件失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/reimport-downloaded")
async def asmr_sync_enhanced_session_reimport_downloaded(session_id: str, request: ASMRReimportDownloadedRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().reimport_downloaded_session(
                session_id,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("从本地已下载内容重新入库失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新入库失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/reimport-local-download")
async def asmr_sync_enhanced_reimport_local_download(request: ASMRReimportLocalDownloadRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "result": await get_asmr_resource_service().reimport_local_download_root(
                download_root=request.download_root,
                rjcode=request.rjcode,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
                circle_name=request.circle_name,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("从本地下载目录直接入库失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"从本地下载目录直接入库失败: {str(exc)}")


@app.post("/api/circle-completion/index")
async def circle_completion_index(request: CircleCompletionIndexRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().index_circle_catalog(
            request.circle_query,
            force_refresh=bool(request.force_refresh),
            include_dlsite=bool(request.include_dlsite),
            include_kikoeru=bool(request.include_kikoeru),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"建立社团索引失败: {str(exc)}")


@app.post("/api/circle-completion/index/start")
async def circle_completion_index_start(request: CircleCompletionIndexJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_query = str(request.circle_query or "").strip()
        if not circle_query:
            raise ValueError("社团名不能为空")

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_INDEX,
            source_path=circle_query,
            auto_classify=False,
            metadata={
                "circle_query": circle_query,
                "circle_name": circle_query,
                "force_refresh": bool(request.force_refresh),
                "include_dlsite": bool(request.include_dlsite),
                "include_kikoeru": bool(request.include_kikoeru),
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "index_start",
                "source_label": circle_query,
                "business_key": circle_query,
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": "index_start",
            "source_label": circle_query,
            "business_key": circle_query,
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": circle_query,
            "circle_id": "",
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {},
            "result": {},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动社团索引任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动社团索引任务失败: {str(exc)}")


@app.get("/api/circle-completion/index/jobs/{job_id}")
async def circle_completion_index_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("索引任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": str(metadata.get("circle_query") or task.source_path or "").strip(),
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": dict(metadata.get("index_meta") or {}),
            "result": dict(metadata.get("index_result") or {}),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团索引任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团索引任务失败: {str(exc)}")


@app.get("/api/circle-completion/circles")
async def circle_completion_circles(keyword: str = "", limit: int = 30):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().search_circles(keyword, limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/recent")
async def circle_completion_recent(limit: int = 20):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().list_recent_indexes(limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询最近社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询最近社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}")
async def circle_completion_detail(
    circle_id: str,
    only_missing: bool = False,
    only_downloadable: bool = False,
    include_dl_only: bool = True,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().build_circle_completion_view(
            circle_id,
            only_missing=bool(only_missing),
            only_downloadable=bool(only_downloadable),
            include_dl_only=bool(include_dl_only),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团补全详情失败: {str(exc)}")


@app.post("/api/circle-completion/download/preview")
async def circle_completion_download_preview(request: CircleCompletionDownloadPreviewRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().preview_batch_download(
            request.circle_id,
            request.canonical_rjcodes,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("预览社团批量下载失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"预览批量下载失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected")
async def circle_completion_refresh_selected(request: CircleCompletionRefreshSelectedRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().refresh_circle_works(
            request.circle_id,
            request.canonical_rjcodes,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("批量刷新社团作品状态失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量刷新社团作品状态失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected/start")
async def circle_completion_refresh_selected_start(request: CircleCompletionRefreshSelectedJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_id = str(request.circle_id or "").strip()
        circle_name = str(request.circle_name or "").strip()
        canonical_rjcodes = [str(code or "").strip() for code in list(request.canonical_rjcodes or []) if str(code or "").strip()]
        if not circle_id:
            raise ValueError("缺少社团标识")
        if not canonical_rjcodes:
            raise ValueError("没有选中要刷新的作品")

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED,
            source_path=circle_name or circle_id,
            auto_classify=False,
            metadata={
                "circle_id": circle_id,
                "circle_name": circle_name,
                "canonical_rjcodes": canonical_rjcodes,
                "selected_count": len(canonical_rjcodes),
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "refresh_selected",
                "source_label": circle_name or circle_id,
                "business_key": f"{circle_id}:refresh_selected",
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": "refresh_selected",
            "source_label": circle_name or circle_id,
            "business_key": f"{circle_id}:refresh_selected",
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": circle_id,
            "circle_name": circle_name,
            "selected_count": len(canonical_rjcodes),
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {},
            "result": {},
            "progress_log": [],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动批量刷新社团作品任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动批量刷新社团作品任务失败: {str(exc)}")


@app.get("/api/circle-completion/refresh-selected/jobs/{job_id}")
async def circle_completion_refresh_selected_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("刷新任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "circle_name": str(metadata.get("circle_name") or task.source_path or "").strip(),
            "selected_count": int(metadata.get("selected_count") or 0),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": dict(metadata.get("refresh_meta") or {}),
            "result": dict(metadata.get("refresh_result") or {}),
            "progress_log": list(metadata.get("progress_log") or []),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询批量刷新社团作品任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询批量刷新社团作品任务失败: {str(exc)}")


@app.post("/api/circle-completion/download/start")
async def circle_completion_download_start(request: CircleCompletionDownloadStartRequest):
    from ..core.activity_log_service import log_circle_completion_event
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可创建的下载项")

    config = get_config()
    batch_id = str(uuid.uuid4())
    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    session_service = get_asmr_resource_service()
    created_tasks = []
    child_rows = []
    batch_options = dict(request.batch_options or {})
    download_base_path = str(batch_options.get("download_base_path") or "").strip()
    target_library_id = str(batch_options.get("target_library_id") or "").strip()
    target_subdir = str(batch_options.get("target_subdir") or "").strip()
    naming_mode = str(batch_options.get("naming_mode") or "api").strip().lower() or "api"
    classify_mode = str(batch_options.get("classify_mode") or "circle").strip().lower() or "circle"

    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode or not session_id or not selected_resources:
            continue
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=False,
            metadata={
                "rjcode": rjcode,
                "work_title": str(item.get("work_title") or rjcode),
                "folder_path": str(item.get("folder_path") or ""),
                "download_mode": "enhanced",
                "session_id": session_id,
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
                "circle_name": request.circle_name,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "selected_resources": selected_resources,
                "selected_resource_count": len(selected_resources),
                "upload_options": dict(item.get("upload_options") or {}),
                "download_base_path": download_base_path,
                "postprocess_options": {
                    "enabled": True,
                    "target_library_id": target_library_id,
                    "target_subdir": target_subdir,
                    "naming_mode": naming_mode,
                    "classify_mode": classify_mode,
                    "circle_name": str((item.get("postprocess_options") or {}).get("circle_name") or request.circle_name or ""),
                },
                "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
                "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
                "priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "batch_download",
                "source_label": str(item.get("work_title") or rjcode),
                "business_key": str(item.get("canonical_rjcode") or rjcode),
            },
            rjcode=rjcode,
        )
        await engine.submit(task)
        session_service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })
        child_rows.append({
            "id": task.id,
            "category": "circle_completion",
            "category_label": "社团补全",
            "action": "download_item_queued",
            "status": "success",
            "summary": f"{rjcode} 已加入下载队列，共 {len(selected_resources)} 个资源",
            "detail": {
                "session_id": session_id,
                "parent_session_id": batch_id,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "downloadable": True,
                "selected_resource_count": len(selected_resources),
                "download_base_path": download_base_path or None,
                "target_library_id": target_library_id or None,
                "target_subdir": target_subdir or None,
                "naming_mode": naming_mode,
                "classify_mode": classify_mode,
            },
            "task_id": task.id,
            "rjcode": rjcode,
            "created_at": datetime.now().isoformat(),
        })

    if not created_tasks:
        raise HTTPException(status_code=400, detail="没有有效下载项")

    log_circle_completion_event(
        "download_batch_start",
        summary=f"{request.circle_name or request.circle_id} 已创建 {len(created_tasks)} 个下载子任务",
        circle_id=request.circle_id,
        circle_name=request.circle_name or request.circle_id,
        batch_id=batch_id,
        detail={
            "items": created_tasks,
            "child_rows": child_rows,
            "download_base_path": download_base_path or None,
            "target_library_id": target_library_id or None,
            "target_subdir": target_subdir or None,
            "naming_mode": naming_mode,
            "classify_mode": classify_mode,
        },
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "circle_id": request.circle_id,
        "tasks": created_tasks,
        "message": f"已创建 {len(created_tasks)} 个社团补全下载任务",
    }


@app.get("/api/asmr-sync/status")
async def asmr_sync_status():
    """获取当前同步任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()

        # 过滤出 ASMR 同步任务
        asmr_tasks = [t for t in all_tasks if t.type == TaskType.ASMR_SYNC_DOWNLOAD]
        session_ids = {
            str(t.task_metadata.get("session_id") or "").strip()
            for t in asmr_tasks
            if str(t.task_metadata.get("session_id") or "").strip()
        }
        session_map = {}
        if session_ids:
            db = SessionLocal()
            try:
                rows = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id.in_(list(session_ids))).all()
                for row in rows:
                    session = row.to_dict()
                    statistics = dict(session.get("statistics") or {})
                    local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
                    local_count = int(session.get("local_downloaded_count") or 0)
                    local_ready = bool(session.get("local_download_ready"))
                    if local_root and os.path.isdir(local_root):
                        if local_count <= 0:
                            local_count = sum(
                                1
                                for item in (session.get("selected_resources") or [])
                                if os.path.exists(
                                    os.path.join(
                                        local_root,
                                        str(item.get("relative_path") or item.get("file_name") or "").strip().replace("/", os.sep),
                                    )
                                )
                            )
                        local_ready = local_ready or local_count > 0
                    else:
                        local_root = ""
                        local_count = 0
                        local_ready = False
                    session_map[str(row.id)] = {
                        "local_download_ready": local_ready,
                        "local_download_root": local_root,
                        "local_downloaded_count": local_count,
                    }
            finally:
                db.close()

        return {
            "total_tasks": len(asmr_tasks),
            "processing": len([t for t in asmr_tasks if t.status.value == "processing"]),
            "pending": len([t for t in asmr_tasks if t.status.value == "pending"]),
            "completed": len([t for t in asmr_tasks if t.status.value == "completed"]),
            "failed": len([t for t in asmr_tasks if t.status.value == "failed"]),
            "waiting_retry": len([t for t in asmr_tasks if t.status.value == "waiting_retry"]),
            "tasks": [
                {
                    "session_state": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}),
                    "id": t.id,
                    "rjcode": t.task_metadata.get("rjcode", ""),
                    "actual_rjcode": t.task_metadata.get("actual_rjcode", ""),
                    "work_title": t.task_metadata.get("work_title", ""),
                    "status": t.status.value,
                    "display_status": "partial_failed" if (t.status.value == "completed" and (t.task_metadata.get("failed_files") or t.task_metadata.get("verification_failures") or t.task_metadata.get("failure_reason"))) else t.status.value,
                    "progress": t.progress,
                    "current_step": t.current_step,
                    "error_message": t.error_message,
                    "created_at": t.created_at.isoformat() if getattr(t, "created_at", None) else None,
                    "started_at": t.started_at.isoformat() if getattr(t, "started_at", None) else None,
                    "completed_at": t.completed_at.isoformat() if getattr(t, "completed_at", None) else None,
                    "output_path": getattr(t, "output_path", ""),
                    "download_files": t.task_metadata.get("download_files", []),
                    "upload_files": t.task_metadata.get("upload_files", []),
                    "upload_runtime": t.task_metadata.get("upload_runtime", {}),
                    "failed_files": t.task_metadata.get("failed_files", []),
                    "uploaded_files": t.task_metadata.get("uploaded_files", []),
                    "verification_failures": t.task_metadata.get("verification_failures", []),
                    "progress_log": t.task_metadata.get("progress_log", []),
                    "performance_metrics": t.task_metadata.get("performance_metrics", {}),
                    "sync_result": t.task_metadata.get("sync_result", {}),
                    "subtitle_moved_to": t.task_metadata.get("subtitle_moved_to", ""),
                    "download_mode": t.task_metadata.get("download_mode", "legacy"),
                    "session_id": t.task_metadata.get("session_id", ""),
                    "queue_priority": t.task_metadata.get("queue_priority", t.task_metadata.get("priority", 100)),
                    "task_metadata": {
                        "retry_reason": t.task_metadata.get("retry_reason", ""),
                        "retry_count": t.task_metadata.get("retry_count", 0),
                        "retry_after": t.task_metadata.get("retry_after", ""),
                        "selected_resource_count": t.task_metadata.get("selected_resource_count", 0),
                        "verify_summary": t.task_metadata.get("verify_summary", {}),
                        "upload_summary": t.task_metadata.get("upload_summary", {}),
                        "retry_summary": t.task_metadata.get("retry_summary", {}),
                        "download_root": (
                            session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_root")
                            or t.task_metadata.get("download_root", "")
                        ),
                        "download_base_path": t.task_metadata.get("download_base_path", ""),
                        "final_output_path": t.task_metadata.get("final_output_path", ""),
                        "target_path": t.task_metadata.get("target_path", ""),
                        "failure_reason": t.task_metadata.get("failure_reason", ""),
                        "local_download_ready": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_ready", False),
                        "local_download_root": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_root", ""),
                        "local_downloaded_count": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_downloaded_count", 0),
                    }
                }
                for t in asmr_tasks[:20]  # 只返回最近20个
            ]
        }

    except Exception as e:
        logger.error(f"获取同步状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/asmr-sync/waiting-retry")
async def asmr_sync_waiting_retry():
    """获取等待重试的任务列表及下次重试时间"""
    from ..core.task_engine import get_task_engine, TaskType
    from ..config.settings import get_config
    from datetime import datetime

    try:
        engine = get_task_engine()
        config = get_config()

        # 获取 cron 表达式
        cron_expr = "0 */1 * * *"  # 默认值
        if hasattr(config, 'asmr_sync') and config.asmr_sync:
            if hasattr(config.asmr_sync, 'retry_cron'):
                cron_expr = config.asmr_sync.retry_cron

        # 计算下次重试时间
        try:
            from croniter import croniter
            now = datetime.now()
            cron = croniter(cron_expr, now)
            next_retry_time = cron.get_next(datetime)
        except Exception as cron_err:
            logger.warning(f"解析cron表达式失败: {cron_err}, 使用默认值")
            next_retry_time = datetime.now()

        # 从数据库获取等待重试任务
        try:
            waiting_tasks = engine.get_waiting_retry_tasks_from_db()
        except Exception as db_err:
            logger.error(f"获取等待重试任务失败: {db_err}", exc_info=True)
            waiting_tasks = []

        return {
            "cron_expression": cron_expr,
            "next_retry_time": next_retry_time.isoformat(),
            "tasks": waiting_tasks
        }

    except Exception as e:
        logger.error(f"获取等待重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/pause")
async def asmr_sync_pause_task(task_id: str):
    """暂停任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.pause()
        return {"success": True, "message": "任务已暂停"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"暂停失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/resume")
async def asmr_sync_resume_task(task_id: str):
    """恢复任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.resume()
        return {"success": True, "message": "任务已恢复"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry")
async def asmr_sync_retry_failed(task_id: str):
    """重试失败的文件"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        failed_files = task.task_metadata.get('failed_files', [])
        if not failed_files:
            return {"success": True, "message": "没有失败的文件需要重试"}

        # 清除失败文件列表，重新触发下载
        task.task_metadata['retry_failed'] = True
        task.resume()

        return {"success": True, "message": f"正在重试 {len(failed_files)} 个失败文件"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试失败文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry-waiting")
async def asmr_sync_retry_waiting_task(task_id: str):
    """手动重试等待中的任务（未找到版本的任务）"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        if engine.retry_task(task_id):
            return {"success": True, "message": "任务已加入重试队列"}
        else:
            raise HTTPException(status_code=400, detail="任务不在等待重试状态")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.delete("/api/asmr-sync/task/{task_id}/waiting-retry")
async def asmr_sync_delete_waiting_retry_task(task_id: str):
    """删除等待重试的任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()

        # 从内存中删除任务
        if task_id in engine.tasks:
            task = engine.tasks[task_id]
            rjcode = task.rjcode
            del engine.tasks[task_id]
            logger.info(f"[等待重试] 从内存中删除任务: {task_id}")

            # 从数据库中删除
            engine._remove_waiting_retry_task(rjcode)

            return {"success": True, "message": "任务已删除"}
        else:
            # 任务不在内存中，尝试从数据库删除
            engine._remove_waiting_retry_task_by_id(task_id)
            return {"success": True, "message": "任务已从数据库删除"}

    except Exception as e:
        logger.error(f"删除任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# 静态文件服务（前端）
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    # 返回项目根目录 (backend/app/api -> ../../../)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_base_path = get_base_path()

static_files_path = os.environ.get('STATIC_FILES_PATH', os.path.join(_base_path, "static"))
frontend_path = os.environ.get('FRONTEND_PATH', os.path.join(_base_path, "frontend", "dist"))

possible_paths = [
    frontend_path,
    static_files_path,
    os.path.join(_base_path, "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "../frontend/dist"),
    "/app/static",
]

frontend_build_path = None
logger.info(f"检查静态文件路径，当前工作目录: {os.getcwd()}")
logger.info(f"基础路径: {_base_path}")
for path in possible_paths:
    index_file = os.path.join(path, "index.html")
    path_exists = os.path.exists(path)
    index_exists = os.path.exists(index_file)
    logger.info(f"检查路径: {path} - 目录存在: {path_exists}, index.html存在: {index_exists}")
    if path_exists and index_exists:
        frontend_build_path = path
        logger.info(f"找到前端构建文件: {path}")
        break

# 注册静态文件服务（放在子路径，避免覆盖 API）
if frontend_build_path:
    # 提供静态资源文件（JS、CSS、图片等）
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_build_path, "assets")), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        favicon_path = os.path.join(frontend_build_path, "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path, media_type="image/x-icon")
        raise HTTPException(status_code=404, detail="Favicon not found")
    
    # 捕获所有非 API 路由，返回 index.html（SPA 支持）
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API 路由不应该被拦截
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # 对于前端路由，返回 index.html
        index_path = os.path.join(frontend_build_path, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")
