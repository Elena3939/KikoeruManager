"""清理已落库的错误社团补全数据。

默认预览；加 --apply 才会真正写库。
纯 sqlite3 版本，避免依赖运行环境里的 ORM 扩展包。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime


INVALID_CATALOG_NAMES = {
    "みんなで翻訳 お助け隊",
}

INVALID_CIRCLE_IDS = {
    "RG69077",
}

INVALID_RJ_CODES = {
    "RJ01547734",
}


def get_db_path() -> str:
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_dir = os.path.join(root_dir, "data")
    return os.path.join(data_dir, "cache.db")


def json_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写入数据库")
    args = parser.parse_args()

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    summary = {
        "db_path": db_path,
        "deleted_catalogs": [],
        "deleted_circle_work_ids": [],
        "deleted_activity_log_ids": [],
        "deleted_canonical_link_ids": [],
    }

    try:
        catalogs = conn.execute(
            """
            SELECT circle_id, circle_name
            FROM circle_catalogs
            WHERE circle_id IN ({circle_ids})
               OR circle_name IN ({circle_names})
            """.format(
                circle_ids=",".join("?" for _ in INVALID_CIRCLE_IDS),
                circle_names=",".join("?" for _ in INVALID_CATALOG_NAMES),
            ),
            [*INVALID_CIRCLE_IDS, *INVALID_CATALOG_NAMES],
        ).fetchall()
        circle_ids = {str(row["circle_id"] or "").strip() for row in catalogs if str(row["circle_id"] or "").strip()}
        circle_ids.update(INVALID_CIRCLE_IDS)

        summary["deleted_catalogs"] = [dict(row) for row in catalogs]

        circle_works = conn.execute(
            """
            SELECT id, circle_id, canonical_rjcode, display_rjcode, title
            FROM circle_works
            WHERE circle_id IN ({circle_ids})
               OR canonical_rjcode IN ({rjcodes})
               OR display_rjcode IN ({rjcodes2})
            """.format(
                circle_ids=",".join("?" for _ in circle_ids),
                rjcodes=",".join("?" for _ in INVALID_RJ_CODES),
                rjcodes2=",".join("?" for _ in INVALID_RJ_CODES),
            ),
            [*circle_ids, *INVALID_RJ_CODES, *INVALID_RJ_CODES],
        ).fetchall()
        summary["deleted_circle_work_ids"] = [dict(row) for row in circle_works]

        activity_logs = conn.execute(
            "SELECT id, summary, detail FROM activity_logs WHERE category = 'circle_completion'"
        ).fetchall()
        for row in activity_logs:
            summary_text = str(row["summary"] or "")
            detail_text = json_text(row["detail"])
            if any(marker in summary_text or marker in detail_text for marker in (*INVALID_CATALOG_NAMES, *INVALID_CIRCLE_IDS, *INVALID_RJ_CODES)):
                summary["deleted_activity_log_ids"].append(str(row["id"] or ""))

        canonical_links = conn.execute(
            """
            SELECT id
            FROM work_canonical_links
            WHERE canonical_rjcode IN ({rjcodes})
               OR linked_rjcode IN ({rjcodes2})
            """.format(
                rjcodes=",".join("?" for _ in INVALID_RJ_CODES),
                rjcodes2=",".join("?" for _ in INVALID_RJ_CODES),
            ),
            [*INVALID_RJ_CODES, *INVALID_RJ_CODES],
        ).fetchall()
        summary["deleted_canonical_link_ids"] = [str(row["id"] or "") for row in canonical_links]

        print(json.dumps({
            "apply": bool(args.apply),
            "timestamp": datetime.now().isoformat(),
            **summary,
        }, ensure_ascii=False, indent=2))

        if not args.apply:
            conn.rollback()
            return 0

        if summary["deleted_canonical_link_ids"]:
            conn.execute(
                "DELETE FROM work_canonical_links WHERE id IN ({ids})".format(
                    ids=",".join("?" for _ in summary["deleted_canonical_link_ids"])
                ),
                summary["deleted_canonical_link_ids"],
            )
        if summary["deleted_circle_work_ids"]:
            conn.execute(
                "DELETE FROM circle_works WHERE id IN ({ids})".format(
                    ids=",".join("?" for _ in summary["deleted_circle_work_ids"])
                ),
                [row["id"] for row in summary["deleted_circle_work_ids"]],
            )
        if summary["deleted_catalogs"]:
            conn.execute(
                "DELETE FROM circle_catalogs WHERE circle_id IN ({ids})".format(
                    ids=",".join("?" for _ in summary["deleted_catalogs"])
                ),
                [row["circle_id"] for row in summary["deleted_catalogs"]],
            )
        if summary["deleted_activity_log_ids"]:
            conn.execute(
                "DELETE FROM activity_logs WHERE id IN ({ids})".format(
                    ids=",".join("?" for _ in summary["deleted_activity_log_ids"])
                ),
                summary["deleted_activity_log_ids"],
            )
        conn.commit()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
