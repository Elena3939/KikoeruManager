import asyncio

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.dlsite_service import DLsiteProductProbeFeature
from app.models.database import (
    CircleWork,
    DLsiteBonusOriginalProbeState,
    DLsiteBonusProbeCache,
    DLsiteBonusProbeDate,
    DLsiteBonusProbeHitIndex,
    WorkMetadata,
)


def _service() -> DLsiteBonusProbeService:
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)

    class _FakeDLsiteService:
        def _normalize_date_text(self, value):
            return str(value or "").strip()

    service.dlsite_service = _FakeDLsiteService()
    return service


class _Row:
    def __init__(
        self,
        canonical_rjcode: str,
        display_rjcode: str = "",
        linked_rjcodes: list[str] | None = None,
        is_bonus_work: bool = False,
    ) -> None:
        self.canonical_rjcode = canonical_rjcode
        self.display_rjcode = display_rjcode
        self.linked_rjcodes = linked_rjcodes or []
        self.is_bonus_work = is_bonus_work


class _DateRow:
    def __init__(self, *, status: str, mode: str, probe_count: int) -> None:
        self.status = status
        self.mode = mode
        self.probe_count = probe_count


class _Meta:
    def __init__(
        self,
        rjcode: str,
        *,
        maker_id: str = "RG62878",
        release_date: str = "2025-06-28",
        is_bonus_work: bool = False,
    ) -> None:
        self.rjcode = rjcode
        self.maker_id = maker_id
        self.release_date = release_date
        self.is_bonus_work = is_bonus_work


def test_public_original_worknos_uses_canonical_only() -> None:
    service = _service()

    worknos = service._public_original_worknos_from_rows([
        _Row("RJ01569979", display_rjcode="RJ01591910", linked_rjcodes=["RJ01591910", "RJ01595776"]),
        _Row("RJ01569983", is_bonus_work=True),
    ])

    assert worknos == ["RJ01569979"]


def test_build_gap_candidates_adds_edge_window_for_single_public_work() -> None:
    service = _service()

    candidates, gap_count, budget_reached = service._build_gap_candidates(["RJ01591910"], 5)

    assert gap_count == 0
    assert budget_reached is False
    assert candidates == [
        "RJ01591905",
        "RJ01591906",
        "RJ01591907",
        "RJ01591908",
        "RJ01591909",
        "RJ01591911",
        "RJ01591912",
        "RJ01591913",
        "RJ01591914",
        "RJ01591915",
    ]


def test_build_gap_candidates_can_expand_circle_edge_window_for_far_bonus() -> None:
    service = _service()

    candidates, gap_count, budget_reached = service._build_gap_candidates(
        ["RJ01314197"],
        500,
        edge_window_limit=service.DEFAULT_CIRCLE_EDGE_WINDOW,
    )

    assert gap_count == 0
    assert budget_reached is False
    assert "RJ01315736" in candidates
    assert "RJ01315739" in candidates
    assert "RJ01316198" not in candidates


def test_build_gap_candidates_keeps_between_public_gap_and_edges() -> None:
    service = _service()

    candidates, gap_count, budget_reached = service._build_gap_candidates(
        ["RJ01574312", "RJ01574314"],
        2,
    )

    assert gap_count == 1
    assert budget_reached is False
    assert candidates == [
        "RJ01574310",
        "RJ01574311",
        "RJ01574313",
        "RJ01574315",
        "RJ01574316",
    ]


def test_build_gap_candidates_marks_large_between_gap_but_still_probes_edges() -> None:
    service = _service()

    candidates, gap_count, budget_reached = service._build_gap_candidates(
        ["RJ01570000", "RJ01570500"],
        10,
    )

    assert gap_count == 0
    assert budget_reached is True
    assert "RJ01570001" in candidates
    assert "RJ01570499" in candidates
    assert "RJ01570250" not in candidates


def test_build_range_candidates_uses_full_date_page_range() -> None:
    service = _service()

    candidates, range_count, budget_reached = service._build_range_candidates(
        ["RJ01416537", "RJ01416598"],
    )

    assert range_count == 60
    assert budget_reached is False
    assert "RJ01416572" in candidates
    assert "RJ01416536" not in candidates
    assert "RJ01416599" not in candidates


