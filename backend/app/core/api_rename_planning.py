"""批量 API 重命名的进程内查询预算，避免多请求叠加放大并发。"""
import asyncio
from weakref import WeakKeyDictionary


_PLAN_LIMITS = WeakKeyDictionary()


def get_api_rename_plan_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _PLAN_LIMITS:
        _PLAN_LIMITS[loop] = asyncio.Semaphore(6)
    return _PLAN_LIMITS[loop]
