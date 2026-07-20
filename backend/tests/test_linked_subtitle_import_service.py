import asyncio
from copy import deepcopy
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timedelta

from app.core.classifier import SmartClassifier
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.core.linked_subtitle_import_service import (
    LinkedSubtitleArchivePrecheckTimeout,
    LinkedSubtitleImportAlreadyRunning,
    LinkedSubtitleImportService,
)
from app.core.rj_subtitle_service import RJSubtitleService
import app.core.linked_subtitle_import_service as linked_subtitle_module
from app.models.database import ConflictWork


class _SubtitleCacheRedisClient:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def incr(self, key):
        value = int(self.values.get(key) or 0) + 1
        self.values[key] = str(value)
        return value


class _SubtitleCacheRedisService:
    def __init__(self):
        self.client_obj = _SubtitleCacheRedisClient()
        self.json_values = {}
        self.set_calls = []

    def is_enabled(self):
        return True

    def client(self, *, required=False):
        return self.client_obj

    def key(self, *parts):
        return ':'.join(str(part) for part in parts if str(part))

    def short_cache_ttl_seconds(self):
        return 45

    def get_json(self, module, type_name, item_id):
        return deepcopy(self.json_values.get((module, type_name, item_id)))

    def set_json(self, module, type_name, item_id, payload, *, ttl_seconds=None):
        self.json_values[(module, type_name, item_id)] = deepcopy(payload)
        self.set_calls.append((item_id, ttl_seconds))
        return True


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
            "can_stage_pending": True,
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


def test_classifier_keeps_linked_duplicate_when_translation_preview_has_no_subtitles():
    classifier = SmartClassifier()
    task = SimpleNamespace(task_metadata={
        "linked_subtitle_preview": {
            "source_rjcode": "RJ01625472",
            "target_rjcode": "RJ01609723",
            "is_translation_work": True,
            "kikoeru_needs_subtitle": True,
            "kikoeru_target_is_empty_shell": False,
            "subtitle_count": 0,
            "can_stage_pending": False,
            "should_queue_pending": False,
            "can_execute": False,
        },
    })
    linked_works = {
        "RJ01625472": SimpleNamespace(work_type="translation", lang="CHI_HANS"),
        "RJ01609723": SimpleNamespace(work_type="original", lang="JPN"),
    }

    should_skip = classifier._should_skip_linked_duplicate_for_subtitle_import(
        "RJ01625472",
        "RJ01609723",
        linked_works,
        task,
    )

    assert should_skip is False


def test_task_engine_blocks_linked_translation_archive_without_subtitles():
    engine = object.__new__(TaskEngine)
    preview = {
        "source_rjcode": "RJ01625472",
        "target_rjcode": "RJ01609723",
        "is_translation_work": True,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "kikoeru_target_is_empty_shell": False,
        "subtitle_count": 0,
        "source_has_subtitles": False,
        "can_stage_pending": False,
        "should_queue_pending": False,
        "can_execute": False,
        "source_subtitle_probe_status": "no_subtitles",
    }

    assert engine._should_block_linked_translation_without_subtitles(preview) is True

    preview["can_stage_pending"] = True
    assert engine._should_block_linked_translation_without_subtitles(preview) is False


def test_task_engine_blocks_uncertain_dlsite_linkage():
    engine = object.__new__(TaskEngine)
    preview = {
        "source_rjcode": "RJ01621937",
        "target_rjcode": "",
        "is_translation_work": False,
        "dlsite_linkage_uncertain": True,
        "dlsite_linkage_uncertain_reason": LinkedSubtitleImportService.DLSITE_LINKAGE_UNCERTAIN_REASON,
        "subtitle_count": 0,
        "can_stage_pending": False,
        "should_queue_pending": False,
        "can_execute": False,
    }

    assert engine._should_block_uncertain_dlsite_linkage(preview) is True

    preview["can_stage_pending"] = True
    assert engine._should_block_uncertain_dlsite_linkage(preview) is False