def test_build_range_candidates_covers_far_same_day_bonus() -> None:
    service = _service()

    candidates, range_count, budget_reached = service._build_range_candidates(
        ["RJ01297739", "RJ01314197", "RJ01318269"],
    )

    assert range_count == 20529
    assert budget_reached is False
    assert "RJ01315736" in candidates
    assert "RJ01315739" in candidates


def test_build_range_candidates_marks_insane_date_page_range() -> None:
    service = _service()

    candidates, range_count, budget_reached = service._build_range_candidates(
        ["RJ01000000", "RJ02000001"],
        range_limit=1000,
    )

    assert range_count == 1000000
    assert budget_reached is True
    assert candidates == []


def test_hidden_bonus_match_does_not_require_current_probe_date() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01569983",
        exists=True,
        maker_id="RG62878",
        release_date="2026-02-23",
        work_type="SOU",
        price=0,
        is_sale=False,
        is_free=True,
        is_oly=True,
        wishlist_count=0,
        is_hidden_bonus_audio=True,
    )

    assert service._hidden_bonus_matches(
        feature,
        maker_id="RG62878",
        release_date="2026-03-22",
    )


def test_cache_values_accept_bigint_probe_counts() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01000001",
        exists=True,
        price=2147483648,
        wishlist_count=2147483649,
    )

    values = service._cache_values_from_feature(feature)

    assert values["price"] == 2147483648
    assert values["wishlist_count"] == 2147483649


def test_cache_values_clamps_values_beyond_bigint() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01000001",
        exists=True,
        price=10**30,
        wishlist_count=-1,
    )

    values = service._cache_values_from_feature(feature)

    assert values["price"] == 0
    assert values["wishlist_count"] == 0


def test_completed_probe_date_row_reuses_current_strategy() -> None:
    service = _service()
    row = _DateRow(status="completed", mode="deep:date-range-v4", probe_count=160)

    assert service._can_reuse_completed_date_row(row, mode="deep")


def test_completed_probe_date_row_does_not_reuse_v3_strategy() -> None:
    service = _service()
    row = _DateRow(status="completed", mode="deep:date-gap-v3", probe_count=6000)

    assert not service._can_reuse_completed_date_row(row, mode="deep")


def test_completed_probe_date_row_does_not_reuse_legacy_full_date_gap_run() -> None:
    service = _service()
    row = _DateRow(status="completed", mode="deep", probe_count=3733)

    assert not service._can_reuse_completed_date_row(row, mode="deep")


def test_completed_probe_date_row_does_not_reuse_legacy_edge_only_run() -> None:
    service = _service()
    row = _DateRow(status="completed", mode="deep", probe_count=160)

    assert not service._can_reuse_completed_date_row(row, mode="deep")


def test_split_reusable_release_dates_uses_current_strategy(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        DLsiteBonusProbeDate(
            maker_id="RG62878",
            release_date="2025-06-28",
            gap_limit=500,
            mode="deep:date-range-v4",
            status="completed",
            probe_count=5800,
        )
    )
    db_session.add(
        DLsiteBonusProbeDate(
            maker_id="RG62878",
            release_date="2025-06-29",
            gap_limit=500,
            mode="deep:date-gap-v3",
            status="completed",
            probe_count=5800,
        )
    )
    db_session.commit()

    pending, skipped = service.split_reusable_release_dates(
        maker_id="RG62878",
        release_dates=["2025-06-28", "2025-06-29", "2025-06-30"],
        mode="deep",
        gap_limit=500,
    )

    assert skipped == ["2025-06-28"]
    assert pending == ["2025-06-29", "2025-06-30"]


