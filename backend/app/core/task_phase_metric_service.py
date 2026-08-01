"""任务阶段耗时指标服务。

这是性能审计用的轻量旁路记录，不改变任务执行状态，也不要求所有任务都接入。
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import asc, desc, func

from ..models.database import SessionLocal, TaskPhaseMetric

logger = logging.getLogger(__name__)

_MAX_DETAIL_KEYS = 20
_MAX_DETAIL_VALUE_LENGTH = 200


def _safe_text(value: Any, *, max_length: int = _MAX_DETAIL_VALUE_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _sanitize_detail(detail: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in list(detail.items())[:_MAX_DETAIL_KEYS]:
        safe_key = _safe_text(key, max_length=60)
        lowered = safe_key.lower()
        if any(marker in lowered for marker in ("token", "password", "cookie", "secret", "authorization")):
            result[safe_key] = "[redacted]"
        elif isinstance(value, (int, float, bool)) or value is None:
            result[safe_key] = value
        elif isinstance(value, (list, tuple, set)):
            result[safe_key] = f"list[{len(value)}]"
        elif isinstance(value, dict):
            result[safe_key] = f"dict[{len(value)}]"
        else:
            result[safe_key] = _safe_text(value)
    return result


class TaskPhaseMetricService:
    async def record_async(self, **kwargs: Any) -> Optional[str]:
        return await asyncio.to_thread(self.record, **kwargs)

    def record(
        self,
        *,
        task_id: str,
        task_type: str = "",
        phase: str,
        resource: str = "",
        status: str = "completed",
        duration_ms: int = 0,
        bytes_total: int = 0,
        items_total: int = 0,
        detail: Optional[dict[str, Any]] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> Optional[str]:
        normalized_task_id = _safe_text(task_id, max_length=36)
        normalized_phase = _safe_text(phase, max_length=80)
        if not normalized_task_id or not normalized_phase:
            return None

        ended = ended_at or datetime.now()
        duration = _safe_int(duration_ms)
        started = started_at or (ended - timedelta(milliseconds=duration) if duration > 0 else ended)
        metric_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            metric = TaskPhaseMetric(
                id=metric_id,
                task_id=normalized_task_id,
                task_type=_safe_text(task_type, max_length=60),
                phase=normalized_phase,
                resource=_safe_text(resource, max_length=40),
                status=_safe_text(status, max_length=24) or "completed",
                duration_ms=duration,
                bytes_total=_safe_int(bytes_total),
                items_total=_safe_int(items_total),
                detail_json=_sanitize_detail(detail),
                started_at=started,
                ended_at=ended,
                created_at=datetime.now(),
            )
            db.add(metric)
            db.commit()
            return metric_id
        except Exception:
            db.rollback()
            logger.warning("[任务阶段指标] 写入失败 task_id=%s phase=%s", normalized_task_id, normalized_phase, exc_info=True)
            return None
        finally:
            db.close()

    def list_recent(self, *, task_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            query = db.query(TaskPhaseMetric)
            normalized_task_id = _safe_text(task_id, max_length=36)
            if normalized_task_id:
                query = query.filter(TaskPhaseMetric.task_id == normalized_task_id)
            rows = (
                query.order_by(desc(TaskPhaseMetric.created_at))
                .limit(min(max(1, int(limit or 100)), 500))
                .all()
            )
            return [self._to_dict(row) for row in rows]
        finally:
            db.close()

    def summarize_recent(self, *, task_id: str = "", limit: int = 1000) -> dict[str, Any]:
        """按 task_type/phase/resource 聚合最近指标。

        为避免跨数据库 percentile 兼容问题，p95 在 Python 里对最近 N 条轻量计算。
        """
        db = SessionLocal()
        try:
            query = db.query(TaskPhaseMetric)
            normalized_task_id = _safe_text(task_id, max_length=36)
            if normalized_task_id:
                query = query.filter(TaskPhaseMetric.task_id == normalized_task_id)
            rows = (
                query.order_by(desc(TaskPhaseMetric.created_at))
                .limit(min(max(1, int(limit or 1000)), 5000))
                .all()
            )
            groups: dict[tuple[str, str, str], list[TaskPhaseMetric]] = {}
            for row in rows:
                key = (row.task_type or "", row.phase or "", row.resource or "")
                groups.setdefault(key, []).append(row)
            summaries = []
            for (task_type, phase, resource), group_rows in groups.items():
                durations = sorted(int(row.duration_ms or 0) for row in group_rows)
                if durations:
                    p95_index = max(0, min(len(durations) - 1, math.ceil(len(durations) * 0.95) - 1))
                    p95 = durations[p95_index]
                    avg = int(sum(durations) / len(durations))
                    max_duration = durations[-1]
                else:
                    p95 = avg = max_duration = 0
                summaries.append({
                    "task_type": task_type,
                    "phase": phase,
                    "resource": resource,
                    "count": len(group_rows),
                    "duration_avg_ms": avg,
                    "duration_p95_ms": p95,
                    "duration_max_ms": max_duration,
                    "bytes_total": sum(int(row.bytes_total or 0) for row in group_rows),
                    "items_total": sum(int(row.items_total or 0) for row in group_rows),
                    "failed_count": sum(1 for row in group_rows if str(row.status or "").lower() in {"failed", "partial_failed", "error"}),
                    "latest_at": max((row.created_at for row in group_rows if row.created_at), default=None),
                })
            summaries.sort(key=lambda item: (int(item["duration_p95_ms"]), int(item["duration_max_ms"])), reverse=True)
            for item in summaries:
                latest_at = item.get("latest_at")
                item["latest_at"] = latest_at.isoformat() if latest_at else None
            return {
                "sample_count": len(rows),
                "group_count": len(summaries),
                "groups": summaries,
            }
        finally:
            db.close()

    def cleanup(self, *, retain_days: int = 14, max_items: int = 5000) -> dict[str, Any]:
        """清理旧任务阶段指标，控制观测表长期增长。"""
        retain = max(1, int(retain_days or 14))
        max_keep = max(100, int(max_items or 5000))
        cutoff = datetime.now() - timedelta(days=retain)
        db = SessionLocal()
        deleted_old = 0
        deleted_overflow = 0
        try:
            old_query = db.query(TaskPhaseMetric).filter(TaskPhaseMetric.created_at < cutoff)
            deleted_old = int(old_query.delete(synchronize_session=False) or 0)
            remaining = int(db.query(func.count(TaskPhaseMetric.id)).scalar() or 0)
            if remaining > max_keep:
                overflow = remaining - max_keep
                overflow_ids = [
                    row.id
                    for row in db.query(TaskPhaseMetric.id)
                    .order_by(asc(TaskPhaseMetric.created_at))
                    .limit(overflow)
                    .all()
                ]
                if overflow_ids:
                    deleted_overflow = int(
                        db.query(TaskPhaseMetric)
                        .filter(TaskPhaseMetric.id.in_(overflow_ids))
                        .delete(synchronize_session=False)
                        or 0
                    )
            db.commit()
            remaining_after = int(db.query(func.count(TaskPhaseMetric.id)).scalar() or 0)
            return {
                "deleted": deleted_old + deleted_overflow,
                "deleted_old": deleted_old,
                "deleted_overflow": deleted_overflow,
                "remaining": remaining_after,
                "retain_days": retain,
                "max_items": max_keep,
                "cutoff": cutoff.isoformat(),
            }
        except Exception:
            db.rollback()
            logger.warning("[任务阶段指标] 清理失败", exc_info=True)
            return {
                "deleted": 0,
                "deleted_old": deleted_old,
                "deleted_overflow": deleted_overflow,
                "remaining": 0,
                "retain_days": retain,
                "max_items": max_keep,
                "cutoff": cutoff.isoformat(),
                "error": "cleanup_failed",
            }
        finally:
            db.close()

    def _to_dict(self, row: TaskPhaseMetric) -> dict[str, Any]:
        return {
            "id": row.id,
            "task_id": row.task_id,
            "task_type": row.task_type,
            "phase": row.phase,
            "resource": row.resource,
            "status": row.status,
            "duration_ms": int(row.duration_ms or 0),
            "bytes_total": int(row.bytes_total or 0),
            "items_total": int(row.items_total or 0),
            "detail": row.detail_json or {},
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


_task_phase_metric_service: Optional[TaskPhaseMetricService] = None


def get_task_phase_metric_service() -> TaskPhaseMetricService:
    global _task_phase_metric_service
    if _task_phase_metric_service is None:
        _task_phase_metric_service = TaskPhaseMetricService()
    return _task_phase_metric_service
