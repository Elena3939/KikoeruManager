from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import sys
import pytest
from fastapi import HTTPException
from app.api import browser_verification_routes as routes
from app.core import http_download_service as http
from app.core import resource_source_service as source
from app.core import task_engine as engine_module
from app.core.task_engine import Task, TaskType, TaskStatus, TaskEngine


def waiting_task(kind=TaskType.RJ_SUBTITLE_FETCH):
    task = Task(kind, 'YAAS', metadata={
        'browser_verification_required': True,
        'browser_verification_url': 'https://cdn.imoutoheaven.org/file',
    })
    task.status = TaskStatus.WAITING_MANUAL
    return task


@pytest.mark.asyncio
async def test_open_returns_url_without_browser_runtime(monkeypatch):
    task = waiting_task()
    monkeypatch.setattr(engine_module, 'get_task_engine', lambda: SimpleNamespace(get_task=lambda _: task))
    validate = AsyncMock()
    monkeypatch.setattr(routes, 'validate_verification_url', validate)
    result = await routes.open_task(task.id)
    assert result == {'presentation': 'current_browser', 'verification_url': 'https://cdn.imoutoheaven.org/file'}
    validate.assert_awaited_once_with(result['verification_url'])
    assert 'app.core.browser_verification_service' not in sys.modules


@pytest.mark.asyncio
async def test_open_refreshes_url_and_preserves_task_on_failure(monkeypatch):
    task = waiting_task()
    task.task_metadata['yaas_path'] = '/subtitles/RJ123456.zip'
    monkeypatch.setattr(engine_module, 'get_task_engine', lambda: SimpleNamespace(get_task=lambda _: task))
    request = AsyncMock(return_value={'raw_url': 'https://cdn.imoutoheaven.org/fresh'})
    monkeypatch.setattr(source, 'get_resource_source_service', lambda: SimpleNamespace(request=request))
    validate = AsyncMock()
    monkeypatch.setattr(routes, 'validate_verification_url', validate)
    assert (await routes.open_task(task.id))['verification_url'].endswith('/fresh')
    request.assert_awaited_once_with('get', {'path': '/subtitles/RJ123456.zip', 'password': ''})
    validate.side_effect = ValueError('非法地址')
    with pytest.raises(HTTPException) as error:
        await routes.open_task(task.id)
    assert error.value.status_code == 409
    assert task.status == TaskStatus.WAITING_MANUAL


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['http://cdn.imoutoheaven.org/a', 'https://evil.example/a', 'https://user:password@cdn.imoutoheaven.org/a'])
async def test_rejects_invalid_download_addresses(url):
    with pytest.raises(ValueError):
        await routes.validate_verification_url(url)


@pytest.mark.asyncio
async def test_valid_address_keeps_public_network_validation(monkeypatch):
    validate = AsyncMock()
    monkeypatch.setattr(http, 'get_http_download_service', lambda: SimpleNamespace(validate_url=validate))
    await routes.validate_verification_url('https://cdn.imoutoheaven.org/file')
    validate.assert_awaited_once_with('https://cdn.imoutoheaven.org/file', allow_private_network=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [TaskType.HTTP_DOWNLOAD, TaskType.RJ_SUBTITLE_FETCH])
async def test_handoff_removes_only_waiting_task(monkeypatch, kind):
    task = waiting_task(kind)
    remove = Mock(return_value=True)
    engine = SimpleNamespace(get_task=lambda _: task, processing=set(), remove_task=remove)
    monkeypatch.setattr(engine_module, 'get_task_engine', lambda: engine)
    assert (await routes.handoff_task(task.id))['success']
    remove.assert_called_once_with(task.id)
    assert task.progress != 100


@pytest.mark.asyncio
@pytest.mark.parametrize('status,required,busy', [(TaskStatus.PROCESSING, True, False), (TaskStatus.WAITING_MANUAL, False, False), (TaskStatus.WAITING_MANUAL, True, True)])
async def test_handoff_refuses_running_or_changed_task(monkeypatch, status, required, busy):
    task = waiting_task()
    task.status = status
    task.task_metadata['browser_verification_required'] = required
    remove = Mock()
    engine = SimpleNamespace(get_task=lambda _: task, processing={task.id} if busy else set(), remove_task=remove)
    monkeypatch.setattr(engine_module, 'get_task_engine', lambda: engine)
    with pytest.raises(HTTPException) as error:
        await routes.handoff_task(task.id)
    assert error.value.status_code == 409
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_deletes_snapshot_and_is_idempotent(monkeypatch):
    from app.core import filter_recovery_service
    engine = TaskEngine(max_concurrent=1)
    task, other = waiting_task(), waiting_task()
    engine.tasks.update({task.id: task, other.id: other})
    delete, cleanup = Mock(), Mock()
    monkeypatch.setattr(engine, 'delete_task_snapshot', delete)
    monkeypatch.setattr(filter_recovery_service, 'get_filter_recovery_service', lambda: SimpleNamespace(cleanup_task=cleanup))
    monkeypatch.setattr(engine_module, 'get_task_engine', lambda: engine)
    await routes.handoff_task(task.id)
    assert engine.get_task(task.id) is None
    assert engine.get_task(other.id) is other
    delete.assert_called_once_with(task.id)
    cleanup.assert_called_once_with(task.id, strict=True)
    assert (await routes.handoff_task(task.id))['success']


@pytest.mark.asyncio
async def test_http_waits_for_client_browser_without_retries(monkeypatch):
    start = AsyncMock(side_effect=source.ResourceSourceError('POW', verification_url='https://cdn.imoutoheaven.org/file'))
    monkeypatch.setattr(http, 'get_http_download_service', lambda: SimpleNamespace(start_download_task=start))
    task = Task(TaskType.HTTP_DOWNLOAD, 'YAAS', metadata={'resource_source': 'imoutoheaven'})
    task.status = TaskStatus.PROCESSING
    task.mark_changed = lambda *args: None
    await TaskEngine._process_http_download(SimpleNamespace(persist_task_snapshot=lambda _: None), task)
    assert task.status == TaskStatus.WAITING_MANUAL
    assert task.task_metadata['browser_verification_required']
    assert 'browser_verification_session_id' not in task.task_metadata
    start.assert_awaited_once()


def test_routes_only_expose_current_browser_handoff():
    assert {route.path for route in routes.router.routes} == {
        '/api/browser-verification/task/{task_id}/open',
        '/api/browser-verification/task/{task_id}/handoff',
    }


@pytest.mark.parametrize('status,expected', [(TaskStatus.WAITING_MANUAL, True), (TaskStatus.PROCESSING, False), (TaskStatus.COMPLETED, False)])
def test_task_payload_has_flag_without_signed_url(status, expected):
    from app.core.rj_subtitle_task_service import task_payload
    task = waiting_task()
    task.status = status
    payload = task_payload(task)
    assert payload['browser_verification_required'] is expected
    assert 'https://' not in repr(payload)
