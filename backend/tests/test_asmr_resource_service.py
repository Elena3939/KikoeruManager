import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

from app.core.asmr_resource_service import ASMRFileDownloadScheduler, ASMRResourceService
from app.core.task_engine import Task, TaskStatus, TaskType


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


@pytest.mark.anyio
async def test_file_download_scheduler_prioritizes_same_rj_and_spills_free_slots():
    scheduler = ASMRFileDownloadScheduler()
    await scheduler.register("RJ-A", total_files=3, limit=5)
    await scheduler.register("RJ-B", total_files=10, limit=5)

    await asyncio.gather(*(scheduler.acquire("RJ-A") for _ in range(3)))
    b_acquires = [asyncio.create_task(scheduler.acquire("RJ-B")) for _ in range(2)]
    await asyncio.gather(*b_acquires)

    snapshot = await scheduler.snapshot()
    assert snapshot["active_total"] == 5
    assert snapshot["sessions"]["RJ-A"]["active"] == 3
    assert snapshot["sessions"]["RJ-B"]["active"] == 2


@pytest.mark.anyio
async def test_file_download_scheduler_does_not_switch_rj_while_priority_rj_has_files():
    scheduler = ASMRFileDownloadScheduler()
    await scheduler.register("RJ-A", total_files=10, limit=5)
    await scheduler.register("RJ-B", total_files=10, limit=5)

    await asyncio.gather(*(scheduler.acquire("RJ-A") for _ in range(5)))
    next_b = asyncio.create_task(scheduler.acquire("RJ-B"))
    await asyncio.sleep(0)
    assert not next_b.done()

    await scheduler.release("RJ-A")
    next_a = asyncio.create_task(scheduler.acquire("RJ-A"))
    await asyncio.wait_for(next_a, timeout=1)
    assert not next_b.done()
    await scheduler.release("RJ-A")

    next_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_b


def test_classify_resource_and_language_detection():
    service = create_service()

    assert service.classify_resource_type("track01.flac") == "audio"
    assert service.classify_resource_type("track01.ass") == "subtitle"
    assert service.classify_resource_type("cover.webp") == "cover"
    assert service.detect_language("RJ123456 简中字幕") == "zh"
    assert service.detect_language("RJ123456 Japanese subtitle") == "ja"


@pytest.mark.anyio
async def test_retry_refreshes_expired_download_link_and_preserves_selection(monkeypatch):
    service = create_service()
    calls = []

    async def fake_fetch_remote_resources(rjcode, *, refresh=False):
        calls.append((rjcode, refresh))
        return {}, [
            {
                "id": "fresh-id",
                "relative_path": "Audio/01 Main Track.mp3",
                "file_name": "01 Main Track.mp3",
                "remote_url": "https://example.com/fresh.mp3",
                "size_bytes": 2048,
                "checksum_md5": "fedcba9876543210fedcba9876543210",
            }
        ]

    monkeypatch.setattr(service, "fetch_remote_resources", fake_fetch_remote_resources)
    refreshed = await service._refresh_retry_resource_links(
        "RJ123456",
        [
            {
                "id": "original-id",
                "relative_path": "Audio/01 Main Track.mp3",
                "file_name": "01 Main Track.mp3",
                "remote_url": "https://example.com/expired.mp3",
                "selected": True,
            }
        ],
    )

    assert calls == [("RJ123456", True)]
    assert refreshed[0]["id"] == "original-id"
    assert refreshed[0]["relative_path"] == "Audio/01 Main Track.mp3"
    assert refreshed[0]["remote_url"] == "https://example.com/fresh.mp3"
    assert refreshed[0]["size_bytes"] == 2048
    assert refreshed[0]["selected"] is True


@pytest.mark.anyio
async def test_retry_does_not_reuse_expired_url_when_resource_is_missing(monkeypatch):
    service = create_service()

    async def fake_fetch_remote_resources(_rjcode, *, refresh=False):
        assert refresh is True
        return {}, []

    monkeypatch.setattr(service, "fetch_remote_resources", fake_fetch_remote_resources)
    refreshed = await service._refresh_retry_resource_links(
        "RJ123456",
        [
            {
                "relative_path": "Audio/missing.mp3",
                "file_name": "missing.mp3",
                "remote_url": "https://example.com/expired.mp3",
            }
        ],
    )

    assert refreshed[0]["remote_url"] == ""


