"""全局资源预算：给跨业务慢资源做轻量背压。

这里只负责发令牌，不掺业务语义。调用方应只在实际占用资源的区间持有，
避免在持有一个预算时再等待另一个预算造成死锁。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from datetime import datetime
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

from ..config.settings import get_config

logger = logging.getLogger(__name__)

RESOURCE_BUDGET_NAMES = (
    "disk_io_local",
    "archive_cpu",
    "archive_inspect",
    "remote_fs",
    "network_download",
    "database_write",
    "library_index_write",
    "bonus_probe_database_write",
)

_WAIT_LOG_THRESHOLD_SECONDS = float(os.getenv("KIKOERUMANAGER_RESOURCE_BUDGET_WAIT_LOG_SECONDS", "1.0") or 1.0)


@dataclass(frozen=True)
class _BudgetState:
    limit: int
    semaphore: _AsyncBudgetLimiter


@dataclass(frozen=True)
class _SyncBudgetState:
    limit: int
    semaphore: _SyncBudgetLimiter


class _AsyncBudgetLimiter:
    """整笔分配权重；缩容保留在途令牌，取消归还已经发出的许可。"""

    def __init__(self, capacity):
        self.capacity = capacity
        self.active = 0
        self.waiters = []
        self.loop = asyncio.get_running_loop()

    def resize(self, capacity):
        self.capacity = capacity
        self._wake()

    def _wake(self):
        while self.waiters:
            future, weight = self.waiters[0]
            if future.done():
                self.waiters.pop(0)
                continue
            amount = min(weight, self.capacity)
            if self.active + amount > self.capacity:
                break
            self.waiters.pop(0)
            self.active += amount
            future.set_result(amount)

    async def acquire(self, weight):
        future = self.loop.create_future()
        entry = (future, weight)
        self.waiters.append(entry)
        self._wake()
        try:
            return await asyncio.shield(future)
        except BaseException:
            if future.done() and not future.cancelled():
                self.release(future.result())
            else:
                future.cancel()
                if entry in self.waiters:
                    self.waiters.remove(entry)
                self._wake()
            raise

    def release(self, amount):
        self.active -= amount
        self._wake()


class _SyncBudgetLimiter:
    def __init__(self, capacity):
        self.capacity = capacity
        self.active = 0
        self.waiters = []
        self.condition = threading.Condition()

    def resize(self, capacity):
        with self.condition:
            self.capacity = capacity
            self.condition.notify_all()

    def acquire(self, weight):
        entry = object()
        with self.condition:
            self.waiters.append(entry)
            try:
                while True:
                    amount = min(weight, self.capacity)
                    if self.waiters[0] is entry and self.active + amount <= self.capacity:
                        self.active += amount
                        return amount
                    self.condition.wait()
            finally:
                self.waiters.remove(entry)
                self.condition.notify_all()

    def release(self, amount):
        with self.condition:
            self.active -= amount
            self.condition.notify_all()


class ResourceBudgetService:
    def __init__(self) -> None:
        self._states: dict[str, _BudgetState] = {}
        self._sync_states: dict[str, _SyncBudgetState] = {}
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

    def _configured_limit(self, resource: str) -> int:
        cfg = getattr(get_config(), "resource_budget", None)
        if cfg is None or not bool(getattr(cfg, "enabled", True)):
            return 0
        try:
            limit = max(0, int(getattr(cfg, resource, 0) or 0))
        except Exception:
            return 0
        # 数据库写入仍保留轻量背压，避免操作历史 / 任务中心批量写把连接池打满。
        # 库存索引使用独立 budget，避免后台索引追赶反压正常业务流程。
        if resource in {"database_write", "library_index_write", "bonus_probe_database_write"}:
            return max(1, limit)
        return limit

    async def _semaphore_for(self, resource: str) -> _AsyncBudgetLimiter | None:
        limit = self._configured_limit(resource)
        state = self._states.get(resource)
        if state and state.semaphore.loop is not asyncio.get_running_loop():
            if state.semaphore.active or state.semaphore.waiters:
                raise RuntimeError("资源预算仍被其他事件循环占用")
            self._states.pop(resource)
            state = None
        if limit <= 0 and state is None:
            return None
        if state and state.limit == limit:
            return state.semaphore
        async with self._lock:
            state = self._states.get(resource)
            if state and state.limit == limit:
                return state.semaphore
            semaphore = state.semaphore if state else _AsyncBudgetLimiter(max(1, limit))
            # 保留在途计数；关闭预算时也唤醒旧等待者，重新开启后仍承认在途工作。
            semaphore.resize(limit if limit > 0 else 2**31 - 1)
            self._states[resource] = _BudgetState(limit=limit, semaphore=semaphore)
            logger.info("[资源预算] %s 并发上限: %s", resource, limit)
            return semaphore

    def _sync_semaphore_for(self, resource: str) -> _SyncBudgetLimiter | None:
        limit = self._configured_limit(resource)
        with self._sync_lock:
            state = self._sync_states.get(resource)
            if limit <= 0 and state is None:
                return None
            if state and state.limit == limit:
                return state.semaphore
            semaphore = state.semaphore if state else _SyncBudgetLimiter(max(1, limit))
            semaphore.resize(limit if limit > 0 else 2**31 - 1)
            self._sync_states[resource] = _SyncBudgetState(limit=limit, semaphore=semaphore)
            logger.info("[资源预算] %s 同步并发上限: %s", resource, limit)
            return semaphore

    @contextlib.asynccontextmanager
    async def acquire(self, resource: str, *, weight: int = 1, reason: str = "") -> AsyncIterator[None]:
        """获取资源预算。

        weight 一次取得全部令牌；默认权重 1。配置为 0 或禁用时直接放行。
        """
        semaphore = await self._semaphore_for(resource)
        if semaphore is None:
            yield
            return
        amount = max(1, int(weight or 1))

        acquired = 0
        wait_started_at = time.monotonic()
        try:
            acquired = await semaphore.acquire(amount)
            waited = time.monotonic() - wait_started_at
            if waited >= _WAIT_LOG_THRESHOLD_SECONDS > 0:
                logger.warning(
                    "[资源预算] 等待 %.3fs resource=%s weight=%s reason=%s",
                    waited,
                    resource,
                    amount,
                    reason or "-",
                )
            if reason:
                logger.debug("[资源预算] acquire %s weight=%s reason=%s", resource, amount, reason)
            yield
        finally:
            semaphore.release(acquired)

    @contextlib.contextmanager
    def acquire_sync(self, resource: str, *, weight: int = 1, reason: str = "") -> Iterator[None]:
        """同步线程里的资源预算获取，用于后台 writer / maintenance 线程。"""
        semaphore = self._sync_semaphore_for(resource)
        if semaphore is None:
            yield
            return
        amount = max(1, int(weight or 1))

        acquired = 0
        wait_started_at = time.monotonic()
        try:
            acquired = semaphore.acquire(amount)
            waited = time.monotonic() - wait_started_at
            if waited >= _WAIT_LOG_THRESHOLD_SECONDS > 0:
                logger.warning(
                    "[资源预算] 等待 %.3fs resource=%s weight=%s reason=%s",
                    waited,
                    resource,
                    amount,
                    reason or "-",
                )
            if reason:
                logger.debug("[资源预算] acquire_sync %s weight=%s reason=%s", resource, amount, reason)
            yield
        finally:
            semaphore.release(acquired)

    async def refresh(self):
        """由调度循环应用最新上限，同时唤醒已有等待者。"""
        for resource in list(self._states):
            await self._semaphore_for(resource)
        for resource in list(self._sync_states):
            self._sync_semaphore_for(resource)

    def snapshot(self) -> dict[str, object]:
        """返回当前资源预算状态，供诊断接口和压测调参使用。"""
        cfg = getattr(get_config(), "resource_budget", None)
        enabled = bool(getattr(cfg, "enabled", True)) if cfg is not None else False
        resources: dict[str, dict[str, int | bool]] = {}
        for resource in RESOURCE_BUDGET_NAMES:
            configured_limit = self._configured_limit(resource)
            state = self._states.get(resource)
            sync_state = self._sync_states.get(resource)
            active_limit = int(state.limit) if state else 0
            active = state.semaphore.active if state else 0
            available = max(0, active_limit - active)
            waiters = state.semaphore.waiters if state else None
            waiting = sum(1 for waiter, _ in list(waiters or []) if not waiter.done())
            sync_active_limit = int(sync_state.limit) if sync_state else 0
            if sync_state:
                with sync_state.semaphore.condition:
                    sync_active = sync_state.semaphore.active
                    sync_waiting = len(sync_state.semaphore.waiters)
            else:
                sync_active = sync_waiting = 0
            resources[resource] = {
                "configured_limit": configured_limit,
                "active_limit": active_limit + sync_active_limit,
                "active": active + sync_active,
                "available": available + max(0, sync_active_limit - sync_active),
                "waiting": waiting + sync_waiting,
                "passthrough": configured_limit <= 0,
            }
        return {
            "enabled": enabled,
            "resources": resources,
            "generated_at": datetime.now().isoformat(),
        }


_resource_budget_service: ResourceBudgetService | None = None


def get_resource_budget_service() -> ResourceBudgetService:
    global _resource_budget_service
    if _resource_budget_service is None:
        _resource_budget_service = ResourceBudgetService()
    return _resource_budget_service
