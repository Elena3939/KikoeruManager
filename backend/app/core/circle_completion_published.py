"""业务接口适配：所有读取只消费已发布的社团快照。"""
import re

from .circle_completion_read_model import read_page, read_selection, read_summary
from .circle_completion_presentation import present_completion_rows


def read_published(service, sessions, circle, operation, **query):
    include = query.get("include_dl_only", True)
    if "status_filters" in query:
        query["status_filters"] = service._completion_status_filters(query["status_filters"])
    if "tab" in query:
        query["tab"] = query["tab"] if query["tab"] in {"missing", "owned", "compare"} else "missing"
    with sessions() as db:
        if operation == "summary":
            return read_summary(db, circle, include_dl_only=include)
        if operation == "page":
            query["page_size"] = max(1, min(200, int(query.get("page_size") or 10)))
            result = read_page(db, circle, **query)
            rows = result.pop("rows")
            present_completion_rows(service, rows)
            prepare = service._build_completion_compare_item if query.get("tab") == "compare" else service._strip_completion_internal_fields
            result.update(items=[prepare(row) for row in rows], tab=query.get("tab", "missing"),
                          status_filters=list(query.get("status_filters") or []))
            return result
        selection_only = query.pop("selection_only", False)
        requested = service.normalize_rjcode(query.pop("rjcode", ""))
        size = max(1, min(200, int(query.pop("page_size", 10) or 10)))
        only_missing = query.pop("only_missing", False)
        only_downloadable = query.pop("only_downloadable", False)
        if operation in {"bonus", "detail", "index_snapshot"}:
            query["tab"] = "missing" if only_missing else "compare"
        header, records = read_selection(db, circle, details=operation in {"detail", "index_snapshot"},
                                         include_compare=operation == "index_snapshot", **query)
        if operation == "index_snapshot":
            from .resource_source_service import get_resource_source_service
            # 一次批量查当前探测缓存和链接库，不逐作品联网或重复构建社团视图。
            get_resource_source_service().decorate_items(db, [row["payload"] for row in records])

    items = [row["payload"] for row in records]
    if operation == "index_snapshot":
        # 审计专用快照保留来源证据，普通详情与全选继续使用轻量投影。
        return dict(header, works=items, filtered_count=len(items))
    if operation == "locate":
        match = next((row for row in records if requested and requested in row["aliases"]), None)
        total = max((row["group_index"] for row in records), default=-1) + 1
        index = match["group_index"] if match else -1
        count = max(1, (total + size - 1) // size)
        item = match["payload"] if match else {}
        return dict(header, tab=query.get("tab", "missing"), rjcode=requested, matched=match is not None,
                    canonical_rjcode=item.get("canonical_rjcode", ""), display_rjcode=item.get("display_rjcode", ""),
                    parent_canonical_rjcode=match["parent"] if match else "", index=index,
                    page=index // size + 1 if match else 1, page_size=size, page_count=count, total=total)
    if operation == "detail":
        items = [item for item in items if not only_downloadable or item.get("has_downloadable_source", item.get("has_asmr_one"))]
        present_completion_rows(service, items)
        return dict(header, works=[service._strip_completion_internal_fields(item) for item in items], filtered_count=len(items))
    if operation == "bonus":
        fields = ("canonical_rjcode", "display_rjcode", "title", "owned", "local_owned", "server_owned")
        bonuses = [{key: item.get(key) for key in fields} for item in items if item.get("is_bonus_work")]
        return dict(header, canonical_rjcodes=[item["canonical_rjcode"] for item in bonuses], total=len(bonuses), items=bonuses)
    codes = [item["canonical_rjcode"] for item in items]
    downloadable = [item["canonical_rjcode"] for item in items if item.get("has_downloadable_source", item.get("has_asmr_one"))]
    result = dict(header, canonical_rjcodes=codes, downloadable_rjcodes=downloadable,
                  total=len(codes), downloadable_count=len(downloadable))
    if selection_only:
        return result
    bonus_parents = {row["parent"] for row in records if row["payload"].get("is_bonus_work")
                     and row["parent"] != row["payload"]["canonical_rjcode"]}
    dates = {}
    for item in items:
        date = item.get("original_release_date") or item.get("release_date") or ""
        if not item.get("is_unreleased") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            dates[item["canonical_rjcode"]] = date
    result.update(bonus_rjcodes=[item["canonical_rjcode"] for item in items if item.get("is_bonus_work")],
                  has_bonus_rjcodes=[item["canonical_rjcode"] for item in items
                                    if item["canonical_rjcode"] in bonus_parents or item.get("early_bonus_status") == "has_bonus"],
                  no_bonus_rjcodes=[item["canonical_rjcode"] for item in items if item.get("early_bonus_status") == "no_bonus"],
                  requested_rjcodes={item["canonical_rjcode"]: [item.get("display_rjcode") or item["canonical_rjcode"]] for item in items},
                  release_dates_by_rjcode=dates,
                  completed_bonus_probe_dates=[date for date in header.get("completed_bonus_probe_dates", []) if date in dates.values()])
    return result
