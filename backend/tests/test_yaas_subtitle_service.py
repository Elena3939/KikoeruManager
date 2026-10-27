"""YAAS 字幕候选边界、缓存和 AI 目录回归。"""
import asyncio
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

from app.core import resource_source_service as resources
from app.core import redis_service
from app.core import http_download_service
from app.core import yaas_subtitle_service as yaas
from app.core.rj_subtitle_service import RJSubtitleService
from app.core import task_engine
from app.core.extract_service import ArchiveInfo, ExtractService
from app.config import settings


@pytest.mark.parametrize('name,expected', [
    ('RJ123456.zip', True), ('RJ1234567.zip', False),
    ('RJ12345678.zip', False), ('RJ123456-RJ234567.zip', False),
    ('xRJ123456.zip', False), ('字幕-RJ123456.zip', True),
])
def test_exact_rj(name, expected):
    assert yaas.exact_code(name, 'RJ123456') is expected


def test_path_authorization_separates_subtitle_and_audio():
    path = yaas.BASE + '/' + yaas.COLLECTIONS[0][0] + '/RJ123456.zip'
    assert yaas.subtitle_path('/guest' + path) == path
    with pytest.raises(ValueError):
        resources.public_path(path)
    for invalid in (path + '/../x.zip', path.replace('/RJ', '\\RJ'), yaas.BASE + '/other/RJ123456.zip'):
        with pytest.raises(ValueError):
            yaas.subtitle_path(invalid)


@pytest.mark.parametrize('entry', [
    {'name': '../01.lrc', 'size': 20},
    {'name': '/01.lrc', 'size': 20},
    {'name': 'C:/01.lrc', 'size': 20},
    {'name': '01.lrc', 'size': 20, 'is_link': True},
    {'name': '01.lrc', 'size': 0},
    {'name': '01.lrc', 'size': 5 * 1024 * 1024},
    {'name': 'RJ234567/01.lrc', 'size': 20},
    {'name': 'audio.wav', 'size': 20},
])
def test_rejects_invalid_archive_entries(entry):
    with pytest.raises(ValueError):
        yaas.selected_entries([entry], 'RJ123456', subtitle_package=True)


def test_audio_archive_only_selects_subtitles_of_target():
    entries = [
        {'name': 'RJ123456/01.lrc', 'size': 20},
        {'name': 'RJ123456/01.wav', 'size': 10000000},
        {'name': 'RJ234567/01.lrc', 'size': 20},
    ]
    assert yaas.selected_entries(entries, 'RJ123456', subtitle_package=False) == ['RJ123456/01.lrc']


@pytest.mark.asyncio
async def test_index_singleflight_cache_and_archive_limits(monkeypatch):
    calls = []

    async def request(endpoint, payload):
        calls.append(payload['path'])
        await asyncio.sleep(.01)
        return {'content': [
            {'name': 'RJ123456.zip', 'size': 100},
            {'name': 'RJ234567.zip', 'size': yaas.SUBTITLE_LIMIT + 1},
            {'name': 'RJ345678.zip', 'size': 0},
            {'name': 'RJ456789.part1.rar', 'size': 100},
            {'name': '合集.rar', 'size': 1024 ** 3},
        ], 'total': 5}

    monkeypatch.setattr(resources, 'get_resource_source_service', lambda: SimpleNamespace(request=request))
    monkeypatch.setattr(redis_service, 'get_redis_service', lambda: SimpleNamespace(
        get_json=lambda *_: None, set_json=lambda *_, **__: True))
    service = yaas.YaasSubtitleService()
    name = yaas.COLLECTIONS[0][0]
    first, second = await asyncio.gather(service._index(name), service._index(name))
    assert first == second
    assert [item['name'] for item in first] == ['RJ123456.zip']
    assert await service._index(name) == first
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_index_is_not_cached(monkeypatch):
    request = AsyncMock(side_effect=ValueError('暂不可访问'))
    monkeypatch.setattr(resources, 'get_resource_source_service', lambda: SimpleNamespace(request=request))
    monkeypatch.setattr(redis_service, 'get_redis_service', lambda: SimpleNamespace(get_json=lambda *_: None))
    service = yaas.YaasSubtitleService()
    for _ in range(2):
        with pytest.raises(ValueError):
            await service._index(yaas.COLLECTIONS[0][0])
    assert request.await_count == 2


