import os
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api import routes as routes_module
from app.config import settings as settings_module
from app.models import database as database_module
from app.models.database import ProcessedArchive


@pytest.mark.asyncio
async def test_scan_processed_archives_aggregates_exe_e_volume_size_and_removes_member_record(
    tmp_path,
    db_session,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    exe = processed_dir / "RJ01629292.exe"
    e01 = processed_dir / "RJ01629292.e01"
    e02 = processed_dir / "RJ01629292.e02"
    exe.write_bytes(b"x" * 700)
    e01.write_bytes(b"y" * 701)
    e02.write_bytes(b"z" * 123)

    db_session.add(
        ProcessedArchive(
            id="stale-member-record",
            original_path=str(e01),
            current_path=str(e01),
            filename="RJ01629292.e01",
            rjcode="RJ01629292",
            file_size=701,
            processed_at=datetime.now(),
            process_count=1,
            task_id="",
            status="completed",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        settings_module,
        "get_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(processed_archives_path=str(processed_dir))
        ),
    )
    monkeypatch.setattr(
        routes_module,
        "get_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(processed_archives_path=str(processed_dir))
        ),
    )

    def fake_get_db():
        yield db_session

    monkeypatch.setattr(database_module, "get_db", fake_get_db)

    await routes_module.scan_processed_archives()

    records = db_session.query(ProcessedArchive).all()
    assert len(records) == 1
    assert records[0].filename == "RJ01629292.exe"
    assert records[0].current_path == str(exe)
    assert records[0].file_size == 1524
    assert records[0].volume_count == 3


@pytest.mark.asyncio
async def test_scan_processed_archives_skips_active_deferred_target_group(
    tmp_path,
    db_session,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    exe = processed_dir / "RJ00009999.exe"
    e01 = processed_dir / "RJ00009999.e01"
    exe.write_bytes(b"x" * 700)
    e01.write_bytes(b"y" * 701)

    monkeypatch.setattr(
        routes_module,
        "get_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(processed_archives_path=str(processed_dir))
        ),
    )

    class FakeDeferredArchiveService:
        def active_target_paths_sync(self):
            return {
                str(exe.resolve()).casefold(),
                str(e01.resolve()).casefold(),
            }

    monkeypatch.setattr(
        "app.core.deferred_archive_service.get_deferred_archive_service",
        lambda: FakeDeferredArchiveService(),
    )

    def fake_get_db():
        yield db_session

    monkeypatch.setattr(database_module, "get_db", fake_get_db)

    await routes_module.scan_processed_archives()

    assert db_session.query(ProcessedArchive).filter(
        ProcessedArchive.current_path.in_([str(exe), str(e01)])
    ).count() == 0


@pytest.mark.asyncio
async def test_scan_processed_archives_keeps_records_when_directory_listing_fails(
    tmp_path,
    db_session,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    archive_path = processed_dir / "RJ01629292.zip"
    archive_path.write_bytes(b"payload")
    db_session.add(
        ProcessedArchive(
            id="keep-on-scan-error",
            original_path=str(archive_path),
            current_path=str(archive_path),
            filename=archive_path.name,
            rjcode="RJ01629292",
            file_size=archive_path.stat().st_size,
            processed_at=datetime.now(),
            process_count=1,
            task_id="",
            status="completed",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        routes_module,
        "get_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(processed_archives_path=str(processed_dir))
        ),
    )

    class FakeDeferredArchiveService:
        def active_target_paths_sync(self):
            return set()

    monkeypatch.setattr(
        "app.core.deferred_archive_service.get_deferred_archive_service",
        lambda: FakeDeferredArchiveService(),
    )

    def fake_get_db():
        yield db_session

    monkeypatch.setattr(database_module, "get_db", fake_get_db)
    monkeypatch.setattr(routes_module.os, "listdir", lambda _path: (_ for _ in ()).throw(OSError("SMB unavailable")))

    await routes_module.scan_processed_archives()

    assert db_session.query(ProcessedArchive).filter_by(id="keep-on-scan-error").count() == 1


@pytest.mark.asyncio
async def test_scan_processed_archives_keeps_records_when_member_stat_fails(
    tmp_path,
    db_session,
    monkeypatch,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    archive_path = processed_dir / "RJ01629293.zip"
    archive_path.write_bytes(b"payload")
    db_session.add(
        ProcessedArchive(
            id="keep-on-stat-error",
            original_path=str(archive_path),
            current_path=str(archive_path),
            filename=archive_path.name,
            rjcode="RJ01629293",
            file_size=archive_path.stat().st_size,
            processed_at=datetime.now(),
            process_count=1,
            task_id="",
            status="completed",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        routes_module,
        "get_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(processed_archives_path=str(processed_dir))
        ),
    )

    class FakeDeferredArchiveService:
        def active_target_paths_sync(self):
            return set()

    monkeypatch.setattr(
        "app.core.deferred_archive_service.get_deferred_archive_service",
        lambda: FakeDeferredArchiveService(),
    )

    def fake_get_db():
        yield db_session

    real_getsize = routes_module.os.path.getsize
    normalized_archive = os.path.normcase(os.path.abspath(str(archive_path)))

    def fail_member_stat(path):
        if os.path.normcase(os.path.abspath(str(path))) == normalized_archive:
            raise OSError("SMB stat unavailable")
        return real_getsize(path)

    monkeypatch.setattr(database_module, "get_db", fake_get_db)
    monkeypatch.setattr(routes_module.os.path, "getsize", fail_member_stat)

    await routes_module.scan_processed_archives()

    assert db_session.query(ProcessedArchive).filter_by(id="keep-on-stat-error").count() == 1
