from datetime import datetime

import httpx
import pytest

from app.core.dlsite_service import DLsiteApiService, DLsiteWorkSummary


@pytest.mark.asyncio
async def test_date_page_http_error_is_retried_immediately(monkeypatch):
    service = DLsiteApiService()
    calls = 0

    async def fake_get(_url, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("date page timeout")
        return type("Response", (), {"status_code": 200, "text": "date page"})()

    monkeypatch.setattr(service, "_guarded_get", fake_get)
    monkeypatch.setattr(service, "_looks_like_dlsite_html", lambda _html: True)
    monkeypatch.setattr(
        service,
        "_extract_summaries_from_listing_html",
        lambda _html: [DLsiteWorkSummary(workno="RJ01652948")],
    )

    first, first_status = await service.list_new_work_summaries_by_date("2026-06-27", max_pages=1)
    second, second_status = await service.list_new_work_summaries_by_date("2026-06-27", max_pages=1)

    assert first == []
    assert first_status == "http_error"
    assert second_status == "ok"
    assert [item.workno for item in second] == ["RJ01652948"]
    assert calls == 2


@pytest.mark.asyncio
async def test_date_page_legacy_http_error_cache_is_discarded(monkeypatch):
    service = DLsiteApiService()
    cache_key = "new_work_summaries_by_date:2026-06-27:JPN:1"
    service.cache[cache_key] = {"data": [], "parse_status": "http_error", "timestamp": datetime.now()}
    calls = 0

    async def fake_get(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return type("Response", (), {"status_code": 200, "text": "date page"})()

    monkeypatch.setattr(service, "_guarded_get", fake_get)
    monkeypatch.setattr(service, "_looks_like_dlsite_html", lambda _html: True)
    monkeypatch.setattr(
        service,
        "_extract_summaries_from_listing_html",
        lambda _html: [DLsiteWorkSummary(workno="RJ01652948")],
    )

    works, status = await service.list_new_work_summaries_by_date("2026-06-27", max_pages=1)

    assert status == "ok"
    assert [item.workno for item in works] == ["RJ01652948"]
    assert calls == 1
    assert service.cache[cache_key]["parse_status"] == "ok"


@pytest.mark.asyncio
async def test_date_page_url_variant_recovers_after_primary_failure(monkeypatch):
    service = DLsiteApiService()
    calls = []

    async def fake_get(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            return type("Response", (), {"status_code": 503, "text": ""})()
        return type("Response", (), {"status_code": 200, "text": "date page"})()

    monkeypatch.setattr(service, "_guarded_get", fake_get)
    monkeypatch.setattr(service, "_looks_like_dlsite_html", lambda _html: True)
    monkeypatch.setattr(
        service,
        "_extract_summaries_from_listing_html",
        lambda _html: [DLsiteWorkSummary(workno="RJ01652948")],
    )

    works, status = await service.list_new_work_summaries_by_date("2026-06-27", max_pages=1)

    assert status == "ok"
    assert [item.workno for item in works] == ["RJ01652948"]
    assert len(calls) == 2