def test_uncertain_dlsite_linkage_sets_waiting_retry_state():
    task = Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path="/input/RJ01621937.rar",
        auto_classify=True,
        metadata={
            "linked_subtitle_preview": {
                "source_rjcode": "RJ01621937",
                "dlsite_linkage_uncertain": True,
            }
        },
        rjcode="RJ01621937",
    )
    reason = LinkedSubtitleImportService.DLSITE_LINKAGE_UNCERTAIN_REASON
    retry_after = datetime.now() + timedelta(minutes=15)

    task.set_waiting_retry(reason, retry_after)

    assert task.status == TaskStatus.WAITING_RETRY
    assert task.task_metadata["retry_reason"] == reason
    assert task.task_metadata["retry_after"]
    assert task.current_step == f"等待重试: {reason}"


@pytest.mark.asyncio
async def test_common_preview_uses_kikoeru_hit_to_block_translation_as_new_work():
    service = object.__new__(LinkedSubtitleImportService)
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: str(value or "").strip().upper()
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(),
        get_product_info=AsyncMock(return_value={}),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace(
        check_duplicate=AsyncMock(side_effect=[
            SimpleNamespace(
                is_found=False,
                source="kikoeru",
                title="简中翻译作",
                has_lyric_hint=False,
                subtitle_file_count=0,
                subtitle_check_source="tracks",
                total_track_count=8,
                lyric_status="",
            ),
            SimpleNamespace(
                is_found=True,
                source="kikoeru",
                title="原作",
                has_lyric_hint=False,
                subtitle_file_count=0,
                subtitle_check_source="tracks",
                total_track_count=9,
                lyric_status="",
            ),
        ])
    )
    service.search_target_candidates = AsyncMock(return_value={
        "candidates": [],
        "search_status": "not_found",
        "search_reason": "ready 库存索引未命中原作目录",
    })

    preview = await service._build_common_preview(
        source_rjcode="RJ01625472",
        source_label="RJ01625472.7z",
        subtitle_count=1,
        preferred_library_id=None,
        _prefetched_translation=(
            SimpleNamespace(is_original=False, original_workno="RJ01609723", lang="CHI_HANS"),
            "RJ01609723",
        ),
    )

    assert preview["is_translation_work"] is True
    assert preview["kikoeru_has_work"] is True
    assert preview["kikoeru_needs_subtitle"] is True
    assert preview["treat_as_new_work"] is False
    assert preview["can_stage_pending"] is True
    assert preview["can_execute"] is False
    assert "未命中任何关联作品" not in preview["reason"]
    assert preview["candidate_search_reason"] == "ready 库存索引未命中原作目录"


@pytest.mark.asyncio
async def test_common_preview_uses_ready_linked_target_for_subtitle_supplement_when_kikoeru_unavailable():
    service = object.__new__(LinkedSubtitleImportService)
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: str(value or "").strip().upper()
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(),
        get_product_info=AsyncMock(return_value={}),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace(check_duplicate=AsyncMock(return_value=None))
    service.search_target_candidates = AsyncMock(return_value={
        "candidates": [{
            "library_id": "asmr",
            "folder_path": "/library/RJ01609723",
            "ready_for_import": True,
            "existing_subtitle_count": 0,
            "total_files": 12,
        }],
        "search_status": "ready",
        "search_reason": "",
    })

    preview = await service._build_common_preview(
        source_rjcode="RJ01625472",
        source_label="RJ01625472.7z",
        subtitle_count=1,
        preferred_library_id=None,
        _prefetched_translation=(
            SimpleNamespace(is_original=False, original_workno="RJ01609723", lang="CHI_HANS"),
            "RJ01609723",
        ),
    )

    assert preview["kikoeru_route_confident"] is False
    assert preview["target_state_source"] == "ready_library_index"
    assert preview["target_has_work"] is True
    assert preview["target_needs_subtitle"] is True
    assert preview["target_route_confident"] is True
    assert preview["can_stage_pending"] is True
    assert preview["can_execute"] is True
    assert preview["treat_as_new_work"] is False


