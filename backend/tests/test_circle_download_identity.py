"""下载目标、语言证据和会话隔离回归；不请求外网。"""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.circle_completion_service import CircleCompletionService
from app.core import resource_source_service as sources


@pytest.fixture
def service(monkeypatch):
    value = CircleCompletionService()
    context = dict(circle_id='circle', circle_name='社团', canonical_rjcode='RJ01699067',
                   display_rjcode='RJ01699067', title='特典', is_bonus_work=True)
    monkeypatch.setattr(value, '_download_preview_context', lambda *args: dict(context))
    monkeypatch.setattr(value, '_describe_download_versions', lambda rows: rows)
    monkeypatch.setattr(value.dlsite_service, 'get_linked_works', AsyncMock())
    monkeypatch.setattr(value.asmr_resource_service, 'build_download_plan', AsyncMock(return_value={
        'rjcode': 'RJ01699067', 'session_id': 'bonus-session', 'selectable_resources': [
            dict(relative_path='bonus.wav', source_workno='RJ01699067', selected=True)]}))
    monkeypatch.setattr(value, '_build_filter_skip_reasons', lambda rows: {})
    async def exact_combine(code, builder, *, exact=False):
        assert exact is True
        assert code == 'RJ01699067'
        return await builder()
    monkeypatch.setattr(sources.get_resource_source_service(), 'combine_plan', exact_combine)
    return value


@pytest.mark.asyncio
async def test_bonus_never_discovers_or_downloads_original(service):
    descriptors = await service._discover_download_versions(service._download_preview_context(), 'RJ01699067')
    assert [row['rjcode'] for row in descriptors] == ['RJ01699067']
    plan = await service.preview_download_version('circle', 'RJ01699067', 'RJ01699067')
    assert plan['rjcode'] == plan['resolved_rjcode'] == 'RJ01699067'
    assert plan['selectable_resources'][0]['source_workno'] == 'RJ01699067'
    service.dlsite_service.get_linked_works.assert_not_called()
    with pytest.raises(ValueError, match='特典只能'):
        await service.preview_download_version('circle', 'RJ01699067', 'RJ01699055')
    assert service.asmr_resource_service.build_download_plan.call_count == 1


@pytest.mark.asyncio
async def test_bonus_rejects_stale_original_plan(service):
    service.asmr_resource_service.build_download_plan.return_value['rjcode'] = 'RJ01699055'
    with pytest.raises(ValueError, match='计划与目标'):
        await service.preview_download_version('circle', 'RJ01699067', 'RJ01699067')


@pytest.mark.asyncio
async def test_bonus_rejects_cross_rj_file(service):
    service.asmr_resource_service.build_download_plan.return_value['selectable_resources'][0]['source_workno'] = 'RJ01699055'
    with pytest.raises(ValueError, match='文件与目标'):
        await service.preview_download_version('circle', 'RJ01699067', 'RJ01699067')


@pytest.mark.asyncio
async def test_language_evidence_order_multiversion_and_failure(service):
    linked = service.dlsite_service.get_linked_works
    linked.return_value = {
        code: dict(workno=code, work_type=kind, evidence_status=evidence, lang='CHI_HANS')
        for code, kind, evidence in [('RJ01699055', 'original', 'verified'),
            ('RJ01699060', 'translation', 'verified'), ('RJ01699061', 'translation', 'verified'),
            ('RJ01699067', 'bonus', 'verified'), ('RJ01699068', 'translation', 'unverified')]}
    context = dict(service._download_preview_context(), is_bonus_work=False)
    rows = await service._discover_download_versions(context, 'RJ01699060')
    assert [row['rjcode'] for row in rows] == ['RJ01699060', 'RJ01699055', 'RJ01699061']
    assert [row['selected_version'] for row in rows] == [True, False, False]
    linked.side_effect = RuntimeError('关联查询失败')
    rows = await service._discover_download_versions(context, 'RJ01699060')
    assert len(rows) == 1 and rows[0]['rjcode'] == 'RJ01699060'
    assert rows[0]['discovery_error'] == '关联查询失败'


@pytest.mark.asyncio
async def test_same_version_singleflight_and_response_isolation(service):
    import asyncio
    left, right = await asyncio.gather(*[
        service.preview_download_version('circle', 'RJ01699067', 'RJ01699067') for _ in range(2)])
    assert service.asmr_resource_service.build_download_plan.call_count == 1
    left['selectable_resources'].clear()
    assert right['selectable_resources']


@pytest.mark.asyncio
async def test_clicked_regular_version_loads_when_language_discovery_fails(service, monkeypatch):
    context = dict(service._download_preview_context(), is_bonus_work=False)
    monkeypatch.setattr(service, '_download_preview_context', lambda *args: dict(context))
    service.dlsite_service.get_linked_works.side_effect = RuntimeError('关联查询失败')
    rows = await service._discover_download_versions(context, 'RJ01699067')
    assert rows[0]['discovery_error'] == '关联查询失败'
    plan = await service.preview_download_version('circle', 'RJ01699067', 'RJ01699067')
    assert plan['resolved_rjcode'] == 'RJ01699067'
    assert service.dlsite_service.get_linked_works.call_count == 1


