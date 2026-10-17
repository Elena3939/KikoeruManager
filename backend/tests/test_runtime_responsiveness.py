"""同步大对象与 watcher 初始化不能阻塞事件循环或越过关闭边界。"""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api import routes
from app.core import asmr_resource_service as asmr_module
from app.core.library_index import watcher_driver as watcher_module
from app.models.database import ASMRDownloadSession


def test_session_list_projects_scalars_without_reading_large_json(db_session, monkeypatch):
    resources = [{"relative_path": f"音频/{index}.wav", "padding": "x" * 100} for index in range(10000)]
    db_session.add(ASMRDownloadSession(
        id="large-session", rjcode="RJ00000001", queue_priority=3,
        selected_resources=resources, statistics={"resources": resources},
        failure_summary={"files": resources}, selected_filters={"audio": True},
    ))
    db_session.flush()
    connection = db_session.connection()
    monkeypatch.setattr(asmr_module, "SessionLocal", sessionmaker(bind=connection))
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        rows = asmr_module.ASMRResourceService().list_sessions(request_id="large-json")
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert rows[0]["id"] == "large-session"
    assert rows[0]["queue_priority"] == 3
    assert rows[0]["local_download_ready"] is False
    assert len(json.dumps(rows)) < 1500
    for name in ("selected_resources", "selected_filters", "statistics", "failure_summary"):
        assert name not in rows[0]
        assert all(name not in statement for statement in statements)
    # 列表投影不改变详情的完整资源数据。
    assert db_session.get(ASMRDownloadSession, "large-session").selected_resources == resources


@pytest.mark.asyncio
async def test_session_list_query_and_response_encoding_run_in_worker(monkeypatch):
    loop_thread = threading.get_ident()
    entered = threading.Event()
    release = threading.Event()
    worker_threads = []
    response_class = routes.JSONResponse

    def list_sessions(**kwargs):
        assert kwargs == {"limit": 7, "request_id": "responsive-request"}
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        return [{"id": "session"}]

    class CheckedResponse(response_class):
        def render(self, content):
            worker_threads.append(threading.get_ident())
            return super().render(content)

    monkeypatch.setattr(asmr_module, "get_asmr_resource_service", lambda: SimpleNamespace(list_sessions=list_sessions))
    monkeypatch.setattr(routes, "JSONResponse", CheckedResponse)
    request = Request({"type": "http", "state": {"request_id": "responsive-request"}})
    task = asyncio.create_task(routes.asmr_sync_enhanced_sessions(request, limit=7))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert not task.done()
    finally:
        release.set()
    response = await task
    assert json.loads(response.body)["sessions"] == [{"id": "session"}]
    assert len(worker_threads) == 2
    assert all(thread != loop_thread for thread in worker_threads)


