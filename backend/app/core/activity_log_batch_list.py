"""操作历史在数据库按批次分页，当前页才读取紧凑统计字段。"""
from sqlalchemy import Integer, and_, case, cast, func, or_
from sqlalchemy.orm import aliased

from ..models.database import ActivityLog
from .activity_log_aggregator import merge_activity_rows_from_dicts
from .activity_log_lite import build_lite_item
from .activity_log_relations import IMPORT_CATEGORIES, IMPORT_RESULT_ACTIONS
from .activity_log_outcomes import sql_import_result_status


def import_batch_key():
    """只采用持久化的批次标识，不按时间或文件名猜测归属。"""
    return func.coalesce(
        func.nullif(ActivityLog.batch_id, ""),
        func.nullif(ActivityLog.detail.op("->>")("batch_id"), ""),
        func.nullif(ActivityLog.detail.op("->>")("session_id"), ""),
    )


def compact_import_rows(db, condition):
    keys = (
        "batch_id", "session_id", "created_count", "requested_count", "archive_count",
        "source_mode", "business_outcome", "conflict_resolution_action",
        "created_tasks", "source_paths", "source_action", "source_label", "source_page",
        "batch_source_action", "batch_source_label", "batch_source_page",
        "parent_task_id", "multi_rj_subtask_count", "duration_ms", "task_started_at",
        "task_completed_at", "extract_phase_duration_ms", "extract_execution_duration_ms", "archive_input", "archive_size_bytes", "extract_output_bytes",
        "filtered_count", "filtered_size", "mode", "success_count", "failed_count", "total_count",
        "deleted_file_count", "deleted_folder_count", "deleted_bytes", "unknown_size_count", "unknown_type_count", "delete_history_version",
        "retry_projection", "retry_batch_id", "retry_updated_at", "retry_result_status",
        "submission_failed_count", "already_running_count",
        "schema_version", "scan_id", "producer_closed", "scan_closed", "execution_status",
    )
    args = [arg for key in keys for arg in (key, ActivityLog.detail[key])]
    rows = db.query(
        ActivityLog.id, ActivityLog.category, ActivityLog.action, ActivityLog.status,
        ActivityLog.summary, ActivityLog.task_id, ActivityLog.source_path, ActivityLog.rjcode,
        ActivityLog.created_at, ActivityLog.batch_id, ActivityLog.session_key,
        func.json_build_object(*args).label("detail"),
    ).filter(condition).all()
    compact = [dict(row._mapping) for row in rows]
    for row in compact:
        row["detail"] = {key: value for key, value in row["detail"].items() if value is not None}
    return compact


