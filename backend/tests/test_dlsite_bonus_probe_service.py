import asyncio

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.dlsite_service import DLsiteProductProbeFeature, DLsiteWorkSummary
from app.config.settings import BonusProbeConfig
from app.models.database import (
    CircleWork,
    DLsiteBonusOriginalProbeState,
    DLsiteBonusProbeCache,
    DLsiteBonusProbeDate,
    DLsiteBonusProbeHitIndex,
    WorkCanonicalLink,
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


def test_hidden_bonus_match_allows_bonus_registered_before_original_date() -> None:
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
    assert service._hidden_bonus_matches(
        feature,
        maker_id="RG62878",
        release_date="2026-02-23",
    )


def test_hidden_bonus_match_allows_non_audio_bonus_payload() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01234567",
        exists=True,
        maker_id="RG62878",
        release_date="2025-06-28",
        work_type="ICG",
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
        release_date="2025-06-28",
    )


def test_hidden_bonus_match_allows_missing_bonus_release_date() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01201745",
        exists=True,
        maker_id="RG68316",
        release_date="",
        work_type="SOU",
        price=0,
        is_sale=False,
        is_free=True,
        is_oly=True,
        wishlist_count=0,
        is_hidden_bonus_audio=True,
        title="♪早期限定4大特典♪",
    )

    assert service._hidden_bonus_matches(
        feature,
        maker_id="RG68316",
        release_date="2024-06-04",
    )
    assert service._selected_hidden_hit_matches_release_date(
        feature,
        release_date="2024-06-04",
    ) is True


@pytest.mark.parametrize(
    ("previous_original", "original_rjcode", "next_original", "bonus_rjcode", "release_date"),
    [
        ("RJ01134131", "RJ01149793", "RJ01165316", "RJ01158522", "2024-02-27"),
        ("RJ01149793", "RJ01165316", "RJ01178141", "RJ01171174", "2024-03-26"),
    ],
)
@pytest.mark.asyncio
async def test_probe_date_selected_rj_scope_finds_known_rg68316_bonus_pairs(
    db_session,
    monkeypatch,
    previous_original,
    original_rjcode,
    next_original,
    bonus_rjcode,
    release_date,
) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for rjcode, metadata_date in [
        (previous_original, "2024-01-14"),
        (original_rjcode, release_date),
        (next_original, "2024-04-23"),
    ]:
        db_session.add(
            CircleWork(
                id=f"known-original-{original_rjcode}-{rjcode}",
                circle_id="circle-known-rg68316",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG68316",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG68316",
                release_date=metadata_date,
                is_bonus_work=False,
            )
        )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return [original_rjcode], [original_rjcode], [original_rjcode, next_original], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return [next_original], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == original_rjcode
            is_bonus = rjcode == bonus_rjcode
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original or is_bonus,
                probe_status="ok" if is_original or is_bonus else "missing",
                maker_id="RG68316" if is_original or is_bonus else "",
                release_date=release_date if is_original or is_bonus else "",
                work_type="SOU" if is_original or is_bonus else "",
                price=0 if is_bonus else 1100,
                is_sale=not is_bonus,
                is_free=is_bonus,
                is_oly=is_bonus,
                wishlist_count=0,
                is_hidden_bonus_audio=is_bonus,
                title="【早期購入限定4大特典】" if is_bonus else "",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-known-rg68316",
        maker_id="RG68316",
        release_date=release_date,
        mode="deep",
        batch_size=500,
        concurrency=6,
        target_rjcodes=[original_rjcode],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).filter(
        DLsiteBonusOriginalProbeState.original_rjcode == original_rjcode,
    ).one()
    bonus_row = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == bonus_rjcode).one()
    hit_index = db_session.query(DLsiteBonusProbeHitIndex).filter(
        DLsiteBonusProbeHitIndex.bonus_rjcode == bonus_rjcode,
    ).one()
    assert result["selected_scope"] is True
    assert result["hit_rjcodes"] == [bonus_rjcode]
    assert result["probe_count"] > int(bonus_rjcode[2:]) - int(original_rjcode[2:])
    assert state.status == "has_bonus"
    assert bonus_row.is_bonus_work is True
    assert bonus_row.linked_rjcodes == [original_rjcode, bonus_rjcode]
    assert hit_index.release_date == release_date


def test_cache_values_keeps_values_beyond_integer_after_bigint_schema() -> None:
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


@pytest.mark.asyncio
async def test_load_public_worknos_for_date_uses_same_maker_date_page_boundaries(monkeypatch) -> None:
    service = _service()

    class FakeDLsiteService:
        def _normalize_date_text(self, value):
            return str(value or "").strip()

        async def list_new_work_summaries_by_date(self, release_date, max_pages=20):
            return [
                DLsiteWorkSummary(
                    workno="RJ01192535",
                    maker_id="RG68316",
                    release_date="2024-06-04",
                    work_type_code="SOU",
                ),
                DLsiteWorkSummary(
                    workno="RJ01195229",
                    maker_id="RG58328",
                    release_date="2024-06-04",
                    work_type_code="SOU",
                ),
                DLsiteWorkSummary(
                    workno="RJ01059487",
                    maker_id="RG60289",
                    release_date="2024-06-04",
                    work_type_code="ICG",
                ),
                DLsiteWorkSummary(
                    workno="RJ01207389",
                    maker_id="RG68316",
                    release_date="2024-06-19",
                    work_type_code="ICG",
                ),
            ], "ok"

    service.dlsite_service = FakeDLsiteService()
    monkeypatch.setattr(service, "_load_indexed_public_worknos", lambda *_args, **_kwargs: ["RJ01192535"])

    public_worknos, date_page_worknos, date_page_boundary_worknos, parse_status = await service._load_public_worknos_for_date(
        "RG68316",
        "RG68316",
        "2024-06-04",
    )

    assert parse_status == "ok"
    assert public_worknos == ["RJ01192535"]
    assert date_page_worknos == ["RJ01192535"]
    assert date_page_boundary_worknos == ["RJ01192535", "RJ01195229", "RJ01059487"]


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


