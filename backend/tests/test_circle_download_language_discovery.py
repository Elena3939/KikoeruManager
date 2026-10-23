"""发行页未收录时，仍从原作发现源站真实译本；不访问网络或数据库。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.circle_download_preview import CircleDownloadPreviewMixin
from app.core.asmr_resource_service import ASMRSourceUnavailableError


class PreviewService(CircleDownloadPreviewMixin):
    normalize_rjcode = staticmethod(lambda value: str(value or '').upper())


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [ValueError('未找到作品'), ASMRSourceUnavailableError('源站暂不可用')])
async def test_uncollected_display_edition_discovers_actual_translation(failure, monkeypatch):
    service = PreviewService()
    context = dict(circle_id='RG68316', circle_name='社团', canonical_rjcode='RJ01509269',
                   display_rjcode='RJ01524705', title='测试作品', is_bonus_work=False)
    service.dlsite_service = SimpleNamespace(get_linked_works=AsyncMock(return_value={
        'original': dict(workno='RJ01509269', work_type='original', lang='JPN', evidence_status='verified'),
        'translation': dict(workno='RJ01524705', work_type='translation', lang='CHI_HANS', evidence_status='verified'),
    }))
    payload = dict(title='测试原作',
        language_editions=[dict(workno='RJ01524705', lang='CHI_HANS')],
        other_language_editions_in_db=[dict(source_id='RJ01524706', lang='简体中文',
            source_type='DLSITE', is_original=False)])

    async def fetch(code, *, refresh=False):
        if code == 'RJ01524705':
            raise failure
        assert code == 'RJ01509269'
        return payload, []

    service.asmr_resource_service = SimpleNamespace(_get_remote_source_payload=AsyncMock(side_effect=fetch))
    service._sync_download_version_links = Mock()
    service._describe_download_versions = lambda rows: [dict(row, resource_sources=[]) for row in rows]
    rows = await service._discover_download_versions(context, 'RJ01524705', refresh=True)
    assert all(call.kwargs['refresh'] for call in service.asmr_resource_service._get_remote_source_payload.await_args_list)
    available = {row['rjcode'] for row in rows if row['resource_sources']}
    assert available == {'RJ01509269', 'RJ01524706'}
    translated = next(row for row in rows if row['rjcode'] == 'RJ01524706')
    assert translated['language_label'] == '简体中文'
    assert translated['resolved_rjcode'] == 'RJ01524706'
    links = service._sync_download_version_links.call_args.args[1]
    assert any(link['rjcode'] == 'RJ01524706' and link['evidence_source'] == 'asmr.one' for link in links)

    # 完整批量预览也必须保留实际译本，且文件/会话目标仍是各自的精确编号。
    from app.core import library_manager
    monkeypatch.setattr(library_manager, 'get_library_manager', lambda: SimpleNamespace(list_libraries=lambda: []))
    service._download_preview_context = lambda *args: dict(context)
    service._build_filter_skip_reasons = lambda rows: {}

    async def build(*, rjcode, **kwargs):
        return dict(rjcode=rjcode, session_id=rjcode, selectable_resources=[dict(
            relative_path='audio.wav', source_workno=rjcode, selected=True)])

    service.asmr_resource_service.build_download_plan = AsyncMock(side_effect=build)
    result = await service.preview_batch_download('RG68316', ['RJ01509269'],
        {'RJ01509269': ['RJ01524705']}, refresh=True)
    assert {plan['rjcode'] for plan in result['plans']} == available
    assert result['planned_count'] == 2
    for plan in result['plans']:
        assert plan['session_id'] == plan['resolved_rjcode'] == plan['selectable_resources'][0]['source_workno']


@pytest.mark.asyncio
@pytest.mark.parametrize('bonus', [False, True])
async def test_same_original_is_not_requested_twice_and_bonus_never_expands(bonus):
    service = PreviewService()
    context = dict(canonical_rjcode='RJ01509269', title='测试作品', is_bonus_work=bonus)
    service.dlsite_service = SimpleNamespace(get_linked_works=AsyncMock(return_value={}))
    fetch = AsyncMock(return_value=({}, []))
    service.asmr_resource_service = SimpleNamespace(_get_remote_source_payload=fetch)
    service._sync_download_version_links = Mock()
    service._describe_download_versions = lambda rows: [dict(row, resource_sources=[]) for row in rows]
    rows = await service._discover_download_versions(context, 'RJ01509269')
    assert [row['rjcode'] for row in rows] == ['RJ01509269']
    assert fetch.await_count == (0 if bonus else 1)
