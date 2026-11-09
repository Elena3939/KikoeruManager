"""百度两阶段等待、缓存隔离及共享命令执行器回归。"""
import asyncio
import os
import subprocess
import sys
import time
import threading

import pytest
import requests

from app.core.baidu_netdisk_service import BaiduNetdiskError, BaiduNetdiskService, _ShareHttpPool, _share_login_cookie
from app.core.task_engine import Task, TaskStatus, TaskType
from tests.test_baidu_netdisk_service import DummyConfig
from tests.test_baidu_share_enumeration import row


@pytest.fixture
def service(monkeypatch, tmp_path):
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path)
    config.baidu_netdisk.download_root = str(tmp_path / 'downloads')
    monkeypatch.setattr('app.core.baidu_netdisk_service.get_config', lambda: config)
    return BaiduNetdiskService()


def task():
    return Task(task_type=TaskType.BAIDU_NETDISK_DOWNLOAD, source_path='test',
                metadata={}, status=TaskStatus.PROCESSING)


@pytest.mark.asyncio
async def test_preview_cache_output_options_force_and_login_isolation(service, monkeypatch):
    calls = []
    async def fetch(share, **kwargs):
        calls.append(dict(share))
        return {'files': [{'name': 'a.rar', 'relative_path': 'a.rar', 'path': '/a.rar',
                           'size': 10, 'size_bytes': 10, 'fs_id': '1'}],
                'file_count': 1, 'total_size': 10, 'title': 'a.rar'}
    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    urls = ['https://pan.baidu.com/s/1abcdefg?pwd=1234']
    first = await service.preview_urls(urls)
    original = first['items'][0]['selection_key']
    first['items'][0]['share_files'][0]['name'] = 'mutated'
    hit = await service.preview_urls(urls)
    assert hit['items'][0]['share_files'][0]['name'] == 'a.rar'
    assert hit['items'][0]['selection_key'] == original
    changed = await service.preview_urls(urls, target_subdir='other', output_folder_name='custom')
    assert changed['target_subdir'] == 'other'
    assert len(calls) == 1
    service._config().cookie += '; BDCLND=another-share'
    await service.preview_urls(urls)
    assert len(calls) == 1
    await service.preview_urls(urls, force_refresh=True)
    assert len(calls) == 2
    service._config().account_uk = 'another-account'
    await service.preview_urls(urls)
    service._config().cookie = 'BDUSS=another-login'
    await service.preview_urls(urls)
    await service.preview_urls(['https://pan.baidu.com/s/1abcdefg?pwd=5678'])
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_singleflight_survives_one_waiter_cancellation(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    async def fetch(*args, **kwargs):
        nonlocal count
        count += 1
        entered.set()
        await release.wait()
        return {'files': [{'name': 'a.rar'}]}
    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    share = {'share_id': '1abcdefg'}
    first = asyncio.create_task(service._resolve_share_detail(share))
    await entered.wait()
    second = asyncio.create_task(service._resolve_share_detail(share, force_refresh=True))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second)['files'][0]['name'] == 'a.rar'
    assert count == 1
    assert not service._share_detail_inflight


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['warning', 'incomplete', 'exception'])
async def test_failed_or_incomplete_results_are_not_cached(service, monkeypatch, failure):
    calls = 0
    async def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failure == 'exception':
            raise BaiduNetdiskError('invalid share')
        return {'files': [{'name': 'a.rar'}], 'warning': 'failed' if failure == 'warning' else '',
                'enumeration_complete': failure != 'incomplete'}
    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    for _ in range(2):
        try:
            await service._resolve_share_detail({'share_id': '1abcdefg'})
        except BaiduNetdiskError:
            pass
    assert calls == 2
    assert not service._share_detail_inflight
    assert not service._share_detail_cache


@pytest.mark.asyncio
async def test_directory_workers_refill_without_waiting_for_slow_sibling(service, monkeypatch):
    slow_release, fifth_started = asyncio.Event(), asyncio.Event()
    async def fetch(*args, dir_path='/', **kwargs):
        if dir_path == '/0':
            await slow_release.wait()
        if dir_path == '/4':
            fifth_started.set()
        return {'errno': 0, 'list': [row(f'{dir_path}/a.rar', dir_path)]}
    monkeypatch.setattr(service, '_fetch_share_list_payload', fetch)
    entries = service._normalize_share_file_list([row(f'/{i}', i, True) for i in range(8)])
    running = asyncio.create_task(service._expand_share_file_list({}, '', '', '', entries))
    try:
        await asyncio.wait_for(fifth_started.wait(), 1)
        assert not running.done()
    finally:
        slow_release.set()
    result = await running
    assert [entry['relative_path'] for entry in result['files']] == [f'{i}/a.rar' for i in range(8)]


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [requests.Timeout, requests.ConnectionError])
async def test_network_failure_does_not_walk_referers(service, monkeypatch, error):
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(kwargs)
        raise error('network')
    monkeypatch.setattr(service, '_fetch_json', fetch)
    with pytest.raises(error):
        await service._fetch_share_list_payload({}, '', '', '1abcdefg')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_eight_quick_commands_and_tail_output(service, tmp_path):
    lines = []
    started = time.monotonic()
    for index in range(8):
        await service._run_baidu_pcs_go_command(
            [sys.executable, '-c', f"print('tail-{index}', end='')"], env=os.environ.copy(),
            log_path=str(tmp_path / 'commands.log'), task=task(), cancel_event=asyncio.Event(),
            on_output=lines.append)
    elapsed = time.monotonic() - started
    assert lines == [f'tail-{index}' for index in range(8)]
    assert elapsed < 3, elapsed
    assert (tmp_path / 'commands.log').read_text() == ''.join(lines)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['cancel', 'pause', 'timeout', 'callback'])