@pytest.mark.asyncio
async def test_audio_fallback_large_archives_and_global_mp3_priority(monkeypatch):
    def groups(code):
        rows = [
            ('原档.zip', 5 * 1024 ** 3), ('[MP3].7z.002', 400 * 1024 ** 2),
            ('[MP3].7z.001', 400 * 1024 ** 2), ('_mp3.zip', 900 * 1024 ** 2),
            ('-缺卷.part2.rar', 100), ('-未知.zip', 0), ('-notmp3.zip', 1024),
            ('-RJ345678.zip', 100),
        ]
        return resources.package_groups([
            dict(name=code + name, parent=resources.ROOTS[0], size=size)
            for name, size in rows
        ], code)
    probe = AsyncMock(side_effect=lambda code: {'candidates': groups(code)})
    monkeypatch.setattr(resources, 'get_resource_source_service', lambda: SimpleNamespace(probe=probe))
    works = [SimpleNamespace(workno=code, lang=lang, work_type='translation')
             for code, lang in [('RJ234567', 'ENG'), ('RJ234567', 'JPN'),
                                ('RJ234567', 'CHI_HANT'), ('RJ456789', 'CHI_HANS')]]
    result = await yaas.YaasSubtitleService().audio_sources(works)
    assert len(result) == 8
    assert [item['audio_variant'] for item in result] == ['mp3'] * 4 + ['original'] * 4
    assert sum(f['size'] for f in result[-1]['archive_files']) == 5 * 1024 ** 3
    assert result[0]['archive_files'][0]['name'].endswith('.7z.001')
    assert len(result[0]['archive_files']) == 2
    assert probe.await_count == 2


@pytest.mark.parametrize('suffixes,expected', [
    (['.part10.rar', '.part1.rar'] + [f'.part{i}.rar' for i in range(2, 10)], '.part1.rar'),
    (['.r01', '.r00', '.rar'], '.rar'),
    (['.7z.002', '.7z.001'], '.7z.001'),
    (['.zip.002', '.zip.001'], '.zip.001'),
])
def test_audio_volume_first_archive(suffixes, expected):
    files = [dict(name='RJ123456' + suffix, size=100,
                  path=resources.ROOTS[0] + '/RJ123456' + suffix) for suffix in suffixes]
    assert yaas.audio_archive_files(files, 'RJ123456')[0]['name'] == 'RJ123456' + expected


@pytest.mark.parametrize('suffixes', [
    ['.7z.002'], ['.part1.rar', '.part3.rar'], ['.r00'],
    ['.zip', '-other.zip'], ['.7z.001', '.7z.001'],
])
def test_audio_rejects_incomplete_or_mixed_groups(suffixes):
    files = [dict(name='RJ123456' + suffix, size=100,
                  path=resources.ROOTS[0] + '/RJ123456' + suffix) for suffix in suffixes]
    with pytest.raises(ValueError):
        yaas.audio_archive_files(files, 'RJ123456')


@pytest.mark.parametrize('is_ai,directory', [(False, 'subtitles'), (True, 'subtitles [AI]')])
def test_local_subtitle_directory_and_file_names(tmp_path, is_ai, directory):
    service = RJSubtitleService.__new__(RJSubtitleService)
    source = tmp_path / 'track01.lrc'
    source.write_text('[00:01.00]测试\n', encoding='utf-8')
    folder = tmp_path / 'RJ123456'
    folder.mkdir()
    result, written, _, errors = service._write_local_downloaded_subtitles(
        folder, [{'name': source.name, 'path': str(source), 'subtitle_is_ai': is_ai}], False)
    assert result == str(folder / directory)
    assert not errors
    assert (folder / directory / 'track01.lrc').is_file()
    assert service._count_existing_subtitles(folder) == 1
    assert service._is_remote_subtitles_relative_path(directory + '/track01.lrc')


@pytest.mark.asyncio
async def test_remote_ai_directory(monkeypatch):
    service = RJSubtitleService.__new__(RJSubtitleService)
    client = SimpleNamespace(stat=AsyncMock(side_effect=[{'path': '/works/RJ123456'},
                                                         RuntimeError('missing')]),
                             create_folder=AsyncMock())
    monkeypatch.setattr(service, '_is_synology_error_codes', lambda *_: True)
    result = await service._ensure_remote_subtitle_dir(client, '/works/RJ123456', is_ai=True)
    assert result == '/works/RJ123456/subtitles [AI]'
    client.create_folder.assert_awaited_once_with('/works/RJ123456', 'subtitles [AI]')


