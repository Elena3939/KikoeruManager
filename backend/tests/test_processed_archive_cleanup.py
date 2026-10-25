from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.core import processed_archive_cleanup as cleanup_module
from app.models.database import ProcessedArchive


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", [True, False])
async def test_cleanup_skips_archive_with_active_deferred_target(
    db_session,
    tmp_path,
    monkeypatch,
    protected,
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    main_path = processed_dir / "RJ01629296.zip"
    volume_path = processed_dir / "RJ01629296.z01"
    main_path.write_bytes(b"main")
    volume_path.write_bytes(b"volume")

    db_session.add(
        ProcessedArchive(
            id="cleanup-active-target",
            original_path=str(main_path),
            current_path=str(main_path),
            filename=main_path.name,
            rjcode="RJ01629296",
            file_size=main_path.stat().st_size + volume_path.stat().st_size,
            volume_count=2,
            archive_manifest=[
                {"target_path": str(main_path), "state": "completed"},
                {"target_path": str(volume_path), "state": "completed"},
            ],
            processed_at=datetime.now() - timedelta(days=1),
            process_count=1,
            task_id="",
            status="completed",
        )
    )
    db_session.commit()

    config = SimpleNamespace(
        processed_archive_cleanup=SimpleNamespace(
            enabled=True,
            exclude_reprocessing=True,
            strategy="age",
            preserve_days=0,
            max_count=1,
            max_size_gb=1,
        )
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.connection(),
    )

    def fake_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    class FakeDeferredArchiveService:
        def active_target_paths_sync(self):
            return {str(main_path.resolve()).casefold()} if protected else set()

        def is_target_claimed_sync(self, path):
            return protected and str(path).casefold() == str(main_path).casefold()

    monkeypatch.setattr(cleanup_module, "get_config", lambda: config)
    monkeypatch.setattr(cleanup_module, "get_db", fake_get_db)
    monkeypatch.setattr(
        "app.core.deferred_archive_service.get_deferred_archive_service",
        lambda: FakeDeferredArchiveService(),
    )

    cleaned = []
    monkeypatch.setattr(
        "app.core.filter_recovery_service.get_filter_recovery_service",
        lambda: SimpleNamespace(cleanup_archive=lambda archive: cleaned.append(archive["id"])),
    )
    result = await cleanup_module.ProcessedArchiveCleanupService().cleanup_archives()

    assert result["deleted_count"] == (0 if protected else 1)
    assert main_path.exists() == protected
    assert volume_path.exists() == protected
    assert cleaned == ([] if protected else ["cleanup-active-target"])
    assert db_session.query(ProcessedArchive).filter_by(id="cleanup-active-target").count() == (1 if protected else 0)
