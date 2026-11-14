"""受影响操作的日账差额；与原始记录和操作投影共享事务。"""
from collections import Counter

from sqlalchemy import and_, exists, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import insert

from ..models.database import (
    ActivityLogOperation as Operation, ActivityLogMetricFact as Fact,
    ActivityLogOperationDaily as Daily,
)

TRACKER = "activity_operation_daily_tracker"


def contributions(db, generation, operation_ids=None):
    """一次 SQL 聚合紧凑投影，不读取历史 JSON。"""
    op_filter = [Operation.generation == generation]
    fact_filter = [Fact.generation == generation]
    if operation_ids is not None:
        op_filter.append(Operation.operation_id.in_(operation_ids))
        fact_filter.append(Fact.operation_id.in_(operation_ids))
    dims = [func.date(Operation.initiated_at), Operation.category, Operation.status]
    op_counts = select(*dims, literal("operations"), literal(""), literal("operations"),
                       func.count()).where(*op_filter).group_by(*dims)
    event_counts = select(*dims, literal("operations"), literal(""), literal("events"),
                          func.sum(Operation.event_count)).where(*op_filter).group_by(*dims)
    fact_dims = [func.date(Fact.completed_at), Operation.category, Operation.status, Fact.phase]
    join = and_(Operation.generation == Fact.generation, Operation.operation_id == Fact.operation_id)
    metrics = select(*fact_dims[:3], literal("metrics"), Fact.phase, Fact.metric,
                     func.sum(Fact.value)).join(Operation, join).where(*fact_filter).group_by(
                         *fact_dims, Fact.metric)
    presence = select(*fact_dims[:3], literal("presence"), Fact.phase, Fact.metric,
                      func.count()).join(Operation, join).where(*fact_filter).group_by(
                          *fact_dims, Fact.metric)
    duration = Fact.__table__.alias("daily_duration")
    known_duration = exists(select(1).where(
        duration.c.generation == Fact.generation, duration.c.execution_id == Fact.execution_id,
        duration.c.operation_id == Fact.operation_id, duration.c.phase == Fact.phase,
        duration.c.metric == "duration_ms", duration.c.value > 0))
    missing = select(*fact_dims[:3], literal("metrics"), Fact.phase, literal("missing_duration"),
                     func.count()).join(Operation, join).where(
                         *fact_filter, Fact.metric == "bytes", Fact.value > 0, ~known_duration
                     ).group_by(*fact_dims)
    return Counter({tuple(row[:-1]): int(row[-1]) for row in db.execute(
        union_all(op_counts, event_counts, metrics, presence, missing))})


def capture(db, generation, operation_ids):
    """调用方持有操作锁；嵌套重放只捕获每个操作最初的状态。"""
    tracker = db.info.get(TRACKER)
    if tracker is None:
        return
    item = tracker.setdefault(generation, {"ids": set(), "before": Counter()})
    new_ids = set(operation_ids) - item["ids"]
    if new_ids:
        item["before"].update(contributions(db, generation, new_ids))
        item["ids"].update(new_ids)


def finish(db):
    db.flush()
    for generation, item in db.info[TRACKER].items():
        after = contributions(db, generation, item["ids"])
        before = item["before"]
        values = []
        for key in sorted(before.keys() | after.keys()):
            delta = after.get(key, 0) - before.get(key, 0)
            if delta:
                day, category, status, kind, phase, metric = key
                values.append(dict(generation=generation, date=day, category=category, status=status,
                                   kind=kind, phase=phase, metric=metric, value=delta))
        # 所有事务按相同桶顺序加锁，避免跨操作回写状态时日汇总发生死锁。
        for offset in range(0, len(values), 500):
            statement = insert(Daily).values(values[offset:offset + 500])
            db.execute(statement.on_conflict_do_update(
                index_elements=["generation", "date", "category", "status", "kind", "phase", "metric"],
                set_={"value": Daily.value + statement.excluded.value}))


def summary(db, generation, *, category=None, status=None, start=None, end=None):
    query = db.query(Daily).filter(Daily.generation == generation)
    if category:
        query = query.filter(Daily.category == category)
    if status:
        query = query.filter(Daily.status == status)
    if start:
        query = query.filter(Daily.date >= start.date())
    if end:
        query = query.filter(Daily.date < end.date())
    return query.filter(Daily.value != 0).all()
