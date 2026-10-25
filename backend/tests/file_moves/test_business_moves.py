"""无需数据库的文件事务边界回归。"""
import asyncio
import hashlib
import threading

import pytest

from app.core import staged_file_move as fs
from app.core.browser_upload_storage import install_local
from app.core.deferred_archive_service import DeferredArchiveService
from app.core.host_file_move_client import HostMoveClient, HostMoveError
from app.core.file_move_protocol import identity


def test_upload_cancel_scope_blocks_same_directory_publish(tmp_path):
    source, target = tmp_path / "upload.part", tmp_path / "final"
    source.write_bytes(b"keep")
    cancelled = threading.Event()
    cancelled.set()
    token = fs._cancel_scope.set(cancelled)
    try:
        with pytest.raises(asyncio.CancelledError):
            install_local(tmp_path, tmp_path, "final", source,
                          hashlib.sha256(b"keep").hexdigest(), "replace", lambda: None, lambda _: None)
    finally:
        fs._cancel_scope.reset(token)
    assert source.read_bytes() == b"keep" and not target.exists()


def test_clone_records_destination_before_release_failure(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"keep")
    client = HostMoveClient("unused")
    created = []

    def request(action, **payload):
        if action == "prepare":
            from pathlib import Path
            pending = Path(payload["destination"])
            pending.write_bytes(source.read_bytes())
            return {"destination_identity": identity(pending)}
        if action == "release":
            raise HostMoveError("模拟断线")
        return {"state": "cancelled"}

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(HostMoveError):
        client.clone(source, target, "version", lambda: None, on_created=created.append)
    assert created and created[0]["inode"] == identity(target)["inode"]
    assert source.read_bytes() == target.read_bytes() == b"keep"


def test_archive_stage_hash_preserves_source(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(fs, "move_config", lambda: SimpleNamespace(host_enabled=False))
    source, stage = tmp_path / "source", tmp_path / "stage"
    source.write_bytes(b"archive" * 1024)
    service = DeferredArchiveService()
    checksum = service._copy_to_part(str(source), str(stage), lambda _: "")
    assert checksum == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.read_bytes() == stage.read_bytes()


def test_archive_existing_stage_is_not_deleted(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(fs, "move_config", lambda: SimpleNamespace(host_enabled=False))
    source, stage = tmp_path / "source", tmp_path / "stage"
    source.write_bytes(b"archive")
    stage.write_bytes(b"other operation")
    with pytest.raises(FileExistsError):
        DeferredArchiveService()._copy_to_part(str(source), str(stage), lambda _: "")
    assert stage.read_bytes() == b"other operation"


def test_archive_retry_rebuilds_owned_stage_after_interruption(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(fs, "move_config", lambda: SimpleNamespace(host_enabled=False))
    source, stage = tmp_path / "source", tmp_path / "stage"
    source.write_bytes(b"archive" * 1024)
    service = DeferredArchiveService()
    checksum = service._copy_to_part(str(source), str(stage), lambda _: "")
    assert service._copy_to_part(str(source), str(stage), lambda _: "") == checksum
    assert stage.read_bytes() == source.read_bytes()


def test_archive_changed_source_does_not_delete_owned_stage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(fs, "move_config", lambda: SimpleNamespace(host_enabled=False))
    source, stage = tmp_path / "source", tmp_path / "stage"
    source.write_bytes(b"archive")
    service = DeferredArchiveService()
    service._copy_to_part(str(source), str(stage), lambda _: "")
    source.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="来源发生变化"):
        service._copy_to_part(str(source), str(stage), lambda _: "")
    assert stage.read_bytes() == b"archive"
