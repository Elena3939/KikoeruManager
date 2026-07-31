from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from app.core import circle_completion_service as circle_module
from app.core import dlsite_bonus_probe_service as bonus_probe_module
from app.core.circle_image_cache_service import CircleImageCacheService
from app.core.circle_completion_service import CircleCompletionService
from app.core.dlsite_service import LinkedWork
from app.models.database import (
    CircleCatalog,
    CircleWork,
    DLsiteBonusOriginalProbeState,
    DLsiteBonusProbeDate,
    LibraryOwnedWork,
    WorkCanonicalLink,
    WorkMetadata,
)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def incr(self, key):
        value = int(self.store.get(key) or 0) + 1
        self.store[key] = str(value)
        return value

    def scan_iter(self, match=None, count=None):
        if not match:
            yield from list(self.store.keys())
            return
        prefix = str(match).rstrip('*')
        for key in list(self.store.keys()):
            if str(key).startswith(prefix):
                yield key

    def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        return 1 if existed else 0


class _FakeRedisService:
    def __init__(self) -> None:
        self.client_obj = _FakeRedisClient()

    def is_enabled(self):
        return True

    def client(self, *, required=False):
        return self.client_obj

    def key(self, *parts):
        return ':'.join(str(part) for part in parts if str(part))

    def set_json(self, module, type_name, item_id, payload, *, ttl_seconds=None):
        self.client_obj.set(self.key(module, type_name, item_id), json.dumps(payload, ensure_ascii=False, default=str))
        return True

    def get_json(self, module, type_name, item_id):
        raw = self.client_obj.get(self.key(module, type_name, item_id))
        return json.loads(raw) if raw else None


class _BrokenRedisService(_FakeRedisService):
    def client(self, *, required=False):
        raise RuntimeError('redis down')

    def set_json(self, module, type_name, item_id, payload, *, ttl_seconds=None):
        raise RuntimeError('redis down')

    def get_json(self, module, type_name, item_id):
        raise RuntimeError('redis down')


@pytest.fixture(autouse=True)
def _disable_real_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: _BrokenRedisService())


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


