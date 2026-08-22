from types import SimpleNamespace

from app.core.conflict_resolution_service import ConflictResolutionService


def test_legacy_existing_subtitle_conflict_allows_keep_new_when_target_exists(tmp_path):
    existing = tmp_path / "RJ01529432"
    existing.mkdir()
    conflict = SimpleNamespace(
        conflict_type="LINKED_WORK",
        status="PENDING",
        existing_path=str(existing),
        new_metadata={
            "available_actions": ["SKIP"],
            "reason": "原作目录已有字幕，按重复作品处理",
        },
        analysis_info={
            "source_mode": "linked_translation_archive_existing_subtitle_conflict",
            "problem_kind": "existing_subtitles",
        },
    )

    assert ConflictResolutionService().get_available_actions(conflict) == ["KEEP_NEW", "SKIP"]


def test_legacy_existing_subtitle_conflict_keeps_skip_when_target_is_missing(tmp_path):
    conflict = SimpleNamespace(
        conflict_type="LINKED_WORK",
        status="PENDING",
        existing_path=str(tmp_path / "missing-RJ01529432"),
        new_metadata={
            "available_actions": ["SKIP"],
            "reason": "原作目录已有字幕，按重复作品处理",
        },
        analysis_info={
            "source_mode": "linked_translation_archive_existing_subtitle_conflict",
            "problem_kind": "existing_subtitles",
        },
    )

    assert ConflictResolutionService().get_available_actions(conflict) == ["SKIP"]