def test_selected_hidden_hit_release_date_filters_history_bonus() -> None:
    service = _service()
    feature = DLsiteProductProbeFeature(
        workno="RJ01091762",
        exists=True,
        probe_status="ok",
        maker_id="RG68316",
        release_date="2023-08-27",
        work_type="SOU",
        price=0,
        is_sale=False,
        is_free=True,
        is_oly=True,
        wishlist_count=0,
        is_hidden_bonus_audio=True,
    )

    assert service._hidden_bonus_matches(feature, maker_id="RG68316", release_date="2024-06-04") is True
    assert service._selected_hidden_hit_matches_release_date(
        feature,
        release_date="2024-06-04",
    ) is False
    assert service._selected_hidden_hit_matches_release_date(
        feature,
        release_date="2024-06-04",
    ) is False
    assert service._selected_hidden_hit_matches_release_date(
        feature,
        release_date="2023-08-27",
    ) is True


def test_selected_target_cache_reuse_filters_other_release_date_history_hit(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-cache-original",
            circle_id="circle-selected-cache",
            canonical_rjcode="RJ01192535",
            display_rjcode="RJ01192535",
            maker_id="RG68316",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01192535",
            maker_id="RG68316",
            release_date="2024-06-04",
            is_bonus_work=False,
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01091762",
            exists=True,
            probe_status="ok",
            maker_id="RG68316",
            release_date="2023-08-27",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="历史发售日的特典",
        )
    )
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-selected-cache",
            maker_id="RG68316",
            release_date="2024-06-04",
            bonus_rjcode="RJ01091762",
        )
    )
    db_session.commit()

    features = service._load_reusable_hidden_bonus_features(
        circle_id="circle-selected-cache",
        maker_id="RG68316",
        release_date="2024-06-04",
        target_original_rjcodes=["RJ01192535"],
    )
    covered = service._selected_targets_with_bonus_hits(
        circle_id="circle-selected-cache",
        maker_id="RG68316",
        release_date="2024-06-04",
        target_rjcodes=["RJ01192535"],
        hidden_hits=[
            DLsiteProductProbeFeature(
                workno="RJ01091762",
                exists=True,
                probe_status="ok",
                maker_id="RG68316",
                release_date="2023-08-27",
                work_type="SOU",
                price=0,
                is_sale=False,
                is_free=True,
                is_oly=True,
                wishlist_count=0,
                is_hidden_bonus_audio=True,
            )
        ],
    )

    assert features == []
    assert covered == set()


def test_selected_target_cache_reuse_allows_same_release_date_far_hit(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-cache-far-original",
            circle_id="circle-selected-cache-far",
            canonical_rjcode="RJ01192535",
            display_rjcode="RJ01192535",
            maker_id="RG68316",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01192535",
            maker_id="RG68316",
            release_date="2024-06-04",
            is_bonus_work=False,
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01234567",
            exists=True,
            probe_status="ok",
            maker_id="RG68316",
            release_date="2024-06-04",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="同发售日远距离特典",
        )
    )
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-selected-cache-far",
            maker_id="RG68316",
            release_date="2024-06-04",
            bonus_rjcode="RJ01234567",
        )
    )
    db_session.commit()

    features = service._load_reusable_hidden_bonus_features(
        circle_id="circle-selected-cache-far",
        maker_id="RG68316",
        release_date="2024-06-04",
        target_original_rjcodes=["RJ01192535"],
        selected_anchor_candidates={"RJ01192534", "RJ01192536"},
    )
    covered = service._selected_targets_with_bonus_hits(
        circle_id="circle-selected-cache-far",
        maker_id="RG68316",
        release_date="2024-06-04",
        target_rjcodes=["RJ01192535"],
        hidden_hits=features,
        selected_anchor_candidates={"RJ01192534", "RJ01192536"},
    )

    assert [feature.workno for feature in features] == ["RJ01234567"]
    assert covered == {"RJ01192535"}


