"""按日期分批、可续跑的操作投影重建；发布前隔离全部新代际。"""
from datetime import datetime
import asyncio
import logging

from sqlalchemy import and_, exists, func, or_, select, text

from ..models.database import (
    ActivityLog, ActivityLogOperation as Operation, ActivityLogOperationEvent as Event,
    ActivityLogMetricFact as Fact, ActivityLogProjectionRepair as Repair,
    ActivityLogOperationMember as Member, ActivityLogOperationFile as File,
)
from .activity_operation_projection import GATE, _ensure_state, maintain_operations
from .activity_operation_normalizer import date_window


async def initialize_unpublished_projection():
    """启动时续建未发布投影；每批独立事务，完整核对后才切换。"""
    from ..models.database import SessionLocal
    from .activity_operation_projection import projection_state, publish_revision

    logger = logging.getLogger(__name__)

    def step():
        with SessionLocal() as db:
            state = projection_state(db)
            if state is not None and state.ready and state.building_generation is None:
                return {"done": True, "already_ready": True}
            if state is None or state.building_generation is None:
                begin_rebuild(db)
                db.commit()
            progress = rebuild_chunk(db, limit=500)
            db.commit()
            if progress["done"]:
                progress["report"] = publish_rebuild(db)
                db.commit()
                publish_revision()
            return progress

    try:
        while True:
            progress = await asyncio.to_thread(step)
            if progress.get("already_ready"):
                return
            logger.info("[操作投影重建] %s", progress)
            if progress["done"]:
                return
            await asyncio.sleep(0.1)
    except Exception:
        logger.exception("[操作投影重建] 未发布，保留检查点供重启续跑")


def _exclusive(db):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": GATE})


def begin_rebuild(db):
    """调用方提交后开始在线双写；已有构建代际原样续跑。"""
    _exclusive(db)
    state = _ensure_state(db)
    if state.building_generation is None:
        state.building_generation = max(state.active_generation, db.query(
            func.coalesce(func.max(Operation.generation), 0)).scalar()) + 1
        state.checkpoint = {"started_at": datetime.now().isoformat(), "processed": 0}
    db.flush()
    return state.building_generation


def rebuild_chunk(db, *, limit=500):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": "activity-operation-rebuild-worker"})
    db.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))"), {"key": GATE})
    state = _ensure_state(db)
    target = state.building_generation
    if target is None:
        raise ValueError("请先开始重建")
    checkpoint = dict(state.checkpoint or {})
    query = db.query(ActivityLog.id, ActivityLog.created_at)
    if checkpoint.get("at"):
        at = datetime.fromisoformat(checkpoint["at"])
        query = query.filter(or_(ActivityLog.created_at > at,
                                 and_(ActivityLog.created_at == at, ActivityLog.id > checkpoint["id"])))
    # 每批只跨一个自然日，便于限流与核对。
    rows = query.order_by(ActivityLog.created_at, ActivityLog.id).limit(max(1, min(2000, limit))).all()
    if rows:
        day = rows[0].created_at.date()
        rows = [row for row in rows if row.created_at.date() == day]
        maintain_operations(db, [{"id": row.id} for row in rows], generation=target)
        checkpoint.update(at=rows[-1].created_at.isoformat(), id=rows[-1].id,
                          processed=checkpoint.get("processed", 0) + len(rows))
        state.checkpoint = checkpoint
        db.flush()
    return {"generation": target, "processed": len(rows), "checkpoint": checkpoint, "done": not rows}


def differences(db, generation):
    """只读对账：原始事件覆盖、操作事件守恒、非负成员/指标。"""
    missing = db.query(func.count(ActivityLog.id)).filter(~exists(select(1).where(
        Event.generation == generation, Event.event_id == ActivityLog.id))).scalar()
    events = db.query(func.count(Event.event_id)).filter(Event.generation == generation).scalar()
    counted = db.query(func.coalesce(func.sum(Operation.event_count), 0)).filter(
        Operation.generation == generation).scalar()
    negative_facts = db.query(func.count()).select_from(Fact).filter(
        Fact.generation == generation, Fact.value < 0).scalar()
    malformed = sum(1 for counts, in db.query(Operation.counts).filter(Operation.generation == generation)
                    if any(value < 0 for value in counts.values()))
    orphan_events = db.query(func.count()).select_from(Event).filter(
        Event.generation == generation, ~exists(select(1).where(ActivityLog.id == Event.event_id))).scalar()
    orphan_projections = 0
    for model in (Event, Member, Fact, File):
        orphan_projections += db.query(func.count()).select_from(model).filter(
            model.generation == generation, ~exists(select(1).where(
                Operation.generation == generation, Operation.operation_id == model.operation_id))).scalar()
    bad_event_counts = db.query(func.count()).select_from(Operation).filter(
        Operation.generation == generation, Operation.event_count != select(func.count()).select_from(Event).where(
            Event.generation == generation, Event.operation_id == Operation.operation_id).scalar_subquery()).scalar()
    bad_member_counts = db.execute(text("""
        SELECT count(*) FROM activity_log_operations o
        WHERE o.generation = :generation AND o.counts <> COALESCE((
            SELECT jsonb_object_agg(m.status, m.n) FROM (
                SELECT status, count(*) AS n FROM activity_log_operation_members
                WHERE generation = o.generation AND operation_id = o.operation_id GROUP BY status
            ) m
        ), '{}'::jsonb)
    """), {"generation": generation}).scalar()
    orphan_sources = 0
    for model in (Fact, File):
        orphan_sources += db.query(func.count()).select_from(model).filter(
            model.generation == generation, ~exists(select(1).where(
                Event.generation == generation, Event.event_id == model.source_event_id,
                Event.operation_id == model.operation_id))).scalar()
    from .activity_operation_daily import contributions
    from ..models.database import ActivityLogOperationDaily as Daily
    expected_daily = contributions(db, generation)
    stored_daily = {tuple((row.date, row.category, row.status, row.kind, row.phase, row.metric)): row.value
                    for row in db.query(Daily).filter(Daily.generation == generation)}
    bad_daily = sum(expected_daily.get(key, 0) != stored_daily.get(key, 0)
                    for key in expected_daily.keys() | stored_daily.keys())
    return {"generation": generation, "missing_events": missing, "mapped_events": events,
            "operation_events": int(counted), "negative_facts": negative_facts,
            "negative_member_counts": malformed,
            "orphan_events": orphan_events, "orphan_projections": orphan_projections,
            "bad_event_counts": bad_event_counts, "bad_member_counts": bad_member_counts,
            "orphan_sources": orphan_sources,
            "bad_daily_buckets": bad_daily,
            "ok": missing == 0 and events == counted and not any((
                negative_facts, malformed, orphan_events, orphan_projections, bad_event_counts,
                bad_member_counts, orphan_sources, bad_daily))}