def test_split_reusable_release_dates_keeps_date_when_original_state_pending(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        DLsiteBonusProbeDate(
            maker_id="RG62878",
            circle_id="circle-pending-state",
            release_date="2025-06-28",
            gap_limit=500,
            mode="deep:date-range-v4",
            status="completed",
            probe_count=5800,
        )
    )
    for rjcode in ["RJ01000001", "RJ01000002"]:
        db_session.add(
            CircleWork(
                id=f"pending-{rjcode}",
                circle_id="circle-pending-state",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG62878",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG62878",
                release_date="2025-06-28",
                is_bonus_work=False,
            )
        )
    db_session.add(
        DLsiteBonusOriginalProbeState(
            circle_id="circle-pending-state",
            maker_id="RG62878",
            original_rjcode="RJ01000001",
            release_date="2025-06-28",
            status="no_bonus",
            strategy_version=service.PROBE_STRATEGY_VERSION,
        )
    )
    db_session.commit()

    pending, skipped = service.split_reusable_release_dates(
        circle_id="circle-pending-state",
        maker_id="RG62878",
        release_dates=["2025-06-28"],
        mode="deep",
        gap_limit=500,
    )

    assert pending == ["2025-06-28"]
    assert skipped == []


def test_order_probe_release_dates_uses_min_original_rj(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        service,
        "_release_date_min_rj_map",
        lambda **_kwargs: {
            "2025-06-28": 10030,
            "2025-06-29": 10010,
            "2025-06-30": 10020,
        },
    )

    assert service._order_probe_release_dates(
        circle_id="circle-order",
        maker_id="RG62878",
        dates=["2025-06-30", "2025-06-28", "2025-06-29", "2025-07-01"],
    ) == ["2025-06-29", "2025-06-30", "2025-06-28", "2025-07-01"]


def test_list_indexed_release_dates_skips_no_bonus_original_state(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for rjcode, release_date in [("RJ01000001", "2025-06-28"), ("RJ01000002", "2025-06-29")]:
        db_session.add(
            CircleWork(
                id=f"work-{rjcode}",
                circle_id="circle-bonus-state",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG62878",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG62878",
                release_date=release_date,
                is_bonus_work=False,
            )
        )
    db_session.add(
        DLsiteBonusOriginalProbeState(
            circle_id="circle-bonus-state",
            maker_id="RG62878",
            original_rjcode="RJ01000001",
            release_date="2025-06-28",
            status="no_bonus",
            strategy_version=service.PROBE_STRATEGY_VERSION,
        )
    )
    db_session.commit()

    dates = service.list_indexed_release_dates("circle-bonus-state", "RG62878", mode="deep")

    assert dates == ["2025-06-29"]


def test_local_hit_index_reuses_minimal_bonus_hit(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-bonus-hit",
            maker_id="RG62878",
            release_date="2025-06-28",
            bonus_rjcode="RJ01416572",
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01416572",
            exists=True,
            probe_status="ok",
            maker_id="RG62878",
            release_date="2025-06-28",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="早期購入特典",
        )
    )
    db_session.commit()

    features = service._load_reusable_hidden_bonus_features(
        circle_id="circle-bonus-hit",
        maker_id="RG62878",
        release_date="2025-06-28",
    )

    assert [feature.workno for feature in features] == ["RJ01416572"]


def test_load_cached_features_reads_redis_overlay(monkeypatch) -> None:
    service = _service()

    class FakeRedis:
        def read_bonus_probe_cache_rows_sync(self, rjcodes):
            assert list(rjcodes) == ["RJ01000001"]
            return {
                "RJ01000001": {
                    "rjcode": "RJ01000001",
                    "exists": True,
                    "probe_status": "ok",
                    "maker_id": "RG62878",
                    "release_date": "2026-01-06",
                    "work_type": "SOU",
                    "price": 0,
                    "is_free": True,
                    "is_oly": True,
                    "is_hidden_bonus_audio": True,
                    "title": "Redis 特典缓存",
                }
            }

    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: FakeRedis())

    features = service._load_cached_features_sync(["RJ01000001"])

    assert features["RJ01000001"].title == "Redis 特典缓存"
    assert features["RJ01000001"].is_hidden_bonus_audio is True


