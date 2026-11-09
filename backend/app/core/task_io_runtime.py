"""任务文件操作吞吐；只记录实际读取/复制，不从百分比推算字节。"""
import asyncio
import contextvars
import ctypes
import functools
import os
import time

current_io_task = contextvars.ContextVar("current_io_task", default=None)
current_move_meter = contextvars.ContextVar("current_move_meter", default=None)


class TaskIOMeter:
    def __init__(self, task, phase, speed_kind, loop=None):
        self.task = task
        self.phase = phase
        self.speed_kind = speed_kind
        self.loop = loop
        self.last_at = time.monotonic()
        self.last_bytes = 0
        self.active = True
        self.runtime = {
            "phase": phase, "speed_kind": speed_kind, "speed_bytes_per_sec": None,
            "completed_bytes": 0, "total_bytes": 0, "io_active": True,
        }
        self._publish()

    def _publish(self):
        snapshot = dict(self.runtime)

        def apply():
            self.task.task_metadata["io_runtime"] = snapshot
            self.task.mark_changed("io_runtime")

        if self.loop:
            self.loop.call_soon_threadsafe(apply)
        else:
            apply()

    def sample(self, completed, total=0, force=False):
        now = time.monotonic()
        elapsed = now - self.last_at
        if not self.active or (not force and elapsed < 0.75):
            return
        self.runtime.update(
            completed_bytes=max(0, completed), total_bytes=max(0, total),
            speed_bytes_per_sec=max(0, completed - self.last_bytes) / max(elapsed, 0.001),
        )
        self.last_bytes, self.last_at = completed, now
        self._publish()

    def finish(self):
        if not self.active:
            return
        self.active = False
        self.runtime.update(io_active=False, speed_bytes_per_sec=None)
        self._publish()


def measured_move(operation):
    @functools.wraps(operation)
    def wrapped(*args, **kwargs):
        context = current_io_task.get()
        if not context or current_move_meter.get():
            return operation(*args, **kwargs)
        task, loop = context
        meter = TaskIOMeter(task, "move", "move", loop)
        token = current_move_meter.set(meter)
        try:
            return operation(*args, **kwargs)
        finally:
            meter.finish()
            current_move_meter.reset(token)
    return wrapped


class ProcessReadCounter:
    def __init__(self, pid):
        self.pid = pid
        self.handle = None
        if os.name == "nt":
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            self.kernel.GetProcessIoCounters.restype = wintypes.BOOL
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.OpenProcess(0x1000, False, pid)

    def read(self):
        try:
            if os.name == "nt":
                counters = (ctypes.c_ulonglong * 6)()
                if self.handle and self.kernel.GetProcessIoCounters(self.handle, ctypes.byref(counters)):
                    return counters[3]
            else:
                with open(f"/proc/{self.pid}/io", encoding="ascii") as stream:
                    # rchar 包含缓存命中的读取；read_bytes 只计物理磁盘 IO。
                    for line in stream:
                        if line.startswith("rchar:"):
                            return int(line.split(":", 1)[1])
        except (OSError, ValueError):
            pass
        return None

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


async def monitor_extract_reads(process, task):
    counter = ProcessReadCounter(process.pid)
    meter = TaskIOMeter(task, "extract", "read")
    try:
        baseline = counter.read()
        while process.returncode is None:
            await asyncio.sleep(0.75)
            value = counter.read()
            if value is not None and baseline is not None:
                meter.sample(max(0, value - baseline))
    finally:
        counter.close()
        meter.finish()
