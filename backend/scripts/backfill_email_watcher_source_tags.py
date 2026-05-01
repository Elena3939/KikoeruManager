"""
回溯补标脚本：把历史 activity_log 中 email_watcher 触发的 RJ 号
补写到 circle_works.source_tags。

命中规则：
1. canonical_rjcode == 邮件 RJ
2. display_rjcode == 邮件 RJ
3. linked_rjcodes JSON 数组中包含 邮件 RJ

用法：
  预览：py -3 backend/scripts/backfill_email_watcher_source_tags.py
  写入：py -3 backend/scripts/backfill_email_watcher_source_tags.py --apply
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys


APPLY = "--apply" in sys.argv


def get_db_path() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(root, "data", "cache.db")


def load_email_watcher_rjcodes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT action, rjcode, detail
        FROM activity_logs
        WHERE category = 'email_watcher'
          AND action IN ('fetch_check', 'circle_index_triggered')
        """
    ).fetchall()
    codes: list[str] = []
    seen = set()
    for action, rjcode, detail in rows:
        if action == "circle_index_triggered" and str(rjcode or "").strip():
            code = str(rjcode).strip().upper()
            if code not in seen:
                seen.add(code)
                codes.append(code)
        detail_obj = {}
        if isinstance(detail, str) and detail.strip():
            try:
                detail_obj = json.loads(detail)
            except Exception:
                detail_obj = {}
        elif isinstance(detail, dict):
            detail_obj = detail
        for code in list(detail_obj.get("rjcodes") or []):
            normalized = str(code or "").strip().upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                codes.append(normalized)
    return codes


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rjcodes = load_email_watcher_rjcodes(conn)
        print(f"从 activity_log 找到历史 email_watcher RJ 号共 {len(rjcodes)} 个:")
        for code in rjcodes:
            print(f"  {code}")

        updated = []
        skipped = []
        not_found = []

        rows = conn.execute(
            "SELECT id, canonical_rjcode, display_rjcode, linked_rjcodes, source_tags FROM circle_works"
        ).fetchall()

        for rjcode in rjcodes:
            matched = False
            for row in rows:
                linked = row["linked_rjcodes"]
                linked_list = []
                if isinstance(linked, str) and linked.strip():
                    try:
                        linked_list = list(json.loads(linked))
                    except Exception:
                        linked_list = []
                candidates = {
                    str(row["canonical_rjcode"] or "").strip().upper(),
                    str(row["display_rjcode"] or "").strip().upper(),
                    *(str(code or "").strip().upper() for code in linked_list),
                }
                if rjcode not in candidates:
                    continue
                matched = True
                tags = row["source_tags"]
                tag_list = []
                if isinstance(tags, str) and tags.strip():
                    try:
                        tag_list = list(json.loads(tags))
                    except Exception:
                        tag_list = []
                if "email_watcher" in tag_list:
                    skipped.append(rjcode)
                    break
                tag_list.append("email_watcher")
                updated.append(rjcode)
                if APPLY:
                    conn.execute(
                        "UPDATE circle_works SET source_tags = ? WHERE id = ?",
                        (json.dumps(tag_list, ensure_ascii=False), row["id"]),
                    )
                break
            if not matched:
                not_found.append(rjcode)

        print(f"\n需要补标: {len(updated)} 个 — {updated}")
        print(f"已有标签跳过: {len(skipped)} 个 — {skipped}")
        print(f"未在 circle_works 找到: {len(not_found)} 个 — {not_found}")

        if APPLY:
            conn.commit()
            print(f"\n已写入 {len(updated)} 个作品的 source_tags = email_watcher")
        else:
            conn.rollback()
            print("\n预览模式，加 --apply 参数才会真正写入")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
