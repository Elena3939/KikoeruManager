"""YAAS 精确匹配、分卷、来源选择与任务隔离回归。"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import httpx

from app.core import resource_source_service as module
from app.core.resource_source_service import ResourceSourceService, ROOTS, SOURCE, package_groups, public_path
from app.core.http_download_service import HttpDownloadService
from app.config.settings import HttpDownloaderConfig


def row(name, size=10, parent=None):
    return dict(name=name, size=size, parent=parent or ROOTS[0] + '/05/Original', is_dir=False)


@pytest.mark.parametrize('name', ['RJ1234567.zip', 'XRJ123456.zip', 'RJ123456A.rar',
                                  'RJ123456.txt', 'RJ123456.part00.rar', 'RJ123456.7z.000'])
def test_exact_rj_and_archive_only(name):
    assert package_groups([row(name)], 'RJ123456') == []


@pytest.mark.parametrize('names,complete', [
    (['RJ123456.rar'], True),
    (['RJ123456.part01.rar', 'RJ123456.part02.rar'], True),
    (['RJ123456.part02.rar'], False),
    (['RJ123456.7z.001', 'RJ123456.7z.003'], False),
    (['RJ123456.rar', 'RJ123456.r00', 'RJ123456.r01'], True),
])
def test_package_groups(names, complete):
    rows = [row(name) for name in names]
    groups = package_groups(rows + rows, 'RJ123456')
    assert len(groups) == 1
    assert groups[0]['complete'] is complete
    assert len(groups[0]['files']) == len(names)
    assert groups[0]['size_bytes'] == len(names) * 10


@pytest.mark.parametrize('path', ['/etc/RJ123456.rar', ROOTS[0] + '/../RJ123456.rar', ROOTS[0] + '/x\\RJ123456.rar'])
def test_reject_paths(path):
    with pytest.raises(ValueError):
        public_path(path)


def test_guest_prefix_and_zero_size():
    assert public_path('/guest' + ROOTS[0] + '/RJ123456.zip') == ROOTS[0] + '/RJ123456.zip'
    assert not package_groups([row('RJ123456.zip', 0)], 'RJ123456')[0]['complete']


@pytest.mark.asyncio
async def test_plan_labels_linked_languages_when_requesting_translation(monkeypatch):
    from app.core import dlsite_service, http_download_service
    from app.core.dlsite_service import LinkedWork

    service = ResourceSourceService()
    monkeypatch.setattr(service, 'candidates_for', AsyncMock(return_value=['RJ123456', 'RJ234567', 'RJ345678']))
    monkeypatch.setattr(service, 'probe', AsyncMock(side_effect=lambda code, **kwargs: {
        'candidates': package_groups([row(f'{code}.zip')], code)}))
    linked = {
        'RJ123456': LinkedWork('RJ123456', 'original', 'JPN'),
        'RJ234567': LinkedWork('RJ234567', 'translation', 'CHI_HANS'),
        'RJ345678': LinkedWork('RJ345678', 'translation', 'ENG'),
    }
    monkeypatch.setattr(dlsite_service.get_dlsite_service(), 'get_linked_works', AsyncMock(return_value=linked))
    downloader = http_download_service.get_http_download_service()
    monkeypatch.setattr(downloader, '_download_root', lambda: 'downloads')

    plan = await service.plan('RJ234567')
    resources = plan['selectable_resources']
    assert [item['language_tag'] for item in resources] == ['日文原版', '简体中文', '英文']
    assert [item['work_type'] for item in resources] == ['original', 'translation', 'translation']
    assert all(not item['selected'] for item in resources)


@pytest.mark.asyncio
async def test_combined_plan_requires_explicit_source_without_mutating_asmr(monkeypatch):
    service = ResourceSourceService()
    original = {'selectable_resources': [{'id': 'one', 'selected': True}], 'session_id': 'existing'}
    monkeypatch.setattr(service, 'plan', AsyncMock(return_value={'selectable_resources': [{'id': 'two', 'complete': True}]}))
    result = await service.combine_plan('RJ123456', AsyncMock(return_value=original))
    assert result['source_selection_required']
    assert [p['source_provider'] for p in result['source_options']] == ['asmr.one', SOURCE]
    assert 'source_provider' not in original
    assert result['session_id'] == 'existing'


@pytest.mark.asyncio
async def test_single_source_survives_other_probe_error(monkeypatch):
    service = ResourceSourceService()
    monkeypatch.setattr(service, 'plan', AsyncMock(return_value={'selectable_resources': [{'id': 'two', 'complete': True}]}))
    result = await service.combine_plan('RJ123456', AsyncMock(side_effect=ValueError('不可用')))
    assert not result['source_selection_required']
    assert result['source_provider'] == SOURCE


@pytest.mark.asyncio
async def test_validate_group_rejects_forged_or_multiple_choices(monkeypatch):
    service = ResourceSourceService()
    monkeypatch.setattr(service, 'plan', AsyncMock(return_value={'selectable_resources': [
        {'id': 'valid', 'complete': True}, {'id': 'broken', 'complete': False}]}))
    for selected in [[], ['fake'], ['broken'], ['valid', 'fake']]:
        with pytest.raises(ValueError):
            await service.validate_item({'rjcode': 'RJ123456', 'selected_resources': [{'id': x} for x in selected]})


@pytest.mark.asyncio
async def test_submit_uses_actual_rj_and_no_postprocessing(monkeypatch):
    from app.core import task_engine
    engine = type('Engine', (), {'submit': AsyncMock()})()
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: engine)
    group = package_groups([row('RJ234567.rar')], 'RJ234567')[0]
    await ResourceSourceService().submit({'rjcode': 'RJ123456'}, 'asmr-sync', validated=('RJ123456', group))
    task = engine.submit.call_args.args[0]
    assert task.rjcode == 'RJ234567'
    assert task.task_metadata['requested_rjcode'] == 'RJ123456'
    assert 'postprocess_options' not in task.task_metadata
    assert 'session_id' not in task.task_metadata
    assert task.task_metadata['target_subdir'] == ''
    assert task.task_metadata['archive_password_hint'] == 'south-plus'
    assert '?' not in task.task_metadata['urls'][0]


@pytest.mark.asyncio
async def test_search_lists_directory_and_keeps_old_hits_on_error(monkeypatch):
    service = ResourceSourceService()
    state = {'status': 'pending', 'fresh': False, 'candidates': []}
    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield
    monkeypatch.setattr(service, 'lease', lease)
    monkeypatch.setattr(service, 'cached', lambda code: dict(state))
    def save(code, **values):
        state.update(values, fresh=True)
    monkeypatch.setattr(service, '_save', save)
    async def request(endpoint, payload):
        if endpoint == 'search':
            assert payload['keywords'] == '"RJ123456"'
            return {'content': [row('RJ123456.part01.rar')], 'total': 1}
        return {'content': [row('RJ123456.part01.rar'), row('RJ123456.part02.rar')], 'total': 2}
    monkeypatch.setattr(service, 'request', request)
    result = await service.probe('RJ123456')
    assert len(result['candidates'][0]['files']) == 2
    monkeypatch.setattr(service, 'request', AsyncMock(side_effect=ValueError('429')))
    result = await service.probe('RJ123456', refresh=True)
    assert result['status'] == 'error'
    assert len(result['candidates'][0]['files']) == 2


def test_aria2_limits_and_preserves_original_package_names(monkeypatch, tmp_path):
    service = HttpDownloadService()
    monkeypatch.setattr(service, '_config', lambda: HttpDownloaderConfig())
    item = {'source': SOURCE, 'filename': 'RJ123456.part01.rar', 'custom_name': '别改分卷名'}
    assert service._apply_custom_download_name_to_item(item) is item
    options = service._aria2_options(item, str(tmp_path))
    assert options['split'] == '1'
    assert options['max-connection-per-server'] == '1'
    assert options['max-download-limit'] == '8M'


@pytest.mark.asyncio
@pytest.mark.parametrize('original,expected', [
    ('RJ123456.rar', 'RJ123456【south-plus】.rar'),
    ('RJ123456.part01.rar', 'RJ123456【south-plus】.part01.rar'),
    ('RJ123456.7z.001', 'RJ123456【south-plus】.7z.001'),
])
async def test_yaas_target_uses_http_root_and_configured_password_template(monkeypatch, tmp_path, original, expected):
    from types import SimpleNamespace
    from app.core import http_download_service
    from app.core.task_engine import Task, TaskType
    service = HttpDownloadService()
    monkeypatch.setattr(http_download_service, 'get_config', lambda: SimpleNamespace(
        extract=SimpleNamespace(filename_password_sniff_templates=['{name}【{password}】'])))
    monkeypatch.setattr(service, '_config', lambda: HttpDownloaderConfig())
    monkeypatch.setattr(service, '_download_root', lambda: str(tmp_path))
    monkeypatch.setattr(service, 'validate_url', AsyncMock())
    monkeypatch.setattr(module, 'get_resource_source_service', lambda: SimpleNamespace(
        resolve_file=AsyncMock(return_value={'filename': original, 'size_bytes': 10, 'url': 'https://cdn.imoutoheaven.org/file'})))
    captured = []
    def capture(item, **kwargs):
        captured.append(item)
        raise RuntimeError('目标已验证，停止传输')
    monkeypatch.setattr(service, '_apply_custom_download_name_to_item', capture)
    task = Task(task_type=TaskType.HTTP_DOWNLOAD, source_path='RJ123456', metadata={
        'resource_source': SOURCE, 'urls': ['https://alist-public.imoutoheaven.org/d/file'],
        'yaas_size': 10, 'yaas_path': '/unused', 'target_subdir': 'YAAS/旧任务子目录'})
    with pytest.raises(RuntimeError, match='目标已验证'):
        await service._start_download_task_inner(task)
    assert captured[0]['filename'] == expected
    assert captured[0]['final_path'] == str(tmp_path / expected)
    assert captured[0]['target_dir'] == str(tmp_path)


def test_partial_without_control_file_restarts_and_complete_file_reused(tmp_path):
    service = HttpDownloadService()
    path = tmp_path / 'RJ123456.rar'
    item = {'source': SOURCE, 'final_path': str(path), 'size_bytes': 10}
    path.write_bytes(b'bad')
    assert service._prepare_existing_aria2_target(item) is None
    assert not path.exists()
    path.write_bytes(b'x' * 10)
    assert service._prepare_existing_aria2_target(item)['existing_file_reused']


@pytest.mark.asyncio
async def test_resolve_landing_before_aria2_and_reject_foreign_redirect(monkeypatch):
    from app.core import http_download_service
    service = ResourceSourceService()
    monkeypatch.setattr(service, 'request', AsyncMock(return_value={
        'raw_url': 'https://landing.imoutoheaven.org/file?sign=secret', 'size': 10}))
    monkeypatch.setattr(service, 'pace', AsyncMock())
    downloader = HttpDownloadService()
    monkeypatch.setattr(downloader, 'validate_url', AsyncMock())
    monkeypatch.setattr(downloader, '_proxy_url', lambda *args: '')
    monkeypatch.setattr(http_download_service, 'get_http_download_service', lambda: downloader)
    requests = []
    foreign = False
    def handler(request):
        requests.append(request)
        assert request.headers['range'] == 'bytes=0-0'
        if request.url.host == 'landing.imoutoheaven.org':
            return httpx.Response(302, headers={'location': 'https://evil.example/file' if foreign
                                  else 'https://cdn.imoutoheaven.org/file?sign=secret'})
        return httpx.Response(206, content=b'x')
    client_class = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs:
        client_class(**kwargs, transport=httpx.MockTransport(handler)))
    result = await service.resolve_file(ROOTS[0] + '/RJ123456.rar')
    assert result['url'].startswith('https://cdn.imoutoheaven.org/')
    assert len(requests) == 2
    foreign = True
    requests.clear()
    with pytest.raises(ValueError, match='非预期下载地址'):
        await service.resolve_file(ROOTS[0] + '/RJ123456.rar')
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_broken_packages_are_not_a_download_source(monkeypatch):
    service = ResourceSourceService()
    monkeypatch.setattr(service, 'plan', AsyncMock(return_value={
        'selectable_resources': [{'id': 'broken', 'complete': False}]}))
    with pytest.raises(ValueError, match='没有可下载来源'):
        await service.combine_plan('RJ123456', AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_batch_rejects_unknown_source_before_submission():
    with pytest.raises(ValueError, match='未知下载来源'):
        await ResourceSourceService().validate_batch([
            {'source_provider': 'asmr.one', 'rjcode': 'RJ123456', 'session_id': 'one',
             'selected_resources': [{'id': 'audio'}]},
            {'source_provider': 'forged'},
        ])


def test_page_source_uses_public_codes_and_does_not_change_owned():
    from types import SimpleNamespace
    state = SimpleNamespace(rjcode='RJ234567', status='hit', candidates=[{'complete': True}])
    class Query:
        def filter(self, *args):
            return self
        def all(self):
            return [state]
    db = SimpleNamespace(query=lambda *args: Query())
    item = {'canonical_rjcode': 'RJ123456', 'display_rjcode': 'RJ123456',
            'linked_rjcodes': ['RJ123456', 'RJ234567'], 'resource_probe_rjcodes': ['RJ123456'],
            'owned': False, 'has_asmr_one': False}
    ResourceSourceService().decorate_items(db, [item])
    assert not item['has_downloadable_source']
    item['resource_probe_rjcodes'].append('RJ234567')
    ResourceSourceService().decorate_items(db, [item])
    assert item['resource_sources'][0]['rjcodes'] == ['RJ234567']
    assert not item['owned']


@pytest.mark.asyncio
@pytest.mark.parametrize('actual_size', [None, 3, 10, 11])
async def test_yaas_completion_checks_disk_instead_of_rpc_size(monkeypatch, tmp_path, actual_size):
    service = HttpDownloadService()
    path = tmp_path / 'RJ123456.rar'
    if actual_size is not None:
        path.write_bytes(b'x' * actual_size)
    monkeypatch.setattr(service, '_tell_status', AsyncMock(return_value={
        'gid': 'one', 'status': 'complete', 'totalLength': '10',
        'completedLength': '10', 'downloadSpeed': '0'}))
    rows, _, done, failed = await service._poll_task(['one'], [{
        'gid': 'one', 'source': SOURCE, 'local_path': str(path), 'expected_size_bytes': 10}])
    assert done
    assert failed == (0 if actual_size == 10 else 1)
    assert rows[0]['status'] == ('completed' if actual_size == 10 else 'failed')


@pytest.mark.asyncio
async def test_yaas_poll_error_does_not_persist_signed_url(monkeypatch):
    service = HttpDownloadService()
    monkeypatch.setattr(service, '_tell_status', AsyncMock(side_effect=ValueError(
        '失败 https://cdn.imoutoheaven.org/file?sign=secret')))
    rows, _, _, failed = await service._poll_task(['one'], [{'gid': 'one', 'source': SOURCE}])
    assert failed == 1
    assert 'secret' not in rows[0]['failure_reason']
