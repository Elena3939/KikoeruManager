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
    CATEGORY_AUTO_IMPORT: "解压入库",
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


def _resolve_archive_snapshot(task: Any) -> tuple[int, Optional[str]]:
    source_path = str(getattr(task, "source_path", "") or "").strip()
    direct_size = _safe_path_size(source_path)
    if direct_size > 0:
        return direct_size, source_path

    task_id = str(getattr(task, "id", "") or "").strip()
    if not task_id:
        return 0, source_path or None

    try:
        from ..models.database import ProcessedArchive, SessionLocal

        db = SessionLocal()
        try:
            record = (
                db.query(ProcessedArchive)
                .filter(ProcessedArchive.task_id == task_id)
                .order_by(ProcessedArchive.processed_at.desc())
                .first()
            )
            if record is None and source_path:
                record = (
                    db.query(ProcessedArchive)
                    .filter(
                        (ProcessedArchive.original_path == source_path)
                        | (ProcessedArchive.current_path == source_path)
                    )
                    .order_by(ProcessedArchive.processed_at.desc())
                    .first()
                )
            if record is None:
                return 0, source_path or None
            record_size = int(record.file_size or 0)
            record_path = str(record.current_path or record.original_path or source_path or "").strip() or None
            if record_size > 0:
                return record_size, record_path
            return _safe_path_size(record_path), record_path
        finally:
            db.close()
    except Exception:
        logger.debug("[操作记录] 回查归档压缩包大小失败", exc_info=True)
        return 0, source_path or None


def _duration_ms_for_task(task: Any) -> int:
    try:
        started_at = getattr(task, "started_at", None) or getattr(task, "created_at", None)
        completed_at = getattr(task, "completed_at", None) or datetime.now()
        if not started_at or not completed_at:
            return 0
        return max(0, int((completed_at - started_at).total_seconds() * 1000))
    except Exception:
        return 0


