"""任务列表的持久化轻量投影，不依赖任务引擎或运行态单例。"""
from datetime import datetime
import os

from .json_safety import safe_text


def build_list_projection(item):
    text = lambda value: safe_text(value, strip=True)
    stamp = 0.0
    for key in ("completed_at", "started_at", "created_at"):
        value = text(item.get(key))
        if value:
            try:
                stamp = datetime.fromisoformat(value).timestamp()
                break
            except ValueError:
                pass
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
    path = text(item.get("source_path"))
    if path:
        try:
            path = os.path.abspath(path)
        except Exception:
            pass
    recovered = metadata.get("recovered_failure_ids") or []
    return {
        "id": text(item.get("id")),
        "entity": text(item.get("entity_id")) or text(item.get("engine_task_id")),
        "waiting_entity": text(item.get("entity_id")),
        "domain": text(item.get("domain")), "status": text(item.get("status")),
        "kind": text(item.get("kind")), "stamp": stamp,
        "path_key": [path, item.get("kind"), item.get("subtype")] if path else None,
        "retry": text(metadata.get("retry_failed_task_id")),
        "superseded": bool(text(metadata.get("superseded_by_task_id"))),
        "recovered": [str(value) for value in recovered],
        "legacy": "subtype" not in item and bool(item.get("engine_task_id")) and (
            text(item.get("kind")).startswith("circle_completion_")
            or item.get("kind") in {"http_download", "asmr_sync_download"}),
        "search": " ".join(text(item.get(key)) for key in (
            "subtype_label", "title", "subtitle", "source_path", "rjcode", "current_step")),
        "subtype": text(item.get("subtype")),
    }


def backfill_list_projections(conn, batch_size=500):
    """按主键分批回填，保留原时间戳；并发快照更新后留给下一轮处理。"""
    from sqlalchemy import bindparam, text as sql_text
    from sqlalchemy.dialects.postgresql import JSONB

    cursor = ""
    count = 0
    statement = sql_text("""
        UPDATE task_center_items SET list_projection = :projection
        WHERE item_id = :item_id AND (list_projection IS NULL OR list_projection = 'null'::jsonb)
          AND payload_json = :snapshot
    """).bindparams(bindparam("projection", type_=JSONB), bindparam("snapshot", type_=JSONB))
    while True:
        rows = conn.execute(sql_text("""
            SELECT item_id, payload_json FROM task_center_items
            WHERE item_id > :cursor AND (list_projection IS NULL OR list_projection = 'null'::jsonb)
            ORDER BY item_id LIMIT :batch_size
        """), {"cursor": cursor, "batch_size": batch_size}).all()
        if not rows:
            return count
        values = [{
            "item_id": row.item_id, "snapshot": row.payload_json,
            "projection": build_list_projection(row.payload_json),
        } for row in rows if isinstance(row.payload_json, dict)]
        if values:
            conn.execute(statement, values)
            count += len(values)
        cursor = rows[-1].item_id