@pytest.mark.anyio
async def test_remote_source_unavailable_is_not_reported_as_missing(monkeypatch):
    service = create_service()

    async def fake_fetch_work_info_with_status(_rjcode):
        return None, "unavailable"

    monkeypatch.setattr(
        service.asmr_service,
        "fetch_work_info_with_status",
        fake_fetch_work_info_with_status,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="ASMR 源站暂时不可用"):
        await service._fetch_remote_source_payload("RJ01455100")


@pytest.mark.anyio
async def test_remote_source_missing_keeps_missing_error(monkeypatch):
    service = create_service()

    async def fake_fetch_work_info_with_status(_rjcode):
        return None, "missing"

    monkeypatch.setattr(
        service.asmr_service,
        "fetch_work_info_with_status",
        fake_fetch_work_info_with_status,
        raising=False,
    )

    with pytest.raises(ValueError, match="未找到作品 RJ01455100"):
        await service._fetch_remote_source_payload("RJ01455100")


@pytest.mark.anyio
async def test_retry_source_unavailable_returns_to_waiting_retry(monkeypatch, tmp_path):
    service = create_service()
    download_root = str(tmp_path / "RJ01455100")
    selected = [{"relative_path": "bonus.png", "file_name": "bonus.png", "remote_url": "expired"}]
    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path="",
        rjcode="RJ01455100",
        metadata={
            "rjcode": "RJ01455100",
            "source_action": "auto_retry_failed_resources",
            "selected_resources": selected,
            "download_root": download_root,
        },
    )

    async def unavailable(*_args, **_kwargs):
        from app.core.asmr_resource_service import ASMRSourceUnavailableError

        raise ASMRSourceUnavailableError("ASMR 源站暂时不可用")

    async def schedule_retry(retry_task, **_kwargs):
        retry_task.set_waiting_retry(
            "ASMR 源站暂时不可用",
            datetime.now() + timedelta(minutes=5),
        )

    monkeypatch.setattr(service, "_refresh_retry_resource_links", unavailable)
    monkeypatch.setattr(service, "_schedule_failed_resource_retry", schedule_retry)

    result = await service.process_download_task(task)

    assert result["success"] is False
    assert result["waiting_retry"] is True
    assert result["download_root"] == download_root
    assert task.status == TaskStatus.WAITING_RETRY
    assert task.task_metadata["failure_reason"] == "ASMR 源站暂时不可用"


@pytest.mark.parametrize(
    ("source_page", "all_files_uploaded", "expected"),
    [
        ("asmr-sync", False, True),
        ("circle-completion", False, True),
        ("asmr-sync", True, False),
    ],
)
def test_local_finalize_syncs_owned_state_regardless_of_source_page(
    source_page,
    all_files_uploaded,
    expected,
):
    service = create_service()

    assert service._should_sync_owned_state_after_finalize(
        final_status="completed",
        postprocess_options={"enabled": True},
        final_output_path="/library/RJ123456",
        all_files_uploaded=all_files_uploaded,
    ) is expected


@pytest.mark.anyio
async def test_waits_for_inventory_index_before_syncing_owned_state(monkeypatch):
    service = create_service()
    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path="",
        rjcode="RJ01455100",
        metadata={
            "library_index_fences": [
                {"library_id": "local-library-3", "accepted_seq": 739},
            ],
        },
    )
    waited = []

    class FakeMutationService:
        def wait_until_materialized(self, fences, *, timeout_seconds):
            waited.append((list(fences), timeout_seconds))

    monkeypatch.setattr(
        "app.core.library_index.get_library_index_mutation_service",
        lambda: FakeMutationService(),
    )

    await service._wait_for_library_index_materialization(task)

    assert waited == [(
        [{"library_id": "local-library-3", "accepted_seq": 739}],
        120.0,
    )]
    assert task.task_metadata["library_index_materialized"] is True


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
async def test_retry_failed_session_serializes_same_session(monkeypatch):
    service = create_service()
    entered = 0
    max_entered = 0

    async def fake_retry(session_id):
        nonlocal entered, max_entered
        assert session_id == "session-1"
        entered += 1
        max_entered = max(max_entered, entered)
        await asyncio.sleep(0)
        entered -= 1
        return {"id": session_id}

    monkeypatch.setattr(service, "_retry_failed_session_unlocked", fake_retry)

    first, second = await asyncio.gather(
        service.retry_failed_session("session-1"),
        service.retry_failed_session("session-1"),
    )

    assert first == {"id": "session-1"}
    assert second == {"id": "session-1"}
    assert max_entered == 1


