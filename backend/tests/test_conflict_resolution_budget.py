from contextlib import asynccontextmanager

import pytest

from app.core.conflict_resolution_service import ConflictResolutionService


@pytest.mark.asyncio
async def test_copy_to_stage_file_uses_disk_io_budget(monkeypatch, tmp_path):
    service = ConflictResolutionService()
    source = tmp_path / "source.zip"
    target = tmp_path / "stage" / "source.zip"
    source.write_bytes(b"archive")
    calls = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    monkeypatch.setattr("app.core.conflict_resolution_service.get_resource_budget_service", lambda: Budget())

    await service._copy_to_stage_with_budget(
        str(source),
        str(target),
        is_dir=False,
        reason="conflict.stage_archive",
    )

    assert calls == [("disk_io_local", 1, "conflict.stage_archive")]
    assert target.read_bytes() == b"archive"


@pytest.mark.asyncio
async def test_copy_to_stage_directory_uses_disk_io_budget(monkeypatch, tmp_path):
    service = ConflictResolutionService()
    source = tmp_path / "source-dir"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (nested / "voice.wav").write_bytes(b"audio")
    target = tmp_path / "stage" / "source-dir"
    calls = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    monkeypatch.setattr("app.core.conflict_resolution_service.get_resource_budget_service", lambda: Budget())

    await service._copy_to_stage_with_budget(
        str(source),
        str(target),
        is_dir=True,
        reason="conflict.stage_dir",
    )

    assert calls == [("disk_io_local", 1, "conflict.stage_dir")]
    assert (target / "nested" / "voice.wav").read_bytes() == b"audio"
