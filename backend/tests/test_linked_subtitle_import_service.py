import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.classifier import SmartClassifier
from app.core.linked_subtitle_import_service import LinkedSubtitleImportService


def test_prefer_deepest_target_rj_candidate_keeps_inner_same_rj_folder():
    service = object.__new__(LinkedSubtitleImportService)
    candidates = [
        {
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library_asmr/circle/[RJ01582352] title",
            "ready_for_import": True,
        },
        {
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library_asmr/circle/[RJ01582352] title/RJ01582352",
            "ready_for_import": True,
        },
    ]

    result = service._prefer_deepest_target_rj_candidates(candidates, "RJ01582352")

    assert len(result) == 1
    assert result[0]["folder_path"].endswith("[RJ01582352] title/RJ01582352")


def test_refresh_preview_execution_state_selects_inner_rj_candidate_from_cached_preview():
    service = object.__new__(LinkedSubtitleImportService)
    parent = {
        "library_id": "asmr",
        "library_type": "local",
        "folder_path": "D:/library_asmr/circle/[RJ01582352] title",
        "ready_for_import": True,
    }
    child = {
        "library_id": "asmr",
        "library_type": "local",
        "folder_path": "D:/library_asmr/circle/[RJ01582352] title/RJ01582352",
        "ready_for_import": True,
    }

    preview = service._refresh_preview_execution_state({
        "source_rjcode": "RJ01582352",
        "target_rjcode": "RJ01582352",
        "is_manual_subtitle_source": True,
        "subtitle_count": 1,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "candidates": [parent, child],
        "selected_candidate": parent,
    })

    assert preview["candidate_count"] == 1
    assert preview["ready_candidate_count"] == 1
    assert preview["selected_candidate"]["folder_path"] == child["folder_path"]


def test_prefer_deepest_target_rj_candidate_keeps_separate_libraries():
    service = object.__new__(LinkedSubtitleImportService)
    candidates = [
        {
            "library_id": "local-a",
            "library_type": "local",
            "folder_path": "D:/a/[RJ01582352] title",
            "ready_for_import": True,
        },
        {
            "library_id": "local-b",
            "library_type": "local",
            "folder_path": "D:/b/[RJ01582352] title/RJ01582352",
            "ready_for_import": True,
        },
    ]

    result = service._prefer_deepest_target_rj_candidates(candidates, "RJ01582352")

    assert result == candidates


def test_classifier_skips_original_duplicate_when_translation_should_supply_subtitles():
    classifier = SmartClassifier()
    task = SimpleNamespace(task_metadata={
        "linked_subtitle_preview": {
            "source_rjcode": "RJ01616588",
            "target_rjcode": "RJ01603646",
            "is_translation_work": True,
            "kikoeru_needs_subtitle": True,
            "kikoeru_target_is_empty_shell": False,
        },
    })
    linked_works = {
        "RJ01616588": SimpleNamespace(work_type="translation", lang="CHI_HANT"),
        "RJ01603646": SimpleNamespace(work_type="original", lang="JPN"),
    }

    should_skip = classifier._should_skip_linked_duplicate_for_subtitle_import(
        "RJ01616588",
        "RJ01603646",
        linked_works,
        task,
    )

    assert should_skip is True


@pytest.mark.asyncio
async def test_preview_archive_import_large_non_translation_skips_archive_listing(tmp_path):
    """大包已有 RJ hint 且确认非翻译作品时，不读压缩包清单也不临时解包。"""
    archive_path = tmp_path / "RJ01616588.zip"
    with open(archive_path, "wb") as f:
        f.seek(11 * 1024 * 1024)
        f.write(b"\0")

    service = object.__new__(LinkedSubtitleImportService)
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: "RJ01616588" if "RJ01616588" in str(value or "") else ""
    )
    service.extract_service = SimpleNamespace(
        NESTED_SUBTITLE_SIZE_THRESHOLD=10 * 1024 * 1024,
        PRECHECK_LIST_TIMEOUT_SECONDS=1,
        get_archive_info=AsyncMock(side_effect=AssertionError("非翻译大包不应读取压缩包清单")),
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(return_value=SimpleNamespace(is_original=True, original_workno="")),
        get_product_info=AsyncMock(return_value={}),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace()
    service._collect_archive_subtitles_to_stage = AsyncMock(
        side_effect=AssertionError("非翻译大包不应临时解包扫描字幕")
    )
    service._build_common_preview = AsyncMock(return_value={
        "source_rjcode": "RJ01616588",
        "target_rjcode": "",
        "is_translation_work": False,
        "is_manual_subtitle_source": False,
        "is_linked_subtitle_source": False,
        "subtitle_count": 0,
    })
    service._refresh_preview_execution_state = lambda preview: preview

    preview = await service.preview_archive_import(
        str(archive_path),
        source_rjcode_hint="RJ01616588",
    )

    service.extract_service.get_archive_info.assert_not_awaited()
    service._collect_archive_subtitles_to_stage.assert_not_awaited()
    service.dlsite_service.get_translation_info.assert_awaited_once_with("RJ01616588")
    service._build_common_preview.assert_awaited_once()
    assert preview["mode"] == "archive"
    assert preview["source_rjcode"] == "RJ01616588"
    assert preview["source_has_subtitles"] is False
