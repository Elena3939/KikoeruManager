"""PikPak 转存清理、文件选择和断点恢复的故障回归。"""
import asyncio
from pathlib import Path

import pytest

from app.core.http_download_service import HttpDownloadError, HttpDownloadService
from app.core.task_engine import Task, TaskType
from tests.test_http_download_service import bind_config


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("complete", "completed"), ("error", "failed"), ("cancel", "cancelled")],
)
@pytest.mark.asyncio
async def test_cleanup_includes_materialized_file_excluded_from_download(monkeypatch, tmp_path, outcome, expected_status):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    selected = {"source": "pikpak", "file_id": "part-1", "share_id": "share"}
    task = Task(task_type=TaskType.HTTP_DOWNLOAD, source_path="pikpak", metadata={
        "urls": ["https://mypikpak.com/s/share"],
        "selected_items": [selected],
        "selected_keys": [service._preview_item_selection_key(selected)],
        "pikpak_retry_rebuild_share": True,
    })
    deleted = []
    source_rows = []
    for number in (1, 2):
        source_rows.append({
            "source": "pikpak", "file_id": f"part-{number}", "share_id": "share",
            "pikpak_cleanup_file_id": f"copy-{number}", "pikpak_materialized": True,
            "pikpak_account_id": f"account-{number}",
        })

    async def preview(*_args, **kwargs):
        assert kwargs["selected_items"] == [selected]
        return {
            "items": [{
                **row, "ok": True, "filename": f"pack.7z.00{index}",
                "relative_path": f"pack.7z.00{index}",
                "final_path": str(tmp_path / f"pack.7z.00{index}"),
                "target_dir": str(tmp_path), "size_bytes": 100,
                "url": f"https://cdn.test/{index}", "masked_url": f"https://cdn.test/{index}",
            } for index, row in enumerate(source_rows, 1)],
            "source_items": source_rows, "source_modes": ["pikpak"], "resolved_urls": [],
        }

    async def rpc(method, params):
        if method == "aria2.addUri":
            assert params[0] == ["https://cdn.test/1"]
            if outcome == "cancel":
                raise asyncio.CancelledError()
            return "gid-1"
        if method == "aria2.tellStatus":
            return {"status": outcome, "totalLength": "100", "completedLength": "100" if outcome == "complete" else "67", "errorMessage": "timed out"}
        return []

    async def delete(ids, *, account_id, permanent):
        assert permanent is True
        deleted.append((account_id, ids))
        return {"deleted_count": len(ids)}

    monkeypatch.setattr(service, "preview_urls", preview)
    monkeypatch.setattr(service, "_rpc_call", rpc)
    monkeypatch.setattr(service, "delete_pikpak_transfer_items", delete)
    if expected_status == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await service.start_download_task(task)
    elif expected_status == "failed":
        with pytest.raises(HttpDownloadError, match="timed out"):
            await service.start_download_task(task)
    else:
        result = await service.start_download_task(task)
        assert result["status"] == expected_status
    assert sorted(deleted) == [("account-1", ["copy-1"]), ("account-2", ["copy-2"])]
    assert task.task_metadata["pikpak_cleanup_result"]["requested_count"] == 2


def test_pikpak_selection_uses_file_id_without_expanding_shared_directory():
    service = HttpDownloadService()
    selected = {"source": "pikpak", "file_id": "part-1", "relative_dir": "pack", "name": "a.001"}
    selection = service._selection_filter_from_items([selected])
    assert service._share_item_matches_selection("pikpak", {"id": "part-1", "name": "a.001", "_relative_dir": "pack"}, selection)
    assert not service._share_item_matches_selection("pikpak", {"id": "part-2", "name": "a.002", "_relative_dir": "pack"}, selection)


def test_pikpak_selection_survives_old_key_and_reports_missing_file():
    service = HttpDownloadService()
    selected = [
        {"source": "pikpak", "file_id": "part-1", "selection_key": "old-key", "custom_name": "自定义"},
        {"source": "pikpak", "file_id": "part-2", "name": "missing.002"},
    ]
    result = service.filter_preview_selection({"items": [{"source": "pikpak", "file_id": "part-1", "ok": True}]}, selected_items=selected)
    assert result["ok_count"] == 1
    assert result["failed_count"] == 1
    assert result["items"][0]["custom_name"] == "自定义"
    assert result["items"][1]["file_id"] == "part-2"
    assert "找不到已选文件" in result["items"][1]["reason"]


