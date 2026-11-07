"""真实 PostgreSQL 的事务、截点发布和 fencing 测试。"""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.circle_completion_changes import enqueue_in_session
from app.core.circle_completion_materializer import CircleCompletionMaterializer
from app.core.circle_completion_read_model import build_normalized_rows, read_page
from app.models.database import (
    CircleCatalog, CircleCompletionControl as Control, CircleCompletionDirty as Dirty,
    CircleCompletionHead as Head, CircleCompletionPublishOutbox as Outbox,
    CircleCompletionWorkEvent as WorkEvent, LibraryIndexStatus, WorkMetadata, get_local_now,
)
from tests.test_circle_completion_projection import projection


@pytest.fixture
def worker(projection):
    service, items, circle, sessions = projection
    with sessions.begin() as db:
        db.add(CircleCatalog(circle_id=circle, circle_name="事务对照"))
    return CircleCompletionMaterializer(sessions, service), items, circle


def prepared(worker):
    materializer, items, circle = worker
    claim = materializer.claim()
    # 这个测试套件共享 schema，先排除其他 fixture 创建的任务。
    while claim and claim[0] != circle:
        with materializer.sessions.begin() as db:
            db.get(Control, claim[0]).lease_until = get_local_now() + timedelta(days=1)
        claim = materializer.claim()
    assert claim
    with materializer.sessions() as db:
        control = db.get(Control, circle)
        head = db.get(Head, circle)
        generation = head.active_generation if head else uuid4().hex
        return dict(circle=circle, token=claim[1], seq=control.requested_seq,
                    generation=generation, expected_generation=head.active_generation if head else None,
                    expected_revision=head.revision if head else 0, full=head is None,
                    rows=build_normalized_rows(materializer.service, items), old=[{}, {}, {}, {}],
                    summary={}, as_of=get_local_now(), next_transition=None)


def test_enqueue_is_atomic_and_one_sequence_per_transaction(worker):
    materializer, _, circle = worker
    with materializer.sessions() as db:
        initial = db.get(Control, circle).requested_seq
        enqueue_in_session(db, [circle], ["RJ10000001"], reason="one")
        enqueue_in_session(db, [circle], ["RJ10000002"], reason="two")
        assert db.get(Control, circle, populate_existing=True).requested_seq == initial + 1
        db.rollback()
    with materializer.sessions() as db:
        assert db.get(Control, circle).requested_seq == initial
        assert db.get(Dirty, (circle, "RJ10000001")) is None
    with materializer.sessions.begin() as db:
        enqueue_in_session(db, [circle], ["RJ10000001"], reason="one")
        enqueue_in_session(db, [circle], ["RJ10000001"], reason="two")
    with materializer.sessions() as db:
        assert db.get(Control, circle).requested_seq == initial + 1
        assert set(db.get(Dirty, (circle, "RJ10000001")).reasons) == {"one", "two"}


def test_cover_worker_fences_claims_and_only_changes_business_conclusions(worker):
    from app.core.circle_completion_cover_worker import CircleCompletionCoverWorker
    from app.models.database import CircleCompletionCoverFact, CircleWork
    materializer, _, circle = worker
    code = "RJ90000111"
    with materializer.sessions.begin() as db:
        db.add(CircleWork(id=uuid4().hex, circle_id=circle, canonical_rjcode=code, display_rjcode=code))
        db.flush()
        db.add(CircleCompletionCoverFact(rjcode=code))
    with materializer.sessions() as db:
        before = db.get(Control, circle).requested_seq
    cover_worker = CircleCompletionCoverWorker(materializer.sessions)
    codes, claimed = cover_worker.claim()
    assert code in codes
    with materializer.sessions() as db:
        assert db.get(Control, circle).requested_seq == before
    assert cover_worker.finish(code, claimed - timedelta(seconds=1), ("missing", "missing")) == 0
    assert cover_worker.finish(code, claimed, ("missing", "unknown")) == 1
    with materializer.sessions.begin() as db:
        fact = db.get(CircleCompletionCoverFact, code)
        assert fact.pending and fact.conclusion == "unknown"
        assert db.get(Control, circle).requested_seq == before
        fact.checked_at = get_local_now() - timedelta(minutes=6)
    codes, claimed = cover_worker.claim()
    assert code in codes
    assert cover_worker.finish(code, claimed, ("missing", "missing")) == 1
    with materializer.sessions() as db:
        assert db.get(Control, circle).requested_seq == before + 1
        assert db.get(Dirty, (circle, code)) is not None


def test_bonus_date_change_enqueues_its_circle(worker):
    from app.models.database import CircleWork, DLsiteBonusProbeDate
    materializer, _, circle = worker
    code = "RJ90000112"
    with materializer.sessions.begin() as db:
        db.add(CircleWork(id=uuid4().hex, circle_id=circle, canonical_rjcode="RJ90000113",
                          display_rjcode="RJ90000113", linked_rjcodes=[code]))
        db.add(WorkMetadata(rjcode=code, maker_id="RG900001", release_date="2026-01-01"))
    with materializer.sessions() as db:
        before = db.get(Control, circle).requested_seq
    with materializer.sessions.begin() as db:
        db.add(DLsiteBonusProbeDate(maker_id="RG900001", release_date="2026-01-01", gap_limit=500))
    with materializer.sessions() as db:
        control = db.get(Control, circle)
        assert control.requested_seq == before + 1
        assert control.full_requested_seq == control.requested_seq