def test_flush_bonus_probe_cache_dirty_once_writes_latest_row(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)

    class FakeRedis:
        def __init__(self):
            self.acked = []

        def read_bonus_probe_cache_dirty_sync(self, **_kwargs):
            return [
                (
                    "1-0",
                    {
                        "rjcode": "RJ01000001",
                        "exists": True,
                        "probe_status": "ok",
                        "maker_id": "RG62878",
                        "release_date": "2026-01-06",
                        "work_type": "SOU",
                        "price": 0,
                        "is_free": True,
                        "is_oly": True,
                        "is_hidden_bonus_audio": True,
                        "title": "旧标题",
                        "checked_at": "2026-01-06T00:00:00",
                        "created_at": "2026-01-06T00:00:00",
                        "updated_at": "2026-01-06T00:00:00",
                    },
                ),
                (
                    "2-0",
                    {
                        "rjcode": "RJ01000001",
                        "exists": True,
                        "probe_status": "ok",
                        "maker_id": "RG62878",
                        "release_date": "2026-01-06",
                        "work_type": "SOU",
                        "price": 0,
                        "is_free": True,
                        "is_oly": True,
                        "is_hidden_bonus_audio": True,
                        "title": "新标题",
                        "checked_at": "2026-01-06T00:00:01",
                        "created_at": "2026-01-06T00:00:00",
                        "updated_at": "2026-01-06T00:00:01",
                    },
                ),
                ("3-0", {"rjcode": ""}),
            ]

        def ack_bonus_probe_cache_dirty_sync(self, message_ids):
            self.acked = list(message_ids)
            return len(self.acked)

    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: fake_redis)

    result = service.flush_bonus_probe_cache_dirty_once(limit=10)

    row = db_session.query(DLsiteBonusProbeCache).filter(DLsiteBonusProbeCache.rjcode == "RJ01000001").one()
    assert result == {"read": 3, "written": 1, "acked": 3}
    assert row.title == "新标题"
    assert row.is_hidden_bonus_audio is True
    assert fake_redis.acked == ["1-0", "2-0", "3-0"]


def test_select_original_work_for_bonus_uses_same_date_and_nearest_rj() -> None:
    service = _service()
    far_original = _Row("RJ01410000")
    near_original = _Row("RJ01416537")
    other_date = _Row("RJ01416598")
    metadata_by_rj = {
        "RJ01410000": _Meta("RJ01410000"),
        "RJ01416537": _Meta("RJ01416537"),
        "RJ01416598": _Meta("RJ01416598", release_date="2025-06-29"),
    }

    selected = service._select_original_work_for_bonus(
        [far_original, near_original, other_date],
        metadata_by_rj,
        bonus_rjcode="RJ01416572",
        maker_id="RG62878",
        release_date="2025-06-28",
    )

    assert selected is near_original


def test_select_original_work_for_bonus_ignores_other_maker_and_bonus_rows() -> None:
    service = _service()
    other_maker = _Row("RJ01416537")
    bonus_row = _Row("RJ01416560", is_bonus_work=True)
    metadata_by_rj = {
        "RJ01416537": _Meta("RJ01416537", maker_id="RG99999"),
        "RJ01416560": _Meta("RJ01416560", is_bonus_work=True),
    }

    selected = service._select_original_work_for_bonus(
        [other_maker, bonus_row],
        metadata_by_rj,
        bonus_rjcode="RJ01416572",
        maker_id="RG62878",
        release_date="2025-06-28",
    )

    assert selected is None


