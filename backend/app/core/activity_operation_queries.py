"""操作投影读路径；筛选、列表和统计共享同一个操作集合。"""
from __future__ import annotations

import base64
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, or_, select

from ..models.database import (
    ActivityLog, ActivityLogMetricFact as Fact, ActivityLogOperation as Operation,
    ActivityLogOperationEvent as Event, ActivityLogOperationFile as File,
    ActivityLogProjectionRepair as Repair, ActivityLogProjectionState as State,
)
from .activity_operation_normalizer import date_window, local_datetime


def active_generation(db):
    state = db.get(State, 1)
    if state is None or not state.ready:
        return None
    if db.query(Repair.event_id).first():
        raise HTTPException(503, "操作统计正在核对，请稍后重试")
    return state.active_generation


def filters(db, generation, *, category=None, status=None, q=None, days=0,
            start_date=None, end_date=None, batch_id=None, session_key=None):
    query = db.query(Operation).filter(Operation.generation == generation)
    if category:
        query = query.filter(Operation.category == category)
    if status:
        query = query.filter(Operation.status == status)
    try:
        start, end = date_window(days, start_date, end_date)
    except (ValueError, TypeError):
        raise HTTPException(400, "日期范围无效")
    if start:
        query = query.filter(Operation.initiated_at >= start)
    if days or start_date or end_date:
        query = query.filter(Operation.initiated_at < end)
    if batch_id:
        query = query.filter(Operation.identity_kind == "batch", Operation.identity_value == batch_id)
    if session_key:
        query = query.filter(Operation.identity_kind == "session", Operation.identity_value == session_key)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        match = exists(select(1).select_from(Event).join(ActivityLog, ActivityLog.id == Event.event_id).where(
            Event.generation == generation, Event.operation_id == Operation.operation_id,
            ActivityLog.searchable_text.ilike(f"%{escaped}%", escape="\\")))
        query = query.filter(match)
    return query


def _missing_duration():
    duration = Fact.__table__.alias("phase_duration")
    known = exists(select(1).where(
        duration.c.generation == Fact.generation,
        duration.c.operation_id == Fact.operation_id,
        duration.c.execution_id == Fact.execution_id,
        duration.c.phase == Fact.phase,
        duration.c.metric == "duration_ms", duration.c.value > 0))
    return func.sum(case((and_(Fact.metric == "bytes", Fact.value > 0, ~known), 1), else_=0)).label("missing_duration")


def _speed(values, missing_duration):
    elapsed = values.get("duration_ms")
    values["average_speed_bytes"] = (
        values["bytes"] * 1000 / elapsed
        if not missing_duration and elapsed and "bytes" in values else None)


def rows_payload(operations, facts=()):
    from .activity_log_service import CATEGORY_LABELS
    metrics, missing_durations = {}, set()
    for fact in facts:
        key = (fact.operation_id, fact.phase)
        bucket = metrics.setdefault(fact.operation_id, {}).setdefault(fact.phase, {})
        bucket[fact.metric] = bucket.get(fact.metric, 0) + fact.value
        if getattr(fact, "missing_duration", 0):
            missing_durations.add(key)
    result = []
    for op in operations:
        item = dict(op.presentation or {})
        detail = dict(item.get("detail") or {})
        phases = metrics.get(op.operation_id, {})
        for phase, values in phases.items():
            _speed(values, (op.operation_id, phase) in missing_durations)
        detail.update({"operation_counts": op.counts, "phase_metrics": phases,
                       "raw_status": op.original_status, "current_result": op.status,
                       "integrity": op.integrity, "event_count": op.event_count})
        item.update({
            "id": op.root_log_id or item.get("id"), "operation_id": op.operation_id,
            "revision": op.revision, "status": op.status, "current_result": op.status,
            "original_status": op.original_status, "category": op.category,
            "category_label": CATEGORY_LABELS.get(op.category, op.category),
            "created_at": op.initiated_at.isoformat(), "latest_activity_at": op.latest_activity_at.isoformat(),
            "integrity": op.integrity, "detail": detail, "chips": [],
        })
        for status, value in op.counts.items():
            label = {"success": "完成", "failed": "失败", "cancelled": "取消", "waiting": "待处理",
                     "incomplete": "未收齐", "processing": "执行中"}.get(status, status)
            item["chips"].append({"label": label, "value": str(value), "tone": "neutral"})
        result.append(item)
    return result


def list_operations(db, generation, *, page=1, limit=50, **kwargs):
    page, limit = max(1, page), min(200, max(1, limit))
    query = filters(db, generation, **kwargs)
    total = query.count()
    operations = query.order_by(Operation.latest_activity_at.desc(), Operation.operation_id.desc()).offset(
        (page - 1) * limit).limit(limit).all()
    ids = [op.operation_id for op in operations]
    # 数据库按页内操作批量聚合，不随成员数或操作数发 N+1。
    facts = db.query(Fact.operation_id, Fact.phase, Fact.metric, func.sum(Fact.value).label("value"), _missing_duration()).filter(
        Fact.generation == generation, Fact.operation_id.in_(ids)).group_by(
        Fact.operation_id, Fact.phase, Fact.metric).all() if ids else []
    return {"items": rows_payload(operations, facts), "total": total, "page": page, "limit": limit,
            "window": {"source": "activity_log_operations", "complete": True, "search_backend": "postgresql_pg_trgm"},
            "generation": generation}