def _looks_like_archive_path(path: Any) -> bool:
    try:
        name = str(path or "").strip().lower()
    except Exception:
        return False
    if not name:
        return False
    archive_exts = (
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
        ".001", ".part1", ".part01"
    )
    return name.endswith(archive_exts) or ".part" in name


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
            "batch_id": str(meta.get("batch_id") or "").strip() or None,
        }
    elif tt == TaskType.EXTRACT:
        archive_size_bytes, archive_path = _resolve_archive_snapshot(task)
        output_size_bytes = _safe_path_size(task.output_path) if st == TaskStatus.COMPLETED else 0
        duration_ms = _duration_ms_for_task(task)
        if st == TaskStatus.COMPLETED:
            summary = (
                f"{summary or '压缩包解压完成'}，"
                f"压缩包 {_format_bytes(archive_size_bytes)}，"
                f"解压产物 {_format_bytes(output_size_bytes)}，"
                f"耗时 {_format_duration_ms(duration_ms)}"
            )[:4000]
        detail = {
            "output_path": task.output_path,
            "source_basename": os.path.basename(str(archive_path or task.source_path or "")),
            "archive_path": archive_path,
            "archive_size_bytes": archive_size_bytes,
            "output_size_bytes": output_size_bytes,
            "duration_ms": duration_ms,
        }
    else:
        archive_input = _looks_like_archive_path(task.source_path)
        linked_preview = meta.get("linked_subtitle_preview") if isinstance(meta.get("linked_subtitle_preview"), dict) else {}
        preview_extract_path = str(
            linked_preview.get("source_subtitle_dir")
            or linked_preview.get("staged_subtitle_dir")
            or ""
        ).strip()
        extract_output_bytes = 0
        if st == TaskStatus.COMPLETED and tt == TaskType.AUTO_PROCESS and archive_input:
            extract_output_bytes = _safe_path_size(task.output_path) if task.output_path else 0
            if extract_output_bytes <= 0 and preview_extract_path:
                extract_output_bytes = _safe_path_size(preview_extract_path)
        archive_size_bytes = 0
        archive_path = None
        if archive_input:
            archive_size_bytes, archive_path = _resolve_archive_snapshot(task)
        duration_ms = _duration_ms_for_task(task)
        source_mode = str(meta.get("source_mode") or "").strip()
        if st == TaskStatus.COMPLETED and tt == TaskType.AUTO_PROCESS and archive_input:
            extract_label = "预检解包" if source_mode == "linked_translation_archive_pending" and not task.output_path else "解压产物"
            summary = (
                f"{summary or '解压入库完成'}，"
                f"压缩包 {_format_bytes(archive_size_bytes)}，"
                f"{extract_label} {_format_bytes(extract_output_bytes)}，"
                f"耗时 {_format_duration_ms(duration_ms)}"
            )[:4000]
        detail = {
            "output_path": task.output_path,
            "source_basename": os.path.basename(str(archive_path or task.source_path or "")),
            "archive_path": archive_path,
            "archive_input": archive_input,
            "extract_performed": bool(tt == TaskType.AUTO_PROCESS and archive_input),
            "extract_output_bytes": extract_output_bytes,
            "archive_size_bytes": archive_size_bytes,
            "duration_ms": duration_ms,
            "source_mode": source_mode or None,
            "linked_source_rjcode": str(linked_preview.get("source_rjcode") or "").strip().upper() or None,
            "linked_target_rjcode": str(linked_preview.get("target_rjcode") or "").strip().upper() or None,
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


def log_api_rename_action(
    *,
    action: str,
    success: bool,
    source_path: str,
    new_path: str = "",
    old_name: str = "",
    new_name: str = "",
    rjcode: Optional[str] = None,
    batch_id: Optional[str] = None,
    library_id: Optional[str] = None,
    error: str = "",
    status: Optional[str] = None,
    extra_detail: Optional[Dict[str, Any]] = None,
) -> None:
    normalized_source_path = str(source_path or "").strip()
    normalized_new_path = str(new_path or "").strip()
    normalized_old_name = str(old_name or "").strip() or (os.path.basename(normalized_source_path) if normalized_source_path else "")
    normalized_new_name = str(new_name or "").strip() or (os.path.basename(normalized_new_path) if normalized_new_path else "")
    normalized_error = str(error or "").strip()
    normalized_status = str(status or ("success" if success else "failed")).strip() or ("success" if success else "failed")
    summary_target = normalized_new_name or normalized_old_name or "未命名"
    summary = f"{normalized_old_name or '原名称未知'} -> {summary_target}"
    if normalized_status == "failed" and normalized_error:
        summary = f"{summary}：{normalized_error}"[:4000]
    else:
        summary = summary[:4000]
    detail = {
        "mode": "api_rename",
        "rename_key": normalized_source_path or normalized_new_path or None,
        "old_name": normalized_old_name or None,
        "new_name": normalized_new_name or None,
        "old_path": normalized_source_path or None,
        "new_path": normalized_new_path or None,
        "batch_id": str(batch_id or "").strip() or None,
        "library_id": str(library_id or "").strip() or None,
        "error": normalized_error or None,
    }
    if isinstance(extra_detail, dict):
        detail.update(extra_detail)
    write_activity_log(
        category=CATEGORY_PIPELINE_RENAME,
        action=action,
        status=normalized_status,
        summary=summary,
        detail={k: v for k, v in detail.items() if v is not None},
        rjcode=rjcode,
        source_path=normalized_source_path or None,
    )


def log_batch_api_rename_result(
    *,
    batch_id: str,
    total_count: int,
    success_count: int,
    failed_count: int,
    results: list[dict[str, Any]],
    source_path: str = "",
) -> None:
    status = "success"
    if success_count > 0 and failed_count > 0:
        status = "partial_success"
    elif success_count <= 0:
        status = "failed"
    summary = f"批量 API 重命名完成，成功 {success_count} 项，失败 {failed_count} 项"
    write_activity_log(
        category=CATEGORY_PIPELINE_RENAME,
        action="batch_api_rename",
        status=status,
        summary=summary[:4000],
        detail={
            "mode": "batch_api_rename",
            "batch_id": str(batch_id or "").strip() or None,
            "total_count": int(total_count or 0),
            "success_count": int(success_count or 0),
            "failed_count": int(failed_count or 0),
            "results": results[:200] if isinstance(results, list) else [],
        },
        source_path=str(source_path or "").strip() or None,
        task_id=str(batch_id or "").strip() or None,
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
    preview_source_path = str(preview.get("source_path") or "").strip()
    preview_source_rjcode = str(preview.get("source_rjcode") or "").strip().upper()
    preview_target_rjcode = str(preview.get("target_rjcode") or "").strip().upper()
    detail = {
        k: result.get(k)
        for k in ("task_id", "final_file_count", "record_id")
        if result.get(k) is not None
    }
    if preview_source_path:
        detail["preview_source_path"] = preview_source_path
    if preview_source_rjcode:
        detail["source_rjcode"] = preview_source_rjcode
    if preview_target_rjcode:
        detail["target_rjcode"] = preview_target_rjcode
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
        "session_key": str(payload.get("session_key") or "").strip() or None,
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


def _mark_filter_delete_failed_preview_retried(payload: Dict[str, Any], retry_status: str) -> None:
    from ..models.database import ActivityLog, SessionLocal

    session_key = str(payload.get("session_key") or "").strip()
    folder_path = str(payload.get("folder_path") or "").strip()
    retry_targets = _build_filter_delete_items(payload.get("retry_targets"))
    retry_target_count = int(payload.get("retry_target_count") or len(retry_targets))
    retry_success_count = int(payload.get("retry_success_count") or 0)
    retry_failed_count = int(payload.get("retry_failed_count") or 0)
    retry_item_count = int(payload.get("recovered_item_count") or 0)
    retry_completed_at = datetime.now().isoformat()

    if not session_key:
        return

    db = SessionLocal()
    try:
        rows = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.category == CATEGORY_PIPELINE_FILTER,
                ActivityLog.action == "filter_delete_preview",
                ActivityLog.status == "failed",
            )
            .order_by(ActivityLog.created_at.desc())
            .all()
        )
        updated = 0
        for row in rows:
            detail = row.detail if isinstance(row.detail, dict) else {}
            if str(detail.get("session_key") or "").strip() != session_key:
                continue
            if folder_path and str(row.source_path or "").strip() not in {"", folder_path}:
                continue
            detail = {
                **detail,
                "retry_status": retry_status,
                "retry_completed": retry_status in {"success", "partial_success"},
                "retry_completed_at": retry_completed_at,
                "retry_target_count": retry_target_count,
                "retry_success_count": retry_success_count,
                "retry_failed_count": retry_failed_count,
                "retry_recovered_item_count": retry_item_count,
                "retry_targets": retry_targets,
            }
            row.detail = _sanitize_for_db_json(detail)
            status_text = "已重试成功" if retry_status == "success" else ("已重试部分成功" if retry_status == "partial_success" else "重试仍失败")
            summary = str(row.summary or "").strip()
            if status_text not in summary:
                row.summary = f"{summary}；{status_text}"[:4000] if summary else status_text
            updated += 1
        if updated:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        logger.warning("[操作记录] 回写删除预审重试状态失败", exc_info=True)
    finally:
        db.close()


