"""网络去重、共享探测结果与限流正确性回归。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.dlsite_service import DLsiteApiService, DLsiteProductProbeFeature, with_dlsite_api_snapshot
from app.core.dlsite_bonus_probe_service import DLsiteBonusProbeService
from app.core.circle_external_search_service import CircleExternalSearchService
from app.core.resource_source_service import ResourceSourceService
from app.core.asmr_download_service import ASMRDownloadService


@pytest.mark.asyncio
async def test_index_snapshot_survives_lru_eviction_and_releases_on_exit(monkeypatch):
    service = DLsiteApiService()
    calls = []

    async def fetch(url):
        calls.append(url)
        service.cache[url] = {'data': {'workno': url}, 'timestamp': datetime.now()}
        return {'workno': url}

    monkeypatch.setattr(service, '_do_fetch_api', fetch)

    @with_dlsite_api_snapshot
    async def index(owner):
        for _ in range(3):
            for i in range(1133):
                assert await owner.dlsite_service._fetch_api(str(i)) == {'workno': str(i)}

    owner = SimpleNamespace(dlsite_service=service)
    await index(owner)
    assert len(calls) == 1133
    await index(owner)
    assert len(calls) == 2266


@pytest.mark.asyncio
async def test_failed_api_response_is_not_pinned(monkeypatch):
    service = DLsiteApiService()
    fetch = AsyncMock(side_effect=[None, {'ok': True}])
    monkeypatch.setattr(service, '_do_fetch_api', fetch)

    @with_dlsite_api_snapshot
    async def index(owner):
        assert await owner.dlsite_service._fetch_api('retry') is None
        assert await owner.dlsite_service._fetch_api('retry') == {'ok': True}
    await index(SimpleNamespace(dlsite_service=service))
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_overlapping_dates_receive_owner_result_and_abort_releases_waiters():
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    codes = ['RJ01000001', 'RJ01000002']
    shards, _ = await service._lease_candidate_shards(codes, shard_size=2, cached_features={})
    waiters = {}
    duplicate, stats = await service._lease_candidate_shards(codes, shard_size=2,
                                                            cached_features={}, waiters=waiters)
    assert duplicate == [] and stats['active'] == 2
    feature = DLsiteProductProbeFeature(workno=codes[0], exists=False, probe_status='missing')
    service._publish_candidate_features({codes[0]: feature})
    await service._release_candidate_shards(shards)
    assert await waiters[codes[0]] is feature
    assert await waiters[codes[1]] is None
    assert not service._active_probe_results


@pytest.mark.asyncio
async def test_external_pool_reuses_client_and_updates_cookie_per_request(monkeypatch):
    import app.core.circle_external_search_service as module
    clients, cookies = [], []
    original = httpx.AsyncClient

    def build(**kwargs):
        def handle(request):
            cookies.append(request.headers.get('cookie'))
            return httpx.Response(200, text='ok')
        client = original(**kwargs, transport=httpx.MockTransport(handle))
        clients.append(client)
        return client

    monkeypatch.setattr(module.httpx, 'AsyncClient', build)
    service = CircleExternalSearchService()
    await service._fetch_text('https://example.org/one', headers={'Cookie': 'a=1'})
    await service._fetch_text('https://example.org/two', headers={'Cookie': 'a=2'})
    assert len(clients) == 1 and cookies == ['a=1', 'a=2']
    await service.stop()
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_external_pool_normalizes_bare_http_proxy_and_preserves_https(monkeypatch):
    import app.core.circle_external_search_service as module
    clients, proxies = [], []
    original = httpx.AsyncClient

    def build(**kwargs):
        proxies.append(kwargs.pop('proxy', None))
        client = original(**kwargs, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text='ok')))
        clients.append(client)
        return client

    monkeypatch.setattr(module.httpx, 'AsyncClient', build)
    service = CircleExternalSearchService()
    await service._fetch_text('https://example.org/one', proxy=' 127.0.0.1:7890 ')
    await service._fetch_text('https://example.org/two', proxy='http://127.0.0.1:7890')
    await service._fetch_text('https://example.org/three', proxy='https://127.0.0.1:7890')
    assert proxies == ['http://127.0.0.1:7890', 'https://127.0.0.1:7890']
    await service.stop()
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_yaas_fresh_cache_needs_no_distributed_lease(monkeypatch):
    service = ResourceSourceService()
    monkeypatch.setattr(service, 'cached', lambda code: {'fresh': True, 'status': 'missing'})
    monkeypatch.setattr(service, 'lease', lambda *args: pytest.fail('缓存命中不得抢租约'))
    assert (await service.probe('RJ01000001'))['status'] == 'missing'


def test_asmr_concurrent_success_cannot_clear_rate_cooldown():
    service = ASMRDownloadService()
    service._record_rate_limit(SimpleNamespace(headers={'Retry-After': '15'}))
    service._record_asmr_api_success()
    assert service._asmr_api_circuit_remaining() >= 14


def test_v4_completed_date_requires_revalidation():
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    assert not service._can_reuse_completed_date_row(
        SimpleNamespace(mode='normal:date-range-v4', status='completed'), mode='normal')


def test_disabled_sources_never_open_database(monkeypatch):
    import app.core.circle_external_search_service as module
    monkeypatch.setattr(module, 'get_config', lambda: SimpleNamespace(
        circle_external_search=SimpleNamespace(anime_share_enabled=False,
                                              south_plus_enabled=True, south_plus_cookie='')))
    monkeypatch.setattr(module, 'SessionLocal', lambda: pytest.fail('不可用来源不得入队'))
    result = CircleExternalSearchService()._load_or_enqueue_records([
        ('anime_share', 'RJ01000001'), ('south_plus', 'RJ01000001')])
    assert len(result) == 2
    assert all(row['status'] == 'unavailable' for row in result.values())


@pytest.mark.asyncio
async def test_slow_south_worker_does_not_block_anime(monkeypatch):
    service = CircleExternalSearchService()
    south_entered, anime_done = asyncio.Event(), asyncio.Event()
    issued = set()
    monkeypatch.setattr(service, '_source_ready', lambda source: True)

    def claim(source):
        if source in issued:
            return None
        issued.add(source)
        return {'id': source, 'source': source, 'rjcode': 'RJ01000001'}

    async def fetch(source, code):
        if source == 'south_plus':
            south_entered.set()
            await asyncio.Event().wait()
        await south_entered.wait()
        anime_done.set()
        return {'status': 'miss', 'results': []}

    monkeypatch.setattr(service, '_claim_next_record', claim)
    monkeypatch.setattr(service, '_fetch_source', fetch)
    monkeypatch.setattr(service, '_complete_record', lambda *args: None)
    await service.start()
    try:
        await asyncio.wait_for(anime_done.wait(), timeout=3)
    finally:
        await service.stop()


def test_incomplete_coverage_cannot_write_no_bonus(monkeypatch):
    import app.core.dlsite_bonus_probe_service as module
    service = DLsiteBonusProbeService.__new__(DLsiteBonusProbeService)
    monkeypatch.setattr(service, '_upsert_bonus_works', lambda *a, **k: 0)
    monkeypatch.setattr(service, '_mark_original_probe_states_after_scan',
                        lambda **kwargs: pytest.fail('覆盖不完整不得写作品结论'))
    monkeypatch.setattr(service, '_release_date_original_state_summary', lambda *a, **k: {
        'original_count': 1, 'concluded_count': 0, 'pending_count': 1,
        'has_bonus_count': 0, 'no_bonus_count': 0})
    row = SimpleNamespace()
    monkeypatch.setattr(service, '_upsert_date_row', lambda *a, **k: row)
    monkeypatch.setattr(module, 'SessionLocal', lambda: SimpleNamespace(close=lambda: None, commit=lambda: None))
    result = service._finish_probe_date_result(circle_id='test', maker_id='RG49556',
        release_date='2026-10-10', gap_limit=10, mode_key=service._mode_key('normal'),
        hidden_hits=[], target_original_rjcodes=None, result={'incomplete': True})
    assert result['original_pending_count'] == 1
    assert row.status == 'incomplete'
