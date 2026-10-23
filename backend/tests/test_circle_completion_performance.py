from __future__ import annotations

import asyncio
import threading
import time
from copy import deepcopy

import pytest

from app.core import circle_completion_service as module
from app.core.circle_completion_service import CircleCompletionService
from tests.test_circle_completion_paged_view import _FakeRedisService, _seed_circle


@pytest.fixture
def perf_service(monkeypatch):
    service = CircleCompletionService()
    monkeypatch.setattr(service, "_completion_redis_service", lambda: None)
    monkeypatch.setattr(service, "_schedule_view_cover_cache", lambda *args: None)
    async def resolve(value):
        return "A" if value in {"A", "社团A"} else value
    monkeypatch.setattr(service, "_resolve_completion_scope", resolve)
    return service


def state(scope):
    return {"catalog": {"circle_id": scope, "circle_name": scope}, "items": []}


@pytest.mark.asyncio
async def test_parallel_build_limit_and_cancel_keeps_slot(perf_service, monkeypatch):
    started = set()
    gate = threading.Event()
    guard = threading.Lock()
    active = 0
    peak = 0
    def build(scope):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            started.add(scope)
        assert gate.wait(5), "冷构建未收到释放信号"
        with guard:
            active -= 1
        return state(scope)
    monkeypatch.setattr(perf_service, "_build_completion_view_state_uncached", build)
    tasks = [asyncio.create_task(perf_service._get_completion_view_state(x)) for x in "ABC"]
    try:
        async with asyncio.timeout(3):
            while len(started) < 2:
                await asyncio.sleep(.005)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        await asyncio.sleep(.05)
        assert len(started) == 2
        assert peak == 2
    finally:
        gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*list(perf_service._completion_state_inflight.values()))
    assert started == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_id_and_name_share_build_and_event_loop_ticks(perf_service, monkeypatch):
    calls = 0
    ticks = 0
    ticks_during_build = 0
    def build(scope):
        nonlocal calls, ticks_during_build
        calls += 1
        initial_ticks = ticks
        time.sleep(.12)
        ticks_during_build = ticks - initial_ticks
        return state(scope)
    monkeypatch.setattr(perf_service, "_build_completion_view_state_uncached", build)
    async def ticker():
        nonlocal ticks
        for _ in range(8):
            await asyncio.sleep(.01)
            ticks += 1
    first, second, _ = await asyncio.gather(
        perf_service._get_completion_view_state("A"),
        perf_service._get_completion_view_state("社团A"), ticker(),
    )
    assert calls == 1
    assert first == second
    assert ticks == 8
    assert ticks_during_build >= 4