def log_subtitle_batch_start_result(payload: Dict[str, Any]) -> None:
    batch_id = str(payload.get("batch_id") or "").strip()
    requested_count = int(payload.get("requested_count") or 0)
    recognized_rj_count = int(payload.get("recognized_rj_count") or 0)
    created_count = int(payload.get("created_count") or 0)
    skipped_total = int(payload.get("skipped_total") or 0)
    skipped_existing = int(payload.get("skipped_existing") or 0)
    skipped_duplicate = int(payload.get("skipped_duplicate") or 0)
    skipped_no_subtitle = int(payload.get("skipped_no_subtitle") or 0)
    scan_directory_count = int(payload.get("scan_directory_count") or 0)
    force_rerun = bool(payload.get("force_rerun"))
    skip_if_existing_subtitles = bool(payload.get("skip_if_existing_subtitles"))
    naming_strategy = str(payload.get("naming_strategy") or "audio").strip() or "audio"

    if created_count > 0 and skipped_total > 0:
        status = "partial_success"
    elif created_count <= 0 and skipped_total > 0 and recognized_rj_count > 0:
        status = "success"
    elif created_count > 0:
        status = "success"
    else:
        status = "failed"

    summary_parts = []
    if scan_directory_count > 0:
        summary_parts.append(f"扫描目录 {scan_directory_count} 个")
    if recognized_rj_count > 0:
        summary_parts.append(f"识别 RJ {recognized_rj_count} 个")
    if created_count > 0:
        summary_parts.append(f"创建爬取 {created_count} 个")
    if skipped_total > 0:
        summary_parts.append(f"跳过 {skipped_total} 个")
    summary = f"批量创建字幕任务，{'，'.join(summary_parts) if summary_parts else '无有效结果'}"

    detail = {
        "mode": "subtitle_batch_start",
        "batch_id": batch_id or None,
        "requested_count": requested_count,
        "recognized_rj_count": recognized_rj_count,
        "created_count": created_count,
        "skipped_total": skipped_total,
        "skipped_existing": skipped_existing,
        "skipped_duplicate": skipped_duplicate,
        "skipped_no_subtitle": skipped_no_subtitle,
        "scan_directory_count": scan_directory_count,
        "force_rerun": force_rerun,
        "skip_if_existing_subtitles": skip_if_existing_subtitles,
        "naming_strategy": naming_strategy,
        "source_directories": payload.get("source_directories") or [],
        "scan_targets": payload.get("scan_targets") or [],
        "created_tasks": payload.get("created_tasks") or [],
        "skipped_items": payload.get("skipped_items") or [],
    }
    write_activity_log(
        category=CATEGORY_SUBTITLE_CRAWL,
        action="batch_start",
        status=status,
        summary=summary[:4000],
        detail=detail,
        task_id=batch_id or None,
        source_path=str(payload.get("source_path") or "").strip() or None,
    )


