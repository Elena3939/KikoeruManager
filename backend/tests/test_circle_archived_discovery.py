"""新库必须能发现列表中已停售的音声，目录只提供候选。"""
from unittest.mock import AsyncMock

import pytest

from app.core.circle_completion_service import CircleCompletionService


@pytest.mark.asyncio
async def test_archived_candidates_require_official_identity_and_audio(monkeypatch):
    service = CircleCompletionService()
    codes = [f"RJ{number}" for number in range(351724, 351730)]
    catalog = {code: {"title": "音声"} for code in codes}
    monkeypatch.setattr(service.asmr_service, "fetch_circle_work_catalog", AsyncMock(return_value=catalog))
    products = {
        codes[1]: {"workno": codes[1], "maker_id": "RG55461", "work_type": "SOU"},
        codes[2]: {"workno": codes[2], "maker_id": "RG99999", "work_type": "SOU"},
        codes[3]: {"workno": codes[3], "maker_id": "RG55461", "work_type": "MOV", "work_name": "ASMR"},
        codes[4]: {"workno": codes[1], "maker_id": "RG55461", "work_type": "SOU"},
    }
    async def product(code):
        return {"product": products.get(code, {})}
    fetch = AsyncMock(side_effect=product)
    monkeypatch.setattr(service.dlsite_service, "get_product_info", fetch)

    result, reused = await service._collect_archived_circle_candidates("RG55461", {codes[0]})

    assert [row["rjcode"] for row in result] == [codes[1]]
    assert reused is catalog
    assert fetch.await_count == 5
    assert codes[0] not in [call.args[0] for call in fetch.await_args_list]


@pytest.mark.asyncio
async def test_incomplete_directory_does_not_invent_candidates(monkeypatch):
    service = CircleCompletionService()
    monkeypatch.setattr(service.asmr_service, "fetch_circle_work_catalog", AsyncMock(return_value=None))
    fetch = AsyncMock()
    monkeypatch.setattr(service.dlsite_service, "get_product_info", fetch)
    assert await service._collect_archived_circle_candidates("RG55461", set()) == ([], None)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_reuses_discovery_catalog(monkeypatch):
    service = CircleCompletionService()
    code = "RJ351724"
    monkeypatch.setattr(service, "_prewarm_canonical_cache_from_db", lambda _codes: 0)
    monkeypatch.setattr(service, "resolve_canonical_rj", AsyncMock(return_value={
        "canonical_rjcode": code, "linked_rjcodes": [code], "link_map": {}}))
    monkeypatch.setattr(service.dlsite_service, "index_product_makers", lambda: {code: "RG55461"})
    reader = AsyncMock(side_effect=AssertionError("同一任务不应重复拉取社团目录"))
    monkeypatch.setattr(service.asmr_service, "fetch_circle_work_catalog", reader)
    monkeypatch.setattr(service.asmr_service, "fetch_work_info", AsyncMock(side_effect=AssertionError("应复用目录作品")))
    monkeypatch.setattr(service.asmr_service, "fetch_track_list", AsyncMock(return_value=[{"type": "audio"}]))
    result = await service._collect_external_snapshot(
        [code], maker_id="RG55461", force_refresh=True,
        discovery_catalogs={"RG55461": {code: {"id": 351724}}},
    )
    reader.assert_not_awaited()
    assert result.contains_asmr(code)
