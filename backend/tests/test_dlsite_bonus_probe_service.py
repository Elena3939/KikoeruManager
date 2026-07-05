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
