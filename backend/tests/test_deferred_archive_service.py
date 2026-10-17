import asyncio
import hashlib
from pathlib import Path
import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.core import deferred_archive_service as deferred_archive_module
from app.models.database import DeferredArchiveJob, ProcessedArchive


@pytest.fixture
def published_member(db_session, db_engine, tmp_path, monkeypatch):
    source_dir = tmp_path / 'input'
    processed_dir = tmp_path / 'processed'
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / 'RJ123456.zip'
    source.write_bytes(b'verified archive content' * 1024)
    service, _ = _configure_service(monkeypatch, db_session, source_dir, processed_dir, tmp_path)
    # 使用真实独立事务，以便 NOWAIT 确认哈希期间另一连接可以取得同一行锁。
    factory = sessionmaker(bind=db_engine, autoflush=False)
    monkeypatch.setattr(deferred_archive_module, 'SessionLocal', factory)
    service.enqueue_sync(str(source))
    claim = service._claim_next_job_sync()
    target = Path(claim['target_manifest'][0]['target_path'])
    target.write_bytes(source.read_bytes())
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    service._record_member_published_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    return service, factory, claim, source, target, checksum


def test_finalize_hashes_without_job_lock_and_deletes_under_fence(published_member, monkeypatch):
    service, factory, claim, source, target, checksum = published_member
    original_hash = service._hash_file
    hashed = []

    def checked_hash(path, should_abort):
        with factory() as db:
            db.query(DeferredArchiveJob).filter_by(id=claim['job_id']).with_for_update(nowait=True).one()
        assert service._heartbeat_sync(claim['job_id'], claim['lease_epoch'])
        hashed.append(path)
        return original_hash(path, should_abort)

    original_remove = deferred_archive_module.os.remove

    def checked_remove(path):
        if str(path) == str(source):
            with factory() as db:
                db.execute(text("SET LOCAL lock_timeout = '50ms'"))
                with pytest.raises(Exception, match='lock timeout|could not obtain lock'):
                    db.query(DeferredArchiveJob).filter_by(id=claim['job_id']).with_for_update(nowait=True).one()
        return original_remove(path)

    monkeypatch.setattr(service, '_hash_file', checked_hash)
    monkeypatch.setattr(deferred_archive_module.os, 'remove', checked_remove)
    service._finalize_published_member_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    assert hashed == [str(target), str(source)]
    assert not source.exists()


@pytest.mark.parametrize('change', ['source', 'target', 'cancel', 'owner', 'epoch', 'manifest'])
def test_finalize_rejects_changes_after_hash(published_member, monkeypatch, change):
    service, factory, claim, source, target, checksum = published_member
    original_hash = service._hash_file

    def changed_hash(path, should_abort):
        result = original_hash(path, should_abort)
        if path == str(source):
            if change in {'source', 'target'}:
                changed = source if change == 'source' else target
                changed.write_bytes(b'x' * changed.stat().st_size)
            else:
                with factory() as db:
                    job = db.query(DeferredArchiveJob).filter_by(id=claim['job_id']).one()
                    if change == 'cancel':
                        job.cancel_requested = True
                    elif change == 'owner':
                        job.lease_owner = 'replacement-owner'
                    elif change == 'epoch':
                        job.lease_epoch += 1
                    else:
                        job.target_manifest = [dict(job.target_manifest[0], state='pending')]
                    db.commit()
        return result

    monkeypatch.setattr(service, '_hash_file', changed_hash)
    with pytest.raises((RuntimeError, deferred_archive_module._ArchiveCancelled)):
        service._finalize_published_member_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    assert source.exists()


def test_finalize_recovery_after_source_delete_before_commit(published_member, monkeypatch):
    service, factory, claim, source, target, checksum = published_member
    original_now = service._database_now

    def crash_after_delete(db):
        assert not source.exists()
        raise RuntimeError('模拟删除后进程中断')

    monkeypatch.setattr(service, '_database_now', crash_after_delete)
    with pytest.raises(RuntimeError, match='模拟删除后'):
        service._finalize_published_member_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=claim['job_id']).one()
        assert job.target_manifest[0]['state'] == 'published'
        job.lease_owner = 'new-owner'
        job.lease_epoch += 1
        epoch = job.lease_epoch
        db.commit()
    service._owner = 'new-owner'
    monkeypatch.setattr(service, '_database_now', original_now)
    service._finalize_published_member_sync(claim['job_id'], epoch, 0, checksum)
    with factory() as db:
        assert db.get(DeferredArchiveJob, claim['job_id']).target_manifest[0]['state'] == 'completed'
    assert hashlib.sha256(target.read_bytes()).hexdigest() == checksum


