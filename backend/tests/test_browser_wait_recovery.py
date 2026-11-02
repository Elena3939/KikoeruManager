from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.task_engine import TaskEngine, TaskType, TaskStatus
from app.models import database


@pytest.mark.parametrize('kind', [TaskType.RJ_SUBTITLE_FETCH, TaskType.HTTP_DOWNLOAD])
def test_restart_restores_waiting_task_without_reusing_browser_session(monkeypatch, kind):
    row = SimpleNamespace(id='waiting', type=kind.value, status='processing',
        source_path='YAAS', output_path=None, progress=0, current_step='下载',
        error_message=None, created_at=datetime.now(), started_at=None, completed_at=None,
        task_metadata={'browser_verification_required': True, 'browser_verification_session_id': 'old-session'})
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = [row]
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    engine = TaskEngine.__new__(TaskEngine)
    engine.tasks = {}
    engine._ensure_task_context = Mock()
    engine.persist_task_center_item_snapshot = Mock()
    assert engine.load_persisted_linked_subtitle_tasks() == 1
    task = engine.tasks['waiting']
    assert task.status == TaskStatus.WAITING_MANUAL
    assert 'browser_verification_session_id' not in task.task_metadata
    assert task.task_metadata['browser_verification_required']
    assert '重新验证' in task.current_step
    db.commit.assert_called_once()