def list_batch_lite(db, query, *, page, limit, status=None, searching=False):
    """搜索命中成员后回查完整批次；total、状态筛选和分页均以主记录为单位。"""
    batch_key = import_batch_key()
    multi_rj_child = and_(
        ActivityLog.category == "process_existing",
        ActivityLog.detail.op("->>")("source_action") == "multi_rj_extract_subtask",
    )
    is_batch = and_(ActivityLog.category.in_(IMPORT_CATEGORIES), batch_key.isnot(None), ~func.coalesce(multi_rj_child, False))
    kind = case((is_batch, "batch"), else_="row")
    delete_parent = aliased(ActivityLog)
    delete_parent_query = db.query(delete_parent.id).filter(
        delete_parent.category == "pipeline_delete", delete_parent.action == "batch_api_delete",
    ).order_by(delete_parent.created_at.desc(), delete_parent.id.desc()).correlate(ActivityLog)
    # 优先走 category + batch_id 索引；只有索引列缺失的旧数据才读 JSON 批次。
    indexed_parent_id = delete_parent_query.filter(delete_parent.batch_id == batch_key).limit(1).scalar_subquery()
    legacy_parent_id = delete_parent_query.filter(
        or_(delete_parent.batch_id.is_(None), delete_parent.batch_id == ""),
        delete_parent.detail.op("->>")("batch_id") == batch_key,
    ).limit(1).scalar_subquery()
    # 旧逐文件记录映射到真实批次摘要；搜索子文件也返回整个批次，不按时间猜归属。
    key = case((is_batch, batch_key),
               (and_(ActivityLog.category == "pipeline_delete", ActivityLog.action == "batch_delete_item"),
                func.coalesce(indexed_parent_id, legacy_parent_id, ActivityLog.id)), else_=ActivityLog.id)
    # 非结果旁路事件只属于审计明细，不产生另一条主记录。
    query = query.filter(or_(
        ~ActivityLog.category.in_(IMPORT_CATEGORIES),
        ActivityLog.action.in_((*IMPORT_RESULT_ACTIONS, "batch_start")),
    ))
    archive_parent = aliased(ActivityLog)
    has_archive_parent = db.query(archive_parent.id).filter(
        archive_parent.category == "auto_import",
        archive_parent.task_id == ActivityLog.detail.op("->>")("parent_task_id"),
        archive_parent.action.in_(IMPORT_RESULT_ACTIONS),
    ).exists()
    # 一包多 RJ 的目录处理是包内明细，不能成为另一条“压缩包批次”。
    query = query.filter(~and_(func.coalesce(multi_rj_child, False), has_archive_parent))
    candidates = query.with_entities(
        kind.label("kind"), ActivityLog.category.label("category"), key.label("key"),
    ).distinct().subquery()
    # 回查完整成员不沿用搜索、日期和单包状态条件，避免只汇总命中的半个批次。
    members = db.query(
        kind.label("kind"), ActivityLog.category.label("category"), key.label("key"),
        ActivityLog.id, ActivityLog.action, sql_import_result_status(ActivityLog).label("status"), ActivityLog.created_at,
        case((ActivityLog.action == "batch_start", cast(func.coalesce(
            ActivityLog.detail.op("->>")("created_count"), "0"), Integer)), else_=0).label("expected"),
        case((ActivityLog.action == "batch_start", cast(func.coalesce(
            ActivityLog.detail.op("->>")("submission_failed_count"), "0"), Integer)), else_=0).label("submission_failed"),
        case((or_(
            ActivityLog.detail.op("->>")("mode") == "conflict_retry_batch",
            ActivityLog.detail.op("->>")("retry_projection") == "true",
        ), 1), else_=0).label("retry_batch"),
        func.row_number().over(
            partition_by=(kind, ActivityLog.category, key, func.coalesce(ActivityLog.task_id, ActivityLog.id)),
            order_by=(ActivityLog.created_at.desc(), ActivityLog.id.desc()),
        ).label("attempt"),
    ).join(candidates, and_(
        candidates.c.kind == kind, candidates.c.category == ActivityLog.category, candidates.c.key == key,
    )).filter(or_(
        ~ActivityLog.category.in_(IMPORT_CATEGORIES),
        ActivityLog.action.in_((*IMPORT_RESULT_ACTIONS, "batch_start")),
    )).subquery()
    result = and_(members.c.action.in_(IMPORT_RESULT_ACTIONS), members.c.attempt == 1)
    count = func.count().filter(result)
    success = func.count().filter(and_(result, members.c.status.in_(("success", "completed"))))
    failed = func.count().filter(and_(result, members.c.status.in_(("failed", "error")))) + func.max(members.c.submission_failed)
    partial = func.count().filter(and_(result, members.c.status == "partial_success"))
    unfinished = func.count().filter(and_(result, ~members.c.status.in_(
        ("success", "completed", "failed", "error", "partial_success"))))
    batch_status = case(
        (and_(func.max(members.c.retry_batch) == 1,
              or_(count < func.max(members.c.expected), unfinished > 0)), "incomplete"),
        (and_(failed > 0, success > 0), "partial_success"),
        (failed > 0, "failed"), (partial > 0, "partial_success"),
        (or_(count == 0, count < func.max(members.c.expected), unfinished > 0), "incomplete"),
        else_="success",
    )
    groups = db.query(
        members.c.kind, members.c.category, members.c.key,
        func.max(members.c.created_at).label("latest"),
        case((members.c.kind == "batch", batch_status), else_=func.coalesce(
            func.max(members.c.status).filter(members.c.action == "batch_api_delete"),
            func.max(members.c.status))).label("status"),
    ).group_by(members.c.kind, members.c.category, members.c.key).subquery()
    # 无状态筛选时不需要对整张历史表按任务排序、计算状态；只做分组键和时间聚合。
    if not status:
        source = db.query(ActivityLog).join(candidates, and_(
            candidates.c.kind == kind, candidates.c.category == ActivityLog.category, candidates.c.key == key,
        )) if searching else query
        source = source.filter(or_(
            ~ActivityLog.category.in_(IMPORT_CATEGORIES),
            ActivityLog.action.in_((*IMPORT_RESULT_ACTIONS, "batch_start")),
        ))
        groups = source.with_entities(
            kind.label("kind"), ActivityLog.category.label("category"), key.label("key"),
            func.max(ActivityLog.created_at).label("latest"),
        ).group_by(kind, ActivityLog.category, key).subquery()
    grouped = db.query(groups)
    if status:
        grouped = grouped.filter(groups.c.status == status)
    total = grouped.count()
    selected = grouped.order_by(groups.c.latest.desc(), groups.c.category, groups.c.key).offset(
        (page - 1) * limit).limit(limit).all()
    batch_keys = [(row.category, row.key) for row in selected if row.kind == "batch"]
    batch_items = {}
    if batch_keys:
        ids = list({bid for _, bid in batch_keys})
        compact = compact_import_rows(db, and_(
            ActivityLog.category.in_({cat for cat, _ in batch_keys}),
            or_(ActivityLog.batch_id.in_(ids), and_(
                or_(ActivityLog.batch_id.is_(None), ActivityLog.batch_id == ""), batch_key.in_(ids),
            )),
        ))
        # 每个批次单独合并，避免跨批次恢复标记、路径关联影响当前批次统计。
        buckets = {}
        for row in compact:
            detail = row.get("detail") or {}
            bid = row.get("batch_id") or detail.get("batch_id") or detail.get("session_id")
            buckets.setdefault((row["category"], bid), []).append(row)
        for group_key, rows in buckets.items():
            merged = merge_activity_rows_from_dicts(rows)
            root = next((row for row in merged if row.get("action") == "batch_start"), None)
            if root is None:
                root = next((row for row in merged if row.get("task_id") == group_key[1]), None)
            if root is not None:
                root["source_path"] = None
                root["rjcode"] = None
                batch_items[group_key] = build_lite_item(root)
    compact_categories = {*IMPORT_CATEGORIES, "pipeline_delete"}
    import_row_ids = [row.key for row in selected if row.kind == "row" and row.category in compact_categories]
    other_row_ids = [row.key for row in selected if row.kind == "row" and row.category not in compact_categories]
    individual = {}
    if import_row_ids:
        individual.update({row["id"]: build_lite_item(row) for row in compact_import_rows(
            db, ActivityLog.id.in_(import_row_ids),
        )})
    if other_row_ids:
        individual.update({row.id: build_lite_item(row.to_dict()) for row in db.query(ActivityLog).filter(
            ActivityLog.id.in_(other_row_ids),
        ).all()})
    items = []
    for group in selected:
        item = batch_items.get((group.category, group.key)) if group.kind == "batch" else individual.get(group.key)
        if item is not None:
            item["latest_activity_at"] = group.latest.isoformat() if group.latest else item.get("created_at")
            items.append(item)
    return {"total": total, "page": page, "limit": limit, "items": items}


def synthetic_batch_detail(db, log_id):
    """历史记录没有 batch_start 时，稳定的虚拟批次标识也能打开详情。"""
    parts = log_id.split(":", 2)
    if len(parts) != 3:
        return None
    prefix, category, batch_id = parts
    if prefix != "synthetic-import-batch" or category not in IMPORT_CATEGORIES or not batch_id:
        return None
    rows = db.query(ActivityLog).filter(
        ActivityLog.category == category, import_batch_key() == batch_id,
    ).order_by(ActivityLog.created_at, ActivityLog.id).all()
    merged = merge_activity_rows_from_dicts([row.to_dict() for row in rows])
    return next((row for row in merged if row.get("id") == log_id), None)
