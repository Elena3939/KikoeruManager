"""审计操作、执行、事件和工作量的共享归一化。只接受明确身份关系。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from typing import Any

BEIJING = timezone(timedelta(hours=8))
IMPORTS = {"auto_import", "process_existing", "extract"}
TERMINAL = {"success", "failed", "cancelled", "partial_success"}
ALIASES = {"completed": "success", "error": "failed", "canceled": "cancelled",
           "waiting_manual": "waiting", "waiting_retry": "waiting", "partial": "partial_success"}
ROOT_ACTIONS = {"batch_start", "batch_api_delete", "batch_api_rename", "batch_manual_rename"}
RESULT_BATCH_ACTIONS = {"batch_api_delete", "batch_api_rename", "batch_manual_rename"}
SESSION_TERMINALS = {"session_completed", "session_partial_failed", "task_finished",
                     "task_finished_incomplete", "task_failed", "task_cancelled"}


def digest(*parts: Any) -> str:
    import json
    return sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":"), default=str).encode()).hexdigest()


def local_datetime(value: Any) -> datetime:
    """历史无时区字段按北京时间解释；有偏移的时间转换后落库为 naive 北京时间。"""
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.astimezone(BEIJING).replace(tzinfo=None) if result.tzinfo else result


def date_window(days=14, start_date=None, end_date=None, *, now=None):
    today = (now or datetime.now(BEIJING)).astimezone(BEIJING).date()
    last = date.fromisoformat(str(end_date)) if end_date else today
    first = date.fromisoformat(str(start_date)) if start_date else (
        last - timedelta(days=max(1, min(int(days), 90)) - 1) if int(days) > 0 else None)
    if first and first > last:
        raise ValueError("开始日期不能晚于结束日期")
    return (datetime.combine(first, time.min) if first else None,
            datetime.combine(last + timedelta(days=1), time.min))


def first_known(*values):
    return next((value for value in values if value is not None), None)


def nonnegative(value):
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return None


def event_identity(row):
    if row.get("_operation_identity"):
        return row["_operation_identity"]
    detail = row.get("detail") or {}
    category = row["category"]
    if detail.get("operation_id"):
        return category, "explicit", str(detail["operation_id"])
    # 批次内任务、阶段归属批次，用户发起的重试使用新的 retry_batch_id。
    batch = row.get("batch_id") or detail.get("batch_id")
    session = row.get("session_key") or detail.get("session_key") or detail.get("session_id")
    if batch and (category in IMPORTS or not session):
        return category, "batch", str(batch)
    if session:
        return category, "session", str(session)
    if row.get("task_id"):
        return category, "task", str(row["task_id"])
    if row.get("parent_id") or detail.get("parent_id"):
        return category, "event", str(row.get("parent_id") or detail["parent_id"])
    return category, "event", row["id"]


def _result_member(category, identity, item, fallback):
    path = first_known(item.get("old_path"), item.get("source_path"), item.get("path"),
                       item.get("rename_key"), item.get("delete_key"))
    return digest(category, identity, "item", item.get("library_id"), path) if path else digest(
        category, identity, "result", fallback)


def normalize_event(row):
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    row = {**row, "detail": detail}
    category, kind, identity = event_identity(row)
    operation_id = digest(category, kind, identity)
    action = row.get("action") or ""
    status = ALIASES.get(row.get("status"), row.get("status")) or "incomplete"
    original_status = ALIASES.get(detail.get("original_execution_status"), detail.get("original_execution_status"))
    retry_repaired = bool(detail.get("retry_completed") and detail.get("retry_status") == "success")
    if retry_repaired:
        original_status = original_status or status
        status = "success"
    event_at = local_datetime(row["created_at"])
    initiated = first_known(detail.get("operation_started_at"), detail.get("task_started_at"),
                            detail.get("started_at"), event_at)
    try:
        initiated = min(local_datetime(initiated), event_at)
    except (ValueError, TypeError):
        initiated = event_at
    projection = bool(detail.get("retry_projection"))
    attempt = first_known(detail.get("attempt_id"), detail.get("execution_id"), detail.get("attempt_no"), 0)
    execution_id = digest(operation_id, identity if kind == "session" else row.get("task_id") or identity, attempt)
    is_root = action in ROOT_ACTIONS
    # 文件成功、计划生成不意味着任务成功。只有生命周期或独立业务结果能改变成员结果。
    file_event = action in {"resource_downloaded", "resource_uploaded", "resource_verify_failed"}
    state_event = not file_event and (
        kind in {"event", "explicit"} or is_root or action in SESSION_TERMINALS
        or action in {"extract_archive", "process_folder", "manual_complete", "complete", "task_retried"}
        or not (kind in {"batch", "session"} and action.endswith(("_queued", "_started", "_created")))
    )
    if action == "session_started":
        state_event, status = True, "processing"
    elif action == "task_retried":
        state_event, status = True, "pending"
    elif action == "task_paused":
        state_event, status = True, "paused"
    elif action == "task_resumed":
        state_event, status = True, "processing"
    if category == "asmr_sync" and kind == "session" and action not in SESSION_TERMINALS | {"session_started", "task_paused", "task_resumed", "task_retried"}:
        state_event = False
    if projection:
        member_identity = detail.get("original_task_id") or row.get("task_id") or row["id"]
    else:
        member_identity = row.get("task_id") or identity
    member_id = digest(category, identity if kind == "session" else member_identity)
    result_members = []
    result_identity_missing = False
    if kind == "batch" and category in {"pipeline_delete", "pipeline_rename"}:
        member_id = _result_member(category, identity, {**detail, "source_path": first_known(
            detail.get("source_path"), row.get("source_path"))}, row["id"])
        # 批次摘要与逐项结果共享同一次执行，摘要只替换该阶段的完整指标。
        execution_id = digest(operation_id, "batch", attempt)
        if action in RESULT_BATCH_ACTIONS:
            for index, result in enumerate(detail.get("results") or []):
                if not isinstance(result, dict):
                    continue
                if not result.get("library_id"):
                    result_identity_missing = True
                    continue
                result_status = ALIASES.get(result.get("status"), result.get("status"))
                if result_status not in TERMINAL:
                    result_status = "success" if result.get("success") is True else (
                        "failed" if result.get("success") is False else "incomplete")
                result_members.append({
                    "member_id": _result_member(category, identity, result, f"{row['id']}:{index}"),
                    "status": result_status,
                })
    if is_root:
        member_id = None
    if status not in TERMINAL | {"pending", "processing", "waiting", "paused", "incomplete"}:
        status = "incomplete"

    metrics = []
    files = []
    integrity = []
    if result_identity_missing:
        integrity.append("member_identity_missing")
    if kind == "event" and not row.get("parent_id"):
        integrity.append("identity_missing")
    if detail.get("__compacted") or detail.get("_compacted") or detail.get("detail_compacted"):
        integrity.append("historical_detail_compacted")
    if not projection:
        for phase, count_key, bytes_key, files_key in (
            ("download", "success_count", "downloaded_bytes", "download_files"),
            ("upload", "uploaded_count", "uploaded_bytes", "uploaded_files"),
        ):
            duration_key = f"{phase}_duration_ms"
            if phase == "upload" and detail.get("upload_mode") == "local":
                phase = "local_import"
            manifest = detail.get(files_key)
            phase_present = bytes_key in detail or files_key in detail or (
                count_key == "uploaded_count" and count_key in detail)
            if not phase_present:
                continue
            manifest = manifest if isinstance(manifest, list) else None
            count = nonnegative(detail.get(count_key))
            byte_count = nonnegative(detail.get(bytes_key))
            authority = 2
            if manifest is not None:
                successful = []
                identities = set()
                for item in manifest:
                    if isinstance(item, dict):
                        files.append((phase, item))
                        if item.get("status") in {"failed", "error", "cancelled", "canceled", "pending", "downloading", "uploading"}:
                            continue
                        path = first_known(item.get("relative_path"), item.get("path"), item.get("name"))
                        key = (item.get("library_id"), path)
                        if path and key not in identities:
                            identities.add(key)
                            successful.append(item)
                # 截断的旧清单不能替换完整摘要，也不能把未知大小当 0。
                complete = (count is None or count == len(successful)) and all(
                    isinstance(item, dict) and any(item.get(key) for key in ("relative_path", "path", "name"))
                    for item in manifest)
                if complete:
                    count = len(successful)
                    sizes = [nonnegative(first_known(item.get("size_bytes"), item.get("size")))
                             for item in successful]
                    if all(v is not None for v in sizes):
                        byte_count = sum(sizes)
                    authority = 3
                else:
                    integrity.append(f"{phase}_manifest_incomplete")
            for metric, value in (("files", count), ("bytes", byte_count)):
                if value is not None:
                    metrics.append((phase, metric, value, authority))
            # 多阶段任务只使用明确的阶段耗时；单阶段任务可使用总耗时。
            duration = detail.get(duration_key)
            other_phase = "uploaded_bytes" if phase == "download" else "downloaded_bytes"
            if duration is None and other_phase not in detail:
                duration = detail.get("duration_ms")
            duration = nonnegative(duration)
            if duration is not None:
                metrics.append((phase, "duration_ms", duration, authority))
        if file_event and action != "resource_verify_failed":
            phase = "download" if action == "resource_downloaded" else "upload"
            if phase == "upload" and detail.get("upload_mode") == "local":
                phase = "local_import"
            item = {"name": detail.get("resource_name"), "relative_path": detail.get("resource_path"),
                    "size_bytes": nonnegative(detail.get("size_bytes")), "status": status,
                    "library_id": detail.get("library_id")}
            if item["relative_path"] or item["name"]:
                files.append((phase, item))
            metrics.append((phase, "files", 1, 1))
            if item["size_bytes"] is not None:
                metrics.append((phase, "bytes", item["size_bytes"], 1))
        if category in IMPORTS and not is_root and state_event and status in TERMINAL:
            if detail.get("extract_performed") or category == "extract":
                for metric, key in (("archive_bytes", "archive_size_bytes"), ("output_bytes", "extract_output_bytes"),
                                    ("duration_ms", "extract_execution_duration_ms")):
                    value = nonnegative(first_known(detail.get(key), (
                        detail.get({"output_bytes": "output_size_bytes", "duration_ms": "duration_ms"}.get(metric))
                        if category == "extract" else None)))
                    if value is not None:
                        metrics.append(("extract", metric, value, 2))
                metrics.append(("extract", "executions", 1, 2))
        if category in {"subtitle_crawl", "subtitle_pair", "subtitle_import"} and not is_root:
            for key in ("applied_pairs", "deleted_subtitles", "imported_count", "downloaded_count"):
                value = nonnegative(detail.get(key))
                if value is not None:
                    metrics.append(("subtitle", key, value, 2))
        if (category in {"pipeline_delete", "pipeline_rename"} or
                category == "pipeline_filter" and action == "filter_delete_apply") and status in TERMINAL:
            phase = "rename" if category == "pipeline_rename" else "delete"
            value = nonnegative(first_known(detail.get("success_count"), detail.get("deleted_count")))
            if value is not None:
                metrics.append((phase, "items", value, 2))
            if phase == "delete":
                for metric, key in (("files", "deleted_file_count"), ("folders", "deleted_folder_count"),
                                    ("bytes", "deleted_bytes"), ("unknown_size_count", "unknown_size_count"),
                                    ("unknown_type_count", "unknown_type_count")):
                    value = nonnegative(detail.get(key))
                    if value is not None:
                        metrics.append((phase, metric, value, 2))
            entries = first_known(detail.get("deleted_items"), detail.get("results"))
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    path = first_known(entry.get("old_path"), entry.get("source_path"), entry.get("path"))
                    if path:
                        files.append((phase, {**entry, "path": path,
                            "status": entry.get("status") or (
                                "success" if entry.get("success") is True else
                                "failed" if entry.get("success") is False else "incomplete")}))
    compact = {key: detail[key] for key in (
        "schema_version", "producer_closed", "scan_closed", "created_count", "submitted_count",
        "expected_count", "total_count", "requested_count", "discovered_count", "skipped_count", "skipped_total",
        "success_count", "failed_count",
        "error", "error_message", "failed_reason", "retry_task_id", "retry_batch_id", "retry_operation_id",
        "original_execution_status", "execution_status", "upload_mode", "source_action", "retry_projection",
        "target_path", "target_library_id", "source_library_id",
    ) if key in detail}
    try:
        completed_at = local_datetime(first_known(detail.get("task_completed_at"), event_at))
    except (TypeError, ValueError):
        completed_at = event_at
        integrity.append("completion_time_invalid")
    return {
        "operation_id": operation_id, "category": category, "identity_kind": kind, "identity_value": identity,
        "event_id": row["id"], "event_at": event_at, "initiated_at": initiated,
        "member_id": member_id if state_event else None, "status": status,
        "result_members": result_members,
        "original_status": original_status, "retry_repaired": retry_repaired,
        "execution_id": execution_id, "projection": projection, "root": is_root,
        "completed_at": completed_at,
        "presentation": {"id": row["id"], "category": category, "action": action,
                         "summary": row.get("summary") or "", "rjcode": row.get("rjcode"),
                         "source_path": row.get("source_path"), "task_id": row.get("task_id"),
                         "batch_id": row.get("batch_id"), "session_key": row.get("session_key"),
                         "detail": compact},
        "metrics": metrics, "files": files, "integrity": integrity,
    }


def operation_status(counts, root_detail, root_status=None):
    members = sum(counts.values())
    expected = first_known(root_detail.get("submitted_count"), root_detail.get("created_count"),
                           root_detail.get("expected_count"), root_detail.get("total_count"))
    expected = nonnegative(expected)
    closed = root_detail.get("scan_closed") is True and root_detail.get("producer_closed") is True
    if counts.get("waiting", 0):
        return "waiting"
    if root_detail.get("schema_version") == 2 and (not closed or (expected is not None and members != expected)):
        return "incomplete"
    if counts.get("processing", 0):
        return "processing"
    if counts.get("pending", 0) or counts.get("paused", 0):
        present = {key for key, value in counts.items() if value}
        return next(iter(present)) if len(present) == 1 else "processing"
    if counts.get("incomplete", 0) or (expected is not None and members != expected):
        return "incomplete"
    present = {key for key, value in counts.items() if value}
    if not present:
        return root_status or ("success" if closed and expected == 0 else "incomplete")
    if present == {"success"}:
        return "success"
    if present == {"failed"}:
        return "failed"
    if present == {"cancelled"}:
        return "cancelled"
    return "partial_success"
