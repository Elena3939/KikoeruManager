"""持久化投影与旧业务函数逐项对照，使用真实 PostgreSQL。"""
from copy import deepcopy
from itertools import product
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.circle_completion_service import CircleCompletionService
from app.core.circle_completion_projection import (
    build_projection_rows, projection_id, publish_projection, read_projection_page,
)
from app.models.database import CircleCompletionProjection


@pytest.fixture
def projection(db_engine, monkeypatch):
    factory = sessionmaker(bind=db_engine)
    service = CircleCompletionService()
    monkeypatch.setattr(service, "_completion_redis_service", lambda: None)
    items = []
    for index in range(24):
        code = f"RJ{10000000 + index}"
        parent = f"RJ{10000000 + index - 1}"
        item = dict(
            canonical_rjcode=code, display_rjcode=code, title=f"作品 {index:02d} 100%_",
            linked_rjcodes=[parent] if index % 3 == 1 else [],
            bonus_parent_rjcode=parent if index % 3 == 1 else "",
            is_bonus_work=index % 3 == 1, owned=index % 4 == 0,
            local_owned=index % 4 == 0, server_owned=index % 8 == 0,
            has_dlsite=True, has_asmr_one=index % 5 != 0,
            has_downloadable_source=index % 5 != 0,
            subtitle_present=index % 2 == 0, subtitle_repairable=index % 3 == 0,
            preferred_variant={"group_key": "original"},
            owned_variant={"group_key": ("original", "simplified", "traditional")[index % 3]},
            release_date=f"2026-01-{index + 1:02d}",
            early_bonus_status="has_bonus" if index % 2 else "no_bonus",
            source_compare={"dlsite": {"all_rjcodes": [code]}, "asmr_one": {"primary_rjcode": code}},
        )
        items.append(item)
    key = uuid4().hex
    summary = service._completion_summary_from_items({"circle_id": key, "circle_name": "对照"}, items)
    assert publish_projection(key, key, "v1", build_projection_rows(service, items), summary,
                              lambda: True, session_factory=factory)
    return service, items, key, factory


def test_all_query_shapes_match_existing_business_rules(projection):
    service, items, key, factory = projection
    for tab, mode, include, sort, search, status in product(
        ("missing", "owned", "compare"), ("card", "list"), (False, True),
        ("updated_desc", "release_asc", "release_desc"), ("", "100%_", "RJ10000001", "不存在"),
        ([], ["downloadable"], ["has_early_bonus", "no_source"]),
    ):
        args = dict(tab=tab, include_dl_only=include, status_filters=status, search=search,
                    sort=sort, view_mode=mode)
        source = deepcopy(items)
        if mode == "card" and tab in {"missing", "owned"}:
            expected = service._filter_completion_items_for_card_tab(
                source, tab=tab, include_dl_only=include, status_filters=status, search=search,
            )
            expected = service._sort_completion_items(expected, sort)
            filtered_count = sum(len(service._completion_group_members(item)) for item in expected)
        else:
            expected = service._filter_completion_items_for_tab(
                source, tab=tab, include_dl_only=include, status_filters=status, search=search,
            )
            expected = service._sort_completion_items(expected, sort)
            filtered_count = len(expected)
            if tab in {"missing", "owned"}:
                expected = service._completion_group_bonus_items(expected)
        result = read_projection_page(key, 2, 3, session_factory=factory, **args)
        assert result["total"] == len(expected), args
        assert result["summary"]["filtered_count"] == filtered_count, args
        start = (result["page"] - 1) * 3
        actual = [service._strip_completion_internal_fields(item) for item in result["rows"]]
        expected = [service._strip_completion_internal_fields(item) for item in expected[start:start + 3]]
        assert actual == expected, args


def test_invalidation_while_publishing_rolls_back_all_rows(projection):
    service, items, _, factory = projection
    key = uuid4().hex
    checks = iter((True, False))
    summary = {"total_works": len(items)}
    assert not publish_projection(key, key, "old", build_projection_rows(service, items), summary,
                                  lambda: next(checks), session_factory=factory)
    with factory() as db:
        assert db.execute(select(CircleCompletionProjection).where(
            CircleCompletionProjection.id == projection_id(key))).scalar_one_or_none() is None
    assert read_projection_page(key, 1, 10, session_factory=factory) is None


@pytest.mark.parametrize("tab,filter_name,values", [
    ("owned", "owned_filter", ("all", "original", "simplified", "traditional", "subtitle", "bonus")),
    ("compare", "compare_filter", ("all", "kikoeru", "dlsite", "asmr_one", "yaas", "missing")),
])
def test_tab_filters_match_existing_business_rules(projection, tab, filter_name, values):
    service, items, key, factory = projection
    for mode, include, value, search in product(("card", "list"), (False, True), values, ("", "RJ10000001")):
        args = dict(tab=tab, include_dl_only=include, search=search, sort="release_desc",
                    view_mode=mode, **{filter_name: value})
        source = deepcopy(items)
        if mode == "card" and tab == "owned":
            expected = service._filter_completion_items_for_card_tab(
                source, tab=tab, include_dl_only=include, search=search, owned_filter=value,
            )
        else:
            expected = service._filter_completion_items_for_tab(
                source, tab=tab, include_dl_only=include, search=search, **{filter_name: value},
            )
        expected = service._sort_completion_items(expected, "release_desc")
        if tab == "owned" and mode == "list":
            expected = service._completion_group_bonus_items(expected)
        result = read_projection_page(key, 1, 200, session_factory=factory, **args)
        assert result["total"] == len(expected), args
        assert [service._strip_completion_internal_fields(item) for item in result["rows"]] == [
            service._strip_completion_internal_fields(item) for item in expected
        ], args


def test_compare_details_only_loaded_for_compare_tab(projection):
    _, _, key, factory = projection
    regular = read_projection_page(key, 1, 10, session_factory=factory, tab="missing")
    compared = read_projection_page(key, 1, 10, session_factory=factory, tab="compare")
    assert all("source_compare" not in row for row in regular["rows"])
    assert all(row["source_compare"] for row in compared["rows"])
