from __future__ import annotations

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