def test_selected_target_cache_reuse_ignores_explicit_link_to_other_original(db_session, monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for rjcode in ["RJ01149793", "RJ01165316"]:
        db_session.add(
            CircleWork(
                id=f"dirty-link-original-{rjcode}",
                circle_id="circle-dirty-link",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG68316",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG68316",
                release_date="2024-03-26",
                is_bonus_work=False,
            )
        )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01171174",
            exists=True,
            probe_status="ok",
            maker_id="RG68316",
            release_date="2024-03-26",
            work_type="SOU",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="旧脏链上的特典",
        )
    )
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-dirty-link",
            maker_id="RG68316",
            release_date="2024-03-26",
            bonus_rjcode="RJ01171174",
        )
    )
    db_session.add(
        WorkCanonicalLink(
            id="dirty-link-other-original",
            canonical_rjcode="RJ01165316",
            linked_rjcode="RJ01171174",
            link_type="bonus",
        )
    )
    db_session.commit()

    features = service._load_reusable_hidden_bonus_features(
        circle_id="circle-dirty-link",
        maker_id="RG68316",
        release_date="2024-03-26",
        target_original_rjcodes=["RJ01149793"],
    )
    covered = service._selected_targets_with_bonus_hits(
        circle_id="circle-dirty-link",
        maker_id="RG68316",
        release_date="2024-03-26",
        target_rjcodes=["RJ01149793"],
        hidden_hits=[
            DLsiteProductProbeFeature(
                workno="RJ01171174",
                exists=True,
                probe_status="ok",
                maker_id="RG68316",
                release_date="2024-03-26",
                work_type="SOU",
                price=0,
                is_sale=False,
                is_free=True,
                is_oly=True,
                wishlist_count=0,
                is_hidden_bonus_audio=True,
            )
        ],
    )

    assert features == []
    assert covered == set()


@pytest.mark.asyncio
async def test_probe_date_selected_scope_does_not_steal_bonus_linked_to_other_original(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for rjcode, release_date in [
        ("RJ01149793", "2024-03-26"),
        ("RJ01165316", "2024-03-26"),
        ("RJ01178141", "2024-04-23"),
    ]:
        db_session.add(
            CircleWork(
                id=f"probe-dirty-link-original-{rjcode}",
                circle_id="circle-probe-dirty-link",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG68316",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG68316",
                release_date=release_date,
                is_bonus_work=False,
            )
        )
    db_session.add(
        WorkCanonicalLink(
            id="probe-dirty-link-other-original",
            canonical_rjcode="RJ01165316",
            linked_rjcode="RJ01171174",
            link_type="bonus",
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01149793"], ["RJ01149793", "RJ01178141"], ["RJ01149793", "RJ01178141"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01190000"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == "RJ01149793"
            is_bonus = rjcode == "RJ01171174"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original or is_bonus,
                probe_status="ok" if is_original or is_bonus else "missing",
                maker_id="RG68316" if is_original or is_bonus else "",
                release_date="2024-03-26" if is_original or is_bonus else "",
                work_type="SOU" if is_original or is_bonus else "",
                price=0 if is_bonus else 1100,
                is_sale=not is_bonus,
                is_free=is_bonus,
                is_oly=is_bonus,
                wishlist_count=0,
                is_hidden_bonus_audio=is_bonus,
                title="【早期購入限定4大特典】" if is_bonus else "",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-probe-dirty-link",
        maker_id="RG68316",
        release_date="2024-03-26",
        mode="deep",
        batch_size=500,
        concurrency=6,
        target_rjcodes=["RJ01149793"],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).filter(
        DLsiteBonusOriginalProbeState.original_rjcode == "RJ01149793",
    ).one()
    stolen_bonus = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01171174").first()
    assert result["hit_rjcodes"] == []
    assert result["original_no_bonus_count"] == 1
    assert state.status == "no_bonus"
    assert stolen_bonus is None


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


def test_legacy_postgres_cache_reclassifies_hidden_bonus() -> None:
    service = _service()
    row = DLsiteBonusProbeCache(
        rjcode="RJ01201745",
        exists=True,
        probe_status="ok",
        maker_id="RG68316",
        release_date="",
        work_type="SOU",
        price=0,
        is_sale=False,
        is_free=True,
        is_oly=True,
        wishlist_count=0,
        is_hidden_bonus_audio=False,
        title="♪早期限定4大特典♪",
    )

    feature = service._feature_from_cache_row(row)

    assert feature.is_hidden_bonus_audio is True


def test_legacy_redis_cache_reclassifies_hidden_bonus() -> None:
    service = _service()

    feature = service._feature_from_cache_payload({
        "rjcode": "RJ01201745",
        "exists": True,
        "probe_status": "ok",
        "maker_id": "RG68316",
        "release_date": "",
        "work_type": "SOU",
        "price": 0,
        "is_sale": False,
        "is_free": True,
        "is_oly": True,
        "wishlist_count": 0,
        "is_hidden_bonus_audio": False,
        "title": "♪早期限定4大特典♪",
    })

    assert feature.is_hidden_bonus_audio is True


def test_cache_reclassification_preserves_raw_boolean_wishlist_semantics() -> None:
    service = _service()

    feature = service._feature_from_cache_payload({
        "rjcode": "RJ01201745",
        "exists": True,
        "probe_status": "ok",
        "maker_id": "RG68316",
        "price": 0,
        "is_sale": False,
        "is_free": True,
        "is_oly": True,
        "wishlist_count": 0,
        "is_hidden_bonus_audio": True,
        "raw_summary_json": {"raw_wishlist_count": False},
    })

    assert feature.is_hidden_bonus_audio is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"probe_status": "missing"}, False),
        ({"exists": False}, False),
        ({"price": 100}, False),
        ({"is_sale": True}, False),
        ({"is_free": False}, False),
        ({"is_oly": False}, False),
        ({"wishlist_count": 1}, False),
    ],
)
def test_legacy_cache_reclassification_keeps_non_bonus_false(overrides, expected) -> None:
    service = _service()
    payload = {
        "rjcode": "RJ01201745",
        "exists": True,
        "probe_status": "ok",
        "maker_id": "RG68316",
        "price": 0,
        "is_sale": False,
        "is_free": True,
        "is_oly": True,
        "wishlist_count": 0,
        "is_hidden_bonus_audio": True,
    }
    payload.update(overrides)

    feature = service._feature_from_cache_payload(payload)

    assert feature.is_hidden_bonus_audio is expected


