"""
用户操作审计持久化（SQLite activity_logs）。
业务分类：字幕爬取、字幕配对、字幕补配、解压、自动入库等。
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# 持久化分类（与前端筛选、图表一致）
CATEGORY_SUBTITLE_CRAWL = "subtitle_crawl"
CATEGORY_SUBTITLE_PAIR = "subtitle_pair"
CATEGORY_SUBTITLE_IMPORT = "subtitle_import"
CATEGORY_EXTRACT = "extract"
CATEGORY_AUTO_IMPORT = "auto_import"
CATEGORY_PROCESS_EXISTING = "process_existing"
CATEGORY_PIPELINE_FILTER = "pipeline_filter"
CATEGORY_PIPELINE_METADATA = "pipeline_metadata"
CATEGORY_PIPELINE_RENAME = "pipeline_rename"
CATEGORY_ASMR_SYNC = "asmr_sync"

CATEGORY_LABELS = {
    CATEGORY_SUBTITLE_CRAWL: "字幕爬取",
    CATEGORY_SUBTITLE_PAIR: "字幕配对",
    CATEGORY_SUBTITLE_IMPORT: "字幕补配",
    CATEGORY_EXTRACT: "解压",
    CATEGORY_AUTO_IMPORT: "自动入库",
    CATEGORY_PROCESS_EXISTING: "已有目录处理",
    CATEGORY_PIPELINE_FILTER: "筛选",
    CATEGORY_PIPELINE_METADATA: "元数据",
    CATEGORY_PIPELINE_RENAME: "重命名",
    CATEGORY_ASMR_SYNC: "ASMR 同步",
}


def _format_bytes(size: Any) -> str:
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


def _format_duration_ms(duration_ms: Any) -> str:
    try:
        value = max(0, int(duration_ms or 0))
    except Exception:
        value = 0
    if value < 1000:
        return f"{value} ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes = int(seconds // 60)
    remain = int(seconds % 60)
    return f"{minutes} 分 {remain} 秒"


def _build_filter_delete_items(items: Any, limit: int = 200) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        out.append({
            "path": item.get("path"),
            "relative_path": item.get("relative_path"),
            "name": item.get("name"),
            "type": item.get("type"),
            "size": item.get("size"),
            "matched_rules": item.get("matched_rules"),
            "covered_by": item.get("covered_by"),
            "delete_path": item.get("delete_path"),
            "status": item.get("status"),
            "error": item.get("error"),
        })
    return out


def _safe_path_size(path: Any) -> int:
    try:
        target = str(path or "").strip()
        if not target or not os.path.exists(target):
            return 0
        if os.path.isfile(target):
            return int(os.path.getsize(target))
        total = 0
        for root, _, files in os.walk(target):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    total += int(os.path.getsize(file_path))
                except Exception:
                    continue
        return total
    except Exception:
        return 0


def _sanitize_for_db_json(value: Any, depth: int = 0) -> Any:
    """将 detail 转为可安全写入 SQLite JSON 列的结构（避免 datetime 等导致 commit 失败）。"""
    if depth > 8:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 8000 else value[:8000] + "…"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 80:
                break
            try:
                sk = str(k)[:120]
                sv = _sanitize_for_db_json(v, depth + 1)
                if sv is not None:
                    out[sk] = sv
            except Exception:
                continue
        return out
    if isinstance(value, (list, tuple, set)):
        return [
            x
            for x in (_sanitize_for_db_json(v, depth + 1) for v in list(value)[:200])
            if x is not None
        ]
    try:
        return str(value)[:2000]
    except Exception:
        return None


def write_activity_log(
    category: str,
    action: str,
    status: str,
    summary: str,
    detail: Optional[Dict[str, Any]] = None,
    rjcode: Optional[str] = None,
    task_id: Optional[str] = None,
    source_path: Optional[str] = None,
) -> None:
    from ..models.database import ActivityLog, SessionLocal

    db = SessionLocal()
    try:
        rc = (rjcode or "").strip().upper() or None
        sp = source_path[:4000] if source_path else None
        detail_clean = _sanitize_for_db_json(detail) if detail else {}
        if not isinstance(detail_clean, dict):
            detail_clean = {"_raw": detail_clean}
        row = ActivityLog(
            id=str(uuid.uuid4()),
            category=category[:40],
            action=(action or "")[:80],
            status=(status or "")[:20],
            summary=(summary or "")[:4000],
            detail=detail_clean,
            rjcode=rc[:32] if rc else None,
            task_id=(task_id or "")[:36] or None,
            source_path=sp,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("[操作记录] 写入失败", exc_info=True)
    finally:
        db.close()


def log_task_lifecycle_event(task) -> None:
    """任务线程结束时记录一条（成功 / 失败 / 取消 / 等待）。"""
    from .task_engine import TaskStatus, TaskType

    try:
        st = task.status
    except Exception:
        return

    if st in (TaskStatus.PENDING, TaskStatus.PAUSED):
        return

    tt = getattr(task, "type", None)
    if isinstance(tt, str):
        try:
            tt = TaskType(tt)
        except ValueError:
            tt = None
    elif tt is not None and not isinstance(tt, TaskType):
        tt = None

    type_map = {
        TaskType.RJ_SUBTITLE_FETCH: CATEGORY_SUBTITLE_CRAWL,
        TaskType.EXTRACT: CATEGORY_EXTRACT,
        TaskType.AUTO_PROCESS: CATEGORY_AUTO_IMPORT,
        TaskType.PROCESS_EXISTING_FOLDER: CATEGORY_PROCESS_EXISTING,
        TaskType.FILTER: CATEGORY_PIPELINE_FILTER,
        TaskType.METADATA: CATEGORY_PIPELINE_METADATA,
        TaskType.RENAME: CATEGORY_PIPELINE_RENAME,
        TaskType.ASMR_SYNC_DOWNLOAD: CATEGORY_ASMR_SYNC,
    }
    category = type_map.get(tt, CATEGORY_AUTO_IMPORT) if tt else CATEGORY_AUTO_IMPORT

    if st == TaskStatus.PROCESSING:
        write_activity_log(
            category=category,
            action="task_finished_incomplete",
            status="incomplete",
            summary=(task.current_step or "任务结束时仍为处理中").strip()[:4000],
            detail=_sanitize_for_db_json({"task_type": getattr(tt, "value", str(getattr(task, "type", "")))}),
            rjcode=(getattr(task, "rjcode", None) or (task.task_metadata or {}).get("rjcode") or "").strip().upper() or None,
            task_id=task.id,
            source_path=task.source_path,
        )
        return

    status = "success"
    if task.is_cancelled():
        status = "cancelled"
    elif st == TaskStatus.FAILED:
        status = "failed"
    elif st in (TaskStatus.WAITING_RETRY, TaskStatus.WAITING_MANUAL):
        status = "waiting"
    elif st == TaskStatus.COMPLETED:
        status = "success"

    rj = (getattr(task, "rjcode", None) or (task.task_metadata or {}).get("rjcode") or "").strip().upper()
    action = "task_finished"

    summary = (task.current_step or "").strip()
    if st == TaskStatus.FAILED and task.error_message:
        summary = (task.error_message or summary)[:2000]
    if not summary:
        summary = f"{getattr(tt, 'value', str(getattr(task, 'type', '')))} {status}"

    meta = task.task_metadata or {}
    if tt == TaskType.RJ_SUBTITLE_FETCH:
        if meta.get("awaiting_manual_match") and st == TaskStatus.COMPLETED:
            summary = "字幕已抓取，待筛选与配对"
        elif meta.get("kikoeru_has_existing_subtitles") and "跳过" in (summary or ""):
            summary = summary or "检测到已有字幕，跳过抓取"
        detail = {
            "downloaded_count": meta.get("downloaded_count"),
            "written_files_count": len(meta.get("written_files") or []) if isinstance(meta.get("written_files"), list) else meta.get("written_files"),
            "folder_path": meta.get("folder_path"),
            "awaiting_manual_match": bool(meta.get("awaiting_manual_match")),
        }
    elif tt == TaskType.EXTRACT:
        detail = {
            "output_path": task.output_path,
            "source_basename": os.path.basename(str(task.source_path or "")),
            "output_size_bytes": _safe_path_size(task.output_path) if st == TaskStatus.COMPLETED else 0,
        }
    else:
        detail = {
            "output_path": task.output_path,
            "source_basename": os.path.basename(str(task.source_path or "")),
        }

    write_activity_log(
        category=category,
        action=action,
        status=status,
        summary=summary,
        detail={k: v for k, v in detail.items() if v is not None},
        rjcode=rj or None,
        task_id=task.id,
        source_path=task.source_path,
    )


def log_subtitle_pair_complete(
    task_id: str,
    rjcode: str,
    applied_pairs: int,
    deleted_subtitles: int,
    summary: str,
    linked_detail: Optional[Dict[str, Any]] = None,
) -> None:
    detail = {
        "applied_pairs": applied_pairs,
        "deleted_subtitles": deleted_subtitles,
    }
    if isinstance(linked_detail, dict):
        detail.update(linked_detail)
    write_activity_log(
        category=CATEGORY_SUBTITLE_PAIR,
        action="manual_complete",
        status="success",
        summary=summary,
        detail=detail,
        rjcode=rjcode,
        task_id=task_id,
    )


def log_subtitle_import_action(
    action: str,
    success: bool,
    summary: str,
    detail: Optional[Dict[str, Any]] = None,
    rjcode: Optional[str] = None,
    task_id: Optional[str] = None,
    source_path: Optional[str] = None,
) -> None:
    write_activity_log(
        category=CATEGORY_SUBTITLE_IMPORT,
        action=action,
        status="success" if success else "failed",
        summary=summary,
        detail=detail,
        rjcode=rjcode,
        task_id=task_id,
        source_path=source_path,
    )


def log_from_subtitle_import_result(
    action: str,
    result: Dict[str, Any],
    archive_path: str = "",
    folder_path: str = "",
) -> None:
    """从字幕补配 API 返回结构中提取摘要并记一条。"""
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    rj = str(
        result.get("target_rjcode")
        or preview.get("target_rjcode")
        or preview.get("source_rjcode")
        or result.get("source_rjcode")
        or ""
    ).strip().upper()
    err = result.get("error") or result.get("detail")
    success = bool(result.get("success", True)) and not err
    msg = str(result.get("message") or ("字幕补配完成" if success else "字幕补配失败"))
    if err:
        msg = f"{msg}: {err}"[:1900]
    path = (archive_path or folder_path or str(result.get("source_path") or "") or "").strip()
    detail = {k: result.get(k) for k in ("task_id", "final_file_count", "record_id") if result.get(k) is not None}
    log_subtitle_import_action(
        action=action,
        success=success,
        summary=msg,
        detail=detail or None,
        rjcode=rj or None,
        task_id=str(result.get("task_id") or "") or None,
        source_path=path or None,
    )


def log_filter_delete_preview_result(payload: Dict[str, Any]) -> None:
    status = str(payload.get("status") or "success")
    selected_count = int(payload.get("selected_count") or 0)
    selected_size = int(payload.get("selected_size") or 0)
    duration_ms = int(payload.get("duration_ms") or 0)
    rule_count = int(payload.get("rule_count") or 0)
    scope_label = str(payload.get("scope_label") or payload.get("folder_name") or "删除过滤")
    folder_path = str(payload.get("folder_path") or "").strip() or None
    warning = str(payload.get("warning") or "").strip()
    error = str(payload.get("error") or "").strip()

    if status == "success":
        summary = f"{scope_label} 删除预审完成，命中 {selected_count} 项，预计删除 {_format_bytes(selected_size)}，耗时 {_format_duration_ms(duration_ms)}"
    elif status == "cancelled":
        summary = f"{scope_label} 删除预审已取消，已扫描 {int(payload.get('scanned_entries') or 0)} 项，耗时 {_format_duration_ms(duration_ms)}"
    else:
        summary = f"{scope_label} 删除预审失败，已扫描 {int(payload.get('scanned_entries') or 0)} 项，耗时 {_format_duration_ms(duration_ms)}"
        if error:
            summary = f"{summary}：{error}"[:4000]

    detail = {
        "mode": "filter_delete_preview",
        "scope_label": scope_label,
        "folder_name": payload.get("folder_name"),
        "folder_path": folder_path,
        "duration_ms": duration_ms,
        "rule_count": rule_count,
        "selected_count": selected_count,
        "selected_size": selected_size,
        "selected_size_exact": bool(payload.get("selected_size_exact", True)),
        "scanned_entries": int(payload.get("scanned_entries") or 0),
        "discovered_entries": int(payload.get("discovered_entries") or 0),
        "pending_directories": int(payload.get("pending_directories") or 0),
        "preview_target_total": int(payload.get("preview_target_total") or 0),
        "truncated": bool(payload.get("truncated")),
        "truncated_reason": payload.get("truncated_reason"),
        "warning": warning or None,
        "error": error or None,
        "items": _build_filter_delete_items(payload.get("items")),
        "item_total_count": len(payload.get("items") or []) if isinstance(payload.get("items"), list) else 0,
    }
    write_activity_log(
        category=CATEGORY_PIPELINE_FILTER,
        action="filter_delete_preview",
        status="success" if status == "success" else ("cancelled" if status == "cancelled" else "failed"),
        summary=summary,
        detail=detail,
        source_path=folder_path,
    )


def log_filter_delete_apply_result(payload: Dict[str, Any]) -> None:
    status = str(payload.get("status") or "success")
    success_count = int(payload.get("success_count") or 0)
    failed_count = int(payload.get("failed_count") or 0)
    duration_ms = int(payload.get("duration_ms") or 0)
    deleted_bytes = int(payload.get("deleted_bytes") or 0)
    scope_label = str(payload.get("scope_label") or payload.get("folder_name") or "删除过滤")
    folder_path = str(payload.get("folder_path") or "").strip() or None
    error = str(payload.get("error") or "").strip()

    if status == "success":
        summary = f"{scope_label} 删除完成，成功 {success_count} 项，失败 {failed_count} 项，删除 {_format_bytes(deleted_bytes)}，耗时 {_format_duration_ms(duration_ms)}"
    elif status == "partial_success":
        summary = f"{scope_label} 删除部分成功，成功 {success_count} 项，失败 {failed_count} 项，删除 {_format_bytes(deleted_bytes)}，耗时 {_format_duration_ms(duration_ms)}"
    elif status == "cancelled":
        summary = f"{scope_label} 删除已停止，成功 {success_count} 项，失败 {failed_count} 项，删除 {_format_bytes(deleted_bytes)}，耗时 {_format_duration_ms(duration_ms)}"
    else:
        summary = f"{scope_label} 删除失败，成功 {success_count} 项，失败 {failed_count} 项，耗时 {_format_duration_ms(duration_ms)}"
        if error:
            summary = f"{summary}：{error}"[:4000]

    detail = {
        "mode": "filter_delete_apply",
        "scope_label": scope_label,
        "folder_name": payload.get("folder_name"),
        "folder_path": folder_path,
        "duration_ms": duration_ms,
        "selected_count": int(payload.get("selected_count") or 0),
        "success_count": success_count,
        "failed_count": failed_count,
        "deleted_bytes": deleted_bytes,
        "deleted_folder_count": int(payload.get("deleted_folder_count") or 0),
        "succeeded_items": _build_filter_delete_items(payload.get("succeeded_items")),
        "failed_items": _build_filter_delete_items(payload.get("failed_items")),
        "attempted_items": _build_filter_delete_items(payload.get("attempted_items")),
        "error": error or None,
    }
    write_activity_log(
        category=CATEGORY_PIPELINE_FILTER,
        action="filter_delete_apply",
        status=(
            "success"
            if status == "success"
            else ("partial_success" if status == "partial_success" else ("cancelled" if status == "cancelled" else "failed"))
        ),
        summary=summary,
        detail=detail,
        source_path=folder_path,
    )
