"""社团批量核对的完整性与请求预算回归。"""
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.asmr_download_service import ASMRDownloadService
from app.core.circle_completion_service import CircleCompletionService


def catalog_page(number, total=101):
    return {
        "pagination": {"currentPage": number, "pageSize": 100, "totalCount": total},
        "works": [
            {"id": value, "source_id": f"RJ{value:08d}", "circle_id": 49556,
             "circle": {"id": 49556, "source_id": "RG49556", "source_type": "DLSITE"}}
            for value in range(total - (number - 1) * 100, max(0, total - number * 100), -1)
        ],
    }


def install_pages(monkeypatch, payloads, status=200):
    service = ASMRDownloadService()
    calls = []

    class Response:
        headers = {"Retry-After": "10"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def json(self):
            return payloads[len(calls) - 1]

    Response.status = status

    class Session:
        def get(self, url, **kwargs):
            calls.append(kwargs["params"]["page"])
            return Response()

    monkeypatch.setattr(service, "_get_session", AsyncMock(return_value=Session()))
    monkeypatch.setattr(service, "_pace_metadata", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_proxy_request_kwargs", lambda: {})
    return service, calls


@pytest.mark.asyncio
async def test_catalog_complete_pages_recheck_and_budget(monkeypatch):
    service, calls = install_pages(monkeypatch, [catalog_page(1), catalog_page(2), catalog_page(1)])
    result = await service.fetch_circle_work_catalog("RG49556", request_budget=10)
    assert len(result) == 101
    assert calls == [1, 2, 1]
    assert result["RJ00000001"]["id"] == 1

    service, calls = install_pages(monkeypatch, [catalog_page(1)])
    assert await service.fetch_circle_work_catalog("RG49556", request_budget=3) is None
    assert calls == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["identity", "duplicate", "missing", "total", "moving", "non_rj"])
async def test_catalog_incomplete_never_returns_missing_evidence(monkeypatch, fault):
    pages = [catalog_page(1), catalog_page(2), catalog_page(1)]
    if fault == "identity":
        pages[0]["works"][0]["circle"]["source_id"] = "RG60289"
    elif fault == "duplicate":
        pages[1]["works"][0] = deepcopy(pages[0]["works"][0])
    elif fault == "missing":
        pages[1]["works"] = []
    elif fault == "total":
        pages[1]["pagination"]["totalCount"] = 102
    elif fault == "moving":
        pages[2]["works"].reverse()
    elif fault == "non_rj":
        pages[0]["works"][0]["source_id"] = "VJ00000101"
    service, _calls = install_pages(monkeypatch, pages)
    assert await service.fetch_circle_work_catalog("RG49556") is None


@pytest.mark.asyncio
async def test_catalog_429_records_cooldown(monkeypatch):
    service, calls = install_pages(monkeypatch, [], status=429)
    record = Mock()
    monkeypatch.setattr(service, "_record_rate_limit", record)
    assert await service.fetch_circle_work_catalog("RG49556") is None
    assert calls == [1]
    record.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_snapshot_multi_maker_preserves_tracks_and_unknown_lookup(monkeypatch, complete):
    service = CircleCompletionService()
    codes = [f"RJ{value:08d}" for value in range(100000, 100031)]
    makers = {code: ("RG49556" if i < 10 else "RG60289") for i, code in enumerate(codes[:20])}
    monkeypatch.setattr(service.dlsite_service, "index_product_makers", lambda: dict(makers))
    additional = {code: "RG60289" for code in codes[20:30]}
    bulk = AsyncMock(return_value=additional)
    monkeypatch.setattr(service.dlsite_service, "fetch_product_makers", bulk)
    monkeypatch.setattr(service, "_prewarm_canonical_cache_from_db", lambda _codes: 0)
    monkeypatch.setattr(service, "resolve_canonical_rj", AsyncMock(side_effect=lambda rj, **kw: {
        "canonical_rjcode": rj, "linked_rjcodes": [rj]}))

    class ASMR:
        fetch_work_info = AsyncMock(return_value={"id": "single"})
        fetch_track_list = AsyncMock(return_value=[{"type": "audio"}])
        fetch_circle_work_catalog = AsyncMock(side_effect=lambda maker, **kw: (
            {code: {"id": code} for code in codes[:30] if {**makers, **additional}[code] == maker and int(code[2:]) % 2 == 0}
            if complete else None))

    service.asmr_service = ASMR()
    snapshot = await service._collect_external_snapshot(codes, force_refresh=True, maker_id="RG49556")
    bulk.assert_awaited_once_with(codes[20:])
    assert service.asmr_service.fetch_circle_work_catalog.await_count == 2
    assert service.asmr_service.fetch_work_info.await_count == (1 if complete else 31)
    assert service.asmr_service.fetch_track_list.await_count == (16 if complete else 31)
    assert snapshot.contains_asmr(codes[-1])
    assert snapshot.contains_asmr(codes[0])
    assert snapshot.contains_asmr(codes[1]) is (not complete)


@pytest.mark.asyncio
async def test_official_maker_bulk_limits_500_and_keeps_unknown(monkeypatch):
    from app.core.dlsite_service import DLsiteApiService
    service = DLsiteApiService()
    codes = [f"RJ{value:08d}" for value in range(100000, 100501)]
    fetch = AsyncMock(side_effect=[{
        codes[0]: {"maker_id": "RG49556"}, codes[1]: {"maker": {"id": "RG60289"}},
        codes[2]: {"maker_id": "unknown"}}, None])
    monkeypatch.setattr(service, "_fetch_product_info_ajax_payloads", fetch)
    assert await service.fetch_product_makers(codes) == {codes[0]: "RG49556", codes[1]: "RG60289"}
    assert [len(call.args[0]) for call in fetch.await_args_list] == [500, 1]


@pytest.mark.asyncio
async def test_catalog_keeps_language_priority_and_requires_tracks(monkeypatch):
    service = CircleCompletionService()
    originals = [f"RJ{value:08d}" for value in range(100000, 100010)]
    translations = [f"RJ{value:08d}" for value in range(200000, 200010)]
    pairs = dict(zip(originals, translations))
    makers = {**dict.fromkeys(originals, "RG49556"), **dict.fromkeys(translations, "RG60289")}
    monkeypatch.setattr(service.dlsite_service, "index_product_makers", lambda: makers)
    monkeypatch.setattr(service, "_prewarm_canonical_cache_from_db", lambda _codes: 0)

    async def resolve(code, **_kwargs):
        translated = pairs[code]
        return {"canonical_rjcode": code, "linked_rjcodes": [code, translated], "link_map": {
            code: {"link_type": "original", "lang": "JPN"},
            translated: {"link_type": "translation", "lang": "CHI_HANS"}}}

    monkeypatch.setattr(service, "resolve_canonical_rj", resolve)

    class ASMR:
        fetch_work_info = AsyncMock(side_effect=AssertionError("完整目录不应触发逐作品请求"))
        fetch_circle_work_catalog = AsyncMock(side_effect=lambda maker, **kw: {
            code: {"id": code} for code in makers if makers[code] == maker})
        fetch_track_list = AsyncMock(side_effect=lambda code: [] if code == translations[0] else [{"type": "audio"}])

    service.asmr_service = ASMR()
    snapshot = await service._collect_external_snapshot(originals, force_refresh=True, maker_id="RG49556")
    assert service.asmr_service.fetch_work_info.await_count == 0
    assert service.asmr_service.fetch_track_list.await_count == 11
    assert snapshot.contains_asmr(originals[0])
    assert not snapshot.contains_asmr(translations[0])
    for code in originals[1:]:
        assert not snapshot.contains_asmr(code)
        assert snapshot.contains_asmr(pairs[code])