def test_finalize_requires_durable_published_checksum(published_member):
    service, factory, claim, source, target, checksum = published_member
    with factory() as db:
        job = db.get(DeferredArchiveJob, claim['job_id'])
        job.target_manifest = [dict(job.target_manifest[0], state='pending', sha256='')]
        db.commit()
    with pytest.raises(RuntimeError, match='持久化发布记录'):
        service._finalize_published_member_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    assert source.exists()


def test_published_member_rejects_user_cancel_and_keeps_recovery_record(published_member):
    service, factory, claim, source, target, checksum = published_member
    with pytest.raises(ValueError, match='已有分卷发布'):
        service.request_cancel_sync(claim['job_id'], strict=True)
    with factory() as db:
        job = db.get(DeferredArchiveJob, claim['job_id'])
        assert not job.cancel_requested
        assert job.target_manifest[0]['state'] == 'published'
    assert source.exists()


@pytest.mark.parametrize('change', ['target', 'recreate_source'])
def test_finalize_recovery_rejects_file_changes(published_member, monkeypatch, change):
    service, factory, claim, source, target, checksum = published_member
    source.unlink()
    original_hash = service._hash_file

    def changed_hash(path, should_abort):
        result = original_hash(path, should_abort)
        if change == 'target':
            target.write_bytes(b'x' * target.stat().st_size)
        else:
            source.write_bytes(b'new source')
        return result

    monkeypatch.setattr(service, '_hash_file', changed_hash)
    with pytest.raises(RuntimeError):
        service._finalize_published_member_sync(claim['job_id'], claim['lease_epoch'], 0, checksum)
    with factory() as db:
        assert db.get(DeferredArchiveJob, claim['job_id']).target_manifest[0]['state'] == 'published'
    if change == 'recreate_source':
        assert source.read_bytes() == b'new source'


@pytest.mark.parametrize('age,delay,eligible', [(899, 0, False), (901, 0, True), (901, 60, False)])
def test_starvation_claim_preserves_retry_deadline(db_session, tmp_path, monkeypatch, age, delay, eligible):
    source_dir = tmp_path / 'input'
    processed_dir = tmp_path / 'processed'
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / 'RJ123456.zip'
    source.write_bytes(b'archive')
    service, session_factory = _configure_service(monkeypatch, db_session, source_dir, processed_dir, tmp_path)
    queued = service.enqueue_sync(str(source))
    with session_factory() as db:
        now = service._database_now(db)
        job = db.query(DeferredArchiveJob).filter_by(id=queued['job_id']).one()
        job.created_at = now - timedelta(seconds=age)
        job.available_at = now + timedelta(seconds=delay)
        job.status = 'waiting_retry'
        db.commit()
    monkeypatch.setattr(service, '_has_foreground_work', lambda: True)
    claim = service._claim_next_job_sync(starved_only=True)
    assert (claim is not None) is eligible
    if claim:
        assert claim['starvation_protected'] is True


def test_starved_archive_finishes_with_foreground_work(db_session, tmp_path, monkeypatch):
    source_dir = tmp_path / 'input'
    processed_dir = tmp_path / 'processed'
    source_dir.mkdir()
    processed_dir.mkdir()
    source = source_dir / 'RJ123456.zip'
    payload = b'archive-content' * 1024
    source.write_bytes(payload)
    service, session_factory = _configure_service(monkeypatch, db_session, source_dir, processed_dir, tmp_path)
    queued = service.enqueue_sync(str(source))
    with session_factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=queued['job_id']).one()
        job.created_at = service._database_now(db) - timedelta(seconds=901)
        db.commit()
    claim = service._claim_next_job_sync(starved_only=True)
    assert claim is not None
    monkeypatch.setattr(service, '_has_foreground_work', lambda: True)
    asyncio.run(service._execute_claimed_job(claim))
    with session_factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=queued['job_id']).one()
        assert job.status == 'completed'
        assert job.lease_owner is None
    assert not source.exists()
    assert (processed_dir / source.name).read_bytes() == payload


@pytest.mark.parametrize('reason', ['cancelled', 'lease_lost', 'shutdown'])
def test_starvation_protection_keeps_control_interrupts(monkeypatch, reason):
    service = deferred_archive_module.DeferredArchiveService()
    service._set_active_job('protected')
    service._active_starvation_protected = True
    monkeypatch.setattr(service, '_has_foreground_work', lambda: True)
    assert service._copy_abort_reason('protected', 1) == ''
    service._request_active_abort('protected', reason)
    assert service._copy_abort_reason('protected', 1) == reason


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
    # 本模块验证归档事务与文件协议；事件传输不连接真实 Redis。
    monkeypatch.setattr(service, "_broadcast", lambda *_args, **_kwargs: None)
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
