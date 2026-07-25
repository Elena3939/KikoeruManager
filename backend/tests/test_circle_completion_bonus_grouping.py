from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.circle_completion_service import CircleCompletionService


def _work(code: str, *, display: str | None = None, bonus: bool = False, owned: bool = False) -> dict:
    return {
        "canonical_rjcode": code,
        "display_rjcode": display or code,
        "title": f"title-{display or code}",
        "linked_rjcodes": [display or code, code],
        "is_bonus_work": bonus,
        "owned": owned,
        "server_owned": owned,
        "has_asmr_one": True,
        "has_dlsite": True,
        "download_plan": {"rjcode": display or code},
        "owned_variant": {"group_key": "original", "rjcode": display or code},
        "preferred_variant": {"group_key": "original", "rjcode": display or code},
        "source_compare": {"work_rjcode": display or code},
    }


def test_completion_attach_bonus_parent_codes_uses_same_release_parent():
    service = CircleCompletionService()
    parent = _work("RJ01538146")
    parent["maker_id"] = "RG62878"
    parent["release_date"] = "2026-05-31"
    parent["original_release_date"] = "2026-05-31"
    bonus = _work("RJ01569983", bonus=True)
    bonus["linked_rjcodes"] = ["RJ01569983"]
    bonus["maker_id"] = "RG62878"
    bonus["release_date"] = "2026-05-31"

    result = service._completion_group_bonus_items(
        service._completion_attach_bonus_parent_codes([bonus, parent])
    )

    assert len(result) == 1
    assert result[0]["canonical_rjcode"] == "RJ01538146"
    assert result[0]["bonus_works"][0]["display_rjcode"] == "RJ01569983"
    assert result[0]["bonus_works"][0]["bonus_parent_rjcode"] == "RJ01538146"


def test_completion_bonus_uses_own_rj_before_same_day_grouping():
    """特典不能继承原作翻译版的展示 RJ，否则会按错误发售日错挂。"""
    service = CircleCompletionService()
    own_bonus = "RJ01576811"
    parent = _work("RJ01576789")
    parent["maker_id"] = "RG49556"
    parent["release_date"] = "2026-03-22"

    unrelated = _work("RJ01632796")
    unrelated["maker_id"] = "RG49556"
    unrelated["release_date"] = "2026-05-26"

    bonus = _work(own_bonus, display="RJ01592088", bonus=True)
    bonus["maker_id"] = "RG49556"
    bonus["release_date"] = "2026-03-22"
    bonus["linked_rjcodes"] = ["RJ01576789", own_bonus]

    display = service._completion_bonus_display_rjcode(
        own_bonus,
        "RJ01592088",
        {
            own_bonus: {"is_bonus_work": True},
            "RJ01592088": {"is_bonus_work": False},
        },
    )
    assert display == own_bonus

    bonus["display_rjcode"] = display
    grouped = service._completion_group_bonus_items(
        service._completion_attach_bonus_parent_codes([bonus, unrelated, parent])
    )

    parent_item = next(item for item in grouped if item["canonical_rjcode"] == "RJ01576789")
    unrelated_item = next(item for item in grouped if item["canonical_rjcode"] == "RJ01632796")
    assert parent_item["bonus_works"][0]["canonical_rjcode"] == own_bonus
    assert "bonus_works" not in unrelated_item


def test_completion_bonus_item_uses_own_date_and_cached_cover():
    """历史特典行残留原作封面时，读取路径也必须立即纠正。"""
    service = CircleCompletionService()

    class _ImageCache:
        def cache_rjcode_for_url(self, url, _fallback):
            assert "RJ01576811" in url
            return "RJ01576811"

        def restore_from_legacy_alias(self, *_args, **_kwargs):
            return None

        def get_local_url(self, rjcode, variant="card", **_kwargs):
            assert rjcode == "RJ01576811"
            return "/api/circle-completion/cover/RJ01576811_sam.jpg" if variant == "list" else ""

    row = SimpleNamespace(
        id="bonus",
        circle_id="RG49556",
        canonical_rjcode="RJ01576811",
        display_rjcode="RJ01592088",
        linked_rjcodes=["RJ01592088", "RJ01576789"],
        title="28日間限定早期特典",
        maker_id="RG49556",
        maker_name="RaRo",
        source_mask="dlsite",
        has_asmr_one=True,
        asmr_available_rjcode="RJ01576811",
        image_url="https://img.dlsite.jp/resize/images2/work/doujin/RJ01577000/RJ01576789_img_main_240x240.jpg",
        price_text="",
        is_bonus_work=True,
        has_bonus=False,
        source_tags=[],
        email_watcher_first_seen_at=None,
        created_at=datetime(2026, 7, 1),
    )
    metadata = {
        "RJ01576811": {
            "work_name": "28日間限定早期特典",
            "release_date": "2026-03-22",
            "is_bonus_work": True,
            "cover_url": "",
        },
        "RJ01592088": {
            "work_name": "错误翻译版",
            "release_date": "2026-05-26",
            "is_bonus_work": False,
        },
        "RJ01576789": {
            "work_name": "原作",
            "release_date": "2026-03-22",
            "is_bonus_work": False,
        },
    }

    item = service._build_completion_item(
        catalog=SimpleNamespace(circle_name="RaRo"),
        row=row,
        owned_row=None,
        link_map_by_canonical={},
        metadata_map_all=metadata,
        image_cache_service=_ImageCache(),
    )

    assert item["display_rjcode"] == "RJ01576811"
    assert item["release_date"] == "2026-03-22"
    assert item["image_url"].endswith("RJ01576811_sam.jpg")


