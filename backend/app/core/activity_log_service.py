"""
用户操作审计持久化（SQLite activity_logs）。
业务分类：字幕爬取、字幕配对、字幕补配、解压、自动入库等。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm.attributes import flag_modified

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
CATEGORY_PIPELINE_DELETE = "pipeline_delete"
CATEGORY_ASMR_SYNC = "asmr_sync"
CATEGORY_UPLOAD = "upload"
CATEGORY_CIRCLE_COMPLETION = "circle_completion"
CATEGORY_EMAIL_WATCHER = "email_watcher"

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
    CATEGORY_PIPELINE_DELETE: "删除",
    CATEGORY_ASMR_SYNC: "ASMR 同步",
    CATEGORY_UPLOAD: "库存上传",
    CATEGORY_CIRCLE_COMPLETION: "社团补全",
    CATEGORY_EMAIL_WATCHER: "邮件监听",
}

ASMR_SYNC_ACTIONS = {
    "enhanced_plan_created",
    "enhanced_plan_failed",
    "session_started",
    "resource_downloaded",
    "resource_verify_failed",
    "resource_uploaded",
    "session_partial_failed",
    "session_completed",
    "queue_reordered",
    "task_paused",
    "task_resumed",
    "task_retried",
}

CIRCLE_COMPLETION_ACTIONS = {
    "index_started",
    "index_completed",
    "index_failed",
    "view_built",
    "refresh_selected_works",
    "refresh_all_circles",
    "download_batch_start",
    "download_batch_completed",
    "download_batch_partial_failed",
    "download_item_queued",
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


def _extract_rjcode(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    import re

    repeated = re.search(r"(?:RJ)+(\d{4,})", text, re.IGNORECASE)
    if repeated:
        return f"RJ{repeated.group(1)}"
    matched = re.search(r"RJ\d{4,}", text, re.IGNORECASE)
    if matched:
        return matched.group(0).upper()
    return ""


def _infer_rjcode_from_payload(payload: Dict[str, Any]) -> str:
    candidates = [
        payload.get("rjcode"),
        payload.get("source_rjcode"),
        payload.get("target_rjcode"),
        payload.get("scope_label"),
        payload.get("folder_name"),
        payload.get("folder_path"),
        payload.get("source_path"),
    ]
    for candidate in candidates:
        rjcode = _extract_rjcode(candidate)
        if rjcode:
            return rjcode
    return ""


def _resolve_filter_scope_label(payload: Dict[str, Any]) -> tuple[str, str]:
    base_label = str(payload.get("scope_label") or payload.get("folder_name") or "删除过滤").strip() or "删除过滤"
    rjcode = _infer_rjcode_from_payload(payload)
    if rjcode:
        if base_label in {"删除过滤", "未知RJ", "未知RJ号"}:
            return f"{rjcode} RJ目录", rjcode
        if "未知RJ" in base_label:
            return base_label.replace("未知RJ号", rjcode).replace("未知RJ", rjcode), rjcode
    return base_label, rjcode


_SAFE_PATH_SIZE_MAX_ENTRIES = 50000  # 保护上限：超过则停止统计，返回已累计值
_SAFE_PATH_SIZE_MAX_SECONDS = 3.0    # 保护上限：单次 walk 最长耗时
_FILE_TREE_SNAPSHOT_MAX_ITEMS = 400


def _safe_path_size(path: Any) -> int:
    """计算文件或目录的字节数，带硬上限防止卡死后台线程。"""
    try:
        target = str(path or "").strip()
        if not target or not os.path.exists(target):
            return 0
        if os.path.isfile(target):
            return int(os.path.getsize(target))
        total = 0
        scanned = 0
        deadline = time.monotonic() + _SAFE_PATH_SIZE_MAX_SECONDS
        for root, _, files in os.walk(target):
            if scanned >= _SAFE_PATH_SIZE_MAX_ENTRIES or time.monotonic() > deadline:
                logger.debug("[操作记录] _safe_path_size 触发保护上限，已扫描 %d 项：%s", scanned, target)
                break
            for name in files:
                scanned += 1
                if scanned >= _SAFE_PATH_SIZE_MAX_ENTRIES or time.monotonic() > deadline:
                    break
                file_path = os.path.join(root, name)
                try:
                    total += int(os.path.getsize(file_path))
                except Exception:
                    continue
        return total
    except Exception:
        return 0


def _snapshot_file_tree_items(root_path: Any, limit: Optional[int] = _FILE_TREE_SNAPSHOT_MAX_ITEMS) -> list[dict[str, Any]]:
    """为操作记录生成轻量文件树快照。"""
    try:
        normalized_root = str(root_path or "").strip()
    except Exception:
        return []
    if not normalized_root or not os.path.isdir(normalized_root):
        return []

    items: list[dict[str, Any]] = []
    try:
        for current_root, dir_names, file_names in os.walk(normalized_root):
            dir_names.sort()
            file_names.sort()
            relative_root = os.path.relpath(current_root, normalized_root)
            current_relative = "" if relative_root in {".", ""} else relative_root.replace("\\", "/")

            if current_relative:
                items.append({
                    "path": current_root,
                    "relative_path": current_relative,
                    "name": os.path.basename(current_root) or current_relative,
                    "type": "dir",
                    "size": 0,
                })
                if limit is not None and len(items) >= limit:
                    return items[:limit]

            for file_name in file_names:
                file_path = os.path.join(current_root, file_name)
                relative_path = f"{current_relative}/{file_name}" if current_relative else file_name
                try:
                    size = int(os.path.getsize(file_path))
                except Exception:
                    size = 0
                items.append({
                    "path": file_path,
                    "relative_path": relative_path.replace("\\", "/"),
                    "name": file_name,
                    "type": "file",
                    "size": size,
                })
                if limit is not None and len(items) >= limit:
                    return items[:limit]
    except Exception:
        logger.debug("[操作记录] 生成文件树快照失败: %s", normalized_root, exc_info=True)
        return []
    return items


def _normalize_file_tree_item_key(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    raw = item.get("relative_path") or item.get("path") or item.get("name") or ""
    return str(raw).strip().replace("\\", "/").strip("/")


def _sanitize_file_tree_item(item: Any) -> Optional[dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    key = _normalize_file_tree_item_key(item)
    if not key:
        return None
    item_type = str(item.get("type") or "file").strip().lower()
    if item_type not in {"file", "dir"}:
        item_type = "file"
    try:
        size = int(item.get("size") or 0)
    except Exception:
        size = 0
    return {
        "path": item.get("path"),
        "relative_path": key,
        "name": item.get("name") or os.path.basename(key) or key,
        "type": item_type,
        "size": size,
    }


def _merge_file_tree_items(*item_groups: Any) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in item_groups:
        if not isinstance(group, list):
            continue
        for raw_item in group:
            item = _sanitize_file_tree_item(raw_item)
            if item is None:
                continue
            key = item["relative_path"].lower()
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                continue
            if not existing.get("path") and item.get("path"):
                existing["path"] = item["path"]
            if (
                existing.get("type") != "dir"
                and item.get("type") == "dir"
            ):
                existing["type"] = "dir"
            if (not existing.get("name")) and item.get("name"):
                existing["name"] = item["name"]
            if int(existing.get("size") or 0) <= 0 and int(item.get("size") or 0) > 0:
                existing["size"] = int(item.get("size") or 0)
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("relative_path") or "").count("/"),
            str(item.get("relative_path") or "").lower(),
            0 if str(item.get("type") or "") == "dir" else 1,
        ),
    )


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
    """入队一条操作记录（Phase 1：异步批量写）。

    之前每次调用都 open/commit/close 一个独立 SQLAlchemy 会话，在任务结束 finally、
    批量删除等高频场景会和 SQLite writer lock 串行竞争。现在统一交给
    ActivityLogWriter 后台线程批量 flush，调用方仅做字段裁剪和 sanitize，无 IO。
    """
    from .activity_log_writer import get_activity_log_writer

    rc = (rjcode or "").strip().upper() or None
    sp = source_path[:4000] if source_path else None
    detail_clean = _sanitize_for_db_json(detail) if detail else {}
    if not isinstance(detail_clean, dict):
        detail_clean = {"_raw": detail_clean}

    # Phase 2：在写入点就把 detail 里的常用索引字段提升到独立列，
    # 避免查询时再通过 json_extract 扫描 detail。
    batch_id_value = str(detail_clean.get("batch_id") or "").strip()[:80] or None
    session_key_value = str(
        detail_clean.get("session_key")
        or detail_clean.get("session_id")
        or ""
    ).strip()[:120] or None
    parent_id_value = str(detail_clean.get("parent_id") or "").strip()[:36] or None

    payload = {
        "id": str(uuid.uuid4()),
        "category": category[:40],
        "action": (action or "")[:80],
        "status": (status or "")[:20],
        "summary": (summary or "")[:4000],
        "detail": detail_clean,
        "rjcode": rc[:32] if rc else None,
        "task_id": (task_id or "")[:36] or None,
        "source_path": sp,
        "batch_id": batch_id_value,
        "session_key": session_key_value,
        "parent_id": parent_id_value,
    }
    get_activity_log_writer().enqueue(payload)


def log_asmr_sync_event(
    action: str,
    *,
    status: str = "success",
    summary: str,
    session_id: Optional[str] = None,
    rjcode: Optional[str] = None,
    task_id: Optional[str] = None,
    source_path: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    payload = dict(detail or {})
    if session_id:
        payload.setdefault("session_id", session_id)
    if rjcode:
        payload.setdefault("rjcode", str(rjcode).strip().upper())
    if action not in ASMR_SYNC_ACTIONS:
        payload.setdefault("custom_action", action)
    write_activity_log(
        category=CATEGORY_ASMR_SYNC,
        action=action,
        status=status,
        summary=summary,
        detail=payload,
        rjcode=rjcode,
        task_id=task_id or session_id,
        source_path=source_path,
    )


class _TaskSnapshotProxy:
    """让 _build_task_lifecycle_detail 等函数可以像访问原 task 一样访问快照。"""

    __slots__ = ("_data",)

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        raise AttributeError(name)

    def is_cancelled(self) -> bool:
        return bool(self._data.get("is_cancelled"))


def _snapshot_task_for_lifecycle(task: Any) -> Optional[Dict[str, Any]]:
    """把任务对象里日志需要的字段一次性拷到普通 dict，避免后台线程读到被清理后的状态。"""
    try:
        task_metadata = getattr(task, "task_metadata", None)
        if isinstance(task_metadata, dict):
            task_metadata = dict(task_metadata)
        else:
            task_metadata = {}
        is_cancelled = False
        try:
            is_cancelled = bool(task.is_cancelled()) if hasattr(task, "is_cancelled") else False
        except Exception:
            is_cancelled = False
        return {
            "id": getattr(task, "id", None),
            "status": getattr(task, "status", None),
            "type": getattr(task, "type", None),
            "current_step": str(getattr(task, "current_step", "") or ""),
            "error_message": str(getattr(task, "error_message", "") or ""),
            "task_metadata": task_metadata,
            "source_path": getattr(task, "source_path", "") or "",
            "output_path": getattr(task, "output_path", "") or "",
            "rjcode": (getattr(task, "rjcode", "") or ""),
            "is_cancelled": is_cancelled,
            "started_at": getattr(task, "started_at", None),
            "created_at": getattr(task, "created_at", None),
            "completed_at": getattr(task, "completed_at", None),
        }
    except Exception:
        logger.debug("[操作记录] 任务快照失败", exc_info=True)
        return None


def log_task_lifecycle_event(task) -> None:
    """任务线程结束时记录一条（成功 / 失败 / 取消 / 等待）。

    Phase 1：任务 finally 只做一次属性快照，然后把昂贵的 detail 构造
    （os.walk / ProcessedArchive 回查）丢到后台线程池；任务线程立刻返回。
    """
    from .activity_log_writer import submit_lifecycle_prep

    snapshot = _snapshot_task_for_lifecycle(task)
    if snapshot is None or snapshot.get("status") is None:
        return
    submit_lifecycle_prep(_build_and_write_task_lifecycle_log, snapshot)


def _build_and_write_task_lifecycle_log(snapshot: Dict[str, Any]) -> None:
    """真正构造 detail 并入队的函数，运行在 lifecycle 线程池里。"""
    from .task_engine import TaskStatus, TaskType

    task = _TaskSnapshotProxy(snapshot)
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
        TaskType.LOCAL_LIBRARY_UPLOAD: CATEGORY_UPLOAD,
        TaskType.CIRCLE_COMPLETION_INDEX: CATEGORY_CIRCLE_COMPLETION,
        TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED: CATEGORY_CIRCLE_COMPLETION,
        TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH: CATEGORY_CIRCLE_COMPLETION,
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
        # 解压入库走“原作目录已有字幕 / 加入问题作品列表”分支时，task 在引擎里被设为 COMPLETED
        # 让任务列表收尾，但作品其实进了问题作品列表，操作记录不能再标记成纯成功，否则会和“入库✓”
        # 冲突。这里覆盖几种来源都降级为 partial_success：
        #   1. source_mode 显式标了 *_existing_subtitle_conflict
        #   2. metadata 上挂了 linked_subtitle_problem / existing_subtitle_problem 字段
        #   3. current_step 里出现“加入问题作品列表 / 转入问题作品 / 按重复作品处理” 等兜底关键词
        _meta_for_status = task.task_metadata or {}
        _source_mode_for_status = str(_meta_for_status.get("source_mode") or "").strip()
        _has_problem_marker = bool(
            _meta_for_status.get("linked_subtitle_problem")
            or _meta_for_status.get("existing_subtitle_problem")
        )
        _step_text_for_status = str(getattr(task, "current_step", "") or "")
        _PARTIAL_KEYWORDS = (
            "加入问题作品列表",
            "已转入问题作品",
            "按重复作品处理",
            "转入问题作品列表",
        )
        _step_hits_partial = any(kw in _step_text_for_status for kw in _PARTIAL_KEYWORDS)
        if (
            _source_mode_for_status.endswith("_existing_subtitle_conflict")
            or _source_mode_for_status == "linked_translation_archive_existing_subtitle_conflict"
            or _has_problem_marker
            or _step_hits_partial
        ):
            status = "partial_success"

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
            "library_id": meta.get("library_id"),
            "subtitle_library_id": meta.get("subtitle_library_id"),
            "awaiting_manual_match": bool(meta.get("awaiting_manual_match")),
            "batch_id": str(meta.get("batch_id") or "").strip() or None,
        }
    elif tt == TaskType.ASMR_SYNC_DOWNLOAD:
        performance_metrics = meta.get("performance_metrics") if isinstance(meta.get("performance_metrics"), dict) else {}
        download_root = str(meta.get("download_root") or "").strip()
        selected_resources = list(meta.get("selected_resources") or [])
        uploaded_files = list(meta.get("uploaded_files") or [])
        upload_runtime = meta.get("upload_runtime") if isinstance(meta.get("upload_runtime"), dict) else {}
        postprocess_options = meta.get("postprocess_options") if isinstance(meta.get("postprocess_options"), dict) else {}
        source_action = str(meta.get("source_action") or "").strip()
        downloaded_bytes = int(performance_metrics.get("downloaded_bytes") or 0)
        success_count = int(performance_metrics.get("success_count") or 0)
        failed_count = int(performance_metrics.get("failed_count") or 0)
        uploaded_count = int(performance_metrics.get("uploaded_count") or len(uploaded_files) or 0)
        duration_ms = int(performance_metrics.get("duration_ms") or _duration_ms_for_task(task) or 0)
        uploaded_bytes = int(
            performance_metrics.get("uploaded_bytes")
            or upload_runtime.get("total_bytes")
            or sum(int(item.get("size_bytes") or 0) for item in uploaded_files)
            or 0
        )
        average_upload_speed_bytes = int(
            performance_metrics.get("average_upload_speed_bytes")
            or (uploaded_bytes / max(duration_ms / 1000, 1) if uploaded_bytes > 0 and duration_ms > 0 else 0)
            or 0
        )
        upload_options = meta.get("upload_options") if isinstance(meta.get("upload_options"), dict) else {}
        target_path = str(upload_options.get("target_path") or "").strip()
        upload_mode = str(upload_options.get("mode") or "").strip() or None
        target_library_id = str(
            meta.get("target_library_id")
            or postprocess_options.get("target_library_id")
            or upload_options.get("library_id")
            or ""
        ).strip()
        target_subdir = str(postprocess_options.get("target_subdir") or "").strip()
        if not target_path:
            target_path = str(meta.get("final_output_path") or postprocess_options.get("target_path") or "").strip()
        is_reimport_task = source_action in {"reimport_local_download_root", "reimport_downloaded_session"}
        if st == TaskStatus.COMPLETED and success_count > 0:
            effective_count = uploaded_count if uploaded_count > 0 else success_count
            summary_parts = [f"{'上传' if uploaded_count > 0 or is_reimport_task else '下载'} {effective_count} 个文件"]
            if uploaded_bytes > 0:
                summary_parts.append(_format_bytes(uploaded_bytes))
            elif downloaded_bytes > 0:
                summary_parts.append(_format_bytes(downloaded_bytes))
            if average_upload_speed_bytes > 0:
                summary_parts.append(f"平均 {_format_bytes(average_upload_speed_bytes)}/s")
            if duration_ms > 0:
                summary_parts.append(f"耗时 {_format_duration_ms(duration_ms)}")
            summary = " / ".join(summary_parts)[:4000]
        detail = {
            "session_id": str(meta.get("session_id") or "").strip() or None,
            "download_root": download_root or None,
            "target_path": target_path or None,
            "upload_mode": upload_mode,
            "target_library_id": target_library_id or None,
            "target_subdir": target_subdir or None,
            "source_action": source_action or None,
            "selected_resource_count": int(meta.get("selected_resource_count") or len(selected_resources) or 0),
            "success_count": success_count,
            "failed_count": failed_count,
            "uploaded_count": uploaded_count,
            "downloaded_bytes": downloaded_bytes,
            "uploaded_bytes": uploaded_bytes,
            "average_upload_speed_bytes": average_upload_speed_bytes,
            "duration_ms": duration_ms,
            "uploaded_files": uploaded_files[:200],
        }
    elif tt == TaskType.LOCAL_LIBRARY_UPLOAD:
        upload_runtime = meta.get("upload_runtime") if isinstance(meta.get("upload_runtime"), dict) else {}
        uploaded_files = list(meta.get("uploaded_files") or [])
        selected_paths = list(meta.get("selected_paths") or [])
        selected_dir_count = int(meta.get("selected_dir_count") or len(selected_paths) or 0)
        duration_ms = int(_duration_ms_for_task(task) or 0)
        uploaded_bytes = int(
            upload_runtime.get("total_bytes")
            or sum(int((item or {}).get("size_bytes") or 0) for item in uploaded_files)
            or 0
        )
        average_upload_speed_bytes = int(
            (uploaded_bytes / max(duration_ms / 1000, 1) if uploaded_bytes > 0 and duration_ms > 0 else 0)
            or 0
        )
        target_path = str(meta.get("target_path") or task.output_path or "").strip()
        source_action = str(meta.get("source_action") or "").strip()
        if st == TaskStatus.COMPLETED:
            summary_parts = [f"上传 {len(uploaded_files) or len(meta.get('upload_files') or []) or 0} 个文件"]
            if uploaded_bytes > 0:
                summary_parts.append(_format_bytes(uploaded_bytes))
            if average_upload_speed_bytes > 0:
                summary_parts.append(f"平均 {_format_bytes(average_upload_speed_bytes)}/s")
            if duration_ms > 0:
                summary_parts.append(f"耗时 {_format_duration_ms(duration_ms)}")
            summary = " / ".join(summary_parts)[:4000]
        detail = {
            "target_path": target_path or None,
            "target_library_id": str(meta.get("target_library_id") or "").strip() or None,
            "target_subdir": str(meta.get("target_subdir") or "").strip() or None,
            "source_library_id": str(meta.get("source_library_id") or "").strip() or None,
            "source_base_path": str(meta.get("source_base_path") or "").strip() or None,
            "source_action": source_action or None,
            "selected_dir_count": selected_dir_count,
            "uploaded_count": len(uploaded_files),
            "uploaded_bytes": uploaded_bytes,
            "average_upload_speed_bytes": average_upload_speed_bytes,
            "duration_ms": duration_ms,
            "uploaded_files": uploaded_files[:200],
        }
    elif tt == TaskType.EXTRACT:
        archive_size_bytes, archive_path = _resolve_archive_snapshot(task)
        output_size_bytes = _safe_path_size(task.output_path) if st == TaskStatus.COMPLETED else 0
        file_tree_items = _snapshot_file_tree_items(task.output_path) if st == TaskStatus.COMPLETED else []
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
            "file_tree_items": file_tree_items,
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
            "batch_id": str(meta.get("batch_id") or "").strip() or None,
            "session_id": str(meta.get("session_id") or "").strip() or None,
            "source_mode": source_mode or None,
            "linked_source_rjcode": str(linked_preview.get("source_rjcode") or "").strip().upper() or None,
            "linked_target_rjcode": str(linked_preview.get("target_rjcode") or "").strip().upper() or None,
            "file_tree_items": list(meta.get("file_tree_items") or []),
            "filtered_count": int(meta.get("filtered_count") or 0),
            "filtered_size": int(meta.get("filtered_size") or 0),
            "filtered_items": _build_filter_delete_items(meta.get("filtered_items"), limit=240),
        }
        if tt in {TaskType.CIRCLE_COMPLETION_INDEX, TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH}:
            detail["circle_id"] = str(meta.get("circle_id") or "").strip() or None
            detail["circle_name"] = str(meta.get("circle_name") or "").strip() or None
            detail["parent_session_id"] = str(meta.get("parent_session_id") or "").strip() or None
            detail["batch_total"] = int(meta.get("batch_total") or 0) or None
            detail["batch_circle_summaries"] = list(meta.get("batch_circle_summaries") or [])[:100]

    if tt in {TaskType.CIRCLE_COMPLETION_INDEX, TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED, TaskType.CIRCLE_COMPLETION_DOWNLOAD_BATCH}:
        detail["source_page"] = str(meta.get("source_page") or "").strip() or None
        detail["source_action"] = str(meta.get("source_action") or "").strip() or None
        detail["source_label"] = str(meta.get("source_label") or "").strip() or None
        detail["business_key"] = str(meta.get("business_key") or "").strip() or None
        if tt == TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED:
            detail["selected_count"] = int(meta.get("selected_count") or 0) or None
            detail["refreshed_count"] = int(meta.get("refreshed_count") or 0) or None
            detail["changed_count"] = int(
                meta.get("changed_count")
                or ((meta.get("refresh_result") or {}).get("changed_count") if isinstance(meta.get("refresh_result"), dict) else 0)
                or 0
            ) or None

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


def log_circle_completion_event(
    action: str,
    *,
    status: str = "success",
    summary: str,
    circle_id: Optional[str] = None,
    circle_name: Optional[str] = None,
    batch_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    source_path: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    payload = dict(detail or {})
    if circle_id:
        payload.setdefault("circle_id", circle_id)
    if circle_name:
        payload.setdefault("circle_name", circle_name)
    if batch_id:
        payload.setdefault("batch_id", batch_id)
    if session_id:
        payload.setdefault("session_id", session_id)
    if action not in CIRCLE_COMPLETION_ACTIONS:
        payload.setdefault("custom_action", action)
    write_activity_log(
        category=CATEGORY_CIRCLE_COMPLETION,
        action=action,
        status=status,
        summary=summary,
        detail=payload,
        task_id=task_id or batch_id or session_id,
        source_path=source_path,
    )


def log_subtitle_pair_complete(
    task_id: str,
    rjcode: str,
    applied_pairs: int,
    deleted_subtitles: int,
    summary: str,
    linked_detail: Optional[Dict[str, Any]] = None,
    source_path: Optional[str] = None,
) -> None:
    detail = {
        "applied_pairs": applied_pairs,
        "deleted_subtitles": deleted_subtitles,
    }
    if isinstance(linked_detail, dict):
        pair_changes = linked_detail.get("pair_changes")
        if isinstance(pair_changes, list):
            linked_detail["pair_changes"] = pair_changes[:200]
        detail.update(linked_detail)
    write_activity_log(
        category=CATEGORY_SUBTITLE_PAIR,
        action="manual_complete",
        status="success",
        summary=summary,
        detail=detail,
        rjcode=rjcode,
        task_id=task_id,
        source_path=source_path,
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


def log_batch_manual_rename_result(
    *,
    batch_id: str,
    total_count: int,
    success_count: int,
    failed_count: int,
    results: list[dict[str, Any]],
    source_path: str = "",
    rename_context: str = "",
) -> None:
    status = "success"
    if success_count > 0 and failed_count > 0:
        status = "partial_success"
    elif success_count <= 0:
        status = "failed"
    summary = f"批量乱码修复完成，成功 {success_count} 项，失败 {failed_count} 项"
    write_activity_log(
        category=CATEGORY_PIPELINE_RENAME,
        action="batch_manual_rename",
        status=status,
        summary=summary[:4000],
        detail={
            "mode": "batch_manual_rename",
            "batch_id": str(batch_id or "").strip() or None,
            "rename_context": str(rename_context or "").strip() or None,
            "total_count": int(total_count or 0),
            "success_count": int(success_count or 0),
            "failed_count": int(failed_count or 0),
            "results": results[:200] if isinstance(results, list) else [],
        },
        source_path=str(source_path or "").strip() or None,
        task_id=str(batch_id or "").strip() or None,
    )


def log_api_delete_action(
    *,
    action: str,
    success: bool,
    source_path: str,
    item_name: str = "",
    item_type: str = "",
    rjcode: Optional[str] = None,
    batch_id: Optional[str] = None,
    library_id: Optional[str] = None,
    error: str = "",
    status: Optional[str] = None,
    extra_detail: Optional[Dict[str, Any]] = None,
) -> None:
    normalized_source_path = str(source_path or "").strip()
    normalized_name = str(item_name or "").strip() or (os.path.basename(normalized_source_path) if normalized_source_path else "")
    normalized_type = str(item_type or "").strip() or "unknown"
    normalized_error = str(error or "").strip()
    normalized_status = str(status or ("success" if success else "failed")).strip() or ("success" if success else "failed")

    summary = f"删除 {normalized_type}：{normalized_name or '未命名'}"
    if normalized_status == "failed" and normalized_error:
        summary = f"{summary}：{normalized_error}"[:4000]
    else:
        summary = summary[:4000]

    detail = {
        "mode": "api_delete",
        "delete_key": normalized_source_path or None,
        "item_name": normalized_name or None,
        "item_type": normalized_type or None,
        "path": normalized_source_path or None,
        "batch_id": str(batch_id or "").strip() or None,
        "library_id": str(library_id or "").strip() or None,
        "error": normalized_error or None,
    }
    if isinstance(extra_detail, dict):
        detail.update(extra_detail)

    write_activity_log(
        category=CATEGORY_PIPELINE_DELETE,
        action=action,
        status=normalized_status,
        summary=summary,
        detail={k: v for k, v in detail.items() if v is not None},
        rjcode=rjcode,
        source_path=normalized_source_path or None,
    )


def log_batch_api_delete_result(
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

    summary = f"批量删除完成，成功 {success_count} 项，失败 {failed_count} 项"
    write_activity_log(
        category=CATEGORY_PIPELINE_DELETE,
        action="batch_api_delete",
        status=status,
        summary=summary[:4000],
        detail={
            "mode": "batch_api_delete",
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
    scope_label, inferred_rjcode = _resolve_filter_scope_label(payload)
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
        rjcode=inferred_rjcode or None,
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


def mark_task_conflict_resolved_activity_log(
    task_id: Optional[str],
    conflict_action: str,
    *,
    conflict_id: Optional[str] = None,
) -> bool:
    """把原任务那条 ``task_finished/waiting`` 行回写成已跳过 / 已保留新版 / 已合并。

    用户在问题作品页面拍板后，原任务在写日志时还是 ``status=waiting`` +
    summary “…，请在问题作品页面处理”。这一行不会再被 task 引擎自动覆盖，
    操作记录的关联事件就一直停留在“等待处理”——本函数就是把这条行就地改写。

    Args:
        task_id: 原始问题作品对应的任务 ID（KEEP_NEW 已经把 ``conflict.task_id`` 换成了
            新任务，调用方需要自己保留更早期的旧 task_id）。
        conflict_action: ``SKIP`` / ``KEEP_NEW`` / ``MERGE``，会决定写回的 status / 标签。
        conflict_id: 关联的 ``ConflictWork.id``，写到 detail 便于排查。

    Returns:
        bool: 是否更新到至少一行。
    """
    from ..models.database import ActivityLog, SessionLocal
    from .activity_log_writer import (
        get_activity_log_query_cache,
        get_activity_log_row_dict_cache,
    )

    raw_task_id = (str(task_id or "").strip())
    if not raw_task_id:
        return False
    raw_action = (conflict_action or "").strip().upper()
    label_map = {"SKIP": "已跳过", "KEEP_NEW": "已保留新版", "MERGE": "已合并"}
    status_map = {"SKIP": "cancelled", "KEEP_NEW": "success", "MERGE": "success"}
    if raw_action not in label_map:
        return False

    db = SessionLocal()
    try:
        rows = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.task_id == raw_task_id,
                ActivityLog.action.in_(("task_finished", "task_finished_incomplete")),
                ActivityLog.status == "waiting",
            )
            .order_by(ActivityLog.created_at.desc())
            .all()
        )
        if not rows:
            return False

        new_status = status_map[raw_action]
        new_label = label_map[raw_action]
        resolved_at = datetime.now().isoformat()
        for row in rows:
            row.status = new_status
            existing_summary = (row.summary or "").strip()
            if existing_summary and not existing_summary.startswith(new_label):
                merged_summary = f"{new_label}：{existing_summary}"
            else:
                merged_summary = existing_summary or new_label
            row.summary = merged_summary[:4000]
            detail = row.detail if isinstance(row.detail, dict) else {}
            updated_detail = {
                **detail,
                "conflict_resolution_action": raw_action,
                "conflict_resolution_label": new_label,
                "conflict_resolved_at": resolved_at,
            }
            if conflict_id:
                updated_detail["conflict_id"] = str(conflict_id)
            row.detail = _sanitize_for_db_json(updated_detail)
            # detail 是 JSON 列，bulk update 时 SQLAlchemy 不一定能识别 dict 内变更，
            # 这里显式打 dirty 标记，和现有 _mark_filter_delete_failed_preview_retried 行为对齐。
            flag_modified(row, "detail")

        db.commit()
        # 行级 dict 缓存按 id 持久缓存（注释里写的“rows 不可变”假设在这里被打破），
        # 必须手动 invalidate 一下，否则下次列表请求会一直命中旧的“等待处理”。
        # 列表查询缓存也走兜底失效，避免拿到旧合并结果。
        try:
            get_activity_log_row_dict_cache().invalidate()
            get_activity_log_query_cache().invalidate()
        except Exception:
            logger.debug("[操作记录] 失效问题作品解决缓存失败（非致命）", exc_info=True)
        return True
    except Exception:
        db.rollback()
        logger.warning(
            "[操作记录] 回写问题作品解决状态失败 task_id=%s action=%s",
            raw_task_id,
            raw_action,
            exc_info=True,
        )
        return False
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


def log_import_batch_start_result(payload: Dict[str, Any], *, category: str = CATEGORY_AUTO_IMPORT) -> None:
    batch_id = str(payload.get("batch_id") or "").strip()
    requested_count = int(payload.get("requested_count") or 0)
    created_count = int(payload.get("created_count") or 0)
    skipped_total = int(payload.get("skipped_total") or 0)
    skipped_processed = int(payload.get("skipped_processed") or 0)
    skipped_duplicate = int(payload.get("skipped_duplicate") or 0)
    archive_count = int(payload.get("archive_count") or 0)
    extracted_count = int(payload.get("extracted_count") or 0)
    total_archive_size_bytes = int(payload.get("total_archive_size_bytes") or 0)
    auto_classify = bool(payload.get("auto_classify"))
    target_library_id = str(payload.get("target_library_id") or "").strip() or None
    source_paths = payload.get("source_paths") or []
    created_tasks = payload.get("created_tasks") or []
    skipped_items = payload.get("skipped_items") or []
    source_action = str(payload.get("source_action") or "").strip()

    if created_count > 0 and skipped_total > 0:
        status = "partial_success"
    elif created_count > 0:
        status = "success"
    elif requested_count > 0 or archive_count > 0 or skipped_total > 0:
        status = "success"
    else:
        status = "failed"

    summary_parts = []
    if requested_count > 0:
        summary_parts.append(f"候选 {requested_count} 个")
    if archive_count > 0:
        summary_parts.append(f"压缩包 {archive_count} 个")
    if extracted_count > 0:
        summary_parts.append(f"已提交解压 {extracted_count} 个")
    elif created_count > 0:
        summary_parts.append(f"已提交处理 {created_count} 个")
    if skipped_total > 0:
        summary_parts.append(f"跳过 {skipped_total} 个")
    if total_archive_size_bytes > 0:
        summary_parts.append(f"总大小 {_format_bytes(total_archive_size_bytes)}")

    base_summary = "批量创建解压任务" if category == CATEGORY_AUTO_IMPORT else "批量创建已有目录处理任务"
    summary = f"{base_summary}，{'，'.join(summary_parts) if summary_parts else '无有效结果'}"

    detail = {
        "mode": "import_batch_start" if category == CATEGORY_AUTO_IMPORT else "process_existing_batch_start",
        "batch_id": batch_id or None,
        "requested_count": requested_count,
        "created_count": created_count,
        "skipped_total": skipped_total,
        "skipped_processed": skipped_processed,
        "skipped_duplicate": skipped_duplicate,
        "archive_count": archive_count,
        "extracted_count": extracted_count,
        "total_archive_size_bytes": total_archive_size_bytes,
        "auto_classify": auto_classify,
        "target_library_id": target_library_id,
        "source_page": str(payload.get("source_page") or "").strip() or None,
        "source_action": source_action or None,
        "source_label": str(payload.get("source_label") or "").strip() or None,
        "source_paths": source_paths,
        "created_tasks": created_tasks,
        "skipped_items": skipped_items,
    }
    write_activity_log(
        category=category,
        action="batch_start",
        status=status,
        summary=summary[:4000],
        detail=detail,
        task_id=batch_id or None,
        source_path=str(payload.get("source_path") or "").strip() or None,
    )


def log_filter_delete_retry_result(payload: Dict[str, Any]) -> None:
    status = str(payload.get("status") or "success")
    scope_label, inferred_rjcode = _resolve_filter_scope_label(payload)
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
        rjcode=inferred_rjcode or None,
        source_path=folder_path,
    )
    _mark_filter_delete_failed_preview_retried(payload, normalized_status)


def log_filter_delete_apply_result(payload: Dict[str, Any]) -> None:
    status = str(payload.get("status") or "success")
    success_count = int(payload.get("success_count") or 0)
    failed_count = int(payload.get("failed_count") or 0)
    duration_ms = int(payload.get("duration_ms") or 0)
    deleted_bytes = int(payload.get("deleted_bytes") or 0)
    scope_label, inferred_rjcode = _resolve_filter_scope_label(payload)
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
        rjcode=inferred_rjcode or None,
        source_path=folder_path,
    )


def backfill_auto_import_extract_fields(
    *,
    chunk_size: int = 200,
    start_offset: int = 0,
    max_rows: Optional[int] = None,
    time_budget_seconds: float = 8.0,
) -> Dict[str, Any]:
    """分片回填旧导入链记录中的压缩包大小、解压标记、解压产物大小与文件树。

    原实现把全表 auto_import 行一次加载到内存并逐行 os.walk，大库存会直接卡死事件循环。
    Phase 1：改成按 offset 分片扫描 + 时间预算 + 可恢复 cursor。调用方（API 或 TaskEngine）
    可多次调用，接着上次的 offset 继续。

    参数：
    - chunk_size: 每批加载行数，默认 200
    - start_offset: 起始偏移（断点续跑用）
    - max_rows: 本次最多扫描多少行，None=直到耗尽 time_budget
    - time_budget_seconds: 单次调用的软时间上限；到点则返回 next_offset

    返回：scanned/updated/skipped/failed/next_offset/done
    """
    from ..models.database import ActivityLog, ProcessedArchive, SessionLocal

    scanned = 0
    updated = 0
    skipped = 0
    failed = 0
    offset = max(0, int(start_offset or 0))
    chunk_size = max(20, min(1000, int(chunk_size or 200)))
    deadline = time.monotonic() + max(1.0, float(time_budget_seconds))
    remaining_budget = int(max_rows) if max_rows is not None else None

    while True:
        if remaining_budget is not None and remaining_budget <= 0:
            break
        if time.monotonic() > deadline:
            break

        this_chunk = chunk_size
        if remaining_budget is not None:
            this_chunk = min(this_chunk, remaining_budget)

        db = SessionLocal()
        try:
            rows = (
                db.query(ActivityLog)
                .filter(ActivityLog.category.in_([CATEGORY_AUTO_IMPORT, CATEGORY_EXTRACT, CATEGORY_PROCESS_EXISTING]))
                .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
                .offset(offset)
                .limit(this_chunk)
                .all()
            )
            if not rows:
                db.close()
                return {
                    "scanned": scanned,
                    "updated": updated,
                    "skipped": skipped,
                    "failed": failed,
                    "next_offset": offset,
                    "done": True,
                }

            for row in rows:
                scanned += 1
                if remaining_budget is not None:
                    remaining_budget -= 1
                try:
                    detail = row.detail if isinstance(row.detail, dict) else {}
                    source_path = str(row.source_path or "").strip()
                    output_path = str(detail.get("output_path") or "").strip()
                    category = str(row.category or "").strip()
                    is_archive = _looks_like_archive_path(source_path)
                    current_archive_input = detail.get("archive_input")
                    current_extract_performed = detail.get("extract_performed")
                    current_extract_output_bytes = detail.get("extract_output_bytes")
                    current_archive_size_bytes = detail.get("archive_size_bytes")
                    current_file_tree_items = list(detail.get("file_tree_items") or [])
                    filtered_items = _build_filter_delete_items(detail.get("filtered_items"), limit=10000)
                    should_snapshot_output_tree = bool(
                        row.status == "success"
                        and output_path
                        and category in {CATEGORY_AUTO_IMPORT, CATEGORY_EXTRACT, CATEGORY_PROCESS_EXISTING}
                    )

                    next_archive_input = bool(is_archive)
                    next_extract_performed = bool(
                        row.status == "success"
                        and (
                            category == CATEGORY_EXTRACT
                            or is_archive
                        )
                    )
                    next_extract_output_bytes = (
                        _safe_path_size(output_path)
                        if next_extract_performed and output_path
                        else int(current_extract_output_bytes or 0)
                    )
                    snapshot_file_tree_items = (
                        _snapshot_file_tree_items(output_path, limit=None)
                        if should_snapshot_output_tree
                        else []
                    )
                    next_file_tree_items = _merge_file_tree_items(
                        snapshot_file_tree_items,
                        current_file_tree_items,
                        filtered_items,
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
                    if current_extract_performed is None and (next_archive_input or category == CATEGORY_EXTRACT):
                        detail["extract_performed"] = next_extract_performed
                        needs_update = True
                    if (current_extract_output_bytes is None or int(current_extract_output_bytes or 0) <= 0) and next_extract_performed:
                        detail["extract_output_bytes"] = int(next_extract_output_bytes or 0)
                        needs_update = True
                    if (current_archive_size_bytes is None or int(current_archive_size_bytes or 0) <= 0) and next_archive_input:
                        detail["archive_size_bytes"] = int(next_archive_size_bytes or 0)
                        needs_update = True
                    if next_file_tree_items != current_file_tree_items:
                        detail["file_tree_items"] = next_file_tree_items
                        needs_update = True
                    if archive_path and archive_path != str(detail.get("archive_path") or "").strip():
                        detail["archive_path"] = archive_path
                        needs_update = True

                    if needs_update:
                        row.detail = _sanitize_for_db_json(detail)
                        flag_modified(row, "detail")
                        if row.status == "success" and (next_archive_input or category == CATEGORY_EXTRACT):
                            duration_ms = int(detail.get("duration_ms") or 0)
                            extract_output_bytes = int(detail.get("extract_output_bytes") or 0)
                            if category == CATEGORY_EXTRACT:
                                row.summary = (
                                    f"{str(row.summary or '压缩包解压完成').split('，压缩包 ')[0]}，"
                                    f"压缩包 {_format_bytes(next_archive_size_bytes)}，"
                                    f"解压产物 {_format_bytes(extract_output_bytes)}，"
                                    f"耗时 {_format_duration_ms(duration_ms)}"
                                )[:4000]
                            else:
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
            offset += len(rows)
            # 若本批加载不足 chunk_size，视作表已扫完
            if len(rows) < this_chunk:
                return {
                    "scanned": scanned,
                    "updated": updated,
                    "skipped": skipped,
                    "failed": failed,
                    "next_offset": offset,
                    "done": True,
                }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # 时间预算或 max_rows 用完，返回断点供下一次继续
    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "next_offset": offset,
        "done": False,
    }
