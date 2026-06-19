from __future__ import annotations

from datetime import datetime

import pytest

from app.core import circle_completion_service as circle_module
from app.core.circle_completion_service import CircleCompletionService
from app.models.database import CircleCatalog, CircleWork, LibraryOwnedWork, WorkCanonicalLink, WorkMetadata


@pytest.fixture
def service(db_session, monkeypatch: pytest.MonkeyPatch) -> CircleCompletionService:
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: db_session)
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

    without_dl_only = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        include_dl_only=False,
        page=1,
        page_size=10,
    )
    assert without_dl_only["total"] == 1
    assert [item["canonical_rjcode"] for item in without_dl_only["items"]] == ["RJ01000002"]


@pytest.mark.asyncio
async def test_compare_tab_returns_flat_payload(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)

    page = await service.list_circle_completion_works(circle_id, tab="compare", compare_filter="asmr_one", page=1, page_size=10)

    assert page["total"] == 2
    assert {item["workRjcode"] for item in page["items"]} == {"RJ01000001", "RJ01000002"}
    assert all("sourceCompare" in item for item in page["items"])
