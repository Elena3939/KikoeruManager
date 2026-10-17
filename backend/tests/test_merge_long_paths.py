import shutil
import zipfile
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.conflict_resolution_service import ConflictResolutionService, MergePreviewJob
from app.core.extract_service import ArchiveInfo, ExtractService


def test_long_names_keep_extension_hierarchy_and_distinct_targets():
    service = ExtractService()
    prefix = "很长的音频文件名" * 35
    names = [f"RJ01731933/mp3/{prefix}{suffix}.mp3" for suffix in ["甲", "乙"]]
    info = ArchiveInfo("RJ01731933.7z", [{"name": name, "size": 3} for name in names])
    remap = service._build_long_component_path_remap(info)
    targets = [service._remap_archive_relative_path(name, remap) for name in names]
    assert remap is not None
    assert targets[0] != targets[1]
    for target in targets:
        assert target.startswith("RJ01731933/mp3/")
        assert target.endswith(".mp3")
        assert all(len(part.encode("utf-8")) <= service.PATH_COMPONENT_SAFE_BYTES for part in target.split("/"))


def test_normal_archives_do_not_enable_path_remapping():
    service = ExtractService()
    info = ArchiveInfo("normal.zip", [{"name": "RJ01731933/track.mp3", "size": 3}])
    assert service._build_long_component_path_remap(info) is None
    assert service._remap_archive_relative_path("../outside.mp3", {"root_from": "", "root_to": ""}) is None


@pytest.mark.asyncio
async def test_real_7z_stream_extracts_long_file_and_nested_directory(tmp_path):
    executable = shutil.which("7zz") or shutil.which("7z")
    if not executable:
        pytest.skip("当前环境未安装 7z")
    service = ExtractService()
    archive = tmp_path / "source.zip"
    payloads = {
        f"RJ01731933/{'长目录' * 35}/{'音频文件' * 35}.mp3": b"audio-one",
        f"RJ01731933/{'长目录' * 35}/{'音频文件' * 35}乙.mp3": b"audio-two",
        "other/normal.txt": b"normal",
    }
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in payloads.items():
            output.writestr(name, data)
    info = ArchiveInfo(str(archive), [{"name": name, "size": len(data), "is_dir": False} for name, data in payloads.items()])
    task = Mock()
    task.task_metadata = {}
    task.progress = 0
    task.is_cancelled.return_value = False
    task.wait_if_paused = AsyncMock()
    output_path = tmp_path / "out"
    with patch.object(service, "_find_7z_executable", return_value=executable), patch.object(
        service, "_reject_if_garbled_after_extract", new=AsyncMock(return_value=False),
    ):
        success, reason = await service._try_extract_with_path_remap(info, str(output_path), "", task)
    assert (success, reason) == (True, "")
    for name, data in payloads.items():
        mapped = service._remap_archive_relative_path(name, info.path_remap)
        assert (output_path / mapped).read_bytes() == data
    assert len(list(output_path.rglob("*.mp3"))) == 2
    assert not list(output_path.rglob("*.part"))
    assert archive.is_file()


def test_merge_failure_preserves_failed_stage_and_error():
    service = ConflictResolutionService()
    job = MergePreviewJob(
        id="job", conflict_id="conflict", status="running", stage="extract",
        stage_label="解压新包", message="", percent=35, created_at=0, updated_at=0,
    )
    with patch.object(service, "_broadcast_merge_preview_job"):
        service._fail_merge_preview_job(job, "文件名过长")
    snapshot = service._serialize_merge_preview_job(job)
    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "解压新包失败：文件名过长"
    assert snapshot["message"] == snapshot["error"]
