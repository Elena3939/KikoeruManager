import os
from contextlib import asynccontextmanager

import pytest

from app.core.asmr_resource_service import ASMRResourceService


class FakeASMRService:
    def __init__(self):
        self.work_info_calls = 0
        self.track_calls = 0

    async def fetch_work_info(self, rjcode):
        self.work_info_calls += 1
        return {
            "id": 1,
            "title": f"作品 {rjcode}",
            "circle": "Circle",
            "tags": ["asmr"],
        }

    async def fetch_track_list(self, rjcode):
        self.track_calls += 1
        return [{"title": "root"}]

    def _flatten_tracks(self, tracks):
        del tracks
        return [
            {
                "title": "01 Main Track.mp3",
                "path": "Audio/01 Main Track.mp3",
                "size": 1024,
                "media_download_url": "https://example.com/audio.mp3",
                "hash": "0123456789abcdef0123456789abcdef",
            },
            {
                "title": "01 Main Track.lrc",
                "path": "Subtitles/01 Main Track.lrc",
                "size": 128,
                "media_download_url": "https://example.com/subtitle.lrc",
                "hash": "",
            },
            {
                "title": "Cover.jpg",
                "path": "Cover.jpg",
                "size": 256,
                "media_download_url": "https://example.com/cover.jpg",
                "hash": "",
            },
        ]


def create_service():
    return ASMRResourceService(asmr_service=FakeASMRService())


def test_classify_resource_and_language_detection():
    service = create_service()

    assert service.classify_resource_type("track01.flac") == "audio"
    assert service.classify_resource_type("track01.ass") == "subtitle"
    assert service.classify_resource_type("cover.webp") == "cover"
    assert service.detect_language("RJ123456 简中字幕") == "zh"
    assert service.detect_language("RJ123456 Japanese subtitle") == "ja"


def test_detect_local_pair_issues_uses_name_and_track_number():
    service = create_service()
    local_resources = [
        {
            "resource_type": "audio",
            "file_name": "01 Main Track.mp3",
            "relative_path": "Audio/01 Main Track.mp3",
            "normalized_name": service.normalize_name("01 Main Track.mp3"),
            "track_number": 1,
            "duration_seconds": 120.0,
            "size_bytes": 1024,
        },
        {
            "resource_type": "subtitle",
            "file_name": "02 Side Track.lrc",
            "relative_path": "Subtitles/02 Side Track.lrc",
            "normalized_name": service.normalize_name("02 Side Track.lrc"),
            "track_number": 2,
            "size_bytes": 128,
        },
    ]

    issues = service._detect_local_pair_issues(local_resources)

    assert len(issues["missing_subtitles_for_audio"]) == 1
    assert issues["missing_subtitles_for_audio"][0]["audio_name"] == "01 Main Track.mp3"
    assert len(issues["orphan_subtitles_without_audio"]) == 1
    assert issues["orphan_subtitles_without_audio"][0]["subtitle_name"] == "02 Side Track.lrc"


def test_retry_download_metadata_reuses_cache_and_keeps_other_failures(tmp_path):
    service = create_service()
    download_root = tmp_path / "RJ123456_original"
    download_root.mkdir()
    session = {
        "local_download_root": str(download_root),
        "statistics": {"download_root": str(tmp_path / "stale")},
        "failure_summary": {
            "failed_resources": [
                {"relative_path": "audio/01.wav", "reason": "断流"},
                {"relative_path": "audio/02.wav", "reason": "断流"},
            ]
        },
    }

    metadata = service._build_retry_download_metadata(session, {"audio/01.wav"})

    assert metadata["download_root"] == str(download_root)
    assert metadata["session_selected_resource_count"] == 0
    assert metadata["remaining_failed_resources"] == [
        {"relative_path": "audio/02.wav", "reason": "断流"}
    ]


def test_retry_download_metadata_rejects_missing_cache(tmp_path):
    service = create_service()

    with pytest.raises(ValueError, match="原下载缓存目录不存在"):
        service._build_retry_download_metadata(
            {
                "local_download_root": str(tmp_path / "missing"),
                "statistics": {},
                "failure_summary": {},
            },
            {"audio/01.wav"},
        )