def test_active_session_download_task_is_reused():
    service = create_service()
    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path="RJ123456",
        metadata={"session_id": "session-1"},
        rjcode="RJ123456",
    )
    task.status = TaskStatus.PENDING

    class Engine:
        @staticmethod
        def get_tasks_by_session(session_id):
            assert session_id == "session-1"
            return [task]

    active = service._find_active_session_download_task(Engine(), "session-1")

    assert active is task
    assert service._build_active_retry_session({"id": "session-1"}, task) == {
        "id": "session-1",
        "task_id": task.id,
        "status": "pending",
        "retry_reused_active_task": True,
    }


def test_active_session_download_task_only_reuses_overlapping_file():
    service = create_service()
    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path="RJ123456",
        metadata={
            "session_id": "session-1",
            "selected_resources": [{"relative_path": "audio/01.wav"}],
        },
        rjcode="RJ123456",
    )
    task.status = TaskStatus.PROCESSING

    class Engine:
        @staticmethod
        def get_tasks_by_session(_session_id):
            return [task]

    assert service._find_active_session_download_task(
        Engine(),
        "session-1",
        {"audio/01.wav"},
    ) is task
    assert service._find_active_session_download_task(
        Engine(),
        "session-1",
        {"audio/02.wav"},
    ) is None


@pytest.mark.anyio
async def test_failed_resources_enter_persistent_auto_retry_and_keep_cache(monkeypatch, tmp_path):
    service = create_service()
    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path="RJ123456",
        metadata={
            "rjcode": "RJ123456",
            "folder_path": str(tmp_path),
            "work_title": "测试作品",
        },
        rjcode="RJ123456",
    )
    task.start()

    class Engine:
        def __init__(self):
            self.saved = None

        def _save_waiting_retry_task(self, *args):
            self.saved = args

        def _remove_waiting_retry_task(self, _rjcode):
            return None

    engine = Engine()
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: engine)

    selected = [
        {
            "relative_path": "audio/ok.wav",
            "file_name": "ok.wav",
            "remote_url": "https://example.com/ok.wav",
        },
        {
            "relative_path": "audio/fail.wav",
            "file_name": "fail.wav",
            "remote_url": "https://example.com/fail.wav",
        },
    ]
    failed = [
        {
            "name": "fail.wav",
            "relative_path": "audio/fail.wav",
            "reason": "连接超时",
            "resource": selected[1],
        }
    ]

    await service._schedule_failed_resource_retry(
        task,
        rjcode="RJ123456",
        metadata=task.task_metadata,
        selected_resources=selected,
        failed_files=failed,
        download_root=str(tmp_path / "download"),
    )

    assert task.status == TaskStatus.WAITING_RETRY
    assert task.task_metadata["selected_resources"] == [selected[1]]
    assert task.task_metadata["source_action"] == "auto_retry_failed_resources"
    assert task.task_metadata["download_root"] == str(tmp_path / "download")
    assert engine.saved is not None


@pytest.mark.anyio
async def test_single_file_retry_serializes_same_file_but_allows_other_files(monkeypatch):
    service = create_service()
    entered = 0
    max_entered = 0

    async def fake_retry(_session_id, _relative_paths):
        nonlocal entered, max_entered
        entered += 1
        max_entered = max(max_entered, entered)
        await asyncio.sleep(0.01)
        entered -= 1
        return {"ok": True}

    monkeypatch.setattr(service, "_retry_failed_session_resources_unlocked", fake_retry)

    await asyncio.gather(
        service.retry_failed_session_resources("session-1", ["audio/01.wav"]),
        service.retry_failed_session_resources("session-1", ["audio/01.wav"]),
    )
    assert max_entered == 1

    max_entered = 0
    await asyncio.gather(
        service.retry_failed_session_resources("session-1", ["audio/01.wav"]),
        service.retry_failed_session_resources("session-1", ["audio/02.wav"]),
    )
    assert max_entered == 2


