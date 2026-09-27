"""归档队列分页、人工控制和发布边界回归。"""
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import deferred_archive_service as archive_module
from app.models.database import DeferredArchiveJob
from tests.test_deferred_archive_service import _configure_service


@pytest.fixture
def archive_api(monkeypatch, db_session, tmp_path):
    source_dir = tmp_path / 'input'
    target_dir = tmp_path / 'processed'
    source_dir.mkdir()
    target_dir.mkdir()
    service, factory = _configure_service(monkeypatch, db_session, source_dir, target_dir, tmp_path)
    # API 拒绝操作会回滚自己的事务，必须隔离于 fixture 的外层事务。
    factory.configure(join_transaction_mode='create_savepoint')
    monkeypatch.setattr(archive_module, 'get_deferred_archive_service', lambda: service)
    monkeypatch.setattr(service, '_update_parent_task', AsyncMock())
    monkeypatch.setattr(service, '_broadcast', Mock())
    jobs = []
    for index in range(3):
        path = source_dir / f'RJ12345{index}.zip'
        path.write_bytes(b'archive')
        jobs.append(service.enqueue_sync(str(path))['job_id'])
    return service, factory, jobs


def test_queue_pagination_filter_and_summary(client, archive_api):
    _, factory, jobs = archive_api
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=jobs[0]).one()
        job.status = 'waiting_retry'
        job.last_error = '磁盘空间不足'
        job.attempt_count = 2
        job.available_at += timedelta(hours=1)
        db.commit()
    response = client.get('/api/deferred-archive-jobs', params={'status': 'pending', 'page_size': 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == payload['pending_count'] == 2
    assert payload['counts_by_status']['waiting_retry'] == 1
    assert len(payload['items']) == 1
    second = client.get('/api/deferred-archive-jobs', params={'status': 'pending', 'page_size': 1, 'page': 2}).json()
    assert second['items'][0]['job_id'] != payload['items'][0]['job_id']
    retry = client.get('/api/deferred-archive-jobs', params={'status': 'waiting_retry'}).json()['items'][0]
    assert retry['wait_reason'] == '等待重试时间'
    assert retry['last_error'] == '磁盘空间不足'
    assert retry['attempt_count'] == 2
    assert retry['source_summary']['total_bytes'] == 7
    assert retry['can_retry'] is True
    assert 'source_manifest' not in retry


@pytest.mark.parametrize('params', [{'status': 'unknown'}, {'page': 0}, {'page_size': 101}])
def test_queue_rejects_invalid_parameters(client, archive_api, params):
    assert client.get('/api/deferred-archive-jobs', params=params).status_code == 422


def test_cancel_releases_pending_claim_and_broadcasts(client, archive_api):
    service, factory, jobs = archive_api
    response = client.post(f'/api/deferred-archive-jobs/{jobs[0]}/cancel')
    assert response.status_code == 200
    assert response.json()['status'] == 'cancelled'
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=jobs[0]).one()
        assert job.status == 'cancelled'
        assert not service.is_source_claimed_sync(job.source_manifest[0]['source_path'])
    service._broadcast.assert_called_once()
    service._update_parent_task.assert_awaited_once()
    assert client.post(f'/api/deferred-archive-jobs/{jobs[0]}/cancel').status_code == 409


def test_processing_cancel_retains_claim_until_worker_stops(client, archive_api):
    service, factory, jobs = archive_api
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=jobs[0]).one()
        job.status = 'processing'
        source = job.source_manifest[0]['source_path']
        db.commit()
    response = client.post(f'/api/deferred-archive-jobs/{jobs[0]}/cancel')
    assert response.status_code == 200
    assert response.json()['status'] == 'processing'
    assert service.is_source_claimed_sync(source)
    items = client.get('/api/deferred-archive-jobs').json()['items']
    item = next(item for item in items if item['job_id'] == jobs[0])
    assert item['cancel_requested'] is True
    assert item['can_cancel'] is False
    assert item['wait_reason'] == '取消已请求，等待安全停止'
    assert client.post(f'/api/deferred-archive-jobs/{jobs[0]}/cancel').status_code == 409
    assert client.post(f'/api/deferred-archive-jobs/{jobs[0]}/retry').status_code == 409
    service._broadcast.assert_called_once()


def test_published_member_prevents_cancel(client, archive_api):
    _, factory, jobs = archive_api
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=jobs[0]).one()
        job.status = 'processing'
        job.target_manifest = [{**item, 'state': 'published'} for item in job.target_manifest]
        db.commit()
    assert client.post(f'/api/deferred-archive-jobs/{jobs[0]}/cancel').status_code == 409
    items = client.get('/api/deferred-archive-jobs').json()['items']
    assert next(item for item in items if item['job_id'] == jobs[0])['can_cancel'] is False


@pytest.mark.parametrize('status', ['failed', 'waiting_retry'])
def test_retry_accepts_only_retryable_state(client, archive_api, status):
    service, factory, jobs = archive_api
    with factory() as db:
        job = db.query(DeferredArchiveJob).filter_by(id=jobs[0]).one()
        job.status = status
        job.last_error = '读取失败'
        job.attempt_count = 3
        db.commit()
    response = client.post(f'/api/deferred-archive-jobs/{jobs[0]}/retry')
    assert response.status_code == 200
    assert response.json()['status'] == 'pending'
    assert client.post(f'/api/deferred-archive-jobs/{jobs[0]}/retry').status_code == 409
    service._broadcast.assert_called_once()


@pytest.mark.parametrize('action', ['cancel', 'retry'])
def test_missing_job_returns_404(client, archive_api, action):
    assert client.post(f'/api/deferred-archive-jobs/missing/{action}').status_code == 404