@pytest.mark.asyncio
async def test_mixed_asmr_source_keeps_human_subtitles_separate(monkeypatch):
    service = RJSubtitleService.__new__(RJSubtitleService)
    service.asmr_service = SimpleNamespace(
        fetch_work_info=AsyncMock(return_value={'title': '测试'}),
        fetch_track_list=AsyncMock(return_value=[]),
        _flatten_tracks=lambda _: [],
    )
    work = SimpleNamespace(workno='RJ123456', lang='CHI_HANS', work_type='original')
    monkeypatch.setattr(service, '_build_work_search_order_from_work_info', lambda *_: [work])
    monkeypatch.setattr(service, '_collect_subtitle_candidates', lambda *_: [
        {'relative_path': '人工/01.lrc'}, {'relative_path': 'Whisper/01.lrc'}])
    result, _ = await service.find_best_subtitle_source('RJ123456')
    assert result['subtitle_is_ai'] is False
    assert result['subtitle_files'] == [{'relative_path': '人工/01.lrc'}]


@pytest.mark.asyncio
async def test_yaas_only_uses_original_rj(monkeypatch):
    service = RJSubtitleService.__new__(RJSubtitleService)
    service.asmr_service = SimpleNamespace(
        fetch_work_info=AsyncMock(return_value={'title': '测试'}),
        fetch_track_list=AsyncMock(return_value=[]),
        _flatten_tracks=lambda _: [],
    )
    works = [SimpleNamespace(workno='RJ234567', lang='CHI_HANT', work_type='translation'),
             SimpleNamespace(workno='RJ123456', lang='JPN', work_type='original')]
    monkeypatch.setattr(service, '_build_work_search_order_from_work_info', lambda *_: works)
    lookup = AsyncMock(return_value=([{
        'rjcode': 'RJ123456', 'subtitle_is_ai': False, 'subtitle_files': [],
        'archive_files': [{'name': 'RJ123456.zip'}],
    }], []))
    monkeypatch.setattr(yaas, 'get_yaas_subtitle_service', lambda: SimpleNamespace(sources=lookup))
    result, _ = await service.find_best_subtitle_source('RJ234567')
    lookup.assert_awaited_once_with(['RJ123456'])
    assert result['deferred_audio_works'] == [
        {'workno': 'RJ234567', 'lang': 'CHI_HANT', 'work_type': 'translation'}]


@pytest.mark.asyncio
async def test_subtitle_packages_are_attempted_before_chinese_audio(monkeypatch, tmp_path):
    calls = []

    async def materialize(source, *_args, **_kwargs):
        calls.append(source['title'])
        if source['title'] == '人工字幕':
            raise ValueError('损坏')
        return {**source, 'subtitle_files': [{'name': '01.lrc'}]}

    audio = AsyncMock()
    monkeypatch.setattr(yaas, 'get_yaas_subtitle_service', lambda: SimpleNamespace(
        materialize=materialize, audio_sources=audio))
    source = dict(title='人工字幕', rjcode='RJ123456', archive_files=[{}],
                  fallback_sources=[dict(title='AI字幕', rjcode='RJ123456', archive_files=[{}])],
                  deferred_audio_works=[dict(workno='RJ234567', lang='CHI_HANS', work_type='translation')])
    attempts = []
    result = await RJSubtitleService.__new__(RJSubtitleService)._prepare_fetch_source(
        source, attempts, str(tmp_path), task_id='', should_cancel=None, progress_callback=None)
    assert calls == ['人工字幕', 'AI字幕']
    assert result['title'] == 'AI字幕'
    audio.assert_not_awaited()
    assert attempts[0]['reason'] == '损坏'


@pytest.mark.asyncio
async def test_audio_fallback_reaches_original_after_multiple_mp3_failures(monkeypatch, tmp_path):
    options = [dict(title=title, rjcode='RJ234567')
               for title in ('MP3-1', 'MP3-2', 'MP3-3', '原档')]
    calls = []

    async def materialize(source, *_args, **_kwargs):
        calls.append(source['title'])
        if source['title'] != '原档':
            raise ValueError('包中无字幕')
        return {**source, 'subtitle_files': [{'name': '01.lrc'}]}

    monkeypatch.setattr(yaas, 'get_yaas_subtitle_service', lambda: SimpleNamespace(
        materialize=materialize, audio_sources=AsyncMock(return_value=options)))
    source = dict(deferred_audio_works=[
        dict(workno='RJ234567', lang='CHI_HANT', work_type='translation')])
    attempts = []
    result = await RJSubtitleService.__new__(RJSubtitleService)._prepare_fetch_source(
        source, attempts, str(tmp_path), task_id='', should_cancel=None, progress_callback=None)
    assert calls == ['MP3-1', 'MP3-2', 'MP3-3', '原档']
    assert result['title'] == '原档'
    assert len(attempts) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('multipart', [False, True])