@pytest.mark.asyncio
async def test_load_or_probe_features_counts_500_rj_batch_as_one_request(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(service, "_load_cached_features_sync", lambda _normalized: {})
    monkeypatch.setattr(service, "_upsert_cache_features_sync", lambda _features: None)

    async def fake_probe(rjcodes, *, concurrency):
        return {
            rjcode: DLsiteProductProbeFeature(workno=rjcode, exists=False, probe_status="missing")
            for rjcode in rjcodes
        }

    service.dlsite_service.probe_product_info_features = fake_probe
    rjcodes = [f"RJ{index:08d}" for index in range(1, 1201)]

    _features, cached_count, request_count = await service._load_or_probe_features(
        rjcodes,
        batch_size=500,
        concurrency=6,
    )

    assert cached_count == 0
    assert request_count == 3


@pytest.mark.asyncio
async def test_probe_circle_dates_uses_configured_date_workers(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        service,
        "resolve_circle_context",
        lambda circle_id, maker_id="": {
            "circle_id": circle_id,
            "circle_name": "测试社团",
            "maker_id": maker_id or "RG62878",
        },
    )
    monkeypatch.setattr(service, "_order_probe_release_dates", lambda **kwargs: list(kwargs["dates"]))

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_probe_date(**kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return {
            "release_date": kwargs["release_date"],
            "probe_count": 1,
            "request_count": 1,
            "hit_count": 0,
            "inserted_count": 0,
        }

    monkeypatch.setattr(service, "probe_date", fake_probe_date)

    result = await service.probe_circle_dates(
        circle_id="circle-six-workers",
        maker_id="RG62878",
        release_dates=[f"2025-06-{day:02d}" for day in range(1, 9)],
        concurrency=6,
    )

    assert max_active == 6
    assert result["date_count"] == 8
    assert [item["release_date"] for item in result["dates"]] == [f"2025-06-{day:02d}" for day in range(1, 9)]


@pytest.mark.asyncio
async def test_probe_circle_dates_keeps_running_after_local_date_failures(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        service,
        "resolve_circle_context",
        lambda circle_id, maker_id="": {
            "circle_id": circle_id,
            "circle_name": "测试社团",
            "maker_id": maker_id or "RG62878",
        },
    )
    monkeypatch.setattr(service, "_order_probe_release_dates", lambda **kwargs: list(kwargs["dates"]))

    async def fake_probe_date(**kwargs):
        release_date = kwargs["release_date"]
        if release_date in {"2025-06-02", "2025-06-04"}:
            raise RuntimeError(f"DLsite RJ 探测异常：{release_date}")
        await asyncio.sleep(0)
        return {
            "release_date": release_date,
            "probe_count": 1,
            "request_count": 1,
            "hit_count": 0,
            "inserted_count": 0,
        }

    monkeypatch.setattr(service, "probe_date", fake_probe_date)

    result = await service.probe_circle_dates(
        circle_id="circle-local-failures",
        maker_id="RG62878",
        release_dates=[f"2025-06-{day:02d}" for day in range(1, 6)],
        concurrency=3,
    )

    assert result["date_count"] == 5
    assert result["failed_count"] == 2
    assert result["failed_dates"] == ["2025-06-02", "2025-06-04"]
    assert result["incomplete_count"] == 2


@pytest.mark.asyncio
async def test_probe_circle_dates_cancels_workers_after_fatal_failure(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        service,
        "resolve_circle_context",
        lambda circle_id, maker_id="": {
            "circle_id": circle_id,
            "circle_name": "测试社团",
            "maker_id": maker_id or "RG62878",
        },
    )
    monkeypatch.setattr(service, "_order_probe_release_dates", lambda **kwargs: list(kwargs["dates"]))
    completed: list[str] = []

    async def fake_probe_date(**kwargs):
        release_date = kwargs["release_date"]
        if release_date == "2025-06-01":
            raise SQLAlchemyError("integer out of range")
        try:
            await asyncio.sleep(1)
            completed.append(release_date)
        except asyncio.CancelledError:
            raise
        return {
            "release_date": release_date,
            "probe_count": 1,
            "request_count": 1,
            "hit_count": 0,
            "inserted_count": 0,
        }

    monkeypatch.setattr(service, "probe_date", fake_probe_date)

    with pytest.raises(SQLAlchemyError):
        await service.probe_circle_dates(
            circle_id="circle-fatal-failure",
            maker_id="RG62878",
            release_dates=[f"2025-06-{day:02d}" for day in range(1, 5)],
            concurrency=4,
        )

    assert completed == []


@pytest.mark.asyncio
async def test_probe_circle_dates_cancels_workers_after_worker_cancel(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        service,
        "resolve_circle_context",
        lambda circle_id, maker_id="": {
            "circle_id": circle_id,
            "circle_name": "测试社团",
            "maker_id": maker_id or "RG62878",
        },
    )
    monkeypatch.setattr(service, "_order_probe_release_dates", lambda **kwargs: list(kwargs["dates"]))
    completed: list[str] = []
    cancelled: list[str] = []

    async def fake_probe_date(**kwargs):
        release_date = kwargs["release_date"]
        if release_date == "2025-06-01":
            await asyncio.sleep(0)
            raise asyncio.CancelledError()
        try:
            await asyncio.sleep(1)
            completed.append(release_date)
        except asyncio.CancelledError:
            cancelled.append(release_date)
            raise
        return {
            "release_date": release_date,
            "probe_count": 1,
            "request_count": 1,
            "hit_count": 0,
            "inserted_count": 0,
        }

    monkeypatch.setattr(service, "probe_date", fake_probe_date)

    with pytest.raises(asyncio.CancelledError):
        await service.probe_circle_dates(
            circle_id="circle-worker-cancel",
            maker_id="RG62878",
            release_dates=[f"2025-06-{day:02d}" for day in range(1, 5)],
            concurrency=4,
        )

    assert completed == []
    assert set(cancelled) == {"2025-06-02", "2025-06-03", "2025-06-04"}


@pytest.mark.asyncio
async def test_probe_date_error_does_not_write_original_no_bonus_state(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="error-original",
            circle_id="circle-error-probe",
            canonical_rjcode="RJ01000001",
            display_rjcode="RJ01000001",
            maker_id="RG62878",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01000001",
            maker_id="RG62878",
            release_date="2025-06-28",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000001"], ["RJ01000001"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        return {
            "RJ01000001": DLsiteProductProbeFeature(
                workno="RJ01000001",
                exists=False,
                probe_status="error",
                error_message="HTTP 429",
            )
        }, 0, 1

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    with pytest.raises(RuntimeError, match="未产出特典结论"):
        await service.probe_date(
            circle_id="circle-error-probe",
            maker_id="RG62878",
            release_date="2025-06-28",
            mode="deep",
        )

    states = db_session.query(DLsiteBonusOriginalProbeState).all()
    date_row = db_session.query(DLsiteBonusProbeDate).first()
    assert states == []
    assert date_row.status == "failed"


@pytest.mark.asyncio
async def test_probe_date_budget_reached_returns_incomplete_without_no_bonus_state(db_session, monkeypatch) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 2
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="budget-original",
            circle_id="circle-budget-probe",
            canonical_rjcode="RJ01000003",
            display_rjcode="RJ01000003",
            maker_id="RG62878",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01000003",
            maker_id="RG62878",
            release_date="2025-06-11",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000001", "RJ02000000"], ["RJ01000001", "RJ02000000"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        return {
            rjcode: DLsiteProductProbeFeature(
                workno=rjcode,
                exists=True,
                probe_status="ok",
                maker_id="RG62878",
                release_date="2025-06-11",
                work_type="SOU",
                price=770,
            )
            for rjcode in rjcodes
        }, 0, 1

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-budget-probe",
        maker_id="RG62878",
        release_date="2025-06-11",
        mode="deep",
        gap_limit=2,
        batch_size=10,
    )

    states = db_session.query(DLsiteBonusOriginalProbeState).all()
    date_row = db_session.query(DLsiteBonusProbeDate).first()
    assert states == []
    assert result["incomplete"] is True
    assert result["budget_reached"] is True
    assert date_row.status == "incomplete"


