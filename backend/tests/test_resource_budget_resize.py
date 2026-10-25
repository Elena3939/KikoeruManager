"""带权重申请与热更新必须保留在途许可。"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.core.resource_budget_service import ResourceBudgetService


def test_sync_weighted_resize_preserves_inflight():
    from app.core.resource_budget_service import _SyncBudgetLimiter

    limiter = _SyncBudgetLimiter(3)
    assert limiter.acquire(2) == 2
    entered = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        def acquire():
            entered.set()
            return limiter.acquire(2)
        waiting = executor.submit(acquire)
        try:
            assert entered.wait(1)
            limiter.resize(1)
            assert limiter.active == 2 and not waiting.done()
            limiter.resize(4)
            assert waiting.result(timeout=1) == 2
            assert limiter.active == 4
        finally:
            limiter.resize(4)
            limiter.release(4 if waiting.done() else 2)
    assert limiter.active == 0


@pytest.mark.asyncio
async def test_weighted_wait_cancel_and_resize(monkeypatch):
    budget = SimpleNamespace(enabled=True, remote_fs=3)
    monkeypatch.setattr("app.core.resource_budget_service.get_config",
                        lambda: SimpleNamespace(resource_budget=budget))
    service = ResourceBudgetService()
    limiter = await service._semaphore_for("remote_fs")
    assert await limiter.acquire(2) == 2
    waiting = asyncio.create_task(limiter.acquire(2))
    await asyncio.sleep(0)
    assert limiter.active == 2
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert limiter.active == 2 and not limiter.waiters

    budget.remote_fs = 1
    await service.refresh()
    assert limiter is await service._semaphore_for("remote_fs")
    waiting = asyncio.create_task(limiter.acquire(1))
    await asyncio.sleep(0)
    assert not waiting.done()
    budget.remote_fs = 4
    await service.refresh()
    assert await asyncio.wait_for(waiting, 1) == 1
    limiter.release(3)
    assert limiter.active == 0


@pytest.mark.asyncio
async def test_disable_and_reenable_preserves_inflight(monkeypatch):
    budget = SimpleNamespace(enabled=True, remote_fs=1)
    monkeypatch.setattr("app.core.resource_budget_service.get_config",
                        lambda: SimpleNamespace(resource_budget=budget))
    service = ResourceBudgetService()
    limiter = await service._semaphore_for("remote_fs")
    await limiter.acquire(1)
    waiting = asyncio.create_task(limiter.acquire(1))
    await asyncio.sleep(0)
    budget.enabled = False
    await service.refresh()
    assert await asyncio.wait_for(waiting, 1) == 1
    budget.enabled = True
    await service.refresh()
    third = asyncio.create_task(limiter.acquire(1))
    await asyncio.sleep(0)
    assert limiter.active == 2 and not third.done()
    limiter.release(2)
    assert await asyncio.wait_for(third, 1) == 1
    limiter.release(1)


@pytest.mark.asyncio
async def test_granted_then_cancelled_returns_weight():
    from app.core.resource_budget_service import _AsyncBudgetLimiter

    limiter = _AsyncBudgetLimiter(2)
    await limiter.acquire(2)
    waiting = asyncio.create_task(limiter.acquire(2))
    await asyncio.sleep(0)
    limiter.release(2)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    assert limiter.active == 0 and not limiter.waiters
