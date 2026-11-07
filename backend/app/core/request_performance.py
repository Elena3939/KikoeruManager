"""请求分段计时；ContextVar 随 asyncio.to_thread 传播，不记录业务数据。"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

request_metrics = ContextVar("request_metrics", default=None)


def _record_span(name, started, ended):
    metrics = request_metrics.get()
    if metrics is None:
        return
    metrics[name] = round(metrics.get(name, 0.0) + (ended - started) * 1000, 2)
    if metrics.get("measurement_schema") == "circle-works-v1":
        metrics.setdefault("_span_ranges", []).append((started, ended))


def uncovered_ms(started, ended, metrics):
    """合并计时区间，计算请求中尚未覆盖的耗时。"""
    ranges = sorted(
        (max(started, left), min(ended, right))
        for left, right in metrics.get("_span_ranges", [])
        if right > started and left < ended
    )
    covered = 0.0
    range_start = range_end = None
    for left, right in ranges:
        if range_start is None:
            range_start, range_end = left, right
        elif left <= range_end:
            range_end = max(range_end, right)
        else:
            covered += range_end - range_start
            range_start, range_end = left, right
    if range_start is not None:
        covered += range_end - range_start
    return round(max(0.0, (ended - started - covered) * 1000), 2)


def timed_stage(name):
    """为整个同步读操作计时，包含提前返回。"""
    from functools import wraps

    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with measure_stage(name):
                return function(*args, **kwargs)
        return run
    return decorate


@contextmanager
def measure_stage(name):
    started = time.perf_counter()
    try:
        yield
    finally:
        _record_span(name, started, time.perf_counter())


async def run_sync_stage(name, function, *args, **kwargs):
    import asyncio

    submitted = time.perf_counter()
    metrics = request_metrics.get()
    if metrics is not None:
        metrics["thread_dispatch_count"] = metrics.get("thread_dispatch_count", 0) + 1
    worker_finished = [None]

    def run():
        metrics = request_metrics.get()
        if metrics is not None:
            started = time.perf_counter()
            _record_span(name + "_queue_ms", submitted, started)
            metrics.setdefault("thread_queue_total_ms", 0.0)
            metrics["thread_queue_total_ms"] += round((started - submitted) * 1000, 2)
        else:
            started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            finished = time.perf_counter()
            _record_span(name + "_worker_exec_ms", started, finished)
            _record_span(name + "_ms", started, finished)
            worker_finished[0] = finished

    try:
        result = await asyncio.to_thread(run)
    finally:
        resumed = time.perf_counter()
        current_metrics = request_metrics.get()
        if current_metrics is not None:
            finished = worker_finished[0] or resumed
            _record_span(name + "_loop_resume_ms", finished, resumed)
            key = name + "_stage_wall_ms"
            current_metrics[key] = round(current_metrics.get(key, 0.0) + (resumed - submitted) * 1000, 2)
    return result
