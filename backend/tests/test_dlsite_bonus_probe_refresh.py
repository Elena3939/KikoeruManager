from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.dlsite_service import DLsiteProductProbeFeature
from app.models.database import CircleWork, DLsiteBonusOriginalProbeState, DLsiteBonusProbeDate, WorkMetadata


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["normal", "force", "upgrade", "error", "incomplete", "unreleased"])
async def test_selected_refresh_preserves_scope_and_reuses_conclusion(db_session, monkeypatch, scenario):
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for code in ["RJ01709662", "RJ01709000"]:
        db_session.add(CircleWork(
            id=f"refresh-{code}", circle_id="refresh-circle", maker_id="RG41088",
            canonical_rjcode=code, display_rjcode=code, is_bonus_work=False,
        ))
        db_session.add(WorkMetadata(
            rjcode=code, maker_id="RG41088",
            release_date="2098年10月上旬" if scenario == "unreleased" and code == "RJ01709662" else "2026-09-22",
        ))
        db_session.add(DLsiteBonusOriginalProbeState(
            circle_id="refresh-circle", maker_id="RG41088", original_rjcode=code,
            release_date="2026-09-22", status="no_bonus",
            strategy_version="date-range-v5" if scenario == "upgrade" else service.PROBE_STRATEGY_VERSION,
            checked_at=datetime(2000, 1, 1),
        ))
    db_session.commit()
    writes = []
    requests = []
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **kwargs: [])
    public = AsyncMock(return_value=(["RJ01709662"], ["RJ01709662"], ["RJ01709662"], "ok"))
    monkeypatch.setattr(service, "_load_public_worknos_for_date", public)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", AsyncMock(return_value=(["RJ01709681"], "ok")))
    monkeypatch.setattr(
        service, "_build_selected_release_date_range_candidates",
        lambda *args, **kwargs: (["RJ01709680"], 1, scenario == "incomplete"),
    )

    def cache(codes, *, force_refresh=False):
        return {
            code: DLsiteProductProbeFeature(workno=code, probe_status="missing")
            for code in codes if code == "RJ01709680" and not force_refresh
        }

    async def probe(codes, **kwargs):
        requests.extend(codes)
        return {
            code: DLsiteProductProbeFeature(
                workno=code, exists=code == "RJ01709662",
                probe_status="error" if scenario == "error" else "ok" if code == "RJ01709662" else "missing",
                maker_id="RG41088", release_date="2026-09-22", work_type="SOU", dl_count=1,
            )
            for code in codes
        }

    monkeypatch.setattr(service, "_load_cached_features_sync", cache)
    monkeypatch.setattr(service, "_upsert_cache_features_sync", lambda features: writes.extend(features))
    service.dlsite_service.probe_product_info_features = probe
    params = dict(
        circle_id="refresh-circle", maker_id="RG41088", release_date="2026-09-22",
        mode="deep", target_rjcodes=["RJ01709662"],
        force_refresh=scenario in {"force", "error", "incomplete", "unreleased"},
    )
    if scenario == "error":
        with pytest.raises(RuntimeError, match="未产出特典结论"):
            await service.probe_date(**params)
    else:
        result = await service.probe_date(**params)
        if scenario == "unreleased":
            assert result["skip_reason"] == "unreleased"
        elif scenario == "normal":
            assert result["parse_status"] == "cached_completed"
        elif scenario == "incomplete":
            assert result["incomplete"]
        else:
            assert "RJ01709680" in requests
            assert writes
            public.reset_mock()
            requests.clear()
            await service.probe_date(**{**params, "force_refresh": False})
            public.assert_not_awaited()
            assert requests == []
    states = {
        row.original_rjcode: row for row in db_session.query(DLsiteBonusOriginalProbeState).all()
    }
    assert states["RJ01709000"].checked_at == datetime(2000, 1, 1)
    if scenario in {"normal", "error", "incomplete", "unreleased"}:
        assert states["RJ01709662"].checked_at == datetime(2000, 1, 1)
    else:
        assert states["RJ01709662"].strategy_version == service.PROBE_STRATEGY_VERSION
        assert states["RJ01709662"].checked_at > datetime(2000, 1, 1)
    if scenario in {"normal", "unreleased"}:
        public.assert_not_awaited()
        assert requests == []