@pytest.mark.asyncio
async def test_probe_date_selected_rj_scope_uses_date_range_for_far_bonus(db_session, monkeypatch) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 6000
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-original",
            circle_id="circle-selected-probe",
            canonical_rjcode="RJ01000003",
            display_rjcode="RJ01000003",
            maker_id="RG62878",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01000003",
            maker_id="RG62878",
            release_date="2025-06-11",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000003"], ["RJ01000000", "RJ01005000"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_bonus = rjcode == "RJ01004000"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_bonus or rjcode in {"RJ01000000", "RJ01000003", "RJ01005000"},
                probe_status="ok" if is_bonus or rjcode in {"RJ01000000", "RJ01000003", "RJ01005000"} else "missing",
                maker_id="RG62878" if is_bonus or rjcode in {"RJ01000000", "RJ01000003", "RJ01005000"} else "",
                release_date="2025-06-11" if is_bonus or rjcode in {"RJ01000000", "RJ01000003", "RJ01005000"} else "",
                work_type="SOU" if is_bonus or rjcode in {"RJ01000000", "RJ01000003", "RJ01005000"} else "",
                price=0 if is_bonus else 770,
                is_free=is_bonus,
                is_oly=is_bonus,
                is_hidden_bonus_audio=is_bonus,
                title="Hidden Bonus" if is_bonus else "",
            )
        return features, 0, 1

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-selected-probe",
        maker_id="RG62878",
        release_date="2025-06-11",
        mode="deep",
        gap_limit=2,
        batch_size=10,
        target_rjcodes=["RJ01000003"],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).first()
    date_row = db_session.query(DLsiteBonusProbeDate).first()
    assert result["selected_scope"] is True
    assert result["target_rjcodes"] == ["RJ01000003"]
    assert result["budget_reached"] is False
    assert result["date_page_range_count"] == 4999
    assert result["hit_rjcodes"] == ["RJ01004000"]
    assert state.original_rjcode == "RJ01000003"
    assert state.status == "has_bonus"
    assert date_row.status == "completed"


