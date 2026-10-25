from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core import task_notification_service as module
from app.models.database import NotificationInboxItem, NotificationOutbox


def _prepare(monkeypatch, db_engine):
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr("app.models.database.SessionLocal", factory)
    cfg = SimpleNamespace(
        enabled=True, enabled_domains=[], to_email="test@example.test", smtp_host="smtp.example.test",
        send_on_completed=True, send_on_failed=True, send_on_waiting_manual=True,
    )
    monkeypatch.setattr("app.config.settings.get_config", lambda: SimpleNamespace(notification_email=cfg))
    task = SimpleNamespace(id="notification-race-task", session_id="", task_metadata={})
    info = dict.fromkeys([
        "severity", "domain", "task_kind", "source_page", "source_action", "source_label",
        "business_key", "title", "summary", "rjcode", "route_path", "domain_label",
    ], "")
    info.update(severity="warning", domain="task", route_query={})
    monkeypatch.setattr(module, "_build_notification_info", lambda *args: info)
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: SimpleNamespace(tasks={}))
    monkeypatch.setattr("app.core.notification_helper.build_notification_extra_for_task", lambda task: {})
    broadcast = Mock()
    monkeypatch.setattr(module, "_sse_broadcast", broadcast)
    return factory, task, broadcast


def test_concurrent_notification_writes_create_one_inbox_outbox_and_event(db_engine, monkeypatch):
    factory, task, broadcast = _prepare(monkeypatch, db_engine)
    build_info = module._build_notification_info
    barrier = Barrier(2)

    def concurrent_info(*args):
        barrier.wait(timeout=10)
        return build_info(*args)

    monkeypatch.setattr(module, "_build_notification_info", concurrent_info)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(module._write_sync, "race-event", "waiting_manual", task, "group", "batch", "run")
            for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=20)

    with factory() as db:
        inbox = db.query(NotificationInboxItem).filter_by(event_key="race-event").one()
        outbox = db.query(NotificationOutbox).filter_by(event_key="race-event").one()
        assert outbox.inbox_item_id == inbox.id
    assert broadcast.call_count == 1


def test_notification_outbox_failure_rolls_back_inbox_and_allows_retry(db_engine, monkeypatch):
    factory, task, broadcast = _prepare(monkeypatch, db_engine)

    def fail_outbox(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO notification_outbox"):
            raise RuntimeError("模拟邮件入队失败")

    event.listen(db_engine, "before_cursor_execute", fail_outbox)
    try:
        module._write_sync("retry-event", "waiting_manual", task, "group", "batch", "run")
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_outbox)
    with factory() as db:
        assert db.query(NotificationInboxItem).filter_by(event_key="retry-event").count() == 0
    assert broadcast.call_count == 0

    module._write_sync("retry-event", "waiting_manual", task, "group", "batch", "run")
    with factory() as db:
        assert db.query(NotificationInboxItem).filter_by(event_key="retry-event").count() == 1
        assert db.query(NotificationOutbox).filter_by(event_key="retry-event").count() == 1
    assert broadcast.call_count == 1