@pytest.mark.asyncio
async def test_load_or_probe_features_uses_redis_overlay_before_http(monkeypatch) -> None:
    service = _service()
    http_calls: list[list[str]] = []
    dirty_payloads: list[list[str]] = []

    class FakeRedis:
        def read_bonus_probe_cache_rows_sync(self, rjcodes):
            return {
                rjcode: {
                    "rjcode": rjcode,
                    "exists": True,
                    "probe_status": "ok",
                    "maker_id": "RG68316",
                    "release_date": "2024-02-27",
                    "work_type": "SOU",
                    "price": 0,
                    "is_sale": False,
                    "is_free": True,
                    "is_oly": True,
                    "wishlist_count": 0,
                    "is_hidden_bonus_audio": True,
                    "title": "Redis 命中特典",
                }
                for rjcode in rjcodes
                if rjcode in {"RJ01158522", "RJ01158523"}
            }

        def write_bonus_probe_cache_dirty_sync(self, payloads):
            dirty_payloads.append([payload["rjcode"] for payload in payloads])
            return len(payloads)

    async def fake_probe(rjcodes, *, concurrency):
        http_calls.append(list(rjcodes))
        assert concurrency == 6
        return {
            rjcode: DLsiteProductProbeFeature(
                workno=rjcode,
                exists=False,
                probe_status="missing",
            )
            for rjcode in rjcodes
        }

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: FakeRedis())
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(service, "_cache_rows_by_rjcodes_sync", lambda _db, _rjcodes: [])
    monkeypatch.setattr(service.dlsite_service, "probe_product_info_features", fake_probe, raising=False)

    features, cached_count, request_count = await service._load_or_probe_features(
        ["RJ01158522", "RJ01158523", "RJ01158524"],
        batch_size=500,
        concurrency=6,
    )

    assert cached_count == 2
    assert request_count == 1
    assert http_calls == [["RJ01158524"]]
    assert dirty_payloads == [["RJ01158524"]]
    assert features["RJ01158522"].title == "Redis 命中特典"
    assert features["RJ01158524"].probe_status == "missing"


