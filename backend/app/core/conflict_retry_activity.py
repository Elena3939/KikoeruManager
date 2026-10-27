"""问题作品重试的批次身份，以及对原导入成员的结果回写。"""
from datetime import datetime


def retry_origin(db, engine, conflict):
    from ..models.database import ActivityLog, Task as TaskRecord

    metadata = dict(conflict.new_metadata or {})
    if metadata.get("retry_origin_task_id"):
        return {key: value for key, value in metadata.items() if key.startswith("retry_origin_")}
    task_id = str(conflict.task_id or "")
    get_task = getattr(engine, "get_task", None)
    task = get_task(task_id) if get_task and task_id else None
    if task is None and task_id:
        task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    task_metadata = dict(getattr(task, "task_metadata", None) or {})
    if task_metadata.get("retry_origin_task_id"):
        return {key: value for key, value in task_metadata.items() if key.startswith("retry_origin_")}
    metadata = {**metadata, **task_metadata}
    row = None
    if task_id:
        row = db.query(ActivityLog).filter(
            ActivityLog.task_id == task_id,
            ActivityLog.category.in_(("auto_import", "process_existing", "extract")),
            ActivityLog.action.in_(("task_finished", "task_finished_incomplete")),
        ).order_by(ActivityLog.created_at.desc()).first()
    detail = dict(getattr(row, "detail", None) or {})
    return {
        "retry_origin_task_id": task_id,
        "retry_origin_batch_id": getattr(row, "batch_id", None) or detail.get("batch_id") or metadata.get("batch_id"),
        "retry_origin_category": getattr(row, "category", None) or {
            "process_existing_folder": "process_existing", "extract": "extract",
        }.get(
            getattr(getattr(task, "type", None), "value", getattr(task, "type", None))
            or metadata.get("source_task_type"), "auto_import",
        ),
        "retry_origin_parent_task_id": detail.get("parent_task_id") or metadata.get("parent_task_id"),
        "retry_origin_started_at": detail.get("task_started_at"),
        "retry_origin_source_path": getattr(row, "source_path", None) or conflict.new_path,
    }


def log_retry_batch(batch_id, results):
    from .activity_log_service import CATEGORY_AUTO_IMPORT, write_activity_log

    created = [item for item in results if item.get("success") and not item.get("already_running")]
    failed_count = sum(not item.get("success") for item in results)
    if not created and not failed_count:
        return
    write_activity_log(
        category=CATEGORY_AUTO_IMPORT, action="batch_start", status="incomplete" if created else "failed",
        summary=f"{'批量重试作品' if len(results) > 1 else '重试作品'}，提交 {len(created)} 个",
        task_id=batch_id,
        detail={
            "mode": "conflict_retry_batch", "batch_id": batch_id, "session_id": batch_id,
            "requested_count": len(results), "created_count": len(created),
            "submission_failed_count": failed_count,
            "already_running_count": sum(bool(item.get("already_running")) for item in results),
            "source_page": "conflicts", "source_action": "conflict_retry",
            "source_label": "问题作品 / 重试作品",
            "created_tasks": [{"task_id": item["task_id"], "conflict_id": item["conflict_id"]} for item in created],
            "submission_failures": [
                {"conflict_id": item["conflict_id"], "message": item.get("message")}
                for item in results if not item.get("success")
            ],
        },
    )


def log_retry_queued(task):
    """重试开始就让原成员进入未完成态，终态仍由生命周期日志结算。"""
    from .activity_log_service import write_activity_log

    meta = task.task_metadata or {}
    if not meta.get("retry_origin_task_id") or not meta.get("retry_origin_batch_id"):
        return
    write_activity_log(
        category=meta["retry_origin_category"], action="task_finished_incomplete",
        status="incomplete", summary="问题作品已提交重试，等待执行结果",
        task_id=meta["retry_origin_task_id"], source_path=meta.get("retry_origin_source_path"),
        created_at=task.created_at,
        detail={
            "batch_id": meta["retry_origin_batch_id"], "session_id": meta["retry_origin_batch_id"],
            "parent_task_id": meta.get("retry_origin_parent_task_id"),
            "retry_projection": True, "retry_task_id": task.id,
            "retry_batch_id": meta["retry_batch_id"], "conflict_resolution_action": "RETRY",
            "task_started_at": meta.get("retry_origin_started_at"),
        },
    )


def sync_retry_parent(db, payloads):
    """与结果写入共用事务，锁住父行防止同批次并发收尾覆盖汇总。"""
    from ..models.database import ActivityLog
    from .activity_log_batch_list import compact_import_rows, import_batch_key
    from .activity_log_aggregator import merge_activity_rows_from_dicts

    keys = sorted({
        (item["category"], item["batch_id"])
        for item in payloads
        if item.get("batch_id") and (
            (item.get("detail") or {}).get("retry_projection") or item.get("action") == "batch_start"
        )
    })
    for category, batch_id in keys:
        parent = db.query(ActivityLog).filter(
            ActivityLog.category == category, ActivityLog.action == "batch_start",
            import_batch_key() == batch_id,
        ).with_for_update().first()
        if parent is None:
            continue
        db.flush()
        rows = compact_import_rows(db, (ActivityLog.category == category) & (import_batch_key() == batch_id))
        if not any((row.get("detail") or {}).get("retry_projection") for row in rows):
            continue
        for row in rows:
            if row["id"] == parent.id:
                row["detail"]["retry_updated_at"] = datetime.now().isoformat()
        merged = merge_activity_rows_from_dicts(rows)
        root = next((row for row in merged if row["id"] == parent.id), None)
        if root is None:
            continue
        detail = dict(parent.detail or {})
        detail.update({
            "retry_updated_at": datetime.now().isoformat(),
            "retry_result_status": root["status"],
            "latest_activity_at": root.get("latest_activity_at"),
            "batch_duration_ms": root["detail"].get("batch_duration_ms"),
        })
        # 新扫描协议只在扫描和投递均关闭后按重试结果重新结算。
        if detail.get("schema_version") == 2 and detail.get("producer_closed") and detail.get("scan_closed"):
            detail.setdefault("original_execution_status", detail.get("execution_status"))
            detail["execution_status"] = {
                "success": "success", "partial_success": "partial", "failed": "failed",
                "cancelled": "cancelled",
            }.get(root["status"], "running")
        parent.status = root["status"]
        parent.detail = detail
        # 提交后再失效，避免并发读把事务提交前的旧父行重新放回缓存。
        db.info["_activity_log_parent_changed"] = True