@pytest.mark.asyncio
async def test_probe_date_reused_hit_index_still_continues_unfinished_scan(db_session, monkeypatch) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 20
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="reuse-index-original",
            circle_id="circle-reuse-index-probe",
            canonical_rjcode="RJ01000003",
            display_rjcode="RJ01000003",
            maker_id="RG62878",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01000003",
            maker_id="RG62878",
            release_date="2025-06-11",
            is_bonus_work=False,
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01000004",
            exists=True,
            probe_status="ok",
            maker_id="RG62878",
            release_date="2025-06-11",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="早期特典 1",
        )
    )
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-reuse-index-probe",
            maker_id="RG62878",
            release_date="2025-06-11",
            bonus_rjcode="RJ01000004",
        )
    )
    db_session.commit()

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000003"], ["RJ01000001", "RJ01000010"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_second_bonus = rjcode == "RJ01000008"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_second_bonus or rjcode in {"RJ01000001", "RJ01000003", "RJ01000010"},
                probe_status="ok" if is_second_bonus or rjcode in {"RJ01000001", "RJ01000003", "RJ01000010"} else "missing",
                maker_id="RG62878" if is_second_bonus or rjcode in {"RJ01000001", "RJ01000003", "RJ01000010"} else "",
                release_date="2025-06-11" if is_second_bonus or rjcode in {"RJ01000001", "RJ01000003", "RJ01000010"} else "",
                work_type="SOU" if is_second_bonus or rjcode in {"RJ01000001", "RJ01000003", "RJ01000010"} else "",
                price=0 if is_second_bonus else 770,
                is_free=is_second_bonus,
                is_oly=is_second_bonus,
                is_hidden_bonus_audio=is_second_bonus,
                title="早期特典 2" if is_second_bonus else "",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-reuse-index-probe",
        maker_id="RG62878",
        release_date="2025-06-11",
        mode="deep",
        gap_limit=2,
        batch_size=20,
        target_rjcodes=["RJ01000003"],
    )

    hit_codes = sorted(result["hit_rjcodes"])
    hit_index_codes = sorted(row.bonus_rjcode for row in db_session.query(DLsiteBonusProbeHitIndex).all())
    assert result["reused_hit_index"] is True
    assert hit_codes == ["RJ01000004", "RJ01000008"]
    assert hit_index_codes == ["RJ01000004", "RJ01000008"]
    assert result["probe_count"] > 0


