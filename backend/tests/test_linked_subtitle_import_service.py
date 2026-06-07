from types import SimpleNamespace

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
