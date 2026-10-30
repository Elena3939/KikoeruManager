"""社团补全与增强下载共用的 YAAS 包来源、缓存和调度。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import hashlib
import os
import posixpath
import re
import uuid
import time
import logging
import threading
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlsplit

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import cast

from ..models.database import ResourceSourceProbe, SessionLocal
from .redis_service import get_redis_service
from .release_dates import is_unreleased

SOURCE = 'imoutoheaven'
ARCHIVE_PASSWORD = 'south-plus'
BASE_URL = 'https://alist-public.imoutoheaven.org'
ROOTS = tuple('/SP后端1[音声分区]/' + name for name in (
    'DLSite归档合集-离散', 'DLSite月份合集-离散',
))
VERSION = 1


class ResourceSourceError(ValueError):
    """保留 YAAS 失败阶段和源站原因，避免任务层误报为传输异常。"""


def normalize_rj(value):
    value = str(value or '').strip().upper()
    if not re.fullmatch(r'RJ\d{6,8}', value):
        raise ValueError('无效的 RJ 号')
    return value


def public_path(value):
    value = str(value or '')
    if value.startswith('/guest/'):
        value = value[6:]
    if '\\' in value or any(part in {'.', '..'} for part in value.split('/')):
        raise ValueError('非法的 YAAS 资源路径')
    if not any(value.startswith(root + '/') for root in ROOTS):
        raise ValueError('仅支持 DLSite 音声离散区')
    return value


def package_groups(rows, rjcode):
    """精确 RJ，候选包互斥，分卷组不可拆开提交。"""
    groups = {}
    for row in rows:
        name = str(row.get('name') or '')
        if row.get('is_dir') or not re.search(rf'(?<![A-Z0-9]){re.escape(rjcode)}(?![A-Z0-9])', name, re.I):
            continue
        match = re.search(r'(?i)\.part(\d+)\.rar$|\.(7z|zip)\.(\d{3})$|\.r(\d{2})$|\.rar$', name)
        if not match and not re.search(r'(?i)\.(zip|7z)$', name):
            continue
        try:
            path = public_path(str(row.get('parent') or '').rstrip('/') + '/' + name)
        except ValueError:
            continue
        number = int(match.group(1) or match.group(3) or 0) if match else 0
        if match and (match.group(1) is not None or match.group(3) is not None) and number == 0:
            continue
        classic = bool(match and match.group(4) is not None) or (
            name.lower().endswith('.rar') and not number and any(
                str(other.get('parent')) == str(row.get('parent')) and
                re.fullmatch(re.escape(name[:-4]) + r'\.r\d{2}', str(other.get('name') or ''), re.I)
                for other in rows))
        if classic:
            number = int(match.group(4)) + 2 if match.group(4) is not None else 1
        stem = (re.sub(r'(?i)\.(rar|r\d{2})$', '', path) if classic else
                re.sub(r'(?i)\.part\d+\.rar$|\.(7z|zip)\.\d{3}$', '', path) if number else path)
        group = groups.setdefault(stem, {'files': [], 'numbers': []})
        if any(item['path'] == path for item in group['files']):
            continue
        group['files'].append({'path': path, 'name': name, 'size_bytes': int(row.get('size') or 0)})
        if number:
            group['numbers'].append(number)
    result = []
    for stem, group in groups.items():
        numbers = sorted(group['numbers'])
        complete = all(item['size_bytes'] > 0 for item in group['files']) and (
            not numbers or numbers == list(range(1, max(numbers) + 1)))
        result.append({
            'id': hashlib.sha256(stem.encode()).hexdigest()[:24], 'rjcode': rjcode,
            'name': posixpath.basename(stem), 'path': stem,
            'files': sorted(group['files'], key=lambda item: item['path']),
            'size_bytes': sum(item['size_bytes'] for item in group['files']),
            'complete': complete, 'multipart': bool(numbers),
        })
    return result


class ResourceSourceService:
    def __init__(self):
        self._worker = None
        self._inflight = {}
        self._enqueued = {}
        self._queue_tasks = set()
        self._client = None
        self._notification_guard = threading.Lock()
        self._pending_notifications = {}
        self._notification_timer = None

    def schedule_circle(self, circle_id):
        if self._worker is None or self._worker.done():
            return
        if self._enqueued.get(circle_id, 0) > time.monotonic():
            return
        self._enqueued[circle_id] = time.monotonic() + 60
        async def enqueue():
            try:
                await asyncio.to_thread(self.enqueue_circle, circle_id)
            except Exception:
                self._enqueued.pop(circle_id, None)
                import logging
                logging.getLogger(__name__).exception('YAAS 社团探测入队失败')
        task = asyncio.create_task(enqueue())
        self._queue_tasks.add(task)
        task.add_done_callback(self._queue_tasks.discard)

    def decorate_items(self, db, items):
        codes = {code for item in items for code in item.get('resource_probe_rjcodes',
                 [item.get('canonical_rjcode'), item.get('display_rjcode')]) if code}
        states = {row.rjcode: row for row in db.query(ResourceSourceProbe).filter(
            ResourceSourceProbe.source == SOURCE, ResourceSourceProbe.probe_version == VERSION,
            ResourceSourceProbe.rjcode.in_(codes)).all()} if codes else {}
        for item in items:
            item_codes = list(dict.fromkeys(item.get('resource_probe_rjcodes',
                [item.get('canonical_rjcode'), item.get('display_rjcode')])))
            hits = [code for code in item_codes if code in states and any(
                group.get('complete') for group in states[code].candidates or [])]
            item['resource_sources'] = ([{'id': 'asmr.one', 'label': 'asmr.one'}] if item.get('has_asmr_one') else [])
            if hits:
                item['resource_sources'].append({'id': SOURCE, 'label': 'YAAS', 'rjcodes': hits})
            item['has_downloadable_source'] = bool(item['resource_sources'])
            item['yaas_probe_status'] = 'hit' if hits else ('pending' if any(
                code not in states or states[code].status == 'pending' for code in item_codes if code)
                else 'error' if any(states[code].status == 'error' for code in item_codes if code in states) else 'missing')
            if hits:
                item['download_plan'] = item.get('download_plan') or {'rjcode': hits[0]}
                item['status_tags'] = [tag for tag in item.get('status_tags', []) if tag != '暂不可下载']
                if '可下载' not in item['status_tags']:
                    item['status_tags'].append('可下载')

    @asynccontextmanager
    async def lease(self, kind, slots=1):
        redis = get_redis_service()
        client = redis.client(required=True)
        token = uuid.uuid4().hex
        key = None
        while key is None:
            for slot in range(slots):
                candidate = redis.key('resource-source', SOURCE, kind, slot)
                if await asyncio.to_thread(client.set, candidate, token, nx=True, ex=90):
                    key = candidate
                    break
            if key is None:
                await asyncio.sleep(.5)

        async def renew():
            while True:
                await asyncio.sleep(25)
                ok = await asyncio.to_thread(client.eval,
                    "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],90) end return 0",
                    1, key, token)
                if not ok:
                    raise RuntimeError('YAAS 调度租约已失效')

        owner = asyncio.current_task()
        heartbeat = asyncio.create_task(renew())
        def on_lease_lost(done):
            if not done.cancelled() and done.exception() is not None:
                owner.cancel('YAAS 调度租约失效，已停止传输')
        heartbeat.add_done_callback(on_lease_lost)
        try:
            yield
            if heartbeat.done():
                heartbeat.result()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await asyncio.to_thread(client.eval,
                "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
                1, key, token)

    async def pace(self, kind='metadata', interval=.34):
        redis = get_redis_service()
        client = redis.client(required=True)
        key = redis.key('resource-source', SOURCE, kind, 'pace')
        while not await asyncio.to_thread(client.set, key, '1', nx=True, px=int(interval * 1000)):
            await asyncio.sleep(.1)
        cooldown = await asyncio.to_thread(client.pttl, redis.key('resource-source', SOURCE, 'cooldown'))
        if cooldown > 0:
            await asyncio.sleep(min(cooldown / 1000, 60))
            return await self.pace(kind, interval)

    async def cooldown(self, seconds):
        redis = get_redis_service()
        client = redis.client(required=True)
        await asyncio.to_thread(client.eval,
            "local ttl=redis.call('pttl',KEYS[1]); if ttl<tonumber(ARGV[1]) then return redis.call('psetex',KEYS[1],ARGV[1],'1') end return 0",
            1, redis.key('resource-source', SOURCE, 'cooldown'), max(1000, int(seconds * 1000)))

    async def request(self, endpoint, payload):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=40, follow_redirects=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=60))
        client = self._client
        for attempt in range(4):
            await self.pace()
            response = await client.post(BASE_URL + '/api/fs/' + endpoint, json=payload)
            if response.status_code in {429, 503}:
                retry = response.headers.get('Retry-After', '')
                try:
                    seconds = int(retry) if retry.isdigit() else parsedate_to_datetime(retry).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    seconds = 5 * 2 ** attempt
                await self.cooldown(max(1, min(seconds, 3600)))
                continue
            response.raise_for_status()
            body = response.json()
            if body.get('code') in {429, 503}:
                await self.cooldown(5 * 2 ** attempt)
                continue
            if body.get('code') != 200:
                reason = re.sub(r"https?://[^\s\"'<>]+", "[YAAS 下载地址]",
                    str(body.get('message') or '源站未提供错误原因'))
                reason = ' '.join(reason.split())[:500]
                raise ResourceSourceError(
                    f"YAAS 接口 {endpoint} 失败（状态码 {body.get('code')}）：{reason}")
            return body.get('data') or {}
        raise ResourceSourceError('YAAS 限流，请稍后重试')

    def cached(self, rjcode):
        with SessionLocal() as db:
            row = db.get(ResourceSourceProbe, (SOURCE, normalize_rj(rjcode), VERSION))
            if row is None:
                return {'status': 'pending', 'candidates': [], 'error': '', 'fresh': False}
            return {'status': row.status, 'candidates': row.candidates or [], 'error': row.error,
                    'checked_at': row.checked_at.isoformat() if row.checked_at else None,
                    'fresh': bool(row.expires_at and row.expires_at > datetime.now())}

    def _save(self, rjcode, *, status, candidates, error='', ttl=300):
        with SessionLocal() as db:
            old = db.get(ResourceSourceProbe, (SOURCE, rjcode, VERSION))
            changed = old is None or (old.status, old.candidates or [], old.error or "") != (status, candidates or [], error or "")
            values = dict(source=SOURCE, rjcode=rjcode, probe_version=VERSION, status=status,
                          candidates=candidates, error=error, checked_at=datetime.now(),
                          expires_at=datetime.now() + timedelta(seconds=ttl))
            db.execute(insert(ResourceSourceProbe).values(**values).on_conflict_do_update(
                index_elements=['source', 'rjcode', 'probe_version'], set_=values))
            db.commit()
        if not changed:
            return
        try:
            self.notify_circles(rjcode)
        except Exception:
            logging.getLogger(__name__).exception('YAAS 探测结果已保存，社团视图通知失败')

    def notify_circles(self, code):
        from ..models.database import CircleWork
        with SessionLocal() as db:
            circles = db.query(CircleWork.circle_id).filter(
                (CircleWork.canonical_rjcode == code) | (CircleWork.display_rjcode == code) |
                cast(CircleWork.linked_rjcodes, JSONB).contains([code])).distinct().all()
        with self._notification_guard:
            for (circle_id,) in circles:
                self._pending_notifications.setdefault(circle_id, set()).add(code)
            if self._pending_notifications and self._notification_timer is None:
                self._notification_timer = threading.Timer(.5, self.flush_notifications)
                self._notification_timer.daemon = True
                self._notification_timer.start()

    def flush_notifications(self):
        from .circle_completion_service import get_circle_completion_service
        from .realtime_event_service import broadcast_event
        with self._notification_guard:
            pending = self._pending_notifications
            self._pending_notifications = {}
            timer = self._notification_timer
            self._notification_timer = None
            if timer is not None:
                timer.cancel()
        for circle_id, codes in pending.items():
            try:
                version = get_circle_completion_service().invalidate_completion_resource_cache(circle_id)
                broadcast_event({'type': 'circle.resource_source.changed', 'domain': 'circle_completion',
                                 'payload': {'circle_id': circle_id, 'source': SOURCE,
                                             'rjcodes': sorted(codes), 'version': version}})
            except Exception:
                logging.getLogger(__name__).exception('合并资源通知失败 circle=%s', circle_id)

    async def probe(self, rjcode, refresh=False):
        rjcode = normalize_rj(rjcode)
        if await asyncio.to_thread(self._is_unreleased, rjcode):
            return {'status': 'skipped', 'skip_reason': 'unreleased', 'candidates': [], 'fresh': False}
        if not refresh:
            old = await asyncio.to_thread(self.cached, rjcode)
            if old['fresh']:
                return old
        if rjcode in self._inflight:
            return await asyncio.shield(self._inflight[rjcode])

        async def run():
            async with self.lease('probe-' + rjcode):
                old = await asyncio.to_thread(self.cached, rjcode)
                if old['fresh'] and not refresh:
                    return old
                try:
                    rows = []
                    for root in ROOTS:
                        page = 1
                        while True:
                            data = await self.request('search', dict(parent=root, keywords=f'"{rjcode}"',
                                scope=0, page=page, per_page=100, password=''))
                            content = data.get('content')
                            if not isinstance(content, list):
                                raise ValueError('YAAS 搜索响应缺少完整结果')
                            rows.extend(content)
                            if len(content) < 100 or (data.get('total') is not None and page * 100 >= int(data['total'])):
                                break
                            page += 1
                            if page > 1000:
                                raise ValueError('YAAS 搜索分页异常')
                    # 搜索索引可能漏分卷；按命中目录完整枚举后再组包。
                    for parent in sorted({posixpath.dirname(public_path(str(row.get('parent') or '').rstrip('/') + '/' + str(row.get('name') or '')))
                                          for row in rows if not row.get('is_dir')
                                          and any(str(row.get('parent') or '').removeprefix('/guest').startswith(root + '/') for root in ROOTS)}):
                        page = 1
                        while True:
                            listing = await self.request('list', dict(path=parent, password='', page=page, per_page=100, refresh=False))
                            content = listing.get('content')
                            if not isinstance(content, list):
                                raise ValueError('YAAS 分卷目录校验失败')
                            rows.extend({**row, 'parent': parent} for row in content)
                            if len(content) < 100 or (listing.get('total') is not None and page * 100 >= int(listing['total'])):
                                break
                            page += 1
                            if page > 1000:
                                raise ValueError('YAAS 目录分页异常')
                    candidates = package_groups(rows, rjcode)
                    await asyncio.to_thread(self._save, rjcode, status='hit' if candidates else 'missing',
                        candidates=candidates, ttl=86400 if candidates else 21600)
                except Exception as exc:
                    await asyncio.to_thread(self._save, rjcode, status='error',
                        candidates=old['candidates'], error='YAAS 探测失败，请稍后重试')
                return await asyncio.to_thread(self.cached, rjcode)

        task = asyncio.create_task(run())
        self._inflight[rjcode] = task
        task.add_done_callback(lambda done: self._inflight.pop(rjcode, None))
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._inflight.pop(rjcode, None)

    async def candidates_for(self, rjcode):
        from .circle_completion_service import get_circle_completion_service
        service = get_circle_completion_service()
        info = await service.resolve_canonical_rj(normalize_rj(rjcode))
        return await service._build_public_download_probe_candidates(info, rjcode)

    async def plan(self, rjcode, refresh=False, *, exact=False):
        rjcode = normalize_rj(rjcode)
        codes = [rjcode] if exact else await self.candidates_for(rjcode)
        from .dlsite_service import get_dlsite_service
        from .asmr_download_service import ASMRDownloadService
        linked_works = {} if exact else await get_dlsite_service().get_linked_works(rjcode)
        resources, states = [], []
        for code in codes:
            state = await self.probe(code, refresh=refresh)
            states.append({'rjcode': code, **state})
            for group in state['candidates']:
                work = linked_works.get(code)
                language = str(getattr(work, 'lang', '') or '').strip()
                group = {**group, 'language': language,
                    'language_tag': ASMRDownloadService._language_label(language),
                    'work_type': getattr(work, 'work_type', ''),
                    'title': getattr(work, 'title', '')}
                resources.append({**group, 'source': SOURCE, 'resource_type': 'archive',
                    'relative_path': group['path'], 'selected': False,
                    'match_status': 'uninspected_archive', 'requested_rjcode': rjcode})
        # 只有单一候选才默认选中，多包/多版本必须明确选择。
        if len(resources) == 1 and resources[0]['complete']:
            resources[0]['selected'] = True
        from .http_download_service import get_http_download_service
        downloader = get_http_download_service()
        for resource in resources:
            stem, ext = downloader._split_custom_archive_filename(resource['name'])
            resource['download_name'] = downloader._filename_with_extract_password(stem, ARCHIVE_PASSWORD, ext)
        return dict(success=True, source_provider=SOURCE, rjcode=rjcode, title=rjcode,
            session_id=f'{SOURCE}:{rjcode}', selectable_resources=resources, probe_states=states,
            download_root=downloader._download_root(),
            summary={'selectable_total': len(resources)}, grouped_resources=[])

    async def resolve_file(self, path, *, subtitle_only=False):
        if subtitle_only:
            from .yaas_subtitle_service import subtitle_path
            path = subtitle_path(path)
        else:
            path = public_path(path)
        data = await self.request('get', {'path': path, 'password': ''})
        url = str(data.get('raw_url') or '')
        from .http_download_service import get_http_download_service
        downloader = get_http_download_service()
        # landing 节点的跳转直接交给 aria2 实测会返回 403；先以单字节请求
        # 取得最终 CDN 地址，再交 aria2。每一跳都限速、校验域名与公网地址。
        async with httpx.AsyncClient(timeout=40, follow_redirects=False,
                proxy=downloader._proxy_url(SOURCE) or None) as client:
            for _ in range(6):
                parts = urlsplit(url)
                if parts.scheme != 'https' or not (parts.hostname or '').endswith('.imoutoheaven.org'):
                    raise ResourceSourceError('YAAS 返回了非预期下载地址')
                await downloader.validate_url(url)
                await self.pace()
                async with client.stream('GET', url, headers={'Range': 'bytes=0-0'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get('location')
                        if not location:
                            raise ResourceSourceError('YAAS 下载节点缺少跳转地址')
                        url = urljoin(url, location)
                        continue
                    if response.status_code in {429, 503}:
                        await self.cooldown(30)
                        continue
                    if response.status_code not in {200, 206}:
                        raise ResourceSourceError(f'YAAS 下载节点返回 HTTP {response.status_code}')
                    return {'url': url, 'size_bytes': int(data.get('size') or 0),
                            'filename': posixpath.basename(path)}
        raise ResourceSourceError('YAAS 下载节点跳转或限流次数过多，请稍后重试')

    async def combine_plan(self, rjcode, asmr_builder, refresh=False, *, exact=False):
        """旧客户端仍可只调原计划；新客户端显式请求两个来源。"""
        options, errors = [], []
        sources = ['asmr.one', SOURCE]
        # 两个来源互不依赖，同时查询，仍按固定顺序展示与汇总错误。
        results = await asyncio.gather(
            asmr_builder(), self.plan(rjcode, refresh=refresh, exact=exact),
            return_exceptions=True,
        )
        for source, plan in zip(sources, results):
            try:
                if isinstance(plan, BaseException):
                    raise plan
                if plan and (plan.get('selectable_resources') or plan.get('filtered_out_resources')) and (source != SOURCE or any(
                        row.get('complete') for row in plan['selectable_resources'])):
                    options.append({**plan, 'source_provider': source})
                elif source == SOURCE and plan:
                    errors.extend(row['error'] for row in plan.get('probe_states', []) if row.get('error'))
                elif source == 'asmr.one' and plan:
                    errors.append('asmr.one：当前作品及关联版本没有可下载文件（或文件已被当前规则过滤）')
            except Exception as exc:
                errors.append(f'{source}: {exc}')
        if not options:
            raise ValueError('；'.join(errors) or f'{rjcode} 没有可下载来源')
        result = dict(options[0])
        result['source_options'] = options
        result['source_errors'] = errors
        result['source_selection_required'] = len(options) > 1
        return result

    async def validate_item(self, item):
        """只信任服务端缓存里的完整候选，不接受客户端伪造路径和分卷。"""
        download_root = str(item.get('download_base_path') or '').strip()
        if download_root and not os.path.isabs(download_root):
            raise ValueError('YAAS 保存目录必须是服务器上的绝对路径')
        requested = normalize_rj(item.get('rjcode') or item.get('requested_rjcode'))
        plan = await self.plan(requested, exact=True)
        selected = {str(row.get('id') or '') for row in item.get('selected_resources') or []}
        groups = [row for row in plan['selectable_resources'] if row['id'] in selected]
        if (len(groups) != 1 or len(selected) != 1 or not groups[0]['complete']
                or normalize_rj(groups[0].get('rjcode')) != requested):
            raise ValueError(f'{requested} 请选择一个完整资源包或分卷组')
        return requested, groups[0]

    @staticmethod
    def validate_asmr_session(item):
        from ..models.database import ASMRDownloadSession
        requested = normalize_rj(item.get('rjcode'))
        with SessionLocal() as db:
            session = db.get(ASMRDownloadSession, item.get('session_id'))
            if session is None or normalize_rj(session.rjcode) != requested:
                raise ValueError('下载会话与目标 RJ 不一致')
            allowed = [row for row in session.selected_resources or [] if row.get('remote_url')]
        selected = item.get('selected_resources') or []
        if not selected:
            raise ValueError('未选择下载文件')
        for row in selected:
            matches = [original for original in allowed
                       if str(row.get('remote_url') or '') == str(original.get('remote_url'))
                       and row.get('file_name') == original.get('file_name')
                       and row.get('relative_path') in {original.get('relative_path'), original.get('file_name')}]
            original = next((candidate for candidate in matches
                             if candidate.get('relative_path') == row.get('relative_path')), next(iter(matches), None))
            if original and original.get('source_workno') and normalize_rj(original['source_workno']) != requested:
                raise ValueError('会话资源与目标 RJ 不一致')
            if not original or any(row.get(key) != original.get(key) for key in ('checksum_md5', 'size_bytes', 'file_name', 'source_workno')):
                raise ValueError('选中文件不属于当前 RJ 下载会话')
            # 允许前端的扁平路径选择，文件来源始终以服务端会话为准。
            path = row.get('relative_path')
            if path not in {original.get('relative_path'), original.get('file_name')}:
                raise ValueError('下载文件路径与预览不一致')
            row.clear()
            row.update(original, relative_path=path, selected=True)

    async def validate_batch(self, items):
        """整个批次先校验来源与选择，防止后面的非法条目导致前半批已入队。"""
        validated = {}
        if any((item.get('source_provider') or 'asmr.one') not in {'asmr.one', SOURCE} for item in items):
            raise ValueError('未知下载来源')
        for index, item in enumerate(items):
            provider = item.get('source_provider') or 'asmr.one'
            if provider not in {'asmr.one', SOURCE}:
                raise ValueError('未知下载来源')
            if provider == SOURCE:
                validated[index] = await self.validate_item(item)
            elif not item.get('rjcode') or not item.get('session_id') or not item.get('selected_resources'):
                raise ValueError('asmr.one 下载项缺少 RJ、会话或选中资源')
            else:
                await asyncio.to_thread(self.validate_asmr_session, item)
        return validated

    async def submit(self, item, source_page, context=None, validated=None):
        from .task_engine import Task, TaskType, get_task_engine
        requested, group = validated or await self.validate_item(item)
        tasks = []
        for file in group['files']:
            path = public_path(file['path'])
            task = Task(task_type=TaskType.HTTP_DOWNLOAD, source_path=requested, rjcode=group['rjcode'], metadata={
                **dict(context or {}), 'rjcode': group['rjcode'], 'requested_rjcode': requested,
                'resource_group_id': group['id'], 'work_title': item.get('work_title') or requested,
                'resource_source': SOURCE, 'yaas_path': path, 'yaas_size': file['size_bytes'],
                'urls': [BASE_URL + '/d' + quote(path, safe='/')],
                'target_subdir': '',
                'download_base_path': str(item.get('download_base_path') or '').strip(),
                'conflict_policy': 'resume', 'download_mode': SOURCE, 'source_modes': [SOURCE],
                'task_domain': 'circle_completion' if source_page == 'circle-completion' else 'http_download', 'task_kind': TaskType.HTTP_DOWNLOAD.value,
                'source_page': source_page, 'source_action': 'yaas_download',
                'source_label': f"YAAS · {requested} · {file['name']}",
                'business_key': f"{SOURCE}:{hashlib.sha256(path.encode()).hexdigest()}",
                'archive_password_hint': ARCHIVE_PASSWORD,
                'http_download_auto_retry_limit': 2,
            })
            await get_task_engine().submit(task)
            tasks.append({'task_id': task.id, 'rjcode': requested, 'source_provider': SOURCE})
        return tasks

    def _is_unreleased(self, rjcode):
        from ..models.database import WorkMetadata
        with SessionLocal() as db:
            row = db.query(WorkMetadata.release_date).filter(WorkMetadata.rjcode == rjcode).first()
            return bool(row and is_unreleased(row.release_date))

    def enqueue_circle(self, circle_id):
        from ..models.database import CircleWork
        from ..models.database import WorkMetadata
        with SessionLocal() as db:
            codes = set()
            for row in db.query(CircleWork.canonical_rjcode, CircleWork.display_rjcode,
                                CircleWork.linked_rjcodes).filter(CircleWork.circle_id == circle_id):
                codes.add(row.canonical_rjcode)
                codes.add(row.display_rjcode)
                codes.update(row.linked_rjcodes or [])
            unreleased = {
                row.rjcode for row in db.query(WorkMetadata).filter(
                    WorkMetadata.rjcode.in_(codes - {None})
                ).all() if is_unreleased(row.release_date)
            }
            values = [dict(source=SOURCE, rjcode=code, probe_version=VERSION,
                           status='pending', candidates=[], error='') for code in sorted(codes - {None} - unreleased)
                      if re.fullmatch(r'RJ\d{6,8}', str(code or ''))]
            for offset in range(0, len(values), 500):
                db.execute(insert(ResourceSourceProbe).values(values[offset:offset + 500]).on_conflict_do_nothing())
            db.commit()

    def pending_codes(self):
        from ..models.database import WorkMetadata
        with SessionLocal() as db:
            query = db.query(ResourceSourceProbe.rjcode, WorkMetadata.release_date).outerjoin(
                WorkMetadata, WorkMetadata.rjcode == ResourceSourceProbe.rjcode
            ).filter(
                ResourceSourceProbe.source == SOURCE,
                ResourceSourceProbe.probe_version == VERSION,
                (ResourceSourceProbe.expires_at.is_(None)) |
                (ResourceSourceProbe.expires_at < datetime.now()),
            ).order_by(ResourceSourceProbe.checked_at.asc().nullsfirst(), ResourceSourceProbe.rjcode)
            result, offset = [], 0
            while len(result) < 20:
                rows = query.offset(offset).limit(100).all()
                result.extend((row.rjcode,) for row in rows if not is_unreleased(row.release_date))
                if len(rows) < 100:
                    break
                offset += 100
            return result[:20]

    async def worker(self):
        while True:
            try:
                rows = await asyncio.to_thread(self.pending_codes)
                for offset in range(0, len(rows), 2):
                    await asyncio.gather(*(self.probe(code) for (code,) in rows[offset:offset + 2]))
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception('YAAS 后台探测失败')
                await asyncio.sleep(30)

    def start(self):
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self.worker(), name='yaas-source-probe')

    async def stop(self):
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        for task in [*self._queue_tasks, *self._inflight.values()]:
            task.cancel()
        await asyncio.gather(*self._queue_tasks, *self._inflight.values(), return_exceptions=True)
        await asyncio.to_thread(self.flush_notifications)
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_service = ResourceSourceService()


def get_resource_source_service():
    return _service
