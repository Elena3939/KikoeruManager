"""合并阶段日志；发布后重试只恢复收口，不再生成目录。"""
import hashlib
import json
import os
import time

from .file_move_protocol import atomic_json
from .staged_file_move import _journal_root, _operation_lock, snapshot


class MergeJournal:
    def __init__(self, conflict_id):
        root = _journal_root() / "merges"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / (hashlib.sha256(str(conflict_id).encode()).hexdigest() + ".json")
        self.record = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def save(self, **fields):
        self.record = {**(self.record or {}), **fields}
        atomic_json(self.path, self.record)

    def reload(self):
        self.record = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def abandon(self):
        from .file_move_protocol import fsync_directory
        import uuid
        self.path.rename(self.path.with_suffix(".abandoned-" + uuid.uuid4().hex + ".json"))
        fsync_directory(str(self.path.parent))
        self.record = None

    def lock(self, target):
        key = hashlib.sha256(os.fsencode(os.path.normcase(os.path.abspath(target)))).hexdigest()
        return _operation_lock(self.path.parent / (key + ".lock"))

    def phase(self, state, **fields):
        now = time.time()
        record = self.record or {}
        timings = dict(record.get("phase_seconds", {}))
        if record.get("state") and record.get("phase_started_at"):
            previous = record["state"]
            timings[previous] = timings.get(previous, 0) + max(0, now - record["phase_started_at"])
        self.save(state=state, phase_started_at=now, phase_seconds=timings, **fields)

    def verify_target(self):
        expected = self.record.get("target_manifest")
        if expected is None or snapshot(self.record["target"]) != expected:
            raise RuntimeError("已发布合并目标发生变化，拒绝继续清理来源")
