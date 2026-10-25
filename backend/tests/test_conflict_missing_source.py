"""来源被外部删除后仍可结束问题作品，权限错误不能吞掉。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import conflict_resolution_service as conflict_module


@pytest.mark.asyncio
@pytest.mark.parametrize('library_id', [None, 'local-library'])
async def test_skip_missing_source_completes(monkeypatch, tmp_path, library_id):
    service = conflict_module.ConflictResolutionService()
    conflict = SimpleNamespace(id='missing-source', new_path=str(tmp_path / 'missing.zip'))
    monkeypatch.setattr(service, 'describe_conflict', lambda _: {'source': {'library_id': library_id}})
    monkeypatch.setattr(service, '_resolve_conflict_new_path', lambda _: None)
    cleanup = AsyncMock()
    monkeypatch.setattr(service, 'cleanup_conflict_sessions', cleanup)
    manager = SimpleNamespace(delete=AsyncMock(side_effect=FileNotFoundError('源文件已被删除')))
    monkeypatch.setattr(conflict_module, 'get_library_manager', lambda: manager)
    result = await service.resolve_skip(conflict)
    assert result['source_missing'] is True
    assert '已不存在' in result['message']
    cleanup.assert_awaited_once_with(conflict.id)


@pytest.mark.asyncio
async def test_skip_preserves_permission_error(monkeypatch, tmp_path):
    service = conflict_module.ConflictResolutionService()
    manager = SimpleNamespace(delete=AsyncMock(side_effect=PermissionError('无权限')))
    monkeypatch.setattr(conflict_module, 'get_library_manager', lambda: manager)
    with pytest.raises(PermissionError):
        await service._delete_source_path(str(tmp_path / 'source.zip'), 'local-library')


@pytest.mark.asyncio
async def test_skip_preserves_local_directory_permission_error(monkeypatch, tmp_path):
    service = conflict_module.ConflictResolutionService()
    monkeypatch.setattr(conflict_module, 'get_library_manager', lambda: Mock())
    delete = Mock(side_effect=PermissionError('无权限'))
    monkeypatch.setattr(conflict_module.shutil, 'rmtree', delete)
    with pytest.raises(PermissionError):
        await service._delete_source_path(str(tmp_path), None)
    delete.assert_called_once_with(str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['PENDING', 'PROCESSING'])
async def test_skip_api_finishes_missing_source_and_records_audit(db_session, monkeypatch, tmp_path, status):
    from app.api import routes
    from app.models import database as database_module
    from app.models.database import ConflictWork
    from app.core import activity_log_service, task_engine

    conflict = ConflictWork(
        id='missing-source-api', rjcode='RJ123456', status=status,
        conflict_type='DUPLICATE', new_path=str(tmp_path / 'missing.zip'),
        existing_path=str(tmp_path / 'existing'), task_id='original-task',
        new_metadata={'available_actions': ['SKIP']},
    )
    db_session.add(conflict)
    db_session.commit()

    def get_db():
        yield db_session

    monkeypatch.setattr(database_module, 'get_db', get_db)
    service = conflict_module.ConflictResolutionService()
    monkeypatch.setattr(conflict_module, 'get_conflict_resolution_service', lambda: service)
    monkeypatch.setattr(service, 'get_available_actions', lambda _: ['SKIP'])
    monkeypatch.setattr(service, 'describe_conflict', lambda _: {'source': {'library_id': 'local-library'}})
    monkeypatch.setattr(service, '_resolve_conflict_new_path', lambda _: None)
    monkeypatch.setattr(service, 'cleanup_conflict_sessions', AsyncMock())
    manager = SimpleNamespace(delete=AsyncMock(side_effect=FileNotFoundError('源文件已不存在')))
    monkeypatch.setattr(conflict_module, 'get_library_manager', lambda: manager)
    engine = Mock()
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: engine)
    audit = Mock()
    resolved_audit = Mock()
    monkeypatch.setattr(activity_log_service, 'log_conflict_resolution_activity', audit)
    monkeypatch.setattr(activity_log_service, 'mark_task_conflict_resolved_activity_log', resolved_audit)

    result = await routes.resolve_conflict(conflict.id, {'action': 'SKIP', 'confirmed': True})

    assert result['success'] is True
    assert result['source_missing'] is True
    assert db_session.query(ConflictWork).filter_by(id='missing-source-api').one().status == 'SKIP'
    engine.update_task_status.assert_called_once_with('original-task', task_engine.TaskStatus.COMPLETED, '跳过完成')
    resolved_audit.assert_called_once_with('original-task', 'SKIP', conflict_id='missing-source-api')
    assert audit.call_args.kwargs['extra_detail']['source_missing'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "failed"])
async def test_skip_archive_failure_preserves_source_and_temporary_directory(monkeypatch, tmp_path, failure):
    from app.core import deferred_archive_service

    archive = tmp_path / "Share.zip"
    archive.write_bytes(b"archive")
    temporary = tmp_path / "extracted"
    temporary.mkdir()
    (temporary / "track.wav").write_bytes(b"audio")
    conflict = SimpleNamespace(
        id="archive-failure", new_path=str(temporary), task_id="original-task",
        new_metadata={"rename_retry_archive_source_path": str(archive)},
    )
    service = conflict_module.ConflictResolutionService()
    monkeypatch.setattr(service, "describe_conflict", lambda _: {"source": {"library_id": None}})
    monkeypatch.setattr(service, "_resolve_conflict_new_path", lambda _: str(temporary))
    enqueue = AsyncMock(
        side_effect=PermissionError("归档目录无权限") if failure == "exception" else None,
        return_value={"status": "failed", "last_error": "归档作业失败"},
    )
    monkeypatch.setattr(
        deferred_archive_service, "get_deferred_archive_service",
        lambda: SimpleNamespace(enqueue_source=enqueue),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(service, "cleanup_conflict_sessions", cleanup)

    with pytest.raises((PermissionError, RuntimeError)):
        await service.resolve_skip(conflict)

    assert archive.read_bytes() == b"archive"
    assert (temporary / "track.wav").read_bytes() == b"audio"
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_skip_api_audits_queued_archive_without_claiming_deletion(db_session, monkeypatch, tmp_path):
    from app.api import routes
    from app.core import activity_log_service, task_engine
    from app.models import database

    archive = tmp_path / "source.zip"
    archive.write_bytes(b"archive")
    conflict = database.ConflictWork(
        id="queued-skip", rjcode="RJ01406188", status="PENDING", conflict_type="DUPLICATE",
        new_path=str(archive), existing_path=str(tmp_path / "existing"), task_id="original-task",
    )
    db_session.add(conflict)
    db_session.commit()

    def get_db():
        yield db_session

    monkeypatch.setattr(database, "get_db", get_db)
    service = SimpleNamespace(
        normalize_action=lambda _: "SKIP",
        get_available_actions=lambda _: ["SKIP"],
        resolve_skip=AsyncMock(return_value={
            "archive_source_path": str(archive), "archive_queue_id": "archive-job",
            "archive_queue_status": "pending", "archive_queued": True,
            "source_missing": False, "deleted_path": None,
        }),
    )
    monkeypatch.setattr(conflict_module, "get_conflict_resolution_service", lambda: service)
    monkeypatch.setattr(task_engine, "get_task_engine", Mock())
    monkeypatch.setattr(activity_log_service, "mark_task_conflict_resolved_activity_log", Mock())
    audit = Mock()
    monkeypatch.setattr(activity_log_service, "log_conflict_resolution_activity", audit)

    result = await routes.resolve_conflict("queued-skip", {"action": "SKIP"})

    assert result["archive_queued"] is True
    assert db_session.get(database.ConflictWork, "queued-skip").status == "SKIP"
    assert archive.read_bytes() == b"archive"
    assert audit.call_args.kwargs["diff_items"] == []
    assert audit.call_args.kwargs["final_path"] == ""
    assert audit.call_args.kwargs["extra_detail"]["archive_queue_id"] == "archive-job"
