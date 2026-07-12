import asyncio
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from app.core import deferred_archive_service as deferred_archive_module
from app.models.database import DeferredArchiveJob, ProcessedArchive


def _configure_service(monkeypatch, db_session, source_dir, processed_dir, tmp_path):
    # 绑定测试已打开的外层事务，避免归档 worker 的独立 commit 污染后续用例。
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.connection(),
    )
    config = SimpleNamespace(
        processing=SimpleNamespace(
            archive_idle_delay_seconds=0,
            archive_poll_interval_seconds=1,
            archive_retry_delay_seconds=5,
            archive_max_retry_count=3,
        ),
        storage=SimpleNamespace(
            input_path=str(source_dir),
            processed_archives_path=str(processed_dir),
            temp_path=str(tmp_path / "temp"),
            library_path=str(tmp_path / "library"),
            existing_folders_path=str(tmp_path / "existing"),
        ),
    )
    monkeypatch.setattr(deferred_archive_module, "SessionLocal", session_factory)
    monkeypatch.setattr(deferred_archive_module, "get_config", lambda: config)
    monkeypatch.setattr(
        "app.core.task_center_event_service.broadcast_processed_archive_changed",
        lambda *_args, **_kwargs: None,
    )
    service = deferred_archive_module.DeferredArchiveService()
    monkeypatch.setattr(service, "_has_foreground_work", lambda: False)
    return service, session_factory


def test_deferred_archive_enqueue_is_idempotent_and_claims_all_volumes(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    exe = source_dir / "RJ01629292.exe"
    e01 = source_dir / "RJ01629292.e01"
    e02 = source_dir / "RJ01629292.e02"
    exe.write_bytes(b"x" * 700)
    e01.write_bytes(b"y" * 701)
    e02.write_bytes(b"z" * 123)

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )

    created = service.enqueue_sync(str(exe), task_id="archive-size-task")
    replayed = service.enqueue_sync(str(exe), task_id="archive-size-task")

    assert created["queued"] is True
    assert created["replayed"] is False
    assert created["volume_count"] == 3
    assert replayed["queued"] is True
    assert replayed["replayed"] is True
    assert replayed["job_id"] == created["job_id"]
    assert service.is_source_claimed_sync(str(exe)) is True
    assert service.is_source_claimed_sync(str(e01)) is True
    assert service.is_source_claimed_sync(str(e02)) is True

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=created["job_id"]).one()
        assert job.status == "pending"
        assert len(job.source_manifest) == 3
        assert len(job.target_manifest) == 3
        assert all(item["state"] == "pending" for item in job.target_manifest)
        assert db.query(ProcessedArchive).count() == 0
    finally:
        db.close()

    assert all(path.exists() for path in (exe, e01, e02))
    assert list(processed_dir.iterdir()) == []


