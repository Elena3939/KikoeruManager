import os
from contextlib import asynccontextmanager

import pytest

from app.core.asmr_resource_service import ASMRResourceService


class FakeASMRService:
    async def fetch_work_info(self, rjcode):
        return {
            "id": 1,
            "title": f"作品 {rjcode}",
            "circle": "Circle",
            "tags": ["asmr"],
        }

    async def fetch_track_list(self, rjcode):
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
