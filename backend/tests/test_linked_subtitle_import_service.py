import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.classifier import SmartClassifier
from app.core.linked_subtitle_import_service import (
    LinkedSubtitleArchivePrecheckTimeout,
    LinkedSubtitleImportAlreadyRunning,
    LinkedSubtitleImportService,
)
import app.core.linked_subtitle_import_service as linked_subtitle_module
from app.models.database import ConflictWork


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


@pytest.mark.asyncio
async def test_finalize_manual_match_task_blocks_empty_workbench_publish():
    service = object.__new__(LinkedSubtitleImportService)
    service.library_manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="local"),
    )
    service._count_local_subtitle_files = lambda _subtitle_dir: 0
    service._publish_workbench_to_target = AsyncMock(side_effect=AssertionError("不应发布空工作台"))
    service._wait_for_published_subtitles = AsyncMock(side_effect=AssertionError("不应等待发布结果"))

    task = SimpleNamespace(
        task_metadata={
            "source_mode": "subtitle_folder_import",
            "library_id": "local-library",
            "folder_path": "D:/library/RJ01586582",
            "subtitle_dir": "D:/library/_kikoerumanager_subtitle_workbench/linked/abc/subtitles",
            "linked_workbench_root_dir": "D:/library/_kikoerumanager_subtitle_workbench/linked/abc",
        },
        current_step="",
        progress=0,
        completed_at=None,
    )

    with pytest.raises(ValueError, match="可发布字幕数量异常"):
        await service.finalize_manual_match_task(task, expected_min_files=2)

    service._publish_workbench_to_target.assert_not_awaited()
    service._wait_for_published_subtitles.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_manual_match_task_allows_fewer_subtitles_than_pairs():
    service = object.__new__(LinkedSubtitleImportService)
    service.library_manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="local"),
    )
    service._count_local_subtitle_files = lambda _subtitle_dir: 1
    service._publish_workbench_to_target = AsyncMock(return_value="D:/library/RJ01586582/subtitles")
    service._wait_for_published_subtitles = AsyncMock(return_value=[
        {"name": "track01.vtt", "relative_path": "track01.vtt"},
    ])

    task = SimpleNamespace(
        task_metadata={
            "source_mode": "subtitle_folder_import",
            "library_id": "local-library",
            "folder_path": "D:/library/RJ01586582",
            "subtitle_dir": "D:/library/_kikoerumanager_subtitle_workbench/linked/abc/subtitles",
            "linked_workbench_root_dir": "D:/library/_kikoerumanager_subtitle_workbench/linked/abc",
        },
        current_step="",
        progress=0,
        completed_at=None,
    )

    result = await service.finalize_manual_match_task(task, expected_min_files=2)

    assert result["applied"] is True
    assert result["final_file_count"] == 1
    assert task.task_metadata["downloaded_count"] == 1
    service._publish_workbench_to_target.assert_awaited_once()
    service._wait_for_published_subtitles.assert_awaited_once_with(
        library_id="local-library",
        subtitle_dir="D:/library/RJ01586582/subtitles",
        expected_count=1,
    )


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


def test_refresh_preview_execution_state_keeps_timeout_archive_executable(tmp_path):
    archive_path = tmp_path / "RJ01620917.7z.001"
    archive_path.write_bytes(b"placeholder")
    service = object.__new__(LinkedSubtitleImportService)
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service._prefer_deepest_target_rj_candidates = lambda candidates, _target: candidates
    service._should_direct_import_to_empty_candidate = lambda _preview, _candidate: False

    preview = service._refresh_preview_execution_state({
        "source_rjcode": "RJ01620917",
        "target_rjcode": "RJ01608823",
        "source_path": str(archive_path),
        "is_translation_work": True,
        "is_manual_subtitle_source": False,
        "subtitle_count": 0,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "kikoeru_route_confident": True,
        "source_subtitle_probe_status": "timeout",
        "source_subtitle_probe_reason": "字幕补配预检超时，执行时将重新解包扫描字幕",
        "candidates": [{
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01608823",
            "ready_for_import": True,
        }],
    })

    assert preview["can_stage_pending"] is True
    assert preview["can_execute"] is True
    assert "重新解包" in preview["execute_reason"]


