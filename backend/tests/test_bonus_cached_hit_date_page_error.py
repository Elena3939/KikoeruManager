"""日期页失败不能丢失已经确认的特典命中。"""
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

import pytest

from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.dlsite_service import DLsiteApiService, DLsiteProductProbeFeature


@pytest.mark.asyncio
@pytest.mark.parametrize("has_hit", [True, False])
async def test_cached_bonus_survives_date_page_error(monkeypatch, has_hit):
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = DLsiteApiService()
    feature = DLsiteProductProbeFeature(
        workno="RJ01750551", exists=True, probe_status="ok",
        maker_id="RG53375", release_date="2026-10-30",
        is_hidden_bonus_audio=True,
    )
    monkeypatch.setattr(service, "_requires_strategy_refresh_sync", lambda **kw: False)
    monkeypatch.setattr(service, "_start_probe_date_sync", lambda **kw: None)
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features",
                        lambda **kw: [feature] if has_hit else [])
    monkeypatch.setattr(service, "_hidden_bonus_matches", lambda *a, **kw: True)
    monkeypatch.setattr(service, "_persist_precise_release_dates", lambda **kw: None)
    monkeypatch.setattr(service, "_load_public_worknos_for_date",
                        AsyncMock(return_value=(["RJ01700444"], [], [], "http_error")))
    finish = Mock(side_effect=lambda **kw: kw)
    fail = Mock()
    monkeypatch.setattr(service, "_finish_probe_date_result", finish)
    monkeypatch.setattr(service, "_fail_probe_date_sync", fail)
    options = dict(circle_id="RG53375", maker_id="RG53375", release_date="2026-10-30")
    if not has_hit:
        with pytest.raises(RuntimeError, match="http_error"):
            await service.probe_date(**options)
        finish.assert_not_called()
        fail.assert_called_once()
        return
    result = await service.probe_date(**options)
    assert [item.workno for item in result["hidden_hits"]] == ["RJ01750551"]
    assert result["result"]["incomplete"] is True
    assert "http_error" in result["result"]["error_message"]
    assert result["release_date"] == "2026-10-30"
    finish.assert_called_once()
    fail.assert_not_called()


def test_incomplete_result_persists_hit_without_no_bonus(monkeypatch):
    import app.core.dlsite_bonus_probe_service as module

    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    feature = DLsiteProductProbeFeature(workno="RJ01750551")
    monkeypatch.setattr(service, "_exclude_coverless_bonus_features", lambda hits: hits)
    upsert = Mock(return_value=1)
    monkeypatch.setattr(service, "_upsert_bonus_works", upsert)
    mark = Mock(side_effect=AssertionError("不完整扫描不能写无特典结论"))
    monkeypatch.setattr(service, "_mark_original_probe_states_after_scan", mark)
    monkeypatch.setattr(service, "_release_date_original_state_summary", lambda *a, **kw: {
        "original_count": 2, "concluded_count": 1, "pending_count": 1,
        "has_bonus_count": 1, "no_bonus_count": 0,
    })
    row = SimpleNamespace(mode="deep:date-range-v6")
    monkeypatch.setattr(service, "_upsert_date_row", lambda *a, **kw: row)
    monkeypatch.setattr(module, "SessionLocal", lambda: SimpleNamespace(
        close=lambda: None, commit=lambda: None,
    ))
    result = service._finish_probe_date_result(
        circle_id="RG53375", maker_id="RG53375", release_date="2026-10-30",
        gap_limit=500, mode_key="deep:date-range-v6", hidden_hits=[feature],
        target_original_rjcodes=None,
        result={"incomplete": True, "error_message": "日期页 http_error"},
    )
    assert result["hit_rjcodes"] == ["RJ01750551"]
    assert result["inserted_count"] == 1
    assert result["error_message"] == "日期页 http_error"
    assert row.status == "incomplete"
    assert row.hit_count == 1
    upsert.assert_called_once()
    mark.assert_not_called()