def test_library_index_status_change_does_not_enqueue_circle_materialization(worker):
    materializer, _, circle = worker
    library_id = f"test-library-{uuid4().hex}"
    with materializer.sessions() as db:
        before = db.get(Control, circle).requested_seq
    with materializer.sessions.begin() as db:
        db.add(LibraryIndexStatus(
            library_id=library_id,
            status="syncing",
            accepted_seq=1,
            materialized_seq=0,
            active_generation=1,
            updated_at=1,
        ))
    with materializer.sessions.begin() as db:
        status = db.get(LibraryIndexStatus, library_id)
        status.status = "ready"
        status.materialized_seq = 1
        status.updated_at = 2
    with materializer.sessions() as db:
        assert db.get(Control, circle).requested_seq == before


def test_publish_acknowledges_only_captured_sequence(worker):
    materializer, _, circle = worker
    with materializer.sessions.begin() as db:
        enqueue_in_session(db, [circle], ["RJ10000001"], reason="before")
    build = prepared(worker)
    with materializer.sessions.begin() as db:
        enqueue_in_session(db, [circle], ["RJ10000001", "RJ10000002"], reason="after")
    assert materializer.publish(build)
    with materializer.sessions() as db:
        result = read_page(db, circle)
        assert result["status"] == "stale"
        assert result["revision"] == 1
        assert db.get(Dirty, (circle, "RJ10000001")).last_seq > build["seq"]
        assert db.get(Dirty, (circle, "RJ10000002")) is not None
        assert db.get(Outbox, (circle, 1)) is not None


def test_expired_worker_cannot_publish_after_reclaim(worker):
    materializer, _, circle = worker
    build = prepared(worker)
    with materializer.sessions.begin() as db:
        db.get(Control, circle).lease_until = get_local_now() - timedelta(seconds=1)
    replacement = prepared(worker)
    assert replacement["token"] > build["token"]
    assert not materializer.publish(build)
    assert materializer.publish(replacement)
    assert not materializer.publish(build)


def test_outbox_failure_keeps_event_pending(worker, monkeypatch):
    materializer, _, circle = worker
    assert materializer.publish(prepared(worker))
    from app.core import realtime_event_service
    def unavailable(*args, **kwargs):
        raise ConnectionError("Redis 暂不可用")
    monkeypatch.setattr(realtime_event_service, "broadcast_event", unavailable)
    materializer.flush_outbox()
    with materializer.sessions.begin() as db:
        event = db.get(Outbox, (circle, 1))
        assert event.sent_at is None
        assert event.attempts == 1
        event.next_retry_at = None
    calls = []
    monkeypatch.setattr(realtime_event_service, "broadcast_event", lambda event, **kw: calls.append((event, kw)))
    materializer.flush_outbox()
    with materializer.sessions() as db:
        assert db.get(Outbox, (circle, 1)).sent_at is not None
    assert any(call[1]["require_persistence"] for call in calls)


def test_real_sources_full_incremental_and_delete(worker):
    from app.models.database import CircleWork
    materializer, _, circle = worker
    with materializer.sessions.begin() as db:
        for number in (1, 2):
            code = f"RJ9000000{number}"
            db.add(CircleWork(id=uuid4().hex, circle_id=circle, canonical_rjcode=code, display_rjcode=code,
                              title=f"真实作品{number}", has_dlsite=True, has_asmr_one=True))
            db.add(WorkMetadata(rjcode=code, work_name=f"真实作品{number}", release_date="2026-01-01"))
    build = prepared(worker)
    full = materializer.build(circle, build["token"])
    assert full["full"]
    assert materializer.publish(full)
    with materializer.sessions.begin() as db:
        db.query(WorkMetadata).filter_by(rjcode="RJ90000001").update({"release_date": "2026-02-02"})
    claim = materializer.claim()
    assert claim and claim[0] == circle
    incremental = materializer.build(*claim)
    assert not incremental["full"]
    assert incremental["rows"][0]["RJ90000001"]["payload"]["release_date"] == "2026-02-02"
    assert incremental["rows"][0]["RJ90000002"] == full["rows"][0]["RJ90000002"]
    with materializer.sessions() as db:
        revision_before = db.get(Head, circle).revision
    assert materializer.publish(incremental)
    with materializer.sessions() as db:
        assert db.get(Head, circle).revision == revision_before
        event = db.scalar(select(WorkEvent).where(
            WorkEvent.circle_id == circle,
            WorkEvent.canonical_rjcode == "RJ90000001",
        ))
        assert event is not None
        assert event.payload["type"] == "circle.completion.work.changed"
        assert db.scalar(select(WorkEvent).where(
            WorkEvent.circle_id == circle,
            WorkEvent.canonical_rjcode == "RJ90000002",
        )) is None
        assert db.scalar(select(Outbox).where(Outbox.circle_id == circle)) is not None
    with materializer.sessions.begin() as db:
        db.query(CircleWork).filter_by(circle_id=circle, canonical_rjcode="RJ90000001").delete()
    deletion = materializer.build(*materializer.claim())
    assert "RJ90000001" not in deletion["rows"][0]
    assert materializer.publish(deletion)
    with materializer.sessions() as db:
        result = read_page(db, circle, tab="compare")
        assert [item["canonical_rjcode"] for item in result["rows"]] == ["RJ90000002"]
