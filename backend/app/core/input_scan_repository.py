"""扫描事实账本；所有副作用交接先在 PostgreSQL 提交，再向执行器派发。"""

import hashlib
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from ..models.database import (
    ActivityLog, ConflictWork, DeferredArchiveJob, InputScanCandidate, InputScanEntry,
    InputScanOutbox, InputScanRun, InputSourceClaim, SessionLocal,
    Task as TaskRecord, get_local_now,
)

TERMINAL = frozenset({"submitted", "routed", "skipped", "failed", "cancelled"})
SOURCE_LOCK = "kikoerumanager:deferred-archive:enqueue"


def record_first(coverage, key, value):
    """并发快照可能乱序到达，首个时间按实际事件时间归并。"""
    if value and (
        not coverage.get(key)
        or datetime.fromisoformat(value) < datetime.fromisoformat(coverage[key])
    ):
        coverage[key] = value
        return True
    return False


def path_key(path):
    normalized = os.path.normcase(os.path.abspath(path))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()


def source_lock(db):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": SOURCE_LOCK})


class SourceOccupied(RuntimeError):
    def __init__(self, owner_type, owner_id):
        super().__init__(f"{owner_type}:{owner_id}")
        self.owner_type, self.owner_id = owner_type, owner_id


class SourceChanged(ValueError):
    """源证据变化需要重新观察；与业务校验失败分开处理。"""


def check_input_claims(db, paths, *, owner_type="", owner_id="", task_id=""):
    """调用方持有 source_lock；终态且没有未解决问题的任务才释放占用。"""
    keys = {path_key(path) for path in paths}
    for claim in db.query(InputSourceClaim).filter(InputSourceClaim.path_key.in_(keys)):
        if (claim.owner_type, claim.owner_id) == (owner_type, owner_id):
            continue
        if claim.owner_type == "task" and claim.owner_id == task_id:
            continue
        if claim.owner_type == "task":
            task = db.get(TaskRecord, claim.owner_id)
            candidate = db.query(InputScanCandidate).filter_by(task_id=claim.owner_id).first()
            if candidate and (candidate.preparation or {}).get("normalization", {}).get("status") == "prepared":
                raise SourceOccupied(claim.owner_type, claim.owner_id)
            unresolved = db.query(ConflictWork.id).filter(
                ConflictWork.task_id == claim.owner_id,
                ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            ).first()
            if task and task.status in {"completed", "failed", "cancelled"} and not unresolved:
                db.delete(claim)
                continue
        raise SourceOccupied(claim.owner_type, claim.owner_id)


def check_source_claims(db, paths, *, owner_type="", owner_id="", task_id=""):
    """归档与扫描在同一事务锁下检查；不能只看各自进程内的缓存。"""
    paths = list(paths)
    keys = {path_key(path) for path in paths}
    check_input_claims(db, paths, owner_type=owner_type, owner_id=owner_id, task_id=task_id)
    for job in db.query(DeferredArchiveJob).filter(
        DeferredArchiveJob.status.in_(["pending", "processing", "waiting_retry", "failed"])
    ):
        if task_id and job.task_id == task_id:
            continue
        if keys & {path_key(item["source_path"]) for item in job.source_manifest or []}:
            raise SourceOccupied("deferred_archive", job.id)
    unresolved = db.query(ConflictWork).filter(
        ConflictWork.new_path.in_(paths), ConflictWork.status.in_(["PENDING", "PROCESSING"]),
        (ConflictWork.task_id.is_(None)) | (ConflictWork.task_id != task_id),
    ).first()
    if unresolved:
        raise SourceOccupied("problem", unresolved.id)
    active = db.query(TaskRecord).filter(
        TaskRecord.source_path.in_(paths),
        TaskRecord.status.in_(["pending", "processing", "paused", "waiting_manual", "waiting_retry"]),
        TaskRecord.id != task_id,
    ).first()
    if active:
        raise SourceOccupied("task", active.id)


