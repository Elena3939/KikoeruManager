from __future__ import annotations

from datetime import datetime

import pytest

from app.core import circle_completion_service as circle_module
from app.core import dlsite_bonus_probe_service as bonus_probe_module
from app.core.circle_completion_service import CircleCompletionService
from app.models.database import (
    CircleCatalog,
    CircleWork,
    DLsiteBonusOriginalProbeState,
    DLsiteBonusProbeDate,
    LibraryOwnedWork,
    WorkCanonicalLink,
    WorkMetadata,
)


@pytest.fixture
def service(db_session, monkeypatch: pytest.MonkeyPatch) -> CircleCompletionService:
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "_dlsite_bonus_probe_service", None)
    return CircleCompletionService()


def _add_work(
    db_session,
    *,
    circle_id: str,
    canonical: str,
    title: str,
    owned: bool = False,
    asmr: bool = False,
    release_date: str = "2024-01-01",
    lang: str = "JPN",
) -> None:
    db_session.add(
        CircleWork(
            id=f"{circle_id}-{canonical}",
            circle_id=circle_id,
            canonical_rjcode=canonical,
            display_rjcode=canonical,
            title=title,
            maker_id="RGPAGE",
            maker_name="分页社团",
            source_mask="dlsite",
            linked_rjcodes=[canonical],
            has_dlsite=True,
            has_asmr_one=asmr,
            asmr_available_rjcode=canonical if asmr else None,
            image_url=f"https://img.dlsite.jp/modpub/images2/work/doujin/RJ999000/{canonical}_img_main.jpg",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
    )
    db_session.add(
        WorkCanonicalLink(
            id=f"link-{circle_id}-{canonical}",
            canonical_rjcode=canonical,
            linked_rjcode=canonical,
            link_type="original",
            lang=lang,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode=canonical,
            work_name=title,
            maker_name="分页社团",
            release_date=release_date,
            cvs=["CV A"],
            cached_at=datetime(2024, 1, 1),
            expires_at=datetime(2099, 1, 1),
        )
    )
    if owned:
        db_session.add(
            LibraryOwnedWork(
                canonical_rjcode=canonical,
                owned_rjcodes=[canonical],
                primary_folder_path=f"/library/{canonical}",
                library_id="default-local",
                folder_count=1,
                folder_size=1024,
                file_count=3,
                owned_paths=[f"/library/{canonical}"],
                has_local_subtitles=True,
                subtitle_file_count=1,
                subtitle_dir=f"/library/{canonical}/subtitles",
            )
        )


def _seed_circle(db_session) -> str:
    circle_id = "circle_paged_view"
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="分页社团",
            circle_name_normalized="分页社团",
            source_mask="dlsite,kikoeru",
            last_indexed_at=datetime(2024, 1, 1),
        )
    )
    _add_work(db_session, circle_id=circle_id, canonical="RJ01000001", title="Owned Work", owned=True, asmr=True, release_date="2023-01-01")
    _add_work(db_session, circle_id=circle_id, canonical="RJ01000002", title="Downloadable Work", owned=False, asmr=True, release_date="2024-02-01")
    _add_work(db_session, circle_id=circle_id, canonical="RJ01000003", title="No Source Work", owned=False, asmr=False, release_date="2025-03-01")
    db_session.commit()
    return circle_id


@pytest.mark.asyncio
async def test_summary_and_paged_works_match_legacy_counts(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)

    summary = await service.build_circle_completion_summary(circle_id)
    legacy = await service.build_circle_completion_view(circle_id)

    assert summary["owned_count"] == legacy["owned_count"] == 1
    assert summary["missing_count"] == legacy["missing_count"] == 2
    assert summary["downloadable_count"] == legacy["downloadable_count"] == 1
    assert "works" not in summary
    assert len(legacy["works"]) == 3


