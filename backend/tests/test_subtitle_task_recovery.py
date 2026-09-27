"""字幕补配恢复不得留下没有执行器的前台任务。"""
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.models import database as database_module
from app.models.database import Task as TaskRecord


@pytest.mark.parametrize('status', ['pending', 'processing'])
def test_interrupted_manual_subtitle_recovers_as_waiting(db_session, monkeypatch, status):
    factory = sessionmaker(bind=db_session.connection())
    monkeypatch.setattr(database_module, 'SessionLocal', factory)
    with factory() as db:
        db.add(TaskRecord(
            id='manual-subtitle-recovery', type=TaskType.RJ_SUBTITLE_FETCH.value,
            status=status, source_path='/test/subtitle',
            task_metadata={'source_mode': 'subtitle_folder_import', 'awaiting_manual_match': True},
        ))
        db.commit()
    engine = TaskEngine()
    persist_item = Mock()
    monkeypatch.setattr(engine, 'persist_task_center_item_snapshot', persist_item)
    try:
        assert engine.load_persisted_linked_subtitle_tasks() == 1
        restored = engine.tasks['manual-subtitle-recovery']
        assert restored.status == TaskStatus.WAITING_MANUAL
        assert restored.task_metadata['awaiting_manual_match'] is True
        persist_item.assert_called_once_with(restored)
        with factory() as db:
            row = db.query(TaskRecord).filter_by(id=restored.id).one()
            assert row.status == 'waiting_manual'
            assert row.task_metadata['manual_match_recovered_at']
    finally:
        engine._materialized_snapshot_executor.shutdown(wait=True)


def test_existing_subtitle_task_is_not_replaced(db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.connection())
    monkeypatch.setattr(database_module, 'SessionLocal', factory)
    metadata = {'source_mode': 'subtitle_folder_import', 'awaiting_manual_match': True}
    with factory() as db:
        db.add(TaskRecord(id='active-subtitle', type=TaskType.RJ_SUBTITLE_FETCH.value,
                          status='processing', source_path='/test/subtitle', task_metadata=metadata))
        db.commit()
    engine = TaskEngine()
    active = Task(task_type=TaskType.RJ_SUBTITLE_FETCH, source_path='/test/subtitle',
                  task_id='active-subtitle', status=TaskStatus.PROCESSING, metadata=metadata)
    engine.tasks[active.id] = active
    try:
        assert engine.load_persisted_linked_subtitle_tasks() == 0
        assert engine.tasks[active.id] is active
        assert active.status == TaskStatus.PROCESSING
    finally:
        engine._materialized_snapshot_executor.shutdown(wait=True)
