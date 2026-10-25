"""汇总多来源上传运行态；速度和剩余时间只在后端计算。"""
import math
import time


class UploadTaskRuntime:
    def __init__(self, total_bytes: int, total_files: int):
        self.total_bytes = total_bytes
        self.total_files = total_files
        self.sources: dict[str, dict] = {}
        self.transferred_bytes = 0
        self.completed_files = 0

    def update(self, snapshot: dict) -> dict:
        source = str(snapshot.get("current_source_dir") or "")
        previous = self.sources.get(source, {})
        self.transferred_bytes += max(0, int(snapshot.get("transferred_bytes") or 0)) - max(0, int(previous.get("transferred_bytes") or 0))
        self.completed_files += int(snapshot.get("completed_files") or 0) - int(previous.get("completed_files") or 0)
        self.sources[source] = dict(snapshot)
        transferred = min(self.total_bytes, self.transferred_bytes)
        speed = max(0, int(snapshot.get("speed_bytes_per_sec") or 0))
        if snapshot.get("phase") != "uploading":
            speed = 0
        remaining = max(0, self.total_bytes - transferred)
        return {
            **snapshot,
            "total_bytes": self.total_bytes,
            "total_files": self.total_files,
            "transferred_bytes": transferred,
            "completed_files": self.completed_files,
            "speed_bytes_per_sec": speed,
            "backend_speed_bytes_per_sec": speed,
            "eta_seconds": math.ceil(remaining / speed) if speed > 0 and remaining > 0 else None,
            "snapshot_at_ms": time.time_ns() // 1_000_000,
        }