async def test_materialize_real_zip_selective_extraction_and_cleanup(monkeypatch, tmp_path, cancel, multipart):
    executable = shutil.which('7zz') or shutil.which('7z')
    if not executable:
        pytest.skip('需要本机 7zz/7z')
    origin = tmp_path / 'source.zip'
    with zipfile.ZipFile(origin, 'w') as archive:
        archive.writestr('字幕/01.lrc', '[00:01.00]测试\n')
        archive.writestr('audio.wav', b'audio-must-not-be-extracted')
    volumes = [origin]
    if multipart:
        contents = tmp_path / 'contents'
        contents.mkdir()
        (contents / '01.lrc').write_text('[00:01.00]测试\n', encoding='utf-8')
        (contents / 'audio.wav').write_bytes(os.urandom(4096))
        archive_path = tmp_path / 'RJ123456[MP3].7z'
        subprocess.run([executable, 'a', '-v256b', '-psouth-plus', '-mhe=on',
                        str(archive_path), str(contents / '*')], check=True, capture_output=True)
        volumes = sorted(tmp_path.glob('RJ123456[[]MP3].7z.*'))
        assert len(volumes) > 10
    engine = SimpleNamespace(tasks={}, _ensure_task_context=lambda _: None,
                             persist_task_snapshot=lambda _: None, _notify_progress=AsyncMock())
    monkeypatch.setattr(task_engine, 'get_task_engine', lambda: engine)
    monkeypatch.setattr(task_engine.Task, '_global_event_hook', None)
    monkeypatch.setattr(ExtractService, 'seven_zip', property(lambda _: executable))
    monkeypatch.setattr(ExtractService, '_get_mcp_args', lambda *_: [])
    monkeypatch.setattr(ExtractService, '_get_seven_zip_mmt_args', lambda _: [])
    monkeypatch.setattr(ExtractService, '_ensure_7z_available', AsyncMock(return_value=True))
    monkeypatch.setattr(ExtractService, '_get_archive_info', AsyncMock(
        side_effect=lambda path, **_: ArchiveInfo(path, [])))
    monkeypatch.setattr(ExtractService, '_get_password_candidates_for_archive', AsyncMock(return_value=[]))
    monkeypatch.setattr(ExtractService, '_get_rj_passwords', lambda *_: [])
    monkeypatch.setattr(ExtractService, 'config', property(lambda _: SimpleNamespace(
        extract=SimpleNamespace(password_list=[]))))
    commands = []
    cancelled = False

    async def run(_self, command, **_kwargs):
        nonlocal cancelled
        commands.append(command)
        if cancel:
            cancelled = True
            await asyncio.Event().wait()
        return await asyncio.to_thread(subprocess.run, command, capture_output=True, timeout=15)

    monkeypatch.setattr(ExtractService, '_run_7z_command', run)
    service = yaas.YaasSubtitleService()

    downloads = []

    async def download(row, directory, **_kwargs):
        volume = next(item for item in volumes if item.name == row['name'])
        downloader = http_download_service.HttpDownloadService.__new__(
            http_download_service.HttpDownloadService)
        stem, ext = downloader._split_custom_archive_filename(row['name'])
        target = Path(directory) / downloader._filename_with_extract_password(stem, 'south-plus', ext)
        shutil.copyfile(volume, target)
        downloads.append(row['name'])
        return str(target)

    monkeypatch.setattr(service, '_download', download)
    source = dict(rjcode='RJ123456', source_provider='yaas', subtitle_is_ai=True,
                  subtitle_package=not multipart, archive_files=[
                      dict(name=volume.name, path=resources.ROOTS[0] + '/' + volume.name,
                           size=volume.stat().st_size) for volume in reversed(volumes)])
    staging = tmp_path / 'staging'
    staging.mkdir()
    operation = service.materialize(source, str(staging), task_id='parent',
                                    should_cancel=lambda: cancelled)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 10)
        assert not list(staging.iterdir())
    else:
        result = await asyncio.wait_for(operation, 20)
        assert len(result['subtitle_files']) == 1
        item = result['subtitle_files'][0]
        assert Path(item['local_subtitle_path']).read_text(encoding='utf-8') == '[00:01.00]测试\n'
        assert item['subtitle_is_ai'] is True
        assert not list(staging.rglob('audio.wav'))
        assert not list(staging.rglob('*.zip'))
        assert any(command[1] == 'x' for command in commands)
    assert len(downloads) == len(volumes)
    if multipart:
        assert downloads[0].endswith('.001')
        assert not list(staging.rglob('*.7z.*'))
    child, = engine.tasks.values()
    assert child.type == task_engine.TaskType.RJ_SUBTITLE_EXTRACT
    assert child.task_metadata['parent_task_id'] == 'parent'
    assert child.status.value == ('cancelled' if cancel else 'completed')
    assert engine._notify_progress.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('subtitle_package', [True, False])