def test_download_runtime_keeps_full_selected_resource_total():
    service = create_service()

    class RuntimeTask:
        task_metadata = {
            "download_runtime": {
                "expected_total_bytes": 1000,
                "total_bytes": 1000,
            }
        }

    task = RuntimeTask()
    progress_state = {}
    service._update_download_runtime(
        task,
        progress_state,
        file_key="audio/01.wav",
        file_name="01.wav",
        relative_path="audio/01.wav",
        downloaded_bytes=100,
        total_bytes=100,
        index=1,
        total_files=2,
        stage="download",
    )

    runtime = task.task_metadata["download_runtime"]
    assert runtime["total_bytes"] == 1000
    assert runtime["transferred_bytes"] == 100
    assert runtime["progress"] == 10


def test_download_runtime_clamps_oversized_failed_file():
    service = create_service()

    class RuntimeTask:
        task_metadata = {
            "download_runtime": {
                "expected_total_bytes": 1000,
                "total_bytes": 1000,
            }
        }

    task = RuntimeTask()
    progress_state = {}
    service._update_download_runtime(
        task,
        progress_state,
        file_key="audio/01.wav",
        file_name="01.wav",
        relative_path="audio/01.wav",
        downloaded_bytes=1500,
        total_bytes=1000,
        index=1,
        total_files=1,
        stage="download_failed",
    )

    runtime = task.task_metadata["download_runtime"]
    assert task.task_metadata["download_files"][0]["downloaded"] == 1000
    assert task.task_metadata["download_files"][0]["progress"] == 99
    assert runtime["transferred_bytes"] == 1000
    assert runtime["completed_files"] == 0
    assert runtime["progress"] == 99


def test_download_runtime_updates_existing_rows_without_rebuilding_file_list():
    service = create_service()
    first_row = {
        "name": "01.wav",
        "relative_path": "audio/01.wav",
        "downloaded": 0,
        "total": 100,
        "progress": 0,
        "index": 1,
        "stage": "pending",
    }
    second_row = {
        "name": "02.wav",
        "relative_path": "audio/02.wav",
        "downloaded": 0,
        "total": 200,
        "progress": 0,
        "index": 2,
        "stage": "pending",
    }

    class RuntimeTask:
        task_metadata = {
            "download_files": [first_row, second_row],
            "download_runtime": {
                "expected_total_bytes": 300,
                "total_bytes": 300,
                "transferred_bytes": 0,
            },
        }

    task = RuntimeTask()
    progress_state = {
        "audio/01.wav": first_row,
        "audio/02.wav": second_row,
    }
    original_file_list = task.task_metadata["download_files"]

    service._update_download_runtime(
        task,
        progress_state,
        file_key="audio/02.wav",
        file_name="02.wav",
        relative_path="audio/02.wav",
        downloaded_bytes=50,
        total_bytes=200,
        index=2,
        total_files=2,
        stage="download",
    )

    assert task.task_metadata["download_files"] is original_file_list
    assert task.task_metadata["download_files"][1] is second_row
    assert second_row["downloaded"] == 50
    assert task.task_metadata["download_runtime"]["transferred_bytes"] == 50
    assert task.task_metadata["download_runtime"]["active_file_count"] == 1

    service._update_download_runtime(
        task,
        progress_state,
        file_key="audio/02.wav",
        file_name="02.wav",
        relative_path="audio/02.wav",
        downloaded_bytes=200,
        total_bytes=200,
        index=2,
        total_files=2,
        stage="downloaded",
    )

    runtime = task.task_metadata["download_runtime"]
    assert runtime["transferred_bytes"] == 200
    assert runtime["completed_files"] == 1
    assert runtime["active_file_count"] == 0


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