@pytest.mark.asyncio
async def test_force_refresh_requires_selected_originals():
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    with pytest.raises(ValueError, match="必须指定选中原作"):
        await service.probe_date(
            circle_id="circle", maker_id="RG41088", release_date="2026-09-22", force_refresh=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("force_refresh", [False, True])
async def test_start_api_reuses_same_active_scope(monkeypatch, force_refresh):
    from app.api.routes import (
        CircleCompletionBonusProbeStartRequest, _circle_bonus_probe_business_key,
        circle_completion_bonus_probe_start,
    )
    from app.core.task_engine import TaskStatus, TaskType

    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    monkeypatch.setattr(service, "resolve_circle_context", lambda *args: {
        "maker_id": "RG41088", "circle_id": "circle", "circle_name": "测试",
    })
    selected = {"2026-09-22": ["RJ01709662"]}
    key = _circle_bonus_probe_business_key(
        maker_id="RG41088", mode="deep", release_dates=list(selected),
        gap_limit=500, selected_rjcodes_by_date=selected,
    )
    task = SimpleNamespace(
        id="active-probe", type=TaskType.CIRCLE_COMPLETION_BONUS_PROBE,
        status=TaskStatus.PROCESSING, progress=10, current_step="探测中",
        task_metadata={"business_key": key},
    )
    submit = AsyncMock()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.get_dlsite_bonus_probe_service", lambda: service)
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: SimpleNamespace(
        get_all_tasks=lambda **kwargs: [task], submit=submit,
    ))
    result = await circle_completion_bonus_probe_start(CircleCompletionBonusProbeStartRequest(
        circle_id="circle", mode="deep", release_dates=list(selected),
        selected_rjcodes_by_date=selected, force_refresh=force_refresh,
    ))
    assert result["duplicate"]
    assert result["job_id"] == "active-probe"
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_api_rejects_force_refresh_without_selection(monkeypatch):
    from fastapi import HTTPException
    from app.api.routes import CircleCompletionBonusProbeStartRequest, circle_completion_bonus_probe_start

    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    monkeypatch.setattr(service, "resolve_circle_context", lambda *args: {"maker_id": "RG41088"})
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.get_dlsite_bonus_probe_service", lambda: service)
    with pytest.raises(HTTPException) as error:
        await circle_completion_bonus_probe_start(CircleCompletionBonusProbeStartRequest(
            circle_id="circle", release_dates=["2026-09-22"], force_refresh=True,
        ))
    assert error.value.status_code == 400
    assert "选中原作" in error.value.detail


@pytest.mark.asyncio
async def test_failed_upgrade_keeps_old_strategy_for_retry(db_session, monkeypatch):
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    service.dlsite_service = SimpleNamespace(_normalize_date_text=lambda value: value)
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(DLsiteBonusProbeDate(
        maker_id="RG41088", circle_id="circle", release_date="2026-09-22",
        gap_limit=500, mode="deep:date-range-v5", status="completed",
    ))
    db_session.commit()
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **kwargs: [])
    monkeypatch.setattr(service, "_load_public_worknos_for_date", AsyncMock(
        return_value=([], [], [], "date_page_error"),
    ))
    with pytest.raises(RuntimeError, match="未产出特典结论"):
        await service.probe_date(
            circle_id="circle", maker_id="RG41088", release_date="2026-09-22", mode="deep",
        )
    assert service._requires_strategy_refresh_sync(
        circle_id="circle", maker_id="RG41088", release_date="2026-09-22",
        gap_limit=500, mode="deep", target_rjcodes=[],
    )