def reconciliation(db, generation, *, baseline_generation=None, start_date=None, end_date=None):
    """只读业务账单；日期仅约束报告，发布闸门始终核对全部原始事件。"""
    start, end = date_window(0, start_date, end_date)
    bounded = bool(start_date or end_date)

    def grouped(target):
        operations = db.query(func.date(Operation.initiated_at), Operation.category, Operation.status,
                              func.count(), func.sum(Operation.event_count)).filter(
                                  Operation.generation == target)
        facts = db.query(func.date(Fact.completed_at), Operation.category, Fact.phase, Fact.metric,
                         func.sum(Fact.value)).join(Operation, and_(
                             Operation.generation == Fact.generation,
                             Operation.operation_id == Fact.operation_id)).filter(Fact.generation == target)
        if start:
            operations = operations.filter(Operation.initiated_at >= start)
            facts = facts.filter(Fact.completed_at >= start)
        if bounded:
            operations = operations.filter(Operation.initiated_at < end)
            facts = facts.filter(Fact.completed_at < end)
        operation_rows = operations.group_by(
            func.date(Operation.initiated_at), Operation.category, Operation.status).all()
        fact_rows = facts.group_by(func.date(Fact.completed_at), Operation.category, Fact.phase, Fact.metric).all()
        return {
            ("operations", str(day), category, status, metric): int(value)
            for day, category, status, count, events in operation_rows
            for metric, value in (("operations", count), ("events", events))
        } | {
            ("metrics", str(day), category, phase, metric): int(value)
            for day, category, phase, metric, value in fact_rows
        }

    expected = grouped(generation)
    before = grouped(baseline_generation) if baseline_generation is not None else {}
    rows = [{"kind": key[0], "date": key[1], "category": key[2],
             "status" if key[0] == "operations" else "phase": key[3], "metric": key[4],
             "before": before.get(key, 0), "expected": expected.get(key, 0),
             "delta": expected.get(key, 0) - before.get(key, 0)}
            for key in sorted(before.keys() | expected.keys())]
    raw = db.query(func.date(ActivityLog.created_at), ActivityLog.category, ActivityLog.status,
                   func.count()).group_by(
                       func.date(ActivityLog.created_at), ActivityLog.category, ActivityLog.status)
    if start:
        raw = raw.filter(ActivityLog.created_at >= start)
    if bounded:
        raw = raw.filter(ActivityLog.created_at < end)
    return {"generation": generation, "baseline_generation": baseline_generation,
            "window": {"start": start.isoformat() if start else None,
                       "end_exclusive": end.isoformat() if bounded else None, "timezone": "Asia/Shanghai"},
            "date_basis": {"operations": "initiated_at", "metrics": "completed_at", "raw_events": "created_at"},
            "buckets": rows, "changed_buckets": sum(row["delta"] != 0 for row in rows),
            "raw_events": [{"date": str(day), "category": category, "status": status, "count": count}
                           for day, category, status, count in raw.order_by(
                               func.date(ActivityLog.created_at), ActivityLog.category, ActivityLog.status)]}


def publish_rebuild(db):
    """独占写入门闩内核对并切换，调用方提交才对外可见。"""
    _exclusive(db)
    state = _ensure_state(db)
    if state.building_generation is None:
        raise ValueError("没有待发布代际")
    repairs = [key for key, in db.query(Repair.event_id).filter(Repair.component == "operations")]
    if repairs:
        # 标记可能来自检查点之后的失败回写，映射存在并不代表派生值已经更新。
        target = state.building_generation
        affected = {key for key, in db.query(Event.operation_id).filter(
            Event.generation == target, Event.event_id.in_(repairs))}
        replay = set(repairs) | {key for key, in db.query(Event.event_id).filter(
            Event.generation == target, Event.operation_id.in_(affected))}
        maintain_operations(db, [{"id": key} for key in replay], generation=target, force=True)
    report = differences(db, state.building_generation)
    if not report["ok"]:
        raise ValueError(f"操作投影尚未完成核对: {report}")
    # 已可靠回放的操作派生错误可以清除；日账错误须由日账重建单独处理。
    db.query(Repair).filter(Repair.component == "operations", exists(select(1).where(
        Event.generation == state.building_generation, Event.event_id == Repair.event_id))).delete(
            synchronize_session=False)
    if db.query(Repair.event_id).first():
        raise ValueError("仍有未修复的派生维护异常")
    state.active_generation, state.building_generation = state.building_generation, None
    state.ready = True
    state.revision += 1
    db.flush()
    return report
