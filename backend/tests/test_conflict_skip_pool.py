"""小连接池下批量跳过不能持有连接等待文件删除或独立事务。"""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize("pool_size", [1, 4])
async def test_parallel_skip_releases_connections(db_engine, monkeypatch, tmp_path, pool_size):
    from app.api import routes
    from app.core import activity_log_service, conflict_resolution_service, task_engine
    from app.models import database

    engine = create_engine(db_engine.url, pool_size=pool_size, max_overflow=0, pool_timeout=0.3)
    sessions = sessionmaker(bind=engine)
    ids = [str(uuid4()) for _ in range(4)]
    with sessions() as db:
        for conflict_id in ids:
            db.add(database.ConflictWork(
                id=conflict_id, rjcode="RJ123456", status="PENDING",
                conflict_type="DUPLICATE", new_path=str(tmp_path / f"{conflict_id}.zip"),
                existing_path=str(tmp_path / "existing"), task_id=conflict_id,
            ))
            db.add(database.ProcessedArchive(
                id=conflict_id, filename=f"{conflict_id}.zip", status="conflict",
            ))
        db.commit()

    def get_db():
        yield sessions()

    monkeypatch.setattr(database, "get_db", get_db)
    main_thread = threading.get_ident()
    arrived = 0
    all_deleting = asyncio.Event()

    async def delete_source(conflict):
        nonlocal arrived
        arrived += 1
        if arrived == 4:
            all_deleting.set()
        await asyncio.wait_for(all_deleting.wait(), timeout=3)
        assert engine.pool.checkedout() == 0
        # 等待四路都检查完成，再允许后续短事务开始。
        await asyncio.sleep(0.01)
        return {"source_missing": True, "message": "已跳过"}

    service = SimpleNamespace(
        normalize_action=lambda action: "SKIP",
        get_available_actions=lambda conflict: ["SKIP"],
        resolve_skip=delete_source,
    )
    monkeypatch.setattr(conflict_resolution_service, "get_conflict_resolution_service", lambda: service)

    def independent_write(*args, **kwargs):
        assert threading.get_ident() != main_thread
        with sessions() as db:
            db.execute(text("SELECT 1"))

    update = Mock(side_effect=independent_write)
    audit = Mock(side_effect=independent_write)
    resolved = Mock(side_effect=independent_write)
    def broadcast_archive(archive):
        independent_write()
        assert archive.id in ids
        assert archive.status == "completed"
        assert archive.processed_at is not None

    broadcast = Mock(side_effect=broadcast_archive)
    monkeypatch.setattr(routes, "_broadcast_processed_archive_changed_safe", broadcast)
    monkeypatch.setattr(task_engine, "get_task_engine", lambda: SimpleNamespace(update_task_status=update))
    monkeypatch.setattr(activity_log_service, "mark_task_conflict_resolved_activity_log", resolved)
    monkeypatch.setattr(activity_log_service, "log_conflict_resolution_activity", audit)
    try:
        results = await asyncio.wait_for(asyncio.gather(*(
            routes.resolve_conflict(conflict_id, {"action": "SKIP"})
            for conflict_id in ids
        )), timeout=5)
        assert all(result["success"] for result in results)
        assert update.call_count == resolved.call_count == audit.call_count == 4
        assert broadcast.call_count == 4
        with sessions() as db:
            assert all(
                row.status == "SKIP"
                for row in db.query(database.ConflictWork).filter(database.ConflictWork.id.in_(ids))
            )
            assert all(
                row.status == "completed"
                for row in db.query(database.ProcessedArchive).filter(database.ProcessedArchive.id.in_(ids))
            )
        assert engine.pool.checkedout() == 0
    finally:
        with sessions() as db:
            db.query(database.ConflictWork).filter(database.ConflictWork.id.in_(ids)).delete()
            db.query(database.ProcessedArchive).filter(database.ProcessedArchive.id.in_(ids)).delete()
            db.commit()
        engine.dispose()


@pytest.mark.asyncio
async def test_failed_skip_does_not_finish_conflict(db_session, monkeypatch, tmp_path):
    from app.api import routes
    from app.core import conflict_resolution_service, task_engine
    from app.models import database

    conflict = database.ConflictWork(
        id=str(uuid4()), rjcode="RJ123456", status="PENDING", conflict_type="DUPLICATE",
        new_path=str(tmp_path / "source.zip"), existing_path=str(tmp_path / "existing"),
    )
    conflict_id = conflict.id
    db_session.add(conflict)
    db_session.commit()

    def get_db():
        yield db_session

    async def delete_source(conflict):
        raise PermissionError("无权限")

    service = SimpleNamespace(
        normalize_action=lambda action: "SKIP",
        get_available_actions=lambda conflict: ["SKIP"],
        resolve_skip=delete_source,
    )
    monkeypatch.setattr(database, "get_db", get_db)
    monkeypatch.setattr(conflict_resolution_service, "get_conflict_resolution_service", lambda: service)
    engine = Mock()
    monkeypatch.setattr(task_engine, "get_task_engine", lambda: engine)
    with pytest.raises(HTTPException) as exc:
        await routes.resolve_conflict(conflict_id, {"action": "SKIP"})
    assert exc.value.status_code == 500
    assert db_session.get(database.ConflictWork, conflict_id).status == "PENDING"
    engine.update_task_status.assert_not_called()
