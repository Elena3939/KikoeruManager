"""回填旧批量社团补全操作记录的子社团摘要。

旧逻辑里批量社团索引是一个 Task 顺序跑多个社团，task_finished 只保留了
最后一个社团的 circle_id/circle_name，导致操作历史无法展开批量子项。
本脚本从同一时间窗口内的 index_completed 记录反推每个社团的统计，并写回
task_finished.detail.batch_circle_summaries。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "cache.db"

KNOWN_CIRCLE_NAME_FIXES = {
    # 旧库里这几个社团名曾被乱码写入；按稳定 RG id 修正旧批量历史子项显示。
    "RG48424": "\u30d1\u30fc\u30b9\u30da\u30af\u30c6\u30a3\u30d6\u5c11\u5973\u5e7b\u594f",
    "RG51745": "\u732b\u9ea6",
    "RG49556": "RaRo",
    "RG53375": "\u30b9\u30bf\u30b8\u30aa\u308a\u3075\u308c\u307c",
}


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _batch_queries(detail: dict[str, Any]) -> list[str]:
    business_key = str(detail.get("business_key") or "").strip()
    if business_key.startswith("batch:"):
        values = business_key.removeprefix("batch:").split("|")
        return [item.strip() for item in values if item.strip()]
    return []


def _summary_from_index_detail(circle_query: str, detail: dict[str, Any]) -> dict[str, Any]:
    indexed_counts = detail.get("indexed_counts") if isinstance(detail.get("indexed_counts"), dict) else {}
    circle_id = str(detail.get("circle_id") or "").strip()
    circle_name = KNOWN_CIRCLE_NAME_FIXES.get(circle_id) or str(detail.get("circle_name") or circle_query).strip()
    return {
        "success": True,
        "circle_query": circle_query,
        "circle_id": circle_id,
        "circle_name": circle_name,
        "works": _safe_int(indexed_counts.get("works") or detail.get("works_count") or detail.get("dl_count")),
        "local_owned_count": _safe_int(detail.get("local_owned_count") or indexed_counts.get("local_owned_count")),
        "kikoeru_owned_count": _safe_int(detail.get("owned_count") or indexed_counts.get("owned_count")),
        "dl_count": _safe_int(detail.get("dl_count") or indexed_counts.get("dl_count")),
        "asmr_available_count": _safe_int(detail.get("asmr_available_count") or indexed_counts.get("asmr_available_count") or indexed_counts.get("downloadable_count")),
        "downloadable_count": _safe_int(detail.get("downloadable_count") or indexed_counts.get("downloadable_count")),
        "missing_count": _safe_int(detail.get("missing_count") or indexed_counts.get("missing_count")),
    }


def backfill(*, apply: bool = False) -> dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0
    candidates = 0
    previews: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, summary, detail
            FROM activity_logs
            WHERE category='circle_completion'
              AND action IN ('task_finished','task_finished_incomplete')
            ORDER BY created_at ASC
            """
        ).fetchall()
        for row in rows:
            detail = _loads(row["detail"])
            queries = _batch_queries(detail)
            existing_summaries = [
                item for item in list(detail.get("batch_circle_summaries") or [])
                if isinstance(item, dict)
            ]
            if not queries and len(existing_summaries) > 1:
                queries = [str(item.get("circle_query") or item.get("circle_name") or "").strip() for item in existing_summaries]
            if len(queries) <= 1 and len(existing_summaries) <= 1:
                continue
            candidates += 1
            finished_at = _parse_dt(row["created_at"])
            if not finished_at:
                continue
            duration_ms = _safe_int(detail.get("duration_ms"))
            started_at = finished_at - timedelta(milliseconds=duration_ms or 0)
            # 给异步写日志留一点缓冲，避免 index_completed 比 task_finished 早/晚几秒。
            window_start = started_at - timedelta(minutes=2)
            window_end = finished_at + timedelta(minutes=2)
            index_rows = conn.execute(
                """
                SELECT id, created_at, detail
                FROM activity_logs
                WHERE category='circle_completion'
                  AND action='index_completed'
                  AND created_at BETWEEN ? AND ?
                ORDER BY created_at ASC
                """,
                (window_start.isoformat(sep=" "), window_end.isoformat(sep=" ")),
            ).fetchall()
            by_circle: dict[str, dict[str, Any]] = {}
            for index_row in index_rows:
                index_detail = _loads(index_row["detail"])
                circle_name = str(index_detail.get("circle_name") or "").strip()
                if circle_name:
                    by_circle[circle_name] = index_detail

            summaries: list[dict[str, Any]] = []
            for query in queries:
                matched = by_circle.get(query)
                if matched:
                    summaries.append(_summary_from_index_detail(query, matched))
                else:
                    summaries.append({
                        "success": False,
                        "circle_query": query,
                        "circle_name": query,
                        "error_message": "未找到对应 index_completed 记录",
                    })
            if existing_summaries and sum(1 for item in summaries if item.get("success")) == 0:
                summaries = existing_summaries
            for item in summaries:
                if not isinstance(item, dict):
                    continue
                fixed_name = KNOWN_CIRCLE_NAME_FIXES.get(str(item.get("circle_id") or "").strip())
                if fixed_name:
                    item["circle_name"] = fixed_name

            detail["batch_total"] = len(queries)
            detail["batch_circle_summaries"] = summaries
            previews.append({
                "id": row["id"],
                "created_at": row["created_at"],
                "summary": row["summary"],
                "queries": queries,
                "matched": sum(1 for item in summaries if item.get("success")),
            })
            if apply:
                conn.execute(
                    "UPDATE activity_logs SET detail=? WHERE id=?",
                    (_dumps(detail), row["id"]),
                )
                updated += 1
        if apply:
            conn.commit()
        return {"candidates": candidates, "updated": updated, "previews": previews}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入 data/cache.db")
    args = parser.parse_args()
    result = backfill(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
