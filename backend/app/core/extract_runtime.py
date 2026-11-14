"""解压共享限流与父子归档链路计时；不保存密码。"""
import asyncio
import contextlib
import contextvars
import time
import uuid
import functools
import os
import hashlib
import hmac
from collections import OrderedDict
from collections.abc import MutableMapping


class ArchiveFingerprintCache(MutableMapping):
    """保留按路径使用的接口；同路径文件替换后，旧编码和方法证据立即失效。"""

    def __init__(self, max_size=2048):
        self._values = OrderedDict()
        self.max_size = max_size

    @staticmethod
    def fingerprint(path):
        from .archive_volume_utils import archive_source_identity
        return archive_source_identity(path)

    def __getitem__(self, path):
        fingerprint, value = self._values[path]
        if fingerprint != self.fingerprint(path):
            del self._values[path]
            raise KeyError(path)
        self._values.move_to_end(path)
        return value

    def __setitem__(self, path, value):
        self._values[path] = (self.fingerprint(path), value)
        self._values.move_to_end(path)
        while len(self._values) > self.max_size:
            self._values.popitem(last=False)

    def __delitem__(self, path):
        del self._values[path]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class AdjustableLimiter:
    """调整容量时保留在途计数，按先到先得唤醒等待者。"""

    def __init__(self, capacity):
        self.capacity = max(1, capacity)
        self.active = 0
        self.waiters = []

    def resize(self, capacity):
        self.capacity = max(1, capacity)
        self._wake()

    def locked(self):
        return self.active >= self.capacity

    def _wake(self):
        while self.waiters and self.active < self.capacity:
            waiter = self.waiters.pop(0)
            if not waiter.done():
                self.active += 1
                waiter.set_result(True)

    async def acquire(self):
        waiter = asyncio.get_running_loop().create_future()
        self.waiters.append(waiter)
        self._wake()
        try:
            await waiter
        except BaseException:
            if not waiter.cancelled() and waiter.done():
                self.release()
            elif waiter in self.waiters:
                self.waiters.remove(waiter)
            raise
        return True

    def release(self):
        self.active -= 1
        self._wake()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


_node = contextvars.ContextVar("extract_archive_node", default=None)
_timing = contextvars.ContextVar("extract_archive_timing", default=None)
_attempt = contextvars.ContextVar("extract_attempt", default=None)
_active_clocks = contextvars.ContextVar("extract_active_clocks", default=())
_phase_kinds = contextvars.ContextVar("extract_phase_kinds", default=())
_probe_budget = contextvars.ContextVar("extract_probe_budget", default=None)
_candidate_secret = os.urandom(32)


class ActiveClock:
    """累计实际工作时间；资源排队和用户暂停可嵌套扣除，不依赖任务诊断数据。"""

    def __init__(self):
        self.started = time.monotonic()
        self.excluded = 0.0
        self.suspended_at = None
        self.suspensions = 0

    @property
    def elapsed(self):
        ended = self.suspended_at if self.suspensions else time.monotonic()
        return max(0.0, ended - self.started - self.excluded)

    def suspend(self):
        if not self.suspensions:
            self.suspended_at = time.monotonic()
        self.suspensions += 1

    def resume(self):
        self.suspensions -= 1
        if not self.suspensions:
            self.excluded += time.monotonic() - self.suspended_at
            self.suspended_at = None


@contextlib.contextmanager
def active_clock(*, budget_seconds=None):
    clock = ActiveClock()
    token = _active_clocks.set((*_active_clocks.get(), clock))
    budget_token = _probe_budget.set((clock, budget_seconds)) if budget_seconds is not None else None
    try:
        yield clock
    finally:
        if budget_token is not None:
            _probe_budget.reset(budget_token)
        _active_clocks.reset(token)


def probe_execution_timeout(timeout):
    """取得资源后重新计算剩余工作预算；不会把排队计入进程时限。"""
    budget = _probe_budget.get()
    if budget is None:
        return timeout
    clock, limit = budget
    remaining = max(0.0, limit - clock.elapsed)
    return remaining if timeout is None else min(timeout, remaining)


@contextlib.contextmanager
def exclude_active_time():
    """在实际等待边界暂停当前协程的工作时钟，退出（含取消）后恢复。"""
    clocks = _active_clocks.get()
    for clock in clocks:
        clock.suspend()
    try:
        yield
    finally:
        for clock in reversed(clocks):
            clock.resume()


def current_archive_depth():
    """读取当前协程的归档层级，避免并行子包互相覆盖展示上下文。"""
    node = _node.get()
    return node["depth"] if node is not None else 0