def test_cache_rows_by_rjcodes_sync_splits_large_in_batches(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(service, "_cache_lookup_batch_size", lambda: 1000)
    captured_batches: list[list[str]] = []

    class FakeQuery:
        def filter(self, condition):
            captured_batches.append(list(condition.right.value))
            return self

        def all(self):
            return []

    class FakeDb:
        def query(self, model):
            assert model is DLsiteBonusProbeCache
            return FakeQuery()

    rows = service._cache_rows_by_rjcodes_sync(
        FakeDb(),
        [f"RJ{index:08d}" for index in range(2500)],
    )

    assert rows == []
    assert [len(batch) for batch in captured_batches] == [1000, 1000, 500]
    assert captured_batches[0][0] == "RJ00000000"
    assert captured_batches[-1][-1] == "RJ00002499"


def test_cache_rows_by_rjcodes_sync_uses_temp_table_for_postgresql_large_lookup() -> None:
    service = _service()
    executed_sql: list[str] = []
    inserted_counts: list[int] = []
    from_statement_sql: list[str] = []

    class FakeDialect:
        name = "postgresql"

    class FakeBind:
        dialect = FakeDialect()

    class FakeConnection:
        def exec_driver_sql(self, sql, params=None):
            executed_sql.append(str(sql))
            if params is not None:
                inserted_counts.append(len(params))

    class FakeQuery:
        def from_statement(self, statement):
            from_statement_sql.append(str(statement))
            return self

        def all(self):
            return []

    class FakeDb:
        def get_bind(self):
            return FakeBind()

        def connection(self):
            return FakeConnection()

        def query(self, model):
            assert model is DLsiteBonusProbeCache
            return FakeQuery()

    rows = service._cache_rows_by_rjcodes_sync(
        FakeDb(),
        [f"RJ{index:08d}" for index in range(3500)],
    )

    assert rows == []
    assert executed_sql[0].startswith("CREATE TEMP TABLE tmp_bonus_probe_rjcodes_")
    assert inserted_counts == [3500]
    assert "JOIN tmp_bonus_probe_rjcodes_" in from_statement_sql[0]
    assert executed_sql[-1].startswith("DROP TABLE IF EXISTS tmp_bonus_probe_rjcodes_")


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


def test_flush_bonus_probe_cache_dirty_once_acks_failed_batch(monkeypatch) -> None:
    service = _service()

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
                        "title": "毒消息",
                    },
                )
            ]

        def ack_bonus_probe_cache_dirty_sync(self, message_ids):
            self.acked = list(message_ids)
            return len(self.acked)

    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: fake_redis)
    monkeypatch.setattr(service, "_upsert_cache_values_sync", lambda _rows: (_ for _ in ()).throw(RuntimeError("boom")))

    result = service.flush_bonus_probe_cache_dirty_once(limit=10)

    assert result == {"read": 1, "written": 0, "acked": 1, "failed": 1}
    assert fake_redis.acked == ["1-0"]


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
        "app.core.dlsite_bonus_probe_service.get_config",
        lambda: type("Config", (), {"bonus_probe": BonusProbeConfig()})(),
    )
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
async def test_probe_circle_dates_caps_product_info_concurrency(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(
        "app.core.dlsite_bonus_probe_service.get_config",
        lambda: type("Config", (), {"bonus_probe": BonusProbeConfig()})(),
    )
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
    seen_concurrency = []

    async def fake_probe_date(**kwargs):
        seen_concurrency.append(kwargs["concurrency"])
        return {
            "release_date": kwargs["release_date"],
            "probe_count": 1,
            "request_count": 1,
            "hit_count": 0,
            "inserted_count": 0,
        }

    monkeypatch.setattr(service, "probe_date", fake_probe_date)

    await service.probe_circle_dates(
        circle_id="circle-product-info-cap",
        maker_id="RG62878",
        release_dates=[f"2025-06-{day:02d}" for day in range(1, 7)],
        concurrency=6,
    )

    assert seen_concurrency
    assert set(seen_concurrency) == {1}

    seen_concurrency.clear()
    await service.probe_circle_dates(
        circle_id="circle-product-info-cap",
        maker_id="RG62878",
        release_dates=["2025-06-01", "2025-06-02", "2025-06-03"],
        concurrency=6,
    )

    assert set(seen_concurrency) == {2}

    seen_concurrency.clear()
    await service.probe_circle_dates(
        circle_id="circle-product-info-cap",
        maker_id="RG62878",
        release_dates=["2025-06-01"],
        concurrency=6,
    )

    assert seen_concurrency == [6]


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
        return ["RJ01000001"], ["RJ01000001"], ["RJ01000001"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01000001"], "ok"

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
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
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
        return ["RJ01000001", "RJ02000000"], ["RJ01000001", "RJ02000000"], ["RJ01000001", "RJ02000000"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ02000000"], "ok"

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
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
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
    service.DEFAULT_DATE_RANGE_LIMIT = 2
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
        return ["RJ01000003"], ["RJ01000000", "RJ01005000"], ["RJ01000000", "RJ01005000"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01005000"], "ok"

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
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
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
    assert result["date_page_range_limit"] is None
    assert result["date_page_range_unbounded"] is True
    assert result["date_page_range_count"] == 4996
    assert result["hit_rjcodes"] == ["RJ01004000"]
    assert state.original_rjcode == "RJ01000003"
    assert state.status == "has_bonus"
    assert date_row.status == "completed"


@pytest.mark.asyncio
async def test_probe_date_selected_rj_scope_runs_full_over_limit_range_before_no_bonus(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 2
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-no-bonus-original",
            circle_id="circle-selected-no-bonus-probe",
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
            release_date="2025年06月中旬",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000003"], ["RJ01000001", "RJ01000003", "RJ01000010"], ["RJ01000001", "RJ01000003", "RJ01000010"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01000010"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        public_rjcodes = {"RJ01000001", "RJ01000003", "RJ01000010"}
        features = {}
        for rjcode in rjcodes:
            is_public = rjcode in public_rjcodes
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_public,
                probe_status="ok" if is_public else "missing",
                maker_id="RG62878" if is_public else "",
                release_date="2025-06-11" if is_public else "",
                work_type="SOU" if is_public else "",
                price=770 if is_public else 0,
            )
        return features, 0, 1

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-selected-no-bonus-probe",
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
    assert result["budget_reached"] is False
    assert "incomplete" not in result
    assert result["date_page_range_limit"] is None
    assert result["date_page_range_unbounded"] is True
    assert result["date_page_range_count"] == 6
    assert result["hit_rjcodes"] == []
    assert result["original_no_bonus_count"] == 1
    assert state.original_rjcode == "RJ01000003"
    assert state.status == "no_bonus"
    assert date_row.status == "completed"


@pytest.mark.asyncio
async def test_probe_date_selected_rj_scope_uses_circle_neighbor_range_when_date_page_has_single_anchor(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 1
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    for rjcode, release_date in [
        ("RJ01186973", "2024-05-14"),
        ("RJ01192535", "2024-06-04"),
        ("RJ01203798", "2024-06-25"),
    ]:
        db_session.add(
            CircleWork(
                id=f"neighbor-{rjcode}",
                circle_id="circle-neighbor-probe",
                canonical_rjcode=rjcode,
                display_rjcode=rjcode,
                maker_id="RG68316",
                is_bonus_work=False,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=rjcode,
                maker_id="RG68316",
                release_date=release_date,
                is_bonus_work=False,
            )
        )
    db_session.commit()

    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01192535"], ["RJ01192535"], ["RJ01192535"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return [], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        public_rjcodes = {"RJ01192535"}
        for rjcode in rjcodes:
            is_bonus = rjcode == "RJ01201745"
            is_public = rjcode in public_rjcodes
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_bonus or is_public,
                probe_status="ok" if is_bonus or is_public else "missing",
                maker_id="RG68316" if is_bonus or is_public else "",
                release_date="2024-06-04" if is_public else "",
                work_type="ICG" if is_bonus else ("SOU" if is_public else ""),
                price=0 if is_bonus else 1100,
                is_free=is_bonus,
                is_oly=is_bonus,
                is_hidden_bonus_audio=is_bonus,
                wishlist_count=0,
                title="♪早期限定4大特典♪" if is_bonus else "",
            )
        return features, 0, 1

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-neighbor-probe",
        maker_id="RG68316",
        release_date="2024-06-04",
        mode="deep",
        batch_size=20000,
        target_rjcodes=["RJ01192535"],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).first()
    assert result["selected_scope"] is True
    assert result["date_page_range_count"] == 16824
    assert result["hit_rjcodes"] == ["RJ01201745"]
    assert state.original_rjcode == "RJ01192535"
    assert state.status == "has_bonus"


@pytest.mark.asyncio
async def test_probe_date_selected_release_date_range_finds_rj01647392_bonus(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-bonus-hint-rj01647392",
            circle_id="circle-rj01647392",
            canonical_rjcode="RJ01647392",
            display_rjcode="RJ01647392",
            maker_id="RG68316",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01647392",
            maker_id="RG68316",
            release_date="2026-06-30",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    probed_rjcodes = []
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])
    monkeypatch.setattr(service, "_load_cached_features_sync", lambda _rjcodes: {})

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01647392"], ["RJ01647392"], ["RJ420268", "RJ01022632", "RJ01647392", "RJ01662245"], "ok"

    async def fake_next_date_worknos(release_date):
        assert release_date == "2026-07-01"
        return ["RJ01103667", "RJ01664259"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        probed_rjcodes.extend(rjcodes)
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == "RJ01647392"
            is_bonus = rjcode in {"RJ01657203", "RJ01658547"}
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original or is_bonus,
                probe_status="ok" if is_original or is_bonus else "missing",
                maker_id="RG68316" if is_original or is_bonus else "",
                release_date="2026-06-30" if is_original or is_bonus else "",
                work_type="SOU" if is_original or is_bonus else "",
                price=0 if is_bonus else 1980,
                is_sale=is_original,
                is_free=is_bonus,
                is_oly=is_original or is_bonus,
                wishlist_count=0 if is_bonus else 4358,
                is_hidden_bonus_audio=is_bonus,
                title=(
                    "【早期購入限定500大特典】_01"
                    if rjcode == "RJ01657203"
                    else "【早期購入限定500大特典】_02"
                    if rjcode == "RJ01658547"
                    else "【7/9日まで 早期限定500大特典】原作"
                    if is_original
                    else ""
                ),
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-rj01647392",
        maker_id="RG68316",
        release_date="2026-06-30",
        mode="deep",
        gap_limit=2,
        batch_size=500,
        concurrency=6,
        target_rjcodes=["RJ01647392"],
    )

    state = db_session.query(DLsiteBonusOriginalProbeState).filter(
        DLsiteBonusOriginalProbeState.original_rjcode == "RJ01647392",
    ).one()
    assert result["selected_scope"] is True
    assert "RJ01657203" in probed_rjcodes
    assert "RJ01658547" in probed_rjcodes
    assert "RJ01022633" not in probed_rjcodes
    assert result["date_page_range_count"] == int("01664259") - int("01647392") - 1
    assert result["selected_probe_stopped_on_hit"] is False
    assert result["hit_rjcodes"] == ["RJ01657203", "RJ01658547"]
    assert state.status == "has_bonus"


@pytest.mark.asyncio
async def test_probe_date_selected_scope_continues_after_cached_bonus_cover(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-cached-cover-original",
            circle_id="circle-cached-cover-rj01647392",
            canonical_rjcode="RJ01647392",
            display_rjcode="RJ01647392",
            maker_id="RG68316",
            is_bonus_work=False,
            has_bonus=True,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01647392",
            maker_id="RG68316",
            release_date="2026-06-30",
            is_bonus_work=False,
            has_bonus=True,
        )
    )
    db_session.add(
        DLsiteBonusProbeCache(
            rjcode="RJ01657203",
            exists=True,
            probe_status="ok",
            maker_id="RG68316",
            release_date="2026-06-30",
            work_type="ICG",
            price=0,
            is_sale=False,
            is_free=True,
            is_oly=True,
            wishlist_count=0,
            is_hidden_bonus_audio=True,
            title="【早期購入限定500大特典】_01",
        )
    )
    db_session.add(
        DLsiteBonusProbeHitIndex(
            circle_id="circle-cached-cover-rj01647392",
            maker_id="RG68316",
            release_date="2026-06-30",
            bonus_rjcode="RJ01657203",
        )
    )
    db_session.add(
        WorkCanonicalLink(
            id="cached-cover-bonus-link",
            canonical_rjcode="RJ01647392",
            linked_rjcode="RJ01657203",
            link_type="bonus",
        )
    )
    db_session.commit()

    monkeypatch.setattr(service, "_load_cached_features_sync", lambda _rjcodes: {})

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01647392"], ["RJ01647392"], ["RJ01647392", "RJ01662245"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01664259"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == "RJ01647392"
            is_new_bonus = rjcode == "RJ01658547"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original or is_new_bonus,
                probe_status="ok" if is_original or is_new_bonus else "missing",
                maker_id="RG68316" if is_original or is_new_bonus else "",
                release_date="2026-06-30" if is_original or is_new_bonus else "",
                work_type="SOU" if is_original or is_new_bonus else "",
                price=0 if is_new_bonus else 1980,
                is_sale=is_original,
                is_free=is_new_bonus,
                is_oly=is_original or is_new_bonus,
                wishlist_count=0 if is_new_bonus else 4358,
                is_hidden_bonus_audio=is_new_bonus,
                title="【早期購入限定500大特典】_02" if is_new_bonus else "",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-cached-cover-rj01647392",
        maker_id="RG68316",
        release_date="2026-06-30",
        mode="deep",
        gap_limit=500,
        batch_size=500,
        concurrency=6,
        target_rjcodes=["RJ01647392"],
    )

    assert result["parse_status"] == "ok"
    assert result["selected_cache_covered"] is True
    assert result["hit_rjcodes"] == ["RJ01657203", "RJ01658547"]
    assert result["probe_count"] > 0


