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
