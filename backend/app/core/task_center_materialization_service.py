import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Text, any_, case, cast, func, or_, text
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.exc import DBAPIError, DataError, IntegrityError, StatementError

from .task_engine import TaskStatus
from .json_safety import safe_text
from .task_center_list_projection import build_list_projection
from .resource_budget_service import get_resource_budget_service
from ..models.database import SessionLocal, TaskCenterItem

logger = logging.getLogger(__name__)


def _escape_ilike_pattern(value: str) -> str:
    return str(value or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")


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
            item.get("subtype_label"),
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

    def _snapshot_values(
        self,
        item: Dict[str, Any],
        *,
        version: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        item_id = safe_text(item.get("id"), strip=True)
        if not item_id:
            return None

        engine_task_id = safe_text(item.get("engine_task_id") or item.get("entity_id"), strip=True)

        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        payload_metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
        source_metadata = metadata if isinstance(metadata, dict) else {}
        business_key = safe_text(
            payload_metadata.get("business_key") or source_metadata.get("business_key"),
            strip=True,
        )
        try:
            snapshot_version = int(version or 0)
        except (TypeError, ValueError, OverflowError):
            logger.warning("[任务中心物化] 忽略无效版本的快照")
            return None
        now = datetime.now()
        return {
            "item_id": item_id,
            "engine_task_id": engine_task_id,
            "domain": safe_text(item.get("domain"), strip=True),
            "status": safe_text(item.get("status"), strip=True),
            "kind": safe_text(item.get("kind"), strip=True),
            "title": safe_text(item.get("title"), strip=True),
            "source_page": safe_text(item.get("source_page"), strip=True),
            "source_action": safe_text(item.get("source_action"), strip=True),
            "business_key": business_key,
            "searchable_text": self._item_searchable_text(item, metadata),
            "payload_json": item,
            "list_projection": build_list_projection(item),
            "version": snapshot_version,
            "created_at": now,
            "updated_at": now,
        }

    def _write_snapshot_batch(self, rows: List[Dict[str, Any]]) -> set[str]:
        if not rows:
            return set()
        # 同批相同主键只写最后一份，避免 ON CONFLICT 一条语句重复更新同一行。
        unique_rows = {row["item_id"]: row for row in rows}
        table = TaskCenterItem.__table__
        statement = insert(table).values([unique_rows[key] for key in sorted(unique_rows)])
        fields = [key for key in rows[0] if key not in {"item_id", "created_at", "updated_at"}]
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.item_id],
            set_={key: statement.excluded[key] for key in [*fields, "updated_at"]},
            where=or_(*(table.c[key].is_distinct_from(statement.excluded[key]) for key in fields)),
        )
        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("database_write", reason="task_center.materialize_upsert"):
                db.execute(statement)
                db.commit()
            return set(unique_rows)
        except Exception as exc:
            db.rollback()
            logger.warning("[任务中心物化] 写入快照失败: count=%s error=%s", len(unique_rows), type(exc).__name__)
            isolate_rows = isinstance(exc, (DataError, IntegrityError)) or (
                isinstance(exc, StatementError) and not isinstance(exc, DBAPIError)
            )
        finally:
            db.close()
        # 单条坏数据不能阻止同批其它任务落库；拆半定位，正常路径仍只提交一次。
        if isolate_rows and len(unique_rows) > 1:
            values = list(unique_rows.values())
            middle = len(values) // 2
            return self._write_snapshot_batch(values[:middle]) | self._write_snapshot_batch(values[middle:])
        return set()

    def upsert_item(
        self,
        item: Dict[str, Any],
        *,
        version: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = self._snapshot_values(item, version=version, metadata=metadata)
        if row:
            self._write_snapshot_batch([row])

    def upsert_engine_snapshots(
        self, snapshots: Iterable[tuple[Dict[str, Any], int, Dict[str, Any]]],
    ) -> set[str]:
        """合并后台快照提交，保留每个任务自己的版本和元数据。"""
        written: set[str] = set()
        batch = []
        for item, version, metadata in snapshots:
            if not safe_text(item.get("id"), strip=True).startswith("engine:"):
                continue
            row = self._snapshot_values(item, version=version, metadata=metadata)
            if row:
                batch.append(row)
            if len(batch) >= 250:
                written.update(self._write_snapshot_batch(batch))
                batch = []
        written.update(self._write_snapshot_batch(batch))
        return written

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
        batch = []
        for item in items:
            if not isinstance(item, dict):
                continue
            engine_task_id = safe_text(item.get("engine_task_id") or item.get("entity_id"), strip=True)
            row = self._snapshot_values(
                item,
                version=version,
                metadata=metadata_by_task_id.get(engine_task_id),
            )
            if row:
                batch.append(row)
            if len(batch) >= 250:
                count += len(self._write_snapshot_batch(batch))
                batch = []
        count += len(self._write_snapshot_batch(batch))
        return count

    def upsert_engine_items(
        self,
        items: Iterable[Dict[str, Any]],
        *,
        version: int = 0,
        metadata_by_task_id: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        metadata_by_task_id = metadata_by_task_id or {}
        return self.upsert_items(
            (item for item in items if isinstance(item, dict)
             and safe_text(item.get("id"), strip=True).startswith("engine:")),
            version=version,
            metadata_by_task_id=metadata_by_task_id,
        )

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
                    query = query.filter(~(TaskCenterItem.item_id == any_(cast(sorted(valid_ids), ARRAY(Text)))))
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
                    query = query.filter(~(TaskCenterItem.engine_task_id == any_(cast(sorted(valid_ids), ARRAY(Text)))))
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
        subtype: Optional[str] = None,
        ordered_ids: Optional[List[str]] = None,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 200), 5000))
        safe_offset = max(0, int(offset or 0))
        normalized_domain = safe_text(domain, strip=True)
        normalized_status = safe_text(status, strip=True)
        normalized_search = safe_text(search, strip=True).lower()

        db = SessionLocal()
        try:
            query = db.query(TaskCenterItem.payload_json)
            def field(key, default):
                replacements = {item_id: safe_text(item.get(key)) for item_id, item in (overrides or {}).items()}
                return case(replacements, value=TaskCenterItem.item_id, else_=default) if replacements else default

            if ordered_ids is not None:
                # 一次数组参数替代超长 IN + CASE，避免重数据下超过绑定参数上限。
                positions = {item_id: position for position, item_id in enumerate(ordered_ids)}
                ids = sorted(positions, key=positions.get)
                ordering = (
                    func.unnest(cast(ids, ARRAY(Text)))
                    .table_valued("item_id", with_ordinality="position")
                    .render_derived(name="task_order")
                )
                query = query.join(ordering, TaskCenterItem.item_id == ordering.c.item_id)
            if subtype and subtype != "all":
                query = query.filter(field("subtype", TaskCenterItem.payload_json["subtype"].as_string()) == subtype)
            if normalized_domain and normalized_domain != "all":
                query = query.filter(field("domain", TaskCenterItem.domain) == normalized_domain)
            if normalized_status and normalized_status != "all":
                query = query.filter(field("status", TaskCenterItem.status) == normalized_status)
            if normalized_search:
                like = f"%{_escape_ilike_pattern(normalized_search)}%"
                if ordered_ids is None:
                    query = query.filter(TaskCenterItem.searchable_text.ilike(like, escape="!"))
                else:
                    # 正式摘要与旧聚合器使用相同字段，支持单字及字面量通配符搜索。
                    parts = [func.coalesce(field(key, TaskCenterItem.payload_json[key].as_string()), "")
                             for key in ("subtype_label", "title", "subtitle", "source_path", "rjcode", "current_step")]
                    text = parts[0]
                    for part in parts[1:]:
                        text = text + " " + part
                    query = query.filter(text.ilike(like, escape="!"))
            total = query.count()
            order = ([ordering.c.position] if ordered_ids is not None
                     else [TaskCenterItem.updated_at.desc(), TaskCenterItem.created_at.desc()])
            rows = (
                query.order_by(*order)
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

    def list_summary_page(
        self, *, domain=None, subtype=None, status=None, search=None, limit=200, offset=0,
        status_priority, domain_priority,
    ):
        """在同一个数据库快照内完成替代去重、统计与分页，只读取本页 payload。"""
        import json

        params = {
            "domain": safe_text(domain, strip=True), "status": safe_text(status, strip=True),
            "subtype": subtype or "", "search": safe_text(search, strip=True).lower(),
            "limit": max(1, min(int(limit or 200), 500)), "offset": max(0, int(offset or 0)),
            "status_priority": json.dumps(status_priority), "domain_priority": json.dumps(domain_priority),
        }
        params["pattern"] = "%" + _escape_ilike_pattern(params["search"]) + "%"
        db = SessionLocal()
        try:
            # 替代关系合并后按键开窗，避免 JSON 投影行数估算偏低触发嵌套扫描。
            result = db.execute(text("""
                WITH base AS MATERIALIZED (
                    SELECT t.item_id, t.created_at, t.updated_at, p.*
                    FROM task_center_items t
                    CROSS JOIN LATERAL jsonb_to_record(NULLIF(t.list_projection, 'null'::jsonb)) AS p(
                        id text, entity text, waiting_entity text, domain text, status text,
                        kind text, stamp double precision, path_key jsonb, retry text,
                        superseded boolean, recovered jsonb, legacy boolean, search text, subtype text)
                ), waiting AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY waiting_entity ORDER BY updated_at DESC, created_at DESC, item_id
                    ) AS position FROM base WHERE kind = 'asmr_sync_waiting_retry'
                ), deduped AS MATERIALIZED (
                    SELECT item_id, id, entity, domain, status, kind, stamp, path_key,
                           retry, superseded, recovered, search, subtype
                    FROM base WHERE kind <> 'asmr_sync_waiting_retry'
                    UNION ALL
                    SELECT item_id, id, entity, domain, status, kind, stamp, path_key,
                           retry, superseded, recovered, search, subtype
                    FROM waiting WHERE position = 1
                ), targets AS MATERIALIZED (
                    SELECT d.item_id, COALESCE(NULLIF(d.stamp, 0), '-Infinity'::float8) AS stamp,
                           k.key
                    FROM deduped d CROSS JOIN LATERAL (
                        SELECT jsonb_build_array('entity', d.entity) AS key
                        UNION ALL
                        SELECT jsonb_build_array('path', d.path_key)
                        WHERE d.path_key <> 'null'::jsonb
                    ) k
                    WHERE left(d.id, 7) = 'engine:'
                      AND d.status IN ('pending','processing','paused','waiting_manual','waiting_retry')
                ), candidates AS (
                    SELECT d.item_id, COALESCE(NULLIF(d.stamp, 0), 'Infinity'::float8) AS stamp,
                           jsonb_build_array('entity', d.retry) AS key
                    FROM deduped d
                    WHERE left(d.id, 7) = 'engine:' AND d.retry <> ''
                    UNION ALL
                    SELECT d.item_id, COALESCE(NULLIF(d.stamp, 0), 'Infinity'::float8),
                           jsonb_build_array('entity', r.value)
                    FROM deduped d CROSS JOIN LATERAL jsonb_array_elements_text(d.recovered) r(value)
                    WHERE left(d.id, 7) = 'engine:' AND d.status = 'completed'
                    UNION ALL
                    SELECT d.item_id, COALESCE(NULLIF(d.stamp, 0), 'Infinity'::float8),
                           jsonb_build_array('path', d.path_key)
                    FROM deduped d
                    WHERE left(d.id, 7) = 'engine:' AND d.status = 'completed'
                      AND d.path_key <> 'null'::jsonb
                ), relations AS (
                    SELECT DISTINCT item_id, key, stamp AS candidate_stamp, NULL::float8 AS target_stamp
                    FROM candidates
                    UNION ALL
                    SELECT item_id, key, NULL::float8, stamp FROM targets
                ), ranked AS (
                    SELECT *, first_value(item_id) OVER w AS first_id,
                           first_value(candidate_stamp) OVER w AS first_stamp,
                           nth_value(item_id, 2) OVER w AS second_id,
                           nth_value(candidate_stamp, 2) OVER w AS second_stamp
                    FROM relations WINDOW w AS (
                        PARTITION BY key ORDER BY candidate_stamp DESC NULLS LAST, item_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
                ), blocked AS (
                    SELECT DISTINCT item_id FROM ranked WHERE target_stamp IS NOT NULL
                      AND ((first_id <> item_id AND first_stamp >= target_stamp)
                           OR (second_id <> item_id AND second_stamp >= target_stamp))
                ), visible AS MATERIALIZED (
                    SELECT d.item_id, d.id, d.domain, d.status, d.stamp, d.search, d.subtype FROM deduped d
                    WHERE NOT EXISTS (SELECT 1 FROM blocked b WHERE b.item_id = d.item_id)
                      AND NOT (d.superseded AND (d.status = 'failed' OR
                          (left(d.id, 7) = 'engine:' AND d.status IN
                          ('pending','processing','paused','waiting_manual','waiting_retry'))))
                ), filtered AS MATERIALIZED (
                    SELECT item_id, id, domain, status, stamp FROM visible
                    WHERE (:domain IN ('','all') OR domain = :domain)
                      AND (:status IN ('','all') OR status = :status)
                      AND (:subtype IN ('','all') OR subtype = :subtype)
                      AND (:search = '' OR search ILIKE :pattern ESCAPE '!')
                ), page AS (
                    SELECT item_id, row_number() OVER (ORDER BY
                        COALESCE((CAST(:status_priority AS jsonb)->>status)::int,99),
                        COALESCE((CAST(:domain_priority AS jsonb)->>domain)::int,99),
                        stamp DESC, id COLLATE "C") AS position
                    FROM filtered ORDER BY position LIMIT :limit OFFSET :offset
                )
                SELECT
                    NOT EXISTS (SELECT 1 FROM base WHERE legacy OR id IS NULL) AS ready,
                    (SELECT count(*) FROM filtered) AS total,
                    COALESCE((SELECT jsonb_agg(t.payload_json ORDER BY p.position)
                        FROM page p JOIN task_center_items t USING(item_id)), '[]'::jsonb) AS items,
                    COALESCE((SELECT jsonb_agg(s) FROM (
                        SELECT domain, status, count(*) AS count FROM visible GROUP BY domain, status
                    ) s), '[]'::jsonb) AS counts
            """), params).mappings().one()
            if not result["ready"]:
                return None
            return {"items": result["items"], "total": result["total"],
                    "offset": params["offset"], "limit": params["limit"], "counts": result["counts"]}
        finally:
            db.close()

    def list_identity_projection(self) -> List[Dict[str, Any]]:
        """仅取去重/排序依赖；大 payload 只在 SQL 分页后读取。"""
        fields = ("id", "entity_id", "engine_task_id", "domain", "status", "kind", "subtype",
                  "source_path", "created_at", "started_at", "completed_at")
        metadata_keys = ("retry_failed_task_id", "superseded_by_task_id", "recovered_failure_ids")
        payload = TaskCenterItem.payload_json
        db = SessionLocal()
        try:
            columns = [payload[key].as_string() for key in fields]
            columns.extend(payload["details"]["metadata"][key] for key in metadata_keys)
            rows = (db.query(*columns)
                    .order_by(TaskCenterItem.updated_at.desc(), TaskCenterItem.created_at.desc(),
                              TaskCenterItem.item_id).all())
            items = []
            for row in rows:
                item = {key: value for key, value in zip(fields, row) if value is not None}
                item["details"] = {"metadata": dict(zip(metadata_keys, row[len(fields):]))}
                items.append(item)
            return items
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
                .filter(TaskCenterItem.item_id == any_(cast(
                    [safe_text(item.get("id"), strip=True) for item in expected], ARRAY(Text))))
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