@pytest.mark.asyncio
async def test_selected_release_date_range_ignores_six_digit_targets() -> None:
    service = _service()

    candidates, range_count, missing_boundary = service._build_selected_release_date_range_candidates(
        ["RJ420268"],
        current_date_worknos=["RJ420268", "RJ01647392"],
        next_date_worknos=["RJ01664259"],
    )

    assert candidates == []
    assert range_count == 0
    assert missing_boundary is False


@pytest.mark.asyncio
async def test_probe_date_selected_scope_falls_back_when_next_date_boundary_missing(
    db_session,
    monkeypatch,
) -> None:
    service = _service()
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 2
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="selected-plain-rj01000003",
            circle_id="circle-plain-selected",
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

    class FakeRedis:
        def read_bonus_probe_cache_rows_sync(self, _rjcodes):
            return {}

    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: FakeRedis())
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000003"], ["RJ01000003"], ["RJ01000003"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return [], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == "RJ01000003"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original,
                probe_status="ok" if is_original else "missing",
                maker_id="RG62878" if is_original else "",
                release_date="2025-06-11" if is_original else "",
                work_type="SOU" if is_original else "",
                price=1100 if is_original else 0,
                is_sale=is_original,
                title="通常作品",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)

    result = await service.probe_date(
        circle_id="circle-plain-selected",
        maker_id="RG62878",
        release_date="2025-06-11",
        mode="deep",
        gap_limit=2,
        batch_size=500,
        concurrency=6,
        target_rjcodes=["RJ01000003"],
    )

    assert result["selected_scope"] is True
    assert result["raw_probe_count"] == 4
    assert result["probe_count"] == 4
    assert result["budget_reached"] is True
    assert result["hit_rjcodes"] == []