@pytest.mark.asyncio
async def test_list_completion_works_groups_bonus_before_paging(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001")
    bonus = _work("RJ01000001", display="RJ01000002", bonus=True)
    bonus["source_compare"] = {"work_rjcode": "RJ01000002"}

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [bonus, parent],
        },
    )

    result = await service.list_circle_completion_works(
        "RG00001",
        tab="missing",
        page=1,
        page_size=1,
        include_dl_only=True,
    )

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["canonical_rjcode"] == "RJ01000001"
    assert result["items"][0]["bonus_works"][0]["display_rjcode"] == "RJ01000002"
    assert "source_compare" not in result["items"][0]["bonus_works"][0]


@pytest.mark.asyncio
async def test_card_completion_works_keeps_owned_parent_with_missing_bonus(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001", owned=True)
    bonus = _work("RJ01000001", display="RJ01000002", bonus=True, owned=False)
    bonus["source_compare"] = {"work_rjcode": "RJ01000002"}

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [bonus, parent],
        },
    )

    owned_page = await service.list_circle_completion_works(
        "RG00001",
        tab="owned",
        page=1,
        page_size=10,
        include_dl_only=True,
        view_mode="card",
    )
    missing_page = await service.list_circle_completion_works(
        "RG00001",
        tab="missing",
        page=1,
        page_size=10,
        include_dl_only=True,
        view_mode="card",
    )

    assert owned_page["total"] == 1
    assert missing_page["total"] == 0
    assert owned_page["items"][0]["canonical_rjcode"] == "RJ01000001"
    assert owned_page["items"][0].get("completion_card_dimmed") is False
    assert owned_page["items"][0]["bonus_works"][0]["display_rjcode"] == "RJ01000002"
    assert owned_page["items"][0]["bonus_works"][0]["completion_card_dimmed"] is True


@pytest.mark.asyncio
async def test_card_completion_works_keeps_owned_bonus_with_missing_parent(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001", owned=False)
    bonus = _work("RJ01000001", display="RJ01000002", bonus=True, owned=True)
    bonus["source_compare"] = {"work_rjcode": "RJ01000002"}

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [bonus, parent],
        },
    )

    owned_page = await service.list_circle_completion_works(
        "RG00001",
        tab="owned",
        page=1,
        page_size=10,
        include_dl_only=True,
        view_mode="card",
    )
    missing_page = await service.list_circle_completion_works(
        "RG00001",
        tab="missing",
        page=1,
        page_size=10,
        include_dl_only=True,
        view_mode="card",
    )

    assert owned_page["total"] == 1
    assert missing_page["total"] == 0
    assert owned_page["items"][0]["canonical_rjcode"] == "RJ01000001"
    assert owned_page["items"][0]["completion_card_dimmed"] is True
    assert owned_page["items"][0]["bonus_works"][0]["completion_card_dimmed"] is False


@pytest.mark.asyncio
async def test_card_completion_works_keeps_missing_group_colorful(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001", owned=False)
    bonus = _work("RJ01000001", display="RJ01000002", bonus=True, owned=False)
    bonus["source_compare"] = {"work_rjcode": "RJ01000002"}

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [bonus, parent],
        },
    )

    result = await service.list_circle_completion_works(
        "RG00001",
        tab="missing",
        page=1,
        page_size=10,
        include_dl_only=True,
        view_mode="card",
    )

    assert result["total"] == 1
    assert result["items"][0]["completion_card_dimmed"] is False
    assert result["items"][0]["bonus_works"][0]["completion_card_dimmed"] is False


@pytest.mark.asyncio
async def test_locate_bonus_work_returns_parent_page(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001")
    bonus = _work("RJ01000001", display="RJ01000002", bonus=True)
    bonus["source_compare"] = {"work_rjcode": "RJ01000002"}

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [bonus, parent],
        },
    )

    result = await service.locate_circle_completion_work(
        "RG00001",
        rjcode="RJ01000002",
        tab="missing",
        page_size=1,
        include_dl_only=True,
    )

    assert result["matched"] is True
    assert result["page"] == 1
    assert result["canonical_rjcode"] == "RJ01000001"
    assert result["display_rjcode"] == "RJ01000002"
    assert result["parent_canonical_rjcode"] == "RJ01000001"


@pytest.mark.asyncio
async def test_list_bonus_work_codes_returns_current_circle_bonus_rows(monkeypatch):
    service = CircleCompletionService()
    parent = _work("RJ01000001")
    bonus = _work("RJ01000002", bonus=True)
    bonus["bonus_parent_rjcode"] = "RJ01000001"
    duplicate_bonus = _work("RJ01000002", bonus=True)
    other = _work("RJ01000003")

    monkeypatch.setattr(
        service,
        "_build_completion_view_state",
        lambda _circle: {
            "catalog": {
                "circle_id": "RG00001",
                "circle_name": "测试社团",
                "source_mask": "",
                "last_indexed_at": None,
            },
            "items": [parent, bonus, duplicate_bonus, other],
        },
    )

    result = await service.list_circle_completion_bonus_work_codes("RG00001")

    assert result["circle_id"] == "RG00001"
    assert result["canonical_rjcodes"] == ["RJ01000002"]
    assert result["total"] == 1
    assert result["items"][0]["canonical_rjcode"] == "RJ01000002"