@pytest.mark.asyncio
async def test_multiple_bonuses_remain_independent_and_ignore_stale_candidates(service, monkeypatch):
    from app.core import library_manager
    context = service._download_preview_context()
    monkeypatch.setattr(service, '_download_preview_context', lambda circle, code: dict(
        context, canonical_rjcode=code, display_rjcode=code))
    monkeypatch.setattr(library_manager, 'get_library_manager', lambda: SimpleNamespace(list_libraries=lambda: []))

    async def build(**kwargs):
        code = kwargs['rjcode']
        return dict(rjcode=code, session_id=code, selectable_resources=[dict(
            relative_path='bonus.wav', source_workno=code, selected=True)])

    service.asmr_resource_service.build_download_plan.side_effect = build
    result = await service.preview_batch_download('circle', ['RJ01699067', 'RJ01699068'],
        {'RJ01699067': ['RJ01699055'], 'RJ01699068': ['RJ01699055']})
    assert [plan['resolved_rjcode'] for plan in result['plans']] == ['RJ01699067', 'RJ01699068']
    assert [plan['session_id'] for plan in result['plans']] == ['RJ01699067', 'RJ01699068']
    service.dlsite_service.get_linked_works.assert_not_called()


def test_session_rejects_cross_rj_and_cross_file(monkeypatch):
    resource = dict(remote_url='https://example.com/bonus', file_name='bonus.wav',
                    relative_path='音声/bonus.wav', source_workno='RJ01699067', size_bytes=42)
    session = SimpleNamespace(rjcode='RJ01699067', selected_resources=[resource])
    monkeypatch.setattr(sources, 'SessionLocal', lambda: nullcontext(SimpleNamespace(get=lambda *args: session)))
    item = dict(rjcode='RJ01699055', session_id='bonus', selected_resources=[deepcopy(resource)])
    with pytest.raises(ValueError, match='会话与目标'):
        sources.ResourceSourceService.validate_asmr_session(item)
    item['rjcode'] = 'RJ01699067'
    item['selected_resources'][0]['remote_url'] = 'https://example.com/original'
    with pytest.raises(ValueError, match='不属于'):
        sources.ResourceSourceService.validate_asmr_session(item)
    item['selected_resources'] = [deepcopy(resource)]
    item['selected_resources'][0]['relative_path'] = 'bonus.wav'
    sources.ResourceSourceService.validate_asmr_session(item)
    assert item['selected_resources'][0]['source_workno'] == 'RJ01699067'


def test_session_preserves_same_name_files_in_different_directories(monkeypatch):
    rows = [dict(remote_url='https://example.com/shared', file_name='bonus.wav',
                 relative_path=f'{folder}/bonus.wav', source_workno='RJ01699067', size_bytes=size)
            for folder, size in [('音声', 42), ('おまけ', 60)]]
    session = SimpleNamespace(rjcode='RJ01699067', selected_resources=rows)
    monkeypatch.setattr(sources, 'SessionLocal', lambda: nullcontext(SimpleNamespace(get=lambda *args: session)))
    item = dict(rjcode='RJ01699067', session_id='bonus', selected_resources=deepcopy(rows))
    sources.ResourceSourceService.validate_asmr_session(item)
    assert [row['size_bytes'] for row in item['selected_resources']] == [42, 60]


def test_version_description_uses_exact_resources_not_workflow_status(db_session, monkeypatch):
    from app.core import circle_completion_service as circle_module
    from app.models.database import ASMRResourceRecord, ASMRWork
    monkeypatch.setattr(circle_module, 'SessionLocal', lambda: nullcontext(db_session))
    db_session.add(ASMRWork(rjcode='RJ01699067', work_status='cataloged'))
    db_session.add_all([
        ASMRResourceRecord(id='bonus-exact', work_rjcode='RJ01699067', source_workno='RJ01699067',
                           source_provider='asmr.one', remote_url='https://example.com/bonus'),
        ASMRResourceRecord(id='bonus-stale', work_rjcode='RJ01699068', source_workno='RJ01699055',
                           source_provider='asmr.one', remote_url='https://example.com/original')])
    db_session.flush()
    rows = CircleCompletionService()._describe_download_versions([
        dict(rjcode='RJ01699067'), dict(rjcode='RJ01699068')])
    assert rows[0]['resource_sources'] == [dict(id='asmr.one', label='asmr.one')]
    assert rows[0]['probe_status'] == 'available'
    assert rows[1]['resource_sources'] == []