@pytest.mark.parametrize(("attempt", "split"), [(0, "5"), (1, "2"), (2, "1"), (100, "1")])
def test_pikpak_retry_reduces_connections_without_changing_proxy(monkeypatch, tmp_path, attempt, split):
    bind_config(monkeypatch, tmp_path, split=5, max_connection_per_server=8, proxy_url="http://proxy.test:7890")
    options = HttpDownloadService()._aria2_options({"source": "pikpak", "filename": "part.001", "pikpak_retry_attempt": attempt}, str(tmp_path))
    assert options["split"] == split
    assert options["continue"] == "true"
    assert "all-proxy" not in options
    if attempt:
        assert options["max-connection-per-server"] == split
        assert options["timeout"] == "120"
        assert options["connect-timeout"] == "30"


def test_resume_progress_requires_matching_path_and_control_file(tmp_path):
    service = HttpDownloadService()
    path = tmp_path / "part.001"
    path.write_bytes(b"x" * 100)
    item = {"source": "pikpak", "file_id": "part-1", "size_bytes": 100, "final_path": str(path)}
    metadata = {"selected_items": [{**item, "local_path": str(path), "downloaded": 67}]}
    assert service._pikpak_resume_bytes(item, metadata) == 0
    Path(str(path) + ".aria2").write_bytes(b"control")
    assert service._pikpak_resume_bytes(item, metadata) == 67
    metadata["selected_items"][0]["local_path"] = str(tmp_path / "different.001")
    assert service._pikpak_resume_bytes(item, metadata) == 0


@pytest.mark.asyncio
async def test_pikpak_timeout_records_diagnostics_without_signed_url(monkeypatch, tmp_path, caplog):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    path = tmp_path / "part.001"
    path.write_bytes(b"partial")
    Path(str(path) + ".aria2").write_bytes(b"control")
    async def status(_gid):
        return {"status": "error", "totalLength": "100", "completedLength": "67", "errorMessage": "timed out", "errorCode": "2", "connections": "5"}
    monkeypatch.setattr(service, "_tell_status", status)
    rows, _, done, failed = await service._poll_task(["gid"], [{
        "gid": "gid", "source": "pikpak", "local_path": str(path),
        "original_url": "https://cdn.test/file?token=secret",
    }])
    assert done and failed == 1
    assert rows[0]["aria2_error_code"] == "2"
    assert rows[0]["resume_available"] is True
    assert "断点文件已保留" in rows[0]["failure_reason"]
    assert "connections=5" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_retry_task_starts_at_saved_progress_and_keeps_it_during_aria2_initialization(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    path = tmp_path / "pack.001"
    path.write_bytes(b"x" * 100)
    Path(str(path) + ".aria2").write_bytes(b"control")
    selected = {"source": "pikpak", "file_id": "part-1", "local_path": str(path), "downloaded": 67}
    task = Task(task_type=TaskType.HTTP_DOWNLOAD, source_path="pikpak", metadata={
        "urls": ["https://mypikpak.com/s/share"], "selected_items": [selected], "retry_count": 1,
    })
    item = {
        "source": "pikpak", "file_id": "part-1", "ok": True,
        "filename": path.name, "relative_path": path.name, "final_path": str(path),
        "target_dir": str(tmp_path), "size_bytes": 100,
        "url": "https://cdn.test/file", "masked_url": "https://cdn.test/file",
    }
    async def preview(*_args, **_kwargs):
        return {"items": [item], "source_items": [], "source_modes": ["pikpak"]}
    polls = 0
    async def rpc(method, params):
        nonlocal polls
        if method == "aria2.addUri":
            assert params[1]["timeout"] == "120"
            return "gid"
        if method == "aria2.tellStatus":
            polls += 1
            assert task.progress == 67
            assert task.task_metadata["download_files"][0]["downloaded"] == 67
            return {"status": "active" if polls == 1 else "complete", "totalLength": "100", "completedLength": "0" if polls == 1 else "100"}
        return []
    monkeypatch.setattr(service, "preview_urls", preview)
    monkeypatch.setattr(service, "_rpc_call", rpc)
    result = await service.start_download_task(task)
    assert polls == 2
    assert result["status"] == "completed"
    assert task.progress == 100
    assert path.read_bytes() == b"x" * 100
