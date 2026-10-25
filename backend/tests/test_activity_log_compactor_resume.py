"""操作历史压缩续扫与事件循环隔离回归。"""
import asyncio
import threading
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.core import activity_log_compactor as compactor
from app.models import database
from app.models.database import ActivityLog


def test_compact_cursor_advances_past_small_and_compacted_rows(db_session, monkeypatch):
    class BorrowedSession:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", BorrowedSession)
    at = datetime.now() - timedelta(days=60)
    for index, detail in enumerate([
        {"small": True}, {"__compacted": True}, {"items": ["大" * 100] * 20},
    ]):
        db_session.add(ActivityLog(
            id=f"resume-{index}", category="auto_import", action="task_finished",
            status="success", summary="测试归档", created_at=at, detail=detail,
        ))
    db_session.flush()
    cursor = None
    rounds = []
    for _ in range(4):
        result = compactor.compact_old_activity_logs(
            max_rows=1, min_detail_bytes=100, cursor=cursor,
        )
        rounds.append(result)
        cursor = result["next_cursor"]
    assert [row["scanned"] for row in rounds] == [1, 1, 1, 0]
    assert [row["updated"] for row in rounds] == [0, 0, 1, 0]
    assert rounds[-1]["done"] is True
    assert cursor is None
    with pytest.raises(ValueError):
        compactor.compact_old_activity_logs(cursor=rounds[0]["next_cursor"], min_detail_bytes=101)


def test_compact_route_runs_outside_event_loop(monkeypatch):
    worker_entered = threading.Event()
    loop_responded = threading.Event()

    def compact(**kwargs):
        worker_entered.set()
        assert loop_responded.wait(3), "压缩阻塞了事件循环"
        return {"done": True, "updated": 0, "next_cursor": None}

    monkeypatch.setattr(compactor, "compact_old_activity_logs", compact)
    app = FastAPI()
    app.post("/compact")(routes.compact_activity_logs)

    @app.get("/ping")
    async def ping():
        loop_responded.set()
        return {"ok": True}

    with TestClient(app) as client:
        result = []
        thread = threading.Thread(target=lambda: result.append(client.post("/compact")))
        thread.start()
        assert worker_entered.wait(3)
        assert client.get("/ping").json() == {"ok": True}
        thread.join(5)
        assert not thread.is_alive()
        assert result[0].status_code == 200


def test_invalid_compact_cursor_returns_bad_request():
    assert not asyncio.iscoroutinefunction(routes.compact_activity_logs)
    app = FastAPI()
    app.post("/compact")(routes.compact_activity_logs)
    with TestClient(app) as client:
        assert client.post("/compact", params={"cursor": "invalid"}).status_code == 400


def test_maintenance_passes_cursor_between_rounds(monkeypatch):
    from app.core import database_maintenance_service as maintenance

    cursors = []

    def compact(**kwargs):
        cursors.append(kwargs["cursor"])
        return {"done": len(cursors) == 2, "next_cursor": "checkpoint"}

    monkeypatch.setattr(compactor, "compact_old_activity_logs", compact)
    monkeypatch.setattr(maintenance, "_set_state", lambda **kwargs: None)
    assert maintenance._do_compact_loop(older_than_days=30, min_detail_bytes=8192)["done"]
    assert cursors == [None, "checkpoint"]


@pytest.mark.asyncio
async def test_periodic_compact_uses_worker_and_resumes(monkeypatch):
    loop_thread = threading.get_ident()
    cursors = []

    def compact(**kwargs):
        assert threading.get_ident() != loop_thread
        cursors.append(kwargs["cursor"])
        return {"done": False, "next_cursor": "checkpoint"}

    async def sleep(_seconds):
        if len(cursors) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(compactor, "compact_old_activity_logs", compact)
    monkeypatch.setattr(routes.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await routes._periodic_activity_log_compact()
    assert cursors == [None, "checkpoint"]
