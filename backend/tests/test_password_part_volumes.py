"""带密码提示的 RAR 分卷必须按真实卷号组合，不能把密码当卷号。"""
import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.archive_volume_utils import (
    detect_archive_volume_group,
    get_archive_total_size,
    normalize_part_volume_filename,
)
from app.core.extract_service import ArchiveInfo, ExtractService
from app.core.file_processor import FileProcessor
from app.core.task_engine import Task, TaskType
from app.core.watcher import ArchiveHandler


@pytest.mark.parametrize("name,expected", [
    ("RJ01519258.part1(1615141).rar", "RJ01519258(1615141).part1.rar"),
    ("RJ01519258.part02(1615141).rar(1615141)", "RJ01519258(1615141).part02.rar"),
    ("RJ01519258.part1.rar(1615141)", "RJ01519258(1615141).part1.rar"),
    ("RJ01519258(1615141).part1.rar", "RJ01519258(1615141).part1.rar"),
    ("RJ01519258.part1(a).rar(b)", "RJ01519258.part1(a).rar(b)"),
    ("RJ01519258.part1.rar", "RJ01519258.part1.rar"),
    ("RJ01519258(1615141).7z.001", "RJ01519258(1615141).7z.001"),
])
def test_normalized_name(name, expected):
    assert normalize_part_volume_filename(name) == expected


def make_volumes(tmp_path, indices=(1, 2), suffix=""):
    paths = []
    for index in indices:
        path = tmp_path / f"RJ01519258.part{index}(1615141).rar{suffix}"
        path.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"x" * 1024)
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("suffix", ["", "(1615141)"])
def test_grouping_and_entry_filter(tmp_path, suffix):
    paths = make_volumes(tmp_path, (1, 2, 10), suffix)
    (tmp_path / "RJ01519258.part3(other).rar").write_bytes(b"other")
    processor, service = FileProcessor(), ExtractService()
    assert processor.is_archive(paths[0])
    assert not processor.is_archive(paths[1])
    assert not processor.is_archive(paths[2])
    for path in paths:
        group = detect_archive_volume_group(path)
        assert group.volumes == paths
        assert group.main_path == paths[0]
        for detected in (processor.detect_volume_set(path), service._detect_volume_set(path)):
            assert detected.type == "part_password"
            assert detected.volumes == paths
            assert detected.entry_path == paths[0]
    assert get_archive_total_size(paths[0]) == sum(os.path.getsize(path) for path in paths)
    mark = Mock()
    handler = ArchiveHandler(Mock(), lambda: set(), lambda: False, mark)
    handler._mark_volume_file_processed(paths[1])
    mark.assert_called_once_with(paths[1])


@pytest.mark.asyncio
async def test_normalize_preserves_original_names(tmp_path):
    paths = make_volumes(tmp_path, suffix="(1615141)")
    service = ExtractService()
    assert await service.normalize_archive_filename(paths[0]) == paths[0]
    assert await service._repair_extension(paths[0]) == paths[0]
    assert all(Path(path).is_file() for path in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_view_cleanup_preserves_sources(tmp_path, monkeypatch, outcome):
    paths = make_volumes(tmp_path)
    service = ExtractService()
    task = Task(task_type=TaskType.EXTRACT, source_path=paths[0])
    view_dir = tmp_path / "view"

    async def create_dir(*args):
        view_dir.mkdir()
        return str(view_dir)

    monkeypatch.setattr(service, "_create_temp_dir_with_fallback", create_dir)

    async def extract(task):
        group = service._detect_volume_set(task.source_path)
        view = await service._prepare_password_part_volume_view(group, task)
        assert task.source_path == paths[0]
        assert [Path(path).name for path in view.volumes] == [
            "RJ01519258(1615141).part1.rar", "RJ01519258(1615141).part2.rar",
        ]
        assert all(Path(path).read_bytes() == Path(source).read_bytes()
                   for path, source in zip(view.volumes, paths))
        if outcome == "failure":
            raise ValueError("模拟预读取失败")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return "output"

    monkeypatch.setattr(service, "_extract", extract)
    if outcome == "success":
        assert await service.extract(task) == "output"
    else:
        with pytest.raises(ValueError if outcome == "failure" else asyncio.CancelledError):
            await service.extract(task)
    assert not view_dir.exists()
    assert all(Path(path).is_file() for path in paths)
    assert "password_part_volume_view" not in task.task_metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [(2, 3), (1, 3)])
async def test_missing_volume_fails_before_linking(tmp_path, indices):
    paths = make_volumes(tmp_path, indices)
    service = ExtractService()
    task = Task(task_type=TaskType.EXTRACT, source_path=paths[0])
    with pytest.raises(ValueError, match="分卷"):
        await service._prepare_password_part_volume_view(service._detect_volume_set(paths[0]), task)
    assert task.task_metadata["extract_failure_reason"] == "volume_incomplete"


@pytest.mark.asyncio
async def test_missing_volume_is_not_cached_as_wrong_password(tmp_path, monkeypatch):
    paths = make_volumes(tmp_path)
    service = ExtractService()
    task = Task(task_type=TaskType.EXTRACT, source_path=paths[0])
    error = b"Missing volume : next.rar\nData Error in encrypted file. Wrong password?"
    assert not service._looks_like_wrong_password_error(error.decode())
    monkeypatch.setattr(service, "_probe_password", AsyncMock(return_value="ok"))
    monkeypatch.setattr(service, "_run_7z_command", AsyncMock(
        return_value=subprocess.CompletedProcess([], 2, b"", error),
    ))
    negative = Mock()
    monkeypatch.setattr(service, "_remember_negative_password", negative)
    monkeypatch.setattr(service, "_cleanup_extract_attempt", AsyncMock())
    task.task_metadata.update(manual_retry_passwords=["1615141"], manual_retry_password_only=True)
    result = await service._try_extract(
        ArchiveInfo(paths[0], []), str(tmp_path / "output"), task, password_candidates=[],
    )
    assert result == (False, None, "volume_incomplete")
    negative.assert_not_called()
