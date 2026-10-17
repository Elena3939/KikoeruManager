from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import threading
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.activity_log_daily_stats_service import rebuild_daily_stats
from app.core.activity_log_writer import ActivityLogWriter
from app.models.database import ActivityLog, ActivityLogDailyStats, ActivityLogRollup


DAY = date(2026, 10, 13)


def _payload():
    return {"id": str(uuid4()), "category": "circle_completion", "action": "test",
            "status": "success", "created_at": datetime(2026, 10, 13, 12), "detail": {}}


def _count(db):
    return db.query(ActivityLogDailyStats.count).filter(ActivityLogDailyStats.date == DAY.isoformat()).scalar()


def test_consecutive_batches_add_to_same_daily_bucket(db_session):
    for count in (2, 3):
        payloads = [_payload() for _ in range(count)]
        db_session.add_all([ActivityLog(**row) for row in payloads])
        db_session.flush()
        ActivityLogWriter._upsert_daily_stats(db_session, payloads)
        db_session.commit()
    assert _count(db_session) == 5
    assert db_session.query(ActivityLog).count() == 5


def test_daily_failure_savepoint_keeps_main_records(db_session, monkeypatch):
    original_execute = db_session.execute

    def fail_daily(statement, *args, **kwargs):
        if "INSERT INTO activity_log_daily_stats" in str(statement):
            return original_execute(text("SELECT 1 / 0"))
        return original_execute(statement, *args, **kwargs)

    payload = _payload()
    db_session.add(ActivityLog(**payload))
    db_session.flush()
    monkeypatch.setattr(db_session, "execute", fail_daily)
    ActivityLogWriter._upsert_daily_stats(db_session, [payload])
    db_session.commit()
    assert db_session.query(ActivityLog).count() == 1
    assert _count(db_session) is None


def test_concurrent_daily_writers_preserve_all_increments(db_session, db_engine):
    factory = sessionmaker(bind=db_engine)

    def write(_):
        with factory() as db:
            payloads = [_payload(), _payload()]
            db.add_all([ActivityLog(**row) for row in payloads])
            db.flush()
            ActivityLogWriter._upsert_daily_stats(db, payloads)
            db.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(4)))
    with factory() as db:
        assert _count(db) == 8
        assert db.query(ActivityLog).count() == 8


def test_rebuild_is_exact_idempotent_and_does_not_add_rollup(db_session):
    from app.core.activity_log_compactor import _compact_detail

    payloads = [_payload(), _payload()]
    payloads[0]["detail"] = _compact_detail({"items": [1, 2, 3]})[0]
    db_session.add_all([ActivityLog(**row) for row in payloads])
    db_session.add(ActivityLogRollup(rollup_key="batch:test", child_count=999))
    db_session.add(ActivityLogDailyStats(date=DAY.isoformat(), category="circle_completion", status="success", count=100))
    db_session.add(ActivityLogDailyStats(date=DAY.isoformat(), category="stale", status="failed", count=10))
    db_session.flush()
    before = rebuild_daily_stats(db_session, start_date=DAY, end_date=DAY)
    assert before["source_rows"] == 2
    assert before["mismatched_buckets"] == 2
    assert _count_for_category(db_session, "circle_completion") == 100
    rebuild_daily_stats(db_session, start_date=DAY, end_date=DAY, apply=True)
    db_session.commit()
    assert _count(db_session) == 2
    again = rebuild_daily_stats(db_session, start_date=DAY, end_date=DAY, apply=True)
    assert again["mismatched_buckets"] == 0
    assert again["source_rows"] == 2
    assert db_session.query(ActivityLogRollup).one().child_count == 999


def _count_for_category(db, category):
    return db.query(ActivityLogDailyStats.count).filter_by(date=DAY.isoformat(), category=category).scalar()


def test_writer_queued_during_rebuild_is_counted_once(db_session, db_engine):
    factory = sessionmaker(bind=db_engine)
    inserted = threading.Event()

    def write():
        with factory() as db:
            payload = _payload()
            db.add(ActivityLog(**payload))
            db.flush()
            inserted.set()
            ActivityLogWriter._upsert_daily_stats(db, [payload])
            db.commit()

    with factory() as repairing, ThreadPoolExecutor(max_workers=1) as pool:
        repairing.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
            "key": f"activity-log-daily:{DAY.isoformat()}",
        })
        future = pool.submit(write)
        assert inserted.wait(5)
        try:
            result = rebuild_daily_stats(repairing, start_date=DAY, end_date=DAY, apply=True)
            assert result["source_rows"] == 0
            repairing.commit()
        finally:
            repairing.rollback()
        future.result(timeout=10)
    with factory() as db:
        assert _count(db) == 1
        assert rebuild_daily_stats(db, start_date=DAY, end_date=DAY)["mismatched_buckets"] == 0