def candidate_evidence(password, sources, **evidence):
    """候选证据仅限当前归档，公开记录不包含密码原文。"""
    node = _node.get()
    if node is None:
        return
    candidate_id = hmac.new(_candidate_secret, (node['id'] + '\0' + password).encode('utf-8'), hashlib.sha256).hexdigest()[:24]
    candidates = node.setdefault('password_candidates', {})
    candidate = candidates.setdefault(candidate_id, {'sources': [], 'no_password': password == ''})
    for source in sources:
        if source and source not in candidate['sources']:
            candidate['sources'].append(source)
    candidate.update(evidence)


@contextlib.contextmanager
def archive_attempt():
    token = _attempt.set(uuid.uuid4().hex)
    try:
        yield _attempt.get()
    finally:
        _attempt.reset(token)


def node_state(state):
    node, timing = _node.get(), _timing.get()
    if node is None or timing is None:
        return
    counts = timing.setdefault("counts", {})
    previous = node.get("state")
    if previous:
        counts[previous] = max(0, counts.get(previous, 0) - 1)
    node["state"] = state
    counts[state] = counts.get(state, 0) + 1
    timing["current_archive"] = node["archive"]
    timing["current_depth"] = node["depth"]


def measured_phase(kind):
    """阶段独立计时，不能将阶段墙钟直接累加为实际进程耗时。"""
    def decorate(method):
        @functools.wraps(method)
        async def wrapped(*args, **kwargs):
            kinds = _phase_kinds.get()
            if kind in kinds:
                return await method(*args, **kwargs)
            started = time.monotonic()
            token = _phase_kinds.set((*kinds, kind))
            try:
                with active_clock() as clock:
                    try:
                        result = await method(*args, **kwargs)
                        if kind == 'probe' and len(args) >= 3:
                            candidate_evidence(args[2], [], content=result)
                        return result
                    except asyncio.CancelledError:
                        if kind == 'probe' and len(args) >= 3:
                            candidate_evidence(args[2], [], content='cancelled')
                        raise
                    finally:
                        record_event(kind, started, duration_seconds=clock.elapsed)
            finally:
                _phase_kinds.reset(token)
        return wrapped
    return decorate


@contextlib.asynccontextmanager
async def archive_node(task, path, *, root=False):
    parent = None if root else _node.get()
    metadata = task.task_metadata if task.task_metadata is not None else {}
    task.task_metadata = metadata
    if root:
        metadata["extract_timing"] = {"version": 1, "nodes": [], "chains": []}
    timing = metadata.setdefault("extract_timing", {"version": 1, "nodes": [], "chains": []})
    node = {"id": uuid.uuid4().hex, "parent_id": parent["id"] if parent else None,
            "archive": str(path), "depth": parent["depth"] + 1 if parent else 0,
            "events": [], "status": "active"}
    timing["nodes"].append(node)
    token = _node.set(node)
    timing_token = _timing.set(timing)
    node_state("preparing")
    started = time.monotonic()
    try:
        yield node
        if node["status"] == "active":
            node["status"] = "completed"
    except BaseException:
        node["status"] = "incomplete"
        raise
    finally:
        node["wall_duration_ms"] = round((time.monotonic() - started) * 1000)
        node_state(node["status"])
        _node.reset(token)
        _timing.reset(timing_token)
        if root:
            timing["wall_duration_ms"] = node["wall_duration_ms"]
            summarize(timing)


def record_event(kind, started, *, ended=None, duration_seconds=None):
    node = _node.get()
    if node is not None:
        ended = time.monotonic() if ended is None else ended
        event_id = uuid.uuid4().hex
        node["events"].append({"id": event_id, "attempt_id": _attempt.get() or event_id, "kind": kind,
                               "start": started, "end": ended,
                               "duration_ms": max(0, round((ended - started if duration_seconds is None else duration_seconds) * 1000))})
        timing = _timing.get()
        if timing is not None:
            totals = timing.setdefault("totals_ms", {})
            totals[kind] = totals.get(kind, 0) + node["events"][-1]["duration_ms"]


def summarize(timing):
    nodes = {node["id"]: node for node in timing["nodes"]}
    kinds = {e["kind"] for node in nodes.values() for e in node["events"]}
    totals = {kind: 0 for kind in ("execution", "wait", "inspect", *sorted(kinds - {"execution", "wait", "inspect"}))}
    for node in nodes.values():
        node["durations_ms"] = {kind: sum(e["duration_ms"] for e in node["events"] if e["kind"] == kind)
                                for kind in totals}
        for kind in totals:
            totals[kind] += node["durations_ms"][kind]
    timing["totals_ms"] = totals
    chains = []
    parents = {node["parent_id"] for node in nodes.values()}
    for node in nodes.values():
        if node["id"] in parents:
            continue
        chain, current = [], node
        while current:
            chain.append(current)
            current = nodes.get(current["parent_id"])
        chains.append({"node_ids": [n["id"] for n in reversed(chain)], "archive": node["archive"],
                       "durations_ms": {kind: sum(n["durations_ms"][kind] for n in chain) for kind in totals}})
    timing["chains"] = chains
