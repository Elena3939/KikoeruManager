from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.circle_completion_service import get_circle_completion_service
from app.models.database import get_db_path


STRONG_AUDIO_MARKERS = (
    "sou",
    "audio",
    "voice",
    "asmr",
    "音声",
    "ボイス",
    "囁き",
    "ささやき",
    "耳かき",
    "耳舐め",
    "舐耳",
    "バイノーラル",
    "フォーリー",
    "foley",
    "wav",
    "ku100",
    "双声道立体声",
    "人头麦",
    "舔耳",
    "低语",
    "拟声音效",
    "拟真音效",
    "耳语",
    "耳边",
)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))


def _normalize_rj(service, value: Any) -> str:
    return service.normalize_rjcode(value)


def _rj_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    return (int(digits) if digits else 10**12, text)


def _has_strong_audio_signal(metadata_rows: list[dict[str, Any]], title: str = "") -> bool:
    pieces: list[str] = [title]
    for row in metadata_rows:
        pieces.append(str(row.get("work_name") or ""))
        pieces.extend(str(item or "") for item in _json_list(row.get("tags")))
        pieces.extend(str(item or "") for item in _json_list(row.get("cvs")))
    text = " ".join(pieces).lower()
    return any(marker.lower() in text for marker in STRONG_AUDIO_MARKERS)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if _rj_sort_key(right_root) < _rj_sort_key(left_root):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