async def test_command_interruption_reaps_child(service, monkeypatch, tmp_path, mode):
    processes = []
    original = subprocess.Popen
    def spawn(*args, **kwargs):
        proc = original(*args, **kwargs)
        processes.append(proc)
        return proc
    monkeypatch.setattr('app.core.baidu_netdisk_service.subprocess.Popen', spawn)
    current = task()
    event = asyncio.Event()
    def started():
        if mode == 'cancel':
            event.set()
        elif mode == 'pause':
            current._pause_event.clear()
        elif mode == 'callback':
            raise RuntimeError('callback')
    with pytest.raises((asyncio.CancelledError, BaiduNetdiskError, RuntimeError)):
        await service._run_baidu_pcs_go_command(
            [sys.executable, '-c', 'import time; time.sleep(20)'], env=os.environ.copy(),
            log_path=str(tmp_path / 'cancel.log'), task=current, cancel_event=event,
            max_runtime_seconds=0.05 if mode == 'timeout' else 0, on_started=started)
    assert processes[0].poll() is not None


@pytest.mark.asyncio
async def test_transfer_backoff_releases_slot(service, monkeypatch):
    attempts = 0
    async def transfer(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.ConnectionError('broken response')
        return {'errno': 0}
    async def backoff(*args):
        assert service._transfer_slot_active == 0
    monkeypatch.setattr(service, '_transfer_share_item_by_web', transfer)
    monkeypatch.setattr(service, '_wait_baidu_transfer_retry', backoff)
    current = task()
    result = await service._transfer_share_item_with_retry(
        current, {}, '', '/temporary', share_url='', pass_code='', download_files=[],
        started=time.monotonic(), cancel_event=asyncio.Event())
    assert result['errno'] == 0
    assert attempts == 2
    assert service._transfer_slot_active == 0


def test_first_byte_requires_growth_beyond_resume_checkpoint(service):
    current = task()
    row_data = {'name': 'a.rar', 'downloaded': 100, 'total': 1000, 'status': 'downloading'}
    service._startup_phase(row_data, 'waiting_network_budget')
    service._download_process_started(current, row_data, [row_data], time.monotonic())
    state = {}
    service._update_pcsgo_transfer_progress(current, row_data, [row_data], time.monotonic(), '100 B / 1000 B', state)
    assert row_data['startup_phase'] == 'starting_download'
    service._update_pcsgo_transfer_progress(current, row_data, [row_data], time.monotonic(), '101 B / 1000 B', state)
    assert row_data['startup_phase'] == 'transmitting'
    assert row_data['startup_timing_ms']['process_to_first_byte'] >= 0


@pytest.mark.asyncio
async def test_preview_removes_unrelated_share_cookie_and_expires_cache(service, monkeypatch):
    cookies = []
    async def fetch(*args, **kwargs):
        cookies.append(_share_login_cookie.get())
        return {'files': [{'name': 'a.rar'}]}
    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    service._config().cookie = 'BDUSS=login; BDCLND=other-share'
    share = {'share_id': '1abcdefg'}
    await service._resolve_share_detail(share)
    service._share_detail_cache[service._share_detail_key(share)]['cached_at'] -= 601
    await service._resolve_share_detail(share)
    assert cookies == ['BDUSS=login', 'BDUSS=login']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [429, 500, 503])
async def test_share_page_does_not_retry_rate_limit_or_server_error(service, monkeypatch, status):
    calls = []
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            calls.append(args)
            response = requests.Response()
            response.status_code = status
            response.raise_for_status()
    monkeypatch.setattr('app.core.baidu_netdisk_service.requests.Session', Session)
    with pytest.raises(requests.HTTPError):
        await service._fetch_share_page_tokens('1abcdefg', 'BDUSS=login')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancelled_pool_request_keeps_session_until_thread_returns():
    pool = _ShareHttpPool()
    entered, release = threading.Event(), threading.Event()
    sessions = []
    def request():
        with pool.session() as session:
            sessions.append(session)
            session.cookies.set('BDCLND', 'share-only')
            entered.set()
            release.wait(5)
            assert session.cookies.get('BDCLND') == 'share-only'
    pending = asyncio.create_task(asyncio.to_thread(request))
    await asyncio.to_thread(entered.wait, 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    with pool.session() as other:
        assert other is not sessions[0]
        assert not other.cookies
    pool.close()
    release.set()
    await asyncio.to_thread(lambda: None)


def test_pool_reuses_exclusive_sessions_without_cookie_leak():
    pool = _ShareHttpPool()
    with pool.session() as first:
        first.cookies.set('BDCLND', 'one-share')
    with pool.session() as second:
        assert first is second
        assert not second.cookies
    pool.close()