def test_circle_image_cache_uses_real_image_rjcode_for_local_urls(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path

    remote_url = "https://img.dlsite.jp/modpub/images2/work/doujin/RJ01202000/RJ01201316_img_sam.jpg"

    assert image_cache.extract_image_rjcode(remote_url) == "RJ01201316"
    assert image_cache.get_local_url("RJ01201316", variant="list", allow_missing=True) == "/api/circle-completion/cover/RJ01201316_sam.jpg"
    assert image_cache.resolve_filename("../RJ01201316_sam.jpg") is None
    assert image_cache.resolve_filename("RJ01201316_sam.jpg") == tmp_path / "RJ01201316_sam.jpg"
    assert image_cache._candidate_source_urls("RJ01201316", "list")[0].endswith("/RJ01202000/RJ01201316_img_sam.jpg")
    assert image_cache.cache_rjcode_for_url(remote_url, "RJ01999999") == "RJ01201316"


@pytest.mark.asyncio
async def test_resolve_canonical_rj_expands_cached_translation_chain(
    service: CircleCompletionService,
    db_session,
) -> None:
    db_session.add_all([
        WorkCanonicalLink(
            id="cached-original",
            canonical_rjcode="RJ01673480",
            linked_rjcode="RJ01673480",
            link_type="translation",
            lang="JPN",
            evidence_source="translation_info",
            evidence_status="verified",
        ),
        WorkCanonicalLink(
            id="cached-english",
            canonical_rjcode="RJ01673480",
            linked_rjcode="RJ01673617",
            link_type="translation",
            lang="ENG",
            evidence_source="translation_info",
            evidence_status="verified",
        ),
        WorkCanonicalLink(
            id="cached-dirty-bonus",
            canonical_rjcode="RJ01673617",
            linked_rjcode="RJ01678200",
            link_type="bonus",
            lang="",
            evidence_source="dlsite_bonus_probe",
            evidence_status="verified",
        ),
    ])
    db_session.commit()

    payload = await service.resolve_canonical_rj("RJ01673617")

    assert payload["canonical_rjcode"] == "RJ01673480"
    assert payload["linked_rjcodes"] == ["RJ01673480", "RJ01673617", "RJ01678200"]


@pytest.mark.asyncio
async def test_resolve_canonical_rj_ignores_legacy_unverified_cache(
    service: CircleCompletionService,
    db_session,
    monkeypatch,
) -> None:
    db_session.add(
        WorkCanonicalLink(
            id="legacy-unverified-link",
            canonical_rjcode="RJ01673480",
            linked_rjcode="RJ01673617",
            link_type="translation",
            lang="ENG",
        )
    )
    db_session.commit()

    async def unverified_links(_rjcode, refresh=False):
        return {
            "RJ01673617": LinkedWork(
                workno="RJ01673617",
                work_type="unknown",
                lang="UNKNOWN",
            )
        }

    monkeypatch.setattr(
        service.dlsite_service,
        "get_linked_works",
        unverified_links,
    )

    payload = await service.resolve_canonical_rj("RJ01673617")

    assert payload["canonical_rjcode"] == "RJ01673617"
    assert payload["linked_rjcodes"] == ["RJ01673617"]
    assert payload["evidence_status"] == "unverified"


def test_circle_image_cache_restores_historical_display_alias(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    legacy_path = tmp_path / "RJ01099999.jpg"
    legacy_path.write_bytes(b"legacy-cover")

    restored = image_cache.restore_from_legacy_alias("RJ01012345", ["RJ01099999"])

    assert restored == tmp_path / "RJ01012345.jpg"
    assert restored.read_bytes() == b"legacy-cover"
    assert legacy_path.read_bytes() == b"legacy-cover"


@pytest.mark.asyncio
async def test_circle_image_cache_bounds_on_demand_failure_wait(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    image_cache.ON_DEMAND_TOTAL_TIMEOUT_SECONDS = 0.01
    image_cache._candidate_source_urls = lambda *_args: ["https://img.dlsite.jp/example.jpg"]

    async def slow_download(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        return False, "ReadTimeout", True

    image_cache._download_with_outcome = slow_download

    assert await asyncio.wait_for(
        image_cache.ensure_local_for_filename("RJ01012345.jpg"),
        timeout=0.1,
    ) is None
    assert image_cache._is_in_failure_cooldown("RJ01012345", "card")


@pytest.mark.asyncio
async def test_circle_image_cache_queue_wait_does_not_consume_download_timeout(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    image_cache.DEFAULT_CONCURRENCY = 1
    image_cache.ON_DEMAND_TOTAL_TIMEOUT_SECONDS = 0.01
    image_cache._candidate_source_urls = lambda *_args: ["https://img.dlsite.jp/example.jpg"]

    async def write_cover(rjcode, _url, *, variant):
        path = image_cache.get_local_path(rjcode, variant)
        path.write_bytes(b"cover")
        return True, "", False

    image_cache._download_with_outcome = write_cover
    gate = image_cache._get_download_semaphore()
    await gate.acquire()

    task = asyncio.create_task(image_cache.ensure_local_for_filename("RJ01012345.jpg"))
    await asyncio.sleep(0.03)
    assert not task.done(), "等待下载名额时不能提前耗尽单张网络超时"

    gate.release()
    result = await asyncio.wait_for(task, timeout=0.1)
    assert result == tmp_path / "RJ01012345.jpg"


@pytest.mark.asyncio
async def test_circle_image_cache_background_ensure_is_deduplicated(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    release = asyncio.Event()
    calls = 0

    async def slow_ensure(_filename, **_kwargs):
        nonlocal calls
        calls += 1
        await release.wait()
        return None

    image_cache.ensure_local_for_filename = slow_ensure

    first = image_cache.schedule_ensure_for_filename("RJ01012345.jpg")
    second = image_cache.schedule_ensure_for_filename("RJ01012345.jpg")
    await asyncio.sleep(0)

    assert first is not None
    assert second is first
    assert calls == 1

    release.set()
    await first
    assert image_cache._background_download_tasks == {}


@pytest.mark.asyncio
async def test_circle_image_cache_does_not_redownload_existing_file(tmp_path) -> None:
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    download_count = 0

    async def write_cover(rjcode, _url, *, variant):
        nonlocal download_count
        download_count += 1
        image_cache.get_local_path(rjcode, variant).write_bytes(b"cover")
        return True, "", False

    image_cache._download_with_outcome = write_cover
    source_url = "https://img.dlsite.jp/modpub/images2/work/doujin/RJ01013000/RJ01012345_img_main.jpg"

    assert await image_cache.download_one("RJ01012345", source_url)
    assert await image_cache.download_one("RJ01012345", source_url)
    assert download_count == 1


@pytest.mark.asyncio
async def test_paged_works_cover_cache_url_uses_image_file_rjcode(service: CircleCompletionService, db_session, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    circle_id = "circle_cover_cache"
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="封面缓存社团",
            circle_name_normalized="封面缓存社团",
            source_mask="dlsite",
            last_indexed_at=datetime(2024, 1, 1),
        )
    )
    _add_work(db_session, circle_id=circle_id, canonical="RJ01012345", title="Cover Work", asmr=True)
    db_session.flush()
    row = db_session.query(CircleWork).filter(CircleWork.circle_id == circle_id).first()
    row.display_rjcode = "RJ01099999"
    row.image_url = "https://img.dlsite.jp/modpub/images2/work/doujin/RJ01013000/RJ01012345_img_main.jpg"
    db_session.commit()
    image_cache = CircleImageCacheService()
    image_cache._cache_dir = tmp_path
    (tmp_path / "RJ01099999.jpg").write_bytes(b"legacy-cover")
    monkeypatch.setattr(circle_module, "get_circle_image_cache_service", lambda: image_cache)

    page = await service.list_circle_completion_works(circle_id, tab="missing", page=1, page_size=10, view_mode="card")

    assert page["items"][0]["display_rjcode"] == "RJ01099999"
    assert page["items"][0]["thumb_image_url"] == "/api/circle-completion/cover/RJ01012345_sam.jpg"
    assert page["items"][0]["image_url"] == "/api/circle-completion/cover/RJ01012345.jpg"
    assert page["items"][0]["remote_image_url"].endswith("/RJ01013000/RJ01012345_img_main_240x240.jpg")
    alias_task = service._cover_alias_restore_tasks.get(circle_id)
    if alias_task is not None:
        await alias_task
    assert (tmp_path / "RJ01012345.jpg").read_bytes() == b"legacy-cover"


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

    selection_codes = await service.list_circle_completion_work_codes(
        circle_id,
        tab="missing",
        sort="release_asc",
        selection_only=True,
    )
    assert selection_codes["canonical_rjcodes"] == ["RJ01000002", "RJ01000003"]
    assert selection_codes["downloadable_rjcodes"] == ["RJ01000002"]
    assert "requested_rjcodes" not in selection_codes
    assert "release_dates_by_rjcode" not in selection_codes

    db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01000003").update({"release_date": "2025年03月下旬"})
    db_session.commit()
    service.invalidate_completion_view_cache(circle_id)
    service._metadata_cache.pop("RJ01000003", None)

    async def fake_get_product_info(rjcode: str, **_kwargs):
        if rjcode == "RJ01000003":
            return {"product": {"regist_date": "2025-03-31 00:00:00"}}
        return None

    service.dlsite_service.get_product_info = fake_get_product_info
    codes = await service.list_circle_completion_work_codes(circle_id, tab="missing", sort="release_asc")
    refreshed_metadata = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01000003").first()
    assert codes["release_dates_by_rjcode"]["RJ01000003"] == "2025-03-31"
    assert refreshed_metadata.release_date == "2025-03-31"
    assert service._metadata_cache["RJ01000003"]["release_date"] == "2025-03-31"

    row_with_bonus = db_session.query(CircleWork).filter(CircleWork.canonical_rjcode == "RJ01000002").first()
    row_with_bonus.has_bonus = True
    db_session.add(
        DLsiteBonusProbeDate(
            maker_id="RGPAGE",
            release_date="2025-03-31",
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
            release_date="2025-03-31",
            status="no_bonus",
            strategy_version="date-range-v4",
        )
    )
    db_session.commit()
    service.invalidate_completion_view_cache(circle_id)
    probe_codes = await service.list_circle_completion_work_codes(circle_id, tab="missing", sort="release_asc")
    assert probe_codes["has_bonus_rjcodes"] == []
    assert probe_codes["no_bonus_rjcodes"] == ["RJ01000003"]
    assert probe_codes["completed_bonus_probe_dates"] == ["2025-03-31"]

    db_session.add(
        CircleWork(
            id=f"{circle_id}-RJ01000002-bonus",
            circle_id=circle_id,
            canonical_rjcode="RJ01000004",
            display_rjcode="RJ01000004",
            title="Downloadable Work Bonus",
            maker_id="RGPAGE",
            maker_name="分页社团",
            source_mask="dlsite",
            linked_rjcodes=["RJ01000002", "RJ01000004"],
            has_dlsite=True,
            has_asmr_one=True,
            asmr_available_rjcode="RJ01000004",
            image_url="https://img.dlsite.jp/modpub/images2/work/doujin/RJ999000/RJ01000004_img_main.jpg",
            is_bonus_work=True,
            has_bonus=False,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode="RJ01000004",
            work_name="Downloadable Work Bonus",
            maker_name="分页社团",
            release_date="2024-02-01",
            cvs=["CV A"],
            cached_at=datetime(2024, 1, 1),
            expires_at=datetime(2099, 1, 1),
        )
    )
    db_session.commit()
    service.invalidate_completion_view_cache(circle_id)
    probe_codes = await service.list_circle_completion_work_codes(circle_id, tab="missing", sort="release_asc")
    assert probe_codes["has_bonus_rjcodes"] == ["RJ01000002"]
    assert probe_codes["no_bonus_rjcodes"] == ["RJ01000003"]
    assert probe_codes["completed_bonus_probe_dates"] == ["2025-03-31"]

    has_bonus_page = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        status_filters="has_early_bonus",
        page=1,
        page_size=10,
        sort="release_asc",
    )
    assert [item["canonical_rjcode"] for item in has_bonus_page["items"]] == ["RJ01000002"]
    assert has_bonus_page["status_filter_counts"]["missing"]["has_early_bonus"] == 1

    no_bonus_page = await service.list_circle_completion_works(
        circle_id,
        tab="missing",
        status_filters="no_early_bonus",
        page=1,
        page_size=10,
        sort="release_asc",
    )
    assert [item["canonical_rjcode"] for item in no_bonus_page["items"]] == ["RJ01000003"]
    assert no_bonus_page["status_filter_counts"]["missing"]["no_early_bonus"] == 1

    owned_bonus_page = await service.list_circle_completion_works(
        circle_id,
        tab="owned",
        status_filters="has_early_bonus",
        page=1,
        page_size=10,
    )
    assert owned_bonus_page["items"] == []

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
async def test_preview_batch_download_falls_back_to_asmr_code_without_requested_mapping(
    service: CircleCompletionService,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    circle_id = _seed_circle(db_session)
    requested_codes = []

    async def fake_build_download_plan(*, rjcode: str, **_kwargs):
        requested_codes.append(rjcode)
        return {"selectable_resources": [], "summary": {}}

    class FakeLibraryManager:
        def list_libraries(self):
            return []

    monkeypatch.setattr(service.asmr_resource_service, "build_download_plan", fake_build_download_plan)
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: FakeLibraryManager())

    result = await service.preview_batch_download(circle_id, ["RJ01000002"], requested_rjcodes={})

    assert requested_codes == ["RJ01000002"]
    assert result["planned_count"] == 1
    assert result["plans"][0]["resolved_rjcode"] == "RJ01000002"


@pytest.mark.asyncio
async def test_completion_state_singleflight_reuses_one_cold_build(service: CircleCompletionService, db_session) -> None:
    circle_id = _seed_circle(db_session)
    original_builder = service._build_completion_view_state_uncached
    calls = 0

    def counted_builder(value):
        nonlocal calls
        calls += 1
        return original_builder(value)

    service._build_completion_view_state_uncached = counted_builder
    summary, page = await asyncio.gather(
        service.build_circle_completion_summary(circle_id),
        service.list_circle_completion_works(circle_id, tab="missing", page=1, page_size=2),
    )

    assert summary["missing_count"] == 2
    assert page["total"] == 2
    assert calls == 1


@pytest.mark.asyncio
async def test_completion_cache_uses_redis_l2_across_service_instances(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "_dlsite_bonus_probe_service", None)
    fake_redis = _FakeRedisService()
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: fake_redis)
    circle_id = _seed_circle(db_session)

    first = CircleCompletionService()
    await first.build_circle_completion_summary(circle_id)

    second = CircleCompletionService()

    def fail_builder(value):
        raise AssertionError("state should be restored from Redis")

    second._build_completion_view_state_uncached = fail_builder
    page = await second.list_circle_completion_works(circle_id, tab="missing", page=1, page_size=2, sort="release_asc")

    assert page["total"] == 2
    assert [item["canonical_rjcode"] for item in page["items"]] == ["RJ01000002", "RJ01000003"]

    version_key = fake_redis.key("circle-completion", "version", second._completion_cache_scope(circle_id))
    assert fake_redis.client_obj.get(version_key) is None
    second.invalidate_completion_view_cache(circle_id)
    assert fake_redis.client_obj.get(version_key) == "1"


@pytest.mark.asyncio
async def test_completion_cache_invalidates_query_alias_when_circle_id_changes(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bonus_probe_module, "_dlsite_bonus_probe_service", None)
    fake_redis = _FakeRedisService()
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: fake_redis)
    circle_id = _seed_circle(db_session)

    by_name = CircleCompletionService()
    first = await by_name.build_circle_completion_summary("分页社团")
    assert first["missing_count"] == 2

    row = db_session.query(LibraryOwnedWork).filter(LibraryOwnedWork.canonical_rjcode == "RJ01000002").first()
    assert row is None
    db_session.add(
        LibraryOwnedWork(
            canonical_rjcode="RJ01000002",
            owned_rjcodes=["RJ01000002"],
            primary_folder_path="/library/RJ01000002",
            library_id="default-local",
            folder_count=1,
            folder_size=2048,
            file_count=5,
            owned_paths=["/library/RJ01000002"],
        )
    )
    db_session.commit()

    invalidator = CircleCompletionService()
    invalidator.invalidate_completion_view_cache(circle_id)

    refreshed = CircleCompletionService()
    summary = await refreshed.build_circle_completion_summary("分页社团")
    assert summary["missing_count"] == 1
    assert fake_redis.client_obj.get(fake_redis.key("circle-completion", "version", circle_id)) == "1"
    assert fake_redis.client_obj.get(fake_redis.key("circle-completion", "version", "分页社团")) == "1"


@pytest.mark.asyncio
async def test_completion_cache_falls_back_when_redis_unavailable(service: CircleCompletionService, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    circle_id = _seed_circle(db_session)
    monkeypatch.setattr("app.core.redis_service.get_redis_service", lambda: _BrokenRedisService())

    summary = await service.build_circle_completion_summary(circle_id)
    page = await service.list_circle_completion_works(circle_id, tab="missing", page=1, page_size=10)

    assert summary["missing_count"] == 2
    assert page["total"] == 2


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
                evidence_source="language_editions",
                evidence_status="verified",
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
                evidence_source="language_editions",
                evidence_status="verified",
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