@pytest.mark.asyncio
async def test_probe_date_reused_hit_index_keeps_scanning_selected_scope_when_cache_covers_target(
    db_session,
    monkeypatch,
) -> None:
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
            release_date="2025年06月中旬",
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
    db_session.add(
        WorkCanonicalLink(
            id="reuse-index-bonus-link",
            canonical_rjcode="RJ01000003",
            linked_rjcode="RJ01000004",
            link_type="bonus",
        )
    )
    db_session.commit()

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01000003"], ["RJ01000003"], ["RJ01000003", "RJ01000008"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01000010"], "ok"

    async def fake_load_or_probe(rjcodes, **_kwargs):
        features = {}
        for rjcode in rjcodes:
            is_original = rjcode == "RJ01000003"
            is_new_bonus = rjcode == "RJ01000006"
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=is_original or is_new_bonus,
                probe_status="ok" if is_original or is_new_bonus else "missing",
                maker_id="RG62878" if is_original or is_new_bonus else "",
                release_date="2025-06-11" if is_original or is_new_bonus else "",
                work_type="SOU" if is_original or is_new_bonus else "",
                price=0 if is_new_bonus else 990,
                is_sale=is_original,
                is_free=is_new_bonus,
                is_oly=is_original or is_new_bonus,
                wishlist_count=0 if is_new_bonus else 120,
                is_hidden_bonus_audio=is_new_bonus,
                title="早期特典 2" if is_new_bonus else "通常作品",
            )
        return features, 0, 1 if rjcodes else 0

    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
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
    state = db_session.query(DLsiteBonusOriginalProbeState).filter(
        DLsiteBonusOriginalProbeState.original_rjcode == "RJ01000003",
    ).first()
    original_row = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000003").first()
    bonus_row = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000004").first()
    new_bonus_row = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000006").first()
    refreshed_metadata = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01000003").first()
    assert result["reused_hit_index"] is True
    assert result["selected_cache_covered"] is True
    assert result["parse_status"] == "ok"
    assert hit_codes == ["RJ01000004", "RJ01000006"]
    assert hit_index_codes == ["RJ01000004", "RJ01000006"]
    assert result["probe_count"] == 4
    assert result["raw_probe_count"] == 5
    assert result["candidate_filter_stats"]["cached"] == 1
    assert result["date_page_public_count"] == 1
    assert result["original_has_bonus_count"] == 1
    assert refreshed_metadata.release_date == "2025-06-11"
    assert state.status == "has_bonus"
    assert original_row.has_bonus is True
    assert bonus_row.linked_rjcodes == ["RJ01000003", "RJ01000004"]
    assert new_bonus_row.linked_rjcodes == ["RJ01000003", "RJ01000006"]


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

    class FakeRedis:
        def read_bonus_probe_cache_rows_sync(self, _rjcodes):
            return {}

    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: FakeRedis())
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01256625"], ["RJ01256625"], ["RJ01256625", "RJ01256636"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return [], "ok"

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
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
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
    assert result["selected_cache_covered"] is True
    assert result["candidate_filter_stats"]["cached"] == 1
    assert result["candidate_filter_stats"]["selected"] == 9
    assert result["raw_probe_count"] == 10
    assert result["probe_count"] == 9
    assert state.original_rjcode == "RJ01256625"
    assert state.status == "has_bonus"
    assert bonus_row is not None
    assert bonus_row.is_bonus_work is True
    assert hit_index.bonus_rjcode == "RJ01256633"
    assert date_row.status == "completed"