@pytest.mark.asyncio
async def test_probe_date_counts_cached_hidden_bonus_candidate(db_session, monkeypatch) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 2
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 10
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="cached-original",
            circle_id="circle-cached-probe",
            canonical_rjcode="RJ01256625",
            display_rjcode="RJ01256625",
            maker_id="RG49556",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01256625",
            maker_id="RG49556",
            release_date="2024-10-31",
            is_bonus_work=False,
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01256633",
            exists=True,
            probe_status="ok",
            maker_id="RG49556",
            release_date="2024-10-31",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="28日間限定早期特典",
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01256625"], ["RJ01256625"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=rjcode == "RJ01256625",
                probe_status="ok" if rjcode == "RJ01256625" else "missing",
                maker_id="RG49556" if rjcode == "RJ01256625" else "",
                release_date="2024-10-31" if rjcode == "RJ01256625" else "",
                work_type="SOU" if rjcode == "RJ01256625" else "",
                price=770 if rjcode == "RJ01256625" else 0,
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-cached-probe",
        maker_id="RG49556",
        release_date="2024-10-31",
        mode="deep",
        gap_limit=10,
        batch_size=20,
        target_rjcodes=["RJ01256625"],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).first()
    bonus_row = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01256633").first()
    hit_index = db_session.query(DLsiteBonusProbeHitIndex).first()
    date_row = db_session.query(DLsiteBonusProbeDate).first()
    assert result["hit_rjcodes"] == ["RJ01256633"]
    assert result["hit_count"] == 1
    assert result["candidate_filter_stats"]["cached"] >= 1
    assert state.original_rjcode == "RJ01256625"
    assert state.status == "has_bonus"
    assert bonus_row is not None
    assert bonus_row.is_bonus_work is True
    assert hit_index.bonus_rjcode == "RJ01256633"
    assert date_row.status == "completed"


def test_split_candidate_shards_keeps_same_day_ranges_non_overlapping() -> None:
    service = _service()
    candidates = ["RJ01000005", "RJ01000001", "RJ01000003", "RJ01000002", "RJ01000004"]

    shards = service._split_candidate_shards(candidates, 2)

    assert [shard["rjcodes"] for shard in shards] == [
        ["RJ01000001", "RJ01000002"],
        ["RJ01000003", "RJ01000004"],
        ["RJ01000005"],
    ]
    assert [shard["range_key"] for shard in shards] == [
        "RJ01000001:RJ01000002",
        "RJ01000003:RJ01000004",
        "RJ01000005:RJ01000005",
    ]
    seen = [rjcode for shard in shards for rjcode in shard["rjcodes"]]
    assert seen == sorted(set(candidates))
    assert len(seen) == len(set(seen))


def test_exclude_unprobeable_candidates_skips_cached_active_and_error_cooldown(monkeypatch) -> None:
    service = _service()
    cached = {
        "RJ01000001": DLsiteProductProbeFeature(workno="RJ01000001", exists=True, probe_status="ok"),
        "RJ01000002": DLsiteProductProbeFeature(workno="RJ01000002", exists=False, probe_status="missing"),
        "RJ01000003": DLsiteProductProbeFeature(workno="RJ01000003", exists=False, probe_status="error"),
    }
    monkeypatch.setattr(service, "_load_cached_features_sync", lambda _values: cached)

    selected, stats = service._exclude_unprobeable_candidates(
        ["RJ01000001", "RJ01000002", "RJ01000003", "RJ01000004", "RJ01000005", "RJ01000005"],
        active_rjcodes=["RJ01000004"],
    )

    assert selected == ["RJ01000005"]
    assert stats == {"input": 5, "cached": 2, "active": 1, "cooldown": 1, "selected": 1}


@pytest.mark.asyncio
async def test_candidate_shard_lease_prevents_same_day_duplicate_ranges(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(service, "_load_cached_features_sync", lambda _values: {})
    candidates = [f"RJ0100000{index}" for index in range(1, 7)]

    first_shards, first_stats = await service._lease_candidate_shards(candidates, shard_size=2)
    second_shards, second_stats = await service._lease_candidate_shards(candidates, shard_size=2)

    assert [shard["range_key"] for shard in first_shards] == [
        "RJ01000001:RJ01000002",
        "RJ01000003:RJ01000004",
        "RJ01000005:RJ01000006",
    ]
    assert second_shards == []
    assert first_stats["leased"] == 6
    assert second_stats["active"] == 6
    assert second_stats["leased"] == 0

    await service._release_candidate_shards(first_shards)
    third_shards, third_stats = await service._lease_candidate_shards(candidates, shard_size=3)

    assert [shard["range_key"] for shard in third_shards] == [
        "RJ01000001:RJ01000003",
        "RJ01000004:RJ01000006",
    ]
    assert third_stats["leased"] == 6
    await service._release_candidate_shards(third_shards)