@pytest.mark.parametrize('expected,body,cancel,error', [
    (3, b'abcd', False, ValueError),
    (4, b'abc', False, ValueError),
    (3, b'abc', True, asyncio.CancelledError),
    (3, b'abc', False, None),
    (5 * 1024 ** 3, b'abc', False, ValueError),
])
async def test_download_stream_enforces_size_and_cancellation(
        monkeypatch, tmp_path, expected, body, cancel, error, subtitle_package):
    @asynccontextmanager
    async def lease(*_args, **_kwargs):
        yield

    resolve = AsyncMock(return_value={'size_bytes': expected, 'url': 'https://test.invalid/file'})
    monkeypatch.setattr(resources, 'get_resource_source_service', lambda: SimpleNamespace(
        resolve_file=resolve, lease=lease))
    monkeypatch.setattr(http_download_service, 'get_http_download_service', lambda: SimpleNamespace(
        _split_custom_archive_filename=lambda name: (Path(name).stem, '.zip'),
        _filename_with_extract_password=lambda stem, password, ext: stem + '.' + password + ext,
        _proxy_url=lambda _: None))
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    monkeypatch.setattr(yaas.httpx, 'AsyncClient',
                        lambda **kwargs: client_type(transport=transport, **kwargs))
    row = {'name': 'RJ123456.zip', 'path': '/test', 'size': expected}
    operation = yaas.YaasSubtitleService()._download(
        row, str(tmp_path), subtitle_package=subtitle_package, should_cancel=lambda: cancel)
    if error:
        message = '下载不完整' if expected > yaas.SUBTITLE_LIMIT and not subtitle_package else None
        with pytest.raises(error, match=message):
            await operation
    else:
        target = Path(await operation)
        assert target.read_bytes() == body
        assert 'south-plus' in target.name
    if subtitle_package and expected > yaas.SUBTITLE_LIMIT:
        resolve.assert_not_awaited()
    else:
        resolve.assert_awaited_once_with('/test', subtitle_only=subtitle_package)


@pytest.mark.asyncio
async def test_process_local_yaas_ai_subtitles_uses_existing_pipeline(monkeypatch, tmp_path):
    folder = tmp_path / 'RJ123456'
    folder.mkdir()
    (folder / '01.wav').write_bytes(b'audio')
    config = SimpleNamespace(
        storage=SimpleNamespace(temp_path=str(tmp_path / 'temp')),
        rj_subtitle=SimpleNamespace(overwrite_existing=False, enable_metadata_match=False,
                                   naming_strategy='audio', use_filter_rules=False),
        asmr_sync=SimpleNamespace(lrc_clean_enabled=False, simplify_chinese_enabled=False),
        file_move=settings.FileMoveConfig(),
    )
    monkeypatch.setattr(settings, 'get_config', lambda: config)
    service = RJSubtitleService()
    source = dict(rjcode='RJ123456', source_provider='yaas', lang='CHI_HANS',
                  work_type='original', title='whisper AI', subtitle_is_ai=True,
                  subtitle_files=[], archive_files=[{'name': 'RJ123456.zip'}])
    monkeypatch.setattr(service, 'find_best_subtitle_source', AsyncMock(return_value=(source, [])))
    monkeypatch.setattr(service, '_maybe_apply_ai_auto_match', AsyncMock(return_value={}))

    async def materialize(source, temp_dir, **_kwargs):
        target = Path(temp_dir) / 'package' / '01.lrc'
        target.parent.mkdir()
        target.write_text('[00:01.00]测试\n', encoding='utf-8')
        return {**source, 'subtitle_files': [
            {'name': '01.lrc', 'relative_path': 'package/01.lrc',
             'local_subtitle_path': str(target), 'subtitle_is_ai': True}]}

    monkeypatch.setattr(yaas, 'get_yaas_subtitle_service',
                        lambda: SimpleNamespace(materialize=materialize))
    result = await service.process_folder(str(folder))
    assert result['success'] is True, (result.get('error'), result.get('write_errors'))
    assert result['subtitle_is_ai'] is True
    assert result['source_provider'] == 'yaas'
    assert result['subtitle_dir'] == str(folder / 'subtitles [AI]')
    assert (folder / 'subtitles [AI]' / '01.lrc').read_text(encoding='utf-8') == '[00:01.00]测试\n'
    assert not list((tmp_path / 'temp' / 'rj_subtitle_fetch').iterdir())