@pytest.mark.asyncio
async def test_paged_missing_works_and_work_codes(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)

    page = await service.list_circle_completion_works(circle_id, tab="missing", page=1, page_size=1, sort="release_asc")

    assert page["total"] == 2
    assert page["page_count"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["canonical_rjcode"] == "RJ01000002"
    assert "owned_paths" not in page["items"][0]
    assert "source_compare" not in page["items"][0]

    codes = await service.list_circle_completion_work_codes(circle_id, tab="missing", sort="release_asc")
    assert codes["canonical_rjcodes"] == ["RJ01000002", "RJ01000003"]
    assert codes["downloadable_rjcodes"] == ["RJ01000002"]
    assert codes["requested_rjcodes"]["RJ01000002"][0] == "RJ01000002"

    row_with_bonus = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000002").first()
    row_with_bonus.has_bonus = True
    db_session.add(
        DLsiteBonusProbeDate(
            maker_id="RGPAGE",
            release_date="2025-03-01",
            gap_limit=500,
            mode="deep:date-range-v4",
            status="completed",
        )
    )
    db_session.add(
        DLsiteBonusOriginalProbeState(
            circle_id=circle_id,
            maker_id="RGPAGE",
            original_rjcode="RJ01000003",
            release_date="2025-03-01",
            status="no_bonus",
            strategy_version="date-range-v4",
        )
    )
    db_session.commit()
    service.invalidate_completion_view_cache(circle_id)
    probe_codes = await service.list_circle_completion_work_codes(circle_id, tab="missing", sort="release_asc")
    assert probe_codes["has_bonus_rjcodes"] == ["RJ01000002"]
    assert probe_codes["no_bonus_rjcodes"] == ["RJ01000003"]
    assert probe_codes["completed_bonus_probe_dates"] == ["2025-03-01"]

    without_dl_only = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        include_dl_only=False,
        page=1,
        page_size=10,
    )
    assert without_dl_only["total"] == 1
    assert [item["canonical_rjcode"] for item in without_dl_only["items"]] == ["RJ01000002"]

    missing_location = await service.locate_circle_completion_work(
        circle_id,
        rjcode="RJ01000003",
        tab="missing",
        page_size=1,
        sort="release_asc",
    )
    assert missing_location["matched"] is True
    assert missing_location["page"] == 2
    assert missing_location["canonical_rjcode"] == "RJ01000003"

    owned_location = await service.locate_circle_completion_work(
        circle_id,
        rjcode="RJ01000001",
        tab="owned",
        page_size=10,
    )
    assert owned_location["matched"] is True
    assert owned_location["page"] == 1
    assert owned_location["canonical_rjcode"] == "RJ01000001"


@pytest.mark.asyncio
async def test_release_sort_uses_original_canonical_release_date(
    service: CircleCompletionService,
    db_session,
) -> None:
    circle_id = "circle_original_release_sort"
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="原作排序社团",
            circle_name_normalized="原作排序社团",
            source_mask="dlsite",
            last_indexed_at=datetime(2026, 7, 4),
        )
    )
    for index, (canonical, display, original_date, display_date, title) in enumerate([
        ("RJ01010001", "RJ02010001", "2024-01-01", "2026-01-01", "翻译版日期更晚"),
        ("RJ01010002", "RJ02010002", "2025-01-01", "2025-06-01", "原作日期更晚"),
    ], start=1):
        db_session.add(
            CircleWork(
                id=f"orig-sort-{index}",
                circle_id=circle_id,
                canonical_rjcode=canonical,
                display_rjcode=display,
                title=title,
                maker_id="RGSORT",
                maker_name="原作排序社团",
                source_mask="dlsite",
                linked_rjcodes=[canonical, display],
                has_dlsite=True,
                has_asmr_one=True,
                asmr_available_rjcode=display,
                image_url=f"https://img.dlsite.jp/modpub/images2/work/doujin/RJ01010000/{canonical}_img_main.jpg",
                created_at=datetime(2026, 7, 4),
                updated_at=datetime(2026, 7, 4),
            )
        )
        for linked_rjcode, link_type, lang in [
            (canonical, "original", "JPN"),
            (display, "translation", "CHI_HANS"),
        ]:
            db_session.add(
                WorkCanonicalLink(
                    id=f"link-sort-{linked_rjcode}",
                    canonical_rjcode=canonical,
                    linked_rjcode=linked_rjcode,
                    link_type=link_type,
                    lang=lang,
                )
            )
        db_session.add(
            WorkMetadata(
                rjcode=canonical,
                work_name=f"{title} 原作",
                maker_name="原作排序社团",
                release_date=original_date,
                cached_at=datetime(2026, 7, 4),
                expires_at=datetime(2099, 1, 1),
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=display,
                work_name=f"{title} 简中",
                maker_name="原作排序社团",
                release_date=display_date,
                cached_at=datetime(2026, 7, 4),
                expires_at=datetime(2099, 1, 1),
            )
        )
    db_session.commit()

    page = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        page=1,
        page_size=10,
        sort="release_desc",
    )

    assert [item["canonical_rjcode"] for item in page["items"]] == ["RJ01010002", "RJ01010001"]
    assert [item["release_date"] for item in page["items"]] == ["2025-06-01", "2026-01-01"]
    assert [item["original_release_date"] for item in page["items"]] == ["2025-01-01", "2024-01-01"]


