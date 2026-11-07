"""归一读模型与旧业务逐项对照，覆盖真实 PostgreSQL 查询。"""
from datetime import datetime
from itertools import product

import pytest
from sqlalchemy import insert, select

from app.core.circle_completion_read_model import build_normalized_rows, read_page
from app.core.circle_completion_projection import read_projection_page
from app.models.database import (
    CircleCatalog, CircleCompletionHead, CircleCompletionControl,
    CircleCompletionWorkState, CircleCompletionWorkAlias,
    CircleCompletionGroup, CircleCompletionGroupMember,
)
from tests.test_circle_completion_projection import projection


@pytest.fixture
def normalized(projection):
    service, items, circle, factory = projection
    tables = (CircleCompletionWorkState, CircleCompletionWorkAlias,
              CircleCompletionGroup, CircleCompletionGroupMember)
    with factory.begin() as db:
        db.add(CircleCatalog(circle_id=circle, circle_name="对照"))
        db.flush()
        db.add(CircleCompletionHead(circle_id=circle, active_generation="g1", revision=1,
                                   applied_seq=1, summary={}, as_of=datetime(2026, 11, 5)))
        for table, rows in zip(tables, build_normalized_rows(service, items)):
            if rows:
                db.execute(insert(table), [dict(circle_id=circle, generation="g1", **row)
                                           for row in rows.values()])
    return projection


def test_query_shapes_match_old_projection(normalized):
    _, _, circle, factory = normalized
    with factory() as db:
        for tab, mode, include, sort, search, status in product(
            ("missing", "owned", "compare"), ("card", "list"), (False, True),
            ("updated_desc", "release_asc", "release_desc"), ("", "100%_", "RJ10000001", "不存在"),
            ([], ["downloadable"], ["has_early_bonus", "no_source"]),
        ):
            args = dict(tab=tab, view_mode=mode, include_dl_only=include,
                        sort=sort, search=search, status_filters=status)
            old = read_projection_page(circle, 2, 3, session_factory=factory, **args)
            new = read_page(db, circle, page=2, page_size=3, **args)
            # 普通页不再夹带特典成员的对比大字段；对比页保持完整字段。
            if tab != "compare":
                for item in old["rows"]:
                    for bonus in item.get("bonus_works", []):
                        bonus.pop("source_compare", None)
            assert new["rows"] == old["rows"], args
            for field in ("total", "page", "page_count"):
                assert new[field] == old[field], (args, field)
            assert new["filtered_count"] == old["summary"]["filtered_count"], args


def test_building_and_pending_are_read_only(normalized):
    _, _, circle, factory = normalized
    with factory.begin() as db:
        control = db.get(CircleCompletionControl, circle)
        control.requested_seq = 2
    with factory() as db:
        assert read_page(db, circle)["status"] == "stale"
        db.delete(db.get(CircleCompletionHead, circle))
        db.flush()
        result = read_page(db, circle)
        assert result["status"] == "building"
        assert result["rows"] == []
        assert db.execute(select(CircleCompletionControl.requested_seq).where(
            CircleCompletionControl.circle_id == circle)).scalar_one() == 2


def test_published_selection_and_location_match_page(normalized, monkeypatch):
    from app.core.circle_completion_published import read_published
    service, _, circle, factory = normalized
    for tab in ("missing", "owned", "compare"):
        page = read_published(service, factory, circle, "page", tab=tab, view_mode="list", page_size=200)
        codes = read_published(service, factory, circle, "codes", tab=tab)
        flattened = [member["canonical_rjcode"] for root in page["items"]
                     for member in [root, *(root.get("bonus_works") or [])]]
        assert set(codes["canonical_rjcodes"]) == set(flattened)
        for index, root in enumerate(page["items"]):
            for member in [root, *(root.get("bonus_works") or [])]:
                locate = read_published(service, factory, circle, "locate", tab=tab,
                                        rjcode=member["canonical_rjcode"], page_size=3)
                assert locate["index"] == index
                assert locate["page"] == index // 3 + 1
                assert locate["parent_canonical_rjcode"] == root["canonical_rjcode"]
    assert read_published(service, factory, circle, "summary")["revision"] == 1
    assert read_published(service, factory, circle, "detail")["works"]
