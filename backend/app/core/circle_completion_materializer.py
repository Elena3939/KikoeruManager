"""社团读模型后台发布：事实快照、租约隔离、增量写入与持久事件。"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, insert, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models.database import (
    SessionLocal, CircleCatalog, CircleWork, WorkMetadata, WorkCanonicalLink, CircleCompletionHead as Head,
    CircleCompletionControl as Control, CircleCompletionDirty as Dirty,
    CircleCompletionWorkState as Work, CircleCompletionWorkAlias as Alias,
    CircleCompletionGroup as Group, CircleCompletionGroupMember as Member,
    CircleCompletionCoverFact as Cover, CircleCompletionPublishOutbox as Outbox,
    CircleCompletionWorkEvent as WorkEvent,
    get_local_now,
)
from .circle_completion_changes import enqueue_in_session
from .circle_completion_read_model import build_normalized_rows
from .release_dates import release_date_end

logger = logging.getLogger(__name__)
TABLES = (Work, Alias, Group, Member)
KEYS = (("canonical_rjcode",), ("canonical_rjcode", "rjcode"),
        ("variant", "group_key"), ("variant", "group_key", "canonical_rjcode"))


class CircleCompletionMaterializer:
    def __init__(self, session_factory=SessionLocal, service=None):
        self.sessions = session_factory
        self.service = service
        self._stop = threading.Event()
        self._thread = None
        self._last_maintenance = 0.0

    def bootstrap(self):
        """只安排没有发布头的社团，重启不重复提升已有社团版本。"""
        with self.sessions.begin() as db:
            circles = db.scalars(select(CircleCatalog.circle_id).outerjoin(
                Head, Head.circle_id == CircleCatalog.circle_id).outerjoin(
                Control, Control.circle_id == CircleCatalog.circle_id).where(
                Head.circle_id.is_(None), Control.circle_id.is_(None)).order_by(
                CircleCatalog.circle_id).limit(100)).all()
            if circles:
                enqueue_in_session(db, circles, reason="initial_backfill", full=True)

    def affected_sources(self, db, circle, old_items, sources):
        """沿新旧别名、父子和同社团同日关系求闭包，包含曾被去重隐藏的候选。"""
        dirty = set(db.scalars(select(Dirty.source_rjcode).where(Dirty.circle_id == circle)))
        codes = {code for row in sources for code in (row.canonical_rjcode, row.display_rjcode, *(row.linked_rjcodes or [])) if code}
        metadata = db.execute(select(WorkMetadata.rjcode, WorkMetadata.maker_id, WorkMetadata.release_date,
                                     WorkMetadata.verified_parent_workno).where(WorkMetadata.rjcode.in_(codes))).all()
        edges = []
        dates = {}
        for row in metadata:
            if row.verified_parent_workno:
                edges.append({row.rjcode, row.verified_parent_workno})
            if row.maker_id and row.release_date:
                dates.setdefault((row.maker_id, row.release_date), set()).add(row.rjcode)
        edges.extend(dates.values())
        for row in sources:
            edges.append({code for code in (row.canonical_rjcode, row.display_rjcode, *(row.linked_rjcodes or [])) if code})
        links = db.execute(select(WorkCanonicalLink.canonical_rjcode, WorkCanonicalLink.linked_rjcode).where(
            WorkCanonicalLink.canonical_rjcode.in_(codes))).all()
        edges.extend(set(row) for row in links)
        old_dates = {}
        for item in old_items:
            edges.append(set(self.service._completion_item_codes(item)) | {item.get("bonus_parent_rjcode", "")})
            date = item.get("original_release_date") or item.get("release_date")
            if item.get("maker_id") and date:
                old_dates.setdefault((item["maker_id"], date), set()).add(item["canonical_rjcode"])
        for key, value in old_dates.items():
            edges.append(value | dates.get(key, set()))
        # 每条边至少共享一个业务身份；不会仅凭语言、标题或封面合并作品。
        while True:
            before = len(dirty)
            for edge in edges:
                if dirty.intersection(edge):
                    dirty.update(edge - {""})
            if len(dirty) == before:
                return dirty

    @staticmethod
    def _merge_summary_delta(summary, delta):
        result = dict(summary or {})
        for key, value in delta.items():
            if isinstance(value, dict):
                result[key] = CircleCompletionMaterializer._merge_summary_delta(
                    result.get(key) or {}, value
                )
            elif isinstance(value, (int, float)):
                result[key] = (result.get(key) or 0) + value
            else:
                result[key] = value
        return result

    @staticmethod
    def _summary_delta(service, catalog, old_items, new_items):
        def visible(items):
            return [item for item in items if item.get("owned") or
                    item.get("has_downloadable_source", item.get("has_asmr_one"))]

        old_summary = {
            "all": service._completion_summary_from_items(catalog, old_items),
            "visible": service._completion_summary_from_items(
                catalog, old_items, visible_items=visible(old_items)
            ),
        }
        new_summary = {
            "all": service._completion_summary_from_items(catalog, new_items),
            "visible": service._completion_summary_from_items(
                catalog, new_items, visible_items=visible(new_items)
            ),
        }

        def subtract(after, before):
            result = {}
            for key in set(after) | set(before):
                left, right = after.get(key), before.get(key)
                if isinstance(left, dict) or isinstance(right, dict):
                    nested = subtract(left or {}, right or {})
                    if nested:
                        result[key] = nested
                elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    if left != right:
                        result[key] = left - right
            return result

        return {
            key: subtract(new_summary[key], old_summary[key])
            for key in ("all", "visible")
        }

    def schedule_time_transitions(self):
        now = get_local_now()
        with self.sessions.begin() as db:
            circles = db.scalars(select(Head.circle_id).join(Control, Control.circle_id == Head.circle_id).where(
                Head.next_transition_at <= now, Control.requested_seq == Head.applied_seq
            ).order_by(Head.circle_id).limit(100)).all()
            if circles:
                enqueue_in_session(db, circles, reason="time_transition", full=True)

    def claim(self):
        """领任务只持短事务，事实构建期间不锁住来源写入。"""
        now = get_local_now()
        with self.sessions.begin() as db:
            control = db.scalars(select(Control).outerjoin(Head, Head.circle_id == Control.circle_id).where(
                (Head.circle_id.is_(None)) | (Control.requested_seq > Head.applied_seq),
                (Control.lease_until.is_(None)) | (Control.lease_until <= now),
                (Control.next_retry_at.is_(None)) | (Control.next_retry_at <= now),
            ).order_by(Control.next_retry_at.asc().nullsfirst(), Control.circle_id)
                .with_for_update(of=Control, skip_locked=True).limit(1)).first()
            if control is None:
                return None
            control.lease_token += 1
            control.lease_until = now + timedelta(minutes=2)
            return control.circle_id, control.lease_token

    def build(self, circle, token):
        from .circle_completion_service import get_circle_completion_service
        from .resource_source_service import get_resource_source_service
        from .circle_subtitle_repair_service import get_circle_subtitle_repair_service

        service = self.service or get_circle_completion_service()
        self.service = service
        with self.sessions() as db:
            # 必须是这个 Session 的第一条 SQL；所有事实与捕获序号共享同一快照。
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout = '60s'"))
            control = db.get(Control, circle)
            head = db.get(Head, circle)
            captured = control.requested_seq
            full = head is None or control.full_requested_seq > head.applied_seq
            generation = uuid4().hex if full else head.active_generation
            revision = head.revision if head else 0
            as_of = get_local_now()
            sources = db.execute(select(CircleWork.canonical_rjcode, CircleWork.display_rjcode,
                CircleWork.linked_rjcodes, CircleWork.updated_at, CircleWork.source_tags,
                CircleWork.email_watcher_first_seen_at, CircleWork.created_at
            ).where(CircleWork.circle_id == circle).order_by(CircleWork.updated_at.desc(), CircleWork.canonical_rjcode)).all()
            old = []
            for table, fields in zip(TABLES, KEYS):
                old.append({} if full else {
                    tuple(getattr(row, field) for field in fields): {
                        column.key: getattr(row, column.key) for column in table.__table__.columns
                        if column.key not in ("circle_id", "generation")
                    } for row in db.scalars(select(table).where(table.circle_id == circle, table.generation == generation))
                })
            previous_items = [{**row["payload"], "source_compare": row["compare_payload"]} for row in old[0].values()]
            affected = None if full else self.affected_sources(db, circle, previous_items, sources)
            fact_codes = {code for row in sources for code in (row.canonical_rjcode, row.display_rjcode, *(row.linked_rjcodes or [])) if code}
            facts = {row.rjcode: True if row.conclusion == "available" else False
                     for row in db.scalars(select(Cover).where(Cover.rjcode.in_(fact_codes), Cover.conclusion.in_(("available", "missing"))))}
            state = service._build_completion_view_state_uncached(circle, db=db, as_of=as_of,
                source_codes=None if full else [row.canonical_rjcode for row in sources if row.canonical_rjcode in affected], cover_facts=facts)
            items = state["items"]
            get_resource_source_service().decorate_items(db, items)
            get_circle_subtitle_repair_service().decorate_items(db, items)
            if not full:
                items.extend(item for item in previous_items if item["canonical_rjcode"] not in affected)
            by_code = {item["canonical_rjcode"]: item for item in items}
            items = [by_code[row.canonical_rjcode] for row in sources if row.canonical_rjcode in by_code]
            rows = build_normalized_rows(service, items, order_keys={row.canonical_rjcode:
                row.updated_at.isoformat() if row.updated_at else "" for row in sources})
            if full:
                visible = [item for item in items if item.get("owned") or
                           item.get("has_downloadable_source", item.get("has_asmr_one"))]
                summary = {
                    "all": service._completion_summary_from_items(state["catalog"], items),
                    "visible": service._completion_summary_from_items(
                        state["catalog"], items, visible_items=visible
                    ),
                }
                for value in summary.values():
                    value["email_works_count"] = sum(
                        "email_watcher" in (row.source_tags or []) for row in sources
                    )
                    value["asmr_available"] = sum(bool(item.get("has_asmr_one")) for item in items)
                completed_dates = self.completed_dates(db, circle, items)
                for value in summary.values():
                    value["completed_bonus_probe_dates"] = completed_dates
                summary_delta = None
            else:
                old_changed = [
                    item for item in previous_items
                    if item["canonical_rjcode"] in affected
                ]
                current_changed = [
                    item for item in items
                    if item["canonical_rjcode"] in affected
                ]
                summary = None
                summary_delta = self._summary_delta(
                    service, state["catalog"], old_changed, current_changed
                )
            if full:
                transitions = []
                for work in sources:
                    if "email_watcher" in (work.source_tags or []):
                        anchor = work.email_watcher_first_seen_at or work.created_at
                        if anchor:
                            transitions.extend((anchor, anchor + timedelta(hours=48, microseconds=1)))
                for item in items:
                    end = release_date_end(item.get("release_date"), today=as_of.date())
                    if item.get("is_unreleased") and end:
                        transitions.append(datetime.combine(end, datetime.min.time()))
                next_transition = min((date for date in transitions if date > as_of), default=None)
            else:
                next_transition = head.next_transition_at
            changed_codes = []
            if not full:
                previous_by_code = {item["canonical_rjcode"]: item for item in previous_items}
                current_by_code = {item["canonical_rjcode"]: item for item in items}
                changed_codes = sorted(code for code in set(previous_by_code) | set(current_by_code)
                    if previous_by_code.get(code) != current_by_code.get(code))
            return dict(circle=circle, token=token, seq=captured, generation=generation,
                        expected_generation=head.active_generation if head else None,
                        expected_revision=revision, full=full, rows=rows, old=old,
                        summary=summary, summary_delta=summary_delta,
                        as_of=as_of, next_transition=next_transition,
                        changed_codes=changed_codes,
                        changed_items={item["canonical_rjcode"]: item for item in items
                                       if item["canonical_rjcode"] in changed_codes},
                        bonus_codes=[row["display_rjcode"] for row in state.get("bonus_cover_candidates", [])])

    def publish(self, build):
        circle, generation = build["circle"], build["generation"]
        with self.sessions.begin() as db:
            control = db.scalar(select(Control).where(Control.circle_id == circle).with_for_update())
            now = get_local_now()
            if control.lease_token != build["token"] or not control.lease_until or control.lease_until <= now:
                return False
            head = db.get(Head, circle)
            if (head.revision if head else 0) != build["expected_revision"] or (
                head.active_generation if head else None) != build["expected_generation"]:
                return False
            writes = 0
            for table, fields, current, previous in zip(TABLES, KEYS, build["rows"], build["old"]):
                # builder 的单字段 key 是字符串，统一转换成复合主键元组。
                current = {(key,) if isinstance(key, str) else key: value for key, value in current.items()}
                removed = previous.keys() - current.keys()
                columns = [getattr(table, field) for field in fields]
                if removed:
                    db.execute(delete(table).where(table.circle_id == circle, table.generation == generation,
                                                   tuple_(*columns).in_(removed)))
                    writes += len(removed)
                changed = [dict(circle_id=circle, generation=generation, **row) for key, row in current.items()
                           if previous.get(key) != row]
                for start in range(0, len(changed), 200):
                    statement = pg_insert(table).values(changed[start:start + 200])
                    updates = {column.key: getattr(statement.excluded, column.key)
                               for column in table.__table__.columns if column.key not in ("circle_id", "generation", *fields)}
                    statement = statement.on_conflict_do_update(
                        index_elements=["circle_id", "generation", *fields], set_=updates
                    ) if updates else statement.on_conflict_do_nothing()
                    db.execute(statement)
                writes += len(changed)
            if not build["full"]:
                head.summary = self._merge_summary_delta(head.summary, build["summary_delta"] or {})
            changed_view = head is None or bool(writes) or (
                build["full"] and head.summary != build["summary"]
            )
            if head is None:
                head = Head(circle_id=circle, revision=0)
                db.add(head)
            head.active_generation = generation
            head.applied_seq = build["seq"]
            head.as_of = build["as_of"]
            head.next_transition_at = build["next_transition"]
            if build["full"]:
                head.summary = build["summary"]
            if build["full"] and changed_view:
                head.revision += 1
                db.add(Outbox(circle_id=circle, revision=head.revision, created_at=now, payload={
                    "type": "circle.completion.changed", "domain": "circle", "id": circle,
                    "payload": {"circle_id": circle, "revision": head.revision,
                                "data_version": f"{generation}/{head.revision}"},
                }))
            elif not build["full"] and build.get("changed_codes"):
                for code in build["changed_codes"]:
                    db.add(WorkEvent(
                        event_id=str(uuid4()), circle_id=circle, canonical_rjcode=code,
                        work_version=build["seq"], created_at=now, payload={
                            "type": "circle.completion.work.changed", "domain": "circle", "id": circle,
                            "payload": {
                                "circle_id": circle, "canonical_rjcode": code,
                                "work_version": build["seq"],
                                "work": build["changed_items"].get(code),
                                "summary": build["summary"],
                                "data_version": f"{generation}/{head.revision}",
                            },
                        },
                    ))
            db.execute(delete(Dirty).where(Dirty.circle_id == circle, Dirty.last_seq <= build["seq"]))
            control.lease_until = None
            control.attempts = 0
            control.last_error = ""
            control.next_retry_at = None
            for code in build.get("bonus_codes", []):
                db.execute(pg_insert(Cover).values(rjcode=code).on_conflict_do_nothing())
            logger.info("[社团物化] circle=%s seq=%s revision=%s full=%s writes=%s", circle,
                        build["seq"], head.revision, build["full"], writes)
            return True

    def fail(self, claim, error):
        circle, token = claim
        with self.sessions.begin() as db:
            control = db.scalar(select(Control).where(Control.circle_id == circle).with_for_update())
            if control and control.lease_token == token:
                control.attempts += 1
                control.next_retry_at = get_local_now() + timedelta(seconds=min(300, 2 ** min(control.attempts, 8)))
                control.last_error = str(error)[:2000]
                control.lease_until = None

    def flush_outbox(self):
        from .realtime_event_service import broadcast_event
        with self.sessions.begin() as db:
            events = db.scalars(select(Outbox).where(Outbox.sent_at.is_(None),
                (Outbox.next_retry_at.is_(None)) | (Outbox.next_retry_at <= get_local_now())
            ).order_by(Outbox.created_at).with_for_update(skip_locked=True).limit(20)).all()
            work_events = db.scalars(select(WorkEvent).where(WorkEvent.sent_at.is_(None),
                (WorkEvent.next_retry_at.is_(None)) | (WorkEvent.next_retry_at <= get_local_now())
            ).order_by(WorkEvent.created_at).with_for_update(skip_locked=True).limit(100)).all()
            for event in [*events, *work_events]:
                try:
                    broadcast_event(event.payload, require_persistence=True)
                except Exception:
                    event.attempts += 1
                    event.next_retry_at = get_local_now() + timedelta(seconds=min(300, 2 ** min(event.attempts, 8)))
                else:
                    event.sent_at = get_local_now()

    def run_once(self):
        from .resource_budget_service import get_resource_budget_service
        claim = self.claim()
        if claim is None:
            return False
        finished = threading.Event()
        heartbeat = threading.Thread(target=self._renew, args=(claim, finished), daemon=True)
        heartbeat.start()
        try:
            build = self.build(*claim)
            with get_resource_budget_service().acquire_sync("database_write", reason="社团物化发布"):
                self.publish(build)
        except Exception as error:
            logger.exception("[社团物化] 构建失败 circle=%s", claim[0])
            self.fail(claim, error)
        finally:
            finished.set()
            heartbeat.join(timeout=3)
        return True

    def _renew(self, claim, finished):
        circle, token = claim
        while not finished.wait(20):
            try:
                with self.sessions.begin() as db:
                    db.execute(text("SET LOCAL lock_timeout = '2s'"))
                    now = get_local_now()
                    result = db.execute(update(Control).where(Control.circle_id == circle,
                        Control.lease_token == token, Control.lease_until > now)
                        .values(lease_until=now + timedelta(minutes=2)))
                    if not result.rowcount:
                        return
            except Exception:
                logger.warning("[社团物化] 租约续期失败 circle=%s", circle, exc_info=True)

    def completed_dates(self, db, circle, items):
        from ..models.database import DLsiteBonusProbeDate, DLsiteBonusOriginalProbeState
        from .dlsite_bonus_probe_service import get_dlsite_bonus_probe_service
        service = get_dlsite_bonus_probe_service()
        originals = [item for item in items if not item.get("is_bonus_work")]
        dates = {item.get("original_release_date") or item.get("release_date") for item in originals}
        makers = {item.get("maker_id") for item in originals if item.get("maker_id")}
        if not dates or not makers:
            return []
        rows = db.scalars(select(DLsiteBonusProbeDate).where(DLsiteBonusProbeDate.maker_id.in_(makers),
            DLsiteBonusProbeDate.release_date.in_(dates - {None, ""}), DLsiteBonusProbeDate.gap_limit == 500)).all()
        completed = {(row.maker_id, row.release_date) for row in rows
                     if service._can_reuse_completed_date_row(row, mode="deep")}
        codes = [item["canonical_rjcode"] for item in originals]
        states = set(db.scalars(select(DLsiteBonusOriginalProbeState.original_rjcode).where(
            DLsiteBonusOriginalProbeState.circle_id == circle,
            DLsiteBonusOriginalProbeState.original_rjcode.in_(codes),
            DLsiteBonusOriginalProbeState.strategy_version == service.PROBE_STRATEGY_VERSION,
            DLsiteBonusOriginalProbeState.status.in_(("has_bonus", "no_bonus")))))
        return sorted(date for date in dates - {None, ""} if all(
            (item.get("maker_id"), date) in completed and item["canonical_rjcode"] in states
            for item in originals if (item.get("original_release_date") or item.get("release_date")) == date))

    def _run(self):
        while not self._stop.is_set():
            try:
                if time.monotonic() - self._last_maintenance >= 30:
                    self.bootstrap()
                    self.cleanup()
                    self._last_maintenance = time.monotonic()
                self.schedule_time_transitions()
                worked = self.run_once()
                self.flush_outbox()
            except Exception:
                logger.exception("[社团物化] 调度失败")
                worked = False
            self._stop.wait(0.1 if worked else 1.0)

    def cleanup(self):
        """限批清理已退休代和已发送事件，不接触当前发布代。"""
        with self.sessions.begin() as db:
            orphaned = db.scalars(select(Control.circle_id).outerjoin(CircleCatalog,
                CircleCatalog.circle_id == Control.circle_id).where(CircleCatalog.circle_id.is_(None)).limit(100)).all()
            if orphaned:
                for table in (Head, Dirty, Outbox, WorkEvent, Control):
                    db.execute(delete(table).where(table.circle_id.in_(orphaned)))
            obsolete = db.execute(select(Work.circle_id, Work.generation).distinct().outerjoin(
                Head, Head.circle_id == Work.circle_id).where(
                (Head.circle_id.is_(None)) | (Work.generation != Head.active_generation)).limit(10)).all()
            for circle, generation in obsolete:
                for table in reversed(TABLES):
                    db.execute(delete(table).where(table.circle_id == circle, table.generation == generation))
            db.execute(delete(Outbox).where(Outbox.sent_at < get_local_now() - timedelta(days=1)))
            db.execute(delete(WorkEvent).where(WorkEvent.sent_at < get_local_now() - timedelta(days=1)))

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="circle-materializer", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)


_materializer = None


def get_circle_completion_materializer():
    global _materializer
    if _materializer is None:
        _materializer = CircleCompletionMaterializer()
    return _materializer
