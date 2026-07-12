from __future__ import annotations

import pytest

from app.core.circle_completion_service import CircleCompletionService
from app.core.dlsite_service import DLsiteWorkSummary


def _search_card(rjcode: str, maker_id: str, maker_name: str) -> str:
    return (
        f'<dd class="work_name"><a href="https://www.dlsite.com/maniax/work/=/product_id/{rjcode}.html">作品</a></dd>'
        f'<dd class="maker_name"><a href="https://www.dlsite.com/maniax/circle/profile/=/maker_id/{maker_id}.html">'
        f'{maker_name}</a></dd>'
    )


def test_search_page_identity_ignores_page_wide_rj_noise() -> None:
    html = (
        "推荐位 RJ01670000 RJ01671000 "
        + _search_card("RJ01474504", "RG62099", "おほ声の館")
        + " 页脚 RJ01672000"
    )

    worknos, makers = CircleCompletionService._extract_dlsite_search_page_identity(html)

    assert worknos == ["RJ01474504"]
    assert makers == [{"maker_id": "RG62099", "maker_name": "おほ声の館"}]


def test_choose_maker_identity_rejects_multiple_same_name_ids() -> None:
    service = CircleCompletionService()

    with pytest.raises(ValueError, match="多个同名社团"):
        service._choose_dlsite_maker_identity(
            "同名社团",
            [
                {"maker_id": "RG10001", "maker_name": "同名社团"},
                {"maker_id": "RG10002", "maker_name": "同名社团"},
            ],
        )


@pytest.mark.asyncio
async def test_collect_dlsite_candidates_discovers_maker_without_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CircleCompletionService()
    summary = DLsiteWorkSummary(
        workno="RJ01474504",
        title="测试音声作品",
        maker_id="RG62099",
        maker_name="おほ声の館",
        work_type_code="SOU",
        is_probably_audio=True,
        classification_reason="work_type:SOU",
    )

    async def fake_search(_keyword: str, max_pages: int = 2):
        return (
            ["RJ01474504"],
            "",
            [{"maker_id": "RG62099", "maker_name": "おほ声の館"}],
        )

    async def fake_announce(_keyword: str, max_pages: int = 3):
        return [], "", []

    async def fake_profile(maker_id: str, language: str = "JPN"):
        assert maker_id == "RG62099"
        return [summary], "ok"

    async def fake_maker_announce(_maker_id: str):
        return [], ""

    async def fake_product_info(rjcode: str):
        assert rjcode == "RJ01474504"
        return {
            "product": {
                "workno": rjcode,
                "work_name": "测试音声作品",
                "maker_id": "RG62099",
                "maker_name": "おほ声の館",
                "regist_date": "2026-01-01",
                "image_main": {},
            }
        }

    monkeypatch.setattr(service, "_search_dlsite_circle_works", fake_search)
    monkeypatch.setattr(service, "_search_dlsite_announce_works", fake_announce)
    monkeypatch.setattr(service.dlsite_service, "list_circle_work_summaries_by_maker", fake_profile)
    monkeypatch.setattr(service, "_list_dlsite_maker_announce_worknos", fake_maker_announce)
    monkeypatch.setattr(service.dlsite_service, "get_product_info", fake_product_info)

    candidates = await service._collect_dlsite_circle_candidates("おほ声の館")

    assert len(candidates) == 1
    assert candidates[0]["rjcode"] == "RJ01474504"
    assert candidates[0]["maker_id"] == "RG62099"
    assert candidates[0]["maker_name"] == "おほ声の館"


@pytest.mark.asyncio
async def test_collect_with_existing_maker_id_skips_identity_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有 maker ID 必须保持原快速路径，不重复请求关键词或预告搜索。"""
    service = CircleCompletionService()
    summary = DLsiteWorkSummary(
        workno="RJ01474504",
        title="测试音声作品",
        maker_id="RG62099",
        maker_name="おほ声の館",
        work_type_code="SOU",
        is_probably_audio=True,
    )

    async def fail_search(*_args, **_kwargs):
        raise AssertionError("已有 maker ID 时不应执行身份搜索")

    async def fake_profile(maker_id: str, language: str = "JPN"):
        assert maker_id == "RG62099"
        return [summary], "ok"

    async def fake_maker_announce(_maker_id: str):
        return [], ""

    async def fake_product_info(rjcode: str):
        return {
            "product": {
                "workno": rjcode,
                "work_name": "测试音声作品",
                "maker_id": "RG62099",
                "maker_name": "おほ声の館",
                "regist_date": "2026-01-01",
                "image_main": {},
            }
        }

    monkeypatch.setattr(service, "_search_dlsite_circle_works", fail_search)
    monkeypatch.setattr(service, "_search_dlsite_announce_works", fail_search)
    monkeypatch.setattr(service.dlsite_service, "list_circle_work_summaries_by_maker", fake_profile)
    monkeypatch.setattr(service, "_list_dlsite_maker_announce_worknos", fake_maker_announce)
    monkeypatch.setattr(service.dlsite_service, "get_product_info", fake_product_info)

    candidates = await service._collect_dlsite_circle_candidates("おほ声の館", "RG62099")

    assert [item["rjcode"] for item in candidates] == ["RJ01474504"]
