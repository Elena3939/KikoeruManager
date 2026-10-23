"""请求分段计时；ContextVar 随 asyncio.to_thread 传播，不记录业务数据。"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

request_metrics = ContextVar("request_metrics", default=None)


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
        metrics = request_metrics.get()
        if metrics is not None:
            metrics[name] = round((time.perf_counter() - started) * 1000, 2)


async def run_sync_stage(name, function, *args, **kwargs):
    import asyncio

    submitted = time.perf_counter()

    def run():
        metrics = request_metrics.get()
        if metrics is not None:
            metrics[name + "_queue_ms"] = round((time.perf_counter() - submitted) * 1000, 2)
        with measure_stage(name + "_ms"):
            return function(*args, **kwargs)

    return await asyncio.to_thread(run)
