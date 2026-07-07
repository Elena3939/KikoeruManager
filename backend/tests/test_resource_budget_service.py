import asyncio
import threading
import time

from app.core.resource_budget_service import ResourceBudgetService


class _BudgetConfig:
    enabled = True
    network_download = 1
    remote_fs = 2
    database_write = 1
    library_index_write = 1
    bonus_probe_database_write = 1


class _Config:
    resource_budget = _BudgetConfig()


def test_resource_budget_limits_concurrent_acquire(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    service = ResourceBudgetService()

    async def run():
        entered = []

        async def worker(index):
            async with service.acquire("network_download", reason=f"test-{index}"):
                entered.append((index, time.monotonic()))
                await asyncio.sleep(0.05)

        started = time.monotonic()
        await asyncio.gather(worker(1), worker(2))
        return started, entered

    started, entered = asyncio.run(run())
    assert len(entered) == 2
    assert entered[0][0] == 1
    assert entered[1][1] - started >= 0.04


def test_resource_budget_zero_limit_is_passthrough(monkeypatch):
    class DisabledBudget:
        enabled = True
        network_download = 0

    class DisabledConfig:
        resource_budget = DisabledBudget()

    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: DisabledConfig())
    service = ResourceBudgetService()

    async def run():
        entered = []

        async def worker(index):
            async with service.acquire("network_download"):
                entered.append(index)
                await asyncio.sleep(0.01)

        await asyncio.gather(*(worker(index) for index in range(4)))
        return entered

    assert sorted(asyncio.run(run())) == [0, 1, 2, 3]


def test_resource_budget_database_write_zero_is_serialized(monkeypatch):
    class Budget:
        enabled = True
        database_write = 0
        library_index_write = 0

    class Config:
        resource_budget = Budget()

    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: Config())
    service = ResourceBudgetService()

    snapshot = service.snapshot()

    assert snapshot["resources"]["database_write"]["configured_limit"] == 1
    assert snapshot["resources"]["database_write"]["passthrough"] is False
    assert snapshot["resources"]["library_index_write"]["configured_limit"] == 1
    assert snapshot["resources"]["library_index_write"]["passthrough"] is False
    assert snapshot["resources"]["bonus_probe_database_write"]["configured_limit"] == 1
    assert snapshot["resources"]["bonus_probe_database_write"]["passthrough"] is False


def test_resource_budget_snapshot_reports_active_tokens(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    service = ResourceBudgetService()

    async def run():
        async with service.acquire("remote_fs", reason="snapshot-test"):
            return service.snapshot()

    snapshot = asyncio.run(run())
    remote_fs = snapshot["resources"]["remote_fs"]

    assert snapshot["enabled"] is True
    assert remote_fs["configured_limit"] == 2
    assert remote_fs["active_limit"] == 2
    assert remote_fs["active"] == 1
    assert remote_fs["available"] == 1
    assert remote_fs["waiting"] == 0
    assert remote_fs["passthrough"] is False
    assert snapshot["resources"]["database_write"]["configured_limit"] == 1
    assert snapshot["resources"]["library_index_write"]["configured_limit"] == 1
    assert snapshot["resources"]["bonus_probe_database_write"]["configured_limit"] == 1


def test_resource_budget_snapshot_reports_waiting_tokens(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    service = ResourceBudgetService()

    async def run():
        holder_ready = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder():
            async with service.acquire("network_download", reason="holder"):
                holder_ready.set()
                await release_holder.wait()

        async def waiter():
            async with service.acquire("network_download", reason="waiter"):
                return

        holder_task = asyncio.create_task(holder())
        await holder_ready.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        snapshot = service.snapshot()
        release_holder.set()
        await asyncio.gather(holder_task, waiter_task)
        return snapshot

    network_download = asyncio.run(run())["resources"]["network_download"]

    assert network_download["configured_limit"] == 1
    assert network_download["active"] == 1
    assert network_download["available"] == 0
    assert network_download["waiting"] == 1


def test_resource_budget_waiter_actually_waits(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    monkeypatch.setattr("app.core.resource_budget_service._WAIT_LOG_THRESHOLD_SECONDS", 0.001)
    service = ResourceBudgetService()

    async def run():
        holder_ready = asyncio.Event()
        release_holder = asyncio.Event()
        waiting_snapshot = None
        waiter_entered_at = None

        async def holder():
            async with service.acquire("network_download", reason="holder"):
                holder_ready.set()
                await release_holder.wait()

        async def waiter():
            nonlocal waiter_entered_at
            async with service.acquire("network_download", reason="slow-wait"):
                waiter_entered_at = time.monotonic()
                return

        holder_task = asyncio.create_task(holder())
        await holder_ready.wait()
        waiter_task = asyncio.create_task(waiter())
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            waiting_snapshot = service.snapshot()["resources"]["network_download"]
            if waiting_snapshot["waiting"] >= 1:
                break
            await asyncio.sleep(0.005)
        assert waiting_snapshot is not None
        assert waiting_snapshot["waiting"] >= 1
        assert not waiter_task.done()
        release_holder.set()
        await asyncio.gather(holder_task, waiter_task)
        assert waiter_entered_at is not None

    asyncio.run(run())


def test_resource_budget_sync_acquire_limits_concurrent_threads(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    service = ResourceBudgetService()
    entered = []
    release_first = threading.Event()

    def worker(index):
        with service.acquire_sync("database_write", reason=f"sync-{index}"):
            entered.append((index, time.monotonic()))
            if index == 1:
                release_first.wait(timeout=1)

    first = threading.Thread(target=worker, args=(1,))
    second = threading.Thread(target=worker, args=(2,))
    first.start()
    time.sleep(0.03)
    started_second_at = time.monotonic()
    second.start()
    time.sleep(0.05)

    assert len(entered) == 1

    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert [item[0] for item in entered] == [1, 2]
    assert entered[1][1] >= started_second_at


def test_resource_budget_snapshot_reports_sync_active_and_waiting(monkeypatch):
    monkeypatch.setattr("app.core.resource_budget_service.get_config", lambda: _Config())
    service = ResourceBudgetService()
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def holder():
        with service.acquire_sync("database_write", reason="sync-holder"):
            holder_ready.set()
            release_holder.wait(timeout=1)

    def waiter():
        with service.acquire_sync("database_write", reason="sync-waiter"):
            return

    holder_thread = threading.Thread(target=holder)
    waiter_thread = threading.Thread(target=waiter)
    holder_thread.start()
    assert holder_ready.wait(timeout=1)
    waiter_thread.start()
    time.sleep(0.05)

    database_write = service.snapshot()["resources"]["database_write"]

    release_holder.set()
    holder_thread.join(timeout=1)
    waiter_thread.join(timeout=1)

    assert database_write["configured_limit"] == 1
    assert database_write["active_limit"] == 1
    assert database_write["active"] == 1
    assert database_write["available"] == 0
    assert database_write["waiting"] == 1
