"""库存改名的数据库等待不得占用事件循环线程。"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.api import routes


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_rename_database_wait_keeps_event_loop_responsive(monkeypatch, batch):
    main_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()

    def check_worker():
        assert threading.get_ident() != main_thread

    class Manager:
        def get_library_definition(self, library_id):
            check_worker()
            return SimpleNamespace(id=library_id, type="local", root_path="/library")

        async def rename(self, *args, **kwargs):
            return {"new_path": "/library/new"}

        async def batch_rename(self, *args, **kwargs):
            return {"results": [{"index": 0, "path": "/library/old", "new_path": "/library/new"}]}

    class Mutations:
        def prepare(self, **kwargs):
            check_worker()
            started.set()
            assert release.wait(3), "事件循环被同步数据库操作阻塞"
            return SimpleNamespace(operation_id="rename", replayed=False, state="prepared", result=None)

        def mark_filesystem_started(self, *args):
            check_worker()

        def finalize(self, *args, **kwargs):
            check_worker()
            return kwargs["actual_result"]

    class Request:
        headers = {}

        async def json(self):
            return {"library_id": "local", "path": "/library/old", "new_name": "new",
                    "items": [{"path": "/library/old", "new_name": "new"}], "skip_activity_log": True}

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(routes, "get_library_index_mutation_service", lambda: Mutations())
    monkeypatch.setattr(routes, "_invalidate_rj_subtitle_folder_summary_cache", lambda *args: None)
    endpoint = routes.batch_rename_library_browser_items if batch else routes.rename_library_browser_item
    task = asyncio.create_task(endpoint(Request()))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        release.set()
        assert await task
    finally:
        release.set()
        if not task.done():
            await task
