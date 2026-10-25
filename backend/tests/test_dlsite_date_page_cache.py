from datetime import datetime
import asyncio
import threading

import httpx
import pytest

from app.core.dlsite_service import DLsiteApiService, DLsiteWorkSummary


@pytest.mark.asyncio
async def test_date_page_decoding_and_parsing_keep_event_loop_responsive(monkeypatch):
    service = DLsiteApiService()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    main_thread = threading.get_ident()
    threads = []

    class Response:
        status_code = 200

        @property
        def text(self):
            threads.append(threading.get_ident())
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=2)
            return '<div class="n_worklist_item" data-product_id="RJ01000001"></div>'

    async def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr(service, "_guarded_get", fake_get)
    task = asyncio.create_task(service.list_new_work_summaries_by_date("2026-10-24", max_pages=1))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not task.done()
        assert threads and all(thread != main_thread for thread in threads)
    finally:
        release.set()
        summaries, status = await task
    assert status == "ok"
    assert [summary.workno for summary in summaries] == ["RJ01000001"]


def test_listing_release_date_handles_whitespace_without_backtracking():
    service = DLsiteApiService()
    chunk = '<span class="release_date">' + " " * 20_000 + "</span>"
    assert service._extract_release_date_from_listing_chunk(chunk) == ""
    assert service._extract_release_date_from_listing_chunk(
        '<span class="release_date">\n 2026年10月24日  </span>',
    ) == "2026-10-24"


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