@pytest.mark.asyncio
async def test_common_preview_uses_ready_linked_target_for_duplicate_when_subtitle_exists():
    service = object.__new__(LinkedSubtitleImportService)
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: str(value or "").strip().upper()
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(),
        get_product_info=AsyncMock(return_value={}),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace(check_duplicate=AsyncMock(return_value=None))
    service.search_target_candidates = AsyncMock(return_value={
        "candidates": [{
            "library_id": "asmr",
            "folder_path": "/library/RJ01609723",
            "ready_for_import": False,
            "existing_subtitle_count": 3,
            "total_files": 15,
        }],
        "search_status": "ready",
        "search_reason": "",
    })

    preview = await service._build_common_preview(
        source_rjcode="RJ01625472",
        source_label="RJ01625472.7z",
        subtitle_count=1,
        preferred_library_id=None,
        _prefetched_translation=(
            SimpleNamespace(is_original=False, original_workno="RJ01609723", lang="CHI_HANS"),
            "RJ01609723",
        ),
    )

    assert preview["target_has_work"] is True
    assert preview["target_has_subtitle"] is True
    assert preview["target_needs_subtitle"] is False
    assert preview["can_stage_pending"] is False
    assert preview["stage_reason"] == LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    assert service._is_existing_subtitle_duplicate_preview(preview) is True


@pytest.mark.asyncio
async def test_common_preview_marks_unverified_translation_page_as_uncertain():
    service = object.__new__(LinkedSubtitleImportService)
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: "RJ01621937" if "RJ01621937" in str(value or "") else ""
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(),
        get_product_info=AsyncMock(return_value={
            "product": {
                "work_name": "【繁体中文版】テスト音声 [みんなで翻訳] | DLsite",
            },
            "fallback_source": "page_metadata",
        }),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace(
        check_duplicate=AsyncMock(return_value=SimpleNamespace(
            is_found=False,
            source="kikoeru",
            title="",
            has_lyric_hint=False,
            subtitle_file_count=0,
            subtitle_check_source="tracks",
            total_track_count=0,
            lyric_status="",
        ))
    )
    service.search_target_candidates = AsyncMock(
        side_effect=AssertionError("target 为空时不应查候选")
    )

    preview = await service._build_common_preview(
        source_rjcode="RJ01621937",
        source_label="RJ01621937.7z",
        subtitle_count=0,
        preferred_library_id=None,
        _prefetched_translation=(
            SimpleNamespace(
                is_original=False,
                is_parent=False,
                is_child=False,
                original_workno="",
                parent_workno="",
                child_worknos=[],
                lang="",
            ),
            "",
        ),
    )

    assert preview["dlsite_linkage_uncertain"] is True
    assert preview["dlsite_product_title"] == "【繁体中文版】テスト音声 [みんなで翻訳] | DLsite"
    assert preview["dlsite_fallback_source"] == "page_metadata"
    assert preview["treat_as_new_work"] is False
    assert preview["can_stage_pending"] is False
    assert preview["stage_reason"] == LinkedSubtitleImportService.DLSITE_LINKAGE_UNCERTAIN_REASON


@pytest.mark.asyncio
async def test_common_preview_keeps_kikoeru_empty_shell_blocking_state():
    service = object.__new__(LinkedSubtitleImportService)
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: str(value or "").strip().upper()
    )
    service.dlsite_service = SimpleNamespace(
        get_translation_info=AsyncMock(),
        get_product_info=AsyncMock(return_value={}),
        get_linked_works=AsyncMock(return_value={}),
    )
    service.kikoeru_service = SimpleNamespace(
        check_duplicate=AsyncMock(side_effect=[
            SimpleNamespace(
                is_found=False,
                source="kikoeru",
                title="简中翻译作",
                has_lyric_hint=False,
                subtitle_file_count=0,
                subtitle_check_source="tracks",
                total_track_count=8,
                lyric_status="",
            ),
            SimpleNamespace(
                is_found=True,
                source="kikoeru",
                title="原作空壳",
                has_lyric_hint=False,
                subtitle_file_count=0,
                subtitle_check_source="tracks",
                total_track_count=0,
                lyric_status="",
            ),
        ])
    )
    service.search_target_candidates = AsyncMock(return_value={
        "candidates": [],
        "search_status": "not_found",
        "search_reason": "",
    })

    preview = await service._build_common_preview(
        source_rjcode="RJ01625472",
        source_label="RJ01625472.7z",
        subtitle_count=1,
        preferred_library_id=None,
        _prefetched_translation=(
            SimpleNamespace(is_original=False, original_workno="RJ01609723", lang="CHI_HANS"),
            "RJ01609723",
        ),
    )

    assert preview["kikoeru_has_work"] is True
    assert preview["kikoeru_target_is_empty_shell"] is True
    assert preview["can_stage_pending"] is False
    assert preview["stage_reason"] == "字幕补配时发现服务器作品为空壳"


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


