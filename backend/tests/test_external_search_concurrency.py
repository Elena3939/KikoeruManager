from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core import circle_external_search_service as module
from app.models.database import CircleExternalSearchRecord, get_local_now


def test_concurrent_external_search_enqueue_preserves_existing_result(db_engine, monkeypatch):
    factory = sessionmaker(bind=db_engine)
    service = module.CircleExternalSearchService()
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(service, "_source_ready", lambda source: True)
    keys = [("anime_share", "RJ01000001"), ("anime_share", "RJ01000002")]
    lease_until = get_local_now() + timedelta(minutes=5)
    with factory() as db:
        db.add(CircleExternalSearchRecord(
            source=keys[0][0], rjcode=keys[0][1],
            probe_schema_version=service._PROBE_SCHEMA_VERSION,
            status="hit", results_json=[{"url": "https://example.test/work"}],
            search_url=service._source_search_url(*keys[0]),
            next_probe_at=get_local_now() - timedelta(minutes=1),
            lease_until=lease_until, priority=0,
        ))
        db.commit()

    barrier = Barrier(2)

    def align_inserts(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO circle_external_search_records"):
            barrier.wait(timeout=10)

    event.listen(db_engine, "before_cursor_execute", align_inserts)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(service._load_or_enqueue_records, keys) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(db_engine, "before_cursor_execute", align_inserts)

    assert all(result[keys[0]]["status"] == "hit" for result in results)
    assert all(result[keys[1]]["status"] == "pending" for result in results)
    with factory() as db:
        rows = db.query(CircleExternalSearchRecord).filter(
            CircleExternalSearchRecord.rjcode.in_([key[1] for key in keys]),
        ).all()
        assert len(rows) == 2
        hit = next(row for row in rows if row.rjcode == keys[0][1])
        assert hit.lease_until == lease_until
        assert hit.priority == 0
        assert hit.results_json == [{"url": "https://example.test/work"}]