@pytest.mark.anyio
async def test_build_download_plan_marks_existing_and_missing_resources(monkeypatch):
    service = create_service()
    monkeypatch.setattr(service, "_upsert_resource_records", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "scan_local_resources",
        lambda folder_path: [
            {
                "resource_type": "audio",
                "file_name": "01 Main Track.mp3",
                "relative_path": "Audio/01 Main Track.mp3",
                "normalized_name": service.normalize_name("01 Main Track.mp3"),
                "track_number": 1,
                "duration_seconds": 120.0,
                "size_bytes": 1024,
                "language": "",
            }
        ] if folder_path else []
    )

    result = await service.build_download_plan(
        rjcode="rj123456",
        folder_path="/mock/library",
        filters={
            "resource_types": ["audio", "subtitle"],
            "audio_formats": ["mp3"],
            "subtitle_languages": [],
            "include_existing": False,
        },
    )

    assert result["success"] is True
    assert result["rjcode"] == "RJ123456"
    assert result["session_id"]
    assert result["summary"]["matched_total"] == 1
    assert result["summary"]["missing_total"] == 2
    assert "missing_remote_resources" in result
    assert "grouped_resources" in result
    assert "selection_presets" in result
    assert len(result["selectable_resources"]) == 1
    assert result["selectable_resources"][0]["resource_type"] == "subtitle"
    assert result["selectable_resources"][0]["selected"] is True


@pytest.mark.anyio
async def test_fetch_remote_resources_caches_source_but_rebuilds_resource_ids():
    fake = FakeASMRService()
    service = ASMRResourceService(asmr_service=fake)

    _, first_resources = await service.fetch_remote_resources("RJ123456")
    _, second_resources = await service.fetch_remote_resources("RJ123456")

    assert fake.work_info_calls == 1
    assert fake.track_calls == 1
    assert first_resources[0]["relative_path"] == second_resources[0]["relative_path"]
    assert first_resources[0]["id"] != second_resources[0]["id"]


@pytest.mark.anyio
async def test_fetch_remote_resources_refresh_bypasses_source_cache():
    fake = FakeASMRService()
    service = ASMRResourceService(asmr_service=fake)

    await service.fetch_remote_resources("RJ123456")
    await service.fetch_remote_resources("RJ123456", refresh=True)

    assert fake.work_info_calls == 2
    assert fake.track_calls == 2


@pytest.mark.asyncio
async def test_upload_to_local_uses_disk_io_budget_and_reports_progress(monkeypatch, tmp_path):
    service = create_service()
    source_path = tmp_path / "source.bin"
    source_path.write_bytes(b"a" * (300 * 1024))
    calls = []
    progress_rows = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    monkeypatch.setattr("app.core.asmr_resource_service.get_resource_budget_service", lambda: Budget())

    result = await service._upload_to_local(
        str(source_path),
        str(tmp_path / "library"),
        "RJ123456/source.bin",
        progress_callback=lambda uploaded, total: progress_rows.append((uploaded, total)),
    )

    assert calls == [("disk_io_local", 1, "asmr.upload_local")]
    assert os.path.exists(result)
    assert open(result, "rb").read() == source_path.read_bytes()
    assert progress_rows[-1] == (300 * 1024, 300 * 1024)


@pytest.mark.asyncio
async def test_upload_to_local_preserves_cancel_behavior(monkeypatch, tmp_path):
    service = create_service()
    source_path = tmp_path / "source.bin"
    source_path.write_bytes(b"a" * 1024)

    class Budget:
        @asynccontextmanager
        async def acquire(self, resource, *, weight=1, reason=""):
            yield

    monkeypatch.setattr("app.core.asmr_resource_service.get_resource_budget_service", lambda: Budget())

    result = await service._upload_to_local(
        str(source_path),
        str(tmp_path / "library"),
        "RJ123456/source.bin",
        cancel_check=lambda: True,
    )

    assert result == ""
