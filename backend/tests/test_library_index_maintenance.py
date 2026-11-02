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
from app.core.library_index.snapshot_store import SnapshotRebuildWriter
from app.core.library_index.snapshot_store import SnapshotStore


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


def test_rjcode_miss_does_not_repair_legacy_rows():
    store = SnapshotStore(session_factory=Mock())
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = []
    store._active_view_query = Mock(return_value=query)
    store._repair_missing_rjcode_rows = Mock(side_effect=AssertionError("不应在查询时修复旧数据"))

    assert store.find_by_rjcode(None, "RJ123456") == []
    store._repair_missing_rjcode_rows.assert_not_called()


def test_periodic_maintenance_does_not_run_legacy_rjcode_backfill(monkeypatch):
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

    result = service.run_periodic_maintenance()

    store.backfill_missing_rjcodes.assert_not_called()
    assert "rjcodes" not in result
    assert budget.acquire_count == 0


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


def test_periodic_maintenance_preserves_generation_cleanup_and_status_repair(monkeypatch):
    store = Mock()
    store.backfill_missing_rjcodes.side_effect = [
        {"scanned": 2, "repaired": 0, "repaired_by_library": {}, "has_more": True},
        {"scanned": 1, "repaired": 1, "repaired_by_library": {"library-1": 1}, "has_more": False},
    ]
    service = LibraryIndexService(store=store)
    monkeypatch.setattr(service, "cleanup_retired_generations", Mock(return_value=0))
    monkeypatch.setattr(service, "repair_status_statistics", Mock(return_value={"repaired": 0, "libraries": {}}))
    result = service.run_periodic_maintenance()
    store.backfill_missing_rjcodes.assert_not_called()
    assert "rjcodes" not in result
    service.cleanup_retired_generations.assert_called_once()
    service.repair_status_statistics.assert_called_once()


@pytest.mark.parametrize("changes", [(1, 0, 0), (0, 4999, 0), (0, 0, 5000), (2000, 2000, 1000), (0, 0, 0)])
def test_staging_maintenance_uses_actual_changed_rows(changes):
    writer = object.__new__(SnapshotRebuildWriter)
    writer._store = Mock()
    writer.library_id = "library-1"
    writer.chunk_size = 5000
    # 十万条扫描结果只有少量变化时，不应全表维护；删除也计入变化量。
    results = [{"total_entries": 100000}, *sum(([count, 0] if count else [0] for count in changes), [])]
    if any(changes):
        results.append(None)
    writer._execute_write = Mock(side_effect=results)

    result = writer.finish()

    assert (result["inserted"], result["updated"], result["deleted"]) == changes
    assert writer._store.analyze_entries_for_query_planner.call_count == int(sum(changes) >= 5000)
    assert writer._store._invalidate_children_total_cache.call_count == int(any(changes))