def operation_stats(db, generation, *, days=14, **kwargs):
    from .activity_log_service import CATEGORY_LABELS
    if not any(kwargs.get(key) for key in ("q", "batch_id", "session_key")):
        # 空身份筛选不参与日汇总，也不能传入仅接受日期、分类和状态的查询。
        daily_filters = {key: value for key, value in kwargs.items()
                         if key not in {"q", "batch_id", "session_key"}}
        return _daily_stats(db, generation, days=days, **daily_filters)
    query = filters(db, generation, days=days, **kwargs)
    source = query.order_by(None).subquery()
    counts = db.query(source.c.category, source.c.status, func.count().label("count")).group_by(
        source.c.category, source.c.status).all()
    by_category, by_status = {}, {}
    for category, status, count in counts:
        by_category[category] = by_category.get(category, 0) + count
        by_status[status] = by_status.get(status, 0) + count
    by_day = db.query(func.date(source.c.initiated_at).label("date"), func.count().label("count")).group_by(
        func.date(source.c.initiated_at)).order_by(func.date(source.c.initiated_at)).all()
    start, end = date_window(days, kwargs.get("start_date"), kwargs.get("end_date"))
    # 工作量按完成日；身份筛选与操作集合相同，但不能受发起日期约束。
    identity_filters = {key: value for key, value in kwargs.items() if key not in {"start_date", "end_date"}}
    operation_ids = filters(db, generation, **identity_filters).with_entities(Operation.operation_id)
    metric_query = db.query(Fact.phase, Fact.metric, func.sum(Fact.value).label("value"), _missing_duration()).filter(
        Fact.generation == generation, Fact.operation_id.in_(operation_ids))
    if days or kwargs.get("start_date") or kwargs.get("end_date"):
        metric_query = metric_query.filter(Fact.completed_at < end)
    if start:
        metric_query = metric_query.filter(Fact.completed_at >= start)
    phase_metrics = {}
    missing_phases = set()
    for phase, metric, value, missing_duration in metric_query.group_by(Fact.phase, Fact.metric):
        phase_metrics.setdefault(phase, {})[metric] = int(value)
        if missing_duration:
            missing_phases.add(phase)
    for phase, values in phase_metrics.items():
        _speed(values, phase in missing_phases)
    total = sum(by_category.values())
    event_count = db.query(func.coalesce(func.sum(source.c.event_count), 0)).scalar()
    return {
        "days": days, "total_in_range": total, "operation_count": total, "event_count": int(event_count),
        "by_day": [{"date": str(day), "count": count} for day, count in by_day],
        "by_category": [{"category": key, "label": CATEGORY_LABELS.get(key, key), "count": count}
                        for key, count in sorted(by_category.items())],
        "by_status": by_status, "metrics": {"phases": phase_metrics},
        "date_basis": {"timezone": "Asia/Shanghai", "operations": "initiated_at", "metrics": "completed_at",
                       "start": start.isoformat() if start else None, "end_exclusive": end.isoformat()},
        "source": "activity_log_operations", "generation": generation,
    }


def _daily_stats(db, generation, *, days=14, category=None, status=None, start_date=None, end_date=None):
    from .activity_log_service import CATEGORY_LABELS
    from .activity_operation_daily import summary
    try:
        start, end = date_window(days, start_date, end_date)
    except (TypeError, ValueError):
        raise HTTPException(400, "日期范围无效")
    rows = summary(db, generation, category=category, status=status, start=start,
                   end=end if days or start_date or end_date else None)
    by_category, by_status, by_day, phases = {}, {}, {}, {}
    events, missing = 0, set()
    for row in rows:
        if row.kind == "operations":
            if row.metric == "events":
                events += row.value
            else:
                by_category[row.category] = by_category.get(row.category, 0) + row.value
                by_status[row.status] = by_status.get(row.status, 0) + row.value
                day = row.date.isoformat()
                by_day[day] = by_day.get(day, 0) + row.value
        elif row.kind == "presence":
            phases.setdefault(row.phase, {}).setdefault(row.metric, 0)
        elif row.metric == "missing_duration":
            if row.value:
                missing.add(row.phase)
        else:
            values = phases.setdefault(row.phase, {})
            values[row.metric] = values.get(row.metric, 0) + row.value
    for phase, values in phases.items():
        _speed(values, phase in missing)
    total = sum(by_category.values())
    return {
        "days": days, "total_in_range": total, "operation_count": total, "event_count": events,
        "by_day": [{"date": day, "count": value} for day, value in sorted(by_day.items())],
        "by_category": [{"category": key, "label": CATEGORY_LABELS.get(key, key), "count": value}
                        for key, value in sorted(by_category.items())],
        "by_status": by_status, "metrics": {"phases": phases},
        "date_basis": {"timezone": "Asia/Shanghai", "operations": "initiated_at", "metrics": "completed_at",
                       "start": start.isoformat() if start else None, "end_exclusive": end.isoformat()},
        "source": "activity_log_operations", "generation": generation,
    }


