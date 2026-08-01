import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func

from .task_engine import TaskStatus
from .json_safety import safe_text
from .resource_budget_service import get_resource_budget_service
from ..models.database import SessionLocal, TaskCenterItem

logger = logging.getLogger(__name__)


def _escape_ilike_pattern(value: str) -> str:
    return str(value or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _normalize_task_center_search(value: Optional[str]) -> str:
    text = safe_text(value, strip=True).lower()
    return text if len(text) >= 2 else ""


class TaskCenterMaterializationService:
    """任务中心旁路物化表维护。

    这层默认不参与当前 API 读路径，保存旧聚合器已经算出的 summary item，
    供后续切换 SQL 分页前做双写和 diff 校验。
    """

    def _item_searchable_text(self, item: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> str:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        payload_metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
        source_metadata = metadata if isinstance(metadata, dict) else {}
        parts = [
            item.get("id"),
            item.get("entity_id"),
            item.get("engine_task_id"),
            item.get("record_id"),
            item.get("title"),
            item.get("subtitle"),
            item.get("source_label"),
            item.get("source_path"),
            item.get("target_path"),
            item.get("rjcode"),
            payload_metadata.get("business_key"),
            source_metadata.get("business_key"),
        ]
        return " ".join(safe_text(part, strip=True).lower() for part in parts if safe_text(part, strip=True))

    def upsert_item(
        self,
        item: Dict[str, Any],
        *,
        version: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        item_id = safe_text(item.get("id"), strip=True)
        if not item_id:
            return

        engine_task_id = safe_text(item.get("engine_task_id") or item.get("entity_id"), strip=True)

        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        payload_metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
        source_metadata = metadata if isinstance(metadata, dict) else {}
        business_key = safe_text(
            payload_metadata.get("business_key") or source_metadata.get("business_key"),
            strip=True,
        )
        now = datetime.now()
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("database_write", reason="task_center.materialize_upsert"):
                record = db.query(TaskCenterItem).filter(TaskCenterItem.item_id == item_id).first()
                if not record:
                    record = TaskCenterItem(item_id=item_id, created_at=now)
                    db.add(record)

                record.engine_task_id = engine_task_id
                record.domain = safe_text(item.get("domain"), strip=True)
                record.status = safe_text(item.get("status"), strip=True)
                record.kind = safe_text(item.get("kind"), strip=True)
                record.title = safe_text(item.get("title"), strip=True)
                record.source_page = safe_text(item.get("source_page"), strip=True)
                record.source_action = safe_text(item.get("source_action"), strip=True)
                record.business_key = business_key
                record.searchable_text = self._item_searchable_text(item, metadata)
                record.payload_json = item
                record.version = int(version or 0)
                record.updated_at = now
                db.commit()
        except Exception:
            db.rollback()
            logger.warning("[任务中心物化] 写入快照失败: item_id=%s", item_id, exc_info=True)
        finally:
            db.close()

    def upsert_engine_item(
        self,
        item: Dict[str, Any],
        *,
        version: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        item_id = safe_text(item.get("id"), strip=True)
        if not item_id.startswith("engine:"):
            return
        self.upsert_item(item, version=version, metadata=metadata)

    def upsert_items(
        self,
        items: Iterable[Dict[str, Any]],
        *,
        version: int = 0,
        metadata_by_task_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        metadata_by_task_id = metadata_by_task_id or {}
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            engine_task_id = safe_text(item.get("engine_task_id") or item.get("entity_id"), strip=True)
            self.upsert_item(
                item,
                version=version,
                metadata=metadata_by_task_id.get(engine_task_id),
            )
            count += 1
        return count

    def upsert_engine_items(
        self,
        items: Iterable[Dict[str, Any]],
        *,
        version: int = 0,
        metadata_by_task_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        metadata_by_task_id = metadata_by_task_id or {}
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            engine_task_id = safe_text(item.get("engine_task_id") or item.get("entity_id"), strip=True)
            self.upsert_engine_item(
                item,
                version=version,
                metadata=metadata_by_task_id.get(engine_task_id),
            )
            count += 1
        return count

    def prune_items(self, valid_item_ids: Iterable[str]) -> int:
        valid_ids = {
            safe_text(item_id, strip=True)
            for item_id in valid_item_ids
            if safe_text(item_id, strip=True)
        }
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("database_write", reason="task_center.materialize_prune"):
                query = db.query(TaskCenterItem)
                if valid_ids:
                    query = query.filter(~TaskCenterItem.item_id.in_(valid_ids))
                deleted = query.delete(synchronize_session=False)
                db.commit()
            return int(deleted or 0)
        except Exception:
            db.rollback()
            logger.warning("[任务中心物化] 清理过期 item 快照失败", exc_info=True)
            return 0
        finally:
            db.close()

    def delete_engine_item(self, task_id: str) -> None:
        normalized_task_id = safe_text(task_id, strip=True)
        if not normalized_task_id:
            return
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("database_write", reason="task_center.materialize_delete"):
                db.query(TaskCenterItem).filter(TaskCenterItem.engine_task_id == normalized_task_id).delete()
                db.commit()
        except Exception:
            db.rollback()
            logger.warning("[任务中心物化] 删除快照失败: task_id=%s", normalized_task_id, exc_info=True)
        finally:
            db.close()

    def prune_engine_items(self, valid_task_ids: Iterable[str]) -> int:
        valid_ids = {
            safe_text(task_id, strip=True)
            for task_id in valid_task_ids
            if safe_text(task_id, strip=True)
        }
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("database_write", reason="task_center.materialize_prune_engine"):
                query = db.query(TaskCenterItem)
                if valid_ids:
                    query = query.filter(~TaskCenterItem.engine_task_id.in_(valid_ids))
                deleted = query.delete(synchronize_session=False)
                db.commit()
            return int(deleted or 0)
        except Exception:
            db.rollback()
            logger.warning("[任务中心物化] 清理过期快照失败", exc_info=True)
            return 0
        finally:
            db.close()

    def get_engine_item(self, task_id: str) -> Optional[Dict[str, Any]]:
        normalized_task_id = safe_text(task_id, strip=True)
        if not normalized_task_id:
            return None
        db = SessionLocal()
        try:
            row = (
                db.query(TaskCenterItem)
                .filter(TaskCenterItem.engine_task_id == normalized_task_id)
                .order_by(TaskCenterItem.updated_at.desc())
                .first()
            )
            if not row:
                return None
            payload = row.payload_json
            return dict(payload) if isinstance(payload, dict) else None
        finally:
            db.close()

    def diff_engine_item(self, expected_item: Dict[str, Any]) -> Dict[str, Any]:
        """对照旧聚合器输出和物化 payload。

        返回结构只给内部测试/诊断用，不进入当前 API 读路径。
        """
        engine_task_id = safe_text(
            expected_item.get("engine_task_id") or expected_item.get("entity_id"),
            strip=True,
        )
        actual = self.get_engine_item(engine_task_id)
        if actual is None:
            return {
                "matched": False,
                "engine_task_id": engine_task_id,
                "missing": True,
                "changed_keys": [],
            }

        changed_keys = sorted(
            key
            for key in set(expected_item.keys()) | set(actual.keys())
            if expected_item.get(key) != actual.get(key)
        )
        return {
            "matched": not changed_keys,
            "engine_task_id": engine_task_id,
            "missing": False,
            "changed_keys": changed_keys,
        }

    def list_items(
        self,
        *,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 200), 5000))
        safe_offset = max(0, int(offset or 0))
        normalized_domain = safe_text(domain, strip=True)
        normalized_status = safe_text(status, strip=True)
        normalized_search = _normalize_task_center_search(search)

        db = SessionLocal()
        try:
            query = db.query(TaskCenterItem)
            if normalized_domain and normalized_domain != "all":
                query = query.filter(TaskCenterItem.domain == normalized_domain)
            if normalized_status and normalized_status != "all":
                query = query.filter(TaskCenterItem.status == normalized_status)
            if normalized_search:
                like = f"%{_escape_ilike_pattern(normalized_search)}%"
                query = query.filter(TaskCenterItem.searchable_text.ilike(like, escape="!"))
            total = query.count()
            rows = (
                query.order_by(TaskCenterItem.updated_at.desc(), TaskCenterItem.created_at.desc())
                .offset(safe_offset)
                .limit(safe_limit)
                .all()
            )
            items: List[Dict[str, Any]] = []
            for row in rows:
                payload = row.payload_json
                if isinstance(payload, dict):
                    items.append(dict(payload))
            return {
                "items": items,
                "total": total,
                "offset": safe_offset,
                "limit": safe_limit,
            }
        finally:
            db.close()

    def list_engine_items(self, **kwargs) -> Dict[str, Any]:
        """兼容旧诊断接口名；当前返回全部物化 summary item。"""
        return self.list_items(**kwargs)

    def build_counts(self) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            counts_by_domain: Dict[str, int] = {}
            counts_by_status: Dict[str, int] = {}
            for domain, count in (
                db.query(TaskCenterItem.domain, func.count(TaskCenterItem.item_id))
                .group_by(TaskCenterItem.domain)
                .all()
            ):
                normalized = safe_text(domain, strip=True) or "system"
                counts_by_domain[normalized] = int(count or 0)
            for status, count in (
                db.query(TaskCenterItem.status, func.count(TaskCenterItem.item_id))
                .group_by(TaskCenterItem.status)
                .all()
            ):
                normalized = safe_text(status, strip=True) or "unknown"
                counts_by_status[normalized] = int(count or 0)
            return {
                "counts_by_domain": counts_by_domain,
                "counts_by_status": counts_by_status,
                "highlight_counts": {
                    "processing": counts_by_status.get(TaskStatus.PROCESSING.value, 0),
                    "waiting_total": (
                        counts_by_status.get(TaskStatus.PENDING.value, 0)
                        + counts_by_status.get(TaskStatus.PAUSED.value, 0)
                        + counts_by_status.get(TaskStatus.WAITING_MANUAL.value, 0)
                        + counts_by_status.get(TaskStatus.WAITING_RETRY.value, 0)
                    ),
                    "completed": counts_by_status.get(TaskStatus.COMPLETED.value, 0),
                    "waiting_manual": counts_by_status.get(TaskStatus.WAITING_MANUAL.value, 0),
                    "waiting_retry": counts_by_status.get(TaskStatus.WAITING_RETRY.value, 0),
                    "partial_failed": counts_by_status.get("partial_failed", 0),
                    "failed": counts_by_status.get(TaskStatus.FAILED.value, 0),
                },
            }
        finally:
            db.close()

    def diff_engine_items(self, expected_items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        diffs = [
            diff
            for item in expected_items
            if isinstance(item, dict) and safe_text(item.get("id"), strip=True).startswith("engine:")
            for diff in [self.diff_engine_item(item)]
            if not diff.get("matched")
        ]
        return {
            "matched": not diffs,
            "diff_count": len(diffs),
            "diffs": diffs[:50],
        }

    def diff_items(self, expected_items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        expected = [
            item for item in expected_items
            if isinstance(item, dict) and safe_text(item.get("id"), strip=True)
        ]
        db = SessionLocal()
        try:
            rows = {
                safe_text(row.item_id, strip=True): dict(row.payload_json or {})
                for row in db.query(TaskCenterItem)
                .filter(TaskCenterItem.item_id.in_([safe_text(item.get("id"), strip=True) for item in expected]))
                .all()
            }
        finally:
            db.close()

        diffs = []
        for item in expected:
            item_id = safe_text(item.get("id"), strip=True)
            actual = rows.get(item_id)
            if actual is None:
                diffs.append({"item_id": item_id, "missing": True, "changed_keys": []})
                continue
            changed_keys = sorted(key for key in set(item.keys()) | set(actual.keys()) if item.get(key) != actual.get(key))
            if changed_keys:
                diffs.append({"item_id": item_id, "missing": False, "changed_keys": changed_keys})
        return {
            "matched": not diffs,
            "diff_count": len(diffs),
            "diffs": diffs[:50],
        }


_task_center_materialization_service: Optional[TaskCenterMaterializationService] = None


def get_task_center_materialization_service() -> TaskCenterMaterializationService:
    global _task_center_materialization_service
    if _task_center_materialization_service is None:
        _task_center_materialization_service = TaskCenterMaterializationService()
    return _task_center_materialization_service
