"""ZSTD 大条目必须实际交给兼容后端，不能把未知探测当作算法不支持。"""

import subprocess
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.extract_service import ArchiveInfo, ExtractService
from app.core.task_engine import Task, TaskType


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome, expected_reason",
    [
        ("success", ""),
        ("incomplete", "extract_incomplete"),
        ("unsupported", "unsupported_method"),
        ("cancelled", "cancelled"),
        ("missing", "unsupported_method"),
    ],
)
async def test_large_encrypted_zstd_uses_compatible_backend(tmp_path, monkeypatch, outcome, expected_reason):
    archive = tmp_path / "RJ01412685_2.7z"
    archive.write_bytes(b"7z")
    info = ArchiveInfo(
        str(archive),
        [{"name": "RJ01412685.zip", "size": 4890902500, "is_dir": False, "encrypted": True}],
    )
    info.method = "04F71101 7zAES"
    task = Task(task_type=TaskType.EXTRACT, source_path=str(archive))
    service = ExtractService()
    monkeypatch.setattr(service, "_ensure_7z_zstd_available", AsyncMock(return_value=outcome != "missing"))
    monkeypatch.setattr(service, "_find_7z_zstd_executable", Mock(return_value="7zzs"))
    monkeypatch.setattr(service.config.extract, "seven_zip_zstd_path", "7zzs")
    monkeypatch.setattr(service, "_probe_7z_no_password_status", AsyncMock(return_value="encrypted"))
    monkeypatch.setattr(service, "_get_rj_passwords", Mock(return_value=[]))
    monkeypatch.setattr(service.config.extract, "password_list", [])
    monkeypatch.setattr(service, "_archive_fingerprint", Mock(return_value=None))
    monkeypatch.setattr(service, "_cleanup_extract_attempt", AsyncMock())
    monkeypatch.setattr(service, "_reject_if_garbled_after_extract", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_verify_extraction", AsyncMock(return_value=outcome != "incomplete"))
    monkeypatch.setattr(service, "_finalize_successful_extract_password", AsyncMock())
    monkeypatch.setattr(service, "_probe_by_smallest_entry", AsyncMock(side_effect=AssertionError("没有小条目")))
    monkeypatch.setattr(service, "_probe_by_full_test", AsyncMock(side_effect=AssertionError("不应整包探测")))
    commands = []

    async def run(cmd, **kwargs):
        assert cmd[1] == "x"
        assert kwargs["task"] is task
        commands.append(cmd)
        if cmd[0] != "7zzs":
            return subprocess.CompletedProcess(cmd, 2, b"", b"Unsupported Method")
        if outcome == "cancelled":
            monkeypatch.setattr(task, "is_cancelled", lambda: True)
        if "-pcorrect" not in cmd:
            return subprocess.CompletedProcess(cmd, 2, b"", b"Wrong password")
        error = b"Unsupported Method" if outcome == "unsupported" else b""
        return subprocess.CompletedProcess(cmd, 2 if error else 0, b"", error)

    monkeypatch.setattr(service, "_run_7z_command", AsyncMock(side_effect=run))
    result = await service._try_extract(
        info, str(tmp_path / "output"), task,
        password_candidates=[
            {"password": "wrong", "source": "文件名"},
            {"password": "correct", "source": "文件名"},
        ],
    )
    assert result == (outcome == "success", "correct" if outcome == "success" else None, expected_reason)
    assert all(cmd[0] == "7zzs" for cmd in commands)
    if outcome == "missing":
        assert commands == []
    elif outcome == "cancelled":
        assert len(commands) == 1
    else:
        assert len(commands) == 2
    if outcome != "success":
        service._finalize_successful_extract_password.assert_not_awaited()
        assert not task.task_metadata.get("extract_zstd_backend_success")
    else:
        assert task.task_metadata["extract_zstd_backend_success"] is True
        service._verify_extraction.assert_awaited_once_with(info, str(tmp_path / "output"))
