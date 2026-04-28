"""任务通知 payload 辅助工具。"""
import os
from datetime import datetime
from typing import Any


def set_notification_extra(task, **kwargs) -> None:
    """把额外通知数据塞进任务 metadata，供 outbox payload 合并。"""
    if task is None:
        return
    meta = dict(getattr(task, "task_metadata", None) or {})
    extra = dict(meta.get("notification_extra") or {})
    for key, value in kwargs.items():
        if value is not None:
            extra[key] = value
    meta["notification_extra"] = extra
    task.task_metadata = meta


def build_recent_logs(task, *, max_lines: int = 30, level: str = "info") -> list[dict]:
    """从任务 progress_log/current_step 生成邮件日志块数据。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    raw_logs = list(meta.get("progress_log") or [])
    rows: list[dict] = []
    for item in raw_logs[-max_lines:]:
        if isinstance(item, dict):
            text = item.get("message") or item.get("text") or item.get("step") or ""
            rows.append({
                "level": str(item.get("level") or level).lower(),
                "text": str(text),
                "ts": str(item.get("ts") or item.get("time") or ""),
            })
        else:
            rows.append({"level": level, "text": str(item), "ts": ""})

    current_step = str(getattr(task, "current_step", "") or "").strip()
    if current_step and not any(row.get("text") == current_step for row in rows):
        rows.append({
            "level": level,
            "text": current_step,
            "ts": datetime.now().strftime("%H:%M:%S"),
        })
    return rows[-max_lines:]


def build_import_notification_extra(task, *, error: str = "") -> dict[str, Any]:
    """为解压 / 入库任务构造业务块 payload。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    output_path = str(getattr(task, "output_path", "") or meta.get("final_output_path") or "").strip()
    file_tree = _normalize_file_tree(meta.get("file_tree_items") or [], output_path)

    filtered_items = list(meta.get("filtered_items") or [])
    filtered_files = list(meta.get("filtered_files") or [])
    filtered_dirs = list(meta.get("filtered_dirs") or [])
    for item in filtered_items or filtered_files or filtered_dirs:
        row = _normalize_tree_item(item, status="filtered")
        if row:
            file_tree.append(row)

    stats = {
        "total_files": _count_files(file_tree) or _count_files_on_disk(output_path),
        "total_size": _format_bytes(_sum_sizes(file_tree)),
        "filtered_count": int(meta.get("filtered_count") or len(filtered_items or filtered_files or filtered_dirs) or 0),
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
    }
    if not stats["total_size"] and output_path:
        stats["total_size"] = _format_bytes(_sum_size_on_disk(output_path))

    result: dict[str, Any] = {
        "stats": stats,
        "file_tree": file_tree[:120],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }
    if error:
        result["error_logs"] = [{"level": "error", "text": str(error), "ts": datetime.now().strftime("%H:%M:%S")}]
        result["summary"] = str(error)
    return result


