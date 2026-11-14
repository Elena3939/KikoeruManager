"""原始审计详情无损归档，只有详情或重建路径需要解压。"""
import json
import zlib
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from ..models.database import ActivityLogDetailArchive as Archive


def archive_detail(db, row):
    payload = zlib.compress(json.dumps(row.detail, ensure_ascii=True, default=str,
                                      separators=(",", ":")).encode(), level=6)
    db.execute(insert(Archive).values(event_id=row.id, payload=payload, created_at=datetime.now())
               .on_conflict_do_nothing())


def restore_details(db, rows):
    """批量恢复，保持压缩后发生的状态/重试回写字段；不修改 ORM 实体。"""
    values = {row.id: row.to_dict() for row in rows}
    ids = [key for key, row in values.items() if (row.get("detail") or {}).get("__archive_version") == 1]
    if ids:
        for archive in db.query(Archive).filter(Archive.event_id.in_(ids)):
            row = values[archive.event_id]
            detail = dict(row["detail"])
            original = json.loads(zlib.decompress(archive.payload))
            original.update({key: value for key, value in detail.items()
                             if not key.startswith("__compact") and key != "__archive_version"})
            row["detail"] = original
    return values
