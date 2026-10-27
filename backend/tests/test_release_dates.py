from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.circle_completion_service import CircleCompletionService
from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.release_dates import is_unreleased, release_date_end


@pytest.mark.parametrize("text,expected", [
    ("2026年10月上旬", date(2026, 10, 10)),
    ("2026年10月中旬", date(2026, 10, 20)),
    ("2026年10月下旬", date(2026, 10, 31)),
    ("2028年2月下旬", date(2028, 2, 29)),
    ("2026年10月", date(2026, 10, 31)),
    ("10月上旬", date(2026, 10, 10)),
    ("2026-10-27", date(2026, 10, 27)),
    ("2026/10/27", date(2026, 10, 27)),
    ("2026年 10月 27日", date(2026, 10, 27)),
    ("2026-02-30", None),
    ("未定", None),
])
def test_release_date_range_end(text, expected):
    assert release_date_end(text, today=date(2026, 10, 27)) == expected


def test_unreleased_uses_month_end_and_pending_keywords():
    today = date(2026, 10, 27)
    assert is_unreleased("2026年10月下旬", today=today)
    assert is_unreleased("発売日未定", today=today)
    assert not is_unreleased("2026年10月中旬", today=today)
    assert not is_unreleased("2026-10-27", today=today)


def test_unreleased_sort_uses_display_date_and_phase_order():
    service = CircleCompletionService.__new__(CircleCompletionService)
    rows = [
        {"title": phase, "release_date": f"2026年10月{phase}",
         "original_release_date": "2020-01-01", "is_unreleased": True}
        for phase in ("下旬", "上旬", "中旬")
    ]
    rows.extend([
        {"title": "未定", "release_date": "未定", "is_unreleased": True},
        {"title": "已发售", "release_date": "2026-10-27"},
    ])
    ascending = service._sort_completion_items(rows, "release_asc")
    assert [item["title"] for item in ascending] == ["已发售", "上旬", "中旬", "下旬", "未定"]
    assert service._sort_completion_items(rows, "release_desc") == list(reversed(ascending))


def test_stable_cache_and_conclusions_never_expire():
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    now = datetime.now(timezone.utc)
    assert service._cache_result_reusable("missing", now.isoformat())
    assert service._cache_result_reusable("missing", now - timedelta(days=3650))
    assert service._cache_result_reusable("missing", None)
    assert not service._cache_result_reusable("missing", now, force_refresh=True)
    assert not service._cache_result_reusable("error", now)
    assert service._cache_result_reusable("ok", now - timedelta(days=60))
    assert service._cache_result_reusable("ok", now, force_refresh=True)
    row = SimpleNamespace(status="completed", mode=service._mode_key("deep"),
                          finished_at=now - timedelta(days=2))
    assert service._can_reuse_completed_date_row(row, mode="deep")
    row.finished_at = now
    assert service._can_reuse_completed_date_row(row, mode="deep")


@pytest.mark.asyncio
async def test_unreleased_bonus_date_does_not_read_cache_or_request(monkeypatch):
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    start = AsyncMock(side_effect=AssertionError("未发售作品不应创建探测状态"))
    monkeypatch.setattr(service, "_start_probe_date_sync", start)
    result = await service.probe_date(circle_id="circle", maker_id="RG12345", release_date="2098-10-01")
    assert result["skip_reason"] == "unreleased"
    start.assert_not_called()


@pytest.mark.asyncio
async def test_unreleased_original_date_is_not_resolved():
    service = CircleCompletionService.__new__(CircleCompletionService)
    result = await service._completion_resolve_bonus_probe_release_date(
        {"release_date": "2098年10月上旬", "original_release_date": "2020-01-01"},
        ["RJ01709662"],
    )
    assert result == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", [False, True])
async def test_unreleased_resource_probe_skips_even_forced_refresh(monkeypatch, refresh):
    from app.core.resource_source_service import ResourceSourceService

    service = ResourceSourceService()
    monkeypatch.setattr(service, "_is_unreleased", lambda code: True)
    request = AsyncMock(side_effect=AssertionError("未发售作品不应请求资源"))
    monkeypatch.setattr(service, "request", request)
    result = await service.probe("RJ01709662", refresh=refresh)
    assert result["skip_reason"] == "unreleased"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("force_refresh", [False, True])
async def test_only_forced_missing_requeries_real_bonus_and_replaces_cache(monkeypatch, force_refresh):
    from app.core.dlsite_service import DLsiteProductProbeFeature

    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    old = datetime.now() - timedelta(days=2)
    writes = []

    class Redis:
        def read_bonus_probe_cache_rows_sync(self, codes):
            return {"RJ01709680": {
                "rjcode": "RJ01709680", "probe_status": "missing", "checked_at": old.isoformat(),
            }}

        def write_bonus_probe_cache_dirty_sync(self, payloads):
            writes.extend(payloads)
            return len(payloads)

    probe = AsyncMock(return_value={
        "RJ01709680": DLsiteProductProbeFeature(
            workno="RJ01709680", exists=True, probe_status="ok",
            is_hidden_bonus_audio=True, title="特典",
        ),
    })
    service.dlsite_service = SimpleNamespace(probe_product_info_features=probe)
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: Redis())
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal",
                        lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(service, "_cache_rows_by_rjcodes_sync", lambda db, codes: [
        SimpleNamespace(rjcode="RJ01709680", probe_status="missing", checked_at=old),
    ])
    features, cached, requests = await service._load_or_probe_features(
        ["RJ01709680"], batch_size=500, concurrency=6, force_refresh=force_refresh,
    )
    if not force_refresh:
        assert (cached, requests) == (1, 0)
        probe.assert_not_awaited()
        assert features["RJ01709680"].probe_status == "missing"
        assert writes == []
        return
    assert (cached, requests) == (0, 1)
    probe.assert_awaited_once_with(["RJ01709680"], concurrency=6)
    assert features["RJ01709680"].is_hidden_bonus_audio
    assert writes[0]["rjcode"] == "RJ01709680"
    assert writes[0]["probe_status"] == "ok"


@pytest.mark.asyncio
async def test_unreleased_download_discovery_never_requests(monkeypatch):
    service = CircleCompletionService.__new__(CircleCompletionService)
    monkeypatch.setattr(service, "_unreleased_download_codes", lambda codes: set(codes))
    assert await service._discover_download_versions({}, "RJ01709662", refresh=True) == []


def test_pending_resource_queue_skips_unreleased_without_blocking_released(db_session, monkeypatch):
    from app.core import resource_source_service as module
    from app.models.database import ResourceSourceProbe, WorkMetadata

    future_codes = [f"RJ{1709000 + index:08d}" for index in range(25)]
    released = "RJ01709662"
    for code in [*future_codes, released]:
        db_session.add(WorkMetadata(
            rjcode=code, work_name=code,
            release_date="2098年10月上旬" if code in future_codes else "2026-09-22",
        ))
        db_session.add(ResourceSourceProbe(
            source=module.SOURCE, rjcode=code, probe_version=module.VERSION,
            status="pending", candidates=[],
        ))
    db_session.commit()
    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    assert module.ResourceSourceService().pending_codes() == [(released,)]
