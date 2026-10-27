"""YAAS 字幕专区索引、有限下载与临时选择性解压。"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

import httpx

from .resource_source_service import ARCHIVE_PASSWORD, SOURCE, normalize_rj, package_groups
from .ttl_cache import TTLCache

BASE = '/SP后端1[音声分区]'
COLLECTIONS = (
    ('DLSite 官中VTT', False),
    ('风花雪月汉化组音声LRC合集', False),
    ('北极汉化组汉化LRC合集', False),
    ('whisper 3.7 AI汉化 LRC x5099', True),
)
SUBTITLE_LIMIT = 16 * 1024 * 1024
UNPACKED_LIMIT = 64 * 1024 * 1024
EXTENSIONS = {'.lrc', '.vtt', '.srt', '.ass', '.ssa'}
RJ_RE = re.compile(r'(?<![a-z0-9])RJ(?:\d{8}|\d{6})(?![a-z0-9])', re.I)


def is_single_archive(name):
    return (Path(name).suffix.lower() in {'.zip', '.rar', '.7z'}
            and not re.search(r'\.part\d+\.(?:rar|zip|7z)$', name, re.I))


def subtitle_path(path):
    """下载授权与普通音声目录隔离，拒绝合集本体和路径穿越。"""
    path = str(path or '').removeprefix('/guest')
    if '\\' in path or any(part in {'.', '..'} for part in path.split('/')):
        raise ValueError('非法的 YAAS 字幕路径')
    if not any(path.startswith(BASE + '/' + name + '/') for name, _ in COLLECTIONS):
        raise ValueError('不在 YAAS 字幕专区')
    return path


def exact_code(value, code):
    codes = {match.group().upper() for match in RJ_RE.finditer(str(value))}
    return codes == {code}


def audio_archive_files(files, code):
    """重新校验单一音声包及连续分卷，按首卷顺序返回。"""
    if not files or any(not exact_code(row['name'], code) for row in files):
        raise ValueError('关联音声包 RJ 不匹配')
    rows = []
    for row in files:
        path = PurePosixPath(row['path'])
        if path.name != row['name']:
            raise ValueError('关联音声包路径与文件名不匹配')
        rows.append(dict(name=row['name'], parent=str(path.parent), size=row['size']))
    groups = package_groups(rows, code)
    if len(groups) != 1 or not groups[0]['complete'] or len(groups[0]['files']) != len(files):
        raise ValueError('关联音声候选必须是单个完整包或连续分卷组')

    def volume_order(row):
        name = row['name']
        match = re.search(r'\.part(\d+)\.rar$|\.(?:7z|zip)\.(\d{3})$|\.r(\d{2})$', name, re.I)
        if not match:
            return 0
        return int(match.group(1) or match.group(2)) if match.group(3) is None else int(match.group(3)) + 2

    return sorted(files, key=volume_order)


def selected_entries(rows, code, *, subtitle_package):
    """先检查清单，只提取目标作品字幕，不把音声或其它 RJ 写到临时目录。"""
    if not rows or len(rows) > 10000:
        raise ValueError('压缩包清单为空或条目过多')
    selected = []
    total = 0
    for row in rows:
        name = str(row.get('name') or '').replace('\\', '/')
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or any(part in {'.', '..'} for part in name.split('/'))
                or re.search(r'[:\x00-\x1f*?]', name)):
            raise ValueError('压缩包包含不安全的条目路径')
        if row.get('is_symlink') or row.get('is_link'):
            raise ValueError('字幕包包含链接条目')
        codes = {match.group().upper() for match in RJ_RE.finditer(name)}
        if codes and codes != {code}:
            if subtitle_package:
                raise ValueError('字幕包包含其它作品的 RJ')
            continue
        if path.suffix.lower() not in EXTENSIONS:
            continue
        size = int(row.get('size') or 0)
        if size <= 0 or size > 4 * 1024 * 1024:
            raise ValueError('单字幕大小未知或超过 4 MiB')
        total += size
        selected.append(name)
    if not selected:
        raise ValueError('压缩包中没有目标作品的字幕')
    if len(selected) > 500 or total > UNPACKED_LIMIT:
        raise ValueError('字幕解压量超过限制')
    return selected


class YaasSubtitleService:
    def __init__(self):
        self._indexes = TTLCache(max_size=8, ttl_seconds=21600, name='yaas.subtitle.index')
        self._inflight = {}

    async def _index(self, name):
        cached = self._indexes.get(name)
        if cached is not None:
            return cached
        if name in self._inflight:
            return await asyncio.shield(self._inflight[name])

        async def load():
            from .redis_service import get_redis_service
            from .resource_source_service import get_resource_source_service
            redis = get_redis_service()
            key = 'index-v1:' + name
            cached = await asyncio.to_thread(redis.get_json, 'yaas-subtitle', 'index', key)
            if isinstance(cached, list):
                self._indexes[name] = cached
                return cached
            service = get_resource_source_service()
            pending = [BASE + '/' + name]
            rows = []
            visited = set()
            while pending:
                parent = pending.pop(0)
                if parent in visited:
                    continue
                visited.add(parent)
                if len(visited) > 64:
                    raise ValueError('字幕目录层数或数量异常')
                for page in range(1, 31):
                    data = await service.request('list', dict(
                        path=parent, page=page, per_page=1000, password='', refresh=False))
                    content = data.get('content')
                    if not isinstance(content, list):
                        raise ValueError('字幕目录返回不完整')
                    for row in content:
                        child_name = str(row.get('name') or '')
                        if not child_name or '/' in child_name or '\\' in child_name:
                            raise ValueError('字幕目录返回非法文件名')
                        path = subtitle_path(parent + '/' + child_name)
                        if row.get('is_dir'):
                            pending.append(path)
                        elif (is_single_archive(child_name)
                              and 0 < int(row.get('size') or 0) <= SUBTITLE_LIMIT):
                            rows.append({'name': child_name, 'path': path, 'size': int(row['size'])})
                    if len(content) < 1000 or (
                            data.get('total') is not None and page * 1000 >= int(data['total'])):
                        break
                else:
                    raise ValueError('字幕目录分页超过限制')
            await asyncio.to_thread(redis.set_json, 'yaas-subtitle', 'index', key, rows, ttl_seconds=21600)
            self._indexes[name] = rows
            return rows

        task = asyncio.create_task(load())
        self._inflight[name] = task
        def finished(done):
            self._inflight.pop(name, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def sources(self, original_codes):
        """缓存目录而非每个 RJ 全站搜索；失败目录不缓存为无字幕。"""
        codes = list(dict.fromkeys(normalize_rj(code) for code in original_codes))
        sources, attempts = [], []
        for name, is_ai in COLLECTIONS:
            try:
                rows = await self._index(name)
                hits = [row for row in rows if any(exact_code(row['name'], code) for code in codes)]
                attempts.append(dict(source='yaas', collection=name, subtitle_count=len(hits)))
                for code in codes:
                    for row in sorted(hits, key=lambda item: (item['size'], item['path'])):
                        if exact_code(row['name'], code):
                            sources.append(dict(
                                rjcode=code, lang='CHI_HANS', work_type='original',
                                title=name, source_provider='yaas', subtitle_is_ai=is_ai,
                                subtitle_files=[], archive_files=[row], subtitle_package=True,
                            ))
            except Exception:
                attempts.append(dict(source='yaas', collection=name, subtitle_count=0,
                                     reason='YAAS 字幕目录暂不可访问'))
        return sources, attempts

    async def audio_sources(self, works):
        from .resource_source_service import get_resource_source_service
        results = []
        service = get_resource_source_service()
        for work in works:
            if getattr(work, 'lang', '') not in {'CHI_HANS', 'CHI_SIMP', 'CHI_HANT', 'CHI_TRAD'}:
                continue
            state = await service.probe(work.workno)
            if state.get('status') == 'error':
                raise ValueError('YAAS 关联中文音声查询失败')
            for group in state.get('candidates') or []:
                if not group.get('complete'):
                    continue
                try:
                    files = audio_archive_files([
                        dict(path=f['path'], name=f['name'], size=f['size_bytes'])
                        for f in group.get('files') or []
                    ], work.workno)
                except ValueError:
                    continue
                is_mp3 = bool(re.search(r'(?<![a-z0-9])mp3(?![a-z0-9])',
                                        files[0]['name'], re.I))
                results.append(dict(
                    rjcode=work.workno, lang=work.lang, work_type=work.work_type,
                    title=f"YAAS 关联中文音声 · {'MP3 分流' if is_mp3 else '原档'}",
                    audio_variant='mp3' if is_mp3 else 'original',
                    source_provider='yaas', subtitle_is_ai=False,
                    subtitle_files=[], subtitle_package=False,
                    archive_files=files,
                ))
        # 跨简繁版本统一排序，避免先遇到的作品原档抢在另一版本 MP3 前。
        results.sort(key=lambda item: (
            item['audio_variant'] != 'mp3',
            sum(row['size'] for row in item['archive_files']),
            item['archive_files'][0]['path'],
        ))
        return results

    async def _download(self, row, directory, *, subtitle_package, should_cancel):
        from .http_download_service import get_http_download_service
        from .resource_source_service import get_resource_source_service
        service = get_resource_source_service()
        downloader = get_http_download_service()
        expected = int(row['size'])
        if expected <= 0 or (subtitle_package and expected > SUBTITLE_LIMIT):
            raise ValueError('YAAS 包体积超过限制或大小未知')
        resolved = await service.resolve_file(row['path'], subtitle_only=subtitle_package)
        if int(resolved['size_bytes']) != expected:
            raise ValueError('YAAS 资源大小已变化，请刷新索引')
        stem, ext = downloader._split_custom_archive_filename(row['name'])
        filename = downloader._filename_with_extract_password(stem, ARCHIVE_PASSWORD, ext)
        target = os.path.join(directory, filename)
        received = 0
        async with service.lease('subtitle-download', slots=2):
            async with httpx.AsyncClient(timeout=60, follow_redirects=False,
                                        proxy=downloader._proxy_url(SOURCE) or None) as client:
                async with client.stream('GET', resolved['url']) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if should_cancel and should_cancel():
                            raise asyncio.CancelledError()
                        received += len(chunk)
                        if received > expected:
                            raise ValueError('YAAS 实际传输量超过限制')
                        # 每次打开追加，避免阻塞事件循环的整个网络下载。
                        await asyncio.to_thread(self._append_chunk, target, chunk)
        if received != expected:
            raise ValueError('YAAS 下载不完整')
        return target

    @staticmethod
    def _append_chunk(path, chunk):
        with open(path, 'ab') as stream:
            stream.write(chunk)

    async def materialize(self, source, temp_dir, *, task_id='', should_cancel=None, progress_callback=None):
        """复用解压任务和 7zz 清单/密码/并发控制；仅发布字幕到既有补配流程。"""
        from .extract_service import ExtractService
        from .task_engine import Task, TaskType, get_task_engine
        stage = tempfile.mkdtemp(prefix='yaas_', dir=temp_dir)
        published = Path(temp_dir) / (Path(stage).name + '_files')
        engine = get_task_engine()
        child = None
        try:
            files = source['archive_files']
            if source['subtitle_package']:
                if len(files) != 1 or not is_single_archive(files[0]['name']):
                    raise ValueError('字幕候选必须是单个完整压缩包')
            else:
                files = audio_archive_files(files, source['rjcode'])
            archives = []
            for index, row in enumerate(files):
                if should_cancel and should_cancel():
                    raise asyncio.CancelledError()
                if progress_callback:
                    progress_callback(28, f"下载 YAAS 候选 {index + 1}/{len(files)} {row['name']}")
                archives.append(await self._download(
                    row, stage, subtitle_package=source['subtitle_package'],
                    should_cancel=should_cancel))
            archive = archives[0]
            child = Task(TaskType.RJ_SUBTITLE_EXTRACT, archive, metadata={
                'parent_task_id': task_id, 'rjcode': source['rjcode'],
                'source_label': '字幕爬取临时解压', 'source_provider': 'yaas',
                'subtitle_is_ai': source['subtitle_is_ai'],
                'manual_retry_passwords': [ARCHIVE_PASSWORD], 'manual_retry_password_only': True,
            })
            child.rjcode = source['rjcode']
            engine._ensure_task_context(child)
            engine.tasks[child.id] = child
            child.mark_changed('submitted')
            child.start()
            await asyncio.to_thread(engine.persist_task_snapshot, child)
            extractor = ExtractService()
            async def monitored(operation):
                running = asyncio.create_task(operation)
                try:
                    while not running.done():
                        if child.is_cancelled() or (should_cancel and should_cancel()):
                            child.cancel()
                            running.cancel()
                            raise asyncio.CancelledError()
                        await asyncio.wait({running}, timeout=.2)
                    result = await running
                    if child.is_cancelled() or (should_cancel and should_cancel()):
                        raise asyncio.CancelledError()
                    return result
                finally:
                    if not running.done():
                        child.cancel()
                        running.cancel()
                    await asyncio.gather(running, return_exceptions=True)

            # 技术清单保留链接属性，在真正写入前拒绝链接和路径穿越。
            async def inspect():
                result = await extractor._run_7z_command(
                    [extractor.seven_zip, 'l', '-slt', '-sccUTF-8', *extractor._get_mcp_args(archive),
                     f'-p{ARCHIVE_PASSWORD}', archive],
                    task=child, command_timeout=60)
                if result.returncode:
                    raise ValueError('YAAS 压缩包清单读取失败')
                decoded, _ = extractor._decode_7z_stdout(result.stdout)
                return extractor._parse_7z_technical_output(decoded)

            rows = await monitored(inspect())
            entries = selected_entries(rows, source['rjcode'], subtitle_package=source['subtitle_package'])
            output = os.path.join(stage, 'extracted')
            child.update_progress(25, f'选择性提取 {len(entries)} 个字幕')
            await monitored(extractor.extract_selected_entries(
                archive, entries, output, task=child, preferred_passwords=[ARCHIVE_PASSWORD]))
            files = []
            for index, entry in enumerate(entries):
                path = Path(output).joinpath(*PurePosixPath(entry).parts)
                if not path.is_file() or path.is_symlink() or Path(output).resolve() not in path.resolve().parents:
                    raise ValueError('解压结果不完整或包含链接')
                if not 0 < path.stat().st_size <= 4 * 1024 * 1024:
                    raise ValueError('解压后字幕大小异常')
                if child.is_cancelled() or (should_cancel and should_cancel()):
                    raise asyncio.CancelledError()
                relative = f'{published.name}/{index:04d}/{path.name}'
                target = Path(temp_dir).joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copyfile, path, target)
                files.append(dict(name=path.name, relative_path=relative, path=str(target),
                                  local_subtitle_path=str(target), source_provider='yaas',
                                  subtitle_is_ai=source['subtitle_is_ai']))
            child.update_progress(100, f'已提取 {len(files)} 个字幕')
            child.complete()
            return {**source, 'subtitle_files': files}
        except asyncio.CancelledError:
            await asyncio.to_thread(shutil.rmtree, published, True)
            if child:
                child.cancel()
            raise
        except Exception as exc:
            await asyncio.to_thread(shutil.rmtree, published, True)
            if child:
                child.fail(str(exc))
            raise
        finally:
            try:
                if child:
                    await asyncio.to_thread(engine.persist_task_snapshot, child)
                    await engine._notify_progress(child)
            finally:
                await asyncio.to_thread(shutil.rmtree, stage, True)


_service = None


def get_yaas_subtitle_service():
    global _service
    if _service is None:
        _service = YaasSubtitleService()
    return _service
