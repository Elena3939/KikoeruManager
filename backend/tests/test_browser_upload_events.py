"""浏览器上传事件只推送有界展示增量，不访问数据库或网络。"""
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.browser_upload_service import BrowserUploadService
from app.core import task_engine, realtime_event_service


def test_browser_upload_event_is_bounded_and_excludes_private_fields(monkeypatch):
    service = object.__new__(BrowserUploadService)
    service.refresh_metrics = Mock()
    files = {str(i): dict(id=str(i), status='receiving', size=10, received=3,
                          final_path='/private', sha256='secret') for i in range(201)}
    state = dict(id='session', status='receiving', source_label='source', target_path='target',
                 created_at='2026-11-07T10:00:00', enumerated=True, library_id='library',
                 files=files, _publish_pending=set(files))
    service.summary = Mock(return_value=dict(id='session', status='receiving', enumerated=True,
        total_files=201, total_bytes=2010, received_bytes=603, written_bytes=0, index_pending=True,
        counts={'completed': 0, 'conflict': 0}, token='secret', target_path='/private'))
    engine = SimpleNamespace(tasks={}, _ensure_task_context=Mock())
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: engine)
    broadcast = Mock()
    monkeypatch.setattr(realtime_event_service, 'broadcast_event', broadcast)
    service.publish(state)
    payload = broadcast.call_args.args[0]['payload']
    assert len(payload['files']) == 200
    assert payload['from_cursor'] == 0 and payload['cursor'] == 200
    assert payload['has_more'] is True
    assert 'token' not in payload and 'target_path' not in payload
    assert all('sha256' not in file and 'final_path' not in file for file in payload['files'])
    service.publish(state)
    assert broadcast.call_count == 1
    state['status'] = 'completed'
    service.summary.return_value.update(status='completed', index_pending=False)
    service.publish(state)
    assert broadcast.call_count == 2
    assert broadcast.call_args.args[0]['payload']['status'] == 'completed'