def log_filter_delete_retry_result(payload: Dict[str, Any]) -> None:
    status = str(payload.get("status") or "success")
    scope_label = str(payload.get("scope_label") or payload.get("folder_name") or "删除过滤")
    folder_path = str(payload.get("folder_path") or "").strip() or None
    duration_ms = int(payload.get("duration_ms") or 0)
    retry_target_count = int(payload.get("retry_target_count") or 0)
    retry_success_count = int(payload.get("retry_success_count") or 0)
    retry_failed_count = int(payload.get("retry_failed_count") or 0)
    recovered_item_count = int(payload.get("recovered_item_count") or 0)
    recovered_selected_size = int(payload.get("recovered_selected_size") or 0)
    warning = str(payload.get("warning") or "").strip()
    error = str(payload.get("error") or "").strip()

    if status == "success":
        summary = (
            f"{scope_label} 删除预审失败项重试成功，"
            f"目录 {retry_success_count}/{retry_target_count}，"
            f"补回 {recovered_item_count} 项，"
            f"新增 {_format_bytes(recovered_selected_size)}，"
            f"耗时 {_format_duration_ms(duration_ms)}"
        )
    elif status == "partial_success":
        summary = (
            f"{scope_label} 删除预审失败项重试部分成功，"
            f"成功 {retry_success_count} 个目录，失败 {retry_failed_count} 个目录，"
            f"补回 {recovered_item_count} 项，"
            f"耗时 {_format_duration_ms(duration_ms)}"
        )
    else:
        summary = (
            f"{scope_label} 删除预审失败项重试失败，"
            f"目录 {retry_target_count} 个，"
            f"耗时 {_format_duration_ms(duration_ms)}"
        )
        if error:
            summary = f"{summary}：{error}"[:4000]

    detail = {
        "mode": "filter_delete_preview_retry",
        "session_key": str(payload.get("session_key") or "").strip() or None,
        "scope_label": scope_label,
        "folder_name": payload.get("folder_name"),
        "folder_path": folder_path,
        "duration_ms": duration_ms,
        "retry_target_count": retry_target_count,
        "retry_success_count": retry_success_count,
        "retry_failed_count": retry_failed_count,
        "recovered_item_count": recovered_item_count,
        "recovered_selected_size": recovered_selected_size,
        "retry_targets": _build_filter_delete_items(payload.get("retry_targets")),
        "recovered_items": _build_filter_delete_items(payload.get("recovered_items")),
        "failed_targets": _build_filter_delete_items(payload.get("failed_targets")),
        "warning": warning or None,
        "error": error or None,
    }
    normalized_status = "success" if status == "success" else ("partial_success" if status == "partial_success" else "failed")
    write_activity_log(
        category=CATEGORY_PIPELINE_FILTER,
        action="filter_delete_preview_retry",
        status=normalized_status,
        summary=summary,
        detail=detail,
        source_path=folder_path,
    )
    _mark_filter_delete_failed_preview_retried(payload, normalized_status)


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
        "session_key": str(payload.get("session_key") or "").strip() or None,
        "execution_key": str(payload.get("execution_key") or "").strip() or None,
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