def test_deferred_archive_completes_volume_group_before_creating_processed_record(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    exe = source_dir / "RJ01629292.exe"
    e01 = source_dir / "RJ01629292.e01"
    e02 = source_dir / "RJ01629292.e02"
    exe.write_bytes(b"x" * 700)
    e01.write_bytes(b"y" * 701)
    e02.write_bytes(b"z" * 123)

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    queued = service.enqueue_sync(str(exe), task_id="archive-size-task")
    claim = service._claim_next_job_sync()

    assert claim is not None
    assert claim["job_id"] == queued["job_id"]
    for index, source in enumerate(claim["source_manifest"]):
        service._move_member_sync(claim["job_id"], claim["lease_epoch"], index, source)

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        assert job.status == "processing"
        assert all(item["state"] == "completed" for item in job.target_manifest)
        assert db.query(ProcessedArchive).count() == 0
    finally:
        db.close()

    completed = service._complete_job_sync(claim["job_id"], claim["lease_epoch"])

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        archive = db.query(ProcessedArchive).filter_by(current_path=str(processed_dir / "RJ01629292.exe")).one()
        assert completed["status"] == "completed"
        assert job.status == "completed"
        assert archive.file_size == 1524
        assert archive.volume_count == 3
        assert [item["state"] for item in archive.archive_manifest] == [
            "completed",
            "completed",
            "completed",
        ]
    finally:
        db.close()

    assert sorted(path.name for path in processed_dir.iterdir()) == [
        "RJ01629292.e01",
        "RJ01629292.e02",
        "RJ01629292.exe",
    ]
    assert not any(path.exists() for path in (exe, e01, e02))
    assert service.is_source_claimed_sync(str(exe)) is False


def test_deferred_archive_recovers_published_member_without_losing_source(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / "RJ01629292.zip"
    source.write_bytes(b"recoverable payload")

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    queued = service.enqueue_sync(str(source), task_id="archive-recovery-task")
    claim = service._claim_next_job_sync()
    assert claim is not None
    target_path = claim["target_manifest"][0]["target_path"]
    with open(source, "rb") as reader, open(target_path, "wb") as writer:
        writer.write(reader.read())
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        target_manifest = [dict(item) for item in job.target_manifest]
        target_manifest[0].update({"state": "published", "sha256": checksum})
        job.target_manifest = target_manifest
        db.commit()
    finally:
        db.close()

    service._move_member_sync(
        claim["job_id"], claim["lease_epoch"], 0, claim["source_manifest"][0]
    )

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        assert job.target_manifest[0]["state"] == "completed"
        assert db.query(ProcessedArchive).count() == 0
    finally:
        db.close()

    assert not source.exists()
    assert (processed_dir / source.name).read_bytes() == b"recoverable payload"


def test_deferred_archive_cancel_pending_job_keeps_source_and_releases_claim(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / "RJ01629294.zip"
    source.write_bytes(b"cancelled payload")

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    queued = service.enqueue_sync(str(source), task_id="archive-cancel-task")

    assert service.is_source_claimed_sync(str(source)) is True
    assert service.request_cancel_sync(queued["job_id"]) is True

    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        assert job.status == "cancelled"
        assert job.cancel_requested is True
        assert db.query(ProcessedArchive).count() == 0
    finally:
        db.close()

    assert source.exists()
    assert list(processed_dir.iterdir()) == []
    assert service.is_source_claimed_sync(str(source)) is False


def test_deferred_archive_reclaims_expired_lease_with_new_epoch(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / "RJ01629295.zip"
    source.write_bytes(b"lease payload")

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    queued = service.enqueue_sync(str(source), task_id="archive-lease-task")
    first_claim = service._claim_next_job_sync()

    assert first_claim is not None
    db = session_factory()
    try:
        job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
        job.lease_until = datetime.now() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    recovered_claim = service._claim_next_job_sync()

    assert recovered_claim is not None
    assert recovered_claim["job_id"] == queued["job_id"]
    assert recovered_claim["lease_epoch"] == first_claim["lease_epoch"] + 1


def test_deferred_archive_reserves_suffix_for_conflicting_target_name(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    first_dir = source_dir / "first"
    second_dir = source_dir / "second"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    processed_dir.mkdir()
    first = first_dir / "RJ01629296.zip"
    second = second_dir / "RJ01629296.zip"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    service, session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    first_job = service.enqueue_sync(str(first))
    second_job = service.enqueue_sync(str(second))

    db = session_factory()
    try:
        first_row = db.query(DeferredArchiveJob).filter_by(id=first_job["job_id"]).one()
        second_row = db.query(DeferredArchiveJob).filter_by(id=second_job["job_id"]).one()
        assert first_row.target_manifest[0]["filename"] == "RJ01629296.zip"
        assert second_row.target_manifest[0]["filename"] == "RJ01629296 (1).zip"
    finally:
        db.close()


def test_deferred_archive_second_owner_cannot_claim_active_lease(
    db_session,
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / "RJ01629297.zip"
    source.write_bytes(b"lease owner payload")

    first_service, _session_factory = _configure_service(
        monkeypatch, db_session, source_dir, processed_dir, tmp_path
    )
    first_service.enqueue_sync(str(source))
    second_service = deferred_archive_module.DeferredArchiveService()
    monkeypatch.setattr(second_service, "_has_foreground_work", lambda: False)

    first_claim = first_service._claim_next_job_sync()
    second_claim = second_service._claim_next_job_sync()

    assert first_claim is not None
    assert second_claim is None
    assert first_service._owner != second_service._owner


async def _wait_for_worker_started(service):
    for _ in range(20):
        if service._worker_task is not None and not service._worker_task.done():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("延后归档 worker 未启动")


def test_deferred_archive_start_and_stop_worker_cleanly(
    db_session,
    tmp_path,
    monkeypatch,
):
    async def run():
        source_dir = tmp_path / "input"
        processed_dir = tmp_path / "processed"
        source_dir.mkdir()
        processed_dir.mkdir()
        service, _session_factory = _configure_service(
            monkeypatch, db_session, source_dir, processed_dir, tmp_path
        )

        await service.start()
        await _wait_for_worker_started(service)
        await service.stop()

        assert service._shutdown is True
        assert service._worker_task is None

    asyncio.run(run())


def test_deferred_archive_yields_claim_before_copy_when_foreground_work_arrives(
    db_session,
    tmp_path,
    monkeypatch,
):
    async def run():
        source_dir = tmp_path / "input"
        processed_dir = tmp_path / "processed"
        source_dir.mkdir()
        processed_dir.mkdir()
        source = source_dir / "RJ01629298.zip"
        source.write_bytes(b"foreground preemption payload")
        service, session_factory = _configure_service(
            monkeypatch, db_session, source_dir, processed_dir, tmp_path
        )
        queued = service.enqueue_sync(str(source))
        claim = service._claim_next_job_sync()
        assert claim is not None
        monkeypatch.setattr(service, "_copy_abort_reason", lambda *_args, **_kwargs: "foreground")

        await service._execute_claimed_job(claim)

        db = session_factory()
        try:
            job = db.query(DeferredArchiveJob).filter_by(id=queued["job_id"]).one()
            assert job.status == "pending"
            assert job.lease_owner is None
            assert job.lease_until is None
        finally:
            db.close()
        assert source.exists()
        assert list(processed_dir.iterdir()) == []

    asyncio.run(run())