@pytest.mark.asyncio
async def test_compare_tab_returns_flat_payload(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)

    page = await service.list_circle_completion_works(circle_id, tab="compare", compare_filter="asmr_one", page=1, page_size=10)

    assert page["total"] == 2
    assert {item["workRjcode"] for item in page["items"]} == {"RJ01000001", "RJ01000002"}
    assert all("sourceCompare" in item for item in page["items"])


@pytest.mark.asyncio
async def test_work_search_locates_circle_by_rj_and_linked_rj(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)
    linked = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000002").one()
    linked.linked_rjcodes = ["RJ01000002", "RJ02000002"]
    db_session.commit()

    by_canonical = await service.search_circle_completion_works("RJ01000002")
    assert by_canonical[0]["circle_id"] == circle_id
    assert by_canonical[0]["canonical_rjcode"] == "RJ01000002"
    assert by_canonical[0]["circle_name"] == "分页社团"

    by_linked = await service.search_circle_completion_works("RJ02000002")
    assert by_linked[0]["circle_id"] == circle_id
    assert by_linked[0]["canonical_rjcode"] == "RJ01000002"


@pytest.mark.asyncio
async def test_owned_original_subtitle_state_survives_translation_variant_priority(
    service: CircleCompletionService,
    db_session,
) -> None:
    circle_id = "circle_original_subtitle"
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="うこんちゃん☆かんぱにぃ",
            circle_name_normalized="うこんちゃんかんぱにぃ",
            source_mask="dlsite,kikoeru",
            last_indexed_at=datetime(2026, 6, 19),
        )
    )
    db_session.add(
        CircleWork(
            id="owned-subtitle-RJ01609723",
            circle_id=circle_id,
            canonical_rjcode="RJ01609723",
            display_rjcode="RJ01609723",
            title="ざこちんぽをおまんこで容赦なく搾精するなかよし双子ちびサキュバス",
            maker_id="RG70169",
            maker_name="うこんちゃん☆かんぱにぃ",
            source_mask="dlsite,kikoeru",
            linked_rjcodes=["RJ01609723", "RJ01625472", "RJ01625473"],
            has_dlsite=True,
            has_asmr_one=False,
            image_url="https://img.dlsite.jp/modpub/images2/work/doujin/RJ01610000/RJ01609723_img_main.jpg",
            created_at=datetime(2026, 6, 19),
            updated_at=datetime(2026, 6, 19),
        )
    )
    for linked_rjcode, link_type, lang in [
        ("RJ01609723", "original", "JPN"),
        ("RJ01625472", "translation", "CHI_HANS"),
        ("RJ01625473", "translation", "CHI_HANT"),
    ]:
        db_session.add(
            WorkCanonicalLink(
                id=f"link-subtitle-{linked_rjcode}",
                canonical_rjcode="RJ01609723",
                linked_rjcode=linked_rjcode,
                link_type=link_type,
                lang=lang,
            )
        )
        db_session.add(
            WorkMetadata(
                rjcode=linked_rjcode,
                work_name=f"{linked_rjcode} title",
                maker_name="うこんちゃん☆かんぱにぃ",
                release_date="2026-05-03",
                cvs=["山田じぇみ子"],
                cached_at=datetime(2026, 6, 19),
                expires_at=datetime(2099, 1, 1),
            )
        )
    db_session.add(
        LibraryOwnedWork(
            canonical_rjcode="RJ01609723",
            owned_rjcodes=["RJ01609723", "RJ01625472", "RJ01625473"],
            primary_folder_path="/library_amsr/うこんちゃん☆かんぱにぃ/[うこんちゃん☆かんぱにぃ][RJ01609723](CV 山田じぇみ子)",
            library_id="default-local",
            folder_count=1,
            folder_size=1024,
            file_count=11,
            owned_paths=[
                "/library_amsr/うこんちゃん☆かんぱにぃ/[うこんちゃん☆かんぱにぃ][RJ01609723](CV 山田じぇみ子)",
            ],
            has_local_subtitles=True,
            subtitle_file_count=8,
            subtitle_dir="/library_amsr/うこんちゃん☆かんぱにぃ/[うこんちゃん☆かんぱにぃ][RJ01609723](CV 山田じぇみ子)/subtitles",
        )
    )
    db_session.commit()

    summary = await service.build_circle_completion_summary(circle_id)
    assert summary["owned_stats"]["subtitle"] == 1
    assert summary["owned_stats"]["original"] == 0

    subtitle_page = await service.list_circle_completion_works(
        circle_id,
        tab="owned",
        owned_filter="subtitle",
        page=1,
        page_size=10,
    )
    assert subtitle_page["total"] == 1
    item = subtitle_page["items"][0]
    assert item["canonical_rjcode"] == "RJ01609723"
    assert item["subtitle_present"] is True
    assert item["owned_variant"]["rjcode"] == "RJ01609723"
    assert item["owned_variant"]["group_key"] == "original"

    legacy = await service.build_circle_completion_view(circle_id)
    assert legacy["works"][0]["owned_variant"]["rjcode"] == "RJ01609723"
    assert legacy["works"][0]["owned_variant"]["group_key"] == "original"