class InputScanRepository:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or SessionLocal

    @staticmethod
    def _touch(run):
        run.revision += 1
        run.updated_at = get_local_now()

    @staticmethod
    def _outbox(db, scan_id, kind, key, payload):
        db.execute(insert(InputScanOutbox).values(
            id=str(uuid.uuid4()), scan_id=scan_id, event_key=key,
            kind=kind, payload=payload,
        ).on_conflict_do_nothing(index_elements=["event_key"]))

    def create_run(self, root, policy, request_key=None, *, force_new=False):
        with self.session_factory.begin() as db:
            source_lock(db)
            if request_key:
                existing = db.query(InputScanRun).filter_by(request_key=request_key).first()
                if existing:
                    return existing.id
            existing = db.query(InputScanRun).filter(
                InputScanRun.scan_status.in_(["starting", "running", "cancelling", "interrupted"]),
                func.coalesce(InputScanRun.policy["source_action"].astext, "scan_input")
                == policy.get("source_action", "scan_input"),
                InputScanRun.producer_closed.is_(False) if policy.get("event_driven") else text("true"),
            ).order_by(InputScanRun.created_at).first()
            if existing and not force_new:
                return existing.id
            scan_id, batch_id = str(uuid.uuid4()), str(uuid.uuid4())
            run = InputScanRun(
                id=scan_id, request_key=request_key or scan_id, batch_id=batch_id,
                root_path=os.path.abspath(root), policy=policy, coverage={},
            )
            db.add(run)
            db.flush()
            from .activity_log_writer import get_activity_log_writer
            get_activity_log_writer().insert_once(db, {
                "id": batch_id, "event_key": f"input-scan:{scan_id}:start",
                "category": "auto_import", "action": "batch_start", "status": "incomplete",
                "summary": "正在扫描输入目录", "task_id": batch_id, "batch_id": batch_id,
                "source_path": run.root_path, "created_at": run.created_at,
                "detail": {
                    "schema_version": 2, "scan_id": scan_id, "batch_id": batch_id,
                    "producer_closed": False, "scan_closed": False, "created_count": 0,
                    "source_page": policy.get("source_page", "dashboard"),
                    "source_action": policy.get("source_action", "scan_input"),
                },
            })
            return scan_id

    def close_event_producer(self, scan_id):
        """事件入口没有目录生产线程；所有已登记候选交接后原子关闭。"""
        with self.session_factory.begin() as db:
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
            if db.query(InputScanCandidate.id).filter(
                InputScanCandidate.scan_id == scan_id,
                ~InputScanCandidate.state.in_(TERMINAL),
            ).first():
                return False
            run.producer_closed = True
            run.coverage = {**(run.coverage or {}), "close_reason": "exhausted"}
            self._touch(run)
            return True

    def candidate_for_group(self, scan_id, group_key):
        candidate = self.find_candidate_for_group(scan_id, group_key)
        if candidate is None:
            raise ValueError("扫描候选不存在")
        return candidate

    def find_candidate_for_group(self, scan_id, group_key):
        with self.session_factory() as db:
            row = db.query(InputScanCandidate).filter_by(scan_id=scan_id, group_key=group_key).first()
            if row is None:
                return None
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            return self._candidate_dict(row, entries)

    def candidate_by_id(self, candidate_id):
        with self.session_factory() as db:
            row = db.get(InputScanCandidate, candidate_id)
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            return self._candidate_dict(row, entries)

    def reconcile_sources(self):
        """启动派发前恢复改名计划，无法证明归属的任务保留占用并暂停。"""
        from .input_source_rename import InputSourceRenamer, SourceRenameUnresolved
        with self.session_factory() as db:
            ids = [row.id for row in db.query(InputScanCandidate).filter(
                InputScanCandidate.preparation["normalization"]["status"].astext == "prepared",
            )]
        for candidate_id in ids:
            candidate = self.candidate_by_id(candidate_id)
            try:
                InputSourceRenamer(self, candidate).reconcile()
            except SourceRenameUnresolved as exc:
                with self.session_factory.begin() as db:
                    source_lock(db)
                    run = db.query(InputScanRun).filter_by(
                        id=candidate["scan_id"],
                    ).with_for_update().one()
                    row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
                    row.reason = str(exc)[:500]
                    if row.task_id:
                        task = db.query(TaskRecord).filter_by(id=row.task_id).with_for_update().one()
                        if task.status != "paused":
                            row.preparation = {
                                **(row.preparation or {}),
                                "normalization_resume_status": task.status,
                            }
                        task.status, task.current_step = "paused", "源文件改名待核对"
                        task.error_message = row.reason
                    else:
                        row.state = "failed"
                    self._touch(run)

    @staticmethod
    def _candidate_dict(row, entries=()):
        return {
            "id": row.id, "scan_id": row.scan_id, "group_key": row.group_key,
            "source_path": row.source_path, "state": row.state, "reason": row.reason,
            "task_id": row.task_id, "version": row.version, "evidence": row.evidence or {},
            "preparation": row.preparation or {}, "deadline": row.deadline,
            "next_check_at": row.next_check_at, "destination": row.destination,
            "record_id": row.record_id,
            "members": [item.source_path for item in entries],
        }

    def discover(self, scan_id, groups, timeout=300):
        """发现结果是完整组快照；成员变化使旧稳定证据失效。"""
        with self.session_factory.begin() as db:
            source_lock(db)
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
            if run.cancel_requested or run.producer_closed:
                return
            now = get_local_now()
            for group in groups:
                row = db.query(InputScanCandidate).filter_by(
                    scan_id=scan_id, group_key=group["group_key"],
                ).first()
                if row is None:
                    row = InputScanCandidate(
                        id=str(uuid.uuid4()), scan_id=scan_id, group_key=group["group_key"],
                        source_path=group["source_path"], state="discovered",
                        deadline=now + timedelta(seconds=timeout),
                        evidence={"needs_stability": bool(group.get("needs_stability"))},
                    )
                    db.add(row)
                    db.flush()
                if row.state in TERMINAL:
                    continue
                if (row.preparation or {}).get("normalization"):
                    # 已开始改名的成员由恢复协议核对，迟到的枚举不能写回旧路径。
                    continue
                members = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
                existing = {item.path_key for item in members}
                current = {path_key(path) for path in group["members"]}
                changed = False
                for item in members:
                    if item.path_key not in current:
                        db.delete(item)
                        db.query(InputSourceClaim).filter_by(
                            path_key=item.path_key, owner_type="candidate", owner_id=row.id,
                        ).delete(synchronize_session=False)
                        changed = True
                for path in group["members"]:
                    key = path_key(path)
                    if key not in existing:
                        db.add(InputScanEntry(candidate_id=row.id, path_key=key, source_path=path))
                        existing.add(key)
                        changed = True
                if changed:
                    row.source_path = group["source_path"]
                    row.evidence = {"needs_stability": bool(group.get("needs_stability"))}
                    row.version += 1
                    row.next_check_at = now
            if groups and not (run.coverage or {}).get("first_candidate_at"):
                run.coverage = {**(run.coverage or {}), "first_candidate_at": now.isoformat()}
            self._touch(run)

    def due(self, scan_id, limit=256, exclude=(), *, include_ready=True):
        with self.session_factory() as db:
            rows = db.query(InputScanCandidate).filter(
                InputScanCandidate.scan_id == scan_id,
                ~InputScanCandidate.state.in_(TERMINAL),
                InputScanCandidate.next_check_at <= get_local_now(),
                ~InputScanCandidate.id.in_(exclude),
            )
            if not include_ready:
                rows = rows.filter(InputScanCandidate.state != "ready")
            rows = rows.order_by(InputScanCandidate.next_check_at, InputScanCandidate.id).limit(limit).all()
            ids = [row.id for row in rows]
            entries = {}
            for item in db.query(InputScanEntry).filter(InputScanEntry.candidate_id.in_(ids)):
                entries.setdefault(item.candidate_id, []).append(item)
            return [self._candidate_dict(row, entries.get(row.id, ())) for row in rows]

    def update_candidate(self, candidate_id, version, *, state, reason=None, evidence=None,
                         delay=0, preparation=None, stable_timeout=None):
        with self.session_factory.begin() as db:
            candidate = db.get(InputScanCandidate, candidate_id)
            if not candidate:
                return False
            # 固定 run -> candidate 锁顺序，与取消、提交一致。
            run = db.query(InputScanRun).filter_by(id=candidate.scan_id).with_for_update().one()
            row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
            if row.version != version or row.state in TERMINAL or run.cancel_requested:
                return False
            if row.state == "ready" and state == "waiting_stable" and stable_timeout is not None:
                row.deadline = get_local_now() + timedelta(seconds=stable_timeout)
            row.state, row.reason = state, reason
            if evidence is not None:
                row.evidence = evidence
            if preparation is not None:
                row.preparation = preparation
            row.next_check_at = get_local_now() + timedelta(seconds=delay)
            row.updated_at = get_local_now()
            row.version += 1
            if state in TERMINAL and (row.preparation or {}).get("normalization", {}).get("status") != "prepared":
                db.query(InputSourceClaim).filter_by(owner_type="candidate", owner_id=row.id).delete()
            self._touch(run)
            return True

    def control_state(self, scan_id):
        """调度热路径只查控制标志和未交接项，不递归聚合业务历史。"""
        with self.session_factory() as db:
            run = db.get(InputScanRun, scan_id)
            pending = db.query(InputScanCandidate.id).filter(
                InputScanCandidate.scan_id == scan_id,
                ~InputScanCandidate.state.in_(TERMINAL),
            ).first() is not None
            return {
                "cancel_requested": run.cancel_requested,
                "producer_closed": run.producer_closed,
                "pending_count": int(pending), "policy": run.policy or {},
            }

    def register_derived_task(self, task):
        """派生任务先持久化再进入内存队列，重启后复用同一派发意图。"""
        metadata = dict(task.task_metadata or {})
        with self.session_factory.begin() as db:
            run = db.query(InputScanRun).filter_by(id=metadata["scan_id"]).with_for_update().one()
            if db.get(TaskRecord, task.id) is not None:
                return
            parent = db.get(TaskRecord, metadata.get("parent_task_id"))
            if parent is None or (parent.task_metadata or {}).get("scan_id") != run.id:
                raise ValueError("派生任务缺少同批次的持久父任务")
            metadata.update({
                "batch_id": run.batch_id, "session_id": run.batch_id,
                "auto_classify": bool(task.auto_classify), "skip_archive": bool(task.skip_archive),
                "_input_snapshot_revision": int(task._input_snapshot_revision),
            })
            db.add(TaskRecord(
                id=task.id, type=task.type.value, status="pending", source_path=task.source_path,
                output_path=task.output_path, progress=0, current_step="等待中",
                created_at=task.created_at, task_metadata=metadata,
            ))
            self._outbox(db, run.id, "task_dispatch",
                         f"input-task:{task.id}:dispatch", {"task_id": task.id})
            self._touch(run)
        task.task_metadata = metadata

    def persist_execution(self, task, *, lifecycle=False):
        """扫描任务的事实状态与生命周期意图在同一事务提交。"""
        from .activity_log_service import _snapshot_task_for_lifecycle
        from copy import deepcopy
        revision = int(getattr(task, "_input_snapshot_revision", 0))
        snapshot = _snapshot_task_for_lifecycle(task)
        if snapshot is None:
            raise ValueError("无法生成扫描任务快照")
        snapshot = deepcopy(snapshot)
        progress = int(task.progress or 0)
        if revision != int(getattr(task, "_input_snapshot_revision", 0)):
            raise ValueError("任务快照已变化，等待重试")
        metadata = snapshot["task_metadata"]
        metadata["_input_snapshot_revision"] = revision
        with self.session_factory.begin() as db:
            # 进度只锁自己的任务；批次状态/首时间变化时才按批次、任务顺序加锁。
            run = db.get(InputScanRun, metadata["scan_id"])
            previous_status = db.query(TaskRecord.status).filter_by(id=task.id).scalar()
            candidate = db.query(InputScanCandidate).filter_by(task_id=task.id).first()
            coverage = dict(run.coverage or {})
            if snapshot["started_at"]:
                record_first(coverage, "first_task_start_at", snapshot["started_at"].isoformat())
                if candidate and candidate.destination == "normal":
                    record_first(coverage, "first_normal_task_start_at", snapshot["started_at"].isoformat())
            record_first(coverage, "first_extract_at", metadata.get("input_first_extract_at"))
            batch_changed = lifecycle or previous_status != snapshot["status"].value or coverage != (run.coverage or {})
            if batch_changed:
                run = db.query(InputScanRun).filter_by(id=metadata["scan_id"]).populate_existing().with_for_update().one()
            row = db.query(TaskRecord).filter_by(id=task.id).with_for_update().one()
            written = int((row.task_metadata or {}).get("_input_snapshot_revision", -1))
            if revision < written:
                return False
            if revision == written and not lifecycle:
                return True
            if not batch_changed and row.status != snapshot["status"].value:
                raise ValueError("任务状态已变化，等待按批次锁顺序重试")
            candidate = db.query(InputScanCandidate).filter_by(task_id=task.id).populate_existing().first()
            if candidate and (candidate.preparation or {}).get("source_aliases"):
                # 改名事务是源路径事实，不能被提前捕获的进度快照写回旧路径。
                snapshot["source_path"] = candidate.source_path
                metadata["input_members"] = [
                    item.source_path for item in db.query(InputScanEntry).filter_by(candidate_id=candidate.id)
                ]
                stability = metadata.get("input_stability") or {}
                if set(stability.get("fingerprints", {})) != set(metadata["input_members"]):
                    metadata["input_stability"] = deepcopy(
                        (row.task_metadata or {}).get("input_stability") or candidate.evidence or {}
                    )
            row.status = snapshot["status"].value
            row.source_path = snapshot["source_path"]
            row.output_path = snapshot["output_path"]
            row.current_step = snapshot["current_step"]
            row.error_message = snapshot["error_message"]
            row.progress = progress
            row.started_at, row.completed_at = snapshot["started_at"], snapshot["completed_at"]
            row.task_metadata = metadata
            if batch_changed:
                coverage = dict(run.coverage or {})
                if snapshot["started_at"]:
                    if record_first(coverage, "first_task_start_at", snapshot["started_at"].isoformat()):
                        coverage["first_task_start_type"] = task.type.value
                    if candidate and candidate.destination == "normal":
                        record_first(coverage, "first_normal_task_start_at", snapshot["started_at"].isoformat())
                record_first(coverage, "first_extract_at", metadata.get("input_first_extract_at"))
                run.coverage = coverage
            if lifecycle:
                payload = {**snapshot, "task_metadata": metadata}
                for key in ("created_at", "started_at", "completed_at"):
                    payload[key] = payload[key].isoformat() if payload[key] else None
                self._outbox(
                    db, run.id, "task_lifecycle", f"input-task:{task.id}:lifecycle:{revision}",
                    payload,
                )
            if batch_changed:
                self._touch(run)
            return True

    def deliver_lifecycle(self, event_id):
        """日志与交付确认原子提交，重复派发不重复计数。"""
        from datetime import datetime
        from .activity_log_service import _build_and_write_task_lifecycle_log
        from .task_engine import TaskStatus, TaskType
        with self.session_factory.begin() as db:
            event = db.query(InputScanOutbox).filter_by(id=event_id).with_for_update().one()
            if event.delivered_at:
                return
            snapshot = dict(event.payload)
            snapshot["status"], snapshot["type"] = TaskStatus(snapshot["status"]), TaskType(snapshot["type"])
            for key in ("created_at", "started_at", "completed_at"):
                snapshot[key] = datetime.fromisoformat(snapshot[key]) if snapshot.get(key) else None
            _build_and_write_task_lifecycle_log(
                snapshot, transaction=db, event_key=event.event_key,
            )
            event.delivered_at, event.last_error = get_local_now(), None

    def claim(self, candidate_id, version):
        with self.session_factory.begin() as db:
            source_lock(db)
            candidate = db.get(InputScanCandidate, candidate_id)
            run = db.query(InputScanRun).filter_by(id=candidate.scan_id).with_for_update().one()
            row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
            if run.cancel_requested or row.version != version or row.state in TERMINAL:
                return False
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            check_source_claims(db, [item.source_path for item in entries],
                                owner_type="candidate", owner_id=row.id)
            for item in entries:
                db.merge(InputSourceClaim(
                    path_key=item.path_key, source_path=item.source_path,
                    owner_type="candidate", owner_id=row.id,
                ))
            return True

    def prepare_stage(self, candidate_id, version, path):
        """先登记再创建临时目录；取消和版本变化必须阻止新副作用。"""
        with self.session_factory.begin() as db:
            candidate = db.get(InputScanCandidate, candidate_id)
            run = db.query(InputScanRun).filter_by(id=candidate.scan_id).with_for_update().one()
            row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
            if run.cancel_requested or row.version != version or row.state in TERMINAL:
                raise ValueError("扫描已取消或候选已变化")
            preparation = dict(row.preparation or {})
            preparation["stage_paths"] = [*preparation.get("stage_paths", []), os.path.abspath(path)]
            row.preparation = preparation

    def stage_paths(self, scan_id, candidate_id=None):
        with self.session_factory() as db:
            query = db.query(InputScanCandidate).filter_by(scan_id=scan_id)
            if candidate_id:
                query = query.filter_by(id=candidate_id)
            return [
                (row.id, path)
                for row in query
                for path in (row.preparation or {}).get("stage_paths", [])
                if path not in (row.preparation or {}).get("handed_off_stage_paths", [])
            ]

    def clear_stage(self, candidate_id, path):
        with self.session_factory.begin() as db:
            row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
            preparation = dict(row.preparation or {})
            if path in preparation.get("handed_off_stage_paths", []):
                return
            preparation["stage_paths"] = [
                item for item in preparation.get("stage_paths", []) if item != path
            ]
            row.preparation = preparation

    def commit_candidate(self, candidate_id, version, task, *, pending_limit=None,
                         routed=False, prepared_conflicts=()):
        """事务成功才允许入队；派发失败保留 outbox，不把源记成已处理。"""
        with self.session_factory.begin() as db:
            source_lock(db)
            candidate = db.get(InputScanCandidate, candidate_id)
            run = db.query(InputScanRun).filter_by(id=candidate.scan_id).with_for_update().one()
            row = db.query(InputScanCandidate).filter_by(id=candidate_id).with_for_update().one()
            if row.task_id:
                return row.task_id
            if run.cancel_requested or row.version != version or row.state in TERMINAL:
                return None
            if routed and task.status.value not in {
                "completed", "failed", "waiting_manual", "waiting_retry", "cancelled",
            }:
                raise ValueError("提前分流必须具有确定的业务结果")
            if not routed and pending_limit is not None and db.query(TaskRecord.id).filter(
                TaskRecord.type == "auto_process", TaskRecord.status == "pending",
            ).limit(pending_limit).count() >= pending_limit:
                row.state = "ready"
                row.reason = "engine_backpressure"
                row.next_check_at = get_local_now() + timedelta(seconds=1)
                row.version += 1
                self._touch(run)
                return None
            entries = db.query(InputScanEntry).filter_by(candidate_id=row.id).all()
            check_source_claims(db, [item.source_path for item in entries],
                                owner_type="candidate", owner_id=row.id)
            from .input_stability import sample_sources
            fingerprints, reason = sample_sources([item.source_path for item in entries])
            if reason or fingerprints != (row.evidence or {}).get("fingerprints"):
                raise SourceChanged("提交前源文件变化，必须重新采样")
            metadata = {
                **(task.task_metadata or {}),
                "scan_id": run.id, "candidate_id": row.id, "batch_id": run.batch_id,
                "session_id": run.batch_id, "batch_log_parent": True,
                "auto_classify": bool(task.auto_classify), "skip_archive": bool(task.skip_archive),
                "input_stability": row.evidence or {},
            }
            task.task_metadata = metadata
            if routed:
                subtitle_id = (metadata.get("linked_subtitle_import") or {}).get("id")
                subtitle = next((
                    item for item in prepared_conflicts
                    if item.id == subtitle_id and item.conflict_type == "LINKED_SUBTITLE_IMPORT"
                ), None)
                if subtitle_id and subtitle is None:
                    raise ValueError("字幕交接缺少对应的待办记录")
                destination = "subtitle" if subtitle is not None else "problem"
                if not prepared_conflicts:
                    destination = "skipped"
                metadata["input_route"] = {
                    "destination": destination,
                    "record_ids": [item.id for item in prepared_conflicts],
                    "committed_at": get_local_now().isoformat(),
                }
                for conflict in prepared_conflicts:
                    conflict.task_id = task.id
                    conflict.analysis_info = {
                        **(conflict.analysis_info or {}),
                        "input_scan": {
                            "scan_id": run.id, "candidate_id": row.id, "task_id": task.id,
                            "decision": metadata.get("input_preflight"),
                        },
                    }
                    db.add(conflict)
            db.add(TaskRecord(
                id=task.id, type=task.type.value,
                status=task.status.value if routed else "pending", source_path=task.source_path,
                output_path=task.output_path, progress=task.progress if routed else 0,
                current_step=task.current_step if routed else "等待中",
                error_message=task.error_message if routed else None,
                started_at=task.started_at if routed else None,
                completed_at=task.completed_at if routed else None,
                created_at=task.created_at, task_metadata=metadata,
            ))
            db.flush()
            row.task_id = task.id
            row.state = "routed" if routed else "submitted"
            row.destination = destination if routed else "normal"
            row.record_id = prepared_conflicts[0].id if prepared_conflicts else None
            if routed and destination == "subtitle":
                preview = (subtitle.analysis_info or {}).get("preview") or {}
                stage = preview.get("source_subtitle_dir") or preview.get("staged_subtitle_dir")
                if stage:
                    stage = os.path.abspath(stage)
                    if stage not in (row.preparation or {}).get("stage_paths", []) or not os.path.isdir(stage):
                        raise ValueError("字幕临时目录未登记或已经丢失")
                    row.preparation = {
                        **(row.preparation or {}), "handed_off_stage_paths": [stage],
                    }
            row.source_path = task.source_path
            row.version += 1
            milestone = "first_route_committed_at" if routed else "first_submit_at"
            coverage = dict(run.coverage or {})
            record_first(coverage, milestone, get_local_now().isoformat())
            if routed and task.started_at:
                if record_first(coverage, "first_task_start_at", task.started_at.isoformat()):
                    coverage["first_task_start_type"] = task.type.value
            record_first(coverage, "first_extract_at", metadata.get("input_first_extract_at"))
            run.coverage = coverage
            for item in entries:
                db.merge(InputSourceClaim(
                    path_key=item.path_key, source_path=item.source_path,
                    owner_type="task", owner_id=task.id,
                ))
            self._outbox(
                db, run.id, "task_restore" if routed else "task_dispatch",
                f"input-task:{task.id}:dispatch", {"task_id": task.id},
            )
            if routed:
                from .activity_log_service import _snapshot_task_for_lifecycle
                snapshot = _snapshot_task_for_lifecycle(task)
                for key in ("created_at", "started_at", "completed_at"):
                    snapshot[key] = snapshot[key].isoformat() if snapshot[key] else None
                self._outbox(
                    db, run.id, "task_lifecycle", f"input-task:{task.id}:lifecycle:0", snapshot,
                )
            self._touch(run)
            return task.id

    def close_producer(self, scan_id, *, reason="exhausted", errors=None, enumerated_files=0):
        with self.session_factory.begin() as db:
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
            run.producer_closed = True
            run.coverage = {
                **(run.coverage or {}), "close_reason": reason, "errors": errors or [],
                "enumerated_files": enumerated_files,
            }
            if reason == "error":
                run.scan_status = "failed"
            self._touch(run)

    def cancel(self, scan_id):
        with self.session_factory.begin() as db:
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one_or_none()
            if run is None:
                return False
            if run.scan_status in {"completed", "cancelled", "failed"}:
                return True
            run.cancel_requested, run.scan_status = True, "cancelling"
            self._touch(run)
            return True

    def finish_cancel(self, scan_id, *, interrupted=False):
        """调用者须先确认生产线程及规范化动作已退出。"""
        with self.session_factory.begin() as db:
            source_lock(db)
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
            if interrupted:
                run.scan_status = "interrupted"
            else:
                ids = [row.id for row in db.query(InputScanCandidate).filter(
                    InputScanCandidate.scan_id == scan_id, ~InputScanCandidate.state.in_(TERMINAL),
                )]
                db.query(InputScanCandidate).filter(InputScanCandidate.id.in_(ids)).update(
                    {"state": "cancelled"}, synchronize_session=False,
                )
                db.query(InputSourceClaim).filter(
                    InputSourceClaim.owner_type == "candidate", InputSourceClaim.owner_id.in_(ids),
                    ~InputSourceClaim.owner_id.in_(select(InputScanCandidate.id).where(
                        InputScanCandidate.preparation["normalization"]["status"].astext == "prepared",
                    )),
                ).delete(synchronize_session=False)
                run.scan_status, run.producer_closed = "cancelled", True
            self._touch(run)

    def snapshot(self, scan_id, *, materialize=False):
        """查询只读；协调者按节流周期物化有变化的父记录。"""
        with self.session_factory.begin() as db:
            query = db.query(InputScanRun).filter_by(id=scan_id)
            run = (query.with_for_update() if materialize else query).one_or_none()
            if not run:
                return None
            counts = dict(db.query(InputScanCandidate.state, func.count()).filter_by(
                scan_id=scan_id,
            ).group_by(InputScanCandidate.state).all())
            total = sum(counts.values())
            pending = sum(value for state, value in counts.items() if state not in TERMINAL)
            scan_status = run.scan_status
            if run.producer_closed and not pending and scan_status == "running":
                scan_status = "completed"
            task_counts = self._root_outcomes(db, scan_id)
            if task_counts.get("processing"):
                execution = "running"
            elif not run.producer_closed or pending or any(
                status in task_counts for status in ("pending", "processing", "paused", "waiting_manual", "waiting_retry")
            ):
                execution = "waiting"
            elif task_counts.get("failed") or counts.get("failed"):
                execution = "partial" if task_counts.get("completed") else "failed"
            elif task_counts.get("cancelled") or counts.get("cancelled"):
                execution = "cancelled"
            else:
                execution = "success" if total else "empty"
            if run.scan_status in {"failed", "interrupted"}:
                execution = "waiting" if run.scan_status == "interrupted" else "failed"
            if materialize:
                parent = db.get(ActivityLog, run.batch_id)
                detail = {
                    **((parent.detail if parent else None) or {}), "producer_closed": run.producer_closed,
                    "scan_closed": run.producer_closed and not pending,
                    "scan_status": scan_status, "execution_status": execution,
                    "requested_count": total, "created_count": counts.get("submitted", 0) + counts.get("routed", 0),
                    "counts": counts, "task_outcomes": dict(task_counts), "coverage": run.coverage or {},
                }
                changed = run.execution_status != execution or run.scan_status != scan_status
                if parent and parent.detail != detail:
                    parent.detail = detail
                    db.flush()
                    from .activity_log_writer import get_activity_log_writer
                    from .activity_log_rollup_service import get_activity_log_rollup_service
                    get_activity_log_rollup_service().upsert_from_payloads(db, [{
                        "batch_id": run.batch_id, "task_id": run.batch_id,
                    }])
                    get_activity_log_writer().invalidate_after_commit(db)
                    changed = True
                if changed:
                    run.execution_status, run.scan_status = execution, scan_status
                    self._touch(run)
                    if run.producer_closed and not pending:
                        event_type = (
                            "waiting_manual" if execution == "waiting" and task_counts.get("waiting_manual")
                            and not any(task_counts.get(key) for key in (
                                "pending", "processing", "paused", "waiting_retry",
                            )) else
                            "completed" if execution == "success" else
                            "failed" if execution in {"partial", "failed"} else None
                        )
                        if event_type:
                            self._outbox(
                                db, run.id, "scan_notification",
                                f"input-scan:{run.id}:notification:{event_type}",
                                {"event_type": event_type},
                            )
            return {
                "scan_id": run.id, "batch_id": run.batch_id, "status": scan_status,
                "scan_status": scan_status, "execution_status": execution,
                "producer_closed": run.producer_closed, "cancel_requested": run.cancel_requested,
                "revision": run.revision, "counts": counts, "discovered_groups": total,
                "total_candidates": total if run.producer_closed else None,
                "found_count": counts.get("submitted", 0), "pending_count": pending,
                "coverage": run.coverage or {}, "policy": run.policy or {}, "task_outcomes": dict(task_counts),
                "root_path": run.root_path, "created_at": run.created_at.isoformat(),
                "message": "扫描中" if scan_status == "running" else "扫描" + {
                    "completed": "完成", "cancelled": "已取消", "interrupted": "已中断", "failed": "失败",
                }.get(scan_status, "正在取消"),
            }

    @staticmethod
    def _root_outcomes(db, scan_id):
        # UNION 去重可截断异常循环关系；派生任务只贡献所属根候选的业务结论。
        roots = select(
            TaskRecord.id.label("id"), TaskRecord.id.label("root_id"),
        ).join(InputScanCandidate, InputScanCandidate.task_id == TaskRecord.id).where(
            InputScanCandidate.scan_id == scan_id,
        ).cte("input_task_tree", recursive=True)
        tree = roots.union(select(
            TaskRecord.id, roots.c.root_id,
        ).join(roots, TaskRecord.task_metadata["parent_task_id"].astext == roots.c.id))
        tasks = db.execute(select(
            tree.c.root_id, TaskRecord.id, TaskRecord.status,
            TaskRecord.task_metadata["multi_rj_dispatch_failures"].label("dispatch_failures"),
        ).join(tree, TaskRecord.id == tree.c.id)).all()
        task_ids = [row.id for row in tasks]
        waiting_ids = {
            row.task_id for row in db.query(ConflictWork.task_id).filter(
                ConflictWork.task_id.in_(task_ids), ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            )
        }
        archive_states = {}
        for task_id, status in db.query(DeferredArchiveJob.task_id, DeferredArchiveJob.status).filter(
            DeferredArchiveJob.task_id.in_(task_ids),
            DeferredArchiveJob.status.in_(["pending", "processing", "waiting_retry", "failed"]),
        ):
            archive_states.setdefault(task_id, set()).add(
                "failed" if status == "failed" else "waiting_retry"
            )
        outcomes = {}
        for root_id, task_id, status, dispatch_failures in tasks:
            statuses = outcomes.setdefault(root_id, set())
            statuses.add("waiting_manual" if task_id in waiting_ids else status)
            statuses.update(archive_states.get(task_id, ()))
            if dispatch_failures:
                statuses.add("failed")
        result = Counter()
        for statuses in outcomes.values():
            waiting = statuses & {"pending", "processing", "paused", "waiting_manual", "waiting_retry"}
            if waiting:
                for state in ("processing", "pending", "paused", "waiting_retry", "waiting_manual"):
                    if state in waiting:
                        result[state] += 1
                        break
            elif "failed" in statuses:
                result["failed"] += 1
            elif "cancelled" in statuses:
                result["cancelled"] += 1
            else:
                result["completed"] += 1
        return result

    def runs(self, limit=20):
        with self.session_factory() as db:
            return [row.id for row in db.query(InputScanRun).order_by(
                InputScanRun.created_at.desc(), InputScanRun.id,
            ).limit(min(100, max(1, limit)))]

    def unsettled_runs(self):
        """只追踪尚未结算的批次，不每秒重聚合已完成的历史。"""
        with self.session_factory() as db:
            return [row.id for row in db.query(InputScanRun.id).filter(
                (InputScanRun.scan_status.in_(["starting", "running", "cancelling", "interrupted"]))
                | (InputScanRun.execution_status.in_(["not_started", "running", "waiting"])),
            )]

    def recoverable(self):
        with self.session_factory() as db:
            return [row.id for row in db.query(InputScanRun).filter(
                InputScanRun.scan_status.in_(["starting", "running", "cancelling", "interrupted"]),
            )]

    def resume(self, scan_id):
        with self.session_factory.begin() as db:
            run = db.query(InputScanRun).filter_by(id=scan_id).with_for_update().one()
            if not run.cancel_requested:
                run.scan_status = "running"
                self._touch(run)

    def pending_tasks(self):
        with self.session_factory() as db:
            return [row.id for row in db.query(TaskRecord.id).join(
                InputScanRun, TaskRecord.task_metadata["scan_id"].astext == InputScanRun.id,
            ).filter(TaskRecord.status == "pending")]

    def candidates(self, scan_id, *, after=None, limit=100):
        with self.session_factory() as db:
            query = db.query(InputScanCandidate).filter_by(scan_id=scan_id)
            if after:
                query = query.filter(InputScanCandidate.id > after)
            return [self._candidate_dict(row) for row in query.order_by(InputScanCandidate.id).limit(min(256, limit))]

    def outbox(self, limit=64):
        with self.session_factory() as db:
            return [{
                "id": row.id, "scan_id": row.scan_id, "kind": row.kind, "payload": row.payload,
            } for row in db.query(InputScanOutbox).filter(
                InputScanOutbox.delivered_at.is_(None), InputScanOutbox.available_at <= get_local_now(),
            ).order_by(InputScanOutbox.available_at, InputScanOutbox.id).limit(limit)]

    def acknowledge(self, event_id, error=None):
        with self.session_factory.begin() as db:
            row = db.get(InputScanOutbox, event_id)
            if error:
                row.attempts += 1
                row.last_error = str(error)[:1000]
                row.available_at = get_local_now() + timedelta(seconds=min(60, 2 ** min(6, row.attempts)))
            else:
                row.delivered_at, row.last_error = get_local_now(), None