@pytest.mark.asyncio
async def test_queue_pending_archive_import_preserves_timeout_as_pending(db_session, monkeypatch):
    def fake_get_db():
        yield db_session

    monkeypatch.setattr(linked_subtitle_module, "get_db", fake_get_db)

    service = object.__new__(LinkedSubtitleImportService)
    service.PENDING_CONFLICT_TYPE = LinkedSubtitleImportService.PENDING_CONFLICT_TYPE
    service.PENDING_SOURCE_MODE = LinkedSubtitleImportService.PENDING_SOURCE_MODE
    service.ARCHIVE_PRECHECK_TIMEOUT_SECONDS = 1
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: "RJ01620917" if "RJ01620917" in str(value or "") else ""
    )
    service._should_create_pending_import = LinkedSubtitleImportService._should_create_pending_import.__get__(service)
    service._can_execute_pending_import = LinkedSubtitleImportService._can_execute_pending_import.__get__(service)
    service._serialize_pending_record = LinkedSubtitleImportService._serialize_pending_record.__get__(service)
    service._cleanup_stage_dir = lambda _stage_dir: None
    service.preview_archive_import = AsyncMock(side_effect=LinkedSubtitleArchivePrecheckTimeout({
        "mode": "archive",
        "source_path": "D:/input/RJ01620917.7z.001",
        "source_label": "RJ01620917.7z.001",
        "source_rjcode": "RJ01620917",
        "target_rjcode": "RJ01608823",
        "is_translation_work": True,
        "is_manual_subtitle_source": False,
        "is_linked_subtitle_source": True,
        "subtitle_count": 0,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "kikoeru_route_confident": True,
        "source_subtitle_probe_status": "timeout",
        "source_subtitle_probe_reason": "字幕补配预检超时，执行时将重新解包扫描字幕",
        "candidate_count": 1,
        "ready_candidate_count": 1,
        "can_stage_pending": True,
        "can_execute": True,
        "selected_candidate": {
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01608823",
            "ready_for_import": True,
        },
        "candidates": [{
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01608823",
            "ready_for_import": True,
        }],
    }))
    service._stage_archive_subtitles_for_preview = AsyncMock(
        side_effect=AssertionError("超时待处理单不应立刻重新解包")
    )

    task = SimpleNamespace(
        id="task-timeout",
        source_path="D:/input/RJ01620917.7z.001",
        task_metadata={},
        update_progress=lambda *_args, **_kwargs: None,
    )

    result = await service.queue_pending_archive_import(task, "RJ01620917")

    assert result["handled"] is True
    assert result["preview"]["source_subtitle_probe_status"] == "timeout"
    service._stage_archive_subtitles_for_preview.assert_not_awaited()

    row = db_session.query(ConflictWork).filter(
        ConflictWork.conflict_type == LinkedSubtitleImportService.PENDING_CONFLICT_TYPE,
        ConflictWork.task_id == "task-timeout",
    ).one()
    assert row.rjcode == "RJ01608823"
    assert row.new_metadata["source_subtitle_probe_status"] == "timeout"


@pytest.mark.asyncio
async def test_execute_pending_import_rejects_running_record(db_session, monkeypatch):
    def fake_get_db():
        yield db_session

    monkeypatch.setattr(linked_subtitle_module, "get_db", fake_get_db)

    service = object.__new__(LinkedSubtitleImportService)
    service.PENDING_CONFLICT_TYPE = LinkedSubtitleImportService.PENDING_CONFLICT_TYPE
    service.PENDING_EXECUTING_STATUS = LinkedSubtitleImportService.PENDING_EXECUTING_STATUS

    row = ConflictWork(
        id="pending-running",
        rjcode="RJ01608823",
        conflict_type=LinkedSubtitleImportService.PENDING_CONFLICT_TYPE,
        new_path="D:/input/RJ01620917.7z",
        status=LinkedSubtitleImportService.PENDING_EXECUTING_STATUS,
        analysis_info={"preview": {"source_rjcode": "RJ01620917", "target_rjcode": "RJ01608823"}},
        new_metadata={},
    )
    db_session.add(row)
    db_session.commit()

    with pytest.raises(LinkedSubtitleImportAlreadyRunning):
        await service.execute_pending_import("pending-running")


@pytest.mark.asyncio
async def test_execute_pending_import_resets_status_when_long_io_fails(db_session, monkeypatch):
    def fake_get_db():
        yield db_session

    monkeypatch.setattr(linked_subtitle_module, "get_db", fake_get_db)

    service = object.__new__(LinkedSubtitleImportService)
    service.PENDING_CONFLICT_TYPE = LinkedSubtitleImportService.PENDING_CONFLICT_TYPE
    service.PENDING_EXECUTING_STATUS = LinkedSubtitleImportService.PENDING_EXECUTING_STATUS
    service.PENDING_SOURCE_MODE = LinkedSubtitleImportService.PENDING_SOURCE_MODE
    service._repair_cached_preview_rj_fields = AsyncMock(return_value={
        "source_rjcode": "RJ01620917",
        "target_rjcode": "RJ01608823",
    })
    service._refresh_pending_preview_candidates = AsyncMock(return_value={
        "source_rjcode": "RJ01620917",
        "target_rjcode": "RJ01608823",
        "can_execute": True,
    })
    service.execute_archive_import = AsyncMock(side_effect=ValueError("模拟解压失败"))

    row = ConflictWork(
        id="pending-fails",
        rjcode="RJ01608823",
        conflict_type=LinkedSubtitleImportService.PENDING_CONFLICT_TYPE,
        new_path="D:/input/RJ01620917.7z",
        status="PENDING",
        analysis_info={"preview": {"source_rjcode": "RJ01620917", "target_rjcode": "RJ01608823"}},
        new_metadata={},
    )
    db_session.add(row)
    db_session.commit()

    with pytest.raises(ValueError, match="模拟解压失败"):
        await service.execute_pending_import("pending-fails")

    refreshed = db_session.query(ConflictWork).filter(ConflictWork.id == "pending-fails").one()
    assert refreshed.status == "PENDING"
    assert refreshed.analysis_info["execution_status"] == "failed"
    assert "模拟解压失败" in refreshed.analysis_info["execution_error"]
