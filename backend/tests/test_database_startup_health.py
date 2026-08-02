from app.models import database


def test_startup_health_retries_postgres_connection_loss(monkeypatch):
    results = [
        {"ok": False, "error": "(psycopg.OperationalError) the connection is lost"},
        {"ok": True, "messages": ["ok"]},
    ]
    calls = []

    class FakeEngine:
        def dispose(self):
            calls.append("dispose")

    monkeypatch.setattr(database, "engine", FakeEngine())
    monkeypatch.setattr(database, "check_database_health", lambda **_kwargs: results.pop(0))
    monkeypatch.setattr(database.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert database._check_startup_database_health()["ok"] is True
    assert calls == ["dispose", ("sleep", 1.0)]


def test_startup_health_does_not_retry_non_connection_error(monkeypatch):
    calls = []

    class FakeEngine:
        def dispose(self):
            calls.append("dispose")

    health = {"ok": False, "error": "password authentication failed for user"}
    monkeypatch.setattr(database, "engine", FakeEngine())
    monkeypatch.setattr(database, "check_database_health", lambda **_kwargs: health)
    monkeypatch.setattr(database.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert database._check_startup_database_health() == health
    assert calls == []
