from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "data" / "cache.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并历史重复社团索引数据")
    parser.add_argument("--apply", action="store_true", help="执行写入迁移；默认只预览")
    return parser.parse_args()


def fetch_duplicate_groups(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT circle_name_normalized
        FROM circle_catalogs
        WHERE circle_name_normalized IS NOT NULL AND TRIM(circle_name_normalized) <> ''
        GROUP BY circle_name_normalized
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, circle_name_normalized ASC
        """
    ).fetchall()

    groups: list[dict] = []
    for row in rows:
        normalized_name = str(row["circle_name_normalized"] or "").strip()
        catalog_rows = conn.execute(
            """
            SELECT circle_id, circle_name, circle_name_normalized, source_mask,
                   last_indexed_at, last_local_sync_at, created_at, updated_at
            FROM circle_catalogs
            WHERE circle_name_normalized = ?
            ORDER BY
                COALESCE(last_indexed_at, updated_at, created_at) DESC,
                COALESCE(updated_at, created_at) DESC,
                circle_id ASC
            """,
            (normalized_name,),
        ).fetchall()
        if len(catalog_rows) <= 1:
            continue
        groups.append(
            {
                "normalized_name": normalized_name,
                "catalogs": [dict(item) for item in catalog_rows],
            }
        )
    return groups


def merge_source_mask(values: Iterable[str]) -> str:
    flags: set[str] = set()
    for value in values:
        for part in str(value or "").split(","):
            text = part.strip()
            if text:
                flags.add(text)
    return ",".join(sorted(flags))


def merge_linked_rjcodes(*values) -> str:
    merged: set[str] = set()
    for value in values:
        current = value
        if not current:
            continue
        if isinstance(current, str):
            try:
                parsed = json.loads(current)
            except Exception:
                parsed = []
        else:
            parsed = current
        if isinstance(parsed, list):
            for item in parsed:
                text = str(item or "").strip()
                if text:
                    merged.add(text)
    return json.dumps(sorted(merged), ensure_ascii=False)


def choose_text(*values) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def choose_int(*values) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return None


def choose_latest(*values) -> str | None:
    valid = [str(value).strip() for value in values if str(value or "").strip()]
    if not valid:
        return None
    return max(valid)


def merge_circle_work_row(keeper: sqlite3.Row, duplicate: sqlite3.Row) -> dict:
    return {
        "display_rjcode": choose_text(keeper["display_rjcode"], duplicate["display_rjcode"]),
        "title": choose_text(keeper["title"], duplicate["title"]),
        "maker_id": choose_text(keeper["maker_id"], duplicate["maker_id"]),
        "maker_name": choose_text(keeper["maker_name"], duplicate["maker_name"]),
        "source_mask": merge_source_mask([keeper["source_mask"], duplicate["source_mask"]]),
        "linked_rjcodes": merge_linked_rjcodes(keeper["linked_rjcodes"], duplicate["linked_rjcodes"]),
        "has_kikoeru": 1 if bool(keeper["has_kikoeru"]) or bool(duplicate["has_kikoeru"]) else 0,
        "has_dlsite": 1 if bool(keeper["has_dlsite"]) or bool(duplicate["has_dlsite"]) else 0,
        "has_asmr_one": 1 if bool(keeper["has_asmr_one"]) or bool(duplicate["has_asmr_one"]) else 0,
        "kikoeru_work_id": choose_int(keeper["kikoeru_work_id"], duplicate["kikoeru_work_id"]),
        "asmr_one_cached_at": choose_latest(keeper["asmr_one_cached_at"], duplicate["asmr_one_cached_at"]),
        "dlsite_cached_at": choose_latest(keeper["dlsite_cached_at"], duplicate["dlsite_cached_at"]),
        "updated_at": choose_latest(keeper["updated_at"], duplicate["updated_at"], datetime.now().isoformat(timespec="seconds")),
    }


def backup_db() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"cache.before-merge-duplicate-circles.{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def apply_merge(conn: sqlite3.Connection, groups: list[dict]) -> dict:
    summary = {
        "group_count": len(groups),
        "merged_catalog_count": 0,
        "moved_work_count": 0,
        "merged_work_count": 0,
        "deleted_catalog_count": 0,
        "deleted_work_count": 0,
    }

    for group in groups:
        catalogs = group["catalogs"]
        keeper = catalogs[0]
        keeper_id = keeper["circle_id"]
        duplicate_ids = [item["circle_id"] for item in catalogs[1:]]
        summary["merged_catalog_count"] += len(duplicate_ids)

        merged_catalog_source_mask = merge_source_mask(item.get("source_mask") for item in catalogs)
        last_indexed_at = choose_latest(*(item.get("last_indexed_at") for item in catalogs))
        last_local_sync_at = choose_latest(*(item.get("last_local_sync_at") for item in catalogs))
        circle_name = choose_text(*(item.get("circle_name") for item in catalogs))

        conn.execute(
            """
            UPDATE circle_catalogs
            SET circle_name = ?, source_mask = ?, last_indexed_at = ?, last_local_sync_at = ?, updated_at = ?
            WHERE circle_id = ?
            """,
            (
                circle_name,
                merged_catalog_source_mask,
                last_indexed_at,
                last_local_sync_at,
                datetime.now().isoformat(timespec="seconds"),
                keeper_id,
            ),
        )

        for duplicate_id in duplicate_ids:
            work_rows = conn.execute(
                """
                SELECT *
                FROM circle_works
                WHERE circle_id = ?
                ORDER BY COALESCE(updated_at, created_at) DESC, id ASC
                """,
                (duplicate_id,),
            ).fetchall()
            for work_row in work_rows:
                canonical = work_row["canonical_rjcode"]
                keeper_work = conn.execute(
                    """
                    SELECT *
                    FROM circle_works
                    WHERE circle_id = ? AND canonical_rjcode = ?
                    """,
                    (keeper_id, canonical),
                ).fetchone()
                if keeper_work:
                    merged = merge_circle_work_row(keeper_work, work_row)
                    conn.execute(
                        """
                        UPDATE circle_works
                        SET display_rjcode = ?, title = ?, maker_id = ?, maker_name = ?, source_mask = ?,
                            linked_rjcodes = ?, has_kikoeru = ?, has_dlsite = ?, has_asmr_one = ?,
                            kikoeru_work_id = ?, asmr_one_cached_at = ?, dlsite_cached_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            merged["display_rjcode"],
                            merged["title"],
                            merged["maker_id"],
                            merged["maker_name"],
                            merged["source_mask"],
                            merged["linked_rjcodes"],
                            merged["has_kikoeru"],
                            merged["has_dlsite"],
                            merged["has_asmr_one"],
                            merged["kikoeru_work_id"],
                            merged["asmr_one_cached_at"],
                            merged["dlsite_cached_at"],
                            merged["updated_at"],
                            keeper_work["id"],
                        ),
                    )
                    conn.execute("DELETE FROM circle_works WHERE id = ?", (work_row["id"],))
                    summary["merged_work_count"] += 1
                    summary["deleted_work_count"] += 1
                else:
                    conn.execute(
                        "UPDATE circle_works SET circle_id = ?, updated_at = ? WHERE id = ?",
                        (keeper_id, datetime.now().isoformat(timespec="seconds"), work_row["id"]),
                    )
                    summary["moved_work_count"] += 1

            conn.execute("DELETE FROM circle_catalogs WHERE circle_id = ?", (duplicate_id,))
            summary["deleted_catalog_count"] += 1

    return summary


def main() -> int:
    args = parse_args()
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    groups = fetch_duplicate_groups(conn)
    print(f"数据库: {DB_PATH}")
    print(f"重复社团组数: {len(groups)}")
    for group in groups[:20]:
        names = [str(item.get("circle_name") or item.get("circle_id") or "") for item in group["catalogs"]]
        ids = [str(item.get("circle_id") or "") for item in group["catalogs"]]
        print(f"- {group['normalized_name']}: {len(group['catalogs'])} 条 -> {' | '.join(ids)}")
        print(f"  名称: {' | '.join(names)}")

    if not args.apply:
        print("当前为预览模式，未写入任何数据。")
        conn.close()
        return 0

    backup_path = backup_db()
    print(f"已备份数据库: {backup_path}")
    try:
        conn.execute("BEGIN")
        summary = apply_merge(conn, groups)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()

    print("合并完成:")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
