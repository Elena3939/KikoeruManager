"""库存索引周期维护与异步重建调度回归测试。"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from unittest.mock import Mock

import pytest

import app.core.library_index.service as service_module
from app.core.library_index.service import LibraryIndexService
from app.core.library_index.types import IndexStatus


class _NonReentrantBudget:
    def __init__(self) -> None:
        self._local = threading.local()
        self.acquire_count = 0

    @contextlib.contextmanager
    def acquire_sync(self, resource: str, **_kwargs):
        if getattr(self._local, "resource", None) == resource:
            raise RuntimeError(f"资源预算发生嵌套获取: {resource}")
        self._local.resource = resource
        self.acquire_count += 1
        try:
            yield
        finally:
            self._local.resource = None


def test_periodic_rjcode_backfill_does_not_reacquire_write_budget(monkeypatch):
    budget = _NonReentrantBudget()
    store = Mock()

    def backfill_missing_rjcodes(*, limit: int):
        with budget.acquire_sync("library_index_write", reason="library_index.write"):
            assert limit == 250
            return {
                "scanned": 0,
                "repaired": 0,
                "repaired_by_library": {},
            }

    store.backfill_missing_rjcodes.side_effect = backfill_missing_rjcodes
    service = LibraryIndexService(store=store)
    monkeypatch.setattr(service_module, "get_resource_budget_service", lambda: budget)
    monkeypatch.setattr(service, "cleanup_retired_generations", Mock(return_value=0))
    monkeypatch.setattr(
        service,
        "repair_status_statistics",
        Mock(return_value={"repaired": 0, "libraries": {}}),
    )

    result = service.run_periodic_maintenance(
        rjcode_limit=250,
        rjcode_max_batches=1,
    )

    assert result["rjcodes"] == {
        "scanned": 0,
        "repaired": 0,
        "repaired_by_library": {},
        "batches": 1,
    }
    assert budget.acquire_count == 1


@pytest.mark.asyncio
async def test_schedule_rebuild_local_offloads_status_write_from_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    status_write_threads: list[int] = []
    store = Mock()

    def upsert_status(library_id: str, **_kwargs):
        status_write_threads.append(threading.get_ident())
        time.sleep(0.05)
        return IndexStatus(library_id=library_id, status="syncing")

    store.upsert_status.side_effect = upsert_status
    service = LibraryIndexService(store=store)
    rebuild_local = Mock(return_value=IndexStatus(library_id="library-1", status="ready"))
    monkeypatch.setattr(service, "rebuild_local", rebuild_local)

    heartbeat_ran = asyncio.Event()

    async def heartbeat() -> None:
        await asyncio.sleep(0.01)
        heartbeat_ran.set()

    heartbeat_task = asyncio.create_task(heartbeat())
    status = await service.schedule_rebuild_local("library-1", "/library")
    await heartbeat_task
    if service._pending_tasks:
        await asyncio.gather(*tuple(service._pending_tasks))

    assert status.status == "syncing"
    assert heartbeat_ran.is_set()
    assert len(status_write_threads) == 1
    assert status_write_threads[0] != event_loop_thread
    rebuild_local.assert_called_once_with("library-1", "/library")