def backfill_auto_import_extract_fields() -> Dict[str, int]:
    """一次性回填旧 auto_import 记录中的压缩包大小、解压标记与解压产物大小。"""
    from ..models.database import ActivityLog, ProcessedArchive, SessionLocal

    db = SessionLocal()
    scanned = 0
    updated = 0
    skipped = 0
    failed = 0
    try:
        rows = (
            db.query(ActivityLog)
            .filter(ActivityLog.category == CATEGORY_AUTO_IMPORT)
            .all()
        )
        for row in rows:
            scanned += 1
            try:
                detail = row.detail if isinstance(row.detail, dict) else {}
                source_path = str(row.source_path or "").strip()
                output_path = str(detail.get("output_path") or "").strip()
                is_archive = _looks_like_archive_path(source_path)
                current_archive_input = detail.get("archive_input")
                current_extract_performed = detail.get("extract_performed")
                current_extract_output_bytes = detail.get("extract_output_bytes")
                current_archive_size_bytes = detail.get("archive_size_bytes")

                next_archive_input = bool(is_archive)
                next_extract_performed = bool(is_archive and row.status == "success")
                next_extract_output_bytes = (
                    _safe_path_size(output_path)
                    if next_extract_performed and output_path
                    else int(current_extract_output_bytes or 0)
                )
                next_archive_size_bytes = int(current_archive_size_bytes or 0)
                archive_path = source_path
                if next_archive_input:
                    next_archive_size_bytes = _safe_path_size(source_path)
                    if next_archive_size_bytes <= 0 and row.task_id:
                        archive_record = (
                            db.query(ProcessedArchive)
                            .filter(ProcessedArchive.task_id == row.task_id)
                            .order_by(ProcessedArchive.processed_at.desc())
                            .first()
                        )
                        if archive_record is not None:
                            next_archive_size_bytes = int(archive_record.file_size or 0)
                            archive_path = str(archive_record.current_path or archive_record.original_path or source_path or "").strip()

                needs_update = False
                if current_archive_input is None:
                    detail["archive_input"] = next_archive_input
                    needs_update = True
                if current_extract_performed is None and next_archive_input:
                    detail["extract_performed"] = next_extract_performed
                    needs_update = True
                if (current_extract_output_bytes is None or int(current_extract_output_bytes or 0) <= 0) and next_extract_performed:
                    detail["extract_output_bytes"] = int(next_extract_output_bytes or 0)
                    needs_update = True
                if (current_archive_size_bytes is None or int(current_archive_size_bytes or 0) <= 0) and next_archive_input:
                    detail["archive_size_bytes"] = int(next_archive_size_bytes or 0)
                    needs_update = True
                if archive_path and archive_path != str(detail.get("archive_path") or "").strip():
                    detail["archive_path"] = archive_path
                    needs_update = True

                if needs_update:
                    row.detail = _sanitize_for_db_json(detail)
                    if row.status == "success" and next_archive_input:
                        duration_ms = int(detail.get("duration_ms") or 0)
                        extract_output_bytes = int(detail.get("extract_output_bytes") or 0)
                        extract_label = "预检解包" if str(detail.get("source_mode") or "").strip() == "linked_translation_archive_pending" and not output_path else "解压产物"
                        row.summary = (
                            f"{str(row.summary or '解压入库完成').split('，压缩包 ')[0]}，"
                            f"压缩包 {_format_bytes(next_archive_size_bytes)}，"
                            f"{extract_label} {_format_bytes(extract_output_bytes)}，"
                            f"耗时 {_format_duration_ms(duration_ms)}"
                        )[:4000]
                    updated += 1
                else:
                    skipped += 1
            except Exception:
                failed += 1
                logger.warning("[操作记录] 回填 auto_import 解压字段失败: id=%s", getattr(row, "id", None), exc_info=True)
        db.commit()
        return {
            "scanned": scanned,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