async def classify_related(service, related_codes: list[str], metadata_by_rj: dict[str, dict[str, Any]]) -> bool:
    for code in related_codes:
        metadata = metadata_by_rj.get(code) or {}
        try:
            result = await service._classify_asmr_work_candidate(code, metadata)
        except Exception:
            result = None
        if result is True:
            return True
    return False


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--circle-id", default="", help="只清洗指定 circle_id；为空则清洗全部社团")
    args = parser.parse_args()

    import sqlite3

    service = get_circle_completion_service()
    db_path = Path(get_db_path())
    backup_path = db_path.with_name(f"{db_path.name}.codex-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    if args.apply:
        shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        metadata_by_rj = {
            str(row["rjcode"] or "").strip().upper(): dict(row)
            for row in conn.execute("select * from work_metadata")
        }

        links = [dict(row) for row in conn.execute("select canonical_rjcode, linked_rjcode, link_type, lang from work_canonical_links")]
        uf = UnionFind()
        link_meta: dict[str, dict[str, str]] = {}
        for row in links:
            canonical = _normalize_rj(service, row.get("canonical_rjcode"))
            linked = _normalize_rj(service, row.get("linked_rjcode"))
            if not canonical or not linked:
                continue
            uf.union(canonical, linked)
            current = link_meta.get(linked)
            next_meta = {
                "link_type": str(row.get("link_type") or ""),
                "lang": service._normalize_lang_code(row.get("lang")),
            }
            if current is None or current.get("link_type") in {"", "self", "unknown"}:
                link_meta[linked] = next_meta

        component_members: dict[str, set[str]] = defaultdict(set)
        for code in set([*uf.parent.keys(), *metadata_by_rj.keys()]):
            normalized = _normalize_rj(service, code)
            if normalized:
                component_members[uf.find(normalized)].add(normalized)

        def select_component_canonical(codes: set[str]) -> str:
            originals = [code for code in codes if (link_meta.get(code) or {}).get("link_type") == "original"]
            if originals:
                return sorted(originals, key=_rj_sort_key)[0]
            jpn = [code for code in codes if (link_meta.get(code) or {}).get("lang") in {"JPN", "JA", "JP"}]
            if jpn:
                return sorted(jpn, key=_rj_sort_key)[0]
            return sorted(codes, key=_rj_sort_key)[0]

        component_canonical: dict[str, str] = {
            root: select_component_canonical(codes)
            for root, codes in component_members.items()
            if codes
        }

        if args.circle_id:
            rows = [
                dict(row)
                for row in conn.execute(
                    "select * from circle_works where circle_id=?",
                    (str(args.circle_id).strip(),),
                )
            ]
        else:
            rows = [dict(row) for row in conn.execute("select * from circle_works")]

        def row_related(row: dict[str, Any]) -> list[str]:
            values = [
                row.get("canonical_rjcode"),
                row.get("display_rjcode"),
                *_json_list(row.get("linked_rjcodes")),
            ]
            result: list[str] = []
            for value in values:
                code = _normalize_rj(service, value)
                if code and code not in result:
                    result.append(code)
            return result

        rows_to_delete: set[str] = set()
        merge_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for row in rows:
            related = row_related(row)
            if not related:
                rows_to_delete.add(row["id"])
                continue
            roots = [uf.find(code) for code in related]
            group_root = sorted(roots, key=lambda root: _rj_sort_key(component_canonical.get(root) or root))[0]
            canonical = component_canonical.get(group_root) or select_component_canonical(set(related))
            merge_groups[(str(row.get("circle_id") or ""), canonical)].append(row)

        merged_count = 0
        updated_count = 0
        for (circle_id, canonical), group_rows in merge_groups.items():
            if not circle_id or not canonical:
                continue
            if len(group_rows) <= 1 and _normalize_rj(service, group_rows[0].get("canonical_rjcode")) == canonical:
                continue
            all_related: list[str] = []
            for row in group_rows:
                root = uf.find(_normalize_rj(service, row.get("canonical_rjcode")) or canonical)
                for code in sorted(component_members.get(root) or set(), key=_rj_sort_key):
                    if code not in all_related:
                        all_related.append(code)
                for code in row_related(row):
                    if code not in all_related:
                        all_related.append(code)

            lang_priority = {"CHI_HANS": 0, "CHI_HANT": 1, "JPN": 2}
            display_code = sorted(
                all_related,
                key=lambda code: (
                    lang_priority.get((link_meta.get(code) or {}).get("lang"), 9),
                    _rj_sort_key(code),
                ),
            )[0]
            keeper = sorted(
                group_rows,
                key=lambda row: (
                    0 if _normalize_rj(service, row.get("display_rjcode")) == display_code else 1,
                    0 if _normalize_rj(service, row.get("canonical_rjcode")) == canonical else 1,
                    -int(bool(row.get("has_asmr_one"))),
                    -int(bool(row.get("has_kikoeru"))),
                    str(row.get("updated_at") or ""),
                ),
            )[0]
            source_mask = ",".join(sorted({
                item
                for row in group_rows
                for item in str(row.get("source_mask") or "").split(",")
                if item
            }))
            found = sorted({
                _normalize_rj(service, code)
                for row in group_rows
                for code in _json_list(row.get("kikoeru_found_rjcodes"))
                if _normalize_rj(service, code)
            }, key=_rj_sort_key)
            subtitles = sorted({
                _normalize_rj(service, code)
                for row in group_rows
                for code in _json_list(row.get("kikoeru_subtitle_rjcodes"))
                if _normalize_rj(service, code)
            }, key=_rj_sort_key)
            title_source = next(
                (row for row in group_rows if _normalize_rj(service, row.get("display_rjcode")) == display_code),
                keeper,
            )
            image_source = title_source if title_source.get("image_url") else keeper
            duplicate_ids = [row["id"] for row in group_rows if row["id"] != keeper["id"]]
            rows_to_delete.update(duplicate_ids)
            merged_count += len(duplicate_ids)
            updated_count += 1
            if args.apply:
                conn.execute(
                    """
                    update circle_works
                    set canonical_rjcode=?, display_rjcode=?, title=?, image_url=?, linked_rjcodes=?,
                        source_mask=?, has_kikoeru=?, kikoeru_found_rjcodes=?, kikoeru_subtitle_rjcodes=?,
                        has_asmr_one=?, asmr_available_rjcode=?, kikoeru_work_id=?, has_dlsite=1,
                        price_text=coalesce(?, price_text), is_bonus_work=?, has_bonus=?, updated_at=?
                    where id=?
                    """,
                    (
                        canonical,
                        display_code,
                        title_source.get("title") or keeper.get("title") or "",
                        image_source.get("image_url") or "",
                        _json_dumps(all_related),
                        source_mask,
                        1 if found else 0,
                        _json_dumps(found),
                        _json_dumps(subtitles),
                        1 if any(row.get("has_asmr_one") for row in group_rows) else 0,
                        next((row.get("asmr_available_rjcode") for row in group_rows if row.get("asmr_available_rjcode")), None),
                        next((row.get("kikoeru_work_id") for row in group_rows if row.get("kikoeru_work_id")), None),
                        next((row.get("price_text") for row in group_rows if row.get("price_text")), None),
                        1 if any(row.get("is_bonus_work") for row in group_rows) else 0,
                        1 if any(row.get("has_bonus") for row in group_rows) else 0,
                        datetime.now().isoformat(sep=" "),
                        keeper["id"],
                    ),
                )

        kept_rows = [row for row in rows if row["id"] not in rows_to_delete]
        suspect_rows = []
        for row in kept_rows:
            related = row_related(row)
            meta_rows = [metadata_by_rj.get(code) for code in related if metadata_by_rj.get(code)]
            if not _has_strong_audio_signal(meta_rows, str(row.get("title") or "")):
                suspect_rows.append((row, related))

        non_audio_ids: set[str] = set()
        for index, (row, related) in enumerate(suspect_rows, start=1):
            if index % 50 == 0:
                print(f"[清洗] 重新分类 {index}/{len(suspect_rows)}")
            if not await classify_related(service, related, metadata_by_rj):
                non_audio_ids.add(row["id"])

        rows_to_delete.update(non_audio_ids)
        if args.apply and rows_to_delete:
            conn.executemany(
                "delete from circle_works where id=?",
                [(row_id,) for row_id in sorted(rows_to_delete)],
            )
            # 删除空社团保守不做，保留索引入口和历史刷新时间。
            conn.commit()
        elif args.apply:
            conn.commit()

        print(json.dumps({
            "apply": bool(args.apply),
            "backup_path": str(backup_path) if args.apply else "",
            "merge_groups": sum(1 for group in merge_groups.values() if len(group) > 1),
            "merged_duplicate_rows": merged_count,
            "updated_rows": updated_count,
            "suspect_reclassified_rows": len(suspect_rows),
            "non_audio_deleted_rows": len(non_audio_ids),
            "total_deleted_rows": len(rows_to_delete),
        }, ensure_ascii=False, indent=2))
    finally:
        conn.close()
        await service.dlsite_service.close()


if __name__ == "__main__":
    asyncio.run(main())