@pytest.mark.asyncio
async def test_invalidation_during_build_discards_old_generation(perf_service, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    def build(scope):
        nonlocal calls
        calls += 1
        generation = calls
        if generation == 1:
            entered.set()
            assert release.wait(5)
        return {**state(scope), "generation": generation}
    monkeypatch.setattr(perf_service, "_build_completion_view_state_uncached", build)
    task = asyncio.create_task(perf_service._get_completion_view_state("A"))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(.005)
        perf_service.invalidate_completion_view_cache("A")
    finally:
        release.set()
    result = await task
    assert calls == 2
    assert result["generation"] == 2
    assert all(value["generation"] == 2 for value in perf_service._completion_state_cache.values())


def test_redis_outage_invalidation_and_recovery_share_l2(monkeypatch):
    redis = _FakeRedisService()
    service = CircleCompletionService()
    monkeypatch.setattr(service, "_completion_redis_service", lambda: redis)
    before = service._completion_version_tag("A")
    original_mget = redis.client_obj.mget
    original_incr = redis.client_obj.incr
    def broken(*args):
        raise ConnectionError("模拟Redis断线")
    monkeypatch.setattr(redis.client_obj, "mget", broken)
    monkeypatch.setattr(redis.client_obj, "incr", broken)
    local = service._completion_version_tag("A")
    recent = service._completion_recent_cache_key("", 30)
    service.invalidate_completion_view_cache("A")
    assert service._completion_version_tag("A") != local
    assert service._completion_recent_cache_key("", 30) != recent
    reads = []
    def tracked_mget(keys):
        reads.append(keys)
        return original_mget(keys)
    monkeypatch.setattr(redis.client_obj, "mget", tracked_mget)
    monkeypatch.setattr(redis.client_obj, "incr", original_incr)
    recovered = service._completion_version_tag("A")
    assert reads == [[
        redis.key("circle-completion", "epoch", "global"),
        redis.key("circle-completion", "version", "A"),
    ]]
    assert recovered != before
    other = CircleCompletionService()
    monkeypatch.setattr(other, "_completion_redis_service", lambda: redis)
    assert other._completion_version_tag("A") == recovered
    key = service._completion_state_cache_key("A", recovered)
    service._completion_l1_l2_set(service._completion_state_cache, "state", key, state("A"), ttl_seconds=60)
    assert other._completion_l1_l2_get(other._completion_state_cache, "state", key) == state("A")


def test_invalidation_removes_selection_pages_and_lock_release_is_atomic(monkeypatch):
    service = CircleCompletionService()
    redis = _FakeRedisService()
    monkeypatch.setattr(service, "_completion_redis_service", lambda: redis)
    service._completion_page_cache["A|selection|v0|hash|page:1:10"] = {}
    service.invalidate_completion_view_cache("A")
    assert len(service._completion_page_cache) == 0
    key = service._completion_try_acquire_build_lock("A")
    redis.client_obj.store[key] = "另一个持有者"
    service._completion_release_build_lock(key)
    assert redis.client_obj.store[key] == "另一个持有者"


@pytest.mark.asyncio
async def test_name_id_resolve_to_same_real_catalog(db_session, monkeypatch):
    circle_id = _seed_circle(db_session)
    service = CircleCompletionService()
    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(service, "_completion_redis_service", lambda: None)
    monkeypatch.setattr(service, "_schedule_view_cover_cache", lambda *args: None)
    calls = 0
    def build(scope):
        nonlocal calls
        calls += 1
        time.sleep(.04)
        return state(scope)
    monkeypatch.setattr(service, "_build_completion_view_state_uncached", build)
    results = await asyncio.gather(service._get_completion_view_state(circle_id), service._get_completion_view_state("分页社团"))
    assert calls == 1
    assert results[0] == results[1]


def test_pages_reuse_filter_sort_and_isolate_responses(perf_service, monkeypatch):
    snapshot = {"catalog": {"circle_id": "A", "circle_name": "A", "source_mask": "", "last_indexed_at": None}, "items": [
        {"canonical_rjcode": f"RJ0000000{x}", "title": str(x), "owned": False, "has_dlsite": True, "has_asmr_one": True, "linked_rjcodes": [str(x)]}
        for x in range(1, 4)
    ]}
    original = deepcopy(snapshot)
    counts = {"filter": 0, "sort": 0}
    def filtered(items, **kwargs):
        counts["filter"] += 1
        return items
    def sorted_items(items, sort):
        counts["sort"] += 1
        return list(reversed(items))
    monkeypatch.setattr(perf_service, "_filter_completion_items_for_tab", filtered)
    monkeypatch.setattr(perf_service, "_sort_completion_items", sorted_items)
    first = perf_service._list_circle_completion_works_sync("A", snapshot, "v0", page=1, page_size=1)
    first["items"][0]["linked_rjcodes"].append("污染")
    second = perf_service._list_circle_completion_works_sync("A", snapshot, "v0", page=2, page_size=1)
    repeated = perf_service._list_circle_completion_works_sync("A", snapshot, "v0", page=1, page_size=1)
    assert counts == {"filter": 1, "sort": 1}
    assert snapshot == original
    assert "污染" not in repeated["items"][0]["linked_rjcodes"]
    assert second["items"][0]["canonical_rjcode"] != repeated["items"][0]["canonical_rjcode"]


def test_resource_version_preserves_base_and_invalidates_queries(perf_service):
    before = perf_service._completion_version_tag('A')
    page_before = perf_service._completion_query_cache_key('page', 'A', {})
    base_key = perf_service._completion_state_cache_key('A', before)
    perf_service._completion_view_cache[base_key] = state('A')
    perf_service._completion_view_cache['A|resources|old'] = ['旧资源']
    perf_service._completion_selection_cache['A|selection|old'] = {'rows': []}
    perf_service._completion_selection_cache['B|selection|current'] = {'rows': []}
    perf_service.invalidate_completion_resource_cache('A')
    assert perf_service._completion_version_tag('A') == before
    assert perf_service._completion_query_cache_key('page', 'A', {}) != page_before
    assert perf_service._completion_view_cache[base_key] == state('A')
    assert perf_service._completion_view_cache.get('A|resources|old') is None
    assert perf_service._completion_selection_cache.get('A|selection|old') is None
    assert perf_service._completion_selection_cache.get('B|selection|current') == {'rows': []}


def test_resource_refresh_keeps_nested_metadata_and_page_responses_isolated(perf_service, monkeypatch):
    from contextlib import nullcontext
    from app.core.resource_source_service import get_resource_source_service
    snapshot = {'catalog': dict(circle_id='A', circle_name='A', source_mask='', last_indexed_at=None),
                'items': [dict(canonical_rjcode='RJ01699055', title='原作', has_dlsite=True,
                               linked_rjcodes=['RJ01699055'], status_tags=['暂不可下载'],
                               bonus_works=[dict(canonical_rjcode='RJ01699067', title='特典',
                                                 is_bonus_work=True, has_dlsite=True)])]}
    original = deepcopy(snapshot)
    available = False
    def decorate(db, items):
        for item in items:
            item['has_downloadable_source'] = available
            item['status_tags'] = ['可下载'] if available else ['暂不可下载']
    monkeypatch.setattr(module, 'SessionLocal', lambda: nullcontext(None))
    monkeypatch.setattr(get_resource_source_service(), 'decorate_items', decorate)
    first = perf_service._list_circle_completion_works_sync('A', snapshot, 'v0')
    assert first['downloadable_count'] == 0
    assert perf_service._list_circle_completion_works_sync(
        'A', snapshot, 'v0', include_dl_only=False)['total'] == 0
    first['items'][0]['linked_rjcodes'].append('污染')
    first['items'][0]['bonus_works'][0]['title'] = '污染'
    available = True
    perf_service.invalidate_completion_resource_cache('A')
    second = perf_service._list_circle_completion_works_sync('A', snapshot, 'v0')
    assert second['items'][0]['has_downloadable_source'] is True
    assert second['items'][0]['status_tags'] == ['可下载']
    assert second['items'][0]['linked_rjcodes'] == ['RJ01699055']
    assert second['items'][0]['bonus_works'][0]['title'] == '特典'
    assert second['downloadable_count'] == 1
    assert perf_service._list_circle_completion_works_sync(
        'A', snapshot, 'v0', include_dl_only=False)['total'] == 1
    assert snapshot == original