def test_watchdog_stack_threshold_is_independent_of_warning_cooldown(monkeypatch):
    times = iter((2.1, 8.1, 10.0, 68.2))
    warnings = []
    stacks = []
    monkeypatch.setattr(routes, "_EVENT_LOOP_WATCHDOG_LAST_BEAT", 0.0)
    monkeypatch.setattr(routes, "_EVENT_LOOP_STALL_ID", None)
    monkeypatch.setattr(routes.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(routes, "_env_float", lambda _name, default, **_kwargs: default)
    monkeypatch.setattr(routes, "_format_all_thread_stacks", lambda: "主线程现场")
    monkeypatch.setattr(routes.logger, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(routes.logger, "error", lambda *args: stacks.append(args))

    class StopAfterSamples:
        count = 0

        def wait(self, _interval):
            self.count += 1
            return self.count > 4

    routes._event_loop_watchdog_thread(StopAfterSamples())
    assert [args[1] for args in warnings] == [2.1, 68.2]
    assert [args[1] for args in stacks] == [8.1, 68.2]
    assert len({args[3] for args in warnings + stacks}) == 1


def test_watcher_shutdown_during_recursive_registration_never_publishes(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    observers = []
    driver = watcher_module.LibraryIndexWatcherDriver()
    monkeypatch.setattr(driver, "_restore_redis_dirty", lambda *_args: None)
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: SimpleNamespace(
        list_libraries=lambda: [
            {"id": "first", "type": "local", "root_path": str(tmp_path)},
            {"id": "second", "type": "local", "root_path": str(tmp_path)},
        ],
    ))

    class BlockingObserver:
        stopped = False

        def __init__(self):
            observers.append(self)

        def schedule(self, handler, *_args, **_kwargs):
            self.handler = handler

        def start(self):
            entered.set()
            assert release.wait(2)

        def stop(self):
            self.stopped = True

        def join(self, **_kwargs):
            pass

    monkeypatch.setattr(watcher_module, "Observer", BlockingObserver)
    driver.start(background=True)
    try:
        assert entered.wait(1)
        assert driver.diagnostics()["startup_state"] == "starting"
        driver.start(background=True)
        driver.stop(timeout=0.01)
        assert driver.diagnostics()["startup_state"] == "stopping"
    finally:
        release.set()
        assert driver._startup_done.wait(2)
        driver.stop(timeout=0.1)
    assert len(observers) == 1
    assert observers[0].stopped
    assert driver.diagnostics()["startup_state"] == "stopped"
    assert not driver.diagnostics()["running"]
    assert not driver.diagnostics()["live_events_available"]


def test_watcher_background_registration_failure_is_reported(monkeypatch, tmp_path):
    driver = watcher_module.LibraryIndexWatcherDriver()
    monkeypatch.setattr(driver, "_restore_redis_dirty", lambda *_args: None)
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: SimpleNamespace(
        list_libraries=lambda: [{"id": "first", "type": "local", "root_path": str(tmp_path)}],
    ))

    class FailedObserver:
        def schedule(self, *_args, **_kwargs):
            raise RuntimeError("注册失败")

        def stop(self):
            pass

        def join(self, **_kwargs):
            pass

    monkeypatch.setattr(watcher_module, "Observer", FailedObserver)
    driver.start(background=True)
    assert driver._startup_done.wait(2)
    assert driver.diagnostics()["startup_state"] == "failed"
    assert driver.diagnostics()["start_error"] == "注册失败"
    assert not driver.diagnostics()["running"]


def test_watcher_keeps_move_and_delete_events_during_background_start(monkeypatch, tmp_path):
    driver = watcher_module.LibraryIndexWatcherDriver()
    root = str(tmp_path)
    source = str(tmp_path / "社团" / "旧作品")
    target = str(tmp_path / "社团" / "新作品")
    deleted = str(tmp_path / "社团" / "已删除作品")
    monkeypatch.setattr(driver, "_restore_redis_dirty", lambda *_args: None)
    monkeypatch.setattr(driver, "_run", lambda: driver._stop_event.wait(2))
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: SimpleNamespace(
        list_libraries=lambda: [{"id": "first", "type": "local", "root_path": root}],
    ))
    monkeypatch.setattr(watcher_module, "get_library_index_mutation_service", lambda: SimpleNamespace(
        should_suppress_watcher=lambda *_args: False,
    ))
    monkeypatch.setattr(watcher_module, "get_redis_service", lambda: SimpleNamespace(
        upsert_library_index_dirty_paths_sync=lambda *_args, **_kwargs: None,
    ))

    class InitializingObserver:
        def schedule(self, handler, *_args, **_kwargs):
            self.handler = handler

        def start(self):
            self.handler.on_any_event(SimpleNamespace(
                event_type="moved", src_path=source, dest_path=target, is_directory=True,
            ))
            self.handler.on_any_event(SimpleNamespace(
                event_type="deleted", src_path=deleted, is_directory=True,
            ))

        def stop(self):
            pass

        def join(self, **_kwargs):
            pass

    monkeypatch.setattr(watcher_module, "Observer", InitializingObserver)
    driver.start(background=True)
    try:
        assert driver._startup_done.wait(2)
        assert driver.diagnostics()["startup_state"] == "ready"
        assert set(driver._dirty["first"]) == {source, target, deleted}
    finally:
        driver.stop(timeout=0.1)