def build_notification_extra_for_task(task) -> dict[str, Any]:
    """从任务详情 metadata 自动抽取邮件业务组件数据。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    domain = str(meta.get("task_domain") or "").strip()
    kind = str(meta.get("task_kind") or getattr(getattr(task, "type", None), "value", "") or "").strip()

    if domain == "circle_completion" or kind.startswith("circle_completion"):
        return build_circle_completion_notification_extra(task)

    if domain == "upload" or kind == "local_library_upload":
        return build_upload_notification_extra(task)

    if domain == "asmr_sync" or kind == "asmr_sync_download":
        return build_download_notification_extra(task, title="下载文件")

    if domain == "rj_subtitle" or kind == "rj_subtitle_fetch":
        return build_subtitle_notification_extra(task)

    if any(meta.get(key) for key in ("file_tree_items", "filtered_items", "filtered_files", "filtered_dirs")):
        return build_import_notification_extra(task, error=str(getattr(task, "error_message", "") or ""))

    result: dict[str, Any] = {}
    logs = build_recent_logs(task, max_lines=30)
    if logs:
        result["recent_logs"] = logs
    return result


def build_circle_completion_notification_extra(task) -> dict[str, Any]:
    """社团补全：统计 + 类似详情页的来源概括表 + 执行日志。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    counts = dict(meta.get("indexed_counts") or {})
    result_payload = dict(meta.get("index_result") or {})
    summary = dict(result_payload.get("summary") or {})
    if summary:
        counts = {**summary, **counts}

    circle_id = str(meta.get("circle_id") or result_payload.get("circle_id") or "").strip()
    circle_name = str(meta.get("circle_name") or summary.get("circle_name") or meta.get("circle_query") or "").strip()

    rows = _load_circle_overview_rows(circle_id, limit=36)
    local_owned = _safe_int(counts.get("local_owned_count"))
    owned = _safe_int(counts.get("owned_count"))
    dl_count = _safe_int(counts.get("dl_count"))
    downloadable = _safe_int(counts.get("downloadable_count"))
    missing = _safe_int(counts.get("missing_count"))
    works = _safe_int(counts.get("works")) or len(rows)
    asmr_one = sum(1 for row in rows if row.get("asmr_one") and row.get("asmr_one") != "暂无来源")
    dl_only = sum(1 for row in rows if row.get("kikoeru") == "未收录" and row.get("dlsite") != "暂无来源" and row.get("asmr_one") == "暂无来源")

    stats = {
        "works": works,
        "local_owned": local_owned,
        "owned": owned,
        "dl_count": dl_count,
        "asmr_one": asmr_one,
        "downloadable": downloadable,
        "missing": missing,
        "dl_only": dl_only,
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
    }
    diff_items = [
        {"label": "本地", "old": "", "new": f"{local_owned} 个"},
        {"label": "Kikoeru", "old": "", "new": f"{owned} 个"},
        {"label": "DLsite", "old": "", "new": f"{dl_count} 个"},
        {"label": "asmr.one", "old": "", "new": f"{asmr_one} 个"},
        {"label": "可下载", "old": "", "new": f"{downloadable} 个"},
        {"label": "暂无来源", "old": "", "new": f"{dl_only} 个"},
    ]
    extra: dict[str, Any] = {
        "stats": stats,
        "circle_name": circle_name,
        "circle_id": circle_id,
        "circle_overview": rows,
        "circle_diff": diff_items,
        "recent_logs": build_recent_logs(task, max_lines=30),
    }
    if circle_name:
        extra["summary"] = (
            f"{circle_name}：共 {works} 个作品，DLsite {dl_count} 个，"
            f"asmr.one {asmr_one} 个，可下载 {downloadable} 个，暂无来源 {dl_only} 个"
        )
    return extra