def resolve_operation(db, generation, log_id):
    operation = db.get(Operation, (generation, log_id))
    if operation is None:
        event = db.get(Event, (generation, log_id))
        operation = db.get(Operation, (generation, event.operation_id)) if event else None
    if operation is None:
        raise HTTPException(404, "未找到对应操作")
    return operation


def encode_cursor(payload):
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(value, *, operation_id, generation, kind):
    if not value:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "==="))
        if payload["operation"] != operation_id or payload["generation"] != generation or payload["kind"] != kind:
            raise ValueError()
        if kind == "events":
            at = local_datetime(payload["at"])
            if not isinstance(payload["id"], str) or not payload["id"]:
                raise ValueError()
            payload["at"] = at.isoformat()
        elif (not isinstance(payload["key"], list) or len(payload["key"]) != 3
              or not all(isinstance(part, str) and part for part in payload["key"])):
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        raise HTTPException(400, "分页游标无效或历史版本已经切换，请刷新")


def operation_children(db, generation, log_id, *, limit=100, cursor=None):
    operation = resolve_operation(db, generation, log_id)
    limit = max(1, min(100, limit))
    query = db.query(Event).filter_by(generation=generation, operation_id=operation.operation_id)
    total = query.count()
    payload = decode_cursor(cursor, operation_id=operation.operation_id, generation=generation, kind="events")
    if payload:
        query = query.filter(or_(Event.event_at < local_datetime(payload["at"]),
                                and_(Event.event_at == local_datetime(payload["at"]), Event.event_id < payload["id"])))
    events = query.order_by(Event.event_at.desc(), Event.event_id.desc()).limit(limit + 1).all()
    page, more = events[:limit], len(events) > limit
    rows = _short_events(db, [event.event_id for event in page]) if page else {}
    last = page[-1] if page else None
    return {"parent": rows_payload([operation])[0], "items": [rows[event.event_id] for event in page if event.event_id in rows],
            "total": total, "has_more": more, "next_cursor": encode_cursor({
                "operation": operation.operation_id, "generation": generation, "kind": "events",
                "at": last.event_at.isoformat(), "id": last.event_id}) if more else None}


def operation_files(db, generation, log_id, *, phase=None, limit=100, cursor=None):
    operation = resolve_operation(db, generation, log_id)
    limit = max(1, min(100, limit))
    query = db.query(File).filter_by(generation=generation, operation_id=operation.operation_id)
    if phase:
        query = query.filter(File.phase == phase)
    total = query.count()
    kind = f"files:{phase or 'all'}"
    payload = decode_cursor(cursor, operation_id=operation.operation_id, generation=generation, kind=kind)
    if payload:
        from sqlalchemy import tuple_
        query = query.filter(tuple_(File.phase, File.file_id, File.execution_id) > tuple(payload["key"]))
    values = query.order_by(File.phase, File.file_id, File.execution_id).limit(limit + 1).all()
    page, more = values[:limit], len(values) > limit
    last = page[-1] if page else None
    return {"items": [{**row.payload, "phase": row.phase, "execution_id": row.execution_id} for row in page],
            "total": total, "has_more": more, "integrity": operation.integrity,
            "next_cursor": encode_cursor({"operation": operation.operation_id, "generation": generation,
                                         "kind": kind, "key": [last.phase, last.file_id, last.execution_id]}) if more else None}


def operation_detail(db, generation, log_id):
    operation = resolve_operation(db, generation, log_id)
    facts = db.query(Fact.operation_id, Fact.phase, Fact.metric, func.sum(Fact.value).label("value"), _missing_duration()).filter(
        Fact.generation == generation, Fact.operation_id == operation.operation_id).group_by(
        Fact.operation_id, Fact.phase, Fact.metric).all()
    item = rows_payload([operation], facts)[0]
    files = operation_files(db, generation, log_id)
    children = operation_children(db, generation, log_id)
    item["detail"].update({"child_rows": children["items"], "children_page": {key: value for key, value in children.items()
                                                                          if key not in {"parent", "items"}},
                           "files_page": files, "raw_detail_available": True})
    return {"row": item}


def _short_events(db, ids):
    """在 SQL 中裁掉大清单，避免分页先下载并反序列化整段 JSON。"""
    columns = [column for column in ActivityLog.__table__.columns
               if column.name not in {"detail", "searchable_text", "event_key"}]
    detail_keys = ("error", "error_message", "failed_reason", "retry_task_id",
                   "retry_batch_id", "retry_operation_id", "original_execution_status",
                   "retry_projection")
    fields = [part for key in detail_keys for part in (key, ActivityLog.detail[key])]
    detail = func.json_build_object(*fields).label("detail")
    result = {}
    for row in db.query(*columns, detail).filter(ActivityLog.id.in_(ids)):
        item = dict(row._mapping)
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
        item["detail"] = {key: value for key, value in (item["detail"] or {}).items()
                          if value is not None and not isinstance(value, (list, dict))}
        item["detail"]["raw_detail_available"] = True
        result[item["id"]] = item
    return result
