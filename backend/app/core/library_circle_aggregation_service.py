"""库存社团聚合视图。

这个服务只读 ``library_index_entries`` 常驻索引和本地元数据表，绝不触发
os.walk / 群晖 FileStation fallback。社团视图是显示层聚合，所有返回行都保留
真实 ``library_id + path``，文件实际位置不变。
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_

from ..models.database import (
    CircleCatalog,
    CircleWork,
    LibraryIndexEntry,
    SessionLocal,
    WorkCanonicalLink,
    WorkMetadata,
)
from .library_manager import get_library_manager

UNKNOWN_CIRCLE_ID = "__unknown__"
UNKNOWN_CIRCLE_NAME = "未识别社团"
_RJ_RE = re.compile(r"RJ\d{4,12}", re.IGNORECASE)


@dataclass(slots=True)
class _CircleIdentity:
    key: str
    circle_id: str
    circle_name: str
    sort_key: str


def _normalize_rjcode(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.isdigit():
        text = f"RJ{text}"
    match = _RJ_RE.search(text)
    return match.group(0).upper() if match else ""


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _top_category(relative_path: Any) -> str:
    normalized = _normalize_path(relative_path)
    if not normalized:
        return ""
    return normalized.split("/", 1)[0]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _encode_circle_key(circle_id: str, circle_name: str) -> str:
    payload = json.dumps(
        {"id": str(circle_id or ""), "name": str(circle_name or "")},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_circle_key(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    try:
        padded = text + ("=" * (-len(text) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if isinstance(payload, dict):
            return str(payload.get("id") or ""), str(payload.get("name") or "")
    except Exception:
        return text, ""
    return text, ""


class LibraryCircleAggregationService:
    """跨库存按社团聚合展示 RJ 作品。"""

    def list_circle_groups(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> dict[str, Any]:
        rows = self._load_index_work_rows()
        identities = self._load_circle_identities({row["rjcode"] for row in rows})
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            identity = identities.get(row["rjcode"]) or self._unknown_identity()
            group = groups.setdefault(
                identity.key,
                {
                    "circle_key": identity.key,
                    "circle_id": identity.circle_id,
                    "circle_name": identity.circle_name,
                    "_sort_key": identity.sort_key,
                    "_rjcodes": set(),
                    "_paths_by_rj": {},
                    "_categories": set(),
                    "folder_count": 0,
                    "total_size": 0,
                },
            )
            rjcode = row["rjcode"]
            group["_rjcodes"].add(rjcode)
            group["_paths_by_rj"].setdefault(rjcode, set()).add((row["library_id"], row["relative_path"]))
            if row["top_category"]:
                group["_categories"].add(row["top_category"])
            group["folder_count"] += 1
            group["total_size"] += row["size"]

        items = []
        keyword_norm = str(keyword or "").strip().lower()
        for group in groups.values():
            conflict_count = sum(1 for paths in group["_paths_by_rj"].values() if len(paths) > 1)
            item = {
                "circle_key": group["circle_key"],
                "circle_id": group["circle_id"],
                "circle_name": group["circle_name"],
                "work_count": len(group["_rjcodes"]),
                "folder_count": int(group["folder_count"] or 0),
                "conflict_count": conflict_count,
                "total_size": int(group["total_size"] or 0),
                "categories": sorted(group["_categories"], key=str.casefold),
            }
            if keyword_norm:
                haystack = " ".join([
                    item["circle_id"],
                    item["circle_name"],
                    " ".join(sorted(group["_rjcodes"])),
                    " ".join(item["categories"]),
                ]).lower()
                if keyword_norm not in haystack:
                    continue
            items.append(item)

        reverse = str(sort_order or "asc").lower() == "desc"
        sort_key_name = str(sort_by or "name").lower()
        if sort_key_name == "work_count":
            items.sort(key=lambda item: (item["work_count"], item["circle_name"].casefold()), reverse=reverse)
        elif sort_key_name == "conflict_count":
            items.sort(key=lambda item: (item["conflict_count"], item["circle_name"].casefold()), reverse=reverse)
        elif sort_key_name in {"size", "total_size"}:
            items.sort(key=lambda item: (item["total_size"], item["circle_name"].casefold()), reverse=reverse)
        else:
            items.sort(key=lambda item: item["circle_name"].casefold(), reverse=reverse)
        return self._paginate(items, page=page, page_size=page_size, extra={"items": items})

    def list_circle_works(
        self,
        circle_key: str,
        *,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
    ) -> dict[str, Any]:
        requested_id, requested_name = _decode_circle_key(circle_key)
        rows = self._load_index_work_rows()
        identities = self._load_circle_identities({row["rjcode"] for row in rows})
        matched: list[dict[str, Any]] = []
        identity_for_response: Optional[_CircleIdentity] = None
        for row in rows:
            identity = identities.get(row["rjcode"]) or self._unknown_identity()
            if identity.key != circle_key and identity.circle_id != requested_id:
                continue
            if requested_name and identity.circle_name != requested_name:
                continue
            identity_for_response = identity
            matched.append(row)
        if identity_for_response is None and requested_id == UNKNOWN_CIRCLE_ID:
            identity_for_response = self._unknown_identity()
        if identity_for_response is None:
            identity_for_response = _CircleIdentity(
                key=circle_key,
                circle_id=requested_id,
                circle_name=requested_name or requested_id or UNKNOWN_CIRCLE_NAME,
                sort_key=(requested_name or requested_id or UNKNOWN_CIRCLE_NAME).casefold(),
            )

        works = self._build_work_items(matched)
        keyword_norm = str(keyword or "").strip().lower()
        if keyword_norm:
            works = [
                item for item in works
                if keyword_norm in " ".join([
                    item["rjcode"],
                    item.get("title") or "",
                    item.get("primary_path") or "",
                    " ".join(item.get("categories") or []),
                ]).lower()
            ]
        works.sort(key=lambda item: (
            str(item.get("primary_category") or "").casefold(),
            item["rjcode"],
        ))
        payload = self._paginate(works, page=page, page_size=page_size, extra={"items": works})
        payload.update({
            "circle_key": identity_for_response.key,
            "circle_id": identity_for_response.circle_id,
            "circle_name": identity_for_response.circle_name,
        })
        return payload

    def _load_index_work_rows(self) -> list[dict[str, Any]]:
        manager = get_library_manager()
        active_libraries = manager._active_libraries()
        library_by_id = {library.id: library for library in active_libraries}
        active_ids = list(library_by_id.keys())
        if not active_ids:
            return []

        rows: list[dict[str, Any]] = []
        db = SessionLocal()
        try:
            query = (
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.library_id.in_(active_ids),
                    LibraryIndexEntry.entry_type == "dir",
                    LibraryIndexEntry.rjcode.isnot(None),
                    LibraryIndexEntry.rjcode != "",
                )
                .order_by(
                    LibraryIndexEntry.library_id.asc(),
                    LibraryIndexEntry.rjcode.asc(),
                    LibraryIndexEntry.depth.asc(),
                    LibraryIndexEntry.relative_path.asc(),
                )
            )
            seen: set[tuple[str, str, str]] = set()
            for entry in query.all():
                rjcode = _normalize_rjcode(entry.rjcode)
                if not rjcode:
                    continue
                library = library_by_id.get(entry.library_id)
                if not library:
                    continue
                relative_path = str(entry.relative_path or "")
                key = (str(entry.library_id or ""), relative_path, rjcode)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "rjcode": rjcode,
                    "library_id": entry.library_id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "path": entry.absolute_path,
                    "relative_path": relative_path,
                    "name": entry.name,
                    "top_category": _top_category(relative_path),
                    "size": _safe_int(entry.size),
                    "file_count": _safe_int(entry.file_count),
                    "modified_time": _safe_int(entry.mtime) or None,
                })
        finally:
            db.close()
        return rows

    def _load_circle_identities(self, rjcodes: Iterable[str]) -> dict[str, _CircleIdentity]:
        normalized = sorted({_normalize_rjcode(code) for code in rjcodes if _normalize_rjcode(code)})
        if not normalized:
            return {}
        result: dict[str, _CircleIdentity] = {}
        db = SessionLocal()
        try:
            link_rows = (
                db.query(WorkCanonicalLink.canonical_rjcode, WorkCanonicalLink.linked_rjcode)
                .filter(
                    or_(
                        WorkCanonicalLink.linked_rjcode.in_(normalized),
                        WorkCanonicalLink.canonical_rjcode.in_(normalized),
                    )
                )
                .all()
            )
            alias_to_canonical: dict[str, str] = {}
            for row in link_rows:
                canonical = _normalize_rjcode(row.canonical_rjcode)
                linked = _normalize_rjcode(row.linked_rjcode)
                if canonical:
                    alias_to_canonical[canonical] = canonical
                if linked and canonical:
                    alias_to_canonical[linked] = canonical
            canonical_candidates = sorted({
                alias_to_canonical.get(code, code)
                for code in normalized
                if alias_to_canonical.get(code, code)
            })
            circle_rows = (
                db.query(
                    CircleWork.canonical_rjcode,
                    CircleWork.display_rjcode,
                    CircleWork.linked_rjcodes,
                    CircleWork.circle_id,
                    CircleWork.maker_name,
                    CircleCatalog.circle_name,
                )
                .outerjoin(CircleCatalog, CircleCatalog.circle_id == CircleWork.circle_id)
                .filter(
                    or_(
                        CircleWork.canonical_rjcode.in_(canonical_candidates),
                        CircleWork.display_rjcode.in_(normalized),
                    )
                )
                .all()
            )
            for row in circle_rows:
                codes = {
                    _normalize_rjcode(row.canonical_rjcode),
                    _normalize_rjcode(row.display_rjcode),
                }
                for linked in row.linked_rjcodes or []:
                    codes.add(_normalize_rjcode(linked))
                canonical = _normalize_rjcode(row.canonical_rjcode)
                for alias, mapped in alias_to_canonical.items():
                    if mapped == canonical:
                        codes.add(alias)
                identity = self._identity_from_values(row.circle_id, row.circle_name or row.maker_name)
                for code in codes:
                    if code and code in normalized and code not in result:
                        result[code] = identity

            missing = [code for code in normalized if code not in result]
            if missing:
                metadata_rows = (
                    db.query(WorkMetadata.rjcode, WorkMetadata.maker_name)
                    .filter(WorkMetadata.rjcode.in_(missing))
                    .all()
                )
                for row in metadata_rows:
                    rjcode = _normalize_rjcode(row.rjcode)
                    maker_name = str(row.maker_name or "").strip()
                    if rjcode and maker_name:
                        result[rjcode] = self._identity_from_values("", maker_name)
        finally:
            db.close()
        return result

    def _build_work_items(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        titles = self._load_work_titles({row["rjcode"] for row in rows})
        for row in rows:
            rjcode = row["rjcode"]
            item = grouped.setdefault(
                rjcode,
                {
                    "rjcode": rjcode,
                    "title": titles.get(rjcode, ""),
                    "folder_count": 0,
                    "total_size": 0,
                    "file_count": 0,
                    "categories": set(),
                    "locations": [],
                },
            )
            if row["top_category"]:
                item["categories"].add(row["top_category"])
            item["folder_count"] += 1
            item["total_size"] += row["size"]
            item["file_count"] += row["file_count"]
            item["locations"].append({
                "library_id": row["library_id"],
                "library_name": row["library_name"],
                "library_type": row["library_type"],
                "path": row["path"],
                "relative_path": row["relative_path"],
                "top_category": row["top_category"],
                "size": row["size"],
                "file_count": row["file_count"],
                "modified_time": row["modified_time"],
                "name": row["name"],
            })

        items = []
        for item in grouped.values():
            item["locations"].sort(key=lambda loc: (
                str(loc.get("top_category") or "").casefold(),
                str(loc.get("library_name") or "").casefold(),
                str(loc.get("relative_path") or "").casefold(),
            ))
            categories = sorted(item.pop("categories"), key=str.casefold)
            item["categories"] = categories
            item["primary_category"] = categories[0] if categories else ""
            item["primary_path"] = item["locations"][0]["path"] if item["locations"] else ""
            item["primary_library_id"] = item["locations"][0]["library_id"] if item["locations"] else ""
            item["conflict"] = len(item["locations"]) > 1
            items.append(item)
        return items

    def _load_work_titles(self, rjcodes: Iterable[str]) -> dict[str, str]:
        normalized = sorted({_normalize_rjcode(code) for code in rjcodes if _normalize_rjcode(code)})
        if not normalized:
            return {}
        titles: dict[str, str] = {}
        db = SessionLocal()
        try:
            rows = (
                db.query(CircleWork.canonical_rjcode, CircleWork.display_rjcode, CircleWork.title)
                .filter(
                    or_(
                        CircleWork.canonical_rjcode.in_(normalized),
                        CircleWork.display_rjcode.in_(normalized),
                    )
                )
                .all()
            )
            for row in rows:
                title = str(row.title or "").strip()
                if not title:
                    continue
                for code in [_normalize_rjcode(row.canonical_rjcode), _normalize_rjcode(row.display_rjcode)]:
                    if code and code not in titles:
                        titles[code] = title
            missing = [code for code in normalized if code not in titles]
            if missing:
                metadata_rows = (
                    db.query(WorkMetadata.rjcode, WorkMetadata.work_name)
                    .filter(WorkMetadata.rjcode.in_(missing))
                    .all()
                )
                for row in metadata_rows:
                    rjcode = _normalize_rjcode(row.rjcode)
                    title = str(row.work_name or "").strip()
                    if rjcode and title:
                        titles[rjcode] = title
        finally:
            db.close()
        return titles

    def _identity_from_values(self, circle_id: Any, circle_name: Any) -> _CircleIdentity:
        name = str(circle_name or "").strip() or UNKNOWN_CIRCLE_NAME
        raw_id = str(circle_id or "").strip()
        identity_id = raw_id or f"name:{name.casefold()}"
        return _CircleIdentity(
            key=_encode_circle_key(identity_id, name),
            circle_id=identity_id,
            circle_name=name,
            sort_key=name.casefold(),
        )

    def _unknown_identity(self) -> _CircleIdentity:
        return _CircleIdentity(
            key=_encode_circle_key(UNKNOWN_CIRCLE_ID, UNKNOWN_CIRCLE_NAME),
            circle_id=UNKNOWN_CIRCLE_ID,
            circle_name=UNKNOWN_CIRCLE_NAME,
            sort_key=UNKNOWN_CIRCLE_NAME,
        )

    @staticmethod
    def _paginate(items: list[dict[str, Any]], *, page: int, page_size: int, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        normalized_page = max(1, int(page or 1))
        normalized_page_size = max(1, min(int(page_size or 50), 200))
        total = len(items)
        start = (normalized_page - 1) * normalized_page_size
        end = start + normalized_page_size
        payload = {
            "items": items[start:end],
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "has_more": end < total,
        }
        if extra:
            payload.update({k: v for k, v in extra.items() if k != "items"})
        return payload


_default_service: Optional[LibraryCircleAggregationService] = None


def get_library_circle_aggregation_service() -> LibraryCircleAggregationService:
    global _default_service
    if _default_service is None:
        _default_service = LibraryCircleAggregationService()
    return _default_service