def build_upload_notification_extra(task) -> dict[str, Any]:
    meta = dict(getattr(task, "task_metadata", None) or {})
    upload_files = [_normalize_tree_item(item, status=str((item or {}).get("status") or "pending")) for item in list(meta.get("upload_files") or []) if item]
    uploaded_files = [_normalize_tree_item(item, status="completed") for item in list(meta.get("uploaded_files") or []) if item]
    rows = [row for row in upload_files if row] or [row for row in uploaded_files if row]
    runtime = dict(meta.get("upload_runtime") or {})
    total_bytes = _safe_int(runtime.get("total_bytes")) or _sum_sizes(rows)
    completed_files = _safe_int(runtime.get("completed_files")) or len(uploaded_files)
    return {
        "stats": {
            "total_files": len(rows) or completed_files,
            "uploaded_count": completed_files,
            "total_size": _format_bytes(total_bytes),
            "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        },
        "upload_files": rows[:160],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }


def build_download_notification_extra(task, *, title: str = "下载文件") -> dict[str, Any]:
    meta = dict(getattr(task, "task_metadata", None) or {})
    rows = [_normalize_tree_item(item, status=str((item or {}).get("status") or "kept")) for item in list(meta.get("download_files") or []) if item]
    rows = [row for row in rows if row]
    failed_count = len(list(meta.get("failed_files") or []))
    return {
        "stats": {
            "total_files": len(rows) or _safe_int(meta.get("selected_resource_count")),
            "failed_count": failed_count,
            "total_size": _format_bytes(_sum_sizes(rows)),
            "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        },
        "download_files": rows[:160],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }


def build_subtitle_notification_extra(task) -> dict[str, Any]:
    meta = dict(getattr(task, "task_metadata", None) or {})
    downloaded = [_normalize_tree_item(item, status="new") for item in list(meta.get("download_files") or []) if item]
    written = [_normalize_tree_item(item, status="kept") for item in list(meta.get("written_files") or []) if item]
    skipped = [_normalize_tree_item(item, status="filtered") for item in list(meta.get("skipped_files") or []) if item]
    rows = [row for row in [*downloaded, *written, *skipped] if row]
    return {
        "stats": {
            "downloaded": _safe_int(meta.get("downloaded_count")) or len(downloaded),
            "written": len(written),
            "skipped": len(skipped),
            "existing_subtitles": _safe_int(meta.get("existing_subtitle_count")),
            "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        },
        "file_tree": rows[:120],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }


def _load_circle_overview_rows(circle_id: str, *, limit: int = 36) -> list[dict]:
    if not circle_id:
        return []
    try:
        from ..models.database import SessionLocal, CircleWork
        db = SessionLocal()
        try:
            rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id)
                .all()
            )
            rows.sort(key=lambda row: (
                bool(getattr(row, "has_kikoeru", False)),
                not bool(getattr(row, "has_asmr_one", False)),
                str(getattr(row, "display_rjcode", "") or getattr(row, "canonical_rjcode", "") or ""),
            ))
            result = []
            for row in rows[:limit]:
                kikoeru = "已收录" if bool(row.has_kikoeru) else "未收录"
                dlsite = str(row.display_rjcode or row.canonical_rjcode or "").strip() if bool(row.has_dlsite) else "暂无来源"
                asmr_one = str(row.asmr_available_rjcode or row.display_rjcode or "").strip() if bool(row.has_asmr_one) else "暂无来源"
                status = "可下载" if (not bool(row.has_kikoeru) and bool(row.has_asmr_one)) else ("已满足" if bool(row.has_kikoeru) else "暂无来源")
                result.append({
                    "title": str(row.title or "").strip(),
                    "rjcode": str(row.display_rjcode or row.canonical_rjcode or "").strip(),
                    "kikoeru": kikoeru,
                    "dlsite": dlsite,
                    "asmr_one": asmr_one,
                    "status": status,
                })
            return result
        finally:
            db.close()
    except Exception:
        return []


def _normalize_file_tree(items: list, output_path: str) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        row = _normalize_tree_item(item, status="kept")
        if row:
            rows.append(row)
    if rows or not output_path:
        return rows
    if not os.path.isdir(output_path):
        return []
    base = output_path
    for root, dirs, files in os.walk(base):
        rel_root = os.path.relpath(root, base)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        if depth > 2:
            dirs[:] = []
            continue
        for name in files[:80]:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace("\\", "/")
            rows.append({
                "path": rel,
                "size": _safe_getsize(full),
                "size_text": _format_bytes(_safe_getsize(full)),
                "status": "kept",
            })
            if len(rows) >= 120:
                return rows
    return rows


def _normalize_tree_item(item, *, status: str) -> dict:
    if isinstance(item, dict):
        path = item.get("relative_path") or item.get("path") or item.get("name") or item.get("filename") or ""
        size = item.get("size") or item.get("size_bytes") or 0
        return {
            "path": str(path),
            "size": size,
            "size_text": item.get("size_text") or _format_bytes(size),
            "status": item.get("status") or status,
        }
    if isinstance(item, str):
        return {"path": item, "size_text": "", "status": status}
    return {}


def _count_files(items: list[dict]) -> int:
    return sum(1 for item in items if item and not item.get("children"))


def _sum_sizes(items: list[dict]) -> int:
    total = 0
    for item in items:
        try:
            total += int(item.get("size") or 0)
        except Exception:
            pass
    return total


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_getsize(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _count_files_on_disk(path: str) -> int:
    if not path or not os.path.isdir(path):
        return 0
    count = 0
    for _, _, files in os.walk(path):
        count += len(files)
    return count


def _sum_size_on_disk(path: str) -> int:
    if not path or not os.path.isdir(path):
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            total += _safe_getsize(os.path.join(root, name))
    return total


def _format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except Exception:
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def _format_duration(started_at, completed_at) -> str:
    if not started_at or not completed_at:
        return ""
    try:
        seconds = max(0, int((completed_at - started_at).total_seconds()))
    except Exception:
        return ""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {rest} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"
