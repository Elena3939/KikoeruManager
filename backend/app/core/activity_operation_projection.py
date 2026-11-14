"""事务内增量维护操作投影。历史重建和在线事件共用同一归一化路径。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_, text, tuple_
from sqlalchemy.dialects.postgresql import insert

from ..models.database import (
    ActivityLog, ActivityLogMetricFact as Fact, ActivityLogOperation as Operation,
    ActivityLogOperationEvent as Event, ActivityLogOperationFile as File,
    ActivityLogOperationMember as Member, ActivityLogProjectionRepair as Repair,
    ActivityLogProjectionState as State,
)
from .activity_operation_normalizer import digest, event_identity, normalize_event, operation_status

GATE = "activity-operation-generation"


def projection_state(db):
    return db.get(State, 1)


def _ensure_state(db):
    existing = projection_state(db)
    if existing is not None:
        db.refresh(existing)
        return existing
    db.execute(insert(State).values(id=1, active_generation=1, ready=False, revision=0, checkpoint={})
               .on_conflict_do_nothing())
    return db.get(State, 1, populate_existing=True)


def maintain_operations(db, payloads, *, generation=None, force=False):
    from .activity_operation_daily import TRACKER, finish
    outer = TRACKER not in db.info
    if outer:
        db.info[TRACKER] = {}
    try:
        _maintain_operations(db, payloads, generation=generation, force=force)
        if outer:
            finish(db)
    finally:
        if outer:
            db.info.pop(TRACKER, None)


def _maintain_operations(db, payloads, *, generation=None, force=False):
    """操作锁顺序固定；不读取整个批次的原始 JSON，不在这里提交调用方事务。"""
    if not payloads:
        return
    db.flush()
    # 没有稳定批次/会话身份的事件可能成为迟到父记录，归属解析必须在门闩内。
    structural = force or any(
        row.get("parent_id") or (row.get("detail") or {}).get("parent_id")
        or row.get("action") == "batch_start"
        or not (row.get("batch_id") or row.get("session_key") or any(
            (row.get("detail") or {}).get(key) for key in ("operation_id", "batch_id", "session_key", "session_id")))
        for row in payloads)
    lock = "pg_advisory_xact_lock" if force or (structural and generation is None) else "pg_advisory_xact_lock_shared"
    db.execute(text(f"SELECT {lock}(hashtextextended(:key, 0))"), {"key": GATE})
    # payload 缺省的 created_at 必须读取已经落库的真实值，不能在多次重放时重新取 now。
    ids = list(dict.fromkeys(row["id"] for row in payloads))
    # 父记录可能晚于子记录到达。只沿明确父键补齐受影响后代，不按时间/RJ 猜关系。
    frontier = set(ids)
    while frontier:
        children = {key for key, in db.query(ActivityLog.id).filter(or_(
            ActivityLog.parent_id.in_(frontier),
            ActivityLog.detail.op("->>")("parent_id").in_(frontier)))}
        frontier = children - set(ids)
        if not frontier:
            break
        ids.extend(sorted(frontier))
    from .activity_detail_archive import restore_details
    stored = restore_details(db, db.query(ActivityLog).filter(ActivityLog.id.in_(ids)))
    # 旧事件的父关系必须回到明确的父身份，不能因为任务 ID 不同拆成另一操作。
    ancestors = dict(stored)
    frontier = set(stored)
    while frontier:
        parents = {str(row.get("parent_id") or (row.get("detail") or {}).get("parent_id"))
                   for key in frontier for row in [ancestors[key]]
                   if row.get("parent_id") or (row.get("detail") or {}).get("parent_id")}
        missing = parents - ancestors.keys()
        if not missing:
            break
        found = restore_details(db, db.query(ActivityLog).filter(ActivityLog.id.in_(missing)))
        ancestors.update(found)
        frontier = set(found)
        if not frontier:
            break
    normalized = []
    for row_id in ids:
        if row_id not in stored:
            continue
        row, anchor, visited = stored[row_id], stored[row_id], [row_id]
        cycle, missing_parent = False, False
        while True:
            detail = anchor.get("detail") or {}
            if detail.get("operation_id") or anchor.get("batch_id") or anchor.get("session_key") or any(
                    detail.get(key) for key in ("batch_id", "session_key", "session_id")):
                break
            parent = anchor.get("parent_id") or detail.get("parent_id")
            if parent in visited:
                cycle = True
                break
            if not parent:
                break
            if parent not in ancestors:
                missing_parent = True
                break
            visited.append(parent)
            anchor = ancestors[parent]
        identity = event_identity(anchor)
        if cycle:
            identity = (row["category"], "event", min(visited[visited.index(parent):]))
        item = normalize_event({**row, "_operation_identity": identity})
        if cycle:
            item["integrity"].append("parent_cycle")
        if missing_parent:
            item["integrity"].append("parent_missing")
        normalized.append(item)
    state = _ensure_state(db)
    generations = [generation] if generation is not None else list(dict.fromkeys(
        value for value in (state.active_generation, state.building_generation) if value is not None))
    if force:
        for target in sorted(generations):
            affected = {key for key, in db.query(Event.operation_id).filter(
                Event.generation == target, Event.event_id.in_(ids))}
            affected.update(item["operation_id"] for item in normalized)
            from .activity_operation_daily import capture
            capture(db, target, affected)
            replay = set(ids) | {key for key, in db.query(Event.event_id).filter(
                Event.generation == target, Event.operation_id.in_(affected))}
            for op in db.query(Operation).filter(
                    Operation.generation == target, Operation.operation_id.in_(affected)):
                op.root_log_id, op.status, op.original_status = None, "incomplete", None
                op.initiated_at, op.latest_activity_at = datetime.max, datetime.min
                op.event_count, op.counts, op.presentation, op.integrity = 0, {}, {}, []
                op.revision += 1
            for model in (Member, Fact, File, Event):
                db.query(model).filter(model.generation == target, model.operation_id.in_(affected)).delete(
                    synchronize_session="fetch")
            maintain_operations(db, [{"id": key} for key in sorted(replay)], generation=target)
            db.query(Operation).filter(
                Operation.generation == target, Operation.operation_id.in_(affected),
                Operation.event_count == 0).delete(synchronize_session="fetch")
        db.flush()
        return
    for target in sorted(generations):
        previous = {event.event_id: event.operation_id for event in db.query(Event).filter(
            Event.generation == target, Event.event_id.in_(ids))}
        relocated = {previous[item["event_id"]] for item in normalized
                     if item["event_id"] in previous and previous[item["event_id"]] != item["operation_id"]}
        lock_ids = relocated | {item["operation_id"] for item in normalized}
        db.execute(text("""
            SELECT pg_advisory_xact_lock(hashtextextended(key, 0))
            FROM unnest(CAST(:keys AS text[])) AS locks(key) ORDER BY key
        """), {"keys": [f"activity-operation:{target}:{identity}" for identity in sorted(lock_ids)]})
        from .activity_operation_daily import capture
        capture(db, target, lock_ids)
        if relocated:
            # 仅迟到父关系和显式身份修正需要重算旧操作；普通事件始终走增量路径。
            affected_ids = [key for key, in db.query(Event.event_id).filter(
                Event.generation == target, Event.operation_id.in_(relocated))]
            for model in (Member, Fact, File, Event, Operation):
                db.query(model).filter(model.generation == target, model.operation_id.in_(relocated)).delete(
                    synchronize_session="fetch")
            maintain_operations(db, [{"id": key} for key in set(ids) | set(affected_ids)],
                                generation=target, force=force)
            continue
        grouped = defaultdict(list)
        for item in normalized:
            grouped[item["operation_id"]].append(item)
        initial = []
        for operation_id, events in grouped.items():
            first = events[0]
            initial.append(dict(
                generation=target, operation_id=operation_id, category=first["category"],
                identity_kind=first["identity_kind"], identity_value=first["identity_value"],
                initiated_at=first["initiated_at"], latest_activity_at=first["event_at"],
                status="incomplete", revision=0, event_count=0, counts={}, presentation={}, integrity=[],
            ))
        for offset in range(0, len(initial), 500):
            db.execute(insert(Operation).values(initial[offset:offset + 500]).on_conflict_do_nothing())
        operations = {op.operation_id: op for op in db.query(Operation).filter(
            Operation.generation == target, Operation.operation_id.in_(grouped)).with_for_update()}
        # 预取本批涉及的成员和指标，后续事件只更新内存中的同一身份对象。
        member_keys = sorted({(item["operation_id"], item["member_id"]) for item in normalized if item["member_id"]})
        member_keys = sorted(set(member_keys) | {
            (item["operation_id"], member["member_id"])
            for item in normalized for member in item["result_members"]})
        members = {}
        for offset in range(0, len(member_keys), 500):
            keys = member_keys[offset:offset + 500]
            members.update({(row.operation_id, row.member_id): row for row in db.query(Member).filter(
                Member.generation == target, tuple_(Member.operation_id, Member.member_id).in_(keys))})
        executions = {item["execution_id"] for item in normalized}
        facts = {(row.execution_id, row.phase, row.metric): row for row in db.query(Fact).filter(
            Fact.generation == target, Fact.execution_id.in_(executions))}
        file_keys = {(item["execution_id"], phase, digest(payload.get("library_id"),
                     payload.get("relative_path") or payload.get("path") or payload.get("name")))
                     for item in normalized for phase, payload in item["files"]}
        existing_files = {}
        file_keys = sorted(file_keys)
        for offset in range(0, len(file_keys), 500):
            existing_files.update({(row.execution_id, row.phase, row.file_id): row for row in db.query(File).filter(
                File.generation == target,
                tuple_(File.execution_id, File.phase, File.file_id).in_(file_keys[offset:offset + 500]))})
        added = set()
        event_values = [dict(generation=target, event_id=item["event_id"],
                            operation_id=item["operation_id"], event_at=item["event_at"])
                        for item in normalized]
        for offset in range(0, len(event_values), 500):
            added.update(db.execute(insert(Event).values(event_values[offset:offset + 500])
                                    .on_conflict_do_nothing().returning(Event.event_id)).scalars())
        context = {"members": members, "facts": facts, "files": existing_files, "file_writes": {}}
        for operation_id in sorted(grouped):
            operation = operations[operation_id]
            events = sorted(grouped[operation_id], key=lambda event: (event["event_at"], event["event_id"]))
            for item in events:
                if item["event_id"] in added:
                    _apply_event(db, operation, item, force=force, context=context)
        values = list(context["file_writes"].values())
        for offset in range(0, len(values), 500):
            stmt = insert(File).values(values[offset:offset + 500])
            db.execute(stmt.on_conflict_do_update(
                index_elements=["generation", "operation_id", "execution_id", "phase", "file_id"],
                set_={"payload": stmt.excluded.payload, "source_event_id": stmt.excluded.source_event_id,
                      "event_at": stmt.excluded.event_at}))
        db.flush()
    # 修订号保留在各操作行。普通事件不争用全局 state 行，避免串行化所有写入。


def _apply_event(db, operation, item, *, force=False, context):
    generation = operation.generation
    operation_id = operation.operation_id
    operation.event_count += 1
    presentation = dict(operation.presentation or {})
    old_order = (str(presentation.get("event_at") or ""), str(presentation.get("id") or ""))
    new_order = (item["event_at"].isoformat(), item["event_id"])
    # 原批次保留根身份与扫描协议；最新成员仅更新错误等结果信息。
    if (item["root"] and (not operation.root_log_id or new_order >= old_order
                         or (force and operation.root_log_id == item["event_id"]))) or (
            not operation.root_log_id and new_order >= old_order):
        root_detail = dict(presentation.get("detail") or {}) if item["root"] else {}
        root_detail.update(item["presentation"]["detail"])
        presentation = {**presentation, **item["presentation"], "detail": root_detail,
                        "event_at": item["event_at"].isoformat(), "root_status": item["status"]}
        if item["root"]:
            operation.root_log_id = item["event_id"]
    if not presentation:
        presentation = {**item["presentation"], "event_at": item["event_at"].isoformat()}
    operation.initiated_at = min(operation.initiated_at, item["initiated_at"])
    operation.latest_activity_at = max(operation.latest_activity_at, item["event_at"])
    operation.integrity = sorted(set(operation.integrity or []) | set(item["integrity"]))
    counts = dict(operation.counts or {})
    updates = ([{"member_id": item["member_id"], "status": item["status"]}]
               if item["member_id"] else []) + item["result_members"]
    for update in updates:
        member_item = {**item, **update}
        key = (operation_id, member_item["member_id"])
        member = context["members"].get(key)
        if member is None:
            member = Member(generation=generation, operation_id=operation_id, member_id=member_item["member_id"],
                            status=member_item["status"], original_status=member_item["status"], event_at=item["event_at"],
                            event_id=item["event_id"], is_projection=item["projection"])
            db.add(member)
            context["members"][key] = member
            counts[member_item["status"]] = counts.get(member_item["status"], 0) + 1
        elif (item["event_at"], item["event_id"]) > (member.event_at, member.event_id) or (
                force and item["event_id"] == member.event_id and member.status != member_item["status"]):
            counts[member.status] = counts.get(member.status, 0) - 1
            counts[member_item["status"]] = counts.get(member_item["status"], 0) + 1
            member.status = member_item["status"]
            member.event_at, member.event_id = item["event_at"], item["event_id"]
            member.is_projection = item["projection"]
        elif (item["event_at"], item["event_id"]) < (member.event_at, member.event_id):
            # 最早结果独立于重放顺序；失败历史仍以事件明细为准。
            if member_item["status"] in {"failed", "partial_success"}:
                member.original_status = member_item["status"]
        if (member_item["status"] in {"failed", "partial_success"} or item["original_status"] in {"failed", "partial_success"}) and not item["projection"]:
            failure = item["original_status"] if item["original_status"] in {"failed", "partial_success"} else member_item["status"]
            if member.original_status != "failed":
                member.original_status = failure
    operation.counts = {key: value for key, value in counts.items() if value}
    operation.presentation = presentation
    if item["root"] and not item["projection"]:
        root_original = item["original_status"] or item["status"]
        if root_original in {"failed", "partial_success"}:
            original_order = presentation.get("original_batch_order", ("", ""))
            if new_order >= tuple(original_order):
                presentation["original_batch_status"] = root_original
                presentation["original_batch_order"] = new_order
    if (item["status"] in {"failed", "partial_success"} or item["original_status"] in {"failed", "partial_success"}) and not item["projection"]:
        failure = item["original_status"] if item["original_status"] in {"failed", "partial_success"} else item["status"]
        if operation.original_status != "failed":
            operation.original_status = failure
    elif operation.original_status not in {"failed", "partial_success"} and item["status"] in {"success", "cancelled"}:
        operation.original_status = item["status"]
    if presentation.get("original_batch_status"):
        operation.original_status = presentation["original_batch_status"]
    if item["projection"] or item["retry_repaired"]:
        presentation["has_retry_projection"] = True
    operation.status = operation_status(operation.counts, presentation.get("detail") or {},
                                        presentation.get("root_status"))
    if operation.status == "success" and operation.original_status in {"failed", "partial_success"} and presentation.get("has_retry_projection"):
        operation.status = "repaired"
    if operation.original_status not in {"failed", "partial_success"}:
        operation.original_status = operation.status
    operation.revision += 1

    # 文件事件按明确的文件身份去重；摘要到达后以权威清单/摘要替换临时累计。
    file_values = {}
    for phase, payload in item["files"]:
        identity = payload.get("relative_path") or payload.get("path") or payload.get("name")
        if not identity:
            continue
        file_id = digest(payload.get("library_id"), identity)
        file_values[(phase, file_id)] = dict(
            generation=generation, operation_id=operation_id, execution_id=item["execution_id"],
            phase=phase, file_id=file_id, payload=payload, source_event_id=item["event_id"],
            event_at=item["event_at"])
    file_deltas = defaultdict(lambda: {"files": 0, "bytes": 0})
    if file_values:
        from types import SimpleNamespace
        for key, value in file_values.items():
            cache_key = (item["execution_id"], *key)
            previous = context["files"].get(cache_key)
            if previous and ((value["event_at"], value["source_event_id"]) < (
                    previous.event_at, previous.source_event_id) or
                    (not force and (value["event_at"], value["source_event_id"]) == (
                        previous.event_at, previous.source_event_id))):
                continue
            old = previous.payload if previous else {}
            new = value["payload"]
            file_deltas[key[0]]["files"] += int(previous is None)
            # 差额来自同一个文件的新旧值，重叠清单不能重复计量。
            from .activity_operation_normalizer import first_known, nonnegative
            old_bytes = nonnegative(first_known(old.get("size_bytes"), old.get("size")))
            new_bytes = nonnegative(first_known(new.get("size_bytes"), new.get("size")))
            if new_bytes is None and old_bytes is not None:
                # 未知值不能抹掉已知文件大小；后续可靠大小更正仍按差额处理。
                new["size_bytes"] = old_bytes
                new_bytes = old_bytes
            file_deltas[key[0]]["bytes"] += (new_bytes or 0) - (old_bytes or 0)
            context["files"][cache_key] = SimpleNamespace(**value)
            context["file_writes"][cache_key] = value
    for phase, metric, value, authority in item["metrics"]:
        key = (item["execution_id"], phase, metric)
        fact = context["facts"].get(key)
        if authority == 1:
            value = file_deltas[phase].get(metric, 0)
            if not value and fact is None:
                # 明确的零字节文件仍然建立零值事实。
                if metric != "bytes" or not any(p == phase and f.get("size_bytes") == 0
                                               for p, f in item["files"]):
                    continue
        if fact is None:
            fact = Fact(generation=generation, operation_id=operation_id, execution_id=item["execution_id"],
                        phase=phase, metric=metric, value=value, authority=authority,
                        completed_at=item["completed_at"], source_event_id=item["event_id"])
            db.add(fact)
            context["facts"][key] = fact
        elif authority == 1 and fact.authority == 1:
            fact.value += value
            fact.completed_at = max(fact.completed_at, item["completed_at"])
            fact.source_event_id = max(fact.source_event_id, item["event_id"])
        elif (authority, item["completed_at"], item["event_id"]) > (
                fact.authority, fact.completed_at, fact.source_event_id) or (
                    force and fact.source_event_id == item["event_id"]):
            fact.value, fact.authority = value, authority
            fact.completed_at, fact.source_event_id = item["completed_at"], item["event_id"]


def record_repair(db, payloads, component, error):
    for row in payloads:
        db.execute(insert(Repair).values(event_id=row["id"], component=component,
                                        error=type(error).__name__, created_at=datetime.now())
                   .on_conflict_do_update(index_elements=["event_id", "component"],
                                          set_={"error": type(error).__name__}))


def refresh_mutated_events(db, rows, *, old_statuses=None):
    """审计原行回写与派生更新共享事务；失败标记必须随原行持久化。"""
    from .activity_log_writer import ActivityLogWriter
    old_statuses = old_statuses or {}
    payloads = [row.to_dict() for row in rows]
    db.flush()
    for row in rows:
        if row.id in old_statuses and old_statuses[row.id] != row.status:
            try:
                ActivityLogWriter._adjust_daily_stats(
                    db, created_at=row.created_at, category=row.category,
                    old_status=old_statuses[row.id], new_status=row.status, strict=True)
            except Exception as error:
                record_repair(db, [{"id": row.id}], "daily", error)
    try:
        with db.begin_nested():
            maintain_operations(db, payloads, force=True)
    except Exception as error:
        record_repair(db, payloads, "operations", error)


def publish_revision():
    """提交后发跨进程版本提示；读接口版本来自 PG，Redis 暂时不可用不返回旧数据。"""
    import logging
    from .activity_log_writer import (
        get_activity_log_query_cache, get_activity_log_row_dict_cache, get_activity_log_lite_item_cache,
    )
    get_activity_log_query_cache().invalidate()
    get_activity_log_row_dict_cache().invalidate()
    get_activity_log_lite_item_cache().invalidate()
    try:
        from .redis_service import get_redis_service
        redis = get_redis_service()
        client = redis.client(required=False)
        if client is not None:
            revision = client.incr(redis.key("activity", "revision"))
            client.publish(redis.key("activity", "revision-channel"), str(revision))
    except Exception:
        logging.getLogger(__name__).warning("[操作记录] 跨进程修订通知失败，读取以数据库版本为准", exc_info=True)