@pytest.mark.asyncio
async def test_preview_archive_import_deduplicates_same_archive_inflight(tmp_path):
    """同一路径并发预检只启动一次真实 archive preview，避免重复临时解包。"""
    archive_path = tmp_path / "RJ01586796.zip"
    archive_path.write_bytes(b"placeholder")
    service = object.__new__(LinkedSubtitleImportService)

    started = asyncio.Event()
    release = asyncio.Event()
    call_count = 0

    async def run_preview(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        started.set()
        await release.wait()
        return {"mode": "archive", "source_path": str(archive_path)}

    service._preview_archive_import_uncached = AsyncMock(side_effect=run_preview)

    first = asyncio.create_task(service.preview_archive_import(str(archive_path)))
    await started.wait()
    second = asyncio.create_task(service.preview_archive_import(str(archive_path)))
    await asyncio.sleep(0)
    release.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert call_count == 1
    assert first_result == second_result == {"mode": "archive", "source_path": str(archive_path)}


@pytest.mark.asyncio
async def test_preview_archive_import_timeout_cancels_inflight_preview(tmp_path):
    """预检超时时必须取消正在执行的内部 preview task，而不是只返回 timeout preview。"""
    archive_path = tmp_path / "RJ01586796.zip"
    archive_path.write_bytes(b"placeholder")
    service = object.__new__(LinkedSubtitleImportService)
    cancelled = asyncio.Event()

    async def run_preview(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service._preview_archive_import_uncached = AsyncMock(side_effect=run_preview)
    service._build_timeout_archive_preview = AsyncMock(return_value={
        "mode": "archive",
        "source_path": str(archive_path),
        "source_subtitle_probe_status": "timeout",
    })

    with pytest.raises(LinkedSubtitleArchivePrecheckTimeout) as exc_info:
        await service.preview_archive_import(str(archive_path), precheck_timeout=0.01)

    assert cancelled.is_set()
    assert exc_info.value.preview["source_subtitle_probe_status"] == "timeout"
    service._build_timeout_archive_preview.assert_awaited_once()


@pytest.mark.asyncio
async def test_collect_archive_subtitles_cancel_marks_probe_task_cancelled():
    """外层 preview task 被取消时，临时解包用的 Task 也要显式 cancel。"""
    service = object.__new__(LinkedSubtitleImportService)
    started = asyncio.Event()
    probe_cancelled = asyncio.Event()

    async def extract(probe_task):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            if probe_task.is_cancelled():
                probe_cancelled.set()
            raise

    service.extract_service = SimpleNamespace(extract=AsyncMock(side_effect=extract))

    runner = asyncio.create_task(service._collect_archive_subtitles_to_stage("RJ01586796.zip"))
    await started.wait()
    runner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await runner

    assert probe_cancelled.is_set()


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


def test_refresh_preview_execution_state_keeps_extract_failure_archive_executable(tmp_path):
    archive_path = tmp_path / "RJ01649862.rar"
    archive_path.write_bytes(b"placeholder")
    service = object.__new__(LinkedSubtitleImportService)
    service.REMOTE_PENDING_REASON = LinkedSubtitleImportService.REMOTE_PENDING_REASON
    service.EXISTING_SUBTITLE_REASON = LinkedSubtitleImportService.EXISTING_SUBTITLE_REASON
    service._prefer_deepest_target_rj_candidates = lambda candidates, _target: candidates
    service._should_direct_import_to_empty_candidate = lambda _preview, _candidate: False

    preview = service._refresh_preview_execution_state({
        "source_rjcode": "RJ01649862",
        "target_rjcode": "RJ01638438",
        "source_path": str(archive_path),
        "is_translation_work": True,
        "is_manual_subtitle_source": False,
        "subtitle_count": 0,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "kikoeru_route_confident": True,
        "source_subtitle_probe_status": "missing_password",
        "source_subtitle_probe_reason": "预检阶段未能解包，执行时重新走解压入库链路",
        "candidates": [{
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01638438",
            "ready_for_import": True,
        }],
    })

    assert preview["can_stage_pending"] is True
    assert preview["can_execute"] is True
    assert "执行时" in preview["execute_reason"]


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
async def test_queue_pending_archive_import_preserves_extract_failure_as_pending(db_session, monkeypatch, tmp_path):
    def fake_get_db():
        yield db_session

    monkeypatch.setattr(linked_subtitle_module, "get_db", fake_get_db)

    archive_path = tmp_path / "RJ01649862.rar"
    archive_path.write_bytes(b"placeholder")

    service = object.__new__(LinkedSubtitleImportService)
    service.PENDING_CONFLICT_TYPE = LinkedSubtitleImportService.PENDING_CONFLICT_TYPE
    service.PENDING_SOURCE_MODE = LinkedSubtitleImportService.PENDING_SOURCE_MODE
    service.ARCHIVE_PRECHECK_TIMEOUT_SECONDS = 1
    service.subtitle_service = SimpleNamespace(
        extract_rjcode=lambda value: "RJ01649862" if "RJ01649862" in str(value or "") else ""
    )
    service._should_create_pending_import = LinkedSubtitleImportService._should_create_pending_import.__get__(service)
    service._can_execute_pending_import = LinkedSubtitleImportService._can_execute_pending_import.__get__(service)
    service._serialize_pending_record = LinkedSubtitleImportService._serialize_pending_record.__get__(service)
    service._refresh_preview_execution_state = LinkedSubtitleImportService._refresh_preview_execution_state.__get__(service)
    service._can_stage_archive_subtitles_later = LinkedSubtitleImportService._can_stage_archive_subtitles_later.__get__(service)
    service._cleanup_stage_dir = lambda _stage_dir: None
    service._prefer_deepest_target_rj_candidates = lambda candidates, _target: candidates
    service._should_direct_import_to_empty_candidate = lambda _preview, _candidate: False
    service.preview_archive_import = AsyncMock(return_value={
        "mode": "archive",
        "source_path": str(archive_path),
        "source_label": "RJ01649862.rar",
        "source_rjcode": "RJ01649862",
        "target_rjcode": "RJ01638438",
        "is_translation_work": True,
        "is_manual_subtitle_source": False,
        "is_linked_subtitle_source": True,
        "subtitle_count": 0,
        "kikoeru_has_work": True,
        "kikoeru_needs_subtitle": True,
        "kikoeru_route_confident": True,
        "source_subtitle_probe_status": "missing_password",
        "source_subtitle_probe_reason": "解压失败：无正确密码",
        "candidate_count": 1,
        "ready_candidate_count": 1,
        "can_stage_pending": True,
        "can_execute": True,
        "selected_candidate": {
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01638438",
            "ready_for_import": True,
        },
        "candidates": [{
            "library_id": "asmr",
            "library_type": "local",
            "folder_path": "D:/library/RJ01638438",
            "ready_for_import": True,
        }],
    })
    service._stage_archive_subtitles_for_preview = AsyncMock(
        side_effect=AssertionError("预检失败的待处理单不应立刻重新解包")
    )

    task = SimpleNamespace(
        id="task-extract-failed",
        source_path=str(archive_path),
        task_metadata={},
        update_progress=lambda *_args, **_kwargs: None,
    )

    result = await service.queue_pending_archive_import(task, "RJ01649862")

    assert result["handled"] is True
    assert result["preview"]["source_subtitle_probe_status"] == "missing_password"
    assert result["preview"]["can_execute"] is True
    service._stage_archive_subtitles_for_preview.assert_not_awaited()

    row = db_session.query(ConflictWork).filter(
        ConflictWork.conflict_type == LinkedSubtitleImportService.PENDING_CONFLICT_TYPE,
        ConflictWork.task_id == "task-extract-failed",
    ).one()
    assert row.rjcode == "RJ01638438"
    assert row.new_metadata["source_subtitle_probe_status"] == "missing_password"


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


@pytest.mark.asyncio
async def test_subtitle_availability_cache_singleflight_and_returns_copies():
    service = object.__new__(RJSubtitleService)
    service._subtitle_availability_redis_service = lambda: None
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def find_best_subtitle_source(rjcode):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {
            "rjcode": rjcode,
            "lang": "CHI_HANS",
            "work_type": "translation",
            "title": "缓存字幕",
            "subtitle_files": [{"name": "track.srt"}],
        }, []

    service.find_best_subtitle_source = find_best_subtitle_source
    first = asyncio.create_task(service.probe_cached_subtitle_availability("rj01234567"))
    await started.wait()
    second = asyncio.create_task(service.probe_cached_subtitle_availability("RJ01234567"))
    await asyncio.sleep(0)
    assert calls == 1

    release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result == second_result
    assert first_result["has_subtitle"] is True

    first_result["selected_source"]["title"] = "被调用方修改"
    cached = await service.probe_cached_subtitle_availability("RJ01234567")
    assert calls == 1
    assert cached["selected_source"]["title"] == "缓存字幕"


@pytest.mark.asyncio
async def test_subtitle_availability_does_not_cache_unstable_absence():
    service = object.__new__(RJSubtitleService)
    service._subtitle_availability_redis_service = lambda: None
    calls = 0

    async def find_best_subtitle_source(_rjcode):
        nonlocal calls
        calls += 1
        return None, [{
            "rjcode": "RJ01234567",
            "subtitle_count": 0,
            "reason": "查询异常: timeout",
        }]

    service.find_best_subtitle_source = find_best_subtitle_source
    await service.probe_cached_subtitle_availability("RJ01234567")
    await service.probe_cached_subtitle_availability("RJ01234567")
    assert calls == 2


@pytest.mark.asyncio
async def test_target_folder_summary_cache_uses_redis_version_after_invalidation():
    redis_service = _SubtitleCacheRedisService()
    service = object.__new__(LinkedSubtitleImportService)
    service.library_manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="local"),
    )
    service._target_folder_summary_redis_service = lambda: redis_service
    calls = 0

    async def summarize_target_folder(library_id, folder_path):
        nonlocal calls
        calls += 1
        return {
            "library_id": library_id,
            "folder_path": folder_path,
            "existing_subtitle_count": calls,
        }

    service.summarize_target_folder = summarize_target_folder
    first = await service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    second = await service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    assert calls == 1
    assert first == second
    assert redis_service.set_calls[-1][1] == 45

    assert service.invalidate_target_folder_summary_cache("library-a") == 1
    refreshed = await service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    assert calls == 2
    assert refreshed["existing_subtitle_count"] == 2

    l2_only_service = object.__new__(LinkedSubtitleImportService)
    l2_only_service.library_manager = service.library_manager
    l2_only_service._target_folder_summary_redis_service = lambda: redis_service
    l2_only_service.summarize_target_folder = AsyncMock(side_effect=AssertionError("应直接命中 Redis L2"))
    from_l2 = await l2_only_service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    assert from_l2 == refreshed


@pytest.mark.asyncio
async def test_target_folder_summary_inflight_result_is_not_cached_after_invalidation():
    redis_service = _SubtitleCacheRedisService()
    service = object.__new__(LinkedSubtitleImportService)
    service.library_manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="local"),
    )
    service._target_folder_summary_redis_service = lambda: redis_service
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def summarize_target_folder(library_id, folder_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return {
            "library_id": library_id,
            "folder_path": folder_path,
            "existing_subtitle_count": calls,
        }

    service.summarize_target_folder = summarize_target_folder
    stale_read = asyncio.create_task(
        service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    )
    await started.wait()

    service.invalidate_target_folder_summary_cache("library-a")
    release.set()
    stale_result = await stale_read

    assert stale_result["existing_subtitle_count"] == 1
    assert redis_service.set_calls == []

    refreshed = await service.summarize_target_folder_cached("library-a", "D:/library/RJ01234567")
    assert calls == 2
    assert refreshed["existing_subtitle_count"] == 2
    assert len(redis_service.set_calls) == 1
