"""源文件改名的持久交接；完整计划先落库，再执行不可覆盖的移动。"""

import asyncio
import os
from contextvars import ContextVar
from datetime import timedelta

from .input_scan_repository import (
    SourceChanged, check_source_claims, path_key, source_lock,
)
from .input_stability import sample_sources
from ..models.database import (
    InputScanCandidate, InputScanEntry, InputScanRun, InputSourceClaim,
    Task as TaskRecord, get_local_now,
)


source_rename_handler = ContextVar("input_source_rename_handler", default=None)


class SourceRenameUnresolved(ValueError):
    """计划已登记但归属尚未核清，保留新旧路径占用。"""


def rename_sources_sync(pairs):
    pairs = [(os.fspath(old), os.fspath(new)) for old, new in pairs if old != new]
    handler = source_rename_handler.get()
    if handler is not None:
        return handler(pairs)
    from .fs_utils import move_path_sync
    for old, new in pairs:
        move_path_sync(old, new)


async def rename_sources(pairs):
    work = asyncio.create_task(asyncio.to_thread(rename_sources_sync, pairs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        # 文件系统动作退出之前不能释放候选和源占用。
        await work
        raise


class InputSourceRenamer:
    def __init__(self, repository, candidate, task=None):
        self.repository, self.candidate, self.task = repository, candidate, task

    def _locked(self, db):
        source_lock(db)
        run = db.query(InputScanRun).filter_by(
            id=self.candidate["scan_id"],
        ).with_for_update().one()
        row = db.query(InputScanCandidate).filter_by(
            id=self.candidate["id"],
        ).with_for_update().one()
        return run, row

    def __call__(self, pairs):
        pairs = [(os.path.abspath(old), os.path.abspath(new)) for old, new in pairs]
        pairs = [(old, new) for old, new in pairs if path_key(old) != path_key(new)]
        if not pairs:
            return
        if not {old for old, _ in pairs} & set(self.candidate["members"]):
            # 嵌套压缩包属于解压输出，沿用移动工具自身的恢复记录。
            from .fs_utils import move_path_sync
            for old, new in pairs:
                move_path_sync(old, new)
            return
        if len({path_key(new) for _, new in pairs}) != len(pairs):
            raise ValueError("源文件改名目标重复")
        with self.repository.session_factory.begin() as db:
            run, row = self._locked(db)
            if (row.preparation or {}).get("normalization", {}).get("status") == "prepared":
                raise SourceRenameUnresolved("源文件改名尚未核对完成")
            if not row.task_id and (run.cancel_requested or row.version != self.candidate["version"]):
                raise ValueError("扫描已取消或候选已变化")
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            members = [item.source_path for item in entries]
            if not {old for old, _ in pairs} <= set(members):
                raise ValueError("改名源不属于当前候选成员")
            if any(os.path.dirname(old) != os.path.dirname(new) for old, new in pairs):
                raise ValueError("源文件规范化只能在原目录改名")
            if any(os.path.lexists(new) for _, new in pairs):
                raise FileExistsError("源文件改名目标已存在")
            if any(os.path.islink(old) for old, _ in pairs):
                raise ValueError("源文件规范化不接受符号链接")
            owner_type, owner_id = ("task", row.task_id) if row.task_id else ("candidate", row.id)
            check_source_claims(
                db, [*members, *(new for _, new in pairs)],
                owner_type=owner_type, owner_id=owner_id, task_id=row.task_id or "",
            )
            fingerprints, reason = sample_sources(members)
            evidence = (self.task.task_metadata or {}).get("input_stability", {}) if self.task else row.evidence
            if reason or fingerprints != (evidence or {}).get("fingerprints"):
                raise SourceChanged("源文件改名前证据变化，必须重新采样")
            plan = {
                "status": "prepared", "previous_state": row.state,
                "source_path": row.source_path, "evidence": evidence,
                "pairs": [{"old": old, "new": new, "fingerprint": fingerprints[old]} for old, new in pairs],
            }
            row.preparation = {**(row.preparation or {}), "normalization": plan}
            if not row.task_id:
                row.state = "normalizing"
            row.version += 1
            for path in [*members, *(new for _, new in pairs)]:
                db.merge(InputSourceClaim(
                    path_key=path_key(path), source_path=path, owner_type=owner_type, owner_id=owner_id,
                ))
            self.repository._touch(run)
            self.candidate.update(self.repository._candidate_dict(row, entries))
        self.reconcile()

    def reconcile(self):
        """仅对身份可证明的旧/新文件继续动作；双存在和替换都必须停止。"""
        with self.repository.session_factory() as db:
            row = db.get(InputScanCandidate, self.candidate["id"])
            plan = (row.preparation or {}).get("normalization") or {}
        if plan.get("status") != "prepared":
            return
        from .fs_utils import move_path_sync
        try:
            # 所有卷先核对，再开始移动，避免已知冲突时继续改动其它卷。
            moves = []
            for item in plan["pairs"]:
                old, new = item["old"], item["new"]
                old_exists, new_exists = os.path.lexists(old), os.path.lexists(new)
                if old_exists == new_exists:
                    raise SourceRenameUnresolved("源文件改名中断：新旧路径归属不明确")
                current = old if old_exists else new
                fingerprints, reason = sample_sources([current])
                if reason or fingerprints[current] != item["fingerprint"]:
                    raise SourceRenameUnresolved("源文件改名中断：文件身份已变化")
                if old_exists:
                    moves.append((old, new))
            for old, new in moves:
                move_path_sync(old, new)
            self._complete(plan)
        except (OSError, SourceChanged) as exc:
            raise SourceRenameUnresolved(f"源文件改名未完成：{exc}") from exc

    def _complete(self, plan):
        mapping = {item["old"]: item["new"] for item in plan["pairs"]}
        record_revision = 0
        with self.repository.session_factory.begin() as db:
            run, row = self._locked(db)
            if (row.preparation or {}).get("normalization") != plan:
                raise SourceRenameUnresolved("源文件改名计划已变化")
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            paths = [mapping.get(item.source_path, item.source_path) for item in entries]
            fingerprints, reason = sample_sources(paths)
            expected = {
                mapping.get(path, path): value
                for path, value in plan["evidence"]["fingerprints"].items()
            }
            if reason or fingerprints != expected:
                raise SourceRenameUnresolved("源文件改名后身份核对失败")
            evidence = {**plan["evidence"], "fingerprints": fingerprints}
            for entry in entries:
                if entry.source_path in mapping:
                    entry.source_path = mapping[entry.source_path]
                    entry.path_key = path_key(entry.source_path)
                entry.fingerprint = fingerprints[entry.source_path]
            row.source_path = mapping.get(row.source_path, row.source_path)
            row.evidence = evidence
            row.preparation = {
                **row.preparation, "normalization": {**plan, "status": "completed"},
                "source_aliases": [
                    *(row.preparation or {}).get("source_aliases", []),
                    *[{"old": old, "new": new} for old, new in mapping.items()],
                ],
            }
            if not row.task_id:
                if run.cancel_requested:
                    row.state = "cancelled"
                else:
                    row.state = plan["previous_state"]
                    row.reason = None
                    row.next_check_at = get_local_now()
                    if row.deadline < row.next_check_at:
                        from ..config.settings import get_config
                        row.deadline = row.next_check_at + timedelta(
                            seconds=get_config().input_scan.stable_timeout_seconds,
                        )
                    if run.scan_status in {"completed", "failed", "interrupted"}:
                        run.scan_status = "running"
            row.version += 1
            owner_type, owner_id = ("task", row.task_id) if row.task_id else ("candidate", row.id)
            db.query(InputSourceClaim).filter(
                InputSourceClaim.owner_type == owner_type, InputSourceClaim.owner_id == owner_id,
                InputSourceClaim.path_key.in_([path_key(old) for old in mapping]),
            ).delete(synchronize_session=False)
            record = db.get(TaskRecord, row.task_id) if row.task_id else None
            if record:
                record.source_path = row.source_path
                record.task_metadata = {
                    **record.task_metadata, "input_members": paths, "input_stability": evidence,
                    "_input_snapshot_revision": int(
                        (record.task_metadata or {}).get("_input_snapshot_revision", 0)
                    ) + 1,
                }
                record_revision = record.task_metadata["_input_snapshot_revision"]
                resume_status = row.preparation.get("normalization_resume_status")
                if record.status == "paused" and resume_status:
                    record.status = "pending" if resume_status in {"pending", "processing"} else resume_status
                    record.current_step, record.error_message = "源文件改名已核对", None
                    row.preparation = {
                        key: value for key, value in row.preparation.items()
                        if key != "normalization_resume_status"
                    }
                    if record.status == "pending":
                        self.repository._outbox(
                            db, run.id, "task_dispatch",
                            f"input-task:{record.id}:normalization:{row.version}",
                            {"task_id": record.id},
                        )
            elif run.cancel_requested:
                db.query(InputSourceClaim).filter_by(
                    owner_type=owner_type, owner_id=owner_id,
                ).delete(synchronize_session=False)
            self.repository._touch(run)
            self.candidate.update(self.repository._candidate_dict(row, entries))
        if self.task:
            self.task.task_metadata["input_members"] = paths
            self.task.task_metadata["input_stability"] = evidence
            self.task.source_path = self.candidate["source_path"]
            self.task._input_snapshot_revision = max(
                getattr(self.task, "_input_snapshot_revision", 0), record_revision,
            )
            self.task.touch_metadata()
