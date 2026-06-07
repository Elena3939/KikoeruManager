from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func

from .json_safety import safe_text
from ..models.database import ActivityLog, ActivityLogRollup, SessionLocal

logger = logging.getLogger(__name__)


SUCCESS_STATUSES = {"success", "completed"}
FAILED_STATUSES = {"failed", "error"}
PARTIAL_STATUSES = {"partial_success", "partial_failed"}
WAITING_STATUSES = {"pending", "processing", "paused", "waiting", "waiting_manual", "waiting_retry"}

_BACKFILL_STATE_LOCK = threading.Lock()
_BACKFILL_RUN_LOCK = threading.Lock()
_BACKFILL_THREAD: Optional[threading.Thread] = None
_BACKFILL_STATE: Dict[str, Any] = {
    "state": "idle",
    "total_groups": 0,
    "rebuilt_groups": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _set_backfill_state(**updates: Any) -> None:
    with _BACKFILL_STATE_LOCK:
        _BACKFILL_STATE.update(updates)


def get_activity_log_rollup_backfill_state() -> Dict[str, Any]:
    with _BACKFILL_STATE_LOCK:
        return dict(_BACKFILL_STATE)


def _status_bucket(status: Any) -> str:
    normalized = safe_text(status, strip=True).lower()
    if normalized in SUCCESS_STATUSES:
        return "success"
    if normalized in FAILED_STATUSES:
        return "failed"
    if normalized in PARTIAL_STATUSES:
        return "partial"
    if normalized in WAITING_STATUSES:
        return "waiting"
    return "other"


def _rollup_status(success: int, failed: int, partial: int, waiting: int) -> str:
    if waiting > 0:
        return "waiting"
    if failed > 0 and (success > 0 or partial > 0):
        return "partial_success"
    if partial > 0:
        return "partial_success"
    if failed > 0:
        return "failed"
    if success > 0:
        return "success"
    return ""


def _created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
    return datetime.now()


def _payload_groups(payload: Dict[str, Any]) -> List[tuple[str, str]]:
    groups: List[tuple[str, str]] = []
    for rollup_type, field in (
        ("batch", "batch_id"),
        ("session", "session_key"),
        ("task", "task_id"),
    ):
        value = safe_text(payload.get(field), strip=True)
        if value:
            groups.append((rollup_type, value[:140]))
    return groups


class ActivityLogRollupService:
    """操作历史轻量 rollup 维护。

    目前只维护 batch/session/task 三类稳定键的计数与最新状态，不替换深度
    activity_log_aggregator 输出。
    """

    def upsert_from_payloads(self, db, payloads: Iterable[Dict[str, Any]]) -> int:
        affected_keys: set[str] = set()
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for rollup_type, group_value in _payload_groups(payload):
                affected_keys.add(f"{rollup_type}:{group_value}")
        for rollup_key in affected_keys:
            rollup_type, group_value = rollup_key.split(":", 1)
            self.rebuild_one(db, rollup_type=rollup_type, group_value=group_value)
        return len(affected_keys)

    def rebuild_one(self, db, *, rollup_type: str, group_value: str) -> Optional[ActivityLogRollup]:
        rollup_type = safe_text(rollup_type, strip=True)
        group_value = safe_text(group_value, strip=True)
        if not rollup_type or not group_value:
            return None

        if rollup_type == "batch":
            query = db.query(ActivityLog).filter(ActivityLog.batch_id == group_value)
        elif rollup_type == "session":
            query = db.query(ActivityLog).filter(ActivityLog.session_key == group_value)
        elif rollup_type == "task":
            query = db.query(ActivityLog).filter(ActivityLog.task_id == group_value)
        else:
            return None

        rows = query.order_by(ActivityLog.created_at.asc()).all()
        if not rows:
            db.query(ActivityLogRollup).filter(ActivityLogRollup.rollup_key == f"{rollup_type}:{group_value}").delete()
            return None

        latest = rows[-1]
        parent = rows[0]
        child_rows = rows[1:] if len(rows) > 1 else []
        count_rows = child_rows or rows
        success = failed = partial = waiting = 0
        categories: Dict[str, int] = {}
        for row in rows:
            category = safe_text(row.category, strip=True)
            if category:
                categories[category] = categories.get(category, 0) + 1
            if _created_at(row.created_at) >= _created_at(latest.created_at):
                latest = row

        for row in count_rows:
            bucket = _status_bucket(row.status)
            if bucket == "success":
                success += 1
            elif bucket == "failed":
                failed += 1
            elif bucket == "partial":
                partial += 1
            elif bucket == "waiting":
                waiting += 1

        category = max(categories.items(), key=lambda item: item[1])[0] if categories else ""
        rollup_key = f"{rollup_type}:{group_value}"
        record = db.query(ActivityLogRollup).filter(ActivityLogRollup.rollup_key == rollup_key).first()
        if not record:
            record = ActivityLogRollup(rollup_key=rollup_key)
            db.add(record)
        record.rollup_type = rollup_type
        record.group_value = group_value
        record.category = category
        record.parent_log_id = safe_text(parent.id, strip=True)
        record.latest_log_id = safe_text(latest.id, strip=True)
        record.child_count = len(child_rows)
        record.success_count = success
        record.failed_count = failed
        record.partial_count = partial
        record.waiting_count = waiting
        record.latest_status = _rollup_status(success, failed, partial, waiting)
        record.latest_activity_at = _created_at(latest.created_at)
        record.updated_at = datetime.now()
        return record

    def backfill(self, *, limit_groups: int = 2000) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            groups: set[tuple[str, str]] = set()
            for field, rollup_type in (
                (ActivityLog.batch_id, "batch"),
                (ActivityLog.session_key, "session"),
                (ActivityLog.task_id, "task"),
            ):
                rows = (
                    db.query(field)
                    .filter(field.isnot(None), field != "")
                    .group_by(field)
                    .limit(max(1, int(limit_groups or 2000)))
                    .all()
                )
                for row in rows:
                    value = safe_text(row[0], strip=True)
                    if value:
                        groups.add((rollup_type, value[:140]))
            rebuilt = 0
            _set_backfill_state(total_groups=len(groups), rebuilt_groups=0)
            for rollup_type, group_value in sorted(groups):
                if self.rebuild_one(db, rollup_type=rollup_type, group_value=group_value):
                    rebuilt += 1
                    if rebuilt % 25 == 0 or rebuilt == len(groups):
                        _set_backfill_state(rebuilt_groups=rebuilt)
            db.commit()
            _set_backfill_state(rebuilt_groups=rebuilt)
            diff = self.diff(limit_groups=limit_groups)
            return {
                "group_count": len(groups),
                "rebuilt": rebuilt,
                **diff,
            }
        except Exception:
            db.rollback()
            logger.warning("[操作记录 rollup] 回填失败", exc_info=True)
            raise
        finally:
            db.close()

    def trigger_backfill(self, *, limit_groups: int = 2000) -> Dict[str, Any]:
        """后台触发 rollup 回填；已在跑时直接返回当前状态。"""
        global _BACKFILL_THREAD
        if not _BACKFILL_RUN_LOCK.acquire(blocking=False):
            return {
                "started": False,
                "already_running": True,
                "status": get_activity_log_rollup_backfill_state(),
            }

        _set_backfill_state(
            state="running",
            total_groups=0,
            rebuilt_groups=0,
            started_at=_now_iso(),
            finished_at=None,
            error=None,
        )
        thread = threading.Thread(
            target=self._backfill_worker,
            kwargs={"limit_groups": max(1, int(limit_groups or 2000))},
            name="activity-log-rollup-backfill",
            daemon=True,
        )
        _BACKFILL_THREAD = thread
        thread.start()
        return {
            "started": True,
            "already_running": False,
            "status": get_activity_log_rollup_backfill_state(),
        }

    def _backfill_worker(self, *, limit_groups: int) -> None:
        try:
            result = self.backfill(limit_groups=limit_groups)
            _set_backfill_state(
                state="done",
                total_groups=int(result.get("group_count") or 0),
                rebuilt_groups=int(result.get("rebuilt") or 0),
                matched=bool(result.get("matched")),
                diff_count=int(result.get("diff_count") or 0),
                finished_at=_now_iso(),
                error=None,
            )
        except Exception as exc:
            logger.warning("[操作记录 rollup] 后台回填失败", exc_info=True)
            _set_backfill_state(
                state="error",
                finished_at=_now_iso(),
                error=str(exc),
            )
        finally:
            try:
                _BACKFILL_RUN_LOCK.release()
            except Exception:
                logger.debug("[操作记录 rollup] 后台回填锁释放失败", exc_info=True)

    def diff(self, *, limit_groups: int = 2000) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            diffs: List[Dict[str, Any]] = []
            rows = (
                db.query(ActivityLogRollup)
                .order_by(ActivityLogRollup.updated_at.desc())
                .limit(max(1, int(limit_groups or 2000)))
                .all()
            )
            for row in rows:
                rollup_type = safe_text(row.rollup_type, strip=True)
                group_value = safe_text(row.group_value, strip=True)
                if rollup_type == "batch":
                    query = db.query(ActivityLog).filter(ActivityLog.batch_id == group_value)
                elif rollup_type == "session":
                    query = db.query(ActivityLog).filter(ActivityLog.session_key == group_value)
                elif rollup_type == "task":
                    query = db.query(ActivityLog).filter(ActivityLog.task_id == group_value)
                else:
                    continue
                raw_rows = query.order_by(ActivityLog.created_at.asc()).all()
                count_rows = raw_rows[1:] if len(raw_rows) > 1 else raw_rows
                success = failed = partial = waiting = 0
                for raw in count_rows:
                    bucket = _status_bucket(raw.status)
                    success += 1 if bucket == "success" else 0
                    failed += 1 if bucket == "failed" else 0
                    partial += 1 if bucket == "partial" else 0
                    waiting += 1 if bucket == "waiting" else 0
                expected = {
                    "child_count": max(0, len(raw_rows) - 1),
                    "success_count": success,
                    "failed_count": failed,
                    "partial_count": partial,
                    "waiting_count": waiting,
                    "latest_status": _rollup_status(success, failed, partial, waiting),
                }
                actual = {
                    "child_count": int(row.child_count or 0),
                    "success_count": int(row.success_count or 0),
                    "failed_count": int(row.failed_count or 0),
                    "partial_count": int(row.partial_count or 0),
                    "waiting_count": int(row.waiting_count or 0),
                    "latest_status": safe_text(row.latest_status, strip=True),
                }
                changed = sorted(key for key in expected if expected[key] != actual[key])
                if changed:
                    diffs.append({
                        "rollup_key": row.rollup_key,
                        "changed_keys": changed,
                        "expected": expected,
                        "actual": actual,
                    })
            return {
                "matched": not diffs,
                "diff_count": len(diffs),
                "diffs": diffs[:50],
            }
        finally:
            db.close()

    def summary_for_batch_ids(self, db, batch_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        values = [safe_text(value, strip=True)[:140] for value in batch_ids if safe_text(value, strip=True)]
        if not values:
            return {}
        rows = (
            db.query(ActivityLogRollup)
            .filter(ActivityLogRollup.rollup_type == "batch", ActivityLogRollup.group_value.in_(values))
            .all()
        )
        return {
            safe_text(row.group_value, strip=True): {
                "child_failed_count": int(row.failed_count or 0),
                "child_success_count": int(row.success_count or 0),
                "child_partial_count": int(row.partial_count or 0),
                "child_total_count": int(row.child_count or 0),
            }
            for row in rows
        }


_activity_log_rollup_service: Optional[ActivityLogRollupService] = None


def get_activity_log_rollup_service() -> ActivityLogRollupService:
    global _activity_log_rollup_service
    if _activity_log_rollup_service is None:
        _activity_log_rollup_service = ActivityLogRollupService()
    return _activity_log_rollup_service
