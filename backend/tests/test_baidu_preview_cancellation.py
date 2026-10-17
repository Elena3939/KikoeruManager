import asyncio

import pytest

from app.core import baidu_netdisk_service as module


def _preview_service(monkeypatch):
    service = module.BaiduNetdiskService()
    monkeypatch.setattr(service, '_safe_subdir', lambda _value: None)
    monkeypatch.setattr(service, 'validate_output_folder_name', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, 'parse_share_inputs', lambda _urls: [{'index': index} for index in range(6)])
    monkeypatch.setattr(service, '_preview_item_from_share', lambda share, *_args: {'index': share['index'], 'ok': False})
    monkeypatch.setattr(service, '_is_svip', lambda: False)
    monkeypatch.setattr(service, '_download_root', lambda: '')
    monkeypatch.setattr(service, '_config', lambda: type('Config', (), {'conflict_policy': 'resume'})())
    monkeypatch.setattr(service, '_cache_raw_preview', lambda *_args: None)
    monkeypatch.setattr(module, '_BAIDU_PREVIEW_MAX_CONCURRENCY', 2)
    return service


@pytest.mark.asyncio
async def test_cancelled_preview_awaits_active_children_and_cancels_queued_links(monkeypatch):
    service = _preview_service(monkeypatch)
    both_started = asyncio.Event()
    started = []
    stopped = []

    async def fetch(share, **_kwargs):
        started.append(share['index'])
        if len(started) == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(share['index'])

    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    request = asyncio.create_task(service.preview_urls(['ignored']))
    await asyncio.wait_for(both_started.wait(), timeout=2)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert sorted(stopped) == [0, 1]
    await asyncio.sleep(0)
    assert started == [0, 1]


@pytest.mark.asyncio
async def test_total_deadline_cancels_inflight_and_queued_preview_links(monkeypatch):
    service = _preview_service(monkeypatch)
    monkeypatch.setattr(module, '_BAIDU_PREVIEW_TOTAL_TIMEOUT_SECONDS', 0.02)
    active = set()
    started = []

    async def fetch(share, **_kwargs):
        index = share['index']
        started.append(index)
        active.add(index)
        try:
            await asyncio.Event().wait()
        finally:
            active.remove(index)

    monkeypatch.setattr(service, '_fetch_share_detail', fetch)
    result = await asyncio.wait_for(service.preview_urls(['ignored']), timeout=2)
    assert active == set()
    assert started == [0, 1]
    assert result['failed_count'] == 6
    assert [item['index'] for item in result['items']] == list(range(6))
