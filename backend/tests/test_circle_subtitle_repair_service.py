"""社团字幕入口的目录隔离、资源依据、持久化与并发回归。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import sessionmaker

from app.core import circle_subtitle_repair_service as repair
from app.core import rj_subtitle_task_service as creation
from app.core import task_engine, library_manager, rj_subtitle_service, resource_source_service
from app.config import settings
from app.models.database import CircleWork, ResourceSourceProbe, WorkCanonicalLink, Task as TaskRecord
from tests.postgres_test_utils import truncate_all_tables


@pytest.fixture
def env(db_engine, monkeypatch, tmp_path):
    truncate_all_tables(db_engine)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(repair, 'SessionLocal', factory)
    monkeypatch.setattr(creation, 'SessionLocal', factory)
    monkeypatch.setattr(creation, '_creation_lock', asyncio.Lock())
    folder = tmp_path / 'RJ123456'
    folder.mkdir()
    (folder / '01.wav').write_bytes(b'audio')
    target = dict(rjcode='RJ123456', library_id='local', library_name='本地库存', library_type='local',
                  folder_path=str(folder), folder_name=folder.name, subtitle_count=0, audio_count=1, eligible=True, reason='')
    service = repair.CircleSubtitleRepairService()
    monkeypatch.setattr(service, 'indexed_targets', lambda codes: {code: [dict(target)] for code in codes})
    subtitle = rj_subtitle_service.RJSubtitleService.__new__(rj_subtitle_service.RJSubtitleService)
    library = SimpleNamespace(id='local', type='local', writable=True, browse_root_path=str(tmp_path), root_path=str(tmp_path))
    manager = library_manager.LibraryManager.__new__(library_manager.LibraryManager)
    manager.get_library_definition = lambda _: library
    monkeypatch.setattr(library_manager, 'get_library_manager', lambda: manager)
    monkeypatch.setattr(rj_subtitle_service, 'get_rj_subtitle_service', lambda: subtitle)
    monkeypatch.setattr(settings, 'get_config', lambda: settings.AppConfig())
    engine = SimpleNamespace(tasks={})
    engine.get_all_tasks = lambda: list(engine.tasks.values())
    async def submit(task):
        engine.tasks[task.id] = task
    def persist(task):
        with factory() as db:
            db.merge(TaskRecord(id=task.id, type=task.type.value, status=task.status.value, source_path=task.source_path,
                                task_metadata=task.task_metadata, created_at=task.created_at))
            db.commit()
    engine.submit, engine.persist_task_snapshot = submit, persist
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: engine)
    with factory() as db:
        db.add(CircleWork(id='work', circle_id='circle', canonical_rjcode='RJ123456', is_bonus_work=False))
        db.add(ResourceSourceProbe(source=repair.PROBE_SOURCE, rjcode='RJ123456', probe_version=1, status='hit',
            candidates=[dict(kind='subtitle', label='发现字幕', rjcode='RJ123456', provider='asmr.one',
                            lang='CHI_HANS', work_type='translation', is_ai=False)], error=''))
        db.commit()
    return SimpleNamespace(service=service, factory=factory, engine=engine, target=target, folder=folder, subtitle=subtitle, library=library)


@pytest.mark.parametrize('verified,kind', [(True, 'subtitle'), (False, 'subtitle_package')])
def test_source_evidence_never_persists_direct_urls(verified, kind):
    result = repair.source_evidence(dict(has_subtitle=True, subtitle_verified=verified,
        selected_source=dict(rjcode='RJ123456', source_provider='yaas', subtitle_is_ai=True, download_url='https://secret.invalid/token')))
    assert result[0]['kind'] == kind
    assert result[0]['is_ai'] is True
    assert 'secret' not in repr(result)
    assert repair.source_evidence({'has_subtitle': False}) == []


@pytest.mark.asyncio
async def test_single_location_creates_real_fetch_task_and_reuses(env):
    first = await env.service.start('circle', ['RJ123456'])
    second = await env.service.start('circle', ['RJ123456'])
    assert first['created_count'] == second['reused_count'] == 1
    assert first['items'][0]['task_id'] == second['items'][0]['task_id']
    task = next(iter(env.engine.tasks.values()))
    assert task.type == task_engine.TaskType.RJ_SUBTITLE_FETCH
    assert task.task_metadata['existing_subtitle_scope'] == 'folder'
    assert task.task_metadata['overwrite'] is False
    assert task.task_metadata['force_rerun'] is False
    assert task.task_metadata['rjcode'] == 'RJ123456'
    assert task.task_metadata['source_action'] == 'circle_subtitle_repair'
    assert task.task_metadata['subtitle_source_hint'] == {
        'rjcode': 'RJ123456', 'provider': 'asmr.one', 'is_ai': False,
        'lang': 'CHI_HANS', 'work_type': 'translation',
    }


@pytest.mark.asyncio
async def test_legacy_probe_recovers_child_translation_from_local_links(env):
    with env.factory() as db:
        probe = db.get(ResourceSourceProbe, (repair.PROBE_SOURCE, 'RJ123456', 1))
        probe.candidates = [dict(kind='subtitle', rjcode='RJ234567', provider='asmr.one', is_ai=False)]
        db.add(WorkCanonicalLink(id='child', canonical_rjcode='RJ123456', linked_rjcode='RJ234567',
                                link_type='child_translation', lang='CHI_HANS'))
        db.commit()
    result = await env.service.start('circle', ['RJ123456'])
    assert result['created_count'] == 1
    task = next(iter(env.engine.tasks.values()))
    hint = task.task_metadata['subtitle_source_hint']
    assert hint['rjcode'] == 'RJ234567'
    assert hint['lang'] == 'CHI_HANS'
    assert hint['work_type'] == 'child_translation'
    source = SimpleNamespace(workno=hint['rjcode'], lang=hint['lang'])
    candidates = env.subtitle._collect_subtitle_candidates(source, [
        dict(title='track01.vtt', media_download_url='https://test.invalid/subtitle'),
    ])
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_yaas_task_keeps_safe_probed_location_without_signed_url(env):
    from app.core import yaas_subtitle_service as yaas
    archive = dict(name='RJ123456.zip', size=100,
                   path=yaas.BASE + '/' + yaas.COLLECTIONS[0][0] + '/RJ123456.zip',
                   download_url='https://secret.invalid/signed')
    evidence = repair.source_evidence(dict(has_subtitle=True, subtitle_verified=False,
        selected_source=dict(rjcode='RJ123456', source_provider='yaas', subtitle_is_ai=True,
                             archive_files=[archive], subtitle_package=True)))
    with env.factory() as db:
        db.get(ResourceSourceProbe, (repair.PROBE_SOURCE, 'RJ123456', 1)).candidates = evidence
        db.commit()
    result = await env.service.start('circle', ['RJ123456'])
    assert result['created_count'] == 1
    hint = next(iter(env.engine.tasks.values())).task_metadata['subtitle_source_hint']
    assert hint['archive_files'] == [{key: archive[key] for key in ('name', 'size', 'path')}]
    assert hint['subtitle_package'] is True
    assert 'secret' not in repr(hint)


@pytest.mark.asyncio
async def test_parallel_clicks_create_only_one_task(env):
    responses = await asyncio.gather(*(env.service.start('circle', ['RJ123456']) for _ in range(4)))
    assert sum(result['created_count'] for result in responses) == 1
    assert sum(result['reused_count'] for result in responses) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['waiting_manual', 'completed'])
async def test_restart_reuses_waiting_manual_record(env, status):
    first = await env.service.start('circle', ['RJ123456'])
    with env.factory() as db:
        row = db.get(TaskRecord, first['items'][0]['task_id'])
        row.status = status
        row.task_metadata = {**row.task_metadata, 'awaiting_manual_match': True}
        db.commit()
    env.engine.tasks.clear()
    response = await env.service.start('circle', ['RJ123456'])
    assert response['reused_count'] == 1
    assert response['items'][0]['awaiting_manual_match'] is True
    assert env.service.task_states('circle', ['RJ123456'])['RJ123456'][0]['task_id'] == first['items'][0]['task_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['failed', 'cancelled'])
async def test_failed_or_cancelled_requires_workbench_retry(env, status):
    result = await env.service.start('circle', ['RJ123456'])
    task = next(iter(env.engine.tasks.values()))
    task.status = task_engine.TaskStatus(status)
    env.engine.persist_task_snapshot(task)
    env.engine.tasks.clear()
    again = await env.service.start('circle', ['RJ123456'])
    assert again['reused_count'] == 1
    assert again['items'][0]['task_id'] == result['items'][0]['task_id']


@pytest.mark.asyncio
async def test_multiple_locations_require_explicit_selection(env, monkeypatch):
    other = {**env.target, 'folder_path': str(env.folder.parent / 'other' / 'RJ123456')}
    monkeypatch.setattr(env.service, 'indexed_targets', lambda codes: {code: [env.target, other] for code in codes})
    first = await env.service.start('circle', ['RJ123456'])
    assert first['items'][0]['state'] == 'selection_required'
    assert not env.engine.tasks
    selected = {'RJ123456': [dict(library_id='local', folder_path=str(env.folder))]}
    response = await env.service.start('circle', ['RJ123456'], selected)
    assert response['created_count'] == 1
    assert len(env.engine.tasks) == 1


@pytest.mark.asyncio
async def test_invalid_selection_and_cross_circle_cannot_create(env):
    bad = {'RJ123456': [dict(library_id='local', folder_path='C:/outside/RJ123456')]}
    result = await env.service.start('circle', ['RJ123456'], bad)
    assert result['skipped_count'] == 1
    result = await env.service.start('other-circle', ['RJ123456'])
    assert result['skipped_count'] == 1
    assert not env.engine.tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('condition,reason', [('subtitle', '已有字幕'), ('loose_subtitle', '已有字幕'), ('missing', '已不存在'), ('audio', '没有音频')])
async def test_rechecks_actual_folder_before_create(env, condition, reason):
    if condition == 'subtitle':
        (env.folder / 'subtitles').mkdir()
        (env.folder / 'subtitles' / '01.lrc').write_text('subtitle')
    elif condition == 'loose_subtitle':
        (env.folder / '01.LRC').write_text('subtitle')
    elif condition == 'audio':
        (env.folder / '01.wav').unlink()
    else:
        (env.folder / '01.wav').unlink()
        env.folder.rmdir()
    result = await env.service.start('circle', ['RJ123456'])
    assert result['skipped_count'] == 1
    assert reason in result['items'][0]['reason']
    assert not env.engine.tasks


@pytest.mark.asyncio
async def test_no_resource_evidence_does_not_create(env):
    with env.factory() as db:
        db.query(ResourceSourceProbe).delete()
        db.commit()
    result = await env.service.start('circle', ['RJ123456'])
    assert result['skipped_count'] == 1
    assert '尚未探测' in result['items'][0]['reason']


@pytest.mark.parametrize('owned,bonus,subtitles,resource,expected', [
    (True, False, False, 'subtitle', True),
    (True, False, True, 'subtitle', False),
    (False, False, False, 'subtitle', False),
    (True, True, False, 'subtitle', False),
    (True, False, False, 'translation', True),
    (True, False, False, 'dlsite_only', False),
])
def test_decorator_uses_directory_state_and_positive_evidence(env, monkeypatch, owned, bonus, subtitles, resource, expected):
    target = {**env.target, 'eligible': not subtitles, 'subtitle_count': int(subtitles)}
    monkeypatch.setattr(env.service, 'indexed_targets', lambda codes: {code: [target] if owned else [] for code in codes})
    item = dict(canonical_rjcode='RJ123456', local_owned=owned, is_bonus_work=bonus, subtitle_translation_rjcodes=['RJ234567'], resource_sources=[])
    if resource != 'subtitle':
        with env.factory() as db:
            db.query(ResourceSourceProbe).delete()
            db.commit()
    if resource == 'translation':
        item['resource_sources'] = [dict(id='imoutoheaven', rjcodes=['RJ234567'])]
    with env.factory() as db:
        env.service.decorate_items(db, [item])
    assert item['subtitle_repairable'] is expected
    if resource == 'translation' and expected:
        assert item['subtitle_repair_sources'][0]['kind'] == 'translated_audio'


def test_remote_scope_validation(env, monkeypatch):
    remote = SimpleNamespace(type='synology_filestation', root_path='/ASMR', browse_root_path='/ASMR', writable=True)
    manager = SimpleNamespace(_normalize_remote_path=lambda p: p, _remote_path_is_within_root=lambda p, r: p == r or p.startswith(r + '/'))
    monkeypatch.setattr(library_manager, 'get_library_manager', lambda: manager)
    env.service.validate_path(remote, '/ASMR/RJ123456')
    for path in ['/elsewhere/RJ123456', '/ASMR/../secret']:
        with pytest.raises(PermissionError):
            env.service.validate_path(remote, path)


@pytest.mark.asyncio
async def test_remote_directory_inspects_only_selected_location(env, monkeypatch):
    env.library.type = 'synology_filestation'
    env.library.root_path = env.library.browse_root_path = '/'
    env.library.synology = object()
    client = SimpleNamespace(stat=AsyncMock(return_value=[dict(isdir=True)]))
    manager = SimpleNamespace(get_library_definition=lambda _: env.library, get_cached_synology_client=lambda _: client,
        _first_remote_info_item=lambda result: result[0], folder_contents=AsyncMock(return_value={'items': [dict(name='01.wav', relative_path='01.wav')]}))
    monkeypatch.setattr(library_manager, 'get_library_manager', lambda: manager)
    env.service.validate_path = lambda *_: None
    remote_target = {**env.target, 'folder_path': '/ASMR/RJ123456'}
    state = await env.service.inspect_target(remote_target)
    assert state['audio_count'] == 1
    manager.folder_contents.assert_awaited_once_with('local', '/ASMR/RJ123456', client=client, prefer_index=False)
    manager.folder_contents.return_value['items'].append(dict(name='01.lrc', relative_path='01.lrc'))
    with pytest.raises(ValueError, match='已有字幕'):
        await env.service.inspect_target(remote_target)


def test_mixed_original_copies_keep_repairable_even_when_display_is_translation(env, monkeypatch):
    monkeypatch.setattr(env.service, 'indexed_targets', lambda codes: {code: [
        {**env.target, 'eligible': False, 'subtitle_count': 1}, env.target] for code in codes})
    item = dict(canonical_rjcode='RJ123456', display_rjcode='RJ234567', owned=False)
    with env.factory() as db:
        env.service.decorate_items(db, [item])
    assert item['subtitle_repairable'] is True
    assert item['subtitle_original_target_count'] == 2
    assert item['subtitle_missing_target_count'] == 1


@pytest.mark.asyncio
async def test_empty_position_selection_is_reported_as_skipped(env):
    result = await env.service.start('circle', ['RJ123456'], {'RJ123456': []})
    assert result['skipped_count'] == 1
    assert not env.engine.tasks


def test_index_summary_uses_active_generation_watermark_and_masks(env):
    from app.core.library_index.snapshot_store import SnapshotStore
    from app.models.database import LibraryIndexEntry, LibraryIndexStatus, LibraryIndexPendingMask, LibraryIndexMutationOperation
    with env.factory() as db:
        db.add(LibraryIndexStatus(library_id='indexed', status='ready', active_generation=2, materialized_seq=3, updated_at=1))
        rows = [('a/01.WAV', 2, 0), ('a/subtitles/02.wav', 2, 0), ('a/subtitles [AI]/03.WAV', 2, 0),
                ('b/01.wav', 2, 0), ('b/01.LRC', 2, 0), ('a/stale.lrc', 1, 0),
                ('a/future.lrc', 2, 4), ('a/hidden.lrc', 2, 0), ('a/masked/01.lrc', 2, 0)]
        for path, generation, seq in rows:
            db.add(LibraryIndexEntry(library_id='indexed', generation=generation, materialized_seq=seq,
                relative_path=path, absolute_path='/ASMR/' + path, name=path.rsplit('/', 1)[-1], entry_type='file', indexed_at=1))
        db.add(LibraryIndexMutationOperation(operation_id='mask-op', idempotency_key='mask-op', request_fingerprint='test', kind='delete'))
        db.flush()
        for number, (path, scope) in enumerate([('a/hidden.lrc', 'exact'), ('a/masked', 'subtree')]):
            db.add(LibraryIndexPendingMask(operation_id='mask-op', effect_no=number, kind='delete', library_id='indexed', relative_path=path, scope=scope, ledger_seq=4))
        db.commit()
    store = SnapshotStore(session_factory=env.factory)
    result = store.summarize_subtitle_targets_many('indexed', ['a', 'b', 'empty'],
        audio_extensions={'.wav'}, subtitle_extensions={'.lrc'})
    assert result == {'a': {'audio_count': 1, 'subtitle_count': 0},
                      'b': {'audio_count': 1, 'subtitle_count': 1},
                      'empty': {'audio_count': 0, 'subtitle_count': 0}}


@pytest.mark.parametrize('lang,provider,complete,expected', [
    ('CHI_HANS', 'asmr', True, True),
    ('CHI_HANT', 'yaas', True, True),
    ('CHI_HANT', 'yaas', False, False),
    ('ENG', 'asmr', True, False),
    ('CHI_HANS', 'dlsite', True, False),
])
def test_translation_source_requires_chinese_resource_hit(env, lang, provider, complete, expected):
    with env.factory() as db:
        db.query(ResourceSourceProbe).delete()
        db.add(WorkCanonicalLink(id='translation', canonical_rjcode='RJ123456', linked_rjcode='RJ234567', link_type='translation', lang=lang))
        if provider == 'asmr':
            row = db.get(CircleWork, 'work')
            row.has_asmr_one, row.asmr_available_rjcode = True, 'RJ234567'
        elif provider == 'yaas':
            db.add(ResourceSourceProbe(source=resource_source_service.SOURCE, probe_version=resource_source_service.VERSION,
                rjcode='RJ234567', status='hit', candidates=[{'complete': complete}], error=''))
        db.commit()
    assert env.service.has_source('circle', 'RJ123456') is expected
    if expected:
        hint = env.service.source_hint('RJ123456', 'circle')
        assert hint['rjcode'] == 'RJ234567'
        assert hint['lang'] == lang
        assert hint['kind'] == 'translated_audio'


@pytest.mark.asyncio
@pytest.mark.parametrize('probe_error', [False, True])
async def test_probe_uncertainty_remains_retryable(env, monkeypatch, probe_error):
    env.subtitle.probe_cached_subtitle_availability = AsyncMock(
        side_effect=RuntimeError('remote') if probe_error else None,
        return_value={'attempts': [{'reason': 'timeout'}]})
    notify = Mock()
    monkeypatch.setattr(resource_source_service, 'get_resource_source_service', lambda: SimpleNamespace(notify_circles=notify))
    await env.service._probe_code('RJ123456')
    with env.factory() as db:
        row = db.get(ResourceSourceProbe, (repair.PROBE_SOURCE, 'RJ123456', 1))
        assert row.status == ('error' if probe_error else 'unknown')
        assert row.candidates == []
        assert row.expires_at is None
    assert not env.service.has_source('circle', 'RJ123456')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['hit', 'missing', 'unknown', 'error'])
async def test_expired_subtitle_probe_requires_explicit_refresh(env, monkeypatch, status):
    with env.factory() as db:
        row = db.get(ResourceSourceProbe, (repair.PROBE_SOURCE, 'RJ123456', 1))
        row.status = status
        row.expires_at = datetime.now() - timedelta(days=1)
        db.commit()
    probe = AsyncMock()
    monkeypatch.setattr(env.service, '_probe_code', probe)
    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield
    monkeypatch.setattr(resource_source_service, 'get_resource_source_service', lambda: SimpleNamespace(lease=lease))
    await env.service.probe_pending()
    probe.assert_not_awaited()
    env.service.enqueue_probe_codes(['RJ123456'], refresh=True)
    await env.service.probe_pending()
    probe.assert_awaited_once_with('RJ123456')


@pytest.mark.parametrize('status', ['hit', 'missing', 'unknown', 'error'])
def test_expired_yaas_probe_is_not_automatically_requeued(env, monkeypatch, status):
    monkeypatch.setattr(resource_source_service, 'SessionLocal', env.factory)
    with env.factory() as db:
        db.add(ResourceSourceProbe(source=resource_source_service.SOURCE, rjcode='RJ234567', probe_version=1,
            status=status, candidates=[], expires_at=datetime.now() - timedelta(days=1)))
        db.add(ResourceSourceProbe(source=resource_source_service.SOURCE, rjcode='RJ345678', probe_version=1,
            status='pending', candidates=[]))
        db.commit()
    assert resource_source_service.ResourceSourceService().pending_codes() == [('RJ345678',)]


def test_resource_overlay_is_shared_by_parallel_views(env, monkeypatch):
    from app.core import circle_completion_service as completion
    service = completion.CircleCompletionService()
    monkeypatch.setattr(service, '_completion_query_cache_key', lambda *args, **kwargs: 'shared')
    monkeypatch.setattr(service, '_completion_redis_get_json', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, '_completion_redis_set_json', lambda *args, **kwargs: None)
    monkeypatch.setattr(completion, 'SessionLocal', env.factory)
    decorate = Mock()
    monkeypatch.setattr(resource_source_service, 'get_resource_source_service', lambda: SimpleNamespace(decorate_items=decorate))
    monkeypatch.setattr(repair, 'get_circle_subtitle_repair_service', lambda: SimpleNamespace(decorate_items=decorate))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service._completion_items_with_resources('circle', {'items': []}), range(4)))
    assert results == [[], [], [], []]
    assert decorate.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['hit', 'missing', 'unknown', 'error'])
async def test_yaas_fact_survives_expiry_and_manual_refresh_is_consumed_once(env, monkeypatch, status):
    monkeypatch.setattr(resource_source_service, 'SessionLocal', env.factory)
    service = resource_source_service.ResourceSourceService()
    service._worker = SimpleNamespace(done=lambda: False)
    with env.factory() as db:
        db.add(ResourceSourceProbe(source=resource_source_service.SOURCE, rjcode='RJ234567', probe_version=1,
            status=status, candidates=[], expires_at=datetime.now() - timedelta(days=1)))
        db.commit()
    request = AsyncMock(return_value={'content': []})
    monkeypatch.setattr(service, 'request', request)
    monkeypatch.setattr(service, '_is_unreleased', lambda code: False)
    monkeypatch.setattr(service, 'notify_circles', Mock())
    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield
    monkeypatch.setattr(service, 'lease', lease)
    assert service.cached('RJ234567')['fresh'] is True
    assert (await service.probe('RJ234567'))['status'] == status
    request.assert_not_awaited()
    service.schedule_codes(['RJ234567'], refresh=True)
    await asyncio.gather(*service._queue_tasks)
    assert service.pending_codes() == [('RJ234567',)]
    assert service.cached('RJ234567')['fresh'] is False
    await service.probe('RJ234567', refresh=True)
    assert request.await_count > 0
    assert service.pending_codes() == []
    with env.factory() as db:
        assert db.get(ResourceSourceProbe, (resource_source_service.SOURCE, 'RJ234567', 1)).expires_at is None
    request.reset_mock()
    await service.probe('RJ234567')
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_owned_sync_does_not_invalidate_or_broadcast(env, monkeypatch):
    from app.core import circle_completion_service as completion, task_notification_service
    monkeypatch.setattr(completion, 'SessionLocal', env.factory)
    service = completion.CircleCompletionService()
    monkeypatch.setattr(service, 'resolve_canonical_rj', AsyncMock(return_value={'canonical_rjcode': 'RJ123456'}))
    monkeypatch.setattr(service, '_load_bonus_rjcodes_for_owned_state', lambda codes: set())
    invalidate, broadcast = Mock(), Mock()
    monkeypatch.setattr(service, 'invalidate_completion_view_cache', invalidate)
    monkeypatch.setattr(task_notification_service, '_sse_broadcast', broadcast)
    manager = library_manager.get_library_manager()
    manager.find_rj_in_ready_index = lambda *args, **kwargs: {'RJ123456': [
        {'path': str(env.folder), 'library_id': 'local', 'file_count': 1}]}
    await service.sync_owned_for_rj('RJ123456', str(env.folder), 'local')
    invalidate.assert_called_once_with('circle')
    broadcast.assert_called_once()
    invalidate.reset_mock()
    broadcast.reset_mock()
    await service.sync_owned_for_rj('RJ123456', str(env.folder), 'local')
    invalidate.assert_not_called()
    broadcast.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('condition', ['subtitle', 'audio', 'missing'])
async def test_execution_rechecks_folder_after_queueing(env, monkeypatch, condition):
    await env.service.start('circle', ['RJ123456'])
    task = next(iter(env.engine.tasks.values()))
    env.subtitle.process_folder = AsyncMock()
    monkeypatch.setattr(repair, 'get_circle_subtitle_repair_service', lambda: env.service)
    if condition == 'subtitle':
        (env.folder / '01.lrc').write_text('subtitle')
    else:
        (env.folder / '01.wav').unlink()
        if condition == 'missing':
            env.folder.rmdir()
    executor = task_engine.TaskEngine.__new__(task_engine.TaskEngine)
    await executor._process_rj_subtitle_fetch(task)
    env.subtitle.process_folder.assert_not_awaited()
    assert task.status == task_engine.TaskStatus.COMPLETED
    assert task.task_metadata['subtitle_repair_skipped_reason']
    assert '跳过' in task.current_step


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome,expected', [('missing', 'failed'), ('manual', 'waiting_manual'), ('cancelled', 'cancelled')])
async def test_folder_scope_does_not_use_other_copy_subtitle_state(env, monkeypatch, outcome, expected):
    await env.service.start('circle', ['RJ123456'])
    task = next(iter(env.engine.tasks.values()))
    monkeypatch.setattr(repair, 'get_circle_subtitle_repair_service', lambda: env.service)
    manager = library_manager.get_library_manager()
    monkeypatch.setattr(manager, 'find_rj_in_ready_index', Mock(side_effect=AssertionError('不得按 RJ 合并其它副本状态')))
    result = {'success': outcome == 'manual', 'awaiting_manual_match': outcome == 'manual', 'error': '没有找到字幕'}
    env.subtitle.process_folder = AsyncMock(return_value=result)
    if outcome == 'cancelled':
        env.subtitle.process_folder.side_effect = asyncio.CancelledError()
    from app.core import task_notification_service
    monkeypatch.setattr(task_notification_service, 'enqueue_notification_check', AsyncMock())
    executor = task_engine.TaskEngine.__new__(task_engine.TaskEngine)
    if outcome == 'cancelled':
        with pytest.raises(asyncio.CancelledError):
            await executor._process_rj_subtitle_fetch(task)
        task.cancel()
    else:
        await executor._process_rj_subtitle_fetch(task)
    await asyncio.sleep(0)
    env.subtitle.process_folder.assert_awaited_once()
    manager.find_rj_in_ready_index.assert_not_called()
    assert task.status.value == expected
    assert creation.task_payload(task)['awaiting_manual_match'] is (outcome == 'manual')


@pytest.mark.parametrize('status,manual,expected', [
    ('pending', False, 'failed'), ('processing', False, 'failed'),
    ('processing', True, 'waiting_manual'), ('failed', True, 'failed'),
    ('cancelled', True, 'cancelled'),
])
def test_circle_task_restart_preserves_actionable_state(env, monkeypatch, status, manual, expected):
    from app.models import database
    monkeypatch.setattr(database, 'SessionLocal', env.factory)
    with env.factory() as db:
        db.add(TaskRecord(id='recovery', type='rj_subtitle_fetch', status=status, source_path=str(env.folder),
            task_metadata={'source_action': 'circle_subtitle_repair', 'rjcode': 'RJ123456', 'awaiting_manual_match': manual}))
        db.commit()
    engine = task_engine.TaskEngine()
    monkeypatch.setattr(engine, 'persist_task_center_item_snapshot', Mock())
    try:
        assert engine.load_persisted_linked_subtitle_tasks() == 1
        assert engine.tasks['recovery'].status.value == expected
        assert creation.task_payload(engine.tasks['recovery'])['awaiting_manual_match'] is (expected == 'waiting_manual')
    finally:
        engine._materialized_snapshot_executor.shutdown(wait=True)


def test_task_state_prefers_active_over_newer_history(env):
    from datetime import datetime, timedelta
    metadata = {'rjcode': 'RJ123456', 'library_id': 'local', 'folder_path': str(env.folder)}
    with env.factory() as db:
        db.add_all([
            TaskRecord(id='active', type='rj_subtitle_fetch', status='waiting_manual', source_path=str(env.folder),
                       task_metadata={**metadata, 'awaiting_manual_match': True}, created_at=datetime.now() - timedelta(hours=1)),
            TaskRecord(id='history', type='rj_subtitle_fetch', status='cancelled', source_path=str(env.folder),
                       task_metadata={**metadata, 'awaiting_manual_match': True}, created_at=datetime.now()),
        ])
        db.commit()
    assert env.service.task_states('circle', ['RJ123456'])['RJ123456'][0]['task_id'] == 'active'


def test_inventory_subtitle_task_for_linked_rj_maps_to_circle_original(env):
    with env.factory() as db:
        work = db.query(CircleWork).filter_by(circle_id='circle', canonical_rjcode='RJ123456').one()
        work.display_rjcode = 'RJ654321'
        work.linked_rjcodes = ['RJ654321']
        db.add(TaskRecord(
            id='linked-inventory-task',
            type='rj_subtitle_fetch',
            status='processing',
            source_path=str(env.folder),
            task_metadata={
                'rjcode': 'RJ654321',
                'library_id': 'local',
                'folder_path': str(env.folder),
            },
        ))
        db.commit()

    tasks = env.service.task_states('circle', ['RJ123456'])
    assert [task['task_id'] for task in tasks['RJ123456']] == ['linked-inventory-task']


@pytest.mark.asyncio
async def test_batch_reports_partial_creation(env):
    response = await env.service.start('circle', ['RJ123456', 'RJ234567'])
    assert response['created_count'] == response['skipped_count'] == 1
    assert response['items'][1]['canonical_rjcode'] == 'RJ234567'


@pytest.mark.asyncio
async def test_written_subtitles_refresh_index_and_circle_state(env, monkeypatch):
    from app.core import circle_completion_service
    await env.service.start('circle', ['RJ123456'])
    task = next(iter(env.engine.tasks.values()))
    monkeypatch.setattr(repair, 'get_circle_subtitle_repair_service', lambda: env.service)
    manager = library_manager.get_library_manager()
    index_replace = Mock()
    monkeypatch.setattr(manager, '_enqueue_index_replace_subtree_many', index_replace)
    sync = AsyncMock()
    monkeypatch.setattr(circle_completion_service, 'get_circle_completion_service', lambda: SimpleNamespace(sync_subtitle_for_rj=sync))
    subtitle_dir = str(env.folder / 'subtitles')
    env.subtitle.process_folder = AsyncMock(return_value={
        'success': True, 'rjcode': 'RJ123456', 'written_files': ['01.lrc'], 'subtitle_dir': subtitle_dir,
    })
    executor = task_engine.TaskEngine.__new__(task_engine.TaskEngine)
    await executor._process_rj_subtitle_fetch(task)
    assert task.status == task_engine.TaskStatus.COMPLETED
    index_replace.assert_called_once_with(env.library, [subtitle_dir])
    sync.assert_awaited_once_with('RJ123456', folder_path=str(env.folder), library_id='local',
                                subtitle_dir=subtitle_dir, subtitle_file_count=1)