@pytest.mark.asyncio
async def test_probe_date_emits_candidate_total_before_probe_requests(db_session, monkeypatch) -> None:
    service = _service()
    service.DEFAULT_DATE_RANGE_LIMIT = 2
    service.DEFAULT_CIRCLE_EDGE_WINDOW = 10
    monkeypatch.setattr("app.core.dlsite_bonus_probe_service.SessionLocal", lambda: db_session)
    db_session.add(
        CircleWork(
            id="progress-original",
            circle_id="circle-progress-probe",
            canonical_rjcode="RJ01257000",
            display_rjcode="RJ01257000",
            maker_id="RG49556",
            is_bonus_work=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01257000",
            maker_id="RG49556",
            release_date="2024-10-31",
            is_bonus_work=False,
        )
    )
    db_session.commit()

    class FakeRedis:
        def read_bonus_probe_cache_rows_sync(self, _rjcodes):
            return {}

    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: FakeRedis())
    monkeypatch.setattr(service, "_load_reusable_hidden_bonus_features", lambda **_kwargs: [])

    async def fake_public_worknos(*_args, **_kwargs):
        return ["RJ01257000"], ["RJ01257000"], ["RJ01257000"], "ok"

    async def fake_next_date_worknos(*_args, **_kwargs):
        return ["RJ01257004"], "ok"

    async def fake_lease_candidate_shards(candidates, *, shard_size):
        assert candidates
        return [
            {
                "index": 0,
                "range_key": "RJ01257001:RJ01257003",
                "start_rjcode": "RJ01257001",
                "end_rjcode": "RJ01257003",
                "count": 3,
                "rjcodes": ["RJ01257001", "RJ01257002", "RJ01257003"],
            }
        ], {"input": len(candidates), "cached": 0, "active": 0, "cooldown": 0, "selected": 3, "leased": 3}

    async def fake_release_candidate_shards(_shards):
        return None

    async def fake_load_or_probe(rjcodes, *, progress_callback=None, **_kwargs):
        if progress_callback and rjcodes == ["RJ01257001", "RJ01257002", "RJ01257003"]:
            progress_callback(len(rjcodes), len(rjcodes))
        features = {}
        for rjcode in rjcodes:
            features[rjcode] = DLsiteProductProbeFeature(
                workno=rjcode,
                exists=rjcode == "RJ01257000",
                probe_status="ok" if rjcode == "RJ01257000" else "missing",
                maker_id="RG49556" if rjcode == "RJ01257000" else "",
                release_date="2024-10-31" if rjcode == "RJ01257000" else "",
                work_type="SOU" if rjcode == "RJ01257000" else "",
                price=770 if rjcode == "RJ01257000" else 0,
            )
        return features, 0, len(rjcodes)

    progress_events: list[dict] = []
    monkeypatch.setattr(service, "_load_public_worknos_for_date", fake_public_worknos)
    monkeypatch.setattr(service, "_load_date_page_boundary_worknos", fake_next_date_worknos)
    monkeypatch.setattr(service, "_load_or_probe_features", fake_load_or_probe)
    monkeypatch.setattr(service, "_lease_candidate_shards", fake_lease_candidate_shards)
    monkeypatch.setattr(service, "_release_candidate_shards", fake_release_candidate_shards)

    result = await service.probe_date(
        circle_id="circle-progress-probe",
        maker_id="RG49556",
        release_date="2024-10-31",
        mode="deep",
        gap_limit=10,
        batch_size=20,
        target_rjcodes=["RJ01257000"],
        probe_progress_callback=progress_events.append,
    )

    probe_events = [event for event in progress_events if event.get("probe_count")]
    assert result["probe_count"] == 3
    assert probe_events[0] == {
        "release_date": "2024-10-31",
        "checked_probe_count": 0,
        "probe_count": 3,
    }
    assert probe_events[-1]["checked_probe_count"] == 3
    assert probe_events[-1]["probe_count"] == 3


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
