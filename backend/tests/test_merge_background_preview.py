"""合并预览在页面刷新后复用解压结果，且不复制或改名原包。"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.conflict_resolution_service import ConflictResolutionService, MergePreviewJob
from app.core.extract_service import ExtractService


def make_job(service, tmp_path, status="completed"):
    source = tmp_path / "new"
    target = tmp_path / "old"
    source.mkdir()
    target.mkdir()
    (source / "new.txt").write_text("新版", encoding="utf-8")
    existing = {"path": str(target), "library_id": None, "library_type": "local", "stats": None}
    session = SimpleNamespace(id="session", staged_root=str(source), existing_path=str(target),
                              compare_items=[], workspace=str(source), conflict_id="conflict")
    service._merge_sessions[session.id] = session
    job = MergePreviewJob("job", "conflict", status=status, target_context=existing,
                          result={"session_id": session.id}, created_at=1, updated_at=1)
    service._merge_preview_jobs[job.id] = job
    return job, session, existing


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "completed"])
async def test_reopening_reuses_backend_job_even_when_display_stats_changed(tmp_path, status):
    service = ConflictResolutionService()
    job, session, existing = make_job(service, tmp_path, status)
    item = SimpleNamespace(id="conflict", new_path="source.zip")
    with patch.object(service, "describe_conflict_async", new=AsyncMock(return_value={
        "existing": {**existing, "stats": {"file_count": 5000}},
    })), patch.object(service, "_validate_merge_target", new=AsyncMock()), patch.object(
        service, "_run_merge_preview_worker", new=AsyncMock(),
    ) as worker:
        response = await service.start_merge_preview(item)
    assert response["job_id"] == job.id
    assert response["status"] == status
    worker.assert_not_called()
    service.cleanup_old_merge_preview_jobs(max_age_seconds=1)
    assert job.id in service._merge_preview_jobs
    assert service.list_merge_preview_jobs()[0]["target_context"]["path"] == existing["path"]
    assert "result" not in service.list_merge_preview_jobs()[0]


@pytest.mark.asyncio
async def test_refresh_only_compares_retained_extraction(tmp_path):
    service = ConflictResolutionService()
    job, session, existing = make_job(service, tmp_path)
    with patch.object(service, "describe_conflict_async", new=AsyncMock(return_value={"existing": existing})), patch.object(
        service, "_validate_merge_target", new=AsyncMock(),
    ), patch.object(service, "_load_existing_remote_items", new=AsyncMock(return_value=None)), patch.object(
        service, "_broadcast_merge_preview_job",
    ), patch.object(service, "_stage_new_source_with_progress", new=AsyncMock()) as extract:
        await service.start_merge_preview(SimpleNamespace(id="conflict", new_path="source.zip"), refresh=True)
        await service._merge_preview_workers[job.id]
    extract.assert_not_called()
    assert job.status == "completed"
    assert job.result["session_id"] == session.id
    assert job.result["summary"]["new_only"] == 1


def test_normal_archive_reads_original_path_without_copy(tmp_path):
    original = tmp_path / "source.zip"
    original.write_bytes(b"original")
    extractor = Mock()
    extractor._detect_volume_set.return_value = None
    assert ConflictResolutionService._prepare_merge_archive_source(extractor, str(original), str(tmp_path)) == str(original)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.zip"]


def test_special_volume_renames_only_link_entries(tmp_path):
    originals = [tmp_path / "source.zip", tmp_path / "source.002"]
    for path in originals:
        path.write_bytes(b"original")
    workspace = tmp_path / "workspace"
    extractor = Mock()
    extractor._detect_volume_set.return_value = SimpleNamespace(type="zip_numeric_split", volumes=list(map(str, originals)))
    view = ConflictResolutionService._prepare_merge_archive_source(extractor, str(originals[0]), str(workspace))
    from pathlib import Path
    Path(view).rename(workspace / "archive-view" / "source.zip.001")
    assert all(path.read_bytes() == b"original" for path in originals)
    assert (workspace / "archive-view" / "source.002").read_bytes() == b"original"


@pytest.mark.asyncio
async def test_staging_keeps_extracted_files_in_session_workspace(tmp_path):
    service = ConflictResolutionService()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = tmp_path / "temporary-extract"
    output.mkdir()
    (output / "payload.txt").write_text("内容", encoding="utf-8")
    extractor = Mock()
    extractor._detect_volume_set.return_value = None
    extractor.extract = AsyncMock(return_value=str(output))
    with patch("app.core.conflict_resolution_service.ExtractService", return_value=extractor), patch(
        "app.core.conflict_resolution_service.FilterService",
    ) as filter_service, patch.object(service, "_broadcast_merge_preview_job"), patch.object(
        service, "_copy_to_stage_with_budget", new=AsyncMock(),
    ) as copy:
        filter_service.return_value.filter = AsyncMock()
        root = await service._stage_new_source_with_progress(None, str(workspace), MergePreviewJob("job", "conflict"), "source.zip")
    copy.assert_not_called()
    task = extractor.extract.call_args.args[0]
    assert task.source_path == "source.zip"
    assert task.task_metadata["preserve_archive_source"] is True
    assert root == str(workspace / "extracted")
    assert (workspace / "extracted" / "payload.txt").exists()
    assert not output.exists()


@pytest.mark.asyncio
async def test_slow_magic_read_does_not_block_event_loop():
    extractor = ExtractService()
    event_loop_thread = threading.get_ident()
    read_threads = []

    def slow_read(path):
        read_threads.append(threading.get_ident())
        time.sleep(0.15)
        return b"PK\x03\x04"

    with patch.object(extractor, "_read_magic_header", side_effect=slow_read):
        worker = asyncio.create_task(extractor._detect_by_magic_bytes("slow-network-file"))
        await asyncio.sleep(0.02)
        assert not worker.done()
        assert await worker == "zip"
    assert read_threads and event_loop_thread not in read_threads