@pytest.mark.asyncio
async def test_missing_work_keeps_translation_variant_priority(
    service: CircleCompletionService,
    db_session,
) -> None:
    circle_id = "circle_missing_translation"
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="翻译优先社团",
            circle_name_normalized="翻译优先社团",
            source_mask="dlsite",
            last_indexed_at=datetime(2026, 6, 19),
        )
    )
    db_session.add(
        CircleWork(
            id="missing-trans-RJ01609723",
            circle_id=circle_id,
            canonical_rjcode="RJ01609723",
            display_rjcode="RJ01625472",
            title="简体显示作品",
            maker_id="RG70169",
            maker_name="翻译优先社团",
            source_mask="dlsite",
            linked_rjcodes=["RJ01609723", "RJ01625472", "RJ01625473"],
            has_dlsite=True,
            has_asmr_one=True,
            asmr_available_rjcode="RJ01625472",
            image_url="https://img.dlsite.jp/modpub/images2/work/doujin/RJ01610000/RJ01609723_img_main.jpg",
            created_at=datetime(2026, 6, 19),
            updated_at=datetime(2026, 6, 19),
        )
    )
    for linked_rjcode, link_type, lang in [
        ("RJ01609723", "original", "JPN"),
        ("RJ01625472", "translation", "CHI_HANS"),
        ("RJ01625473", "translation", "CHI_HANT"),
    ]:
        db_session.add(
            WorkCanonicalLink(
                id=f"link-missing-{linked_rjcode}",
                canonical_rjcode="RJ01609723",
                linked_rjcode=linked_rjcode,
                link_type=link_type,
                lang=lang,
            )
        )
    db_session.commit()

    page = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        page=1,
        page_size=10,
    )

    assert page["total"] == 1
    item = page["items"][0]
    assert item["owned"] is False
    assert item["display_rjcode"] == "RJ01625472"
    assert item["preferred_variant"]["rjcode"] == "RJ01625472"
    assert item["preferred_variant"]["group_key"] == "simplified"
    assert item["download_plan"]["rjcode"] == "RJ01625472"
