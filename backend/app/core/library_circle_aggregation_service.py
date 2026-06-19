"""库存社团聚合视图。

这个服务只读 ``library_index_entries`` 常驻索引和本地元数据表，绝不触发
os.walk / 群晖 FileStation fallback。社团视图是显示层聚合，所有返回行都保留
真实 ``library_id + path``，文件实际位置不变。
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import quote, unquote

from sqlalchemy import or_

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
_CIRCLE_ROOT_PATH = "circle:/"
_SNAPSHOT_TTL_SECONDS = 300.0


@dataclass(slots=True)
class _CircleIdentity:
    key: str
    circle_id: str
    circle_name: str
    sort_key: str


@dataclass(slots=True)
class _CircleVirtualPath:
    type: str
    group_key: str = ""
    work_key: str = ""
    location_index: int = 0
    item_relative_path: str = ""


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


def _infer_circle_name_from_bracketed_folder(value: Any, rjcode: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized_rjcode = _normalize_rjcode(rjcode)
    matches = re.findall(r"\[([^\[\]]+)\]", text)
    if len(matches) < 2:
        return ""
    for index in range(len(matches) - 1):
        if _normalize_rjcode(matches[index + 1]) == normalized_rjcode:
            return str(matches[index] or "").strip()
    return ""


def _infer_circle_name_from_any_bracketed_work_folder(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    matches = re.findall(r"\[([^\[\]]+)\]", text)
    if len(matches) < 2:
        return ""
    for index in range(len(matches) - 1):
        if _normalize_rjcode(matches[index + 1]):
            return str(matches[index] or "").strip()
    return ""


def _infer_circle_name_from_index_path(relative_path: Any, rjcode: Any, folder_name: Any = "") -> str:
    name_circle = _infer_circle_name_from_bracketed_folder(folder_name, rjcode)
    if name_circle:
        return name_circle

    parts = [part.strip() for part in _normalize_path(relative_path).split("/") if part.strip()]
    if len(parts) < 2:
        return ""

    normalized_rjcode = _normalize_rjcode(rjcode)
    for index, part in enumerate(parts):
        matched_rjcode = _normalize_rjcode(part)
        if not matched_rjcode:
            continue
        if normalized_rjcode and matched_rjcode != normalized_rjcode:
            continue
        path_circle = _infer_circle_name_from_bracketed_folder(part, normalized_rjcode)
        if path_circle:
            return path_circle
        for parent_part in reversed(parts[:index]):
            parent_circle = _infer_circle_name_from_any_bracketed_work_folder(parent_part)
            if parent_circle:
                return parent_circle
        return ""

    return ""


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


def _encode_virtual_segment(value: Any) -> str:
    return quote(str(value or "").strip(), safe="")


def _decode_virtual_segment(value: Any) -> str:
    return unquote(str(value or "").strip())


def _circle_group_path(group_key: str) -> str:
    return f"{_CIRCLE_ROOT_PATH}group/{_encode_virtual_segment(group_key or 'unknown')}"


def _circle_work_path(group_key: str, work_key: str) -> str:
    return f"{_circle_group_path(group_key)}/work/{_encode_virtual_segment(work_key or 'unknown')}"


def _circle_conflict_path(group_key: str, work_key: str, location: dict[str, Any], index: int) -> str:
    library_id = _encode_virtual_segment(location.get("library_id") or "unknown")
    relative_path = _encode_virtual_segment(location.get("relative_path") or location.get("path") or "unknown")
    return f"{_circle_work_path(group_key, work_key)}/path/{int(index or 0)}-{library_id}-{relative_path}"


def _circle_child_path(base_path: str, relative_path: Any) -> str:
    normalized = _normalize_path(relative_path)
    return f"{base_path}/item/{_encode_virtual_segment(normalized)}" if normalized else base_path


def _decode_circle_virtual_path(path: Any) -> _CircleVirtualPath:
    normalized = str(path or "").strip()
    if not normalized or normalized in {"circle:", _CIRCLE_ROOT_PATH}:
        return _CircleVirtualPath(type="root")

    parts = normalized.replace("circle:/", "", 1).split("/")
    parts = [part for part in parts if part]
    if not parts or parts[0] != "group":
        return _CircleVirtualPath(type="unknown")

    group_key = _decode_virtual_segment(parts[1] if len(parts) > 1 else "")
    if len(parts) < 3 or parts[2] != "work":
        return _CircleVirtualPath(type="group", group_key=group_key)

    work_key = _decode_virtual_segment(parts[3] if len(parts) > 3 else "")
    if len(parts) < 5:
        return _CircleVirtualPath(type="work", group_key=group_key, work_key=work_key)

    if parts[4] == "item":
        return _CircleVirtualPath(
            type="item",
            group_key=group_key,
            work_key=work_key,
            item_relative_path=_decode_virtual_segment(parts[5] if len(parts) > 5 else ""),
        )

    if parts[4] == "path":
        raw_index = str(parts[5] if len(parts) > 5 else "0").split("-", 1)[0]
        try:
            location_index = int(raw_index)
        except (TypeError, ValueError):
            location_index = 0
        if len(parts) > 6 and parts[6] == "item":
            return _CircleVirtualPath(
                type="location-item",
                group_key=group_key,
                work_key=work_key,
                location_index=max(0, location_index),
                item_relative_path=_decode_virtual_segment(parts[7] if len(parts) > 7 else ""),
            )
        return _CircleVirtualPath(
            type="location",
            group_key=group_key,
            work_key=work_key,
            location_index=max(0, location_index),
        )

    return _CircleVirtualPath(type="work", group_key=group_key, work_key=work_key)


def _location_folder_name(location: dict[str, Any]) -> str:
    direct_name = str(location.get("name") or "").strip()
    if direct_name:
        return direct_name
    for key in ("relative_path", "path"):
        normalized = _normalize_path(location.get(key))
        if normalized:
            return normalized.split("/")[-1] or normalized
    return ""


def _join_real_path(base_path: Any, relative_path: Any) -> str:
    base = str(base_path or "").strip().rstrip("\\/")
    relative = _normalize_path(relative_path)
    if not relative:
        return str(base_path or "").strip()
    separator = "\\" if "\\" in base else "/"
    return f"{base}{separator}{relative.replace('/', separator)}"


def _relative_path_from_base(base_path: Any, real_path: Any, fallback: Any = "") -> str:
    normalized_base = str(base_path or "").replace("\\", "/").rstrip("/")
    normalized_real = str(real_path or "").replace("\\", "/").rstrip("/")
    if normalized_base and normalized_real.casefold().startswith(f"{normalized_base}/".casefold()):
        return normalized_real[len(normalized_base) + 1 :]
    return _normalize_path(fallback)


def _parent_relative_path(relative_path: Any) -> str:
    parts = _normalize_path(relative_path).split("/")
    if not parts or parts == [""]:
        return ""
    parts.pop()
    return "/".join(part for part in parts if part)


def _normalize_sort_by(sort_by: Any) -> str:
    value = str(sort_by or "").strip()
    if value == "modified_time":
        return "time"
    return value if value in {"name", "size", "time", "work_count"} else "size"


class LibraryCircleAggregationService:
    """跨库存按社团聚合展示 RJ 作品。"""

    def __init__(self) -> None:
        self._snapshot_cache: dict[str, Any] = {}
        self._snapshot_lock = threading.Lock()

    async def browse_circle_path(
        self,
        *,
        current_path: str = _CIRCLE_ROOT_PATH,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
        sort_by: str = "name",
        sort_order: str = "asc",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        decoded = _decode_circle_virtual_path(current_path)
        if decoded.type == "unknown":
            return self._empty_browser_payload(current_path=_CIRCLE_ROOT_PATH, page=page, page_size=page_size)

        snapshot = self._get_snapshot(force_refresh=force_refresh)
        if decoded.type == "root":
            groups = self._filter_groups(snapshot["groups"], keyword)
            groups = self._sort_groups(groups, sort_by=sort_by, sort_order=sort_order)
            group_data = self._paginate(groups, page=page, page_size=page_size)
            rows = [self._build_group_row(group) for group in group_data.get("items") or []]
            return self._browser_payload(
                files=rows,
                total=group_data.get("total", len(rows)),
                page=group_data.get("page", page),
                page_size=group_data.get("page_size", page_size),
                current_path=_CIRCLE_ROOT_PATH,
                parent_path="",
                circle_context={"type": "root"},
                circle_groups=group_data.get("items") or [],
                circle_summary=snapshot.get("summary") or {},
            )

        group = snapshot["groups_by_key"].get(decoded.group_key)
        if not group:
            return self._empty_browser_payload(
                current_path=_CIRCLE_ROOT_PATH,
                page=page,
                page_size=page_size,
                circle_summary=snapshot.get("summary") or {},
            )

        if decoded.type == "group":
            works = self._filter_works(self._get_group_works(snapshot, decoded.group_key), keyword)
            works = self._sort_works(works, sort_by=sort_by, sort_order=sort_order)
            work_data = self._paginate(works, page=page, page_size=page_size)
            works = work_data.get("items") or []
            rows = [self._build_work_row(group, work) for work in works]
            return self._browser_payload(
                files=rows,
                total=work_data.get("total", len(rows)),
                page=work_data.get("page", page),
                page_size=work_data.get("page_size", page_size),
                current_path=_circle_group_path(decoded.group_key),
                parent_path=_CIRCLE_ROOT_PATH,
                circle_context={"type": "group", "group": group},
                circle_group=group,
                circle_works=works,
                circle_summary=snapshot.get("summary") or {},
            )

        work = self._find_group_work(snapshot, decoded.group_key, decoded.work_key)
        if not work:
            return self._empty_browser_payload(
                current_path=_circle_group_path(decoded.group_key),
                parent_path=_CIRCLE_ROOT_PATH,
                page=page,
                page_size=page_size,
                circle_group=group,
                circle_summary=snapshot.get("summary") or {},
            )

        if decoded.type == "work" and work.get("conflict"):
            locations = list(work.get("locations") or [])
            rows = [
                self._build_conflict_location_row(group, work, location, index)
                for index, location in enumerate(locations)
            ]
            return self._browser_payload(
                files=rows,
                total=len(rows),
                page=page,
                page_size=page_size,
                current_path=_circle_work_path(decoded.group_key, decoded.work_key),
                parent_path=_circle_group_path(decoded.group_key),
                circle_context={"type": "work", "group": group, "work": work},
                circle_group=group,
                circle_work=work,
                circle_works=[work],
                circle_summary=snapshot.get("summary") or {},
            )

        if decoded.type in {"work", "item"}:
            location = (work.get("locations") or [None])[0]
            if not location:
                return self._empty_browser_payload(
                    current_path=_circle_work_path(decoded.group_key, decoded.work_key),
                    parent_path=_circle_group_path(decoded.group_key),
                    page=page,
                    page_size=page_size,
                    circle_group=group,
                    circle_work=work,
                    circle_works=[work],
                    circle_summary=snapshot.get("summary") or {},
                )
            return await self._browse_location_children(
                group=group,
                work=work,
                location=location,
                location_index=0,
                relative_path=decoded.item_relative_path if decoded.type == "item" else "",
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                conflict_location=False,
                circle_summary=snapshot.get("summary") or {},
            )

        if decoded.type in {"location", "location-item"}:
            locations = list(work.get("locations") or [])
            location_index = max(0, min(int(decoded.location_index or 0), len(locations) - 1)) if locations else 0
            location = locations[location_index] if locations else None
            if not location:
                return self._empty_browser_payload(
                    current_path=_circle_work_path(decoded.group_key, decoded.work_key),
                    parent_path=_circle_group_path(decoded.group_key),
                    page=page,
                    page_size=page_size,
                    circle_group=group,
                    circle_work=work,
                    circle_works=[work],
                    circle_summary=snapshot.get("summary") or {},
                )
            return await self._browse_location_children(
                group=group,
                work=work,
                location=location,
                location_index=location_index,
                relative_path=decoded.item_relative_path if decoded.type == "location-item" else "",
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                conflict_location=True,
                circle_summary=snapshot.get("summary") or {},
            )

        return self._empty_browser_payload(
            current_path=_CIRCLE_ROOT_PATH,
            page=page,
            page_size=page_size,
            circle_summary=snapshot.get("summary") or {},
        )

    def should_thread_browse(self, current_path: str = _CIRCLE_ROOT_PATH) -> bool:
        return _decode_circle_virtual_path(current_path).type in {"unknown", "root", "group"}

    def browse_circle_listing(
        self,
        *,
        current_path: str = _CIRCLE_ROOT_PATH,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
        sort_by: str = "name",
        sort_order: str = "asc",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        decoded = _decode_circle_virtual_path(current_path)
        if decoded.type == "unknown":
            return self._empty_browser_payload(current_path=_CIRCLE_ROOT_PATH, page=page, page_size=page_size)

        snapshot = self._get_snapshot(force_refresh=force_refresh)
        if decoded.type == "root":
            groups = self._filter_groups(snapshot["groups"], keyword)
            groups = self._sort_groups(groups, sort_by=sort_by, sort_order=sort_order)
            group_data = self._paginate(groups, page=page, page_size=page_size)
            rows = [self._build_group_row(group) for group in group_data.get("items") or []]
            return self._browser_payload(
                files=rows,
                total=group_data.get("total", len(rows)),
                page=group_data.get("page", page),
                page_size=group_data.get("page_size", page_size),
                current_path=_CIRCLE_ROOT_PATH,
                parent_path="",
                circle_context={"type": "root"},
                circle_groups=group_data.get("items") or [],
                circle_summary=snapshot.get("summary") or {},
            )

        group = snapshot["groups_by_key"].get(decoded.group_key)
        if not group:
            return self._empty_browser_payload(
                current_path=_CIRCLE_ROOT_PATH,
                page=page,
                page_size=page_size,
                circle_summary=snapshot.get("summary") or {},
            )

        works = self._filter_works(self._get_group_works(snapshot, decoded.group_key), keyword)
        works = self._sort_works(works, sort_by=sort_by, sort_order=sort_order)
        work_data = self._paginate(works, page=page, page_size=page_size)
        work_items = work_data.get("items") or []
        rows = [self._build_work_row(group, work) for work in work_items]
        return self._browser_payload(
            files=rows,
            total=work_data.get("total", len(rows)),
            page=work_data.get("page", page),
            page_size=work_data.get("page_size", page_size),
            current_path=_circle_group_path(decoded.group_key),
            parent_path=_CIRCLE_ROOT_PATH,
            circle_context={"type": "group", "group": group},
            circle_group=group,
            circle_works=work_items,
            circle_summary=snapshot.get("summary") or {},
        )

    def _get_snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        cached_payload = self._get_cached_snapshot(now=now, force_refresh=force_refresh)
        if cached_payload is not None:
            return cached_payload

        with self._snapshot_lock:
            now = time.monotonic()
            cached_payload = self._get_cached_snapshot(now=now, force_refresh=force_refresh)
            if cached_payload is not None:
                return cached_payload
            return self._build_snapshot(now=now)

    def _get_cached_snapshot(self, *, now: float, force_refresh: bool = False) -> Optional[dict[str, Any]]:
        if force_refresh or not self._snapshot_cache:
            return None
        if float(self._snapshot_cache.get("expires_at") or 0.0) <= now:
            return None
        return self._snapshot_cache["payload"]

    def _build_snapshot(self, *, now: float) -> dict[str, Any]:
        rows = self._load_index_work_rows()
        library_summary_items = self._load_active_library_summary_items()
        path_identities: dict[int, _CircleIdentity] = {}
        metadata_rjcodes: set[str] = set()
        for index, row in enumerate(rows):
            path_identity = self._identity_from_index_path(row)
            if path_identity:
                path_identities[index] = path_identity
            else:
                metadata_rjcodes.add(row["rjcode"])
        identities = self._load_circle_identities(metadata_rjcodes)
        builders: dict[str, dict[str, Any]] = {}
        rows_by_group: dict[str, list[dict[str, Any]]] = {}
        for index, row in enumerate(rows):
            identity = path_identities.get(index) or identities.get(row["rjcode"]) or self._unknown_identity()
            builder = builders.setdefault(
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
                    "modified_time": None,
                },
            )
            rjcode = row["rjcode"]
            builder["_rjcodes"].add(rjcode)
            builder["_paths_by_rj"].setdefault(rjcode, set()).add((row["library_id"], row["relative_path"]))
            if row["top_category"]:
                builder["_categories"].add(row["top_category"])
            builder["folder_count"] += 1
            builder["total_size"] += row["size"]
            row_modified_time = _safe_int(row.get("modified_time"))
            if row_modified_time and row_modified_time > _safe_int(builder.get("modified_time")):
                builder["modified_time"] = row_modified_time
            rows_by_group.setdefault(identity.key, []).append(row)

        groups: list[dict[str, Any]] = []
        groups_by_key: dict[str, dict[str, Any]] = {}
        for key, builder in builders.items():
            conflict_count = sum(1 for paths in builder["_paths_by_rj"].values() if len(paths) > 1)
            group = {
                "circle_key": builder["circle_key"],
                "circle_id": builder["circle_id"],
                "circle_name": builder["circle_name"],
                "work_count": len(builder["_rjcodes"]),
                "folder_count": int(builder["folder_count"] or 0),
                "conflict_count": conflict_count,
                "total_size": int(builder["total_size"] or 0),
                "modified_time": _safe_int(builder.get("modified_time")) or None,
                "categories": sorted(builder["_categories"], key=str.casefold),
                "rjcodes": sorted(builder["_rjcodes"]),
            }
            groups.append(group)
            groups_by_key[key] = group

        total_size = sum(int(group.get("total_size") or 0) for group in groups)
        matched_libraries_by_id = {
            str(row.get("library_id") or ""): {
                "library_id": str(row.get("library_id") or ""),
                "library_name": str(row.get("library_name") or row.get("library_id") or ""),
                "library_type": str(row.get("library_type") or ""),
            }
            for row in rows
            if str(row.get("library_id") or "")
        }
        matched_libraries = sorted(
            matched_libraries_by_id.values(),
            key=lambda item: (str(item.get("library_type") or ""), str(item.get("library_name") or "").casefold()),
        )
        summary = {
            "group_count": len(groups),
            "work_count": sum(int(group.get("work_count") or 0) for group in groups),
            "folder_count": sum(int(group.get("folder_count") or 0) for group in groups),
            "conflict_count": sum(int(group.get("conflict_count") or 0) for group in groups),
            "total_size": total_size,
            "total_size_bytes": total_size,
            "total_size_gb": round(total_size / (1024**3), 2),
            "library_count": len(library_summary_items),
            "matched_library_count": len(matched_libraries),
            "libraries": library_summary_items,
            "matched_libraries": matched_libraries,
        }
        payload = {
            "groups": groups,
            "groups_by_key": groups_by_key,
            "rows_by_group": rows_by_group,
            "works_by_group": {},
            "summary": summary,
        }
        self._snapshot_cache = {
            "expires_at": now + _SNAPSHOT_TTL_SECONDS,
            "payload": payload,
        }
        return payload

    @staticmethod
    def _filter_groups(groups: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
        keyword_norm = str(keyword or "").strip().lower()
        if not keyword_norm:
            return list(groups)
        return [
            group
            for group in groups
            if keyword_norm in " ".join([
                str(group.get("circle_id") or ""),
                str(group.get("circle_name") or ""),
                " ".join(group.get("rjcodes") or []),
                " ".join(group.get("categories") or []),
            ]).lower()
        ]

    @staticmethod
    def _sort_groups(groups: list[dict[str, Any]], *, sort_by: str, sort_order: str) -> list[dict[str, Any]]:
        reverse = str(sort_order or "asc").lower() == "desc"
        sort_key_name = str(sort_by or "name").lower()
        if sort_key_name == "modified_time":
            sort_key_name = "time"
        items = list(groups)
        if sort_key_name == "work_count":
            items.sort(key=lambda item: (item["work_count"], item["circle_name"].casefold()), reverse=reverse)
        elif sort_key_name == "conflict_count":
            items.sort(key=lambda item: (item["conflict_count"], item["circle_name"].casefold()), reverse=reverse)
        elif sort_key_name in {"size", "total_size"}:
            items.sort(key=lambda item: (item["total_size"], item["circle_name"].casefold()), reverse=reverse)
        elif sort_key_name == "time":
            items.sort(key=lambda item: (_safe_int(item.get("modified_time")), item["circle_name"].casefold()), reverse=reverse)
        else:
            items.sort(key=lambda item: item["circle_name"].casefold(), reverse=reverse)
        return items

    @staticmethod
    def _filter_works(works: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
        keyword_norm = str(keyword or "").strip().lower()
        if not keyword_norm:
            return list(works)
        result = []
        for item in works:
            locations = item.get("locations") or []
            haystack = " ".join([
                str(item.get("rjcode") or ""),
                str(item.get("title") or ""),
                str(item.get("primary_path") or ""),
                " ".join(item.get("categories") or []),
                " ".join(_location_folder_name(location) for location in locations),
            ]).lower()
            if keyword_norm in haystack:
                result.append(item)
        return result

    @staticmethod
    def _sort_works(works: list[dict[str, Any]], *, sort_by: str = "", sort_order: str = "asc") -> list[dict[str, Any]]:
        normalized_sort = _normalize_sort_by(sort_by) if sort_by else ""
        reverse = str(sort_order or "asc").lower() == "desc"
        items = list(works)
        if normalized_sort == "name":
            items.sort(
                key=lambda item: (
                    _location_folder_name((item.get("locations") or [{}])[0]).casefold(),
                    str(item.get("rjcode") or ""),
                ),
                reverse=reverse,
            )
        elif normalized_sort == "size":
            items.sort(
                key=lambda item: (int(item.get("total_size") or 0), str(item.get("rjcode") or "")),
                reverse=reverse,
            )
        elif normalized_sort == "time":
            items.sort(
                key=lambda item: (
                    max([_safe_int(location.get("modified_time")) for location in item.get("locations") or []] or [0]),
                    str(item.get("rjcode") or ""),
                ),
                reverse=reverse,
            )
        else:
            items.sort(key=lambda item: (
                str(item.get("primary_category") or "").casefold(),
                str(item.get("rjcode") or ""),
            ))
        return items

    def _find_group_work(self, snapshot: dict[str, Any], group_key: str, work_key: str) -> Optional[dict[str, Any]]:
        target = _normalize_rjcode(work_key) or str(work_key or "").strip()
        for work in self._get_group_works(snapshot, group_key):
            rjcode = _normalize_rjcode(work.get("rjcode")) or str(work.get("rjcode") or "").strip()
            if rjcode == target:
                return work
        return None

    def _get_group_works(self, snapshot: dict[str, Any], group_key: str) -> list[dict[str, Any]]:
        works_by_group = snapshot.setdefault("works_by_group", {})
        if group_key in works_by_group:
            return works_by_group.get(group_key) or []

        rows_by_group = snapshot.get("rows_by_group") or {}
        works = self._sort_works(self._build_work_items(rows_by_group.get(group_key) or []))
        works_by_group[group_key] = works
        return works

    def resolve_action_targets(
        self,
        *,
        current_path: str = _CIRCLE_ROOT_PATH,
        paths: Optional[list[str]] = None,
        max_targets: int = 5000,
    ) -> dict[str, Any]:
        snapshot = self._get_snapshot()
        requested_paths = [str(path or "").strip() for path in (paths or []) if str(path or "").strip()]
        if not requested_paths:
            requested_paths = [str(current_path or _CIRCLE_ROOT_PATH).strip() or _CIRCLE_ROOT_PATH]

        normalized_limit = max(1, min(int(max_targets or 5000), 20000))
        targets: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        truncated = False

        for path in requested_paths:
            for target in self._resolve_virtual_path_targets(snapshot, path):
                key = (str(target.get("library_id") or ""), str(target.get("path") or ""))
                if not key[0] or not key[1] or key in seen:
                    continue
                if len(targets) >= normalized_limit:
                    truncated = True
                    break
                seen.add(key)
                targets.append(target)
            if truncated:
                break

        return {
            "items": targets,
            "total": len(targets),
            "truncated": truncated,
            "max_targets": normalized_limit,
            "circle_summary": snapshot.get("summary") or {},
        }

    def _resolve_virtual_path_targets(self, snapshot: dict[str, Any], path: str) -> list[dict[str, Any]]:
        decoded = _decode_circle_virtual_path(path)
        rows_by_group = snapshot.get("rows_by_group") or {}

        if decoded.type == "root":
            targets: list[dict[str, Any]] = []
            for group in snapshot.get("groups") or []:
                targets.extend(self._targets_from_index_rows(rows_by_group.get(group.get("circle_key") or "") or []))
            return targets

        if decoded.type == "group":
            return self._targets_from_index_rows(rows_by_group.get(decoded.group_key) or [])

        if decoded.type in {"work", "item"}:
            rows = [
                row
                for row in rows_by_group.get(decoded.group_key) or []
                if _normalize_rjcode(row.get("rjcode")) == _normalize_rjcode(decoded.work_key)
            ]
            if decoded.type == "item":
                rows = rows[:1]
            return self._targets_from_index_rows(rows, relative_path=decoded.item_relative_path if decoded.type == "item" else "")

        if decoded.type in {"location", "location-item"}:
            group = snapshot.get("groups_by_key", {}).get(decoded.group_key)
            work = self._find_group_work(snapshot, decoded.group_key, decoded.work_key) if group else None
            locations = list(work.get("locations") or []) if work else []
            if not locations:
                return []
            location_index = max(0, min(int(decoded.location_index or 0), len(locations) - 1))
            location = locations[location_index]
            return [self._target_from_location(location, decoded.item_relative_path if decoded.type == "location-item" else "", work)]

        return []

    def _targets_from_index_rows(self, rows: list[dict[str, Any]], relative_path: str = "") -> list[dict[str, Any]]:
        return [self._target_from_index_row(row, relative_path) for row in rows]

    def _target_from_index_row(self, row: dict[str, Any], relative_path: str = "") -> dict[str, Any]:
        real_path = _join_real_path(row.get("path"), relative_path) if relative_path else str(row.get("path") or "")
        name = _location_folder_name({
            "name": row.get("name"),
            "relative_path": relative_path or row.get("relative_path"),
            "path": real_path,
        })
        return {
            "library_id": str(row.get("library_id") or ""),
            "library_name": str(row.get("library_name") or ""),
            "path": real_path,
            "folder_path": real_path,
            "name": name,
            "folder_name": name,
            "rjcode": _normalize_rjcode(row.get("rjcode")),
            "is_directory": True,
        }

    def _target_from_location(self, location: dict[str, Any], relative_path: str = "", work: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        real_path = _join_real_path(location.get("path"), relative_path) if relative_path else str(location.get("path") or "")
        name = _location_folder_name({
            "name": relative_path or location.get("name"),
            "relative_path": relative_path or location.get("relative_path"),
            "path": real_path,
        })
        return {
            "library_id": str(location.get("library_id") or ""),
            "library_name": str(location.get("library_name") or ""),
            "path": real_path,
            "folder_path": real_path,
            "name": name,
            "folder_name": name,
            "rjcode": _normalize_rjcode((work or {}).get("rjcode")),
            "is_directory": True,
        }

    def _build_group_row(self, group: dict[str, Any]) -> dict[str, Any]:
        name = str(group.get("circle_name") or UNKNOWN_CIRCLE_NAME).strip()
        return {
            "id": f"circle-group:{group.get('circle_key') or name}",
            "path": _circle_group_path(group.get("circle_key") or name),
            "name": name,
            "type": "directory",
            "is_directory": True,
            "rjcode": "",
            "size": int(group.get("total_size") or 0),
            "size_status": "ready",
            "file_count": int(group.get("work_count") or 0),
            "folder_count": int(group.get("folder_count") or 0),
            "modified_time": _safe_int(group.get("modified_time")) or None,
            "circle_virtual": True,
            "circle_row_type": "group",
            "circle_key": group.get("circle_key") or "",
            "circle_id": group.get("circle_id") or "",
            "circle_name": name,
            "circle_conflict_count": int(group.get("conflict_count") or 0),
            "circle_categories": list(group.get("categories") or []),
            "circle_work_count": int(group.get("work_count") or 0),
        }

    def _build_work_row(self, group: dict[str, Any], work: dict[str, Any]) -> dict[str, Any]:
        locations = list(work.get("locations") or [])
        primary_location = locations[0] if locations else {}
        rjcode = str(work.get("rjcode") or "").strip()
        folder_name = _location_folder_name(primary_location)
        conflict = bool(work.get("conflict"))
        display_name = f"{rjcode or '未知 RJ'} · {len(locations)} 个路径冲突" if conflict else (folder_name or rjcode or "未知作品")
        group_key = str(group.get("circle_key") or "")
        return {
            "id": f"circle-work:{group_key}:{rjcode}",
            "path": _circle_work_path(group_key, rjcode),
            "name": display_name,
            "type": "directory",
            "is_directory": True,
            "rjcode": rjcode,
            "size": int(work.get("total_size") or 0),
            "size_status": "ready",
            "file_count": int(work.get("file_count") or 0),
            "folder_count": int(work.get("folder_count") or len(locations) or 0),
            "modified_time": _safe_int(work.get("modified_time")) or (primary_location.get("modified_time") if primary_location else None),
            "library_id": "" if conflict else str(primary_location.get("library_id") or ""),
            "library_name": "" if conflict else str(primary_location.get("library_name") or ""),
            "parent_path": _circle_group_path(group_key),
            "circle_virtual": conflict,
            "circle_row_type": "work-conflict" if conflict else "work-single",
            "circle_key": group_key,
            "circle_name": str(group.get("circle_name") or ""),
            "circle_work_key": rjcode,
            "circle_title": work.get("title") or "",
            "circle_folder_name": folder_name,
            "circle_conflict": conflict,
            "circle_location_count": len(locations),
            "circle_locations": locations,
            "circle_categories": list(work.get("categories") or []),
            "circle_relative_path": str(primary_location.get("relative_path") or ""),
            "circle_top_category": str(primary_location.get("top_category") or ""),
            "circle_real_path": str(primary_location.get("path") or ""),
            "circle_real_library_id": str(primary_location.get("library_id") or ""),
        }

    def _build_conflict_location_row(
        self,
        group: dict[str, Any],
        work: dict[str, Any],
        location: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        group_key = str(group.get("circle_key") or "")
        rjcode = str(work.get("rjcode") or "").strip()
        return {
            "id": f"circle-location:{group_key}:{rjcode}:{index}:{location.get('library_id') or ''}:{location.get('relative_path') or location.get('path') or ''}",
            "path": _circle_conflict_path(group_key, rjcode, location, index),
            "name": _location_folder_name(location) or "未知路径",
            "type": "directory",
            "is_directory": True,
            "rjcode": rjcode,
            "size": int(location.get("size") or 0),
            "size_status": "ready",
            "file_count": int(location.get("file_count") or 0),
            "folder_count": 0,
            "modified_time": location.get("modified_time"),
            "library_id": str(location.get("library_id") or ""),
            "library_name": str(location.get("library_name") or ""),
            "parent_path": _circle_work_path(group_key, rjcode),
            "circle_virtual": False,
            "circle_row_type": "conflict-location",
            "circle_key": group_key,
            "circle_name": str(group.get("circle_name") or ""),
            "circle_work_key": rjcode,
            "circle_title": work.get("title") or "",
            "circle_conflict": True,
            "circle_location_index": int(index or 0),
            "circle_conflict_tone": int(index or 0) % 4,
            "circle_relative_path": str(location.get("relative_path") or ""),
            "circle_top_category": str(location.get("top_category") or ""),
            "circle_real_path": str(location.get("path") or ""),
            "circle_real_library_id": str(location.get("library_id") or ""),
        }

    async def _browse_location_children(
        self,
        *,
        group: dict[str, Any],
        work: dict[str, Any],
        location: dict[str, Any],
        location_index: int,
        relative_path: str,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        conflict_location: bool,
        circle_summary: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        manager = get_library_manager()
        group_key = str(group.get("circle_key") or "")
        rjcode = str(work.get("rjcode") or "").strip()
        normalized_relative = _normalize_path(relative_path)
        real_path = _join_real_path(location.get("path"), normalized_relative)
        data = await manager.list_files(
            str(location.get("library_id") or ""),
            page=page,
            page_size=page_size,
            search="",
            current_path=real_path,
            sort_by=_normalize_sort_by(sort_by),
            sort_order=sort_order,
            force_refresh=False,
        )

        rows = [
            self._build_child_row(
                group=group,
                work=work,
                location=location,
                location_index=location_index,
                item=item,
                conflict_location=conflict_location,
            )
            for item in data.get("files") or []
        ]
        base_virtual_path = (
            _circle_conflict_path(group_key, rjcode, location, location_index)
            if conflict_location
            else _circle_work_path(group_key, rjcode)
        )
        current_virtual_path = _circle_child_path(base_virtual_path, normalized_relative) if normalized_relative else base_virtual_path
        parent_relative = _parent_relative_path(normalized_relative)
        if normalized_relative:
            parent_path = _circle_child_path(base_virtual_path, parent_relative) if parent_relative else base_virtual_path
        else:
            parent_path = _circle_work_path(group_key, rjcode) if conflict_location else _circle_group_path(group_key)

        return self._browser_payload(
            files=rows,
            total=int(data.get("total") or len(rows)),
            page=int(data.get("page") or page),
            page_size=int(data.get("page_size") or page_size),
            current_path=current_virtual_path,
            parent_path=parent_path,
            circle_context={"type": "children", "group": group, "work": work},
            circle_group=group,
            circle_work=work,
            circle_works=[work],
            circle_summary=circle_summary or {},
        )

    def _build_child_row(
        self,
        *,
        group: dict[str, Any],
        work: dict[str, Any],
        location: dict[str, Any],
        location_index: int,
        item: dict[str, Any],
        conflict_location: bool,
    ) -> dict[str, Any]:
        group_key = str(group.get("circle_key") or "")
        rjcode = str(work.get("rjcode") or "").strip()
        real_path = str(item.get("path") or "").strip()
        relative_path = _relative_path_from_base(location.get("path"), real_path, item.get("relative_path") or item.get("name") or "")
        base_virtual_path = (
            _circle_conflict_path(group_key, rjcode, location, location_index)
            if conflict_location
            else _circle_work_path(group_key, rjcode)
        )
        parent_relative = _parent_relative_path(relative_path)
        row = dict(item)
        row.update({
            "id": f"circle-item:{group_key}:{rjcode}:{location_index}:{relative_path or real_path}",
            "path": _circle_child_path(base_virtual_path, relative_path or item.get("name") or ""),
            "parent_path": _circle_child_path(base_virtual_path, parent_relative) if parent_relative else base_virtual_path,
            "library_id": "",
            "library_name": "",
            "circle_virtual": False,
            "circle_row_type": "work-child",
            "circle_key": group_key,
            "circle_name": str(group.get("circle_name") or ""),
            "circle_work_key": rjcode,
            "circle_title": work.get("title") or "",
            "circle_relative_path": relative_path,
            "circle_real_path": real_path,
            "circle_real_library_id": str(location.get("library_id") or ""),
            "circle_location_index": int(location_index or 0),
        })
        return row

    @staticmethod
    def _browser_payload(
        *,
        files: list[dict[str, Any]],
        total: int,
        page: int,
        page_size: int,
        current_path: str,
        parent_path: str,
        circle_context: Optional[dict[str, Any]] = None,
        circle_groups: Optional[list[dict[str, Any]]] = None,
        circle_group: Optional[dict[str, Any]] = None,
        circle_work: Optional[dict[str, Any]] = None,
        circle_works: Optional[list[dict[str, Any]]] = None,
        circle_summary: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "files": files,
            "page": max(1, int(page or 1)),
            "page_size": max(1, int(page_size or 50)),
            "total": max(0, int(total or 0)),
            "current_path": current_path or _CIRCLE_ROOT_PATH,
            "browse_root_path": _CIRCLE_ROOT_PATH,
            "parent_path": parent_path or "",
        }
        if circle_context is not None:
            payload["circle_context"] = circle_context
        if circle_groups is not None:
            payload["circle_groups"] = circle_groups
        if circle_group is not None:
            payload["circle_group"] = circle_group
        if circle_work is not None:
            payload["circle_work"] = circle_work
        if circle_works is not None:
            payload["circle_works"] = circle_works
        if circle_summary is not None:
            payload["circle_summary"] = circle_summary
        return payload

    def _empty_browser_payload(
        self,
        *,
        current_path: str,
        page: int,
        page_size: int,
        parent_path: str = "",
        circle_group: Optional[dict[str, Any]] = None,
        circle_work: Optional[dict[str, Any]] = None,
        circle_works: Optional[list[dict[str, Any]]] = None,
        circle_summary: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._browser_payload(
            files=[],
            total=0,
            page=page,
            page_size=page_size,
            current_path=current_path,
            parent_path=parent_path,
            circle_group=circle_group,
            circle_work=circle_work,
            circle_works=circle_works,
            circle_summary=circle_summary,
        )

    def list_circle_groups(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> dict[str, Any]:
        snapshot = self._get_snapshot()
        items = self._filter_groups(snapshot["groups"], keyword)
        items = self._sort_groups(items, sort_by=sort_by, sort_order=sort_order)
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
        snapshot = self._get_snapshot()
        group = snapshot["groups_by_key"].get(circle_key)
        if group is None:
            for item in snapshot["groups"]:
                if item.get("circle_id") != requested_id:
                    continue
                if requested_name and item.get("circle_name") != requested_name:
                    continue
                group = item
                break
        if group is None:
            group = {
                "circle_key": circle_key,
                "circle_id": requested_id,
                "circle_name": requested_name or requested_id or UNKNOWN_CIRCLE_NAME,
            }

        effective_key = str(group.get("circle_key") or circle_key)
        works = self._filter_works(self._get_group_works(snapshot, effective_key), keyword)
        payload = self._paginate(works, page=page, page_size=page_size, extra={"items": works})
        payload.update({
            "circle_key": effective_key,
            "circle_id": group.get("circle_id") or requested_id,
            "circle_name": group.get("circle_name") or requested_name or requested_id or UNKNOWN_CIRCLE_NAME,
        })
        return payload

    def _load_active_library_summary_items(self) -> list[dict[str, str]]:
        manager = get_library_manager()
        libraries = manager._active_libraries()
        items = [
            {
                "library_id": str(library.id or ""),
                "library_name": str(library.name or library.id or ""),
                "library_type": str(library.type or ""),
            }
            for library in libraries
            if str(library.id or "")
        ]
        return sorted(items, key=lambda item: (
            0 if item["library_type"] == "local" else 1,
            item["library_name"].casefold(),
            item["library_id"].casefold(),
        ))

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
                db.query(
                    LibraryIndexEntry.library_id,
                    LibraryIndexEntry.rjcode,
                    LibraryIndexEntry.absolute_path,
                    LibraryIndexEntry.relative_path,
                    LibraryIndexEntry.name,
                    LibraryIndexEntry.size,
                    LibraryIndexEntry.file_count,
                    LibraryIndexEntry.mtime,
                )
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
            for entry in query.yield_per(1000):
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
                    "modified_time": None,
                },
            )
            if row["top_category"]:
                item["categories"].add(row["top_category"])
            item["folder_count"] += 1
            item["total_size"] += row["size"]
            item["file_count"] += row["file_count"]
            row_modified_time = _safe_int(row.get("modified_time"))
            if row_modified_time and row_modified_time > _safe_int(item.get("modified_time")):
                item["modified_time"] = row_modified_time
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
            item["modified_time"] = _safe_int(item.get("modified_time")) or None
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

    def _identity_from_index_path(self, row: dict[str, Any]) -> Optional[_CircleIdentity]:
        circle_name = _infer_circle_name_from_index_path(row.get("relative_path"), row.get("rjcode"), row.get("name"))
        if not circle_name:
            return None
        return self._identity_from_values("", circle_name)

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
