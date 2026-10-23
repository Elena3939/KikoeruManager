import asyncio
from types import SimpleNamespace

import pytest

from app.core.extract_runtime import AdjustableLimiter, archive_node, record_event
from app.core.filter_planner import plan_filter
from app.core.filter_recovery_service import FilterRecoveryService


@pytest.mark.asyncio
async def test_chain_includes_ancestors_and_sibling_wait_without_double_counting():
    task = SimpleNamespace(task_metadata={})
    async with archive_node(task, "parent", root=True):
        record_event("execution", 0, ended=30)
        async with archive_node(task, "child"):
            record_event("wait", 30, ended=90)
            record_event("execution", 90, ended=110)
            async with archive_node(task, "grandchild"):
                record_event("execution", 110, ended=120)
        async with archive_node(task, "sibling"):
            record_event("wait", 30, ended=50)
            record_event("execution", 50, ended=55)
    timing = task.task_metadata['extract_timing']
    chains = {c['archive']: c['durations_ms'] for c in timing['chains']}
    assert chains['grandchild'] == {'execution': 60000, 'wait': 60000, 'inspect': 0}
    assert chains['sibling']['execution'] == 35000
    assert timing['totals_ms']['execution'] == 65000
    assert timing['totals_ms']['wait'] == 80000


@pytest.mark.asyncio
async def test_resize_keeps_active_count_and_cancelled_waiter_releases_slot():
    limiter = AdjustableLimiter(2)
    await limiter.acquire()
    await limiter.acquire()
    limiter.resize(1)
    waiting = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    limiter.release()
    assert not waiting.done()
    limiter.resize(2)
    await waiting
    assert limiter.active == 2
    pending = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    limiter.release()
    limiter.release()
    assert limiter.active == 0
    assert not limiter.waiters


def test_filter_tree_parent_selection_and_subtree_size():
    items = [
        {'relative_path': 'remove', 'name': 'remove', 'type': 'dir', 'size': None},
        {'relative_path': 'remove/child', 'name': 'child', 'type': 'dir', 'size': None},
        {'relative_path': 'remove/child/a.tmp', 'name': 'a.tmp', 'type': 'file', 'size': 7},
        {'relative_path': 'keep/a.tmp', 'name': 'a.tmp', 'type': 'file', 'size': 2},
    ]
    rules = [SimpleNamespace(enabled=True, target='all', pattern=r'remove|child|\.tmp$', name='test')]
    directories, files = plan_filter(items, rules, True)
    assert [(i['relative_path'], i['size']) for i in directories] == [('remove', 7)]
    assert [i['relative_path'] for i in files] == ['keep/a.tmp']


def test_recovery_batches_keep_old_payload_and_target(tmp_path):
    recovery = FilterRecoveryService(str(tmp_path / 'recovery'))
    source = tmp_path / 'remove.txt'
    source.write_bytes(b'first')
    recovery.begin_capture('task')
    first = recovery.capture_item('task', str(source), relative_path='remove.txt', entry_type='file', size=5)
    recovery.finalize_task('task', final_root='old-target')
    recovery.begin_capture('task')
    source.write_bytes(b'second')
    second = recovery.capture_item('task', str(source), relative_path='remove.txt', entry_type='file', size=6)
    recovery.finalize_task('task', final_root='new-target')
    manifest = recovery._read_manifest('task')
    assert first['batch_id'] != second['batch_id']
    assert len(manifest['items']) == 2
    assert manifest['batches'][first['batch_id']]['target']['root'] == 'old-target'
    assert manifest['batches'][second['batch_id']]['target']['root'] == 'new-target'
    assert recovery._payload_path('task', first).read_bytes() == b'first'


def test_preparing_record_recovers_after_publish(tmp_path, monkeypatch):
    recovery = FilterRecoveryService(str(tmp_path / 'recovery'))
    source = tmp_path / 'item'
    source.write_bytes(b'abc')
    recovery.begin_capture('task')
    write = recovery._write_item
    def crash(task_id, item):
        if item['recovery_status'] == 'available':
            raise SystemExit('模拟发布后退出')
        write(task_id, item)
    monkeypatch.setattr(recovery, '_write_item', crash)
    with pytest.raises(SystemExit):
        recovery.capture_item('task', str(source), relative_path='item', entry_type='file', size=3)
    restarted = FilterRecoveryService(str(tmp_path / 'recovery'))
    restarted.begin_capture('task')
    item = restarted._read_manifest('task')['items'][0]
    assert item['recovery_status'] == 'available'
    assert restarted._payload_path('task', item).read_bytes() == b'abc'
