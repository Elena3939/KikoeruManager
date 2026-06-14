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
)

_WAIT_LOG_THRESHOLD_SECONDS = float(os.getenv("KIKOERUMANAGER_RESOURCE_BUDGET_WAIT_LOG_SECONDS", "1.0") or 1.0)


@dataclass(frozen=True)
class _BudgetState:
    limit: int
    semaphore: asyncio.Semaphore


@dataclass(frozen=True)
class _SyncBudgetState:
    limit: int
    semaphore: threading.BoundedSemaphore
    active: int = 0
    waiting: int = 0


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
        # 数据库写入仍保留轻量背压，避免操作历史 / 库存索引批量写把连接池打满。
        if resource == "database_write":
            return max(1, limit)
        return limit

    async def _semaphore_for(self, resource: str) -> asyncio.Semaphore | None:
        limit = self._configured_limit(resource)
        if limit <= 0:
            return None
        state = self._states.get(resource)
        if state and state.limit == limit:
            return state.semaphore
        async with self._lock:
            state = self._states.get(resource)
            if state and state.limit == limit:
                return state.semaphore
            semaphore = asyncio.Semaphore(limit)
            self._states[resource] = _BudgetState(limit=limit, semaphore=semaphore)
            logger.info("[资源预算] %s 并发上限: %s", resource, limit)
            return semaphore

    def _sync_semaphore_for(self, resource: str) -> threading.BoundedSemaphore | None:
        limit = self._configured_limit(resource)
        if limit <= 0:
            return None
        state = self._sync_states.get(resource)
        if state and state.limit == limit:
            return state.semaphore
        with self._sync_lock:
            state = self._sync_states.get(resource)
            if state and state.limit == limit:
                return state.semaphore
            semaphore = threading.BoundedSemaphore(limit)
            self._sync_states[resource] = _SyncBudgetState(limit=limit, semaphore=semaphore)
            logger.info("[资源预算] %s 同步并发上限: %s", resource, limit)
            return semaphore

    def _sync_state_add_waiting(self, resource: str, delta: int) -> None:
        with self._sync_lock:
            state = self._sync_states.get(resource)
            if not state:
                return
            self._sync_states[resource] = _SyncBudgetState(
                limit=state.limit,
                semaphore=state.semaphore,
                active=state.active,
                waiting=max(0, state.waiting + delta),
            )

    def _sync_state_add_active(self, resource: str, delta: int) -> None:
        with self._sync_lock:
            state = self._sync_states.get(resource)
            if not state:
                return
            self._sync_states[resource] = _SyncBudgetState(
                limit=state.limit,
                semaphore=state.semaphore,
                active=max(0, state.active + delta),
                waiting=state.waiting,
            )

    @contextlib.asynccontextmanager
    async def acquire(self, resource: str, *, weight: int = 1, reason: str = "") -> AsyncIterator[None]:
        """获取资源预算。

        weight 会顺序获取多个令牌；默认权重 1。配置为 0 或禁用时直接放行。
        """
        semaphore = await self._semaphore_for(resource)
        if semaphore is None:
            yield
            return
        state = self._states.get(resource)
        limit = state.limit if state else 1
        amount = min(max(1, int(weight or 1)), max(1, int(limit or 1)))

        acquired = 0
        wait_started_at = time.monotonic()
        try:
            for _ in range(amount):
                await semaphore.acquire()
                acquired += 1
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
            for _ in range(acquired):
                semaphore.release()

    @contextlib.contextmanager
    def acquire_sync(self, resource: str, *, weight: int = 1, reason: str = "") -> Iterator[None]:
        """同步线程里的资源预算获取，用于后台 writer / maintenance 线程。"""
        semaphore = self._sync_semaphore_for(resource)
        if semaphore is None:
            yield
            return
        state = self._sync_states.get(resource)
        limit = state.limit if state else 1
        amount = min(max(1, int(weight or 1)), max(1, int(limit or 1)))

        acquired = 0
        wait_started_at = time.monotonic()
        try:
            for _ in range(amount):
                self._sync_state_add_waiting(resource, 1)
                try:
                    semaphore.acquire()
                    acquired += 1
                    self._sync_state_add_active(resource, 1)
                finally:
                    self._sync_state_add_waiting(resource, -1)
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
            for _ in range(acquired):
                semaphore.release()
                self._sync_state_add_active(resource, -1)

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
            available = int(getattr(state.semaphore, "_value", 0)) if state else 0
            active = max(0, active_limit - available) if state else 0
            waiters = getattr(state.semaphore, "_waiters", None) if state else None
            waiting = sum(1 for waiter in list(waiters or []) if not waiter.done())
            sync_active_limit = int(sync_state.limit) if sync_state else 0
            sync_active = int(sync_state.active) if sync_state else 0
            sync_waiting = int(sync_state.waiting) if sync_state else 0
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
